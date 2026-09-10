"""`ow ingest --scope`'s runner: walk a tree, write the `unit` roster, print `ingest_scope`.

**Why a `tools/` script and not a CLI in the package.** `omniweave.cli` is P7's (16-roadmap.md
section 10) and `packages/omniweave/src/omniweave/` is a bare skeleton; W3.8 lands at P3. This is
the fourth application of the standing pattern (ledger D25): `ow schema emit` shipped as
`tools/schemagen.py` at P1, `ow store verify` as `store/verify.py` plus `tools/gate_crash.py`,
`ow test crash-matrix` as `store/crashmatrix.py` plus the same gate, and `ow eval perf` as
`store/inspect.py` plus `tools/measure_store.py`. In each the LIBRARY FUNCTION lives in the
package and a `tools/` script drives it, so P7 wraps a function rather than re-implementing one.
`tools/gate_crash.py`'s docstring is the worked example and this file follows its shape.

`omniweave_core.acquire` is the library half. Everything below is argument parsing, a store
handle, and printing -- there is no walk, no glob, no `stat` and no SQL in this file, which is
what makes it a driver of the library rather than a second implementation of it. In particular
the `ingest_scope` arithmetic is `ScopeTally.__post_init__`'s and is not re-checked here: a
runner that recomputed the number its subject claimed would mask exactly the bug the check
exists to catch.

## What `--scope` is

05-ingest-and-routing.md:411 spells the verb `ow ingest --scope <scope_id>` and
18-api-sketch.md:1462 calls the value *"the `ingest_scope` row id; pass it to `ow queue status
--scope`"*. That row's id is its primary key, and 07-store-and-retrieval.md section 3.8 says the
primary key is *"the canonical URI PREFIX of the enumerated root"* -- so `--scope` and `--root`
name the same tree in two coordinate systems, and `--scope` is derived from `--root` unless the
operator overrides it. `--scope` alone is not enough to walk with: a URI prefix is not a path
until something un-normalises it, and `canonical_uri()` is deliberately one-way.

## Exit codes

`0` the scan completed: the roster is written and the `ingest_scope` row says `complete = 1`.
`1` the scan ran and did not complete -- `--max-units` truncated it, or a root vanished. The
roster rows and the coverage row are still written, with `complete = 0`, because 05:371 makes an
incomplete scan a *recorded* fact rather than a discarded one: *"An **incomplete** scan never
marks anything out of scope."*
`2` the scan did not run: a bad argument, a missing root, or a store with no `unit` table. Nothing
was written.

1 and 2 are distinguished for the reason `tools/gate_crash.py` distinguishes them -- both are
failures to a caller and a human needs to know which -- and 0/1 are distinguished because
"incomplete" is the state absence gate 4 exists to report and must not be reported as success.

Specified in 05-ingest-and-routing.md sections 1.1-1.5, 02-architecture.md:472,
07-store-and-retrieval.md section 3.8, 16-roadmap.md:527 (W3.8) and 10-interfaces.md:1114.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from omniweave_core import acquire
from omniweave_core.errors import OwError
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow

EXIT_CLEAN = 0
EXIT_INCOMPLETE = 1
EXIT_NOT_RUN = 2

Emit = Callable[[str], None]

__all__ = [
    "EXIT_CLEAN",
    "EXIT_INCOMPLETE",
    "EXIT_NOT_RUN",
    "Emit",
    "discover",
    "main",
]


def _parser() -> argparse.ArgumentParser:
    """The flags, each named after the `[ingest]` key or `unit` column it sets."""
    parser = argparse.ArgumentParser(
        prog="ow_discover.py",
        description=(
            "Walk a tree, write the unit roster and one ingest_scope row, print the summary. "
            "The runner for `ow ingest --scope`, which is P7's CLI (ledger D25)."
        ),
        epilog="exit 0 the scan completed - 1 it ran and did not complete - 2 it did not run",
    )
    parser.add_argument("--root", type=Path, required=True, help="the tree to walk")
    parser.add_argument("--store", type=Path, required=True, help="the .owstore file")
    parser.add_argument(
        "--scope",
        default=None,
        help="ingest_scope.scope_id; defaults to canonical_uri(--root) plus a trailing '/'",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="apply the shipped migrations when --store does not exist yet",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB",
        help=f"repeatable; default {list(acquire.DEFAULT_INCLUDE)}",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="GLOB",
        help=f"repeatable; default {list(acquire.DEFAULT_EXCLUDE)}",
    )
    parser.add_argument("--max-depth", type=int, default=acquire.DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-unit-bytes", type=int, default=acquire.DEFAULT_MAX_UNIT_BYTES)
    parser.add_argument(
        "--hidden", action="store_true", help="[ingest] hidden = true: index dotfiles"
    )
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="[ingest] follow_symlinks = true. NEVER for an untrusted tree (OW-A-007)",
    )
    parser.add_argument(
        "--trust-class",
        choices=[member.value for member in acquire.TrustClass],
        default=acquire.TrustClass.INTERNAL.value,
        help="unit.trust_class, stamped by the host from SourceLocator.trust_class",
    )
    parser.add_argument(
        "--generation",
        type=int,
        default=1,
        help="unit.last_seen_gen: the run's monotonic generation, never a clock",
    )
    parser.add_argument(
        "--now-ns",
        type=int,
        default=None,
        help=(
            "unit.indexed_at_ns and ingest_scope.scanned_at_ns. INJECTED, because time.time is "
            "banned in library code and two runs at one --now-ns write identical rows"
        ),
    )
    parser.add_argument("--cursor", default=None, help="resume from an emitted next_cursor")
    parser.add_argument("--max-units", type=int, default=acquire.MAX_UNITS_PER_CALL)
    parser.add_argument("--plan-batch", type=int, default=acquire.PLAN_BATCH)
    parser.add_argument("--json", action="store_true", help="print the summary as one JSON object")
    return parser


def discover(args: argparse.Namespace, emit: Emit) -> tuple[int, acquire.ScopeTally]:
    """One scan: open the store, stream the roster into it, write the coverage row.

    The tally is returned rather than only printed so that a test asserts on the value the store
    was given instead of on a re-render of it.
    """
    locator = acquire.locator_for(args.root, cursor=args.cursor)
    scope_id = args.scope or acquire.scope_id_for(locator)
    scope = acquire.Scope(
        roots=(locator.target,),
        include=tuple(args.include) if args.include else acquire.DEFAULT_INCLUDE,
        exclude=tuple(args.exclude) if args.exclude else acquire.DEFAULT_EXCLUDE,
    )
    guards = acquire.IngestGuards(
        follow_symlinks=args.follow_symlinks,
        max_depth=args.max_depth,
        max_unit_bytes=args.max_unit_bytes,
        hidden=args.hidden,
    )
    now_ns = _now_ns(args)
    tally = acquire.Tally()

    with ow.StoreThread(lambda: ow.connect(args.store)) as thread:
        acquire.refuse_unmigrated(thread)
        rows = acquire.scan(
            locator,
            scope,
            guards,
            indexed_at_ns=now_ns,
            last_seen_gen=args.generation,
            tally=tally,
            trust_class=acquire.TrustClass(args.trust_class),
            max_units=args.max_units,
        )
        # `rows` is a generator and `tally` is the accumulator behind it, so the coverage row is
        # frozen by `write_roster` after the last candidate and written in the same transaction
        # as the last roster batch. Freezing it here would record `complete = 0` on every run;
        # writing it in a second transaction would leave a window in which the roster is done
        # and the store still reports coverage unknown.
        written, frozen = acquire.write_roster(
            thread,
            rows,
            tally=tally,
            scope_id=scope_id,
            scanned_at_ns=now_ns,
            plan_batch=args.plan_batch,
        )
        assert frozen is not None  # noqa: S101 - `tally` and `scope_id` were both given

    emit(f"root   {locator.target}")
    emit(f"scope  {scope_id}")
    emit(f"rows   {written} roster upserts at {args.plan_batch}/transaction")
    return (EXIT_CLEAN if frozen.complete else EXIT_INCOMPLETE), frozen


def _now_ns(args: argparse.Namespace) -> int:
    """`--now-ns`, or the wall clock read HERE.

    `tools/` is not library code -- `tools/gate_semgrep.py:26-37` takes that reading for itself in
    as many words -- so a runner may read a clock where `omniweave_core.acquire` may not
    (02-architecture.md:392: clocks are parameters). The flag exists so a test and a byte-diff can
    pin it, which is the same seam `store/crashmatrix.py` gives `migrate.apply_pending(conn, *,
    now_ns)`.
    """
    if args.now_ns is not None:
        return args.now_ns
    import time  # noqa: PLC0415 - deferred so the import itself cannot be mistaken for library use

    return time.time_ns()


def _report(tally: acquire.ScopeTally, *, as_json: bool, emit: Emit) -> None:
    """Print the `ingest_scope` row. The three counters, then the reasons, then completeness."""
    if as_json:
        emit(json.dumps(dict(tally.params()), sort_keys=True))
        return
    emit("")
    emit("ingest_scope")
    emit(f"  discovered {tally.discovered}")
    emit(f"  indexed    {tally.indexed}")
    emit(f"  skipped    {tally.skipped}")
    for reason in sorted(tally.skipped_why):
        emit(f"    {reason:<22} {tally.skipped_why[reason]}")
    emit(f"  complete   {int(tally.complete)}")
    emit("")
    if tally.complete:
        emit(
            f"discover ok  {tally.discovered} discovered = {tally.indexed} indexed + "
            f"{tally.skipped} skipped; absence gate 4 reads this row."
        )
        return
    emit(
        "discover INCOMPLETE  complete = 0, so no unit may be marked out_of_scope from this "
        "scan (05-ingest-and-routing.md:371). Resume with --cursor."
    )


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    """Parse, scan, report. 0 completed, 1 ran and did not complete, 2 did not run."""
    stream = sys.stdout if out is None else out

    def emit(line: str) -> None:
        print(line, file=stream)

    args = _parser().parse_args(argv)

    if not args.root.is_dir():
        emit(f"discover DID NOT RUN  --root {args.root} is not a directory")
        return EXIT_NOT_RUN
    if args.create and not args.store.exists():
        args.store.parent.mkdir(parents=True, exist_ok=True)
        connection = ow.connect(args.store)
        try:
            migrate.apply_pending(connection, now_ns=_now_ns(args))
        finally:
            connection.close()
    if not args.store.exists():
        emit(f"discover DID NOT RUN  --store {args.store} does not exist; pass --create")
        return EXIT_NOT_RUN

    try:
        code, tally = discover(args, emit)
    except (OwError, OSError, ValueError) as error:
        emit(f"discover DID NOT RUN  {error}")
        return EXIT_NOT_RUN

    _report(tally, as_json=args.json, emit=emit)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
