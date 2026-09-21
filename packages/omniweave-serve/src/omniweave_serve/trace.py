"""`ow trace export`'s body: read, pair, batch, send, and commit only what is safe to commit.

The three modules under this one each do a job and hold no opinion about the others. `shards.py`
turns bytes into `(Position, Event)`; `otlp.py` turns events into spans; `export.py` turns spans
into requests and requests into a cursor. This one joins them, and joining them turns out to be
where the interesting rule lives.

## A CURSOR CANNOT ADVANCE PAST AN OPEN SPAN

A span is two records. `pair()` needs both, so a drain that has read a `start` and not its `end`
must carry that start into the next drain — and it must not let the cursor past it either, because
a resume from a later offset would read the `end` alone and produce an `orphaned` record that
becomes no span at all. 15:255 makes re-sending harmless and says nothing about this, because it
is about requests and this is about records.

So the committed position is `min(what was read, the earliest still-open span)`, which
`safe_position()` computes and `Step.pinned_by` names.

**And the consequence is severe on a live run.** The `run` span opens with the first record of a
shard and closes with the last, so while a run is in flight the earliest open span is at offset
zero and **the cursor cannot advance at all**. A `--follow` that is killed and restarted re-reads
the run from the beginning. That is *correct* — nothing is lost and every duplicate is one the
collector deduplicates — and it is not what an operator reading 15:256 would expect. D370 is the
entry; `pinned_by` exists so the reason is visible in a report rather than inferred from a cursor
that never moves.

## WHY THE CARRIED STARTS ARE RE-FED RATHER THAN HELD IN A PAIRER

`pair()` is a pure function over a sequence, and the cheapest way to make it incremental is to put
the unterminated starts back at the front of the next sequence. That costs one re-walk of at most
the open-span depth — five levels crossed with the in-flight concurrency, which `SESSION_LIMITS`
and `[serve] max_concurrent_queries` both bound in single digits — and it buys a stateless mapper
that the one-shot and the follow path share unchanged. A stateful `Pairer` would be a second
implementation of the pairing rule, kept in step by nothing.

## WHAT THIS MODULE DOES NOT HOLD, AND WHAT CANNOT REACH IT

No clock, no loop, no sleep: `follow()` is one drain-and-send, and the caller decides whether to go
round again. `--since` arrives as a resolved `ts_wall_ns` rather than a duration string, because
parsing `7d` is an argument-parsing job and the CLI tree that would do it is generated.

**And the CLI cannot import any of this.** `tools/layers.toml` gives `omniweave` the row
`["omniweave_core", "omniweave_ports", "omniweave_office"]`, and `omniweave-serve` is an optional
extra (`serve = [...]` in `[project.optional-dependencies]`), so `ow trace export` and `ow serve`
must reach this distribution the way an `eval` Action reaches `omniweave_conform` — a guarded
import and a named refusal. That refusal has a code for `eval` (`OW-A-027 /
OW_EVAL_NOT_INSTALLED`) and none for `serve`. D369.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from omniweave_serve.export import Halted
from omniweave_serve.otlp import MAX_BATCH_BYTES, MAX_BATCH_SPANS, batches, pair
from omniweave_serve.shards import Position, Tail, shards_for, walk

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from omniweave_core.events import Event

    from omniweave_serve.export import Delivered, Exporter
    from omniweave_serve.otlp import Resource

__all__ = [
    "Carried",
    "Selection",
    "Step",
    "export_once",
    "follow",
    "safe_position",
    "send",
]


@dataclass(frozen=True, slots=True)
class Selection:
    """Which run, and how far back. 15:233's `--run` and `--since`.

    `since_wall_ns` is a resolved instant and not a duration, because `7d` is a string the
    generated CLI parses and this module would otherwise own a grammar nothing else reads.
    `None` is *everything the shards still hold*, which retention has already bounded at
    `[observe] retain_days`.
    """

    live: Path
    since_wall_ns: int | None = None

    def keeps(self, event: Event) -> bool:
        """Whether this record is in the window. Compared on `ts_wall_ns`, because a window is a
        human's question and `ts_mono_ns` is not comparable across processes."""
        return self.since_wall_ns is None or event.ts_wall_ns >= self.since_wall_ns


@dataclass(frozen=True, slots=True)
class Carried:
    """An unterminated `start` held over, and the position it was read at.

    The position is why this is a pair and not just the event: it is what pins the cursor, and
    `Event` carries no idea where it came from.
    """

    position: Position
    event: Event


@dataclass(frozen=True, slots=True)
class Step:
    """One read-pair-send cycle, and everything the caller needs to decide what to do next."""

    result: Delivered | Halted
    safe: Position | None
    """What was committed, or would have been: never past the earliest open span."""

    carried: tuple[Carried, ...] = ()
    """The starts to feed into the next step, front first."""

    orphaned: int = 0
    """Ends whose starts were outside this window. Each is a span that will never exist."""

    pinned_by: str = ""
    """The kind of the earliest open span holding the cursor back, or `""`. D370."""

    continues_at: str | None = None
    """For a follow step, the shard name to open next. `None` while the shard is still live."""

    spans: int = 0
    """How many spans this step produced, which is not how many records it read."""

    def halted(self) -> bool:
        """Whether the export stopped. The caller turns this into an exit code (D363)."""
        return isinstance(self.result, Halted)


def safe_position(
    reached: Position | None, carried: Sequence[Carried], *, order: Sequence[str]
) -> Position | None:
    """The furthest position it is safe to commit: `reached`, or the earliest open span if sooner.

    `order` is the shard sequence, because two positions in different shards are only comparable
    against it — `{run}.0001.ndjson.gz` byte 900 is before `{run}.ndjson` byte 20 and no property
    of either says so. A shard absent from `order` sorts first, which is the conservative way to
    be wrong: it can only hold the cursor back.
    """
    if reached is None and not carried:
        return None
    rank = {name: index for index, name in enumerate(order)}

    def key(position: Position) -> tuple[int, int]:
        return (rank.get(position.shard, -1), position.offset)

    candidates = [held.position for held in carried]
    if reached is not None:
        candidates.append(reached)
    return min(candidates, key=key)


def send(
    exporter: Exporter,
    resource: Resource,
    records: Iterable[tuple[Position, Event]],
    *,
    url: str,
    order: Sequence[str],
    carried: Sequence[Carried] = (),
    cursor: Path | None = None,
    endpoint: str = "",
    run_id: str = "",
    committed: Position | None = None,
    max_spans: int = MAX_BATCH_SPANS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Step:
    """Pair, batch and send one window of records. The core both entry points share.

    The carried starts go in **front** of the new records, which is what makes `pair()` incremental
    without a second implementation of the pairing rule: it is order-sensitive and a start still
    precedes the end it belongs to.
    """
    read = list(records)
    reached = read[-1][0] if read else None
    positions = {(event.trace_id, event.span_id): position for position, event in read}
    for held in carried:
        positions.setdefault((held.event.trace_id, held.event.span_id), held.position)

    stream = [held.event for held in carried] + [event for _, event in read]
    pairing = pair(stream)
    still_open = tuple(
        Carried(position=positions[(event.trace_id, event.span_id)], event=event)
        for event in pairing.unterminated
    )
    safe = safe_position(reached, still_open, order=order)
    pinned = _pinned(safe, still_open)

    plan = batches(pairing.spans, max_spans=max_spans, max_bytes=max_bytes)
    result = exporter.export(
        resource,
        [] if safe is None else [(safe, spans) for spans in plan],
        url=url,
        cursor=cursor,
        endpoint=endpoint,
        run_id=run_id,
        committed=committed,
    )
    return Step(
        result=result,
        safe=safe,
        carried=still_open,
        orphaned=len(pairing.orphaned),
        pinned_by=pinned,
        spans=len(pairing.spans),
    )


def export_once(
    exporter: Exporter,
    resource: Resource,
    selection: Selection,
    *,
    events_dir: Path,
    url: str,
    cursor: Path | None = None,
    endpoint: str = "",
    run_id: str = "",
    resume: Position | None = None,
    max_spans: int = MAX_BATCH_SPANS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Step:
    """One pass over every shard of a run. `ow trace export` without `--follow`."""
    found = shards_for(events_dir, selection.live)
    order = [shard.name for shard in found]
    records = [
        (position, event)
        for position, event in walk(found, resume=resume)
        if selection.keeps(event)
    ]
    return send(
        exporter,
        resource,
        records,
        url=url,
        order=order,
        cursor=cursor,
        endpoint=endpoint,
        run_id=run_id,
        committed=resume,
        max_spans=max_spans,
        max_bytes=max_bytes,
    )


def follow(
    exporter: Exporter,
    resource: Resource,
    tail: Tail,
    selection: Selection,
    *,
    url: str,
    carried: Sequence[Carried] = (),
    cursor: Path | None = None,
    endpoint: str = "",
    run_id: str = "",
    committed: Position | None = None,
    max_spans: int = MAX_BATCH_SPANS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Step:
    """One drain-and-send against a live shard. `ow trace export --follow`, one turn of it.

    Returns without waiting. The caller loops: if `continues_at` is set the shard rolled and the
    next `Tail` opens that name at offset 0; otherwise it waits and calls again. That split is why
    this module holds no sleep and why a roll is testable as a sequence of appends.
    """
    step = send(
        exporter,
        resource,
        [(position, event) for position, event in tail.drain() if selection.keeps(event)],
        url=url,
        order=[tail.position.shard],
        carried=carried,
        cursor=cursor,
        endpoint=endpoint,
        run_id=run_id,
        committed=committed,
        max_spans=max_spans,
        max_bytes=max_bytes,
    )
    return replace(step, continues_at=tail.rolled)


def _pinned(safe: Position | None, carried: Sequence[Carried]) -> str:
    """Which open span is holding the cursor, or `""` when the cursor is at what was read."""
    for held in carried:
        if held.position == safe:
            return held.event.kind
    return ""
