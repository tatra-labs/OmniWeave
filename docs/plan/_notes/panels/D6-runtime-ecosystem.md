# D6-runtime — Execution runtime: scheduling, concurrency, caching, incremental refresh, observability

*Panel proposal — the ecosystem and operator advocate.*

## Headline

**The runtime is a product surface, not plumbing: a single-threaded `asyncio` supervisor that owns no
CPU, drains a bounded *wave* of `work` rows at a time so a 100k-document ingest never plans more than
it can hold, dispatches every unit through D3's `subproc` driver host in `dispatch_key`-coherent
batches, keeps GPUs fed by letting the *model server* coalesce across documents while the host only
does attach-or-spawn with an authenticated sentinel, memoises through one `cache_index` table that
prices five layers on one key, and emits one stdlib-only versioned NDJSON event stream from which
`ow top`, `ow why`, `ow cost`, `ow replay` and an out-of-core `omniweave-otel` bridge are all
derived — so `omniweave-core` never imports a telemetry SDK, a third-party driver gets fleet-grade
batching and tracing for free, and every failure message ends in the command that clears it.**

The one substantive correction I make to the reference design in `mine-runtime.md` §7.5: **the whole
effective run config must not enter every cache key.** Splitting it into a CI-classified
`SEMANTIC`/`OPERATIONAL` projection is the difference between "raising `max_inflight` re-bills your
corpus" and a cache an operator can reason about.

---

## Design

### 1. What runs the work: one supervisor, no CPU, no `multiprocessing`

Three substrates were available and the rulings already eliminate two of the three combinations.

- **The supervisor is one `asyncio` event loop in one process** (`omniweave/run/supervisor.py`, in
  the `omniweave` distribution — *not* in `omniweave-core`, which stays on the per-turn import path
  under D1's 80 ms budget). It claims, admits, dispatches, reaps leases, prices, emits events, and
  writes the manifest. It executes **no driver code and no document bytes**. Its steady-state RSS
  target is under 250 MB at any corpus size, and that is a nightly CI assertion (gate G21), not an
  aspiration.
- **All third-party driver execution is out of process**, through D3's `subproc` host: one long-lived
  worker per `(driver_id, config_digest)`, length-prefixed frames over a 0600 unix socket or an
  owner-only named pipe. omniweave ships **no process pool of its own**. That is deliberate: a
  `multiprocessing` pool on top of the driver host would be a second worker lifecycle to debug on
  three OSes, and `fork` is unsafe with CUDA and with a live SQLite handle. One mechanism, three OSes.
- **`inproc` drivers run on a bounded `ThreadPoolExecutor`** sized `drivers.max_workers.free`
  (default 4). This is safe only because D3 already restricts `inproc` to first-party/vendored, free,
  GPU-less, network-less drivers named in `[drivers.inproc]`, and because the one that matters
  (`omniweave-office` over `firecrawl-anydoc`) releases the GIL for the decode via `py.detach`.
  D1 records the honest caveat — the *eager Python marshal* is not covered by `py.detach`, so GIL
  hold time scales with document size. The runtime does not assume; it **measures**: every inproc call
  records `queued_ms` separately from `ran_ms` (jcodemunch §5.3 — "a contended lock and slow work are
  indistinguishable from the outside"), and when `queued_ms / ran_ms` exceeds 1.0 over a wave the
  supervisor emits `degrade{kind:"inproc_saturation"}` naming `ow config set drivers.inproc = []`,
  which moves the driver to `subproc` with no code change.
- **SQLite runs on one dedicated store thread.** Writes serialise anyway; a single writer thread keeps
  `busy_timeout` contention purely cross-process and lets the supervisor batch 64 row transitions per
  transaction. Read-only consumers (`ow top`, hooks, the MCP server) use jcodemunch's
  `connect_readonly` ladder verbatim, which D1 already mandates.

Backpressure is a **six-step ladder that never drops work**, only pauses the producer at a safe
boundary (mine-runtime §7.3.5, and the WAL valve's correct terminal mode): the wave gate, the
per-`CostClass` admission semaphore, the service's own queue, store write-batch halving on repeated
`SQLITE_BUSY`, a disk-headroom pause, and per-worker `RLIMIT_AS`/`RLIMIT_DATA` with batch halving on
`OOM`.

### 2. The job model: unit → wave → work row → batch

The failure this is designed against is the one no repo in `_collections/` avoids: **planning the
whole corpus before doing any of it.** graphrag's `_copy_previous_output` physically copies the whole
index per update; DataFlow compiles the full op graph up front and its refcount leaks GPU memory on
resume; LDR's `get_pending_tasks()` hands the same 50 rows to two workers.

Five nouns, and only five:

| noun | grain | durable? | who creates it |
|---|---|---|---|
| **run** | one `ow` invocation; one `run_id`, one `generation` (a monotonic int, never a clock) | `run` row + `runs/<run_id>.json` written incrementally | the CLI |
| **unit** | one source document; the corpus roster, streamed, one row | `unit` table | discovery / a connector cursor |
| **wave** | ≤ `run.wave_units` (512) admitted units, ≤ `run.wave_parts_cap` (8192) parts | `wave` row | the scheduler |
| **work row** | one `(unit_uri, unit_part, operator, op_version)` — identical to D4's decision grain | `work` table | wave expansion |
| **batch** | claimed rows sharing `dispatch_key = sha1(driver‖config_digest‖isolation)[:16]` | **not durable — invisible to the `work` table** (D3) | the dispatcher |

A **wave** is the whole answer to "resumable, observable, and not OOM". Roster discovery streams into
`unit` rows (≈220 B each: 100k documents is 22 MB, not a Python list). Work rows are materialised only
for the units in the current wave, so the claimable set is bounded by `max_queue_depth` rather than by
corpus size, index churn on the `work` table stays inside the codegraph bulk-load window, and the
first document is parsed in seconds instead of after a 40-minute plan.

A unit whose part count exceeds `run.wave_parts_cap` is not special-cased away: it gets its own wave
and is scheduled in ordered **part windows** of `run.part_window` (256). The unit is not `settled`
until every window is. This is `mine-runtime.md` §7.12's open question #1 answered on the scheduling
axis, with D4 having already answered it on the decision axis.

Two hosts expanding the same wave is **not a race that needs a lock**: expansion is `INSERT OR IGNORE`
against `work_identity`, so both produce the same rows, and the claim protocol is the only
authoritative arbiter. That is what keeps T1→T2→T3 free of a wrapper tax.

**Checkpoint and resume are unchanged from settled law**: there is no checkpoint file, the claimable
set *is* the checkpoint, `ow resume` is an alias for `ow ingest`, and resume re-derives the plan from
current inputs and current config and subtracts what is done. What I add is that the work table stays
small enough for that COUNT to be instant, and that **`done` rows are swept** once their `cache_index`
row exists and their unit is `settled` — never while claimable or claimed (a `BEFORE DELETE` trigger
enforces it). The durable record of "this was derived" is the cache index, not the queue.

### 3. Batching, and keeping a GPU fed

D3 already ruled that one `INVOKE` carries up to `batch_max_units` and one `RESULT` comes back per
unit, so **the batch is invisible to the `work` table**. The runtime's contribution is *how the batch
is assembled* and *where coalescing actually happens*.

Assembly: the claim query orders by `(status, retry_after, priority DESC, dispatch_key, id)` — the
`dispatch_key` in the composite index is what makes a batch-coherent claim one indexed scan rather
than a group-by. Only admitted units enter a batch (`admit()` runs before assembly), so a batch never
straddles a budget boundary. On `OOM`/`WORKER_DIED` the effective `batch_max_units` for that
`(driver, config_digest)` halves for the rest of the run, floor 1, with a `degradations[]` entry —
mine-runtime §7.3.2's rule, made stateful. On a crash, D3's retry-once-at-`batch = 1` localises the
poison unit.

**Coalescing across documents lives in the model server, not in omniweave**, and this is the single
biggest ergonomics win available. surya states the rationale in `surya/settings.py:173-178` — *"there's
no benefit to more than one layout model on a host, and N in-process copies thrash the CPU/GPU"* — and
implements it in `surya/common/batch_service/` with a `batch_wait_ms` window and a `max_batch` ceiling
*across all clients*. vLLM does the same natively through continuous batching. So omniweave's host does
attach-or-spawn, model-id verification, capacity accounting and residency; the server does the
batching. The consequence for adoption is decisive: **a driver an outside contributor writes in an
afternoon, which submits one page per call, still saturates the GPU**, because four `local_compute`
workers × `batch_max_units = 8` present a steady 32-deep queue to a server whose window is 25 ms.

`Service` is D3's word for this and it is explicitly *not* a Port: named, host-managed, never routed.
The runtime owns the pool:

- **One service per `(name, model_id, options_digest)` per host** — the "one inference manager, many
  heads" property. `parse.vlm.page` and `derive.table.vlm` both call `io.service("vlm")` and share one
  engine.
- **attach-or-spawn is surya's ladder, taken whole** (`surya/inference/backends/spawn.py`): pinned
  external URL → probe `/health` → `GET /v1/models` and **refuse to attach on a model-id mismatch** →
  unlocked sentinel fast-path that never mutates the sentinel → `FileLock` → re-check inside the lock →
  spawn detached → write sentinel → `atexit` **only in the spawning process**. The comment explaining
  why the unlocked path must not delete an unhealthy sentinel is load-bearing and is reproduced in
  our source. Failure diagnostics include the server's own log tail, which is what makes a spawned
  server debuggable at all.
- **Authenticated.** surya ships `VLLM_API_KEY = "EMPTY"`; LEANN ships unauthenticated ZMQ on a dynamic
  loopback port, which D1 names as the anti-pattern. omniweave writes a 32-byte token into the 0600
  sentinel, passes it to the server (`--api-key`) and to the driver in `HELLO.services`, and a request
  without it is 401. Disabling this requires `allow_unauthenticated = true` and prints the risk.
- **Residency by refcount over *surviving* work, never over the compiled plan.** DataFlow primes
  `llm_serving_counter` at compile time and decrements only inside the executed loop, so
  `resume_step > 0` leaks GPU memory forever (`dataflow/pipeline/Pipeline.py`, `_compiled_forward`).
  omniweave increments on first acquisition within a wave and evicts at `services.<n>.keep_alive_s`
  idle; `ow services` shows residency, model id, capacity, cold-start ms and queue percentiles.
- **Never spawned speculatively.** A born-digital corpus starts no GPU server — D4's demand plan
  guarantees no `local_compute` signal is even computed, and X12 asserts zero `service_observation`
  rows on that fixture.

### 4. The cache: five layers, one key, one table, one bill

The framework already fixes the key's *shape* (`omniweave_core.cache`: three groups, two invalidation
tiers). What is missing, and what every repo in the collection is missing, is that the layers share
**one index, one accounting path and one GC**, so an operator can answer "what is my LLM cache costing
me in disk, and what would a driver upgrade re-bill?" — a question nothing in `_collections/` can
answer today.

Five layers on `cache_index`: `bytes` (acquired source and blobs, CAS), `parse` (a locator into the
`.owstore`, because D2 makes the store canonical and a second parse representation is forbidden),
`derive`, `llm`, `embed`, plus `render` for page rasters, which D2 already defines as an evictable
derived cache keyed by DPI and renderer. D4's `route_signal` is its own table by D4's ruling and is
swept per `signal_version`.

The key, honouring D3's versioning rule exactly:

```
key = sha256_canonical({
  "k": <cache.recipe>, "layer": …,
  "content":  {"digest": unit.content_digest, "salt": unit_salt(unit, roots), "part": unit.part or ""},
  "producer": {"driver": driver_id, "schema_version": card.schema_version,
               "code_fingerprint": <only if cost.class == "free">,
               "deps_digest":      <only if cost.class == "free">},
  "config":   {"driver": candidate.config_digest, "run": SEMANTIC_PROJECTION(effective_config)},
})
```

Three deliberate decisions here.

**(a) `code_fingerprint` and `deps_digest` enter the key only for `free`.** D3 ruled that
`schema_version` *alone* enters the cache key "so a bug-fix release does not re-bill a `billed_api`
cache"; mine-runtime §7.5.2 wants `v{schema_version}-c{code_fingerprint}` namespacing. These reconcile
exactly along the two-tier philosophy — a cheap miss is invalidated aggressively by producer identity,
a billable miss only by evidence the answer changed — and D3 already settled the twin question for
`[deps] pins` the same way. This also closes `mine-runtime.md` §7.12 open question #4.

**(b) The run-config contribution is a projection, not the whole digest.** This is my one substantive
correction to the reference design. mine-runtime §7.5 puts `ctx.config_digest` — the digest of the
*entire* effective config — in every cache key. Under that rule, raising `budget.max_inflight` from 4
to 8, or turning on an event sink, invalidates every `billed_api` entry in the corpus. That is
graphrag's permanent-silent-cache-miss failure wearing a different costume, and it is the kind of thing
an operator discovers by reading a bill. So `tools/config_axes.toml` classifies every key as `SEMANTIC`
or `OPERATIONAL`, gate **G17** fails CI on an unclassified key, an unclassified key defaults to
`SEMANTIC` (fail expensive, never wrong), and only the semantic projection enters keys and sets the
full-scan latch. `ow cache explain <uri> --op parse` prints the three groups verbatim and diffs them
against the previous run, so a miss is never mysterious.

**(c) A recipe bump namespaces; it never deletes.** `cache_index.recipe` is a column, old rows stay
readable, `free` namespaces are swept and `billed_api` never is (graphify's rule: two hosts with
different prompts sharing one output dir must not each delete the other's entries and re-bill on every
alternation). **`ow cache migrate --to-recipe 2 --dry-run` prints the micros a bump would re-bill
before you `pip install -U`.** That number is the upgrade path.

Read policy is graphify's six clauses with the one improvement mine-runtime already identifies — a
corrupt entry is **overwritten on the next success**, so it self-heals without a flag. Writes carry
graphify's allowlist (`cache.put(entries, allowed_units=frozenset(batch_units))`): the only
cache-poisoning control in the collection, and the reason an LLM enrichment step cannot replace the
parse record of a document it was never given.

### 5. Incremental invalidation: cohorts by default, witnesses by opt-in

codegraph measured **4.3% of distinct edges wrong, in both directions, silently, forever until a full
rebuild** without its convergence pass. That number is why this section exists, and why the CI gate
below is the most important one in this decision.

D3 forbids a driver from touching the store, the cache or the work table — which is right, and which
means the runtime cannot observe what a cross-document derivation actually read. So:

- **Default: the cohort.** A `corpus`-granularity operator's unit is a *cohort* — a named, digest-
  addressed member set. `cohort.member_digest` is a merkle over `(unit_uri, unit_part, content_digest)`
  in sorted order, and that digest is the operator's content identity. Any member change changes the
  digest, misses the cache, and re-derives the whole cohort. **Correct by construction, no dependency
  table, and expensive.**
- **Opt-in: the witness.** Core adds one closed artifact kind, `witness_set`. A `derive` driver that
  declares `produces = [..., "witness_set"]` returns, per produced item, the foreign
  `(unit_uri, unit_part, token)` tuples it consulted; the runner writes them to the `witness` table.
  On the next run, `resurrect` re-derives only items whose witness set intersects the change delta.
  This is codegraph's `definitionDelta` → `resurrectStaleResolutionEdges` mechanism generalised, with
  the dependency record supplied by the driver rather than reverse-engineered by the host.
- **The gate that makes either believable: G18, incremental-then-full equivalence.** Run incremental,
  then full, on the 200-document fixture corpus, and diff every table. Runs on merge, ~8 minutes.
  Without it, incremental mode is quietly wrong and nobody finds out for a year.
- **X17, and I am not softening it:** a `corpus`-granularity driver whose class is `billed_api` and
  which does not produce `witness_set` is **refused at resolve time** with
  `CORPUS_REBILL_UNBOUNDED`, unless `drivers.allow_full_cohort_rebill = true`. Correctness by default,
  efficiency opt-in, and the cost of not opting in is a refusal an operator can read rather than an
  invoice they cannot.

Ownership and loss are settled law and are carried verbatim: every derived row carries
`origin_operator`; an operator's re-run replaces only rows it owns; the attribution guard is per-unit
and computed from `work`, with the starred clause — **a unit whose derivation failed this run may
never account for its own loss** — enforced, because a failed operator is the most likely cause of the
loss and must never be its excuse. Overrides are named per check: `--allow-unexplained-loss`,
`--allow-rebill`, `--accept-partial`, `--ignore-cache`. There is no `--force`.

### 6. Cost: physical units in, one price book, two ledgers out

D4 owns `Spend`, `PriceBook` and `route_spend`, and its central rule — a driver states physical
resource units and **never dollars** — is the right one. The runtime's job is the accounting the
router does not do:

- **Every `cache_index` row stores the `Spend` that produced it**, and a hit replays that `Spend`
  flagged `was_cache_hit = true`, priced with the *current* `PriceBook`. That is the only way to
  compute `would_have_been_micros_if_uncached` when 90% of calls are hits (graphrag §2.5), and it is
  the only number that justifies the cache's existence to a finance team.
- **Two rollups, both first-class.** Per-document (`ow cost --by document`) answers "what did this
  contract cost to ingest"; per-corpus with a slice axis (`--by driver|provider|slice --since 7d`)
  answers "where is the money going". Both are views over `route_spend ⋈ work ⋈ unit`, exported as
  `table|json|csv`.
- **Reconciliation is the honesty mechanism.** D4's `route lint --estimates` fails the build when a
  driver's estimate is more than 2× off its 7-day measured median. The runtime supplies the
  measurement, and `ow doctor --runtime` prints the current drift per driver so it is visible before
  CI fails.
- **A denial is `DEFERRED_BUDGET`, not a failure.** The row stays claimable, the manifest reports the
  deferral, and for `billed_api` it surfaces as a pending-cost record requiring confirmation. Without a
  distinct outcome, budget exhaustion looks like breakage — and an operator who cannot tell those apart
  disables the budget.

### 7. Observability: one event stream, everything else derived

**Zero of the 22 repositories in `_collections/` emit OpenTelemetry.** `grep -rl "get_tracer|opentelemetry-sdk|opentelemetry-api|@opentelemetry/"` across the collection returns nothing; the single hit,
`jcodemunch-mcp/src/jcodemunch_mcp/runtime/otel.py`, is a *parser* for OTLP JSON files produced by
someone else's collector. The state of the art here is codegraph's `[phase-timing]` lines on stderr and
graphify's `warnings.warn(RuntimeWarning)`, which is filterable, unstructured and invisible under JSON
logging. So there is no incumbent to copy and a clear space to win.

The design has one rule: **the event schema is the contract; OTel is a sink.**

- `omniweave_core.events` is stdlib-only, roughly 200 lines. `Event` is a frozen dataclass with W3C-
  shaped ids (`tid` 16 bytes, `sid`/`psid` 8 bytes, hex) so the bridge is a mapping and not a second
  instrumentation pass. Cost: 24 bytes per event.
- The span hierarchy is **closed and six deep**: `run > wave > unit > part > attempt > call`. Every
  driver call is a `call` span carrying `driver`, `cache`, `service`, `spend`, `micros`, `queued_ms`,
  `ran_ms`, `peak_rss`.
- `kind` comes from a closed, append-only registry `events.toml`, and `schema/event-v1.json` is
  generated from the Python definitions, committed and byte-diff gated — gate **G19**, exactly the
  discipline D1 applies to its other schemas, and the fix for LEANN's hand-written `llms.txt` declaring
  two tools against a server that ships four.
- Sinks are pluggable via an `omniweave.sinks` entry point: `console` (TTY-aware), `ndjson`, `sqlite`
  (a bounded ring). **`omniweave-otel` is a separate distribution** that registers a sink translating
  events to OTel spans and metrics. `omniweave-core` never imports `opentelemetry`, D1's gates G1/G9/G10
  survive intact, and a production user still gets first-class traces. This is the whole argument for
  the event bus in one sentence: *a vendor SDK on the per-turn import path is a tax on every hook
  invocation, and a stable event stream costs nothing and serves more consumers.*
- **Timings are always on**, in the manifest, never behind an env var. codegraph burned three
  25-minute cycles before "is the valve even alive?" could be answered.

Four operator commands are the deliverable, not a nice-to-have:

- **`ow top`** — a live view over the read-only store and the NDJSON tail: queue depth by status,
  inflight by cost class, service utilisation and queue percentiles, cache hit rate, spend rate, ETA.
  It never attaches to the supervisor process. Nothing in the collection has this, and it is the single
  thing that makes a twelve-hour 100k ingest tolerable. `--plain` prints one line every ten seconds for
  CI logs.
- **`ow why <uri> [--part p41]`** — the highest-value command in the system. One screen: acquisition
  state and failure class, route decisions with `cause` and read set, the three cache-key groups with
  *which group differed from last run*, spend, retries with the next `retry_after`, and what it is
  currently waiting on. This answers "why is this document not in my index", which today requires
  reading source.
- **`ow cost`** and **`ow replay <run_id> --offline`** — replay re-executes from the cache with egress
  disabled; a missing key is a named failure, not a silent re-bill. It is how you prove a bug is in the
  driver and not in the runtime.

Freshness, degradations and the run manifest are settled law and are carried through unchanged:
freshness is derived from `work`-table state so every process agrees, a degraded subsystem is visible
in the product surface and not only in a log, and the manifest is written **incrementally** so a
`SIGKILL` at hour six leaves a parseable partial with `"outcome": "interrupted"`.

### 8. Determinism and replay

- `HELLO` carries `determinism: {seed, clock_ns}`, mirroring D1's `omniweave-target/1` envelope, so a
  driver that respects it produces byte-identical output across hosts.
- A driver whose card says `deterministic = true` is sampled at `run.verify_idempotence_rate`
  (default 0.01, deterministic `blake2b` selection per D4 R2, never RNG): re-run, diff
  `content_digest`, and a mismatch writes a `driver_observation` row and fails CI for first-party
  drivers.
- A driver whose card says `deterministic = false` is cached and **never re-derived for comparison**;
  it is scored instead through D4's free `agree.decode_vs_page` channel.
- Committed artifacts are byte-reproducible: sorted collections before serialisation, frozen float
  formatting, no wall clock in committed output (I17).

---

## Concrete shape

### Package layout (delta on D1's tree)

```
packages/omniweave-core/src/omniweave_core/
├── operator.py      OperatorABC · OperatorIdentity · StepResult · StepMetrics · Outcome · RunContext · Roots
├── cache.py         cache_key() · CacheIndex · six-clause read policy · allowlisted put · tiers
├── events.py        NEW · stdlib only · Event · emit() · Sink protocol · W3C ids · ~200 lines
├── frames.py        NEW · length-prefixed frame codec for D3's wire  (see CONFLICT C1)
├── budget.py        BudgetLedger · Reservation · Denied · headroom  (Spend/PriceBook are D4's)
├── modelserver.py   attach_or_spawn() · ServiceEndpoint · sentinel+filelock+model-id verify (surya shape)
├── store/sqlite.py  THE ONLY sqlite3.connect · pragmas · heal-on-open · WAL valve · connect_readonly
└── probe.py         capability probes, verdict cached (driver, version, host_fingerprint) 24 h  [D3]

packages/omniweave/src/omniweave/
└── run/             NEW · the supervisor.  Never imported by a hook or by `--version`.
    ├── supervisor.py  the asyncio loop: claim → admit → dispatch → complete → reap
    ├── discover.py    streaming roster; connector cursors; the stat index; scope rules
    ├── wave.py        wave gate · part windows · expansion (INSERT OR IGNORE) · sweep
    ├── dispatch.py    dispatch_key batching · OOM halving · crash quarantine · Sequence sessions
    ├── services.py    Service pool: residency refcount, capacity derivation, token minting
    ├── pipeline.py    THE middleware order (below).  The only caller of DriverHost.invoke.
    ├── converge.py    cohorts · witness · resurrect · the attribution guard
    ├── manifest.py    incremental run manifest writer
    └── cli/           ingest update resume queue top why cost cache services replay events manifest

packages/omniweave-otel/     NEW, 12th distribution.  deps: omniweave-core, opentelemetry-sdk (Apache-2.0)
    src/omniweave_otel/sink.py     entry point: omniweave.sinks → "otel"
```

### DDL (SQLite; the same DDL on Postgres for T3, `UPDATE…RETURNING` → `FOR UPDATE SKIP LOCKED`)

```sql
PRAGMA busy_timeout = 5000;   -- FIRST. journal_mode before busy_timeout crashes a contended open (#238)
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA cache_size   = -64000;
PRAGMA temp_store   = MEMORY;
PRAGMA mmap_size    = 268435456;

-- ─── the corpus roster.  ONE row per document.  100k docs ≈ 22 MB. ────────────────
CREATE TABLE unit (
  unit_uri       TEXT PRIMARY KEY,            -- canonical_uri(): realpath + normcase + '/' + strip \\?\
  connector      TEXT NOT NULL DEFAULT 'fs',
  cursor         TEXT,                        -- the connector's resume token FOR THIS UNIT
  state          TEXT NOT NULL CHECK (state IN
                   ('discovered','acquiring','acquired','planned','running',
                    'settled','failed','out_of_scope')),
  -- the stat index, inline: graphify's racily-clean predicate needs exactly these three
  size           INTEGER, mtime_ns INTEGER,
  indexed_at_ns  INTEGER,                     -- captured BEFORE the read
  content_digest TEXT,                        -- sha256 over NORMALISED load-bearing bytes
  normalizer     TEXT,                        -- NULL ⇒ raw bytes hashed; records OW-C-041
  media_type TEXT, format TEXT, bytes INTEGER,
  part_count     INTEGER,                     -- NULL until `identify`; drives wave expansion
  acq_failure_class TEXT, acq_retry_after INTEGER,
  acq_attempts_total INTEGER NOT NULL DEFAULT 0,
  acq_attempts_today INTEGER NOT NULL DEFAULT 0,
  acq_last_attempt_at INTEGER,                -- the PERIOD STAMP for attempts_today
  stale_since    INTEGER,                     -- FIRST transition only; kept across a reset
  settled_gen    INTEGER, last_seen_gen INTEGER NOT NULL,
  scope_rule     TEXT CHECK (scope_rule IN ('explicit','inherited') OR scope_rule IS NULL),
  x              TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE INDEX unit_ready ON unit(state, last_seen_gen)
  WHERE state IN ('discovered','acquired','planned');
CREATE INDEX unit_stale ON unit(stale_since) WHERE stale_since IS NOT NULL;

-- ─── the queue, the checkpoint and the freshness source.  D4 owns `decision_id`. ──
CREATE TABLE work (
  id              INTEGER PRIMARY KEY,
  unit_uri        TEXT NOT NULL REFERENCES unit(unit_uri) ON DELETE CASCADE,
  unit_part       TEXT NOT NULL DEFAULT '',   -- '' folds NULL: NULLs are distinct in a UNIQUE index
  operator        TEXT NOT NULL,              -- the SCHEDULED step: 'parse' | 'derive.chunk' | 'embed'
  op_version      INTEGER NOT NULL,
  driver          TEXT,                       -- resolved driver_id; NULL until routed
  driver_schema_v INTEGER,
  cache_key       TEXT NOT NULL,              -- RECORDED, so a config change is a mismatch not a reuse
  dispatch_key    TEXT NOT NULL DEFAULT '',   -- sha1(driver‖config_digest‖isolation)[:16]  ★ the batch axis
  decision_id     TEXT REFERENCES route_decision(decision_id),      -- D4: no driver runs unrouted
  sequence_id     TEXT,                       -- D4 Sequence binding
  wave_id         INTEGER,
  status          TEXT NOT NULL CHECK (status IN
                    ('pending','claimed','done','failed_transient','failed_permanent','deferred')),
  failure_class   TEXT, failure_message TEXT, retry_after INTEGER,
  attempts_total  INTEGER NOT NULL DEFAULT 0,
  attempts_today  INTEGER NOT NULL DEFAULT 0,
  last_attempt_at INTEGER,
  stale_since     INTEGER,
  claimed_by      TEXT,                       -- "<host>:<pid>:<process_create_time>" — a PID is reusable
  claimed_gen     INTEGER, lease_expires INTEGER,
  cost_micros     INTEGER NOT NULL DEFAULT 0,
  queued_ms       INTEGER NOT NULL DEFAULT 0, -- ★ separate from ran_ms, always
  ran_ms          INTEGER NOT NULL DEFAULT 0,
  peak_rss_bytes  INTEGER NOT NULL DEFAULT 0,
  priority        INTEGER NOT NULL DEFAULT 0  -- and it is ACTUALLY ORDERED BY
) STRICT;
CREATE UNIQUE INDEX work_identity  ON work(unit_uri, unit_part, operator, op_version);
CREATE INDEX work_claimable ON work(status, retry_after, priority DESC, dispatch_key, id)
  WHERE status IN ('pending','failed_transient');           -- batch-coherent claim = one index scan
CREATE INDEX work_leases    ON work(lease_expires) WHERE status = 'claimed';
CREATE INDEX work_unit      ON work(unit_uri);
-- No counter table: `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift.

CREATE TRIGGER work_no_live_delete BEFORE DELETE ON work
  WHEN OLD.status IN ('pending','claimed','failed_transient')
  BEGIN SELECT RAISE(ABORT, 'OW-S-014 refusing to delete a live work row'); END;

-- ─── one cache index for five layers: one GC, one bill, one `ow cache` verb ───────
CREATE TABLE cache_index (
  cache_key    TEXT PRIMARY KEY,
  recipe       INTEGER NOT NULL,              -- a bump NAMESPACES.  It never deletes.
  layer        TEXT NOT NULL CHECK (layer IN ('bytes','parse','derive','llm','embed','render')),
  tier         TEXT NOT NULL CHECK (tier  IN ('free','local_compute','billed_api')),
  ref          TEXT NOT NULL,                 -- 'cas://ab/cd/<sha256>' | 'owstore://doc/7/gen/3'
  bytes        INTEGER NOT NULL,
  unit_uri     TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  driver       TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  config_digest TEXT NOT NULL,
  origin_operator TEXT NOT NULL,              -- OWNERSHIP.  Never conflated with confidence.
  spend_json   TEXT NOT NULL,                 -- the Spend that produced it — REPLAYED on every hit
  micros       INTEGER NOT NULL,              -- priced at creation; re-priced on hit with the live PriceBook
  partial      INTEGER NOT NULL DEFAULT 0,
  created_ns   INTEGER NOT NULL, last_hit_ns INTEGER NOT NULL,
  hits         INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX cache_gc   ON cache_index(tier, last_hit_ns);
CREATE INDEX cache_unit ON cache_index(unit_uri, unit_part, layer);
CREATE INDEX cache_ns   ON cache_index(driver, driver_schema_v, recipe);   -- the FREE-tier sweep

-- ─── cross-document derivation: cohorts by default, witnesses by opt-in ──────────
CREATE TABLE cohort (
  cohort_id     TEXT PRIMARY KEY,             -- 'coh_' || sha256_canonical(member merkle)[:24]
  name          TEXT NOT NULL, member_count INTEGER NOT NULL,
  member_digest TEXT NOT NULL,
  built_gen     INTEGER NOT NULL, built_ns INTEGER NOT NULL
) STRICT;
CREATE TABLE cohort_member (
  cohort_id TEXT NOT NULL REFERENCES cohort(cohort_id) ON DELETE CASCADE,
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', content_digest TEXT NOT NULL,
  PRIMARY KEY (cohort_id, unit_uri, unit_part)
) WITHOUT ROWID;
CREATE TABLE witness (              -- artifact kind `witness_set`: what a produced item CONSULTED
  item_key TEXT NOT NULL, origin_operator TEXT NOT NULL,
  src_uri TEXT NOT NULL, src_part TEXT NOT NULL DEFAULT '', src_token TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (item_key, origin_operator, src_uri, src_part, src_token)
) WITHOUT ROWID;
CREATE INDEX witness_src ON witness(src_uri, src_part);   -- resurrect: delta ⋈ witness

-- ─── runs, waves, services ───────────────────────────────────────────────────────
CREATE TABLE run (
  run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL UNIQUE,   -- integer, NEVER a clock
  trigger TEXT NOT NULL CHECK (trigger IN ('cli','hook','upstream','watch')),
  argv TEXT NOT NULL,
  config_digest TEXT NOT NULL, semantic_digest TEXT NOT NULL,    -- ★ two digests, see config_axes
  policy_digest TEXT NOT NULL, pricebook_digest TEXT NOT NULL,
  omniweave_version TEXT NOT NULL, contract INTEGER NOT NULL,
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  outcome TEXT, manifest_path TEXT NOT NULL
) STRICT;
CREATE TABLE wave (
  run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
  wave_id INTEGER NOT NULL, units INTEGER NOT NULL, parts INTEGER NOT NULL,
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  ok INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
  deferred INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, wave_id)
) WITHOUT ROWID;
CREATE TABLE service_observation (
  run_id TEXT NOT NULL, service TEXT NOT NULL, model_id TEXT NOT NULL,
  base_url TEXT NOT NULL, spawned INTEGER NOT NULL, cold_start_ms INTEGER,
  capacity INTEGER NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
  units INTEGER NOT NULL DEFAULT 0, gpu_ms INTEGER NOT NULL DEFAULT 0,
  queue_p50_ms INTEGER, queue_p95_ms INTEGER, evicted_at_ns INTEGER,
  PRIMARY KEY (run_id, service, model_id)
) STRICT;
```

### The claim, with the batch axis

```sql
-- One statement.  Claims a BATCH-COHERENT set: every row shares dispatch_key with the first.
WITH head AS (
  SELECT dispatch_key FROM work
   WHERE status IN ('pending','failed_transient')
     AND (retry_after IS NULL OR retry_after <= :now_ms)
     AND attempts_total < 5
   ORDER BY priority DESC, dispatch_key, id LIMIT 1)
UPDATE work SET
  status = 'claimed', claimed_by = :worker_identity, claimed_gen = :generation,
  lease_expires = :now_ms + :lease_ms,
  attempts_total = attempts_total + 1,
  attempts_today = CASE WHEN date(last_attempt_at/1000,'unixepoch')
                          = date(:now_ms/1000,'unixepoch') THEN attempts_today + 1 ELSE 1 END,
  last_attempt_at = :now_ms
WHERE id IN (
  SELECT w.id FROM work w, head
   WHERE w.dispatch_key = head.dispatch_key
     AND w.status IN ('pending','failed_transient')
     AND (w.retry_after IS NULL OR w.retry_after <= :now_ms)
     AND w.attempts_total < 5
   ORDER BY w.priority DESC, w.id LIMIT :batch_max_units)
RETURNING *;
-- Completion is atomic w.r.t. supersession — no extra lock:
--   UPDATE work SET status=… WHERE id=:id AND claimed_gen=:gen AND status='claimed';
--   zero rows affected ⇒ superseded ⇒ the whole transaction rolls back.
-- A live holder past its lease gets ONE extension with a WARNING naming it.  Never a steal.
```

### The middleware order — the ordering *is* the artifact

```python
# omniweave/run/pipeline.py — the ONLY caller of DriverHost.invoke().  Semgrep-enforced.
with_events                                   # span open/close; W3C ids; always on
  └─ with_request_count
      └─ with_cache          # ← a HIT returns HERE.  No budget, no tokens, no rate-limit slot.
          │                  #   metrics replayed from cache_index.spend_json, was_cache_hit=True
          └─ with_budget     # ← reserve/commit.  DENIED short-circuits to DEFERRED_BUDGET (not a failure)
              └─ with_retries        # OUTSIDE rate limiting: a retry gets back in line
                  │                  # serial per (unit_uri, unit_part): Semaphore(1)  [D4 R11]
                  └─ with_rate_limiting
                      └─ with_metrics          # measures the PROVIDER, not the queue
                          └─ with_fault_injection   # `_chaos:{failure_rate,exception_type,latency_ms}`
                              │                     # gated, SHIPPED in production builds
                              └─ DriverHost.invoke(batch)   # D3 subproc | inproc thread
# Each layer is (sync_fn, async_fn) -> (sync_fn, async_fn) and is skipped when its dependency is None.
# Composition is a sequence of `if`s.  No framework.
```

### Config (delta on `omniweave.toml`)

```toml
[run]
wave_units        = 512        # units admitted per wave
wave_parts_cap    = 8192       # parts per wave; a unit above this gets its own wave
part_window       = 256        # ordered scheduling windows inside an oversized unit
max_queue_depth   = 32768      # claimable rows before discovery PAUSES (backpressure, never drop)
lease_ms          = 120000
interactive_wait_s = 2         # named wait budgets, passed per call, never a constant
batch_wait_s       = 60
yield_interval    = 1000       # cooperative yield, at the TOP of the loop body
watchdog_ms       = 600000     # no synchronous stage may exceed watchdog_ms / 2   (X15)
min_free_bytes    = 5368709120 # below this, PAUSE and name the GC command.  Never silently evict.
verify_idempotence_rate = 0.01 # deterministic blake2b selection, never RNG

[budget]                       # UNITS in flight (D1).  Distinct from drivers.max_workers (D3).
per_document_micros = 20000
max_inflight = { FREE = 32, LOCAL_COMPUTE = 4, BILLED_API = 2 }
max_inflight_per_provider = { openai = 8 }

[drivers]                      # PROCESSES (D3)
max_workers       = { free = 4, local_compute = 4, billed_api = 8 }
worker_idle_ttl_s = 300
crash_quarantine  = { crashes = 3, window_s = 60 }
allow_full_cohort_rebill = false          # X17

[services."vlm"]
model_id          = "…"
model_revision    = "a1b2c3…"   # "main" is a STARTUP ERROR, not a warning
endpoint          = ""          # non-empty ⇒ attach only, never spawn
autostart         = true
capacity          = 0           # 0 ⇒ derive from the server's own reported concurrency at preflight
batch_wait_ms     = 25          # the server's coalescing window across ALL clients
max_batch         = 32
keep_alive_s      = 300
startup_timeout_s = 600
auth              = "token"     # `none` additionally requires allow_unauthenticated = true

[cache]
recipe    = 1
gc        = { free_after_days = 7, local_after_days = 90, billed_after_days = 0 }   # 0 = NEVER
max_bytes = { free = 21474836480, local_compute = 107374182400, billed_api = 0 }    # 0 = unbounded

[observe]
level       = "info"                                  # error|warn|info|debug|trace
sinks       = ["console", "ndjson"]                   # + "otel" when omniweave-otel is installed
ndjson_path = ".omniweave/events/{run_id}.ndjson"
call_sample = 1.0                                     # deterministic blake2b sampling of call.* spans
timings     = "always"                                # never behind an env var
```

```toml
# tools/config_axes.toml — gate G17.  An UNCLASSIFIED key is treated as SEMANTIC (fail expensive,
# never wrong) and FAILS CI until a row is added with a justification.
[semantic]      # enters cache keys AND sets the full-scan latch
keys = ["drivers.*.config", "limits.*", "targets.*", "cache.recipe",
        "services.*.model_id", "services.*.model_revision"]
[operational]   # NEVER enters a cache key.  Changing these must not cost a dollar.
keys = ["run.*", "budget.*", "observe.*", "store.*",
        "roots.source", "roots.output", "roots.cache",         # the SALT is relative — see D1 §7.1.4
        "drivers.max_workers", "drivers.worker_idle_ttl_s", "drivers.crash_quarantine",
        "services.*.endpoint", "services.*.autostart", "services.*.capacity",
        "services.*.batch_wait_ms", "services.*.max_batch", "services.*.keep_alive_s",
        "cache.gc", "cache.max_bytes"]
```

### The event schema (`schema/event-v1.json`, generated + byte-diff gated — G19)

```jsonc
{"v":1,"ts":1756713041882317000,"run":"01JBQ…","seq":41207,
 "tid":"4bf92f3577b34da6a3ce929d0e0e4736","sid":"00f067aa0ba902b7","psid":"a1b2c3d4e5f60718",
 "k":"call.end","lvl":"info","code":null,
 "unit":"file:///corpus/10-K.pdf","part":"p41","op":"parse","drv":"parse.pdf.pdfium","dv":3,
 "f":{"outcome":"ok","cache":"miss","queued_ms":9,"ran_ms":214,"rss":184123392,
      "spend":{"wall_ms":214,"cpu_ms":198,"gpu_ms":0,"tokens_in":0,"tokens_out":0,
               "calls":1,"bytes_egress":0},
      "micros":0,"decision":"dec_7f3a…","batch":8,"service":null}}
```

```
events.toml — CLOSED, APPEND-ONLY, CI-diffed.  Span hierarchy: run > wave > unit > part > attempt > call
run.start  run.end            wave.start wave.end
unit.discover unit.acquire unit.identify unit.settle unit.scope_drop
part.route  work.claim  work.complete  attempt.start attempt.end
call.start call.end
cache.hit cache.miss cache.corrupt cache.legacy cache.sweep
budget.reserve budget.deny budget.exhaust
service.spawn service.attach service.evict service.refuse
driver.crash driver.quarantine  store.contend  degrade  gc.sweep  manifest.write
```

### CLI

```
ow ingest [PATHS…] [--dry-run] [--profile fast|balanced|thorough|offline] [--max-rung PAGE]
ow update [--dry-run]                    # --dry-run on BOTH.  graphrag has it on index and not update.
ow resume                                # an ALIAS for `ow ingest`: recovery IS the normal command
ow queue  status | list --status failed_permanent | retry --class TIMEOUT | drain
ow top    [--plain] [--interval 10]      # live; read-only; never attaches to the supervisor
ow why    <uri> [--part p41]             # acquisition · decisions · cache-key diff · spend · next retry
ow cost   [--by document|driver|provider|slice] [--since 7d] [--format table|json|csv]
ow cache  stat | explain <uri> --op parse | gc [--dry-run] | migrate --to-recipe 2 --dry-run
ow services list | stop <name> | logs <name>
ow replay <run_id> [--unit URI] --offline
ow events tail [--kind call.end] | schema
ow manifest <run_id>
ow doctor --runtime
ow dev run --driver ./mydriver --unit sample.pdf --trace     # a contributor's whole inner loop
```

```
$ ow why file:///corpus/10-K.pdf --part p41
unit   file:///corpus/10-K.pdf   settled_gen 40 · last_seen_gen 41 · 188 parts · 9.2 MB · pdf
       content_digest 3f9c…  (normalizer pdf/1: stripped /ModDate /ID)
       stat: size=9663488 mtime_ns=…  racily-clean ✓
part   p41 · lane text
route  dec_7f3a…  rule decode.part-text-unusable  (project:.omniweave/route.toml:41)
       cause garble.score=0.71 >= 0.50 · read set: decode.char_count, garble.score, ink.coverage
       DECODE decode.pdftext → PAGE page.olmocr   est 4,100 µ · reserved 6,000 µ  ADMITTED
cache  MISS.  key 9a41…  differs from generation 40 in group `producer`:
         producer.schema_version  3 → 4        (driver parse.ocr.olmocr upgraded)
         everything else identical.   `ow cache migrate --to-recipe 1 --dry-run` for the corpus cost.
spend  attempt 1  gpu_ms 2,410  tokens_out 3,102  calls 1  → 4,880 µ   (pricebook v3)
state  done at gen 41.  origin_operator parse.  restriction_bits 0.
```

### Protocol deltas (additive; flagged, not silent)

```
D3 HELLO   + services: {"<name>": {base_url, model_id, capacity,
                                   auth:{scheme:"bearer", token:"…"}}}
           + determinism: {seed:int, clock_ns:int}
           ── D3 defines `DriverIO.service(name)` but no wire field to carry the endpoint;
              this fills that gap rather than contradicting it.  `determinism` mirrors D1's
              omniweave-target/1 envelope so the two child-process seams say the same thing.
D3 INVOKE  + sequence_id: str|null, session: bool          ── D4's Sequence binding on the wire
```

### Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| X1 | The `work` claimable set is the only resume state; there is no checkpoint file. | CI grep bans `*checkpoint*` under `cache_root`; **G20**: a `SIGKILL` fixture at three random points asserts `ow resume` completes and the final store equals an uninterrupted run |
| X2 | A work row is never deleted while `pending`, `claimed` or `failed_transient`. | `work_no_live_delete` `BEFORE DELETE` trigger; the sweep is one `DELETE … WHERE status='done' AND unit_uri IN (settled)` |
| X3 | Discovery never materialises more than `run.max_queue_depth` claimable rows, and supervisor RSS stays under 250 MB at any corpus size. | The wave gate; **G21** nightly 100k-synthetic-roster run asserting peak `count(claimable)` and peak RSS |
| X4 | No `OPERATIONAL` config key enters a cache key. | `tools/config_axes.toml` + **G17** (unclassified key fails CI, defaults to SEMANTIC); a test mutates every operational key and asserts `cache_key` is byte-identical |
| X5 | `code_fingerprint` and `deps_digest` enter the cache key **iff** `cost.class == "free"`. | One `cache_key()`; a table-driven test over all three classes. Reconciles D3's "schema_version alone" with mine-runtime §7.5.2's FREE namespacing |
| X6 | A cache-recipe bump namespaces; it never deletes, and `billed_api` is never swept. | `recipe` is a plain column; `ow cache migrate --dry-run` prints re-bill micros; a test writes recipe 1, bumps to 2, asserts recipe-1 rows still readable and billed rows intact |
| X7 | A cache hit costs no budget, no tokens and no rate-limit slot, and replays its metrics with `was_cache_hit=true`. | Middleware order asserted by a composition test; a zero-headroom-ledger test asserts the hit still succeeds |
| X8 | No billable call happens without a reservation. | `pipeline.py` is the only caller of `DriverHost.invoke`; semgrep bans it elsewhere; a `BILLED_MICROS=0` test asserts zero provider calls and N `DEFERRED_BUDGET` rows |
| X9 | Retries are serial per `(unit_uri, unit_part)` and share the per-part budget. | `Semaphore(1)` keyed on the pair; fault injection asserts sequential provider calls (D4 R11 — the fix for olmocr's 64× amplifier) |
| X10 | A batch is invisible to the `work` table. | One claim per row, one `RESULT` per unit, one completion per row; a `batch_max_units=32` test asserts 32 transitions and 32 `route_spend` rows |
| X11 | `OOM`/`WORKER_DIED` halves `batch_max_units` for that `(driver, config_digest)` for the run, floor 1. | Stateful in `dispatch.py`; a chaos fixture that OOMs above batch 8 asserts convergence and a `degradations[]` entry |
| X12 | A run with no admitted work needing a service spawns no service. | Lazy acquisition on first `INVOKE` to a service-declaring driver; a born-digital fixture asserts zero `service_observation` rows |
| X13 | One service per `(name, model_id, options_digest)` per host, and attach verifies the model id. | surya's sentinel+filelock ladder; an 8-process concurrent-cold-start test asserts exactly one spawn; a wrong-model-id server test asserts refusal |
| X14 | A spawned service is authenticated. | 32-byte token in the 0600 sentinel and in `HELLO.services`; an unauthenticated request test asserts 401; `allow_unauthenticated` prints the risk |
| X15 | No synchronous stage exceeds `run.watchdog_ms / 2`. | Cooperative yield every `yield_interval` at the **top** of the loop body; CI timing assertion over the fixture corpus; bulk index drop/recreate windowed |
| X16 | An incremental run converges to a full rebuild. | Cohort digests + `witness` + `resurrect`; **G18** incremental-then-full on the 200-doc fixture, diffing every table |
| X17 | A `billed_api` `corpus`-granularity driver without `witness_set` cannot run. | Resolve-time `CORPUS_REBILL_UNBOUNDED` unless `drivers.allow_full_cohort_rebill = true` |
| X18 | An operator's re-run replaces only rows whose `origin_operator` is its own. | `origin_operator NOT NULL`; every eviction statement filtered on it; a test runs a `free` derive after a `billed_api` derive and asserts the billed rows survive |
| X19 | Unaccounted per-unit loss refuses that unit's transaction; a unit that failed this run may never account for its own loss. | The per-unit attribution guard computed from `work`; quarantine is `failed_permanent(UNEXPLAINED_LOSS)`, one unit, not the run |
| X20 | Every emitted event validates against `schema/event-v1.json` and every `kind` is registered in `events.toml`. | **G19** byte-diff gate; a test asserts each emitted kind is registered and the NDJSON sink round-trips |
| X21 | `omniweave-core` imports no telemetry SDK and no compiled extension. | D1's G1/G9 plus a grep for `opentelemetry` outside `packages/omniweave-otel/` |
| X22 | The run manifest is written incrementally. | A `SIGKILL` test asserts a parseable partial with `"outcome":"interrupted"` |

New CI gates: **G17** config axes · **G18** incremental-vs-full equivalence (on merge, ~8 min) ·
**G19** event schema byte-diff · **G20** kill-9 resume fixture · **G21** nightly 100k-roster scale.

---

## The 100k-document ingest, with numbers

| stage | quantity | note |
|---|---|---|
| roster | 100,000 `unit` rows × ~220 B = **22 MB** | streamed from a connector cursor; resumable at the cursor; never a Python list |
| parts | mean 8 → **800,000 parts** | `part_count` filled at `identify`, which is a page count, not a parse |
| work rows, naive | 800k parts × 4 PART operators = **3.2 M rows ≈ 1.3 GB** | this is what "plan the corpus first" costs, plus index churn on every insert |
| work rows, waves | 512 units × 8 parts × 4 ops = **16,384 live rows ≈ 6 MB** | 196 waves; swept to `cache_index` as units settle |
| route bookkeeping | D4's own figure, ~1 GB per million parts → **~800 MB**, ~290 MB after the 30-day sweep | decisions + deduplicated evidence + spend |
| page rasters | 192-DPI A4 = **10.7 MB each** (D2); `render_batch = 4` ⇒ **43 MB** resident | rasters go to the blob CAS on creation and are referenced by digest, never held. All 5,000 pages of one document would be ~53 GB — which is why rendering follows routing |
| supervisor RSS | **< 250 MB** steady, asserted nightly (G21) | it holds no document bytes |
| worker RSS | bounded by each card's `isolation.memory_mb` (anydoc 512 MB, a 7B VLM 8 GB) | `ow doctor` **refuses to start** when `Σ max_workers × memory_mb > 0.8 × RAM`, naming the knob |
| bookkeeping cost | ~4 SQLite statements + ~2.4 KB per part → 3.2 M statements ≈ **65 s** across the whole run | 64 transitions per transaction; negligible against parse |
| time to first document | **< 5 s** | roster streaming plus one wave; not a 40-minute planning phase |
| crash at hour 6 | recovery is `ow resume`; the health check is one indexed `COUNT`; expected re-work **≤ one wave** | claimed rows with expired leases plus pending rows are *exactly* the unfinished work |
| GPU feed | 4 `local_compute` workers × `batch_max_units = 8` = **32 concurrent page requests** against a 25 ms server window | the server coalesces; the driver need not know batching exists |

---

## What this costs

- **Engineering, two people, ≈20 engineer-weeks (~10 calendar weeks) to a shippable runtime**, layered
  so each phase ships something a user runs:
  P1 (5 wk) `unit`/`work`/claim/lease/failure taxonomy, wave scheduler, `events.py`, `cache_index`,
  `ow queue`/`ow doctor --runtime` · P2 (3 wk) driver-host integration, `dispatch_key` batching, OOM
  halving, crash quarantine, the middleware stack with fault injection · P3 (3 wk) services:
  attach-or-spawn, tokens, residency, capacity derivation, `ow services` · P4 (4 wk) cohorts, witness,
  resurrect, attribution guard, **G18** · P5 (3 wk) `ow top`/`ow why`/`ow cost`/`ow replay`, the
  incremental manifest, `omniweave-otel` · plus **2 wk of Windows parity budgeted explicitly** (named
  pipes, `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, no `nohup`/`setsid`, NUL-byte paths).
- **Runtime overhead**: ~65 s of SQLite bookkeeping per 800k parts; ~24 B/event of id overhead;
  ~8 events per part at `level = info` (≈6.4 M events, ~1.9 GB of NDJSON per 100k-doc run — the sink
  rotates and `call_sample` throttles it).
- **Dependency weight: zero new runtime dependencies.** `omniweave-otel` is opt-in and Apache-2.0.
  Nothing here touches an AGPL, OpenRAIL or GPL artefact.
- **Operational burden**: five new CI gates, one of which (G18) costs ~8 minutes on merge and one of
  which (G21) is nightly. Two new tables an operator will eventually need to GC (`cache_index`,
  `route_*`), both with `ow cache gc --dry-run` and stated retention defaults.
- **Documentation surface**: one runtime page, one events reference (generated from `events.toml`),
  one cost page, one "my ingest is stuck" runbook whose entire body is `ow why` and `ow top`.

---

## Conflicts with upstream rulings

**C1 — D3's MessagePack wire versus D1's zero-dependency core. Load-bearing for this decision.**
D1 §Spec: `omniweave-core` `dependencies = []` — *"ENFORCED BY GATE G1. Amending this amends D1"* —
and G9 asserts `import omniweave_core` loads **zero** third-party modules. D3 places the subproc host
at `omniweave-core/omniweave/core/drivers/host/subproc.py` and specifies
`Frame ::= u32 length_le | u8 kind | MessagePack payload`. `msgpack` is a third-party compiled
extension. **Minimum amendment (pick one):** (a) the frame codec becomes `omniweave_core.frames`, a
vendored ~300-line pure-Python MessagePack subset (the format is a public spec; the reference
implementation is Apache-2.0), keeping G1 and G9 intact — frames are small by construction because D3
sends anything over `INLINE_MAX = 262144` as a blob reference, so a pure-Python codec at ~4 KB/frame
costs tens of microseconds; or (b) G1 is amended to permit exactly one pure-Python third-party
dependency. **I recommend (a)** and have written the design against it; if measurement shows the codec
dominates at 32 inflight, the escape is an optional compiled accelerator in `omniweave` (not core) with
a parity test, the same shape as `json`/`ujson`.

**C2 — D1 §Spec "zero third-party dependencies" versus D2 §Spec "`omniweave-core` depends on
`pydantic`, `zstandard` and stdlib `sqlite3`".** These cannot both hold; D2 also budgets `omniweave/owdoc/`
at "~15 MB" against D1's 3 MB ceiling for core. This is not my decision to make, but it changes my
cold-start and import-time assumptions, so I flag it and **design to the tighter constraint**: nothing
in this proposal requires pydantic or zstandard, and `omniweave_core.events` and
`omniweave_core.frames` are stdlib-only. Minimum amendment: either D2's owdoc pydantic models move to a
separate `omniweave-owdoc` distribution and D1's G1 stands, or D1's G1 is amended and the 80 ms
cold-start budget is re-measured with `pydantic_core` on the import path.

**Two apparent conflicts that are not conflicts, recorded so the judge does not have to re-derive them.**
(i) D1's `[budget] max_inflight = { FREE = 32, LOCAL_COMPUTE = 4, BILLED_API = 2 }` and D3's
`[drivers] max_workers = { free = 4, local_compute = 4, billed_api = 8 }` measure **different
quantities** — units in flight versus worker processes — and compose exactly: 32 FREE units across 4
worker processes at `batch_max_units = 8`. Both stand; `ow doctor --runtime` prints the derived
throughput ceiling so nobody has to work it out. (ii) D1's "three seams and no fourth" plus D3's
long-lived subproc driver host over a 0600 UDS is D3 exercising the escape hatch D1 wrote
(*"if a later decision needs one it is a unix socket or named pipe at 0600, never a loopback port"*).
The runtime treats process seams as two families — `Toolchain` for targets, `DriverHost` for drivers —
and does not re-open it.

---

## Rationale

**Adoption is decided at three moments, and this runtime is designed around all three.** The first is
`pip install omniweave && ow ingest ./docs`: it must work on a laptop with no GPU, no Node and no
config, produce a result in seconds, and print progress. The wave scheduler and the demand-planned
signal layer are what make time-to-first-document under five seconds instead of a planning phase.
The second is the first failure: a corrupt PDF, a missing tesseract language pack, an exhausted budget.
Every one of those is a typed class with a named remedy, and `ow why` turns "it didn't work" into one
screen. The third is production: a 100k ingest that must survive a crash, be visible on a dashboard,
and produce a bill someone can defend. That is `ow top`, the event stream, `omniweave-otel`, and
`would_have_been_micros_if_uncached`.

**The single highest-leverage decision here is putting coalescing in the model server and the event
schema in core.** Both are the same move: push the hard part to a place where a third party gets it for
free. A contributor writing a driver in an afternoon submits one page per call and gets a saturated
GPU, because the server batches across every client; they call `io.log()` and `io.progress()` and get a
trace, a cost row and a `ow top` line, because the host wraps every `INVOKE` in a `call` span. Neither
requires them to read the runtime's source. The counter-design — batching inside the driver, tracing
inside the driver — is what every repo in the collection does, and it is why none of them has a second
implementation of anything.

**The correction to `mine-runtime.md` §7.5 is not cosmetic.** A cache key containing the entire
effective run config means the cache is invalidated by knobs that cannot change the answer. In a
`billed_api` tier that is money, and it is money spent in a way the operator cannot see, because the
symptom is a hit rate that quietly dropped. graphrag's `str()` fallback produced a permanent silent
100% miss; this is the same failure with a nicer cause. Classifying config keys costs one TOML table
and one CI gate, and it makes `ow cache explain` able to say which group differed — which is the
difference between a cache you trust and a cache you disable.

**Correctness-first, efficiency-opt-in, cost-visible** is the pattern I applied three times: cohorts
before witnesses, refusal before unbounded re-billing, `SEMANTIC` as the default classification. Each
time the safe choice is the expensive one and the expensive choice is *visible*, because the failure
mode I fear most in this layer is not slowness, it is codegraph's 4.3% — silent, both directions,
forever, until a full rebuild.

---

## Tradeoffs

- **Waves add a scheduling concept the reference design does not have.** Cost: one more table, one more
  span level, one more thing to explain, and a pathological unit (a 4,000-page PDF) needs part windows
  as a special path. Benefit: bounded memory, bounded index churn, sub-five-second first result, and a
  resume that re-does at most one wave.
- **Sweeping `done` work rows means the queue is not a complete history.** History lives in
  `cache_index`, `route_decision` and `driver_observation`. If an operator wants the queue as an audit
  log they must set `run.sweep = false` and pay 1.3 GB per 100k documents.
- **Coalescing in the server means omniweave does not control the batch shape.** A vLLM tuned badly is
  a vLLM tuned badly, and we can only report `queue_p95_ms`. The alternative — proxying every model
  call through the host — would give us control and would put a Python hop in front of a GPU.
- **A pure-Python frame codec is slower than `msgpack`.** Chosen to protect D1's G1/G9, measurable,
  and with a stated escape.
- **The `SEMANTIC`/`OPERATIONAL` split is a judgment call, made by humans, in a file.** A
  misclassification is a real bug. Mitigated by failing toward SEMANTIC, by G17, and by
  `ow cache explain` diffing the projection between runs — not eliminated.
- **`ow top`, `ow why`, `ow cost`, `ow replay` and `ow dev run` are ~3 engineer-weeks of surface that
  parse no documents.** I am spending it deliberately: TCO in this layer is dominated by the hours
  someone spends not knowing why a run is stuck.
- **X17's refusal will annoy someone.** A `billed_api` corpus operator without witnesses is refused
  rather than allowed to re-bill the corpus on a one-document change. The flag exists; the default
  does not.

---

## Failure modes

1. **A single 4,000-page unit stalls a wave.** Part windows bound it, but the *unit* is not `settled`
   until every window is, so a document that fails in window 14 of 16 holds `unit.state = 'running'`
   and its downstream corpus operators. Input that breaks it: one 10,000-page court filing in a corpus
   of memos. Mitigation is a per-unit deadline that settles the unit `ok_partial` with the completed
   windows; the failure is that the cohort digest then changes again when the rest lands.
2. **Config-axis misclassification.** An `OPERATIONAL` label on a key that does change the answer
   silently reuses wrong cached output — worse than re-billing. The fail-toward-SEMANTIC default and
   G17 catch new keys, not a wrong human judgment on an old one.
3. **The event stream becomes the bottleneck.** At `level = debug` with `call_sample = 1.0`, a 100k
   ingest writes ~6 GB of NDJSON and the sink's `write()` sits on the supervisor's loop. Mitigation:
   the sink is a bounded queue drained by a writer thread with a drop counter — and *dropping events
   while claiming completeness* is exactly the sin I am accusing others of, so the drop count is a
   `degradations[]` entry, not a log line.
4. **A model server that accepts a connection and never returns.** `progress_ms` covers a driver that
   stops reporting, but a server that streams a token every 10 s forever satisfies it. `wall_ms_hard`
   is the real bound and it is per-unit, so a `Sequence` of 64 parts inherits a 64× ceiling. Input that
   breaks it: a repetition loop under a long-generation session.
5. **Two hosts, one SQLite store, one NFS mount.** The claim protocol is correct; SQLite's locking over
   NFS is not. `ow doctor` detects the mount type and refuses T2 on a network filesystem, naming
   Postgres. Someone will override it.
6. **Witness sets that lie.** A driver that under-reports its witnesses produces exactly codegraph's
   silent staleness, and nothing in the runtime can detect it except G18 on a fixture corpus that may
   not exercise the driver's real dependency shape. This is the residual risk of the whole incremental
   story, and I would rather state it than pretend the conformance kit closes it.
7. **The disk-headroom pause is a deadlock in disguise** if the only way to free space is a GC that
   needs to write. The GC path is `DELETE` + `PRAGMA incremental_vacuum` with a reserved 256 MB
   headroom file created at store init and released on the pause.
8. **`ow top` shows a healthy queue while every worker is wedged on an FFI call** that holds the GIL,
   because the supervisor cannot preempt a thread. This is D1's own recorded risk in the anydoc marshal.
   The `queued_ms/ran_ms` heuristic detects saturation; it does not detect a single 90-second marshal.
9. **Cost reconciliation is a lagging indicator.** A driver whose estimate is 2× off is caught by D4's
   lint after seven days of data. The first week of a new driver's billed usage is unbounded by
   anything except the per-document and per-run budgets.
10. **`generation` is a `UNIQUE` integer in one store.** Two runs starting in the same millisecond on
    two hosts contend on that insert; the loser retries with `generation + 1`. Under heavy T2 fan-out
    this serialises run starts, which is fine at ten runs and wrong at ten thousand.

---

## Why I reject the alternatives

- **A general workflow engine (Prefect / Dagster / Temporal / Ray) as the runtime.** This is the
  tempting answer and it is wrong on every axis I care about. It adds tens of megabytes and a
  transitive dependency graph to a framework whose flagship install must stay inside 250 MB (D1's
  Lambda-layer gate); it puts a second scheduler's semantics between the operator and the `work` table,
  so `ow why` becomes "read the Temporal UI"; it forces a service to be running before `ow ingest`
  works on a laptop; and DataFlow already demonstrated the wrapper tax — RayOrch needs
  `AcceleratedOperatorABC` subclasses and a `MemoryStorage` shim, so an operator is either local or
  distributed and porting is a rewrite. The claim protocol on a store row is ~120 lines and gives
  T1→T2→T3 with **no operator change**.
- **A step-numbered or JSON-bag checkpoint (DataFlow, graphrag).** DataFlow's `cache_step_{N}.json` has
  eight documented failure modes, its artifacts live outside the checkpoint model and are not
  content-addressed, and its row index is not stable under batching. graphrag's `state: dict[Any, Any]`
  makes `update_clean_state` load-bearing — omitting it crashes at the *end* of a successful run — and
  reordering the workflow list is a `KeyError` hours in. The claimable set is a checkpoint that cannot
  disagree with reality because it *is* reality.
- **Planning the whole corpus up front.** Every repo studied does this and none of them ingests 100k
  documents. It costs 1.3 GB of rows, minutes of index churn, and the entire time-to-first-result.
- **Batching inside the driver.** It is where every OCR repo puts it, and it means every driver
  re-implements coalescing, every driver gets it slightly wrong, and a contributor's afternoon driver
  starves the GPU. surya already proved the alternative in `common/batch_service/`: one shared server,
  a `batch_wait_ms` window across all clients, `max_batch` as a ceiling.
- **Per-driver in-process model loading.** N in-process copies thrash CPU and GPU (surya's own words),
  and DataFlow's refcount leaks on resume because the counter is primed from the compiled plan rather
  than the surviving work list. One service per `(name, model_id, options_digest)`, refcounted over
  surviving work.
- **An unauthenticated loopback model server.** LEANN's ZMQ REQ/REP on a dynamic loopback port with no
  auth is compute theft from any local process; surya ships `VLLM_API_KEY = "EMPTY"`. A 32-byte token
  in a 0600 sentinel costs nothing.
- **Instrumenting with the OpenTelemetry SDK directly in core.** It is a compiled-adjacent dependency
  graph on the per-turn import path, it breaks D1's G1/G9/G10, it forces every consumer onto OTel, and
  it makes `ow top` and `ow why` depend on a collector being configured. A versioned NDJSON event
  schema plus an out-of-core bridge serves OTel users *and* the laptop user *and* a third-party sink,
  and it is byte-diff gated so it cannot drift the way LEANN's hand-written `llms.txt` did.
- **`warnings.warn(RuntimeWarning)` for cache vintage, corruption and re-bill (graphify).** Filterable,
  unstructured, invisible under JSON logging. These are run-manifest facts and event kinds.
- **`multiprocessing` or a fork-based worker pool of our own.** A second worker lifecycle beside D3's
  driver host, unsafe with CUDA and with an open SQLite handle, and different on three OSes.
- **A wall clock as the generation stamp.** A backward NTP step makes a serviced entry permanently
  stale or evicts an unserviced one; jcodemunch reaches the same conclusion from process start times.
  Integer generations, `monotonic_ns()` for durations, wall clock only for humans.
- **A single `--force`.** graphify writes the scope down: *"force means 'accept a shrink', not 'clobber
  an unreadable graph'"*. Named overrides only.
- **Making per-driver process isolation optional for third parties, or in-process by a card claim.**
  D3 already forbids it; I note only that the runtime depends on it — a third-party driver that can
  OOM the supervisor makes every number in the ingest table above a fiction.
