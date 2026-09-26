"""The `subproc` worker's own side of S4: the bootstrap, the audit hook, and one `RESULT` per unit.

02-architecture.md section 4.1 hop 13 is this process's whole job: *"`parse.pdf.pdfium` (child) |
`UnitRef`, `PartSelector`, `DriverIO` | `owdoc-fragment/1` NDJSON as an `ArtifactRef` -- inline
under `INLINE_MAX = 262,144` bytes, else a CAS blob ref; `RESULT`, **one frame per unit** | nothing
in the store: it has no store handle (INV-6)"* (02:483). `host/subproc.py` built the host's half of
that conversation at W3.2 and said, of this half, *"the bootstrap is `inproc.py`'s company"*
(`subproc.py`'s "What is deliberately NOT here"). This is that company.

```text
python -m omniweave_core.host.worker <base address>
  connect()                    subproc.connect: the read half first, then the write half
  HELLO                        04:1695's nine keys, plus the two this module names
  catalog()[driver_id]         the card, READ -- never imported (INV-4) -- and its sha checked
  install_egress_guard()       14:867: BEFORE activate(), armed iff needs_network = false
  activate(card)(**config)     the framework's only import_module, and the driver's __init__
  HELLO_ACK                    04:1696's five keys, plus isolation_granted echoed (DR10)
  INVOKE -> RESULT x units     until SHUTDOWN, or the host's end of the pipe closes
```

## The order of the first four steps is the security property

14-security.md:867: *"The `subproc` worker bootstrap installs the hook **before** `activate()`
imports the driver's module ... A worker that fails to install it exits before `activate()` rather
than running unprotected."* The card is read first because `needs_network` is on the card and the
hook's arming depends on it -- and reading a card is `tomllib` over a file, which runs none of the
driver's code (INV-4, the whole of `discovery.py`'s contract). So by the time the first line of a
third party's module body executes, the hook is in and cannot be taken out: PEP 578 hooks have no
removal API, which 14:850 calls *"the design, not a limitation"*.

**The hook is armed for `needs_network = false`, not only for `[egress] mode = "none"`.** 14:842
installs the host's hook under `mode = "none"`; 14:867's sandbox assertion is that *"an egress
attempt from a `needs_network = false` driver fails **in the worker**"*, under every mode. Those are
two statements about two processes, and in the worker the card's own declaration is the stronger
of the two: a driver that declared it needs no network has no connection to make. It refuses
`socket.connect` -- the event 14:842 names -- and `socket.getaddrinfo`, because a name resolution
is already a packet to a resolver the corpus never chose (D584).

## What crosses back, and the one thing the printed grammar cannot carry

04:1700's `RESULT` is *"`{invoke_id, unit_index, ...DriverResult}`"* and :1674's frame is one
header and ONE body. A `DriverResult` has a `produced` tuple, and the office driver's is a fragment
plus every asset -- two or more `ArtifactRef`s, each of which `ArtifactRef.of` may have left inline.
Several inline bodies cannot share one frame body without an offset table, which is exactly the
grammar `subproc.Invocation` already refused to invent for `INVOKE` (its docstring's "`body` is
singular"). This module takes the same line in the other direction: **at most one** produced ref
rides inline -- the first `doc_fragment` that fits -- and every other inline ref is written to the
CAS through `io.blobs.put()` before the frame is sent, so it crosses as `blob`. The header lists
each ref as `{kind, byte_len, blob}` or `{kind, byte_len, inline: true}` (D583).

Specified in 04-driver-system.md sections 6.2 and 6.5, 14-security.md section 5.3, and
02-architecture.md section 4.1 rows 12-14.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final

from omniweave_ports.types import (
    ArtifactRef,
    DriverError,
    DriverIO,
    DriverResult,
    FailureClass,
    PartSelector,
    UnitRef,
)

from omniweave_core.errors import DriverHostError
from omniweave_core.host import subproc, wire

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from omniweave_ports.types import Scalar, ServiceHandle

    from omniweave_core.blobs import BlobStore as CasStore
    from omniweave_core.drivers.card import DriverCard

__all__ = [
    "EGRESS_EVENTS",
    "HELLO_EXTRA_KEYS",
    "MESSAGE_MAX_CHARS",
    "PORTS_SERVED",
    "Session",
    "WorkerBlobs",
    "WorkerIO",
    "egress_refusal",
    "install_egress_guard",
    "main",
    "produced_header",
    "result_header",
    "serve",
]

PORTS_SERVED: Final[frozenset[str]] = frozenset({"parse/1"})
"""The ports this bootstrap can dispatch. `parse/1` alone, and a card on another port is refused at
`HELLO` rather than half-served: `acquire/1`, `derive/1` and `embed/1` each take a different input
type through a different method, and each lands with the cell that routes to it."""

EGRESS_EVENTS: Final[frozenset[str]] = frozenset({"socket.connect", "socket.getaddrinfo"})
"""The PEP 578 events the armed hook refuses. 14:842 names `socket.connect`; `getaddrinfo` is the
resolver lookup that precedes every named connection and is egress on its own. D584."""

HELLO_EXTRA_KEYS: Final[tuple[str, ...]] = ("max_output_bytes", "egress_mode")
"""The two `HELLO` keys beyond 04:1695's nine, each owed to the plan (D583).

`max_output_bytes` is `DriverIO`'s fourth field and the host's number (04:1795 -- *"on the host's
number, not by the driver's own check"*); no printed frame carries it, and a worker that picked its
own ceiling would be the driver's own check by another name. `egress_mode` is 14:867's *"the `HELLO`
frame carries the resolved `[egress] mode` so the worker cannot be started under a different policy
than the host resolved"*, which 04:1695's key list does not yet print."""

MESSAGE_MAX_CHARS: Final[int] = 2_048
"""A failure message's ceiling on the wire. `DriverError.message` is the driver's own text and
02:1060 says *"Nothing else crosses"* for a crash; a bounded message keeps a hostile or runaway
`str(exc)` from filling `MAX_HEADER_BYTES` and turning a failure into a protocol error."""

_TMP_KEY: Final[str] = "tmp"
_SOURCE_KEY: Final[str] = "source_ro"


# =============================================================================================
# 1. The audit hook: installed once, before activate(), never removed
# =============================================================================================


def egress_refusal(event: str, *, armed: bool) -> str | None:
    """The refusal message for one audit event, or `None` to let it through. PURE.

    The hook itself is two lines around this function, because a hook cannot be tested in the
    process that installs it: PEP 578 hooks are permanent, and a test runner with one armed could
    not open its own sockets afterwards.
    """
    if not armed or event not in EGRESS_EVENTS:
        return None
    return (
        f"{event} refused in the S4 worker: the card declares needs_network = false "
        f"(14-security.md:867)"
    )


def install_egress_guard(*, armed: bool) -> None:
    """`sys.addaudithook`, once per process. Called by `serve()` and by nothing else."""

    def hook(event: str, args: tuple[object, ...]) -> None:
        del args
        refused = egress_refusal(event, armed=armed)
        if refused is not None:
            raise PermissionError(refused)

    sys.addaudithook(hook)


# =============================================================================================
# 2. What HELLO said, validated once
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Session:
    """One worker's `HELLO`, parsed. Everything the rest of the process reads comes from here."""

    driver_id: str
    port: str
    card_sha256: str
    effective_config: Mapping[str, Scalar]
    source_ro: str
    tmp: str
    blob_base: str
    isolation_granted: Mapping[str, object]
    max_output_bytes: int
    egress_mode: str

    @classmethod
    def of(cls, header: Mapping[str, object]) -> Session:
        """Refuse a `HELLO` missing any key this process acts on. The host is not trusted blind
        either: a worker started with no `tmp` has nowhere to put a driver's scratch files."""
        roots = header.get("roots")
        if not isinstance(roots, Mapping):
            raise _refuse("HELLO carries no roots table")
        config = header.get("effective_config") or {}
        if not isinstance(config, Mapping):
            raise _refuse("HELLO effective_config is not a table")
        granted = header.get("isolation_granted") or {}
        if not isinstance(granted, Mapping):
            raise _refuse("HELLO isolation_granted is not a table")
        ceiling = header.get("max_output_bytes")
        if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 1:
            raise _refuse(f"HELLO max_output_bytes is {ceiling!r}, not a positive integer")
        return cls(
            driver_id=_text(header, "driver_id"),
            port=_text(header, "port"),
            card_sha256=_text(header, "card_sha256"),
            effective_config=dict(config),  # type: ignore[arg-type]
            source_ro=_text(roots, _SOURCE_KEY),
            tmp=_text(roots, _TMP_KEY),
            blob_base=_text(header, "blob_base"),
            isolation_granted=dict(granted),
            max_output_bytes=ceiling,
            egress_mode=str(header.get("egress_mode") or "granted"),
        )


def _text(header: Mapping[str, object], key: str) -> str:
    value = header.get(key)
    if not isinstance(value, str) or not value:
        raise _refuse(f"HELLO {key} is {value!r}, not a non-empty string")
    return value


def _refuse(message: str) -> DriverHostError:
    return DriverHostError(message, fix="check the host's HELLO against 04-driver-system.md:1695")


# =============================================================================================
# 3. The DriverIO a worker hands a driver
# =============================================================================================


class WorkerBlobs:
    """`omniweave_ports.BlobStore` over the host's CAS, with the invocation's units aliased in.

    **Why the alias exists.** A driver opens its input by `unit.content_sha256` (the office driver's
    `io.blobs.open(unit.content_sha256)`), and that digest is over the unit's NORMALISED bytes
    (0004_runtime.sql's comment on `unit.content_sha256`). The CAS names a blob by the digest of the
    bytes it holds. Where no normaliser ran the two agree; where one did, they do not, and the
    `INVOKE` unit's `blob_ref` is the only place the raw bytes are named. So `open()` resolves a
    unit's `content_sha256` to that unit's `blob_ref` first, and anything else as a CAS digest.
    """

    __slots__ = ("_aliases", "_cas")

    def __init__(self, cas: CasStore, aliases: Mapping[str, str] | None = None) -> None:
        self._cas = cas
        self._aliases = dict(aliases or {})

    def _digest(self, digest: str) -> str:
        wanted = self._aliases.get(digest, digest)
        return wanted.rsplit("/", 1)[-1].removeprefix("cas://")

    def path(self, digest: str) -> str:
        return str(self._cas.path(self._digest(digest)))

    def open(self, digest: str) -> BinaryIO:
        return self._cas.open(self._digest(digest))

    def put(self, data: bytes) -> str:
        from omniweave_core.blobs import format_ref  # noqa: PLC0415 -- the put path only

        return format_ref(self._cas.put(io.BytesIO(data)))


@dataclass(slots=True)
class _Call:
    """One unit's invocation state, held off the `DriverIO` so INV-6's field count stays four."""

    send: Callable[[wire.FrameKind, Mapping[str, object]], None]
    invoke_id: str
    unit_index: int
    cancelled: bool = False


_CALLS: weakref.WeakKeyDictionary[DriverIO, _Call] = weakref.WeakKeyDictionary()
"""io -> its call. The `inproc._STATE` idiom, for `inproc._STATE`'s reason."""


class WorkerIO(DriverIO):
    """The concrete `DriverIO` in a worker. FOUR FIELDS, all inherited; `__slots__ = ()`."""

    __slots__ = ()

    def service(self, name: str) -> ServiceHandle:
        """No Service is attached to a worker yet: 08 section 3.2's handles land with S3."""
        raise DriverError(
            cls=FailureClass.DRIVER_BUG,
            message=f"service({name!r}): no Service is attached to this S4 worker",
        )

    def cancelled(self) -> bool:
        call = _CALLS.get(self)
        return True if call is None else call.cancelled

    def log(self, event: str, **fields: Scalar) -> None:
        """One `LOG` frame, structured only (04:1701). Resets nothing on the host."""
        call = _CALLS.get(self)
        if call is not None:
            call.send(wire.FrameKind.LOG, {"level": "info", "event": event, "fields": fields})

    def progress(self, done: int, total: int | None) -> None:
        """One `PROGRESS` frame -- the only frame that resets the host's `progress_ms`."""
        call = _CALLS.get(self)
        if call is not None:
            call.send(
                wire.FrameKind.PROGRESS,
                {
                    "invoke_id": call.invoke_id,
                    "unit_index": call.unit_index,
                    "done": done,
                    "total": total,
                },
            )


# =============================================================================================
# 4. The RESULT header, and the one inline body
# =============================================================================================


def produced_header(
    produced: Sequence[ArtifactRef], blobs: WorkerBlobs
) -> tuple[list[dict[str, object]], bytes]:
    """`produced` as header entries plus the ONE inline body. The module docstring's rule.

    The first inline `doc_fragment` keeps its place in the body; every other inline ref is put in
    the CAS first. Order is preserved: the host rebuilds `produced` in this order, and the office
    driver's asset records name their refs by position.
    """
    entries: list[dict[str, object]] = []
    body = b""
    for ref in produced:
        if ref.inline is not None and not body and ref.kind == "doc_fragment":
            body = ref.inline
            entries.append({"kind": ref.kind, "byte_len": ref.byte_len, "inline": True})
            continue
        blob = ref.blob if ref.inline is None else blobs.put(ref.inline)
        entries.append({"kind": ref.kind, "byte_len": ref.byte_len, "blob": blob})
    return entries, body


def result_header(
    invoke_id: str, unit_index: int, result: DriverResult, entries: list[dict[str, object]]
) -> dict[str, object]:
    """`RESULT{invoke_id, unit_index, ...DriverResult}` for a success. 04:1700."""
    metrics = result.metrics
    return {
        "invoke_id": invoke_id,
        subproc.RESULT_UNIT_INDEX_KEY: unit_index,
        "outcome": result.outcome,
        "partial_reason": result.partial_reason,
        "produced": entries,
        "metrics": {
            "wall_ms": metrics.wall_ms,
            "cpu_ms": metrics.cpu_ms,
            "gpu_ms": metrics.gpu_ms,
            "tokens_in": metrics.tokens_in,
            "tokens_out": metrics.tokens_out,
            "calls": metrics.calls,
            "bytes_egress": metrics.bytes_egress,
            "bytes_read": metrics.bytes_read,
            "peak_rss_bytes": metrics.peak_rss_bytes,
        },
    }


def failure_header(invoke_id: str, unit_index: int, error: DriverError) -> dict[str, object]:
    """02:1060's five `DriverError` fields, which `subproc._result_of` reads back unchanged."""
    return {
        "invoke_id": invoke_id,
        subproc.RESULT_UNIT_INDEX_KEY: unit_index,
        "failure_class": error.cls.value,
        "message": error.message[:MESSAGE_MAX_CHARS],
        "retry_after_ms": error.retry_after_ms,
        "pages": list(error.pages),
        "limit": error.limit,
    }


def _bug(exc: BaseException) -> DriverError:
    """Anything a driver raised that is not a `DriverError` is `DRIVER_BUG`, with its type named.

    Permanent, which is 02:1014's direction for a class the driver did not choose: the host cannot
    tell a bug that will recur from one that will not, and a retry of a bug is a second bill.
    """
    return DriverError(
        cls=FailureClass.DRIVER_BUG,
        message=f"{type(exc).__name__}: {exc}"[:MESSAGE_MAX_CHARS],
    )


# =============================================================================================
# 5. The loop
# =============================================================================================


class _Channel:
    """The worker's channel with one lock around `sendall`: a driver may log from its own thread."""

    __slots__ = ("_channel", "_lock")

    def __init__(self, channel: subproc.ByteChannel) -> None:
        self._channel = channel
        self._lock = threading.Lock()

    def send(self, kind: wire.FrameKind, header: Mapping[str, object], body: bytes = b"") -> None:
        frame = wire.encode(kind, dict(header), body)  # type: ignore[arg-type]
        with self._lock:
            self._channel.sendall(frame)

    def next(self) -> wire.Frame | None:
        return subproc.next_frame(self._channel, expect=wire.Direction.HOST_TO_DRIVER)


def serve(
    channel: subproc.ByteChannel,
    *,
    find_card: Callable[[str], DriverCard | None] | None = None,
    guard: Callable[..., None] = install_egress_guard,
) -> int:
    """The whole conversation, over an already-connected channel. Returns the exit status.

    `find_card` and `guard` are parameters so the loop is testable in one process: a test passes a
    card lookup over a fixture and a guard that records its arming instead of installing a hook it
    could never take out. `main()` passes neither.
    """
    wired = _Channel(channel)
    hello = wired.next()
    if hello is None:
        return 0
    if hello.kind is not wire.FrameKind.HELLO:
        _fatal(wired, f"the first frame was {hello.kind.name}, not HELLO")
        return 1
    try:
        session = Session.of(hello.header)
        card = _card(session, find_card)
    except DriverHostError as refused:
        _fatal(wired, str(refused))
        return 1
    guard(armed=not card.hardware.needs_network or session.egress_mode == "none")
    try:
        driver = _construct(card, session)
    except DriverHostError as refused:
        _fatal(wired, str(refused))
        return 1
    wired.send(
        wire.FrameKind.HELLO_ACK,
        {
            "driver_id": card.identity.id,
            "version": card.identity.version,
            "schema_version": card.identity.schema_version,
            "port": f"{card.identity.port.value}/{card.identity.port_major}",
            "code_fingerprint": "",
            "isolation_granted": dict(session.isolation_granted),
        },
    )
    cas = _cas(session)
    while True:
        frame = wired.next()
        if frame is None or frame.kind is wire.FrameKind.SHUTDOWN:
            return 0
        if frame.kind is wire.FrameKind.INVOKE:
            _invoke(wired, driver, session, cas, frame)
            continue
        if frame.kind is wire.FrameKind.CANCEL:
            continue  # between units there is nothing in flight to cancel: `_invoke` is synchronous
        _fatal(wired, f"{frame.kind.name} is not served by this worker bootstrap")
        return 1


def _card(session: Session, find_card: Callable[[str], DriverCard | None] | None) -> DriverCard:
    """The card by id, from the catalog this process builds, and the host's digest checked.

    The host read its card from disk and so does the worker; they agree only if both read the same
    bytes, and `card_sha256` is how that is known rather than assumed (04:1696's mismatch row).
    """
    if session.port not in PORTS_SERVED:
        raise _refuse(f"{session.driver_id} is a {session.port} driver; this worker serves parse/1")
    lookup = find_card or _catalog_card
    card = lookup(session.driver_id)
    if card is None:
        raise _refuse(f"no installed card has id {session.driver_id!r}")
    if card.card_sha256 != session.card_sha256:
        raise DriverHostError(
            f"{session.driver_id}: the host's card is {session.card_sha256} and this worker's is "
            f"{card.card_sha256}",
            symbol="OW_CARD_CODE_MISMATCH",
            fix="reinstall the driver so the host and the worker read one driver.toml",
        )
    return card


def _catalog_card(driver_id: str) -> DriverCard | None:
    from omniweave_core.discovery import catalog  # noqa: PLC0415 -- a worker's first act only

    return catalog().cards.get(driver_id)


def _construct(card: DriverCard, session: Session) -> object:
    """`activate()` then `__init__(**effective_config)`. Both run the driver's code, so both are
    after the hook, and a raise from either is the host's `HELLO` failure, not a crash."""
    from omniweave_core.host.activate import activate  # noqa: PLC0415 -- after the hook

    loaded = activate(card)
    try:
        return loaded(**dict(session.effective_config))
    except Exception as exc:
        raise DriverHostError(
            f"{card.identity.id}.__init__ raised {type(exc).__name__}: {exc}",
            symbol="OW_DRIVER_ACTIVATION_FAILED",
            fix=f"ow drivers verify {card.identity.id}",
        ) from exc


def _cas(session: Session) -> CasStore:
    from omniweave_core.blobs import BlobStore  # noqa: PLC0415

    return BlobStore(session.blob_base)


def _units(header: Mapping[str, object]) -> tuple[tuple[UnitRef, str | None], ...]:
    raw = header.get("units")
    if not isinstance(raw, list) or not raw:
        raise _refuse("INVOKE carries no units list")
    out: list[tuple[UnitRef, str | None]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise _refuse("an INVOKE unit is not a table")
        blob = entry.get("blob_ref")
        out.append(
            (
                UnitRef(
                    uri=str(entry.get("uri", "")),
                    part=str(entry.get("part", "")),
                    content_sha256=str(entry.get("content_sha256", "")),
                    byte_len=int(entry.get("byte_len", 0) or 0),  # type: ignore[arg-type]
                    media_type=None
                    if entry.get("media_type") is None
                    else str(entry.get("media_type")),
                ),
                None if blob is None else str(blob),
            )
        )
    return tuple(out)


def _invoke(
    wired: _Channel, driver: object, session: Session, cas: CasStore, frame: wire.Frame
) -> None:
    """One `INVOKE`: one `RESULT` per unit, in unit order, whatever each unit did (04:1715)."""
    invoke_id = str(frame.header.get("invoke_id", ""))
    deadline_ms = int(frame.header.get("deadline_ms", 0) or 0)  # type: ignore[arg-type]
    units = _units(frame.header)
    aliases = {unit.content_sha256: blob for unit, blob in units if blob is not None}
    blobs = WorkerBlobs(cas, aliases)
    parse = getattr(driver, "parse", None)
    for index, (unit, _blob) in enumerate(units):
        scratch = Path(session.tmp) / invoke_id / str(index)
        scratch.mkdir(parents=True, exist_ok=True)
        io_obj = WorkerIO(
            blobs=blobs,
            tmpdir=str(scratch),
            deadline_ms=deadline_ms,
            max_output_bytes=session.max_output_bytes,
        )
        _CALLS[io_obj] = _Call(send=wired.send, invoke_id=invoke_id, unit_index=index)
        body = b""
        try:
            result = _parse_one(parse, unit, io_obj)
            entries, body = produced_header(result.produced, blobs)
            header = result_header(invoke_id, index, result, entries)
        except DriverError as error:
            header = failure_header(invoke_id, index, error)
        except Exception as exc:  # a driver may raise anything; the unit, not the worker, fails
            header = failure_header(invoke_id, index, _bug(exc))
        finally:
            # The scratch goes BEFORE the frame: once the host has read a unit's RESULT it may
            # reuse or inspect the tmp root, and nothing a RESULT names lives in scratch -- every
            # produced ref is inline or in the CAS by now.
            _CALLS.pop(io_obj, None)
            shutil.rmtree(scratch, ignore_errors=True)
        wired.send(wire.FrameKind.RESULT, header, body)
    shutil.rmtree(Path(session.tmp) / invoke_id, ignore_errors=True)


def _parse_one(parse: object, unit: UnitRef, io_obj: WorkerIO) -> DriverResult:
    """`parse(unit, PartSelector(), io)`; anything but a `DriverResult` is the driver's bug."""
    if not callable(parse):
        raise DriverError(cls=FailureClass.DRIVER_BUG, message="the driver has no parse()")
    result = parse(unit, PartSelector(), io_obj)
    if not isinstance(result, DriverResult):
        raise DriverError(
            cls=FailureClass.DRIVER_BUG,
            message=f"parse() returned {type(result).__name__}, not a DriverResult",
        )
    return result


def _fatal(wired: _Channel, detail: str) -> None:
    """`FATAL{failure_class, detail}` -- the driver's last words (04:1705). Best effort."""
    with contextlib.suppress(OSError, DriverHostError):
        wired.send(
            wire.FrameKind.FATAL,
            {"failure_class": FailureClass.DRIVER_BUG.value, "detail": detail[:MESSAGE_MAX_CHARS]},
        )


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m omniweave_core.host.worker <base address>`. The host's `SpawnRequest.argv`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        sys.stderr.write("usage: python -m omniweave_core.host.worker <base address>\n")
        return 2
    channel = subproc.connect(args[0])
    try:
        return serve(channel)
    finally:
        channel.close()
