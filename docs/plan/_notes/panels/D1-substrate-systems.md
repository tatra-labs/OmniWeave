# D1 — Language, runtime substrate, and repository/package layout

**Panel:** D1 · **Prior:** the systems purist · **Author:** architect-3
**Status:** proposal · **Date:** 2026-09-01

---

## Headline

**omniweave is a small Rust kernel that owns the document model, the ingest limits, the digest
functions and the store; a Python orchestrator that owns the plan, the driver registry and the agent
surface; and out-of-process TypeScript compilers for the two OUT targets that genuinely need a
browser. One monorepo with one version and one *generated* schema; every driver and every model
runtime lives out of tree in its own distribution. The base install is a 250 MB budget enforced by a
CI gate, contains no tensor library, no browser and no codec, and cold-starts in under 250 ms.**

The three languages are not a compromise between ecosystems. Each owns exactly the layer where its
properties are load-bearing, and the *seams* — one FFI buffer contract, one stdio protocol, one
generated schema — are the actual design.

---

## 1. The decision in one table

| Concern | Substrate | Why this one, not the others |
|---|---|---|
| L2 document model (the pivot) | **Rust** — `omniweave-model`, the normative definition | It is the only artifact all three languages must agree on byte-for-byte. One definition, N generated projections. |
| Ingest limits, error taxonomy | **Rust** — `omniweave-limits`, `omniweave-error` | anydoc's `limits.rs`: compile-time constants that *cannot* be switched off. A knob that disables the zip-bomb cap will be disabled. |
| `content_digest` / `config_digest` / `canonical_uri` | **Rust** — `omniweave-digest`, `omniweave-uri` | Every cache key in the system. Reimplementing it in a second language is how `["a","bc"]` and `["ab","c"]` collide (graphrag `gen_sha512_hash`). |
| Tier-0 format decoding (docx/pptx/xlsx/odf/rtf/doc/epub/csv/md/html) | **Rust** — `omniweave-parse-*` | The stated requirement is milliseconds. anydoc median **4.4 ms** vs markitdown **134.8 ms** vs docling **513.6 ms** vs LibreOffice **1129.5 ms** (`anydoc/README.md:176`). 30× and 117×. |
| Store: SQLite, WAL, pragmas, work table, FTS5, fusion | **Rust** — `omniweave-store` | Pragma *order* is a correctness property (codegraph #238), and every reader — hook, CLI, MCP, a second process — must apply the same ladder. One implementation or none. |
| Plan, registry, cache policy, budget, retry, freshness | **Python** — `omniweave` | This is rule code that changes weekly, and it is where the runtime reference design (`mine-runtime.md` §7) already lives. |
| Parser/OCR/VLM/embedding drivers | **Python**, out of tree | docling, olmocr, vLLM, transformers, graphrag prompts. A driver author who must write Rust will not write the driver. |
| PPTX / DOCX targets | **Python** + kernel OPC writer | OOXML is a ZIP of XML. Making the highest-value OUT target need Node would be a self-inflicted wound. ppt-master's validator is 9,368 lines of *rules* — Python's shape. |
| HTML-deck / MP4 targets | **TypeScript**, out of process | They need a DOM, a headless browser and ffmpeg. Those are a fault domain and a licence hazard; they belong behind a process boundary. |
| Browser / zero-install parsing | **wasm32** build of the same kernel | anydoc's WASM target is a privacy architecture *and* a structural guarantee: a parser that must compile to `wasm32-unknown-unknown` cannot grow a network call by accident. |

---

## 2. Repository layout

**Monorepo for the core. Polyrepo for drivers.** The boundary is exact: *anything that pins a model
runtime is out of tree.*

```
omniweave/                            one git repo · one VERSION · three toolchains
├── VERSION                           single source of truth
├── omniweave.toml                    the reference config (also the user-facing shape)
├── Cargo.toml                        [workspace] members = ["crates/*", "bindings/*"]
├── pyproject.toml                    [tool.uv.workspace] members = ["py/*"]   (root: Private::Do Not Upload)
├── package.json                      "workspaces": ["ts/*"]                   (root: private: true)
│
├── schema/                           ★ GENERATED — hand-editing fails CI (S1)
│   ├── json/document.schema.json     JSON Schema 2020-12
│   ├── json/receipt.schema.json
│   ├── json/il-envelope.schema.json
│   └── sql/0001_init.sql             the block/edge/work DDL
│
├── crates/
│   ├── omniweave-model/              ★ THE NORMATIVE DEFINITION of L2
│   ├── omniweave-limits/             anydoc's 12 constants, verbatim, as the MAXIMUM
│   ├── omniweave-error/              ConvertError + code() + is_fatal() + NeedsOcr{pages}
│   ├── omniweave-digest/             canonical JSON + sha256; content/producer/config groups
│   ├── omniweave-uri/                canonical_uri: realpath + normcase + strip \\?\
│   ├── omniweave-abi/                DocBuf fixed-width layout + ABI_VERSION + kind tables
│   ├── omniweave-parse-ooxml/        docx pptx xlsx odt odp ods       — wasm-clean
│   ├── omniweave-parse-legacy/       doc rtf cfb epub csv md html      — wasm-clean
│   ├── omniweave-parse-pdf/          feature-gated; NOT wasm-clean (mmap)
│   ├── omniweave-store/              pragmas · WAL valve · work table · FTS5 · WRR fusion
│   ├── omniweave-kernel/             façade; the ONLY crate bindings depend on
│   └── omniweave-schemagen/          the generator. `--check` is the CI gate.
│
├── bindings/
│   ├── python/                       pyo3 abi3-py310  → ONE wheel per platform, CPython 3.10+
│   ├── node/                         napi, 7 targets, optionalDependencies by os/cpu
│   └── wasm/                         wasm32-unknown-unknown; browser + parity fallback
│
├── py/
│   ├── omniweave/                    orchestrator · registry · CLI · MCP.  ZERO heavy deps.
│   ├── omniweave-target-pptx/        OOXML writer + ppt-master-derived blocking validator
│   └── omniweave-target-node/        ~40 KB. Locates and spawns Node. Bundles NOTHING.
│
├── ts/
│   ├── kernel/                       @omniweave/kernel        (napi prebuilds)
│   ├── kernel-wasm/                  @omniweave/kernel-wasm
│   ├── compilers/                    @omniweave/compilers     deck + video; owns puppeteer
│   └── cli/                          @omniweave/cli           `ow-compile`, stdio protocol
│
├── scripts/
│   ├── check-versions.sh             S2 — every manifest + the git tag agree
│   ├── weight-gate.py                S4 — clean venv, measure, denylist intersect
│   ├── import-graph-scan.py          S5 — undeclared imports (the cairosvg case)
│   └── licence-gate.py               S11 — transitive graph + UNPACKED artifacts
│
└── tests/
    ├── parity/                       S7 — native × wasm × python-reference, golden corpus
    ├── fuzz/                         12+ cargo-fuzz targets, one per format handler
    └── coldstart/                    S12 — timing assertions
```

Out of tree, separate repos, independent cadence, own pins:

```
omniweave-driver-docling     omniweave-driver-olmocr      omniweave-driver-vllm
omniweave-driver-surya-code  (code only — never the weights)
omniweave-connector-{s3,sharepoint,drive,imap}
```

### Why monorepo for the core

The schema is cross-language. In a polyrepo, a model change is a three-PR dance with a window in
which the Rust, Python and TS projections disagree, and *no CI job can observe that window*. That is
the irreversible-mistake class this prior exists to avoid. Three working precedents in the
collection show a monorepo of this exact shape is routine:

- **graphrag** — `packages/{graphrag,graphrag-cache,graphrag-chunking,graphrag-common,graphrag-input,graphrag-llm,graphrag-storage,graphrag-vectors}`, a `uv` workspace, private root (`name = "graphrag-monorepo"`, `classifiers = ["Private :: Do Not Upload"]`, `version = "0.0.0"`), lockstep `==3.1.2` inter-package pins, and a `_semversioner_update_*_toml_version` poe task per package.
- **hyperframes** — 14 npm workspace packages, all at `0.8.20` — *except* `@hyperframes/sdk-playground` at `0.6.106`. That is the drift you get when nothing gates it.
- **anydoc** — 1 crate + 3 binding manifests, and `scripts/check-versions.sh` asserting **five** version locations agree, run as job 1 of `release.yml` with the git tag.

So: monorepo **plus a version gate as the first CI job**. That gate is 60 lines of `sh` and it is the entire difference between anydoc and hyperframes.

### Why polyrepo for drivers

DataFlow's `pyproject.toml` ships **twenty extras of which four pin mutually incompatible vLLM
ranges** (`vllm>=0.7.0,<=0.9.2` / `vllm<0.8` / `vllm<0.9` / `vllm==0.6.3`) — installing `[kbc]` and
`[mineru]` together is unsatisfiable. Extras *cannot express* "these two drivers cannot coexist".
Separate distributions can, because pip's resolver sees them as independent roots and reports the
conflict honestly.

The corollary rule, from the risk digest: **an L5 orchestration layer must never be a dependency of
an L1 parser.** docling proves the cost of getting this wrong — 33 base dependencies including
`torch`, `torchvision`, `accelerate`, `scipy`, `pandas`, `rapidocr` (`docling/pyproject.toml:45-79`),
so you cannot get its `python-docx` reader without a tensor library. And note what happens even to a
*correct* split when the axis is wrong: graphrag split into 8 packages, but `graphrag-storage` still
hard-requires `azure-cosmos`, `azure-identity`, `azure-storage-blob` and `pandas`, so a user who
wants local file storage installs the Azure SDK. **Split by dependency weight, never by conceptual
layer.**

---

## 3. The one schema, and its four projections

The single highest-leverage structural decision here. `omniweave-model` is normative; everything
else is generated and diff-gated.

```
crates/omniweave-model/src/document.rs        ← the ONLY definition
        │
        └── cargo run -p omniweave-schemagen [--check]
                ├── bindings/python/omniweave_kernel/_model.py      pydantic + .pyi
                ├── ts/kernel/src/model.ts                          types + zod
                ├── schema/json/*.schema.json                        JSON Schema 2020-12
                ├── schema/sql/0001_init.sql                         the DDL
                ├── crates/omniweave-abi/src/layout.rs               row offsets + ABI_VERSION
                ├── ts/kernel/src/layout.ts                          the TS mirror of the above
                └── docs/model.md
```

`--check` regenerates into a temp dir and byte-diffs, with CRLF→LF normalisation so a Windows
checkout is not reported stale (hyperframes' `hashSkillBundle` normalises for exactly this reason).
CI runs `--check`; a hand-edited projection fails. This is graphify's `tools/skillgen`
`--check`/`--bless` discipline applied to the data model instead of to prose.

**I am deliberately not adopting protobuf, Cap'n Proto or gRPC as the universal contract.** proto3's
all-optional field model actively defeats the invariant that every block carries an
`origin_operator` and a `confidence`; and gRPC is ceremony where I need a file. Instead there are
exactly two wire formats, each matched to its seam:

1. **Fixed-width row buffers** for the hot in-process FFI path (§4).
2. **Canonical JSON** for anything crossing a process boundary or landing in the store, with the
   generated JSON Schema as the checkable artifact.

### The DocBuf contract (FFI)

Lifted directly from codegraph's `src/extraction/kernel/layout.ts` ↔ `codegraph-kernel/src/buffers.rs`,
which is the only working example of this pattern in the collection ("one JS boundary crossing per
file").

```
DocBuf = 5 buffers. Little-endian. Fixed-width rows. Strings are (u32 off, u32 len) into `arena`.
NONE = 0xFFFF_FFFF means "field absent".  ABI_VERSION: u16, bumped on ANY layout change.

meta   40 B : abi u16 | flags u16 | block_count u32 | span_count u32 | asset_count u32
            | arena_len u32 | errors_off u32 | errors_len u32 | page_count u32 | status u8 | _pad
block  80 B : kind u8 | content_layer u8 | confidence u8 | origin u8      ← ENUM INDEXES
            | page u32 | parent u32 (NONE=root) | first_child u32 | next_sibling u32
            | poly_off u32   (8 × f32 in arena; NONE = no spatial provenance)
            | char_start u32 | char_len u32       ← docling's ProvenanceItem charspan
            | text str | block_id str | section_path str | extra_json str
span   24 B : block u32 | byte_start u32 | byte_len u32 | flags u16 | _pad
asset  32 B : block u32 | media_type str | sha256 str | byte_len u32 | flags u16
```

- `BlockKind`, `Confidence`, `Origin`, `ContentLayer` cross as **indexes into append-only tables**;
  the generator emits a table hash and the loader compares it. Reordering an enum is therefore a
  detected ABI break, not a silent mis-decode. (This is also why marker's `(str, Enum)` +
  `auto()` — values `"1"`, `"2"` — is banned: enum *values* are names in the schema, indexes only on
  the wire.)
- `has_span` / `NONE` sentinels exist because `byte_offset == 0` cannot distinguish "unset" from
  "starts at byte 0" (mine-graph §4.2.2).
- **Decoding into host objects is lazy and opt-in.** `doc.blocks[i]` decodes one row. Materialising
  2M blocks into Python objects is the memory failure mode — LEANN's pickled passage map is
  "1–1.5 GB of interpreter objects at 10M entries".

---

## 4. The two seams

### Seam A: kernel ↔ orchestrator is **in-process FFI**

Parse is called millions of times against 4.4 ms of work. A process hop per document is absurd
overhead, and the store handle must be shared. pyo3/napi call overhead is hundreds of ns to low µs —
under 0.1% of one conversion.

Two call shapes only, and no third is permitted:

```python
# bindings/python — the whole surface
def abi_version() -> int: ...
def convert(data: memoryview, opts: ConvertOpts) -> DocBuf: ...          # one crossing per unit
def convert_part(data: memoryview, part: PartRange, opts) -> DocBuf: ...  # per page/slide/sheet
def open_store(path: str, mode: StoreMode) -> Store: ...                  # kernel owns SQLite
```

**The kernel owns the SQLite connection and nothing else may open the file.** This is not
convenience; it is how the pragma ladder (`busy_timeout` **before** `journal_mode`, or you crash on a
contended open — codegraph #238), heal-on-open for an oversized WAL (25.6 GB observed), the WAL valve
with its proportional threshold `clamp(dbSize/4, 256MB, 2GB)` and its futility latch, and
`connect_readonly`'s `mode=ro` vs `mode=ro&immutable=1` ladder are guaranteed to be applied by
*every* reader — the hook, the CLI, the MCP server, and a second process. A `sqlite3.connect` /
`better-sqlite3` / `node:sqlite` call anywhere outside `omniweave-store` is a lint failure (S9).

### Seam B: orchestrator ↔ TS compilers is a **process boundary with a stdio protocol**

Not FFI, not a daemon, not HTTP by default. Three reasons, in order of weight:

1. **Failure isolation.** A headless-Chromium render OOMs, hangs and leaks fds. It must not be in
   the address space holding the store's single WAL writer.
2. **Dependency weight.** hyperframes' Lambda bundle is **≈212 MB** (Chrome 70 + ffmpeg 80 +
   ffprobe 62). Behind a process boundary, a Python user who never asks for MP4 never installs any of
   it. Note that hyperframes already confines that weight correctly: `ffmpeg-static`,
   `ffprobe-static` and `@sparticuz/chromium` appear only in `packages/aws-lambda/package.json`, not
   in `cli` or `core`.
3. **Licence.** `libx264` makes a bundled ffmpeg a **GPL-2.0-or-later binary redistributed inside a
   deploy artefact**. The process boundary lets us spawn the *system* binary, report its encoders,
   and refuse rather than substitute.

```jsonc
// request: ONE JSON object on stdin, then EOF
{"v":1,"op":"compile","target":"deck.html","il_sha256":"3f8a…","il":{…},
 "out_dir":"…","assets_dir":"…","budget_ms":120000,"deadline_ms":180000}

// responses: NDJSON on stdout.  stderr is a log and is never parsed.
{"v":1,"ev":"progress","stage":"render","done":12,"total":40}
{"v":1,"ev":"finding","severity":"error","code":"canvas_overflow","page":7,"detail":"…"}
{"v":1,"ev":"receipt","status":"passed_with_warnings","il_sha256":"3f8a…",
 "artifacts":[{"path":"deck.html","sha256":"…"}],
 "fidelity":{"passthrough":3,"cloned_passthrough":0,"patched":0,"rebuilt":37},
 "encoders":{"video":"libvpx-vp9"}}
{"v":1,"ev":"error","code":"target_unavailable","reason":"node>=20 not found",
 "fix":"omniweave targets install deck"}
```

- **Exit 0 iff a receipt was emitted.** No other success signal exists.
- `il_sha256` is echoed in the receipt, so a gate result binds to *bytes*, not to a filename
  (ppt-master's `source_fingerprint` rule).
- Every error carries `fix` — the exact command that clears it (ppt-master's nine-value gate rule:
  the failure message names the status *and prints the command*).

The probe is the same binary with `--probe`, and it probes the **capability**, not the import:

```jsonc
{"v":1,"ev":"probe","node":"22.11.0",
 "chromium":{"path":"…","rev":"131.0.6778.204"},
 "ffmpeg":{"path":"/usr/bin/ffmpeg","encoders":["libvpx-vp9","libaom-av1"],"libx264":false}}
```

`ffmpeg` present but no libvpx/libaom ⇒ **refuse the MP4 target; never fall back to H.264.** Codec
choice is a licence decision, not a quality decision.

### How Node is *not* forced on anyone

`omniweave-target-node` is ~40 KB of pure Python and bundles nothing. Resolution order:
`$OMNIWEAVE_NODE` → a bundle installed under `$OMNIWEAVE_HOME/targets/` → `node` on `PATH`. If none
resolves, `omniweave targets install deck` fetches a per-platform archive containing a vendored Node
plus the compiler — codegraph's `BUNDLING.md` shape exactly, with a recorded sha256 and an
architecture assertion (hyperframes' `assertLinuxX86_64Elf`) before unpacking. Until the user runs
that command, the deck and video targets are simply **pruned from the plan with a report** — never
an `ImportError`, never a silent substitution.

PPTX and DOCX never touch this path. That is the point.

---

## 5. How a driver ships, and why discovery must not import

Discovery is via entry points, but **not markitdown's or docling's version of it.**

- **markitdown** (`packages/markitdown/src/markitdown/_markitdown.py:75`): `_load_plugins()`
  iterates `entry_points(group="markitdown.plugin")` and calls `entry_point.load()` inside
  `except Exception: warn(...)`, caching into a module global `_plugins`. So any installed
  distribution silently gains code execution in the converter path, and a load failure is a warning
  nobody reads. This is how `markitdown-ocr` — which hard-requires AGPL PyMuPDF — becomes invisible
  once installed.
- **docling** is better and still wrong in a specific, checkable way. `base_factory.py:95-105`:

```python
plugin_manager = PluginManager(plugin_name)
plugin_manager.load_setuptools_entrypoints(plugin_name)      # ← IMPORTS every plugin module
for plugin_name, plugin_module in plugin_manager.list_name_plugin():
    plugin_module_name = str(plugin_module.__name__)
    if not allow_external_plugins and not plugin_module_name.startswith("docling."):
        logger.warning(...); continue                        # ← gate is AFTER the import
```

  `allow_external_plugins=False` blocks *registration*, not *import*. A third-party plugin's
  module-level code runs regardless of the flag. The mechanism exists, its default is safe, and it is
  on the wrong side of the import.

**omniweave's rule: discovery is metadata-only; import requires an allowlist entry.** Entry-point
metadata carries the module path as a *string*, so the whole catalog is buildable with zero imports.

```toml
# a driver distribution declares:
[project.entry-points."omniweave.driver"]
"parse.pdf.docling" = "omniweave_driver_docling.driver:DoclingPdfDriver"
```

```python
@dataclass(frozen=True)
class DriverCard:
    """Built from importlib.metadata ONLY. `module` is a string and is never imported here."""
    name: str            # "parse.pdf.docling"  — the registry key
    kind: str            # parse | ocr | embed | llm | structure | target | connector
    cost_class: CostClass          # FREE | LOCAL_COMPUTE | BILLED_API
    dist: str; dist_version: str
    module: str
    abi_req: str         # "omniweave-abi ~=1.2"  — checked BEFORE import
    allowlisted: bool    # present in omniweave.toml [drivers]

class Driver(Protocol):
    NAME: ClassVar[str]; KIND: ClassVar[str]; COST_CLASS: ClassVar[CostClass]
    ABI: ClassVar[str]
    @classmethod
    def probe(cls, cfg: Mapping[str, Scalar]) -> ProbeResult: ...
    def run(self, unit: UnitRef, ctx: RunContext) -> StepResult: ...
```

Consequences, each of which is a requirement from another area:

- **A 100%-cache-hit run loads zero driver modules.** This is the precondition for `--dry-run`, cost
  estimation and free-tier auto-refresh (`mine-runtime.md` §7.1.1). DataFlow cannot do it because
  `PromptedGenerator` takes an `LLMServingABC` in `__init__`.
- **An attacker who gets a package installed does not thereby get code execution in the parse path.**
- **`probe()` runs the smallest real operation**, not an import check — a `tesseract` without the
  language pack, a CUDA torch that fails on first kernel launch, a `pdfium` that cannot open an
  encrypted PDF, an Ollama client with no model pulled all import fine. Verdict cached for the run;
  a red probe **prunes the plan and reports**, and `sys.exit()` is banned in library code
  (graphrag's `validate_config_names` kills the process).
- `register()` **raises on a duplicate name** unless `replace=True`. DataFlow's registry is keyed on
  bare `__name__`, first-wins, silent: two plugins with one class name and one vanishes.

---

## 6. Install matrix — what a user actually types

```
pip install omniweave                    # ~14 MB wheel. kernel + orchestrator + CLI + MCP.
                                         #   NO torch. NO onnxruntime. NO numpy. NO browser.
pip install omniweave[server]            # + the HTTP/ASGI transport (pure Python)
pip install omniweave[postgres]          # + psycopg (T3 store)

pip install omniweave-driver-docling     # opts in to 33 deps and ~2.5–3.5 GB. Their choice.
pip install omniweave-driver-olmocr
pip install omniweave-target-pptx        # pure Python. No Node.
pip install omniweave-target-node        # 40 KB. Then: omniweave targets install deck
npm i -g @omniweave/cli                  # for a TS-native user; the same compilers
```

**Extras on the core distribution may only pull pure-Python, small packages.** No extra on
`omniweave` may pull a tensor library, a browser, or a codec — and that is a CI gate, not a
convention (S4).

Publication targets per release:

| Registry | Artifacts |
|---|---|
| PyPI | `omniweave` (7 abi3 wheels + sdist), `omniweave-target-pptx`, `omniweave-target-node` |
| npm | `@omniweave/kernel` + 7 platform packages, `@omniweave/kernel-wasm`, `@omniweave/compilers`, `@omniweave/cli` |
| crates.io | `omniweave-model`, `-limits`, `-error`, `-digest`, `-uri`, `-abi`, `-parse-*`, `-store`, `-kernel` |
| GH Releases | per-platform Node-target bundles (vendored Node + compilers), sha256-manifested |

### CI: wheels for 3 OSes, concretely

anydoc's `release.yml` is 483 lines and already does exactly this; I am copying the shape:

- **7 wheel targets** (`{x86_64,aarch64}-unknown-linux-{gnu,musl}`, `{x86_64,aarch64}-apple-darwin`,
  `x86_64-pc-windows-msvc`) via `PyO3/maturin-action@v1` with `manylinux` per row. Because
  `pyo3 = { features = ["abi3-py310"] }`, that is **7 wheels total, not 7 × 4 Python versions**
  (`anydoc/python/Cargo.toml`: *"abi3-py310 pins the stable ABI: one wheel per platform covers every
  CPython from 3.10 up"*).
- **7 napi targets**, musl rows cross-compiled with the Zig toolchain, shipped as npm
  `optionalDependencies` gated on `os`/`cpu` so npm installs only the matching one.
- **1 wasm target** via `wasm-pack build --target web`.
- A separate **test-the-artifact** matrix that downloads each built artifact and runs it on the real
  platform (or in a container). Building is not testing.
- Job 1 is the version gate. Jobs are `--dry-run` on non-tag pushes and idempotent on republish
  ("skip if this version is already on npm/crates.io").

Total ≈ 30 jobs per release. That is the operational bill and I am stating it.

---

## 7. Configuration and environment

```toml
# omniweave.toml — the file grammar version is line 1, ppt-master's spec_lock discipline
schema = 1

[project]
name        = "acme-contracts"
source_root = "./corpus"            # the IDENTITY anchor (cache salt is relative to this)
output_root = ".omniweave/out"
cache_root  = ".omniweave/cache"    # NEVER inside source_root — graphify #1774

[store]
backend = "sqlite"                  # sqlite | postgres
path    = ".omniweave/index.db"

[limits]                            # clamps BELOW the kernel's compile-time maxima
max_entry_bytes = 33554432          # 32 MiB   (kernel max 134217728 = 128 MiB)
max_pages       = 2000              # (kernel max: none — page count is unbounded by design)
# The effective value is min(tenant_cap, KERNEL_MAX). Widening past a kernel maximum is not a
# flag; it is a fork. A limit hit returns ResourceLimit{limit} naming which knob would help.

[drivers]                           # the ALLOWLIST. Discovery lists; only these may be imported.
"parse.ooxml"       = { builtin = true }
"parse.pdf.docling" = { dist = "omniweave-driver-docling", version = "==0.4.2" }
"ocr.page.olmocr"   = { dist = "omniweave-driver-olmocr",  version = ">=0.2,<0.3" }

[targets]
"pptx"      = { builtin = true }
"deck.html" = { runtime = "node", node = "auto" }   # auto | <path> | bundled
"video.mp4" = { runtime = "node", codec = "vp9" }   # h264 requires an explicit operator opt-in

[budget]
per_document_micros = 5000          # $0.005 hard cap. A currency budget, not a retry count.
```

Three roots, always separate (graphify retrofitted this across five functions). Every knob has an
`OMNIWEAVE_*` env twin resolved **once** at startup, and `omniweave show-config` prints each resolved
value **with its source** — codegraph's ten-plus env-only knobs with no dump is the counter-example.

---

## 8. Invariants, and how each is enforced

"Enforced by" is the column that matters. An invariant held only by discipline is not held.

| # | Invariant | Enforced by | Evidence it is needed |
|---|---|---|---|
| **S1** | Exactly one definition of the document model exists. | `omniweave-schemagen --check` byte-diffs all 7 projections in CI; CRLF-normalised. | Three credible document models exist across 11 repos and none has a second-language projection; every one that acquired a serializer acquired drift. |
| **S2** | Every version-bearing manifest agrees with the git tag. | `scripts/check-versions.sh` as CI job 1, over ~14 manifests. | anydoc gates five locations and holds; hyperframes does not and `sdk-playground` sits at 0.6.106 against 0.8.20. |
| **S3** | The kernel has no network capability. | Two independent gates: (a) `cargo tree -p omniweave-kernel` must not resolve reqwest/hyper/ureq/curl/socket2/rustls/native-tls/tokio-net; (b) `cargo build --target wasm32-unknown-unknown -p omniweave-kernel --no-default-features` must succeed. | anydoc: eight crates, **no HTTP client of any kind**, so it structurally cannot SSRF, exfiltrate or fetch a remote entity. It is the only parser in the collection with that property. |
| **S4** | Base install ≤ 250 MB, denylist-clean. | `scripts/weight-gate.py`: clean venv, install `omniweave` + every declared extra, measure `site-packages`, intersect the resolved set with the denylist. **Fails**, never warns. | 250 MB is the Lambda unzipped-layer limit. Denylist: `torch`, `torchvision`, `onnxruntime`, `nvidia-*`, `PyMuPDF`, `mineru`, `pypandoc-binary`, `ffmpeg-static`, `cairosvg`, `curl_cffi`, `edge-tts`. |
| **S5** | No import is undeclared. | `scripts/import-graph-scan.py` per distribution; any import absent from that dist's declared deps fails the build. | `cairosvg` (LGPL-3.0) is imported by `ppt-master/.../pptx_package/media.py` and appears in **no** requirements file. A manifest-only SBOM cannot see it. |
| **S6** | Driver discovery never imports. | A test installs a driver whose module body raises `SystemExit`, then asserts `omniweave drivers list` succeeds and `ctx.driver()` returns `DriverUnavailable`. | markitdown `_markitdown.py:75`; docling `base_factory.py:96` (gate after import). |
| **S7** | Two implementations of one operator are equivalent. | A parity suite per format handler across native-Rust × wasm × the Python reference, over a committed golden corpus. | codegraph ships **13** `kernel-*-parity.test.ts` files and a `kernel-grammar-parity` node-kind-table assertion precisely because it has two extraction paths. |
| **S8** | An ABI mismatch degrades; it never mis-decodes. | `ABI_VERSION` + an enum-table hash verified at load; unknown ⇒ return null and use the fallback path. A test loads a deliberately-stale stub. | codegraph's loader: *"a stale `.node` degrades to the wasm path instead of mis-decoding"*, `KERNEL_ABI_VERSION = 2`. |
| **S9** | Nothing outside `omniweave-store` opens the store. | Lint: `sqlite3.connect`, `better-sqlite3`, `node:sqlite`, `rusqlite::Connection::open` banned elsewhere. | Pragma order is a correctness property (codegraph #238); `mode=ro` on a WAL DB *creates* sidecars and moves the mtime a freshness check reads (jcodemunch §5.2.1). |
| **S10** | A vendored binary carries sha256 **and** a parity/equality test **and** an arch assertion **and** a NOTICE entry — all four. | `scripts/licence-gate.py` reads `vendor.toml`; a file present in-tree and absent from it fails. | codegraph has 3 of 4 (66 MB of WASM, 27 grammars, **3** LICENSE files); hyperframes has 1 of 4; Unlimited-OCR has 0 (a 12,450,224-byte unsigned sglang wheel from a dev commit as install step 1). |
| **S11** | No GPL/AGPL/LGPL binary is redistributed in any artifact. | The gate resolves the transitive graph *and* **unpacks every built wheel and npm tarball** and scans the files. | hyperframes' `ffmpeg-static` in a Lambda zip; local-deep-research's `pypandoc-binary`. Both are wheel/zip contents no manifest scanner sees. |
| **S12** | `omniweave --version` and `omniweave query` cold-start ≤ 250 ms with no driver installed. | A CI timing assertion in `tests/coldstart/`. | graphify's own measurement: importing the graspologic *package* rather than its native extension pulls umap → pynndescent → numba JIT for **7–19 s** of one-time import cost, against a ~1 s native call, for a layout algorithm the function never invokes. Cold start is a number or it rots. |
| **S13** | Every symbol crossing a language boundary is generated. | The schemagen also emits the pyo3 `#[pyclass]` and napi `#[napi]` shims; a hand-written binding fails `--check`. | Hand-written bindings are where a nullable-vs-required mismatch hides. |
| **S14** | `sys.exit` / `process.exit` never appears in library code. | Lint. | graphrag's `validate_config_names` — *"a library that kills the process"*. |
| **S15** | No `omniweave.toml` `[limits]` value may exceed the kernel constant. | The kernel clamps; the CLI errors on a config that tries. It is not a flag. | *"A knob that turns off the zip-bomb cap will be turned off"* (anydoc). markitdown's default-registered `ZipConverter` has no entry cap, no size cap, no total cap and no recursion counter. |

---

## 9. What it costs

- **Engineering, before the first document parses.** The schema generator (~1,200 lines), the ABI
  layout + loader on three sides, the tri-language CI, the version gate, the four policy gates, and
  the parity harness: **4–6 engineer-weeks**. anydoc's `release.yml` is 483 lines for 3 bindings of
  1 crate; omniweave's will be larger. I am explicitly buying this to avoid a schema-skew bug class
  that has no cheap fix later.
- **A Python reference implementation of every kernel behaviour**, maintained purely to feed S7's
  parity suite. This is real ongoing cost and it is the mitigation for kernel bus factor (see §10.8).
  Without it the kernel is unreplaceable, which is worse.
- **Contributor tax.** Touching the document model requires all three toolchains. Mitigated by
  scope: a *driver* author needs Python only, a *target* author needs TS only, and `make schema`
  runs the generator in a container so no contributor installs a Rust toolchain to review a diff.
- **Runtime overhead.** One FFI crossing per unit (<0.1% of a 4.4 ms conversion). One process spawn
  per OUT compile: ~80–150 ms of Node cold start, amortised over a multi-second render.
- **Memory.** One arena allocation per DocBuf, bounded by the anydoc caps: 128 MiB/entry,
  512 MiB/archive, 64 MiB duplicated text, 128 MiB assets, 4M grid slots. Lazy host-side decode keeps
  a 4,000-page PDF from materialising.
- **Dependency weight.** Kernel target: ≤ 12 crates (anydoc proves the envelope with 8: `cfb`, `csv`,
  `flate2`, `encoding_rs`, `log`, `pdf-inspector`, `quick-xml`, `zip`). Core wheel target ≤ 14 MB —
  against markitdown's ≈150–250 MB "lightest here", which is only that heavy because
  `magika~=0.6.1` pulls `onnxruntime` + `numpy`.
- **Operational.** Three registries, a ~30-job release, a per-platform Node bundle channel, and one
  ABI version that is a public API. `pdf-inspector = "1.14.2"` is Firecrawl's own crate, not
  vendored, licence and limit discipline unaudited — that audit is on the day-one list.

---

## 10. Failure modes, honestly

1. **The wasm gate blocks a legitimate design.** `wasm32-unknown-unknown` has no threads, no mmap,
   no filesystem. A PDF path that needs `mmap` for a 2 GB file cannot satisfy S3(b). *Response:* the
   wasm gate applies to `omniweave-model` + `omniweave-parse-ooxml` + `omniweave-parse-legacy` only;
   `omniweave-parse-pdf` is feature-gated out. **Consequence I accept and state: the structural
   no-network guarantee covers the OOXML/legacy family, and the PDF path is defended by the
   `cargo tree` gate alone — which is a weaker, auditable-not-structural control.**
2. **The generator becomes the single point of failure.** A bug in schemagen makes all languages
   wrong *identically*, which is better than differently wrong but still wrong. *Response:* output is
   committed, so the diff is human-reviewable, and the parity suite compares behaviour, not just
   shape. Residual risk is real.
3. **abi3 excludes free-threaded CPython.** The stable ABI does not cover 3.13t/3.14t. If a
   GIL-free Python becomes the target, the wheel matrix goes from 7 to 7 × N and the "one wheel per
   platform" property is lost. This is a bet with a known expiry.
4. **The input that breaks it: a 40,000-page scanned PDF where the caller wants streaming.** DocBuf
   is a whole-document contiguous buffer; at 20 KB/page of blocks that is 800 MB in one allocation.
   *Response:* `convert_part()` and a driver declaring `GRANULARITY = PART` gets per-page buffers —
   which is exactly `mine-runtime.md` §7.12's unresolved question 1, and my substrate answer is
   *the FFI granularity is the `unit_part`*. But a DOCX is one XML stream: you cannot decode page 900
   without page 1. **A 512 MiB DOCX containing one enormous table is the input that breaks this
   design, and it breaks as `ResourceLimit{limit:"grid_slots"}` rather than an OOM** — the mechanism
   working as a refusal, not as a success.
5. **An out-of-tree driver opens its own SQLite connection.** S9's lint covers the monorepo only.
   *Response:* the store handle on `ctx` is a capability object with no path attribute, and
   `omniweave doctor` reports every process holding the WAL. I cannot fully prevent it, and a
   third-party driver *can* corrupt the pragma discipline.
6. **Lockstep versioning makes releases all-or-nothing.** graphrag's `graphrag-common==3.1.2` exact
   inter-package pin means no consumer takes a chunking patch without a whole-world bump.
   *Response:* lockstep for the kernel ↔ bindings ↔ schema set only (they share an ABI, so they
   must be); drivers and targets carry independent semver against `omniweave-abi ~= X.Y`.
   **Consequence: the ABI minor version is public API, and bumping it breaks every out-of-tree
   driver.** That is the reversibility cost of the FFI seam, priced in.
7. **Windows.** `canonical_uri` handles `\\?\` and case-folding; CRLF normalisation handles the diff
   gate; the `.cmd` shim hazard is real (codegraph: *"modern Node throws EINVAL when asked to spawn a
   `.cmd`/`.bat`"* — invoke `node.exe` against the entry directly). But the wheel matrix has exactly
   **one** Windows target: `aarch64-pc-windows-msvc` is unserved on day one, as it is for anydoc.
8. **Kernel bus factor.** If the org is Python-heavy, the Rust kernel becomes a bus-factor-1 asset —
   precisely the failure the risk register names for `lift` (1 author, 24 commits) and `olmocr`
   (88% one author). *Response:* the kernel is deliberately small and mechanical (decoders, limits,
   digests, DDL); every rule-heavy layer stays in Python; and the S7 Python reference implementation
   exists so the kernel is *replaceable*. That reference is the most expensive line item in this
   proposal and it is the reason the proposal is safe.
9. **A "fast path" grows a second parser.** The moment someone writes a Python DOCX reader "just for
   this one case", S1 and S7 are the only things stopping two document models. Both are CI gates, so
   the failure mode is a red build rather than silent divergence — but a reviewer can approve a
   `--bless`.

---

## 11. Why I reject the alternatives

**Pure Python.** Fails the stated requirement in two measurable ways. (a) Office ingest: median
**134.8 ms** (markitdown) to **513.6 ms** (docling) against anydoc's **4.4 ms** — 30× to 117×, and
the gap is interpreter overhead per XML node, not algorithm. (b) The canonical-JSON + sha256 digest
that every cache key depends on would have to be reimplemented identically in TypeScript for the OUT
side; graphrag's `gen_sha512_hash` concatenates without a separator so `["a","bc"]` and `["ab","c"]`
collide, in *one* language, written once. Two independent implementations of a digest is a
correctness bug waiting for a schedule. And the ecosystem gravity argument cuts the other way at the
substrate layer: `pip install docling` is 33 base deps including torch just to read a DOCX. A
Python-first *core* inherits that gravity; a Python *orchestrator* with out-of-tree drivers does not.

**Pure Rust with thin bindings and no Python orchestrator.** Loses the ecosystem outright. docling,
olmocr, vLLM, transformers, every graphrag prompt and every future VLM client are Python. A driver
author who must write Rust will not write the driver, and a framework whose plugin surface is
uninhabited is not a framework. Separately, the rule-heavy layers are the wrong shape for Rust
iteration speed: ppt-master's validator is 9,368 lines of rules in one class.

**TypeScript everywhere.** codegraph disproves the naive performance objection — 70,000 files /
2M symbols / 6.4M relationships in under 12 minutes on a 2-core 6 GB VPS. But it (a) cuts you off
from every Python model runtime, (b) forces Node on every IN user, not just OUT users, and (c) is
self-refuting on the hot path: codegraph's own answer to extraction throughput was to write a **Rust
napi kernel** and then maintain 13 parity test files to keep it honest. If the fastest TS project in
the collection reached for Rust for extraction, a TS-only omniweave would reach for it too — and
would then be a TS project with a Rust kernel and no Python, i.e. this proposal minus the ecosystem.

**Polyrepo.** The schema is cross-language, so a schema change cannot be atomic, and there is a
window in which the projections disagree that no CI job can observe. Everything else about polyrepo
is a preference; this is a correctness hole.

**One fat distribution with extras** (docling's and DataFlow's model). Extras cannot express "these
two cannot coexist". DataFlow's 20 extras include four mutually incompatible vLLM pins; `[kbc]` +
`[mineru]` is unsatisfiable and pip reports it as a resolution failure in *your* package. Separate
distributions make each driver an independent resolver root, so the conflict is reported where it
lives.

**In-process Node** (a Rust↔V8 embed, or napi-into-Python). Two GCs and two event loops in one
address space, no fault isolation, and a Chromium crash takes down the process holding the store's
WAL writer. The process boundary buys failure isolation and per-target dependency weight for
~120 ms.

**Protobuf/gRPC as the universal internal contract.** Overhead where I need zero (per-unit FFI),
ceremony where I need a file (canonical JSON at rest), and proto3's all-optional field model
actively defeats "every block carries `origin_operator` and `confidence`". Fixed-width buffers plus
canonical JSON plus a generated JSON Schema is strictly more precise here.

---

## 12. Build order for this decision

1. `omniweave-model` + `omniweave-schemagen --check` in CI, emitting **all** projections. Nothing
   else is safe to build first. (S1, S13)
2. `omniweave-limits` + `omniweave-error` + 12 cargo-fuzz targets, one per format handler. (S15)
3. `omniweave-digest` + `omniweave-uri`, with property tests against a filesystem fixture that
   writes same-length content inside one mtime tick.
4. `omniweave-abi` + the three loaders + the stale-stub degradation test. (S8)
5. `bindings/python` (abi3) + the 7-target wheel matrix + `check-versions.sh` as job 1. (S2)
6. `py/omniweave`: the registry with metadata-only discovery, the allowlist, `probe()`,
   `show-config`, `drivers list`. (S6)
7. The four policy gates: `weight-gate`, `import-graph-scan`, `licence-gate`, `coldstart`.
   (S4, S5, S11, S12)
8. `omniweave-store` with codegraph's pragma order, heal-on-open and the WAL valve. (S9)
9. `bindings/wasm` + the parity suite. (S3b, S7)
10. `omniweave-target-pptx` (no Node). Only then `omniweave-target-node` and the stdio protocol.

Steps 1–7 are the substrate. A judge should read steps 1 and 7 as the two that cannot be deferred:
the schema generator, because retrofitting it means rewriting three languages at once; and the gates,
because every one of them exists to catch a defect that was *shipped* by a repo in this collection.

---

## Appendix — evidence index

| Claim | Source |
|---|---|
| anydoc 4.4 ms vs markitdown 134.8 / docling 513.6 / LibreOffice 1129.5 ms median | `_collections/anydoc/README.md:176` (self-authored harness; caveat stated in `_index/comparisons.md:48-59`) |
| anydoc: 1 crate + node/python/wasm bindings, 8 runtime deps, MIT | `_collections/anydoc/Cargo.toml` |
| abi3-py310 ⇒ one wheel per platform for CPython 3.10+ | `_collections/anydoc/python/Cargo.toml` |
| 7 napi targets; 7 wheel targets; version gate over 5 locations as job 1 | `_collections/anydoc/node/package.json`, `.github/workflows/release.yml:20-38,312-338`, `scripts/check-versions.sh` |
| graphrag: 8-package uv workspace, private root, lockstep `==3.1.2` | `_collections/graphrag/pyproject.toml:2-4,58-68,81-88`; `packages/graphrag-chunking/pyproject.toml` |
| `graphrag-storage` forces azure-cosmos/identity/storage-blob + pandas | `_collections/graphrag/packages/graphrag-storage/pyproject.toml` |
| docling: 33 base deps incl. torch, torchvision, accelerate, scipy | `_collections/docling/pyproject.toml:45-79` |
| docling's `allow_external_plugins` gate is applied **after** the import | `_collections/docling/docling/models/factories/base_factory.py:90-105` |
| markitdown loads every plugin entry point into a module global, warn-on-failure | `_collections/markitdown/packages/markitdown/src/markitdown/_markitdown.py:62-82` |
| markitdown core: 6 deps + per-format extras; `markitdown.plugin` entry-point group | `_collections/markitdown/packages/markitdown/pyproject.toml:28-60`; `packages/markitdown-ocr/pyproject.toml:56` |
| codegraph: optional Rust napi kernel, ABI-versioned, kill switch, wasm fallback | `_collections/codegraph/src/extraction/kernel/loader.ts:1-24`, `layout.ts:1-20` (`KERNEL_ABI_VERSION = 2`) |
| codegraph: 13 kernel parity test files | `_collections/codegraph/__tests__/kernel-*-parity.test.ts` |
| codegraph: vendored-Node per-platform bundles, zero native addons, npm optionalDependencies | `_collections/codegraph/BUNDLING.md:1-60` |
| hyperframes: 14 lockstep packages except `sdk-playground` 0.6.106; ffmpeg/chromium confined to `aws-lambda` | `_collections/hyperframes/packages/*/package.json` |
| open-slide: unedited template SECURITY.md, root `version = 0.0.0` | `_collections/open-slide/SECURITY.md:1-20`, `package.json` |
| DataFlow: 20 extras, 4 incompatible vLLM pins | `mine-runtime.md` §1.10 (L875-921) |
| 7–19 s Python package import cost vs ~1 s native call | `mine-graph.md:1472-1481` (graphify `cluster.py:22-40`) |
| anydoc limits, `ConvertError`, 12 fuzz targets, no HTTP client | `DIGEST.md` risk §, `mine-parse.md` A6.4/A6.5 |
| WAL pragma order, valve thresholds, 25.6 GB leak, 22 GB + exit 137 | `mine-runtime.md` §4.6.1-4.6.2 |
| Transitive denylist, pin policy by role, vendored-binary four-part rule | `mine-risk.md` §18.2, §18.3 |
| Operator contract, `RunContext`, three roots, registry duplicate-name rule | `mine-runtime.md` §7.1-7.2, §7.10.3-7.10.4 |
