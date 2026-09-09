"""The four Port protocols a third party may implement: acquire, parse, derive, embed.

`CompileV1` is the fifth and is deliberately NOT here: its signature mixes ports types
(`DriverIO`, `DriverResult`) with the OUT framework types a target is validated by (`Plan`,
`ILBundle`, `AssetLedger`, `RuleSpec`, `CarrierDoc`), a Protocol has to live in the one
distribution holding both halves, and so it lives in `omniweave_core.out.compile`
(02-architecture.md section 3.2 rule 4, charter.md section 5 X4). Its seven methods are
`probe`, `carrier`, `rules`, `measure`, `lower`, `postflight`, `project` — there is no
`validate()` — and they are specified in 09-generation.md. Adding a Port is a core release.

Four obligations bind every Port (04-driver-system.md section 1.5): a driver receives
`DriverIO` and nothing else (INV-6); the driver proposes and the host commits, so no
`block_id`, `unit_uri`, `segment_id` or `entity_id` ever crosses the wire from a driver
(charter.md section 5 X1); a driver never forges provenance, price, trust or a cache hit
(INV-7, INV-15); and a driver never retries internally, because retry is the runtime's, with
the runtime's budget and the runtime's ledger.

Specified in 04-driver-system.md section 1.4 and 18-api-sketch.md section 5.1.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from omniweave_ports.detect import FormatGuess, StreamHint
from omniweave_ports.types import (
    ArtifactRef,
    DeriveScope,
    DriverIO,
    DriverResult,
    EmbedManifest,
    Locator,
    PartSelector,
    ProbeEnv,
    ProbeVerdict,
    Scalar,
    TextBatch,
    UnitRef,
)


class AcquireV1(Protocol):
    """`acquire/1` — a connector: fs, url, SharePoint, IMAP.

    Ships with zero first-party drivers at release 1 (04-driver-system.md section 10.3).

    Specified in 04-driver-system.md section 1.4.
    """

    PORT: ClassVar[str] = "acquire/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """MUST NOT download, spawn or write. Runs in a worker (04 section 4.7)."""
        ...

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: loads no model and opens no file."""
        ...

    def enumerate(self, locator: Locator, io: DriverIO) -> DriverResult:
        """Emit `owroster-items/1`: one NDJSON record per discovered unit, plus blobs put
        through `io.blobs`.

        The HOST writes the `unit` and `ingest_scope` rows. A driver never writes the roster,
        exactly as a parse driver never writes `DocSink` (charter.md section 5 X1).
        """
        ...

    def fetch(self, ref: UnitRef, io: DriverIO) -> DriverResult:
        """Materialise one unit's bytes into the CAS. Idempotent on `content_sha256`."""
        ...


class ParseV1(Protocol):
    """`parse/1` — a parser, decoder, OCR engine, page VLM, or a target's `read_back`.

    Specified in charter.md D3 (printed in full) and 04-driver-system.md section 1.4.
    """

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """MUST NOT download, spawn or write. Runs in a worker (04 section 4.7)."""
        ...

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: loads no model and opens no file."""
        ...

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """MANY-TO-ONE and RANKED. MUST NOT advance a stream it is given.

        The HOST asserts that by passing immutable `bytes` and re-checking the caller's
        offset. `head` is the first 8,192 bytes and one read. Returning `()` is a legitimate
        "not mine", not a failure.
        """
        ...

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """Emit `owdoc-fragment/1` as an `ArtifactRef`; the HOST decodes it and drives
        `DocSink` (charter.md section 5 X1).

        Raise `DriverError` for every failure. NEVER return `None` and NEVER return an empty
        success: the host converts an `ok` that fails `is_valid_nonempty` into
        `FAILED_PERMANENT(EMPTY_RESULT)` BEFORE anything is cached.
        """
        ...

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """Called by the host BEFORE caching, so an empty success is never memoised."""
        ...


class DeriveV1(Protocol):
    """`derive/1` — an extractor, a chunker, a segmenter.

    Specified in 04-driver-system.md section 1.4.
    """

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """MUST NOT download, spawn or write. Runs in a worker (04 section 4.7)."""
        ...

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: loads no model and opens no file."""
        ...

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """Emit `owgraph-items/1`, plus a `witness_set` artefact where the card declares one
        — which a corpus-granularity billed driver must (04-driver-system.md section 2.6)."""
        ...


class EmbedV1(Protocol):
    """`embed/1` — an embedder.

    Ships with zero first-party drivers at release 1 (04-driver-system.md section 10.3). The
    engine behind an embedder is a Service, not a Driver: the embedder has a model identity
    that enters index metadata, a `(dim, metric, normalization)` contract, a cost class and a
    licence; the engine has no unit and no cost per unit.

    Specified in 04-driver-system.md section 1.4.
    """

    PORT: ClassVar[str] = "embed/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """MUST NOT download, spawn or write. Runs in a worker (04 section 4.7)."""
        ...

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY: loads no model and opens no file."""
        ...

    def manifest(self) -> EmbedManifest:
        """MUST equal the card's `[embed]` table field for field, or `CARD_CODE_MISMATCH`,
        for the same reason `HELLO_ACK` is checked: a wrong `dim` corrupts an index with no
        symptom."""
        ...

    def embed(self, texts: TextBatch, io: DriverIO) -> DriverResult:
        """Emit `owvec-batch/1`: a JSON header plus a raw little-endian f32/int8/bit body.

        Row order is the input order; a short batch is `TOO_LARGE`, never a silent
        truncation.
        """
        ...
