# D1-substrate — Language, runtime substrate, and repository/package layout

## Decision

omniweave is a **Python 3.11+ framework** laid out as **one repository, one `uv` workspace, one
lockfile, eleven first-party distributions sharing a single `RELEASE` version**, whose foundation
distribution `omniweave-core` has **zero third-party dependencies**. Compiled code exists in exactly
one place and **we do not compile it**: the office/text/CSV/EPUB/RTF decoder is the already-published
MIT `abi3` wheel `firecrawl-anydoc`, consumed in-process behind the `omniweave-office` driver, with
its source vendored at a recorded SHA and a written fork trigger. TypeScript exists only as
**Toolchains** — digest-pinned, non-Python execution bundles invoked as a child process over the
`omniweave-target/1` NDJSON-on-stdio protocol with a **job directory** as the data plane — so no
`pip install` ever pulls Node, and the flagship OUT target (PPTX) is pure Python. There is **no
first-party Rust kernel, no cross-language document model, and no IDL**: the L2 model never crosses a
language boundary, so the language-neutral contract is *generated* JSON Schema emitted from the
Python definitions, committed, and byte-diff gated. Third-party drivers are separate distributions in
separate repositories, **discovered by entry point without importing anything and activated only by
name in `omniweave.toml`**. Day one builds eleven `py3-none-any` wheels on one runner: no
`manylinux`, no `maturin`, no Zig, no napi in omniweave's own CI.

## Spec

**Language and floor.** Python, `requires-python = ">=3.11"`, no upper bound in `omniweave-core` or
`omniweave`. 3.11 is forced, not preferred: `olmocr/pyproject.toml:21` is `>=3.11` and
`graphrag/packages/graphrag-chunking/pyproject.toml` is `>=3.11,<3.14`, and 3.11 supplies `tomllib`
(which `graphrag-common` carries `toml~=0.10` for want of), `StrEnum` (which makes marker's
`(str, Enum)` + `auto()` bug — block-type values serialising as `"1"`, `"2"` — unwritable),
`TaskGroup`, `ExceptionGroup` and `typing.Self`. Upstream Python ceilings live in the distribution
that owns them: `omniweave-graph` inherits graphrag's `<3.14`, and a user on 3.14 still gets parse,
store, serve and PPTX plus a `doctor` line naming the gap.

**Why not a Rust kernel of our own.** The requirement that would justify one — a document model three
languages must agree on byte-for-byte — does not exist under this ruling. OUT targets consume an
intermediate language that is *text and blobs on disk*; the only thing crossing to a toolchain is a
job envelope, a receipt, and plain `sha256` over bytes, on which every language already agrees.
Canonical-JSON digesting (`content_digest`, `config_digest`) therefore has exactly one
implementation, in Python, and no second implementation can drift from it. Meanwhile the one seam
where compiled speed is load-bearing is already solved by someone else's MIT code: `anydoc` is eight
Rust dependencies with **no HTTP client of any kind**, 12 `cargo-fuzz` targets, compile-time limit
constants, a typed `ConvertError` taxonomy, and `pyo3 = { features = ["abi3-py310"] }` so its release
matrix is seven wheels rather than seven times N. Its `release.yml` (version gate as job 1, PyPI
trusted publishing, skip-if-already-published, seven wheel targets, seven napi targets) is the
pipeline we would otherwise have to write. Building it ourselves is the mistake in the other
direction.

**Why not vendor-fork it on day one either.** anydoc's document model has **no spatial provenance of
any kind** — `grep -rn "bbox\|BoundingBox\|polygon" _collections/anydoc/src/` returns one unrelated
ODF shape-name match — so "extend the vendored crate's model with polygons and `CoordOrigin`" is not
a change to a vendored crate, it is layout engineering a non-rendering decoder cannot do. And the two
fields most often cited as needing to be in the decoder, `origin_operator` and `confidence`, are
store columns the **runner** writes from `StepResult` (`mine-runtime.md` §7.6.1), never fields a
producer emits. So the adapter mapping anydoc's `Document` into omniweave's L2 belongs in Python, in
`omniweave-office`, and the fork is a priced option we hold, not a cost we pay before shipping.

**The store is Python, and this is where I overrule both compiled-kernel proposals.** The store is
the T1→T2→T3 distribution boundary (`mine-runtime.md` §7.10.2) and T3 is Postgres. A Rust crate that
speaks Postgres has a network client, forfeiting the exact property (`cargo tree` clean of
`reqwest`/`hyper`/`ureq`, buildable for `wasm32-unknown-unknown`) used to justify the kernel's
in-process seat; the alternative — SQLite in Rust, Postgres in Python — puts two implementations
behind the claim protocol, the one place two implementations are least affordable.
`omniweave_core.store` is therefore the **only** module permitted to call `sqlite3.connect`, and that
is a lint rule, so codegraph's pragma ordering (`busy_timeout` *before* `journal_mode`, or a
contended open crashes — #238), heal-on-open for an oversized WAL, the proportional WAL valve with
its futility latch, and jcodemunch's `connect_readonly` ladder (`mode=ro` when a WAL sidecar exists,
`mode=ro&immutable=1` when it does not) are applied by every reader — hook, CLI, MCP server, second
process. SQLite is not guaranteed: FTS5 absence and `sqlite_version < 3.35` (no
`UPDATE … RETURNING`) are **named capability probes** with a stated remedy, and the claim protocol
ships a `BEGIN IMMEDIATE` + `UPDATE` + `SELECT` fallback so an enterprise-LTS SQLite degrades rather
than fails.

**Core purity.** `omniweave-core` depends on nothing outside the standard library, enforced by a gate
that resolves it in a clean environment and asserts exactly one distribution. This is not minimalism
for its own sake: `import omniweave_core` is on the per-turn path of every hook and CLI call, and
pydantic's compiled `pydantic_core` is a fixed tax there. It is affordable because the operator
config surface is flat and JSON-canonicalisable *by contract* (`mine-runtime.md` §7.1.1) — exactly
the shape ~250 lines of property-tested scalar coercion handles. Consequence, stated because it binds
D3 and D6: **driver configuration is `Mapping[str, Scalar]`, not a pydantic model**; unknown keys are
preserved verbatim and enter `config_digest`, and an un-canonicalisable config value is a startup
error, never a `str()` fallback (graphrag's permanent silent 100% cache miss).

**Distributions, not extras.** DataFlow ships 20 extras of which four pin mutually incompatible vLLM
ranges (`vllm>=0.7.0,<=0.9.2` / `<0.8` / `<0.9` / `==0.6.3`), so `[kbc]`+`[mineru]` is unsatisfiable,
under a `requires-python = ">=3.7, <4"` that is a lie by three minor versions and an Apache-2.0
`license` contradicted by a `"License :: Free For Educational Use"` classifier. Extras cannot express
"these two cannot coexist"; separate distributions can, because each is an independent resolver root.
So every driver family is its own distribution, and `omniweave`'s extras are a **1:1 alias map onto
`omniweave-*` siblings** — an extra may name a sibling and nothing else, and there is no `[all]`.
`pip install omniweave[vision]` and `pip install omniweave-vision` resolve identically.

**Discovery is not consent, and discovery does not import.** `markitdown-ocr` self-registers through
`entry_points(group="markitdown.plugin")` and hard-requires AGPL PyMuPDF; docling is better and still
wrong in a checkable way — `base_factory.py:95-105` calls `load_setuptools_entrypoints` (which
imports every plugin module) and applies the `allow_external_plugins` gate *after* the import. So the
catalog is built from `importlib.metadata` alone, the entry-point value is a string that is never
`load()`ed, and each driver's capabilities come from an `omniweave-driver.toml` located through
`importlib.metadata.distribution(...).locate_file(...)` and read with `tomllib` — zero Python
executed. Activation requires the driver's dotted registry key in `omniweave.toml [drivers] enabled`.
A discovered-but-unenabled driver is reported by `omniweave doctor` with its distribution, version
and declared SPDX. `register()` raises on a duplicate name unless `replace=True`, closing DataFlow's
first-wins-silent registry.

**Limits are a ceiling, not a setting.** anydoc's twelve constants are the maximum; a tenant cap
clamps *down* (`effective = min(tenant_cap, MAX)`), widening past a maximum is a fork rather than a
flag, and a breach is `ResourceLimit{limit}` naming which knob would need raising.

**Three seams, and no fourth.** (S1) In-process FFI, `omniweave-office` only, one call per document,
`py.detach` releasing the GIL for the decode. (S2) One `omniweave-target/1` child process per
artefact, argv plus a job directory plus NDJSON on stdio — never HTTP, because a local server that
writes files needs open-slide's 76-line CSRF guard as a *minimum*, and never a socket, because
LEANN's embedding server is unauthenticated ZMQ on a dynamic loopback port. (S3) Attach-or-spawn
HTTP model servers for GPU VLMs only, with surya's model-id verification on attach and lazy spawn, so
a clean digital document never starts a GPU server. A long-lived local IPC daemon for parsing,
embedding or indexing is banned; if a later decision needs one it is a unix socket or named pipe at
0600, never a loopback port.

**CI.** Eleven `py3-none-any` wheels built once on Linux; tests on {ubuntu, macos, windows} ×
{3.11, 3.12, 3.13}; toolchains built only when `toolchains/**` changes; sixteen fail-not-warn gates
with version agreement as job 1; PyPI trusted publishing from a workflow file whose name must never
change.

## Concrete shape

```
omniweave/                                  ONE repo · Apache-2.0 · one RELEASE · one uv.lock
├── LICENSE  NOTICE  LICENSES/  THIRD_PARTY.md      (last two GENERATED, --check gated)
├── pyproject.toml            uv workspace root, NOT publishable
├── uv.lock                   committed
├── codes.toml                the error-code register — append-only
├── omniweave.toml.example
│
├── packages/
│   ├── omniweave-core/         src/omniweave_core/          STDLIB ONLY
│   │   ├── contract.py           CONTRACT: int; CONTRACTS_SUPPORTED: frozenset[int]
│   │   ├── model/                the L2 document model — D2 owns the fields
│   │   ├── operator.py           OperatorABC, OperatorIdentity, StepResult, RunContext, Roots
│   │   ├── registry.py           Registry[T]; scope = "run" | "shared"; duplicate ⇒ raise
│   │   ├── discovery.py          metadata-only catalog; NEVER EntryPoint.load()
│   │   ├── identity.py           canonical_uri, content_digest, config_digest, stat index
│   │   ├── canonical.py          sha256_canonical(obj) — allow_nan=False, sorted, separator-safe
│   │   ├── limits.py             anydoc's 12 constants as MAX_*; effective = min(cap, MAX_*)
│   │   ├── errors.py             OwError tree; .code() (codes.toml); .is_fatal(); .fix
│   │   ├── store/                sqlite.py — THE ONLY sqlite3.connect in the framework
│   │   ├── cache.py              three-group key; two invalidation tiers
│   │   ├── toolchain.py          THE ONLY subprocess seam; omniweave-target/1 client
│   │   ├── modelserver.py        attach-or-spawn HTTP client (surya shape)
│   │   ├── probe.py              capability probes; verdict cached per run
│   │   └── config.py             flat scalar coercion (~250 lines), source-tracked
│   ├── omniweave/              src/omniweave/{cli,plan,router,install,doctor}/
│   ├── omniweave-office/       src/omniweave_office/          parse.office.anydoc
│   ├── omniweave-pdf/          src/omniweave_pdf/             parse.pdf.pdfium
│   ├── omniweave-vision/       src/omniweave_vision/          ocr.page.olmocr, vlm.*
│   ├── omniweave-graph/        src/omniweave_graph/           structure.*
│   ├── omniweave-serve/        src/omniweave_serve/           MCP stdio+HTTP, hooks, llms.txt
│   ├── omniweave-target-pptx/  src/omniweave_target_pptx/     target `pptx` (+ parse_back)
│   ├── omniweave-target-deck/  src/omniweave_target_deck/     toolchain manifest only
│   ├── omniweave-target-video/ src/omniweave_target_video/    toolchain manifest only
│   └── omniweave-conform/      src/omniweave_conform/         pytest plugin: conformance kit
│
├── toolchains/                 TypeScript. Its own package manager. NOT a Python dependency.
│   ├── pnpm-workspace.yaml  pnpm-lock.yaml
│   ├── deck/   package.json  src/*.ts        open-slide-derived
│   └── video/  package.json  src/*.ts        hyperframes-derived
│
├── schema/                     GENERATED from Python, committed, byte-diff gated
│   ├── document-v1.json  job-v1.json  receipt-v1.json
│   ├── driver-manifest-v1.json  run-manifest-v1.json
│   └── expected/               golden render; `--bless` to update
│
├── vendor/                     third-party source at a recorded SHA
│   ├── anydoc/                 SHA · LICENSE · NOTICE · .sha256 · FORK-TRIGGER.md
│   └── graphify-security/      security.py at a pinned SHA + NOTICE
│
├── tools/
│   ├── layers.toml  weights.toml  licences.toml  vendor.toml
│   ├── schemagen.py            emit | --check | --bless
│   ├── check_versions.py       every declaration site + the git tag
│   ├── gate_*.py               core_pure weights licences layers importtime coldstart egress
│   └── semgrep/omniweave.yaml
├── fixtures/                   40-byte docx · encrypted pdf · zip bomb · 4M-cell xlsx · fuzz corpus
└── .github/workflows/{ci.yml,release.yml}      release.yml MUST NOT be renamed (OIDC binding)
```

```
DISTRIBUTIONS — 11 first-party, one shared RELEASE, all py3-none-any

dist                     import pkg               third-party deps                    ceiling
omniweave-core           omniweave_core           (none — gate G1)                      3 MB
omniweave                omniweave                core, office                         25 MB
omniweave-office         omniweave_office         core, firecrawl-anydoc==0.2.4        15 MB
omniweave-pdf            omniweave_pdf            core, pypdfium2, defusedxml          30 MB
omniweave-serve          omniweave_serve          core, mcp                            40 MB
omniweave-target-pptx    omniweave_target_pptx    core, python-pptx, XlsxWriter,       60 MB
                                                  skia-pathops, uharfbuzz, Pillow
omniweave-graph          omniweave_graph          core, tree-sitter, graphrag-chunking 150 MB
omniweave-vision         omniweave_vision         core, torch, transformers         UNBOUNDED
omniweave-target-deck    omniweave_target_deck    core                                  1 MB
omniweave-target-video   omniweave_target_video   core                                  1 MB
omniweave-conform        omniweave_conform        core, pytest                          3 MB

AGGREGATE GATE: `omniweave[recommended]` = serve + pdf + target-pptx ≤ 250 MB installed
                (the AWS Lambda unzipped-layer limit).  omniweave-vision is exempt and
                MUST print its resolved installed size during `omniweave doctor`.

INSTALL MATRIX
  pip install omniweave                 CLI + office parse. No torch, no Node, no browser.
  pip install omniweave[serve]          + MCP stdio/HTTP
  pip install omniweave[pdf]            + born-digital PDF
  pip install omniweave[pptx]           + the PPTX target                (still zero Node)
  pip install omniweave[recommended]    serve + pdf + pptx
  pip install omniweave[deck]           the deck target manifest; then `omniweave targets install deck`
  pip install omniweave[vision]         opts in to torch. Their choice, stated in the extra's docs.
  pip install omniweave-driver-<x>      a third-party driver. Discovered; inert until enabled.
  RULE: an extra on `omniweave` may name ONLY an `omniweave-*` sibling.  No `[all]`.  (Gate G14)
```

```toml
# pyproject.toml — workspace root (graphrag's verified shape)
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
omniweave-core = { workspace = true }        # … one row per sibling

[dependency-groups]
dev = ["pytest~=9.1", "pytest-xdist", "ruff", "pyright", "semgrep", "hypothesis"]
```

```toml
# packages/omniweave-core/pyproject.toml — the zero-dependency foundation
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omniweave-core"
version = "0.1.0"                     # == RELEASE.  Gate G5.
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
requires-python = ">=3.11"            # NO upper bound.
dependencies = []                     # ENFORCED BY GATE G1. Amending this amends D1.

[project.optional-dependencies]
# Only ever a capability REMEDY named by the probe that fails. Never a feature.
sqlite = ["pysqlite3-binary>=0.5"]    # interpreter SQLite lacks FTS5, or is < 3.35
```

```toml
# packages/omniweave-office/pyproject.toml — a first-party driver distribution
[project]
name = "omniweave-office"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "omniweave-core ~= 0.1.0",          # siblings track core at the MINOR level
  # Exact pin: single-vendor, 3 months old, `pdf-inspector = "1.14.2"` unaudited.
  # MIT source vendored at vendor/anydoc/. Fork trigger: vendor/anydoc/FORK-TRIGGER.md.
  "firecrawl-anydoc == 0.2.4",
]

[project.entry-points."omniweave.drivers"]
"parse.office.anydoc" = "omniweave_office.driver:AnydocOfficeDriver"
```

```toml
# omniweave-driver.toml — shipped as package data. Read WITHOUT importing the driver.
# Located via importlib.metadata.distribution(dist).locate_file("<toplevel>/omniweave-driver.toml")
# where <toplevel> is the first dotted segment of the entry-point value. Missing ⇒ the driver
# is reported `manifest-missing` and is NEVER loaded.  (Gate G11)
schema   = 1
name     = "ocr.page.olmocr"          # THE registry key. Grammar: <kind>.<family>.<impl>
contract = 1                          # must be in omniweave_core.CONTRACTS_SUPPORTED

[capability]                          # D3 owns the full field set; D1 fixes these five
kind        = "ocr"                   # parse | ocr | vlm | embed | llm | structure | connect
cost_class  = "BILLED_API"            # FREE | LOCAL_COMPUTE | BILLED_API
granularity = "PART"                  # DOCUMENT | PART | CORPUS
formats     = ["pdf", "png", "jpeg", "tiff"]
deterministic = false

[[probe]]                             # run the smallest REAL operation, not an import check
kind = "http_model"
url_config_key = "drivers.'ocr.page.olmocr'.endpoint"
assert = "model_id_matches"           # surya's GET /v1/models check on attach

[licence]
code             = "Apache-2.0"
weights          = "Apache-2.0"       # REQUIRED when the driver downloads weights
weights_revision = "a1b2c3d4e5f6…"    # exact SHA. `main` fails gate G8.
notice           = "NOTICE"

[egress]
default = "none"                      # none | configured_endpoint | internet
hosts   = []                          # allowlist; asserted by the socket-blocked conformance run
```

```toml
# omniweave.toml — the user-facing config. Line 1 is the grammar version.
schema = 1

[roots]                               # THREE ROOTS, ALWAYS SEPARATE (graphify #1774)
source = "."                          # the identity anchor; cache salt is relative to this
output = ".omniweave/out"
cache  = ".omniweave/cache"           # a cache_root inside source_root is a STARTUP ERROR

[store]
backend = "sqlite"                    # sqlite (shipped) | postgres (D5, later)
path    = ".omniweave/index.db"

[limits]                              # clamps BELOW omniweave_core.limits MAX_*; never above
max_entry_bytes = 33554432            # MAX_ENTRY_BYTES = 134217728

[drivers]                             # DISCOVERY IS NOT CONSENT. Unlisted ⇒ reported, never loaded.
enabled = ["parse.office.anydoc", "parse.pdf.pdfium"]
[drivers."parse.pdf.pdfium"]
dpi = 192

[targets]
enabled = ["pptx"]
[targets.video]
ffmpeg = "system"                     # never "bundled" — libx264 makes a bundle GPL-2.0-or-later
codec  = "vp9"                        # h264 is an operator-owned opt-in, not a fallback

[budget]
per_document_micros = 20000           # a HARD currency cap, not a retry count
max_inflight = { FREE = 32, LOCAL_COMPUTE = 4, BILLED_API = 2 }

# Precedence: --config <path> > ./omniweave.toml (walking up to .git or root) >
#             [tool.omniweave] in pyproject.toml (only if no omniweave.toml) >
#             $OMNIWEAVE_HOME/config.toml > built-in defaults.
# Env: every key has an OMNIWEAVE_* twin, resolved ONCE at startup.
# `omniweave show-config` prints each resolved value WITH ITS SOURCE; `--digest` prints config_digest.
# $OMNIWEAVE_HOME defaults to ~/.omniweave and holds toolchains/ and the probe verdict cache.
```

```python
# omniweave_core/contract.py — the whole substrate ABI surface
CONTRACT: int = 1
CONTRACTS_SUPPORTED: frozenset[int] = frozenset({1})
# A driver whose manifest `contract` is absent from CONTRACTS_SUPPORTED is refused with a message
# naming both integers, the distribution and its version.  Never a silent skip.  (Gate G16)

# omniweave_core/discovery.py — metadata only. Imports NOTHING from any driver.
@dataclass(frozen=True)
class DriverCard:
    name: str            # "ocr.page.olmocr" — the registry key
    kind: str            # parse | ocr | vlm | embed | llm | structure | connect
    contract: int
    dist: str
    dist_version: str
    module: str          # a STRING. Never imported here.
    manifest: Mapping[str, Any]     # parsed omniweave-driver.toml
    enabled: bool                   # present in omniweave.toml [drivers] enabled
    status: Literal["ok", "manifest-missing", "contract-mismatch", "probe-red"]

def catalog() -> tuple[DriverCard, ...]: ...        # ≤ 20 ms for 20 installed drivers

# omniweave_core/toolchain.py — THE ONLY module permitted to import `subprocess`  (Gate G8)
@dataclass(frozen=True)
class ToolchainSpec:
    name: str                       # "deck" | "video"
    version: str
    sha256: str                     # FULL digest. hash[:16] is 64 bits — weak against intent.
    entry: tuple[str, ...]          # ("dist/render.mjs",) — argv after the resolved node
    node_range: str                 # ">=20 <25"

@dataclass(frozen=True)
class ToolchainResult:
    outcome: Outcome                # the SAME enum as StepResult. No magic values.
    receipt: Mapping[str, Any]      # validated against schema/receipt-v1.json
    stderr_tail: tuple[str, ...]    # bounded ring: 8 samples + a 4-line tail
    queued_ms: int                  # separate from ran_ms: a contended lock and slow work are
    ran_ms: int                     # indistinguishable from the outside (jcodemunch §5.3)

def run(spec: ToolchainSpec, job_dir: Path, *, timeout_s: int, ctx: RunContext) -> ToolchainResult:
    """Resolve node -> verify FULL sha256 -> probe (cached per run) -> spawn -> drain -> reap.

    Node resolution, in order:
      1. $OMNIWEAVE_NODE
      2. $OMNIWEAVE_HOME/toolchains/<name>@<version>-<sha256>/node[.exe]
      3. `node` on PATH, IF it satisfies spec.node_range
      none  -> the target is PRUNED FROM THE PLAN WITH A REPORT naming
               `omniweave targets install <name>`. Never an ImportError, never a substitution.

    Invariants:
      * cwd is ALWAYS job_dir, never inherited          (graphify: four recorded CWD bugs)
      * env is a constructed allowlist, never os.environ
      * SIGTERM at timeout, SIGKILL at timeout+5s, the whole process group reaped, both recorded
      * a digest mismatch is FAILED_PERMANENT(TOOLCHAIN_DIGEST) and NEVER triggers a fetch
      * on Windows, invoke node.exe against the entry directly — modern Node throws EINVAL on
        a .cmd/.bat  (codegraph's recorded scar)
      * refuse rather than substitute a codec: libvpx/AV1 absent => refuse the mp4 target
    """
```

```
JOB DIRECTORY — the Python <-> Toolchain data plane. Blobs NEVER travel on stdio.
<cache_root>/jobs/<run_id>/<unit_digest>/
├── job.json        written by Python; validated against schema/job-v1.json
├── il/             the intermediate language: canonical SVG / TSX / HTML — TEXT ON DISK
├── assets/         frozen media, content-addressed, one media-ledger row each
└── out/            written by the toolchain: the artefact + receipt.json
```

```jsonc
// omniweave-target/1 — NDJSON on stdio. stdout is CONTROL ONLY, < 1 MiB per invocation.
// stderr is a log, drained to a bounded ring tail, and NEVER parsed.
// -> child, always first
{"t":"hello","proto":"omniweave-target/1","run_id":"01JBQ…","job_dir":"…","schema":1,
 "limits":{"wall_ms":600000,"rss_bytes":4294967296,"out_bytes":2147483648},
 "determinism":{"seed":0,"clock_ns":0}}
// <- child, always first: the in-band capability probe
{"t":"ready","target":"video","version":"0.1.0","proto":"omniweave-target/1",
 "capabilities":{"parse_back":false,"assets":true},
 "external":[{"name":"ffmpeg","found":true,"version":"7.1","encoders":["libvpx-vp9","libopus"]}]}

{"t":"validate","id":1,"il":"il/main.tsx"}
{"t":"progress","id":1,"pct":40,"note":"page 5/12"}          // rate-limited to 4/s
{"t":"result","id":1,"status":"blocked","findings":[
  {"code":"OW-T-311","severity":"error","provenance":"introduced","at":"il/main.tsx:41:9",
   "msg":"mix-blend-mode requires bake","fix":"omniweave compile --bake p03/title"}]}
{"t":"compile","id":2,"il":"il/main.tsx","out":"out/q3.webm"}
{"t":"result","id":2,"status":"ok","receipt":"out/receipt.json"}
{"t":"bye"}

// exit 0 ok · 2 validation blocked · 3 resource limit · 4 protocol error
// exit 64 required capability missing (named in the last error line)
// EXIT 0 IFF a receipt was written. No other success signal exists.
// The parent drains stdout on a dedicated thread into an unbounded queue: the pipe never deadlocks.
```

```toml
# tools/layers.toml — the import DAG (gate G4).  An arrow means "may import".
# Rationale: mine-risk.md §4.8 — an L5 layer must never be a dependency of an L1 parser.
omniweave_core         = []
omniweave_office       = ["omniweave_core"]
omniweave_pdf          = ["omniweave_core"]
omniweave_vision       = ["omniweave_core"]
omniweave_graph        = ["omniweave_core"]
omniweave_serve        = ["omniweave_core"]
omniweave_target_pptx  = ["omniweave_core"]
omniweave_target_deck  = ["omniweave_core"]
omniweave_target_video = ["omniweave_core"]
omniweave_conform      = ["omniweave_core"]
omniweave              = ["omniweave_core", "omniweave_office"]
```

```toml
# tools/licences.toml — the denylist that MUST catch cairosvg
mode = "fail"                                   # never "warn"
scan = ["resolved-graph", "import-graph", "unpacked-artifacts"]   # ALL THREE
deny_spdx  = ["AGPL-*", "GPL-*", "LGPL-3.0*", "OpenRAIL*", "SSPL*", "*-Proprietary"]
deny_names = [
  "PyMuPDF", "pymupdf", "fitz",        # AGPL; MANDATORY dep of leann-core and markitdown-ocr
  "mineru",                             # AGPL; DataFlow's PDF path
  "pypandoc-binary",                    # bundles GPL-2.0+ pandoc inside a wheel
  "ffmpeg-static", "ffprobe-static",    # libx264 ⇒ GPL-2.0-or-later binary in a deploy artefact
  "cairosvg",                           # LGPL-3.0; UNDECLARED import in ppt-master's media.py
  "marker-pdf", "surya-ocr", "texify", "lift",   # OpenRAIL-M weights: clause 2(c) + clause 8
  "curl_cffi",                          # TLS-fingerprint impersonation
  "edge-tts",                           # undocumented Microsoft endpoint
]
# LGPL/GPL external binaries: permitted ONLY as a spawned process, never bundled, never linked.
external_only = ["pandoc", "ffmpeg", "libreoffice", "poppler-utils", "tesseract"]
```

```
THREE VERSION AXES
  RELEASE   semver, one git tag, one changelog. EVERY first-party distribution carries it.
            Siblings depend on `omniweave-core ~= <MAJOR>.<MINOR>.0`, so a core patch flows
            without re-releasing eleven distributions. CONTRACT may change only on a MINOR bump.
  CONTRACT  small int in omniweave_core.contract. What a THIRD PARTY pins. Bumping it is an
            announced, migration-guided product event.
  SCHEMA    small int; the L2 model + the store schema. Owned by D2/D5; declared here so the
            three axes exist from day one and nothing invents a fourth.

CI (.github/workflows/ci.yml)
  gates       ubuntu × 3.11        G1..G16, fails fast, ~2 min
  test        {ubuntu, macos, windows} × {3.11, 3.12, 3.13} = 9
  toolchains  ubuntu × node 20     `if: changed(toolchains/**)`
  build       ubuntu × 3.11        11 sdists + 11 wheels, all py3-none-any, one runner
  publish     on tag v*            PyPI trusted publishing (OIDC). release.yml MUST NOT be renamed.

THE SIXTEEN GATES — every one names a defect a repo in _collections/ actually shipped
  G1  omniweave-core resolves to exactly ONE distribution                (docling: torch is base)
  G2  no distribution exceeds tools/weights.toml; aggregate ≤ 250 MB     (Lambda layer limit)
  G3  licences: resolved graph AND import graph AND unpacked artifacts   (cairosvg; ffmpeg-static)
  G4  module graph obeys tools/layers.toml                               (mine-risk §4.8)
  G5  every version declaration site agrees, and matches the tag  [JOB 1] (anydoc: 5 sites)
  G6  `omniweave schema emit --check` byte-diff, CRLF-normalised          (LEANN's llms.txt)
  G7  a constraint tighter than `>=` carries a comment                    (local-deep-research)
  G8  semgrep: no os.getcwd / Path(".") / bare subprocess outside toolchain.py / time.time() /
      sys.exit in library code / bare except around identity fns / revision="main"
  G9  `import omniweave_core` under -X importtime loads ZERO third-party modules
  G10 cold start on 3 OSes vs a recorded per-OS baseline, 25% drift tolerance
  G11 discovery never imports: install a rogue driver whose module body writes a file and
      raises SystemExit; assert `omniweave doctor` succeeds and the file is absent
  G12 every vendored artefact has sha256 AND a parity test AND an arch assertion AND a NOTICE row
  G13 codes.toml is append-only against the previous tag
  G14 no extra named all/everything; every `omniweave` extra names only an omniweave-* sibling
  G15 no egress compiled in: hostname-literal grep vs allowlist + socket-blocked conformance run
  G16 contract compat: the previous TWO releases' conformance-template drivers load against HEAD

COLD-START BUDGETS (gate G10)
  import omniweave_core                     ≤  80 ms
  omniweave --version                       ≤ 150 ms
  omniweave --help                          ≤ 250 ms
  driver discovery, 20 installed            ≤  20 ms      (dist-info only; imports nothing)
  omniweave query, warm store               ≤ 250 ms

ERROR CODES — codes.toml, append-only, never renumbered, never reused.
  OW-C-nnn core (config · identity · cache · plan)      OW-S-nnn store
  OW-D-nnn driver (incl. parse failures)                OW-T-nnn target
  OW-P-nnn policy (licence · egress · limits · budget)
  Every message ends with the exact command that clears it.  `omniweave explain OW-D-012`.

ENTRY-POINT GROUPS
  omniweave.drivers    <kind>.<family>.<impl>   e.g. parse.office.anydoc, ocr.page.olmocr
  omniweave.targets    <artefact>               e.g. pptx, docx, deck, video
  omniweave.operators  RESERVED. Not created: operators are first-party until D3/D6 shows a
                       third-party operator that a driver cannot express.

NAMES FIXED HERE
  console scripts: `omniweave` and `ow`     env prefix: OMNIWEAVE_     state dir: .omniweave/
  user home: $OMNIWEAVE_HOME (default ~/.omniweave)   config: omniweave.toml
  third-party driver distributions SHOULD be named omniweave-driver-<name>; the framework does
  not care, because the registry key comes from the entry point, not the distribution name.
```

## Rationale

The three proposals agreed on more than they disagreed on — monorepo for first-party, polyrepo for
third-party drivers, distributions rather than extras, entry-point discovery with config activation,
a process boundary for Node, fixed non-configurable ingest limits, gates rather than discipline. The
real disagreement was one question: **does omniweave own compiled code?** I rule no, and the reason
is that the argument for owning it collapses once you notice the L2 model never crosses a language
boundary. Strip that premise away and the systems proposal's central artefact — a schema generator
emitting seven projections including pyo3 and napi binding shims, plus a maintained Python reference
implementation whose only job is to feed a parity suite — is 4-6 engineer-weeks of substrate buying
a property nothing needs, before a single format decoder is written. The ecosystem proposal's
vendored fork is cheaper but rests on a claim that does not survive `grep`: anydoc has no spatial
provenance, so its model cannot be "extended with polygons" without building layout, and the two
fields it wanted to add are runner-written store columns.

What survives is the pragmatist's shape with the ecosystem's boundary work grafted on and the systems
purist's enforcement discipline applied to all of it. From the pragmatist: Python host, stdlib-only
core, distributions with declared weight ceilings, the published `abi3` wheel instead of a build
matrix, a first milestone that is four weeks rather than nine months. From the ecosystem advocate:
the `omniweave-target/1` handshake (a `ready` frame carrying real encoder capability is worth far
more than a bare one-shot exec), the zero-import driver manifest, the append-only error-code register
with a fix line on every message, Apache-2.0 with generated attribution, no telemetry with a CI grep
to prove it, and the compat job that installs two prior releases' driver templates against HEAD. From
the systems purist: discovery that never calls `load()`, limits as a maximum a tenant may only clamp
below, the four-part vendored-artefact rule, version agreement as CI job 1, and `omniweave targets
install` with an explicit node-resolution order and refusal rather than substitution.

I also rejected one thing every proposal wanted in some form: a second implementation of anything.
There is one canonical-JSON digester, one place that opens SQLite, one subprocess seam, one decoder
per format family. Where an abstraction has a single implementation I kept only those the evidence
already names as a required seam — the `Store` protocol, because `mine-runtime.md` §7.10.2 makes it
*the* distribution boundary and it is four methods, not a framework — and declined the rest: no
kernel abstraction over the office decoder, no IL abstraction with one format, no worker-pool
abstraction, no `omniweave.operators` entry-point group until something needs it.

## Rejected

- **Owning compiled code — whether written from scratch (systems) or vendor-forked (ecosystem)** —
  the justifying premise, that three languages must agree on the L2 model byte-for-byte, is false
  here: L2 never reaches TypeScript and the only cross-language digest is plain `sha256` over bytes.
  Writing it is priced by its own author at 4-6 engineer-weeks for the substrate alone, excluding
  fourteen format decoders that already exist under MIT. Forking it rests on a claim that does not
  survive `grep`: `grep -rn "bbox\|polygon" _collections/anydoc/src/` returns one unrelated ODF
  match, so "extend its model with polygons and `CoordOrigin`" is layout engineering, not a
  vendored-crate patch — and `origin_operator` / `confidence` are runner-written store columns
  (`mine-runtime.md` §7.6.1), so they never belonged in a decoder. The fork stays a priced option
  with a written trigger.
- **The store inside a compiled kernel (systems and ecosystem)** — both keep Postgres as the T3
  backend, and a Rust crate that speaks Postgres has a network client, forfeiting the `cargo tree` /
  `wasm32` property used to justify the kernel's in-process seat. The alternative puts two
  implementations behind the claim protocol.
- **A language-neutral IDL: protobuf, Cap'n Proto, Arrow, or schemars-from-Rust** — a fourth
  toolchain and a second source of truth for a boundary that carries a ~30-field job envelope and a
  receipt. proto3's all-optional field model additionally cannot express "every block carries an
  origin and a confidence". Generated JSON Schema from Python plus a byte-diff gate is the whole
  requirement.
- **Polyrepo** — zero of 22 repos do it. anydoc needs a five-location version gate inside *one* repo;
  N repos over a shared contract multiplies that and makes an atomic change unreviewable.
- **One fat distribution with extras (docling / DataFlow)** — DataFlow's receipt: four incompatible
  vLLM pins, `[kbc]`+`[mineru]` unsatisfiable, `requires-python = ">=3.7, <4"` untested and false.
- **Vendored Node shipped as platform-tagged wheels on day one (`omniweave-nodert`)** — rejected on
  ordering, not principle: it multiplies the release matrix by six before a deck target exists and
  reintroduces the platform-tag-miss failure the proposal itself lists. `omniweave targets install`
  is the day-one channel; the wheel is a later delivery vehicle for the same bundle.
- **A long-lived local daemon or loopback socket for parse/embed/index** — LEANN's unauthenticated
  ZMQ on a dynamic loopback port (compute theft from any local process); open-slide's mandatory
  76-line CSRF guard. Attach-or-spawn HTTP is reserved for GPU model servers, where a cold model load
  justifies the surface.
- **pydantic in `omniweave-core`, and the pragmatist's bare driver names** — `pydantic_core` is a
  compiled extension on the per-turn import path, and "zero dependencies" is a gate that cannot erode
  while "few" is not; this overrules `mine-runtime.md` §7.2's `ConfigDict(extra="allow")` for driver
  config. Separately, the registry-key grammar is `<kind>.<family>.<impl>`, as `mine-runtime.md` §7.1
  already uses (`parse.pdf.marker`) — one name grammar, not two — and the seam is
  `omniweave_core.toolchain`, not `exttool`, so the lint rule reads correctly.

## Consequences

- **D2 is bound: the normative L2 definition is Python.** Invariants a Rust type system would enforce
  by construction (`CellSlot::Origin | Covered` with `GridBuilder` as sole constructor) must be
  enforced by a private constructor plus a property test plus a store constraint. This is weaker, and
  it is the same enforcement class every other invariant in this system uses.
- **D2 must also accept two producers into one model on day one**: anydoc's office `Document` (no
  spatial provenance) and pdfium's per-page path. Bounding boxes are optional in L2, and their
  absence must be representable rather than faked.
- **D3 inherits a fixed loading contract**: entry point → `omniweave-driver.toml` via
  `importlib.metadata` → contract check → allowlist check → probe → import. D3 owns the manifest's
  capability fields; it does not own the file's location, name, or the no-import rule.
- **D3 and D6 inherit `Mapping[str, Scalar]` driver config**, not pydantic models. Validation errors
  will be worse than pydantic's, and the coercion layer needs property tests against the
  `config_digest` contract.
- **D5 gets a Python SQLite store as the only shipped backend**, a four-method `Store` protocol as
  the T3 seam, and a hard requirement that the claim protocol work without `UPDATE … RETURNING`.
- **D8 gets the job directory and `omniweave-target/1` as the envelope** and owns everything inside
  `job.json`, `receipt.json` and the IL. It gets a `ready` frame carrying real external-binary
  capability, and it must refuse rather than substitute a codec.
- **D9's MCP server is a separate distribution** (`omniweave-serve`), so the CLI and hook paths never
  pay pydantic's import cost. The per-turn cold-start budget is a CI gate D9 must live inside.
- **PPTX and DOCX never require Node.** That is the point of putting the flagship OUT target in
  Python, and it is what makes `pip install omniweave[pptx]` a 60 MB one-liner.
- **`pip install omniweave` contains a compiled wheel** (`firecrawl-anydoc`). On a platform outside
  its seven targets the install fails at build time with a Rust error — a bad first impression that
  we buy in exchange for a default install that can read a DOCX. The README names the seven targets;
  the failure message names the `omniweave-core` + `omniweave-pdf` two-step.
- **Eleven distributions is real release coordination.** One `release.yml` run, gated on G5, and
  every first-party version moves together.
- **Two package managers and two lockfiles** (`uv.lock`, `toolchains/pnpm-lock.yaml`). A pnpm bump
  can break the video target with no Python-side signal; the full-digest pin is the only thing
  standing between that and a silent change.
- **Sixteen gates is a real tax on every PR** — roughly two minutes of CI and occasional
  false-positive triage on the import-graph scanner. Each one exists because a repo in
  `_collections/` shipped the defect it catches.

## Risks

- **`firecrawl-anydoc` is the single largest external dependency**: single-vendor, three months old,
  and it pulls `pdf-inspector = "1.14.2"`, Firecrawl's own unvendored crate with unaudited licence
  and limit discipline. Bounded by an exact pin, a vendored MIT source snapshot at a SHA, and a
  written fork trigger — but if it goes unmaintained we inherit a Rust toolchain and a seven-target
  release pipeline on someone else's schedule.
- **The eager Python marshal is a memory cliff.** `anydoc/python/src/document.rs` states "converted
  eagerly into Python objects", and `py.detach` covers the Rust decode but **not** the marshal, so
  the GIL is held for a duration proportional to document size, so thread-pool scaling is worse than
  the GIL-release story suggests and must be measured rather than assumed. A legal-discovery XLSX near the 4M
  grid-slot cap becomes millions of frozen `pyclass` instances in one un-abortable call, and
  `limits.rs` caps the Rust side while nothing caps the Python heap. This is the workload that fires
  the fork trigger, and until then it is a refusal (`ResourceLimitError.limit`) rather than a fix.
- **A distro CPython without FTS5, or with SQLite < 3.35.** Some enterprise LTS distributions ship
  SQLite below 3.35, which has no `UPDATE … RETURNING`. The fallback claim path and the
  `omniweave[sqlite]` remedy cover it, but on a platform with no `pysqlite3-binary` wheel and an old
  SQLite, omniweave does not run.
- **Hand-written config coercion silently mis-coerces** — `"false"` → `True` — and two hosts that
  believe they share a config get different `config_digest`s and a permanent 100% cache miss.
  Mitigated by `allow_nan=False`, un-canonicalisable values being a startup error, and
  `show-config --digest`; not eliminated.
- **A third-party distribution publishes the entry-point name `parse.office.anydoc`** and
  `register()` raises. That is the correct failure, and it still means one bad PyPI upload bricks an
  install until the user uninstalls it. There is no namespace reservation for entry points.
- **The import-graph scanner produces false positives** on `importlib.import_module(name)` and
  optional imports inside `try`, and the social failure mode is someone adding `--warn-only`.
  Mitigated by an `allowed-undeclared.toml` with a required justification and a review date per row,
  where a row past its date fails the gate. Past ~15 rows the gate has failed socially while passing
  mechanically.
- **`$OMNIWEAVE_HOME/toolchains/` is a user-writable directory holding executable code.** The digest
  is in the path and verified on every invocation, and `--offline` refuses to fetch — but a
  compromised home directory is compromised and no substrate choice fixes it.
- **Toolchain determinism is only as good as the resolved Node.** Allowing `node` on PATH means two
  renders of the same job can differ; the receipt records the resolved version and a mismatch is a
  `degradations[]` entry rather than a refusal. That softness will eventually produce an
  unreproducible render someone cares about.
- **Eleven distributions invite version skew in the wild**, and a user pairing `omniweave-core 0.4.x`
  with a driver built against `CONTRACT = 1` when core is at 2 gets a hard load error naming both.
  Correct, and still support load.
- **The weight gate is a lagging indicator**: a transitive dependency that quietly grows 40 MB fails
  an unrelated PR. The failure message must name the *new* transitive package, not just the total.

## Terminology

- Toolchain := a digest-pinned, non-Python execution bundle (Node + a compiled JS app) invoked as a one-shot child process through `omniweave_core.toolchain.run`; never imported, never a Python dependency.
- Job directory := the filesystem envelope of one Toolchain invocation — `job.json`, `il/`, `assets/`, `out/` — and the only channel by which bulk data crosses the Python/Toolchain boundary.
- `omniweave-target/1` := the NDJSON-on-stdio control protocol between omniweave and a Toolchain; stdout carries control frames only, under 1 MiB per invocation.
- Driver := an installable implementation of a capability (parse, ocr, vlm, embed, llm, structure, connect), discovered by entry point, activated by name in `omniweave.toml`, resolved at run time through `ctx.driver(kind)`.
- Target := an OUT compiler addressed by artefact kind (`pptx`, `docx`, `deck`, `video`), registered in the `omniweave.targets` entry-point group.
- Operator := a unit of scheduled work with a cache key and a row in the `work` table; the framework ships operators, a distribution ships drivers.
- Registry key := the dotted driver name `<kind>.<family>.<impl>`, e.g. `parse.office.anydoc`; it is what appears in `omniweave.toml [drivers] enabled` and in `OperatorIdentity.name`.
- Driver manifest := `omniweave-driver.toml`, shipped as package data, located through `importlib.metadata` and parsed with `tomllib`, declaring capability, probes, licence and egress without importing one line of the driver.
- Activation := naming a discovered driver in `omniweave.toml [drivers] enabled`; installation alone is discovery and is never consent.
- Capability probe := the smallest real operation that proves a capability works (not that a module imports); its verdict is cached for the run, and a red probe prunes the plan and reports.
- CONTRACT := the integer driver/target ABI in `omniweave_core.contract`; the only version a third party pins.
- RELEASE := the single semver carried by every first-party distribution and by the git tag.
- SCHEMA := the integer version of the L2 document model and the store schema.
- Core purity := the invariant that `omniweave-core` resolves to exactly one distribution, enforced by gate G1.
- Weight ceiling := the per-distribution installed-size limit in `tools/weights.toml`, measured from `RECORD` in a fresh environment, with an aggregate limit of 250 MB for `omniweave[recommended]`.
- Fork trigger := the written, testable condition in `vendor/<name>/FORK-TRIGGER.md` under which omniweave takes ownership of a vendored dependency.
- Three roots := `source_root`, `output_root`, `cache_root`, always separate; a `cache_root` inside `source_root` is a startup error.
- `$OMNIWEAVE_HOME` := the per-user state directory (default `~/.omniweave`) holding installed Toolchains and the probe verdict cache; distinct from the per-project `.omniweave/`.

## Open questions

- **Does the eager anydoc marshal actually dominate at realistic corpus scale?** Nothing in
  `_collections/` measures Python-side marshal cost. Settled by a benchmark on a 200-document mixed
  office corpus recording wall time, peak RSS and GIL-held fraction against the pure-Rust
  `to_markdown_bytes` path; if the marshal exceeds ~30% of wall time, the fork trigger fires and the
  fork's first change is a single-buffer return.
- **Does per-driver process isolation need to exist, and at what boundary?** The pathological-XLSX
  failure argues for an RSS-capped worker; adding a worker pool now would be an abstraction with one
  user. Settled by D4/D6 producing a second driver that needs isolation for a different reason (a
  CUDA OOM, a native crash) — one reason is a special case, two is a mechanism.
- **Is a `SCHEMA`-versioned msgpack encoding of L2 worth adding beside JSON?** It matters only if a
  Toolchain must read the full document model rather than an IL. Settled by D8 naming a target that
  genuinely needs L2 in-process; until then the IL is text and JSON is enough.
- **What is the real installed size of a vendored Node bundle per platform, and does it justify a
  platform-tagged wheel?** The ecosystem proposal's ~50 MB is unverified and Node's own binary is
  substantially larger uncompressed. Settled by building one bundle per platform with
  `tools/build-toolchain.sh` and measuring; a wheel becomes worthwhile only if the aggregate stays
  inside a 250 MB `omniweave[recommended, deck]`.
- **Does `omniweave-graph`'s dependency on `graphrag-chunking` earn its Python ceiling?** Its direct
  dependency set is two packages, but its transitive closure includes `pydantic-core` (compiled),
  `python-dotenv`, `pyyaml` and `toml`, and it caps CPython at `<3.14`. Settled by D7 measuring what
  `graphrag-chunking` supplies that ~400 lines of our own chunker would not.
- **Should `omniweave` (the CLI) depend on `omniweave-office` at all?** It buys a default install
  that reads a DOCX; it costs a compiled wheel in the default install and an opaque build failure on
  an unsupported platform. Settled by install telemetry we will not collect — so instead by counting
  platform-support issues in the first two releases, with the pre-committed remedy being to move
  office behind `omniweave[office]` and print the one-line remedy in the "no driver for .docx" error.
