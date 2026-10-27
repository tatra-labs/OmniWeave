# D7-structure — the systems proposal

## Headline

**One knowledge model, `owgraph`, living in the same `.owstore` as `owdoc`, in which the
deterministic/LLM distinction is not a pipeline mode but a per-row invariant enforced by a `CHECK`
constraint — `method = LLM` may never carry `trust = EXTRACTED` — and in which `mention(entity_id,
block_id, ts_a, ts_b)` is the single bridge between the entity space and the block space, so every
edge reaches a polygon on a page by construction, entity resolution is an append-only, reversible,
order-independent merge log rather than a destructive union-find, communities are re-clustered
always and re-reported only where `member_digest` changed, and incremental extraction is held to
byte-equality with a full rebuild by a CI gate.**

---

## 0. Conformance with the binding rulings, and one flagged conflict

I use, verbatim and without amendment: D2's `block_id` / `addr` / `cite` identity split, `TextSpan`,
`OriginSpan`, `Quad`, `Trust`, `Method`, `Producer`/`producer_id`, `origin_operator`, `Diag`, the
`.owstore` pragma order, the `IFNULL`-sentinel rule for nullable natural keys, and D2's ruling that
"L3 (D7) may not put containment or intra-document references in its own tables. The seven `rel`
kinds are L2's; entity, claim, community and cross-document edges are D7's and key on `block_id`."
I use D3's five Ports (structure extractors are `derive/1` drivers, `granularity ∈
{document, corpus}`), D3's card, `RejectCode`, `DriverIO`, `resolve()`, and `omniweave-conform`. I
use D4's `Rung.ENRICH`, its `Lane` open registry, `Spend`/`PriceBook`/`CostCard`, `evaluate()` /
`admit()` separation, `route_decision.decision_id`, and D4's consequence "D6/D7 … get `decision_id`
on every block". I use D1's distribution `omniweave-graph`, the `<port>.<family>.<impl>` registry
grammar, `min(tenant_cap, MAX_*)` limits, and the gate-not-discipline enforcement style.

**Where D1 and D3 disagree on driver mechanics** (D1: `omniweave-driver.toml`, kind vocabulary
including `structure`; D3: `driver.toml`, five Ports with `structure` explicitly rejected in favour
of `derive`), I follow **D3** as the later and more specific ruling, which D1 anticipated ("D3 owns
the manifest's capability fields"). I do not re-open it.

### Two questions the rulings explicitly delegated to D7, settled here

- **D2 open question: "Should L3 entity spans live in `mark` or in a separate annotation table?"** —
  **Separate table (`mention`).** D2's own test applies: a mention carries its own `producer_id`,
  `method`, `trust`, `score`/`score_kind`, `origin_operator`, `taint`, `decision_id` and a derived
  `quad`. That is not "a pointer with a label"; `mark` would absorb it at very much more than zero
  cost, and it would put L3 provenance inside an L2 table.
- **D1 open question: "Does `omniweave-graph`'s dependency on `graphrag-chunking` earn its Python
  ceiling?"** — **No. Drop it.** Verified in-tree: the whole distribution is **388 lines** of Python
  (`_collections/graphrag/packages/graphrag-chunking/graphrag_chunking/`, `wc -l` over the package,
  tests excluded). `TokenChunker` (`token_chunker.py`, 69 lines) is a sliding token window that
  knows nothing about blocks and would split a table cell in half, destroying `block_id`
  attribution. `SentenceChunker` (`sentence_chunker.py`) calls
  `bootstrap()` → `nltk.download("punkt")` — **a network fetch at first use**, which violates D1's
  gate G15 and D3's `needs_network = false` posture — and imports `nltk`, which is **not in that
  package's declared dependencies** (`pyproject.toml:32-35` is `graphrag-common==3.1.2`,
  `pydantic~=2.13` and nothing else), so it is a latent `ImportError` on a clean install. Dropping it
  removes `pydantic` from `omniweave-graph`'s closure and removes the `<3.14` CPython ceiling D1
  inherited from it. `omniweave-graph`'s third-party dependency set becomes **`tree-sitter` only**.

### CONFLICT — D4, one clause, one-sentence amendment

D4 §Spec, first paragraph, states verbatim:

> "**The unit of decision is the part** (page / slide / sheet / track), identical to the `work`
> table's `unit_part` (`mine-runtime.md` §7.3.1)"

and its Consequences state:

> "**`mine-runtime.md` §7.12 open question 1 is settled**: the router's decision grain and the
> `work` row's identity are the same thing, always."

D2 pairs with this: "The `work` table's unit is `(unit_uri, unit_part=page)` for parse and
`(unit_uri, unit_part=NULL)` for document-level structure."

**Why this is a defect for D7 specifically.** Structure extraction's natural unit is a **Segment** —
a heading-scoped, table-atomic, ~1,200-token run of Blocks that routinely spans a page break and is
routinely many-per-page. Under the clause as written, a 500-page 10-K is *one* routing decision
covering ~40,000 segments. Three consequences, all bad and none recoverable later: `budget.per_part`
(6,000 micros, 3 calls) is applied to the whole document, so the runaway guard is a no-op on exactly
the workload that runs away; `route_spend` has no per-segment attribution, so `agree`/`audit`/`tune`
cannot learn a threshold for extraction at all; and `route_decision`'s UNIQUE index on
`(content_digest, unit_part, lane, rung, …)` collapses 40,000 distinct cache decisions into one row,
so the D4 ledger cannot see the extraction cache's hit rate — the single number that determines the
LLM bill.

**Minimum amendment (does not touch D4's DDL, which already types `unit_part TEXT NOT NULL DEFAULT
''`):** replace "always" with a declared-partition rule —

> The unit of decision is the part. For `parse`, `ocr` and `vlm` lanes the part is the page / slide /
> sheet / track. A `derive` stage whose card declares `granularity ∈ {document, corpus}` MAY declare
> its own sub-unit, which MUST partition the unit, MUST be a stable content-derived string, and MUST
> be recorded in `route_decision.unit_part`. The `graph` lane's sub-unit is
> `"seg:" || hex(segment.content_digest)[:16]`.

`Lane` is already "an open registry" in D4, so adding `graph` needs no amendment. If the judge
refuses the amendment, the fallback is a second ledger inside `omniweave-graph` (the `extraction`
table below already carries `spend_micros`/`tokens`), and the cost is that extraction spend becomes
invisible to `ow route explain`, `tune.py` and the pricebook reconciliation — i.e. D4's honesty
mechanism stops covering the most expensive stage in the framework. I would rather amend.

---

## 1. The design

### 1.1 Why there is no mode switch, stated as a mechanism

graphrag ships two pipelines over one schema (`Standard` with `extract_graph`, `Fast` with
`extract_graph_nlp` + `prune_graph`; `index/workflows/factory.py:52-96`) and that is already better
than two subsystems — but it makes the *corpus* have a vintage. A user holding a fact cannot ask
"did this cost money, and may I trust it?" without knowing which pipeline ran. graphify goes the
other way and puts the answer on the row (`confidence ∈ {EXTRACTED, INFERRED, AMBIGUOUS}`,
`validate.py:4-8`) but has no spatial provenance and no producer identity, and its reader defaults a
missing confidence to `EXTRACTED` (`callflow_html.py:210-217`) — the strongest tier, which is
backwards.

omniweave puts the answer on the row and makes the asymmetry a schema property:

```sql
CHECK (NOT (method = 6 AND trust = 2))   -- METHOD_LLM may NEVER be EXTRACTED
```

on both `mention` and `edge` (`6` is `enum_val('method','llm').ord`; a unit test asserts the integer,
so a reordering of D2's `Method` enum fails the build rather than silently disabling the constraint).
The corollary is the whole ordering policy:

- **Deterministic extractors write first**, and they are the only writers that may produce
  `trust = EXTRACTED`.
- **The LLM extractor writes second, and is reconciled, never blind-inserted.** An LLM-emitted node
  whose `normalize_key(surface)` matches an existing entity or alias becomes a **mention on that
  entity**; it never mints a second node. An LLM-emitted edge duplicating an existing
  `(src, dst, rel, observed_block)` increments `corroborations` and **cannot raise `trust`** —
  graphify's "alias recovery is not provenance" (`build.py:205-231`) generalised to
  *corroboration is not promotion*.
- **The router decides whether the paid tier runs at all**, per segment, at `Rung.ENRICH`, on free
  signals. Not a flag.

So "deterministic-first" is not an ordering convention that a future contributor can invert. It is
(a) a `CHECK`, (b) a reconciliation function with a property test, and (c) a D4 rung.

### 1.2 The model — one Block space, one Entity space, one bridge

D2 owns block↔block. I own entity↔entity. The bridge is `mention`, and:

> **Invariant G7-BRIDGE: `mention` is the only table in the framework whose rows reference both a
> `block_id` and an `entity_id`.** Enforced by a schema lint over the DDL (every FK's target table is
> classified L2 or L3; a table with FKs into both fails unless it is named `mention`).

That one rule is what keeps L2 and L3 from growing a sync layer, and it is what makes the
polygon question answerable in one join path (§1.5).

`Segment` is the extraction unit and it is not a second representation of blocks: it is a grouping
with its own durable id and its own merkle digest over member `block.content_digest`s, plus
`heading_path`. `segment_block` has `PRIMARY KEY (block_id)` — **a block belongs to exactly one
segment, and overlap is unrepresentable**. I reject sliding-window overlap outright: overlap
duplicates mentions across units and then forces mention-level dedup, which is a second entity
resolution problem you created yourself. Boundary entities are handled by handing the LLM the
neighbouring segments' first/last 200 characters inside a `<context>` block that is explicitly
non-extractable, and by the span-verification rule (§1.7) which will reject a mention pointing
outside the segment.

The seven graphrag types map without loss and with three corrections:

| graphrag | owgraph | correction |
|---|---|---|
| `Document` | D2's `doc` | already exists; L3 adds nothing |
| `TextUnit` | `segment` | structural, not token-sliding; `Identified` not `Named` (graphrag §1.1) — kept: a segment has a `cite`, no title |
| `Entity` | `entity` + `alias` + `mention` | edges key on `entity_id`, **never on an uppercased title** (`graph_extractor.py:139-141` `clean_str(x.upper())` is why graphrag's whole resolution is `groupby("title")` and why spelling drift splits a node) |
| `Relationship` | `edge` | + `observed_block` (graphify's `source_file` on edges), + `role` (reifies a hyperedge without a hyperedge table) |
| `Covariate` | `edge` with `object_literal`/`valid_from`/`valid_to`/`claim_status` | graphrag's covariate columns are the best temporal-fact schema in the collection and they are the *same shape* as a relationship; two tables would drift |
| `Community` | `community` + `community_member` | `level` is INTEGER (graphrag's is `str` and `index/update/communities.py:52` does `.astype(int)` — type drift across the seam); parent is `NULL`, not `-1` |
| `CommunityReport` | `community_report` | + `coverage`, + `member_digest` at generation time, + `taint` |

`Community.level` as INTEGER and `parent = NULL` are small, but they are exactly the kind of thing
that is unfixable in year three.

### 1.3 Deterministic extraction that is actually deterministic — six extractors

The usual objection to "deterministic-first" for documents is that documents have no AST. That is
false for the formats that matter, and the evidence is in the decoder D1 already ships:

- **`derive.graph.spine`** — headings, sections, TOC entries and figure/table containers from
  `block.kind` / `parent_id` / `ord`. `anydoc/src/formats/docx/content.rs:238-248` resolves
  `w:outlineLvl` (including the `9 = off` sentinel) through the style chain; `styles.rs:93-115` does
  the inheritance. Free, exact, `trust = EXTRACTED`, `method = native_xml`.
- **`derive.graph.anchor`** — author-declared cross-references. `content.rs:407-452` resolves
  `w:hyperlink` to a `LinkTarget`; `shared/fields.rs:84-130` parses the `HYPERLINK` field including
  `\l "sec2"` internal anchors and `"…" \l "frag"` (tests at `:154-210`); `content.rs:431`/`:711`
  handles `bookmarkStart` and keeps a bookmark-only paragraph's anchor. On PDF: `/Annots` link
  annotations, named destinations and the outline tree. These are **real edges the author wrote
  down**, and no LLM in the collection extracts them because every parser in the collection has
  already thrown them away.
- **`derive.graph.label`** — numbered captions, `§4.2`, `Table 3`, `Figure 7`, `[12]`,
  `(Smith 2020)`, equation numbers, defined-term definitions (`"Agreement" means …`). Mints
  `entity(type=label|defined_term)` and, on a miss, an `unresolved_ref` row.
- **`derive.graph.kv`** — form fields (`Kind.FORM_FIELD`, `KEY_VALUE`, `CHECKBOX`) and table
  header→cell claims via D2's `Grid.top_heading(c)` / `left_heading(r)` (which D2 guarantees O(1)).
  A row of a financial table becomes `edge(src=row-key entity, rel=has_value,
  object_literal=cell text, object_datatype='money:USD', observed_block=cell block_id,
  trust=EXTRACTED)`. **This is the highest-yield document-side deterministic extractor and nobody in
  the collection has it** — graphrag would spend an LLM call per chunk to get worse answers about a
  spreadsheet.
- **`derive.graph.pattern`** — a closed builtin gazetteer (DOI, ISIN, CAS, email, URL, ISO-8601
  dates, currency amounts, statute cites) plus a corpus gazetteer file. `trust = EXTRACTED` only for
  checksum-validated patterns (DOI, ISIN, IBAN); everything else is `INFERRED`.
- **`derive.code.treesitter`** — graphify's extractor family over `Kind.CODE` blocks. Measured
  yield: **~23 nodes and ~49 edges per 1k LOC** (graphify `BENCHMARKS.md`, 689 ERPNext checkpoints,
  ~1M LOC → 22,620 nodes / 48,710 edges over 3,758 files). This is the only place `tree-sitter`
  enters `omniweave-graph`.

Honest limit, stated up front: on a corpus of scanned prose with no OOXML, no tables and no forms,
the free tier yields nearly nothing but the spine. The deterministic yield is **format-dependent and
uneven**, and the router must be able to see that (signal `graph.det_entity_density`).

### 1.4 Confidence, provenance and taint — five axes, zero new enums

Every `mention`, `edge`, `alias`, `entity_merge` and `community_report` row carries:

1. `producer_id` → D2's `producer` row (operator, version, code_fingerprint, model_id, `model_rev`
   as an **exact sha** — `"main"` is a lint error, D2 §8).
2. `method` → D2's `Method` (`native_xml`, `heuristic`, `llm`, `user`, …). codegraph's
   `edges.provenance ∈ {tree-sitter, scip, heuristic}` says *which mechanism*; that is this column
   plus `producer_id`, not a new field.
3. `trust` → D2's `Trust` IntEnum (`AMBIGUOUS=0 < INFERRED=1 < EXTRACTED=2`), `NOT NULL DEFAULT 0`
   so **absent ⇒ weakest**, fixing graphify's `default="EXTRACTED"`. `MIN()` over a set is the set's
   trust, exactly as D2 designed it.
4. `score` + `score_kind`, **nullable together** — a Jaro-Winkler 92 and a token log-probability are
   not comparable and must never be averaged.
5. `origin_operator` verbatim from D2 (ownership, not trust: a free re-extraction may not delete
   billable LLM rows) and `decision_id` from D4 (cost attribution).

Plus one axis that is new here because nothing in the collection has it, and it is the injection
answer:

6. **`taint INTEGER`** — an `IntFlag` bitset, `OR`-propagating up the chain
   mention → entity/edge → community_report:

```
TAINT_UNTRUSTED_SOURCE  = 1<<0   # D4 signal unit.trust_class = untrusted_external
TAINT_SENTINEL_DEFANGED = 1<<1   # the source contained a chat-template control token
TAINT_HIDDEN_TEXT       = 1<<2   # block.layer = hidden, or a white-on-white / <=1pt run
TAINT_OFFSCREEN         = 1<<3   # block.quad lies outside the page media box
TAINT_SPAN_FUZZY        = 1<<4   # span verification passed only on the >=0.95 fuzzy fallback
TAINT_SINGLE_SOURCE_XDOC= 1<<5   # a cross-document assertion with exactly one untrusted witness
```

`resolution_trust` for entities reuses **the same `Trust` enum** (`EXTRACTED` = atomic or exact-key
merge, `INFERRED` = fuzzy merge, `AMBIGUOUS` = LLM-band merge) with `resolution_method` from the same
`Method` enum. Two different questions — "how sure am I this text says X" and "how sure am I this X
is that X" — get two columns and no new vocabulary.

**Three consumers or it rots into decoration** (the digest's rule). `trust`: the retrieval ranking
filter, `ow graph review` (sorted uncertain-first, `AMBIGUOUS < INFERRED < EXTRACTED`, graphify
`analyze.py:413`), and citation rendering (`trust < EXTRACTED` renders hedged, never as a quote).
`taint`: the generation-context filter (a hard exclusion, §1.7), the review queue, and D-serve's
absence contract. `resolution_trust`: the merge-audit CLI, alias display, and the un-merge path.
Enforced weakly (a doc test greps for ≥3 distinct read sites) — I say plainly that this is the
weakest enforcement in the package.

### 1.5 How a graph edge points back to a polygon on a page

One join path, no new coordinate system, and an honest label on the answer:

```
edge --edge_evidence--> mention --> (block_id, ts_a, ts_b)
                                     |
                                     +-- block.quad (D2 Quad: 4 corners, i32 1/1000 pt,
                                     |                topleft, unrotated page)
                                     +-- block.page, block.doc_ord, block.gen
                                     +-- block.os_kind/os_* (the OriginSpan into the container)
```

`mention.quad` is a **derived cache with a declared method**, never an identity:

| driver `Capabilities.spatial` | `mention.quad_method` | meaning |
|---|---|---|
| `char_bbox` | `char_exact` | the polygon is the union of the glyph quads over `[ts_a, ts_b)` |
| `line_bbox` | `line_interp` | the polygon is the intersected line boxes, horizontally interpolated by character fraction |
| `block_bbox`, `page_bbox` | `block_fallback` | the polygon is the whole Block. Say so. |
| `none` | `NULL` | there is no polygon. Do not invent one. |

For an OCR/VLM block, D2's `OriginPixels(page, quad)` means the block's own quad *is* its address, so
`block_fallback` is exact by construction — and the honest label still reads `block_fallback`,
because a downstream highlighter must not assume sub-block precision it does not have.

> **Invariant G7-GEOM: geometry is derived from identity, never part of it.** `mention.quad` and
> `quad_method` are excluded from every digest. A CI gate greps the digest recipes; a property test
> perturbs every `quad` in a fixture store, re-runs `resolve` and `cluster`, and asserts an identical
> canonical projection. This is what makes a pdfium upgrade's bbox jitter unable to orphan an edge —
> the same reasoning D2 used to keep geometry out of `content_digest`.

The re-parse path: D2's `rebind` carries `block_id` when `content_digest` is unchanged, so mentions
survive a driver upgrade for free. When a block is retired (rebind rule 3), its mentions are **not
deleted**: they become `status='orphaned'` and a re-bind pass follows `block_history.superseded_by`;
if that is `NULL` the mention is retired with a reason. Silence is never an option.

### 1.6 Entity resolution — a funnel, and a merge log rather than a mutation

**The structural decision first: resolution is append-only and reversible.** Entities are never
merged destructively. `entity_merge(loser_id, winner_id, method, trust, score, score_kind, guards,
evidence, decided_at_gen, retired_at_gen)` is the decision log; `entity.canonical_id` is a
**materialized, path-compressed pure function of the live rows in that log**, recomputed by an
idempotent `resolve` pass. Un-merging is retiring one row and recomputing one closure.

The alternative — graphify's in-place union-find (`dedup.py`) — is cheaper by one column and
irreversible, and on a growing corpus a merge made with 40 mentions of evidence at generation 3 may
be plainly wrong with 4,000 at generation 40. A knowledge graph is a persistence layer; an
irreversible decision in a persistence layer is a defect regardless of how good the decision usually
is.

The funnel (graphify's `dedup.py`, with a type gate, two new guards, and a cohesion re-check):

1. **Normalize.** `omniweave_graph.ident.normalize_key` — **one function, one module**, with
   graphify's three tested invariants (idempotent, charset-closed, caseless-stable) and its bounded
   6-iteration `NFKC(casefold(...))` fixpoint loop, because the two do not commute (`İ` → `i` +
   U+0307, then NFKC recomposes; graphify #2614) — and `re.UNICODE` on the non-word filter, without
   which every CJK/Cyrillic/Arabic corpus collapses to one node per document (graphify #811).
   Exact `(scope, type, key)` match ⇒ merge, `resolution_trust = EXTRACTED`, free.
2. **Type gate.** Entities of different `entity_type` never merge unless the type registry lists them
   `compatible`. graphrag has no type gate at all. A `type.scope = 'document'` type (e.g. `label`,
   `section`, `party` in a contract corpus) resolves **within a document only**; cross-document
   promotion requires an exact key match *and* ≥2 witnesses (see guard 7g).
3. **Entropy gate** — Shannon ≥ 2.5 bits/char on the normalized label (`dedup.py:242`). `test`, `x1`,
   `aaa` never enter fuzzy matching.
4. **MinHash/LSH blocking** — 128 permutations, threshold 0.7, 3-gram character shingles **with
   spaces stripped** so `graph extractor` and `graphextractor` share shingles (`dedup.py:46-52`).
   Persisted as an on-disk banded table (§2 `lsh_band`), never an in-memory index — 128-perm
   signatures for 10M entities is ~1.3 GB of RAM otherwise.
5. **Jaro-Winkler ≥ 92.0**, with plain Jaro for cross-document labels of length ≥ 12 because
   Winkler's prefix bonus over-fires across documents (`dedup.py:903-907`).
6. **Community boost +5.0** when both are in the same community and `min(len) ≥ 12`. Graph structure
   as evidence for identity: the cheapest possible use of the graph to improve resolution.
7. **Negative guards, applied to BOTH the deterministic and the LLM path** — graphify's discipline
   ("decisively-distinct pairs never reach the LLM", `dedup.py:917-923`), extended:
   a. prefix containment (`Auth` vs `AuthService`) — never merge;
   b. numeric tokens differ (#1284);
   c. content-token swap (#2576);
   d. variant/SKU suffix on labels < 12 chars (`ASR1603` / `M1`);
   e. short labels merge only on a same-length single-character substitution;
   f. **`_label_scope_blocked` (new):** two `type.scope='document'` entities in different `doc_key`s
      never merge — *Figure 3* in doc A is not *Figure 3* in doc B. This is the single most common
      false merge in a document corpus and no code-oriented deduper needs it;
   g. **`_cooccurrence_blocked` (new):** two entities that appear as distinct mentions inside the same
      Segment are *less* likely the same thing — a document saying "X and Y" is asserting they
      differ. Blocks the merge outright below Jaro-Winkler 97.
8. **LLM band `[75, 92)`**, batches of 30, guards re-applied first, admitted by D4's `admit()` and
   charged to the graph lane's budget. `resolution_trust = AMBIGUOUS` on anything it decides.
9. **Cohesion re-check.** After union-find, recompute each cluster member's similarity to the
   survivor and split any member below `_MERGE_THRESHOLD − 10`, recording the split. This kills the
   transitive-chain false merge (A~B 91, B~C 91, A~C 60) that plain union-find creates and that
   nobody in the collection guards against.
10. **Deterministic survivor and deterministic order.** Candidate pairs are processed in the total
    order `(-score, min(key), max(key))`; the survivor is `min` on
    `(merge_hops, -len(alias_set), key)`. A Hypothesis property test shuffles the candidate list 100×
    and asserts an identical `canonical_id` map (**G7-6**).

**Failure modes of resolution, named, with what actually happens:**

- **The god-entity.** 4,000 NDAs, every one naming "the Company". Even with document scoping, an
  exact legal-name match across documents produces a node with 200k mentions; Leiden then puts half
  the corpus in one community and its report is meaningless. **Guard:** `entity.degree` above
  `MAX_ENTITY_DEGREE` (default 4,096, `min(tenant_cap, MAX)`) flips `status='overloaded'`, which
  excludes it from graph expansion and from community membership and emits `OW_GRAPH_OVERLOADED`
  naming the entity. This is graphify's god-node *insight*, not graphrag's `remove_ego_nodes=True`
  blunt delete of the single highest-degree node (`prune_graph.py:44-72`). It is a refusal, not a
  fix, and I am not pretending otherwise.
- **Adversarial alias bridging.** See §1.7 layer 4.
- **A shrinking alias set silently keeping a stale merge.** Handled in §1.8 step 4: merges whose
  evidence mention was deleted are retired and the closure recomputed.

### 1.7 Prompt-injection-carried false entities — five layers, none of them a proof

The threat is qualitatively worse here than at inference time: a graph is a persistence layer, so one
successful injection poisons **every future retrieval**, not one turn. Exactly one repo in the
collection implements a defence (graphify) and exactly one documents an evaluation programme
(graphrag's `RAI_TRANSPARENCY.md`, which also ships the sentence "the system is designed for trusted
users" — disqualifying as a posture for omniweave).

**Layer 1 — wrapping, with the three fixes the risk digest names.** graphify's `_wrap_untrusted`
(`llm.py:581-595`): a hash-stamped `<untrusted_source path="…" sha256="…">` block, the generalised
sentinel regex `<\|[A-Za-z0-9_.\-]{1,64}\|>` (form, not enumeration — the old list missed Llama 3's
`<|start_header_id|>`, graphify #3183), `<<SYS>>`, `[INST]`, and defanging of a **forged closing
delimiter**. Our three required changes: (a) escape the path attribute before interpolation; (b)
**defang a copy** — graphify inserts a zero-width space in place, shifting every later byte offset by
3, and our `TextSpan` offsets are load-bearing, so we keep a `ShiftMap` (a sorted list of insertion
offsets; ~30 lines) and lift every model-returned offset back through it before writing a mention;
(c) **drop the heading-shaped sentinel** `^\s*###?\s*(?:system|instruction)s?\s*:?\s*$`, which matches
`## Instructions` in any manual, RFP or SOP.

**Layer 2 — structural containment. This is the layer that does the real work.** The LLM extractor's
output contract is not "a list of entities"; it is a list of `(surface, a, b, type, …)` where
`[a, b)` indexes **the segment text it was given**. The runner **verifies every one**:
`normalize_k(segment_text[a:b]) == normalize_k(surface)`, with a fuzzy fallback at ratio ≥ 0.95 that
sets `TAINT_SPAN_FUZZY` and caps `trust` at `AMBIGUOUS`. A failure is not an entity — it is a
`quarantine` row with `reason='span_unverified'`. This eliminates the entire class of *"the injected
text instructed the model to emit an entity that is not in the document"*, because the model must
point at bytes that exist. It does **not** eliminate *"the injected text contains the false entity"*
— that is layers 3 and 4.

**Layer 3 — taint, and taint as a hard filter.** Every mention inherits `unit.trust_class` from D4's
connector signal, plus `TAINT_HIDDEN_TEXT` (D2 already gives us `layer = hidden`, and OOXML
white-on-white / ≤1pt runs are the classic DOCX injection carrier), `TAINT_OFFSCREEN` (the quad is
outside the media box), and `TAINT_SENTINEL_DEFANGED` (the source contained a chat-template control
token — strong evidence of intent, and free because layer 1 already found it). Taint `OR`s upward.
**The default policy refuses to place a `TAINT_SENTINEL_DEFANGED | TAINT_HIDDEN_TEXT | TAINT_OFFSCREEN`
fact into a generation context**, and that refusal is a named gate in D-serve's absence contract, not
a warning banner. A warning is a thing nobody reads; a refusal with a named override
(`--allow-tainted <bits>`) is a decision someone makes.

**Layer 4 — cross-document assertions need more than one witness.** The highest-value injection is
not "invent an entity"; it is "assert that *MegaCorp Ltd* is an alias of *MegaCorp Inc*", so the
attacker's claims attach to the victim's node. Therefore: **an alias whose only witness is a single
`untrusted_external` document is never a blocking key for cross-document resolution**, and an edge
crossing a `doc_key` boundary with exactly one untrusted witness is written at
`trust = AMBIGUOUS` with `TAINT_SINGLE_SOURCE_XDOC`. One rule, large blast radius, zero runtime cost.

**Layer 5 — reviewability, and the honest claim.** `ow graph review --taint` lists tainted
assertions sorted uncertain-first, each with its `cite`, its page polygon, and the sha256 of the
source block, so a reviewer can go and look at the pixels. And omniweave ships graphify's own claim
verbatim rather than a stronger one: this *"does not make injection impossible, but changes it from
'works on first try' to 'requires evasion.'"*

Conformance: `omniweave-conform` gains an `injection` suite — a fixture corpus of 40 payloads (DOCX
white text, PDF off-page text, a `<|im_start|>` in a code sample, a forged closing delimiter, a
`## Instructions` heading that must **not** be flagged) asserting zero untainted entities and zero
false positives on the SOP fixture.

### 1.8 Incremental — what recomputes when a document changes

Four steps, in order, and the fourth is a CI gate rather than a claim.

**Step 1 — segment deltas, from digests we already have.** D2's `rebind` reports which blocks
carried, revised and retired. `segment.content_digest = blake3_128(canonical([heading_path,
[b.content_digest …]]))`, so `changed = {s : digest_new ≠ digest_old}`. This is *narrower* than the
document (a typo on page 3 of a 500-page report re-extracts one segment) and *wider* than the block
(a block moving between segments changes both) — correct by construction because it is a merkle.
Note the deliberate over-invalidation: **`heading_path` is a digest input**, so renaming a section
heading re-extracts everything beneath it. That is right — it genuinely changes what the model saw —
and I price it as a failure mode below rather than trading correctness for a cosmetic-edit bill.

**Step 2 — tier-scoped replacement (graphify `build_merge`, `build.py:1652-1680`).** For each changed
segment, delete that segment's contributions **per tier**, where `tier ∈ {det, llm}` is derived from
the driver card's `cost.class` and never self-declared. A deterministic-only re-extraction must not
delete the segment's LLM mentions (graphify #2333/#2336, labelled COEXIST in its source). Deletion of
a whole document is an **explicit prune list**, never inferred — graphrag's `deleted_inputs` is
computed and consumed nowhere (`incremental_index.py:29-58`) and its graph therefore only grows.

**Step 3 — the reference delta. This is what makes incremental *correct* rather than merely fast.**
codegraph's `SyncResult.definitionDelta` (`src/extraction/index.ts:108-132`), transposed to
documents. Document corpora have corpus-scoped resolvable names: **defined terms, section numbers,
figure/table labels, citation keys, bookmark/anchor names, glossary entries**. The `name_def` table
records them per `(doc_ord, gen)`; then

```
name_delta = ⨁_doc  symmetric_difference(name_def[doc, gen_old], name_def[doc, gen_new])
```

computed **per document**, so a name moving between two changed documents does not cancel itself out.
Then two bounded queries, both on partial indexes: every `unresolved_ref` whose `retry_key ∈
name_delta` is re-resolved, and every edge bound *by name* to a key in `name_delta` is re-bound.
Skipping the equivalent pass is what produced codegraph's measured **4.3% of distinct edges wrong,
both directions, silently** (cited in D2 §4). A body-only edit leaves `name_delta` empty, which is the
common case and free.

**Step 4 — resolution, clustering, reports.**

- **Resolution:** entities touching a changed segment are probed against the persisted LSH bands.
  Separately, every `entity_merge` row whose supporting mention was deleted in step 2 is **retired**,
  and `canonical_id` is recomputed for that closure only. (Bounded, except through a god-entity —
  named.)
- **Clustering: always full, never incremental.** Leiden on a million edges is seconds. graphrag's
  update path offsets delta community ids by `old_max+1` and concatenates
  (`index/update/communities.py:44-70`), so after an update an entity in both halves lives in two
  unrelated hierarchies with two reports and global search map-reduces over both. That is the exact
  mistake to invert: **re-cluster always, re-report only what changed.**
- **Reports:** `community.member_digest` = blake3-128 over sorted canonical member ids. A report is
  stale iff `report.member_digest ≠ community.member_digest`. Exact, cheap, no heuristic. And
  because reports are *lazily* materialized (§1.9), "recompute" means "invalidate".
- **Salience columns are recomputed, all three.** `entity.mention_count`, `entity.doc_count` (new:
  corpus spread, far more useful than mention count for document corpora — 400 mentions in one
  contract is not 400 mentions across 400 contracts), `entity.degree`, `edge.combined_degree`.
  graphrag recomputes edge degrees and leaves node `degree` at `"first"` with a literal `# todo`
  (`index/update/entities.py:36-72`); a post-run assertion fails the build if
  `entity.degree ≠ COUNT(*)`.

**The gate that makes all of the above credible — `G7-8 test_incremental_converges`:** build a
fixture corpus fully; build it again as N incremental steps in a Hypothesis-shuffled order; assert
the two stores are **identical on a canonical projection** — sorted `(scope, type, key)` entity
multiset, sorted `(src.key, dst.key, rel, object_literal, trust, method)` edge multiset, sorted
community `member_digest` multiset, sorted `unresolved_ref.retry_key` multiset. Any divergence fails
the build. This gate is why step 3 cannot be quietly skipped: omitting it fails immediately and
loudly.

### 1.9 Cost control on the LLM path

Everything runs through D4; I invent no second budget system.

- Each paid extractor is a `derive/1` driver with a D3 `[cost]` block **written by
  `omniweave-conform`, not by the author**, and a D4 `CostCard` (`model = "linear_per_token"`,
  `tokens_out_p95_multiple` reconciled against the 7-day median or `ow route lint --estimates`
  fails).
- Extraction is `Rung.ENRICH`, lane `graph`. `evaluate()` picks, `admit()` reserves,
  `budget.exhausted` writes back and the `DEGRADE` rule falls to the deterministic-only graph with
  `degraded=1` and a `Diag` — **never a silent partial**, and never Unlimited-OCR's
  `{"text": ""}` for an exhausted unit.
- **Reject graphrag's gleaning loop as implemented.** `2 × max_gleanings` calls per chunk on a
  monotonically growing conversation, gated by comparing a response to the exact string `"Y"` — any
  preamble reads as "no" (`graph_extractor.py:83-119`). Replace with one structured-output call per
  segment plus a **conditional** second call fired by a free signal
  (`graph.llm_recall_gap`: unresolved refs in the segment that the pass did not claim, plus
  `verify.finish_reason ≠ "stop"`), expressed as a D4 rule, not a loop. Arithmetic on the digest's
  own numbers: 10M units × 2 calls = **20M calls, ~35B prompt tokens, ~9 days single-process**; at a
  15% gleaning rate that is **11.5M calls, a 42% cut**, and the gleaning lands where recall is
  actually suspect.
- **The cache, tiered by cost of recomputation** (graphify `cache.py:932-941`, the key policy
  decision in that file). Free artifacts are namespaced by producer version so an upgrade invalidates
  them; paid artifacts are **not**, so an upgrade preserves them:

```
det_key = blake3_128(canonical([driver_id, driver_version, schema_version,
                                segment.content_digest, config_digest]))
llm_key = blake3_128(canonical([driver_id, schema_version, segment.content_digest,
                                prompt_fp, model_id, model_rev, decode_digest]))
```

  `prompt_fp` is 12 hex chars of sha256 over the prompt **with line endings and trailing whitespace
  normalized**, or every Windows checkout re-bills the corpus (`cache.py:1140-1148`). `model_id` and
  `model_rev` close graphify's one gap (it has three of the four key components). `model_rev = "main"`
  is a lint error (D2).
- **"Cache hit" is a policy, not a lookup.** Five miss shapes, each counted in `graph_spend` and
  reported once per run: unparseable payload, a `partial` marker, a semantic entry with zero entities
  *and* zero edges, a `doc_key`/`source` mismatch, a prompt-vintage miss. Plus graphify's aggregate
  warning: *"this graph may mix extraction vintages."* A cache that silently serves a partial result
  never self-heals.
- **Reports are demand-materialized.** graphrag's `max_cluster_size = 10` on 3M entities is ~300k
  leaf communities plus every internal level ⇒ **≥400k LLM calls at ~10k tokens ≈ 4B tokens**, on top
  of extraction — for a hierarchy that `DynamicCommunitySelection`'s rated BFS descent will then
  touch a small fraction of. So: default `max_cluster_size = 32`, and a report is generated **on
  first descent into that community** and cached against `member_digest`.
  `ow graph report --warm --level 0` exists for operators who want global search hot. The cost is
  named in §4: the first global query on a cold corpus is slow and expensive, and that cost lands on
  an interactive user.
- **`ow graph cost --dry-run`** prints the projected bill *before* the run from
  `COUNT(segment) × CostCard × PriceBook`, split into cached / to-extract. graphrag's README warns you
  indexing is expensive; we print the number.

### 1.10 Embeddings — three, each named to a consuming retrieval mode

`segment.text` (basic/local), `entity.description` (mention → node resolution),
`community_report.full_content` (thematic). graphrag's discipline exactly (`config/embeddings.py:6-17`),
and it is a rule with a gate: a fourth embedding requires a row in `tools/embeddings.toml` naming
its consuming retrieval mode, and CI fails an embedding computed with no row. D5 owns storage.

`entity.description` is **derived, not truth**: the highest-trust mention's context sentence. An LLM
summary is an *optional* `derive.graph.summarize` pass writing a separate `entity.summary` column,
invalidated by `entity.mention_digest`. This avoids graphrag's merge behaviour, where `description`
becomes a **list** that is re-summarized by an LLM call on every merge and truncated at 4,000 input
tokens, lossily and silently (`index/update/entities.py:36-72`,
`update_entities_relationships.py:99-110`).

---

## 2. Concrete shape

### 2.1 DDL — `omniweave_graph/store/schema.sql`, in the SAME `.owstore`

```sql
-- L3. Same file, same pragmas (busy_timeout FIRST), same conventions as D2.
-- ENDPOINT RULE: L2 `rel` endpoints are block_id. L3 `edge` endpoints are entity_id.
-- `mention` is the ONLY table in the framework referencing both.               (G7-BRIDGE)
-- enum_val domains added by L3: rel, ref_kind, taint (bit names), tier.

CREATE TABLE entity_type (
  type_id    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,            -- 'person'|'org'|'defined_term'|'label'|'section'…
  parent_id  INTEGER REFERENCES entity_type(type_id),
  scope      TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  status     TEXT NOT NULL CHECK(status IN ('builtin','declared','proposed')),
  resolution TEXT NOT NULL CHECK(resolution IN ('exact_only','fuzzy','none')),
  compatible TEXT NOT NULL DEFAULT '[]'       -- JSON array of type names that MAY merge across
);
-- 'proposed' types come from the LLM pass and are NOT queryable as first class until an
-- operator promotes them. A closed four-value entity-type list in config is why
-- "graphrag doesn't work on my domain" (DEFAULT_ENTITY_TYPES = organization/person/geo/event).

CREATE TABLE segment (
  segment_id  INTEGER PRIMARY KEY,
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, ord INTEGER NOT NULL,
  first_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  last_block  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  block_count INTEGER NOT NULL, n_tokens INTEGER NOT NULL,
  layer       INTEGER NOT NULL,               -- D2 Layer: body / furniture / note segments split
  heading_path TEXT NOT NULL,                 -- JSON array of ancestor heading texts
  atom        TEXT,                           -- 'table' | 'list' | NULL: an unsplittable atom
  content_digest BLOB NOT NULL,               -- blake3_128([heading_path, member content_digests])
  cite        TEXT NOT NULL,                  -- 's7#12'
  UNIQUE (doc_ord, gen, ord)
);
CREATE INDEX segment_digest ON segment(content_digest);

CREATE TABLE segment_block (
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  block_id   INTEGER NOT NULL REFERENCES block(block_id)     ON DELETE CASCADE,
  PRIMARY KEY (block_id)          -- EXACTLY ONE segment per block. Overlap is unrepresentable.
) WITHOUT ROWID;                  --                                              (G7-SEG)
CREATE INDEX segment_block_seg ON segment_block(segment_id);

CREATE TABLE entity (
  entity_id    INTEGER PRIMARY KEY,           -- durable surrogate; never re-derived
  corpus_scope INTEGER NOT NULL,              -- 0 = corpus-wide, else the owning doc_ord
  key          TEXT NOT NULL,                 -- normalize_key(canonical surface). NOT a surface.
  type_id      INTEGER NOT NULL REFERENCES entity_type(type_id),
  title        TEXT NOT NULL,                 -- display surface (highest-trust mention)
  cite         TEXT NOT NULL,                 -- 'e#412' — the ONLY entity id an LLM may emit
  canonical_id INTEGER NOT NULL REFERENCES entity(entity_id),  -- DERIVED from entity_merge
  resolution_trust  INTEGER NOT NULL DEFAULT 0,   -- D2 Trust, reused. No new enum.
  resolution_method INTEGER NOT NULL,             -- D2 Method, reused.
  trust        INTEGER NOT NULL DEFAULT 0,    -- MIN over live mentions. Absent => AMBIGUOUS.
  taint        INTEGER NOT NULL DEFAULT 0,    -- OR over live mentions
  mention_count INTEGER NOT NULL DEFAULT 0,
  doc_count     INTEGER NOT NULL DEFAULT 0,   -- corpus SPREAD; not the same question as frequency
  degree        INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'live'
               CHECK(status IN ('live','overloaded','retired')),
  mention_digest BLOB NOT NULL,               -- merkle over live mention digests: summary key
  description  TEXT,                          -- DERIVED (highest-trust mention's sentence)
  summary      TEXT,                          -- LLM, optional, separate column
  summary_producer_id INTEGER REFERENCES producer(producer_id),
  x            TEXT NOT NULL DEFAULT '{}',
  UNIQUE (corpus_scope, type_id, key)
);
CREATE INDEX entity_canon  ON entity(canonical_id) WHERE status='live';
CREATE INDEX entity_review ON entity(resolution_trust, taint) WHERE resolution_trust < 2 OR taint<>0;

CREATE TABLE alias (
  entity_id   INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  surface     TEXT NOT NULL,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL DEFAULT 0,
  taint       INTEGER NOT NULL DEFAULT 0,
  doc_count   INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (entity_id, key, producer_id)
) WITHOUT ROWID;
CREATE INDEX alias_key ON alias(key);
-- RULE (injection layer 4): an alias with (taint & TAINT_UNTRUSTED_SOURCE) AND doc_count = 1
-- is NEVER a blocking key for cross-document resolution. Enforced in resolve/block.py + a test.

CREATE TABLE mention (                 -- THE BRIDGE. The only both-spaces table.
  mention_id INTEGER PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entity(entity_id)   ON DELETE CASCADE,
  block_id   INTEGER NOT NULL REFERENCES block(block_id)     ON DELETE CASCADE,
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,    -- D2 TextSpan into block.text
  surface TEXT NOT NULL,
  -- geometry: A DERIVED CACHE with a DECLARED METHOD. Never a digest input.       (G7-GEOM)
  quad BLOB,
  quad_method TEXT CHECK(quad_method IN ('char_exact','line_interp','block_fallback')),
  -- provenance, verbatim from D2 + D4
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL,
  trust  INTEGER NOT NULL DEFAULT 0,
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL,
  decision_id TEXT,                                -- D4 route_decision
  taint INTEGER NOT NULL DEFAULT 0,
  digest BLOB NOT NULL,                            -- blake3_128([entity.key, block_id, ts_a, ts_b])
  status TEXT NOT NULL DEFAULT 'live'
         CHECK(status IN ('live','orphaned','quarantined')),
  CHECK (ts_a <= ts_b),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  CHECK ((quad IS NULL) = (quad_method IS NULL)),
  CHECK (NOT (method = 6 AND trust = 2))     -- method=llm may NEVER be trust=EXTRACTED  (G7-1)
);                                           -- 6 == enum_val('method','llm').ord; unit-tested
CREATE UNIQUE INDEX mention_ident   ON mention(block_id, ts_a, ts_b, entity_id, producer_id);
CREATE INDEX        mention_entity  ON mention(entity_id)  WHERE status='live';
CREATE INDEX        mention_segment ON mention(segment_id);
CREATE INDEX        mention_review  ON mention(trust, taint) WHERE trust < 2 OR taint <> 0;

CREATE TABLE edge (            -- relationship AND claim. One shape, because they ARE one shape.
  edge_id INTEGER PRIMARY KEY,
  src_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  dst_id  INTEGER          REFERENCES entity(entity_id) ON DELETE CASCADE,  -- NULL ⇒ literal
  rel     INTEGER NOT NULL,                    -- closed vocab, FK enum_val('rel')
  role    TEXT,                                -- participation role: reifies a hyperedge
  object_literal  TEXT, object_datatype TEXT,  -- 'xsd:date'|'xsd:decimal'|'money:USD'|'string'
  valid_from TEXT, valid_to TEXT,              -- graphrag covariates: the best temporal schema here
  claim_status TEXT CHECK(claim_status IN ('asserted','disputed','superseded','withdrawn')),
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
       -- WHERE THE RELATIONSHIP WAS OBSERVED (graphify: source_file is required on EDGES).
       -- This is what makes "where does this document assert that" answerable, and what
       -- gives a blast-radius answer the call site rather than the definition line.
  weight REAL NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,
  corroborations  INTEGER NOT NULL DEFAULT 1,  -- corroboration is NOT promotion
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL DEFAULT 0,
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, decision_id TEXT,
  taint INTEGER NOT NULL DEFAULT 0,
  x TEXT NOT NULL DEFAULT '{}',
  CHECK ((dst_id IS NULL) <> (object_literal IS NULL)),
  CHECK ((object_literal IS NULL) = (object_datatype IS NULL)),
  CHECK (src_id <> IFNULL(dst_id, -1)),
  CHECK (NOT (method = 6 AND trust = 2))
);
-- Identity IN THE SCHEMA with IFNULL sentinels, or INSERT OR IGNORE is a plain INSERT
-- with nothing to conflict on, and SQL NULLs are each distinct.       (codegraph schema.sql:170-178)
CREATE UNIQUE INDEX edge_identity ON edge(
  src_id, IFNULL(dst_id,-1), rel, IFNULL(object_literal,''), observed_block, producer_id);
CREATE INDEX edge_src    ON edge(src_id, rel);
CREATE INDEX edge_dst    ON edge(dst_id, rel);
CREATE INDEX edge_review ON edge(trust, taint) WHERE trust < 2 OR taint <> 0;

CREATE TABLE edge_evidence (
  edge_id    INTEGER NOT NULL REFERENCES edge(edge_id)       ON DELETE CASCADE,
  mention_id INTEGER NOT NULL REFERENCES mention(mention_id) ON DELETE CASCADE,
  slot TEXT NOT NULL CHECK(slot IN ('src','dst','predicate','value')),
  PRIMARY KEY (edge_id, mention_id, slot)
) WITHOUT ROWID;

CREATE TABLE entity_merge (       -- APPEND-ONLY DECISION LOG. entity.canonical_id is derived.
  merge_id  INTEGER PRIMARY KEY,
  loser_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  winner_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  score REAL, score_kind TEXT,           -- 'jaro_winkler' | 'lsh_jaccard' | 'llm_logprob'
  guards TEXT NOT NULL DEFAULT '[]',     -- the guards that PASSED: a rule change is auditable
  evidence TEXT NOT NULL DEFAULT '{}',
  decided_at_gen INTEGER NOT NULL,
  retired_at_gen INTEGER,                -- non-NULL ⇒ this merge no longer applies
  CHECK (loser_id <> winner_id),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX entity_merge_pair ON entity_merge(loser_id, winner_id)
  WHERE retired_at_gen IS NULL;

CREATE TABLE lsh_band (           -- persisted MinHash bands. NEVER an in-memory index.
  band_no INTEGER NOT NULL, band_hash INTEGER NOT NULL,
  type_id INTEGER NOT NULL, entity_id INTEGER NOT NULL REFERENCES entity(entity_id)
    ON DELETE CASCADE,
  PRIMARY KEY (band_no, band_hash, entity_id)
) WITHOUT ROWID;

CREATE TABLE unresolved_ref (     -- codegraph's durable unfinished-business queue, for documents
  ref_id INTEGER PRIMARY KEY,
  from_entity INTEGER REFERENCES entity(entity_id) ON DELETE CASCADE,
  from_block  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  ref_kind TEXT NOT NULL,         -- section|figure|table|citation|anchor|defined_term|glossary
  ref_text TEXT NOT NULL,
  retry_key TEXT NOT NULL,        -- normalize_key of the resolvable name — the name_delta join
  scope TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  candidates TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK(status IN ('pending','failed')),   -- resolved ⇒ ROW DELETED
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  last_tried_gen INTEGER
);
CREATE INDEX unresolved_retry ON unresolved_ref(retry_key) WHERE status='failed';
-- Partial, because on a healthy index the pending set is empty and the failed set is the only
-- population worth indexing.                                       (codegraph migrations.ts v8)

CREATE TABLE name_def (           -- the definitionDelta support table
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  scope TEXT NOT NULL, ref_kind TEXT NOT NULL, name_key TEXT NOT NULL,
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (doc_ord, gen, scope, ref_kind, name_key)
) WITHOUT ROWID;
CREATE INDEX name_def_key ON name_def(scope, ref_kind, name_key);

CREATE TABLE community (
  community_id INTEGER PRIMARY KEY,
  cluster_run  INTEGER NOT NULL,
  level        INTEGER NOT NULL,          -- INTEGER. graphrag's is str and .astype(int)'d later.
  parent_id    INTEGER REFERENCES community(community_id),   -- NULL at root. Never -1.
  component_id INTEGER NOT NULL,          -- we cluster PER COMPONENT: no use_lcc silent discard
  size INTEGER NOT NULL,
  member_digest BLOB NOT NULL,            -- blake3_128 over sorted canonical member ids
  cohesion REAL,
  UNIQUE (cluster_run, level, community_id)
);
CREATE TABLE community_member (
  community_id INTEGER NOT NULL REFERENCES community(community_id) ON DELETE CASCADE,
  entity_id    INTEGER NOT NULL REFERENCES entity(entity_id)       ON DELETE CASCADE,
  PRIMARY KEY (community_id, entity_id)
) WITHOUT ROWID;
CREATE INDEX community_member_entity ON community_member(entity_id);

CREATE TABLE community_report (   -- DEMAND-MATERIALIZED. Written on first descent.
  community_id INTEGER PRIMARY KEY REFERENCES community(community_id) ON DELETE CASCADE,
  member_digest BLOB NOT NULL,    -- the digest AT GENERATION TIME. != community's ⇒ STALE.
  title TEXT NOT NULL, summary TEXT NOT NULL, full_content TEXT NOT NULL,
  rank REAL NOT NULL, rating_explanation TEXT NOT NULL, findings TEXT NOT NULL,
  coverage REAL NOT NULL,         -- fraction of member evidence that FIT the context window
  trust INTEGER NOT NULL, taint INTEGER NOT NULL DEFAULT 0,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  spend_micros INTEGER NOT NULL, tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
  generated_at_gen INTEGER NOT NULL
);
CREATE VIEW community_report_fresh AS
  SELECT r.* FROM community_report r JOIN community c USING (community_id)
  WHERE r.member_digest = c.member_digest;
-- Retrieval reads the VIEW. A stale report is invisible, not silently served.

CREATE TABLE extraction (         -- per (segment, driver). What makes incremental exact.
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  driver_id  TEXT NOT NULL,
  tier       TEXT NOT NULL CHECK(tier IN ('det','llm')),   -- DERIVED from card cost.class
  schema_version INTEGER NOT NULL,
  input_digest BLOB NOT NULL, key_digest BLOB NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','partial','empty','failed','quarantined')),
  n_entities INTEGER NOT NULL DEFAULT 0, n_edges INTEGER NOT NULL DEFAULT 0,
  n_unverified INTEGER NOT NULL DEFAULT 0,
  spend_micros INTEGER NOT NULL DEFAULT 0,
  tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
  decision_id TEXT, ran_at_gen INTEGER NOT NULL,
  PRIMARY KEY (segment_id, driver_id)
) WITHOUT ROWID;

CREATE TABLE quarantine (         -- NOTHING IS DELETED.
  q_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('entity','edge','mention','alias','merge')),
  reason TEXT NOT NULL,   -- span_unverified | dangling_endpoint | guard_blocked | taint_refused
                          -- | type_incompatible | budget_truncated | llm_trust_ceiling
                          -- | cohesion_split | overloaded_entity
  payload TEXT NOT NULL,  -- canonical JSON of the rejected row
  segment_id INTEGER REFERENCES segment(segment_id) ON DELETE CASCADE,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  decision_id TEXT, at_gen INTEGER NOT NULL
);
CREATE INDEX quarantine_reason ON quarantine(reason, at_gen);
-- graphrag logs a drop count and deletes (filter_orphan_relationships). We KEEP the row:
-- a hallucinated entity name is very often a REAL entity the extractor failed to emit a row for.

CREATE TABLE graph_spend (
  run_id TEXT NOT NULL, driver_id TEXT NOT NULL,
  segments_in INTEGER NOT NULL, segments_cached INTEGER NOT NULL,
  calls INTEGER NOT NULL, tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
  micros INTEGER NOT NULL, wall_ms INTEGER NOT NULL,
  miss_corrupt INTEGER NOT NULL DEFAULT 0, miss_partial INTEGER NOT NULL DEFAULT 0,
  miss_empty   INTEGER NOT NULL DEFAULT 0, miss_vintage INTEGER NOT NULL DEFAULT 0,
  miss_mismatch INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, driver_id)
) WITHOUT ROWID;
```

### 2.2 Python — `omniweave-graph`, dependencies `{omniweave-core, tree-sitter}`

```python
# omniweave_graph/ident.py — ONE implementation. Three producers must agree or the graph
# splits one entity into disconnected ghost nodes. (graphify ids.py, 93 lines, verbatim recipe)
def normalize_key(s: str) -> str:
    """Invariants, one test each:
       idempotent:       normalize_key(normalize_key(s)) == normalize_key(s)
       charset-closed:   result contains only \\w and _
       caseless-stable:  normalize_key(s) == normalize_key(s.casefold())
    The bounded fixpoint loop is required: casefold and NFKC do not commute and neither is a
    fixpoint of the other (İ -> i + U+0307, which NFKC then recomposes).  graphify #2614.
    re.UNICODE on the filter, or every CJK/Cyrillic/Arabic corpus collapses to one node per
    document.  graphify #811."""
    cur = s
    for _ in range(6):
        nxt = unicodedata.normalize("NFKC", cur.casefold())
        if nxt == cur: break
        cur = nxt
    cur = re.sub(r"[^\w]+", "_", cur, flags=re.UNICODE)
    return re.sub(r"_+", "_", cur).strip("_")

def make_key(*parts: str) -> str: ...
# The LLM extraction prompt states THIS SAME RECIPE in prose so model-minted surfaces normalize
# onto deterministic keys on purpose — but the model's own `id` string is NEVER stored.  (G7-11)

# omniweave_graph/model/taint.py
class Taint(IntFlag):
    NONE = 0
    UNTRUSTED_SOURCE   = 1 << 0
    SENTINEL_DEFANGED  = 1 << 1
    HIDDEN_TEXT        = 1 << 2
    OFFSCREEN          = 1 << 3
    SPAN_FUZZY         = 1 << 4
    SINGLE_SOURCE_XDOC = 1 << 5
    # bits 6..31 RESERVED. A 33rd bit is a migration, and that is written down.
GENERATION_BLOCKED = Taint.SENTINEL_DEFANGED | Taint.HIDDEN_TEXT | Taint.OFFSCREEN

# omniweave_graph/model/rel.py — CLOSED at v1. Adding one is a core release.
# EVERY member carries a DIRECTION RULE. A lint fails a member with no rule.
class Rel(StrEnum):
    MENTIONS="mentions"; DEFINES="defines"; DEFINED_AS="defined_as"
    CITES="cites"; CROSS_REFS="cross_refs"
    CONTAINS="contains"; PART_OF="part_of"          # ENTITY containment. Block containment is L2's.
    HAS_VALUE="has_value"; ATTRIBUTED_TO="attributed_to"; STATES="states"
    LOCATED_IN="located_in"; DATED="dated"
    PARTY_TO="party_to"; SIGNED_BY="signed_by"
    AMENDS="amends"; GOVERNS="governs"
    PARTICIPATES_IN="participates_in"               # + edge.role reifies an n-ary event
    SEMANTICALLY_RELATED="semantically_related"
DIRECTION: Mapping[Rel, str] = {
  Rel.CITES: "source is the CITING entity; target is the CITED entity. Never reverse this.",
  Rel.DEFINES: "source is the DEFINING passage's entity; target is the term being defined.",
  Rel.HAS_VALUE: "source is the SUBJECT the value is about; the value is object_literal.",
  Rel.PARTY_TO: "source is the PERSON/ORG; target is the AGREEMENT.",
  ...  # graphify llm.py:500-504. Every schema needs this paragraph; almost none have it.
}

# omniweave_graph/segment.py
MAX_SEGMENT_TOKENS = 1200          # min(tenant_cap, MAX_*). Never widened by config.
MAX_SEGMENT_BLOCKS = 512
def segment(doc: "Doc", *, sink: "GraphSink") -> Iterator[SegmentDraft]:
    """Structural, not token-sliding.
       * never splits a table or a list (atom='table'/'list'); a table over MAX_SEGMENT_BLOCKS
         becomes its own segment and is routed to derive.graph.kv, never to an LLM entity pass;
       * `layer` partitions: body / furniture / note segments are separate, so a footnote's
         entities are attributable without polluting body context;
       * carries heading_path, which IS a digest input;
       * ZERO overlap. Boundary context is a <context> block in the prompt, not a shared span."""

# omniweave_graph/llm/verify.py — LAYER 2 OF THE INJECTION DEFENCE
def verify_span(segment_text: str, surface: str, a: int, b: int
                ) -> tuple[Literal["exact","fuzzy","reject"], float]:
    """normalize_k(segment_text[a:b]) == normalize_k(surface) -> "exact".
       ratio >= 0.95 -> "fuzzy": Taint.SPAN_FUZZY, trust capped at AMBIGUOUS.
       else -> "reject": a quarantine row (reason='span_unverified'), NEVER an entity.
       A model cannot mint an entity that does not point at bytes that exist."""

# omniweave_graph/llm/wrap.py — LAYER 1, with the three fixes the risk digest names
_SENTINELS = re.compile(
    r"</?untrusted_source\b[^>]*>"
    r"|<\|[A-Za-z0-9_.\-]{1,64}\|>"      # the FORM is the hazard, not an enumerated list
    r"|<<SYS>>|<</SYS>>|\[/?(?:INST|SYSTEM)\]",
    re.IGNORECASE)
# DELIBERATELY ABSENT: graphify's ^\s*###?\s*(system|instruction)s?:?\s*$ — it matches
# "## Instructions" in any manual, RFP or SOP.  A conformance fixture asserts NO taint on one.
@dataclass(frozen=True, slots=True)
class ShiftMap:                          # defang a COPY; lift model offsets back through this
    inserts: tuple[int, ...]             # sorted insertion offsets, one ZWSP each
    def lift(self, off: int) -> int: ...
def wrap_untrusted(rel: str, text: str, sha256: str) -> tuple[str, ShiftMap, Taint]: ...
    # path attribute is XML-escaped; sha256 lets a reviewer correlate a node back to bytes.

# omniweave_graph/resolve/funnel.py
ENTROPY_MIN = 2.5; LSH_THRESHOLD = 0.7; NUM_PERM = 128
MERGE_THRESHOLD = 92.0; COMMUNITY_BOOST = 5.0
LLM_BAND = (75.0, 92.0); LLM_BATCH = 30
COHESION_SPLIT_DELTA = 10.0            # re-check after union-find: kills transitive chains
COOCCUR_BLOCK_ABOVE = 97.0             # two entities in one segment: near-identical or nothing
MAX_ENTITY_DEGREE = 4096               # above => status='overloaded', excluded from expansion

def resolve(store, *, changed: frozenset[EntityId] | None, budget: "Admission") -> ResolveReport:
    """PURE over (entity rows, alias rows, entity_merge live rows, community membership).
       Writes entity_merge rows and recomputes entity.canonical_id as a path-compressed
       closure. Idempotent. Order-independent (G7-6). Never mutates or deletes an entity."""

# omniweave_graph/cluster/leiden.py — stdlib only, over an array('i') CSR built by one SQL scan.
LEIDEN_SEED = 0xDEADBEEF
MAX_CLUSTER_SIZE = 32                  # not graphrag's 10: 10 on 3M entities is ~300k leaves
def cluster(store, *, run: int) -> ClusterReport:
    """Determinism engineered three ways, all copied from graphrag cluster_graph.py:57-97:
       direction-normalized (lo=min,hi=max), drop_duplicates(keep=last), sorted edge list,
       fixed seed. PER CONNECTED COMPONENT — use_lcc is REJECTED: on a folder of unrelated
       PDFs (omniweave's default corpus) it silently discards most of the graph.
       Refuses above MAX_GRAPH_EDGES = 2_000_000 with OW_GRAPH_TOO_LARGE naming the cap and
       the driver seam (`omniweave-driver-graspologic`) that raises it."""

# omniweave_graph/incr/converge.py — the flagship gate
def canonical_projection(store) -> bytes:
    """sorted (scope,type,key) | sorted (src.key,dst.key,rel,object_literal,trust,method)
       | sorted community member_digest multiset | sorted unresolved_ref.retry_key multiset.
       Surrogate ids are EXCLUDED. This is what full and incremental must agree on."""
```

### 2.3 The driver cards — `derive/1`, D3 shape

```toml
# omniweave_graph/det/kv/driver.toml            (one driver per file; card_schema at the top)
card_schema = 1
[driver]
id = "derive.graph.kv" ; port = "derive/1" ; version = "0.1.0" ; schema_version = 1
title = "Key/value and table-header claim extractor"
summary = "Form fields and Grid.top_heading/left_heading -> temporal claims. Zero LLM."
entrypoint = "omniweave_graph.det.kv.driver:KvExtractor"
granularity = "document" ; deterministic = true
[capability]
consumes = ["doc_model"] ; produces = ["graph_items"]
formats  = ["*"]
[capability.derive]
emits_entities = true ; emits_edges = true ; emits_claims = true
max_trust = "extracted"          # THE ORDER GATE: only a det driver may declare this
needs_spatial = "none"
[hardware] gpu="none" ; needs_network=false ; imports_torch=false ; install_bytes=90_000
[isolation] requires="inproc" ; memory_mb=256 ; wall_ms_hard=60_000
[licence.code] spdx="Apache-2.0" ; licence_sha256="sha256:…" ; redistribution="allowed"
```

```toml
# omniweave_graph/llm/entity/driver.toml
card_schema = 1
[driver]
id = "derive.graph.llm_entity" ; port = "derive/1" ; version = "0.1.0" ; schema_version = 1
entrypoint = "omniweave_graph.llm.entity.driver:LlmEntityExtractor"
granularity = "document" ; deterministic = false
[capability.derive]
emits_entities = true ; emits_edges = true ; emits_claims = true
max_trust = "inferred"           # A CARD DECLARING "extracted" HERE FAILS `omniweave driver check`
                                 # because cost.class != "free".  (G7-1 at the card layer)
span_verified = true             # conform asserts it: 40-payload injection fixture, 0 untainted
[isolation] requires="subproc" ; progress_ms=15_000 ; wall_ms_hard=180_000 ; batch_max_units=8
[cost]   # WRITTEN BY omniweave-conform. Author values rejected.
class="billed_api" ; unit="segment" ; model="linear_per_token"
tokens_out_p95_multiple = 1.9
```

### 2.4 D4 additions — the `graph` lane, its signals, its rules

```python
# omniweave/route/signals/graph.py — all FREE unless marked
"graph.segment_count"       unit  count     FREE
"graph.det_entity_density"  part  measure   FREE   # det mentions per 1k chars of the segment
"graph.unresolved_frac"     part  measure   FREE   # unresolved_ref rows / det mentions
"graph.novel_key_frac"      part  measure   FREE   # det keys not already in the corpus
"graph.injection_sentinels" part  count     FREE   # from wrap_untrusted, computed once
"graph.hidden_text_frac"    part  measure   FREE   # blocks with layer=hidden in the segment
"graph.llm_recall_gap"      part  measure   FREE   # requires=(ENRICH): the GLEANING trigger
```

```toml
# additions to omniweave/route/policies/balanced.toml
[[rule]]
id = "graph.deterministic-always" ; rung = "ENRICH" ; lane = "graph"
comment = "Free tier is unconditional. It is the floor the paid tier is measured against."
when = {}
then = { driver = "derive.graph.spine,derive.graph.anchor,derive.graph.label,derive.graph.kv,derive.graph.pattern" }

[[rule]]
id = "graph.llm-only-where-det-is-thin" ; rung = "ENRICH" ; lane = "graph"
comment = """A segment the deterministic tier already covered densely, that introduces no new
keys, is a poor LLM candidate. This is the whole cost story in one predicate."""
on_unknown = "defer"                      # REQUIRED: reads nullable keys, target is BILLED_API
when.all_of = [
  { "graph.det_entity_density" = { lt  = 3.0 } },
  { "graph.novel_key_frac"     = { gte = 0.15 } },
]
then = { driver = "derive.graph.llm_entity", max_cost_class = "billed_api" }

[[rule]]
id = "graph.glean-once-on-measured-gap" ; rung = "ENRICH" ; lane = "graph"
comment = """Replaces graphrag's 2-calls-per-chunk loop gated on the string 'Y'
(graph_extractor.py:83-119). One conditional second call, on a measured signal."""
when.any_of = [
  { "graph.llm_recall_gap"   = { gte = 0.30 } },
  { "verify.finish_reason"   = { ne = "stop" } },
]
then = { escalate_to = "REGEN", driver = "derive.graph.llm_entity", cause_from = "when" }

[[rule]]
id = "graph.untrusted-never-auto-bills" ; rung = "GATE" ; lane = "graph"
comment = "An untrusted external document may not spend money on extraction unattended."
when.all_of = [ { "unit.trust_class" = "untrusted_external" }, { "trigger.kind" = "watch" } ]
then = { max_cost_class = "local_compute" }
```

### 2.5 Config, CLI, directory

```toml
# omniweave.toml additions
[graph]
enabled          = true
max_segment_tokens = 1200          # clamps BELOW MAX_SEGMENT_TOKENS; never above
max_cluster_size = 32
reports          = "lazy"          # lazy | warm
gazetteer        = "gazetteer.toml"
[graph.types]                       # corpus type registry; 'proposed' types need promotion
party   = { scope = "document", resolution = "exact_only" }
statute = { scope = "corpus",   resolution = "fuzzy", compatible = ["regulation"] }
[graph.taint]
block_generation = ["sentinel_defanged", "hidden_text", "offscreen"]
[graph.resolve]
merge_threshold = 92.0 ; llm_band = [75.0, 92.0] ; max_entity_degree = 4096
```

```
ow graph build     [--tier det|all] [--dry-run]   # --dry-run prints the projected bill
ow graph resolve   [--explain <entity>]           # prints the funnel trace + the guards that fired
ow graph unmerge   <merge_id>                     # retires one entity_merge row, recomputes closure
ow graph cluster
ow graph report    [--warm --level 0]
ow graph review    [--taint] [--trust below=extracted]
ow graph cost      [--since <run>]
ow graph diff      <gen_a> <gen_b>                # canonical_projection delta, human-readable
ow graph explain   <cite>                         # cite -> mention -> block -> page + polygon

packages/omniweave-graph/src/omniweave_graph/
  ident.py  segment.py  check.py  cost.py
  model/    entity.py edge.py mention.py community.py taint.py rel.py types.py
  store/    schema.sql  migrations/0007_graph.sql  sink.py  reader.py
  det/      spine/ anchor/ label/ kv/ pattern/ code/     (each: driver.toml + driver.py)
  llm/      wrap.py prompt.py verify.py entity/ claim/ report/ summarize/
  resolve/  block.py lsh.py guards.py funnel.py merge.py
  cluster/  leiden.py cohesion.py
  incr/     delta.py replace.py namedelta.py rebind.py converge.py
fixtures/graph/
  injection/            40 payloads: docx white text, pdf off-page, <|im_start|> in a code fence,
                        forged </untrusted_source>, and an SOP with "## Instructions" (MUST NOT taint)
  converge/             a 60-document mixed corpus + a scripted edit sequence
  merge/                the seven false-merge shapes, one fixture each
```

### 2.6 The invariant table

| # | Invariant | Enforcement |
|---|---|---|
| G7-1 | An LLM may never mint an `EXTRACTED` fact. | `CHECK (NOT (method=6 AND trust=2))` on `mention` and `edge`; a unit test pins `enum_val('method','llm').ord == 6`; the card's `max_trust` is refused by `omniweave driver check` when `cost.class != "free"`. |
| G7-2 | Every entity has ≥1 live mention; every edge ≥1 evidence row. | `owcheck --graph` before commit; a `DELETE` trigger retires an entity whose last mention goes; property test. |
| G7-3 | Every mention resolves inside its block's text. | FK + `CHECK(ts_a<=ts_b)` + `owcheck` rule `ts_b <= length(block.text)`. |
| G7-4 | Geometry is derived, never identity. | `quad`/`quad_method` excluded from all digests; CI greps the recipes; property test perturbs every quad and asserts an identical canonical projection. |
| G7-5 | `entity.canonical_id` is a pure function of live `entity_merge` rows. | CI recomputes from the log and byte-compares; `owcheck` asserts acyclic + fully path-compressed. |
| G7-6 | Resolution is order-independent. | Hypothesis: shuffle the candidate list 100×, assert an identical `canonical_id` map. |
| G7-7 | Migrations may only downgrade `trust`, `resolution_trust`, `taint`-clearing is forbidden. | Migration lint parses `UPDATE … SET trust`/`taint` and fails on any that can increase trust or clear taint. Absent ⇒ weakest (`NOT NULL DEFAULT 0`). |
| G7-8 | Incremental converges with full. | `test_incremental_converges` over `fixtures/graph/converge/`, Hypothesis-shuffled edit order, equality on `canonical_projection()`. **Blocking, not nightly.** |
| G7-9 | No dangling edge; nothing is deleted. | FKs; the referential-integrity gate writes to `quarantine`; the drop count is reported per run. |
| G7-10 | Deterministic extraction and clustering are bit-reproducible. | Two runs, identical canonical projection including community assignment. CI gate. |
| G7-11 | No LLM-returned string is ever an identifier. | semgrep in `llm/`: a parsed-response `id`-shaped field may flow only into `normalize_key()`, never into an INSERT. |
| G7-12 | Every LLM mention is span-verified before insert. | `verify_span`; `n_unverified` per extraction; `span_unverified_frac > 0.1` emits `OW_GRAPH_LOW_GROUNDING`. |
| G7-13 | Untrusted text never reaches a prompt outside `wrap_untrusted()`. | semgrep in `llm/`; conform suite `injection` over the 40-payload fixture; zero false positives on the SOP fixture. |
| G7-14 | A report is stale iff `member_digest` changed. | Retrieval reads `community_report_fresh`; a test mutates one member, re-clusters, asserts exactly the affected reports go stale. |
| G7-15 | `mention` is the only both-spaces table. | Schema lint over the DDL: every table's FK targets are classified L2/L3; both ⇒ fail unless named `mention`. |
| G7-16 | Salience is recomputed, all three columns. | Post-run assertion `entity.degree == COUNT(*)`, `mention_count`, `doc_count`; fails the run, not a warning. |
| G7-17 | Every `Rel` member has a written direction rule. | `test_rel_direction_complete` over `DIRECTION`. |
| G7-18 | Three consumers per confidence field. | Doc test greps ≥3 distinct read sites for `trust`, `taint`, `resolution_trust`. **Weakest enforcer here; stated as such.** |

---

## 3. Cost, stated

**Engineering, ~21–24 engineer-weeks.** Schema + migrations + `owcheck --graph` 2w; segmenter 1w;
six deterministic extractors 4–5w (code largely graphify-derived); `ident` + property tests 0.5w;
resolution funnel + LSH + guards + merge log 2.5w; Leiden + cohesion 1.5w; incremental (delta, tier
replacement, `name_delta`, rebind) 3w; LLM tier + cache + injection layers 3w; conform suites 1.5w;
convergence gate, fixtures and property tests 1.5w. **First useful milestone at week 6**:
`ow graph build --tier det` over a DOCX corpus, entities/edges/claims with polygons and zero LLM
spend — a demoable product before a dollar is billed.

**Runtime.** Deterministic extraction is one ordered pass over blocks, O(blocks), roughly the cost of
D2's `owcheck` (~240 ns/block). `resolve` is O(entities × bands) against a covering index. `cluster`
is the only superlinear stage and it is capped.

**Storage.** A 5,000-page report is 300k–600k blocks (D2's arithmetic). Deterministic yield of
roughly one mention per eight blocks ⇒ ~50k mentions, ~15k entities, ~30k edges; at ~80 B/row plus
indexes that is **~10 MB against D2's ~200 MB store**. LLM extraction at graphrag's 1–3 entities per
unit over ~40k segments adds ~80k pre-resolution entity rows. **The graph is not the storage problem;
reports and embeddings are, and they are D5's.**

**Memory.** The only cliff is clustering. graphrag's is a Python list of edge tuples — 20M edges is
4–6 GB of interpreter objects before the algorithm allocates. Ours is `array('i')` CSR from one SQL
scan: 2M edges is ~16 MB, and above `MAX_GRAPH_EDGES = 2_000_000` it refuses with a named cap and a
named driver seam rather than swapping.

**Dependency weight.** `omniweave-graph` becomes `{omniweave-core, tree-sitter}`. Dropping
`graphrag-chunking` removes `pydantic` from its closure and removes the `<3.14` CPython ceiling.

**Operational burden.** `entity_merge` grows monotonically on a churning corpus and needs a
generation-boundary compaction. `ow graph review` is a queue a human is expected to work, and on an
untrusted corpus it will be long. The convergence gate is minutes of CI on every PR touching the
package.

---

## 4. Failure modes, honestly

1. **The god-entity.** 4,000 NDAs and "the Company". `status='overloaded'` at degree 4,096 is a
   refusal, not a fix: the entity stops participating in expansion and in communities, and every
   query about it degrades. The input that breaks the design is a homogeneous corpus of boilerplate
   documents about genuinely different parties.
2. **`name_delta`'s class list is a judgement call.** Which document names are "globally resolvable"
   — defined terms, section numbers, figure labels, citation keys, anchors, glossary entries — is
   enumerated by us. Miss a class a specific corpus depends on (a corpus-specific exhibit id scheme,
   say) and incremental silently diverges from full for that class, and G7-8 catches it **only if the
   fixture corpus contains that class**. **This is the weakest point in the design.** Partial
   mitigation: `ow graph diff` and a quarterly full rebuild whose divergence is reported.
3. **A heading rename re-bills a section.** `heading_path` is a digest input, so renaming a top-level
   heading in a 500-page report re-extracts everything beneath it. Correct — it changes what the
   model saw — and someone will hit it on a cosmetic edit and be angry. I will not trade the
   correctness for the bill.
4. **Our own Leiden may under-perform graspologic.** Lower modularity ⇒ worse communities ⇒ worse
   thematic retrieval. Mitigated by a modularity floor gate against a reference partition on a
   fixture graph, and by the `structure.cluster` driver seam. Not eliminated.
5. **Lazy reports move cost to the interactive path.** The first global query on a cold corpus is
   slow and expensive, and the person paying is a user, not a batch job. `--warm` exists; the default
   is still the surprising one for someone who expected indexing to be the expensive part.
6. **Taint over-blocks technical corpora.** A book about prompt engineering, an LLM API reference, a
   corpus of jailbreak research — all carry `SENTINEL_DEFANGED` legitimately, and their facts are
   excluded from generation by default. Taint is per-mention, not per-document, which helps; on those
   corpora it will still be loud.
7. **Span verification rejects legitimate model output.** A model that expands an abbreviation or
   normalizes a ligature fails the exact check and lands on the ≥0.95 fuzzy path or in quarantine.
   The rejection rate on non-Latin scripts is **unmeasured**, and `normalize_k`'s tolerance is a
   number I am guessing at until a fixture corpus says otherwise.
8. **A merge log without compaction.** On a high-churn corpus `entity_merge` grows without bound and
   `canonical_id` recomputation walks a long log. Compaction at a generation boundary is designed but
   is operational work someone must schedule.
9. **`quarantine` is a table nobody opens.** graphrag deletes and logs; we keep, which is better and
   also means a corpus with 40,000 `span_unverified` rows reads as forty thousand things nobody
   looks at. The per-run aggregate counter is the only thing standing between that and invisibility.
10. **Cohesion re-check can split a correct cluster.** Three genuine spellings of one entity, pairwise
    similar to each other but each 88 to the survivor, get split at `MERGE_THRESHOLD − 10`. That is a
    false *negative* rather than a false merge, which is the direction I choose — but it is a real
    loss and it is recorded in `quarantine` with `reason='cohesion_split'` so it is at least visible.

---

## 5. Why I reject the alternatives

- **graphrag's model as shipped.** Take the seven types, the covariate columns, the cache-key design,
  the proportional context budget and the rated hierarchical descent. Reject the machinery, all of it
  checkable: edges keyed on uppercased **titles** (`graph_extractor.py:139-141`) so resolution is
  `groupby("title")` and spelling drift splits a node; delimited-text extraction whose record test is
  `== '"entity"'` **with the quotes**, so a total parse failure is indistinguishable from "no
  entities here" (`graph_extractor.py:126-166`); title-only delta detection so an in-place edit
  reports "no new documents" and stops (`incremental_index.py:29-58`); `deleted_inputs` computed and
  consumed nowhere; node `degree` merged as `"first"` with a literal `# todo`; communities never
  recomputed, id-shifted by `old_max+1` and concatenated so one entity lives in two hierarchies with
  two reports; `use_lcc = True` silently discarding everything outside the largest component; and
  `remove_ego_nodes = True` deleting the single highest-degree node outright.
- **graphify's model as shipped.** Take the confidence enum and its six consumers, the cache in full,
  `ids.py`, tier-scoped `build_merge`, the dedup funnel, and the injection wrapper. Reject the
  storage: NetworkX plus a committed `graph.json` with the authors' own caps of **50 MB / 100k nodes**
  is two to three orders short of 10M blocks; `default="EXTRACTED"` on a missing confidence is the
  strongest tier where it must be the weakest; there is **no spatial provenance anywhere**, so
  nothing in it can answer the polygon question; and its union-find merge is destructive.
- **A mode switch — two named pipelines over one schema (graphrag's `PipelineFactory`).** Genuinely
  better than two subsystems, and still wrong: the corpus acquires a *vintage*, and a user holding a
  fact cannot ask "did this cost money, may I trust it, and can I re-derive it for free". Provenance
  on every row answers all three and costs one interned FK plus a `CHECK`. And a mode switch cannot
  express the actual product: a corpus where the tables were extracted deterministically and only the
  prose was billed.
- **A separate graph database (Neo4j, kuzu, DuckDB-PGQ).** D2 ruled one store — "L4 builds on these
  tables, not beside them; a second block representation is a schema violation" — and a second engine
  is a second consistency problem, a second backup story, a second freshness question and a second
  install. Nothing in the retrieval contract needs traversal past depth 3, and depth 3 is three
  indexed joins.
- **A schemaless property graph (arbitrary node/edge attribute bags).** Reintroduces exactly the
  spelling-dependent DAG D3 rejected when it refused the `x-` experimental artifact-kind namespace: in
  three years two vendors ship `x.acme.reading_order` and `x.beta.reading_order` and nothing
  reconciles them. Types are a table with a promotion step; attributes are `x.<vendor>.<key>` per D2.
- **Embedding-only, no graph.** Loses temporal claims, loses "what asserts X", loses the free
  deterministic tier entirely, and loses the citation-to-polygon chain. Six of the nine query shapes
  in the mine's routing table are answered without an embedding at all.
- **A separate hyperedge table (graphify's `G.graph["hyperedges"]`).** A hyperedge is an entity with
  `n` typed participation edges. One nullable `edge.role` column expresses it; a second table would
  be a second edge model with a second identity rule and a second incremental path.
- **Destructive entity resolution (in-place union-find).** One column cheaper and irreversible. A
  merge decided at generation 3 on 40 mentions may be plainly wrong at generation 40 on 4,000, and a
  knowledge graph is a persistence layer. The append-only log plus a derived `canonical_id` costs one
  indirection and one recompute pass and buys `ow graph unmerge`.
- **Eager community reports.** `max_cluster_size = 10` on 3M entities is ~300k leaf communities plus
  every internal level, ≥400k LLM calls at ~10k tokens ≈ 4B tokens — for a hierarchy a rated BFS
  descent will touch a small fraction of. Demand-materialization with a `member_digest` cache is the
  same artifact at roughly an order of magnitude less money.
- **`graphrag-chunking` as the segmenter.** 388 lines; `TokenChunker` would split a table cell;
  `SentenceChunker` calls `nltk.download("punkt")` at first use and imports a package that is not in
  its declared dependencies. Our segmenter is ~400 lines, block-aligned, table-atomic, heading-aware
  and offline.
