# D7-structure — the pragmatist proposal

## Headline

**There is no deterministic mode and no LLM mode. There is one table set, one writer, and a `pass`
row with a fixed integer `rank`; "zero-LLM" is the value of a column, not a pipeline** — and every
node, edge, claim and chunk is anchored to a `block_id` plus a `TextSpan`, never to a copied string
and never to its own copy of geometry, so "where on the page does this edge come from" is one join
against D2's `block.quad` and an LLM-emitted entity earns its polygon by returning a **short verbatim
quote we locate ourselves**, which is simultaneously the citation mechanism, the grounding gate and
the prompt-injection defence.

---

## Design

### 0. What D2 already gave me, and what is therefore *not* in this design

The single biggest cost saving available here is noticing that `D2-docmodel` already ships most of
what graphrag calls a knowledge model. `block.parent_id + ord` is the containment spine and *is* the
reading order; `rel` already carries `caption_of · note_ref · continues · anchor_ref · heading_of ·
derived_from · supersedes`; `Kind` already has `HEADING/TABLE/TABLE_CELL/FIGURE/CAPTION/FOOTNOTE/
TOC_ENTRY/REFERENCE/BIBLIOGRAPHY/FORM_FIELD/KEY_VALUE`; `block.cite` is already graphrag's
`short_id`; `content_digest` is already the change-detection key; `Trust` is already the tri-state
confidence with `AMBIGUOUS=0` so `MIN()` over a set is the set's trust.

So **L3 does not re-derive document structure.** It derives exactly seven things D2 does not have:
*mentions*, *entities* (with aliases), *semantic edges between entities*, *claims with a validity
window*, *chunks*, *communities and their reports*, and *the residue* (unresolved references and
quarantined rows). Everything else is a join. D2's ruling that "L3 (D7) may not put containment or
intra-document references in its own tables" is not a restriction I work around; it removes about a
third of the work.

Containment is exposed to graph traversal as a **view**, not a table:
`CREATE VIEW ow_contains AS SELECT parent_id AS src_block, block_id AS dst_block FROM block WHERE
state = 0 AND parent_id IS NOT NULL;` — codegraph's "containment is an edge kind so one traversal
answers everything" (`codegraph/src/types.ts:56-70`) without a second representation of the spine.

### 1. One model that carries graphrag and graphify without a mode switch

graphrag's seven types and graphify's tri-state confidence are **not two models to choose between.**
They are orthogonal: graphrag's `data_model/` has no confidence axis of any kind (verified — no
`confidence` field on `Entity`, `Relationship` or `Covariate` in
`graphrag/packages/graphrag/graphrag/data_model/`), and graphify has no claim layer, no community
layer and no chunk type. The join between them is a `pass` row.

| graphrag type | omniweave | note |
|---|---|---|
| `Document` | D2's `doc` | already exists; not duplicated |
| `TextUnit` | `chunk` | `Identified`, not `Named` — no `title` column. A chunk is addressed, never named |
| `Entity` | `entity` + `entity_alias` | the alias set is the fix for `clean_str(x.upper())` title keying (`graph_extractor.py:139-141`) |
| `Relationship` | `edge` | endpoints are `entity_id`, never titles; plus the **observation site** |
| `Covariate` | `claim` | generalized: open `claim_type`, `t_start/t_end/t_precision`, and the source is a *reference*, not a copy |
| `Community` | `community` + `community_member` | `level` is INTEGER (graphrag's `str`↔`int` drift, `index/update/communities.py:52`, fixed) |
| `CommunityReport` | `community_report` | plus `staleness`, which graphrag has no notion of |

And graphify's columns ride on **every** L3 row: `pass_id` (→ `producer_id`, the reproduction tuple;
→ `pass.kind`, codegraph's "which mechanism"), `trust` (D2's `Trust`, graphify's
`EXTRACTED/INFERRED/AMBIGUOUS`), `score`/`score_kind` nullable together, plus D2's
`origin_operator` and D3's `origin_driver` / `driver_schema_v` / `restriction_bits` and D4's
`decision_id`.

Two properties make "no mode switch" mechanically true rather than rhetorical:

- **The deterministic-only store is a strict row subset of the LLM-enabled store**, modulo `pass_id`.
  CI gate G-18 builds a fixture corpus both ways and asserts it. So `ow graph build --allow-billed`
  on Tuesday *adds* rows; it never rewrites one, and every retrieval mode, CLI command and serve
  response works identically over both.
- **Tier-scoped replacement is a SQL predicate, not a code path.** graphify's `build_merge` needs
  `_is_ast_tier(item)` and a stated COEXIST rule (#2333/#2336, `build.py:1652-1680`) because AST and
  semantic node sets share one JSON blob. Here it is
  `DELETE FROM edge WHERE pass_id IN (SELECT pass_id FROM pass WHERE doc_ord=? AND gen=? AND kind=?)`.

### 2. The pass ladder — deterministic before LLM, as a schedule with a number

Eleven pass kinds with a **fixed integer rank**. The scheduler runs them in rank order and a pass at
rank *r* may only read rows emitted at rank < *r*.

| rank | `pass.kind` | cost class | input | emits |
|---|---|---|---|---|
| 0 | `spine` | FREE | `block` tree + `rel` | one structural entity per HEADING/TABLE/FIGURE/FORM/TOC block + `heading_of`-derived `defname`s |
| 1 | `lexicon` | FREE | `block.text` × `entity_alias` | mentions of already-known entities (Aho-Corasick over `entity_alias.norm`) |
| 2 | `pattern` | FREE | `block.text` | typed literals + **defined terms**: dates, money, ISO/DOI/ISBN/LEI/case numbers, emails, URLs, `§`/`¶` refs, `"X" means …`, `Long Name (ABBR)` |
| 3 | `code` | FREE | `Kind.CODE` blocks | tree-sitter symbols and `calls`/`imports` edges (**P5**, grammars are separate distributions) |
| 4 | `link` | FREE | `mark(kind IN ('link','anchor','note_ref'))` | cross-document edges, resolved or an `unresolved_ref` row |
| 5 | `resolve` | FREE | mentions + entities | the entity-resolution funnel; writes `entity_merge` |
| 6 | `llm_entity` | BILLED_API | chunks **not already explained** | new entities, relations |
| 7 | `llm_claim` | BILLED_API | chunks with ≥1 entity | claims with validity windows |
| 8 | `community` | LOCAL_COMPUTE | the edge set | a deterministic Leiden partition |
| 9 | `report` | BILLED_API | communities whose members changed | community reports |
| 10 | `user` | FREE | human input | corrections; the only pass allowed to write `trust = EXTRACTED` by hand |

"Deterministic-first" is enforced as an **exclusion with a measured number**, not a slogan. Rank 6
consumes only chunks whose `coverage_frac` — the fraction of the chunk's body blocks already carrying
a mention from ranks 0–5 — is below `[graph] llm_coverage_floor` (default 0.60). `PassReport`
publishes `coverage_frac` per pass and `ow graph plan` prints the resulting chunk count, call count,
token count and micros **before anything is spent**. On a structured corpus (contracts, filings,
manuals) I expect 40–60% of chunks excluded; on scanned narrative prose I expect near zero, and the
design's honest answer is that the number is printed rather than assumed.

The **type vocabulary is corpus metadata, derived, never a config default.** graphrag's
`DEFAULT_ENTITY_TYPES = ["organization","person","geo","event"]` (`config/defaults.py:41`) is why
"graphrag doesn't work on my domain". `ow graph types --propose` runs a deterministically sampled
40-chunk pass (`blake2b(chunk.cite ‖ salt) % 10000`, never RNG) and prints a vocabulary a human
commits to `omniweave.toml [graph] entity_types`; the vocabulary's digest enters the LLM cache key.
With an empty vocabulary the LLM passes **refuse** rather than fall back to four news types. An
out-of-vocabulary type is kept as `type='unknown'` with `raw_type` preserved — D2's `raw_kind` idiom,
never a drop.

### 3. Grounding by quote — one mechanism, three jobs

An LLM cannot reliably emit character offsets. So the extraction schema does not ask for them. Every
emitted entity, relation and claim carries `cite` (a `d7#412` block token that was in the prompt) and
`quote` (≤ 300 chars, claimed verbatim). The host then:

1. checks `cite` is one of the block cites the prompt actually supplied → else `quarantine(reason='dangling_endpoint')`;
2. computes `i = normalize_k(block.text).find(normalize_k(quote))` → if `i < 0`,
   `quarantine(reason='ungrounded')`;
3. writes a `mention` row with `(block_id, ts_a=i, ts_b=i+len)`.

That one step does three jobs at once:

- **Citation and polygon.** The mention's span resolves to a page and a `Quad` (§5).
- **Hallucination gate.** graphrag's `filter_orphan_relationships` (`extract_graph/utils.py:14-52`)
  drops relationships naming a non-existent *entity title*; this drops anything naming non-existent
  *text*, which is a strictly stronger and span-level test. `grounded_frac` per pass feeds D4's
  already-declared day-one signal `verify.grounded_field_frac`.
- **Injection containment.** An entity invented by an instruction the document carried cannot be
  quoted from the document's own prose, so it is quarantined by construction rather than by a
  classifier.

Dropped rows are **kept, not deleted** (`quarantine`, with `payload` and `reason`), because
graphrag's own comment concedes the case: a hallucinated name is very often a real entity the
extractor failed to emit a row for in that chunk.

### 4. Confidence and provenance — four axes, D2's names, no new vocabulary

Every L3 row carries `pass_id NOT NULL`, and `pass` carries `producer_id` (D2's `Producer`, the
reproduction tuple with `model_rev` as an exact SHA), `kind`, `cost_class`, `origin_driver`,
`driver_schema_v`, `restriction_bits`, `decision_id`. Every node/edge/claim/mention row additionally
carries `trust INTEGER NOT NULL` and `score`/`score_kind` nullable together.

Four rules, each with an enforcer:

1. **Absent ⇒ weakest.** `trust` has no column default; the reader maps a missing wire field to
   `AMBIGUOUS`. This is the explicit fix for graphify's `first_present(..., default="EXTRACTED")`
   (`callflow_html.py:210-217`).
2. **A migration may only downgrade.** graphify's own words: *"alias recovery is not provenance"*
   (`build.py:205-231`). Enforced by a migration lint that rejects any statement raising `trust`.
3. **An LLM pass may never mint `EXTRACTED`.** Enforced twice: the sink clamps
   `effective_trust = min(proposed, PASS_TRUST_CEILING[kind])`, and a SQLite `BEFORE INSERT` trigger
   aborts with `OW_G_TRUST_CEILING` when `pass.rank >= 6 AND NEW.trust > 1`. A driver *proposes*
   trust; only the runner sets it — the same asymmetry D3 already enforces for `confidence`,
   `origin_driver` and `was_cache_hit`.
4. **Confidence must have three consumers or it rots.** It has five: ranking (`edge_review` /
   `entity_rank` partial indexes; `MIN(trust)` over a chunk), review surfaces
   (`ow graph residue` sorts uncertain first, graphify's `order = {AMBIGUOUS:0, INFERRED:1,
   EXTRACTED:2}`), rendering (serve marks sub-`EXTRACTED` claims), retrieval (a `trust < 2` edge is
   excluded from the identity channel), and the insight surface (graphify's `_surprise_score`
   *inverts* it — uncertain connections are the interesting ones). The useful predicate is
   `(trust, relation, boundary_crossed)`, exactly as graphify found: an `INFERRED` `references` edge
   across a trust-class boundary is resolver noise; the same trust on `semantically_similar_to` is
   the signal.

### 5. How a graph edge points back to a polygon on a page

**No L3 table stores geometry.** That is invariant G-1 and it is a CI grep. The chain is:

```sql
SELECT b.doc_ord, b.gen, b.page, b.cite, b.quad, b.addr, b.os_kind, m.ts_a, m.ts_b,
       m.locus_precision
FROM edge e
JOIN mention m ON m.mention_id = e.src_mention_id
JOIN block   b ON b.block_id   = m.block_id
WHERE e.edge_id = ?1;
```

`mention.block_id` is D2's durable surrogate, so `rebind` carries it across a re-parse. The polygon
is `block.quad`, in D2's one stored frame (topleft, 1/1000 pt, unrotated). Two honesty rules follow
directly from D1's consequence that *"bounding boxes are optional in L2, and their absence must be
representable rather than faked"*:

- `Locus.quad` is `Quad | None`. An anydoc office document has `spatial: none`, so the answer is
  "no polygon; here is `addr` and the `OriginSpan`". **We never synthesize a box.**
- `locus_precision ∈ {char, line, block, page, none}` names what we actually have. When the parse
  driver declared `spatial >= line_bbox` and emitted line-level children, the mention's char range
  narrows to the covering child block(s) and precision is `line`; otherwise it is `block`.

The same join, driven from `chunk_block`, is what highlights a retrieved chunk on a rendered page.

### 6. Entity resolution — graphify's funnel, pushed into SQLite, with a trust boundary

Stages and their published constants (`graphify/dedup.py:242-248`), adopted with two additions:

1. `normalize_id()` — graphify's `ids.py` verbatim in behaviour: bounded NFKC/casefold **fixpoint
   loop** (they do not commute; `İ → i + U+0307` then recomposition), casefold **before** the
   non-word filter, `re.UNICODE` on the filter or every CJK/Cyrillic corpus collapses to one node per
   document. Three invariants with a test each: idempotent, charset-closed, caseless-stable. **One
   function, one module, and the LLM prompt states the same recipe so its ids collide with ours on
   purpose.**
2. Blocking key is `(entity.type, norm)`, so exact matches never enter the fuzzy path.
3. Entropy gate — Shannon ≥ 2.5 bits/char of the normalized label.
4. **MinHash/LSH pushed into SQLite.** 128 permutations, 32 bands, 3-gram shingles with spaces
   stripped (*so "graph extractor" and "graphextractor" share shingles*), threshold 0.7. Signatures
   are computed streaming and only the band hashes are written to a temporary
   `minhash_band(band, bucket, entity_id)` table; candidate pairs are one
   `GROUP BY band, bucket HAVING COUNT(*) > 1`. Memory is O(1) in the entity count instead of
   512 B/entity. Cap `MAX_CANDIDATE_PAIRS = 5_000_000`; above it the threshold rises in 0.05 steps
   and the run reports it.
5. Jaro-Winkler ≥ 92.0, with **plain Jaro** for cross-document labels ≥ 12 chars (Winkler's prefix
   bonus over-fires across documents). Implemented in-house (~40 lines, property-tested against
   published vectors) rather than taking `rapidfuzz`, because a score change in a dependency silently
   changes *durable* merges — the risk digest's own pin policy would otherwise force an exact pin
   with a named owner and a refresh rota.
6. `+5.0` community boost when both nodes already share a community and `min(len) >= 12`. Graph
   structure as evidence for identity, at zero cost.
7. **Eight negative guards**, applied to the deterministic path *and* re-applied before the LLM band
   sees a pair: prefix containment (`Auth` vs `AuthService`), numeric tokens differ, content-token
   swap, short labels merge only on a same-length single-char substitution, variant/SKU suffix pairs
   under 12 chars, file/document-anchored nodes in different documents, structural entities never
   label-merge (graphify's rule that code nodes never label-merge — for us, a `spine` entity's
   identity is its `block_id`, not its heading text), and — my addition —
8. **the trust-class boundary.** An entity whose observations include a document with
   `unit.trust_class = 'untrusted_external'` (D4's day-one signal) is **never** automatically merged
   into an internal-only entity. `cross_trust_class_merge ∈ {never, llm_band_only, allow}`, default
   `llm_band_only`, and such a merge lands `AMBIGUOUS` with a review row.
9. Union-find with a deterministic survivor, then an **append-only `entity_merge` journal** with
   `rule`, `score` and `guard_trace`. `ow graph unmerge <merge_id>` restores. Reversibility, not
   prevention, is the affordable answer to a wrong merge.
10. The `[75.0, 92.0)` band goes to an LLM in batches of 30, budgeted through D4 like any other
    billed call. Absent a model it is a **no-op that is counted and reported**, never a silent
    threshold change.

Two additions of my own that pay for themselves on documents:

- The `pattern` pass mints `abbrev`/`expansion` aliases from `Long Name (ABBR)` and
  `"X" means …` with `trust = EXTRACTED`. Acronym pairs are the single largest class the fuzzy
  funnel provably cannot catch (`IBM` vs `International Business Machines` scores far below 92), and
  documents state them explicitly far more often than prose does.
- The resolution key is `(normalized_label, type)`. Type is a *blocking* dimension, not a tiebreak.

### 7. Chunking — block-anchored, ~150 lines, and why `graphrag-chunking` is rejected

D1 left this open: *"Does `omniweave-graph`'s dependency on `graphrag-chunking` earn its Python
ceiling? Settled by D7 measuring what `graphrag-chunking` supplies that ~400 lines of our own chunker
would not."* I read all 388 lines. It supplies less than nothing, and four of the reasons are
disqualifying under rulings already on disk:

1. **Undeclared dependency plus unauthorised egress on the extraction path.**
   `graphrag_chunking/sentence_chunker.py:9` does `import nltk`, and
   `graphrag_chunking/bootstrap_nltk.py:19-30` calls `nltk.download()` **eight times** at runtime.
   `graphrag-chunking/pyproject.toml` declares `dependencies = ["graphrag-common==3.1.2",
   "pydantic~=2.13"]` — no `nltk`. That is the `cairosvg` defect class, and it fails D1 gate G3
   (import-graph scan) and G15 (no egress compiled in) and D3's `needs_network = false`.
2. **Its provenance is not merely absent, it is wrong.** `token_chunker.split_text_on_tokens` emits
   *overlapping* chunks (`start_idx += chunk_size - chunk_overlap`), while
   `create_chunk_results.py` assigns `start_char = 0` then `end_char = start_char + len(chunk) - 1`
   then `start_char = end_char + 1`. At the shipped default `size=1200, overlap=100`, every chunk
   after the first carries a `start_char` overstated by ~1/12 of a chunk, and the error accumulates
   linearly. Anything built on those offsets cites the wrong text.
3. **Its unit is a flat `str`.** Under D2 a character range in a serialized view is a `RenderSpan`
   and requires a `SpanMap`, and *"spanmap:false output may never be cited"*. A chunker that takes a
   string cannot produce a citable chunk.
4. `requires-python = ">=3.11,<3.14"` contradicts D1's no-upper-bound rule for first-party
   distributions, and `ChunkingConfig` is `ConfigDict(extra="allow")`, which D1 explicitly overruled.

**Our chunker never sees a string.** It walks D2's `block_read` index in `(page, ord)` order over
`Layer.BODY`, accumulates whole Blocks to `chunk_target_tokens` (1200), **never splits a Block**,
prefers a heading boundary, treats a table as one chunk (row-windowed above budget), and overlaps by
**whole blocks** (`chunk_overlap_blocks = 1`). Consequences: no character arithmetic anywhere;
`chunk.content_digest = blake3_128(canonical([b.content_digest …]))` is a merkle over D2's digests so
an unchanged chunk survives a re-parse for free; `heading_path` gives docling's `contextualize()` at
zero cost; and every chunk resolves to pages and polygons through `chunk_block`. `token_est` uses a
documented byte heuristic (`ceil(utf8_len/4)`) unless the embed/LLM driver supplies a real tokenizer
through `DriverIO`; `tokenizer_id` is stamped, so a chunk built under a different tokenizer is a
different chunk. The estimate only *sizes* a chunk — D4 bills on actual tokens — so an estimate error
never becomes a wrong bill.

**Embedding policy** (D5 owns the index; D7 owns the policy): exactly three things are embedded, each
named to one consuming retrieval mode — `chunk` text (basic/local), `entity.description` (mention →
node resolution), `community_report.full_content` (thematic). Relationships are **not** embedded.
The key is `chunk.content_digest`, not `chunk_id`: LEANN's
`passage_id_scheme ∈ {sequential, content_hash}` fork resolved for a re-ingested corpus, and D2's own
open question answered from D7's side — D5 owns the final call.

### 8. Incremental maintenance — what recomputes when a document changes

Delta detection is D2's, not a new mechanism: `doc_key` over normalized source bytes, then graphify's
**racily-clean stat rule** — `indexed_at_ns` captured *before* the content read, an entry trusted only
when `mtime_ns + 2s <= indexed_at_ns`, an entry lacking the field untrusted rather than trusted, and
the stat memo keyed by the *salt* rather than the absolute path. Never `(size, mtime)` alone.

After `rebind` commits a new `gen`, its `RebindReport` tells us exactly which `block_id`s carried,
which were revised, which are new and which retired. The L3 recompute rule, in four lines:

```
carried, content_digest unchanged   ⇒ every L3 row observed at that block SURVIVES UNTOUCHED
carried, content_digest changed     ⇒ DELETE L3 rows for that block, per pass kind; re-run ranks 0..5
new block                           ⇒ run ranks 0..5 over it
retired block                       ⇒ ON DELETE CASCADE takes its mentions, edges, claims, defnames
```

Note the key: **`content_digest`, not `block_id`.** D2 deliberately excludes geometry, spans, marks,
`producer_id`, `trust` and `x` from `content_digest`, so a parse-driver upgrade that jitters a bbox
or re-accounts bytes does **not** re-bill a single LLM extraction. If `rebind` quarantines the new
generation, the graph stays on the old `gen` — correct, and it means a blocked upgrade blocks graph
freshness, which is stated rather than hidden.

**The convergence key — `defname_delta`.** codegraph's `definitionDelta` (`src/extraction/index.ts:
108-132`) is the piece that makes incremental *correct* rather than merely fast, and it is the piece
graphrag lacks. The document analogue is the `defname` table: globally-resolvable identifiers minted
by deterministic passes — section numbers, figure and table labels, defined terms, citation keys,
anchor ids, entity aliases. `defname_delta` is the **per-document symmetric difference of
`(doc_ord, name, kind)` triples across the store phase**. Then:

- every `unresolved_ref` whose `retry_key` is in `defname_delta` is re-resolved (bounded query on the
  partial index `WHERE status='failed'`, because on a healthy corpus the pending set is empty and the
  failed set is the only population worth indexing);
- every *already-resolved* edge whose `resolution_witness` is in `defname_delta` is re-bound;
- a body-only edit leaves `defname_delta` empty, which is the common case and costs nothing.

The residue is data, not a log line. `unresolved_ref` rows are inserted `pending`; a resolution pass
either **deletes** the row (resolved) or marks it `failed` and writes `retry_key`. omniweave mints
these constantly — a citation to a document not yet ingested, a cross-reference to a figure in
another PDF, a caption naming a section number — and "the corpus grew and now this link resolves"
becomes a bounded query instead of a re-index.

**Communities: re-cluster always, re-report only what changed.** graphrag inverts this exactly —
`index/update/communities.py:44-70` offsets delta community ids by `old_max+1` and concatenates, so
after an update an entity present in both halves lives in two unrelated hierarchies with two separate
reports and global search map-reduces over both. Detection is cheap; reports are the expensive
artifact. So:

- Clustering is a **pure function** returning a partition (graphify's `cluster()` does not mutate the
  graph), with a fixed seed, a sorted edge list and direction-normalized deduplication — all three of
  graphrag's determinism mechanisms, kept.
- A community's durable identity is `ckey = blake3_128(sorted member entity keys at that level)` —
  content-addressed, like everything else in this framework. Leiden's own integer ids are never
  exported and never held by anything.
- New partition → old partition matching is **Jaccard ≥ 0.9 at the same level**. A match carries the
  old `community_id` and its report, with `staleness = 1 - jaccard`. A report regenerates when
  `staleness > report_refresh_staleness` (0.15) or the community is new. `report_regen_cap` (500)
  bounds a run; exceeding it is a refusal naming `ow graph report --force --cap N`, not a surprise
  bill.
- `use_lcc` is **off**, permanently. graphrag's default silently discards every entity outside the
  largest connected component, which on a heterogeneous document corpus is most of the graph.
- Oversized communities split at 25% of the graph (relative, per graphify) rather than graphrag's
  absolute `max_cluster_size = 10`, plus a cohesion re-split below 0.05 at ≥ 50 nodes. graphrag's
  absolute cap is what produces ~300k leaf communities on 3M entities and hence ≥400k report calls.
- `degree`, `frequency`, `doc_count` and `combined_degree` are recomputed by **one SQL statement each
  after every merge** — graphrag recomputes edge degrees and leaves node `degree` at `"first"` with a
  literal `# todo` (`index/update/entities.py:66`), an asymmetry a reviewer can check in ten lines.

### 9. Cost control on the LLM path — zero new machinery

Structure extraction's billed passes are **D4's `Rung.ENRICH`**, whose own definition is *"cross-part
/ cross-block model pass, scoped by block type, non-fatal"*. I add three lanes to D4's open `LANES`
registry — `entities`, `claims`, `community` — and nothing else. Consequences, all free:

- Every billed extraction writes a `route_decision` row with its read set, its `est_spend`, its
  `reserved_micros` and its `cause`. `omniweave route explain` already replays it.
- Budget is D4's `[budget.per_unit]` and `admit()`. `evaluate()` never sees the ledger; exhaustion is
  written back as `budget.exhausted` and the DEGRADE rule fires.
- Retries are the `REGEN` rung, strictly serial, charged to the same per-unit budget. This is the
  structural fix for the 64× amplifier (`olmocr/pipeline.py:107,1221` — 8000 tokens × 8 retries, and
  `:343-350` fires remaining retries *in parallel* on an idle queue). **Never parallel fan-out on a
  metered backend.**
- `unit.trust_class = untrusted_external` raises D4's `audit.rate` from 0.005 to 0.05 on exactly the
  documents whose extractions are most worth sampling.

Four cost mechanisms are mine:

1. **The unit of billed work is the document (`unit_part = ''`), and resumability lives in the cache,
   not the work table.** D2 settled that document-level structure is `(unit_uri, unit_part=NULL)` and
   D4 folds NULL to `''`; I do not re-litigate it. Instead, each chunk's call is content-addressed on
   `sha256_canonical({chunk.content_digest, prompt_fp, schema_version, type_vocab_digest, model_id,
   model_rev, sampling})`, so a document that dies at chunk 900 of 1,000 re-runs with 900 cache hits.
   That is precisely what graphrag's cache buys, at no new table.
2. **Cost-tiered cache namespacing** (graphify's rule, verbatim): free-to-recompute artifacts get a
   producer-version namespace (`graph/ast/v{ver}-s{schema}/`) so an upgrade invalidates them; **paid
   artifacts do not** (`graph/semantic/p{prompt_fp}/`), so a bug-fix release never re-bills. This is
   also why D3's `schema_version` and not `driver_version` enters the cache key.
3. **The gleaning loop is one schema field, not a second call.** graphrag pays `2 × max_gleanings`
   calls per chunk on a monotonically growing conversation, with the continuation gate comparing the
   response to the exact string `"Y"` (`graph_extractor.py:83-119`) — any preamble reads as "no". My
   schema carries `"complete": bool`; a second call fires only when `complete = false` **and** the
   budget admits, capped at one. Expected 1.0–1.3 calls/chunk against graphrag's fixed 2.0: a 35–50%
   cut on the dominant line item, from one boolean.
4. **`ow graph plan` spends nothing and prints the bill.** It runs ranks 0–5, computes
   `coverage_frac`, and prints chunks / calls / tokens / micros. `ow graph build` refuses to run a
   rank ≥ 6 pass without `--allow-billed`, and `[graph] enabled_passes` defaults to
   `["spine","pattern","link","resolve"]` — **no LLM pass is on by default**, which is the same
   fail-closed posture D4 already applies to a watcher.

Order-of-magnitude, derived from the evidence rather than asserted: a 5,000-page corpus at D2's
60–120 blocks/page is 300k–600k blocks ⇒ ~40k chunks at 1200 tokens. At 1.3 calls/chunk with ~3.5k
prompt and ~600 completion tokens (graphrag's measured shape), that is ~52k calls, ~180M prompt and
~31M completion tokens. At $0.20/1M in and $1.00/1M out ≈ **$67**, before the coverage exclusion.
With 50% exclusion, ≈ $34. Deterministic ranks 0–5 over the same corpus: an Aho-Corasick scan plus
regexes at ~1–3 µs/block/pass ⇒ **seconds**, $0. Those two lines side by side are the argument for
the ordering.

### 10. Prompt-injection-carried false entities

A knowledge graph is a persistence layer, so one successful injection poisons **every future
retrieval**, not one turn. Five controls, in order of how much they actually buy:

1. **The grounding gate (§3).** Structural, cheap, and it is the only control that catches an
   invented entity rather than an invented instruction.
2. **The trust ceiling (§4.3).** An LLM pass cannot mint `EXTRACTED`. Enforced by a trigger, so no
   downstream consumer can be tricked into treating injected content as deterministic fact.
3. **The trust-class merge boundary (§6.8).** Injection's *payoff* is poisoning retrieval for other
   documents, and the alias table is the vector. Cutting automatic cross-boundary merges is the
   single highest-leverage containment here.
4. **The wrapper**, vendored from `vendor/graphify-security/` at a pinned SHA (D1 already vendors
   this file), with graphify's three known defects fixed: escape the path interpolated into the
   `<untrusted_source path=… sha256=…>` attribute; **defang a copy** — graphify's zero-width
   insertion shifts every later byte offset by 3, which would break the `str.find` grounding this
   design depends on, so grounding is computed against the *undefanged* block text; and drop the
   heading-shaped sentinel `^###\s*instructions?$`, which matches `## Instructions` in any manual,
   RFP or SOP. Ship graphify's own honest claim verbatim: it *"does not make injection impossible,
   but changes it from 'works on first try' to 'requires evasion.'"*
5. **Shape refusals and output sanitisation.** `MAX_ENTITY_LABEL = 200` chars (a "name" longer than
   that is an instruction); a label matching a chat-template sentinel form `<\|[A-Za-z0-9_.\-]{1,64}\|>`
   is quarantined `OW_G_INJECTION_SUSPECT`; and — the direction nobody in the collection covers —
   every entity label, description and community report that re-enters a prompt or an MCP response
   goes through `sanitize_label` from the same vendored module. The prompt carries **only** `cite`,
   `ecite` and `ccite` tokens: no `block_id`, no `entity_id`, no `addr`, no file paths.

graphrag's `RAI_TRANSPARENCY.md` is the only documented cross-prompt-injection evaluation programme
in the collection and it ships the sentence *"the system is designed for trusted users"*. That is
disqualifying as omniweave's posture, and the replacement is a stated one: **untrusted by default,
grounded by construction, capped at `INFERRED`, and quarantined rather than dropped.**

---

## Concrete shape

### `packages/omniweave-graph/src/omniweave_graph/`

```
omniweave_graph/
├── omniweave-driver.toml         # one card per shipped derive driver (D3 §card)
├── schema/
│   ├── graph.sql                 # the DDL below; installed as model_version 1.1 (MINOR, additive)
│   └── migrations/0001_graph.sql
├── model.py        PassKind PASS_RANK PASS_COST PASS_TRUST_CEILING · EntityDraft EdgeDraft
│                   ClaimDraft MentionDraft ChunkDraft UnresolvedDraft · PassReport · Locus
├── ids.py          normalize_id / make_key  — 3 invariants, 3 tests, bounded NFKC/casefold fixpoint
├── sink.py         GraphSink — the ONLY writer of L3 tables; clamps trust; one txn per pass
├── passes/
│   ├── spine.py    rank 0   structural entities from the block tree
│   ├── lexicon.py  rank 1   Aho-Corasick over entity_alias.norm
│   ├── pattern.py  rank 2   typed literals + defined terms + abbreviation pairs
│   ├── link.py     rank 4   marks -> cross-doc edges | unresolved_ref
│   ├── resolve.py  rank 5   the funnel (below)
│   ├── llm.py      ranks 6,7  chunk -> structured output -> grounding gate -> sink
│   ├── community.py rank 8  graspologic_native.leiden, probed; ckey; Jaccard match
│   └── report.py   rank 9   changed communities only
├── chunk.py        block-anchored chunker (~150 lines). Never sees a str.
├── resolve/        minhash.py (in-house) · jaro.py (in-house) · guards.py · unionfind.py
├── prompts/        extract_v1.md · claim_v1.md · report_v1.md · tiebreak_v1.md · schema/*.json
│                   (every file's sha256[:12] is the prompt_fp; CRLF-normalised)
├── jsonschema.py   ~120-line JSON-Schema-2020-12 subset validator (no pydantic requirement)
├── delta.py        defname_delta · rebind consumption · tier-scoped replacement
├── convergence.py  the incremental-vs-full CI gate
└── cli.py          ow graph {plan,build,why,merges,unmerge,residue,types,converge,report}
```

### The DDL — same `.owstore`, same `block_id` FK target, no second representation

```sql
-- ══════════ L3. Added to D2's .owstore at model_version 1.1 (MINOR ⇒ additive only). ══════════
-- Pragma order is D2's and is load-bearing: busy_timeout FIRST (codegraph #238).
-- enum_val gains domains: 'pass_kind', 'relation', 'claim_status', 'locus_precision'.

CREATE TABLE pass (
  pass_id     INTEGER PRIMARY KEY,
  scope       TEXT    NOT NULL CHECK (scope IN ('doc','corpus')),
  doc_ord     INTEGER REFERENCES doc(doc_ord) ON DELETE CASCADE,   -- NULL for corpus scope
  gen         INTEGER,
  kind        INTEGER NOT NULL,                     -- enum_val domain 'pass_kind'
  rank        INTEGER NOT NULL,                     -- FIXED per kind. The extraction order.
  cost_class  TEXT    NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),   -- D2's reproduction tuple
  origin_driver    TEXT    NOT NULL,                -- D3: "derive.entity.llm"
  driver_schema_v  INTEGER NOT NULL,                -- D3: enters the cache key
  restriction_bits INTEGER NOT NULL DEFAULT 0,      -- D3: rides every produced item
  decision_id TEXT,                                 -- D4: NULL only for FREE passes that never route
  status      TEXT    NOT NULL CHECK (status IN ('ok','partial','failed','skipped','pending')),
  inputs      INTEGER NOT NULL DEFAULT 0,
  emitted     INTEGER NOT NULL DEFAULT 0,
  quarantined INTEGER NOT NULL DEFAULT 0,
  coverage_frac REAL,                               -- the deterministic-first metric
  grounded_frac REAL,                               -- LLM passes only -> D4 verify.grounded_field_frac
  spend       TEXT    NOT NULL DEFAULT '{}',        -- canonical JSON of D4's Spend
  started_ns  INTEGER NOT NULL, ended_ns INTEGER,
  -- IFNULL sentinels are mandatory: a nullable natural key silently admits duplicates (codegraph #1034)
  UNIQUE (kind, IFNULL(doc_ord,-1), IFNULL(gen,-1), producer_id)
);
CREATE INDEX pass_doc ON pass(doc_ord, gen, rank);

CREATE TABLE entity (
  entity_id   INTEGER PRIMARY KEY,        -- DURABLE surrogate. Corpus-local. The only FK target.
  ecite       TEXT    NOT NULL,           -- 'e412' — with block cite and ccite, the ONLY prompt ids
  key         TEXT    NOT NULL,           -- normalize_id(label) || x'00' || type
  label       TEXT    NOT NULL,           -- canonical display form (the merge survivor)
  type        TEXT    NOT NULL,           -- from the CORPUS vocabulary; 'unknown' is legal
  raw_type    TEXT,                       -- the producer's own label, kept (D2's raw_kind rule)
  description TEXT,                       -- a description is not an identity
  first_pass_id INTEGER NOT NULL REFERENCES pass(pass_id),
  trust       INTEGER NOT NULL,           -- D2's Trust. NO DEFAULT. Absent on the wire => AMBIGUOUS.
  score REAL, score_kind TEXT,
  frequency   INTEGER NOT NULL DEFAULT 0, -- corpus salience: COUNT(DISTINCT chunk)   (graphrag)
  degree      INTEGER NOT NULL DEFAULT 0, -- graph salience: edge degree              (graphrag)
  doc_count   INTEGER NOT NULL DEFAULT 0,
  trust_class INTEGER NOT NULL DEFAULT 0, -- 1 iff any observation is untrusted_external (D4 signal)
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  state       INTEGER NOT NULL DEFAULT 0, -- 0 live, 1 merged away
  merged_into INTEGER REFERENCES entity(entity_id),
  x           TEXT    NOT NULL DEFAULT '{}',        -- keys MUST be 'x.<vendor>.<key>'
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  CHECK ((state = 1) = (merged_into IS NOT NULL)),
  CHECK (length(label) <= 200)            -- a "name" longer than this is an instruction
);
CREATE UNIQUE INDEX entity_key  ON entity(key) WHERE state = 0;
CREATE UNIQUE INDEX entity_cite ON entity(ecite);
CREATE INDEX entity_rank   ON entity(type, degree DESC, frequency DESC) WHERE state = 0;
CREATE INDEX entity_review ON entity(first_pass_id) WHERE trust < 2 AND state = 0;

CREATE TABLE entity_alias (
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  norm      TEXT    NOT NULL,             -- normalize_id(surface)
  surface   TEXT    NOT NULL,
  kind      TEXT    NOT NULL CHECK (kind IN ('canonical','variant','abbrev','expansion',
                                             'translit','llm','user')),
  pass_id   INTEGER NOT NULL REFERENCES pass(pass_id),
  trust     INTEGER NOT NULL,
  PRIMARY KEY (entity_id, norm, kind)
) WITHOUT ROWID;
CREATE INDEX entity_alias_norm ON entity_alias(norm);     -- the lexicon pass's automaton source

CREATE TABLE mention (                    -- the span. NOT a D2 `mark`: it carries its own provenance.
  mention_id INTEGER PRIMARY KEY,
  block_id   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,     -- D2 TextSpan into block.text. NOT NULL:
                                                    -- a mention without a span is not a mention.
  entity_id  INTEGER REFERENCES entity(entity_id) ON DELETE SET NULL,   -- NULL => unresolved_ref
  surface    TEXT    NOT NULL, norm TEXT NOT NULL,
  pass_id    INTEGER NOT NULL REFERENCES pass(pass_id),
  trust      INTEGER NOT NULL, score REAL, score_kind TEXT,
  locus_precision TEXT NOT NULL CHECK (locus_precision IN ('char','line','block','page','none')),
  CHECK (ts_b >= ts_a),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  UNIQUE (block_id, ts_a, ts_b, pass_id)
);
CREATE INDEX mention_entity ON mention(entity_id, block_id);
CREATE INDEX mention_block  ON mention(block_id, ts_a);

CREATE TABLE edge (
  edge_id    INTEGER PRIMARY KEY,
  src        INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  dst        INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  relation   TEXT    NOT NULL,            -- closed vocab; every value has a written DIRECTION RULE
  -- THE OBSERVATION SITE: where the RELATIONSHIP was seen, not where either endpoint is defined.
  block_id       INTEGER REFERENCES block(block_id)     ON DELETE CASCADE,
  src_mention_id INTEGER REFERENCES mention(mention_id) ON DELETE SET NULL,
  dst_mention_id INTEGER REFERENCES mention(mention_id) ON DELETE SET NULL,
  chunk_id       INTEGER REFERENCES chunk(chunk_id)     ON DELETE SET NULL,
  resolution_witness TEXT,                -- the defname that bound this edge; drives re-bind
  pass_id    INTEGER NOT NULL REFERENCES pass(pass_id),
  trust      INTEGER NOT NULL, score REAL, score_kind TEXT,
  weight     REAL    NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,          -- src.degree + dst.degree (graphrag)
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0, decision_id TEXT,
  x TEXT NOT NULL DEFAULT '{}',
  CHECK (src <> dst),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
-- codegraph #1034 verbatim: INSERT OR IGNORE is a plain INSERT with nothing to conflict on, and
-- SQL NULLs are each distinct, so a nullable natural key needs IFNULL sentinels. The migration
-- that installs this MUST dedup with a GROUP BY matching this expression exactly.
CREATE UNIQUE INDEX edge_identity ON edge(
  src, dst, relation, IFNULL(block_id,-1), IFNULL(src_mention_id,-1), pass_id);
CREATE INDEX edge_src    ON edge(src, relation);
CREATE INDEX edge_dst    ON edge(dst, relation);
CREATE INDEX edge_review ON edge(pass_id) WHERE trust < 2;
CREATE INDEX edge_witness ON edge(resolution_witness) WHERE resolution_witness IS NOT NULL;

CREATE TABLE claim (                      -- graphrag's covariates, generalized. The best schema there.
  claim_id   INTEGER PRIMARY KEY,
  ccite      TEXT    NOT NULL,            -- 'k91'
  subject_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  object_id  INTEGER          REFERENCES entity(entity_id) ON DELETE SET NULL,
  claim_type TEXT    NOT NULL,            -- OPEN vocabulary, corpus metadata (graphrag: covariate_type)
  predicate  TEXT    NOT NULL,
  description TEXT   NOT NULL,
  status     TEXT    NOT NULL CHECK (status IN ('true','false','suspected','superseded')),
  t_start TEXT, t_end TEXT,               -- ISO-8601, partial permitted ('2024', '2024-06')
  t_precision TEXT CHECK (t_precision IN ('year','month','day','datetime')),
  -- graphrag stores `source_text`, a COPY. A copy drifts. We store the reference and the tier.
  block_id   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  quote_tier INTEGER NOT NULL,            -- D2's Quote of the source block, copied at write time
  pass_id    INTEGER NOT NULL REFERENCES pass(pass_id),
  trust      INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0, decision_id TEXT,
  x TEXT NOT NULL DEFAULT '{}',
  CHECK ((t_start IS NOT NULL OR t_end IS NOT NULL) = (t_precision IS NOT NULL)),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX claim_cite ON claim(ccite);
CREATE INDEX claim_subject ON claim(subject_id, claim_type);
CREATE INDEX claim_time    ON claim(t_start, t_end) WHERE t_precision IS NOT NULL;

CREATE TABLE chunk (                      -- graphrag's TextUnit: Identified, NOT Named. No title.
  chunk_id  INTEGER PRIMARY KEY,
  doc_ord   INTEGER NOT NULL, gen INTEGER NOT NULL,
  ord       INTEGER NOT NULL,
  cite      TEXT    NOT NULL,             -- 'd7c12'
  content_digest BLOB NOT NULL,           -- blake3_128 merkle over member block content_digests
  token_est INTEGER NOT NULL, tokenizer_id TEXT NOT NULL,
  n_blocks  INTEGER NOT NULL,
  heading_path TEXT NOT NULL,             -- 'Part II / 7. Risk Factors'  (docling's contextualize)
  first_page INTEGER NOT NULL, last_page INTEGER NOT NULL,
  trust     INTEGER NOT NULL,             -- MIN(block.trust) over members — why AMBIGUOUS=0 matters
  pass_id   INTEGER NOT NULL REFERENCES pass(pass_id),
  UNIQUE (doc_ord, gen, ord)
);
CREATE UNIQUE INDEX chunk_cite   ON chunk(cite);
CREATE INDEX        chunk_digest ON chunk(content_digest);   -- re-chunk reuse + the embedding key

CREATE TABLE chunk_block (
  chunk_id INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('body','overlap')),
  PRIMARY KEY (chunk_id, block_id)
) WITHOUT ROWID;
CREATE INDEX chunk_block_rev ON chunk_block(block_id);

CREATE TABLE community (
  community_id  INTEGER PRIMARY KEY,      -- LOCAL. Never exported, never held by anything external.
  ckey          BLOB    NOT NULL,         -- blake3_128(sorted member entity keys at this level)
  level         INTEGER NOT NULL,         -- INTEGER, not str (graphrag's type drift, fixed)
  parent        INTEGER REFERENCES community(community_id),   -- root parent is NULL, never -1
  size          INTEGER NOT NULL,
  cohesion      REAL,                     -- graphify's cohesion score; graphrag emits none
  member_digest BLOB    NOT NULL,
  run_seed      INTEGER NOT NULL,         -- determinism is auditable, not asserted
  pass_id       INTEGER NOT NULL REFERENCES pass(pass_id),
  UNIQUE (level, ckey)
);
CREATE TABLE community_member (
  community_id INTEGER NOT NULL REFERENCES community(community_id) ON DELETE CASCADE,
  entity_id    INTEGER NOT NULL REFERENCES entity(entity_id)       ON DELETE CASCADE,
  PRIMARY KEY (community_id, entity_id)
) WITHOUT ROWID;
CREATE INDEX community_member_rev ON community_member(entity_id);

CREATE TABLE community_report (
  community_id INTEGER PRIMARY KEY REFERENCES community(community_id) ON DELETE CASCADE,
  title TEXT NOT NULL, summary TEXT NOT NULL, full_content TEXT NOT NULL,
  findings TEXT NOT NULL DEFAULT '[]',
  rank REAL, rating_explanation TEXT,
  built_from_member_digest BLOB NOT NULL,
  staleness REAL NOT NULL DEFAULT 0.0,    -- 1 - jaccard(current members, the members it was written from)
  pass_id INTEGER NOT NULL REFERENCES pass(pass_id),
  trust   INTEGER NOT NULL CHECK (trust <= 1),        -- a report is never EXTRACTED
  origin_operator TEXT NOT NULL, decision_id TEXT,
  restriction_bits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX community_report_stale ON community_report(staleness) WHERE staleness > 0.0;

CREATE TABLE unresolved_ref (             -- codegraph's biggest idea. The residue is DATA.
  ref_id    INTEGER PRIMARY KEY,
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  ref_kind  TEXT NOT NULL,                -- doc_link|anchor|figure_ref|table_ref|section_ref|
                                          -- citation|defined_term|entity_mention
  ref_text  TEXT NOT NULL,
  retry_key TEXT NOT NULL,                -- normalize_id(last significant segment) — name_tail
  candidates TEXT NOT NULL DEFAULT '[]',
  status    TEXT NOT NULL CHECK (status IN ('pending','failed')),   -- resolved => ROW DELETED
  attempts  INTEGER NOT NULL DEFAULT 0, last_seen_ns INTEGER NOT NULL,
  pass_id   INTEGER NOT NULL REFERENCES pass(pass_id)
);
-- PARTIAL: on a healthy corpus the pending set is empty and the failed set is the only
-- population worth indexing (codegraph migrations.ts v8).
CREATE INDEX unresolved_retry ON unresolved_ref(retry_key) WHERE status = 'failed';

CREATE TABLE defname (                    -- the definitionDelta substrate, for documents
  doc_ord  INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen      INTEGER NOT NULL,
  name     TEXT NOT NULL,                 -- normalize_id'd
  kind     TEXT NOT NULL,                 -- section|figure|table|term|citation_key|anchor|alias
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  PRIMARY KEY (doc_ord, gen, name, kind)
) WITHOUT ROWID;
CREATE INDEX defname_name ON defname(name, kind);

CREATE TABLE quarantine (                 -- dropped is not deleted (anti-graphrag)
  q_id     INTEGER PRIMARY KEY,
  pass_id  INTEGER NOT NULL REFERENCES pass(pass_id) ON DELETE CASCADE,
  row_kind TEXT NOT NULL CHECK (row_kind IN ('entity','edge','claim','alias','mention')),
  reason   TEXT NOT NULL,                 -- ungrounded|dangling_endpoint|injection_suspect|
                                          -- type_out_of_vocab|label_too_long|schema_invalid|budget
  payload  TEXT NOT NULL,                 -- the rejected row, canonical JSON
  block_id INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  seen_ns  INTEGER NOT NULL
);
CREATE INDEX quarantine_reason ON quarantine(reason, pass_id);

CREATE TABLE entity_merge (               -- append-only journal; every merge is reversible
  merge_id  INTEGER PRIMARY KEY,
  winner_id INTEGER NOT NULL REFERENCES entity(entity_id),
  loser_id  INTEGER NOT NULL REFERENCES entity(entity_id),
  rule      TEXT NOT NULL,                -- exact|lsh_jw|community_boost|abbrev|llm_band|user
  score REAL, guard_trace TEXT NOT NULL DEFAULT '[]',
  pass_id   INTEGER NOT NULL REFERENCES pass(pass_id),
  trust     INTEGER NOT NULL, undone_ns INTEGER,
  UNIQUE (winner_id, loser_id, rule)
);

-- Containment is D2's. It is exposed to traversal as a VIEW, never a second table.
CREATE VIEW ow_contains AS
  SELECT parent_id AS src_block, block_id AS dst_block
  FROM block WHERE state = 0 AND parent_id IS NOT NULL;

-- The trust ceiling, enforced in the schema and not only in the writer.
CREATE TRIGGER edge_trust_ceiling BEFORE INSERT ON edge
WHEN (SELECT rank FROM pass WHERE pass_id = NEW.pass_id) >= 6 AND NEW.trust > 1
BEGIN SELECT RAISE(ABORT, 'OW_G_TRUST_CEILING'); END;
-- (the identical trigger exists on entity, claim and mention)
```

### Types

```python
# omniweave_graph/model.py — stdlib dataclasses + StrEnum. No pydantic requirement (see CONFLICTS).
class PassKind(StrEnum):
    SPINE="spine"; LEXICON="lexicon"; PATTERN="pattern"; CODE="code"; LINK="link"
    RESOLVE="resolve"; LLM_ENTITY="llm_entity"; LLM_CLAIM="llm_claim"
    COMMUNITY="community"; REPORT="report"; USER="user"

PASS_RANK: Mapping[PassKind, int] = {SPINE:0, LEXICON:1, PATTERN:2, CODE:3, LINK:4, RESOLVE:5,
                                     LLM_ENTITY:6, LLM_CLAIM:7, COMMUNITY:8, REPORT:9, USER:10}
PASS_COST: Mapping[PassKind, CostClass] = {                       # D3/D4's CostClass, not a new one
    SPINE:FREE, LEXICON:FREE, PATTERN:FREE, CODE:FREE, LINK:FREE, RESOLVE:FREE,
    LLM_ENTITY:BILLED_API, LLM_CLAIM:BILLED_API, COMMUNITY:LOCAL_COMPUTE, REPORT:BILLED_API,
    USER:FREE}
# THE CEILING. A driver may PROPOSE a trust; the runner clamps. Mirrors D3-8 exactly.
PASS_TRUST_CEILING: Mapping[PassKind, Trust] = {
    SPINE:EXTRACTED, LEXICON:EXTRACTED, PATTERN:EXTRACTED, CODE:EXTRACTED, LINK:EXTRACTED,
    RESOLVE:INFERRED, LLM_ENTITY:INFERRED, LLM_CLAIM:INFERRED, COMMUNITY:INFERRED,
    REPORT:INFERRED, USER:EXTRACTED}

RELATIONS: frozenset[str] = frozenset({          # closed. Adding one is a SCHEMA MINOR bump.
    "references","cites","defines","supersedes","amends","party_to","located_in","part_of",
    "owns","employs","reports_to","depends_on","measures","conflicts_with",
    "semantically_similar_to","calls","imports","implements"})
# DIRECTION RULE, one line per relation, in prompts/DIRECTION.md and asserted by a doc test:
#   references / cites : source is the CITER, target is the CITED. Never reverse this.
#   defines            : source is the DEFINING block's entity, target is the DEFINED TERM.
#   party_to           : source is the PERSON/ORG, target is the AGREEMENT.
#   supersedes/amends  : source is the NEWER instrument.
# Without this paragraph half your edges point backwards and traversal returns the wrong side.

@dataclass(frozen=True, slots=True)
class Locus:                        # what "where is this on the page" returns. Absence is a value.
    doc_ord: int; gen: int; page: int
    block_cite: Cite; addr: Addr
    span: TextSpan
    quad: Quad | None               # NULL for spatial:'none' drivers. NEVER synthesized.
    origin: OriginSpan              # D2's tagged union — the answer when there is no polygon
    precision: Literal["char","line","block","page","none"]

@dataclass(frozen=True, slots=True)
class MentionDraft:
    block_id: BlockId; span: TextSpan; surface: str
    entity_key: str | None = None
    trust: Trust = Trust.AMBIGUOUS  # a PROPOSAL. sink clamps to PASS_TRUST_CEILING[pass.kind].
    score: float | None = None; score_kind: str | None = None

@dataclass(frozen=True, slots=True)
class PassReport:
    pass_id: int; kind: PassKind; status: str
    inputs: int; emitted: int; quarantined: int
    coverage_frac: float                  # the deterministic-first metric, printed by `ow graph plan`
    grounded_frac: float | None           # LLM passes -> D4's verify.grounded_field_frac
    spend: Spend                          # D4's seven-unit physical vector. No dollars here.

class GraphSink(Protocol):
    """The ONLY writer of L3 tables. Mirrors D2's DocSink. One transaction per pass."""
    def begin_pass(self, p: "PassRecord") -> int: ...
    def add_entity(self, e: "EntityDraft") -> int: ...
    def add_alias(self, eid: int, norm: str, surface: str, kind: str, trust: Trust) -> None: ...
    def add_mention(self, m: MentionDraft) -> int: ...
    def add_edge(self, e: "EdgeDraft") -> int: ...
    def add_claim(self, c: "ClaimDraft") -> int: ...
    def add_chunk(self, c: "ChunkDraft") -> int: ...
    def add_defname(self, name: str, kind: str, block_id: BlockId) -> None: ...
    def add_unresolved(self, u: "UnresolvedDraft") -> None: ...
    def quarantine(self, row_kind: str, reason: str, payload: Mapping[str, Any],
                   block_id: BlockId | None = None) -> None: ...
    def diag(self, d: Diag) -> None: ...                          # D2's Diag, D2's registry
    def end_pass(self, status: str, spend: Spend) -> PassReport: ...   # COMMITS ONE TRANSACTION
# The sink is the ONLY place trust is written, and it is the only place that can raise it above a
# draft's proposal — which it never does. Two enforcers for one invariant: this, and the trigger.

def locate(store, edge_id: int) -> tuple[Locus | None, Locus | None]: ...
def rebuild_after(store, report: RebindReport) -> "DeltaReport": ...   # consumes D2's rebind output
```

### Driver cards (D3 grammar `^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$`)

```
derive.chunk.block        free           document   inproc-eligible   P1
derive.spine.native       free           document   inproc-eligible   P1
derive.pattern.regex      free           document   inproc-eligible   P1
derive.link.native        free           document   inproc-eligible   P1
derive.lexicon.aho        free           corpus     inproc-eligible   P2
derive.resolve.funnel     free           corpus     inproc-eligible   P2
derive.entity.llm         billed_api     document   subproc           P3
derive.claim.llm          billed_api     document   subproc           P3
derive.community.leiden   local_compute  corpus     inproc-eligible   P4
derive.report.llm         billed_api     corpus     subproc           P4
derive.code.treesitter    free           document   subproc           P5 (grammars = separate dists)
```

`inproc` is legal for the FREE first-party passes under D3-9 (`first_party ∧ free ∧ gpu=none ∧
needs_network=false ∧ green fuzz ∧ listed in `[drivers.inproc]`), which matters: a 450k-block scan
must not pay MessagePack framing per unit. Billed passes run `subproc` like every other billed driver.

```toml
# packages/omniweave-graph/src/omniweave_graph/driver.toml  (abridged; one file per driver)
card_schema = 1
[driver]
id = "derive.entity.llm" ; port = "derive/1" ; version = "0.1.0" ; schema_version = 1
granularity = "document" ; deterministic = false
[capability]
consumes = ["doc_fragment","chunk"] ; produces = ["entity","edge","mention"]
[capability.derive]
grounding    = "span_quote"      # none < name_match < span_quote
trust_ceiling = "inferred"       # DECLARED, and asserted absent-above by the conform kit
temporal     = true              # emits claims with a validity window
[hardware]
gpu = "none" ; needs_network = true ; needs_binaries = [] ; imports_torch = false
[isolation]
requires = "subproc" ; progress_ms = 30000 ; wall_ms_hard = 180000 ; batch_max_units = 8
[licence.code] spdx = "Apache-2.0" ; redistribution = "allowed"
[egress] default = "configured_endpoint"
```

### The extraction schema — every leaf nullable, cardinality specified, cites constrained

```json
{ "type":"object","additionalProperties":false,
  "required":["entities","relations","complete"],
  "properties":{
    "entities":{"type":"array","minItems":0,"maxItems":40,"items":{
      "type":"object","additionalProperties":false,
      "required":["name","type","cite","quote","description"],
      "properties":{
        "name":       {"type":["string","null"],"maxLength":200},
        "type":       {"type":["string","null"],"enum":["<corpus vocabulary>","unknown"]},
        "cite":       {"type":"string","pattern":"^d[0-9]+#[0-9]+$"},
        "quote":      {"type":"string","minLength":3,"maxLength":300},
        "description":{"type":["string","null"],"maxLength":400}}}},
    "relations":{"type":"array","minItems":0,"maxItems":40,"items":{
      "type":"object","additionalProperties":false,
      "required":["source","target","relation","cite","quote"],
      "properties":{
        "source":{"type":"string","maxLength":200},"target":{"type":"string","maxLength":200},
        "relation":{"type":"string","enum":["<RELATIONS>"]},
        "cite":{"type":"string","pattern":"^d[0-9]+#[0-9]+$"},
        "quote":{"type":"string","minLength":3,"maxLength":300}}}},
    "complete":{"type":"boolean"}}}
```
```
RULES, each from a measured failure in the collection:
  * EVERY leaf is nullable ([T,"null"]) before constrained decoding — lift's make_properties_nullable.
    Without it the grammar forces the model to INVENT a value, and "left blank" becomes a hallucination.
  * minItems/maxItems on EVERY array — surya disabled guided table-rec outright because a schema with
    no minItems lets greedy decoding legally close the array after one element.
  * `complete` replaces graphrag's CONTINUE/LOOP pair of calls and its `!= "Y"` string compare.
  * `cite` is a pattern AND is re-checked against the cites the prompt supplied. Anything else is
    quarantine(dangling_endpoint).
  * `quote` is the grounding evidence. `normalize_k(block.text).find(normalize_k(quote))` gives the
    TextSpan. No offsets are ever requested from the model.
  * No `bbox`, no `page`, no `id`. Geometry and identity are OURS.
```

### Config

```toml
[graph]
enabled_passes = ["spine","pattern","link","resolve"]   # NO LLM PASS BY DEFAULT. Opt-in is a line.
entity_types   = []             # empty => run `ow graph types --propose`; llm passes REFUSE
chunk_target_tokens  = 1200
chunk_overlap_blocks = 1
llm_coverage_floor   = 0.60     # a chunk this well explained by ranks 0..5 is not sent to a model
max_gleaning         = 1        # fired only when the model says complete=false AND budget admits

[graph.resolve]
entropy_min = 2.5 ; lsh_threshold = 0.7 ; num_perm = 128 ; bands = 32
merge_threshold = 92.0 ; community_boost = 5.0 ; llm_band = [75.0, 92.0] ; llm_batch = 30
cross_trust_class_merge = "llm_band_only"        # never | llm_band_only | allow
max_candidate_pairs = 5000000

[graph.community]
enabled = false
seed = 3735928559               # 0xDEADBEEF, graphrag's, kept — determinism is auditable
max_cluster_size_frac = 0.25    # RELATIVE (graphify), not graphrag's absolute 10
cohesion_split = 0.05 ; cohesion_split_min_size = 50
use_lcc = false                 # PERMANENTLY. graphrag's default discards the rest of the graph.
match_jaccard = 0.90 ; report_refresh_staleness = 0.15 ; report_regen_cap = 500

[graph.limits]                  # ceilings; a tenant cap clamps BELOW, never above (D1's rule)
max_mentions_per_doc = 2000000 ; max_entity_label_chars = 200
max_entities_per_chunk = 40 ; max_relations_per_chunk = 40
max_lexicon_aliases = 500000 ; max_edges_for_clustering = 20000000
```

### CLI

```
ow graph plan            # ranks 0..5 + a PRINTED estimate of chunks/calls/tokens/micros. Spends $0.
ow graph types --propose # a 40-chunk deterministic sample -> a vocabulary a human commits
ow graph build           # runs [graph] enabled_passes; rank>=6 requires --allow-billed
ow graph why e412        # every mention: block cite, page, quad, precision, trust, pass, driver
ow graph merges          # the entity_merge journal, uncertain first
ow graph unmerge 4417    # reverses one merge, by journal id
ow graph residue         # unresolved_ref + quarantine grouped by reason, with counts
ow graph report --stale  # regenerate only reports above the staleness threshold
ow graph converge FIXTURE  # incremental-vs-full equality, the gate below, runnable locally
```

### Invariants and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| G-1 | No L3 table stores geometry. | CI grep over `schema/graph.sql` and the generated `schema.json` for `quad`/`bbox`/`x0`/`poly`; a test asserts `locate()` returns `quad=None` for an anydoc-parsed document rather than a synthesized box |
| G-2 | Every L3 row's provenance is complete and reproducible. | `pass_id` is `NOT NULL REFERENCES pass`; `pass` carries `producer_id`, `origin_driver`, `driver_schema_v`, `restriction_bits`, `decision_id`; `owcheck --graph` asserts no row reaches a `pass` with a NULL producer |
| G-3 | An LLM pass can never mint `trust = EXTRACTED`. | Sink clamps to `PASS_TRUST_CEILING`; a `BEFORE INSERT` trigger on entity/edge/claim/mention aborts with `OW_G_TRUST_CEILING`; a test inserts one directly and asserts the abort |
| G-4 | Every LLM-emitted row is span-grounded in the block it cites. | The sink's grounding gate; `mention.ts_a/ts_b NOT NULL`; fixture whose model output quotes absent text asserts `quarantine(reason='ungrounded')` and `grounded_frac < 1.0` |
| G-5 | A dangling endpoint is quarantined, never dropped and never admitted. | FK on `edge.src/dst`; test asserts `len(candidates) == len(admitted) + len(quarantined)` for every pass |
| G-6 | Edge identity lives in the schema, not the writer. | `edge_identity` UNIQUE expression index with `IFNULL` sentinels; the installing migration dedups with a `GROUP BY` matching the index expression **exactly**; a test inserts the same edge twice and asserts one row |
| G-7 | A migration may only downgrade `trust`. | `tools/migration_lint.py` rejects any statement that raises `trust`; a property test replays the migration corpus and asserts monotone non-increase |
| G-8 | Absent `trust` means `AMBIGUOUS`. | `trust INTEGER NOT NULL` with **no** column default; the wire reader maps missing → 0; test |
| G-9 | Only `cite`, `ecite` and `ccite` may enter a prompt. | The prompt builder accepts only those `NewType`s; semgrep bans `block_id`/`entity_id`/`addr`/`os.fspath` inside `omniweave_graph/prompts/`; a test renders every prompt over a fixture and greps for `p\d+/\d+` and bare integers |
| G-10 | Incremental converges with a full rebuild. | `ow graph converge`: build a 200-document fixture corpus in 20 incremental batches and once from scratch; assert the two stores' `(entity.key set, edge natural-key set, claim natural-key set, defname set)` are equal. **This one gate is the whole incremental correctness story** |
| G-11 | Re-cluster always; re-report only what changed. | Test adds one document and asserts every `community` row was rewritten while `community_report` regenerations == the count whose `staleness > threshold` |
| G-12 | Deterministic passes are deterministic. | Property test shuffles block iteration order and input file order 100× and asserts byte-identical emitted rows sorted by natural key; D3's `deterministic = true` on the card is asserted by the conform kit |
| G-13 | No FREE pass touches the network. | `needs_network = false` on the card + D1 G15's socket-blocked conformance run |
| G-14 | An out-of-vocabulary entity type is kept, never dropped. | `raw_type` column; test feeds a type outside the vocabulary and asserts `type='unknown' AND raw_type=<original>` |
| G-15 | Every merge is reversible. | `entity_merge` is append-only (no UPDATE except `undone_ns`); `ow graph unmerge` round-trip test |
| G-16 | Budget exhaustion is `partial` with a durable marker, never a silent `ok`. | D4's `admit()` + `budget.exhausted` + a `pass.status='pending'` row; test asserts the document ends `partial` with `OW_TRUNCATED_BY_BUDGET` in `diag` |
| G-17 | No L3 row outlives its block. | `ON DELETE CASCADE` from `block`; `owcheck --graph` asserts zero orphans across `mention`/`edge`/`claim`/`defname`/`chunk_block` |
| G-18 | Deterministic-only output is a strict subset of LLM-enabled output. | CI builds one fixture corpus both ways and asserts row-set containment modulo `pass_id`. **This is what makes "no mode switch" a fact rather than a claim** |
| G-19 | `normalize_id` is idempotent, charset-closed and caseless-stable. | Three property tests, plus a Turkish/Greek/CJK fixture (graphify #2614, #811); a test asserts the recipe text in `prompts/extract_v1.md` matches the docstring byte-for-byte |
| G-20 | The residue is queryable, not logged. | `unresolved_ref` and `quarantine` are tables with partial indexes; a semgrep rule bans `logger.warning` inside `passes/` for a dropped row |

### Build order — every phase ships something a user runs

| phase | weeks | ships | user-visible |
|---|---|---|---|
| **P1** | 3 | `pass`/`entity`/`alias`/`mention`/`edge`/`claim`/`defname`/`unresolved_ref`/`quarantine` DDL + migrations · `GraphSink` · `ids.py` · spine + pattern + link passes · `locate()` · delta-by-`content_digest` · `ow graph plan/build/why/residue` | **A zero-LLM, zero-API-key knowledge graph over any parsed corpus, with every node citing a page and a polygon.** `ow graph why` works on day 21 |
| **P2** | 3 | chunker + `chunk`/`chunk_block` · lexicon pass · the full resolution funnel (SQLite-backed MinHash, in-house Jaro-Winkler, eight guards, union-find, `entity_merge`) · embedding-policy handoff to D5 · G-10 convergence gate | `ow graph merges` / `unmerge`; retrieval gets entity and chunk channels |
| **P3** | 4 | `derive.entity.llm` + `derive.claim.llm` behind D4's `ENRICH` rung · the prompt kit · the JSON-Schema subset validator · the grounding gate · the vendored injection wrapper with its three fixes · cost-tiered cache namespacing · `ow graph types --propose` | Paid extraction, with a printed estimate before it spends and a quarantine you can read |
| **P4** | 3 | `derive.community.leiden` (probed `graspologic_native`) · `ckey` + Jaccard matching · reports with `staleness` · rated hierarchical descent handed to D5's retrieval | Thematic search; `ow graph report --stale` |
| **P5** | — | `derive.code.treesitter`, grammars as separate driver distributions with their own licence facts | Code-in-documents |

**≈13 engineer-weeks to P4 for two people.** P1 lands in three.

### What this costs, stated

- **Dependency weight.** `omniweave-graph` third-party deps at P4: **`graspologic-native` only**, and
  only for the optional community pass. It ships as `cp38-abi3` wheels (5 targets; 352 KB
  manylinux-aarch64, 648 KB macOS universal2 — `graphify/uv.lock:1411-1416`), consistent with D1's
  "consume a published abi3 wheel, do not build one". Called directly, bypassing the `graspologic`
  package, whose import pulls umap → pynndescent → numba JIT at **7–19 s** for a layout algorithm we
  never call. Its licence must be verified in-tree at adoption; if it fails, the community pass is
  probed-red and pruned, not substituted. `tree-sitter` and `graphrag-chunking` are both **dropped**
  from D1's provisional list, which takes `omniweave-graph` from a 150 MB ceiling to under 5 MB
  through P3.
- **Storage.** Projection, not a measurement: a 5,000-page corpus at D2's 60–120 blocks/page is
  300k–600k blocks. Deterministic ranks 0–4 yield roughly 0.3–1 node/block ⇒ ~200k entities and
  ~500k edges; at ~120 B/entity, ~90 B/edge, ~40 B/mention that is **~100 MB on top of D2's ~200 MB**.
  Chunks add ~40k rows.
- **Runtime.** Deterministic passes stream over D2's `Doc.blocks()` iterator; peak RSS is one Frame
  (8,192 blocks) plus the lexicon automaton. Aho-Corasick over 1M aliases is 60–120 MB of Python, so
  `max_lexicon_aliases = 500_000`; above it the lexicon pass degrades to exact-`norm` dict lookup
  with `OW_G_LEXICON_DEGRADED`. Resolution memory is O(1) in the entity count because the MinHash
  bands live in a temp SQLite table.
- **Operational burden.** One new CLI namespace, one new migration series, one prompt-fingerprint
  rota (a prompt edit is a cache-namespace change and a re-bill; the `prompt_fp` is CRLF-normalised
  and 12 chars, graphify's shape), and one convergence fixture corpus that must be maintained or G-10
  degrades to a tautology.
- **Cost, at the numbers above.** Deterministic: seconds, $0. LLM: ~52k calls / ~$67 per
  5,000-page corpus before coverage exclusion, ~$34 after 50% exclusion, printed by
  `ow graph plan` before a cent is spent.

---

## Rationale

Three arguments carry this design.

**One store, one writer, one model, and tiering as data.** graphrag ships `Standard` and `Fast` as two
registered pipeline name-lists over one schema — and even there the two have already diverged
(`create_community_reports_text` vs `create_community_reports`, `prune_graph` only in `Fast`), which
is what two pipelines always do. graphify ships two tiers inside one JSON blob and needs
`_is_ast_tier(item)` plus a written COEXIST rule to stop a semantic re-extract from deleting the
file's AST nodes. A `pass` row with a fixed rank is strictly less machinery than either and buys
something neither has: **partial tiering.** A corpus can be 90% deterministic and 10% LLM
*per chunk*, decided by a measured coverage number, which a pipeline-name switch cannot express.
G-18 turns the property into a test.

**Grounding by quote is the load-bearing invention here, and it is cheap.** It is one `str.find`, and
it simultaneously produces the span (hence the page and the polygon), gates hallucination at
span-level rather than name-level, and makes injected entities unquotable by construction. graphrag's
`filter_orphan_relationships` is the same instinct at the weaker granularity of entity names, and it
is the only such gate in the collection. Everything expensive in this area — a verification model, a
second LLM judging the first, a confidence classifier — is downstream of not having this.

**Incremental correctness is one table and one gate.** The evidence is unusually clear: graphrag's
incremental path fails four independent ways (title-only delta with no content hash; `deleted_inputs`
computed and consumed nowhere; node `degree` left at `"first"` with a literal `# todo`; communities
never recomputed, id-shifted and concatenated so global search map-reduces over two hierarchies).
codegraph and graphify independently reached the same correct shape from opposite domains:
content-hash the unit, replace per tier, delete explicitly, and — codegraph's `definitionDelta` — also
invalidate the units whose *resolution* could have changed. The document analogue is `defname`, and
the honest way to ship it is not to argue for it but to write G-10 and let CI decide every commit.

Two smaller calls worth defending. First, **the deterministic passes had to become cheap, not
clever**: with D2 already owning headings, tables, captions, notes and continuations, ranks 0–4 are a
tree walk, a regex bank, an automaton and a link resolver — a few hundred lines, no tree-sitter, no
model, no grammar downloads. That is why P1 is three weeks and produces something a user runs with no
API key. Second, **cost control adds no machinery at all**: `Rung.ENRICH` already exists, `Spend`,
`PriceBook`, `admit()` and `route_decision` already exist, and D4 already declares
`verify.grounded_field_frac` and `unit.trust_class` as day-one signals. Building a second budget
system for the graph would be the single most predictable failure available here.

---

## Tradeoffs

- **Grounding by quote costs recall.** A coreference ("the Company" → Acme Corp) and any
  summarization-shaped fact are quarantined. We buy citability and injection resistance and pay in
  recall, measured by `quarantine_rate` and reviewable through `ow graph residue`.
- **One store means one writer.** Graph passes contend with parse writes on D2's single-writer
  `.owstore`. Passes commit one transaction per document, so a corpus build parallelises the
  *compute* and serializes the *write*. On a fast NVMe this is fine; on a network filesystem it is
  the bottleneck, and the answer is D5's Postgres tier, not a second SQLite file.
- **Content-addressed community keys make report reuse precise and community ids unstable.** Nothing
  outside the store may hold a `community_id`; only `ckey` is portable. That is a real constraint on
  any external system integrating with the graph.
- **No graph database means no Cypher.** Traversal is recursive CTE over an indexed edge table. A
  depth-3 neighbourhood is milliseconds; a six-hop analytic query is not what this store is for.
- **In-house Jaro-Winkler and MinHash cost ~350 lines and buy version stability.** A dependency's
  score change silently alters *durable* merges; the risk digest's own pin policy would force an
  exact pin with a named owner and a refresh rota, which is more ongoing cost than the code.
- **Deterministic-first can hide evidence from the model.** A relation whose evidence spans a block
  the deterministic pass already claimed may never reach an LLM. The audit lane (D4's deterministic
  0.5% sample, raised to 5% on untrusted-external documents) is what detects it; nothing prevents it.
- **`enabled_passes` defaulting to no-LLM will read as "the graph is empty" to some users.** The
  mitigation is that `ow graph plan` always prints what the LLM tier would add and what it would
  cost. Fail-closed on spend is the right default and it will generate support questions.

---

## Failure modes

1. **A corpus of unstructured narrative prose defeats the cost story.** Ranks 0–4 produce a heading
   spine and some dates; `coverage_frac` ≈ 0; the entire bill is the LLM tier. The design does not
   break — the *economics argument* does, and `ow graph plan` makes that visible before payment
   rather than after.
2. **The alias table is the injection blast radius.** One poisoned alias merged into a real entity
   makes every future retrieval for that entity return hostile text. `cross_trust_class_merge`
   bounds it; it does not eliminate it, because an untrusted-external document can be *correct*, and
   an operator who marks a shared drive `internal` has disabled the control with one config line.
3. **Leiden near a modularity plateau.** One new edge can flip the partition wholesale; every `ckey`
   changes, every report is stale, and you face a full re-report bill you did not budget.
   `report_regen_cap = 500` converts the surprise into a refusal naming a command, which is better
   and is still a cliff.
4. **`defname_delta` is only as good as its extractors.** A defined term stated inside a table cell
   that the pattern pass does not recognise produces a link that never re-binds — incremental and
   full diverge, silently, exactly the class G-10 exists for, and G-10 only covers the patterns its
   fixtures contain.
5. **A 4M-cell spreadsheet.** D2 makes every cell a Block, so the pattern pass over a legal-discovery
   XLSX mints millions of literal mentions. `max_mentions_per_doc = 2_000_000`, above which
   cell-level passes are skipped for `page_kind='sheet'` with `OW_G_SHEET_PASS_SKIPPED` and the sheet
   is represented by table-level entities only. Capped and reported; still a real capability loss.
6. **"Apple" the company, the fruit, and Apple Bank all merge.** `(normalized_label, type)` blocking
   and the community boost reduce it; nothing prevents it. The affordable answer is the
   `entity_merge` journal and `ow graph unmerge`, i.e. reversibility rather than prevention.
7. **Community detection has a hard memory ceiling.** 20M edges as Python tuples is 4–6 GB before
   the algorithm allocates. `max_edges_for_clustering = 20_000_000`; above it the community pass is
   **refused with a named limit** and the graph, entity and chunk channels keep working. Stated here
   so nobody discovers it at 30M edges.
8. **Two generations, one graph.** L3 is built over the latest committed `gen` only. If `rebind`
   quarantines a re-parse, the graph stays on the previous generation — correct, and it means a
   blocked parse upgrade silently blocks graph freshness until a human clears the quarantine.
9. **Near-duplicate documents double salience.** `doc_key` dedupes exact bytes; a PDF and its DOCX
   source produce two full graphs and inflate `frequency` and `doc_count`, biasing every ranking
   built on them. D4's `corpus.dup_of` signal is recorded and **not** acted on in v1.
10. **A hostile document that is also the ground truth.** Nothing here distinguishes an attacker's
    document from a customer's genuine one when the customer *is* the attacker. Every control in §10
    is containment, not detection, and graphify's honest sentence is the one we ship.

---

## Why I reject the alternatives

- **graphrag's machinery wholesale.** Take the seven types, the covariate schema, the cache-key
  design, the three-embedding rule, the proportional context budget and the rated hierarchical
  descent. Leave: the entire incremental path (four independent defects, §8); `clean_str(x.upper())`
  title identity, which makes `groupby("title")` the whole of entity resolution and splits any entity
  whose spelling drifts; delimited-text extraction whose record test is `== '"entity"'` **including
  the quotes**, with no counter of unparsed records, so a total parse failure is indistinguishable
  from an empty chunk; `use_lcc = True`; std-based prune thresholds on a power-law degree
  distribution; `max_cluster_size = 10` absolute; four news-shaped default entity types; and
  one-file-per-cache-entry, which at 10M chunks is 20M small files with no compaction.
- **graphify's storage wholesale.** Take `ids.py`, the confidence enum and its consumers, the cache
  (racily-clean stat, prompt fingerprint, miss policy, two roots), the dedup funnel, tier-scoped
  `build_merge`, the injection prompt. Leave `graph.json` + in-memory NetworkX as primary storage —
  its authors state their own ceiling at **50 MB / 100k nodes**, two to three orders below the target
  — the optional `root` anchor (ids carrying path segments from the extracting machine), and
  `default="EXTRACTED"` on a missing confidence, which is the exact inversion of what a provenance
  default must be.
- **A mode switch (a `fast` pipeline and a `standard` pipeline).** Two pipelines is two things to
  keep converging, and graphrag's two have already diverged. One `pass` table with a rank is less
  code and expresses per-chunk tiering, which a pipeline name cannot.
- **A separate graph database (Neo4j, Kuzu, FalkorDB).** A second store, a second consistency
  problem, a second deployment, and a sync layer — and D2 already ruled that a model plus a sync
  layer is the failure whose shape is graphrag's dead `deleted_inputs`. Leiden reads its edge list
  out of SQLite in one query.
- **Vector-only ("just embed the chunks").** No entity resolution, no claims with validity windows,
  no "where does this document assert that", no blast radius, and no bounded absence contract — an
  embedding zero is a statement about the model, not about the corpus.
- **Putting L3 spans in D2's `mark` table.** This answers D2's open question directly: `mark` has no
  `producer_id`, no `trust`, no `score`, is written by the parse driver, and is deliberately excluded
  from `content_digest`. An L3 span carries its own provenance and its own trust, so by D2's own
  stated test it needs its own table. `mention` it is.
- **`graphrag-chunking` (D1's open question, assigned to D7).** All four disqualifiers are in §7:
  eight `nltk.download()` calls at runtime from an undeclared dependency (fails D1 gates G3 and G15
  and D3's `needs_network=false`); `start_char` computed as if chunks did not overlap when the token
  chunker's default overlap is 100, so provenance is wrong and the error accumulates;
  a flat-`str` unit, which under D2 is an uncitable `RenderSpan`; and `requires-python <3.14` plus
  `ConfigDict(extra="allow")`, both of which D1 overruled. It is 388 lines and our block-anchored
  chunker is ~150 with exact provenance.
- **`rapidfuzz` / `datasketch` for the resolution funnel.** These score *durable* merges. A version
  bump that shifts a Jaro-Winkler score by 0.5 silently changes which entities are the same thing,
  months later, with no signal. Exact-pinning them means owning a pin with a named owner and a
  refresh rota; owning 350 lines with property tests against published vectors is cheaper and the
  test suite is the specification.
- **Copying `source_text` onto claims (graphrag's `covariates.source_text`).** A copy of the source
  span drifts from the block the moment a re-parse fixes a ligature. `(block_id, ts_a, ts_b)` plus
  D2's `quote_tier` gives the text through `Doc.block()` and stays correct, and it is what lets serve
  say "byte-identical" only where D2 says it may.

---

## Conflicts and amendments

**One genuine conflict, narrowly scoped.**

D3 states, invariant D3-7: *"A driver never receives a writable `output_root` or `cache_root`, **the
store**, the cache, or the budget ledger"*, and `DriverIO`'s docstring reads *"The ONLY channel a
driver has to the outside. **No Store**, no Cache, no work table, no BudgetLedger, no RunContext, no
writable output_root or cache_root. Not extensible."* Read strictly, a corpus-granularity `derive`
driver — `derive.resolve.funnel` over ~1M entities, `derive.community.leiden` over ~10M edges — must
receive its entire input through `INVOKE` payloads and blob references, because `INLINE_MAX` is
262,144 bytes. That means serializing and re-parsing the whole entity and edge set on every run of a
pass that is first-party, free, deterministic, network-less and `inproc`-eligible under D3-9. It is
pure overhead against an invariant whose stated purpose is preventing a driver from **writing**.

**Minimum amendment:** add one member to `DriverIO`,

```python
def reader(self) -> "StoreReader": ...   # READ-ONLY. Present ONLY when
                                         # effective_isolation == "inproc" AND
                                         # trust in {first_party, vendored}. Absent otherwise.
```

returning a read-only connection opened through jcodemunch's `connect_readonly` ladder that D1
already mandates (`mode=ro` when a WAL sidecar exists, `mode=ro&immutable=1` when it does not). The
absence of this member for `subproc` and third-party drivers is unchanged, so D3-7's actual property —
a driver cannot write, cannot forge a cache hit, cannot poison the cache — is untouched. Without the
amendment the design still works; it just pays a full graph serialization per corpus pass, and I
would rather name that than absorb it silently.

**Two upstream inconsistencies I observed and did not create** (not mine to rule, flagged so the
charter does not inherit them):

1. **D1 vs D2 on `omniweave-core`'s dependencies.** D1: `dependencies = []`, *"ENFORCED BY GATE G1"*,
   and the Rejected section explicitly refuses pydantic in core. D2: *"`omniweave-core` depends on
   `pydantic`, `zstandard` and stdlib `sqlite3`, asserted by a CI test over the resolved closure."*
   These cannot both hold. **This design is neutral to the outcome**: L3's row types are stdlib
   dataclasses with SQLite `CHECK` constraints, and LLM structured output is validated by a ~120-line
   JSON-Schema-2020-12 subset validator inside `omniweave-graph`, so nothing here requires pydantic
   in core either way.
2. **D1's driver `kind` vocabulary vs D3's `Port` vocabulary.** D1 fixes
   `kind = parse | ocr | vlm | embed | llm | structure | connect` and names `omniweave-graph`'s
   drivers `structure.*`; D3 fixes five Ports `acquire | parse | derive | embed | compile` and a
   driver-id grammar whose first segment must be one of those five. Structure extraction is D3's
   `derive/1`. **I use D3's `derive.*` throughout**, since D3 is the ruling that owns the driver
   system and the id grammar is a build-time-checkable regex; the charter should retire `structure`
   from D1's kind list or record the alias.

**Not a conflict:** dropping `graphrag-chunking` from D1's provisional dependency list for
`omniweave-graph` is D1's own open question, explicitly delegated — *"Settled by D7 measuring what
`graphrag-chunking` supplies that ~400 lines of our own chunker would not."* §7 is that measurement.
Dropping `tree-sitter` from the P1–P4 dependency set is a scheduling call, not a repeal: the `code`
pass is P5 and its grammars ship as separate driver distributions with their own licence facts,
because codegraph's 27 vendored grammars at 66 MB with 3 LICENSE files is the outcome to avoid.

---

## Terminology

- **Pass** := one execution of one extraction mechanism over one scope, with a fixed integer `rank`;
  a row in `pass`. The tier (deterministic vs LLM) is a property of the pass, never of the schema.
- **Rank** := the fixed position of a pass kind in the extraction order. A pass at rank *r* may read
  only rows emitted at rank < *r*. This is what "deterministic before LLM" means mechanically.
- **Mention** := a `TextSpan` inside one Block that names an entity, carrying its own producer, trust
  and score. Deliberately not a D2 `mark`.
- **Observation site** := the `(block_id, TextSpan)` where a *relationship* was seen, distinct from
  where either endpoint is defined. graphify's `source_file`-on-edges at block-and-span resolution.
- **Grounding** := locating an LLM-claimed verbatim `quote` inside the block it cited, yielding the
  span. An ungrounded row is quarantined, never admitted and never deleted.
- **Locus** := the resolved answer to "where on the page", carrying `quad: Quad | None`, D2's
  `OriginSpan`, and a `precision` naming what we actually have. A synthesized box is never returned.
- **`defname`** := a globally-resolvable identifier minted by a deterministic pass — section number,
  figure or table label, defined term, citation key, anchor, alias. `defname_delta` is codegraph's
  `definitionDelta` for documents and is the convergence key for incremental indexing.
- **`ckey`** := a community's durable content-addressed identity, `blake3_128` over its sorted member
  entity keys at that level. Leiden's own integer ids never leave the store.
- **Staleness** := `1 - jaccard(a community's current members, the members its report was written
  from)`. A stale report is served with its staleness, never silently.
- **Coverage** := the fraction of a chunk's body blocks already carrying a mention from ranks 0–5.
  The number that decides whether a chunk is worth paying a model for.
- **Residue** := `unresolved_ref` plus `quarantine`. Unfinished business and rejected rows are
  queryable tables with partial indexes, never log lines.

## Open questions

- **What is `coverage_frac` on real corpora?** The whole cost argument for deterministic-first is a
  projection. Settled by running ranks 0–5 over ten real documents per class (10-K, court filing,
  scientific review, RFP, technical manual, scanned correspondence) and plotting the distribution. If
  the median is below 0.2 outside structured corpora, `llm_coverage_floor` becomes per-corpus and the
  economics section is rewritten rather than defended.
- **What is the real quarantine rate of the grounding gate?** Settled by a 500-chunk human-labelled
  audit measuring how many quarantined rows were *true* facts the model simply did not quote. Above
  ~15% and a second, cheaper "quote it again" repair call becomes worth the tokens.
- **Does `graspologic-native`'s licence survive an in-tree read?** It is not vendored in
  `_collections/`, so its LICENSE is unverified here. If it is not permissive, the community pass is
  probed-red and pruned; there is no substitute algorithm, by the same rule that forbids substituting
  a codec.
- **Does the resolution funnel's LLM band earn its cost on documents?** graphify's `[75, 92)` band was
  tuned on code identifiers. Settled by measuring band-hit precision on a labelled 1,000-pair
  document sample; if deterministic precision inside the band is already above ~0.9, the band closes
  and the LLM tiebreak is deleted.
- **Do embeddings key on `chunk.content_digest` or `chunk_id`?** I recommend `content_digest` (LEANN's
  `passage_id_scheme = content_hash`, so a re-chunk after a re-parse does not re-embed). D5 owns the
  call and must measure re-embed cost on a real driver upgrade before deciding.
- **Should `derive.lexicon.aho` run before or interleaved with `derive.resolve.funnel`?** Ranked
  1 and 5 here, so the lexicon only sees entities from a previous run. A second lexicon sweep after
  resolution would raise recall at one extra corpus scan. Settled by measuring the second sweep's
  marginal mention yield on a fixture corpus; below ~2% it stays a single pass.
