"""The streaming roster: the walk pulled under the water mark, and the bytes read once.

W4.3 of `16-roadmap.md:543` -- *"`run/discover.py`'s streaming roster and connector cursors;
`run/expand.py` and `op.identify` materialising part rows under the water mark"* -- of which this
module is the first clause. `02-architecture.md:69` gives the module its one-line charter:
*"`run/discover.py`  L0 ACQUIRE (fs): the `unit` roster + CAS blobs, plan_batch = 512/txn"*, and
`02:472` and `:474` are hops 2 and 3 of the worked ingest trace.

**The library half already shipped and this module does not repeat it.** `omniweave_core.acquire`
is W3.8's: the walk, the guards, `CandidateRecord`, `RosterRow`, `UNIT_UPSERT_SQL`, `Tally` and
`write_roster()`. What was missing was everything that only exists inside a run -- the water mark,
the resume token, the change-detection decision, the acquisition transition and the deletion sweep
-- because none of those is a property of a walk and all of them are properties of a *generation*.
So this module owns four things, and each is named by a document the enumerator could not see:

1. **The producer pauses at a batch boundary and keeps the cursor** (`05:427`, `08:880`).
2. **The resume token is the last COMMITTED record's `next_cursor`** (`05:104`, `05:427`).
3. **`discovered -> acquiring -> acquired`, and the stat triple moves HERE and nowhere else.**
4. **`out_of_scope` after a complete scan, and never after a partial one** (`05:365-372`).

## 1. Why the pause is a generator that returns, and not a flag

`08:880`'s backpressure table gives the mechanism in the cell itself: *"`producer_should_pause(
claimable)` returns True; the `enumerate` generator is simply not pulled."* `05:427` says what is
kept: *"on a pause the host **stops reading** the `owroster-items/1` stream between 512-row batches
and keeps the last committed record's `next_cursor`, and the next `INVOKE` resumes from it."*

`write_roster()` is already a lazy consumer -- it pulls one row, appends it, and commits when the
batch fills. `RosterFeed` sits between it and `scan()` and uses that laziness as its clock: the
wrapper's post-`yield` code runs when the consumer asks for the *next* row, which is after the
previous one was appended and therefore after the commit that a full batch triggers. So the boundary
at which the pause is decided and the boundary at which a cursor becomes durable are **the same
boundary**, observed from the same place, rather than two approximations of each other.

A `return` there is what stops the walk. `iter_candidates()` is then abandoned mid-tree and never
calls `tally.finish()`, so `ingest_scope.complete` is `0` -- which is not a side effect to be tidied
up but exactly `05:371`'s rule arriving for free: *"An **incomplete** scan never marks anything out
of scope."*

## 2. The fs walk writes no CAS blob, and the roster has no column that could hold one

`02:69` labels this module *"the `unit` roster + CAS blobs"* and `02:472`'s hop 3 has
`omniweave_core.blobs` write *"the CAS entry"*. `08:861` says the opposite in the table whose whole
purpose is to enumerate why there are exactly five cache layers:

| `acquire.fs` | none | the file *is* the blob; a copy would be a second representation |

**`08` wins, and the schema is the tie-breaker.** `unit` has no `store_ref`, no `blob_ref` and no
`cas_ref` column (`0004_runtime.sql:45-79`) -- the only columns that reference a CAS blob anywhere
are `part.store_ref` and `asset.store_ref`, both written by `DocSink` under `[store] retain_parts`,
and `cache_index.ref`. A blob written here would therefore be a blob nothing in the store points at,
swept by nothing, and counted in no sizing: `12:355` prices CAS at *"~ x1 the store"* under
`retain_parts = "when_citable"`, which is retained parts and assets and not a second copy of the
corpus. `02`'s phrasing is the connector case, where the bytes exist nowhere else and
`owroster-items/1`'s `fetched` record carries a `blob_ref` for exactly that reason (`05:142`). For
`fs` the bytes are at `[roots] source` and re-readable by path, which is what `08:861` means.
Recorded as **D165**.

So acquisition here reads, digests and forgets. `unit.content_sha256` is the durable artefact.

## 3. The three writes, and the one that is allowed to move the stat triple

`UNIT_UPSERT_SQL`'s `DO UPDATE SET` refreshes `last_seen_gen` and `cursor` and nothing else, and
`acquire.py`'s docstring states the reason as a trap: if enumeration refreshed
`size`/`mtime_ns`/`indexed_at_ns`, `stat_fresh()` would compare the stored triple against the very
`stat` it was written from, every unit would be fresh forever, and no changed document would ever be
re-indexed. *"The stored triple is a record of the last indexing, not of the last walk, and only the
acquisition path may move it."*

`ACQUIRED_SQL` **is** that path -- the one statement in the framework that writes those three
columns after the first sight of a unit -- and it writes them together with the digest they
describe, in one transaction, so there is no state in which the triple claims a freshness the digest
does not support. `size` is what `stat` said *before* the read and `bytes` is what was actually
read; for a local file they agree, and where they do not the difference is a write that raced the
read, which is the whole point of capturing the triple first (`05:344`).

## 4. `acquiring` is claimed by compare-and-swap, because there is no lease column

`05:400` rule 6 is explicit: *"A logical unit is expanded by exactly one process ... the expanding
process moves the parent to `acquiring` in one transaction, and a second process that observes
`acquiring` **with an unexpired lease** skips it."* `unit` has no `lease_expires`, no `claimed_by`
and no `claimed_gen`; `work` has all three and `unit` has none of them. Recorded as **D163**.

What ships is the transition as a conditional `UPDATE` whose `WHERE` names the state it is leaving.
`rowcount == 1` is the claim and `0` means somebody else took it -- which is stronger than a lease
for the live case and weaker for the crash case, so `acq_last_attempt_at` doubles as the lease stamp
and `RESET_ACQUIRING_SQL` returns a unit whose stamp is older than `ACQUIRING_STALE_MS` to
`discovered`. That reset **cannot check liveness**: `work.claimed_by` carries
`'<host>:<pid>:<create_time>'` precisely so a recycled pid cannot look alive (`08:496`), and `unit`
has no column to put it in. The consequence is bounded and stated rather than hidden -- a live
acquisition that takes longer than the threshold can be re-run by a second process, which costs a
duplicated read and converges through `ACQUIRED_SQL`'s own `WHERE state = 'acquiring'`.

## 5. `unseen` and `filtered` are not `FailureClass` members, and this is the module D80 named

`D80` recorded that `unit.acq_failure_class` takes `'unseen'` (`05:370`) and `'filtered'` (`05:375`)
while `FailureClass` is thirteen members frozen at the end of P3, and closed with: *"Nothing this
wave writes either value ... P4's deletion pass will."* This is that pass. `ACQ_FAILURE_CLASSES` is
therefore fifteen strings and `acq_retryable()` is the verdict the retry ladder needs: the two
extras are **terminal scope statements and never retried**, because "it disappeared" and "a glob
excluded it" are answers, not failures. A future `FailureClass` member for either would be a
migration on a hot table; a fifteen-member domain for this column would be a CHECK. The choice is
still the plan's.

## 6. What this module is not

* **It does not detect.** `05:393`'s state machine puts *"DETECTION runs here. FREE. No driver
  invoked"* on the `acquired` state, and `05` sections 2.1-2.5 specify the ladder -- the 21-row
  magic table, container identity reads, content probes, the clamped driver sniff and the
  `(basis_rank, -confidence, format_token)` total order. **No roadmap row schedules it and `02`'s
  fifty-row component table has no row for it**; `doc.format_evidence` is a column with a reader and
  no producer. Recorded as **D166**. `unit.format` and `unit.media_type` are therefore left NULL
  here and `expand.py` takes its format as an argument.
* **It does not route, plan or claim.** The claim is `work.py`'s statement and the loop is
  `supervisor.py`'s.
* **It is synchronous.** `StoreThread.run()` blocks on a ticket, `os.scandir` blocks, and `02:659`
  pushes the whole of it through `asyncio.to_thread`; the same argument `pipeline.py` makes.

Specified in 05-ingest-and-routing.md sections 1.1-1.5, 02-architecture.md:69 and :469-476,
08-runtime.md section 2.5 and :500-505, and 16-roadmap.md:543.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, TypeAlias

from omniweave_core.acquire import (
    CONNECTOR,
    DEFAULT_MAX_UNIT_BYTES,
    MAX_UNITS_PER_CALL,
    PLAN_BATCH,
    SKIP_TOO_LARGE,
    SKIP_UNREADABLE,
    WALKED_PATH_KEY,
    RosterRow,
    StatTriple,
    Tally,
    TrustClass,
    fetch_local,
    locator_for,
    scan,
    scope_id_for,
    stat_fresh,
    walked_path,
    write_roster,
)
from omniweave_core.errors import RouteError
from omniweave_core.events import EventKind
from omniweave_core.store.sqlite import BATCH_WAIT_MS, Unit
from omniweave_core.work import MAX_ATTEMPTS_TODAY, STORE_NOW_MS
from omniweave_ports.types import DriverError, FailureClass

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Mapping, Sequence

    from omniweave_core.acquire import IngestGuards, Scope, ScopeTally
    from omniweave_core.store.sqlite import StoreThread

__all__ = [
    "ACQUIRED",
    "ACQUIRED_SQL",
    "ACQUIRING",
    "ACQUIRING_STALE_MS",
    "ACQ_FAILED_SQL",
    "ACQ_FAILURE_CLASSES",
    "CLAIM_ACQUIRING_SQL",
    "FAILED",
    "FILTERED",
    "MARK_STALE_SQL",
    "OUT_OF_SCOPE",
    "OUT_OF_SCOPE_SQL",
    "PENDING_ACQUISITION_AFTER_SQL",
    "PENDING_ACQUISITION_SQL",
    "RAW_DIGEST_CODE",
    "RESET_ACQUIRING_SQL",
    "SKIP_REASON_CLASSES",
    "STALE_SCAN_SQL",
    "UNCHANGED_SQL",
    "UNSEEN",
    "WALKED_PATH_KEY",
    "AcquirePass",
    "Acquired",
    "Backpressure",
    "DiscoverReport",
    "Freshness",
    "Normaliser",
    "RosterFeed",
    "StoredStat",
    "acq_retryable",
    "acquire_pending",
    "acquire_unit",
    "content_digest",
    "discover",
    "freshness",
    "mark_stale",
    "observe",
    "pending_params",
    "raw",
    "reset_stale_acquiring",
    "roster_rows",
    "stale_params",
    "sweep_unseen",
    "walked_path",
]


class _Rows(Protocol):
    """The two cursor methods this module's statements need, and no connection at all.

    The same device `acquire.py` uses, and for the same reason: `sqlite3` is banned outside
    `store/sqlite.py` by `TID251` (INV-17), so a closure handed to the store thread is annotated
    against the shape it uses rather than against the type it receives. `execute` returns `Any`
    because what these statements want from it is `rowcount`, and typing that would be typing
    `sqlite3.Cursor`.
    """

    def execute(self, sql: str, parameters: Mapping[str, object] = ..., /) -> Any: ...


# =============================================================================================
# 1. The states this module writes, and the two values that are not `FailureClass` members
# =============================================================================================


ACQUIRING: Final[str] = "acquiring"
ACQUIRED: Final[str] = "acquired"
FAILED: Final[str] = "failed"
OUT_OF_SCOPE: Final[str] = "out_of_scope"
"""The four `unit.state` values this module writes, from `0004_runtime.sql:49-51`'s CHECK.

`discovered` is the fifth and it is `acquire.py`'s -- the enumerator writes it and nothing here
writes it again, except `RESET_ACQUIRING_SQL`'s one path back. `identified` is `expand.py`'s and
`planned`/`running`/`settled` belong to the planner and the loop above.
"""

UNSEEN: Final[str] = "unseen"
FILTERED: Final[str] = "filtered"

ACQ_FAILURE_CLASSES: Final[frozenset[str]] = frozenset(
    {member.value for member in FailureClass} | {UNSEEN, FILTERED}
)
"""`unit.acq_failure_class`'s domain: the thirteen `FailureClass` members plus two. **D80.**

`05:227` writes `'too_large'` (a member), `05:370` writes `'unseen'` and `05:375` writes
`'filtered'`; neither of the last two is one of the thirteen, and `0004_runtime.sql:73` declares the
column bare `TEXT` while `state`, `trust_class` and `scope_rule` beside it all carry CHECKs. D80
left the question open -- *"a `FailureClass` column with two extra strings or a column of its own
with a fifteen-member domain"* -- and noted that nothing written before P4 depended on the answer.
The deletion sweep is what depends on it, so the set is built here from the enum rather than
transcribed: a fourteenth `FailureClass` joins this domain without an edit, and a typo in either
extra is a failing membership check rather than a row nothing can classify.
"""


def acq_retryable(failure_class: str) -> bool:
    """Whether an acquisition failure may be attempted again. The two extras never are.

    `05:419` rule 4 gives acquisition its own retry counters -- *"`unit.acq_attempts_total`,
    `acq_attempts_today` and `acq_last_attempt_at` are the acquire-side twins of
    `work.attempts_*`"* -- and `work.classify()` maps a `FailureClass` to transient-or-permanent
    through `08` section 1.6's table. `unseen` and `filtered` have no row in that table, which is
    what D80 called *"two inputs it cannot classify"*.

    They are not failures. A unit marked `out_of_scope/unseen` disappeared from a scope that
    completed; a unit marked `out_of_scope/filtered` was excluded by a glob, a size guard or a
    `skip` rule. Retrying either would re-walk a tree to re-learn the same answer, and the state
    they rest in is `out_of_scope` rather than `failed` precisely because the state machine already
    says they are terminal (`05:389-395`). So they are `False` here, and grading the remaining
    thirteen is `work.classify()`'s job and not a second table in this module.
    """
    if failure_class not in ACQ_FAILURE_CLASSES:
        raise RouteError(
            f"{failure_class!r} is not one of unit.acq_failure_class's "
            f"{len(ACQ_FAILURE_CLASSES)} values (05:227, :370, :375; D80)",
            fix="use a FailureClass member, or discover.UNSEEN / discover.FILTERED",
        )
    return failure_class not in {UNSEEN, FILTERED}


#  `WALKED_PATH_KEY` and `walked_path()` moved to `omniweave_core.acquire` in W7.3w (D559):
#  `add_sources()` is a second walker below this package and has to stamp the same key. Both
#  names are re-exported from here, where W4.3 put them.

ACQUIRING_STALE_MS: Final[int] = 600_000
"""How old `acq_last_attempt_at` must be before `acquiring` is returned to `discovered`. **D163.**

Ten minutes, and the number is this module's rather than the plan's, because the plan asks for a
lease and the table has no lease column. It is deliberately five times `[runtime] lease_ms`'s
120 s: a `work` lease is extended by a live holder every `lease_extend_ms` and can therefore be
tight, while nothing extends this one, so the threshold has to cover the longest single acquisition
-- a 2 GiB `max_unit_bytes` read -- rather than the longest heartbeat interval. Naming a knob it
does not have would be worse than naming a constant it does.
"""

RAW_DIGEST_CODE: Final[str] = "OW-C-041"
"""The diagnostic `05:261` requires when `unit.normalizer` is NULL and the raw bytes were hashed.

*"The normaliser is per format, recorded in `unit.normalizer`; NULL means the raw bytes were hashed
and records `OW-C-041`."* The code has no `codes.toml` row -- `acquire.py`'s `FetchedRecord`
docstring reported the same absence from the other side -- so it is carried as a string on
`Acquired.diagnostics` and emitted by the caller that owns a `Diag` sink, which this module is not.
"""


# =============================================================================================
# 2. The streaming roster: the feed, the pause, and the cursor
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Backpressure:
    """The water mark as this module needs it: one predicate and the two numbers the events carry.

    `08:880`'s row is *"`producer_should_pause(claimable)` returns True; the `enumerate` generator
    is simply not pulled. `plan.pause` / `plan.resume` carry `claimable` and the water mark."* Three
    things, and they belong to three places: the predicate is
    `supervisor.producer_should_pause(claimable, admission, paused=...)` and carries the caller's
    hysteresis state across calls; the claimable count is a `work` query this module has no business
    issuing; the two thresholds are `Admission`'s. So all three are supplied, and the hysteresis is
    **not** re-implemented here -- a second copy of a two-threshold rule is how `plan.pause` and
    `plan.resume` start disagreeing about which threshold they crossed.

    The defaults make the whole mechanism inert, which is the right default for a caller that has no
    queue yet: `pause` never fires and the walk runs to exhaustion.
    """

    pause: Callable[[], bool] = lambda: False
    claimable: Callable[[], int] = lambda: 0
    high_water: int = 0
    low_water: int = 0

    def pause_fields(self) -> Mapping[str, object]:
        """`plan.pause`'s two declared fields (`tools/events.toml`), read at emission time."""
        return {"claimable": self.claimable(), "high_water": self.high_water}

    def resume_fields(self) -> Mapping[str, object]:
        """`plan.resume`'s two declared fields. The **low** water mark, because that is the one a
        resume crossed -- `08:885`'s *"the 2:1 gap means one pause drains 25,000 rows before
        discovery resumes"* is only legible if each event names the threshold it answers to."""
        return {"claimable": self.claimable(), "low_water": self.low_water}


class RosterFeed:
    """A `RosterRow` stream that stops at a committed batch boundary when the water mark says so.

    **The laziness of the consumer is the clock.** `write_roster()` pulls one row, appends it, and
    commits when `len(batch) >= plan_batch`; the code after this generator's `yield` therefore runs
    once the consumer asks for the *next* row, which is after the previous row was appended and
    after the commit that a full batch triggered. So `committed_cursor` is the `next_cursor` of a
    record that is durable, not of one that is merely buffered -- which is exactly `05:427`'s *"the
    last committed record's `next_cursor`"* and the difference between a resume that repeats 511
    rows and one that skips them.

    **It pauses; it never drops** (`08:875`). A paused feed returns, `write_roster` commits the
    empty remainder with the coverage row, `iter_candidates()` is abandoned without
    `tally.finish()`, and `ingest_scope.complete` is `0`. Every row already yielded is already
    committed or in the batch about to be.
    """

    __slots__ = (
        "_boundaries",
        "_committed",
        "_pause",
        "_paused",
        "_plan_batch",
        "_seen",
        "_source",
    )

    def __init__(
        self,
        source: Iterator[RosterRow],
        *,
        pause: Callable[[], bool] = lambda: False,
        plan_batch: int = PLAN_BATCH,
    ) -> None:
        if plan_batch < 1:
            raise ValueError("plan_batch is a positive row count per transaction")
        self._source = source
        self._pause = pause
        self._plan_batch = plan_batch
        self._seen = 0
        self._boundaries = 0
        self._committed: str | None = None
        self._paused = False

    @property
    def seen(self) -> int:
        """Rows yielded to the consumer. Not rows committed: the last batch may be open."""
        return self._seen

    @property
    def boundaries(self) -> int:
        """Full batches the consumer committed, which is how often `pause` was evaluated."""
        return self._boundaries

    @property
    def committed_cursor(self) -> str | None:
        """The resume token: the `next_cursor` of the last row in the last committed batch.

        `None` before the first boundary, which is honest rather than empty -- a scan that has
        committed nothing has nothing to resume from and must restart, and `Locator.cursor = None`
        is `05:88`'s own spelling for a full enumeration.
        """
        return self._committed

    @property
    def paused(self) -> bool:
        """Whether the stream ended because of the water mark rather than because of the tree."""
        return self._paused

    def __iter__(self) -> Iterator[RosterRow]:
        for row in self._source:
            self._seen += 1
            yield row
            # Resumed: the consumer has appended the row above and is asking for the next one, so
            # a full batch has already committed. This is the only place either question is asked.
            if self._seen % self._plan_batch:
                continue
            self._boundaries += 1
            self._committed = row.cursor
            if self._pause():
                self._paused = True
                return


@dataclass(frozen=True, slots=True)
class DiscoverReport:
    """One discovery pass, as the Supervisor needs to read it.

    `statements` is `write_roster`'s count of upserts executed, which is not the number of rows
    *changed*: `ON CONFLICT` makes those different numbers and the honest count of what changed is a
    `SELECT`, not a `rowcount`. `coverage` is the `ingest_scope` row that landed in the final
    transaction, and `coverage.complete` is the fact `sweep_unseen()` refuses to run without.

    `paused` and `exhausted_call_bound` are two bounds with one consequence, and they are separate
    fields because the caller's next move differs: a pause resumes when the queue drains, a call
    bound resumes immediately. `complete` is `False` for both, which is what matters to the sweep.
    """

    scope_id: str
    statements: int
    coverage: ScopeTally | None
    paused: bool
    resume_cursor: str | None
    boundaries: int
    exhausted_call_bound: bool

    @property
    def complete(self) -> bool:
        """Whether the scan covered its scope. `False` for a pause, a call bound or a crash."""
        return self.coverage is not None and self.coverage.complete


def roster_rows(
    root: Path | str,
    scope: Scope,
    guards: IngestGuards,
    *,
    indexed_at_ns: int,
    generation: int,
    tally: Tally,
    trust_class: TrustClass = TrustClass.INTERNAL,
    cursor: str | None = None,
    max_units: int = MAX_UNITS_PER_CALL,
) -> Iterator[RosterRow]:
    """`scan()` with `walked_path` stamped onto every row. D143's write site.

    The one thing this wrapper adds to `acquire.scan()` is `derived["walked_path"]`, and it is added
    here rather than in the enumerator for the reason `derived`'s other members are not: `labels`
    and `etag` are the *candidate's*, and the walked path is the *host's* -- the enumerator hands
    over a connector-local id and `canonical_uri()` consumes it, so the last component holding an
    unresolved path is the one that joins the two.
    """
    locator = locator_for(root, cursor=cursor)
    source = str(root)
    for row in scan(
        locator,
        scope,
        guards,
        indexed_at_ns=indexed_at_ns,
        last_seen_gen=generation,
        tally=tally,
        trust_class=trust_class,
        max_units=max_units,
    ):
        yield RosterRow(
            unit_uri=row.unit_uri,
            cursor=row.cursor,
            stat=row.stat,
            trust_class=row.trust_class,
            last_seen_gen=row.last_seen_gen,
            connector=row.connector,
            derived={**dict(row.derived), WALKED_PATH_KEY: walked_path(source, row.unit_uri)},
            scope_rule=row.scope_rule,
        )


def discover(
    thread: StoreThread,
    root: Path | str,
    scope: Scope,
    guards: IngestGuards,
    *,
    indexed_at_ns: int,
    generation: int,
    scanned_at_ns: int,
    emit: Callable[..., object] | None = None,
    backpressure: Backpressure | None = None,
    resumed: bool = False,
    cursor: str | None = None,
    trust_class: TrustClass = TrustClass.INTERNAL,
    plan_batch: int = PLAN_BATCH,
    max_units: int = MAX_UNITS_PER_CALL,
    wait_ms: int = BATCH_WAIT_MS,
) -> DiscoverReport:
    """One discovery pass: walk, roster at `plan_batch` per transaction, pause at a boundary.

    `02:472`'s hop 2 in one call. It commits `unit` rows *"at `[runtime] plan_batch = 512` rows per
    transaction; plus one `ingest_scope` row recording discovered vs indexed vs skipped"*, and the
    coverage row rides in the final transaction because `write_roster()` puts it there.

    **`resumed` is the caller's hysteresis state, not this module's.** `08:884` forbids one
    threshold -- *"A single threshold makes the producer oscillate at the boundary and turns
    `plan.pause`/`plan.resume` into noise"* -- and the state that makes it hysteresis lives on the
    Supervisor across calls. What this function does with it is emit `plan.resume` when a pass
    starts that a previous pass paused, which is the event's only honest issue point: the run
    resumed when the walk restarted, not when a counter crossed a line.

    `max_units` bounds one call at `[acquire] max_units_per_call = 5000` (`05:211`), *"so a
    million-file tree is 200 invocations rather than one, each of which the water mark can end
    early."* A pass that emits exactly `max_units` rows without exhausting the tree reports
    `exhausted_call_bound` -- a resume the caller must make and not a completion.
    """
    marks = Backpressure() if backpressure is None else backpressure
    if emit is not None and resumed:
        emit(kind=EventKind.PLAN_RESUME, fields=marks.resume_fields())
    tally = Tally()
    feed = RosterFeed(
        roster_rows(
            root,
            scope,
            guards,
            indexed_at_ns=indexed_at_ns,
            generation=generation,
            tally=tally,
            trust_class=trust_class,
            cursor=cursor,
            max_units=max_units,
        ),
        pause=marks.pause,
        plan_batch=plan_batch,
    )
    scope_id = scope_id_for(locator_for(root))
    statements, coverage = write_roster(
        thread,
        feed,
        tally=tally,
        scope_id=scope_id,
        scanned_at_ns=scanned_at_ns,
        plan_batch=plan_batch,
        wait_ms=wait_ms,
    )
    report = DiscoverReport(
        scope_id=scope_id,
        statements=statements,
        coverage=coverage,
        paused=feed.paused,
        resume_cursor=feed.committed_cursor,
        boundaries=feed.boundaries,
        exhausted_call_bound=(
            not feed.paused
            and coverage is not None
            and not coverage.complete
            and feed.seen >= max_units
        ),
    )
    if emit is not None:
        emit(
            kind=EventKind.PLAN_DISCOVER,
            fields={
                "scope_id": scope_id,
                "discovered": 0 if coverage is None else coverage.discovered,
                "skipped": 0 if coverage is None else coverage.skipped,
            },
        )
        if feed.paused:
            emit(kind=EventKind.PLAN_PAUSE, fields=marks.pause_fields())
    return report


# =============================================================================================
# 3. Acquisition: the change-detection ladder, the claim, the digest and the triple
# =============================================================================================


Normaliser: TypeAlias = Callable[[bytes, str], "tuple[bytes, str | None]"]
"""`(raw bytes, format token) -> (bytes to digest, the normaliser's name or None)`.

`05:257-271`'s table is per format -- `pdf_trailer_v1` for PDF, `opc_v1` for OPC, `ocf_v1` for
ODF/EPUB, *"everything else | none | raw bytes are hashed"* -- and every one of the three named
normalisers needs a format reader this distribution may not import (`tools/layers.toml` gives
`omniweave` `omniweave_core`, `omniweave_ports` and `omniweave_office`, and PDF is not among them).
So the normaliser is a parameter and `raw` is the shipped one, which is the row the table itself
calls *"everything else"* and the row every format reaches until the detection ladder exists (D166).

`05:272` fixes the contract a replacement must keep: *"A normaliser is **read-only and total**: it
digests a projection of the bytes and never rewrites the stored blob ... If it raises, the raw
digest is used and a `Diag` is recorded; the failure mode is 'reparse a document we could have
skipped', never 'treat two documents as one'."* `content_digest()` enforces the second half.
"""

Freshness: TypeAlias = Literal["unchanged", "unsettled", "changed"]
"""Which rung of `05:337-347`'s ladder answered, as a closed three-member domain."""


def raw(body: bytes, fmt: str) -> tuple[bytes, str | None]:
    """`05:271`'s last row: the raw bytes are hashed and `unit.normalizer` is NULL."""
    del fmt
    return body, None


def content_digest(
    body: bytes, *, fmt: str = "", normalise: Normaliser = raw
) -> tuple[str, str | None]:
    """`unit.content_sha256` over the normalised load-bearing bytes, and the normaliser's name.

    **A raising normaliser is caught and the raw digest is used**, which is `05:276`'s rule
    verbatim: the failure mode is a re-parse of a document that could have been skipped, never two
    documents treated as one. The caller records `RAW_DIGEST_CODE` on the fallback exactly as it
    does on the `raw` path, because both are the same fact -- *"NULL means the raw bytes were
    hashed"*.

    `BaseException` is deliberately not caught: a `KeyboardInterrupt` inside a normaliser is a
    cancellation and must not be converted into a silently different identity.
    """
    try:
        projected, name = normalise(body, fmt)
    except Exception:
        projected, name = body, None
    return hashlib.sha256(projected).hexdigest(), name


@dataclass(frozen=True, slots=True)
class StoredStat:
    """The `unit` row's freshness columns as `freshness()` reads them.

    `settled_gen` is here and not on `StatTriple` because `08:503` makes it half the predicate:
    *"63,411 units are `stat_fresh` and settled at a `settled_gen`, so they produce no work."* A
    unit whose bytes are unchanged but which never reached `settled` has work outstanding and must
    be re-entered; freshness alone is not a reason to skip it.
    """

    triple: StatTriple
    settled_gen: int | None = None
    content_sha256: str | None = None


def freshness(stored: StoredStat, observed: StatTriple) -> Freshness:
    """`unchanged`, `unsettled` or `changed`. The zero-byte rung, and `08:503`'s second conjunct.

    ```
    stat_fresh   size == st_size AND mtime_ns == st_mtime_ns
                 AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns   [0 bytes read]
    cursor       the connector's own monotonic token                            [1 round trip]
    digest       content_sha256 over normalised load-bearing bytes              [full read]
    ```

    Three rungs at three prices, and `05:349` says *"`stat_fresh` is the only mechanism that costs
    nothing and the only one available to the `fs` connector, which is 100% of the reference
    ingest"* -- so the cursor rung has no fs form and the digest rung is reached only by
    `--verify-digests`, which is `acquire_unit()`'s parameter because it is a decision made *after*
    the bytes are read and this function reads none.

    `unsettled` is not a freshness verdict at all -- it is `08:503`'s second conjunct, and returning
    it separately is what lets a caller report "0 bytes read, and re-entered anyway" honestly
    instead of calling a settled-state gap a content change.
    """
    if not stat_fresh(stored.triple, observed):
        return "changed"
    if stored.settled_gen is None:
        return "unsettled"
    return "unchanged"


def observe(path: Path, *, indexed_at_ns: int) -> StatTriple:
    """A bare `stat` for the freshness question, and **not** the triple that gets written.

    Two stats, deliberately. This one decides whether to read at all, because `05:339` prices the
    zero-byte rung at zero bytes and `fetch_local()` always reads. The one that reaches
    `ACQUIRED_SQL` is `fetch_local()`'s own, taken immediately before the read it describes -- which
    is the ordering `05:344` requires and the only one under which a write racing the read is
    caught. A unit that changes between the two stats is read and digested under the second, so the
    extra syscall can cause a redundant read and can never cause a wrong record.
    """
    info = path.stat()
    return StatTriple(size=info.st_size, mtime_ns=info.st_mtime_ns, indexed_at_ns=indexed_at_ns)


PENDING_ACQUISITION_SQL: Final[str] = """
SELECT unit_uri, state, size, mtime_ns, indexed_at_ns, content_sha256, settled_gen, derived
  FROM unit
 WHERE connector = :connector
   AND last_seen_gen = :generation
   AND state IN ('discovered', 'failed')
   AND (acq_retry_after IS NULL OR acq_retry_after <= {now})
   AND acq_attempts_total < :max_attempts
 ORDER BY unit_uri
 LIMIT :limit
""".replace("{now}", STORE_NOW_MS)
"""The units this pass may acquire, in a deterministic order.

`last_seen_gen = :generation` and not `>=`: a unit this run's walk did not see is out of this run's
scope, and acquiring it would be the deletion sweep's mirror image -- work on a document nobody
asked about.

`failed` is in the state set beside `discovered` because `05:392` puts the retry there:
*"acquiring --> failed (acq_failure_class, acq_retry_after)"*, and `05:419` gives acquisition
its own counters. The `acq_retry_after` clause reads the **store's** clock for `08:597`'s
reason -- a backward NTP step on one worker must not make a row permanently unacquirable.

`ORDER BY unit_uri` is for determinism across two runs of one corpus, which is what makes a partial
run's second half reproducible; it is not a priority, because acquisition has none.
"""

CLAIM_ACQUIRING_SQL: Final[str] = """
UPDATE unit SET
  state = 'acquiring',
  acq_attempts_total = acq_attempts_total + 1,
  acq_attempts_today = CASE WHEN date(acq_last_attempt_at/1000,'unixepoch')
                              = date(unixepoch('subsec'),'unixepoch')
                            THEN acq_attempts_today + 1 ELSE 1 END,
  acq_last_attempt_at = {now}
 WHERE unit_uri = :unit_uri
   AND state IN ('discovered', 'failed')
   AND (acq_retry_after IS NULL OR acq_retry_after <= {now})
""".replace("{now}", STORE_NOW_MS)
"""`05:400` rule 6's claim, as a compare-and-swap. **D163: there is no lease column to hold.**

*"the expanding process moves the parent to `acquiring` in one transaction, and a second process
that observes `acquiring` with an unexpired lease skips it."* `unit` has no `lease_expires` and no
`claimed_by`, so the `WHERE` names the state being left and `rowcount == 1` is the claim -- a second
process reading `acquiring` matches zero rows and moves on, which is the skip the rule asks for, by
a different mechanism.

The `attempts_today` `CASE` is `work.py`'s `CLAIM_SQL` arithmetic on the acquire-side twins, and it
is recomputed from `date(acq_last_attempt_at)` rather than trusting a stored zero for `08:595`'s
reason: *"a counter without its period stamp cannot answer 'is this from today'."* `05:419` rule 4
is why the counters are separate at all -- *"A rate-limited connector must not consume a document's
parse retry budget."*
"""

RESET_ACQUIRING_SQL: Final[str] = """
UPDATE unit SET state = 'discovered'
 WHERE state = 'acquiring'
   AND (acq_last_attempt_at IS NULL OR acq_last_attempt_at <= {now} - :stale_ms)
""".replace("{now}", STORE_NOW_MS)
"""The stale-`acquiring` reset, which stands in for the lease reaper `unit` has no columns for.

`08:496`'s reaper *"checks `_is_live_holder(claimed_by)` ... and the third component is what stops a
recycled pid from looking alive"*. There is no `claimed_by` on `unit`, so this cannot check liveness
and does not pretend to: it is a timeout, `ACQUIRING_STALE_MS` says how long, and the worst case is
a duplicated read whose second writer loses `ACQUIRED_SQL`'s own `WHERE state = 'acquiring'` race.
Recorded as **D163**.

`acq_attempts_total` is deliberately **not** decremented, unlike `08:496`'s lease reap which returns
rows to `pending` *"with `attempts_total` decremented"*. A `work` lease expires while a live holder
is still working and the decrement is what stops a slow driver from burning its retry budget; an
`acquiring` unit past ten minutes has no such defence and no liveness check, so an undecremented
counter is the only thing that bounds a crash loop.
"""

ACQUIRED_SQL: Final[str] = """
UPDATE unit SET
  state = 'acquired',
  size = :size, mtime_ns = :mtime_ns, indexed_at_ns = :indexed_at_ns,
  content_sha256 = :content_sha256, normalizer = :normalizer, bytes = :bytes,
  acq_failure_class = NULL, acq_retry_after = NULL
 WHERE unit_uri = :unit_uri AND state = 'acquiring'
"""
"""**The only statement in the framework that moves the stat triple after first sight.**

`acquire.py`'s `UNIT_UPSERT_SQL` refuses to refresh `size`, `mtime_ns` or `indexed_at_ns` on a
conflict, and its docstring gives the failure that refusal prevents: a triple re-stamped from the
current `stat` on every walk would make `stat_fresh(stored, observed)` compare a triple against the
`stat` it was just written from, every unit would read fresh forever, and no changed document would
be re-indexed again. The triple is *"a record of the last indexing, not of the last walk"*, and this
is the indexing.

It writes the triple in the same statement as the digest that triple describes, so no state exists
in which freshness claims more than the digest supports. `size` is the **pre-read** `stat` (`05:344`
-- *"the stat triple is captured BEFORE the content read ... so a write racing the read is
caught"*) and `bytes` is what the read actually returned; they differ exactly when a writer raced
the read, and the next run's `stat_fresh` then says `changed`.

`acq_failure_class` and `acq_retry_after` are cleared because a success erases a previous failure's
cooldown; leaving them would make a unit that failed once and succeeded twice look permanently
suspect to `ow doc verify`.
"""

UNCHANGED_SQL: Final[str] = """
UPDATE unit SET
  state = 'acquired', indexed_at_ns = :indexed_at_ns,
  acq_failure_class = NULL, acq_retry_after = NULL
 WHERE unit_uri = :unit_uri AND state = 'acquiring'
"""
"""The skip's write: the state, the index time, and nothing else. Zero bytes were read.

`size` and `mtime_ns` are untouched because the verdict that got here **is** the statement that they
are unchanged -- writing them back would be writing a value to itself, and the one time it would not
be is the one time the verdict was wrong.

`indexed_at_ns` moves, and that is the whole point of the statement existing. `stat_fresh`'s third
clause is `st_mtime_ns + MTIME_GRANULARITY_NS <= indexed_at_ns` (`05:339`), so a unit indexed while
its mtime was still inside the two-second granularity window is *not* provably fresh and is re-read
every run. Advancing the index time on a confirmed-unchanged unit is what lets it become provably
fresh on the next pass and stop paying for a re-read forever. `05:346` states the asymmetry it
relies on: *"a unit indexed before its own mtime settled is re-read, which costs a parse and never
loses a document."*
"""

ACQ_FAILED_SQL: Final[str] = """
UPDATE unit SET
  state = :state, acq_failure_class = :failure_class, acq_retry_after = :retry_after
 WHERE unit_uri = :unit_uri AND state = 'acquiring'
"""
"""`05:392-393`'s two exits from `acquiring`: `failed` with a class, or `out_of_scope/filtered`.

One statement for both because they differ only in the destination state and in whether the class is
retryable -- `acq_retryable()` is the predicate and the caller supplies both, which keeps the
pairing ("`filtered` goes to `out_of_scope`, `too_large` goes to `failed`") in a Python expression a
test can read rather than in two nearly identical statements.
"""

OUT_OF_SCOPE_SQL: Final[str] = """
UPDATE unit SET state = 'out_of_scope', acq_failure_class = 'unseen'
 WHERE connector = :connector
   AND unit_uri GLOB :prefix
   AND last_seen_gen < :generation
   AND state NOT IN ('out_of_scope', 'acquiring')
"""
"""`05:365-372`'s deletion rule. **Its blocks are not deleted and this statement deletes nothing.**

*"`unit.last_seen_gen` is stamped on every discovery pass. A unit whose `last_seen_gen <
run.generation` after a **complete** scan of its scope (`ingest_scope.complete = 1`) is marked
`state = 'out_of_scope'` with `acq_failure_class = 'unseen'`; its blocks are **not** deleted,
because a shipped `cite` must still resolve. `ow store gc --unseen-for <days>` is the only path
that removes them."*

`unit_uri GLOB :prefix` is the scope containment test, the same shape `07` section 3.8 uses for
absence gate 4 (`doc.uri GLOB scope_id || '*'`) and with the same unfixed hazard: SQLite's
`GLOB` has no `ESCAPE` clause, so a root literally named `docs[1]` produces a prefix whose `[1]`
is a character class. `acquire.scope_id_for()` reported it from the other side; the fix is a
predicate and the predicate is `07`'s to change.

`acquiring` is excluded because a unit another process is reading has not been seen-and-lost -- its
`last_seen_gen` is simply older than the generation doing the sweeping, and marking it
`out_of_scope` would race a live `ACQUIRED_SQL` that would then match zero rows and lose the read.
`out_of_scope` is excluded because the transition is idempotent and re-stamping it would overwrite a
`filtered` cause with `unseen`.
"""


STALE_SCAN_SQL: Final[str] = """
SELECT unit_uri, size, mtime_ns, indexed_at_ns, content_sha256, settled_gen
  FROM unit
 WHERE connector = :connector
   AND unit_uri GLOB :prefix
   AND last_seen_gen = :generation
   AND state = 'settled'
   AND stale_since IS NULL
 ORDER BY unit_uri
 LIMIT :limit
"""
"""The settled units this generation's walk saw, so the ladder can be applied to them too.

**Without this query a changed document is never noticed.** `08:503`'s recovery step is *"for each
unit takes the change-detection ladder"* -- each unit, not each `discovered` one -- and its worked
example says why: *"63,411 units are `stat_fresh` and settled at a `settled_gen`, so they produce no
work."* The sentence is only informative if the settled ones were examined and found fresh.
`PENDING_ACQUISITION_SQL` deliberately does not cover them, because an unchanged settled unit must
not be claimed, demoted or re-read; this query surveys them and `MARK_STALE_SQL` records the verdict
without touching `state`.

`stale_since IS NULL` in the `WHERE` is `08:1891`'s rule expressed as a predicate rather than as a
comment: *"`stale_since` is set on the **first** transition only and is **kept across a reset**,
because it measures how long the answer has been untrustworthy, not how long the attempt has run."*
A unit already marked is not re-surveyed, so the clock never restarts.
"""

MARK_STALE_SQL: Final[str] = """
UPDATE unit SET stale_since = :at_ns
 WHERE unit_uri = :unit_uri AND stale_since IS NULL
"""
"""Stamp a settled unit whose bytes no longer match the roster. **The column's only writer. D169.**

`0004_runtime.sql:76` declares `stale_since INTEGER, -- FIRST transition only; KEPT across a reset`
and `unit_stale ON unit(stale_since) WHERE stale_since IS NOT NULL` indexes it.
`store/reader.py`'s `Coverage` counts it -- `SELECT count(*) FROM unit WHERE stale_since IS NOT NULL
AND <scope>` -- and the count reaches the `Verdict`. So the column has a reader, a dedicated partial
index and a stated meaning, and **the plan names no component that writes it**. Discovery is the
only one that can: on the `fs` path the change-detection ladder is the sole observer of a content
change, and `05:349` makes that path *"100% of the reference ingest"*.

**It does not move `state`, and that is not timidity.** `05:389`'s state machine draws `settled` as
terminal -- there is no arrow back -- and the component that re-opens a unit is the invalidation
pass, whose mechanism `08:1818` and `07` section 11.4 fix as one query over the `dep` reverse index:
`SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c ON c.kind=d.kind AND c.key=d.key WHERE
d.digest <> c.new_digest`. That is W4.6's cell and it resets **work** rows, which is the level the
re-entry actually happens at: `work_identity` carries no generation, so a changed document's second
parse is the same row re-run, not a second one. Marking the unit here is what puts it in the
`changed` set that query joins against; demoting it would be this module answering a question the
`dep` index answers with evidence.
"""


def stale_params(
    *, scope_id: str, generation: int, connector: str = CONNECTOR, limit: int = PLAN_BATCH
) -> Mapping[str, object]:
    """The named parameters of `STALE_SCAN_SQL`. The prefix is `scope_id` plus `GLOB`'s wildcard."""
    return {
        "connector": connector,
        "prefix": f"{scope_id}*",
        "generation": generation,
        "limit": limit,
    }


def mark_stale(
    thread: StoreThread,
    unit_uris: Sequence[str],
    *,
    at_ns: int,
    wait_ms: int = BATCH_WAIT_MS,
) -> int:
    """Stamp `stale_since` on each of `unit_uris`, in one transaction. Returns rows changed.

    One transaction for the batch rather than one per unit, for `05:1198`'s reason applied to a
    smaller write: the caller surveys at `plan_batch` and a per-unit transaction would take the
    write lock once per document across a 100k corpus.

    `at_ns` is the caller's clock reading and not a store-side `unixepoch()`, unlike every other
    statement in this module. The difference is deliberate: the others compare a stamp against the
    store's own now, so the store must own both sides; `stale_since` is only ever *read* as an age
    by `ow doctor` and a `Verdict`, so it is a correlation timestamp, which `clock.py` says is
    `wall_ns()`'s job and never `monotonic_ns()`'s.
    """
    if not unit_uris:
        return 0
    params = [{"unit_uri": uri, "at_ns": at_ns} for uri in unit_uris]
    changed = 0

    def run(connection: _Rows) -> None:
        nonlocal changed
        for row in params:
            changed += int(connection.execute(MARK_STALE_SQL, row).rowcount or 0)

    thread.run(Unit(name="discover.mark_stale", run=run, cost_class="free", wait_ms=wait_ms))
    return changed


@dataclass(frozen=True, slots=True)
class Acquired:
    """What one acquisition produced, before it is written. One record, three statements.

    `bytes_read` is `0` for a skip and `05:339` is why it is carried at all: the ladder is priced in
    bytes, and a report that could not distinguish "0 bytes read" from "2 GiB read and identical"
    would make the whole ladder unmeasurable. `verdict` names which rung answered, so the two skips
    -- the free one and `--verify-digests`' expensive one -- are never the same row in a manifest.
    """

    unit_uri: str
    state: str
    verdict: Freshness
    bytes_read: int = 0
    content_sha256: str | None = None
    normalizer: str | None = None
    stat: StatTriple | None = None
    failure_class: str | None = None
    retry_after_ms: int | None = None
    skipped: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Three invariants, each of which a wrong branch in `acquire_unit()` would violate."""
        if self.failure_class is not None and self.failure_class not in ACQ_FAILURE_CLASSES:
            raise RouteError(
                f"{self.failure_class!r} is not one of unit.acq_failure_class's values (D80)",
                fix="use a FailureClass member, or discover.UNSEEN / discover.FILTERED",
            )
        if self.state in {FAILED, OUT_OF_SCOPE} and self.failure_class is None:
            raise RouteError(
                f"a unit in {self.state!r} carries the cause 05:392 gives the transition",
                fix="pass failure_class",
            )
        if self.state == ACQUIRED and not self.skipped and self.stat is None:
            raise RouteError(
                "an acquired unit carries the stat triple its digest was read under (05:344)",
                fix="pass stat, or report the outcome as skipped",
            )

    def statement(self) -> tuple[str, Mapping[str, object]]:
        """The one statement this outcome writes, with its parameters. Three outcomes, three SQL.

        Returning the pair rather than executing it is the house rule the module follows
        throughout: the SQL is a constant a test can read and the transaction is the caller's, which
        is what lets an acquisition ride in the same transaction as whatever else the caller is
        committing.
        """
        if self.state == ACQUIRED and self.skipped:
            return UNCHANGED_SQL, {
                "unit_uri": self.unit_uri,
                "indexed_at_ns": 0 if self.stat is None else self.stat.indexed_at_ns,
            }
        if self.state == ACQUIRED:
            triple = self.stat
            if triple is None:  # pragma: no cover -- __post_init__ makes this unreachable.
                raise RouteError(
                    "an acquired unit carries the stat triple it was read under",
                    fix="pass stat to Acquired, or report the outcome as skipped",
                )
            return ACQUIRED_SQL, {
                "unit_uri": self.unit_uri,
                "size": triple.size,
                "mtime_ns": triple.mtime_ns,
                "indexed_at_ns": triple.indexed_at_ns,
                "content_sha256": self.content_sha256,
                "normalizer": self.normalizer,
                "bytes": self.bytes_read,
            }
        return ACQ_FAILED_SQL, {
            "unit_uri": self.unit_uri,
            "state": self.state,
            "failure_class": self.failure_class,
            "retry_after": self.retry_after_ms,
        }


def acquire_unit(
    path: Path,
    unit_uri: str,
    stored: StoredStat,
    *,
    indexed_at_ns: int,
    max_unit_bytes: int,
    fmt: str = "",
    normalise: Normaliser = raw,
    verify_digests: bool = False,
    read: Callable[[Path, int], bytes] | None = None,
) -> Acquired:
    """Stat, decide, then stat-and-read -- or report the rung that made the read unnecessary.

    `02:472`'s hop 3 with `05:337`'s ladder in front of it. `fetch_local()` is `acquire.py`'s and it
    exists for one reason: *"Stat, THEN read. The order is the contract."* Stat-after-read produces
    a triple describing the file as it was **after** a racing writer finished, `stat_fresh()` then
    compares the new triple against itself on the next run, and the torn bytes in the store are
    never noticed.

    `verify_digests` promotes the unit to the digest rung (`05:352`) -- the bytes are read, the
    digest is computed, and it is compared against the stored one. A match is still a skip, because
    `05:361` is explicit that a re-read whose digest matches *"does **not** mint a new `gen`"*; it
    is reported with `bytes_read` set, which is what distinguishes it from the free skip in
    every number downstream.

    A `DriverError(TOO_LARGE)` from the bounded read is `05:330`'s mechanism 2, *"the `size = null`
    case and the lying-`Content-Length` case; a declared length is attacker-supplied"*, and it lands
    as `failed/too_large` rather than propagating: one 3 GiB file must not end a corpus.
    """
    try:
        pre = observe(path, indexed_at_ns=indexed_at_ns)
    except OSError:
        return _unreadable(unit_uri)
    verdict = freshness(stored, pre)
    #  D561: a skip preserves a digest, so a unit with none -- rostered, never read -- is read.
    if verdict != "changed" and not verify_digests and stored.content_sha256 is not None:
        return Acquired(unit_uri=unit_uri, state=ACQUIRED, verdict=verdict, skipped=True, stat=pre)

    kwargs = {} if read is None else {"read": read}
    try:
        triple, body = fetch_local(
            path, indexed_at_ns=indexed_at_ns, max_unit_bytes=max_unit_bytes, **kwargs
        )
    except DriverError as failure:
        return Acquired(
            unit_uri=unit_uri,
            state=FAILED,
            verdict=verdict,
            failure_class=failure.cls.value,
            retry_after_ms=failure.retry_after_ms,
        )
    except OSError:
        return _unreadable(unit_uri)

    digest, normalizer = content_digest(body, fmt=fmt, normalise=normalise)
    unchanged_bytes = verdict != "changed" and digest == stored.content_sha256
    return Acquired(
        unit_uri=unit_uri,
        state=ACQUIRED,
        verdict=verdict,
        bytes_read=len(body),
        content_sha256=digest,
        normalizer=normalizer,
        stat=triple,
        skipped=unchanged_bytes,
        diagnostics=() if normalizer is not None else (RAW_DIGEST_CODE,),
    )


def _unreadable(unit_uri: str) -> Acquired:
    """A file readable at `scandir` and gone at `stat` or `open`. `05:773`'s sibling, one step on.

    `unreadable` is `acquire.py`'s `skipped_why` key and not an `acq_failure_class` value, so the
    thirteen's own member for "these bytes are not usable" carries it. `CORRUPT_INPUT` rather than
    `TOO_LARGE` or `AUTH` because the classifier grades it permanent: a path that vanished mid-scan
    is not retried into the same run, and the next run's walk simply will not discover it.
    """
    return Acquired(
        unit_uri=unit_uri,
        state=FAILED,
        verdict="changed",
        failure_class=FailureClass.CORRUPT_INPUT.value,
    )


def pending_params(
    *, generation: int, connector: str = CONNECTOR, limit: int = PLAN_BATCH
) -> Mapping[str, object]:
    """The named parameters of `PENDING_ACQUISITION_SQL`, with the acquire-side attempt ceiling.

    `MAX_ATTEMPTS_TODAY` is `08:595`'s per-unit daily cap of 3 and `work.py` declares it; the same
    number bounds `acq_attempts_total` here because `05:419` makes the acquire counters *"the
    acquire-side twins"* of the work ones and names no second ceiling. Reported: the plan gives
    acquisition its own counters and no cap of its own to spend them against, so the twin's number
    is borrowed rather than invented.
    """
    return {
        "connector": connector,
        "generation": generation,
        "max_attempts": MAX_ATTEMPTS_TODAY,
        "limit": limit,
    }


def sweep_unseen(
    thread: StoreThread,
    *,
    scope_id: str,
    generation: int,
    complete: bool,
    connector: str = CONNECTOR,
    wait_ms: int = BATCH_WAIT_MS,
) -> int:
    """Mark every unit under `scope_id` that this generation's walk did not see. `05:365-372`.

    **It refuses on an incomplete scan and the refusal is the rule.** `05:371`: *"An **incomplete**
    scan never marks anything out of scope: `ingest_scope`'s absent-row rule -- 'coverage unknown,
    never nothing was excluded' -- applies to partial rows too."* A pause, a `max_units` bound or a
    crash all produce `complete = False`, and each of them would otherwise retire every document the
    walk had not reached yet -- which on a paused 100k corpus is tens of thousands of `cite`s a
    query can still resolve but a verdict would call absent.

    Returning `0` rather than raising for the incomplete case would be the wrong shape: "nothing was
    unseen" and "I was not allowed to look" are the two readings `ingest_scope`'s absent-row rule
    exists to keep apart, so this raises and the caller decides.
    """
    if not complete:
        raise RouteError(
            f"the scan of {scope_id!r} did not complete, so nothing under it is out of scope "
            f"(05:371: an incomplete scan never marks anything out of scope)",
            fix="resume discovery from the kept cursor until ingest_scope.complete is 1",
        )
    marked = 0

    def run(connection: _Rows) -> None:
        nonlocal marked
        cursor = connection.execute(
            OUT_OF_SCOPE_SQL,
            {"connector": connector, "prefix": f"{scope_id}*", "generation": generation},
        )
        marked = int(cursor.rowcount or 0)

    thread.run(Unit(name="discover.sweep_unseen", run=run, cost_class="free", wait_ms=wait_ms))
    return marked


def reset_stale_acquiring(
    thread: StoreThread, *, stale_ms: int = ACQUIRING_STALE_MS, wait_ms: int = BATCH_WAIT_MS
) -> int:
    """Return units stuck in `acquiring` to `discovered`. The lease reaper's stand-in. **D163.**

    Run at the start of a pass, beside `08:492`'s lease reaping and for the same reason: a `SIGKILL`
    between the claim and the write leaves a row nothing else can take. The threshold is a timeout
    and not a liveness check, because `unit` has no `claimed_by` to check against.
    """
    returned = 0

    def run(connection: _Rows) -> None:
        nonlocal returned
        cursor = connection.execute(RESET_ACQUIRING_SQL, {"stale_ms": stale_ms})
        returned = int(cursor.rowcount or 0)

    thread.run(Unit(name="discover.reset_acquiring", run=run, cost_class="free", wait_ms=wait_ms))
    return returned


PENDING_ACQUISITION_AFTER_SQL: Final[str] = PENDING_ACQUISITION_SQL.replace(
    " ORDER BY unit_uri", "   AND unit_uri > :after\n ORDER BY unit_uri"
)
"""`PENDING_ACQUISITION_SQL` resumed past a key: the keyset page `acquire_pending()` walks by.

**Without the key a failing unit is read three times in one pass.** `ACQ_FAILED_SQL` leaves a unit
in `failed`, and a failure whose class carries no `retry_after` leaves `acq_retry_after` NULL -- so
the unit satisfies `PENDING_ACQUISITION_SQL` again the moment its row is written, sorts first, and
comes back in the next page until `acq_attempts_total` reaches `MAX_ATTEMPTS_TODAY`. A pass visits
each unit once and the next run is the retry; `unit_uri > :after` is what makes "once" true.
"""


@dataclass(frozen=True, slots=True)
class AcquirePass:
    """What one `acquire_pending()` pass did, counted by the statement each unit wrote.

    `lost` is the units another process claimed between this pass's page read and its claim --
    `CLAIM_ACQUIRING_SQL`'s compare-and-swap matching zero rows, which is D163's skip and not a
    failure. `bytes_read` is `05:339`'s price of the ladder, summed.
    """

    acquired: int = 0
    unchanged: int = 0
    failed: int = 0
    lost: int = 0
    bytes_read: int = 0

    def plus(self, outcomes: Sequence[Acquired], *, lost: int) -> AcquirePass:
        """This pass with one page's outcomes added."""
        read = [one for one in outcomes if one.state == ACQUIRED and not one.skipped]
        return AcquirePass(
            acquired=self.acquired + len(read),
            unchanged=self.unchanged
            + sum(1 for one in outcomes if one.state == ACQUIRED and one.skipped),
            failed=self.failed + sum(1 for one in outcomes if one.state != ACQUIRED),
            lost=self.lost + lost,
            bytes_read=self.bytes_read + sum(one.bytes_read for one in outcomes),
        )


def acquire_pending(
    thread: StoreThread,
    *,
    generation: int,
    indexed_at_ns: int,
    max_unit_bytes: int = DEFAULT_MAX_UNIT_BYTES,
    connector: str = CONNECTOR,
    plan_batch: int = PLAN_BATCH,
    wait_ms: int = BATCH_WAIT_MS,
    verify_digests: bool = False,
    read: Callable[[Path, int], bytes] | None = None,
) -> AcquirePass:
    """`02:473`'s hop 3 for every unit this generation's walk saw: claim, read, write. W7.3w.

    Every statement it runs was here before it: `PENDING_ACQUISITION_SQL`, `CLAIM_ACQUIRING_SQL`,
    `acquire_unit()` and `Acquired.statement()`. **Nothing ran them in order**, which is the gap
    W7.3w found: `ow_add` rostered units into `discovered` and no code anywhere moved one out.

    One page is three steps and two transactions:

    1. **claim** -- one transaction: read up to `plan_batch` pending units past the last key, and
       compare-and-swap each into `acquiring`. `rowcount == 1` is the claim (D163), so a unit a
       second process took first is counted `lost` and left to it;
    2. **read** -- outside any transaction: `acquire_unit()` stats, decides, and reads. The file is
       the `unit_uri` itself -- an `fs` unit's canonical uri is its `realpath` in path form (05
       section 1.2), which is the file the bytes are, where the walked path is only the salt;
    3. **write** -- one transaction: each outcome's own statement, which names the state it leaves
       (`WHERE state = 'acquiring'`), so a unit `RESET_ACQUIRING_SQL` handed to someone else
       meanwhile is written by exactly one of them.

    **No transaction is held across a read.** A 2 GiB file read inside `BEGIN IMMEDIATE` would hold
    `store.write` for as long as the disk takes, and `ow_add` waits `INTERACTIVE_WAIT_MS` for it.

    **Nothing is copied into the content-addressed store**, which is D165's reading of hop 3 --
    08:860, *"the file *is* the blob"* -- and is unchanged here.
    """
    if plan_batch < 1:
        raise ValueError("plan_batch is a positive row count per transaction")
    params = pending_params(generation=generation, connector=connector, limit=plan_batch)
    after = ""
    total = AcquirePass()
    while True:
        page, keys = _claim_page(thread, params, after=after, wait_ms=wait_ms)
        if not keys:
            return total
        after = keys[-1]
        outcomes = [
            acquire_unit(
                Path(uri),
                uri,
                stored,
                indexed_at_ns=indexed_at_ns,
                max_unit_bytes=max_unit_bytes,
                verify_digests=verify_digests,
                read=read,
            )
            for uri, stored in page
        ]
        _write_outcomes(thread, outcomes, wait_ms=wait_ms)
        total = total.plus(outcomes, lost=len(keys) - len(page))


def _claim_page(
    thread: StoreThread, params: Mapping[str, object], *, after: str, wait_ms: int
) -> tuple[list[tuple[str, StoredStat]], list[str]]:
    """Step 1: one page past `after`, each unit compare-and-swapped into `acquiring`.

    Returns `(claimed, every key the page read)`. The second is what the next page resumes past,
    so a unit lost to another process is not read again by this one.
    """
    claimed: list[tuple[str, StoredStat]] = []
    keys: list[str] = []

    def run(connection: _Rows) -> None:
        rows = connection.execute(PENDING_ACQUISITION_AFTER_SQL, {**params, "after": after})
        for uri, _state, size, mtime, indexed, digest, settled, _derived in rows.fetchall():
            keys.append(str(uri))
            if connection.execute(CLAIM_ACQUIRING_SQL, {"unit_uri": uri}).rowcount != 1:
                continue
            triple = StatTriple(size=size or 0, mtime_ns=mtime or 0, indexed_at_ns=indexed or 0)
            claimed.append(
                (str(uri), StoredStat(triple=triple, settled_gen=settled, content_sha256=digest))
            )

    thread.run(Unit(name="discover.acquire.claim", run=run, cost_class="free", wait_ms=wait_ms))
    return claimed, keys


def _write_outcomes(thread: StoreThread, outcomes: Sequence[Acquired], *, wait_ms: int) -> None:
    """Step 3: each outcome's own statement, in one transaction."""
    statements = [outcome.statement() for outcome in outcomes]
    if not statements:
        return

    def run(connection: _Rows) -> None:
        for sql, values in statements:
            connection.execute(sql, values)

    thread.run(Unit(name="discover.acquire.write", run=run, cost_class="free", wait_ms=wait_ms))


SKIP_REASON_CLASSES: Final[Mapping[str, str]] = MappingProxyType(
    {
        SKIP_TOO_LARGE: FailureClass.TOO_LARGE.value,
        SKIP_UNREADABLE: FailureClass.CORRUPT_INPUT.value,
    }
)
"""How a `ScopeTally.skipped_why` key would read as an `acq_failure_class`, for the two that can.

`acquire.py`'s three skip reasons are *"a THREE-MEMBER set for this connector rather than a closed
framework vocabulary"*, and two of them name a condition the failure taxonomy also names. The third,
`path_outside_roots`, has no `FailureClass` and must not acquire one: it is `OW_PATH_OUTSIDE_ROOTS`
(`OW-A-007`), a policy refusal, and `05:70` calls it *"a refusal, not a warning"*.

**Nothing in this module writes a `unit` row from a skip, and `05:227` asks for one.** *"The host's
enumerate loop refuses a candidate whose `size > ingest.max_unit_bytes` before calling `fetch`:
`unit.state = 'failed'`, `acq_failure_class = 'too_large'`, no blob written."* `05:191-197`'s own
loop sketch orders the roster commit **before** the guards while `05:225` orders the guard before
the fetch, and only under the first reading does the row `05:227` names exist to be updated -- a
candidate carries no `unit_uri` by construction (`05:161`), so a guard that runs before the roster
write has no row to fail. W3.8 read it the second way and refuses inside the walk, which counts the
path in `skipped_why` and mints nothing. Recorded as **D168**; this mapping is what the fix would
use, and it is exported so a test can assert the gap rather than let somebody rediscover it.
"""
