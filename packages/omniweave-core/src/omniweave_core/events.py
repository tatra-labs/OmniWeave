"""The closed event vocabulary, the five-deep span model, and the record they share.

`Event` is the only thing a human or a machine reads (15-observability.md:1268: *"omniweave has no
logger hierarchy, no `logging.getLogger(__name__)` tree and no per-module level configuration.
Everything a human or a machine reads is an `Event`."*). This module is the half of W4.8 that
**decides nothing at run time**: a vocabulary, a span hierarchy, a record, a `Protocol`, and four
pure functions. `NdjsonSink` and `ConsoleSink` -- the half with a thread, a file handle and a
bounded queue -- are the same cell's second half and are not here.

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

* **The sinks.** `NdjsonSink`, `ConsoleSink`, the 64k drop-oldest queue, `seq` under the sink's own
  lock, the 64 MiB shard roll and the writer thread are W4.8's second half. `TraceSink` is a
  `Protocol` here and nothing implements it, which is what keeps this module free of a thread.
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

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Protocol, runtime_checkable

from omniweave_core.errors import ConfigError

# `Mapping` is imported at run time and not under `TYPE_CHECKING`: `tools/schemagen.py` resolves
# this module's annotations with `typing.get_type_hints()` to emit `schema/event-v1.json`, and a
# name that exists only for a type checker is a `NameError` there. G6 is the check that would
# otherwise fail, on the day the schema goes live rather than on the day the import moved.

__all__ = [
    "EVENTS",
    "EVENTS_DROPPED_DEGRADATION",
    "EVENT_ORDER",
    "LEVEL_ORDER",
    "NON_OK_SAMPLE_RATE",
    "OK_SAMPLE_RATE",
    "SEVERITY_NUMBER",
    "SPAN_ATTRIBUTES",
    "SPAN_ID_HEX_LEN",
    "SPAN_PARENT",
    "STAGE_ATTRIBUTE",
    "STAGE_MS_KEYS",
    "TRACEPARENT_RE",
    "TRACE_FLAGS_SAMPLED",
    "TRACE_ID_HEX_LEN",
    "Event",
    "EventKind",
    "EventSpec",
    "Level",
    "Phase",
    "SpanLevel",
    "Stage",
    "TraceSink",
    "is_span_kind",
    "kinds_at",
    "sample_key",
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
