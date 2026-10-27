# The Execution Runtime

## In one paragraph

Work is one row per `(unit_uri, unit_part, operator, op_version)` in a `work` table that is
simultaneously the queue, the checkpoint and the freshness source; there is no checkpoint file, no
counter row and no scheduling barrier. One `asyncio` Supervisor in the `omniweave` distribution
claims batches by `dispatch_key`, admits them against four semaphore families plus a durable
reservation ledger, dispatches them to `subproc` DriverHost workers, and commits each unit's derived
rows, work transition, `dep` rows, reservation and spend row in one transaction. Five
content-addressed cache layers live under one `cache_index`, keyed by a three-group canonical-JSON
digest whose composition is a specification in §4.2 and not a suggestion. Incremental correctness
rests on the `dep` reverse index and the `anchor_delta`, not on the cache key; incremental *speed*
rests on a batch cache-check that returns cached results plus the outstanding work list in one call.
Cancellation propagates as a signal and is made safe by a monotonic integer compared inside the
committing `UPDATE`, so a superseded result writes nothing. The distributed seam is the four-method
`Store` protocol and nothing else.

## What this document owns, and what it defers

| Subject | Owner |
|---|---|
| the `unit` roster state machine, connectors, the change-detection ladder, `[ingest]` | [05-ingest-and-routing.md](05-ingest-and-routing.md) §1 |
| `evaluate()`, `Rung`, `Lane`, `Evidence`, the policy grammar, `PriceBook`, per-dimension budget *values*, `on_exhausted` | [05-ingest-and-routing.md](05-ingest-and-routing.md) §4-§6 |
| store pragmas, the WAL valve, snapshot isolation, `connect_readonly`, `page_render`'s DDL, store-level scale-out tiers | [07-store-and-retrieval.md](07-store-and-retrieval.md) §2, §3.11, §10, §12 |
| `DriverIO`, the `omniweave-driver/1` wire protocol, the deadline *enforcement* actions, isolation eligibility, the conformance kit | [04-driver-system.md](04-driver-system.md) §1, §6, §8 |
| Segment and pass semantics, `derive_cover`, owner-scoped replacement steps 0-7 | [06-structure-extraction.md](06-structure-extraction.md) |
| the process topology diagram, the nine startup steps, the `store.write` lock's wait budgets | [02-architecture.md](02-architecture.md) §5 |
| the event vocabulary's *contents*, sinks, sampling, OTLP export, the manifest's rendering | [15-observability.md](15-observability.md) |
| latency and throughput budgets, the Pacer, the reference-ingest projections | [12-performance.md](12-performance.md) |
| `ow bench *`, `ow test crash-matrix`, G8/G18/G19/G20/G23/G24 gate mechanics | [13-quality.md](13-quality.md) |

This document owns: the `work` row's lifecycle and its `Outcome` mapping, `StepResult`, idempotency
and resume, attempt accounting, priority, concurrency derivation and backpressure, Sequence
sessions, the model-server seam (S3), the whole cache hierarchy, the incremental-refresh loop, the
Plan document, budget *enforcement*, cancellation propagation, and the distributed seam.

## Part 1 — The work model

### 1.1 One row, five jobs

The `work` table (charter §D6; DDL not restated) carries a single row per
`(unit_uri, unit_part, operator, op_version)`, and that row is **the** unit of scheduling, claiming,
accounting, retry and failure — deliberately identical to the routing-decision grain, so `ow why`
never has to reconcile two grains. Five consumers read the same row:

| consumer | what it reads | why not a separate table |
|---|---|---|
| the scheduler | the `work_claimable` partial index | a second queue is a second source of truth about what is done — DataFlow's `cache_step_{N}.json` failure |
| resume | `status IN ('pending','failed_transient')` ∪ `claimed` with an expired lease | the claimable set **is** the checkpoint (codegraph); there is no file to corrupt |
| freshness | `EXISTS(claimable)` ⇒ stale, `EXISTS(claimed with live lease)` ⇒ refreshing | jcodemunch's `reindex_state` module-global gives a cold CLI process no view and two clients different views |
| accounting | `cost_micros`, `queued_ms`, `ran_ms`, `peak_rss_bytes` | `queued_ms` separate from `ran_ms` always: a contended lock and slow work are indistinguishable from outside |
| the shrink guard | `work_done.rows_written` as the per-unit baseline | attribution must be per-unit, or an equal-size swap is invisible |

`SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift, which is why there is
no counter table (LDR maintains one by hand and it drifts).

### 1.2 The lifecycle, the outcome mapping and attempt accounting

```
                       planner (route_decision -> work row)
                                    |
                                    v
       +------------------------> pending <-----------+---------------------+
       |                            |                 |                     |
       |                    claim (one statement,     | CANCELLED, or       | lease_reaper:
       |                     batch-coherent,          | a dead worker's     | claimed AND
       |                     RETURNING)               | uncommitted rows    | lease_expires < now
       |                            v                 |                     | AND NOT
       |                         claimed --------------+---------------------+ _is_live_holder
       |                            |
       |         +------------------+---------------------+-----------------+
       |         v                  v                     v                 v
       |    complete(ok |      complete(               complete(       complete(
       |    ok_partial |       failed_transient)       failed_          deferred_budget)
       |    skipped_*)              |                  permanent)           |
       |         v                  v                     v                 v
       |       done          failed_transient      failed_permanent     deferred
       |                            |                     |                 |
       +----------------------------+                     |                 |
         retry_after elapsed AND attempts_total < 5       |         deferred_sweeper
                                                          |         returns it to
                               clear_old_permanent(30d) --+         pending on headroom
```

`status` values are the charter's CHECK verbatim: `pending`, `claimed`, `done`, `failed_transient`,
`failed_permanent`, `deferred`. There is no `cancelled` status, which is deliberate — a cancellation
is not a state a row rests in.

**The `Outcome` → row transition, in full.** This table is the specification; a reviewer may reject
any `Store.complete()` change that alters a cell without amending it. Every transition is written by
the one commit predicate of §8.1.

| `Outcome` | `work.status` becomes | `attempts_total` | `cost_micros` | reservation | `retry_after` | claimable again |
|---|---|---|---|---|---|---|
| `ok` | `done` | kept | `+= actual` | committed at actual | NULL | no |
| `ok_partial` | `done` | kept | `+= actual` | committed at actual | NULL | no |
| `skipped_cached` | `done` | kept (inert) | unchanged — **0** | released | NULL | no |
| `skipped_unchanged` | `done` | kept (inert) | unchanged | none was taken | NULL | no |
| `failed_transient` | `failed_transient` | kept | unchanged | released | the ladder (§1.6) | yes, at `retry_after` |
| `failed_permanent` | `failed_permanent` | kept | `+= actual` | committed at actual | NULL | no, until `clear_old_permanent(30d)` |
| `deferred_budget` | `deferred` | **decremented** | unchanged | released | the sweeper's backoff | via `deferred_sweeper` |
| `cancelled` | **`pending`** | **decremented** | unchanged | released | NULL | immediately |
| `held` | **`pending`**, `claimed_by` kept | **decremented** | unchanged | released | NULL | by the next run, never by its holder (D661) |
| *(superseded)* | unchanged — **zero rows updated** | — | — | released by the reaper | — | after the lease reap |

**Two of those cells are the whole reason the table exists.** The claim statement increments
`attempts_total` unconditionally, and `attempts_total < 5` is a clause in the claim predicate. So a
row deferred five times for lack of budget, or cancelled five times by Ctrl-C, would become
permanently unclaimable **without ever having been attempted** — a corpus that quietly stops
ingesting because the operator interrupted five runs. `DEFERRED_BUDGET`, `CANCELLED` and `HELD` therefore
decrement `attempts_total` in the same statement that writes the status, floored at zero:

```sql
UPDATE work SET
       status = :status,
       attempts_total = CASE WHEN :outcome IN ('deferred_budget','cancelled','held')
                             THEN MAX(0, attempts_total - 1) ELSE attempts_total END,
       attempts_today = CASE WHEN :outcome IN ('deferred_budget','cancelled','held')
                             THEN MAX(0, attempts_today - 1) ELSE attempts_today END,
       retry_after = :retry_after,
       claimed_by = CASE WHEN :outcome = 'held' THEN claimed_by END, claimed_gen = NULL, lease_expires = NULL,
       cost_micros = cost_micros + :micros,
       queued_ms = :queued_ms, ran_ms = :ran_ms,
       peak_rss_bytes = MAX(peak_rss_bytes, :peak_rss_bytes),
       failure_class = :failure_class, failure_message = :failure_message
 WHERE id = :id AND claimed_gen = :gen AND status = 'claimed';
```

`skipped_cached` and `skipped_unchanged` keep the attempt: the row is `done` and the counter inert.
The lease reaper decrements like `CANCELLED` — a power cut is not an attempt. `HELD` keeps `claimed_by` so the claim's `claimed_by IS NOT :worker` skips the holder.

**`deferred` is not claimable, and that is a fact about the claim SQL, not a policy.** The charter's
claim predicate is `status IN ('pending','failed_transient')`. `deferred` is absent from it, so
"the work row stays claimable" ([05-ingest-and-routing.md](05-ingest-and-routing.md) §6.4) is true
of the *work*, not of the row's status, and the mechanism that makes it true is named:

```python
# omniweave/run/supervisor.py — an ordinary TaskGroup task
async def deferred_sweeper(ctx: RunContext) -> None:
    """Return `deferred` rows to `pending` when headroom for every dimension they were denied on
       has reappeared. Edge-triggered on budget release; a 5 s backstop poll, not a mechanism."""
```

Four rules make it neither a spin nor a leak:

1. **It is edge-triggered.** Every `budget.commit` and `budget.release` that lowers
   `Σ(held) + Σ(committed)` for some `(dim, scope, scope_key)` wakes the sweeper for exactly that
   key. `[runtime] deferred_sweep_ms = 5000` is a backstop, because a `run`-scoped `wall_ms` cap
   frees nothing and still needs a terminal answer. *(Build note, D946: the backstop's sweep runs in a thread, and the ledger commits it whether or not the task awaiting it survives. Cancelled at run end, the task dropped that sweep's count, which CI saw as `swept` 14 against eight calls of 2. The sweep is now shielded, and on cancellation it is waited for and counted, as the lease reaper's was in D606.)*
2. **A row returns only when every denied dimension has headroom ≥ its estimate**, computed by the
   SQL of §7.3. Returning it on partial headroom re-runs `admit()` for a guaranteed denial.
3. **It honours [05-ingest-and-routing.md](05-ingest-and-routing.md) §6.4's sibling clause.**
   `budget.exhausted` enters Evidence only when a deferred row is re-offered with no sibling
   reservation still `held` for the same `scope_key`; otherwise the release that woke the sweeper is
   a p95 over-reservation being handed back, and treating that as exhaustion would degrade the
   second half of every document while a third of the cap was spent.
4. **Repeated deferral backs off durably.** A row that defers again gets
   `retry_after = store_now + min(60_000 × 2^(n-1), 1_800_000)`, where `n` is the in-run defer
   streak for its `scope_key`. `retry_after` on a `deferred` row gates only the sweeper, so a
   permanently-exhausted budget costs one probe per 30 minutes instead of a hot loop, and the
   row's priority drops to −100 (§1.7).

**Every terminal state has a scheduled way out.** `failed_permanent` is swept by
`clear_old_permanent(30d)`; without it, codegraph #1127 retried a deterministic failure at the
debounce cadence forever and its own note read "the auto-update guarantee is silently dead". LDR's
`clear_old_permanent_failures(days=30)` (`retry_manager.py:235`) is the shipped form: 30 days is long
enough that a permanently-broken source costs one attempt a month, short enough that a
genuinely-fixed one recovers with no operator action.

A `work_no_live_delete` trigger raises `OW-S-014` on any `DELETE` of a row in
`{pending, claimed, failed_transient}`. Rows leave the table only through compaction (§1.8) or
`ON DELETE CASCADE` from `unit`.

### 1.3 `Outcome` and `StepResult` — what the runner produces

**The block below is the sole home of `Outcome`, `StepMetrics` and `StepResult`.** The charter names
`Outcome` four times and defines it nowhere, so this is not a second home; every other document
cites this section and prints no field list of its own. `Outcome` has **nine** members (`HELD` is
D661's), and the count is load-bearing: `Store.complete(row_id, gen, result: StepResult) -> bool`
([the store](07-store-and-retrieval.md) §1.1) is typed against this block, and adding or removing a member is one edit to this enum **and**
to §1.2's transition table in the same change — that table is the specification, and a member with no row in it is a rejectable PR.

```python
# omniweave_core/operator.py — SYNCHRONOUS, stdlib only (G23: no asyncio, no selectors)

class Outcome(StrEnum):
    OK                = "ok"
    OK_PARTIAL        = "ok_partial"          # usable but incomplete; partial_reason required
    SKIPPED_CACHED    = "skipped_cached"      # a cache hit; Spend replayed, was_cache_hit=True
    SKIPPED_UNCHANGED = "skipped_unchanged"   # stat_fresh + a matching work.cache_key
    FAILED_TRANSIENT  = "failed_transient"    # retry_after_ms required
    FAILED_PERMANENT  = "failed_permanent"    # failure_class required
    DEFERRED_BUDGET   = "deferred_budget"     # deferred_dim required; NOT a failure
    CANCELLED         = "cancelled"           # a CancelToken, or a superseded generation
    HELD              = "held"                # a quarantined driver's untried unit; the next run's

@dataclass(frozen=True, slots=True)
class StepMetrics:
    queued_ms: int = 0                # ALWAYS separate from ran_ms
    ran_ms: int = 0
    spend: "Spend" = Spend()          # the seven physical units plus a provider tag
    micros: int = 0                   # priced by the runner through PriceBook. NEVER by a driver
    was_cache_hit: bool = False
    rows_written: int = 0
    peak_rss_bytes: int = 0

@dataclass(frozen=True, slots=True)
class StepResult:
    outcome: Outcome
    unit: "UnitRef"
    identity: "OperatorIdentity"      # == Producer. One type, two layers, one table
    cache_key: str                    # sha256_canonical hex, 64 chars, from the one cache_key()
    produced: tuple["ArtifactRef", ...] = ()
    partial_reason: str | None = None
    failure_class: "FailureClass | None" = None
    retry_after_ms: int | None = None
    deferred_dim: str | None = None
    degradations: tuple["Degradation", ...] = ()
    metrics: StepMetrics = StepMetrics()

    def __post_init__(self) -> None:
        required = {
            Outcome.OK_PARTIAL:       ("partial_reason",),
            Outcome.FAILED_TRANSIENT: ("retry_after_ms", "failure_class"),
            Outcome.FAILED_PERMANENT: ("failure_class",),
            Outcome.DEFERRED_BUDGET:  ("deferred_dim",),
        }.get(self.outcome, ())
        for field in required:
            if getattr(self, field) is None:
                raise ValueError(f"{self.outcome} requires {field}")
        if self.retry_after_ms is not None and self.outcome is not Outcome.FAILED_TRANSIENT:
            raise ValueError("retry_after_ms is meaningful only for failed_transient")
        if len(self.cache_key) != 64:
            raise ValueError("cache_key is the 64-char hex output of cache_key()")
```

The invariant is in the constructor, not in review. A `FailureClass` is required on
`FAILED_TRANSIENT` as well as on `FAILED_PERMANENT`, because the retry ladder escalates *from* the
class's first cooldown and a classless transient failure has nothing to escalate from.

`StepResult` is **strictly larger** than `DriverResult`, and the difference is the list of things a
driver may not claim: `SKIPPED_CACHED`, `SKIPPED_UNCHANGED`, `DEFERRED_BUDGET`, `CANCELLED`, an
identity, a `cache_key`, a price, `rows_written`, a `Degradation` (INV-7). The runner constructs it;
the driver contributes `outcome ∈ {ok, ok_partial}`, `produced`, `partial_reason` and
`DriverMetrics`.

**There is no empty success.** Every parse and derive Port declares `is_valid_nonempty(ref)`, and
the runner converts an `ok` result failing that predicate into `FAILED_PERMANENT{EMPTY_RESULT}`
**before anything is cached**. DataFlow writes the empty string on LLM failure and propagates it;
graphify has to *detect* structurally-empty semantic cache entries and treat them as misses
(`graphify/cache.py:958`, miss reason 4).

`RunContext` is the operator's only channel to the outside — and it is not `DriverIO`, which is the
*driver's* only channel and carries far less:

```python
@dataclass(frozen=True, slots=True)
class Roots:
    source: Path          # read-only in every run; the cache salt is RELATIVE to this
    output: Path
    cache: Path           # a cache root inside source is a STARTUP ERROR (startup step 2)

@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: str                       # 'r_' + a 26-char Crockford base32 ULID; see below
    generation: int                   # a monotonic INTEGER, never a clock
    trigger: Literal["cli","hook","upstream","watch","mcp","sdk"]
    roots: Roots
    config_digest: str                # the FULL effective config: manifest + full-scan latch
    semantic_digest: str              # the NARROW projection that enters cache keys
    policy_digest: str
    pricebook_digest: str
    catalog_digest: str               # FROZEN at startup step 7; a mid-run install is invisible
    limits: "Limits"
    admission: "Admission"
    services: "ServiceRegistry"
    budget: "BudgetLedger"
    cancel: "CancelToken"
    clock: "Clock"                    # INJECTED: monotonic_ns() + wall_ns(). Never ambient
    events: "TraceSink"
    def service(self, name: str) -> "ServiceHandle": ...
```

`run_id` is `'r_' + ulid(ctx.clock.wall_ns(), os.urandom(10))` — 26 Crockford base32 characters,
lexicographically sortable by mint time. It is **not** `uuid4`, which is semgrep-banned in library
code, and not a counter, because two processes mint run ids concurrently.

Three bans, each with a recorded bug behind it. **No ambient cwd**: `os.getcwd()`, `Path(".")` and
`subprocess` without `cwd=` are semgrep-banned inside `omniweave/` (graphify #1774 wrote its cache
into the analysed tree; #2316 ran `git rev-parse HEAD` without `cwd=` and stamped the *invoking*
repo's commit into the target's graph). **No module globals in `omniweave/run/`**: `ctx` is per-run
(graphify's first-caller-wins `_stat_index` globals, graphrag's `Factory.__new__` process singleton,
jcodemunch's `_repo_states` module dict — the same disease in three languages). **No ambient
clock**: `Clock` is injected, which is what makes the debounce and generation invariants testable
without an operating system.

**`RunContext` is defined in `omniweave_core/operator.py`, and that does not put the Supervisor in
core.** The charter's §D6 module inventory places it there beside `StepResult`, `CancelToken` and
`Roots`, while §D6's decision text says the one `asyncio` Supervisor never lives in
`omniweave-core`. Both hold as written, neither is superseded, and the reason is normative rather
than incidental — a reader who does not have it will move the type on sight:

1. **`RunContext` is a frozen value object.** No loop, no store handle, no `async def`. The
   Supervisor is `omniweave/run/supervisor.py` (§2.1), and it is not `RunContext`.
2. **`services: ServiceRegistry` is synchronous.** `ServiceRegistry.handle()` performs **blocking**
   attach-or-spawn (§3.3). The async part is the Supervisor's `service_refill` task in
   `omniweave/run/`, never the registry.
3. **`budget: BudgetLedger` is synchronous.** Headroom is computed **in SQL on a synchronous
   connection** (§7.3), never awaited and never cached in an attribute.

Neither field makes `omniweave-core` asyncio-dependent, which is why `RunContext` may be defined
there under **G23** ([repo layout](11-repo-layout.md) §6.4). The field is a *reference*: core
defines the shape, `omniweave` constructs the value. Moving the type into `omniweave/run/` would
break `Operator.run(self, batch: Sequence[UnitRef], ctx: RunContext) -> Sequence[StepResult]`
(§6.1), whose Protocol is `T-CONTRACT` in `omniweave_core/operator.py`, and would force an
out-of-tree Operator to import `omniweave` to type its own `run()` — inverting the dependency
direction the charter exists to enforce.

**`CancelToken`, the last type in `operator.py`.** `RunContext.cancel` above is a forward reference
until it is printed, and printing it requires deciding what it must distinguish first. Four things
stop work in this design and they are not interchangeable: the operator pressed Ctrl-C, a call ran
out of its own deadline, the Supervisor withdrew a run it can no longer make progress on, and an MCP
or SDK client withdrew one request. They differ in the `run.status` they leave, in the process exit
code, and in whether a `run` row exists at all — so a token that carries only a boolean forces every
one of those four answers to be reconstructed at the top of the shutdown path, where the information
is gone. The token carries the cause.

```python
# omniweave_core/operator.py, continued — SYNCHRONOUS, stdlib only (G23)

class CancelReason(StrEnum):
    INTERRUPT = "interrupt"   # SIGINT. The FIRST one; the second exits without waiting (§8.1)
    DEADLINE  = "deadline"    # this token's own deadline elapsed. REQUEST scope only — see below
    SHED      = "shed"        # the Supervisor withdrew the run: stall_detector's verdict (§2.5)
    CLIENT    = "client"      # MCP `notifications/cancelled`, or an SDK caller closing the call

@dataclass(frozen=True, slots=True)
class Cancellation:
    """The latched cause. Frozen because it is a value; the TOKEN is the latch, not this."""
    reason: CancelReason
    at_mono_ns: int           # ctx.clock.monotonic_ns(). NEVER a wall clock: [runtime]
                              #   shutdown_grace_ms is measured from here (§8.3), and a backward
                              #   NTP step must not turn a 5 s grace into an hour or a no-op
    detail: str = ""          # for the operator and the manifest. NEVER parsed — §1.6 tier 3

class CancelToken:
    """ONE per cancellation scope, checked at every loop top. It PROPAGATES intent; `claimed_gen`
    is the separate mechanism that makes a late result safe (§8.1). Not a frozen dataclass: a
    one-way latch is the one runtime object that is honestly mutable, and it is monotone —
    `cancelled()` never returns False after returning True, and `cause()` never changes once set,
    which is what makes it safe to share across the loop, the worker threads and the handler."""

    __slots__ = ("scope", "scope_id", "deadline_mono_ns", "_clock", "_latch")

    scope: Literal["run", "request"]  # 'run' on the ingest path; 'request' on the serve path
    scope_id: str                     # ctx.run_id, or the MCP/JSON-RPC request id
    deadline_mono_ns: int | None      # None on a run token. See (c)
    _clock: "Clock"
    _latch: list[Cancellation]        # a one-slot append-only log; `list.append` needs no lock,
                                      #   so the SIGINT handler cannot deadlock against a worker

    def cancelled(self) -> bool: ...  # O(1), allocation-free on the not-cancelled path. See (d)
    def cause(self) -> Cancellation | None: ...          # `_latch[0]` — FIRST cause wins
    def cancel(self, reason: CancelReason, detail: str = "") -> bool: ...   # True iff it latched
    def remaining_ms(self) -> int | None: ...            # None iff deadline_mono_ns is None
```

| reason | set by | `run.status` on exit | process exit | who reads the reason |
|---|---|---|---|---|
| `interrupt` | the loop's `SIGINT` handler, on the first Ctrl-C ([02-architecture.md](02-architecture.md) §7.7) | `interrupted` | `130`, which is the shell's `128 + signal` and not an omniweave code ([10-interfaces.md](10-interfaces.md) §6.2) | the manifest, and the second-interrupt branch |
| `deadline` | the token itself, the first time `cancelled()` observes `clock.monotonic_ns() >= deadline_mono_ns` | — (no `run` row) | — | `retrieve()`, which discards the partial ranking and rolls back the snapshot |
| `shed` | `stall_detector` (§2.5), when nothing is claimed, nothing has committed for two `stall_poll_ms` cycles and the sweeper returned nothing | `partial` | `0` — a partial run is a result, not an error | `ow queue status`'s exit breakdown, and `degradations[]` |
| `client` | the MCP `notifications/cancelled` handler ([10-interfaces.md](10-interfaces.md) §7) | — | — | nothing; the handler returns no response |

Every one of the four commits its claimed rows as `Outcome.CANCELLED` through the **one** commit
predicate — §1.2 owns that transition and this table does not restate it. What differs is only the
four columns above.

Six consequences, each with the thing that breaks if it is reversed:

**(a) Supersession is not a `CancelReason`, and must never become one.** `Outcome.CANCELLED` has two
producers — this token and a superseded `claimed_gen` — and §8.1 exists to keep them apart. A worker
whose parent was SIGKILLed has no token to consult; its late `RESULT` updates zero rows and is
recorded as `work.cancel{work_id, generation}`. Adding a `SUPERSEDED` member would reintroduce the
conflation the whole section is built to prevent, and would imply the doomed worker could be told.

**(b) The reason does not cross S4.** The `CANCEL` frame is `{invoke_id, generation}` and gains no
field ([04-driver-system.md](04-driver-system.md) §5); `DriverIO.cancelled()` and
`ServiceHandle.cancelled()` stay `-> bool`. A driver that could see `deadline` rather than
`interrupt` would eventually branch on it, and "finish this one, it is only a deadline" is exactly
the decision a driver may not make. The projection is deliberately lossy in one direction only.

**(c) `deadline` is a request-scope reason.** A run token's `deadline_mono_ns` is `None`: the ingest
path's three deadlines are §8.2's — `progress_ms`, `wall_ms_hard` and `deadline_ms` — they are
per-invocation, they are enforced by the host watchdog, and a breach is
`FAILED_PERMANENT{TIMEOUT}` on one unit, **not** a cancelled run. A request token's
`deadline_mono_ns` is the call's `deadline_ms` translated once through the injected `Clock`, and
`remaining_ms()` is what `ServiceHandle.post()` takes the `min(remaining, request_timeout_s)` of in
§8.3 step (b). Putting the invocation deadlines on the token would give three separate failures one
indistinguishable outcome.

**(d) `cancelled()` reads two words of memory and nothing else.** It is called at every loop top on
every worker, and `[runtime] loop_lag_max_ms = 250` is sampled at 100 ms with a **one-way**
`degrade()` on breach (§8.4). A token that took a lock, read the store, or called `time.monotonic()`
through anything but the injected `Clock` would be the cheapest available way to trip the very
monitor that is supposed to be watching the work. The deadline check is one integer comparison; the
`Cancellation` it latches is allocated once, on the transition.

**(e) One token per scope, never one per work row.** At `queue_high_water = 50000` claimable rows, a
per-row token would be fifty thousand objects the Supervisor holds for the length of the run,
against a **600 MB** supervisor RSS ceiling (G22, [12-performance.md](12-performance.md) §1) that is
gated on a 100k-roster run. Scope is the unit of cancellation because it is the unit somebody
actually withdraws.

**(f) `cancel()` returns whether it latched, and that return is the two-interrupt sequence.** The
first Ctrl-C latches and returns `True`; the second finds a latch already present, returns `False`,
and the handler exits the process without waiting — which is safe because the claimable set *is* the
checkpoint (§1.5). First cause wins, so a run that is interrupted and then passes a deadline still
reports `interrupt`, and the manifest names what the operator did rather than what happened next.

### 1.4 Idempotency — three mechanisms, none of them a convention

| # | Mechanism | Covers |
|---|---|---|
| 1 | `CREATE UNIQUE INDEX work_identity ON work(unit_uri, unit_part, operator, op_version)`, with `unit_part TEXT NOT NULL DEFAULT ''` | a second enqueue of the same work. `''` folds what prose calls NULL, because NULLs are **distinct** in a UNIQUE index |
| 2 | every derived table carries a UNIQUE identity index with nullable columns `IFNULL`-folded, and every insert is `INSERT OR IGNORE` | a re-run writing duplicate rows. `INSERT OR IGNORE` with no UNIQUE index to conflict on is a plain `INSERT` — codegraph #1034 shipped byte-identical duplicate rows that inflated counts and flowed into callers |
| 3 | `origin_operator` on every derived row, and every eviction statement filtered on it | a re-run deleting rows it does not own. `derive.segment` re-running cannot touch `derive.entity` rows (I4) |

Mechanism 3 is the load-bearing one for a mixed-cost pipeline. Without it a free structure
re-extraction after one keystroke silently deletes every LLM-derived row for that unit — a free
operation destroying billable output. graphrag has no analogue and pays for it: its
`_copy_previous_output` is a full physical copy of the whole index per update, so adding one
document to a 50 GB index copies 50 GB, and
`index/workflows/update_text_embeddings.py` re-embeds the entire corpus.

`ow ingest --verify-idempotence` runs the claimed set twice into a scratch generation and asserts
equal row counts per `(table, origin_operator)`; it is the CI form of I1 and I2.

### 1.5 Killed at document 63,412 of 100,000

This is the case the design is shaped around, so it is worked through completely. Take the reference
ingest (charter §D6): 70k office documents at document grain, 25k born-digital PDFs and 5k scanned
PDFs at part grain, mean 12 pages — run with `[drivers.cost] allow_classes = ["free",
"local_compute", "billed_api"]` and a hosted `derive.entity.llm` pass enabled, so all three cost
classes are in flight, which is what makes the recovery interesting. At the moment of `SIGKILL` —
say the machine loses power six hours in:

```
unit         100,000 rows.  63,411 state='settled', 1 state='running', 36,588 in
                            {discovered, acquired, identified, planned}
work         846,400 rows.  512,000 status='done'
                            4        status='claimed'   (three subproc workers + one op.identify)
                            18       status='failed_transient', retry_after in the future
                            41       status='failed_permanent'
                            2,900    status='deferred'  (derive.entity.llm, no micros headroom)
                            331,437  status='pending'   (= 846,400 minus the five rows above)
budget_reservation   6 rows state='held', one per (reservation, dim): 2 gpu_ms rows for the two
                            claimed local_compute VLM parts, and 4 rows -- micros, tokens_in,
                            tokens_out, calls -- for the one claimed billed_api part. The
                            op.identify row has a NULL decision_id and therefore CANNOT have a
                            reservation at all (§7.6). Every expires_ms == its work row's
                            lease_expires.
cache_index  ~410,000 rows across five layers; every CAS blob fsynced before its index row.
                            The basis: one `call` row per completed parse part and per completed
                            derive unit, one `render` row per escalated part, one `embed` row per
                            segment; `op.identify` and `op.converge` write none. An estimate, not
                            a measurement -- F8's benchmark reports the real ratio.
run          1 row, status='running', ended_ns NULL
```

Nothing else exists. There is no plan file, no step counter, no in-memory queue and no artefact
outside the content-addressed store. Recovery is **re-running the ordinary command** — `ow ingest` —
and it proceeds in this order:

1. **Store open.** `MIN_SQLITE = (3,42,0)` check, `busy_timeout` before `journal_mode`, heal-on-open
   for the oversized WAL a `SIGKILL` leaves (codegraph observed 25.6 GB), refuse if
   `index_state.bulk_window` is open and name `ow store repair`. Details in
   [07-store-and-retrieval.md](07-store-and-retrieval.md) §2.
2. **Abandoned-generation sweep.** Document 63,412 was a 200-page office document parsed at
   `staged_gen = doc.gen + 1`; 40 pages had committed. Readers resolve at the committed `doc.gen`,
   so those 40 pages were never visible. The sweep deletes them through `ON DELETE CASCADE` and the
   previous generation still serves every shipped `cite`. This is the whole of the torn-parse fix —
   one integer column (I21). `--allow-abandoned-gen` is the named override for an operator who wants
   to inspect them first; there is no `--force`. *(Build note, D969: the sweep was not built, and a mid-document crash then broke the document. `begin_doc` targets `head_gen + 1` again, so the re-parse collided with the abandoned pages: `UNIQUE constraint failed: page.doc_ord, page.gen, page.page`. `store.doc.sweep_abandoned` now runs per document, as `begin_doc` opens a re-parse, in its transaction: it deletes the document's `page` rows above `doc.gen` (cascading to `block`, `rel` and `anchor`, with their FTS triggers) and its `page_render`, `diag` and `segment` rows there. Per document rather than at store open, so a write that failed mid-document and is retried in the same run is swept too. It also takes a quarantined generation once that document is re-parsed, which the override path needs. `--allow-abandoned-gen` is not built: `ow doctor` D-23 reports the rows before any re-parse touches them, and that is the inspection.)*
3. **The prior run is reconciled.** The old `run` row goes to `status='interrupted'`. A new `run`
   row is written with `generation = old.generation + 1`. If `semantic_digest` differs from the
   interrupted run's, `needs_full_scan` is latched (§5.8).
4. **Lease reaping.** `lease_reaper` selects `status='claimed' AND lease_expires < now`, checks
   `_is_live_holder(claimed_by)` — `claimed_by` is `'<host>:<pid>:<process_create_time>'`, and the
   third component is what stops a recycled pid from looking alive (jcodemunch #450 observed
   two-week-old lock rows resolving to a Chrome renderer and an AMD service) — and returns all four
   rows to `pending` with `attempts_total` decremented. **A live holder past its lease gets one
   extension with a WARNING naming it, never a steal**: codegraph's `STALE_TIMEOUT_MS = 2 min`
   unlinks locks regardless of liveness, so a legitimate three-minute bulk index loses its lock
   mid-write. D719 builds the extension. On every sweep the reaper first extends this loop's own expired claims, with their held reservations, by `lease_extend_ms`, and names each in `work.lease_extend`; then it reaps. This loop is taken as the one live holder because `store.write` admits one ingest per store, and on Windows the identity's third component reads `unavailable`. `SqliteStore.extend_live_leases` is outside the frozen four-method `Store`: the reaper asks for it by name (`LeaseExtender`).
5. **Reservations released.** The six `state='held'` rows are released **in the same transaction**
   as the lease reap (I29). Headroom is computed in SQL, never cached in an attribute, so a crash
   cannot leak it.
6. **Discovery re-streams the roster.** Not a re-plan: `discoverer` walks the scope, stamps
   `last_seen_gen`, and for each unit takes the change-detection ladder
   ([05-ingest-and-routing.md](05-ingest-and-routing.md) §1.4). 63,411 units are `stat_fresh` and
   settled at a `settled_gen`, so they produce no work. Streaming at `plan_batch = 512` rows per
   transaction means the first new parse starts in under five seconds; **there is no planning
   phase.**
7. **The claim loop resumes.** `pending ∪ failed_transient` — 331,437 + 18 = **331,455 rows** — is
   exactly the unfinished work. The 41 `failed_permanent` rows are not retried. The 2,900
   `deferred` rows are picked up by `deferred_sweeper`, re-`admit()`ed, and run if headroom exists.
8. **Zero re-bills.** Every `billed_api` unit that completed has a `call`-layer `cache_index` row
   whose key does not include `driver_version`, and every one that was in flight had a `held`
   reservation, not a spend row. The manifest's `cost.would_have_been_micros_if_uncached` shows what
   the cache saved on resume.

**What is lost:** the wall-clock time of four in-flight invocations; the GPU-seconds the shared
engine had already spent on the two `local_compute` VLM parts; and whatever the hosted provider had
already computed for the one `billed_api` part — charged by the provider, not recorded by us,
because the reservation is released rather than committed. That is why the manifest's
`Σ route_spend.micros == manifest.cost.billed_micros` self-check is exact only over *committed*
attempts, and why an interrupted run records `interrupted_inflight`.

**What is not lost:** every completed unit, every cache entry, every generation of every document
that committed, the exact retry state of every failure, and every row's attempt budget.

**The same recovery, mid-run, when one worker dies.** A `subproc` worker holding a claimed Batch of
32 sends 17 `RESULT` frames and then segfaults. The host observes the exit status, so it does **not**
wait for the lease: it returns the 15 uncommitted rows to `pending` in one transaction with
`attempts_total` decremented — nothing was attempted for rows the worker never reached — retries the
batch **once at `batch = 1`** to localise the poison unit, and feeds `WORKER_DIED` to `adapt_batch`.
The 17 committed rows are untouched. Three crashes in 60 s quarantine the **driver** for the run;
[04-driver-system.md](04-driver-system.md) §6.3 owns the kill actions, and the row disposition is
this document's.

### 1.6 Failure classification and the retry ladder

`classify()` is a **pure function** in one module, table-driven, with three tiers tried in order:

```python
# omniweave_core/work.py
def classify(declared: "FailureClass | None", exc: BaseException,
             provider: str, status_code: int | None) -> "Failure": ...
```

1. **A structured `FailureClass` from the driver wins.** `DriverError` carries one
   ([04-driver-system.md](04-driver-system.md) §1), and it is believed.
2. **Otherwise `status_code`**, against a fixed table: 401/403 → `auth`; 404/410 →
   `upstream_unavailable`, permanent for this locator; 429 → `rate_limited`; 5xx →
   `upstream_unavailable`. This tier exists because an exception crossing the S4 wire from a
   third-party HTTP client routinely loses the class and keeps the code.
3. **Otherwise the message table**, and only then, with `Diag(OW-D-051, severity='warning')`
   recording the unclassified string, so the gap is closed rather than tolerated.

LDR's 120 lines of substring matching (`"requires login" in details_lower`) silently reclassifies a
permanent failure as retryable the day upstream changes its wording; codegraph's
`isWatchResourceExhaustion` is the discipline — prefer the structured code, match messages only when
there is no code. Neither parameter is decoration: `status_code` drives tier 2, and `provider`
selects the rate-limit cooldown in the table below.

| `FailureClass` | source | verdict | first cooldown | side effect |
|---|---|---|---|---|
| `encrypted`, `unsupported_format`, `corrupt_input`, `empty_result`, `auth` | driver | permanent | — | a `Diag` row, which the absence contract can join against |
| `too_large` | driver | permanent **for this operator** | — | re-queued for a part-granularity or chunked operator at the same `unit_part` |
| `driver_bug` | driver or host | permanent | — | `ow drivers explain` prints the card and the fix command |
| `needs_ocr` | driver | **not a failure** | — | it is *routing data*: the named pages escalate one Rung (anydoc's pattern of returning an error as a routing input) |
| `rate_limited` | driver or a 429 | transient | the driver's `retry_after_ms` if present, else `RATE_LIMIT_COOLDOWN_MS[provider]` | AIMD does **not** shrink the batch: this is a provider signal, not a poison unit |
| `upstream_unavailable` | driver or a 5xx | transient | 300,000 ms | — |
| `timeout` | **driver** — a socket or provider timeout it observed | transient | 1,800,000 ms | the message names the deadline the driver was working to |
| `timeout` | **host** — `progress_ms` or `wall_ms_hard` fired | **permanent** | — | `limit` names which of the two fired, per [04-driver-system.md](04-driver-system.md) §6.3. A driver that hangs on this input hangs on it again |
| `resource_limit` | driver or host | transient | 60,000 ms | `adapt_batch`: `max(1, batch // 2)`, and the call's `resource_limit` units go again at that size at once, so only a unit killed **alone** keeps the host's permanent verdict ([04-driver-system.md](04-driver-system.md) §6.3; D657); the message names **which knob** would need raising |
| `driver_crashed` | host — exit status plus the stderr ring | permanent **for this unit** | — | retry once at `batch = 1` to localise the poison unit; 3 crashes in 60 s quarantines the **driver** |
| *unclassified* | tier 3 | transient | **3,600,000 ms** | `Diag(OW-D-051)` naming the raw message. **Fail toward retryable, and report the gap** |

The two `timeout` rows are the one place two plan documents could have contradicted each other, so
the split is explicit: a *host*-detected deadline breach is `FAILED_PERMANENT{TIMEOUT}` because the
host killed a process that produced nothing, and a *driver*-reported timeout is transient because
the driver observed a remote peer being slow. One `FailureClass`, two producers, two verdicts, and
`Failure.source ∈ {driver, host}` records which.

**`RATE_LIMIT_COOLDOWN_MS` is shipped data, not a constant.** LDR keys per-domain cooldowns off the
netloc with a `default` (`failure_classifier.py:60`: arxiv.org 6 h, researchgate.net 12 h, PubMed
2 h, default 1 h) and the spread is the point — a network blip and an anti-bot challenge are both
"temporary" three orders of magnitude apart. omniweave's analogue is keyed on `Spend.provider`:

```python
RATE_LIMIT_COOLDOWN_MS: Mapping[str, int] = {"default": 3_600_000}
```

with `[providers.<tag>] rate_limit_cooldown_ms` as the operator override (`operational` — it changes
no output). A `Retry-After` header always overrides both.

**The escalation ladder overrides the classifier after the first attempt**, so a policy with a
generous first cooldown still converges. LDR's `compute_retry_cooldown` verbatim
(`status_tracker.py:17`): `classifier cooldown → 1 day → 30 days → 30 days → PERMANENT` at
`attempts_total >= 5`, which is the `attempts_total < 5` clause in the claim predicate. The
classifier's cooldown governs the **first** attempt only; after that, repeated failure is itself the
evidence. Plus a per-unit daily cap of 3, enforced by `attempts_today` with `last_attempt_at` as the
period stamp beside it — a counter without its period stamp cannot answer "is this from today",
which is why the claim statement recomputes it from `date(last_attempt_at)` rather than trusting a
stored zero.

`retry_after` is a **store-clock** millisecond timestamp, never a worker's: a backward NTP step on
one worker must not make a row permanently unclaimable.

**Every refusal carries a reason and an ETA, and the aggregate is an operator artefact.** LDR's
`FilterSummary` (`retry_manager.py:44`) is the shape: a per-item verdict with a reason and an
`estimated_wait`, plus counts by failure type. omniweave's form is the `blocked` block of the Plan
document (§6.3) and `ow queue status`, which prints deferrals by `dim` and failures by
`failure_class` with the next `retry_after` for each — the same table
[15-observability.md](15-observability.md) §R2 diagnoses a stalled corpus from.

### 1.7 Priority — who sets it, and to what

`work.priority` is `NOT NULL DEFAULT 0` and the claim's `ORDER BY priority DESC, id` actually reads
it, so a design that never writes it has a scheduling knob nobody turns. It is set **once, by the
planner, from the trigger and the operator**, and never edited afterwards (I22's rule that the
planner owns the derived columns).

| priority | assigned to | why |
|---|---|---|
| 300 | `op.converge`, `op.identify` | a convergence step that loses to a 300,000-row parse backlog leaves the graph incorrect for hours; `op.identify` is high for the opposite reason — it is what *creates* the part rows the queue then drains |
| 200 | any row whose run `trigger` is `hook` or `mcp` | an agent is waiting on a tool call; a background ingest is not |
| 100 | a row planned by an explicit `ow add <path>` scope | the operator named this document |
| 0 | everything else — a full `ow ingest`, a `watch` refresh, an `upstream` delta | the bulk case |
| −100 | a row re-offered by `deferred_sweeper` after its second deferral | a budget that keeps saying no should not keep going to the front of the line |

`ow add --priority <n>` clamps to `[-100, 300]`. Priority is **not** a cost input and never changes
which driver runs; it orders the claim and nothing else. Two properties follow and are tested:
priority survives batching (§2.2 property 1), and a `deferred` row's priority is preserved across
the sweep, so relative order inside a starved class is stable rather than reshuffled.

### 1.8 Compaction

Above `[runtime] work_compact_above = 5000000` rows, `done` rows move to `work_done` in one
transaction per 10,000 rows. `work_done` preserves **exactly** the two things a `done` row is read
for — resume (`unit_uri`, `unit_part`, `operator`, `op_version`, `cache_key`, `gen`) and the shrink
guard's baseline (`rows_written`, `cost_micros`) — at ~90 B/row against `work`'s ~250 B. It is
`WITHOUT ROWID` on the natural key.

Compaction resets the durable spend ledger's history, which is a **`Degradation`**, not a silent
event: `Degradation(kind="ledger_reset_by_compaction", ...)` names `work_compact_above` as the knob
that would defer it. Sweeping `done` rows entirely and making `cache_index` the durable derivation
record was considered and rejected: two sources of truth for completion is precisely DataFlow's
failure.

## Part 2 — Concurrency

### 2.1 Four places, and the derivation of every number

Parallelism lives in exactly four places — the loop (IO plus its `to_thread` executor), the store
thread (writes), the `subproc` DriverHost (all driver execution), and the model server (Coalescing).
The topology is drawn in [02-architecture.md](02-architecture.md) §5.1 and is not redrawn here.
What this document owns is **where the numbers come from**.

Every degree of parallelism is derived at preflight from the machine and clamped by config; none is
a shipped constant except the ceilings.

```python
# omniweave/run/supervisor.py

@dataclass(frozen=True, slots=True)
class HostFacts:
    """Measured ONCE at preflight and recorded in the run manifest, so a performance number is
       attributable to a machine."""
    cpus: int                              # os.process_cpu_count() -- respects cgroup + affinity
    ram_bytes: int
    free_disk_bytes: int                   # of roots.cache
    gpus: tuple[tuple[str, int], ...]      # (name, vram_bytes), device order
    is_container: bool

def derive_admission(cfg: "Config", host: HostFacts) -> "Admission":
    cpus = max(1, host.cpus)

    # -- CPU raster: olmocr pipeline.py:87, adopted verbatim ---------------------
    #    BoundedSemaphore(max(1, multiprocessing.cpu_count() - 2)), with CPU render pushed
    #    through asyncio.to_thread at :112. A CPU-render semaphore is NOT the GPU
    #    semaphore: at 10.7 MB per rendered 192-DPI page (charter §D2), one shared
    #    semaphore renders faster than it evicts.
    render = max(1, cpus - 2)

    # -- worker PROCESSES per cost class ([drivers] max_workers) ----------------
    workers = {
        CostClass.FREE:          min(cfg.drivers.max_workers[CostClass.FREE],
                                     max(1, cpus - 1)),
        CostClass.LOCAL_COMPUTE: min(cfg.drivers.max_workers[CostClass.LOCAL_COMPUTE],
                                     max(1, cpus // 2)),
        CostClass.BILLED_API:    cfg.drivers.max_workers[CostClass.BILLED_API],  # IO-bound
    }

    # -- UNITS in flight per cost class ([budget] max_inflight) -----------------
    #    These count UNITS, not processes: one worker process may hold a Batch of 256.
    inflight = dict(cfg.budget.max_inflight)
    inflight[CostClass.LOCAL_COMPUTE] = min(inflight[CostClass.LOCAL_COMPUTE], render)

    return Admission(
        class_sem   = {c: asyncio.BoundedSemaphore(inflight[c]) for c in CostClass},
        worker_sem  = {c: asyncio.BoundedSemaphore(workers[c])  for c in CostClass},
        render_sem  = asyncio.BoundedSemaphore(render),
        service_sem = {n: asyncio.BoundedSemaphore(0) for n in cfg.services},  # refilled per §3.4
        high_water  = cfg.runtime.queue_high_water,
        low_water   = cfg.runtime.queue_low_water,
    )

def ram_required(cfg, catalog, workers) -> int:
    """RAM is a REFUSAL, not a clamp. `ow doctor --runtime` prints this against host.ram_bytes and
       REFUSES above 0.8x, naming [drivers] max_workers. A silent clamp would hide the fact that
       the chosen driver roster does not fit the machine."""
    return sum(
        workers[c] * max((card.isolation.memory_mb for card in catalog.enabled_in(c)), default=0)
        for c in CostClass
    ) * 1_048_576
```

Worked on three machines, with `[drivers] max_workers` at its default
`{free = 4, local_compute = 4, billed_api = 8}`, `[budget] max_inflight` at
`{free = 32, local_compute = 4, billed_api = 2}`, and this enabled roster and its declared
`[isolation] memory_mb`:

| driver | cost class | `memory_mb` |
|---|---|---|
| `parse.pdf.pdfium` | free | 450 (the class maximum) |
| `parse.office.anydoc`, `derive.*` | free | 200-300 |
| `embed.local.bge` | local_compute | 1,800 (the class maximum) |
| `parse.page.olmocr` | local_compute | 350 — it is a **thin client of a Service**, so the engine's memory is the server process's, not the worker's |
| `derive.entity.llm` | billed_api | 260 (the class maximum) |

`ram_required = workers[free]×450 + workers[local]×1800 + workers[billed]×260`, in MB:

| machine | cpus | RAM | `render_sem` | workers free / local / billed | inflight free / local / billed | `ram_required` | `ow doctor --runtime` |
|---|---|---|---|---|---|---|---|
| 4-core laptop, 16 GB | 4 | 16 GB | 2 | 3 / 2 / 8 | 32 / 2 / 2 | 3×450 + 2×1800 + 8×260 = **7.0 GB** | ok (7.0 < 0.8 × 16 = 12.8 GB) |
| 16-core workstation, 64 GB, one RTX 4090 (24 GB) | 16 | 64 GB | 14 | 4 / 4 / 8 | 32 / 4 / 2 | 4×450 + 4×1800 + 8×260 = **11.1 GB** | ok (11.1 < 51.2 GB) |
| 8-core container, 4 GB cgroup limit | 8 | 4 GB | 6 | 4 / 4 / 8 | 32 / 4 / 2 | **11.1 GB** | **REFUSES**: 11.1 > 0.8 × 4 = 3.2 GB. Names `[drivers] max_workers` |

The container row is the point of a refusal rather than a clamp: `os.process_cpu_count()` sees eight
CPUs while the cgroup memory limit admits at most one local_compute worker, and a silent clamp would
have made an operator's `max_workers = 4` a lie recorded nowhere. The fix the message names is
`[drivers] max_workers = { free = 2, local_compute = 1, billed_api = 2 }`, which gives
2×450 + 1×1800 + 2×260 = 3.2 GB — at the limit, and the operator's own decision.

`BILLED_API` is deliberately **absent from the semaphore family that matters**: its real admission is
the durable `budget_reservation` ledger, because two scheduler processes each holding an in-memory
semaphore of 2 show the provider 4. `Σ(amount) WHERE dim='calls' AND scope='provider' AND
state='held'` **is** the cross-process in-flight count (I29). `class_sem[BILLED_API]` still exists
and still bounds this process's own concurrency; it is simply not the authority.

### 2.2 The claim, and Batch formation

The claim is one statement (charter §D6), batch-coherent by
`dispatch_key = sha256(driver_id‖config_digest‖isolation)[:16]`. Two properties are worth restating
because both were mis-designed in earlier drafts:

1. **`priority DESC` survives batching.** The `head` CTE picks the highest-priority row's
   `dispatch_key`, then the outer `UPDATE` claims up to `:batch` rows sharing it, still ordered
   `priority DESC, id`. Round-robin over drivers — the rejected alternative — discards global
   priority and spins on drained drivers.
2. **A NULL `dispatch_key` batches alone.** `op.identify`, `op.converge`, `op.lexicon`, `op.resolve`
   and `op.cluster` have no driver and therefore no dispatch key; the three routing columns are
   nullable together with CHECKs binding the pairing to the `op.` prefix (charter §5 X41). *(Build note, D917: by a user ruling of 2026-10-21, *"batches alone"* binds at the INVOKE: `dispatch.form_batches()` gives each NULL-key row its own batch, so `CLAIM_SQL` claims NULL-key rows at the asked width rather than one a statement (D191). And the claim width follows the class the last claim returned, `billed_api`'s 8 only for a run's first claim and after a mixed one (D192). G22 at 100,000 units went from 504 to 870 transitions/s, the claim from most of the drain to 4% of it; the bound is 2,000, and what is left is `Store.complete`, one transaction per unit, which :919 calls the ingest ceiling and F8's group commit is the remedy for.)*

`[runtime.claim] batch = { free = 256, local_compute = 32, billed_api = 8 }`, clamped by the card's
`isolation.batch_max_units`, then adapted:

```python
def adapt_batch(key: tuple[str, str], event: "BatchEvent", state: "AimdState") -> int:
    """AIMD per (driver_id, config_digest). Multiplicative decrease, ADDITIVE increase.
       BatchEvent is a projection of FailureClass, not a second taxonomy."""
    match event:
        case BatchEvent.RESOURCE_LIMIT | BatchEvent.WORKER_DIED:
            return max(1, state.batch // 2)
        case BatchEvent.DRIVER_CRASHED:
            return 1                                        # localise the poison unit
        case BatchEvent.CLEAN if state.clean_streak >= 20:
            return min(state.batch + 1, state.card_max)
        case _:
            return state.batch
```

Halve-and-never-recover was rejected: it lets one foreign process's memory spike permanently cap a
driver's throughput for the rest of the run.

**A Batch is invisible in all four ledgers** (I24). One `RESULT` frame per unit, one `work`
transition per unit, one spend row per unit, one `unit` span per unit; `batch_index` and `batch_size`
are **span attributes** on the `call` span. The test is explicit: a `batch = 32` run with one poison
unit asserts 32 transitions, 32 spend rows, 32 unit spans and exactly one
`FAILED_PERMANENT{DRIVER_CRASHED}`.

### 2.3 Sequence sessions — the one Batch that may not be split

A **Sequence** is a contiguous run of parts bound to *one driver session*, priced by the cost card's
`per_session` versus `per_part` split so the planner can see the amortisation before choosing; its
parts share a `sequence_id` and each still gets its own `route_decision`. The routing half is
[05-ingest-and-routing.md](05-ingest-and-routing.md)'s. The **scheduling** half is this document's,
and it is the one case where the ordinary Batch rules are not enough, because splitting a session
across two Batches pays the session cost twice and produces two sessions' worth of context for one
document.

Four rules, and each closes a specific way a session leaks money:

1. **A Sequence is claimed whole or not at all.** The claim's `:batch` parameter is not a constant:
   before issuing it, `dispatch.py` reads the head row's `sequence_id` and, when it is non-NULL,
   passes `:batch = max(cfg_batch, sequence_len)` where
   `sequence_len = SELECT count(*) FROM work WHERE sequence_id = :sid AND status IN
   ('pending','failed_transient')`. All parts of one Sequence share one driver, one config and one
   isolation, so they share a `dispatch_key` by construction and the widened claim takes them
   together. `[runtime] max_sequence_units = 64` caps it; a longer session is refused at plan time
   with `SEQUENCE_TOO_LONG` naming the knob, because an unbounded widening defeats `max_inflight`.
2. **One reservation for the session, at `scope = 'unit'`.** `admit()` reserves the *session*
   estimate once, not one reservation per part, so a session cannot be half-admitted. A denial
   defers **every** part of the Sequence with the same `deferred_dim`, and `deferred_sweeper`
   returns them together.
3. **Failure is session-wide, attribution is per-part.** A session that dies mid-run yields one
   `FailureClass` and `len(sequence)` `work` transitions carrying it — the Batch invisibility rule
   (I24) is unchanged. What *is* special is that a `REGEN` of one part cannot reuse the dead
   session: the retry re-plans as a fresh Sequence of one part, at `per_part` pricing, and the
   `Degradation(kind="budget")` message says so, because a retry silently priced at `per_session`
   is a cost surprise.
4. **Spend is apportioned by token share and the sum is checked.** One spend row per part, with
   `micros` split from the session actual in proportion to that part's `tokens_in + tokens_out`, and
   `Σ(part micros) == session micros ± 1 micro` (I30's second self-check). Integer division makes
   the ±1 real: the remainder goes to the highest-token part, deterministically, so two runs
   apportion identically.

A Sequence is therefore visible in exactly three places: `work.sequence_id`, the widened `:batch`,
and the apportionment. It adds no state machine, no table and no span level.

### 2.4 The middleware order is the artifact

`omniweave/run/pipeline.py` is the **only** caller of `DriverHost.invoke()`, semgrep-enforced. The
order is graphrag's contribution (`graphrag_llm/middleware/`) plus `with_budget`, and it is an
ordering, not a set:

```
with_events                  span open/close, W3C ids, ALWAYS ON
 |- with_request_count
    |- with_cache            <- A HIT RETURNS HERE. Zero budget, zero tokens, zero rate-limit
       |                        slots. Spend replayed from cache_index.spend_json,
       |                        was_cache_hit=True, micros RE-PRICED from the current PriceBook.
       |- with_budget        <- reserve/commit. A denial short-circuits to DEFERRED_BUDGET.
          |- with_retries    <- OUTSIDE rate limiting: a retry gets back in line.
             |                  Semaphore(1) per (unit_uri, unit_part): a REGEN rung is strictly
             |                  serial per part, so two attempts cannot double-bill one page.
             |- with_rate_limiting   no busy-wait, no time.sleep under a held lock
                |- with_metrics     <- measures the PROVIDER, not the queue
                   |- with_fault_injection    _chaos:{failure_rate, exception_type,
                      |                              latency_ms, oom_at_unit}
                      |                       SHIPPED in production builds, OFF by default
                      |- DriverHost.invoke(batch)
```

Each layer is `(fn) -> fn` and is skipped when its dependency is `None` — a plain sequence of `if`s,
no framework. Two composition properties are property-tested: a cache hit with a zero-headroom
ledger still returns `SKIPPED_CACHED` (I25), and `with_budget` inside `with_cache` plus outside
`with_retries` means no billable work happens without a reservation (I8).

**`with_cache` must be told which layer to probe, and the mapping is fixed by the operator, not by
the driver.** This is the answer to "why exactly five cache layers":

| operator | `CacheLayer` probed | what the blob is |
|---|---|---|
| `acquire.*` on a non-`fs` connector | `blob` | the fetched source bytes |
| `acquire.fs` | none | the file *is* the blob; a copy would be a second representation |
| `op.identify` | none | its answer is `unit.part_count`, a store column |
| `parse.*` | `call` | one `owdoc-fragment/1` document |
| the raster step inside a `render`-requiring decision | `render` | the page image |
| `evaluate()`'s signal computation | `signal` | the computed `route_signal` scalars for one part |
| `derive.*` | `call` | one `owgraph-items/1` document |
| `embed.*` | `embed` | the vector |
| `op.converge`, `op.lexicon`, `op.resolve`, `op.cluster` | none | corpus-granularity; their memo is the store |
| `compile.*` | none | an `artifact` row is the memo ([09-generation.md](09-generation.md)) |

An operator with no layer skips `with_cache` entirely rather than probing a layer it can never hit —
which is what makes a 100%-cache-hit `ow ingest` issue zero cache queries for `acquire.fs`.

### 2.5 Backpressure, and the stall that looks like health

Three bounded queues, three different producers, and **none of them drops work except the event
queue, which drops by design and says so**.

| queue | bound | producer | on full |
|---|---|---|---|
| the claimable set | `queue_high_water = 50000` / `queue_low_water = 25000` | `discoverer` + `expander` | `producer_should_pause(claimable)` returns True; the `enumerate` generator is simply not pulled. `plan.pause` / `plan.resume` carry `claimable` and the water mark |
| the store thread's transaction queue | 256 closures | every writer in the process | the awaiting coroutine blocks, which back-pressures the loop — that is the point |
| the `TraceSink` queue | 64k events | everything | **drop-oldest**, counted into `run.events_dropped` **and** into `degradations[]`. `emit()` must not block |

**Hysteresis, never one threshold.** A single threshold makes the producer oscillate at the boundary
and turns `plan.pause`/`plan.resume` into noise; the 2:1 gap means one pause drains 25,000 rows
before discovery resumes. A connector that buffers its whole enumeration in `__init__` defeats this
and fails the `acquire` conformance suite.

**Backpressure pauses at a safe boundary and never drops.** That is also the WAL valve's correct
terminal mode: the pause is the disk's honest catch-up cost.

**The failure mode hysteresis alone does not cover is a full claimable set with nothing admissible.**
Discovery pauses at 50,000 claimable rows; every one of them is `billed_api` against an exhausted
`run`-scoped `micros` cap, or belongs to a quarantined driver. Nothing drains, nothing fails, no
event fires, and [15-observability.md](15-observability.md) §R2 records the symptom exactly: "work
rows are `deferred`, which is an `Outcome`, not a failure — so nothing is red." A loop that spins
here for six hours is worse than one that stops, so it stops:

```python
async def stall_detector(ctx: RunContext) -> None:
    """Every [runtime] stall_poll_ms = 30000: if counts_by_status() shows claimable > 0 and
       claimed == 0 and no work.complete has committed since the previous poll, and
       deferred_sweeper returned nothing, the run ends."""
```

The run ends with `run.status = 'partial'`, a `Degradation` drawn from the **existing** closed
`kind` set — `kind="budget"` when the dominant blocker is a denial (following
[05-ingest-and-routing.md](05-ingest-and-routing.md) §6.4's precedent of reusing `budget` for a
cost-class clamp rather than inventing a member), `kind="quarantine"` when it is a quarantined
driver — and the `ow queue status` breakdown printed on the way out. **This document adds no
`Degradation.kind` member.** `ow ingest` still exits 0, because a partial run is a result and not an
error; what changes is that the operator is told, in the words of the knob that would unblock it,
instead of watching a progress bar that will never move.

Two poll cycles are required before the run ends, and `claimed == 0` is part of the predicate, so a
single slow 200-page document cannot trip it. A drain that is not a stall -- nothing pending, transient, claimed or deferred, and a caller that enqueues nothing beside the loop -- ends on its empty claim without them (D676).

### 2.6 What is deliberately not parallel

| thing | why |
|---|---|
| the commit | one writer per store, one thread per connection, one transaction per unit (INV-17). `subproc` hosts parallelise the *work*; the commit is serialised by design, and it is the ingest throughput ceiling |
| a second `run()` in one process | refused with `StoreError` before the loop opens: one Supervisor per process is an assertion, not a convention ([02-architecture.md](02-architecture.md) §5.3 step 9) |
| two writers on one store | the cross-process `store.write` scoped lock. The Supervisor takes it at `batch_wait_lock_ms = 60000`, a foreground command at `interactive_wait_ms = 2000`, and the loser gets exit 7 naming the holder — never a silent retry ([02-architecture.md](02-architecture.md) §5.4). The lock is why the durable reservation ledger, not a semaphore, is the cross-process billed bound: the writers are serialised, their *provider calls* are not |
| a `REGEN` retry for one `(unit, part)` | `Semaphore(1)` in `with_retries`. Two attempts in flight on one page can double-bill it and produce two spend rows for one decision |
| `op.cluster`, `op.resolve`, `op.lexicon` | corpus-granularity; they run once at converge, after every part-granularity row is terminal |
| driver construction | `__init__` is static config only and must load no model and open no file, so a 100%-cache-hit run constructs and loads nothing. This is what makes `--dry-run` and cost estimation possible at all; DataFlow cannot do it because `PromptedGenerator` takes an `LLMServingABC` in its constructor |

## Part 3 — Model serving (seam S3)

### 3.1 Why a Service is not a Driver

A Service is a **host-managed shared model server, named and never routed**: one per
`(name, config_digest)`, reached through `ctx.service(name)` and `DriverIO.service(name)`. It has no
unit, no cost-per-unit, no card, no capability floors and never enters `resolve()`. The engine
behind an embedder or a page VLM is a Service; the embedder or VLM **driver** is a Driver with a
card, because it has a model identity that enters index metadata, a `(dim, metric, normalization)`
contract and a licence. Ten roles including `engine` were rejected for exactly this reason.

The rationale for one shared server per model is surya's, stated in `surya/settings.py:173-178`:
"there's no benefit to more than one layout model on a host, and N in-process copies thrash the
CPU/GPU. The first client attaches to a running server or spawns one; the rest attach."

### 3.2 The types

```python
# omniweave_core/modelserver.py — stdlib only; http.client, not requests

@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str                     # '[services.<name>]'; the key ctx.service() takes
    model_id: str                 # SEMANTIC: enters the cache key. A Service's model is on NO card
    model_revision: str           # an EXACT sha. "main" is a CONFIG ERROR (the ports-level rule)
    endpoint: str                 # "" = attach-or-spawn on demand; else PINNED, never spawned
    autostart: bool               # default true
    capacity: int                 # 0 = derive (§3.4)
    batch_wait_ms: int = 5        # surya's *_SERVER_BATCH_WAIT_MS
    max_batch: int = 8            # surya's default_max_batch (batch_service/config.py:37)
    keep_alive_s: int = 300       # interactive default; see F37 and §3.8
    startup_timeout_s: int = 600  # surya SURYA_INFERENCE_STARTUP_TIMEOUT = 600.0
    request_timeout_s: int = 600  # surya SURYA_INFERENCE_TIMEOUT_SECONDS = 600.0
    vram_floor_mb: int = 0        # 0 = undeclared; see §3.5's refusal and §3.7's group accounting
    server_argv: tuple[str, ...] = ()   # `python -m <module> --host --port --checkpoint <id>`
    gpu_group: str = "default"    # §3.7: which VRAM budget this Service draws from

@dataclass(frozen=True, slots=True)
class ServiceHandle:
    """What a driver gets. It is NOT a client library: it is a base URL, a token and a
    deadline, so `omniweave-llm` needs neither torch nor an SDK (2 MB, ports-only)."""
    name: str
    base_url: str                 # http://127.0.0.1:<port> — the ONE sanctioned loopback listener
    token: str                    # 32 bytes from os.urandom, hex; from the 0600 sentinel
    model_id: str
    model_rev: str
    capacity: int
    traceparent: str              # rides as an HTTP header (I33)
    deadline_ms: int
    def post(self, path: str, body: bytes,
             *, headers: Mapping[str, str] | None = None) -> bytes: ...
    def cancelled(self) -> bool: ...

class ServiceRegistry:
    """Per-RUN, carried on RunContext. Never a module global, never a process singleton.
       attach_or_spawn is BLOCKING; the async part is the Supervisor's service_refill task."""
    def live(self) -> Iterator[ServiceSpec]: ...
    def handle(self, name: str) -> ServiceHandle: ...    # attach_or_spawn, memoised per run
    def evict(self, name: str, reason: str) -> None: ...
    def observe(self) -> Iterator[Mapping[str, Scalar]]: ...   # one service_observation row each
```

The token is `os.urandom(32).hex()`. `secrets` is semgrep-banned in library code alongside `random`
and `uuid4`, and `os.urandom` is the same CSPRNG without the banned import.

A subprocess driver's handle crosses the process boundary as fields (D712). `INVOKE` carries a
`services` list of grants, each the handle's fields plus the Service's `request_timeout_s`; it is
absent when nothing is granted. The worker's `io.service(name)` rebuilds `modelserver.Handle` from
the grant under the call's deadline and cancellation; a name not granted is `DRIVER_BUG`, naming
it. `post()`'s failure is `UPSTREAM_UNAVAILABLE`, transient, because a driver imports
`omniweave_ports` alone and cannot name core's error. A `deadline_ms` of 0 is no deadline, as
`Deadlines` reads it, so `request_timeout_s` alone bounds the request. The run's registry is built from
`[services.*]` when its `RunContext` is (D713), with `$OMNIWEAVE_HOME/services` as its sentinel
root. Derive asks it for each Service the card's `[hardware] services` names, `model:<name>` naming
`[services.<name>]`. A Service that will not attach fails that batch's rows, permanent and
`upstream_unavailable` with the attach's own fix, and the drain goes on.

A pinned local OpenAI-compatible server attaches (D717), with two changes to the probe:
- Ollama and LM Studio serve no `/health`. A 404 there, and only a 404, makes `GET /v1/models` the health check; a refused connection stays down.
- A server listing several models is verified for the configured one when it lists it, since each request names its model. A spawned engine's first id is still its only one.

The constrained decoder gets the lane's schema without `pattern` and without empty `enum`s (`omniweave_llm.prompt.decodable`). Ollama 0.20.7 crashes in `SchemaToGrammar` on any `pattern`. The full schema stays the validator's.

Measured against the live `qwen3:4b`, the attach and the decode now hold. Two runtime gaps showed:
- the driver emits no `PROGRESS` per Segment, so the 120 s `progress_ms` kills a slow model mid-batch;
- the live-holder lease extension of 08:462-470 is unbuilt, so a batch longer than `lease_ms` is reaped from under its holder and its completion superseded.

**One entry point, many heads.** This is surya's `SuryaInferenceManager`
(`surya/inference/__init__.py:86-107`): one manager per process, injected explicitly into every
predictor — `LayoutPredictor(manager)`, `RecognitionPredictor(manager)`, `TableRecPredictor(manager)`
— with a module-level `get_default_manager()` singleton that surya's own docstring says exists "only
for notebooks" and that "surya's own models.py and marker should use explicit construction".
omniweave takes the injection and **does not ship the singleton at all**: `ServiceRegistry` is on
`RunContext`, and there is no ambient accessor to forget to pass.

### 3.3 `attach_or_spawn` — the ladder

Six steps, in order, from `surya/inference/backends/spawn.py` with three additions.

```
0. PINNED ENDPOINT (spec.endpoint != "", or the OMNIWEAVE_SERVICES_<NAME>_ENDPOINT env twin)
   -> GET {endpoint}/health.  Unreachable => SERVICE_UNREACHABLE naming the key and the env var.
   -> GET {endpoint}/v1/models; REFUSE TO ATTACH if the reported model id != spec.model_id.
      A model-id mismatch is a FATAL ConfigError, never a retry: retrying attaches to the same
      wrong server. No lock is taken and NOTHING is ever spawned on this branch.
1. UNLOCKED SENTINEL FAST PATH
   -> read $OMNIWEAVE_HOME/services/<name>-<config_digest>.json  (mode 0600)
   -> probe /health; verify the model id; attach.
   -> IT MUST NOT MUTATE THE SENTINEL. surya's comment is the reason, and it is subtle:
      "when many clients cold-start at once, one holds the lock mid-spawn with its server still
       loading (so it reads unhealthy here). If an unlocked waiter deleted the sentinel on that
       'unhealthy' read, it would then acquire the lock, find no sentinel, and spawn a second
       server." Only the locked path owns sentinel deletion and replacement.
2. if not spec.autostart -> SERVICE_NOT_RUNNING naming [services.<name>] autostart.
3. TAKE THE SCOPED LOCK  scope="service.<name>", target=<config_digest>, wait 120 s
   -> re-check the sentinel INSIDE the lock (the double-check that makes step 1 safe)
4. SPAWN DETACHED
   -> pick_port(): bind ("127.0.0.1", 0), read getsockname()[1], CLOSE, and HAND THE PORT TO THE
      CHILD. This window is a real race and it is handled, not ignored: the child may fail to
      bind because a foreign process took the port in between. Three consequences, all shipped:
        (a) a bind failure in the child is retried by the parent up to 3 times with a fresh port;
        (b) the model-id verification of step 5 catches a foreign listener that DID bind;
        (c) the sentinel records the port, so a later attach probes the port we chose, not a
            port we guessed.
   -> mint a 32-byte token with os.urandom; write the sentinel {port, pid, create_time, token,
      model_id, model_rev, started_ns} at 0600 BEFORE the child is unblocked
   -> argv = spec.server_argv + ["--host","127.0.0.1","--port",port,"--checkpoint",model_id]
      -- the checkpoint is PINNED so the spawned server reports the id the client then verifies
   -> env: CUDA_VISIBLE_DEVICES from spec.gpu_group when it has the form "cuda:<n>" (§3.7)
   -> child stdout/stderr -> $OMNIWEAVE_HOME/services/<name>.log, buffering=1
   -> register the atexit reaper ONLY in the spawning process
5. VERIFY, THEN ATTACH
   -> poll /health to spec.startup_timeout_s (600); record cold_start_ms
   -> GET /v1/models and compare the reported id to spec.model_id, exactly as on the pinned branch
6. ON FAILURE: the error message CARRIES THE SERVER'S OWN LOG TAIL (last 100 lines).
   That is what makes a spawned-subprocess architecture debuggable at all, and it is what
   service_observation.log_tail stores.
```

Three additions to surya's ladder. **The 32-byte token**: `surya/settings.py:97` is
`VLLM_API_KEY = "EMPTY"`, so any local process can drive the engine; omniweave's sentinel is 0600
and the token is required on every request. **The `config_digest` in the sentinel name**: a Service
is one per `(name, config_digest)`, so changing `model_revision` attaches to a different server
rather than talking to the old model through a stale sentinel. **The port-race handling** above,
which surya leaves implicit.

Backend detection is worth taking whole (`surya/inference/__init__.py:24-59`):
`torch.cuda.is_available()` can be `False` on a good GPU box when the wheel's CUDA build is newer
than the host driver, so **trust torch when it says yes; otherwise probe `/dev/nvidia0`** — instant
and load-independent — and only then fall back to `nvidia-smi -L`, which can block for seconds on a
loaded GPU and race a timeout.

### 3.4 Capacity, and keeping the GPU fed

**Service capacity is derived at preflight, never a constant.**

```python
MAX_AUTO_PARALLEL = 96      # omniweave_core.limits. A CAP, not a default.

def service_capacity(spec: ServiceSpec, server_reported: int) -> int:
    ceiling = spec.capacity if spec.capacity > 0 else server_reported
    return max(1, min(server_reported, MAX_AUTO_PARALLEL, ceiling))
```

96 is a **cap**, not a default. `surya/inference/backends/vllm.py:89-104` reads
`MAX_AUTO_PARALLEL = 96` with `_client_parallel() = min(self._max_num_seqs, MAX_AUTO_PARALLEL)` and
`self._max_num_seqs: int = 8`. Measured on a B200: 48 to 96 is +28%, 96 to 240 is +5%, and surya's
own comment says why — "the GPU is compute-bound past ~96 concurrent, so extra requests just queue
while adding thread/connection overhead". **A flat 96 on a 24 GB consumer card is an OOM, not the
measured +28%.**

The loop keeps the engine fed with a refill task per Service:

```python
def refill_target(svc: ServiceSpec, cfg, ledger: "BudgetLedger") -> int:
    return min(service_capacity(svc, svc.reported), MAX_AUTO_PARALLEL,
               cfg.budget.max_inflight[svc.cost_class], ledger.headroom_units(svc))
```

`service_refill(svc, ctx)` tops the per-Service semaphore up to `refill_target()` on every
completion, so the number of outstanding requests tracks headroom rather than a constant. This is
where **batching across documents** happens: a `dispatch_key`-coherent Batch of 8 parts drawn from
eight *different* documents is one `INVOKE`, and the requests it issues land in the server's
coalescing window alongside requests from other worker processes.

### 3.5 GPU memory management

Two levers, and neither is a fixed number.

**Lever 1 — engine sizing from VRAM.** Adopted from `surya/inference/backends/vllm.py:25-60`, which
derives from a 24 GB baseline rather than shipping a constant:

```python
BASELINE_VRAM_GB = 24; BASELINE_MAX_BATCHED_TOKENS = 8192; BASELINE_MAX_NUM_SEQS = 32

def engine_sizing(vram_gb: int) -> tuple[int, int]:
    ratio = vram_gb / BASELINE_VRAM_GB
    max_batched_tokens = max(1024, 2 ** floor(log2(BASELINE_MAX_BATCHED_TOKENS * ratio)))
    max_num_seqs       = max(8, (int(BASELINE_MAX_NUM_SEQS * ratio) // 8) * 8)
    return max_batched_tokens, max_num_seqs
```

| card | VRAM | `max_batched_tokens` | `max_num_seqs` | a resident 7B engine | `keep_alive_s` effect |
|---|---|---|---|---|---|
| T4 | 16 GB | 4,096 | 16 | does not fit fp16 — `SERVICE_INSUFFICIENT_VRAM`, naming `vram_floor_mb` | n/a |
| RTX 4090 / A10 / L4 | 24 GB | 8,192 | 32 | 20-40 GB claimed (F37) — the whole card | blocks the next interactive command |
| L40S | 48 GB | 16,384 | 64 | ~half the card | tolerable |
| H100 | 80 GB | 32,768 | 104 | ~a third of the card | tolerable |
| B200 | 180 GB | 65,536 | 240 | small | fine, and past the measured knee anyway |

Every cell is the arithmetic above: at 80 GB, `ratio = 3.333`, `int(32 × 3.333) = 106`,
`(106 // 8) × 8 = 104`; at 16 GB, `int(32 × 0.667) = 21`, `(21 // 8) × 8 = 16`.

**omniweave does not size the engine itself** — it passes `max_batched_tokens` and `max_num_seqs` in
`server_argv` and records both in `service_observation`, because the engine is a foreign process and
guessing its internals is how a framework acquires a support burden. Nor does it ship surya's
`GPU_VRAM_GB` name table (`{b200: 180, h100: 80, "4090": 24, t4: 16, …}`, which raises `SpawnError`
on an unknown key): `HostFacts.gpus` carries `vram_bytes` measured from the device, so an unknown
card sizes correctly instead of refusing.

What omniweave owns is the **refusal**. `[services.<name>] vram_floor_mb` is the Service's declared
floor; if the largest device in its `gpu_group` reports less, `resolve()` returns a
`HARDWARE_UNSATISFIABLE` rejection for every driver that needs that Service and the plan is pruned
**with a report** in `plan/1`'s `pruned` array rather than OOMing at page 400. `vram_floor_mb = 0`
means undeclared: no refusal fires, `ow doctor --runtime` prints "undeclared" beside the Service,
and §3.7's group accounting treats the Service as filling its group.

**Lever 2 — one Service per GPU group.** `spec.gpu_group` names a VRAM budget; two Services in the
same group are never resident simultaneously unless their declared floors both fit. The eviction
rule is §3.8.

### 3.6 Two batching sites, and only two

| site | who | window | merges across | visible as |
|---|---|---|---|---|
| **Batch** | the host, `omniweave/run/dispatch.py` | none — a claim returns a `dispatch_key`-coherent set | work rows in one process | span attributes `batch_index`, `batch_size` |
| **Coalescing** | the model server | `batch_wait_ms = 5`, ceiling `max_batch = 8` | **worker processes** | `service.coalesce{name, batch, wait_ms}` |

Coalescing is surya's verified `_drain()` (`surya/common/batch_service/server.py:79-99`): block for
one job, then coalesce more arriving within the wait window up to the batch ceiling — "units from
independent client requests merge into one forward". **It happens in the server, never in
omniweave**, and it merges across worker processes, which host-side batching structurally cannot do.
A runtime-level batcher that owns units was rejected: the moment a batcher owns units it owns
accounting, retry granularity, failure isolation and the shrink guard.

The measured speedup is **not published anywhere** and every GPU-hour figure in this plan carries a
1.5x-4x band because of it (F7 closes it with `ow bench service`).

Server-side bucketing is worth copying from `surya/fast_layout/server.py`: `run_batch` buckets a
coalesced batch by any parameter the model cannot vary within one forward — surya buckets by
detection threshold — and lazily loads a secondary head only when some request in the batch asked
for it: `order = self._load_order() if any(p.get("use_order") for p in params) else None`.

### 3.7 Lazy group loading, demand-driven residency, and omniparse's bug

omniparse declares model groups by flag — `load_omnimodel(load_documents, load_media, load_web)`
loading marker's model list plus Florence-2, Whisper and a crawler
(`omniparse/__init__.py:31-64`) — and **the flags do not gate anything**: routers are registered
unconditionally at import (`server.py:33-37`) and re-registered in `main()` with
`include_in_schema=flag`, so a disabled capability is *live* and 500s on a `None` model.

The idea is right, the mechanism is not. omniweave's form:

1. **A Service is declared, never loaded, by config.** `[services.<name>]` in `omniweave.toml` makes
   a Service *nameable*. Nothing is spawned at startup. The Supervisor starts a `service_refill`
   task only for `ctx.services.live()`, and a Service becomes live on the **first**
   `ctx.service(name)` / `DriverIO.service(name)` call in the run.
2. **A capability that is not loaded is a refusal, not a `None`.** `resolve()` prunes every driver
   whose Service floor is unsatisfiable and returns a typed `Rejection`; `ow drivers explain` prints
   which `[services.*]` key or which GPU fact caused it. There is no code path in which a driver
   receives a handle to an unloaded model.
3. **A group is a VRAM budget, not a flag.** `spec.gpu_group` (default `"default"`) collects the
   Services that share a device set. A group name of the form `cuda:<n>` pins a device, and the
   Supervisor sets `CUDA_VISIBLE_DEVICES` for the spawned child from it; `"default"` means "whatever
   the engine picks", which is the single-GPU case. The group's budget is
   `max(vram_bytes over the devices it names)`, and the accounting figure for a resident Service is
   its declared `vram_floor_mb` — omniweave cannot measure a foreign process's VRAM and does not
   pretend to. A Service with `vram_floor_mb = 0` is accounted as filling the group, so an
   undeclared Service is exclusive: fail safe, not fail dense.
4. **Residency follows outstanding demand, not a plan-wide refcount.** DataFlow gets the idea right
   and the scope wrong: `llm_serving_counter[obj]` is primed at compile for **all** operators but
   decremented only inside the executed loop, so with `resume_step > 0` a serving shared between a
   skipped and an executed operator never reaches zero and is never unloaded — **resume leaks GPU
   memory** (`dataflow/pipeline/Pipeline.py`, `PipelineABC._compiled_forward`). omniweave's
   equivalent is derived from the *claimable set*, which is precisely the surviving work list:

   ```sql
   -- one query over the claimable set, which the water mark bounds at 50,000 rows
   SELECT service, count(*) FROM work
    WHERE service IS NOT NULL AND status IN ('pending','claimed','failed_transient')
    GROUP BY service;
   ```

   That is what `work.service` is for. A Service whose demand is zero is eligible for eviction the
   moment `keep_alive_s` expires; a Service with non-zero demand is never evicted for idleness. The
   resume leak cannot happen, because a skipped operator has no work row to count.
5. **INV-13 is the hard floor.** A clean born-digital page **starts no model server**. The
   `service_attaches` counter is `exact` — plus or minus one fails — precisely so a refactor cannot
   quietly warm a VLM for a corpus that never needed one.

### 3.8 Eviction and shutdown

```
keep_alive_s (default 300)      idle timer, armed only when §3.7's demand query returns 0 for this
                                Service; on expiry -> SIGTERM, poll os.kill(pid,0) 20x at 0.5 s,
                                then SIGKILL with a WARNING. Docker: `docker stop` timeout=30.
run exit                        the SPAWNING process's atexit reaper runs. A process that
                                ATTACHED never stops a server it did not start.
gpu_group pressure              LRU within the group, by last request: attach_or_spawn on a second
                                Service evicts the group's LRU resident when the declared floors do
                                not both fit, records service.evict{name, reason=
                                "gpu_group_pressure"} and
                                Degradation(kind="budget", unit_dim="vram_bytes",
                                            message=<one sentence naming the group and the knob;
                                                     REQUIRED, no default>,
                                            wanted_driver=<the evicted Service's driver>, ...),
                                and only then spawns.
3 health failures in 60 s       quarantine for the run: every affected driver's plan is pruned,
                                a Degradation(kind="quarantine", ...) is recorded, and the log tail
                                goes into service_observation.log_tail
```

**Both records name their kind, and eviction's is `budget`, not a member of its own.** VRAM is a
resource that ran out, so it is `kind="budget"` with a new `unit_dim` — the rule
[observability](15-observability.md) §6.3 states as rule 3, and the reason the closed literal
stays at twenty-seven members while a new pressurised resource costs one `unit_dim` string.
`wanted_driver` is the **evicted** Service's driver, not the spawning one: the spawn succeeded,
and the record exists to name what stopped being resident. Quarantine's record is a member,
`kind="quarantine"`, because a quarantined driver is not a bound that was reached. Both prints
elide their remaining fields with `...`, this document's convention at §1.8 and §7.4, and what
they elide includes `message` — the one field besides `kind` that carries no default, so it is
written at the construction site and never inferred from the kind.

F37's residency problem is real and its fallback is pre-committed, with a precedent: a resident 7B
engine holds 20-40 GB of VRAM **after `ow ingest` exits**, which on a 24 GB card blocks the
operator's next interactive command, and surya's own shipped default is
`SURYA_INFERENCE_KEEP_ALIVE = False`. If the measurement confirms the residency, `keep_alive_s`
drops to **0** for `trigger` in `{cli, hook}` and stays 300 for `watch` — a watcher pays a cold
start every few seconds otherwise.

### 3.9 What is recorded

Every Service writes one `service_observation` row per `(run_id, name, config_digest)` with
`lifecycle` in `{attached, spawned, failed, quarantined, evicted}`, plus `capacity`,
`peak_inflight`, `requests`, `units`, `gpu_ms`, `health_failures`, `cold_start_ms`, `queue_p50_ms`,
`queue_p95_ms` and `log_tail`. `queue_p95_ms` is the number that says whether `max_batch` and
`batch_wait_ms` are tuned, and it is the readout F7's benchmark reports.

`gpu_ms` on this row is a **per-Service rollup and not a per-unit measurement**, because Coalescing
means one forward pass serves requests from several units. The per-unit figure on a `route_spend`
row for a coalesced call is apportioned by token share — the same rule as a Sequence (§2.3) — and
the manifest labels it `apportioned`. That is honest arithmetic over an unmeasurable quantity, and
it is a written open question rather than a silent convention.

## Part 4 — The cache hierarchy

This part is a specification. A reviewer may reject a PR that adds a key input, removes one, or
reorders the canonical groups without amending §4.2's table.

### 4.1 Five layers, one index, one GC, one bill

| `CacheLayer` | contents | typical entry | `[cache.max_bytes]` | GC (`[cache] gc`) | why it exists |
|---|---|---|---|---|---|
| `blob` | acquired source bytes for a non-`fs` connector; retained `part` bytes | 40 KB - 200 MB | 100 GiB | `free_after_days = 7` | a re-fetch of an unchanged URL is a round trip already paid for |
| `call` | **a driver invocation's raw response** — `owdoc-fragment/1`, `owgraph-items/1`, a VLM's JSON | 2 KB - 4 MB | 0 = unbounded | `billed_after_days = 0` = **never** | the layer that makes a re-derivation of a corpus **within one store** cost CPU-seconds instead of a re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` lives in the store |
| `embed` | vectors for a `(model_key, text_digest)` | 1-6 KB | 0 = unbounded | never (billed) / 90 d (local) | an embedder is the second most expensive thing in the framework |
| `render` | rasterised page images | 10.7 MB per 192-DPI A4 page (charter §D2) | 20 GiB | `local_after_days = 90` | 5,000 pages is ~53.5 GB, which is why rendering follows routing |
| `signal` | computed `route_signal` values, per signal, per part | 200 B - 40 KB | 2 GiB | `local_after_days = 90` | the decision is microseconds; the 96-DPI raster it needs is not |

**There is no `parse` layer and no `derive` layer.** If it is a row in the `.owstore` it is never
also a blob in the cache (INV-1). The parse memo is
`work.status='done' AND work.cache_key == cache_key(...) AND doc(doc_key, gen) present` — three
facts already in the store. Making three of five tiers "the store" was the earlier design, and it
had a cost nobody priced: a re-derivation at a new `producer.schema_version` re-billed every VLM
page, because the only record of that response was a block row.

**The `call` layer does not survive a move to a second store.** `cache_index` is created by
`0004_runtime.sql` **inside** the `.owstore`, so a fresh store opens with an empty cache and every
`billed_api` response is billed again. What the layer does buy, all of it inside one store: a
re-parse at a new `producer.schema_version`; a `digest_recipe` bump re-derived as a re-digest pass
rather than a re-parse; an `ow index rebuild --derived`; and a re-run after a metadata-only touch
that leaves `unit.content_sha256` unchanged. On the 100k reference corpus that is 116,400 pages ×
853.4 micros ≈ **$99 not re-billed per re-derivation**. A machine-scoped cache sidecar under
`roots.cache` that would make the claim true across stores is **deferred and unfunded** — 2-3
engineer-weeks, its own GC and its own `--allow-rebill` path — and no plan document may assume it.

**The `render` layer and the `page_render` table are two indexes over one blob, and that is not an
INV-1 violation.** The bytes live exactly once, in CAS under `roots.cache`. `page_render`
([03-document-model.md](03-document-model.md) §; keyed
`(doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)`) is the *lookup* path, which is
what `Doc.page_render(page, dpi)` resolves and what carries `last_used_ns`. `cache_index` at
`layer='render'` is the *accounting and GC* path, which is what carries `spend_json`, `micros` and
the size bound — and [07-store-and-retrieval.md](07-store-and-retrieval.md) §3.11 states the
consequence directly: "CAS is swept by `[cache.max_bytes] blob` and `render`, not by the store."
INV-1 forbids a second *representation*; two indexes over one content-addressed blob are one
representation with two access paths, and a `cache_index` row whose `ref` names a CAS digest that no
`page_render` row references is exactly what mark-and-sweep collects.

Every row carries the `Spend` that produced it (`spend_json`) and its price at creation (`micros`).
A hit **replays the Spend and re-prices it from the current `PriceBook`**, which is the only way to
do cost accounting when 90% of calls are hits, and the only source of
`cost.would_have_been_micros_if_uncached`.

### 4.2 `cache_key()` — the composition, field by field

One function, in `omniweave_core.cache`, returning `sha256_canonical(...)` — a 64-char hex TEXT.
Every `cache_key` column in the framework holds its output, `derive_run.cache_key` included.

```python
def cache_key(unit: UnitRef, ident: OperatorIdentity,
              card: DriverCard, ctx: RunContext) -> str:
    free  = card.cost_model.klass is CostClass.FREE
    cheap = card.cost_model.klass is not CostClass.BILLED_API
    return sha256_canonical({
      "k": CACHE_RECIPE,
      "content":  {"digest": unit.content_sha256,
                   "salt":   unit_salt(unit, ctx.roots),
                   "part":   unit.part or ""},
      "producer": {"operator": ident.operator,
                   "schema_version": card.schema_version,
                   "code_fingerprint": ident.code_fingerprint if cheap else None,
                   "deps_digest":      deps_digest(card)   if free  else None},
      "config":   {"driver": ident.options_digest.hex(),
                   "run":    ctx.semantic_digest,
                   "digest_recipe": DIGEST_RECIPE if consumes_blocks(ident) else None},
    })
```

| input | value | why it is in the key | why the obvious alternative is wrong |
|---|---|---|---|
| `k` | `CACHE_RECIPE`, from `[cache] recipe = 1` | a bump **namespaces**; it never deletes | deleting on a recipe bump discards `billed_api` entries an operator paid for |
| `content.digest` | `unit.content_sha256` — sha256 over **normalised load-bearing** source bytes | a metadata-only touch (PDF `/ModDate`, OOXML `w:rsid*`, frontmatter, EXIF) must not re-bill a VLM pass | hashing the file re-bills on every `touch`; a normaliser that throws falls back to raw bytes, records `OW-C-041` and sets `unit.normalizer = NULL` |
| `content.salt` | `unit_salt()` — see below | two symlink aliases of the same bytes are two units; the same unit in two checkouts is **one** cache entry (graphify's `file_hash`) | an absolute path destroys portability across checkouts, which is why `roots.source` is `operational` |
| `content.part` | `unit_part`, `''` for whole-document | one page's response is not another's | omitting it is graphrag's `gen_sha512_hash` bug class, which also omits `document_id` from the chunk id so identical text in two documents collapses to one TextUnit |
| `producer.operator` | `'<port>.<family>'`, two segments | the **ownership** grain: `derive.segment` and `derive.entity` are different memos | the three-segment `driver_id` would make an impl swap invalidate a free memo it need not |
| `producer.schema_version` | the card's integer `schema_version` | **the only driver version in the key.** An output-shape or semantics change must miss | `driver_version` (semver) in the key means a bug-fix release re-bills a corpus |
| `producer.code_fingerprint` | `sha256(operator module source)[:12]`, **only when not `billed_api`** | a free or local operator's source change should invalidate its own memo | including it for `billed_api` re-bills on every refactor; excluding it for free work makes a developer editing an extractor share one namespace with every version, which is graphify's `_EXTRACTOR_VERSION = "unknown"` |
| `producer.deps_digest` | the card's `[deps] pins` digest, **only when `free`** | a pdfium or tokenizer bump changes free output with no source change | the lockfile digest would invalidate the whole free tier on every unrelated dependency bump (F26) |
| `config.driver` | `candidate.config_digest` — the driver's own effective config | `dpi = 192` and `dpi = 96` are different answers | — |
| `config.run` | **`ctx.semantic_digest`**, not `config_digest` | only keys that can change the **content** of a produced row belong here | `config_digest` includes `runtime.**`, `store.**` and `observe.**`, so raising `max_workers` would re-bill the corpus (I26) |
| `config.digest_recipe` | `DIGEST_RECIPE`, **only if the operator consumes Blocks** | a digest-definition change moves every `content_digest` a derive pass reads | including it unconditionally makes a recipe bump invalidate parse `call` entries that never saw a digest |

**`unit_salt()`, in full, because a connector without a filesystem still needs one:**

```python
def unit_salt(unit: UnitRef, roots: Roots) -> str:
    if unit.connector == "fs":
        # the WALKED path, relative to roots.source, POSIX-separated. `canonical_uri()` has
        # already applied realpath + normcase, so on Windows this is case-folded and two
        # case-different names for one file are one salt -- which is what the filesystem means.
        return PurePosixPath(relpath(unit.walked_path, roots.source)).as_posix()
    # a non-fs connector has no local path at all. The salt is the connector-scoped locator,
    # which is stable across machines by construction and never a local path.
    return f"{unit.connector}/{unit.locator}"
```

The `fs` branch uses the **walked** path and not `realpath`'s output, which is the whole point: two
symlink aliases of one file are two units with two salts and two cache entries, because a corpus
that lists a document twice under two names has two documents as far as citation is concerned.

**Deliberately absent, and each absence is load-bearing:**

- `policy_digest` and `pricebook_digest` are **decision**-key inputs, never artefact-key inputs.
  Repricing must not re-bill.
- `config_digest` (see the table). It keeps its two other jobs: the run manifest and the full-scan
  latch.
- geometry. `content_digest` excludes geometry by design, so a parse driver's bbox jitter re-bills
  nothing and cannot orphan a document.
- `drivers.enabled`. Which driver runs is *already* in the key via `producer.*`; classifying an
  allowlist as semantic would re-bill an entire corpus every time an operator enabled an unrelated
  driver — the exact failure the axis exists to prevent, pointed the other way.
- `unit.normalizer`. Its effect is already in `content.digest`, so a normaliser change invalidates
  by moving the digest rather than by a separate input. That is correct and it is **expensive**:
  see the last row of §4.8.
- the wall clock, the run id, the generation, the hostname, `PYTHONHASHSEED`.

**The canonicaliser is part of the specification.** `canonical()` is JSON with sorted keys,
`allow_nan=False`, geometry as `i32` only, and **three distinct encodings for absent / null / the
empty string** — because the difference between "this key was not in the config" and "this key was
the empty string" is a real difference. Two failure modes it closes: `"".join(values)`
concatenation, where `["a","bc"]` and `["ab","c"]` collide (graphrag's `gen_sha512_hash`), and a
`str()` fallback for an unserialisable value, which yields address-bearing reprs and therefore a
**permanent silent 100% cache miss**. An un-canonicalisable config value is a **startup error**;
there is no `str()` fallback, ever (I12).

### 4.3 The `semantic` / `operational` axis

Every config key declares its axis at its declaration site, generated into `tools/config_axes.toml`,
committed and byte-diff gated (G18). The classification rule, so a reader can check a row rather
than trust it:

> A key is `semantic` **iff** changing it can change the **content** of a produced row for a driver
> whose identity, `schema_version` and config are unchanged. Everything else is `operational`.

`semantic_digest = sha256_canonical(the semantic projection)`. An **unclassified key fails CI and is
treated at runtime as `semantic`** — fail expensive, never wrong. The failure direction is
"re-bill" (visible in `ow cost`) rather than "wrong" (not visible at all). G18 additionally asserts
that the two lists cover every key in `omniweave.toml.example` **exactly**, neither over nor under;
without that clause sixteen shipped keys matched no pattern at all. Glob arity is stated so
coverage is evaluable: `*` matches exactly one segment, `**` matches one or more, an explicit key
beats a glob, and two globs matching one key is a **G18 failure**, not a precedence puzzle.

The full lists are the charter's. The five rows most often got wrong: `services.*.model_id` and
`services.*.model_revision` are **semantic** (the model behind a Service is on no driver's card, so
it can only reach the key from there); `roots.source` is **operational** (the salt is relative to
it); `retrieval.vec.model_key` is **semantic**; `graph.passes.enable` is **operational**, being a
selector; and every key this document introduces — `[watch] *`, `[runtime] shutdown_grace_ms`,
`deferred_sweep_ms`, `stall_poll_ms`, `max_sequence_units`, `[services.*] gpu_group`, `server_argv`,
`vram_floor_mb`, `[providers.*] rate_limit_cooldown_ms` — is **operational**, which is checkable
against the rule: none of them can change the content of a produced row.

### 4.4 Namespacing — two tiers, chosen by who pays for a miss

```
FREE          op/<operator>/v<op_version>-c<code_fingerprint>/                      <- SWEPT
LOCAL_COMPUTE op/<operator>/v<op_version>-c<code_fingerprint>/cfg/<config_digest>/  <- liveness only
BILLED_API    cfg/<config_digest>/                                                  <- NEVER SWEPT
```

The asymmetry is graphify's and it is correct (`graphify/cache.py:1179`, `prune_semantic_cache`):
two hosts with different prompts sharing one output directory must not each delete the other's
entries and re-bill extraction on every alternation. A `billed_api` namespace is therefore keyed on
config alone and pruned by **liveness only**.

`ow cache stat` prints the growth bound **in these words**: `live units x configurations seen`.

I27 is structural, not a policy: `cache_ns` is a **partial index** on `cost_class='free'`, so the
automatic sweep's query cannot see a billed row. Deleting one needs `ow cache prune --allow-rebill`,
which prints the row count and the `would_have_been_micros` it is about to discard.
`--ignore-cache` is **struck**: it named the whole five-layer index, which makes it an unnamed
authorisation to re-bill — a hazard that already has its own flag.

### 4.5 The read policy — six clauses, and they are the cache's business

`CacheVerdict` is `hit | miss | miss_corrupt | miss_partial | miss_empty | miss_unit_mismatch |
hit_legacy`. "Cache hit" is a **policy**, not a lookup:

| # | condition | verdict | side effect |
|---|---|---|---|
| 1 | no entry | `miss` | — |
| 2 | the blob does not parse, or its sha256 does not match `ref` | `miss_corrupt` | counted into `manifest.cache.corrupt_entries` **and overwritten on the next success** — self-healing with no flag. graphify re-billed a corrupt entry every run until #2405 counted it |
| 3 | `partial = 1` and the caller did not pass `allow_partial` | `miss_partial` | counted |
| 4 | the decoded artefact fails the operator's `is_valid_nonempty` | `miss_empty` | counted; the entry is overwritten |
| 5 | the recorded `(unit_uri, unit_part)` differs from the one asked for | `miss_unit_mismatch` | counted, and it is a **bug report**: a key collision or a poisoned write |
| 6 | the entry is in an older namespace and legacy reads are allowed | `hit_legacy` | reported per run — "this corpus may mix extraction vintages" — with the count |

Clause 6 exists because dropping pre-fingerprinting entries would re-bill a whole corpus, and
clause 5 exists because a cache is the one place where a key collision is silent. All six are
counted, and `graph_observation` carries the five distinct miss shapes per `(run, pass, lane)` so
"is the cache working" is a query rather than a feeling. graphify reports vintage, corruption and
re-bill through `warnings.warn(RuntimeWarning)` — filterable, unstructured and invisible under JSON
logging.

### 4.6 Writes, and the poisoning allowlist

```python
def put(entries: Sequence[CacheEntry], *, allowed_units: frozenset[tuple[str, str]]) -> int: ...
```

`allowed_units` is **runner-supplied, never driver-supplied**, and it is the set of
`(unit_uri, unit_part)` pairs in the Batch just dispatched. An entry naming anything else is
rejected and recorded. This makes I13 structural rather than a review rule, and the second half of
the mechanism is that **`DriverIO` carries no cache handle at all** — a driver cannot write to the
cache even incorrectly.

The threat is concrete: an LLM enrichment pass, handed pages 12-14 of one document, must not be able
to replace the parse record of a document it was never given. graphify's `allowed_source_files`
(`graphify/cache.py:1385`) is the only cache-poisoning control in the mined collection, and its own
issue note (#1757) states the case: "semantic nodes can legitimately mention another corpus file,
but a model must not be able to replace that file's complete cache entry unless the file was part of
the current extraction batch".

Ordering: the CAS blob is written and fsynced **before** its `cache_index` row, so a crash leaves an
unreferenced blob — swept by mark-and-sweep — rather than an index row pointing at nothing. Deletion
is the mirror image and [07-store-and-retrieval.md](07-store-and-retrieval.md) §3.11 fixes it: the
file goes before the row, so a dangling row (recoverable, and a `miss_corrupt` on the next read) is
the only reachable inconsistency and never a dangling file (a leak).

### 4.7 Size bounds and GC

Three mechanisms, and the draft-obvious mistake is to ship only the first.

**(a) The write refusal.** `blobs.py` maintains a **headroom file** and refuses a write when
`free_disk_bytes(roots.cache) < [cache] min_free_bytes = 5368709120` (5 GiB), naming the knob. It is
**not** a per-unit failure: failing the *work* because the *cache* is full loses correctness for no
reason, and `RESOURCE_LIMIT` would then halve every batch (§1.6) and retry five times against a disk
that is still full. Instead the first refusal latches a run-level
`Degradation(kind="cache_disabled_no_space")` naming `cache.min_free_bytes`, `with_cache` becomes a
pass-through for the rest of the run, and every subsequent write is skipped without an event storm.
Work continues, uncached, and `ow cost` shows what that cost.

**(b) The age sweep**, at run end, one query per layer:

```sql
-- index: cache_gc(cost_class, last_hit_ns)
DELETE FROM cache_index
 WHERE cost_class = 'free'
   AND last_hit_ns < :now_ns - :free_after_days * 86400000000000
   AND cache_key NOT IN (SELECT cache_key FROM work WHERE status IN ('pending','claimed'));
```

`[cache] gc` is `{ free_after_days = 7, local_after_days = 90, billed_after_days = 0 }`, where
**0 means never**.

**(c) The size sweep, which is what actually enforces `[cache.max_bytes]`.** Age alone does not
bound anything: at 10.7 MB per rendered page, one 2,000-page ingest puts 21 GB in the `render` layer
inside its `local_after_days = 90` window and blows straight past `render = 20 GiB`. So after (b),
per layer with a non-zero bound, oldest-touched first:

```sql
-- LRU by last_hit_ns until the layer is under its bound. cost_class='billed_api' rows are
-- structurally invisible here for the same reason as in §4.4: an automatic sweep NEVER re-bills.
WITH ordered AS (
  SELECT cache_key, bytes,
         SUM(bytes) OVER (ORDER BY last_hit_ns DESC, cache_key) AS running
    FROM cache_index
   WHERE layer = :layer AND cost_class <> 'billed_api'
     AND cache_key NOT IN (SELECT cache_key FROM work WHERE status IN ('pending','claimed')))
DELETE FROM cache_index WHERE cache_key IN (SELECT cache_key FROM ordered WHERE running > :bound);
```

A layer whose bound is `0` (`call`, `embed`) is skipped entirely — unbounded is the decision, not an
oversight, because those are the two layers where a miss costs money. `[cache.max_bytes] call = 0`
therefore means the `call` layer's only bound is (a)'s disk-headroom refusal, and
`ow cache stat` prints its size beside the free-disk figure so the operator sees it coming.

Then a mark-and-sweep over CAS by refcount, which is what actually frees bytes: the `cache_index`
row is a reference, and `page_render` rows are the other. `gc.sweep{rows, bytes}` and
`cache.sweep{layer, rows, bytes}` are events.

**What happens under concurrency:** the sweep runs in the store thread inside the `store.write` lock
like every other write, and both queries exclude keys referenced by a live `work` row, so a
concurrently-claimed unit's memo is never swept out from under it. A hit on a row deleted between
probe and read is clause 2 (`miss_corrupt`) and self-heals.

### 4.8 The invalidation cascade when a driver is upgraded

Ten upgrade shapes, and they invalidate different things. This table is the answer to "will this
release re-bill my corpus", and it is the reason `schema_version` is the most expensive integer in
the framework to forget.

| what changed | key input that moves | `free` layers | `local_compute` layers | `billed_api` (`call`, `embed`) | store rows | serviced by |
|---|---|---|---|---|---|---|
| `driver_version` only (bug fix, same output shape) | **none** | hit | hit | **hit — no re-bill** | untouched | nothing runs |
| `schema_version` bump (output shape or semantics) | `producer.schema_version` | miss | miss | **miss — a re-bill, and it is intended** | replaced owner-scoped by `origin_operator` | a re-parse or re-derive of affected units *(Build note, D930: the re-parse happens on `ow add` too, over files that did not change. D679 re-enters a moved driver's settled units, but only inside a run, and `ow add` opened none when no file was queued, so a bump over unchanged files re-parsed nothing. GR8's driver-version step passed only when the step before it left a file in the racy-mtime window; sixteen runs at once failed it at least ten times. `ow add` now opens a run when a settled unit's driver key moved (`ingest.parse_keys_moved`), at ~50 ms on a no-op add.)* |
| operator module source edit | `producer.code_fingerprint` | miss | miss | hit (excluded for billed) | replaced owner-scoped | re-derive, free |
| `[deps] pins` change (a pdfium minor) | `producer.deps_digest` | miss | hit | hit | replaced owner-scoped | re-parse, free |
| a `semantic` config key | `config.run` | miss | miss | miss | replaced owner-scoped | whatever the key affects |
| `digest_recipe` bump | `config.digest_recipe` | miss for block-consuming ops | miss | miss | **not re-parsed** | a **re-digest pass**: every digest input is a stored field, so digests are recomputed from rows. Budgeted at **at most annually** |
| `cache.recipe` bump | `k` | miss (namespaced, not deleted) | miss | miss | untouched | operator-initiated and explicit |
| an `operational` config key | **none** | hit | hit | hit | untouched | nothing (I26, tested by mutating **every** operational key and asserting a byte-identical `cache_key`) |
| **a normaliser change** (a new OOXML field added to the load-bearing set) | `content.digest`, for every unit the normaliser touches | miss | miss | **miss — a full re-bill of the affected formats** | replaced owner-scoped | a re-parse of every unit of those formats |
| **a rename or a move inside the scope** | `content.salt` | miss | miss | **miss — a re-bill of that one unit** | the new `unit_uri` parses fresh; the old row goes `out_of_scope` | a re-parse of the moved unit |

The last two rows are the expensive ones and they are stated because they will surprise someone.

**A normaliser change is a corpus-wide re-bill and is therefore a release-gated act.** The
normaliser has no version input of its own — deliberately, because adding one would double-count the
same invalidation — so its effect reaches the key only by moving `content.digest`. Consequences,
pre-committed: a normaliser's load-bearing set may change only in a **major** omniweave release; the
release note must state which formats are affected; `ow doctor` after the upgrade prints
`normaliser changed for {formats}: N units will re-parse, M of them billed, ~K micros at the current
PriceBook` before anything runs; and `ow cost --by driver --since 7d` is the lagging check.

**A `git mv` re-bills that document's billed parse.** The salt is in the key because graphify's
aliasing case requires it, and the cost is one unit, not a corpus. It is real enough to measure and
narrow enough not to design around yet — see Open questions.

Three cascade rules, stated because each is a place a naive implementation breaks something:

1. **A bump namespaces; it never deletes.** The old entries remain reachable through `hit_legacy`
   until GC's liveness rule collects them. An operator who reverts a release gets their cache back.
2. **Replacement is owner-scoped.** A `schema_version` bump on `derive.segment` deletes
   `derive.segment`'s rows for the affected Segments and **nothing else** — `derive.entity`'s billed
   rows on the same Segments survive (I4). The eviction statement is filtered on `origin_operator`,
   always.
3. **The dep reverse index runs after, not instead.** Invalidating a unit's own memo does not
   invalidate the *other* units whose answers depended on it. That is §5.6's job, and a cache key
   provably cannot do it: it is a function of *this* derivation's inputs, while incremental
   correctness is a question about *others'*.

`ow cost --by driver --since 7d` is the lagging indicator for the worst case — a `schema_version`
that was **not** bumped when it should have been serves stale billed output forever with no symptom.
The defences are review, a kit check that diffs output across two tagged versions, and the fact that
a driver's spend falling to zero after a release is visible to anyone who looks.

## Part 5 — Incremental refresh

### 5.1 The loop

```
 trigger --> debounce --> filter --> scope --> cache-check --> re-parse --> re-extract
   §5.2       §5.3        §5.3      §5.4       §5.5           (L1/L2)      (L3)
                                                  |                            |
                                                  +-- cached results ----------+
                                                  +-- outstanding work list ---+
                                                                               |
                                          merge (owner-scoped) <---------------+
                                                §5.6
                                                  |
                                          op.converge: anchor_delta + dep reverse index
                                                §5.6
                                                  |
                                          bump generation (one UPDATE, inside the
                                          completing transaction) --> index_state.generation
```

Each arrow is a place a real system loses work, and each has a named mechanism below.

**Three counters are called some form of "generation" and they do three different things.** The
naming is [07-store-and-retrieval.md](07-store-and-retrieval.md) §11.2's and is not re-decided here;
what this document owes the reader is which one the runtime compares:

| counter | scope | who writes it | what the runtime does with it |
|---|---|---|---|
| `run.generation` | one run | the runner, at run start: `old.generation + 1` | it **is** `ctx.generation`, it is stamped into `work.claimed_gen` by the claim, and the commit predicate compares it. This is the cancellation and supersession counter (§8.1) |
| `index_state.generation` | the store | the generation-advance transaction | bumped as the last step of the refresh loop; retrieval's gate 3 compares it across the snapshot boundary. The runtime writes it and never reads it for scheduling |
| `doc.gen` (and `staged_gen`) | one `doc_key` | a document-granularity parse | the parse generation. `staged_gen = doc.gen + 1` is the torn-parse fix (I21) |

`unit.last_seen_gen`, `unit.settled_gen`, `cohort.built_gen`, `artifact_gen` and `card_gen` all
carry qualifying prefixes for the same reason. A bare `gen` means `doc.gen`, everywhere.

### 5.2 Three triggers, and the completeness declaration

| trigger | change set | latency | cost | covers | `run.trigger` |
|---|---|---|---|---|---|
| **agent tool-call hook** (`PostToolUse`) | exact, one unit, already coalesced | ~0 | one spawn | edits the agent makes | `hook` |
| **upstream delta** (VCS hook, connector cursor, webhook) | authoritative, complete, pre-coalesced | seconds | ~0 | pulls, checkouts, remote changes | `upstream` |
| **filesystem watcher** | lossy, needs coalescing | the debounce window | fds / inotify / CPU | everything else | `watch` |
| `ow ingest`, `ow add` | whatever the scope names | — | — | explicit | `cli` |
| `ow_add` / SDK | roster rows plus a detached child | — | — | agent-requested | `mcp`, `sdk` |

**These are complements, and the watcher is the last resort.** A `PostToolUse` hook is strictly
better than a watcher for agent edits — no inotify, no fd budget, no WSL problem, and no debounce
needed for coalescing, because the harness has already coalesced by giving one file per tool call. A
post-commit hook gets an authoritative git delta rather than inferring one from events. codegraph's
own watcher module documents why the watcher is expensive, with four issue numbers and a system-wide
crash.

**Every trigger declares whether its change set is complete.** Incomplete implies latching
`run.needs_full_scan` (§5.8). A `post-checkout` hook declares itself incomplete because a branch
switch can touch arbitrary files.

**A detached refresh child must actually start.** graphify's hooks backgrounded the rebuild with
`nohup … &`, and Git for Windows' MSYS shell ships no `nohup` (nor `setsid`), so the line died with
`nohup: command not found` and the rebuild silently never ran — `git commit` still returned 0, so
the graph just went stale with no signal (`graphify/hooks.py:258`). omniweave lets Python do the
detaching: `start_new_session=True` on POSIX, `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` on
Windows. **Not `DETACHED_PROCESS`**: on Windows 11 with Windows Terminal as the console host, a
console-less Python still gets a *visible* console allocated when its runtime touches the console
API during startup, popping an empty Terminal window over whatever the user is doing, once per
commit, for the whole rebuild (reproduced via `GetConsoleWindow()`; graphify commit `3bac3df`). And
the hook writes the child's exit status somewhere the next `ow doctor` reads it, because a
fire-and-forget refresh whose failure is invisible is a stale index with a green light.

### 5.3 The watcher: resource model, filter, debounce

```
backend:      macOS/Windows -> ONE recursive watch (O(1) descriptors)
              Linux -> one watch per non-ignored DIRECTORY (O(dirs), NEVER O(files)), capped
              -- codegraph uses the single recursive native watch on darwin because per-file fds
                 crashed machines; graphify uses PollingObserver() on darwin because "FSEvents can
                 miss rapid saves in some editors". BOTH are right for their constraints; the
                 transferable rule is that the backend is a per-platform policy decision with a
                 written reason, not one library call.
exhaustion:   EMFILE/ENFILE -> degrade() one-way latch with an actionable message
              ENOSPC        -> warn ONCE, keep running, name the sysctl and where to persist it,
                               and stop attempting further watches for the session
environment
veto:         watch_disabled_reason(root) -> str | None, ONE module, three consumers.
              Precedence: explicit off > explicit force-on > auto-detected bad environment.
              Known-bad: WSL2 /mnt/[a-z], SMB/NFS mounts, Dropbox/OneDrive/iCloud sync roots,
              FUSE cloud mounts.
event filter: compiled ONCE at start, REBUILT when its inputs change (graphify gh-928: a busy
              volume -- Time Machine, Docker/Colima VM I/O, Spotlight -- can saturate a core
              discarding events one extension at a time). Ordered by expected rejection rate:
                1 ignore rules   2 extension   3 dotfile component   4 the output root
              And DROP READ-ONLY EVENT TYPES: {"opened", "closed_no_write"}. On Linux with
              watchdog >= 2.3 inotify reports these for every open/close, including the
              watcher's OWN indexing pass reading the tree -- a self-trigger LIVELOCK that
              re-writes the pending flag forever while nothing was modified.
              omniweave hits this the moment ingestion reads files inside a watched root, so
              both defences ship: filter the event types, AND keep roots.output and roots.cache
              outside the watched set (which [roots] already requires).
resource
limits:       the watcher process runs at nice(10) with the §8.4 caps. A background refresh
              must lose to the user's editor.
```

**The debounce is adaptive, and the numbers are measured, not chosen.**

| constant | value | source |
|---|---|---|
| `QUICK_SYNC_MAX_PENDING` | 2 | codegraph `src/sync/watcher.ts:~60` |
| `QUICK_SYNC_QUIET_MS` | 300 | codegraph, same file |
| `[watch] debounce_ms` | **2000** | codegraph `options.debounceMs ?? 2000`, env-overridable via `CODEGRAPH_WATCH_DEBOUNCE_MS`, floor 100 ms |
| `SCOPED_SYNC_MAX_PENDING` | 500 | codegraph: above this a full scan-diff is simpler and comparably fast, and it self-heals anything event coalescing dropped |
| graphify's own default | **3.0 s** — `graphify/watch.py:2180`, `def watch(watch_path, debounce: float = 3.0)`, with 0.5 s polling granularity | the slower of the two; omniweave ships codegraph's 2 s, because the number is chosen against the agent's patience, not the indexer's convenience |
| `MAX_RETRY_BACKOFF_MS` | 30,000 | codegraph |
| contention streak / failure streak | 5 / 5, **separate**, each reset by one clean run | codegraph: two cadences, two budgets, one shared backoff `base * 2^(n-1)` |

```
delay = max(100, min(QUICK_SYNC_QUIET_MS, debounce_ms))   if len(pending) <= 2
        else debounce_ms
```

The timer is **re-armed on every event**, so a burst that starts as one file is re-evaluated with
the bigger pending set and extends to the full window automatically — the fast path can never
truncate a burst. One save feels instant (300 ms); a multi-file burst coalesces (2 s); a
user-lowered `debounce_ms` stays authoritative and caps the quick path. Two constants and one
comparison, and it gets both behaviours right.

**graphify's implementation is the anti-pattern to avoid, in three named ways**
(`graphify/watch.py` around line 2255): the `batch = list(changed); changed.clear()` pair drops any
event the observer thread adds between those two statements, with nothing left to re-arm —
`pending` was set `False` on the line before and `last_trigger` was stamped before the observer
touched `changed`; `_rebuild_code(watch_path)` is called **without** `changed_paths`, so every
watcher-triggered rebuild is a full-corpus AST re-extraction even though the incremental path exists
and the git hook uses it (`graphify/hooks.py:136` passes `changed_paths=changed`); and the rebuild
runs **on the debounce loop thread**, so no debounce timing happens during a rebuild and the loss
window becomes the rebuild duration. omniweave's refresh runs as an ordinary `ow ingest` in a
separate process, so the third failure is structurally impossible.

### 5.4 The pending set and the generation stamp

```python
pending: dict[UnitKey, PendingEntry]     # UnitKey = (unit_uri, unit_part)

@dataclass
class PendingEntry:
    first_seen_gen: int
    last_seen_gen: int
```

**The pending set is never cleared at flush.** Eviction happens after **success only**, and only for
entries with `last_seen_gen < run.generation`. This is the whole of I3:

> **I3.** After a successful run at generation G, the pending set contains exactly the units with
> `last_seen_gen >= G`.

The stamp is a **monotonic integer**, not a clock. codegraph's `syncStartedMs`/`lastSeenMs` pair has
the right structure and the wrong type: a backward NTP step makes a serviced entry permanently stale
or silently evicts an unserviced one. And an integer makes the eviction rule provable, which is why
the watcher's whole debounce/generation/pending logic is testable without an operating system, given
the injected `Clock` and an event-injection entry point.

Above `SCOPED_SYNC_MAX_PENDING = 500` the refresh becomes a **full reconcile** rather than a scoped
delta, because a branch checkout emits thousands of events and a full scan-diff is simpler,
comparably fast, and self-heals whatever event coalescing dropped.

**The pending set lives in the watcher process and is not durable, which is correct and bounded.**
A watcher killed with 40 pending entries loses them; what it does not lose is the *work*, because
the next `ow ingest` re-derives the same change set from `stat_fresh` and `last_seen_gen` on the
`unit` roster. The pending set is a coalescing buffer, not a queue — the queue is the `work` table —
and that is exactly why it may be in memory. A durable pending set would be a second record of
pending work that must agree with `unit`, which is the shape this design refuses everywhere else.

### 5.5 The batch cache-check — cached results **plus** the outstanding work list

The signature is the artefact. graphify's is
`check_semantic_cache(files, root, mode, prompt, prompt_file, cache_root) ->
tuple[list[dict], list[dict], list[dict], list[str]]` — "(cached_nodes, cached_edges,
cached_hyperedges, uncached_files); uncached files need Claude extraction, cached files are merged
directly" (`graphify/cache.py:1233-1244`). One call returns reusable output **and** the remaining
work. omniweave's typed form:

```python
@dataclass(frozen=True, slots=True)
class CacheProbe:
    """What ONE call over a claimed Batch returns. The caller never issues N lookups."""
    hits:        tuple["CacheHit", ...]      # decoded artefact + replayed Spend + micros re-priced
    outstanding: tuple[UnitRef, ...]         # EXACTLY what must be computed. Order preserved.
    verdicts:    Mapping[UnitKey, CacheVerdict]   # every non-hit says WHICH clause fired
    legacy:      int                         # hit_legacy count -> the mixed-vintage warning
    would_have_been_micros: int              # sum over hits, at the CURRENT PriceBook

def probe(units: Sequence[UnitRef], ident: OperatorIdentity, card: DriverCard,
          ctx: RunContext, *, layer: CacheLayer, allow_partial: bool = False) -> CacheProbe: ...
```

`layer` is not a caller's choice: `with_cache` passes the operator's layer from §2.4's table, and an
operator with no layer never calls `probe()` at all.

Three properties a naive `get(key)` loop does not have:

1. **One indexed query per Batch**, not one per unit: `WHERE cache_key IN (...)` against
   `cache_index`'s primary key. At `batch = 256` that is one statement instead of 256, and the
   `IN` list is chunked at 900 to stay under SQLite's `SQLITE_MAX_VARIABLE_NUMBER` floor.
2. **`outstanding` is what gets dispatched.** `with_cache` returns `SKIPPED_CACHED` for every hit
   *before* `with_budget` runs, so a 100%-hit Batch reserves nothing, consumes no rate-limit slot,
   and constructs no driver.
3. **Every miss carries its clause.** `verdicts` is what makes `manifest.cache.corrupt_entries`,
   `legacy_vintage_hits` and `rebilled_units` computable, and it is the difference between "the
   cache is not helping" and "the cache is corrupt".

`probe()` is distinct from a **Capability probe**, which proves a driver capability works. Same
English word, two mechanisms; `probe()` reads the cache and nothing else.

### 5.6 Merge, converge, and bump

Merging is owner-scoped replacement, and the L3 steps 0-7 are
[06-structure-extraction.md](06-structure-extraction.md)'s. This section discharges **INV-18** — an
incremental run converges to a full rebuild — by owning the two things that make the merge
**correct** rather than merely fast; both run in `op.converge`, an ordinary `op.*` work row at
`cost_class = 'free'` and priority 300, which **must ship before the watcher**, because INV-18 is
the invariant a watcher breaks silently.

**(a) The `dep` reverse index.** One query, never a sweep:

```sql
SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c
  ON c.kind = d.kind AND c.key = d.key WHERE d.digest <> c.new_digest;   -- index: dep_reverse
```

`dep` rows are populated three ways, because **observing** a driver's reads cannot be built:
`DriverIO` carries no store handle by design (INV-6), so the host cannot see what a cross-document
derivation read. There is no `DeriveIO.read_unit()`; no such type exists. So:

| path | who supplies it | when |
|---|---|---|
| runner-known inputs | the runner records what it fed the driver | always, for `unit` and `part` deps |
| a declared **Witness set** | the driver **produces** a closed artefact kind listing the foreign `(unit_uri, unit_part, token)` tuples each produced item consulted | a `derive` driver that reads across units |
| a **cohort** merkle | the runner, for corpus-granularity work that declares neither | `cohort.cohort_id = 'coh_' \|\| sha256_canonical(member merkle)[:24]`, over `(unit_uri, unit_part, content_sha256)` in sorted order; the merkle itself is `cohort.member_sha256` |

**A Witness set is a subset declaration, not a discovery.** A driver cannot name a unit it was never
given, because it has no store handle and no enumeration: the runner assembles the input set and
hands it over, and the witness set says "of the N you gave me, item X consulted these M". That is
precisely why it is cheaper than a cohort — it narrows the runner's own over-approximation from N to
M — and why it cannot be forged into naming something outside the batch: `Store.complete()` rejects
a `dep` row whose key is not in the invocation's input set, on the same rule and for the same reason
as `cache.put(allowed_units=…)` (§4.6).

A cohort dep re-derives **the whole cohort** on any member change — correct by construction and
expensive on purpose. `MAX_DEPS_PER_UNIT = 256`, enforced in `Store.complete()`, which **raises**
`OwError(OW-S-021)` rather than returning `False` — `False` means superseded and conflating the two
would turn a driver bug into a silent no-op. The runner converts the raise into
`FAILED_PERMANENT{DRIVER_BUG}` and `ow drivers explain` prints the fix: declare a cohort dep, which
is coarser, always safe, and over-invalidating deliberately. A `billed_api` corpus driver that
declares neither a witness set nor a cohort is **refused at resolve time**. The real enforcer is
**G19**, not the honour system.

**(b) The `anchor_delta`.** The per-document symmetric difference of `(name_norm, akind)` pairs
across the phase. Added names retry the unresolved set in one indexed lookup — "the corpus grew and
now this citation resolves"; removed names **unbind** every `edge` and `block_link` carrying that
`bound_by`, and **only** a row carrying `bound_by` participates, because we never delete what we
cannot restore. Skipping the equivalent pass measured **4.3% of codegraph's distinct edges wrong, in
both directions, silently, forever until a full rebuild**. A body-only edit leaves `anchor_delta`
empty, which is the common case and free — F34 instruments whether that holds on real edits.

**(c) The bump.** `index_state.generation` and, for a document-granularity parse, `doc.gen`, are
bumped by **one `UPDATE` inside the completing transaction**. Readers resolve the committed value,
so a torn parse is invisible (I21). Convergence is **gated, not asserted**: G19 drives a
300-document fixture through 40 scripted mutations and diffs the `.owdoc` **exports** against a full
rebuild into a second store — exports rather than tables, because an archive contains no `block_id`
and the allocation-order normalisation that could hide a bug is therefore not needed at all.

### 5.7 Cost-tier dispatch — a watcher may never bill

```python
def dispatch_policy(trigger: str, cost_class: CostClass, ledger: BudgetLedger) -> str:
    if cost_class is CostClass.FREE:           return "run_now"
    if cost_class is CostClass.LOCAL_COMPUTE:  return "run_now" if ledger.headroom(...) else "enqueue"
    return "deferred_budget"                   # BILLED_API, whenever trigger != "cli"
```

`[drivers.cost] auto_refresh_classes = ["free"]` is the config form, and two route gates enforce it:
`gate.watcher-may-not-bill` and `gate.agent-triggered-may-not-bill` clamp `max_cost_class` to
`local_compute` for `trigger` in `{watch, mcp, sdk}`. This is why `RouteHints` has no budget field
and cannot widen anything: spending money requires a human typing `ow add --allow-cost <micros>`.

**A watcher that silently re-bills a VLM pass because something touched a 400-page PDF's mtime is
the support ticket that ends a pilot.** A billed unit becomes a `deferred` work row plus a
pending-cost record the operator confirms.

**Deletions are always free to service.** Eviction needs no model, so a doc-only deletion batch must
not sit behind the confirmation flag until an unrelated code event arrives (graphify #2580).
Deletion itself is explicit and tier-blind (`ow store rm --doc d7`), never inferred: `out_of_scope`
marking retires nothing, and `ow store gc --unseen-for <days>` prints the `cite` count it is about
to retire.

### 5.8 The full-scan latch

`run.needs_full_scan` is a durable integer, set by an inexact change set and cleared **only** by a
successful full reconcile. It is set by: an incomplete-declared trigger; a directory move; watcher
event overflow; a connector reporting loss; and a change in `config_digest`. `stale_since` is set on
the **first** transition only and is **kept across a reset**, because it measures how long the
answer has been untrustworthy, not how long the attempt has run.

## Part 6 — Pipelines as data

### 6.1 The operator contract

`Operator` is **core-internal**. One generic Operator class per Port, plus the five `op.<name>`
core-only steps; **nobody outside core writes one**. The extension point is the Driver, and that is
deliberate: an operator owns accounting, retry granularity, ownership-scoped replacement and
transaction boundaries, and a third party cannot be given those without being given the store.

The Protocol lives in `omniweave_core/operator.py` beside `StepResult`, because it is pure typing.
The implementations live in the `omniweave` distribution, next to the middleware that is their only
caller:

```
packages/omniweave/src/omniweave/run/
├── operators/acquire.py · parse.py · derive.py · embed.py · compile.py   one per Port
├── ops/identify.py · converge.py                                         two core-only steps
└── ../graph/lexicon.py · resolve.py · cluster.py       the three host graph passes, per §D6
```

```python
class Operator(Protocol):
    OPERATOR:    ClassVar[str]           # '<port>.<family>' or 'op.<name>'
    OP_VERSION:  ClassVar[int]           # == Producer.op_version. AN INTEGER AT EVERY SITE
    COST_CLASS:  ClassVar[CostClass]     # an op.* step declares its own: op.cluster is local_compute
    GRANULARITY: ClassVar[Literal["document", "part", "corpus"]]
    CACHE_LAYER: ClassVar["CacheLayer | None"]     # §2.4's table, declared once, here
    def plan(self, unit: UnitRef, ctx: RunContext) -> Sequence["WorkSpec"]: ...
    def run(self, batch: Sequence[UnitRef], ctx: RunContext) -> Sequence[StepResult]: ...
    def is_valid_nonempty(self, ref: ArtifactRef) -> bool: ...
```

`run()` returns `StepResult`, which a driver may not construct — an Operator is core-internal, so it
may. It reaches the driver only through `omniweave/run/pipeline.py`, which is the single
semgrep-enforced caller of `DriverHost.invoke()`; an Operator that called the host directly would
bypass the cache, the budget and the retry semaphore in one line.

`Producer` **is** `OperatorIdentity` — one type, two layers, one table:

```
Producer.operator          = origin_operator  = '<port>.<family>'   <- THE OWNERSHIP GRAIN
Producer.op_version        = the operator's schema_version, AS AN INTEGER
Producer.code_fingerprint  = sha256(the operator module's source)[:12]  <- never a packaging lookup
Producer.runtime           = origin_driver = a driver_id '<port>.<family>.<impl>'
Producer.runtime_version   = the card's driver_version (semver)
Producer.model_id/.model_rev = the driver's declared model; model_rev is an EXACT sha
Producer.prompt_fp         = CRLF->LF, trailing whitespace stripped, THEN hashed
Producer.options_digest    = candidate.config_digest, as bytes
```

`op_version` is an integer at **every** site. The two conversion lines an earlier draft carried
(`str(...)` out, `int(...)` back) were a lossy round-trip through text on an **identity** input:
`"07"` and `7` canonicalise differently, so `producer_identity` and `work_identity` could disagree
about the same operator and neither index would notice.

`code_fingerprint` is `sha256` of the operator module's **source**, never `importlib.metadata`:
graphify's metadata fallback silently shares one cache namespace across every version in a source
checkout — for exactly the developers changing the extractor.

`prompt_fp` normalises CRLF to LF and strips trailing whitespace **before** hashing, or every
Windows checkout re-bills.

### 6.2 Three authorable registries, and none of them is a DAG

| registry | file or table | what it decides | who authors it |
|---|---|---|---|
| the driver catalog | `driver.toml` in each installed distribution, read by `importlib.metadata` + `tomllib` with **no import** | what *can* run | driver authors; the operator activates by naming ids in `[drivers] enabled` |
| the pass registry | `derive_pass` — **data, not a hardcoded pipeline list** | which extraction passes exist, their `(cost_rank, phase)` order, lanes and granularity | populated from cards at activation; gated by `[graph.passes] enable` |
| the policy | `.omniweave/policy.d/*.toml`, first-match-wins ordered `[[rule]]` rows with a required `surface` key | which Rung and which Candidate a given `(unit, part, lane)` gets | the operator |

Ordering is `(cost_rank, phase)` and nothing else: `cost_rank` in `{0, 1, 2}`, derived from
`cost_class`, is **primary**, and card-declared `phase` (default 50) orders only **within** one
rank. That is the whole of "deterministic before LLM", and it means a third party's free extractor
preempts every paid one with no core change.

`[graph.passes] enable` is a lane/pass **allowlist** and `[drivers] enabled` is the **activation**
gate (INV-5). Both apply; neither bypasses the other; and `ow doctor` **fails** on a pass enabled
in one and absent from the other.

### 6.3 The Plan document — `plan/1`

The pipeline **is** data, and it is **derived** data: the Plan is a canonical JSON projection of
(catalog x policy x pass registry x scope x the store's current state). It is emitted, hashed,
diffed and read; it is never hand-authored. That is the omniweave answer to DataFlow's three
front-ends — the definition is one document, but its authoring surface is the three registries
above, so a canvas cannot draw an edge that no policy rule can produce and an agent cannot compose a
pipeline that violates coverage ordering.

- **Emitted** by `ow ingest --dry-run --render json`, to `{output_root}/runs/{run_id}.plan.json`.
  `--dry-run` computes the Plan and the estimate and **spends nothing**, which is only possible
  because a driver constructor loads no model. graphrag has `--dry-run` on `index` and **not** on
  `update` — exactly where you want the delta priced before paying.
- **Hashed** as `plan_digest`, which is `sha256_canonical()` over the document with the
  `plan_digest` and `estimate` keys removed. Both removals matter: the estimate carries a `PriceBook`-dependent number, and
  `plan_digest` cannot hash itself. Two runs of the same scope over the same store therefore produce
  the same digest and a diff is meaningful.
- **Read** by `ow queue explain`, by a visual builder, and by an agent.

Digests are shown abbreviated to their first four hex characters below for readability; the emitted
document carries the full 64.

```json
{
  "schema": "plan/1",
  "plan_digest": "3f2a7c91e0b845d6c2f70a1839bd4e6c5a02d7f18b9c34e5610af2837bd5c904",
  "run": {
    "run_id": "r_01JC8Q2KX7M4V0ZR3NBWHT5E9D", "generation": 47, "trigger": "cli",
    "scope_id": "sc_9f1", "corpus_id": "handbook",
    "config_digest": "a91c", "semantic_digest": "77b0",
    "policy_digest": "5c1e", "catalog_digest": "e40d", "pricebook_digest": "1b7f"
  },
  "roster": { "in_scope": 1, "fresh": 0, "changed": 1, "new": 0, "out_of_scope": 0 },
  "stages": [
    { "stage": "acquire",
      "operator": "acquire.fs", "op_version": 1, "cost_class": "free",
      "granularity": "document", "driver": "acquire.fs.local", "isolation": "inproc",
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": "9c1e2a70f3b48d55",
      "cache_layer": null, "priority": 100 },
    { "stage": "identify",
      "operator": "op.identify", "op_version": 1, "cost_class": "free",
      "granularity": "document", "driver": null, "isolation": null,
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": null,
      "cache_layer": null, "priority": 300 },
    { "stage": "parse",
      "operator": "parse.pdf", "op_version": 3, "cost_class": "free",
      "granularity": "part", "driver": "parse.pdf.pdfium", "isolation": "subproc",
      "units": 12, "cached": 9, "outstanding": 3, "dispatch_key": "b7d0114ac9e26f81",
      "cache_layer": "call", "priority": 100,
      "rung": "decode", "lanes": ["text", "table"],
      "rule": "00-builtin-route.toml#12", "why": "decode.has_text_span == true" },
    { "stage": "parse",
      "operator": "parse.page", "op_version": 2, "cost_class": "local_compute",
      "granularity": "part", "driver": "parse.page.olmocr", "isolation": "subproc",
      "units": 2, "cached": 1, "outstanding": 1, "dispatch_key": "4e5f9a20cc71b3d6",
      "cache_layer": "call", "priority": 100,
      "rung": "page", "lanes": ["text"], "service": "vlm",
      "rule": "00-builtin-route.toml#31", "why": "decode.cid_ratio >= 0.30",
      "parts": ["p7", "p11"] },
    { "stage": "derive",
      "operator": "derive.segment", "op_version": 1, "cost_class": "free",
      "granularity": "document", "driver": "derive.segment.spine", "isolation": "subproc",
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": "0a13cc8e5b7f9042",
      "cache_layer": "call", "priority": 100, "cost_rank": 0, "phase": 10, "lanes": [] },
    { "stage": "derive",
      "operator": "derive.anchor", "op_version": 1, "cost_class": "free",
      "granularity": "document", "driver": "derive.anchor.native", "isolation": "subproc",
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": "77aa01d3e2b64c19",
      "cache_layer": "call", "priority": 100, "cost_rank": 0, "phase": 20, "lanes": ["anchor"] },
    { "stage": "derive",
      "operator": "derive.entity", "op_version": 2, "cost_class": "free",
      "granularity": "document", "driver": "derive.entity.table", "isolation": "subproc",
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": "c3097e1fb5d2a486",
      "cache_layer": "call", "priority": 100, "cost_rank": 0, "phase": 30, "lanes": ["entity"] },
    { "stage": "derive",
      "operator": "derive.xref", "op_version": 1, "cost_class": "free",
      "granularity": "document", "driver": "derive.xref.pattern", "isolation": "subproc",
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": "5be2f7c04198a3dd",
      "cache_layer": "call", "priority": 100, "cost_rank": 0, "phase": 40, "lanes": ["xref"] },
    { "stage": "converge",
      "operator": "op.converge", "op_version": 1, "cost_class": "free",
      "granularity": "corpus", "driver": null, "isolation": null,
      "units": 1, "cached": 0, "outstanding": 1, "dispatch_key": null,
      "cache_layer": null, "priority": 300 }
  ],
  "services": [
    { "name": "vlm", "model_id": "allenai/olmOCR-7B", "model_rev": "9f8e7d6c5b4a3928",
      "lifecycle": "would_spawn", "capacity": 8, "gpu_group": "default",
      "vram_floor_mb": 20480, "demand_units": 1 }
  ],
  "blocked": {
    "deferred": [],
    "failed_permanent": [],
    "cooldown": [
      { "operator": "acquire.http", "failure_class": "rate_limited", "units": 4,
        "next_retry_at_ms": 1772064000000, "estimated_wait_ms": 2100000,
        "reason": "provider 'arxiv' rate_limited; RATE_LIMIT_COOLDOWN_MS default" } ]
  },
  "pruned": [
    { "driver": "derive.entity.llm", "code": "OW_DRIVER_COST_CLASS_FORBIDDEN",
      "detail": "billed_api not in [drivers.cost] allow_classes" },
    { "driver": "parse.page.hunyuan", "code": "OW_DRIVER_PROBE_UNAVAILABLE",
      "detail": "omniweave-vision not installed" }
  ],
  "estimate": {
    "wall_ms_p50": 34000,
    "spend": { "calls": 1, "tokens_in": 1700, "tokens_out": 1300, "gpu_ms": 2400 },
    "would_cost_micros": 854,
    "cached_saves_micros": 854,
    "basis": "pricebook 1b7f; 1 outstanding PAGE part x olmocr p50 2.4 s = 854 micros (05 §6.2); 1 cached PAGE part replays 854; 3 free pdfium decodes price 0. wall_ms_p50 = 2400 (olmocr) + 640 (3 x pdfium 192-DPI decode) + 31000 (Service cold start, p50, UNMEASURED -- F7's band applies)"
  },
  "degradations": [
    { "kind": "layout_unavailable",
      "message": "no licence-clean layout detector installed; REPAIR is thin on the PDF path" }
  ]
}
```

**The real pipeline above** is a 12-page born-digital PDF whose pages 7 and 11 are CID-mapped
garbage. Nine parse parts are cache hits, three decode fresh, two escalate to the VLM rung — of
which page 7 is a `call`-layer hit from a previous run and only page 11 is outstanding — four free
derive passes run in `(cost_rank, phase)` order (segment 10, anchor 20, entity 30, xref 40), and
`op.converge` closes the run. `parse.page.olmocr` is **`local_compute`**, not `billed_api`: it runs a
local VLM behind the `vlm` Service, its priced dimension is `gpu_ms`, and it is admissible under the
default `[drivers.cost] allow_classes = ["free", "local_compute"]` — which is also why
`derive.entity.llm`, which is genuinely hosted, appears in `pruned` rather than in `stages`. The two
`pruned` rows are the "a zero-candidate resolution **is** the error message" rule made visible in
the plan rather than at the bottom of a stack trace.

Five rules make the format usable by three front-ends:

1. **Eleven keys are mandatory on every stage**: `stage`, `operator`, `op_version`, `cost_class`,
   `granularity`, `driver`, `isolation`, `units`, `cached`, `outstanding`, `dispatch_key`. `driver`,
   `isolation` and `dispatch_key` are `null` **together**, exactly for an `op.*` row.
2. **Every routed stage carries `rule` and `why`** — the policy file and line, plus the predicate
   that fired. A plan you cannot explain is a plan you cannot review.
3. **`cached` and `outstanding` sum to `units`.** That is §5.5's `CacheProbe` projected into the
   document, and it is what makes `--dry-run` a cost estimate rather than a shape.
4. **`blocked` is a first-class block, not an omission.** LDR's lesson is that a batch admission
   check must return a per-item verdict *with a reason and an ETA*, plus an aggregate by failure
   type (`retry_manager.py:44`, `FilterSummary`), and that `ow ingest` must print it before it
   starts and after it ends. Without it, [15-observability.md](15-observability.md) §R2's stalled
   corpus — 88,104 rows `deferred`, nothing red — is invisible at plan time, which is the one moment
   the operator can still act cheaply. `deferred` groups by `dim`, `cooldown` by `failure_class`
   with a `next_retry_at_ms` and an `estimated_wait_ms`, and `failed_permanent` by `failure_class`
   so a corpus's dead weight is one number.
5. **No import paths, ever.** A stage names a `driver_id`, and ids are validated against the
   catalog. Config that is an import path is RCE the moment config arrives in a request body, and
   omniweave is served: marker's `--converter_cls` / `--processors` through `strings_to_classes`,
   merged from `--config_json`, is the anti-pattern.

**What the plan does not carry**, because the whole point of one definition is one home per fact:
no per-driver config values (they are in `config_digest`, and `ow show-config` prints them with
their sources), no policy rule bodies (`policy_digest` plus `rule` locates them), and no store
statistics beyond the roster counts.

### 6.4 Three front-ends over one definition

| front-end | reads | writes | how |
|---|---|---|---|
| **code / CLI** | `plan/1` | the three registries | `ow ingest --dry-run --render json`; `ow queue explain <work_id>` prints the stage plus the rule that produced it |
| **a visual builder** | `plan/1` | `.omniweave/policy.d/*.toml` and `[graph.passes] enable` | stages are nodes, `dispatch_key` groups them into batches, `rule` links a node back to the policy row that created it. It **cannot** draw an arbitrary edge: an edit round-trips through a policy rule and `ow route lint` |
| **an agent** | `plan/1` plus the generated Action catalog | the same registries, through Actions | the plan is a JSON document under 24,000 chars for a typical scope, with `blocked`, `pruned` and `degradations` already explaining what is missing and which knob fixes it |

The three front-ends are the same document because the *authoring* surface is the registries, not
the plan. A builder that could edit the plan directly would be editing a projection: the next
`--dry-run` would overwrite it, and the operator would learn that their canvas has no memory.

DataFlow's suite proves the value of one definition and three surfaces — a WebUI drag-and-drop
builder, natural-language interaction, and a `DataFlow-agent` that recombines existing operators or
creates new ones on demand — and its **trace-compilation** idea is worth taking in one specific
form: `inspect.signature(fn).bind(*a, **kw).apply_defaults()` produces a *complete,
self-describing, hashable* call record, so a plan can be printed, diffed or hashed without the
caller having repeated every default (`dataflow/wrapper/auto_op.py`). omniweave applies exactly that
to `WorkSpec` construction, which is why `plan_digest` is stable. What it does not take is
DataFlow's *mechanism*: `AutoOP.run` returns `None` because it records instead of executing, so any
`forward()` that uses an operator's return value silently breaks at compile time
(`kbcleaning_pipeline.py` does exactly this and gets away with it only because the value is unused),
and signature introspection makes wrappers hazardous enough that `RayAcceleratedOperator` needs a
30-line hack to survive it. omniweave builds `WorkSpec` in the planner explicitly; the `bind` +
`apply_defaults` discipline applies to the *record*, not to a proxy that replaces the call.

What omniweave also does **not** take is the DAG-from-parameter-spelling. DataFlow derives its graph
from `input_*` / `output_*` kwarg **name prefixes** (`dataflow/pipeline/nodes.py`), which makes the
graph depend on parameter spelling; its key-flow validation then has no types (`text` produced as
`str` and consumed as `list[str]` passes), no nullability semantics, no detection of a key being
**overwritten** by two operators — `last_modified_index_of_keys[k]` is a list precisely because that
happens, and nothing warns — and it **mutates the recorded plan**
(`kwargs.pop("storage", None)`), so the plan you would hash is not the plan you recorded. omniweave
declares `CONSUMES`/`PRODUCES` as explicit artefact kinds and validates in both directions.

The one thing to copy verbatim is DataFlow's **error message shape**: it names the key, the pipeline
attribute, the class **and the parameter to fix**. Most frameworks name only the key.

### 6.5 What is deliberately not authorable

| refused | why |
|---|---|
| a user-authored DAG file | a DAG whose nodes are operators lets an author violate `(cost_rank, phase)` coverage ordering, ownership-scoped replacement and transaction grain — the three things that make a mixed-cost pipeline correct |
| a third-party Operator | it would need the store, the cache, the budget ledger and `Store.complete()`. That is the whole of INV-6, INV-7 and INV-17 |
| a general workflow engine (Prefect / Dagster / Temporal / Ray / Celery) or a broker | a second durable store that must agree with `work` about what is done; a second scheduler's semantics between the operator and `ow why`; a service that must be running before `ow ingest` works on a laptop; tens of MB against the 250 MB aggregate gate. DataFlow priced the wrapper tax: RayOrch needs `AcceleratedOperatorABC` subclasses and a `MemoryStorage` shim, so an operator is either local or distributed and porting is a rewrite |
| a step-numbered or JSON-bag checkpoint | eight documented failure modes; artefacts outside the checkpoint model and not content-addressed; a row index unstable under batching; and graphrag's `state: dict[Any, Any]` makes reordering the workflow list a `KeyError` hours in |
| an import path in config | RCE the moment config arrives in a request body (marker's `strings_to_classes`) |
| a plan file as *input* | it is a projection of four registries and the store; accepting it as input would make it a fifth registry that can disagree with all of them |

## Part 7 — Budgets and quotas

### 7.1 Physical, then priced, per dimension, first exhausted wins

A driver reports `Spend` — seven physical units plus a provider tag — and only the operator-owned
`PriceBook` converts it to micros (INV-15). `DriverMetrics` has no currency field, ever: a
contributor on a rented A100 cannot know your GPU-hour cost, and if they guess, every estimate in
your fleet is wrong in a way you cannot audit.

Budgets are declared **per dimension**, and the **first exhausted dimension wins**, because a count
cannot bound spend when per-attempt cost varies 100x with page density. The measured anti-pattern is
Unlimited-OCR's `8,000 tokens x 8 retries = 64,000 output tokens per page`, fired in parallel — a
request-count cap does not see it and a token cap does.

| `dim` | unit | what it bounds | scopes it is declared at |
|---|---|---|---|
| `micros` | millionths of the pricebook currency | money | `run`, `corpus`, `unit`, `part`, `operator` |
| `tokens_in`, `tokens_out` | tokens | context and generation blow-ups | `run`, `part`, `operator` |
| `calls` | requests | **a held `(dim='calls', scope='provider')` sum IS the cross-process in-flight count** | `provider`, `run` |
| `gpu_ms` | ms | local-compute GPU spend | `run`, `operator` |
| `wall_ms` | ms | a run's total time | `run` |
| `cpu_ms` | ms | a background refresh's footprint | `run` |
| `bytes_egress` | bytes | **defaults to 0** | `run`, `corpus` |

`bytes_egress = 0` by default means the first hosted escalation is a deliberate act requiring a
site-layer `Grant` with a `dpa_ref`, printed in the run manifest of every document it covers.

Currency caps have exactly **one** home: `.omniweave/policy.d/*.toml` under `[budget.per_part]` and
`[budget.per_unit]`. `omniweave.toml [budget]` holds admission only (`max_inflight`) and has no
`per_document_micros`, so there is no second knob, no undefined precedence, and a `Degradation`
message can name a key that exists.

### 7.2 Where it is enforced — three sites, and only three

| site | what it does | what it may not do |
|---|---|---|
| `evaluate()` | chooses the Rung and the Candidate, **purely** over `(policy, evidence, hints)` | see a ledger, a clock, an RNG, env, IO or `RunContext` (INV-14) |
| `admit()` | reserves the chosen decision's estimate against the durable ledger. Outcomes `admitted \| deferred \| degraded` | change **which** rung was chosen |
| `with_budget` | reserve before the call, commit after, release on cancel | run outside `with_cache` (a hit must cost nothing) or inside `with_retries` (a retry must re-check) |

**Budget never changes which rung is chosen, only whether it runs.** Exhaustion re-enters the next
decision as the evidence key `budget.exhausted` — the single channel by which budget reaches routing
(INV-14). That is what keeps the routing scoreboard interpretable: a rung that was never chosen and
a rung that was chosen and denied are different rows.

### 7.3 Reserve, commit, release

```sql
-- headroom, ALWAYS computed in SQL, never cached in an attribute (I29)
SELECT :limit
     - COALESCE((SELECT SUM(amount) FROM budget_reservation
                  WHERE dim=:dim AND scope=:scope AND scope_key=:key AND state='held'), 0)
     - COALESCE((SELECT SUM(amount) FROM budget_reservation
                  WHERE dim=:dim AND scope=:scope AND scope_key=:key AND state='committed'), 0);
```

```
reserve   INSERT budget_reservation(reservation_id = 'res_' || sha256_canonical(identity)[:24],
            run_id, work_id, decision_id, dim, amount = <the p95 CEILING>, scope, scope_key,
            claimed_gen, expires_ms = the work row's lease_expires, state = 'held')
          -- the id is content-addressed over (work_id, decision_id, attempt, dim), so a retried
          -- reserve is idempotent AND one reservation per dimension is a distinct row
commit    UPDATE ... SET state='committed', amount=<ACTUAL> WHERE reservation_id=? AND state='held'
          -- IN THE SAME TRANSACTION as the derived rows, the work transition, the dep rows
          -- and the spend row (I20)
release   UPDATE ... SET state='released' WHERE reservation_id=?      -- cancel, or a cache hit
reap      UPDATE ... SET state='released' WHERE expires_ms < :now AND state='held'
          -- IN THE SAME TRANSACTION as the lease reap, so a SIGKILL cannot leak headroom
```

**One decision takes one reservation row per dimension it is capped on**, which is why the crash
snapshot of §1.5 shows six `held` rows for three in-flight units: two `gpu_ms` rows for the two
`local_compute` parts, and `micros` + `tokens_in` + `tokens_out` + `calls` for the one `billed_api`
part. `dim` is a column, `reservation_id` is the primary key, and the identity that produces it
includes `dim` — otherwise four dimensions would collide on one id and three of them would silently
not be reserved.

`amount` is the **p95 ceiling**, not the mean: a reservation that under-estimates admits work the
budget cannot pay for. The over-reservation is released at commit, so the cost of pessimism is
throughput, not money — at `tokens_out_p95_multiple = 3.2`
([05-ingest-and-routing.md](05-ingest-and-routing.md) §6.4), in-flight reservations consume 3.2x the
eventual spend, so effective concurrency against a per-unit cap is roughly a third of nominal, and
release-on-commit is what buys it back. F6 is the open number the whole model rests on — the only
published anchors for a page VLM's `tokens_out` p95 are **3.4x apart**.

Every `billed_api` operator implements `estimate(unit) -> Estimate`.
`ow drivers check --estimates` fails a declared p95 multiple that understates measurement by more
than 25%, or an estimate more than 2x off the 7-day measured median.

### 7.4 Behaviour at exhaustion

| exhausted | who sees it | behaviour | what the operator is told |
|---|---|---|---|
| a `part`- or `unit`-scoped `micros` cap | one part | `admit()` returns `deferred`; the work row goes `deferred` with `attempts_total` decremented and `cost_micros` unchanged; `budget.exhausted` is written into that part's Evidence and the **next** decision may choose a cheaper rung (`DEGRADE`) | `Degradation(kind="budget", ...)` naming `[budget.per_part] micros` — or `micros_per_part`, whichever actually bound |
| a `run`-scoped `micros` or `wall_ms` cap | the run | remaining `billed_api` rows stay `deferred`; **free and local rows keep running**, so the run still produces a usable index. `stall_detector` (§2.5) ends the run rather than spinning if nothing else can drain | `run.status = 'partial'`, `degradations[]`, and the manifest's deferred count by dimension |
| a `provider`-scoped `calls` cap | one provider | admission blocks; the semaphore *is* the held-reservation sum, so it holds **across processes** | `budget.deny{dim, scope, headroom}` events |
| `bytes_egress` (default 0) | the first hosted call | the driver is not activated at all; `resolve()` returns `EGRESS_NOT_GRANTED` | the exact `ow` command that creates a `Grant`, with `--allow-egress <grant-id>` |
| a `local_compute` dimension | one unit | it is a **queue** decision: the row waits for headroom behind `class_sem[LOCAL_COMPUTE]`, it does not fail | nothing, unless the run ends with it still waiting — then §2.5's detector says so |

**A denial is never a failure.** `DEFERRED_BUDGET` is an `Outcome`, it consumes no attempt (§1.2),
and it has a named path back to `pending`. Without a distinct outcome, budget exhaustion is
indistinguishable from breakage, and an operator's first move on seeing failures is to retry —
which is the one thing that cannot help.

A retry is a **rung** (`REGEN`), strictly serial per `(unit, part)` behind `Semaphore(1)`, and it is
charged to the **same** per-part budget. That is what stops the retry ladder from being an unbounded
multiplier on the per-page cost.

### 7.5 The two self-checks that make the numbers trustworthy

`omniweave/run/manifest.py` writes the run manifest incrementally and asserts, at run end:

1. `sum(route_spend.micros) == manifest.cost.billed_micros`, **exactly**. Not within a tolerance —
   every micro is attributable to exactly one `(unit, part, decision, attempt)` (I30).
2. Every `ok` / `ok_partial` row **with a `decision_id`** has at least one spend row, and a
   Sequence's apportionment (per-session cost split by token share) sums to the session plus or
   minus one micro.

A failure of either is a hard run failure, not a warning.
`manifest.cost.would_have_been_micros_if_uncached` is the third number and it comes from
`cache_index.spend_json` replayed at the current `PriceBook` — the only honest way to report savings
when 90% of calls are hits.

### 7.6 The `op.*` accounting hole, and where its spend goes

`route_spend.decision_id` is `NOT NULL REFERENCES route_decision`, and an `op.*` work row has a NULL
`decision_id` by CHECK. So a core-only step **cannot have a `route_spend` row**, and
`budget_reservation.decision_id` being `NOT NULL` means it cannot hold a reservation either. For
four of the five `op.*` steps that is correct and free: `op.identify`, `op.converge`, `op.lexicon`
and `op.resolve` are `cost_class = 'free'`. `op.cluster` is **`local_compute`**, and it is the
exception that has to be answered rather than assumed away.

The answer, pre-committed and using only columns that already exist:

- **Admission** for `op.cluster` is `class_sem[LOCAL_COMPUTE]` plus `render_sem` where it rasters,
  not the durable ledger. That is sufficient because the ledger's load-bearing job is bounding
  *billed* concurrency across processes, and there is no provider to over-offer.
- **Its spend is recorded on its own `work` row**: `cost_micros`, `ran_ms`, `peak_rss_bytes`, priced
  by the runner from `StepMetrics.spend` through the `PriceBook` exactly as for any other row.
- **The manifest carries two figures, not one.** `manifest.cost.billed_micros` is
  `Σ route_spend.micros` and stays exact, which is what self-check 1 asserts.
  `manifest.cost.op_micros` is `Σ work.cost_micros WHERE operator LIKE 'op.%'`, and
  `manifest.cost.total_micros` is their sum. `ow cost --by driver` reports the `op.*` rows under a
  synthetic `op` driver row so they are visible rather than merely recorded.
- **A `run`-scoped `gpu_ms` cap therefore does not bind `op.cluster`.** This is a real limitation and
  it is stated rather than hidden; the mitigation is that `op.cluster`'s GPU use is bounded by
  `class_sem` and by its own `wall_ms_hard`, and the residual is a written open question.

The general rule this establishes: **a `cost_class` that is not `free` needs either a
`route_decision` or an explicit non-ledger admission path, and there are exactly two such steps in
the framework.** A future `op.*` step at `local_compute` or worse must take one of the two, and
`ow doctor` fails on a third.

## Part 8 — Cancellation, deadlines and shutdown

### 8.1 Two mechanisms: a signal that stops work, and a generation that makes it safe

Cancellation is often described as one thing. It is two, and conflating them is how a design ends up
either unable to stop or able to write a result nobody wants.

| mechanism | what it does | what it cannot do |
|---|---|---|
| `CancelToken` on `RunContext`, plus the `CANCEL` frame on S4 | **propagates** the intent: one object per run — the ingest path's cancellation scope, printed in §1.3 — checked at every loop top by the Supervisor, by each `worker_loop`, and by the driver through `DriverIO.cancelled()` | stop a foreign process mid-kernel (§8.3), or prevent a result already in flight from arriving |
| `claimed_gen`, compared inside the committing `UPDATE` | **makes it safe**: a result produced under a superseded generation writes nothing | stop the work — by the time it fires, the work is done and the money is spent |

The commit predicate is the second mechanism entire:

```sql
UPDATE work SET status = :status, ... WHERE id = :id AND claimed_gen = :gen AND status = 'claimed';
-- ZERO ROWS => SUPERSEDED => THE WHOLE TRANSACTION ROLLS BACK. The claim IS the lease (I23).
```

No extra lock, and check-and-commit is atomic with respect to the generation bump by construction.
The test bumps the generation mid-flight and asserts `CANCELLED` plus **zero rows written**.

**Which events bump the generation, and which do not.** Only a new run does: `run.generation =
old.generation + 1` at startup (§1.5 step 3). A Ctrl-C does **not** bump anything — it sets
`ctx.cancel`, and the rows it releases go back to `pending` at their existing generation, so the
next run picks them up cleanly. Supersession is therefore what happens when a *second* run starts
while a worker from a previous one is still alive: a watcher-triggered refresh overlapping a
manual `ow ingest`, or a worker whose parent was SIGKILLed and which is still finishing a page. Its
late `RESULT` frame updates zero rows and is recorded as `work.cancel{work_id, generation}`.

Wall clock is the wrong stamp for this, and codegraph's is: a backward NTP step makes a serviced
entry permanently stale or silently evicts an unserviced one.

### 8.2 Three deadlines, all named, all separate

| deadline | measures | default | fires on |
|---|---|---|---|
| `progress_ms` | time since the last `PROGRESS` frame | per-card (the reference card: 15,000) | a **silent** driver — a hang with no output |
| `wall_ms_hard` | total invocation wall time | per-card (the reference card: 60,000) | a **chatty** driver that progresses forever |
| `deadline_ms` | this `INVOKE`'s deadline, carried in the frame and in `DriverIO.deadline_ms` | derived from the part budget's `wall_ms` less elapsed | the work this batch was admitted for running out of time |

One number cannot do all three: a VLM emitting a token every 400 ms for six hours is not hung, and a
driver that renders a page for 90 s with no output is not chatty. Unlimited-OCR's
`MAX_RETRIES = 5` times `REQUEST_TIMEOUT = 1200` is 100 GPU-minutes per document from a single
misconfiguration, which is what happens when the only knob is a timeout. `PROGRESS` is the **only**
frame that resets `progress_ms` — a `LOG` frame does not, or a chatty driver making no progress
looks alive forever — and a driver cannot extend its own wall clock.
[04-driver-system.md](04-driver-system.md) §6.3 owns what the host *does* when one fires; §1.6 owns
how the resulting `FailureClass` is classified, and the answer is `FAILED_PERMANENT{TIMEOUT}` with
`limit` naming which of the two.

### 8.3 How a cancel reaches a driver inside a GPU inference

The hard case, step by step, and it has two variants because the loss is different. A
`local_compute` `parse.page.olmocr` invocation is mid-forward-pass on the shared `vlm` engine when
the user presses Ctrl-C.

```
t+0 ms     SIGINT -> the loop's signal handler sets ctx.cancel. TaskGroup cancellation begins;
           every worker_loop catches BaseException and NEVER propagates, so shutdown is
           structured and one crash costs one unit.
t+0 ms     the Supervisor sends CANCEL{invoke_id, generation} on the S4 socket to every subproc
           worker holding a claimed Batch. Frame kind 9. Non-blocking.
t+~1 ms    the worker's reader thread sets its own cancelled flag. The DRIVER observes it two
           ways: DriverIO.cancelled() at its next loop top, and the CANCEL frame.
t+? ms     * THE FORWARD PASS IS NOT INTERRUPTIBLE. omniweave does not own the engine process
           and will not claim it can abort a kernel. What it can do, and does:
             (a) the driver stops SUBMITTING. ServiceHandle.cancelled() returns True, so the
                 next of the batch's parts is never posted.
             (b) the outstanding HTTP request is abandoned: ServiceHandle.post() is issued with
                 a socket timeout of min(remaining deadline_ms, request_timeout_s), and on
                 cancel the connection is closed. The engine finishes that one forward and
                 discards the response.
             (c) the driver returns, or raises DriverError(TIMEOUT).
t+grace    if the worker has not returned within [runtime] shutdown_grace_ms = 5000, the host
           sends SHUTDOWN{grace_ms}; then SIGTERM; then SIGKILL at +5 s, reaping the WHOLE
           PROCESS GROUP. Both signals are recorded.
t+commit   the Supervisor writes StepResult(outcome=CANCELLED) for every claimed row -- through
           the SAME commit predicate, so a late RESULT frame from a worker that was already
           reaped writes nothing. Each row goes to `pending` with attempts_total decremented.
t+commit   every held reservation for those rows is RELEASED in that transaction.
           The engine is NOT stopped: keep_alive_s governs it, and a process that merely
           ATTACHED never stops a server it did not start.
t+end      run.status = 'interrupted'. The manifest is already on disk (it is written
           incrementally), and the claimable set is exactly the unfinished work.
```

**What is lost differs by cost class, and the difference is the whole reason to state it:**

- For a **`local_compute`** Service like `vlm`, the loss is **GPU-seconds on your own hardware**.
  Nothing was billed; `route_spend` records no attempt; the reservation on `gpu_ms` is released.
  The operator paid in electricity and wall time.
- For a **`billed_api`** driver like `derive.entity.llm`, the loss is **money the provider charges
  for tokens it generated after we stopped listening**. Our ledger therefore under-counts an
  interrupted run by at most the in-flight parts' actual spend, because the reservation was released
  rather than committed. The manifest records `interrupted_inflight: n` — the count, not the amount,
  which is exactly the residue Open questions names.

Two honest statements this design refuses to hide. **A GPU forward pass in a foreign process cannot
be aborted by us**, so cancellation is "stop submitting and abandon the response", not "stop
computing". And **a provider bills for what it generated after the socket closed**, so an
interrupted run's cost is a lower bound and is labelled as one.

### 8.4 The watchdog, the yield rule, the futility latch and the per-worker caps

| mechanism | value | what it protects |
|---|---|---|
| `[runtime] watchdog_ms` | 60,000 | **no synchronous stage may exceed `watchdog_ms / 2`** (I15). Four `CREATE INDEX` at ~20 s each is 79 s against a 60 s liveness watchdog, and codegraph's daemon-triggered re-index was **SIGKILLed right after doing the work** — the most expensive failure available is one that discards completed work |
| `[runtime] yield_interval` | 1,000 items | a cooperative yield **at the top of the loop body**, so a `continue` fast path still yields. At the bottom it is a yield the common path skips |
| `[runtime] loop_lag_max_ms` | 250 | `lag_monitor` samples at 100 ms; a breach is a **one-way** `degrade()`, and CI asserts p99 loop lag (I32) |
| the futility latch | 2 consecutive give-ups implies disable for 60 s and degrade to the un-repaired behaviour, with an `armed` log line and a heartbeat | **a governor must detect that it cannot help and get out of the way** (I9). codegraph's WAL valve produced 22 GB of WAL and an OOM-kill (exit 137) at an envelope the un-valved build survived |
| proportional thresholds | `clamp(db_bytes / 4, 256 MB, 2 GB)` | a flat resource threshold is wrong at both ends: 256 MB cost 111 s of folding on a kernel-scale index |
| per-worker caps | `nice(10)`; `RLIMIT_DATA` on darwin and `RLIMIT_AS` on linux (`RLIMIT_AS` is unreliable under Apple's libmalloc); a job object on Windows; a wall-clock watchdog using `SIGALRM` where available — it unwinds and releases locks — and a `threading.Timer` plus **`os._exit`** fallback where not; per-worker peak-RSS sampled into `StepMetrics` | a background refresh must lose to the user's editor, and a VLM page parse that allocates gigabytes must not take the editor with it. `os._exit`, not `sys.exit`: a `Timer` thread raising `SystemExit` would not stop the main thread. **What was not obtained is recorded, never claimed** — Windows has no `RLIMIT_CPU` analogue, so `wall_ms_hard` is the only cap there and the `driver_observation` row says so |

All four unattended entry points — the watcher, a `PostToolUse` hook's detached child, a
post-commit hook's child, and `ow ingest` itself — take the full set. graphify applies them only on
the hook path (`graphify/watch.py:221`, `_apply_resource_limits`), which means its watcher can still
out-prioritise the editor it is watching.

## Part 9 — Distributed execution: the seam, not the cluster

### 9.1 What the single-node design does not cover

Stated as limitations, not as future work.

1. **Two hosts cannot share one `.owstore`.** The `store.write` lock's identity is
   `(host, pid, process_create_time)`; a second host is a **refusal**, not corruption.
2. **No shared blob namespace.** CAS is a local directory under `roots.cache`. A worker on another
   host cannot fetch a blob by digest without a shared or object store.
3. **No cross-host claim fairness, no work stealing, no rebalancing.** SQLite's claim is one
   `UPDATE` in one process's transaction; there is no gossip and no leader.
4. **No cross-host Service discovery.** `attach_or_spawn` reads a sentinel in `$OMNIWEAVE_HOME`,
   which is per-user and per-host.
5. **The honest ceiling is ~10^7 parts on one host.** 100k documents at 300 pages of legal
   discovery — 30M parts, ~7.5 GB of work rows — is **not this design on SQLite**, and the plan says
   so rather than implying the file scales forever. Store-side envelopes are
   [07-store-and-retrieval.md](07-store-and-retrieval.md) §12.
6. **Multi-tenancy is store-per-tenant** (F27). Row-level tenancy is not designed and no plan
   document may assume it.
7. **One writer bounds ingest throughput even on one host.** Several `ow` processes may write, but
   the `store.write` lock serialises them, so the commit is the ceiling (§2.6). Distribution does
   not remove that ceiling; it moves it to whatever the T3 backend's commit throughput is.

### 9.2 The seam, and it is four methods

```python
class Store(Protocol):
    """THE ONLY THING THAT CHANGES BETWEEN T1, T2 AND T3. Never widened."""
    def claim(self, cost_class: CostClass, batch: int, gen: int,
              worker: str, lease_ms: int) -> Sequence["WorkRow"]: ...
    def complete(self, row_id: int, gen: int, result: StepResult,
                 *, deps: Sequence["Dep"], rows: "DerivedRows") -> bool: ...   # False => superseded
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...
```

`complete()` is the only mutation entry point, and one call is one transaction containing the
derived rows, the work transition, the `dep` rows, the reservation commit and the spend row. It
returns `False` for exactly one condition — superseded — and **raises** for every other refusal
(`MAX_DEPS_PER_UNIT` exceeded, a `dep` key outside the invocation's input set, a `cache.put`
allowlist violation), because a boolean that means both "someone else won" and "your driver is
wrong" turns a bug into a no-op. That is what makes T3 a backend swap rather than a rewrite.

The full T3 distribution boundary is four protocols — `Store` (4 methods), `Reader` (6), `DocSink`
(11) and `GraphSink` (12), 33 methods — and this document owns only the first. Saying "four methods"
understates the port by an order of magnitude, and an ADR sized off that number would be wrong by
that factor.

**The whole of a Postgres T3 backend's queue change is the claim:**

```sql
WITH head AS (
  SELECT dispatch_key FROM work
   WHERE cost_class = $1 AND status IN ('pending','failed_transient')
     AND (retry_after IS NULL OR retry_after <= (extract(epoch from now())*1000)::bigint)
     AND attempts_total < 5 AND claimed_by IS DISTINCT FROM $3
   ORDER BY priority DESC, dispatch_key, id
   LIMIT 1),
picked AS (
  SELECT w.id FROM work w JOIN head h ON w.dispatch_key = h.dispatch_key
   WHERE w.cost_class = $1 AND w.status IN ('pending','failed_transient')
     AND (w.retry_after IS NULL OR w.retry_after <= (extract(epoch from now())*1000)::bigint)
     AND w.attempts_total < 5 AND w.claimed_by IS DISTINCT FROM $3
   ORDER BY w.priority DESC, w.id
   LIMIT $2
   FOR UPDATE SKIP LOCKED)                     -- <- the entire difference
UPDATE work SET status='claimed', claimed_by=$3, claimed_gen=$4,
       lease_expires=(extract(epoch from now())*1000)::bigint + $5,
       attempts_total = attempts_total + 1,
       last_attempt_at=(extract(epoch from now())*1000)::bigint
 WHERE id IN (SELECT id FROM picked)
RETURNING *;
```

The `work` schema is deliberately portable to make that true: no SQLite-specific types, `IFNULL`
folded (a Postgres backend uses a generated column or `COALESCE` in the index), the empty string
rather than NULL in `unit_part`, and a store-clock timestamp rather than a worker's.

**No operator changes.** That is the entire point of making the store the distribution boundary, and
it is only true because three properties hold — the IO port is the single seam, the unit of work is
addressable with content-addressed inputs, and row identity is stable and independent of batching.
DataFlow fails the last two (artefacts are paths, not payloads; the row index is not stable under
batching) and then charges a wrapper tax on top.

### 9.3 What else a distributed backend must supply

The queue is the easy half. Four more substitutions, each with a named contract:

| component | single-node | what T3 needs | contract it must keep |
|---|---|---|---|
| **blobs** | `roots.cache/cas/ab/cd/<sha256>` | an S3-compatible or shared-FS `BlobStore` | `put(BinaryIO) -> sha256` is idempotent by construction; `path(digest)` becomes a signed URL, and `DriverIO.blobs` is the only accessor a driver has, so nothing else changes |
| **locks** | `omniweave_core.locks`: `O_CREAT\|O_EXCL` plus `flock` plus `(host, pid, create_time)` | a lock whose liveness check works across hosts — an advisory Postgres lock, or a lease row | `inspect()` without acquiring; `held()` exposing `waited_seconds` and **naming the holder**; a live holder past its lease is extended once with a warning, **never** stolen |
| **Services** | attach-or-spawn against a local 0600 sentinel | a pinned `[services.*] endpoint`, which is already the shipped branch (step 0 of §3.3) and takes no lock and spawns nothing | model-id verification on attach, and a token that is not `"EMPTY"` |
| **events** | `roots.output/events/{run_id}.ndjson`, 64 MiB shards | any sink; `ow trace export [--follow]` is already a separate process | `TraceSink.emit` must not block; W3C trace ids already reach every seam (I33), so the span tree reassembles across hosts with no change |

**What a distributed backend must also keep, and it is easy to break:** the cache. `cache_index` is
a store table, so it moves with the store, but the CAS blobs it references do not — a T3 backend
that shares the queue and not the blob store produces `miss_corrupt` on every entry written by
another host, silently re-deriving and (worse) re-billing. So the contract is stated: **a T3 store
and its `BlobStore` are swapped together or not at all**, and `ow doctor` fails a configuration that
names a `postgres` store with a local CAS root.

The file-descriptor arithmetic is the constraint on the *other* axis: a per-tenant encrypted store at
`pool_size=20, max_overflow=40` costs `tenants x 60 x 3` file descriptors plus ~0.2 ms per
`PRAGMA key`. Per-project stores are right for a desktop or single-team deployment and wrong for a
multi-tenant service; the **pooling model** changes, not these numbers. Also: `engine.dispose()` on
a cleanup schedule, because SQLCipher plus WAL leaks handles on out-of-order closes and long-lived
handles otherwise accumulate over days of idle operation.

### 9.4 What is refused, and stays refused

A distributed backend may **not** introduce: a second durable record of what is done; a broker; a
long-lived local IPC daemon for parsing, embedding, indexing or scheduling; a parallel operator type
hierarchy; or a loopback TCP control port for omniweave's own IPC. The two sanctioned loopback TCP
endpoints are named and stay named: an attached or spawned model server (S3), and `ow serve --http`,
which refuses a non-loopback bind without `--api-key`.

## Runtime configuration, in one table

Every key here is `operational` — none of `runtime.**`, `budget.**` or `observe.**` enters a cache
key (I26) — and every key carries an `OMNIWEAVE_*` twin.

| key | default | what it bounds |
|---|---|---|
| `[runtime] queue_high_water` / `queue_low_water` | 50000 / 25000 | the claimable-set hysteresis; never one threshold |
| `[runtime] plan_batch` | 512 | roster rows per discovery transaction |
| `[runtime] store_group_commit_ms` | 20 | the group-commit window, for zero-derived-row transitions **only** *(Build note, D919: by a user ruling of 2026-10-22 on F8 the window is taken narrow: `SqliteStore.complete_group()` commits zero-derived-row transitions of one operator and one cost class in one transaction, and the supervisor's committer gathers them across batches for up to the window, closing at once when no other batch is in flight. A unit with derived rows still commits alone. `0` turns it off. G21 kills the group at each of its five boundaries and checks, before `ow resume`, that no unit of a torn group is done. G22 at 100,000 units went from 870 to a median of 2,651 transitions/s over seven runs, two of them under 2,000, on a developer machine, not `ow-bench-1`.)* |
| `[runtime] lease_ms` / `lease_extend_ms` | 120000 / 60000 | a claim's lease, and the one extension a live holder gets |
| `[runtime] watchdog_ms` | 60000 | the liveness watchdog; I15 caps a synchronous stage at half of it |
| `[runtime] loop_lag_max_ms` | 250 | `lag_monitor`'s one-way degrade threshold |
| `[runtime] yield_interval` | 1000 | items between cooperative yields, at the top of the loop body |
| `[runtime] interactive_wait_ms` / `batch_wait_lock_ms` | 2000 / 60000 | the two named `store.write` wait budgets, passed per call |
| `[runtime] max_inproc` / `inproc_bulk_threshold` | 2 / 64 | in-process office decodes, and the batch size above which even office goes `subproc` (F2) |
| `[runtime] max_deps_per_unit` | 256 | `MAX_DEPS_PER_UNIT`; past it a cohort dep is mandatory |
| `[runtime] work_compact_above` | 5000000 | when `done` rows move to `work_done` |
| `[runtime.claim] batch` | `{free=256, local_compute=32, billed_api=8}` | the AIMD starting point, clamped by the card |
| `[budget] max_inflight` | `{free=32, local_compute=4, billed_api=2}` | **units** in flight per cost class |
| `[drivers] max_workers` | `{free=4, local_compute=4, billed_api=8}` | **worker processes** per cost class |
| `[drivers] worker_idle_ttl_s` | 300 | a `subproc` worker's idle life; run-scoped, never a daemon |
| `[drivers] crash_quarantine` | `{crashes=3, window_s=60}` | quarantines the **driver**, not the unit |
| `[services.<name>] batch_wait_ms` / `max_batch` / `capacity` / `keep_alive_s` | 5 / 8 / 0 / 300 | the Coalescing window, its ceiling, derived capacity, residency |
| `[cache] recipe` | 1 | the key-recipe namespace; a bump namespaces and never deletes |
| `[cache] gc` | `{free_after_days=7, local_after_days=90, billed_after_days=0}` | 0 = never |
| `[cache] min_free_bytes` | 5368709120 | the write refusal, naming the knob |
| `[cache.max_bytes]` | `blob=107374182400, render=21474836480, signal=2147483648, call=0, embed=0` | the per-layer LRU bound of §4.7(c); 0 = unbounded |

New keys this document introduces, each `operational` by §4.3's rule, and each flagged under
**Extends the charter**:

```toml
[runtime]
shutdown_grace_ms  = 5000
deferred_sweep_ms  = 5000
stall_poll_ms      = 30000
max_sequence_units = 64

[watch]
debounce_ms        = 2000
quick_quiet_ms     = 300
quick_max_pending  = 2
scoped_max_pending = 500
backend            = "auto"

[services.vlm]
gpu_group     = "default"
vram_floor_mb = 0
server_argv   = []

[providers.default]
rate_limit_cooldown_ms = 3600000
```

## Runtime invariants: where the most-read ones are discharged

I1-I34 are the charter's and are binding; this document adds none and restates none. The seven it is
most often read for:

| # | claim | the section that discharges it |
|---|---|---|
| I5 / INV-18 | an incremental run converges to a full rebuild | §5.6's `op.converge`, the `anchor_delta` and the `dep` reverse index, gated by **G19**, which diffs the `.owdoc` **exports** against a full rebuild into a second store and owns its own fixture size and mutation count (§5.6(c)) |
| I6 | a crash loses no work and creates no phantom completion | §1.5, step by step, on the 100,000-document case; §1.2's transition table for the row-level rules |
| I7 | every failure path terminates | §1.2's `clear_old_permanent(30d)` and `deferred_sweeper`; §1.6's five-attempt ladder |
| I9 | a repair or governor loop cannot make things worse than not running | §8.4's futility latch, and §2.5's `stall_detector`, which is the same idea applied to the whole loop |
| I25 | a cache hit consumes zero budget, zero tokens and zero rate-limit slots, and replays its Spend | §2.4 (composition) plus §4.5 (verdicts) plus §5.5 (`CacheProbe`) |
| I26 | no `operational` config key enters a cache key | §4.2 (the input table) plus §4.3 (the axis, including this document's new keys) |
| I28 | every derivation's cross-unit inputs are recorded, as dep rows or a cohort digest | §5.6(a), three population paths, with G19 as the enforcer |

## Extends the charter

Fifteen additions. Each is a detail the charter leaves to this document, decided in its spirit, and
none contradicts a charter decision.

1. **`derive_admission(cfg, host)` and `ram_required()`** — the charter fixes the four semaphore
   families and their config keys but not how they are derived from a machine. This document derives
   them from `os.process_cpu_count()` (not `cpu_count()`, so a cgroup or affinity mask is respected)
   and makes the RAM check a **refusal** naming `[drivers] max_workers` rather than a silent clamp,
   with the per-class arithmetic written out.
2. **`HostFacts`** — the preflight machine measurement, recorded in the run manifest so a
   performance number is attributable to a machine.
3. **The `Outcome` enum (§1.3) and its → `work.status` transition table (§1.2)**, including the rule
   that `DEFERRED_BUDGET`, `CANCELLED` and a lease reap **decrement `attempts_total`**. The charter
   names `Outcome` four times and defines it nowhere: it fixes the six statuses and
   `attempts_total < 5`, and neither the outcomes nor the map from one onto the other. The
   naive mapping makes five interrupted runs permanently unclaim a document.
4. **`deferred_sweeper`** — the charter's claim predicate excludes `deferred`, while
   [05-ingest-and-routing.md](05-ingest-and-routing.md) §6.4 says a deferred row stays claimable.
   The sweeper is what makes both true, edge-triggered on budget release with a durable backoff.
5. **`stall_detector`** — a full claimable set with nothing admissible is the one shape hysteresis
   does not cover, and [15-observability.md](15-observability.md) §R2 documents the symptom
   ("nothing is red"). Ends the run at `partial` with an existing `Degradation.kind`.
6. **Priority assignment (§1.7)** — the charter says priority "is ACTUALLY ORDERED BY" and never
   says who writes it. Five bands, planner-assigned.
7. **`classify()`'s three tiers and its cooldown table** — the charter fixes the `FailureClass`
   vocabulary and the five-attempt stop; the structured-then-status-then-message ladder, the
   per-class first cooldowns, the unclassified 1 h default with a recorded `Diag`, the
   per-provider `RATE_LIMIT_COOLDOWN_MS` table, and the host-vs-driver `timeout` split that
   reconciles this document with [04-driver-system.md](04-driver-system.md) §6.3 are set here.
8. **Sequence scheduling (§2.3)** — the charter names "Sequence sessions" in `dispatch.py`'s
   one-line inventory and the terminology lock defines the concept; the four scheduling rules that
   stop a session being split, half-admitted, or silently re-priced on retry are this document's.
9. **`ServiceSpec` / `ServiceHandle` / `ServiceRegistry`** — named in the charter's module inventory
   with no shape. Defined here, with `gpu_group`, `vram_floor_mb` and `server_argv` as new config
   keys, surya's 600 s timeouts as real defaults, the `os.urandom` token rule, and the spawn
   port-race handling.
10. **`engine_sizing(vram_gb)`** — the VRAM-proportional derivation adopted from surya, plus the
    rules that omniweave **passes** these to the engine and never tunes it, does **not** ship
    surya's GPU-name table because `HostFacts` measures VRAM, and refuses when a Service's declared
    `vram_floor_mb` is unsatisfiable.
11. **Demand-driven Service residency (§3.7 step 4)** — `work.service` is a charter column with no
    stated reader. It is the residency signal, derived from the claimable set, which is what avoids
    DataFlow's resume-time GPU leak.
12. **The operator → `CacheLayer` map (§2.4) and `Operator.CACHE_LAYER`** — the charter fixes five
    layers and never says which operator uses which, so `with_cache` had no way to know what to
    probe.
13. **`CacheProbe` / `probe()`** — the batch cache-check that returns hits **plus** the outstanding
    work list plus per-unit verdicts. graphify's signature, typed.
14. **The size-bounded cache sweep (§4.7c)** — `[cache.max_bytes]` is a charter key and
    [07-store-and-retrieval.md](07-store-and-retrieval.md) §3.11 asserts that CAS is swept by it;
    the age sweep alone cannot enforce it, so the per-layer LRU query is specified here, along with
    the disk-full **run-level degrade** rather than a per-unit `RESOURCE_LIMIT`.
15. **`plan/1`, `plan_digest`, and the `blocked` block** — the charter says "there is no pipeline
    array" and names `ow graph plan`; this extends that to a full-pipeline projection with eleven
    mandatory stage keys, the `rule`/`why` requirement, and LDR's per-item-verdict-with-ETA
    aggregate that `ow queue status` shares.

Plus the shapes the charter names without defining, which this document defines and lists under
**New terms**: `Outcome`, `StepResult`, `StepMetrics`, `RunContext`, `Roots`, `Operator`,
`BudgetLedger`, `Dep`/`DepKind`, `CancelToken`, `Clock`, `Limits`, `WorkRow`, `WorkSpec`.

## Open questions

Charter-deferred numbers this document rests on, restated only where a section is unbuildable
without them, plus the gaps found while writing.

**F7 — the server-coalescing speedup is unmeasured.** Every GPU-hour figure in §3.6 is a 1.5x-4x
band, and §3.4's `refill_target` cannot be tuned without it. It is also what makes the
`wall_ms_p50` in §6.3's plan a labelled band rather than a number. Closed by `ow bench service`:
2,000 pages through one engine at `max_batch` in `{1,4,8,16}` crossed with `batch_wait_ms` in
`{0,5,25}`, reporting throughput and `queue_p95_ms`. Pre-committed fallback: under 2x, raise
`max_batch` and reconsider the per-part `wall_ms_hard`.

**F8 — is 0.5 ms/unit of scheduler overhead achievable at `synchronous = NORMAL`, and what is the
p99?** Nothing in the mined collection measures a per-unit transactional scheduler. Closed by
`ow bench scheduler`: 1M synthetic units with a no-op operator on NVMe, a spinning disk and SMB,
reporting p50/p95/p99 of claim, commit and total. It also reports the `cache_index`-rows-per-`done`-
row ratio that §1.5's ~410,000 estimate assumes. Pre-committed fallback: if p95 exceeds 1 ms, group
commit widens from zero-derived-row transitions to same-operator batches — which weakens I20 for the
case it protects, and is a trade to make **with a number in hand**.

**F37 — Service residency.** `keep_alive_s = 300` is an interactive default behind which a resident
7B engine holds 20-40 GB of VRAM after `ow ingest` exits. Closed by measuring residency on a 24 GB
card. Pre-committed fallback, with surya's own `SURYA_INFERENCE_KEEP_ALIVE = False` as precedent:
`keep_alive_s` drops to **0** for `trigger` in `{cli, hook}` and stays 300 for `watch`.

**F26 — should the cache key include a lockfile digest?** §4.2 excludes it and uses the per-driver
`[deps] pins` digest for `free` only. Closed by measuring output drift across one pdfium minor over a
500-document fixture. Including the lockfile is *correct* and invalidates the whole free tier on
every unrelated dependency bump, which is why it is excluded until the drift is known.

**F6 — the p95 of `tokens_out` for a page VLM.** §7.3's reserve-the-p95-ceiling model rests on it and
the only published anchors are 3.4x apart.

**F29 — a sub-page commit boundary.** One page holding millions of blocks is still one transaction: a
4M-cell sheet is a multi-GB WAL and a multi-minute commit that **will** trip
`loop_lag_max_ms = 250`, and the WAL valve cannot help mid-transaction because its release condition
is a full backfill. Generation staging fixed the 5,000-*page* case; this residue is narrower and
real. Until measured, the answer is `MAX_BLOCKS_PER_DOC` plus a `RESOURCE_LIMIT` refusal naming the
knob.

**New — the interrupted-run accounting gap.** §8.3 states that a hosted provider bills for tokens
generated after we stop listening, and that the reservation is released rather than committed, so an
interrupted run's ledger under-counts by up to the in-flight parts' actual spend.
`interrupted_inflight` records the count but not the amount. **What closes it:** whether any provider
exposes usage for an abandoned request — some do, on a separate usage endpoint. If one does,
`with_budget` gains a post-hoc reconciliation step for `CANCELLED` rows; if none does, the manifest
must say "under-counts by at most N in-flight parts" in those words rather than presenting a total as
if it were complete.

**New — `op.cluster`'s spend cannot be capped by the durable ledger.** §7.6 works the problem
through: `route_spend.decision_id` and `budget_reservation.decision_id` are both `NOT NULL`, and an
`op.*` row's `decision_id` is NULL by CHECK, so the one non-free core-only step has no reservation
and no spend row. The pre-committed answer — `class_sem` admission, `work.cost_micros` accounting,
and `manifest.cost.op_micros` beside `billed_micros` — keeps every number visible and leaves exactly
one hole: a `run`-scoped `gpu_ms` cap does not bind `op.cluster`. **What closes it:** measuring
`op.cluster`'s GPU share of a reference ingest. If it is material, the smallest correct fix is to
make `budget_reservation.decision_id` nullable with a CHECK pairing it to `work.operator LIKE 'op.%'`
— the same pattern the `work` table already uses — which is a charter DDL amendment and is therefore
recorded here rather than done.

**New — `service_observation.gpu_ms` has no per-request attribution.** Coalescing means one forward
pass serves requests from several units, so per-unit `gpu_ms` is an apportionment, not a measurement
(§3.9). The Sequence apportionment rule — split by token share — is the analogue and is what §7.5's
second self-check would need. **What closes it:** deciding whether per-unit `gpu_ms` is worth an
apportionment at all, or whether `local_compute` pricing should be per-Service rather than per-unit.
Until then, `gpu_ms` on a `route_spend` row for a coalesced call is apportioned by token share and
the manifest labels it `apportioned`.

**New — a rename inside the scope re-bills that document's billed parse.** §4.8's last row states
it: `content.salt` is the walked path, so a `git mv` is a cache miss. The salt is in the key because
graphify's symlink-aliasing case requires it, and the blast radius is one unit rather than a corpus,
so it is not worth designing around blind. **What closes it:** instrumenting rename frequency on a
real corpus over a month (`unit` rows going `out_of_scope` while a new `unit_uri` appears with an
identical `content_sha256` is exactly detectable). Pre-committed fallback if it is material: store a
second column `key_nosalt` beside `cache_key`, indexed, computed from the same recipe with the
`content.salt` group omitted; on a `miss`, look up `key_nosalt` and return `hit_alias` when the
entry's `content.digest`, `producer.*` and `config.*` all match. That is a `cache_index` DDL
amendment and a seventh `CacheVerdict` member, so it is recorded here and not decided.

**New — `[watch] backend = "auto"` is untested on two of nine cells.** codegraph's darwin choice
(one recursive native watch) and graphify's (`PollingObserver`, because FSEvents can miss rapid saves
in some editors) are opposite, and both are justified. **What closes it:** an fs-event fidelity
fixture — 200 rapid saves through three editors on darwin — measuring missed events per backend.
Until it runs, `auto` selects the recursive native watch on darwin and Windows and per-directory
inotify on Linux, and `[watch] backend` is an operator override with the platform reason printed by
`ow doctor --runtime`.

**Charter/lock gap, flagged as instructed.** `terminology.md` §2 has rows for `Admission`,
`StepResult`, `Spend`, `PriceBook`, `Operator`, `CacheLayer`, `CacheVerdict` and `Batch`, but **not**
for `Outcome`, `StepMetrics`, `RunContext`, `Roots`, `CancelToken`, `Clock`, `WorkRow`, `WorkSpec`,
`Reservation`, `BudgetLedger`, `Dep`, `DepKind`, `Limits`, `Estimate`, `ServiceSpec`,
`ServiceHandle`, `ServiceRegistry`, `UnitRef`, `ArtifactRef` or `classify()` — every one of which
the charter's own §D6 module inventory names. The lock's own CI check 1 ("every `class` name
appearing in `charter.md` or in any plan document has a row in §2") therefore fails against the
charter as written. This document follows the charter's names and lists the missing ones under
**New terms** for merging; a reviewer should treat that list as lock additions, not as new concepts.

**Closed — the charter's `RunContext` placement.** The D6 module inventory and §D6's decision text
were read as a contradiction while the resolution sat here as an aside. It is normative text in
§1.3 now, where the type is printed: both charter sentences hold as written, neither is superseded,
and no erratum is owed.

## New terms

Terms this document coins, plus the charter-named types absent from `terminology.md` §2 that it
defines. All are proposed for the lock.

| Term | Kind | Definition |
|---|---|---|
| `BudgetLedger` | type | The durable ledger over `budget_reservation`: `reserve` / `commit` / `release` / `headroom` / `headroom_units`. One row per `(reservation, dim)`. Headroom is computed **in SQL**, never cached in an attribute. |
| `CacheProbe` | type | What one batch cache-check returns: the decoded hits with their replayed `Spend`, the **outstanding** `UnitRef` list in order, a per-unit `CacheVerdict` map, the `hit_legacy` count and `would_have_been_micros` at the current `PriceBook`. One indexed query per Batch; the caller never issues N lookups. |
| `CancelToken` | type | One object per **cancellation scope** in `omniweave_core.operator` — a run on the ingest path, one call on the serve path — checked at every loop top. A one-way monotone latch carrying its `Cancellation`, so the four causes stay distinguishable at the shutdown boundary. It **propagates** cancellation; `claimed_gen` is what makes a late result safe. Two mechanisms, not one. Printed in §1.3. |
| `CancelReason` | enum | The four causes a `CancelToken` distinguishes: `interrupt` (the first Ctrl-C), `deadline` (a request token's own deadline), `shed` (`stall_detector` withdrawing a run) and `client` (an MCP or SDK caller). **Supersession is not a member** — it is the other mechanism (§8.1), and a superseded worker has no token to consult. |
| `Cancellation` | type | The latched cause: a `CancelReason`, `at_mono_ns` from the injected `Clock` — which is where `[runtime] shutdown_grace_ms` is measured from — and an unparsed `detail`. Frozen, because the value is a value; the token is the latch. |
| `classify()` | fn | The pure function `(FailureClass \| None, exception, provider, status_code) -> Failure`. Three tiers: the driver's structured class, then the HTTP status table, then the message table **with a recorded `Diag`**. `provider` selects the rate-limit cooldown; `Failure.source ∈ {driver, host}` is what splits `timeout` into a transient and a permanent verdict. |
| `Clock` | proto | `monotonic_ns()` plus `wall_ns()`, **injected** on `RunContext`, never ambient. What makes the debounce and generation invariants testable without an operating system. |
| `deferred_sweeper` | fn | The Supervisor task that returns `deferred` rows to `pending` when headroom reappears. Edge-triggered on budget release, backstopped at `[runtime] deferred_sweep_ms`, gated by the sibling-reservation clause, with a durable exponential backoff in `retry_after`. It is why "a deferred row stays claimable" is true while the claim predicate does not mention `deferred`. |
| `Dep` / `DepKind` | type / enum | One recorded cross-unit input and its closed kind `unit \| part \| name \| cohort \| policy \| service_model`. Reverse-indexed on `(kind, key)`, so invalidation is one query and never a sweep. |
| `derive_admission()` | fn | The preflight function mapping `(Config, HostFacts)` to `Admission`. `os.process_cpu_count()`, not `cpu_count()`. Every semaphore is an `asyncio.BoundedSemaphore`; the RAM check is a **refusal** naming `[drivers] max_workers`, never a silent clamp. |
| `engine_sizing()` | fn | The VRAM-proportional derivation of `(max_batched_tokens, max_num_seqs)` from a 24 GB baseline. omniweave **passes** these to a model server and never tunes it; a `vram_floor_mb` it cannot meet is a resolve-time refusal. |
| `Estimate` | type | A non-free operator's pre-flight prediction of `Spend` for one unit, at the **p95 ceiling**. The input to `admit()`; checked by `ow drivers check --estimates`. |
| `gpu_group` | cfg | `[services.<name>] gpu_group`. Names the VRAM budget a Service draws from; `cuda:<n>` pins a device and sets `CUDA_VISIBLE_DEVICES` for the spawned child. Two Services in one group are resident together only if their declared `vram_floor_mb` both fit; otherwise the second spawn evicts the group's LRU with a recorded `Degradation`. |
| `HostFacts` | type | The machine measured once at preflight — `cpus`, `ram_bytes`, `free_disk_bytes(roots.cache)`, `gpus` as `(name, vram_bytes)` in device order, `is_container` — and recorded in the run manifest, so a performance number is attributable to a machine. |
| `Limits` | type | The resolved `MAX_*` ceilings for this run — `effective = min(tenant_cap, declared, HOST_MAX)` — carried on `RunContext` so no site reads a constant directly. |
| `Operator` | proto | The core-internal scheduled-step contract: `OPERATOR`, `OP_VERSION`, `COST_CLASS`, `GRANULARITY`, `CACHE_LAYER`, `plan()`, `run()`, `is_valid_nonempty()`. The Protocol is in `omniweave_core/operator.py`; the implementations are in `omniweave/run/operators/`, one per Port, plus the five `op.<name>` steps. **Nobody outside core writes one.** |
| `Outcome` | enum | The nine-value work outcome: `ok`, `ok_partial`, `skipped_cached`, `skipped_unchanged`, `failed_transient`, `failed_permanent`, `deferred_budget`, `cancelled`, `held`. There is **no empty success**; `deferred_budget` is **not** a failure; and `deferred_budget`, `cancelled` and `held` are the three that do not consume an attempt. |
| Plan document | concept | The canonical JSON projection of (catalog x policy x pass registry x scope x store state) at `plan/1`, digested as `plan_digest`. **Derived, never authored, and never accepted as input**: one definition, three front-ends (code, a visual builder, an agent), and the authoring surface is the three registries. Eleven mandatory stage keys; every routed stage carries its `rule` and its `why`; `blocked` carries the per-reason counts and ETAs. |
| `plan/1` | proto | The Plan document's wire name and `schema` value. |
| `plan_digest` | concept | `sha256_canonical()` over the Plan document with its own `plan_digest` key and its `estimate` block removed. Stable across two runs of the same scope over the same store, so a plan diff is meaningful. |
| `probe()` | fn | The `CacheProbe` constructor in `omniweave_core.cache`, taking the layer from the operator's `CACHE_LAYER`. Distinct from a **Capability probe**, which proves a driver capability works; `probe()` reads the cache and nothing else. |
| `RATE_LIMIT_COOLDOWN_MS` | const | The per-provider rate-limit cooldown table in `omniweave_core.work`, keyed on `Spend.provider` with a `default` of 3,600,000 ms and overridable by `[providers.<tag>] rate_limit_cooldown_ms`. A `Retry-After` header always wins. LDR's per-domain table, generalised. |
| `Reservation` | type | One `budget_reservation` row's handle, with a `reservation_id` content-addressed over `(work_id, decision_id, attempt, dim)`, so a retried reserve is idempotent and each capped dimension is a distinct row. |
| `Roots` | type | `source` / `output` / `cache`, always separate; a `cache` inside `source` is a startup error. The cache salt is relative to `source`, which is why `roots.source` is `operational`. |
| `RunContext` | type | The **operator's** only channel to the outside: identity, six digests, `Limits`, `Admission`, `ServiceRegistry`, `BudgetLedger`, `CancelToken`, `Clock`, `TraceSink`, `service()`. A frozen value object with no store handle, so core defines it and stays asyncio-free. **Never handed to a driver** — that is `DriverIO`. |
| `ServiceHandle` | type | What `ctx.service(name)` and `DriverIO.service(name)` return: a base URL, a 32-byte `os.urandom` token, the verified model id and revision, capacity, a `traceparent` and a deadline. Not a client library, which is why `omniweave-llm` needs neither torch nor an SDK. |
| `ServiceRegistry` | type | The per-run Service table on `RunContext`: `live()`, `handle()`, `evict()`, `observe()`. **Blocking** attach-or-spawn; the async part is the Supervisor's `service_refill` task. Never a module global and never a process singleton. |
| `ServiceSpec` | type | One `[services.<name>]` block, frozen: model id and exact revision (both **semantic**), endpoint, autostart, capacity, `batch_wait_ms`, `max_batch`, `keep_alive_s`, two 600 s timeouts, `vram_floor_mb`, `server_argv` and `gpu_group`. |
| `stall_detector` | fn | The Supervisor task that ends a run at `status='partial'` when the claimable set is non-empty, nothing is claimed, nothing has committed for two `[runtime] stall_poll_ms` cycles and the sweeper returned nothing. The futility latch applied to the whole loop: a scheduler that cannot make progress says so instead of spinning. |
| `StepMetrics` | type | The runner-owned metric bundle on a `StepResult`: `queued_ms` **always** separate from `ran_ms`, the physical `Spend`, runner-priced `micros`, `was_cache_hit`, `rows_written`, `peak_rss_bytes`. |
| `unit_salt()` | fn | The `content.salt` input to `cache_key()`: for `fs`, the **walked** path relative to `roots.source`, POSIX-separated; for any other connector, `'<connector>/<locator>'`. Never an absolute path, so a cache entry is portable across checkouts, and never `realpath`'s output, so two symlink aliases stay two units. |
| `WorkRow` | type | One claimed `work` row as returned by `Store.claim()`, carrying `claimed_gen` — which is what the commit predicate compares, and therefore what makes a superseded result write nothing. |
| `WorkSpec` | type | What `Operator.plan()` emits: the tuple from which a `work` row's identity, `cache_key`, `dispatch_key` and `priority` are derived. Constructed through `signature.bind().apply_defaults()`, so it is complete, self-describing and hashable — which is what makes `plan_digest` stable. |

**Supporting type names used in the signatures above**, listed so the lock's name check has a row
for each and a reviewer can see that none of them is a new *concept*:

| Term | Kind | Definition |
|---|---|---|
| `AimdState` | type | The per-`(driver_id, config_digest)` batch-adaptation state: the current batch, the card ceiling and the clean streak. |
| `BatchEvent` | enum | What `adapt_batch()` reacts to: `clean`, `resource_limit`, `worker_died`, `driver_crashed`. A projection of `FailureClass`, not a second taxonomy. |
| `CacheEntry` | type | One row `cache.put()` writes: layer, key, the blob, the `Spend`, the `partial` bit and the `(unit_uri, unit_part)` it belongs to. |
| `CacheHit` | type | One decoded cache hit inside a `CacheProbe`: the artefact ref, the replayed `Spend`, the re-priced `micros` and the `CacheVerdict` (`hit` or `hit_legacy`). |
| `DerivedRows` | type | The batch of L2/L3 rows one `Store.complete()` call commits, so the transaction boundary is a parameter rather than a convention. |
| `Failure` | type | `classify()`'s output: a `FailureClass`, a `source ∈ {driver, host}`, a verdict (`transient` or `permanent`), a first cooldown in ms and an optional `adapt_batch` event. |
| `PendingEntry` | type | One watcher pending-set entry: `first_seen_gen` and `last_seen_gen`. Eviction compares `last_seen_gen` against the run generation, which is what makes I3 provable. The set is in-memory by design — it is a coalescing buffer, not a queue. |
| `UnitKey` | type | `(unit_uri, unit_part)` — the pair that keys the pending set, the cache write allowlist and the per-part retry semaphore. Not a `UnitRef`, which additionally carries `content_sha256`, the connector and the walked path. |
