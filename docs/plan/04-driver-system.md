# 04 — Drivers, Operators and the Extension System

## In one paragraph

Every replaceable part of omniweave is a **Driver**: one implementation of exactly one of five
**Ports** (`acquire`, `parse`, `derive`, `embed`, `compile`), shipped as its own distribution,
described by a **DriverCard** (`driver.toml`) that the host reads with `importlib.metadata` and
`tomllib` and **never imports**. Two things are deliberately not Ports — a **Service** and a
**Backend** — and two things everybody expects to be extension points are not: serialization and the
core Operator. This document specifies the card grammar table by table with its comparison
semantics, the four discovery origins and their millisecond budget, how the probe stays out of the
host process without making `resolve()` impure, the version axes and the complete refusal map, the
isolation policy with a per-OS watchdog and the bounded-reader defences against a hostile driver,
licence tiering and the posture report a commercial deployment runs before it ships, the twelve
conformance suites and what a passing run does and does not entitle an author to claim, a worked
end-to-end publish, and the complete release-1 roster — including the two Ports that ship with
**zero** first-party drivers.

Governing charter sections: **§D3** in full, plus §3.2 (the distribution rule), §3.3 (`layers.toml`),
§3.4 (seams S1/S4), §3.5 (version axes), §5 C1/C2/C5/C6/C10/C12, §5
X1/X4/X5/X10/X11/X15/X20/X21/X35/X37, §6.6, §6.7, §6.10, §6.11, INV-2/3/4/5/6/7/15/16, DR1–DR24.

Where this document decides something the charter leaves open it says so in a numbered **Extends the
charter** note and nowhere else. There are fourteen, listed once here so a reviewer can audit them
without reading the body.

| # | what it adds | why the charter needed it |
|---|---|---|
| E1 | `[capability.acquire\|derive\|embed]` and their non-monotone siblings | §D3 prints only `[capability.parse]`; `Requirement.floors` was unusable for three of five Ports |
| E2 | the closed artifact-kind vocabulary for `consumes` / `produces` | §D3 calls it "a CLOSED, core-owned artifact-kind vocabulary" and never enumerates it |
| E3 | `[config]`'s closed JSON-Schema subset, keyword by keyword | §D3 says "the CLOSED JSON-Schema subset" and stops |
| E4 | the discovery budget ladder and `Degradation(kind="discovery_slow")` | §D1 gives one row (20 installed ≤ 20 ms); the measured environment has 328 |
| E5 | the probe verdict cache, `env_digest`, and `Catalog.probe_status` | `resolve()` filters on a probe verdict and is declared pure and import-free; something had to reconcile them |
| E6 | card-load hardening caps (`MAX_CARD_BYTES` and five others) | the loader parses attacker-adjacent TOML with no stated bound |
| E7 | `[driver] exec` for a non-Python `driver_path` driver | §D3 admits non-Python drivers and gives them no way to name an executable |
| E8 | `[deprecation]`'s shape and its two-MINOR minimum window | `DriverCard.deprecation` is a field with no grammar |
| E9 | `omniweave.lock`'s shape | named in §D1's six config files as "driver pins"; no shape given |
| E10 | `requires_credential` as a `[licence.code]` fact | `compute_tier` reads it; no fact list contains it |
| E11 | `omniweave.acks.toml`'s shape | named in §D1 and §5 X11; no shape given |
| E12 | `ow drivers check --posture` and `omniweave.licence_posture()` | the posture report has no verb in the charter |
| E13 | how `DriverCard.trust` is computed | the field is "COMPUTED BY THE LOADER, NEVER SELF-REPORTED" with no recipe |
| E14 | the four digest recipes | `card_sha256`, `attestation`, `config_digest` and the pins digest are all load-bearing and none is defined |

## 1. The unified extension model

### 1.1 Five Ports, two non-Ports, and the mapping from familiar nouns

The question "is this thing a Driver?" has one mechanical answer: a Driver has a **unit**, a **cost
per unit**, a **licence** and a **replaceable implementation**, and it is **routed** — meaning
`resolve()` may return more than one candidate for the same requirement. Anything failing one of
those five is not a Driver, and the charter names what it is instead. §D3 names exactly two
non-Ports, a **Service** and a **Backend**; an **Operator** is not a non-Port but a non-*Driver* —
core's own scheduled step, which invokes no driver and has no card.

| familiar noun | omniweave concept | Port | ships in |
|---|---|---|---|
| parser, decoder, OCR engine, page VLM | Driver | `parse/1` | `omniweave-office`, `-pdf`, `-vision`, target `back/` packages |
| extractor (entities, claims, fields, cross-references) | Driver | `derive/1` | `omniweave-graph`, `omniweave-llm` |
| chunker / segmenter | Driver | `derive/1` | `omniweave-graph` (`derive.segment.spine`) |
| embedder | Driver | `embed/1` | nothing at release 1 (§10.3) |
| connector (fs, url, SharePoint, IMAP) | Driver | `acquire/1` | nothing at release 1 (§10.3) |
| generator target (PPTX, DOCX, deck, video) | Driver | `compile/1` | `omniweave-target-*` |
| artefact reader (`read_back`) | Driver | `parse/1` | the target's own `back/` package |
| **exporter / serializer (`.owdoc`, Markdown, JSON, text, HTML)** | **not an extension** | — | `omniweave_core.model.serialize()` + `SERIALIZER_CAPS` |
| vLLM / Ollama / any shared model engine | **Service** | — | `omniweave_core.modelserver` (S3) |
| SQLite / Postgres / an ANN index | **Backend** | — | `omniweave_core.store`, `omniweave.backends` entry point |
| `op.identify`, `op.lexicon`, `op.resolve`, `op.cluster`, `op.converge` | **Operator** | — | `omniweave/`, `omniweave/graph/` |
| TypeScript render bundle (deck, video) | **Toolchain** | — | `toolchains/`, invoked over `omniweave-target/1` (S2) |

**The exporter row is the one that surprises people, so it is stated first.** Serialization is not an
extension point. `serialize()` is core's own function over five core-owned formats and its capability
table is `SERIALIZER_CAPS` in [the document model](03-document-model.md) — not a card field, because
a parse driver never calls it, could never write the claim, and the conform `capability` suite would
have nothing to assert in either direction (§5 C2, as amended). A future "export to X" is a
`compile/1` target if X is an artefact a human opens, and a core serializer addition if X is a
lossless projection of L2. There is no third answer and there is no `omniweave.exporters`
entry-point group.

Two further consequences of the test, both recorded in §D3's Rejected list and both worth knowing
before anyone proposes a sixth Port:

- **A Service has no unit and no cost-per-unit.** One engine serves N drivers under an
  attach-or-spawn lifecycle; billing it per invocation is meaningless.
  `surya/surya/inference/__init__.py:86` — `SuryaInferenceManager`, docstring *"Single entry point
  for VLM inference. Construct once per process."* — is the mechanism a Service reproduces, and it is
  why an *embedder* is a Driver while the *engine behind it* is a Service: the embedder has a model
  identity that enters index metadata, a `(dim, metric, normalization)` contract the store must
  match, a cost class and a licence.
- **A Backend cannot be subprocess-isolated without paying IPC per row**, so it is admitted
  first-party-or-named-in-config only, never routed, and never enters `resolve()`. Its four contract
  obligations are [the store's](07-store-and-retrieval.md).

An Operator is also not a Driver, for a third reason: it is not *replaceable*. `evaluate()` never
runs for an `op.*` step, so its `work` rows carry NULL `decision_id`, `driver` and `dispatch_key`
(§5 X41), and the `omniweave.operators` entry-point group stays **reserved and uncreated** until
something appears that a Driver cannot express. A step invoking no driver is not therefore free:
`op.cluster` is `local_compute`.

### 1.2 The base contract, in one sentence and then in code

Every Driver of every Port satisfies exactly this: a class with a `PORT` and `SCHEMA_VERSION` class
variable, a `probe()` classmethod, an `__init__(**config: Scalar)` that loads nothing, one or more
work methods taking a `DriverIO` and returning a `DriverResult`, and a `driver.toml` beside it. No
base class, no registration decorator, no import of the framework beyond `omniweave_ports`.

```python
# omniweave_ports/base.py — the shape every Port protocol repeats. NOT an ABC: a Protocol.
@runtime_checkable
class DriverBase(Protocol):
    PORT: ClassVar[str]              # "<name>/<MAJOR>", asserted against the card by activate()
    SCHEMA_VERSION: ClassVar[int]    # asserted against the card by activate()

    @classmethod
    def probe(cls, env: "ProbeEnv") -> "ProbeVerdict": ...
        # MAY import the driver's own heavy dependencies; MUST NOT download, spawn or write.
        # Runs in a WORKER, never in the host process, and is cached per
        # (driver_id, version, card_sha256, env_digest) under $OMNIWEAVE_HOME. See section 4.7.

    def __init__(self, **config: "Scalar") -> None: ...
        # STATIC CONFIG ONLY, validated against the card's [config] schema BEFORE construction.
        # Constructing a driver MUST load no model and open no file: a 100%-cache-hit run
        # constructs nothing at all, which is why the model load belongs in the first work call.
```

There is no `close()`, no `__enter__` and no explicit teardown on any Port protocol. A `subproc`
worker's lifetime is the host's (`SHUTDOWN`, then SIGTERM, then SIGKILL at +5 s, the whole process
group reaped — §6.3); an `inproc` driver's resources are released when the object is dropped. A
driver needing a flush point uses `atexit` inside its own process and the host does not care.

### 1.3 The vocabulary a driver is written in

`omniweave_ports` is ~40 KB of pure typing and is the whole third-party surface. §D3 prints
`DriverIO`, `DriverMetrics`, `DriverResult`, `DriverError`, `ProbeVerdict` and the enums; the types
those shapes *reference* are printed here because this document is their home and because six of
them carry decisions of their own. All are frozen `slots=True` dataclasses unless marked `Protocol`.

```python
# omniweave_ports/types.py — stdlib only. No pydantic, no numpy, no third party (INV-2, §5 C3).
Scalar = str | int | float | bool | None

@dataclass(frozen=True, slots=True)
class ProbeEnv:
    """What probe() is allowed to know. No writable path, no network handle, no config."""
    platform: str                      # sys.platform
    machine: str                       # platform.machine()
    python: tuple[int, int]
    which: Mapping[str, str | None]    # every [hardware] needs_binaries name -> shutil.which()
    gpu_present: bool                  # ctypes.util.find_library("cuda") is not None. NOT torch.
    vram_gb: float                     # 0.0 when unknown; never obtained by importing a framework
    offline: bool                      # --offline; a probe that would need the network says so

@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """What a driver returns bytes as. Exactly one of `inline` and `blob` is set."""
    kind: str                          # an artifact-kind vocabulary member (section 2.3)
    byte_len: int
    inline: bytes | None = None        # set iff byte_len <= INLINE_MAX (262_144)
    blob: str | None = None            # 'cas://<sha256>' otherwise
    def head(self, n: int) -> bytes: ...      # first n bytes; the only read a driver needs
    @classmethod
    def of(cls, kind: str, body: bytes, io: "DriverIO") -> "ArtifactRef": ...
        # Inlines under INLINE_MAX, io.blobs.put()s above it, and RAISES
        # DriverError(TOO_LARGE, limit="max_output_bytes") when this invocation's running total
        # would cross the ceiling. THE CEILING IS ENFORCED HERE, ONCE, so no driver hand-rolls it
        # and no driver can evade it by writing many small blobs (section 6.5).

class BlobStore(Protocol):
    def path(self, digest: str) -> str: ...   # a READ-ONLY filesystem path under roots.source_ro
    def open(self, digest: str) -> BinaryIO: ...
    def put(self, data: bytes) -> str: ...    # returns a digest; metered through ArtifactRef.of

class ServiceHandle(Protocol):
    """What `DriverIO.service(name)` returns. NOT a client library: a base URL, a token and a
    deadline, which is why `omniweave-llm` needs neither torch nor an SDK (ports-only, 2 MB)."""
    name: str
    base_url: str                  # http://127.0.0.1:<port> — the one sanctioned loopback listener
    token: str                     # 32 bytes from os.urandom, hex; from the 0600 sentinel
    model_id: str
    model_rev: str
    capacity: int
    traceparent: str
    deadline_ms: int
    def post(self, path: str, body: bytes,
             *, headers: Mapping[str, str] | None = None) -> bytes: ...
    def cancelled(self) -> bool: ...

@dataclass(frozen=True, slots=True)
class Locator:                         # acquire/1 input
    scheme: str                        # must be a member of [capability.acquire] schemes
    target: str
    cursor: str | None = None          # opaque iff [acquire] cursor_opaque
    since_ns: int | None = None        # None = full enumeration

@dataclass(frozen=True, slots=True)
class UnitRef:
    uri: str; part: str; content_sha256: str; byte_len: int
    media_type: str | None = None
    # NO unit_id, NO doc_ord, NO block_id. The host mints every durable identity (§5 X1).

@dataclass(frozen=True, slots=True)
class PartSelector:
    pages: tuple[int, ...] = ()        # () = the whole document
    parts: tuple[str, ...] = ()        # container member paths, for a part-granularity driver
    # A fragment naming a page outside this selector is OW_FRAGMENT_OUT_OF_SCOPE.

# The next two live in `omniweave_ports/detect.py` and this is THE declaration of both. Nothing
# else in the plan re-declares them: 05 §2.1 references this block and adds the host-side wrapper.
@dataclass(frozen=True, slots=True)
class StreamHint:
    """What the HOST knows before any driver looks. A hint, never an authority."""
    filename: str | None             # basename only — never a path (a path leaks roots into a card test)
    extension: str | None            # lower-cased, WITH the dot: '.docx'
    declared_media_type: str | None  # an HTTP Content-Type or a connector's claim
    byte_len: int | None             # None for a stream of unknown length
    # NO trust_class. `TrustClass` is routing's, and `omniweave_ports`' layers.toml row is [].

@dataclass(frozen=True, slots=True)
class FormatGuess:
    """One detection candidate as a DRIVER may state it. Four fields, and no more."""
    media_type: str
    format_token: str                # the framework's own token: 'pdf', 'docx', 'eml', …
    confidence: float                # [0.0, 1.0] inclusive; a third party's is CLAMPED to 0.95
    consumed_bytes: int              # how far into the stream the guess looked
    # NO basis and NO detail: `basis` is the HOST's classification of how a guess was obtained,
    # and a driver has no standing to assert it. __post_init__ raises outside [0.0, 1.0].

@dataclass(frozen=True, slots=True)
class DeriveScope:
    lane: str
    units: tuple[UnitRef, ...]
    allowed_cites: frozenset[str]      # THE containment boundary (section 6.6). An item citing
                                       # outside it is quarantined BY THE HOST, not dropped here.
    schema: Mapping[str, object] | None = None    # only when [capability.derive] schema != "none"
    corpus_vocab: tuple[str, ...] = ()            # the closed etype set, when one is configured

@dataclass(frozen=True, slots=True)
class TextBatch:
    texts: tuple[str, ...]
    role: Literal["document", "query"]  # gates the asymmetric instruction prefix, if declared

@dataclass(frozen=True, slots=True)
class EmbedManifest:
    dim: int
    metric: Literal["cosine", "ip", "l2"]
    normalization: Literal["none", "l2"]
    model_id: str
    model_revision: str                 # an EXACT sha; "main" is forbidden framework-wide
    max_tokens: int
```

**`FormatGuess` and `StreamHint` are declared here and nowhere else, and two fields are deliberately
absent from them.** Both types live in `omniweave_ports`, because both are in the signature of
`sniff()` — the first method a third-party `parse/1` driver implements — and a type in a driver's
signature that a driver cannot import is not a contract. `FormatGuess` carries a `format_token` and
**no `basis`**: a driver must be able to name the framework's own token for the format it decoded,
because that token is what a routing rule matches and therefore what makes a new format reachable at
all (§2.2's `format_tokens`), while `basis` is the *host's* classification of **how** a guess was
obtained — magic bytes, container identity, a content probe, an extension, a declaration, a driver's
`sniff()` — and a driver has no standing to assert it. `StreamHint` carries no `trust_class` for the
same reason plus a structural one: `TrustClass` is [routing](05-ingest-and-routing.md)'s type, and
`tools/layers.toml` gives `omniweave_ports = []`, so a `trust_class` field on a ports dataclass would
pull routing across the layer boundary G4 closes.

`sniff()` keeps its signature `def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]`
(§1.4). The host wraps each returned `FormatGuess` in `RankedGuess(guess, basis, detail)` with
`basis = "driver_sniff"` and a `detail` naming the driver id; `RankedGuess` and the six-member `Basis`
alias are host-side types in `omniweave/route/detect.py`, are declared once in
[routing](05-ingest-and-routing.md) §2.1, and may never appear in an `omniweave_ports` inventory.

**What `sniff()` therefore cannot do, stated so no driver author discovers it by failing.** A sniffer
sees `head` — the first 8,192 bytes, one read, and it may not advance the stream
([routing](05-ingest-and-routing.md) §2.1 step 1) — and `FormatGuess` has no "inconclusive, need more
bytes" channel: `consumed_bytes` is a **report of how far the guess looked**, not a request for more.
So a third-party format whose only identifying evidence lives in a **trailer** — a ZIP central
directory, an EOF tag, a footer index — is not identifiable from `sniff()` alone, and a driver for one
returns no guess rather than a low-confidence one. Core covers its own trailer-identified formats
because the magic-byte table and the container-identity step of §2.1's ladder are host code with the
whole stream, not a `head` window: `zip`, `gz`, `tar`, `sevenz`, `rar` and `xz` all resolve there. A
third party has three real paths and no fourth: a head-detectable signature (what almost every format
has), a `[capability] formats` + `format_tokens` pair reached through `hint.declared_media_type` or
the extension table at ladder steps 6-7, or an `acquire/1` driver that sets `declared_media_type`
itself. Widening the window or adding an inconclusive channel is **Q13**.

**`ServiceHandle` is a ports Protocol because the layer graph leaves no other place to put it.**
`tools/layers.toml` gives `omniweave_ports = []`, and [the architecture](02-architecture.md) §3.2
makes a row *the complete allowed set of first-party import roots, transitively closed*, with G4
walking `if TYPE_CHECKING:` blocks alongside module, class and function scope. So `omniweave_ports`
can neither import nor conditionally import `omniweave_core.modelserver`, and the charter's forward
reference `def service(self, name: str) -> "ServiceHandle"` on `DriverIO` would otherwise never
resolve — while `omniweave-llm` and `omniweave-vision`, whose rows are `["omniweave_ports"]`
**exactly**, could not name the type they are handed at all
([repo layout](11-repo-layout.md) §1.2: `omniweave-llm` reaches a model *through `io.service()`* and
by no other route). What satisfies the Protocol does not move:
`omniweave_core.modelserver.ServiceHandle` ([the runtime](08-runtime.md) §3.2; 02 §2 row 15) is the
host-side frozen `slots=True` dataclass, field for field the shape printed above, and it stays where
the charter's module tree puts it
(`modelserver.py  ServiceSpec · ServiceHandle · attach_or_spawn · ServiceRegistry`, seam S3). The
shared name is therefore **a Protocol and its sole implementation** — one concept, one name, one lock
row — and not the one-name-two-types collision Q5 and §5 X14 forbid. It is the identical split
already used for `BlobStore`: the Protocol here, the implementation in `omniweave_core.blobs`
(02 §2 row 17). `service()` is the single widening of "`DriverIO` and nothing else" (§1.5 obligation
1), and what it widens to is a base URL, not a socket. The attach-or-spawn ladder, spawn semantics,
the token rule and `ServiceSpec` are not restated here; they are 08 §3.2's and stay there.

**The `toolchain:` prefix is a different type and not this Protocol.**
[Generation](09-generation.md) §12.2's `io.service("toolchain:deck") -> ToolchainHandle` is a
`compile`-Port-only path whose handle is typed in `omniweave_core.out` — annotated on `CompileV1`'s
`io` parameter, in the one distribution `CompileV1` itself lives in (§1.4) — so it never widens this
Protocol, never enters `omniweave_ports`, and does not contradict 02 §3's process map, whose
`no io.service()` line scopes to the Toolchain **child** process, which holds no `DriverIO` at all: a
compile driver reaching a Toolchain over S2 runs `omniweave_core.toolchain.run` in the host process,
attaches no Service and is handed no `ServiceHandle`.

**`ServiceRegistry` stays out of `omniweave_ports`.** It is core-only, carried on `RunContext`
(08 §1.3), never a module global and never a process singleton, and it is not reachable from a
driver: `DriverIO` exposes `service(name)` and no registry. A `ServiceRegistry` symbol appearing in
`omniweave_ports` is a defect, not a convenience.

Ten of the twelve types declared above have no terminology-lock row — `FormatGuess` and `StreamHint`
are the two that do; see Q3, which counts fourteen across the whole document. Two `omniweave_ports`
export inventories elsewhere stop at `EmbedManifest` and need `ServiceHandle` appended —
[the architecture](02-architecture.md) §2
row 1 and [the API sketch](18-api-sketch.md)'s `omniweave_ports` `T-CONTRACT` row. That is a one-line
correction in each, not a design change.

### 1.4 The five work signatures

The charter prints `ParseV1` in full. The four siblings, printed here because nothing else does:

```python
# omniweave_ports/ports.py
class AcquireV1(Protocol):
    PORT: ClassVar[str] = "acquire/1"
    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
    def enumerate(self, locator: Locator, io: DriverIO) -> DriverResult: ...
        # Emits `owroster-items/1`: one NDJSON record per discovered unit, plus blobs put through
        # io.blobs. The HOST writes `unit` and `ingest_scope` rows. A driver never writes the
        # roster, exactly as a parse driver never writes DocSink (§5 X1).
    def fetch(self, ref: UnitRef, io: DriverIO) -> DriverResult: ...
        # Materialises one unit's bytes into the CAS. Idempotent on content_sha256.

class ParseV1(Protocol):
    PORT: ClassVar[str] = "parse/1"
    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]: ...
        # MANY-TO-ONE and RANKED. MUST NOT advance a stream it is given; the HOST asserts this by
        # passing immutable `bytes` and re-checking the caller's offset.
    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult: ...
        # Emits `owdoc-fragment/1`. Raise DriverError for every failure. NEVER return None and
        # NEVER return an empty success: the host converts an `ok` that fails is_valid_nonempty
        # into FAILED_PERMANENT(EMPTY_RESULT) BEFORE anything is cached.
    def is_valid_nonempty(self, ref: ArtifactRef) -> bool: ...

class DeriveV1(Protocol):
    PORT: ClassVar[str] = "derive/1"
    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult: ...
        # Emits `owgraph-items/1`, and additionally a `witness_set` artefact where the card
        # declares one — which a corpus-granularity billed driver must (section 2.6).

class EmbedV1(Protocol):
    PORT: ClassVar[str] = "embed/1"
    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
    def manifest(self) -> EmbedManifest: ...
        # MUST equal the card's [embed] table field for field, or CARD_CODE_MISMATCH, for the same
        # reason HELLO_ACK is checked: a wrong `dim` corrupts an index with no symptom.
    def embed(self, texts: TextBatch, io: DriverIO) -> DriverResult: ...
        # Emits `owvec-batch/1`: a JSON header plus a raw little-endian f32/int8/bit body. Row
        # order is the input order; a short batch is TOO_LARGE, never a silent truncation.

# CompileV1 lives in `omniweave_core.out.compile`, NOT here (§3.2 rule 4, §5 X4): its signature
# mixes ports types with `Plan`, `ILBundle`, `AssetLedger`, `RuleSpec` and `CarrierDoc`, and a
# Protocol has to live in the one distribution holding both halves. Its seven methods are
# `probe`, `carrier`, `rules`, `measure`, `lower`, `postflight`, `project` — there is no
# `validate()` — and they are specified in 09-generation.md.
```

### 1.5 The four obligations that bind every Port

1. **`DriverIO` and nothing else** (INV-6). No store handle, no cache handle, no budget ledger, no
   `RunContext`, no writable `output_root` or `cache_root`, no socket, no sink. `DriverIO` is frozen
   and **not extensible**; adding a field amends the charter.
2. **The driver proposes, the host commits** (§5 X1). Every Port emits a wire stream addressed by
   per-invocation `tmp` ids and the host mints every durable identity. No `block_id`, `unit_uri`,
   `segment_id` or `entity_id` ever crosses the wire *from* a driver, which is what makes a fragment
   portable between stores.
3. **A driver never forges provenance, price, trust or a cache hit** (INV-7, INV-15).
   `DriverResult.outcome ∈ {ok, ok_partial}`; `DriverMetrics` carries physical units only; the
   runner writes `producer_id`, `origin_driver`, `origin_operator`, `restriction_bits`,
   `confidence`, `was_cache_hit`, every micro and the `MAX_TRUST_BY_METHOD` clamp.
4. **A driver never retries internally.** `[cost.model] max_retries = 0` is the only value a first
   release accepts; retry is the runtime's, with the runtime's budget and the runtime's ledger. The
   receipt is `Unlimited-OCR/infer.py:35-36` — `REQUEST_TIMEOUT = 1200` seconds ×
   `MAX_RETRIES = 5` is a **100-minute** worst case per document (1200 × 5 = 6000 s), with no ledger
   anywhere.

A fifth rule is a consequence of DR20 rather than an obligation of its own, and it is stated because
the instinct of every driver author is to violate it: **a driver does not re-check a host-enforced
ceiling.** `[limits] max_input_bytes` is refused by the host before `INVOKE` is sent; a driver
re-checking it is a second implementation of a safety limit, which is how limits drift apart. §2.6
gives the enforcement side of every declared limit, key by key.

### 1.6 What a driver may import, and the gate that proves it

| Port | permitted omniweave imports | `layers.toml` row |
|---|---|---|
| `acquire`, `parse`, `derive`, `embed` | `omniweave_ports` only; `omniweave_conform.testkit` dev-only | `["omniweave_ports"]` **exactly** |
| `compile` | `omniweave_ports` **and** `omniweave_core` | `["omniweave_core", "omniweave_ports"]` |

G4 reads each distribution's declared entry points and asserts the row its Ports require, so no
author picks and a driver wheel cannot pin the framework. The single carve-out for `compile` exists
because it is the only Port whose *input* the framework validates: a target consumes
`ConstructTable`, `RuleSpec`, `Finding`, `Plan`, `ILBundle`, `AssetLedger`, `CarrierDoc` and
`write_opc()`, and a validator and the thing it validates move together (§3.2 rule 4).
`omniweave-ports` is versioned by **Port major**, not by `RELEASE` — the one exception to "one
`RELEASE`", and the reason a driver pinning `omniweave-ports >=1,<2` has not pinned the framework.
`omniweave-core` depends on `omniweave-ports` (INV-2) and never the reverse, so there is no cycle.

## 2. The capability descriptor

### 2.1 The closed top-level table set, and the one safe asymmetry

**An unknown top-level table or top-level key is a hard error**: a card is a contract, not config.
Inside `[capability.<port>]` an unknown *key* is ignored with a recorded `CARD_CAPABILITY_UNKNOWN`
degradation — the one safe asymmetry, and it is safe only because every key in a
`[capability.<port>]` table is an **ordered ladder or a set-valued floor**, so an unrecognised one
can only make a driver look *less* capable.

The set below is **closed and complete**. A loader implementing it needs no other name, and a PR
adding a row to it bumps `card_schema`.

| table or key | who writes it | unknown key | what it answers |
|---|---|---|---|
| `card_schema` (top-level int) | author | — | the card grammar version; the first key read |
| `attestation` (top-level str) | **`ow conform`** | — | the recomputable digest over everything else |
| `[driver]` | author | hard error | identity, Port, versions, entrypoint or exec, granularity, replay class |
| `[capability]` | author | hard error | `formats`, `consumes`, `produces` |
| `[capability.<port>]` | author | **ignored + degradation** | the monotone capability floors `resolve()` filters on |
| `[<port>]` sibling | author | hard error | non-monotone identity, limits and switches (§5 X37) |
| `[hardware]` | author | hard error | GPU, VRAM, RAM, arch, OS, egress, binaries, install size, Services |
| `[isolation]` | author | hard error | requested mode, memory, deadlines, batch size |
| `[limits]` | author | hard error | declared input ceilings, clamped by `HOST_MAX` |
| `[licence.code]` / `[licence.weights]` | author | hard error | **facts only**; the tier is computed |
| `[deps]` | author | hard error | the pins list, whose digest enters a free driver's cache key |
| `[config]` | author | hard error | the closed JSON-Schema subset (§2.7) |
| `[cost.model]` | author | hard error | the structural cost claim |
| `[deprecation]` | author | hard error | the driver's own retirement schedule (E8) |
| `[cost.measured]` | **`ow conform`** | hard error | measured p50/p95 and a `Spend` vector; author values are **rejected** |
| `[quality]`, `[quality.suites]`, `[[quality.benchmark]]` | **`ow conform`** | hard error | suite results and benchmark rows; author values are **rejected** |
| `[tombstone]` | **omniweave only** | hard error | a refusal, not a driver — its own grammar (§7.5) |

Two structural notes a reviewer checks before reading any card:

- **`[tombstone]` branches first.** The loader tests for `[tombstone]` *before* validating anything
  else, because a tombstone has no `entrypoint`, no `schema_version`, no `granularity` and no
  `replay_class` — all non-optional on `DriverCard` — and its `version` is a wildcard, which is not
  semver. Validating one as a driver card was a guaranteed `CARD_INVALID` on a file whose only job is
  to explain a refusal.
- **`attestation` is a top-level key and is written before the first table header.** This is not
  cosmetic. TOML scopes a bare key to the most recent table header, so an `attestation = "…"` line
  placed after `[quality.suites]` parses as `quality.suites.attestation` and the loader's
  recomputation reads nothing. Writing it on line 2 makes the key unambiguously top-level, which is
  what "a sha256 over the canonical card minus the `attestation` key" requires. `ow conform` writes
  it there and the `card` suite asserts the position.

Because the asymmetry is narrowed to monotone floors, **no `feature_level` axis is needed**: one
`card_schema` integer plus the ignore rule covers forward compatibility for capabilities, and
everything non-monotone lives where an unknown key fails closed.

### 2.2 `[capability.parse]` — the fifteen fields, with comparison semantics

These fifteen are `omniweave_core.model.Capabilities`, `driver.toml [capability.parse]` and
`doc.declared` / `doc.achieved`: **one field set, three homes** (§5 C2). Field *semantics* belong to
[the document model](03-document-model.md); what belongs here is how the router compares them.

| field | domain | comparison | note |
|---|---|---|---|
| `spatial` | `none < page_bbox < block_bbox < line_bbox < char_bbox` | `>=` | |
| `origin_span` | `none < normalized < exact` | `>=` | gates INV-10; `exact` needs a re-verifiable `OriginSpan` |
| `text_span` | bool | `>=` (False < True) | |
| `marks` | bool | `>=` | |
| `reading_order` | `raster < learned < model_emitted < char_stream < source` | `>=` | ordered by marker's measured 75%-vs-56% char-stream-over-learned-head result (`marker/builders/line.py:80-82`) |
| `sections` | `none < markdown_only < outline_from_source < typed_levels` | `>=` | |
| `tables` | `none < flat_html < cells < cells_with_spans` | `>=` | |
| `math` | set over `{latex, mathml}` | `⊇` | a **set**, not a ladder: notation choice, not a quality rung |
| `assets` | `none < refs < bytes` | `>=` | |
| `asset_origin` | bool | `>=` | |
| `notes` | `none < inline < linked` | `>=` | |
| `confidence` | `none < document < page < element` | `>=` | |
| `furniture` | `destroyed < flagged < separated` | `>=` | |
| `round_trip` | `none < text < structure < passthrough` | `>=` | |
| `forfeits` | set over `{blocks, spatial, text_span, citation, round_trip}` | `⊆`, **inverted** | folded in from D4; a floor reads "forfeits nothing I need" |

`forfeits` is the only inverted comparison on the whole card, and therefore the only key a reviewer
should expect to see special-cased in `resolve()`. It is also the single `[capability.<port>]` key
where the ignore-with-degradation asymmetry runs the *wrong* way: an unknown `forfeits` **member** on
a newer card, if ignored, makes the driver look **more** capable. Resolution: an unknown member of
`forfeits` is a **match failure** — `CAPABILITY_BELOW_FLOOR`, detail `forfeits_unknown_member` — and
the card loader records `CARD_CAPABILITY_UNKNOWN` as usual. This narrows the asymmetry from keys to
keys-and-members; it is not a new rule, it is the only exception, and a proposed second one is a
reason to reject the PR. `spanmap` is **not** among the fifteen; see §1.1.

**A sixteenth `[capability.parse]` key, and it is not one of the fifteen: `format_tokens`.** The
fifteen above are one field set with three homes, so each is also a `doc.declared` / `doc.achieved`
field. `format_tokens` is not: it is a card-only declaration, it never appears on a `Doc`, and it is
the key that makes a format a third party invented reachable at all.

| key | domain | what it answers |
|---|---|---|
| `format_tokens` | `list[FormatTokenPair]`, default `[]`; every member an inline table `{ media_type = "<media type>", token = "<token>" }` | the media-type-to-token **pairs** this driver contributes to `unit.format`'s domain. Compared **`⊇`** over the pair set, which fits `05` §2.1's safe-asymmetry rule exactly: an unrecognised member can only make a driver look *less* capable, never more. `token` matches `[a-z0-9]{1,16}` and must not collide with one of core's 48 unless the driver actually parses that format; `media_type` must be a member of the same card's `[capability] formats`; and every pair must appear in the driver's `sniff()` output as a `FormatGuess` whose `media_type` and `format_token` are that pair, or the `capability` suite fails |

**The key is pair-shaped, and that is the whole point of it.** A card that declared bare tokens
would carry two unpaired lists — `[capability] formats` holds media types, `format_tokens` would
hold tokens — and a driver declaring `formats = ["application/warc", "application/warc+gzip"]`
alongside `["warc", "warcgz"]` would supply **no association between them**, leaving routing's
`format_token_for(media_type)` undefined on both and `OW-D-024` undecidable. The pair is therefore
the declaration, and it is the *only* place a third party's media-type-to-token association is
written: nothing infers a pairing from list order, list length or string similarity.

Two derived sets read this key, and each has exactly one owner:

| derived set | scope | defined by |
|---|---|---|
| the **computed format-token domain** | every enabled card at once; it is `unit.format`'s domain | [routing](05-ingest-and-routing.md) §5.1, which owns the computation and the three lint checks that read it — restated in the next paragraph only as far as this document's card validations need |
| a driver's **served token set** | one card | this section: `{ format_token_for(m) for m in [capability] formats }` ∪ `{ p.token for p in [capability.parse] format_tokens }`, with `None` results dropped. Read by `ow route lint` check 11 (`05` §4.5) |

The served token set exists because `[capability] formats` holds **media types** while a routing rule's
`unit.format` clause holds **tokens**, so the two cannot be compared directly. It is the token-side
projection of a card, and it is what a lint check may compare a rule's format literals against.

`unit.format`'s **domain** is therefore computed rather than literal — core's forty-eight tokens ∪ the
union of the `token` fields of `[capability.parse] format_tokens` over every driver in
`[drivers] enabled`, taken at policy-compile time and entering `policy_digest`
([routing](05-ingest-and-routing.md) §5.1 owns that computation and the lint checks that read it).
Three validations are this document's, because all three are card work rather than routing work: a
`format_tokens` member whose `token` regex fails, or whose `media_type` is absent from the same
card's `[capability] formats`, is `CARD_INVALID`; and two enabled cards that pair the **same
`media_type` with different `token`s** are a **card-activation error**, `OW-D-024`, naming both
drivers and both pairs — the `format_token_for(media_type) -> str | None` lookup routing performs
must stay total and single-valued, and an activation that would make it ambiguous is refused at
activation rather than resolved by precedence. Two cards pairing the same `media_type` with the
**same** `token` is not an error: it is two drivers that decode one format, which is exactly what
`resolve()` is for.

A card declares; `doc.achieved` records what the driver delivered on one document, may be **lower**
and may never be **higher**, and serve reads `achieved`, never a card (§5 X9). The `capability`
conformance suite asserts both directions (DR12).

### 2.3 The closed artifact-kind vocabulary

**Extends the charter (E2).** `[capability] consumes` and `produces` are sets over a closed,
core-owned vocabulary that §D3 names and never enumerates, which leaves
`Requirement.requires_produces` and `PRODUCES_INSUFFICIENT` with no domain. The vocabulary is
thirteen members and lives in `omniweave_ports.ArtifactKind`:

| member | produced by | consumed by | payload |
|---|---|---|---|
| `raw_bytes` | `acquire.fetch` | every `parse` driver | a CAS blob plus a `UnitRef` |
| `roster_items` | `acquire.enumerate` | the host | `owroster-items/1` NDJSON |
| `doc_fragment` | `parse.parse` | the host (`DocSink`) | `owdoc-fragment/1` NDJSON |
| `graph_items` | `derive.derive` | the host (`GraphSink`) | `owgraph-items/1` NDJSON |
| `witness_set` | `derive.derive` | the host (`dep` rows) | the foreign `(unit_uri, unit_part, token)` tuples each item consulted — **the only way a driver contributes deps** |
| `vector_batch` | `embed.embed` | the store or a `VectorBackend` | `owvec-batch/1` |
| `text_batch` | the host | `embed.embed` | a `TextBatch` |
| `il_bundle` | the host | `compile.lower` | an `ILBundle` (09) |
| `asset` | `parse`, the host | `compile` | a CAS blob plus a media type |
| `artifact` | `compile` | `read_back` (a `parse` driver) | the compiled file's bytes |
| `receipt` | `compile`, a Toolchain | the host | the validated per-artefact receipt (09) |
| `carrier_doc` | `compile.carrier` | `compile.measure` | an SVG or HTML `CarrierDoc` (09) |
| `diag` | any Port | the host | a `Diag` row; never the sole member of `produces` |

The vocabulary is closed and there is **no experimental namespace** — §D3's Rejected list strikes one,
on the ground that it reintroduces the spelling-dependent DAG a closed vocabulary exists to prevent.
Adding a member bumps `card_schema`. A card declaring a member outside the set is `CARD_INVALID`
naming the member; a `Requirement` whose `requires_produces` is not a subset of a card's `produces`
is `PRODUCES_INSUFFICIENT`.

### 2.4 The three new capability vocabularies

**Extends the charter (E1).** §D3 prints `[capability.parse]` in full and §D8 prints
`[capability.compile]` plus its `[compile]` sibling. The three remaining Ports had no capability
vocabulary at all, which left `Requirement.floors` unusable for `acquire`, `derive` and `embed` and
made `CAPABILITY_BELOW_FLOOR` unreachable for three of five Ports. The three below apply §5 X37's
rule mechanically: **a declaration that is not monotone moves to the `[<port>]` sibling table**,
where an unknown key is a hard error. That is why `[embed]` carries `dim`, `metric` and
`normalization` — "dim ≥ 768" is not a capability floor, a larger dimension is not strictly better,
and an older core silently dropping `dim = 384` from an unknown-key-tolerant table would corrupt an
index with no symptom.

```toml
# [capability.acquire] — ORDERED LADDERS AND SET FLOORS ONLY.
[capability.acquire]
schemes    = ["file"]                   # SET, compared ⊇. The acquire analogue of `formats`.
listing    = "recursive"                # none < flat < recursive
revision   = "content_hash"             # none < mtime < etag < content_hash — change detection
addressing = "uri"                      # path < uri < uri_with_cursor  (resumability)
deletes    = "authoritative"            # none < tombstone < authoritative — coverage needs this
ranges     = true                       # byte-range fetch
streaming  = true                       # emits roster records incrementally, not one big listing
authn      = []                         # SET over {token, basic, oauth2, mtls}, compared ⊇
trust_class_declared = true             # writes `unit.trust_class`; false => the host defaults to
                                        #   untrusted_external, which RAISES audit.rate

[acquire]                               # NON-MONOTONE. Unknown key = HARD ERROR.
implemented        = true
max_units_per_call = 5000
rate_limit_rps     = 0                  # 0 = unlimited; the runtime's AIMD reads this
cursor_opaque      = true               # false => the host may not persist a cursor across runs
```

```toml
# [capability.derive]
[capability.derive]
items       = ["segment"]               # SET, compared ⊇, over the ten item kinds below
grounding   = "quote_verified"          # none < offsets < quote < quote_verified
relations   = "closed_vocab"            # none < closed_vocab < declares_vocab   (§5 X2)
schema      = "none"                    # none < json_schema — accepts a caller-supplied schema
confidence  = "item"                    # none < item < field
coreference = false
scripts     = ["Latin"]                 # SET, compared ⊇, over Unicode script names
scope_honoured = true                   # honours scope.allowed_cites; false => NEVER activatable

[derive]                                # NON-MONOTONE. Unknown key = HARD ERROR.
implemented           = true
phase                 = 50              # ORDERING, not a floor: the second component of the
                                        #   ladder's (cost_rank, phase) key, WITHIN one cost_rank
                                        #   only. Here and NOT in [capability.derive] — ADR-8 D8.4,
                                        #   erratum E71 over the charter's :4893 parenthetical.
max_items_per_segment = 2048            # clamped by MAX_ITEMS_PER_SEGMENT
prompt_version        = ""              # "" for a free pass; a version string for an llm pass
schema_path           = ""              # package-relative; its sha256 is inside card_sha256
```

`items` is a set over exactly `{segment, anchor, xref, entity, alias, mention, edge, claim, summary,
field}` — the eight `owgraph-items/1` frame kinds that carry an item (`cover`, `cover_empty`, `more`
and `diag` are control frames, not items), plus `summary`, which D7's ladder produces and the graph
wire does not print, and `segment`, which `derive.segment.spine` alone prints (D662). `field` is reserved for an extraction driver and has no
first-party producer at release 1. `items` is the input to
[structure extraction](06-structure-extraction.md)'s lane filter.

```toml
# [capability.embed]
[capability.embed]
inputs       = ["text"]                 # SET, compared ⊇, over {text, image, table_text}
quantization = ["f32"]                  # SET, compared ⊇, over {f32, int8, binary}
truncation   = "head"                   # error < head < window_pool
instructions = false                    # asymmetric query/document instruction prefixes
multi_vector = false                    # ColBERT-style; the Backend must also declare it

[embed]                                 # IDENTITY AND LIMITS. Unknown key = HARD ERROR.
implemented    = true
model_id       = "BAAI/bge-m3"
model_revision = "5617a9f61b028005a4858fdac845db406aefb181"  # EXACT sha; "main" is a CARD ERROR
dim            = 1024
metric         = "cosine"               # cosine | ip | l2
normalization  = "l2"                   # none | l2
max_tokens     = 8192
max_units      = 512                    # texts per embed() call
```

Three notes a reviewer will want:

- **`phase` lives in `[derive]`, and this table is its only home on the card.** It is card-declared,
  defaults to 50 and is the second component of the derive ladder's `(cost_rank, phase)` order,
  ordering Passes **within** one `cost_rank` only — `cost_rank` derives from `cost_class` and never
  from the card, so "deterministic before LLM" stays a property of the ledger rather than of a card
  key. It is not in `[capability.derive]` because it is neither ordered-as-a-floor nor set-valued: a
  higher `phase` is not a more capable driver, so it is exactly the non-monotone declaration §5 X37
  sends to the sibling table. The disposition is the point — an unrecognised key under
  `[capability.derive]` is *ignored* with `CARD_CAPABILITY_UNKNOWN`, which is correct for a floor and
  wrong for a key whose default sits in the middle of its range, while an unknown key here is a hard
  error (ADR-8 D8.4; erratum `E71` supersedes the charter's `:4893` parenthetical, and
  [structure extraction](06-structure-extraction.md) §1.8 states the same placement from the
  capability side).
- `scope_honoured = false` on a `derive` card is the one capability value that makes a driver
  permanently **unactivatable** rather than merely unselected. Scope containment is the layer that
  survives a fully successful prompt injection (§6.6), so `resolve()` rejects such a card for every
  requirement with `CAPABILITY_BELOW_FLOOR` detail `scope_not_honoured`, and `ow drivers check`
  reports it as a card defect rather than a limitation.
- `model_revision` repeats `[licence.weights].weights_revision`'s rule because it is the same hazard:
  docling's model `revision` defaults to `"main"` at six declaration sites
  (`docling/docling/datamodel/layout_model_specs.py:87,94,101,108,115,122`) while the field's own
  annotation at `:44` says it names a "Git revision (branch, tag, or commit hash) of the model".
  `revision="main"` is forbidden framework-wide and is `CARD_INVALID` here.

### 2.5 The rest of the descriptor, as the router reads it

The assignment's field list maps onto the card exactly like this. **Every row is readable without
importing the driver**, which is the whole point of the design.

| the router needs | card location | who writes it |
|---|---|---|
| formats | `[capability] formats` (a set of media types, ≤ 64) | author |
| modality / artifact kinds | `[capability] consumes` / `produces` over §2.3's closed vocabulary | author |
| cost class | `[cost.model] class` | author, **kit-verified** |
| cost shape and scaling | `[cost.model] shape / unit / per_part / per_session / scaling` | author (structural) |
| measured cost | `[cost.measured]` p50/p95 plus a `Spend` vector | **kit** |
| hardware requirements | `[hardware] gpu / vram_gb_min / ram_gb_min / cpu_arch / os` | author |
| external binaries | `[hardware] needs_binaries` (≤ 16) | author, probe-verified |
| egress | `[hardware] needs_network` | author, **sandbox-suite-verified** |
| Services required | `[hardware] services` — names, never routed (§5 C5) | author, preflight-verified |
| install weight | `[hardware] install_bytes`, `imports_torch` | author, publish-gate-verified |
| quality profile | `[[quality.benchmark]]` value plus `n`, `ci95`, `witness`, a ten-field `measured_on` | **kit** |
| licence tier | *computed*, never on the card | `compute_tier()` in core |
| licence facts | `[licence.code]`, `[licence.weights]` | author (§7) |
| determinism | `[driver] replay_class` | author |
| streaming support | `[driver] granularity`; `[capability.acquire] streaming` | author |
| version constraints | `[driver] port`, top-level `card_schema`, `[driver] schema_version` | author (§5) |
| isolation request | `[isolation] requires` — the host may only **tighten** | author |
| retirement | `[deprecation]` | author (E8) |

**`granularity` is the streaming axis for `parse` and `derive`,** and it is exactly one of
`document | part | corpus` (§5 C10). It says what one `INVOKE` addresses, which is what lets a
500-page 10-K be a few hundred part-granularity decisions instead of one, and it is why
`[budget.per_part]` can bite at all. A `part`-granularity parse driver receives a `PartSelector`
naming a page range and must not read outside it: a fragment naming a page outside the selector is
refused with `OW_FRAGMENT_OUT_OF_SCOPE`. The shipped ladder pins granularity per pass — free graph
passes route at `document`, billed ones at `part`
(`unit_part = "seg:" || hex(segment.content_digest)[:16]`), and `derive.merge.llm` and
`derive.report.llm` at `corpus`.

**`corpus` granularity carries one extra obligation, and it is a resolve-time gate.** A
corpus-granularity driver reads across units, so its dependency footprint cannot be inferred from
what the runner fed it. It must therefore either declare `witness_set` in `[capability] produces` —
and emit one, listing the foreign `(unit_uri, unit_part, token)` tuples each produced item consulted —
or accept a **Cohort** digest, a merkle over `(unit_uri, unit_part, content_sha256)` in sorted order,
in which case any member change re-derives the whole cohort. A `billed_api` corpus-granularity driver
declaring **neither** is refused with `NO_WITNESS_SET`, because the alternative is a paid derivation
whose incremental correctness nothing can check (I28; G19 is the real enforcer). A free corpus driver
may take the cohort route because re-deriving it is cheap.

**`[cost.model]` is author-declared because it is structural, not measured** (§5 X10): only the author
knows whether the driver loads a model once per session.

| key | domain | what the router does with it |
|---|---|---|
| `class` | `free \| local_compute \| billed_api` | admission, cache namespace, GC policy, `auto_refresh_classes` |
| `shape` | `constant \| linear_per_part \| linear_per_byte \| linear_per_token` | the reservation formula |
| `unit` | `document \| part \| page \| token \| byte` | the denominator of `per_part` |
| `per_part` | a `Spend` vector | the marginal cost of one `unit` |
| `per_session` | a `Spend` vector | model load and warm-up, amortised over a Sequence — the whole reason `inproc_bulk_threshold` exists |
| `scaling` | `{ key, exponent, reference }` — one evidence key, one exponent, one reference value | superlinear or per-byte cost on one measurable input |
| `tokens_out_p95_multiple` | float ≥ 1.0 | reservations use **p95**, never the mean |
| `max_retries` | `0` | see §1.5 obligation 4 |

`tokens_out_p95_multiple` earns its slot from a measurement gap the charter carries as F6: the only
two published anchors for a page VLM's output-token p95 are **3.4× apart**. A reservation model built
on a mean is wrong by that factor on every billed page. `ow drivers check --estimates` fails a
declared p95 multiple that understates the kit measurement by more than **25%**, or an estimate more
than **2×** off the 7-day measured median (DR13).

**`[limits]` declares; the table below says who enforces.** `effective = min(tenant_cap, declared,
HOST_MAX)`, and a declaration above `HOST_MAX` is `CARD_INVALID` (DR20). The split matters because a
limit with two enforcers drifts and a limit with none is decoration.

| limit | `HOST_MAX` | enforced by | how |
|---|---|---|---|
| `max_input_bytes` | `MAX_ENTRY_BYTES = 134_217_728` | the **host**, before `INVOKE` | `unit.byte_len` is known from the roster; the unit is refused with `RESOURCE_LIMIT{max_input_bytes}` and no worker is asked |
| `max_parts` | `MAX_ENTRY_COUNT` | the **driver**, at its read boundary | only the driver can count container members; `take(N+1)`-then-check, then `DriverError(RESOURCE_LIMIT, limit="max_parts")` |
| `[isolation] memory_mb` | physical RAM ÷ `max_workers` | the **host** watchdog | §6.4 |
| `[isolation] progress_ms`, `wall_ms_hard` | none | the **host** supervisor | §6.3 |
| `[isolation] batch_max_units` | `plan_batch = 512` | the **host** dispatcher | one `INVOKE` never carries more |
| blocks per document | `MAX_BLOCKS_PER_DOC` | the **host**, decoding the fragment | a fragment crossing it is `RESOURCE_LIMIT{MAX_BLOCKS_PER_DOC}` and nothing is committed |
| output bytes per invocation | `io.max_output_bytes` | `ArtifactRef.of` in ports | §1.3; a driver never writes this check |

### 2.6 Benchmarks: four required kit-written keys and one digest

`[[quality.benchmark]]` rows are the only place a card carries an accuracy number. Every row requires
`n`, `ci95`, `witness` and a **complete** `measured_on` — all ten fields of `MeasuredOn`, which is
frozen with **no defaults**, so a card supplying seven of them raises `TypeError` at construction
rather than writing a blank cell (DR14, §5 C1). The ten, because nothing else in the plan lists
them: `weights`, `weights_revision`, `runtime`, `runtime_version`, `sampling`, `prompt_version`,
`hardware`, `corpus`, `corpus_digest`, `harness_version`. A pure-code path writes the literal `"n/a"`
where a field does not apply — a None-equivalent that is still a value.

**The corpus digest lives in exactly one place, `measured_on.corpus_digest`, and there is no
row-level twin.** Two fields that must agree are one field plus a bug. DR24 then closes the
run-the-kit-against-a-modified-corpus hole: a row whose `measured_on.corpus_digest` does not match a
digest in the omniweave release manifest is treated as `witness = "self"` **regardless of what it
declares**; a `witness != "ci"` row is **displayed and never ranked**, and is never read by
`ow route propose`. The cautionary case is recorded: HunyuanOCR's TensorRT-measured 94.10 against a
repo shipping Transformers and vLLM.

`min_slice_n = 30` — the same number as `min_audit_n`, reused rather than reinvented. A row with
`n < 30` is refused at load, not rendered with a caveat.

### 2.7 `[config]` — the closed JSON-Schema subset

**Extends the charter (E3).** §D3 calls `[config]` "the CLOSED JSON-Schema subset, as TOML tables"
and stops. The subset has to be closed and small for three reasons: core validates config **before
construction** and therefore ships the validator (INV-2 forbids a `jsonschema` dependency); the
validator's output feeds `config_digest`, which is a cache key; and `ow show-config` renders every
key with its source, which needs a finite type lattice. The subset is:

| keyword | where legal | semantics |
|---|---|---|
| `type` | root and every property | exactly one of `object`, `string`, `integer`, `number`, `boolean`, `array` — never a list of types, never `null` |
| `additionalProperties` | root only | must be present and must be `false` |
| `properties` | root only | a TOML sub-table per property; ≤ 32 properties |
| `required` | root only | an array of property names |
| `default` | every property | required for every property not in `required`; its type must match |
| `enum` | `string`, `integer` | an array of ≤ 32 scalars |
| `minimum`, `maximum` | `integer`, `number` | inclusive |
| `minLength`, `maxLength` | `string` | `maxLength` ≤ 4096 |
| `pattern` | `string` | an `re`-compatible regex ≤ 200 chars, compiled at load |
| `items` | `array` | one `{type, …}` table; arrays of objects are **not** in the subset |
| `minItems`, `maxItems` | `array` | `maxItems` ≤ 256 |

Everything else — `$ref`, `oneOf`, `anyOf`, `allOf`, `not`, `if`/`then`, `patternProperties`,
`dependentSchemas`, `format`, and nested `properties` below depth 3 — is `CARD_INVALID` naming the
keyword. The rejection is not a taste judgement: `$ref` alone turns a 60-line validator into a
resolver with a cycle detector, and a driver's static config has never needed one.

Config values arrive from `omniweave.toml [drivers."<id>"] config` and from nowhere else. DR19 holds
absolutely: a config value may name a registered `DriverId` and may never name an import path.
marker's `--converter_cls` and `--processors` reaching `import_module` on a caller-supplied string,
merged in from `--config_json`, is the anti-pattern — that is remote code execution the moment config
arrives in a request body, and omniweave is served.

### 2.8 The four digests

**Extends the charter (E14).** Four digests are load-bearing and none is defined anywhere. One
canonicaliser serves three of them:

```python
# omniweave_core/drivers/digest.py
def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
```

| digest | over what | why that choice |
|---|---|---|
| `card_sha256` | the **raw bytes** of `driver.toml` as read from disk | the lockfile and G12 pin *bytes*; a comment-only edit must be visible, and a raw-byte digest needs no canonicaliser on the discovery path |
| `attestation` | `sha256(canonical(card_dict))` with the `attestation` key **deleted** | pins *meaning*, so reformatting a card does not invalidate a conformance run. Floats are serialised by `float.__repr__`, which is round-trip-exact for IEEE-754 doubles; `allow_nan=False` plus a card grammar that forbids `nan` and `inf` removes the only remaining ambiguity |
| `config_digest` | `sha256(canonical(effective_config))` after `[config]` validation and default-filling | the worker key is `(driver_id, config_digest)`, so two callers passing the same values in a different order must share a worker |
| the pins digest | `sha256(canonical(sorted(deps.pins)))` | enters the cache key **only** for `cost.model.class = "free"` (§5.1) |

A comment-only card edit therefore changes `card_sha256` and not `attestation`. That is deliberate
and is why both exist: `ow drivers verify` fails on the first (the installed bytes are not the locked
bytes) while `card.attested` stays true (the contract did not change).

## 3. The card, complete, for the driver in the worked example

This is the whole grammar in one file that parses. It is the card written in §9, so §9's commands
operate on exactly this text.

```toml
# omniweave-driver-ipynb/src/omniweave_driver_ipynb/driver.toml
# ONE KEY PER LINE. `;` is not a TOML separator. An inline table may not span a newline.
# `attestation` is a TOP-LEVEL key and is written HERE, before the first table header: TOML scopes a
# bare key to the most recent header, so writing it at the end of the file would make it
# `quality.suites.attestation` and the loader's recomputation would read nothing.
card_schema = 1
attestation = "sha256:f745a15153c4dacf0ea4bbf57265e73283941f8335939b33c693975315cf5916"

[driver]
id             = "parse.notebook.ipynb"
port           = "parse/1"
version        = "0.1.0"
schema_version = 1
title          = "ipynb"
summary        = "Jupyter notebook decoder. Stdlib json only. Exact JSON-pointer node paths."
homepage       = "https://github.com/example/omniweave-driver-ipynb"
entrypoint     = "omniweave_driver_ipynb.driver:IpynbParser"
granularity    = "document"
replay_class   = "byte_exact"
detects        = true

[capability]
formats  = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[capability.parse]
spatial       = "none"
origin_span   = "exact"
text_span     = true
marks         = false
reading_order = "source"
sections      = "markdown_only"
tables        = "none"
math          = []
assets        = "bytes"
asset_origin  = true
notes         = "none"
confidence    = "none"
furniture     = "flagged"
round_trip    = "structure"
forfeits      = []
# `ipynb` is already one of core's forty-eight, so this is a CLAIM TO THE TOKEN — it puts the driver
# in `format_token_for`'s table for that media type — and not a widening of `unit.format`'s domain.
# PAIR-SHAPED (section 2.2): the media type is the lookup key, the token is what a rule matches, and
# `media_type` must also appear in `[capability] formats` above. An array MAY span newlines in TOML;
# each inline table may not.
format_tokens = [
  { media_type = "application/x-ipynb+json", token = "ipynb" },
]

[hardware]
gpu            = "none"
vram_gb_min    = 0
ram_gb_min     = 0.125
cpu_arch       = ["x86_64", "aarch64"]
os             = ["linux", "darwin", "windows"]
needs_network  = false
needs_binaries = []
imports_torch  = false
install_bytes  = 41000
services       = []

[isolation]
requires        = "subproc"
memory_mb       = 256
progress_ms     = 15000
wall_ms_hard    = 60000
batch_max_units = 32

[limits]
max_input_bytes = 67108864
max_parts       = 1

[licence.code]
spdx = "Apache-2.0"
licence_sha256 = "sha256:c693279643b8cd5d248172d9c22cb7cf4ed163a3c98c8a3f69c2717edd3eacb7"
licence_url = "https://github.com/example/omniweave-driver-ipynb/blob/v0.1.0/LICENSE"
notice_path = "NOTICE"
redistribution = "allowed"
output_share_alike = false
competitor_bar = false
requires_credential = false
revenue_gate_usd = 0
mau_gate = 0
territory_excluded = []
field_of_use_excluded = []
attribution_per_output = false
no_model_training = false
remote_kill_switch = false
clause_refs = []

[deps]
pins = []

[config]
type = "object"
additionalProperties = false
required = []
[config.properties.include_outputs]
type = "boolean"
default = true
[config.properties.max_output_chars]
type = "integer"
minimum = 0
maximum = 65536
default = 4096

[cost.model]
class   = "free"
shape   = "linear_per_byte"
unit    = "document"
per_part    = { wall_ms = 3 }
per_session = { }
scaling     = { key = "input_bytes", exponent = 1.0, reference = 65536 }
tokens_out_p95_multiple = 1.0
max_retries = 0

# ══ EVERYTHING BELOW IS WRITTEN BY `ow conform`. AUTHOR VALUES ARE REJECTED. ══
[cost.measured]
p50_ms_per_unit = 3
p95_ms_per_unit = 19
spend_per_unit  = { wall_ms = 3, cpu_ms = 3 }
hardware          = "x86_64-linux 8c/16GiB · min-of-5 warm · in-process"
hardware_spawn    = "x86_64-linux 8c/16GiB · min-of-5 warm · spawn-inclusive"
timing_basis      = "in_process"
# NOT `measured_on`: on a card `measured_on` is always the frozen ten-field MeasuredOn of
# [[quality.benchmark]], so a loader reading the wrong one gets a missing key, never a str
# where it expects a record. `timing_basis` already carries in-process versus spawn.

[quality]
kit_version = "1.0.0"
kit_run = "2026-09-02T11:04:18Z"
[quality.suites]
card = "pass"
purity = "pass"
contract = "pass"
capability = "pass"
idempotence = "pass"
determinism = "pass"
limits = "pass"
sandbox = "pass"
cost = "pass"
licence = "pass"
fuzz = "pass"
quality = "unknown"
```

Six things a reviewer checks in that file before reading a line of code:

1. **`origin_span = "exact"` is a claim with a proof obligation.** The testkit re-reads the retained
   part and asserts `nfc(node_text(part, os_path)) == block.text` on INV-10's `nodepath` branch, per
   fixture. A notebook can honestly make this claim because a `.ipynb` **is** JSON and a JSON pointer
   is a stable node path — which is exactly what `parse.office.anydoc` cannot claim: verified against
   the pinned wheel's source, `_collections/anydoc/src/model/block.rs:5-38` defines `Block` as **eight**
   variants with **no source address of any kind** (only `Asset` carries `origin_part`,
   `src/model/asset.rs:15`), so its card honestly says `origin_span = "none"` and every block from the
   twelve office media types §10.1 lists is `quote = normalized` at release 1.
2. **`marks = false` and `tables = "none"` are asserted *absent*.** The conform `capability` suite is
   derived from the card **in both directions** (DR12): declaring `spatial = "none"` is not a
   failure; declaring `line_bbox` and returning none is. A notebook driver that later starts emitting
   `marks` without bumping the card fails its own conformance run.
3. **`max_parts = 1`, not a large number.** A notebook has exactly one retained part
   (`notebook.json`). The cell count is bounded by `MAX_BLOCKS_PER_DOC`, a host constant enforced
   when the host decodes the fragment — not by a driver-side check, and not by a `[limits]` key that
   would then have two enforcers (§2.5).
4. **`shape = "linear_per_byte"` is reconciled by `scaling`, not by `unit`.** `unit = "document"`
   makes `per_part = { wall_ms = 3 }` "3 ms for a document of `reference` bytes", and
   `scaling = { key = "input_bytes", exponent = 1.0, reference = 65536 }` carries the byte term. A
   `shape` naming a scaling dimension with an empty `scaling` table is `CARD_INVALID`; the `cost`
   suite additionally fits the measured curve and fails a declared shape it contradicts.
5. **`quality = "unknown"`, not a skipped state.** The terminology lock strikes the skip vocabulary
   outright: `unknown` is the value, and `ow eval release-check` refuses on it. The `quality` suite
   is D10's and is non-mandatory, run by `ow conform --bench`.
6. **`[deprecation]` is absent, not empty.** An absent table means "not scheduled for retirement".
   An empty one is a different statement and is `CARD_INVALID`, for the same reason
   `[licence.weights]` is omitted rather than emptied when a driver ships no weights.

## 4. Registration and discovery

### 4.1 Four origins, two entry-point groups, one loader

| origin | how it is declared | trust ceiling | intended for |
|---|---|---|---|
| `entry_point` | `[project.entry-points."omniweave.drivers"]` → `"<id>" = "<dotted.package>"` | `first_party` | installed wheels |
| `driver_path` | a directory on `OMNIWEAVE_DRIVER_PATH`, scanned depth-1 for `*/driver.toml` | `local` | non-Python drivers; development |
| `project` | `.omniweave/drivers/<name>/driver.toml` | `local` | a driver vendored into one project |
| `tombstone` | `omniweave_core/drivers/tombstones/*.toml`, package data | n/a | framework-shipped refusals |

**Two names, two grammars, and they are not the same name.** The entry-point *value* is a
**colon-free dotted package path**, because `setuptools._entry_points.validate` **raises at build
time** on a path-shaped value (`"pkg/driver.toml"`) and accepts `"pkg.sub"`. The card's own
`entrypoint` key is `<dotted.module>:<Attr>` with **exactly one colon and no slash**, because
`activate()` must assert the loaded *class's* `PORT` and `SCHEMA_VERSION` and a package has no such
attributes. Discovery reads the colon-free value and never imports it; `activate()` is the only site
in the framework that resolves the colon form (DR2, §5 C12). Violations: a discovery-time rejection
for an entry-point value containing `:` or `/`; `CARD_ENTRYPOINT_MALFORMED` for a card `entrypoint`
that does not contain exactly one `:` or that contains a `/`. The packaging test builds a wheel and
asserts setuptools accepts the value form, so the rule is proved at build time rather than argued.

A card is located with `Distribution.locate_file(value.replace(".", "/") + "/driver.toml")`.
**Scanning `Distribution.files` / RECORD to find cards is forbidden**: measured at **2124 ms** for
328 installed distributions against a claimed 1–4 ms — three orders of magnitude wrong, on the
discovery path.

**A `compile` driver is discovered through `omniweave.drivers` like every other driver, and is
additionally aliased in a second group.** §5 X5 settles it: both groups stand and both gates apply.

```text
omniweave.drivers  "compile.pptx.native" = "omniweave_target_pptx"        # a DOTTED PACKAGE
                   "parse.pptx.native"   = "omniweave_target_pptx.back"   # the read_back driver
omniweave.targets  "pptx"                = "omniweave_target_pptx"        # an ARTEFACT ALIAS
omniweave.toml     [drivers] enabled = [...]   -> DriverIds     (INV-5, the activation gate)
                   [targets] enabled = ["pptx"] -> artefact kinds (a policy allowlist)
```

`omniweave.targets` exists so `ow out targets` can list an artefact kind without resolving a driver.
**Neither list bypasses the other**, and `ow doctor` fails on a `[targets] enabled` entry whose
`compile` driver is absent from `[drivers] enabled`. A third group, `omniweave.backends`, declares a
`VectorBackend` and is read by this same import-free loader; `omniweave.operators` stays reserved and
uncreated.

`OMNIWEAVE_DRIVER_PATH` is how a driver participates without being installed as a wheel. The
directory holds a `driver.toml` whose `entrypoint` names a module reachable after the directory is
added to `sys.path` — which is what a development driver wants. A driver that is **not Python at
all** needs something the charter's grammar cannot express, so:

**Extends the charter (E7).**

```toml
[driver]
id   = "parse.cad.dwg"
port = "parse/1"
exec = ["bin/owdwg", "--serve"]     # argv, RELATIVE to the card's own directory
```

`exec` and `entrypoint` are **mutually exclusive and exactly one is required** (a tombstone has
neither). `exec` is legal only for `origin ∈ {driver_path, project}`, so such a driver is always
`trust = local` and can never reach `inproc` or satisfy `require_lock = true`. Rules, all of them
`CARD_INVALID` on breach: `argv[0]` must resolve, after `realpath`, to a file **inside** the card's
directory (no `..` escape, no absolute path, no `PATH` lookup); no element may contain a shell
metacharacter, and the host spawns with `shell=False`; `[isolation] requires` must be `"subproc"`.
`activate()` imports nothing for such a driver — the `PORT` and `SCHEMA_VERSION` assertions come from
`HELLO_ACK` alone, which is exactly why `HELLO_ACK` carries them — and `code_fingerprint` is the
sha256 of the executable rather than of the package's `*.py` bytes.

### 4.2 Trust, computed

**Extends the charter (E13).** `DriverCard.trust` is "COMPUTED BY THE LOADER, NEVER SELF-REPORTED"
and the computation is given nowhere. `TrustTier` has five values and the rule is first-match-wins:

| condition | trust |
|---|---|
| `origin == entry_point`, the distribution name is in the release manifest's first-party list, and `dist_sha256` matches the manifest | `first_party` |
| `origin == entry_point`, first-party as above, and the driver wraps third-party source under `vendor/<name>/` carrying a recorded SHA, LICENSE, NOTICE and a G12 parity test | `vendored` |
| `origin == entry_point`, present in `omniweave.lock` with a matching `dist_sha256` | `pinned` |
| `origin ∈ {driver_path, project}` | `local` |
| otherwise (an installed distribution absent from the lockfile, or one whose `dist_sha256` has drifted) | `unpinned` |

`vendored` is the tier that lets `parse.office.anydoc` be `inproc`-eligible: `omniweave-office`
depends on `firecrawl-anydoc == 0.2.4` **and** carries its source at a recorded SHA under
`vendor/anydoc/` with a written fork trigger, which is what makes the code auditable by omniweave's
own CI rather than merely pinned. `unpinned` is not a rejection by itself — `require_lock = true`
(the shipped default) turns it into `NOT_IN_LOCKFILE`, and `[drivers] require_lock = false` is the
operator's own decision to run unpinned code.

### 4.3 What happens at process start — nothing

```text
import omniweave_core          ->  no discovery. No entry_points(). No tomllib.
                                   (INV-3: <= 80 ms; G17 asserts core imports none of
                                    {model, store, archive, retrieve, answer, out, host,
                                     toolchain, modelserver}; G23 asserts no asyncio/selectors)
ow --version | ow hook prompt  ->  no discovery. G26 holds the hook path at 250 ms p95 warm.
first Requirement for a Port   ->  Catalog.build(), ONCE per run, memoised on the validity key.
```

`Catalog.build()`, in order, with the measured cost of each step on the charter's reference machine
(Windows / 3.11.9 / **328 installed distributions**, warm):

| # | step | mechanism | cost |
|---|---|---|---|
| 1 | enumerate entry points | `importlib.metadata.entry_points(group="omniweave.drivers")` | **15.3 ms** |
| 2 | compute the cache validity key | `os.scandir` + `stat` of every `*.dist-info` | **1.01 ms** |
| 3 | scan `OMNIWEAVE_DRIVER_PATH` | `os.scandir`, depth 1 | ~0.1 ms per directory |
| 4 | scan `.omniweave/drivers/` | `os.scandir`, depth 1 | ~0.1 ms |
| 5 | load framework tombstones | package data, 6 files at release 1 | ~1.2 ms |
| 6 | per card, cache **hit** | `json.loads(driver_card_cache.card_json)` | ~0.05 ms |
| 7 | per card, cache **miss** | `locate_file` + `tomllib.load` + validate + `card_sha256` | ~0.35 ms (a 4 KB card) |
| 8 | read the probe verdict cache | one `os.scandir` of `$OMNIWEAVE_HOME/probe/` plus a read per card | ~0.1 ms + ~0.03 ms per card |
| 9 | `catalog_digest` | `sha256(canonical(sorted rows))` | ~0.02 ms |

Steps 1, 2 and 5 are the fixed cost; 6–8 are per card. The card cache is the `driver_card_cache`
table, keyed `(prefix, dist_name, dist_version, card_path)` and validated on `(mtime_ns, size)`; its
DDL belongs to [the runtime](08-runtime.md). **Its validity key costs 1.01 ms for 328
distributions**, which is precisely why the cache is validated wholesale rather than per card.

**The wholesale key has one blind spot and it is the developer's own workflow.** The validity key
stats `*.dist-info`; an editable install (`uv pip install -e .`) leaves `dist-info` untouched while
the author edits `driver.toml` in the source tree, so a wholesale-valid cache would serve the *old*
card through the entire edit-conform-fix loop — the exact loop §9 walks. Resolution: a distribution
whose `dist-info` contains `direct_url.json` with `"editable": true`, or which is reached through a
`.pth`, is **always** stat'ed per card, wholesale key or not. Cost: one `stat` per editable
distribution, which in practice is one.

**One `Catalog` per run, and it is never rebuilt mid-run.** The validity key is re-checked at run
start and at no other time. A catalog that changed under a plan would make `resolution_digest` a lie
and would let two units of one run be parsed by different drivers with no record of why. A
long-running `ow serve` process therefore holds one catalog per run and drops it at run end; at
1.01 ms per check that is free.

### 4.4 The discovery cost budget

**Extends the charter (E4).** §D1's cold-start table gives one row — `driver discovery, 20 installed
≤ 20 ms` — which does not distinguish a 20-distribution environment from a 328-distribution one,
where step 1 alone costs 15.3 ms. The full budget, asserted in `tools/gate_coldstart.py` beside G10,
with the arithmetic shown so a reviewer can check the headroom rather than trust it:

| scenario | fixed | per-card | total | budget | headroom |
|---|---|---|---|---|---|
| 20 drivers, 20 installed distributions, cold | ~2.2 ms | 20 × 0.38 = 7.6 ms | ~9.8 ms | **20 ms** (G10, unchanged) | 2.0× |
| 20 drivers, 328 installed distributions, cold | 16.3 + 1.2 + 0.2 = 17.7 ms | 20 × 0.38 = 7.6 ms | ~25.3 ms | **45 ms** | 1.8× |
| 20 drivers, 328 installed distributions, warm | 17.7 ms | 20 × 0.08 = 1.6 ms | ~19.3 ms | **25 ms** | 1.3× |
| per additional installed driver, cold | — | 0.35 + 0.03 | — | **0.4 ms** | — |
| per additional installed driver, warm | — | 0.05 + 0.03 | — | **0.06 ms** | — |
| hard ceiling, any environment | — | — | — | **250 ms** | — |

The warm row is the tightest at 1.3×, and deliberately so: it is the row a regression would show up
in first, because it is dominated by a single `entry_points()` call whose cost is a property of the
environment rather than of omniweave.

Crossing the 250 ms hard ceiling records `Degradation(kind="discovery_slow")` naming the slowest step
and the installed-distribution count. It is **not** a failure: a user with 900 installed
distributions gets a slow catalog and a report, not a refusal. The whole budget is affordable because
`Catalog` is built at most once per run and `resolve()` is memoised (§4.8).

### 4.5 Card-load hardening

**Extends the charter (E6).** The loader parses TOML that a third party wrote, in a process that must
not be made to allocate or spin. Every cap below is `CARD_INVALID` naming the key and the cap, and
each is enforced with `take(N+1)`-then-check per §6.10 so the memory is never spent first.

| cap | value | derivation |
|---|---|---|
| `MAX_CARD_BYTES` | 65,536 | the largest first-party card (`parse.page.olmocr`, with benchmark rows) is ~8 KB; 64 KB is 8× that |
| table nesting depth | 6 | the deepest legal path is `quality.benchmark[].measured_on.<field>` at 4 |
| `[capability] formats` members | 64 | anydoc's twelve formats (§10.1) is the widest first-party card; 64 covers a plausible universal decoder |
| `[hardware] needs_binaries` members | 16 | — |
| `[deps] pins` members | 256 | — |
| `[[quality.benchmark]]` rows | 64 | the golden corpus has fewer than 20 slices |
| `[config] properties` | 32 | §2.7 |

The loader reads at most `MAX_CARD_BYTES + 1` bytes, parses with `tomllib` (the C parser; no `eval`,
no object hooks), and validates before constructing `DriverCard`. Three failure modes that are not
caps and need naming:

- **The entry point exists and the card does not.** `locate_file(...)` returns a path that is missing
  or unreadable — a partially-uninstalled distribution, a wheel built without package data. This is
  `CARD_INVALID` with detail `card_missing`, plus one `Degradation(kind="driver_unavailable")`
  naming the distribution. Discovery never raises; a broken neighbour cannot stop a catalog.
- **Two distributions declare the same id.** `Registry.register` raises `DuplicateDriver`, `resolve()`
  emits `ID_COLLISION_UNQUALIFIED`, and only an explicit disambiguation proceeds:
  `[drivers.resolve] "parse.office.anydoc" = "omniweave-office"` maps a colliding id to the
  distribution that wins. DataFlow supplies the receipt for why silence is unacceptable — a registry
  keyed on a bare `__name__`, first-wins and silent, so two plugins with one class name means one
  vanishes with no diagnostic.
- **A card is valid and its `[capability.parse]` disagrees with the code.** Not a load-time failure:
  that is the `capability` conformance suite's job, and a card whose recomputed `attestation` does not
  match sets `attested = False` rather than being rejected (§8.3).

### 4.6 Discovery never executes driver code

INV-4, and the one decision here that cannot be reversed. Enforcement is three-layered:

1. `EntryPoint.load()` is banned under `omniweave_core/drivers/` by a rule in
   `tools/semgrep/omniweave.yaml`, alongside the ban on `importlib.import_module` and `__import__`
   outside `host/`.
2. **G11** installs a rogue driver whose module body writes a file and raises `SystemExit`, and
   asserts `ow doctor` succeeds and the file is absent.
3. A core test discovers 30 cards and asserts `sys.modules` gains no `omniweave_driver_*` key.

The charter records why: `docling/docling/models/factories/base_factory.py:96` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)`, and the `allow_external_plugins` test sits
in the **next** loop over `list_name_plugin()` at `:98-105` — so the gate suppresses *registration* by
code that has already *executed*, and `process_plugin` then swallows a duplicate as a
`logger.warning`. Four consequences omniweave cannot accept: no licence gate before execution, no
cost evidence without paying the import, no catalog without importing everything, and
order-dependent registration.

### 4.7 The probe, and how `resolve()` stays pure

**Extends the charter (E5).** This is the sharpest unforced contradiction in §D3 as written.
`resolve()` is declared **pure — no imports, no network, no clock** — and its filter order contains
`probe verdict not unavailable`. But `probe()` may import the driver's heavy dependencies, so calling
it inside `resolve()` would import torch into a process that INV-3 and G17 exist to keep at 80 ms.
Both statements are load-bearing, so the resolution is that **a probe verdict is an input to
`resolve()`, not an action it takes.**

`Catalog` carries the verdicts:

```python
# omniweave_core/drivers/catalog.py
@dataclass(frozen=True, slots=True)
class Catalog:
    cards: Mapping["DriverId", DriverCard]
    probe_status: Mapping["DriverId", Literal["ok", "degraded", "unavailable", "unknown"]]
    validity_key: str          # sha256 over the sorted (dist-info path, mtime_ns, size) triples
    catalog_digest: str        # sha256(canonical(sorted (id, card_sha256, origin, trust, status)))
```

`catalog_digest` includes `probe_status`, so a verdict changing invalidates the resolve memo the same
way a card changing does. `resolve()` reads `probe_status` and treats `unknown` as **passing** the
filter — an unprobed driver is a candidate, not a refusal.

**Preflight closes the loop, out of process.** After `resolve()` returns, the runtime probes every
candidate whose status is `unknown`, in the same `subproc` worker that would run the driver, under
`[drivers] probe_timeout_ms = 2000`. If any verdict comes back `unavailable`, the runtime re-resolves
**once** against the refreshed catalog; the second pass has no `unknown` status for those ids, so
there is no loop and the bound is two resolutions per requirement per run. A driver granted `inproc`
is probed in a worker too, and the worker is then discarded: probing in the host process would import
the driver's dependencies into core, which is the whole thing INV-4 forbids.

The verdict cache is keyed on **`(driver_id, driver_version, card_sha256, env_digest)`** and lives in
`$OMNIWEAVE_HOME/probe/<driver_id>/<version>/<card_sha256>/<env_digest>.json`, one file per key,
written by `os.replace` from a `.tmp` in the same directory so two concurrent processes cannot tear a
row and the loser's write is simply overwritten by an equal value. `card_sha256` is in the key for
the reason §4.4's wholesale validity key has a blind spot — the developer's own workflow: a card
edited in place under an unchanged `[driver] version` moves `[hardware] needs_binaries`, `[config]`
and every other probe-relevant declaration while every other component of the key holds still.
`env_digest` is the **one** name for the environment half of that key — this section is its sole
home and the only place an executable recipe for it is printed. `host_fingerprint` is retired: it
named a host where the digest covers an environment, and a second name for one key is the collision
§5 X14 forbids.

```python
def _ident(p: str | None) -> tuple[str, int, int] | None:      # realpath, size, mtime_ns
    if p is None: return None
    st = os.stat(rp := os.path.realpath(p)); return (rp, st.st_size, st.st_mtime_ns)

env_digest = sha256(canonical({
    "platform": sys.platform,
    "machine":  platform.machine(),
    "python":   f"{sys.version_info.major}.{sys.version_info.minor}",
    "which":    {n: _ident(shutil.which(n))                    # an identity, never a bare path
                 for n in sorted(card.hardware.needs_binaries)},
    "cuda":     _ident(ctypes.util.find_library("cuda")),      # an identity, never a bool
    "epoch":    int(os.environ.get("OMNIWEAVE_PROBE_EPOCH", "0")),
})).hexdigest()
```

**The digest covers identities, not presences.** A bare `shutil.which()` path and a
`find_library("cuda") is not None` boolean both survive the upgrade they are supposed to catch: a
CUDA 12.4 → 12.6 bump moves neither, and a cached `ok` outlives it. `os.path.realpath` resolves
`libcuda.so.1` to `libcuda.so.<driver version>`, so on Linux the driver version enters the digest as
a **name**; `(st_size, st_mtime_ns)` catches the platforms where the name does not move
(`nvcuda.dll`) and catches an in-place `apt upgrade tesseract-ocr` on every platform. **`libcuda` is
never loaded and no framework is imported** — `ProbeEnv.gpu_present`'s "NOT torch" constraint holds
unchanged, and the alternative of calling `cuDriverGetVersion` through `ctypes` was rejected because
it `dlopen`s a vendor driver library in the host process, and a segfault on load is not catchable.
Cost is one `os.stat` per declared binary plus one; §4.4 step 2 prices `os.scandir` + `stat` over 328
distributions at 1.01 ms, so a per-card handful is under 50 µs.

| verdict | cached for | why |
|---|---|---|
| `ok`, `degraded` | the life of the `env_digest` | nothing short of an environment change can make a working driver stop working, and an environment change moves the digest |
| `unavailable` | `probe_ttl_s = 600`, then re-probed | this is the verdict a user *fixes*. Caching it for the life of the digest would mean `apt install tesseract-ocr-deu` had no effect until the next release, because installing a language pack changes neither `shutil.which("tesseract")` nor any other digest input |
| a probe timeout | `probe_ttl_s = 600` | recorded as `ProbeVerdict(status="unavailable", detail="probe timed out after 2000 ms")`; a hung probe is not evidence of a permanent condition |

`ow doctor --refresh-probes` deletes the tree, and `OMNIWEAVE_PROBE_EPOCH` is the escape hatch for a
condition the digest cannot see. A probe is never run more than once per
`(id, version, card_sha256, env_digest)`
per machine, so the ~200–800 ms worker spawn it costs is amortised across every run on that machine —
which is the reason the cache exists at all and the reason `ow doctor` is where a first run pays it.

DR21 holds throughout: a missing capability is a pruned plan with a report, never an `ImportError`.
`ProbeVerdict.missing` is machine-actionable (`("tesseract-lang:deu",)`), `fix_hint` is printed, and
`capabilities_lost` on a `degraded` verdict lets the router re-filter rather than guess. `sys.exit`
is banned in library code.

### 4.8 Installation is not consent

Discovery produces a **catalog**. Activation requires all of `resolve()`'s filter order, in this
order, with the two filters the charter's printed list omits shown in place:

```text
port major supported                          -> PORT_UNSUPPORTED
  -> id not tombstoned                        -> TOMBSTONED (with the quoted reason)
  -> card_schema supported                    -> CARD_SCHEMA_TOO_NEW
  -> format in capability.formats             -> FORMAT_UNSUPPORTED
  -> requires_produces subset of produces     -> PRODUCES_INSUFFICIENT
  -> granularity matches, when requested      -> GRANULARITY_MISMATCH
  -> every requested capability FLOOR met     -> CAPABILITY_BELOW_FLOOR
  -> licence tier allowed AND acknowledged    -> LICENCE_TIER_NOT_ALLOWED | LICENCE_ACK_MISSING
                                                 | LICENCE_ACK_STALE
  -> cost class permitted                     -> COST_CLASS_NOT_PERMITTED
  -> hardware satisfiable                     -> HARDWARE_ABSENT | BINARY_ABSENT
  -> witness set or cohort, if billed+corpus  -> NO_WITNESS_SET
  -> probe status != unavailable               -> PROBE_UNAVAILABLE
  -> not quarantined this run                 -> QUARANTINED
  -> attested, unless explicitly pinned       -> UNATTESTED
  -> present in the lockfile when require_lock -> NOT_IN_LOCKFILE
  -> isolation grantable                      -> ISOLATION_NOT_PERMITTED | TRUST_INSUFFICIENT
```

Plus the gate that is not inside `resolve()` at all: **the id must appear in `omniweave.toml
[drivers] enabled`** (INV-5). That list is the only activation gate, so every driver a policy rule or
a `[graph.passes]` entry names must appear there or it can never run, and `ow doctor` **fails** on a
named-but-unenabled driver.

A **zero-candidate `Resolution` is the error message**: `resolve()` returns
`(candidates=(), rejected=(…))` with a typed `RejectCode` and a detail per considered driver, never a
raise, and `len(candidates) + len(rejected) == len(considered)` is a test (DR5).

`resolve()` never ranks and never chooses: `candidates` is documented unordered and sorted lexically
on `driver_id` before return, so no caller can depend on an emergent order (DR6). Ranking belongs to
[the routing engine](05-ingest-and-routing.md), and the reason the split is absolute is in §D3's
Rejected list: a fidelity score ranks *expressiveness*, not accuracy, so a VLM claiming
`cells_with_spans` would beat a better `flat_html` driver on a ragged financial table.

`resolve()` is pure over `(Requirement, Catalog, Policy)` and a property test shuffles the catalog
100× and asserts an identical `Resolution` (DR4). Purity requires that everything it reads is inside
those three arguments, which has two consequences worth stating because they are easy to get wrong:
**the ack set, the lockfile id set and the tombstone digest set are loaded into `Policy` at startup**,
not read from disk inside `resolve()`, and `policy_digest` covers all three. A `Candidate` therefore
carries the host's decision, never the card's request:

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    card: DriverCard
    isolation_granted: Isolation                # the HOST's decision; never the card's request
    effective_config: Mapping[str, Scalar]      # [config]-validated, defaults filled
    config_digest: str                          # section 2.8
```

**The memo key is a digest of the whole `Requirement`.** The key is
`(requirement_digest, policy_digest, catalog_digest)` — three strings — and `requirement_digest` is
`Requirement.digest`. The charter's printed six-tuple
`(port, format, frozenset(floors.items()), max_cost_class, policy_digest, catalog_digest)` is
superseded: it omits four of `Requirement`'s eight fields, all of which change the answer —
`input_kind`, `requires_produces`, `granularity` and `pinned` — so two requirements differing only in
`granularity` collide and the second silently receives the first's driver. Widening the tuple into
the object is not available either: `Requirement.floors` is `Mapping[str, Scalar | frozenset[str]]`
defaulting to `MappingProxyType({})`, a `mappingproxy` is unhashable, and a frozen `Requirement` is
therefore not a dict key. `Requirement` carries the projection instead:

```python
@dataclass(frozen=True, slots=True)
class Requirement:
    ...                                  # the charter's eight fields, unchanged
    digest: str = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256(canonical({
            f.name: _jsonable(getattr(self, f.name))
            for f in fields(self) if f.name != "digest"
        })).hexdigest())
```

`canonical()` is §2.8's one canonicaliser and there is no second recipe. `_jsonable` sorts a
`frozenset` into a list and takes `.value` from a `StrEnum`; every other field is already a `Scalar`.

**Iterating `dataclasses.fields(self)` rather than a written-out key list is the mechanism, not a
stylistic choice.** A ninth field added to `Requirement` enters the digest with nobody remembering to
add it — which is exactly the property the six-tuple lacked, and the reason it went stale. A recipe
that enumerates the eight names satisfies the sentence above and reinstates the defect on the ninth
field, so **narrowing this to an enumeration is a regression and the `capability` suite's property
tests exist to catch it**: two `Requirement`s differing only in `granularity` must resolve to
different `Resolution`s, and the same for each of `input_kind`, `requires_produces` and `pinned`.

The cost is one `sha256` per `Requirement` **construction**, not per `resolve()` call: the canonical
form of [the architecture](02-architecture.md) §2's worked `Requirement` is 187 bytes and its
`sha256` takes 3.58 µs, so the run bound below — fewer than 128 distinct requirements — puts the
whole-run cost under 0.5 ms. **There is no soundness condition left to state**, which is the point: a
paragraph asserting that every caller today holds four fields constant per `(port, lane)` is
precisely what an out-of-tree caller does not read. What a debugger loses, `ow drivers explain`
recovers — `resolution_report.requirement_json` already holds the whole requirement in canonical
JSON, one row per resolution, and this key reuses that serialisation rather than adding one.

The memo is bounded: `RESOLVE_MEMO_MAX = 512` entries, LRU, held on the `Catalog` instance so it dies
with the catalog rather than leaking across runs in a served process. Derivation: the widest shipped
configuration is 14 ladder passes plus the parse escalation ladder's rungs plus one requirement per
enabled target — fewer than 128 distinct requirements — and each entry is a `Resolution` over ≤ 22
drivers at roughly 2 KB, so the ceiling is about 1 MB.

One `resolution_report` row per `(run_id, resolution_digest)` with a hit counter records what
happened; **per-unit `route_decision` rows for resolution were rejected** — 4,000 JSON rows for one
PDF. Every `RejectCode` member has a row in `codes.toml` under `OW-D-nnn` with the symbol
`OW_DRIVER_<MEMBER>`, so the enum is a typed view over the one register rather than a second
register. `resolution_report.report_json` stores the enum's own wire value (the lower-case member
name) and `ow drivers explain` resolves it through `codes.toml` to the numeric code and the fix
command, exactly as it does for a `Diag`.

The `ow drivers` group is **exactly seven verbs** and no eighth may be added without amending the
generated agent surface (G25, which also asserts no two CLI groups differ only by a trailing `s`):
`scaffold`, `list`, `add`, `verify`, `check`, `explain`, `ack`. Everything this document asks the CLI
to do is a flag on one of those seven.

## 5. Contract versioning

### 5.1 What a driver declares, and what each declaration binds

Three framework version axes exist (`RELEASE`, `CONTRACT`, `SCHEMA`) and **nothing invents a
fourth**. A driver touches four subordinate, per-artefact versions and pins exactly one framework
distribution.

| declaration | on the card | domain | what it binds | who bumps it |
|---|---|---|---|---|
| Port major | `[driver] port = "parse/1"` | `<name>/<int>` | the Protocol signature and the wire stream shape | a core release |
| `card_schema` | top-level `card_schema = 1` | int | the card grammar | a core release |
| `schema_version` | `[driver] schema_version` | int | the driver's **output shape and semantics** | the driver author |
| `version` | `[driver] version` | semver | humans, the changelog and `omniweave.lock` | the driver author |
| the ports pin | `pyproject.toml` `omniweave-ports >=1,<2` | a range | the type vocabulary | Port major |
| `CONTRACT` | not on the card | int, in `omniweave_core.contract` | the ABI a third party may pin | a `RELEASE` MINOR, announced |

The id itself is versionless and its grammar is fixed:
`^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$` (§5 X35). The first
segment **is** the Port, and there are exactly five; `origin_operator` is the first two segments and
`origin_driver` is all three. An id fully qualified against a colliding distribution is written
`<id>@<dist>`.

**`schema_version` is the only driver version that enters a cache key**, and forgetting to bump it is
the most expensive single mistake available in the whole design: it serves stale billed output
forever with no symptom (§6.6). Three defences, and none of them is a gate:

1. review;
2. a kit check that diffs the driver's output across two tagged versions of its own source and fails
   when the bytes changed and `schema_version` did not (`ow conform --diff-against <ref>`);
3. `ow cost --by driver --since 7d` showing a driver's spend fall to zero after a release — a
   **lagging** indicator that requires someone to look.

Because that mistake is unpreventable, the card also records `[deps] pins`, whose digest (§2.8)
enters the cache key **only for `cost.model.class = "free"`**. A free driver's output is cheap to
recompute, so invalidating it on a dependency bump costs nothing; a billed driver's is not, so a
pdfium or tokenizer bump does not silently re-bill the fleet. Whether the *lockfile* digest belongs
in the key is charter F26 and stays open (Q6).

### 5.2 What breaks a contract

| change | breaks | required action |
|---|---|---|
| adding a method to a Port protocol, or a required field to `DriverIO` | Port major | a new Port major, e.g. `parse/2`; both majors coexist and `resolve()` filters on `port major supported` |
| adding a **new** table or top-level key to the card grammar | `card_schema` | bump `card_schema`; older cores reject with `CARD_SCHEMA_TOO_NEW` |
| adding a key to a `[capability.<port>]` table | **nothing** | older cores ignore it and record `CARD_CAPABILITY_UNKNOWN` — the safe asymmetry |
| adding a **member** to a `[capability.<port>]` set-valued key | **nothing**, except `forfeits` | `forfeits` fails closed (§2.2); every other set is a floor and an unknown member only shrinks it |
| adding a key to a `[<port>]` sibling, `[hardware]`, `[isolation]`, `[limits]`, `[licence.*]`, `[cost.*]`, `[deprecation]` | `card_schema` | bump; an unknown key there is a hard error by design (§5 X37) |
| adding a member to the artifact-kind vocabulary | `card_schema` | bump; the vocabulary is closed (§2.3) |
| changing the meaning of an existing card key | `card_schema` **and** a `CONTRACT` bump | announced, migration-guided |
| changing a wire frame's header keys, or adding a frame `kind` | `CONTRACT` | announced; G16 gates it |
| changing a driver's output bytes for the same input | `schema_version` | the author bumps; see §5.1 |
| changing a driver's dependency pins | nothing formally; the pins digest changes | free drivers re-run, billed drivers do not |
| retiring a driver id | nothing | ship a **tombstone** (§7.5) |

A `CONTRACT` bump may happen only on a `RELEASE` MINOR and is an announced, migration-guided product
event. **G16** loads the previous **two** releases' conformance-template drivers against HEAD, so the
window in which a third-party driver keeps working without a rebuild is two minor releases — stated
as a number so an author can plan. A `SCHEMA` major gets the same two-release window (§6.6).

### 5.3 How the core refuses an incompatible driver

Refusal happens at four distinct points, each with its own code, and **none of them imports the
driver except the last**:

```text
1. DISCOVERY (tomllib + validate; no imports)
     card_schema > max(CARDS_SUPPORTED)                 -> CARD_SCHEMA_TOO_NEW
     unknown top-level table or bare key                -> CARD_INVALID (names the table or key)
     entrypoint without exactly one ':' or with a '/'   -> CARD_ENTRYPOINT_MALFORMED
     both `entrypoint` and `exec`, or neither           -> CARD_INVALID
     id not matching the DriverId grammar               -> CARD_INVALID
     a [limits] value above HOST_MAX                    -> CARD_INVALID  (DR20)
     any section-4.5 cap exceeded                       -> CARD_INVALID (names the cap)
     a benchmark row with n < 30, or an incomplete
       measured_on                                      -> CARD_INVALID (TypeError on MeasuredOn)
     a [capability] consumes/produces member outside
       the closed vocabulary                            -> CARD_INVALID
     recomputed attestation != attestation              -> card.attested = False (NOT a rejection)

2. RESOLVE (pure over Requirement x Catalog x Policy; no imports)
     the full filter order of section 4.8, twenty-one codes

3. PREFLIGHT (probe; runs in a WORKER, imports the driver's OWN deps, never the framework's)
     ProbeVerdict.status == unavailable                 -> PROBE_UNAVAILABLE (missing[] is
                                                           machine-actionable; fix_hint is printed)

4. ACTIVATE (the ONLY site that imports card.entrypoint)
     loaded class PORT           != card.port           -> CARD_CODE_MISMATCH
     loaded class SCHEMA_VERSION != card.schema_version  -> CARD_CODE_MISMATCH
     HELLO_ACK {driver_id, version, schema_version, port} != the card
                                                        -> CARD_CODE_MISMATCH, BEFORE any work
```

Step 4 is checked **twice on purpose** — once against the imported class and once against the
worker's `HELLO_ACK` — because an `inproc` driver has no `HELLO_ACK`, an `exec` driver has no
importable class, and a `subproc` worker may be a different build than the card the host read from
disk. `code_fingerprint` in `HELLO_ACK` is the sha256 of the driver package's `RECORD`-listed `*.py`
bytes for a Python driver and of the executable for an `exec` one; a mismatch against the value the
kit recorded is **reported, not refused**, because attestation is tamper-evidence and not
authentication (§6.6).

The complete code set, so no member is orphaned. Twenty-five `RejectCode` members, each with an
`OW-D-nnn` row in `codes.toml`:

| refusal point | codes |
|---|---|
| discovery | `CARD_INVALID`, `CARD_ENTRYPOINT_MALFORMED`, `CARD_SCHEMA_TOO_NEW` |
| resolve — identity | `PORT_UNSUPPORTED`, `PORT_MISMATCH`, `ID_COLLISION_UNQUALIFIED`, `TOMBSTONED`, `DEPRECATED_REMOVED` |
| resolve — fit | `FORMAT_UNSUPPORTED`, `PRODUCES_INSUFFICIENT`, `CAPABILITY_BELOW_FLOOR`, `GRANULARITY_MISMATCH`, `NO_WITNESS_SET` |
| resolve — policy | `LICENCE_TIER_NOT_ALLOWED`, `LICENCE_ACK_MISSING`, `LICENCE_ACK_STALE`, `COST_CLASS_NOT_PERMITTED`, `NOT_IN_LOCKFILE`, `UNATTESTED` |
| resolve — environment | `HARDWARE_ABSENT`, `BINARY_ABSENT`, `ISOLATION_NOT_PERMITTED`, `TRUST_INSUFFICIENT`, `QUARANTINED` |
| preflight | `PROBE_UNAVAILABLE` |
| activate | `CARD_CODE_MISMATCH` |

`PORT_MISMATCH` is the one that reads redundantly next to `PORT_UNSUPPORTED` and is not:
`PORT_UNSUPPORTED` means this core does not implement that Port major at all,
`PORT_MISMATCH` means the caller asked for `derive/1` and the card is a `parse/1` — a caller bug,
raised as a rejection rather than an exception so a mis-wired policy rule produces a report instead
of a traceback.

### 5.4 The deprecation window

**Extends the charter (E8).** `DriverCard.deprecation` is a field with no grammar. It is a top-level
`[deprecation]` table:

```toml
[deprecation]
since       = "0.4.0"          # the RELEASE at which the warning starts
removed_in  = "0.6.0"          # the RELEASE at which resolve() emits DEPRECATED_REMOVED
replaced_by = "parse.pdf.pdfium2"
reason      = "pdfium 6.x changes glyph run grouping; the successor declares char_bbox."
```

`since <= RELEASE < removed_in` records `Degradation(kind="deprecation")` naming the replacement and
still runs the driver. `RELEASE >= removed_in` is `DEPRECATED_REMOVED`, and the author is expected to
ship a tombstone at the same time so DR22 holds — a removed driver resolves to a *reason*, never to
"unknown driver". The **minimum window is two `RELEASE` MINORs**, matching G16's two-release
compatibility promise; a card declaring a shorter one is `CARD_INVALID`, as is one whose
`removed_in <= since`, whose `replaced_by` is not a valid `DriverId`, or whose `reason` is empty.
`replaced_by` may be omitted only when there is no successor, and then `reason` must say so.

### 5.5 The lockfile

**Extends the charter (E9).** `omniweave.lock` is named in §D1's six config files as "driver pins"
and in §6.11 as the only thing that catches a publisher who ships a different wheel than the one the
kit ran against. Its shape:

```toml
lock_version = 1
release = "0.1.0"
contract = 1
generated_at = "2026-09-02T11:31:04Z"

[[driver]]
id = "parse.notebook.ipynb"
version = "0.1.0"
schema_version = 1
dist = "omniweave-driver-ipynb"
dist_version = "0.1.0"
dist_sha256 = "sha256:bcae0416621b3db43d8cba1e4454a792c7af9e4b7287e51056efc5a215d95839"
card_sha256 = "sha256:8367cd66fdd136bba8ba23f8805bb050dd6289401c8ec3b0be44a3c233eef90d"
tier = "open"
restriction_bits = 0
requires = "subproc"
```

`ow drivers add <dist>` writes a row; `ow drivers verify` recomputes `dist_sha256` and `card_sha256`
from what is installed and exits non-zero on any drift; `require_lock = true` (the shipped default)
makes an unlocked id `NOT_IN_LOCKFILE`. `tier` and `restriction_bits` are recorded **in the lock**
deliberately: a licence posture is a reviewable diff in version control, not a value recomputed at
runtime and forgotten. The loader still recomputes both and `ow drivers check` exits non-zero when a
recorded tier disagrees with `compute_tier` (DR15), so the lock is a witness rather than an
authority.

## 6. Isolation

### 6.1 The policy, and it is not negotiable per driver

`subproc` is the default and **the only mode a third party gets**. `inproc` requires **all** of:

```text
trust in {first_party, vendored}
  AND cost.model.class == "free"
  AND hardware.gpu == "none"
  AND hardware.needs_network == false
  AND the `fuzz` conformance suite is green
  AND the id is listed in omniweave.toml [drivers] inproc
```

**No config key widens the first four** (DR9). `[isolation] requires` on the card is a *request* and
the host may only **tighten** it: a card asking for `inproc` that fails any conjunct runs `subproc`
(`Degradation(kind="isolation_shortfall")`, not a refusal), and a card asking for `subproc` can never
be relaxed to `inproc` by config. `[drivers] isolation_floor = "subproc"` (the shipped default)
tightens globally. `wasm` is in the vocabulary and not built at v1; `container` is not in the
vocabulary at all — one is a mode you cannot run, the other is a mode you cannot ship.

At release 1 exactly one driver is `inproc`-eligible and it is named in the shipped config:
`inproc = ["parse.office.anydoc"]`.

**Why the carve-out is narrow rather than absent.** anydoc's measured median is **4.4 ms** across the
fourteen formats of **anydoc's own benchmark denominator** — a benchmark row, never a served-format
count, which is twelve (§10.1) — (`anydoc/README.md:178`; 100 real-world documents, 94 judged for anydoc, versus
**134.8 ms** for markitdown and **513.6 ms** for docling on the same harness), against a 200–800 ms
import-dominated cold Python worker — and a one-shot `ow parse report.docx` has exactly one unit to
batch. Uniform `subproc` is therefore a two-order-of-magnitude regression on the framework's cheapest
and most frequent route. Everything else is `subproc`, and the collection's receipts are
`omniparse/omniparse/documents/router.py:68-76,106-114,152-160` — three
`subprocess.run(["libreoffice", …], check=True)` sites with **no `timeout=`**, inside `async def`
handlers, against a headless singleton — Unlimited-OCR's 100 GPU-minutes per document, and
codegraph's measured **22 GB WAL and exit 137**. In process each of those kills the run and discards
completed work; out of process each is one row.

### 6.2 The `subproc` host, concretely

One long-lived worker per `(driver_id, config_digest)`, **run-scoped**, `worker_idle_ttl_s = 300` (a class at its `max_workers` retires its least recently used worker nobody is calling before it refuses a new one, D653),
over `omniweave-driver/1` (seam S4):

```text
Frame     ::= u32 header_len_le | u32 body_len_le | JSON header (UTF-8) | raw body bytes
Transport ::= AF_UNIX SOCK_STREAM @ 0600  |  Windows named pipe, owner-only DACL
INLINE_MAX = 262144 bytes for the BODY; anything larger travels as a content-addressed blob ref.
```

The body is raw bytes, so binary needs no base64 and core needs no MessagePack codec (§5 C4). Never a
loopback TCP port — `LEANN/packages/leann-core/src/leann/api.py:133-134`'s
`socket = context.socket(zmq.REQ)` / `socket.connect(f"tcp://localhost:{port}")` with no auth and no
CURVE is the named anti-pattern, and it is compute theft from any local process. Never stdio for the
protocol either: stdout and stderr are **captured, logged at debug and never parsed**, because
"stdout is protocol only" is a discipline rather than a mechanism and an MCP server's stderr banner
renders at error level. `omniweave_core.host.wire` is **framing only** (~80 lines) and is fuzzed:
`header_len <= 1 MiB`, `body_len <= INLINE_MAX`, JSON depth cap 32, and an unknown `kind` is a
protocol error. The module is `wire.py` because D2 already defines a Frame as a block-count-bounded
run of Blocks, and two names for two things is the rule (§5 X20).

Eleven frame kinds. This document owns the grammar; [the runtime](08-runtime.md) owns the worker
pool, the dispatch key, the retry ledger and the `driver_observation` table.

| kind | name | direction | header payload |
|---|---|---|---|
| 1 | `HELLO` | host→drv | `{port, card_schema, card_sha256, driver_id, effective_config, roots:{source_ro, tmp}, blob_base, isolation_granted:{…}, traceparent}` |
| 2 | `HELLO_ACK` | drv→host | `{driver_id, version, schema_version, port, code_fingerprint}` — any mismatch against the card is `CARD_CODE_MISMATCH` before work |
| 3 | `PROBE` | host→drv | `{}` |
| 4 | `PROBE_ACK` | drv→host | a `ProbeVerdict` |
| 5 | `INVOKE` | host→drv | `{invoke_id, units:[{uri, part, content_sha256, blob_ref?}], deadline_ms, budget_micros}`; a unit's bytes ride in the body |
| 6 | `RESULT` | drv→host | `{invoke_id, unit_index, …DriverResult}` — **one frame per unit** |
| 7 | `LOG` | drv→host | `{level, event, fields}`, structured only |
| 8 | `PROGRESS` | drv→host | `{invoke_id, unit_index, done, total}` — **the only frame that resets `progress_ms`** |
| 9 | `CANCEL` | host→drv | `{invoke_id, generation}` |
| 10 | `SHUTDOWN` | host→drv | `{grace_ms}` |
| 11 | `FATAL` | drv→host | `{failure_class, detail}` — the driver's last words |

`isolation_granted` is a closed, eight-key record and the worker echoes it in `HELLO_ACK`'s
acknowledgement path so a shortfall is visible from both sides (DR10):
`{mode, address_space_capped, rss_sampled, cpu_capped, fd_capped, net_blocked, tmp_only_writable,
batch_max_units}`. Any boolean that is `false` where the card asked for the property becomes one
`Degradation(kind="isolation_shortfall")` on the result, naming the control and the OS.

Two properties of the batching matter for every downstream document:

- One `INVOKE` carries up to `batch_max_units`; **one `RESULT` per unit**, so the batch is
  **invisible to the `work` table**, the spend ledger, the trace and the failure taxonomy. Batch
  identity is a span attribute, never a row.
- A crashed batch **retries once at `batch = 1`** to localise the poison unit. The death is
  `FAILED_PERMANENT{DRIVER_CRASHED}` on **one** unit with the child's last **4 KiB** of stderr
  attached, and `crash_quarantine = { crashes = 3, window_s = 60 }` quarantines the **driver** — not
  the unit — for the run, re-routing the plan and recording `Degradation(kind="quarantine")`.

### 6.3 The five failure modes, and the mechanism for each

| failure | detector | mechanism | outcome |
|---|---|---|---|
| **segfault / abnormal exit** | `waitpid` returns a signal or a non-zero exit before `RESULT` | retry once at `batch = 1`; attach the last 4 KiB of stderr | `FAILED_PERMANENT{DRIVER_CRASHED}` on one unit; 3-in-60 s quarantines the driver for the run |
| **hang, silent** | `progress_ms` since the last `PROGRESS` frame | SIGTERM, SIGKILL at +5 s, **the whole process group** reaped | `FAILED_PERMANENT{TIMEOUT}`, `limit = "progress_ms"` |
| **hang, chatty** | `wall_ms_hard` since `INVOKE` | the same | `FAILED_PERMANENT{TIMEOUT}`, `limit = "wall_ms_hard"` |
| **memory leak / runaway** | §6.4's per-OS controls | RLIMIT or a job object where available; RSS sampling everywhere; the worker is killed with the call | `FAILED_PERMANENT{RESOURCE_LIMIT}`, `limit = "memory_mb"`, on a unit killed **alone**; a larger batch's units go again at half first ([08-runtime.md](08-runtime.md) §2.2; D657) |
| **malicious** | not detected | containment only; §6.6 | the residual risk, written down |

Three deadlines exist, they are separate and they are separately named: `progress_ms` (a silent
driver), `wall_ms_hard` (a chatty one) and `deadline_ms` on the invocation (the caller's).
**`PROGRESS` is the only frame that resets `progress_ms`.** A `LOG` frame does not, and that is a
deliberate correction of the obvious design: a driver logging in a tight loop while making no
progress would otherwise look alive forever, which is the failure `progress_ms` exists to catch.
`DriverIO.cancelled()` is checked at every loop top and a `CANCEL` frame carries the generation,
because cancellation propagates **by generation, not by signal** — the commit predicate is
`WHERE id=:id AND claimed_gen=:gen AND status='claimed'` and a superseded result **writes nothing**
(§6.7).

### 6.4 The memory watchdog, per OS, with the shortfall recorded

`[isolation] memory_mb` is enforced by whatever the OS actually provides, and **what was not obtained
is recorded rather than claimed** (DR10).

| control | Linux | macOS | Windows |
|---|---|---|---|
| address-space cap | `resource.setrlimit(RLIMIT_AS, …)` in the child before it execs the driver module | `RLIMIT_DATA`, **not** `RLIMIT_AS` | Job Object `JOB_OBJECT_LIMIT_PROCESS_MEMORY` via `ctypes` |
| RSS sampling | `/proc/<pid>/statm` every **250 ms** | `ps -o rss= -p <pid>` every 250 ms (a G8-permitted `subprocess` site inside `host/subproc.py`) | `GetProcessMemoryInfo` via `ctypes` every 250 ms |
| CPU cap | `RLIMIT_CPU` | `RLIMIT_CPU` | not available; `wall_ms_hard` only |
| file-descriptor cap | `RLIMIT_NOFILE` | `RLIMIT_NOFILE` | not applicable |
| priority | `os.nice(10)` | `os.nice(10)` | `SetPriorityClass(BELOW_NORMAL)` |
| no-egress | `unshare(CLONE_NEWUSER \| CLONE_NEWNET)` — `os.unshare` on 3.12+, `ctypes.CDLL(None).unshare` on 3.11 | **not available**; degrades to a process-level guard | **not available**; degrades to a process-level guard |
| writable surface | one per-invocation `tmpdir`, asserted by the `sandbox` suite | the same | the same |

The macOS row is the one a reviewer should check, because getting it wrong is silent:
`graphify/watch.py:221` (`_apply_resource_limits`) selects
`resource.RLIMIT_DATA if sys.platform == "darwin" else resource.RLIMIT_AS`, with the comment
"RLIMIT_AS is unreliable under Apple's libmalloc". omniweave takes that split verbatim and additionally
records `address_space_capped` per platform, so a macOS worker that overshoots is diagnosable rather
than mysterious. graphify's `nice(10)` — "a background rebuild must lose to the user's editor" — is
taken too, and matters more here than there because a VLM parse can allocate gigabytes and an
OOM-killer visit takes the user's editor with it. `DriverMetrics.peak_rss_bytes` carries the sampled
peak into the ledger so an OOM is diagnosable **before** it happens. *(Build note, D921: `wall_ms` and `cpu_ms` are now sampled the same way, so a `PriceBook` that rates them prices a first-party parse, whose drivers report neither. The host reads the worker's CPU from outside: the job's accounting on Windows, which counts exited helpers; `/proc/<pid>/stat` with reaped children on Linux; `ps -o cputime=` on darwin. Each `RESULT` is charged the change since the one before. Wall is always the host's, and CPU is the larger of the host's and the driver's. An in-process call is charged its wall time by the run's clock and keeps its own CPU figure. A real three-driver `ow add` priced at 1 micro a wall ms and 2 a CPU ms billed 82 micros and reconciled under `ow cost --verify`.)* *(Build note, D945: an in-process call's CPU is now the calling thread's across `parse()`, read through `clock.thread_cpu_ns()` and injected. The driver runs on that thread, with only the deadline watchdog on another. The charge is the larger of that figure and the driver's own, and `time.thread_time` joins G8's ambient-clock ban. Still unmetered: CPU under one Windows accounting tick, and the segment and derive operators' calls.)*

Everything in the table is stdlib: `resource`, `ctypes` and `os` are core-permitted, so the watchdog
adds no dependency. RSS sampling at 250 ms is the same cadence as `loop_lag_max_ms = 250`, so the
supervisor loop already wakes at that rate and the watchdog is free. *(Build note, D944: the host sampled only on a tick that found no frame, so a worker whose frames never let the queue run dry, a `PROGRESS` flood or a loaded host's backlog, was never sampled and ran on to its wall clock over the cap. A tick that takes a frame now samples too, once `tick_ms` has passed since the last sample, from the reading taken before the queue read. So a flood pays one sample per tick, not per frame, and a frame taken on the tick that finds the worker over its cap is dropped with the worker.)*

The watchdog's own kill path uses `os._exit`, never `sys.exit`, in the timer fallback: a
`threading.Timer` thread raising `SystemExit` would not stop the main thread — a fact
`graphify/watch.py`'s §3.6(d) states outright and one that turns a wall-clock guard into a no-op if
missed.

`ow doctor --runtime` prints `Σ max_workers × memory_mb` against physical RAM and **refuses above
0.8×**. That is the only place the two counters interact: `[budget] max_inflight` counts **units** in
flight per cost class and `[drivers] max_workers` counts **worker processes** per cost class
(§5 X18). Both exist and both are needed; the shipped defaults are
`max_inflight = { free = 32, local_compute = 4, billed_api = 2 }` and
`max_workers = { free = 4, local_compute = 4, billed_api = 8 }`.

### 6.5 A hostile driver, and the reader that does not oblige it

The watchdog covers a driver that leaks. A driver that is actively adversarial toward the *host*
attacks the reader, not the allocator, and each of those attacks has one mechanism:

| attack | mechanism |
|---|---|
| a 4 GB `header_len` | `header_len <= 1 MiB` and `body_len <= INLINE_MAX` are checked **before** any allocation; the reader allocates exactly the declared length and never speculatively |
| a JSON header nested 10,000 deep | depth cap 32 in the framing layer, enforced during parse |
| a frame flood (millions of `LOG` frames) | the host reads into a bounded queue, `frame_queue_max = 256`. A full queue means the host **stops reading**; pipe backpressure stalls the driver, and `wall_ms_hard` fires. No frame is buffered on the host's behalf |
| a `PROGRESS` flood to hold the worker alive | `progress_ms` resets, but `wall_ms_hard` does not, and it is the backstop. A driver cannot extend its own wall clock |
| many small blobs to evade the output ceiling | `ArtifactRef.of` meters the **running total per invocation** against `io.max_output_bytes`, so 100 blobs of 1 MB each under a 4 MB ceiling raise `TOO_LARGE` on the put that crosses it — enforced in ports, on the host's number, not by the driver's own check |
| a `RESULT` for a unit that was not in the `INVOKE` | `unit_index` is validated against the batch; out of range is a protocol error and the worker is killed, not trusted |
| a fragment naming a page outside the `PartSelector` | `OW_FRAGMENT_OUT_OF_SCOPE`, refused at decode; nothing is committed |
| a `tmp` id referenced and never defined | `OW_FRAGMENT_DANGLING_TMP` fails the **whole document** (and `OW_GRAPH_DANGLING_TMP` quarantines the whole segment); a partial graph is worse than none |
| a derive item citing outside `scope.allowed_cites` | quarantined **by the host**, kept verbatim in a `quarantine` row; the driver's own honesty is not load-bearing |
| a write outside `tmpdir` | the `sandbox` suite asserts it fails; `HELLO` carries only `{source_ro, tmp, blob_base}` and `DriverIO` has no writable root (INV-6, DR7) |

None of that makes `subproc` a security boundary; it makes the host's *availability* independent of
the driver's behaviour, which is a different and achievable property. The security statement is §6.6.

### 6.6 Malicious, stated plainly

Three sentences, and the documentation says them in these words rather than implying otherwise.
**`subproc` is not a security boundary without OS support** — net namespaces are Linux-only, so on
macOS and Windows `needs_network = false` degrades to a process-level guard that a determined
malicious driver in that process can bypass. **A compromised publisher's driver with read access to
`source_ro` can exfiltrate a corpus**; that is the residual risk, and only `dist_sha256` in
`omniweave.lock` narrows it, and only for consumers who installed through the index. **Attestation is
tamper-evidence, not authentication** — an author can run the kit on a clean build and ship a
different wheel with the same card, which is why a signed registry was rejected at v1 (it guards an
empty set and adds an availability dependency plus a key-management rota) rather than shipped as a
half-measure that reads like one.

What *does* hold under a fully successful compromise is scope containment: `allowed_cites` on every
derive run, `allowed_units` on every cache write, and a writable surface of one tmpdir. Those are
structural, and they are what [security](14-security.md) builds on.

### 6.7 `inproc`, and the guard around it

`omniweave_core.host.inproc` wraps an `inproc` driver in a `DriverGuard` that supplies the same
`DriverIO`, the same three deadlines (enforced by a watchdog thread, since RLIMIT is per-process) and
the same `progress_ms` reset semantics. What it cannot supply is crash containment: an `inproc`
segfault kills the run. That asymmetry is the entire justification for the six-conjunct gate, and it
is why `max_inproc = 2` and `inproc_bulk_threshold = 64` exist as `[runtime]` knobs — above 64 units
the per-session model-load amortisation of a worker beats the in-process saving, and the host
switches. Whether the anydoc eager marshal dominates at `max_inproc = 2` is charter F2, closed by
`ow bench inproc` over `fixtures/office-200` at `max_inproc ∈ {1,2,4,8}`; the pre-committed fallback
is `vendor/anydoc/FORK-TRIGGER.md` and a single-buffer return.

## 7. Licence tiering

### 7.1 Facts on the card, the tier computed by core

The card carries **facts only**. `LicenceTier` is computed. **An author cannot mislabel**, and
`ow drivers check` exits non-zero when a stored tier differs from the computed one (DR15).

```python
# omniweave_core/drivers/licence.py — PURE, ~25 lines, unit-tested against all 22 mined repos.
def compute_tier(code: "LicenceFacts", weights: "LicenceFacts | None") -> LicenceTier:
    # forbidden  <= id in the shipped tombstone set
    #               OR licence_sha256 (code or weights) matches a shipped tombstone's
    # commercial <= requires_credential
    # restricted <= competitor_bar | output_share_alike | territory_excluded
    #               | field_of_use_excluded | revenue_gate_usd | mau_gate
    #               | remote_kill_switch | redistribution != "allowed"
    #               | spdx in COPYLEFT_NETWORK | spdx in COPYLEFT_STRONG
    # open       <= otherwise
    ...
```

The tier of a card with `[licence.weights]` is `max(tier(code), tier(weights))` on the ordering
`open < restricted < commercial < forbidden`, because the weakest link governs. `[licence.weights]`
is **omitted entirely** when a driver ships no weights — an empty table is not the same statement as
an absent one — and its `weights_revision` must be an **exact sha**: `"main"` is `CARD_INVALID` and
is banned framework-wide.

**Extends the charter (E10).** `compute_tier` reads `requires_credential` and no `[licence.code]`
fact of that name appears in §D3's card, so the `commercial` tier had no producer. It is added as a
`[licence.code]` fact — `requires_credential = false` in the worked card — because "this licence
requires a purchased credential" is a fact about the same text `licence_sha256` covers, and putting
it anywhere else would give `compute_tier` an input outside the hash the ack is bound to.

### 7.2 The restriction bits, and where they go

`Restriction` is an `IntEnum` with **32 codes reserved**, bit = `1 << value`, twelve defined
(`OUTPUT_SHARE_ALIKE=0` through `COPYLEFT_STRONG=11`) and twenty reserved. A 33rd code is a migration
on a hot table and that is written down. The runner maps each card fact to its bit; **the fact and
its bit differ by casing and nothing else** (`territory_excluded` → `TERRITORY_EXCLUDED`,
`field_of_use_excluded` → `FIELD_OF_USE_EXCLUDED`), so the fact-to-bit map special-cases nothing —
which is exactly why the lock strikes the `_BARRED` spelling.

`restriction_bits` is stamped **by the runner, from the producing card**, onto every block, segment,
entity, mention, edge, claim, asset and artefact (INV-16, DR17). It is `NOT NULL` on every carrier
with partial indexes, and the `compile` host **refuses** to emit an artefact carrying a restricted
item without policy, naming the offending cites and asset ids. A synthetic restricted driver's
refusal is tested parse → derive → compile. This is what makes "a restricted driver contaminated my
deliverable" a refusal instead of a discovery.

Output-side bits exist because `marker/MODEL_LICENSE:39` (clause 8, Share-a-Like) applies the licence
*"to the Output and any derivatives, changes or improvements to or of the Output"*. For a parsing
product that is worse than a revenue gate — it contaminates the deliverable — and no care at install
time helps if the bit does not travel to the artefact.

### 7.3 The acknowledgement file

A `restricted` driver never activates without a valid ack **bound to the licence text's sha256**
(INV-5, DR16). The ack is a reviewable, diffable file, never a boolean in the main config, and it is
**void the moment the licence text changes**.

**Extends the charter (E11)** — the file is named in §D1 and §5 X11 and its shape is not given:

```toml
# omniweave.acks.toml — checked into version control. `ow drivers ack` writes rows; never a boolean.
ack_version = 1

[[ack]]
driver = "parse.pdf.pymupdf"
licence_sha256 = "sha256:37a680133bd09342f934afb8dd2c7d9e1b624da5f35e3a38adb103e37c055ed1"
which = "code"                  # code | weights — one row per licensed artefact
tier = "restricted"
restrictions = ["copyleft_network"]
acknowledged_by = "legal@example.com"
acknowledged_at = "2026-08-30T09:12:00Z"
note = "AGPL-3.0 accepted for internal-only deployment; ticket LEGAL-4471."
```

The ack set is loaded into `Policy` at startup, so `resolve()` reads it as an argument rather than
touching the filesystem, and `policy_digest` covers it (§4.8). Mutating the licence file in a test
and asserting `LICENCE_ACK_STALE` **with the hash diff printed** is a required test. Two rows for the
same `(driver, which)` is a hard error at load — an ack is a decision, and two decisions is none.
`[licence] allow_tiers = ["open"]` is the shipped default, so a restricted driver is refused twice
over on a fresh install: once by the tier allowlist and once by the missing ack.
`[licence] jurisdiction` is checked against `territory_excluded` and `[licence] fields_of_use`
against `field_of_use_excluded`, so a territorial or field-of-use exclusion is a *local* refusal
rather than a global one.

### 7.4 The posture report

**Extends the charter (E12).** The assignment requires a CLI and API that report the licence posture
of an installed configuration; the charter has `ow drivers check` and `ow doctor [--runtime]` and does
not say which reports posture. Decision: **`ow drivers check --posture`**, a report *mode* on an
existing verb — so the `ow drivers` group stays at seven and G25's generated surface is unchanged —
plus the SDK twin `omniweave.licence_posture(config_path=None) -> LicencePosture`.

Run against the shipped default configuration:

```console
$ ow drivers check --posture
omniweave 0.1.0 · config_digest sha256:e67d23e7… · allow_tiers=[open] · jurisdiction=DE

  driver                     tier    restrictions   ack   source
  parse.office.anydoc        open    —              n/a   MIT (code)
  parse.pdf.pdfium           open    —              n/a   Apache-2.0 (code) + BSD-3-Clause (pdfium)
  parse.page.olmocr          open    —              n/a   Apache-2.0 (code + weights)
  derive.segment.spine       open    —              n/a   Apache-2.0 (code)
  derive.anchor.native       open    —              n/a   Apache-2.0 (code)
  derive.anchor.defterm      open    —              n/a   Apache-2.0 (code)
  derive.xref.native         open    —              n/a   Apache-2.0 (code)
  derive.xref.pattern        open    —              n/a   Apache-2.0 (code)
  derive.entity.table        open    —              n/a   Apache-2.0 (code)
  derive.entity.gazetteer    open    —              n/a   Apache-2.0 (code)

  ENABLED SET  (10 drivers)
    effective tier            open
    restriction_bits          0x00000000
    output_share_alike        no      -> compiled artefacts carry no upstream licence obligation
    attribution_per_output    no      -> no per-artefact NOTICE requirement
    redistribution            allowed -> this configuration may be shipped to a customer
    no_model_training         no
    remote_kill_switch        no

  NOT ENABLED, PRESENT IN THE ENVIRONMENT
    compile.pptx.native       open       named by [targets] enabled=["pptx"] and ABSENT from
                                         [drivers] enabled -> `ow doctor` FAILS (§5 X5; see Q1)
    parse.pptx.native         open       the pptx read_back driver, same
    derive.entity.llm         open       billed_api; [drivers.cost] allow_classes excludes it
    parse.page.surya          forbidden  tombstoned: MODEL_LICENSE md5 e1f69b64… Attachment A 2(c)

verdict: CLEAN for a commercial deployment in DE under fields_of_use=[enterprise_documents]
exit 0
```

Semantics, so the report is usable in CI:

- **exit 0** — every enabled driver's tier is in `allow_tiers`, every `restricted` one has a valid
  ack, no `territory_excluded` matches `jurisdiction`, no `field_of_use_excluded` matches
  `fields_of_use`.
- **exit 6** — a policy refusal: a tier outside the allowlist, a missing or stale ack, or a
  territorial or field-of-use hit. The message names the driver, the clause refs and the exact
  command that would resolve it.
- **exit 1** — the configuration itself is unreadable, or a stored tier disagrees with
  `compute_tier`.
- `--render json` emits the `ow drivers check` Action's own generated output schema,
  `schema/drivers-check-out-v1.json` (generated from `LicencePosture`, byte-diff gated under G6 like
  every other Action output), whose top level is `{release, config_digest, allow_tiers, jurisdiction,
  fields_of_use, drivers[], enabled_set, not_enabled[], verdict}` — the shape a release pipeline
  asserts on.
- The **ENABLED SET** block is the answer to "can a commercial deployment accidentally depend on a
  restricted driver?" It aggregates `restriction_bits` over `[drivers] enabled` **and** every
  `[targets] enabled` compile driver, and states the consequence in the operator's language
  (share-alike, attribution, redistribution) rather than in bit names.
- The **NOT ENABLED** block is not decoration: it is where the report earns its place. A driver that
  is installed, forbidden and unenabled is invisible to every other view, and a named-but-unenabled
  driver is a configuration bug the operator would otherwise meet as a mid-run rejection.
- `ow doctor` runs `--posture` as one of its checks and **fails** the doctor run on exit 6, so the
  posture is not something anyone has to remember to look at.

Build-time licence policy is a *different* mechanism with a different owner and is not this report:
`tools/licences.toml` plus **G3** scans the resolved dependency graph **and** the import graph **and**
unpacked artefacts, fails rather than warns, and has `cairosvg` as its regression fixture — LGPL-3.0,
imported at `ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_package/media.py:15` and **absent
from `ppt-master/requirements.txt`**, which is the proof that manifest scanning alone is insufficient
(DR18). Three files, three jobs, no overlap: `tools/licences.toml` for what omniweave may depend on,
`driver.toml [licence.*]` for the facts, `omniweave.acks.toml` for the operator's consent (§5 X11).
The full posture, including the corpus-side questions this report does not answer, is
[security](14-security.md)'s.

### 7.5 Tombstones

A **tombstone** is its own grammar, not a driver card with holes: the loader branches on the presence
of `[tombstone]` **before** validating anything else, because a tombstone has no `entrypoint`, no
`schema_version`, no `granularity` and no `replay_class` — all non-optional on `DriverCard` — and its
`version` is a wildcard, which is not semver. Only three keys are legal in a tombstone's `[driver]`
table: `id`, `port`, `title`.

Tombstones do two jobs:

1. **DR22**: a removed or forbidden driver resolves to a **quoted reason and a named replacement**,
   never to "unknown driver". A test asserts every vetoed id has a tombstone with a non-empty reason
   and a future `review_by`, and CI **fails** a tombstone past its `review_by` date, so the refusal
   set cannot silently ossify.
2. **The known-bad-weights-licence seed set** (§5 X11): `compute_tier` returns `forbidden` for any
   card whose `[licence.code].licence_sha256` **or** `[licence.weights].licence_sha256` matches a
   shipped tombstone's. This is hash-keyed, so it **survives renaming**: a third party wrapping the
   same weights under a different driver id computes `forbidden` too. It absorbs D4's two separate
   licence-denylist mechanisms, both of which are struck.

The lookup is a `frozenset[str]` of at most a few dozen digests, built once with the tombstones at
step 5 of `Catalog.build()`, so the hash-keyed check costs one set membership test per card and does
not grow with the roster.

The distinction that matters in practice, and it is the reason `restricted` and `forbidden` are
different tiers rather than one:

| licence shape | tier | ack path | example |
|---|---|---|---|
| AGPL-3.0 / SSPL / GPL-3.0 code | `restricted` | **yes** — an operator may knowingly accept copyleft for an internal deployment | PyMuPDF, mineru |
| a competitor bar with no revenue threshold, plus output share-alike | `forbidden` | **no** — there is no configuration in which omniweave may run it | marker / surya / lift weights |
| a territorial exclusion covering the operator's jurisdiction | `restricted`, refused locally | jurisdiction-dependent | HunyuanOCR |
| "all rights reserved" with no tier permitting redistribution | `forbidden` | no | jcodemunch-mcp |

That is why `parse.pdf.pymupdf` is **not** tombstoned — an operator running internally may
legitimately accept AGPL, and tombstoning it would remove a decision that is theirs to make — while
the Datalab weights are. `marker/MODEL_LICENSE:58` (Attachment A, clause 2(c)) bars use *"for any
purpose if You (your employer, or the entity you are affiliated with) provides or otherwise makes
available any product or service that competes with any product or service offered by or made
available by Licensor"*, **with no revenue threshold and no research carve-out** — 2(a) and 2(b) at
`:56-57` both carve out personal and research use below $5,000,000 in revenue or funding; 2(c) does
not. Datalab sells document parsing. So does omniweave. There is no ack that fixes that, and lift's
README says it outright: *"cannot be used competitively with our API"* (`lift/README.md:232`).

The six tombstones shipped at release 1 are in §10.4.

## 8. The conformance kit

### 8.1 The thesis: the card is the test plan

`omniweave-conform` is a separate distribution whose whole claim is that **the descriptor is
mechanically checked in both directions**: every declared capability asserted *present* and every
undeclared one asserted *absent*. The bar is **the honesty of the descriptor, not the excellence of
the driver** — declaring `spatial = "none"` is not a failure; declaring `line_bbox` and returning
none is.

Every descriptor in the mined collection that is not mechanically checked has already rotted:
DataFlow's 171 hand-written `get_desc(lang)` strings with nothing comparing them to
`inspect.signature(run)`; LEANN's `llms.txt` declaring 2 tools against a server shipping 4;
open-slide's `skills-lock.json` hashing only `SKILL.md`. That is three independent projects and the
same failure, which is why the kit is a distribution and not a checklist.

`omniweave-conform` also carries the driver **testkit** (~120 property tests, which the `read_back`
drivers run unchanged), the eval harness, the reducers, the Cassette codec, the calibrator and the
scoreboard generator. There is no separate testkit distribution.

### 8.2 The twelve suites

| suite | mandatory | what it asserts | the defect it catches |
|---|---|---|---|
| `card` | yes | the card parses; every required key is present and in domain; `attestation` is top-level; `[limits]` ≤ `HOST_MAX`; every §4.5 cap holds; every benchmark row has `n ≥ 30`, `ci95`, `witness` and a complete ten-field `measured_on` | a card with seven `MeasuredOn` fields and a blank cell |
| `purity` | yes | discovery under an **import tracer**: fails if any module of the driver's distribution was imported while building the catalog | docling's load-then-gate order |
| `contract` | yes | `PORT` and `SCHEMA_VERSION` match the card; every protocol method exists with the declared signature; `__init__` loads no model and opens no file; `DriverError` is raised, never `None` returned, never an empty success | a driver returning `None` on failure and blaming the next stage *(Build note, D939: the suite also decodes every fixture that parses to blocks through the host's own `store.fragment` into a real `DocSink` (`omniweave_conform.stored.into_store`, which `labels.candidate` now shares). A fragment the host refuses or quarantines fails `outcome:stored`, with the host's reason. The conformance template had passed all eleven suites with a page box, a byte origin the decoder did not read and a bare codec, and `ow add` refused it for each (D935, D938): a driver's conformance is now also a claim that the host will hold its documents.)* |
| `capability` | yes | **derived from the card in both directions**: `text_span = false` asserts text spans are *absent*; `origin_span = "exact"` re-reads the retained part on the branch the driver's `os_kind` selects | an aspirational card |
| `idempotence` | yes | the same input twice through one process yields byte-identical output, and again through two processes | hidden per-instance state |
| `determinism` | yes | `replay_class` is honoured: `byte_exact` across processes with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd; `seeded` across seeds; `unpinnable` merely declared | a determinism boolean that cannot express continuous batching |
| `limits` | yes | every driver-enforced `[limits]` value refuses at the read boundary with `take(N+1)`-then-check, and every host-enforced one refuses before `INVOKE`; a breach is `RESOURCE_LIMIT{limit}` naming the knob | a max-file-size set to `sys.maxsize`, with the page check *after* the parse |
| `sandbox` | yes | a write outside `tmp` fails; with `needs_network = false` the run is socket-blocked and any egress attempt fails the suite | marker's `--use_llm` shipping page images to a hosted model |
| `cost` | yes | `class = "free"` makes no egress and no GPU call; `[cost.model] shape` is consistent with the measured curve; `max_retries = 0` is honoured | a "free" driver that phones home |
| `licence` | yes | the **resolved dependency graph and the import graph** are both scanned; a violation **fails**, never warns | `cairosvg`, undeclared and LGPL-3.0 |
| `fuzz` | yes | a corpus of malformed inputs: **a crash is allowed, a hang is not**; ships a deliberate segfault fixture and asserts the run completes | in-process death taking the run with it |
| `quality` | **no** | D10's benchmark harness; run by `ow conform --bench` | an unfalsifiable accuracy claim |

**The mandatory tier runs in under five minutes on a laptop**, enforced as a CI timing assertion,
because a skipped gate is not a gate. `omniweave-conform` also ships the reference target
`compile.text.owtext`, so a `compile` author has a working example to diff against. *(Build note, D879: the `licence` suite reads its spellings from `tools/licences.toml`'s `[normalise]`, the table G3 reads, instead of an `ALIASES` copy in code. The copy had drifted: `uharfbuzz` declares `Apache License 2.0`, which G3 reads as `Apache-2.0` and the kit refused. The kit's two extra spellings, `Apache-2` and `The Unlicense`, moved into the table. Run over `compile.pptx.native`'s reader with the compiled golden as its fixture, the mandatory tier now fails on Pillow's MIT-CMU alone, which is G3's open policy question. The docx reader passes all eleven.)* *(Build note, D889: `contract` now compares a `compile/1` driver with `CompileV1`, which D749 landed in `omniweave_core.out.compile`; all four compile cards pass it. Every compile card declares `[cost.model]` (`free`, `linear_per_part` over `plan.units`; pptx's `per_part` is 12-performance.md B37's 45 ms). `cost` still fails a compile card for want of a run to price, and `capability`, `idempotence`, `determinism`, `sandbox` and `fuzz` are `unknown`: the kit has no `compile/1` harness yet, so no compile card can be attested, which is half of D576.)* *(Build note, D890: the kit has a `compile/1` harness, `omniweave_conform.compile_harness`, which compiles a compile card's golden (its `--fixtures`, a directory holding `il/`) through the target suite's `compile_golden`. `idempotence` and `determinism` now run over it and compare `part_digest`, the class 09 section 6 makes every target promise; bytes are reported, never promised. `tools/ow_conform.py --config KEY=VALUE` hands a driver's `[config]` to the parent and every child, because pptx's golden needs `font_dir`. `capability`, `sandbox` and `fuzz` remain `unknown` for a compile card, and `cost` fails for want of a priced run.)* *(Build note, D891: `sandbox` runs over a compile card's golden. `compile_golden` takes a `guard`, entered around the driver's own `lower()` and `postflight()` and nothing the kit does between them, rooted at the driver's `io.tmpdir`; a write beside it, inside the kit's scratch, is still outside tmp. pptx, docx and owtext write nothing outside tmp and open no socket.)* *(Build note, D892: `fuzz` runs over a compile card: every mutation of every file under its golden's `il/` through `carrier()`, and of the golden's compiled artefact through `postflight()`. A compile driver's typed refusals are `DriverError`, an `OwError` (09's `OW_TARGET_*` codes) or `CarrierParseError`, the carrier's declared refusal. pptx, docx and owtext refuse all 28 inputs by type with no hang, which leaves `capability` `unknown` and `cost` failing.)* *(Build note, D893: `cost` prices a compile card over one compile of its golden: sockets and GPU-runtime imports are counted across it, and the one `(plan units, ms)` point is reported, since a line needs three. pptx, docx and owtext pass. A compile card's mandatory tier now stops at `capability` alone, which is the target suite's laws: R3, R5 and R6 are `unknown` over a golden (R3 needs `project()`, which both shipped cards decline; R5's observed-loss clauses need the reader; R6 needs a source artefact). That is the rest of D576's compile half.)*

The `fuzz` suite's "a crash is allowed, a hang is not" asymmetry is deliberate and is the whole
reason `subproc` is affordable: the host already handles a crash as one row and it cannot handle a
hang without a deadline. anydoc is the only fuzzed parser in the collection — **12 cargo-fuzz
targets** in `anydoc/fuzz/fuzz_targets/` (`csv`, `doc`, `docx`, `epub`, `numfmt`, `odf`, `pdf`,
`ppt`, `rtf`, `xls`, `xlsb`, `xlsx`) — and its seeds are mirrored into `fuzz/seeds/`.

### 8.3 What the kit writes, and what the loader recomputes

`[cost.measured]` and `[quality]` are **kit-written; author values are rejected by the publish gate**
(DR13). `attestation` is a sha256 over the canonical card **minus** the `attestation` key itself
(§2.8), and the card loader **recomputes** it: a mismatch sets `card.attested = False`, and an
unattested driver is never auto-selected (`allow_unattested = false` is the shipped default;
`UNATTESTED` is the reject code, waived only by an explicit pin). *(Build note, D894, two user rulings of 2026-10-20 (D576): **`dist_sha256` is a sha256 over the distribution's own `RECORD` rows** (sorted `path,hash`, dropping what an installer adds: hashless rows, bytecode, `../` scripts, `.data/`, and every `.dist-info/` file but `METADATA`, `WHEEL`, `entry_points.txt` and `licenses/`), so the wheel and its install give one value (`omniweave_core.drivers.digest`); `catalog()` computes it for the release manifest's distributions alone. **The release manifest is the explicit pin that waives `UNATTESTED` for a first-party card**: `first_party` and `vendored` pass the attestation gate and D-08, and a third party's card still needs its attestation. And per section 4.2's own reading, `require_lock` refuses `unpinned` and `local` only: `first_party`, `vendored` and `pinned` satisfy it without a lock row of their own.)*

**CI runs the kit from a trusted tag, never from the PR branch** (DR23), because *a validator
supplied by the submission validates nothing* — the `pull_request_target` class of vulnerability,
stated as a review rule. This is lifted directly from `awesome-skills/REVIEWING.md:37-39`: *"Never
run scripts that come from the PR. Validate with `scripts/` from a trusted ref (`main`, or a tag you
control), not with the copy in the branch. PR content is untrusted input; a validator supplied by the
submission validates nothing."* `ow drivers verify` re-runs the kit locally against installed bytes;
a supplied report alone is never sufficient.

### 8.4 What a passing run entitles a third party to claim

**Entitled**, and generated rather than hand-written:

- the exact string `ow conform --badge` emits, which encodes `kit_version`, the twelve suite results
  and `card_sha256`;
- the sentence "passes the omniweave conformance kit `<kit_version>`, mandatory suites";
- the kit-written `[cost.measured]` block, as a measurement on the hardware its `hardware` key names;
- a listing in the community index with `witness = "self"` on any benchmark rows;
- auto-selectability under a default configuration, since the card is attested.

**Not entitled**, and each has a mechanism that enforces it:

| claim | why not | mechanism |
|---|---|---|
| "certified", "verified by omniweave", "official" | the kit measures descriptor honesty, not excellence, and attestation is not authentication | trademark policy, plus the badge string being generated |
| an accuracy or quality ranking | `witness = "self"` rows are **displayed and never ranked**, and are never read by `ow route propose` | DR24 |
| a benchmark number against a corpus digest not in the release manifest | treated as `witness = "self"` **regardless of what it declares** | DR24, at card load |
| "safe to run in-process" | `inproc` is unreachable for a third party by construction | DR9's six conjuncts |
| "licence-clean" | the tier is computed from facts the author supplied; the kit checks the graph, not the author's honesty about the text | `compute_tier` plus `ow drivers check --posture` |
| a `witness = "ci"` or `"third_party"` row | requires a run on omniweave's CI or a named third party's | the card loader downgrades anything else |
| a cost number on hardware the card does not name | `[cost.measured]` carries `hardware`, `hardware_spawn` and `timing_basis`, and all three are printed with the number | the publish gate rejects an author-written `[cost.measured]` |

That list is short on purpose. A conformance kit that entitles an author to a quality claim becomes a
marketing surface and stops being a test, which is the failure mode `[[quality.benchmark]]`'s four
required keys exist to prevent.

## 9. Worked example: publishing `parse.notebook.ipynb`

An afternoon, eight steps, real files and real commands. The card is §3's, verbatim. Steps 1-7
publish a driver; **step 8 is what makes it a route**, and a publish that stops at step 7 leaves a
conformant, attested, enabled, lockfile-pinned driver that never parses a document. Step 8b then
walks the same path for a format core has no token for, because that is the case the first eight
steps do not exercise.

### Step 1 — scaffold

```console
$ ow drivers scaffold --port parse/1 --id parse.notebook.ipynb --dir omniweave-driver-ipynb
wrote omniweave-driver-ipynb/pyproject.toml
wrote omniweave-driver-ipynb/src/omniweave_driver_ipynb/__init__.py
wrote omniweave-driver-ipynb/src/omniweave_driver_ipynb/driver.py
wrote omniweave-driver-ipynb/src/omniweave_driver_ipynb/driver.toml
wrote omniweave-driver-ipynb/tests/test_conform.py
wrote omniweave-driver-ipynb/LICENSE  NOTICE  README.md
next: fill [capability.parse] honestly, then `ow conform`
```

`ow drivers scaffold` emits a card with every capability at its **weakest** value and with
`[cost.measured]`, `[quality]` and `attestation` absent. Filling the card upward is the author's
work; the kit then refuses anything unearned.

### Step 2 — the packaging

```toml
# omniweave-driver-ipynb/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omniweave-driver-ipynb"
version = "0.1.0"
requires-python = ">=3.11"
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
dependencies = ["omniweave-ports >=1,<2"]

[project.entry-points."omniweave.drivers"]
"parse.notebook.ipynb" = "omniweave_driver_ipynb"

[dependency-groups]
dev = ["omniweave-conform ~= 0.1", "pytest ~= 9.1"]
```

Three properties a reviewer checks here and nowhere else: **one runtime dependency**, and it is
`omniweave-ports` (never `omniweave-core` — a `parse/1` driver that pins core fails G4 in the
consuming repo and cannot be a first-party driver at all); the entry-point value is a **dotted
package with no colon**; and `omniweave-conform` is a **dev** dependency, so the kit never ships in
the wheel.

### Step 3 — the driver

```python
# src/omniweave_driver_ipynb/driver.py
import json
from omniweave_ports import (ArtifactRef, DriverError, DriverMetrics, DriverResult,
                             FailureClass, FormatGuess, ProbeStatus, ProbeVerdict)

# The fifteen keys of `achieved`, exactly as the card declares them. The `capability` suite asserts
# this constant is <= the card's [capability.parse] on every key -- achieved may be lower, never
# higher -- so the wire and the card cannot drift apart.
_ACHIEVED = {
    "spatial": "none", "origin_span": "exact", "text_span": True, "marks": False,
    "reading_order": "source", "sections": "markdown_only", "tables": "none", "math": [],
    "assets": "bytes", "asset_origin": True, "notes": "none", "confidence": "none",
    "furniture": "flagged", "round_trip": "structure", "forfeits": [],
}
_KIND = {"markdown": "paragraph", "code": "code", "raw": "paragraph"}


def _outputs_text(cell) -> str:
    parts = []
    for o in cell.get("outputs", ()):
        if "text" in o:
            parts.append("".join(o["text"]))
        elif "data" in o and "text/plain" in o["data"]:
            parts.append("".join(o["data"]["text/plain"]))
    return "".join(parts)


class IpynbParser:
    PORT = "parse/1"
    SCHEMA_VERSION = 1

    @classmethod
    def probe(cls, env):
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib json only")

    def __init__(self, **config):
        self.include_outputs = bool(config.get("include_outputs", True))
        self.max_output_chars = int(config.get("max_output_chars", 4096))
        # No file opened, no model loaded, no network. The `contract` suite asserts all three.

    def sniff(self, head, hint):
        if b'"nbformat"' in head[:4096]:
            return (FormatGuess(media_type="application/x-ipynb+json", format_token="ipynb",
                                confidence=0.95, consumed_bytes=4096),)
        return ()

    def parse(self, unit, parts, io):
        # NO max_input_bytes CHECK. The host refused the unit before INVOKE (DR20); a driver that
        # re-checks a host-enforced ceiling is a second implementation of a safety limit.
        with io.blobs.open(unit.content_sha256) as fh:
            raw = fh.read()
        try:
            nb = json.loads(raw)
        except json.JSONDecodeError as e:
            raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"not JSON: {e}") from None
        cells = nb.get("cells")
        if not isinstance(cells, list):
            raise DriverError(cls=FailureClass.UNSUPPORTED_FORMAT, message="no `cells` array")

        out = [
            {"t": "doc", "format": "ipynb", "media_type": "application/x-ipynb+json",
             "page_count": 1, "achieved": _ACHIEVED},
            {"t": "part", "path": "notebook.json", "sha256": unit.content_sha256,
             "byte_len": len(raw), "retain": True},
            {"t": "page", "page": 0, "page_kind": "stream", "w_mpt": 0, "h_mpt": 0,
             "quad_origin": "topleft", "rotation": 0, "method": "native_json"},
        ]
        n = 0
        for i, cell in enumerate(cells):
            if io.cancelled():
                raise DriverError(cls=FailureClass.TIMEOUT, message="cancelled by generation")
            n += 1
            out.append({
                "t": "block", "tmp": f"c{i}", "parent": None,
                "kind": _KIND.get(cell.get("cell_type"), "paragraph"), "layer": "body",
                "text": "".join(cell.get("source", ())),
                "quote": "verbatim", "trust": "extracted", "method": "native_json",
                # THE POINT OF THIS DRIVER: a JSON pointer IS a stable node path, so INV-10's
                # `nodepath` branch re-verifies the text against the retained part.
                "os": {"k": "nodepath", "part": "notebook.json", "path": ["cells", i, "source"]},
                "quad": None, "marks": [], "payload": None})
            io.progress(done=n, total=len(cells))

            if self.include_outputs and cell.get("cell_type") == "code":
                text = _outputs_text(cell)[: self.max_output_chars]
                if text:
                    n += 1
                    out.append({
                        "t": "block", "tmp": f"o{i}", "parent": f"c{i}", "kind": "code",
                        "layer": "body", "text": text,
                        # `normalized`, NOT `verbatim`: the text is joined across output records and
                        # truncated at max_output_chars, so it is not a byte slice of the part.
                        # `origin_span` stays `exact` -- the node path is exact. Two axes, two
                        # answers, and conflating them is how a byte-exactness claim gets faked.
                        "quote": "normalized", "trust": "extracted", "method": "native_json",
                        "os": {"k": "nodepath", "part": "notebook.json",
                               "path": ["cells", i, "outputs"]},
                        "quad": None, "marks": [], "payload": None})

        out.append({"t": "end", "status": "ok", "page_stats": {"blocks": n}})
        body = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in out).encode()
        ref = ArtifactRef.of("doc_fragment", body, io)   # meters max_output_bytes for us
        return DriverResult(outcome="ok", produced=(ref,),
                            metrics=DriverMetrics(bytes_read=len(raw)))

    def is_valid_nonempty(self, ref) -> bool:
        return b'"t":"block"' in ref.head(65536)
```

Six things that file does **not** do, each because a protocol obligation forbids it: it never touches
a store, cache or ledger; it never returns `None` or an empty success; it never retries; it never
writes outside `io.tmpdir`; it never sets `confidence`, `restriction_bits` or a price; and it never
re-checks a host-enforced limit. Each absence is a suite, not a review comment.

### Step 4 — fixtures and the conformance run

```console
$ mkdir -p fixtures && cp ~/nb/*.ipynb fixtures/
$ uv run ow conform --card src/omniweave_driver_ipynb/driver.toml --fixtures fixtures/
card          pass   (43 keys, 0 unknown top-level, 0 unknown [capability.parse],
                      attestation position ok, card 3.9 KB of 64 KB)
purity        pass   (0 driver modules imported during discovery)
contract      pass   (7 assertions; __init__ opened 0 files, loaded 0 models)
capability    pass   (15 declared, 15 asserted present-or-absent; origin_span=exact re-verified
                      on 214 blocks via the `nodepath` branch; 38 output blocks correctly
                      declared quote=normalized)
idempotence   pass   (12 fixtures x 2 processes, byte-identical)
determinism   pass   (replay_class=byte_exact across PYTHONHASHSEED, TZ, LC_ALL, TMPDIR, cwd)
limits        pass   (max_input_bytes refused host-side before INVOKE; max_parts=1 honoured;
                      RESOURCE_LIMIT names the knob)
sandbox       pass   (socket-blocked; 0 writes outside tmp)
cost          pass   (class=free: 0 bytes egress, 0 gpu_ms; shape=linear_per_byte fits at r2=0.98)
licence       pass   (resolved graph 1 dist, import graph 1 module, both Apache-2.0/stdlib)
fuzz          pass   (5,000 execs, 3 crashes contained, 0 hangs)
quality       unknown (run `ow conform --bench` with a registered corpus)
wrote [cost.measured], [quality] and attestation into src/omniweave_driver_ipynb/driver.toml
attestation   sha256:f745a151…
12 suites, 11 pass, 1 unknown, 0 fail, 4m12s  -> PASS (mandatory tier)
```

If `capability` had failed on `origin_span`, the message names the fixture, the block and the two
strings that differed — because the point of a capability suite is to be *actionable*, not to be a
verdict.

### Step 5 — install, enable, run

```console
$ uv pip install -e .
$ ow drivers list --port parse/1
parse.office.anydoc      0.2.4  open  free           inproc-eligible  attested  enabled
parse.pdf.pdfium         0.1.0  open  free           subproc          attested  enabled
parse.notebook.ipynb     0.1.0  open  free           subproc          attested  NOT ENABLED
                                ^ add it to omniweave.toml [drivers] enabled  (INV-5)

$ ow drivers add omniweave-driver-ipynb --enable
omniweave.lock   + parse.notebook.ipynb 0.1.0 (card sha256:8367cd66…, dist sha256:bcae0416…)
omniweave.toml   [drivers] enabled += "parse.notebook.ipynb"
next: enabling a driver does not route to it — write the rule (step 8):
      ow drivers scaffold --policy parse.notebook.ipynb

$ ow parse notebooks/analysis.ipynb --dry-run
DECODE  decode.text-native (builtin)  ->  parse.text.builtin   terminal
        parse.notebook.ipynb  enabled, attested, locked, NOT REACHED — `ipynb` is one of core's
                              forty-eight tokens and the builtin DECODE rule claims it first
        fix: step 8's project-layer fragment, which is prepended and therefore matches first
  resolution_digest sha256:0a37c1be…
```

**That is the whole of what `--enable` buys, and it is deliberate.** `decode.text-native` names
`parse.text.builtin` with `terminal = true` for ten tokens including `ipynb`
([routing](05-ingest-and-routing.md) §4.4's shipped policy), so at the `DECODE` rung it matches before
any card is consulted and `resolve()` is never reached for this unit. Step 8 states what
`terminal = true` does and does not mean and installs the rule that pre-empts the builtin one.
**This is the resolution step 8 makes reachable**, and it is what the last two commands of the
example print:

```console
$ ow parse notebooks/analysis.ipynb --dry-run
resolve(parse/1, format=application/x-ipynb+json)
  candidates  parse.notebook.ipynb   (free, subproc, origin_span=exact)
  rejected    parse.office.anydoc    format_unsupported
              parse.pdf.pdfium       format_unsupported
              parse.page.olmocr      probe_unavailable (missing: omniweave-vision)
  resolution_digest sha256:6eeb55f7…

$ ow parse notebooks/analysis.ipynb && ow doc show d1 --limit 2
d1#1  paragraph  verbatim  extracted  native_json  "# Revenue analysis"
d1#2  code       verbatim  extracted  native_json  "import pandas as pd"
```

The editable install matters to step 5 and is the reason §4.3 makes an editable distribution
per-card stat'ed: without that rule the next `ow conform` would validate the card the cache
remembered rather than the one just edited, and the whole loop above would be a lie exactly once,
silently.

### Step 6 — publish, and what the badge says

```console
$ uv build && uv publish
$ ow conform --badge
omniweave-conform 1.0.0 · mandatory 11/11 pass · quality unknown · card sha256:8367cd66…
```

That string, and the sentence "passes the omniweave conformance kit 1.0.0, mandatory suites", are the
whole of the claim. See §8.4 for what it is not. *(Build note, D923: earned outside the checkout too. A driver project in a temp directory -- its own package, card, `pyproject.toml` and fixtures, importable only through its author's `PYTHONPATH` -- passes 11/11 through `tools/ow_conform.py`. Its code is the template's under its own names, so this proves the kit's process control, not an independent driver. It took one fix: the tool's children set `PYTHONPATH` to this repository's sources alone, so `idempotence` and `determinism` failed on a child that could not import the driver. The caller's path is now kept after the repository's.)*

### Step 7 — the maintenance obligation, in one line

Change the driver's output bytes for the same input and **bump `[driver] schema_version`**. That is
the one mistake this design cannot catch for you (§5.1), and `ow conform --diff-against v0.1.0` is
how you check before you tag.

### Step 8 — the routing fragment, and why the operator installs it

No wheel may ship a routing rule, and all six policy layers belong to someone other than the driver
author ([routing](05-ingest-and-routing.md) §4.1). Step 8 is therefore how a published driver becomes
a *route*, and it is the step the first seven do not cover:

> `terminal = true` ends rule evaluation at that rung; it does not make the named driver
> unreplaceable. For a format **inside** the 48, a third-party driver becomes reachable when the
> operator prepends a rule that pre-empts the builtin one — layers **prepend** and first match wins
> (`05` §4.1), so a `project`-layer rule naming the same `unit.format` set wins with no precedence
> arithmetic. `ow drivers scaffold` emits that fragment as publish **step 8**, and
> `ow drivers add --enable` prints the exact path it must be copied to; INV-5 keeps the operator in
> the loop, because enabling a driver and redirecting a route are two decisions and the second is the
> one that can move money.

```console
$ ow drivers scaffold --policy parse.notebook.ipynb
wrote  policy.d/50-parse-notebook-ipynb.toml   (layer: project)

# policy.d/50-parse-notebook-ipynb.toml
surface        = "route"
policy_name    = "driver:parse.notebook.ipynb"
policy_version = 1
schema         = "omniweave.policy/1"

[[rule]]
id      = "decode.notebook-ipynb"
rung    = "DECODE"
comment = "Pre-empts builtin decode.text-native for ipynb. Prepended, so first match wins."
when = { "unit.format" = { in = ["ipynb"] } }
then = { driver = "parse.notebook.ipynb", terminal = true }

$ cp policy.d/50-parse-notebook-ipynb.toml .omniweave/policy.d/
$ ow route lint && ow route explain notebooks/analysis.ipynb --rung decode
DECODE  decode.notebook-ipynb (project)  ->  parse.notebook.ipynb   terminal
        pre-empted: decode.text-native (builtin)
```

The author **writes** the fragment and the operator **copies** it: `ow drivers scaffold --policy`
emits a file into the distribution, never into `.omniweave/policy.d/`, and there is no `driver`
policy layer — [05](05-ingest-and-routing.md) §4.1 records why. A driver author who wants to
demonstrate the win without an operator's copy has a typed path already: `[[pin]]`'s `PinRejected`
names, per unit, which driver would have been selected and the reason it was not.

What the example deliberately leaves out, so an afternoon stays an afternoon: cell attachments (which
would make `assets = "bytes"` load-bearing and bring `MAX_ASSET_BYTES = 268_435_456` into play), a
`part`-granularity variant, and a `[deprecation]` table. None changes any contract above.

### Step 8b — the same walk for a format **outside** core's forty-eight

`ipynb` is already a core token, so §2.2's `format_tokens` pair is a claim to an existing token and
step 8's fragment names one every policy layer can already spell. That is the easy half, and naming
the hard half without walking it is how a linter check ends up hardcoded against core's 48 and a new
token ends up unroutable. So: `omniweave-driver-warc`, a `parse/1` driver for WARC web archives,
which core has no token for.

| # | what the author writes | what it changes |
|---|---|---|
| 1 | `[capability] formats = ["application/warc", "application/warc+gzip"]` | two media types the card serves |
| 2 | `[capability.parse] format_tokens = [{ media_type = "application/warc", token = "warc" }, { media_type = "application/warc+gzip", token = "warcgz" }]` | two **pairs**, so `format_token_for("application/warc") -> "warc"` is defined and single-valued; without the pairing the lookup is undefined and `OW-D-024` cannot be decided (§2.2) |
| 3 | `sniff()` returns `FormatGuess("application/warc", "warc", 0.9, 16)` on a `WARC/1.` head | the `capability` suite asserts each declared pair is reachable from `sniff()` |
| 4 | `detects = true` | puts the driver in ladder step 4 of [routing](05-ingest-and-routing.md) §2.1 |
| 5 | the operator adds the driver to `[drivers] enabled` | the computed format-token domain becomes **50**: core's 48 ∪ `{warc, warcgz}` (`05` §5.1) |
| 6 | the operator copies a `project`-layer `DECODE` rule naming `unit.format in ["warc", "warcgz"]` | `ow route lint` check 2 resolves both literals against the **computed** domain, not against core's 48; check 10 finds the GATE∪DECODE literal union equal to that same computed domain; check 11 finds both tokens in the driver's served token set |

Skip step 6 and the linter fails naming `omniweave-driver-warc` and the two tokens no rule spells —
which is check 10's job. Perform step 6 and the linter passes, because check 10's target is the
computed domain and not a hardcoded 48. Both halves are `05` §4.5 check 10 as written; a form of that
check comparing against core's 48 would fail step 6 **and** fail its omission, leaving `warc`
unroutable either way, which is the one outcome the contribution path exists to prevent.

## 10. The first-party driver roster

### 10.1 Drivers shipped at release 1

Twenty-three drivers across three of five Ports. `tier` is the **computed** `LicenceTier`; `trust` is
the computed `TrustTier` (§4.2); `iso` is the isolation mode the host **grants**, never merely the one
the card requests.

| driver id | Port | distribution | wraps / reimplements | code licence | tier | trust | iso | cost | status |
|---|---|---|---|---|---|---|---|---|---|
| `parse.office.anydoc` | `parse/1` | `omniweave-office` | `firecrawl-anydoc == 0.2.4`, source vendored at a recorded SHA under `vendor/anydoc/` with a written fork trigger | MIT | open | vendored | **inproc** | free | shipped |
| `parse.pdf.pdfium` | `parse/1` | `omniweave-pdf` | `pypdfium2`; page and line logic informed by `marker/builders/line.py` | Apache-2.0 / BSD-3-Clause | open | first_party | subproc | free | shipped |
| `parse.text.builtin` | `parse/1` | `omniweave-office` | stdlib only: `codecs`, `json`, `csv`, `html.parser`, `xml.etree` via `defusedxml`. Serves the ten tokens `decode.text-native` names — `html`, `xhtml`, `xml`, `md`, `txt`, `json`, `jsonl`, `ipynb`, `tsv`, `svg` — none of which anydoc's card declares | Apache-2.0 | open | first_party | subproc | free | shipped |
| `parse.page.olmocr` | `parse/1` | `omniweave-vision` | olmocr (`_collections/olmocr`) — **the only permissive high-accuracy OCR**: Apache-2.0 code *and* Apache-2.0 weights | Apache-2.0 | open | first_party | subproc | local_compute | shipped |
| `parse.pptx.native` | `parse/1` | `omniweave-target-pptx` (`back/`) | `python-pptx`; the `read_back` half of the OUT loop | MIT | open | first_party | subproc | free | shipped |
| `parse.docx.native` | `parse/1` | `omniweave-target-docx` (`back/`) | `python-docx` + `lxml` | MIT | open | first_party | subproc | free | shipped |
| `parse.deck.native` | `parse/1` | `omniweave-target-deck` (`back/`) | the deck target's `read_back`; HTML with `data-ow-el` / `data-ow-cite` | MIT | open | first_party | subproc | free | shipped (see Q1) |
| `derive.segment.spine` | `derive/1` | `omniweave-graph` | segmentation shape from `graphrag-chunking`; reads `block_sec` | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.anchor.native` | `derive/1` | `omniweave-graph` | OOXML/ODF anchor extraction; reimplemented | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.anchor.defterm` | `derive/1` | `omniweave-graph` | definition-term mining; the highest-yield free pass on legal and financial corpora | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.xref.native` | `derive/1` | `omniweave-graph` | native cross-reference fields | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.xref.pattern` | `derive/1` | `omniweave-graph` | pattern cross-references; shape from `codegraph` | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.entity.table` | `derive/1` | `omniweave-graph` | table-structured entities and claims | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.entity.gazetteer` | `derive/1` | `omniweave-graph` | gazetteer matching; ids and dedup constants vendored from `graphify` (`vendor/graphify-ids/`) | Apache-2.0 | open | first_party | subproc | free | shipped |
| `derive.entity.llm` | `derive/1` | `omniweave-llm` | extraction prompts informed by `graphrag`; untrusted-source wrapping vendored from `graphify` (`vendor/graphify-security/`) | Apache-2.0 | open | first_party | subproc | billed_api | shipped, **off by default** |
| `derive.claim.llm` | `derive/1` | `omniweave-llm` | the same | Apache-2.0 | open | first_party | subproc | billed_api | shipped, **off by default** |
| `derive.merge.llm` | `derive/1` | `omniweave-llm` | the resolution funnel's `[75, 92)` LLM band; `granularity = "corpus"` | Apache-2.0 | open | first_party | subproc | billed_api | **at risk** (Q7) |
| `derive.report.llm` | `derive/1` | `omniweave-llm` | community reports, shape from `graphrag`; `granularity = "corpus"` | Apache-2.0 | open | first_party | subproc | billed_api | shipped, **off by default** |
| `compile.pptx.native` | `compile/1` | `omniweave-target-pptx` | `python-pptx`, `XlsxWriter`, `skia-pathops`, `uharfbuzz`, `Pillow`; DrawingML mapping informed by `ppt-master` **with the watermark remover, `curl_cffi` and `edge-tts` excised** | MIT | open | first_party | subproc | free | shipped, flagship |
| `compile.docx.native` | `compile/1` | `omniweave-target-docx` | `python-docx` + `lxml`; the honest test that OUT is not one implementation wearing an interface | MIT | open | first_party | subproc | free | shipped |
| `compile.deck.native` | `compile/1` | `omniweave-target-deck` | a Toolchain manifest over `toolchains/deck/`, derived from `open-slide` | MIT | open | first_party | subproc + S2 | free | shipped, `bake = "unavailable"` |
| `compile.video.native` | `compile/1` | `omniweave-target-video` | a manifest over `toolchains/video/`, derived from `hyperframes`; `ffmpeg = "system"`, **never bundled** | Apache-2.0 | open | first_party | subproc + S2 | free | **`implemented = false`** |
| `compile.text.owtext` | `compile/1` | `omniweave-conform` | the reference target a third-party author diffs against | Apache-2.0 | open | first_party | subproc | free | shipped |

Five notes the table cannot carry:

- **"Off by default" is `[drivers.cost] allow_classes = ["free", "local_compute"]`, not a missing
  driver.** The four `omniweave-llm` passes are shipped, attested and absent from the default
  `[drivers] enabled` and from `[graph.passes] enable`; enabling one is two config edits and an
  operator's decision about money. `auto_refresh_classes = ["free"]` additionally guarantees a
  watcher may never auto-run billed work.
- **`derive.merge.llm` and `derive.report.llm` are `granularity = "corpus"` and `billed_api`**, so
  §2.5's rule binds them: each declares `witness_set` in `[capability] produces` and emits one, or it
  is `NO_WITNESS_SET` at resolve time. They declare one.
- **A Target is implemented by exactly two Drivers**, one `compile/1` and one `parse/1`, which is why
  `parse.deck.native` is in the table. `omniweave-target-video` is the exception and says so on its
  own card: `[compile] implemented = false` and no `read_back`, because there is nothing to read
  back from an unimplemented target.
- **`compile.video.native`'s `ffmpeg = "system"` is a licence decision, not a packaging
  preference.** `hyperframes/packages/aws-lambda/package.json:76` bundles `ffmpeg-static ^5.2.0`
  (~80 MB) whose `libx264` build is **GPL-2.0-or-later**, inside a deploy artefact shipping no ffmpeg
  NOTICE, and H.264/AAC additionally carry Via LA / Via Licensing patent pools.
  `[targets.video] codec = "vp9"` is the default and `h264` is an operator-owned opt-in, never a
  fallback.
- **No driver in this roster declares `Capabilities.sections = "typed_levels"`, and `Kind.SECTION`
  is kept anyway (ADR-3 D6).** The roster above is the member's whole release-1 write set, so it has
  no producer. `Kind` is the framework's closed **read** vocabulary, not the shipped roster's write
  set: a third-party EPUB or DITA driver may lawfully declare `typed_levels`, and withdrawing the
  member would leave that driver unable to express its output while retiring an `enum_val.ord`
  forever, because ordinals are append-only ([document model](03-document-model.md) §2.1). The
  vacancy is therefore stated here rather than inferred, and `Kind.SECTION` is excluded **by name**
  from `V01-17`'s scope ([vision](00-vision.md) §9.1) so that gate does not read a kept
  read-vocabulary member as an unserved format class.

**The shipped office card's `[capability] formats`, printed here because it is not documentation.**
`resolve()` filters on `format in capability.formats` before anything else, so this list is the input
to `format_token_for`, to `ow route lint` **check 11** and to `V01-17`. It is **twelve media types,
one per token `decode.office-native` routes** ([routing](05-ingest-and-routing.md) §4.4, the sole home
of the token list); the card and the rule are images of each other under `format_token_for` and check
11 asserts the equality, so neither can drift alone (ADR-8 D8.2).

```toml
# omniweave-office — parse.office.anydoc's driver.toml. ONE MEDIA TYPE PER LINE.
[capability]
formats = ["application/msword",                                                        # doc
           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",   # docx
           "application/vnd.ms-powerpoint",                                             # ppt
           "application/vnd.openxmlformats-officedocument.presentationml.presentation", # pptx
           "application/vnd.ms-excel",                                                  # xls
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",         # xlsx
           "application/vnd.oasis.opendocument.text",                                   # odt
           "application/vnd.oasis.opendocument.spreadsheet",                            # ods
           "application/vnd.oasis.opendocument.presentation",                           # odp
           "application/rtf", "application/epub+zip", "text/csv"]                       # rtf epub csv
```

`application/pdf` is **excluded** although anydoc decodes it: `parse.pdf.pdfium` owns the PDF path and
`decode.office-native`'s own comment reads "minus pdf". The nine further extensions anydoc supports
(`docm`, `pptm`, `ppsx`, `ppsm`, `pps`, `pot`, `xlsm`, `xlsb`, and the `.doc` legacy alias's second
media type) are **out** until a fixture class exists for them; adding one is a single change to this
list, to `decode.office-native` and to core's forty-eight-token table **together**, because a card
token no `[[rule]]` names fails check 10 from the other direction. `V01-17` will not flag their
absence — they are not format classes in [vision](00-vision.md) §2.1 — so the trigger is a user report
or `12#P-Q9`'s re-measurement.

### 10.2 Not drivers, and where they actually live

Named here because a reader scanning the roster will look for them:

| thing | why it is not a Driver | where it is |
|---|---|---|
| the filesystem walk | it is the enumerator, not a routed implementation | `omniweave/run/discover.py`; `unit.connector` defaults to `'fs'` |
| `op.identify`, `op.converge`, `op.lexicon`, `op.resolve`, `op.cluster` | core-only Operators; `evaluate()` never runs for them, so their `work` rows carry NULL `decision_id`, `driver` and `dispatch_key` | `omniweave/`, `omniweave/graph/` |
| the two normalisers and the taint/trust clamp | a `GraphSink` and a migration-generated trigger both need them | `omniweave_core.ident`, `omniweave_core.model.taint` |
| the segmenter's spine source | one computation, two shapes | `block_sec`, read by `derive.segment.spine` |
| the format-detection chain | `sniff()` is a driver method; the chain that ranks its answers is core code | [ingest and routing](05-ingest-and-routing.md) |
| the `sqlite` store, an ANN index | Backends, selected by name in config | `omniweave_core.store`, `omniweave.backends` |
| a vLLM or Ollama engine | a Service, named and never routed | `omniweave_core.modelserver` (S3) |
| `.owdoc` / Markdown / JSON / text / HTML output | core serialization, not an extension | `omniweave_core.model.serialize()` |

### 10.3 The two empty Ports, stated rather than implied

**`acquire/1` and `embed/1` ship with zero first-party drivers at release 1.** Both Ports, both
protocols, both capability vocabularies and both `resolve()` paths exist and are conformance-tested
against the kit's reference implementations; neither has a shipped driver.

- **`acquire/1`**: the fs roster is built by `omniweave/run/discover.py` and `unit.connector` defaults
  to `'fs'`, so the common case needs no driver. A URL connector, a SharePoint connector or an IMAP
  connector is the first thing an out-of-tree author should build, and markitdown is the map of what
  is worth building: nothing else in the collection converts Outlook `.msg`, RSS, Bing SERPs or
  Wikipedia with structure-aware extraction.
- **`embed/1`**: `[retrieval] vectors = "off"` is the **shipped default**, so most first runs get four
  retrieval channels and a verdict that says `semantic: off`. That is a visible product limitation and
  the correct one; the alternative is a five-second query or numpy in core. `embed.text.bge_m3` in the
  L4 DDL comment and in §2.4's example is illustrative, not shipped.

Stating this in the roster rather than leaving it to inference matters because a plan document that
lists five Ports and twenty-three drivers without saying which Ports are empty invites a downstream
author to assume an embedder exists.

### 10.4 Tombstones shipped at release 1

| tombstoned id | replaced_by | tier | the clause |
|---|---|---|---|
| `parse.page.surya` | `parse.page.olmocr` | forbidden | `surya/MODEL_LICENSE`, md5 `e1f69b64dee2f1641a9b1ab12adf24d6`: Attachment A clause 2(c) at `:58` is a competitor bar with **no** revenue threshold, where 2(a)/(b) at `:56-57` both carve out research and sub-$5M use; clause 8 at `:39` licenses the Output; clause 9 at `:41` reserves a remote kill switch |
| `parse.page.marker` | `parse.page.olmocr` | forbidden | the **byte-identical** file — `md5sum marker/MODEL_LICENSE surya/MODEL_LICENSE lift/MODEL_LICENSE` returns one digest three times |
| `parse.fields.lift` | *none* | forbidden | the same file, plus `lift/README.md:232` — "free for research, personal use, and startups under $5M funding/revenue, **cannot be used competitively with our API**" |
| `parse.page.hunyuan` | `parse.page.olmocr` | forbidden | `HunyuanOCR/License.txt:3,17,31,35` — `:3` and `:17` put the EU, UK and South Korea **outside the licensed Territory**; `:35` extends that to the Output ("You must not use … Output … outside the Territory"); `:31` adds a 100-million-MAU gate; the AUP bars insurance, credit, health and employment use |
| `derive.code.jcodemunch` | *none* | forbidden | `jcodemunch-mcp/LICENSE:29-33,82-84` — three paid tiers topping out at $1,999 for org-wide **internal** deployment, none licensing embedding or redistribution, and clause (c) forbids publishing any derivative "to any public package registry, index, marketplace, or app store". There is no price at which omniweave may ship it |
| `parse.doc.omniparse` | `parse.office.anydoc` | forbidden | `omniparse/LICENSE:1-2` is a GPL-3.0 while `omniparse/pyproject.toml:6` says `license = "Apache"` — a self-contradicting licence is itself a blocker; and it pulls `marker-pdf`, `surya-ocr` and `texify`, so it is triple-encumbered by the rows above |

Every tombstone carries a `review_by` date and **CI fails a tombstone past it**, so the refusal set is
re-read rather than inherited. The three Datalab tombstones additionally seed the known-bad weights
hash set, which is why a third party wrapping those weights under **any** id computes `forbidden`
(§7.5).

Two repos are deliberately **not** tombstoned, because the objection is supply chain rather than
licence and a tombstone is a licence instrument: Unlimited-OCR (MIT code, weights not in tree,
install instruction is a **12.4 MB unsigned prebuilt sglang wheel from a dev commit**) and Ollama-OCR
(MIT, abandoned, unpinned, AGPL PyMuPDF transitively). Neither was ever shipped, so there is nothing
to retire; both are refused by `require_lock`, by G3, and by `[licence] allow_tiers` when their
transitive AGPL surfaces.

### 10.5 Out of tree, on purpose

`omniweave-driver-leiden` (the escape above `MAX_CLUSTER_EDGES = 8_000_000`, pending a licence read of
`graspologic-native`), `omniweave-driver-code` — three drivers, and the list is exhaustive:
`parse.code.text` (stdlib-only `parse/1`, and the one that contributes the source-language
`format_tokens` pairs, without which a `.py` file resolves to `txt`), `derive.code.treesitter` and
`derive.code.manifest` ([structure extraction](06-structure-extraction.md) §3.9 specifies all three;
it is `derive.code.treesitter` that is why the distribution is **not** in the shipped pass ladder — a
pass in the ladder whose distribution does not exist is a promise nothing keeps) — and the ANN
`VectorBackend`. Naming an escape that does not exist is worse than naming none,
which is why each of the three carries an open charter question.

## 11. What breaks, at scale and under concurrency

Every mechanism above has a scale limit, a hostile-input answer, a partial-failure answer and a
concurrency answer. They are collected here so a reviewer can check them in one pass rather than
hunting, and so nothing in this document rests on an unexamined "it just works".

| mechanism | at scale | on hostile input | on partial failure | under concurrency |
|---|---|---|---|---|
| `Catalog.build()` | 0.4 ms per additional driver cold, 0.06 ms warm; 250 ms hard ceiling with `Degradation(kind="discovery_slow")` above it (§4.4) | §4.5's seven caps, each `CARD_INVALID` naming the cap | one broken card is `CARD_INVALID` plus `Degradation(kind="driver_unavailable")`; the catalog still builds | one catalog per process per run; `driver_card_cache` writes are idempotent per `(prefix, dist, version, path)` and last-writer-wins on equal content |
| the card cache validity key | 1.01 ms for 328 distributions, so it is re-checked at every run start | n/a — it stats `dist-info`, not driver-supplied paths | a `stat` failure invalidates that row only | two processes may both recompute and both write; the values are equal by construction |
| an editable install | one extra `stat` per editable distribution | n/a | n/a | the per-card `(mtime_ns, size)` check catches an edit made between two runs of the same process |
| the probe cache | one worker spawn (200–800 ms) per `(id, version, card_sha256, env_digest)` per machine, once | `probe()` runs in a worker under `probe_timeout_ms = 2000`; a hung probe is killed and cached as `unavailable` for `probe_ttl_s = 600` | an `unavailable` verdict prunes the plan with a named `missing[]`, never an `ImportError` (DR21) | `os.replace` from a same-directory `.tmp`, so a torn read is impossible and the loser's write is byte-equal |
| `resolve()` | memoised; `RESOLVE_MEMO_MAX = 512` LRU entries on the `Catalog`, ~1 MB ceiling | pure, so there is no input it can be made to execute | a zero-candidate `Resolution` **is** the error message; never a raise | pure and memo-safe; two threads racing the memo compute the same value |
| the `subproc` worker pool | `max_workers = { free = 4, local_compute = 4, billed_api = 8 }` processes; `max_inflight` counts units separately (§5 X18) | §6.5's bounded reader, depth cap, frame queue and blob metering | one crash is one `FAILED_PERMANENT{DRIVER_CRASHED}` row; 3 in 60 s quarantines the driver for the run | one worker per `(driver_id, config_digest)`; `ow doctor --runtime` refuses above 0.8× physical RAM |
| the memory watchdog | RSS sampled at 250 ms, the cadence the supervisor already wakes at | a runaway allocation hits `RLIMIT_AS` (Linux), `RLIMIT_DATA` (macOS) or a job object (Windows) | the shortfall is recorded in `isolation_granted`, never claimed (DR10) | per-process limits, so workers cannot interfere; the sampler holds no lock |
| cancellation | by generation, not by signal | a driver ignoring `cancelled()` still meets `wall_ms_hard` | a superseded result **writes nothing** — the commit predicate carries `claimed_gen` | the generation is a monotonic integer, so a late result from a previous generation is discarded rather than merged |
| the tombstone hash set | a `frozenset[str]` of a few dozen digests, one membership test per card | hash-keyed, so it survives a rename | a tombstone past `review_by` fails CI, not the run | immutable after `Catalog.build()` |
| `restriction_bits` | one integer per row, `NOT NULL`, with partial indexes | a driver cannot set it (INV-7); the runner does, from the card | the `compile` host refuses and names the offending cites and asset ids | write-once per row at insert |
| the ack set | one file, loaded into `Policy` at startup | two rows for one `(driver, which)` is a hard error at load | a stale ack is `LICENCE_ACK_STALE` with the hash diff printed | read-only during a run; `policy_digest` pins it |

Two limits this document does **not** own and states as dependencies: the dispatch key, the batch
adapter and the `driver_observation` table are [the runtime](08-runtime.md)'s, and the
`driver_card_cache` DDL is too.

## 12. Where each driver invariant is enforced

DR1–DR24 are stated in the charter and are not restated. What belongs here is the map from invariant
to the file a reviewer opens, so a PR that weakens one is caught by name.

| DR | primary enforcement site |
|---|---|
| DR1, DR2 | `omniweave_core/discovery.py`; `tools/semgrep/omniweave.yaml`; conform `purity`; G11 |
| DR3 | `omniweave_core/registry.py` (`DuplicateDriver`); `resolve()`'s `ID_COLLISION_UNQUALIFIED`; `[drivers.resolve]` |
| DR4, DR5, DR6 | `omniweave_core/drivers/resolve.py`; a 100× catalog-shuffle property test; the `len(candidates) + len(rejected) == len(considered)` test |
| DR7, DR8 | `omniweave_ports/types.py` (`DriverIO` frozen, no such field); conform `sandbox`; `host/subproc.py`'s `HELLO` builder |
| DR9 | `omniweave_core/drivers/policy.py` — the six conjuncts, in one function, with one test per conjunct |
| DR10 | `host/subproc.py`'s `isolation_granted` echo; a test on a platform lacking net namespaces |
| DR11 | `omniweave/run/dispatch.py` (crash quarantine); conform `fuzz`'s deliberate segfault fixture |
| DR12 | `omniweave_conform/suites/capability.py` — assertions **derived** from the card, both directions |
| DR13 | the publish gate in `omniweave_conform/publish.py`; `ow drivers check --estimates` |
| DR14, DR24 | `omniweave_core/drivers/card.py` (`MeasuredOn` frozen, no defaults); the scoreboard's `standing` column |
| DR15, DR16 | `omniweave_core/drivers/licence.py`; the mutated-licence `LICENCE_ACK_STALE` test; `ow drivers check --posture` |
| DR17 | `NOT NULL restriction_bits` on every carrier; the `compile` host's refusal; a parse → derive → compile test |
| DR18 | conform `licence`; G3; `cairosvg` as the regression fixture |
| DR19 | `tools/semgrep/omniweave.yaml` bans `import_module` and `__import__` outside `host/`; §2.7's config subset has no import-path keyword |
| DR20 | `omniweave_core/limits.py`; conform `limits` (`take(N+1)`-then-check); §2.5's enforcement split |
| DR21 | `omniweave_core/probe.py`; §4.7's cache; `sys.exit` banned in library code by G8 |
| DR22 | `omniweave_core/drivers/tombstones/`; the `review_by` CI check |
| DR23 | `.github/workflows/ci.yml` checks the kit out at a tag |

## Open questions

**Q1 — the shipped `[drivers] enabled` list could not satisfy `[targets] enabled`, and
`parse.deck.native` had no distribution row. CLOSED.** Three linked charter inconsistencies, all in
the compile direction. (a) §5 X5 rules that `[targets] enabled` and `[drivers] enabled` both apply and
neither bypasses the other, and INV-5 makes `[drivers] enabled` the only activation gate with
`ow doctor` **failing** on a named-but-unenabled driver — yet the charter's `omniweave.toml` has
`[targets] enabled = ["pptx"]` and a `[drivers] enabled` list of ten ids containing neither
`compile.pptx.native` nor `parse.pptx.native`, so as printed the shipped configuration fails its own
doctor check. (b) §D8's target matrix gives the deck target `read_back = parse.deck.native` and the
lock states a Target is implemented by exactly two Drivers, while §D1's repository layout row for
`omniweave-target-deck` lists only `compile.deck.native`. **Resolved**: ADR-3 D1 takes
`[drivers] enabled` from ten ids to **thirteen** — adding `parse.text.builtin`, `compile.pptx.native`
and `parse.pptx.native` — and §D1's `omniweave-target-deck` row gains `parse.deck.native`, which is
why §10.1 lists it as shipped. The thirteen are exactly the set the shipped routing policy is linted
against ([routing](05-ingest-and-routing.md) §4.4; `ow route lint` check 6, `OW-P-006`), and ADR-3 D2
gives `ow doctor`'s activation check a stated scope plus `expect_unavailable = true` for the one
deliberate absence, so `ow doctor` on a fresh install exits 0. The ten-id form survives only in the
immutable charter; erratum pending on `:505-512` (`E36`).

**Q2 — `resolve()`'s memo key under-keys four `Requirement` fields. CLOSED.** The charter's six-tuple
omitted `input_kind`, `requires_produces`, `granularity` and `pinned`, so two requirements differing
only in `granularity` collided and the second got the first's answer, silently. **Resolved**: §4.8
replaces the tuple with `(requirement_digest, policy_digest, catalog_digest)`, where
`requirement_digest` is derived from `dataclasses.fields(Requirement)` and therefore cannot go stale
the way the tuple did. One `sha256` per `Requirement` construction, and the soundness condition §4.8
used to state — that at release 1 every caller holds all four constant per `(port, lane)` — is struck
rather than weakened. Charter erratum pending on `:2170-2172`.

**Q3 — fourteen `omniweave_ports` names are used by the charter and absent from the terminology lock.**
Sixteen names appear in §D3's concrete shapes or are required by them, and this document names all
sixteen: `Candidate`, `Catalog`, `DriverHandle`, `ArtifactRef`, `BlobStore`, `ProbeEnv`,
`FormatGuess`, `StreamHint`, `UnitRef`, `PartSelector`, `DeriveScope`, `TextBatch`, `Locator`,
`LicenceFacts`, `EmbedManifest` and `ServiceHandle`. **Two of the sixteen are already locked** —
`FormatGuess` ([terminology](_notes/terminology.md) §2) and `StreamHint` (same) each carry a §2 row —
so the missing count is **fourteen**, not sixteen. The fourteen fail the lock's own bidirectional
check (G27c) the moment a plan document names them. §1.3 gives each a shape so the rows can be
written mechanically; ten of the fourteen are the §1.3 types, and the remaining four are `Candidate`,
`Catalog`, `DriverHandle` and `LicenceFacts`. They need lock rows in the same change that merges
this document. This document adds no *new* concept for any of them: `ServiceHandle` in particular is
one concept needing one row — the ports Protocol of §1.3 and its sole implementation in
`omniweave_core.modelserver`
([the runtime](08-runtime.md) §3.2), which 08 already carries as a missing-row defect from the runtime
side.

**Q4 — `omniweave-vision`'s `derive.*.vlm` drivers have no ladder entry, no distribution row and no
enabled entry. CLOSED.** §D1's repository layout gives `omniweave-vision` the row
`parse.page.olmocr · derive.*.vlm`, while §D7's shipped pass ladder enumerates all fourteen passes
with their distributions and contains **no `.vlm` pass at all**, and `[drivers] enabled` names none.
**Resolved**: ADR-8 D8.3 rules `derive.*.vlm` **out of the release-1 ladder** and
[structure extraction](06-structure-extraction.md) §3.9 records the absence, so §D1's layout row
reads `parse.page.olmocr` only and §10.1's one-driver roster for `omniweave-vision` is right as
printed rather than merely charter-following. A VLM figure and chart pass is named out of tree, the
way `derive.code.treesitter` is, until an ADR adds it — with a `pass_id`, a rank and phase, a lane, a
distribution row and an entry in `[drivers] enabled` in that ADR and not before. Charter erratum
pending on `:345`, repeated at `:8230-8231`.

**Q5 — `measured_on` named two different types on one card. CLOSED.** `[cost.measured].measured_on`
was a free-text hardware string (`"x86_64-linux 8c/16GiB · min-of-5 warm · in-process"`) while
`[[quality.benchmark]].measured_on` is the frozen ten-field `MeasuredOn` — one name for two types in
one file, exactly the class of collision §5 X14, X17, X20 and X38 exist to prevent, and a loader
reading the wrong one got a `str` where it expected a record. **Resolved**: §3's card renames the
cost block's keys to `hardware` and `hardware_spawn` (`timing_basis` already carries the
in-process-versus-spawn distinction the `_spawn` suffix duplicated, and `MeasuredOn`'s own tenth
field is named `hardware`), leaving `measured_on` on a card always a `MeasuredOn`. A `card_schema`
change under §5.2 — free while `card_schema = 1` is unreleased, a migration after. `hardware` stays
a **label, not a machine identity**: it is compared only against the same card's own history, and the
day `ow conform` ranks a cost number across cards it must become a structured record. Charter
erratum pending on `:1850-1851`.

**Q6 — should the cache key include a lockfile digest?** Charter F26, and it lands directly on §5.1:
a pdfium or tokenizer bump changes output with no change to any operator's source. What closes it:
measured output drift across one pdfium minor over a 500-document fixture. Pre-committed fallback: if
drift is nil, per-driver `[deps] pins` digests suffice; including the lockfile is *correct* and
invalidates the whole free tier on every unrelated dependency bump.

**Q7 — does `derive.merge.llm` survive?** Charter F39. It ships in the ladder and in §10.1 marked *at
risk*, while D7's own pre-committed answer was to delete it — a billed pass sitting on top of a free
nine-guard funnel. What closes it: precision and recall of the `[75, 92)` band against the guards
alone on the human-labelled resolution audit. If it goes, §10.1 loses a row and the ladder loses a
pass; nothing else in this document changes.

**Q8 — two `drivers.*` config keys are missing from `tools/config_axes.toml`.** G18 asserts that the
union of the two key lists covers every key in `omniweave.toml.example` **exactly** — neither over
nor under, one matching pattern per key. The list enumerates thirteen `drivers.*` keys and contains
neither `drivers.*.config` (which the charter's own `omniweave.toml` uses:
`[drivers."parse.pdf.pdfium"] config = { dpi = 192 }`) nor `drivers.resolve` (which DR3 requires for
a duplicate-id disambiguation). As printed, G18 fails on the shipped example. What closes it: adding
`"drivers.*.config"` and `"drivers.resolve.*"` to the key list. Recorded here because §2.7 and §4.5
depend on both keys existing.

**Q9 — hard-error-on-unknown-key across a language boundary.** Charter F41. A Toolchain's `ready`
frame is produced by TypeScript reading the same card, so an unknown `[compile]` key is a
cross-language forward-compatibility question the Python side cannot answer alone. The same question
now applies to `[acquire]`, `[derive]` and `[embed]` (E1) the day a non-Python `exec` driver (E7)
reads its own card. What closes it: add one unknown `[compile]` key to the deck target's card and
observe whether `target-runtime.ts` refuses, ignores or crashes.

**Q10 — is the 250 ms discovery hard ceiling the right disposition?** E4 makes crossing it a
`Degradation`, not a failure, on the ground that a user with 900 installed distributions should get a
report rather than a refusal. What closes it: the distribution-count distribution across the first two
releases' `ow doctor` reports. If the p99 environment sits above 250 ms, the ceiling is wrong and the
fix is a persistent catalog snapshot in `$OMNIWEAVE_HOME` keyed on the 1.01 ms validity key — which is
a new file and therefore a charter amendment, not a knob.

**Q11 — does per-driver process isolation need a second reason to exist?** Charter F25. The
pathological-XLSX failure argues for an RSS-capped worker; one reason is a special case, two is a
mechanism. What closes it: a second driver needing isolation for a **different** reason (a CUDA OOM, a
native crash). Until then the answer stays `subproc` plus `memory_mb` plus a refusal, and §6.4's
per-OS table is the whole of the mechanism.

**Q12 — `requires_credential` had no producer, and `commercial` had no route.** `compute_tier` reads
it and §D3's `[licence.code]` fact list does not contain it, so the `commercial` tier was unreachable.
Resolved as **E10** (a `[licence.code]` fact) because the ack is bound to the licence text's hash and
an input outside that hash would make the ack unsound. Recorded because it is a charter gap rather
than a charter decision, and because release 1 ships **no** `commercial`-tier driver, so the tier is
specified and untested. What closes it: one synthetic `commercial` card in the licence unit tests,
which is cheap and should land with `compute_tier`.

**Q13 — `sniff()` cannot identify a third-party format that is only identifiable from a trailer.**
§1.3 states the limit: the sniffer sees 8,192 bytes of `head`, may not advance the stream, and
`FormatGuess.consumed_bytes` reports rather than requests. Core's own trailer-identified formats
(`zip`, `gz`, `tar`, `sevenz`, `rar`, `xz`) are covered by the host's magic table and the
container-identity step, so the asymmetry falls entirely on third parties. **Flagged, not resolved**
— release 1 ships the 8 KiB window, because every format in core's forty-eight is head-detectable and
a two-read ladder doubles the FREE cost of the `acquired → identified` transition on every unit to
serve a case with no known instance. What closes it: a fifth `FormatGuess` field
`need_bytes: int | None`, with the host re-invoking `sniff()` at most **once** per driver per unit
with a window of `min(need_bytes, 65_536)`, the second call charged to the same 5 ms
budget as the first. What would force it: one real third-party format with no head signature and no
usable extension. Until then the honest answer to a driver author is the three paths §1.3 names.

## New terms

Coined here, for merge into the lock. Every one is a **mechanism this document specifies**, not a
rename of an existing concept. `code_fingerprint` is deliberately **not** in this list: it already
has a home as a field of `Producer`, and §5.3 only specifies how it is computed for a driver.

| term | kind | definition |
|---|---|---|
| `owroster-items/1` | proto | What an `acquire/1` driver emits: NDJSON, one record per discovered unit, addressed by locator, with the **host** writing `unit` and `ingest_scope` rows. Symmetric with `owdoc-fragment/1` and `owgraph-items/1` — one pattern, three Ports. |
| `owvec-batch/1` | proto | What an `embed/1` driver emits: a JSON header plus a raw little-endian f32/int8/bit body over `omniweave-driver/1`. Row order is input order; a short batch is `TOO_LARGE`, never a silent truncation. |
| `ArtifactKind` | enum | The closed, core-owned thirteen-member vocabulary behind `[capability] consumes` and `produces`. Adding a member bumps `card_schema`; there is no experimental namespace (E2). |
| `EmbedManifest` | type | `(dim, metric, normalization, model_id, model_revision, max_tokens)` returned by `EmbedV1.manifest()` and asserted equal to the card's `[embed]` table, on the same grounds as `HELLO_ACK`. |
| `[acquire]` / `[derive]` / `[embed]` | file | The three non-monotone sibling tables added by E1, where an unknown key is a hard error, exactly as `[compile]` is (§5 X37). |
| `[deprecation]` | file | A driver's own retirement schedule: `since`, `removed_in`, `replaced_by`, `reason`, with a **minimum two-MINOR window** matching G16 (E8). |
| `[driver] exec` | column | An argv list, relative to the card's own directory, by which a non-Python `driver_path` driver names its executable. Mutually exclusive with `entrypoint`; forces `subproc` and `trust = local`; `activate()` imports nothing and the class assertions come from `HELLO_ACK` alone (E7). |
| `requires_credential` | column | A `[licence.code]` fact: the licence requires a purchased credential. `compute_tier`'s sole route to the `commercial` tier (E10). |
| `format_tokens` | column | The `[capability.parse]` card key listing the `{media_type, token}` **pairs** a driver contributes to `unit.format`'s **computed** domain — core's 48 ∪ the union of the `token` fields over every enabled card ([routing](05-ingest-and-routing.md) §5.1). Compared `⊇` over pairs, each `token` `[a-z0-9]{1,16}` and each `media_type` also in `[capability] formats`; two enabled cards pairing one `media_type` with different `token`s is `OW-D-024` at activation. Card-only: it is not a `doc.declared` / `doc.achieved` field and not one of §2.2's fifteen (§2.2). |
| `FormatTokenPair` | type | One `format_tokens` member: `{ media_type: str, token: str }`, the only place a third party's media-type-to-token association is written. Read by `format_token_for()` ([routing](05-ingest-and-routing.md) §2.2) (§2.2). |
| served token set | derived set | The token-side projection of one card: `{ format_token_for(m) for m in [capability] formats }` ∪ `{ p.token for p in [capability.parse] format_tokens }`, `None` dropped. Exists because `[capability] formats` holds media types and a rule's `unit.format` clause holds tokens, so `ow route lint` check 11 has something of the right type to compare (§2.2). |
| `env_digest` | concept | The sha256 over `(platform, machine, python minor, needs_binaries → identity of which(), identity of libcuda, OMNIWEAVE_PROBE_EPOCH)` — where an *identity* is `(realpath, st_size, st_mtime_ns)`, never a bare path and never a boolean — that forms the environment half of a cached `ProbeVerdict`'s key `(driver_id, driver_version, card_sha256, env_digest)`. The **only** name for it: there is no `host_fingerprint`. An environment change moves the digest; `OMNIWEAVE_PROBE_EPOCH` is the escape hatch for one it cannot see (E5, §4.7). |
| `probe_ttl_s` | constant | 600. How long an `unavailable` `ProbeVerdict` is cached before it is re-probed, because `unavailable` is the verdict a user *fixes* and its inputs are not all in `env_digest`. `ok` and `degraded` are cached for the life of the digest (E5). |
| `MAX_CARD_BYTES` | constant | 65,536. The card-size ceiling, with six sibling shape caps (nesting depth 6, 64 formats, 16 binaries, 256 pins, 64 benchmark rows, 32 config properties), each `CARD_INVALID` naming the cap (E6). |
| `requirement_digest` | concept | `Requirement.digest`: `sha256(canonical({f.name: _jsonable(getattr(self, f.name)) for f in fields(self) if f.name != "digest"}))`, computed once at construction. The first component of `resolve()`'s memo key `(requirement_digest, policy_digest, catalog_digest)`. Built from `dataclasses.fields()` and **never** from a written-out key list, so a field added to `Requirement` enters the digest by construction (§4.8). |
| `RESOLVE_MEMO_MAX` | constant | 512. The LRU bound on `resolve()`'s memo, held on the `Catalog` so it dies with the catalog rather than leaking across runs in a served process. |
| `frame_queue_max` | constant | 256. The host's bounded read queue per worker. A full queue means the host stops reading, so a frame flood becomes pipe backpressure and then `wall_ms_hard`, never host memory. |
| `canonical()` | fn | `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()`. The one canonicaliser behind `attestation`, `config_digest`, `catalog_digest` and the pins digest (E14). |
| `discovery_slow` | member | A `Degradation.kind` literal recorded when `Catalog.build()` crosses its 250 ms hard ceiling, naming the slowest step and the installed-distribution count (E4). |
| `driver_unavailable` | member | A `Degradation.kind` literal recorded when an entry point resolves and its `driver.toml` is missing or unreadable — a partially uninstalled distribution, or a wheel built without package data. Names the distribution; never stops a catalog. |
| `LicencePosture` | type | The frozen result of `ow drivers check --posture` and `omniweave.licence_posture()`: per-driver tiers and acks, the aggregated `restriction_bits` of the enabled set, the not-enabled-but-present set, and a verdict. Its JSON Schema is generated as `schema/drivers-check-out-v1.json` under G6, like every other Action output (E12). |
