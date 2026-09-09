"""The frozen shapes of `omniweave_ports`, field for field.

P1's exit freezes this package: `CONTRACT = 1` is the ABI every driver any third party ever
writes is typed against, so these tests are the freeze, not a smoke test. Each asserts a
printed shape from 04-driver-system.md section 1.3 or charter.md section D3 — including the
two fields that are deliberately ABSENT (`FormatGuess.basis`, `StreamHint.trust_class`),
which no positive test would catch.

Specified in 02-architecture.md section 2 row 1, 04-driver-system.md section 1.3,
13-quality.md section 2 (T1 unit tier).
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import sys
from pathlib import Path

import omniweave_ports
import pytest
from omniweave_ports import (
    INLINE_MAX,
    RESTRICTION_BITS_RESERVED,
    TRANSIENT_FAILURE_CLASSES,
    ArtifactKind,
    CostClass,
    DeriveScope,
    DriverError,
    DriverIO,
    DriverMetrics,
    DriverResult,
    EmbedManifest,
    FailureClass,
    FormatGuess,
    Isolation,
    LicenceTier,
    Locator,
    PartSelector,
    Port,
    ProbeEnv,
    ProbeStatus,
    ProbeVerdict,
    ReplayClass,
    Restriction,
    StreamHint,
    TextBatch,
    TrustTier,
    UnitRef,
)

SRC = Path(omniweave_ports.__file__).parent


# --------------------------------------------------------------------------------------
# the export inventory
# --------------------------------------------------------------------------------------

# 18-api-sketch.md section 9's two `omniweave_ports` T-CONTRACT rows, plus the three names
# 04-driver-system.md adds and says the inventories are missing: `ServiceHandle` (section 1.3,
# "Two `omniweave_ports` export inventories elsewhere stop at `EmbedManifest` and need
# `ServiceHandle` appended"), `ArtifactKind` (section 2.3, "lives in
# `omniweave_ports.ArtifactKind`") and `DriverBase` (section 1.2, `omniweave_ports/base.py`).
PLANNED_EXPORTS = frozenset(
    {
        "Port",
        "CostClass",
        "Isolation",
        "ReplayClass",
        "TrustTier",
        "LicenceTier",
        "Restriction",
        "FailureClass",
        "DriverError",
        "ProbeStatus",
        "ProbeVerdict",
        "ProbeEnv",
        "DriverIO",
        "BlobStore",
        "DriverMetrics",
        "DriverResult",
        "ArtifactRef",
        "Locator",
        "UnitRef",
        "PartSelector",
        "StreamHint",
        "FormatGuess",
        "DeriveScope",
        "TextBatch",
        "EmbedManifest",
        "ServiceHandle",
        "ArtifactKind",
        "DriverBase",
        "Scalar",
        "AcquireV1",
        "ParseV1",
        "DeriveV1",
        "EmbedV1",
    }
)

# Constants the plan states but does not put in an export row. They are exported because
# `ArtifactRef.of` applies INLINE_MAX inside this package (04 section 6.5) and because
# `DriverError.__post_init__` needs the transient set (08-runtime.md section 1.6).
EXPORTED_CONSTANTS = frozenset(
    {"INLINE_MAX", "RESTRICTION_BITS_RESERVED", "TRANSIENT_FAILURE_CLASSES"}
)


def test_all_is_exactly_the_planned_inventory() -> None:
    """A T-CONTRACT surface changes only on a CONTRACT bump (18 section 9.3), so the
    inventory is asserted in both directions rather than sampled."""
    assert set(omniweave_ports.__all__) == PLANNED_EXPORTS | EXPORTED_CONSTANTS


def test_every_exported_name_resolves() -> None:
    for name in omniweave_ports.__all__:
        assert hasattr(omniweave_ports, name), name


def test_compile_v1_is_not_here() -> None:
    """`CompileV1` lives in `omniweave_core.out` because its signature mixes ports types with
    the OUT framework types a target is validated by, and a Protocol has to live in one
    distribution (02-architecture.md section 3.2 rule 4)."""
    assert "CompileV1" not in omniweave_ports.__all__
    assert not hasattr(omniweave_ports, "CompileV1")


def test_service_registry_is_not_here() -> None:
    """04-driver-system.md section 1.3: a `ServiceRegistry` symbol appearing in
    `omniweave_ports` is a defect, not a convenience."""
    assert not hasattr(omniweave_ports, "ServiceRegistry")


def test_no_host_side_routing_type_leaked_in() -> None:
    """`RankedGuess`, `Basis` and `TrustClass` are routing's and may never appear here
    (04-driver-system.md section 1.3, terminology.md rows for `Basis` and `RankedGuess`)."""
    for name in ("RankedGuess", "Basis", "TrustClass"):
        assert not hasattr(omniweave_ports, name), name


# --------------------------------------------------------------------------------------
# stdlib only, and no mutable value type
# --------------------------------------------------------------------------------------


def test_every_import_in_the_package_is_stdlib_or_self() -> None:
    """Mechanical, from the source text rather than from belief: D1 and INV-2 give this
    package zero third-party runtime dependencies (02-architecture.md section 2 row 1)."""
    offenders: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root != "omniweave_ports" and root not in sys.stdlib_module_names:
                    offenders.append(f"{path.name}: {root}")
    assert offenders == []


def _dataclasses() -> list[type]:
    return [
        obj
        for name in omniweave_ports.__all__
        if isinstance(obj := getattr(omniweave_ports, name), type)
        if dataclasses.is_dataclass(obj)
    ]


def test_no_dataclass_is_mutable() -> None:
    """Every value type is a frozen, slotted dataclass (18-api-sketch.md section 1)."""
    found = _dataclasses()
    assert len(found) >= 14
    for cls in found:
        assert cls.__dataclass_params__.frozen, cls.__name__
        assert cls.__dataclass_params__.slots, cls.__name__
        assert not hasattr(cls, "__dict__") or "__dict__" not in cls.__slots__, cls.__name__


def test_assignment_to_a_value_type_raises() -> None:
    hint = StreamHint(filename="a.txt", extension=".txt", declared_media_type=None, byte_len=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        hint.filename = "b.txt"  # type: ignore[misc]


def test_a_value_type_admits_no_extra_attribute() -> None:
    """`slots=True` is what makes an undeclared field unwritable rather than silently kept."""
    guess = FormatGuess(
        media_type="text/plain",
        format_token="txt",  # noqa: S106 — a format token, not a credential
        confidence=0.9,
        consumed_bytes=8,
    )
    assert not hasattr(guess, "basis")
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        guess.basis = "driver_sniff"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------
# the enums, member for member (charter.md D3)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_cls", "values"),
    [
        (Port, ["acquire", "parse", "derive", "embed", "compile"]),
        (CostClass, ["free", "local_compute", "billed_api"]),
        (Isolation, ["inproc", "subproc", "wasm"]),
        (ReplayClass, ["byte_exact", "seeded", "unpinnable"]),
        (TrustTier, ["first_party", "vendored", "pinned", "local", "unpinned"]),
        (LicenceTier, ["open", "restricted", "commercial", "forbidden"]),
        (ProbeStatus, ["ok", "degraded", "unavailable"]),
        (
            FailureClass,
            [
                "encrypted",
                "needs_ocr",
                "unsupported_format",
                "corrupt_input",
                "resource_limit",
                "too_large",
                "timeout",
                "upstream_unavailable",
                "rate_limited",
                "auth",
                "empty_result",
                "driver_crashed",
                "driver_bug",
            ],
        ),
        (
            ArtifactKind,
            [
                "raw_bytes",
                "roster_items",
                "doc_fragment",
                "graph_items",
                "witness_set",
                "vector_batch",
                "text_batch",
                "il_bundle",
                "asset",
                "artifact",
                "receipt",
                "carrier_doc",
                "diag",
            ],
        ),
    ],
)
def test_enum_membership_is_the_charters(enum_cls: type[enum.StrEnum], values: list[str]) -> None:
    """Wire values, in the charter's order. A StrEnum's value IS what crosses the wire."""
    assert [member.value for member in enum_cls] == values
    assert issubclass(enum_cls, str)


def test_the_artifact_kind_vocabulary_is_closed_at_thirteen() -> None:
    """Thirteen members, and no experimental namespace (04 section 2.3, E2)."""
    assert len(ArtifactKind) == 13


def test_restriction_is_an_int_enum_of_bit_positions() -> None:
    """32 codes reserved, twelve allocated, `bit = 1 << value` (charter.md D3)."""
    assert [member.value for member in Restriction] == list(range(12))
    assert RESTRICTION_BITS_RESERVED == 32
    assert all(member.bit == 1 << member.value for member in Restriction)
    assert Restriction.COMPETITOR_BAR.bit == 2


def test_restriction_spellings_match_their_card_facts() -> None:
    """charter.md D3: _EXCLUDED, not _BARRED, so every neighbouring pair matches its card
    fact exactly and the runner's fact-to-bit map special-cases no name."""
    assert Restriction.TERRITORY_EXCLUDED.name.lower() == "territory_excluded"
    assert Restriction.FIELD_OF_USE_EXCLUDED.name.lower() == "field_of_use_excluded"
    assert Restriction.COMPETITOR_BAR.name.lower() == "competitor_bar"


# --------------------------------------------------------------------------------------
# DriverError
# --------------------------------------------------------------------------------------


def test_driver_error_is_raisable_and_catchable() -> None:
    with pytest.raises(DriverError) as caught:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message="utf-8 decode failed at 12")
    assert caught.value.cls is FailureClass.CORRUPT_INPUT
    assert "corrupt_input" in str(caught.value)


def test_the_transient_set_is_the_classifier_tables() -> None:
    """08-runtime.md section 1.6: rate_limited, upstream_unavailable, driver-reported timeout
    and resource_limit are the transient verdicts. Only a driver builds a `DriverError`."""
    assert {
        FailureClass.RATE_LIMITED,
        FailureClass.UPSTREAM_UNAVAILABLE,
        FailureClass.TIMEOUT,
        FailureClass.RESOURCE_LIMIT,
    } == TRANSIENT_FAILURE_CLASSES


@pytest.mark.parametrize("cls", sorted(TRANSIENT_FAILURE_CLASSES))
def test_a_transient_class_requires_retry_after_ms(cls: FailureClass) -> None:
    """charter.md D3: REQUIRED iff transient, and __post_init__ raises."""
    with pytest.raises(ValueError, match="retry_after_ms"):
        DriverError(cls=cls, message="upstream is slow")
    assert DriverError(cls=cls, message="slow", retry_after_ms=0).retry_after_ms == 0


@pytest.mark.parametrize("cls", sorted(set(FailureClass) - set(TRANSIENT_FAILURE_CLASSES), key=str))
def test_a_permanent_class_refuses_retry_after_ms(cls: FailureClass) -> None:
    """The other half of "iff": a permanent failure with a cooldown would be retried."""
    assert DriverError(cls=cls, message="no").retry_after_ms is None
    with pytest.raises(ValueError, match="meaningless"):
        DriverError(cls=cls, message="no", retry_after_ms=100)


def test_needs_ocr_carries_pages_and_resource_limit_carries_a_knob() -> None:
    """`NEEDS_OCR` is routing data, not a failure; `RESOURCE_LIMIT` names WHICH knob would
    need raising (charter.md D3)."""
    ocr = DriverError(cls=FailureClass.NEEDS_OCR, message="no text layer", pages=(3, 4))
    assert ocr.pages == (3, 4)
    limited = DriverError(
        cls=FailureClass.RESOURCE_LIMIT,
        message="page cover map",
        retry_after_ms=60_000,
        limit="max_grid_slots",
    )
    assert limited.limit == "max_grid_slots"


# --------------------------------------------------------------------------------------
# DriverIO, DriverMetrics, DriverResult
# --------------------------------------------------------------------------------------


def test_driver_io_has_exactly_four_fields() -> None:
    """INV-6's audit question is "count `DriverIO`'s fields" (01-principles.md section 12
    row 2). Adding one amends the charter."""
    assert [f.name for f in dataclasses.fields(DriverIO)] == [
        "blobs",
        "tmpdir",
        "deadline_ms",
        "max_output_bytes",
    ]


def test_driver_io_carries_no_store_cache_ledger_or_writable_root() -> None:
    names = {f.name for f in dataclasses.fields(DriverIO)}
    for forbidden in (
        "store",
        "cache",
        "ledger",
        "budget",
        "ctx",
        "output_root",
        "cache_root",
        "sink",
        "socket",
    ):
        assert forbidden not in names


def test_driver_metrics_carries_no_price() -> None:
    """charter.md D3, INV-15: PHYSICAL UNITS ONLY, and `cost_micros` is DELETED."""
    names = [f.name for f in dataclasses.fields(DriverMetrics)]
    assert names == [
        "wall_ms",
        "cpu_ms",
        "gpu_ms",
        "tokens_in",
        "tokens_out",
        "calls",
        "bytes_egress",
        "bytes_read",
        "peak_rss_bytes",
    ]
    assert not [n for n in names if "micro" in n or "cost" in n or "price" in n]
    assert DriverMetrics() == DriverMetrics(wall_ms=0)


def test_driver_result_cannot_claim_what_only_the_runner_writes() -> None:
    """`DriverResult` is STRICTLY SMALLER than `StepResult` (INV-7, 08 section 1.3)."""
    names = {f.name for f in dataclasses.fields(DriverResult)}
    assert names == {"outcome", "produced", "partial_reason", "metrics"}
    for forbidden in (
        "was_cache_hit",
        "confidence",
        "restriction_bits",
        "trust",
        "identity",
        "cache_key",
        "producer_id",
        "origin_driver",
        "micros",
        "degradations",
    ):
        assert forbidden not in names


def test_driver_result_outcome_is_ok_or_ok_partial_and_nothing_else() -> None:
    assert DriverResult(outcome="ok", produced=()).metrics == DriverMetrics()
    with pytest.raises(ValueError, match="not one of"):
        DriverResult(outcome="skipped_cached", produced=())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not one of"):
        DriverResult(outcome="cancelled", produced=())  # type: ignore[arg-type]


def test_ok_partial_requires_a_partial_reason() -> None:
    """08-runtime.md section 1.3's `Outcome` table: "usable but incomplete; partial_reason
    required", enforced in the constructor rather than in review."""
    with pytest.raises(ValueError, match="partial_reason"):
        DriverResult(outcome="ok_partial", produced=())
    assert DriverResult(outcome="ok_partial", produced=(), partial_reason="pages 4-9 encrypted")


# --------------------------------------------------------------------------------------
# detect.py — the two shapes with a deliberately absent field each
# --------------------------------------------------------------------------------------


def test_format_guess_is_four_fields_and_carries_no_basis() -> None:
    """Four fields and no more (04 section 1.3): `basis` is the HOST's classification of how
    a guess was obtained and lives on `RankedGuess`, host-side."""
    assert [f.name for f in dataclasses.fields(FormatGuess)] == [
        "media_type",
        "format_token",
        "confidence",
        "consumed_bytes",
    ]


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0, float("nan")])
def test_format_guess_confidence_outside_the_unit_interval_raises(confidence: float) -> None:
    """18-api-sketch.md section 5.1 rule 2: __post_init__ raises outside [0.0, 1.0]."""
    with pytest.raises(ValueError, match="confidence"):
        FormatGuess(
            media_type="text/plain",
            format_token="txt",  # noqa: S106 — a format token, not a credential
            confidence=confidence,
            consumed_bytes=0,
        )


@pytest.mark.parametrize("confidence", [0.0, 0.4, 0.95, 1.0])
def test_the_unit_interval_is_inclusive(confidence: float) -> None:
    assert (
        FormatGuess(
            media_type="text/plain",
            format_token="txt",  # noqa: S106 — a format token, not a credential
            confidence=confidence,
            consumed_bytes=8192,
        ).confidence
        == confidence
    )


def test_stream_hint_is_four_fields_and_carries_no_trust_class() -> None:
    """`omniweave_ports`' layers.toml row is [], so a `trust_class` field would pull
    routing's `TrustClass` across the layer boundary G4 closes (04 section 1.3)."""
    assert [f.name for f in dataclasses.fields(StreamHint)] == [
        "filename",
        "extension",
        "declared_media_type",
        "byte_len",
    ]


def test_stream_hint_admits_an_unknown_length() -> None:
    hint = StreamHint(
        filename=None, extension=None, declared_media_type="application/pdf", byte_len=None
    )
    assert hint.byte_len is None


# --------------------------------------------------------------------------------------
# the remaining printed shapes
# --------------------------------------------------------------------------------------


def test_probe_env_is_what_probe_is_allowed_to_know() -> None:
    """No writable path, no network handle, no config (04 section 1.3)."""
    names = [f.name for f in dataclasses.fields(ProbeEnv)]
    assert names == ["platform", "machine", "python", "which", "gpu_present", "vram_gb", "offline"]
    env = ProbeEnv(
        platform="linux",
        machine="x86_64",
        python=(3, 11),
        which={"tesseract": None},
        gpu_present=False,
        vram_gb=0.0,
        offline=True,
    )
    assert env.which["tesseract"] is None


def test_probe_verdict_names_the_missing_thing() -> None:
    verdict = ProbeVerdict(
        status=ProbeStatus.UNAVAILABLE,
        detail="tesseract German data not installed",
        missing=("tesseract-lang:deu",),
        fix_hint="apt install tesseract-ocr-deu",
    )
    assert verdict.capabilities_lost == ()
    assert ProbeVerdict(status=ProbeStatus.OK, detail="stdlib codecs only").missing == ()


def test_unit_ref_mints_no_identity() -> None:
    """NO unit_id, NO doc_ord, NO block_id: the host mints every durable identity
    (charter.md section 5 X1)."""
    names = {f.name for f in dataclasses.fields(UnitRef)}
    assert names == {"uri", "part", "content_sha256", "byte_len", "media_type"}
    for forbidden in ("unit_id", "doc_ord", "block_id", "segment_id", "entity_id"):
        assert forbidden not in names


def test_locator_and_part_selector_defaults() -> None:
    assert Locator(scheme="file", target="/corpus").cursor is None
    assert Locator(scheme="file", target="/corpus").since_ns is None
    assert PartSelector() == PartSelector(pages=(), parts=())


def test_derive_scope_carries_the_containment_boundary() -> None:
    scope = DeriveScope(
        lane="claims",
        units=(UnitRef(uri="file:///a", part="", content_sha256="ab", byte_len=2),),
        allowed_cites=frozenset({"cite:1"}),
    )
    assert scope.schema is None
    assert scope.corpus_vocab == ()
    assert "cite:1" in scope.allowed_cites


def test_text_batch_and_embed_manifest() -> None:
    batch = TextBatch(texts=("a", "b"), role="query")
    assert batch.role == "query"
    manifest = EmbedManifest(
        dim=768,
        metric="cosine",
        normalization="l2",
        model_id="bge-base",
        model_revision="0c1a2b3c4d5e6f",
        max_tokens=512,
    )
    assert manifest.dim == 768
    assert manifest.model_revision != "main"


def test_inline_max_is_the_charters_number() -> None:
    """charter.md section 6.10 and 03-document-model.md section 14's limits table."""
    assert INLINE_MAX == 262_144
