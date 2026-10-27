# D9-serve — the agent-facing surface (PRAGMATIST)

## Headline

**Three listed MCP tools behind a frozen 1,200-token `tools/list` baseline, one composite retriever
whose response is a fixed-section Markdown document carrying a per-passage provenance line and a
four-state verdict with ten named gates, every handler a thin wrapper over exactly one `ow` CLI verb
rendered by exactly one renderer, OUT delivered as generated skills + CLI rather than MCP tools, five
hooks whose `PreCompact` deliberately says nothing, and an `ow init` / `ow uninstall` pair proven
symmetric by a byte-identity CI gate — shipped in four three-week phases each of which ends with
something a real user runs.**

---

## 1. The resolution: codegraph's 1 vs jcodemunch's 110

The panel brief asks for a rule, not a hedge. Here it is, in four clauses, all mechanical.

### R-LIST-1 — Capability is a CLI question. Listing is a token question. They are never the same decision.

Every capability omniweave has is an `ow` CLI verb. Always, with no exception and no dependency on
whether an MCP client exists. This is codegraph's actual structure, not its slogan: it defines eight
MCP tools, lists one (`DEFAULT_MCP_TOOLS = new Set(['explore'])`, `tools.ts:1300-1308`) and keeps
**every** verb on the CLI (`codegraph node|query|callers|callees|impact|files|status|explore|
context|affected`, `src/bin/codegraph.ts`). The collapse is MCP-only. jcodemunch reached the same
place from the other end: 108 tool modules, ~91 advertised, then a 3-verb `order/menu/route` front
door shipped as the default for new installs (`counter.py`).

### R-LIST-2 — The listed set is governed by a frozen token budget, not by taste.

`benchmarks/schema_baseline.json` holds the tiktoken `cl100k_base` count of the entire `tools/list`
payload (`[{name, description, inputSchema}]`) at every surface × compact-mode combination.
`tests/test_schema_budget.py` fails at **5% drift**. This is jcodemunch's own mechanism and its own
receipt: `full_full` 22,741 tokens vs `counter_full` 939 — **24.2×**, paid every turn whether a tool
is called or not, and `core_compact` once had **4 tokens** of headroom, which is what made "remove an
advanced param from the minimal surface" the fix instead of "shave words".

omniweave's frozen baselines:

```
ow_default_full      1150     # the 3 listed tools, full schemas          <- the number that binds
ow_default_compact    880     # advanced params stripped from the SCHEMA, handler still honors them
ow_wide_full         4300     # OMNIWEAVE_MCP_TOOLS=<9 names>, for callers who know what they want
```

**Resident cost of the whole omniweave surface must stay under 1,500 tokens/turn.** Over a 40-turn
session that is 46,000 tokens. The same session against a jcodemunch-shaped surface is 909,640.

### R-LIST-3 — Promotion test. A fourth listed tool must pass all four, in the PR, with numbers.

1. **Inexpressible.** The question cannot be phrased inside `ow_retrieve`'s six parameters.
2. **Net-negative token delta.** On the 30-task `bench/serve/` eval, `(schema tokens × turns) +
   (response bytes)` is *lower* with the tool listed than with the same work routed through
   `ow_do`. Measured, committed as a row in `benchmarks/promotion/<tool>.json`.
3. **Different response kind.** It returns something the composite's renderer cannot emit — rows
   instead of bytes, a job id instead of an answer, an image block instead of text.
4. **Fits, or evicts.** It stays inside 1,150 tokens or it names the incumbent it displaces. Raising
   the baseline is a separate, reviewable line in the same PR.

Anything failing any clause is an unlisted handler reachable through `ow_do`, and its description
ends with the redirect sentence — codegraph's discipline, so re-enabling it preserves the steering
(`'Quick symbol search by name. … Use codegraph_explore instead …'`, `tools.ts:1043`).

### R-LIST-4 — Gate listing *and* dispatch, on one env var, and never gate availability on index presence.

`OMNIWEAVE_MCP_TOOLS=retrieve,corpora,do,doc,parse,compile,verify,route,jobs` allowlists both
`tools/list` and execute-time dispatch; a client remembering a name from a previous session gets
`Tool ow_doc is not listed on this surface; set OMNIWEAVE_MCP_TOOLS or call ow_do(action="doc").`
Tool *availability* is never gated on whether a corpus is indexed — codegraph #964: gating on
`./` having an index broke monorepos and a server started before `init` never surfaced its tools
afterwards. The **instructions** are gated instead, in two variants.

### Why three, not one

codegraph's one-tool result is right and I am adopting it for retrieval. I list two more, and I owe
the panel the reason each survives R-LIST-3 rather than "it felt useful":

- **`ow_corpora`** — codegraph serves one repo rooted at one path; omniweave is inherently
  multi-corpus (a legal matter, a data room, a personal archive, a shared drive mount) and the
  question "what corpora exist and what is in them" is *not* a retrieval query and cannot be phrased
  as one. Without it the agent's fallback is Glob + Read over `.omniweave/`, which is 2–3 round trips
  and teaches it to poke at the filesystem — the exact reflex the whole design exists to remove.
  It returns rows, not bytes (clause 3), and its schema is ~140 tokens (clause 4).
- **`ow_do`** — the escape hatch is what makes the one-tool decision *permanent*. It is the reason
  the listed set never has to grow again, and it is the only path for hosts where the agent has no
  shell (some MCP-only clients) and therefore cannot reach the CLI. ~200 tokens buys a cap on the
  surface forever. jcodemunch measured this trade at 939 tokens for three verbs; I fold `menu` into
  a reserved action and pay ~200 for one.

I am **not** listing an OUT tool. Section 6.

---

## 2. `ow_retrieve` — the composite tool

### 2.1 Schema (the whole thing; six params)

```jsonc
{
  "name": "ow_retrieve",
  "annotations": {"readOnlyHint": true, "destructiveHint": false,
                  "idempotentHint": true, "openWorldHint": false},
  "description":
    "Retrieve passages from an indexed document corpus (PDF, Office, scans, decks, email). Returns "
    "the source text of the matching passages grouped by document — each with a citable id, page, "
    "provenance and confidence — plus where they sit in the document structure and what they relate "
    "to, in one budgeted call.\n\n"
    "Use this INSTEAD of opening, converting or grepping source documents: they are already parsed, "
    "and this hands back the text you would otherwise extract yourself. It also proves absence: a "
    "verdict of `absent` means the whole corpus was scanned and the answer is not there.\n\n"
    "Examples: 'revenue guidance for fiscal 2026' · 'what does the MSA say about termination for "
    "convenience' · 'the table of per-region headcount' · 'the slide where the roadmap is shown'.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query":     {"type": "string",  "maxLength": 10000},
      "corpus":    {"type": "string",  "description": "corpus id from ow_corpora. Omit for the default."},
      "locators":  {"type": "array", "items": {"type": "string"}, "maxItems": 32,
                    "description": "cite ids from a previous response, e.g. \"d7#412\". Widens around them."},
      "want":      {"type": "array", "items": {"enum": ["text","structure","related","page_image","fields"]}},
      "scope":     {"type": "string",
                    "description": "doc:d7 | doc:d7/p12-40 | format:pdf | since:2025-01 | indexed"},
      "max_chars": {"type": "integer", "minimum": 2000, "maximum": 25000}
    },
    "required": ["query"]
  }
}
```

Three-part description shape taken from LEANN (`mcp.py:53-62`): **what it returns / when to reach for
it / four literal example queries**. The examples teach the register — natural-language phrases, not
`§`-and-page addresses — which is the thing an agent guesses wrong.

`corpus` is **promoted to `required`** when the server has no default corpus, generated purely per
request, never by mutating the shared schema array. codegraph's `withRequiredProjectPath`
(`tools.ts:1240-1262`): *"A `required` field is a HIGH-salience channel … unlike the instructions
text the reporter found too weak to stop the agent omitting the param."*

Compact mode (`OMNIWEAVE_MCP_COMPACT=1`, default on the `ow_default_compact` surface) strips `want`,
`scope`, `max_chars` from the **schema** while the dispatcher keeps honoring them, and
`_DECLARED_ARG_KEYS` is snapshotted *before* the strip so a hidden-but-honored param is never
reported as unknown (jcodemunch `server.py:938-985`).

Input caps, each with a reason: `query` 10,000 chars (*a 100 MB string forces a full FTS5 scan*),
`locators` 32, `scope` 512, `corpus` 128.

### 2.2 Response — fixed section order, one renderer, hard ceiling

The response is **one Markdown document**, not JSON. Rationale, from measurement not taste: MUNCH's
tabular encoding buys 39.4–55.4% (median 45.5%) on row-shaped results and **0% on verbatim text**
(`TOKEN_SAVINGS.md`), and omniweave's flagship payload *is* verbatim text. A JSON envelope would
roughly double the cost of the half that cannot be compressed, to structure the half that can be
structured with pipe tables at a third of the price. So: Markdown for the model; the compact pipe
encoder applied to the row-shaped sections only, behind MUNCH's `≥15% savings` gate with fail-open to
plain Markdown; `--format json` exists for the SDK and for `ow query`, and is never the MCP default.

Section order (documents with a fixed section order beat prose — codegraph §1.3):

```
0  UNREAD-PAGES BANNER            only when a doc in scope has diag rows in the absence set
1  STALENESS BANNER               only when a source is edited-unread or the store is frozen
2  **Retrieve: "<query>"**
3  VERDICT LINE                   always, one line, sentinel-substituted last
4  **Where this sits**            structure table (doc, title, section path, pages)
5  QUOTE-TIER HEADER              selected by the MINIMUM quote tier present (3 variants)
6  **Passages**                   the bytes. one header line + one fence per passage.
7  BACK-REFERENCES                "Already sent earlier in this conversation" pointers
8  **Related**                    rel-table; gated off below 50,000 blocks
9  **Not shown**                  pointer list, rank order
10 BUDGET NOTE
11 LICENCE NOTICES                D3 requires licence_notices[] on the envelope
```

The counts in §3 are emitted through a `[[ow-retrieve-summary]]` sentinel substituted after
truncation, because *the honest count is only knowable after packing* — codegraph #1046: reporting a
260-symbol candidate pool as the answer is a lie.

Hard ceiling: `max_chars` default from the tier table, `hard_ceiling = min(round(max_chars*1.5),
25_000)`. The 25,000 is the host inline tool-result cap: above it the result is externalized to a
file the agent must Read back, *reintroducing exactly the read the tool exists to remove* (measured
on a 35 K response, `tools.ts:220-231`). This is the single most reusable number in the mine and I am
taking it verbatim.

**Tiers keyed on indexed blocks, not documents.** D2 fixes 60–120 blocks/page and makes cells blocks,
so a 137-document corpus can be 41 k blocks or 4 M; documents is the wrong unit.

| indexed blocks | max_chars | max_docs | chars/doc | max_passages | related | pointers | budget note | calls |
|---|---|---|---|---|---|---|---|---|
| < 5 000 | 13 000 | 3 | 4 000 | 8 | off | off | off | 1 |
| < 50 000 | 18 000 | 5 | 4 500 | 14 | off | on | off | 2 |
| < 500 000 | 24 000 | 6 | 6 500 | 20 | on | on | on | 3 |
| < 5 000 000 | 24 000 | 8 | 7 000 | 24 | on | on | on | 4 |
| ≥ 5 000 000 | 24 000 | 8 | 7 000 | 24 | on | on | on | 5 |

Monotonicity invariant: a larger tier never gets a smaller `chars/doc` than a smaller tier. Meta-text
(related / pointers / budget note) is gated **off** on small corpora because prose is pure overhead
when one call is the whole story.

### 2.3 Provenance and confidence, per passage, on one line

D2 gives me the fields; the job is to spend as few characters as possible on them. A separate
provenance table doubles the cost, so provenance rides the passage header:

```
**`Q3-Report.pdf`** · d7 p14 · `d7#412` · normalized/extracted · parse.pdf.pdfium@1.4.0 · 0.94
```

Field by field, all D2 names verbatim: the display name; `doc_ord` + `page`; **`cite`** (`d7#412` —
D2: *the only id an LLM may emit or receive*; `block_id` never appears, `addr` appears only in
`--format json` and on the CLI); `quote` / `trust` as a slash pair from D2's closed vocabularies
(`verbatim|normalized|reflowed|reconstructed|synthetic` and `ambiguous|inferred|extracted`); the
`Producer` rendered as `operator@op_version` with `model_rev[:8]` appended when non-null; and
`score` printed **only when `score_kind` is non-null**, because D2 makes `(score, score_kind)`
nullable together and a bare number whose scale is unnamed is worse than no number.

Cost: ~95 chars per passage. At 20 passages that is 1,900 of a 24,000 envelope — 8%. Acceptable, and
it is what lets the response make a claim it can defend.

### 2.4 The verbatimness claim is per-passage and conditional. This is the D2 obligation.

codegraph's load-bearing paragraph — *"the verbatim, current on-disk source … byte-for-byte identical
to what the Read tool returns … treat each block as a Read you have already performed"* — is what
stops the second Read, and it is also a claim codegraph makes globally with **no confidence field at
all** (mine-serve §1.12). D2 forbids that here: *"Serve may claim byte-exactness only for
`verbatim`"*, and `verbatim` requires `os_kind='bytes'` **and** `part.store_ref IS NOT NULL`. Most
PDF drivers declare `origin_span: none` and produce `normalized` or lower.

So the header is selected mechanically from a three-row table keyed on `min(quote)` across the
rendered passages:

| min tier | header emitted |
|---|---|
| `verbatim` | *"Every body below is the original source bytes, byte-identical to the file on disk. Treat each as a read you have already performed: do not open these documents."* |
| `normalized` / `reflowed` | *"Bodies below are the extracted text of these documents — complete and correctly ordered, with whitespace and hyphenation normalised. Quote them by id. They are not byte-identical to the file; if you need the exact bytes, run `ow doc show <cite> --verbatim`."* |
| `reconstructed` / `synthetic` | *"Bodies below are reconstructions produced by OCR or a model, not extracted text. Cite them by id and say so; do not present them as quotations. `ow doc verify <cite>` reports what each was checked against."* |

Per-passage exceptions are marked inline: any passage whose tier is worse than the header's is
prefixed `⚠ reconstructed —`. Enforced by S5 below. **This is a product limitation and the correct
one**: shipping the verbatimness paragraph over a reflowed PDF paragraph is a lie the agent cannot
detect.

### 2.5 The verdict — four states, ten gates, one `absent` return site

Reimplemented from `mine-graph.md` §4.6 (jcodemunch is dual-use licensed — reimplement, never
vendor). The four states are `ok | low_confidence | absent | degraded`. `result_count == 0` becomes
`absent` only after failing ten gates in precedence order; any gate forces `degraded`.

| # | gate | omniweave source of truth |
|---|---|---|
| 1 | `timed_out` | the `deadline_ms` narrowing (D4) elapsed mid-scan |
| 2 | `channel_requested_not_run` | vector channel requested, `embed` driver probe red (D3/D4 `Degradation(kind="driver_unavailable")`) |
| 3 | `index_changed` | store `generation` (D4's integer, never a clock) bumped between plan and pack |
| 4 | `coverage_incomplete` | `documents_discovered > documents_indexed` for the corpus |
| 5 | `source_edited_unread` | graphify's racily-clean rule: `mtime_ns + 2s > indexed_at_ns` for any doc in scope |
| 6 | `freshness_unknown` | corpus freshness is `unknown` (not `not_tracked` — that is disclosed, not refused) |
| 7 | **`parse_partial_in_scope`** | **any doc in scope has `doc.status IN ('partial','failed')`, or a `diag` row whose `code` is in the absence set** |
| 8 | `budget_truncated` | `matches_before_packing > 0` — an empty response is not an empty search |
| 9 | `restricted_items_withheld` | D3's `restriction_bits` filter removed candidates from the pool |
| 10 | `absence_unprovable_by_mode` | checked LAST: only a vector channel ran; a cosine zero is a statement about the model, not about the corpus |

Gate 7 is the one nobody else has and it is why this design is worth building. It is a single indexed
query — D2 ships `CREATE INDEX diag_code ON diag(code)` with the comment *"the serve layer's absence
contract reads this"* — over a closed absence set:

```
ABSENCE_BLOCKING_DIAGS = {OW_ENCRYPTED, OW_NEEDS_OCR, OW_TIMEOUT, OW_TRUNCATED_BY_BUDGET,
                          OW_DRIVER_UNAVAILABLE, OW_MISSING_PART, OW_MALFORMED,
                          OW_UNSUPPORTED_FORMAT, OW_RESOURCE_LIMIT, OW_ORIGIN_SPAN_DOWNGRADE}
```

"OCR failed on pages 12–40" is currently a silent confident zero in every RAG system in existence.
Here it is a `degraded` verdict with the page range and the command that fixes it.

Enforcement: `verdict()` has **exactly one** `return STATE_ABSENT` site, counted by semgrep. Every
future hazard is expressed by forcing `degraded`, never by adding a second citability rule.

`scorer_version` is printed on the verdict line, because *"0.8 under scorer v1"* is a measurable
statement and *"0.8"* is not.

### 2.6 Cross-call dedup — and omniweave already has the fingerprint

codegraph's per-session emission ledger is the strongest single idea in the mine and it transfers
without modification, except that codegraph must compute `len:sha1[:16]` at read time and **omniweave
already stores the fingerprint**: D2's per-block `content_digest` (blake3-128, merkle over children,
geometry and spans deliberately excluded). Dedup is therefore a set difference over digests we
already have, at zero extra hashing cost, and it is correct across a re-parse by construction —
`rebind` rule 1 carries `block_id` on equal `content_digest`, rule 2 changes the digest, so a revised
block is always re-sent.

```python
EXPLORE_LIMITS = dict(MAX_CORPORA=4,        # LRU; per session, never persisted
                      MAX_CALLS_RETAINED=8, # oldest dropped; call_count keeps counting
                      MAX_CITES_PER_CALL=64)
DEDUP = dict(MIN_COVERED_BLOCKS=3,   # below this the ~150-char pointer is BIGGER than the content
             MIN_DELTA_CHARS=400,    # remainder smaller than this folds into the back-reference
             MAX_SPANS_IN_POINTER=4)
```

The back-reference wording is engineered and never says "omitted", never steers to a file read:

```
> **Already sent earlier in this conversation:** `Q3-Report.pdf` `d7#404`–`d7#411` (p14) —
> unchanged since, so that copy is still exact and is not repeated here. Use it from your
> context; do not re-open the file.
```

The asymmetry rule governs every threshold: **re-sending something the agent already has costs a few
hundred chars; withholding something it never saw costs a whole retrieval round trip.** Kill switch
`OMNIWEAVE_DEDUP=0`; per-session, never persisted, because dedup across sessions would suppress
passages a new agent has never seen.

### 2.7 The packer — reserve, then render

codegraph's `EXPLORE_ALLOCATION` shape, with the constants **re-derived for documents and put in a
config file with the fixtures as tests**, because inheriting anecdote-calibrated constants is the
methodology mistake mine-serve §1.12 names explicitly.

```toml
# packages/omniweave-core/src/omniweave_core/retrieve/packing.toml
cliff_fraction        = 0.15   # below 15% of the top doc's weight -> pointer only, ~110 chars
cliff_exempt_above    = 10.0   # a full-strength identity match is never cliffed
min_chars             = 400    # DERIVED: header(95) + fence(10) + pointer-sentence(150) = 255.
                               # below ~400 a fenced excerpt costs more than the pointer it replaces.
max_share             = 0.55   # one 400-page report must not eat the envelope
doc_overhead          = 120    # header line + fences, charged against the pool before allocation
passage_overhead      = 95     # the provenance line
whole_section_buy     = 0.60   # a reservation covering 60% of a section buys the whole section
buy_overshoot         = 0.15   # funded from ONE shared pool, spent in rank order
spine_boost           = 2.0    # a passage on the heading spine of a hit is weighted up, cliff-exempt
```

Three properties I am keeping verbatim from codegraph because the reasoning is right:
a reservation is a **guarantee, not a race** (first-come-first-served let the top two items exhaust
the envelope); a cliffed item costs ~110 chars instead of ~4,500 **and does not consume a doc slot**,
which is the concentration lever; and the whole-section buy is funded from **one shared pool**
because N independent per-item overshoots inflate the response until the ceiling drops whatever is
last, and a dropped section is strictly worse than a clustered one.

**Two omniweave-specific packer rules the source repos do not need:**

- **`TABLE_PROMOTE`.** A hit whose `kind` is `TABLE_CELL` is never packed alone. It promotes to its
  `table_meta` parent and the renderer emits a **window** of the grid: the hit's ±3 rows and ±3
  columns plus `header_rows`/`header_cols`, resolved through D2's `Grid.slot()` (O(1); zero
  `grid_slot` rows when `has_merges = 0`). Without this rule, one query against a 4 M-cell workbook
  returns forty thousand 12-character passages and the pointer list becomes the answer.
- **`LAYER_FILTER`.** Default `layers = {body}` (D2's `Layer`). `furniture` and `note` are packed only
  when the query matched inside them, and then they are labelled — a page footer that name-collides
  on a domain word is worth ranking and worth almost nothing in bytes. This is the "relevance and
  worth are two different scores" rule, applied where documents actually need it.

The epilogue (pointer list → budget note → licence notices) is fitted against **remaining** room in
priority order, and at final truncation the epilogue is cut **before** a passage section. When
nothing fits, one line survives:

```
> (Trailing pointer list omitted for size. The passages above are complete — treat them as read.
>  For anything this call did not cover, run ow_retrieve again with the specific terms rather
>  than opening those documents.)
```

### 2.8 Worked responses

**Degraded-with-results:**

```
⚠️ 2 documents in scope have unread pages. A thin or empty result here is NOT evidence of absence.
  - Q3-Report.pdf pages 12–40 — OW_NEEDS_OCR, no ocr driver enabled  ->  ow doctor --drivers
  - appendix-c.pdf — OW_ENCRYPTED                                    ->  ow add appendix-c.pdf --password

**Retrieve: "revenue guidance for fiscal 2026"**
9 passages across 3 documents · verdict **degraded** (parse_partial_in_scope) · scanned 41,208
blocks / 137 docs · scorer v1 · channels lexical=ok vector=ok structure=ok identity=ok

**Where this sits**
| doc | title | section | pages |
|---|---|---|---|
| d7  | Q3-Report.pdf     | 2. Outlook › 2.1 Guidance | 14–16 |
| d31 | earnings-call.docx| Prepared Remarks          | —     |

Bodies below are the extracted text of these documents — complete and correctly ordered, with
whitespace and hyphenation normalised. Quote them by id. They are not byte-identical to the file;
if you need the exact bytes, run `ow doc show <cite> --verbatim`.

**Passages**

**`Q3-Report.pdf`** · d7 p14 · `d7#412` · normalized/extracted · parse.pdf.pdfium@1.4.0 · 0.94
```text
We expect fiscal 2026 revenue of $4.10–4.25B, representing 11–15% growth …
```

**`earnings-call.docx`** · d31 · `d31#88` · verbatim/extracted · parse.office.anydoc@0.2.4
```text
…on guidance, we are raising the low end of the range and holding the top…
```

> **Already sent earlier in this conversation:** `Q3-Report.pdf` `d7#404`–`d7#411` (p14) —
> unchanged since, so that copy is still exact and is not repeated here. Use it from your
> context; do not re-open the file.

**Related** (3 of 11)
| from | rel | to |
|---|---|---|
| d7#412 | caption_of | d7#415 — Table 3: Guidance by segment |
| d7#412 | continues  | d7#431 (p15) |

**Not shown**
- d52 `policy-memo.pdf` p3, p9 — 2 passages · retrieve with scope="doc:d52"
- 4 more documents

> **Retrieve budget: 3 calls for this corpus (41,208 blocks).** Each call covers ~6 documents. If
> your question spans more, spend the remaining calls on the uncovered area before opening files.
> Licence: no restricted items in this response.
```

**Proven absence** — the answer that saves the most tokens, and the one only this design may give:

```
**Retrieve: "SOC 2 Type II attestation date"**
0 passages · verdict **absent** · scanned 41,208 blocks / 137 docs · coverage 137/137 indexed,
0 skipped · scorer v1 · channels lexical=ok vector=ok structure=ok identity=ok

No document in corpus `acme-2026` contains this. Every indexed document was scanned, every
requested channel ran, no page in scope is unread, and the response was not truncated — this is a
proven absence and you may rely on it. Do not grep the corpus to double-check.

Near misses: `d19#204` "SOC 2 readiness assessment" (0.31) · `d3#77` "attestation" (0.28)
```

**Unproven zero** — same query, one broken driver:

```
0 passages · verdict **degraded** · because: parse_partial_in_scope, coverage_incomplete

This is NOT evidence of absence. Pages 12–40 of Q3-Report.pdf were never read (OW_NEEDS_OCR) and
14 of 151 discovered documents are not indexed. Either fix the gap (`ow doctor --drivers`) or
re-ask scoped to what was actually read: scope="indexed".
```

### 2.9 Errors

`isError: true` is reserved for **"stop trying"**, and that is one class only: a policy refusal
(a path outside the configured roots, a restricted-licence artefact, a state-change without
`allow_write`). It ships **without** retry guidance, because abandoning the path is the desired
reaction. Everything else — corpus not indexed, driver unavailable, budget exhausted, deadline
elapsed, no such corpus — returns a **success-shaped** response with the banner and the exact command
that clears it. One early `isError` teaches the agent the toolset is broken and it stops calling,
observed repeatedly (codegraph `tools.ts:64-80`), and D4 already binds me: *"A budget-exhausted parse
returns a success-shaped response with a banner, never `isError`."*

Every response carries D4's `degradations[]` and D3's `licence_notices[]`, rendered as the last two
lines. `Degradation.message` must name the knob that would raise the limit, which turns an error into
a pricing conversation.

---

## 3. `ow_corpora` — how an agent discovers what exists and what is in it

```jsonc
{"name": "ow_corpora",
 "annotations": {"readOnlyHint": true, "idempotentHint": true, "openWorldHint": false},
 "description": "List the document corpora this server can search, and what each contains: size, "
                "formats, date range, dominant topics, freshness, and what fraction of it is "
                "reliably extracted. Call this first when you do not know which corpus to search "
                "or whether the documents you need are indexed at all.",
 "inputSchema": {"type": "object", "properties": {
    "query":  {"type": "string", "description": "filter corpora by name or content"},
    "corpus": {"type": "string", "description": "one corpus id for the full profile"}}}}
```

Response (compact table when ≥15% saving, else Markdown; capped at 4,000 chars with an
`N more — filter with query=` tail):

```
**Corpora on this server** (3)

| id | documents | blocks | formats | span | freshness |
|---|---|---|---|---|---|
| acme-2026 | 137 | 41,208 | pdf 88, docx 31, pptx 18 | 2024-03 → 2026-08 | fresh |
| datroom-b | 2,904 | 1.1M | pdf 2,880, xlsx 24 | 2019 → 2026 | 14 docs indexing |
| personal  | 61 | 9,330 | eml 40, pdf 21 | 2021 → 2026 | stale (6d) |

**acme-2026** — /work/acme/docs
  coverage      137 discovered / 137 indexed / 0 skipped
  extraction    62% of blocks verbatim-or-normalized · 31% reflowed · 7% reconstructed (OCR)
  unread        Q3-Report.pdf p12–40 (OW_NEEDS_OCR) · appendix-c.pdf (OW_ENCRYPTED)
  top terms     guidance, segment, EBITDA, indemnity, termination, headcount, ARR, renewal
  sections      Outlook · Risk Factors · MD&A · Exhibits
  drivers       parse.pdf.pdfium@1.4.0, parse.office.anydoc@0.2.4
```

The two rows nobody else surfaces are `coverage` and `extraction`. They are what make a later
`absent` verdict defensible: an agent that has seen "7% reconstructed, 40 pages unread" already knows
what an empty answer from this corpus can and cannot mean. `top terms` and `sections` come free from
FTS5 and the `kind IN (title, heading)` index — no model call, no extra table.

---

## 4. `ow_do` — the escape hatch and the permanent cap on the surface

```jsonc
{"name": "ow_do",
 "annotations": {"readOnlyHint": false, "openWorldHint": false},
 "description": "Dispatch any omniweave action by name. Read-only unless allow_write=true. "
                "Call ow_do(action=\"_menu\", args={\"query\":\"...\"}) to search the catalog: it "
                "returns each action's name, one-line summary, required args and a worked example. "
                "Use this only for things ow_retrieve and ow_corpora cannot do — parsing a new "
                "document, compiling a deck, inspecting a route decision.",
 "inputSchema": {"type": "object", "properties": {
    "action":      {"type": "string"},
    "args":        {"type": "object"},
    "allow_write": {"type": "boolean", "default": false}},
  "required": ["action"]}}
```

Gate ladder, in this order, because the message the agent sees must be the most actionable one
(jcodemunch `counter.py:104-134`):

```
""                -> "ow_do requires a non-empty 'action'. Call ow_do(action='_menu') to list actions."
listed tool name  -> "'ow_retrieve' is a listed tool on this surface; call it directly."
never-dispatchable-> "'uninstall' is not reachable from an agent surface. Run `ow uninstall` yourself."
unknown           -> "Unknown action 'X'. Call ow_do(action='_menu', args={'query':'X'}) to discover it."
forbidden verb    -> "'X' names a shell/exec verb. ow_do is not a shell; use the ow CLI."
state-changing    -> "'X' writes to the store or the filesystem. Re-issue with allow_write=true."
```

```python
NEVER_DISPATCHABLE = frozenset({"init", "uninstall", "uninit", "corpus_rm",
                                "route_promote", "skills_remove", "targets_remove"})
STATE_CHANGING     = frozenset({"add", "parse", "index", "rebind", "compile", "export",
                                "targets_install", "skills_install", "route_replay", "watch"})
_FORBIDDEN_VERB_RE = re.compile(r"(^|[._-])(exec|shell|eval|spawn|rm|chmod|curl|wget|"
                                r"write_file|patch|apply_patch)($|[._-])", re.I)
```

`NEVER_DISPATCHABLE` is the guard nobody in the collection has: **an agent cannot uninstall omniweave,
delete a corpus, or promote a routing policy.** Those are human verbs.

`_menu` ranking is deterministic idf over the catalog with no embeddings, with jcodemunch's stopword
carve-out (`_MIN_SUBSTRING_LEN = 4`; `find/get/show/search` deliberately kept because they are real
verbs here). Every catalog row carries a curated `example`, and `tests/test_catalog_examples.py`
validates every example key against the live `inputSchema` of its action — a renamed arg fails CI.

---

## 5. Progressive disclosure — the three levels

| level | reach | schema cost | how |
|---|---|---|---|
| L0 default | `ow_retrieve`, `ow_corpora`, `ow_do` | 1,150 tokens | nothing |
| L1 wide | + `ow_doc`, `ow_parse`, `ow_compile`, `ow_verify`, `ow_route`, `ow_jobs` | 4,300 tokens | `OMNIWEAVE_MCP_TOOLS=...` (gates listing **and** dispatch) |
| L2 runtime | every handler, ~40 actions | 0 tokens | `ow_do(action=...)` |
| L3 shell | every CLI verb | 0 tokens | Bash |

Every L1/L2 description ends with the redirect: `… Prefer ow_retrieve, which returns this inline.`

**MCP `instructions` — the only prose that survives tool deferral.** When a host has more tools than
its schema budget allows it ships tool *names* only and withholds schemas until a ToolSearch-style
lookup. `instructions` arrives on a separate track and arrives whole. Budget **1,000 chars** (observed
siblings 660–984); two variants, generated from the catalog, bound to it by
`tests/test_instructions.py` so it can never advertise a tool we do not serve (LEANN's `llms.txt`
declares 2 tools against a server shipping 4; jcodemunch #397 shipped a hand-written CLAUDE.md block
naming ~25 tools the client no longer offered).

```
omniweave indexes documents (PDF, Office, scans, decks, email) into a searchable corpus.

ow_retrieve — any question whose answer is IN a document. Returns the passages themselves with
  citable ids, not a list of filenames. Use it instead of opening or converting a document.
ow_corpora — first call when you don't know which corpus holds what, or whether it's indexed.
ow_do — everything else, by name. ow_do(action="_menu") lists it.

Cite passages by the `d7#412` ids in the response. A verdict of `absent` means the corpus was
fully scanned: trust it, don't re-check. `degraded` means something was unread — the banner says
what and how to fix it. Text marked `reconstructed` is OCR: cite it, don't quote it.

If these tools are deferred (names shown, schemas withheld), load them in ONE lookup:
ToolSearch "select:mcp__omniweave__ow_retrieve,mcp__omniweave__ow_corpora,mcp__omniweave__ow_do"
```

The deferral-load query is the **first** thing a truncating host would keep only if it is early, so it
is emitted on the first line in the no-default-corpus variant and last in the full one; both variants
are under 1,000 chars and both are byte-diff gated. A **second variant** (`INSTRUCTIONS_NO_DEFAULT`)
is served when the server has no default corpus, saying "pass `corpus`" and nothing else — because
the common case must stay short (codegraph `server-instructions.ts:83-96`).

---

## 6. Skills — OUT only, generated, router + stubs

### 6.1 Why OUT is skills and CLI, and gets no MCP tool

Three of three OUT repos in the collection — ppt-master, open-slide, hyperframes — ship **skills and
a CLI and zero MCP servers**. `_index/interfaces.md` records it and calls it deliberate. The reason is
structural, not cultural: nothing in the MCP protocol expresses *"confirm the brief with the user,
lock the spec, run the checker, and if it errors do not proceed"*, and a compile is a **job** (seconds
to minutes, a job directory, a receipt) rather than a call. D1 already made the job directory and the
`omniweave-target/1` protocol the OUT envelope. So OUT is: a router skill that routes, a workflow
skill that drives, and `ow compile` that does the work. `ow_do(action="compile")` exists at L2 for
shell-less hosts and returns a job id, not an artefact.

### 6.2 The set — one core, five on-demand

```
skills/
├── omniweave/                       CORE. 130 lines. The router. Installed by `ow init`.
│   ├── SKILL.md
│   └── references/routes/
│       ├── pptx.md   deck.md   video.md   docx.md   extract.md   review.md   ingest.md
└── (on demand, installed by `ow skills install <name>` on the winning branch only)
    omniweave-pptx/  omniweave-deck/  omniweave-video/  omniweave-extract/  omniweave-review/
```

`isCoreSkill(name) = name == "omniweave"`. Seven route stubs, one per destination — including
`ingest.md`, whose entire content is *"not a workflow; run `ow add <path>` then use `ow_retrieve`"*,
so the router can route **away** instead of failing silently.

Route stubs are hyperframes' sharpest trick and I am taking it whole: the router ships **contracts for
every destination and bodies for none**. Each stub is ~40 lines — inputs, outputs, triggers,
non-goals, the interview entry — and is readable *before* the lazy-installed workflow exists. The
router validates the candidate against its stub and continues routing if the contract is not
satisfied, then installs only the winner. Twenty capabilities at the context cost of one.

Router frontmatter (the description is the entire routing input; 1,024 chars is the agentskills.io
cap and this uses 690):

```yaml
---
name: omniweave
description: >
  Entry point for producing a document, deck, presentation, slide, PPTX, PDF report, DOCX, video,
  explainer, or animated clip from source material — and for editing, reviewing, regenerating or
  applying feedback to one omniweave already produced. Also the entry point for structured field
  extraction from a corpus. Inputs may be an indexed corpus, a brief, a template deck, an existing
  artefact, or a schema. It resumes project state, selects the owning workflow, installs it on
  demand, and hands off. For questions ANSWERED BY documents rather than producing one, do not load
  this: call the ow_retrieve tool or run `ow query`.
---
```

The last sentence is the most valuable one in the file: a router skill's worst failure is capturing
retrieval traffic that belongs to a tool.

### 6.3 Skills are generated artifacts, not authored files

graphify renders 16+ platform variants from fragments + `platforms.toml`, commits the render, and
gates CI on a byte-diff. Hand-maintaining 12,700 lines of skill body across hosts is not possible.
omniweave copies the machinery and starts with **five** platforms, not sixteen.

```
tools/skillgen/            build-time only; NOT in any wheel
├── platforms.toml         [platform.claude] [platform.cursor] [platform.codex]
│                          [platform.opencode] [platform.agents-md]
├── fragments/{core,dispatch,routes,always-on,shell}/
├── expected/              golden render, byte-compared
└── gen.py                 emit | --check | --audit-coverage | --bless
```

Determinism contract, stated and tested: fixed slot order, reference index sorted by name, LF
newlines, **no timestamp and no version ever written into a generated file**. `platforms.toml` carries
graphify's key set with two constraints riding along: the frontmatter `name` must equal the install
folder name (a Claude Code requirement — graphify #1635), so a per-platform body variant must not
change the name; and `description` is preserved **verbatim** per platform.

Integrity: `skills-manifest.json` at the repo root, per-skill **whole-bundle** hash, because the
vercel-labs `skills-lock.json` `computedHash` covers only `SKILL.md` and a drifted `references/` or
`scripts/` inside a pinned skill is undetected — integrity theatre. hyperframes' `hashSkillBundle` is
the shape: full-path sort, path folded into the hash so a moved file changes it, CRLF→LF for text
extensions so a Windows checkout is not reported stale.

Placement: one canonical on-disk location `.agents/skills/<name>/`, with **relative** symlinks
(`../../.agents/skills/<name>`) into each host's dir and a `cp -r` fallback on `EPERM`/`EEXIST` so
Windows without developer mode works (open-slide `sync.ts:47-118`).

---

## 7. The CLI — the substrate both surfaces sit on

### 7.1 Grammar

**A bare verb is reserved for the fourteen things a human types daily. Everything else is
`ow <group> <verb>`, and a group is created only when it has three or more verbs.** That rule is what
stops the surface sprawling; it is also why there is no `ow session` group (two verbs → folded into
`ow doctor --session`).

```
ow init [--target auto|all|<ids>] [--location global|local] [--hooks] [--strict] [--yes]
ow uninstall [--target all] [--location] [--keep-cli] [--yes]
ow doctor [--drivers] [--session] [--extensions] [--json]
ow explain <CODE>                       # OW-V-014 -> what it means, what clears it   (D1)
ow add <path|uri>...                    # acquire + parse + store + index, one verb
ow parse <uri> [--dry-run]              # D2, D4
ow query <q> [--corpus] [--want] [--scope] [--max-chars] [--format md|json|jsonl] [--explain]
ow doc <cite|addr> [show|verbatim|verify|grid|render]      # D2's `ow doc`
ow check [--no-cache]                   # owcheck                                     (D2)
ow rebind <doc> [--allow-unexplained-rebind]                                          (D2)
ow export <doc> -o x.owdoc                                                            (D2)
ow compile <target> [--bake ...] [--job <id>]
ow watch [--debounce 3s]
ow serve --mcp | --http --token-file <p>

ow corpus   list | show | stats | rm | rename
ow route    explain | replay | simulate | lint | scoreboard | propose | promote | audit   (D4)
ow driver   list | check | scaffold | explain                                            (D3, D4)
ow targets  list | install | remove                                                      (D1)
ow skills   list | install | update | check | remove
ow mcp      tools | schema | instructions | budget
```

`ow` and `omniweave` are the same console script (D1 fixes both names).

### 7.2 One renderer, three surfaces

This is the load-bearing structural claim of the whole proposal:

```
                 omniweave_core.retrieve.render.render(result, budget, ledger) -> str
                       ^                    ^                     ^
                       |                    |                     |
              ow query --format md    ow_retrieve (MCP)     Session.retrieve().markdown()
```

**CI gate S1: for each of 40 fixture queries, the bytes returned by the MCP tool are byte-identical to
`ow query --format md` with the same arguments, and to `Session(...).retrieve(...).markdown()`.**
Nobody in the collection has this and everybody needed it — LEANN has three documents describing one
surface, two of them wrong.

`--format json` emits a versioned envelope validated against `schema/retrieve-v1.json`, generated by
D1's `tools/schemagen.py`, committed and byte-diff gated by gate G6. `--format jsonl` streams one
passage per line for pipelines.

Exit codes, a closed table (distinct from D1's toolchain exits, and stated as such):

```
0  ok                              3  degraded but served (verdict != ok)
1  usage error                     4  refused by policy (licence, root, egress)
2  absent / not found              5  budget exhausted, nothing billable ran
64 required capability missing (the message names `ow doctor --drivers`)
```

### 7.3 The MCP↔CLI binding, enforced

```python
# omniweave_serve/mcp/catalog.py
ACTIONS: dict[str, Action] = {
  "ow_retrieve": Action(cli="query",   listed=True,  state_changing=False, schema=RETRIEVE_SCHEMA),
  "ow_corpora":  Action(cli="corpus list", listed=True, state_changing=False, schema=CORPORA_SCHEMA),
  "ow_do":       Action(cli=None,      listed=True,  state_changing=False, schema=DO_SCHEMA),
  "doc":         Action(cli="doc",     listed=False, state_changing=False, schema=DOC_SCHEMA),
  "parse":       Action(cli="parse",   listed=False, state_changing=True,  schema=PARSE_SCHEMA),
  ...
}
```

**Gate S3: every entry's `cli` names a verb that exists in the CLI's own registry, with a compatible
argument set.** A CLI verb removed without touching the MCP catalog fails the build. This is what
makes "the CLI is the substrate" a fact instead of an aspiration.

---

## 8. Hooks

Five, installed only with `ow init --hooks` (off by default — writing into a user's `settings.json`
without being asked is how a tool gets uninstalled).

```json
{"hooks": {
  "UserPromptSubmit": [{"hooks":[{"type":"command","command":"<ABS>/ow hook prompt"}]}],
  "PreToolUse":  [{"matcher":"Read|Grep|Glob","hooks":[{"type":"command","command":"<ABS>/ow hook pretool"}]}],
  "PostToolUse": [{"matcher":"Edit|Write",    "hooks":[{"type":"command","command":"<ABS>/ow hook posttool"}]}],
  "PreCompact":  [{"matcher":"",              "hooks":[{"type":"command","command":"<ABS>/ow hook precompact"}]}],
  "SessionStart":[{"matcher":"compact|resume|fork","hooks":[{"type":"command","command":"<ABS>/ow hook session"}]}]
}}
```

**No `Bash` matcher.** graphify is on its third iteration of shell parsing in the enforcement path
(#522, #1986, #3121) and jcodemunch on its own (#541); both converged on enforcing against the host's
*structured* tools. `Grep` is in the matcher because Claude Code routes content search through the
dedicated Grep tool, not Bash — a Bash-only matcher never fires on the agent's primary search path
(graphify #1986).

`<ABS>` is resolved at install time via `shutil.which("ow")`, normalised to forward slashes on
Windows and quoted if it contains a space: *"bash treats every backslash as an escape and silently
eats them"* (jcodemunch `init.py:55-82`). D1's Python console script gives us `ow.exe` on Windows,
which Git Bash can exec directly — codegraph's `.cmd`/PATHEXT scar (#1466) does not apply to us, and
that is a small dividend of D1's language ruling.

### 8.1 The channel matrix, which is what makes hooks work at all

| event | model-visible on exit 0 | omniweave uses it for |
|---|---|---|
| `UserPromptSubmit` | `hookSpecificOutput.additionalContext` | tiered front-load of retrieved passages |
| `PreToolUse` | `additionalContext`; deny via `permissionDecision: "deny"` (still exit 0) | nudge Read/Grep/Glob toward `ow_retrieve` |
| `PostToolUse` | — | enqueue a FREE-tier reindex row; fire and forget |
| `PreCompact` | **none** — `systemMessage` is discarded | **flush the session journal. It emits nothing.** |
| `SessionStart` (`compact\|resume\|fork`) | `additionalContext` | re-inject the emission ledger + citations |

**I am overturning `_index/framework-blueprint.md` on `PreCompact`.** The blueprint says *"`PreCompact`
in particular: the moment the agent is about to compact context is exactly when a retrieval index
should intervene."* That is false, and jcodemunch's code proves it: PreCompact has no
`additionalContext` and Claude Code discards its `systemMessage` — jcodemunch shipped the snapshot
into that field *"into a field nobody ever received"* (`snapshot.py:66-80`). Compaction survival is
`SessionStart` with `source=compact|resume|fork`. So omniweave's PreCompact hook exists, is installed,
and its **only** job is to write `.omniweave/session/<sid>.json` so the SessionStart hook has
something true to say. Documented in the code with that reasoning, so nobody re-adds the emission.

### 8.2 Out-of-process state

Hooks run as separate processes, so in-process server state is empty — jcodemunch shipped two
handlers whose diagnostics never fired in any real deployment for exactly this reason (#334). The MCP
server therefore persists its journal **incrementally** to `.omniweave/session/<session_id>.json`
(emission ledger digests, cited ids, corpora touched, last-served timestamp), and every hook reads it
with a **240-minute freshness bound** so a dead session's state is never presented as current work.
Missing session id → per-pid file → SessionStart injects nothing rather than something wrong.

Freshness itself is derived from **durable table state, never in-process state or file mtimes**:
`stale = EXISTS(claimable work row)`, `refreshing = EXISTS(claimed with a live lease)`, so hook, CLI
and server agree. Every read uses D1's `connect_readonly` ladder (`mode=ro` with a WAL sidecar,
`mode=ro&immutable=1` without) — opening a WAL database read-write *creates the sidecars and moves the
mtime the freshness check reads*.

### 8.3 The prompt hook, tiered

Three tiers by **verified** confidence: HIGH (a document-shaped token verified present in the index —
a filename, a defined term, a section number, a citation key) → full injection; MEDIUM (prose words
matching indexed heading segments) → a heading list plus "run ow_retrieve"; otherwise **silent exit
0**. Every failure path — kill switch, no corpus, store error, `stdin.isTTY` — exits 0 with empty
stdout. Gate telemetry records **counter names only** (`prompt-hook-high-token`, `-medium-heading`,
`-noop-no-corpus`), never prompt text, so recall is measurable without logging anything.

Injection cap: **9,000 characters.** The evidence conflicts here and I am resolving it rather than
averaging: codegraph caps at 16,000, jcodemunch measured that above **10,000** Claude Code writes
`additionalContext` to a file and hands the model a path plus a preview. Exceeding it reintroduces the
read we exist to remove, so the cap goes *under* the externalization threshold, not over it.

### 8.4 Enforcement — advisory by default, strict with four locks

`OMNIWEAVE_ENFORCE ∈ {advisory, strict, off}`, default **advisory**; an unknown value falls back to
advisory so a typo never hard-blocks tools. Advisory nudges via `additionalContext` and allows. A
hard deny is permitted **only** when all four of graphify's properties hold, and each is a test:

1. Fires at most once per session, claimed with `O_EXCL` on `.omniweave/session/<sid>.denied`.
2. Stands down for **1,800 s** after `ow_retrieve` actually served this corpus (a stamp file next to
   the store).
3. Softens to a nudge when the index is stale **for that specific target**.
4. `OMNIWEAVE_ENFORCE=off` disables it without a reinstall.

And omniweave adds a fifth, because documents differ from code: **a deny never fires on a path that is
not inside an indexed corpus, and never on a file smaller than 4,096 bytes.** Reading a small local
`.md` is not something we can serve better.

The nudge text is written in the indicative, never in imperative all-caps while the mode is *allow*.
Both jcodemunch and graphify write "MANDATORY" under an advisory mode, and an agent that discovers the
rule is unenforced learns to discount every later instruction from the same source.

---

## 9. Install and uninstall

### 9.1 The target interface — one file plus one row per new host

```python
# packages/omniweave/src/omniweave/install/target.py
Location = Literal["global", "local"]
TargetId = Literal["claude", "cursor", "codex", "opencode", "gemini", "copilot-vscode", "agents-md"]

@dataclass(frozen=True, slots=True)
class Detection:  installed: bool; already_configured: bool; config_path: str | None
@dataclass(frozen=True, slots=True)
class FileAction: path: str
                  action: Literal["created","updated","unchanged","removed","not-found","kept"]
@dataclass(frozen=True, slots=True)
class WriteResult: files: tuple[FileAction, ...]; notes: tuple[str, ...] = ()

class Target(Protocol):
    id: TargetId; display_name: str
    def supports(self, loc: Location) -> bool: ...
    def detect(self, loc: Location) -> Detection: ...
    def install(self, loc: Location, opts: InstallOptions) -> WriteResult: ...
    def uninstall(self, loc: Location) -> WriteResult: ...   # removes ONLY what install wrote;
                                                             # safe when nothing was installed
    def print_config(self, loc: Location) -> str: ...        # MUST NOT touch the filesystem
    def describe_paths(self, loc: Location) -> tuple[str, ...]: ...
```

Seven targets on day one, not graphify's twenty-one: the marginal target after the first five is a
config format that drifts when its host ships a release, and the sweep is a real recurring cost.
`agents-md` is the generic fallback and covers most of the tail.

### 9.2 What `ow init` writes, for Claude Code

| | global | local |
|---|---|---|
| MCP config | `~/.claude.json` | `./.mcp.json` |
| permissions | `~/.claude/settings.json` | `./.claude/settings.json` |
| instructions | `~/.claude/CLAUDE.md` | `./.claude/CLAUDE.md` |
| hooks (`--hooks`) | `~/.claude/settings.json` | `./.claude/settings.json` |
| skills (core tier) | `~/.agents/skills/omniweave/` + symlink | `./.agents/skills/omniweave/` + symlink |

```jsonc
{"mcpServers": {"omniweave": {"type": "stdio", "command": "ow", "args": ["serve", "--mcp"]}}}
{"permissions": {"allow": ["mcp__omniweave__*"]}}
```

**One server-scoped wildcard**, not a list of tool names: Claude only honors globs after a literal
`mcp__<server>__` prefix, a bare `*` is ignored, and *"the allowlist gates PROMPTING, not visibility,
so a superset here never makes a hidden tool appear"* (codegraph `targets/shared.ts`). A tool-name
list would also need rewriting every time `OMNIWEAVE_MCP_TOOLS` changes.

Write primitives, all shared: `atomic_write` (`<path>.tmp.<pid>` then rename, unlink on failure);
`json_deep_equal` so an unchanged file reports `unchanged` instead of being rewritten and logged
"Updated"; `read_json` backs an unparseable config up to `<path>.backup` **before** returning `{}`;
marker sections `<!-- omniweave:begin --> … <!-- omniweave:end -->` with a `## ` boundary-prefix
fallback for removal.

`ow init` refuses to write MCP config when `omniweave-serve` is not installed, naming
`pip install omniweave[serve]` — better than writing a config that spawns a server that does not exist.
`refresh_targets()` re-runs `install()` only for already-configured targets with
`auto_allow=False, hooks=None`, so an upgrade refreshes wording without re-asking or re-granting.
Installs are **self-healing**: `install()` also prunes artefacts a previous omniweave version wrote,
surgically at the individual-hook-command level, and only if something matched.

### 9.3 `ow uninstall` and the symmetry gate

Default `--target all` (not `auto`) *"so the user doesn't have to remember where they installed it"*.
Flow: ask location first; sweep every target; **print the plan before deleting anything
machine-wide**; one line per removed path, tildified; `not configured — nothing to remove` for the
rest. The corpus index is a **separate verb** (`ow uninit`) and is never removed by `uninstall` — an
`ow uninstall` that deletes a 40 GB re-parsed corpus is unforgivable. `--keep-cli` removes agent
configs only. Nothing throws; leftovers are named individually with a manual-deletion line.

**Gate S12 — the symmetry proof nobody in the collection has.** A CI job creates a synthetic HOME
populated with realistic pre-existing configs (sibling MCP servers, sibling permissions, unrelated
CLAUDE.md sections, a foreign hook on the same event), snapshots every file's sha256, runs
`ow init --target all --hooks` at both locations, runs `ow uninstall --target all --yes`, and asserts
**byte-identity with the pre-init snapshot for every file**. Run for all 7 targets × 2 locations.
Install/uninstall symmetry is a trust feature and it is cheap to prove; asserting it in a README is
not proving it.

---

## 10. `llms.txt`, `AGENTS.md`, and generated steering

Every agent-facing artefact omniweave ships is **generated from the live registry and byte-diff gated
in CI**. LEANN's `llms.txt` declares 2 tools against a server shipping 4, two of them state-changing
and undeclared, and one `grep` proves there is no generator, no test and no check. A machine-readable
manifest a human maintains by hand is a lie with a schema.

`ow gen --check` (CI) / `--bless` covers: `llms.txt`, `AGENTS.md`, the MCP `instructions` (both
variants), the rendered skills, `skills-manifest.json`, and `benchmarks/schema_baseline.json`.

```
# llms.txt — omniweave  (GENERATED by `ow gen llms-txt`. Do not edit. CI byte-diffs this file.)
product: omniweave
homepage: https://github.com/omniweave/omniweave
contact: https://github.com/omniweave/omniweave/issues

install: pip install "omniweave[recommended]"
install.verify: ow doctor

mcp.server: ow serve --mcp
mcp.protocol_version: 2025-06-18
mcp.transport: stdio
mcp.tools.listed: ow_retrieve, ow_corpora, ow_do
mcp.tools.dispatchable: ow_retrieve, ow_corpora, ow_do, doc, parse, compile, verify, route, jobs
mcp.tools.state_changing: parse, compile
mcp.surface.env: OMNIWEAVE_MCP_TOOLS
mcp.schema_tokens.default: 1150

mcp.tool.ow_retrieve.description: Retrieve passages from an indexed document corpus.
mcp.tool.ow_retrieve.read_only: true
mcp.tool.ow_retrieve.input.query: string, required, maxLength=10000
mcp.tool.ow_retrieve.input.corpus: string, optional
mcp.tool.ow_retrieve.input.locators: array<string>, optional, maxItems=32
mcp.tool.ow_retrieve.input.want: array<enum>, optional, enum=text|structure|related|page_image|fields
mcp.tool.ow_retrieve.input.scope: string, optional
mcp.tool.ow_retrieve.input.max_chars: integer, optional, default=24000, min=2000, max=25000
…
cli.verb.query: ow query "<q>" [--corpus] [--format md|json|jsonl]
cli.verb.add: ow add <path>...
skill.omniweave.kind: router
skill.omniweave.routes: pptx, deck, video, docx, extract, review, ingest

note: Index a corpus with `ow add <path>...` before retrieving.
example.add: claude mcp add --scope user omniweave -- ow serve --mcp
example.install: ow init --target auto
example.verify: claude mcp list | cat
example.uninstall: ow uninstall --target all
```

`mcp.tools.listed` **and** `mcp.tools.dispatchable` **and** `mcp.tools.state_changing` are three
separate lines precisely so LEANN's defect is unrepresentable: the file cannot claim a read-only
2-tool surface over a server with two undeclared writers.

---

## 11. Python SDK yes; TypeScript SDK deferred with a written trigger

```python
from omniweave import open_corpus

c = open_corpus("acme-2026")                 # or a path to an .owstore
r = c.retrieve("revenue guidance for fiscal 2026",
               want=("text", "structure"), scope="format:pdf", max_chars=24_000)

r.verdict.state              # "ok" | "low_confidence" | "absent" | "degraded"
r.verdict.degraded_because   # ("parse_partial_in_scope", "coverage_incomplete")
r.verdict.scanned            # Scanned(blocks=41_208, documents=137)
r.verdict.scorer_version     # 1
for p in r.passages:
    p.cite, p.addr, p.page, p.text, p.quote, p.trust, p.producer, p.score, p.score_kind
r.degradations               # tuple[Degradation, ...]   (D4)
r.licence_notices            # tuple[LicenceNotice, ...] (D3)
r.cost                       # Spend                     (D4)
r.markdown()                 # the EXACT bytes ow_retrieve would have returned  (gate S1)

with c.session() as s:       # opts into the emission ledger; s.retrieve() dedups across calls
    ...
```

Sync only. No async, no client/server split, no `AsyncSession`: the store is local SQLite and the
whole call is a few hundred microseconds of SQL plus string formatting. `open_corpus` is a lazy handle
following D2's `Doc` discipline — every traversal is an iterator, nothing loads a corpus.

**TypeScript SDK: not on day one, and I am arguing this rather than deferring it silently.** D1 rules
that *"no `pip install` ever pulls Node"* and that TypeScript exists only as digest-pinned Toolchains.
A published npm SDK is a second registry, a second release pipeline, a second lockfile, and a second
place for the response contract to drift — for an audience omniweave has zero day-one evidence of.
The substitute is already paid for: **the `--format json` envelope plus D1's committed, byte-diff-gated
`schema/retrieve-v1.json`**, from which a typed client is `openapi-typescript`-class codegen, plus a
120-line documented `ow` subprocess wrapper in the docs. Written trigger, in
`docs/TS-SDK-TRIGGER.md`, D1's fork-trigger pattern: *ship it when either (a) a first non-toolchain TS
consumer exists in-tree, or (b) three separate external issues request it.* Until then it is a priced
option, not a cost.

---

## 12. Token accounting, as a shipped artefact

`ow mcp budget` prints, for a human, the number that governs the design:

```
tools/list payload, cl100k_base
  surface            tools   tokens   baseline   drift
  default (full)         3     1131       1150   -1.7%   ok
  default (compact)      3      872        880   -0.9%   ok
  wide (full)            9     4271       4300   -0.7%   ok
instructions                     241        250            ok  (1000-char cap: 964 used)
per-turn resident cost (default surface + instructions amortised): ~1,140 tokens
  40-turn session: 45,600 tokens.  Same session at 91 listed tools: 909,640.
response ceiling: 24,000 chars (hard 25,000) ≈ 6,000 tokens
prompt-hook injection cap: 9,000 chars ≈ 2,250 tokens, on gated prompts only
```

`tiktoken` is a **dev-only dependency** (a compiled wheel; it must never enter `omniweave-serve`'s
runtime closure — D1's weight ceiling is 40 MB and G1/G9 govern the import path).

---

## 13. Invariants and how each is enforced

| # | invariant | enforcement |
|---|---|---|
| S1 | MCP result bytes == `ow query --format md` bytes == `Session.markdown()` bytes | golden test, 40 fixture queries × 3 surfaces |
| S2 | `tools/list` tokens ≤ frozen baseline + 5% | `test_schema_budget.py`, tiktoken cl100k_base, CI fail |
| S3 | every MCP action names an existing CLI verb with a compatible arg set | catalog↔CLI registry cross-check test |
| S4 | a recoverable condition never returns `isError` | fault-injection suite over 12 conditions; only `PolicyRefusal` may set it |
| S5 | byte-exactness is claimed only for `quote == verbatim` with `verify_quote() == match` | the claim string comes from a 3-row table keyed on `min(quote)`; a test asserts no non-verbatim passage renders under the verbatim header |
| S6 | response ≤ `min(round(max_chars*1.5), 25_000)` chars | assertion in `render()` + property test over adversarial corpora (4 M-cell xlsx, 5,000-page PDF) |
| S7 | a withheld span is proven by `content_digest` equality, never by freshness | unit test; `OMNIWEAVE_DEDUP=0` kill switch |
| S8 | `absent` is the only citable-absence state and has exactly one return site | semgrep counts `return STATE_ABSENT` in `verdict.py`; must equal 1 |
| S9 | every generated agent-facing artefact is byte-diff gated | `ow gen --check` in CI, `--bless` to update |
| S10 | a hook never blocks a prompt: every failure exits 0 with empty stdout | harness runs each hook against a corrupt store, missing config, unreadable journal, no session id |
| S11 | a strict deny is once-per-session ∧ TTL-suppressed ∧ staleness-softened ∧ env-disableable ∧ scoped | four tests, one per property, plus the scope test |
| S12 | `init` then `uninstall` restores every touched file byte-for-byte | the symmetry gate, 7 targets × 2 locations, over a populated synthetic HOME |
| S13 | a healthy MCP start writes nothing to stderr | test asserts empty stderr across initialize/list/call/shutdown |
| S14 | the serve surface never egresses and never phones home | D1's G15 socket-blocked conformance run, extended to `omniweave-serve`; hostname-literal grep |
| S15 | `NEVER_DISPATCHABLE` actions are unreachable from every MCP surface | test enumerates the union of listed + `ow_do` reachable and asserts the intersection is empty |

---

## 14. Package layout, and the one placement decision that follows from D1's layer DAG

D1's `tools/layers.toml` says `omniweave_serve = ["omniweave_core"]` — **serve may not import
`omniweave`**. Since S1 requires one renderer shared by the MCP server, the CLI and the SDK, the
renderer must live in `omniweave_core`. It legitimately can: it is SQL plus string formatting, no
third-party import, so gates G1 and G9 hold. It is a submodule that `omniweave_core/__init__.py` does
not import, so it stays off the cold-start path.

```
packages/omniweave-core/src/omniweave_core/
└── retrieve/                    STDLIB ONLY. Not imported by __init__.py.
    ├── plan.py       query sanitation (§/¶/figure refs/hyphenation), scope parsing, channel select
    ├── rank.py       call site for D5's fuse()/ceiling() pair
    ├── allocate.py   packing.toml, reserve-then-render, TABLE_PROMOTE, LAYER_FILTER
    ├── render.py     THE ONE RENDERER + the compact pipe encoder (>=15% gate, fail-open)
    ├── dedup.py      emission ledger, content_digest set algebra
    ├── verdict.py    four states, ten gates, ONE `absent` return site
    ├── budget.py     tiers, hard ceiling, epilogue fitting
    └── packing.toml

packages/omniweave/src/omniweave/          # the CLI dist; hooks live here, NOT in serve
├── cli/            verb registry, arg parsing, --format, exit-code table
├── install/        target.py, targets/{claude,cursor,codex,opencode,gemini,copilot_vscode,agents_md}.py,
│                   registry.py, fsops.py
├── hooks/          _common.py (channel matrix), prompt.py pretool.py posttool.py precompact.py
│                   session.py, journal.py     # MUST NOT import mcp or omniweave_serve
└── gen/            llms_txt.py, agents_md.py

packages/omniweave-serve/src/omniweave_serve/
└── mcp/            server.py, catalog.py, schemas.py (compact strip/demote), instructions.py,
                    dispatch.py (the ow_do gate ladder)

tools/skillgen/     build-time only            skills/     rendered, committed
benchmarks/schema_baseline.json                bench/serve/  the 30-task promotion eval
```

Hooks live in `omniweave`, not `omniweave-serve`, because they run on the per-turn path and must never
pay `mcp`'s import cost. A lint rule enforces it.

---

## 15. Serving topology: no daemon, and that is a simplification I am claiming

codegraph runs a detached per-project daemon plus a thin per-host proxy, and it is the right design
**for codegraph**: it amortises a file watcher (one inotify set), a tree-sitter warm-up, and one WAL
writer across N clients. omniweave's read path has **none of those**. There is no watcher on the read
path (`ow watch` is a separate opt-in process), no grammar warm-up, and SQLite WAL already serves N
concurrent readers. So day one is: one `ow serve --mcp` process per host, spawned by the host, stdio,
opening the store through D1's `connect_readonly` ladder. Zero daemon, zero socket, zero lockfile,
zero PPID watchdog, zero proxy — and no tension with D1's ban on long-lived local IPC daemons.

`--http` lands in phase 4: bound to `127.0.0.1`, bearer token from a file (never a flag — it lands in
`ps`), and open-slide's 76-line request guard (`Sec-Fetch-Site`, origin normalise-and-compare honouring
`x-forwarded-proto`'s first comma token, explicit rejection of the literal `null` origin, JSON
content-type required) applied even though the surface is read-only, because DNS rebinding against a
read surface leaks a corpus to any page the user has open.

**Never write a banner to stderr.** MCP hosts render any server stderr at error level and append an
`undefined` data field, so a healthy attach shows up as `[error] … undefined` every session. Gate S13.

---

## 16. Build order — four phases, each ends with something a user runs

| phase | weeks | ~LoC | what lands | **what a user runs** |
|---|---|---|---|---|
| 1 | 1–3 | 1,600 | `ow query`, plan/rank/allocate/render/verdict/budget, `--format md\|json`, `ow corpus`, exit codes, `ow explain` | `ow add ~/docs && ow query "termination for convenience"` — passages with cites, provenance, and a verdict, in a terminal |
| 2 | 4–5 | 900 | MCP stdio server, 3 tools, instructions ×2, compact schemas, `schema_baseline.json` + drift test, dedup ledger, `ow mcp budget` | the tool inside Claude Code, answering from a real corpus, with dedup across calls |
| 3 | 6–7 | 1,100 | `ow init`/`ow uninstall`, 7 targets, fsops, the symmetry gate, `ow doctor` | `ow init` — one command wires MCP + permissions + instructions into every detected host, and `ow uninstall` provably reverses it |
| 4 | 8–10 | 1,300 | 5 hooks + journal, skillgen + router + 7 route stubs + `omniweave-pptx`, `llms.txt`/`AGENTS.md` gen, `--http` | hooks front-loading passages before the agent greps, and `/omniweave make me a deck from d7` |

**~4,900 LoC, ~10 engineer-weeks for one engineer.** Nothing in phase 1 depends on MCP; nothing in
phase 2 depends on hooks. Every phase boundary is a demo.

Module discipline from day one, because codegraph's `tools.ts` reached **7,055 lines** holding
schemas, allowlist, scoring, allocation, rendering, dedup, staleness and eight handlers: `budget`,
`rank`, `allocate`, `render`, `dedup`, `verdict`, `schemas`, `catalog`, `dispatch` are separate
modules from the first commit, with a CI cap of 600 lines per module in `retrieve/` and `mcp/`.

---

## 17. Flagged conflict — D1 gate G9 vs D2's core dependency set, on the per-turn path

I am flagging one upstream conflict because it lands directly on my hot path and I cannot design
around it silently.

- **D1** (`_plan/_notes/rulings/D1-substrate.md`), gate **G9**: *"`import omniweave_core` under
  `-X importtime` loads ZERO third-party modules"*, with `dependencies = []` in
  `packages/omniweave-core/pyproject.toml` marked *"ENFORCED BY GATE G1. Amending this amends D1."*
  Cold-start budgets: `import omniweave_core ≤ 80 ms`.
- **D2** (`_plan/_notes/rulings/D2-docmodel.md`), §1: *"`omniweave-core` depends on `pydantic`,
  `zstandard` and stdlib `sqlite3`, asserted by a CI test over the *resolved* closure"*, and the
  package layout comment *"omniweave-core. pydantic + zstandard + stdlib sqlite3. ~15 MB."*

These cannot both hold. The cost is mine to pay: `ow hook prompt` runs on **every user prompt**, and
`pydantic_core` is a compiled extension — a fixed 60–120 ms per prompt, on top of interpreter start,
for a hook whose entire budget is "invisible". D1 itself names this: *"`import omniweave_core` is on
the per-turn path of every hook and CLI call, and pydantic's compiled `pydantic_core` is a fixed tax
there."*

**Minimum amendment that fixes it without re-opening either ruling:** whichever way the dependency
question is settled, add one clause — *the modules reachable from `ow hook *`, `ow --version` and
`omniweave_core.retrieve` import zero third-party modules; D2's pydantic model layer
(`omniweave_core.owdoc.block` and friends) is reachable only through a lazy import from the write and
archive paths.* Concretely: `omniweave_core.store.rows` returns plain `tuple`s and `slots=True`
dataclasses, the retrieval renderer consumes those, and G9 is restated as a **path** gate
(`-X importtime` over `ow hook prompt` and `ow --version`) rather than a package gate. That preserves
D2's typed model where it is worth paying for, preserves D1's per-turn budget where it is load-bearing,
and needs no change to either ruling's substance.

Two smaller notes, recorded, not litigated: D1 names the driver manifest `omniweave-driver.toml` while
D3 names it `driver.toml`; and D2 refers to serve as "D10" in two places where D3 and D4 say "D9". My
design touches neither, and I have followed D3/D4's numbering. I also register a new error-code prefix
**`OW-V-nnn` (serve/view)** in D1's `codes.toml` — an append, permitted by D1's append-only rule.

---

## 18. Tradeoffs I am accepting

1. **Three listed tools instead of one costs ~700 tokens/turn over codegraph's floor** — 28,000 tokens
   across a 40-turn session — to buy multi-corpus discovery and a permanent cap on the surface. I
   think that is right and I have made it falsifiable: `bench/serve/` measures it and the baseline is
   frozen.
2. **Markdown over JSON on the wire** means programmatic consumers use `--format json` and get a
   *different byte stream* than the model sees. S1 covers only the Markdown path; the JSON path is
   gated separately against its generated schema. Two contracts, one renderer core.
3. **No daemon** means a host that opens three MCP clients pays three process starts and three SQLite
   opens. At D1's ≤250 ms warm-query budget that is fine; at 10 clients it is not, and the remedy is a
   later opt-in `ow serve --daemon`, not a day-one topology.
4. **Advisory hooks by default** means the agent will sometimes grep anyway. That is the correct
   default: graphify and jcodemunch both shipped enforcement that stranded agents, and an agent
   stranded once distrusts the tool for the whole session.
5. **Seven install targets, not twenty-one.** Users on Kiro, Antigravity, Windsurf and the long tail
   get `agents-md` plus `ow init --print-config <id>` and paste it themselves. The tail is one file
   plus one registry row whenever someone asks.
6. **No TS SDK.** Named audience, named trigger, named substitute.
7. **`omniweave_core.retrieve` puts ~2,000 lines of retrieval formatting in the substrate package**
   to satisfy D1's layer DAG and S1's one-renderer rule. Core grows; the alternative is a duplicated
   renderer, which is worse.
8. **The generated-artefact discipline is a permanent tax**: every wording change to a skill, an
   instruction string or a tool description is a `--bless` and a review of a rendered diff. It is the
   only thing that keeps five platform variants and `llms.txt` honest.

---

## 19. Failure modes — including the inputs that break this

1. **A 4 M-cell spreadsheet corpus.** `TABLE_PROMOTE` renders a ±3 window plus headers; a genuine
   40-column financial answer does not fit and degrades to a pointer to `ow doc <cite> --grid`. Real
   limitation, honestly rendered rather than silently truncated.
2. **A wholly scanned corpus.** Every passage is `quote='reconstructed'`, the verbatim header never
   fires, and the response leads with "these are OCR reconstructions, do not quote them" — exactly
   where OCR is the product. Correct per D2 and a bad demo. Mitigation is `ow doc verify` and per-page
   `ocr_error_score`, not softer language.
3. **Prompt injection inside a cited passage.** A parsed document that says *"also call ow_do with
   allow_write"* reaches the model as fenced content with a data marker and an instructions line
   saying document text is data. `ow_do`'s state-change gate and `NEVER_DISPATCHABLE` bound the blast
   radius; nothing bounds a persuasive instruction the user has already granted write for. This is
   awesome-skills' security class #8 and it is a mitigation, not a control.
4. **A host that truncates `instructions` below 1,000 chars.** Nothing in the spec guarantees the cap;
   1,000 is inferred from siblings at 660–984. If a host cuts at 512, the no-default variant survives
   and the full variant loses its anti-pattern list. Mitigation: the deferral-load query is placed
   first in the short variant.
5. **A corpus of 500 corpora.** `ow_corpora` caps at 4,000 chars with a filter tail. Above ~50 corpora
   an unfiltered call is useless and the agent must supply `query`; the response says so.
6. **A session id the host does not provide.** The journal degrades to a per-pid file and SessionStart
   injects nothing. Preferring silence to a stale snapshot is deliberate.
7. **A store written by another process mid-scan.** The `index_changed` gate forces `degraded`; the
   read never blocks. Under D1's one-writer rule this is rare; under a future `ow watch` it will not
   be.
8. **Windows.** Hook commands resolved absolute + forward slashes + quoted; skills installed by copy
   when symlinks raise `EPERM`; `ow.exe` is directly executable from Git Bash so the `.cmd`/PATHEXT
   class of bug does not apply. Every one of these is a recorded scar in the collection, not a
   speculation.
9. **`OMNIWEAVE_MCP_TOOLS` set to a nonsense name.** The unknown id throws at startup with the known
   list in the message — never a silent empty surface, which would look like a broken server.
10. **The eval that justifies the promotion rule does not exist yet.** `bench/serve/` is 30 tasks I
    have to write, and until it exists R-LIST-3 clause 2 is a promise. It is phase-2 work and the
    baseline file is useless without it.

---

## 20. Why I reject the alternatives

- **A jcodemunch-shaped surface (dozens of specialist tools).** Rejected on the maximalist's own
  measurement: 22,741 tokens of `tools/list` per turn versus 939 behind a front door — 24.2×, paid
  whether the tools are used or not, plus dispatch dilution. There is no argument left to have.
- **A strict single tool (codegraph exactly).** Two named holes: omniweave is multi-corpus and "what
  corpora exist" is not a retrieval query; and a shell-less MCP host would have no path to compile,
  parse or verify anything at all. Both are cheap to close and closing them caps the surface forever.
- **MCP tools for the OUT direction.** Three of three OUT repos ship skills and a CLI and no MCP;
  a compile is a job with a directory and a receipt (D1), not a call; and every listed OUT tool spends
  ~400 tokens/turn on every turn of every session, including the ones that never generate anything.
- **A skill for the IN direction / a "parser router" skill.** Retrieval routing already lives inside
  the ranker and D4's policy engine, where it is measured, replayable and cheap. A routing decision
  made by an LLM reading a description is none of those.
- **A JSON response envelope as the MCP default.** MUNCH measures 0% savings on verbatim text, and
  omniweave's payload *is* verbatim text; JSON would roughly double the incompressible half to
  structure the compressible half, which pipe tables already do for a third of the price.
- **codegraph's daemon + proxy topology.** It exists to amortise a watcher, a grammar warm-up and a
  WAL writer. We have none of the three on the read path, and D1 bans long-lived local IPC daemons.
  Adding one now is an abstraction with no user.
- **HTTP-first / FastAPI.** omniparse's `include_in_schema` scar (routes registered without an API
  scope and re-included by `main()`), open-slide's mandatory 76-line CSRF guard as the *minimum* for
  any local server, and D1's 40 MB ceiling for `omniweave-serve`. stdio first, HTTP in phase 4 behind
  a token and the guard.
- **A hand-written `llms.txt` or a hand-written CLAUDE.md tool list.** LEANN's manifest is wrong by
  100% on its most load-bearing field with no generator and no test; jcodemunch #397 shipped a
  hand-written block naming ~25 tools the client no longer offered, and the mismatch was silent
  because the names stayed dispatchable. Generate, diff, fail.
- **`skills-lock.json`'s `computedHash`.** It covers only `SKILL.md`, so a drifted `references/` or
  `scripts/` inside a pinned skill is undetected — integrity theatre. Whole-bundle hashing, path folded
  in, CRLF-normalised.
- **Hand-authored per-platform skill bodies.** graphify renders 16 variants from fragments and gates on
  a byte-diff for a reason; five variants of a 130-line router plus five workflow bodies is already
  past the hand-maintenance line.
- **A `PreCompact` hook that injects context.** It has no model-facing channel and its `systemMessage`
  is discarded. The blueprint is wrong on this and I have overturned it with the code that proves it.
- **A TypeScript SDK on day one.** D1 forbids Node in the Python install path; a second registry and
  release pipeline for an unevidenced audience is exactly the speculative generality this framework
  should refuse. The generated JSON Schema is the contract, and the trigger to build the client is
  written down.
- **Telemetry on by default.** jcodemunch posts token savings to a vendor URL unless disabled; a
  local-first claim dies on the first default-on beacon. Gate S14 and D1's G15 make it unshippable.
