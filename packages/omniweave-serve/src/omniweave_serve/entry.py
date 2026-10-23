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

Specified in 15-observability.md section 2.6 (:213-262).
"""

from __future__ import annotations

import time
from pathlib import Path

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
from omniweave_serve.shards import shards_for, walk
from omniweave_serve.trace import Selection, export_once

__all__ = ["export"]


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
