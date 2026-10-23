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
4. **No cursor.** A file or a rehearsal is a whole-run snapshot. 15:255's cursor belongs to the
   `--otlp` path, where a resume matters.

Specified in 15-observability.md section 2.6 (:213-262).
"""

from __future__ import annotations

from pathlib import Path

from omniweave_serve.export import _replace, payload
from omniweave_serve.otlp import MAX_BATCH_BYTES, Resource, batches, pair
from omniweave_serve.shards import shards_for, walk
from omniweave_serve.trace import Selection

__all__ = ["export"]


def export(
    *,
    live: str,
    config_digest: str,
    file: str | None,
    max_batch: int,
    since_wall_ns: int | None = None,
) -> dict[str, object]:
    """`ow trace export --file P` or `--dry-run --print-payload`, over one run's shards.

    `live` is the run's resolved live shard path, which the CLI computes from `[observe]
    ndjson_path` (`omniweave.run.trace.shard_of`); its rolled siblings are found beside it.
    `file` is an absolute path to write (ruling 1), or `None` to return the bodies (ruling 2).
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
    return {
        "shards": [one.name for one in found],
        "spans": len(pairing.spans),
        "batches": len(bodies),
        "points": len(pairing.points),
        "unterminated": len(pairing.unterminated),
        "orphaned": len(pairing.orphaned),
        "file": "" if file is None else file,
        "payloads": [] if file is not None else bodies,
    }
