"""`ow trace export`: one run's spans as OTLP JSON, to a file or printed. D947.

15-observability.md:233 prints the verb and section 2.6 its mapping. The reader, the pairer and
the payload builder live in `omniweave-serve` beside the OTLP code (02-architecture.md row 40),
which `omniweave` may not import, so the work happens across an entry point,
`omniweave.surface.dispatch.trace_entry()`. This module parses, resolves the run's shard from
`[observe] ndjson_path`, calls the verb with builtin values, and prints. D369 recorded the gap
this closes: every part was built, and no command reached them.

## Rulings

1. **`--run` is required.** 15:233 offers `--run` or `--since`; `--since` is not served, so a run
   is the only selection, and none is refused naming the flag.
2. **`--file P` or `--dry-run`, never both, never neither.** `--file` writes the requests, one per
   line (`omniweave_serve.entry`'s ruling 1); `--dry-run` writes nothing and reports the counts,
   and `--print-payload`, which needs `--dry-run`, prints each request body on its own line, as
   15:2024 has it. `P` is relative to the working directory.
3. **A run with no shard is `NotFoundError`, exit 2**, naming the path `[observe] ndjson_path`
   resolved to, and so is a project with no `ndjson` sink. Nothing is written for it.
4. **`--render json` prints one object** with the report's fields; under `--print-payload` the
   bodies print first and the object after. `--render jsonl|rows` has no writer and is refused.
5. **Without `omniweave-serve` the verb is `CapabilityMissing`, exit 64**, from `trace_entry()`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import InternalError, NotFoundError, OwError, UsageError

from omniweave.run.trace import shard_of
from omniweave.sdk.reports import TraceExportReport
from omniweave.surface.dispatch import trace_entry
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

__all__ = ["TRACE_WORD", "main"]

TRACE_WORD: Final[str] = "trace"
_EXPORT_FIX: Final[str] = "ow trace export --run RUN_ID (--file PATH | --dry-run [--print-payload])"
_LIVE_SUFFIX: Final[str] = ".ndjson"
_ROLLED_GLOB: Final[str] = ".*.ndjson.gz"


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow trace ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(TRACE_WORD, parsed)
        return _export(parsed, cwd=cwd, env=env, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _export(
    parsed: argparse.Namespace, *, cwd: Path, env: Mapping[str, str], stdout: TextIO
) -> int:
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow trace export",
            fix=_EXPORT_FIX,
        )
    if not parsed.run:
        raise UsageError("ow trace export needs --run: --since is not served", fix=_EXPORT_FIX)
    if (parsed.file is None) == (not parsed.dry_run):
        raise UsageError(
            "ow trace export takes --file or --dry-run, one of the two", fix=_EXPORT_FIX
        )
    if parsed.print_payload and not parsed.dry_run:
        raise UsageError("--print-payload prints what --dry-run would send", fix=_EXPORT_FIX)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    live = shard_of(config, parsed.run, env=env)
    if live is None:
        raise NotFoundError(
            f"run {parsed.run} has no event shard: no project is in view, or [observe] sinks "
            f"leaves out ndjson",
            fix="run ow trace export from the project the run belongs to",
        )
    stem = live.name.removesuffix(_LIVE_SUFFIX)
    if not (live.is_file() or any(live.parent.glob(stem + _ROLLED_GLOB))):
        raise NotFoundError(
            f"run {parsed.run} has no event shard at {live.as_posix()}",
            fix="check the run id against ow cost or the run manifests",
        )
    target = None if parsed.file is None else cwd / parsed.file
    done = _report(
        parsed.run,
        trace_entry("export")(
            live=str(live),
            config_digest=config.config_digest,
            file=None if target is None else str(target),
            max_batch=parsed.max_batch,
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
        stdout.write(_line(done, file=parsed.file) + "\n")
    return 0


def _report(run_id: str, result: Mapping[str, object]) -> TraceExportReport:
    """The entry point's builtins as this side's report. Anything else is a broken install."""
    shards, payloads = result.get("shards"), result.get("payloads")
    counts = {
        key: result.get(key) for key in ("spans", "batches", "points", "unterminated", "orphaned")
    }
    written = result.get("file")
    if not (
        isinstance(shards, list)
        and isinstance(payloads, list)
        and isinstance(written, str)
        and all(isinstance(value, int) for value in counts.values())
    ):
        raise InternalError(
            "the [omniweave.trace] export entry point returned an unreadable report",
            fix="pip install --force-reinstall omniweave-serve",
        )
    return TraceExportReport(
        run_id=run_id,
        shards=tuple(str(name) for name in shards),
        spans=int(counts["spans"]),  # type: ignore[arg-type]
        batches=int(counts["batches"]),  # type: ignore[arg-type]
        points=int(counts["points"]),  # type: ignore[arg-type]
        unterminated=int(counts["unterminated"]),  # type: ignore[arg-type]
        orphaned=int(counts["orphaned"]),  # type: ignore[arg-type]
        file=written,
        payloads=tuple(str(body) for body in payloads),
    )


def _line(done: TraceExportReport, *, file: str | None) -> str:
    """One verdict line, with what was read and not written named rather than dropped."""
    where = f"wrote {file}" if file is not None else "dry run, nothing written"
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
