"""`ow trace export` and `ow trace stat`: a run's event shards, sent or counted. D947-D949.

15-observability.md:233 prints the verb and section 2.6 its mapping. The reader, the pairer and
the payload builder live in `omniweave-serve` beside the OTLP code (02-architecture.md row 40),
which `omniweave` may not import, so the work happens across an entry point,
`omniweave.surface.dispatch.trace_entry()`. This module parses, resolves the run's shard from
`[observe] ndjson_path`, calls the verb with builtin values, and prints. D369 recorded the gap
this closes: every part was built, and no command reached them.

## Rulings

1. **`--run` is required.** 15:233 offers `--run` or `--since`; `--since` is not served, so a run
   is the only selection, and none is refused naming the flag.
2. **One destination: `--file P`, `--otlp E`, or `--dry-run`.** `--file` writes the requests, one
   per line (`omniweave_serve.entry`'s ruling 1), and `P` is relative to the working directory.
   `--otlp` sends them to `E/v1/traces` (D948). `--dry-run` writes and sends nothing and reports
   the counts, and `--print-payload`, which needs it, prints each request body on its own line, as
   15:2024 has it. `--dry-run` beside `--otlp` is the rehearsal of that send; beside `--file` it is
   refused, because a file is the rehearsal already. With no destination at all, `[observe]
   otlp_endpoint` is the collector, which 15:260 makes this verb's alone; empty, it is refused.
3. **A run with no shard is `NotFoundError`, exit 2**, naming the path `[observe] ndjson_path`
   resolved to, and so is a project with no `ndjson` sink. Nothing is written or sent for it.
4. **`--render json` prints one object** with the report's fields; under `--print-payload` the
   bodies print first and the object after. `--render jsonl|rows` has no writer and is refused.
5. **Without `omniweave-serve` the verb is `CapabilityMissing`, exit 64**, from `trace_entry()`.
6. **A send that stops is `ResourceLimit`, exit 1** (D948). 15:255: the export *"stops and exits
   non-zero naming the last shard offset it committed"*, and `Halted.message()` names it. D363
   left the code unallocated and pointed at `ResourceLimit`'s shape, a refusal that names a knob,
   here `[observe] otlp_endpoint`; it carries that class's own symbol rather than one minted
   here. The endpoint itself is never printed: an operator's URL may carry a credential.
7. **`ow trace stat` reads, and writes nothing** (D949). With `--run`, that run's shards, which
   must exist as ruling 3 says; without it, every run's in the events directory `[observe]
   ndjson_path` resolves to, and a directory holding none is a report of zero runs, not a
   refusal. The text form is a line per shard with its deflate ratio, one of kinds, a line
   per span name with its wall, and the dropped total; `--render json` is the report.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import (
    InternalError,
    NotFoundError,
    OwError,
    ResourceLimit,
    UsageError,
)

from omniweave.run.trace import shard_of
from omniweave.sdk.reports import (
    TraceExportReport,
    TraceKindRow,
    TraceShardRow,
    TraceSpanRow,
    TraceStatReport,
)
from omniweave.surface.dispatch import trace_entry
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.config import Config

__all__ = ["TRACE_WORD", "main"]

TRACE_WORD: Final[str] = "trace"
_EXPORT_FIX: Final[str] = (
    "ow trace export --run RUN_ID (--file PATH | --otlp URL | --dry-run [--print-payload])"
)
_ENDPOINT_KEY: Final[str] = "observe.otlp_endpoint"
_LIVE_SUFFIX: Final[str] = ".ndjson"
_ROLLED_GLOB: Final[str] = ".*.ndjson.gz"
_PROBE_RUN: Final[str] = "r_0"
"""A run id to resolve `[observe] ndjson_path` with when no run is named, for its directory."""
_NS_PER_MS: Final[int] = 1_000_000


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow trace ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(TRACE_WORD, parsed)
        verb = _stat if parsed.ow_action == "trace.stat" else _export
        return verb(parsed, cwd=cwd, env=env, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _refuse_usage(parsed: argparse.Namespace) -> None:
    """Rulings 1, 2 and 4, before anything is read."""
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow trace export",
            fix=_EXPORT_FIX,
        )
    if not parsed.run:
        raise UsageError("ow trace export needs --run: --since is not served", fix=_EXPORT_FIX)
    if parsed.file is not None and parsed.otlp is not None:
        raise UsageError("ow trace export takes one destination, --file or --otlp", fix=_EXPORT_FIX)
    if parsed.file is not None and parsed.dry_run:
        raise UsageError(
            "ow trace export takes --file or --dry-run, one of the two", fix=_EXPORT_FIX
        )
    if parsed.print_payload and not parsed.dry_run:
        raise UsageError("--print-payload prints what --dry-run would send", fix=_EXPORT_FIX)


def _endpoint(parsed: argparse.Namespace, config: Config) -> str | None:
    """Ruling 2: `--otlp`, else `[observe] otlp_endpoint` when nothing else was chosen."""
    if parsed.otlp is not None:
        return str(parsed.otlp)
    if parsed.file is not None or parsed.dry_run:
        return None
    configured = str(config.get(_ENDPOINT_KEY) or "")
    if not configured:
        raise UsageError(
            "ow trace export takes --file, --otlp or --dry-run, and [observe] otlp_endpoint is "
            "empty",
            fix=_EXPORT_FIX,
        )
    return configured


def _export(
    parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO
) -> int:
    _refuse_usage(parsed)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    endpoint = _endpoint(parsed, config)
    live = _run_shard(config, parsed.run, env=env)
    target = None if parsed.file is None else cwd / parsed.file
    sending = endpoint is not None and not parsed.dry_run
    done = _report(
        parsed.run,
        trace_entry("export")(
            live=str(live),
            config_digest=config.config_digest,
            file=None if target is None else str(target),
            max_batch=parsed.max_batch,
            endpoint=endpoint if sending else None,
            run_id=parsed.run,
        ),
    )
    if done.halted:
        raise ResourceLimit(
            done.halted,
            limit=_ENDPOINT_KEY,
            fix=(
                f"run ow trace export --run {parsed.run} again once the collector answers; it "
                "resumes at the committed offset"
            ),
        )
    if parsed.print_payload:
        for body in done.payloads:
            stdout.write(body + "\n")
    if parsed.render == "json":
        row = asdict(done)
        row["payloads"] = len(done.payloads)
        stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif not parsed.print_payload:
        stdout.write(_line(done, file=parsed.file, sent=sending) + "\n")
    return 0


def _report(run_id: str, result: Mapping[str, object]) -> TraceExportReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    shards, payloads = result.get("shards"), result.get("payloads")
    #  The run's counts are always returned; the send's only when there was a send.
    counts = {
        **{key: result.get(key) for key in ("spans", "batches", "points", "unterminated")},
        "orphaned": result.get("orphaned"),
        **{key: result.get(key, 0) for key in ("sent_requests", "sent_spans")},
    }
    written, halted = result.get("file"), result.get("halted", "")
    if not (
        isinstance(shards, list)
        and isinstance(payloads, list)
        and isinstance(written, str)
        and isinstance(halted, str)
        and all(isinstance(value, int) for value in counts.values())
    ):
        raise InternalError(
            "the [omniweave.trace] export entry point returned an unreadable report",
            fix="pip install --force-reinstall omniweave-serve",
        )
    number = {key: int(value) for key, value in counts.items()}  # type: ignore[call-overload]
    return TraceExportReport(
        run_id=run_id,
        shards=tuple(str(name) for name in shards),
        spans=number["spans"],
        batches=number["batches"],
        points=number["points"],
        unterminated=number["unterminated"],
        orphaned=number["orphaned"],
        file=written,
        payloads=tuple(str(body) for body in payloads),
        sent_requests=number["sent_requests"],
        sent_spans=number["sent_spans"],
        halted=halted,
    )


def _line(done: TraceExportReport, *, file: str | None, sent: bool) -> str:
    """One verdict line, with what was read and not written named rather than dropped."""
    if sent:
        where = f"sent {done.sent_requests} request(s), {done.sent_spans} span(s), to the collector"
    elif file is not None:
        where = f"wrote {file}"
    else:
        where = "dry run, nothing written or sent"
    held = [
        f"{count} {label}"
        for count, label in (
            (done.points, "point record(s)"),
            (done.unterminated, "unterminated span(s)"),
            (done.orphaned, "orphaned end(s)"),
        )
        if count
    ]
    rest = f"; not exported: {', '.join(held)}" if held else ""
    return (
        f"run {done.run_id}: {done.spans} span(s) in {done.batches} request(s) from "
        f"{len(done.shards)} shard(s), {where}{rest}"
    )


def _shard_path(config: Config, run: str, *, env: Mapping[str, str]) -> Path:
    """Where `run`'s live shard would be, or ruling 3's refusal when no project writes one."""
    live = shard_of(config, run, env=env)
    if live is None:
        raise NotFoundError(
            f"run {run} has no event shard: no project is in view, or [observe] sinks leaves out "
            "ndjson",
            fix="run ow trace from the project the run belongs to",
        )
    return live


def _run_shard(config: Config, run: str, *, env: Mapping[str, str]) -> Path:
    """Ruling 3: the run's live shard path, which it or a rolled sibling must exist at."""
    live = _shard_path(config, run, env=env)
    stem = live.name.removesuffix(_LIVE_SUFFIX)
    if not (live.is_file() or any(live.parent.glob(stem + _ROLLED_GLOB))):
        raise NotFoundError(
            f"run {run} has no event shard at {live.as_posix()}",
            fix="check the run id against ow cost or the run manifests",
        )
    return live


def _stat(parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO) -> int:
    """Ruling 7."""
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow trace stat",
            fix="ow trace stat [--run RUN_ID] [--render json]",
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    if parsed.run:
        live: Path | None = _run_shard(config, parsed.run, env=env)
        events_dir = live.parent
    else:
        live = None
        events_dir = _shard_path(config, _PROBE_RUN, env=env).parent
    done = _stat_report(trace_entry("stat")(events_dir=str(events_dir), live=_or_none(live)))
    if parsed.render == "json":
        stdout.write(json.dumps(asdict(done), ensure_ascii=False) + "\n")
    else:
        for line in _stat_lines(done):
            stdout.write(line + "\n")
    return 0


def _or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _stat_report(result: Mapping[str, object]) -> TraceStatReport:
    """The `stat` entry point's builtins as this side's report; else a broken install."""
    runs, shards, kinds, spans = (result.get(key) for key in ("runs", "shards", "kinds", "spans"))
    dropped = result.get("dropped")
    broken = InternalError(
        "the [omniweave.trace] stat entry point returned an unreadable report",
        fix="pip install --force-reinstall omniweave-serve",
    )
    if not (
        isinstance(runs, list)
        and isinstance(shards, list)
        and isinstance(kinds, list)
        and isinstance(spans, list)
        and isinstance(dropped, int)
    ):
        raise broken
    try:
        return TraceStatReport(
            runs=tuple(str(run) for run in runs),
            shards=tuple(
                TraceShardRow(
                    name=str(row["name"]),
                    records=int(row["records"]),
                    bytes=int(row["bytes"]),
                    uncompressed_bytes=int(row["uncompressed_bytes"]),
                )
                for row in shards
            ),
            kinds=tuple(TraceKindRow(kind=str(kind), records=int(n)) for kind, n in kinds),
            spans=tuple(
                TraceSpanRow(name=str(name), spans=int(n), total_ns=int(ns))
                for name, n, ns in spans
            ),
            dropped=dropped,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise broken from error


def _stat_lines(done: TraceStatReport) -> list[str]:
    """Ruling 7's text form."""
    lines = [f"ow trace stat  {len(done.runs)} run(s), {len(done.shards)} shard(s)"]
    for shard in done.shards:
        ratio = shard.uncompressed_bytes / shard.bytes if shard.bytes else 0.0
        lines.append(
            f"  shard   {shard.name}  {shard.records} record(s), {shard.bytes} bytes on disk, "
            f"{shard.uncompressed_bytes} uncompressed, ratio {ratio:.2f}"
        )
    if done.kinds:
        shown = ", ".join(f"{row.kind} {row.records}" for row in done.kinds)
        lines.append(f"  kinds   {shown}")
    for span in done.spans:
        lines.append(
            f"  span    {span.name}  {span.spans} span(s), {span.total_ns // _NS_PER_MS} ms"
        )
    lines.append(f"  dropped {done.dropped} record(s)")
    return lines
