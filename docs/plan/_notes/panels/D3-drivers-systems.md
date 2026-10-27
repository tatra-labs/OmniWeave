# D3 — The driver / plugin / extension system

**Panel: D3-drivers · Architect prior: THE SYSTEMS PURIST · 2026-09-01**

---

## Headline

**A driver declares itself in a static manifest that the host reads without importing it; selection
is a pure function over manifests that always returns both the candidate set and a typed rejection
list; every non-first-party driver runs in a supervised subprocess that never receives a writable
root; and a licence-encumbrance bit on the manifest propagates onto every artifact the driver
touches.**

The one-line justification: **discovery must not be execution.** Every plugin system in the
collection makes discovery *be* execution, and every consequence we care about — router evidence,
licence gating, catalog building, failure isolation, install weight — falls out of that single
mistake. I verified it in source: pluggy's `PluginManager.load_setuptools_entrypoints` calls
`ep.load()` and `self.register(...)` inside its distribution loop, and docling's
`allow_external_plugins` check happens in the *next* loop, over `list_name_plugin()`
(`docling/docling/models/factories/base_factory.py:88-115`). So docling's opt-in gate suppresses
*registration*, not *execution*: a third-party module's import-time side effects have already run by
the time the gate says no. markitdown has the same shape without even the gate —
`_load_plugins()` does `entry_point.load()` for every `markitdown.plugin` entry point
(`markitdown/packages/markitdown/src/markitdown/_markitdown.py:63-81`), which is exactly how
`markitdown-ocr` drags mandatory AGPL PyMuPDF into a process that believes it is MIT
(`markitdown/packages/markitdown-ocr/pyproject.toml:31`).

That is not a bug to patch. It is a contract shape, and it is one of the three or four decisions in
this framework that cannot be reversed later, because the day a driver's entry point is a callable
is the day the router can never see cost without paying it.

---

## Design

### 1. One extension type, called a driver, with a role

There is exactly one kind of replaceable part: a **driver**. It fills a **role**. Roles are a
closed, core-owned vocabulary:

| Role | Consumes → produces | Schedulable | Example |
|---|---|:-:|---|
| `acquire` | locator → `raw_bytes` | ✅ | S3, SharePoint, crawl |
| `detect` | `raw_bytes` → media type + format evidence | ✅ | content sniffer |
| `parse` | `raw_bytes`/`page_image` → `doc_blocks` | ✅ | pdfium, OOXML, olmocr |
| `extract` | `doc_blocks` → typed fields | ✅ | schema-constrained VLM |
| `chunk` | `doc_model` → `chunk_set` | ✅ | layout-aware chunker |
| `embed` | `chunk_set` → `embedding_set` | ✅ | bge-m3 |
| `structure` | `doc_model` → `graph_delta` | ✅ | AST, entity extraction |
| `generate` | `il_source` → `artifact_file` | ✅ | PPTX, MP4, DOCX compiler |
| `engine` | — (a shared resource) | ✖ | a vLLM server, an ONNX session |
| `store` | — (a backend) | ✖ | SQLite, Postgres, S3 blobs |

Roles are closed for the same reason artifact kinds are closed (§4 below). Adding a role is a core
release and a feature-level bump.

**Naming reconciliation with `mine-runtime.md` §7.1.** That reference design calls the schedulable
unit an *operator* (`OperatorABC`) and calls a resource `ctx.driver(kind)`. I am overturning both
halves of that vocabulary, and here is why: two names for one lifecycle is how you end up with two
registries, and a system with two registries has two collision policies, two version schemes and two
licence gates. In this proposal:

- `OperatorABC` becomes `Driver`, and its `ClassVar` block (`NAME`, `CONSUMES`, `PRODUCES`,
  `COST_CLASS`, `GRANULARITY`, `DETERMINISTIC`) is **lifted out of the class and into the manifest**,
  because a `ClassVar` requires an import to read and that is the whole problem.
- `ctx.driver(kind)` becomes `ctx.acquire(role, name)` and returns a `DriverHandle`. An `engine` is
  a driver whose role is not schedulable. One registry, one collision policy, one licence gate.

Everything else in §7 — `StepResult`, `Outcome`, `UnitRef`, `RunContext`, `canonical_uri`, the `work`
table, invariants I1–I18 — I adopt unchanged. This is a naming and locus change, not a semantic one,
and D6 should treat it as such.

### 2. Discovery: an entry point that names a data file

A distribution declares:

```toml
[project.entry-points."omniweave.drivers"]
manifest = "omniweave_pdfium/omniweave.toml"
```

The value is a **POSIX-relative path inside the installed tree**, never `module:attr`. The resolver
does `Path(dist.locate_file(value)).read_bytes()` — `importlib.metadata.Distribution.locate_file`
resolves against the install root **without importing anything**. A value containing `:` is rejected
with `MANIFEST_NOT_A_PATH` and the message "omniweave never imports from a driver entry point."

Three manifest sources, in precedence order, and a shadow is **reported, never silent** (this is
DataFlow's `apply_whitelist` report shape — `DataFlow/dataflow/utils/registry.py` — generalized):

1. `<project>/.omniweave/drivers/*.toml` — project-local, for development and vendored drivers.
2. `$OMNIWEAVE_HOME/drivers/*.toml` — user-installed.
3. `omniweave.drivers` entry points across installed distributions.

`omniweave drivers list --explain` prints, for every name: which source won, which sources were
shadowed, and why. A misspelled driver name in config surfaces as `missing_in_catalog`, not as
silence.

### 3. The manifest is the capability descriptor

One file per distribution, `[[driver]]` array, so a distribution can ship a family (a `parse` driver
and the `engine` it needs) with one licence block and one contract declaration. Full shape in
**Concrete shape §A**. The load-bearing design choices:

- **Identity is `<role>.<subject>.<impl>`, regex-enforced**, and the fully-qualified id is
  `<name>@<dist>`. A duplicate `name` from two distributions is **a resolve error**, fixable only by
  qualifying with `@dist` in config. This closes both silent-failure modes at once: DataFlow's
  `_do_register` is first-registration-wins on a bare `__name__` key with no warning
  (`DataFlow/dataflow/utils/registry.py`), and graphrag's `PipelineFactory.register` silently
  *overwrites*. Both are wrong in opposite directions and both are silent.
- **`config` is a JSON Schema (draft 2020-12) in the manifest.** This is the piece nobody has.
  docling's factories dispatch on `type(options)` and build a dynamic CLI enum from registrations
  (`base_factory.py:38-45, 54-59`) — elegant, and I am taking the *principle* ("adding an engine =
  adding an options type; nothing else has to know"). But dispatching on an options *class* requires
  importing it, so the router still cannot price a driver it has not loaded. A JSON Schema in the
  manifest gives validation, `--help` text, CLI enums, and a computable `config_digest` with zero
  imports.
- **Cost is declared as a bound and then measured.** `cost.class`, `cost.unit`,
  `cost.p50_ms_per_unit`, `cost.p95_ms_per_unit`, `cost.micros_per_unit`. The conformance kit
  measures p50/p95 on the golden corpus and the registry stores the measurement. The router prefers
  measured over declared. A driver whose measured p95 exceeds 3× its declared p95 fails conformance
  with `COST_DECLARATION_VIOLATED`. This is the honesty mechanism, and it exists because the
  collection's cost surface is attacker-controllable: olmocr's `MAX_TOKENS = 8000` ×
  `--max_page_retries` default 8 = 64 000 output tokens/page ⇒ **$0.0128/page, 64× its own
  $0.0002/page baseline** (`olmocr/pipeline.py:107,1221`), with remaining retries fired in parallel
  (`:343-350`); Unlimited-OCR's `MAX_RETRIES = 5 × REQUEST_TIMEOUT = 1200` = **100 minutes of a GPU
  per document** (`Unlimited-OCR/infer.py:21-36`). A driver that can do that must say so in a field
  the router reads before it runs.
- **Capability is role-scoped.** `[driver.capability.parse]` adopts `mine-parse.md` §E11's
  vocabulary almost verbatim (`spatial`, `charspan`, `reading_order`, `sections`, `tables`, `math`,
  `assets`, `notes`, `confidence`, `furniture`, `round_trip`). `[driver.capability.embed]` has
  `{dim, metric, max_tokens, normalized, pooling, languages}`. Each role's capability schema lives
  in core and is versioned by feature level. This is what keeps the descriptor rich without becoming
  a union of every role's fields.
- **`hardware.needs_network` is load-bearing, not documentation.** A driver declaring
  `needs_network = false` is *run with no egress* (§6), and the conformance kit fails it if it
  attempts a connect. This makes anydoc's strongest structural property — eight Rust crates with
  **no HTTP client of any kind**, so it cannot SSRF, exfiltrate, or fetch a remote entity by accident
  — into something a third-party Python driver can also assert and be held to.
- **Benchmarks require provenance or are rejected.** Every `[[driver.benchmark]]` entry must carry
  `measured_on = {weights, runtime, runtime_version, sampling, prompt_version}`. HunyuanOCR is the
  cautionary case: its published 94.10 OmniDocBench was measured on TensorRT while the repo ships
  Transformers and vLLM, which it admits disagree. A model configuration is
  `(weights, runtime, runtime version, sampling params, prompt version)`, and a benchmark number
  without that tuple may not enter a router's quality table.

### 4. Artifact kinds are a closed, core-owned vocabulary

A driver may not invent an artifact kind. Kinds are registered in core with a version; extension is
a core release plus a feature-level bump. Reason: if drivers can invent kinds, the pipeline DAG
degenerates into ad-hoc string matching — which is exactly what DataFlow does, parsing
`input_*`/`output_*` kwarg *name prefixes* to build its graph, so the DAG depends on parameter
spelling. With a closed vocabulary, `omniweave plan --check` can statically prove a pipeline's edges
resolve before any driver is imported.

Cost, stated: a genuinely new capability waits for a core release. Mitigation: an `x-` experimental
kind namespace that `resolve()` admits only under `policy.allow_experimental_kinds = true`, and which
can never appear in a pipeline reachable from a `serve` surface.

### 5. Selection is three stages and the split is the point

```
resolve(demand, catalog, policy) -> Resolution{candidates, rejected}     # PURE. no imports.
  ↓  D4's router picks from candidates on cost/quality evidence
activate(candidate, config) -> DriverHandle                              # imports, probes, spawns
  ↓
handle.invoke(units, ctx) -> Sequence[StepResult]
```

- **`resolve()` is a pure function of `(demand, catalog, policy)`.** No imports, no network, no
  clock; the only IO is reading manifests, which is cached and content-hashed per run. It is
  therefore **hashable and deterministically replayable**: `resolution_digest` goes in the run
  manifest, and `omniweave drivers why <demand>` replays it offline. This is what makes "why didn't
  it use the good parser" a one-command answer instead of an archaeology project.
- **`rejected` is required output, not a log line.** Every rejection is
  `(name@dist, RejectReason, detail)` from a closed enum (**Concrete shape §C**). A demand with zero
  candidates returns a `Resolution` whose `rejected` list *is* the error message. This is
  omniparse's failure inverted: omniparse's `--documents`/`--media`/`--web` flags gate model loading
  and OpenAPI visibility but **not route registration** — `app.include_router` runs unconditionally
  at module scope (`omniparse/server.py:33-37`) before `load_omnimodel` runs inside `main()`
  (`:52-78`), so a `--documents`-only deployment still serves `POST /parse_media/audio` into a `None`
  whisper model and returns a 500 with a `NoneType` message. The idea (capability groups gated by
  policy) is right; the implementation must build the enabled set from the descriptor and register
  once, and a disabled capability must name the policy that would enable it.
- **`activate()` probes the capability, not the import.** LDR's SQLCipher probe is the model: create
  a temp DB, key it, apply pragmas, read back the version. Every optional dependency needs this — a
  `tesseract` present without the language pack, a CUDA torch that imports and dies on first kernel
  launch, a `pdfium` that loads and cannot open an encrypted PDF, an Ollama client with no model
  pulled all import fine. The probe runs the smallest real operation; the verdict is cached per run
  *and* persisted keyed by `(name@dist, driver_version, host_fingerprint)` with a 24 h TTL, because
  probing a GPU driver costs seconds. A red probe **prunes the plan with a report**; it never raises
  `ImportError` at the bottom of a stack trace, and `sys.exit()` is banned in driver and core library
  code (graphrag's `validate_config_names` kills the process).

### 6. Isolation: subprocess by default, and the driver never gets a writable root

This is where I spend engineering budget to avoid a structural mistake.

**Default isolation for any driver whose trust tier is not `first_party` or `vendored` is
`subprocess`.** One `DriverHost` worker process per `(name@dist, config_digest, isolation profile)`,
supervised by a `DriverSupervisor` in the host, speaking a length-prefixed framed protocol over a
**unix domain socket / Windows named pipe with 0600-equivalent permissions**. Not a loopback TCP
port: LEANN's embedding server is a ZMQ REQ/REP socket on a dynamic loopback port with no auth and
no CURVE, so any local process on a shared host or CI runner can submit text for embedding or probe
msgpack paths — and the fix nobody in the collection applies is a UDS with filesystem permissions.

`inproc` is **representable only** for `trust ∈ {first_party, vendored}` **and** `cost.class = free`
**and** `hardware.gpu = none` **and** `hardware.needs_network = false`. That set is small, it is code
we own, and it is auditable. A manifest asking for `inproc` outside it is rejected at resolve with
`ISOLATION_NOT_PERMITTED`. There is no flag that widens this; widening is a code change in core.

Why pay for it, on the evidence:

- Parsers segfault. anydoc is the only fuzzed parser in the collection (12 cargo-fuzz targets) and
  "the only defence here that found bugs before shipping." pdfium, libxml and image codecs are C in
  the hot path of untrusted input.
- Parsers hang. `subprocess.run(..., check=True)` with no `timeout=` on `libreoffice`
  (`omniparse/omniparse/documents/router.py:97-128`); 100 GPU-minutes per document
  (`Unlimited-OCR/infer.py`); markitdown's `convert_uri` passes no `timeout=` at all.
- Parsers OOM. codegraph produced **22 GB of WAL and an exit-137 OOM-kill at an envelope the
  un-valved build survived**.
- In-process, each of those kills the run and loses completed work. codegraph's own measured lesson
  is that **"the most expensive failure available is one that discards completed work"** — 79 s of
  index builds against a 60 s liveness watchdog meant a SIGKILL right after the work was done. Out
  of process, the same event is one `FAILED_PERMANENT{failure_class = DRIVER_CRASHED}` row against
  one unit, and the other 3 999 pages survive.

**The driver never receives `output_root` or `cache_root`.** It receives `source_root` read-only
where the OS supports it, a per-invocation temp dir it owns, and blob *references*. It returns
artifacts; the **host** writes them. This converts the stage-ownership invariant (I4:
"an operator's re-run replaces only rows whose `origin_operator` is its own") from a convention
enforced by review into a property enforced at the process boundary. It also makes graphify's four
recorded CWD bugs — #1774 (cache written into the analysed tree), #2316 (`git rev-parse HEAD` with no
`cwd=` stamping the invoking repo's commit into the target's graph), #1747, `_stabilize_rebuild_cwd`
— structurally unrepresentable for a driver, because the driver has nowhere to write.

Enforcement in the worker, all from the manifest:

| Control | Linux | macOS | Windows | Degradation if unavailable |
|---|---|---|---|---|
| Address space | `RLIMIT_AS` | `RLIMIT_AS` | Job Object `ProcessMemoryLimit` | `memory_limit: none` recorded |
| No-progress deadline | parent-side timer on `PROGRESS` frames | same | same | — (always available) |
| Hard wall deadline | SIGKILL | SIGKILL | `TerminateJobObject` | — |
| No egress | net namespace (`unshare -n`) | process-level socket guard | process-level socket guard | `network_isolation: process_level` recorded |
| Read-only source | bind mount / `mount --bind -o ro` | process-level guard | process-level guard | `fs_isolation: process_level` recorded |
| Untrusted native code | `container` tier | `container` tier | `container` tier | not day one |

**State the degradation; never claim an isolation you did not get.** That is invariant I18 applied to
the driver boundary, and it is the difference between a security property and a security claim. The
degradation string appears in the run manifest's `degradations[]` and in the response envelope's
`Freshness.degradations` — the same channel every other degraded subsystem uses.

**Two deadlines, not one.** `progress_ms` (no `PROGRESS` frame received) and `wall_ms_hard` (total).
A single total deadline is how codegraph's `STALE_TIMEOUT_MS = 2 min` made a legitimate 3-minute bulk
index lose its lock mid-write. A driver that reports progress may run long; a driver that goes quiet
dies.

**Batching, because per-unit IPC does not pay at page granularity.** One `INVOKE` frame carries up to
`batch_max_units`; the worker returns one `RESULT` frame per unit. **The batch is a transport detail,
invisible to the `work` table** — the supervisor commits each unit's row individually, which
preserves mine-runtime §7.10.1's property 3 ("row identity is stable and independent of batching"),
the exact property DataFlow fails. Payloads over `INLINE_MAX = 256 KiB` travel as content-addressed
blob references, not bytes, which is DataFlow's "paths, not payloads" failure inverted: a reference
resolves from a local dir at T1/T2 and from object storage at T3, so scale-out needs no protocol
change.

### 7. Licence tiering, and the encumbrance bit that propagates

The manifest carries **two** licence blocks, because one is the trap:

```toml
[driver.licence]        # the CODE
[driver.model_licence]  # the WEIGHTS — absent means "no weights"
```

marker, surya and lift ship an Apache-2.0 top-level `LICENSE` that mentions weights nowhere, plus a
byte-identical `MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`, modified AI Pubs OpenRAIL-M)
whose Attachment A clause 2(c) bars use if you offer any competing product — no revenue threshold, no
research carve-out — and whose **clause 8 (`marker/MODEL_LICENSE:39`) licences the Output**:
"You agree to apply this License (to the exclusion of all others) … to the Output and any
derivatives." A single `spdx` field cannot express that. Two blocks plus these fields can:

- `tier ∈ {permissive, weak_copyleft, strong_copyleft, network_copyleft, source_available,
  field_restricted, noncommercial}`
- `output_encumbered: bool` — **the field that catches clause 8**
- `territory_excluded: [ISO-3166-2]` — the field that catches HunyuanOCR's exclusion of the EU, UK
  and South Korea (`HunyuanOCR/License.txt:3,17`) with §5(c) (`:35`) reaching *Output*
- `field_of_use_excluded: [...]` — the field that catches its AUP #14 (`:68`) bar on law
  enforcement, migration, medicine, credit, employment, housing, education, insurance
- `redistribution: allowed | internal_only | forbidden` — the field that catches jcodemunch-mcp,
  where **no tier at $79/$349/$1 999 permits embedding, redistribution or SaaS provision**
- `notice_required: bool`, `notice_path`, `licence_url`

**Default policy is `accept_tiers = ["permissive"]` and `accept_output_encumbered = false`.** Any
widening is per-driver, names the SPDX id again, and **carries a credential, not a flag**:

```toml
[[licence.accept]]
driver              = "parse.pdf.marker_code"
spdx                = "Apache-2.0"
model_licence_spdx  = "LicenseRef-AIPubs-OpenRAIL-M"
output_encumbered   = true
acknowledged_by     = "legal@example.com"
acknowledged_at     = "2026-09-01"
acknowledgement_ref = "https://tracker/LEGAL-412"
```

`acknowledged_by` / `acknowledged_at` / `acknowledgement_ref` are **required** and land in the run
manifest and in every produced artifact's provenance. This is the digest's rule made mechanical: the
recurring anti-pattern is "the safety mechanism exists and its default disables it"
(`docling.datamodel.settings.DocumentLimits.max_file_size = sys.maxsize`; docling's `revision`
defaulting to `"main"` while its own docstring says the field exists for reproducibility; olmocr's
`--apply_filter` being `action="store_true"`; DataFlow's `--host` defaulting to `0.0.0.0` in four
places). Fail-closed defaults, and the widening is a credential.

**The propagating bit.** When `resolve()` admits a driver with `output_encumbered = true`, every
`StepResult` it produces is stamped `encumbrance = {driver, spdx, clause_ref}`, and that stamp
**merges upward onto the L2 document and onto every artifact derived from it**. A `generate` driver
or an export surface can then refuse, or attach the required notice, or ask. Nothing in the 22 repos
does this, and it is the only mechanism I can construct that prevents a single OpenRAIL-M parser from
silently placing every customer's parsed contract under a competitor bar. It costs one field on
`StepResult` and one merge rule.

**Loud labelling, three surfaces:** `omniweave drivers list` marks restricted drivers with their
tier and the clause; the CLI prints a one-line banner naming driver, SPDX and clause on first
activation per run; and every response envelope carrying restricted output includes
`licence_notices[]`. The transitive gate must resolve the **full dependency graph and run an
import-graph scan against the declared set** — `cairosvg` (LGPL-3.0) is imported by
`ppt-master/.../svg_to_pptx/pptx_package/media.py` and `visual_review.py` and appears in **no**
requirements file. A manifest-only gate misses it, and a gate that misses `cairosvg` is
manifest-only.

### 8. Contract versioning and deprecation

Two numbers, two jobs:

- **`contract` (major int)** — the ABI: the wire protocol, the frame kinds, `StepResult`'s shape, the
  manifest's top-level structure. Core supports exactly `N` and `N-1`. A major bump requires a
  12-month overlap, an adapter in core that speaks `N-1`, and a conformance matrix run against both.
- **`feature_level` (int, additive within a major)** — new capability sub-schemas, new artifact
  kinds, new roles, new optional frame kinds. A driver declares `feature_level_min` it *requires* of
  the host, never an exact level. A driver requiring 9 on a host at 7 is refused at resolve with
  `FEATURE_LEVEL_TOO_HIGH` and the message naming the minimum core version — **no import**.

**Deprecation is data.** Every deprecated manifest field carries `deprecated_in`, `removed_in`,
`replacement` **in the published schema**, and the resolver emits a structured
`DriverDeprecation{driver, field, deprecated_in, removed_in, replacement}` into the run manifest's
`degradations[]`. Not `warnings.warn` — graphify reports cache vintage, corruption and re-bill
through `warnings.warn(RuntimeWarning)`, which is filterable, unstructured and invisible under JSON
logging. A driver still using a field past `removed_in` fails resolve. `CONTRACT.md` in core is the
changelog, one entry per feature level, naming exactly what it added; a level bump with no entry
fails CI.

### 9. The conformance kit

Shipped as a separate distribution, `omniweave-conform`, so a third party installs it without core's
dev stack. CLI: `omniweave conform ./omniweave.toml`.

**Its thesis: the kit tests the honesty of the descriptor, not the excellence of the driver.** A
driver declaring `spatial = "none"` is not failed for having no bounding boxes; it is failed if it
declares `block_bbox` and returns none. This is the only bar that a third party can meet without
matching the best driver in the field, and it is the only bar that makes the router's evidence
trustworthy — which is the actual thing we need.

Suites (full list in **Concrete shape §E**):

| Suite | Roles | Bar | Budget |
|---|---|---|---|
| `manifest` | all | schema-valid; closed vocabularies; every benchmark has `measured_on`; `config` schema compiles; no field past `removed_in` | < 1 s |
| `capability` | role-specific | every declared capability is *exercised and present*; every undeclared one is *absent* | < 90 s |
| `idempotence` | all | two runs byte-equal when `deterministic = true`; shape-stable otherwise | < 60 s |
| `purity` | all | result unchanged under perturbed `CWD`, `HOME`, `TZ`, `LANG`, `PYTHONHASHSEED` | < 60 s |
| `limits` | `acquire`,`parse`,`detect` | the bomb corpus returns typed `LIMIT_EXCEEDED`; never OOM; never exceeds declared `memory_mb` | < 60 s |
| `sandbox` | all | `needs_network = false` ⇒ no connect attempt; no write outside temp dir | < 30 s |
| `cost` | all | measured p95 ≤ 3× declared p95; a `free` driver makes no socket/exec syscall | < 90 s |
| `injection` | `parse`,`extract`,`acquire` | output wrapped/defanged per §10 | < 30 s |
| `fuzz` | `parse`,`detect`,`acquire` | N minutes mutation fuzz: **crash allowed, hang not** | tiered, 10 min default |

Two deliberate calls:

- **The mandatory suites run in under 5 minutes on a laptop.** A kit that takes an hour gets skipped,
  and a skipped gate is not a gate.
- **`fuzz` allows crashes.** A crash inside a subprocess-isolated driver is a legitimate typed
  outcome; a hang past `wall_ms_hard` is not. Requiring "no crashes" would exclude every real parser
  in the collection except anydoc, and a bar nobody clears is a bar nobody attempts.

**Golden corpus** must be licence-clean and shippable, so it is **our** corpus with olmOCR-Bench's
*taxonomy* (`baseline | present | absent | order | table | math | format | footnote`, `max_diffs`
fuzzy budget, relational `TableTest{cell, up/down/left/right, top_heading, left_heading}`), plus
lift's adversarial extraction categories (cross-page, exhaustive lists, must-be-null, near-miss
distractors, multi-source) and anydoc's bomb corpus. Report **both** field and full-document
accuracy: lift measures **90.2 % per field but 20.9 % full-document** on its own adversarial
benchmark, so per-field accuracy does not compound and a single headline number is a lie.

**The report is the artifact, and a report supplied by the submission validates nothing.** Output is
`conformance-report.json` = `{driver, version, manifest_sha256, kit_version, host_fingerprint,
results[], measured_cost, degradations[], verdict}`. The catalog requires a report from kit version
≥ current minor. `omniweave drivers verify <name>` re-runs the kit locally against the installed
driver. And CI **runs the kit from a trusted ref, never from the PR branch** — awesome-skills'
`REVIEWING.md:35-41` states this as a review rule: "Never run scripts that come from the PR …
a validator supplied by the submission validates nothing." That is the `pull_request_target` class of
GitHub Actions vulnerability, and local-deep-research runs `zizmor` for exactly it.

### 10. Injection hygiene is a driver-contract obligation

Every `parse`/`extract`/`acquire` driver's textual output is untrusted input that will reach an agent
context. graphify's `llm.py` is the only implemented defence in 22 repos: it wraps every untrusted
file in `<untrusted_source path=… sha256=…>` and defangs chat-template sentinels by *form*
(`<\|[A-Za-z0-9_.\-]{1,64}\|>`) including a forged closing delimiter. The kit's `injection` suite
requires that shape, with graphify's three known defects fixed:

1. **Escape the path** interpolated into the prompt attribute.
2. **Defang a copy** — graphify's zero-width-space insertion shifts every later byte offset by 3,
   which breaks citation. The wrapped text and the citable text must be separate artifacts.
3. **Drop the heading-shaped sentinel `^###\s*instructions?$`** — it matches `## Instructions` in any
   manual, RFP or SOP.

And ship graphify's own honest claim verbatim rather than a stronger one: it "does not make injection
impossible, but changes it from 'works on first try' to 'requires evasion.'"

The kit also enforces the **OUT** direction, which nobody in the collection addresses: a `generate`
driver's artifact must contain no external references and no active content unless it declares
`capability.generate.active_content = true`, in which case it is `field_restricted` by policy.

### 11. Trust tiers, the lockfile, and the catalog

**Trust tiers** gate isolation and gate whether `inproc` is even representable:

| Tier | Meaning | Default isolation | `inproc` allowed |
|---|---|---|:-:|
| `first_party` | shipped in the omniweave repo | `inproc` if §6's four conditions hold | ✅ |
| `vendored` | in-tree at a recorded commit SHA, with header + NOTICE | as `first_party` | ✅ |
| `signed` | catalog-published, valid signature over `bundle_sha256` | `subprocess` | ✖ |
| `pinned` | third-party, pinned in `omniweave.lock` with `wheel_sha256` | `subprocess` | ✖ |
| `unpinned` | present but not in the lock | **refused** | ✖ |
| `untrusted` | explicitly marked | `container` | ✖ |

`vendored` exists because of a specific evidence pattern: graphify is Apache-2.0 today, has already
relicensed once (MIT → Apache-2.0 in 2026, both texts shipped), and is a single-owner VC-funded
project — the profile whose standard next step is a source-available relicense. Apache-2.0 is
irrevocable for the version you received, so the correct posture is **vendor at a recorded commit
SHA with the header and NOTICE in-tree; never a floating PyPI dependency**. The same reasoning covers
`lift` (1 author, 24 commits) and `olmocr` (88 % one author, 5.2 months quiet) on the critical path:
a 96 %-single-author repo is prior art, not a dependency.

**Lockfile entry** (`omniweave.lock`, `[[drivers]]`), taking the digest's §19.3 lesson verbatim:

```
{name, dist, version, ref <40-hex>, bundle_sha256, manifest_sha256, wheel_sha256,
 spdx, model_licence_spdx, licence_url, contract, feature_level, retrieved_at}
```

The resolver fetches by `ref`, never a branch. The hash covers the **whole bundle**, every file the
driver can execute — open-slide's `skills-lock.json` records **no git ref** (resolution is "whatever
that repo's default branch is now") and its `computedHash` covers only `SKILL.md`, so a drifted
`scripts/` or `references/` inside a "pinned" skill is undetected. A lockfile whose failure mode is
"broken install" rather than "the pinned version" is not a lockfile. CI fails on a missing `spdx`.
Hashes are never truncated to 16 hex if they decide what to install.

**The catalog is governance, not hosting.** Drivers are ordinary wheels on PyPI. omniweave publishes
a signed, append-only `catalog.json` of `{name, dist, versions[], manifest, conformance_report_sha256,
trust, licence, state}` where `state ∈ {listed, deprecated, revoked}`. **Revocation is symmetric with
admission** — awesome-skills' "(and an existing skill removed)". A revoked driver in a lockfile is a
hard resolve failure with a *named* override, `--allow-revoked-driver=<name>`, never a bare `--force`:
"an override flag whose scope is 'skip whatever check just complained' is not an override, it is an
off switch."

**Vendored binaries inside a driver need all four**: `sha256` recorded, an equality/parity test, an
architecture assertion, and a NOTICE entry. codegraph has the best process and the worst attribution
— 27 tree-sitter WASM grammars, 66 MB, with **3 grammar LICENSE files** — and hyperframes validates
a downloaded binary's architecture before zipping but records no hash. Combining them is the bar.
Unlimited-OCR is the floor: a **12 450 224-byte unsigned prebuilt sglang wheel from a dev commit** as
step 1 of its official install instruction.

---

## Concrete shape

### A. `omniweave.toml` — the driver manifest

```toml
# ── omniweave_pdfium/omniweave.toml ────────────────────────────────────────────
schema        = "omniweave.driver-manifest/1"     # manifest format, not the ABI
contract      = 1                                  # ABI major the driver implements
feature_level_min = 3                              # minimum host feature level required

[[driver]]
name            = "parse.pdf.pdfium"               # ^(role)\.([a-z0-9_]+)\.([a-z0-9_]+)$
title           = "PDFium born-digital PDF parser"
role            = "parse"
driver_version  = "1.4.2"                          # semver of the impl
schema_version  = 3                                # bump ⇒ output shape/semantics changed
                                                   #        ⇒ cache invalidation
granularity     = "part"                           # document | part | corpus
target          = "omniweave_pdfium.driver:PdfiumParser"   # imported ONLY by activate()

  # ── selection evidence: media types in, artifact kinds out ──────────────────
  accepts_media   = ["application/pdf"]
  accepts_kinds   = ["raw_bytes"]
  produces_kinds  = ["doc_blocks", "page_text_map"]

  # ── determinism ─────────────────────────────────────────────────────────────
  [driver.determinism]
  deterministic = true
  seedable      = false
  replay        = "byte"                           # none | byte | semantic

  # ── cost: a declared BOUND, measured by the conformance kit ──────────────────
  [driver.cost]
  class            = "free"                        # free|local_cpu|local_gpu|billed_api
  unit             = "page"
  p50_ms_per_unit  = 4
  p95_ms_per_unit  = 22
  micros_per_unit  = 0
  max_retries      = 0                             # a driver may not retry internally;
                                                   # retry is the runtime's, charged to a budget

  # ── hardware & environment ──────────────────────────────────────────────────
  [driver.hardware]
  gpu           = "none"                           # none | optional | required
  vram_gb_min   = 0
  ram_gb_min    = 0.25
  cpu_arch      = ["x86_64", "aarch64"]
  os            = ["linux", "darwin", "windows"]
  needs_network = false                            # ⇒ RUN WITH NO EGRESS; kit enforces
  needs_binaries = []                              # e.g. ["ffmpeg", "soffice"]

  # ── isolation ───────────────────────────────────────────────────────────────
  [driver.isolation]
  requires         = "subprocess"                  # inproc|subprocess|container|wasm
  memory_mb        = 768
  progress_ms      = 15_000                        # no-PROGRESS deadline
  wall_ms_hard     = 120_000
  batch_max_units  = 32

  # ── declared input limits; effective = min(tenant, declared, HOST_MAX) ───────
  [driver.limits]
  max_input_bytes  = 134_217_728                   # 128 MiB — anydoc's per-entry cap
  max_parts        = 10_000

  # ── role-scoped capability profile (mine-parse.md §E11 vocabulary) ───────────
  [driver.capability.parse]
  spatial        = "line_bbox"   # none|page_bbox|block_bbox|line_bbox|char_bbox
  charspan       = true
  reading_order  = "char_stream" # source|char_stream|learned|model_emitted|raster
  sections       = "typed_levels"# none|markdown_only|typed_levels|outline_from_source
  tables         = "cells"       # none|flat_html|cells|cells_with_spans
  math           = "none"        # none|latex|mathml
  assets         = "bytes"       # none|refs|bytes
  notes          = "linked"      # none|inline|linked
  confidence     = "page"        # none|document|page|element
  furniture      = "separated"   # destroyed|flagged|separated
  round_trip     = "structure"   # none|text|structure

  # ── licence: CODE ───────────────────────────────────────────────────────────
  [driver.licence]
  spdx                 = "Apache-2.0"
  tier                 = "permissive"
  licence_url          = "https://…/LICENSE"
  notice_required      = true
  notice_path          = "NOTICE"
  output_encumbered    = false
  redistribution       = "allowed"                 # allowed|internal_only|forbidden
  territory_excluded   = []
  field_of_use_excluded = []

  # ── licence: WEIGHTS (omit entirely when the driver ships no weights) ────────
  # [driver.model_licence]
  # spdx                 = "LicenseRef-AIPubs-OpenRAIL-M"
  # tier                 = "field_restricted"
  # output_encumbered    = true                    # ← the field that catches clause 8
  # clause_refs          = ["Attachment A 2(c)", "8", "9"]
  # weights_revision     = "a1b2c3d4…"             # exact SHA; "main" is a lint error
  # weights_sha256       = { "model.safetensors" = "9f8e…" }

  # ── benchmarks: every entry MUST carry measured_on ───────────────────────────
  [[driver.benchmark]]
  suite   = "omniweave-golden"
  version = "2026.09"
  metric  = "order_accuracy"
  value   = 0.75
  measured_on = { weights = "n/a", runtime = "pdfium",
                  runtime_version = "6721", sampling = "n/a", prompt_version = "n/a" }

  # ── static config: JSON Schema, so config_digest is computable WITHOUT import ─
  [driver.config]
  schema = """
  { "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": false,
    "properties": {
      "lowres_dpi":  {"type":"integer","minimum":36,"maximum":600,"default":96},
      "highres_dpi": {"type":"integer","minimum":36,"maximum":600,"default":192},
      "keep_furniture": {"type":"boolean","default":true}
    } }
  """
```

### B. Core types

```python
# omniweave/core/driver.py
Scalar = str | int | float | bool | None

class Role(StrEnum):
    ACQUIRE="acquire"; DETECT="detect"; PARSE="parse"; EXTRACT="extract"
    CHUNK="chunk"; EMBED="embed"; STRUCTURE="structure"; GENERATE="generate"
    ENGINE="engine"; STORE="store"

SCHEDULABLE_ROLES = frozenset(Role) - {Role.ENGINE, Role.STORE}

class CostClass(StrEnum):
    FREE="free"; LOCAL_CPU="local_cpu"; LOCAL_GPU="local_gpu"; BILLED_API="billed_api"

class Isolation(StrEnum):
    INPROC="inproc"; SUBPROCESS="subprocess"; CONTAINER="container"; WASM="wasm"

class Trust(StrEnum):
    FIRST_PARTY="first_party"; VENDORED="vendored"; SIGNED="signed"
    PINNED="pinned"; UNPINNED="unpinned"; UNTRUSTED="untrusted"

@dataclass(frozen=True, slots=True)
class DriverId:
    name: str                  # parse.pdf.pdfium
    dist: str                  # omniweave-pdfium
    def __str__(self) -> str: return f"{self.name}@{self.dist}"

@dataclass(frozen=True, slots=True)
class DriverManifest:
    """Parsed, validated, IMMUTABLE. Constructed WITHOUT importing `target`."""
    id: DriverId
    contract: int
    feature_level_min: int
    role: Role
    driver_version: str
    schema_version: int
    granularity: Granularity
    target: str                              # dotted path; imported only by activate()
    accepts_media: frozenset[str]
    accepts_kinds: frozenset[str]            # closed vocabulary, core-owned
    produces_kinds: frozenset[str]
    determinism: Determinism
    cost: CostDecl
    hardware: HardwareDecl
    isolation: IsolationDecl
    limits: LimitsDecl
    capability: Mapping[str, Mapping[str, Scalar]]   # role-scoped, schema-validated
    licence: LicenceDecl
    model_licence: LicenceDecl | None
    benchmarks: tuple[Benchmark, ...]
    config_schema: Mapping[str, Any]         # JSON Schema draft 2020-12
    # computed by the loader, never self-reported:
    manifest_sha256: str
    source: ManifestSource                   # PROJECT | USER | DISTRIBUTION
    trust: Trust

@dataclass(frozen=True, slots=True)
class LicenceDecl:
    spdx: str
    tier: LicenceTier
    licence_url: str
    notice_required: bool = False
    notice_path: str | None = None
    output_encumbered: bool = False
    redistribution: Redistribution = Redistribution.ALLOWED
    territory_excluded: tuple[str, ...] = ()
    field_of_use_excluded: tuple[str, ...] = ()
    clause_refs: tuple[str, ...] = ()
    weights_revision: str | None = None      # "main" ⇒ MANIFEST_INVALID
```

### C. Resolution — the pure function, and its typed rejections

```python
@dataclass(frozen=True, slots=True)
class Demand:
    role: Role
    media_type: str | None = None
    input_kind: str | None = None
    required_kinds: frozenset[str] = frozenset()          # must be in produces_kinds
    required_capability: Mapping[str, Scalar] = MappingProxyType({})
                        # e.g. {"parse.charspan": True, "parse.tables": "cells_with_spans"}
    pinned: DriverId | None = None

class RejectReason(StrEnum):
    MANIFEST_INVALID           = "manifest_invalid"
    MANIFEST_NOT_A_PATH        = "manifest_not_a_path"
    NAME_COLLISION_UNQUALIFIED = "name_collision_unqualified"
    CONTRACT_UNSUPPORTED       = "contract_unsupported"
    FEATURE_LEVEL_TOO_HIGH     = "feature_level_too_high"
    DEPRECATED_FIELD_REMOVED   = "deprecated_field_removed"
    ROLE_MISMATCH              = "role_mismatch"
    MEDIA_TYPE_UNSUPPORTED     = "media_type_unsupported"
    ARTIFACT_KIND_UNSUPPORTED  = "artifact_kind_unsupported"
    CAPABILITY_INSUFFICIENT    = "capability_insufficient"
    LICENCE_TIER_NOT_ENABLED   = "licence_tier_not_enabled"
    LICENCE_TERRITORY_EXCLUDED = "licence_territory_excluded"
    LICENCE_FIELD_EXCLUDED     = "licence_field_excluded"
    OUTPUT_ENCUMBERED_REFUSED  = "output_encumbered_refused"
    REDISTRIBUTION_FORBIDDEN   = "redistribution_forbidden"
    COST_CLASS_NOT_PERMITTED   = "cost_class_not_permitted"
    HARDWARE_ABSENT            = "hardware_absent"
    BINARY_ABSENT              = "binary_absent"
    ISOLATION_NOT_PERMITTED    = "isolation_not_permitted"
    TRUST_TIER_INSUFFICIENT    = "trust_tier_insufficient"
    LIMIT_EXCEEDS_HOST_MAX     = "limit_exceeds_host_max"
    CATALOG_REVOKED            = "catalog_revoked"
    NOT_IN_LOCKFILE            = "not_in_lockfile"
    PROBE_FAILED               = "probe_failed"          # set by activate(), not resolve()

@dataclass(frozen=True, slots=True)
class Candidate:
    manifest: DriverManifest
    effective_config: Mapping[str, Scalar]
    config_digest: str
    effective_isolation: Isolation
    effective_limits: LimitsDecl        # min(tenant, declared, HOST_MAX)

@dataclass(frozen=True, slots=True)
class Resolution:
    demand: Demand
    candidates: tuple[Candidate, ...]                       # unordered; D4's router ranks
    rejected: tuple[tuple[DriverId, RejectReason, str], ...]  # REQUIRED output
    resolution_digest: str      # sha256 of canonical JSON of (demand, catalog digest, policy)

def resolve(demand: Demand, catalog: Catalog, policy: Policy) -> Resolution: ...
    # PURE. No imports. No network. No clock. Deterministic and replayable.
```

### D. The wire protocol (contract 1)

```
Frame  ::= u32 length_le | u8 kind | payload
payload ::= MessagePack, canonical, no ext types, no bin field > INLINE_MAX (262144)
Transport ::= AF_UNIX SOCK_STREAM at 0600  |  Windows named pipe, owner-only DACL
              (NEVER a loopback TCP port — LEANN's ZMQ REQ/REP on a dynamic
               loopback port with no auth and no CURVE is the anti-pattern)

kind  name        direction  payload
────  ──────────  ─────────  ──────────────────────────────────────────────────────
 1    HELLO       host→drv   {contract, feature_level, manifest_sha256,
                              driver_name, effective_config, roots:{source_ro, tmp},
                              blob_base, isolation_granted:{...}}
 2    HELLO_ACK   drv→host   {driver_name, driver_version, schema_version,
                              code_fingerprint, contract, feature_level_min}
                              ── mismatch vs manifest ⇒ MANIFEST_CODE_MISMATCH,
                                 before any work
 3    INVOKE      host→drv   {invoke_id, units:[{uri, part, content_digest,
                              inline?: bin, blob_ref?: sha256}], deadline_ms}
 4    RESULT      drv→host   {invoke_id, unit_index, outcome, produced:[ArtifactRef],
                              confidence, partial_reason?, failure_class?,
                              retry_after_ms?, metrics:{ran_ms, input_tokens,
                              output_tokens, cost_micros, bytes_read, peak_rss}}
                              ── ONE frame per unit; the batch is a transport detail
 5    LOG         drv→host   {level, event, fields}   ← structured only; stdout/stderr
                                                        are captured and never parsed
 6    PROGRESS    drv→host   {invoke_id, unit_index, done, total}
                              ── resets the progress_ms deadline
 7    CANCEL      host→drv   {invoke_id, generation}
 8    SHUTDOWN    host→drv   {grace_ms}
 9    FATAL       drv→host   {failure_class, detail}   ← driver's last words
```

Two deadlines: `progress_ms` (no PROGRESS frame) and `wall_ms_hard` (total). A crashed batch is
retried once at `batch=1` to localise the poison unit; the localisation cost is bounded by
`batch_max_units` extra invocations, once per poison unit.

### E. Directory tree of a third-party driver

```
omniweave-pdfium/
├── pyproject.toml                 [project.entry-points."omniweave.drivers"]
│                                  manifest = "omniweave_pdfium/omniweave.toml"
├── LICENSE
├── NOTICE                         ← required when licence.notice_required
├── CONTRACT.md                    ← which contract/feature level, and why
├── src/omniweave_pdfium/
│   ├── omniweave.toml             ← THE MANIFEST. read without import.
│   ├── driver.py                  ← `class PdfiumParser(Driver)` — imported by activate()
│   └── _probe.py                  ← smallest real operation, for activate()'s probe
├── conformance/
│   ├── conformance-report.json    ← generated; catalog requires it
│   └── fixtures/                  ← driver-specific additions to the golden corpus
└── tests/
```

### F. Policy configuration (fail-closed defaults)

```toml
# omniweave.toml (project config — distinct from a driver manifest)
[drivers]
allow_experimental_kinds = false
require_lockfile         = true          # unpinned third-party ⇒ NOT_IN_LOCKFILE
max_resident_workers     = { free = 4, local_cpu = 4, local_gpu = 1, billed_api = 8 }
worker_idle_ttl_s        = 300

[drivers.cost]
allow_classes            = ["free", "local_cpu"]      # local_gpu/billed_api are opt-in
auto_refresh_classes     = ["free"]                    # a watcher may NEVER auto-run billed work

[licence]
accept_tiers                = ["permissive"]
accept_output_encumbered    = false
accept_redistribution       = ["allowed"]
jurisdiction                = "DE"        # checked against territory_excluded
fields_of_use               = ["enterprise_documents"]  # vs field_of_use_excluded

# widening is per-driver and carries a credential, not a flag
# [[licence.accept]]
# driver = "parse.pdf.marker_code"
# spdx = "Apache-2.0"
# model_licence_spdx = "LicenseRef-AIPubs-OpenRAIL-M"
# output_encumbered = true
# acknowledged_by = "legal@example.com"
# acknowledged_at = "2026-09-01"
# acknowledgement_ref = "https://tracker/LEGAL-412"
```

### G. CLI surface

```
omniweave drivers list [--role R] [--explain]    # sources, shadows, trust, licence tier
omniweave drivers show <name>[@dist]             # the full manifest, resolved
omniweave drivers why <role> --media <mt> [...]  # replay resolve(); prints candidates + rejected
omniweave drivers probe <name>                   # run activate()'s probe, print the verdict
omniweave drivers verify <name>                  # re-run the conformance kit locally
omniweave drivers add <spec>                     # resolve → lock → install --require-hashes
omniweave drivers lock [--check]                 # write/verify omniweave.lock
omniweave conform ./omniweave.toml [--tier full] # third-party entry point
```

---

## Rationale

**Why the manifest is the hill to die on.** Four things we need are all downstream of "read the
descriptor without importing the code," and no other mechanism supplies them:

1. *The router chooses on evidence.* D4 needs cost class, hardware needs, quality profile and
   licence tier for every candidate *before* deciding. With entry-point imports, seeing a
   `local_gpu` driver's cost means importing torch — ≈2.5–3.5 GB installed with CUDA wheels, which
   is exactly why `torch` and `torchvision` are **hard base requirements** of docling: you cannot get
   its DOCX reader without a tensor library. Our core install target is 250 MB (a Lambda layer), and
   core hits it by construction because core imports no driver.
2. *Licence gating happens before execution.* This is the verified defect: `ep.load()` runs before
   docling's `allow_external_plugins` check. A licence gate that fires after the import has already
   executed is theatre. It also cannot survive an adversary — docling's gate is
   `plugin_module_name.startswith("docling.")`, which a module placed in a `docling` namespace
   package satisfies.
3. *The catalog is buildable statically.* DataFlow needs an AST scrape of its own
   `TYPE_CHECKING` blocks (`generate_import_structure_from_type_checking`) precisely because its
   registry wants to *enumerate* without importing — and mine-runtime's own note on it is the
   verdict: "Scraping your own source at runtime means a `.pyc`-only or zipped install breaks the
   catalog." A declared manifest is that same idea done honestly.
4. *`resolve()` is replayable.* A pure function over data hashes; a function over imported modules
   does not. `resolution_digest` in the run manifest turns "why did it pick that parser" from
   archaeology into `omniweave drivers why`.

**Why isolation is not deferrable.** Isolation is the one decision in this panel that cannot be
retrofitted, because retrofitting it means taking `output_root` away from every driver that already
has it, and that is a breaking contract change for every third party at once. The evidence that we
will need it is not speculative — it is 22 repos of segfaulting C parsers, missing `timeout=`
arguments, 100-GPU-minute per-document ceilings, and a measured exit-137 OOM-kill. The evidence that
in-process is survivable is: anydoc, which achieved it by being written in Rust with 12 fuzz targets
and no HTTP client, i.e. by discipline we cannot impose on third parties.

**Why the conformance kit tests honesty rather than quality.** Because a quality bar excludes
everyone, and because the thing the system actually depends on is not that a driver is good but that
its *descriptor is true*. The router degrades explicitly against a true descriptor and catastrophically
against a false one. This also gives the kit a stable definition that will not drift as models
improve: "declared `block_bbox`, returned none" is a fail in 2026 and in 2031.

**Why the encumbrance bit propagates.** Because clause 8 of the Datalab `MODEL_LICENSE` is viral on
**Output**, defined at 1(k) as the informational content produced. Without a propagating field, a
single opt-in parser silently places every customer's parsed contract under an OpenRAIL-M competitor
bar, and you could not put a customer's own parsed document under their EULA. One field on
`StepResult` and one merge rule is a very small price for a defect class that is otherwise invisible
until diligence.

---

## Tradeoffs

- **Duplication between manifest and code.** `name`, `contract`, `schema_version` exist in both. Paid
  for with a `HELLO_ACK` equality assertion (`MANIFEST_CODE_MISMATCH`) and a kit check, but it is
  genuine duplication and third-party authors will get it wrong. Mitigation: `omniweave conform`
  reports the mismatch as its first check, in under a second.
- **Subprocess overhead on cheap, fine-grained work.** ~40–120 ms to spawn a Python worker,
  ~0.1–0.3 ms per frame. For a 200-page DOCX text extraction at page granularity that is ~60 ms of
  framing against multi-second work — acceptable *only because we batch*. Unbatched it would be
  indefensible, so batching is part of the contract, not an optimisation.
- **One resident worker per `(driver, config_digest, isolation)`.** ~30–60 MB RSS for a model-free
  Python worker. `max_resident_workers` per cost class plus a 300 s idle TTL bounds it. For a GPU
  driver residency is where the design *wins* — surya's attach-or-spawn shape with N thin clients
  sharing one server is the reference, and a subprocess driver is that shape by default.
- **Closed artifact-kind and role vocabularies mean core releases gate new capability.** The `x-`
  experimental namespace softens it; it does not eliminate it. I accept the friction because the
  alternative is DataFlow's spelling-dependent DAG.
- **Windows parity is real work.** Job Objects instead of `RLIMIT_AS`, named pipes instead of UDS, no
  `fork`, no net namespaces. Budget ~2 engineer-weeks explicitly, or discover it late.
- **Two governance artifacts to keep honest** — `catalog.json` and `omniweave.lock` — plus a
  per-driver conformance CI matrix. This is recurring operational cost, and a registry with a stale
  policy doc is worse than none: open-slide's `SECURITY.md` is the unedited GitHub template with
  placeholder text intact, listing versions 4.0.x–5.1.x for a monorepo at `"version": "0.0.0"`.
  Guard it with a CI condition (`fail if SECURITY.md contains "Use this section to tell people"`) and
  generate the supported-versions table from the release process.
- **Engineering cost, honestly:** manifest + resolve + catalog + lockfile ≈ 3 500 LoC and the JSON
  Schemas; supervisor + wire protocol + per-OS limits ≈ 2 500 LoC; conformance kit + golden corpus
  ≈ 4 000 LoC plus corpus curation. Roughly **10–12 engineer-weeks for two people** to a shippable
  v1, plus the ~2 weeks of Windows work. Runtime resolve for 60 installed drivers is ~5–15 ms cold
  (60 file reads + schema validation), cached per run. Core's new dependency surface is `tomllib`
  (stdlib) plus a JSON Schema validator plus a MessagePack codec — three small pure-Python-capable
  libraries, no torch, no onnx.

---

## Failure modes

1. **The descriptor lies in a way the kit cannot catch.** The kit catches *shape* lies (declared
   `cells_with_spans`, returned none) and *cost* lies (measured p95 > 3× declared). It does **not**
   catch "declared `cells_with_spans` and returned structurally-valid garbage spans." The router's
   per-corpus quality feedback (D4) is the only real defence, and it is a lagging one. The
   descriptor is a *bound*, never a promise of excellence, and every published number must carry its
   `measured_on` tuple.
2. **Manifest/code drift beyond identity.** `HELLO_ACK` catches name/contract/schema mismatches. It
   does not catch a driver that produces an artifact kind it never declared — only the kit's
   `capability` suite on the golden corpus does, and only for behaviour the corpus exercises.
3. **Subprocess isolation is not a security boundary without OS support.** Net namespaces are Linux
   only. On macOS and Windows `needs_network = false` degrades to a process-level socket guard, which
   a determined malicious driver in the same process can bypass. I declare the degradation rather
   than claim the property; the honest answer for untrusted native code is the `container` tier, and
   it is not day one. **A `signed`-tier driver from a compromised publisher, running subprocess on
   Windows with read access to `source_root`, can exfiltrate a corpus.** That is the residual risk
   and it should be written down, not argued away.
4. **The input that breaks it: a 4 000-page PDF at page granularity through a subprocess `free`
   driver, with one poison page.** 4 000 units become ~125 batched invocations at `batch_max = 32`;
   the crashed batch retries at `batch = 1`, costing 32 extra invocations to localise. Bounded and
   fine. What is *not* fine is the interaction with mine-runtime's own open question #1 (what a unit
   is for a 4 000-page PDF): if `parse` is per-page and `structure` is per-document, a partially
   failed batch leaves a document whose parts are at different generations, and the shrink guard and
   the cost model both get harder. My contribution is only that **the batch is invisible to the
   `work` table** — the granularity mixing itself is D6's problem and I am handing it over
   unresolved.
5. **The feature-level ratchet becomes a version wall.** Casual bumps churn every third-party
   driver. Mitigation: levels are additive-only, drivers declare `feature_level_min` never `exact`,
   and a bump with no `CONTRACT.md` entry fails CI. If we bump carelessly anyway, the ecosystem
   fragments and the mitigation is social, not mechanical. That is a real weakness.
6. **The kit rots or gets skipped.** A five-minute mandatory tier is the defence; if the golden
   corpus grows and the tier stretches to twenty minutes, CI starts getting `--skip`ped and the
   descriptor's honesty guarantee quietly dies. Enforce the budget as a CI timing assertion, the way
   jcodemunch enforces a 5 % schema-token drift tolerance against a frozen baseline.
7. **Golden-corpus licensing.** The kit must ship its corpus, so it cannot vendor olmOCR-Bench or
   OmniDocBench wholesale. Using only the taxonomy on our own corpus means our numbers are not
   comparable to published ones — which is *correct* (published numbers are mostly irreproducible;
   `grep -rn "revision=" marker/ surya/ lift/` returns zero hits) but will read as evasion to a
   reviewer who wants a leaderboard row.
8. **Name-collision qualification changes the cache key.** `parse.pdf.foo` vs
   `parse.pdf.foo@vendor-b` are different `config_digest` inputs, so switching qualification
   re-derives everything that driver produced. Correct, and expensive to discover at the wrong
   moment. `omniweave drivers lock --check` should warn when a qualification change is pending.
9. **A `store`-role driver is a different animal and I have under-designed it.** A store cannot be
   subprocess-isolated without paying IPC on every row, so `store` drivers are effectively
   `first_party` or `vendored` only. I am stating that as a restriction rather than pretending the
   uniform contract covers it; D5 should ratify or overturn it.

---

## Why I reject the alternatives

**Entry points that resolve to callables (docling, markitdown, DataFlow).** The dominant convention,
and verified broken for our purposes. pluggy's `load_setuptools_entrypoints` does `ep.load()` then
`register()` inside its loop over distributions; docling's `allow_external_plugins` test is in the
*next* loop (`base_factory.py:88-115`), so the gate suppresses registration after execution.
markitdown's `_load_plugins()` calls `entry_point.load()` unconditionally
(`_markitdown.py:63-81`) — which is precisely how `markitdown-ocr` self-registers and puts mandatory
AGPL PyMuPDF into a process advertising MIT. Consequences, all fatal here: no licence gate before
execution, no cost evidence without paying the import, no catalog without paying every import, and
import-order-dependent registration.

**Options-type dispatch (docling's factories).** I take the *principle* — "adding an engine = adding
an options class; nothing else has to know" is the right decomposition, and `get_enum()` building CLI
choices from registrations is genuinely good. I reject the *mechanism*: dispatch on `type(options)`
requires importing the options class, so the router cannot price what it has not loaded, and CLI
`--help` cannot enumerate what is not installed-and-imported. A JSON Schema in the manifest gets
validation, help text, CLI enums and `config_digest` for free, with no imports.

**Bare-`__name__` flat registry (DataFlow) / silent-overwrite factory (graphrag).** Two silent
failure modes, quotable. DataFlow's `_do_register` is `if name not in self._obj_map` — first
registration wins, keyed on a bare `__name__`, no namespace, no version, no distribution id, no
warning; two packages shipping `PdfChunker` and the second vanishes. Its `get()` is a linear scan
over `LazyLoader` modules that `continue`s on `AttributeError`, so "this operator failed to import"
is indistinguishable from "this operator does not exist." graphrag's
`PipelineFactory.register` has the mirror bug: `cls.workflows[name] = workflow` silently overwrites.
Both wrong, both silent, both fixed by "a collision is a resolve error qualified only by `@dist`."

**AST-scraping your own `TYPE_CHECKING` blocks for the catalog (DataFlow).** The `TYPE_CHECKING`
lazy-import trick itself is worth keeping for the *public namespace* (one declaration serves mypy and
the runtime loader; importing `core_vision` does not drag in torch). Scraping it at runtime to build
the catalog is not: it breaks on a `.pyc`-only or zipped install, and it makes the catalog depend on
source layout. The manifest is the same idea with the data written down instead of recovered.

**Flag-gated model groups (omniparse).** The idea is right and I am implementing it as
`policy.allow_classes` + `resolve()`. The implementation is a catalogue of what not to do:
`app.include_router` runs unconditionally at module scope (`server.py:33-37`) while
`load_omnimodel(args.documents, args.media, args.web)` runs later inside `main()` (`:52-78`), so the
flags gate model loading and OpenAPI visibility but not route registration. A `--documents`-only
deployment serves `POST /parse_media/audio` into a `None` whisper model and returns a 500 with a
`NoneType` message instead of a 404 naming the flag. Every route is registered twice. (Separately,
omniparse is GPL-3.0 with a `pyproject.toml` claiming Apache and is 21.9 months dead — design
reference only, not a line vendored.)

**Provider/Builder/Processor/Renderer as *the* extension taxonomy (marker).** I take
`resolve_dependencies` (`marker/converters/__init__.py:24-41`) almost verbatim for **in-tree**
wiring: 18 lines, no framework, no decorators, matching `__init__` parameter names against an
`artifact_dict`. I reject it as the *extension* mechanism for two reasons. It is a per-repo taxonomy
of four fixed unit types, not a role vocabulary a third party can extend. And it is an RCE channel:
`--converter_cls`, `--processors` and `--llm_service` import arbitrary dotted paths and are settable
from `--config_json`, so the moment config comes from a request body, config *is* code. An extension
mechanism whose selector is "import this dotted path" cannot be exposed on a server, and omniweave
is a served framework. In my design the dotted `target` exists but is reachable only from a manifest
that resolve() has already licence-gated, trust-gated and lockfile-gated — never from a request.

**In-process everything, "just be careful."** Rejected on the numbers, and rejected because it is the
irreversible choice. Once drivers hold `output_root`, taking it back breaks every third party
simultaneously. And the failure it invites is the worst one available: codegraph's measured lesson is
that a SIGKILL arriving right after the work was done discards completed work, and an in-process
segfault on page 3 700 of 4 000 does exactly that.

**A WASM-only driver ABI.** Genuinely tempting: anydoc's `wasm32-unknown-unknown` target is a privacy
architecture (the document never leaves the browser) and a parser that must compile to WASM cannot
grow a network call by accident. Rejected as the *universal* mechanism, because the drivers that most
need sandboxing — VLM inference, headless browser render, ffmpeg — are exactly the ones WASM cannot
host. Kept as a first-class **isolation profile** (`isolation.requires = "wasm"`) for pure-function
parsers, where it is the strongest sandbox available and unlocks the browser/edge deployment for
free. The manifest is agnostic to which profile a driver asks for, which is the whole point of making
isolation a declared field.

**A custom package index or plugin marketplace.** Rejected: it duplicates PyPI's job, adds an
availability dependency on us, and buys nothing that a signed catalog over ordinary wheels does not
already buy. Governance is admission, revocation and a conformance requirement — none of which needs
us to host artifacts.

---

## For the downstream panels

- **D4 (router)** consumes `Resolution.candidates` and the `cost`/`capability`/`benchmark` blocks. It
  does not consume manifests directly and it never imports a driver. `Resolution` is hashable, so a
  routing decision is replayable given `(resolution_digest, policy_digest)`.
- **D5 (storage)** owns the artifact-kind vocabulary's *contents*; this panel owns the rule that it
  is closed and core-owned. The `store` role's isolation exemption (failure mode 9) needs D5's
  ratification.
- **D6 (runtime)** inherits `Driver` in place of `OperatorABC` and `ctx.acquire(role, name)` in place
  of `ctx.driver(kind)`; everything else in `mine-runtime.md` §7 stands. The batch/unit seam
  (failure mode 4) is handed over unresolved.
- **D8 (OUT)** gets `role = "generate"`, `capability.generate.*`, and the `encumbrance` stamp that
  lets an export refuse to emit an artifact derived from output-encumbered weights.
- **D9 (serve)** gets the rule that no `x-` experimental artifact kind may appear in a pipeline
  reachable from a serve surface, and the `licence_notices[]` field on the response envelope.
- **D10 (quality)** owns the golden corpus; this panel owns the conformance kit that runs against it
  and the five-minute budget on its mandatory tier.

## Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| **D3-1** | Reading a manifest never imports driver code. | `resolve()` has no import site; a CI test resolves a fixture catalog with an import hook that fails on any `omniweave_*` driver module |
| **D3-2** | An entry-point value is a path, never `module:attr`. | Loader rejects any value containing `:` → `MANIFEST_NOT_A_PATH` |
| **D3-3** | A duplicate driver `name` is an error, never a silent win or overwrite. | `Catalog.add` raises `NameCollision`; resolution requires `@dist` qualification; unit test with two fixture dists |
| **D3-4** | `resolve()` is pure and deterministic. | No `ctx`, no clock, no network in its signature; a property test asserts equal `resolution_digest` across 100 runs and across process restarts |
| **D3-5** | Every resolution returns its rejection list. | `Resolution.rejected` is a required field; a zero-candidate `Resolution` is not an exception |
| **D3-6** | No driver outside `{first_party, vendored} × free × no-GPU × no-network` runs in-process. | `resolve()` computes `effective_isolation`; `Isolation.INPROC` unreachable otherwise; no config key can widen it |
| **D3-7** | A driver never receives a writable `output_root` or `cache_root`. | `HELLO` carries only `{source_ro, tmp, blob_base}`; the supervisor writes all artifacts; a sandbox test asserts a write outside `tmp` fails |
| **D3-8** | A driver declaring `needs_network = false` performs no egress. | Net namespace where available, process guard otherwise, degradation recorded; conformance `sandbox` suite fails a connect attempt |
| **D3-9** | An isolation property that was not obtained is recorded as a degradation. | `HELLO.isolation_granted` is echoed into the run manifest's `degradations[]`; a test on a platform lacking namespaces asserts the record appears |
| **D3-10** | No driver outside `accept_tiers` activates without a per-driver credentialed acknowledgement. | `resolve()` gate; `[[licence.accept]]` schema requires `acknowledged_by`/`_at`/`_ref`; CI lint fails a widening with a missing field |
| **D3-11** | `output_encumbered` propagates to every derived artifact. | `StepResult.encumbrance` merged by the runner into the L2 document and every downstream artifact; a test parses with an encumbered fixture driver and asserts the stamp survives parse → chunk → generate |
| **D3-12** | A benchmark claim carries its `measured_on` tuple. | Manifest schema `required`; conformance `manifest` suite |
| **D3-13** | A driver's declared limits never exceed the host maximum. | `effective_limits = min(tenant, declared, HOST_MAX)` computed in `resolve()`; `LIMIT_EXCEEDS_HOST_MAX` on a declaration above `HOST_MAX` |
| **D3-14** | An unpinned third-party driver does not activate. | `require_lockfile = true` default; `NOT_IN_LOCKFILE`; CI fails a lockfile entry missing `spdx` or `bundle_sha256` |
| **D3-15** | A revoked driver does not activate without a named override. | Catalog `state = revoked` → `CATALOG_REVOKED`; only `--allow-revoked-driver=<name>` lifts it; there is no `--force` |
| **D3-16** | Conformance is verified from a trusted ref, never from the submission. | CI checks out the kit from a tag; `omniweave drivers verify` re-runs locally; a catalog report alone is never sufficient |

---

## Build order

1. **Manifest schema + loader + `Catalog` + `omniweave drivers list --explain`.** No selection yet.
   Proves D3-1/2/3 with a CI import-hook test. ~1.5 weeks.
2. **`resolve()` + `RejectReason` + `Policy` + `omniweave drivers why`.** Pure, fully unit-testable
   with fixture manifests and no real drivers. D3-4/5/13. ~1.5 weeks.
3. **The licence gate + the encumbrance stamp.** Before any driver exists, so the propagation rule is
   in `StepResult` from day one. D3-10/11/12. ~1 week.
4. **Wire protocol + `DriverSupervisor` + `DriverHost` + per-OS limits.** Two fixture drivers: one
   that crashes, one that hangs. D3-6/7/8/9. ~3 weeks including Windows.
5. **`activate()` + capability probe + the resident-worker pool.** ~1 week.
6. **The conformance kit, `manifest` and `capability` and `purity` suites first.** Then `limits`,
   `sandbox`, `cost`, `injection`, `fuzz`. D3-16. ~3 weeks plus corpus curation.
7. **Lockfile + catalog + `drivers add`.** D3-14/15. ~1.5 weeks.
8. **`container` and `wasm` isolation profiles.** Only when a real driver demands one; the protocol
   already accommodates both.

Steps 1–3 are ~4 weeks and produce a working, testable selection layer before a single real driver is
written. That ordering is deliberate: the descriptor's shape is the irreversible decision, and it
should be settled against fixtures while it is still cheap to change.
