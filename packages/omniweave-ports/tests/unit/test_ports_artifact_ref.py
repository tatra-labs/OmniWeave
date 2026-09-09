"""`ArtifactRef` — the one place the per-invocation output ceiling is enforced.

`ArtifactRef.of` "meters the running total per invocation against `io.max_output_bytes`, so
100 blobs of 1 MB each under a 4 MB ceiling raise `TOO_LARGE` on the put that crosses it —
enforced in ports, on the host's number, not by the driver's own check"
(04-driver-system.md section 6.5). That sentence is the hostile-driver mechanism for
"many small blobs to evade the output ceiling", so it is tested with many small blobs.

Specified in 04-driver-system.md sections 1.3 and 6.5.
"""

from __future__ import annotations

import hashlib
import io as _io
from typing import BinaryIO

import pytest
from omniweave_ports import (
    INLINE_MAX,
    ArtifactKind,
    ArtifactRef,
    DriverError,
    DriverIO,
    FailureClass,
)

MIB = 1_048_576


class RecordingBlobStore:
    """A `BlobStore` that keeps everything in memory and counts its puts."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.puts = 0

    def path(self, digest: str) -> str:
        return f"/cas/{digest}"

    def open(self, digest: str) -> BinaryIO:
        return _io.BytesIO(self.blobs[digest])

    def put(self, data: bytes) -> str:
        self.puts += 1
        digest = hashlib.sha256(data).hexdigest()
        self.blobs[digest] = data
        return digest


def make_io(max_output_bytes: int = 32 * MIB) -> DriverIO:
    return DriverIO(
        blobs=RecordingBlobStore(),
        tmpdir="ow-tmp/invocation",
        deadline_ms=30_000,
        max_output_bytes=max_output_bytes,
    )


# --------------------------------------------------------------------------------------
# the shape
# --------------------------------------------------------------------------------------


def test_exactly_one_of_inline_and_blob_is_set() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ArtifactRef(kind="doc_fragment", byte_len=0)
    with pytest.raises(ValueError, match="exactly one"):
        ArtifactRef(kind="doc_fragment", byte_len=3, inline=b"abc", blob="cas://ab")


def test_kind_is_a_member_of_the_closed_vocabulary() -> None:
    """ "A card declaring a member outside the set is CARD_INVALID naming the member"
    (04 section 2.3); the same closure applies to what a driver puts on the wire."""
    with pytest.raises(ValueError, match="artifact-kind"):
        ArtifactRef(kind="doc-fragment", byte_len=1, inline=b"x")
    assert ArtifactRef(kind=ArtifactKind.DIAG, byte_len=1, inline=b"x").kind == "diag"


def test_byte_len_must_match_an_inline_body() -> None:
    with pytest.raises(ValueError, match="byte_len"):
        ArtifactRef(kind="doc_fragment", byte_len=2, inline=b"abc")


def test_a_blob_reference_is_spelled_cas() -> None:
    with pytest.raises(ValueError, match="cas://"):
        ArtifactRef(kind="artifact", byte_len=INLINE_MAX + 1, blob="deadbeef")


def test_an_inline_body_may_not_exceed_inline_max() -> None:
    with pytest.raises(ValueError, match="INLINE_MAX"):
        ArtifactRef(kind="artifact", byte_len=INLINE_MAX + 1, inline=b"\x00" * (INLINE_MAX + 1))


# --------------------------------------------------------------------------------------
# of() — inline below the line, a blob above it
# --------------------------------------------------------------------------------------


def test_of_inlines_a_body_at_or_under_inline_max() -> None:
    driver_io = make_io()
    body = b'{"t":"block"}\n' * 8
    ref = ArtifactRef.of("doc_fragment", body, driver_io)
    assert ref.inline == body
    assert ref.blob is None
    assert ref.byte_len == len(body)
    assert driver_io.blobs.puts == 0


def test_of_inlines_exactly_at_the_boundary() -> None:
    driver_io = make_io()
    ref = ArtifactRef.of("artifact", b"\x00" * INLINE_MAX, driver_io)
    assert ref.inline is not None
    assert driver_io.blobs.puts == 0


def test_of_puts_a_blob_one_byte_over_the_boundary() -> None:
    driver_io = make_io()
    body = b"\x00" * (INLINE_MAX + 1)
    ref = ArtifactRef.of("artifact", body, driver_io)
    assert ref.inline is None
    assert ref.blob is not None
    assert ref.blob.startswith("cas://")
    assert ref.byte_len == INLINE_MAX + 1
    assert driver_io.blobs.puts == 1


# --------------------------------------------------------------------------------------
# of() — the ceiling, metered once, on the running total
# --------------------------------------------------------------------------------------


def test_a_single_oversized_body_is_too_large_and_names_the_knob() -> None:
    driver_io = make_io(max_output_bytes=1024)
    with pytest.raises(DriverError) as caught:
        ArtifactRef.of("doc_fragment", b"\x00" * 1025, driver_io)
    assert caught.value.cls is FailureClass.TOO_LARGE
    assert caught.value.limit == "max_output_bytes"
    assert caught.value.retry_after_ms is None


def test_many_small_blobs_cannot_evade_the_ceiling() -> None:
    """04-driver-system.md section 6.5, the hostile-driver row, verbatim: 100 blobs of 1 MB
    each under a 4 MB ceiling raise TOO_LARGE on the put that crosses it."""
    driver_io = make_io(max_output_bytes=4 * MIB)
    one_mib = b"\x00" * MIB
    written = 0
    with pytest.raises(DriverError) as caught:
        for _ in range(100):
            ArtifactRef.of("asset", one_mib, driver_io)
            written += 1
    assert written == 4
    assert caught.value.cls is FailureClass.TOO_LARGE
    assert caught.value.limit == "max_output_bytes"


def test_the_crossing_body_is_never_written() -> None:
    """The ceiling is charged BEFORE the put, so a refused body leaves no blob behind."""
    driver_io = make_io(max_output_bytes=INLINE_MAX + 8)
    ArtifactRef.of("asset", b"\x00" * 8, driver_io)
    with pytest.raises(DriverError):
        ArtifactRef.of("asset", b"\x00" * (INLINE_MAX + 1), driver_io)
    assert driver_io.blobs.puts == 0


def test_the_meter_is_per_invocation() -> None:
    """A second invocation gets a fresh DriverIO and therefore a fresh running total."""
    first = make_io(max_output_bytes=1024)
    ArtifactRef.of("asset", b"\x00" * 1024, first)
    with pytest.raises(DriverError):
        ArtifactRef.of("asset", b"\x00", first)
    second = make_io(max_output_bytes=1024)
    assert ArtifactRef.of("asset", b"\x00" * 1024, second).byte_len == 1024


def test_an_empty_body_is_admitted_and_charged_nothing() -> None:
    driver_io = make_io(max_output_bytes=0)
    ref = ArtifactRef.of("diag", b"", driver_io)
    assert ref.byte_len == 0
    assert ref.inline == b""


# --------------------------------------------------------------------------------------
# head()
# --------------------------------------------------------------------------------------


def test_head_slices_an_inline_body() -> None:
    ref = ArtifactRef.of("doc_fragment", b'{"t":"block"}\n', make_io())
    assert ref.head(6) == b'{"t":"'
    assert ref.head(0) == b""
    assert ref.head(10_000) == b'{"t":"block"}\n'


def test_head_answers_for_a_blob_backed_ref_built_by_of() -> None:
    """`is_valid_nonempty(ref)` is `ref.head(65_536)` on a ref the driver just returned
    (18-api-sketch.md section 5.2), and most real fragments are over INLINE_MAX."""
    body = b'{"t":"doc"}\n' + b"\x00" * INLINE_MAX
    ref = ArtifactRef.of("doc_fragment", body, make_io())
    assert ref.blob is not None
    assert ref.head(11) == b'{"t":"doc"}'
    assert b'"t":"doc"' in ref.head(65_536)


def test_head_on_a_blob_ref_built_elsewhere_says_so() -> None:
    """A ref decoded off the wire holds no bytes and no BlobStore; reporting an empty body
    would turn a readable fragment into FAILED_PERMANENT(EMPTY_RESULT)."""
    ref = ArtifactRef(kind="doc_fragment", byte_len=INLINE_MAX + 1, blob="cas://" + "ab" * 32)
    with pytest.raises(DriverError) as caught:
        ref.head(16)
    assert caught.value.cls is FailureClass.DRIVER_BUG


def test_head_refuses_a_negative_window() -> None:
    ref = ArtifactRef(kind="diag", byte_len=1, inline=b"x")
    with pytest.raises(ValueError, match="non-negative"):
        ref.head(-1)
