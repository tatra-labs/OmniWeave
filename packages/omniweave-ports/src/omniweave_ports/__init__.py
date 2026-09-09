"""The driver-facing type surface: Port, CostClass, Isolation, ReplayClass, TrustTier,
LicenceTier, Restriction, FailureClass, DriverError, ProbeStatus, ProbeVerdict,
DriverIO, DriverMetrics, DriverResult, and the AcquireV1 / ParseV1 / DeriveV1 /
EmbedV1 protocols. No behaviour: not one function here has a side effect.

The whole third-party surface, ~40 KB of pure typing, stdlib only, and the one distribution
with no first-party dependency of its own. An `acquire`/`parse`/`derive`/`embed` driver's
ONLY permitted omniweave imports are this package and, dev-only, `omniweave_conform.testkit`;
it never depends on `omniweave-core`. `CompileV1` is the exception and lives in
`omniweave_core.out`, because its signature needs the framework types a target is validated
by. This package is versioned by PORT MAJOR, not by RELEASE, which is why a core upgrade is
never blocked by a driver's resolver constraint.

Specified in 02-architecture.md section 2 row 1 and 04-driver-system.md section 1.3.
"""

from omniweave_ports.base import DriverBase
from omniweave_ports.detect import FormatGuess, StreamHint
from omniweave_ports.ports import AcquireV1, DeriveV1, EmbedV1, ParseV1
from omniweave_ports.types import (
    INLINE_MAX,
    RESTRICTION_BITS_RESERVED,
    TRANSIENT_FAILURE_CLASSES,
    ArtifactKind,
    ArtifactRef,
    BlobStore,
    CostClass,
    DeriveScope,
    DriverError,
    DriverIO,
    DriverMetrics,
    DriverResult,
    EmbedManifest,
    FailureClass,
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
    Scalar,
    ServiceHandle,
    TextBatch,
    TrustTier,
    UnitRef,
)

__all__ = [
    "INLINE_MAX",
    "RESTRICTION_BITS_RESERVED",
    "TRANSIENT_FAILURE_CLASSES",
    "AcquireV1",
    "ArtifactKind",
    "ArtifactRef",
    "BlobStore",
    "CostClass",
    "DeriveScope",
    "DeriveV1",
    "DriverBase",
    "DriverError",
    "DriverIO",
    "DriverMetrics",
    "DriverResult",
    "EmbedManifest",
    "EmbedV1",
    "FailureClass",
    "FormatGuess",
    "Isolation",
    "LicenceTier",
    "Locator",
    "ParseV1",
    "PartSelector",
    "Port",
    "ProbeEnv",
    "ProbeStatus",
    "ProbeVerdict",
    "ReplayClass",
    "Restriction",
    "Scalar",
    "ServiceHandle",
    "StreamHint",
    "TextBatch",
    "TrustTier",
    "UnitRef",
]
