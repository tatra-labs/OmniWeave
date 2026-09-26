"""`pipeline.inproc_host`: seam S1 at the bottom of the chain, over a real `DriverGuard`.

The guard is built from a real `Candidate`: `resolve()` over the shipped catalog with the office
driver as a released build carries it (conftest's `released_catalog`), so DR9's six conjuncts
hold and `resolve()` itself grants `inproc`. Nothing below forges clearance; the work each unit
does is the test's.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from omniweave.run import pipeline
from omniweave.run.dispatch import Batch
from omniweave.run.routing import PORT, resolve_policy
from omniweave_core.blobs import format_ref
from omniweave_core.config import Config, load
from omniweave_core.discovery import catalog
from omniweave_core.drivers.catalog import Catalog
from omniweave_core.drivers.resolve import Candidate, Requirement, resolve
from omniweave_core.host.inproc import DRIVER, HOST, Deadlines, DriverGuard
from omniweave_core.host.subproc import BatchEvent
from omniweave_core.operator import Outcome
from omniweave_core.work import WORK_COLUMNS, WorkRow
from omniweave_ports.types import (
    ArtifactRef,
    BlobStore,
    DriverError,
    DriverIO,
    DriverResult,
    FailureClass,
    Isolation,
    UnitRef,
)

OFFICE = "parse.office.anydoc"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\n"
)


def _config(tmp_path: Path) -> Config:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    return load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})


def _candidate(config: Config, found: Catalog) -> Candidate | None:
    resolution = resolve(Requirement(port=PORT, format=DOCX), found, resolve_policy(config))
    return next((one for one in resolution.candidates if one.driver_id == OFFICE), None)


@pytest.fixture
def granted(tmp_path: Path, released_catalog: Catalog) -> Candidate:
    candidate = _candidate(_config(tmp_path), released_catalog)
    assert candidate is not None
    return candidate


class _Blobs:
    """A `BlobStore` the work never opens and the host may put into: the units here are the
    test's, and `put` is where the host moves an inline ref the frame rule does not keep."""

    def __init__(self) -> None:
        self.put_bytes: list[bytes] = []

    def open(self, digest: str) -> object:
        raise AssertionError(f"no unit here reads a blob, and {digest} was opened")

    def path(self, digest: str) -> str:
        raise AssertionError(digest)

    def put(self, data: bytes) -> str:
        self.put_bytes.append(data)
        return format_ref(hashlib.sha256(data).digest())


class _Source:
    """A `GuardSource` whose per-unit work is a list of callables, and which records scratch."""

    def __init__(self, guard: DriverGuard, works: list[object], tmp: Path) -> None:
        self._guard = guard
        self._works = works
        self._tmp = tmp
        self.scratch: list[str] = []
        self.store = _Blobs()

    def guard(self, call: pipeline.Call) -> DriverGuard:
        del call
        return self._guard

    def work(self, call: pipeline.Call, index: int) -> object:
        del call
        chosen = self._works[index]

        def run(io: DriverIO) -> DriverResult:
            assert not any(Path(one).exists() for one in self.scratch), "removed before the next"
            self.scratch.append(io.tmpdir)
            assert Path(io.tmpdir).is_dir(), "each unit gets its scratch before its call"
            return chosen(io)  # type: ignore[operator]

        return run

    def blobs(self, call: pipeline.Call) -> BlobStore:
        del call
        return self.store  # type: ignore[return-value]

    def tmp(self, call: pipeline.Call) -> Path:
        del call
        return self._tmp

    def max_output_bytes(self, call: pipeline.Call) -> int:
        del call
        return 1 << 20


def _row(index: int) -> WorkRow:
    """One claimed `parse.office` row, every column present -- `test_run_dispatch.row()`'s way,
    built from `WORK_COLUMNS` so a migration breaks it rather than this file."""
    values: dict[str, object] = {}
    values.update(dict.fromkeys(WORK_COLUMNS))
    values.update(
        id=index + 1,
        unit_uri=f"file:///u{index}.docx",
        unit_part="",
        operator="parse.office",
        op_version=1,
        cache_key="c" * 64,
        decision_id=f"dec_{index}",
        driver=OFFICE,
        cost_class="free",
        dispatch_key="k",
        status="claimed",
        attempts_total=1,
        attempts_today=1,
        cost_micros=0,
        queued_ms=0,
        ran_ms=0,
        peak_rss_bytes=0,
        priority=0,
    )
    return WorkRow.from_row(tuple(values[name] for name in WORK_COLUMNS))


def _call(size: int) -> pipeline.Call:
    rows = tuple(_row(index) for index in range(size))
    units = tuple(
        UnitRef(uri=row.unit_uri, part="", content_sha256="0" * 64, byte_len=1, media_type=DOCX)
        for row in rows
    )
    return pipeline.Call(
        batch=Batch(invoke_id="inv", rows=rows), units=units, operator="parse.office"
    )


def _ok(io: DriverIO) -> DriverResult:
    return DriverResult(outcome="ok", produced=(ArtifactRef.of("doc_fragment", b"{}", io),))


def test_resolve_grants_the_released_office_driver_inproc_and_refuses_the_editable_one(
    tmp_path: Path, released_catalog: Catalog
) -> None:
    """The precondition every other test here stands on, stated: the same card under the shipped
    `[drivers] inproc` is refused on a checkout and granted `inproc` as a release -- and
    `resolve()`, not this file, is what decides both (DR9, D576, D599)."""
    config = _config(tmp_path)
    policy = resolve_policy(config)
    editable = resolve(Requirement(port=PORT, format=DOCX), catalog(), policy)
    assert not any(one.driver_id == OFFICE for one in editable.candidates)
    (refused,) = (one for one in editable.rejected if one.driver_id == OFFICE)
    assert str(refused.code) == "trust_insufficient"
    released = _candidate(config, released_catalog)
    assert released is not None
    assert released.isolation_granted is Isolation.INPROC


def test_each_unit_answers_in_order_with_s4_s_reply_shape(
    granted: Candidate, tmp_path: Path
) -> None:
    """One outcome per unit (I24), `produced` per unit, and an `InvokeReport` whose failures are
    `HostVerdict`s: the three a driver can end in, side by side -- a result, a transient failure
    it reported with a cooldown, and a raise the guard turns into `driver_bug`."""

    def transient(_io: DriverIO) -> DriverResult:
        raise DriverError(cls=FailureClass.RATE_LIMITED, message="slow down", retry_after_ms=250)

    def bug(_io: DriverIO) -> DriverResult:
        raise KeyError("oops")

    guard = DriverGuard(granted, deadlines=Deadlines())
    source = _Source(guard, [_ok, transient, bug], tmp_path)
    reply = pipeline.inproc_host(source)(_call(3))  # type: ignore[arg-type]
    assert reply.outcomes == (Outcome.OK, Outcome.FAILED_TRANSIENT, Outcome.FAILED_PERMANENT)
    assert [ref.kind for ref in reply.produced[0]] == ["doc_fragment"]
    assert reply.produced[1:] == ((), ())
    assert reply.report is not None
    ok, slow, broken = reply.report.failures
    assert ok is None
    assert slow is not None and broken is not None
    assert (slow.failure_class, slow.permanent, slow.retry_after_ms) == (
        FailureClass.RATE_LIMITED,
        False,
        250,
    )
    assert slow.detected_by == DRIVER
    assert (broken.failure_class, broken.permanent, broken.detected_by) == (
        FailureClass.DRIVER_BUG,
        True,
        HOST,
    )
    assert reply.report.event is BatchEvent.CLEAN


def test_a_host_detected_timeout_is_permanent_and_names_its_limit(
    granted: Candidate, tmp_path: Path
) -> None:
    """04:1728's `FAILED_PERMANENT{TIMEOUT}`: the guard's own verdict has no cooldown to give, so
    it is permanent -- where the same class reported by a driver would be transient."""
    ticks = iter(range(0, 10**12, 10**9))
    guard = DriverGuard(
        granted, deadlines=Deadlines(wall_ms_hard=1_500), monotonic_ns=lambda: next(ticks)
    )
    reply = pipeline.inproc_host(_Source(guard, [_ok], tmp_path))(_call(1))  # type: ignore[arg-type]
    assert reply.outcomes == (Outcome.FAILED_PERMANENT,)
    assert reply.report is not None
    (verdict,) = reply.report.failures
    assert verdict is not None
    assert (verdict.failure_class, verdict.limit, verdict.detected_by) == (
        FailureClass.TIMEOUT,
        "wall_ms_hard",
        HOST,
    )


def test_a_resource_limit_is_the_batch_event_and_scratch_is_gone(
    granted: Candidate, tmp_path: Path
) -> None:
    """AIMD's one arm an in-process batch can reach, and the worker's scratch order: each unit's
    directory exists for its call and is gone after it, and so is the invocation's root."""

    def limited(_io: DriverIO) -> DriverResult:
        raise DriverError(
            cls=FailureClass.RESOURCE_LIMIT,
            message="too deep",
            retry_after_ms=1_000,
            limit="max_depth",
        )

    source = _Source(DriverGuard(granted, deadlines=Deadlines()), [_ok, limited], tmp_path)
    reply = pipeline.inproc_host(source)(_call(2))  # type: ignore[arg-type]
    assert reply.report is not None
    assert reply.report.event is BatchEvent.RESOURCE_LIMIT
    assert len(source.scratch) == 2
    assert not any(Path(one).exists() for one in source.scratch)
    assert not (tmp_path / "inv").exists()


def test_produced_is_the_shape_a_result_frame_carries(granted: Candidate, tmp_path: Path) -> None:
    """`worker.produced_header`'s rule, applied in process: the first `doc_fragment` stays inline
    and every other inline ref goes to the CAS, in order -- so the Operator reads one shape from
    both seams. An in-process driver's small asset would otherwise reach the fragment decoder
    inline, where S4 never sends one."""

    def two(io: DriverIO) -> DriverResult:
        fragment = ArtifactRef.of("doc_fragment", b'{"t":"page"}', io)
        asset = ArtifactRef.of("asset", b"PNG", io)
        return DriverResult(outcome="ok", produced=(fragment, asset))

    source = _Source(DriverGuard(granted, deadlines=Deadlines()), [two], tmp_path)
    reply = pipeline.inproc_host(source)(_call(1))  # type: ignore[arg-type]
    (fragment, asset) = reply.produced[0]
    assert (fragment.kind, fragment.inline, fragment.blob) == (
        "doc_fragment",
        b'{"t":"page"}',
        None,
    )
    assert (asset.kind, asset.inline, asset.byte_len) == ("asset", None, 3)
    assert asset.blob == format_ref(hashlib.sha256(b"PNG").digest())
    assert source.store.put_bytes == [b"PNG"]
