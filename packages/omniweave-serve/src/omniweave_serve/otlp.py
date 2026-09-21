"""`ow trace export`'s reconstructor: NDJSON records in, OTLP/HTTP JSON out. 15 section 2.6.

> *"`ow trace export` is a **reconstructor**, not an emitter: it reads NDJSON shards, pairs
> `phase="start"` with `phase="end"` on `(trace_id, span_id)`, and builds OTLP. Nothing on the hot
> path knows OTLP exists."*

## NO SDK, AND THE REASON IS A DEPENDENCY BUDGET RATHER THAN A PREFERENCE

15:216: *"It also imports no `opentelemetry`. It writes **OTLP/HTTP JSON** -- the
`ExportTraceServiceRequest` message in its JSON encoding ... because the alternative fails a
dependency check the charter already ships: `omniweave-serve`'s declared dependencies are `core,
ports, mcp` under a 40 MB ceiling, and the OpenTelemetry SDK plus a gRPC channel does not fit
inside either."* `pyproject.toml` grants this module the only `TID251` exemption for
`opentelemetry` in the repository, and 15:222 calls that permission *"reserved and unused at
release 1"*. It stays unused here: nothing below imports it, and a test asserts that.

The JSON encoding is proto3's, which has two rules this file obeys and a reader would otherwise
have to guess at. A 64-bit integer is encoded as a **string**, so `startTimeUnixNano` is
`"1700000000000000000"` and never a float that has already lost the nanoseconds. A `traceId` and a
`spanId` are lowercase hex, which is what `Event` already carries, so neither is re-encoded.

## THE DURATION RULE, WHICH IS THE ONLY PLACE TWO CLOCKS MEET

15:245 states it as one table row: *"`startTimeUnixNano`/`endTimeUnixNano` from `ts_wall_ns`; the
duration is recomputed from `ts_mono_ns` and, if the two disagree by more than 1 ms, the monotonic
duration wins and `ow.clock_stepped=true` is set -- a wall clock steps and a stepped clock produces
negative durations a dashboard renders as zero."*

So a span's START is a wall reading, because that is what correlates with an external system, and
its LENGTH is a monotonic difference, because that is the only number a stepped clock cannot
corrupt. When they agree the end is the wall reading and nothing is flagged; when they do not, the
end becomes `start + monotonic duration` and the span carries the flag that says so. `Event`'s own
docstring is the warrant -- *"every duration is computed from `ts_mono_ns`"* -- and the 1 ms
tolerance is the plan's, not this module's.

## WHAT THIS MODULE DOES AND WHAT IT DELIBERATELY DOES NOT

It pairs, it maps, it batches, and it builds the two request documents. It does **not** POST, retry,
hold a cursor or tail a shard: 15:253-270's export mechanics are a second cell, and every property
worth testing lives on this side of that line. `batches()` yields the exact span lists a request
would carry, so the caller that eventually holds a socket decides nothing about what goes in one.

Five rows of 15:245's mapping table cannot be produced from an NDJSON stream at all, and
`unmapped()` reports them by name rather than leaving a reader to discover the gaps one dashboard
at a time. D357 through D361 are the entries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.contract import CONTRACT, RELEASE, SCHEMA
from omniweave_core.errors import UsageError
from omniweave_core.events import SEVERITY_NUMBER, Event, is_span_kind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from omniweave_core.config import Scalar

__all__ = [
    "CLOCK_STEPPED",
    "DEGRADATION_EVENT",
    "FORBIDDEN_RESOURCE_KEYS",
    "MAX_BATCH_BYTES",
    "MAX_BATCH_SPANS",
    "SCOPE_NAME",
    "SERVICE_NAME",
    "SKEW_TOLERANCE_NS",
    "SPAN_KIND_CLIENT",
    "SPAN_KIND_INTERNAL",
    "STATUS_CODE_ERROR",
    "STATUS_CODE_UNSET",
    "Pairing",
    "Resource",
    "Span",
    "attribute",
    "batches",
    "logs_request",
    "looks_absolute",
    "pair",
    "span_kind",
    "span_name",
    "traces_request",
    "unmapped",
]

SERVICE_NAME: Final = "omniweave"
"""`service.name`. 15:257, and the one resource attribute every OTLP consumer requires."""

SCOPE_NAME: Final = "omniweave.trace.export"
"""The instrumentation scope. Not a library name, because no library instrumented anything: the
records were written by `omniweave_core.events` and reconstructed here."""

SKEW_TOLERANCE_NS: Final = 1_000_000
"""15:245's *"disagree by more than 1 ms"*, in the nanoseconds both clocks are read in."""

CLOCK_STEPPED: Final = "ow.clock_stepped"
"""Set `true` on a span whose two clocks disagreed by more than `SKEW_TOLERANCE_NS`."""

DEGRADATION_EVENT: Final = "degradation"
"""15:252: a `Degradation` is *"a span event named `degradation` on the innermost open span"*."""

MAX_BATCH_SPANS: Final = 512
"""15:254's `--max-batch` default: spans per request."""

MAX_BATCH_BYTES: Final = 4 * 1024 * 1024
"""15:254's second bound, *"whichever binds first"*: 4 MiB of serialised JSON per request."""

SPAN_KIND_INTERNAL: Final = 1
SPAN_KIND_CLIENT: Final = 3
"""OTLP's `SpanKind` enum values. 15:247 uses exactly these two and no others."""

STATUS_CODE_UNSET: Final = 0
STATUS_CODE_ERROR: Final = 2
"""OTLP's `StatusCode`. `STATUS_CODE_OK` is 1 and is never emitted: 15:248 is explicit that
*"OTel's `OK` is an explicit assertion; we do not assert"*."""

FORBIDDEN_RESOURCE_KEYS: Final = (
    "host.id",
    "host.name",
    "os.user",
    "process.command_line",
)
"""15:259's **Never** list, sorted. A resource carrying one of these is refused, not stripped.

Stripping would make the exporter the last line of defence and a silent one; refusing makes the
attempt visible at the site that assembled the resource. The sixth item on that list -- *"or any
absolute path"* -- is a predicate rather than a key and `looks_absolute()` is it.
"""

_ABSOLUTE: Final = re.compile(r"^(?:/|\\\\|[A-Za-z]:[\\/])")
"""A POSIX root, a UNC share, or a drive letter. Three shapes, because a trace exported from a
Windows host reaches the same collector as one exported from a container."""

_ERROR_OUTCOMES: Final = ("cancelled", "failed_permanent", "failed_transient")
"""15:249: *"`failed_*`, `cancelled` -> `STATUS_CODE_ERROR`, description = `failure_class`"*."""

_UNSET_OUTCOMES: Final = (
    "deferred_budget",
    "ok",
    "ok_partial",
    "skipped_cached",
    "skipped_unchanged",
)
"""The other five of `Outcome`'s eight, sorted. Everything not in `_ERROR_OUTCOMES`."""

_UNROWED_OUTCOMES: Final = ("deferred_budget", "skipped_cached", "skipped_unchanged")
"""The three `Outcome` members 15:249's status table gives no row at all.

Mapped `UNSET` here for the reason the table gives `ok` -- *"OTel's `OK` is an explicit assertion;
we do not assert"* -- and because `ERROR` would paint a document red for having been cached. D360
records that the table covers five of eight."""


def looks_absolute(value: object) -> bool:
    """Whether a value is an absolute filesystem path under any of the three root shapes.

    15:259 bans *"any absolute path"* from the resource, and 15 section 12 is why: a path names a
    user, a project and often a customer, and a collector is a different trust domain from the
    machine that produced the trace.
    """
    return isinstance(value, str) and bool(_ABSOLUTE.match(value))


def attribute(key: str, value: Scalar) -> dict[str, object]:
    """One OTLP `KeyValue`. `bool` before `int`, because `bool` IS an `int` in Python.

    A `None` becomes an empty `stringValue` rather than being dropped: an attribute the producer
    declared and left empty is a different fact from one it never wrote, and OTLP has no null.
    """
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": "" if value is None else value}}


@dataclass(frozen=True, slots=True)
class Resource:
    """15:257's resource attributes, and nothing else may be added to one.

    `corpus_id` is `""` unless exactly one corpus is in scope, which is 15:258's *"only when one
    corpus is in scope"*: a resource is a property of the producing process, and a run that touched
    three corpora has no single one to name.
    """

    config_digest: str
    corpus_id: str = ""
    release: str = RELEASE
    contract: int = CONTRACT
    schema: int = SCHEMA

    def attributes(self) -> tuple[dict[str, object], ...]:
        """The `KeyValue` list, refusing anything 15:259 bans."""
        pairs: list[tuple[str, Scalar]] = [
            ("service.name", SERVICE_NAME),
            ("service.version", self.release),
            ("omniweave.contract", self.contract),
            ("omniweave.schema", self.schema),
            ("omniweave.config_digest", self.config_digest),
        ]
        if self.corpus_id:
            pairs.append(("omniweave.corpus_id", self.corpus_id))
        for key, value in pairs:
            if key in FORBIDDEN_RESOURCE_KEYS:  # pragma: no cover - no row spells a banned key
                raise _banned(key, "is on 15:259's Never list")
            if looks_absolute(value):
                raise _banned(key, f"holds an absolute path ({value!r})")
        return tuple(attribute(key, value) for key, value in pairs)

    def wire(self) -> dict[str, object]:
        """The `Resource` message."""
        return {"attributes": list(self.attributes())}


@dataclass(frozen=True, slots=True)
class Span:
    """One reconstructed span: a `start` record, its `end`, and whatever attached to it.

    Held as a typed row rather than assembled straight into JSON so that `batches()` can measure a
    span and `traces_request()` can order them, without either one re-deriving the mapping.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: int
    start_wall_ns: int
    end_wall_ns: int
    clock_stepped: bool
    status_code: int
    status_message: str
    attributes: tuple[dict[str, object], ...] = ()
    events: tuple[dict[str, object], ...] = ()

    def wire(self) -> dict[str, object]:
        """The `Span` message. Every 64-bit field is a string, which is proto3 JSON's rule."""
        out: dict[str, object] = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "startTimeUnixNano": str(self.start_wall_ns),
            "endTimeUnixNano": str(self.end_wall_ns),
            "attributes": [*self.attributes],
            "status": {"code": self.status_code},
        }
        if self.parent_span_id:
            out["parentSpanId"] = self.parent_span_id
        if self.status_message:
            out["status"] = {"code": self.status_code, "message": self.status_message}
        if self.clock_stepped:
            out["attributes"] = [*self.attributes, attribute(CLOCK_STEPPED, True)]
        if self.events:
            out["events"] = [*self.events]
        return out


@dataclass(frozen=True, slots=True)
class Pairing:
    """What a pass over one shard produced, including what it could not pair.

    **The unpaired halves are returned rather than dropped**, and 15:199 is the reason a dropped
    one would be the worst outcome: a hole *"is worse than no trace, because the hole is where the
    failure was"*. A `start` with no `end` is a crashed run, a killed process or a window that cut
    mid-span, which is exactly the case an operator is exporting a trace to look at. What this
    module cannot do is emit it, because an OTLP span with no `endTimeUnixNano` is not a span and
    the mapping table gives no row for one. D357.
    """

    spans: tuple[Span, ...] = ()
    points: tuple[Event, ...] = ()
    unterminated: tuple[Event, ...] = ()
    orphaned: tuple[Event, ...] = ()


def span_name(begin: Event) -> str:
    """15:246's five names, and the property that matters is what is NOT in them.

    *"low cardinality by construction: never a path, never a cite, never a query."* Each name is a
    level plus at most one declared field or envelope column -- a stage, an operator, a driver --
    and every one of those is drawn from a closed vocabulary or a registry id.
    """
    level = begin.spec().span
    if level is None:  # pragma: no cover - callers filter on `is_span_kind` first
        raise _not_a_span(begin.kind)
    if level == "run":
        return "run"
    if level == "plan":
        return f"plan/{begin.fields.get('stage', '')}"
    if level == "call":
        return f"call/{begin.driver or begin.fields.get('driver', '')}"
    return f"{level}/{begin.operator or ''}"


def span_kind(begin: Event) -> int:
    """`INTERNAL`, except a `call` reaching a Service or a provider.

    15:247: *"an S4 driver invocation is not a network call; a Service request is."* The two fields
    are `call.begin`'s own, and either being non-empty is enough: a Service request goes over
    loopback TCP and a provider call goes over the internet, and both are a client span.
    """
    if begin.spec().span != "call":
        return SPAN_KIND_INTERNAL
    reaches = begin.fields.get("service") or begin.fields.get("provider")
    return SPAN_KIND_CLIENT if reaches else SPAN_KIND_INTERNAL


def pair(events: Iterable[Event]) -> Pairing:
    """Pair `start` with `end` on `(trace_id, span_id)`, in one streaming pass.

    **Order is the stream's, not a sort.** `Event.seq` is per writer and the shard is append-only,
    so the records arrive in the order they were emitted and a span's `end` always follows its
    `start`; an `end` that arrives first is an `orphaned` record and named as one rather than
    buffered forever in case its partner turns up.

    A `degrade` point record attaches to the innermost span open on its own `(trace_id)` at the
    moment it is read, which is 15:252's *"innermost open span"* -- and it is also emitted as a
    point record in `points`, because the plan's table gives it a span-event row and the
    `LogRecord` row covers every point event without excluding it.
    """
    open_spans: dict[tuple[str, str], Event] = {}
    innermost: dict[str, list[tuple[str, str]]] = {}
    attached: dict[tuple[str, str], list[dict[str, object]]] = {}
    spans: list[Span] = []
    points: list[Event] = []
    orphaned: list[Event] = []

    for event in events:
        if not is_span_kind(event.kind):
            points.append(event)
            if event.fields.get("degradation_kind"):
                stack = innermost.get(event.trace_id, [])
                if stack:
                    attached.setdefault(stack[-1], []).append(_degradation(event))
            continue
        key = (event.trace_id, event.span_id)
        if event.phase == "start":
            open_spans[key] = event
            innermost.setdefault(event.trace_id, []).append(key)
            continue
        begin = open_spans.pop(key, None)
        if begin is None:
            orphaned.append(event)
            continue
        stack = innermost.get(event.trace_id, [])
        if key in stack:
            stack.remove(key)
        spans.append(_span(begin, event, tuple(attached.pop(key, ()))))

    return Pairing(
        spans=tuple(spans),
        points=tuple(points),
        unterminated=tuple(open_spans.values()),
        orphaned=tuple(orphaned),
    )


def batches(
    spans: Sequence[Span],
    *,
    max_spans: int = MAX_BATCH_SPANS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Iterator[tuple[Span, ...]]:
    """15:254's two bounds, *"whichever binds first"*.

    The byte bound is measured over the SERIALISED span rather than estimated, because the whole
    point of a 4 MiB cap is that a collector refuses a larger body and an estimate that was 5%
    optimistic fails the export rather than splitting the batch. A single span larger than
    `max_bytes` is yielded alone rather than dropped: it is over the cap either way, and an export
    that silently lost the largest span would lose the interesting one.
    """
    if max_spans < 1 or max_bytes < 1:
        raise UsageError(
            f"--max-batch is {max_spans} spans and {max_bytes} bytes; both are at least 1",
            fix=f"ow trace export --max-batch {MAX_BATCH_SPANS}",
        )
    current: list[Span] = []
    size = 0
    for span in spans:
        measured = len(json.dumps(span.wire(), separators=(",", ":")).encode("utf-8"))
        if current and (len(current) >= max_spans or size + measured > max_bytes):
            yield tuple(current)
            current, size = [], 0
        current.append(span)
        size += measured
    if current:
        yield tuple(current)


def traces_request(resource: Resource, spans: Sequence[Span]) -> dict[str, object]:
    """One `ExportTraceServiceRequest`, the body of a `POST {endpoint}/v1/traces`."""
    return {
        "resourceSpans": [
            {
                "resource": resource.wire(),
                "scopeSpans": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": RELEASE},
                        "spans": [span.wire() for span in spans],
                    }
                ],
            }
        ]
    }


def logs_request(resource: Resource, points: Sequence[Event]) -> dict[str, object]:
    """One `ExportLogsServiceRequest` from the point records. 15:250.

    *"a point `Event` -> `LogRecord` with `traceId`/`spanId` set ... `severityNumber` from
    section 8.1"*, and `SEVERITY_NUMBER` is that table, imported rather than restated.

    **Built, and not sendable.** 15:217 names one endpoint, `POST {endpoint}/v1/traces`, and OTLP
    puts logs on `/v1/logs`. `unmapped()` reports it; D359 is the entry.
    """
    return {
        "resourceLogs": [
            {
                "resource": resource.wire(),
                "scopeLogs": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": RELEASE},
                        "logRecords": [_log_record(event) for event in points],
                    }
                ],
            }
        ]
    }


def unmapped() -> tuple[str, ...]:
    """The rows of 15:245's mapping table this module cannot produce, and why.

    Reported rather than raised, because each is a gap in the mapping and not a defect in the
    records: everything that can be reconstructed is reconstructed, and a caller assembling an
    export can print this beside what it sent. `catalog.unservable()` is the same shape one
    artefact over.
    """
    return (
        "an unterminated span (a `start` with no `end`) has no OTLP encoding and no row in the "
        "mapping table, so a crashed run's outermost spans are reported by `Pairing.unterminated` "
        "and not exported -- 15:199 calls the hole 'where the failure was'. D357",
        "`Diag` is mapped to a `LogRecord` at WARN, and `Diag` is not an event kind: it is a store "
        "row, and this is a reconstructor over NDJSON shards. D358",
        "`logs_request()` has no endpoint: 15:217 names `POST {endpoint}/v1/traces` and OTLP puts "
        "a `LogRecord` on `/v1/logs`. D359",
        "`run.end` carries `status` and not `outcome`, so the status mapping does not reach the "
        "outermost span; and three of `Outcome`'s eight members have no row and are mapped UNSET "
        f"here: {', '.join(_UNROWED_OUTCOMES)}. D360",
        "`ow.partial_reason` has no field in the event vocabulary -- `partial_reason` is a "
        "`StepResult` field and no `[[event]]` row carries it -- so an `ok_partial` span is UNSET "
        "with nothing saying why. D361",
    )


def _span(begin: Event, end: Event, events: tuple[dict[str, object], ...]) -> Span:
    """One pair, with the duration rule applied and the status read off the `end` record."""
    monotonic = end.ts_mono_ns - begin.ts_mono_ns
    wall = end.ts_wall_ns - begin.ts_wall_ns
    stepped = abs(wall - monotonic) > SKEW_TOLERANCE_NS
    code, message = _status(end)
    return Span(
        trace_id=begin.trace_id,
        span_id=begin.span_id,
        parent_span_id=begin.parent_span_id,
        name=span_name(begin),
        kind=span_kind(begin),
        start_wall_ns=begin.ts_wall_ns,
        end_wall_ns=begin.ts_wall_ns + (monotonic if stepped else wall),
        clock_stepped=stepped,
        status_code=code,
        status_message=message,
        attributes=tuple(attribute(key, value) for key, value in sorted(end.fields.items())),
        events=events,
    )


def _status(end: Event) -> tuple[int, str]:
    """`(code, description)` from the `end` record's `outcome`, where it has one."""
    outcome = end.fields.get("outcome")
    if outcome in _ERROR_OUTCOMES:
        return STATUS_CODE_ERROR, str(end.fields.get("failure_class") or outcome)
    return STATUS_CODE_UNSET, ""


def _degradation(event: Event) -> dict[str, object]:
    """15:252's span event: one per record, carrying `kind` and `message`."""
    return {
        "timeUnixNano": str(event.ts_wall_ns),
        "name": DEGRADATION_EVENT,
        "attributes": [
            attribute("kind", event.fields.get("degradation_kind")),
            attribute("message", event.fields.get("message")),
        ],
    }


def _log_record(event: Event) -> dict[str, object]:
    """One point record as a `LogRecord`, with its trace context preserved."""
    return {
        "timeUnixNano": str(event.ts_wall_ns),
        "severityNumber": SEVERITY_NUMBER[event.level],
        "severityText": event.level,
        "body": {"stringValue": event.kind},
        "traceId": event.trace_id,
        "spanId": event.span_id,
        "attributes": [attribute(key, value) for key, value in sorted(event.fields.items())],
    }


def _banned(key: str, why: str) -> UsageError:
    """A resource attribute 15:259 forbids, refused where it was assembled."""
    return UsageError(
        f"the OTLP resource may not carry {key}: it {why}",
        fix="remove it from the Resource; 15-observability.md section 2.6 fixes the six it may "
        "carry",
    )


def _not_a_span(kind: str) -> UsageError:  # pragma: no cover - guarded by `is_span_kind`
    return UsageError(
        f"{kind} records a point and opens no span",
        fix="pass a span-shaped kind, or read it through `pair()` which filters them",
    )
