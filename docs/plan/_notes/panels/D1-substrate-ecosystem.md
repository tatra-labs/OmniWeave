# D1 — Language, runtime substrate, repository/package layout

**Panel:** D1 · **Seat:** the ecosystem and operator advocate · 2026-09-01

---

## Headline

**Three languages, three *published-artifact* boundaries, one monorepo: a fuzzed Rust kernel that owns
bytes, identity and the store and ships as an `abi3` wheel + a napi addon + a wasm module from one
crate; Python as the framework, the CLI and the entire third-party extension surface; TypeScript OUT
compilers shipped as self-contained platform bundles inside Python wheels and driven over NDJSON on
stdio, so `pip install omniweave` is 25 MB, has no torch and no `node` on PATH, and parses a DOCX in
under 400 ms cold.**

The one-sentence boundary rule, which every later decision is bound by:

> **The kernel owns bytes, identity and the store. Python owns policy, models and drivers.
> TypeScript owns targets that only exist in TypeScript.**

---

## 1. Design

### 1.1 Why three languages, and why the seams are where they are

The evidence does not permit a single-language answer.

- **Office ingest in milliseconds requires a compiled decoder.** anydoc is eight Rust modules with
  single-digit-millisecond warm conversions on office formats (`_index/comparisons.md:48-59`), and it
  is *the only fuzzed parser in the collection* — 12 `cargo-fuzz` targets with their own lockfile,
  excluded from the workspace (`anydoc/Cargo.toml:3`, `anydoc/fuzz/`). The Python alternative is
  docling, whose DOCX reader you cannot obtain without `torch` and `torchvision` as **base**
  dependencies (`docling/pyproject.toml:50-51`) — ≈2.5–3.5 GB installed.
- **Drivers, models and orchestration must be Python.** vLLM, sglang, transformers, ollama clients,
  graphrag, LEANN, DataFlow are all Python. A driver author writing Rust is not an afternoon.
- **The OUT targets do not exist outside Node.** ppt-master is Python but open-slide is a
  pnpm/turbo TS monorepo (`open-slide/package.json`) and hyperframes is a bun workspace of 13 TS
  packages (`hyperframes/package.json`). Their compilers (Vite build, headless render, GSAP AST
  parser/writer) are not portable and must not be reimplemented.

The seams therefore are **not** "call the fast thing from the slow thing". They are three artifact
boundaries with different failure containment:

| Class | What runs there | Boundary | What earns it that boundary |
|---|---|---|---|
| **In-process, native** | tier-0 format decode, `content_digest` + normalisers, canonical-JSON hashing, the store writer (pragmas, WAL valve, claim SQL, migrations) | none — CPython extension / napi addon / wasm | Must be identical in three languages, must be ms-fast, must be memory-safe on hostile bytes. **Earned** by: fuzzed, no HTTP client, compiles to `wasm32-unknown-unknown`. |
| **In-process, Python** | router, operators, drivers, MCP handlers, CLI | none | This is the contribution surface. Nothing here needs to be fast. |
| **Child process, long-lived** | GPU model servers (vLLM / sglang / llama.cpp) | HTTP on loopback, attach-or-spawn | surya's pattern (`surya/inference/backends/spawn.py`): N light workers share one GPU, a CUDA OOM cannot kill the indexer, and `torch` is never in the core process. A clean digital document never starts a GPU server. |
| **Child process, short-lived** | OUT targets (Node), and every GPL-adjacent external binary (ffmpeg, pandoc, LibreOffice, Chrome) | **NDJSON on stdio** | Licence hygiene (we never *link* GPL), no Node in the Python process, a hung Chrome is killable, and no port means no CSRF/SSRF/auth surface at all. |

That last row is the answer to *"how are the TS OUT compilers invoked without forcing Node on every
user."* Not "require Node ≥ 20". Not "shell out and hope". **We vendor Node.**

### 1.2 The kernel: `omniweave-kernel`

**Start as a vendored fork of anydoc at a pinned SHA** (MIT, `anydoc/LICENSE`), not a floating
dependency. The risk digest's rule for graphify applies identically here — a single-vendor,
recently-funded project on the critical path gets vendored with its header and a NOTICE row, never a
`Cargo.toml` version range. What that buys on day one:

- `src/error.rs` — `ConvertError` with a stable machine `code()`, `is_fatal()`, `Encrypted`,
  `NeedsOcr{pages, page_count}`. Errors as branchable routing data, unit-tested because the bindings
  publish them.
- `src/limits.rs` — 12 fixed non-configurable caps enforced at the read boundary (128 MiB/entry,
  512 MiB/archive, 100k entries, XML depth 256, 2M nodes, 4M grid slots, 4M expansion cells,
  64 MiB duplicated text, 128 MiB assets).
- `fuzz/` — 12 targets and seeds, one per format handler.
- The **structural no-network property**: no `reqwest`, `hyper` or `ureq` anywhere in the tree
  (`anydoc/Cargo.toml` dependencies are `cfb`, `csv`, `flate2`, `encoding_rs`, `log`,
  `pdf-inspector`, `quick-xml`, `zip`). A crate that must compile to `wasm32-unknown-unknown`
  cannot grow a socket by accident.
- The **entire three-language binding scaffold and release pipeline**, which is the expensive part
  nobody budgets for (§1.6).

Four changes before it is ours:
1. **Audit or replace `pdf-inspector = "1.14.2"`** — Firecrawl's own crate, unvendored, licence and
   limit discipline unaudited (`mine-risk.md` §5.5). Put it behind a cargo feature and offer
   `pdfium` as the alternative so the decision is reversible.
2. **`limits.rs` caps become the ceiling, not the value**: effective = `min(tenant_cap, MAX_*)`, so a
   breach returns `ResourceLimit{limit: "archive_total_bytes", value: 536870912}` — a pricing signal
   that names which knob would need raising. The `MAX_*` constants stay non-configurable: a knob that
   turns off the zip-bomb cap will be turned off.
3. **Extend the document model per D2** (the closed block vocabulary, polygons, `CoordOrigin` in the
   type normalised once at ingest, `CellSlot::Origin/Covered` grid, `origin_operator`, `confidence`).
4. **Add the store**: pragma order (`busy_timeout` **first**), heal-on-open, the WAL valve,
   migrations, the FTS5 external-content table. One writer implementation for all three languages.

**Why the store is in the kernel and not in Python.** Three languages read this file: Python (the
indexer), TypeScript (an OUT target resolving citations), and the CLI/wasm. Three implementations of
pragma order, WAL healing and the claim `UPDATE … RETURNING` is three chances to get
`journal_mode`-before-`busy_timeout` wrong (codegraph #238 crashes on a contended open). The file
stays plain SQLite — anyone can `sqlite3` it read-only — but **writes go through one implementation**.

**The FFI contract: one crossing per unit, payload as one buffer.** codegraph's kernel states the
rule as "one JS boundary crossing per file" (`codegraph/codegraph-kernel/Cargo.toml` description).
Ours:

- Input crosses as bytes (`Vec<u8>`, one memcpy: ~1–3 ms for a 10 MB DOCX, negligible against parse).
- Output crosses as **one MessagePack buffer**, not an object graph. The same buffer is what goes into
  the store, what crosses to a Node target, and what `omniweave dump --json` renders. **One
  serialisation, three consumers, zero re-encode.** Python wraps it in a lazy view (decode-on-access,
  cached); msgpack decode of a ~2 MB document model is 5–15 ms and the whole-document path pays it
  once.
- **Every entry point releases the GIL.** anydoc already does this — `py.detach(|| anydoc::to_document(&data, format))` (`anydoc/python/src/lib.rs:193`), pyo3 0.29's rename of
  `allow_threads`. Consequence: a plain `ThreadPoolExecutor` genuinely parallelises tier-0 parsing.
  No multiprocessing, no pickling documents across a process boundary. This is the concrete reason
  the kernel is in-process rather than a service.

**No second kernel implementation, ever.** codegraph runs a native napi kernel *and* a wasm fallback
and pays for it with a `kernel-grammar-parity` test asserting node-kind-table equality between them
(`codegraph/codegraph-kernel/Cargo.toml` comment) — an entire CI gate whose only job is keeping two
readers of hostile bytes honest. Instead: **one implementation, three delivery vehicles.** If no
wheel exists for a platform, the sdist builds with a Rust toolchain, and `omniweave[kernel-wasm]`
runs the *same* wasm artifact we already build for the browser through `wasmtime-py`. Slower vehicle,
identical semantics, zero parity surface.

### 1.3 Python: the framework and the whole extension surface

`omniweave-core` (pure Python, `py3-none-any`) holds the operator contract, the registry, the
router, `RunContext`, the cache, the middleware stack, freshness, and the driver/target loaders.
`omniweave-cli` holds the CLI and `init`/`doctor`/`uninstall`. `omniweave` is a meta-distribution
that pins both `== RELEASE`.

**The hard weight invariant.** `omniweave-core`'s transitive closure contains none of: `torch`,
`torchvision`, `onnxruntime`, `numpy`, `transformers`, `vllm`, `sglang`, `tensorflow`, `jax`,
`pymupdf`, `PyPDF2`. Against the measured baselines: docling ≈2.5–3.5 GB (torch is a *base* dep),
`leann-core` requires torch **and** AGPL PyMuPDF **and** archived PyPDF2 (`LEANN/packages/leann-core/pyproject.toml:24,37,38`), local-deep-research 90 direct deps ≈4–6 GB, markitdown "6 deps" that is really ≈150–250 MB because `magika~=0.6.1` pulls onnxruntime + numpy
(`markitdown/packages/markitdown/pyproject.toml:30`). **Our number: ≤ 25 MB installed, ≤ 8 MB of
wheels, and `import omniweave` touches zero third-party modules.**

**The extras list is the design, not a footnote.**

```
omniweave                  core + cli.                     ~25 MB    no models, no Node, no torch
omniweave[office]          EMPTY, and documented as empty  0 MB      office formats are the kernel
omniweave[pdf-native]      pdfium binding                  ~12 MB
omniweave[serve]           MCP + HTTP server               ~6 MB
omniweave[out-pptx]        target-pptx + nodert            ~62 MB
omniweave[out-deck]        target-deck + nodert            ~62 MB    (+ a SYSTEM browser, probed)
omniweave[out-video]       target-video + nodert           ~62 MB    (+ SYSTEM ffmpeg, probed)
omniweave[out]             all three targets + one nodert  ~85 MB
omniweave[vectors]         index-vector (numpy allowed here)
omniweave[graph-llm]       extract-llm (no local model)
omniweave[kernel-wasm]     wasmtime fallback               ~12 MB
omniweave[recommended]     core+cli+serve+out+pdf-native   ~120 MB
omniweave[vision]          driver-olmocr (torch, vLLM)     ~2.5-3 GB — stated in the extra's own docs
```

Two deliberate, checkable choices:

- **`omniweave[office]` exists and is empty.** It is the extra people will try to install; its being
  a no-op that prints "office formats are built in — nothing to install" is the fastest way to teach
  that tier 0 is free.
- **There is no `[all]`.** DataFlow's `all` is how you get twenty extras with **four mutually
  incompatible vLLM ranges** where `[kbc]` + `[mineru]` is unsatisfiable
  (`DataFlow/pyproject.toml`, `mine-runtime.md` §1.10). A CI check fails the build if an extra named
  `all` or `everything` is ever added. `[recommended]` is the aggregate, and it contains no GPU-class
  download.

**Third-party drivers are separate distributions in separate repos**, discovered by entry point —
with the one fix that turns markitdown's footgun into an explicit act.

markitdown's plugin system is `[project.entry-points."markitdown.plugin"]`
(`markitdown/packages/markitdown-ocr/pyproject.toml:56`) resolved with
`entry_points(group="markitdown.plugin")` (`markitdown/packages/markitdown/src/markitdown/_markitdown.py:75`). It works — and it is exactly why `markitdown-ocr` puts **AGPL PyMuPDF in your
process invisibly the moment it is installed** (`markitdown/packages/markitdown-ocr/pyproject.toml:31`). So:

> **A driver discovered by entry point is never loaded unless it is listed in
> `omniweave.toml`'s `[drivers]` table.** A discovered-but-unlisted driver is reported by
> `omniweave doctor` as `available, not enabled` with its declared licence, and is not imported.

One table, and installation stops being consent.

**A driver declares its capabilities without being imported.** Not a hand-written prose blob
(DataFlow's 171 hand-maintained `get_desc(lang)` strings with nothing checking them), and not an AST
scrape (DataFlow's `LazyLoader`, which the runtime notes reject). Instead: an
`omniweave-driver.toml` shipped as package data, read with `importlib.resources` — **zero import of
the driver module**, so `omniweave doctor`, `--dry-run` and cost estimation all work with `torch`
uninstalled. Shape in §2.3.

**The afternoon test, concretely.** `omniweave new driver mydriver` scaffolds a repo with the class,
the manifest, a GitHub workflow, and `pytest --omniweave-driver mydriver` wired to
`omniweave-testing` — ~40 shared conformance tests: idempotence (run twice, equal rows),
`StepResult` shape, `FAILED_TRANSIENT` implies `retry_after`, error codes resolve in `codes.toml`,
limits actually refuse the fuzz corpus, licence declared, **and no socket opened under a
socket-blocking fixture**. A third party proves their driver correct without reading our source.
This is the highest-ROI artifact in the whole proposal.

### 1.4 TypeScript: a target, not a layer

**Each OUT target is a Node application bundled with its own Node runtime and published as a Python
wheel.** codegraph already ships exactly this and documents why it works
(`codegraph/BUNDLING.md`):

- Node 22.5+ has built-in `node:sqlite` **with WAL and FTS5**, so `better-sqlite3` is gone and there
  are **zero native addons**. Consequence, quoted: *"building a bundle is pure file-packaging — any
  target builds on any OS (the whole matrix builds on one Linux runner)."* Six targets:
  `darwin-{arm64,x64}`, `linux-{x64,arm64}`, `win32-{x64,arm64}`.
- Distribution today is npm `optionalDependencies` with `os`/`cpu` keys plus a `curl | sh`
  installer. **We invert the channel and keep the bundle:** one shared wheel
  `omniweave-nodert` with a platform tag (`macosx_11_0_arm64`, `manylinux_2_17_x86_64`,
  `win_amd64`, …) carrying the vendored Node, and each `omniweave-target-*` wheel is pure JS
  depending on it. Install `omniweave[out]` and all three targets share **one** ~50 MB Node payload.
  No `node` on PATH, no npm resolution at install time, no Node-version dependence.
- codegraph's recorded Windows scar, which we inherit for free: modern Node throws `EINVAL` when
  asked to spawn a `.cmd`/`.bat`, so the launcher invokes `node.exe` against the app entry directly.

**Chrome and ffmpeg are never bundled.** hyperframes' Lambda zip is ≈212 MB — Chrome 70 MB +
`ffmpeg-static` 80 MB + `ffprobe-static` 62 MB — and `ffmpeg-static` is a **libx264 build, i.e. a
GPL-2.0-or-later binary redistributed inside a deploy artefact carrying no ffmpeg NOTICE**
(`hyperframes/packages/aws-lambda/package.json`). Our rule, three parts: probe the system binary,
report its encoders, **refuse rather than substitute**. Default codec VP9/WebM or AV1; H.264 is an
operator-owned opt-in. Same for pandoc (ppt-master declares it external — correct;
local-deep-research bundles `pypandoc-binary` — not).

**The protocol is NDJSON on stdio**, `ow-target-protocol/1`, defined in §2.4. Why not HTTP: a local
server that writes source files is a CSRF target from any page the user has open — open-slide needed
a 76-line `request-guard.ts` for exactly this. Why not a socket: LEANN's embedding server is a ZMQ
REQ/REP on a **dynamic loopback TCP port with no auth**, so any local process on a shared CI runner
can submit work; the fix people reach for is a UDS with 0600, and stdio to a child you spawned is
strictly better than either because **there is no name to bind at all**. Why NDJSON and not msgpack
for control: you can `cat` a protocol trace. The document payload *is* msgpack, referenced by path
in a per-invocation `workdir`; **blobs never travel on stdio** (§2.4, S15).

### 1.5 Monorepo, and the two version axes

**One monorepo. Three workspaces, three committed lockfiles.**

- Python: `uv` workspace. Precedent in-collection: graphrag's `[tool.uv.workspace] members = ["packages/*"]` over an 8-package split of exactly our shape
  (`graphrag/pyproject.toml`), and that split is a measured weight win — `pip install graphrag-chunking` resolves to **two** transitive packages (`graphrag-common`, `pydantic`;
  `graphrag/packages/graphrag-chunking/pyproject.toml:32-35`), not the whole spaCy/nltk/Azure stack.
- Rust: `cargo` workspace with binding crates as members and `fuzz` **excluded** (anydoc's exact
  layout: `members = ["node", "python", "wasm"]`, `exclude = ["fuzz"]`).
- TypeScript: `pnpm` + `turbo` (open-slide's stack). The TS surface is a *build input*, not a dev
  loop; pnpm's lockfile is the one every audit tool reads.

**Why not polyrepo.** anydoc needs a 5-location version gate (`scripts/check-versions.sh`) inside
*one* repo, because Cargo.toml × 3, package.json and a generated `node/index.js` guard already drift.
N repos sharing an FFI ABI multiplies that by N and makes an atomic breaking change impossible.
Third-party drivers *are* polyrepo — that is the right place for it, and it is why §1.3's compat
promise is an ABI integer rather than a release number.

**Two version axes, and this is the upgrade-path answer:**

| Axis | Form | Scope | Enforced by |
|---|---|---|---|
| `RELEASE` | semver, one tag, one changelog | every **first-party** distribution pins `== RELEASE` to its siblings | `scripts/check-versions.sh` over all N declaration sites, run in the release gate job (anydoc's script, generalised) |
| `OW_ABI` | small int | the FFI/kernel surface | a compat CI job that installs the previous **two** releases' driver-template wheels against HEAD |
| `SCHEMA_VERSION` | small int | the document model + store schema | generated-artifact byte-diff + a migration test |

A third-party driver declares `requires_abi = 3`, `requires_schema = 2` — **not** a release range. A
driver published in March keeps working in September unless we bump an integer, and bumping one is a
deliberate, announced, migration-guided act. Cost of one-version-for-the-monorepo: a driver-only fix
bumps every distribution's number. Accepted, stated, and cheaper than 14 independent version graphs
over a shared ABI.

### 1.6 The language-neutral schema: yes, and generated

The core data model **does** need a language-neutral definition — three languages and an on-disk
interchange buffer demand it — but a hand-maintained IDL is the wrong source of truth.

**Source of truth: the Rust types.** They are the ones on the hostile-byte boundary and the ones
that must be exactly right; and Rust's type system carries invariants a proto message cannot —
`CoordOrigin` in the `BoundingBox` type, `CellSlot::Origin(Cell) | Covered{origin_row, origin_col}`
with `GridBuilder` as the sole constructor (exactly-once cell addressability *by construction*).

**Generated, in CI, from those types:** JSON Schema 2020-12 (`schemars`), Python typed models,
TypeScript `.d.ts`, and the msgpack field-order table. Committed to `schema/` and gated by a
**byte-diff `--check`**. The pattern is proven in-collection: graphify's `tools/skillgen/` renders
16+ platform variants from fragments, commits the render, and gates CI on `--check`, an `expected/`
golden dir, a coverage audit and an explicit `--bless`, with a stated determinism contract ("output
is LF-newline, and no timestamp or version is ever written into a generated file"). We copy the
mechanism wholesale for schemas. Its inverse is the trap: **never ship a hand-written
machine-readable manifest** — LEANN's `llms.txt` declares 2 MCP tools while the server ships 4, and
one grep proves nothing checks it.

**The cost, stated honestly:** the block-type vocabulary is closed, so adding a block type is a Rust
PR + a codegen run + a release. That is deliberate — an open block vocabulary is how a closed
vocabulary rots (and marker's `(str, Enum)` + `auto()` giving block-type values of `"1"`, `"2"` is
the specific failure). Drivers carry `extra: map<string, Scalar>` as the escape valve, and a
vocabulary release train runs quarterly.

### 1.7 CI, wheels for three OSes, and the release gate

`abi3-py310` is non-negotiable and it is the single biggest matrix reduction available: anydoc pins
`pyo3 = { version = "0.29", features = ["abi3-py310", "extension-module"] }` with the comment
*"abi3-py310 pins the stable ABI: one wheel per platform covers every CPython from 3.10 up"*
(`anydoc/python/Cargo.toml`). **7 wheels, not 7 × 5.**

The matrix, lifted from a workflow that demonstrably ships (`anydoc/.github/workflows/release.yml`):

```
build-wheels (maturin-action, --locked):
  x86_64-unknown-linux-gnu    manylinux 2014   (glibc 2.17 floor)
  aarch64-unknown-linux-gnu   manylinux 2014   (native arm runner, no QEMU)
  x86_64-unknown-linux-musl   musllinux_1_2
  aarch64-unknown-linux-musl  musllinux_1_2
  x86_64-apple-darwin
  aarch64-apple-darwin
  x86_64-pc-windows-msvc
test-wheels: every target, Linux flavours via `docker run` (JS actions cannot run
             inside Alpine containers on arm64 runners)
build-sdist: maturin sdist  — a source install works wherever Rust does
```

Four load-bearing details we inherit rather than rediscover, each recorded as a comment in our own
workflow because each is a release-day outage:

1. *"PyPI trusted publishing is registered against this exact filename (release.yml); renaming the
   file breaks the PyPI publisher."* Trusted Publishing / OIDC — no long-lived tokens.
2. *"npm rejects provenance attestations minted on self-hosted runners"* — the publish job runs
   GitHub-hosted even when everything else does not.
3. musl aarch64 cross-compiles with Zig (`mlugg/setup-zig@v2`, pinned `0.14.1`) — a third toolchain
   in the release path, and a real maintenance cost.
4. `workflow_dispatch` is a **dry run**: everything builds and tests, publishes run in dry-run mode,
   nothing reaches a registry.

Plus a version-gate job as job #1 that fails before anything builds, and a *"already published?
skip"* probe so a re-run is idempotent.

`release.yml` is ~450 lines. That is not incidental complexity and I am not pretending it is: **one
engineer-week to stand up from anydoc's template, ~2 engineer-days per quarter thereafter.**

### 1.8 Licensing, and the gate that catches `cairosvg`

**Apache-2.0 for the whole repo, with a `NOTICE`.** Not MIT: we will vendor third-party files at
pinned SHAs (anydoc as the kernel, graphify's `security.py` as the only egress path), and
Apache-2.0's §4(b)/(d) give us the *mechanism* to do the attribution codegraph botched — 27 vendored
tree-sitter WASM grammars, 66 MB, **3 grammar LICENSE files**. MIT-licensed vendored files
(codegraph, LEANN, graphrag) compose into Apache-2.0 with their notices preserved; Apache-2.0
vendored files (graphify) compose natively.

`NOTICE`, `LICENSES/`, and `THIRD_PARTY.md` are **generated** from the three lockfiles plus the
import-graph scan, byte-diff gated. Never hand-maintained.

**The `licence-gate` CI job, four checks, each of which fails the build:**

1. Resolve the **full transitive graph** of `uv.lock` + `Cargo.lock` + `pnpm-lock.yaml` against a
   named denylist: `pymupdf`/`PyMuPDF`/`fitz`, `mineru`, `pypandoc-binary`, `ffmpeg-static`,
   `ffprobe-static`, `cairosvg`, `marker-pdf`, `surya-ocr`, `texify`, `lift`, `curl_cffi`,
   `edge-tts`.
2. **Import-graph scan against the declared set.** `cairosvg` (LGPL-3.0) is imported by
   `ppt-master/.../svg_to_pptx/pptx_package/media.py` and `visual_review.py` and appears in **no**
   requirements file. If the gate does not catch `cairosvg`, the gate is manifest-only and
   insufficient. Any import not declared → fail.
3. **No GPL/AGPL/LGPL binary inside any built artifact.** Unzip every wheel/sdist/npm tarball and
   match against a known-binary name list plus an SPDX check per file.
4. **Every vendored file has all four**: origin SHA, licence header, a parity/equality test, and a
   `NOTICE` row. Three of four is codegraph (sha in comments + parity test, no NOTICE) and
   hyperframes (arch check, no hash, no NOTICE).

Plus a ten-line metadata check: SPDX `license` must agree with the `LICENSE` file and with the
classifiers. DataFlow declares Apache-2.0 in `license` and ships a
`"License :: Free For Educational Use"` classifier — a metadata bug a legal review will find.

**Pin policy, by dependency role, mixing them silently being the failure:**

| Role | Policy |
|---|---|
| HTTP/TLS/crypto, XML/HTML/PDF parsers, template engines, browsers, archive readers, inference servers | **Floor with a CVE comment, no ceiling.** A ceiling here is an unpatchable CVE. (`pypdf` alone carries 13 advisories on one pin in local-deep-research.) |
| Tokenisers, clustering, embedding models — anything whose output is a golden test | Exact pin permitted, and it must carry a named owner, refresh procedure, review date, issue link. |
| Model weights | Exact commit SHA + file hashes. `revision="main"` is a **lint error** (docling's own field docstring says the field exists "for reproducibility" and defaults to `"main"`). |
| Vendored binaries (wasm, Node runtime, pdfium) | sha256 **+** an equality/parity test **+** an architecture assertion **+** a NOTICE entry — all four. |

Review rule, from local-deep-research: **a constraint tighter than `>=` requires a comment.**

### 1.9 Operability: install, cold start, errors, `doctor`, telemetry

**Install.** `uv tool install omniweave` · `uvx omniweave parse report.docx` (zero install) ·
`pip install omniweave`. `omniweave init` writes `omniweave.toml`, `.omniweave/`, and the MCP config
into every detected host via a registry of `AgentTarget`-shaped rows — `detect / install /
uninstall / print_config / describe_paths`, atomic write, `json_deep_equal → unchanged`, marker-
section upsert, self-healing removal of stale artefacts. **A new host is one file plus one registry
row.** graphify's 21 install destinations prove the map must be **data, not code**, and record two
constraints we inherit: the frontmatter `name` must equal the install folder name (Claude Code
requirement, graphify #1635), and Amp searches `.agents/skills`, not `.amp/skills`.
`omniweave uninstall` has full symmetry, shows what it found before deleting, with `--keep-cli` and
`--purge`.

**Cold-start budgets, as CI gates on three OSes with a recorded baseline and 20% drift tolerance**
(modelled on jcodemunch's 5% schema-token drift gate, loosened because wall-clock on shared runners
is noisier):

```
import omniweave                       ≤ 150 ms
omniweave --help                       ≤ 250 ms
omniweave parse fixture.docx           ≤ 400 ms   wall, including process start, kernel path
omniweave query "…" (warm SQLite)      ≤ 200 ms
```

The enforcement mechanism for import time is the interesting one: **no third-party import at module
scope anywhere in `omniweave.core`**, checked by importing `omniweave` in a subprocess under
`-X importtime` and failing if the loaded-module set outside the allowlist (stdlib + `omniweave.*` +
`omniweave._kernel`) is non-empty. Public-namespace ergonomics come from DataFlow's `TYPE_CHECKING`
re-export trick, which the runtime notes endorse as *"genuinely good for import time and IDE
completion."*

**Errors.** Every error carries a stable machine code, namespaced `OW-K-0xx` (kernel) / `OW-R-1xx`
(runtime) / `OW-D-2xx` (driver) / `OW-T-3xx` (target) / `OW-L-4xx` (licence & policy), living in one
`codes.toml`; `omniweave explain OW-K-012` prints the long form. Codes are **never reused or
renumbered** — a CI test asserts `codes.toml` is append-only against the previous tag. And every
message ends with **the exact command that clears it** (ppt-master's nine-value gate rule: the
failure message names the status *and prints the command*). A missing capability is never an
`ImportError` at the bottom of a stack trace: it is a **pruned plan with a report**.

**Capability probes, not import checks.** *Test that the capability works, not that the module
imports*: a `tesseract` without the language pack, a CUDA torch that fails on first kernel launch, a
`pdfium` that cannot open an encrypted PDF, an Ollama client with no model pulled all import fine.
Each probe runs the smallest real operation and caches its verdict for the run. Our own list
includes one nobody expects: **SQLite FTS5 availability** — some distro CPython builds omit it, and
"FTS5 missing" must be a named probe failure with a fix line, not a `sqlite3.OperationalError` from
inside a query.

**`omniweave doctor` is the single support artifact** — the thing you ask a user to paste into an
issue. Resolved config with per-value *source*; discovered-vs-enabled drivers with declared
licences; every capability probe with verdict and cache age; store path, `schema_version`, WAL size,
pragma readback; kernel ABI + build target + vendored-anydoc SHA; Node runtime presence and version;
every external binary with its `--version` output and encoder list; and the licence-gate summary.
Redaction rule: `$HOME`-relative paths shown; any value whose key matches `*key*|*token*|*secret*`
replaced by `sha256[:8]`.

**Logging.** Structured JSON events to stderr, human renderer on a TTY. **Never a startup banner to
stderr** — MCP hosts render *any* server stderr at error level, so a healthy attach otherwise shows
up as `[error] … undefined` every session. Timings are always on, never behind an env var.

**Telemetry: none.** No beacon, no default-on anything. `omniweave doctor` prints
`telemetry: none compiled in`, and a CI check greps every published artifact for hostname literals
against a documented allowlist. A local-first claim dies on the first default-on beacon (jcodemunch
posts token savings to a vendor URL unless disabled).

**Config.** `omniweave.toml` at the project root; a `[tool.omniweave]` table in `pyproject.toml` is
read only when no `omniweave.toml` exists; env prefix `OW_`; **every env var has a config-file
equivalent** and `omniweave show-config` prints resolved values with their source. Env-vars-only
tuning with no dump is codegraph's recorded mistake (ten-plus knobs, no effective-config output).

---

## 2. Concrete shape

### 2.1 Repository tree

```
omniweave/                                     ← ONE repo, Apache-2.0
├── LICENSE  NOTICE  LICENSES/  THIRD_PARTY.md         (last two GENERATED, --check gated)
├── Cargo.toml            [workspace] members=["kernel","bindings/*"] exclude=["kernel/fuzz"]
├── pyproject.toml        [tool.uv.workspace] members=["py/*"]
├── pnpm-workspace.yaml   packages: ["ts/*"]
├── Cargo.lock  uv.lock  pnpm-lock.yaml               (all committed)
├── codes.toml                                        ← the error-code register, append-only
│
├── kernel/                              crate omniweave-kernel   (vendored anydoc @ SHA + NOTICE)
│   ├── src/{lib,error,limits,model/,formats/,store/,digest/,render/}.rs
│   └── fuzz/                            12 targets, own lockfile, excluded from the workspace
├── bindings/
│   ├── python/     crate-type=["cdylib"]  pyo3 abi3-py310 → omniweave._kernel
│   ├── node/       crate-type=["cdylib"]  napi-rs         → @omniweave/kernel
│   └── wasm/       crate-type=["cdylib","rlib"] wasm-bindgen → @omniweave/kernel-wasm
│
├── py/
│   ├── omniweave-core/          pure Python. operator, registry, router, cache, freshness, loaders
│   ├── omniweave-cli/           the CLI: init doctor parse index query compile explain show-config
│   ├── omniweave/               META. depends: core==R, cli==R. owns [project.optional-dependencies]
│   ├── omniweave-kernel-py/     the wheel built from bindings/python  (platform-tagged, 7 targets)
│   ├── omniweave-testing/       the driver/target conformance suite. pytest plugin.
│   ├── omniweave-serve/         MCP (stdio + HTTP), hooks, llms.txt generator
│   ├── omniweave-index-vector/  numpy ALLOWED here and only here
│   ├── omniweave-extract-llm/
│   ├── omniweave-driver-pdfium/
│   ├── omniweave-driver-olmocr/ the ONLY distribution permitted to depend on torch
│   ├── omniweave-nodert/        VENDORED NODE, platform-tagged wheels (~50 MB). No Python code.
│   ├── omniweave-target-pptx/   pure-Python shim + the built JS bundle from ts/target-pptx
│   ├── omniweave-target-deck/
│   └── omniweave-target-video/
│
├── ts/
│   ├── kernel/            thin re-export of the napi addon + the generated .d.ts
│   ├── target-pptx/  target-deck/  target-video/     each: one NDJSON stdio entry point
│   └── protocol/          ow-target-protocol/1 types, generated from schema/
│
├── schema/                ← GENERATED, byte-diff gated. The language-neutral contract.
│   ├── document.schema.json      JSON Schema 2020-12   (schemars, from kernel/src/model)
│   ├── document.py               typed models
│   ├── document.d.ts
│   ├── msgpack-fields.toml       field order + tag table (wire stability)
│   └── expected/                 golden render; `--bless` to update
│
├── tools/
│   ├── schemagen/         gen.py, --check, --bless      (graphify's skillgen mechanism)
│   ├── check-versions.sh  N declaration sites must agree, and match the tag
│   ├── licence-gate/      4 checks incl. the import-graph scanner
│   └── build-noderuntime.sh   per-platform Node bundle (pure file-packaging, any host)
└── .github/workflows/
    ├── ci.yml         rust · python · node · wasm · schema-check · licence-gate · coldstart · importtime
    └── release.yml    gate → tests → 7 wheels + 6 node bundles + wasm → test → publish (OIDC)
```

### 2.2 The kernel FFI surface (the whole crossing, per language)

```rust
// kernel/src/lib.rs — the public surface. Everything else is internal.
pub fn detect(bytes: &[u8], hint: Option<&str>) -> Option<Format>;
pub fn to_document(bytes: &[u8], format: Option<Format>, limits: Limits)
    -> Result<DocumentBuf, ConvertError>;     // DocumentBuf derefs to &[u8] — ONE msgpack buffer
pub fn content_digest(bytes: &[u8], format: Option<Format>) -> Result<Digest, ConvertError>;
pub fn canonical_digest(json: &[u8]) -> Result<Digest, ConvertError>;  // allow_nan = false
pub mod store;   // open, migrate, heal_wal, claim, complete, reap_expired_leases, counts_by_status
```

```python
# omniweave/_kernel  (pyo3 abi3-py310).  EVERY entry point wraps its work in py.detach(..).
def detect(data: bytes, hint: str | None = None) -> str | None: ...
def to_document(data: bytes, format: str | None = None, limits: bytes | None = None) -> memoryview:
    """One msgpack buffer. Zero-copy. GIL released for the whole decode.
    Raises OwKernelError with .code (stable, in codes.toml) and .is_fatal."""
```

```ts
// @omniweave/kernel  (napi-rs). Same shape, same codes, generated .d.ts from schema/.
export function toDocument(data: Uint8Array, format?: string, limits?: Uint8Array): Buffer;
```

Invariant, tested: **one crossing per unit**. The extension keeps a crossing counter; a test parses a
fixture corpus and asserts `crossings == units`.

### 2.3 `omniweave-driver.toml` — the zero-import capability declaration

Shipped as package data beside the driver module, read with `importlib.resources`. Nothing in the
driver's own module is imported to answer `omniweave doctor`.

```toml
schema = 1                              # of THIS file
name   = "olmocr"                       # registry key suffix -> "parse.vlm.olmocr"
entry  = "omniweave_driver_olmocr:OlmocrDriver"

requires_abi    = 3                     # the kernel FFI surface, NOT a release number
requires_schema = 2                     # the document model version

[capability]
consumes    = ["page_image"]
produces    = ["page_text", "page_layout"]
cost_class  = "BILLED_API"              # FREE | LOCAL_COMPUTE | BILLED_API
granularity = "PART"                    # DOCUMENT | PART | CORPUS
formats     = ["pdf", "png", "jpeg", "tiff"]
deterministic = false

[[capability.probe]]                    # run the smallest REAL operation, cache the verdict per run
kind = "http_model"
url_config_key = "drivers.olmocr.endpoint"
assert = "model_id_matches"             # surya's GET /v1/models check on attach
[[capability.probe]]
kind = "python_import"
module = "torch"
assert = "cuda_kernel_launch"           # NOT "imports cleanly"

[licence]
code    = "Apache-2.0"
weights = "Apache-2.0"                  # REQUIRED when the driver downloads weights
weights_revision = "a1b2c3d4e5f6..."    # exact SHA. "main" fails the gate.
weights_sha256   = ["…"]
notice  = "NOTICE"

[egress]
default = "none"                        # none | configured_endpoint | internet
hosts   = []                            # allowlist; empty + "none" is asserted by the conformance run
```

And in the consumer's project:

```toml
# omniweave.toml
schema = 1
[store]        path = ".omniweave/index.db"
[roots]        source = "."   output = ".omniweave/out"   cache = ".omniweave/cache"

[drivers]                       # ← DISCOVERY IS NOT CONSENT. Unlisted = reported, never loaded.
enabled = ["pdfium"]            # `omniweave doctor` lists olmocr as: available, not enabled (Apache-2.0)

[targets]
enabled = ["pptx"]
[targets.video]
ffmpeg = "system"               # never "bundled"
codec  = "vp9"                  # h264 is an operator-owned opt-in
```

### 2.4 `ow-target-protocol/1` — NDJSON on stdio

One JSON object per line. stdin: parent→child. stdout: child→parent, **control only**. stderr:
logs, drained into a 4-line ring tail and surfaced with any failure (surya attaches the server's own
log tail to spawn failures; ppt-master bounds its audit transcript).

```jsonc
// → child, always first
{"t":"hello","proto":"ow-target-protocol/1","run_id":"…","workdir":"/tmp/ow-8f3a",
 "schema_version":2,"limits":{"wall_ms":600000,"rss_bytes":2147483648}}
// ← child, always first
{"t":"ready","target":"pptx","version":"0.4.1","proto":"ow-target-protocol/1",
 "capabilities":{"parse_back":true,"assets":true},
 "external":[{"name":"soffice","found":false},{"name":"ffmpeg","found":true,"encoders":["libvpx-vp9"]}]}

{"t":"validate","id":1,"il":"il/deck.msgpack"}                       // paths are workdir-relative
{"t":"progress","id":1,"pct":40,"note":"page 5/12"}                  // rate-limited to 4/s
{"t":"result","id":1,"status":"blocked","findings":[
   {"code":"OW-T-311","severity":"error","provenance":"introduced","path":"p03/title",
    "msg":"mix-blend-mode requires bake","fix":"omniweave compile --bake p03/title"}]}

{"t":"compile","id":2,"il":"il/deck.msgpack","out":"artifact/deck.pptx"}
{"t":"result","id":2,"status":"ok","artifact":"artifact/deck.pptx",
 "sha256":"…","fidelity":{"passthrough":3,"cloned_passthrough":0,"patched":1,"rebuilt":8},
 "receipt":"artifact/deck.postflight.json"}

{"t":"parse_back","id":3,"artifact":"in/deck.pptx","out":"doc/model.msgpack"}
{"t":"bye"}
```

```
exit 0  ok             exit 2  validation blocked      exit 3  resource limit
exit 4  protocol error exit 64 required capability missing (named in the last error line)
```

Rules, each with a conformance test in `omniweave-testing`:

- **Blobs never touch stdio.** Total stdout per invocation `< 1 MiB` (asserted). A target that
  writes an artifact to stdout instead of `workdir` would OOM the parent.
- The parent reads stdout on a dedicated thread into an unbounded queue; the child is killed on
  `wall_ms` and its process group is reaped. Backpressure never deadlocks the pipe.
- `hello`/`ready` exchange **both** carry `proto` and `schema_version`; a mismatch is exit 4 with a
  message naming both sides' versions.
- Child receives no environment except an explicit allowlist, and no network capability is required
  for `validate`; the conformance run executes `validate` and `compile` with sockets blocked.

### 2.5 The substrate invariants, and how each is enforced

| # | Invariant | Enforced by | Why it is needed |
|---|---|---|---|
| **S1** | `omniweave-core`'s transitive closure has no tensor/GPU/AGPL package | CI resolves `uv.lock` and fails on `{torch, torchvision, onnxruntime, numpy, transformers, vllm, sglang, tensorflow, jax, pymupdf, PyPDF2}` | docling: torch is a **base** dep (`pyproject.toml:50-51`); `leann-core` requires torch + AGPL PyMuPDF + archived PyPDF2 |
| **S2** | `import omniweave` imports zero third-party modules | subprocess `-X importtime`, allowlist = stdlib + `omniweave.*` + `omniweave._kernel` | an L5 layer must never be a dependency of an L1 parser |
| **S3** | Cold-start budgets (§1.9) hold on 3 OSes | timing gate vs a recorded baseline, 20% drift | a CLI an agent calls per turn is a per-turn tax |
| **S4** | The kernel cannot make a network call | `cargo deny` ban on `reqwest/hyper/ureq/tokio-net/socket2` **+** a `wasm32-unknown-unknown` build job | anydoc's structural property: the only parser here that *cannot* SSRF |
| **S5** | Exactly one implementation of "what do these bytes mean" | no second decoder exists; the wasm fallback is the same artifact | codegraph needs a `kernel-grammar-parity` CI gate to keep two honest |
| **S6** | Every kernel entry point releases the GIL | a threading test asserting ≥ 0.7 × N scaling to 8 threads | `py.detach` in `anydoc/python/src/lib.rs:193` is what makes a thread pool work |
| **S7** | One FFI crossing per unit; payload is one buffer | a crossing counter in the extension + a fixture-corpus assertion | an object-graph return is the whole FFI cost |
| **S8** | A driver is loaded only if listed in `[drivers]` | the loader; a test installs a rogue dist and asserts not-loaded **and** reported | `markitdown-ocr` self-registers via `markitdown.plugin` and drags AGPL PyMuPDF in invisibly |
| **S9** | A driver's capabilities are readable without importing it | `omniweave doctor` runs with the driver module blocked by a raising meta-path finder | a plan must be prunable and priceable with torch uninstalled |
| **S10** | Version, SPDX and classifiers agree everywhere | `check-versions.sh` over all N sites + a metadata check | anydoc needs this for 5 sites in 1 repo; DataFlow ships a contradictory classifier |
| **S11** | No GPL/AGPL/LGPL code or binary in any published artifact | the 4-check `licence-gate`, incl. the **import-graph** scan | `cairosvg` is imported by ppt-master and declared nowhere — the proof manifest scanning fails |
| **S12** | No network egress compiled into any artifact | hostname-literal grep vs allowlist + socket-blocked conformance run | jcodemunch beacons token savings to a vendor URL unless disabled |
| **S13** | No aggregate extra named `all`/`everything` | a check on `omniweave/pyproject.toml` | DataFlow: 20 extras, 4 incompatible vLLM ranges, `[kbc]`+`[mineru]` unsatisfiable |
| **S14** | Error codes are stable and append-only | diff `codes.toml` against the previous tag | anydoc's codes are unit-tested *because* the bindings publish them |
| **S15** | Targets never move blobs over stdio | protocol conformance: stdout < 1 MiB/invocation | a 200 MB artifact on stdout OOMs the parent |
| **S16** | A driver built against ABI *n* still loads at *n* | a compat job installing the previous **two** releases' driver-template wheels against HEAD | this is the entire third-party upgrade promise |
| **S17** | Every generated artifact is byte-reproducible | `--check` byte-diff, sorted collections, LF newlines, no timestamps in generated files | graphify's skillgen determinism contract, verbatim |

### 2.6 The costs, priced

| Item | One-off | Ongoing |
|---|---|---|
| Kernel: vendor anydoc, rebrand, audit `pdf-inspector`, clamp limits, add store + model | **~3 eng-weeks** (greenfield: ~10) | ~1 eng-day/mo tracking upstream anydoc for fixes |
| Release pipeline (7 wheels, 6 Node bundles, wasm, OIDC, version gate) | ~1 eng-week from anydoc's template | ~2 eng-days/quarter (runner images, pyo3/Zig bumps) |
| `schemagen` + byte-diff gate + 3 generated targets | ~1 eng-week | ~0 |
| `omniweave-nodert` bundling (6 platforms) | ~1 eng-week from `BUNDLING.md` | ~1 eng-day per Node LTS bump |
| `omniweave-testing` conformance suite + driver template | ~2 eng-weeks | grows with the contract |
| `licence-gate` incl. the import-graph scanner | ~1 eng-week | ~1 eng-day/mo triage |
| **Substrate total before the first driver** | **~9–10 eng-weeks** | ~4 eng-days/mo |

| Runtime / footprint | Number |
|---|---|
| FFI in-crossing, 10 MB DOCX | 1 memcpy, ~1–3 ms |
| msgpack decode, ~2 MB document model | 5–15 ms, paid once per document |
| Target child spawn (vendored Node, no npm resolution) | 60–120 ms — per *artifact*, never per request |
| `omniweave-core` installed | ≤ 25 MB · wheels ≤ 8 MB (kernel `lto="thin"`, `strip="symbols"`) |
| `omniweave[recommended]` installed | ≈120 MB |
| `omniweave[vision]` installed | 2.5–3 GB, stated in the extra's own documentation |
| Core process RSS, indexing | 45–60 MB + kernel peak bounded by `limits.rs` |
| Target child RSS | 80–150 MB (Node); + a **system** browser for the deck/video targets |
| Wheel matrix | **7** (abi3-py310), not 7 × 5 |

Operational burden: one SQLite file, no service, no listening port by default, `omniweave doctor` as
the single support artifact, upgrade is `uv tool upgrade`, rollback is pinning `RELEASE`.

---

## 3. Rationale

Five claims, each resting on something checkable.

**1. The fast/rich/target split is not a preference, it is what the evidence forces.** Every repo
that tried to be one language at this scope either paid in weight or in loss. docling is Python and
so `pip install docling` is 2.5–3.5 GB *for a DOCX reader*. marker is Python and so its office path
renders DOCX/PPTX to a temp A4 PDF and re-parses it with a layout model — speaker notes, comments,
tracked changes, OMML math, numbering restarts and the true reading order are destroyed *before
parsing begins*, the single largest information loss in the collection. codegraph is TypeScript and
still had to write a Rust napi kernel *and* vendor a Node runtime to be operable — it converged on
this split from the other side.

**2. The kernel earns in-process residency by *provable* properties, not by being fast.** The three
gates are fuzzed, no-HTTP-client, and wasm-buildable. That last one is not a feature request, it is
an enforcement mechanism: a crate that must build for `wasm32-unknown-unknown` cannot grow a socket
without failing CI. anydoc is the only fuzzed parser in the collection and the only one that
structurally cannot SSRF. If a component cannot pass those three gates, it does not go in-process,
and the model servers are the worked example — they go in a child process because `torch` failing a
CUDA kernel launch must not take the indexer with it.

**3. Discovery is not consent, and this is the single most important ecosystem-safety decision
here.** `pip install markitdown-ocr` puts AGPL PyMuPDF in your process via an entry point you never
named, and neither package's SPDX metadata reveals it. Docling's pluggy entry point has the same
shape. Our `[drivers] enabled = [...]` table costs one line of config and converts a silent
supply-chain event into an explicit act — while `omniweave doctor` still *tells* you the driver is
there, with its licence, so the ergonomics do not suffer.

**4. Vendoring the Node runtime is how the OUT direction stops being a second install story.** The
alternatives are worse in ways that are already documented: require Node (a Python user who wants a
PPTX now has a Node version problem), reimplement the compilers (three teams' work, and hyperframes'
GSAP AST parser/writer is not portable), or bundle GPL binaries (hyperframes' 212 MB Lambda zip with
a libx264 `ffmpeg-static` and no ffmpeg NOTICE). codegraph proves the bundle is cheap *because*
Node 22.5+ removed the last native addon: "any target builds on any OS." One ~50 MB
`omniweave-nodert` wheel shared by three targets is the whole cost.

**5. Generated artifacts everywhere a human would otherwise hand-maintain a contract.** Schemas,
`NOTICE`, `THIRD_PARTY.md`, `llms.txt`, the MCP instructions, the driver catalog. The pattern comes
from graphify's `skillgen` (fragments → render → committed → `--check` byte-diff → `expected/` →
`--bless`), and its inverse is LEANN's `llms.txt`, which claims 2 MCP tools while the server ships 4
and nothing checks it. A hand-written machine-readable manifest is a lie with a delay fuse.

---

## 4. Tradeoffs

1. **The kernel is a contribution bottleneck for the closed vocabulary.** A new block type is a Rust
   PR + codegen + a release across three languages: hours becomes days. Mitigated by `extra` maps on
   blocks, a quarterly vocabulary train, and the rule that *drivers never need it* — but it is real,
   and if D2 chooses an open block vocabulary this substrate is wrong and must be re-argued.
2. **The release pipeline is ~450 lines of YAML and three toolchains** (cargo, maturin, Zig for musl
   aarch64) with a hard failure mode: a `pyo3` major bump, a Rust edition bump, or a deprecated
   runner image breaks release day. 2 eng-days/quarter, and one person must own it.
3. **Two runtimes on disk.** `omniweave[recommended]` puts CPython, a vendored Node and a Rust native
   extension in one venv. Someone will open an issue titled *"why does a document parser install
   Node."* The answer is in `doctor` output and in the docs; the annoyance is permanent.
4. **One monorepo version means noisy version numbers.** A driver-only fix bumps all 14 first-party
   distributions. The compensation is that `OW_ABI`/`SCHEMA_VERSION` are the numbers third parties
   actually pin, so the noise is internal.
5. **No pure-Python fallback for the kernel.** An air-gapped s390x build farm with no Rust toolchain
   cannot install omniweave except via `wasmtime-py`. I am choosing one correct reader of hostile
   bytes over two readers with a parity test, and paying for it in platform reach.
6. **Rust staffing.** The kernel needs someone who can write unsafe-free Rust and read a fuzz crash.
   For a two-Python-engineer team this design is wrong; for a team that can hire one Rust engineer it
   is the cheapest correct option.
7. **`[drivers] enabled` adds a step.** `pip install omniweave-driver-x` then edit a TOML is one more
   action than magic auto-registration. `omniweave doctor` printing the exact line to add, and
   `omniweave enable driver x` writing it, is the mitigation — not a removal of the requirement.
8. **msgpack as the interchange buffer is one more format to debug.** Mitigated by
   `omniweave dump --json`, but a `grep` over a document model no longer works.

---

## 5. Failure modes

1. **A Rust panic in the kernel aborts the CPython process.** A panic across the FFI boundary is
   UB-adjacent and pyo3 converts it to `pyo3_runtime.PanicException`, but a panic inside a
   `py.detach` block on a worker thread can still take the interpreter down — and the fuzzer's whole
   job is finding panics. Mitigation: `panic = "abort"` is **banned** in the kernel profile, every
   entry point wraps its body in `catch_unwind` and maps a panic to
   `ConvertError::Internal{code:"OW-K-099"}` with the fuzz seed recorded; a CI job asserts a
   fuzz-crash input yields an exception, not a process exit. The residual risk is a stack overflow on
   deep XML, which `catch_unwind` cannot catch — hence the depth-256 cap being non-configurable.
2. **The input that breaks it: a 900 MB PPTX with 40,000 embedded media parts.** The fixed caps
   refuse it (`archive_total_bytes`, `entry_count`), correctly and typed — but the document is
   *legitimate*, and today the only remedy is a fork, because making `MAX_*` configurable forfeits
   the property that earned the kernel its in-process seat. `min(tenant_cap, MAX_*)` clamps *down*,
   never up. A large-corpus customer will hit this and the answer will be unsatisfying.
3. **`abi3` locks us out of newer CPython C-API features and hides a subtle break.** A CPython
   release that changes stable-ABI behaviour (not signature) ships a wheel that loads and misbehaves.
   Mitigation: the test-wheels matrix runs the newest and oldest supported CPython against the
   *same* wheel; but the failure would be silent between releases.
4. **Backpressure deadlock in the target protocol.** A target emitting progress faster than the
   parent drains fills the OS pipe buffer and both sides block. Mitigated by a dedicated reader
   thread, a 4/s progress rate limit and a `wall_ms` kill — but a target that ignores the rate limit
   (a third-party target) reintroduces it, so the conformance suite must measure line rate, and
   a third-party target that skips conformance can still hang a production run.
5. **`omniweave-nodert` platform-tag misses.** A platform tag that resolves on a host where the
   vendored Node cannot actually execute (glibc older than the build's floor, a musl host matching a
   manylinux tag through a mis-set `pip` config) yields an `ENOENT`/`GLIBC_2.28 not found` at compile
   time, not install time. Mitigation: `omniweave doctor` executes `node --version` from the
   bundle and reports it as a probe; the failure surfaces in `doctor` rather than mid-render.
6. **The import-graph scanner produces false positives and gets disabled.** A dynamic
   `importlib.import_module(name)` or an optional import inside a `try` is unresolvable statically;
   too many false positives and someone adds `--warn-only`. Mitigation: an
   `allowed-undeclared.toml` with a required justification string and a review date per row, and the
   gate fails on a row past its review date. If that file grows past ~15 rows the gate has failed
   socially even while passing mechanically.
7. **The vendored anydoc fork diverges and we stop pulling upstream fixes.** This is the standard
   fate of vendored forks, and the cost lands exactly on the fuzz-found parser bugs we most want.
   Mitigation: a monthly `upstream-diff` CI job that fails if the delta grows without a recorded
   rationale, and keeping our changes in separate modules where possible.
8. **`schema_version` and `OW_ABI` drift out of the driver ecosystem's reach.** If we bump either
   more than about once a year, third-party drivers rot and the ecosystem thesis dies. There is no
   mechanism that prevents this — only the compat CI job that makes the breakage visible, and the
   discipline to treat a bump as a product event.
9. **`doctor` output as an exfiltration surface.** We ask users to paste it into public issues. The
   redaction rule covers `*key*|*token*|*secret*`, but a custom endpoint URL with an embedded
   credential, or a corpus path naming a client, leaks. Mitigation: `doctor --redact-paths` and a
   printed warning above the output; the default still shows paths, which is a deliberate
   usability-over-privacy choice and could be judged wrong.

---

## 6. Why I reject the alternatives

**A. Pure Python, everything.** The requirement is office ingest in milliseconds; docling's Python
office path costs torch as a *base* dependency and marker's costs the entire logical structure of the
document (DOCX → mammoth → HTML → weasyprint → temp A4 PDF → layout model). Worse for my prior: a
Python parser on hostile bytes has no fuzzing story comparable to 12 `cargo-fuzz` targets, and a
zip-bomb cap expressed as a Python config value is a knob someone turns off — markitdown's
default-registered `ZipConverter` has no entry cap, no size cap, no total cap, no recursion-depth
counter and no path sanitisation.

**B. Pure Rust, Python as a thin binding.** Kills the ecosystem thesis outright. Every model runtime
and every retrieval library in the gravity well is Python; a driver in Rust is not an afternoon; and
the OUT targets *do not exist* in Rust. It also puts the closed-vocabulary bottleneck on the driver
surface, which is exactly where it must not be.

**C. TypeScript as the primary language.** No VLM ecosystem, and the parse/index gravity is Python
(docling, graphrag, LEANN, DataFlow). codegraph is the strongest TS-primary example in the collection
and it needed a Rust napi kernel plus a vendored Node runtime to be operable — it converged on my
split from the other direction, which is corroboration, not a counterexample.

**D. Polyrepo.** anydoc needs a 5-location version-agreement script *inside one repo* because
`Cargo.toml` × 3, `package.json` and a generated `node/index.js` guard already drift. N repos over a
shared FFI ABI multiplies that and makes an atomic breaking change impossible — you cannot land a
`SCHEMA_VERSION` bump across kernel, core, three targets and the schema artifacts in one reviewable
commit. Third-party drivers *are* polyrepo; that is where the model belongs, and the ABI integer is
what makes it work there.

**E. One fat package with extras.** DataFlow's receipt: twenty extras, four mutually incompatible
vLLM ranges, `pip install DataFlow[kbc,mineru]` unsatisfiable, and a `requires-python = ">=3.7"`
floor that is a lie by three minor versions with nothing testing it. graphrag's opposite move is the
measured win: an 8-package split where `graphrag-chunking` resolves to two transitive packages.

**F. Process-isolate everything (a parse service, gRPC between layers).** Cold start. A per-document
HTTP hop turns a 5 ms DOCX into a 50 ms one and buys a port, an auth story, an SSRF surface and a
second failure mode for zero benefit. LEANN's unauthenticated loopback ZMQ embedding server is what
this looks like when done casually. Process isolation is for things that can kill you (a CUDA OOM) or
that must not be linked (GPL binaries) — not for things that are merely in another language.

**G. A hand-written language-neutral IDL as the source of truth** (protobuf, Cap'n Proto, or a
bespoke `.owschema` DSL). A fourth toolchain, and it relocates the authoritative definition to a
place that cannot express the invariants the hostile-byte boundary needs: `CoordOrigin` inside the
`BoundingBox` type, and `CellSlot::Origin(Cell) | Covered{origin_row, origin_col}` with
`GridBuilder` as the sole constructor, which is the only table model in the collection that can
answer "which cell is above this one" *by construction*. Generate the neutral artifacts **from**
Rust and byte-diff them in CI; you get the cross-language contract without a fourth language.

**H. A second, pure-Python (or separately-written wasm) kernel as a fallback.** codegraph runs a
native kernel and a wasm fallback and pays with a `kernel-grammar-parity` test whose only job is
asserting two implementations agree — and the risk digest calls that repo "the best process and the
worst attribution in the collection," i.e. even a careful team cannot make dual implementations
cheap. Two readers of hostile bytes is two attack surfaces and two fuzz corpora. One implementation,
three delivery vehicles.

**I. `uv`/`pip` auto-discovery of drivers with no allowlist** (docling's and markitdown's model). It
is more convenient by exactly one config line and it is how AGPL code enters your process without
appearing in any SPDX field. Rejected on the strength of that one worked example.

---

## 7. Names coined here, for the record

Later panels are bound by these; each is chosen to read well ten thousand times.

| Name | What it is |
|---|---|
| `omniweave` | the meta-distribution and the CLI (with `ow` as an installed alias) |
| `omniweave-kernel` | the Rust crate; `omniweave._kernel` in Python, `@omniweave/kernel` on npm |
| `omniweave-core` | the pure-Python framework: operator, registry, router, cache, freshness |
| `omniweave-cli`, `omniweave-serve`, `omniweave-testing` | CLI · MCP/HTTP · the conformance harness |
| `omniweave-driver-<name>` | an IN driver distribution (third-party or first-party) |
| `omniweave-target-<name>` | an OUT target distribution |
| `omniweave-nodert` | the vendored Node runtime, platform-tagged wheels |
| `omniweave.drivers`, `omniweave.targets`, `omniweave.operators` | entry-point groups |
| `omniweave-driver.toml` | the zero-import capability + licence + egress declaration |
| `omniweave.toml` · `[tool.omniweave]` · `OW_` · `.omniweave/` | config file · pyproject fallback · env prefix · state dir |
| `ow-target-protocol/1` | the NDJSON-on-stdio contract between core and an OUT target |
| `OW_ABI`, `SCHEMA_VERSION`, `RELEASE` | the three version axes |
| `codes.toml`, `OW-K/R/D/T/L-nnn` | the append-only error-code register and its namespaces |
| `omniweave doctor`, `omniweave explain`, `omniweave show-config` | the three operator verbs |
| `schema/`, `tools/schemagen` | the generated language-neutral contract and its generator |
