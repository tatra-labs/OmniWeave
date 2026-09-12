"""The closed event vocabulary, the five-deep span model, and the record they share.

`Event` is the only thing a human or a machine reads (15-observability.md:1268: *"omniweave has no
logger hierarchy, no `logging.getLogger(__name__)` tree and no per-module level configuration.
Everything a human or a machine reads is an `Event`."*). This is `02-architecture.md:245`'s
component row 21 whole: `Event`, `TraceSink`, `NdjsonSink`, `ConsoleSink`, `traceparent` and the
closed `EVENTS` vocabulary, in the one module that row names.

The file falls into two halves and the boundary is worth knowing before reading it. Sections 1-6
**decide nothing at run time** -- a vocabulary, a span hierarchy, a record, a `Protocol` and four
pure functions, none of which opens a file or takes a lock. Sections 7-11 are the sinks: a
serialiser, a bounded drop-oldest queue, one writer thread, a 64 MiB shard roll, and the recorder
that stamps `seq`. Everything in the second half is testable without the first half's documents and
everything in the first half is testable without a thread.

## `tools/events.toml` is generated from `EVENTS`, and the plan offers both directions

`_notes/charter.md:4456` heads the file *"CLOSED, APPEND-ONLY, byte-diff gated (G20)"* and says
*"`schema/event-v1.json` is GENERATED from it"*; `02-architecture.md:245` says the vocabulary is
*"loaded from `tools/events.toml`"*. Read as runtime loading that is unbuildable:
`11-repo-layout.md:792` enumerates the **five** kinds of file that ship inside a wheel and
`tools/` is not among them, so an installed `omniweave_core` has no `tools/events.toml` to load and
a vocabulary that fails to load refuses every event in the run.

`02-architecture.md:274` settles it without a deviation. Row 50 covers
`tools/{layers,weights,licences,vendor,indexes,config_axes,events,scorekinds,embeddings,wirekeys}
.toml` as **T-GENERATED** and its does-NOT column offers two shapes: *"each is either append-only
against the previous tag **or** generated from a declaration site."* `config_axes.toml` is already
built the second way -- `omniweave_core.config.KEYS` declares, `tools/gen_config_axes.py` renders,
G18 byte-diffs -- and this file follows it, for the same reason `ConfigKey.axis` has no default:

* **an invalid row is unconstructible rather than a CI finding.** `15:341` makes `level` a required
  key on every row, *"including the charter's forty-eight"*, and calls that the one change to the
  file that is not an append. `EventSpec.level` is a required field, so a row without one is a
  `TypeError` at import -- which is strictly stronger than a byte diff that runs in CI.
* **core reads no file to know its own vocabulary.** `emit()` is on the hot path at ~8 records per
  unit inside the charter's `<= 0.5 ms/unit` overhead budget, and a lazily-read TOML would put a
  first-call file read inside it.

The append-only PROPERTY is unchanged and is what `tools/gate_events.py` checks: `EVENT_ORDER` is
append order, a row is never removed, and a `kind` is never reused. Reported, because the two
sentences in `02` read differently and a later reader should not have to re-derive this.

## The vocabulary is sixty-five rows, and six of them are this cell's append

Forty-eight are the charter's (`_notes/charter.md:4462-4620`), transcribed kind for kind and field
for field, in charter order. Eleven are `15-observability.md:293-339`'s own append -- the read path,
the compile path, the driver log, `doctor.check` and `shard.roll` -- carrying the `level` that
document declares for each.

**Six are appended here, and the reason is arithmetic rather than taste.** `15:32` says the stream
carries *"one record per span boundary or point"*; `15:73`'s hierarchy is five deep;
`15:2.6` reconstructs a span by pairing `phase="start"` with `phase="end"` on
`(trace_id, span_id)`; and `Event.kind` is closed. So every span level needs a kind that can carry
a boundary. Three levels have one and two do not:

| level | opens with | closes with |
|---|---|---|
| `run` | `run.start` | `run.end` |
| `plan` | — | — |
| `unit` | `unit.begin` | `unit.complete` / `unit.failed` |
| `attempt` | — | — |
| `call` | — | — |

`driver.invoke` and `driver.result` do not pair as a `call` span: `04-driver-system.md:1700` makes
`RESULT` *"one frame per unit"*, so a batch of 32 emits one `driver.invoke` and thirty-two
`driver.result`, and a span whose end fires 32 times is not a span. Nor are `plan.discover`,
`plan.identify` and `plan.expand` `plan` spans -- their fields (`discovered`, `skipped`,
`part_count`, `rows`) are results, there are three of them against `15:2.2`'s **nine** Stages, and
`15:159` needs a `plan` span for every Stage entered whether or not any of the three fired.

The charter's own projection is the receipt: `15:165` budgets `~8 events` per unit as *"a `unit`
pair, an `attempt` pair, a `call` pair, plus `work.claim` and `work.complete`"* -- three pairs, of
which only the first has kinds. So `plan.begin`/`plan.end`, `attempt.begin`/`attempt.end` and
`call.begin`/`call.end` are appended, with fields taken from `15:2.3`'s closed per-level attribute
sets and nothing invented: `call.begin` carries the ten of the eighteen that are known when the
seam is crossed and `call.end` the eight that are not, and a test asserts the union is exactly
`15:140`'s row. Appending is *"the sanctioned change to an append-only file"* (`15:289`), which is
how `15` added its own eleven. Reported.

## What is deliberately NOT here

* **The manifest's `observe.*` block.** `SinkStats.as_manifest_fields()` produces the four numbers
  `15:434` names; assembling them into `{output_root}/runs/{run_id}.json` is
  `omniweave/run/manifest.py`'s, in the CLI distribution, because that is the process holding the
  `store.write` lock.
* **`ow trace tree | stat | export | prune`.** `parse_line()` is the read primitive all four need
  and `15:2.6` makes the exporter *"a reconstructor, not an emitter"* that runs after the fact. The
  verbs are `omniweave.surface`'s.
* **`Degradation`.** `15:964` is that type's sole home and `omniweave_core/observe/degradation.py`
  does not exist. `EVENTS_DROPPED_DEGRADATION` transcribes the one literal, on `subproc.py`'s
  `IsolationShortfall.DEGRADATION_KIND` precedent.
* **The manifest.** `15:33` homes it in `omniweave/run/manifest.py`, in the CLI distribution,
  because it is written by the process that holds the `store.write` lock. `STAGE_MS_KEYS` is here
  because `15:2.2` makes the Stage vocabulary *"exactly the key set of the run manifest's
  `stage_ms` map"*, and one vocabulary with two homes is INV-21's own failure.
* **OTLP.** `15:2.6` makes `ow trace export` a reconstructor that reads shards after the fact.
  `SEVERITY_NUMBER` is here because `15:1273` binds the number to the level and a mapping printed in
  two places is a mapping that can disagree; nothing else OTLP is.

Specified in 15-observability.md sections 1, 2 and 3 and section 8.1, 02-architecture.md section 2
row 21, _notes/charter.md:4456-4620, and 16-roadmap.md:548 (P4 W4.8).
"""

from __future__ import annotations

import contextlib
import dataclasses
import gzip
import hashlib
import json
import os
import queue
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import IO, Final, Literal, Protocol, runtime_checkable

from omniweave_core.clock import Clock
from omniweave_core.errors import ConfigError
from omniweave_core.limits import MAX_EVENT_QUEUE, MAX_SPAN_BUFFER_EVENTS

# `Mapping` is imported at run time and not under `TYPE_CHECKING`: `tools/schemagen.py` resolves
# this module's annotations with `typing.get_type_hints()` to emit `schema/event-v1.json`, and a
# name that exists only for a type checker is a `NameError` there. G6 is the check that would
# otherwise fail, on the day the schema goes live rather than on the day the import moved.

__all__ = [
    "CONSOLE_FLOOR_WHEN_PIPED",
    "DEFAULT_SHARD_BYTES",
    "EVENTS",
    "EVENTS_DROPPED_DEGRADATION",
    "EVENT_ORDER",
    "LEVEL_ORDER",
    "NDJSON_SEPARATORS",
    "NON_OK_SAMPLE_RATE",
    "OK_SAMPLE_RATE",
    "SEVERITY_NUMBER",
    "SHARD_ORDINAL_DIGITS",
    "SPAN_ATTRIBUTES",
    "SPAN_ID_HEX_LEN",
    "SPAN_PARENT",
    "STAGE_ATTRIBUTE",
    "STAGE_MS_KEYS",
    "TRACEPARENT_RE",
    "TRACE_FLAGS_SAMPLED",
    "TRACE_ID_HEX_LEN",
    "ConsoleSink",
    "Event",
    "EventKind",
    "EventSpec",
    "Level",
    "NdjsonSink",
    "Phase",
    "RunRecorder",
    "SinkStats",
    "SpanLevel",
    "Stage",
    "TraceSink",
    "is_span_kind",
    "kinds_at",
    "parse_line",
    "sample_key",
    "serialise",
    "shard_path",
    "should_sample",
    "span_path",
    "traceparent",
    "writer_id",
]


# =============================================================================================
# 1. The level, and the one mapping OTLP needs
# =============================================================================================


class Level(StrEnum):
    """The five, from 15-observability.md:1273's table. Declared per `kind`, never per call site.

    15:1270: *"The level is **declared in `tools/events.toml` per `kind`**, not chosen at the call
    site -- so 'which events are warnings' is a static list a reviewer can read, and a refactor
    cannot silently demote an error."* That is the whole reason `EventSpec` carries it and `Event`
    does not take it as an argument.
    """

    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARN = "warn"
    ERROR = "error"


LEVEL_ORDER: Final[tuple[str, ...]] = tuple(member.value for member in Level)
"""Ascending, so `[observe] level`'s floor is one index comparison at `emit()`.

15:1281: the floor *"is applied **at `emit()`**, before serialisation, so a `debug` floor costs one
comparison rather than a discarded JSON document."* A tuple rather than a dict because the answer
wanted is an ordering and `index()` on five strings is the cheapest thing that gives one."""

SEVERITY_NUMBER: Final[Mapping[str, int]] = MappingProxyType(
    {
        Level.DEBUG.value: 5,
        Level.INFO.value: 9,
        Level.NOTICE.value: 11,
        Level.WARN.value: 13,
        Level.ERROR.value: 17,
    }
)
"""15:1273's second column, the OTel `severityNumber` per level.

Here rather than in an exporter because 15:250 maps *"a point `Event`"* to a `LogRecord` with
*"`severityNumber` from §8.1"*, and a table printed in one document and implemented in another is a
table that can disagree. `ow trace export` reads this; nothing on the hot path does."""


class Phase(StrEnum):
    """`start | end | point`. 15:358, and 15:90 is why the name is taken.

    *"`Event.phase` is already taken (`start | end | point`) and `derive_pass.phase` is already
    taken"* -- which is the sentence that made the pipeline phase a third name, `Stage`.
    """

    START = "start"
    END = "end"
    POINT = "point"


# =============================================================================================
# 2. The span hierarchy -- closed, five deep, and a charter amendment to widen
# =============================================================================================


class SpanLevel(StrEnum):
    """15:73-79's five, outermost first. *"There is no sixth level and no level between `plan` and
    `unit`: the unit IS `(unit_uri, unit_part)`. Adding a level is a charter amendment, not a
    refactor."*"""

    RUN = "run"
    PLAN = "plan"
    UNIT = "unit"
    ATTEMPT = "attempt"
    CALL = "call"


SPAN_PARENT: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        SpanLevel.RUN.value: None,
        SpanLevel.PLAN.value: SpanLevel.RUN.value,
        SpanLevel.UNIT.value: SpanLevel.PLAN.value,
        SpanLevel.ATTEMPT.value: SpanLevel.UNIT.value,
        SpanLevel.CALL.value: SpanLevel.ATTEMPT.value,
    }
)
"""The tree, as a parent link per level. One root, one chain, no branching between levels.

A mapping rather than an implicit reading of `SpanLevel`'s declaration order: a reader checking
I33's *"zero orphans and zero cycles"* (15:198) needs the parent relation to be a fact somewhere,
and deriving it from an enum's order makes reordering the enum a silent re-parenting."""


def span_path(level: str) -> tuple[str, ...]:
    """The chain from `run` down to `level`, inclusive. `()` for a level outside the five.

    This is what an orphan check walks: an `Event` at `call` whose ancestry does not reach `run`
    through exactly this sequence is the hole 15:199 calls *"worse than no trace, because the hole
    is where the failure was."*
    """
    if level not in SPAN_PARENT:
        return ()
    chain: list[str] = []
    current: str | None = level
    while current is not None:
        chain.append(current)
        current = SPAN_PARENT[current]
    return tuple(reversed(chain))


SPAN_ATTRIBUTES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        SpanLevel.RUN.value: (
            "trigger",
            "argv_digest",
            "config_digest",
            "semantic_digest",
            "policy_digest",
            "pricebook_digest",
            "lock_digest",
            "catalog_digest",
            "generation",
            "omniweave_version",
            "contract",
            "schema",
            "corpus_id",
            "needs_full_scan",
        ),
        SpanLevel.PLAN.value: (
            "ow.stage",
            "scope_id",
            "discovered",
            "skipped",
            "rows",
            "claimable",
            "high_water",
        ),
        SpanLevel.UNIT.value: (
            "operator",
            "op_version",
            "cost_class",
            "cache_key",
            "decision_id",
            "staged_gen",
            "queued_ms",
            "ran_ms",
            "rows_written",
            "outcome",
            "was_cache_hit",
            "peak_rss_bytes",
            "sampled",
        ),
        SpanLevel.ATTEMPT.value: (
            "attempt",
            "claimed_gen",
            "lease_ms",
            "failure_class",
            "retry_after",
            "rung",
            "lane",
        ),
        SpanLevel.CALL.value: (
            "driver",
            "driver_version",
            "driver_schema_v",
            "isolation",
            "invoke_id",
            "batch_index",
            "batch_size",
            "dispatch_key",
            "service",
            "provider",
            "wall_ms",
            "cpu_ms",
            "gpu_ms",
            "tokens_in",
            "tokens_out",
            "calls",
            "bytes_egress",
            "micros",
        ),
    }
)
"""15:134-140's table, transcribed per level and in its order. CLOSED, and that is the point.

15:142-147 states what the closure buys: *"`Event.fields` is `Mapping[str, Scalar]` and the
permitted key set per `kind` is declared in `tools/events.toml`, so document text has no free-form
field to ride in … A `cite`, a `block_id`, an `entity_id`, a query string and a `quote` never appear
in an `Event`, at any level."* These are the **additional** attributes; the envelope is `Event`'s
own fields and is not repeated here.

`ow.stage` keeps its prefix because 15:92 gives the attribute that spelling and 15:2.6 maps the
`ow.`-prefixed names straight through to OTLP. The `Event.fields` key on `plan.begin` is `stage`
without it -- the prefix is the wire spelling, not the record's."""


class Stage(StrEnum):
    """15:97-107's nine. The vocabulary is closed and is also the manifest's `stage_ms` key set.

    15:94-96: *"Its vocabulary is closed and is exactly the key set of the run manifest's `stage_ms`
    map, so a timing in the manifest and a subtree in the trace are the same partition of the run."*
    Two of the nine are excluded from `stage_ms` and `STAGE_MS_KEYS` below is that subset -- the
    exclusion is per-Stage and stated in the table's own last column, not a property of the enum.
    """

    DISCOVER = "discover"
    PLAN = "plan"
    PARSE = "parse"
    DERIVE = "derive"
    INDEX = "index"
    CONVERGE = "converge"
    MAINTAIN = "maintain"
    QUERY = "query"
    COMPILE = "compile"


STAGE_ATTRIBUTE: Final = "ow.stage"
"""15:92 -- the span attribute a `plan` span carries and *"every descendant"* inherits."""

STAGE_MS_KEYS: Final[tuple[str, ...]] = (
    Stage.DISCOVER.value,
    Stage.PLAN.value,
    Stage.PARSE.value,
    Stage.DERIVE.value,
    Stage.INDEX.value,
    Stage.CONVERGE.value,
    Stage.MAINTAIN.value,
)
"""The seven Stages whose elapsed time lands in the manifest. 15:105-107's `in stage_ms` column.

`query` and `compile` are out and each says why in its own row: *"no: a read writes no manifest"*
and *"no: a compile writes a receipt"*. They are still Stages and still open a `plan` span --
15:110-113 is explicit that they are why the hierarchy did not need widening -- so excluding them
here and not from `Stage` is the distinction the table draws."""


# =============================================================================================
# 3. The vocabulary. Sixty-five rows, in APPEND ORDER. Nothing is renumbered.
# =============================================================================================


class EventKind(StrEnum):
    """Every `kind`, in APPEND ORDER. The closed vocabulary, as a type.

    A `StrEnum` and not a set of bare strings for the reason `schema/` exists at all:
    11-repo-layout.md:833 makes the generated JSON Schema *"the language-neutral contract -- the
    only artefact a second-language reader is allowed to read instead of the Python"*, and
    `schemagen` renders an enum-annotated field as a closed `enum` in that schema. A `kind: str`
    would have left `event-v1.json` saying "any string" about a vocabulary 15:283 calls *"a name
    a dashboard, a runbook and a test all hard-code"*.

    Declaration order IS `tools/events.toml`'s row order, and `EVENT_ORDER` below is asserted
    equal to it at import so the two cannot drift into two answers.
    """

    RUN_START = "run.start"
    RUN_END = "run.end"
    RUN_DEGRADED = "run.degraded"
    PLAN_DISCOVER = "plan.discover"
    PLAN_IDENTIFY = "plan.identify"
    PLAN_EXPAND = "plan.expand"
    PLAN_PAUSE = "plan.pause"
    PLAN_RESUME = "plan.resume"
    WORK_ENQUEUE = "work.enqueue"
    WORK_CLAIM = "work.claim"
    WORK_LEASE_EXTEND = "work.lease_extend"
    WORK_LEASE_REAP = "work.lease_reap"
    WORK_COMPLETE = "work.complete"
    WORK_DEFER = "work.defer"
    WORK_CANCEL = "work.cancel"
    UNIT_BEGIN = "unit.begin"
    UNIT_PROGRESS = "unit.progress"
    UNIT_COMPLETE = "unit.complete"
    UNIT_FAILED = "unit.failed"
    DRIVER_SPAWN = "driver.spawn"
    DRIVER_READY = "driver.ready"
    DRIVER_INVOKE = "driver.invoke"
    DRIVER_RESULT = "driver.result"
    DRIVER_CRASH = "driver.crash"
    DRIVER_QUARANTINE = "driver.quarantine"
    DRIVER_SHUTDOWN = "driver.shutdown"
    SERVICE_ATTACH = "service.attach"
    SERVICE_SPAWN = "service.spawn"
    SERVICE_REFUSE = "service.refuse"
    SERVICE_EVICT = "service.evict"
    SERVICE_COALESCE = "service.coalesce"
    CACHE_HIT = "cache.hit"
    CACHE_MISS = "cache.miss"
    CACHE_CORRUPT = "cache.corrupt"
    CACHE_WRITE = "cache.write"
    CACHE_SWEEP = "cache.sweep"
    BUDGET_RESERVE = "budget.reserve"
    BUDGET_DENY = "budget.deny"
    BUDGET_COMMIT = "budget.commit"
    STORE_TXN = "store.txn"
    STORE_WAL_VALVE = "store.wal_valve"
    STORE_BULK_LOCK = "store.bulk_lock"
    STORE_CONTEND = "store.contend"
    DEP_RECORD = "dep.record"
    DEP_INVALIDATE = "dep.invalidate"
    GC_SWEEP = "gc.sweep"
    DEGRADE = "degrade"
    MANIFEST_WRITE = "manifest.write"
    QUERY_PLAN = "query.plan"
    QUERY_CHANNEL = "query.channel"
    QUERY_COMPLETE = "query.complete"
    QUERY_REFUSE = "query.refuse"
    COMPILE_BEGIN = "compile.begin"
    COMPILE_UNIT = "compile.unit"
    COMPILE_GATE = "compile.gate"
    TOOLCHAIN_RUN = "toolchain.run"
    DRIVER_LOG = "driver.log"
    DOCTOR_CHECK = "doctor.check"
    SHARD_ROLL = "shard.roll"
    PLAN_BEGIN = "plan.begin"
    PLAN_END = "plan.end"
    ATTEMPT_BEGIN = "attempt.begin"
    ATTEMPT_END = "attempt.end"
    CALL_BEGIN = "call.begin"
    CALL_END = "call.end"


@dataclass(frozen=True, slots=True)
class EventSpec:
    """One `[[event]]` row: a `kind`, its `level`, and the keys permitted in `Event.fields`.

    **`level` has no default.** 15:341 makes it required on every row *"including the charter's
    forty-eight"* and calls that the one change to `tools/events.toml` that is not an append; a
    default here would let a row ship without the decision that sentence is about. `ConfigKey.axis`
    is the same shape for the same reason.

    `fields` is a tuple and is allowed to be empty (`unit.begin` carries none): a `kind` whose whole
    content is the envelope is a real row, and `()` says so where a `None` would ask a reader
    whether the row was finished.
    """

    kind: EventKind
    level: Level
    fields: tuple[str, ...] = ()
    span: str | None = None
    phase: Phase = Phase.POINT

    def __post_init__(self) -> None:
        if not self.kind:
            raise ConfigError(
                "an event row with no kind",
                fix="give the row a dotted kind, e.g. kind = 'work.claim'",
            )
        if len(set(self.fields)) != len(self.fields):
            raise ConfigError(
                f"{self.kind} declares a field twice: {self.fields}",
                fix="every key in Event.fields is named once",
            )
        if self.span is not None and self.span not in SPAN_PARENT:
            raise ConfigError(
                f"{self.kind} claims span level {self.span!r}, which is not one of "
                f"{tuple(SPAN_PARENT)}",
                fix="15-observability.md:73's hierarchy is five deep and closed",
            )
        if (self.span is None) != (self.phase is Phase.POINT):
            raise ConfigError(
                f"{self.kind} has span={self.span!r} and phase={self.phase.value!r}: a span "
                f"boundary names its level and a point event names none",
                fix="set both, or neither",
            )


def _row(
    kind: EventKind,
    level: Level,
    fields: tuple[str, ...] = (),
    *,
    span: str | None = None,
    phase: Phase = Phase.POINT,
) -> EventSpec:
    return EventSpec(kind=kind, level=level, fields=fields, span=span, phase=phase)


_DECLARATIONS: Final[tuple[EventSpec, ...]] = (
    # -- the charter's forty-eight, `_notes/charter.md:4462-4620`, in charter order -------------
    # `level` is 15:1273's, named there for twenty of these and derived from its `meaning` column
    # for the other twenty-eight. See `test_every_level_the_plan_names_is_the_level_declared`.
    _row(
        EventKind.RUN_START,
        Level.NOTICE,
        ("trigger", "argv_digest", "config_digest", "semantic_digest", "generation"),
        span=SpanLevel.RUN.value,
        phase=Phase.START,
    ),
    _row(
        EventKind.RUN_END,
        Level.NOTICE,
        ("status", "units", "failures", "micros", "events_dropped"),
        span=SpanLevel.RUN.value,
        phase=Phase.END,
    ),
    _row(EventKind.RUN_DEGRADED, Level.ERROR, ("degradation_kind", "message")),
    _row(EventKind.PLAN_DISCOVER, Level.INFO, ("scope_id", "discovered", "skipped")),
    _row(EventKind.PLAN_IDENTIFY, Level.INFO, ("part_count",)),
    _row(EventKind.PLAN_EXPAND, Level.INFO, ("rows",)),
    _row(EventKind.PLAN_PAUSE, Level.NOTICE, ("claimable", "high_water")),
    _row(EventKind.PLAN_RESUME, Level.NOTICE, ("claimable", "low_water")),
    _row(EventKind.WORK_ENQUEUE, Level.DEBUG, ("work_id", "cost_class", "dispatch_key")),
    _row(EventKind.WORK_CLAIM, Level.INFO, ("work_id", "batch_size", "claimed_gen", "lease_ms")),
    _row(EventKind.WORK_LEASE_EXTEND, Level.DEBUG, ("work_id", "lease_ms")),
    _row(EventKind.WORK_LEASE_REAP, Level.WARN, ("work_id", "age_ms")),
    _row(
        EventKind.WORK_COMPLETE,
        Level.INFO,
        ("work_id", "outcome", "rows_written", "micros", "was_cache_hit"),
    ),
    _row(EventKind.WORK_DEFER, Level.WARN, ("work_id", "dim", "retry_after")),
    _row(EventKind.WORK_CANCEL, Level.NOTICE, ("work_id", "generation")),
    _row(EventKind.UNIT_BEGIN, Level.INFO, (), span=SpanLevel.UNIT.value, phase=Phase.START),
    _row(EventKind.UNIT_PROGRESS, Level.DEBUG, ("done", "total")),
    _row(
        EventKind.UNIT_COMPLETE,
        Level.INFO,
        ("outcome", "queued_ms", "ran_ms"),
        span=SpanLevel.UNIT.value,
        phase=Phase.END,
    ),
    _row(EventKind.UNIT_FAILED, Level.WARN, ("failure_class", "message")),
    _row(EventKind.DRIVER_SPAWN, Level.NOTICE, ("driver", "config_digest", "isolation")),
    _row(
        EventKind.DRIVER_READY,
        Level.NOTICE,
        ("driver", "version", "schema_version", "code_fingerprint"),
    ),
    _row(
        EventKind.DRIVER_INVOKE,
        Level.INFO,
        ("driver", "invoke_id", "units", "batch_index", "batch_size"),
    ),
    _row(EventKind.DRIVER_RESULT, Level.INFO, ("driver", "invoke_id", "unit_index", "outcome")),
    _row(EventKind.DRIVER_CRASH, Level.ERROR, ("driver", "failure_class", "stderr_tail_bytes")),
    _row(EventKind.DRIVER_QUARANTINE, Level.ERROR, ("driver", "crashes", "window_s")),
    _row(EventKind.DRIVER_SHUTDOWN, Level.NOTICE, ("driver", "grace_ms")),
    _row(EventKind.SERVICE_ATTACH, Level.NOTICE, ("name", "model_id", "model_rev", "base_url")),
    _row(EventKind.SERVICE_SPAWN, Level.NOTICE, ("name", "cold_start_ms")),
    _row(EventKind.SERVICE_REFUSE, Level.ERROR, ("name", "reason")),
    _row(EventKind.SERVICE_EVICT, Level.NOTICE, ("name", "reason")),
    _row(EventKind.SERVICE_COALESCE, Level.DEBUG, ("name", "batch", "wait_ms")),
    _row(EventKind.CACHE_HIT, Level.INFO, ("layer", "cache_key", "would_have_been_micros")),
    _row(EventKind.CACHE_MISS, Level.INFO, ("layer", "cache_key", "verdict")),
    _row(EventKind.CACHE_CORRUPT, Level.WARN, ("layer", "cache_key")),
    _row(EventKind.CACHE_WRITE, Level.DEBUG, ("layer", "cache_key", "bytes", "micros")),
    _row(EventKind.CACHE_SWEEP, Level.NOTICE, ("layer", "rows", "bytes")),
    _row(EventKind.BUDGET_RESERVE, Level.DEBUG, ("dim", "scope", "amount")),
    _row(EventKind.BUDGET_DENY, Level.WARN, ("dim", "scope", "headroom")),
    _row(EventKind.BUDGET_COMMIT, Level.DEBUG, ("dim", "scope", "amount")),
    _row(EventKind.STORE_TXN, Level.DEBUG, ("rows", "ms")),
    _row(EventKind.STORE_WAL_VALVE, Level.WARN, ("wal_bytes", "action", "armed")),
    _row(EventKind.STORE_BULK_LOCK, Level.NOTICE, ("indexes_dropped",)),
    _row(EventKind.STORE_CONTEND, Level.WARN, ("holder", "waited_ms")),
    _row(EventKind.DEP_RECORD, Level.DEBUG, ("kind", "keys")),
    _row(EventKind.DEP_INVALIDATE, Level.NOTICE, ("kind", "keys", "dependents")),
    _row(EventKind.GC_SWEEP, Level.NOTICE, ("rows", "bytes")),
    _row(EventKind.DEGRADE, Level.WARN, ("degradation_kind", "message")),
    _row(EventKind.MANIFEST_WRITE, Level.NOTICE, ("path", "sha256")),
    # -- 15-observability.md:293-339's eleven, with the `level` that document declares ----------
    _row(
        EventKind.QUERY_PLAN,
        Level.INFO,
        ("surface", "mode", "plan_digest", "narrowing_kind", "narrowing_n", "prefilter_exact"),
    ),
    _row(
        EventKind.QUERY_CHANNEL,
        Level.INFO,
        ("channel", "status", "reason", "ranked_n", "ran_ms", "truncated_at_limit"),
    ),
    _row(
        EventKind.QUERY_COMPLETE,
        Level.INFO,
        ("verdict_state", "gates_n", "confidence", "returned_n", "latency_ms", "micros"),
    ),
    _row(EventKind.QUERY_REFUSE, Level.WARN, ("code", "detail")),
    _row(EventKind.COMPILE_BEGIN, Level.NOTICE, ("target", "slug", "artifact_gen", "units")),
    _row(EventKind.COMPILE_UNIT, Level.INFO, ("unit_index", "unit_outcome", "reason", "nsig")),
    _row(
        EventKind.COMPILE_GATE,
        Level.NOTICE,
        ("gate_status", "findings_error", "findings_warning", "determinism"),
    ),
    _row(
        EventKind.TOOLCHAIN_RUN,
        Level.NOTICE,
        ("name", "version", "queued_ms", "ran_ms", "exit_code"),
    ),
    _row(EventKind.DRIVER_LOG, Level.INFO, ("driver_level", "message", "redacted")),
    _row(EventKind.DOCTOR_CHECK, Level.INFO, ("check_id", "status", "detail")),
    _row(EventKind.SHARD_ROLL, Level.NOTICE, ("closed", "successor", "bytes", "records")),
    # -- this cell's six: the span boundaries three of the five levels had no kind for ----------
    _row(
        EventKind.PLAN_BEGIN, Level.NOTICE, ("stage",), span=SpanLevel.PLAN.value, phase=Phase.START
    ),
    _row(
        EventKind.PLAN_END,
        Level.NOTICE,
        ("stage", "elapsed_ms"),
        span=SpanLevel.PLAN.value,
        phase=Phase.END,
    ),
    _row(
        EventKind.ATTEMPT_BEGIN,
        Level.INFO,
        ("attempt", "claimed_gen", "lease_ms", "rung", "lane"),
        span=SpanLevel.ATTEMPT.value,
        phase=Phase.START,
    ),
    _row(
        EventKind.ATTEMPT_END,
        Level.INFO,
        ("attempt", "outcome", "failure_class", "retry_after"),
        span=SpanLevel.ATTEMPT.value,
        phase=Phase.END,
    ),
    _row(
        EventKind.CALL_BEGIN,
        Level.INFO,
        (
            "driver",
            "driver_version",
            "driver_schema_v",
            "isolation",
            "invoke_id",
            "batch_index",
            "batch_size",
            "dispatch_key",
            "service",
            "provider",
        ),
        span=SpanLevel.CALL.value,
        phase=Phase.START,
    ),
    _row(
        EventKind.CALL_END,
        Level.INFO,
        (
            "invoke_id",
            "wall_ms",
            "cpu_ms",
            "gpu_ms",
            "tokens_in",
            "tokens_out",
            "calls",
            "bytes_egress",
            "micros",
        ),
        span=SpanLevel.CALL.value,
        phase=Phase.END,
    ),
)

EVENT_ORDER: Final[tuple[str, ...]] = tuple(spec.kind.value for spec in _DECLARATIONS)
"""Every `kind`, in append order. This tuple IS `tools/events.toml`'s row order.

`_notes/charter.md:4458` and `15:293`: *"Ordering is append order; nothing is renumbered."* G20
reads this to check the property a generated file cannot enforce on its own -- that a row was never
removed and a `kind` was never reused -- by diffing against the previous tag."""

if len(set(EVENT_ORDER)) != len(EVENT_ORDER):  # pragma: no cover -- a duplicated declaration.
    raise AssertionError("an event kind is declared twice")
if tuple(member.value for member in EventKind) != EVENT_ORDER:  # pragma: no cover
    raise AssertionError("EventKind and _DECLARATIONS disagree about the vocabulary or its order")

EVENTS: Final[Mapping[str, EventSpec]] = MappingProxyType(
    {spec.kind.value: spec for spec in _DECLARATIONS}
)
"""The closed vocabulary, by `kind`. 02-architecture.md:245's `EVENTS`.

*"A row is never removed and a `kind` is never reused: an event kind is a name a dashboard, a
runbook and a test all hard-code, so retiring one silently breaks three consumers"* (15:283-286)."""


def kinds_at(span: str, phase: Phase | None = None) -> tuple[str, ...]:
    """The span-boundary kinds for one level, optionally narrowed to one phase. Append order."""
    return tuple(
        spec.kind.value
        for spec in _DECLARATIONS
        if spec.span == span and (phase is None or spec.phase is phase)
    )


def is_span_kind(kind: str) -> bool:
    """Whether this `kind` opens or closes a span rather than recording a point."""
    spec = EVENTS.get(kind)
    return spec is not None and spec.span is not None


EVENTS_DROPPED_DEGRADATION: Final = "events_dropped"
"""15:968's member, for the record `15:40` requires *"in those words"*.

*"The drop count is itself reported, as `run.events_dropped` and as
`Degradation(kind="events_dropped")` on the result."* The type is 15:964's sole property and does
not exist yet; this is the literal, not the type."""


# =============================================================================================
# 4. The record, and the two clocks
# =============================================================================================

Scalar = str | int | float | bool | None
"""What may ride in `Event.fields`. 15:355 types it `Mapping[str, Scalar]`.

Flat and scalar, which is 14-security.md:891's requirement restated as a type: *"a flat scalar
`fields` map drawn from the closed `tools/events.toml` vocabulary -- a string field is a name, a
code or an id -- never document text, never prompt text, never a secret."* A nested mapping would
be a place for a `quote` to hide from the key allowlist."""


@dataclass(frozen=True, slots=True)
class Event:
    """One record. 15-observability.md:352-364, field for field.

    **Both clocks, always, and both read host-side.** 15:366-367: *"`ts_wall_ns` is for humans and
    correlation with an external system; **every duration is computed from `ts_mono_ns`**, and both
    are read host-side by the sink."* 15:201-207 gives the reason the sink reads them rather than
    the producer: a monotonic clock is per process, so a `ts_mono_ns` from an S4 worker, a Toolchain
    child or a model server is not comparable with the host's. A driver-supplied timestamp is a
    value in `fields` and never an envelope field.

    `parent_span_id` is `None` only on a `run` span. Everything else has a parent, which is what
    I33's *"zero orphans and zero cycles"* is a check over.
    """

    ts_wall_ns: int
    ts_mono_ns: int
    run_id: str
    writer_id: str
    seq: int
    trace_id: str
    span_id: str
    parent_span_id: str | None
    kind: EventKind
    phase: Literal["start", "end", "point"]
    level: Literal["debug", "info", "notice", "warn", "error"]
    unit: str | None = None
    part: str = ""
    operator: str | None = None
    driver: str | None = None
    fields: Mapping[str, Scalar] = field(default_factory=dict)

    def spec(self) -> EventSpec:
        """This record's row. Raises on a kind outside the closed vocabulary."""
        spec = EVENTS.get(self.kind)
        if spec is None:
            raise ConfigError(
                f"{self.kind!r} is not an event kind; the vocabulary is closed and has "
                f"{len(EVENTS)} rows",
                fix="add a row to omniweave_core.events._DECLARATIONS and regenerate "
                "tools/events.toml, or emit an existing kind",
            )
        return spec

    def validate(self) -> None:
        """Refuse a record the vocabulary does not permit. Called by the sink, not by `__init__`.

        Not in `__post_init__` deliberately: 15:36 makes the stream *"diagnostic"* and 15:47 says
        an unwritable path *"is a `Degradation(kind='events_dropped')` and the run continues:
        telemetry never fails a run."* A constructor that raised would make a mis-typed field name
        in a rarely-hit branch a crash in the run rather than a dropped record, which is the
        direction that sentence forbids. The sink calls this, counts a refusal, and carries on.

        Three clauses, and the second is the security one: 14-security.md:891 keeps document text
        out of the stream by allowlisting keys per `kind`, so a key the row does not declare is not
        a typo to tolerate -- it is the exact shape a leak takes.
        """
        spec = self.spec()
        if self.phase != spec.phase.value and spec.span is not None:
            raise ConfigError(
                f"{self.kind} is declared phase={spec.phase.value!r} and this record carries "
                f"{self.phase!r}: a span boundary's phase is a property of its kind",
                fix=f"emit {self.kind} with phase={spec.phase.value!r}",
            )
        undeclared = tuple(key for key in self.fields if key not in spec.fields)
        if undeclared:
            raise ConfigError(
                f"{self.kind} permits {spec.fields} and this record carries {undeclared}",
                fix="add the key to the row in omniweave_core.events and regenerate "
                "tools/events.toml, or drop it",
            )
        if self.level != spec.level.value:
            raise ConfigError(
                f"{self.kind} is declared {spec.level.value!r} and this record carries "
                f"{self.level!r}: the level is the kind's, never the call site's",
                fix=f"emit {self.kind} at level {spec.level.value!r}",
            )


@runtime_checkable
class TraceSink(Protocol):
    """15:361-363. Two methods, and a third is a charter amendment (15:54).

    *"No new sink type, ever. A fifteenth `omniweave-otel` distribution plus an `omniweave.sinks`
    entry-point group was rejected in the charter as a third extension point created for one
    implementation."*
    """

    def emit(self, e: Event) -> None:
        """MUST NOT BLOCK. 15:361, in capitals in the plan."""
        ...

    def flush(self, timeout_ms: int) -> int:
        """Returns the number still queued. 15:362."""
        ...


# =============================================================================================
# 5. Trace context: the ids, and the one flag that is always 01
# =============================================================================================

TRACE_ID_HEX_LEN: Final = 32
"""16 bytes as hex. 15:357 -- *"W3C shaped: 16B / 8B, hex."*"""

SPAN_ID_HEX_LEN: Final = 16
"""8 bytes as hex."""

TRACE_FLAGS_SAMPLED: Final = "01"
"""15:186-189: *"The sampled flag is always `01`, because tail sampling means anything reaching a
wire was already selected; a `00` would instruct a downstream server to discard what we have decided
to keep."* A constant and not a parameter: there is no caller entitled to the other value."""

TRACEPARENT_RE: Final = r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$"
"""What a seam may accept. Version `00`, lowercase hex, and the sampled flag above.

Declared as a pattern rather than left to a parser because four seams carry a `traceparent`
(15:191-197) and each of them validates what it received; four hand-written checks is four places
the flag could be read as optional."""


def traceparent(trace_id: str, span_id: str) -> str:
    """`"00-{trace_id}-{span_id}-01"`. 15:186, signature and all.

    Both ids are checked, because this string crosses four seams and a malformed one is rejected by
    a W3C-conformant peer with no diagnostic that reaches us -- the trace simply stops, which is
    the hole 15:199 is about.
    """
    _require_hex(trace_id, TRACE_ID_HEX_LEN, "trace_id")
    _require_hex(span_id, SPAN_ID_HEX_LEN, "span_id")
    if int(trace_id, 16) == 0 or int(span_id, 16) == 0:
        raise ConfigError(
            "an all-zero trace or span id is invalid under W3C trace-context and a conformant "
            "peer drops it",
            fix="mint ids from os.urandom(16) and os.urandom(8)",
        )
    return f"00-{trace_id}-{span_id}-{TRACE_FLAGS_SAMPLED}"


def _require_hex(value: str, width: int, name: str) -> None:
    if len(value) != width or any(char not in "0123456789abcdef" for char in value):
        raise ConfigError(
            f"{name} must be {width} lowercase hex characters and this is {len(value)}",
            fix=f"pass os.urandom({width // 2}).hex()",
        )


def writer_id(host: str, pid: int, process_create_time: str) -> str:
    """`sha256(host || pid || process_create_time)[:12]`. 15:372-374.

    *"the same triple `work.claimed_by` uses. One run can have several writers -- a detached
    `ow add` child, a hook invocation inside a `watch` run -- and a bare per-`run_id` counter would
    have each of them restarting at 1, making every gap indistinguishable from a collision."*

    The third component is what `0004_runtime.sql:110` calls out for `claimed_by`: it *"stops a
    recycled pid from looking like a live holder"*. A writer id that collided across two processes
    would make `seq` non-monotone within one writer and break exactly the gap detection this exists
    for, so it takes the same triple and not a shorter one.
    """
    if not host or not process_create_time:
        raise ConfigError(
            "a writer id needs a host and a process create time; without the third component a "
            "recycled pid looks like the same writer",
            fix="pass socket.gethostname() and the process's own create time",
        )
    joined = f"{host}{pid}{process_create_time}".encode()
    return hashlib.sha256(joined).hexdigest()[:WRITER_ID_HEX_LEN]


WRITER_ID_HEX_LEN: Final = 12
"""15:372's `[:12]`. 48 bits over the writer processes in one run, which is a single-digit count."""


# =============================================================================================
# 6. Tail sampling at the `unit` boundary
# =============================================================================================

NON_OK_SAMPLE_RATE: Final = 1.0
"""`[observe] sample = { non_ok = 1.0, ... }`. Everything that did not settle `ok` is kept."""

OK_SAMPLE_RATE: Final = 0.015625
"""One in 64. 15:150 -- *"the charter's `[observe]` default."*"""

_SAMPLE_DIGEST_BYTES: Final = 8
"""The prefix compared against `rate * 2**64`. 15:160's `digest()[:8]`."""


def sample_key(work_id: str, salt: str) -> int:
    """`int.from_bytes(blake2b(work_id || salt).digest()[:8], "big")`. 15:160, verbatim.

    15:151-152 gives the reason it is a digest and not an RNG: *"the key is `blake2b(work_id ‖
    salt)`, never RNG, so two processes select the same set and a replay selects the same set."*
    A sampled trace that differed between a run and its replay would make every comparison between
    them a comparison of two different subsets.
    """
    digest = hashlib.blake2b(f"{work_id}{salt}".encode()).digest()
    return int.from_bytes(digest[:_SAMPLE_DIGEST_BYTES], "big")


def should_sample(
    outcome: str, work_id: str, salt: str, *, ok_rate: float = OK_SAMPLE_RATE
) -> bool:
    """Tail sampling, decided at span CLOSE. 15:148-163.

    15:154-157 is why the decision cannot be made at `unit.begin`: *"the outcome is not yet known,
    so `non_ok = 1.0` is unimplementable; and dropping a `unit` while keeping its `call` children
    produces exactly the orphans I33's CI test forbids."* So this takes an `outcome`, which only
    exists once the unit has settled, and the sink buffers the subtree until then.

    `outcome != "ok"` keeps the whole subtree -- `ok_partial`, every `failed_*`, `deferred_budget`,
    `cancelled` and both `skipped_*` verdicts. That is wider than "failures" on purpose: a cache hit
    that should not have been one is diagnosed from the trace, and at one in 64 the sampled stream
    would hold nothing to diagnose it with.
    """
    if outcome != "ok":
        return True
    if not 0.0 <= ok_rate <= 1.0:
        raise ConfigError(
            f"[observe] sample.ok is {ok_rate}; a rate is a fraction",
            fix="set [observe] sample = { non_ok = 1.0, ok = 0.015625 }",
        )
    return sample_key(work_id, salt) < ok_rate * 2**64


# =============================================================================================
# 7. Serialising a record: one line, sorted keys, and nothing between the separators
# =============================================================================================

NDJSON_SEPARATORS: Final[tuple[str, str]] = (",", ":")
"""15:389's `json.dumps(..., sort_keys=True, separators=(",", ":"))`, transcribed.

Three properties in one call, and the plan names all three: *"One record per line, UTF-8 …, no
trailing whitespace."* `sort_keys` makes two records with the same content one byte string, which is
what lets a test diff a stream; the tight separators are what makes the ~180 B per record of
15:3.3's arithmetic reachable; and the absence of an indent is what keeps one record on one line,
which is the entire NDJSON contract."""


def serialise(event: Event) -> bytes:
    """One record as one UTF-8 line, newline-terminated. 15:389.

    `ensure_ascii=False` keeps a non-ASCII name as itself rather than as twelve bytes of escapes --
    the file is declared UTF-8, so escaping is cost without a reader. `allow_nan=False` because NaN
    is not JSON and a `float('nan')` in `fields` would otherwise produce a line no conformant parser
    on the other side can read.
    """
    body = {
        "ts_wall_ns": event.ts_wall_ns,
        "ts_mono_ns": event.ts_mono_ns,
        "run_id": event.run_id,
        "writer_id": event.writer_id,
        "seq": event.seq,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "parent_span_id": event.parent_span_id,
        "kind": str(event.kind),
        "phase": event.phase,
        "level": event.level,
        "unit": event.unit,
        "part": event.part,
        "operator": event.operator,
        "driver": event.driver,
        "fields": dict(event.fields),
    }
    text = json.dumps(
        body, sort_keys=True, separators=NDJSON_SEPARATORS, ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8") + b"\n"


def parse_line(line: str) -> Event | None:
    """One line back into an `Event`, or `None` for a line that is not one.

    15:390: *"A partial final line is skipped on read, never repaired."* A writer killed mid-record
    leaves a prefix of a JSON document, and the only honest thing a reader can do with it is drop
    it -- repairing would invent a record that was never emitted, and raising would make one
    truncated byte at the end of a 370,000-record shard cost the whole shard.

    A line that parses but is not a record of this shape is `None` for the same reason. This is the
    read path and the read path is not a validator: `Event.validate()` is the writer's check, and a
    reader that refused a record the writer already accepted could not read its own output.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        body = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or "kind" not in body or "seq" not in body:
        return None
    try:
        return Event(
            ts_wall_ns=int(body["ts_wall_ns"]),
            ts_mono_ns=int(body["ts_mono_ns"]),
            run_id=str(body["run_id"]),
            writer_id=str(body["writer_id"]),
            seq=int(body["seq"]),
            trace_id=str(body["trace_id"]),
            span_id=str(body["span_id"]),
            parent_span_id=(
                None if body.get("parent_span_id") is None else str(body["parent_span_id"])
            ),
            kind=EventKind(body["kind"]),
            phase=body["phase"],
            level=body["level"],
            unit=body.get("unit"),
            part=str(body.get("part", "")),
            operator=body.get("operator"),
            driver=body.get("driver"),
            fields=dict(body.get("fields") or {}),
        )
    except (KeyError, TypeError, ValueError):
        return None


# =============================================================================================
# 8. What the sink reports about itself
# =============================================================================================


@dataclass(slots=True)
class SinkStats:
    """The four numbers 15:434 puts in the manifest, plus two the roll produces.

    15:432-436: *"The manifest records what observability actually cost -- `observe.events_emitted`,
    `observe.events_dropped`, `observe.serialise_ns_total`, `observe.shard_bytes` -- adopting
    graphrag's habit of reporting the profiler's own overhead so a reader can subtract it. A number
    that cannot be subtracted contaminates every measurement beside it."*

    Mutable, unlike almost everything else in this module: it is a running tally inside one sink and
    a frozen counter would mean one allocation per record on the hot path.

    `refused` is not in the plan's four and is separate from `dropped` on purpose. A drop is back
    pressure -- the queue was full and the oldest record went, which 15:38 designs for. A refusal is
    a record `validate()` rejected, which is a **bug in a call site** and not a load condition;
    adding it to `events_dropped` would let a mis-typed field name hide inside a number an operator
    reads as "the machine was busy".
    """

    emitted: int = 0
    dropped: int = 0
    refused: int = 0
    serialise_ns_total: int = 0
    shard_bytes: int = 0
    shards_rolled: int = 0

    def as_manifest_fields(self) -> Mapping[str, int]:
        """The `observe.*` keys, under the names 15:434 prints."""
        return MappingProxyType(
            {
                "events_emitted": self.emitted,
                "events_dropped": self.dropped,
                "events_refused": self.refused,
                "serialise_ns_total": self.serialise_ns_total,
                "shard_bytes": self.shard_bytes,
                "shards_rolled": self.shards_rolled,
            }
        )


# =============================================================================================
# 9. `NdjsonSink` -- a bounded drop-oldest queue, one writer thread, and a 64 MiB roll
# =============================================================================================

SHARD_ORDINAL_DIGITS: Final = 4
"""`{run_id}.0001.ndjson.gz` (15:387). Four digits is 9,999 shards, which at 64 MiB each is 625 GiB
of uncompressed events for one run -- five hundred times the reference ingest's unsampled 1.22
GB."""

DEFAULT_SHARD_BYTES: Final = 67_108_864
"""`[observe] shard_bytes = 67108864`. 64 MiB **of uncompressed bytes** (15:396)."""


def shard_path(live: Path, ordinal: int) -> Path:
    """The name a rolled shard takes. `{run_id}.ndjson` -> `{run_id}.0001.ndjson.gz`.

    Derived from the live path rather than from a `run_id`, because `[observe] ndjson_path` is a
    template an operator may change and the rolled name has to stay beside whatever it produced. A
    follower resolves the successor from the `shard.roll` record's `successor` field and never by
    guessing this (15:264-268), so this function has exactly one caller.
    """
    if ordinal < 1:
        raise ConfigError(
            f"a shard ordinal of {ordinal}; the live shard has no ordinal and rolls start at 1",
            fix="pass the count of shards already rolled, plus one",
        )
    stem = live.name.removesuffix(".ndjson")
    return live.with_name(f"{stem}.{ordinal:0{SHARD_ORDINAL_DIGITS}d}.ndjson.gz")


class _Stop:
    """The sentinel that ends the writer thread. A class, so no record can equal it."""


class NdjsonSink:
    """One record per line, one writer thread, and a queue that drops rather than blocks.

    **`emit()` must not block** (15:361, in capitals; 08:882). Everything expensive happens on the
    writer thread: the serialisation, the write, the roll and the deflate. `emit()` puts one object
    on a bounded queue and returns, and when the queue is full it discards the OLDEST record and
    counts it. Dropping the newest would be cheaper and is wrong: under back pressure the records
    that matter are the ones describing what is happening now, and a queue that discarded them would
    preserve a history of a run that had stopped being interesting.

    **An unwritable path is a degradation and not a failure.** 15:401-403: *"An unwritable path is a
    `Degradation(kind="events_dropped")` and the run continues: telemetry never fails a run, exactly
    as telemetry never fails a query."* So `open()` failing is recorded in `stats.dropped` and
    `degraded` rather than raised, and every later record is counted and discarded. The run's work
    is not affected at all, which is rule 1 of 15:36 -- *"the event stream is diagnostic; the ledger
    is
    authoritative."*

    **The `Clock` is injected here too, and that is not ceremony.** 15:434 requires
    `observe.serialise_ns_total` in the manifest *"so a reader can subtract it"*, which is a
    duration measurement, and 08:277 makes `Clock` the one duration source -- *"INJECTED:
    `monotonic_ns()` + `wall_ns()`. Never ambient"*. G8 bans `time.perf_counter_ns()` in library
    code for the same reason, so the machine reading belongs in the `Clock` implementation and
    nowhere else. A test supplies a counting clock and gets a deterministic total.

    **`fsync` only on roll and at exit** (15:400). A per-record `fsync` would put a disk flush
    inside the charter's `<= 0.5 ms/unit` runtime overhead budget eight times per unit; the exposure
    that
    buys is the tail of the live shard after a power loss, which is diagnostic data about a run that
    also did not commit.
    """

    __slots__ = (
        "_clock",
        "_closed",
        "_degraded",
        "_handle",
        "_live",
        "_lock",
        "_queue",
        "_rolled",
        "_shard_bytes",
        "_stats",
        "_thread",
        "_written",
    )

    def __init__(self, path: Path, *, clock: Clock, shard_bytes: int = DEFAULT_SHARD_BYTES) -> None:
        if shard_bytes < 1:
            raise ConfigError(
                f"[observe] shard_bytes is {shard_bytes}; a shard that rolls at zero bytes rolls "
                f"once per record",
                fix="set [observe] shard_bytes = 67108864",
            )
        self._live = path
        self._clock = clock
        self._shard_bytes = shard_bytes
        self._queue: queue.Queue[Event | type[_Stop]] = queue.Queue(maxsize=MAX_EVENT_QUEUE)
        self._stats = SinkStats()
        self._lock = threading.Lock()
        self._handle: IO[bytes] | None = None
        self._written = 0
        self._rolled = 0
        self._degraded = ""
        self._closed = False
        self._thread = threading.Thread(target=self._drain, name="ow-events", daemon=True)
        self._thread.start()

    # -- the producer side, which must not block -------------------------------------------

    def emit(self, e: Event) -> None:
        """Queue one record. Never blocks, never raises, never writes.

        The `try/except Full` loop rather than `put_nowait` inside a lock: `queue.Queue` is already
        thread-safe, and the race a lock would close -- two producers both seeing a full queue and
        both discarding one record -- costs one extra drop under contention and is counted. A lock
        here would serialise every producer behind the writer thread's own `get`, which is the one
        thing 15:361 forbids.
        """
        while True:
            try:
                self._queue.put_nowait(e)
            except queue.Full:
                self._discard_oldest()
            else:
                return

    def _discard_oldest(self) -> None:
        """Make room by dropping the OLDEST queued record, and count it.

        Oldest and not newest, which is the whole of 15:38's *"drop-oldest"*: under back pressure
        the records that matter describe what is happening now, and a queue that discarded those
        would preserve a detailed history of the moment the run stopped being interesting.

        `queue.Empty` here means the writer thread drained the queue between the failed `put` and
        this `get`, so there is nothing to discard and nothing to count -- the retry will succeed.
        """
        with contextlib.suppress(queue.Empty):
            self._queue.get_nowait()
            self._stats.dropped += 1

    def flush(self, timeout_ms: int) -> int:
        """Wait up to `timeout_ms` for the queue to drain. Returns the number still queued.

        15:362's signature and its return value. A number rather than a bool because the caller --
        the shutdown sequence, at `[runtime] shutdown_grace_ms` -- reports what it could not write
        rather than deciding for itself whether that was acceptable.
        """
        # `time.monotonic()` and not the injected clock: this is a WAIT and not a measurement --
        # nothing it produces reaches a row, a digest or the manifest, and a fake clock here would
        # make a shutdown that has to really elapse return instantly. G8's ban lists the readings
        # that can reach an artefact and `time.monotonic` is not among them.
        deadline = time.monotonic() + timeout_ms / 1000
        while self._queue.qsize() and time.monotonic() < deadline:
            time.sleep(0.001)
        return self._queue.qsize()

    def close(self, *, timeout_ms: int = 5_000) -> int:
        """Drain, `fsync`, close the handle and stop the thread. Returns what was left unwritten.

        Idempotent: a second call returns zero and does nothing, because a shutdown path that could
        be reached twice -- a signal handler and a `finally` -- would otherwise join a dead thread.
        """
        if self._closed:
            return 0
        self._closed = True
        remaining = self.flush(timeout_ms)
        self._queue.put(_Stop)
        self._thread.join(timeout=timeout_ms / 1000)
        return remaining

    # -- what a reader of the manifest gets ------------------------------------------------

    @property
    def stats(self) -> SinkStats:
        return self._stats

    @property
    def degraded(self) -> str:
        """Empty, or the one sentence a `Degradation(kind="events_dropped")` carries."""
        return self._degraded

    @property
    def live_path(self) -> Path:
        return self._live

    # -- the writer thread ------------------------------------------------------------------

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if item is _Stop:
                self._close_handle(sync=True)
                return
            if isinstance(item, Event):
                self._write(item)
            if self._queue.empty() and self._handle is not None:
                # Flush the userspace buffer when the queue goes quiet, so `flush()` waiting for the
                # queue is also waiting for the bytes. NOT an `fsync`: 15:400 puts the disk barrier
                # on roll and at exit only, and this is the cheaper of the two -- it moves bytes
                # into the OS, which is what a reader of the live shard needs and what a crash of
                # THIS process cannot take back. Doing it here rather than in `flush()` keeps every
                # access to the handle on the writer thread.
                with contextlib.suppress(OSError, ValueError):
                    self._handle.flush()

    def _write(self, event: Event) -> None:
        started = self._clock.monotonic_ns()
        line = serialise(event)
        self._stats.serialise_ns_total += self._clock.monotonic_ns() - started
        handle = self._open()
        if handle is None:
            self._stats.dropped += 1
            return
        handle.write(line)
        self._written += len(line)
        self._stats.emitted += 1
        self._stats.shard_bytes = self._written
        if self._written >= self._shard_bytes:
            self._roll(event)

    def _open(self) -> IO[bytes] | None:
        """The append handle, opened on first use. A failure degrades once and stays degraded."""
        if self._handle is not None:
            return self._handle
        if self._degraded:
            return None
        try:
            self._live.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._live.open("ab")
        except OSError as exc:
            self._degraded = (
                f"the event stream at {self._live} could not be opened ({exc.strerror or exc}); "
                f"this run's records are dropped and its work is unaffected. "
                f"Set [observe] ndjson_path to a writable location, or "
                f'[observe] sinks = ["console"]'
            )
            return None
        return self._handle

    def _roll(self, last: Event) -> None:
        """Close the live shard with a `shard.roll` record, rename it, deflate it, reopen.

        15:399 and 15:264-268. The roll record is *"the closing line of the shard it closes"* and
        carries the successor's name, which is what lets `ow trace export --follow` hold the open
        HANDLE rather than the path: it reads to EOF, sees the roll, and opens the name it was
        given. A follower that stat'ed the path in a loop would race the rename and read a `.gz` as
        text.

        The deflate happens here, on the writer thread, which is where 15:398 puts it. It is the one
        genuinely slow thing this class does -- tens of milliseconds for 64 MiB -- and it is off the
        producer's path by the whole width of the queue.
        """
        handle = self._handle
        if handle is None:  # pragma: no cover -- `_write` only calls this after `_open` succeeded.
            return
        ordinal = self._rolled + 1
        successor = shard_path(self._live, ordinal)
        record = dataclasses.replace(
            last,
            kind=EventKind.SHARD_ROLL,
            phase=Phase.POINT.value,
            level=EVENTS[EventKind.SHARD_ROLL.value].level.value,
            fields={
                "closed": self._live.name,
                "successor": successor.name,
                "bytes": self._written,
                "records": self._stats.emitted,
            },
        )
        handle.write(serialise(record))
        self._close_handle(sync=True)
        try:
            raw = self._live.read_bytes()
            with gzip.open(successor, "wb") as out:
                out.write(raw)
            self._live.unlink()
        except OSError as exc:  # pragma: no cover -- a roll that cannot rename keeps writing.
            self._degraded = f"shard {self._live} could not be rolled ({exc.strerror or exc})"
            return
        self._rolled = ordinal
        self._written = 0
        self._stats.shards_rolled = ordinal
        self._stats.shard_bytes = 0

    def _close_handle(self, *, sync: bool) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.flush()
            if sync:
                os.fsync(handle.fileno())
        except OSError:  # pragma: no cover -- a closed or unsyncable handle is already lost.
            pass
        handle.close()


# =============================================================================================
# 10. `ConsoleSink` -- stderr, and the suppression that is a correctness property
# =============================================================================================

CONSOLE_FLOOR_WHEN_PIPED: Final = Level.WARN
"""15:452: *"suppressed to `warn` and above when stderr is not a TTY."*"""


class ConsoleSink:
    """The same records for a human, one line each, on **stderr**. 15:444-457.

    *"Not stdout: stdout is the machine channel -- `ow query --render json`, `ow cost --render
    json`, `ow doctor --render json` -- and a progress line interleaved into a JSON document is a
    parse
    error in the caller, discovered by whoever automated the command rather than by us."*

    **It tests the stream, not a config flag.** 15:454-457 takes the lesson from codegraph's prompt
    hook (`if (process.stdin.isTTY) return;`): *"an interactive-only side effect must test the
    stream it writes to, not a config flag someone forgot to set."* So the floor is raised by asking
    the stream whether it is a terminal, once, at construction -- a hook, a cron and a piped
    invocation get `warn` and above without anybody having configured anything.

    There is no queue and no thread. A console line is bounded by the human reading it, `emit()`
    writes one line to an already-buffered stream, and a second queue would be a second place
    records could be dropped without the first one knowing.
    """

    __slots__ = ("_floor", "_stats", "_stream")

    def __init__(self, stream: IO[str] | None = None, *, floor: Level = Level.DEBUG) -> None:
        self._stream = stream if stream is not None else sys.stderr
        piped = not _isatty(self._stream)
        effective = CONSOLE_FLOOR_WHEN_PIPED if piped else floor
        self._floor = max(LEVEL_ORDER.index(floor.value), LEVEL_ORDER.index(effective.value))
        self._stats = SinkStats()

    @property
    def floor(self) -> Level:
        """The level this sink actually renders at, after the not-a-TTY suppression."""
        return Level(LEVEL_ORDER[self._floor])

    @property
    def stats(self) -> SinkStats:
        return self._stats

    def emit(self, e: Event) -> None:
        """One line, or nothing. Never raises: a broken stderr is not a reason to fail a run."""
        if LEVEL_ORDER.index(e.level) < self._floor:
            self._stats.dropped += 1
            return
        try:
            self._stream.write(self.render(e) + "\n")
        except (OSError, ValueError):  # pragma: no cover -- a closed or detached stderr.
            self._stats.dropped += 1
            return
        self._stats.emitted += 1

    def flush(self, timeout_ms: int) -> int:  # noqa: ARG002 -- nothing is queued to wait for.
        """Nothing is queued, so nothing is ever still queued. Flushes the stream and returns 0."""
        with contextlib.suppress(OSError, ValueError):  # pragma: no cover -- a closed stderr.
            self._stream.flush()
        return 0

    @staticmethod
    def render(e: Event) -> str:
        """One record as one human line. The envelope, then the fields, in declaration order.

        `fields` is rendered in the row's declared order rather than sorted: `tools/events.toml` is
        the order a reader of the vocabulary already knows, and `serialise()` sorts for the machine
        channel where a stable byte string is what matters.
        """
        spec = EVENTS.get(str(e.kind))
        order = spec.fields if spec is not None else tuple(sorted(e.fields))
        pairs = " ".join(f"{name}={e.fields[name]!r}" for name in order if name in e.fields)
        where = e.unit or ""
        if e.part:
            where = f"{where}#{e.part}" if where else f"#{e.part}"
        head = f"{e.level:<6} {e.kind}"
        return " ".join(part for part in (head, where, pairs) if part)


def _isatty(stream: object) -> bool:
    """Whether `stream` is a terminal, treating "it will not say" as "no".

    A `StringIO` has no `isatty`, a detached stream raises from it, and both mean the same thing for
    this decision: there is nobody watching, so render less. Failing closed here is what stops a
    captured stream in a test or a CI log from filling with `info` lines.
    """
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):  # pragma: no cover -- a detached stream.
        return False


# =============================================================================================
# 11. `RunRecorder` -- `seq` at the head, the floor, and the tail-sampling buffer
# =============================================================================================


@dataclass(slots=True)
class _UnitBuffer:
    """One open `unit` span's held subtree. 15:157-159."""

    span_ids: set[str]
    held: list[Event]
    overflowed: bool = False


class RunRecorder:
    """The sink a run holds: it stamps `seq`, applies the floor, buffers, and fans out.

    **Why this is a `TraceSink` and 15:56 still counts two.** That sentence -- *"`TraceSink` is a
    Protocol with two methods and two shipped implementations; a third is a charter amendment"* --
    rejects, in its own next clause, *"a fifteenth `omniweave-otel` distribution plus an
    `omniweave.sinks` entry-point group … a third extension point created for one implementation."*
    The two it counts are the two that WRITE. This one writes nothing: it consumes and forwards, and
    it exists because three facts in 15 cannot all be true of a terminal sink at once:

    * `RunContext.events` is typed `TraceSink` (08:281), so an operator's only channel is `emit()`;
    * `seq` is *"assigned under the sink's own lock at the head of `emit()`"* (15:381);
    * `[observe] sinks` is a LIST, defaulting to two.

    Two terminal sinks each assigning `seq` under their own lock would give one record two values
    for one field. So the assignment belongs to the object the run holds, and that object is this
    one. Reported.

    **`seq` before the queue, always.** 15:382-385: *"That ordering is what makes a drop detectable
    as a gap in `seq` rather than invisible; the reverse ordering would have made
    `run.events_dropped` the only evidence a record ever existed."* So the counter advances for
    every record that passes the floor, including one a downstream queue is about to discard -- the
    gap is
    the evidence.

    **Tail sampling buffers a unit's whole subtree** (15:154-163). Deciding at `unit.begin` is wrong
    twice: the outcome is not known yet, so `non_ok = 1.0` is unimplementable, and dropping a `unit`
    while keeping its `call` children produces the orphans I33 forbids. `open_unit()` and
    `close_unit()` bracket the buffer; `run` and `plan` records are never buffered, so the tree
    always has a spine.
    """

    __slots__ = (
        "_buffers",
        "_clock",
        "_floor",
        "_lock",
        "_ok_rate",
        "_owner",
        "_run_id",
        "_salt",
        "_seq",
        "_sinks",
        "_stats",
        "_writer_id",
    )

    def __init__(
        self,
        *,
        run_id: str,
        writer: str,
        clock: Clock,
        sinks: Sequence[TraceSink] = (),
        level: Level = Level.INFO,
        salt: str = "",
        ok_rate: float = OK_SAMPLE_RATE,
    ) -> None:
        if not run_id or not writer:
            raise ConfigError(
                "a recorder needs a run_id and a writer_id; `seq` is monotone per the pair",
                fix="pass ctx.run_id and events.writer_id(host, pid, create_time)",
            )
        self._run_id = run_id
        self._writer_id = writer
        self._clock = clock
        self._sinks = tuple(sinks)
        self._floor = LEVEL_ORDER.index(level.value)
        self._salt = salt
        self._ok_rate = ok_rate
        self._lock = threading.Lock()
        self._seq = 0
        self._buffers: dict[str, _UnitBuffer] = {}
        self._owner: dict[str, str] = {}
        self._stats = SinkStats()

    # -- the `TraceSink` surface ------------------------------------------------------------

    def emit(self, e: Event) -> None:
        """Stamp `seq`, apply the floor, buffer or forward. Never blocks and never raises.

        The record arrives with whatever `seq` the caller left on it -- conventionally zero -- and
        leaves with this recorder's next. `dataclasses.replace` rather than mutation because `Event`
        is frozen, and it is frozen because a record that could be edited after the sink saw it
        would make the stream a mutable log.
        """
        spec = EVENTS.get(str(e.kind))
        if spec is None or LEVEL_ORDER.index(spec.level.value) < self._floor:
            self._stats.dropped += 1
            return
        with self._lock:
            self._seq += 1
            stamped = dataclasses.replace(
                e,
                run_id=self._run_id,
                writer_id=self._writer_id,
                seq=self._seq,
                level=spec.level.value,
                ts_wall_ns=e.ts_wall_ns or self._clock.wall_ns(),
                ts_mono_ns=e.ts_mono_ns or self._clock.monotonic_ns(),
            )
            buffered = self._buffer(stamped)
        if not buffered:
            self._forward(stamped)

    def flush(self, timeout_ms: int) -> int:
        """Flush every sink and report the worst. 15:362's return value, over a fan-out."""
        return max((sink.flush(timeout_ms) for sink in self._sinks), default=0)

    # -- the unit bracket, which is what makes tail sampling possible -----------------------

    def open_unit(self, work_id: str, span_id: str) -> None:
        """Start buffering the subtree under one `unit` span. 15:156.

        A second `open_unit` for one `work_id` is the REGEN case -- the same work row claimed again
        -- and it replaces the buffer rather than merging: the previous attempt's span closed with
        its own outcome, and holding two attempts' records under one sampling decision would make
        one attempt's failure keep the other attempt's records.
        """
        with self._lock:
            self._buffers[work_id] = _UnitBuffer(span_ids={span_id}, held=[])
            self._owner[span_id] = work_id

    def close_unit(self, work_id: str, outcome: str) -> int:
        """Decide, then release or discard the whole subtree. Returns the number of records kept.

        15:157-159, in order: emitted whole if `outcome != ok` or if the digest selects it, dropped
        whole and counted into `run.events_dropped` otherwise, and **an overflow flushes the unit
        unsampled rather than truncating it**. The overflow branch is checked first because a
        truncated subtree is an orphan wearing a different hat, and 15:158 calls the choice
        *"fail visible"*.
        """
        with self._lock:
            buffer = self._buffers.pop(work_id, None)
            if buffer is None:
                return 0
            for span_id in buffer.span_ids:
                self._owner.pop(span_id, None)
            keep = buffer.overflowed or should_sample(
                outcome, work_id, self._salt, ok_rate=self._ok_rate
            )
            held = tuple(buffer.held)
        if not keep:
            self._stats.dropped += len(held)
            return 0
        for record in held:
            self._forward(record)
        return len(held)

    # -- what a manifest reads --------------------------------------------------------------

    @property
    def stats(self) -> SinkStats:
        """This recorder's own counters. A terminal sink's are its own; the manifest sums them."""
        return self._stats

    @property
    def seq(self) -> int:
        """The last `seq` assigned. Monotone per `(run_id, writer_id)` and never reset."""
        return self._seq

    @property
    def open_units(self) -> int:
        """How many `unit` subtrees are held right now. The multiplicand in 15:170's formula."""
        return len(self._buffers)

    # -- internals --------------------------------------------------------------------------

    def _buffer(self, e: Event) -> bool:
        """Hold `e` if it belongs to an open unit. Returns whether it was held. Caller holds lock.

        `run` and `plan` records are never buffered (15:161) -- *"so the tree always has a spine,
        and a fully sampled-out run still produces a manifest and a `plan` subtree per Stage."*
        Ownership is resolved from `parent_span_id` and inherited: a record whose parent is inside
        the subtree
        registers its own `span_id`, so a `call` three levels down is caught without this class
        walking a chain it has not seen.
        """
        spec = EVENTS[str(e.kind)]
        if spec.span in (SpanLevel.RUN.value, SpanLevel.PLAN.value):
            return False
        work_id = self._owner.get(e.span_id)
        if work_id is None and e.parent_span_id is not None:
            work_id = self._owner.get(e.parent_span_id)
        if work_id is None:
            return False
        buffer = self._buffers[work_id]
        buffer.span_ids.add(e.span_id)
        self._owner[e.span_id] = work_id
        if len(buffer.held) >= MAX_SPAN_BUFFER_EVENTS:
            buffer.overflowed = True
            return False
        buffer.held.append(e)
        return True

    def _forward(self, e: Event) -> None:
        self._stats.emitted += 1
        for sink in self._sinks:
            sink.emit(e)
