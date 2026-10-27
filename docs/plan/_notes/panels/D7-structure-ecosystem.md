# D7-structure — Structure extraction, the knowledge model, deterministic-first graph building
### The ecosystem / operator proposal

---

## Headline

**There is no deterministic mode and no LLM mode.** The knowledge model is one set of tables in the
same `.owstore`, written only by the host through a single `GraphSink`, and the difference between
graphify's zero-LLM AST extraction and graphrag's LLM extraction is *three existing D2 columns* —
`method`, `producer_id`, `trust` — not two subsystems, not two pipelines, not a `Fast` switch. What
makes the order deterministic-first is a **coverage ledger** (`derive_cover`), not a convention: a
billable pass's input selector is literally `blocks WHERE NOT EXISTS a cheaper pass claiming this
(block, lane)`, and a CI query proves zero billed items on covered ground. Entity resolution is
**non-destructive** — mentions are ground truth, an entity is a union-find cluster over an auditable
`merge_edge` table, so `ow graph resolve --split` is a supported operation rather than a re-index.
Communities are re-clustered always and re-**reported** only when a `member_digest` changes, with
reports lazy by default because the arithmetic below shows reports cost 3–6× extraction. Every node,
edge, mention and claim carries D2's four provenance axes verbatim plus D3's `origin_driver` /
`restriction_bits` plus one new bit, `taint`. A third party adds an extractor by writing a
`derive/1` driver that emits NDJSON drafts and knows nothing about ids, resolution, clustering, or
the store — which is the whole reason it can be done in an afternoon.

---

## 0. Conflicts with upstream rulings

I found one genuine conflict, one already-settled naming inconsistency, and one place where D4's
shape needed care rather than amendment. Everything else in this proposal is consistent with D1–D4.

### CONFLICT 1 — D2 forbids the entity/community short ids that global retrieval requires

`_plan/_notes/rulings/D2-docmodel.md`, Terminology, verbatim:

> `cite` := the short per-document token `d7#412`. **The only identifier that may appear in a prompt
> or in model output.**

and in §3:

> `cite` is `d{doc_ord}#{n}` — graphrag's rule that a citation be short enough for a model to emit
> reliably.

That clause, read literally, makes community-level and entity-level retrieval uncitable. graphrag's
`Community`, `CommunityReport` and `Entity` are all `Named`/`Identified` with a `short_id` precisely
because *"Human readable ID used to refer to this community in prompts or texts displayed to users,
such as in a report text"* (`packages/graphrag/graphrag/data_model/identified.py`). A global-search
answer says "communities 3.1 and 3.4 both discuss the indemnity clause"; it cannot say that with a
block cite, because a community is not a block. Forcing every entity reference through a block cite
also destroys the one thing an entity node is for: it is the *join* across documents, so pinning it
to one document's `d7#412` reintroduces graphrag's title-keying bug from the other side.

**Minimum amendment.** Generalise D2's rule from *one token* to *one closed token space*, keeping
its stated intent (short enough to emit reliably, stable enough to resolve, type-tagged) word for
word. Replace the Terminology line with:

> The prompt-safe id space is a **closed set of typed short tokens**, each minted by the layer that
> owns the row and each resolvable by exactly one indexed lookup: `d7#412` (Block, L2),
> `e412` (Entity, L3), `c3.1` (Community, level.ordinal, L3), `k412` (Claim, L3). No other
> identifier — `block_id`, `entity_id`, `addr`, a UUID — may appear in a prompt or in model output.

Cost of the amendment: one sentence, one regex in the prompt-lint, and three `UNIQUE` indexes I
already specify below. Cost of *not* amending: global/thematic retrieval (graphrag's `global_search`,
`DynamicCommunitySelection`) cannot be built at all, and D5 inherits the hole.

### Not a conflict — D1's `structure.*` is already superseded by D3

`D1-substrate.md:152` lists `omniweave-graph/  src/omniweave_graph/  structure.*` as the driver
namespace. `D3-drivers.md` closes the Port set at five and states plainly: *"`structure`, `engine`
and `store` are rejected as Ports"*, with the id regex
`^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$` and *"chunkers and
extractors are both `derive` drivers"*. D3 is the ruling on driver identity and it is later; I use
`derive.*` throughout. Flagging it only so the charter does not copy D1's illustrative table row
verbatim and ship an id that fails its own loader with `CARD_INVALID`.

### Not a conflict — D3 has no `[capability.derive]` vocabulary, and that is fine by construction

D3 defines the capability vocabulary only for `parse` (mine-parse §E11). I define
`[capability.derive]` in §5 below. D3 already covers this case: *"Unknown keys inside
`[capability.<port>]` are ignored with a recorded `CARD_CAPABILITY_UNKNOWN` degradation, because an
unrecognised capability can only make a driver look **less** capable — the one safe asymmetry."* So a
new derive capability key is forward- and backward-compatible with no port major bump. No amendment.

### Not a conflict — gleaning is an `attempt`, not a `Rung`

D4's `Rung` is a closed IntEnum with `ENRICH = 6` at the top and the invariant `child.rung >
parent.rung, ALWAYS`. Extraction lives at `ENRICH`, so a gleaning pass cannot be a *child* decision
without violating monotonicity. It does not need to be: D4's `route_spend` already has
`attempt INTEGER NOT NULL,  -- 1-based; REGEN increments`, and D4's own cost rule is *"Retries are
rungs (REGEN), strictly serial per (unit, part), charged to the same per-part budget"*. A glean is
the same decision, the same driver, serially, charged to the same budget — `attempt = 2`. This is
also the structural fix for graphrag's gleaning loop, whose cost is `2 × max_gleanings` calls per
chunk on a monotonically growing conversation (`graph_extractor.py:83-119`) with a continuation gate
that string-compares to `"Y"`. Ours is a typed `more_available: bool` in structured output, capped by
`policy.max_attempts`, and the cap is a budget dimension rather than a retry count — D4's stated
reason: *"A retry count is not a cost bound because the cost of a retry is not fixed."*

---

## 1. The knowledge model — one shape, no mode switch

### 1.1 What the mode switch actually was

graphrag ships two pipelines over one schema — `_standard_workflows` with `extract_graph` and
`_fast_workflows` with `extract_graph_nlp` + `prune_graph` (`index/workflows/factory.py:52-96`).
graphify ships two tiers inside one graph, distinguished by a predicate `_is_ast_tier(item)` whose
only job is to stop a semantic re-extract from deleting the file's AST nodes
(`build.py:1652-1680`, issues #2333/#2336). **Both are encoding the same fact structurally that D2
already encodes as a column.** D2's `Block` carries `method: Method` with members
`native | text_layer | native_xml | ocr_page | ocr_block | vlm_page | llm | heuristic | roundtrip |
user`, `producer_id` interned into the full reproduction tuple, and `trust: Trust` as an ordered
`IntEnum` where `MIN()` over a set is that set's trust. D3 adds `origin_driver` and
`driver_schema_v` to every produced item, set by the runner.

So: an AST-extracted entity mention is `(method=native_xml, trust=EXTRACTED,
origin_driver='derive.entity.table')`. An LLM-extracted one is `(method=llm, trust=INFERRED,
origin_driver='derive.entity.llm')`. Same row, same table, same index, same query. graphify's
`_is_ast_tier` becomes `derive_pass.cost_class = 'free'`, which is a *card* field, so the host knows
it without importing anything (D3-1).

**Consequence for the tier-scoped replacement rule.** graphify's hardest-won property is that a
re-extract replaces its own contribution *per tier* and nothing else. D-runtime already generalises
this as the stage-ownership invariant: *"an operator's re-run may replace only rows it owns"*, keyed
on `origin_operator`. So `build_merge`'s per-tier replacement is, in omniweave,
`DELETE FROM mention WHERE observed_block IN (:rederive_set) AND origin_operator = :this_pass` —
one predicate, no tier predicate, no `_is_ast_tier`. The bug graphify fixed twice is unexpressible.

### 1.2 The type map — graphrag's seven types onto D2

| graphrag type | omniweave | why |
|---|---|---|
| `Document` | **D2's `doc` row.** Not recreated. | D2 owns it; `doc_key`, `gen`, `status`, `confidence` are already there. |
| `TextUnit` | `derive_unit` (D7-owned) | graphrag conflates the extraction unit with the retrieval chunk and pays for it with a 12k-token context budget split three ways. Extraction wants ~1,500-token windows; retrieval wants precise spans. D5 owns retrieval chunks and **may not write** `derive_unit`. |
| `Entity` | `entity` + `entity_alias` + `mention` | graphrag's entity *is* its title (`clean_str(x.upper())`, `graph_extractor.py:139-141`), which is why an entity whose spelling drifts becomes two nodes and why its entire resolution is `groupby("title")`. Split into a surrogate cluster id, an alias set, and per-occurrence mentions. |
| `Relationship` | `edge` | Keyed on `entity_id`, never a title. Carries `observed_block` — graphify's *"`source_file` is required on **edges**"*, which is what makes "where does this document assert that" answerable. |
| `Covariate` | `claim` | Adopted almost whole. `COVARIATES_FINAL_COLUMNS` (`data_model/schemas.py`) is the best temporal-fact schema in the collection: `subject_id, object_id, covariate_type, type, status, start_date, end_date, source_text, text_unit_id`. `source_text` becomes a span, because D2 already stores the text. |
| `Community` | `community` + `community_member` | Plus graphify's `cohesion` (`cluster.py`) and a `member_digest` for incremental reporting. |
| `CommunityReport` | `community_report` | Plus `report_state ∈ {absent, stale, fresh}` and lazy materialisation. |
| graphify `hyperedge` | **rejected as a table; reified** | graphify stores them in `G.graph["hyperedges"]` beside the graph because NetworkX has no hyperedge — a table with one producer and no query. A hyperedge is an `entity` of kind `group` plus `member_of` edges, which is queryable by every path that already exists. |
| graphify `file_type` | `entity.eclass` from a per-corpus `type_vocab` | `DEFAULT_ENTITY_TYPES = ["organization","person","geo","event"]` (`config/defaults.py:41`) is four news-shaped types and is the source of most "graphrag doesn't work on my domain" reports. Derived per corpus, stored as corpus metadata, never a closed list in config. |
| graphrag `frequency` / `degree` | both, as columns | `frequency = COUNT(DISTINCT mention.derive_unit)` is corpus salience; `degree` is graph salience; `edge.combined_degree` is the edge prior. graphrag recomputes edge degrees on merge and leaves node `degree` at `"first"` with a literal `# todo` (`index/update/entities.py:66`) — ours recomputes both in one pass and a test asserts the symmetry. |
| — | `unresolved_ref` | codegraph's `schema.sql:88-101`, the idea nobody else has, and omniweave will mint these constantly. |
| — | `quarantine` | graphrag's `filter_orphan_relationships` (`extract_graph/utils.py:14-52`) *deletes* dangling edges. A hallucinated entity name is very often a real entity the extractor failed to emit a row for on that chunk. Keep them. |
| — | `merge_edge` | The auditable, reversible substrate of entity resolution. Nobody in the collection has it. |
| — | `anchor` | The `definitionDelta` mechanism, made concrete for documents. |
| — | `derive_cover` | The mechanism that makes "deterministic first" enforceable rather than aspirational. |

### 1.3 Confidence and provenance on every row

Every row in every D7 table carries, verbatim from D2 and D3, with **no parallel names invented**:

```
producer_id      INTEGER  -> producer(...)   the full reproduction tuple, model_rev an exact sha
method           INTEGER  -> enum_val        native_xml | heuristic | llm | vlm_page | user | ...
trust            INTEGER                     0=AMBIGUOUS 1=INFERRED 2=EXTRACTED; MIN() is the answer
score, score_kind  REAL, TEXT                nullable TOGETHER; the scale is named or both are NULL
origin_operator  TEXT                        OWNERSHIP, not trust (D2 §8 / runtime §7.6.1)
origin_driver    TEXT                        D3; set by the RUNNER from the card, never the driver
driver_schema_v  INTEGER                     D3; enters the cache key
restriction_bits INTEGER                     D3; "may I ship this deck" is one indexed predicate
taint            INTEGER                     NEW. 1 = derived from a unit that tripped the
                                             injection detector or from a low-trust source.
```

`trust` is D2's `Trust`, and it is exactly graphify's enum with graphify's own bug fixed: graphify's
reader coerces `first_present(edge, "confidence", "evidence", "provenance", default="EXTRACTED")`
(`callflow_html.py:210-217`) — missing provenance defaulting to the *strongest* claim. D2 already
rules: *"absent ⇒ ambiguous, migrations only downgrade"*. graphify's own writer already gets the
migration half right and says why: *"alias recovery is not provenance"* (`build.py:205-231`).

The digest's rule — *never ship a confidence field with fewer than three consumers* — is met with
four, and each is a named code path, not an intention:

1. **Ranking.** `edge.trust` is a multiplier in D5's fusion; `graphify/analyze.py:216-241` *inverts*
   it for insight ranking (`{AMBIGUOUS:3, INFERRED:2, EXTRACTED:1}`), and both consumers exist.
   The useful predicate is graphify's `(confidence, relation, boundary_crossed)` triple, not
   confidence alone: an `INFERRED refers_to` edge across two unrelated corpora is resolver noise and
   is zeroed; the same trust on `semantically_similar_to` *is* the signal.
2. **Review surface.** `ow graph review` sorts ambiguous-first — graphify's
   `order = {"AMBIGUOUS":0,"INFERRED":1,"EXTRACTED":2}` (`analyze.py:413`).
3. **Rendering.** Serve labels an `INFERRED` assertion and refuses to place an `AMBIGUOUS` one in a
   generated deck without an accompanying block cite.
4. **The gate.** `MAX_TRUST_BY_METHOD[LLM] = MAX_TRUST_BY_METHOD[VLM_PAGE] = INFERRED`, clamped by
   the runner. A hostile document cannot talk its way to `EXTRACTED`. §7.

---

## 2. Deterministic-before-LLM, as a mechanism

### 2.1 Lanes and the coverage ledger

An **extraction lane** is what is being asked for. Registered into D4's open `LANES` registry:

```
anchor    a globally-resolvable name this document DEFINES (section no., figure label, table id,
          defined term, citation key, glossary entry)
xref      a reference this document MAKES to an anchor (here or elsewhere)
entity    a named thing mentioned
claim     a temporal, attributed assertion (graphrag's covariate)
community derived clustering (corpus granularity)
summary   community reports and entity descriptions
```

A pass declares the lanes it produces and, per lane, whether it **covers** a block. Covering means:
*I looked at this block for this lane and my answer is complete.* It is written to `derive_cover`.

```
An LLM pass's input selector is, literally:

  SELECT b.block_id FROM block b
  WHERE b.doc_ord = :d AND b.gen = :g AND b.layer IN ('body','note') AND b.state = 0
    AND NOT EXISTS (SELECT 1 FROM derive_cover c
                    JOIN derive_pass p ON p.pass_id = c.pass_id
                    WHERE c.block_id = b.block_id AND c.lane = :lane
                      AND p.cost_rank < :this_cost_rank)
```

`cost_rank` is `free=0 < local_compute=1 < billed_api=2`, from D3's `CostClass` on the card. That is
the whole ordering rule: **cost class is the order.** No hardcoded pipeline list, no
`_standard_workflows` array whose reordering silently produces wrong output (graphrag
`factory.py:207`, `cls.workflows[name]` with no `KeyError` handling and no declared inputs/outputs).

**The honesty guard.** A pass may only write `derive_cover` when it emitted ≥1 item for that
(block, lane), *or* when it explicitly writes `covered_empty` with a reason string. Otherwise a
cheap pass that silently found nothing would suppress the expensive pass that would have — silent
recall loss shaped exactly like absence. `ow graph doctor` reports `covered_empty` rate per pass per
lane, and a rate above `0.98` is a warning naming the pass, because that pass is almost certainly a
no-op wearing a coverage claim.

**The CI gate.** `test_deterministic_first.py` runs, on the fixture corpus, the query

```sql
SELECT COUNT(*) FROM mention m
JOIN derive_pass p  ON p.pass_id = m.pass_id AND p.cost_rank = 2
JOIN derive_cover c ON c.block_id = m.observed_block AND c.lane = 'entity'
JOIN derive_pass q  ON q.pass_id = c.pass_id AND q.cost_rank < 2;
```

and asserts `0`. That is the difference between a design and a diagram.

### 2.2 The shipped pass ladder

Everything at `free` is on by default. Everything at `billed_api` is off by default, because D3's
project config already says `allow_classes = ["free", "local_compute"]` and *"billed_api is opt-in"*.
This is the single largest adoption decision in the proposal: `pip install omniweave && ow graph
build` costs **$0**, needs **no API key**, and produces a useful graph — graphify's own measurement
is the justification (0.497 recall@10 on LOCOMO, 76% on LongMemEval-S at zero LLM build cost, tying
dense RAG).

| pass_id | class | lane(s) | method | notes |
|---|---|---|---|---|
| `derive.anchor.native` | free | anchor | `native_xml` | OOXML numbering, PDF outline, `kind ∈ {heading, toc_entry, caption, table, figure, formula, reference}` blocks. Zero inference: the label is in the source. |
| `derive.xref.pattern` | free | xref | `heuristic` | "see Figure 3", "§4.2", "[Smith 2019]", "Table 1", "Exhibit A". Locale-aware pattern packs are data files, not code. |
| `derive.entity.table` | free | entity | `native_xml` | Header cells and key/value blocks (`kind ∈ {table_cell, key_value, form_field}`) with `cell.r < table_meta.header_rows`. A header cell *is* an entity type declaration. |
| `derive.entity.gazetteer` | free | entity | `heuristic` | A corpus-supplied term list. `trust=EXTRACTED` on exact match, `INFERRED` on a normalised match. This is the extension point that makes a domain corpus work on day one without a prompt. |
| `derive.entity.nlp` | local_compute | entity | `heuristic` | graphrag's `extract_graph_nlp` shape. Needs `prune_graph`-equivalent statistical filtering — but with **quantiles, not std** (graphrag's `_get_upper_threshold_by_std` on a power-law degree distribution keeps almost everything) and without `remove_ego_nodes=True`, which deletes the single highest-degree node outright. |
| `derive.entity.llm` | billed_api | entity | `llm` | graphrag's extraction, structured output, one attempt + capped glean attempts. |
| `derive.claim.llm` | billed_api | claim | `llm` | graphrag's covariate extraction. |
| `derive.community.louvain` | free | community | `heuristic` | corpus granularity. Default; `networkx.community.louvain_communities`, BSD-3. |
| `derive.report.llm` | billed_api | summary | `llm` | Lazy. §4.3. |
| `derive.merge.llm` | billed_api | entity | `llm` | Writes `merge_edge` rows only, in the `[75, 92)` band. §3. |

Third-party additions people will actually write, in an afternoon each: a citation-style pass
(BibTeX/CSL keys), a legal defined-terms pass (`"Agreement" means`), an invoice line-item pass, a
CAD part-number gazetteer, a clinical code pass (ICD/SNOMED as a gazetteer). Every one of them is
`free`, so they land above the LLM in the ladder automatically. That is the ecosystem argument: the
cost class *is* the priority, so a contributor who writes a cheap, precise extractor is rewarded by
the routing rather than needing a core PR to be inserted into a pipeline list.

---

## 3. Entity resolution — non-destructive, auditable, reversible

### 3.1 The identity function

One module, one function, three invariants, three tests. graphify's `ids.py` (93 lines) is the
recipe and I take it nearly verbatim, including the bounded NFKC/casefold fixpoint loop and its
stated reason — *"casefold and NFKC do not commute, and neither is a fixpoint of the other"* — and
`re.UNICODE` on the filter *"so CJK/Cyrillic/Arabic/accented-Latin letters survive instead of
collapsing to a per-file node"*. The three invariants are enforced by property tests: idempotent,
charset-closed, caseless-stable.

The one deviation: graphify's `make_id` produces the *node id*. Mine produces `entity.key`, a
**blocking key**, not an identity — because an identity that is a normalised surface form is exactly
graphrag's bug at one remove. `entity_id` is a surrogate int64, `key` is the deterministic normalised
form of the canonical alias, `entity_alias` holds every observed surface. The LLM extraction prompt
carries the same normalisation recipe in prose (graphify `llm.py:497-498`) so model-minted keys
collide with deterministic ones **on purpose**, and the host re-normalises every key it receives.

### 3.2 The funnel

graphify's `dedup.py` is the pipeline graphrag does not have, and I take the whole thing including
its constants (`dedup.py:242-248`) and, more importantly, its seven negative guards:

```
exact key match           -> union
entropy gate              -> _entropy(label) >= 2.5 bits/char, else excluded from fuzzy matching
MinHash/LSH blocking      -> 3-gram char shingles with SPACES STRIPPED, 128 perms, threshold 0.7
Jaro-Winkler              -> merge at >= 92.0; plain Jaro for cross-document labels >= 12 chars
                             (Winkler's prefix bonus over-fires across documents)
community boost           -> +5.0 when both already share a community AND min(len) >= 12
LLM tiebreak              -> ONLY the [75.0, 92.0) band, batches of 30, negative guards RE-APPLIED
                             before the LLM sees a pair
union-find                -> deterministic survivor
```

The negative guards are where the knowledge is, and each is a class of false merge with a real issue
number behind it: prefix containment never merges (`Auth` vs `AuthService`), differing numeric tokens
never merge (#1284), swapped content words never merge (#2576), short labels merge only on a
same-length single-character substitution, file-anchored nodes in different files never merge. I add
two document-specific ones: **a `kind='anchor'` entity never label-merges** (a "Figure 3" in two
documents is two figures; they merge only if a `refers_to` chain says so), and **two entities whose
`eclass` differ never merge** unless one is `unknown`.

The `_COMMUNITY_BOOST` deserves a note because it is nearly free and nobody else does it: two
entities Leiden already put in one community are more likely the same entity. It costs one join
against `community_member`.

### 3.3 Non-destructive: the property nothing in the collection has

**Mentions are ground truth. An `entity` row is a derived cluster.** Every pairwise decision is a
`merge_edge(a_mention_cluster, b_mention_cluster, score, method, producer_id, trust, decided_by,
reason)` row. `entity` is the union-find closure over `merge_edge`. Consequences:

- `ow graph resolve --split e412` writes a `merge_edge` with `polarity = -1` (a *separation*
  constraint that union-find honours as a blocking pair) and re-runs the closure over the affected
  block. No re-extraction, no re-parse, no LLM call.
- `ow graph resolve --explain e412` prints the merge tree: which pairs merged, at what score, by
  which method, with which producer and prompt fingerprint. This is the single highest-value
  operator command in the whole layer, because "why did these two become one entity" is the question
  every pilot asks in week two and no existing system can answer.
- Changing `_MERGE_THRESHOLD` from 92.0 to 94.0 is a re-closure, not a re-index — seconds, not
  hours, and `ow graph diff` shows exactly what changed.
- A human decision is a `merge_edge` with `method = 'user'`, `trust = EXTRACTED`, and it outranks
  every automatic edge because the closure processes `method='user'` rows last and they cannot be
  overwritten by a pass (stage ownership: the resolver does not own rows it did not write).

### 3.4 Entity id stability — `ow resolve` is `rebind` for the graph

Cluster ids churn under incremental updates, and an `e412` in a shipped answer must keep resolving.
The rule mirrors D2's `rebind` deliberately, because the operator has already learned it:

```
1. A new cluster containing a PLURALITY of a previous cluster's mentions CARRIES its entity_id.
2. A cluster that splits: the plurality half carries the id; each other half mints a fresh id and
   the old row gets an `entity_history` row with `superseded_by` and a reason.
3. A cluster that merges two prior clusters: the one contributing more mentions carries the id;
   the other is retired with `superseded_by` pointing at the survivor.
4. Below `carry_rate` threshold (default 0.80) the resolution generation is QUARANTINED, not
   committed, and `ResolveReport` names the clusters.
```

`ResolveReport` has the same fields as `RebindReport` (`carried, revised, created, retired,
carry_rate_by_eclass, quarantined, threshold`) because two reports with the same job should not have
two shapes. Overrides are named per check (`--allow-unexplained-resolve`), never one `--force` —
D2's rule and D-runtime's: *"An override flag whose scope is 'skip whatever check just complained'
is not an override, it is an off switch."*

### 3.5 Failure modes of entity resolution, named

| Failure | What happens | What we do about it |
|---|---|---|
| Two distinct people, same name, different documents | Union-find merges them; every downstream answer conflates them | `_crossdoc_fileanchored_blocked` analogue + `eclass` guard + `ow graph review --cluster-cohesion`, which lists clusters whose *minimum* pairwise score is below threshold. We do not solve correlation clustering; we make the bad clusters visible and one-command splittable. |
| Acronym vs expansion ("EBITDA" / "earnings before…") | Never merges: entropy gate excludes the acronym, LSH shingles do not overlap | An `alias` pass: a deterministic "X ('Y')" / "Y (hereinafter X)" pattern extractor writes `entity_alias` rows at `trust=EXTRACTED`. This is a `free` driver and it is the single highest-yield one for legal and financial corpora. |
| LSH blocking miss | Two clearly-identical entities never even get scored | Threshold 0.7 over 128 perms; `ow graph doctor --recall-probe` samples 1,000 exact-key-adjacent pairs and reports the block miss rate. Measured, not assumed. |
| Non-associative merges under incremental (A~B at t0, B~C at t1, A≁C) | Union-find merges all three | `merge_edge.score` is retained, so cohesion is computable; flagged, not silently accepted. |
| Cross-lingual ("北京" / "Beijing") | Never merges | **Out of scope for v1, stated.** `entity_alias` is the extension point; a translation-alias driver is a `derive/1` driver someone else writes. |
| A 4M-cell spreadsheet | `derive.entity.table` would mint millions of mentions | Header cells and key/value blocks only, plus `MAX_MENTIONS_PER_DOC = 250_000` and `MAX_MENTIONS_PER_ENTITY_PER_DOC = 512` as **fixed constants clamped per tenant** (anydoc's discipline, D2's rule): `effective = min(tenant_cap, MAX_*)`. A breach is `OWG_ITEM_BUDGET` naming the knob, which is a pricing signal. |

---

## 4. Communities and summaries

### 4.1 Clustering: always, and cheap

graphrag's incremental path never recomputes communities: delta ids are offset by `old_max + 1` and
concatenated (`index/update/communities.py:44-70`), so *"after an update an entity appearing in both
old and delta belongs to two unrelated communities in two unrelated hierarchies, each with its own
report, and global search map-reduces over both."* The inversion is graphify's and it is right:
**detection is cheap, reports are expensive, so re-cluster always and re-report selectively.**

Determinism, all three of graphrag's mechanisms copied (`cluster_graph.py:57-97`): sorted edge list,
explicit reversed-pair deduplication, fixed seed. A non-deterministic community layer makes the most
expensive stage in the pipeline non-idempotent.

Two rejections of graphrag's defaults:

- **`use_lcc = True` is off.** It *"silently discards every entity not in the largest connected
  component"*, which on a heterogeneous document corpus — unrelated PDFs, which is omniweave's
  premise — is most of the graph. graphify clusters each component it can and handles the rest
  separately. We do that, and `community.component_ord` records which.
- **`max_cluster_size = 10` (absolute) is replaced by graphify's relative + quality caps**:
  `max_fraction = 0.25`, `cohesion_split = 0.05`, `cohesion_split_min_size = 50`. The absolute cap
  is what produces ~300k leaf communities on 3M entities and therefore ≥400k report calls. The
  relative cap plus `report_levels = 2` bounds report count to O(10²–10³) for **any** corpus size,
  which is the difference between eager reports being affordable and being a five-figure invoice.

`cohesion` is returned alongside the partition (graphify does this; graphrag emits no quality signal
at all) and is a column, so a consumer can see which communities are trustworthy.

### 4.2 Which communities must be re-reported

```
member_digest = blake3_128(canonical(sorted(entity_ids)))
```

After a re-cluster: `UPDATE community_report SET report_state='stale' WHERE member_digest <>
:new_digest`. Nothing else. A one-typo edit to one paragraph of a 200-page PDF changes no member
set, so **zero reports are rewritten and zero tokens are spent** — which is the entire point.

Community *ids* carry by the same plurality rule as entities (§3.4), with `community_history`.

### 4.3 Reports are lazy by default

`[graph.community] reports = "lazy"`. A report is materialised when a retrieval path asks for it, is
admitted by D4's `admit()` against the caller's budget, and is written back. Cold global search
therefore pays inline for the levels it descends — graphrag's `DynamicCommunitySelection` is a rated
BFS descent with `keep_parent=False`, so it touches a small fraction of the hierarchy. The response
carries the absence contract when it could not pay: `degraded{reports_absent: [c3.1, c3.4],
reason: "budget"}`, never a silent thin answer.

`reports = "eager"` backfills in the background at `free`-tier-only concurrency and is what a batch
operator sets. `reports = "off"` is the `offline` profile. All three are one policy key, and
`ow graph estimate --reports` prices the eager option before you choose it.

---

## 5. The driver contract — what a contributor actually writes

### 5.1 `derive/1` and the card

A derive driver receives blocks and returns NDJSON drafts. It **never** sees the store, ids,
resolution, clustering, budgets, or the graph. D3 makes this structural: `DriverIO` has no store and
no writable root, `DriverResult.produced` is `ArtifactRef`s, and *"confidence, origin_driver,
restriction_bits, was_cache_hit are set BY THE RUNNER."*

```toml
# omniweave-driver-defterms/src/omniweave_driver_defterms/driver.toml
card_schema = 1

[driver]
id             = "derive.anchor.defterms"
port           = "derive/1"
version        = "0.1.0"
schema_version = 1
title          = "Legal defined-terms extractor"
summary        = "Extracts `\"X\" means ...` and `(the \"X\")` definitions as anchors. Regex only."
entrypoint     = "omniweave_driver_defterms.driver:DefTerms"
granularity    = "document"
deterministic  = true

[capability]
formats  = ["*"]                     # operates on the DocModel, not on bytes
consumes = ["doc_fragment"]
produces = ["graph_items"]

[capability.derive]                  # NEW vocabulary; unknown keys degrade safely (D3)
lanes          = ["anchor"]          # SET
item_kinds     = ["entity", "mention"]   # SET; conform asserts nothing else is emitted
covers         = "claimed"           # never | claimed | exhaustive
span_precision = "text_span"         # none | block | text_span  -> gates mention.ts_a/ts_b
emits_quad     = false               # true requires the parse driver declared char_bbox/line_bbox
max_trust      = "extracted"         # the CEILING the driver claims; runner clamps by method too
needs_corpus   = false               # true => granularity must be "corpus"
languages      = ["en"]

[hardware]
gpu = "none"; needs_network = false; imports_torch = false; install_bytes = 48_000

[isolation]
requires = "subproc"; memory_mb = 128; progress_ms = 5_000; wall_ms_hard = 30_000
batch_max_units = 64

[limits]
max_items_per_unit = 2_048

[licence.code]
spdx = "Apache-2.0"; licence_sha256 = "sha256:…"; redistribution = "allowed"
output_share_alike = false; competitor_bar = false

# [cost] and [quality] written by `omniweave conform`. Author values rejected. (D3-13)
```

### 5.2 The protocol shape

```python
# omniweave/ports/derive_v1.py  — part of omniweave-ports (~40 KB, pure typing, no pydantic)

class DeriveV1(Protocol):
    PORT: ClassVar[str] = "derive/1"
    @classmethod
    def probe(cls, env: "ProbeEnv") -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...      # STATIC CONFIG ONLY; loads nothing
    def derive(self, unit: "UnitRef", io: DriverIO) -> DriverResult: ...
    def is_valid_nonempty(self, ref: "ArtifactRef") -> bool: ...

# The input the host hands over, as a blob reference in the INVOKE frame:
#   owgraph-input/1 : NDJSON, one object per block, in (page, ord) order
{"cite":"d7#412","kind":"paragraph","layer":"body","page":13,"text":"…",
 "marks":[[12,19,"bold",null]],"quote":"normalized","trust":2,
 "table":{"r":0,"c":3,"header_rows":1}}          // present only for table_cell
# NOTE: NO block_id. The driver addresses blocks by `cite`, which is per-document and short.
#       The host maps cite -> block_id on ingest. A driver therefore cannot forge a block_id,
#       and a driver's output is portable between stores.

# The output, as a produced blob:
#   owgraph-items/1 : NDJSON, one DRAFT per line, `t` discriminates
{"t":"entity","tmp":"e1","key":"indemnified_party","eclass":"defined_term",
 "title":"Indemnified Party","trust":2,"score":null}
{"t":"mention","tmp_entity":"e1","cite":"d7#412","span":[12,29],"trust":2,
 "surface":"Indemnified Party"}
{"t":"edge","tmp_src":"e1","tmp_dst":"e7","relation":"defined_in","cite":"d7#412",
 "span":[0,64],"trust":2,"weight":1.0}
{"t":"claim","tmp_subject":"e1","tmp_object":"e7","claim_type":"obligation",
 "status":"asserted","t_start":"2026-01-01","t_end":null,"cite":"d7#412","span":[0,180],
 "trust":1,"score":0.72,"score_kind":"model_logprob"}
{"t":"cover","cite":"d7#412","lane":"anchor"}
{"t":"cover_empty","cite":"d7#413","lane":"anchor","reason":"no definition pattern"}
{"t":"unresolved","kind":"xref","name":"Exhibit C","retry_key":"exhibit_c","cite":"d7#500",
 "span":[4,13]}
{"t":"diag","code":"OWG_LANGUAGE_UNSUPPORTED","severity":"warning","detail":{"lang":"ja"}}
```

`tmp` ids are **local to one invocation**. The host resolves them, mints real ids, stamps the
provenance, and writes. A driver that emits a `tmp` it never defined gets its whole unit
quarantined with `OWG_DANGLING_TMP` — graphrag's `filter_orphan_relationships` as a hard gate with a
counter, and the dropped rows kept rather than deleted.

### 5.3 The host side: `GraphSink`

```python
class GraphSink(Protocol):
    """The ONLY writer of D7 tables. Drivers never see it. Symmetric with D2's DocSink."""
    def begin_unit(self, u: DeriveUnitRef, pass_: PassIdentity,
                   allowed_blocks: frozenset[BlockId]) -> None: ...
    def entity(self, d: EntityDraft) -> EntityId: ...
    def mention(self, d: MentionDraft) -> MentionId: ...
    def edge(self, d: EdgeDraft) -> EdgeId: ...
    def claim(self, d: ClaimDraft) -> ClaimId: ...
    def cover(self, block: BlockId, lane: str, *, empty_reason: str | None = None) -> None: ...
    def unresolved(self, d: UnresolvedDraft) -> None: ...
    def quarantine(self, d: Any, code: str, detail: Mapping[str, Any]) -> None: ...
    def diag(self, d: Diag) -> None: ...
    def end_unit(self, status: str) -> UnitReport: ...      # COMMITS ONE TRANSACTION
```

`allowed_blocks` is the cache-poisoning control, lifted verbatim from graphify's
`cache.put(entries, allowed_units=frozenset(batch_units))` and D-runtime invariant I13. Any draft
naming a `cite` outside the set is quarantined with `OWG_OUT_OF_SCOPE_BLOCK`, not written. This is
the single most important line of defence in §7 and it is enforced by the sink's constructor
signature, not by review.

### 5.4 Conformance: five new suites

`omniweave-conform` gains a `derive` profile. D3's thesis holds: **the card is the test plan**, and
a claim is asserted in both directions.

| suite | asserts |
|---|---|
| `derive_capability` | Every declared lane produces items; every **undeclared** lane produces none. `span_precision="none"` ⇒ every mention has a null span. `emits_quad=false` ⇒ no quad. `max_trust="inferred"` ⇒ no item at `trust=2`. |
| `derive_identity` | `normalize_key` is idempotent, charset-closed, caseless-stable; run over a 20k-string corpus including Turkish `İ`, Greek ypogegrammeni, CJK, Cyrillic, and full-width Latin. Failing this is the #811/#2614 bug class. |
| `derive_scope` | A fixture hands the driver 10 blocks and asserts every emitted `cite` is one of the 10 and every `tmp` reference resolves. |
| `derive_injection` | 40 hostile fixtures. Gate: **zero items at `trust > INFERRED`, zero out-of-scope cites, zero items above the per-unit budget, and the item count within 3× the count from the same document with the payload removed.** §7. |
| `derive_cost` | The card's `tokens_out_p95_multiple` is within 25% of measurement; `ow route lint --estimates` fails the build at >2× off the 7-day median (D4's rule, inherited). |

Mandatory tier runs in under five minutes on a laptop, per D3, *because a skipped gate is not a
gate*.

---

## 6. Incremental maintenance — exactly what recomputes

This is the question the brief asks and the one graphrag answers wrongly in four independent ways.
Here is the complete answer for "document D changes, gen `g` → `g+1`".

```
STEP 0.  D2's `rebind` runs first and produces the carried / revised / created / retired block sets.
         If rebind QUARANTINES, D7 does nothing at all: the generation is not committed.

STEP 1.  RE-DERIVE SET.
         R = { b : b in revised ∪ created }
         Carried blocks with an unchanged content_digest are NOT re-derived — D2 guarantees the
         content_digest excludes geometry and spans, so a driver upgrade's bbox jitter does not
         re-bill an LLM pass. This is the whole benefit of D2's digest discipline landing here.
         Invalidation is per (block, pass): `DELETE FROM derive_state WHERE block_id IN R`.
         COST OF A ONE-TYPO EDIT IN A 200-PAGE PDF: 1 block, 0 LLM calls if that block's lane
         was covered free.

STEP 2.  OWNED-ROW REPLACEMENT (graphify's build_merge, one predicate).
         For each pass P that re-runs:
           DELETE FROM mention WHERE observed_block IN R AND origin_operator = P;
           (same for edge, claim, cover, unresolved)
         Rows owned by OTHER passes on the SAME blocks survive. A free re-extraction cannot
         delete billable LLM rows — runtime §7.6.1, and graphify's #2333/#2336 by construction.

STEP 3.  RETIRED BLOCKS.
         Mentions/edges/claims whose observed_block is in `block_history` are moved to
         `graph_history` with the reason, NOT deleted. `ow graph doctor` counts them.
         `entity.frequency` and `degree` are recomputed for every affected entity.

STEP 4.  ANCHOR DELTA — the definitionDelta equivalent, and the thing that makes incremental
         CORRECT rather than merely fast.
         anchor_delta(D) = symmetric_difference( anchors(D, g), anchors(D, g+1) )
           computed as a per-document symmetric difference of (name_norm, akind) pairs, so a
           name moving between two changed documents does not cancel itself out.
         ADDED names   -> retry the bounded query
                            SELECT * FROM unresolved_ref
                            WHERE status='failed' AND retry_key IN (:added)
                          against the PARTIAL index on retry_key WHERE status='failed'.
                          "The corpus grew and now this citation resolves" costs one indexed
                          lookup, not a re-index.
         REMOVED names -> UNBIND: every `refers_to` edge whose destination anchor was removed is
                          deleted and re-written as an `unresolved_ref` row. This is codegraph's
                          inbound re-bind pass, and skipping the equivalent is what left 4.3% of
                          its distinct edges wrong, in both directions, silently, forever.
         A body-only edit leaves anchor_delta EMPTY, which is the common case and is free.

STEP 5.  ENTITY RESOLUTION SCOPE.
         E_touched = clusters_of(mentions_added ∪ mentions_removed)
                   ∪ clusters_of( lsh_candidates(mentions_added) )
                   ∪ clusters that lost their last mention
         The second term is mandatory and easy to miss: a NEW mention can join an EXISTING cluster
         it was never compared against. It is answered from the persisted MinHash index in one
         query per new mention. Everything outside E_touched is untouched.
         Then the union-find closure runs over merge_edge restricted to E_touched, and §3.4's
         plurality rule assigns ids.

STEP 6.  COMMUNITIES.
         RE-CLUSTER THE WHOLE GRAPH, ALWAYS. Measured: native Rust Leiden ~1 s on a million-edge
         graph (graphify cluster.py). Pure-Python Louvain on the same graph is minutes, which is
         the honest cost of the licence-clean default; see §9.
         Then: UPDATE community_report SET report_state='stale' WHERE member_digest changed.
         NOTHING ELSE. Reports for unchanged member sets are not rewritten and not re-billed.

STEP 7.  ow graph diff g g+1  ->  the only "what did re-indexing change" answer in the mine
         (graphify's graph_diff, edge key (min(u,v), max(u,v), relation), human-readable summary).
```

**The CI gate that makes this real** (runtime invariant I5): `test_incremental_equals_full.py`
builds a 60-document fixture corpus in one shot, then builds it again in 20 incremental steps
(including 3 edits, 2 deletions and 1 re-parse under a bumped driver version), and asserts the two
graph table sets are equal modulo `entity_id` / `community_id` — compared on `(key, eclass)` for
entities, `(src_key, dst_key, relation, observed_cite)` for edges, and `member_digest` for
communities. Without this test, incremental and full diverge and nobody notices for months.

**Deletion** is explicit and tier-blind, never inferred — graphify's `prune_sources`, and the
inverse of graphrag's `deleted_inputs`, which is *computed and consumed nowhere*. D2's
`ON DELETE CASCADE` from `doc` does the work; a document deletion is `ow store rm --doc d7`.

---

## 7. Hostile documents: prompt-injection-carried false entities

A knowledge graph is a persistence layer, so one successful injection poisons **every future
retrieval**, not one turn. graphify is the only repo in the collection with any defence, and
graphrag's `RAI_TRANSPARENCY.md` ships the sentence *"the system is designed for trusted users"* —
disqualifying as a posture here. Five layers, in order of how much they actually buy:

**1. Scope containment (structural, buys the most).** `GraphSink.begin_unit(..., allowed_blocks)`.
A model that is handed pages 12–14 cannot write a mention on page 400, cannot touch another
document, and cannot modify an existing entity. Enforced by the constructor signature. This is the
one control that survives a fully successful injection.

**2. Trust clamping (structural).** `MAX_TRUST_BY_METHOD[LLM] = MAX_TRUST_BY_METHOD[VLM_PAGE] =
INFERRED`, applied by the runner *after* the driver returns, so a driver cannot opt out. The two
capped methods are exactly the two where the document can talk back. Everything a hostile document
produces is therefore forever visible as `INFERRED` or `AMBIGUOUS`, is sorted first in
`ow graph review`, is down-weighted in fusion, and may not be asserted in a generated artifact
without an accompanying block cite the reader can check.

**3. Item budgets (structural).** `max_items_per_unit` from the card, clamped by
`MAX_ITEMS_PER_UNIT = 2048` and `MAX_MENTIONS_PER_DOC = 250_000` as fixed constants. "Emit 100,000
entities named ACME" hits `OWG_ITEM_BUDGET` and the unit is quarantined. anydoc's own reasoning:
*a knob that turns off the zip-bomb cap will be turned off*, so the cap is a constant and the tenant
value is `min(tenant_cap, MAX_*)`.

**4. The wrapper (prompt-level, real but weaker).** graphify's `<untrusted_source>` block and its
system-prompt doctrine, with the **three fixes the risk mine names**:
  - escape the values interpolated into the tag's attributes;
  - **defang a copy** — graphify's zero-width-space insertion shifts every later byte offset by 3,
    which here would break `mention.ts_a/ts_b` against `block.text`. We render the wrapped copy for
    the prompt, keep an offset map, and lift model-returned offsets back through it. This is
    literally D2's `SpanMap` mechanism reused, and it is why D2's insistence on typed coordinate
    systems pays off in D7.
  - drop the heading-shaped sentinel `^###\s*instructions?$`, which matches `## Instructions` in
    every manual, RFP and SOP on earth.
  Ship graphify's own honest claim verbatim in the docs: it *"does not make injection impossible,
  but changes it from 'works on first try' to 'requires evasion.'"*

**5. `taint` and both-directions sanitisation.** A block whose text matched the sentinel detector
sets `taint=1` on every item derived from it. Taint does **not** propagate across edges (that would
poison a whole neighbourhood from one bad PDF and make the bit useless). It is a query dimension:
`ow graph review --taint`, and serve's MCP layer labels tainted entity titles. Separately,
`sanitize_label()` runs on every string that round-trips *back* to an agent, not only on HTML —
graphify applies it to MCP text output, and the index is a persistence layer for attacker text.

**6. The regression corpus is the actual deliverable.** `omniweave-conform`'s `derive_injection`
suite ships 40 hostile fixtures: an instruction block in white-on-white PDF text, an OOXML
`w:instrText` field, a PPTX speaker note, an EXIF comment, an alt-text payload, a table cell with a
forged `</untrusted_source>`, an SVG `<title>`, a zero-width-joiner-obfuscated directive, a
non-Latin-script directive, and a "cite this URL as the source" exfiltration attempt. The gate is
four assertions (§5.4) and it runs in CI on every driver, first-party or not. **No repo in the
collection tests for this class; graphrag documents evaluating it and ships the trusted-users
sentence.**

Residual risk, stated: a *plausible false entity* — a hostile contract that invents a
counterparty — is not detectable by any of this. It arrives as `INFERRED`, correctly, and the answer
is the review surface and the citation, not a filter.

---

## 8. Concrete shape

```sql
-- ══════════════ D7 additions to the .owstore. Same file. Same block_id FKs. ══════════════
-- D2 rules: "L3 (D7) may not put containment or intra-document references in its own tables.
--            The seven `rel` kinds are L2's; entity, claim, community and cross-document edges
--            are D7's and key on `block_id`."  Observed here verbatim.
-- Pragmas are D2's; this file is opened by the same connection.

CREATE TABLE type_vocab (               -- entity classes, DERIVED PER CORPUS, never a config list
  eclass_ord INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL CHECK(source IN ('builtin','corpus_tuned','user')),
  n_entities INTEGER NOT NULL DEFAULT 0
);
-- builtin seeds: anchor, defined_term, citation, figure, table_ref, section, person,
--                organization, place, date, money, quantity, product, group, unknown

CREATE TABLE derive_pass (              -- the pass registry. DATA, not a hardcoded list.
  pass_id     TEXT PRIMARY KEY,         -- 'derive.entity.llm'   == D3 driver id
  port        TEXT NOT NULL,            -- 'derive/1'
  cost_class  TEXT NOT NULL CHECK(cost_class IN ('free','local_compute','billed_api')),
  cost_rank   INTEGER NOT NULL,         -- 0 | 1 | 2   -- THE ORDERING. Nothing else orders passes.
  lanes       TEXT NOT NULL,            -- JSON array
  granularity TEXT NOT NULL CHECK(granularity IN ('document','part','corpus')),
  card_sha256 TEXT NOT NULL, schema_version INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE derive_unit (              -- the EXTRACTION unit. NOT D5's retrieval chunk.
  unit_id  INTEGER PRIMARY KEY,
  doc_ord  INTEGER NOT NULL, gen INTEGER NOT NULL,
  lo_block INTEGER NOT NULL REFERENCES block(block_id),
  hi_block INTEGER NOT NULL REFERENCES block(block_id),
  n_blocks INTEGER NOT NULL, n_tokens INTEGER NOT NULL,
  content_digest BLOB NOT NULL,         -- merkle over member blocks' content_digests, in ord order
  UNIQUE (doc_ord, gen, lo_block)
);
CREATE INDEX derive_unit_dig ON derive_unit(content_digest);

CREATE TABLE derive_state (             -- per (block, pass) cache/staleness. The invalidation unit.
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  pass_id   TEXT    NOT NULL REFERENCES derive_pass(pass_id),
  content_digest BLOB NOT NULL,         -- the block's digest AT DERIVE TIME
  cache_key TEXT NOT NULL,              -- sha256_canonical(content|producer|configuration), §7.5
  derived_at_ns INTEGER NOT NULL,
  n_items INTEGER NOT NULL,
  PRIMARY KEY (block_id, pass_id)
) WITHOUT ROWID;

CREATE TABLE derive_cover (             -- THE deterministic-first mechanism
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  lane     TEXT    NOT NULL,
  pass_id  TEXT    NOT NULL REFERENCES derive_pass(pass_id),
  empty_reason TEXT,                    -- NOT NULL => covered with zero items; doctor reports rate
  PRIMARY KEY (block_id, lane, pass_id)
) WITHOUT ROWID;
CREATE INDEX derive_cover_lane ON derive_cover(lane, block_id);

-- ─────────────────────────────── the graph proper ───────────────────────────────
CREATE TABLE entity (
  entity_id  INTEGER PRIMARY KEY,       -- DURABLE surrogate. Every FK points here. Not in prompts.
  cite       TEXT    NOT NULL,          -- 'e412'  -- prompts ONLY. See CONFLICT 1.
  key        TEXT    NOT NULL,          -- normalize_key(canonical alias). A BLOCKING key,
                                        --   NOT an identity: graphrag keys on the surface form
                                        --   (clean_str(x.upper())) and splits on spelling drift.
  eclass     INTEGER NOT NULL REFERENCES type_vocab(eclass_ord),
  title      TEXT    NOT NULL,          -- display; an entity IS Named (graphrag's asymmetry)
  description TEXT,                     -- SYNTHETIC. Never quotable. Never rendered as a quote.
  frequency  INTEGER NOT NULL DEFAULT 0,-- COUNT(DISTINCT mention.unit_id) — CORPUS salience
  degree     INTEGER NOT NULL DEFAULT 0,-- graph degree — GRAPH salience. Both, always recomputed.
  n_docs     INTEGER NOT NULL DEFAULT 0,
  -- provenance of the CLUSTER (the min over its mentions; MIN() over Trust is meaningful)
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method     INTEGER NOT NULL, trust INTEGER NOT NULL,
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  taint      INTEGER NOT NULL DEFAULT 0,
  state      INTEGER NOT NULL DEFAULT 0,        -- 0=live 1=retired
  x          TEXT NOT NULL DEFAULT '{}',        -- keys MUST be 'x.<vendor>.<key>'
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX entity_cite ON entity(cite);
CREATE INDEX entity_key   ON entity(key, eclass)        WHERE state = 0;
CREATE INDEX entity_rank  ON entity(eclass, degree DESC, frequency DESC) WHERE state = 0;
CREATE INDEX entity_review ON entity(trust, taint)      WHERE state = 0 AND trust < 2;
CREATE INDEX entity_restricted ON entity(restriction_bits) WHERE restriction_bits <> 0;

CREATE TABLE entity_alias (             -- the fix for graphrag's title keying
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  alias_norm TEXT NOT NULL, alias_raw TEXT NOT NULL,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  PRIMARY KEY (entity_id, alias_norm)
) WITHOUT ROWID;
CREATE INDEX entity_alias_lookup ON entity_alias(alias_norm);

CREATE TABLE entity_history (           -- symmetric with D2's block_history
  entity_id INTEGER PRIMARY KEY, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER, reason TEXT NOT NULL   -- split|merged|source_deleted|resolver_upgrade
);

-- The join from graph to document to PIXEL. This answers D2's open question:
--   "Should L3 entity spans live in `mark` or in a separate annotation table?"
-- ANSWER: its own table. A mention carries its own producer, method, trust, score and
--         origin_operator. D2's own criterion: "if a span carries its own provenance, trust and
--         producer, it is not a Mark." A Mark is a pointer with a label; this is an assertion.
CREATE TABLE mention (
  mention_id INTEGER PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  unit_id    INTEGER REFERENCES derive_unit(unit_id),
  ts_a INTEGER, ts_b INTEGER,           -- D2's TextSpan: chars in THIS block's own .text
  quad BLOB,                            -- 8 x i32 LE. NULL => "use the block's quad".
                                        --   NON-NULL is legal ONLY when the parse driver declared
                                        --   spatial >= line_bbox AND the derive card says
                                        --   emits_quad=true. Conform proves both directions.
  surface    TEXT NOT NULL,             -- the observed surface form; feeds entity_alias
  pass_id    TEXT NOT NULL REFERENCES derive_pass(pass_id),
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0, taint INTEGER NOT NULL DEFAULT 0,
  CHECK ((ts_a IS NULL) = (ts_b IS NULL)),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  -- Identity IN THE SCHEMA. INSERT OR IGNORE is a plain INSERT with nothing to conflict on,
  -- and SQL NULLs are each distinct, so the nullable span needs IFNULL sentinels (codegraph #1034).
  UNIQUE (observed_block, IFNULL(ts_a,-1), IFNULL(ts_b,-1), entity_id, pass_id)
);
CREATE INDEX mention_entity ON mention(entity_id, observed_block);
CREATE INDEX mention_block  ON mention(observed_block);
CREATE INDEX mention_review ON mention(trust, taint) WHERE trust < 2;

CREATE TABLE edge (
  edge_id INTEGER PRIMARY KEY,
  src_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  dst_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  relation   TEXT NOT NULL,             -- closed per-corpus vocab + a DIRECTION RULE per relation
  -- WHERE THE RELATIONSHIP WAS OBSERVED. graphify requires source_file on EDGES, not just nodes;
  -- that one field is what lets an answer cite the sentence that asserts the link.
  observed_block INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER, ts_b INTEGER,
  src_mention INTEGER REFERENCES mention(mention_id) ON DELETE SET NULL,
  dst_mention INTEGER REFERENCES mention(mention_id) ON DELETE SET NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,   -- src.degree + dst.degree; the edge prior
  pass_id TEXT NOT NULL REFERENCES derive_pass(pass_id),
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0, taint INTEGER NOT NULL DEFAULT 0,
  CHECK (src_entity <> dst_entity),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  UNIQUE (src_entity, dst_entity, relation, IFNULL(observed_block,-1), IFNULL(ts_a,-1), pass_id)
);
CREATE INDEX edge_src ON edge(src_entity, relation, weight DESC);
CREATE INDEX edge_dst ON edge(dst_entity, relation, weight DESC);
CREATE INDEX edge_obs ON edge(observed_block);

CREATE TABLE relation_vocab (           -- the DIRECTION RULE, as data, per relation
  relation TEXT PRIMARY KEY,
  symmetric INTEGER NOT NULL DEFAULT 0,
  actor_rule TEXT NOT NULL              -- "source = the block that MAKES the reference;
);                                      --  target = the thing referenced. Never reverse this."
-- graphify states this per relation in its prompt (llm.py:500-504). Almost no schema does, and
-- without it half your edges point backwards and traversal returns callees when asked for callers.

CREATE TABLE claim (                    -- graphrag's covariates: the best temporal-fact schema here
  claim_id INTEGER PRIMARY KEY,
  cite TEXT NOT NULL,                   -- 'k412'  -- prompts ONLY
  subject_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  object_entity  INTEGER          REFERENCES entity(entity_id) ON DELETE CASCADE,  -- BIPARTITE
  claim_type TEXT NOT NULL,             -- open vocab, corpus-tuned
  status TEXT NOT NULL CHECK(status IN ('asserted','denied','superseded','suspected')),
  t_start TEXT, t_end TEXT,             -- ISO-8601, partial allowed ("2026", "2026-Q1")
  -- source_text is a SPAN, not a copy: D2 already stores the text and a second copy would drift.
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  pass_id TEXT NOT NULL REFERENCES derive_pass(pass_id),
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0, taint INTEGER NOT NULL DEFAULT 0,
  UNIQUE (subject_entity, IFNULL(object_entity,-1), claim_type, observed_block, ts_a, pass_id)
);
CREATE UNIQUE INDEX claim_cite ON claim(cite);
CREATE INDEX claim_subject ON claim(subject_entity, IFNULL(t_start,''), IFNULL(t_end,''));

-- ─────────────────── entity resolution: reversible by construction ───────────────────
CREATE TABLE merge_edge (
  a_mention INTEGER NOT NULL REFERENCES mention(mention_id) ON DELETE CASCADE,
  b_mention INTEGER NOT NULL REFERENCES mention(mention_id) ON DELETE CASCADE,
  polarity  INTEGER NOT NULL CHECK(polarity IN (-1, 1)),   -- -1 = MUST NOT merge (a user split)
  score     REAL NOT NULL,             -- jaro_winkler*100, or 100.0 for an exact-key union
  stage     TEXT NOT NULL,             -- exact|lsh_jw|community_boost|llm_band|user
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  reason TEXT,                         -- required when method='user'
  PRIMARY KEY (a_mention, b_mention, stage)
) WITHOUT ROWID;
CREATE INDEX merge_edge_b ON merge_edge(b_mention);
-- entity = the union-find closure over polarity=+1, honouring polarity=-1 as a blocking pair,
-- with method='user' rows applied LAST and never overwritten by a pass.

CREATE TABLE minhash_block (            -- persisted LSH so a NEW mention finds an OLD cluster
  band INTEGER NOT NULL, bucket BLOB NOT NULL, entity_id INTEGER NOT NULL
    REFERENCES entity(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (band, bucket, entity_id)
) WITHOUT ROWID;

-- ─────────────────── anchors, references, and the durable residue ───────────────────
CREATE TABLE anchor (                   -- what a document DEFINES. Feeds anchor_delta.
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  name_norm TEXT NOT NULL,
  akind TEXT NOT NULL,                  -- section|figure|table|exhibit|defined_term|citation_key
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  entity_id INTEGER REFERENCES entity(entity_id) ON DELETE SET NULL,
  scope TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  PRIMARY KEY (doc_ord, gen, name_norm, akind)
) WITHOUT ROWID;
CREATE INDEX anchor_global ON anchor(name_norm, akind) WHERE scope = 'corpus';

CREATE TABLE unresolved_ref (           -- codegraph's biggest architectural idea, for documents
  ref_id INTEGER PRIMARY KEY,
  from_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER, ts_b INTEGER,
  reference_name TEXT NOT NULL, reference_kind TEXT NOT NULL,
  retry_key TEXT NOT NULL DEFAULT '',   -- codegraph's name_tail: 'Smith 2019, Fig 3' -> 'fig_3'
  candidates TEXT,                      -- JSON array of near-miss entity cites
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','failed')),
  first_seen_gen INTEGER NOT NULL, last_tried_gen INTEGER NOT NULL,
  pass_id TEXT NOT NULL REFERENCES derive_pass(pass_id)
);
-- "on a healthy index the pending set is empty and the failed set is the only population worth
--  indexing" (codegraph migrations.ts v8)
CREATE INDEX unresolved_retry ON unresolved_ref(retry_key) WHERE status = 'failed';

CREATE TABLE quarantine (               -- graphrag DELETES these. A hallucinated name is often real.
  q_id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,                   -- OWG_DANGLING_TMP | OWG_OUT_OF_SCOPE_BLOCK |
                                        -- OWG_ITEM_BUDGET | OWG_TRUST_CLAMPED | OWG_UNPARSED_ITEM
  pass_id TEXT NOT NULL, unit_id INTEGER, doc_ord INTEGER, gen INTEGER,
  payload TEXT NOT NULL,                -- the rejected draft, verbatim
  detail TEXT NOT NULL DEFAULT '{}', created_at_ns INTEGER NOT NULL
);
CREATE INDEX quarantine_code ON quarantine(code, pass_id);

CREATE TABLE graph_history (            -- items retired by a re-derive. NOT deleted.
  kind TEXT NOT NULL, row_id INTEGER NOT NULL, retired_gen INTEGER NOT NULL,
  reason TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (kind, row_id, retired_gen)
) WITHOUT ROWID;

-- ─────────────────────────── communities and reports ───────────────────────────
CREATE TABLE community (
  community_id INTEGER PRIMARY KEY,
  cite TEXT NOT NULL,                   -- 'c3.1' == level.ordinal -- prompts ONLY
  level INTEGER NOT NULL,               -- INTEGER. graphrag stores it as str and .astype(int)s it
  parent INTEGER REFERENCES community(community_id), -- root parent is NULL, never -1 as a sentinel
  component_ord INTEGER NOT NULL,       -- which connected component. use_lcc is OFF; nothing is
                                        --   silently discarded (graphrag's use_lcc=True default)
  size INTEGER NOT NULL,
  cohesion REAL,                        -- graphify's quality signal; graphrag emits none
  member_digest BLOB NOT NULL,          -- blake3_128(canonical(sorted(entity_ids))) -> re-report key
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  state INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX community_cite ON community(cite);
CREATE INDEX community_level ON community(level, size DESC) WHERE state = 0;

CREATE TABLE community_member (
  community_id INTEGER NOT NULL REFERENCES community(community_id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (community_id, entity_id)
) WITHOUT ROWID;
CREATE INDEX community_member_e ON community_member(entity_id);

CREATE TABLE community_report (
  community_id INTEGER PRIMARY KEY REFERENCES community(community_id) ON DELETE CASCADE,
  report_state TEXT NOT NULL CHECK(report_state IN ('absent','stale','fresh')),
  member_digest BLOB,                   -- the digest the CURRENT text was written against
  title TEXT, summary TEXT, full_content TEXT,
  rank REAL, rating_explanation TEXT, findings TEXT,   -- JSON
  producer_id INTEGER REFERENCES producer(producer_id),
  method INTEGER, trust INTEGER,
  cost_micros INTEGER NOT NULL DEFAULT 0,
  written_at_ns INTEGER
);
CREATE INDEX community_report_todo ON community_report(report_state) WHERE report_state <> 'fresh';

CREATE TABLE community_history (
  community_id INTEGER PRIMARY KEY, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER, reason TEXT NOT NULL
);

-- ─────────────────── operability: the artefact an on-call engineer reads ───────────────────
CREATE TABLE graph_observation (        -- symmetric with D3's driver_observation
  run_id TEXT NOT NULL, pass_id TEXT NOT NULL, lane TEXT NOT NULL,
  units INTEGER NOT NULL DEFAULT 0, blocks_in INTEGER NOT NULL DEFAULT 0,
  items_out INTEGER NOT NULL DEFAULT 0, covered INTEGER NOT NULL DEFAULT 0,
  covered_empty INTEGER NOT NULL DEFAULT 0, quarantined INTEGER NOT NULL DEFAULT 0,
  cache_hits INTEGER NOT NULL DEFAULT 0, wall_ms INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, pass_id, lane)
) STRICT;
```

```python
# ══════════════════ omniweave_graph/ — the host side ══════════════════
# Distribution: omniweave-graph (D1). Deps beyond D1's table, with sizes and SPDX, because
# dependency weight is an architectural constraint and a licence gate reads this:
#   networkx    3.x   BSD-3-Clause   ~2.5 MB pure Python   community detection (default)
#   datasketch  1.6   MIT            ~0.3 MB               MinHash / LSH blocking
#   rapidfuzz   3.x   MIT            ~2 MB   (C++ ext)     Jaro-Winkler at 92.0
# NOT depended on, deliberately: leidenalg (GPL-3.0), python-igraph (GPL-2.0).
# Leiden ships as a SEPARATE distribution `omniweave-driver-leiden` -> graspologic-native, and
# it imports the NATIVE module directly, never the graspologic package: graphify measured
# 7-19 s of one-time import cost (umap -> pynndescent -> numba JIT) against a ~1 s native call
# for a layout algorithm it never invokes (cluster.py:22-40). Confirm graspologic-native's SPDX
# at pin time; D3's compute_tier() gates it, and an unverified licence fails allow_tiers=["open"].

MAX_TRUST_BY_METHOD: Mapping[Method, Trust] = {
    Method.NATIVE: Trust.EXTRACTED,   Method.NATIVE_XML: Trust.EXTRACTED,
    Method.TEXT_LAYER: Trust.EXTRACTED, Method.HEURISTIC: Trust.EXTRACTED,
    Method.OCR_PAGE: Trust.INFERRED,  Method.OCR_BLOCK: Trust.INFERRED,
    Method.VLM_PAGE: Trust.INFERRED,  Method.LLM: Trust.INFERRED,      # <- the security clamp
    Method.ROUNDTRIP: Trust.INFERRED, Method.USER: Trust.EXTRACTED,
}
# Applied by the RUNNER after the driver returns. A driver cannot opt out. A clamp writes a
# `quarantine` row with OWG_TRUST_CLAMPED carrying the driver's original claim, so over-claiming
# is visible in `ow graph doctor` rather than silently corrected.

def normalize_key(s: str) -> str:
    """graphify/ids.py:51-93, adopted with its three tested invariants:
         idempotent · charset-closed (\\w and _ only) · caseless-stable
       The bounded fixpoint loop is load-bearing: casefold and NFKC do not commute and neither is
       a fixpoint of the other (Turkish dotted I, Greek ypogegrammeni). re.UNICODE on the filter,
       or every CJK/Cyrillic corpus collapses to one node per document."""
    cur = s
    for _ in range(6):
        nxt = unicodedata.normalize("NFKC", cur.casefold())
        if nxt == cur: break
        cur = nxt
    cur = re.sub(r"[^\w]+", "_", cur, flags=re.UNICODE)
    return re.sub(r"_+", "_", cur).strip("_")

@dataclass(frozen=True, slots=True)
class ResolveReport:                    # deliberately shaped like D2's RebindReport
    from_gen: int; to_gen: int
    carried: int; created: int; retired: int; split: int; merged: int
    carry_rate_by_eclass: Mapping[str, float]
    low_cohesion_clusters: tuple[Cite, ...]
    quarantined: bool; threshold: float

def resolve_entities(store, *, scope: frozenset[EntityId] | None = None,
                     threshold: float = 0.80) -> ResolveReport: ...
    # scope=None means the whole corpus. Incremental passes E_touched (§6 step 5).
    # Below `threshold` carry rate the generation is QUARANTINED, not committed.
    # Override is `--allow-unexplained-resolve`, never `--force`.

@dataclass(frozen=True, slots=True)
class Locate:                           # what `ow graph locate` returns; the polygon answer
    cite: Cite                          # 'd7#412'
    doc_ord: int; page: int
    quad: Quad | None
    quad_source: Literal["mention", "block", "unavailable"]
    reason: str | None                  # populated iff quad_source == "unavailable", e.g.
                                        # "driver parse.doc.anydoc declares spatial=none"
    span: TextSpan | None
```

```toml
# ── omniweave.toml, the D7 section. Everything here is data. ──
[graph]
enabled       = true
entity_types  = "auto"          # "auto" = corpus-tuned into type_vocab. NEVER a four-item list.
unit_tokens   = 1500            # derive_unit target; 0 overlap (extraction, not retrieval)
max_items_per_unit = 2048       # clamped: effective = min(tenant_cap, 2048)

[graph.passes]
order   = "cost_class"          # THE ONLY ordering. There is no pipeline array to reorder.
enable  = ["derive.anchor.native", "derive.xref.pattern",
           "derive.entity.table", "derive.entity.gazetteer",
           "derive.community.louvain"]
# billed_api passes are absent, therefore off. D3: "billed_api is opt-in".

[graph.pass."derive.entity.llm"]
enabled = false
budget  = { tokens_out_per_document = 40000, micros_per_document = 20000 }
max_attempts = 2                # the glean cap, as ATTEMPTS on one decision (see §0)

[graph.resolve]
entropy_min      = 2.5          # bits/char
lsh_threshold    = 0.7
lsh_perms        = 128
merge_threshold  = 92.0
community_boost  = 5.0
llm_band         = [75.0, 92.0]
carry_threshold  = 0.80

[graph.community]
backend        = "louvain"      # louvain | leiden (a separate driver distribution)
max_fraction   = 0.25           # RELATIVE, not graphrag's absolute max_cluster_size = 10
cohesion_split = 0.05
cohesion_split_min_size = 50
use_lcc        = false          # graphrag's true default silently discards everything else
seed           = 3735928559     # 0xDEADBEEF. Determinism is engineered three ways; copy all three.
reports        = "lazy"         # lazy | eager | off
report_levels  = 2
```

```
══ ow graph explain — the operator payoff, symmetric with `omniweave drivers explain` ══
$ ow graph explain e412

e412  "Indemnified Party"   eclass=defined_term   trust=EXTRACTED   taint=0
  frequency 27 mentions in 4 documents · degree 19 · communities c1.3, c2.7

CLUSTER  (3 mention groups merged; `ow graph resolve --explain e412` for the tree)
  "Indemnified Party"   19 mentions   exact key
  "Indemnified party"   6 mentions    exact key (caseless-stable)
  "the Indemnitee"      2 mentions    llm_band score 81.4  <- derive.merge.llm, prompt fp 7c3f12a4
                                      `ow graph resolve --split e412 --group 3` to undo

EVIDENCE  (first 3 of 27)
  d7#412   p14   contract-2026.pdf   quad (98,140)-(402,158)   trust=EXTRACTED
  d7#480   p16   contract-2026.pdf   quad unavailable — parse.doc.anydoc declares spatial=none
  d9#88    p2    amendment-3.docx    quad unavailable — same

EDGES  (19; showing trust<EXTRACTED first — review order)
  AMBIGUOUS  refers_to    e77 "Exhibit C"          d7#500  derive.xref.pattern
  INFERRED   obligated_to e120 "Acme Holdings"     d7#412  derive.entity.llm  fp 7c3f12a4
  EXTRACTED  defined_in   e3  "Section 4.2"        d7#410  derive.anchor.native

COST attributable to this entity: $0.0031 (2 llm calls, 6,140 in / 810 out)
```

```
══ ow graph build — the first-run experience, which is the adoption argument ══
$ pip install omniweave && ow parse contract-2026.pdf --store corpus.owstore
$ ow graph build --store corpus.owstore

graph build · 4 passes · 0 billed · 1,284 blocks · 3.1 s · $0.00
  derive.anchor.native      free   412 anchors     covered 1,284/1,284   trust=extracted
  derive.xref.pattern       free   231 xrefs       188 bound, 43 -> unresolved_ref
  derive.entity.table       free   903 mentions    covered 96 cells      trust=extracted
  derive.community.louvain  free   61 communities  cohesion p50 0.31     reports: lazy (0 written)
resolve: 744 entities (carried 0, created 744) · 12 clusters below cohesion 0.20

  ! 43 unresolved references          ow graph unresolved
  ! 12 low-cohesion clusters          ow graph review --cluster-cohesion
  i LLM passes are disabled (billed_api is opt-in).
      ow graph estimate --enable derive.entity.llm
        -> 41 units · 82 calls · ~143k in / ~25k out · ~$0.04 at your pricebook
      ow graph build --enable derive.entity.llm --budget 0.10
```

---

## 9. Cost, in numbers

**The digest's headline LLM figure is computed on graphrag's model, not D2's, and it is ~2 orders
too high for omniweave.** `digest-graph.md` states *"2 LLM calls per chunk … 10M blocks ⇒ ~20M
calls, ~35B prompt tokens, ~9 days single-process"* — that assumes one chunk per block, which is
true in graphrag (its `TextUnit` is the chunk *and* the extraction unit) and false under D2, where
**table cells are blocks** and D2's own envelope is 60–120 blocks per A4 page.

Redone against D2's model, stated assumptions first: 10M blocks at 100 blocks/page ≈ **100,000
pages**; ~650 tokens of body text per page ≈ **65M tokens**; `derive_unit` at 1,500 tokens with no
overlap ≈ **43,000 units**.

| item | volume | tokens | at $0.20/$0.60 per 1M | at $3/$15 per 1M |
|---|---|---|---|---|
| `derive.entity.llm`, 2 attempts/unit | 86k calls | 150M in / 26M out | **$46** | **$840** |
| `derive.claim.llm`, 1 attempt on prose units | 30k calls | 60M in / 12M out | **$19** | **$360** |
| community reports, **graphrag's `max_cluster_size=10`** on ~1.5M entities ⇒ ~150k leaf communities | 150k calls | 300M in / 150M out | **$150** | **$3,150** |
| community reports, **our relative cap + `report_levels=2`** | ~900 calls | 1.8M in / 0.9M out | **$0.90** | **$19** |

Three readings an operator should take from that table:

1. **Reports, not extraction, are the bill** under graphrag's defaults — 3–6× extraction cost. That
   is why `max_cluster_size = 10` is replaced by a relative cap and why reports are lazy. The single
   configuration change is worth ~$3,100 per 10M-block corpus at frontier prices, per rebuild.
2. **Extraction on the LLM path is affordable at commodity prices and is a real decision at frontier
   prices.** `ow graph estimate` prints it before you pay, on `build` *and* on `update` — graphrag
   has `--dry-run` on `index` and not on `update`, which is exactly where you want the delta priced.
3. **The free tier costs $0 and no API key,** and graphify's LOCOMO/LongMemEval numbers say it is
   competitive rather than a stub.

**Storage.** Assuming 0.6 deterministic mentions per body block (an *estimate*, flagged in Open
Questions): 6M mentions × ~140 B with indexes ≈ **840 MB**; ~2M edges × ~180 B ≈ **360 MB**;
~1.5M entities × ~300 B ≈ **450 MB**. Total **≈1.65 GB on top of D2's measured 3.3 GB** for a
10M-block store — **≈ +50%**. Mentions dominate, which is why the per-entity-per-document mention
cap exists and why `ow graph doctor` reports the mention/block ratio per pass.

**Runtime, free tier.** Deterministic passes are regex and index scans: budget **~2.5 ms/block**
single-threaded, so 10M blocks ≈ 7 CPU-hours, embarrassingly parallel by document. Resolution: LSH
blocking over 1.5M entities at 128 perms ≈ 3–5 minutes; the union-find closure is O(n α(n)).
Clustering is the honest weak point: **`networkx.louvain_communities` on a 2M-edge graph is minutes,
not the ~1 s graphify measures for native Rust Leiden.** That is the price of a BSD-3 default over a
GPL clustering library, it is stated in `ow graph build`'s output as `community: 4m12s (louvain;
install omniweave-driver-leiden for ~1s)`, and the fix is one `pip install`.

**Engineering cost.** ~10–14 engineer-weeks for L3: DDL + migrations (1w), `GraphSink` + the
`owgraph-items/1` codec + tmp-id resolution + quarantine (2w), the five shipped free passes (2w),
`normalize_key` + the resolution funnel with all seven negative guards + MinHash persistence (3w),
communities + lazy reports + `member_digest` (1.5w), the incremental path including `anchor_delta`
and the inbound re-bind (2w), CLI + `ow graph explain/why/locate/review/doctor/diff` (1.5w),
conform's five `derive` suites and the 40-fixture injection corpus (2w, overlapping). A first
`ow graph build` on the free tier lands in week 4.

---

## 10. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| G1 | No LLM/deterministic mode switch exists. The distinction is `method` + `producer_id` + `cost_class`. | A grep CI rule bans the identifiers `fast_pipeline`, `is_ast_tier`, `llm_mode` in `omniweave_graph/`; a test asserts every D7 table has exactly one `mention`/`edge`/`claim` shape and no tier column. |
| G2 | A billed pass never runs on a (block, lane) a cheaper pass covered. | The input selector *is* the `NOT EXISTS` query (§2.1); `test_deterministic_first.py` asserts the join count is 0 on the fixture corpus. |
| G3 | A pass writes `derive_cover` only when it emitted an item, or writes `covered_empty` with a reason. | `GraphSink.cover(empty_reason=...)` — the argument is required when `n_items == 0`; `ow graph doctor` reports the rate and warns above 0.98. |
| G4 | Every node, edge, mention and claim carries all seven provenance fields plus `taint`. | `NOT NULL` in the DDL; the fields are set by the runner from `PassIdentity`, not by any draft field, so a driver cannot omit or forge them (D3-8). |
| G5 | An LLM- or VLM-derived item never reaches `trust = EXTRACTED`. | `MAX_TRUST_BY_METHOD` clamp in the runner + an `OWG_TRUST_CLAMPED` quarantine row + the `derive_injection` conform assertion. |
| G6 | A driver's output may reference only blocks it was handed. | `GraphSink.begin_unit(allowed_blocks=...)`; a `cite` outside the set is quarantined `OWG_OUT_OF_SCOPE_BLOCK`; conform suite `derive_scope`. |
| G7 | Entity identity is never a surface form. | `entity.key` is documented and named as a *blocking* key; `entity_alias` exists; a test asserts two entities may share a `key` and differ (there is no UNIQUE on `key`). |
| G8 | `normalize_key` is idempotent, charset-closed, caseless-stable. | Three property tests over a 20k-string Unicode corpus; conform suite `derive_identity`. |
| G9 | Every derived row's identity tuple is in the schema, with `IFNULL` sentinels. | The four `UNIQUE` constraints above; a migration installing one must dedup with a `GROUP BY` matching the index expression exactly (codegraph #1034, migration v6). |
| G10 | Entity resolution is reversible. | `entity` has no writer other than the union-find closure over `merge_edge`; a test deletes a `merge_edge` row, re-closes, and asserts the split; `ow graph resolve --split` is a shipped command with a test. |
| G11 | Missing trust is AMBIGUOUS; a migration may only downgrade. | D2's rule, inherited. A migration test asserts `new_trust <= old_trust` for every row; the loader defaults absent to 0. |
| G12 | Incremental converges with full. | `test_incremental_equals_full.py` (§6), 60 documents, 20 steps, compared modulo surrogate ids. Runtime invariant I5. |
| G13 | A community is re-reported only when its member set changed. | `member_digest` is the only write trigger; a test builds, edits one paragraph, rebuilds, and asserts `community_report.written_at_ns` is unchanged for every row. |
| G14 | Nothing outside the largest connected component is silently discarded. | `use_lcc = false`; `community.component_ord` is `NOT NULL`; a test on a deliberately disconnected fixture asserts every entity has a community. |
| G15 | Clustering is deterministic. | Sorted edge list + explicit reversed-pair dedup + fixed seed; a test runs it 20× with a shuffled input and asserts an identical partition. |
| G16 | A dropped/hallucinated item is kept, not deleted. | `quarantine` is the only disposal path; `GraphSink` has no `drop()`; a test asserts a dangling-`tmp` draft produces a `quarantine` row. |
| G17 | Every relation has a written direction rule. | `relation_vocab.actor_rule` is `NOT NULL`; the LLM extraction prompt is generated from this table, so prompt and schema cannot drift. |
| G18 | The only prompt-safe ids are `d7#412`, `e412`, `c3.1`, `k412`. | A lint over every prompt template and every serve response asserts no `entity_id`/`block_id`/`addr` appears; three `UNIQUE` cite indexes make each resolvable in one lookup. Requires the §0 amendment. |
| G19 | An item budget breach is a typed outcome naming the knob. | `OWG_ITEM_BUDGET{limit, value, knob}` — anydoc's `ResourceLimit` shape, so a limit hit is a pricing signal, not a crash. |
| G20 | D7 writes nothing into L2's tables. | A CI test opens the store after `ow graph build` and asserts `rel`, `mark`, `block` row counts and digests are byte-identical to before. |

---

## 11. Tradeoffs

- **Two chunkings.** `derive_unit` (extraction, ~1,500 tokens) is not D5's retrieval chunk. That is a
  second table, a second cache namespace, and a second thing to explain. graphrag's single
  `TextUnit` is simpler and is why its local search must split a 12k-token budget 0.50/0.15/0.35
  across evidence classes rather than sizing each for its job.
- **Mentions are rows.** Non-destructive resolution costs one row per occurrence — ~840 MB of the
  ~1.65 GB overhead at 10M blocks. graphrag stores `text_unit_ids` as a list column on the entity
  and pays nothing; it also cannot answer "which sentence" or undo a merge.
- **Lazy reports move cost to query time.** The first global query on a cold graph pays inline and
  the operator sees a latency spike, not a batch cost. `reports = "eager"` is one key, and
  `ow graph estimate --reports` prices it.
- **The free tier is the default, so out-of-the-box quality is graphify-tier, not graphrag-tier.**
  Deliberate: zero-cost, zero-key, zero-egress first run buys adoption, and every LLM pass is one
  documented flag away with a printed estimate. A reviewer benchmarking omniweave against graphrag
  at defaults will find us behind on prose entity recall, and we should say so in the README rather
  than be discovered.
- **The BSD-3 clustering default is minutes where the GPL one is seconds.** Licence cleanliness
  bought with latency, visible in the build output, fixed by one optional install.
- **`derive_cover` is another table and another place to be wrong.** A pass that over-claims coverage
  causes silent recall loss. Mitigated by G3 and by `ow graph doctor`, not eliminated.
- **`taint` will be misread as "bad".** It means "derived from a unit that tripped a detector",
  which is often a false positive on a security manual. It is a dimension, not a filter, and every
  surface that shows it must say what it means.
- **We do not solve correlation clustering.** Union-find over pairwise merges is not
  merge-consistent; we retain scores and surface incoherent clusters instead of pretending.

---

## 12. Failure modes, honestly

1. **The input that breaks it: a 4M-cell spreadsheet.** Every cell is a block (D2's ruling). Even
   header-only extraction on a 2,000-column sheet mints millions of anchors. `MAX_MENTIONS_PER_DOC`
   catches it and quarantines, but the *right* answer — profile a column, mint one entity for the
   column, not one per cell — is a `derive.entity.sheet` pass I have specified but not designed.
   Until it exists, spreadsheet-heavy corpora will hit the budget and the operator will see
   `OWG_ITEM_BUDGET` on real, legitimate documents.
2. **`anchor_delta` is only as good as the anchor extractor.** If `derive.anchor.native` misses a
   defined-term style ("Capitalised Terms shall have the meanings given in Schedule 1"), the removed
   name is never detected, no unbind happens, and an edge points at a definition that no longer
   exists. Incremental then diverges from full in exactly the 4.3%-of-edges way codegraph measured.
   G12 catches it only if the fixture corpus contains that pattern. **The fixture corpus is the
   control, and it will be incomplete.**
3. **The plurality carry rule is unstable at n=2.** A cluster of two mentions that splits has no
   plurality; the tiebreak is lowest `mention_id`, which is arbitrary and will churn `e412` for
   someone. Stated rather than hidden; `entity_history.superseded_by` makes it recoverable.
4. **MinHash persistence is a second index that can drift.** `minhash_block` is rebuilt whenever
   `normalize_key`, `lsh_perms` or `lsh_threshold` change, and nothing forces that rebuild except a
   version check I have specified (`meta['graph.resolve_signature']`). A forgotten bump means new
   mentions silently stop finding old clusters — recall loss with no error.
5. **Lazy reports plus a tight budget produce a permanently thin global search.** If every query
   defers report generation, reports never get written and every global answer is `degraded`. The
   escape is the eager backfill, which an operator has to notice they need.
6. **Union-find over user splits is not stable under later automatic merges.** A `polarity = -1`
   pair blocks that pair, not the transitive path around it. A user who splits A|B can see them
   rejoin via C. Detectable (`ow graph doctor --violated-splits`), not preventable by union-find;
   the real fix is constrained correlation clustering and it is not v1.
7. **The injection corpus is a snapshot.** 40 fixtures written in 2026 against 2026 attack shapes.
   A new carrier (a font ligature payload, a PDF optional-content group) is invisible until someone
   adds a fixture. The suite is a floor, not a proof, and the docs must say graphify's sentence.
8. **`entity.description` is model-written text that lives in the store forever.** It is marked
   synthetic and never quotable, but it *is* rendered to agents, and a hostile document can put text
   in it. `sanitize_label()` and the `taint` bit are the controls; neither is a guarantee.
9. **`ow graph diff` is O(graph), not O(delta).** On a 1.5M-entity graph it is a full table scan and
   a sort. Fine at 10 s; annoying if someone puts it in a loop.

---

## 13. Why I reject the alternatives

- **"Adopt graphrag's knowledge model verbatim" (`_index/framework-blueprint.md:179`).** Overturned
  in three places, each with a measurement behind it. (a) `Relationship.source/target` are
  uppercased entity *titles* (`graph_extractor.py:139-141`), which makes the whole entity resolution
  a `groupby("title")` and splits any entity whose spelling drifts. (b) `Community.level` is a `str`
  the update path `.astype(int)`s (`index/update/communities.py:52`) — type drift across a seam that
  is a real bug source. (c) `Document`/`TextUnit` duplicate what D2 already owns; recreating them
  would be exactly the "model plus a sync layer" D2 rejected. The *shapes* — the `id`/`short_id`
  split, `TextUnit` being `Identified` not `Named`, `frequency` vs `degree` as two columns,
  `covariate_ids` keyed by type, and the covariates table entire — are adopted and cited.
- **A separate deterministic tier with its own tables (graphify's shape).** graphify needs
  `_is_ast_tier` because its store is a NetworkX graph in a JSON file with no provenance columns.
  D2 gives us `method`, `producer_id` and `origin_operator` for free, and D-runtime already rules
  that ownership is the replacement key. A tier column would be a fourth provenance axis meaning the
  same thing as an existing one — and the moment a third party ships a pass that is *both* (regex
  plus a small local model), the tier predicate has no answer and the tier table has no home.
- **graphrag's `StandardUpdate` incremental path, in whole.** Four independent defects: title-only
  delta detection with no content hash, so an in-place edit reports "No new update documents found"
  and stops (`incremental_index.py:29-58`); `deleted_inputs` computed and consumed nowhere; entity
  merge with `"degree": "first"` and a literal `# todo`; and communities never recomputed, id-shifted
  by `old_max + 1` and concatenated so one entity lives in two hierarchies with two reports. It also
  `_copy_previous_output`s the entire index per update — adding one document to a 50 GB index copies
  50 GB. Every one of those is a design decision I have inverted explicitly above.
- **`max_cluster_size = 10` and `use_lcc = True`.** The absolute cap generates ~300k leaf communities
  on 3M entities and therefore the biggest LLM bill in the pipeline; `use_lcc` silently discards
  everything outside the largest component, which on a heterogeneous document corpus is most of it.
  graphrag knew `use_lcc` was a stability hazard — it ships `graphs/stable_lcc.py` to make the
  discard *deterministic* — and fixed the symptom rather than the policy.
- **`prune_graph`'s standard-deviation thresholds and `remove_ego_nodes = True`.** Both stages
  compute cut-offs as standard deviations above the mean on a power-law degree distribution, so
  `_get_upper_threshold_by_std` keeps almost everything; and deleting the single highest-degree node
  outright is graphify's "god node" insight used as a filter instead of a signal. Quantiles, and
  `min_edge_weight_pct = 40.0`, which is the one filter there that does work.
- **Delimited-text extraction (`<|>` / `##` / `<|COMPLETE|>`).** The record-type test is
  `== '"entity"'` with the literal quotes as part of the match, so a model emitting `entity<|>…`
  yields zero rows silently; there is no unparsed-record counter and no salvage, making total parse
  failure of a chunk indistinguishable from "this chunk had no entities". Structured output with a
  nullable-leaf schema, an `OWG_UNPARSED_ITEM` quarantine row, and a per-pass unparsed counter in
  `graph_observation`.
- **Storing `source_text` on the claim (graphrag's covariates column).** A verbatim copy beside D2's
  `block.text` is a second representation that drifts on any re-parse, and D2's whole `quote`
  discipline exists to stop exactly that. A `(observed_block, ts_a, ts_b)` span resolves to the same
  string and stays correct through `rebind`.
- **A hyperedge table.** graphify has one because NetworkX cannot express a hyperedge, and stores it
  in `G.graph["hyperedges"]` — outside the graph, capped at 3 per chunk, with defensive member
  coercion and a stderr warning. One producer, no query, no index. Reified as `group` entities plus
  `member_of` edges it inherits traversal, ranking, resolution, communities and citation for free.
- **Entity resolution as a `derive/1` driver.** Tempting for extensibility, impossible under D3: a
  resolver needs corpus-wide state and *"A Driver never receives `RunContext`, the store, the cache,
  the budget ledger, or a writable root."* The pluggable parts are the two that can be pure — a
  `normalize_key` implementation, and an LLM tiebreak that is a `derive/1` driver receiving only
  candidate *pairs* as a blob. Keeping the resolver in the host is what keeps the driver contract
  small enough to implement in an afternoon.
- **Putting entity spans in D2's `mark` table.** D2 asks the question and states the test: *"if a
  span carries its own provenance, trust and producer, it is not a Mark."* A mention carries seven
  provenance fields, a `taint` bit, a `pass_id` and its own identity constraint. It is an assertion
  about the document, not a formatting annotation, and folding it into `mark` would put L3
  provenance inside an L2 table — which D2's own consequence section forbids.
- **`graph.json` / NetworkX as the primary store.** graphify's own stated ceiling is *typical
  < 5 MB / < 50k nodes, hard caps 50 MB / 100k nodes* — two to three orders short of 10M blocks —
  and D2 already ruled one store. Graph exports (`ow export graph --format graphml|cypher|parquet`)
  are derived artifacts. If a committed graph artifact is wanted, graphify's union merge driver with
  its caps is the shipped answer, not the primary.
- **Any use of jcodemunch-mcp code.** Its Dual-Use Licence v1.1 bars use *"within a for-profit
  organization to support revenue-generating activities"* and bars publishing any derivative or
  **portion** to a package registry. Its retrieval thinking is cited as prior art and reimplemented
  clean-room; no line is copied, and that fact is recorded.
- **`leidenalg` / `python-igraph` as the clustering dependency.** GPL-3.0 and GPL-2.0 respectively.
  D3's `compute_tier` puts both at `restricted` (`spdx in COPYLEFT_STRONG`), so the default policy
  `allow_tiers = ["open"]` would refuse them anyway — better to never write the import than to ship
  a default that fails its own licence gate on first run.

---

## 14. Consequences for other layers

- **D5 (storage/indexing/retrieval)** inherits `entity_id`, `edge_id`, `community_id` as join keys
  and the three embedding targets, named to their consuming retrieval mode per graphrag's rule:
  block text (basic/local), `entity.description` (mention→node resolution), `community_report.
  full_content` (thematic). `edge.description` is **not** embedded — graphrag has the field and
  never embeds it either. D5 must not overwrite `derive_unit`; its retrieval chunks are its own.
  D5's absence contract gains four new gates from here: `reports_absent`, `unresolved_backlog > 0`,
  `resolution_quarantined`, `pass_disabled(lane)`.
- **D6 (runtime)** gets `(unit_uri, unit_part=NULL, operator=<pass_id>)` as the `work` row identity
  for document-granularity passes and `(corpus, NULL, 'derive.community.*')` for corpus ones.
  `derive_state.cache_key` uses §7.5's three-group canonical digest unchanged.
- **D4 (router)** gains six lanes (`anchor, xref, entity, claim, community, summary`) in its open
  registry and no new rungs. Extraction decisions are `ENRICH`; gleans are `attempt > 1`.
- **D9/D10 (out, serve)** get `restriction_bits` on every graph row, so "may I ship this deck" is
  one indexed predicate over blocks *and* entities; and they get the `Locate` type, which returns a
  typed `quad_source: "unavailable"` with a reason rather than a guessed rectangle.
- **The permanent burden:** the injection fixture corpus and the `type_vocab` tuning prompts are
  living artifacts with an owner, and `omniweave-conform`'s `derive` profile must stay under the
  five-minute laptop budget as suites accumulate.

---

## 15. Open questions (each with the experiment that settles it)

- **Is 0.6 deterministic mentions per body block right?** Every storage number above scales off it.
  Run the five shipped free passes over ten real 200-page documents (a 10-K, a court filing, a
  scientific review, a merger agreement, a spreadsheet-heavy operations report) and count mentions
  per block by `kind`. If dense corpora land at 2.0/block, the mention cap and the +50% storage
  figure both need retuning.
- **What is the block-miss rate of LSH at 0.7 / 128 perms on document entities?** graphify tuned it
  on code symbols. Sample 1,000 known-identical cross-document pairs from an annotated corpus and
  measure. If it is above ~3%, either the shingle size or the band count is wrong for prose names.
- **Does the `entity`/`community` short-id space actually get emitted reliably by current models?**
  graphrag's `short_id` premise is untested for `c3.1`. Measure emission accuracy for `d7#412`,
  `e412`, `c3.1` and `k412` over 1,000 generations; if `c3.1` is confused with a section number,
  change the sigil before anything ships.
- **Should `derive_unit` and D5's retrieval chunk be unified after all?** Measure extraction F1 at
  1,500-token units versus at D5's chunk size on an annotated corpus. If the difference is under
  ~2 points, one table wins on simplicity and I would take it.
- **Is `taint` actionable or decorative?** Instrument it: count how often a `taint=1` item is
  surfaced, reviewed, or suppressed over a 90-day pilot. The digest's rule is that a field with
  fewer than three consumers rots into decoration, and `taint` currently has two.
- **Does eager reporting under the relative cluster cap produce *useful* reports?** A 25%-of-graph
  community on a 1.5M-entity corpus is 375k entities — a report over it is meaningless. Measure the
  size distribution after the cohesion split on real corpora; if the tail is still huge, a hybrid
  (relative cap with an absolute ceiling of a few thousand) is needed and the cost table changes.
- **Confirm `graspologic-native`'s SPDX and its wheel coverage** before `omniweave-driver-leiden`
  ships. D3's `compute_tier` gates it; if the wheels do not cover aarch64-darwin, the "one pip
  install" fix is not one pip install for half the developer population.
