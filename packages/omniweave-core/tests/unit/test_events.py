"""The vocabulary, the span model and the record -- read back out of the documents that own them.

Sixty-five rows is sixty-five transcriptions, so almost nothing here is an assertion about my
memory. The charter's forty-eight are parsed out of `_notes/charter.md`'s own `toml` fence with
`tomllib` and compared kind for kind and field for field, in order; 15-observability.md's eleven are
parsed out of its fence the same way, with the `level` that document declares for each; and
15:134-140's per-level attribute table and 15:1273's level table are read out of the Markdown and
compared to `SPAN_ATTRIBUTES` and `SEVERITY_NUMBER`.

## The two things that are NOT transcriptions, and how each is checked instead

**Twenty-eight of the charter's forty-eight get no level from 15:1273.** That table names twenty
kinds across its five rows as examples, and 15:341 requires a level on all forty-eight. So twenty
are transcribed and twenty-eight are derived from the table's `meaning` column.
`test_every_level_the_plan_names_is_the_level_declared` checks the twenty against the document, and
`test_the_derived_levels_are_counted_so_a_table_edit_is_noticed` pins the count of the other
twenty-eight -- a number that changes the day 15:1273 gains an example, which is exactly when
somebody should re-read this file.

**Six rows are this cell's append.** `test_every_span_level_has_a_boundary_kind` is the finding
stated as a test: it fails against the charter's vocabulary plus 15's eleven, because three of the
five span levels have no kind that can carry a `phase="start"`. The tests around it show why the
existing kinds cannot serve -- `driver.result` fires once per unit and a span whose end fires
thirty-two times is not a span, and there are three `plan.*` result kinds against nine Stages.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import ConfigError
from omniweave_core.events import (
    EVENT_ORDER,
    EVENTS,
    EVENTS_DROPPED_DEGRADATION,
    LEVEL_ORDER,
    NON_OK_SAMPLE_RATE,
    OK_SAMPLE_RATE,
    SEVERITY_NUMBER,
    SPAN_ATTRIBUTES,
    SPAN_ID_HEX_LEN,
    SPAN_PARENT,
    STAGE_ATTRIBUTE,
    STAGE_MS_KEYS,
    TRACE_FLAGS_SAMPLED,
    TRACE_ID_HEX_LEN,
    TRACEPARENT_RE,
    Event,
    EventKind,
    EventSpec,
    Level,
    Phase,
    SpanLevel,
    Stage,
    TraceSink,
    is_span_kind,
    kinds_at,
    sample_key,
    should_sample,
    span_path,
    traceparent,
    writer_id,
)
from omniweave_core.limits import MAX_EVENT_QUEUE, MAX_SPAN_BUFFER_EVENTS

if TYPE_CHECKING:
    from conftest import PlanDocs

CHARTER = "_notes/charter.md"
OBSERVABILITY = "15-observability.md"

CHARTER_ROWS = 48
APPENDED_BY_15 = 11
APPENDED_HERE = 6

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


_IDENT = re.compile(r"`([a-z_][a-z0-9_.]*)`")


def _backticked(cell: str) -> tuple[str, ...]:
    r"""Every backticked lowercase identifier in one table cell, in order.

    A regex and not `str.split(",")` because 15:136's `run` row carries
    `` `trigger` (`cli\|hook\|upstream\|watch\|mcp\|sdk`) `` -- a backticked token holding the
    table's own column separator, which splits a Markdown row into the wrong number of cells and a
    comma split into the wrong number of names. The character class excludes `\|`, so the enum
    token matches nothing and the attribute names either side of it still do.
    """
    return tuple(_IDENT.findall(cell))


def _fence_with(plan: PlanDocs, document: str, needle: str) -> str:
    """The one ```toml fence in `document` that contains `needle`."""
    bodies = [body for body in plan.fences(document, "toml") if needle in body]
    assert len(bodies) == 1, f"{needle!r} is in {len(bodies)} toml fences of {document}"
    return bodies[0]


def _charter_events(plan: PlanDocs) -> list[dict[str, object]]:
    body = _fence_with(plan, CHARTER, "tools/events.toml — CLOSED, APPEND-ONLY")
    return list(tomllib.loads(body)["event"])


def _appended_events(plan: PlanDocs) -> list[dict[str, object]]:
    body = _fence_with(plan, OBSERVABILITY, "APPENDED BY THIS DOCUMENT")
    return list(tomllib.loads(body)["event"])


# ---------------------------------------------------------------------------------------------
# 1. The vocabulary, against the two documents that declare it
# ---------------------------------------------------------------------------------------------


def test_the_charters_forty_eight_are_transcribed_kind_for_kind_and_field_for_field(
    plan: PlanDocs,
) -> None:
    """`_notes/charter.md:4462-4620`, parsed with `tomllib` and compared in order.

    Field ORDER is compared and not just membership: `tools/events.toml` is generated from these
    declarations and `schema/event-v1.json` from the same, so a reordered `fields` list is a diff in
    two committed artefacts for no reason a reader can see.
    """
    declared = _charter_events(plan)
    assert len(declared) == CHARTER_ROWS
    for index, row in enumerate(declared):
        kind = str(row["kind"])
        assert EVENT_ORDER[index] == kind, f"row {index}: {EVENT_ORDER[index]} vs {kind}"
        assert EVENTS[kind].fields == tuple(row["fields"])  # type: ignore[arg-type]


def test_the_charter_declares_no_level_and_fifteen_says_that_is_the_one_non_append(
    plan: PlanDocs,
) -> None:
    """15:340-343, which is why `EventSpec.level` has no default.

    *"One change is not an append and is declared as such. `level` becomes a required key on every
    row, including the charter's forty-eight, so `tools/events.toml` and `schema/event-v1.json` are
    both regenerated once in the same change that lands this document."*
    """
    assert all("level" not in row for row in _charter_events(plan))
    hits = plan.grep(r"`level` becomes a required key", documents=(OBSERVABILITY,))
    assert hits, "15:341's sentence moved"
    with pytest.raises(TypeError):
        EventSpec(kind=EventKind.DEGRADE)  # type: ignore[call-arg]


def test_fifteens_eleven_are_transcribed_with_the_level_that_document_declares(
    plan: PlanDocs,
) -> None:
    """15-observability.md:293-339, the read path, the compile path and four others."""
    declared = _appended_events(plan)
    assert len(declared) == APPENDED_BY_15
    for index, row in enumerate(declared):
        kind = str(row["kind"])
        assert EVENT_ORDER[CHARTER_ROWS + index] == kind
        assert EVENTS[kind].fields == tuple(row["fields"])  # type: ignore[arg-type]
        assert EVENTS[kind].level.value == row["level"], kind


def test_the_vocabulary_is_sixty_five_rows_and_the_last_six_are_this_cells_append() -> None:
    assert len(EVENTS) == CHARTER_ROWS + APPENDED_BY_15 + APPENDED_HERE == 65
    assert EVENT_ORDER[-APPENDED_HERE:] == (
        "plan.begin",
        "plan.end",
        "attempt.begin",
        "attempt.end",
        "call.begin",
        "call.end",
    )


def test_a_kind_is_never_reused_and_the_enum_is_the_order() -> None:
    """15:283-286 -- *"A row is never removed and a `kind` is never reused."*

    `EventKind`'s declaration order and `_DECLARATIONS`'s are asserted equal at import; this is the
    same fact from outside, so the assertion is not checking only itself.
    """
    assert len(set(EVENT_ORDER)) == len(EVENT_ORDER)
    assert tuple(member.value for member in EventKind) == EVENT_ORDER
    assert tuple(EVENTS) == EVENT_ORDER


# ---------------------------------------------------------------------------------------------
# 2. The level: twenty transcribed, twenty-eight derived, and the count of each pinned
# ---------------------------------------------------------------------------------------------


def _level_table(plan: PlanDocs) -> dict[str, tuple[str, ...]]:
    """15:1273's five rows, as `{level: (the kinds it names as examples, ...)}`."""
    rows = plan.grep(r"^\| `(debug|info|notice|warn|error)` \|", documents=(OBSERVABILITY,))
    assert len(rows) == len(LEVEL_ORDER), [str(hit) for hit in rows]
    table: dict[str, tuple[str, ...]] = {}
    for hit in rows:
        cells = hit.text.split("|")
        level = cells[1].strip().strip("`")
        table[level] = tuple(_backticked(cells[4]))
    return table


def test_every_level_the_plan_names_is_the_level_declared(plan: PlanDocs) -> None:
    """15:1273's `examples` column, read out of the table and checked kind by kind."""
    table = _level_table(plan)
    named = {kind: level for level, kinds in table.items() for kind in kinds}
    assert named, "15:1273's table moved"
    for kind, level in named.items():
        assert kind in EVENTS, f"{kind} is named at 15:1273 and is in no row"
        assert EVENTS[kind].level.value == level, kind


def test_the_derived_levels_are_counted_so_a_table_edit_is_noticed(plan: PlanDocs) -> None:
    """Twenty of the charter's forty-eight are named at 15:1273; twenty-eight are derived.

    Pinned as a number rather than left implicit: the day 15:1273 gains an example this count moves,
    and that is the day somebody should re-read the derivations rather than discover them later.
    """
    named = {kind for kinds in _level_table(plan).values() for kind in kinds}
    charter = {str(row["kind"]) for row in _charter_events(plan)}
    assert len(charter & named) == 20
    assert len(charter - named) == 28


def test_the_severity_numbers_are_the_plans(plan: PlanDocs) -> None:
    """15:1273's second column. `ow trace export` reads these; nothing on the hot path does."""
    rows = plan.grep(r"^\| `(debug|info|notice|warn|error)` \| \d+ \|", documents=(OBSERVABILITY,))
    assert len(rows) == len(LEVEL_ORDER)
    for hit in rows:
        cells = hit.text.split("|")
        assert SEVERITY_NUMBER[cells[1].strip().strip("`")] == int(cells[2].strip())
    assert LEVEL_ORDER == ("debug", "info", "notice", "warn", "error")
    assert sorted(SEVERITY_NUMBER.values()) == list(SEVERITY_NUMBER.values())


def test_the_floor_is_an_index_comparison_over_an_ascending_tuple() -> None:
    """15:1281: applied *"at `emit()`, before serialisation"*, so it has to be cheap."""
    assert [LEVEL_ORDER.index(level.value) for level in Level] == [0, 1, 2, 3, 4]
    floor = LEVEL_ORDER.index("notice")
    kept = [kind for kind, spec in EVENTS.items() if LEVEL_ORDER.index(spec.level.value) >= floor]
    assert "driver.crash" in kept
    assert "store.txn" not in kept


# ---------------------------------------------------------------------------------------------
# 3. The span hierarchy, and the six kinds it had no way to emit
# ---------------------------------------------------------------------------------------------


def test_the_hierarchy_is_five_deep_and_closed(plan: PlanDocs) -> None:
    """15:73-79, and 15:81-85's *"no sixth level and no level between `plan` and `unit`"*."""
    assert tuple(SpanLevel) == (
        SpanLevel.RUN,
        SpanLevel.PLAN,
        SpanLevel.UNIT,
        SpanLevel.ATTEMPT,
        SpanLevel.CALL,
    )
    assert len(SPAN_PARENT) == 5
    assert SPAN_PARENT["run"] is None
    assert [level for level, parent in SPAN_PARENT.items() if parent is None] == ["run"]
    assert plan.grep(r"no sixth level and no level between", documents=(OBSERVABILITY,))


def test_span_path_from_call_reaches_run_through_every_level() -> None:
    """What an orphan check walks (15:198's *"zero orphans and zero cycles"*)."""
    assert span_path("call") == ("run", "plan", "unit", "attempt", "call")
    assert span_path("run") == ("run",)
    assert span_path("batch") == ()
    for level in SPAN_PARENT:
        assert span_path(level)[0] == "run"
        assert span_path(level)[-1] == level


def test_every_span_level_has_a_begin_and_an_end_kind() -> None:
    """The gap the six appended rows close. 15:32 and 15:2.6's pairing rule.

    Without them `plan`, `attempt` and `call` have no kind that can carry `phase="start"`, and a
    closed vocabulary with no kind for a boundary means that boundary cannot be emitted at all.
    """
    for level in SPAN_PARENT:
        assert kinds_at(level, Phase.START), f"{level} has no kind that opens a span"
        assert kinds_at(level, Phase.END), f"{level} has no kind that closes a span"
    assert kinds_at("call") == ("call.begin", "call.end")
    assert kinds_at("run") == ("run.start", "run.end")
    assert kinds_at("unit") == ("unit.begin", "unit.complete")


def test_the_charters_vocabulary_alone_cannot_emit_three_of_the_five_levels(
    plan: PlanDocs,
) -> None:
    """The finding, stated against the documents rather than against my summary of them."""
    published = {str(row["kind"]) for row in _charter_events(plan)}
    published |= {str(row["kind"]) for row in _appended_events(plan)}
    assert len(published) == CHARTER_ROWS + APPENDED_BY_15
    for level in ("plan", "attempt", "call"):
        assert not (set(kinds_at(level)) & published), f"{level} already had a boundary kind"
    for level in ("run", "unit"):
        assert set(kinds_at(level)) <= published


def test_driver_result_cannot_be_a_call_spans_end_because_it_fires_once_per_unit(
    plan: PlanDocs,
) -> None:
    """04-driver-system.md:1700 -- `RESULT` is *"one frame per unit"*, in bold in the table."""
    hits = plan.grep(r"one frame per unit", documents=("04-driver-system.md",))
    assert hits, "04:1700's phrase moved"
    assert EVENTS["driver.result"].span is None
    assert "unit_index" in EVENTS["driver.result"].fields


def test_three_plan_result_kinds_cannot_cover_nine_stages() -> None:
    """`plan.discover`, `plan.identify` and `plan.expand` carry results, not Stage boundaries."""
    result_kinds = [k for k in EVENT_ORDER if k.startswith("plan.") and EVENTS[k].span is None]
    assert set(result_kinds) == {
        "plan.discover",
        "plan.identify",
        "plan.expand",
        "plan.pause",
        "plan.resume",
    }
    assert len(Stage) == 9
    assert EVENTS["plan.begin"].fields == ("stage",)
    assert EVENTS["plan.end"].fields == ("stage", "elapsed_ms")


def test_the_two_call_kinds_partition_the_plans_eighteen_call_attributes(plan: PlanDocs) -> None:
    """15:140's `call` row, split into what is known at the seam crossing and what is not.

    A partition and not a copy: `invoke_id` is on both, because it is what pairs the two records,
    and every other attribute appears exactly once.
    """
    rows = plan.grep(r"^\| `call` \|", documents=(OBSERVABILITY,))
    assert len(rows) == 1
    declared = tuple(
        name.strip().strip("`") for name in rows[0].text.split("|")[2].split(",") if name.strip()
    )
    assert declared == SPAN_ATTRIBUTES["call"]
    begin, end = EVENTS["call.begin"].fields, EVENTS["call.end"].fields
    assert set(begin) | set(end) == set(declared)
    assert set(begin) & set(end) == {"invoke_id"}
    assert len(declared) == 18


def test_span_attributes_are_the_plans_per_level_table(plan: PlanDocs) -> None:
    """15:134-140, every level, in the document's own order."""
    for level in SPAN_PARENT:
        rows = plan.grep(rf"^\| `{level}` \| `", documents=(OBSERVABILITY,))
        assert len(rows) == 1, level
        assert _backticked(rows[0].text.removeprefix(f"| `{level}` |")) == SPAN_ATTRIBUTES[level]


def test_the_stage_vocabulary_is_nine_and_stage_ms_holds_seven(plan: PlanDocs) -> None:
    """15:97-107's table: nine Stages, and two rows whose last column says `no`."""
    stages = "|".join(member.value for member in Stage)
    rows = plan.grep(rf"^\| `({stages})` \| ", documents=(OBSERVABILITY,))
    named = [hit.text.split("|")[1].strip().strip("`") for hit in rows]
    assert set(named) == {member.value for member in Stage}
    assert len(Stage) == 9
    assert set(STAGE_MS_KEYS) == {member.value for member in Stage} - {"query", "compile"}
    assert len(STAGE_MS_KEYS) == 7
    assert STAGE_ATTRIBUTE == "ow.stage"
    assert STAGE_ATTRIBUTE in SPAN_ATTRIBUTES["plan"]


def test_a_spec_that_names_a_span_without_a_phase_is_refused() -> None:
    with pytest.raises(ConfigError, match="a span boundary names its level"):
        EventSpec(kind=EventKind.DEGRADE, level=Level.WARN, span="unit")
    with pytest.raises(ConfigError, match="a span boundary names its level"):
        EventSpec(kind=EventKind.DEGRADE, level=Level.WARN, phase=Phase.START)
    with pytest.raises(ConfigError, match="is not one of"):
        EventSpec(kind=EventKind.DEGRADE, level=Level.WARN, span="batch", phase=Phase.START)


def test_is_span_kind_separates_boundaries_from_points() -> None:
    assert is_span_kind("call.begin")
    assert not is_span_kind("cache.hit")
    assert not is_span_kind("not.a.kind")
    assert sum(1 for kind in EVENT_ORDER if is_span_kind(kind)) == 10


# ---------------------------------------------------------------------------------------------
# 4. The record
# ---------------------------------------------------------------------------------------------


def record(kind: EventKind = EventKind.CACHE_HIT, **over: object) -> Event:
    spec = EVENTS[kind.value]
    values: dict[str, object] = {
        "ts_wall_ns": 1,
        "ts_mono_ns": 2,
        "run_id": "r_01",
        "writer_id": "abc123abc123",
        "seq": 1,
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "parent_span_id": None,
        "kind": kind,
        "phase": spec.phase.value,
        "level": spec.level.value,
        "fields": {},
    }
    values.update(over)
    return Event(**values)  # type: ignore[arg-type]


def test_a_record_carrying_an_undeclared_field_is_refused() -> None:
    """14-security.md:891's allowlist: an undeclared key is the exact shape a leak takes."""
    record(EventKind.CACHE_HIT, fields={"layer": "call"}).validate()
    with pytest.raises(ConfigError, match="permits"):
        record(EventKind.CACHE_HIT, fields={"quote": "the document said this"}).validate()


def test_a_record_at_the_wrong_level_is_refused() -> None:
    """15:1270 -- *"the level is the kind's, never the call site's."*"""
    with pytest.raises(ConfigError, match="never the call site's"):
        record(EventKind.DRIVER_CRASH, level="info").validate()


def test_a_span_boundary_carrying_the_wrong_phase_is_refused() -> None:
    with pytest.raises(ConfigError, match="phase is a property of its kind"):
        record(EventKind.CALL_BEGIN, phase="end").validate()
    record(EventKind.CALL_BEGIN, phase="start").validate()


def test_a_point_event_may_carry_any_phase_because_its_kind_declares_none() -> None:
    """A point kind's `phase` is the emitter's: `unit.progress` is a point and so is `degrade`."""
    record(EventKind.UNIT_PROGRESS, phase="point", fields={"done": 3, "total": 9}).validate()
    assert EVENTS["unit.progress"].span is None


def test_an_unknown_kind_names_the_closed_vocabulary() -> None:
    with pytest.raises(ConfigError, match="the vocabulary is closed"):
        Event(
            ts_wall_ns=1,
            ts_mono_ns=2,
            run_id="r_01",
            writer_id="abc123abc123",
            seq=1,
            trace_id=TRACE_ID,
            span_id=SPAN_ID,
            parent_span_id=None,
            kind="cache.warm",  # type: ignore[arg-type]
            phase="point",
            level="info",
        ).spec()


def test_the_constructor_validates_nothing_because_telemetry_never_fails_a_run() -> None:
    """15:47 -- *"telemetry never fails a run, exactly as telemetry never fails a query."*

    A bad record is CONSTRUCTIBLE and is refused by the sink, which counts it and carries on. A
    constructor that raised would make a mis-typed field name in a rarely-hit branch a crash in the
    run rather than one dropped record.
    """
    bad = record(EventKind.CACHE_HIT, level="error", fields={"nope": 1})
    assert bad.level == "error"
    with pytest.raises(ConfigError):
        bad.validate()


def test_unit_begin_carries_no_fields_and_that_is_a_row_not_an_omission(plan: PlanDocs) -> None:
    charter = {str(row["kind"]): tuple(row["fields"]) for row in _charter_events(plan)}  # type: ignore[arg-type]
    assert charter["unit.begin"] == ()
    assert EVENTS["unit.begin"].fields == ()
    record(EventKind.UNIT_BEGIN).validate()


def test_the_drop_degradation_is_the_kind_the_plan_names(plan: PlanDocs) -> None:
    """15:40 requires the record *"in those words"*."""
    assert EVENTS_DROPPED_DEGRADATION == "events_dropped"
    assert plan.grep(r'Degradation\(kind="events_dropped"\)', documents=(OBSERVABILITY,))
    assert "events_dropped" in EVENTS["run.end"].fields


# ---------------------------------------------------------------------------------------------
# 5. Trace context
# ---------------------------------------------------------------------------------------------


def test_traceparent_is_the_plans_string_and_the_flag_is_always_01() -> None:
    """15:186-189. A `00` *"would instruct a downstream server to discard what we have decided to
    keep."*"""
    assert traceparent(TRACE_ID, SPAN_ID) == f"00-{TRACE_ID}-{SPAN_ID}-01"
    assert TRACE_FLAGS_SAMPLED == "01"
    assert re.match(TRACEPARENT_RE, traceparent(TRACE_ID, SPAN_ID))


def test_an_all_zero_id_is_refused_because_a_conformant_peer_drops_it() -> None:
    with pytest.raises(ConfigError, match="all-zero"):
        traceparent("0" * TRACE_ID_HEX_LEN, SPAN_ID)
    with pytest.raises(ConfigError, match="all-zero"):
        traceparent(TRACE_ID, "0" * SPAN_ID_HEX_LEN)


def test_a_malformed_id_is_refused_at_the_producer() -> None:
    with pytest.raises(ConfigError, match="trace_id must be 32"):
        traceparent(TRACE_ID[:-1], SPAN_ID)
    with pytest.raises(ConfigError, match="trace_id must be 32"):
        traceparent(TRACE_ID.upper(), SPAN_ID)
    with pytest.raises(ConfigError, match="span_id must be 16"):
        traceparent(TRACE_ID, SPAN_ID + "aa")


def test_the_pattern_rejects_an_unsampled_flag() -> None:
    assert not re.match(TRACEPARENT_RE, f"00-{TRACE_ID}-{SPAN_ID}-00")
    assert not re.match(TRACEPARENT_RE, f"01-{TRACE_ID}-{SPAN_ID}-01")


def test_the_writer_id_is_the_triple_claimed_by_uses() -> None:
    """15:372-374, recomputed rather than compared to a frozen literal."""
    expected = hashlib.sha256(b"host-a4242created-at-9").hexdigest()[:12]
    assert writer_id("host-a", 42, "42created-at-9") == expected
    assert len(writer_id("host-a", 42, "t")) == 12


def test_a_recycled_pid_is_a_different_writer() -> None:
    """`0004_runtime.sql:110`'s third component: it *"stops a recycled pid from looking like a live
    holder"*, and here it stops two writers sharing one `seq` sequence."""
    first = writer_id("host-a", 42, "2026-09-12T10:00:00Z")
    second = writer_id("host-a", 42, "2026-09-12T11:00:00Z")
    assert first != second


def test_a_writer_id_without_the_third_component_is_refused() -> None:
    with pytest.raises(ConfigError, match="recycled pid"):
        writer_id("host-a", 42, "")
    with pytest.raises(ConfigError, match="recycled pid"):
        writer_id("", 42, "t")


# ---------------------------------------------------------------------------------------------
# 6. Tail sampling
# ---------------------------------------------------------------------------------------------


def test_a_non_ok_outcome_is_always_kept() -> None:
    """`non_ok = 1.0`. Wider than "failures": a wrong cache hit is diagnosed from the trace."""
    assert NON_OK_SAMPLE_RATE == 1.0
    for outcome in (
        "ok_partial",
        "skipped_cached",
        "failed_transient",
        "failed_permanent",
        "deferred_budget",
        "cancelled",
    ):
        assert should_sample(outcome, "w1", "salt", ok_rate=0.0)


def test_the_ok_rate_is_one_in_sixty_four_over_a_population() -> None:
    """The rate the plan ships, measured rather than asserted. 15:150."""
    assert OK_SAMPLE_RATE == 1 / 64
    kept = sum(1 for n in range(20_000) if should_sample("ok", f"w{n}", "salt"))
    assert 250 <= kept <= 375, kept  # 20000/64 = 312.5


def test_two_processes_and_two_replays_select_the_same_set() -> None:
    """15:151 -- *"never RNG, so two processes select the same set and a replay selects the same
    set."*"""
    first = [n for n in range(2_000) if should_sample("ok", f"w{n}", "salt")]
    second = [n for n in range(2_000) if should_sample("ok", f"w{n}", "salt")]
    assert first == second
    assert first != [n for n in range(2_000) if should_sample("ok", f"w{n}", "pepper")]


def test_the_key_is_blake2b_over_the_work_id_and_the_salt() -> None:
    """15:160's expression, recomputed independently."""
    expected = int.from_bytes(hashlib.blake2b(b"w7salt").digest()[:8], "big")
    assert sample_key("w7", "salt") == expected


def test_a_rate_outside_zero_to_one_is_refused_naming_the_knob() -> None:
    with pytest.raises(ConfigError, match=r"\[observe\] sample.ok"):
        should_sample("ok", "w1", "salt", ok_rate=1.5)
    assert should_sample("ok", "w1", "salt", ok_rate=1.0)
    assert not should_sample("ok", "w1", "salt", ok_rate=0.0)


# ---------------------------------------------------------------------------------------------
# 7. The sink boundary, and the two bounds that size its buffers
# ---------------------------------------------------------------------------------------------


def test_the_sink_protocol_has_exactly_two_methods(plan: PlanDocs) -> None:
    """15:54 -- *"`TraceSink` is a Protocol with two methods and two shipped implementations; a
    third is a charter amendment."*"""
    declared = {name for name in vars(TraceSink) if not name.startswith("_")}
    assert declared == {"emit", "flush"}
    assert plan.grep(r"a Protocol with two methods", documents=(OBSERVABILITY,))


def test_the_buffer_bound_is_the_plans_own_arithmetic() -> None:
    """15:168-175: `38 x 64 x 180 = 437,760 B = 427.5 KiB` at the charter's `max_inflight`."""
    assert MAX_SPAN_BUFFER_EVENTS == 64
    inflight = 32 + 4 + 2
    assert inflight * MAX_SPAN_BUFFER_EVENTS * 180 == 437_760
    assert 437_760 / 1024 == 427.5


def test_the_event_queue_is_the_bounded_sixty_four_k_the_plan_names(plan: PlanDocs) -> None:
    assert MAX_EVENT_QUEUE == 65_536
    assert plan.grep(r"bounded 64k.*drop-oldest", documents=(OBSERVABILITY,))
