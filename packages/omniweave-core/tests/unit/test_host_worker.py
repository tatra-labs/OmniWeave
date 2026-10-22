"""`host/worker`: the S4 worker's own half -- the bootstrap, the hook, one `RESULT` per unit.

Three layers of test, cheapest first. The pure pieces (`egress_refusal`, `Session.of`,
`produced_header`, the failure header) are called directly. `serve()` is driven over a
`socket.socketpair()` in this process, with the real office card and a guard that RECORDS its arming
-- because an audit hook cannot be removed, and a test runner with one armed could not open its own
sockets afterwards. The hook itself, and the whole host-to-worker conversation through
`subproc.launch()`, are each exercised in a real child process.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import socket
import subprocess  # noqa: TID251 -- two tests run a real child
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_core.blobs import BlobStore, format_ref
from omniweave_core.discovery import catalog
from omniweave_core.drivers.card import load_card, read_card_bytes
from omniweave_core.errors import DriverHostError
from omniweave_core.events import traceparent
from omniweave_core.host import subproc as sp
from omniweave_core.host import wire
from omniweave_core.host import worker as wk

#  At module scope, every module whose errors a worker catches: `test_errors.py` reloads
#  `omniweave_core.errors`, and a module first imported after that raises classes the
#  worker's `except OwError` was not bound to, in whatever order xdist deals the files (D777).
from omniweave_core.modelserver import Handle
from omniweave_core.out import agentdoc
from omniweave_core.out.agentdoc import load_table
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.card import CompileCard
from omniweave_core.out.compile import refusal_of
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle, job_unit, scaffold
from omniweave_core.out.receipt import Receipt
from omniweave_ports.types import ArtifactRef, DeriveScope, DriverError, FailureClass, UnitRef

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures"
OFFICE = "parse.office.anydoc"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPO = Path(__file__).resolve().parents[4]


def _card() -> Any:
    card = catalog().cards.get(OFFICE)
    if card is None:  # pragma: no cover -- the workspace installs omniweave-office
        pytest.skip("parse.office.anydoc is not installed")
    return card


def _hello(tmp_path: Path, **overrides: object) -> dict[str, object]:
    card = _card()
    (tmp_path / "tmp").mkdir(exist_ok=True)
    (tmp_path / "cas").mkdir(exist_ok=True)
    header: dict[str, object] = {
        "port": "parse/1",
        "card_schema": card.card_schema,
        "card_sha256": card.card_sha256,
        "driver_id": OFFICE,
        "effective_config": {},
        "roots": {"source_ro": str(tmp_path), "tmp": str(tmp_path / "tmp")},
        "blob_base": str(tmp_path / "cas"),
        "isolation_granted": {"mode": "subproc"},
        "traceparent": "",
        "max_output_bytes": 64 * 1_048_576,
        "egress_mode": "granted",
    }
    header.update(overrides)
    return header


# ---------------------------------------------------------------------------------------------
# 1. the pure pieces
# ---------------------------------------------------------------------------------------------


def test_the_armed_hook_refuses_the_two_egress_events_and_nothing_else() -> None:
    assert wk.egress_refusal("socket.connect", armed=True) is not None
    assert wk.egress_refusal("socket.getaddrinfo", armed=True) is not None
    assert wk.egress_refusal("open", armed=True) is None, "the S4 pipe is an open(), not egress"
    assert wk.egress_refusal("socket.connect", armed=False) is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"roots": None}, "no roots table"),
        ({"roots": {"source_ro": "x"}}, "HELLO tmp"),
        ({"max_output_bytes": 0}, "max_output_bytes"),
        ({"max_output_bytes": True}, "max_output_bytes"),
        ({"driver_id": ""}, "driver_id"),
        ({"effective_config": [1]}, "effective_config"),
        ({"card_source": "driver.toml"}, "card_origin"),
        ({"card_source": "", "card_origin": "driver_path"}, "card_source"),
    ],
)
def test_a_hello_missing_what_the_worker_acts_on_is_refused(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    with pytest.raises(DriverHostError, match=message):
        wk.Session.of(_hello(tmp_path, **change))


def test_one_fragment_rides_inline_and_every_other_inline_ref_goes_to_the_cas(
    tmp_path: Path,
) -> None:
    """D583: :1674's frame has one body. The first inline `doc_fragment` keeps it; an inline
    asset, and a SECOND inline fragment, are put in the CAS; a blob ref passes through."""
    cas = BlobStore(tmp_path)
    blobs = wk.WorkerBlobs(cas)
    fragment = ArtifactRef(kind="doc_fragment", byte_len=3, inline=b"abc")
    asset = ArtifactRef(kind="asset", byte_len=2, inline=b"xy")
    second = ArtifactRef(kind="doc_fragment", byte_len=1, inline=b"z")
    stored = ArtifactRef(kind="asset", byte_len=9, blob="cas://" + "0" * 64)
    entries, body = wk.produced_header((fragment, asset, second, stored), blobs)
    assert body == b"abc"
    assert entries[0] == {"kind": "doc_fragment", "byte_len": 3, "inline": True}
    assert entries[1] == {
        "kind": "asset",
        "byte_len": 2,
        "blob": format_ref(hashlib.sha256(b"xy").digest()),
    }
    assert entries[2]["blob"] == format_ref(hashlib.sha256(b"z").digest())
    assert entries[3] == {"kind": "asset", "byte_len": 9, "blob": "cas://" + "0" * 64}
    assert cas.has(hashlib.sha256(b"xy").digest())


def test_a_units_content_digest_resolves_to_its_blob_ref(tmp_path: Path) -> None:
    """The driver opens its input by `content_sha256`, which is over NORMALISED bytes; the CAS
    names the raw bytes. The `INVOKE` unit's `blob_ref` is the alias between the two."""
    cas = BlobStore(tmp_path)
    raw = hashlib.sha256(b"raw bytes").digest()
    with (tmp_path / "raw.bin").open("wb") as out:
        out.write(b"raw bytes")
    with (tmp_path / "raw.bin").open("rb") as source:
        assert cas.put(source) == raw
    blobs = wk.WorkerBlobs(cas, {"n" * 64: format_ref(raw)})
    with blobs.open("n" * 64) as handle:
        assert handle.read() == b"raw bytes"


def test_a_failure_header_is_02_1060s_five_fields_with_a_bounded_message() -> None:
    error = DriverError(
        cls=FailureClass.RESOURCE_LIMIT, message="x" * 10_000, retry_after_ms=5, limit="depth"
    )
    header = wk.failure_header("inv", 2, error)
    assert header["failure_class"] == "resource_limit"
    assert header["unit_index"] == 2
    assert header["limit"] == "depth"
    assert len(str(header["message"])) == wk.MESSAGE_MAX_CHARS


# ---------------------------------------------------------------------------------------------
# 2. serve(), over a socketpair, in this process
# ---------------------------------------------------------------------------------------------


_OPEN: list[socket.socket] = []
"""Every socket `_serve` opened, closed after each test: the suite turns a ResourceWarning into
an error, and a socketpair end left open is exactly that."""


@pytest.fixture(autouse=True)
def _close_sockets() -> Any:
    yield
    while _OPEN:
        _OPEN.pop().close()


class _Host:
    """The host's end of a `socketpair`, speaking the frame grammar through `wire` itself."""

    def __init__(self, sock: socket.socket) -> None:
        self._channel = sp.SocketChannel(sock)

    def send(self, kind: wire.FrameKind, header: dict[str, object], body: bytes = b"") -> None:
        self._channel.sendall(wire.encode(kind, header, body))  # type: ignore[arg-type]

    def next(self) -> wire.Frame:
        frame = sp.next_frame(self._channel)
        assert frame is not None
        return frame

    def until(self, kind: wire.FrameKind, count: int = 1) -> list[wire.Frame]:
        seen: list[wire.Frame] = []
        while len(seen) < count:
            frame = self.next()
            if frame.kind is kind:
                seen.append(frame)
        return seen


def _serve(
    monkeypatch: pytest.MonkeyPatch, *, find_card: Any = None
) -> tuple[_Host, dict[str, Any], threading.Thread, list[str]]:
    order: list[str] = []
    from omniweave_core.host import activate as activate_module  # noqa: PLC0415

    real = activate_module.activate

    def recording(card: Any) -> type[object]:
        order.append("activate")
        return real(card)

    monkeypatch.setattr(activate_module, "activate", recording)
    armed: dict[str, Any] = {}

    def guard(*, armed: bool) -> None:
        order.append("guard")
        armed_box["armed"] = armed

    armed_box = armed
    host_sock, worker_sock = socket.socketpair()
    _OPEN.extend((host_sock, worker_sock))
    host_sock.settimeout(30)
    outcome: dict[str, Any] = {}

    def run() -> None:
        outcome["status"] = wk.serve(
            sp.SocketChannel(worker_sock), find_card=find_card, guard=guard
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    armed["outcome"] = outcome
    return _Host(host_sock), armed, thread, order


def test_the_hook_is_armed_before_the_drivers_module_is_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14:867's order, observed: the guard runs, THEN `activate()`, then `HELLO_ACK` -- whose five
    keys are 04:1696's, `isolation_granted` echoed (DR10)."""
    host, box, thread, order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _hello(tmp_path))
    ack = host.next()
    assert ack.kind is wire.FrameKind.HELLO_ACK
    assert order == ["guard", "activate"]
    assert box["armed"] is True, "the office card declares needs_network = false"
    assert ack.header["driver_id"] == OFFICE
    assert ack.header["port"] == "parse/1"
    assert ack.header["isolation_granted"] == {"mode": "subproc"}
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_one_result_per_unit_whatever_each_unit_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """04:1715: one `RESULT` per unit. A parsed DOCX and a truncated one in one `INVOKE`: the
    first answers with its fragment inline and its asset in the CAS, the second with the
    driver's own `corrupt_input`, and neither answer is the batch's."""
    host, box, thread, _order = _serve(monkeypatch)
    hello = _hello(tmp_path)
    host.send(wire.FrameKind.HELLO, hello)
    host.next()
    cas = BlobStore(tmp_path / "cas")
    units: list[dict[str, object]] = []
    for name in ("rich.docx", "truncated.docx"):
        with (FIXTURES / name).open("rb") as source:
            digest = cas.put(source)
        units.append(
            {
                "uri": str(FIXTURES / name),
                "part": "",
                "content_sha256": digest.hex(),
                "byte_len": (FIXTURES / name).stat().st_size,
                "media_type": DOCX,
                "blob_ref": format_ref(digest),
            }
        )
    host.send(
        wire.FrameKind.INVOKE,
        {"invoke_id": "inv1", "units": units, "deadline_ms": 60_000, "budget_micros": 0},
    )
    first, second = host.until(wire.FrameKind.RESULT, 2)
    assert (first.header["unit_index"], second.header["unit_index"]) == (0, 1)
    assert first.header["outcome"] == "ok"
    produced = first.header["produced"]
    assert produced[0] == {"kind": "doc_fragment", "byte_len": len(first.body), "inline": True}  # type: ignore[index]
    assert str(produced[1]["blob"]).startswith("cas://")  # type: ignore[index]
    assert b'"t":"block"' in first.body
    assert second.header["failure_class"] == "corrupt_input"
    assert not (tmp_path / "tmp" / "inv1" / "0").exists(), "a unit's scratch goes before its RESULT"
    assert not (tmp_path / "tmp" / "inv1" / "1").exists()
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_a_driver_that_raises_anything_else_is_a_driver_bug_on_that_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave_office.driver import AnydocParser  # noqa: PLC0415

    def broken(self: object, unit: UnitRef, parts: object, io: object) -> None:
        del self, unit, parts, io
        raise ValueError("a bug in the driver")

    monkeypatch.setattr(AnydocParser, "parse", broken)
    host, box, thread, _order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _hello(tmp_path))
    host.next()
    unit = {"uri": "u", "part": "", "content_sha256": "0" * 64, "byte_len": 1}
    host.send(wire.FrameKind.INVOKE, {"invoke_id": "i", "units": [unit], "deadline_ms": 0})
    (result,) = host.until(wire.FrameKind.RESULT)
    assert result.header["failure_class"] == "driver_bug"
    #  D934: the type and where it was raised, never the exception's text (15:1366).
    line = broken.__code__.co_firstlineno + 2
    assert result.header["message"] == f"ValueError at test_host_worker.py:{line} in broken"
    assert "a bug in the driver" not in str(result.header["message"])
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_a_driver_errors_message_is_redacted_before_it_crosses_the_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D934, 15:1336: `redact()` runs in the worker, so a credential a driver put in its own
    message never reaches the host, and the driver's class and words otherwise stand."""
    from omniweave_office.driver import AnydocParser  # noqa: PLC0415

    def refused(self: object, unit: UnitRef, parts: object, io: object) -> None:
        del self, unit, parts, io
        raise DriverError(cls=FailureClass.AUTH, message="denied: Authorization: Bearer s3cr3t")

    monkeypatch.setattr(AnydocParser, "parse", refused)
    host, box, thread, _order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _hello(tmp_path))
    host.next()
    unit = {"uri": "u", "part": "", "content_sha256": "0" * 64, "byte_len": 1}
    host.send(wire.FrameKind.INVOKE, {"invoke_id": "i", "units": [unit], "deadline_ms": 0})
    (result,) = host.until(wire.FrameKind.RESULT)
    assert result.header["failure_class"] == "auth"
    assert result.header["message"] == "denied: Authorization: <redacted>"
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"card_sha256": "sha256:" + "0" * 64}, "the host's card is"),
        ({"port": "embed/1"}, "this worker serves compile/1, derive/1 and parse/1"),
        ({"port": "derive/1"}, "card declares parse/1, and HELLO says derive/1"),
        ({"driver_id": "parse.nobody.here"}, "no installed card"),
    ],
)
def test_a_hello_the_worker_cannot_honour_is_fatal_before_any_driver_code_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, object], detail: str
) -> None:
    host, box, thread, order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _hello(tmp_path, **change))
    fatal = host.next()
    assert fatal.kind is wire.FrameKind.FATAL
    assert detail in str(fatal.header["detail"])
    thread.join(10)
    assert box["outcome"]["status"] == 1
    assert order == [], "neither the guard nor activate() ran for a card the worker refused"


SEGMENTER = "derive.segment.spine"
VIEW = (
    b'{"t":"doc","doc":"d1","sections":{"/0001":"One"},"defaults":{"sec":"/0001"}}\n'
    b'{"t":"block","cite":"d1#1","kind":"heading","text":"One"}\n'
    b'{"t":"block","cite":"d1#2","kind":"paragraph","text":"A paragraph."}\n'
)


def test_a_derive_session_answers_each_unit_with_its_graph_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D664: `derive/1` is served. The `INVOKE`'s `lane` reaches the driver as `DeriveScope.lane`,
    each unit is its own call and its own `RESULT`, and a unit that is not a view is that unit's
    `corrupt_input`, not the batch's."""
    card = catalog().cards.get(SEGMENTER)
    assert card is not None, "omniweave-graph is a workspace member and ships the card"
    from omniweave_graph.segment.driver import SpineSegmenter  # noqa: PLC0415

    seen: list[tuple[str, int]] = []
    real = SpineSegmenter.derive

    def recording(self: Any, scope: Any, io_obj: Any) -> Any:
        seen.append((scope.lane, len(scope.units)))
        return real(self, scope, io_obj)

    monkeypatch.setattr(SpineSegmenter, "derive", recording)
    host, box, thread, _order = _serve(monkeypatch)
    host.send(
        wire.FrameKind.HELLO,
        _hello(tmp_path, port="derive/1", driver_id=SEGMENTER, card_sha256=card.card_sha256),
    )
    ack = host.next()
    assert (ack.kind, ack.header["port"]) == (wire.FrameKind.HELLO_ACK, "derive/1")
    cas = BlobStore(tmp_path / "cas")
    units = []
    for body in (VIEW, b"not a view\n"):
        digest = cas.put(io.BytesIO(body))
        units.append(
            {"uri": "view", "part": "", "content_sha256": digest.hex(), "byte_len": len(body),
             "blob_ref": format_ref(digest)}
        )  # fmt: skip
    host.send(
        wire.FrameKind.INVOKE,
        {"invoke_id": "d1", "units": units, "deadline_ms": 60_000, "budget_micros": 0,
         "lane": "segment"},
    )  # fmt: skip
    first, second = host.until(wire.FrameKind.RESULT, 2)
    assert first.header["outcome"] == "ok"
    produced = first.header["produced"]
    assert produced == [{"kind": "graph_items", "byte_len": len(first.body), "inline": True}]
    assert b'"t":"segment"' in first.body
    assert b'"blocks":["d1#1","d1#2"]' in first.body
    assert second.header["failure_class"] == "corrupt_input"
    assert seen == [("segment", 1), ("segment", 1)], "the lane, one unit a call"
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_derive_one_refuses_a_driver_without_derive_or_a_non_result() -> None:
    scope = DeriveScope(lane="segment", units=(), allowed_cites=frozenset())
    with pytest.raises(DriverError, match="no derive"):
        wk.derive_one(None, scope, None)  # type: ignore[arg-type]
    with pytest.raises(DriverError, match="returned NoneType"):
        wk.derive_one(lambda _scope, _io: None, scope, None)  # type: ignore[arg-type]


def test_lane_rides_the_invoke_header_only_when_there_is_one() -> None:
    unit = UnitRef(uri="u", part="", content_sha256="0" * 64, byte_len=1)
    parse = sp.Invocation(invoke_id="i", units=(unit,), deadline_ms=0, budget_micros=0)
    derive = sp.Invocation(
        invoke_id="i", units=(unit,), deadline_ms=0, budget_micros=0, lane="segment"
    )
    assert "lane" not in parse.as_header()
    assert derive.as_header()["lane"] == "segment"


def test_a_first_frame_that_is_not_hello_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    host, box, thread, _order = _serve(monkeypatch)
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    assert host.next().kind is wire.FrameKind.FATAL
    thread.join(10)
    assert box["outcome"]["status"] == 1


# ---------------------------------------------------------------------------------------------
# 3. real processes
# ---------------------------------------------------------------------------------------------


def test_the_armed_hook_refuses_egress_in_a_real_interpreter() -> None:
    """The hook cannot be installed in this process (it is permanent), so a child runs it. Armed,
    a name resolution raises the worker's `PermissionError`; unarmed, the same call succeeds."""
    probe = (
        "import socket, sys\n"
        "from omniweave_core.host.worker import install_egress_guard\n"
        "install_egress_guard(armed=sys.argv[1] == 'armed')\n"
        "try:\n"
        "    socket.getaddrinfo('localhost', 80)\n"
        "except PermissionError as exc:\n"
        "    print('refused', exc)\n"
        "else:\n"
        "    print('allowed')\n"
    )
    armed = subprocess.run(  # noqa: S603 -- the interpreter plus a literal program
        [sys.executable, "-c", probe, "armed"], capture_output=True, text=True, check=True
    )
    assert armed.stdout.startswith("refused socket.getaddrinfo refused in the S4 worker")
    unarmed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe, "open"], capture_output=True, text=True, check=True
    )
    assert unarmed.stdout.strip() == "allowed"


def test_the_host_launches_a_real_worker_that_parses_a_real_document(tmp_path: Path) -> None:
    """Hops 12-14 across a process boundary: `launch()` listens, spawns
    `python -m omniweave_core.host.worker`, puts it in a job object, accepts, and exchanges
    `HELLO`; one `INVOKE` comes back as one `RESULT` whose `produced` the host rebuilt (D583)."""
    card = _card()
    hello = _hello(tmp_path)
    cas = BlobStore(tmp_path / "cas")
    with (FIXTURES / "rich.docx").open("rb") as source:
        digest = cas.put(source)
    address = sp.local_address(f"ow-test-worker-{time.monotonic_ns()}")
    settings = sp.HostSettings(
        worker_idle_ttl_s=300, crash_threshold=3, crash_window_s=60, tick_ms=50,
        max_workers={"free": 4},
    )  # fmt: skip
    worker, ack = sp.launch(
        sp.WorkerKey(OFFICE, "0" * 64),
        sp.SpawnRequest(
            argv=sp.worker_argv(sys.executable, address),
            cwd=str(tmp_path),
            env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
            address=address,
        ),
        hello=hello,
        expect={"driver_id": OFFICE, "version": card.identity.version, "port": "parse/1"},
        deadlines=sp.Deadlines(0, 60_000, 0),
        settings=settings,
        now_ms=lambda: time.monotonic_ns() // 1_000_000,
        memory_mb=1024,
    )  # fmt: skip
    try:
        assert ack.driver_id == OFFICE
        if sys.platform == "win32":
            #  D636: `launch()` spawned the child suspended INTO its job, so the job holds it.
            #  D637: and at 04-driver-system.md:1754's priority, set at creation. Both are the
            #  Windows cells of S4; POSIX has neither (D927), and the rest of this test is
            #  the same worker on either transport.
            assert worker._job is not None
            assert worker.pid in worker._job.pids()
            assert sp.priority_class(worker.pid) == sp.BELOW_NORMAL_PRIORITY_CLASS
        unit = UnitRef(
            uri=str(FIXTURES / "rich.docx"), part="", content_sha256=digest.hex(),
            byte_len=(FIXTURES / "rich.docx").stat().st_size, media_type=DOCX,
        )  # fmt: skip
        report = worker.invoke(
            sp.Invocation(
                invoke_id="i1", units=(unit,), deadline_ms=60_000, budget_micros=0,
                blob_refs=(format_ref(digest),),
            ),
            deadlines=sp.Deadlines(15_000, 60_000, 60_000),
            memory_mb=1024,
        )  # fmt: skip
        assert report.failures == (None,)
        (result,) = report.results
        assert result is not None
        kinds = [(ref.kind, ref.inline is not None) for ref in result.produced]
        assert kinds == [("doc_fragment", True), ("asset", False)]
        assert report.progress_count > 0, "the office driver reports progress per top-level block"
    finally:
        assert worker.stop() == 0


def test_a_memory_error_in_the_driver_is_resource_limit_on_memory_mb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D657: an allocation past the job object's cap fails in the driver before the watchdog
    samples it. That is the card's `memory_mb`, not a bug, and it is reported as one:
    `resource_limit`, `limit = "memory_mb"`, at 08-runtime.md:567's first cooldown."""
    from omniweave_core.work import Source, rung_for  # noqa: PLC0415
    from omniweave_office.driver import AnydocParser  # noqa: PLC0415

    def hungry(self: object, unit: UnitRef, parts: object, io: object) -> None:
        del self, unit, parts, io
        raise MemoryError

    monkeypatch.setattr(AnydocParser, "parse", hungry)
    host, box, thread, _order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _hello(tmp_path))
    host.next()
    unit = {"uri": "u", "part": "", "content_sha256": "0" * 64, "byte_len": 1}
    host.send(wire.FrameKind.INVOKE, {"invoke_id": "i", "units": [unit], "deadline_ms": 0})
    (result,) = host.until(wire.FrameKind.RESULT)
    assert result.header["failure_class"] == "resource_limit"
    assert result.header["limit"] == "memory_mb"
    assert result.header["retry_after_ms"] == wk.MEMORY_COOLDOWN_MS
    rung = rung_for("resource_limit", Source.DRIVER)
    assert rung is not None
    assert rung.first_cooldown_ms == wk.MEMORY_COOLDOWN_MS
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_a_worker_the_watchdog_finds_over_memory_mb_is_ended_with_the_call(
    tmp_path: Path,
) -> None:
    """D657: the verdict that ends a call ends the worker. Before, the child kept running the
    unit it was given, over the cap and with a peak that never comes down, and the pool handed
    it to the next batch -- whose first quiet tick failed every unit on the old peak. A 1 MiB
    `memory_mb` puts any interpreter over the cap at the first sample, and the watchdog samples on
    a tick with no frame, so the unit is office-200's 20,000-row spreadsheet: long enough to
    leave one."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "omniweave_gen_office200_watchdog", REPO / "fixtures" / "gen" / "gen_office200.py"
    )
    assert spec is not None
    assert spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    big = tmp_path / "big.xlsx"
    big.write_bytes(gen.xlsx(gen._Stream("t:watchdog"), 20_000))
    card = _card()
    hello = _hello(tmp_path)
    cas = BlobStore(tmp_path / "cas")
    with big.open("rb") as source:
        digest = cas.put(source)
    address = sp.local_address(f"ow-test-worker-{time.monotonic_ns()}")
    settings = sp.HostSettings(
        worker_idle_ttl_s=300, crash_threshold=3, crash_window_s=60, tick_ms=50,
        max_workers={"free": 4},
    )  # fmt: skip
    worker, _ack = sp.launch(
        sp.WorkerKey(OFFICE, "0" * 64),
        sp.SpawnRequest(
            argv=sp.worker_argv(sys.executable, address),
            cwd=str(tmp_path),
            env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
            address=address,
        ),
        hello=hello,
        expect={"driver_id": OFFICE, "version": card.identity.version, "port": "parse/1"},
        deadlines=sp.Deadlines(0, 60_000, 0),
        settings=settings,
        now_ms=lambda: time.monotonic_ns() // 1_000_000,
        memory_mb=1024,
    )  # fmt: skip
    try:
        unit = UnitRef(
            uri=str(big), part="", content_sha256=digest.hex(),
            byte_len=big.stat().st_size, media_type=XLSX,
        )  # fmt: skip
        report = worker.invoke(
            sp.Invocation(
                invoke_id="i1", units=(unit, unit), deadline_ms=60_000, budget_micros=0,
                blob_refs=(format_ref(digest), format_ref(digest)),
            ),
            deadlines=sp.Deadlines(15_000, 60_000, 60_000),
            memory_mb=1,
        )  # fmt: skip
        verdicts = [one for one in report.failures if one is not None]
        assert verdicts, "a 1 MiB cap is over at the first sample"
        assert {one.failure_class for one in verdicts} == {FailureClass.RESOURCE_LIMIT}
        assert report.event is sp.BatchEvent.RESOURCE_LIMIT
        assert worker.stopped is True
        assert worker._proc.poll() is not None, "the child is gone, not left running the unit"
    finally:
        worker.stop()


# ---------------------------------------------------------------------------------------------
# D712: a Service granted on the INVOKE, reached through io.service()
# ---------------------------------------------------------------------------------------------

ENTITY_LLM = "derive.entity.llm"
BILLED_VIEW = (
    json.dumps(
        {
            "t": "segment", "seg": "seg:9f2c1d4a77b03e51", "heading_path": [], "n_blocks": 1,
            "n_tokens": 5, "layer": "body", "atom": None,
            "defaults": {"layer": "body", "page": 1, "covered": False},
            "etypes": ["org", "unknown"], "document_scoped": [], "relations": [],
            "doc": {"format": "md", "media_type": "text/markdown"},
        }
    )
    + "\n"
    + json.dumps({"t": "block", "cite": "d1#4", "kind": "paragraph", "ord": 0,
                  "text": "Acme pays Beta."})
    + "\n"
).encode()  # fmt: skip
ANSWER = {
    "entities": [{"name": "Acme", "etype": "org", "cite": "d1#4", "quote": "Acme pays",
                  "description": None}],
    "relations": [],
    "more_available": False,
}  # fmt: skip


class _Model(http.server.BaseHTTPRequestHandler):
    """A chat-completion server answering from a script, and recording what it was sent."""

    replies: ClassVar[list[tuple[int, bytes]]] = []
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
        )
        status, payload = type(self).replies.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 -- the base's name
        del format, args


def _model(replies: list[tuple[int, bytes]]) -> tuple[str, http.server.ThreadingHTTPServer]:
    _Model.replies, _Model.seen = list(replies), []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def _completion(answer: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
    ).encode()


def _billed_invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    services: list[dict[str, object]],
    deadline_ms: int = 60_000,
) -> Any:
    card = catalog().cards.get(ENTITY_LLM)
    assert card is not None, "omniweave-llm ships the card (D711)"
    host, box, thread, _order = _serve(monkeypatch)
    host.send(
        wire.FrameKind.HELLO,
        _hello(tmp_path, port="derive/1", driver_id=ENTITY_LLM, card_sha256=card.card_sha256),
    )
    assert host.next().kind is wire.FrameKind.HELLO_ACK
    cas = BlobStore(tmp_path / "cas")
    digest = cas.put(io.BytesIO(BILLED_VIEW))
    unit = {"uri": "seg", "part": "", "content_sha256": digest.hex(),
            "byte_len": len(BILLED_VIEW), "blob_ref": format_ref(digest)}  # fmt: skip
    header: dict[str, object] = {
        "invoke_id": "b1", "units": [unit], "deadline_ms": deadline_ms, "budget_micros": 0,
        "lane": "entity", "services": services,
    }  # fmt: skip
    host.send(wire.FrameKind.INVOKE, header)
    [result] = host.until(wire.FrameKind.RESULT, 1)
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0
    return result


def _grant(base_url: str) -> dict[str, object]:
    return sp.ServiceGrant(
        name="llm", base_url=base_url, token="ab" * 32, model_id="qwen3:4b",
        model_rev="0123456789abcdef", capacity=2, traceparent="00-trace",
    ).as_header()  # fmt: skip


def test_services_ride_the_invoke_header_only_when_granted() -> None:
    unit = UnitRef(uri="u", part="", content_sha256="0" * 64, byte_len=1)
    bare = sp.Invocation(invoke_id="i", units=(unit,), deadline_ms=0, budget_micros=0)
    grant = sp.ServiceGrant(name="llm", base_url="http://127.0.0.1:1", token="t",  # noqa: S106
                            model_id="m", model_rev="r")  # fmt: skip
    granted = sp.Invocation(
        invoke_id="i", units=(unit,), deadline_ms=0, budget_micros=0, services=(grant,)
    )
    assert "services" not in bare.as_header()
    assert granted.as_header()["services"] == [
        {"name": "llm", "base_url": "http://127.0.0.1:1", "token": "t", "model_id": "m",
         "model_rev": "r", "capacity": 1, "traceparent": "", "request_timeout_s": 600}
    ]  # fmt: skip


@pytest.mark.parametrize("deadline_ms", [60_000, 0], ids=["deadline", "no-deadline"])
def test_a_granted_service_is_reached_and_its_answer_is_the_units_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deadline_ms: int
) -> None:
    """D712: the grant rebuilds the handle; the token, the model and the path reach the server.

    An `INVOKE` with no deadline (0, as `subproc.Deadlines` reads it) still reaches the Service: the
    request timeout alone bounds the call, never a timeout of 0.
    """
    base_url, server = _model([(200, _completion(ANSWER))])
    try:
        result = _billed_invoke(tmp_path, monkeypatch, [_grant(base_url)], deadline_ms)
    finally:
        server.shutdown()
        server.server_close()
    assert result.header["outcome"] == "ok", result.header
    assert b'"t":"entity"' in result.body and b'"title":"Acme"' in result.body
    [seen] = _Model.seen
    assert (seen["path"], seen["auth"]) == ("/v1/chat/completions", "Bearer " + "ab" * 32)
    assert seen["body"]["model"] == "qwen3:4b"


def test_a_service_not_granted_is_the_drivers_bug_and_names_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _billed_invoke(tmp_path, monkeypatch, [])
    assert result.header["failure_class"] == "driver_bug"
    assert "no Service of that name is granted" in str(result.header.get("message", ""))


def test_a_service_that_fails_is_upstream_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handle's core error becomes the ports class a driver and the runtime read."""
    base_url, server = _model([(500, b'{"error":"overloaded"}')])
    try:
        result = _billed_invoke(tmp_path, monkeypatch, [_grant(base_url)])
    finally:
        server.shutdown()
        server.server_close()
    assert result.header["failure_class"] == "upstream_unavailable"


def test_a_malformed_grant_grants_nothing() -> None:
    assert wk._services({"services": "llm"}) == {}
    assert wk._services({"services": 7}) == {}
    assert wk._services({"services": [{"base_url": "x"}, "llm", {"name": "llm"}]}) == {
        "llm": {"name": "llm"}
    }


def test_the_granted_handle_is_the_calls_deadline_cancellation_and_timeout() -> None:
    """The deadline and the cancellation are the call's; the timeout is the Service's own."""
    grant = {**_grant("http://127.0.0.1:1"), "request_timeout_s": 7}
    handle = wk._GrantedHandle(grant, deadline_ms=5, cancelled=lambda: True)
    assert (handle.deadline_ms, handle.cancelled(), handle._handle._timeout_s) == (5, True, 7.0)
    assert (handle.name, handle.model_id, handle.model_rev) == (
        "llm",
        "qwen3:4b",
        "0" + "123456789abcdef",
    )
    assert (handle.capacity, handle.traceparent, handle.token) == (2, "00-trace", "ab" * 32)
    with pytest.raises(DriverError) as caught:
        wk._GrantedHandle({"name": "llm"}, deadline_ms=0, cancelled=bool)
    assert caught.value.cls is FailureClass.DRIVER_BUG


def test_service_issues_only_the_named_grant_under_the_calls_deadline(tmp_path: Path) -> None:
    io_obj = wk.WorkerIO(
        blobs=wk.WorkerBlobs(BlobStore(tmp_path)),
        tmpdir=str(tmp_path),
        deadline_ms=4321,
        max_output_bytes=1,
    )
    call = wk._Call(
        send=lambda *_: None,
        invoke_id="i",
        unit_index=0,
        services={"vlm": _grant("http://127.0.0.1:1")},
    )
    wk._CALLS[io_obj] = call
    handle = io_obj.service("vlm")
    assert (handle.deadline_ms, handle.cancelled()) == (4321, False)
    call.cancelled = True
    assert handle.cancelled() is True
    with pytest.raises(DriverError, match=r"service\('llm'\): no Service of that name"):
        io_obj.service("llm")


def test_a_grant_is_made_from_the_handle_the_registry_issued() -> None:
    """D713: the handle's fields, and its request timeout; a handle with none keeps 600."""
    bearer = "ab"
    handle = Handle(
        name="llm", base_url="http://127.0.0.1:9", token=bearer, model_id="m", model_rev="r",
        capacity=3, traceparent="00-t", deadline_ms=0, _timeout_s=42.0,
    )  # fmt: skip
    assert sp.ServiceGrant.of(handle) == sp.ServiceGrant(
        name="llm", base_url="http://127.0.0.1:9", token=bearer, model_id="m", model_rev="r",
        capacity=3, traceparent="00-t", request_timeout_s=42,
    )  # fmt: skip
    bare = SimpleNamespace(
        name="llm", base_url="http://127.0.0.1:9", token="", model_id="m", model_rev="r",
        capacity=1, traceparent="",
    )  # fmt: skip
    assert sp.ServiceGrant.of(bare).request_timeout_s == 600  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 7. compile/1 (D771): the job document, lowered in the worker
# ---------------------------------------------------------------------------------------------

OWTEXT = "compile.text.owtext"
GOLDEN = REPO / "fixtures" / "out" / "golden" / "owtext" / "il"
TOMBSTONE = (
    REPO / "packages" / "omniweave-core" / "src" / "omniweave_core" / "drivers" / "tombstones"
) / "parse.doc.omniparse.toml"
TEXT = b"== u01 ==\nRevenue rose 12% in Q3.\n== u02 ==\nMargins held.\n"


def _owtext_card() -> Any:

    path = HERE / "driver.toml"
    return load_card(read_card_bytes(path), origin="driver_path", source=str(path))


def _compile_hello(tmp_path: Path, **overrides: object) -> dict[str, object]:
    card = _owtext_card()
    fields: dict[str, object] = {
        "port": "compile/1",
        "driver_id": OWTEXT,
        "card_sha256": card.card_sha256,
        "card_source": card.source,
        "card_origin": "driver_path",
    }
    fields.update(overrides)
    return _hello(tmp_path, **fields)


def _compile_job(tmp_path: Path) -> tuple[Path, Any]:
    """A scaffolded owtext JobDir holding the golden IL, and the Job its host gated."""
    import shutil  # noqa: PLC0415
    from dataclasses import replace  # noqa: PLC0415

    card = _owtext_card()
    compiled = CompileCard.of(card)
    table = load_table(Path(card.source), compiled)
    brief = (
        f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
        "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
        "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
        "- u02: { anchor: content }\n## forbidden\n"
    )
    job_dir = tmp_path / "job"
    job = scaffold(
        job_dir, card=compiled, card_sha256=card.card_sha256, table=table, brief_text=brief,
        brief=parse_brief(brief, baseline=()), slug="q3", artifact_gen=1, corpus="handbook",
        traceparent=traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"),
        clock_ns=1_700_000_000_000_000_000,
    )  # fmt: skip
    for name in ("il.toml", "u01.html", "u02.html"):
        shutil.copyfile(GOLDEN / name, job_dir / "il" / name)
    bundle = ILBundle.load(job_dir / "il", carrier=OwTextCompiler().carrier, constructs=table)
    plan = replace(
        job.plan,
        il_digest=bundle.il_digest,
        gate_status=GateStatus.PASSED,
        units=tuple(
            replace(mine, nsig=theirs.nsig, manual_reason=theirs.manual_reason)
            for mine, theirs in zip(job.plan.units, bundle.units, strict=True)
        ),
    )
    return job_dir, replace(job, plan=plan)


def _compile_invoke(job: Any, job_dir: Path, /, **changes: object) -> dict[str, object]:

    unit = job_unit(job)
    header: dict[str, object] = {
        "invoke_id": "c1",
        "units": [
            {"uri": unit.uri, "part": unit.part, "content_sha256": unit.content_sha256,
             "byte_len": unit.byte_len, "media_type": unit.media_type}
        ],
        "deadline_ms": 60_000,
        "budget_micros": 0,
        "job": job.as_json(),
        "job_dir": str(job_dir),
    }  # fmt: skip
    header.update(changes)
    return header


def _compile_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_Host, dict[str, Any], threading.Thread, list[str]]:
    served = _serve(monkeypatch)
    host = served[0]
    host.send(wire.FrameKind.HELLO, _compile_hello(tmp_path))
    ack = host.next()
    assert (ack.kind, ack.header["port"]) == (wire.FrameKind.HELLO_ACK, "compile/1")
    assert ack.header["driver_id"] == OWTEXT
    return served


def _shut(host: _Host, thread: threading.Thread, box: dict[str, Any]) -> None:
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


def test_a_compile_session_lowers_the_job_in_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The card is the one the HELLO names; the artefact and the receipt come back through the
    CAS, the frame's body empty, and the worker's scratch is gone before the RESULT."""

    host, box, thread, order = _compile_session(tmp_path, monkeypatch)
    assert order == ["guard", "activate"]
    assert box["armed"] is True, "owtext declares needs_network = false"
    job_dir, job = _compile_job(tmp_path)
    host.send(wire.FrameKind.INVOKE, _compile_invoke(job, job_dir))
    [result] = host.until(wire.FrameKind.RESULT)
    assert result.header["outcome"] == "ok"
    assert result.body == b""
    produced: Any = result.header["produced"]
    assert [entry["kind"] for entry in produced] == ["artifact", "receipt"]
    cas = BlobStore(tmp_path / "cas")
    with cas.open_ref(str(produced[0]["blob"])) as handle:
        assert handle.read() == TEXT
    with cas.open_ref(str(produced[1]["blob"])) as handle:
        receipt = Receipt.from_json(json.loads(handle.read()))
    assert receipt.output["sha256"] == hashlib.sha256(TEXT).hexdigest()
    assert receipt.slug == "q3"
    assert not (tmp_path / "tmp" / "c1").exists()
    _shut(host, thread, box)


def _refusal(result: wire.Frame) -> Any:

    assert result.header["failure_class"] == "corrupt_input"
    refused = refusal_of(str(result.header["message"]))
    assert refused is not None
    return refused


def test_a_job_dir_changed_after_the_gate_is_refused_with_its_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, box, thread, _order = _compile_session(tmp_path, monkeypatch)
    job_dir, job = _compile_job(tmp_path)
    (job_dir / "il" / "u02.html").write_text("<section><p>Margins fell.</p></section>\n")
    host.send(wire.FrameKind.INVOKE, _compile_invoke(job, job_dir))
    [result] = host.until(wire.FrameKind.RESULT)
    refused = _refusal(result)
    assert (refused.code(), refused.fix) == ("OW_TARGET_JOB_CHANGED", "ow out check --stage final")
    assert "il_digest" in str(refused)
    _shut(host, thread, box)


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"job_dir": ""}, "job_dir ''"),
        ({"job_dir": None}, "job_dir None"),
        ({"units": [{"uri": "ow-job://x", "part": "", "content_sha256": "0" * 64}]}, "ow-job://x"),
    ],
)
def test_an_invoke_that_does_not_carry_its_job_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, object], named: str
) -> None:
    host, box, thread, _order = _compile_session(tmp_path, monkeypatch)
    job_dir, job = _compile_job(tmp_path)
    host.send(wire.FrameKind.INVOKE, _compile_invoke(job, job_dir, **changes))
    [result] = host.until(wire.FrameKind.RESULT)
    refused = _refusal(result)
    assert refused.code() == "OW_TARGET_JOB_INVALID"
    assert named in str(refused)
    _shut(host, thread, box)


def test_a_job_that_does_not_load_is_refused_with_its_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, box, thread, _order = _compile_session(tmp_path, monkeypatch)
    job_dir, job = _compile_job(tmp_path)
    host.send(wire.FrameKind.INVOKE, _compile_invoke(job, job_dir, job={"schema": "x"}))
    [result] = host.until(wire.FrameKind.RESULT)
    assert _refusal(result).code() == "OW_TARGET_JOB_INVALID"
    _shut(host, thread, box)


def test_a_compile_bug_is_the_drivers_bug_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def broken(*_args: object, **_kwargs: object) -> object:
        raise KeyError("u03")

    monkeypatch.setattr(OwTextCompiler, "lower", broken)
    host, box, thread, _order = _compile_session(tmp_path, monkeypatch)
    job_dir, job = _compile_job(tmp_path)
    host.send(wire.FrameKind.INVOKE, _compile_invoke(job, job_dir))
    [result] = host.until(wire.FrameKind.RESULT)
    assert result.header["failure_class"] == "driver_bug"
    said = str(result.header["message"])
    assert said.startswith("KeyError at test_host_worker.py:")
    assert "u03" not in said
    _shut(host, thread, box)


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"driver_id": "compile.text.other"}, "declares compile.text.owtext, not"),
        ({"card_origin": "nowhere"}, "card_origin 'nowhere' is not one of"),
        ({"card_source": "no/such/driver.toml"}, "does not read"),
        ({"card_sha256": "sha256:" + "0" * 64}, "the host's card is"),
        ({"card_source": str(TOMBSTONE), "card_origin": "tombstone"}, "is a tombstone"),
    ],
)
def test_a_named_card_the_worker_cannot_honour_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, object], detail: str
) -> None:
    host, box, thread, order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _compile_hello(tmp_path, **change))
    fatal = host.next()
    assert fatal.kind is wire.FrameKind.FATAL
    assert detail in str(fatal.header["detail"])
    thread.join(10)
    assert box["outcome"]["status"] == 1
    assert order == []


def test_a_compile_card_whose_table_does_not_load_is_fatal_at_hello(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table is read once, after the driver activates: a table the card's digest does not
    describe is refused at HELLO, before any INVOKE."""

    def refusing(*_args: object) -> object:
        raise DriverHostError(
            "constructs.toml digests otherwise", symbol="OW_CARD_INVALID", fix="f"
        )

    monkeypatch.setattr(agentdoc, "load_table", refusing)
    host, box, thread, order = _serve(monkeypatch)
    host.send(wire.FrameKind.HELLO, _compile_hello(tmp_path))
    fatal = host.next()
    assert fatal.kind is wire.FrameKind.FATAL
    assert "digests otherwise" in str(fatal.header["detail"])
    thread.join(10)
    assert box["outcome"]["status"] == 1
    assert order == ["guard", "activate"]
