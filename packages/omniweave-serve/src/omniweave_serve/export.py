"""The export mechanics: batches out, a cursor back, and a failure that names where it stopped.

15:253 heads the paragraph this module implements, and the heading is the specification:
*"**Export mechanics, because 'then it POSTs' is not a design.**"*

> *"A non-2xx response or a socket error is retried three times with 1 s / 2 s / 4 s backoff, after
> which the export **stops and exits non-zero naming the last shard offset it committed**, so a
> re-run resumes rather than duplicating: the offset is written to
> `.omniweave/events/.export_cursor.json` keyed by `(endpoint_digest, run_id)`. Export is
> idempotent at the span level because a span id is stable across re-reads, so a duplicate arrival
> is a duplicate the collector deduplicates, never a double-count in omniweave."*

## THE ONE PROPERTY THE WHOLE DESIGN RESTS ON

**A re-run must resume rather than duplicate, and it is allowed to duplicate.** Those are not in
tension: the cursor makes a re-run start where the last one committed, and the span id makes a
duplicate harmless if it starts earlier. That asymmetry is what lets the cursor be written *after*
a request succeeds rather than inside it. A cursor written first would lose spans on a crash
between the write and the send, and lost spans are the one failure a collector cannot repair.

So the order here is fixed and is the same order 10 section 3.11(c) fixes for the emission ledger,
for the same reason one step over: **send, then record that you sent.**

## WHAT A FAILURE RETURNS INSTEAD OF RAISING

`Halted`, carrying the last committed offset, the attempt count and the last status. Not an
exception, and the reason is that 15:255's *"exits non-zero"* has no `OW-*` numeric: `codes.toml`
is append-only and allocating one is a plan decision under 18 section 9 item 7, not something a
module coins on its way past. D363 records the gap. The CLI owns exit codes (10 section 9.3) and is
the right place for both the code and the message, and it can build both from this object.

## `--dry-run --print-payload` PRINTS WHAT WOULD BE SENT, AND THAT IS A TESTABLE CLAIM

15:2024 asks for *"the exact OTLP JSON that **would** be sent"*. A rehearsal that re-derived the
payload from the same inputs by a second path would be a second answer, and the first time the two
drifted the printed payload would be a reassuring fiction. `rehearse()` and `export()` therefore
call one builder, and a test asserts the bytes `rehearse()` yields are byte-identical to the bytes
the transport is handed.

## WHAT THIS MODULE DOES NOT HOLD

A clock, a loop, and a socket. `sleep` is injected for `clock.py`'s reason -- a backoff ladder
driven by real seconds is a test that takes seven seconds to assert three retries -- and the socket
lives behind `Transport`, whose shipped implementation is the only part of this distribution that
dials anything. `tools/egress.toml` carries its `[[client]]` row.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from omniweave_core.errors import ConfigError

from omniweave_serve.otlp import traces_request

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_serve.otlp import Resource, Span

__all__ = [
    "BACKOFF_S",
    "CONTENT_TYPE",
    "CURSOR_NAME",
    "DELIVERED",
    "TRACES_PATH",
    "Delivered",
    "Exporter",
    "Halted",
    "Response",
    "Transport",
    "UrllibTransport",
    "cursor_key",
    "cursor_path",
    "endpoint_digest",
    "payload",
    "read_cursor",
    "traces_url",
    "write_cursor",
]

CURSOR_NAME: Final = ".export_cursor.json"
"""15:256's file, beside the shards it indexes. A dotfile because it is not a shard."""

BACKOFF_S: Final = (1.0, 2.0, 4.0)
"""15:254's ladder. Three retries, so four attempts, and the last wait is four seconds.

The tuple IS the retry count: a fourth entry is a fourth retry and one comment explains both.
"""

TRACES_PATH: Final = "/v1/traces"
"""15:217's path. `POST {endpoint}/v1/traces`, and `logs_request()` has no twin (D359)."""

CONTENT_TYPE: Final = "application/json"
"""15:217. OTLP/HTTP JSON, which is why nothing here imports `opentelemetry` or a protobuf."""

DELIVERED: Final = range(200, 300)
"""The status codes 15:254 counts as delivery. *"A non-2xx response ... is retried"*, so the
predicate is the whole 2xx class and not a list of the four an OTLP collector actually returns."""

_DIGEST_CHARS: Final = 16
"""How much of the endpoint's sha256 keys a cursor row.

Sixty-four bits of a digest over an operator-supplied URL, which needs to be collision-resistant
across the handful of endpoints one `.omniweave/` ever sees and not against an adversary choosing
both sides. The full digest is not used because the cursor is a file a human reads when an export
stops, and a 64-character key per row makes it unreadable at exactly that moment.
"""


@dataclass(frozen=True, slots=True)
class Response:
    """One HTTP answer, narrowed to what the retry rule reads.

    `status = 0` is a socket error: 15:254 treats *"a non-2xx response or a socket error"*
    identically, so they are one type with one predicate rather than two branches at every site.
    """

    status: int
    reason: str = ""

    def ok(self) -> bool:
        """Whether this delivery succeeded. 2xx and nothing else."""
        return self.status in DELIVERED


@runtime_checkable
class Transport(Protocol):
    """The one method an exporter needs, so a test can supply one in four lines.

    Narrow on purpose, in `AdmissionView`'s spirit: a Protocol listing only what is called is what
    lets the shipped `urllib` implementation and a recording fake satisfy one type with no shared
    base and no mocking library.
    """

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> Response:
        """Deliver one request. A socket error is a `Response(status=0)`, never an exception."""
        ...


@dataclass(frozen=True, slots=True)
class Delivered:
    """Every batch reached the collector."""

    requests: int
    spans: int
    offset: int
    """The last offset committed to the cursor, which a re-run resumes from."""


@dataclass(frozen=True, slots=True)
class Halted:
    """The export stopped. 15:255's *"exits non-zero naming the last shard offset it committed"*.

    `offset` is the committed one and not the one being attempted, which is the whole point: it is
    where a re-run starts, and starting there re-sends at most the batch that failed. Re-sending is
    free because a span id is stable across re-reads and the collector deduplicates; skipping is
    not, because nothing else will ever carry those spans.
    """

    requests: int
    spans: int
    offset: int
    attempts: int
    status: int
    reason: str

    def message(self) -> str:
        """One line naming what failed and where to resume, for the CLI to print. D363."""
        cause = f"HTTP {self.status}" if self.status else "a socket error"
        detail = f" ({self.reason})" if self.reason else ""
        return (
            f"trace export stopped after {self.attempts} attempts against {cause}{detail}; "
            f"{self.requests} request(s) and {self.spans} span(s) were delivered, and the "
            f"cursor is committed at offset {self.offset}"
        )


def endpoint_digest(endpoint: str) -> str:
    """The cursor's first key component. 15:256.

    A digest rather than the endpoint itself because a collector URL can carry a token in its query
    string, and `.omniweave/` is a directory people tar up and attach to issues.
    """
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def cursor_key(endpoint: str, run_id: str) -> str:
    """15:256's `(endpoint_digest, run_id)`, flattened for a JSON object's one-level keys."""
    return f"{endpoint_digest(endpoint)}:{run_id}"


def cursor_path(events_dir: Path) -> Path:
    """`.omniweave/events/.export_cursor.json`, beside the shards."""
    return events_dir / CURSOR_NAME


def read_cursor(path: Path, *, endpoint: str, run_id: str) -> int:
    """The committed offset for this `(endpoint, run)`, or `0`.

    **An unreadable or malformed cursor is `0`, never an error.** A cursor is an optimisation over
    re-sending, and 15:255 already licenses a duplicate arrival as harmless; refusing to export
    because a JSON file was truncated by a full disk would turn a recoverable duplicate into an
    unrecoverable gap. A cursor whose value is not a non-negative integer is treated as absent for
    the same reason.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(rows, dict):
        return 0
    offset = rows.get(cursor_key(endpoint, run_id))
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return 0
    return offset


def write_cursor(path: Path, *, endpoint: str, run_id: str, offset: int) -> None:
    """Commit an offset, preserving every other row, atomically.

    Atomic because `ow trace export` and `ow trace export --follow` can run against one
    `.omniweave/` at once, and a torn cursor read as `0` re-sends a whole run. Written into the
    same directory and `os.replace`d, which is atomic within a filesystem and is the only guarantee
    a rename gives.
    """
    if offset < 0:
        raise ConfigError(
            f"an export cursor of {offset}; an offset is a byte count and is never negative",
            fix="delete .omniweave/events/.export_cursor.json and re-run the export",
        )
    rows: dict[str, object] = {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        rows = parsed
    rows[cursor_key(endpoint, run_id)] = offset
    _replace(path, json.dumps(rows, indent=2, sort_keys=True) + "\n")


def traces_url(endpoint: str) -> str:
    """`{endpoint}/v1/traces`, with the operator's trailing slash tolerated and not doubled."""
    return endpoint.rstrip("/") + TRACES_PATH


def payload(resource: Resource, spans: Sequence[Span]) -> bytes:
    """One request body. The ONE builder, so a rehearsal cannot differ from a send.

    Compact separators because this is a wire format and not a file a human diffs; `sort_keys` is
    deliberately off, because OTLP's field order is the message's and re-sorting it would make the
    printed payload differ from every example a collector's documentation shows.
    """
    return json.dumps(traces_request(resource, spans), separators=(",", ":")).encode("utf-8")


class UrllibTransport:
    """The shipped `Transport`, and the only thing in this distribution that dials anything.

    `urllib.request` rather than a client library, for 15:216's reason one layer down: this
    distribution's declared dependencies are `core, ports, mcp` and a fifth would have to earn its
    place against a 40 MB ceiling to save eight lines. `tools/egress.toml` carries the
    `[[client]]` row, and the URL is operator data in every case -- `--otlp <endpoint>` or
    `[observe] otlp_endpoint` -- with no host compiled in anywhere.

    **Every error becomes a `Response`.** 15:254 treats a non-2xx and a socket error alike, so a
    caller that had to catch `URLError` as well as read a status would be implementing that rule
    twice. An `HTTPError` is a response with a status; everything else is `status=0`.
    """

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> Response:
        """One `POST`. Never raises: a transport error is a `Response`, per this class's rule."""
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as answer:  # noqa: S310
                return Response(status=answer.status, reason=answer.reason or "")
        except urllib.error.HTTPError as exc:
            return Response(status=exc.code, reason=exc.reason or "")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return Response(status=0, reason=str(exc))


class Exporter:
    """Batches in, requests out, a cursor behind. 15:253-258.

    `sleep` is injected and required: a retry ladder driven by real seconds makes asserting three
    retries a seven-second test, and `clock.py`'s argument for injecting time applies to waiting it
    as much as to reading it.
    """

    __slots__ = ("_backoff", "_sleep", "_transport")

    def __init__(
        self,
        *,
        transport: Transport,
        sleep: Callable[[float], None],
        backoff: Sequence[float] = BACKOFF_S,
    ) -> None:
        if any(wait < 0 for wait in backoff):
            raise ConfigError(
                f"a backoff ladder of {tuple(backoff)}; a wait is never negative",
                fix=f"use the shipped ladder {BACKOFF_S}",
            )
        self._transport = transport
        self._sleep = sleep
        self._backoff = tuple(backoff)

    @property
    def attempts(self) -> int:
        """One try plus one per rung. Four under the shipped ladder."""
        return 1 + len(self._backoff)

    def deliver(self, url: str, body: bytes) -> tuple[Response, int]:
        """One request, retried up the ladder. Returns the last response and the attempt count.

        The wait happens BETWEEN attempts and never after the last one: a ladder of three that
        slept after its final failure would add four seconds to the runtime of every failed export
        and change nothing about its outcome.
        """
        headers = {"Content-Type": CONTENT_TYPE}
        answer = self._transport.post(url, body, headers)
        if answer.ok():
            return answer, 1
        for index, wait in enumerate(self._backoff, start=2):
            self._sleep(wait)
            answer = self._transport.post(url, body, headers)
            if answer.ok():
                return answer, index
        return answer, self.attempts

    def rehearse(
        self, resource: Resource, batches: Iterable[tuple[int, Sequence[Span]]]
    ) -> tuple[bytes, ...]:
        """`--dry-run --print-payload`: the exact bodies `export()` would send, in order.

        Nothing is dialled and no cursor is written. The bytes come from the same `payload()` the
        send path uses, which is what makes 15:2024's *"would be sent"* a claim a test can hold.
        """
        return tuple(payload(resource, spans) for _, spans in batches)

    def export(
        self,
        resource: Resource,
        batches: Iterable[tuple[int, Sequence[Span]]],
        *,
        url: str,
        cursor: Path | None = None,
        endpoint: str = "",
        run_id: str = "",
        committed: int = 0,
    ) -> Delivered | Halted:
        """Send every batch in order, committing after each success and stopping at the first
        failure the ladder does not clear.

        **Send, then commit.** The cursor is written after the transport accepted the request and
        never before, which is 10 section 3.11(c)'s ordering one system over and for the same
        reason: a cursor written first loses spans on a crash in the gap, and 15:255 makes a
        duplicate harmless while nothing makes a gap recoverable.

        `committed` is where this run started, so a `Halted` on the very first batch still names an
        offset a re-run can resume from rather than `0`.
        """
        requests = 0
        spans_sent = 0
        for offset, spans in batches:
            answer, attempts = self.deliver(url, payload(resource, spans))
            if not answer.ok():
                return Halted(
                    requests=requests,
                    spans=spans_sent,
                    offset=committed,
                    attempts=attempts,
                    status=answer.status,
                    reason=answer.reason,
                )
            requests += 1
            spans_sent += len(spans)
            committed = offset
            if cursor is not None:
                write_cursor(cursor, endpoint=endpoint, run_id=run_id, offset=committed)
        return Delivered(requests=requests, spans=spans_sent, offset=committed)


def _replace(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: a sibling temp file, then `os.replace`.

    A sibling and not `/tmp`, because `os.replace` is atomic only within one filesystem and a temp
    directory is often another one. `omniweave.install.atomic_write` is the same six lines in a
    distribution this one may not import; see the measurement note in D363's batch.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
        Path(temporary).replace(path)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
