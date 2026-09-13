"""The driver-facing value types, enums and Protocols.

Stdlib only. No pydantic, no numpy, no third party at all: `omniweave_ports` is the one
distribution whose `tools/layers.toml` row is `[]` and whose `dependencies` list is empty,
which is what lets a third-party driver import the whole omniweave surface in ~40 KB.

Specified in 04-driver-system.md section 1.3 (the home of every one of these types) and
charter.md section D3's `omniweave_ports` block; the enum members are charter.md D3 verbatim.
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import BinaryIO, Literal, Protocol, TypeAlias

Scalar: TypeAlias = str | int | float | bool | None
"""Everything a card's `[config]` schema may carry into `__init__`. charter.md D3."""

INLINE_MAX = 262_144
"""A driver-protocol body larger than this travels as a content-addressed blob reference.

charter.md section 6.10, restated in 03-document-model.md section 14, whose table gives
`omniweave_core.limits` as the home of the L2 limits. It is repeated here because
`ArtifactRef.of()` is the single site that applies it and ports may not import core — see the
note in 04-driver-system.md section 6.5 that the ceiling is "enforced in ports".
"""


class ArtifactKind(StrEnum):
    """The CLOSED, core-owned artifact-kind vocabulary behind `consumes` / `produces`.

    Thirteen members, and there is no experimental namespace: adding one bumps `card_schema`.
    Specified in 04-driver-system.md section 2.3 (Extends the charter, E2).
    """

    RAW_BYTES = "raw_bytes"
    ROSTER_ITEMS = "roster_items"
    DOC_FRAGMENT = "doc_fragment"
    GRAPH_ITEMS = "graph_items"
    WITNESS_SET = "witness_set"
    VECTOR_BATCH = "vector_batch"
    TEXT_BATCH = "text_batch"
    IL_BUNDLE = "il_bundle"
    ASSET = "asset"
    ARTIFACT = "artifact"
    RECEIPT = "receipt"
    CARRIER_DOC = "carrier_doc"
    DIAG = "diag"


_ARTIFACT_KINDS: frozenset[str] = frozenset(member.value for member in ArtifactKind)
"""The vocabulary as bare strings, for `ArtifactRef.__post_init__`'s membership check."""


class Port(StrEnum):
    """The five Ports.

    Four of the five protocols live in this package; `CompileV1` lives in
    `omniweave_core.out`. charter.md D3, 04-driver-system.md section 1.1.
    """

    ACQUIRE = "acquire"
    PARSE = "parse"
    DERIVE = "derive"
    EMBED = "embed"
    COMPILE = "compile"


class CostClass(StrEnum):
    """`[cost.model] class`. charter.md D3."""

    FREE = "free"
    LOCAL_COMPUTE = "local_compute"
    BILLED_API = "billed_api"


class Isolation(StrEnum):
    """`[isolation] preferred`. `WASM` is reserved and is not v1. charter.md D3."""

    INPROC = "inproc"
    SUBPROC = "subproc"
    WASM = "wasm"


class ReplayClass(StrEnum):
    """How far a re-run reproduces a previous one. charter.md D3."""

    BYTE_EXACT = "byte_exact"
    SEEDED = "seeded"
    UNPINNABLE = "unpinnable"


class TrustTier(StrEnum):
    """COMPUTED BY THE LOADER, never self-reported by a card.

    charter.md D3; the recipe is 04-driver-system.md section 4.2 (Extends the charter, E13).
    """

    FIRST_PARTY = "first_party"
    VENDORED = "vendored"
    PINNED = "pinned"
    LOCAL = "local"
    UNPINNED = "unpinned"


class LicenceTier(StrEnum):
    """`compute_tier(licence_code, licence_weights)`'s four values. charter.md D3."""

    OPEN = "open"
    RESTRICTED = "restricted"
    COMMERCIAL = "commercial"
    FORBIDDEN = "forbidden"


class Restriction(IntEnum):
    """A licence or use restriction as a reserved bit position: `bit = 1 << value`.

    Thirty-two codes are RESERVED and twelve are allocated; 12..31 are free, and a
    thirty-third code is a migration on a hot table. Every member's spelling matches its card
    fact exactly (`territory_excluded` -> `TERRITORY_EXCLUDED`), so the runner's fact-to-bit
    map special-cases no name. charter.md D3.
    """

    OUTPUT_SHARE_ALIKE = 0
    COMPETITOR_BAR = 1
    TERRITORY_EXCLUDED = 2
    FIELD_OF_USE_EXCLUDED = 3
    REVENUE_GATE = 4
    MAU_GATE = 5
    NO_REDISTRIBUTION = 6
    NO_MODEL_TRAINING = 7
    ATTRIBUTION_PER_OUTPUT = 8
    REMOTE_KILL_SWITCH = 9
    COPYLEFT_NETWORK = 10
    COPYLEFT_STRONG = 11

    @property
    def bit(self) -> int:
        """`1 << value` — the mask this restriction contributes to `restriction_bits`."""
        return 1 << self.value


RESTRICTION_BITS_RESERVED = 32
"""How many `Restriction` codes are reserved. charter.md D3: "32 codes RESERVED"."""


class FailureClass(StrEnum):
    """The thirteen classes a driver may raise.

    charter.md D3; the transient-or-permanent verdict for each is 08-runtime.md section 1.6's
    classifier table.
    """

    ENCRYPTED = "encrypted"
    NEEDS_OCR = "needs_ocr"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CORRUPT_INPUT = "corrupt_input"
    RESOURCE_LIMIT = "resource_limit"
    TOO_LARGE = "too_large"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    EMPTY_RESULT = "empty_result"
    DRIVER_CRASHED = "driver_crashed"
    DRIVER_BUG = "driver_bug"


TRANSIENT_FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {
        FailureClass.RATE_LIMITED,
        FailureClass.UPSTREAM_UNAVAILABLE,
        FailureClass.TIMEOUT,
        FailureClass.RESOURCE_LIMIT,
    }
)
"""The classes whose verdict is `transient` when a DRIVER reports them.

08-runtime.md section 1.6's table. `timeout` is the one class with two producers and two
verdicts: driver-reported it is transient (the driver observed a slow remote peer),
host-detected it is `failed_permanent`. Only a driver constructs a `DriverError`, so this set
is the driver half of that table, and it is what makes charter.md D3's "`retry_after_ms`
REQUIRED iff transient" a constructor check rather than a comment.
"""


@dataclass(frozen=True, slots=True)
class DriverError(Exception):
    """The one way a driver reports failure. Never return `None`, never an empty success.

    `retry_after_ms` is required if and only if the class is transient, because the retry
    ladder escalates from the class's first cooldown and a classless transient failure has
    nothing to escalate from. `NEEDS_OCR` fills `pages` — it is routing data, not a failure —
    and `RESOURCE_LIMIT` and `TOO_LARGE` fill `limit` with the knob that would need raising.

    Specified in charter.md D3 and 18-api-sketch.md section 5.1 rule 4.
    """

    cls: FailureClass
    message: str
    retry_after_ms: int | None = None
    pages: tuple[int, ...] = ()
    limit: str | None = None

    def __post_init__(self) -> None:
        """Enforce charter.md D3's "REQUIRED iff transient" in the constructor rather than in
        review — the discipline `StepResult.__post_init__` applies host-side (08 section 1.3).
        """
        transient = self.cls in TRANSIENT_FAILURE_CLASSES
        if transient and self.retry_after_ms is None:
            raise ValueError(f"{self.cls.value} is transient and requires retry_after_ms")
        if not transient and self.retry_after_ms is not None:
            raise ValueError(f"retry_after_ms is meaningless for {self.cls.value}")
        if self.retry_after_ms is not None and self.retry_after_ms < 0:
            raise ValueError("retry_after_ms is a non-negative millisecond cooldown")

    def __str__(self) -> str:
        """`<class>: <message>` — the form a stderr ring tail and a `Diag` row carry."""
        return f"{self.cls.value}: {self.message}"


class ProbeStatus(StrEnum):
    """A probe's three verdicts. charter.md D3."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProbeVerdict:
    """What `probe()` returns. `detail` must NAME the missing thing.

    A `DEGRADED` verdict fills `capabilities_lost` so the router can re-filter; an
    `UNAVAILABLE` one fills `missing` and `fix_hint`. charter.md D3.
    """

    status: ProbeStatus
    detail: str
    missing: tuple[str, ...] = ()
    fix_hint: str | None = None
    capabilities_lost: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeEnv:
    """What `probe()` is allowed to know. No writable path, no network handle, no config.

    `gpu_present` comes from `ctypes.util.find_library("cuda")`, NEVER by importing a
    framework, and `vram_gb` is 0.0 when unknown for the same reason. The probe runs in a
    worker, never in the host process, and its verdict is cached per
    `(driver_id, version, card_sha256, env_digest)`.

    Specified in 04-driver-system.md section 1.3.
    """

    platform: str
    machine: str
    python: tuple[int, int]
    which: Mapping[str, str | None]
    gpu_present: bool
    vram_gb: float
    offline: bool


class BlobStore(Protocol):
    """The CAS as a driver sees it: a read-only path, a reader, and a metered writer.

    `put()` returns a digest and is metered through `ArtifactRef.of`, the single site that
    applies the invocation's `max_output_bytes` ceiling. The sole implementation is
    `omniweave_core.blobs` (02-architecture.md section 2 row 17).

    Specified in 04-driver-system.md section 1.3.
    """

    def path(self, digest: str) -> str:
        """A READ-ONLY filesystem path under `roots.source_ro`."""
        ...

    def open(self, digest: str) -> BinaryIO:
        """Open the blob for reading."""
        ...

    def put(self, data: bytes) -> str:
        """Store `data` and return its digest. Metered through `ArtifactRef.of`."""
        ...


class ServiceHandle(Protocol):
    """What `DriverIO.service(name)` returns: a base URL, a token and a deadline.

    NOT a client library, which is why `omniweave-llm` needs neither torch nor an SDK. It is
    a Protocol here and a frozen dataclass in `omniweave_core.modelserver` (08-runtime.md
    section 3.2) — one concept, one name, one lock row, the same split `BlobStore` uses —
    because `tools/layers.toml` gives `omniweave_ports = []` and a driver must be able to
    name the type it is handed.

    **The eight attributes are `@property` and not bare annotations, and that is the fix for
    D181.** A bare annotation in a Protocol is READ-WRITE, so the frozen dataclass 08:967
    prints could not satisfy this Protocol — and a mutable `base_url` or `token` would be a
    driver able to redirect its own calls or rewrite its own credential, through the one
    channel INV-6 exists to keep narrow. Both shipped implementations are frozen
    (`modelserver.Handle` and `cassette.CassetteHandle`); nothing was ever meant to write
    here, and until W4.9b nothing had asserted the conformance so nothing had noticed.

    Specified in 04-driver-system.md section 1.3.
    """

    @property
    def name(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def token(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def model_rev(self) -> str: ...

    @property
    def capacity(self) -> int: ...

    @property
    def traceparent(self) -> str: ...

    @property
    def deadline_ms(self) -> int: ...

    def post(self, path: str, body: bytes, *, headers: Mapping[str, str] | None = None) -> bytes:
        """POST to `base_url + path` under this handle's token and deadline."""
        ...

    def cancelled(self) -> bool:
        """True once the generation this handle was issued for is superseded."""
        ...


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DriverIO:
    """The ONLY channel a driver has to the outside.

    No Store, no Cache, no work table, no BudgetLedger, no RunContext, no writable
    `output_root` or `cache_root`, no socket, no DocSink, no GraphSink. NOT EXTENSIBLE:
    adding a field here amends the charter (INV-6), whose audit question is literally "count
    `DriverIO`'s fields" (01-principles.md section 12 row 2). It has four.

    The four methods are the host's. `omniweave_core.host` (02-architecture.md section 2
    row 14, roadmap item W3.2) provides the concrete `DriverIO` a worker hands a driver; they
    raise `NotImplementedError` here because ports has no behaviour and charter.md D3 prints
    their bodies as `...`.

    Specified in charter.md D3 and 04-driver-system.md sections 1.3 and 1.5.
    """

    blobs: BlobStore
    tmpdir: str
    deadline_ms: int
    max_output_bytes: int

    def service(self, name: str) -> ServiceHandle:
        """Attach-or-spawn a HOST-managed Service.

        The single widening of "`DriverIO` and nothing else", and what it widens to is a base
        URL, not a socket (04-driver-system.md section 1.5 obligation 1). The attach-or-spawn
        ladder is 08-runtime.md section 3.2's; the implementation arrives with W3.2.
        """
        raise NotImplementedError(f"service({name!r}): omniweave_core.host provides DriverIO")

    def cancelled(self) -> bool:
        """Check at every loop top. Implemented by the host in W3.2."""
        raise NotImplementedError("cancelled(): omniweave_core.host provides DriverIO")

    def log(self, event: str, **fields: Scalar) -> None:
        """Emit one LOG frame. Implemented by the host in W3.2."""
        raise NotImplementedError(f"log({event!r}): omniweave_core.host provides DriverIO")

    def progress(self, done: int, total: int | None) -> None:
        """Reset `progress_ms`.

        `wall_ms_hard` does not reset and is the backstop, so a `PROGRESS` flood cannot
        extend a driver's own wall clock (04-driver-system.md section 6.5). Implemented by
        the host in W3.2.
        """
        raise NotImplementedError(f"progress({done}): omniweave_core.host provides DriverIO")


_OUTPUT_METER: weakref.WeakKeyDictionary[DriverIO, int] = weakref.WeakKeyDictionary()
"""Per-invocation running total of bytes leaving through `ArtifactRef.of`.

Keyed on the invocation's `DriverIO`, which is what "the running total per invocation" names
(04-driver-system.md section 6.5). Weak, so a finished invocation's counter dies with its
`DriverIO` — which is why `DriverIO` carries `weakref_slot=True`.
"""

_HEAD_CACHE: weakref.WeakKeyDictionary[ArtifactRef, bytes] = weakref.WeakKeyDictionary()
"""The head window retained for a blob-backed `ArtifactRef` built by `ArtifactRef.of`.

`head()` is "the only read a driver needs" and takes no `BlobStore`, so a blob-backed ref
keeps its first `INLINE_MAX` bytes here rather than being unreadable — see
`ParseV1.is_valid_nonempty`, which the host calls as `ref.head(65_536)` on a ref that may be
blob-backed (18-api-sketch.md section 5.2).
"""

_METER_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ArtifactRef:
    """What a driver returns bytes as. Exactly one of `inline` and `blob` is set.

    `inline` is set iff the body is at most `INLINE_MAX`; above it the body is a
    `cas://<sha256>` reference. Construct through `of()`, the single site that enforces the
    invocation's `max_output_bytes` ceiling, so no driver hand-rolls it and none evades it by
    writing many small blobs.

    Specified in 04-driver-system.md sections 1.3 and 6.5.
    """

    kind: str
    byte_len: int
    inline: bytes | None = None
    blob: str | None = None

    def __post_init__(self) -> None:
        """`kind` is an `ArtifactKind` member and exactly one body channel is set."""
        if self.kind not in _ARTIFACT_KINDS:
            raise ValueError(f"{self.kind!r} is outside the closed artifact-kind vocabulary")
        if self.byte_len < 0:
            raise ValueError("byte_len is a non-negative byte count")
        if (self.inline is None) == (self.blob is None):
            raise ValueError("exactly one of `inline` and `blob` is set")
        if self.inline is not None:
            if len(self.inline) != self.byte_len:
                raise ValueError("byte_len must equal len(inline) for an inline body")
            if self.byte_len > INLINE_MAX:
                raise ValueError(f"an inline body is at most INLINE_MAX={INLINE_MAX} bytes")
        elif not str(self.blob).startswith("cas://"):
            raise ValueError("a blob reference is spelled 'cas://<sha256>'")

    def head(self, n: int) -> bytes:
        """The first `n` bytes of the body — the only read a driver needs.

        An inline body is sliced directly. A blob-backed ref built by `of()` answers from the
        head window `of()` retained. A blob-backed ref built any other way carries no bytes
        and holds no `BlobStore`, and says so rather than reporting an empty body.
        """
        if n < 0:
            raise ValueError("n is a non-negative byte count")
        if self.inline is not None:
            return self.inline[:n]
        retained = _HEAD_CACHE.get(self)
        if retained is None:
            raise DriverError(
                cls=FailureClass.DRIVER_BUG,
                message=f"head() on a blob-backed ArtifactRef({self.kind}) not built by of()",
            )
        return retained[:n]

    @classmethod
    def of(cls, kind: str, body: bytes, io: DriverIO) -> ArtifactRef:
        """Inline under `INLINE_MAX`, `io.blobs.put()` above it, and meter both.

        THE CEILING IS ENFORCED HERE, ONCE: this invocation's running total is charged before
        anything is written, so a hundred one-megabyte blobs under a four-megabyte ceiling
        raise `TOO_LARGE` on the put that crosses it (04-driver-system.md section 6.5). A
        driver re-checking `max_output_bytes` is a second implementation of a safety limit,
        which is how limits drift apart.

        Raises:
            DriverError(TOO_LARGE, limit="max_output_bytes") — this body crosses the ceiling.
        """
        byte_len = len(body)
        with _METER_LOCK:
            total = _OUTPUT_METER.get(io, 0) + byte_len
            if total > io.max_output_bytes:
                raise DriverError(
                    cls=FailureClass.TOO_LARGE,
                    message=(
                        f"{kind}: {byte_len} bytes would bring this invocation to {total}, "
                        f"over max_output_bytes={io.max_output_bytes}"
                    ),
                    limit="max_output_bytes",
                )
            _OUTPUT_METER[io] = total
        if byte_len <= INLINE_MAX:
            return cls(kind=kind, byte_len=byte_len, inline=body)
        digest = io.blobs.put(body)
        ref = cls(
            kind=kind,
            byte_len=byte_len,
            blob=digest if digest.startswith("cas://") else f"cas://{digest}",
        )
        _HEAD_CACHE[ref] = body[:INLINE_MAX]
        return ref


@dataclass(frozen=True, slots=True)
class Locator:
    """`acquire/1`'s input.

    `scheme` must be a member of the card's `[capability.acquire] schemes`, `cursor` is
    opaque iff `[acquire] cursor_opaque`, and `since_ns = None` is a full enumeration.
    04-driver-system.md section 1.3.
    """

    scheme: str
    target: str
    cursor: str | None = None
    since_ns: int | None = None


@dataclass(frozen=True, slots=True)
class UnitRef:
    """One unit of work as a driver sees it.

    NO `unit_id`, NO `doc_ord`, NO `block_id`: the host mints every durable identity, which
    is what makes a fragment portable between stores. 04-driver-system.md section 1.3.
    """

    uri: str
    part: str
    content_sha256: str
    byte_len: int
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class PartSelector:
    """Which pages or container members this invocation covers.

    `pages = ()` is the whole document; `parts` names container member paths for a
    part-granularity driver. A fragment naming a page outside this selector is
    `OW_FRAGMENT_OUT_OF_SCOPE`. 04-driver-system.md section 1.3.
    """

    pages: tuple[int, ...] = ()
    parts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeriveScope:
    """`derive/1`'s input, carrying THE containment boundary.

    An item citing outside `allowed_cites` is quarantined BY THE HOST and kept verbatim in a
    `quarantine` row — the driver's own honesty is not load-bearing (04-driver-system.md
    section 6.6). `schema` is set only when `[capability.derive] schema != "none"`, and
    `corpus_vocab` is the closed etype set when one is configured.

    Specified in 04-driver-system.md section 1.3.
    """

    lane: str
    units: tuple[UnitRef, ...]
    allowed_cites: frozenset[str]
    schema: Mapping[str, object] | None = None
    corpus_vocab: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TextBatch:
    """`embed/1`'s input.

    `role` gates the asymmetric instruction prefix, if the card declares one.
    04-driver-system.md section 1.3.
    """

    texts: tuple[str, ...]
    role: Literal["document", "query"]


@dataclass(frozen=True, slots=True)
class EmbedManifest:
    """The `(dim, metric, normalization)` contract the store must match.

    `model_revision` is an EXACT sha; `"main"` is forbidden framework-wide.
    `EmbedV1.manifest()` must equal the card's `[embed]` table field for field, or
    `CARD_CODE_MISMATCH`, because a wrong `dim` corrupts an index with no symptom.
    04-driver-system.md sections 1.3 and 1.4.
    """

    dim: int
    metric: Literal["cosine", "ip", "l2"]
    normalization: Literal["none", "l2"]
    model_id: str
    model_revision: str
    max_tokens: int


@dataclass(frozen=True, slots=True)
class DriverMetrics:
    """PHYSICAL UNITS ONLY. There is no `cost_micros`.

    The runner prices these through the operator's `PriceBook`: a contributor on a rented
    A100 cannot know your GPU-hour cost, and if they guess, every estimate in your fleet is
    wrong in a way you cannot audit (INV-15). charter.md D3.
    """

    wall_ms: int = 0
    cpu_ms: int = 0
    gpu_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    bytes_egress: int = 0
    bytes_read: int = 0
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class DriverResult:
    """STRICTLY SMALLER than the runtime's `StepResult`.

    A driver cannot claim `skipped_cached`, `skipped_unchanged`, `deferred_budget`,
    `cancelled`, an identity, a cache key, a price or a cache hit (INV-7): `outcome` is `ok`
    or `ok_partial` and nothing else. `confidence`, `origin_driver`, `origin_operator`,
    `producer_id`, `restriction_bits`, `trust`, `was_cache_hit` and every micro are set BY
    THE RUNNER.

    Specified in charter.md D3 and 08-runtime.md section 1.3.
    """

    outcome: Literal["ok", "ok_partial"]
    produced: tuple[ArtifactRef, ...]
    partial_reason: str | None = None
    metrics: DriverMetrics = DriverMetrics()

    def __post_init__(self) -> None:
        """`ok_partial` requires `partial_reason` — 08-runtime.md section 1.3's `Outcome`
        table, which `StepResult.__post_init__` enforces on the same key host-side."""
        if self.outcome not in ("ok", "ok_partial"):
            raise ValueError(f"{self.outcome!r} is not one of 'ok', 'ok_partial'")
        if self.outcome == "ok_partial" and self.partial_reason is None:
            raise ValueError("ok_partial requires partial_reason")
