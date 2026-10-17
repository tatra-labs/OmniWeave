"""`ow cost`: what a corpus or a run spent, sliced, and what the cache saved. **D838, D839.**

15-observability.md section 5.4 is the specification:

    ow cost [--corpus N] [--by driver|document|provider|lane|rung|slice|day]
            [--since <dur>|--run <run_id>] [--currency] [--verify] [--render text|json]

and 10-interfaces.md's `full` roster gives the tool: `ow_cost` / `cost.report`, *"spend by driver,
corpus and window, plus `would_have_been_micros_if_uncached`"*. The rows are
`omniweave.run.cost`'s; this module resolves the corpus, opens its store read-only, and prints.

## Rulings

1. **Six of section 5.4's seven slicings are served; `document` is refused by name.** Exit 1,
   with what is served as the fix. One decision serves several documents, so a per-document bill
   needs section 5.3's apportionment, and a table summing past its own bill would be one that lies
   about its axis.
2. **The window is the whole ledger, one run, or `--since <dur>` back from now.**
   - `--run R` keeps run R's generation. A run the store does not hold is `NotFoundError`, exit 2.
   - `--since` is `<n>m|h|d`, measured back from the wall clock read once here, `SystemClock`, as
     the other surfaces read it. A `--since` that reaches past the ledger's earliest decision says
     so, because section 5.4 calls a bill that silently starts where the sweep stopped *"a bill
     with a hole"*.
   - `--since` and `--run` together are refused, as 5.4's grammar prints them as alternatives.
   - `--currency` waits on a priced run, and is not a field, so it is not published as a
     promise. `--verify` is ruling 6.
3. **The four checkable lines of section 5.4's output are printed and checkable:**
   - `TOTAL` is the sum of the `micros` column;
   - `saved` is the sum of the `saved` column, and its ratio is `saved / TOTAL`;
   - the window says which rows were summed;
   - under `--run`, the reconcile line compares `Σ route_spend.micros` with the manifest's
     `cost.billed_micros` and says OK or MISMATCH. A run with no readable manifest says that
     instead of guessing.
   Section 5.4's worked line and its pricebook line wait on `--currency` and are not printed.
4. **`--render json` prints one object:** the report's fields with the rows as an array.
   `--render jsonl|rows` has no writer and is refused by name, as `ow out list` refuses them,
   and so is `--quiet`: a bill has no scalar to print alone.
5. **A mismatch is printed, not exited on.** Exiting non-zero on it is `--verify`'s job. A
   reconcile that failed the command without being asked would make reading a bill depend on the
   bill being right.
6. **`--verify` runs I30's two self-checks over one run and fails on either** (15 section 5.4,
   D853). The bill is printed first, then one `verify` line per check, then the failure:
   - `Σ route_spend.micros == manifest.cost.billed_micros`, exactly. A run with no readable
     manifest fails, because a check that could not be made did not pass;
   - every finished work row of the run's generation that names a decision has a `route_spend`
     row (`run.cost.unspent()`).

   Under `--render json` the output stays ruling 4's one object: the report when the run
   reconciles, and the error object alone when it does not.

   It checks the run `--run` names, or, without one, the latest run, so one command audits the
   last ingest. `--since` is refused beside it, since the checks are a run's. A failure is
   `RouteError` `OW_ROUTE_SPEND_UNRECONCILED` (`OW-R-031`), naming the run and each failed check.
   Section 5.4's third check, a Sequence's apportionment summing to its session within 1 micro,
   is not made: the session's own micros are not recorded apart from its parts, so there is
   nothing to sum against. The verify lines say so.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import NotFoundError, OwError, RouteError, UsageError

from omniweave.sdk.reports import CostListing, CostReport
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

__all__ = ["COST_WORD", "SLICINGS", "UNRECONCILED", "cost_report", "main"]

COST_WORD: Final[str] = "cost"
SLICINGS: Final = ("driver", "document", "provider", "lane", "rung", "slice", "day")
"""Section 5.4's `--by` vocabulary, in its order. `omniweave.run.cost.SLICINGS` is what is
served."""
_FIX: Final[str] = (
    "ow cost [--by driver|provider|lane|rung|slice|day] [--since 7d | --run R] [--corpus N] "
    "[--verify] [--render json]"
)
UNRECONCILED: Final = "OW_ROUTE_SPEND_UNRECONCILED"
"""Ruling 6's code, `OW-R-031`."""
_COLUMNS: Final = (
    "class",
    "units",
    "calls",
    "tokens_in",
    "tokens_out",
    "gpu_ms",
    "micros",
    "hits",
    "saved",
)


def main(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: TextIO, stderr: TextIO
) -> int:
    """`ow cost ...` from argv (starting at the root word). Exit 0, or the refusal's exit."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(COST_WORD, parsed)
        _refuse_unserved(parsed)
        explicit = Path(parsed.config) if parsed.config else None
        now_ms = None if parsed.since is None else _wall_ms()
        bill, earliest, unspent = cost_report(
            cwd=cwd,
            env=env,
            explicit=explicit,
            by=parsed.by,
            since=parsed.since,
            now_ms=now_ms,
            run=parsed.run,
            corpus=parsed.corpus,
            verify=parsed.verify,
        )
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)
    lines, failed = ([], []) if unspent is None else _verify(bill, unspent)
    if parsed.render == "json":
        if not failed:
            stdout.write(json.dumps(asdict(bill), ensure_ascii=False) + "\n")
    else:
        for line in [*_lines(bill, now_ms=now_ms, earliest=earliest), *lines]:
            stdout.write(line + "\n")
    if not failed:
        return 0
    error = RouteError(
        f"run {bill.run_id} does not reconcile (I30): {'; '.join(failed)}",
        symbol=UNRECONCILED,
        fix=f"ow cost --run {bill.run_id} --by driver",
    )
    return report(error, parsed, stdout=stdout, stderr=stderr)


def cost_report(
    *,
    cwd: Path,
    env: Mapping[str, str],
    explicit: Path | None,
    by: str,
    since: str | None,
    now_ms: int | None,
    run: str | None,
    corpus: str | None,
    verify: bool = False,
) -> tuple[CostReport, int | None, int | None]:
    """Rulings 1-3 and 6: one corpus's ledger, sliced and windowed, read-only.

    Returns the report, the ledger's earliest `decided_at`, which only a `--since` line reads, and
    under `verify` the run's unspent count (ruling 6), else `None`. `now_ms` is the wall clock in
    milliseconds, required with `since` and read by the caller.
    """
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    from omniweave.run.cost import (  # noqa: PLC0415
        by_key,
        earliest_decision,
        latest_run,
        manifest_billed,
        run_window,
        since_ms,
        unspent,
    )
    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    cutoff = None
    if since is not None:
        if now_ms is None:
            raise UsageError("--since needs the wall clock", fix=_FIX)
        try:
            cutoff = now_ms - since_ms(since)
        except ValueError as exc:
            raise UsageError(str(exc), fix=_FIX) from exc
    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow cost")
    connection = store_sqlite.connect_readonly(store_of(resolved, name, cwd=cwd))
    try:
        if verify and run is None:
            run = latest_run(connection)
            if run is None:
                raise NotFoundError(
                    f"corpus {name!r} has no run to verify", fix=f"ow ingest --corpus {name}"
                )
        window = None if run is None else run_window(connection, run)
        if run is not None and window is None:
            raise NotFoundError(
                f"no run {run!r} in corpus {name!r}", fix=f"ow cost --corpus {name}"
            )
        rows = by_key(
            connection,
            by,
            generation=None if window is None else window.generation,
            cutoff_ms=cutoff,
        )
        earliest = earliest_decision(connection)
        missing = None if window is None or not verify else unspent(connection, window.generation)
        billed = by_key(
            connection,
            "driver",
            generation=None if window is None else window.generation,
            cutoff_ms=cutoff,
        )
    finally:
        connection.close()
    listed = tuple(CostListing(**asdict(row)) for row in rows)
    return (
        CostReport(
            corpus=name,
            by=by,
            since=since,
            run_id=run,
            rows=listed,
            total_micros=sum(row.micros for row in listed),
            saved_micros=sum(row.saved for row in listed),
            billed_micros=sum(row.micros for row in billed if not row.key.startswith("op.")),
            manifest_billed_micros=(
                None if window is None else manifest_billed(window.manifest_path)
            ),
        ),
        earliest,
        missing,
    )


def _verify(bill: CostReport, missing: int) -> tuple[list[str], list[str]]:
    """Ruling 6: the verify lines, and each failed check named for the error."""
    failed = []
    if bill.manifest_billed_micros is None:
        failed.append("its manifest does not read, so the bill cannot be checked against it")
    elif bill.manifest_billed_micros != bill.billed_micros:
        failed.append(
            f"Σ route_spend.micros {bill.billed_micros:,} != manifest.cost.billed_micros "
            f"{bill.manifest_billed_micros:,}"
        )
    if missing:
        failed.append(f"{missing:,} finished work row(s) name a decision and have no spend row")
    one = "OK" if not failed or not failed[0].startswith(("its manifest", "Σ")) else "FAIL"
    two = "FAIL" if missing else "OK"
    return (
        [
            f"verify: run {bill.run_id}: Σ route_spend.micros == manifest billed  {one}",
            f"verify: run {bill.run_id}: every finished decided work row has a spend row  {two}",
            "verify: a Sequence's apportionment is not checked: no session total is recorded",
        ],
        failed,
    )


def _wall_ms() -> int:
    """Ruling 2: the one wall-clock read, as the other surfaces make it."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- only --since pays

    return SystemClock().wall_ns() // 1_000_000


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    from omniweave.run.cost import SLICINGS as SERVED  # noqa: PLC0415

    named = ["--quiet"] if parsed.quiet else []
    if parsed.by not in SERVED:
        named.append(f"--by {parsed.by}")
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow cost in this build; "
            f"--by takes one of {', '.join(SLICINGS)}, and serves {', '.join(SERVED)}",
            fix=_FIX,
        )
    if parsed.since is not None and parsed.run is not None:
        raise UsageError("--since and --run are two windows; give one", fix=_FIX)
    if parsed.verify and parsed.since is not None:
        raise UsageError("--verify checks a run, and --since is not one; give --run R", fix=_FIX)


def _lines(bill: CostReport, *, now_ms: int | None, earliest: int | None) -> list[str]:
    """Ruling 3's text form: the table, its total, what the cache saved, and the window."""
    window = _window(bill, now_ms=now_ms, earliest=earliest)
    if not bill.rows:
        return [f"{bill.corpus}: no decision and no op row in this window", *window]
    cells = [
        [
            row.key,
            row.cost_class,
            *(
                f"{value:,}"
                for value in (
                    row.units,
                    row.calls,
                    row.tokens_in,
                    row.tokens_out,
                    row.gpu_ms,
                    row.micros,
                    row.hits,
                    row.saved,
                )
            ),
        ]
        for row in bill.rows
    ]
    # TOTAL sits in the gpu_ms column so its figures land under `micros` and `saved`.
    totals = [
        "",
        "",
        "",
        "",
        "",
        "",
        "TOTAL",
        f"{bill.total_micros:,}",
        "",
        f"{bill.saved_micros:,}",
    ]
    table = [[bill.by, *_COLUMNS], *cells, totals]
    widths = [max(len(cell[at]) for cell in table) for at in range(len(_COLUMNS) + 1)]
    lines = [_row(cell, widths) for cell in table]
    ratio = f" ({bill.saved_micros / bill.total_micros:.1f}x the bill)" if bill.total_micros else ""
    lines.append(f"cache saved {bill.saved_micros:,}µ{ratio}.")
    lines.extend(window)
    if bill.run_id is not None:
        lines.append(_reconcile(bill))
    return lines


def _window(bill: CostReport, *, now_ms: int | None, earliest: int | None) -> list[str]:
    """Ruling 2's window line, and the hole a `--since` past the ledger's start would hide."""
    if bill.run_id is not None:
        return [f"window: run {bill.run_id}'s generation"]
    if bill.since is None or now_ms is None:
        return ["window: every generation in the ledger"]
    from omniweave.run.cost import since_ms  # noqa: PLC0415

    cutoff = now_ms - since_ms(bill.since)
    lines = [f"window: since {_date(cutoff)} ({bill.since})"]
    if earliest is not None and earliest > cutoff:
        lines.append(
            f"the ledger's earliest decision is {_date(earliest)}: nothing older is held to count"
        )
    return lines


def _date(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _row(cells: Sequence[str], widths: Sequence[int]) -> str:
    left = [cells[0].ljust(widths[0]), cells[1].ljust(widths[1])]
    right = [cell.rjust(width) for cell, width in zip(cells[2:], widths[2:], strict=True)]
    return "  ".join([*left, *right]).rstrip()


def _reconcile(bill: CostReport) -> str:
    """Ruling 3's last line and ruling 5: said, never exited on."""
    ledger = f"Σ route_spend.micros = {bill.billed_micros:,}"
    if bill.manifest_billed_micros is None:
        return f"reconcile: {ledger}; run {bill.run_id} wrote no readable manifest"
    verdict = "OK" if bill.manifest_billed_micros == bill.billed_micros else "MISMATCH"
    sign = "==" if verdict == "OK" else "!="
    return (
        f"reconcile: {ledger} {sign} manifest.cost.billed_micros "
        f"{bill.manifest_billed_micros:,}  {verdict}"
    )
