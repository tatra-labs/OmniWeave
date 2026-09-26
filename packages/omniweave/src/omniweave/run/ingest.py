"""`ow ingest`: the drain every `ow_add` and every `PostToolUse` hook waits on, as far as it goes.

02-architecture.md section 4.1 traces one born-digital PDF through nineteen hops, and every hop
from 2 to 17 has a module in this tree. **None of them had ever run after another.** `ow_add`
rostered units into `discovered` (W7.3v) and nothing anywhere moved one out: the SQL for the claim,
the read and the identify row was written in P4, tested alone, and called by no command. This
module is the first caller, and it runs the trace in order until the first hop that is not built:

- **hop 1**, one `run` row with a monotonic `generation` and `status='running'`: `open_run()`;
- **hop 2**, `run/discover` rostering at `plan_batch` with one `ingest_scope` row: `discover()` per
  scope, and a file source as a roster row with no scope row (D556);
- **hop 3**, the stat triple, the digest and `unit.state='acquired'`: `acquire_pending()`;
- **hop 4**, `op.identify`'s `work` row and then `part_count` and `state='identified'`:
  `expand.enqueue()`, then **the Supervisor** draining it;
- **hops 5-9**, resolve, evidence, `evaluate()`, `admit()` and `omniweave.plan`'s `INSERT`: **not
  built.** No code writes a `route_decision` row, and a `parse.*` `work` row cannot exist before
  one -- 02:452-461's three CHECKs;
- **hops 10-17**, dispatch, the pipeline, S4, the driver, `DocSink` and `complete()`: unreachable
  without hop 9.

So a unit ends this run `identified`, and **the run says so**: `status = 'partial'`, and the last
line of the report names the hop the drain stopped at. A run that exited 0 printing `ok` over a
corpus that `ow_query` still cannot cite would be the defect INV-20 names -- a front door that lies.

## THE SUPERVISOR RUNS A REAL OPERATOR FOR THE FIRST TIME

`Supervisor` has been built twice before, by `ow bench scheduler` and `tools/gate_scale.py`, and
both pass `no_op` -- a dispatcher that answers `OK` for every row without reading anything. Here
the dispatcher is `op.identify`: it reads each claimed unit's digest, runs the part counter, and
records the answer in `expand.IdentifyLedger`, whose statement rides in the same `complete()`
transaction as the `work` transition (07:2733-2735's five participants, derived rows first). That is
the path 08 section 1.2 specifies and no run had taken.

**The counter is `single_part`, and that is correct for every unit this build can parse, not a
placeholder.** `05:3186`: *"op.identify -> part_count = 1 (granularity='document' on the card, so
unit_part = '')"*. Both shipped `parse/1` DECODE drivers declare `granularity = "document"` --
`parse.pdf.pdfium` because the glyph index space is the document's, `parse.office.anydoc` because
it is one `to_document` call per unit -- so every unit a shipped decoder reads has exactly one part.
A unit no driver reads is also counted 1, and the place it fails is resolution (hop 5), which is
where 02 section 7.4 puts a zero-candidate outcome. The page-granularity lane is an escalation of a
decoded part, not a second count.

## WHAT THE RUN ROW CARRIES, AND THE THREE COLUMNS NOTHING PRODUCES YET

`config_digest` and `semantic_digest` are the loaded `Config`'s. `policy_digest` is the built-in
route policy's, compiled here, because startup step 4 freezes one and no project policy loader is
wired -- and this run routes nothing, so the digest names the policy that would have. Three
columns are `NOT NULL` and have no producer in this run: `pricebook_digest` (no `PriceBook` is
loaded: nothing here is priced), `lock_digest` (`omniweave.index.lock` is hop 19's), and
`manifest_path` (`RunManifest` is hop 19's). Each is written as the empty string and D562 records
why an empty string rather than an invented digest.

**`index_state.generation` is not bumped.** 08:1623 makes the bump *"the last step of the refresh
loop"*, and 08:1610-1611 put it *"inside the completing transaction"* -- after parse, merge and
converge -- and retrieval's gate 3 reads it. Nothing this run writes is visible to a query, so
advancing it would tell every reader a refresh happened that did not.

Specified in 02-architecture.md sections 4.1 and 5.3-5.4, 05-ingest-and-routing.md sections 1.2
and 3, 08-runtime.md sections 1.2, 2.5 and 5.1-5.2, and 10-interfaces.md sections 6.4 and 8.6.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
from dataclasses import dataclass, field, replace
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from omniweave_core.acquire import (
    IngestGuards,
    RosterRow,
    Scope,
    Tally,
    locator_for,
    scope_id_for,
    write_roster,
)
from omniweave_core.clock import SystemClock
from omniweave_core.contract import CONTRACT
from omniweave_core.errors import RouteError, StoreError
from omniweave_core.locks import BATCH_WAIT_MS, store_write_lock
from omniweave_core.operator import (
    ULID_ENTROPY_BYTES,
    CancelToken,
    Roots,
    RunContext,
    new_run_id,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import SqliteStore
from omniweave_ports.types import DriverError, FailureClass

from omniweave.route.detect import Detection, detect
from omniweave.run import discover, expand
from omniweave.run import supervisor as sup
from omniweave.run.routing import RouteTally, resolve_policy, route_identified

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.clock import Clock
    from omniweave_core.config import Config
    from omniweave_core.operator import StepResult
    from omniweave_core.store.queue import StepResultView
    from omniweave_core.work import WorkRow
    from omniweave_ports.types import UnitRef

    from omniweave.run.dispatch import Batch

__all__ = [
    "IDENTIFIED",
    "PLANNED",
    "RUN_CLOSE_SQL",
    "RUN_INSERT_SQL",
    "STOPPED_AT",
    "TRIGGER",
    "UNROUTED",
    "IngestReport",
    "NoExecutorError",
    "Source",
    "close_run",
    "ingest",
    "open_run",
    "row_as_explicit",
    "sources_of",
]

TRIGGER: Final[str] = "cli"
"""`run.trigger` for every run this module starts. 08:1636's table gives `ow ingest` the `cli` row.

`hook` and `mcp` are the rows a `PostToolUse` drain and an `ow_add` child would write, and neither
exists: no module in the workspace may spawn a detached child (D554, D433), so every `ow ingest`
this build runs was typed by someone.
"""

STOPPED_AT: Final[str] = (
    "hops 10-17 (dispatch, the pipeline, the driver, DocSink, complete) are not run by this build: "
    "a planned parse row waits for them"
)
"""Why a planned unit goes no further, printed on the report's parse line. D578."""

UNROUTED: Final[str] = "routed to no driver (see the route lines above)"
"""Why an identified unit went no further: `run.routing` named a rule and no candidate served it."""

RUN_INSERT_SQL: Final[str] = """
INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest, policy_digest,
                pricebook_digest, lock_digest, omniweave_version, contract, schema, started_ns,
                status, manifest_path)
SELECT :run_id, COALESCE(MAX(generation), 0) + 1, :trigger, :argv, :config_digest,
       :semantic_digest, :policy_digest, '', '', :version, :contract, :schema, :started_ns,
       'running', ''
  FROM run
RETURNING generation
"""
"""Hop 1: one `run` row, its generation minted in the same statement that stores it.

08:1622's rule -- *"`run.generation` ... the runner, at run start: `old.generation + 1`"* -- as one
`INSERT ... SELECT` rather than a read and a write, so two `ow ingest` processes starting together
cannot mint one generation between them: the statement runs under the store thread's `BEGIN
IMMEDIATE`, and the second waits for the first to commit. `RETURNING` gives the value back without a
second read that a third process could interleave with.
"""

RUN_CLOSE_SQL: Final[str] = (
    "UPDATE run SET status = :status, ended_ns = :ended_ns WHERE run_id = :id"
)

IDENTIFIED: Final[str] = "identified"
PLANNED: Final[str] = "planned"
"""The `unit.state` hop 4 leaves a unit in, and the one this build leaves every parsable unit in."""

_SCOPES_SQL: Final[str] = "SELECT scope_id FROM ingest_scope ORDER BY scope_id"
_EXPLICIT_SQL: Final[str] = """
SELECT unit_uri FROM unit
 WHERE connector = 'fs' AND scope_rule = 'explicit' AND state <> 'out_of_scope'
 ORDER BY unit_uri
"""
_UNIT_SQL: Final[str] = "SELECT content_sha256, bytes, media_type FROM unit WHERE unit_uri = ?"
_TALLY_SQL: Final[str] = """
SELECT state, count(*), COALESCE(sum(part_count), 0) FROM unit
 WHERE last_seen_gen = :generation GROUP BY state
"""
_FORMATS_SQL: Final[str] = """
SELECT format, count(*) FROM unit
 WHERE last_seen_gen = :generation AND format IS NOT NULL GROUP BY format ORDER BY format
"""


@dataclass(frozen=True, slots=True)
class Source:
    """One thing to walk: a directory, which is a scope, or one file, which is not (D556)."""

    path: Path
    directory: bool


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What one `ow ingest` did, per hop, in the order 10:1570-1575's progress block prints them.

    `states` is `SELECT state, count(*) FROM unit WHERE last_seen_gen = <this generation>` at the
    end of the run: the units this run's walk saw, by where each one stopped. It is read from the
    table rather than summed from the phases, because 02:751 is the rule for every such number --
    *"`SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift"*.
    """

    run_id: str
    generation: int
    status: str
    scopes: int = 0
    files: int = 0
    discovered: int = 0
    skipped: int = 0
    unseen: int = 0
    acquired: discover.AcquirePass = field(default_factory=discover.AcquirePass)
    enqueued: int = 0
    unsalted: int = 0
    drained: sup.RunReport | None = None
    states: Mapping[str, int] = field(default_factory=dict)
    parts: int = 0
    formats: Mapping[str, int] = field(default_factory=dict)
    routed: RouteTally | None = None

    @property
    def planned(self) -> int:
        return self.states.get(PLANNED, 0)

    @property
    def identified(self) -> int:
        return self.states.get(IDENTIFIED, 0)

    @property
    def failed(self) -> int:
        return self.states.get(discover.FAILED, 0)

    def lines(self) -> tuple[str, ...]:
        """The report, one line per hop. ASCII only: a piped child's stdout on Windows is cp1252."""
        acq = self.acquired
        drained = self.drained
        identify = (
            "identify  nothing to identify"
            if drained is None
            else (
                f"identify  {drained.completed} work rows completed, {self.identified} units "
                f"identified, {self.parts} parts"
            )
        )
        out = [
            f"ow ingest  run {self.run_id}  generation {self.generation}",
            f"  roster    {self.scopes} scopes, {self.files} files, {self.discovered} units, "
            f"{self.skipped} skipped, {self.unseen} unseen",
            f"  acquire   {acq.acquired} read, {acq.unchanged} unchanged, {acq.failed} failed, "
            f"{acq.bytes_read} bytes",
            f"  {identify}",
        ]
        if self.formats:
            shown = ", ".join(f"{token} {count}" for token, count in self.formats.items())
            out.append(f"  detect    {shown}")
        if self.unsalted:
            out.append(
                f"  identify  {self.unsalted} units carry no walked path and cannot be keyed (D559)"
            )
        if self.routed is not None:
            out.extend(self.routed.lines())
        if self.identified:
            out.append(f"  identify  {self.identified} units stop here: {UNROUTED}")
        if self.planned:
            out.append(f"  parse     {self.planned} units planned: {STOPPED_AT}")
        out.append(f"{self.status}  {self.failed} failed")
        return tuple(out)


def sources_of(
    thread: ow.StoreThread, *, paths: Sequence[Path], scope: str | None
) -> tuple[Source, ...]:
    """What this run walks: the paths given, else one stored scope, else everything stored.

    10:1570's `ow ingest --scope 92` names a scope the roster already holds, and the detached child
    `ow_add` would spawn is exactly that. With no argument at all -- the spawn `posttool.command()`
    builds is `ow ingest` and nothing else -- the drain re-walks every stored scope, plus every file
    rostered on its own (`scope_rule = 'explicit'`) that no stored scope contains: the files
    `ow_add` was given one by one, which have no scope row by D556 and would otherwise never be
    walked again.

    **Every run re-walks, and that is the design rather than a cost.** 08:1759: *"the next `ow
    ingest` re-derives the same change set from `stat_fresh` and `last_seen_gen` on the `unit`
    roster."* The walk is what stamps `last_seen_gen` with this run's generation, and
    `PENDING_ACQUISITION_SQL` reads exactly that generation -- so a unit the walk did not see this
    run is not acquired this run, which is the deletion sweep's mirror image.
    """
    if paths:
        return tuple(Source(path=path, directory=path.is_dir()) for path in paths)
    stored = cast("list[str]", _read(thread, "ingest.scopes", _scopes))
    if scope is not None:
        wanted = _scope_key(scope)
        if wanted not in stored:
            raise StoreError(
                f"no ingest_scope row is {wanted!r}; the store holds {len(stored)} scopes",
                fix="ow add <directory> first, or ow ingest <directory>",
            )
        return (Source(path=Path(wanted), directory=True),)
    explicit = cast("list[str]", _read(thread, "ingest.explicit", _explicit))
    loose = [uri for uri in explicit if not any(uri.startswith(prefix) for prefix in stored)]
    return (
        *(Source(path=Path(prefix), directory=True) for prefix in stored),
        *(Source(path=Path(uri), directory=False) for uri in loose),
    )


def _scope_key(scope: str) -> str:
    """A `--scope` value as a stored `scope_id`: a stored prefix is taken as it is, a path is
    canonicalised. D555 is why this is a prefix and not 10:1570's integer."""
    if scope.endswith("/") and not Path(scope).is_dir():
        return scope
    return scope_id_for(locator_for(Path(scope).resolve()))


def _scopes(connection: object) -> list[str]:
    return [str(row[0]) for row in connection.execute(_SCOPES_SQL).fetchall()]  # type: ignore[attr-defined]


def _explicit(connection: object) -> list[str]:
    return [str(row[0]) for row in connection.execute(_EXPLICIT_SQL).fetchall()]  # type: ignore[attr-defined]


def _read(thread: ow.StoreThread, name: str, run: Callable[[object], object]) -> object:
    """One read on the store thread. INV-17: it is the only holder of a connection."""
    return thread.run(ow.Unit(name=name, run=run, cost_class="free", wait_ms=BATCH_WAIT_MS))


def ingest(
    store: Path,
    *,
    config: Config,
    source_root: Path,
    output_root: Path,
    cache_root: Path,
    argv: Sequence[str],
    paths: Sequence[Path] = (),
    scope: str | None = None,
    clock: Clock | None = None,
    sweep_ms: int | None = None,
) -> IngestReport:
    """Run hops 1-4 over one store, under `store.write`, and report where every unit stopped.

    `sweep_ms` replaces `[runtime] deferred_sweep_ms` for this run's loop when given. It is the
    interval `Supervisor._settle()` waits between empty claims, and 08:915's two quiet polls mean a
    drain ends two of them after its last row: ten seconds at the shipped 5,000. A test passes a
    small value for `bench.SWEEP_MS`'s reason; the CLI does not, and D564 records the tail.

    Refuses a store that does not exist unless `paths` were given, because an ingest with nothing
    rostered and nothing to walk has no work that could exist -- and creating an empty store as a
    side effect of a typo in `--corpus` would leave a file that says a corpus is there.
    """
    ticking = SystemClock() if clock is None else clock
    if not store.exists():
        if not paths:
            raise StoreError(
                f"no store at {store}; there is nothing rostered to ingest",
                fix="ow add <source> first, or ow ingest <directory>",
            )
        _create(store, now_ns=ticking.wall_ns())
    lock = store_write_lock(store, now_ns=ticking.wall_ns)
    with ow.StoreThread(lambda: ow.connect(store), lock=lock) as thread:
        run_id, generation = open_run(thread, config=config, argv=argv, clock=ticking)
        try:
            report = _hops(
                thread,
                run_id=run_id,
                generation=generation,
                config=config,
                roots=Roots(source=source_root, output=output_root, cache=cache_root),
                paths=paths,
                scope=scope,
                clock=ticking,
                sweep_ms=sweep_ms,
                store=store,
            )
        except BaseException:
            close_run(thread, run_id, status="failed", ended_ns=ticking.wall_ns())
            raise
        close_run(thread, run_id, status=report.status, ended_ns=ticking.wall_ns())
    return report


def _create(store: Path, *, now_ns: int) -> None:
    """A store that does not exist yet, created and migrated. `add_sources()`'s own first step."""
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = ow.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=now_ns)
    finally:
        connection.close()


def open_run(
    thread: ow.StoreThread, *, config: Config, argv: Sequence[str], clock: Clock
) -> tuple[str, int]:
    """Hop 1. The `run` row, `status = 'running'`, and the generation it minted."""
    from omniweave.route.policy import builtin_layer, compile_policy  # noqa: PLC0415

    run_id = new_run_id(clock, os.urandom(ULID_ENTROPY_BYTES))
    params = {
        "run_id": run_id,
        "trigger": TRIGGER,
        "argv": json.dumps(list(argv), separators=(",", ":")),
        "config_digest": config.config_digest,
        "semantic_digest": config.semantic_digest,
        "policy_digest": compile_policy([builtin_layer()]).policy_digest,
        "version": metadata.version("omniweave"),
        "contract": CONTRACT,
        "started_ns": clock.wall_ns(),
    }

    def run(connection: object) -> object:
        schema = connection.execute(  # type: ignore[attr-defined]
            "SELECT v FROM index_state WHERE k = 'schema'"
        ).fetchone()
        major = int(str(schema[0]).split(".", 1)[0]) if schema else 0
        row = connection.execute(RUN_INSERT_SQL, {**params, "schema": major}).fetchone()  # type: ignore[attr-defined]
        return int(row[0])

    generation = thread.run(
        ow.Unit(name="ingest.run", run=run, cost_class="free", wait_ms=BATCH_WAIT_MS)
    )
    return run_id, cast("int", generation)


def close_run(thread: ow.StoreThread, run_id: str, *, status: str, ended_ns: int) -> None:
    """The run row's last write: its status and its end."""

    def run(connection: object) -> None:
        connection.execute(RUN_CLOSE_SQL, {"status": status, "ended_ns": ended_ns, "id": run_id})  # type: ignore[attr-defined]

    thread.run(ow.Unit(name="ingest.run.close", run=run, cost_class="free", wait_ms=BATCH_WAIT_MS))


def _hops(
    thread: ow.StoreThread,
    *,
    run_id: str,
    generation: int,
    config: Config,
    roots: Roots,
    paths: Sequence[Path],
    scope: str | None,
    clock: Clock,
    sweep_ms: int | None,
    store: Path,
) -> IngestReport:
    now_ns = clock.wall_ns()
    plan_batch = int(config.get("runtime.plan_batch"))  # type: ignore[arg-type]
    sources = sources_of(thread, paths=paths, scope=scope)
    walked = _walk(thread, sources, generation=generation, now_ns=now_ns, plan_batch=plan_batch)
    discover.reset_stale_acquiring(thread)
    acquired = discover.acquire_pending(
        thread, generation=generation, indexed_at_ns=now_ns, plan_batch=plan_batch
    )
    context = _context(run_id, generation, config=config, roots=roots, clock=clock)
    enqueued, unsalted = _enqueue(thread, context, plan_batch=plan_batch)
    drained = (
        asyncio.run(
            _drain(context, thread, config=config, sweep_ms=sweep_ms, host_root=store.parent)
        )
        if enqueued
        else None
    )
    routed = _route(thread, context, config=config, roots=roots, clock=clock)
    states, parts = _tally(thread, generation)
    formats = _formats(thread, generation)
    waiting = states.get(IDENTIFIED, 0) + states.get(PLANNED, 0)
    status = "partial" if waiting or (drained is not None and drained.status != "done") else "ok"
    return IngestReport(
        run_id=run_id,
        generation=generation,
        status=status,
        scopes=sum(1 for one in sources if one.directory),
        files=sum(1 for one in sources if not one.directory),
        discovered=walked[0],
        skipped=walked[1],
        unseen=walked[2],
        acquired=acquired,
        enqueued=enqueued,
        unsalted=unsalted,
        drained=drained,
        states=states,
        parts=parts,
        formats=formats,
        routed=routed,
    )


def _route(
    thread: ow.StoreThread, ctx: RunContext, *, config: Config, roots: Roots, clock: Clock
) -> RouteTally:
    """Hops 5-9 over every unit this generation identified. Startup step 7 runs here, once.

    The catalog, the signal registry and both policies are built per run and frozen into it --
    02:729's *"a driver installed mid-run is invisible until the next run"*.
    """
    from importlib.metadata import distributions  # noqa: PLC0415 -- the routing path only

    from omniweave_core.discovery import catalog as build_catalog  # noqa: PLC0415

    from omniweave.route.evidence import (  # noqa: PLC0415
        build_registry,
        builtin_specs,
        installed_specs,
    )
    from omniweave.route.policy import builtin_layer, compile_policy  # noqa: PLC0415

    registry = build_registry((*builtin_specs(), *installed_specs(distributions()).specs))
    catalog = build_catalog()
    policy = compile_policy([builtin_layer()], registry=registry)
    return route_identified(
        thread,
        ctx=replace(ctx, policy_digest=policy.policy_digest, catalog_digest=catalog.catalog_digest),
        policy=policy,
        registry=registry,
        catalog=catalog,
        resolving=resolve_policy(config),
        source_root=str(roots.source),
        now_ms=clock.wall_ns() // 1_000_000,
    )


def _walk(
    thread: ow.StoreThread,
    sources: Sequence[Source],
    *,
    generation: int,
    now_ns: int,
    plan_batch: int,
) -> tuple[int, int, int]:
    """Hop 2 for every source. Returns `(discovered, skipped, marked unseen)`.

    A directory is `discover.discover()`, resumed from its own cursor while a call ends on
    `max_units_per_call` (05:211), and swept for vanished units only when its scan completed in
    one call -- 05:372-373's *"an **incomplete** scan never marks anything out of scope"*,
    read strictly, because a resumed call's coverage row describes its own segment and not the
    tree.

    A file is its parent walked for its name, with no coverage row (D556), exactly as
    `add_sources()` rosters it.
    """
    discovered = skipped = unseen = 0
    guards = IngestGuards()
    for source in sources:
        if not source.directory:
            tally = Tally()
            parent = str(source.path.parent)
            rows = discover.roster_rows(
                parent,
                Scope(roots=(parent,), include=(_escape(source.path.name),)),
                guards,
                indexed_at_ns=now_ns,
                generation=generation,
                tally=tally,
            )
            write_roster(thread, (row_as_explicit(row) for row in rows), plan_batch=plan_batch)
            discovered += tally.discovered
            skipped += tally.skipped
            continue
        cursor: str | None = None
        calls = 0
        while True:
            report = discover.discover(
                thread,
                source.path,
                Scope(roots=(str(source.path),)),
                guards,
                indexed_at_ns=now_ns,
                generation=generation,
                scanned_at_ns=now_ns,
                cursor=cursor,
                plan_batch=plan_batch,
            )
            calls += 1
            if report.coverage is not None:
                discovered += report.coverage.discovered
                skipped += report.coverage.skipped
            if not report.exhausted_call_bound:
                break
            cursor = report.resume_cursor
        if calls == 1 and report.complete:
            unseen += discover.sweep_unseen(
                thread, scope_id=report.scope_id, generation=generation, complete=True
            )
    return discovered, skipped, unseen


def _escape(name: str) -> str:
    """A file name as a glob that matches only itself: `a[1].pdf` is not a character class."""
    return glob.escape(name)


def row_as_explicit(row: RosterRow) -> RosterRow:
    """A roster row for a file source, marked `explicit` as `add_sources()` marks it."""
    return replace(row, scope_rule="explicit")


def _context(
    run_id: str, generation: int, *, config: Config, roots: Roots, clock: Clock
) -> RunContext:
    """The `RunContext` for hop 4. Four fields are `None`, and the type says each is unread.

    `limits`, `services`, `budget` and `events` are what a parse, a model call, a billed admission
    and a trace would read, and `op.identify` is none of them: it is free, core-only, and its answer
    is a store column (08:861). `admission` is the loop's own and is set by `_drain()`. A plausible
    stub for any of them would claim a coverage this run does not have.
    """
    return RunContext(
        run_id=run_id,
        generation=generation,
        trigger=TRIGGER,  # type: ignore[arg-type]
        roots=roots,
        config_digest=config.config_digest,
        semantic_digest=config.semantic_digest,
        policy_digest="",
        pricebook_digest="",
        catalog_digest="",
        limits=None,  # type: ignore[arg-type]
        admission=None,  # type: ignore[arg-type]
        services=None,  # type: ignore[arg-type]
        budget=None,  # type: ignore[arg-type]
        cancel=CancelToken("run", run_id, clock),
        clock=clock,
        events=None,  # type: ignore[arg-type]
    )


def _enqueue(thread: ow.StoreThread, ctx: RunContext, *, plan_batch: int) -> tuple[int, int]:
    """Hop 4's first half: an `op.identify` row per acquired, uncounted unit. `(written, unkeyed)`.

    The key is `expand.identify_key()` over the salt `discover` stamped (D143). A unit with no
    walked path cannot be keyed and is counted rather than raised: `expand.salt_for()` refuses to
    guess, correctly, and one such unit must not end a corpus. Only a store written by W7.3v's
    `ow_add` holds one (D559), and `UNIT_UPSERT_SQL` never refreshes `derived`, so it stays unkeyed.
    """
    written = unsalted = 0
    source = str(ctx.roots.source)
    after = ""
    while True:
        rows = cast(
            "list[tuple[str, str | None, int | None, str | None, str | None, str]]",
            _read(
                thread,
                "ingest.pending_identify",
                lambda c, a=after: _pending(c, ctx, a, plan_batch),
            ),
        )
        if not rows:
            return written, unsalted
        after = rows[-1][0]
        params: list[Mapping[str, object]] = []
        for uri, digest, size, media, _fmt, derived in rows:
            try:
                salt = expand.salt_for(json.loads(derived or "{}"), source_root=source)
            except RouteError:
                unsalted += 1
                continue
            unit = expand.counted(uri, digest or "", size or 0, media or "")
            params.append(expand.row_params(uri, expand.identify_key(unit, ctx, salt=salt)))
        count, _paused = expand.enqueue(thread, params, plan_batch=plan_batch)
        written += count


_PENDING_AFTER_SQL: Final[str] = expand.PENDING_IDENTIFY_SQL.replace(
    " ORDER BY u.unit_uri", "   AND u.unit_uri > :after\n ORDER BY u.unit_uri"
)
"""`PENDING_IDENTIFY_SQL` resumed past a key, for `discover.PENDING_ACQUISITION_AFTER_SQL`'s reason:
an unkeyable unit stays pending and would come back first in every page."""


def _pending(connection: object, ctx: RunContext, after: str, limit: int) -> object:
    values = {**expand.pending_params(generation=ctx.generation, limit=limit), "after": after}
    return connection.execute(_PENDING_AFTER_SQL, values).fetchall()  # type: ignore[attr-defined]


def _tally(thread: ow.StoreThread, generation: int) -> tuple[dict[str, int], int]:
    rows = cast(
        "list[tuple[str, int, int]]",
        _read(
            thread,
            "ingest.tally",
            lambda c: c.execute(_TALLY_SQL, {"generation": generation}).fetchall(),  # type: ignore[attr-defined]
        ),
    )
    states = {str(state): int(count) for state, count, _ in rows}
    parts = sum(int(total) for state, _, total in rows if state == IDENTIFIED)
    return states, parts


def _formats(thread: ow.StoreThread, generation: int) -> dict[str, int]:
    """`unit.format` over this generation's walk: what the ladder decided, from the table."""
    rows = cast(
        "list[tuple[str, int]]",
        _read(
            thread,
            "ingest.formats",
            lambda c: c.execute(_FORMATS_SQL, {"generation": generation}).fetchall(),  # type: ignore[attr-defined]
        ),
    )
    return {str(token): int(count) for token, count in rows}


# =============================================================================================
# Hop 4's second half: the Supervisor, with `op.identify` as its dispatcher
# =============================================================================================


class NoExecutorError(RuntimeError):
    """A claimed row whose operator this build cannot run: every routed `parse.*` row. D578.

    Raised inside the dispatcher, so `Supervisor._crash()` takes it: the row stays claimed, the
    reaper returns it at `lease_ms` with its attempt decremented (08:130-131), and `run.degraded`
    names it. The claim cannot be narrowed to `op.*` rows -- `Store.claim()` is four parameters and
    names no operator -- and every other answer would write something false: `failed` burns the
    unit's attempts on a driver that never ran, and `CANCELLED` puts it straight back in the
    claimable set for the same claimer to take again. Only a run that has `op.identify` rows to
    drain opens the loop at all, so a corpus with nothing new to identify never claims one.
    """

    def __init__(self, operator: str, driver: str | None) -> None:
        super().__init__(f"no executor for {operator} ({driver}): hops 10-17 are not built")


class _Identify:
    """The `Dispatcher` for `op.identify` rows: read the unit, count it, remember the answer.

    Runs in a worker thread (`Supervisor._serve`'s `asyncio.to_thread`), which is why it reads the
    unit through the store thread and not through a connection of its own (INV-17). A `NULL`
    `dispatch_key` batches alone (08:755), so a batch is one row; the loop over rows is for the
    `Dispatcher` contract, which answers for every row it was given (I24).
    """

    __slots__ = ("_ledger", "_thread")

    def __init__(self, thread: ow.StoreThread, ledger: expand.IdentifyLedger) -> None:
        self._thread = thread
        self._ledger = ledger

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]:
        out: list[StepResult] = []
        for row in batch.rows:
            if row.operator != expand.OP_IDENTIFY:
                raise NoExecutorError(row.operator, row.driver)
            unit = self._unit(row)
            detected, refused = _detected(row.unit_uri)
            count = expand.single_part if refused is None else _refusing(refused)
            result, answer = expand.identify(
                unit,
                count=count,
                cache_key_hex=row.cache_key,
                fmt="" if detected is None else detected.format,
            )
            self._ledger.record(row.id, row.unit_uri, answer, _columns(detected))
            out.append(result)
        return out

    def _unit(self, row: WorkRow) -> UnitRef:
        found = _read(
            self._thread,
            "ingest.identify.unit",
            lambda c: c.execute(_UNIT_SQL, (row.unit_uri,)).fetchone(),  # type: ignore[attr-defined]
        )
        if found is None or not cast("tuple[object, ...]", found)[0]:
            raise RouteError(
                f"work row {row.id} names {row.unit_uri!r}, which has no acquired digest; an "
                f"op.identify row is only ever enqueued for an acquired unit",
                fix="ow ingest again: the lease reaper returns the row",
            )
        digest, size, media = cast("tuple[str, int | None, str | None]", found)
        return expand.counted(row.unit_uri, digest, size or 0, media or "")


def _detected(unit_uri: str) -> tuple[Detection | None, DriverError | None]:
    """05 section 2's ladder over the unit's file: `(detection, None)` or `(None, the refusal)`.

    An `fs` unit's uri is its file (05 section 1.2). A file gone since acquisition
    fails as `corrupt_input`, which is what `discover._unreadable` calls
    the same fact; a container identity that breaks 05:748's bound is the ladder's own refusal.
    """
    try:
        return detect(Path(unit_uri)), None
    except DriverError as refused:
        return None, refused
    except OSError as gone:
        return None, DriverError(
            cls=FailureClass.CORRUPT_INPUT, message=f"the file is unreadable at identify: {gone}"
        )


def _refusing(refused: DriverError) -> expand.PartCounter:
    """A counter that answers with the ladder's refusal, so `expand.identify()` fails the unit with
    its class exactly as it fails one whose counter refused -- one failure path, not two."""

    def count(unit: UnitRef, *, fmt: str) -> expand.PartCount:
        del unit, fmt
        raise refused

    return count


def _columns(detected: Detection | None) -> dict[str, object] | None:
    """The three columns `IDENTIFIED_SQL` writes from a detection, or none for a refusal."""
    if detected is None:
        return None
    return {
        "format": detected.format,
        "media_type": detected.media_type,
        "format_evidence": detected.evidence_json(),
    }


class _Forgetting:
    """`SqliteStore` with `IdentifyLedger.forget()` after every commit that stuck.

    `IdentifyLedger`'s docstring leaves the call to the caller -- *"`forget()` is the caller's
    acknowledgement that the commit stuck"* -- and the caller of `complete()` is the Supervisor,
    which knows no ledger. So the queue it is handed forgets on its behalf, and only on `True`: a
    superseded commit rolled back, and its entry is what a retry would need.
    """

    __slots__ = ("_inner", "_ledger")

    def __init__(self, inner: SqliteStore, ledger: expand.IdentifyLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:
        return self._inner.claim(batch, gen, worker, lease_ms)

    def complete(self, row_id: int, gen: int, result: StepResultView) -> bool:
        committed = self._inner.complete(row_id, gen, result)
        if committed:
            self._ledger.forget(row_id)
        return committed

    def reap_expired_leases(self, now_ms: int) -> int:
        return self._inner.reap_expired_leases(now_ms)

    def counts_by_status(self) -> Mapping[str, int]:
        return self._inner.counts_by_status()


async def _drain(
    ctx: RunContext,
    thread: ow.StoreThread,
    *,
    config: Config,
    sweep_ms: int | None,
    host_root: Path,
) -> sup.RunReport:
    """Startup step 9: the one loop, draining the `op.identify` rows hop 4 wrote.

    The admission is derived inside the loop because its semaphores are `asyncio` objects, and a
    semaphore created outside the loop that awaits it is one Python 3.10 bound to the wrong one.
    """
    admission = sup.derive_admission(config, sup.HostFacts.measure(host_root))
    shipped = sup.LoopTimings.of(config)
    timings = (
        shipped
        if sweep_ms is None
        else sup.LoopTimings(
            lease_ms=shipped.lease_ms,
            lease_extend_ms=shipped.lease_extend_ms,
            stall_poll_ms=shipped.stall_poll_ms,
            deferred_sweep_ms=sweep_ms,
            shutdown_grace_ms=shipped.shutdown_grace_ms,
            loop_lag_max_ms=shipped.loop_lag_max_ms,
        )
    )
    ledger = expand.IdentifyLedger()
    queue = _Forgetting(SqliteStore(thread, wait_ms=BATCH_WAIT_MS, derived_rows=ledger), ledger)
    loop_ctx = _with_admission(ctx, admission)
    supervisor = sup.Supervisor(
        loop_ctx,
        queue=queue,  # type: ignore[arg-type]
        dispatch=_Identify(thread, ledger),
        admission=admission,
        timings=timings,
        worker=sup.worker_identity(),
        claim_batch=sup.claim_batch_of(config),
    )
    return await supervisor.run()


def _with_admission(ctx: RunContext, admission: sup.Admission) -> RunContext:
    return replace(ctx, admission=admission)  # type: ignore[arg-type]
