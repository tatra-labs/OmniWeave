# System Architecture

**In one paragraph.** omniweave is fourteen `py3-none-any` distributions arranged as one directed
acyclic import graph with a single pivot: `omniweave_core.model` (L2, `owdoc`). Everything below the
pivot populates it through host-side sinks; everything above it is a view over it or a compiler out of
it. One distribution holds the driver-facing vocabulary and depends on nothing (`omniweave-ports`);
one owns the store, the retrieval engine, the answer renderer and the OUT framework
(`omniweave-core`, zero third-party dependencies, synchronous); one owns the event loop, the router
and the surface registry (`omniweave`); eleven are drivers, targets, the MCP server or the
conformance kit. The dependency rule is one sentence — a non-`compile` driver imports
`omniweave_ports` and nothing else of ours — and it is a CI gate (`tools/gate_layers.py`, G4) that
reads each distribution's entry points rather than trusting a hand-maintained list. This document is
the component map, the dependency law, three traced data flows, the startup sequence, the process
topology, the extension-surface index, the error taxonomy and the configuration model. It expands
charter §3 (layers, distributions, import DAG, seams, version axes), D1's package layout and CI
gates, D3's ports/host/wire split, D6's process and cache shapes, and §6.4–§6.10; it re-decides none
of them.

## 1. The component map

### 1.1 The two call paths

Every entry into omniweave is one of exactly two shapes, and keeping them apart is what makes
charter §3.3 consequence 3 (`omniweave-serve` never runs the Supervisor) structural rather than a
review habit.

```text
                 ACTIONS — ONE registry, SEVEN generated surfaces (INV-20, gate G25)
 +- SERVE ------------------------------------------------------------------------------------+
 | omniweave-serve                    omniweave                    skills/ (a data artefact)  |
 | +------------------------+  +-----------------------------+  +---------------------------+ |
 | | mcp/stdio  mcp/http    |  | surface/registry.py         |  | omniweave/SKILL.md        | |
 | | otlp.py — THE ONLY     |  |   ActionSpec ACTIONS Profile|  | references/actions.md     | |
 | |  opentelemetry site    |  |   HUMAN_ONLY                |  +-------------^-------------+ |
 | | NEVER imports          |  |  |- cli/    argparse tree   |                | GENERATED     |
 | |  `omniweave`           |  |  |- sdk/    sync+async twins|                | (G25)         |
 | +-----------+------------+  |  |- hooks/  ow hook <event> |                |               |
 |             |               |  `- gen/    ow surface emit -----------------+               |
 +-------------|------------------------------|-----------------------------------------------+
               |                              |
   READ PATH   |                  DRAIN PATH  |  ow ingest · ow make · ow out · ow resume
   ow_query ow_open ow_corpora                |  (CLI, a hook, the watcher, or the detached
   ow_add: writes `unit` roster rows ONLY     |   child `ow_add` spawns)
               |                              |
               v                              v
 +- omniweave_core.retrieve + .answer -+   +- L5 RUNTIME (panel 1.2) --------------------+
 | THE ONE implementation three        |   | omniweave/{plan,run,route,graph}/           |
 | surfaces call, and none of them     |   | Exactly one asyncio Supervisor per process. |
 | owns (charter §3.3 consequence 2)   |   +---------------------------------------------+
 +-------------------------------------+
```

A read never blocks on a refresh: `ow_add` appends to the roster and returns, and freshness in the
response is derived from `work`-table state, not from waiting for it. That is why `omniweave-serve`
can be embedded, hosted or dropped without changing what a read means. The roster append is itself a
store write and therefore takes the same writer lock as an ingest — §5.4 specifies what `ow_add`
does when an ingest holds it, because "appends and returns" is only true if that case has an answer.

### 1.2 The layers, the wheels and the seams

Read the diagram as three things at once: **layers** (L0–L6, left gutter), **distribution
boundaries** (the boxes; one box is one wheel), and **seams** (S1–S4 — the only four places control
leaves the host process).

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
 | expand.py BFS over block_link only             |   | quarantine (rejected drafts, kept)  |
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

### 1.3 Six assertions the map makes that a reader can check

1. **No arrow enters L3, L4 or L6 without passing through L2.** L3 references blocks by `block_id`
   only; L4 scores over `block` and `segment` rows; L6 compiles from a `Doc`, a set of `Hit`s and a
   `CiteResolver` — all L2/L4 read surfaces. There is no path from a parse driver to an index. That
   is INV-1 drawn.
2. **Every driver box connects to L2 by exactly one edge**, labelled `owdoc-fragment/1` for a
   `parse` driver and `owgraph-items/1` for a `derive` driver. A driver never holds a `DocSink` or a
   `GraphSink`, and neither protocol carries a `block_id`, so a fragment is portable between stores.
   See [the driver system](04-driver-system.md).
3. **The edge from a driver box into `omniweave_core.drivers` points the wrong way to be an import.**
   It is a *file read*: `discovery.py` locates each named package's `driver.toml` through
   `Distribution.locate_file()` and parses it with `tomllib`. `EntryPoint.load()` is banned under
   `omniweave_core/drivers/` and G11 installs a rogue driver whose module body writes a file and
   raises `SystemExit` to prove the ban holds (INV-4).
4. **`omniweave-serve` has no edge into `omniweave/run/`.** Its two arrows in §1.1 land in
   `omniweave_core.retrieve`/`.answer` (read) and in the `unit` roster (write). The drain is
   `ow ingest`.
5. **Nothing in `omniweave_core` imports `asyncio` or `selectors`.** The single event loop lives in
   `omniweave/run/supervisor.py`, in the CLI distribution, precisely so that the per-turn hook path
   pays no loop-import tax (G23, INV-3).
6. **No box in the L1/L3 driver band has an arrow to any other box in it.** A driver's entire
   omniweave surface is `omniweave_ports`; two drivers cannot compose except through L2. That is why
   `derive.segment.spine` reads `owgraph-segment/1` — a host-assembled view over committed blocks —
   rather than calling a parse driver.

### 1.4 What the map deliberately does not show

Each of these is another document's fact. This document states the contract it depends on in one
line and links; duplicating any of it would give one fact two homes.

| the map shows | the fact it depends on | owner |
|---|---|---|
| `DocSink`, `Doc`, `Block` as boxes | the fifteen `Capabilities` fields, the five `Quote` tiers, `rebind()`'s three rules, the `addr`/`cite` grammars | [the document model](03-document-model.md) |
| `DriverCard`, `resolve()`, `DriverIO` as boxes | the card grammar, the gate order inside `resolve()`, `activate()`, the twelve conformance suites | [the driver system](04-driver-system.md) |
| `evidence.py`, `eval.py`, `admit.py` as boxes | the `SignalSpec` registry, the `[[rule]]` grammar, the shipped rule set, the thresholds | [ingest and routing](05-ingest-and-routing.md) |
| L3 as a table list | every L3 column, the resolution funnel's nine guards, Louvain, the grounding gate | [structure extraction](06-structure-extraction.md) |
| L2/L4 as boxes | the store DDL, the pragma order, the five channels' internals, the fifteen absence gates | [storage and retrieval](07-store-and-retrieval.md) |
| the Supervisor's five verbs | the claim SQL, the retry ladder's timing, AIMD's constants, the dep reverse index | [the runtime](08-runtime.md) |
| L6 as a box | `CompileV1`'s signature, `r1..r7`, the ten `GateStatus` values, the OPC writer's rules | [generation](09-generation.md) |
| the SERVE panel | `ActionSpec`, the four listed tools, the profiles, the hook events, the SDK surface | [interfaces](10-interfaces.md) |
| one box = one wheel | the repository tree, `pyproject.toml` contents, the release workflow, the weight ceilings | [repo layout](11-repo-layout.md) |

## 2. The component table

`Owner interface` is the type or protocol a component is *addressed through* — the thing another
component may depend on. Anything not in that column is an implementation detail a PR may change.

`Stability tier` is one of five, derived from charter §3.5's three version axes:

| tier | promise | changes on | guarded by |
|---|---|---|---|
| **T-CONTRACT** | a third party pins it and builds against it | a `CONTRACT` bump, only on a `RELEASE` MINOR, announced and migration-guided | G16 loads the previous two releases' conformance-template drivers against HEAD |
| **T-SCHEMA** | a published read contract over stored rows or digests | a `SCHEMA` major, with a two-release deprecation window | migration tests; `[DER]` objects are explicitly outside the promise |
| **T-PUBLIC** | semver'd with `RELEASE`, documented, SDK-typed | a MINOR may add, a MAJOR may remove | `omniweave/sdk/_generated.pyi` byte-diff (G25) |
| **T-GENERATED** | never hand-written; byte-identical to its generator's output | whenever its source declaration changes | G6, G18, G20, G25 `--check` |
| **T-INTERNAL** | none; may change on any `RELEASE` MINOR | freely | its own tests only |

> **Extends the charter.** The charter fixes three version *axes* but names no per-component
> stability vocabulary. These five tiers are that vocabulary, defined here so every later document
> can answer "may I depend on this?" without re-deriving it from §3.5. Nothing about the axes moves.
> Where a module is hand-written but *emits* a generated artefact, the module carries its own tier
> and the artefact is listed separately as T-GENERATED — a tier is a promise about one file, and
> collapsing the two made `omniweave.cli` read as un-editable.

| # | component | package / module | responsible for | explicitly NOT responsible for | owner interface | tier |
|---|---|---|---|---|---|---|
| 1 | Ports | `omniweave_ports` | the driver-facing vocabulary — `Port`, `CostClass`, `Isolation`, `ReplayClass`, `TrustTier`, `LicenceTier`, `Restriction`, `FailureClass`, `DriverError`, `ProbeStatus`, `ProbeVerdict`, `DriverIO`, `DriverMetrics`, `DriverResult` — and **four of the five Port protocols**: `AcquireV1`, `ParseV1`, `DeriveV1`, `EmbedV1` | any behaviour — it has no function with a side effect; `CompileV1`, the fifth, which lives in `omniweave_core.out` because its signature needs the framework types a target is validated by; no store, cache or config type | the module itself (~40 KB, stdlib only) | T-CONTRACT |
| 2 | Contract stamp | `omniweave_core.contract` | `CONTRACT: int`, `CONTRACTS_SUPPORTED: frozenset[int]`, `SCHEMA: int` (the store-schema major this build writes) and `SCHEMA_MINOR: int` (its minor, reset to `0` at a major bump) — the **sole code home** of both stamps, and the one site that formats `f"{SCHEMA}.{SCHEMA_MINOR}"` ([ADR-9](adr/0009-schema-single-home.md)) | deciding what the contract contains; holding the file's value, which is `index_state.schema`'s ([storage and retrieval](07-store-and-retrieval.md) §3.8) | four module constants | T-CONTRACT |
| 3 | Canonical digests | `omniweave_core.canonical` | `sha256_canonical(obj)` (canonical JSON, `allow_nan=False`) and `ow128(...)` = `blake2b(digest_size=16, person=<domain>)` | choosing what enters a digest — every caller owns its own recipe | two functions | T-SCHEMA |
| 4 | Identity | `omniweave_core.identity` | `canonical_uri`, `content_digest`, `config_digest`, `semantic_digest` | naming rows — `block_id`, `addr` and `cite` are L2's to mint | four functions | T-SCHEMA |
| 5 | Normalisers | `omniweave_core.ident` | `normalize_key`, the **blocking-key** normaliser (a bounded NFKC/casefold fixpoint then a `re.UNICODE` `\w` filter) called by the `anchor`/`ref_site` writers and by `op.resolve`, **vendored** from graphify's `ids.py` at a pinned SHA under `vendor/graphify-ids/`; `normalize_k`, the **grounding** normaliser called by `GraphSink.mention` and by `FieldGrounding`, which is **omniweave's own — graphify has no `normalize_k` original**; `nfc`, the **proof** normaliser INV-10's three branches compare whole strings under, which folds strictly less than either of the two above and carries no back-map ([ADR-5](adr/0005-byte-exactness-chain.md)); and `fold_common`, the shared `Cf`/dash/whitespace/NFKC table that lives here so [quality](13-quality.md) §8.2's `normalize_eval()` can compose it rather than copy it. Every one of the four has its operations, their order and its return type defined once — `normalize_k` and `nfc` in [structure extraction](06-structure-extraction.md) section 1.7, `fold_common` in [quality](13-quality.md) section 8.2 — and this row names them and does not restate them | restating `normalize_k`'s operations — section 1.7 is their one home; deciding which one a caller wants; they are **not** interchangeable and the four docstrings say so. It lives in core, not in `omniweave-graph`, because both callers are host-side | four functions | T-SCHEMA |
| 6 | Errors | `omniweave_core.errors` | the `OwError` tree, `.code()`, `.is_fatal()`, `.fix`; the `codes.toml` reader behind `ow explain` | recording diagnostics (`Diag` is L2's), findings (L6's) or rejections (`resolve()`'s) | `OwError`, `explain(code)` | T-PUBLIC |
| 7 | Limits | `omniweave_core.limits` | every `MAX_*` ceiling, the one `MIN_SQLITE = (3,42,0)` floor, and `effective = min(tenant_cap, declared, HOST_MAX)` | enforcing them — enforcement is at each read boundary with `take(N+1)`-then-check, so a limit is never discovered after the memory is spent; and **carrying any version constant**, now or ever: `SCHEMA` is a stamp with a two-release deprecation window, not a ceiling, so it lives in row 2 ([ADR-9](adr/0009-schema-single-home.md)) | module constants | T-PUBLIC |
| 8 | Config | `omniweave_core.config` | ~250 lines of property-tested flat scalar coercion, source tracking, the precedence chain, and each key's `semantic`/`operational` axis plus its `OMNIWEAVE_*` twin, declared at the key's site | validating a *driver's* config — that is the closed JSON-Schema-2020-12 subset validator in `omniweave` and `omniweave-conform`, off the hot path | `load() -> Config`, `Config.get`, `Config.source_of` | T-PUBLIC |
| 9 | Probes | `omniweave_core.probe` | running a candidate's `probe()` at preflight, memoising the `ProbeVerdict` for the life of the run, and persisting it under `$OMNIWEAVE_HOME/probe/<driver_id>/<version>/<card_sha256>/<env_digest>.json`, keyed `(driver_id, driver_version, card_sha256, env_digest)`, so a cold `ow doctor` need not re-probe | deciding what `degraded` means for a plan — `resolve()` filters on `ProbeStatus` and the router re-filters on `capabilities_lost`. The persisted entry is advisory: `ow doctor --runtime` always re-probes | `probe(candidate) -> ProbeVerdict` | T-INTERNAL |
| 10 | Operator vocabulary | `omniweave_core.operator` | `Operator` (**a `Protocol`**, not an abstract base class — the spelling `OperatorABC` is struck, [ADR-1](adr/0001-terminology-lock-bulk-pass.md) decision 7; [the runtime](08-runtime.md) §6.1 is its home), `OperatorIdentity` (**is** `Producer`), `StepResult`, `Outcome`, `StepMetrics`, `RunContext`, `Roots`, `CancelToken` | scheduling (L5's) and pricing (`route/spend.py`'s) | the `Protocol` plus the dataclasses | T-CONTRACT |
| 11 | Registry | `omniweave_core.registry` | `Registry[T]`; a duplicate id raises `DuplicateDriver` unless `replace=True` | resolving, ranking or activating | `Registry.register/get/items` | T-INTERNAL |
| 12 | Discovery | `omniweave_core.discovery` | building the `Catalog` from `importlib.metadata` + `tomllib` + `Distribution.locate_file()`, and the `driver_card_cache` validity key (mtime + size — measured **1.01 ms** for 328 distributions against **2124 ms** for a `RECORD` scan, charter D3) | importing anything (INV-4). `EntryPoint.load()` is banned in this package and G11 proves it | `catalog() -> Catalog` | T-INTERNAL |
| 13 | Driver resolution | `omniweave_core.drivers` | `DriverCard` parse + validation, `compute_tier()`, `resolve()` (pure, memoised on `(port, format, frozenset(floors.items()), max_cost_class, policy_digest, catalog_digest)`), `Rejection`/`RejectCode`, `activate()` — the only site that imports a card's `entrypoint` — and the framework tombstones | **choosing a winner.** `resolve()` returns candidates in ascending `driver_id` order, which is a canonicalisation forced by `resolution_digest` and not a ranking; ranking is the router's | `resolve(Requirement, Catalog, RoutePolicy) -> Resolution` | T-CONTRACT |
| 14 | Driver hosts | `omniweave_core.host` | `wire.py` (framing only, ~80 lines, fuzzed: `header_len <= 1 MiB`, `body_len <= INLINE_MAX`, JSON depth 32, an unknown `kind` is a protocol error), `inproc.py` (`DriverGuard`), `subproc.py` (one long-lived worker per `(driver_id, config_digest)`, `worker_idle_ttl_s = 300`) | batching policy, retries and quarantine decisions — all `omniweave/run/dispatch.py`'s | `DriverHost.invoke(Batch) -> Sequence[DriverResult]` | T-CONTRACT |
| 15 | Model server client | `omniweave_core.modelserver` | seam S3: `ServiceSpec`, `ServiceHandle`, `attach_or_spawn`, `ServiceRegistry`, model-id verification on attach, the 32-byte token in a 0600 sentinel | choosing a model (config's `[services.*]` does) or routing to one — a Service is **named and never routed** | `ServiceRegistry.get(name) -> ServiceHandle` | T-CONTRACT |
| 16 | Toolchain client | `omniweave_core.toolchain` | seam S2: `ToolchainSpec`, `ToolchainResult`, `run(spec, job_dir, *, timeout_s, ctx)`, node resolution, **full**-sha256 verification, SIGTERM→SIGKILL+5 s process-group reaping | what the child does, and parsing its stderr — stderr is drained on a dedicated thread into an unbounded queue so the pipe cannot deadlock, kept as a bounded ring tail, and never parsed | `run()` | T-CONTRACT |
| 17 | Blobs | `omniweave_core.blobs` | the CAS: `put(BinaryIO) -> sha256`, `path(digest)`, refcount, mark-and-sweep, a headroom file | holding document bytes in a caller's memory — semgrep bans `.read()`/`read_bytes()` on a source path outside this module (I31) | `BlobStore` | T-PUBLIC |
| 18 | Cache | `omniweave_core.cache` | the one `cache_key()`; `CacheIndex`; `CacheLayer` (`blob`, `call`, `embed`, `render`, `signal`); `CacheVerdict`; the six-clause read policy; `put(entries, allowed_units=…)` with a runner-supplied allowlist | being the record of completion — that is `work.status='done'` plus a matching `work.cache_key`. There is no `parse` or `derive` layer: if it is a row in the `.owstore` it is never also a blob in the cache | `CacheIndex.get/put` | T-SCHEMA |
| 19 | Budget | `omniweave_core.budget` | `BudgetLedger` over `budget_reservation`; `Reservation`; headroom **computed in SQL**, never cached in an attribute | pricing (`Spend.micros(book)`'s job) and choosing a rung (INV-14) | `BudgetLedger.reserve/commit/release/headroom` | T-SCHEMA |
| 20 | Deps | `omniweave_core.deps` | `Dep`, the closed `DepKind` (`unit`, `part`, `name`, `cohort`, `policy`, `service_model`), `record_deps`, `invalidate(delta)` as **one query** over the reverse index, `cohort_digest` | observing a driver's reads — impossible by design (INV-6), so a driver declares a `witness_set` or takes a cohort digest and pays | `invalidate(delta) -> set[int]` | T-SCHEMA |
| 21 | Events | `omniweave_core.events` | `Event`, `TraceSink`, `NdjsonSink`, `ConsoleSink`, `traceparent`, the closed `EVENTS` vocabulary loaded from `tools/events.toml`; a bounded 64k queue, drop-oldest, the drop count surfaced as a `Degradation` and counted into `run.events_dropped` | exporting to OTLP — that is `omniweave_serve.otlp`, the only module where `opentelemetry` may be imported. The vocabulary file itself is append-only data (G20) and `schema/event-v1.json` is generated from it | `TraceSink.emit(Event)` | T-SCHEMA |
| 22 | Work vocabulary | `omniweave_core.work` | `WorkRow`, `FailureClass` re-export, `classify()`, the claim/complete/reap SQL, the retry ladder | running the loop (L5's job) | the SQL plus `WorkRow` | T-SCHEMA |
| 23 | Locks, clock | `omniweave_core.locks`, `.clock` | the scoped cross-process lock (`O_CREAT\|O_EXCL` + `flock`, holder identity `(host, pid, process_create_time)`); the injected `Clock` protocol | ambient time — `time.time()` is banned in library code; a lease is stamped from **the store's** clock (`unixepoch('subsec')*1000 + :lease_ms`), never a worker's, and what makes a late result from an expired lease harmless is the commit predicate's `claimed_gen`, not the clock | `scoped_lock()`, `Clock` | T-INTERNAL |
| 24 | L2 model | `omniweave_core.model` (lazy) | `owdoc`: `Block`, `BlockDraft`, `Page`, `Part`, `Asset`, `Rel`, `Grid`, `Mark`, `Capabilities` (15 fields), `Quad`, `TextSpan`, `OriginSpan`, `Cite`, `Addr`, `Diag`, `DocSink`, `Doc`, `rebind()`, `SERIALIZER_CAPS`; `model/taint.py`'s `Taint` and `MAX_TRUST_BY_METHOD` | carrying a format a driver chose — `serialize()` is core's own over five core-owned formats, and no model class has an `html`, `markdown` or `md` field (a build-failing test asserts it) | `DocSink` to write, `Doc` to read — see [the document model](03-document-model.md) | T-SCHEMA |
| 25 | Archive | `omniweave_core.archive` (lazy) | the `.owdoc` codec: a plain ZIP of `ZIP_DEFLATED` NDJSON Frames plus `frames.json` and a pretty-printed `manifest.json`; `owcheck` | being the canonical form — the `.owstore` is; `.owdoc` is a lossless projection held to `import(export(store)) == store` (G6) | `export(store, path)`, `import_(path, sink)` | T-SCHEMA |
| 26 | Store | `omniweave_core.store` (lazy) | the only `sqlite3.connect` (INV-17); the pragma order with `busy_timeout` first; heal-on-open; the WAL valve; the `connect_readonly` ladder; `Store` (4 methods), `Reader` (6), `Snapshot` (an opaque backend-owned token) | planning a retrieval (`retrieve/plan.py`'s job) and being multi-writer — one writer per store at v1, tenancy is store-per-tenant | `Store`, `Reader` (T-CONTRACT); the `[SOR]` DDL is T-SCHEMA — see [storage and retrieval](07-store-and-retrieval.md) | T-CONTRACT |
| 27 | Retrieval | `omniweave_core.retrieve` (lazy) | `Query`, `Filters`, `Narrowing`, the five `CHANNELS`, `ChannelResult`, `plan()` (pure, memoised), `fuse()` (RRF at `RRF_K = 60`, `SCORER_VERSION = 1`), `ceiling()`, `Verdict`, `build_verdict()` with the one `ABSENT` return site, `Expand`, `expand()` | packing an answer (row 28's job) and owning the schema (row 26's) | `retrieve(Reader, Query, RetrievalPolicy) -> Response` | T-PUBLIC |
| 28 | Answer | `omniweave_core.answer` (lazy) | `worth`, `allocate`, `dedup`, `untrusted` (`wrap_untrusted`, `sanitize_label`), `render`; `budget.py`'s five block-count-tiered budget layers from `[serve.packing] tier`; the fixed-section Answer document | deciding what to ask, and transport (serve's job) | `render(Response, AnswerBudget) -> Answer` | T-PUBLIC |
| 29 | OUT framework | `omniweave_core.out` (lazy) | `CompileV1`; `Finding` with orthogonal `Severity`/`Provenance`; `ConstructTable`; `RulePack` + `run_pack()`; `GateStatus` (10, exactly one permits a release); `Plan`/`Unit`/`UnitOutcome` (7); `Brief`; `AssetLedger`; the `OWC1` marker grammar; `ManualReason`/`ManualEvidence`; `Receipt`; `roundtrip.py`'s `r1..r7`; `opc.py`, the only `zipfile`-for-write in the framework; `job.py` | implementing a target. There is deliberately **no** `validate()` on `CompileV1` — a target that could run its own gate could skip it | `CompileV1` — see [generation](09-generation.md) | T-CONTRACT |
| 30 | Surface registry | `omniweave.surface` | `ActionSpec`, `ACTIONS`, `HUMAN_ONLY`, `Profile`; invariant SV1 (`set(listed) ⊆ set(enabled)`, `HUMAN_ONLY ∩ enabled = {}`) as a startup check | emitting the artefacts (row 31's job) and hand-writing any of them (INV-20) | `ACTIONS` | T-PUBLIC |
| 31 | Surface generators | `omniweave.gen` | `ow surface emit`: the seven agent-facing artefacts — `schema/mcp-tools-v1.json`, the two MCP `instructions` variants, the CLI argparse tree, `omniweave/sdk/_generated.pyi`, `llms.txt`, `docs/AGENTS.md`, `skills/omniweave/references/actions.md` — plus `ow surface typescript <dir>` | deciding what an Action is (row 30's job) | `ow surface emit [--check]`; every output is T-GENERATED | T-INTERNAL |
| 32 | CLI | `omniweave.cli` | the `ow`/`omniweave` console script (one script, two names); the exit-code mapping; `OwError` → exit code + `code`/message/`fix`, never a traceback | defining capabilities (row 30) or generating its own parser (row 31) | `ow <group> <verb>` — see [interfaces](10-interfaces.md) | T-PUBLIC |
| 33 | SDK | `omniweave.sdk` | the public Python API, sync + async twins, semver'd with `RELEASE`, typed by `_generated.pyi` | a hand-written TypeScript port — `ow surface typescript` generates types plus a ~120-line zero-dependency client from the same gated schemas | `omniweave.sdk` | T-PUBLIC |
| 34 | Hooks | `omniweave.hooks` | `ow hook <event>`: stdin JSON in, a bounded injection out, a 400 ms self-deadline, **every failure path a silent exit 0**, counter names only and never prompt text | being importable by the Supervisor, or importing it — a hook must not pay a loop import (G26, INV-3) | `ow hook <event>` — see [interfaces](10-interfaces.md) | T-PUBLIC |
| 35 | Router | `omniweave.route` | `Rung` (7, closed, ordered), `LANES` (open), `Spend`, `PriceBook`, the `SignalSpec` registry, `Evidence` with its read log, `evaluate()` (pure), `admit()`, `RouteHints`, `Degradation`, the policy loader, the subsumption linter and the isotonic threshold fitter | inventing a driver — it ranks `resolve()`'s candidates — and pricing inside a driver (INV-15) | `evaluate()`, `admit()` — see [ingest and routing](05-ingest-and-routing.md) | T-PUBLIC |
| 36 | Ingest planner | `omniweave.plan` | the single `INSERT` that creates a routed `work` row, carrying `driver`, `decision_id`, the denormalised `dispatch_key` and the recorded `cache_key` together — so two rows share one `INVOKE` iff they share that key, and I1's idempotence check has a key to compare | claiming, dispatching or completing (row 37's job); deciding the winner (row 35's) | `work` rows — see [the runtime](08-runtime.md) | T-INTERNAL |
| 37 | Supervisor | `omniweave.run` | the one `asyncio` loop; roster discovery; `op.identify` behind the water mark; `Batch` formation with AIMD and crash quarantine; the middleware order; `op.converge`; the run manifest | executing driver code (the `DriverHost` does) and holding document bytes (I31) | `run(Scope, RunContext) -> RunManifest` — see [the runtime](08-runtime.md) | T-INTERNAL |
| 38 | Host graph passes | `omniweave.graph` | `op.lexicon`; `op.resolve` (the nine-guard funnel, MinHash/LSH bands persisted in `entity_band`, Jaro-Winkler ≥ 92.0, union-find with a deterministic survivor); `op.cluster` (pure-Python Louvain over an `array('i')` CSR from one SQL scan) | being drivers — they need a corpus-wide store view and a driver may not hold a store handle | three `Operator` implementations | T-INTERNAL |
| 39 | Install | `omniweave.install` | MCP config, permissions, instructions, hooks and the core skill; `AgentTarget`, `FileAction`, `atomic_write`, `json_deep_equal`, `read_json` (backs up an unparseable config first), marked-section upsert/remove, `refresh_targets()`; the install receipt with a post-write sha256 per path | deciding what a host permits | `AgentTarget.install(loc, opts) -> WriteResult` ([interfaces](10-interfaces.md) §7.1) | T-PUBLIC |
| 40 | MCP server | `omniweave-serve` | the `stdio` and `http` transports; the four listed tools; `ow trace export [--follow]` in `otlp.py`; a non-loopback bind refused without `--api-key` | running the Supervisor, and importing `omniweave` at all | the MCP protocol | T-PUBLIC |
| 41 | Office driver | `omniweave-office` | `parse.office.anydoc` over `firecrawl-anydoc == 0.2.4`; DOCX/ODT/RTF/EPUB/CSV/TXT/MD/HTML decode across seam S1 | per-block source addresses. Its card declares `origin_span = "none"` because `anydoc/src/model/block.rs:5-38`'s eight `Block` variants carry no source address of any kind — only `Asset` carries `origin_part` (`src/model/asset.rs:15`) — so `quote = verbatim` is unreachable on the office path at release 1 and `corpus_card.verbatim_fraction` discloses it | `ParseV1` | T-INTERNAL |
| 42 | PDF driver | `omniweave-pdf` | `parse.pdf.pdfium`: the text layer and glyph runs (INV-10's `glyphs` branch), page geometry, page rasters at a requested DPI | layout classification — there is no licence-clean detector at release 1 (F4), so `layout.class_hist` is absent and every affected decision records `cause = "layout_unavailable"` | `ParseV1` | T-INTERNAL |
| 43 | Vision driver | `omniweave-vision` | `parse.page.olmocr` and nothing else — a `derive.*.vlm` pass is out of the release-1 ladder ([ADR-8](adr/0008-input-surface-and-pass-ladder.md) D8.3) — reaching a model through `io.service("vlm")`; the only distribution carrying `torch`, and the only one exempt from the 250 MB aggregate gate (G2) — it must print its resolved installed size during `ow doctor` | hosting a model (S3 does), pricing its GPU time (INV-15), and any `derive/1` pass | `ParseV1` | T-INTERNAL |
| 44 | Graph drivers | `omniweave-graph` | the seven free `derive/1` passes: `derive.segment.spine`, `derive.anchor.{native,defterm}`, `derive.xref.{native,pattern}`, `derive.entity.{table,gazetteer}` | writing L3 rows — `GraphSink` is host-side and a pass emits `owgraph-items/1` | `DeriveV1` — see [structure extraction](06-structure-extraction.md) | T-INTERNAL |
| 45 | LLM drivers | `omniweave-llm` | the four `billed_api` passes `derive.{merge,entity,claim,report}.llm`, reaching a model through `io.service()` — which is why the distribution is ports-only and 2 MB and needs neither `torch` nor core | choosing to run: they are absent from the shipped `[graph.passes] enable`, therefore off | `DeriveV1` | T-INTERNAL |
| 46 | Targets | `omniweave-target-{pptx,docx,deck,video}` | four target-owned artefacts each: `constructs.toml`, a `RulePack` of one-function-per-file predicates, `lower()`, `read_back()`; plus `project()` where the card declares it. `measure.py` is imported by **both** `rules/` and `lower/`, which is the whole point | validating themselves — the framework validates from `rules()` plus `constructs.toml` | `CompileV1` plus a sibling `ParseV1` | T-INTERNAL |
| 47 | Conformance | `omniweave-conform` | the twelve suites (`card`, `purity`, `contract`, `capability`, `idempotence`, `determinism`, `limits`, `sandbox`, `cost`, `licence`, `fuzz`, `quality`), the driver testkit (~120 property tests), the eval harness, the reducers, the Cassette codec, the calibrator, the scoreboard generator, and the reference target `compile.text.owtext` | shipping in a runtime install, and being run from a PR branch — CI checks the kit out at a trusted tag | `ow conform`, `omniweave_conform.testkit` | T-PUBLIC |
| 48 | Toolchains | `toolchains/{_shared,deck,video}` | non-Python execution bundles: `target-runtime.ts` (the framework-owned hello/ready/validate/compile loop) plus one app per Toolchain target, with their own `pnpm-lock.yaml` | being a Python dependency — no `pip install` ever pulls a JavaScript runtime. Installed by `ow targets install`, digest **in the path**, verified on every invocation | `omniweave-target/1` | T-CONTRACT |
| 49 | Generated schemas | `schema/*.json` | the language-neutral contract: `document-v1`, `fragment-v1`, `job-v1`, `receipt-v1`, `event-v1`, `driver-card-v1`, `run-manifest-v1`, `answer-v1`, `verdict-v1`, `mcp-tools-v1`, `open-out-v1`, `corpora-out-v1`, `add-out-v1`, plus `il-digest-v1.md`, the cross-language parity spec | being a source of truth — they are emitted from the Python definitions and byte-diff gated (G6) | the JSON files | T-GENERATED |
| 50 | Declaration files | `codes.toml`, `tools/{layers,weights,licences,vendor,indexes,config_axes,events,scorekinds,embeddings,wirekeys}.toml` | the data every gate reads: the one error register (append-only, G13), the import DAG (G4), the size ceilings (G2), the licence allowlist (G3), the config axes (G18), the event vocabulary (G20), the confidence scales | being edited to make a gate pass — each is either append-only against the previous tag or generated from a declaration site | the TOML files — see [repo layout](11-repo-layout.md) | T-GENERATED |
| 51 | Data artefacts | `omniweave-golden`, `omniweave-index` | the Tier-B eval corpus and the static pre-install card-stub index. Both a plain ZIP with `ZIP_DEFLATED` members + `manifest.toml` + `.sha256`, installed by digest into `$OMNIWEAVE_HOME/`, re-verified on every use, read through [security](14-security.md) §2.2's bounded reader — a stdlib-only install has no zstd decoder, so `.tar.zst` is not available to them ([ADR-10](adr/0010-data-artefacts-and-weight-ceiling.md)) | **being wheels.** They are versioned data artefacts, and a digest mismatch is a permanent failure that never triggers a fetch | a digest-named directory | T-SCHEMA |

Three rows deserve a second reading of their non-responsibility column, because each names an
architecture mistake this design refuses outright.

**Row 13.** `resolve()` does not choose, because the moment resolution ranks, it ranks
*expressiveness* rather than accuracy — a VLM claiming `cells_with_spans` would beat a better
`flat_html` driver on a ragged financial table. Filtering and ranking are two jobs, and only one of
them can be pure.

**Row 29.** The OUT framework does not delegate validation, because a target that could run its own
gate could skip it. `CompileV1` therefore has `rules()` and no `validate()`.

**Row 30/31.** The Action registry does not emit, and the emitters do not declare. One definition,
seven generated artefacts, one byte-diff gate — which is what makes INV-20 checkable instead of
aspirational.

## 3. The dependency rule set

### 3.1 The layering

```text
                          +----------------------+
                          |   omniweave_ports    |  depends on NOTHING. Versioned by Port MAJOR.
                          +----------^-----------+  The only distribution with no first-party edge.
                                     |
       +-----------------------------+----------------------------------+
       |                             |                                  |
 +-----+---------------+  +----------+-------------------+   +----------+-------+
 | DRIVER DISTS        |  |       omniweave_core         |   |   TOOLCHAINS     |
 | office  pdf  vision |  | stdlib + ports. Zero third   |   |  toolchains/*/   |
 | graph   llm         |  | party (INV-2). SYNCHRONOUS:  |   |  pnpm, not pip.  |
 | ports only, rule 3  |  | no asyncio, no selectors(G23)|   |  NOT A PYTHON    |
 +---------------------+  +-----^-------------------^----+   |  DEPENDENCY.     |
   ^                            |                   |        +------------------+
   | office is ALSO the one     |                   |
   | first-party edge out of    |          +--------+-------+
   | `omniweave` (F33)    +-----+----+     | omniweave-serve|
   |                      |omniweave |     | MCP + otlp.py  |
   +----------------------+  (CLI)   |     +----------------+
                          +----------+     NEVER imports omniweave
                                           NEVER runs the Supervisor

  compile-driver distributions — rule 4: ["omniweave_core", "omniweave_ports"]
  +-------------+ +-------------+ +-------------+ +--------------+ +-------------------+
  | target-pptx | | target-docx | | target-deck | | target-video | | omniweave-conform |
  +-------------+ +-------------+ +-------------+ +--------------+ +-------------------+
       (conform is here because it ships the reference target compile.text.owtext)
```

`omniweave-office` appears twice on purpose: it is a ports-only driver distribution under rule 3
**and** the single first-party dependency of `omniweave`. That edge is the only one in the graph not
forced by a protocol, and F33 is the written question of whether it survives.

**`acquire/1` is a live Port with no in-tree implementation at release 1**, which is why no
`acquire.*` box appears above. Filesystem discovery is core-side, in `omniweave/run/discover.py`,
which owns the connector cursors, and `unit.connector` defaults to `'fs'`. A shipped `acquire.fs.local`
could not live in the `omniweave` distribution in any case: rule 3 would then demand the row
`["omniweave_ports"]` for a package that also holds the Supervisor. Charter §3.1's parenthetical
"(fs, url, connectors)" is loose prose, retired by erratum `E39`, and **this paragraph is its sole
superseding home** — so [repository layout](11-repo-layout.md) §1.2's distribution table stays at
fourteen rows and §3.2's `layers.toml` at fourteen lines ([ADR-3](adr/0003-shipped-configuration.md)).

### 3.2 The enforceable statement

`tools/layers.toml`, verbatim from charter §3.3:

```toml
omniweave_ports        = []
omniweave_core         = ["omniweave_ports"]
omniweave_office       = ["omniweave_ports"]
omniweave_pdf          = ["omniweave_ports"]
omniweave_vision       = ["omniweave_ports"]
omniweave_graph        = ["omniweave_ports"]
omniweave_llm          = ["omniweave_ports"]
omniweave_serve        = ["omniweave_core", "omniweave_ports"]
omniweave_target_pptx  = ["omniweave_core", "omniweave_ports"]
omniweave_target_docx  = ["omniweave_core", "omniweave_ports"]
omniweave_target_deck  = ["omniweave_core", "omniweave_ports"]
omniweave_target_video = ["omniweave_core", "omniweave_ports"]
omniweave_conform      = ["omniweave_core", "omniweave_ports"]
omniweave              = ["omniweave_core", "omniweave_ports", "omniweave_office"]
```

A row is the **complete allowed set of first-party import roots** for that package, transitively
closed. `omniweave_serve = ["omniweave_core", "omniweave_ports"]` therefore means that
`import omniweave` anywhere under `omniweave_serve/` is a gate failure — inside a function body and
inside an `if TYPE_CHECKING:` block included.

The four clauses, and which of them a gate *reads* rather than trusts:

| rule | statement | how G4 knows |
|---|---|---|
| 1 | `omniweave-ports` depends on nothing | its `dependencies = []`, asserted by G1's clean-environment resolve, which also asserts `omniweave_ports` resolves to itself alone |
| 2 | `omniweave-core` depends on `omniweave-ports` and no third party | G1 resolves core in a clean environment and asserts exactly that pair; G9 runs `python -X importtime -c "import omniweave_core"` and asserts zero third-party modules |
| 3 | a distribution declaring only `acquire`/`parse`/`derive`/`embed` drivers has the row `["omniweave_ports"]` **exactly** | G4 reads `[project.entry-points."omniweave.drivers"]`, locates each named package's `driver.toml` **without importing it**, reads `port`, and derives the required row. Adding `omniweave_core` to such a row fails the gate |
| 4 | a distribution declaring a `compile` driver has the row `["omniweave_core", "omniweave_ports"]` | the same read. `CompileV1` lives in `omniweave_core.out` because its signature mixes ports types (`DriverIO`, `DriverResult`) with the OUT framework types a target is validated by (`Plan`, `ILBundle`, `AssetLedger`, `RuleSpec`, `CarrierDoc`), and a Protocol has to live in one distribution |

The consequence to know by heart: **a driver cannot pin the framework.** An
`acquire`/`parse`/`derive`/`embed` driver's only permitted omniweave imports are `omniweave_ports`
and, dev-only, `omniweave_conform.testkit`. A `compile` driver additionally imports
`omniweave_core ~= <MAJOR>.<MINOR>.0` for the OUT framework it is validated by, and that carve-out is
the whole of the exception. Moving those four target rows plus `omniweave-conform` is a `CONTRACT`
bump: an announced, migration-guided event on a `RELEASE` MINOR.

### 3.3 How it is checked in CI

There is no third-party import linter. `import-linter` and `grimp` are not in the dev dependency
group D1 prints — `["pytest~=9.1", "pytest-xdist", "ruff", "pyright", "semgrep", "hypothesis",
"atheris", "msgpack", "zstandard", "tiktoken"]` — and introducing one would put a package's own
import graph between HEAD and the gate that proves HEAD's import graph. Enforcement is three
first-party mechanisms:

| mechanism | file | what it does | gate |
|---|---|---|---|
| the layer gate | `tools/gate_layers.py` | walks every `packages/*/src/**/*.py` with `ast.parse`, collects every `Import`/`ImportFrom` at module, class and function scope (`TYPE_CHECKING` blocks included), maps each to its first-party root, and asserts membership in that package's `layers.toml` row. Then re-derives every row from that distribution's entry points under rules 3 and 4 and asserts equality, so no author picks their own row | **G4** |
| the purity gates | `tools/gate_core_pure.py`, `tools/gate_lazy_core.py`, `tools/gate_importtime.py` | resolve `omniweave-core` in a clean environment (G1); run `-X importtime` and assert no third-party module and neither `asyncio` nor `selectors` (G9, G23); assert `import omniweave_core` imports none of `{model, store, archive, retrieve, answer, out, host, toolchain, modelserver}` (G17) | **G1, G9, G17, G23** |
| semgrep | `tools/semgrep/omniweave.yaml` | the site bans a layer graph cannot express: `sqlite3.connect` / `conn.commit()` / `BEGIN` / `import sqlite3` outside `omniweave_core/store/`; `subprocess` outside `toolchain.py` and `host/subproc.py`; `zipfile.ZipFile(..., 'w'\|'a'\|'x')` and `shutil.make_archive` outside `out/opc.py`; `opentelemetry` outside `omniweave_serve/otlp.py`; `EntryPoint.load()` under `core/drivers/`; `importlib.import_module` / `__import__` outside `host/`; `os.getcwd()` / `Path(".")` / `time.time()` / `random` / `secrets` / `uuid4` / `datetime.now` / `sys.exit` in library code, and all of them in `route/eval.py`, `retrieve/plan.py` and every `omniweave-target-*`; a bare `except` around a digest, cache key, code fingerprint, probe, baseline read or retrieval channel; `revision="main"`; a `DriverHost.invoke()` call outside `run/pipeline.py`; an `html`/`markdown`/`md` field on a model class; a second `return VerdictState.ABSENT` site | **G8, G24** |

> **Extends the charter.** The charter lists `tools/gate_layers.py` in its `gate_*.py` inventory but
> does not say how the module graph is built. It is built with the stdlib `ast` module, walking
> source rather than importing it — which also means the gate runs on a package whose dependencies
> are not installed, and keeps the dev dependency group exactly as D1 prints it.

Two worked violations, so the gate's output is predictable rather than a puzzle:

```text
$ python tools/gate_layers.py
G4 FAIL  packages/omniweave-pdf/src/omniweave_pdf/driver.py:14
         import omniweave_core.model
         omniweave-pdf declares only parse/1 drivers, so its layers.toml row must be
         ["omniweave_ports"] exactly (charter §3.2 rule 3). A parse driver emits
         owdoc-fragment/1; it never constructs a Block and never holds a DocSink.
         fix: emit the fragment. See _plan/04-driver-system.md.

G4 FAIL  packages/omniweave-serve/src/omniweave_serve/tools/query.py:9
         from omniweave.run.supervisor import run
         omniweave-serve may not import omniweave (§3.3 consequence 2) and never runs the
         Supervisor (consequence 3). Retrieval lives in omniweave_core.retrieve precisely so
         that three surfaces call one implementation and none of them owns it.
         fix: call omniweave_core.retrieve.retrieve(); enqueue a refresh through ow_add.
```

### 3.4 The four seams as dependency edges

A seam is where the import graph stops and a *protocol* starts. Naming exactly four is what keeps
the process topology reviewable: everything not on this list runs in the host process.

| seam | importer | protocol | who may cross | why the boundary sits here |
|---|---|---|---|---|
| S1 | `omniweave_core.host.inproc` | a Python call, `py.detach` around the decode | `omniweave-office` only, and only under DR9's five conditions (first-party or vendored, free, GPU-less, network-less, fuzz-green) plus an id in `[drivers] inproc` | anydoc's measured **4.4 ms** median across fourteen formats (`anydoc/README.md:176`, its own harness, 100 documents, against 134.8 ms for markitdown, 513.6 ms for docling and 1129.5 ms for LibreOffice) against a **200–800 ms** cold Python worker. A one-shot `ow parse report.docx` has exactly one unit to batch, so a uniform `subproc` tax would be a two-order-of-magnitude regression on the framework's cheapest and most frequent route |
| S2 | `omniweave_core.toolchain` | `omniweave-target/1`, NDJSON on stdio plus a job directory | any Toolchain target (`deck`, `video`) | a language boundary carrying a ~30-field job envelope and a receipt. Blobs never travel on stdio; stdout is control only and under 1 MiB per invocation; stderr is a log drained to a bounded ring and never parsed; exit 0 iff a receipt was written |
| S3 | `omniweave_core.modelserver` | HTTP over loopback, a 32-byte token in a 0600 sentinel, model-id verification on attach | GPU VLM Services | server-side **Coalescing** merges requests across worker *processes*, which host-side batching cannot do (surya `common/batch_service/server.py:79-99` `_drain()`: block for one job, coalesce within `batch_wait_ms = 5`, ceiling `max_batch = 8`) |
| S4 | `omniweave_core.host.subproc` | `omniweave-driver/1` over a 0600 unix socket or an owner-only named pipe | every third party, every GPU driver, every driver with egress | the mined evidence: segfaulting C parsers; `subprocess.run` on `libreoffice` with no `timeout=`; `MAX_RETRIES = 5 × REQUEST_TIMEOUT = 1200` = 100 GPU-minutes per document in Unlimited-OCR; codegraph's measured 22 GB WAL and exit-137 OOM. In process, each of those kills the run and discards completed work; out of process, each is one row |

A fifth seam is a charter amendment. A long-lived local IPC daemon for parsing, embedding, indexing
or scheduling is banned outright, and only `omniweave_core.toolchain` and
`omniweave_core.host.subproc` may import `subprocess` (G8). Two loopback TCP endpoints are
sanctioned and no third may be added: an attached or spawned model server (S3, token-authenticated)
and `ow serve --http`, which refuses a non-loopback bind without `--api-key`
(`OW_HTTP_BIND_UNAUTHENTICATED`, `OW-A-040`).

**The seams do not compose, and that is a design consequence rather than an omission.** A Toolchain
child (S2) receives a job directory and an NDJSON control channel; it does not receive a `DriverIO`,
so it has no `io.service()` and therefore cannot reach a Service across S3. A target that needs a
model is a `subproc` compile driver (S4 + S3), not a Toolchain target. Likewise an `inproc` driver
(S1) is barred from egress by DR9's `needs_network == false` condition, so S1 + S3 is unreachable by
construction. The only composition that exists is S4 + S3 — a `subproc` driver reaching a Service —
and it is the one every GPU path uses.

## 4. The end-to-end data flow

Three scenarios, traced hop by hop with the real type at each hop. Where a hop crosses a process
boundary the seam is named. Where a hop writes a row the table is named. Indexes are maintained by
those inserts and are not listed as writes — `block_addr` and `block_cite` are unique indexes on
`block`, not tables.

**One ordering constraint governs every ingest trace and is worth stating before the tables**, because
two schema facts force it and no author may reorder it. `work.decision_id REFERENCES
route_decision(decision_id)`, and `work`'s CHECKs pair `driver` with `dispatch_key`, make an `op.*` row
carry neither, and require a decision of every other row except a FREE `derive.*` one (06 section 1.7:
`decision_id` is "NULL for a free Pass"; D665). A `parse.*` or billed `derive.*` work row therefore
**cannot exist before its route decision does**: the FK has no referent and a CHECK fails. Consequently the expander
task runs two modules in order — `run/expand.py` executes `op.identify` (an `op.*` work row, all
three routing columns NULL, batching alone) which persists `unit.part_count`; then, per part,
resolution, evidence, `evaluate()`, `admit()` and finally `omniweave.plan`'s single `INSERT`
carrying `driver`, `decision_id`, `dispatch_key`, `cost_class` and the recorded `cache_key` together.
There is no window in which a routed work row is half-populated, and there is no `UPDATE work SET
driver = …` anywhere in the codebase.

### 4.1 Scenario (a) — a born-digital PDF, ingested and then queried

**Ingest.** `ow ingest ./docs` with `./docs/eu-annual-report-2019.pdf`, 42 pages, a full text layer.

| # | component | receives | emits | writes |
|---|---|---|---|---|
| 1 | `omniweave.cli` → `ACTIONS["ingest"]` | argv | `Scope(roots, include, exclude)` + `RunContext(run_id, generation, roots, clock, cancel, admission, services, catalog)` | one `run` row: a monotonic `generation` (never a clock), `trigger='cli'`, argv, `config_digest`, `semantic_digest` and the four subordinate digests [the runtime](08-runtime.md) enumerates, the full-scan latch, `status='running'` |
| 2 | `omniweave.run.discover` | `Scope` | a stream of `unit` rows | `unit`: `unit_uri = canonical_uri(path)`, `connector='fs'`, `state='discovered'`, the stat triple `(size, mtime_ns, indexed_at_ns)` **captured before the content read**, at `[runtime] plan_batch = 512` rows per transaction; plus one `ingest_scope` row recording discovered vs indexed vs skipped |
| 3 | `omniweave_core.blobs` | the open file handle | a `sha256` | the CAS entry; `unit.content_sha256`, `unit.state='acquired'` |
| 4 | `omniweave.run.expand` → `op.identify` | `unit_uri` | `part_count = 42` | one `op.identify` `work` row (`driver`, `decision_id`, `dispatch_key` all NULL, `cost_class='free'`, batching alone), then `unit.part_count = 42`, `unit.state='identified'`. **No `parse.pdf` work row exists yet** — see the ordering constraint above |
| 5 | `omniweave_core.drivers.resolve` | `Requirement(port='parse/1', format='pdf', floors={'text_span': True}, max_cost_class=CostClass.LOCAL_COMPUTE, granularity='part')`, `Catalog`, `RoutePolicy` | `Resolution(requirement, candidates=(Candidate(parse.pdf.pdfium), Candidate(parse.page.olmocr)), rejected=(Rejection(…),), catalog_digest, policy_digest, resolution_digest)` — semantically unordered, emitted in ascending `driver_id` so that `resolution_digest` is canonical | one `resolution_report` row per `(run_id, resolution_digest)` with a hit counter — **not** one per part. The call is memoised, so 42 parts cost one resolve |
| 6 | `omniweave.route.evidence` (a demand plan) | the part | `Evidence` with the FREE group computed first: `decode.char_count = 3184`, `decode.line_count = 71`, `decode.has_text_span = true`, `garble.score = 0.02` | `route_signal` rows keyed per signal, with refcounted blobs in `route_evidence`; accounted under `CacheLayer.signal` |
| 7 | `omniweave.route.eval.evaluate` | `(RoutePolicy, Evidence, RouteHints)` — **no ledger, no clock, no RunContext** (INV-14) | `RouteDecision(rung=Rung.DECODE, lane='text', driver='parse.pdf.pdfium', read_set_digest=<sha256 over the read set>, cause=None, …)` — the `…` elides the rest of [05](05-ingest-and-routing.md) §4.6's shape. Rule `decode.pdf-text-layer` matches on `unit.format = 'pdf'` and `decode.char_count > 0`; then `decode.skip-block-recheck-on-clean-parts` sets `skip_rungs=['REPAIR']` because `garble.score = 0.02 < @thresholds.garble_recheck = 0.05` | `route_decision`, written **before any driver runs and before the work row exists**, carrying the winning rule with its file and line, the read set with provider versions, the estimate, and `route_unit_decision` so cost provenance outlives the queue |
| 8 | `omniweave.route.admit.admit` | `(RouteDecision, BudgetLedger)` | `Admitted(reservations=())` — a `free` decision reserves nothing | nothing |
| 9 | `omniweave.plan` | `(Resolution, RouteDecision)` | the routed `work` row | one `INSERT` per part: `operator='parse.pdf'`, `op_version=<int>`, `unit_part='p1'..'p42'`, `status='pending'`, `driver='parse.pdf.pdfium'`, `decision_id`, `dispatch_key = sha256(driver_id‖config_digest‖isolation)[:16]`, `cost_class='free'`, and `cache_key` from the **free** recipe of §8.3 — recorded, so a later config change is a mismatch and never a silent reuse (I1) |
| 10 | `omniweave.run.dispatch` | claimed `WorkRow`s grouped by `dispatch_key` | a `Batch` of up to `[runtime.claim] batch.free = 256`, clamped by the card and AIMD-adapted | `work.status='claimed'`, `claimed_by='<host>:<pid>:<create_time>'`, `claimed_gen`, `lease_expires` from the **store's** clock |
| 11 | `omniweave.run.pipeline` | `Batch` | passes through `with_events → with_request_count → with_cache → with_budget → with_retries → with_rate_limiting → with_metrics → with_fault_injection` | on a `CacheVerdict.hit`, returns here with `was_cache_hit=True` and `Spend` replayed from `cache_index.spend_json`; zero budget, zero tokens, zero rate-limit slots consumed (I25) |
| 12 | `omniweave_core.host.subproc` (**S4**) | `Batch` | `HELLO{port, card_schema, card_sha256, driver_id, effective_config, roots:{source_ro, tmp}, blob_base, isolation_granted, traceparent}`, `HELLO_ACK` checked against the card (`CARD_CODE_MISMATCH` before any work), then `INVOKE{invoke_id, units, deadline_ms, budget_micros}` | one worker per `(driver_id, config_digest)`, run-scoped |
| 13 | `parse.pdf.pdfium` (child) | `UnitRef`, `PartSelector`, `DriverIO` | `owdoc-fragment/1` NDJSON as an `ArtifactRef` — inline under `INLINE_MAX = 262,144` bytes, else a CAS blob ref; `RESULT`, **one frame per unit** | nothing in the store: it has no store handle (INV-6) |
| 14 | `omniweave_core.host.wire` | `u32 header_len ‖ u32 body_len ‖ JSON header ‖ raw body` | `DriverResult(outcome='ok', produced=(ArtifactRef,), partial_reason=None, metrics=DriverMetrics(wall_ms=…, bytes_read=…))` | — |
| 15 | `omniweave.run.pipeline` (the runner) | `DriverResult` | `StepResult` — adding `producer_id`, `origin_operator='parse.pdf'`, `origin_driver='parse.pdf.pdfium'`, `method=Method.TEXT_LAYER`, `restriction_bits`, `trust` after the `MAX_TRUST_BY_METHOD` clamp, `was_cache_hit`, and priced micros (INV-7, INV-15) | — |
| 16 | `omniweave_core.model.DocSink` (host-side) | the decoded fragment, block by block | `BlockId`s, minting `addr` and `cite` from `doc.next_cite_n` | `doc`, `page`, `block`, `part` (retained because `origin_span='glyphs'` satisfies `[store] retain_parts='when_citable'`), `mark`, `rel`, `diag`. `end_page()` commits **one transaction** |
| 17 | `omniweave_core.store.Store.complete` | `(row_id, gen, StepResult)` | `bool` — the commit predicate is `WHERE id=:id AND claimed_gen=:gen AND status='claimed'` | in **one** transaction: the derived rows, `work.status='done'` + `work.cache_key`, the `dep` rows, the reservation commit and the `route_spend` row (I20) |
| 18 | the seven free `derive/1` passes | `owgraph-segment/1` (a Segment header plus its blocks, addressed by `cite` only) | seven `owgraph-items/1` draft streams | through `GraphSink`: `segment`, `segment_block`, `anchor`, `ref_site`, `block_link`, `entity`, `entity_alias`, `mention`, `edge`, `claim`; ungrounded or `tmp`-dangling drafts go to `quarantine`, never dropped |
| 19 | `omniweave.run.manifest` | the run's counters | `RunManifest` | `{output_root}/runs/{run_id}.json` and `omniweave.index.lock` (one sorted, timestamp-free line per document, ~200 B) |

**Query.** `ow query "what were 2019 emissions in the Rhine region"`.

| # | component | receives | emits |
|---|---|---|---|
| 1 | `omniweave.cli` → `ACTIONS["query"]` | argv | `Query(text=…, refs=(), filters=Filters(layers={Layer.BODY}, min_quote=…), mode='find', k=20, max_blocks=60, max_chars=24000)`. `Query` has no `corpora` field: one `Reader` is one store is one corpus |
| 2 | `omniweave_core.store.Reader.snapshot()` | — | a `Snapshot` — **one** `BEGIN DEFERRED` for every channel, hydration and the coverage scan, clamped by `[retrieval] snapshot_ms = 2000` under `MAX_SNAPSHOT_MS = 5000`. The deadline is a WAL-valve safety parameter, not a UX parameter: a held read transaction pins the WAL |
| 3 | `retrieve.plan.plan()` — pure, memoised on `(mode, channel set, filter-field set, policy_digest, caps_digest)` | `(Query, RetrievalPolicy)` | a `QueryPlan`: the channel order (cheapest first, and the order **is** the run order), each with its own `budget_ms` from `[retrieval.budget] channel_ms` |
| 4 | narrowing | `Filters` | `Narrowing` — the tagged result: `set` (a TEMP table plus its exact row count, from `INSERT INTO tmp_narrow SELECT … LIMIT PREFILTER_MAX+1`), or `all`, or `empty`. Above `PREFILTER_MAX = 200,000` narrowing becomes an over-fetch factor `clamp(1/selectivity, 1, 64)` and gate `filter_starved` fires if post-filtering leaves fewer than `k` |
| 5 | four channels — `semantic` reports `ChannelStatus.OFF` because `[retrieval] vectors = "off"` is the shipped default | `tmp_narrow` | four `ChannelResult(name, status, ranked, spans, grades, weight, reason, truncated_at_limit, ran_ms, cost)` |
| 6 | `retrieve.fuse.fuse()` | the `ChannelResult`s | ranked `FusedHit`s at one key, `block_id`, with **1-based** ranks. `score(b) = Σ_c weight(c)/(60 + rank(c,b))` over `status == OK`; `ceiling = Σ_c weight(c)/61` over `status ∈ {OK, EMPTY}`; `confidence = best/ceiling`. The shipped weights are `identity 2.0 + exact 1.2 + lexical 1.0 + structural 0.4 = 4.6`, so `ceiling = 4.6/61 = 0.07541` — the same number charter D5 prints for "four (no semantic)". `OFF` contributes nothing to the ceiling and does not force `degraded`; `UNAVAILABLE` contributes nothing **and** forces it |
| 7 | `retrieve.verdict.build_verdict()` | the fused set plus the fifteen absence gates | `Verdict(state=VerdictState.OK, gates=(), channels={'semantic': OFF}, freshness='fresh', coverage=…, best_score, score_ceiling, confidence, scorer_version=1, plan_digest, snapshot_gen)`. One constructor, one `citable_as_absence()` predicate, exactly one `ABSENT` return site (INV-11) |
| 8 | `answer.worth → allocate → dedup → untrusted → render` | `Response(hits, verdict, cost)` | the Answer document: `≤ HARD_CEILING = 24,000` chars, one content block, `**ow:<name>**` section markers, every emitted block wrapped in `<ow:untrusted>` and carrying `cite · page · quote · trust · method · origin_driver · restriction_bits`, and a byte-exactness sentence only where `quote == Quote.VERBATIM` **and** `doc.achieved` supports it (INV-10) |

Budget arithmetic worth checking once: the four live channel budgets sum to `15 + 25 + 50 + 40 = 130`
ms against `[retrieval.budget] query_ms = 250`, leaving hydration and the coverage scan inside the
envelope. With `semantic` on it is `130 + 80 = 210` against `250`, which is the sum charter D1's
config block prints. `ow route lint` refuses a set whose sum reaches `query_ms`, because a plan that
merely used its budgets would make every query `degraded` and turn the honesty machinery into
permanent noise.

A channel that exceeds **its own** `budget_ms` returns `UNAVAILABLE(timeout)` and forces `degraded`.
A channel pre-empted by the **query** deadline reports its partial ranking with
`truncated_at_limit = True` and status `OK`, and the channels after it report `OFF(query_deadline)`.
Absence gate 1 (`timed_out`) reads only the first case. Two deadlines, two outcomes, and the
difference is the whole verdict.

### 4.2 Scenario (b) — a scanned 400-page report, with per-page escalation

Hops 1–4 of (a) are unchanged: the roster row, the CAS blob, `op.identify` → `part_count = 400`. The
divergence starts at the evidence plan and is the single most load-bearing behaviour in the framework,
so it is traced per page class. Because each part is decided independently, the four classes below
produce four different `route_decision` rows and therefore four different `work` inserts — the 400
work rows are not homogeneous and were never created as a block.

```text
part p1..p400, each decided INDEPENDENTLY (INV-13: the unit of decision is the part)

  FREE evidence group, computed first, ~2 ms/part, NO raster, NO model server:
     decode.char_count   decode.line_count   decode.has_text_span
     garble.score        ink.coverage        geometry.overlap_line_frac

  380 parts:  decode.line_count == 0  ->  rule `decode.part-text-unusable` fires on
              when.any_of[0], with on_unknown = "match".  `decode.pdf-text-layer` does not
              fire because its second clause is decode.char_count > 0.
              -> RouteDecision(rung=DECODE -> escalate_to=PAGE, lane='text',
                               driver='parse.page.olmocr',
                               cause='decode.line_count==0', …)
                 alongside Modifiers(render='glyph').  `render` is a MODIFIER and
                 `cause_from` is a rule key: the decision carries the RENDERED
                 `cause`, and the modifier set is recomputed from the read set.
   14 parts:  a text layer PLUS garble.score 0.61 >= @thresholds.garble_escalate 0.50
              -> the same escalation via when.any_of[1], cause = garble.score
    4 parts:  ink.tiles <= @thresholds.blank_page_tiles = 4
              -> rule `decode.blank-part-escape`: outcome=ok, terminal=true,
                 reason='blank-part'.  ZERO cost, and the page is RECORDED, not dropped.
    2 parts:  clean born-digital exhibits -> rung=DECODE, parse.pdf.pdfium, free.
              INV-13 in force: no LOCAL_COMPUTE signal, no raster, no model server, and
              the service_attaches / page_renders / signal_computations counters are
              EXACT for these two parts — +-1 fails the gate.

  Then, because doc.escalated_part_frac = (380+14)/400 = 0.985 > 0.80:
     rule `page.collapse-to-sequence` DOES NOT FIRE — its second clause is
     `unit.part_count <= 64` and part_count is 400 — so the 394 escalated parts stay
     per-part rather than becoming one Sequence session. On a 40-page scan the same
     rule DOES fire, one Sequence amortises the model load across parts, and cost is
     apportioned by token share so per-part attribution keeps working.
```

The escalated path, per part:

| # | component | receives | emits / writes |
|---|---|---|---|
| 1 | `route.admit.admit` | the `PAGE` decision | `Admitted(reservations=(Reservation(dim='micros', amount=<p95 ceiling>, scope='part', …), Reservation(dim='tokens_out', …), Reservation(dim='calls', …), Reservation(dim='gpu_ms', …)))` against `[budget.per_part]` `micros = 6_000`, `tokens_out = 24_000`, `calls = 3`, `gpu_ms = 12_000`. **The first exhausted dimension wins**, because a count cannot bound spend when per-attempt cost varies 100× with page density. A denial is `DEFERRED_BUDGET` — an `Outcome`, not a failure — and the work row stays claimable with `cost_micros` unchanged | `budget_reservation` rows at `state='held'` with `expires_ms == work.lease_expires`; headroom is recomputed **in SQL** on every reserve |
| 2 | the render step | `render='glyph'` | a page raster at `[render.glyph] short_edge_min_px = 1384`, `area_max_px = 6_291_456`, `patch_snap = 28`, **`binarize = false` always** — a 72-DPI-then-Otsu path destroys the antialiasing a modern VLM trained on | `page_render`, a derived evictable cache keyed by `(dpi, renderer, renderer_version, colorspace)`; accounted under `CacheLayer.render` |
| 3 | `omniweave_core.modelserver` (**S3**) | `ServiceSpec('vlm', model_id='allenai/olmOCR-7B', model_revision='9f8e7d6c5b4a3928')` | a `ServiceHandle` — attach if a healthy server reports the same model id, else lazy spawn. `refill_target = min(svc.capacity(), MAX_AUTO_PARALLEL=96, cfg.max_inflight, ledger.headroom_units(svc))`: **derived, never constant**, because surya's `MAX_AUTO_PARALLEL = 96` is a cap over a server whose own `_max_num_seqs` defaults to 8, and a flat 96 on a 24 GB consumer card is an OOM rather than the measured 48→96 = +28% | `service_observation` per `(run_id, name, config_digest)`: lifecycle, capacity, peak in-flight, `cold_start_ms`, `queue_p50_ms`, `queue_p95_ms`, and the server's own log tail on a failure |
| 4 | `parse.page.olmocr` (child, **S4**) | `DriverIO` with `io.service('vlm')` | `owdoc-fragment/1` with `method=Method.OCR_PAGE` and `os:{"k":"pixels"}` — which can **never** reach `Quote.VERBATIM` (INV-10), because `pixels` and `none` have no re-verifiable branch | — |
| 5 | the acceptors | the model output | `verify.repeat_ngram_max >= 12`, `verify.finish_reason != "stop"`, `verify.token_saturation >= 0.98`, `verify.parse_ok`, `verify.nonempty` → on any failure, rule `regen.output-invalid` escalates to `Rung.REGEN`, strictly serial per `(unit, part)` under `Semaphore(1)` (RT11), charged to the **same** per-part budget | a `route_decision` child row with `rung > parent.rung`, enforced by a generated `BEFORE INSERT` trigger on the parent join, because SQLite prohibits a subquery in a `CHECK` (RT8) |
| 6 | `DocSink` | the fragment | one transaction per `end_page()`, at `staged_gen = doc.gen + 1` because this is a **document-granularity** producer. Readers resolve the committed `doc.gen` and see nothing until the work row is done; the bump is one `UPDATE` inside the completing transaction (I21) | `page`, `block`, `diag` |
| 7 | the free `agree.decode_vs_page` signal | both rungs' text for the 14 parts that had a text layer | a cross-rung normalised edit distance at zero marginal cost — the only quality label available on every escalation. `TruthKind = "agreement"`, and it may **never** populate an accuracy column | `route_quality` |

**Partial failure, which is the point of the scenario.** Suppose 20 of the 400 parts die: 12 hit
`resource_limit` (a page whose raster exceeds `area_max_px` after `patch_snap`), 5 exhaust
`[budget.per_part] tokens_out`, 3 crash the worker.

```text
  work rows          380 status='done'
                      12 status='failed_permanent'  failure_class='resource_limit'
                                                     failure_message names WHICH knob
                       5 status='deferred'           Outcome DEFERRED_BUDGET, still claimable
                       3 status='failed_permanent'   failure_class='driver_crashed'
                                                     + the child's last 4 KiB of stderr ring
  the document       the `doc` row COMMITS at the new gen. 380 pages of blocks are present and
                     citable. The 20 gaps are `diag` rows with a codes.toml symbol, a page,
                     a severity, a component and a fatal bit. Failure is a field.
  the driver         3 crashes in 60 s trips [drivers] crash_quarantine -> the DRIVER is
                     quarantined for the run (not the unit), resolve() returns
                     RejectCode.QUARANTINED, the plan re-routes, and a
                     Degradation(kind='quarantine') is recorded.
  the corpus         `ow doc verify` lists the 20; `ingest_scope` records discovered vs
                     indexed vs skipped, and AN ABSENT ingest_scope ROW MEANS "coverage
                     unknown", never "nothing was excluded". Absence gate
                     `parse_gap_in_scope` (gate 9) joins the `diag` table through
                     CREATE INDEX diag_code, so a query whose answer would live on page 137
                     returns verdict=degraded and NEVER verdict=absent (INV-12).
  the retry          each failed_transient row has attempts_total < 5 and a retry_after;
                     attempts_today is period-stamped by last_attempt_at, so a daily cap
                     is real rather than a per-process counter.
  the exit code      `ow ingest` exits 0; `ow queue status` shows the 20; the `run` row is
                     status='partial' and the manifest carries failures by class.
```

`--accept-partial` is the named override that lets a downstream step consume a `partial` run. There
is no `--force`, anywhere.

### 4.3 Scenario (c) — an agent compiles a PPTX from that corpus, then re-ingests it

The OUT direction is **skills plus CLI, never MCP**. The agent writes IL and runs `ow` verbs.

| # | component | receives | emits / writes |
|---|---|---|---|
| 1 | the `omniweave` skill | the user's request | `ow query` calls returning `Hit`s with `cite` tokens; then a `Brief` — schema-version comment on line 1, `## section` headings, `- key: value` rows, `## forbidden` items tagged `(user)`. The role that consumes a Brief cannot write it |
| 2 | `ow out scaffold pptx` → `omniweave_core.out.job` | the `Brief` and the selection | a job directory `<cache_root>/jobs/<run_id>/<artifact_slug>@<gen>/` holding `job.json` (validated against `schema/job-v1.json`), `brief.md`, `il/`, `assets/index.json` + `assets/cas/ab/cd/<sha256>`, `validation/`, `out/`. For a Toolchain target this same directory **is** the S2 data plane |
| 3 | the agent | `ow out constructs pptx --format md` (≤ `agent_doc_tokens_max = 6000`, CI-gated) | authored `il/u01.svg … il/u12.svg` in the `owsvg/1` subset over carrier `svg`, each element carrying `data-ow-el` and `data-ow-cite`; asset references only as `asset-slot:<sha256>`, so the IL hashes identically on another machine |
| 4 | `ow out stamp` | the IL bundle | `el` addresses (`u03/e17`) minted once, never renumbered, refused on a duplicate; `nsig` as the content half of the two-factor anchor |
| 5 | `ow out check` → `omniweave_core.out.rules.run_pack()` | `RuleCtx(doc=CarrierDoc, unit, plan, constructs=ConstructTable, brief, cites=CiteResolver, limits, measure)` | a `FindingSet` folded on `(code, rule, unit, canonical)` with a count and ≤ 3 examples; `validation/early.json`. **Phase 0 is the carrier parse and short-circuits.** The framework runs the pack; the target has no `validate()`; the validator never rewrites the IL |
| 6 | `omniweave_core.out.gate.gate_status()` | the `FindingSet` and `il_digest` | `(GateStatus, int)`. Exactly one of ten values — `passed` — permits a release; every other prints the exact command that clears it. An **inherited error still blocks**, attributed to the template, because `Severity` and `Provenance` are orthogonal |
| 7 | `compile.pptx.native.lower(plan, il, ledger, io)` | `Plan`, `ILBundle`, a frozen `AssetLedger`, `DriverIO` | writes into `io.tmpdir` only, never `output_root` (DR7, INV-6); returns a `DriverResult` |
| 8 | `omniweave_core.out.opc.write_opc()` | the lowered parts | the `.pptx`: members in canonical order (`[Content_Types].xml`, `_rels/.rels`, then sorted by partname); `ZipInfo(name)` only — never `from_file` or `writestr`, whose `date_time` reads the local clock; `dcterms:created == dcterms:modified == job.determinism.clock_ns`; `cp:revision="1"`; `cp:lastModifiedBy=""`; no `w:rsid*`, no `p14:creationId`; shape ids from a per-unit counter seeded at 2; EMU integers only, so no `repr(float)` reaches the XML; every attribute map sorted before serialization |
| 9 | `compile.pptx.native.postflight()` | the artefact path and the `Plan` | a `Receipt` with `CheckValue`s; `out/receipt.json`; `out/<slug>.owcite.json` |
| 10 | the runner | the receipt | `artifact` and `artifact_unit` rows: `il_sha256` pointing at the **retained** IL bundle frozen into CAS, `nsig`, a `UnitOutcome` per unit summing exactly to `unit_count` (unclassifiable is fatal and the artefact is **not** written), plus `artifact_cite`, `artifact_asset` and `restriction_bits` — a restricted item makes the `compile` host refuse, naming the offending cites and asset ids (INV-16) |

**Re-ingest, and the loop is a foreign key.** `ow out back <artefact>`, or an ordinary `ow ingest`
over the output root:

| # | component | receives | emits / writes |
|---|---|---|---|
| 1 | `omniweave.run.discover` | the `.pptx` under a scanned root | a `unit` row like any other source document |
| 2 | `route.eval.evaluate` | `unit.format = 'pptx'` | the target's own `read_back` id `parse.pptx.native` for an artefact omniweave built. **The shipped policy does not yet express this preference** — see Open question 4 — so at release 1 this hop is exercised by `ow out back` and by the golden suite, and an ordinary `ow ingest` over the output root resolves `parse.office.anydoc` under rule `decode.office-native`, which names it by id with `terminal = true` |
| 3 | `parse.pptx.native` (an ordinary `parse/1` driver, with an ordinary card, probe, licence block and conformance run) | `UnitRef`, `PartSelector`, `DriverIO` | `owdoc-fragment/1`. `read_back` recovers cites from the **embedded channel only** and never infers a citation from visible text, and never invents provenance |
| 4 | `DocSink` | the fragment | a `doc` row with `method = Method.ROUNDTRIP` always, `quote = Quote.RECONSTRUCTED` unless the text was read from the artefact, `trust = Trust.INFERRED` wherever `kind_map` is many-to-one (OUT22); `artifact.read_back_doc_ord` **is a foreign key into `doc`** |
| 5 | the host | each Block's `x["x.ow.el"]` | `artifact_el` rows, which is what makes round-trip law R2 checkable: for every IL element carrying `data-ow-el`, `read_back(compile(I))` contains **exactly one** Block with that `el`, the right `Kind` under `kind_map`, `nfc(text)` equal to `nfc(visible_text(e))`, and the same cite set |
| 6 | `ow out verify <artefact>` | the artefact plus its retained bundle | R1: `compile(I) ≡_det A` at the declared `ArtefactDeterminism` classes. `part` is the floor and is **promised** (F16 measures it across nine cells before week 8); `byte` is asserted under one pinned resolution, recorded in the receipt, and **never promised** — a zlib bump falsifies it |

The consequence: a generated deck is a citable corpus document, and editing an omniweave-built
artefact is a `passthrough` (R4a: zero edits ⇒ 100% of units `passthrough` or `cloned_passthrough`,
each copied part's sha256 asserted equal to the source's) rather than a reconstruction. `project()`
is the reconstruction path, reserved for foreign artefacts and for artefacts whose retained IL was
lost, and it is always `rebuilt` with declared loss.

## 5. Process and deployment topology

### 5.1 What runs where

Parallelism lives in **exactly four places and nowhere else**: the loop (IO and its `to_thread`
executor), the store thread (writes), the `subproc` DriverHost (all driver execution), and the model
server (Coalescing). Batching exists at **two** named sites — the host `Batch` and server-side
Coalescing — and is invisible in all four ledgers.

```text
PROCESS 1  the `ow` process  (CLI | hook | SDK embedder | MCP server)
  |- MAIN THREAD           the asyncio Supervisor.  Exactly one per process.
  |                        Executes NO driver code.  Holds NO document bytes (I31).
  |                        TaskGroup for STRUCTURED SHUTDOWN ONLY; a worker_loop catches
  |                        BaseException and NEVER propagates, so one crash costs one unit.
  |- STORE THREAD          the ONLY holder of a sqlite3.Connection in this process (I19).
  |                        Every write arrives as a transaction closure on a BOUNDED queue;
  |                        a full queue back-pressures the loop, which is the point.
  |- RENDER THREADS        asyncio.to_thread, bounded by Admission.render_sem = cpu_count - 2
  |                        (olmocr pipeline.py:87-88, adopted verbatim; CPU render pushed
  |                        through to_thread at :112).  A CPU-render semaphore is NOT the
  |                        GPU-inference semaphore: at 10.7 MB per 192-DPI page, one shared
  |                        semaphore renders faster than it evicts.
  |- EVENT WRITER          a bounded 64k drop-oldest queue behind NdjsonSink.  emit() must
  |                        not block; the drop count is a Degradation, never a log line.
  `- INPROC DRIVER         omniweave-office only, under DriverGuard, [runtime] max_inproc = 2
                           (a guess -- F2 measures whether the anydoc marshal dominates)

  FOUR SEMAPHORE FAMILIES, and BILLED_API is not one of them:
    Admission.class_sem   [budget]  max_inflight = { free=32, local_compute=4, billed_api=2 }  UNITS
    Admission.worker_sem  [drivers] max_workers  = { free=4,  local_compute=4, billed_api=8 }  PROCS
    Admission.render_sem  cpu_count - 2
    Admission.service_sem refill_target(), one per Service
  BILLED_API admission is THE DURABLE LEDGER, not a semaphore: two scheduler processes each
  holding an in-memory semaphore of 2 show the provider 4 (I29).

PROCESS 2..N  subproc DriverHost workers  (seam S4)
  one long-lived worker per (driver_id, config_digest), run-scoped, worker_idle_ttl_s = 300,
  over a 0600 unix socket or an owner-only named pipe.  Never a daemon, never loopback TCP.

PROCESS X  a Toolchain child  (seam S2)
  ONE per artefact, one-shot, cwd ALWAYS the job dir, env a constructed allowlist,
  SIGTERM at timeout and SIGKILL at timeout + 5 s with the whole process group reaped.
  The parent drains stdout on a dedicated thread into an unbounded queue: the pipe cannot
  deadlock.  stderr is a bounded ring tail and is never parsed.  No DriverIO, therefore
  no io.service(): a Toolchain target cannot reach a Service.

PROCESS Y  a model server  (seam S3)  -- MAY be a separate service, MAY be pre-existing
  attach-or-spawn with model-id verification on attach.  keep_alive_s = 300 by default;
  a resident 7B engine holds 20-40 GB of VRAM after the run exits (F37).
  capacity = min(server-reported concurrency, MAX_AUTO_PARALLEL = 96, the operator ceiling).

NOT A PROCESS, ANYWHERE
  no daemon; no loopback control port; no broker; no second durable store that must agree
  with the `work` table about what is done; no long-lived local IPC daemon for parsing,
  embedding, indexing or scheduling.
```

### 5.2 Why each boundary is where it is

| boundary | in-process | separate process | may be a service | the argument |
|---|---|---|---|---|
| the store | yes, one thread | no | **T3**: Postgres behind the same protocols, with **no operator change** | making the store the distribution boundary is what buys T3 for free. The port is `Store` (4 methods) + `Reader` (6) + `DocSink` (11) + `GraphSink` (12) — **33 methods, not four** — and that is the whole surface a Postgres backend must implement. `Snapshot`'s handle is an opaque backend-owned `token: object`, never a `sqlite3.Connection`, so INV-17 holds by construction in a backend that has no SQLite at all |
| the office decoder | yes (S1) | fallback | no | 4.4 ms median against a 200–800 ms cold worker, on the framework's most frequent route |
| every other parse driver | no | yes (S4) | no | a segfault, a hang or a 22 GB WAL costs one row instead of the run |
| the VLM | no | yes (S4) for the driver | **yes (S3)** for the engine | server-side Coalescing merges across worker processes; host-side batching cannot |
| the Toolchain | no | yes (S2) | no | a language boundary, one-shot, with a job directory instead of a wire |
| the Supervisor | yes | — | **no** | a general workflow engine would be a second durable store that must agree with `work` about what is done, a second scheduler's semantics between the operator and `ow why`, and a service that must be running before `ow ingest` works on a laptop |
| the MCP server | yes (`omniweave-serve`) | yes (`ow serve --http`) | yes, loopback-only unless `--api-key` | serve holds no loop and no Supervisor, so it can be embedded or hosted without changing what a read means |

### 5.3 The startup sequence

Every `ow` invocation, every SDK embedder and the MCP server run the same ordered sequence. The order
is load-bearing in two ways: nothing that can fail cheaply runs after something expensive, and the
first five steps touch no store, which is what makes `ow --version` ≤ 150 ms and `ow hook prompt`
≤ 250 ms p95 (G10, G26) achievable at all.

| # | step | what it does | what a failure is |
|---|---|---|---|
| 1 | dispatch | parse argv against the generated argparse tree, look the verb up in `ACTIONS` | an unknown verb or flag: usage error, **exit 1**, no config read |
| 2 | config | resolve the five layers plus every declared `OMNIWEAVE_*` twin, **once**; coerce every value to a flat `Scalar` | an unknown key (naming the nearest known one), an un-canonicalisable value, or a `cache` root inside `source`: `ConfigError` (`OW-C-*`), **exit 1** |
| 3 | limits | `effective = min(tenant_cap, declared, HOST_MAX)` for every `MAX_*` | a `[limits]` value above its `MAX_*`: `ConfigError` — widening is a fork, not a flag |
| 4 | digests | compute and freeze `config_digest`, `semantic_digest`, `policy_digest`, `pricebook_digest` into the `RunContext` or read context | a policy that will not load or lint: `RouteError` (`OW-R-*`), **exit 1** |
| 5 | surface | serve only: assert SV1 — `set(listed) ⊆ set(enabled)` and `HUMAN_ONLY ∩ enabled = {}`; assert `default_corpus` names a `[corpora]` entry | `SurfaceError` (`OW-A-*`), **exit 1**, before the transport opens |
| 6 | store | store-touching verbs only: check `sqlite3.sqlite_version_info` against `MIN_SQLITE = (3,42,0)`; apply `CONN_PRAGMAS` with `busy_timeout = 5000` **first** (a `journal_mode` set before it crashes a contended open); heal-on-open; refuse if `index_state.bulk_window` is open, naming `ow store repair` (ST13) | `StoreError` (`OW-S-*`). The `MIN_SQLITE` refusal names `pip install omniweave-core[sqlite]`; a git-tracked `.owstore` is `OW-S-060` |
| 7 | catalog | build the `Catalog` from `entry_points(group="omniweave.drivers")` + `Distribution.locate_file("driver.toml")` + `tomllib`, importing nothing; compute `catalog_digest` and **freeze it into the `RunContext`** | never a startup abort. A malformed card becomes a `Rejection` at resolve time, so one bad third-party wheel cannot stop `ow query` |
| 8 | write lock | write verbs only: acquire the scoped `store.write` lock at the caller's wait budget | the loser gets **exit 7** naming the holder's host, pid and lock age |
| 9 | loop | `omniweave/run/supervisor.py` opens the one `asyncio` loop and its `TaskGroup` | a second concurrent `run()` in one process is refused with `StoreError` before the loop opens: one Supervisor per process is an assertion, not a convention |

Two consequences of step 7 being frozen. First, **a driver installed mid-run is invisible until the
next run**: `catalog_digest` is part of `resolve()`'s memo key and of every `resolution_digest`, so a
mid-run catalog change would make two parts of one run resolve differently with no record of why.
Second, `ow doctor` is the only command that rebuilds the catalog and re-probes unconditionally;
everything else reads the frozen one. Probes themselves run at **preflight for the candidates a
`Requirement` actually reaches**, never for the whole catalog at startup — probing 20 installed
drivers to answer `ow --version` would spend the entire cold-start budget on drivers the command
never touches.

### 5.4 Concurrency on one store, across processes

This is the part a single-process diagram hides, and it is where INV-17 either holds or is a slogan.
One `.owstore` is one corpus with **one writer**, and the writer may be in any of several `ow`
processes started by a CLI invocation, a hook, a watcher or a detached `ow_add` child.

| question | mechanism |
|---|---|
| what serialises two writers | the cross-process scoped lock `store.write` in `omniweave_core.locks`: `O_CREAT\|O_EXCL` plus `flock`, holder identity `(host, pid, process_create_time)` — the third component is what distinguishes a live holder from a recycled pid |
| how long a caller waits | passed per call, not global: `[runtime] interactive_wait_ms = 2000` for a foreground command, `batch_wait_lock_ms = 60000` for an ingest |
| what a loser sees | exit code **7**, `store busy`, naming the holder's host, pid and lock age — never a bare `database is locked` |
| how a reader avoids the writer | the `connect_readonly` ladder: `mode=ro` when a `-wal` sidecar exists, `mode=ro&immutable=1` when it does not. A plain read-write open **creates** the WAL sidecars and moves the very mtime the freshness check reads (I10), so the ladder is a correctness mechanism, not an optimisation |
| how billed concurrency is bounded across processes | durable `budget_reservation` rows, not semaphores. A held `(dim='calls', scope='provider')` reservation **is** the cross-process in-flight count, headroom is computed in SQL, and a two-process test asserts the provider sees ≤ N (I29) |
| what a crash leaves | `claimed`-with-expired-lease ∪ `pending` **is** the unfinished work. There is no checkpoint file and no counter table, because `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift. `lease_reaper` returns expired rows; the commit predicate's `claimed_gen` makes a late result from a dead process write nothing (I23) |
| what a stale generation leaves | abandoned `staged_gen` rows are swept at startup through `ON DELETE CASCADE`; `--allow-abandoned-gen` is the named override, and there is no `--force` |
| what protects the loop | `lag_monitor` samples at 100 ms against `[runtime] loop_lag_max_ms = 250` with a **one-way** `degrade()`, and CI asserts p99 loop lag (I32). A multi-minute commit is the one thing that trips it, which is why F29 (a sub-page commit boundary) is a written open question rather than a hope |
| what a bulk load leaves | `index_state.bulk_window` is written **before** the first DDL. Bulk windows drop only non-`UNIQUE` secondary indexes and read their DDL from `schema/` by name with a hard raise on a miss; an open marker at store open refuses to serve and names `ow store repair` |

**What `ow_add` does when an ingest holds the lock**, because "the read path never blocks on a
refresh" is only true if this case has an answer and the roster append is itself a write. `ow_add`
takes `store.write` at `interactive_wait_ms = 2000`, writes its `unit` rows in transactions of at
most `[runtime] plan_batch = 512`, releases, and only then spawns the detached `ow ingest` child.
On a timeout it does **not** queue in memory, block the response or drop the request: the `ow_add`
envelope returns `accepted = false` with a `Degradation(kind='store_busy')` naming the holder's host,
pid and lock age, and the CLI form exits 7. The honest reading is that a refresh request during a
bulk ingest is refused and reported, not lost — and it costs the caller nothing, because the ingest
already holding the lock will discover the same files on its own scan. The alternative, an in-memory
queue in a process that may exit, would be a second record of pending work that must agree with the
`unit` table, which is the shape this design refuses everywhere else.

Two further consequences worth stating plainly. First, **there is no distributed mode at v1**: two
hosts cannot share one `.owstore`, and the lock's host component makes that a refusal rather than
corruption. Second, **tenancy is store-per-tenant** (F27), so the `segment.content_digest` embedding
dedup — a covert channel in a shared store, where two tenants observe each other's embeddings as a
timing difference — never arises. No plan document may assume row-level tenancy.

### 5.5 Cold start and memory

```text
COLD-START BUDGETS (charter D1, gate G10: per-OS recorded baseline, 25% drift fails)
  import omniweave_core                        <=  80 ms
  ow --version                                 <= 150 ms
  ow --help                                    <= 250 ms
  driver discovery, 20 installed                <=  20 ms   dist-info only; imports nothing
  ow query, warm store                          <= 250 ms
  ow hook prompt, warm                          <= 250 ms p95  (G26); 1 s cold

MEASURED DISCOVERY COSTS  (charter D3: Windows / CPython 3.11.9 / 328 distributions, warm)
  entry_points(group=...)                          15.3 ms   -> the discovery mechanism
  scandir + stat of every *.dist-info               1.01 ms  -> the card cache's validity key
  Distribution.files (RECORD) over all dists     2124 ms     -> FORBIDDEN as a mechanism

SUBPROCESS AND SERVICE START
  cold Python subproc worker                    200-800 ms, import-dominated -- which is the
                                                whole numerator of the S1 argument
  model server cold start                       recorded per run in service_observation
                                                (cold_start_ms); attach avoids it entirely

MEMORY
  supervisor peak RSS                           <= 600 MB, gated by G22 on a nightly
                                                100k-roster run at >= 2,000 transitions/s
  worker RSS ceiling                            SUM over cost classes of
                                                (max_workers x card.limits.memory_mb);
                                                `ow doctor` REFUSES above 0.8 x RAM
  a driver's own cap                            the card's `memory_mb` (e.g. 512), enforced by
                                                the worker; a breach is resource_limit
  Frame, the unit of streaming                  block-count-bounded, target 8,192 blocks --
                                                deliberately NOT a page range, so a page with
                                                400,000 blocks is harmless
  a 5,000-page document                         never exists in memory; page images are an
                                                evictable derived cache keyed by DPI
  INLINE_MAX                                    262,144 bytes; anything larger crosses S4 as a
                                                content-addressed blob reference
  a rendered 192-DPI A4 page                    10.7 MB decoded (charter D2) -- so 5,000 of
                                                them is ~53 GB, which is why rendering FOLLOWS
                                                routing rather than preceding it
```

Two numbers with an honest caveat, carried from the charter's deferred list rather than presented as
settled. The blocks-per-page envelope is **estimated** at 60–120/page against a measured 338 B/block
with one synthetic corpus at 912 B/block (F1), and every storage, Frame, segment and RSS projection
scales off it. The server-Coalescing speedup is a **1.5×–4× band with no published throughput number**
(F7), so every GPU-hour figure downstream is uncertain by up to 2.7× until `ow bench service` runs.

### 5.6 What each seam does on hostile input, at scale, on partial failure and under contention

The four questions every mechanism in this document must answer, answered once per seam.

| seam | hostile input | at scale | partial failure | contention |
|---|---|---|---|---|
| **S1** inproc | a malformed DOCX is anydoc's `is_fatal()` decision, surfaced as a `DriverError`; a crash in the FFI is **unrecoverable by construction**, which is exactly why S1 is reachable only for a first-party, vendored, fuzz-green, network-less, GPU-less driver named in `[drivers] inproc` | `[runtime] inproc_bulk_threshold = 64` units switches the same driver to `subproc`, so a bulk ingest does not hold the GIL proportionally to corpus size (F2) | a per-document call: one document fails, the batch continues | `max_inproc = 2` concurrent calls; `py.detach` releases the GIL for the Rust decode but **not** for the marshal into Python objects, which is the measured unknown |
| **S2** Toolchain | stdout over 1 MiB, a missing receipt, or a non-JSON line is a protocol error (exit 4); stderr is never parsed for a code | one child per artefact, one-shot. There is no pool, so there is no pool to exhaust | `{"t":"result","status":"blocked"}` is a `FindingSet`, not a failure; the gate blocks and prints the clearing command | none: the job directory is private to the invocation and the digest is in its path |
| **S3** model server | a model-id mismatch on attach is a **fatal** `ConfigError` — retrying attaches to the same wrong server; the token is 32 bytes in a 0600 sentinel, because surya's own `settings.py:97` `VLLM_API_KEY = "EMPTY"` is what happens without one | `refill_target` derives from the server's reported concurrency; a flat 96 on a 24 GB card is an OOM, not the measured +28% | an HTTP failure is `upstream_unavailable` or `rate_limited`, both transient and both requiring `retry_after_ms`; the server's log tail lands in `service_observation` | Coalescing inside the server merges across worker processes; the host holds one `service_sem` per Service so it cannot over-offer |
| **S4** subproc | `wire.py` caps `header_len` at 1 MiB, `body_len` at `INLINE_MAX` and JSON depth at 32, and is fuzzed; an unknown frame `kind` is a protocol error attributed to **us**, not the driver | one worker per `(driver_id, config_digest)`, `max_workers` per cost class, `worker_idle_ttl_s = 300`; AIMD halves the batch on OOM and **recovers** after 20 consecutive clean batches, because halve-and-never-recover lets one foreign process permanently cap a driver | a worker that dies without a frame yields `driver_crashed` synthesised from the exit status plus the last 4 KiB of the stderr ring; the batch retries **once at `batch = 1`** to localise the poison unit | three crashes in 60 s quarantines the **driver** for the run, not the unit; `resolve()` then returns `RejectCode.QUARANTINED` and the router re-plans |

### 5.7 The honest ceiling

The charter's reference ingest, restated because §5.5's memory numbers are meaningless without the
workload they were measured against: 100k documents (70k office at document grain, 25k born-digital
PDF, 5k scanned, mean 12 pages).

```text
  unit roster                    100,000 rows x ~220 B                        22 MB
  op.identify work rows          one per document                            100,000
  parse work rows                70,000 office + 360,000 PDF parts           430,000
  escalated parts                60,000 scanned + 18.8% x 300,000            116,400
  derive + embed rows            document grain                              200,000
  TOTAL work rows                100,000+430,000+116,400+200,000 = 846,400
                                 x ~250 B with indexes                       ~210 MB
  claimable at any instant       <= [runtime] queue_high_water                50,000
  time to first parsed document  the roster streams; there is NO plan phase   < 5 s
  .owstore                       ~80M blocks                                 ~26 GB
  routing ledger                 ~1 GB per million parts                     ~850 MB
  events                         ~846k x 8 x ~180 B, deflated, 64 MiB shards  ~140 MB
  runtime overhead               claim + commit + key + ~8 events        <= 0.5 ms/unit (F8)
  crash at hour 6                claimed-with-expired-lease UNION pending IS the unfinished
                                 work -- there is nothing else to reconcile

CEILING: ~10^7 parts on one host.  100k x 300-page legal discovery (30M parts, ~7.5 GB of
work rows) is NOT this design on SQLite.  T3 is Postgres with FOR UPDATE SKIP LOCKED behind
the same 33-method port surface, with NO operator change -- which is the entire point of
making the store the distribution boundary.
```

The three numbers on that list that are estimates and not measurements are labelled as such: 250 B
per work row and 26 GB of store both scale off F1's blocks-per-page envelope, and 0.5 ms/unit of
scheduler overhead is F8's open question with a written fallback (group commit widens from
zero-derived-row transitions to same-operator batches, which weakens I20 for the case it protects —
a trade to make with a number in hand).

## 6. The extension surface

Every point a third party can plug in, and the one document that specifies each. Nothing else is an
extension point, and adding one is a charter amendment.

| # | surface | mechanism | activation | isolation | specified in |
|---|---|---|---|---|---|
| 1 | `acquire/1` driver (a connector) | `omniweave.drivers` entry point + `driver.toml` | `[drivers] enabled` (INV-5) | `subproc` | [drivers](04-driver-system.md) |
| 2 | `parse/1` driver | same | same | `subproc`; `inproc` only under DR9's five conditions plus an id in `[drivers] inproc` | [drivers](04-driver-system.md) |
| 3 | `derive/1` driver | same | `[drivers] enabled` **and** `[graph.passes] enable` — both apply, neither bypasses the other, and `ow doctor` FAILS on a pass enabled without its driver | `subproc` | [drivers](04-driver-system.md), [structure](06-structure-extraction.md) |
| 4 | `embed/1` driver | same | `[drivers] enabled` plus `[retrieval.vec] model_key` | `subproc` | [drivers](04-driver-system.md) |
| 5 | `compile/1` driver (a Target) | `omniweave.drivers` + `omniweave.targets` + `driver.toml` + `constructs.toml` + a `RulePack` | `[drivers] enabled` **and** `[targets] enabled` | `subproc`, or S2 for a Toolchain target | [generation](09-generation.md) |
| 6 | a `VectorBackend` | `omniweave.backends` entry point + `backend.toml`, read by the **same import-free loader** as a DriverCard | selected **by name in config only**; never in `resolve()` | in-process | [storage](07-store-and-retrieval.md) |
| 7 | a store Backend | `[store] backend = "sqlite" \| "postgres" \| "fabric"` | config | in-process | [storage](07-store-and-retrieval.md) |
| 8 | a Signal | a `SignalSpec` registered by an entry-point provider; `Evidence.read()` accepts a key core has never heard of, and there is no `__getitem__` and no public mapping | naming it in a policy rule; `ow route lint` resolves every key against the registry | computed in the host | [routing](05-ingest-and-routing.md) |
| 9 | routing / retrieval policy | `.omniweave/policy.d/*.toml`, one grammar with a required `surface` key | file presence and merge order, through one loader, one subsumption linter and one threshold fitter | data, not code | [routing](05-ingest-and-routing.md) |
| 10 | a `PriceBook` | `.omniweave/pricebook.toml`, operator-owned, versioned, digested | file presence | data | [routing](05-ingest-and-routing.md) |
| 11 | a Toolchain | a digest-pinned bundle in `$OMNIWEAVE_HOME/toolchains/<name>@<version>-<sha256>/` | `ow targets install <name>`; the digest is **in the path** and verified on every invocation; `--offline` refuses to fetch | S2 child process | [generation](09-generation.md) |
| 12 | a Service | `[services.<name>]` in `omniweave.toml` | config; named and **never routed** | S3 | [the runtime](08-runtime.md) |
| 13 | a hook | `ow install` writes it; `ow hook <event>` reads stdin JSON | the host's config | the `ow` process, on a 400 ms self-deadline | [interfaces](10-interfaces.md) |
| 14 | an install target (a host) | one `AgentTarget` file plus one registry row: `detect`, `install`, `uninstall`, `print_config` (which must not touch the filesystem), `describe_paths` | `ow install <target>` | in-process | [interfaces](10-interfaces.md) |
| 15 | a skill | `skills/` data artefacts, with `references/actions.md` generated | install | data | [interfaces](10-interfaces.md) |
| 16 | a dev / non-Python driver | `OMNIWEAVE_DRIVER_PATH` | env plus `[drivers] enabled` | `subproc` | [drivers](04-driver-system.md) |

Three namespaces are **reserved** and a third party may not use them: `omniweave.operators` (created
deliberately never — Operators stay first-party until something appears that a Driver cannot
express), the `ow` / `x.ow.*` vendor namespace with its `data-ow-el` / `data-ow-cite` attributes and
four cite sigils, and the `OW-*` / `OW_*` code namespaces.

Two things that look like extension points and are not.

A **Service** is not a Port. It has no unit, no cost-per-unit and no card, and its lifecycle is
attach-or-spawn — so it is named in config and never resolved. Making it a Port would have required
a cost-per-unit for a thing whose cost is a residency, and a `resolve()` over servers that may not
be running.

A **Backend** is not a DriverCard. It declares no capability floors, never enters `resolve()`, and is
selected by name — but `omniweave-conform` still holds a `VectorBackend` to four contract
obligations: real filter pushdown (`candidates` narrows **before** ranking, tested at 0.01
selectivity); either epoch-immutability or an `unavailable(rebuilding)` return; a declared ceiling it
**refuses** above rather than serving a slow query; and `recall@10` against exhaustive f32 on a fixed
50k fixture with a committed floor. There is no fifth write protocol: `DocSink` writes L2,
`GraphSink` writes L3, `Store.complete()` writes the queue, `VectorBackend.upsert()` writes vectors.

## 7. Error taxonomy and propagation

### 7.1 Six kinds, and they are not interchangeable

The framework has exactly six diagnostic kinds. Confusing two of them is the most common way an
honesty property silently stops holding, so each has its own verb and its own storage.

| kind | verb | scope | where it survives | who reads it |
|---|---|---|---|---|
| `OwError` (`DriverError` is its driver-facing subset) | **raised** | aborts the current unit | the `work` row's `failure_class` + `failure_message` | the retry ladder, then the CLI's exit-code map |
| `Diag` | **recorded** | a document, page, block or part | the `diag` table (with `CREATE INDEX diag_code`, which exists so the absence contract can join against it) | the absence contract, `ow doc verify` |
| `Finding` | **recorded** | one IL element during an OUT validation | `validation/*.json` — **never** `diag` | the gate, the agent |
| `Rejection` | **returned**, never raised | one candidate in one `resolve()` call | `resolution_report.report_json`, as the enum's lower-case wire value | `ow drivers explain`, which resolves it through `codes.toml` |
| `quarantine` row | **kept**, verbatim | one rejected derive draft | the `quarantine` table | `ow graph residue`, human review |
| `Degradation` | **carried** | one downgrade, anywhere | `degradations[]` on the result, in the run manifest, and in every serve envelope | every surface |

`Diag` is recorded; `OwError` is raised. Two names for two things.

One transition matters more than the rest: **`FailureClass.needs_ocr` is not a failure.** A driver
raising it is supplying *routing data*; `DriverError.pages` names the pages, and the router escalates
exactly those parts. This is anydoc's `ConvertError::NeedsOcr{pages}` — "error as routing data" —
adopted, and it is why the recoverability table below has a row that is neither retryable nor
permanent.

### 7.2 The `OwError` tree

```python
# omniweave_core/errors.py — stdlib only; imported by `import omniweave_core` (it is NOT lazy,
# because a config error must be raisable before any lazy submodule loads).

class OwError(Exception):
    """Every framework error. Carries a codes.toml symbol, a fatality bit and a fix command."""

    SYMBOL: str = ""          # the class's default codes.toml symbol, e.g. 'OW_INTERNAL'

    def __init__(self, message: str, *, symbol: str | None = None, fix: str = "") -> None:
        if not fix:
            raise ValueError("every OwError names the exact command that clears it")
        super().__init__(message)
        self._symbol = symbol or self.SYMBOL
        self.fix = fix        # THE EXACT COMMAND THAT CLEARS IT. Never empty. §6.4.

    def code(self) -> str:
        """The SYMBOL — the stored and wire form (§5 C9). 'OW-S-010' is the human form,
        resolved from codes.toml by `ow explain`, which accepts either spelling."""
        return self._symbol

    def is_fatal(self) -> bool:
        """A limit breach is never swallowed (anydoc's is_fatal())."""
        return True


class ConfigError(OwError):      SYMBOL = "OW_CONFIG"      # OW-C-*  startup only
class ModelError(OwError):       SYMBOL = "OW_MODEL"       # OW-M-*  an unknown kind, a retired cite
class DriverHostError(OwError):  SYMBOL = "OW_DRIVER_HOST" # OW-D-*  a protocol/card/code mismatch
class RouteError(OwError):       SYMBOL = "OW_ROUTE"       # OW-R-*  a policy that will not lint
class StoreError(OwError):       SYMBOL = "OW_STORE"       # OW-S-*  snapshot expiry, busy writer
class GraphError(OwError):       SYMBOL = "OW_GRAPH"       # OW-G-*  a cluster above the cap
class TargetError(OwError):      SYMBOL = "OW_TARGET"      # OW-T-*  an OUT failure that must raise
class SurfaceError(OwError):     SYMBOL = "OW_SURFACE"     # OW-A-*  an ambiguous cite, a bad bind
class PolicyRefusal(OwError):    SYMBOL = "OW_POLICY"      # OW-P-*  a licence tier, a missing grant
class QualityError(OwError):     SYMBOL = "OW_QUALITY"     # OW-Q-*  an incomplete measured_on


class ResourceLimit(OwError):
    """Cross-area, because it is the ONE error required to name a knob."""

    SYMBOL = "OW_RESOURCE_LIMIT"

    def __init__(self, message: str, *, limit: str, fix: str) -> None:
        if not limit:
            raise ValueError("a ResourceLimit names WHICH knob would need raising")
        super().__init__(message, fix=fix)
        self.limit = limit
```

The ten area letters (`C M D R S G T A P Q`) are exactly the areas of `codes.toml`, the single
append-only register (G13 diffs it against the previous tag). Every row carries a numeric
`OW-<AREA>-nnn`, a stable `OW_SCREAMING_SNAKE` symbol, a one-line meaning and **the exact command
that clears it**. `RejectCode` members are rows in the same register under `OW-D-nnn` with
`OW_DRIVER_*` symbols — a typed enum over one register, not a second register.

The refusal to have a `--force` is what makes `fix` non-empty a constructor invariant rather than a
style rule. Overrides are named per hazard: `--allow-cost`, `--allow-egress <grant-id>`,
`--accept-partial`, `--allow-unexplained-rebind`, `--allow-rebill`, `--ignore-evidence-cache`,
`--allow-abandoned-gen`, `--max-rung`, `--allow-tainted`, `--accept-manual`.

> **Extends the charter.** The charter names `errors.py` as "`OwError` tree · `.code()` ·
> `.is_fatal()` · `.fix`" and fixes the ten `codes.toml` area letters, but never enumerates the
> subclasses. The eleven above are that enumeration: one class per area letter plus `ResourceLimit`,
> which is cross-area because it is the one error required to name a knob. No new area letter and no
> second register. `.code()` is a **method**, as the charter's inventory writes it, so a subclass can
> override the symbol per instance without a second attribute; `fix` is a plain attribute because
> §6.4 makes it a value, not a computation.

### 7.3 Which errors are recoverable

Recovery is decided by `omniweave_core.work.classify()`, which maps a raised error onto a work-row
status. This is the whole of the retry policy; there is no second ladder.

| `FailureClass` | status | retryable | `retry_after` | notes |
|---|---|---|---|---|
| `timeout` | `failed_transient` | yes | required | `progress_ms`, `wall_ms_hard` and `deadline_ms` are three separate deadlines |
| `upstream_unavailable` | `failed_transient` | yes | required | |
| `rate_limited` | `failed_transient` | yes | **required** — `DriverError.__post_init__` raises without it | the retry sits **outside** rate limiting: a retry gets back in line |
| `resource_limit` | `failed_permanent` | no | — | `limit` names which knob; a tenant may clamp down, never widen |
| `too_large` | `failed_permanent` | no | — | discovered at the read boundary by `take(N+1)`-then-check, so the memory is never spent first |
| `driver_crashed` | `failed_permanent` | the batch retries **once at `batch = 1`** to localise the poison unit | — | 3 crashes in 60 s quarantines the **driver** for the run, not the unit |
| `driver_bug` | `failed_permanent` | no | — | prints the `OW-*` code and the report command; process exit 70 |
| `encrypted`, `unsupported_format`, `corrupt_input` | `failed_permanent` | no | — | routing data, not surprises: `gate.encrypted` refuses at `Rung.GATE` for zero compute |
| `needs_ocr` | **not a failure** | — | — | **a routing input.** `DriverError.pages` names the pages and the router escalates those parts |
| `empty_result` | `failed_permanent` | no | — | the host converts an `ok` that fails `is_valid_nonempty()` into this **before anything is cached** |
| `auth` | `failed_permanent` | no | — | a credential is not a transient condition |
| — (budget denial) | `deferred` | the row stays claimable | — | `DEFERRED_BUDGET` is an `Outcome`, not a failure, and `cost_micros` is unchanged |
| — (superseded) | `CANCELLED` | writes nothing | — | the commit predicate is `WHERE id=:id AND claimed_gen=:gen AND status='claimed'` (I23) |

Hard ceiling: `attempts_total < 5` in the claim predicate. `attempts_today` is period-stamped from
`last_attempt_at`, so a daily cap survives a process restart rather than resetting with the process.

### 7.4 A zero-candidate resolution, which is not an exception

`resolve()` never raises: a zero-candidate `Resolution` is a value whose `rejected` tuple **is** the
error message. That value has to land somewhere, and the `work` table's CHECKs decide where. With no
candidate there is no `Candidate`, therefore no `driver`, therefore — under `CHECK ((driver IS NULL) =
(dispatch_key IS NULL))` and `CHECK ((operator LIKE 'op.%') = (driver IS NULL))` (D665) — **no routed
work row can be inserted at all**. The planner therefore does exactly four things and raises nothing:

1. writes the `resolution_report` row with every `Rejection` as `(driver_id, RejectCode, detail)`;
2. writes one `diag` row against the unit or part, whose `code` is the `OW_DRIVER_<MEMBER>` symbol of
   the *most specific* rejection — `LICENCE_ACK_MISSING` over `FORMAT_UNSUPPORTED` — so `ow explain`
   resolves it to a numeric and a fix command;
3. sets `unit.state = 'failed'` when no part of the unit resolved, and leaves it `'identified'` when
   some parts did, because a document with 3 unroutable pages of 400 is a partial parse and not a
   failed document;
4. records a `Degradation(kind='no_driver')` so the run manifest and every serve envelope carry it.

The run continues and exits 0 with `run.status = 'partial'`. This matters because the most common
zero-candidate cause is not a bug but INV-5 working correctly: a driver installed but not named in
`[drivers] enabled`, or a licence tier not allowed. `ow doctor` fails loudly on the first of those at
configuration time; the runtime path records it per unit and never converts it into a crash.

### 7.5 How an error crosses each seam

An error is not a Python exception once it leaves the host process, and pretending otherwise is how
a protocol bug gets attributed to a third party's driver. Each seam has one conversion, in one place.

| seam | the driver's side | the wire | the host's side |
|---|---|---|---|
| **S4** subproc | `ParseV1`/`DeriveV1` raise `DriverError`. Never return `None`, never an empty success | the worker's top-level handler serialises the five `DriverError` fields — `failure_class`, message, `retry_after_ms`, `pages`, `limit` — into the `RESULT` header, or sends `FATAL{failure_class, detail}` as its last words. Nothing else crosses: no traceback, no module path | `host/subproc.py` reconstructs a `DriverError` and `run/pipeline.py`'s `with_retries` calls `classify()`. A worker that dies **without** a frame yields `driver_crashed` synthesised from the exit status plus the last 4 KiB of the stderr ring. A frame that violates `wire.py`'s caps or carries an unknown `kind` is a `DriverHostError` (`OW-D-*`) — **our** bug, never the driver's |
| **S1** inproc | the same `DriverError` | none | `DriverGuard` catches `BaseException` at the call boundary and converts anything that is not a `DriverError` into `FailureClass.driver_bug`; nothing propagates into the loop. Interpreter-state corruption is unrecoverable here by construction, which is the fifth reason `inproc` is gated to a fuzz-green first-party driver |
| **S2** Toolchain | exit status plus a receipt | exit 0 iff a receipt was written; 2 validation blocked; 3 resource limit; 4 protocol error; 64 required capability missing, named in the last error line | 0 → validate the receipt; 2 → a `FindingSet` and a `GateStatus`, **not** an `OwError`; 3 → `ResourceLimit`; 4 and 64 → `DriverHostError`; anything else → `driver_crashed`. stderr is never parsed for a code |
| **S3** model server | an HTTP status and body | loopback HTTP with the 32-byte token; `traceparent` as a header (I33) | 429/503 → `rate_limited`/`upstream_unavailable`, both transient, both requiring `retry_after_ms`; a model-id mismatch on attach → `ConfigError`, **fatal**, because a retry attaches to the same wrong server; a health-check failure records the server's own log tail into `service_observation` |

Above the seams there are exactly four places an error lands, and a reader can reconstruct any
failure from them: `work.failure_class` + `failure_message`; a `diag` row against the document, page,
block or part; `degradations[]`; and the run manifest's failures-by-class rollup. A raised `OwError`
never reaches a user as a traceback — `omniweave.cli` maps it to an exit code from the charter's one
table (0–7, 9, 64, 70; there is deliberately no 8) and prints `code()`, the message and `fix`.

### 7.6 How partial failure is represented

There is no "partially failed document" state. Partiality is expressed in four places at once, and a
reader can reconstruct exactly which 20 of 400 pages are missing and why.

1. **`DriverResult.outcome = 'ok_partial'`** with a `partial_reason`. This is the only partiality a
   driver may claim; `DriverResult` is strictly smaller than `StepResult` and cannot claim
   `SKIPPED_CACHED`, `DEFERRED_BUDGET`, `CANCELLED`, an identity, a price or a cache hit (INV-7).
2. **`work` rows, one per part.** 380 `done`, 12 `failed_permanent{resource_limit}`, 5 `deferred`, 3
   `failed_permanent{driver_crashed}`. The `work` table **is** the record of completion; there is no
   checkpoint file and no counter table, because `SELECT status, count(*) FROM work GROUP BY status`
   is exact and cannot drift.
3. **`diag` rows** against the document, page or block, each with a `codes.toml` symbol, a severity,
   a component and a `fatal` bit. Failure is a field, not an exception. `ingest_scope` separately
   records discovered vs indexed vs skipped, and **an absent `ingest_scope` row means "coverage
   unknown", never "nothing was excluded"**.
4. **`Verdict`.** A query whose answer would live on a missing page returns
   `state = VerdictState.DEGRADED` and never `ABSENT`: absence gate 9 (`parse_gap_in_scope`) reads
   the `diag` table, and INV-12 forbids collapsing unknown into clean. A fault-injection test
   corrupts `block_fts` and asserts `degraded`.

The document itself commits. A document-granularity producer writes at `staged_gen = doc.gen + 1`,
readers resolve the committed `doc.gen`, and abandoned generations are swept at startup through
`ON DELETE CASCADE` (I21) — so a crash after page 40 of 200 leaves *nothing* visible rather than a
torn half-document. The `run` row is `status = 'partial'`, and the run manifest at
`{output_root}/runs/{run_id}.json` carries counts, failures by class, cache statistics,
`cost.would_have_been_micros_if_uncached`, per-phase timings and `degradations[]`. It is a manifest,
not a log, and it is written incrementally so a killed run still has one.

### 7.7 Cancellation, deadlines and shutdown

Cancellation propagates **by generation, not by signal**. `ctx.generation` is a monotonic integer,
`CancelToken` is checked at every loop top, and the commit predicate carries `claimed_gen` — so a
superseded result writes nothing rather than racing a live one. Supersession and interruption are
therefore different events with different row effects: the full `Outcome` → row transition table,
`cancelled` included, is [the runtime](08-runtime.md) §1.2's, and this section owns only the three
deadlines, what a driver observes at each seam, and the two-interrupt sequence.

```text
  three deadlines, three names, never conflated
    progress_ms      a SILENT driver          reset by DriverIO.progress(done, total)
    wall_ms_hard     a CHATTY driver          absolute
    deadline_ms      on the invocation        carried in the INVOKE header

  what a driver observes
    in-process       DriverIO.cancelled()
    over S4          a CANCEL{invoke_id, generation} frame, then SIGTERM, then SIGKILL at
                     timeout + 5 s with the WHOLE process group reaped, and BOTH recorded
    over S2          the same SIGTERM/SIGKILL ladder; the job directory is left in place for
                     diagnosis and swept by the cache GC, never deleted on the failure path
    over S3          the request is abandoned; a Service is not cancelled, because it is
                     shared -- which is why keep_alive_s, not a cancel, ends its residency

  structured shutdown  TaskGroup, for shutdown ONLY.  worker_loop catches BaseException and
                       NEVER propagates, so one driver crash costs one unit.
  queued_ms            ALWAYS separate from ran_ms -- a contended lock and slow work are
                       indistinguishable from the outside, and one number cannot say which.
  first interrupt      Ctrl+C sets the token.  Every claimed row is then committed as
                       Outcome.cancelled through the ONE commit predicate of §7.3:
                       status -> pending, attempts_total AND attempts_today decremented
                       (floored at 0), lease_expires = NULL, the held reservation released,
                       claimable again IMMEDIATELY -- which is why five interrupted runs
                       never permanently unclaim a document.  No generation is bumped.
  second interrupt     the process exits without waiting.  Nothing is lost that the lease
                       reaper cannot recover, because the claimable set IS the checkpoint;
                       G21 asserts the store equals an uninterrupted run after kill -9 at
                       three random points, and `ow resume` converges.
```

## 8. Configuration

### 8.1 The layered model

Precedence, resolved **once** at startup (step 2 of §5.3), highest first:

```text
  1  --config <path>                                   an explicit file
  2  ./omniweave.toml                                  walking up to .git or the filesystem root
  3  [tool.omniweave] in pyproject.toml                ONLY if no omniweave.toml was found
  4  $OMNIWEAVE_HOME/config.toml                       per-user  (default ~/.omniweave)
  5  built-in defaults                                 omniweave_core.config
  ---
  env: every key has a DECLARED OMNIWEAVE_* twin, resolved ONCE at startup, applied over the
       file layers
  call site: an Action argument (k, max_chars, corpus, ...) overrides for that call only and
       NEVER mutates the resolved Config -- which is what makes `ow show-config` a true
       statement rather than a snapshot of a mutable object
```

`ow show-config` prints every resolved value **with its source**; `--digest` prints `config_digest`.
There are exactly six config files and no seventh:

| file | holds | why not folded into `omniweave.toml` |
|---|---|---|
| `omniweave.toml` | the one user-facing config; line 1 is `schema = 1` | — |
| `omniweave.acks.toml` | per-driver licence acknowledgements, each bound to a `licence_sha256` and **void when it changes** | a boolean in the main config cannot be void; a mutated-licence test asserts `LICENCE_ACK_STALE` |
| `omniweave.lock` | driver pins: version, ref, `card_sha256`, `dist_sha256`, licence tier, restriction codes | a lockfile is generated, not authored |
| `omniweave.index.lock` | the corpus receipt: one sorted, timestamp-free line per document, ~200 B, with a merge driver registered for that path only. A deleted line **stays deleted** | it is a committed artefact with its own merge semantics; the `.owstore` itself is `.gitignore`d and a tracked store is `OW-S-060` |
| `.omniweave/policy.d/*.toml` | **all** `[[rule]]` policy — routing, retrieval and pins — in one grammar with a required `surface` key | separate `route`, `retrieval`, `pins` and `packing` files are rejected: one grammar, one loader, one linter |
| `.omniweave/pricebook.toml` | the operator-owned `Spend` → micros conversion | INV-15: no driver prices anything, and money has one home |

The per-project `.omniweave/` and the per-user `$OMNIWEAVE_HOME` are distinct directories with
distinct jobs: policy and events are per project; Toolchains, the probe verdict cache, the golden
corpora and the install receipt are per user.

### 8.2 The schema

`omniweave.toml` is **flat and JSON-canonicalisable by contract** — which is what makes ~250 lines of
property-tested scalar coercion sufficient and `pydantic` unnecessary in a zero-dependency core. An
un-canonicalisable value is a **startup error**. There is no `str()` fallback, ever (I12). Driver
configuration is `Mapping[str, Scalar]` where `Scalar = str | int | float | bool | None`; unknown
driver keys are **preserved verbatim** and enter `config_digest`.

Sections, with the invariant each carries:

| section | governs | the rule a reviewer checks |
|---|---|---|
| `[roots]` | `source`, `output`, `cache` | three roots, always separate. A `cache` root inside `source` is a **startup error** |
| `[corpora.<name>]` | `path` + `source` per corpus | the registry `ow_corpora` enumerates and every `corpus` argument resolves through. `<name>` matches `[a-z0-9][a-z0-9_-]{0,31}` and **is** the string a qualified cite carries |
| `[store]` | backend, path, `retain_parts`, the WAL valve, bulk windows | `retain_parts = "never"` makes `Quote.VERBATIM` unreachable and is disclosed in `corpus_card.verbatim_fraction` before any query runs |
| `[limits]` | tenant clamps | clamps **below** `omniweave_core.limits`' `MAX_*`, never above. Widening is a fork, not a flag |
| `[drivers]` | `enabled`, `inproc`, `isolation_floor`, `max_workers`, `require_lock`, quarantine | `enabled` is the **only** activation gate (INV-5); `ow doctor` FAILS on a driver named in policy but absent from `enabled` |
| `[services.<name>]` | model id, revision, endpoint, batching, `keep_alive_s` | `model_id` and `model_revision` are **semantic**: the model behind a Service is on no driver's card, so this is its only route into the cache key |
| `[licence]` | `allow_tiers`, `jurisdiction`, `fields_of_use` | selectors, checked against card facts. The tier itself is computed by `compute_tier`, never declared, and `ow drivers check` exits non-zero on a mismatch |
| `[targets]` | an artefact-kind allowlist | both this and `[drivers] enabled` apply; neither bypasses the other |
| `[budget]` | `max_inflight` per cost class, in **units** | there is no `per_document_micros` here. Currency caps live in `policy.d` under `[budget.per_part]` / `[budget.per_unit]`, which is their one home — so a `Degradation` message can name a knob that exists |
| `[runtime]` | water marks, leases, group commit, lock waits, `max_inproc` | `queue_high_water = 50000` / `queue_low_water = 25000` — **hysteresis, never one threshold** |
| `[cache]` | `recipe`, GC windows, per-layer byte caps | `billed_after_days = 0` means **never**; an automatic sweep never deletes a `billed_api` entry, and deletion needs `ow cache prune --allow-rebill`, which prints the count and the micros it is about to discard (I27) |
| `[retrieval]` | `vectors`, `scorer`, `fusion_k`, weights, `lex`, budgets, `vec` | the channel budgets must sum **below** `query_ms`; `ow route lint` refuses otherwise. `[retrieval.vec]` is a table because `vectors` above is a string, and a TOML key cannot be both |
| `[graph]` | `enabled`, `etypes`, `segment_target_tokens`, the coverage floor, `passes` | `segment_target_tokens = 1200` is a **target**, clamped below the ceiling `MAX_SEGMENT_TOKENS = 2048`. A target and a ceiling are two numbers |
| `[serve]` | profile, `listed`, `enabled`, `default_corpus`, `packing` | `set(listed) ⊆ set(enabled)` and `HUMAN_ONLY ∩ enabled = {}` are startup invariants (SV1); `default_corpus` must name a `[corpora]` entry; `[serve.packing] tier` is monotone in `chars_per_doc` (SV4) |
| `[observe]` | sinks, NDJSON path, shard size, sampling | sampling is `blake2b(work_id‖salt)`, **never** RNG, so a sampled trace is reproducible |

Two rules about keys that are decided rather than left to a reviewer's taste, and both follow from
G18's exact-coverage assertion:

- **An unknown key in `omniweave.toml` is a startup error**, naming the nearest known key. G18
  asserts that the union of the two axis lists covers every key in `omniweave.toml.example` exactly —
  neither over nor under — so a key with no axis cannot be digested, and a silently-ignored key is a
  config value with no effect, no source and no digest contribution. (Unknown keys inside a
  *driver's* `[config]` table are the opposite case and are preserved verbatim, because that table's
  schema belongs to the driver.)
- **A key's `OMNIWEAVE_*` twin is declared, not derived.** `[serve] listed` twins as
  `OMNIWEAVE_MCP_LISTED`, which no mechanical `section_key` rule produces, so the twin name is
  declared at the key's declaration site beside its axis and emitted into `tools/config_axes.toml`.
  The same G18 byte diff therefore covers both, and a key with no twin fails CI.

> **Extends the charter.** The charter says "every key has an `OMNIWEAVE_*` twin" and fixes G18's
> coverage assertion over the axis lists, but does not say where the twin name lives or what an
> unknown key does. Both answers above are forced by the coverage assertion rather than chosen; they
> add no gate and no file.

### 8.3 How a config value participates in a cache key

This is the mechanism that decides whether changing a knob costs money, so it is stated as a rule a
reader can apply to a key rather than a list to trust:

> **A key is `semantic` iff changing it can change the CONTENT of a produced row for a driver whose
> identity, `schema_version` and config are unchanged. Everything else is `operational`.**

Only the **semantic projection** enters a cache key:

```text
  semantic_digest = sha256_canonical(the semantic projection of the resolved config)
  config_digest   = sha256_canonical(the FULL resolved config)

  semantic_digest  ->  cache_key inputs, AND the full-scan latch (run.needs_full_scan)
  config_digest    ->  the run manifest, and the full-scan latch. NEVER a cache key.
  policy_digest    ->  a DECISION-key input. NEVER an artifact-key input.
  pricebook_digest ->  a DECISION-key input. NEVER an artifact-key input.
```

Each key declares its axis **at its declaration site** in `omniweave_core.config`; the declarations
are generated into `tools/config_axes.toml`, committed, and byte-diff gated (G18). Glob arity is
fixed: `*` matches exactly one key segment, `**` matches one or more, an explicit key beats a glob,
and **two globs matching one key is a G18 failure, not a precedence puzzle**. **An unclassified key
fails CI and is treated at runtime as `semantic`**: fail expensive, never wrong.

Worked example, because the direction of the failure is the whole point:

```text
  drivers.enabled  is OPERATIONAL.
    WHICH driver ran is ALREADY in the key -- producer.operator, schema_version,
    code_fingerprint, options_digest.  An allowlist that merely selects among drivers
    therefore cannot change a produced row's content.
    Classifying it `semantic` would re-bill an entire corpus every time an operator
    enabled an unrelated driver -- the exact failure this axis exists to prevent,
    pointed the other way.  (graphrag shipped a permanent silent 100% cache miss.)

  roots.source     is OPERATIONAL.
    The cache salt is the walked path RELATIVE to it.  An absolute root in a key would
    destroy portability across checkouts.

  limits.**        is SEMANTIC.  A lower limit TRUNCATES output.
  services.*.model_id / .model_revision  are SEMANTIC.  The model behind a Service is on
    no driver's card, so this is its only route into the key.
  graph.segment_target_tokens  is SEMANTIC.  It changes Segment boundaries, and a Segment
    is the extraction, embedding, packing and cache unit.
```

The two cache-key **input recipes** a produced artifact may use, both fed to the single `cache_key()`
in `omniweave_core.cache` and both returning a 64-char hex `sha256_canonical`. There is one function
and one digest format; `free_key` and `paid_key` are recipes for it, not a second algorithm. The
planner computes one of them at insert time and records it in `work.cache_key`, which is why a config
change is a mismatch rather than a silent reuse.

| tier | key inputs | why |
|---|---|---|
| **free** artifacts | `recipe`, `operator`, `op_version`, `code_fingerprint`, `driver_id`, **`driver_version`**, `options_digest`, `semantic_digest`, `unit_uri`, `unit_part`, `content_sha256`, the card's `[deps] pins` digest | a producer-version namespace, so an upgrade correctly invalidates cheap output |
| **paid** artifacts | the same **minus `driver_version`** and minus the pins digest, plus `model_id`, `model_rev` (an exact sha; `"main"` is a lint error) and `prompt_fp` | a bug-fix release must **never** re-bill a corpus. `prompt_fp` hashes the prompt with CRLF→LF and trailing whitespace stripped, or every Windows checkout re-bills |

I26 is the enforcement: a test mutates **every** `operational` key and asserts a byte-identical
`cache_key`. The growth bound `ow cache stat` prints, in these words, is **live units ×
configurations seen**. And the single most expensive mistake available in this design is not a config
error at all: forgetting to bump a driver's `schema_version` serves stale billed output forever with
no symptom, defended only by review, a kit check that diffs output across two tagged versions, and
`ow cost --by driver --since 7d` showing a driver's spend fall to zero after a release — a lagging
indicator that requires someone to look.

### 8.4 `Config` — the type `load()` returns

§8.1 fixes the precedence, §8.2 the schema and §8.3 the axis. This is the object all three produce
and the one `§2` row 8 exposes as `load() -> Config`, `Config.get` and `Config.source_of`. It is
**frozen**, resolved exactly once at startup step 2, and it has **no mutator**: an `Action`
argument overrides a value *for that call* and never reaches this object, which is what makes
`ow show-config` a true statement rather than a snapshot.

```python
# omniweave_core/config.py — stdlib only (tomllib, dataclasses, enum, pathlib). No pydantic, by
# contract: the value grammar below is finite and NON-RECURSIVE, which is what keeps coercion at
# ~250 property-tested lines and makes "JSON-canonicalisable by contract" (I12) checkable.

Scalar = str | int | float | bool | None

ConfigValue = (
    Scalar                              # int · float · str · bool · path · enum
    | tuple[Scalar, ...]                # list[str] · list[enum]      e.g. `drivers.enabled`
    | tuple[tuple[Scalar, ...], ...]    # THE ONE NESTED SHAPE: `serve.packing.tier`'s five
                                        #   eight-column rows. A matrix of scalars, never a tree
    | Mapping[str, Scalar]              # table[str,int|float|Scalar] e.g. `budget.max_inflight`,
                                        #   `retrieval.budget.channel_ms`, `cache.gc`
)

ConfigAxis = Literal["semantic", "operational"]

ConfigKind = Literal["str", "int", "float", "bool", "path", "enum",
                     "list", "table", "matrix", "str_or_list"]
# Ten coercers, one per distinct `type` in the key table of [18](18-api-sketch.md) §4, each
# property-tested. `matrix` is `serve.packing.tier`'s alone and `str_or_list` is
# `serve.enabled`'s alone; both are NAMED rather than special-cased, so the coercion table has
# no `else` branch and no `str()` fallback exists to reach (I12).


class ConfigLayer(IntEnum):
    """Precedence, lowest first. §8.1's numbered list orders the FILE chain; `ENV` sits above all
    of it, because the declared twins are 'applied over the file layers'."""
    BUILTIN       = 0   # the `ConfigKey.default`s below
    USER_FILE     = 1   # $OMNIWEAVE_HOME/config.toml  (default ~/.omniweave)
    PYPROJECT     = 2   # [tool.omniweave], ONLY when no omniweave.toml was found
    PROJECT_FILE  = 3   # ./omniweave.toml, walking up to .git or the filesystem root
    EXPLICIT_FILE = 4   # --config <path>
    ENV           = 5   # the DECLARED OMNIWEAVE_* twin


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """Where ONE resolved value came from. `ow show-config` prints `render()` and nothing else."""
    layer: ConfigLayer
    path: Path | None = None      # the file, for the three file layers; None otherwise
    line: int | None = None       # tomllib reports no line numbers, so the loader records each
                                  #   key's line during its single raw scan. Without it a
                                  #   precedence bug is a bisect instead of one command's output
    env_var: str | None = None    # the twin that won, for ENV. DECLARED, never derived (§8.2)

    def render(self) -> str:
        """'./omniweave.toml:141' · 'OMNIWEAVE_MCP_LISTED' · '(built-in)'."""


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """One key's DECLARATION SITE — the single home of its axis and its twin. The registry of
    these is what `tools/config_axes.toml` is generated from and G18 byte-diffs."""
    name: str                            # dotted; a segment may be `*` (`corpora.*.path`)
    kind: ConfigKind
    default: ConfigValue
    axis: ConfigAxis                     # REQUIRED, no default — see (a) below
    env: str                             # the declared twin, e.g. 'OMNIWEAVE_MCP_LISTED'
    choices: tuple[str, ...] = ()        # non-empty iff `kind` is 'enum', or 'list' over an enum
    item_kind: ConfigKind | None = None  # the element coercer for 'list' · 'table' · 'matrix'


KEYS: Mapping[str, ConfigKey]            # every declared key, glob segments included


@dataclass(frozen=True, slots=True)
class Config:
    values: Mapping[str, ConfigValue]    # EVERY declared key, resolved. Never partial
    sources: Mapping[str, ConfigSource]  # exactly the same key set as `values`
    config_digest: str                   # sha256_canonical(values). 64-char hex (§8.3)
    semantic_digest: str                 # sha256_canonical(semantic_projection()). 64-char hex

    def get(self, key: str) -> ConfigValue: ...
    def source_of(self, key: str) -> ConfigSource: ...
    def axis_of(self, key: str) -> ConfigAxis: ...
    def subkeys(self, prefix: str) -> tuple[str, ...]: ...
    def driver_config(self, driver_id: str) -> Mapping[str, Scalar]: ...
    def semantic_projection(self) -> Mapping[str, ConfigValue]: ...


def load(*, cwd: Path, env: Mapping[str, str], explicit: Path | None = None) -> Config: ...
```

Six decisions in that block a reader would otherwise have to guess, each with the thing that breaks
if it is reversed:

**(a) `axis` has no default, so an unclassified key cannot be constructed.** §8.3's rule is "an
unclassified key fails CI and is treated at runtime as `semantic`"; the constructor makes the first
half unreachable rather than merely gated, because a `ConfigKey` with no axis is a `TypeError` at
import. The runtime half is not thereby dead: the one key family that carries no `ConfigKey` at all
is a **driver's own `[config]` table**, whose keys belong to the driver, are preserved verbatim and
enter `options_digest` — and `drivers.*.config` is `semantic` in the axis lists, so the two halves
agree rather than compete. This is also why `schema` must carry an axis (`operational`): G18's
exact-coverage assertion admits no third state.

**(b) `get()` takes no caller-supplied default.** Every declared key has a `ConfigKey.default`, so a
`get(key, fallback)` would let a mistyped key resolve silently to the caller's fallback and never
reach §8.2's unknown-key startup error. An undeclared key raises `ConfigError`, naming the nearest
known key, at the one place that check belongs.

**(c) There is no `set`, no `replace` and no `copy(update=…)`.** The call-site override is an
argument to an `Action`, not an operation on this object. A single mutator would make
`ow show-config`, `config_digest`, the run manifest and the full-scan latch four statements about
four different objects.

**(d) `cache_key()` never receives a `Config`.** It takes `semantic_digest: str` among its inputs
(§8.3's two recipes), so "an operational key entered a cache key" is not a rule to remember but a
call that does not type-check. I26 — mutate every `operational` key, assert a byte-identical
`cache_key` — is then a regression test over an already-closed door rather than the only defence.

**(e) `load()` takes `cwd` and `env` as keyword arguments.** `os.getcwd()` and `Path(".")` are
semgrep-banned inside `omniweave/` ([08](08-runtime.md) §1.3's three bans), and the project-file
search walks up from `cwd` to `.git`; a `load()` that read the ambient directory would be the same
bug that wrote graphify's cache into the analysed tree. `env` is injected for the same reason the
`Clock` is: the twin-resolution table is otherwise untestable without mutating the process.

**(f) `subkeys()` and `driver_config()` exist because two sections are open-ended.**
`subkeys("corpora")` and `subkeys("services")` return the declared `<name>` segments — the set
`ow_corpora` enumerates and the set `ServiceRegistry` builds a `ServiceSpec` from.
`driver_config(driver_id)` returns the verbatim-preserved `drivers."<id>".config` table as
`Mapping[str, Scalar]`, which is the `effective_config` the `HELLO` frame carries (§5.6 row 12).

Where each non-obvious field is consumed, so a reader deleting one knows who breaks:

| field | consumer | what breaks without it |
|---|---|---|
| `ConfigSource.line` | `ow show-config <key>` ([18](18-api-sketch.md) §2 prints `source: ./omniweave.toml:141`) | a precedence complaint becomes a bisect over four files |
| `ConfigSource.env_var` | `ow doctor` D-26, which reports how many past runs had `[observe] otlp_endpoint` set | "an endpoint cannot be configured invisibly" ([15](15-observability.md) §8) |
| `ConfigKey.env` | G18's byte diff over `tools/config_axes.toml` | the twin name becomes derived, and `[serve] listed` → `OMNIWEAVE_MCP_LISTED` has no mechanical rule (§8.2) |
| `ConfigKey.axis` | `semantic_projection()`, hence `semantic_digest`, hence every cache key | the failure the axis exists to prevent, pointed either way: a re-billed corpus, or stale billed output |
| `ConfigKey.choices` | the startup validator, and `ow show-config`'s enum rendering | an invalid enum value is discovered by the subsystem that reads it, not at startup |
| `Config.sources` | `ow show-config`, the `run` row, `ow doctor` | `config_digest` says a value changed and nothing says which layer moved |
| `Config.semantic_digest` | `cache_key()` inputs and the full-scan latch (§8.3) | the cache key falls back to `config_digest` and every operational edit re-bills |

> **Extends the charter.** The charter fixes the precedence chain, the twins, the axis rule and both
> digests, but never prints the object. Everything above is the shape those four decisions force:
> the four-shape value grammar (read off [18](18-api-sketch.md) §4's `type` column), `ConfigLayer`'s
> ordering (read off §8.1, which is the only text that places `ENV` relative to the file layers),
> and the six method names, three of which — `load`, `get`, `source_of` — the charter and §2 row 8
> already name. No new file, no new gate, and no new config key.

## Open questions

Everything below is a genuine gap in my inputs or a place where the charter's own text is in tension
with itself or with the terminology lock. Each names the evidence that closes it. None blocks
implementing this document; where the charter is ambiguous I have followed it and said so.

1. **The terminology lock fails G27(c) against the charter, at scale.** G27(c) asserts that every
   `class` name appearing in `charter.md` or a plan document has a §2 row. A mechanical check of 100
   class names the charter uses finds **at least 38 with no row**, including `Catalog`, `DriverGuard`,
   `Scope`, `RunContext`, `Roots`, `CancelToken`, `OperatorABC`, `StepMetrics`, `Outcome`,
   `WorkRow`, `RunManifest`, `Candidate`, `RouteDecision`, `Reservation`, `BudgetLedger`,
   `CacheIndex`, `BlobStore`, `Dep`, `DepKind`, `Config`, `Response`, `Hit`, `Plan`, `Receipt`,
   `AssetLedger`, `ArtifactRef`, `ILBundle`, `ServiceSpec`, `ServiceHandle`, `ServiceRegistry`,
   `RejectCode`, `Cite`, `Addr`, `ResourceLimit`, `InstallReport` and `FileAction`. This is not a
   defect my document introduced and I have not tried to fix it here: each name belongs to the
   document that specifies it (`Hit`/`Response`/`Plan` to 07 and 09, `Scope`/`RunContext`/`WorkRow`
   to 08, `DriverGuard`/`Candidate` to 04), and coining them all in one document would put 38 facts
   in the wrong home. I have coined only the ones this document owns (New terms, below).
   **Answered by [ADR-1](adr/0001-terminology-lock-bulk-pass.md).** The bulk pass ran: `terminology.md`
   §2 holds 744 rows, each name homed to the document that specifies it, and G27(c) switches on once
   §3 is three-column, `tools/lock_allow.toml` exists and the residual on a clean tree is zero. Two
   entries in the list above did not survive the pass. `OperatorABC` is **struck** — a `Protocol` is
   not an abstract base class, so the seam is `Operator` (§2 row 10). And `InstallReport` is specified
   by no document and **not** by the charter, so no row was authored for it; `omniweave.install`'s
   owner interface is `AgentTarget.install(loc, opts) -> WriteResult`
   ([interfaces](10-interfaces.md) §7.1), which §2 row 39 now names instead of the phantom.
2. **`block_cite` is specified twice with different columns.** Charter §6.1's token table writes the
   unique index as `block_cite(doc_ord, gen, cite)`; §D2 and the terminology lock both write
   "`block_cite` is `UNIQUE(doc_ord, cite)` with **no `gen`**", and D2's reasoning is explicit — a
   cite must name at most one row for the life of the corpus, so inserting a block on re-parse cannot
   re-point a shipped citation. I have written §4.1 on the no-`gen` form, because the lock is binding
   alongside the charter and the with-`gen` form would make a re-parse silently mint a second live
   meaning for one cite. **Closes:** [storage and retrieval](07-store-and-retrieval.md) printing the
   index DDL, and a one-line correction to charter §6.1.
3. **`vectors = "off"` yields `ChannelStatus.OFF`, not `EMPTY`, and one charter line says
   otherwise.** Charter §D5 line-comments the fusion property test with "`vectors = "off"` makes
   `semantic` EMPTY", but the same block's arithmetic gives "four (no semantic) = 4.6/61" — which is
   only true if `OFF` contributes nothing to the ceiling — and the lock's `ChannelStatus` row says
   `off` is an operator choice that is disclosed while `ok`/`empty` are the two that contribute
   weight. I have written §4.1 with `OFF`, contributing nothing to the ceiling and **not** forcing
   `degraded`. Note that half (a) of ST6's property test was justified in the charter by the
   `EMPTY` reading, so fixing the comment without re-reading the test would break the test's stated
   rationale on the shipped default. **Closes:** [storage and retrieval](07-store-and-retrieval.md)
   stating the ceiling's status set explicitly, in one sentence, next to `_weight()`, and restating
   ST6 half (a) over a channel set with a routinely-empty `exact` channel.
4. **Which driver wins on re-ingesting an omniweave-built PPTX.** Both `parse.office.anydoc` (whose
   `formats` include `pptx`) and `parse.pptx.native` (the target's `read_back`) are admitted
   candidates, and the shipped rule `decode.office-native` names `parse.office.anydoc` by id with
   `terminal = true` for `pptx`. §4.3's re-ingest table therefore says plainly that at release 1 the
   `read_back` path is exercised by `ow out back` and the golden suite, and that an ordinary
   `ow ingest` over the output root resolves anydoc. **Closes:** a `[[rule]]` in
   `00-builtin-route.toml` keyed on the artefact registry (a matching `artifact` row with
   `read_back_doc_ord IS NULL`), specified in [ingest and routing](05-ingest-and-routing.md) and
   [generation](09-generation.md). Without it, R2 and R4 go unexercised outside the golden suite,
   which is the exact shape of a round-trip law that quietly stops holding.
5. **`acquire/1` has no shipped driver, and charter §3.1 implies one — CLOSED** by
   [ADR-3](adr/0003-shipped-configuration.md) decision 5, on the second branch: `fs` is core-side,
   `acquire/1` is a live Port with no in-tree implementation at release 1, and charter §3.1's
   "(fs, url, connectors)" is loose prose retired by erratum `E39`. §3.2's distribution table in
   [ingest and routing](05-ingest-and-routing.md) therefore stays at fourteen rows and `layers.toml`
   at fourteen lines. **§3.1 above is that statement's sole home; this entry is a pointer and carries
   no fact of its own.**
6. **Whether `op.identify` writes L2 `part` rows or only `unit.part_count`.** The `work` CHECKs settle
   the larger question this document originally raised — routing must precede the routed work row, so
   `run/expand.py` and `omniweave.plan` are two passes inside one expander task, and the boundary is
   forced rather than chosen (§4). What remains is narrower: charter D6 says `op.identify`
   "materialises part rows", and `part` is also the name of an L2 table that `DocSink.part` writes
   with a `store_ref`. Either `op.identify` writes `part` rows with a NULL `store_ref` that a later
   parse fills in, or it writes only `unit.part_count` and every `part` row comes from `DocSink`. I
   have written the second reading, because a `part` row is defined as "named byte streams of the
   original container, hash-pinned" and `op.identify` does not read bytes. **Closes:** one sentence in
   [the runtime](08-runtime.md) or [the document model](03-document-model.md) saying which component
   inserts a `part` row.
7. **The stability tier of `omniweave_core.retrieve`.** I tier it T-PUBLIC because three surfaces
   call `retrieve()` and the SDK exposes it. But `Verdict` is a stored-shape-adjacent record whose
   fields the MCP envelope serialises through `schema/verdict-v1.json`, which is T-GENERATED and
   byte-diff gated — so a field addition is simultaneously a public API change and a generated-schema
   change. **Closes:** [interfaces](10-interfaces.md) stating whether a `Verdict` field addition is a
   MINOR (additive, generated schema regenerated) or a `CONTRACT` event. My assumption, on which
   rows 27 and 49 rest: additive is a MINOR, removal is a MAJOR, and no `Verdict` change is a
   `CONTRACT` event, because no third party implements `Verdict`.
8. **Whether `omniweave` keeps its edge to `omniweave-office`.** This is charter F33 verbatim, and it
   is the only first-party edge in §3.1 not forced by a protocol. **Closes:** counting
   platform-support issues attributable to `firecrawl-anydoc` in the first two releases.
   Pre-committed fallback: move office behind `omniweave[office]` with a one-line remedy printed in
   the "no driver for .docx" error. Only the dependency row changes, so no component in §2 moves and
   §3.2's fourteenth row loses one entry.
9. **The blocks-per-page envelope invalidates §5.5 and §5.7 if it is wrong** (charter F1). Every
   number in those two sections scales off 60–120 blocks/page. If dense corpora land near 300/page,
   the 8,192-block Frame target, the 600 MB supervisor RSS gate and the ~26 GB store projection all
   retune, and T2 arrives at 5M blocks rather than 50M. **Closes:** `fixtures/gen/gen_5000p_pdf.py`
   plus ten real 200-page documents, counting blocks per page **including cells**, with
   `store.bytes_per_block` as a nightly ratchet.
10. **A sub-page commit boundary** (charter F29). §5.4 makes `loop_lag_max_ms = 250` the guard on a
    long commit, and a 4M-cell sheet is one page, therefore one transaction, therefore a multi-GB WAL
    and a multi-minute commit the WAL valve **cannot** help with mid-transaction. Generation staging
    fixed the 5,000-*page* case; this residue is narrower and real, and it is the one place where
    §5.4's concurrency story has a hole rather than a mechanism. **Closes:** measuring it on the
    4M-cell fixture. Pre-committed fallback: `MAX_BLOCKS_PER_DOC` plus a `ResourceLimit` refusal
    naming the knob — not a speculative new work-table unit.
11. **The persisted probe verdict cache had no declared validity key. Answered by
    [ADR-7](adr/0007-driver-resolution-keys.md).** Charter D1 says the probe verdict is "cached per
    run" and separately lists "the probe verdict cache" among what `$OMNIWEAVE_HOME` holds; those two
    statements need one key between them. The per-run memo is authoritative and the persisted entry
    advisory, keyed `(driver_id, driver_version, card_sha256, env_digest)` — four components, with
    `card_sha256` in the key so that a card edited in place under an unchanged `[driver] version`
    invalidates it — and `ow doctor --runtime` always re-probes (§2 row 9). **`env_digest` is the one
    name for the environment half of that key; `host_fingerprint` is retired**, and
    [the driver system](04-driver-system.md) §4.7 is the sole home of its recipe. That recipe digests
    *identities* — `(realpath, st_size, st_mtime_ns)` — rather than presences, which is what stops a
    CUDA 12.4 → 12.6 upgrade or an in-place `tesseract` upgrade from serving a stale `ok`.

## New terms

Coined here and offered for the lock. Each is a name for something the charter describes but does not
name, or a name the charter uses as a class with no §2 row (see Open question 1).

| term | kind | definition |
|---|---|---|
| `Catalog` | type | The metadata-only driver index built by `omniweave_core.discovery` from `importlib.metadata` and `tomllib` alone, holding one validated `DriverCard` per discovered `DriverId` plus a `catalog_digest` that enters `resolve()`'s memoisation key. Built **without importing anything** (INV-4), and **frozen into the `RunContext` at startup**, so a driver installed mid-run is invisible until the next run. Already used as a class name in the charter with no lock row. |
| `Config` | type | The frozen result of resolving the five configuration layers plus the declared `OMNIWEAVE_*` twins, exactly once at startup: `get`, `source_of`, and the `semantic`/`operational` projection behind `semantic_digest`. A call-site argument overrides a value **for that call** and never mutates it, which is what makes `ow show-config` a true statement. Printed in §8.4. |
| `ConfigValue` | type | The whole value grammar a config leaf may take: a `Scalar`, a tuple of `Scalar`, a tuple of tuples of `Scalar` (`serve.packing.tier` alone), or a `Mapping[str, Scalar]`. Four shapes, **non-recursive** — which is what "flat and JSON-canonicalisable by contract" means operationally, and why there is no `str()` fallback to reach (I12). |
| `ConfigAxis` | member | `Literal["semantic", "operational"]`. Declared at the key's site, required by the `ConfigKey` constructor, and the only thing `semantic_projection()` reads. |
| `ConfigKind` | member | The ten coercer names — `str`, `int`, `float`, `bool`, `path`, `enum`, `list`, `table`, `matrix`, `str_or_list` — one per distinct `type` in [18](18-api-sketch.md) §4's key table. Named rather than special-cased, so the coercion table has no `else`. |
| `ConfigLayer` | type | The precedence chain as an ordered `IntEnum`, lowest first: `BUILTIN`, `USER_FILE`, `PYPROJECT`, `PROJECT_FILE`, `EXPLICIT_FILE`, `ENV`. §8.1's numbered list orders the file chain; `ENV` is above all of it because the twins are applied over the file layers. |
| `ConfigSource` | type | Where one resolved value came from: a `ConfigLayer`, the file and line for a file layer, the winning twin for `ENV`. Its `render()` is exactly what `ow show-config` prints after `source:`. |
| `ConfigKey` | type | One key's declaration: name (glob segments allowed), `ConfigKind`, default, **required** `ConfigAxis`, declared `OMNIWEAVE_*` twin, enum `choices` and an `item_kind`. The registry of these is what `tools/config_axes.toml` is generated from and G18 byte-diffs, which is why an unclassified key is a `TypeError` at import rather than a CI finding. |
| **stability tier** | concept | A component's compatibility promise, one of five: `T-CONTRACT`, `T-SCHEMA`, `T-PUBLIC`, `T-GENERATED`, `T-INTERNAL`. Derived from the three version axes; it says who may depend on a component and which event moves it. A tier is a promise about **one file**: a hand-written module that emits a generated artefact carries its own tier and the artefact is tiered separately. |
| `T-CONTRACT` | member | A stability tier: a third party pins it and builds against it; it moves only on a `CONTRACT` bump, on a `RELEASE` MINOR, announced and migration-guided, with G16 loading the previous two releases' template drivers against HEAD. |
| `T-SCHEMA` | member | A stability tier: a published read contract over stored rows or digests; it moves only on a `SCHEMA` major with a two-release deprecation window. `[DER]` objects are outside the promise. |
| `T-PUBLIC` | member | A stability tier: semver'd with `RELEASE`, documented, and typed in `omniweave/sdk/_generated.pyi`. A MINOR may add; a MAJOR may remove. |
| `T-GENERATED` | member | A stability tier: never hand-written, byte-identical to its generator's output, and gated by a `--check` byte diff (G6, G18, G20, G25). Editing one by hand fails the build. |
| `T-INTERNAL` | member | A stability tier: no promise. It may change on any `RELEASE` MINOR, and only its own tests constrain it. |
| **startup sequence** | concept | The nine ordered steps every `ow` process runs before any work: dispatch, config, limits, digests, surface invariants, store open, catalog freeze, write lock, loop. Steps 1–5 touch no store, which is what makes the cold-start budgets reachable; each step names the error class a failure raises and the exit code it produces (§5.3). |
| `ConfigError` | type | The `OW-C-*` member of the `OwError` tree: a configuration or startup failure, raised **only** during resolution and never after it. A model-id mismatch on attaching a Service is one, because retrying attaches to the same wrong server. |
| `ModelError` | type | The `OW-M-*` member: an L2 violation — an unknown non-`unknown` `Kind` on read, a retired `cite` with no `superseded_by`, a torn generation. |
| `DriverHostError` | type | The `OW-D-*` member: a driver-protocol failure attributable to **the framework or the wire**, not to the driver — a frame violating `wire.py`'s caps, an unknown frame `kind`, a card/code mismatch at `activate()`. Deliberately distinct from `FailureClass.driver_crashed`, which is the driver's. |
| `RouteError` | type | The `OW-R-*` member: a policy that will not load, will not lint, or names a key absent from the `SignalSpec` registry. |
| `StoreError` | type | The `OW-S-*` member: a snapshot expiry, a busy writer, a `MIN_SQLITE` floor breach, an open bulk-window marker, a tracked `.owstore`, a second concurrent `run()` in one process. |
| `GraphError` | type | The `OW-G-*` member: a cluster above `MAX_CLUSTER_EDGES`, an ungrounded item that must raise rather than quarantine, a trust clamp that cannot be applied. |
| `TargetError` | type | The `OW-T-*` member: an OUT construct or gate failure that must abort rather than record a `Finding`. |
| `SurfaceError` | type | The `OW-A-*` member: an ambiguous `cite` across the corpora a session touched, an unlisted tool, an unauthenticated non-loopback bind. |
| `PolicyRefusal` | type | The `OW-P-*` member: a licence tier, `restriction_bits`, or a missing egress `Grant`. A refusal, not a failure — it names the approving command. |
| `QualityError` | type | The `OW-Q-*` member: an incomplete `MeasuredOn`, an unblessed golden diff, a cassette miss under `--cassette required`. |
| `ResourceLimit` | type | The cross-area `OwError` whose constructor **requires** `limit`, the name of the knob that would need raising. It is the one error obliged to name a knob, which is why it is not confined to a single area letter. Already used as a class name in the charter with no lock row. |
