"""The `omniweave.trace` entry points: what `ow trace <verb>` calls in this distribution. **D947.**

15-observability.md:233 prints `ow trace export`, and 02-architecture.md row 40 puts it in this
distribution's `otlp.py`. `omniweave` may not import this package (`tools/layers.toml`), so
`omniweave.surface.dispatch.trace_entry()` loads each function here by its entry-point name at call
time, as `eval_entry()` loads `omniweave-conform`'s (D833). That closes D369's gap: the reader,
the pairer, the batcher and the payload builder were here, and no command reached them.

**Only builtin values cross**, as across `ow serve`'s and `ow eval`'s boundaries: arguments are
`str`, `int`, `bool` and `None`, and the result is a `dict` of `str`, `int` and lists of `str`.

## Rulings

1. **`--file` holds one `ExportTraceServiceRequest` per line**, each the exact body `--otlp` would
   `POST`, built by `export.payload()`, the one builder. 15:233 names the flag and says nothing of
   the layout. This is the layout the OpenTelemetry Collector's file exporter writes and its
   `otlpjsonfile` receiver reads, so the file can be replayed into a collector with no code of
   ours. It is written atomically, and a run with no spans writes an empty file.
2. **`--dry-run --print-payload` returns the same bodies and writes nothing.** They are
   `Exporter.rehearse()`'s, with no exporter, because nothing here dials.
3. **Spans only, as the send path.** A point record is counted in `points` and not written: the
   `--otlp` path sends `ExportTraceServiceRequest`s only, and a file that held more than a send
   would not be "what would be sent". An unterminated `start` or an orphaned `end` is counted and
   named, never dropped silently (`otlp.Pairing`, D357).
4. **No cursor for a file.** A file or a rehearsal is a whole-run snapshot. 15:255's cursor
   belongs to the `--otlp` path, where a resume matters.
5. **`--otlp` sends through `trace.export_once()`, from the committed cursor.** D948. The transport
   is `export.UrllibTransport`, the one thing in this distribution that dials, and the ladder's
   waits are real seconds (`time.sleep`, injected here as the composition root, as
   `omniweave.install` injects it). The run's counts come from one pairing of the whole run; what
   was sent comes from the `Delivered` or `Halted` the export returns, and a `Halted` is returned
   as its `message()`, never raised, for the CLI to turn into its exit (D363).

## `stat`, D949

15:236: `ow trace stat [--run <run_id>]  # per-kind counts, per-Stage wall, dropped, shard bytes`,
and 15:432 asks it for the observed deflate ratio per shard, so the charter's ~8.7x stops being
an assumption. `stat()` reads every shard of the run, or of every run in the events directory,
once and in place:
- per shard, its records, its bytes on disk and its uncompressed bytes, whose quotient is the
  ratio (1.0 for the live shard, which is never deflated);
- per kind, its records;
- per span name, its count and total wall time. A `plan/<stage>` name is a Stage, so this is
  15:236's per-Stage wall, and every other level comes with it. A duration is `Span`'s own,
  the monotonic delta when the wall clock stepped;
- the run's dropped records, which `run.end` carries as `events_dropped`.

The reader's own wall time per shard, 15:2165's closing condition, is not here: this module
reads no clock, and a figure from the caller's clock would time the whole call, not a shard.

Specified in 15-observability.md section 2.6 (:213-262).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave_serve.export import (
    Exporter,
    Halted,
    UrllibTransport,
    _replace,
    cursor_path,
    payload,
    read_cursor,
    traces_url,
)
from omniweave_serve.otlp import MAX_BATCH_BYTES, Resource, batches, pair
from omniweave_serve.shards import GZ_SUFFIX, LIVE_SUFFIX, Shard, read_shard, shards_for, walk
from omniweave_serve.trace import Selection, export_once

if TYPE_CHECKING:
    from omniweave_core.events import Event

__all__ = ["export", "stat"]


def export(
    *,
    live: str,
    config_digest: str,
    file: str | None,
    max_batch: int,
    since_wall_ns: int | None = None,
    endpoint: str | None = None,
    run_id: str = "",
) -> dict[str, object]:
    """`ow trace export --file P`, `--otlp E` or `--dry-run --print-payload`, over one run.

    `live` is the run's resolved live shard path, which the CLI computes from `[observe]
    ndjson_path` (`omniweave.run.trace.shard_of`); its rolled siblings are found beside it.
    `file` is an absolute path to write (ruling 1), or `None` to return the bodies (ruling 2).
    `endpoint` sends instead (ruling 5), keyed in the cursor by `run_id`; it and `file` are
    exclusive.
    """
    shard = Path(live)
    selection = Selection(live=shard, since_wall_ns=since_wall_ns)
    found = shards_for(shard.parent, shard)
    pairing = pair(event for _, event in walk(found) if selection.keeps(event))
    resource = Resource(config_digest=config_digest)
    bodies = [
        payload(resource, spans).decode("utf-8")
        for spans in batches(pairing.spans, max_spans=max_batch, max_bytes=MAX_BATCH_BYTES)
    ]
    if file is not None:
        _replace(Path(file), "".join(body + "\n" for body in bodies))
    sent = _send(resource, selection, endpoint, run_id, max_batch) if endpoint else {}
    return {
        "shards": [one.name for one in found],
        "spans": len(pairing.spans),
        "batches": len(bodies),
        "points": len(pairing.points),
        "unterminated": len(pairing.unterminated),
        "orphaned": len(pairing.orphaned),
        "file": "" if file is None else file,
        "payloads": [] if file is not None or endpoint else bodies,
        **sent,
    }


def _send(
    resource: Resource, selection: Selection, endpoint: str, run_id: str, max_batch: int
) -> dict[str, object]:
    """Ruling 5: one pass from the committed cursor, as builtins."""
    events_dir = selection.live.parent
    cursor = cursor_path(events_dir)
    step = export_once(
        Exporter(transport=UrllibTransport(), sleep=time.sleep),
        resource,
        selection,
        events_dir=events_dir,
        url=traces_url(endpoint),
        cursor=cursor,
        endpoint=endpoint,
        run_id=run_id,
        resume=read_cursor(cursor, endpoint=endpoint, run_id=run_id),
        max_spans=max_batch,
    )
    done = step.result
    return {
        "sent_requests": done.requests,
        "sent_spans": done.spans,
        "halted": done.message() if isinstance(done, Halted) else "",
        "pinned_by": step.pinned_by,
    }


def stat(*, events_dir: str, live: str | None) -> dict[str, object]:
    """`ow trace stat [--run R]`: one run's shards when `live` names its live shard, else every
    run's in `events_dir`. Builtins out, as `export()`'s."""
    root = Path(events_dir)
    runs = (
        [Path(live)] if live is not None else [root / (stem + LIVE_SUFFIX) for stem in _stems(root)]
    )
    shards: list[dict[str, object]] = []
    kinds: dict[str, int] = {}
    spans: dict[str, list[int]] = {}
    dropped = 0
    for run in runs:
        found = shards_for(run.parent, run)
        records: list[Event] = []
        for shard in found:
            row, events = _read(shard)
            shards.append(row)
            records.extend(events)
        pairing = pair(records)
        for event in records:
            kinds[event.kind] = kinds.get(event.kind, 0) + 1
            if event.kind == "run.end":
                value = event.fields.get("events_dropped", 0)
                dropped += value if isinstance(value, int) else 0
        for span in pairing.spans:
            total = spans.setdefault(span.name, [0, 0])
            total[0] += 1
            total[1] += span.end_wall_ns - span.start_wall_ns
    return {
        "runs": [run.name.removesuffix(LIVE_SUFFIX) for run in runs],
        "shards": shards,
        "kinds": [[kind, kinds[kind]] for kind in sorted(kinds)],
        "spans": [[name, spans[name][0], spans[name][1]] for name in sorted(spans)],
        "dropped": dropped,
    }


def _stems(root: Path) -> list[str]:
    """Every run with a live or a rolled shard in `root`, by its live shard's stem, sorted."""
    try:
        names = [entry.name for entry in root.iterdir() if entry.is_file()]
    except OSError:
        return []
    stems = {name.removesuffix(LIVE_SUFFIX) for name in names if name.endswith(LIVE_SUFFIX)}
    for name in names:
        if name.endswith(GZ_SUFFIX):
            stem, _, _ordinal = name.removesuffix(GZ_SUFFIX).rpartition(".")
            if stem:
                stems.add(stem)
    return sorted(stems)


def _read(shard: Shard) -> tuple[dict[str, object], list[Event]]:
    """One shard's row and its records. The last position is its uncompressed size."""
    events: list[Event] = []
    uncompressed = 0
    for position, event in read_shard(shard):
        events.append(event)
        uncompressed = position.offset
    on_disk = shard.path.stat().st_size
    return (
        {
            "name": shard.name,
            "records": len(events),
            "bytes": on_disk,
            "uncompressed_bytes": uncompressed,
        },
        events,
    )
