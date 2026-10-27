# D3 — The driver system — THE SHIPPING PRAGMATIST

## Headline

**Every replaceable part in omniweave is a `Driver`, and a Driver is a TOML file plus an
implementation.** The file — `driver.toml`, the `DriverCard` — is discovered and read *without
importing a single line of the driver's code*, carries measured cost, declared fidelity, hardware
needs and a machine-readable licence tier, and is simultaneously the router's evidence and the
conformance kit's test plan. There are exactly **four contracts** (`acquire/1`, `parse/1`,
`derive/1`, `compile/1`), **one registry**, and **two isolation levels that ship** (`inproc`,
`subproc`) where `subproc` doubles as the polyglot mechanism so it is not an extra cost. Phase 1 is
six weeks and produces something a user runs: `omniweave drivers explain application/pdf` printing
the real ladder, and four real drivers behind it.

---

## Design

### 1. One concept, not six. `Driver` and `Service`.

The question lists parsers, extractors, chunkers, embedders, generators, connectors. Six words. I
ship **two**:

- **`Driver`** — does work on a unit. Declared in a card. Discovered without import. Selected by the
  router on card evidence. Versioned on three independent axes. Conformance-tested. Distributed by
  third parties. *A parser is a Driver. A chunker is a Driver. A PPTX compiler is a Driver.*
- **`Service`** — a shared expensive resource a Driver asks for **by name**, with a different
  lifecycle (attach-or-spawn, health-checked, N clients share one GPU) and no unit and no
  `StepResult`. surya's `SuryaInferenceManager` (`surya/inference/__init__.py:86-107`) is the
  reference shape and mining notes A3.3/A3.4 are the implementation. *An embedding model is a
  Service. A vLLM endpoint is a Service.*

That distinction is load-bearing, not cosmetic: the router chooses Drivers, never Services, so a
Service never needs a fidelity ladder or a cost class, and a Driver never needs a spawn protocol.
`mine-runtime.md` §7.1.3's `ctx.driver(kind)` should therefore be renamed `ctx.service(name)` — same
mechanism, correct word — and the runtime's `OperatorABC` **is** a `Driver` with `contract` fixed.
Two registries for "the pipeline step" and "the parser plugin" is exactly the abstraction-with-one-
implementation this panel should kill on sight.

**Embedders are Services, not Drivers**, and I will defend that against D5: an embedder's unit is a
batch of strings, its cost is contended GPU seconds, and its config change re-embeds the corpus
(graphrag `update_*` re-embeds everything, §2.7). It has none of a Driver's properties. What *is* a
Driver is the `derive/1` step that decides what text to embed.

### 2. The card is read without importing. This is the whole design.

Discovery, in order, and each step is cheap:

1. **Entry-point scan, value-only.** A driver distribution declares
   `[project.entry-points."omniweave.driver-cards"] <name> = "<relative/dir>"`. We enumerate with
   `importlib.metadata`, read **`EntryPoint.value` as a plain string**, and resolve
   `dist.locate_file(value)/driver.toml`. **`EntryPoint.load()` is never called anywhere in
   `omniweave/core/driver/`** — enforced by a grep-level CI rule and by an import-tracer test.
2. **`OMNIWEAVE_DRIVER_PATH`** — `os.pathsep`-separated directories scanned for `*/driver.toml`.
   This is how a Rust, Go or Node driver ships (no Python packaging involved) and how you dev-load a
   driver without installing it.
3. **First-party tombstones** — cards the framework ships itself for drivers that are *forbidden*,
   so a forbidden id resolves to a reason instead of "unknown driver" (§7 below).
4. **Card cache** — a store table keyed on `(dist_name, dist_version, card_path, mtime_ns, size)`,
   so warm discovery is one indexed `SELECT`, cold is one small file read per driver.

**Why this matters, with evidence.** docling's plugin system does the opposite and its opt-in flag
does not do what its name says:

- `docling/docling/models/factories/base_factory.py:96` calls
  `plugin_manager.load_setuptools_entrypoints(plugin_name)`.
- pluggy 1.6.0's implementation of that method iterates
  `importlib.metadata.distributions()` and calls **`plugin = ep.load()`** for every entry point in
  the group — an import — then `self.register(plugin, name=ep.name)`.
- The `allow_external_plugins` check is at `base_factory.py:100-107`, in the loop **after**, over
  `plugin_manager.list_name_plugin()`, and only `continue`s past registration.

So `allow_external_plugins=False` is a **registration gate, not an execution gate**: a third-party
wheel that declares a `docling` entry point has already executed its module top-level code by the
time docling decides not to trust it. And it happens four times (`get_ocr_factory`,
`get_picture_description_factory`, `get_layout_factory`, and its sibling at
`factories/__init__.py:15,24,33,42`), each doing a full distribution scan. That is both a security
hole and a cold-start bill.

markitdown is more honest — `enable_plugins()` is a real opt-in
(`markitdown/packages/markitdown/src/markitdown/_markitdown.py:75,137,232`) — but once enabled it
has the same shape, and `register_converter` inserting at the front so "later registrations at equal
priority win" means **install order decides behaviour**.

omniparse's flag-gated model groups gate nothing that costs anything: `omniparse/server.py:6` imports
`omniparse`, whose `omniparse/omniparse/__init__.py:20-27` does `import torch`, `import whisper`,
`from marker.models import load_all_models` **at module scope**, before `argparse` runs in `main()`.
`--media` gates only `whisper.load_model("small")` at `:60`. All four routers are registered
unconditionally at `server.py:33-38`; the flags only set `include_in_schema`. A capability flag that
is not a *discovery* mechanism is decoration.

### 3. Selection is a pure function that returns the whole ladder

```
resolve(want: Requirement, cards: frozenset[DriverCard], policy: Policy) -> Resolution
```

Pure, no IO, deterministically replayable, and the `Resolution` (with card digests) goes in the run
manifest. Rules, in this order:

1. **Contract major must match exactly.** A `parse/2` driver cannot serve a `parse/1` host. No
   duck-typing, no "try it and see".
2. **Hard filters**: format ∈ `capability.formats`; every requested fidelity field satisfied at or
   above the requested rung; `licence.tier ∈ policy.tiers`; `hardware.needs ⊆ probed capabilities`;
   `cost.cost_class ≤ want.max_cost_class`; `quality.attested` unless `policy.allow_unattested`.
3. **Rank** on `(policy.pin_rank, −fidelity_score, cost_class, usd_per_unit, p50_ms)`.
4. **Return the ladder and every rejection with a named reason.** This is DataFlow's
   `apply_whitelist` report shape (`dataflow/utils/registry.py`, notes §1.2.2) generalised: what you
   asked for, what was missing, what survived, what went, and why. A misspelled driver id or a
   licence-blocked driver surfaces as a reason, never as silence.
5. **Memoise** on `(contract, format, fidelity_request, policy_digest, cards_digest)`. Per-part
   resolution on a 4,000-page PDF is 4,000 calls; unmemoised it dominates.

The fidelity vocabularies from `mine-parse.md` E11 are adopted **verbatim and as ordered ladders**,
which is what makes "satisfied at or above" meaningful:

```
spatial       none < page_bbox < block_bbox < line_bbox < char_bbox
reading_order raster < learned < model_emitted < char_stream < source
sections      none < markdown_only < outline_from_source < typed_levels
tables        none < flat_html < cells < cells_with_spans
math          none < latex < mathml            (unordered in truth; ranked by round-trip value)
assets        none < refs < bytes
notes         none < inline < linked
confidence    none < document < page < element
furniture     destroyed < flagged < separated
round_trip    none < text < structure
```

Pin beats rank; **licence and hardware beat pin**, because a pin is a human preference and a licence
bar is a legal fact. `omniweave show-config` prints the effective policy (invariant I16).

### 4. Three version axes, because conflating them costs money

| axis | shape | changes when | who cares |
|---|---|---|---|
| `driver.contract` | `"parse/1"` — name + **major only** | the host↔driver protocol changes non-additively | the loader: refuses a major it doesn't implement |
| `driver.version` | semver | any release | humans, `drivers list`, the lockfile |
| `driver.schema_version` | `int` | the **output shape or semantics** change | **the cache key** |

`schema_version` — not `driver.version` — enters `OperatorIdentity` and therefore the cache key
(`mine-runtime.md` §7.1). That is deliberate: a bug-fix release that does not change output must not
invalidate a BILLED_API cache, and a "no behaviour change" release that *does* change output must.
This is also my answer to mine-runtime's open question #4: **`code_fingerprint` covers the driver
module's own source; native/model dependency changes are declared by bumping `schema_version`, and
the card carries `[deps] pins` whose digest enters the key only for `cost_class = free` drivers**,
where a spurious full re-derive is affordable and a stale answer is not.

Deprecation is cheap and loud: `[deprecated] since / replaced_by / reason` — the resolver still
selects it and emits one `degradation` record into the response envelope (invariant I18). Never a
silent substitute. Removal is a **tombstone card** the framework ships.

### 5. Four contracts. Not seven.

```
acquire/1   AcquireRequest              -> Iterator[UnitRef]  (+ bytes into the blob store)
parse/1     bytes + PartSelector        -> DocModel fragment
derive/1    DocModel                    -> items (blocks, chunks, entities, edges)
compile/1   IL + Assets                 -> artifact bytes + report   (+ optional parse_back id)
```

Chunkers and extractors are the same contract (`derive/1`: docmodel → items). OCR, VLM and
schema-constrained extraction are all `parse/1` — they differ in cost and fidelity, which is what the
card is for, not in shape. `compile/1`'s round-trip is not a fifth contract: the card names a
`parse/1` driver id in `capability.parse_back`, which is how the blueprint's loop closes without a
new abstraction.

If a fifth contract is genuinely needed, adding one is adding a name plus a conformance suite;
nothing in discovery, resolution, versioning, isolation or distribution changes. That is the test of
whether the factoring is right, and it is why I refuse to ship contracts speculatively.

### 6. Isolation: two levels that ship, one in the vocabulary

`isolation` is declared **in the card**; the host may only tighten it, never loosen.

- **`inproc`** — default only for `licence.tier = "open"` **and** `cost_class = "free"` **and**
  `hardware.needs = []` **and** `imports_torch = false`. Wrapped in a `DriverGuard`:
  `faulthandler.enable()`, a wall-clock watchdog at `WATCHDOG_MS/2` (invariant I15),
  `resource.setrlimit(RLIMIT_AS)` where the platform has it, and **anydoc's fixed limits enforced by
  the host at the read boundary, not by the driver** (`anydoc/src/limits.rs`: 128 MiB/entry,
  512 MiB/archive, 100k entries, XML depth 256, 2M nodes, 4M grid slots, 64 MiB duplicated text —
  adopted verbatim as the maximum, with the effective value `min(tenant_cap, MAX_*)`).
  **Honest statement: a segfault here kills the process.** We accept that for a driver we fuzz.
- **`subproc`** — default for **everything third-party** and for anything with `hardware.needs`,
  `imports_torch = true`, or `tier != "open"`. One long-lived child per driver id, reused across
  units, line-delimited JSON over stdin/stdout, **blobs by content-addressed URI, never inline**
  (DataFlow's "paths, not payloads", §1.8, is right for binary). A crash is
  `FAILED_TRANSIENT{WORKER_DIED}` on one unit; batch size halves on retry; the pool restarts.
  **This is also the polyglot mechanism** — a Rust or Node driver speaks the same protocol — which
  is the whole argument that `subproc` is not an extra cost. One mechanism, two payoffs.
- **`wasm`** — in the card vocabulary, phase 4. `anydoc/wasm/` already targets `wasm32`, so the tier
  gets one real driver the day we want it. Not on the critical path and I will not build it early.

Promotion from `subproc` to `inproc` requires the driver id to appear in the project's
`omniweave.toml` under `[drivers.trust] inproc = [...]` — a reviewable act, not a card claim.

**Why not everything out-of-process:** anydoc parses a DOCX in the ~12 ms class. A process spawn plus
an IPC round trip is a ~2 ms tax on the hottest path in the framework — a ~17% regression on the
cheapest, most-frequently-hit route — and the whole reason tier-0 formats are worth having is that
they are free. Uniform sandboxing sacrifices the one route where the framework beats every
alternative on cost.

### 7. Licence tiering, and the part that makes it not theatre

Four tiers; `restrictions` is a **closed vocabulary** because free-text licence prose is unroutable:

```
no_compete · output_share_alike · territory_excluded · field_of_use_barred · revenue_gate
mau_gate · no_redistribution · no_model_training · attribution_per_output
remote_kill_switch · copyleft_network · copyleft_strong
```

| tier | behaviour |
|---|---|
| `open` | selectable by default |
| `restricted` | **never selected** unless the driver id is named in `omniweave.toml`; `licence_notice` in every response envelope citing its output |
| `commercial` | as `restricted`, plus a preflight probe that the licence/key is actually present |
| `vetoed` | a **tombstone card we ship**; resolution fails with the clause quoted |

**`licence.code` and `licence.weights` are separate fields.** They exist as two fields *because* of
one specific case: marker/surya/lift ship Apache-2.0 **code** and an OpenRAIL-M **`MODEL_LICENSE`**
(byte-identical, md5 `e1f69b64dee2f1641a9b1ab12adf24d6`) whose Attachment A clause 2(c) bars use by
anyone offering a competing product with no revenue threshold and no research carve-out, and whose
clause 8 licenses the **Output**. A single `licence` field cannot express "run this code against
other weights, never these weights", and that is precisely the distinction the framework must be able
to make. Day-one tombstones, all on **weights**: `parse.pdf.marker`, `parse.ocr.surya`,
`extract.schema.lift` (`no_compete, output_share_alike, attribution_per_output,
remote_kill_switch`), `parse.ocr.hunyuan` (`territory_excluded, field_of_use_barred, mau_gate,
no_model_training`), `parse.any.omniparse` (`copyleft_strong`).

★ **The non-obvious half, and the reason tiering is enforceable rather than advisory: restrictions
travel on the produced items.** Every block, chunk and edge carries `licence_bits INTEGER NOT NULL
DEFAULT 0` — a bitmask over the twelve restriction codes — set by the *runner* from the producing
card, alongside `origin_operator` / `confidence` / `partial` (`mine-runtime.md` §7.1.2). Then:

- `SELECT 1 FROM block WHERE licence_bits & 2 /* output_share_alike */ AND doc_id = ?` answers
  "may I ship this deck" in one indexed query.
- The `compile/1` host **refuses** to emit an artefact containing `output_share_alike` items unless
  the target policy allows it, naming the offending block ids — the OUT direction's version of
  ppt-master's blocking validator.
- A licence audit or a takedown request is a query, not an archaeology project.

Cost: one smallint column and 12 named constants. Without it, a `restricted` driver's output silently
infects the index and the tier system is a label on a box nobody checks.

### 8. The conformance kit — the descriptor *is* the test plan

`omniweave-conform` is a separate distribution so a third party does not install our dev stack.
`omniweave conform ./my-driver` runs, in order:

1. **Card validation** — against a JSON Schema, **fail-closed on unknown keys.** (`extra="allow"` is
   right for driver *config*, per graphrag's `CacheConfig` shape; it is wrong for the card, which is
   a contract.)
2. **Purity** — discovers the card under an import tracer; **fails if any module from the driver's
   distribution was imported during discovery.** This is the docling defect, tested for.
3. **Contract suite** — golden fixtures: one file per claimed format plus six adversarial
   (encrypted PDF, zip bomb, 100k-entry zip, XML depth 300, 0-byte file, truncated DOCX). Asserts the
   **typed error taxonomy**, not message text: `Encrypted` must be `Encrypted`, a limit breach must
   be `ResourceLimit{limit}` naming the knob, `NeedsOcr{pages}` must name the pages. anydoc's
   `ConvertError` + stable `code()` + `is_fatal()` (`anydoc/src/error.rs`) is the model, and its
   codes are unit-tested there precisely because bindings publish them.
4. ★ **Fidelity-claim suite, derived from the card, in both directions.** `charspan = true` runs the
   charspan assertions; `charspan = false` **asserts charspans are absent**. So you cannot get credit
   for a field you half-implement, and every downstream `if card.fidelity.charspan` is trustworthy.
   This is the structural kill for DataFlow's drift problem — 171 hand-maintained `get_desc(lang)`
   strings with nothing checking them against `inspect.signature(run)`.
5. **Idempotence / no-duplicate-rows** — runs each unit twice, asserts canonicalised output equality
   and equal row counts (invariants I1/I2; codegraph #1034 shipped byte-identical duplicate rows
   because `INSERT OR IGNORE` had no UNIQUE index to conflict on).
6. **Determinism** — same input, varied `PYTHONHASHSEED`; unequal output requires
   `deterministic = false` in the card, and the runner then never caches-and-compares.
7. **Cost measurement** — min-of-5 warm runs, in-process and spawn-inclusive timings declared
   *separately* (anydoc's bench methodology). **Writes `[cost]` into the card.**
8. **Licence gate** — resolves the full transitive dependency graph **and runs an import-graph scan
   against the declared set**, failing the build on the denylist. The proof this is necessary:
   `cairosvg` (LGPL-3.0) is imported by
   `ppt-master/.../svg_to_pptx/pptx_package/media.py` and `visual_review.py` and appears in **no**
   requirements file. A manifest-only gate cannot see it. Denylist seed: **PyMuPDF, mineru,
   pypandoc-binary, ffmpeg-static, cairosvg** — and PyMuPDF is a *mandatory* dependency of
   `leann-core` (`LEANN/packages/leann-core/pyproject.toml:38`) and `markitdown-ocr`
   (`markitdown/packages/markitdown-ocr/pyproject.toml:31`), both of which advertise MIT.
9. **Emit** — an updated card with `[cost]`, `[quality]`, and an `Attestation` digest, plus
   `conformance-report.json`.

**`[cost]` and `[quality]` are not author-writable.** The kit stamps them and writes
`quality.attestation = sha256(canonical card minus attestation)`. The loader recomputes; on mismatch
`attested = false` and the router will not auto-select the driver. This is a **tamper-evidence
mechanism, not a signature** — it detects hand-editing after a run, not forgery. Forgery is a
governance problem at our scale, handled by review, and I would rather ship an honest 40-line digest
than a PKI nobody operates. Say so in the docs.

**Registry CI runs the kit from a tag we control, never the copy in the PR** — awesome-skills'
`REVIEWING.md` stage-1 rule verbatim: *"a validator supplied by the submission validates nothing."*

### 9. Distribution: no omniweave-hosted registry

Third parties publish to PyPI / crates.io / npm (whatever D1 rules). What we ship:

- **A static index.** One repo with `drivers/<id>/card-stub.toml` + a route-stub description,
  rendered to a generated `index.json` on Pages, **gated on a byte-diff in CI** (graphify's
  `tools/skillgen/ --check --bless` discipline: generated artefacts, committed, drift-checked).
  Stubs are readable **before** the driver is installed — hyperframes' `references/routes/*.md`
  pattern: contracts before bodies.
- `omniweave drivers add <id>` → resolve from the index → **print licence tier, restriction codes and
  installed size loudly, and require confirmation for any tier ≠ open** → install → verify the
  installed card digest against the index → write `omniweave.lock`.
- **`omniweave.lock`** records `{driver_id, version, contract, card_sha256, dist_sha256, source_url,
  resolved_at, licence_tier, restrictions}`. Every field is there because a real lockfile in this
  collection lacked it: open-slide's `skills-lock.json` records **no git ref** (resolution is
  "whatever that branch is now"), its `computedHash` covers only `SKILL.md`, and it has **no licence
  field**. hyperframes' `hashSkillBundle` (whole bundle, path folded in, sorted, CRLF-normalised) is
  the hashing to copy.
- **A weekly rot sweep**, non-blocking, exit code always 0, dedup by subject not by file, reporting
  "unverifiable" separately from "broken", and **re-checking licence fields** — graphify relicensed
  MIT → Apache-2.0 in 2026 with both texts shipped, so a licence read once is not a licence known.
  awesome-skills' `revalidate_catalog.py` is the template.
- **A four-stage PR gate** (awesome-skills' rubric), with stage 4 reduced to the five classes that
  matter for a driver: code built from a string at runtime; network egress not declared in
  `hardware.needs`; credential/`.env` reads; parsed content passed onward as instructions rather than
  data; undeclared subprocess execution.

### 10. Registry mechanics, and the two silent failures to close

```
Registry[T] — an INSTANCE, created per run, carried on ctx. Never a module global.
  register(id, card, factory, *, replace=False)   raises DuplicateDriver unless replace=True
  create(id, config)                              unknown id -> error ENUMERATING known ids
```

- **Never first-wins-silently** (DataFlow `dataflow/utils/registry.py:81-83`:
  `if name not in self._obj_map: self._obj_map[name] = obj`, keyed on bare `__name__`, no namespace,
  no version, no warning) and **never overwrite-silently** (graphrag's mirror bug).
- **Never a lookup that swallows `AttributeError`**: DataFlow's `get()` scans `LazyLoader` modules
  whose `__getattr__` *executes* the target module, so "failed to import" and "does not exist" are
  the same `continue`. A failed driver import is `DriverLoadFailed{id, exc}` and is reported.
- **Never module-global state**: graphify's `_stat_index` first-caller-wins, graphrag's
  `Factory.__new__` singleton, jcodemunch's `_repo_states` dict — one disease, three repos.
- **Config is never an import path.** marker's `--processors` / `--converter_cls` go through
  `strings_to_classes` (`marker/marker/util.py:15-21`: `import_module(module_name)` on a caller
  string) and are settable from `--config_json`. That is an RCE channel the moment config arrives in
  a request body. In omniweave a config value is a **registered driver id**; unknown ids error with
  the list of known ones.
- **Startup self-check**: every driver id in the shipped catalog resolves, and every card in the
  lockfile is present with a matching digest. graphrag's `validate_config_names` is the precedent —
  *"cheap, and it prevents six-hour failures"* — but **`sys.exit(1)` is banned in library code**;
  preflight raises, the CLI decides the exit code.
- **Capability probes, not import checks.** LDR's SQLCipher probe is the model: *test that the
  capability works, not that the module imports.* Every `hardware.needs` entry has a probe that runs
  the smallest real operation (a CUDA kernel launch, `ffmpeg -encoders`, opening an encrypted PDF)
  and caches the verdict for the run. A failing probe **prunes the plan and reports it**, never an
  `ImportError` at the bottom of a stack trace.

### 11. Phasing — every phase ships something a user runs

- **Phase 1 (6 weeks).** Card schema + import-free discovery + `resolve()` + `Registry` +
  `parse/1` contract + `inproc` host with `DriverGuard` + four tombstones. Four drivers: anydoc
  (tier 0), markitdown (breadth, `lossy = true`, all fidelity `none`), a pdfium+layout digital-PDF
  driver, olmocr (`subproc`, `needs = ["cuda"]`). **Deliverable a user runs today:**
  `omniweave parse` picks correctly across those four, and `omniweave drivers explain
  application/pdf` prints the ladder with reasons.
- **Phase 2 (4 weeks).** `subproc` host + protocol + `omniweave-conform` suites 1–5 + fixture corpus.
  **Deliverable:** a third party can write a driver, run the kit, and get a green report. This is the
  phase that makes the system *a plugin system* rather than a config file.
- **Phase 3 (3 weeks).** `derive/1` + `compile/1` + `licence_bits` on items + the OUT refusal +
  kit suites 6–9 + the static index and lockfile.
- **Phase 4 (opportunistic).** `wasm` tier via anydoc's existing target; `acquire/1`.

---

## Concrete shape

### `driver.toml` — the DriverCard (real example, anydoc)

```toml
schema = 1                                # card schema version; unknown keys are a HARD ERROR

[driver]
id             = "parse.doc.anydoc"       # dotted, namespaced, stable; THE registry key
version        = "0.2.4"                  # semver, the author's
contract       = "parse/1"                # name + MAJOR only
schema_version = 3                        # output shape/semantics; ENTERS THE CACHE KEY
title          = "anydoc"
summary        = "Rust office/PDF decoder, no HTTP client, 12 fuzz targets."   # <=200 chars
homepage       = "https://github.com/firecrawl/anydoc"
isolation      = "inproc"                 # inproc | subproc | wasm ; host may only TIGHTEN
deterministic  = true

[capability]
consumes    = ["bytes"]
produces    = ["docmodel"]
formats     = ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "application/vnd.oasis.opendocument.text", "application/rtf",
               "application/epub+zip", "text/csv", "application/pdf"]
granularity = "document"                  # document | part | corpus  (exactly ONE)
detects     = true                        # can sniff format from bytes
lossy       = false
parse_back  = ""                          # compile/1 cards name a parse/1 id here

[fidelity]                                # ORDERED ladders, mine-parse.md E11 vocabulary
spatial       = "none"                    # none|page_bbox|block_bbox|line_bbox|char_bbox
charspan      = false
reading_order = "source"                  # raster|learned|model_emitted|char_stream|source
sections      = "typed_levels"            # none|markdown_only|outline_from_source|typed_levels
tables        = "cells_with_spans"        # none|flat_html|cells|cells_with_spans
math          = "none"
assets        = "bytes"                   # none|refs|bytes
notes         = "linked"                  # none|inline|linked
confidence    = "none"                    # none|document|page|element
furniture     = "flagged"                 # destroyed|flagged|separated
round_trip    = "structure"               # none|text|structure

[hardware]
needs          = []                       # [] | ["cuda:>=16GiB"] | ["ffmpeg"] | ["network"]
services       = []                       # Service names requested from ctx.service(...)
imports_torch  = false
install_bytes  = 2_400_000

[licence]
code         = "MIT"                      # SPDX
weights      = "none"                     # SPDX | "proprietary" | "none"
tier         = "open"                     # open | restricted | commercial | vetoed
restrictions = []                         # CLOSED vocabulary, 12 codes
notice       = "NOTICE"

[deps]                                    # for the transitive gate + optional key participation
pins = ["cfb=0.14.0","csv=1.4.0","flate2=1","encoding_rs=0.8.35","log=0.4",
        "pdf-inspector=1.14.2","quick-xml=0.41.0","zip=8.6.0"]

# ---- STAMPED BY omniweave-conform. Author-written values are rejected at publish. ----
[cost]
cost_class      = "free"                  # free | local_compute | billed_api
p50_ms_per_unit = 12
p95_ms_per_unit = 90
usd_per_unit    = 0.0
tokens_per_unit = 0
measured_on     = "x86_64-linux, 8c/16GiB, min-of-5 warm, in-process"

[quality]
kit_version = "1.0.0"
kit_run     = "2026-08-14T09:22:31Z"
suites      = { card="pass", purity="pass", parse_v1="pass", fidelity="pass", idempotence="pass" }
scores      = { office_structure_f1 = 0.94 }
attestation = "sha256:9f2c…"              # over the canonical card MINUS this key
```

### Tombstone card (shipped by the framework)

```toml
schema = 1
[driver]
id = "parse.ocr.surya"; contract = "parse/1"; version = "*"; title = "surya (weights)"
[licence]
code = "Apache-2.0"          # the CODE is free
weights = "AI-Pubs-OpenRAIL-M"
tier = "vetoed"
restrictions = ["no_compete","output_share_alike","attribution_per_output","remote_kill_switch"]
[removed]
reason = """MODEL_LICENSE (md5 e1f69b64dee2f1641a9b1ab12adf24d6) Attachment A clause 2(c) bars use
by any party offering a product competing with Licensor's — no revenue threshold, no research
carve-out (2(a)/(b) have one; 2(c) does not). Clause 8 licenses the OUTPUT. The Apache-2.0 CODE may
be run against other weights: see parse.ocr.olmocr."""
replaced_by = "parse.ocr.olmocr"
```

### Python-side types

```python
# omniweave/core/driver/card.py
Fidelity = TypedDict("Fidelity", {                       # every value from a closed ladder
    "spatial": Spatial, "charspan": bool, "reading_order": ReadingOrder,
    "sections": Sections, "tables": Tables, "math": Math, "assets": Assets,
    "notes": Notes, "confidence": ConfidenceGrain, "furniture": Furniture,
    "round_trip": RoundTrip})

@dataclass(frozen=True, slots=True)
class DriverCard:
    id: str                      # "parse.doc.anydoc"
    contract: str                # "parse/1"
    version: str
    schema_version: int
    isolation: Literal["inproc", "subproc", "wasm"]
    deterministic: bool
    granularity: Literal["document", "part", "corpus"]
    formats: frozenset[str]
    consumes: frozenset[str]
    produces: frozenset[str]
    fidelity: Fidelity
    needs: tuple[str, ...]
    services: tuple[str, ...]
    cost_class: CostClass
    usd_per_unit: float
    p50_ms_per_unit: int
    licence_tier: LicenceTier
    restrictions: frozenset[Restriction]
    attested: bool               # recomputed digest == quality.attestation
    card_sha256: str
    origin: CardOrigin           # entry_point | driver_path | tombstone | lockfile
    removed_reason: str | None
    deprecated: Deprecation | None
    # NOTE: no callable, no module path, no import. A card cannot execute anything.

# omniweave/core/driver/resolve.py
@dataclass(frozen=True)
class Requirement:
    contract: str
    format: str
    need: Mapping[str, object]         # fidelity floors, e.g. {"tables": "cells", "charspan": True}
    max_cost_class: CostClass
    budget_left_micros: int
    granularity: Literal["document", "part"] | None = None

@dataclass(frozen=True)
class Rejection:
    driver_id: str
    reason: str                        # "licence tier 'vetoed': MODEL_LICENSE clause 2(c)"
    code: RejectCode                   # CONTRACT_MAJOR|FORMAT|FIDELITY|LICENCE|HARDWARE|COST|
                                       # UNATTESTED|DENIED|REMOVED|GRANULARITY

@dataclass(frozen=True)
class Resolution:
    chosen: DriverCard | None
    ladder: tuple[DriverCard, ...]     # ordered fallbacks, for D4's escalation
    rejected: tuple[Rejection, ...]    # EVERY candidate that lost, with a reason
    policy_digest: str
    cards_digest: str

def resolve(want: Requirement, cards: frozenset[DriverCard], policy: Policy) -> Resolution: ...
#  PURE. No IO, no import, no clock. Memoised on
#  (contract, format, frozenset(need.items()), policy_digest, cards_digest).
```

### The `parse/1` contract

```python
# omniweave/core/driver/contracts/parse_v1.py
class ParseV1(Protocol):
    CARD: ClassVar[DriverCard]         # loaded from driver.toml at import, not hand-written

    def probe(self, ctx: RunContext) -> ProbeResult: ...
    #   The capability probe: smallest REAL operation. LDR's SQLCipher pattern.
    #   Cached per run. A red probe prunes the plan and REPORTS; never an ImportError.

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]: ...
    #   MUST NOT advance any stream it is given (markitdown asserts this invariant twice in its
    #   dispatcher; we assert it too, in the host, not in the driver).

    def parse(self, unit: UnitRef, parts: PartSelector, ctx: RunContext) -> StepResult: ...
    #   Returns StepResult (mine-runtime §7.1.2). NEVER returns None. NEVER raises for an
    #   expected condition: Encrypted / NeedsOcr{pages} / ResourceLimit{limit} are OUTCOMES.

    def is_valid_nonempty(self, artifact: ArtifactRef) -> bool: ...
    #   The runner converts OK-but-empty into FAILED_PERMANENT{EMPTY_RESULT} BEFORE caching.
    #   Exists because DataFlow writes "" on LLM failure and propagates it (§1.8c) and
    #   Unlimited-OCR writes "" for a page that failed 5 retries.
```

### `subproc` protocol — line-delimited JSON, blobs by URI

```
→ {"v":1,"op":"hello","contract":"parse/1","host":"omniweave/0.1.0"}
← {"v":1,"op":"hello","card_sha256":"9f2c…","pid":41233,"caps":["parse","sniff"]}
→ {"v":1,"op":"probe"}
← {"v":1,"op":"probe","ok":true,"detail":"cuda:1 device, 24GiB, kernel launch ok"}
→ {"v":1,"op":"parse","id":"r-91",
   "unit":{"uri":"ow://blob/sha256-ab12…","content_digest":"sha256:ab12…","part":"p:4000"},
   "blob_root":"/run/ow/b7/","out_root":"/run/ow/o7/","deadline_ms":30000,
   "budget_micros":12000,"config":{"dpi":192}}
← {"v":1,"op":"log","id":"r-91","level":"info","event":"page_needs_highres","page":4000}
← {"v":1,"op":"result","id":"r-91","outcome":"ok_partial",
   "produced":[{"kind":"docmodel","uri":"ow://blob/sha256-cd34…"}],
   "partial_reason":"page 4000 needs_ocr",
   "metrics":{"queued_ms":2,"ran_ms":1840,"input_tokens":0,"output_tokens":0,
              "cost_micros":0,"peak_rss_bytes":412000000}}
← {"v":1,"op":"result","id":"r-92","outcome":"failed_permanent",
   "failure_class":"RESOURCE_LIMIT","detail":{"limit":"xml_depth","value":256}}
→ {"v":1,"op":"bye"}
```

Rules: stdout is **protocol only** (a startup banner on stdout is a protocol violation; a banner on
stderr is rendered at error level by MCP hosts, so drivers log via the `log` op). `blob_root` is a
per-invocation directory the driver may read and `out_root` one it may write — the kit runs every
`subproc` driver once with a `blob_root` it cannot `listdir` to catch hardcoded path assumptions. A
child that exits or misses `deadline_ms` yields `FAILED_TRANSIENT{WORKER_DIED}` for the in-flight
unit only; the pool restarts and the retry halves the batch.

### `omniweave drivers explain` — the operational payoff, ~50 lines of code

```
$ omniweave drivers explain application/pdf --need tables=cells --need charspan=true

contract parse/1   format application/pdf   policy sha256:4b1e…   cards sha256:c0de…

CHOSEN   parse.pdf.native          v0.3.1  free           p50 210ms   $0.0000  open
LADDER   parse.ocr.olmocr          v0.5.0  local_compute   p50 2.4s   $0.0002  open
         parse.doc.anydoc          v0.2.4  free           p50  12ms   $0.0000  open   [needs_ocr fallback]

REJECTED
  parse.ocr.surya        REMOVED    MODEL_LICENSE clause 2(c) competitor bar; use parse.ocr.olmocr
  parse.pdf.marker       REMOVED    MODEL_LICENSE clause 8 licenses the Output
  parse.ocr.hunyuan      LICENCE    tier=vetoed  territory_excluded, field_of_use_barred
  parse.any.markitdown   FIDELITY   tables=flat_html < cells; charspan=false
  parse.vlm.internal     UNATTESTED no conformance attestation (run: omniweave conform)
  parse.ocr.tesseract    HARDWARE   probe red: language pack 'eng' missing
```

### Store DDL that D3 requires of D5

```sql
-- Restrictions travel on every produced item. 12 codes, one smallint.
ALTER TABLE block ADD COLUMN origin_driver   TEXT    NOT NULL;   -- "parse.doc.anydoc"
ALTER TABLE block ADD COLUMN driver_schema_v INTEGER NOT NULL;
ALTER TABLE block ADD COLUMN licence_bits    INTEGER NOT NULL DEFAULT 0;
CREATE INDEX block_licence ON block(licence_bits) WHERE licence_bits <> 0;  -- partial: usually empty

-- Card cache: warm discovery is one indexed SELECT, cold is one file read per driver.
CREATE TABLE driver_card_cache (
  dist_name  TEXT NOT NULL, dist_version TEXT NOT NULL, card_path TEXT NOT NULL,
  mtime_ns   INTEGER NOT NULL, size INTEGER NOT NULL,
  card_json  TEXT NOT NULL, card_sha256 TEXT NOT NULL,
  PRIMARY KEY (dist_name, dist_version, card_path)
) WITHOUT ROWID;
```

### Directory tree

```
omniweave/core/driver/
  card.py            DriverCard · load_card · CARD_SCHEMA (fail-closed on unknown keys)
  discover.py        entry-point scan (EntryPoint.value ONLY) · OMNIWEAVE_DRIVER_PATH · card cache
  resolve.py         Requirement · Rejection · Resolution · resolve()  [pure]
  registry.py        Registry[T]  (per-run instance; raises on duplicate)
  policy.py          Policy · allow/deny/pin/tiers/trust · policy_digest
  licence.py         Restriction enum · RESTRICTION_BITS · tier rules
  contracts/         acquire_v1.py  parse_v1.py  derive_v1.py  compile_v1.py
  host/              inproc.py (DriverGuard)  subproc.py (protocol + pool)  wasm.py (phase 4)
  tombstones/        marker.toml surya.toml lift.toml hunyuan.toml omniparse.toml
drivers/                                  # each its own distribution; core depends on NONE
  omniweave-driver-anydoc/    driver.toml + binding        (inproc, free, 2.4 MB)
  omniweave-driver-markitdown/driver.toml                  (inproc, free, ~150-250 MB, lossy)
  omniweave-driver-pdfnative/ driver.toml                  (inproc, free)
  omniweave-driver-olmocr/    driver.toml                  (subproc, cuda, local_compute)
conform/
  suites/{card,purity,parse_v1,derive_v1,compile_v1,fidelity,idempotence,determinism,licence}/
  fixtures/{formats/, adversarial/, LICENCES.md}           # a fixture corpus is redistributed content
  report.py
```

### Invariants and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| **D3-1** | No driver code is imported before the router selects it. | `EntryPoint.load()` banned in `core/driver/` (grep CI rule) + conform suite 2's import tracer + a core test that discovers 30 cards in a venv and asserts zero third-party imports |
| **D3-2** | A card claim is a test. | Conform suite 4 derives assertions from the card in **both** directions; `false`/`none` is asserted absent |
| **D3-3** | `[cost]` and `[quality]` are kit-written. | Publish gate rejects author-written values; loader recomputes `attestation`; `attested=false` ⇒ never auto-selected |
| **D3-4** | Selection is a pure, replayable function of declared evidence. | `resolve()` takes no `ctx`; a property test asserts equal `Resolution` for equal inputs; `Resolution` + digests recorded in the run manifest |
| **D3-5** | Every rejected candidate has a named reason. | `Rejection` is required to construct a `Resolution`; `drivers explain` prints it; a test asserts `len(rejected) + len(ladder) + (chosen is not None) == len(candidates)` |
| **D3-6** | A duplicate driver id never wins silently. | `Registry.register` raises `DuplicateDriver` unless `replace=True`; startup self-check resolves every catalog id |
| **D3-7** | Config never names an import path. | Card schema has no module/callable field; a lint rule bans `import_module`/`__import__` outside `host/`; config values referencing drivers are validated against registered ids |
| **D3-8** | A third-party driver cannot run in-process by its own claim. | `inproc` requires open+free+no-hardware+no-torch **and** the id listed under `[drivers.trust]`; card validation rejects the contradiction |
| **D3-9** | Restrictions travel on produced items. | `block.licence_bits NOT NULL`, set by the runner from the card (never by the driver); `compile/1` host refuses `output_share_alike` items; a test parses with a synthetic `restricted` driver and asserts the OUT refusal |
| **D3-10** | A transitive licence violation fails the build. | Conform suite 8 resolves the full graph **and** scans the import graph against the declared set; fails (not warns) on the denylist; the `cairosvg` case is a fixture |
| **D3-11** | Safety limits are not driver-configurable. | Limits are constants in `host/`, enforced at the read boundary with `take(N+1)`-then-check; no card field can raise them; effective value is `min(tenant_cap, MAX_*)` |
| **D3-12** | A missing driver is a pruned plan with a report, never an `ImportError`. | `probe()` at preflight; `Resolution.rejected` carries `HARDWARE`; `sys.exit` banned in library code |
| **D3-13** | Granularity is never mixed within one `(unit, contract)`. | Card declares exactly one `granularity`; the host refuses a `part`-granularity result over a `document`-granularity artefact for the same generation except as an explicit `escalation` layer |
| **D3-14** | A removed driver resolves to a reason, not to "unknown". | Framework-shipped tombstone cards; a test asserts every vetoed id in the risk register has a tombstone with a non-empty `removed_reason` |

### What it costs

| item | lines | time | notes |
|---|---:|---:|---|
| Card schema, loader, discovery, cache | ~700 | 1 wk | |
| `resolve()` + policy + `drivers explain` | ~500 | 0.5 wk | pure, heavily property-tested |
| `Registry` + preflight + probes | ~400 | 0.5 wk | |
| `parse/1` contract + `inproc` host + `DriverGuard` | ~600 | 1 wk | limits ported from `anydoc/src/limits.rs` |
| 4 first-party driver cards + bindings | ~900 | 2 wk | olmocr is the only expensive one |
| `subproc` host + protocol + pool | ~800 | 1.5 wk | **also the polyglot story** |
| `omniweave-conform` suites 1–5 | ~1,500 | 2 wk | |
| Fixture corpus (40 formats + 6 adversarial) | — | 1.5 wk | needs an owner and its own licence audit |
| Conform suites 6–9 + index + lockfile + rot sweep | ~1,200 | 2 wk | phase 3 |

**~6,600 lines, ~12 engineer-weeks to phase 3.** Runtime overhead: cold discovery target **< 15 ms
for 30 installed drivers** (one small file read each) against docling's four full
`importlib.metadata.distributions()` scans plus `ep.load()` of every plugin; warm is one indexed
`SELECT`. Memory: a card is ~2 KB, 100 drivers is 200 KB. Dependency weight added to core: **zero** —
core depends on no driver, and the base install stays inside the 250 MB target (contrast docling
≈2.5–3.5 GB because `torch` is a *base* dependency, so you cannot get its DOCX reader without a
tensor library). Operational burden: the weekly rot sweep (one CI job), the fixture corpus owner, and
two contract majors' worth of conformance suites at any time.

---

## Rationale

Three facts from the evidence set the shape, and everything else follows.

**Fact 1: the router must choose without importing.** D4 routes per page and per block. If choosing
requires importing, then choosing requires *installing*, and installing every candidate means `torch`
in the base install. The risk digest is unambiguous that this is the failure that eats the framework:
docling's DOCX reader costs 2.5–3.5 GB because `torch` is a base dependency, and an L5 orchestration
layer must never be a dependency of an L1 parser. A rich, import-free descriptor is therefore not a
nicety — it is what makes the 250 MB core install and the per-page router simultaneously possible.
docling *has* a plugin system and it does not have this property: `allow_external_plugins=False`
gates registration after pluggy has already `ep.load()`ed every candidate.

**Fact 2: a declaration nobody checks becomes a lie.** DataFlow has 171 operators with hand-written
`get_desc(lang)` prose and nothing comparing it to `inspect.signature(run)`. LEANN's `llms.txt`
declares 2 tools while the server ships 4, two of them state-changing and undeclared, and one grep
shows no generator and no test. open-slide's `skills-lock.json` hashes only `SKILL.md`, so a drifted
`references/` inside a pinned skill is undetected. Every descriptor in this collection that is not
mechanically checked has already rotted. So the card must be *the test plan*: `charspan = false`
asserts absence, `[cost]` is stamped by the measuring tool, and a tampered attestation demotes the
driver. That inversion — the descriptor generates the tests rather than describing them — is the
single idea in this proposal I would fight hardest for.

**Fact 3: licence tiering is worthless unless the restriction travels with the bytes.** OpenRAIL-M
clause 8 licenses the **Output**. A tier label on a driver stops selection; it does nothing once the
output is in the index and a deck is compiled from it three months later. `licence_bits` on every
produced item costs one smallint and turns "may I ship this" into an indexed query and a blocking
gate in the `compile/1` host. This is also why `licence.code` and `licence.weights` are two fields:
the marker/surya/lift case is Apache-2.0 code with unusable weights, and a single field cannot say
"run this code against other weights".

Beyond those three, the pragmatism is in the subtractions. **Four contracts, not seven**, because
chunkers and extractors have the same shape and embedders are Services. **Two isolation levels, not
three**, because WASM has no first user today and `anydoc/wasm/` will still be there when it does.
**No hosted registry**, because PyPI already solves distribution and what is missing is a *card
index*, which is a static JSON file and a CI byte-diff. **Tamper-evidence, not signatures**, because
a digest catches the realistic failure (a hand-edited card) and a PKI catches a threat we do not
have while adding an operational burden we cannot carry. Every one of those subtractions is a place
where the ambitious design would add an abstraction with one implementation.

And `subproc` deserves its own defence, because it is the one place I spend real money. It buys three
things with one mechanism: failure isolation for third-party code, GPU/torch drivers out of the core
process, and **any-language drivers**. anydoc is Rust with a WASM target; codegraph is TypeScript;
the OUT compilers are TypeScript. A framework whose plugin boundary is a Python ABC cannot use them
without a rewrite. One line-JSON protocol makes the isolation story and the polyglot story the same
1.5 weeks of work — which is exactly the kind of trade a small team should take, and exactly the trade
DataFlow refused when it built `AcceleratedOperatorABC` as a *parallel type hierarchy* for its
distributed path, making every operator either local or distributed with porting as a rewrite.

---

## Tradeoffs

1. **`inproc` is the default for first-party drivers, so a first-party segfault kills the process.**
   Bought: no IPC tax on the 12 ms office-format path, which is the framework's cheapest and most
   frequent route. Paid: we must fuzz those drivers (anydoc already ships 12 cargo-fuzz targets — the
   only fuzzed parser in the collection) and accept process death when we do not.
2. **The card duplicates facts the code already knows** (formats, config keys, determinism). Bought:
   import-free routing and a mechanically-checkable contract. Paid: a drift surface, mitigated by
   conformance but not eliminated for `subproc` drivers, where introspection is impossible and the
   `describe` op can lie.
3. **Fidelity ladders rank expressiveness, not accuracy.** Bought: a total order the resolver can use
   with no benchmark. Paid: a bad `cells_with_spans` driver outranks a good `flat_html` one until D4's
   quality feedback exists. I keep `[quality].scores` in the card so D4 has something to rank on, but
   I do not pretend D3 solves it.
4. **Two contract majors supported at once.** Bought: third parties are not broken by our releases.
   Paid: 8 conformance suites at steady state, and "additive-with-a-default" is a review judgement no
   test can enforce.
5. **No hosted registry and no signing.** Bought: 4+ weeks and an ongoing operational burden avoided.
   Paid: a determined author can ship a doctored card with a valid-looking attestation; the defence is
   the four-stage human review rubric, which awesome-skills itself admits does not scale past ~13
   entries without automation it declines to build.
6. **`schema_version` is hand-maintained.** Bought: a bug-fix release does not re-bill a BILLED_API
   cache. Paid: an author who forgets to bump it silently serves stale cached output — the single most
   expensive mistake available in this design, and it is enforced only by review plus the kit's
   idempotence suite noticing that output changed while `schema_version` did not (which the kit *can*
   check across two tagged versions, and should, in phase 3).
7. **Embedders as Services, not Drivers.** Bought: no fidelity ladder or cost class for a thing that
   needs neither. Paid: D5 may want to route between embedders on evidence, and it will have to build
   a smaller, separate mechanism for that or push the embedder behind a `derive/1` driver.

---

## Failure modes

1. **The card lies about real corpora.** `charspan = true` passes on the fixture corpus and is false
   on scanned PDFs. The kit measures what the fixtures contain and nothing else. The breaking input:
   any format whose hard cases are absent from a 40-file corpus — which is most of them.
2. **Expressiveness beats accuracy and the router picks the worse driver.** A VLM declaring
   `tables = cells_with_spans` outranks marker's model-free CPU judge declaring `flat_html`, and is
   worse on a ragged financial table. Until D4 has per-corpus quality feedback this is a real
   regression and the only mitigation is `policy.pin`.
3. **Attestation is tamper-evidence, not authentication.** An author runs the kit on a clean build,
   ships a different wheel with the same card. Nothing in D3 catches it; the `dist_sha256` in
   `omniweave.lock` catches it only for consumers who installed from the index.
4. **`subproc` blob-path assumptions.** A driver that resolves paths relative to CWD or assumes a
   shared filesystem works on T1/T2 and silently breaks on T3 multi-host. The kit's
   unreadable-`blob_root` fixture catches the common case and not the clever one.
5. **Mixed granularity on a 4,000-page PDF.** D3-13 forbids mixing within one `(unit, contract)`, but
   the realistic input — 3,999 digital pages and one scan — *wants* a document-granularity driver plus
   a part-granularity escalation. My rule makes the escalation an explicit second layer, which means
   two artefacts for one document, which means the shrink guard and the cost model must understand
   layers. mine-runtime flagged this as open question #1 and I am deferring it, not solving it. If D4
   or D5 needs true mixing, D3-13 is the invariant that has to give.
6. **Resolution cost at scale.** 4,000 parts × 3 candidate fidelity requests is 12,000 `resolve()`
   calls per document if unmemoised. Memoisation keys on `cards_digest`, so a driver installed
   mid-run invalidates every entry — correct, and a pathological churn case.
7. **Contract v1→v2 done badly.** If `parse/1` turns out to need a non-additive change in month four,
   every third-party driver breaks at once and we support two suites for a year with a two-person
   team. The realistic mitigation is that phase 1 ships `parse/1` with *four in-house drivers first*
   and no third-party contract promise until phase 2 — i.e. the promise is deliberately late.
8. **A tombstone becomes wrong.** If Datalab relicenses, `parse.ocr.surya` resolves to a stale refusal
   quoting a superseded clause. The rot sweep re-checks licence fields precisely because graphify
   relicensed MIT → Apache-2.0 in 2026, but a tombstone is *our* text and nothing forces us to revisit
   it. Give the tombstone directory a review date and a CI check on it.
9. **`licence_bits` runs out.** Twelve codes today; a thirteenth restriction class means a schema
   change on the hottest table. Reserve 32 bits, document the reservation, and accept that a 33rd code
   is a migration.
10. **The fixture corpus is itself a licence problem.** 40 real documents redistributed in a public
    repo. `conform/fixtures/LICENCES.md` is a required file and the corpus needs the same
    `{licence, licence_url, spdx, source_url, retrieved_at, sha256}` ledger hyperframes uses for
    media. If we get this wrong, the conformance kit is the thing that cannot be shipped.

---

## Why reject the alternatives

**docling's pluggy entry points.** The mechanism is right in shape and wrong in one decisive detail:
`base_factory.py:96` calls `load_setuptools_entrypoints`, pluggy 1.6.0 does `plugin = ep.load()` for
every entry point in the group, and the `allow_external_plugins` check at `:100-107` runs afterwards.
So the opt-in flag prevents *registration* by code that has already *executed*, four times over
(`factories/__init__.py:15,24,33,42`), each with a full distribution scan. It also dispatches on
**options type** rather than a string, which is genuinely good and which I keep in spirit — but the
options class lives in the driver, so knowing what options exist means importing. The card replaces
the options class as the *pre-selection* surface and keeps typed options as the *post-selection* one.

**markitdown's converter registry.** `accepts()`/`convert()` with priority ordering, and the
dispatcher *asserts* the stream-position invariant twice — the best protocol-enforcement instinct in
the collection, which I copy (in the host, not the driver). But `DocumentConverterResult` is
`(markdown, title)`: **there is no intermediate representation at all**, so no downstream feature can
re-derive spans, provenance or confidence. And `register_converter` inserting at the front so later
equal-priority registrations win means install order decides behaviour. markitdown is a *breadth
driver* for omniweave — `.msg`, RSS, YouTube, Wikipedia, ipynb — with a card declaring every fidelity
field `none` and `lossy = true`, which is exactly the honesty the card format exists to force.

**DataFlow's operator registry.** I take the *separation* (resources / static config / IO port / field
wiring) and reject the *mechanism*. `dataflow/utils/registry.py:81-83` is
`if name not in self._obj_map: self._obj_map[name] = obj` — flat `__name__` keys, first-wins,
silently; two packages shipping `PdfChunker` and the second vanishes. `get()` linear-scans
`LazyLoader` modules whose `__getattr__` *executes* the target, swallowing `AttributeError`, so a
driver that fails to import is indistinguishable from one that does not exist. The `TYPE_CHECKING` +
AST-scrape trick is clever and I decline it for the reason the notes give: scraping your own source at
runtime breaks on a `.pyc`-only or zipped install, and graphrag's lazy `match`-based registration
achieves the same import-time saving with no AST parser. What I *do* take verbatim is
`apply_whitelist`'s **report shape** — requested / missing / kept / removed / deltas — as
`Resolution.rejected`.

**omniparse's flag-gated model groups.** The idea is right and the implementation gates nothing:
`import torch`, `import whisper`, `from marker.models import load_all_models` are at module scope in
`omniparse/omniparse/__init__.py:20-27`, imported via `server.py:6` before `argparse` runs; `--media`
gates only `whisper.load_model("small")` at `:60`; all four routers are registered unconditionally at
`server.py:33-38` with the flags setting only `include_in_schema`. So the flags gate neither install
weight nor cold start nor route reachability. (It is also GPL-3.0 with its own file header attributing
copied marker code, and 21.9 months dead — a tombstone, not a design input.) The lesson I keep: a
capability flag must be a *discovery* mechanism, which is what the card is.

**marker's Provider/Builder/Processor/Renderer units.** Excellent *internal* structure for a parser,
and `resolve_dependencies` (`marker/converters/__init__.py:24-41`, 18 lines, no framework, no
decorators) is worth copying almost verbatim *inside* a driver. As an *extension* surface it is four
contracts where I need one, and the wiring is `--processors` / `--converter_cls` dotted strings
through `strings_to_classes` (`marker/marker/util.py:15-21`: `import_module` on a caller-supplied
string), settable from `--config_json`. Config that is an import path is an RCE channel the moment
config arrives in a request body. omniweave's config values are registered driver ids.

**The ambitious design: WASM-everything plus a signed hosted registry.** Correct at three years, wrong
at three months, and it has **no first user**. Our own drivers do not need a sandbox we would then
have to fight (a PDF driver that cannot open a file handle needs a WASI preopen story; a CUDA driver
cannot be WASM at all). Third-party drivers do not exist yet, so the signing infrastructure would
guard an empty set while costing a key-management burden a small team cannot carry. I keep `wasm` in
the card vocabulary and anydoc's existing `wasm32` target as the proof-of-boundary, so the door opens
in a week whenever there is a reason to open it.

**The minimal design: a Python `Protocol` and a dict, no cards.** Genuinely tempting — and it is what
phase 1 *is*, underneath. It fails on one requirement I cannot negotiate away: D4 must choose per page
without importing. Without a descriptor the router imports to choose, importing means installing,
installing means `torch` in the base install, and the framework's cheapest route — a DOCX parsed in
12 ms with a 2.4 MB dependency — stops existing. The card is not the plugin system; it is the router's
evidence, and the plugin system is what you get for free once the evidence exists.

---

## Terminology this decision coins (for D5–D10)

`Driver` · `DriverCard` · `driver.toml` · `DriverId` (dotted, e.g. `parse.doc.anydoc`) ·
`Contract` (`acquire/1`, `parse/1`, `derive/1`, `compile/1`) · `Fidelity` (11 ordered ladders) ·
`CostClass` (`free` / `local_compute` / `billed_api`) · `LicenceTier` (`open` / `restricted` /
`commercial` / `vetoed`) · `Restriction` (12 codes) · `licence_bits` · `Requirement` · `Rejection` ·
`Resolution` · `ladder` · `Tombstone` · `Attestation` · `DriverGuard` · `Service` (replaces
`ctx.driver(kind)` → `ctx.service(name)`) · `omniweave conform` · `omniweave.lock` ·
`OMNIWEAVE_DRIVER_PATH`
