# omniweave — the plan

**In one paragraph.** This directory is the complete design of **omniweave**: a Python framework that
turns a folder of real documents into one queryable, citable corpus and compiles new artefacts back
out of it without losing the thread to the source. Nineteen specification documents, 44,702 lines,
written against one binding [charter](_notes/charter.md) and one binding
[terminology lock](_notes/terminology.md), which are themselves the harmonised output of ten
adversarial design panels over the ten hardest architecture decisions. The decisions are settled; the
documents expand them into implementable detail with real type signatures, real SQL, real config keys
and real numbers. This file is the entry point: what omniweave is, the ten decisions with links to
their rulings, a table of all nineteen documents with three named reading paths, what is decided
versus deferred, and where every idea came from.

## 1. omniweave in one page

> **Thesis.** One document model in the middle, with provenance and confidence on every block; parsers
> are drivers that populate it, indexes are views over it, generators compile out of it, and the
> framework's only irreplaceable job is to route work by evidence and cost, and to carry provenance
> across the whole loop.

**The problem, stated as a mechanism.** The parse step of nearly every stack in production converts a
structured intermediate into a string, and the string is what travels downstream. Somebody's code held
a polygon, a page number, a cell coordinate and an OCR confidence, and a `to_markdown()` call threw
all four away in one line. Measured across the twenty-two repositories in `_index/` (`_index/README.md`, not published):
only four of eleven parsing repositories expose anything beyond a markdown string. markitdown's entire
return type is a string and an optional title
(`markitdown/packages/markitdown/src/markitdown/_base_converter.py:5-25`). Nothing in that type tells a
caller a page number was available and dropped. Five things die at that seam — spatial provenance,
section containment, table semantics, per-Block confidence, and any path from a generated artefact back
to the bytes it came from — and they die silently, so the caller learns what was forfeited only when an
answer turns out to be wrong.

**What omniweave is.** Fourteen `py3-none-any` distributions arranged as one directed acyclic import
graph with a single pivot: `omniweave_core.model` (L2, **`owdoc`**). Everything below the pivot populates
it through host-side sinks; everything above it is a view over it or a compiler out of it. One
distribution holds the driver-facing vocabulary and depends on nothing (`omniweave-ports`); one owns the
store, the retrieval engine, the answer renderer and the OUT framework (`omniweave-core`, zero
third-party dependencies, synchronous); one owns the event loop, the router and the surface registry
(`omniweave`); eleven are drivers, targets, the MCP server or the conformance kit.

**The shape, in six sentences.** A `.owstore` SQLite file per corpus holds L2's Block table, L3's
`owgraph`, L4's five retrieval channels and the operational tables — one store, never a model plus a
sync layer. Every replaceable part is a **Driver**: one implementation of one of five **Ports**
(`acquire`, `parse`, `derive`, `embed`, `compile`), described by a `driver.toml` **DriverCard** the host
reads with `tomllib` and never imports. A **router** turns a flat, versioned `Evidence` record for one
`(unit, part)` into a `Rung` × `Lane` decision written to an immutable `route_decision` row *before* any
driver runs, so escalation is per part, monotone, and a clean born-digital page costs nothing. Retrieval
fuses five channels by weighted RRF at one key, `block_id`, and returns a **`Verdict`** in which
`absent` is reachable only after fifteen absence gates. The OUT direction compiles a declared subset of
an existing text format (an **IL**: carrier + `constructs.toml` + RulePack) through a ten-value
`GateStatus` into real PPTX/DOCX/deck bytes. And the loop closes: a compiled artefact re-enters at L1 as
an ordinary `parse/1` driver (`read_back`), so a generated deck is a citable corpus document with
`Method.ROUNDTRIP` provenance.

**The architecture diagram**, taken verbatim from
[system architecture](02-architecture.md) §1.2 so the two cannot disagree. Read it as three things at
once: **layers** (L0–L6, left gutter), **distribution boundaries** (the boxes; one box is one wheel),
and **seams** (S1–S4 — the only four places control leaves the host process).

```text
 +- L5 RUNTIME -- omniweave/{plan,run,route,graph}/ --------------------------------------+
 | plan/            Resolution x RouteDecision -> `work` rows carrying the denormalised   |
 |                  dispatch_key = sha256(driver_id||config_digest||isolation)[:16]        |
 | run/discover.py  L0 ACQUIRE (fs): the `unit` roster + CAS blobs, plan_batch = 512/txn  |
 | run/expand.py    op.identify -> unit.part_count, gated by the water mark               |
 | run/supervisor.py ONE asyncio loop: claim -> admit -> dispatch -> complete -> reap;    |
 |                  TaskGroup for STRUCTURED SHUTDOWN ONLY                                |
 | run/dispatch.py  Batch formation · AIMD · crash quarantine · Sequence sessions         |
 | run/pipeline.py  THE MIDDLEWARE ORDER; the ONLY caller of DriverHost.invoke() (G8)     |
 | run/converge.py  op.converge: the anchor_delta, the dep delta, the attribution guard   |
 | run/manifest.py  {output_root}/runs/{run_id}.json                                      |
 | route/           evidence.py · eval.py (PURE) · admit.py · spend.py   -> see doc 05    |
 | graph/           op.lexicon · op.resolve · op.cluster                 -> see doc 06    |
 +---+-------------------------+----------------------------------+---------------------+-+
     | Requirement             | Batch                            | StepResult          |
     v                         v                                  ^                     |
 +- omniweave_core.drivers --+ +- omniweave_core.host ----------+  |                     |
 | discovery.py -> Catalog   | | inproc.py  DriverGuard         |<-|--- S1  in-process   |
 |   (metadata only, INV-4)  | | subproc.py one worker per      |  |     FFI, office only|
 | card.py    DriverCard     | |   (driver_id, config_digest)   |<-|--- S4  0600 UDS or  |
 | resolve.py resolve() PURE | | wire.py    FRAMING ONLY (~80   |  |     a named pipe    |
 | policy.py  licence.py     | |            lines, fuzzed)      |  |                     |
 | tombstones/               | +---------------+----------------+  |                     |
 +------------^--------------+                 | HELLO INVOKE      |                     |
              | driver.toml READ,              | RESULT CANCEL     |                     |
              | NEVER imported (INV-4)         v                   |                     |
 +- L1 PARSE / L3 DERIVE DRIVERS -- ports-only, no core edge (G4 rule 3) ----------------+ |
 | omniweave-office   parse.office.anydoc                                    <- S1       | |
 | omniweave-pdf      parse.pdf.pdfium                                                   | |
 | omniweave-vision   parse.page.olmocr                           (io.service) <- S3     | |
 | omniweave-graph    derive.segment.spine · derive.anchor.{native,defterm} ·             | |
 |                    derive.xref.{native,pattern} · derive.entity.{table,gazetteer}      | |
 | omniweave-llm      derive.{merge,entity,claim,report}.llm      (io.service) <- S3     | |
 +--------------------------------+------------------------+----------------------------+ |
                                  | owdoc-fragment/1       | owgraph-items/1             |
                                  v                        |                             |
 +- L2 MODEL -- omniweave_core.model + .store + .archive ---|-----------------------------+
 |  *** THE PIVOT. Nothing bypasses it. ***                 |                             |
 |  DocSink (11 methods, HOST-SIDE) -> doc · page · block · part · asset · rel · grid ·   |
 |                                     mark · diag ;  end_page() commits ONE transaction  |
 |  store/sqlite.py  THE ONLY sqlite3.connect (INV-17) · ONE store thread · the WAL valve |
 |  archive/         the `.owdoc` codec — a plain ZIP of ZIP_DEFLATED NDJSON Frames       |
 +--+--------------------------------------------------------------------+-----------------+
    | Doc (lazy handle) · Reader.snapshot() -> Snapshot                  | GraphSink
    v                                                                   v  (12, host-side)
 +- L4 INDEX -- omniweave_core.retrieve -----------+   +- L3 STRUCTURE -- `owgraph` --------+
 | plan.py   plan()  PURE, memoised               |   | segment · segment_block            |
 | channels/ identity · exact · lexical ·         |<--+ anchor · ref_site · block_link     |
 |           structural · semantic                | seg| entity · entity_alias · mention   |
 | fuse.py   RRF at RRF_K = 60 · ceiling()        |lift| edge · edge_evidence · claim      |
 | verdict.py Verdict, ONE `ABSENT` return site   |   | community · community_report        |
 | expand.py BFS over block_link ONLY             |   | quarantine (rejected drafts, kept)  |
 +--+---------------------------------------------+   +------------------------------------+
    | Response = (hits, Verdict, Spend)
    v
 +- omniweave_core.answer ------------------------------------------------------------------+
 | worth.py -> allocate.py -> dedup.py -> untrusted.py -> render.py                         |
 | the Answer document: <= HARD_CEILING = 24,000 chars, one content block, `ow:` markers    |
 +------------------------------------------------------------------------------------------+

 +- L6 OUT -- omniweave_core.out (framework) + omniweave-target-* (targets) ----------------+
 | compile.py CompileV1   constructs.py ConstructTable   rules.py RulePack + run_pack()     |
 | gate.py GateStatus (10, exactly one permits a release)   plan.py Plan/Unit/UnitOutcome   |
 | carrier/{xml,html}.py CarrierDoc   ledger.py AssetLedger   marker.py the OWC1 grammar    |
 | opc.py THE ONLY zipfile-for-write in the framework   receipt.py   roundtrip.py r1..r7    |
 | job.py the JobDir layout — also the S2 data plane                                        |
 |  +--------------------+--------------------+-------------------+-------------------+     |
 |  | target-pptx        | target-docx        | target-deck       | target-video      |     |
 |  | owsvg/1  · svg     | owflow/1 · html    | owdeck/1 · html   | owmotion/1        |     |
 |  | compile.pptx.native| compile.docx.native| compile.deck.     | implemented =     |     |
 |  | parse.pptx.native  | parse.docx.native  |   native  <- S2   |   false           |     |
 |  +--------------------+--------------------+-------------------+-------------------+     |
 +---------------------------+--------------------------------------------------------------+
                             | read_back: artefact -> owdoc-fragment/1 -> back into L2
                             +-------------------------------> (the loop closes at L1)

 +- QUALITY (never on the runtime path) -- omniweave-conform -------------------------------+
 | testkit/ ~120 property tests   suites/ 12 conformance suites   eval/ harness · reducers  |
 | Cassette codec · calibrator · scoreboard generator                                       |
 | compile.text.owtext — the reference target that falsifies "one impl wearing an interface" |
 +------------------------------------------------------------------------------------------+

 THE FOUR SEAMS, AND THERE IS NO FIFTH (charter §3.4)
 S1  in-process FFI     omniweave-office only, one call per document, py.detach for the decode
 S2  Toolchain child    omniweave_core.toolchain — omniweave-target/1 NDJSON on stdio, a job
                        directory as the data plane. Never HTTP, never a socket.
 S3  model server       omniweave_core.modelserver — attach-or-spawn, a 32-byte token in a 0600
                        sentinel, loopback HTTP (one of exactly two sanctioned endpoints)
 S4  subproc DriverHost omniweave_core.host.subproc — omniweave-driver/1 over a 0600 unix socket
                        or an owner-only named pipe. Never a daemon, never loopback TCP.
```

**What omniweave is not.** Not a chat product, an agent or a UI. Not a markdown pipeline — no model
class has an `html`, `markdown` or `md` field, and a build-failing test asserts it. Not a workflow
engine, scheduler or broker — no daemon, no loopback control listener, no second durable store that
must agree with the `work` table. Not a vector database, graph database or search engine. Not a model
trainer and not a model host beyond attach-or-spawn — omniweave ships no weights. Not multi-tenant at
v1. Not a compiled-code owner: exactly one compiled dependency exists (`firecrawl-anydoc`), it is
someone else's published `abi3` wheel, and we do not build it. The full list is
[vision](00-vision.md) §5.

## 2. The ten decisions

Each decision was argued by three independent architect proposals
([`_notes/panels/`](_notes/panels/)), ruled on adversarially, and then harmonised into
[`_notes/charter.md`](_notes/charter.md) §4, which **supersedes a ruling wherever the two conflict**.
The ruling file carries the decision, every rejected alternative with the reason, and the consequences
— which is what an ADR would carry, plus the alternatives reasoning. There is no separate ADR set.

| # | Decision | Ruling |
|---|---|---|
| **D1** | Python 3.11+, one repository, one `uv` workspace, one lockfile, **fourteen** `py3-none-any` distributions on a shared `RELEASE`, whose foundation `omniweave-core` has zero third-party dependencies and exactly one first-party one (`omniweave-ports`). Exactly one compiled dependency exists and we do not build it: the MIT `abi3` wheel `firecrawl-anydoc`, vendored at a recorded SHA behind a written fork trigger. TypeScript exists only as digest-pinned **Toolchains** invoked as a child process, so no `pip install` ever pulls Node. No Rust kernel, no cross-language model, no IDL — the language-neutral contract is *generated* JSON Schema, committed and byte-diff gated. | [D1-substrate](_notes/rulings/D1-substrate.md) |
| **D2** | omniweave defines its own normative model, **`owdoc`**: a flat append-only **Block** table with one containment spine (`parent_id` + `ord`, where `ord` *is* the reading order) plus a closed seven-member `rel` table, canonical in the `.owstore` and interchanged as a `.owdoc` plain ZIP of deflated NDJSON Frames. `DoclingDocument` is an importer and an export target behind an extra, never a base class. Four identities with four jobs (`block_id`, `addr`, `cite`, `content_digest`), three coordinate systems the type system refuses to mix (`OriginSpan`, `TextSpan`, `RenderSpan`), table cells are ordinary Blocks, and no type anywhere has an `html` field. Re-parse identity is an explicit `rebind()` pass that carries the `cite` and quarantines a low-match generation. | [D2-docmodel](_notes/rulings/D2-docmodel.md) |
| **D3** | Every replaceable part is a **Driver**: one implementation of exactly one of five **Ports** (`acquire`, `parse`, `derive`, `embed`, `compile`), shipped as its own distribution, described by a `driver.toml` **DriverCard** the host reads **without importing a single line of driver code**. A Service and a Backend are deliberately not Ports. `resolve()` is pure and returns admitted candidates plus every rejection with a typed code — it never picks a winner. A driver receives `DriverIO` and nothing else. Licence *facts* live on the card and the *tier is computed by core*, so an author cannot mislabel; `restriction_bits` travel to every derived item. `omniweave-conform`'s thesis: **the card is the test plan**, and the kit — not the author — writes `[cost.measured]` and `[quality]`. | [D3-drivers](_notes/rulings/D3-drivers.md) |
| **D4** | Routing is **data, not code**: a first-match-wins ordered list of `[[rule]]`s in TOML across six merge layers, evaluated by a pure function over a flat versioned `Evidence` record. The predicate grammar is closed comparisons only, and an unavailable signal evaluates UNKNOWN under Kleene semantics, forcing every rule over a nullable key to declare `on_unknown`. Escalation is monotone in a closed seven-value `Rung` crossed with an open `Lane` registry — numbered tiers are rejected because a number cannot express a cheap high-capability driver. Every decision records its **read set**, so it replays byte-for-byte and a candidate policy re-scores over history for $0. Cost is a seven-unit physical `Spend` vector no driver may price; **budget never changes which rung is chosen, only whether it runs**. | [D4-router](_notes/rulings/D4-router.md) |
| **D5** | SQLite is the **published read interface and the swappable write implementation**: one `.owstore` per corpus plus exactly two derived, separately-deletable sidecars (`index.vec.owstore`, `events.owstore`), so no query process ever needs a write handle. Retrieval is **five channels** — `identity · exact · lexical · structural · semantic` — fused by weighted RRF at one key, `block_id`, with a `ceiling()` sharing one weight function with `fuse()`. The planner is pure and its narrowing is a closed three-way choice decided by an exact `LIMIT PREFILTER_MAX+1` probe — no histograms, no cost-based optimiser. The ANN index is a **Backend** behind an entry point; the shipped stdlib backend refuses above 250,000 segments. A zero result is `absent` only after **fifteen** gates. The index is a cache, is `.gitignore`d, and the one committed artefact is `omniweave.index.lock`. | [D5-store](_notes/rulings/D5-store.md) |
| **D6** | The runtime is **one `asyncio` Supervisor in the `omniweave` distribution — never in `omniweave-core`, which stays synchronous and asyncio-free** — over a durable two-table plan (`unit` roster → `work` rows), with exactly one thread per process holding a `sqlite3.Connection` and one transaction per unit that writes derived rows. There is no wave and no checkpoint file: the claimable set *is* the checkpoint, bounded by a `queue_high_water`/`queue_low_water` hysteresis. Parallelism lives in exactly four places; batching at exactly two named sites and is invisible in all four ledgers. The cache is five content-addressed layers under one `cache_index`, of which the decisive one is `call` — we cache the *driver's raw response*, so a re-derivation of a corpus **within one store** costs CPU-seconds instead of a re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` is created by `0004_runtime.sql` inside the `.owstore`, so a fresh store opens with an empty cache. Incremental correctness rests on a **`dep` reverse index**, not on the cache key. | [D6-runtime](_notes/rulings/D6-runtime.md) |
| **D7** | The knowledge layer is **`owgraph`**: tables inside the `.owstore`, written only by the host through one `GraphSink`, where "deterministic versus LLM pipeline" is not a mode but four columns L2 already defines (`method`, `producer_id`, `trust`, `origin_driver`). The extraction unit is the **Segment**, and there is exactly one chunking in the framework. Deterministic-before-LLM is enforced by a **coverage ledger** ordered on `(cost_rank, phase)`, so a third party's free extractor preempts every paid one with no core change. An LLM is never asked for a character offset: it returns a `cite` and a verbatim `quote`, and the host locates it with one `str.find` that is simultaneously the citation, the polygon, the hallucination gate and the injection containment. No L3 table stores geometry. Entity resolution is append-only and reversible; communities are re-clustered always and re-reported only when `member_digest` changes. | [D7-structure](_notes/rulings/D7-structure.md) |
| **D8** | There is no `GeneratorTarget` abstraction and no universal omniweave IL. A **Target** is an artefact kind implemented by exactly two Drivers on existing Ports — one `compile/1` and one `parse/1` — plus four target-owned artefacts: a `constructs.toml` **ConstructTable**, a **RulePack** of one-function-per-file predicates, a `lower()`, and a `read_back`. An **IL** is a carrier plus a ConstructTable plus a RulePack: a closed declared subset of an *existing* text format (`svg` for pptx, `html` for deck and docx — zero of the three mined OUT repos invented syntax), text on disk, retained content-addressed in CAS so editing an omniweave-built artefact is a `passthrough` rather than a reconstruction. Determinism is a **declared set** over four classes where `part` is the promised floor and `byte` is recorded and never promised. | [D8-out](_notes/rulings/D8-out.md) |
| **D9** | Every capability is one **Action** declared once in `omniweave.surface.registry`, from which the CLI parser, the SDK, the MCP tool schemas, the MCP `instructions`, `llms.txt`, `AGENTS.md` and the router skill's action table are all **generated and byte-diff gated**; a hand-written agent-facing artefact is not shippable. **Listing and enabling are two keys with two owners**, with `listed ⊆ enabled` a startup invariant, so an unlisted capability is still served and never refused. Exactly **four tools are listed** — `ow_query`, `ow_open`, `ow_corpora`, `ow_add` — inside a frozen 1,900-token `tools/list` baseline; there is no generic `ow_do` dispatcher, because an untyped `action: string` collapses the host's only authority control. The response is a fixed-section **Answer** document of ≤ 24,000 chars. The entire OUT direction is skills plus CLI, **never MCP**. | [D9-serve](_notes/rulings/D9-serve.md) |
| **D10** | Evaluation is a **data model with a publishing gate**, not a CI job: every number omniweave shows anyone is a row in one `.oweval` file carrying `(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)`, produced by an RNG-free harness in `omniweave-conform`. Six budgeted test tiers plus a `contributor-parity` job proving `uv sync && pytest` is green offline, GPU-free and Node-free under ten minutes — affordable because **Cassettes** intercept the only two outbound model channels a driver has. Parser goldens are never document snapshots but three **Reductions** whose only differ is `rebind()`. Regression is gated in a strict hierarchy: exact **Counters**, then absolute memory, then time as a **Pacer** ratio. And the rule it exists for: an uncalibrated confidence is stored, usable as an internal filter, and **may never render a number, a percentage, a bar, a grade or a colour**. | [D10-quality](_notes/rulings/D10-quality.md) |

## 3. How to read this plan

### 3.1 The nineteen documents

| # | Document | What it is | Read it if you are |
|---|---|---|---|
| 00 | [Vision, Scope and Success Criteria](00-vision.md) | The five losses at the parse seam, the release-1 input/output/interface surface, six user scenarios, the fourteen non-goals, positioning against docling/LangChain/hosted APIs/rolling-your-own, and the numbered v0.1 / v1.0 / v2.0 acceptance criteria | deciding whether to adopt or fund this; writing the acceptance tests |
| 01 | [Principles and Invariants](01-principles.md) | The constitution: INV-1…INV-25, each with its failure mode, named enforcer and the shape a violation takes in a diff; thirteen principles for judgment calls; eighteen anti-patterns traced to measured failures; the reviewer's ten questions and rejection list | reviewing any PR; anyone at all, first |
| 02 | [System Architecture](02-architecture.md) | The component map and table, the import DAG and its CI gate, three traced end-to-end flows, process topology, startup sequence, the six-kind error taxonomy and the `OwError` tree, and the layered configuration model | orienting; deciding which module a change belongs in |
| 03 | [The Document Model (`owdoc`)](03-document-model.md) | Normative L2: every enum, dataclass and JSON Schema; the 34-member `Kind` vocabulary; four identities; `rebind()`; three coordinate systems; tables and grids; assets; the `.owstore` DDL and the `.owdoc` archive; projections and the conformance obligations | implementing L2, a parse driver, or anything that reads a Block |
| 04 | [Drivers, Operators and the Extension System](04-driver-system.md) | The card grammar table by table with comparison semantics, four discovery origins and their millisecond budget, probe-versus-purity, versioning and the refusal map, isolation with a per-OS watchdog, licence tiering and the posture report, the twelve conformance suites, and a worked end-to-end publish | writing a driver, first-party or third-party; reviewing one |
| 05 | [Acquisition, Parsing and the Routing Engine](05-ingest-and-routing.md) | `acquire/1`, connectors and change detection; content-first format detection; rungs and lanes; the policy grammar and evaluation order; the complete shipped policy; every day-one escalation signal and how each lies; the cost model and pricebook; replay; the quality loop; three documents traced part by part | implementing the router or a signal provider; tuning cost |
| 06 | [Structure Extraction and the Knowledge Graph](06-structure-extraction.md) | The L3 node and edge census with full columns; the extraction cascade and coverage ledger; the deterministic extractor roster; the LLM path with prompts, structured-output enforcement and caching; the nine-guard entity-resolution funnel; communities and demand-materialised reports; the provenance chain with real ids | implementing L3; deciding what to spend LLM tokens on |
| 07 | [Storage, Indexing and Retrieval](07-store-and-retrieval.md) | Pragma order, the physical schema, FTS5 configuration, the five channels and their internals, fusion and its defaults, the pure query planner with five worked plans, result shaping and `owrows/1`, byte-exact retrieval, vectors, WAL/snapshot/bulk-window concurrency, scale-out tiers and ST1–ST20 | implementing the store or retrieval; capacity planning |
| 08 | [The Execution Runtime](08-runtime.md) | The `work` row's five jobs and its lifecycle; concurrency in exactly four places with every number derived; model serving (S3); the five cache layers and `cache_key()` field by field; incremental refresh and the watcher; pipelines as data; budgets and admission; cancellation and shutdown; the four-method distributed seam | implementing the Supervisor, the cache, or a backend |
| 09 | [Generation: the OUT Compiler Contract](09-generation.md) | `CompileV1` in full; IL discipline and the `constructs.toml` contract-as-data; the validator, `RuleSpec` and the rule runner; the ten `GateStatus` values; compile purity over six digests and the seven `UnitOutcome`s; determinism; the asset ledger; the `OWC1` marker; `manual_required`; citation flow; the seven round-trip laws; the three v1 targets | implementing a Target; building the OUT skills |
| 10 | [Interfaces: MCP, Skills, CLI, SDK and Hooks](10-interfaces.md) | `ActionSpec` and the seven generated surfaces; the mechanical listing rule; the four listed tools with every parameter's exact meaning; the Answer's section and drop order with a full measured example; corpus discovery; the skill tier; the CLI grammar and exit codes; `install`/`doctor`/`uninstall`; five hook handlers; the SDKs; token accounting | building an agent surface; integrating omniweave into a host |
| 11 | [Repository Layout, Packaging and Release Engineering](11-repo-layout.md) | The tree, the fourteen distributions and what belongs in each, extras and the three install profiles, the two-language story and the Toolchain boundary, the three version axes, migration numbering under concurrent PRs, the CI job graph and the twenty-nine gates, the signed release path, and the licence segregation mechanism | setting up the repo; adding a distribution; owning CI or release |
| 12 | [Performance, Scalability and Efficiency](12-performance.md) | Three reference machines and the Pacer; the operation-by-operation budget and cold-start table; scaling at 10 / 1k / 100k / 10M documents with the component that binds at each; the resident-set and streaming policy; fifteen efficiency techniques each with its measured or derived saving; a dollar cost model for three corpora; `ow bench`; the Budget-versus-Guard regression mechanism | making a performance claim; sizing a deployment; setting a budget |
| 13 | [Quality, Testing and Evaluation](13-quality.md) | Four claim classes; the six-tier pyramid with per-tier budgets; statistics with no RNG on the default path; golden-corpus sourcing and licensing; three Reductions and one differ; property tests; determinism where models are involved; retrieval, extraction and absence evaluation; confidence calibration and its kill conditions; the public scoreboard | writing tests; publishing a number; owning the eval harness |
| 14 | [Security, Privacy and Licensing](14-security.md) | The threat model and the register that generates `SECURITY.md`; every ingest-boundary ceiling; the prompt-injection containment chain and a plain statement of what it cannot prevent; the narrow-API posture; the local-first privacy inventory and the egress switch's honest limits; the encryption seam; PII, retention and the crash-safe erasure cascade; supply chain; the per-dependency and per-weight licence register | shipping this commercially; a security or legal review |
| 15 | [Observability and Operations](15-observability.md) | Three artefacts and no fourth; the five-deep span model and the OTLP mapping with no SDK; the closed event vocabulary; metrics as queries; the cost ledger and its three group-bys; `ow query --explain` and `ow why`; logging and redaction; health and `ow doctor`; five deployment topologies; five failure runbooks; the telemetry policy | operating this; debugging a live corpus; being on call |
| 16 | [Build Order and Milestones](16-roadmap.md) | The five forcing edges; the three-week walking skeleton M0 and exactly what it fakes; ten phases with the staffing matrix, the Gantt, freeze points and command-shaped exit criteria; the critical path and what parallelises; build-versus-wrap per component; fourteen decision points | planning the build; staffing it; sequencing your own fork |
| 17 | [Risk Register and Open Questions](17-risks.md) | `tools/risks.toml` as data with ten owner roles and a leading indicator per row; six compound paths worse than their parts; three project-level and ten component-level kill criteria; eighteen load-bearing assumptions; the consolidated 203 open questions and the fifty-two recorded defects; what the plan over- and under-engineers | deciding whether to proceed; picking the next thing to close |
| 18 | [Public API Reference Sketch](18-api-sketch.md) | The whole v1 public surface as reference docs: the `omniweave.sdk` API, the `ow` CLI with real invocations, the four MCP tools in full JSON Schema, every `omniweave.toml` key, a complete working driver, a complete working Target, six end-to-end examples, and the per-symbol stability index | calling omniweave from code; checking the plan's coherence |

### 3.2 Reading path — "I am implementing this"

Ordered, with the reason each step precedes the next. This is the same order
[16-roadmap.md](16-roadmap.md) sequences the build in, and for the same forcing reasons.

1. **[01-principles.md](01-principles.md)** — first, because every later document assumes you will
   reject a PR by naming an invariant. Read §1 (INV-1…INV-25) and §4.2 (the reviewer's ten questions).
   Nothing downstream is comprehensible as *design* rather than as *taste* without it.
2. **[02-architecture.md](02-architecture.md)** — next, because you need to know which of fourteen
   wheels a change belongs in before you write one. §3.2's dependency rule and §7's error taxonomy are
   the two things you will consult weekly.
3. **[11-repo-layout.md](11-repo-layout.md)** §1–§2 and §6 — before any code, because
   `tools/layers.toml`, the extras graph and the twenty-nine gates decide what will even merge. The
   CI floor is roadmap phase **P1** for exactly this reason.
4. **[03-document-model.md](03-document-model.md)** — the pivot before its producers. Every parse
   driver, every index, every compiler is written against `Block`, `addr`, `cite` and the three
   coordinate systems. Building a driver first means rewriting it.
5. **[07-store-and-retrieval.md](07-store-and-retrieval.md)** §1–§3 — the DDL and the four Protocols,
   because L2's types are meaningless until you know what a transaction is and who holds the
   connection. Read §4 before you promise anyone a latency.
6. **[04-driver-system.md](04-driver-system.md)** — now that there is somewhere to write to. The card
   grammar and `resolve()`'s gate order must exist before the router can rank, and §9's worked publish
   is the fastest way to internalise the whole contract.
7. **[08-runtime.md](08-runtime.md)** Parts 1–4 — the `work` row, admission, the DriverHost and the
   cache. This precedes the router because the router writes a `route_decision` *and a reservation*,
   and both need a work row and a ledger to write into.
8. **[05-ingest-and-routing.md](05-ingest-and-routing.md)** — acquisition, detection and the policy
   engine. It comes after the runtime and after drivers because a decision is only meaningful once
   something can be dispatched and billed; §4.4's complete shipped policy is the test of everything
   above it.
9. **[06-structure-extraction.md](06-structure-extraction.md)** — L3, after L2 is stable and after the
   coverage ledger has a `derive_pass` registry and a cache to sit on. Segments are the extraction,
   embedding, packing and caching unit, so getting them wrong here is expensive everywhere.
10. **[07-store-and-retrieval.md](07-store-and-retrieval.md)** §5–§9 — the five channels, fusion, the
    planner and the `Verdict`. Deliberately revisited late: `structural` traverses L3's
    `block_link` **only** — `edge` is L3's entity→entity table and is reachable through
    `GraphView.neighbours()`, which is outside `retrieve()` and carries no budget, weight, ceiling
    contribution or `Verdict` — and the fifteen absence gates read L3 and the `diag` table.
11. **[10-interfaces.md](10-interfaces.md)** — the Action registry, after retrieval returns something
    worth serving. The registry must exist before the *second* surface, or the two hand-written
    surfaces will disagree and INV-20 becomes unenforceable retroactively.
12. **[09-generation.md](09-generation.md)** — OUT last of the functional layers, because `read_back`
    is an ordinary `parse/1` driver and the loop can only close once L1, L2 and the driver host all
    work. A Target additionally depends on `omniweave_core.out`, which depends on L2.
13. **[13-quality.md](13-quality.md)** and **[12-performance.md](12-performance.md)** — the gates and
    budgets, read together, because a Counter regression is cheaper to catch than a time regression and
    both must be wired before the numbers exist to protect. Read
    [12](12-performance.md) §2.4 "The gated subset — `eval/perf.toml`" before you add a budget row.
14. **[14-security.md](14-security.md)** and **[15-observability.md](15-observability.md)** — before
    shipping to anyone else's documents. [14](14-security.md) §2 "Untrusted document handling" — §2.1
    is the limit register at the ingest boundary — and [15](15-observability.md) §11 "Failure
    runbooks" are what make a real deployment survivable.
15. **[18-api-sketch.md](18-api-sketch.md)** — last, as the coherence check. If a signature you need
    cannot be written from the documents above, that is the disagreement, and §"Open questions" lists
    the four places it already happened.

### 3.3 Reading path — "I am reviewing the design"

Start with the invariants, because a design review that does not begin with the falsifiable properties
degenerates into preference.

1. **[01-principles.md](01-principles.md)** §"The enforcement classes, and the ladder", then §1
   (INV-1…INV-20 are the charter's; INV-21…INV-25 are this document's additions, adopted as
   invariants by ADR-2), then §1c "When two invariants collide" and §1d "Where the invariants are
   hardest to hold". §4.5 tells you what a reviewer may **not** reject for.
2. **[_notes/charter.md](_notes/charter.md)** §2 and §8 — the invariant table, which prints twenty of
   the twenty-five (`INV-21`…`INV-25` are [01](01-principles.md)'s, adopted as invariants by ADR-2,
   whose erratum `E30` supersedes charter `:66`'s own count), and the twenty-two-item rejection list,
   which is the charter's own compressed statement of what it will not
   accept. §8 items 19–22 are the ones a plan document is most likely to violate.
3. **[00-vision.md](00-vision.md)** §3 (the thesis and what follows from it), §5 (non-goals) and §10
   (the definition of failure). Read §10 before §9: knowing what counts as failure makes the success
   criteria checkable rather than aspirational.
4. **[02-architecture.md](02-architecture.md)** §1.3 "Six assertions the map makes that a reader can
   check" and §3.2 "The enforceable statement" — the fastest available falsification of the whole
   layering claim, then §5.7 "The honest ceiling".
5. **The ten rulings** in [`_notes/rulings/`](_notes/rulings/), each of which carries its **Rejected**
   section. This is where to attack a decision: the alternatives are already written down with the
   evidence that killed them, so a review either finds an alternative nobody considered or it is
   re-litigating a settled one.
6. **[17-risks.md](17-risks.md)** §5 (kill criteria), §6 (the eighteen assumptions and what each costs
   if false), §8 and §9 (what the plan over- and under-engineers). §5.3 lists four failures that are
   deliberately *not* kill criteria, which is where a reviewer's disagreement is most likely to be
   substantive.
7. **[13-quality.md](13-quality.md)** §1 (four claim classes) and §9 (calibration, including the
   kill conditions) — because the plan's honesty machinery is the part most likely to be quietly
   dropped under schedule pressure, and §9.5 is what stops it.
8. **[12-performance.md](12-performance.md)** §1 (reference hardware and what a number without it
   means), §8.1 (Budget versus Guard) and §9 (what omniweave is not fast at, and why the trade is
   right). A performance claim with no Runner and no Pacer ratio is not a claim.
9. **[14-security.md](14-security.md)** §1 (threat model) and §3.1 (what the framework prevents and
   what it does not) — the two places the plan is most explicitly bounded, plus §9.1, which corrects
   seven licence errors in the source analysis and changes three shipping decisions.
10. **[16-roadmap.md](16-roadmap.md)** §14 (the critical path) and §17 (decision points) last — a
    schedule review is only meaningful once the design under it is settled, and §15.1 states the
    estimation basis precisely so a reviewer can reject a number.

### 3.4 Reading path — "I want to understand one thing"

An index by question. Every target is a section that exists.

| Question | Where |
|---|---|
| How does a citation resolve to a page region? | [01](01-principles.md) §INV-9 states the rule (a Block, a page, and a polygon **or a stated reason** — never a synthesized box); the mechanism is [06](06-structure-extraction.md) §8 "The provenance chain, with real ids", where `locate()` walks `mention → block.quad` and returns a `Locus` whose `reason` is non-`None` iff `quad is None` |
| What exactly may appear in a prompt or in model output? | [01](01-principles.md) §INV-8 — the closed token space `d…#…`, `e…`, `c…`, `k…`, optionally corpus-qualified. The grammar and the `next_cite_n` minting rule are [03](03-document-model.md) §6.3 "`cite` — the durable, prompt-safe name" |
| When may omniweave claim a quote is byte-exact? | [01](01-principles.md) §INV-10 — a retained part plus an `OriginSpan` re-verified on one of three branches (`bytes`, `nodepath`, `glyphs`). The retrieval side is [07](07-store-and-retrieval.md) §8 "Byte-exact retrieval", and §8.2 is the rule for when reconstructed text is returned instead |
| How does a zero result become "absent" rather than "we found nothing"? | [01](01-principles.md) §INV-11 states the single-return-site rule; the gate-by-gate trace in precedence order 1..15 is [15](15-observability.md) §6.1 "`ow query --explain`", and [07](07-store-and-retrieval.md) §6.6 "Five worked plans" shows two verdicts derived end to end |
| Why does a scanned page not silently cost me a GPU call? | [01](01-principles.md) §INV-13 (escalation is per part and monotone; a clean page computes zero `LOCAL_COMPUTE` signals) and [05](05-ingest-and-routing.md) §4.3 "Evaluation order, the demand plan, and what `on_unknown` actually does" — evidence is acquired by a `DemandPlan` in ascending `CostClass` |
| Where does money enter the system? | [05](05-ingest-and-routing.md) §6.1 "Seven physical units, and no driver prices anything" and §6.2 "`.omniweave/pricebook.toml` — operator-owned, versioned, digested". The invariant is [01](01-principles.md) §INV-15 |
| How is a driver chosen for a given page? | [04](04-driver-system.md) §4.7 "The probe, and how `resolve()` stays pure" for the pure admission filter and its gate order, then [05](05-ingest-and-routing.md) §4.2 "The rule grammar" for the ranking — `resolve()` never chooses |
| What stops a driver lying about what it can do? | [04](04-driver-system.md) §8 "The conformance kit" — §8.1 is the thesis (the card is the test plan), §8.2 the twelve suites, §8.3 what the kit writes versus what the loader recomputes, §8.4 what a passing run does and does not entitle an author to claim |
| How do I write and publish a driver? | [04](04-driver-system.md) §9 "Worked example: publishing `parse.notebook.ipynb`", seven steps from scaffold to badge; the same thing as reference material is [18](18-api-sketch.md) §5.2 "A complete minimal working driver" |
| How is a merged-cell table with a header hierarchy represented? | [03](03-document-model.md) §10 "Tables" — §10.1 the representation, §10.2 `build_grid` as the sole streaming constructor, §10.3 a fully worked merged-cell example, §10.4 what was rejected |
| What happens when the extraction model invents a quote? | [06](06-structure-extraction.md) §9.2 "What each layer stops, and what it does not" — grounding is the one function `ground(block_text, quote) -> (ts_a, ts_b, occurrences) \| None` of §1.7, which searches in `normalize_k`'s **normalised** space and returns offsets in **`block.text`** space, carried across by `normalize_k`'s back-map; an ungrounded item is written to `quarantine` **verbatim with a closed code**, never deleted, because a hallucinated name is often a real entity the extractor failed to emit |
| Why are only four MCP tools listed, and how do I reach the rest? | [10](10-interfaces.md) §2.4 "The listing rule: L1–L4, mechanical" for why four survive, §3.1 "The front door: four tools, and the measured payload" for the token accounting — 850 tokens of the 1,900-token ceiling under the shipped `compact_schemas = true` and 1,031 with it off, so the refusal of a fifth tool is the listing rule's and never the budget's — and §3.8 "Progressive disclosure: the env var, the profile, and the roster" for reaching a narrow Action |
| What does a query cost, in milliseconds? | [07](07-store-and-retrieval.md) §4.4 "The query latency budget" for the per-channel decomposition that sums to 210 ms against 250; the machine-by-machine envelope and the cold-start table are [12](12-performance.md) §2.2 "The envelope" and §2.3 |
| What does ingesting a thousand documents cost, in dollars? | [12](12-performance.md) §6.3–§6.5 — three corpora (born-digital, scanned, mixed) under three configurations, per 1,000 documents — then §6.7 "The incremental unit cost", which is the workload a deployed system actually runs, and §6.8's five honesty clauses |
| How does an incremental run stay correct rather than merely fast? | [01](01-principles.md) §INV-18, then [08](08-runtime.md) §Part 5 "Incremental refresh" for the `dep` reverse index and the batch cache-check, and [06](06-structure-extraction.md) §10 "Incremental maintenance, concurrency and partial failure" for `anchor_delta` and §10.4's convergence gate |
| How does a generated PPTX become a citable corpus document? | [09](09-generation.md) §11 "`read_back`: the round-trip contract" — the seven laws as testable properties, what must survive versus what may be lost, and `il_digest_rt`. The citation half is §10 "Citation flow" |
| Why is an IL a subset of SVG rather than a schema we designed? | [09](09-generation.md) §3.1 "What qualifies as an IL" and §3.4 "`constructs.toml` — the contract as data" — the three things a real table must express (a bake tier, a *conditional* prohibition, a cross-element occurrence budget) are none of them shape constraints, so JSON Schema cannot hold them |
| Why is there no `--force`, and what do I use instead? | [01](01-principles.md) §P10 "An override is named for its hazard, never for what complained", then [05](05-ingest-and-routing.md) §7.3 "Overrides — seven, each named for its hazard" |
| Where is every configuration key defined? | [18](18-api-sketch.md) §4 "`omniweave.toml` — every key"; the precedence and the `semantic`/`operational` axis that decides whether a key enters a cache key are [02](02-architecture.md) §8 "Configuration", §8.3 in particular |
| What breaks first as the corpus grows, and where is the exit? | [07](07-store-and-retrieval.md) §12 "Scale-out" — §12.2 the four tiers, §12.4 what breaks first in order, §12.5 the honest statement — and [12](12-performance.md) §3.5 "Ten million documents — out of envelope, and the exit is named" |
| A driver quarantined and a whole format went quiet. Now what? | [15](15-observability.md) §11 "Failure runbooks", R3. R1 is a growing WAL, R2 is spend exhausted mid-corpus, R4 is a silent re-bill or silently stale billed output, R5 is every query saying `degraded` |
| Can I ship this commercially? | [14](14-security.md) §9 "Licensing" — §9.1 the seven corrections to the source analysis, §9.3 the default-install line per dependency, §9.5 the model-weights register, §9.8 the clean-room fallback if every restricted component must be dropped, §9.9 what omniweave claims about its own output |
| Why does the confidence badge show a word instead of a number? | [01](01-principles.md) §INV-19 and [13](13-quality.md) §9 "Confidence calibration" — §9.3 the two tests and their thresholds, §9.4 the surfacing rule, §9.5 the kill conditions that delete a tag rather than caveat it |
| What is the actual build order, and when does v0.1 land? | [16](16-roadmap.md) §1 "The sequencing principle", §2 for M0, §3 for the phase map and Gantt, §14 for the critical path. v0.1 at program week 42 / 224 engineer-weeks; v1.0 at week 64 / 363 |

## 4. Status

### 4.1 Decided

The ten decisions of §2 are settled law. So are: the twenty-five invariants (ADR-2 adopts
`INV-21`…`INV-25`, so they are invariants and not pending principles); the fourteen distributions
and the import DAG; the five Ports
and the two things that are deliberately not Ports; the four seams and the rule that there is no fifth;
the three version axes (`RELEASE`, `CONTRACT`, `SCHEMA`); the terminology lock, including its list of
rejected synonyms and its reserved-and-forbidden set; the five retrieval channels and the fifteen
absence gates; the one chunking (the Segment) and its target/ceiling pair; the seven-unit `Spend`
vector and the operator-owned `PriceBook`; the six-tier test pyramid; and the twenty-nine `G` gates
(`G1`-`G29`; ADR-2 allocates `G28` and `G29` and makes the series append-by-ADR rather than closed,
with its cardinality in `tools/gates.toml`).
[_notes/charter.md](_notes/charter.md) §7 also names four things that **look** open and are not:
`ord_path` stays rejected permanently, `use_lcc` is permanently off, the embedding-key question is
settled on both objects, and `vectors = "off"` is the shipped default — most first runs get four
channels and a verdict that says `semantic: off`, which is a visible product limitation and the correct
one.

### 4.2 Deferred

[_notes/charter.md](_notes/charter.md) §7 carries **forty-one** deferred items, `F1`–`F41`. Each names
the measurement that closes it and, where the answer changes a shipped default, a **pre-committed
fallback** — so none of them blocks writing or implementing the plan; each is a number someone must
produce. They cluster into six groups:

| group | items | the shape of the risk |
|---|---|---|
| Envelope and sizing | `F1` blocks-per-page, `F8` scheduler overhead, `F29` a sub-page commit boundary, `F36` `dep` rows per unit, `F37` `route_signal` disk and VRAM residency | every storage, frame, segment and RSS number scales off `F1`; if dense corpora land near 300 blocks/page, T2 arrives at 5M blocks rather than 50M |
| Licence-clean components | `F4` a layout detector, `F10` an ANN library, `F18` an SVG rasterizer, `F40` `graspologic-native` | each is a capability that ships **absent and disclosed** rather than encumbered; `F4`'s absence makes `REPAIR` thin on the PDF path and every affected decision records `cause = "layout_unavailable"` |
| Model behaviour | `F5` `garble.score` thresholds across scripts, `F6` VLM `tokens_out` p95, `F12` the grounding gate's true-fact quarantine rate, `F14` whether models emit `e412`/`c412`/`k412` reliably, `F23` whether agreement is a usable calibration label | `F14` is the one that must close **before** anything ships: a sigil in a delivered answer is permanent |
| Economics | `F7` server-coalescing speedup, `F13` real `coverage_frac`, `F26` whether the cache key needs a lockfile digest, `F39` whether the `[75,92)` LLM merge band earns its cost | `F13` is the whole cost argument for deterministic-first; below a 0.2 median outside structured corpora, [06](06-structure-extraction.md) §2.4 is **rewritten rather than defended** |
| Retrieval and quality | `F3` one Segment table for two jobs, `F9` binary quantisation recall, `F11` `W_HEAD`/`SPINE_DECAY`, `F19` front-door mis-pick rate, `F20` budget tiers, `F22`/`F24` calibration sample sizes, `F30` policy subsumption yield, `F31` geometry quantization stability, `F35` the verdict at federation scale | `F31` must close **before the golden suite freezes**, because `Q-G4` is a hard byte-diff gate resting on it and the exit is a `digest_recipe` bump budgeted at most annually |
| Packaging and shape | `F2` the anydoc eager marshal, `F16` `part` determinism across nine cells, `F17` the `project()` ceiling for foreign artefacts, `F21` subagent MCP sessions, `F25` a second reason for process isolation, `F27` multi-tenancy, `F28` `block_id` under a Postgres T3, `F32` whether parts are retained by default, `F33` whether the CLI should depend on office, `F41` cross-language card semantics | `F27` is pre-committed: **v1 is store-per-tenant**, and row-level tenancy is not designed and must not be assumed by any plan document |

Beyond the charter's forty-one, [17-risks.md](17-risks.md) §7 consolidates **one hundred and
sixty-two** further open questions raised by the nineteen documents, of which **fifty-two** are
recorded charter or cross-document *defects* — followed as written per the plan's own rule, each with a
named closer, grouped in §7.6 into twelve change sets that resolve them together. Those twelve are on
the v0.1 critical path and are unpriced.

### 4.3 What would change the plan

Three project-level and ten component-level **kill criteria** in [17-risks.md](17-risks.md) §5, each an
*observation* — an instrument, a threshold, and what specifically stops. The three that stop the whole
thing:

- **K-1** — `source_reread_rate > 0.25` at v1.0 **and** `task_accuracy` no better than the
  no-omniweave control arm by more than one Wilson width, with no fixable cause. The entire apparatus
  of Blocks, polygons, `Trust` tiers, absence gates and cite carrying exists to make the agent's second
  read unnecessary.
- **K-2** — `citation_soundness < 0.995` or `citability_violations > 0` across two consecutive
  releases. The one number that is not tradeable against any other.
- **K-3** — `first_answer_seconds > 3600` on the acceptance path after two attempts at reducing the
  identified dominant term. The MCP surface stops shipping as a self-install; the engine survives as an
  embedded component.

The ten component-level criteria delete a *part* rather than the project, and each names what survives:
the `semantic` channel (**K-4**), the `bake` disposition (**K-5**), the LLM merge band (**K-6**), the
video Target (**K-7**), most of L3 (**K-8** — leaving Segments, anchors and `block_link`, exactly the
subset the `structural` channel and the incremental-correctness argument depend on), the `inproc` seam
(**K-9**), the `deck` Target and with it the Toolchain seam (**K-10**), the `PAGE` rung's only producer
(**K-11**), the ecosystem investment (**K-12**), and SQLite-at-T2 (**K-13**, which pulls Postgres
forward behind the four Protocols that exist for it).

Eighteen assumptions in §6 are the other lever: each says what rests on it and what happens if it is
false. The four most load-bearing are `A1` (a document is static once ingested — otherwise the
**roster** is redesigned, not tuned), `A3` (60–120 Blocks per page at ~660 B — nine claims repoint at
once), `A4` (deterministic extraction covers most load-bearing structure — otherwise deterministic-first
survives as a correctness argument and dies as an economic one), and `A18` (the nineteen documents are
mutually consistent — already false in fifty-two recorded places, with the enforcer that would find the
rest still blocked).

## 5. Provenance

This plan derives from the twenty-two-repository analysis in `_index/` (`_index/README.md`, not published) —
per-repo architecture in `_index/repos/` (`_index/repos/`, not published), head-to-head tables in
`_index/comparisons.md` (`_index/comparisons.md`, not published), the layer model in
`_index/taxonomy.md` (`_index/taxonomy.md`, not published), and the first synthesis in
`_index/framework-blueprint.md` (`_index/framework-blueprint.md`, not published) — refined into source-verified
engineering notes in [`_notes/mine-*.md`](_notes/) (27,433 lines with real class names, schemas,
signatures and measured numbers), then ruled on by ten adversarial panels and harmonised into the
charter. Where a plan document makes a claim it cites the file and line it verified.

### 5.1 What each source project contributed

| Project | Contribution |
|---|---|
| **docling** | The converter/backend/pipeline/serializer separation, `DoclingDocument` as a design to copy rather than inherit, `contextualize()`, per-item confidence, and the plugin defect that forced INV-4: `load_setuptools_entrypoints()` executes plugin code *before* the `allow_external_plugins` gate can suppress its registration |
| **marker** | Per-page cost-tiered routing — the single idea `Rung` × `Lane` generalises; the block tree with `polygon` and `section_hierarchy`; and the measured result that settles reading order, 75% versus 56% for a char stream over a learned head (`builders/line.py:80-82`) |
| **surya** | The shared inference manager with many predictor heads, OCR-error detection as a *routing signal* rather than a quality report, and the `SURYA_INFERENCE_URL` override that became attach-or-spawn |
| **olmocr** | The only pipeline in the collection that has run millions of PDFs: two `asyncio.BoundedSemaphore`s with CPU render separated from GPU inference (`pipeline.py:87-88,112`), adopted verbatim; olmOCR-Bench's per-category assertion record, generalised into the `Assertion` model; and Apache-2.0 weights with a pinnable revision |
| **HunyuanOCR** | Task-as-prompt — one model serving parse, extract, translate and QA, which is why a Lane is what is asked for and a Service is not routed |
| **Unlimited-OCR** | Repetition guards for long-context VLM parsing (`no_repeat_ngram_size`, `ngram_window`), and the counter-example that fixed the fan-out deadline: `MAX_RETRIES = 5` × `REQUEST_TIMEOUT = 1200 s` is 100 GPU-minutes for one document (`infer.py:21-25`) |
| **Ollama-OCR** | `format_type` as a first-class parse parameter |
| **markitdown** | The narrow-API security posture, adopted wholesale — capability is chosen by which door you call; per-format optional extras; ZIP iteration; and the sharpest single illustration of the problem omniweave exists to solve, a return type of one string plus an optional title |
| **anydoc** | The published MIT `abi3` decoder omniweave consumes rather than rebuilds (eight Rust dependencies, no HTTP client of any kind, twelve `cargo-fuzz` targets, `abi3-py310`), its exactly-once table grid, `toDocument()` exposing the intermediate, and its release pipeline's shape. Its honest limit is on the card: `block.rs` carries no source address of any kind, so `origin_span = "none"` on the office path and the fork trigger's first clause is the fix |
| **omniparse** | Flag-gated model-group loading and the lazy-residency bug that made demand-driven loading a design rule rather than an optimisation |
| **lift** | Schema-constrained decoding as the `fields` lane, Schema Studio as prompt tuning, and adversarial extraction-benchmark design |
| **graphrag** | The seven-type knowledge model, TextUnit provenance, the factory-per-subsystem shape, the LLM cache, `update_*` incremental workflows, and the rule that a citation must be short enough for a model to emit reliably — which is `cite` |
| **graphify** | `EXTRACTED / INFERRED / AMBIGUOUS` on every edge, decomposed here into three orthogonal axes; zero-LLM extraction wherever structure exists; a lenient substring check that *flags* rather than drops, which became grounding-by-quote; the git merge driver; `graph_diff`; and 0.497 recall@10 on LOCOMO at zero LLM build cost |
| **codegraph** | One composite MCP tool, measured; SQLite plus FTS5 as the whole store; the pragma ordering that crashes a contended open if reversed (`busy_timeout` before `journal_mode`, issue #238); the eight-property WAL valve and bulk-index windows, ported whole; auto-sync on OS events with debounce; install/uninstall symmetry; and the 4.3%-of-distinct-edges-wrong-in-both-directions-silently measurement that makes `rebind()` a required pass |
| **jcodemunch-mcp** | Weighted RRF over heterogeneous signals; byte-offset retrieval against cached originals; the `PreCompact` hook; the compact wire encoding that became `owrows/1`; token accounting in the store; the decode-symmetry bug (#400) behind `QuoteVerdict`; and the receipt that settles the front-door magnitude — 22,741 tokens per turn for 91 listed tools against 939 for three |
| **LEANN** | Selective recomputation and the storage argument behind binary quantisation; ~15 personal-data connectors; AST-aware chunking; a two-tool MCP surface; `llms.txt`; and the defect that `mcp_name = None` closes structurally — an `llms.txt` declaring two tools against a four-tool server, two of them state-changing and undeclared |
| **DataFlow** | The operator/pipeline/registry triad and one definition behind three front-ends — adopted as the Plan document and rejected as a DAG; distribution under a registration contract; and the in-process unsandboxed execution of LLM-generated Python that omniweave has no equivalent of, by construction |
| **local-deep-research** | The compounding library loop; the per-user encrypted store with password-derived keys, adopted as the encryption seam's design; the private-destination-by-default egress posture, adopted wholesale; the semgrep rule set; and the only complete release pipeline in the collection, used as the release template |
| **ppt-master** | The canonical/compatible/invalid trichotomy behind `Disposition`; "prompts are not a correctness boundary"; the spec lock that became the `Brief`; `manual_required`; round-trip intake; bounded audit transcripts; canonicalize-then-hash; and the stamped `data-*` source attribute that proves an in-file anchor is durable — which is `el` plus `nsig` |
| **open-slide** | Source-embedded, element-addressed feedback markers, which is the `OWC1` grammar; the four scoping questions; a separate authoring-reference skill; a fixed canvas; and `skills-lock.json` — including its defect of pinning no ref and hashing only `SKILL.md`, which is why whole-bundle content hashing replaced it |
| **hyperframes** | Determinism as an explicit declared contract, which became `ArtefactDeterminism`'s four classes; the router skill plus on-demand workflow install; the media ledger, generalised to the asset ledger over L2's `asset` table; lint/check/snapshot as three verbs; brief confirmation before work; and `options.remainingMs?.()` as the shape of a fan-out deadline |
| **awesome-skills** | The skill-registry patterns: a `_template`, `AGENTS.md` as a separate generated deliverable, a published review rubric, and description-as-dispatch-surface |

### 5.2 The licence vetoes, named

Four exclusions, each verified in-tree, each with the consequence stated rather than hidden.
[14-security.md](14-security.md) §9.1 carries the full corrections and §9.2 carries the gate.

- **marker, surya and lift model weights — excluded.** `marker/MODEL_LICENSE`, `surya/MODEL_LICENSE`
  and `lift/MODEL_LICENSE` are **byte-identical**, md5 `e1f69b64dee2f1641a9b1ab12adf24d6`. Clause 2(c)
  at `marker/MODEL_LICENSE:58` bars use *"for any purpose if You … provide … any product or service
  that competes with any product or service offered by … Licensor"* — with no revenue threshold and no
  research carve-out. The widely quoted "$5M startup exemption" is a different clause. Datalab sells
  document parsing; so does omniweave. Clause 8 at `:39` is additionally viral on **Output**, which for
  a parsing product is worse than the competitor bar because it contaminates the deliverable — and is
  why output-side `Restriction` bits exist at all. `texify` is a fourth Datalab package, easy to miss
  because its name contains neither "marker" nor "surya". **Consequence:** two of marker's four page
  signals cannot ship, `layout.class_hist` is absent on day one, and the `REPAIR` rung is thin on the
  PDF path until a licence-clean detector lands (`F4`). The router's job is to make that hole priced
  and visible: every affected decision records `cause = "layout_unavailable"`.
  `geometry.overlap_line_frac` survives intact, because `check_line_overlaps` reads only line boxes and
  the page polygon.
- **HunyuanOCR — excluded, territorially unusable rather than merely "check terms".**
  `License.txt:3,17` exclude the EU, the UK and South Korea from the licensed Territory; `:31` adds a
  100M-MAU gate; `:35` forbids using or displaying even the **Output** outside the Territory; AUP items
  12 and 14 bar the insurance, credit, health, employment, housing and education use cases. HK law, HK
  exclusive venue.
- **jcodemunch-mcp — excluded from vendoring.** No tier at any price permits redistribution, and
  clause (c) forbids publishing a derivative to any public registry (`LICENSE:29-33,69-84`). Its
  *ideas* are adopted and attributed; none of its code is.
- **omniparse — excluded, and the licence itself is the blocker.** `LICENSE:1-2` is GPL-3.0 while
  `pyproject.toml:7` says `license = "Apache"`; a self-contradicting licence is a blocker regardless of
  which text wins. It also pulls `marker-pdf`, `surya-ocr` and `texify` together, so one abandoned
  dependency drags in three OpenRAIL-M weights sets.

**What the plan is built on instead: docling and anydoc.** docling supplies the *designs* — the
converter/backend/pipeline/serializer separation, the document-model shape, per-item confidence — and
none of its classes, because `docling-core` is pinned across a whole major, hard-requires `pandas` and
`typer`, lists `torch` and `torchvision` as *base* dependencies, and shipped 168 releases in 21 months,
so a minor could redefine our public type between two installs. anydoc supplies the *implementation* of
the office/text/CSV/EPUB/RTF path as someone else's published MIT `abi3` wheel we do not build. Weights
come from olmocr (Apache-2.0, pinnable revision). graphify's Apache-2.0 relicensing in 2026 means a
vendored copy must be pinned to a commit. The default install line is
unconditionally commercial with no acknowledgement required, and
[14-security.md](14-security.md) §9.8 carries a clean-room fallback stack for the case where every
restricted component must be dropped.

## Open questions

These are properties of the plan **as a set**, not of any one document. Every one of them is a defect
in the corpus of nineteen documents that a reader of this README will hit, so it belongs here rather
than nowhere. Each names what closes it. The per-document open questions live in each document's own
"Open questions" section and are consolidated in [17-risks.md](17-risks.md) §7.

1. **The gate counts — decided: twenty-nine `G` (ADR-2) and twenty-seven `Q-G` (ADR-11).** The `Q-G`
   series is closed at twenty-seven, `Q-G1`-`Q-G27`, which is what [13-quality.md](13-quality.md)
   defines. The `G` series is **not** closed: ADR-2 allocates `G28` and `G29`, makes further appends
   an ADR each, and moves the cardinality into `tools/gates.toml`, which is why
   [00-vision.md](00-vision.md) `V10-1` now quotes the register rather than a literal. **Remaining
   edits:** [16-roadmap.md](16-roadmap.md)'s opening paragraph still says v1.0 lands with "all 27
   `G` gates and all 23 `Q-G` gates green", and §15.1 basis rule 3 still computes `27 + 23 = 50`
   gates ⇒ 10 ew where ADR-11 makes it `27 + 27 = 54` ⇒ **10.8 ew** — four engineer-days **added**,
   not returned, against a 6 ew program buffer.
2. **The `[[job_assertion]]` count — decided by ADR-2: nine.** The seven of
   [11-repo-layout.md](11-repo-layout.md) §6.4 plus `gates.invariant_register` and
   `gates.risk_register`, the two register checks ADR-2 declines to make `G27` clauses because a
   register's semantics are not a document check. **Remaining edit:**
   [11-repo-layout.md](11-repo-layout.md)'s opening paragraph and its Job-assertion lock row still
   say "seven unnumbered job assertions".
3. **The ADR directory has two homes.** [11-repo-layout.md](11-repo-layout.md) §1.8
   places ADRs at `docs/adr/NNNN-<slug>.md` and §8.4's `CODEOWNERS` confirms `/docs/adr/`, while
   [01-principles.md](01-principles.md) §"Open questions" and [17-risks.md](17-risks.md) `R-O9` and its
   New-terms entry for `charter_defects_open` both point at `_plan/adr/`. The contents half is now
   settled: [`_plan/adr/`](adr/) holds the twelve ADRs of
   [17-risks.md](17-risks.md) §7.6, all accepted, so `charter_defects_open` has a populated directory
   to count. By an explicit scope decision no ADR file is written for the ten original decisions;
   this README links those to
   [`_notes/rulings/`](_notes/rulings/) instead, which carries the same content an ADR would plus the
   full alternatives reasoning. **Closes when:** one of the two paths is chosen — a `docs/adr/`
   ruling would move twelve files and re-point three documents, and a `_plan/adr/` ruling would
   amend 11 §1.8 and its `CODEOWNERS` row instead.
4. **The invariant count — decided by ADR-2: twenty-five.** It was stated four ways;
   `INV-21`…`INV-25` are adopted as invariants, on the ladder's own rule 1, and
   `tools/invariants.toml`'s five `force = "principle"` rows become `force = "invariant"`.
   `tools/invariants.toml` is the single register both the short form and the gate read, and
   `gates.invariant_register` clause 5 asserts that **every spelled-out invariant count in any
   document equals the number of `[[inv]]` rows**, so this cannot drift again.
   [01-principles.md](01-principles.md), [00-vision.md](00-vision.md),
   [17-risks.md](17-risks.md) and this file now read twenty-five. **Remaining edit:**
   [11-repo-layout.md](11-repo-layout.md) §1.8 still describes `docs/ARCHITECTURE.md` as carrying
   "the twenty invariants". Charter `:66`'s "Twenty properties." stands as printed and is superseded
   by ADR-2 erratum `E30`.
5. **This README's own document count is a fact about a directory, not a register.** Nineteen
   documents and 44,702 lines (`wc -l 00-vision.md … 18-api-sketch.md`) are true at the time of
   writing and have no enforcer: nothing fails if a
   twentieth lands unlinked, and [11-repo-layout.md](11-repo-layout.md) §1.8 hard-codes
   "`docs/plan/00-vision.md … 18-api-sketch.md`" in a tree that `G27` renders but does not count.
   **Closes when:** `G27(d)`'s link check is extended to assert that this table's row set equals the
   `docs/plan/` file set in both directions — the same bidirectional shape the terminology lock's CI
   rules already use, and cheap because the checker exists.
