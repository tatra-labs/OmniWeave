# 00 — Vision, Scope and Success Criteria

**In one paragraph.** omniweave turns a folder of real documents into one queryable, citable corpus
and compiles new artefacts back out of it without losing the thread to the source. It exists because
every stack that currently sits between unstructured data and a language model destroys the same five
things at the same seam — spatial provenance, section containment, table semantics, per-Block
confidence, and any path from a generated artefact back to the bytes it came from — and destroys them
silently, so the caller learns what was forfeited only when an answer turns out to be wrong. omniweave
puts one document model (`owdoc`) in the middle, makes parsers replaceable Drivers that populate it,
makes indexes and `owgraph` views over it, makes PPTX/DOCX/decks compilers out of it, and makes a
generated artefact re-enter the corpus through the same `parse/1` pipe a source document does. This
document fixes what omniweave is, what is in and out of scope at each release, who it is for, the
fourteen things it refuses to be, why it is worth adopting over the alternatives that actually exist,
and the numbered tests that decide whether it worked.

This document is subordinate to [`_notes/charter.md`](_notes/charter.md), which is binding, and to
[`_notes/terminology.md`](_notes/terminology.md), which fixes every name used here. Where the charter
speaks, this document expands rather than re-decides; where it is silent, a new decision is marked
**Extends the charter** and carries its own closing measurement.

## 1. The problem, stated as a mechanism

The complaint "LLMs are bad at PDFs" is not the problem. The problem is a specific, locatable,
repeated act of destruction: **the parse step of nearly every stack in production converts a
structured intermediate into a string, and the string is what travels downstream.** The intermediate
existed. Somebody's code held a polygon, a page number, a cell coordinate and an OCR confidence, and
then a `to_markdown()` call threw all four away in one line. Everything an agent later cannot do is a
consequence of that line, and every workaround — re-reading the file, grepping for the quote,
"according to the document" without a page number — is a symptom of it.

Measured across the twenty-two repositories in `_index/` (`_index/README.md`, not published): **only four of eleven
parsing repositories expose anything beyond a markdown string**
(`_index/comparisons.md` (`_index/comparisons.md`, not published), "Representation fidelity"). The other seven are
not badly written; they are correctly written for a purpose that stops one layer short of what an
agent needs. markitdown's entire return type is a string and an optional title
(`markitdown/packages/markitdown/src/markitdown/_base_converter.py:5-25`: `DocumentConverterResult.__init__`
takes `markdown` and an optional `title`, assigns exactly those two attributes, and adds nothing else).
There is no page, no polygon, no per-paragraph anything, and nothing in the type tells a caller that a
page number was available and dropped.

### 1.1 The five losses, named

| # | Loss | The mechanism that causes it | What the agent cannot then do | omniweave's answer |
|---|---|---|---|---|
| **L-1** | **Spatial provenance** | The polygon and page live inside the parser's page object and are not fields of the serialized output. Recovery requires re-parsing. | Verify a quote; show a human *where*; highlight; prove a citation is not fabricated. | `Locus` carries `cite`, `doc_ord`, `gen`, `page`, `addr`, a `TextSpan`, a `quad` that may be `None` **only** with a non-`None` `reason`, the `OriginSpan`, and a `precision ∈ {char, line, block, page, none}` so the answer says *how tight* the box is instead of implying char precision from a block rectangle. `Quad.from_driver` is the only public constructor and normalizes once, at ingest, to 1/1000 pt top-left unrotated `i32` — a float bbox would make any digest over it libm- and platform-dependent. No synthesized geometry exists anywhere in the framework (INV-9). |
| **L-2** | **Section containment** | Markdown encodes heading *level* (`##`), not heading *membership*. A text splitter windowing on characters cannot know which section a paragraph is in, so it cuts across the boundary and mixes two sections into one retrievable unit. | Scope a query to a clause; answer "what does §4.2 say"; refuse to blend two contracts' terms. | `block.parent` + `ord` is real containment; `heading_path` is derived from it; a Segment is heading-scoped, table-atomic, **zero-overlap** and block-aligned, so a Block belongs to exactly one Segment and overlap is unrepresentable. `Filters.sec_path_prefix` narrows on it before any channel scores. See [03](03-document-model.md) and [06](06-structure-extraction.md). |
| **L-3** | **Table semantics** | GFM pipe syntax has no span. A merged cell is either duplicated across the cells it covers or blanked, and the cell → (row, column) map is gone. Row and column headers become ordinary text. | Read a value at (row, column); sum a column; round-trip the table into a deck; tell a header from a datum. | Cells are ordinary Blocks with `addr` `p14/3/r2c5` inside anydoc's exactly-once `Grid`. `Capabilities.tables` is an ordered ladder (`none < flat_html < cells < cells_with_spans`) and the shipped office Driver declares the top rung. The gate `table_rel_acc` on slice `*/has_merges=1` is budgeted at **0.70** with a 0.020 guard, deliberately low, because merges are where every serializer in the collection fails and a 0.90 promise would be one we could not keep. |
| **L-4** | **Confidence** | OCR and VLM engines produce confidence per glyph or per region; the document boundary aggregates it to one number or drops it. docling's finest grain is a **page**: `ConfidenceReport(PageConfidenceScores)` with `pages: dict[int, PageConfidenceScores]` (`docling/docling/datamodel/base_models.py:486-489`). marker keeps its routing signals internal and exports none (`_index/comparisons.md` (`_index/comparisons.md`, not published), "Representation fidelity"). | Tell a clean born-digital paragraph from a garbled OCR line inside the same answer; decide whether to escalate; decline to quote. | `Capabilities.confidence` is an ordered ladder whose top rung is `element`, so "per Block" is a declarable, testable claim rather than an aspiration. `Trust` (ordered `AMBIGUOUS=0 < INFERRED=1 < EXTRACTED=2`), `Quote` (ordered `SYNTHETIC=0 < RECONSTRUCTED < REFLOWED < NORMALIZED < VERBATIM=4`) and `Method` (ten members) are **per Block**, clamped by `MAX_TRUST_BY_METHOD` after the Driver returns (INV-7). Both enums put the weakest tier lowest so `MIN()` over a Segment is the Segment's tier and not its best member. An uncalibrated confidence may print an ordinal name and never a digit (INV-19). |
| **L-5** | **Round-trip fidelity** | OUT is treated as prose generation. The model is asked for PPTX XML, or for markdown that a converter styles badly, and nothing records which source Block each produced element came from. Of the three OUT repositories mined, exactly one has any round trip (ppt-master's `pptx_intake.py`); hyperframes' Remotion port is one-way, from a different source format (`_index/out-01-generation.md` (`_index/out-01-generation.md`, not published)). | Answer "which decks quote page 14 of this contract"; edit a generated deck without reconstruction loss; treat a generated artefact as a citable document. | The IL bundle is retained content-addressed in CAS and pointed at by `artifact_unit.il_sha256`, so editing an omniweave-built artefact is a `passthrough` `UnitOutcome`, not a reconstruction. `artifact_cite` is the authoritative citation channel with a **proved** `verbatim` bit; inferring a citation from visible text on read-back is rejected outright. `read_back` is an ordinary `parse/1` Driver stamping `Method.ROUNDTRIP` (OUT22). See [09](09-generation.md). |

### 1.2 The two losses nobody in the collection even attempts

**L-6 — the meaning of zero.** No repository in the collection distinguishes *"this corpus does not
contain that"* from *"OCR failed on pages 12-40 of the one document that would have contained it"*.
Both return an empty list. That is the most expensive failure available to a document system, because
a confident zero terminates the agent's search. omniweave's `VerdictState` has four members
(`ok | low_confidence | absent | degraded`) and `absent` is reachable only after **fifteen**
precedence-ordered absence gates, any one of whose failures forces `degraded`. Gate 9
(`parse_gap_in_scope`) is one indexed join against `diag` over the thirteen-member
`ABSENCE_BLOCKING_DIAGS` set — `OW_NEEDS_OCR` among them — and turns exactly that scenario into
`degraded`, with a `DegradeCause` naming the document, the page range and the exact command that
clears it. There is exactly one `return VerdictState.ABSENT` site in the framework (INV-11, SV8),
enforced by semgrep, with one fixture per gate. See [07](07-store-and-retrieval.md) for the gate list
and the `build_verdict()` constructor.

**L-7 — cost, licence and restriction as document facts.** No repository prices a document, and none
propagates a model-weights licence from the engine that read the page to the answer that quotes it.
This matters commercially: the three highest-accuracy open parsers in the collection — marker, surya,
lift — are simultaneously the three under revenue-gated OpenRAIL-M weights, free below **$5M** funding
or revenue and requiring a commercial licence above it
(`_index/comparisons.md` (`_index/comparisons.md`, not published), "License risk map"). A team that builds on them
and then crosses that threshold has a compliance problem distributed across every artefact it ever
produced, with no query that finds the affected rows. In omniweave, `restriction_bits` is stamped by
the runner from the producing DriverCard onto every Block, Segment, entity, mention, entity edge,
claim, asset and artefact (INV-16), is `NOT NULL` on every carrier with partial indexes, and **blocks
the OUT direction**: the `compile` host refuses and names the offending cites and asset ids (OUT11).
A Driver reports a physical `Spend` vector (`{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls,
bytes_egress}` plus a provider tag) and never money; only the operator-owned `PriceBook` converts
`Spend` to micros (INV-15). See [14](14-security.md) and [12](12-performance.md).

### 1.3 The same mechanism, in the OUT direction

The OUT direction fails for the mirror-image reason. Asking a model for the target format directly
produces invalid output, so every serious system in the collection independently converged on the same
three-stage shape — **author a constrained intermediate language, run a deterministic validator that
can block, then compile** — and none of them generalised it. ppt-master constrains the *language*
(a canonical SVG subset; `_SUPPORTED_INLINE_STYLE_PROPERTIES` is 32 properties, counted from
`ppt-master/skills/ppt-master/scripts/svg_quality/svg_contracts.py:180-188`); open-slide constrains the
*canvas* (fixed 1920×1080, language stays general React); hyperframes constrains the *contract*
(determinism rules on HTML/CSS/JS). Three projects, three validators, three sets of findings with
incompatible severity models, zero shared provenance, and one round trip between them.

omniweave's answer is not a generic generator abstraction and not a universal omniweave IL — the
charter rejects both, and the `docx` target exists in the release-1 set specifically to falsify the
one-interface-over-slides-and-flow-documents claim. A **Target** is an artefact kind implemented by
exactly two Drivers on the existing Ports (one `compile/1`, one `parse/1`) plus four target-owned
artefacts: a `constructs.toml` `ConstructTable`, a `RulePack` of one-function-per-file predicates, a
`lower()` and a `read_back()`. Everything else — the `Finding` model with orthogonal
`Severity`/`Provenance`, the rule runner, the ten-value `GateStatus`, the asset ledger over L2's
`asset` table, the `OWC1` marker grammar, `manual_required`, the seven-value `UnitOutcome`
classification, the receipt and the round-trip laws — is framework code in `omniweave_core.out` that
no Target may reimplement. [09](09-generation.md) owns that contract in full.

## 2. Scope

Non-goals (§5) say what omniweave refuses. This section says what it *has*, at which release, and with
what provenance ceiling — because a framework whose positive scope is only implied is a framework
whose gaps are discovered by users. Every row names the artefact that proves it.

### 2.1 The input surface at release 1

| Input class | Shipped path | Provenance ceiling | The gate that holds it |
|---|---|---|---|
| Office containers — Word, PowerPoint, Excel, OpenDocument, RTF, EPUB, CSV — the twelve office media types `decode.office-native` routes | `parse.office.anydoc`, the only `inproc` Driver (seam S1), one FFI call per document | `spatial = none`, `origin_span = none`, `tables = cells_with_spans`, `reading_order = source`, `round_trip = structure`. **`quote` tops out at `normalized`**: anydoc's `Block` enum carries no per-block source address, so `os_path` has nothing to populate | `structure_f1 ≥ 0.90` on `office/*`; `parse.office.p50_ms ≤ 5` nightly |
| Born-digital PDF | `parse.pdf.pdfium` at `Rung.DECODE` | `origin_span = exact` through INV-10's `glyphs` branch, so `quote = verbatim` is reachable and `Quad` is real | `structure_f1 ≥ 0.85` and `order_acc ≥ 0.75` on `pdf/born_digital/*` |
| Scanned PDF, page images | `parse.page.olmocr` at `Rung.PAGE`, in `omniweave-vision`; named in `[drivers] enabled` so the escalation rule can fire even where the distribution is absent, in which case `resolve()` returns a named `PROBE_UNAVAILABLE` rejection rather than a silent no-op | the `OriginSpan` is the `pixels` branch — the polygon *is* the address — so `verbatim` is unreachable by construction (INV-10) | `hallucination_rate ≤ 0.02`; the 2,400-block human `scan-degraded` slice |
| Locators: local paths, `http(s)` URLs | `acquire/1` Drivers `fs` and `url` → `unit` roster rows plus blobs in CAS (charter §3.1) | n/a — acquisition produces bytes and a roster, never Blocks | `ingest_scope` completeness feeds absence gate 4 |
| **HTML, email** | **HTML and XHTML: `parse.text.builtin`** ([drivers](04-driver-system.md) §10.1, D646), with the other eight text tokens `decode.text-native` routes. **Email: no first-party `parse/1` Driver at release 1.** Named in charter §1's prose; there is no enabled Driver, no format gate slice, no fixture class and no Lane. A third party ships one | HTML: `origin_span = none`, `quote` tops out at `normalized`; email: whatever their card declares and the testkit proves | V-Q6 |
| **Audio, video** | **Out of scope.** No `parse` Lane transcribes; `audio` and `video` appear in the framework only as OUT asset roles and as the unimplemented `video` Target | n/a | V-Q7 |

The shipped parse `Lane` registry is `text`, `table`, `math`, `fields`, `caption`; the graph lanes are
`anchor`, `xref`, `entity`, `claim`, `community`, `summary`. The registry is open and adding a lane is
a Driver, not a core release (NG-11). [05](05-ingest-and-routing.md) owns the router that selects
`Rung` × `Lane`; [04](04-driver-system.md) owns the DriverCard that declares a lane.

### 2.2 The output surface at release 1

Four Targets ship. `ArtefactDeterminism` is a declared set over four classes; `part` (member-payload
equality) is the promised floor and `byte` is recorded, never promised, because a zlib bump falsifies
it (OUT13).

| Target | Carrier IL | Route | Determinism | Release 1 status |
|---|---|---|---|---|
| `pptx` | declared SVG subset | pure Python, `passthrough` | `part` | implemented |
| `deck` | HTML | Toolchain child process (seam S2) | `render` | implemented |
| `docx` | HTML, a flow carrier | pure Python | `part` | implemented; deliberately **not** in `[recommended]` |
| `video` | `owmotion/1` | Toolchain | `frame` when it lands | ships with `[compile] implemented = false`, and `ow out targets` prints the reason |

`bake` (rasterizing a construct the target cannot express natively) is `unavailable` on every target
at release 1, fail-closed: both candidate rasterizers are LGPL-3.0, and `cairosvg` is imported by
ppt-master's `svg_to_pptx/pptx_package/media.py:15` while appearing in no requirements file — G3's
named regression fixture. See F18.

### 2.3 The interface surface

One Action registry, seven generated surfaces (the CLI parser, the SDK, the MCP tool schemas, the MCP
`instructions`, `llms.txt`, `AGENTS.md`, the router skill's action table), all byte-diff gated
(INV-20, gate G25). Four MCP tools are listed — `ow_query`, `ow_open`, `ow_corpora`, `ow_add` — under
a frozen 1,900-token `tools/list` baseline. The entire OUT direction is skills plus CLI, **never MCP**.
`ow serve --http` exists for non-agent callers and refuses a non-loopback bind without `--api-key`.
[10](10-interfaces.md) owns all of it.

### 2.4 The scale envelope

| Tier | Shape | Where it lands |
|---|---|---|
| **T1** | one `.owstore`, one writer, one thread per connection (INV-17) | v0.1 |
| **T2** | one store plus the full WAL valve and an ANN `VectorBackend` behind the `omniweave.backends` entry point | v2.0, conditional on F9 and F10 |
| **T3** | Postgres behind the same four protocols with **zero Operator changes** — that is the entire point of making the store the distribution boundary | v2.0, conditional on F28's scope question |
| **T4** | a fabric of shards federating by **rank** fusion, because two BM25 indexes with different corpus statistics produce incomparable scores; the bias toward small shards is disclosed as `fusion_kind = "rank_merge"` plus `shards_contributed`, never hidden behind a global `term_df` table nobody can keep consistent | v2.0, conditional on F35 |

The 16-bit minting prefix in `block_id` ships at shard 0 from day one, at zero bytes, precisely so T3
and T4 can never become a migration (F28). [07](07-store-and-retrieval.md) owns the tiers.

### 2.5 What is deliberately unavailable at release 1, and disclosed rather than hidden

Four product limitations are pre-committed, printed by the framework itself, and are **not** failures
(§10):

- `vectors = "off"` is the shipped default. A first run gets four of five retrieval channels and a
  `Verdict` whose `channels` mapping says `semantic: off`.
- `verbatim` is unreachable on the office path. `corpus_card.verbatim_fraction` prints that before any
  query runs, and `vendor/anydoc/FORK-TRIGGER.md`'s first clause names the change that opens the tier
  (emit a `w:p` / `a:t` child-index path per Block).
- No confidence signal is calibrated, so nothing renders a digit (INV-19). `Trust` and `Quote` stay
  usable as internal filters and sort keys.
- `bake` is `unavailable`; `video` is `implemented = false`; `doc_acc` on `fields/*` is gated at 0.20.

## 3. The thesis, and what follows from it

> **One document model in the middle, with provenance and confidence on every Block; parsers are
> Drivers that populate it, indexes are views over it, generators compile out of it, and the
> framework's only irreplaceable job is to route work by evidence and cost, and to carry provenance
> across the whole loop.**

Eight consequences follow. Each is load-bearing rather than decorative, and each is specified in the
document named.

1. **Markdown is an output, never a representation.** No model class in the framework has an `html`,
   `markdown` or `md` field, and a build-failing test asserts it. `serialize()` is core's own function
   over five core-owned formats (`md`, `gfm`, `html`, `text`, `otsl`) and returns `(str, SpanMap)` —
   the text and the map back to Blocks — so a string never travels without its inverse. There is no
   text-only serializer: if you have the text you have the map. A format whose `SERIALIZER_CAPS` entry
   is `False` may never be cited from, and at release 1 there is no such format.
   → [03](03-document-model.md)
2. **A parser is not the framework.** Because parsers are Drivers behind a versioned `parse/1` Port
   described by a TOML DriverCard that core reads **without importing the Driver** (INV-4), the choice
   of OCR engine is a config line, a licence tier and a benchmark row rather than an architecture.
   omniweave ships no weights and is not an OCR research project. → [04](04-driver-system.md)
3. **Every index is a view, so there is never a second copy of a Block's text.** `block_fts` is an
   FTS5 **external-content** table over `block.text`. INV-1 forbids a second text column *and* any
   reference to a Block by anything other than `block_id`; a schema lint classifies every foreign-key
   target and rejects a positional reference. This is what makes "the store is the truth" checkable
   instead of aspirational. → [07](07-store-and-retrieval.md)
4. **Provenance is written by the host, not claimed by the producer.** A Driver receives `DriverIO`
   and nothing else — no store handle, no cache handle, no budget ledger, no writable root, no socket
   (INV-6); `HELLO` carries only `{source_ro, tmp, blob_base}`. It cannot forge `producer_id`,
   `origin_driver`, `origin_operator`, `restriction_bits`, `confidence`, `was_cache_hit`, a price, a
   `Trust` level or a citation (INV-7). `DriverResult.outcome` is restricted to `{ok, ok_partial}`;
   `DriverMetrics` has no currency field; a generated `BEFORE INSERT` trigger mirrors the trust clamp
   with CI parity. Honesty is structural, not a review habit. → [04](04-driver-system.md)
5. **Byte-exactness is claimed only where it is proved.** `Quote.VERBATIM` requires a retained
   content-addressed copy of the part (`part.store_ref IS NOT NULL`) **and** an `OriginSpan` that
   re-verifies on one of exactly three branches — `bytes`, `nodepath`, `glyphs` — and `Q-G6` gates
   `span_exact_rate` at **1.000** as a hard gate, not a metric. The gate runs over Blocks that *claim*
   verbatimness, so a slice with no such Blocks passes vacuously, which is correct. Serve reads the
   claim from `doc.achieved`, never from a card, at one call site. → [03](03-document-model.md),
   [05](05-ingest-and-routing.md)
6. **Routing is the irreplaceable part.** Escalation is per part and monotone (`child.rung >
   parent.rung` always, over the seven-member ladder `GATE < DECODE < REPAIR < PAGE < REGEN < DEGRADE
   < ENRICH`), and a clean born-digital PDF page computes zero `LOCAL_COMPUTE` signals, renders no
   raster and starts no model server — asserted by *exact* counters (`service_attaches`,
   `page_renders`, `signal_computations`) where ±1 fails (INV-13, RT4). Budget never changes which
   `Rung` is chosen, only whether it runs: `evaluate()` is pure over `(policy, evidence, hints)` and
   its signature has no ledger and no clock (INV-14). → [05](05-ingest-and-routing.md)
7. **The loop closes through the front door.** An artefact compiled at L6 re-enters at L1 as an
   ordinary `parse/1` Driver, so a generated deck is a citable corpus document with `Method.ROUNDTRIP`
   provenance and gets the same ~120-test Driver testkit run against it unchanged (OUT22). There is no
   privileged re-import path — and §8 states the hazard that creates. → [09](09-generation.md)
8. **Nothing agent-facing is hand-written.** Every MCP tool schema, the `instructions` string,
   `llms.txt`, `AGENTS.md`, the CLI verb tree, the SDK stubs and the router skill's action table are
   generated from the one Action registry and byte-diff gated (INV-20, gate G25). LEANN's `llms.txt`
   declares two tools against a four-tool server, two of them state-changing and undeclared; that
   defect is unreachable here by construction. → [10](10-interfaces.md)

## 4. Users and use cases

Six stories. Each names the user, the workflow they run today with its concrete failure, the omniweave
workflow with real verbs, and the mechanism that makes the difference — not the feeling.

### 4.1 The contract analyst's agent (a 5,000-page matter)

**Today.** The agent is pointed at a directory of 137 PDFs. It calls a host `Read` on
`MSA-2024-final.pdf`, gets 400 KB of markdown with the pages already gone, spends most of its context,
and answers "the MSA appears to allow termination for convenience with 30 days' notice." The human
asks *where*, and the agent cannot say. Pages 12-40 of the executed copy were a scan the converter
silently returned as empty; the clause the human actually needed is on page 31. Nothing in the
transcript reveals this. The answer is confident and wrong.

**With omniweave.**

```text
ow add ~/matters/acme-msa/         # writes the roster; spawns a detached `ow ingest --scope <id>`
ow query --corpus acme "termination for convenience notice period"
```

The Answer is a fixed-section document of ≤ 24,000 chars, one content block, no `outputSchema` — the
ceiling is set at the host inline tool-result cap (~25,000 chars) because above it the result is
externalised to a file the agent must `Read` back, reintroducing exactly the read the tool exists to
remove. Every emitted block carries `cite · page · quote · trust · method · origin_driver ·
restriction_bits`. The byte-exactness sentence appears only where `quote == VERBATIM` **and**
`doc.achieved` supports it — never from a DriverCard's claim. And because pages 12-40 produced an
`OW_NEEDS_OCR` row in `diag`, absence gate 9 fires: the state is `degraded`, not `absent`, the
`DegradeCause` names the page range, and it prints the command that fixes it.
`ow query --fail-on absent,degraded` makes that a non-zero exit (3 and 4 respectively) for a scripted
caller.

**The mechanism.** Not "better retrieval". The mechanism is that the empty result is *typed*. The
agent gets a state it can act on rather than a list it must trust.

### 4.2 The compliance officer (the query that has no answer today)

**Today.** "Which of our client decks quote non-public pages of the Acme contract?" is a question
nobody can answer, because a deck is a file and the contract is a different file and nothing joins
them. The honest answer is a two-week manual review.

**With omniweave.** `artifact_cite` is `(artifact, unit, el, cite)` with a pinned `doc_gen`, a citation
kind and a **proved** `verbatim` bit — one indexed query. Combined with `restriction_bits` propagation
(INV-16), the same join answers "which artefacts contain content produced by a Driver whose weights
licence became commercially restricted", which is the question the OpenRAIL-M exposure in §1.2 creates
and which no other stack in the collection can express at all.

**The mechanism.** The generated artefact is a first-class corpus document, not a build output — a
consequence of thesis point 7, and the reason the loop closes through `parse/1` rather than through a
bespoke importer that could invent its own provenance.

### 4.3 The deck build (the OUT direction, end to end)

**Today.** The agent is asked for a 12-slide deck from a 90-page report. It writes markdown; a
converter produces slides with 11-point body text overflowing the frame; the human rewrites all twelve
slides in PowerPoint. Or the agent writes a python-pptx script and produces valid XML that renders as
unstyled boxes. Either way the source of truth is now the .pptx, and the report is disconnected from
it.

**With omniweave.** `ow make deck <selection>` — OUT is skills plus CLI, never MCP. The model authors
the IL (a declared SVG subset for `pptx`, HTML for `deck` and `docx`); `ow out check` runs the
`RulePack` and returns `Finding` rows folded on `(code, rule, unit, canonical)` with a count and at
most three examples, each with a **non-empty `fix`** (`__post_init__` raises otherwise, OUT6), so 200
lowercase hex colours are one recommendation and not 200 lines of noise. `Severity` decides whether a
finding blocks and `Provenance` decides who owns it, orthogonally — so **an inherited error still
blocks**, attributed to the template. `ow out compile` produces the artefact and a receipt;
`ow out verify <artefact>` is the user-facing check that makes editing an omniweave-built artefact
safe. A unit the framework cannot honestly produce is `manual_required` with a mandatory
`ManualReason` from a closed seven-member vocabulary — it is never faked. `GateStatus` has ten values
and exactly one, `passed`, permits a release; `passed-with-warnings` is a report status and never a
gate status, and every non-`passed` status prints the exact command that clears it.

**The mechanism.** The validator can block, and it never rewrites the IL (OUT20): `ow out stamp` and
`ow out normalize` are separate commands with their own exit codes, semgrep bans a write under `il/`
from `rules/`, and no flag makes the checker repair its own input. A generator that can silently
repair its own input cannot be held to a contract. `CompileV1` additionally has no `validate()`, so a
target cannot run — and therefore cannot skip — its own gate (OUT23).

### 4.4 The non-agent user: a Python service over 100k invoices a month

This user has no agent, no MCP host and no chat. They have a FastAPI service and a JSON Schema.

**Today.** They call a hosted document API and discover two things over the following quarter. First,
full-document accuracy is far below per-field accuracy: on lift's own 225-document, ~11,000-field
benchmark, lift scores **90.2% per field against 20.9% full document**, and the best full-document
entry in that table is the Datalab API at **44.4%** against 95.9% per field
(`lift/README.md:70-80`) — so a document-level "valid" flag is not obtainable by prompting harder.
Second, when a field is wrong there is nothing to look at, because the API returned a value and not a
location.

**With omniweave.** The service imports the SDK, whose stubs are generated from the same Action
registry the CLI and MCP surfaces are (`omniweave/sdk/_generated.pyi`), or calls `ow serve --http`
behind its own authorization. It runs `want="fields"`, gets fields *with* cites, and resolves any
suspect field with `ow open <cite>` to get the exact Block, page and polygon a reviewer can look at.
Ingest is transactional and idempotent: identical bytes are never re-parsed, `ow add` is safe to call
twice, and `ow cost --by driver --since 7d` reconciles against the run manifest's spend rows.

**The mechanism.** Three surfaces, one implementation. `omniweave-serve` may not import `omniweave`
(the import DAG, gate G4), which is precisely why the retrieval engine and the Answer renderer live in
`omniweave_core.retrieve` and `omniweave_core.answer`: MCP, CLI and SDK call one implementation and
none of them owns it. A library user is not a second-class consumer of an agent product.

Two caveats for this user, stated here rather than discovered later: the shipped default is
`vectors = "off"`, so a first run gets four retrieval channels and a `Verdict` that says
`semantic: off`; and `doc_acc` on `fields/*` is gated at **0.20**, not 0.90, because that is what the
field can currently deliver and `Q-G21` refuses to ship `field_acc` without `doc_acc` beside it.

### 4.5 The retrieval platform engineer replacing a loader stack

**Today.** A loader per format, a text splitter with a character window and an overlap, a vector store
and a re-ranker. Retrieval returns text with a `source` metadata key holding a file path. When a
citation is challenged, the platform cannot produce a page. When a table is retrieved, the merged
header has become a duplicated string. When the corpus changes, the re-index is a full rebuild,
because nothing tracks per-document identity across re-parses — and the cost of skipping that pass is
measured, not theoretical: codegraph's own repository diverged from a clean rebuild by **1,227 edges,
4.3% of distinct edges, in both directions, silently**
(`codegraph/docs/benchmarks/index-drift-cg33.md:5,25`).

**With omniweave.** The engineer keeps their orchestration and replaces L0-L4. `rebind()` is an
explicit re-parse identity pass with three rules and a `threshold = 0.80`: equal `content_digest`
under the same parent carries the `block_id` **and** the `cite`; equal `addr` and kind with a changed
digest carries both and increments `revision`; neither mints a new `block_id` and a fresh `cite` `n`
from `doc.next_cite_n` and retires the old row into `block_history` with a reason and a
`superseded_by`. **Carrying the cite is the point of the pass** — a cite is a shipped, durable name,
`block_cite` is `UNIQUE(doc_ord, cite)` with no `gen`, and re-minting on re-parse would re-point every
citation already sitting in someone's document. A retired cite still resolves by following
`block_history.superseded_by`; where `superseded_by IS NULL` the answer is a stated refusal
(`OW-M-030 / OW_CITE_RETIRED`) naming the generation it was retired at and the reason — never a silent
miss and never a nearby Block. Below the threshold the new generation is **quarantined, not
committed**, and L3 does nothing until it clears; overrides are named per check
(`--allow-unexplained-rebind`), never one broad off switch. INV-18 plus gate G19 assert that an
incremental run converges to a full rebuild, measured as a 300-document fixture under 40 scripted
mutations, diffing the `.owdoc` *exports* rather than the tables.

**The mechanism.** Identity across re-parses is a designed pass with a quarantine threshold, not an
emergent property of hashing text. And `rebind()` is *also* the golden differ, so there is one matcher
and nothing to drift.

### 4.6 The Driver author (a third-party OCR vendor)

**Today.** They publish a Python package and a README. Integration into any given stack is bespoke,
their accuracy claim is unfalsifiable, and their model's licence is a sentence in a model card that
nothing downstream reads.

**With omniweave.** They ship one distribution declaring one `omniweave.drivers` entry point (a
colon-free dotted package path, because setuptools validates the value form at build time) and one
`driver.toml` DriverCard whose `entrypoint` is `module:attr` — the one place in the framework a colon
is legal, because `activate()` must assert the loaded class's `PORT` and `SCHEMA_VERSION` before any
work. They depend on **`omniweave-ports >=1,<2` and nothing else of ours** — a stdlib-only typing
distribution with no dependencies of its own, ceiling 1 MB, versioned by Port major — so they cannot
pin the framework and a core upgrade is never blocked by their floor (charter §3.2 rule 3; gate G4
reads their entry points and asserts the row is `["omniweave_ports"]` exactly). They declare
`[capability.parse]` from the same fifteen-field `Capabilities` set the model uses, and
**over-declaring fails the shared testkit's ~120 property tests** — including a per-Driver proof of
`origin_span = 'exact'` by re-reading the retained part on whichever of INV-10's three branches their
`os_kind` selects. They run `ow conform` for the eleven mandatory suites (which must complete in under
five minutes on a laptop, enforced as a CI timing assertion) and `ow conform --bench` for the twelfth,
which **writes** the card's `[quality]` block; author-supplied measurements there are rejected by the
publish gate, and every row carries four kit-written keys (`n`, `ci95`, `witness`, `measured_on`) with
all ten fields of a frozen, defaultless `MeasuredOn` — a card supplying seven of them cannot construct
the type and fails `Q-G8`. Their licence facts go in `[licence.weights]` with an exact
`weights_revision` sha; `revision="main"` is a card error (RT14) and is banned framework-wide by
semgrep, because docling defaults six RT-DETR layout specs to exactly that
(`docling/docling/datamodel/layout_model_specs.py:87-122`) — and `grep -rn "revision=" marker/ surya/
lift/` returns zero hits, so those weights were never reproducible even where licensed.

**The mechanism.** Installation is not consent (INV-5). Their Driver executes only when it is named in
`omniweave.toml [drivers] enabled`, its computed licence tier is allowed and, if restricted,
acknowledged against the licence text's hash — a mutated licence file yields `LICENCE_ACK_STALE` with
the hash diff printed. Discovery never executes their code: the catalog is built from
`importlib.metadata` and `tomllib` alone, and an entry-point value is a string that is never
`load()`ed (INV-4; gate G11 installs a rogue Driver whose module body writes a file and raises
`SystemExit`, and asserts `ow doctor` succeeds and the file is absent). This is the property that
makes a third-party ecosystem safe to have, and docling's own factory calls
`load_setuptools_entrypoints` at `docling/docling/models/factories/base_factory.py:96` and checks
`allow_external_plugins` at `:101` — one loop later — which is the defect it is aimed at.

Attestation is stated for what it is: **tamper-evidence, not authentication.** An author can run the
kit on a clean build and ship a different wheel with the same card; only `dist_sha256` in
`omniweave.lock` catches that, and only for consumers who installed through `omniweave-index`. The
docs say so rather than implying a signature.

## 5. Non-goals

Non-goals are the highest-value part of this document, because every one of them is a request omniweave
will receive and must refuse in the same words each time. The first nine are the charter's own (§1) and
are quoted in substance; the remaining five are new and marked.

| # | Non-goal | The reason | Use instead |
|---|---|---|---|
| **NG-1** | **Not a chat product, an agent, or a UI.** | omniweave never decides what to ask. It is a library, a CLI, an MCP server and a set of skills. An opinion about the question would have to live somewhere, and every place it could live is a place a caller cannot override. | Your host (Claude Code, Cursor, an app you write against the SDK). omniweave installs into it with `ow install`. |
| **NG-2** | **Not a markdown pipeline.** | Markdown is an output of serialization, never the representation. No model class has an `html`, `markdown` or `md` field, and a build-failing test asserts it. Accepting a markdown pivot would forfeit L-1 through L-5 on the first hop. | markitdown or anydoc, called directly, if a markdown string is genuinely all you need. anydoc converts fourteen office formats at a 4.4 ms median; omniweave cannot beat that at a task that does not need a `block` table. |
| **NG-3** | **Not a general workflow engine, scheduler, broker or service mesh.** | No daemon, no loopback control listener, no second durable store that must agree with the `work` table about what is done. The Supervisor drives one store's roster and nothing else. A general engine needs a second source of truth about completion, and two sources of truth about completion is the bug. | Prefect, Airflow, Temporal, or your own cron. Call `ow ingest` from it. |
| **NG-4** | **Not a vector database, graph database or search engine.** | SQLite is the store; an ANN index is an optional `VectorBackend` behind the `omniweave.backends` entry point. Owning an index means owning its recall, its compaction and its clustering, none of which is our irreplaceable job. | pgvector, Qdrant, LanceDB, Neo4j. Register one as a Backend, or export with `ow store export --portable` and index it yourself. |
| **NG-5** | **Not a model trainer, and not a model host beyond attach-or-spawn.** | omniweave ships no weights. Seam S3 is attach-or-spawn with model-id verification on attach and a 32-byte token in a 0600 sentinel — that is the whole of it. Hosting is a different product with a different operational contract. | vLLM, Ollama, TGI, SGLang. omniweave attaches to a running engine and records the shortfall where it cannot. |
| **NG-6** | **Not an OCR or layout research project.** | We ship the best licence-clean implementation available and make the choice replaceable, priced and measurable. Competing on OCR accuracy would mean owning weights, which contradicts NG-5, and would put the framework in competition with its own Driver ecosystem. | surya (83.3% on olmOCR-Bench at 650M params), olmocr, HunyuanOCR, Unlimited-OCR — as Drivers, or directly if you are benchmarking engines rather than building a corpus. |
| **NG-7** | **Not a benchmark leaderboard.** | The scoreboard exists to make *our own* numbers falsifiable. It defaults to accuracy-per-dollar within a licence tier and prints `UNKNOWN` far more often than a number, because `Q-G8` refuses an `eval_metric` row without a complete `MeasuredOn` and marks an unpinned corpus `UNRANKED`. DR24 additionally treats any card row whose `measured_on.corpus_digest` is not in our release manifest as `witness = "self"`, displayed and never ranked. | olmOCR-Bench, OmniDocBench. Our scoreboard will not rank your Driver against a competitor's on a corpus neither of you pinned. |
| **NG-8** | **Not multi-tenant at v1.** | One writer per store (INV-17). Tenant isolation is store-per-tenant. Row-level tenancy forfeits the `segment.content_digest` embedding dedup and turns it into a covert channel: two tenants observe each other's embeddings as a timing difference. F27 records this as open with the pre-committed answer "v1 is store-per-tenant"; **no plan document may assume row-level tenancy.** | One store per tenant, one process per store. If you need shared-index multi-tenancy, this is not the framework yet. |
| **NG-9** | **Not a compiled-code owner.** | Exactly one compiled dependency exists (`firecrawl-anydoc == 0.2.4`), it is someone else's published `abi3` wheel, and we do not build it. Every distribution is `py3-none-any`. Owning compiled code was priced by its own proposer at 4-6 engineer-weeks for the substrate alone, and the justifying premise (three languages must agree on L2 byte-for-byte) is false: L2 never reaches TypeScript. | If you need a Rust document kernel, build one and publish it as a Driver. `vendor/anydoc/FORK-TRIGGER.md` names the exact conditions under which we would fork one, and they are measurements, not preferences. |
| **NG-10** | **Not a document editor, a preview server or a WYSIWYG surface.** *(new)* | omniweave compiles artefacts and reads them back. An editing UI needs a live bidirectional binding to the IL, which makes the framework the owner of a rendering loop and of a browser, and it needs a listener: charter §D1 prices this by name — open-slide's local server needs a CSRF guard as a *minimum*, and a long-lived local listener is exactly what §3.4 bans outside the four seams. | PowerPoint, Word, the target's own preview. `ow out verify <artefact>` is the check that makes hand-editing an omniweave-built artefact safe, and an `OWC1:` Marker survives the edit because it is in the file, and presence is the state (OUT19); that is the supported workflow. |
| **NG-11** | **Not a domain-model shop: handwriting, CAD, sheet music, medical imaging, chemical structures.** *(new)* | Each needs a domain model, a domain benchmark and a domain licence review. The framework ships none and will not special-case any of them in the router, because a lane whose only implementation is absent is a lane that lies. (`Kind` does carry `HANDWRITING`, `CHEMICAL` and `DIAGRAM` members for forward compatibility — a vocabulary slot is not a capability claim.) | A `parse/1` Driver you or a vendor writes. The `Lane` registry is open; adding one is a Driver, not a core release. |
| **NG-12** | **Not a translation, rewriting or summarization product.** *(new)* | omniweave never rewrites a Block's text in place. A `summary` graph lane exists and its output is a *new* row at `Quote.SYNTHETIC` with its own `Method` and `Trust` — it never overwrites the source. Rewriting in place would make INV-1's "one representation of a Block" and INV-10's byte-exactness proof simultaneously unenforceable. Even defanging a chat-template sentinel happens **on a copy**, and the defanged Block is emitted as `normalized`, marked `ow:defanged` and counted in the trailer. | Your own model call over `ow_query` output. You keep the cites; we keep the source. |
| **NG-13** | **Not an analytics engine over extracted fields.** *(new)* | `want="fields"` returns fields with cites for a bounded selection. Aggregating a million invoices means a columnar scan, a query planner and a cost model for joins — three things SQLite-plus-FTS5 is the wrong substrate for and that no invariant here protects. | `ow store export`, then DuckDB or your warehouse. Keep the `cite` column: it is what lets you walk from a suspicious aggregate back to a polygon. |
| **NG-14** | **Not an access-control or DRM system.** *(new)* | `restriction_bits` is a propagating bitmask of licence and use restrictions, stamped by the runner and enforced at the `compile` boundary. It is **not** a per-user ACL and has no notion of identity. Giving it one would put an authorization decision inside a bitmask that also encodes licence facts, and the two have different lifetimes. | Your own authorization in front of `ow serve --http`, plus the store-per-tenant boundary from NG-8. And read charter §6.11: a compromised publisher's Driver with read access to `source_ro` can exfiltrate a corpus, and that residual risk is written down rather than argued away. |

Three further refusals that are less obvious and get asked anyway:

- **Not a crawler.** An `acquire/1` Driver turns a locator into `unit` roster rows plus blobs in CAS.
  We ship `fs` and `url`. We do not ship a JavaScript-rendering spider, a sitemap walker or a
  login-session manager, because a crawler's failure modes (rate limits, robots, auth, infinite
  calendars) are a product, not a Port. Use Firecrawl or Playwright and hand omniweave the files.
- **Not real-time.** Ingest is batch, transactional and single-writer. `ow_add` returns a *pending
  cost*, not a document: free and local work runs immediately, and anything that would spend money
  comes back as the exact command that approves it. Sub-second document-to-queryable is not a target
  and no budget in [12](12-performance.md) implies it.
- **Not a defence against a persuasive document.** Every string reaching a prompt or an MCP response
  passes `wrap_untrusted()` or `sanitize_label()`; sentinels are matched **by form**
  (`<\|[A-Za-z0-9_.\-]{1,64}\|>`), never by a heading regex that fires on every SOP in a real corpus;
  and scope containment (`allowed_cites` on every derive run, `allowed_units` on every cache write,
  one tmpdir of writable surface per Driver) is the layer that survives a fully successful injection.
  But a malicious document that simply argues persuasively in prose is **not addressed**: the
  `<ow:untrusted>` framing is prose inside the same context window as the attack. Instruction-shaped
  text is *reported* (`OW-A-021`) with its `cite` and never rewritten. Charter §6.11 says so, and this
  document repeats it rather than softening it.

## 6. Positioning against the alternatives that actually exist

Five alternatives. For each: what it actually gives you, the specific mechanism that makes omniweave
worth the adoption cost instead, and the case where omniweave is the wrong choice. The last row is the
real incumbent and the hardest one to beat.

### 6.0 The adoption cost, priced first

An argument that does not price its own cost is marketing. Adopting omniweave costs:

| Cost | Number |
|---|---|
| Install weight | `omniweave[recommended]` (`serve + pdf + target-pptx`) ≤ **250 MB** installed, the AWS Lambda unzipped-layer limit (gate G2). `omniweave-core` + `omniweave-ports` alone is ≤ **4 MB** with zero third-party dependencies. `omniweave-vision` is exempt and unbounded, and `ow doctor` prints its resolved size |
| Store overhead | **660 B/Block** ± 10% (`store.bytes_per_block`, a nightly ratchet). At F1's estimated 60-120 Blocks/page including cells, a 5,000-page corpus is 0.3-0.6M Blocks ⇒ **200-400 MB** |
| Config surface | one `omniweave.toml` plus `.omniweave/policy.d/*.toml`; `ow show-config` prints every resolved value with its source, and `--digest` prints `config_digest` |
| Agent context surface | **1,900 tokens** for `tools/list`, ≤ 700 per tool, ≤ 1,000 chars of `instructions` |
| Learning surface | four listed MCP tools; `ow <group> <verb>` with no aliases |
| Hard ceilings you inherit | one writer per store; store-per-tenant; batch ingest; no `verbatim` on the office path; `vectors = "off"` by default |

Below roughly a thousand documents with no third party who will ever challenge an answer, that bill is
larger than the problem. The threshold is not document count — it is whether anyone will ever ask
*where did that come from*.

### 6.1 Calling docling (or marker, or anydoc) directly

**What you get.** The best structured intermediate in the open ecosystem. `DoclingDocument` has real
provenance and per-page confidence; marker's block tree has polygons and scores **76.0% overall /
83.5% born-digital on olmOCR-Bench** (1,403 PDFs, ~8,400 pass/fail tests, macro-averaged over eight
categories — `marker/README.md:45,457,469`); anydoc converts fourteen office formats at a 4.4 ms
median. If your job is "one document to structure", these are the right tools and omniweave uses them.

**Why omniweave instead.** Four things you must build yourself on top of any single parser, all of
which are framework-shaped rather than parser-shaped:

1. **Routing between them.** No single parser wins: docling wins structure depth, markitdown wins
   source variety, anydoc wins speed, omniparse wins modality breadth
   (`_index/comparisons.md` (`_index/comparisons.md`, not published), format matrix and "one winner per axis").
   Picking one is picking its blind spot. omniweave's router escalates **per part**, monotonically,
   and a clean born-digital page pays nothing — enforced by exact counters, not by intent.
2. **A store with identity across re-parses.** `rebind()`, `block_history`, cite carrying, and G19's
   convergence proof. Calling a parser gives you a fresh object graph every time.
3. **The `Verdict`.** A parser tells you what it found. It cannot tell you that a zero result is not
   proof of absence, because it never saw the corpus.
4. **Licence and cost propagation.** marker and surya are OpenRAIL-M with a revenue gate; docling
   pins six layout models at `revision="main"`, which is unpinnable and which RT14 refuses. Neither
   fact reaches your artefacts unless something carries it.

**When omniweave is NOT worth it.** One format, one document at a time, no citation requirement, no
corpus. If you are converting DOCX to markdown inside a request handler, anydoc is 4.4 ms and
omniweave is a store, a roster and a transaction. Use anydoc.

### 6.2 LangChain / LlamaIndex document loaders

**What you get.** Breadth and a single import. Fifty loaders, a text splitter, a vector store
adapter, and a working demo in fifteen lines.

**Why omniweave instead.** The loader interface is the problem, not the loaders. A loader returns
text plus a metadata dict, so the interface *cannot* carry a polygon, a containment relation, a cell
coordinate or a per-Block confidence even when the underlying parser produced all four — and the
caller cannot tell which loader forfeited what, because the type is identical either way. Everything
in §1.1 is lost at the interface boundary. Concretely, three things omniweave gives that no loader
interface can express: a `Locus` whose `quad` is `None` only with a `reason` and whose `precision`
says how tight the box is; a Segment that is heading-scoped and zero-overlap, so a retrieved unit
never straddles two sections; and `restriction_bits` that reach the artefact.

**When omniweave is NOT worth it.** Prototyping, or a corpus of homogeneous plain text (support
tickets, chat logs, scraped articles) where there is no spatial provenance to preserve and no table
to get wrong. A character-window splitter over plain text loses nothing, because there was nothing to
lose. omniweave's value is proportional to how structured the source is.

### 6.3 A hosted document API

**What you get.** Zero operations, good accuracy, and someone else's GPUs. The Datalab API leads
lift's own published field-accuracy table at **95.9% per field**, and the one hosted endpoint in the
olmOCR-Bench comparison, Mistral OCR API, scores **72.0%**
(`_index/comparisons.md` (`_index/comparisons.md`, not published), "Parser accuracy & cost").

**Why omniweave instead.** Five specific mechanisms, in the order they will bite:

1. **Full-document accuracy is the number that matters and it is low everywhere.** The best entry in
   lift's table is **44.4% full-document** against 95.9% per field (`lift/README.md:70-80`). A hosted
   API returns fields; it does not return a location you can review, so you cannot triage the other
   55%. omniweave returns fields *with* cites, and `Q-G21` forbids publishing `field_acc` without
   `doc_acc`.
2. **Egress.** `bytes_egress = 0` is the default and `needs_network = false` runs with no egress where
   the OS can enforce it, **recording the shortfall where it cannot** rather than claiming it (DR10).
   Gate G15 greps for hostname literals against an allowlist and runs a socket-blocked conformance
   pass. The defect this is aimed at is named: marker's `--use_llm` ships page images to Gemini by
   default. The honest limit is also named: net namespaces are Linux-only, so on macOS and Windows
   `needs_network = false` degrades to a process-level guard a determined malicious Driver in that
   process can bypass.
3. **Cost, as a number you can audit before spending it.** `ow add --dry-run` prices the ingest;
   `admit()` reserves against a durable ledger; exhaustion re-enters as the evidence key
   `budget.exhausted` and the message names the approving command.
4. **Provenance you can subpoena.** Every Block records which Driver produced it, by what `Method`, at
   what `Trust`, from which bytes, under which licence, at what price — and all six axes survive into
   an answer, a bill, a deck and a compliance query. An API response has one axis: the vendor's name.
5. **Determinism.** A hosted model changes under you with no version you pinned. omniweave's cache key
   includes the Driver's `schema_version`, its declared `model_rev` as an exact sha, a
   `code_fingerprint` over the operator module's source, and the semantic projection of config —
   where every config key is classified `semantic` or not and an unclassified key fails CI (G18).

**When omniweave is NOT worth it.** Low volume, no compliance requirement, no local GPU, and a
deadline. Hosted APIs are genuinely the right answer for a few thousand pages a month with no audit
trail requirement, and pretending otherwise would be dishonest. Also: if you need handwriting or a
domain omniweave ships no Driver for (NG-11), a hosted specialist beats a framework with a hole in it.

### 6.4 Rolling your own

**What you get.** Exactly what you need and nothing else, which is a real advantage, and the reason
most teams do it.

**Why omniweave instead.** Because the collection is a list of the specific defects a from-scratch
build reproduces, and each has a named enforcement here. This is the honest form of the argument —
not "we are better engineers", but "here is the bug you will ship, and here is the gate that catches
it":

| The defect you will reproduce | Measured in | omniweave's enforcement |
|---|---|---|
| A silent 100% cache miss for the whole life of the project | graphrag | Gate G18: every config key is classified `semantic` or not, the union of the two key lists must cover `omniweave.toml.example` exactly, an unclassified key **fails CI**, and `cache_hits` / `cache_misses` are **exact** counters where a delta fails without a bless |
| Discovery that imports plugin code before the enable gate | docling: `load_setuptools_entrypoints` at `base_factory.py:96`, the `allow_external_plugins` check at `:101` | INV-4 + gate G11 (a rogue Driver that writes a file and raises `SystemExit` must not run) + DR1 (a core test discovers 30 cards and asserts `sys.modules` gains no driver key) |
| A WAL that reaches 5.9 GB against a 340 MB database (`codegraph/src/db/wal-valve.ts:14`), and 22.2 GB against a 4.6 GB database with exit 137 at kernel scale (`codegraph/docs/design/rust-kernel-migration-plan.md:768`) | codegraph | `wal.bulk_index_peak_bytes` budgeted at **2 GiB absolute**, not a percentage, plus the WAL valve |
| A union merge driver that resurrects deleted rows: `nx.compose(G_cur, G_oth)` at `graphify/graphify/cli.py:2572`, with caps of 50 MB / 100k nodes at `:2547-2548` — two to three orders below a document corpus at omniweave's T2 target | graphify | `omniweave.index.lock`: sort-merge by `doc_key`, identical lines union, a conflicting line for one `doc_key` is a real conflict a human resolves, and **a deleted line stays deleted** |
| Four CWD-dependent bugs | graphify | Gate G8: semgrep bans `os.getcwd()` and `Path(".")` in library code |
| Twenty extras, four incompatible vLLM pins, an unsatisfiable extra combination (`[kbc]`+`[mineru]`), and a `requires-python = ">=3.7, <4"` that is untested and false | DataFlow | Gate G14 (an `omniweave` extra may name only an `omniweave-*` sibling; there is no `[all]`), gate G5 (every version declaration site agrees, as CI job 1), gate G7 (a constraint tighter than `>=` carries a comment) |
| Five version declaration sites that drift | anydoc | Gate G5 |
| An `llms.txt` declaring 2 tools against a 4-tool server, two of them state-changing and undeclared | LEANN | INV-20 + gate G25 (`ow surface emit --check`, byte-identical) + `mcp_name = None` as a structural human-only marker rather than a denylist |
| An unauthenticated ZMQ REQ/REP on a dynamic loopback listener — compute theft from any local process | LEANN | Charter §3.4: four seams and no fifth; a long-lived local IPC daemon for parse/embed/index/schedule is banned outright; exactly two loopback TCP endpoints are sanctioned **by name** and a third requires amending the charter |
| A cross-prompt-injection programme shipped alongside "the system is designed for trusted users" | one repo, unnamed here | Charter §6.11, which the charter's own §8 makes a rejection criterion aimed at ourselves |
| An LGPL-3.0 dependency reaching production as an undeclared import: `cairosvg`, imported at `ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_package/media.py:15` and declared in no requirements file | ppt-master | Gate G3: licences checked over the resolved graph **and** the import graph **and** the unpacked artifacts; `cairosvg` is the named regression fixture and `bake` is fail-closed as a result |
| 1,227 edges — 4.3% of distinct edges — wrong in both directions, silently, from skipping the re-bind pass (`codegraph/docs/benchmarks/index-drift-cg33.md:5,25`) | codegraph CG-33 | `rebind()` as an explicit pass with a 0.80 quarantine threshold + gate G19 |
| 22,741 tokens per turn for 91 visible tools of 94 defined, against 939 for three (`jcodemunch-mcp/benchmarks/schema_baseline.json`) | jcodemunch | A frozen 1,900-token `tools/list` baseline with a 5% drift gate, four listed tools, and a mechanical listing rule (L1-L4) rather than taste |

**When omniweave is NOT worth it.** A single format, a single question shape, under ~1,000 documents,
and no third party who will ever challenge an answer. Fourteen distributions, twenty-five invariants
and thirty gates are overhead you should not pay to grep a folder of text files.

### 6.5 The real incumbent: the agent just reads the file

**What you get.** Nothing to install. The host already has `Read`, `Grep` and a shell.

**Why omniweave instead.** Because that workflow has four failure modes the user never sees. The file
gets converted by whatever the host happens to use, so §1.1's losses all apply at once. A 400 KB
markdown dump consumes the context that the reasoning needed. A scanned page range comes back as
empty text and the agent reads the absence as content. And there is no citation: the agent's answer
cites a *file*, which is unfalsifiable at the granularity anyone cares about. `ow_query`'s own tool
description exists to redirect exactly this behaviour — *"Use this instead of opening, converting or
grepping an indexed PDF/DOCX/PPTX/XLSX"* — and `ow_open`'s ends *"never re-Read the file."* The
paragraph asserting "this is the current source, treat it as a `Read` you have already performed" is
prose in the Answer, not a field, because a tabular encoding buys 39-55% on row-shaped results and
**0% on verbatim text**, and it is the prose that stops the second read.

**When omniweave is NOT worth it.** One file, once, that the agent will never cite. Installing a
corpus to answer a question about a file you are about to delete is the wrong trade, and the `ow_add`
tool description should not pretend otherwise.

## 7. What omniweave does when it cannot do its job

L-6 generalises. The framework's single behavioural commitment across every layer is: **a job omniweave
cannot do produces a typed, named, countable state carrying the command that clears it — never a
silent success, never a bare empty result, and never a warning that cannot fail.** This table is the
index of that commitment; each mechanism is owned elsewhere.

| Failure | The typed state | Owner |
|---|---|---|
| A source page could not be read (encrypted, needs OCR, unsupported) | a `diag` row in `ABSENCE_BLOCKING_DIAGS`, so absence gate 9 forces `degraded` with the pages and the fix named | [07](07-store-and-retrieval.md) |
| A retrieval channel was unavailable, off-but-requested, or raised | absence gate 2 plus the per-channel `ChannelStatus` in the `Verdict`; there is no bare `except` around a retrieval channel (INV-12) | [07](07-store-and-retrieval.md) |
| The index was corrupted under us | a fault-injection test corrupts `block_fts` and asserts `degraded`, never `absent` (INV-12, ST9) | [07](07-store-and-retrieval.md) |
| A Driver crashed | `FAILED_PERMANENT{DRIVER_CRASHED}` on **one unit** plus a stderr tail; three crashes in 60 s quarantines the Driver; the run completes (DR11) | [04](04-driver-system.md), [08](08-runtime.md) |
| A capability is missing (no GPU, no binary, no weights) | `probe()` at preflight returns `PROBE_UNAVAILABLE`, the plan is pruned, and the rejection is typed and named — never an `ImportError`, and never `sys.exit` in library code (DR21) | [04](04-driver-system.md) |
| An isolation property was requested and not obtained | `HELLO.isolation_granted` echoed into `degradations[]`; the record appears rather than the claim (DR10) | [14](14-security.md) |
| The budget ran out | exhaustion re-enters `evaluate()` as the evidence key `budget.exhausted`; the `Degradation` message names the knob, and exit code 5 names the approving command | [12](12-performance.md) |
| A re-parse does not match | the generation is **quarantined, not committed**; L3 does nothing; `RebindReport` carries `match_rate_by_page` | [05](05-ingest-and-routing.md) |
| A process died mid-write | `ow test crash-matrix` covers every statement boundary in `Store.complete()`; `ow resume` converges to the uninterrupted result (INV-17, G21) | [08](08-runtime.md) |
| An OUT unit cannot be produced honestly | `UnitOutcome.MANUAL_REQUIRED` with a `ManualReason` from a closed vocabulary, and `GateStatus.MANUAL_REQUIRED` on the release gate | [09](09-generation.md) |
| A gate check could not run | `GateStatus.UNVERIFIED` with `report.skipped_checks[]` non-null — never `passed` (OUT3) | [09](09-generation.md) |
| A confidence signal is not calibrated | an ordinal name plus `(uncalibrated)`; no numeral, percentage, bar, colour or grade (INV-19) | [13](13-quality.md) |
| An event stream backs up | events are dropped, never blocking (a bounded 64k queue, drop-oldest), and the drop count is a `Degradation`, not a log line | [15](15-observability.md) |
| A published number lacks its evidence | `MeasuredOn` is frozen with no defaults, so a missing field is a `TypeError` at construction (`Q-G8`) | [13](13-quality.md) |

Two corollaries a reviewer should apply without argument. First, `skip` is not a state:
`ow eval release-check` refuses on `unknown`, and a warning that cannot fail is a rejectable pull
request (charter §8.22). Second, every override is named per hazard — `--allow-cost`,
`--allow-egress <grant-id>`, `--accept-partial`, `--allow-unexplained-rebind`, `--allow-rebill`,
`--ignore-evidence-cache`, `--allow-abandoned-gen`, `--max-rung`, `--allow-tainted`,
`--accept-manual` — and an override whose scope is "skip whatever complained" is an off switch and
does not exist (charter §6.4).

## 8. The hard part: a corpus that eats its own output

Thesis point 7 is the framework's best idea and it creates the framework's worst hazard. Because a
generated artefact re-enters through `parse/1`, a corpus can contain omniweave's own output; because
`ow_query` retrieves over the corpus, an answer can be grounded in a previous answer's deck; and
because that deck's Blocks carry real cites, the provenance chain *looks* intact while the actual
authority has decayed one generation per hop. Nothing in the collection has this problem, because
nothing in the collection closes the loop. Stated plainly: **the framework must be able to tell "the
contract says X" from "our deck said the contract says X", and it must be able to do so in a filter,
not in a reviewer's head.**

Three mechanisms already exist and are load-bearing here:

- **The provenance is honest at the source.** `read_back` never invents provenance (OUT22):
  `Method.ROUNDTRIP` always, `Quote.RECONSTRUCTED` unless the text was genuinely read from the
  artefact, and `Trust.INFERRED` wherever the target's `kind_map` is many-to-one. So a re-imported
  deck's Blocks are structurally distinguishable from a source contract's.
- **The citation channel is embedded, never inferred.** Inferring a citation from visible text on
  read-back is rejected outright. `artifact_cite` resolves to the original corpus Block or it does not
  resolve, so the chain back to the source survives a hop instead of being re-derived from prose.
- **Retrieval already down-weights it.** `WORTH_QUOTE` scores `Quote.RECONSTRUCTED` at 0.85 and
  `Quote.SYNTHETIC` at 0.70, and `WORTH_TRUST` scores `Trust.INFERRED` at 0.80, so a re-imported
  artefact competes at 0.85 x 0.80 = **0.68** of a source Block's byte share for the same relevance.

One mechanism does not exist, and this document is where the gap is recorded rather than discovered.
`Filters` narrows on `doc_keys`, `uri_prefix`, `formats`, `kinds`, `layers`, `pages`,
`sec_path_prefix`, `lang`, `min_trust`, `min_quote`, `deny_restriction_bits` and `gen` — and on
nothing that names a `Method`. A caller therefore cannot say "answer from source documents only", and
a down-weight is not an exclusion: at 0.68 relative worth, a well-written generated summary still
outranks a badly-scanned source page whose own worth multiplier is lower. **Extends the charter:** [07](07-store-and-retrieval.md) owns
the resolution, the scope commitment here is that one must exist by v1.0, and V10-17 makes it a
release criterion measured by `generated_share` (see New terms). The bias is a `Filters` predicate
over `Method` rather than a new table, a new score term or a new absence gate, because a filter
narrows before channels score and therefore cannot be outvoted by a fusion weight.

## 9. Success criteria

Every criterion below is a number or a named passing test. Adjectives are not criteria. Tiers are
cumulative: v1.0 includes all of v0.1, v2.0 includes all of v1.0.

**Extends the charter.** The charter names only "release 1". The v0.1 / v1.0 / v2.0 tiering below is
new, with **v1.0 == release 1**. Every criterion is anchored to a gate, invariant, budget or deferred
item the charter already owns; nothing here invents a threshold the charter did not state, except
where marked *(new)*. [16](16-roadmap.md) owns the build order that reaches these; this document owns
the acceptance definitions.

### 9.1 v0.1 — the pivot exists and is honest

The IN spine only: L0 acquire (`fs`), L1 parse (office + PDF), L2 `owdoc`, L4 lexical and identity
retrieval channels, and the four listed Actions. No graph, no OUT, no vectors, no model server.

| # | Criterion | How it is measured |
|---|---|---|
| V01-1 | `omniweave-core` resolves to exactly two first-party distributions (`omniweave-core` + `omniweave-ports`) and zero third-party; `omniweave_ports` resolves to itself alone | Gate G1, clean-environment resolve |
| V01-2 | `import omniweave_core` under `-X importtime` loads **zero** third-party modules and neither `asyncio` nor `selectors`; it imports none of `{model, store, archive, retrieve, answer, out, host, toolchain, modelserver}` | Gates G9, G17, G23 |
| V01-3 | `import omniweave_core` ≤ **80 ms**; `ow --version` ≤ **150 ms**; `ow --help` ≤ **250 ms**; driver discovery over 20 installed distributions ≤ **20 ms** (dist-info only, importing nothing) | Gate G10, per-OS baseline, 25% drift; recorded as `import.omniweave_core_ms = 62` and `cold.ow_version_ms = 118` in `eval/perf.toml` |
| V01-4 | A rogue Driver whose module body writes a file and raises `SystemExit` does not run; `ow doctor` exits 0 and the file is absent. A discovery pass over 30 cards adds no driver key to `sys.modules` | Gate G11, DR1 |
| V01-5 | `span_exact_rate == 1.000` over the Blocks that **claim** verbatimness on the fixture corpus; zero Blocks claim `verbatim` without a non-NULL `part.store_ref` | `Q-G6` (hard), `owcheck`'s verbatim-implies-retained-part clause |
| V01-6 | `Locus.reason` is non-`None` iff `quad is None`, over every fixture; `Quad.from_driver` is the only constructor reached; a schema grep finds no `quad` / `bbox` / `poly` column in any L3 table | INV-9, GR1 |
| V01-7 | `import(export(store)) == store` over the fixture corpus | INV-1's export-round-trip check, **`G28`** (ADR-2; the charter's INV-1 row credits `G6`, which is `ow schema emit --check` and is unchanged) |
| V01-8 | The full **fifteen** absence gates are implemented with one fixture per gate and exactly one `return VerdictState.ABSENT` site; a fault-injection test that corrupts `block_fts` yields `degraded`, never `absent` | INV-11, INV-12, ST9, SV8 |
| V01-9 | `ow test crash-matrix`: SIGKILL at **every** statement boundary in `Store.complete()` leaves the store openable, and `ow resume` converges to the uninterrupted result. G21's CI job additionally kill-9s at three random points and asserts store equality against an uninterrupted run | INV-17, gate G21 |
| V01-10 | `store.bytes_per_block` ≤ **660 B** ± 10% on the 5,000-page generated PDF fixture | `eval/perf.toml`, nightly ratchet |
| V01-11 | Peak RSS of the S4 worker that parses the 5,000-page fixture ≤ **1,610,612,736 bytes** (1.5 GiB) + 10%, a one-sided ceiling | `rss.gen5000p_peak_bytes`, `process = "worker"`; anydoc's fork trigger is `rss.office200_peak_bytes` ([ADR-13](adr/0013-v01-acceptance-reconciliation.md) D13.2) |
| V01-12 | `tools/list` for `profile=default, compact_schemas=true` ≤ **1,900 tokens** (`tiktoken cl100k_base`, 5% drift), per-tool ≤ 700, `instructions` ≤ 1,000 chars (both variants; `profile = "full"` has its own 1,100); the **six** file artefacts byte-identical and the `instructions` string held to its frozen `instructions_chars` baseline; no two CLI groups differ only by a trailing `s` | SV2, gate G25 ([ADR-13](adr/0013-v01-acceptance-reconciliation.md) D13.3) |
| V01-13 | `set(listed) ⊆ set(enabled)` and no human-only Action is enabled on an agent surface, checked at startup, else a startup error | SV1 |
| V01-14 | CI: the `gates` job ≤ **3 min**; the `conform` job (the eleven mandatory suites) ≤ **5 min**; `contributor-parity` green in a clean container with **no network, no GPU, no Node**, ≤ **7 min** against a hard ceiling of **600 s** | `Q-G22`; `conform.mandatory_tier_s = 240`, `contributor_parity_s = 420` *(Build note, D970: `tools/ci_job_seconds.py` reads the job timings of master's latest green `ci.yml` run through `gh` and holds `gates`, `conform` and `parity` to 180, 300 and 420 s; on run 39984230165 they took 96, 32 and 9 s. The `parity` job is the light half, and `ci.job_seconds.*` has no writer, so no ratchet holds the timings between runs.)* |
| V01-15 | `first_answer_seconds` ≤ **600 s** *(new)*: on a clean 4-core machine with no GPU, offline after install, the sequence `ow install` → `ow add ~/docs` → `ow query "<question>"` returns an Answer with at least one `cite` that `ow open` resolves, carrying its page wherever the cited page's `page_kind` is not `stream` ([03](03-document-model.md) §12.5), over a folder of 100 born-digital office documents | A scripted acceptance test in `bench/serve/` ([ADR-13](adr/0013-v01-acceptance-reconciliation.md) D13.1); see New terms and V-Q2 |
| V01-16 | `ow doctor` on a store tracked in git **fails** with `OW-S-060`; the shipped `.gitignore` covers `.owstore`, and no `.owstore` is ever a git artefact | ST19 |
| V01-17 | Every format class in §2.1 either has an enabled Driver whose card's `formats` list covers it, or is absent from the shipped scope with a named reason — asserted mechanically against `[drivers] enabled` *(new)*. **`Kind.SECTION` is excluded by name**: it is a member of the closed read vocabulary with no release-1 producer, not a format class, and its vacancy is stated in [drivers](04-driver-system.md) §10.1 (ADR-3 D6) | A test over the card roster, reading `parse.office.anydoc`'s twelve-entry `formats` list ([drivers](04-driver-system.md) §10.1). Closes V-Q6 for v0.1; V-Q7 passes on the same second branch (ADR-8 D8.6) |

### 9.2 v1.0 (== release 1) — the whole loop, gated

| # | Criterion | How it is measured |
|---|---|---|
| V10-1 | Every `G` row in `tools/gates.toml` green and all **27** `Q-G` gates green on the tagged commit; `ow eval release-check` exits 0 with **zero** `unknown` results | The `gates` CI job; `skip` is not a state. The `G` half quotes the register rather than a literal because the series is append-by-ADR (ADR-2); it holds twenty-nine rows, `G1`-`G29`, at release 1. The `Q-G` series is closed at twenty-seven (ADR-11) *(Build note, D971, a user ruling of 2026-10-23: Q-G20, the judge's kappa over 100 double-labelled items, is deferred past v1.0.)* |
| V10-2 | **14** sdists and 14 wheels build on one runner, all `py3-none-any`; no distribution exceeds its `tools/weights.toml` ceiling; `omniweave[recommended]` (`serve + pdf + target-pptx`) ≤ **250 MB** installed; `omniweave-vision` prints its resolved installed size during `ow doctor` | Gate G2, the `build` job |
| V10-3 | Accuracy floors, all slices, from `eval/gates.toml`: `structure_f1` ≥ **0.90** (guard 0.010) on `office/*` and ≥ **0.85** on `pdf/born_digital/*`; `order_acc` ≥ **0.75** (guard 0.015) on `pdf/born_digital/*`; `table_rel_acc` ≥ **0.70** (guard 0.020) on `*/has_merges=1`; `citation_soundness` ≥ **0.995** (guard 0.002); `doc_acc` ≥ **0.20** (guard 0.020) on `fields/*` | The eval harness. `order_acc`'s floor is sourced: marker's own annotation records a pdftext char-stream reading order at 75% against a learned head's 56% on olmOCR-Bench order tests (`marker/marker/builders/line.py:77-85`), and we may not ship below the free baseline |
| V10-4 | Honesty ceilings: `hallucination_rate` ≤ **0.02** (guard 0.005); `false_confident_zero` ≤ **0.01**; `degradation_detection` == **1.000** (hard); `citability_violations` == **0** (hard) | `eval/gates.toml`; `Q-G7` *(Build note, D964, a user ruling of 2026-10-23: `degradation_detection` is measured over the built Injectors, and the damage the other nine model is disclosed as features this build does not have.)* *(Build note, D971, a user ruling of 2026-10-23: `hallucination_rate` is not applicable at v1.0. It is defined over field extraction, and no field-extraction driver ships: `parse.fields.lift` is a tombstone with no successor.)* |
| V10-5 | Every published number carries `(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)`; a `MeasuredOn` missing a field is a `TypeError`; a confidence whose `Calibrated.status != "calibrated"` renders no digit, percentage, bar, colour or grade | INV-19, `Q-G8`, `Q-G14` |
| V10-6 | Performance: `ow query` warm p50 ≤ **180 ms** (±20%) under the G10 ceiling of **250 ms**, with the five channel budgets summing to **210 ms** (`identity 15 + exact 25 + lexical 50 + structural 40 + semantic 80`) against `[retrieval.budget] query_ms = 250`, and `ow route lint` refusing a sum ≥ `query_ms`; `parse.office` p50 ≤ **5 ms**; `wal.bulk_index_peak_bytes` ≤ **2 GiB** absolute; `rss.merged4mcell_peak_bytes` ≤ **4 GiB** | `eval/perf.toml`, nightly, time as a Pacer ratio on the pinned runner `ow-bench-1` against a 7-run rolling median, failing on 3 consecutive runs above tolerance *(Build note, D964, a user ruling of 2026-10-23: the 4M-cell sheet is a declared v1.0 limitation (F2); anydoc's `max_xml_nodes` and the office worker's memory stay as shipped.)* |
| V10-7 | Scale: a nightly **100k-roster** run with peak claimable ≤ `queue_high_water`, supervisor RSS ≤ **600 MB**, and ≥ **2,000** work transitions/s | Gate G22 |
| V10-8 | Incremental converges to full: a **300-document** fixture under **40** scripted mutations produces `.owdoc` exports identical to a full rebuild; the graph-specific run is 60 documents / 20 steps | INV-18, gate G19, GR8 *(Build note, D964, a user ruling of 2026-10-23: "identical" is content identity, the same blocks with every cite resolving, which G19 fails on; generation and revision counters are parse history and excluded, and `--strict` (D187) stays a report.)* |
| V10-9 | Three Targets (`pptx`, `deck`, `docx`) reach `GateStatus == passed` on the OUT conformance suite; `video` ships with `[compile] implemented = false` and `ow out targets` prints the reason; `bake` is `unavailable` on every target with both exits named in the error | Charter §D8 |
| V10-10 | Round-trip: two compiles of the 40-unit golden fixture are equal at `part` determinism on all **9** OS/Python cells; every `artifact_cite` row from a corpus-sourced artefact resolves; `read_back` stamps `Method.ROUNDTRIP` and passes the ~120-test testkit unchanged | F16 must close before the OUT phase's week 8; a failure moves the declared floor to a normalized-part class as a **card-visible** downgrade *(Build note, D968: every clause is measured. Both reader cards, docx's and pptx's, pass the conformance kit's mandatory tier over their own compiled goldens; pptx's `licence` clears since D884 admitted Pillow's MIT-CMU, which D879 had found failing.)* |
| V10-11 | Contract compatibility: the previous **two** releases' conformance-template Drivers load against HEAD | Gate G16 |
| V10-12 | **At least one Driver authored outside this repository passes the eleven mandatory conformance suites**, and `ow conform --bench` writes its `[quality]` block with four kit-written keys and a complete `MeasuredOn` *(new)* | A named external Driver in the release notes. This is the criterion that decides whether the Port design is real; see V-Q4 *(Build note, D967, a user ruling of 2026-10-23: the evidence is an independent SubRip driver that shares no code with the template, passing 11/11 from a copy outside the checkout, run from its own directory; a third party's run comes after release.)* |
| V10-13 | Money reconciles exactly: `ow cost --by driver` equals the run manifest's spend rows to **0 micros**, and `cost.would_have_been_micros_if_uncached` is present in every run manifest | INV-15; `rebilled_units` is an **exact** counter *(Build note, D964, a user ruling of 2026-10-23: the free segment and derive passes are host-metered but write no spend row, since `route_spend` keys on a `route_decision` a free pass does not have (D665); their spend is out of v1.0's scope and disclosed, and a `pass_spend` table comes after.)* |
| V10-14 | Determinism of the frozen golden: `shape` is byte-identical across two pdfium minors × **9** OS/Python cells | `Q-G4`; rests on F31, which must close **before** the golden suite freezes *(Build note, D966, a user ruling of 2026-10-23: the second pdfium minor is one nightly cell beside the nine at the locked minor; 152 and 153 matched locally.)* |
| V10-15 | `ow install` records every written path with its post-write sha256 in an install receipt, and `ow uninstall` reverses exactly that under a **byte-identity** CI gate | Charter §D9 *(Build note, D971: G35 is law, by ADR-16, accepted on 2026-10-23 (a user ruling); its D16.3 makes the fixture home the gate's definition.)* |
| V10-16 | The harness scores a set of deliberately wrong outputs (a dropped page, a transposed table, a fabricated quote) and asserts the exact expected scores | `Q-G23` — the eval code is itself tested |
| V10-17 | A caller can restrict retrieval to Blocks whose `Method` is not `ROUNDTRIP`, and `generated_share` is reported on every `Verdict` *(new)* | The §8 resolution owned by [07](07-store-and-retrieval.md); a fixture corpus containing its own compiled deck asserts `generated_share == 0.0` under the restriction and `> 0` without it |

### 9.3 v2.0 — scale, federation, and the first rendered digit

| # | Criterion | How it is measured |
|---|---|---|
| V20-1 | **T2**: the full WAL valve plus an ANN `VectorBackend` that clears gate G3 and ships pure wheels for 9 cells; recall@10 of `sig → top-1000 → f32 rerank` ≥ **0.95** against exhaustive f32 on the fixed 50k fixture | F9, F10; below 0.95 the stdlib backend ships `sig_full` only, with a smaller ceiling, and `vector.brute` plus the 250k refusal stands |
| V20-2 | **50M Blocks** in one `.owstore` at ≤ 660 B/Block ± 10% — a **33 GB** store by arithmetic (50e6 × 660 B) — with `ow query` warm p50 ≤ **250 ms**, the G10 ceiling, at that size *(the latency figure is a target, not a measured budget: `query.warm_p50_ms = 180` is recorded on the fixture corpus, not at T2 scale)* | Conditional on F1: if dense corpora land at ~300 Blocks/page, T2 arrives at 5M Blocks and this row is refit rather than defended |
| V20-3 | **T3**: a Postgres backend behind the same four protocols with **zero Operator changes** — the acceptance test is that `tests/store/` runs unmodified against both backends and G19 passes on both | Charter §D5's scale tiers; the 16-bit minting prefix already ships at shard 0 so this cannot become a migration (F28) |
| V20-4 | **T4**: a two-shard federation where the absence suite passes with one shard deliberately unreachable, and every federated `Verdict` carries `fusion_kind = "rank_merge"` and `shards_contributed` | F35 |
| V20-5 | **At least one confidence signal reaches `status == "calibrated"`** — ordinal separation under `Q-G11` (strictly increasing `p_hat`, non-overlapping adjacent Wilson intervals, n ≥ 150/bucket/slice) or probability sharpness under `Q-G12` (ECE ≤ 0.05, Brier ≤ 0.08, 10 equal-mass bins, n ≥ 1000) — so the framework renders its first numeral | INV-19, F22, F23; until then every badge stays dark and the internal-filter clause keeps the review surface alive |
| V20-6 | **≥ 5 third-party Drivers across ≥ 3 Ports** in the static `omniweave-index` card-stub index, each attested, each with a kit-written `[quality]` block | Installed by digest into `$OMNIWEAVE_HOME/` and re-verified on every use; a digest mismatch is a permanent failure that never triggers a fetch |
| V20-7 | The `video` Target moves to `implemented = true` with a declared `ArtefactDeterminism` of at least `frame` | Charter §D8; requires the hyperframes mining that was never written |
| V20-8 | Every one of the **41** deferred items F1-F41 is either closed with a measurement or explicitly re-deferred with a new closing measurement and a review date | Charter §7; `Q-G17` already fails any gate row past its `review_by` |
| V20-9 | F27 (multi-tenancy) is closed by a recorded decision, implemented or not | NG-8 stands until it is |

## 10. The definition of failure

> **omniweave has failed and should be stopped if, after v1.0, an agent with omniweave installed still
> opens the source file with a host tool to check an answer it just received — because the entire
> apparatus of Blocks, polygons, `Trust` tiers, absence gates and cite carrying exists for no other
> purpose than to make that second read unnecessary, and if the second read persists then the
> apparatus is cost without benefit and no amount of additional invariants will change it.**

This is measurable, and the instrument already exists. The 30-task `bench/serve/` harness with a
scripted agent (F19's instrument) counts, per task, whether a host `Read`, `Grep` or shell `cat` of an
**indexed** source file occurs after an `ow_query` or `ow_open` in the same task. That ratio is
`source_reread_rate` (see New terms). The stop condition is `source_reread_rate > 0.25` on the
harness at v1.0 with no identified and fixable cause — a quarter of the time, the agent did not
believe us, and the honest conclusion is that the Answer is not doing the job the charter designed it
to do.

**The instrument's own failure mode, stated so it cannot be exploited.** `ow_query`'s and `ow_open`'s
tool descriptions and the Answer's "treat this as a `Read` you have already performed" paragraph exist
precisely to suppress the behaviour the metric counts, so the metric can be driven down by prompt
engineering that makes the agent stop checking rather than by provenance that makes checking
unnecessary. The harness therefore reports two numbers and gates on both: `source_reread_rate`, and
the fraction of harness tasks whose final answer is **wrong** — a re-read the agent skipped because
it was told to, over a `degraded` verdict it should have acted on, is a worse outcome than the
re-read. A run in which `source_reread_rate` falls and task accuracy falls with it is a failing run,
not a passing one. [13](13-quality.md) owns the harness; this document owns the pairing rule.

Three failures that are explicitly **not** stop conditions, because each has a pre-committed
degradation rather than an exit (see §2.5):

- **`vectors = "off"` is still the default at v1.0.** Most first runs get four channels and a
  `Verdict` that says `semantic: off`. That is a visible product limitation and the correct one; the
  alternative is a five-second query or numpy in core.
- **No confidence signal is calibrated at v1.0.** Then nothing renders a digit. INV-19 already
  requires that, and the internal-filter clause keeps `Trust` and `Quote` usable as sort keys.
- **`verbatim` is unreachable on the office path at release 1.** Disclosed by
  `corpus_card.verbatim_fraction` before any query runs, with the fork trigger named.

## 11. Open questions

Numbered `V-Q` so downstream documents can reference them. Each names what closes it. Charter §7's
F1-F41 are not restated here; only questions this document's own subject raises.

- **V-Q1 — Is `source_reread_rate > 0.25` the right stop threshold?** The number is chosen, not
  measured: nothing in the collection reports an agent's file-re-read rate against a
  provenance-carrying retriever. *Closes:* the first full `bench/serve/` run at v0.1, reporting the
  distribution rather than the mean, split by whether the task's source was born-digital or scanned,
  and paired with task accuracy per §10. *Pre-committed fallback:* if the v0.1 baseline is already
  above 0.25 for reasons unrelated to trust (host tools invoked by reflex, a system prompt that
  mandates `Read`), the threshold is re-anchored to *relative* improvement — a 60% reduction against
  the no-omniweave control — and the absolute number is dropped.
- **V-Q2 — `first_answer_seconds ≤ 600` is unvalidated.** It is a product-adoption promise with no
  measured basis: nothing in the collection reports install-to-first-cited-answer. *Closes:* the
  V01-15 acceptance test on V01-15's own folder of 100 born-digital office documents (`bench/serve/first_answer.py`), with `first_answer_seconds` over each of the three reference
  corpora reported beside it and gating nothing ([ADR-14](adr/0014-reference-corpora-and-control-arm.md) D14.5). *Fallback:* if the dominant term is model
  download rather than parse, the criterion splits into `install_seconds` and `first_answer_seconds`
  and only the second is gated.
- **V-Q3 — Is the non-agent (SDK/HTTP) user a first-class target or a documented side effect?** §4.4
  asserts first-class and the import DAG supports it, but no gate measures the SDK path. *Closes:* a
  decision in [10](10-interfaces.md) on whether the SDK gets its own conformance suite. *Bias:* it
  should, because "three surfaces, one implementation" is otherwise a claim with one enforcer (G4)
  that checks imports rather than behaviour.
- **V-Q4 — Charter gap: no release criterion names an external Driver.** The charter builds the entire
  Port, DriverCard, testkit and attestation apparatus for third parties, and gate G16 checks contract
  compatibility against *our own* conformance-template Drivers. Nothing requires that a real external
  Driver has ever passed. V10-12 adds it; it needs ratification into the charter or an ADR, because if
  it is not a release criterion the ecosystem claim is untested at v1.0.
- **V-Q5 — Charter gap: `Filters` cannot express "source documents only".** §8's hazard is created by
  thesis point 7 and the charter ships no filter predicate over `Method`, only a `WORTH_QUOTE` and
  `WORTH_TRUST` down-weight that a strong generated summary can out-earn. V10-17 makes it a release
  criterion and [07](07-store-and-retrieval.md) owns the shape. *Closes:* a `Filters` field plus the
  self-ingesting-corpus fixture. *Bias:* a filter, not a score term — a filter narrows before channels
  score and therefore cannot be outvoted by a fusion weight.
- **V-Q6 — Charter gap: HTML and email are named as inputs with no implementation.** Charter §1's
  first sentence lists "email, HTML" among the inputs; neither appears again anywhere in the charter —
  no enabled Driver, no `formats` entry on any card, no gate slice, no fixture class, no Lane. §2.1
  therefore records them as out of the shipped surface. **Answered by ADR-8 D8.6**: charter §1 is
  **not** amended — its opening sentence states what omniweave is *for*, §2.1 states what it *ships*,
  and the two differing is the shape of a v1 release rather than an error. `V01-17`'s second branch,
  "absent from the shipped scope with a named reason", is written for exactly this and passes on the
  row as it stands, which is what makes the divergence mechanical rather than editorial. *Closes for
  real:* a first-party `parse/1` Driver with a card entry, a gate slice and a fixture class. Until
  then, no plan document may assume an HTML or email ingest path exists.
- **V-Q7 — Charter gap: audio and video ingest are in the project's purpose and not in the charter.**
  The framework's stated purpose covers audio and video in both directions; the charter's input
  surface does not mention either, `audio` and `video` appear only as OUT asset roles, and there is no
  transcription Lane. §2.1 records them as out of scope at v1. **Answered by ADR-8 D8.6 as a v2.0
  anchor with a named precondition**, not as an open question: a `parse` Lane for time-based media is
  not a Driver question until the model can address time. `Locus.precision` has no temporal member and
  `OriginSpan` has no time branch, so the precondition is a **`SCHEMA` major proposal** under charter
  §6.6's two-release window, and `R-T1` prices a structural model miss as the most expensive outcome
  in the plan. *Closes:* that proposal landing. Until it does, `V01-17` passes on its named-reason
  branch, and audio and video are third-party Drivers with no first-party support and no gate.
- **V-Q8 — answered by ADR-2. Charter defect: gate G6 had two definitions.** The charter's INV-1
  enforcer column named G6 as "`import(export(store)) == store` over the fixture corpus"; the gate
  table's G6 row reads "`ow schema emit --check` byte-diff, CRLF-normalised" with LEANN's `llms.txt`
  as the defect it catches — and LEANN's `llms.txt` is G25's named defect. **ADR-2 numbers the
  archive round-trip check `G28`** and leaves `G6` as `ow schema emit --check`, which is what the
  gate table, INV-20's enforcer list, `ST17` and [11](11-repo-layout.md)'s `.gitattributes` comment
  already say; renumbering the correct citation to fix the incorrect one would invert the repair.
  Charter `:72` is superseded by erratum `E31`; the sole home for INV-1's enforcer column is
  [01](01-principles.md) §INV-1. V01-7 names `G28`, and a downstream document may now cite the
  number.
- **V-Q9 — answered by ADR-8. Charter defect: two verified counts are off by one and one card list is
  short.** (a) Charter §D3's anydoc card note says anydoc's `Block` is "nine variants" and then
  enumerates eight; the enum at `anydoc/src/model/block.rs:5-38` has eight (`Heading`, `Paragraph`,
  `List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`, `Math`). The conclusion the note draws — no
  per-block source address, only `Asset.origin_part` at `anydoc/src/model/asset.rs:15`, therefore
  `origin_span = none` — is verified and unaffected. (b) The same card's `[capability] formats` lists
  five media types (wordprocessingml.document, ODT, RTF, EPUB, CSV) while `PageKind` ships `SLIDE` and
  `SHEET`, the packing constants budget a 4M-cell workbook, and `rss.merged4mcell_peak_bytes` is a
  nightly gate — so PPTX, XLSX, ODS and ODP are load-bearing everywhere except in the one list that
  would authorise them; as printed, `resolve()` filters `pptx` out on `format in capability.formats`
  and `ow parse deck.pptx` returns `FORMAT_UNSUPPORTED`. **Resolved**: **ADR-8 D8.1** rules the enum
  eight, and **D8.2** widens the card to **twelve** media types, one per token `decode.office-native`
  routes. Sole home of the media types is [04](04-driver-system.md) §10.1 and of the tokens
  [05](05-ingest-and-routing.md) §4.4, held equal by `ow route lint` check 11; §2.1's office row names
  the twelve. anydoc's own "fourteen formats" is a **benchmark denominator**, not a served-format
  count, and no plan document may cite it as one again. Charter errata pending on `:1748` (`E66`) and
  `:1738-1740` (`E68`).
- **V-Q10 — Author's note, not a contradiction: `_index/framework-blueprint.md` is written in
  vocabulary the terminology lock rejects.** Its L1 router diagram names escalation levels with a
  numbered tier scheme the lock replaces with `Rung` × `Lane`, on the stated ground that a number
  conflates spend with capability. `_index/` is not a plan document and so is outside G27c's check,
  but a downstream author who reads it for background must not import the rejected labels along with
  the ideas. No plan document may reproduce that diagram or its labels.

One near-miss worth recording, resolved rather than open: charter §1 lists nine non-goals and §7 lists
F27 (multi-tenancy) as deferred with the pre-committed answer "v1 is store-per-tenant". These are
consistent — NG-8 states the non-goal and cites F27 as the open item — but a reader skimming §7 alone
could read "deferred" as "possibly in v1", which it is not. NG-8 closes that reading.

## 12. New terms

Three coined here, for merge into [`_notes/terminology.md`](_notes/terminology.md) §2.

| Term | Kind | Definition |
|---|---|---|
| `source_reread_rate` | concept | The fraction of `bench/serve/` harness tasks in which the scripted agent opens an **indexed** source file with a host tool (`Read`, `Grep`, a shell `cat`) *after* an `ow_query` or `ow_open` in the same task. The framework's single adoption metric and the instrument behind the definition of failure (§10). Measured by the same 30-task harness F19 uses; reported as a distribution, sliced by born-digital versus scanned source, never as a bare mean, and **always paired with the harness's task-accuracy number**, because suppressing the re-read by instruction rather than by provenance moves this metric the wrong way for the right reason. |
| `first_answer_seconds` | concept | Wall time on a clean 4-core, GPU-free machine, offline after install, from the start of `ow install` to the return of an `ow query` Answer carrying at least one `cite` that `ow open` resolves — with its page wherever the cited page's `page_kind` is not `stream` — over a folder of 100 born-digital office documents. A v0.1 acceptance criterion (V01-15), budgeted at 600 s. Distinct from the G10 cold-start budgets, which measure a warm store; this measures the whole first-run path including ingest. |
| `generated_share` | concept | The fraction of a `Response`'s evidence characters whose producing Block has `Method.ROUNDTRIP` — that is, the share of an answer that came from omniweave's own compiled output rather than from a source document. [07](07-store-and-retrieval.md) §6.7 owns the arithmetic: the denominator is `Response.hits`, **not** a rendered Answer's characters, because a number that moves with `Answer.render(max_chars=…)` is not provenance. Reported on every `Verdict`; the instrument for §8 and for V10-17. A corpus that has never ingested its own artefacts reports `0.0`; a value above zero is not an error, but an answer whose `generated_share` exceeds its source share is a fact the caller must be able to see and to filter on. |
