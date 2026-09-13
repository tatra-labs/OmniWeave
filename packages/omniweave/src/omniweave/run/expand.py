"""`op.identify`: the one work row that has no driver, no decision and no cache layer.

W4.3's second clause (`16-roadmap.md:543`) -- *"`run/expand.py` and `op.identify` materialising part
rows under the water mark"* -- whose estimation basis is the sentence the module is built around:
*"a document's part count is not knowable without opening it, so this is an operator with a work
row, not a scan."* `02-architecture.md:70` gives the one-line charter: *"`run/expand.py`
op.identify -> unit.part_count, gated by the water mark."*

## 1. What `op.identify` writes, and the bold sentence that says what it does not

`02:474`, hop 4 of the worked ingest trace, is the specification and it is unusually complete:

> one `op.identify` `work` row (`driver`, `decision_id`, `dispatch_key` all NULL,
> `cost_class='free'`, batching alone), then `unit.part_count = 42`, `unit.state='identified'`.
> **No `parse.pdf` work row exists yet** -- see the ordering constraint above.

The ordering constraint at `02:456-461` is forced by three CHECKs rather than chosen:
`work.decision_id REFERENCES route_decision(decision_id)`, plus
`CHECK ((operator LIKE 'op.%') = (decision_id IS NULL))` and the two that chain `driver` and
`dispatch_key` to it. A `parse.*` row therefore **cannot exist before its route decision does** --
the FK has no referent and the first CHECK fails -- so the expander task runs two modules in order:
this one, then `omniweave.plan`'s single `INSERT` *"carrying `driver`, `decision_id`,
`dispatch_key`, `cost_class` and the recorded `cache_key` together. There is no window in which a
routed work row is half-populated, and there is no `UPDATE work SET driver = ...` anywhere in the
codebase."*

**`03-document-model.md:589` says this module also writes the per-part `work` rows, and `02:474`
says in bold that they do not exist yet.** 03's sentence exists to settle a different question
(ADR-5: whether `op.identify` writes L2 `part` rows -- it does not, `DocSink.add_part` is the sole
inserter) and it names the per-part `work` rows in passing as *"part-row expansion"*. Under 03's
reading this module would write rows whose `decision_id` is NULL and whose operator is `parse.pdf`,
which the first CHECK refuses outright. `02` wins and 03's phrase is the expander *task*, not this
module. Recorded as **D167**. So: `unit.part_count`, `unit.state`, and one `op.identify` work row.
Nothing else.

## 2. The cache key of a row that has no card

`work.cache_key` is `TEXT NOT NULL` on every row (`0004_runtime.sql:97`) and `08:861` gives
`op.identify` no cache layer at all -- *"its answer is `unit.part_count`, a store column"*. Those
two are not in tension: the key is not a cache *lookup*, it is the recorded memo `07` section 3.12
clause 1 reads -- *"the parse memo IS `work.status='done'` AND a matching `work.cache_key`"* -- so a
config change is a mismatch and never a silent reuse (I1).

What was missing is a way to compute one. `cache.cache_key()` took a `DriverCard`, and a core-only
Operator has none by construction (`04:2580`). `cache_key(card=None)` now covers it and the three
values it reads off a card are supplied from facts a core operator has: `free`, `ident.op_version`,
and no dependency set. One recipe, not two -- see **D164**, and `cache.py`'s own docstring for the
argument. `identity()` below is the `Producer` that feeds it.

## 3. The counter is injected, and the three providers live where this distribution cannot reach

`05:2135` registers `unit.part_count` as an evidence key with three providers --
`pdfium · officexml · builtin` -- and `05:2080` says they are *"disjoint by format"*. `05:2199`
gives the shape: *"`unit.part_count` comes from `FPDF_GetPageCount` on a PDF and from a sheet count
on an [office document]"*. `tools/layers.toml` gives `omniweave` exactly
`["omniweave_core", "omniweave_ports", "omniweave_office"]`, so the `pdfium` provider is behind a
distribution this module may not import, and the table that binds a format token to a provider needs
a `unit.format` that nothing yet writes (**D166**: the detection ladder of `05` sections 2.1-2.5 is
in no roadmap row and has no component row).

So `PartCounter` is a Protocol, `PART_COUNT_PROVIDERS` is `05:2135`'s own three names in its own
order, and `single_part` is the shipped counter -- `05:3186`'s case, *"op.identify -> part_count = 1
(granularity='document' on the card, so unit_part = '')"*. A counter that cannot answer raises
`DriverError(UNSUPPORTED_FORMAT)` and the unit fails permanently, which is the honest outcome: a
default of 1 for a 400-page scan would route one part, parse one page, and report a complete
document.

## 4. Its spend is charged to acquisition, and it can hold no reservation

`08:2303` is the `op.*` accounting hole: `route_spend.decision_id` is `NOT NULL REFERENCES
route_decision` and an `op.*` row has a NULL `decision_id` by CHECK, so *"a core-only step
**cannot** have a `route_spend` row"* and `budget_reservation.decision_id` being `NOT NULL` means it
cannot hold a reservation either. For `op.identify` that is *"correct and free"*. Its cost still
exists -- `05:1201`: *"`unit.part_count`'s provider cost is `linear_per_byte` for container formats
-- `FPDF_GetPageCount` is O(1), but counting messages in an mbox is a full scan -- so `op.identify`
records its `Spend` on `route_signal` under `unit.part_count` and is charged to acquisition, not to
a part."* `PartCount.spend` carries it and `StepMetrics.spend` delivers it to `work.cost_micros`,
which is the column `manifest.cost.op_micros` sums (`08:2318`).

## 5. The water mark, and what `plan.expand` counts

`08:880` names `expander` as a producer of the claimable set beside `discoverer`, under the same
`queue_high_water = 50000` / `queue_low_water = 25000` hysteresis. `enqueue()` therefore batches at
`plan_batch` and stops at a transaction boundary, the same shape `discover.RosterFeed` uses and for
the same reason -- and `05:1198` says the batch size is deliberately the same number: *"Part rows
and their decisions are written **512 per transaction**, the same batch size as roster enumeration,
so no transaction holds a 10,000-row write and the water mark can stop expansion between batches."*

`plan.expand`'s one declared field is `rows`, and this module counts the `op.identify` rows one
transaction wrote. That is the only reading available to a module whose whole output is those rows:
the per-part rows `05:1198` also calls "part rows" are `omniweave.plan`'s, and an event emitted here
cannot count rows another module has not written yet.

## 6. What this module is not

* **It does not detect, route, admit or plan.** It takes `format` as an argument (D166), and the
  `GATE` rule at `05:3037` that refuses a unit above `[ingest] max_parts` reads `unit.part_count`
  *after* this module has written it -- *"GATE, from `unit.part_count` (NOT NULL: `op.identify`
  precedes routing)"* -- so the cap is the router's and is deliberately absent here.
* **It does not own the loop or the claim.** `CLAIM_SQL` is `work.py`'s, and a NULL `dispatch_key`
  batches alone there (`08:755`), so a claimed `op.identify` batch is always one row.
* **It is synchronous**, for `pipeline.py`'s reason: the store thread blocks and `02:659` pushes the
  whole chain through `asyncio.to_thread`.

Specified in 02-architecture.md:70 and :456-476, 03-document-model.md:588-598, 05-ingest-and-
routing.md:389-398, :1196-1203 and :2130-2140, 08-runtime.md:755, :861 and :2303-2320, and
16-roadmap.md:543.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.acquire import CONNECTOR, PLAN_BATCH
from omniweave_core.cache import cache_key, unit_salt
from omniweave_core.errors import RouteError
from omniweave_core.events import EventKind
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store.queue import Statement
from omniweave_core.store.sqlite import BATCH_WAIT_MS, Unit
from omniweave_ports.types import DriverError, FailureClass, UnitRef

from omniweave.run.discover import ACQUIRED, WALKED_PATH_KEY

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.operator import RunContext, SpendVector
    from omniweave_core.store.queue import StepResultView
    from omniweave_core.store.sqlite import StoreThread

__all__ = [
    "IDENTIFIED_SQL",
    "IDENTIFY_FAILED_SQL",
    "IDENTIFY_INSERT_SQL",
    "MAX_PENDING_IDENTIFICATIONS",
    "OP_IDENTIFY",
    "OP_IDENTIFY_COST_CLASS",
    "OP_IDENTIFY_PRIORITY",
    "OP_IDENTIFY_VERSION",
    "PART_COUNT_PROVIDERS",
    "PART_COUNT_SIGNAL",
    "PENDING_IDENTIFY_SQL",
    "UNIDENTIFIED_PART",
    "IdentifyLedger",
    "PartCount",
    "PartCounter",
    "counted",
    "enqueue",
    "identify",
    "identify_key",
    "identity",
    "pending_params",
    "row_params",
    "salt_for",
    "single_part",
]


# =============================================================================================
# 1. The operator, as the three columns that make it core-only
# =============================================================================================


OP_IDENTIFY: Final[str] = "op.identify"
"""`work.operator`. The `op.` prefix is load-bearing: it is half of a CHECK.

`0004_runtime.sql` carries `CHECK ((operator LIKE 'op.%') = (decision_id IS NULL))`, so the prefix
is not a naming convention -- it is the column the database uses to decide whether a routing triple
is required or forbidden. `04:2580` files the five that carry it: *"core-only Operators;
`evaluate()` never runs for them, so their `work` rows carry NULL `decision_id`, `driver` and
`dispatch_key`."*
"""

OP_IDENTIFY_VERSION: Final[int] = 1
"""`work.op_version`, **an integer at every site**. `02:474` prints it as `op_version` on the row.

`03:212` states the rule the type obeys: *"`op_version` is an integer at every site: here, on the
`producer` table, and on `work`/`work_done` ... There is no `str()` round-trip anywhere in the
framework, so `"07"` and `7` can never disagree between this key and `work_identity`."* `1` because
this is the first shipped behaviour of the operator; a change to what `part_count` means for a
format is a bump, and the bump is what makes `work_identity` admit a second row for one unit.
"""

OP_IDENTIFY_COST_CLASS: Final[str] = "free"
"""`08:2307`: *"`op.identify`, `op.converge`, `op.lexicon` and `op.resolve` are `cost_class =
'free'`"*, and `02:474` prints `cost_class='free'` on the row itself. It is `free` in the pricing
sense and not in the wall-clock sense -- `05:1201` gives the provider cost as `linear_per_byte` for
container formats -- which is exactly why the cost still has to be recorded somewhere, and
`work.cost_micros` is where."""

OP_IDENTIFY_PRIORITY: Final[int] = 300
"""`08:619`'s priority. The highest in the table, and the reason is the opposite of `op.converge`'s.

*"`op.converge`, `op.identify` | a convergence step that loses to a 300,000-row parse backlog leaves
the graph incorrect for hours; `op.identify` is high for the opposite reason -- it is what *creates*
the part rows the queue then drains."* A low-priority identify starves the queue it feeds.
"""

UNIDENTIFIED_PART: Final[str] = ""
"""`work.unit_part` for an `op.identify` row: the empty string, which folds NULL.

`0004_runtime.sql:93`: *"`''` folds NULL: NULLs are distinct in a UNIQUE index"* -- and
`work_identity` is `UNIQUE (unit_uri, unit_part, operator, op_version)`, so a NULL here would let
one unit take two identify rows. `05:3186` prints the same empty string for the document-granularity
case and gives its reason on the card rather than on the operator.
"""

PART_COUNT_SIGNAL: Final[str] = "unit.part_count"
"""The `route_signal` key this operator's `Spend` is recorded under. `05:1201`.

*"so `op.identify` records its `Spend` on `route_signal` under `unit.part_count` and is charged to
acquisition, not to a part."* This module does not write `route_signal` -- that table is
`omniweave.route.evidence`'s -- it names the key so the writer and the payer agree on one string.
"""

PART_COUNT_PROVIDERS: Final[tuple[str, ...]] = ("pdfium", "officexml", "builtin")
"""`05:2135`'s three providers for `unit.part_count`, in its own order. *"Disjoint by format."*

`05:2080` states the disjointness as a rule about instances -- *"One instance per (key, provider):
`unit.part_count` has three, disjoint by format"* -- which is what makes the answer deterministic
without a tie-break: a format reaches exactly one provider, so there is never a second opinion to
rank. Two of the three need a library this distribution may not import; `builtin` is the one that
ships here, as `single_part`.
"""

MAX_PENDING_IDENTIFICATIONS: Final[int] = 2_048
"""How many un-committed identifications `IdentifyLedger` will hold before it refuses.

Eight claim batches at `[runtime.claim] batch.free = 256`, which is more in-flight identification
than a single-loop Supervisor can produce and small enough that a caller who never calls `forget()`
finds out in seconds rather than in a heap profile. The ledger is a map from a claimed row id to the
answer that row produced, and it is emptied by the completing transaction -- an unbounded one would
be the same defect `DegradationTally` was built to avoid in `manifest.py`.
"""


# =============================================================================================
# 2. The counter, and what it may not guess
# =============================================================================================


@dataclass(frozen=True, slots=True)
class PartCount:
    """One answer to *"how many addressable parts does this unit have"*, with its provenance.

    `provider` is one of `PART_COUNT_PROVIDERS` and it is not decoration: `05:2080` makes the
    provider half of a signal's identity, and a `part_count` whose provider is unrecorded cannot be
    invalidated when that provider's version moves.

    `spend` is `05:1201`'s -- the read that counting cost. It is a `SpendVector` and never micros,
    for INV-15's reason: *"THE ONLY PLACE MONEY APPEARS"* is `Spend.micros(book)`, and an operator
    that priced its own work would be the second place.
    """

    count: int
    provider: str = "builtin"
    spend: SpendVector | None = None

    def __post_init__(self) -> None:
        if self.count < 0:
            raise RouteError(
                f"unit.part_count is a count and {self.count} is not one "
                f"(05:2135 gives its domain as [0, 2^31))",
                fix="return 0 for an empty container, never a negative sentinel",
            )
        if self.provider not in PART_COUNT_PROVIDERS:
            raise RouteError(
                f"{self.provider!r} is not one of 05:2135's providers {PART_COUNT_PROVIDERS}",
                fix="name the provider that counted, or register a fourth in 05 section 5.2",
            )


class PartCounter(Protocol):
    """What `identify()` calls to learn a part count. The seam, and the whole of it.

    It receives the `UnitRef` and the format token because those are what the three providers
    discriminate on (`05:2080`, *"disjoint by format"*), and it receives nothing else -- no store
    handle, no clock, no ledger. A counter that could read the store could answer from a previous
    run's row, which is the one answer this operator exists to avoid.

    A counter that cannot answer raises `DriverError(UNSUPPORTED_FORMAT)`. It must not return `1`
    as a fallback: `05:3037` shows what a wrong count costs -- the `GATE` rule that refuses a
    10,000-page PDF reads `unit.part_count`, and a document that claims one part is routed as one
    part, parsed once, and reported complete.
    """

    def __call__(self, unit: UnitRef, *, fmt: str) -> PartCount: ...


def single_part(unit: UnitRef, *, fmt: str) -> PartCount:
    """The `builtin` provider's answer for a document-granularity unit: one part. `05:3186`.

    *"op.identify -> part_count = 1 (granularity='document' on the card, so unit_part = '')"*. This
    is the whole of what core can count without opening a format it has no reader for, and it is
    correct for exactly the units whose resolved driver declares `granularity = "document"` -- which
    the caller knows and this function does not, so the caller chooses it.

    It is not a default. `identify()` requires a counter and this one has to be passed.
    """
    del unit, fmt
    return PartCount(count=1, provider="builtin")


# =============================================================================================
# 3. The work row: the INSERT that is not `omniweave.plan`'s
# =============================================================================================


IDENTIFY_INSERT_SQL: Final[str] = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, status,
                 priority)
VALUES(:unit_uri, :unit_part, :operator, :op_version, :cache_key, :cost_class, 'pending',
       :priority)
ON CONFLICT(unit_uri, unit_part, operator, op_version) DO NOTHING
"""
"""The `op.identify` row. **The one `work` INSERT in the framework that is not the planner's.**

`02:459` gives `omniweave.plan` *"a single `INSERT` carrying `driver`, `decision_id`,
`dispatch_key`, `cost_class` and the recorded `cache_key` together"* -- and every column in that
list except `cost_class` and `cache_key` is one this statement deliberately omits. The three routing
columns are left to their NULL defaults because `CHECK ((operator LIKE 'op.%') = (decision_id IS
NULL))` requires it, and naming them here with `NULL` would read as a choice where the schema leaves
none.

`ON CONFLICT ... DO NOTHING` on `work_identity` is what makes `enqueue()` idempotent under a resume:
`08:503`'s recovery *"re-streams the roster"* rather than re-planning, so a unit that already has an
identify row must not acquire a second one, and a second `pending` row for one `(unit, operator,
op_version)` would be counted by `counts_by_status()` and claimed twice. `DO NOTHING` rather than
`DO UPDATE` because there is nothing to refresh: a row that exists is either pending, running or
done, and each of those is a state this statement must not touch.

`status` is the literal `'pending'` rather than a parameter, because an enqueue that could insert a
row in any other status would be a second writer for a state machine `work.py` owns.
"""

PENDING_IDENTIFY_SQL: Final[str] = """
SELECT u.unit_uri, u.content_sha256, u.bytes, u.media_type, u.format, u.derived
  FROM unit u
 WHERE u.connector = :connector
   AND u.last_seen_gen = :generation
   AND u.state = '{acquired}'
   AND u.part_count IS NULL
   AND NOT EXISTS (SELECT 1 FROM work w
                    WHERE w.unit_uri = u.unit_uri
                      AND w.operator = :operator
                      AND w.op_version = :op_version)
 ORDER BY u.unit_uri
 LIMIT :limit
""".replace("{acquired}", ACQUIRED)
"""The units that need an identify row: acquired, uncounted, and not already enqueued.

`part_count IS NULL` is the state machine's own predicate -- `0004_runtime.sql:58` writes *"NULL
until op.identify. Drives expansion"* and `05:397` puts *"`unit.part_count` is NOT NULL"* on the
`identified` state. It is redundant with the `NOT EXISTS` in the common case and it is not redundant
after a compaction: `work` rows are archived into `work_done` (`0004_runtime.sql:143`), so a unit
whose identify row has been compacted away would be re-enqueued by the `NOT EXISTS` alone.

The `NOT EXISTS` is checked against `work` rather than left to `IDENTIFY_INSERT_SQL`'s `ON CONFLICT`
because the two answer different questions: the conflict clause keeps the table correct, and this
clause keeps the batch honest -- `plan.expand`'s `rows` would otherwise count inserts that wrote
nothing, and a run's expansion progress would read as work where there was none.
"""

IDENTIFIED_SQL: Final[str] = """
UPDATE unit SET part_count = :part_count, state = 'identified'
 WHERE unit_uri = :unit_uri AND state = '{acquired}'
""".replace("{acquired}", ACQUIRED)
"""`02:474`'s second half: *"then `unit.part_count = 42`, `unit.state='identified'`"*.

**It rides in `complete()`'s transaction as the `derived_rows` participant, and that is not
optional.** `07:2730-2733` lists the five things one `complete()` commits *"together or not at
all"*, and derived rows are the first of them. If this landed in its own transaction, a crash
between the two would leave `work.status='done'` with `unit.part_count` still NULL -- and the work
row being `done` is exactly what stops anything from ever computing it again. The unit would sit in
`acquired` forever with no queue row to move it, which is the shape of a corpus that is 99% indexed
and never finishes.

`WHERE ... AND state = 'acquired'` for the same reason `ACQUIRED_SQL` names the state it is leaving:
a second process that identified the unit first has already moved it, and a blind `UPDATE` would
re-stamp a `planned` unit back to `identified` and re-open a window the planner had closed.
"""

IDENTIFY_FAILED_SQL: Final[str] = """
UPDATE unit SET state = 'failed', acq_failure_class = :failure_class
 WHERE unit_uri = :unit_uri AND state = '{acquired}'
""".replace("{acquired}", ACQUIRED)
"""`05:395`'s terminal exit: *"failed (a permanent FailureClass, no doc row)"*.

The unit stops here and no `doc` row is ever written, which is what `07:2229`'s absence gate reads.
`acq_failure_class` carries the cause even though the failure is an identification rather than an
acquisition: `unit` has exactly one column for "why did this unit stop", the state machine at
`05:389-395` routes both arrows into it, and a second column would be a migration on a charter table
to distinguish two things `ow doc verify` prints identically.
"""


def row_params(unit_uri: str, cache_key_hex: str) -> Mapping[str, object]:
    """The named parameters of `IDENTIFY_INSERT_SQL` for one unit.

    Every value except the two arguments is a module constant, which is the point: an `op.identify`
    row differs from another `op.identify` row in exactly the unit it names and the key it recorded.
    """
    return {
        "unit_uri": unit_uri,
        "unit_part": UNIDENTIFIED_PART,
        "operator": OP_IDENTIFY,
        "op_version": OP_IDENTIFY_VERSION,
        "cache_key": cache_key_hex,
        "cost_class": OP_IDENTIFY_COST_CLASS,
        "priority": OP_IDENTIFY_PRIORITY,
    }


def identity(code_fingerprint: str = "") -> Producer:
    """The `Producer` this operator writes under. `03:396`: **one type, two layers.**

    *"`Producer` ... == L5's `OperatorIdentity`. ONE TYPE, TWO LAYERS"* -- so the record that feeds
    `cache_key()` is the same record a `block` row's `producer_id` would point at, and there is no
    conversion between the two names. `op.identify` writes no blocks, so nothing points at it; the
    type is still the right one, because the alternative is a second shape for the same tuple.

    `code_fingerprint` is the caller's -- it is *"the version of the code that produced this"* and
    this module cannot know its own build. It reaches the key only when the operator is `cheap`,
    which a `free` one is.
    """
    return Producer(
        operator=OP_IDENTIFY, op_version=OP_IDENTIFY_VERSION, code_fingerprint=code_fingerprint
    )


def identify_key(
    unit: UnitRef,
    ctx: RunContext,
    *,
    salt: str,
    code_fingerprint: str = "",
    recipe: int | None = None,
) -> str:
    """`work.cache_key` for an `op.identify` row, through the one `cache_key()`. **D164.**

    `card=None` is the core-operator arm and `cache.py`'s docstring carries the argument for why
    that is one recipe rather than two. `salt` comes from `cache.unit_salt()`, which for an `fs`
    unit is the walked path relative to `roots.source` -- `derived["walked_path"]` is where
    `discover.py` put it and D143 is why it had to be put anywhere at all.

    `recipe` defaults to `cache_key()`'s own `DEFAULT_CACHE_RECIPE` rather than being restated here:
    `[cache] recipe` is a knob, and a module constant shadowing it would make the knob a lie.
    """
    extra = {} if recipe is None else {"recipe": recipe}
    return cache_key(unit, identity(code_fingerprint), None, ctx, salt=salt, **extra)


def salt_for(derived: Mapping[str, object], *, source_root: str, connector: str = CONNECTOR) -> str:
    """`cache.unit_salt()` fed from the roster row `discover.py` wrote. D143's read site.

    The `fs` branch needs the walked path and the source root and refuses without both. A roster row
    written before `WALKED_PATH_KEY` existed has neither, so this raises rather than substituting
    the canonical uri: a salt computed from `realpath`'s output is the exact value `08:1364` says
    must not be used, and silently using it would collapse two aliases into one cache entry without
    anything saying so.
    """
    walked = derived.get(WALKED_PATH_KEY)
    if connector == CONNECTOR and not isinstance(walked, str):
        raise RouteError(
            f"unit.derived[{WALKED_PATH_KEY!r}] is missing, so this unit's cache salt cannot be "
            f"reproduced (D143; 08:1364 forbids falling back to the canonical uri)",
            fix="re-run discovery on this scope: run/discover.py stamps it at first sight",
        )
    return unit_salt(
        connector,
        walked_path=walked if isinstance(walked, str) else "",
        locator="" if connector == CONNECTOR else str(derived.get("locator", "")),
        source_root=source_root,
    )


# =============================================================================================
# 4. Enqueue: the expander as a producer under the water mark
# =============================================================================================


class _Rows(Protocol):
    """The one cursor method this module's statements need. `acquire.py`'s device, same reason.

    `sqlite3` is banned outside `store/sqlite.py` by `TID251` (INV-17), so a closure handed to the
    store thread is annotated against the shape it uses rather than against the type it receives.
    """

    def executemany(self, sql: str, parameters: Sequence[Mapping[str, object]], /) -> object: ...


def enqueue(
    thread: StoreThread,
    rows: Iterable[Mapping[str, object]],
    *,
    emit: Callable[..., object] | None = None,
    pause: Callable[[], bool] = lambda: False,
    plan_batch: int = PLAN_BATCH,
    wait_ms: int = BATCH_WAIT_MS,
) -> tuple[int, bool]:
    """Write `op.identify` rows at `plan_batch` per transaction, stopping at a boundary on a pause.

    `05:1198`: *"Part rows and their decisions are written **512 per transaction**, the same batch
    size as roster enumeration, so no transaction holds a 10,000-row write and the water mark can
    stop expansion between batches."* `08:880` names `expander` a producer of the claimable set
    beside `discoverer` under the same hysteresis.

    The pause is checked **after** a commit and never mid-batch, which is the same boundary
    `discover.RosterFeed` uses: a transaction that is open when the queue crosses the high-water
    mark is finished, because abandoning it would discard rows the walk has already paid for and
    `08:875` says the producer *"pauses at a safe boundary and never drops"*.

    Returns `(rows written, paused)`. `rows` is consumed lazily so a caller may pass a generator
    over `PENDING_IDENTIFY_SQL`'s result and hold one batch rather than a corpus.

    `plan_batch` defaults to `acquire.PLAN_BATCH`, which is `KEYS["runtime.plan_batch"].default`
    and therefore the same 512 `05:1198` names -- one declaration, read from the config register
    rather than transcribed, so a change to the knob moves both producers together.
    """
    if plan_batch < 1:
        raise ValueError("plan_batch is a positive row count per transaction")
    written = 0
    paused = False
    batch: list[Mapping[str, object]] = []
    for row in rows:
        batch.append(row)
        if len(batch) < plan_batch:
            continue
        written += _commit(thread, batch, wait_ms=wait_ms, emit=emit)
        batch = []
        if pause():
            paused = True
            break
    if not paused and batch:
        written += _commit(thread, batch, wait_ms=wait_ms, emit=emit)
    return written, paused


def _commit(
    thread: StoreThread,
    batch: Sequence[Mapping[str, object]],
    *,
    wait_ms: int,
    emit: Callable[..., object] | None,
) -> int:
    """One transaction of `op.identify` inserts, and the `plan.expand` that reports it.

    The event is emitted after the transaction rather than before it, because `plan.expand`'s
    `rows` is a statement about what is durable -- an event that announced an open transaction would
    be a count a crash could unwrite.
    """
    if not batch:
        return 0
    params = list(batch)

    def run(connection: _Rows) -> None:
        connection.executemany(IDENTIFY_INSERT_SQL, params)

    thread.run(Unit(name="expand.op_identify", run=run, cost_class="free", wait_ms=wait_ms))
    if emit is not None:
        emit(kind=EventKind.PLAN_EXPAND, fields={"rows": len(params)})
    return len(params)


def pending_params(
    *, generation: int, connector: str = CONNECTOR, limit: int = PLAN_BATCH
) -> Mapping[str, object]:
    """The named parameters of `PENDING_IDENTIFY_SQL`."""
    return {
        "connector": connector,
        "generation": generation,
        "operator": OP_IDENTIFY,
        "op_version": OP_IDENTIFY_VERSION,
        "limit": limit,
    }


# =============================================================================================
# 5. Execute: the counter, the `StepResult`, and the statement that rides with it
# =============================================================================================


def identify(
    unit: UnitRef,
    *,
    count: PartCounter,
    cache_key_hex: str,
    fmt: str = "",
    emit: Callable[..., object] | None = None,
) -> tuple[StepResult, PartCount | None]:
    """Run the counter for one claimed row and build the `StepResult` `complete()` takes.

    **The Operator contributes an outcome and metrics; the runner constructs the rest.** `08:238`
    lists what a driver may not claim -- `SKIPPED_CACHED`, `SKIPPED_UNCHANGED`, `DEFERRED_BUDGET`,
    `CANCELLED`, an identity, a `cache_key`, a price, `rows_written`, a `Degradation` -- and
    `op.identify` is core-only, so this module *is* the runner for it and constructs all of them.
    What it does not construct is a price: `StepMetrics.micros` is left `0` and the `PriceBook`
    applies `PartCount.spend` above (INV-15).

    `rows_written` is `1` on success and it is the `unit` row -- `IDENTIFIED_SQL`'s single update.
    Counting the `work` row itself would double-count the transition that `complete()` performs.

    A counter raising `DriverError` becomes `FAILED_PERMANENT` with the driver's own class, not
    `DRIVER_BUG`: `05:3037`'s ladder treats `unsupported_format` as a routing fact a corpus report
    can act on, and re-labelling it would hide a whole format class behind an internal error. The
    unit goes to `failed` through `IDENTIFY_FAILED_SQL`, which is `05:395`'s *"a permanent
    FailureClass, no doc row"*.

    Returns `(result, part_count)` -- `None` for a failure. The pair is what `IdentifyLedger.record`
    takes, and returning it rather than writing it keeps the transaction the caller's.
    """
    try:
        answer = count(unit, fmt=fmt)
    except DriverError as failure:
        return (
            StepResult(
                outcome=Outcome.FAILED_PERMANENT,
                unit=unit,
                identity=identity(),
                cache_key=cache_key_hex,
                failure_class=failure.cls,
                failure_message=failure.message,
            ),
            None,
        )
    if emit is not None:
        emit(kind=EventKind.PLAN_IDENTIFY, fields={"part_count": answer.count})
    return (
        StepResult(
            outcome=Outcome.OK,
            unit=unit,
            identity=identity(),
            cache_key=cache_key_hex,
            metrics=StepMetrics(spend=answer.spend, rows_written=1),
        ),
        answer,
    )


class IdentifyLedger:
    """The `derived_rows` contribution for `op.identify`, and the map it closes over.

    `store/queue.py` declares `Contribution = Callable[[int, StepResultView], Sequence[Statement]]`
    and says *"P4 supplies contributions when it has rows to write"*. This is one. It is a class
    rather than a function because the statement it contributes needs the **answer**, and
    `StepResultView` -- the narrow Protocol `complete_plan()` passes -- carries `outcome`,
    `cache_key`, `failure_class` and `metrics` and no unit and no identity. A callable that could
    read `.unit` would be one that only accepts the concrete `StepResult`, which is not assignable
    to the seam's type.

    So the executor records `(row_id -> what that row produced)` before calling `complete()`, and
    the contribution looks the row up. **It does not pop.** `complete()` returns `False` when the
    commit predicate matches zero rows and the whole transaction rolls back (`07:58`), and an entry
    consumed by a rolled-back plan would leave a retry with nothing to write. `forget()` is the
    caller's acknowledgement that the commit stuck, and `MAX_PENDING_IDENTIFICATIONS` is what turns
    a caller who never calls it into an error rather than a leak.

    A row this ledger does not know contributes nothing, which is how one contribution serves a
    store that also completes `parse.*` rows: the map is the dispatch.
    """

    __slots__ = ("_answers", "_max")

    def __init__(self, *, max_pending: int = MAX_PENDING_IDENTIFICATIONS) -> None:
        self._answers: dict[int, tuple[str, PartCount | None]] = {}
        self._max = max_pending

    def __len__(self) -> int:
        return len(self._answers)

    def record(self, row_id: int, unit_uri: str, answer: PartCount | None) -> None:
        """Remember what a claimed row produced, so its statement can be built at commit time."""
        if row_id not in self._answers and len(self._answers) >= self._max:
            raise RouteError(
                f"{len(self._answers)} identifications are recorded and uncommitted, at the "
                f"{self._max} ceiling: a caller is not calling forget() after complete()",
                fix="call IdentifyLedger.forget(row_id) once complete() has returned True",
            )
        self._answers[row_id] = (unit_uri, answer)

    def forget(self, row_id: int) -> None:
        """Drop a row whose transaction committed. Unknown ids are ignored, because a caller that
        forgets twice is not a caller that did anything wrong."""
        self._answers.pop(row_id, None)

    def __call__(self, row_id: int, result: StepResultView) -> Sequence[Statement]:
        """One `Statement`, or none. The `unit` update that rides in `complete()`'s transaction."""
        known = self._answers.get(row_id)
        if known is None:
            return ()
        unit_uri, answer = known
        if result.outcome == Outcome.FAILED_PERMANENT:
            return (
                Statement(
                    participant="derived_rows",
                    name="unit_identify_failed",
                    sql=IDENTIFY_FAILED_SQL,
                    params={
                        "unit_uri": unit_uri,
                        "failure_class": result.failure_class
                        or FailureClass.UNSUPPORTED_FORMAT.value,
                    },
                ),
            )
        if answer is None or result.outcome != Outcome.OK:
            return ()
        return (
            Statement(
                participant="derived_rows",
                name="unit_identified",
                sql=IDENTIFIED_SQL,
                params={"unit_uri": unit_uri, "part_count": answer.count},
            ),
        )


def counted(unit_uri: str, content_sha256: str, byte_len: int, media_type: str = "") -> UnitRef:
    """A `UnitRef` for an `op.identify` row: the whole unit, never a part.

    `part` is the empty string because the count is a property of the container and not of one of
    its members -- the same empty string `UNIDENTIFIED_PART` puts on the `work` row, and for the
    same index reason. `UnitRef` carries five fields and `03`'s docstring gives the reason it is
    that narrow: *"the host mints every durable identity, which is what makes a fragment portable
    between stores."*
    """
    return UnitRef(
        uri=unit_uri,
        part=UNIDENTIFIED_PART,
        content_sha256=content_sha256,
        byte_len=byte_len,
        media_type=media_type,
    )
