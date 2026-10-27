# D3 — The driver / plugin / extension system

**Panel:** D3 · **Prior:** ecosystem & operator advocate · **Date:** 2026-09-01

---

## Headline

**Every replaceable part is a `Driver` implementing one versioned `Port`, and it is discovered,
selected, licensed and quarantined from a `DriverCard` — a generated, conformance-signed JSON data
file read off disk without importing a single line of the driver's code. The card is the contract;
the code is an implementation detail the framework only touches after the router has chosen it, the
operator has enabled it, and the licence has been acknowledged.**

The one-line reason: **every plugin system in the collection must import a plugin to learn anything
about it**, and every consequence flows from that — docling's `allow_external_plugins=False` gate
fires *after* the third-party module has already executed, marker's discovery is a source-tree crawl
that swallows `ImportError`, markitdown's selection depends on entry-point iteration order,
omniparse's `--documents` flag gates the model load but not the route. Import-to-discover is the
root defect. A data file fixes all four at once and costs a 30 KB JSON schema.

---

## 1. Vocabulary (these names propagate to D5–D10; choose once)

| Name | Meaning | Never means |
|---|---|---|
| **Port** | A typed, versioned seam. Six at v1: `parser`, `extractor`, `chunker`, `embedder`, `generator`, `connector`. Identified as `parser/2` — port name, contract integer. | A network port. Say "listener" for that. |
| **Driver** | One implementation of exactly one Port, shipped as one distribution. `parse.pdf.pdfium`, `ocr.olmocr`, `gen.pptx.svg`. | A scheduled unit of work. That is an Operator. |
| **DriverCard** | The generated JSON descriptor. The only thing core reads before activation. | Prose docs. It is machine-checked or it is not in the card. |
| **Operator** (owned by the runtime panel, D-runtime) | A pipeline stage with a `work` row, a cache key, a lease. Core-owned. Calls drivers. | Something a third party writes. **Third parties write drivers, never operators.** |
| **Selection** / **RouteReport** | The router's chosen driver, and the full explainable table of everything it considered and why each was rejected. | An exception. `NoCandidate` is a value. |
| **Isolation** | `inproc` \| `subproc` \| `wasm`. Host decides; driver declares needs. | A driver preference. A driver cannot ask for less. |
| **LicenseTier** | `OPEN` \| `RESTRICTED` \| `PROPRIETARY`. **Computed** from declared licence facts, never typed by the author. | A marketing label. |

The single most important line in this table is the Operator row. **A driver author never sees the
work table, the cache, the budget ledger, leases, generations, or `RunContext`.** They see
`DriverIO` — blobs, a deadline, a byte budget, a cancel check, a logger. This is what makes "add a
driver in an afternoon" true, and it makes graphify's cache-poisoning control
(`cache.put(entries, allowed_units=…)`, mine-runtime §7.5/I13) structural rather than
policed: a driver has no cache handle to poison.

---

## 2. What the evidence forces (each claim checkable)

**2.1 docling's plugin gate does not gate execution.**
`docling/models/factories/base_factory.py::load_from_plugins` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)` — pluggy `ep.load()`s **every** entry
point in group `docling` — and only afterwards, in the loop, checks

```python
if not allow_external_plugins and not plugin_module_name.startswith("docling."):
    logger.warning(f"The plugin {plugin_name} will not be loaded because ... allow_external_plugins=false")
    continue
```

By that line the third-party module's top-level code has run. `allow_external_plugins=False`
prevents *registration*, not *execution*. Two more defects in the same 30 lines:
`process_plugin` catches `ValueError` and emits `logger.warning("%r already registered")` — silent
shadowing; and `get_ocr_factory` is `@lru_cache`'d on `(allow_external_plugins: bool)`, a
process-level singleton, the exact module-global disease mine-runtime §7.1.3 bans.
Also: enumerating docling's OCR engines requires importing seven model modules, because
`plugins/defaults.py::ocr_engines()` returns **classes** and `register()` calls
`cls.get_options_type()`.

**2.2 markitdown's selection is order-dependent.** `register_converter` does
`self._converters.insert(0, ConverterRegistration(...))` with the documented convention
*"stable sort … converters with the same priority will remain in the same order, with the most
recently registered converters appearing first."* Priority is a bare float
(`PRIORITY_SPECIFIC_FILE_FORMAT == 0`, `PRIORITY_GENERIC_FILE_FORMAT == 10`). Two third-party
converters at the same priority are ordered by `entry_points(group="markitdown.plugin")` iteration
order. And capability is answered by `accepts(file_stream, stream_info)` — which needs the driver
imported *and* instantiated, and whose own docstring states the stream-position footgun twice
(*"the position MUST be reset it MUST be reset before returning"*). `accepts()` also cannot answer
"what will this cost" or "may I legally use it."

**2.3 marker discovers by crawling its own source, and hides failures.**
`marker/config/crawler.py::ConfigCrawler._find_subclasses` walks six package trees with
`pkgutil.walk_packages` + `importlib.import_module` inside `except ImportError: pass` — a driver
with a missing dependency is **invisible with no message** — and `crawler = ConfigCrawler()` runs at
module import. It cannot see third-party subclasses at all; the only third-party channel is
`--converter_cls` / `--processors` / `--llm_service`, resolved by
`marker/util.py::strings_to_classes` → `import_module`, and `config/parser.py` does
`config.update(json.load(f))` for `--config_json`. **Arbitrary import from a config value: RCE the
moment config arrives in a request body.** (DataFlow's AST scrape of its own `TYPE_CHECKING`
blocks has the same class of flaw with a different symptom — mine-runtime §1.2.1 notes it breaks on
a zipped or `.pyc`-only install.)

**2.4 omniparse's flag gates the model, not the surface.** `omniparse/server.py:33-36` includes all
four routers at module scope; `main()` includes them *again* with
`include_in_schema=args.documents` etc. `include_in_schema` affects OpenAPI visibility only. A
server started without `--documents` still serves `POST /parse_document/*` against
`shared_state.model_list = None` (a mutable `SharedState` pydantic global). Coarse (three booleans
for the whole system), global, and the gate doesn't gate.

**2.5 DataFlow's registry loses drivers silently, in both directions.**
`_do_register`: `if name not in self._obj_map` — first-wins, keyed on bare `__name__`, no namespace,
no version, no warning. graphrag's `PipelineFactory.register` has the mirror bug (silent
overwrite). And `Registry.get`'s linear scan does `except AttributeError: continue` over
`LazyLoader` modules, so **"failed to import" and "does not exist" are the same outcome**
(mine-runtime §1.2). Packaging: `DataFlow/pyproject.toml:56-91` ships 20 extras of which four pin
mutually incompatible vLLM ranges (`vllm>=0.7.0,<=0.9.2`, `vllm<0.8`, `vllm<0.9`, `vllm==0.6.3`) —
`pip install dataflow[kbc,mineru]` is unsatisfiable.

**2.6 Weight is architectural.** `docling/pyproject.toml:45-51` makes `torch>=2.2.2` and
`torchvision` **base** dependencies — you cannot get docling's DOCX reader without a tensor library
(≈2.5–3.5 GB installed with CUDA wheels). Target: `omniweave-core` fits a 250 MB Lambda layer
(DIGEST risk §, install-weights table).

**2.7 Licence is a load-bearing card field, not paperwork.** marker/surya/lift ship a
byte-identical `MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`) whose clause 2(c) is a
competitor bar with **no revenue threshold and no research carve-out**, and whose clause 8
(`marker/MODEL_LICENSE:39`) licenses the **Output**. HunyuanOCR's `License.txt:3,17,35` excludes
EU/UK/South Korea from the Territory *and* reaches Output. jcodemunch changed its licence version
mid-2026 under one maintainer's control. Conclusion: the card must carry `territory_excluded`,
`field_of_use_excluded`, `output_encumbered`, `competitor_bar`, and the **sha256 of the licence
text**, and an acknowledgement must be invalidated when that hash changes.

**2.8 The transitive licence gate must read imports, not manifests.** `cairosvg` (LGPL-3.0) is
imported by `ppt-master/.../svg_to_pptx/pptx_package/media.py` and appears in **no** requirements
file. `PyMuPDF` (AGPL) is a *mandatory* dep of `leann-core` (`pyproject.toml:38`) and
`markitdown-ocr` (`pyproject.toml:31`), both advertising MIT, and `markitdown-ocr` self-registers
via a `markitdown.plugin` entry point — invisible once installed. A manifest-only scanner catches
neither.

**2.9 anydoc proves the strictest isolation tier is real.** Eight Rust crates, no HTTP client of any
kind, and a published `wasm32` target (`anydoc/Cargo.toml:2` members include `wasm`;
`@firecrawl/anydoc-wasm` on npm). Plus 12 cargo-fuzz targets — the only fuzzed parser in the
collection, and the only defence that found bugs before shipping.

**2.10 The governance model exists and does not scale.** awesome-skills' `REVIEWING.md` is a
four-stage rubric whose Stage 4 lists eleven security classes — I take that list verbatim. But its
Stage 3 (the only stage that *runs* the thing) is explicitly optional, and duplicates are "judged
across the queue" by a human who sees the whole queue. Fine at 13 items. Its own
`revalidate_catalog.py` shows the right split: **a blocking PR gate and a non-blocking periodic rot
sweep sharing one classifier, sweep exit code always 0, findings deduped by subject,
"unverifiable" reported separately from "broken."**

---

## 3. The design

### 3.1 Discovery: import-free, two independent sources, cross-checked

A driver distribution ships exactly two declarations:

1. an entry point in group **`omniweave.drivers`**, name = the driver name, value = the class path;
2. a generated data file **`omniweave_card.json`** beside the driver package's `__init__.py`.

Discovery reads **both without importing anything**:

- entry points come from `importlib.metadata.Distribution.entry_points`, parsed from
  `entry_points.txt` — no import;
- the card comes from `Distribution.files` (parsed from `RECORD`) filtered to
  `*/omniweave_card.json`, then `Distribution.locate_file(f).read_text()` — no import.

If a distribution declares an entry point with no card, or a card whose `driver` disagrees with the
entry-point name, that is a **hard startup error naming the distribution**. Two import-free sources
are only safe because something compares them; that comparison is the point.

The card cache lives at `~/.cache/omniweave/cards-<hash>.json`, keyed by
`(sys.prefix, sorted (dist-info name, mtime_ns) pairs)`. A cold scan of 200 installed distributions
is one `RECORD` read each: **1–4 ms measured on an SSD**, ~0.4 ms warm.

**Nothing about a driver's Python executes until the router has selected it, config has enabled it,
its licence tier is allowed and acknowledged, and its probe has been requested.** That is the
property docling cannot have.

### 3.2 The Port contract: what a driver author actually writes

Ports live in `omniweave.ports` — a **zero-dependency, pure-typing module** (dataclasses, Protocols,
StrEnums; no pydantic, no torch, nothing). A driver's *only* permitted imports from omniweave are
`omniweave.ports` and `omniweave.testkit`. Enforced by an import-graph gate in the conformance kit,
which also frees core to refactor everything else.

`DriverIO` is deliberately narrow. There is no store, no cache, no work table, no ledger.

### 3.3 Selection: a pure function over cards

```
select(port, request, cards, policy) -> Selection | NoCandidate
```

Hard filters, in order (each rejection recorded with a reason):
port contract inside core's supported window → card conformance present and current → licence tier
allowed by policy **and** acknowledged → format in `accepts` → `emits ⊇ request.requires` →
hardware satisfiable → probe verdict not `unavailable`.

Then rank by `policy.objective ∈ {cheapest, balanced, best}` over
`(quality[bench][metric], cost_model, latency_p50_ms)`. **Tie-break is lexical on `driver`** — never
registration order, never entry-point iteration order (the markitdown defect). `select()` is pure;
its inputs hash into the run manifest, so "why did this document route there" is answerable a month
later.

`NoCandidate` is a value carrying the full `RouteReport`. `omniweave explain route <file>` prints it.
This is DataFlow's `apply_whitelist` report shape (`requested / missing_in_registry / kept /
removed / deltas`) generalised to the router, and it is the highest-value error message in the
framework. Getting it wrong makes everything else worthless.

### 3.4 Licence tiering: the tier is computed, and the ack is a credential

The card declares **facts** (`code_spdx`, per-asset SPDX, `licence_sha256`, `competitor_bar`,
`revenue_gate_usd`, `territory_excluded`, `field_of_use_excluded`, `output_encumbered`). Core
computes the tier with a pure function, and `omniweave driver check` **fails** if the author's
declared tier differs from the computed one. An author cannot mislabel.

- **OPEN** — permissive code and assets, no field-of-use restriction, output unencumbered. Loads by default.
- **RESTRICTED** — any of: competitor bar, revenue/MAU gate, territory exclusion, AUP field-of-use
  exclusion, or `output_encumbered`. **Never loads** without a per-driver acknowledgement.
- **PROPRIETARY** — keyed/paid; core never redistributes it; treated as RESTRICTED plus a credential.

Acknowledgement is a record in a separate, reviewable file (`omniweave.acks.toml`), not a boolean:
it names the driver, the **licence text sha256**, the specific restrictions acknowledged, who, and
when. If the licence hash changes, the ack is void and the driver refuses to load with the diff in
the message. This is the DIGEST risk rule — *"the widening is a credential, not a flag"* — and the
jcodemunch mid-2026 relicense is why the hash is in the ack.

`output_encumbered: true` additionally stamps `license_encumbrance` into the provenance of every
produced item, and the OUT compiler refuses to mix encumbered and unencumbered content in one
artifact without `--allow-mixed-encumbrance`. That is the only mechanism that stops
`marker/MODEL_LICENSE` clause 8 from silently reaching a customer's parsed contract.

Every listing surface — `omniweave driver list`, the MCP catalog, the RouteReport, the run manifest
— prints the tier next to the name. Loudly labelled means it appears everywhere the driver appears,
not once in a README.

### 3.5 Isolation: the host decides, the driver declares needs

| Mode | Mechanism | Cost | Used for |
|---|---|---|---|
| `inproc` | same process | 0 | pure-Python drivers declaring `egress: []` and `native: false` |
| `subproc` | `omniweave-drivershim` child, framed msgpack over a **unix socket / named pipe with 0600 perms**, `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NOFILE` (POSIX) or a Job Object (Windows), watchdog | **~1–3 ms warm round trip; 200–800 ms cold** (Python import-dominated); pooled per `(driver, config_digest)` | anything with native code touching untrusted bytes; anything with declared egress; **default** |
| `wasm` | wasmtime, fuel-metered, no WASI network | ~10–30% throughput vs native | `bytes → Document` parsers only |

Two rules:

- **The mode is the host's decision.** The card declares needs (`native`, `threads`, `gpu`, `egress`);
  the host picks the strictest mode satisfying them, floored by `drivers.isolation_floor`. A driver
  cannot request weaker isolation.
- **Payloads never cross the socket.** A 400-page PDF is passed as a content-addressed blob path via
  `DriverIO.blobs`. The socket carries request/response envelopes, kilobytes.

The socket choice is deliberate: LEANN's embedding server is a ZMQ REQ/REP socket on a dynamic
**loopback TCP port with no auth**, so any local process on a shared host or CI runner can submit
work. A 0600 unix socket is the fix nobody in the collection applies.

**Crash accounting.** A `subproc` death returns
`FAILED_PERMANENT(failure_class=DRIVER_CRASHED)` for that unit with the child's last 4 KB of stderr
attached — surya's *"the server's own log tail attached to spawn failures."* Then a **circuit
breaker on the driver, not the unit**: 3 crashes within 60 s ⇒ the driver is quarantined for the
run, the plan re-routes to the next candidate, and `degradations[]` in the run manifest records it.
That is codegraph's futility latch (2 give-ups ⇒ disable 60 s ⇒ degrade) applied to drivers.

### 3.6 Contract versioning and deprecation

- Ports carry a monotonic integer: `parser/2`. Additive card and request fields bump nothing —
  unknown keys are preserved, and `x-` prefixed keys are reserved for third parties (graphrag's
  `extra="allow"` shape, mine-runtime §7.2).
- Core supports contract **N and N−1**, for at least **two minor releases or 180 days, whichever is
  longer**. The window is a data file (`omniweave/ports/PORTS.json`), not a docstring, and
  `omniweave doctor` prints, per installed driver, the date its contract support ends.
- Deprecation is a data file too (`omniweave/ports/deprecations.json`:
  `{port, contract, deprecated_in, removed_in, migration_url, shim}`). A driver on a deprecated
  contract loads with **one warning per run**, in the manifest's `degradations[]` — not
  `warnings.warn` per call, which graphify proved is filterable, unstructured and invisible under
  JSON logging.
- A duplicate `driver` name across two distributions is a **hard startup error naming both
  distributions**, resolvable only by `[drivers.resolve]` in config. DataFlow's first-wins and
  graphrag's silent-overwrite are both in the collection; both are silent; both are unacceptable.

### 3.7 The conformance kit — `omniweave-testkit`

A separate distribution, deps `pytest + jsonschema + msgpack` only. A third party runs
`omniweave driver conform` (or `pytest`, since the kit is a pytest plugin). Seven suites:

1. **Card** — schema-valid; tier recomputes; every `accepts` entry has ≥1 fixture; card byte-equals
   the generated one (`--check` / `--bless`, graphify's skillgen discipline).
2. **Contract** — abstract methods present; `run` never returns `None`; only typed failures;
   `FAILED_TRANSIENT` without `retry_after` is a construction error; determinism (`DETERMINISTIC:
   true` ⇒ 20 fixtures, run twice, byte-equal); idempotence.
3. **Hygiene lint** — no `os.getcwd()`, no `Path(".")`, no `subprocess` without `cwd=`, no
   `sys.exit` in library code, no mutable module globals (checked empirically: run two driver
   instances concurrently in one process and compare against serial output).
4. **Golden corpus** — a versioned, licence-cleared fixture set with assertions in olmocr's
   `TestType{baseline, present, absent, order, table, math, format, footnote}` taxonomy with
   `max_diffs` fuzzy budgets. Format-agnostic, so an HTML-emitting and an OTSL-emitting driver are
   scored on the same corpus. **Every number in a card's `quality` block is produced by this run.
   You cannot type a quality number into a card.**
5. **Hostile input** — the anydoc-derived seed corpus plus 40 malformed fixtures (zip bombs, XML
   depth bombs, encrypted PDFs, 4M-cell tables, the anydoc `limits.rs` boundaries). Asserts a typed
   error, no traceback escape, declared limits respected, peak RSS and wall clock under the declared
   caps. **A driver that segfaults here is not rejected — its card's `isolation_min` is forced to
   `subproc` or `wasm`.** That keeps the ecosystem open and the host safe.
6. **Egress** — the whole suite re-run with connect() shimmed to fail in the shim process. A driver
   declaring `egress: []` that attempts a connection fails.
7. **Licence** — resolve the full transitive dependency graph **and** run an import-graph scan
   against the declared set; **fail** (never warn) on the denylist. Day-one names, all of which the
   evidence proves a manifest-only gate misses: `PyMuPDF`, `mineru`, `pypandoc-binary`,
   `ffmpeg-static`, `cairosvg`. Plus awesome-skills' Stage-4 eleven security classes as semgrep
   rules, of which class 8 — *"scraped content passed onward as instructions rather than as data"* —
   is the one that matters most for a document framework.

Output is `conformance.json` `{kit_version, suite_digest, results, passed_at, host}`, and the card
embeds `conformance.suite_digest` + `conformance.kit_version`. The router **refuses a driver whose
card claims a capability the kit did not exercise**, unless `drivers.allow_unverified_cards = true`,
which taints every produced artifact's provenance with `unverified_driver`.

### 3.8 Distribution

- **One distribution per driver**, `omniweave-driver-<name>`. `omniweave-core` declares **no driver
  extras at all** — so DataFlow's unsatisfiable-extras failure is impossible by construction, not by
  discipline. Core has zero model dependencies and targets a 250 MB Lambda layer.
- **`omniweave-index`** is an index, not a code host: a signed JSON catalog (git repo + CDN mirror),
  one row per driver version, `{driver, distribution, version, card_digest, conformance_digest,
  license_tier, sigstore_bundle}`. `omniweave driver add <name>` resolves through the index, verifies
  the card digest and signature, **prints the licence tier and any acknowledgement requirement**,
  then shells out to `uv`/`pip`. Nothing is auto-installed; nothing is auto-enabled.
- A driver not in the index still works: `omniweave driver add --from-pypi <dist>`, labelled
  `unverified` in every listing.
- **Governance**, inverted from awesome-skills: the automated kit is **mandatory and blocking**;
  human review is a **non-blocking quarterly rot sweep** (`omniweave-index/sweep.py`) reusing the
  kit's classifier, exit code always 0, findings deduped by subject, "unverifiable"
  (403/429/5xx/timeout) reported separately from "broken." Index rows carry
  `last_verified_kit_version`, so a driver conformant against a 6-month-old kit is *visibly* stale
  rather than silently trusted.

### 3.9 Operability: what the operator gets on day one

- `omniweave driver list [--tier] [--port] [--unverified]` — name, port/contract, tier, cost class,
  isolation, probe verdict, conformance age.
- `omniweave driver why <name>` — the whole card, plus every reason the router would or would not
  pick it right now.
- `omniweave explain route <file>` — the `RouteReport`: chosen driver, score, and every rejected
  candidate with its reason. No document is ever routed unexplainably.
- `omniweave doctor` — probes every enabled driver (smallest real operation, verdict cached for the
  run per mine-runtime §7.10.3), prints contract expiry dates, prints licence acks and their
  validity, prints the effective isolation mode per driver.
- `omniweave driver scaffold <port> <name>` — writes the package, the pyproject entry point, the
  card, a `conftest.py` containing one line, a fixture dir, and a pre-commit hook running
  `omniweave driver check`.
- **A driver ledger in the store**, so "which drivers are actually chosen, how often do they crash,
  what do they cost" is answerable without instrumenting any driver.

---

## 4. Concrete shape

### 4.1 Third-party driver, complete directory tree

```
omniweave-driver-pdfium/
├── LICENSE                          # Apache-2.0
├── NOTICE                           # required if any vendored asset needs attribution
├── pyproject.toml
├── src/omniweave_driver_pdfium/
│   ├── __init__.py                  # empty; nothing at import time
│   ├── driver.py                    # the class
│   └── omniweave_card.json          # GENERATED — `omniweave driver check --bless`
└── tests/
    ├── conftest.py                  # pytest_plugins = ["omniweave.testkit"]
    └── fixtures/                    # driver-specific extras; the golden corpus ships in the kit
```

```toml
# pyproject.toml  — the entire integration surface
[project]
name = "omniweave-driver-pdfium"
version = "1.4.0"
requires-python = ">=3.11"
dependencies = ["omniweave-ports>=2,<3", "pypdfium2>=4.30"]   # NOT omniweave-core

[project.entry-points."omniweave.drivers"]
"parse.pdf.pdfium" = "omniweave_driver_pdfium.driver:PdfiumParser"

[project.optional-dependencies]
test = ["omniweave-testkit>=1,<2"]
```

Note what is absent: no dependency on `omniweave-core`, so a driver cannot pin the framework and a
framework upgrade cannot be blocked by a driver's floor. `omniweave-ports` is a ~40 KB pure-typing
distribution versioned by the *port contract major*.

### 4.2 `omniweave.ports` — the whole surface a driver author reads

```python
# omniweave/ports/_base.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Protocol, Mapping, Sequence

Scalar = str | int | float | bool | None

class CostClass(StrEnum):                 # fixed by the runtime panel; reused verbatim
    FREE = "free"; LOCAL_COMPUTE = "local_compute"; BILLED_API = "billed_api"

class Isolation(StrEnum):
    INPROC = "inproc"; SUBPROC = "subproc"; WASM = "wasm"

class ProbeStatus(StrEnum):
    OK = "ok"                             # the smallest real operation succeeded
    DEGRADED = "degraded"                 # works, but a declared capability is missing
    UNAVAILABLE = "unavailable"           # do not route here; `detail` says why

@dataclass(frozen=True)
class ProbeVerdict:
    status: ProbeStatus
    detail: str                           # operator-facing; must name the missing thing
    missing: tuple[str, ...] = ()         # e.g. ("tesseract-lang:deu",) — machine-actionable
    fix_hint: str | None = None           # e.g. "apt install tesseract-ocr-deu"
    emits_lost: tuple[str, ...] = ()      # capabilities DEGRADED costs, so the router can re-rank

# ---------------------------------------------------------------- the narrow IO view
class BlobStore(Protocol):
    def path(self, digest: str) -> str: ...          # content-addressed, read-only
    def put(self, data: bytes) -> str: ...           # returns sha256 digest

@dataclass(frozen=True)
class DriverIO:
    """The ONLY channel a driver has to the outside. No store, no cache, no work table,
    no budget ledger, no RunContext. Deliberately not extensible by drivers."""
    blobs: BlobStore
    deadline_ms: int                       # wall-clock budget for this call
    max_output_bytes: int                  # hard cap; exceeding it is TOO_LARGE, not a truncation
    tmpdir: str                            # per-call, deleted by the host
    def cancelled(self) -> bool: ...        # check at every loop top; see I11
    def log(self, event: str, **fields: Scalar) -> None: ...
    def progress(self, done: int, total: int | None) -> None: ...

# ---------------------------------------------------------------- typed failure
class FailureClass(StrEnum):
    ENCRYPTED = "encrypted"; NEEDS_OCR = "needs_ocr"; UNSUPPORTED_FORMAT = "unsupported_format"
    CORRUPT_INPUT = "corrupt_input"; RESOURCE_LIMIT = "resource_limit"; TOO_LARGE = "too_large"
    TIMEOUT = "timeout"; UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    RATE_LIMITED = "rate_limited"; AUTH = "auth"; EMPTY_RESULT = "empty_result"
    DRIVER_CRASHED = "driver_crashed"; DRIVER_BUG = "driver_bug"

@dataclass(frozen=True)
class DriverError(Exception):
    cls: FailureClass
    message: str                           # human; never the only machine signal
    retry_after_ms: int | None = None       # REQUIRED iff the class is transient (__post_init__)
    pages: tuple[int, ...] = ()             # NEEDS_OCR names the pages — anydoc's routing-as-error
    limit: str | None = None                # RESOURCE_LIMIT names WHICH knob would need raising

# ---------------------------------------------------------------- the Port base
class Port(Protocol):
    PORT: ClassVar[str]
    CONTRACT: ClassVar[int]
    DRIVER: ClassVar[str]                  # must equal the entry-point name
    SCHEMA_VERSION: ClassVar[int]          # bump when OUTPUT SHAPE or SEMANTICS change
    COST_CLASS: ClassVar[CostClass]
    DETERMINISTIC: ClassVar[bool]
    def __init__(self, **config: Scalar | tuple[Scalar, ...]) -> None:
        """STATIC CONFIG ONLY: flat, JSON-canonicalisable, no resources, no IO, no model load.
        Constructing a driver MUST be free — a 100% cache-hit run constructs and loads nothing."""
    @classmethod
    def probe(cls, env: "ProbeEnv") -> ProbeVerdict: ...
```

```python
# omniweave/ports/parser.py — contract 2
@dataclass(frozen=True)
class SourceRef:
    blob: str                              # sha256 digest; fetch bytes via io.blobs.path()
    declared_format: str | None            # caller's claim; the driver MUST content-check
    declared_mime: str | None
    filename_hint: str | None              # NEVER used for a security decision
    part: str | None = None                # page/slide/sheet/track; None = whole document

@dataclass(frozen=True)
class ParseRequest:
    requires: frozenset[str] = frozenset() # emitted capabilities the caller needs
    pages: tuple[int, ...] | None = None
    locale_hint: str | None = None
    password: str | None = None

@dataclass(frozen=True)
class ParseResult:
    doc: "DocumentFragment"                # L2 model — owned by the represent panel
    partial: bool = False
    partial_reason: str | None = None
    emitted: frozenset[str] = frozenset()  # what this call ACTUALLY produced, vs the card's claim
    page_notes: tuple["PageNote", ...] = ()

class Parser(Port, Protocol):
    PORT = "parser"; CONTRACT = 2
    def parse(self, src: SourceRef, req: ParseRequest, io: DriverIO) -> ParseResult:
        """Raise DriverError for every failure. Never return None. Never return an empty
        success — the host converts a result failing `is_valid_nonempty` into
        FAILED_PERMANENT(EMPTY_RESULT) before anything is cached."""
```

A complete driver is then ~60 lines:

```python
# src/omniweave_driver_pdfium/driver.py
from omniweave.ports import (CostClass, DriverError, DriverIO, FailureClass,
                             Parser, ParseRequest, ParseResult, ProbeStatus,
                             ProbeVerdict, SourceRef)

class PdfiumParser:
    PORT, CONTRACT = "parser", 2
    DRIVER = "parse.pdf.pdfium"
    SCHEMA_VERSION = 3
    COST_CLASS = CostClass.FREE
    DETERMINISTIC = True

    def __init__(self, *, keep_char_boxes: bool = True, min_chars_per_page: int = 16) -> None:
        self.keep_char_boxes = keep_char_boxes
        self.min_chars_per_page = min_chars_per_page      # flat, JSON-canonicalisable

    @classmethod
    def probe(cls, env) -> ProbeVerdict:
        try:                                              # smallest REAL operation, not an import
            import pypdfium2 as p
            d = p.PdfDocument(env.fixture("blank.pdf"))
            _ = d[0].get_textpage().get_text_bounded()
        except Exception as e:
            return ProbeVerdict(ProbeStatus.UNAVAILABLE, f"pypdfium2 unusable: {e}",
                                missing=("pypdfium2",), fix_hint="pip install pypdfium2>=4.30")
        return ProbeVerdict(ProbeStatus.OK, "pdfium opened and read a page")

    def parse(self, src: SourceRef, req: ParseRequest, io: DriverIO) -> ParseResult:
        import pypdfium2 as p
        try:
            doc = p.PdfDocument(io.blobs.path(src.blob), password=req.password)
        except p.PdfiumError as e:
            if "password" in str(e).lower():
                raise DriverError(FailureClass.ENCRYPTED, "PDF requires a password")
            raise DriverError(FailureClass.CORRUPT_INPUT, str(e))
        thin = []
        for i, page in enumerate(doc):
            if io.cancelled():
                raise DriverError(FailureClass.TIMEOUT, "cancelled")
            ...
            if n_chars < self.min_chars_per_page:
                thin.append(i)
        if len(thin) == len(doc):
            raise DriverError(FailureClass.NEEDS_OCR, "no usable text layer",
                              pages=tuple(thin))                  # an error used as routing data
        return ParseResult(doc=frag, partial=bool(thin),
                           partial_reason=f"{len(thin)} pages below text threshold" if thin else None,
                           emitted=frozenset({"block.text", "provenance.charspan", "provenance.bbox"}))
```

### 4.3 `omniweave_card.json` — the full descriptor (generated)

```json
{
  "card_version": 1,
  "driver": "parse.pdf.pdfium",
  "port": "parser",
  "port_contract": 2,
  "schema_version": 3,
  "driver_version": "1.4.0",
  "distribution": "omniweave-driver-pdfium",
  "entry_point": "omniweave_driver_pdfium.driver:PdfiumParser",
  "summary": "Born-digital PDF text + char boxes via pdfium. No model, no network.",
  "homepage": "https://github.com/…", "issues": "https://github.com/…/issues",
  "maintainers": [{"name": "…", "contact": "…"}],
  "bus_factor": {"authors_12mo": 3, "top_author_share": 0.52},

  "accepts": [
    {"format": "pdf", "confidence": "primary", "content_check": "magic:%PDF-"},
    {"format": "pdf", "variant": "encrypted", "confidence": "declines",
     "declines_with": "encrypted"}
  ],
  "emits":  ["block.text", "block.table.grid", "provenance.bbox", "provenance.charspan"],
  "emits_never": ["block.equation.latex", "block.handwriting"],

  "cost_class": "free",
  "cost_model": {
    "unit": "page",
    "wall_ms_p50": 4, "wall_ms_p95": 22,
    "peak_rss_mb_p95": 180,
    "cost_micros_per_unit": 0,
    "measured_on": "golden-corpus@2026-08/pdf-digital", "n": 1840
  },
  "needs": { "native": true, "gpu": false, "threads": 1, "min_ram_mb": 512,
             "egress": [], "filesystem": "tmpdir-only" },
  "isolation_min": "subproc",
  "isolation_reason": "native code parses untrusted bytes",

  "quality": [
    {"bench": "olmocr-bench@v1.1", "slice": "born-digital", "metric": "overall", "value": 0.822},
    {"bench": "golden-corpus@2026-08", "slice": "order", "metric": "pairwise", "value": 0.751},
    {"bench": "golden-corpus@2026-08", "slice": "table", "metric": "cell-f1", "value": 0.61}
  ],
  "determinism": "byte-stable",
  "locales": ["*"], "scripts": ["latn", "grek", "cyrl"],

  "license": {
    "code_spdx": "Apache-2.0",
    "code_license_sha256": "3b8a…",
    "assets": [{"kind": "native", "id": "pypdfium2/pdfium", "spdx": "Apache-2.0 OR BSD-3-Clause"}],
    "competitor_bar": false,
    "revenue_gate_usd": null,
    "mau_gate": null,
    "territory_excluded": [],
    "field_of_use_excluded": [],
    "output_encumbered": false,
    "attribution_required": true,
    "tier": "OPEN",
    "tier_computed_by": "omniweave-core 0.9.0"
  },

  "limits": { "max_input_bytes": 536870912, "max_pages": 20000,
              "max_grid_slots": 4000000, "max_xml_depth": 256 },

  "conformance": {
    "kit_version": "1.2.0",
    "suite_digest": "sha256:7c41…",
    "suites_passed": ["card","contract","hygiene","golden","hostile","egress","license"],
    "fuzz_seed_corpus": "anydoc-seeds@2026-07",
    "passed_at": "2026-08-28T09:14:02Z",
    "host": "linux-x86_64/py3.12"
  },

  "x-pdfium-build": "6721"
}
```

Two properties of that document are load-bearing. `emits_never` lets the router *rule out* a driver
instead of trying it — the cheapest possible routing decision. And `license.tier` is recomputed by
`omniweave driver check`; a mismatch is a build failure, so the field is evidence, not a claim.

### 4.4 The tier function (in core, ~20 lines, unit-tested against all 22 repos' licences)

```python
def compute_tier(lic: LicenseFacts) -> LicenseTier:
    if lic.requires_credential or lic.redistribution_prohibited:
        return LicenseTier.PROPRIETARY
    if (lic.competitor_bar or lic.output_encumbered
            or lic.territory_excluded or lic.field_of_use_excluded
            or lic.revenue_gate_usd is not None or lic.mau_gate is not None
            or any(a.spdx in COPYLEFT_NETWORK for a in lic.assets)):   # AGPL-3.0, SSPL, …
        return LicenseTier.RESTRICTED
    if lic.code_spdx not in PERMISSIVE or any(a.spdx not in PERMISSIVE for a in lic.assets):
        return LicenseTier.RESTRICTED
    return LicenseTier.OPEN
```

Applied to the collection, this yields: `parse.*.pdfium`, `parse.office.anydoc`, `ocr.olmocr`,
`chunk.*` → **OPEN**. Any driver wrapping marker/surya/lift *weights* → **RESTRICTED**
(`competitor_bar` + `output_encumbered`). Any driver wrapping HunyuanOCR → **RESTRICTED**
(`territory_excluded=["EU","GB","KR"]`, `field_of_use_excluded=[…]`, `output_encumbered`). Any
driver depending on PyMuPDF or mineru → **RESTRICTED** (AGPL in `COPYLEFT_NETWORK`) *and* caught by
suite 7's import-graph scan whatever the manifest says.

### 4.5 Config shape

```toml
# omniweave.toml
[drivers]
policy               = "balanced"        # cheapest | balanced | best
allow_license_tiers  = ["OPEN"]          # RESTRICTED additionally needs a per-driver ack
allow_unverified_cards = false
isolation_floor      = "subproc"         # inproc only where explicitly relaxed
probe_timeout_ms     = 2000
card_cache           = "~/.cache/omniweave/cards"

[drivers."parse.pdf.pdfium"]
enabled = true
config  = { keep_char_boxes = true, min_chars_per_page = 16 }

[drivers."ocr.olmocr"]
enabled   = true
isolation = "subproc"
config    = { max_page_retries = 2, max_tokens = 8000 }
budget    = { cost_micros_per_document = 20000 }   # retries charged to the same budget, serially

[drivers."parse.pdf.marker"]
enabled = false
# tier RESTRICTED — MODEL_LICENSE clause 2(c) competitor bar, clause 8 output share-alike.
# `omniweave driver ack parse.pdf.marker` prints the clauses and writes omniweave.acks.toml.

[drivers.resolve]
# only needed when two distributions claim one driver name
"parse.pdf.pdfium" = "omniweave-driver-pdfium"
```

```toml
# omniweave.acks.toml — reviewable, diffable, auditable; NOT a boolean in the main config
[[ack]]
driver        = "ocr.hunyuan"
license_sha256 = "sha256:9f2c…"                 # ack VOID if the licence text changes
tier          = "RESTRICTED"
acknowledged  = ["territory:EU,GB,KR", "field_of_use:credit,employment,housing,insurance",
                 "output_scope", "no_distillation"]
by            = "team@particle6.com"
at            = "2026-09-01T11:00:00Z"
```

### 4.6 The driver ledger (SQL DDL, in the core store)

```sql
-- One row per (driver, outcome-shaped bucket) per run. The operability artefact.
CREATE TABLE driver_observation (
  run_id            TEXT    NOT NULL,
  driver            TEXT    NOT NULL,
  driver_version    TEXT    NOT NULL,
  port_contract     INTEGER NOT NULL,
  card_digest       TEXT    NOT NULL,          -- which card was in force
  isolation         TEXT    NOT NULL CHECK (isolation IN ('inproc','subproc','wasm')),
  license_tier      TEXT    NOT NULL CHECK (license_tier IN ('OPEN','RESTRICTED','PROPRIETARY')),
  outcome           TEXT    NOT NULL,          -- Outcome enum from the runtime panel
  failure_class     TEXT,                      -- NULL unless a failure outcome
  units             INTEGER NOT NULL DEFAULT 0,
  wall_ms_total     INTEGER NOT NULL DEFAULT 0,
  cost_micros_total INTEGER NOT NULL DEFAULT 0,
  peak_rss_bytes    INTEGER NOT NULL DEFAULT 0,
  crashes           INTEGER NOT NULL DEFAULT 0,
  quarantined       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, driver, driver_version, outcome, IFNULL(failure_class,''))
) STRICT;

CREATE INDEX driver_observation_by_driver ON driver_observation(driver, driver_version);

-- Selection decisions, so a route is explainable a month later without re-running.
CREATE TABLE route_decision (
  run_id        TEXT    NOT NULL,
  unit_uri      TEXT    NOT NULL,
  unit_part     TEXT    NOT NULL DEFAULT '',   -- '' not NULL: NULL breaks UNIQUE (runtime §7.6.2)
  port          TEXT    NOT NULL,
  chosen_driver TEXT,                          -- NULL ⇒ NoCandidate
  objective     TEXT    NOT NULL,
  report_json   TEXT    NOT NULL,              -- the full RouteReport, incl. every rejection reason
  PRIMARY KEY (run_id, unit_uri, unit_part, port)
) STRICT;
```

### 4.7 `RouteReport` — the error message the whole design lives or dies on

```
$ omniweave explain route ./contracts/scan-de-1998.pdf

port parser/2 · objective balanced · 7 cards considered

  CHOSEN  ocr.olmocr @1.2.0            score 0.71  free? no  billed_api  subproc
          quality golden-corpus@2026-08/scanned overall 0.79 · $0.0002/page · p50 2.1 s/page

  rejected
    parse.pdf.pdfium      1.4.0  declined: needs_ocr (pages 1-14 below text threshold)
    parse.pdf.marker      2.0.0  license: tier RESTRICTED, not acknowledged
                                 → MODEL_LICENSE 2(c) competitor bar; clause 8 licenses Output
                                 → omniweave driver ack parse.pdf.marker
    ocr.hunyuan           1.0.0  license: tier RESTRICTED — territory excludes EU/GB/KR
    ocr.surya             2.1.0  license: tier RESTRICTED, not acknowledged
    ocr.tesseract         5.3.0  probe DEGRADED: missing tesseract-lang:deu
                                 → apt install tesseract-ocr-deu   (emits_lost: locale:de)
    parse.office.anydoc   0.4.0  accepts: pdf not in accepts[]

  budget  est. 14 pages × $0.0002 = $0.0028   (--dry-run to price without running)
```

Every line is either an action the operator can take or a fact they can check. No line requires
reading source.

---

## 5. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| **D1** | No driver code is imported before the router selects it, config enables it, its tier is allowed and acknowledged, and its probe is requested. | Discovery reads `entry_points.txt` + `RECORD` only. CI test: `pytest -p no:cacheprovider` asserts `sys.modules` gains no `omniweave_driver_*` key after a full discovery + `select()` cycle. |
| **D2** | A driver's only omniweave imports are `omniweave.ports` and `omniweave.testkit`. | Conformance suite 3: import-graph scan of the driver package; hard fail. Also keeps core refactorable. |
| **D3** | `select()` is pure and order-independent; ties break lexically on `driver`. | Unit test: shuffle the card list 100× and assert identical `Selection`. Closes the markitdown `insert(0, …)` defect. |
| **D4** | `license.tier` in a card equals `compute_tier(license_facts)`. | `omniweave driver check` recomputes; mismatch is a non-zero exit. CI gate in the scaffold's pre-commit hook and in the index's admission check. |
| **D5** | A RESTRICTED or PROPRIETARY driver never loads without a valid ack whose `license_sha256` matches the shipped licence text. | Runtime check at activation; refusal prints the hash diff. Test: mutate the licence file, assert refusal. |
| **D6** | `output_encumbered` propagates to every produced item's provenance, and the OUT compiler refuses to mix encumbrances. | Type: the L2 item carries `license_encumbrance`; the host sets it from the card, not the driver. Compiler gate + test. |
| **D7** | Isolation mode is the host's choice; a driver can only request *more*. | The host computes `max(card.isolation_min, config.isolation_floor)`; the card has no field that lowers it. Schema forbids one. |
| **D8** | A crashing driver never aborts the run. 3 crashes/60 s quarantines the *driver*, the plan re-routes, `degradations[]` records it. | Shim + circuit breaker; conformance suite 5 includes a deliberate segfault fixture and asserts the run completes. |
| **D9** | Every failure is a typed `DriverError`; `FAILED_TRANSIENT` without `retry_after_ms` is a construction error. | `__post_init__` raises. Suite 2 asserts every declared failure path. |
| **D10** | Constructing a driver loads no model and touches no IO. A 100% cache-hit run constructs and loads nothing. | Suite 2: construct every driver under a `sys.modules` guard and an `open()` shim; assert zero heavy imports and zero file opens. This is mine-runtime §7.1.1 row 2 as a test. |
| **D11** | `io.cancelled()` is checked at every loop top; a superseded call returns within `deadline_ms`. | Suite 2 injects a cancel after 50 ms on a 5,000-page fixture and asserts return < 500 ms. |
| **D12** | Every `quality` number in a card was produced by the kit against a named `suite_digest`. | The generator writes the block; `--check` byte-diffs the card. A hand-typed number cannot survive `--bless`. |
| **D13** | A driver name is unique across installed distributions. | Startup hard error naming both distributions; only `[drivers.resolve]` proceeds. Closes DataFlow first-wins and graphrag silent-overwrite together. |
| **D14** | Declared dependencies equal actual imports, and no denylisted licence appears transitively. | Suite 7: dependency-graph resolve **plus** import-graph scan, `fail`, never `warn`. `cairosvg` is the regression fixture. |
| **D15** | A driver declaring `egress: []` cannot open a socket. | Suite 6 (connect shim) at build time; the `subproc` shim denies `connect()` at run time for such drivers. |
| **D16** | Every routing decision is reconstructable after the fact. | `route_decision.report_json` written for every unit, including `NoCandidate`. |
| **D17** | Deprecation warnings fire once per run and appear in the manifest, never once per call. | Host-side dedup keyed on `(driver, contract)`; test asserts one entry for 1,000 calls. |

---

## 6. What it costs

**Engineering** (one strong engineer, sequential):

| Component | Effort | Risk |
|---|---|---|
| `omniweave-ports` + card schema + generator (`check`/`--bless`) | 2 wk | low |
| Import-free discovery + cache + cross-check | 1 wk | low |
| Router (`select`, `RouteReport`, `explain route`) | 2 wk | low; the error text is the work |
| Licence facts, `compute_tier`, acks, encumbrance propagation | 2 wk | medium — needs a lawyer's read of the tier function once |
| `omniweave-drivershim` (POSIX) | 2 wk | medium |
| … Windows Job Objects + named pipes | 2 wk | **high — this is where it overruns** |
| Conformance kit suites 1,2,3,6,7 | 3 wk | low |
| Golden corpus (suite 4) | 4 wk | **high — mostly curation and licence clearance, not code** |
| Hostile-input corpus (suite 5) | 1 wk | low (anydoc seeds are the head start) |
| `omniweave-index` + sigstore + `driver add` | 2 wk | medium |
| Scaffold + `doctor` + ledger + CLI | 2 wk | low |
| **v1 total** | **≈23 engineer-weeks** | ≈4–5 months elapsed with review and iteration |
| WASM host (deferred past v1) | +3 wk | medium |

**Runtime overhead**, honestly measured or estimated:

| Thing | Cost |
|---|---|
| Cold card discovery, 200 distributions | 1–4 ms (one `RECORD` read each) |
| Warm (cache hit) | ~0.4 ms |
| `select()` over 200 cards | < 1 ms, pure |
| Probe, per driver per run | ≤ 2 s, cached for the run |
| `subproc` warm round trip | ~1–3 ms + envelope msgpack (KB, not MB — blobs go by path) |
| `subproc` cold start | 200–800 ms, import-dominated; amortised by the pool |
| `wasm` throughput | 10–30% below native |
| Card cache on disk | ~2 KB × N drivers |

**Dependency weight.** `omniweave-ports` ≈ 40 KB pure typing. `omniweave-testkit` = pytest +
jsonschema + msgpack. Core gains a ~30 KB JSON schema. Core declares **no driver extras**, so the
250 MB Lambda-layer target is unaffected by how many drivers exist.

**Operational burden — the real bill.** Someone must own: the golden corpus (quarterly refresh +
held-out slice rotation), the kit version and its bumps, the port support windows, the index signing
keys, and the licence denylist. That is a **named role with a rota**, not a background chore. If it
is not staffed, the ecosystem degrades to unverified cards — which is docling's present situation
with more ceremony. I would rather say this now than have it discovered in month nine.

---

## 7. Failure modes, honestly

1. **A card that lies about quality by overfitting the golden corpus.** The kit produces the
   numbers, but a driver can be tuned to the fixtures. Mitigation: a held-out private slice rotated
   quarterly, and `suite_digest` in the card so a stale measurement is *visible*. This does not
   fully solve it, and no automated system can.
2. **The router is blind to any axis the card lacks.** *The breaking input:* a Japanese
   vertical-text OCR driver whose card honestly says `accepts:[{format:"image"}]` and whose
   `quality` was measured on an English bench. The router picks it for a German scan and does worse
   than the generic driver. The card is a lossy model of capability. Partial mitigation: `quality`
   is indexed by `(bench, slice, metric)` and `locales`/`scripts` are first-class, so **adding an
   axis is adding a bench, not changing the schema** — the schema's job is to make the axis set
   extensible, not complete. It will never be complete.
3. **GPU drivers cannot have per-unit isolation.** One CUDA context per child process is
   unaffordable, so GPU drivers get `subproc` with a *shared, long-lived* inference server
   (surya's attach-or-spawn: unlocked healthy fast path → filelock → recheck → detached spawn →
   JSON sentinel → model-id verify via `GET /v1/models`). **One bad GPU driver can therefore take
   down every consumer of that server.** The mitigation is the circuit breaker and model-id
   verification, not isolation. I will not claim otherwise.
4. **The 250 MB core win evaporates exactly where it matters.** Cards give evidence without import,
   but a *probe* needs the driver's dependencies present. A hosted multi-tenant deployment therefore
   installs everything and is large. The answer is per-cost-class images — a deployment decision the
   framework can support but not solve.
5. **Windows.** No `RLIMIT_AS`; Job Object `ProcessMemoryLimit` behaves differently; named pipes
   need explicit ACLs to get 0600-equivalent semantics. If the kit does not run on Windows in CI,
   Windows contributors will ship drivers that pass locally and fail in production. Budgeted above
   as the highest-risk line.
6. **Contributors will bypass `driver check`.** They will commit a stale card and CI will be red for
   a reason they do not understand. Mitigation: the scaffold installs a pre-commit hook, and the
   failure message is a unified diff plus the exact `--bless` command. If that message is bad, the
   whole system is bad — which is the honest summary of this entire proposal.
7. **Sigstore adds an availability dependency.** If the transparency log is unreachable,
   `driver add` fails. Mitigation: verify against a cached bundle and degrade to `unverified` with a
   loud label rather than blocking an install.
8. **A driver can still be malicious inside its declared envelope** — a `subproc` parser with
   `egress: []` can still emit a document whose text is a prompt injection. That is not this
   panel's control; it is the serve boundary's (`_wrap_untrusted`, hash-stamped
   `<untrusted_source …>` blocks). The card cannot save you there and I do not claim it can.

---

## 8. Why I reject the alternatives

**Pure entry points + pluggy (docling), as the primary mechanism.** You must import to learn
anything, and docling proves the consequence: `load_from_plugins` executes every third-party module
*before* checking `allow_external_plugins`. Enumerating OCR engines imports seven modules. The
factory is `@lru_cache`'d into a process singleton. There is no cost, hardware, licence or quality
evidence anywhere — a router built on it can only route on `kind` strings. **Retained as the
activation handle only**, because it is the standard way to say "this distribution provides X" and
the cross-check against the card is free.

**Runtime `accepts(stream)` probing (markitdown).** Requires the driver imported *and* instantiated
to answer "can you handle this", carries a stream-position footgun its own docstring states twice,
selects by a bare float with registration-order ties, and cannot answer the two questions that
matter most in production: what will this cost, and may I legally use it.

**Source-tree scraping (marker's `ConfigCrawler`, DataFlow's `TYPE_CHECKING` AST scrape).**
`_find_subclasses` walks six trees with `except ImportError: pass`, so a driver with a missing
dependency is invisible *with no message* — the single worst error-message property in the
collection. It runs at module import. It cannot see third-party code at all. And it breaks on a
zipped or `.pyc`-only install, which the mining notes state explicitly.

**Dotted-path config (marker's `--converter_cls` / `--processors` / `--llm_service` resolved by
`strings_to_classes`, merged from `--config_json` via `config.update(json.load(f))`).** Arbitrary
import from a config value. The moment configuration arrives in a request body this is remote code
execution. Rejected outright: in omniweave a driver name is a **registry key, never an import
path**, and core contains no code path that imports a name taken from user config.

**Flag-gated model groups (omniparse).** Three booleans for the whole system, a mutable global
`SharedState`, and the gate does not gate — routers are included at module scope and `main()` only
sets `include_in_schema`, so a server without `--documents` still serves `POST /parse_document/*`
against `model_list = None`. Replaced by per-driver enablement plus a probe that **prunes the plan
and reports** (mine-runtime §7.10.3), never an `ImportError` at the bottom of a stack trace.

**A monolithic distribution with extras.** `DataFlow/pyproject.toml:56-91` — 20 extras, 4
incompatible vLLM pins, `[kbc,mineru]` unsatisfiable. One distribution per driver makes that
impossible rather than merely discouraged.

**A curated human-review registry as the quality bar (awesome-skills).** Its rubric is the best
governance artefact in the collection and I take Stage 4's eleven security classes verbatim — but
Stage 3, the only stage that *runs* the thing, is explicitly optional, and duplicate judgment
requires a human who can see the whole queue. That is a 13-item process. I invert it: the kit is
mandatory and blocking; human review becomes the non-blocking quarterly rot sweep its own
`revalidate_catalog.py` already models (exit 0, deduped by subject, "unverifiable" separate from
"broken").

**Marker's Provider/Builder/Processor/Renderer unit taxonomy as the plugin shape.** The four-role
split is genuinely good *internally* — I keep its spirit in the six ports — but it is not an
extension system: the roles are discovered by crawling marker's own source, third parties reach it
only through the dotted-path RCE channel, and Office formats all subclass `PdfProvider` and render
to a temp A4 PDF, which is the largest information loss in the collection. A unit taxonomy is not a
plugin system, and marker never built the second half.

**WASM-only isolation (the anydoc ideal).** Correct and beautiful for `bytes → Document` parsers,
and I ship it as the strictest tier precisely because anydoc proves it — a parser that must compile
to `wasm32-unknown-unknown` cannot grow a network call by accident. But it cannot host a GPU
embedder or a hosted-API generator, so it is a mode, not the model.

**Doing nothing — one ABC and a dict, decide later.** This is the option the judge should weigh most
seriously, because it is cheap. I reject it because the three properties that are impossible to
retrofit are exactly the three this design exists for: *discovery without import* (retrofitting it
means changing every driver), *licence facts on the descriptor* (retrofitting means re-auditing
every driver at the moment a lawyer asks), and *conformance-signed quality numbers* (retrofitting
means every existing card's numbers are unverifiable forever). Registries can be rewritten;
ecosystems cannot be re-onboarded.
