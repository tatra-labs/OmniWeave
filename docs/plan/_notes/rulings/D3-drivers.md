# D3-drivers — The driver / plugin / extension system

## Decision

Every replaceable part of omniweave is a **Driver**: one implementation of exactly one **Port**,
shipped as its own distribution, declared by a **DriverCard** (`driver.toml`) that the host reads
**without importing a single line of the driver's code**. There are five Ports at v1 — `acquire`,
`parse`, `derive`, `embed`, `compile` — and two things that are deliberately *not* Ports: a
**Service** (a host-managed shared resource such as a vLLM engine, named and never routed) and a
**Backend** (the store, D5's). Discovery is a `omniweave.drivers` entry point whose value is a
**dotted package path** — never `module:attr`, never a filesystem path — plus
`OMNIWEAVE_DRIVER_PATH` for non-Python and dev drivers; the card is `driver.toml` inside that
package, resolved with `Distribution.locate_file()`. `resolve(requirement, catalog, policy)` is a
pure function returning **admitted candidates and every rejection with a typed code** — it never
picks a winner; ranking is D4's. A Driver never receives `RunContext`, the store, the cache, the
budget ledger, or a writable root — only `DriverIO` — so the runtime's ownership and
cache-poisoning invariants are enforced by the contract shape rather than by review. Isolation is
the host's decision: `subproc` (length-prefixed MessagePack over a 0600 unix socket / owner-only
named pipe) is the default and the only mode a third party gets; `inproc` is reachable only for a
first-party or vendored, free, GPU-less, network-less driver with a green fuzz suite that is
additionally named in project config. Licence **facts** live on the card, the **tier is computed by
core** (an author cannot mislabel), widening is a credential keyed to the licence text's sha256, and
restriction codes travel as `restriction_bits` on every produced item so the `compile` host can
refuse. `omniweave-conform` is a separate distribution whose thesis is that **the card is the test
plan**: it asserts every declared capability present *and every undeclared one absent*, and it — not
the author — writes `[cost]` and `[quality]` into the card under a recomputable attestation.

## Spec

**Ports.** Five, closed, core-owned, each with a major integer: `acquire/1` (locator → `UnitRef`s +
blobs), `parse/1` (bytes + `PartSelector` → DocModel fragment), `derive/1` (DocModel → items:
chunks, entities, edges, extracted fields), `embed/1` (texts → vectors), `compile/1` (IL + assets →
artifact bytes + report). A *connector* is an `acquire` driver; *chunkers* and *extractors* are both
`derive` drivers; *format detection* is not a Port — a `parse` driver declares `detects = true` and
exposes `sniff()`, and the detection chain is core code. `structure`, `engine` and `store` are
rejected as Ports (see Rejected). Adding a Port is a core release.

**Discovery.** `[project.entry-points."omniweave.drivers"] <driver_id> = "<dotted.package>"`. The
value is read as a string; `EntryPoint.load()` is banned inside `omniweave/core/drivers/` by a grep
CI rule and by an import-tracer test. A value containing `:` or `/` is rejected with
`CARD_ENTRYPOINT_NOT_A_PACKAGE`. This form is mandatory because setuptools validates every entry
point against `(?P<module>[\w.]+)\s*(:\s*(?P<attr>[\w.]+))?...$` — a path-shaped value **fails at
build time** (verified: `setuptools._entry_points.validate` on `"pkg/driver.toml"` raises;
`"pkg.sub"` passes). Three sources in precedence order — project `.omniweave/drivers/*/driver.toml`,
`OMNIWEAVE_DRIVER_PATH` entries, installed entry points — and a shadow is **reported, never silent**.
Measured on Windows/Python 3.11.9 with 328 installed distributions, warm: `entry_points(group=…)`
costs **15.3 ms**; a `scandir`+`stat` of all `.dist-info` dirs costs **1.01 ms** and is therefore the
catalog cache's validity key; a full `Distribution.files` (RECORD) scan of every distribution costs
**2124 ms** and is consequently forbidden as a discovery mechanism.

**The card.** `driver.toml`, one driver per file, `card_schema` integer at the top. Unknown
*top-level* tables are a hard error (a card is a contract, not config). Unknown keys inside
`[capability.<port>]` are ignored with a recorded `CARD_CAPABILITY_UNKNOWN` degradation, because an
unrecognised capability can only make a driver look *less* capable — the one safe asymmetry, and the
reason no `feature_level` axis is needed. Capability vocabulary is `mine-parse.md` §E11 with two
stated deviations: `math` becomes a **set** (`[]`/`["latex"]`/`["latex","mathml"]`) because latex vs
mathml is a notation choice, not a quality ladder; and `reading_order` is ordered
`raster < learned < model_emitted < char_stream < source`, justified by the 75%-vs-56% olmOCR-bench
order result for char-stream over a learned head and by native formats carrying a canonical order.
Capability is a **filter with per-field floors**, never a ranking key.

**Selection.** `resolve(req, catalog, policy) -> Resolution{candidates, rejected,
resolution_digest}`. Pure: no imports, no network, no clock. Filters in order: port major supported →
driver id not tombstoned → `card_schema` supported → format in `capability.formats` → every
requested capability floor met → licence tier allowed by policy *and* acknowledged → cost class
permitted → hardware satisfiable → probe verdict not `unavailable` → attested (unless explicitly
pinned) → present in the lockfile when `require_lock`. Every rejection is `(driver_id, RejectCode,
detail)`; a zero-candidate `Resolution` **is** the error message. Memoised on `(port, format,
frozenset(floors), policy_digest, catalog_digest)` — 4,000 parts otherwise means 4,000 calls.
`resolution_digest` goes in the run manifest so `omniweave drivers explain` replays offline.

**Isolation.** `subproc` default; one long-lived worker per `(driver_id, config_digest)`, framed
MessagePack over UDS/named pipe — **never a loopback TCP port** (LEANN's ZMQ REQ/REP on a dynamic
loopback port with no auth is the anti-pattern). stdout/stderr are captured and never parsed, which
is why the protocol does not ride stdio. Payloads over 256 KiB travel as blob references. One
`INVOKE` carries up to `batch_max_units`; one `RESULT` per unit, so **the batch is invisible to the
`work` table**. Two deadlines: `progress_ms` and `wall_ms_hard`. A crashed batch retries once at
`batch = 1` to localise the poison unit; the death is `FAILED_PERMANENT{DRIVER_CRASHED}` on one unit
with the child's last 4 KiB of stderr attached, and **3 crashes in 60 s quarantines the driver** (not
the unit) for the run, re-routing the plan and recording a degradation. The driver receives
`source_ro`, a per-invocation `tmp`, and blob *references* — never `output_root` or `cache_root`; the
host writes all artifacts. Where the OS cannot enforce `needs_network = false`, the achieved level is
recorded rather than claimed. `inproc` requires `trust ∈ {first_party, vendored}` ∧
`cost.class == "free"` ∧ `gpu == "none"` ∧ `needs_network == false` ∧ a green `fuzz` suite ∧ the id
listed under `[drivers.inproc]`. `wasm` is in the vocabulary and not built at v1; `container` is not
in the vocabulary at all.

**Versioning.** Three axes and no fourth. `port` major = the ABI (core supports N and N−1 for ≥180
days or two minors, whichever is longer; the window is `ports.json`, not a docstring).
`driver_version` = semver, for humans and the lockfile. `schema_version` = int, bumped when output
shape or semantics change, and **it alone enters the cache key** so a bug-fix release does not re-bill
a `billed_api` cache. Deprecation is data (`deprecated_in`, `removed_in`, `replacement`), surfaced
once per run in `degradations[]` — never `warnings.warn`, which graphify proved is filterable and
invisible under JSON logging. A removed driver resolves to a **Tombstone** card the framework ships,
quoting the clause, naming the replacement.

**Licence.** Two fact blocks, `[licence.code]` and `[licence.weights]` (absent ⇒ no weights), because
marker/surya/lift ship Apache-2.0 code with an OpenRAIL-M `MODEL_LICENSE` whose clause 8 licenses the
**Output**. Facts include `licence_sha256`, `output_share_alike`, `competitor_bar`,
`territory_excluded`, `field_of_use_excluded`, `revenue_gate_usd`, `mau_gate`, `redistribution`,
`remote_kill_switch`, `no_model_training`, `attribution_per_output`. `tier ∈ {open, restricted,
commercial, forbidden}` is **computed** by core; `omniweave driver check` fails on a mismatch.
Default policy is `allow_tiers = ["open"]`; widening is a per-driver entry in `omniweave.acks.toml`
carrying `licence_sha256`, `by`, `at`, `ref` — **void when the hash changes** (jcodemunch relicensed
mid-2026; graphify relicensed MIT → Apache-2.0). Restriction codes ride every produced item as
`restriction_bits` set by the runner from the card, never by the driver; the `compile` host refuses to
emit an artifact containing restricted items unless policy allows, naming the offending item ids. The
transitive gate resolves the dependency graph **and** scans the import graph against the declared set
and **fails**, never warns; `cairosvg` — LGPL-3.0, imported by ppt-master, declared in no
requirements file — is the regression fixture.

**Conformance.** `omniweave-conform`, a separate distribution. Eleven suites: `card`, `purity`
(discovery under an import tracer — fails if any module of the driver's distribution was imported),
`contract`, `capability` (**derived from the card in both directions**: `charspan = false` asserts
charspans are *absent*), `idempotence`, `determinism`, `limits`, `sandbox`, `cost`, `licence`, `fuzz`
(crash allowed, hang not). The bar is **the honesty of the descriptor, not the excellence of the
driver**: declaring `spatial = "none"` is not a failure; declaring `line_bbox` and returning none is.
The mandatory tier must run in under five minutes on a laptop, enforced as a CI timing assertion,
because a skipped gate is not a gate. `[cost]` and `[quality]` are kit-written; the loader recomputes
`attestation` and an unattested driver is never auto-selected. CI runs the kit from a trusted tag,
never the PR branch.

**Distribution.** No hosted registry and no signing at v1. One distribution per driver,
`omniweave-driver-<id>`; core declares **no driver extras**, so DataFlow's four mutually incompatible
vLLM pins are impossible by construction. A driver depends on **`omniweave-ports`** — a ~40 KB
pure-typing distribution versioned by port major — and never on `omniweave-core`, so a driver cannot
pin the framework. `omniweave-index` is a static, CI-byte-diff-gated `index.json` of card stubs
readable before install; `omniweave drivers add` prints tier, restriction codes and install size,
demands confirmation for any tier ≠ `open`, verifies the installed card digest, and writes
`omniweave.lock`. The weekly rot sweep is non-blocking, exits 0, and re-checks licence hashes.

## Concrete shape

```toml
# ── omniweave-driver-anydoc/src/omniweave_driver_anydoc/driver.toml ───────────
# THE DRIVERCARD. Read without importing. Unknown TOP-LEVEL tables are an error.
card_schema = 1

[driver]
id             = "parse.doc.anydoc"     # ^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$
port           = "parse/1"              # <name>/<MAJOR>
version        = "0.2.4"                # semver — humans + lockfile
schema_version = 3                      # output shape/semantics — ENTERS THE CACHE KEY
title          = "anydoc"
summary        = "Rust office/PDF decoder. No HTTP client. 12 cargo-fuzz targets."   # <=200 ch
homepage       = "https://github.com/firecrawl/anydoc"
entrypoint     = "omniweave_driver_anydoc.driver:AnydocParser"  # imported ONLY by activate()
granularity    = "document"             # document | part | corpus — exactly one
deterministic  = true
detects        = true                   # parse drivers only: exposes sniff()

[capability]
formats     = ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "application/vnd.oasis.opendocument.text", "application/rtf",
               "application/epub+zip", "text/csv", "application/pdf"]
consumes    = ["raw_bytes"]             # closed, core-owned artifact kinds
produces    = ["doc_fragment"]

[capability.parse]                      # mine-parse.md E11; ORDERED floors unless noted
spatial       = "none"                  # none < page_bbox < block_bbox < line_bbox < char_bbox
charspan      = false                   # bool
reading_order = "source"                # raster < learned < model_emitted < char_stream < source
sections      = "typed_levels"          # none < markdown_only < outline_from_source < typed_levels
tables        = "cells_with_spans"      # none < flat_html < cells < cells_with_spans
math          = []                      # SET, not a ladder: [] | ["latex"] | ["latex","mathml"]
assets        = "bytes"                 # none < refs < bytes
notes         = "linked"                # none < inline < linked
confidence    = "none"                  # none < document < page < element
furniture     = "flagged"               # destroyed < flagged < separated
round_trip    = "structure"             # none < text < structure

[hardware]
gpu            = "none"                 # none | optional | required
vram_gb_min    = 0
ram_gb_min     = 0.25
cpu_arch       = ["x86_64", "aarch64"]
os             = ["linux", "darwin", "windows"]
needs_network  = false                  # ⇒ RUN WITH NO EGRESS; kit enforces
needs_binaries = []                     # e.g. ["ffmpeg", "soffice"]
imports_torch  = false
install_bytes  = 2_400_000
services       = []                     # Service names requested via io.service(...)

[isolation]
requires        = "subproc"             # inproc | subproc | wasm ; the HOST may only TIGHTEN
memory_mb       = 512
progress_ms     = 15_000                # no-PROGRESS deadline
wall_ms_hard    = 120_000
batch_max_units = 32

[limits]                                # effective = min(tenant_cap, declared, HOST_MAX)
max_input_bytes = 134_217_728           # anydoc MAX_ENTRY_BYTES
max_parts       = 100_000               # anydoc MAX_ENTRY_COUNT

[licence.code]                          # FACTS ONLY. `tier` is computed by core.
spdx                  = "MIT"
licence_sha256        = "sha256:3b8a…"  # an ack is VOID when this changes
licence_url           = "https://…/LICENSE"
notice_path           = "NOTICE"
redistribution        = "allowed"       # allowed | internal_only | forbidden
output_share_alike    = false
competitor_bar        = false
revenue_gate_usd      = 0
mau_gate              = 0
territory_excluded    = []              # ISO-3166-2
field_of_use_excluded = []
attribution_per_output = false
no_model_training     = false
remote_kill_switch    = false
clause_refs           = []
# [licence.weights]  — OMIT ENTIRELY when the driver ships no weights.
#   weights_revision = "a1b2c3…"        # "main" is a card error
#   weights_sha256   = { "model.safetensors" = "9f8e…" }

[deps]
pins = ["cfb=0.14.0","quick-xml=0.41.0","zip=8.6.0","pdf-inspector=1.14.2"]
# digest enters the cache key ONLY for cost.class = "free" (mine-runtime open question #4)

[config]                                # JSON Schema 2020-12, as TOML tables — no import needed
type = "object"
additionalProperties = false
[config.properties.emit_notes]
type = "boolean"
default = true

# ══ EVERYTHING BELOW IS WRITTEN BY `omniweave conform`. Author values are rejected. ══
[cost]
class            = "free"               # free | local_compute | billed_api
unit             = "document"
p50_ms_per_unit  = 5                    # anydoc README: 4.4 ms median across 14 formats
p95_ms_per_unit  = 41
usd_per_unit     = 0.0
tokens_per_unit  = 0
max_retries      = 0                    # a driver MAY NOT retry internally; retry is the runtime's
measured_on      = "x86_64-linux 8c/16GiB · min-of-5 warm · in-process"
measured_on_spawn = "x86_64-linux 8c/16GiB · min-of-5 warm · spawn-inclusive"

[quality]
kit_version = "1.0.0"
kit_run     = "2026-08-14T09:22:31Z"
suites      = { card="pass", purity="pass", contract="pass", capability="pass",
                idempotence="pass", determinism="pass", limits="pass", sandbox="pass",
                cost="pass", licence="pass", fuzz="pass" }
[[quality.benchmark]]
suite = "omniweave-golden"; version = "2026.09"; slice = "office"
metric = "structure_f1"; value = 0.94
measured_on = { weights="n/a", runtime="anydoc", runtime_version="0.2.4",
                sampling="n/a", prompt_version="n/a" }   # REQUIRED on every benchmark row

attestation = "sha256:9f2c…"            # over the canonical card MINUS this key
```

```toml
# ── Tombstone card shipped by omniweave (framework-owned) ────────────────────
card_schema = 1
[driver]
id = "parse.ocr.surya"; port = "parse/1"; version = "*"; title = "surya (weights)"
[licence.code]    spdx = "Apache-2.0"
[licence.weights] spdx = "LicenseRef-AIPubs-OpenRAIL-M"
                  output_share_alike = true
                  competitor_bar = true
                  attribution_per_output = true
                  remote_kill_switch = true
                  clause_refs = ["Attachment A 2(c)", "8", "9"]
[tombstone]
tier   = "forbidden"
reason = """MODEL_LICENSE (md5 e1f69b64dee2f1641a9b1ab12adf24d6) Attachment A clause 2(c) bars use
by any party offering a competing product — no revenue threshold, no research carve-out (2(a)/(b)
have one; 2(c) does not). Clause 8 licenses the OUTPUT. The Apache-2.0 CODE may be run against
other weights."""
replaced_by = "parse.ocr.olmocr"
review_by   = "2027-03-01"              # CI fails a tombstone past its review date
```

```python
# ══ omniweave-ports (distribution) → import omniweave.ports ═══════════════════
# ~40 KB, pure typing: dataclasses, Protocols, StrEnums. NO pydantic, NO torch.
# A driver's ONLY permitted omniweave imports are `omniweave.ports` and `omniweave.testkit`.
# A driver NEVER depends on omniweave-core.

Scalar = str | int | float | bool | None

class Port(StrEnum):
    ACQUIRE="acquire"; PARSE="parse"; DERIVE="derive"; EMBED="embed"; COMPILE="compile"

class CostClass(StrEnum):   FREE="free"; LOCAL_COMPUTE="local_compute"; BILLED_API="billed_api"
class Isolation(StrEnum):   INPROC="inproc"; SUBPROC="subproc"; WASM="wasm"
class TrustTier(StrEnum):
    FIRST_PARTY="first_party"; VENDORED="vendored"; PINNED="pinned"
    LOCAL="local"; UNPINNED="unpinned"
class LicenceTier(StrEnum):
    OPEN="open"; RESTRICTED="restricted"; COMMERCIAL="commercial"; FORBIDDEN="forbidden"

class Restriction(IntEnum):                 # 32 codes RESERVED; bit = 1 << value
    OUTPUT_SHARE_ALIKE=0; COMPETITOR_BAR=1; TERRITORY_EXCLUDED=2; FIELD_OF_USE_BARRED=3
    REVENUE_GATE=4; MAU_GATE=5; NO_REDISTRIBUTION=6; NO_MODEL_TRAINING=7
    ATTRIBUTION_PER_OUTPUT=8; REMOTE_KILL_SWITCH=9; COPYLEFT_NETWORK=10; COPYLEFT_STRONG=11
    # 12..31 reserved. A 33rd code is a migration, and that is written down.

class FailureClass(StrEnum):
    ENCRYPTED="encrypted"; NEEDS_OCR="needs_ocr"; UNSUPPORTED_FORMAT="unsupported_format"
    CORRUPT_INPUT="corrupt_input"; RESOURCE_LIMIT="resource_limit"; TOO_LARGE="too_large"
    TIMEOUT="timeout"; UPSTREAM_UNAVAILABLE="upstream_unavailable"; RATE_LIMITED="rate_limited"
    AUTH="auth"; EMPTY_RESULT="empty_result"; DRIVER_CRASHED="driver_crashed"
    DRIVER_BUG="driver_bug"

@dataclass(frozen=True, slots=True)
class DriverError(Exception):
    cls: FailureClass
    message: str
    retry_after_ms: int | None = None      # REQUIRED iff transient — __post_init__ raises
    pages: tuple[int, ...] = ()            # NEEDS_OCR names the pages (anydoc: error as routing data)
    limit: str | None = None               # RESOURCE_LIMIT names WHICH knob would need raising

class ProbeStatus(StrEnum): OK="ok"; DEGRADED="degraded"; UNAVAILABLE="unavailable"

@dataclass(frozen=True, slots=True)
class ProbeVerdict:
    status: ProbeStatus
    detail: str                            # must name the missing thing
    missing: tuple[str, ...] = ()          # ("tesseract-lang:deu",) — machine-actionable
    fix_hint: str | None = None            # "apt install tesseract-ocr-deu"
    capabilities_lost: tuple[str, ...] = ()  # what DEGRADED costs, so the router can re-filter

@dataclass(frozen=True, slots=True)
class DriverIO:
    """The ONLY channel a driver has to the outside. No Store, no Cache, no work table,
    no BudgetLedger, no RunContext, no writable output_root or cache_root. Not extensible."""
    blobs: "BlobStore"                     # .path(digest) read-only · .put(bytes) -> digest
    tmpdir: str                            # per-invocation, owned by the driver, host-deleted
    deadline_ms: int
    max_output_bytes: int                  # exceeding it is TOO_LARGE, never a silent truncation
    def service(self, name: str) -> "ServiceHandle": ...   # attach-or-spawn, host-managed
    def cancelled(self) -> bool: ...       # check at every loop top
    def log(self, event: str, **fields: Scalar) -> None: ...
    def progress(self, done: int, total: int | None) -> None: ...   # resets progress_ms

@dataclass(frozen=True, slots=True)
class DriverResult:
    """What a driver returns. STRICTLY SMALLER than the runtime's StepResult: a driver
    cannot claim SKIPPED_CACHED, DEFERRED_BUDGET, an identity, or a cache hit."""
    outcome: Literal["ok", "ok_partial"]
    produced: tuple["ArtifactRef", ...]
    partial_reason: str | None = None
    metrics: "DriverMetrics" = ...         # ran_ms, input/output_tokens, cost_micros,
                                           # bytes_read, peak_rss_bytes
    # confidence, origin_driver, restriction_bits, was_cache_hit are set BY THE RUNNER.

class ParseV1(Protocol):
    PORT: ClassVar[str] = "parse/1"
    @classmethod
    def probe(cls, env: "ProbeEnv") -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
        # STATIC CONFIG ONLY. Constructing a driver MUST load no model and open no file:
        # a 100%-cache-hit run constructs and loads nothing (mine-runtime §7.1.1 row 2).
    def sniff(self, head: bytes, hint: "StreamHint") -> tuple["FormatGuess", ...]: ...
        # MUST NOT advance a stream it is given. The HOST asserts this, not the driver.
    def parse(self, unit: "UnitRef", parts: "PartSelector", io: DriverIO) -> DriverResult: ...
        # Raise DriverError for every failure. NEVER return None. NEVER return an empty success:
        # the host converts an `ok` failing is_valid_nonempty into FAILED_PERMANENT(EMPTY_RESULT)
        # BEFORE anything is cached.
    def is_valid_nonempty(self, ref: "ArtifactRef") -> bool: ...
```

```python
# ══ omniweave/core/drivers/ — core-side, never imported by a driver ═══════════
@dataclass(frozen=True, slots=True)
class DriverId:
    id: str; dist: str
    def __str__(self) -> str: return f"{self.id}@{self.dist}"

@dataclass(frozen=True, slots=True)
class DriverCard:
    """Parsed, validated, IMMUTABLE. Constructed WITHOUT importing `entrypoint`."""
    id: DriverId
    card_schema: int
    port: str                       # "parse/1"
    version: str
    schema_version: int
    entrypoint: str                 # dotted path; imported ONLY by activate()
    granularity: Literal["document","part","corpus"]
    deterministic: bool
    formats: frozenset[str]
    consumes: frozenset[str]; produces: frozenset[str]
    capability: Mapping[str, Mapping[str, Scalar | frozenset[str]]]   # port-scoped
    hardware: HardwareDecl; isolation: IsolationDecl; limits: LimitsDecl
    cost: CostDecl; benchmarks: tuple[Benchmark, ...]
    licence_code: LicenceFacts; licence_weights: LicenceFacts | None
    config_schema: Mapping[str, Any]
    deprecation: Deprecation | None
    tombstone: Tombstone | None
    # computed by the loader, NEVER self-reported:
    tier: LicenceTier               # = compute_tier(licence_code, licence_weights)
    restriction_bits: int
    trust: TrustTier
    origin: Literal["entry_point","driver_path","project","tombstone"]
    card_sha256: str
    attested: bool                  # recomputed digest == quality.attestation

def compute_tier(code: LicenceFacts, weights: LicenceFacts | None) -> LicenceTier: ...
    # PURE, ~25 lines, unit-tested against all 22 repos' licences.
    # forbidden  ⇐ id in the shipped tombstone set
    # commercial ⇐ requires_credential
    # restricted ⇐ competitor_bar | output_share_alike | territory_excluded
    #              | field_of_use_excluded | revenue_gate_usd | mau_gate
    #              | remote_kill_switch | redistribution != allowed
    #              | spdx in COPYLEFT_NETWORK ∪ COPYLEFT_STRONG   (AGPL-3.0, SSPL, GPL-3.0, …)
    # open       ⇐ otherwise
    # `omniweave driver check` FAILS if a card's stored tier != this. An author cannot mislabel.

@dataclass(frozen=True, slots=True)
class Requirement:
    port: str
    format: str | None = None
    input_kind: str | None = None
    requires_produces: frozenset[str] = frozenset()
    floors: Mapping[str, Scalar | frozenset[str]] = MappingProxyType({})
                                     # {"tables": "cells", "charspan": True, "math": {"latex"}}
    max_cost_class: CostClass = CostClass.LOCAL_COMPUTE
    granularity: Literal["document","part"] | None = None
    pinned: DriverId | None = None

class RejectCode(StrEnum):
    CARD_INVALID="card_invalid"
    CARD_ENTRYPOINT_NOT_A_PACKAGE="card_entrypoint_not_a_package"
    CARD_SCHEMA_TOO_NEW="card_schema_too_new"
    PORT_UNSUPPORTED="port_unsupported"
    PORT_MISMATCH="port_mismatch"
    ID_COLLISION_UNQUALIFIED="id_collision_unqualified"
    TOMBSTONED="tombstoned"
    FORMAT_UNSUPPORTED="format_unsupported"
    PRODUCES_INSUFFICIENT="produces_insufficient"
    CAPABILITY_BELOW_FLOOR="capability_below_floor"
    GRANULARITY_MISMATCH="granularity_mismatch"
    LICENCE_TIER_NOT_ALLOWED="licence_tier_not_allowed"
    LICENCE_ACK_MISSING="licence_ack_missing"
    LICENCE_ACK_STALE="licence_ack_stale"          # licence_sha256 changed
    COST_CLASS_NOT_PERMITTED="cost_class_not_permitted"
    HARDWARE_ABSENT="hardware_absent"
    BINARY_ABSENT="binary_absent"
    ISOLATION_NOT_PERMITTED="isolation_not_permitted"
    TRUST_INSUFFICIENT="trust_insufficient"
    NOT_IN_LOCKFILE="not_in_lockfile"
    UNATTESTED="unattested"
    DEPRECATED_REMOVED="deprecated_removed"
    PROBE_UNAVAILABLE="probe_unavailable"
    QUARANTINED="quarantined"                      # circuit breaker tripped this run

@dataclass(frozen=True, slots=True)
class Candidate:
    card: DriverCard
    effective_config: Mapping[str, Scalar]
    config_digest: str
    effective_isolation: Isolation
    effective_limits: LimitsDecl        # min(tenant_cap, declared, HOST_MAX)

@dataclass(frozen=True, slots=True)
class Rejection:
    driver: DriverId; code: RejectCode; detail: str

@dataclass(frozen=True, slots=True)
class Resolution:
    requirement: Requirement
    candidates: tuple[Candidate, ...]      # UNORDERED. D4's router ranks. D3 never picks.
    rejected: tuple[Rejection, ...]        # REQUIRED output; zero candidates is a value, not a raise
    catalog_digest: str; policy_digest: str; resolution_digest: str

def resolve(req: Requirement, catalog: Catalog, policy: Policy) -> Resolution: ...
    # PURE. No imports, no network, no clock. Memoised on
    # (port, format, frozenset(floors.items()), max_cost_class, policy_digest, catalog_digest).

def activate(c: Candidate, host: DriverHost) -> DriverHandle: ...
    # The ONLY site that imports `card.entrypoint`. Asserts the loaded class's PORT and
    # SCHEMA_VERSION equal the card's → CARD_CODE_MISMATCH, before any work.
```

```
══ Wire protocol, port contract 1 ═══════════════════════════════════════════════
Frame     ::= u32 length_le | u8 kind | MessagePack payload
Transport ::= AF_UNIX SOCK_STREAM @ 0600  |  Windows named pipe, owner-only DACL
              NEVER a loopback TCP port (LEANN api.py:133 `zmq.REQ` → tcp://localhost:{port},
              no auth, no CURVE, is the anti-pattern).
              stdout/stderr are CAPTURED, logged at debug, and NEVER parsed — which is why the
              protocol does not ride stdio (an MCP server's stderr banner renders at error level).
INLINE_MAX = 262144 bytes; anything larger travels as a content-addressed blob reference.

kind name       dir       payload
──── ────────── ───────── ───────────────────────────────────────────────────────────────
 1   HELLO      host→drv  {port, card_schema, card_sha256, driver_id, effective_config,
                           roots:{source_ro, tmp}, blob_base, isolation_granted:{...}}
 2   HELLO_ACK  drv→host  {driver_id, version, schema_version, port, code_fingerprint}
                           ── any mismatch vs the card ⇒ CARD_CODE_MISMATCH, before work
 3   PROBE      host→drv  {}                        4  PROBE_ACK drv→host  ProbeVerdict
 5   INVOKE     host→drv  {invoke_id, units:[{uri, part, content_digest,
                           inline?: bin, blob_ref?: sha256}], deadline_ms, budget_micros}
 6   RESULT     drv→host  {invoke_id, unit_index, DriverResult…}
                           ── ONE frame per unit; the batch is invisible to the `work` table
 7   LOG        drv→host  {level, event, fields}    (structured only)
 8   PROGRESS   drv→host  {invoke_id, unit_index, done, total}   ── resets progress_ms
 9   CANCEL     host→drv  {invoke_id, generation}
10   SHUTDOWN   host→drv  {grace_ms}
11   FATAL      drv→host  {failure_class, detail}   ── the driver's last words
```

```sql
-- ══ Store DDL D3 requires of D5 ═════════════════════════════════════════════
-- Restrictions travel on every produced item. Set by the RUNNER from the card, never the driver.
ALTER TABLE block ADD COLUMN origin_driver    TEXT    NOT NULL;   -- "parse.doc.anydoc"
ALTER TABLE block ADD COLUMN driver_schema_v  INTEGER NOT NULL;
ALTER TABLE block ADD COLUMN restriction_bits INTEGER NOT NULL DEFAULT 0;   -- 32 codes reserved
CREATE INDEX block_restricted ON block(restriction_bits) WHERE restriction_bits <> 0;
--   "may I ship this deck" == SELECT 1 FROM block WHERE restriction_bits & 1 AND doc_id = ?

-- Catalog cache. Validity key measured at 1.01 ms for 328 dists (scandir+stat of *.dist-info);
-- a full RECORD scan of the same env costs 2124 ms and is therefore forbidden.
CREATE TABLE driver_card_cache (
  prefix     TEXT NOT NULL, dist_name TEXT NOT NULL, dist_version TEXT NOT NULL,
  card_path  TEXT NOT NULL, mtime_ns  INTEGER NOT NULL, size INTEGER NOT NULL,
  card_json  TEXT NOT NULL, card_sha256 TEXT NOT NULL,
  PRIMARY KEY (prefix, dist_name, dist_version, card_path)
) WITHOUT ROWID;

-- The operability artefact: which drivers ran, what they cost, how often they died.
CREATE TABLE driver_observation (
  run_id TEXT NOT NULL, driver TEXT NOT NULL, driver_version TEXT NOT NULL,
  port TEXT NOT NULL, card_sha256 TEXT NOT NULL,
  isolation TEXT NOT NULL CHECK (isolation IN ('inproc','subproc','wasm')),
  licence_tier TEXT NOT NULL CHECK (licence_tier IN ('open','restricted','commercial','forbidden')),
  outcome TEXT NOT NULL, failure_class TEXT,
  units INTEGER NOT NULL DEFAULT 0, wall_ms_total INTEGER NOT NULL DEFAULT 0,
  cost_micros_total INTEGER NOT NULL DEFAULT 0, peak_rss_bytes INTEGER NOT NULL DEFAULT 0,
  crashes INTEGER NOT NULL DEFAULT 0, quarantined INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, driver, driver_version, outcome, IFNULL(failure_class,''))
) STRICT;

-- One row per resolution, NOT per unit: a 4,000-page PDF must not write 4,000 report rows.
CREATE TABLE resolution_report (
  run_id TEXT NOT NULL, resolution_digest TEXT NOT NULL, port TEXT NOT NULL,
  requirement_json TEXT NOT NULL, report_json TEXT NOT NULL,   -- candidates + every rejection
  first_seen_ms INTEGER NOT NULL, hits INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (run_id, resolution_digest)
) STRICT;
```

```toml
# ── omniweave.toml (PROJECT config — distinct from a driver's driver.toml) ────
[drivers]
require_lock        = true              # unpinned third party ⇒ NOT_IN_LOCKFILE
allow_unattested    = false
isolation_floor     = "subproc"
inproc              = ["parse.doc.anydoc", "parse.pdf.native"]   # a reviewable act, not a card claim
probe_timeout_ms    = 2000
max_workers         = { free = 4, local_compute = 4, billed_api = 8 }
worker_idle_ttl_s   = 300
crash_quarantine    = { crashes = 3, window_s = 60 }

[drivers.cost]
allow_classes       = ["free", "local_compute"]     # billed_api is opt-in
auto_refresh_classes = ["free"]                     # a watcher may NEVER auto-run billed work

[drivers.resolve]                       # only needed when two dists claim one driver id
"parse.pdf.pdfium" = "omniweave-driver-pdfium"

[licence]
allow_tiers   = ["open"]
jurisdiction  = "DE"                    # checked against territory_excluded
fields_of_use = ["enterprise_documents"]

[drivers."parse.ocr.olmocr"]
enabled = true
config  = { max_page_retries = 2, max_tokens = 8000 }
budget  = { cost_micros_per_document = 20000 }      # retries SERIAL, charged to the same budget
```

```toml
# ── omniweave.acks.toml — reviewable, diffable; NOT a boolean in the main config ──
[[ack]]
driver         = "parse.ocr.hunyuan"
licence_sha256 = "sha256:9f2c…"         # ack VOID if the licence text changes → LICENCE_ACK_STALE
tier           = "restricted"
acknowledged   = ["territory:EU,GB,KR", "field_of_use:credit,employment,housing,insurance",
                  "output_share_alike", "no_model_training"]
by             = "legal@example.com"
at             = "2026-09-01T11:00:00Z"
ref            = "https://tracker/LEGAL-412"
```

```
══ Directory layout ═════════════════════════════════════════════════════════════
omniweave-ports/                       # ~40 KB pure typing; versioned by PORT MAJOR
  omniweave/ports/__init__.py  _base.py  acquire_v1.py  parse_v1.py
                               derive_v1.py  embed_v1.py  compile_v1.py  ports.json

omniweave-core/
  omniweave/core/drivers/
    card.py        DriverCard · load_card · CARD_SCHEMA (unknown top-level table = error)
    discover.py    entry-point scan (EntryPoint.value ONLY) · OMNIWEAVE_DRIVER_PATH · cache
    resolve.py     Requirement · Rejection · Resolution · resolve()          [PURE]
    registry.py    Registry[T] — a per-run INSTANCE; raises DuplicateDriver
    policy.py      Policy · policy_digest · omniweave show-config
    licence.py     LicenceFacts · Restriction · compute_tier · acks
    probe.py       ProbeVerdict cache, keyed (driver, version, host_fingerprint), 24 h TTL
    host/          inproc.py (DriverGuard)  subproc.py (supervisor + pool)  wasm.py [not v1]
    tombstones/    surya.toml marker.toml lift.toml hunyuan.toml omniparse.toml jcodemunch.toml
  omniweave/services/   attach-or-spawn (surya SuryaInferenceManager shape), health, model-id verify

omniweave-conform/                     # separate distribution: pytest + jsonschema + msgpack
  suites/{card,purity,contract,capability,idempotence,determinism,limits,sandbox,cost,licence,fuzz}/
  corpus/{formats/,adversarial/,LICENCES.md}     # a fixture corpus is redistributed content

omniweave-driver-anydoc/               # ONE DISTRIBUTION PER DRIVER
  pyproject.toml    [project.entry-points."omniweave.drivers"]
                    "parse.doc.anydoc" = "omniweave_driver_anydoc"   # DOTTED PACKAGE, no ':', no '/'
                    dependencies = ["omniweave-ports>=1,<2"]         # NEVER omniweave-core
  LICENSE  NOTICE
  src/omniweave_driver_anydoc/{driver.toml, driver.py, _probe.py}
  conformance/conformance-report.json
```

```
══ omniweave drivers explain — the payoff, and the highest-value error message ══
$ omniweave drivers explain application/pdf --need tables=cells --need charspan=true

port parse/1 · policy sha256:4b1e… · catalog sha256:c0de… · resolution sha256:77a2…

CANDIDATES (unordered — D4's router ranks these)
  parse.pdf.native@omniweave-driver-pdfnative  v0.3.1  free           p50 210 ms  inproc
  parse.ocr.olmocr@omniweave-driver-olmocr     v0.5.0  local_compute  p50 2.4 s   subproc

REJECTED
  parse.ocr.surya       TOMBSTONED               MODEL_LICENSE 2(c) competitor bar; clause 8
                                                 licenses the Output → use parse.ocr.olmocr
  parse.pdf.marker      TOMBSTONED               same MODEL_LICENSE (md5 e1f69b64…)
  parse.ocr.hunyuan     LICENCE_ACK_MISSING      tier=restricted · territory excludes EU/GB/KR
                                                 → omniweave driver ack parse.ocr.hunyuan
  parse.any.markitdown  CAPABILITY_BELOW_FLOOR   tables=flat_html < cells; charspan=false
  parse.vlm.internal    UNATTESTED               no conformance attestation → omniweave conform
  parse.ocr.tesseract   PROBE_UNAVAILABLE        language pack 'deu' missing
                                                 → apt install tesseract-ocr-deu
  parse.doc.anydoc      FORMAT_UNSUPPORTED       application/pdf not in capability.formats
```

**Invariants, and how each is enforced**

| # | Invariant | Enforced by |
|---|---|---|
| D3-1 | No driver code is imported before resolve admits it, policy enables it, its tier is allowed and acknowledged, and its probe is requested. | `EntryPoint.load()` banned in `core/drivers/` (grep CI rule); conform suite `purity` runs discovery under an import tracer; a core test discovers 30 cards in a venv and asserts `sys.modules` gains no `omniweave_driver_*` key |
| D3-2 | An entry-point value is a dotted package path. | Loader rejects any value containing `:` or `/` → `CARD_ENTRYPOINT_NOT_A_PACKAGE`; the packaging test builds a wheel and asserts setuptools accepts it |
| D3-3 | A duplicate driver id never wins silently. | `Registry.register` raises `DuplicateDriver`; resolve emits `ID_COLLISION_UNQUALIFIED`; only `[drivers.resolve]` proceeds. Closes DataFlow first-wins and graphrag silent-overwrite together |
| D3-4 | `resolve()` is pure, deterministic and replayable. | No `ctx`, no clock, no network in the signature; a property test shuffles the catalog 100× and asserts an identical `Resolution`; `resolution_digest` in the run manifest |
| D3-5 | Every rejected candidate carries a typed code. | `Rejection` required to construct a `Resolution`; test asserts `len(candidates) + len(rejected) == len(considered)` |
| D3-6 | `resolve()` never ranks and never chooses. | `Resolution.candidates` is a `tuple` documented unordered and sorted lexically on `driver_id` before return, so no caller can depend on an emergent order |
| D3-7 | A driver never receives a writable `output_root` or `cache_root`, the store, the cache, or the budget ledger. | `DriverIO` has no such field; `HELLO` carries only `{source_ro, tmp, blob_base}`; a sandbox test asserts a write outside `tmp` fails. Makes mine-runtime I4 and I13 structural |
| D3-8 | A driver cannot forge a cache hit, a budget deferral, or its own provenance. | `DriverResult.outcome ∈ {ok, ok_partial}` only; `confidence`, `origin_driver`, `restriction_bits`, `was_cache_hit` are set by the runner |
| D3-9 | A third-party driver cannot run in-process by its own claim. | `inproc` requires first_party/vendored ∧ free ∧ no GPU ∧ no network ∧ green `fuzz` ∧ the id in `[drivers.inproc]`; no config key widens the first four |
| D3-10 | An isolation property that was not obtained is recorded, never claimed. | `HELLO.isolation_granted` echoed into `degradations[]`; a test on a platform lacking net namespaces asserts the record appears |
| D3-11 | A crashing driver never aborts the run. | `FAILED_PERMANENT{DRIVER_CRASHED}` on one unit + stderr tail; 3 crashes/60 s quarantines the driver, the plan re-routes, `degradations[]` records it; the `fuzz` suite ships a deliberate segfault fixture and asserts the run completes |
| D3-12 | A card claim is a test, in both directions. | Conform `capability` derives assertions from the card; `false`/`none`/`[]` is asserted **absent** |
| D3-13 | `[cost]` and `[quality]` are kit-written. | Publish gate rejects author-written values; the loader recomputes `attestation`; `attested = false` ⇒ never auto-selected |
| D3-14 | Every benchmark row carries its `measured_on` tuple. | Card schema `required`; conform `card`. HunyuanOCR's TensorRT-measured 94.10 against a repo shipping Transformers/vLLM is the cautionary case |
| D3-15 | `licence.tier` is computed, never declared. | `compute_tier` in core; `omniweave driver check` exits non-zero on mismatch; index admission re-checks |
| D3-16 | A restricted driver never activates without a valid ack bound to the licence text hash. | resolve gate; mutate the licence file in a test and assert `LICENCE_ACK_STALE` with the hash diff printed |
| D3-17 | Restrictions travel to every derived item and block the OUT direction. | `block.restriction_bits NOT NULL`, set by the runner; the `compile` host refuses, naming the item ids; a test parses with a synthetic restricted driver and asserts the refusal survives parse → derive → compile |
| D3-18 | A transitive licence violation fails the build. | Conform `licence` resolves the dependency graph **and** scans the import graph; fails, never warns; `cairosvg` is the regression fixture |
| D3-19 | Config never names an import path. | The card schema is the only place `entrypoint` exists; a lint rule bans `import_module`/`__import__` outside `host/`; config values naming a driver are validated against registered ids |
| D3-20 | Safety limits are not driver-configurable upward. | Limits are constants in `host/` enforced at the read boundary with `take(N+1)`-then-check; effective = `min(tenant_cap, declared, HOST_MAX)`; a declaration above `HOST_MAX` is `CARD_INVALID` |
| D3-21 | A missing capability is a pruned plan with a report, never an `ImportError`. | `probe()` at preflight; `PROBE_UNAVAILABLE` in `rejected`; `sys.exit` banned in library code |
| D3-22 | A removed driver resolves to a reason, not to "unknown". | Framework-shipped tombstones; a test asserts every vetoed id in the risk register has a tombstone with a non-empty reason and a future `review_by` |
| D3-23 | Conformance is verified from a trusted ref, never from the submission. | CI checks the kit out at a tag; `omniweave drivers verify` re-runs locally; a supplied report alone is never sufficient |

**Build order** — every phase ships something a user runs.

1. **P1 (≈6 wk).** `omniweave-ports` · card schema + loader + catalog + cache · import-free discovery ·
   `resolve()` + `RejectCode` + `Policy` · `Registry` · tombstones · `parse/1` · `inproc` host with
   `DriverGuard` · **`origin_driver`/`driver_schema_v`/`restriction_bits` columns and the runner's
   stamp** (plumbing only — the column must exist before there is data to migrate) ·
   `omniweave drivers list/explain`. Drivers: anydoc, pdfnative, markitdown (all fidelity `none`,
   `lossy`), olmocr. D3-1..8, 19..22.
2. **P2 (≈4 wk).** `subproc` host + wire protocol + supervisor + per-OS limits + circuit breaker ·
   `omniweave-conform` suites `card`/`purity`/`contract`/`capability`/`idempotence`. **A third party
   can now write a driver and get a green report.** D3-9..13.
3. **P3 (≈4 wk).** Licence facts + `compute_tier` + acks + the `compile` refusal · suites `limits`/
   `sandbox`/`cost`/`licence`/`fuzz` · `derive/1` + `compile/1` · index + lockfile + rot sweep.
   D3-14..18, 23.
4. **P4.** `embed/1` · `acquire/1` breadth (connectors) · `wasm` via anydoc's existing `wasm32`
   target · `omniweave drivers scaffold`.

≈14 engineer-weeks to P3 for two people, plus ~2 weeks of Windows parity budgeted explicitly.

## Rationale

**Discovery must not be execution, and it is the one decision here that cannot be reversed.** Verified
in source: `docling/docling/models/factories/base_factory.py` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)`, and the `allow_external_plugins` test sits
in the *next* loop over `list_name_plugin()` — so the gate suppresses *registration* by code that has
already *executed*, and `process_plugin` then swallows a duplicate as
`logger.warning("%r already registered")`. Four consequences we cannot accept follow: no licence gate
before execution, no cost evidence without paying the import, no catalog without importing everything,
and order-dependent registration. It is also what forces install weight: `torch` and `torchvision` are
**base** dependencies of docling, so you cannot get its DOCX reader without a tensor library
(≈2.5–3.5 GB with CUDA wheels) — against our 250 MB core target. A card fixes all four for the price
of a schema, and the day a driver's entry point is a callable is the day the router can never see cost
without paying it.

**The correct mechanism is a dotted package path, and both card-based proposals got it wrong.** They
specify the entry-point value as a relative filesystem path (`"omniweave_pdfium/omniweave.toml"`).
setuptools validates every entry point against `(?P<module>[\w.]+)\s*(:\s*(?P<attr>[\w.]+))?…$`; I ran
`setuptools._entry_points.validate` on both forms and the path form raises at build time while
`"pkg.sub"` passes. I also measured the ecosystem proposal's alternative — discovering cards by
filtering `Distribution.files` (RECORD) across installed distributions — at **2124 ms** for 328
distributions, against its claim of "1–4 ms measured on an SSD". That is the single load-bearing
factual error in the panel, and it invalidates the mechanism, not merely the number. The specified
form costs `entry_points(group=…)` at **15.3 ms** plus one small read per driver, cached behind a
**1.01 ms** `scandir`+`stat` validity key.

**Five Ports, because each has two or more real implementations and a genuinely different shape.**
Ten roles is a design with `store` admitted as under-designed by its own author and `engine`
carrying a `cost.p95_ms_per_unit` field that means nothing for an attach-or-spawn server. Four
contracts is one too few: an embedder's input is not a DocModel, its output has a `(dim, metric,
normalization, model_id)` contract the index must match (LEANN's `meta.json` is the portability
artefact), and its licence and cost are exactly the things a card exists to declare. So an embedder
is a Driver. What is *not* a Driver is the vLLM engine it talks to — that is a **Service**, named,
host-managed, attach-or-spawn (surya's `SuryaInferenceManager` is the reference shape), with no
unit, no cost-per-unit and nothing for a router to choose between. Two words, two lifecycles, and
still exactly one registry, because Services are not registered by third parties.

**`resolve()` filters; it does not rank.** The pragmatist ranks on a `fidelity_score` over the E11
ladders and then names the failure himself: a VLM declaring `cells_with_spans` outranks marker's
model-free CPU judge declaring `flat_html` and is worse on a ragged financial table. Capability is
expressiveness, not accuracy. Ranking needs measured quality, per-corpus feedback and a budget —
all of which are D4's, and none of which D3 has. Returning `chosen` from D3 would pre-empt the panel
that owns the evidence.

**The driver gets `DriverIO` and nothing else.** This is the ecosystem proposal's best structural
idea and it is nearly free. graphify has four recorded CWD bugs of exactly the shape a writable root
invites (#1774 writing the cache into the analysed tree; #2316 stamping the invoking repo's commit
into the target's graph), and its `cache.put(entries, allowed_units=…)` is the only cache-poisoning
control in 22 repos. Give a driver no cache handle and no writable root and both become
unrepresentable rather than policed. It also keeps the third-party surface tiny while the runtime
evolves freely behind it — a driver written in P2 still compiles in year three.

**Isolation is a host decision with an honest floor, not a uniform tax.** anydoc's measured median is
**4.4 ms** across fourteen formats (its own README benchmark, 100 documents, versus 134.8 ms for
markitdown and 513.6 ms for docling). A cold Python worker costs 200–800 ms, import-dominated, and a
one-shot `omniweave parse report.docx` has exactly one unit to batch — so uniform `subproc` would be a
two-order-of-magnitude regression on the framework's cheapest and most-frequent route, which is
precisely the route that makes omniweave cheaper than every alternative. The answer is not to weaken
isolation but to define narrowly, mechanically, and reviewably where it may be skipped: our own code,
free, no GPU, no network, fuzzed, and named in project config. Everything else — every third party,
every GPU driver, every driver with egress — is `subproc`, where the evidence is overwhelming:
segfaulting C parsers, `subprocess.run` on `libreoffice` with no `timeout=`, `MAX_RETRIES=5 ×
REQUEST_TIMEOUT=1200` = 100 GPU-minutes per document in Unlimited-OCR, and codegraph's measured 22 GB
WAL and exit-137 OOM. In-process, each of those kills the run and discards completed work; out of
process, each is one row.

**Licence is a routing input, and the tier must be computed.** The card declares facts; core derives
the tier; `omniweave driver check` fails on a mismatch, so an author cannot mislabel. Two blocks —
code and weights — because marker, surya and lift ship Apache-2.0 code and a byte-identical OpenRAIL-M
`MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`) whose Attachment A clause 2(c) is a
competitor bar with no threshold and whose clause 8 licenses the **Output**. A single SPDX field
cannot say "run this code against other weights, never these weights." And a tier label alone stops
selection while doing nothing once the output is in the index and a deck is compiled from it three
months later — which is why restriction codes ride every item as `restriction_bits` and the `compile`
host refuses. One smallint column and a partial index turn "may I ship this" into an indexed query.

**The card is the test plan.** Every descriptor in this collection that is not mechanically checked
has already rotted: DataFlow's 171 hand-written `get_desc(lang)` strings with nothing comparing them
to `inspect.signature(run)`; LEANN's `llms.txt` declaring 2 tools against a server shipping 4;
open-slide's `skills-lock.json` hashing only `SKILL.md`. So the kit derives its assertions from the
card **in both directions** — `charspan = false` asserts charspans are absent — and writes `[cost]`
and `[quality]` itself under a recomputable attestation. The bar is honesty, not excellence, because a
quality bar excludes everyone and because what the router actually depends on is not that a driver is
good but that its descriptor is true. That definition does not drift as models improve.

## Rejected

- **Entry points resolving to callables (docling, markitdown, DataFlow)** — verified: pluggy `ep.load()`s
  every entry point in the group before docling's `allow_external_plugins` check runs in the next loop.
  No licence gate before execution, no cost evidence without the import, no catalog without importing
  everything, order-dependent registration.
- **A path-shaped entry-point value (systems, pragmatist)** — fails setuptools' entry-point pattern at
  build time; verified by running `setuptools._entry_points.validate` on both forms. Replaced by a
  dotted package path with the card inside it.
- **Card discovery by scanning `Distribution.files`/RECORD (ecosystem)** — measured at 2124 ms for 328
  distributions against a claimed 1–4 ms. Three orders of magnitude wrong, and it is the discovery path.
- **Ten roles including `engine` and `store` (systems)** — `store` cannot be subprocess-isolated without
  paying IPC per row and is admitted first-party-only by its own author; `engine` has no unit, no
  cost-per-unit and an attach-or-spawn lifecycle. Both are abstractions with one implementation sharing
  a schema that does not fit them. `engine` becomes a Service; `store` becomes D5's Backend.
- **Four contracts with embedders as Services (pragmatist)** — an embedder has a model identity that
  enters index metadata, a `(dim, metric, normalization)` contract the store must match, a cost class
  and a licence. That is a Driver with a card. The Service is the engine behind it.
- **`feature_level` as a fourth version axis (systems)** — a second additive number inside a major, with
  a per-driver minimum and a `CONTRACT.md` per level, whose own failure analysis concedes the mitigation
  is social. Replaced by one `card_schema` integer plus the rule that an unknown key inside
  `[capability.<port>]` is ignored with a recorded degradation — safe because an unrecognised capability
  can only make a driver look less capable.
- **Ranking inside `resolve()` on a fidelity score (pragmatist)** — ranks expressiveness, not accuracy;
  a VLM claiming `cells_with_spans` beats a better `flat_html` driver. Capability becomes a filter;
  ranking moves to D4 where the evidence lives.
- **Line-delimited JSON over stdio (pragmatist)** — binary needs base64 (a copy plus 33%), a stray
  banner on stdout breaks framing, and "stdout is protocol only" is a discipline rather than a
  mechanism. Length-prefixed MessagePack on a dedicated 0600 socket makes a banner harmless.
- **A signed hosted registry / sigstore at v1 (ecosystem)** — guards an empty set, adds an availability
  dependency and a key-management rota a small team cannot carry. A recomputable attestation catches the
  realistic failure (a hand-edited card); forgery is a governance problem at this scale, and the docs say
  so plainly.
- **A `container` isolation tier (systems)** — in the vocabulary with no implementation and no first
  user. Adding an enum value later is additive; shipping a mode you cannot run is not.
- **An `x-` experimental artifact-kind namespace (systems)** — reintroduces the DataFlow
  spelling-dependent DAG it was designed to prevent, gated by a flag that will be set. Kinds stay closed;
  a new kind is a core release.
- **Per-unit `route_decision` rows (ecosystem)** — 4,000 JSON rows for one PDF. Replaced by one
  `resolution_report` row per `(run_id, resolution_digest)` with a hit counter.
- **Marker's Provider/Builder/Processor/Renderer as the extension taxonomy** — excellent internally
  (`resolve_dependencies`, 18 lines, no framework, is worth copying *inside* a driver), but its only
  third-party channel is `--converter_cls`/`--processors` through `strings_to_classes`
  (`marker/marker/util.py:15-21`, `import_module` on a caller string) merged from `--config_json`. Config
  that is an import path is RCE the moment config arrives in a request body, and omniweave is served.
- **omniparse's flag-gated model groups** — verified: all four routers are `include_router`ed at module
  scope (`omniparse/server.py:33-36`) and `main()` re-includes them with `include_in_schema=args.*`, so
  the flags gate OpenAPI visibility, not reachability. The idea is right; it becomes
  `policy.allow_classes` + `resolve()`, where a disabled capability names the policy that would enable it.
- **One ABC and a dict, decide later** — the cheapest option and the one that loses on exactly three
  properties that cannot be retrofitted: discovery without import (retrofitting changes every driver),
  licence facts on the descriptor (retrofitting means re-auditing every driver the day a lawyer asks),
  and kit-written quality numbers (retrofitting makes every existing number unverifiable forever).

## Consequences

- **D4 (router)** consumes `Resolution.candidates` plus `[cost]`, `[capability]` and
  `[quality.benchmark]`. It never sees a card it did not get from `resolve()`, never imports a driver,
  and owns ranking outright — including the correction for capability-expressiveness bias that D3
  deliberately does not attempt.
- **D5 (storage)** owns the contents of the `consumes`/`produces` artifact-kind vocabulary; D3 owns the
  rule that it is closed and core-owned. D5 must accept three columns on every produced item
  (`origin_driver`, `driver_schema_v`, `restriction_bits`) plus the partial index, and must ratify
  `embed/1`'s capability block against its own index metadata.
- **D6 (runtime)** keeps `StepResult`, `Outcome`, `UnitRef`, `RunContext`, `canonical_uri`, the `work`
  table and invariants I1–I18 unchanged. Two changes: `OperatorABC`'s ClassVar block moves onto the card
  (a ClassVar requires an import, which is the whole problem), and `ctx.driver(kind)` becomes
  `ctx.service(name)`. An Operator becomes thin — resolve a Driver, invoke it through a `DriverHost`,
  translate `DriverResult` → `StepResult`. Third parties write Drivers; nobody outside core writes an
  Operator.
- **D8 (OUT)** gets `compile/1`, `capability.compile.*`, `parse_back` as a named `parse/1` driver id on
  the card, and the obligation to refuse an artifact containing restricted items.
- **D9 (serve)** gets `licence_notices[]` on the response envelope, the rule that no unattested driver is
  reachable from a serve surface, and `degradations[]` as the single channel for isolation shortfalls,
  deprecations and quarantines.
- **D10 (quality)** owns the golden corpus; D3 owns the kit that runs against it and the five-minute
  budget on its mandatory tier, enforced as a CI timing assertion.
- Core's new dependency surface is `tomllib` (stdlib), a JSON Schema validator and a MessagePack codec —
  three small pure-Python-capable libraries. No torch, no onnx. The 250 MB core target holds *by
  construction*, because core declares no driver extras and imports no driver.
- A driver author's whole surface is `omniweave.ports` (~40 KB) plus `omniweave.testkit`. A driver cannot
  pin the framework, so a core upgrade is never blocked by a driver's floor.
- Two governance artefacts must be kept honest — `omniweave-index` and `omniweave.lock` — plus a
  per-driver conformance CI matrix and the weekly rot sweep. This is a named role with a rota, not a
  background chore; an unstaffed registry degrades to unverified cards, which is docling's present state
  with more ceremony.
- Windows parity is real work and is budgeted, not discovered: Job Objects instead of `RLIMIT_AS`, named
  pipes with an owner-only DACL instead of a 0600 socket, no `fork`, no net namespaces. Where a control
  is unavailable the achieved level is recorded, never claimed.

## Risks

- **The card lies in a way the kit cannot catch.** The kit catches shape lies (declared
  `cells_with_spans`, returned none) and cost lies (measured p95 > 3× declared). It does not catch
  structurally-valid garbage spans. D4's per-corpus quality feedback is the only real defence and it is
  lagging. A card is a bound, never a promise of excellence.
- **`schema_version` is hand-maintained, and forgetting to bump it silently serves stale cached output.**
  This is the most expensive single mistake available in the design. Mitigation is review plus a kit
  check that diffs output across two tagged versions — which the kit can do and should, from P3.
- **Attestation is tamper-evidence, not authentication.** An author can run the kit on a clean build and
  ship a different wheel with the same card. Only `dist_sha256` in `omniweave.lock` catches it, and only
  for consumers who installed through the index. Say so in the docs rather than implying a signature.
- **`subproc` is not a security boundary without OS support.** Net namespaces are Linux-only; on macOS
  and Windows `needs_network = false` degrades to a process-level guard a determined malicious driver in
  that process can bypass. A compromised publisher's driver with read access to `source_ro` can exfiltrate
  a corpus. That is the residual risk and it is written down, not argued away.
- **A first-party `inproc` segfault still kills the process.** The `fuzz` gate and the narrow eligibility
  set reduce the probability; they do not eliminate it. anydoc's 12 cargo-fuzz targets are the reason
  this is tolerable for the one driver that most needs it.
- **Mixed granularity on a large document is unresolved.** One granularity per card forbids mixing within
  a `(unit, port)`, but the realistic input — 3,999 digital pages and one scan — wants a
  document-granularity parse with a part-granularity escalation. That is two artefacts for one document,
  and the shrink guard and cost model must understand layers.
- **The kit rots or gets skipped.** If the golden corpus grows and the mandatory tier stretches past five
  minutes, CI starts getting skipped and the honesty guarantee dies quietly. The timing assertion is the
  only defence and it must be treated as a correctness test.
- **The fixture corpus is itself a licence problem.** Forty real documents redistributed publicly need the
  same `{licence, licence_url, spdx, source_url, retrieved_at, sha256}` ledger hyperframes uses for media.
  Get it wrong and the conformance kit is the thing that cannot ship.
- **A tombstone can become wrong.** If Datalab relicenses, `parse.ocr.surya` resolves to a stale refusal
  quoting a superseded clause. `review_by` plus a CI check on it is the mitigation; it is procedural.
- **`restriction_bits` has 32 codes and twelve are used.** A 33rd is a migration on a hot table. The
  reservation is documented; the migration path is not designed.

## Terminology

- **Port** := a typed, versioned seam identified as `<name>/<major>`. Exactly five at v1: `acquire`,
  `parse`, `derive`, `embed`, `compile`. Never a network port — say "listener".
- **Driver** := one implementation of exactly one Port, shipped as one distribution, described by one
  DriverCard. Parsers, OCR engines, chunkers, extractors, embedders, generators and connectors are all
  Drivers.
- **DriverCard** := the generated TOML descriptor (`driver.toml`) that core reads without importing the
  driver. The only thing `resolve()` sees. Never called a manifest — "run manifest" is D6's.
- **driver.toml** := the on-disk file holding one DriverCard, inside the package the entry point names.
- **DriverId** := `<port>.<subject>.<impl>`, e.g. `parse.doc.anydoc`. Fully qualified as `<id>@<dist>`.
- **Catalog** := the set of DriverCards discovered from all sources for one run, with a digest.
- **Requirement** := what a caller needs from a Port — format, produced kinds, capability floors, cost
  ceiling, granularity, optional pin.
- **Capability floor** := the minimum acceptable value of one capability field. Ordered fields compare
  `>=`; `math` is a set and compares `⊇`; `charspan` is a boolean.
- **Resolution** := the pure output of `resolve()`: unordered admitted `candidates`, every `Rejection`,
  and a `resolution_digest`. Never contains a chosen driver.
- **Rejection** := `(DriverId, RejectCode, detail)`. A zero-candidate Resolution *is* the error message.
- **Service** := a host-managed shared resource a Driver requests by name through `io.service(name)` —
  a vLLM engine, an ONNX session, an embedding server. Attach-or-spawn lifecycle, no unit, no card, never
  routed, never third-party-registered.
- **Backend** := a store implementation (SQLite, Postgres). D5's contract. Not a Port, not carded.
- **DriverIO** := the only channel a Driver has to the outside: blobs, a per-invocation tmpdir, deadlines,
  a cancel check, a logger, a progress reporter, `service()`. No store, no cache, no budget ledger, no
  writable output or cache root.
- **DriverResult** := what a Driver returns (`ok` | `ok_partial` plus artifacts and metrics). Strictly
  smaller than the runtime's `StepResult`, which the runner constructs.
- **DriverHost** := the executor for one Isolation mode: `inproc`, `subproc`, `wasm`.
- **Isolation** := `inproc | subproc | wasm`. Declared as a need by the card; decided by the host, which
  may only tighten.
- **TrustTier** := `first_party | vendored | pinned | local | unpinned`. Gates whether `inproc` is
  representable and whether a driver activates under `require_lock`.
- **LicenceTier** := `open | restricted | commercial | forbidden`. **Computed** by core from the card's
  licence facts; never typed by an author.
- **Restriction** := one of 32 reserved closed-vocabulary licence restriction codes
  (`output_share_alike`, `competitor_bar`, `territory_excluded`, …).
- **restriction_bits** := the integer bitmask over Restriction codes, set by the runner from the
  producing card and carried on every produced item. The single name for this concept — never
  "encumbrance".
- **Tombstone** := a framework-shipped card for a forbidden or removed DriverId that resolves to a quoted
  reason and a replacement instead of "unknown driver". Carries a `review_by` date.
- **Attestation** := `sha256` over the canonical card minus the attestation key, written by
  `omniweave conform`. Tamper-evidence, not a signature. A mismatch sets `attested = false`.
- **ProbeVerdict** := `ok | degraded | unavailable` plus `detail`, `missing[]`, `fix_hint`,
  `capabilities_lost[]`, from running the smallest real operation. Cached per run, persisted 24 h per
  `(driver, version, host_fingerprint)`.
- **omniweave-ports** := the ~40 KB pure-typing distribution (`import omniweave.ports`) that a Driver
  depends on instead of `omniweave-core`. Versioned by Port major.
- **omniweave-conform** := the conformance kit distribution; CLI `omniweave conform`.
- **omniweave-index** := the static, CI-byte-diff-gated `index.json` of card stubs. An index, not a host.
- **omniweave.lock** := the project lockfile pinning every driver by version, ref, card and dist digest,
  licence tier and restriction codes.
- **omniweave.acks.toml** := the reviewable file of per-driver licence acknowledgements, each bound to a
  `licence_sha256` and void when it changes.

## Open questions

- **What a unit is for a 4,000-page PDF, and whether one granularity per card survives it.** D3-13 forbids
  mixing within a `(unit, port)`, so 3,999 digital pages plus one scan becomes a document artefact plus an
  explicit escalation layer. Settled by D6 running both shapes on that exact corpus and comparing the
  shrink guard's and cost model's behaviour; if true mixing is needed, one-granularity-per-card is the
  invariant that gives.
- **Whether `capability.embed` duplicates D5's index metadata.** If D5's index already pins
  `(model_id, dim, metric, normalization, prompt_template)` and refuses a mismatch at write time — LEANN's
  `meta.json` is the reference — the card's embed block may be redundant evidence. Settled by D5's index
  metadata schema; if it pins all five, the card keeps only `dim`, `max_tokens` and `languages` for routing.
- **How much isolation Windows can actually deliver.** Job Objects, named-pipe DACLs and a process-level
  socket guard are not equivalent to `RLIMIT_AS` plus a net namespace. Settled by a one-week spike
  implementing all four controls on Windows and measuring which hold under a hostile fixture; the output is
  the exact degradation string, not a claim.
- **Whether a licence-clean golden corpus can produce numbers comparable to olmOCR-Bench.** We cannot vendor
  OmniDocBench or olmOCR-Bench wholesale, so we take the taxonomy and our own documents — which is correct
  (published numbers are mostly irreproducible; `grep -rn "revision=" marker/ surya/ lift/` returns zero)
  but will read as evasion. Settled by a licence audit of candidate fixture sources plus a correlation run
  of our corpus against published numbers on three drivers where both exist.
- **Whether a hand-maintained `schema_version` can be mechanically defended.** The kit can diff output
  across two tagged versions of a driver and fail when output changed while `schema_version` did not.
  Settled by running that check against two real tagged versions of anydoc and olmocr and measuring the
  false-positive rate on legitimately nondeterministic drivers.
- **Process note, not a design gap:** the panel brief stated the ecosystem-prior proposal was missing. The
  file `_plan/_notes/panels/D3-drivers-ecosystem.md` was present and complete (936 lines) and I read and
  used it; `omniweave-ports`, computed licence tiers, hash-bound acks, `DriverIO`, `ProbeVerdict` and the
  driver-crash circuit breaker come from it. Downstream authors should treat all three proposals as
  inputs to this ruling. Whether the orchestration that reported it missing has a defect worth fixing is
  for the charter stage, not for this panel.
