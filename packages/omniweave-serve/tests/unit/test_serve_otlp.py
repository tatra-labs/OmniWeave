"""The reconstructor, over streams built by hand a record at a time.

**Every input here is an `Event` this repository's own vocabulary permits**, built through a helper
that calls `validate()`, so a test cannot assert a mapping over a record `omniweave_core.events`
would have refused at the sink. That matters more here than in most files: this module's whole job
is to translate a closed vocabulary, and a test working from records outside it would be checking a
translation of something that never gets written.

**The two clocks are driven apart on purpose.** The duration rule is the only place in the export
where two sources of time meet, and it is the one an operator notices only as a dashboard full of
zero-length spans months later.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import omniweave_serve.otlp as otlp_module
import pytest
from omniweave_core.contract import CONTRACT, RELEASE, SCHEMA
from omniweave_core.errors import UsageError
from omniweave_core.events import EVENTS, SEVERITY_NUMBER, Event, EventKind
from omniweave_core.operator import Outcome
from omniweave_serve.otlp import (
    CLOCK_STEPPED,
    DEGRADATION_EVENT,
    FORBIDDEN_RESOURCE_KEYS,
    MAX_BATCH_BYTES,
    MAX_BATCH_SPANS,
    SCOPE_NAME,
    SERVICE_NAME,
    SKEW_TOLERANCE_NS,
    SPAN_KIND_CLIENT,
    SPAN_KIND_INTERNAL,
    STATUS_CODE_ERROR,
    STATUS_CODE_UNSET,
    Resource,
    Span,
    attribute,
    batches,
    logs_request,
    looks_absolute,
    pair,
    span_kind,
    span_name,
    traces_request,
    unmapped,
)

TRACE = "0af7651916cd43dd8448eb211c80319c"
SPAN = "b7ad6b7169203331"
OTHER = "00f067aa0ba902b7"
MS = 1_000_000
"""One millisecond in nanoseconds, which is exactly `SKEW_TOLERANCE_NS`."""


def _event(kind: str, **over: object) -> Event:
    """One record, validated against the closed vocabulary before a test may use it."""
    values: dict[str, Any] = {
        "ts_wall_ns": 1_700_000_000_000_000_000,
        "ts_mono_ns": 5_000_000_000,
        "run_id": "r_01J0000000000000000000000",
        "writer_id": "abc123abc123",
        "seq": 1,
        "trace_id": TRACE,
        "span_id": SPAN,
        "parent_span_id": None,
        "kind": kind,
        "phase": "point",
        "level": "info",
        "fields": {},
    }
    values.update(over)
    spec = Event(**values).spec()
    if spec.span is not None:
        values["phase"] = spec.phase.value
    values["level"] = spec.level.value
    event = Event(**values)
    event.validate()
    return event


def _run(**over: object) -> tuple[Event, Event]:
    """A `run` span: one `start`, one `end`, one millisecond apart on both clocks."""
    begin = _event("run.start", **over)
    end = _event(
        "run.end",
        ts_wall_ns=begin.ts_wall_ns + 250 * MS,
        ts_mono_ns=begin.ts_mono_ns + 250 * MS,
        seq=2,
        **over,
    )
    return begin, end


def _resource() -> Resource:
    return Resource(config_digest="3b8a1f4c" * 8)


# ---------------------------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------------------------


def test_a_start_and_an_end_on_one_key_become_one_span() -> None:
    begin, end = _run()
    result = pair([begin, end])
    assert len(result.spans) == 1
    assert result.unterminated == ()
    assert result.orphaned == ()
    span = result.spans[0]
    assert span.trace_id == TRACE
    assert span.span_id == SPAN
    assert span.start_wall_ns == begin.ts_wall_ns
    assert span.end_wall_ns == end.ts_wall_ns


def test_two_spans_on_one_trace_are_paired_independently() -> None:
    outer_begin, outer_end = _run()
    inner_begin = _event("plan.begin", span_id=OTHER, parent_span_id=SPAN, fields={"stage": "plan"})
    inner_end = _event(
        "plan.end",
        span_id=OTHER,
        parent_span_id=SPAN,
        ts_wall_ns=inner_begin.ts_wall_ns + 10 * MS,
        ts_mono_ns=inner_begin.ts_mono_ns + 10 * MS,
        fields={"stage": "plan", "elapsed_ms": 10},
    )
    result = pair([outer_begin, inner_begin, inner_end, outer_end])
    assert {span.span_id for span in result.spans} == {SPAN, OTHER}
    inner = next(s for s in result.spans if s.span_id == OTHER)
    assert inner.parent_span_id == SPAN


def test_a_start_with_no_end_is_reported_and_not_exported() -> None:
    """D357. 15:199 -- a hole *"is worse than no trace, because the hole is where the failure
    was"* -- and an OTLP span with no `endTimeUnixNano` is not a span."""
    begin, _ = _run()
    result = pair([begin])
    assert result.spans == ()
    assert result.unterminated == (begin,)


def test_an_end_with_no_start_is_named_rather_than_buffered() -> None:
    """A window that cut mid-span. Holding it in case its partner turns up is a leak with no
    bound, because in a truncated stream the partner never does."""
    _, end = _run()
    result = pair([end])
    assert result.spans == ()
    assert result.orphaned == (end,)


def test_point_records_are_collected_separately() -> None:
    begin, end = _run()
    point = _event(EventKind.CACHE_HIT, fields={"layer": "call"})
    result = pair([begin, point, end])
    assert len(result.spans) == 1
    assert result.points == (point,)


def test_an_empty_stream_produces_an_empty_pairing() -> None:
    result = pair([])
    assert result.spans == result.points == result.unterminated == result.orphaned == ()


# ---------------------------------------------------------------------------------------------
# The duration rule, which is the only place two clocks meet
# ---------------------------------------------------------------------------------------------


def test_agreeing_clocks_use_the_wall_reading_and_flag_nothing() -> None:
    span = pair(_run()).spans[0]
    assert span.clock_stepped is False
    assert span.end_wall_ns - span.start_wall_ns == 250 * MS
    assert CLOCK_STEPPED not in json.dumps(span.wire())


def test_a_wall_clock_that_stepped_forward_loses_to_the_monotonic_duration() -> None:
    """A wall clock steps; a monotonic one does not. 15:245 gives the monotonic duration the win
    and requires the span to say so."""
    begin = _event("run.start")
    end = _event(
        "run.end",
        ts_wall_ns=begin.ts_wall_ns + 3600 * 1_000 * MS,
        ts_mono_ns=begin.ts_mono_ns + 250 * MS,
        seq=2,
    )
    span = pair([begin, end]).spans[0]
    assert span.clock_stepped is True
    assert span.end_wall_ns - span.start_wall_ns == 250 * MS, "the monotonic duration wins"
    assert attribute(CLOCK_STEPPED, True) in span.wire()["attributes"]  # type: ignore[operator]


def test_a_wall_clock_that_stepped_backward_produces_no_negative_duration() -> None:
    """*"a stepped clock produces negative durations a dashboard renders as zero"* -- which is the
    failure mode the rule exists to prevent, and it is the one worth asserting."""
    begin = _event("run.start")
    end = _event(
        "run.end",
        ts_wall_ns=begin.ts_wall_ns - 5_000 * MS,
        ts_mono_ns=begin.ts_mono_ns + 40 * MS,
        seq=2,
    )
    span = pair([begin, end]).spans[0]
    assert span.clock_stepped is True
    assert span.end_wall_ns > span.start_wall_ns
    assert span.end_wall_ns - span.start_wall_ns == 40 * MS


@pytest.mark.parametrize("drift_ns", [0, SKEW_TOLERANCE_NS])
def test_drift_at_or_under_the_tolerance_is_not_a_step(drift_ns: int) -> None:
    begin = _event("run.start")
    end = _event(
        "run.end",
        ts_wall_ns=begin.ts_wall_ns + 250 * MS + drift_ns,
        ts_mono_ns=begin.ts_mono_ns + 250 * MS,
        seq=2,
    )
    assert pair([begin, end]).spans[0].clock_stepped is False


def test_drift_one_nanosecond_past_the_tolerance_is() -> None:
    begin = _event("run.start")
    end = _event(
        "run.end",
        ts_wall_ns=begin.ts_wall_ns + 250 * MS + SKEW_TOLERANCE_NS + 1,
        ts_mono_ns=begin.ts_mono_ns + 250 * MS,
        seq=2,
    )
    assert pair([begin, end]).spans[0].clock_stepped is True


# ---------------------------------------------------------------------------------------------
# Names and kinds
# ---------------------------------------------------------------------------------------------


def test_the_five_span_names() -> None:
    """15:246. Low cardinality by construction: never a path, never a cite, never a query."""
    assert span_name(_event("run.start")) == "run"
    assert span_name(_event("plan.begin", fields={"stage": "parse"})) == "plan/parse"
    assert span_name(_event("unit.begin", operator="parse.pdf")) == "unit/parse.pdf"
    assert (
        span_name(_event("attempt.begin", operator="parse.pdf", fields={"attempt": 2}))
        == "attempt/parse.pdf"
    )
    assert span_name(_event("call.begin", driver="parse.pdf.pdfium")) == "call/parse.pdf.pdfium"


def test_a_span_name_carries_nothing_a_document_supplied() -> None:
    """The property, restated as a check over the names the vocabulary can produce: each one is a
    level plus a stage, an operator or a driver, all of which are registry ids."""
    begin = _event("call.begin", driver="parse.pdf.pdfium", unit="file:///x/y.pdf", part="p3")
    name = span_name(begin)
    assert "/x/y.pdf" not in name
    assert "p3" not in name


def test_every_span_is_internal_except_a_call_that_reaches_out() -> None:
    for kind in ("run.start", "plan.begin", "unit.begin", "attempt.begin", "call.begin"):
        assert span_kind(_event(kind)) == SPAN_KIND_INTERNAL


@pytest.mark.parametrize("reach", ["service", "provider"])
def test_a_call_naming_a_service_or_a_provider_is_a_client_span(reach: str) -> None:
    """15:247: *"an S4 driver invocation is not a network call; a Service request is."*"""
    assert span_kind(_event("call.begin", fields={reach: "vlm"})) == SPAN_KIND_CLIENT


def test_an_empty_service_field_is_not_a_client_span() -> None:
    assert span_kind(_event("call.begin", fields={"service": ""})) == SPAN_KIND_INTERNAL


# ---------------------------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------------------------


def _unit(outcome: str, **fields: object) -> Span:
    begin = _event("unit.begin", operator="parse.pdf")
    end = _event(
        "unit.complete",
        operator="parse.pdf",
        ts_wall_ns=begin.ts_wall_ns + MS,
        ts_mono_ns=begin.ts_mono_ns + MS,
        seq=2,
        fields={"outcome": outcome, **fields},
    )
    return pair([begin, end]).spans[0]


def test_ok_asserts_nothing() -> None:
    """15:248: *"OTel's `OK` is an explicit assertion; we do not assert."* `STATUS_CODE_OK` is 1
    and is never emitted by this module."""
    span = _unit(Outcome.OK.value)
    assert span.status_code == STATUS_CODE_UNSET
    assert span.wire()["status"] == {"code": 0}
    assert STATUS_CODE_UNSET == 0
    assert STATUS_CODE_ERROR == 2, "1 is STATUS_CODE_OK and is not among the codes this emits"
    emitted = {_unit(member.value).status_code for member in Outcome}
    assert 1 not in emitted


def test_ok_partial_is_unset_because_otel_has_no_partial_state() -> None:
    """*"`ERROR` would paint every escalated document red."*"""
    assert _unit(Outcome.OK_PARTIAL.value).status_code == STATUS_CODE_UNSET


@pytest.mark.parametrize(
    "outcome", [Outcome.FAILED_TRANSIENT.value, Outcome.FAILED_PERMANENT.value]
)
def test_a_failure_is_an_error_described_by_its_failure_class(outcome: str) -> None:
    begin = _event("attempt.begin", operator="parse.pdf", fields={"attempt": 1})
    end = _event(
        "attempt.end",
        operator="parse.pdf",
        ts_wall_ns=begin.ts_wall_ns + MS,
        ts_mono_ns=begin.ts_mono_ns + MS,
        seq=2,
        fields={"attempt": 1, "outcome": outcome, "failure_class": "timeout"},
    )
    span = pair([begin, end]).spans[0]
    assert span.status_code == STATUS_CODE_ERROR
    assert span.status_message == "timeout"
    assert span.wire()["status"] == {"code": 2, "message": "timeout"}


def test_cancelled_is_an_error_and_falls_back_to_the_outcome_when_unclassified() -> None:
    """*"never the driver's stderr"* -- so where there is no `failure_class` the description is
    the outcome name and not a message from the process that died."""
    span = _unit(Outcome.CANCELLED.value)
    assert span.status_code == STATUS_CODE_ERROR
    assert span.status_message == Outcome.CANCELLED.value


@pytest.mark.parametrize(
    "outcome",
    [Outcome.SKIPPED_CACHED.value, Outcome.SKIPPED_UNCHANGED.value, Outcome.DEFERRED_BUDGET.value],
)
def test_the_three_outcomes_with_no_row_are_unset_and_never_red(outcome: str) -> None:
    """D360. 15:249's table covers five of `Outcome`'s eight members. `ERROR` would paint a
    document red for having been cached."""
    assert _unit(outcome).status_code == STATUS_CODE_UNSET


def test_every_outcome_member_maps_somewhere() -> None:
    """The count is the assertion: a ninth member added to `Outcome` without a decision here
    would silently take the UNSET branch."""
    codes = {member.value: _unit(member.value).status_code for member in Outcome}
    assert len(codes) == 8
    assert set(codes.values()) == {STATUS_CODE_UNSET, STATUS_CODE_ERROR}


def test_a_span_whose_end_carries_no_outcome_is_unset() -> None:
    """`plan.end` and `call.end` have no `outcome` field at all."""
    assert pair(_run()).spans[0].status_code == STATUS_CODE_UNSET


# ---------------------------------------------------------------------------------------------
# Degradations
# ---------------------------------------------------------------------------------------------


def test_a_degradation_attaches_to_the_innermost_open_span() -> None:
    """15:252, and "innermost" is the whole content of the rule: attaching it to the run span
    would put every degradation in a trace on one row."""
    outer_begin, outer_end = _run()
    inner_begin = _event("unit.begin", span_id=OTHER, parent_span_id=SPAN, operator="parse.pdf")
    degrade = _event(
        "degrade",
        span_id=OTHER,
        fields={"degradation_kind": "layout_unavailable", "message": "no detector"},
    )
    inner_end = _event(
        "unit.complete",
        span_id=OTHER,
        parent_span_id=SPAN,
        operator="parse.pdf",
        ts_wall_ns=inner_begin.ts_wall_ns + MS,
        ts_mono_ns=inner_begin.ts_mono_ns + MS,
        fields={"outcome": "ok_partial"},
    )
    result = pair([outer_begin, inner_begin, degrade, inner_end, outer_end])
    inner = next(s for s in result.spans if s.span_id == OTHER)
    outer = next(s for s in result.spans if s.span_id == SPAN)
    assert len(inner.events) == 1
    assert outer.events == ()
    assert inner.events[0]["name"] == DEGRADATION_EVENT


def test_a_degradation_carries_its_kind_and_message_and_nothing_else() -> None:
    outer_begin, outer_end = _run()
    degrade = _event(
        "degrade", fields={"degradation_kind": "events_dropped", "message": "queue full"}
    )
    result = pair([outer_begin, degrade, outer_end])
    event = result.spans[0].events[0]
    keys = {row["key"] for row in event["attributes"]}  # type: ignore[union-attr,index]
    assert keys == {"kind", "message"}


def test_a_degradation_with_no_open_span_is_still_a_point_record() -> None:
    """It is not dropped: 15:250 maps every point record to a `LogRecord` regardless."""
    degrade = _event("degrade", fields={"degradation_kind": "events_dropped", "message": "x"})
    result = pair([degrade])
    assert result.points == (degrade,)
    assert result.spans == ()


def test_a_degradation_is_a_span_event_and_a_point_record_both() -> None:
    """Two rows of the mapping table cover it, and neither excludes the other."""
    begin, end = _run()
    degrade = _event("degrade", fields={"degradation_kind": "events_dropped", "message": "x"})
    result = pair([begin, degrade, end])
    assert len(result.spans[0].events) == 1
    assert result.points == (degrade,)


# ---------------------------------------------------------------------------------------------
# The resource, and what it may never carry
# ---------------------------------------------------------------------------------------------


def test_the_resource_carries_the_five_the_plan_lists() -> None:
    keys = {row["key"] for row in _resource().attributes()}  # type: ignore[index]
    assert keys == {
        "service.name",
        "service.version",
        "omniweave.contract",
        "omniweave.schema",
        "omniweave.config_digest",
    }


def test_the_resource_values_come_from_the_contract_module() -> None:
    rows = {row["key"]: row["value"] for row in _resource().attributes()}  # type: ignore[index]
    assert rows["service.name"] == {"stringValue": SERVICE_NAME}
    assert rows["service.version"] == {"stringValue": RELEASE}
    assert rows["omniweave.contract"] == {"intValue": str(CONTRACT)}
    assert rows["omniweave.schema"] == {"intValue": str(SCHEMA)}


def test_a_corpus_id_appears_only_when_one_corpus_is_in_scope() -> None:
    """15:258. A run that touched three corpora has no single one to name."""
    without = {row["key"] for row in _resource().attributes()}  # type: ignore[index]
    assert "omniweave.corpus_id" not in without
    with_one = Resource(config_digest="a" * 64, corpus_id="handbook")
    assert "omniweave.corpus_id" in {row["key"] for row in with_one.attributes()}  # type: ignore[index]


@pytest.mark.parametrize(
    "value",
    ["/home/u/corpus", "/", "C:\\Users\\u\\corpus", "c:/Users/u", "\\\\share\\corpus"],
)
def test_an_absolute_path_is_recognised_under_three_root_shapes(value: str) -> None:
    """A trace exported from a Windows host reaches the same collector as one from a container."""
    assert looks_absolute(value) is True


@pytest.mark.parametrize("value", ["handbook", "relative/path", "", "sha256:ab", 7, None, True])
def test_these_are_not_absolute_paths(value: object) -> None:
    assert looks_absolute(value) is False


def test_a_resource_holding_an_absolute_path_is_refused_and_not_stripped() -> None:
    """15:259, and refusing rather than stripping is the choice: a silent strip makes the exporter
    the last line of defence and hides that something upstream put a path in a resource."""
    with pytest.raises(UsageError, match="absolute path"):
        Resource(config_digest="a" * 64, corpus_id="/srv/corpora/handbook").attributes()


def test_the_never_list_is_the_plans_four_keys() -> None:
    assert FORBIDDEN_RESOURCE_KEYS == ("host.id", "host.name", "os.user", "process.command_line")
    assert list(FORBIDDEN_RESOURCE_KEYS) == sorted(FORBIDDEN_RESOURCE_KEYS)


def test_no_banned_key_can_reach_a_resource_because_none_is_a_field() -> None:
    """The structural half of 15:259: the four keys are not attributes a caller can set, because
    `Resource` has no field that produces one."""
    produced = {row["key"] for row in Resource(config_digest="a" * 64).attributes()}  # type: ignore[index]
    assert produced.isdisjoint(FORBIDDEN_RESOURCE_KEYS)


# ---------------------------------------------------------------------------------------------
# The two request documents
# ---------------------------------------------------------------------------------------------


def test_a_traces_request_is_shaped_the_way_a_collector_reads_one() -> None:
    spans = pair(_run()).spans
    body = traces_request(_resource(), spans)
    resource_spans = body["resourceSpans"]
    assert isinstance(resource_spans, list)
    scope_spans = resource_spans[0]["scopeSpans"]
    assert scope_spans[0]["scope"] == {"name": SCOPE_NAME, "version": RELEASE}
    assert len(scope_spans[0]["spans"]) == 1


def test_every_sixty_four_bit_field_is_a_string() -> None:
    """proto3's JSON mapping, and the reason it matters: a nanosecond timestamp in a JSON number
    is a double, and a double has fifty-three bits of mantissa."""
    span = pair(_run()).spans[0].wire()
    assert isinstance(span["startTimeUnixNano"], str)
    assert isinstance(span["endTimeUnixNano"], str)
    assert int(span["startTimeUnixNano"]) > 2**53, "the value really does exceed a double"


def test_a_root_span_carries_no_parent_span_id_key_at_all() -> None:
    """`parent_span_id` is `None` only on a `run` span, and OTLP has no null: the key is absent."""
    assert "parentSpanId" not in pair(_run()).spans[0].wire()


def test_a_child_span_carries_its_parent() -> None:
    begin = _event("unit.begin", span_id=OTHER, parent_span_id=SPAN, operator="parse.pdf")
    end = _event(
        "unit.complete",
        span_id=OTHER,
        parent_span_id=SPAN,
        operator="parse.pdf",
        ts_wall_ns=begin.ts_wall_ns + MS,
        ts_mono_ns=begin.ts_mono_ns + MS,
        fields={"outcome": "ok"},
    )
    assert pair([begin, end]).spans[0].wire()["parentSpanId"] == SPAN


def test_a_logs_request_carries_the_severity_table_from_core() -> None:
    """15:250's `severityNumber` *"from section 8.1"*, which `omniweave_core.events` already
    holds; a second copy here would be a second answer to one question."""
    point = _event(EventKind.DRIVER_CRASH, fields={"driver": "d", "failure_class": "crash"})
    body = logs_request(_resource(), [point])
    record = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]  # type: ignore[index]
    assert record["severityNumber"] == SEVERITY_NUMBER[point.level]
    assert record["severityText"] == point.level
    assert record["body"] == {"stringValue": point.kind}


def test_a_log_record_keeps_its_trace_context() -> None:
    """15:250: *"a `LogRecord` with `traceId`/`spanId` set"*. A log without them is a line in a
    file; with them it is the reason the span next to it failed."""
    point = _event(EventKind.CACHE_HIT, fields={"layer": "call"})
    record = logs_request(_resource(), [point])["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]  # type: ignore[index]
    assert record["traceId"] == TRACE
    assert record["spanId"] == SPAN


# ---------------------------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------------------------


def test_a_bool_is_a_bool_and_not_an_int() -> None:
    """`bool` IS an `int` in Python, so the order of the branches is the whole test."""
    assert attribute("k", True) == {"key": "k", "value": {"boolValue": True}}
    assert attribute("k", 1) == {"key": "k", "value": {"intValue": "1"}}


def test_an_int_attribute_is_a_string_and_a_float_is_not() -> None:
    assert attribute("k", 2**60) == {"key": "k", "value": {"intValue": str(2**60)}}
    assert attribute("k", 0.5) == {"key": "k", "value": {"doubleValue": 0.5}}


def test_none_becomes_an_empty_string_rather_than_disappearing() -> None:
    """An attribute the producer declared and left empty is a different fact from one it never
    wrote, and OTLP has no null."""
    assert attribute("k", None) == {"key": "k", "value": {"stringValue": ""}}


def test_span_attributes_are_sorted_so_two_exports_of_one_shard_agree() -> None:
    span = _unit("ok", queued_ms=3, ran_ms=40)
    keys = [str(row["key"]) for row in span.attributes]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------------------------


def _spans(count: int) -> list[Span]:
    return [
        Span(
            trace_id=TRACE,
            span_id=f"{index:016x}",
            parent_span_id=None,
            name="run",
            kind=SPAN_KIND_INTERNAL,
            start_wall_ns=1,
            end_wall_ns=2,
            clock_stepped=False,
            status_code=STATUS_CODE_UNSET,
            status_message="",
        )
        for index in range(count)
    ]


def test_the_span_count_binds_first_when_it_is_the_smaller_bound() -> None:
    sizes = [len(batch) for batch in batches(_spans(1100))]
    assert sizes == [MAX_BATCH_SPANS, MAX_BATCH_SPANS, 1100 - 2 * MAX_BATCH_SPANS]


def test_the_byte_bound_binds_first_when_it_is() -> None:
    """*"whichever binds first"*, and the bytes are MEASURED rather than estimated: a collector
    refuses an oversized body, and an estimate 5% optimistic fails the export."""
    sizes = [len(batch) for batch in batches(_spans(40), max_bytes=400)]
    assert max(sizes) < 40
    for batch in batches(_spans(40), max_bytes=400):
        measured = len(json.dumps([s.wire() for s in batch], separators=(",", ":")))
        assert measured <= 400 + 2


def test_a_single_span_over_the_cap_is_yielded_alone_and_not_dropped() -> None:
    """It is over the cap either way, and an export that silently lost the largest span would
    lose the interesting one."""
    batch_list = list(batches(_spans(3), max_bytes=1))
    assert [len(batch) for batch in batch_list] == [1, 1, 1]


def test_no_spans_yields_no_requests() -> None:
    assert list(batches([])) == []


def test_the_shipped_bounds_are_the_plans() -> None:
    assert MAX_BATCH_SPANS == 512
    assert MAX_BATCH_BYTES == 4 * 1024 * 1024


@pytest.mark.parametrize(("spans", "byte_cap"), [(0, 1), (1, 0), (-1, 10), (10, -1)])
def test_a_bound_below_one_is_refused(spans: int, byte_cap: int) -> None:
    with pytest.raises(UsageError, match="at least 1"):
        list(batches(_spans(1), max_spans=spans, max_bytes=byte_cap))


# ---------------------------------------------------------------------------------------------
# What cannot be produced, said out loud
# ---------------------------------------------------------------------------------------------


def test_unmapped_names_five_rows_and_each_one_cites_its_entry() -> None:
    rows = unmapped()
    assert len(rows) == 5
    assert [f"D{357 + index}" in row for index, row in enumerate(rows)] == [True] * 5


def test_unmapped_names_the_thing_that_cannot_be_reconstructed_in_each_case() -> None:
    joined = " ".join(unmapped())
    assert "unterminated" in joined
    assert "`Diag`" in joined
    assert "/v1/logs" in joined
    assert "`run.end` carries `status`" in joined
    assert "ow.partial_reason" in joined


def test_partial_reason_really_has_no_field_in_the_vocabulary() -> None:
    """D361, asserted against the vocabulary rather than asserted in prose: `partial_reason` is a
    `StepResult` field and no `[[event]]` row carries it, so an `ok_partial` span has nothing to
    say why."""
    assert not [kind for kind, spec in EVENTS.items() if "partial_reason" in spec.fields]


def test_run_end_really_carries_status_and_not_outcome() -> None:
    """D360, the same way."""
    assert "status" in EVENTS["run.end"].fields
    assert "outcome" not in EVENTS["run.end"].fields


def test_diag_really_is_not_an_event_kind() -> None:
    """D358. The mapping table's `Diag` row names a store row, and this is a reconstructor over
    NDJSON shards."""
    assert not [kind for kind in EVENTS if kind.startswith("diag")]


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(otlp_module.__file__).read_text(encoding="utf-8"))


def test_the_only_module_permitted_to_import_opentelemetry_does_not() -> None:
    """15:222: the permission is *"reserved and unused at release 1"*, and this is what keeps that
    sentence true rather than aspirational. The SDK plus a gRPC channel does not fit inside the
    distribution's declared dependencies or its 40 MB ceiling."""
    tree = _module_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "opentelemetry" not in roots
    assert "grpc" not in roots
    assert roots.isdisjoint({"asyncio", "urllib", "http", "socket"}), "the POST is a second cell"


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(otlp_module.__all__)
