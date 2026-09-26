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
import os
import socket
import subprocess  # noqa: TID251 -- two tests run a real child
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.blobs import BlobStore, format_ref
from omniweave_core.discovery import catalog
from omniweave_core.errors import DriverHostError
from omniweave_core.host import subproc as sp
from omniweave_core.host import wire
from omniweave_core.host import worker as wk
from omniweave_ports.types import ArtifactRef, DriverError, FailureClass, UnitRef

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures"
OFFICE = "parse.office.anydoc"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="the named-pipe arm")


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
    assert result.header["message"] == "ValueError: a bug in the driver"
    host.send(wire.FrameKind.SHUTDOWN, {"grace_ms": 0})
    thread.join(10)
    assert box["outcome"]["status"] == 0


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"card_sha256": "sha256:" + "0" * 64}, "the host's card is"),
        ({"port": "derive/1"}, "this worker serves parse/1"),
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


@WINDOWS_ONLY
def test_the_host_launches_a_real_worker_that_parses_a_real_document(tmp_path: Path) -> None:
    """Hops 12-14 across a process boundary: `launch()` listens, spawns
    `python -m omniweave_core.host.worker`, puts it in a job object, accepts, and exchanges
    `HELLO`; one `INVOKE` comes back as one `RESULT` whose `produced` the host rebuilt (D583)."""
    card = _card()
    hello = _hello(tmp_path)
    cas = BlobStore(tmp_path / "cas")
    with (FIXTURES / "rich.docx").open("rb") as source:
        digest = cas.put(source)
    address = f"\\\\.\\pipe\\ow-test-worker-{time.monotonic_ns()}"
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
