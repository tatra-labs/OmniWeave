"""The five Protocols, and a minimal conforming stub for each of the four Ports.

"A driver has a `PORT` and `SCHEMA_VERSION` class variable, a `probe()` classmethod, an
`__init__(**config: Scalar)` that loads nothing, one or more work methods taking a `DriverIO`
and returning a `DriverResult`, and a `driver.toml` beside it. No base class, no registration
decorator, no import of the framework beyond `omniweave_ports`" (04-driver-system.md section
1.2). These stubs are written the way a third party writes one — implementing nothing but the
protocol, importing nothing but this package — and each work method is actually CALLED, so a
signature that reads right and does not run cannot pass.

Specified in 04-driver-system.md sections 1.2 and 1.4, 18-api-sketch.md section 5.1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import io as _io
from typing import BinaryIO, ClassVar

import pytest
from omniweave_ports import (
    AcquireV1,
    ArtifactRef,
    DeriveScope,
    DeriveV1,
    DriverBase,
    DriverIO,
    DriverMetrics,
    DriverResult,
    EmbedManifest,
    EmbedV1,
    FormatGuess,
    Locator,
    ParseV1,
    PartSelector,
    ProbeEnv,
    ProbeStatus,
    ProbeVerdict,
    Scalar,
    StreamHint,
    TextBatch,
    UnitRef,
)

# --------------------------------------------------------------------------------------
# a host, as small as the contract allows
# --------------------------------------------------------------------------------------


class MemoryBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def path(self, digest: str) -> str:
        return f"/cas/{digest}"

    def open(self, digest: str) -> BinaryIO:
        return _io.BytesIO(self.blobs[digest])

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.blobs[digest] = data
        return digest


class HostIO(DriverIO):
    """What `omniweave_core.host` will be: a subclass supplying the four methods.

    Proves the printed shape is usable — a frozen, slotted `DriverIO` with four fields whose
    behaviour arrives host-side (W3.2) without any field being added to it (INV-6).
    """

    events: list[tuple[str, dict[str, Scalar]]] = []  # noqa: RUF012 — a test spy, not a field

    def cancelled(self) -> bool:
        return False

    def log(self, event: str, **fields: Scalar) -> None:
        self.events.append((event, dict(fields)))

    def progress(self, done: int, total: int | None) -> None:
        self.events.append(("progress", {"done": done, "total": total}))


def make_io(store: MemoryBlobStore | None = None) -> HostIO:
    return HostIO(
        blobs=store or MemoryBlobStore(),
        tmpdir="ow-tmp/invocation",
        deadline_ms=30_000,
        max_output_bytes=32 * 1_048_576,
    )


ENV = ProbeEnv(
    platform="linux",
    machine="x86_64",
    python=(3, 11),
    which={},
    gpu_present=False,
    vram_gb=0.0,
    offline=True,
)


# --------------------------------------------------------------------------------------
# one minimal conforming driver per Port
# --------------------------------------------------------------------------------------


class StubAcquire:
    PORT: ClassVar[str] = "acquire/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"stdlib only on {env.platform}")

    def __init__(self, **config: Scalar) -> None:
        self.root = str(config.get("root", "/"))

    def enumerate(self, locator: Locator, io: DriverIO) -> DriverResult:
        body = f'{{"t":"item","uri":"{locator.scheme}://{locator.target}"}}\n'.encode()
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("roster_items", body, io),))

    def fetch(self, ref: UnitRef, io: DriverIO) -> DriverResult:
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("raw_bytes", ref.content_sha256.encode(), io),),
            metrics=DriverMetrics(bytes_read=ref.byte_len),
        )


class StubParse:
    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"stdlib codecs on {env.machine}")

    def __init__(self, **config: Scalar) -> None:
        self.errors = str(config.get("errors", "strict"))

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        if b"\x00" in head:
            return ()
        confidence = 0.9 if (hint.extension or "") == ".txt" else 0.4
        return (
            FormatGuess(
                media_type="text/plain",
                format_token="txt",  # noqa: S106 — a format token, not a credential
                confidence=confidence,
                consumed_bytes=len(head),
            ),
        )

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        pages = parts.pages or (1,)
        body = b"".join(
            b'{"t":"block","tmp":"b%d","kind":"paragraph","text":"%s"}\n'
            % (page, unit.content_sha256.encode())
            for page in pages
        )
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("doc_fragment", body, io),))

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        return b'"t":"block"' in ref.head(65_536)


class StubDerive:
    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"offline={env.offline}")

    def __init__(self, **config: Scalar) -> None:
        self.lane = str(config.get("lane", "claims"))

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        body = b"".join(
            b'{"t":"item","tmp":"i%d","lane":"%s"}\n' % (i, scope.lane.encode())
            for i, _ in enumerate(scope.units)
        )
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("graph_items", body, io),))


class StubEmbed:
    PORT: ClassVar[str] = "embed/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"gpu_present={env.gpu_present}")

    def __init__(self, **config: Scalar) -> None:
        self.batch = int(config.get("batch", 8) or 8)

    def manifest(self) -> EmbedManifest:
        return EmbedManifest(
            dim=8,
            metric="cosine",
            normalization="l2",
            model_id="stub",
            model_revision="0" * 40,
            max_tokens=512,
        )

    def embed(self, texts: TextBatch, io: DriverIO) -> DriverResult:
        body = b'{"rows":%d,"role":"%s"}\n' % (len(texts.texts), texts.role.encode())
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("vector_batch", body, io),))


PORTS: list[tuple[type, type, str, tuple[str, ...]]] = [
    (AcquireV1, StubAcquire, "acquire/1", ("probe", "__init__", "enumerate", "fetch")),
    (ParseV1, StubParse, "parse/1", ("probe", "__init__", "sniff", "parse", "is_valid_nonempty")),
    (DeriveV1, StubDerive, "derive/1", ("probe", "__init__", "derive")),
    (EmbedV1, StubEmbed, "embed/1", ("probe", "__init__", "manifest", "embed")),
]


# --------------------------------------------------------------------------------------
# the protocol surface
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("proto", "_stub", "port", "members"), PORTS)
def test_each_port_declares_its_port_string(
    proto: type, _stub: type, port: str, members: tuple[str, ...]
) -> None:
    """`PORT` is `"<name>/<MAJOR>"` and `activate()` asserts it against the card."""
    assert port == proto.PORT
    assert "SCHEMA_VERSION" in proto.__annotations__
    assert members  # the row is not empty; membership is asserted below


@pytest.mark.parametrize(("proto", "_stub", "_port", "members"), PORTS)
def test_a_port_protocol_has_exactly_its_printed_members(
    proto: type, _stub: type, _port: str, members: tuple[str, ...]
) -> None:
    """04-driver-system.md section 1.4 prints all four in full. There is no `close()`, no
    `__enter__` and no explicit teardown on any Port protocol."""
    declared = {
        name
        for name, value in vars(proto).items()
        if (callable(value) or isinstance(value, classmethod))
        and (not name.startswith("__") or name == "__init__")
    }
    assert declared == set(members)
    for absent in ("close", "__enter__", "__exit__", "validate"):
        assert absent not in declared


@pytest.mark.parametrize(("proto", "stub", "_port", "members"), PORTS)
def test_the_stub_matches_the_protocol_signature_for_signature(
    proto: type, stub: type, _port: str, members: tuple[str, ...]
) -> None:
    """Structural conformance, checked the way a type checker would: same names, same
    parameters, same annotations."""
    for name in members:
        assert inspect.signature(getattr(proto, name)) == inspect.signature(getattr(stub, name))


def test_driver_base_is_runtime_checkable_and_the_four_ports_are_not() -> None:
    """18-api-sketch.md section 5.1 marks `DriverBase` `@runtime_checkable` and prints the
    four Port protocols as plain `Protocol`s. `isinstance` against a Protocol only checks
    member presence, so the work signatures are the conform `contract` suite's, not
    `isinstance`'s."""
    assert getattr(DriverBase, "_is_runtime_protocol", False) is True
    for proto, _stub, _port, _members in PORTS:
        assert getattr(proto, "_is_runtime_protocol", False) is False


@pytest.mark.parametrize(("_proto", "stub", "_port", "_members"), PORTS)
def test_every_stub_satisfies_driver_base(
    _proto: type, stub: type, _port: str, _members: tuple[str, ...]
) -> None:
    """The shape every Port protocol repeats: `PORT`, `SCHEMA_VERSION`, `probe`, `__init__`."""
    assert isinstance(stub(), DriverBase)


def test_driver_base_rejects_a_class_without_probe() -> None:
    class NotADriver:
        PORT: ClassVar[str] = "parse/1"
        SCHEMA_VERSION: ClassVar[int] = 1

    assert not isinstance(NotADriver(), DriverBase)


# --------------------------------------------------------------------------------------
# the stubs actually run
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("_proto", "stub", "_port", "_members"), PORTS)
def test_probe_returns_a_verdict_that_names_what_was_checked(
    _proto: type, stub: type, _port: str, _members: tuple[str, ...]
) -> None:
    verdict = stub.probe(ENV)
    assert isinstance(verdict, ProbeVerdict)
    assert verdict.status is ProbeStatus.OK
    assert verdict.detail


@pytest.mark.parametrize(("_proto", "stub", "_port", "_members"), PORTS)
def test_construction_is_static_config_only(
    _proto: type, stub: type, _port: str, _members: tuple[str, ...]
) -> None:
    """A 100%-cache-hit run constructs nothing at all, so `__init__` takes only `Scalar`s
    and touches no file (04-driver-system.md section 1.2)."""
    parameters = inspect.signature(stub.__init__).parameters
    assert list(parameters)[1:] == ["config"]
    assert parameters["config"].kind is inspect.Parameter.VAR_KEYWORD


def test_acquire_enumerate_and_fetch_produce_the_right_artifact_kinds() -> None:
    driver, driver_io = StubAcquire(), make_io()
    roster = driver.enumerate(Locator(scheme="file", target="/corpus"), driver_io)
    assert roster.outcome == "ok"
    assert [ref.kind for ref in roster.produced] == ["roster_items"]
    unit = UnitRef(uri="file:///corpus/a.txt", part="", content_sha256="ab" * 32, byte_len=9)
    fetched = driver.fetch(unit, driver_io)
    assert [ref.kind for ref in fetched.produced] == ["raw_bytes"]
    assert fetched.metrics.bytes_read == 9


def test_parse_sniffs_ranked_guesses_without_advancing_a_stream() -> None:
    driver = StubParse()
    head = b"hello world\n\nsecond paragraph\n"
    hint = StreamHint(
        filename="a.txt", extension=".txt", declared_media_type=None, byte_len=len(head)
    )
    guesses = driver.sniff(head, hint)
    assert [g.format_token for g in guesses] == ["txt"]
    assert guesses[0].consumed_bytes == len(head)
    assert head == b"hello world\n\nsecond paragraph\n"


def test_returning_no_guess_is_a_legitimate_not_mine() -> None:
    """ "Returning `()` is a legitimate 'not mine', not a failure" (18 section 5.1 rule 2)."""
    assert StubParse().sniff(b"\x00\x01\x02", StreamHint(None, None, None, 3)) == ()


def test_parse_emits_a_doc_fragment_the_host_can_validate() -> None:
    driver, driver_io = StubParse(), make_io()
    unit = UnitRef(uri="file:///a.txt", part="", content_sha256="cd" * 32, byte_len=4)
    result = driver.parse(unit, PartSelector(pages=(1, 2)), driver_io)
    assert result.outcome == "ok"
    assert result.partial_reason is None
    assert driver.is_valid_nonempty(result.produced[0])


def test_an_empty_fragment_fails_is_valid_nonempty() -> None:
    """The host converts an `ok` failing this into FAILED_PERMANENT(EMPTY_RESULT) BEFORE
    anything is cached, so an empty success is never memoised."""
    ref = ArtifactRef.of("doc_fragment", b'{"t":"end","status":"ok"}\n', make_io())
    assert not StubParse().is_valid_nonempty(ref)


def test_derive_emits_graph_items_within_its_scope() -> None:
    driver, driver_io = StubDerive(), make_io()
    scope = DeriveScope(
        lane="claims",
        units=(UnitRef(uri="file:///a", part="", content_sha256="ef" * 32, byte_len=1),),
        allowed_cites=frozenset({"cite:a"}),
    )
    result = driver.derive(scope, driver_io)
    assert [ref.kind for ref in result.produced] == ["graph_items"]


def test_embed_manifest_is_stable_and_embed_emits_a_vector_batch() -> None:
    driver, driver_io = StubEmbed(), make_io()
    assert driver.manifest() == driver.manifest()
    assert driver.manifest().model_revision != "main"
    result = driver.embed(TextBatch(texts=("a", "b"), role="document"), driver_io)
    assert [ref.kind for ref in result.produced] == ["vector_batch"]


# --------------------------------------------------------------------------------------
# DriverIO, as the host will subclass it
# --------------------------------------------------------------------------------------


def test_the_host_supplies_driver_io_s_behaviour_without_adding_a_field() -> None:
    driver_io = make_io()
    assert driver_io.cancelled() is False
    assert driver_io.log("decoded", pages=3) is None
    assert driver_io.progress(1, None) is None
    assert len(dataclasses.fields(driver_io)) == 4


def test_the_ports_driver_io_defers_its_four_methods_to_the_host() -> None:
    """Ports has no behaviour: the bodies charter.md D3 prints as `...` arrive with W3.2
    (`omniweave_core.host`), and say so rather than returning `None`."""
    bare = DriverIO(blobs=MemoryBlobStore(), tmpdir="ow-tmp", deadline_ms=1, max_output_bytes=1)
    with pytest.raises(NotImplementedError, match=r"omniweave_core\.host"):
        bare.cancelled()
    with pytest.raises(NotImplementedError, match=r"omniweave_core\.host"):
        bare.log("decoded")
    with pytest.raises(NotImplementedError, match=r"omniweave_core\.host"):
        bare.progress(0, None)
    with pytest.raises(NotImplementedError, match=r"omniweave_core\.host"):
        bare.service("vlm")
