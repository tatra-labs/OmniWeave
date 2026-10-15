"""`ow cost`: what a corpus or a run spent, by driver, and what the cache saved. **D838.**

15-observability.md section 5.4 is the specification:

    ow cost [--corpus N] [--by driver|document|provider|lane|rung|slice|day]
            [--since <dur>|--run <run_id>] [--currency] [--verify] [--render text|json]

and 10-interfaces.md's `full` roster gives the tool: `ow_cost` / `cost.report`, *"spend by driver,
corpus and window, plus `would_have_been_micros_if_uncached`"*. The rows are
`omniweave.run.cost`'s; this module resolves the corpus, opens its store read-only, and prints.

## Rulings

1. **`--by driver` is served; the other six slicings are refused by name.** Exit 1, with what is
   served as the fix. A slicing that printed `driver`'s rows under another name would be a bill
   that lies about its own axis.
2. **The window is the whole ledger, or one run.** `--run R` keeps run R's generation. A run the
   store does not hold is `NotFoundError`, exit 2. `--since` waits on a clock this surface does not
   take, and `--currency` and `--verify` on I30's audit (`work` records no outcome, and parse rows
   carry no spend yet: 05:2596). None of the three is a field, so none is published as a promise.
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
5. **A mismatch is printed, not exited on.** Exiting non-zero on it is `--verify`'s job, and
   `--verify` is not served. A reconcile that failed the command without being asked would make
   reading a bill depend on the bill being right.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.errors import NotFoundError, OwError, UsageError

from omniweave.sdk.reports import CostListing, CostReport
from omniweave.surface.query import parse
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

__all__ = ["COST_WORD", "SERVED", "SLICINGS", "cost_report", "main"]

COST_WORD: Final[str] = "cost"
SLICINGS: Final = ("driver", "document", "provider", "lane", "rung", "slice", "day")
"""Section 5.4's `--by` vocabulary, in its order."""
SERVED: Final = frozenset({"driver"})
"""Ruling 1."""
_FIX: Final[str] = "ow cost [--by driver] [--run R] [--corpus N] [--render json]"
_HEADER: Final = (
    "driver",
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
        bill = cost_report(
            cwd=cwd, env=env, explicit=explicit, run=parsed.run, corpus=parsed.corpus
        )
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)
    if parsed.render == "json":
        stdout.write(json.dumps(asdict(bill), ensure_ascii=False) + "\n")
    else:
        for line in _lines(bill):
            stdout.write(line + "\n")
    return 0


def cost_report(
    *, cwd: Path, env: Mapping[str, str], explicit: Path | None, run: str | None, corpus: str | None
) -> CostReport:
    """Rulings 2 and 3: one corpus's ledger, or one run of it, read-only."""
    from omniweave_core import config  # noqa: PLC0415 -- only this verb pays
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    from omniweave.run.cost import by_driver, manifest_billed, run_window  # noqa: PLC0415
    from omniweave.surface.opening import corpus_for  # noqa: PLC0415
    from omniweave.surface.query import store_of  # noqa: PLC0415

    resolved = config.load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(resolved, [], corpus, verb="ow cost")
    connection = store_sqlite.connect_readonly(store_of(resolved, name, cwd=cwd))
    try:
        window = None if run is None else run_window(connection, run)
        if run is not None and window is None:
            raise NotFoundError(
                f"no run {run!r} in corpus {name!r}", fix=f"ow cost --corpus {name}"
            )
        rows = by_driver(connection, generation=None if window is None else window.generation)
    finally:
        connection.close()
    listed = tuple(CostListing(**asdict(row)) for row in rows)
    billed = sum(row.micros for row in rows if not row.driver.startswith("op."))
    return CostReport(
        corpus=name,
        run_id=run,
        rows=listed,
        total_micros=sum(row.micros for row in listed),
        saved_micros=sum(row.saved for row in listed),
        billed_micros=billed,
        manifest_billed_micros=None if window is None else manifest_billed(window.manifest_path),
    )


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.by not in SERVED:
        named.append(f"--by {parsed.by}")
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow cost in this build; "
            f"--by takes one of {', '.join(SLICINGS)}, and serves {', '.join(sorted(SERVED))}",
            fix=_FIX,
        )


def _lines(bill: CostReport) -> list[str]:
    """Ruling 3's text form: the table, its total, what the cache saved, and the window."""
    window = (
        f"window: run {bill.run_id}'s generation"
        if bill.run_id is not None
        else "window: every generation in the ledger"
    )
    if not bill.rows:
        return [f"{bill.corpus}: no decision and no op row in this window", window]
    cells = [
        [
            row.driver,
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
    table = [list(_HEADER), *cells, totals]
    widths = [max(len(cell[at]) for cell in table) for at in range(len(_HEADER))]
    lines = [_row(cell, widths) for cell in table]
    ratio = f" ({bill.saved_micros / bill.total_micros:.1f}x the bill)" if bill.total_micros else ""
    lines.append(f"cache saved {bill.saved_micros:,}µ{ratio}.")
    lines.append(window)
    if bill.run_id is not None:
        lines.append(_reconcile(bill))
    return lines


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
