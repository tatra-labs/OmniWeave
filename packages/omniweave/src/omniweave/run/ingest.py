"""`ow ingest`: the drain every `ow_add` and every `PostToolUse` hook waits on, as far as it goes.

02-architecture.md section 4.1 traces one born-digital PDF through nineteen hops. This module runs
them in order, and every hop but 18 is built:

- **hop 1**, one `run` row with a monotonic `generation` and `status='running'`: `open_run()`;
- **hop 2**, `run/discover` rostering at `plan_batch` with one `ingest_scope` row: `discover()` per
  scope, and a file source as a roster row with no scope row (D556);
- **hop 3**, the stat triple, the digest and `unit.state='acquired'`: `acquire_pending()`;
- **hop 4**, `op.identify`'s `work` row and then `part_count` and `state='identified'`:
  `expand.enqueue()`, then **the Supervisor** draining it;
- **hops 5-9**, resolve, evidence, `evaluate()`, `admit()` and the plan's `INSERT`:
  `run.routing.route_identified()` (W7.3y);
- **hops 10-17**, dispatch, the pipeline, S4, the driver, `DocSink` and `complete()`: the parse
  Operator, drained by the same Supervisor (W7.3z);
- **hop 18**, the seven free `derive/1` passes: **not built**, so no Segment exists and the
  receipt's `n_segments` column is 0 on every line;
- **hop 19**, `omniweave.run.manifest` and `omniweave.index.lock`: `_Book` and `_receipt()`,
  below.

A unit a hop could not take further ends the run where it stopped, and **the run says so**:
`status = 'partial'`, and the report's second-last line names where. A run that exited 0 printing
`ok` over a corpus that `ow_query` still cannot cite would be the defect INV-20 names -- a front
door that lies.

## HOP 19: THE MANIFEST, THE RECEIPT, AND THE GENERATION A QUERY READS

**The manifest** is `{output_root}/runs/{run_id}.json` (02:489), and `run.manifest_path` names it
from the run's first statement. It is written when the run opens, at each of the three Stage
boundaries this run crosses (15 section 2.2: `discover` is hops 2-3, `plan` is hops 4-9, `parse` is
hops 10-17), and when it closes -- 15:68's *"so a killed run has one"*. Its outcome counts come from
the commits that stuck, counted where `complete()` returns `True`.

**The receipt** is `omniweave.index.lock` at the corpus's source root, beside `.omniweave/`
(07:131-142), derived by `store.verify.derive_lock()` -- the function `ow store verify --lock`
compares against, so the two cannot disagree by construction. Its uris are relative to the source
root (D591), and the walk never rosters it (D592).

**`index_state.generation` moves when the receipt's rows move** (D594). 07:2920 makes it *"the
monotonic run counter"* and gate 3 compares it across a snapshot, and 08:1623 makes the bump
*"the last step of the refresh loop"*. The receipt is exactly the corpus a query sees -- one line
per document, its generation, status, block count and root digest -- so a run whose derived rows
equal the committed ones changed nothing a reader can see, and bumping would announce a refresh
that did not happen. When they differ, the bump rides in the transaction that closes the run
(08:1610's *"inside the completing transaction"*), and the file is replaced after it commits: a
crash between the two leaves the old file, whose rows still differ, so the next run bumps again. An
extra bump is harmless; a missed one would hide a change from gate 3.

A run that fails writes a `failed` manifest and neither the receipt nor the bump: it did not reach
the last step of the loop, and the next run's comparison sees whatever it did commit.

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

## WHAT THE RUN ROW CARRIES, AND THE ONE COLUMN NOTHING PRODUCES YET

`config_digest` and `semantic_digest` are the loaded `Config`'s. `policy_digest` is the built-in
route policy's, compiled here, because startup step 4 freezes one and no project policy loader is
wired. `manifest_path` is the manifest's, known from the `run_id`. `lock_digest` is the sha256 of
the receipt as it stands when the run closes, or the empty string while no receipt exists (D593).
`pricebook_digest` is still the empty string: no `PriceBook` is loaded because nothing here is
priced, and D562 records why an empty string rather than an invented digest.

Specified in 02-architecture.md sections 4.1 and 5.3-5.4, 05-ingest-and-routing.md sections 1.2
and 3, 08-runtime.md sections 1.2, 2.5 and 5.1-5.2, and 10-interfaces.md sections 6.4 and 8.6.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import hashlib
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
from omniweave_core.events import Stage
from omniweave_core.locks import BATCH_WAIT_MS, store_write_lock
from omniweave_core.operator import (
    ULID_ENTROPY_BYTES,
    CancelToken,
    Outcome,
    Roots,
    RunContext,
    new_run_id,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.indexlock import LOCK_PATH, LockHeader, read_lock
from omniweave_core.store.queue import SqliteStore
from omniweave_ports.types import DriverError, FailureClass

from omniweave.route.detect import Detection, detect
from omniweave.run import discover, expand
from omniweave.run import supervisor as sup
from omniweave.run.manifest import (
    TEMP_SUFFIX,
    ManifestWriter,
    Provenance,
    RunTally,
    manifest_path,
)
from omniweave.run.operators.parse import ParseLedger, ParseOperator, ParseTally, is_parse
from omniweave.run.routing import RouteTally, resolve_policy, route_identified

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.clock import Clock
    from omniweave_core.config import Config
    from omniweave_core.drivers.catalog import Catalog
    from omniweave_core.drivers.resolve import Policy
    from omniweave_core.operator import StepResult
    from omniweave_core.store.indexlock import LockFile, LockRow
    from omniweave_core.store.queue import Statement, StepResultView
    from omniweave_core.work import WorkRow
    from omniweave_ports.types import UnitRef

    from omniweave.route.evidence import SignalRegistry
    from omniweave.route.policy import RoutePolicy
    from omniweave.run.dispatch import Batch
    from omniweave.run.manifest import RunStatus, Timings

__all__ = [
    "GENERATION_BUMP_SQL",
    "IDENTIFIED",
    "NO_SEGMENTER",
    "NO_SPACE",
    "PLANNED",
    "RUN_CLOSE_SQL",
    "RUN_INSERT_SQL",
    "SETTLED",
    "STOPPED_AT",
    "TRIGGER",
    "UNROUTED",
    "IngestReport",
    "NoExecutorError",
    "OpenedRun",
    "Receipt",
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
    "planned and not parsed by this run: its row is retrying, or it was granted inproc and the S1 "
    "host is not built (see the parse lines above)"
)
"""Why a planned unit is still planned when the run ends. Hops 10-17 run since W7.3z; a unit left
here is one whose row did not reach `done` or `failed` this run."""

SETTLED: Final[str] = "settled"
"""05:404's terminal success: *"every part terminal; doc.status in ok|partial"*."""

UNROUTED: Final[str] = "routed to no driver (see the route lines above)"
"""Why an identified unit went no further: `run.routing` named a rule and no candidate served it."""

RUN_INSERT_SQL: Final[str] = """
INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest, policy_digest,
                pricebook_digest, lock_digest, omniweave_version, contract, schema, started_ns,
                status, manifest_path)
SELECT :run_id, COALESCE(MAX(generation), 0) + 1, :trigger, :argv, :config_digest,
       :semantic_digest, :policy_digest, '', '', :version, :contract, :schema, :started_ns,
       'running', :manifest_path
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
    "UPDATE run SET status = :status, ended_ns = :ended_ns, lock_digest = :lock_digest "
    "WHERE run_id = :id"
)
"""The run row's last write. `lock_digest` is the receipt's as the run leaves it (D593)."""

GENERATION_BUMP_SQL: Final[str] = """
UPDATE index_state SET v = :value
 WHERE k = 'generation' AND CAST(v AS INTEGER) < :generation
"""
"""08:1610's *"one UPDATE, inside the completing transaction"*: `index_state.generation` becomes
this run's `run.generation`, which 07:2920 makes the same counter.

The guard keeps it monotonic without a read: `run.generation` is minted under `BEGIN IMMEDIATE`
and only grows, so the only way the stored value could be at or above this run's is a later run
having closed first, and a counter that moved backwards would make gate 3 compare two snapshots as
the same corpus. `v` is `TEXT` (0003_index.sql:406), hence the cast on the read side and a string
on the write side."""

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


NO_SEGMENTER: Final[str] = "none"
NO_SPACE: Final[str] = "none"
"""The receipt header's `segmenter` and `space` tokens in a build that has neither (D595).

07:3117 prints `segmenter=derive.segment.spine@3:9c1e space=bge-m3@a1b2c3/768/cosine/i8`: the
segmenter's identity and the embedding space's. Hop 18 is not built, so no Segment was ever cut,
and no `embed/1` driver ships, so there is no space. `none` says exactly that, is a token
`LockHeader.validate` accepts, and cannot be mistaken for an identity -- which an invented one
could. The header is where 07:3130 catches *"two corpora indexed by different scorers"*; the
first build that segments or embeds changes these two words, and the merge driver then refuses to
merge a receipt from before it, which is the refusal the header exists for."""


@dataclass(frozen=True, slots=True)
class Receipt:
    """What hop 19 did with `omniweave.index.lock`.

    `changed` is the fact the generation bump keys on: the derived ROWS differ from the rows on
    disk. `written` is whether the file's bytes were replaced, which can differ from `changed` in
    one direction only -- a header-only difference rewrites the file without changing a row.
    """

    path: Path
    documents: int
    changed: bool
    written: bool
    digest: str

    def line(self, generation: int) -> str:
        if not self.digest:
            return "  receipt   none: no document is committed"
        state = "written" if self.written else "unchanged"
        moved = f"generation {generation}" if self.changed else "generation not moved"
        return f"  receipt   {LOCK_PATH} {state}, {self.documents} documents, {moved}"


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
    parsed: ParseTally | None = None
    manifest: str = ""
    receipt: Receipt | None = None

    @property
    def settled(self) -> int:
        return self.states.get(SETTLED, 0)

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
        if self.parsed is not None:
            out.extend(self.parsed.lines())
        if self.manifest:
            out.append(f"  manifest  {self.manifest}")
        if self.receipt is not None:
            out.append(self.receipt.line(self.generation))
        if self.settled:
            out.append(f"  settled   {self.settled} units have a committed document")
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
    host = sup.HostFacts.measure(store.parent)
    lock = store_write_lock(store, now_ns=ticking.wall_ns)
    with ow.StoreThread(lambda: ow.connect(store), lock=lock) as thread:
        opened = open_run(thread, config=config, argv=argv, clock=ticking, output_root=output_root)
        book = _Book(opened, config=config, host=host, clock=ticking)
        book.write()
        try:
            report = _hops(
                thread,
                run_id=opened.run_id,
                generation=opened.generation,
                config=config,
                roots=Roots(source=source_root, output=output_root, cache=cache_root),
                paths=paths,
                scope=scope,
                clock=ticking,
                sweep_ms=sweep_ms,
                store=store,
                book=book,
                host=host,
            )
            pending = _receipt(thread, source_root=source_root)
        except BaseException:
            ended = ticking.wall_ns()
            close_run(thread, opened.run_id, status="failed", ended_ns=ended)
            with contextlib.suppress(OSError):
                book.write(status="failed", ended_ns=ended)
            raise
        receipt = pending.receipt
        ended = ticking.wall_ns()
        close_run(
            thread,
            opened.run_id,
            status=report.status,
            ended_ns=ended,
            lock_digest=receipt.digest,
            generation=opened.generation if receipt.changed else None,
        )
        try:
            if receipt.written:
                _replace(receipt.path, pending.text)
        finally:
            book.write(
                status=cast("RunStatus", report.status), ended_ns=ended, lock_digest=receipt.digest
            )
    return replace(report, manifest=book.path, receipt=receipt)


def _create(store: Path, *, now_ns: int) -> None:
    """A store that does not exist yet, created and migrated. `add_sources()`'s own first step."""
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = ow.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=now_ns)
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class OpenedRun:
    """What hop 1 wrote: the ids, the start, and the provenance the manifest repeats (15:1568)."""

    run_id: str
    generation: int
    started_ns: int
    provenance: Provenance
    manifest: Path | None


def open_run(
    thread: ow.StoreThread,
    *,
    config: Config,
    argv: Sequence[str],
    clock: Clock,
    output_root: Path | None = None,
) -> OpenedRun:
    """Hop 1. The `run` row, `status = 'running'`, and the generation it minted.

    `output_root` places the manifest, whose path the row records from its first statement: a run
    killed before it closes still names the file that says how far it got. With none, the column is
    the empty string and no manifest is kept.
    """
    from omniweave.route.policy import builtin_layer, compile_policy  # noqa: PLC0415

    run_id = new_run_id(clock, os.urandom(ULID_ENTROPY_BYTES))
    manifest = None if output_root is None else manifest_path(output_root, run_id)
    started_ns = clock.wall_ns()
    params = {
        "run_id": run_id,
        "trigger": TRIGGER,
        "argv": json.dumps(list(argv), separators=(",", ":")),
        "config_digest": config.config_digest,
        "semantic_digest": config.semantic_digest,
        "policy_digest": compile_policy([builtin_layer()]).policy_digest,
        "version": metadata.version("omniweave"),
        "contract": CONTRACT,
        "started_ns": started_ns,
        "manifest_path": "" if manifest is None else str(manifest),
    }

    def run(connection: object) -> object:
        schema = connection.execute(  # type: ignore[attr-defined]
            "SELECT v FROM index_state WHERE k = 'schema'"
        ).fetchone()
        major = int(str(schema[0]).split(".", 1)[0]) if schema else 0
        row = connection.execute(RUN_INSERT_SQL, {**params, "schema": major}).fetchone()  # type: ignore[attr-defined]
        return int(row[0]), major

    generation, major = cast(
        "tuple[int, int]",
        thread.run(ow.Unit(name="ingest.run", run=run, cost_class="free", wait_ms=BATCH_WAIT_MS)),
    )
    provenance = Provenance(
        omniweave_version=str(params["version"]),
        contract=CONTRACT,
        schema=major,
        config_digest=config.config_digest,
        semantic_digest=config.semantic_digest,
        policy_digest=str(params["policy_digest"]),
    )
    return OpenedRun(run_id, generation, started_ns, provenance, manifest)


def close_run(
    thread: ow.StoreThread,
    run_id: str,
    *,
    status: str,
    ended_ns: int,
    lock_digest: str = "",
    generation: int | None = None,
) -> None:
    """The run row's last write -- its status, its end and its receipt digest -- and, when
    `generation` is given, `index_state.generation` moved to it in the same transaction."""

    def run(connection: object) -> None:
        connection.execute(  # type: ignore[attr-defined]
            RUN_CLOSE_SQL,
            {"status": status, "ended_ns": ended_ns, "lock_digest": lock_digest, "id": run_id},
        )
        if generation is not None:
            connection.execute(  # type: ignore[attr-defined]
                GENERATION_BUMP_SQL, {"value": str(generation), "generation": generation}
            )

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
    book: _Book,
    host: sup.HostFacts,
) -> IngestReport:
    now_ns = clock.wall_ns()
    plan_batch = int(config.get("runtime.plan_batch"))  # type: ignore[arg-type]
    opened = clock.monotonic_ns()
    sources = sources_of(thread, paths=paths, scope=scope)
    walked = _walk(thread, sources, generation=generation, now_ns=now_ns, plan_batch=plan_batch)
    discover.reset_stale_acquiring(thread)
    acquired = discover.acquire_pending(
        thread, generation=generation, indexed_at_ns=now_ns, plan_batch=plan_batch
    )
    opened = book.stage(Stage.DISCOVER, opened)
    context = _context(run_id, generation, config=config, roots=roots, clock=clock)
    enqueued, unsalted = _enqueue(thread, context, plan_batch=plan_batch)
    inputs = _routing_inputs(config)
    book.catalog(inputs.catalog.catalog_digest)
    context = replace(
        context,
        policy_digest=inputs.policy.policy_digest,
        catalog_digest=inputs.catalog.catalog_digest,
    )
    tally = ParseTally()
    executor = _Executors(thread, context, config=config, inputs=inputs, store=store, tally=tally)

    def drain() -> sup.RunReport:
        return asyncio.run(
            _drain(
                context,
                thread,
                config=config,
                sweep_ms=sweep_ms,
                host=host,
                executors=executor,
                tally=book.tally,
            )
        )

    try:
        drained = drain() if enqueued else None
        routed = _route(thread, context, inputs=inputs, roots=roots, clock=clock)
        opened = book.stage(Stage.PLAN, opened)
        if _pending_parse(thread):
            drain()
            book.stage(Stage.PARSE, opened)
    finally:
        executor.close()
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
        parsed=tally if (tally.parsed or tally.failed) else None,
    )


@dataclass(frozen=True, slots=True)
class _RoutingInputs:
    """Startup step 7's four products, built once and frozen for the run -- 02:729's *"a driver
    installed mid-run is invisible until the next run"*. Routing reads all four; the parse
    Operator reads the catalog and the resolve policy, so the card it runs is the card that was
    routed and the config digest it recomputes is the one the row's `dispatch_key` was minted
    over."""

    registry: SignalRegistry
    catalog: Catalog
    policy: RoutePolicy
    resolving: Policy


def _routing_inputs(config: Config) -> _RoutingInputs:
    from importlib.metadata import distributions  # noqa: PLC0415 -- the routing path only

    from omniweave_core.discovery import catalog as build_catalog  # noqa: PLC0415

    from omniweave.route.evidence import (  # noqa: PLC0415
        build_registry,
        builtin_specs,
        installed_specs,
    )
    from omniweave.route.policy import builtin_layer, compile_policy  # noqa: PLC0415

    registry = build_registry((*builtin_specs(), *installed_specs(distributions()).specs))
    return _RoutingInputs(
        registry=registry,
        catalog=build_catalog(),
        policy=compile_policy([builtin_layer()], registry=registry),
        resolving=resolve_policy(config),
    )


def _route(
    thread: ow.StoreThread,
    ctx: RunContext,
    *,
    inputs: _RoutingInputs,
    roots: Roots,
    clock: Clock,
) -> RouteTally:
    """Hops 5-9 over every unit this generation identified."""
    return route_identified(
        thread,
        ctx=ctx,
        policy=inputs.policy,
        registry=inputs.registry,
        catalog=inputs.catalog,
        resolving=inputs.resolving,
        source_root=str(roots.source),
        now_ms=clock.wall_ns() // 1_000_000,
    )


_PENDING_PARSE_SQL: Final[str] = (
    "SELECT 1 FROM work WHERE status = 'pending' AND operator LIKE 'parse.%' LIMIT 1"
)


def _pending_parse(thread: ow.StoreThread) -> bool:
    """Whether hop 9 left anything for hops 10-17. A run with nothing planned opens no loop."""
    found = _read(
        thread,
        "ingest.pending_parse",
        lambda c: c.execute(_PENDING_PARSE_SQL).fetchone(),  # type: ignore[attr-defined]
    )
    return found is not None


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


class _Executors:
    """The one `Dispatcher` a drain is handed: `op.identify` to `_Identify`, `parse.*` to the
    parse Operator, anything else to `NoExecutorError` (D578). A batch is one `dispatch_key`, so it
    is one operator family, and the first row names it.

    It also carries the two ledgers' `derived_rows` contribution and their `forget()`, because
    `SqliteStore` takes ONE contribution per participant and each ledger answers only for the rows
    it recorded -- `IdentifyLedger`'s docstring: *"the map is the dispatch"*.
    """

    __slots__ = ("_identify", "_identify_ledger", "_parse", "_parse_ledger")

    def __init__(
        self,
        thread: ow.StoreThread,
        ctx: RunContext,
        *,
        config: Config,
        inputs: _RoutingInputs,
        store: Path,
        tally: ParseTally,
    ) -> None:
        self._identify_ledger = expand.IdentifyLedger()
        self._parse_ledger = ParseLedger()
        self._identify = _Identify(thread, self._identify_ledger)
        self._parse = _ParseLazily(thread, ctx, config, inputs, store, self._parse_ledger, tally)

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]:
        operator = batch.rows[0].operator
        if operator == expand.OP_IDENTIFY:
            return self._identify(batch)
        if is_parse(operator):
            return self._parse.get()(batch)
        raise NoExecutorError(operator, batch.driver)

    def contribution(self, row_id: int, result: StepResultView) -> Sequence[Statement]:
        return (*self._identify_ledger(row_id, result), *self._parse_ledger(row_id, result))

    def forget(self, row_id: int) -> None:
        self._identify_ledger.forget(row_id)
        self._parse_ledger.forget(row_id)

    def close(self) -> None:
        self._parse.close()


class _ParseLazily:
    """The parse Operator, built on its first batch. A run that plans nothing opens no CAS and
    builds no worker pool, so `ow ingest` over a text-only corpus costs what it did before."""

    __slots__ = ("_args", "_operator")

    def __init__(self, *args: object) -> None:
        self._args = args
        self._operator: ParseOperator | None = None

    def get(self) -> ParseOperator:
        if self._operator is None:
            thread, ctx, config, inputs, store, ledger, tally = self._args
            cas_root = Path(cast("Path", store)).parent / CAS_DIR
            cas_root.mkdir(parents=True, exist_ok=True)
            from omniweave_core.blobs import BlobStore  # noqa: PLC0415 -- the parse path only

            self._operator = ParseOperator(
                thread,  # type: ignore[arg-type]
                ctx=ctx,  # type: ignore[arg-type]
                config=config,  # type: ignore[arg-type]
                catalog=cast("_RoutingInputs", inputs).catalog,
                resolving=cast("_RoutingInputs", inputs).resolving,
                cas=BlobStore(cas_root),
                ledger=ledger,  # type: ignore[arg-type]
                tally=tally,  # type: ignore[arg-type]
            )
        return self._operator

    def close(self) -> None:
        if self._operator is not None:
            self._operator.close()


CAS_DIR: Final[str] = "cas"
"""The CAS directory, beside the store: 07:905 and 03:2088 put it at `.omniweave/cas/`, and
`store/portable.py` calls it *"a directory beside the store"*. 08:2542 prints
`roots.cache/cas/...`; the two are not the same path under the shipped `roots.cache =
".omniweave/cache"`, and the store documents win because the CAS is what `asset.store_ref` and
`part.store_ref` point into, which is the store's contract (D582)."""


class _Forgetting:
    """`SqliteStore` with each ledger's `forget()` after every commit that stuck.

    `IdentifyLedger`'s docstring leaves the call to the caller -- *"`forget()` is the caller's
    acknowledgement that the commit stuck"* -- and the caller of `complete()` is the Supervisor,
    which knows no ledger. So the queue it is handed forgets on its behalf, and only on `True`: a
    superseded commit rolled back, and its entry is what a retry would need.
    """

    __slots__ = ("_inner", "_ledger", "_tally")

    def __init__(
        self, inner: SqliteStore, ledger: _Executors, tally: RunTally | None = None
    ) -> None:
        self._inner = inner
        self._ledger = ledger
        self._tally = tally

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]:
        return self._inner.claim(batch, gen, worker, lease_ms)

    def complete(self, row_id: int, gen: int, result: StepResultView) -> bool:
        """`complete()`, then the ledger's `forget()` and the manifest's count -- both only on a
        commit that stuck, because a superseded one rolled back and settled nothing."""
        committed = self._inner.complete(row_id, gen, result)
        if committed:
            self._ledger.forget(row_id)
            if self._tally is not None:
                _settled(self._tally, result)
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
    host: sup.HostFacts,
    executors: _Executors,
    tally: RunTally | None = None,
) -> sup.RunReport:
    """Startup step 9: the one loop, draining whatever is claimable -- `op.identify` rows before
    routing, `parse.*` rows after it. One dispatcher serves both (`_Executors`), because a claim
    names no operator and a row from an earlier run may be either.

    The admission is derived inside the loop because its semaphores are `asyncio` objects, and a
    semaphore created outside the loop that awaits it is one Python 3.10 bound to the wrong one.
    `host` is measured once per run rather than once per drain: 08:661's *"measured ONCE at
    preflight and recorded in the run manifest"*, and two drains that measured twice could admit
    against two machines while the manifest recorded one.
    """
    admission = sup.derive_admission(config, host)
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
    queue = _Forgetting(
        SqliteStore(thread, wait_ms=BATCH_WAIT_MS, derived_rows=executors.contribution),
        executors,
        tally,
    )
    loop_ctx = _with_admission(ctx, admission)
    supervisor = sup.Supervisor(
        loop_ctx,
        queue=queue,  # type: ignore[arg-type]
        dispatch=executors,
        admission=admission,
        timings=timings,
        worker=sup.worker_identity(),
        claim_batch=sup.claim_batch_of(config),
    )
    return await supervisor.run()


def _with_admission(ctx: RunContext, admission: sup.Admission) -> RunContext:
    return replace(ctx, admission=admission)  # type: ignore[arg-type]


# =============================================================================================
# Hop 19: the manifest and the receipt
# =============================================================================================


class _Book:
    """Hop 19's manifest half: the run's frozen facts, its `RunTally`, and its writer.

    One per run, held by the process that holds `store.write` -- 15:69's *"one writer process holds
    the `store.write` lock, so one manifest has one author"*. `RunTally` counts and `ManifestWriter`
    replaces the file atomically; this class is only where the two meet the run, and it writes at
    the four moments the module docstring names.

    **What this run leaves at zero, and why each zero is true rather than unmeasured.** `cost` is
    zero because nothing this build runs is priced (D562). `cache` is zero because no Operator here
    probes the cache: `op.identify` answers from a store column and the parse Operator stages
    bytes without a verdict. `observe` is empty because the run opens no event sink. Each block
    fills when its producer runs, through the `RunTally` method already waiting for it.
    """

    __slots__ = ("_clock", "_host", "_opened", "_provenance", "_timings", "_writer", "tally")

    def __init__(
        self, opened: OpenedRun, *, config: Config, host: sup.HostFacts, clock: Clock
    ) -> None:
        self._opened = opened
        self._provenance = opened.provenance
        self._host = host
        self._clock = clock
        self._timings: Timings = cast("Timings", str(config.get("observe.timings")))
        self._writer = (
            None if opened.manifest is None else ManifestWriter(opened.manifest, clock=clock)
        )
        self.tally = RunTally()

    @property
    def path(self) -> str:
        """The manifest's path, or the empty string for a run that keeps none."""
        return "" if self._writer is None else str(self._writer.path)

    def stage(self, stage: Stage, opened_ns: int) -> int:
        """Close one Stage opened at the monotonic `opened_ns`, rewrite the file, and return the
        reading that opens the next -- so two Stages share a boundary and no time falls between
        them."""
        now = self._clock.monotonic_ns()
        self.tally.stage_closed(stage, (now - opened_ns) // _NS_PER_MS)
        self.write()
        return now

    def catalog(self, digest: str) -> None:
        """Startup step 7's catalog digest. D140: no `run` column holds it, so the manifest is the
        only durable place it reaches."""
        self._provenance = replace(self._provenance, catalog_digest=digest)

    def write(
        self, *, status: RunStatus = "running", ended_ns: int | None = None, lock_digest: str = ""
    ) -> None:
        if self._writer is None:
            return
        if lock_digest:
            self._provenance = replace(self._provenance, lock_digest=lock_digest)
        opened = self._opened
        self._writer.write(
            self.tally.snapshot(
                run_id=opened.run_id,
                generation=opened.generation,
                trigger=TRIGGER,
                status=status,
                started_ns=opened.started_ns,
                ended_ns=ended_ns,
                provenance=self._provenance,
                host=self._host,
                timings=self._timings,
            )
        )


_NS_PER_MS: Final[int] = 1_000_000


def _settled(tally: RunTally, result: StepResultView) -> None:
    """One committed transition, in `RunTally`'s vocabulary. `deferred_dim` is read off the result
    when it has one: `StepResult` carries it and the store's read surface does not name it."""
    failure = result.failure_class
    tally.settled(
        Outcome(result.outcome),
        failure_class=None if failure is None else FailureClass(failure),
        deferred_dim=cast("str | None", getattr(result, "deferred_dim", None)),
    )


@dataclass(frozen=True, slots=True)
class _PendingReceipt:
    """A `Receipt` and the text it would write, held between the derivation and the commit."""

    receipt: Receipt
    text: str


def _receipt(thread: ow.StoreThread, *, source_root: Path) -> _PendingReceipt:
    """Hop 19's receipt half: the lock the store implies, against the one on disk. Writes nothing.

    The rows are `store.verify.derive_lock()`'s, over the uri root `acquire.scope_id_for()` gives
    the source root -- the spelling a scope row uses, trailing `/` and all -- so the receipt is
    what `ow store verify --lock` re-derives when it is handed the same root. Imported at function
    scope for `inspect.lock_rows`'s reason: `verify.py` pulls in the archive and identity layers,
    and a run that settles nothing should not pay for them before it gets here.

    The comparison is over ROWS, because the bump keys on what a reader sees (the module docstring,
    and D594). A file that is missing reads as no rows; a file that does not parse -- a merge left
    conflict markers in it, or a hand edit broke a column -- reads as changed, since nothing it says
    can be trusted, and the store's derivation replaces it. That is `ow store lock`'s fix for the
    same state (`indexlock._FIX_LOCK`), run by the one process that holds the write lock.
    """
    from omniweave_core.retrieve.types import SCORER_VERSION  # noqa: PLC0415
    from omniweave_core.store.verify import derive_lock  # noqa: PLC0415

    header = LockHeader(scorer=SCORER_VERSION, segmenter=NO_SEGMENTER, space=NO_SPACE)
    root = scope_id_for(locator_for(source_root.resolve()))
    derived = cast(
        "LockFile",
        _read(thread, "ingest.receipt", lambda c: derive_lock(c, header=header, uri_root=root)),  # type: ignore[arg-type]
    )
    path = source_root / LOCK_PATH
    before = _on_disk(path)
    prior = _prior_rows(before)
    text = derived.render()
    kept = before is not None or bool(derived.rows)
    receipt = Receipt(
        path=path,
        documents=len(derived.rows),
        changed=prior != derived.rows,  # an unreadable file's `None` equals no tuple of rows
        written=kept and text != before,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest() if kept else "",
    )
    return _PendingReceipt(receipt=receipt, text=text)


def _on_disk(path: Path) -> str | None:
    """The receipt's text, or `None` when there is no file. Undecodable bytes read as `""`, which
    `_prior_rows` then refuses to parse -- a file that exists is never mistaken for none."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _prior_rows(text: str | None) -> tuple[LockRow, ...] | None:
    """The rows a receipt on disk lists: `()` for no file, `None` for one that does not parse."""
    if text is None:
        return ()
    try:
        return read_lock(text).rows
    except StoreError:
        return None


def _replace(path: Path, text: str) -> None:
    """The receipt's bytes, replaced atomically through a sibling -- `ManifestWriter.write()`'s
    reason -- and written as bytes with `\n`, so a Windows run commits the file a Linux run would
    (11-repo-layout.md section 1.9's third rule)."""
    staging = path.with_name(path.name + TEMP_SUFFIX)
    staging.write_bytes(text.encode("utf-8"))
    staging.replace(path)
