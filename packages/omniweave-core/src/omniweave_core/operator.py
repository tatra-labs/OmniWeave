"""The runner's vocabulary: `Outcome`, `StepMetrics`, `StepResult`, `RunContext`, `CancelToken`.

02-architecture.md section 2 row 10 is this module's charter, and the exclusion names two things
that are elsewhere for two different reasons:

> | 10 | Operator vocabulary | `omniweave_core.operator` | `Operator` (**a `Protocol`**, not an
> abstract base class -- the spelling `OperatorABC` is struck, ADR-1 decision 7; the runtime
> section 6.1 is its home), `OperatorIdentity` (**is** `Producer`), `StepResult`, `Outcome`,
> `StepMetrics`, `RunContext`, `Roots`, `CancelToken` | **scheduling (L5's) and pricing
> (`route/spend.py`'s)** | the `Protocol` plus the dataclasses | T-CONTRACT |

08-runtime.md:177-179 is stronger than a home: *"**The block below is the sole home of `Outcome`,
`StepMetrics` and `StepResult`.** The charter names `Outcome` four times and defines it nowhere, so
this is not a second home; every other document cites this section and prints no field list of its
own."* Everything in sections 1-4 below is transcribed from 08:185-283 and :330-360, field names and
order verbatim, and the two deliberate divergences are argued where they occur.

**This module is the hinge of P4.** It carries no roadmap row of its own -- 16-roadmap.md:537-550
has ten W4.x items and none of them names it -- because it is a *contract* module rather than a work
item: 11-repo-layout.md:195 lists `operator.py registry.py discovery.py` on one line and the other
two already existed. Three of P4's remaining cells block on what is declared here. W4.2's loop needs
`RunContext` and `CancelToken`; W4.5's `admit()` returns `DEFERRED_BUDGET`, which is an `Outcome`
member; W4.7's dispatch returns `StepResult`. Building any of them first would have meant inventing
the type all three share, which is the `route_decision` mistake W4.1's own estimation basis names.

**Nothing here runs, and nothing here is async.** The block's header comment is the rule:
*"SYNCHRONOUS, stdlib only (G23: no asyncio, no selectors)"*. 08:298-320 answers the objection this
raises at length -- the charter's D6 module inventory puts `RunContext` here while D6's decision
text says the one `asyncio` Supervisor never lives in `omniweave-core` -- and the resolution is
normative rather than incidental: `RunContext` is a frozen value object with no loop, no store
handle and no `async def`; `ServiceRegistry.handle()` performs **blocking** attach-or-spawn; and
`BudgetLedger` headroom is *"computed in SQL on a synchronous connection, never awaited"*. The field
is a **reference**: core defines the shape, `omniweave` constructs the value. Moving the type into
`omniweave/run/` *"would force an out-of-tree Operator to import `omniweave` to type its own
`run()` -- inverting the dependency direction the charter exists to enforce"*.

## Still owed, and by which cell

Five types are named in an annotation here and have no home in the tree yet; the table below
carries a sixth, `ServiceRegistry`, which is **called** rather than named and is therefore reached
through `ServiceRegistryView` instead of through a suppression.

A seventh row left this table when W4.5 landed `omniweave_core.budget`: `RUF100` failed the build
over `BudgetLedger`'s now-unused `# noqa`, which is the mechanism working exactly as described here.
Each remaining forward reference carries that suppression on its own line, and it is a
**self-cleaning** device rather than a way of hiding something: ruff fails the build the day the
name resolves, so the cell that lands the type is told to delete the comment and make the import
real.

| name | home | cell |
|---|---|---|
| `Limits` | `omniweave_core.limits` (02 row 7) | unscheduled -- see below |
| `CacheLayer` | `omniweave_core.cache` (02 row 18) | W4.4 |
| `TraceSink` | `omniweave_core.events` (02 row 21), printed at 15:362 | W4.8 |
| `ServiceRegistry` | `omniweave_core.modelserver` (02 row 15) | W4.9 |
| `Degradation` | 15-observability.md's, by charter erratum E15 | P7 |
| `WorkSpec` | 08:2842 -- *"what `Operator.plan()` emits"* | W4.3's planner |

`Limits` is the odd one: the *module* exists and holds every `MAX_*` constant, but the **record**
08:275 hands an operator does not, and no cell is scheduled to build it. 08:2790 lists it among the
terms the charter's own lock has no row for, which is the same gap seen from the other side.
`Degradation`'s path is `omniweave_core.observe.degradation`, which `discovery.py:325` already names
in a placeholder of its own.

Two more can never become imports here, because `tools/layers.toml` gives `omniweave_core` exactly
`["omniweave_ports"]` and both live in the `omniweave` distribution. They are declared as
structural stand-ins in section 2, the device `store/graph.py` introduced for this exact case and
`store/queue.py` reuses for `StepResultView`: `Spend` (05-ingest-and-routing.md:2370, reached as
`SpendVector`) and `Admission` (08:669-700, reached as `AdmissionView`).

## What moved here, and from where

`StepMetrics` and `StepResult` were written in `store/queue.py` at P2 under a docstring that said
what would happen next -- *"Deleted when `omniweave_core/operator.py` lands (P4). `StepMetricsView`
is what survives."* This is that deletion. The two `*View` Protocols stay there, because they are
the *read surface* `complete()` is typed against and keeping them is what stops `store/` from
growing an import edge into the runtime's vocabulary. `CACHE_KEY_HEX_LEN` came with them: it is
`StepResult.__post_init__`'s only length rule, so it belongs beside the invariant that uses it.

`SpendVector` came from `store/graph.py`, where it was declared for `end_run(status, spend)` while
`Spend` had no home. Its reasoning is unchanged and its docstring is largely intact; what changed is
that a second structural description of the same eight attributes would have had to be written here
today, and INV-21 does not distinguish between two declarations of a type and two declarations of
its shape. `store/graph.py` imports it from here and keeps it in its own `__all__`.

## Three defects this cell found

**D138** -- `work.failure_message` is a real column that 08:113-125's own UPDATE binds, and
08:209-231's `StepResult` has no field to feed it. Carried here as `failure_message`, the one field
this class holds that the plan does not print, for the reason `StepResultView` already records.

**D139** -- 08:202 gives `StepMetrics.spend` the default value `Spend()` inside a block headed
*"stdlib only"*, and `Spend` is `omniweave.route`'s. A **reference** to a type core may not import
is exactly what 08:298-320 defends; a **construction** of one is not, and the distinction is the
plan's own. Shipped as `spend: SpendVector | None = None`.

**D140** -- 08:2834 says `RunContext` carries *"six digests"*; the printed block carries five, the
`run` table carries five, and the two fives are not the same five. `catalog_digest` is on the
context and on no row.

Stdlib plus `omniweave_ports` and two intra-core imports (INV-2, G1). Not one of the nine LAZY
names, and not imported by `omniweave_core/__init__.py`: `import omniweave_core.operator` is what a
caller does on purpose.

Tier T-CONTRACT: 02-architecture.md section 2 row 10, 18-api-sketch.md:844.

Specified in 08-runtime.md sections 1.3 and 6.1 (:177-283, :320-360, :1900-1960), 02-architecture.md
section 2 row 10 and section 5.3, and 18-api-sketch.md:844.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol, runtime_checkable

from omniweave_ports.types import ArtifactRef, CostClass, FailureClass, ServiceHandle, UnitRef

from omniweave_core.budget import BudgetLedger
from omniweave_core.clock import Clock
from omniweave_core.model.records import Producer

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "CACHE_KEY_HEX_LEN",
    "CROCKFORD32",
    "RUN_ID_PREFIX",
    "ULID_CHARS",
    "ULID_ENTROPY_BYTES",
    "AdmissionView",
    "CancelReason",
    "CancelToken",
    "Cancellation",
    "Operator",
    "OperatorIdentity",
    "Outcome",
    "Roots",
    "RunContext",
    "ServiceRegistryView",
    "SpendVector",
    "StepMetrics",
    "StepResult",
    "new_run_id",
    "ulid",
]


# ---------------------------------------------------------------------------------------------
# 1. `OperatorIdentity` -- one type, two layers, one table.
# ---------------------------------------------------------------------------------------------

OperatorIdentity = Producer
"""**`Producer` IS `OperatorIdentity`** -- an alias, never a subclass and never a copy.

08:1930-1940 prints the mapping as an equality between layers rather than a conversion between
types::

    Producer.operator          = origin_operator  = '<port>.<family>'   <- THE OWNERSHIP GRAIN
    Producer.op_version        = the operator's schema_version, AS AN INTEGER

and gives the reason the two names must resolve to one object: *"`op_version` is an integer at
**every** site. The two conversion lines an earlier draft carried (`str(...)` out, `int(...)` back)
were a lossy round-trip through text on an **identity** input: `"07"` and `7` canonicalise
differently, so `producer_identity` and `work_identity` could disagree about the same operator and
neither index would notice."*

A `class OperatorIdentity(Producer)` would restore exactly that hazard in the type system instead of
in a format string: two classes, two `__eq__`s, and a `producer` row that round-trips through the
wrong one. The declaration is `omniweave_core.model.records`' (03:396-401) because every `block`,
`page` and `rel` row carries a `producer_id` FK to that table; L5 reads the same object under the
name its own layer uses.
"""


# ---------------------------------------------------------------------------------------------
# 2. The two structural stand-ins, for types core may never import.
# ---------------------------------------------------------------------------------------------


@runtime_checkable
class SpendVector(Protocol):
    """The seven physical units plus `provider`, as the runner needs to read them.

    **A structural description, never a second declaration.** `Spend` is 05-ingest-and-routing.md
    section 6.1's (:2366-2374) and 02-architecture.md row 35 homes it in `omniweave.route`, a
    distribution `tools/layers.toml` forbids core from importing in either direction of the arrow.
    A Protocol naming the eight attributes lets `StepMetrics` carry a spend vector and `end_run`
    canonicalise one into `derive_run.spend` without declaring the type twice (INV-21) and without
    an `Any` that would let a `dict` through.

    `micros()` is deliberately absent: *"THE ONLY PLACE MONEY APPEARS"* is `Spend.micros(book)`
    (INV-15), `StepMetrics` carries its priced result in a separate `micros` field that only the
    runner writes, and `derive_run.spend` holds *"canonical JSON of Spend. NO DOLLARS HERE"*
    (0002:203). A sink that could price would be a second place money appears.

    Declared here rather than in `store/graph.py`, where it was written at P2: `StepMetrics` needs
    the same shape, `store/` is one of the nine LAZY names, and a type the runner's vocabulary
    depends on cannot live behind a lazy import of the store. `store/graph.py` imports it from here
    and re-exports it, so nothing that named it there breaks.
    """

    wall_ms: int
    cpu_ms: int
    gpu_ms: int
    tokens_in: int
    tokens_out: int
    calls: int
    bytes_egress: int
    provider: str


@runtime_checkable
class AdmissionView(Protocol):
    """The two water marks, and deliberately not the four semaphore families.

    `Admission` is 08:669-700's and it lives in `omniweave/run/supervisor.py`, so this is the same
    cross-distribution case `SpendVector` answers -- with one extra reason for the narrowing.
    `Admission`'s four families are `asyncio.BoundedSemaphore` instances (08:693), and an annotation
    naming that type would put `asyncio` in `omniweave_core`'s source. G23 asserts that a bare
    `import omniweave_core` reaches neither `asyncio` nor `selectors`, and `pyproject.toml` bans the
    import outright outside `omniweave/run/` -- *"INV-3: omniweave/run/ only. Core must not import a
    loop."* The invariant is a mechanism here rather than a rule, and a type-checking-only import
    would be the first hole in it.

    What survives the narrowing is what an operator can legitimately read: the producer's two water
    marks, which 08:703-720 makes a hysteresis pair (`queue_high_water = 50000`,
    `queue_low_water = 25000`, a 2:1 gap) rather than one threshold. Nothing in core reads even
    these; they are here so that `RunContext.admission` names a shape instead of `object`, and so
    that an out-of-tree Operator typing its own `plan()` against `RunContext` gets a field it can
    use rather than one it must cast.
    """

    high_water: int
    low_water: int


@runtime_checkable
class ServiceRegistryView(Protocol):
    """One method, because `RunContext.service()` calls exactly one.

    02-architecture.md row 15 gives `omniweave_core.modelserver` the whole of seam S3 --
    `ServiceSpec`, `attach_or_spawn`, model-id verification, the 32-byte token in a 0600 sentinel --
    and names the typical call `ServiceRegistry.get(name) -> ServiceHandle`. That module is W4.9's
    and does not exist, but unlike the seven forward references in this module's docstring, this one
    is **called** rather than annotated: 08:283's `def service(self, name)` has a body here. A
    forward reference cannot be called, so the alternative was to leave `service()` as a `...` stub
    that returns `None` at runtime.

    Narrow on purpose, in the `StepResultView` spirit: a Protocol listing only what is read is what
    lets W4.9's real `ServiceRegistry` satisfy this with no edit on either side.
    """

    def get(self, name: str) -> ServiceHandle:
        """Return the handle for a **named** Service. A Service is named and never routed."""
        ...


# ---------------------------------------------------------------------------------------------
# 3. `Outcome` -- eight members, and the count is load-bearing.
# ---------------------------------------------------------------------------------------------


class Outcome(StrEnum):
    """What the runner produced. 08:189-198, names, values and order verbatim.

    **Eight, and the count is the specification** (08:179-183): *"`Store.complete(row_id, gen,
    result: StepResult) -> bool` is typed against this block, and adding or removing a member is one
    edit to this enum **and** to section 1.2's transition table in the same change -- that table is
    the specification, and a member with no row in it is a rejectable PR."* `omniweave_core.work`
    holds that table as `TRANSITIONS` and its eight `OUTCOMES` strings; `test_operator.py` asserts
    this enum and those two agree, in both directions, which is what makes the rejectable PR a
    failing test instead of a reviewer's memory.

    A `StrEnum` rather than a `str` domain, and the two coexist on purpose. `work.OUTCOMES` was
    minted as a tuple at W4.1 under the argument that *"a second `StrEnum` here would be the second
    home that sentence forbids"*; a `StrEnum` member compares and binds equal to its value, so every
    check in that module accepts these members unchanged, and the `work` table stores the value.

    Two of the eight are **not failures** and the distinction is load-bearing twice over.
    `DEFERRED_BUDGET` is 08:695's *"NOT a failure"* -- a deferred row keeps its attempt count, drops
    to priority -100 and is swept by the deferred sweeper, so a permanently-exhausted budget costs
    one probe per 30 minutes instead of a hot loop. `CANCELLED` has **two** producers, this enum's
    `CancelToken` and a superseded `claimed_gen`, and 08:8.1 exists to keep them apart (see
    `CancelReason`'s consequence (a)).
    """

    OK = "ok"
    OK_PARTIAL = "ok_partial"
    """Usable but incomplete; `partial_reason` required."""
    SKIPPED_CACHED = "skipped_cached"
    """A cache hit; `Spend` replayed, `was_cache_hit=True`."""
    SKIPPED_UNCHANGED = "skipped_unchanged"
    """`stat_fresh` plus a matching `work.cache_key`."""
    FAILED_TRANSIENT = "failed_transient"
    """`retry_after_ms` required."""
    FAILED_PERMANENT = "failed_permanent"
    """`failure_class` required."""
    DEFERRED_BUDGET = "deferred_budget"
    """`deferred_dim` required; **NOT a failure**."""
    CANCELLED = "cancelled"
    """A `CancelToken`, or a superseded generation."""


# ---------------------------------------------------------------------------------------------
# 4. `StepMetrics` and `StepResult` -- what the runner produces.
# ---------------------------------------------------------------------------------------------

CACHE_KEY_HEX_LEN: Final = 64
"""`sha256_canonical` hex is 64 characters, and `StepResult.cache_key` is checked against it.

Moved here from `store/queue.py` with the type whose invariant it is: 08:230 writes the check as
`if len(self.cache_key) != 64`, and a constant lives beside the one rule that reads it. The value is
a property of `sha256` rather than a knob, which is why it is not in `omniweave_core.limits` -- a
`MAX_*` is *"a number its own producer is built never to exceed, clampable down by a tenant"*, and
this one is neither clampable nor a ceiling.
"""


@dataclass(frozen=True, slots=True)
class StepMetrics:
    """08:200-207, field names and order verbatim, with `spend`'s default changed. D139.

    **`queued_ms` is ALWAYS separate from `ran_ms`** -- the plan writes that in capitals on the
    field itself, because a single "duration" makes an admission backlog indistinguishable from a
    slow driver, and those two numbers send an operator to opposite knobs.

    **`micros` is priced by the runner through `PriceBook`, NEVER by a driver** (INV-15).
    `DriverMetrics` has no currency field and `[cost.*]` on a card has none either: *"a contributor
    on a rented A100 cannot know your GPU-hour cost, and if they guess, every estimate in your fleet
    is wrong in a way you cannot audit"* (05:2376-2380).

    **`spend` defaults to `None` rather than to `Spend()`, and that is D139.** 08:202 prints
    `spend: "Spend" = Spend()` inside a block headed *"SYNCHRONOUS, stdlib only"*. The annotation is
    quoted, so the plan already knew the name was unhomed here; the default is not, and a default
    value is a **construction**. 08:298-320 defends `RunContext`'s `services` and `budget` fields at
    length on exactly that distinction -- *"the field is a reference: core defines the shape,
    `omniweave` constructs the value"* -- and `tools/layers.toml` turns it into a gate: core's
    complete allowed import set is `["omniweave_ports"]`, so `from omniweave.route import Spend`
    fails G4 and G1 on the line it is written. `None` is the zero vector, spelled as the absence it
    is: a `StepMetrics` that recorded no physical cost is not the same fact as one that measured
    zero of seven units, and only the runner can tell them apart.
    """

    queued_ms: int = 0
    ran_ms: int = 0
    spend: SpendVector | None = None
    micros: int = 0
    was_cache_hit: bool = False
    rows_written: int = 0
    peak_rss_bytes: int = 0


@dataclass(frozen=True, slots=True)
class StepResult:
    """What an Operator returns and `Store.complete()` takes. 08:209-231, plus one field. D138.

    **`StepResult` is strictly larger than `DriverResult`**, and 08:238-243 lists the difference as
    the things a driver may not claim: `SKIPPED_CACHED`, `SKIPPED_UNCHANGED`, `DEFERRED_BUDGET`,
    `CANCELLED`, an identity, a `cache_key`, a price, `rows_written`, a `Degradation` (INV-7). *"The
    runner constructs it; the driver contributes `outcome in {ok, ok_partial}`, `produced`,
    `partial_reason` and `DriverMetrics`."*

    **The invariant is in the constructor, not in review.** `__post_init__` is 08:222-231 verbatim.
    A `FailureClass` is required on `FAILED_TRANSIENT` as well as on `FAILED_PERMANENT`, *"because
    the retry ladder escalates **from** the class's first cooldown and a classless transient failure
    has nothing to escalate from"* -- `work.rung_for()` is that lookup and it takes the class as its
    key, so a `None` there is an `AttributeError` a thousand rows later.

    **`failure_message` extends the plan, and the extension is a column with no printed producer.
    D138.** `work.failure_message` is a real column (0004_runtime.sql:107, charter.md:4040) and
    08:113-125's own UPDATE binds `:failure_message`, but 08:209-231 gives this class no such field.
    The message lives on `Failure`, which `work.classify()` returns (08:537-539) and which the plan
    never routes back into a `StepResult`. 08:565 relies on it existing (*"the message names the
    deadline the driver was working to"*) and 08:583 on it naming *"which knob would need raising"*.
    A column the plan's own statement writes must have a channel, so the field is here, optional,
    and `None` writes NULL. `store/queue.py`'s `StepResultView` declared the same field at P2 for
    the same reason; this is where the defect is now visible rather than inferred.

    **There is no empty success** (08:245-249). Every parse and derive Port declares
    `is_valid_nonempty(ref)`, and the runner converts an `ok` result failing that predicate into
    `FAILED_PERMANENT{EMPTY_RESULT}` **before anything is cached**. That conversion is the runner's
    and not this constructor's: the predicate is the Operator's, it takes an `ArtifactRef`, and a
    value type that called it would need the driver's artefacts open.
    """

    outcome: Outcome
    unit: UnitRef
    identity: OperatorIdentity
    cache_key: str
    produced: tuple[ArtifactRef, ...] = ()
    partial_reason: str | None = None
    failure_class: FailureClass | None = None
    failure_message: str | None = None
    retry_after_ms: int | None = None
    deferred_dim: str | None = None
    degradations: tuple[Degradation, ...] = ()  # noqa: F821 -- 15-observability.md's; P7.
    metrics: StepMetrics = StepMetrics()

    def __post_init__(self) -> None:
        """08:222-231. Four outcomes require a field, and one field requires an outcome."""
        required = {
            Outcome.OK_PARTIAL: ("partial_reason",),
            Outcome.FAILED_TRANSIENT: ("retry_after_ms", "failure_class"),
            Outcome.FAILED_PERMANENT: ("failure_class",),
            Outcome.DEFERRED_BUDGET: ("deferred_dim",),
        }.get(self.outcome, ())
        for name in required:
            if getattr(self, name) is None:
                raise ValueError(f"{self.outcome} requires {name}")
        if self.retry_after_ms is not None and self.outcome is not Outcome.FAILED_TRANSIENT:
            raise ValueError("retry_after_ms is meaningful only for failed_transient")
        if len(self.cache_key) != CACHE_KEY_HEX_LEN:
            raise ValueError("cache_key is the 64-char hex output of cache_key()")


# ---------------------------------------------------------------------------------------------
# 5. `Roots` and `RunContext` -- the operator's only channel to the outside.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Roots:
    """Three directories, one of them read-only in every run. 08:257-262 verbatim.

    `source` is read-only in every run and *"the cache salt is RELATIVE to this"*, which is what
    makes a corpus relocatable without re-billing it.

    **A cache root inside `source` is a STARTUP ERROR**, and the refusal is startup step 2's rather
    than this constructor's. 02-architecture.md:720-722 puts it in config resolution -- *"an unknown
    key (naming the nearest known one), an un-canonicalisable value, or a `cache` root inside
    `source`: `ConfigError` (`OW-C-*`), **exit 1**"* -- where the operator gets a named knob and an
    exit code instead of a traceback from inside a value type. The bug behind it is recorded at
    08:290: graphify #1774 wrote its cache into the analysed tree.
    """

    source: Path
    output: Path
    cache: Path


@dataclass(frozen=True, slots=True)
class RunContext:
    """The operator's only channel to the outside -- and it is **not** `DriverIO`. 08:264-283.

    *"`RunContext` is the operator's only channel to the outside -- and it is not `DriverIO`, which
    is the **driver's** only channel and carries far less"* (08:251-253). `DriverIO` has four
    fields, INV-6's audit question is literally *"count `DriverIO`'s fields"*, and 08:2834 states
    the other half: this type is **never handed to a driver**.

    **A frozen value object, which is why core may define it** (08:300-317). No loop, no store
    handle, no `async def`. See this module's docstring for the three-point argument the plan makes
    normative, and `AdmissionView` for the one field whose real type carries `asyncio`.

    **Five digests, and 08:2834 says six. D140.** The printed block carries `config_digest`,
    `semantic_digest`, `policy_digest`, `pricebook_digest` and `catalog_digest`; the glossary row
    describing this same type says *"identity, **six** digests"*; and the `run` table
    (0004_runtime.sql:246-248) carries `config_digest`, `semantic_digest`, `policy_digest`,
    `pricebook_digest` and `lock_digest`. The union is six and each site holds five of them, and the
    two fives differ in *which* one. The consequence is one-directional and worth naming:
    `catalog_digest` is *"FROZEN at startup step 7; a mid-run install is invisible"*, and it reaches
    no durable row, so which catalog produced a run is unanswerable the moment the process exits.
    Transcribed as printed; the sixth is not invented here.

    **`config_digest` and `semantic_digest` are not interchangeable and the comments say which is
    which.** The full effective config is the manifest's and the full-scan latch's; the narrow
    projection is the only one that enters a cache key. 08:1346 is the cost of confusing them:
    `config_digest` includes `runtime.**`, `store.**` and `observe.**`, *"so raising `max_workers`
    would re-bill the corpus (I26)"*.

    **Three bans travel with this type**, each with a recorded bug behind it (08:288-296): no
    ambient cwd (graphify #1774, #2316), no module globals in `omniweave/run/` (three projects,
    three languages, one disease), and no ambient clock -- which is why `clock` is a field and
    `omniweave_core.clock.Clock` is a Protocol.
    """

    run_id: str
    generation: int
    trigger: Literal["cli", "hook", "upstream", "watch", "mcp", "sdk"]
    roots: Roots
    config_digest: str
    semantic_digest: str
    policy_digest: str
    pricebook_digest: str
    catalog_digest: str
    limits: Limits  # noqa: F821 -- 08:275; unhomed, see the docstring table.
    admission: AdmissionView
    services: ServiceRegistryView
    budget: BudgetLedger
    cancel: CancelToken
    clock: Clock
    events: TraceSink  # noqa: F821 -- omniweave_core.events, W4.8.

    def service(self, name: str) -> ServiceHandle:
        """The handle for a **named** Service. 08:283.

        One line, and the delegation is the point: a Service is *"named and never routed"*
        (02-architecture.md:886), so there is no selection to make here and nothing for an operator
        to influence. `ServiceRegistry` performs blocking attach-or-spawn behind this call
        (08:1013-1048) -- attach if a healthy server reports the same model id, else lazy spawn,
        under a scoped lock with a 120 s wait -- and none of that is async, which is the second of
        the three reasons this type may live in core.
        """
        return self.services.get(name)


# ---------------------------------------------------------------------------------------------
# 6. `CancelToken`, the last type in this module, and the four things it must distinguish.
# ---------------------------------------------------------------------------------------------


class CancelReason(StrEnum):
    """Four things stop work in this design and they are not interchangeable. 08:332-336.

    08:321-329 states the requirement before the enum: *"they differ in the `run.status` they leave,
    in the process exit code, and in whether a `run` row exists at all -- so a token that carries
    only a boolean forces every one of those four answers to be reconstructed at the top of the
    shutdown path, where the information is gone. The token carries the cause."*

    | reason | `run.status` on exit | process exit |
    |---|---|---|
    | `interrupt` | `interrupted` | `130` -- the shell's `128 + signal`, not an omniweave code |
    | `deadline` | -- (no `run` row) | -- |
    | `shed` | `partial` | `0` -- a partial run is a result, not an error |
    | `client` | -- | -- |

    All four commit their claimed rows as `Outcome.CANCELLED` through the **one** commit predicate;
    08 section 1.2 owns that transition and the table above does not restate it.

    **(a) Supersession is not a `CancelReason`, and must never become one.** `Outcome.CANCELLED` has
    two producers -- this token and a superseded `claimed_gen` -- and 08 section 8.1 exists to keep
    them apart. *"A worker whose parent was SIGKILLed has no token to consult; its late `RESULT`
    updates zero rows and is recorded as `work.cancel{work_id, generation}`. Adding a `SUPERSEDED`
    member would reintroduce the conflation the whole section is built to prevent, and would imply
    the doomed worker could be told."*

    **(b) The reason does not cross S4.** The `CANCEL` frame is `{invoke_id, generation}` and gains
    no field; `DriverIO.cancelled()` and `ServiceHandle.cancelled()` stay `-> bool`. *"A driver that
    could see `deadline` rather than `interrupt` would eventually branch on it, and 'finish this
    one, it is only a deadline' is exactly the decision a driver may not make."* The projection is
    lossy in one direction only.
    """

    INTERRUPT = "interrupt"
    """SIGINT. The FIRST one; the second exits without waiting (08 section 8.1)."""
    DEADLINE = "deadline"
    """This token's own deadline elapsed. REQUEST scope only -- see `CancelToken.__init__`."""
    SHED = "shed"
    """The Supervisor withdrew the run: `stall_detector`'s verdict (08 section 2.5)."""
    CLIENT = "client"
    """MCP `notifications/cancelled`, or an SDK caller closing the call."""


@dataclass(frozen=True, slots=True)
class Cancellation:
    """The latched cause: frozen, because it is a value and the TOKEN is the latch. 08:338-345.

    `at_mono_ns` is `ctx.clock.monotonic_ns()` and **never a wall clock**: *"`[runtime]
    shutdown_grace_ms` is measured from here (section 8.3), and a backward NTP step must not turn a
    5 s grace into an hour or a no-op"*.

    `detail` is *"for the operator and the manifest. NEVER parsed"* -- 08 section 1.6 tier 3 is the
    rule it is an instance of, and `work.MESSAGE_PATTERNS` shipping empty is the same rule enforced
    one module over.
    """

    reason: CancelReason
    at_mono_ns: int
    detail: str = ""


class CancelToken:
    """ONE per cancellation scope, checked at every loop top. 08:347-360.

    *"It PROPAGATES intent; `claimed_gen` is the separate mechanism that makes a late result safe
    (section 8.1). Not a frozen dataclass: a one-way latch is the one runtime object that is
    honestly mutable, and it is monotone -- `cancelled()` never returns False after returning True,
    and `cause()` never changes once set, which is what makes it safe to share across the loop, the
    worker threads and the handler."*

    **`_latch` is a list and not an attribute, and that is a concurrency decision.** 08:358 calls it
    *"a one-slot append-only log; `list.append` needs no lock, so the SIGINT handler cannot deadlock
    against a worker"*. `cancel()` appends unconditionally and then asks whether its own object came
    first, so two threads racing produce one winner with no compare-and-swap and no lock; `cause()`
    reads `_latch[0]`, so **first cause wins**. A run that is interrupted and then passes a deadline
    still reports `interrupt`, *"and the manifest names what the operator did rather than what
    happened next"*.

    **(d) `cancelled()` reads two words of memory and nothing else.** It is called at every loop top
    on every worker, and `[runtime] loop_lag_max_ms = 250` is sampled at 100 ms with a one-way
    `degrade()` on breach. *"A token that took a lock, read the store, or called `time.monotonic()`
    through anything but the injected `Clock` would be the cheapest available way to trip the very
    monitor that is supposed to be watching the work."* The deadline check is one integer
    comparison, skipped entirely on a run token, and the `Cancellation` is allocated once, on the
    transition.

    **(e) One token per scope, never one per work row.** At `queue_high_water = 50000` claimable
    rows a per-row token would be fifty thousand objects the Supervisor holds for the length of the
    run, against a 600 MB supervisor RSS ceiling (G22) gated on a 100k-roster run. *"Scope is the
    unit of cancellation because it is the unit somebody actually withdraws."*
    """

    __slots__ = ("_clock", "_latch", "deadline_mono_ns", "scope", "scope_id")

    def __init__(
        self,
        scope: Literal["run", "request"],
        scope_id: str,
        clock: Clock,
        deadline_mono_ns: int | None = None,
    ) -> None:
        """**(c) `deadline` is a request-scope reason**, and a run token with one is refused.

        08:390-399: *"A run token's `deadline_mono_ns` is `None`: the ingest path's three deadlines
        are section 8.2's -- `progress_ms`, `wall_ms_hard` and `deadline_ms` -- they are
        per-invocation, they are enforced by the host watchdog, and a breach is
        `FAILED_PERMANENT{TIMEOUT}` on one unit, **not** a cancelled run. Putting the invocation
        deadlines on the token would give three separate failures one indistinguishable outcome."*

        The refusal is here rather than in review because the two mistakes it prevents are silent:
        a run token carrying a deadline cancels the whole run when one slow unit crosses it, and the
        `work` rows it cancels are indistinguishable from a Ctrl-C.
        """
        if scope not in ("run", "request"):
            raise ValueError(f"scope is 'run' or 'request', not {scope!r}")
        if not scope_id:
            raise ValueError("a token names its scope: ctx.run_id, or the JSON-RPC request id")
        if scope == "run" and deadline_mono_ns is not None:
            raise ValueError(
                "a run token has no deadline (08:390): the ingest path's three deadlines are "
                "per-invocation and a breach is FAILED_PERMANENT{TIMEOUT} on one unit"
            )
        self.scope = scope
        self.scope_id = scope_id
        self.deadline_mono_ns = deadline_mono_ns
        self._clock = clock
        self._latch: list[Cancellation] = []

    def cancelled(self) -> bool:
        """O(1), allocation-free on the not-cancelled path. Latches `DEADLINE` on the first breach.

        The deadline is checked **here** rather than by a timer, which is what makes it free on a
        run token: `deadline_mono_ns is None` short-circuits before the clock is read at all.
        """
        if self._latch:
            return True
        deadline = self.deadline_mono_ns
        if deadline is not None and self._clock.monotonic_ns() >= deadline:
            self.cancel(CancelReason.DEADLINE)
            return True
        return False

    def cause(self) -> Cancellation | None:
        """`_latch[0]` -- FIRST cause wins. `None` until something latches."""
        return self._latch[0] if self._latch else None

    def cancel(self, reason: CancelReason, detail: str = "") -> bool:
        """True iff **this** call latched. 08:414-419 -- the return is the two-interrupt sequence.

        *"The first Ctrl-C latches and returns `True`; the second finds a latch already present,
        returns `False`, and the handler exits the process without waiting -- which is safe because
        the claimable set **is** the checkpoint (section 1.5)."*

        Append-then-check rather than check-then-append: the check-then-append order has a window in
        which two threads both see an empty latch and both believe they won, and a SIGINT handler
        that believed it was the second Ctrl-C would exit a process that had not yet latched.
        """
        latched = Cancellation(reason=reason, at_mono_ns=self._clock.monotonic_ns(), detail=detail)
        self._latch.append(latched)
        return self._latch[0] is latched

    def remaining_ms(self) -> int | None:
        """`None` iff `deadline_mono_ns` is `None`. Never negative.

        08:399: *"`remaining_ms()` is what `ServiceHandle.post()` takes the `min(remaining,
        request_timeout_s)` of"*, so a negative value would become a negative socket timeout at the
        one call site the plan names. Floor division on nanoseconds, so the answer is never rounded
        **up** into a deadline that has already passed.
        """
        deadline = self.deadline_mono_ns
        if deadline is None:
            return None
        return max(0, (deadline - self._clock.monotonic_ns()) // 1_000_000)


# ---------------------------------------------------------------------------------------------
# 7. `run_id` -- minted, not counted. 08:285-287.
# ---------------------------------------------------------------------------------------------

CROCKFORD32: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
"""Crockford's base32 alphabet: no `I`, `L`, `O` or `U`.

`U` is excluded to avoid accidental obscenity and the other three because they are the digit
homoglyphs. A `run_id` is read aloud off a terminal and typed into `ow resume` by hand, which is the
whole reason for an alphabet that cannot produce `l` versus `1`.
"""

ULID_CHARS: Final = 26
"""A ULID is 128 bits and 26 base32 characters hold 130, so the first character is at most `7`."""

ULID_ENTROPY_BYTES: Final = 10
"""80 bits of randomness under a 48-bit millisecond timestamp. 128 bits total."""

RUN_ID_PREFIX: Final = "r_"
"""08:266 -- *"`'r_'` + a 26-char Crockford base32 ULID"*. 28 characters in total."""

_ULID_MS_BITS: Final = 48
_ULID_ENTROPY_BITS: Final = ULID_ENTROPY_BYTES * 8
_MAX_ULID_MS: Final = (1 << _ULID_MS_BITS) - 1


def ulid(wall_ns: int, entropy: bytes) -> str:
    """A 26-character Crockford base32 ULID: 48 bits of milliseconds, then 80 bits of randomness.

    Both inputs are arguments and neither is read here, which is the same discipline `Clock` exists
    for: the timestamp comes from an injected clock and the entropy from the caller, so a test can
    produce a fixed id and a property test can produce ten thousand ordered ones.
    """
    if wall_ns < 0:
        raise ValueError("wall_ns is nanoseconds since the epoch and is never negative")
    if len(entropy) != ULID_ENTROPY_BYTES:
        raise ValueError(f"a ULID takes exactly {ULID_ENTROPY_BYTES} bytes of entropy")
    milliseconds = wall_ns // 1_000_000
    if milliseconds > _MAX_ULID_MS:
        raise ValueError("48 bits of milliseconds runs out in the year 10889")
    value = (milliseconds << _ULID_ENTROPY_BITS) | int.from_bytes(entropy, "big")
    out = [""] * ULID_CHARS
    for position in range(ULID_CHARS - 1, -1, -1):
        out[position] = CROCKFORD32[value & 0x1F]
        value >>= 5
    return "".join(out)


def new_run_id(clock: Clock, entropy: bytes) -> str:
    """08:285-287 -- `'r_' + ulid(ctx.clock.wall_ns(), os.urandom(10))`.

    *"26 Crockford base32 characters, lexicographically sortable by mint time. It is **not**
    `uuid4`, which is semgrep-banned in library code, and not a counter, because two processes mint
    run ids concurrently."*

    `entropy` is an argument rather than an `os.urandom(10)` call inside this function, for the
    reason the clock is: the plan writes the call at the *site*, `omniweave.cli` is that site
    (02-architecture.md:471 is where a `RunContext` is constructed), and a function that reached for
    its own randomness would be one more ambient source to stub. `random` is banned outright by
    `pyproject.toml` -- *"Sampling is blake2b. Determinism is a gate, not a habit."*
    """
    return RUN_ID_PREFIX + ulid(clock.wall_ns(), entropy)


# ---------------------------------------------------------------------------------------------
# 8. `Operator` -- core-internal, and nobody outside core writes one. 08:1904-1927.
# ---------------------------------------------------------------------------------------------


@runtime_checkable
class Operator(Protocol):
    """The core-internal scheduled-step contract. A `Protocol`, and `OperatorABC` is struck.

    **One generic Operator class per Port, plus the five `op.<name>` core-only steps; nobody outside
    core writes one.** 08:1896-1900 gives the reason and it is not a preference: *"an operator owns
    accounting, retry granularity, ownership-scoped replacement and transaction boundaries, and a
    third party cannot be given those without being given the store."* The extension point is the
    Driver. ADR-1 decision 7 strikes the spelling `OperatorABC` on its face -- *"a `Protocol` is not
    an abstract base class and the suffix is wrong"*.

    **The Protocol is here; the implementations are in `omniweave`** (08:1906-1915), in
    `run/operators/` one per Port and `run/ops/` for `identify` and `converge`, *"next to the
    middleware that is their only caller"*. `run()` returns a `StepResult`, which a driver may not
    construct and an Operator may, and it *"reaches the driver only through
    `omniweave/run/pipeline.py`, which is the single semgrep-enforced caller of
    `DriverHost.invoke()`; an Operator that called the host directly would bypass the cache, the
    budget and the retry semaphore in one line."*

    `CACHE_LAYER` is `None` for an operator that caches nothing, and 02-architecture.md row 18 is
    blunt about why the five layers are the whole list: *"There is no `parse` or `derive` layer: if
    it is worth keeping it is a row."*
    """

    OPERATOR: ClassVar[str]
    """`'<port>.<family>'` or `'op.<name>'`. It **is** `Producer.operator`, the ownership grain."""
    OP_VERSION: ClassVar[int]
    """`== Producer.op_version`. AN INTEGER AT EVERY SITE."""
    COST_CLASS: ClassVar[CostClass]
    """An `op.*` step declares its own: `op.cluster` is `local_compute`."""
    GRANULARITY: ClassVar[Literal["document", "part", "corpus"]]
    """What one work row covers, which is what makes a retry's blast radius declared rather than
    discovered."""
    CACHE_LAYER: ClassVar[CacheLayer | None]  # noqa: F821 -- omniweave_core.cache, W4.4.
    """08 section 2.4's table, declared once, here."""

    def plan(self, unit: UnitRef, ctx: RunContext) -> Sequence[WorkSpec]:  # noqa: F821
        """The work rows this unit becomes. 08:2842 -- `WorkSpec` has no module row yet."""
        ...

    def run(self, batch: Sequence[UnitRef], ctx: RunContext) -> Sequence[StepResult]:
        """One `StepResult` per unit in the batch. The runner prices it; the driver does not."""
        ...

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """False turns an `ok` into `FAILED_PERMANENT{EMPTY_RESULT}` **before anything is cached**.

        08:245-249: DataFlow *"writes the empty string on LLM failure and propagates it"*, and
        graphify has to *detect* structurally-empty semantic cache entries and treat them as misses
        (`graphify/cache.py:958`, miss reason 4). Declaring the predicate on the operator is what
        turns that detection into a contract.
        """
        ...
