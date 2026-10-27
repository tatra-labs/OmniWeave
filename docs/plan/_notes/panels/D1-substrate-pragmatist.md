# D1 — Substrate, layout, packaging — THE SHIPPING PRAGMATIST

## Headline

**omniweave is a Python 3.11+ framework in one repository as a `uv` workspace of nine
independently-versioned distributions; Rust exists only behind one already-published abi3 wheel we
do not build, and TypeScript exists only as a digest-pinned toolchain we invoke as a one-shot
subprocess — so week 4 ships `pip install omniweave && omniweave parse deck.pptx` to a real user
and omniweave itself compiles zero binary artefacts on day one.**

---

## Design

### 1. The language decision, and why it is not close

**Host language: Python. Floor: `>=3.11`. No upper bound in core.**

This is not an ecosystem-gravity hand-wave; the floor is *forced* by the two packages we most want
to reuse, and it is checkable:

- `olmocr/pyproject.toml:21` — `requires-python = ">=3.11"`. olmocr is the **only** permissive
  high-accuracy OCR in the collection: Apache-2.0 code *and* Apache-2.0 weights (risk digest §18.1),
  and it is the mandated substitute for every vetoed OCR (marker/surya/lift weights, HunyuanOCR).
- `graphrag/packages/graphrag-chunking/pyproject.toml:25` — `requires-python = ">=3.11,<3.14"`.
  `graphrag-chunking` resolves to **two** transitive packages (`graphrag-common==3.1.2` + `pydantic`;
  verified in `packages/graphrag-chunking/pyproject.toml` dependencies), which is the cheapest
  reuse in the whole collection.

So 3.11 is the intersection, not a preference. What we get for free at 3.11 that we would otherwise
carry as dependencies or polyfills: `tomllib` in the stdlib (`graphrag-common` carries `toml~=0.10`
purely for want of it), `StrEnum` (the runtime reference design's `Outcome`, `FailureClass`,
`Confidence` are all string enums — and `mine-parse.md` Traps records marker's `(str, Enum)` +
`auto()` bug where `BlockTypes` values serialise as `"1"`, `"2"`; `StrEnum` makes that bug
unwritable), `asyncio.TaskGroup` for fan-out with a deadline, `typing.Self`, and exception groups
for the "one page failed, 200 succeeded" partial-result shape.

**The upper bound is a packaging problem, and the package split is its solution.** graphrag pins
`<3.14`. If omniweave were one distribution, that ceiling would poison the whole framework: a user
on Python 3.14 could not parse a DOCX because a graph package they never use caps the interpreter.
In this design the ceiling lives *only* in `omniweave-graph`'s metadata. `omniweave-core` declares
`requires-python = ">=3.11"` with **no ceiling**, and a 3.14 user gets parse + store + serve + PPTX
and a `doctor` line saying `omniweave-graph: unavailable on CPython 3.14 (upstream cap)`.

**Rust: exactly one seam, and we do not write it in year one.**

The seam is `bytes → office document`, and it is already written, MIT, fuzzed, and shipping wheels.
`anydoc` (Firecrawl, MIT, `anydoc/LICENSE`) is:

- one root crate plus three binding member crates — `Cargo.toml` `[workspace] members = ["node",
  "python", "wasm"]`, `exclude = ["fuzz"]`;
- **`abi3-py310`** — `anydoc/python/Cargo.toml`: `pyo3 = { version = "0.29", features =
  ["abi3-py310", "extension-module"] }`, with the comment *"abi3-py310 pins the stable ABI: one
  wheel per platform covers every CPython from 3.10 up."* That is the fact that kills the
  "Rust means a wheel matrix explosion" objection: it is **7 wheels total**, not 7 × N Pythons;
- published as `firecrawl-anydoc` on PyPI (`anydoc/python/pyproject.toml`, maturin backend), and
  **the Python binding exposes the full model, not just markdown** — `anydoc/python/src/lib.rs:206`
  registers `to_document`, and `anydoc/python/anydoc/_anydoc.pyi:74-94` types it, including the
  entire error taxonomy as real Python exception classes with payloads: `NeedsOcrError.pages:
  list[int]`, `ResourceLimitError.limit: str`, `MalformedError.part`, `EncryptedError`,
  `MissingPartError.part`;
- GIL-releasing — `lib.rs:194`, `py.detach(|| anydoc::to_document(...))` — so a thread pool gets
  real parallelism from CPython without a process boundary;
- structurally incapable of SSRF: no `reqwest`/`hyper`/`ureq` anywhere (risk digest), and the
  dependency list in `Cargo.toml` is nine crates.

We take a **hash-pinned, exact dependency** on `firecrawl-anydoc==0.2.4`, we vendor its MIT source
at a recorded SHA in `vendor/anydoc/` with the NOTICE, and we write down the fork trigger. We do not
write Rust. If and when we fork, we inherit `anydoc/.github/workflows/release.yml`, which already
encodes the whole matrix (7 wheel targets with `manylinux2014` / `musllinux_1_2`, 7 Node targets
with `napi-cross` for the glibc-2.17 floor and Zig for musl) and a five-location version gate
(`anydoc/scripts/check-versions.sh`).

**TypeScript: a toolchain, never an import, never a dependency of the Python install.**

Two of three OUT targets are TS (`open-slide`, `hyperframes`) and **the flagship is not**.
`ppt-master/skills/ppt-master/requirements.txt` is the whole PPTX compiler dependency set:
`python-pptx>=0.6.21`, `XlsxWriter>=3.0.0`, `skia-pathops>=0.9.2`, `uharfbuzz>=0.50.0`, `Pillow`,
`numpy` — all pip-installable wheels, no Node, no system binary. And PPTX is the **only** target in
the collection with a working `parse_back()` (`pptx_intake.py`), i.e. the one that closes the loop.
So the highest-value OUT target is pure Python and the Node requirement is confined to
`omniweave-out-deck` and `omniweave-out-video`.

The video target genuinely cannot avoid Node: `hyperframes/packages/cli/package.json` needs
`puppeteer-core`, `@puppeteer/browsers`, `sharp`, `onnxruntime-node`, `esbuild`. That is a browser
render pipeline. Fine — it is one of nine distributions, it is opt-in, and its Node payload does not
enter a `pip install`.

### 2. Repository and package layout

**One repository. A `uv` workspace with a non-publishable root. Nine published distributions.**

Nobody in the 22 repos ships a polyrepo. Every multi-artefact project here is single-repo:
graphrag (uv workspace, `[tool.uv] package = false`, `members = ["packages/*"]`, root classifier
`"Private :: Do Not Upload"`, 8 packages), markitdown (4 packages, hatchling), anydoc (1 cargo
workspace → crates.io + PyPI + npm ×2), open-slide (pnpm + turbo), hyperframes (bun workspaces, 14
packages). We copy graphrag's root shape verbatim because it is the proven `uv` incantation.

**But we reject graphrag's version lockstep.** Every graphrag leaf pins its siblings at
`==3.1.2`, which means a chunking bugfix forces a coordinated 8-package release. That is correct for
a single-vendor monolith and wrong for a third-party driver ecosystem. Instead:

- first-party distributions depend on core by **compatible range**: `omniweave-core>=0.4,<0.5`;
- the driver ABI is a separate integer, `omniweave_core.contract.CONTRACT`, bumped only when the
  driver contract changes, and checked at load;
- one `uv.lock` at the root pins the *development* graph exactly, so a cross-package change is one
  PR and one CI run;
- one version gate (G5 below) generalises `anydoc/scripts/check-versions.sh` across every place a
  version is declared.

### 3. The nine distributions, and the weight budget

The rule from `mine-risk.md` §4.8, stated as a hard constraint rather than a preference:
*"an L5 orchestration layer must never be a dependency of an L1 parser, or every consumer of your
DOCX reader installs Chromium."* docling proves the failure: `torch` and `torchvision` are **base**
dependencies (`docling/pyproject.toml:53` region), so you cannot get docling's DOCX reader without
≈2.5–3.5 GB (≈700 MB–1 GB with `torch+cpu` pre-installed). `leann-core` requires torch **and** AGPL
PyMuPDF. local-deep-research is 90 direct deps ≈4–6 GB.

| Distribution | What it is | Dependencies | Installed ceiling (CI-gated) |
|---|---|---|---|
| `omniweave-core` | L2 model, operator contract, `work` table, cache, SQLite store, registry, limits, error taxonomy, `canonical_uri`/`content_digest`, `exttool` | **standard library only** | **2 MB** |
| `omniweave` | CLI, MCP server, hooks, installer, router, default plan | `omniweave-core`, `omniweave-office`, `mcp` | 60 MB |
| `omniweave-office` | office/text/CSV/EPUB/RTF decoder driver | `firecrawl-anydoc==0.2.4` | 15 MB |
| `omniweave-pdf` | born-digital PDF driver | `pypdfium2`, `defusedxml` | 25 MB |
| `omniweave-graph` | deterministic structure extraction, graph query | `tree-sitter`, `graphrag-chunking` | 120 MB |
| `omniweave-vision` | OCR/VLM drivers (olmocr client, layout) | `torch`, `transformers`; `[vllm]` extra | unbounded, declared |
| `omniweave-out-pptx` | PPTX target + validator + `parse_back` | `python-pptx`, `XlsxWriter`, `skia-pathops`, `uharfbuzz`, `Pillow` | 60 MB |
| `omniweave-out-deck` | HTML-deck target: **toolchain manifest only** | `omniweave-core` | 1 MB |
| `omniweave-out-video` | MP4 target: **toolchain manifest only** | `omniweave-core` | 1 MB |
| `omniweave-conformance` | pytest plugin: the driver conformance kit | `pytest` | 2 MB |

`pip install omniweave` is **≤ 60 MB and fits a 250 MB Lambda layer with room for the PDF driver**,
against markitdown's ≈150–250 MB "lightest in the collection" (its 6 declared deps hide
`magika~=0.6.1` → `onnxruntime` + `numpy`) and docling's 2.5–3.5 GB.

**`omniweave-core` has zero third-party dependencies.** Not "few" — zero. This is achievable
because everything core needs is stdlib: `sqlite3` (store + FTS5), `hashlib` (content digests),
`tomllib` (config, 3.11), `json` (canonical serialisation), `dataclasses`, `importlib.metadata`
(driver discovery), `subprocess` (the single `exttool` seam), `zoneinfo`. The one thing we give up is
`pydantic`, and we can give it up *because of a property the runtime reference design already
requires*: operator config is **flat and JSON-canonicalisable by contract** (§7.1, so
`config_digest` is computable without the operator's cooperation). Flat scalar coercion with good
errors is ~200 lines and a property test. Cost and reversal are stated in Tradeoffs.

### 4. Exactly three process boundaries, and one rejected fourth

**B1 — In-process FFI with the GIL released.** `omniweave-office` only. One call per document,
`py.detach`, real thread-pool parallelism. Cost: `anydoc/python/src/document.rs` header says *"The
document model, converted eagerly into Python objects"* and every class is `#[pyclass(frozen,
get_all)]`. So the FFI cost is **one eager marshal of the whole document per call**, not a per-block
crossing. For office formats (single-digit-ms conversions, small trees) that is the right trade. For
a 5,000-page PDF it would be catastrophic — which is exactly why PDF does **not** go through this
seam; it goes through `omniweave-pdf`'s per-page Python/pdfium path where routing is per-page
(`mine-parse.md` A2.4) and pages stream.

**B2 — Managed one-shot subprocess with a job directory.** Every non-Python toolchain (deck,
video) and every external binary (system `ffmpeg`, `pandoc`, `libreoffice`). One helper in core;
**no driver may call `subprocess` directly** (lint-enforced, invariant I14 in `mine-runtime.md`
§7.11). One process per compile, argv + a job directory + a JSON receipt on stdout.

Why one-shot and not a long-lived worker: Node cold start is 40–80 ms against a compile that costs
seconds-to-minutes, and a long-lived local server buys that 60 ms at the price of the entire
localhost-mutation surface — `mine-serve.md` §6.5 says open-slide's 76-line `request-guard.ts`
(content-type, `Sec-Fetch-Site`, literal `null` origin, `x-forwarded-proto` first comma token) is the
*minimum* for a local server that writes source files, and the notes say copy it verbatim. We would
rather not need it.

**B3 — Attach-or-spawn model server over HTTP.** GPU VLMs only, where a cold model load is tens of
seconds and amortisation is real. surya's shape is the reference and nothing else is close
(`mine-parse.md` A3.3): unlocked healthy fast path → filelock → recheck → detached spawn → JSON
sentinel → **model-id verification via `GET /v1/models` on attach** → `atexit` in the spawning
process only, with the server's log tail attached to spawn failures, and a uniform `<PREFIX>_SERVER_*`
env block. omniweave's block: `OMNIWEAVE_MODEL_SERVER_URL`, `_MODEL_ID`, `_SPAWN`, `_LOG`. Lazy spawn
is mandatory: **a clean digital document must never start a GPU server** — that is the difference
between cents and dollars per document (`framework-blueprint.md` L1).

**Rejected: a long-lived local IPC daemon for parsing or embedding.** LEANN's embedding server is a
ZMQ REQ/REP socket on a dynamic **loopback TCP port with no auth and no CURVE**, so any local process
on a shared host or CI runner can submit text for embedding (compute theft) or probe msgpack paths
(risk digest §7.3). If a future decision needs one, the substrate rule is written down now: **a unix
domain socket or named pipe at 0600, never a loopback port** — the fix nobody in the collection
applies.

### 5. Driver discovery: discoverable ≠ active

Entry points are the discovery mechanism (markitdown's `[project.entry-points."markitdown.plugin"]`
in `packages/markitdown-sample-plugin/pyproject.toml`, with the in-file comment *"IMPORTANT:
MarkItDown will look for this entry point to find the plugin"*). But markitdown also proves the
hazard: `markitdown-ocr` **hard-requires AGPL PyMuPDF** (`packages/markitdown-ocr/pyproject.toml:31`)
and *self-registers via that entry point, so it is invisible once installed*.

So the substrate rule, with teeth:

1. An entry point makes a driver **discoverable**. It never makes it **active**.
2. Activation requires the driver's name in the effective config (`omniweave.toml`
   `[drivers] enabled = [...]`) or on the command line. A discovered-but-not-enabled driver is
   reported by `omniweave doctor` as `discovered, not enabled` with its distribution name, version,
   and declared licence tier.
3. The entry point resolves to a **manifest module** whose only import is
   `omniweave_core.contract`. Capability declaration must be readable without importing the driver's
   heavy module (this is the substrate half of D3's descriptor; D3 owns the fields).
   Gate: a test imports every shipped manifest module in a subprocess with `torch`, `transformers`,
   `onnxruntime` and `puppeteer` poisoned in `sys.modules`, and asserts success.
4. `register()` **raises on a duplicate name** unless `replace=True` — closing DataFlow's registry
   keyed on bare `__name__`, first-wins, silent (`mine-runtime.md` §1.11 #5: *"Two plugins with one
   class name: one vanishes with no diagnostic"*).
5. A driver declaring a licence tier other than `permissive` is loaded only with an explicit
   `--accept-licence <tier>` and prints its SPDX plus the restriction on every run.

### 6. The core data model does **not** need a language-neutral IDL

The question deserves a direct answer: **no protobuf, no capnp, no Arrow schema, no `.proto`.**

The reason is structural, not aesthetic: **in this design the L2 document model never crosses a
language boundary.** IN is Python (with one FFI seam that already returns Python objects). OUT
targets consume an *intermediate language* — canonical SVG, TSX, HTML — which is **text on disk**,
and they consume it through a job directory. What actually crosses the Python↔Node boundary is a
~30-field job envelope and a receipt. That does not justify a codegen toolchain in three languages.

What we do instead is the pattern that is *proven* here and the anti-pattern that is *documented*
here:

- Proven: hyperframes has `scripts/sync-schemas.ts` with a `--check` mode wired into `lint`
  (`hyperframes/package.json`), i.e. schemas are **generated and CI-diffed**.
- Anti-pattern: `mine-serve.md` Traps — *"Never ship a hand-written machine-readable manifest:
  LEANN's `llms.txt` claims 2 tools, the server has 4, and one grep shows no generator, no test, no
  CI check."*

So: `omniweave schema emit` generates JSON Schema (draft 2020-12) from the Python dataclasses into
`schema/`, the files are committed, and `omniweave schema emit --check` fails CI on drift (gate G6).
The TS toolchains run `json-schema-to-typescript` against `schema/omniweave-job-v1.json` at *their*
build time. Cross-language typing at zero authoring cost, one source of truth, and a CI gate.

### 7. Cold start, and how it is held

Targets, asserted in CI as timing assertions (the same discipline as invariant I15's
`WATCHDOG_MS/2` rule):

| Measurement | Budget | Mechanism |
|---|---|---|
| `import omniweave_core` | **80 ms** | stdlib only; no `re` compilation at import; dataclasses not pydantic |
| `omniweave --help` | **250 ms** | subcommands registered by name, module imported on dispatch |
| `omniweave doctor` (cold, no drivers active) | 800 ms | capability probes cached per run |
| driver discovery (`importlib.metadata.entry_points()`) | 15 ms | reads dist-info, imports nothing |

Two mechanisms, both taken from the notes: DataFlow's `TYPE_CHECKING` re-export trick for the public
namespace, which `mine-runtime.md` §7.2 says is *"genuinely good for import time and IDE completion,
and orthogonal to the runtime registry"*; and lazy built-in registration by `match` on first request
(graphrag's `cache_factory`), which is *"strictly better than DataFlow's `LazyLoader` + AST scrape:
no AST parsing, no `sys.modules` surgery, no dependence on source layout at runtime."*

And the load-bearing consequence from §7.1.1: **a pipeline that is a 100% cache hit must load zero
models.** That is why resources come from `ctx.driver(kind)` and never from a constructor. It is the
substrate property that makes `--dry-run`, cost estimation, and free-tier auto-refresh possible at
all.

### 8. Capability probes, not import checks

`omniweave doctor` is preflight, and it runs the smallest real operation for every capability rather
than checking that a module imports (`mine-runtime.md` §7.10.3: *"Test that the capability works,
not that the module imports"*). The concrete list on day one, including two that bite the
zero-dependency core:

- `sqlite3.sqlite_version_info >= (3, 35, 0)` — the claim protocol uses `UPDATE … RETURNING`.
- **FTS5 present** — `CREATE VIRTUAL TABLE t USING fts5(x)` in a `:memory:` DB inside try/except.
  Not guaranteed by CPython's bundled SQLite on every distro build. Remedy named in the failure
  message: `pip install omniweave[sqlite]` → `pysqlite3-binary`.
- `firecrawl-anydoc` round-trips a 40-byte fixture DOCX to a `Document` with one block.
- `pypdfium2` opens an encrypted fixture PDF and raises the *expected* error (a `pdfium` that loads
  and cannot open an encrypted PDF imports fine).
- `ffmpeg` present **and reports the encoders we need** — and per the risk digest, we **refuse
  rather than substitute** if `libvpx`/AV1 are absent, and we never bundle a GPL ffmpeg
  (hyperframes' Lambda zip embeds `ffmpeg-static` ~80 MB + `ffprobe-static` ~62 MB, making it a
  GPL-2.0-or-later binary redistributed with no ffmpeg NOTICE).
- Node ≥ 20 and the toolchain digest verifies, for `out-deck` / `out-video` only.

A red probe **prunes the plan and reports it**; it never raises `ImportError` at the bottom of a
stack trace, and `sys.exit(1)` is banned in library code (graphrag's `validate_config_names` kills
the process — `mine-runtime.md` §2.12 #13).

### 9. CI: what actually gets built

**Day one, omniweave builds zero binary artefacts.** Nine pure-Python wheels (`py3-none-any`), built
once on Linux, tested on three OSes.

| Job | Matrix | Purpose |
|---|---|---|
| `gates` | ubuntu × 3.11 | G1–G8 (below). Fails fast, ~90 s. |
| `test` | {ubuntu, macos, windows} × {3.11, 3.12, 3.13} = 9 | pure-Python unit + integration |
| `toolchains` | ubuntu × node 20 | only `if: changed(toolchains/**)` |
| `build` | ubuntu × 3.11 | 9 sdists + 9 wheels, `py3-none-any` |
| `publish` | on tag `v*` | trusted publishing; gate on G5 first |

No cross-compilation, no `manylinux` container, no Zig, no maturin, no napi-cross — because our only
compiled dependency is upstream's. That is the single largest engineering cost this design avoids,
and it is the reason phase 1 is four weeks instead of six months. Total CI: 12 jobs, all under
10 minutes.

Contrast: `anydoc/.github/workflows/release.yml` is 7 wheel targets + 7 Node targets + a wasm build +
a version gate + separate test-the-artefact matrices for each. That workflow is the price of owning
a compiled core, and it is a price we defer until we have a reason to pay it.

### 10. The invariant set

| # | Invariant | Enforced by |
|---|---|---|
| **S1** | `omniweave-core` has zero third-party dependencies. | **CI gate G1**: `uv pip compile packages/omniweave-core` must resolve to exactly one distribution. |
| **S2** | No distribution exceeds its declared installed size. | **CI gate G2**: fresh venv install, sum `RECORD` sizes, compare to `tools/weights.toml`. Fails. |
| **S3** | No dependency, transitive or **undeclared**, is on the licence denylist. | **CI gate G3**: full transitive resolution **plus an import-graph scan against the declared set**. Fails, never warns. (`cairosvg`, LGPL-3.0, is imported by `ppt-master/.../svg_to_pptx/pptx_package/media.py` and declared in no requirements file — if a gate misses it, the gate is manifest-only and insufficient.) |
| **S4** | An L1 parse driver never imports an L5/serve/out module. | **CI gate G4**: module-graph walk against the declared DAG in `tools/layers.toml`. |
| **S5** | Every place a version is declared agrees, and agrees with the tag. | **CI gate G5**: `tools/check_versions.py`, generalising `anydoc/scripts/check-versions.sh` (which checks five sites). |
| **S6** | `schema/` is generated, never authored. | **CI gate G6**: `omniweave schema emit --check` byte-diff. |
| **S7** | A constraint tighter than `>=` carries a comment. | **CI gate G7** (local-deep-research's review rule, `mine-risk.md` §18.3). |
| **S8** | No ambient state: no `os.getcwd()`, `Path(".")`, bare `subprocess`, `time.time()`, `sys.exit()` inside `packages/*/src/omniweave*/`. | **CI gate G8** (ruff custom rules + a semgrep file). Invariant I14. |
| **S9** | An installed driver is discoverable but inert until named in the effective config. | Registry only calls `create()` for names in the effective config; **test** installs a rogue driver that writes a file on import and asserts the file is absent. |
| **S10** | A driver's capabilities are readable without importing the driver. | **Test**: import every manifest module in a subprocess with heavy modules poisoned in `sys.modules`. |
| **S11** | Cold-start budgets hold. | **Test**: timing assertions in `test_coldstart.py`, run on the `gates` job. |
| **S12** | A vendored artefact has sha256 + a parity test + an architecture assertion + a NOTICE entry — **all four**. | **CI gate G3b** over `vendor/` (`mine-risk.md` §18.3; codegraph has sha-in-comments + a parity test and *no NOTICE* for 24 grammars; hyperframes has an arch check and no hash). |
| **S13** | Model weights are pinned by commit SHA + file hashes; `revision="main"` is a lint error. | **CI gate G8b**. |
| **S14** | The Node toolchain is verified by its **full** digest before every invocation. | `exttool` refuses on mismatch; `--offline` refuses to fetch. (hyperframes truncates to `hash.slice(0,16)` — 64 bits, "fine against accident, weak against intent".) |

Nothing on this list is held by discipline. That column is the design.

### 11. Build order — every phase ships something a user runs

| Phase | Weeks | Content | Deliverable a real user runs |
|---|---|---|---|
| **1** | 1–4 | repo + uv workspace + `omniweave-core` (L2 skeleton, limits, error taxonomy, `canonical_uri` + `content_digest` + the racily-clean stat index, SQLite store with codegraph's pragma order) + `omniweave-office` + `omniweave parse` + G1/G3/G5/G8 | `pip install omniweave && omniweave parse deck.pptx --json` — office formats → L2 JSON in single-digit ms, typed errors, non-configurable limits |
| **2** | 5–10 | `omniweave-pdf` + the `work` table + the two-tier cache + FTS5 index + one composite MCP tool + `omniweave doctor` / `init` / `uninstall` | an agent queries a mixed PDF/office corpus and gets sourced, confidence-tagged spans |
| **3** | 11–16 | `omniweave-out-pptx` end to end, including `parse_back` | author a deck from the corpus and edit a native PPTX — **still zero Node** |
| **4** | 17–24 | `omniweave-vision` (olmocr client + B3 attach-or-spawn), `omniweave-graph` | scanned corpora and deterministic structure extraction |
| **5** | 25+ | `omniweave-out-deck`, `omniweave-out-video`, `toolchains/` | HTML decks and MP4 |

**Node enters the repository in month 6, not week 1.** Rust enters as a pinned wheel in week 1 and as
source we own only if the fork trigger fires.

---

## Concrete shape

```
omniweave/                                  # ONE repository
├── pyproject.toml                          # uv workspace root, NOT publishable
├── uv.lock                                 # one lockfile, committed
├── omniweave.toml.example
├── packages/
│   ├── omniweave-core/
│   │   ├── pyproject.toml
│   │   └── src/omniweave_core/
│   │       ├── contract.py                 # CONTRACT: int  — the driver ABI version
│   │       ├── model/                       # L2 dataclasses (D2 owns the fields)
│   │       ├── operator.py                  # OperatorABC, StepResult, RunContext
│   │       ├── registry.py                  # Registry[T], scope="run"|"shared"
│   │       ├── identity.py                  # canonical_uri, content_digest, stat index
│   │       ├── limits.py                    # fixed constants, ported from anydoc limits.rs
│   │       ├── errors.py                    # ConvertError taxonomy, .code(), .is_fatal()
│   │       ├── store/sqlite.py              # pragmas, WAL valve, work table, FTS5
│   │       ├── cache.py                     # three-group key, two-tier invalidation
│   │       ├── exttool.py                   # THE ONLY subprocess seam
│   │       ├── modelserver.py               # B3 attach-or-spawn
│   │       └── config.py                    # flat scalar coercion, ~200 lines
│   ├── omniweave/                  src/omniweave/{cli,serve,router,hooks,install}/
│   ├── omniweave-office/           src/omniweave_office/{manifest,driver}.py
│   ├── omniweave-pdf/              src/omniweave_pdf/...
│   ├── omniweave-graph/            src/omniweave_graph/...
│   ├── omniweave-vision/           src/omniweave_vision/...
│   ├── omniweave-out-pptx/         src/omniweave_out_pptx/...
│   ├── omniweave-out-deck/         src/omniweave_out_deck/{manifest,toolchain.json}
│   ├── omniweave-out-video/        src/omniweave_out_video/{manifest,toolchain.json}
│   └── omniweave-conformance/      src/omniweave_conformance/plugin.py
├── toolchains/                              # TypeScript, its own package manager
│   ├── pnpm-workspace.yaml
│   ├── pnpm-lock.yaml
│   ├── deck/    package.json  src/*.ts      # open-slide-derived
│   └── video/   package.json  src/*.ts      # hyperframes-derived
├── schema/                                  # GENERATED, committed, CI-diffed
│   ├── omniweave-doc-v1.json
│   ├── omniweave-job-v1.json
│   ├── omniweave-receipt-v1.json
│   └── omniweave-manifest-v1.json
├── vendor/                                  # third-party source at a recorded SHA
│   ├── anydoc/         SHA, LICENSE, NOTICE, .sha256
│   └── graphify-security/  security.py at a pinned SHA + NOTICE
├── tools/
│   ├── layers.toml          # the import DAG (S4)
│   ├── weights.toml         # per-distribution size ceilings (S2)
│   ├── licences.toml        # denylist + allowlist-with-justification (S3)
│   ├── gate_core_pure.py    gate_weights.py  gate_licences.py
│   ├── gate_layers.py       check_versions.py
│   └── semgrep/omniweave.yaml
├── fixtures/                 # 40-byte docx, encrypted pdf, zip bomb, 4M-cell xlsx
└── .github/workflows/{ci.yml,release.yml}
```

### Root `pyproject.toml` (graphrag's shape, verified against `graphrag/pyproject.toml`)

```toml
[project]
name = "omniweave-monorepo"
version = "0.0.0"
classifiers = ["Private :: Do Not Upload"]
requires-python = ">=3.11"

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
omniweave-core        = { workspace = true }
omniweave-office      = { workspace = true }
omniweave-pdf         = { workspace = true }
omniweave-graph       = { workspace = true }
omniweave-vision      = { workspace = true }
omniweave-out-pptx    = { workspace = true }
omniweave-out-deck    = { workspace = true }
omniweave-out-video   = { workspace = true }
omniweave-conformance = { workspace = true }

[dependency-groups]
dev = ["pytest~=9.1", "pytest-xdist", "ruff", "pyright", "semgrep", "hypothesis"]
```

### `packages/omniweave-core/pyproject.toml` — the zero-dependency core

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omniweave-core"
version = "0.1.0"
description = "omniweave substrate: document model, operator contract, store, cache, limits."
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
requires-python = ">=3.11"          # NO upper bound. See D1 §1.
dependencies = []                   # ENFORCED BY CI GATE G1. Do not add anything here.

[project.optional-dependencies]
# Only ever a capability REMEDY, never a feature. Named by the probe that fails.
sqlite = ["pysqlite3-binary>=0.5"]  # when the interpreter's SQLite lacks FTS5 or <3.35
```

### `packages/omniweave-office/pyproject.toml` — a driver

```toml
[project]
name = "omniweave-office"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "omniweave-core>=0.1,<0.2",
  # Exact pin + hash: single-vendor, 3 months old, `pdf-inspector` unaudited.
  # Fork trigger recorded in vendor/anydoc/FORK-TRIGGER.md. Owner: parse.
  "firecrawl-anydoc==0.2.4",
]

# Discoverable, NOT active. Resolves to a manifest module whose only import is
# omniweave_core.contract. Verified by test_manifests_import_light.
[project.entry-points."omniweave.driver"]
office = "omniweave_office.manifest:MANIFEST"
```

### `tools/layers.toml` — the import DAG (gate G4)

```toml
# An arrow means "may import". Anything not listed is forbidden.
# Rationale: mine-risk.md §4.8 — an L5 layer must never be a dependency of an L1 parser.
"omniweave_core"        = []
"omniweave_office"      = ["omniweave_core"]
"omniweave_pdf"         = ["omniweave_core"]
"omniweave_graph"       = ["omniweave_core"]
"omniweave_vision"      = ["omniweave_core"]
"omniweave_out_pptx"    = ["omniweave_core"]
"omniweave_out_deck"    = ["omniweave_core"]
"omniweave_out_video"   = ["omniweave_core"]
"omniweave"             = ["omniweave_core", "omniweave_office"]   # the CLI may know two things
```

### `tools/weights.toml` — the size gate (S2)

```toml
# Installed size in a fresh venv, MB. Measured from RECORD, not from the wheel.
# Ceiling rationale: markitdown core is 150-250MB and is the LIGHTEST in the
# collection; docling is 2500-3500MB because torch is a BASE dependency;
# the base install must fit a 250MB Lambda layer.
"omniweave-core"        = 2
"omniweave"             = 60
"omniweave-office"      = 15
"omniweave-pdf"         = 25
"omniweave-out-pptx"    = 60
"omniweave-graph"       = 120
"omniweave-conformance" = 2
"omniweave-out-deck"    = 1
"omniweave-out-video"   = 1
"omniweave-vision"      = 0      # 0 == declared unbounded; must print its size on install
```

### `tools/licences.toml` — the denylist that must catch `cairosvg`

```toml
mode = "fail"          # never "warn"
scan = ["resolved-graph", "import-graph"]   # BOTH. Manifest-only is insufficient.

deny_spdx  = ["AGPL-*", "GPL-*", "OpenRAIL*", "LGPL-3.0*", "SSPL*", "*-Proprietary"]
deny_names = [
  "PyMuPDF", "pymupdf", "fitz",       # AGPL; MANDATORY dep of leann-core & markitdown-ocr
  "mineru",                            # AGPL; DataFlow's PDF path
  "pypandoc-binary",                   # bundles GPL-2.0+ pandoc in a wheel
  "ffmpeg-static", "ffprobe-static",   # GPL libx264 build inside a deploy artefact
  "cairosvg",                          # LGPL-3.0; UNDECLARED import in ppt-master
  "marker-pdf", "surya-ocr", "texify", "lift",   # OpenRAIL-M weights, clause 2(c)+8
  "curl_cffi",                         # TLS-fingerprint impersonation
  "edge-tts",                          # undocumented Microsoft endpoint
]

# LGPL external binaries are permitted ONLY as a spawned process, never bundled.
external_only = ["pandoc", "ffmpeg", "libreoffice", "poppler-utils", "tesseract"]

[[allow]]
name = "pypdfium2"
reason = "pdfium is BSD-3; docling ships it under MIT (docling/pyproject.toml:53). Verify SPDX per release."
owner  = "parse"
review = "2026-12-01"
```

### `omniweave.toml` — the user-facing config

```toml
[core]
source_root = "."
output_root = ".omniweave/out"          # three roots, ALWAYS separate (§7.1.3)
cache_root  = ".omniweave/cache"

[drivers]
# Discoverable != active. A driver absent from this list is reported by
# `omniweave doctor` as "discovered, not enabled" and is never constructed.
enabled = ["office", "pdf", "out-pptx"]

[drivers.office]
type = "office"

[budget]
per_document_micros = 20_000            # a HARD currency cap, not a retry count
max_inflight = { FREE = 32, LOCAL_COMPUTE = 4, BILLED_API = 2 }

[toolchains.video]
# Pinned by FULL digest. `slice(0,16)` is weak against intent.
version = "0.1.0"
sha256  = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
node    = ">=20 <25"
```

### The B2 subprocess seam — the only place `subprocess` appears

```python
# omniweave_core/exttool.py
@dataclass(frozen=True)
class ToolSpec:
    name: str                       # "video", "deck", "ffmpeg", "pandoc"
    version: str
    sha256: str | None              # None only for a system binary located by PATH
    entry: tuple[str, ...]          # ("node", "dist/render.mjs")
    probe: tuple[str, ...]          # ("node", "dist/render.mjs", "--probe")
    node_range: str | None = None

@dataclass(frozen=True)
class ToolResult:
    outcome: Outcome                # the SAME enum as StepResult; no magic values
    receipt: Mapping[str, Any]      # validated against schema/omniweave-receipt-v1.json
    stderr_tail: tuple[str, ...]    # bounded ring: 8 samples + a 4-line tail
    ran_ms: int
    queued_ms: int                  # separate: "a contended lock and slow work are
                                    # indistinguishable from the outside" (jcodemunch §5.3)

def run(spec: ToolSpec, job_dir: Path, *, timeout_s: int, ctx: RunContext) -> ToolResult:
    """Resolve -> verify FULL sha256 -> probe (cached per run) -> spawn one-shot.

    Invariants:
      * cwd is ALWAYS job_dir, never inherited (graphify has four recorded CWD bugs)
      * env is a constructed allowlist, never os.environ
      * SIGTERM at timeout, SIGKILL at timeout + 5s, both recorded
      * a digest mismatch is FAILED_PERMANENT(failure_class=TOOLCHAIN_DIGEST), never a fetch
      * refuses rather than substitutes a codec: `libx264` absent => refuse, do not fall back
    """
```

### The job directory — the Python↔Node wire, in full

```
<cache_root>/jobs/<run_id>/<unit_digest>/
├── job.json          # written by Python, validated against schema/omniweave-job-v1.json
├── src/              # the IL: canonical SVG / TSX / HTML.  TEXT ON DISK.
├── assets/           # frozen media, content-addressed, with a ledger row each
└── out/              # written by the toolchain: the artefact + receipt.json
```

```json
// job.json  — omniweave-job-v1
{
  "$schema": "omniweave-job-v1",
  "contract": 1,
  "target": "video",
  "job_id": "01JBQ...",
  "unit": { "uri": "file:///c:/corpus/q3.pptx", "content_digest": "sha256:9f2c...", "part": null },
  "src_root": "src",
  "entry": "src/main.tsx",
  "out_dir": "out",
  "assets": [
    { "id": "a1", "path": "assets/9f2c...png", "sha256": "9f2c...",
      "media_type": "image/png", "origin_part": "ppt/media/image3.png",
      "licence": "CC-BY-4.0", "licence_url": "https://...", "source_url": "https://...",
      "retrieved_at": "2026-09-01T12:00:00Z" }
  ],
  "codec": { "video": "libvpx-vp9", "audio": "libopus", "container": "webm" },
  "limits": { "wall_s": 900, "rss_mb": 4096, "out_bytes": 2147483648 },
  "determinism": { "seed": 0, "clock_ns": 0 }
}
```

```json
// out/receipt.json  — omniweave-receipt-v1.  A gate result binds to BYTES, not filenames.
{
  "$schema": "omniweave-receipt-v1",
  "contract": 1,
  "outcome": "ok_partial",
  "artefacts": [ { "path": "out/q3.webm", "sha256": "1a2b...", "bytes": 18234112 } ],
  "source_fingerprint": {
    "algorithm": "sha256", "digest": "cafe...", "file_count": 12,
    "files": [ { "file": "main.tsx", "sha256": "dead..." } ]
  },
  "gate_status": "passed-with-warnings",
  "findings": [ { "code": "text_box_overflow", "provenance": "introduced",
                  "severity": "warning", "at": "src/main.tsx:41:9" } ],
  "degradations": [ "av1 encoder absent; used libvpx-vp9" ],
  "toolchain": { "name": "video", "version": "0.1.0", "sha256": "e3b0...",
                 "node": "20.18.1", "ffmpeg": "7.1", "encoders": ["libvpx-vp9","libopus"] },
  "metrics": { "ran_ms": 184312, "peak_rss_bytes": 3120000000 }
}
```

### `tools/check_versions.py` — the sites that must agree (S5)

```
1. packages/*/pyproject.toml            [project].version
2. omniweave_core/contract.py           CONTRACT (int; changes only on a contract change)
3. schema/*.json                        "$id" version suffix
4. toolchains/*/package.json            .version
5. packages/omniweave-out-*/toolchain.json   .version and .sha256 (must exist on disk)
6. the git tag (release only)
Prints the agreed version on stdout, exit 0; actionable errors on stderr, exit 1.
Generalised from anydoc/scripts/check-versions.sh, which checks five sites.
```

### CI (`ci.yml`), abbreviated

```yaml
jobs:
  gates:
    runs-on: ubuntu-24.04
    steps:
      - run: uv run tools/gate_core_pure.py       # S1 — resolves to exactly 1 dist
      - run: uv run tools/gate_weights.py         # S2 — fresh-venv installed size
      - run: uv run tools/gate_licences.py        # S3 — resolved graph AND import graph
      - run: uv run tools/gate_layers.py          # S4 — module-graph vs layers.toml
      - run: uv run tools/check_versions.py       # S5
      - run: uv run omniweave schema emit --check # S6
      - run: uv run tools/gate_pin_comments.py    # S7
      - run: uv run semgrep --config tools/semgrep/omniweave.yaml --error   # S8
      - run: uv run pytest tests/gates -x         # S9 S10 S11 S12 S13 S14
  test:
    strategy:
      matrix: { os: [ubuntu-24.04, macos-15, windows-2025], py: ['3.11','3.12','3.13'] }
```

### Terminology this decision fixes (propagates to D2–D10)

```
omniweave-core   the substrate distribution: stdlib-only, no models, no ceiling on Python
driver           an installable implementation, entry-point DISCOVERED, config ACTIVATED,
                 resolved at run time through ctx.driver(kind)
operator         a unit of scheduled work with a cache key and a row in the `work` table
                 (the framework ships operators; a distribution ships drivers)
target           an OUT compiler (omniweave-out-pptx ships the `pptx` target)
toolchain        a digest-pinned non-Python execution bundle invoked as a one-shot subprocess
job directory    the filesystem envelope of a toolchain invocation (job.json / src / assets / out)
CONTRACT         the integer driver-ABI version in omniweave_core.contract
omniweave doctor the preflight command: capability probes, driver inventory, weight report
exttool          the single subprocess seam; no other module may import `subprocess`
```

---

## Rationale

**Because the first milestone is four weeks and it is a real product.** `pip install omniweave &&
omniweave parse contract.docx --json` gives a user office-format parsing at anydoc's single-digit
millisecond speed, with a typed error taxonomy (`NeedsOcrError.pages` naming which pages need OCR),
non-configurable safety limits, and an L2 JSON they can actually consume — and it required us to
write zero Rust, zero TypeScript, and zero wheels. Every competing substrate choice pushes that
milestone past month six.

**Because the reuse is where the value is and the reuse is Python.** The unconditionally-commercial
IN stack the risk digest names is docling + anydoc + olmocr. Two of three are Python-callable today;
the third is Python-callable via an abi3 wheel that already exists. graphrag's leaf packages are
importable in twos (`graphrag-chunking` → 2 transitive packages). The PPTX compiler needs four pip
packages. `graphify/security.py` (the only DNS-rebind-proof fetcher in the collection) is Python.
LEANN, jcodemunch and graphrag's retrieval designs are Python or reimplemented-from-notes. A Rust or
TypeScript core throws all of that away and buys speed on the one seam where speed is already
solved by someone else's MIT code.

**Because dependency weight is the constraint that actually decides adoption.** docling makes
`torch` a *base* dependency, so nobody can use its DOCX reader in a Lambda. `leann-core` requires
torch *and* AGPL PyMuPDF. local-deep-research is 90 direct deps. The single move that avoids all of
this is a stdlib-only core plus one distribution per driver, and it is enforceable by a 40-line CI
gate rather than by discipline.

**Because separate distributions can express something extras cannot.** DataFlow's 20 extras include
four mutually incompatible vLLM pins — `pip install dataflow[kbc,mineru]` is unsatisfiable
(`mine-runtime.md` §1.10). Extras share one resolution; distributions do not. When
`omniweave-vision[vllm]` and a hypothetical `omniweave-vision-sglang` need incompatible `numpy`
ranges, the answer is "install one of them", not "the framework is unresolvable".

**Because the L2 model never crosses a language boundary, an IDL buys nothing.** OUT targets consume
text on disk. That single architectural fact removes protobuf, Arrow, and a three-language codegen
toolchain from the design, and replaces them with generated JSON Schema and a CI diff — which is
what the one repo that does this correctly (hyperframes' `sync-schemas --check`) already does.

**Because every invariant here has an "enforced by" column.** `mine-runtime.md` §7.11 states the
rule and I have applied it to packaging: *"an invariant held only by discipline is not held."* S1
through S14 are gates, tests, and lint rules. The `cairosvg` case is the proof that a licence policy
without an import-graph scan is a licence policy that fails.

---

## Tradeoffs

- **Python is slower than Rust for CPU-bound parse, and we accept it everywhere except the one seam
  where a fuzzed MIT Rust crate already exists.** The PDF path is Python + pdfium. If profiling
  shows the layout/geometry inner loops dominate, the mitigation is `numpy` inside
  `omniweave-pdf` (not core) or a second Rust seam — a bounded, later, evidence-driven decision.
- **A zero-dependency core means hand-written config coercion**, so worse validation errors than
  pydantic and a real risk of a subtle coercion bug. ~200 lines, property-tested. Fully reversible:
  adding `pydantic` to core costs the G1 gate and ~8 MB, and we would take that trade if the
  hand-written version bleeds.
- **Nine distributions is real release coordination for a small team.** A security bump in
  `omniweave-core` means re-releasing every distribution whose floor moves. Priced: one
  `release.yml` run, ~15 minutes, gated by S5. The alternative (one distribution) costs docling's
  weight problem and DataFlow's extras problem permanently.
- **Two package managers and two lockfiles** (`uv.lock`, `toolchains/pnpm-lock.yaml`). A pnpm bump
  can break the video target with no Python-side signal. Mitigated by S14 (full-digest verification)
  and by `toolchains` CI running only on change — but it is genuine surface.
- **One-shot subprocesses make progress and cancellation coarse.** A 20-minute video render reports
  progress only as bounded stderr lines and cancels only by SIGTERM. We buy this to avoid the entire
  local-daemon security surface (LEANN's unauthenticated loopback ZMQ port; open-slide's mandatory
  76-line CSRF guard).
- **Python 3.11 excludes 3.10 users and RHEL 9's default 3.9.** Remedy is `uv python install 3.11`
  or a module stream. We take the floor because olmocr and graphrag already require it, so
  supporting 3.10 would mean supporting them nowhere.
- **`firecrawl-anydoc` publishes 7 wheel targets, so Windows-on-ARM has no binary wheel** and a
  source build needs Rust 1.88 (`anydoc/Cargo.toml` `rust-version = "1.88"`). ~99.9% of installs are
  covered; `omniweave doctor` names the gap and the remedy explicitly.
- **We inherit anydoc's limitation that `to_document` is unsupported for PDF** (`anydoc/src/lib.rs`
  and the `_anydoc.pyi:79-80` docstring). That is not a substrate defect — it is why `omniweave-pdf`
  is a separate driver with a separate path — but it does mean the office and PDF paths do not share
  a decoder, and D2/D3 must reconcile two producers into one model.

---

## Failure modes

1. **anydoc goes stale, or `pdf-inspector = "1.14.2"` (Firecrawl's own crate, not vendored, licence
   and limit discipline unaudited) turns out to be a problem.** The repo is 3 months old and
   single-vendor. This is the design's largest single-point dependency. Bounded, not unbounded:
   exact pin + hash, MIT source vendored at a SHA, and a written fork trigger (60 days with no
   security response, or a licence change). The fork costs a Rust toolchain and ~3 engineer-weeks,
   most of it copying `release.yml`.
2. **The input that breaks it: a legal-discovery XLSX at anydoc's 4M-grid-slot ceiling.**
   `to_document` marshals eagerly into frozen Python objects, so a document at the limit becomes
   millions of `pyclass` instances in a single un-abortable, un-streamable, back-pressure-free call.
   `limits.rs` caps the *Rust* side; nothing caps the Python heap. Substrate mitigation: the office
   driver runs in a worker process with an RSS cap so the blast radius is one worker and
   `ResourceLimitError.limit` names the knob. That is a mitigation, not a fix. A streaming office
   decoder is a future Rust seam, and this is the workload that would justify it.
3. **A distro CPython without FTS5, or SQLite < 3.35.** The store cannot serve. Caught at
   `doctor`/preflight with `pip install omniweave[sqlite]` named in the message — but if that
   extra also fails (a platform with no `pysqlite3-binary` wheel), omniweave does not run at all on
   that platform.
4. **The hand-written config layer silently coerces something wrong**, e.g. `"false"` → `True`, and
   a `config_digest` then differs across two hosts that believe they share a config, producing a
   permanent 100% cache miss — graphrag's exact failure shape from a different cause
   (`str()`-fallback on an unserialisable cache-key value, `mine-runtime.md` §2.12 #6). Mitigation:
   `allow_nan=False`, an un-canonicalisable config value is a *startup error*, and a
   `show-config --digest` command so two hosts can be compared in one command.
5. **A third-party driver publishes an entry point named `office` and shadows ours.** `register()`
   raises on duplicates, so the outcome is a hard startup failure rather than a silent swap — which
   is the right failure, but it means one bad PyPI upload can brick a user's install until they
   uninstall it. There is no namespace reservation on PyPI entry points and no fix available at this
   layer.
6. **The toolchain cache (`~/.cache/omniweave/toolchains/<name>@<version>-<sha256>/`) is a
   user-writable directory holding executable code.** The digest is in the path and verified on
   every invocation, and `--offline` refuses to fetch. But a user with a compromised home directory
   is compromised, and no substrate choice fixes that.
7. **Nine distributions invite version skew in the wild.** A user with `omniweave-core 0.4.9` and a
   third-party driver built against `CONTRACT = 1` when core is at `CONTRACT = 2` gets a hard load
   error naming both versions. That is correct and it will still generate support load.
8. **The weight gate is a lagging indicator.** G2 measures installed size after resolution, so a
   transitive dependency that quietly grows 40 MB fails the build on an unrelated PR. That is
   annoying and correct; the failure message must name the *new* transitive package, not just the
   total.
9. **The video target's determinism claim is only as good as the toolchain digest.** If Chrome is
   resolved from the system rather than the pinned `@puppeteer/browsers` cache, two renders of the
   same job can differ. The receipt records the resolved Chrome version; a mismatch against the
   recorded one is a `degradations[]` entry, not a refusal — a deliberate softness that will
   eventually produce an unreproducible render someone cares about.
10. **`omniweave` depending on `omniweave-office` means the default install has a compiled wheel.**
    On an unlisted platform `pip install omniweave` fails at build time with a Rust error, which is a
    terrible first experience. Mitigated by naming the seven supported targets in the README and by
    a `pip install omniweave-core omniweave` two-step in the failure message — but the first
    impression is already spent.

---

## Why reject the alternatives

**A. "Rust core, Python and TypeScript are bindings."** This is the most attractive wrong answer,
and anydoc is the reason it looks attractive — so look at *why* anydoc can be Rust cheaply: it is a
pure function `bytes → Document` with **no HTTP client of any kind** and compile-time constant
limits. omniweave's core is not that. It is a scheduler with leases, a `work` table, a two-tier
cache with opposite invalidation policies, a middleware stack with a specific ordering
(`logging → request_count → cache → budget → retries → rate_limiting → metrics → fault_injection →
driver`), a registry, a freshness contract, and an MCP server. Rust makes none of that cheaper —
invariants I1–I18 in `mine-runtime.md` §7.11 are enforced by SQL UNIQUE indexes, lint rules and CI
tests, all of which are language-agnostic. Meanwhile a Rust core forces the L2 document model across
the FFI boundary on every operation, and anydoc's own binding proves that boundary costs an eager
full-document marshal (`python/src/document.rs`: *"converted eagerly into Python objects"*) — so you
pay the marshal *and* you still write the Python layer, *and* you maintain two ABIs across 7 targets
with maturin, manylinux containers, napi-cross and Zig (`anydoc/.github/workflows/release.yml`), and
every model, retriever, extractor and generator we want to reuse (olmocr, graphrag leaves,
python-pptx, tree-sitter, litellm, graphify's `security.py`) is still Python. Rust earns exactly one
seam and that seam is already written, MIT-licensed, and fuzzed with 12 cargo-fuzz targets.

**B. "TypeScript everywhere; Python via a sidecar."** Inverts the weight rule. IN is the large
surface and it is Python; OUT is the small surface and its highest-value target (PPTX, the only one
with a working `parse_back()`) is Python too — `ppt-master`'s compiler is four pip packages. A TS
core forces Node on every consumer of a DOCX reader, which is the precise failure the risk digest
names for docling and torch. And codegraph, the best TS project here, is the cautionary weight
example: 66 MB of vendored WASM grammars, 24 of them plausibly out of licence compliance.

**C. Polyrepo, one repository per distribution.** Nine repos, nine CI configs, nine release
processes, and every contract change becomes a cross-repo version dance — for a small team. Zero of
22 repos do this. Every multi-artefact project in the collection is single-repo: graphrag (8
packages, one uv workspace), markitdown (4), anydoc (crates.io + PyPI + 2 npm from one cargo
workspace), open-slide (pnpm/turbo), hyperframes (14 packages, bun). The coupling is real either way
— graphrag pins siblings at `==3.1.2` — so put it where one CI run can see it.

**D. One fat distribution with extras** (docling's and DataFlow's shape). Rejected on the hardest
number available: DataFlow ships 20 extras of which **four pin mutually incompatible vLLM ranges**,
so `[kbc]` + `[mineru]` is unsatisfiable, and its declared `requires-python = ">=3.7, <4"` is a lie
by three minor versions with nothing testing it (`mine-runtime.md` §1.10). docling shows the other
half: `torch` and `torchvision` as *base* dependencies means ≈2.5–3.5 GB to read a DOCX. Extras
cannot express "these two drivers cannot coexist in one resolution"; separate distributions can,
trivially.

**E. A language-neutral IDL (protobuf / Cap'n Proto / Arrow) for the core model.** Buys nothing here
because the L2 model never crosses a language boundary — OUT targets consume an IL that is text on
disk, and the only cross-language wire is a ~30-field job envelope. Costs a codegen toolchain in
three languages, a schema-compiler version to keep in step, and a second source of truth. The proven
alternative is in the collection: hyperframes generates schemas and CI-diffs them
(`sync-schemas --check`), while the hand-authored counter-example fails silently — LEANN's
`llms.txt` declares 2 tools against a server that ships 4, two of them state-changing and
undeclared, with no generator and no CI check.

**F. A long-lived local daemon (or gRPC service) as the substrate.** Rejected on two pieces of
evidence. LEANN's embedding server is an unauthenticated ZMQ REQ/REP socket on a dynamic loopback
TCP port — compute theft from any local process on a shared CI runner — and the fix nobody in the
collection applies is a unix socket at 0600, not a loopback port. open-slide needs a 76-line
`request-guard.ts` (Sec-Fetch-Site, normalised origin honouring `x-forwarded-proto`'s first comma
token, explicit rejection of the literal `null` origin) purely because it has a local server that
writes files. Attach-or-spawn for GPU model servers only, where the cold model load actually
justifies the surface — and even then with surya's model-id verification on attach, because
attaching to the wrong server is a silent correctness bug.

**G. Vendoring anydoc's Rust source and building it ourselves from day one.** Tempting, because it
removes the single-vendor dependency. Rejected for phase 1 only: it converts a `pip install` line
into a 7-target cross-compilation pipeline (maturin, manylinux2014, musllinux_1_2, two macOS arches,
MSVC) in week 1, for a benefit — supply-chain independence — that a hash pin plus a vendored source
snapshot plus a written fork trigger already substantially delivers. The fork is a *priced option we
hold*, not a cost we pay before shipping anything.
