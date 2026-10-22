"""A run's event spine, written to its NDJSON shard: `run.start`, each `unit.failed`, `run.end`.

**D941.** 15-observability.md section 1 makes `Event` *"the only thing a human or a machine
reads"*, and `omniweave_core.events` has carried the closed vocabulary, `NdjsonSink` and
`RunRecorder` since P4. Nothing in `ow add` or `ow ingest` constructed either, so a run wrote no
event at all and `[observe] ndjson_path` named a file that never existed. This is the first
writer: the run's own span and the failures a reader would look for first.

## Rulings

1. **Only a run with a project writes a shard.** `[observe] ndjson_path` is relative,
   `.omniweave/events/{run_id}.ndjson`, and it resolves against the project root
   (`config.project_root`). A library caller that names no project gets `None` and the run is
   unchanged; so does a project whose `[observe] sinks` leaves out `ndjson`.
2. **The run's span is the root.** One `trace_id` and one `span_id` per run, from `os.urandom`
   (15:357's 16 and 8 bytes, hex), `parent_span_id = None` on `run.start` and `run.end` alone.
   Each `unit.failed` is a point record parented on the run span, because no `unit` span is
   opened yet; the tail-sampling bracket that would open one is the recorder's, unused here.
3. **A failure's message is the stored one**, `work.failure_message`, which both Driver hosts have
   already redacted (D934), and the stream's per-kind allowlist keeps every other key out.
4. **Telemetry never fails a run** (15:47). A shard that cannot be written is the sink's to count;
   `close()` waits a bounded time for the writer thread and returns what it could not write.

Specified in 15-observability.md sections 1-3 and 8.1.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.config import project_root
from omniweave_core.events import (
    SPAN_ID_HEX_LEN,
    TRACE_ID_HEX_LEN,
    Event,
    EventKind,
    Level,
    NdjsonSink,
    RunRecorder,
    writer_id,
)
from omniweave_core.identity import canonical_uri
from omniweave_core.redact import normalized, path_token, redact

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.clock import Clock
    from omniweave_core.config import Config
    from omniweave_core.events import Scalar

__all__ = [
    "CLOSE_TIMEOUT_MS",
    "PATHS_FILE_MODE",
    "PATHS_MODE",
    "PathRedaction",
    "RunTrace",
    "shard_of",
]

CLOSE_TIMEOUT_MS: Final = 5_000
"""Ruling 4: how long `close()` waits for the writer thread to drain."""

_NDJSON: Final = "ndjson"
_HOME_VAR: Final = "$OMNIWEAVE_HOME"


def shard_of(config: Config, run_id: str, *, env: Mapping[str, str] | None = None) -> Path | None:
    """Ruling 1: where this run's live shard is, or `None` when the run writes none.

    15:1729's shared-service form is `$OMNIWEAVE_HOME/events/{run_id}.ndjson`, so that one variable
    is expanded from the run's declared `env` and the result is absolute. A path naming it when the
    environment does not is no shard, rather than a directory called `$OMNIWEAVE_HOME`.
    """
    root = project_root(config)
    if root is None or _NDJSON not in tuple(config.get("observe.sinks")):  # type: ignore[arg-type]
        return None
    text = str(config.get("observe.ndjson_path")).format(run_id=run_id)
    if _HOME_VAR in text:
        home = (env or {}).get(_HOME_VAR.removeprefix("$"))
        if not home:
            return None
        text = text.replace(_HOME_VAR, home)
    path = Path(text)
    return path if path.is_absolute() else root / path


PATHS_MODE: Final = "paths"
PATHS_FILE_MODE: Final = 0o600
"""15:1330: `{run_id}.paths.json` is mode 0600, and it is not in the event stream."""


@dataclass(slots=True)
class PathRedaction:
    """Ruling 5: `[observe] redact = "paths"` for one run. D943.

    15:1330: the `unit` a record names becomes `u:` + `blake2b(unit_uri || run_salt)[:12]`
    (`redact.path_token`), and a message passes `redact()` in mode `"paths"` against the run's
    `[roots]`, so a path in it becomes the same token. The token -> path mapping is written to
    `{output_root}/runs/{run_id}.paths.json`, mode 0600, beside the manifest and never in the
    stream; the salt is the run's own and is written nowhere.

    The roots are held in `canonical_uri`'s form, because that is the form a `unit_uri` and a
    driver's message take: resolved through symlinks and case-folded where the platform folds.
    A root given as macOS's `/var/...` would otherwise miss every unit under `/private/var/...`,
    and those paths would fall to rule 2's `<redacted:{n}chars>` with no token in the map.
    """

    salt: bytes
    roots: tuple[str, ...]
    out: Path
    seen: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(
        cls, config: Config, *, run_id: str, roots: Sequence[Path], output_root: Path | None
    ) -> PathRedaction | None:
        if str(config.get("observe.redact")) != PATHS_MODE or output_root is None:
            return None
        return cls(
            salt=os.urandom(16),
            roots=tuple(canonical_uri(root) for root in roots),
            out=output_root / "runs" / f"{run_id}.paths.json",
        )

    def unit(self, uri: str) -> str:
        token = path_token(uri, salt=self.salt)
        self.seen[token] = normalized(uri)
        return token

    def text(self, message: str) -> str:
        return redact(message, mode=PATHS_MODE, salt=self.salt, roots=self.roots, seen=self.seen)[0]

    def write(self) -> None:
        """The mapping, sorted, created at mode 0600 rather than chmodded after."""
        self.out.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(dict(sorted(self.seen.items())), indent=2, sort_keys=True) + "\n"
        fd = os.open(self.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PATHS_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)


class RunTrace:
    """One run's recorder over its NDJSON shard, and the run span every record hangs from."""

    __slots__ = ("_closed", "_recorder", "_redaction", "_sink", "_span", "_trace", "path")

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        writer: str,
        clock: Clock,
        level: Level,
        shard_bytes: int,
        redaction: PathRedaction | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._sink = NdjsonSink(path, clock=clock, shard_bytes=shard_bytes)
        self._recorder = RunRecorder(
            run_id=run_id, writer=writer, clock=clock, sinks=(self._sink,), level=level
        )
        self._trace = os.urandom(TRACE_ID_HEX_LEN // 2).hex()
        self._span = os.urandom(SPAN_ID_HEX_LEN // 2).hex()
        self._closed = False
        self._redaction = redaction

    @classmethod
    def open(
        cls,
        config: Config,
        *,
        run_id: str,
        worker: str,
        clock: Clock,
        env: Mapping[str, str] | None = None,
        roots: Sequence[Path] = (),
        output_root: Path | None = None,
    ) -> RunTrace | None:
        """Ruling 1. `worker` is `supervisor.worker_identity()`, `host:pid:create_time`. Ruling 5:
        `roots` and `output_root` are the run's `[roots]`, which `redact = "paths"` reads."""
        path = shard_of(config, run_id, env=env)
        if path is None:
            return None
        host, pid, created = worker.rsplit(":", 2)
        return cls(
            path,
            run_id=run_id,
            writer=writer_id(host, int(pid), created),
            clock=clock,
            level=Level(str(config.get("observe.level"))),
            shard_bytes=int(config.get("observe.shard_bytes")),  # type: ignore[arg-type]
            redaction=PathRedaction.of(config, run_id=run_id, roots=roots, output_root=output_root),
        )

    def _emit(
        self,
        kind: EventKind,
        phase: str,
        *,
        fields: dict[str, Scalar],
        root: bool = False,
        unit: str | None = None,
        driver: str | None = None,
    ) -> None:

        self._recorder.emit(
            Event(
                ts_wall_ns=0,
                ts_mono_ns=0,
                run_id="",
                writer_id="",
                seq=0,
                trace_id=self._trace,
                span_id=self._span if root else os.urandom(SPAN_ID_HEX_LEN // 2).hex(),
                parent_span_id=None if root else self._span,
                kind=kind,
                phase=phase,  # type: ignore[arg-type]
                level="info",  # the recorder stamps the kind's own level
                unit=unit,
                driver=driver,
                fields=fields,
            )
        )

    def start(
        self,
        *,
        trigger: str,
        argv_digest: str,
        config_digest: str,
        semantic_digest: str,
        generation: int,
    ) -> None:
        """`run.start`, the run span's opening record."""
        self._emit(
            EventKind.RUN_START,
            "start",
            root=True,
            fields={
                "trigger": trigger,
                "argv_digest": argv_digest,
                "config_digest": config_digest,
                "semantic_digest": semantic_digest,
                "generation": generation,
            },
        )

    def failed(self, failures: Iterable[tuple[str, str | None, str, str]]) -> int:
        """One `unit.failed` per `(unit, driver, failure_class, message)`. Returns the count."""
        count = 0
        redaction = self._redaction
        for unit, driver, failure_class, message in failures:
            self._emit(
                EventKind.UNIT_FAILED,
                "point",
                unit=unit if redaction is None else redaction.unit(unit),
                driver=driver,
                fields={
                    "failure_class": failure_class,
                    "message": message if redaction is None else redaction.text(message),
                },
            )
            count += 1
        return count

    def end(self, *, status: str, units: int, failures: int, micros: int) -> None:
        """`run.end`, closing the run span, with what the recorder and the sink dropped."""
        dropped = self._recorder.stats.dropped + self._sink.stats.dropped
        self._emit(
            EventKind.RUN_END,
            "end",
            root=True,
            fields={
                "status": status,
                "units": units,
                "failures": failures,
                "micros": micros,
                "events_dropped": dropped,
            },
        )

    def close(self) -> int:
        """Ruling 4: drain and stop the writer thread. Returns the records it could not write."""
        if self._closed:
            return 0
        self._closed = True
        if self._redaction is not None:
            self._redaction.write()
        return self._sink.close(timeout_ms=CLOSE_TIMEOUT_MS)
