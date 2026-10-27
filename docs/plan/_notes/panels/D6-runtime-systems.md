# D6-runtime — Execution runtime: scheduling, concurrency, caching, incremental refresh, observability
### Systems-purist proposal

## Headline

**The runtime is a single-threaded transactional Conductor over the `work` table plus a bounded pool
of OS processes — no asyncio anywhere in `omniweave-core`, exactly one thread per process holding a
`sqlite3.Connection`, and exactly one transaction per unit that commits derived rows, the work-row
transition, the dependency record, the budget commit and the spend row together.** Batching exists in
three places and is invisible in all four ledgers (work, spend, trace, failure). The cache is not a
layer but **five content-addressed tiers with three invalidation policies**, of which three tiers are
*the store itself* — and the thing that makes incremental correct is not the cache key at all but a
**`dep` reverse-index table** recording what each derivation read outside its own unit, which is the
only mechanism that answers codegraph's 4.3%-wrong question. GPU saturation is a **pull-based refill
against a per-Service in-flight target**, never a push-based batcher, because a batcher that owns
units owns accounting and accounting must stay per unit.

---

## 0. Conflicts with binding upstream rulings — read first

Two upstream clauses are, as written, jointly unsatisfiable with each other or with this decision. I
flag them rather than silently pick, because both land inside D6's implementation surface and the
charter will inherit whichever reading it copies.

### C1 — `omniweave-core` may have zero dependencies (D1) but needs three (D3)

- **D1-substrate**, `packages/omniweave-core/pyproject.toml`: `dependencies = []` with the comment
  *"ENFORCED BY GATE G1. Amending this amends D1."*, plus gate **G1** *"omniweave-core resolves to
  exactly ONE distribution"* and **G9** *"`import omniweave_core` under -X importtime loads ZERO
  third-party modules"*.
- **D3-drivers**, Consequences: *"Core's new dependency surface is `tomllib` (stdlib), a JSON Schema
  validator and a MessagePack codec — three small pure-Python-capable libraries."*

The MessagePack codec is not optional: D3's wire protocol is
`Frame ::= u32 length_le | u8 kind | MessagePack payload`, it is the transport for every third-party
driver, and the `subproc` host is runtime machinery that must be reachable from both `omniweave` and
`omniweave-serve` — D1's `tools/layers.toml` gives `omniweave_serve = ["omniweave_core"]`, so the host
cannot live in the CLI distribution.

**Minimum amendment (my recommendation): keep G1, write two small core modules instead of taking two
dependencies.**

1. `omniweave_core/msgpack.py` — encoder/decoder for the **D3 frame subset only**: nil, bool, int (all
   widths), float64, str, bin, array, map. ~250 lines. Enforced by a property test in the dev
   dependency group that round-trips against the reference `msgpack` package on 10k
   Hypothesis-generated payloads plus every frame in `schema/`, and by a fuzz target on the decoder
   (malformed length prefixes, truncated frames, depth bombs — decoder depth cap 32, element cap 1e6).
2. `omniweave_core/jsonschema_flat.py` — validator for the **flat-scalar subset** a driver card's
   `[config]` block can express under D1's ruling that *"driver configuration is
   `Mapping[str, Scalar]`, not a pydantic model"*: `type`, `enum`, `minimum`/`maximum`,
   `minLength`/`maxLength`, `pattern`, `default`, `additionalProperties: false`. ~120 lines. Full
   JSON Schema 2020-12 validation stays in `omniweave-conform`, which already has dependencies and is
   where a card is *audited* rather than *loaded*.

The alternative amendment — relax G1 to "exactly one distribution plus a named, pure-Python,
zero-transitive allowlist" — is worse: G1's whole value is that it is a bright line that cannot erode,
and "few" is not a gate. Two files and two parity suites are cheaper than the first erosion. If the
judge prefers the dependency, the cost is that `import omniweave_core` on the per-turn hook path loads
a C extension and G9 must be rewritten.

### C2 — `ctx.driver(kind)` is renamed twice, to two different things

- **D3-drivers**, Consequences: *"`ctx.driver(kind)` becomes `ctx.service(name)`."*
- **D4-router**, Consequences: *"`mine-runtime.md` §7.1.3's `ctx.driver(kind)` is renamed
  `ctx.resource(kind) -> Resource`."*

These cannot both hold, and D4's version is additionally unimplementable under D3: an Operator does
not obtain a driver *by kind* any more. It calls `resolve(requirement, catalog, policy)`, receives
unranked `Candidate`s, hands them to D4's router, and activates the winner through a `DriverHost`.
There is no "get me a resource of kind X" call left to rename.

**Minimum amendment: D3's clause stands and D4's stated goal is satisfied by it.** D4's reason for the
rename is that *"`Driver` is the parse-engine noun … the runtime resource accessor must yield the
name"* — `ctx.service(name)` yields the name as completely as `ctx.resource(kind)` does. So:

- `RunContext.service(name: str) -> ServiceHandle` — host-managed shared resources (D3's Service: a
  vLLM engine, an ONNX session, an embedding server). The same spelling and shape as
  `DriverIO.service(name)`, so an Operator and a Driver reach a Service one way.
- `RunContext.host(candidate: Candidate) -> DriverHandle` — activation; the only site that imports a
  driver's `entrypoint`.
- There is no `ctx.resource` and no `ctx.driver`.

### Noted reconciliations (not conflicts — recorded so the charter does not trip)

- **D1 says "Three seams, and no fourth"; D3 added a fourth.** D1's S1/S2/S3 are in-process FFI (office
  only), the `omniweave-target/1` toolchain child, and attach-or-spawn HTTP model servers. D3's
  `subproc` DriverHost — length-prefixed MessagePack over a 0600 AF_UNIX socket / owner-only named
  pipe — is a fourth. It is permitted by D1's own escape clause (*"if a later decision needs one it is
  a unix socket or named pipe at 0600, never a loopback port"*) and D3 is binding. **This design
  enumerates four seams.** A `subproc` worker is a child of the run with `worker_idle_ttl_s = 300`,
  not a daemon.
- **Two `max_inflight`-shaped knobs already exist and mean different things.** D1
  `[budget] max_inflight = { FREE = 32, LOCAL_COMPUTE = 4, BILLED_API = 2 }` bounds **units in
  flight**; D3 `[drivers] max_workers = { free = 4, local_compute = 4, billed_api = 8 }` bounds
  **worker processes**. Both are kept verbatim under their existing keys. This design adds a third,
  per-Service request ceiling, because neither can express "96 concurrent sequences against one vLLM
  engine served by 4 worker processes".
- **Blocks carry two ownership columns and they are not redundant.** D2 mandates
  `origin_operator TEXT NOT NULL` (*"OWNERSHIP, not trust"*); D3 mandates `origin_driver`,
  `driver_schema_v`, `restriction_bits`. **Eviction and the shrink guard key on `origin_operator`
  (invariant I4); cost attribution, licence refusal and the scoreboard key on `origin_driver`.** They
  differ whenever one operator can be served by more than one driver, which is the normal case.
- **`OperatorIdentity` *is* D2's `Producer`** (D2: *"== L5's OperatorIdentity. One type, two
  layers."*). D2's field names are used verbatim. Mapping onto the work table:
  `work.operator = Producer.operator`; `work.op_version INTEGER = int(Producer.op_version)` (the
  operator's `schema_version`, with a startup assertion on the round-trip). The *driver's* semver is
  not in `Producer` — it lives in `block.origin_driver` / `driver_schema_v` per D3.

---

## 1. Design

### 1.1 The thread and process model — and why there is no `asyncio`

```
ONE `ow ingest` PROCESS
┌─ Conductor thread ─────────────────────────────────────────────────────────┐
│  Owns the ONLY sqlite3.Connection in this process.                         │
│  loop:  heartbeat → reap leases+reservations → plan-expand (if under LWM)  │
│         → claim(batch) → refill services → dispatch → collect → COMMIT     │
│  Never blocks on a socket, a model, or a disk write it does not own.       │
└────────────────────────────────────────────────────────────────────────────┘
      │ Lease (bounded queue, cap = Σ workers)   ▲ Completion (bounded queue)
      ▼                                          │
┌─ Runner threads: one per live DriverWorker, ≤ Σ [drivers] max_workers ─────┐
│  Blocking framed read on its own UDS. `import sqlite3` is a lint error     │
│  in this package. Holds one unit's control payload; blobs by reference.    │
└────────────────────────────────────────────────────────────────────────────┘
      │ seam 4: msgpack/UDS 0600   │ seam 3: HTTP    │ seam 2: job dir   │ seam 1: FFI
      ▼                            ▼                 ▼                   ▼
 DriverWorker processes      Service (vLLM)     Toolchain child    inproc DriverGuard
                              attach-or-spawn   omniweave-target/1  (first-party only)

┌─ Tracer thread ─┐   append-only NDJSON events; bounded queue, DROP-OLDEST, counted
┌─ Watchdog thread ┐  reads a monotonic heartbeat only; faulthandler dump then os._exit(70)
```

**No `asyncio` in `omniweave-core`.** This is a hard call and I will defend it four ways.

1. **The store is the serialization point anyway.** SQLite in WAL mode admits one writer at a time. The
   Conductor's hot path — reap, claim, commit — is inherently serial. An event loop buys nothing on
   the only path that is contended and costs its own scheduling latency on the path that must stay
   well under a millisecond per unit.
2. **Concurrency here is bounded and small.** `Σ max_workers` is 16 under D3's defaults. Sixteen
   threads doing blocking framed reads on sixteen sockets is a correct, debuggable, stack-traceable
   design; sixteen coroutines is the same design with a scheduler bolted on.
3. **Every recorded scar is async-shaped.** graphrag's sync cache facade opens
   `asyncio.new_event_loop()` per LLM call *and raises inside a thread that already has a running
   loop*; its rate limiter busy-waits with `time.sleep` under a held lock, called from async, burning
   a core per blocked worker and stalling the loop (mine-runtime §2.5, §2.6, §2.12 #8–9). The digest
   names both "do not copy". Neither is expressible in this model.
4. **D1 puts `import omniweave_core` on the per-turn hook path with an 80 ms budget and gate G10.**
   `import asyncio` alone pulls `selectors`, `socket`, `concurrent.futures`, `contextvars` and the
   coroutine machinery. A hook that runs on every tool call must not pay for a scheduler it will never
   start.

**Where each form of parallelism actually lives:**

| Work shape | Mechanism | Bound | Why not the others |
|---|---|---|---|
| Driver execution (parse, derive, embed, compile) | **OS process** (D3 `subproc`) | `[drivers] max_workers` per cost class | A segfaulting C parser, a CUDA OOM and a 4M-cell XLSX are one row each, not a dead run |
| Blocking on a Service (HTTP to vLLM) | **Runner thread** waiting on the worker's socket | per-Service `max_inflight` | The wait is inside the worker process; the runner thread is a pipe reader |
| Store writes | **Conductor thread only** | 1 | I19; also closes the `sqlite3` cross-thread bug class outright |
| Event export | **Tracer thread**, drop-oldest | queue 64k | Blocking the Conductor on a log write is how codegraph got 25 minutes of unanswerable "is it alive" |
| `inproc` first-party drivers | Conductor's dispatch, **concurrency 1 per GIL-bound driver** | see below | D1's own recorded risk |

★ **The `inproc` bulk rule, which follows directly from a D1 risk nobody has costed.** D1 states:
*"`anydoc/python/src/document.rs` states 'converted eagerly into Python objects', and `py.detach`
covers the Rust decode but **not** the marshal, so the GIL is held for a duration proportional to
document size."* In-process office parse therefore does **not** scale across threads, and
`[drivers.inproc] = ["parse.doc.anydoc", …]` buys latency on the one-document CLI path (anydoc's
measured 4.4 ms median against a 200–800 ms cold worker spawn) while buying **nothing** on the bulk
path. So: **the planner forces `subproc` for every driver when
`plan.units > runtime.inproc_bulk_threshold` (default 64)**, recorded as a `degradations[]` entry of
kind `isolation_tightened`. This needs no new machinery — D3 already rules that *"Isolation … is
declared as a need by the card; decided by the host, which may only tighten."* It is the cheapest
scaling decision in this document.

### 1.2 The job model: two-level planning, because 100k documents will not fit

D2 settled the unit: `(unit_uri, unit_part=page)` for parse, `(unit_uri, unit_part='')` for
document-level structure. D4 settled that a 4,000-page PDF is 4,000 parts and that
`work.decision_id NOT NULL` makes the planner the sole producer of work rows.

**The arithmetic nobody has done.** A `work` row with its indexes costs roughly 250 B.

| corpus | parts | `work` bytes | verdict |
|---|---|---|---|
| 100k documents × 20 pages | 2.0 M | ~500 MB | tolerable, and *pure overhead* before a byte is parsed |
| 100k documents × 300 pages (legal discovery) | 30 M | ~7.5 GB | the work table now dwarfs most corpora's text |

Eagerly materialising every part row before the first parse is therefore wrong, and it is also
**semantically** wrong: you cannot know a PDF's page count without opening it, so an eager plan is a
plan built on a guess.

**Two-level planning.**

1. **Discovery** (the `acquire` port) streams `UnitRef`s. The planner writes one **document row** per
   unit — `work(unit_uri, unit_part='', operator='plan.expand', …)` — in 512-row transactions. 100k
   documents ≈ 30 MB. Discovery is a generator and never materialises a list.
2. **Plan expansion is an ordinary operator.** Claiming a `plan.expand` row opens the document far
   enough to learn `part_count` (a `sniff` plus a container probe, never a full parse), writes that
   one document's part rows in one transaction, and completes.
3. **Backpressure pauses the producer at a safe boundary and never drops work** — the WAL valve's
   correct terminal mode. Expansion stops at `queue_high_water` (50k claimable rows) and resumes at
   `queue_low_water` (25k). Discovery and expansion both block on a condition variable; nothing is
   discarded and nothing is buffered in RAM.

Consequence, stated honestly: **`ow ingest --dry-run` cannot price a corpus exactly**, because part
counts are unknown until expansion. It prices from a per-format sampled estimate over the first
`min(512, 1%)` documents and prints the estimate **with its sample size and a 90% interval**, plus the
exact cost of the sample. graphrag ships `--dry-run` on `index` and not on `update`, which is exactly
backwards; we ship it on both, and we label its error bar rather than implying precision.

### 1.3 Claim, lease, generation, and the one transaction

Inherited verbatim from mine-runtime §7.3.3 / §7.8.1 and unchanged: the `UPDATE … RETURNING` claim,
`claimed_by = (host, pid, process_create_time)`, lease-not-lock with one warned extension for a live
holder, `attempts_total < 5` in the claim predicate, `priority` actually ordered by, and the commit
predicate `WHERE id=:id AND claimed_gen=:gen AND status='claimed'` so a superseded result affects zero
rows and rolls back.

Three additions that are D6's own.

**(a) The store's clock, not the worker's.** Lease expiry, `retry_after` and reservation expiry are
evaluated against `unixepoch('subsec') * 1000` computed **inside** the claim/reap SQL, never against a
worker's `time.time()`. Under T3 two hosts with 400 ms of NTP skew otherwise reap each other's live
leases. Durations stay `monotonic_ns()` deltas; generations stay integers; wall clock is for humans.

**(b) The SQLite < 3.35 fallback is a first-class path, not a degradation.** D1 requires it (*"the
claim protocol ships a `BEGIN IMMEDIATE` + `UPDATE` + `SELECT` fallback"*). Both paths run in CI on
every build under a 16-process hammer test that claims 100k rows and asserts every id appears exactly
once. A path that only executes on enterprise LTS is a path that is broken on enterprise LTS.

**(c) One transaction per unit, and no second way to write.**

```
Store.complete(row_id, claimed_gen, result, *, blocks, deps, spend, reservations) -> bool
```

commits atomically: the derived rows (or the `doc.gen` bump, §1.6), the `work` row transition, the
`dep` rows, the `budget_reservation` state changes, the `route_spend` row and the
`driver_observation` counters. `conn.commit()` outside `omniweave_core/store/sqlite.py` is a semgrep
failure. If these could commit separately a crash between them yields either a `done` row with no
output (a silent hole) or output with a `pending` row (duplicate work, and without I2 duplicate rows).

### 1.4 Admission, backpressure, and the three batching sites

**Admission is three independent semaphores, all of which must admit:**

```
class_sem[cost_class]      <= [budget] max_inflight[cost_class]           (D1)
worker_sem[cost_class]     <= [drivers] max_workers[cost_class]           (D3)
service_sem[service_name]  <= min(handle.capacity(), [services.<n>] max_inflight)
```

plus `max_queue_depth` on the producer. A denial is never a failure: a `LOCAL_COMPUTE` denial is a
queue decision (the row stays claimable); a `BILLED_API` denial from the **budget ledger** (not the
semaphore) is `DEFERRED_BUDGET` with a pending-cost record.

**Three batching sites.**

| # | Where | Window / cap | Formed by |
|---|---|---|---|
| **B1** | One `INVOKE` frame to one DriverWorker (D3) | `batch_max_units` from the card; coalescing window `batch_wait_ms = 5` | The Conductor drains claimed rows sharing a `(driver_id, config_digest)` from its dispatch buffer |
| **B2** | Server-side coalescing inside a Service | `[services.<n>] batch_wait_ms`, `max_batch`; bucketed by any parameter that cannot share one forward pass (surya's threshold bucketing) | The model server, across **all** clients and **all** runs |
| **B3** | Store writes | 512 rows per planner transaction; one transaction per page for `DocSink` (D2) | The Conductor |

★ **THE RULE: a batch never appears in the work table, the spend ledger, the trace, or the failure
taxonomy.** One unit is one work row, one span, one `route_spend` row, one outcome — always. D3 states
this for B1 (*"ONE frame per unit; the batch is invisible to the `work` table"*); I generalise it to
all three, because the moment a batch owns accounting, per-document cost, the shrink guard, per-unit
retry and failure isolation break together. A crashed B1 batch retries **once at `batch = 1`** to
localise the poison unit; that one unit becomes `FAILED_PERMANENT{DRIVER_CRASHED}` with the child's
last 4 KiB of stderr attached.

**Cross-document batching falls out for free**, because the claimable index is ordered
`(priority DESC, id)` across the whole table, not per document. Page 7 of document 41,000 and page 2
of document 41,003 land in the same `INVOKE` if they route to the same driver. That is the answer to
"batching across documents to keep a GPU fed", and it required no batcher.

### 1.5 Services: one engine, many heads, and a pull-based refill

D3: a Service is *"a host-managed shared resource a Driver requests by name through
`io.service(name)` — attach-or-spawn lifecycle, no unit, no card, never routed."* D1 seam S3 allows
attach-or-spawn HTTP for GPU VLMs only. surya's `SuryaInferenceManager` + `inference/backends/spawn.py`
+ `common/batch_service/` is the reference shape and is taken essentially whole:

- Sentinel `$OMNIWEAVE_HOME/services/<name>@<config_digest>.json` = `{port, pid, model_id, started_ns}`,
  with a sibling `.lock` and `.log`.
- **Unlocked healthy fast path** → probe `/health` → `GET /v1/models` → **refuse to attach if the model
  id differs from the expected id**. The fast path *never mutates the sentinel*: surya's comment gives
  the reason and it is a real race — an unlocked waiter deleting a sentinel during another process's
  mid-spawn model load will spawn a second 7B engine on the same GPU.
- Locked path (`FileLock`, 120 s) owns **all** sentinel deletion and replacement; re-check inside the
  lock; detached spawn; `atexit` cleanup registered **only in the spawning process**.
- Shutdown: SIGTERM, poll `os.kill(pid, 0)` 20× at 0.5 s, then SIGKILL with a warning.
- **Every spawn failure carries the tail of the server's own log.** This is the single thing that makes
  a spawned-server architecture debuggable at all.
- `keep_alive` (default `false` in CI, `true` interactively) so a second run attaches instead of
  paying a 30–120 s 7B cold load.

**One engine, many heads.** `ServiceRegistry` is keyed `(name, config_digest)` and yields one
`ServiceHandle` per unique config, shared by every DriverWorker in the run (D1's `Registry` `shared`
scope, whose lifetime is the run, not the process). N thin predictor heads — layout, recognition,
table-rec, a different prompt version — hold no model and share one engine. That is surya's stated
rationale verbatim: *"there's no benefit to more than one layout model on a host, and N in-process
copies thrash the CPU/GPU."*

**Keeping the GPU fed is a pull, not a push.**

```python
def refill(self) -> None:
    for svc in self.services.live():
        target = min(svc.capacity(),                        # server-reported
                     cfg.services[svc.name].max_inflight,   # operator ceiling
                     self.budget.headroom_units(svc.cost_class))
        while svc.inflight < target:
            lease = self.claim_one_for(svc)   # claim restricted to drivers bound to svc
            if lease is None:
                break
            self.dispatch(lease)
```

The default `max_inflight` for a vLLM-backed Service is **96**, from surya's own measurement
(`inference/backends/vllm.py:88-92`: **48→96 concurrency = +28%, 96→240 = +5%**,
`MAX_AUTO_PARALLEL = 96` on a B200). Past the knee you buy queueing, not throughput — and queueing
inflates `queued_ms`, the field that exists precisely because *"a contended lock and slow work are
indistinguishable from the outside"*. Note that 96 in-flight requests are served by 4 worker
**processes**; this is exactly why the third ceiling had to exist.

**Service health reuses D3's circuit breaker rather than adding a second one.** Three health failures
in 60 s quarantines every driver bound to that Service for the run, the plan re-routes, and it lands
in `degradations[]`. One mechanism, two subjects.

### 1.6 Checkpoint, resume, generation staging, replay

The `work` table's pending set is the checkpoint; resume re-derives the plan from current inputs and
subtracts what is done; `stale_since` survives a reset. All inherited unchanged.

★ **The hole nobody has closed, and its fix.** D2 makes `DocSink.end_page()` commit **one transaction
per page**, while D3 permits `granularity = "document"` (anydoc is exactly that). So a
document-granularity parse commits N page transactions under **one** work row. A crash after page 40
of 200 leaves 40 committed pages and a `pending` work row; on resume the driver re-pushes pages 1–40
and either duplicates them or trips `block_addr`'s UNIQUE index. Neither is acceptable, and neither
ruling can fix it alone: `DocSink` must commit per page because a 5,000-page document cannot sit in
memory, and a document-granularity card has one work row by definition.

**Fix: generation staging, reusing D2's existing `gen`, inventing nothing.**

- A document-granularity parse writes every page at `staged_gen = doc.gen + 1`.
- Readers resolve a document at its **committed** `gen`, recorded in `doc`. The staged generation is
  invisible; yesterday's citation still resolves throughout.
- The `doc.gen` bump happens **in the completing transaction** — the same one that flips the work row
  to `done`. That transaction is one UPDATE regardless of document size.
- An abandoned staged generation is swept by `ow store gc --abandoned-gens`, which the Conductor also
  runs at startup: deleting the orphaned `page` rows cascades through `block`, `mark`, `cell` and
  `rel` via D2's `ON DELETE CASCADE`.

This makes I21 true — **a document-granularity producer's pages are invisible until its work row is
`done`** — at the cost of one integer column that already exists and one startup sweep.

**Replay.** `ow replay <work_id> [--verify]` re-executes one unit against the recorded `cache_key`,
`resolution_digest`, `policy_digest`, `pricebook_digest`, `read_set_digest`, `producer_id` and a
frozen `Clock`. Sampling is already deterministic (D4 R2: blake2b, never RNG). A card with
`deterministic = true` must produce a **byte-equal** artefact, and CI runs `--verify` over the fixture
corpus every build. A card with `deterministic = false` produces a **diff report** with a normalised
edit distance, never an assertion: a vLLM engine with continuous batching genuinely produces
batch-composition-dependent output, and a gate that pretended otherwise would be a lie.

**Crash injection is a shipped harness, not a thought experiment.** `_chaos` (graphrag's, generalised)
rides the driver config in production builds: `{failure_rate, exception_type, exception_args,
latency_ms}`. Above it sits `ow test crash-matrix`, which runs a fixture ingest N times SIGKILLing the
process at each of the ~30 statement boundaries inside `Store.complete` and asserts, every time, that
the store passes `owcheck` and the pending set is exactly the unfinished work.

### 1.7 The cache: five tiers, one key, three policies

Three of the five "cache layers" the brief asks for **are the store**, and saying so out loud is the
point: a parse-result cache beside the `.owstore` would be D2's "model plus a sync layer" failure one
level down.

| tier | lives in | key | invalidation | budget |
|---|---|---|---|---|
| **T0 blob** — raw bytes, assets, frozen media | `<cache_root>/blobs/ab/cd/<sha256>` | `sha256(raw bytes)` | never; refcounted, GC at refcount 0 ∧ age > 7 d | disk quota; at 90% **refuse, do not evict** |
| **T1 store** — parse + derive results | `.owstore` rows (`doc`, `page`, `block`, …) | `work.cache_key` + `(doc_key, gen)` | by `work` identity — a `cache_key` mismatch resets the row to `pending` | none: it *is* the corpus |
| **T2 call** — LLM / VLM / embed responses | `<cache_root>/call/<config_digest>/ab/cd/<sha>.mp` | `sha256_canonical(request envelope)` | **never swept**; pruned by liveness only | reported, never auto-deleted |
| **T3 render** — page images | D2's `page_render` row + a CAS asset | `(doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)` — D2's PK verbatim | LRU on `last_used_ns` against a disk budget | 20 GB default |
| **T4 signal** — routing signals | D4's `route_signal` | `(content_digest, unit_part, signal_key, signal_version)` — D4's PK verbatim | swept **per signal** on `signal_version` change | 2 GB default |

Three policies, chosen by **who pays for a miss** (graphify's rule, generalised to three cost classes):
`FREE ⇒ namespaced by producer identity, old namespaces swept`;
`LOCAL_COMPUTE ⇒ namespaced by producer *and* config, swept by liveness only`;
`BILLED_API ⇒ namespaced by config digest only, never swept`. The growth bound is
**`live units × configurations seen`**, printed by `ow cache stats` in those words. Two hosts with
different prompts sharing one cache root must not each delete the other's entries and re-bill on every
alternation.

**The key.** One function, three groups, canonical JSON, `allow_nan=False`, never `"".join`. Three
amendments are forced by the upstream rulings:

- **`driver_version` is not a key input; `schema_version` alone is** (D3: *"it alone enters the cache
  key so a bug-fix release does not re-bill a `billed_api` cache"*).
- **The `[deps] pins` digest enters the key only when `cost.class == "free"`** (D3, explicitly settling
  mine-runtime open question #4). A tree-sitter or pdfium bump re-derives free artefacts and does not
  re-bill an LLM.
- **`digest_recipe` (D2) enters the key only for operators whose `CONSUMES` includes a block-level
  artifact kind.** D2 rules that a recipe bump *"is serviced by a re-digest pass, never a re-parse"* —
  putting it in every key would re-parse the corpus, which is the exact thing D2 forbids.

Two content-identity rules ride along, both non-negotiable:

- **`content_digest` for a source unit is sha256 over *normalised* bytes.** Per-format normalisers strip
  PDF `/ModDate` + `/ID`, OOXML `cp:revision` / `w:rsid*` / `TotalTime`, Markdown frontmatter (a
  whole-line `^---[ \t]*\r?$` regex, never `startswith("---")` — which also matches `----` rules and
  `--- prose`), and EXIF timestamps. A normaliser that throws falls back to raw bytes and records D2's
  `OW_NORMALIZER_FAILED` in the manifest; it is never a silent pass-through.
- **The racily-clean fastpath is mandatory**: `size == st_size ∧ mtime_ns == st_mtime_ns ∧
  st_mtime_ns + MTIME_GRANULARITY_NS (2e9) <= indexed_at_ns`, with `indexed_at_ns` captured **before**
  the read, staged codegraph's way (stat → hash → parse, each gating the next). An agent writing files
  inside one mtime tick is the actual workload, and codegraph explicitly accepts that blind spot.

**Cache poisoning is now structural, not policed.** Under D3 a Driver has no cache handle at all —
`DriverIO` carries `blobs`, `tmpdir`, deadlines, `service`, `cancelled`, `log`, `progress` and nothing
else. The runner writes cache entries, and only for the claimed unit. graphify's
`cache.put(entries, allowed_units=…)` — the only cache-poisoning control in 22 repos — becomes an
invariant of the type shape rather than a parameter someone can forget to pass.

**Miss policy is the cache's business, not the caller's.** Six clauses: no entry; unparseable ⇒ miss,
counted, **and overwritten on the next success** so it self-heals without a flag; marked partial; fails
the operator's `is_valid_nonempty`; the recorded unit/part does not match the one asked for; from an
older namespace under a legacy allowance ⇒ hit, counted as legacy, reported. Every count lands in the
run manifest, never in `warnings.warn` (filterable, unstructured, invisible under JSON logging).

### 1.8 Incremental invalidation: the cache key cannot do this, and the `dep` table can

**This is the most important section in the document.** A cache key answers *"is this derivation
stale?"*. It cannot answer *"whose answer depended on what changed?"*, and the second set is not
derivable from the first. codegraph measured the consequence on itself: **4.3% of distinct edges
wrong, in both directions, silently, forever until a full rebuild.**

So every derivation records what it read outside its own unit, and the reverse index is the
invalidation query.

```sql
CREATE TABLE dep (
  dependent_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  dep_kind     TEXT    NOT NULL,   -- unit | part | name | policy | service_model
  dep_key      TEXT    NOT NULL,
  dep_digest   TEXT    NOT NULL,   -- the value OBSERVED when the dependent was derived
  PRIMARY KEY (dependent_id, dep_kind, dep_key)
) WITHOUT ROWID;
CREATE INDEX dep_reverse ON dep(dep_kind, dep_key);
```

`dep_kind` is closed:

| kind | `dep_key` | `dep_digest` | the question it answers |
|---|---|---|---|
| `unit` | another document's `canonical_uri` | that unit's `content_digest` | cross-document dedup, citation resolution |
| `part` | `uri#p41` | that part's `content_digest` | a caption resolved against a figure on another page |
| `name` | `sec:4.2`, `fig:3.1`, `cite:Smith2019`, `term:Consideration`, `tbl:A-3` | sha256 over the **sorted definition set** for that name | codegraph's `definitionDelta`, in document vocabulary |
| `policy` | `route:<policy_digest>` | the digest | a policy change invalidates decisions, never artifacts (D4) |
| `service_model` | `vlm.olmocr` | `(model_id, model_rev)` | a model upgrade invalidates exactly what used it |

**Invalidation is one query, not a sweep:**

```sql
SELECT DISTINCT d.dependent_id
FROM dep d JOIN changed c ON c.kind = d.dep_kind AND c.key = d.dep_key
WHERE d.dep_digest <> c.new_digest;
```

The `name` kind is what makes "a new document defines Figure 3.2, so 40 dangling references across 12
other documents now resolve" a **bounded query** rather than a corpus rebuild. A body-only edit
produces an empty definition delta and costs nothing, which is the common case.

**Write amplification is bounded by construction.** Dep granularity is the *unit*, never the block: a
derive operator reading 500 blocks from one other document writes **one** dep row. Budget: ≤ 8 dep rows
per unit at p95, gated in CI on the fixture corpus. An operator whose dep set exceeds
`MAX_DEPS_PER_UNIT = 256` must instead declare a **corpus-slice** dependency
(`dep_kind='name', dep_key='slice:<selector>'`) — coarser, always safe, and the honest answer for an
operator that genuinely reads the world.

**When the key and the dep table disagree, stale wins**, and the direction of the resulting work
depends on cost class: a `FREE` operator re-derives immediately; a `BILLED_API` operator is enqueued
as `DEFERRED_BUDGET` with a `needs_upgrade` pending-cost record. Re-running a *cheaper* rung to
"comply" spends money to obtain a worse answer — D4's rule, applied to invalidation.

**The enforcer is a CI job, not a review.** `test_incremental_equivalence`: full-index a 300-document
fixture corpus → snapshot every table → apply 40 scripted mutations (edit in place preserving size and
mtime; rename; delete; add a document defining a previously-dangling label; upgrade a driver
`schema_version`; bump a `signal_version`; change a prompt) → incremental-update → **diff every table**
modulo `run_id`, wall timestamps and `block_id` allocation order. This job is the only reason to
believe the `dep` table is complete, and it is why I5 finally has an enforcer instead of a hope.

### 1.9 Cost: durable reservations, and an unbroken attribution chain

D4 owns `Spend` (the seven-unit physical vector), `PriceBook` (the only place money appears),
`CostCard`, `admit()` and `route_spend`. D6 owns **durability** and **attribution**, and D4 left
exactly one hole: `BudgetLedger` is in-memory, so a crash with outstanding reservations leaks headroom
until someone restarts.

```sql
CREATE TABLE budget_reservation (
  reservation_id TEXT PRIMARY KEY,             -- 'res_' || sha256_canonical(identity)[:24]
  run_id      TEXT NOT NULL,
  work_id     INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  decision_id TEXT NOT NULL REFERENCES route_decision(decision_id),
  dim   TEXT NOT NULL CHECK (dim IN
          ('micros','tokens_in','tokens_out','calls','gpu_ms','wall_ms','cpu_ms','bytes_egress')),
  amount INTEGER NOT NULL,                     -- the p95 ceiling (D4's tokens_out_p95_multiple)
  scope  TEXT NOT NULL CHECK (scope IN ('run','unit','operator','provider')),
  claimed_gen INTEGER NOT NULL,
  expires_ms  INTEGER NOT NULL,                -- == the work row's lease_expires
  state  TEXT NOT NULL CHECK (state IN ('held','committed','released'))
) STRICT;
CREATE INDEX res_open   ON budget_reservation(dim, scope)  WHERE state = 'held';
CREATE INDEX res_expiry ON budget_reservation(expires_ms)  WHERE state = 'held';
```

`headroom(dim, scope) = limit − Σ(held) − Σ(committed)` is **computed in SQL**, never cached in a
Python attribute. The reaper that returns expired leases releases expired reservations in the same
transaction, so a SIGKILL costs at most one lease interval of phantom headroom and never leaks.

**The attribution chain, unbroken end to end** — a systems requirement, because "what did this corpus
cost" is the question every pilot asks in month two:

```
block.origin_driver ──┐
block.origin_operator ┤
route_unit_decision ──┼──> route_decision.decision_id ──> route_spend(decision_id, attempt).micros
work.decision_id ─────┘                    ^
                              budget_reservation.decision_id
```

Two self-checks make it a fact rather than a diagram, both asserted at manifest-write time:

- `Σ route_spend.micros WHERE run_id = ?` equals `manifest.cost.billed_micros` **exactly**, to the
  micro.
- Every `work` row reaching `ok`/`ok_partial` has ≥ 1 `route_spend` row, and every `route_spend` row
  joins to exactly one `work` row. A `Sequence` (D4) apportions its session cost across parts by token
  share, and the apportionment must sum to the session total ±1 micro (integer rounding).

**A cache hit costs zero budget and zero tokens, and still reports metrics.** The middleware order is
graphrag's — an ordering, not a set — with `with_budget` as the one new layer, inside the cache and
outside retry:

```
with_logging → with_request_count → with_cache → with_budget → with_retries
  → with_rate_limiting → with_metrics → with_fault_injection → driver
```

Metrics are cached alongside the response and replayed with `was_cache_hit = True`. That is the only
way to compute `cost.would_have_been_micros_if_uncached` when 90% of calls are hits — and without that
number nobody can justify the cache's existence or estimate a cold run.

### 1.10 Observability: structured events in core, OpenTelemetry in `omniweave-serve`

D1 forbids third-party imports in core, so **`opentelemetry-sdk` cannot live there** — and that is the
better architecture anyway. Core emits a stable event stream; the exporter is a separate concern in a
distribution that already carries dependencies.

- **`omniweave_core/events.py`** defines `Event`, `TraceSink` (a Protocol) and a W3C-`traceparent`
  id generator (`os.urandom` + hex — no dependency needed).
- **Default sink**: append-only NDJSON at `<output_root>/runs/<run_id>.events.ndjson`, written by the
  Tracer thread from a bounded 64k queue with **drop-oldest** and an `events_dropped` counter in the
  manifest. Dropping telemetry under pressure is correct; blocking the Conductor on a log write is how
  codegraph burned three 25-minute cycles unable to answer *"is the valve even alive?"*.
- **`omniweave_serve/otel.py`** maps events to OTLP spans. `omniweave-serve` may depend on
  `opentelemetry-sdk`; core may not.
- **Timings are always on and in the manifest**, never behind an env var.

**Span taxonomy — closed, `ow.*`, one span per unit and never per batch:**

```
ow.run                     run_id, config_digest, omniweave_version, roots.*, generation, trigger
├─ ow.discover             units_seen, bytes_seen
├─ ow.plan.expand          unit_uri, parts_created
├─ ow.unit                 unit_uri, unit_part, operator, op_version, decision_id, outcome,
│  │                       failure_class?, queued_ms, ran_ms, cache_hit, cost_micros, peak_rss
│  ├─ ow.cache.lookup      tier, verdict(hit|miss|miss_corrupt|miss_partial|hit_legacy), key
│  ├─ ow.route.evaluate    rule_id, rung, cause, read_set_digest
│  ├─ ow.budget.reserve    dim, amount, admitted|deferred
│  ├─ ow.driver.invoke     driver, driver_version, isolation, batch_index, batch_size
│  │  └─ ow.service.request  service, gen_ai.request.model, gen_ai.usage.input_tokens,
│  │                         gen_ai.usage.output_tokens, attempt, finish_reason
│  └─ ow.store.txn         rows_written, deps_written, wal_bytes_after
├─ ow.toolchain.run        target, node_version, queued_ms, ran_ms, exit
└─ ow.maintain             wal_checkpoint_ms, gc_blobs, gc_gens, indexes_rebuilt
```

`batch_index` and `batch_size` are **attributes on the per-unit driver span**, so a batch is visible
for diagnosis and invisible for accounting — §1.4's rule, expressed in the trace.

**Trace context crosses every seam.** `traceparent` rides in D3's `HELLO` frame, in D1's `job.json` for
a toolchain, and as an HTTP header to a Service. A CI test reconstructs the span tree of a fixture run
and asserts **zero orphan spans**.

**Sampling.** Head-based at 1.0 while `plan.units < 1000`; above that, tail-based: keep every unit
whose outcome is not `ok`/`skipped_cached`, plus a deterministic 1% of the rest via
`blake2b(unit_uri‖part‖run_id) % 100 == 0`. Never RNG — D4's R2 applies to the tracer too, or two
processes disagree about what was sampled.

### 1.11 Store hygiene at ingest scale

Inherited and non-negotiable: codegraph's pragma order (`busy_timeout` **first**, or a contended open
crashes, #238), `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`,
`mmap_size=268435456`; heal-on-open for an oversized WAL (**25.6 GB observed leaked** across SIGKILLed
sessions); the WAL valve with a **proportional** threshold `clamp(dbSize/4, 256 MB, 2 GB)` and a
**futility latch** (2 consecutive give-ups ⇒ disable 60 s ⇒ degrade to un-valved), because the valve
itself once produced **22 GB of WAL and an exit-137 OOM at an envelope the un-valved build survived**;
`connect_readonly`'s ladder (`mode=ro` when a WAL sidecar exists, `mode=ro&immutable=1` when it does
not) for every reader — hook, CLI, MCP server, second process.

Three D6-specific additions.

**(a) The single-writer question D2 deferred, answered.** D2: *"One writer per `.owstore`. Multi-writer
is D6's problem, not the model's."* The answer is that "one writer" is **per document generation, not
per file**:

- T2 (N runner processes on one host) is correct on WAL SQLite because every write is a short claim or
  complete transaction, serialised by SQLite under `busy_timeout = 5000`. The **claim** is what makes
  it safe: only the process holding a live claim on `(unit_uri, unit_part, operator, op_version)` may
  write rows for that `(doc_ord, gen)`, and the commit predicate rejects a superseded writer.
- The **file-level** lock (jcodemunch's `process_locks` shape: `O_CREAT|O_EXCL` + JSON metadata +
  `flock` on POSIX + `(pid, create_time)` liveness + `inspect()` without acquiring + `held()` exposing
  **`waited_seconds`** and naming the holder) is taken for exactly three operations: schema migration,
  WAL truncate, and a bulk-load index window. Two named wait budgets, passed per call, never a
  constant: `INTERACTIVE_WAIT = 2 s`, `BATCH_WAIT = 60 s`.

**(b) The bulk-load index window, with one prohibition.** Dropping and recreating indexes took
codegraph's 224k-edge insert from **2.8 s to 1.1 s** with ~0.3 s of recreation. For a 100k-document
ingest the Conductor takes the file lock, drops the **non-UNIQUE** block indexes (`block_read`,
`block_parent`, `block_kind`, `block_cdig`, `block_review`), loads, recreates, releases.
★ **A UNIQUE index may never be dropped in a bulk window.** `block_addr`, `block_cite`, `block_sib`
and `block_identity` *are* the enforcement of invariant I2; dropping them turns `INSERT OR IGNORE`
into a plain `INSERT`, which is codegraph #1034 — byte-identical duplicate rows that inflated counts
and flowed into callers. Recreation is chunked so no single stage exceeds `WATCHDOG_MS / 2` (I15):
four `CREATE INDEX` at ~20 s each against a 60 s watchdog is *"SIGKILLed right after doing the work"*,
the most expensive failure available.

**(c) `done`-row retention.** `done` rows are needed for resume and as the shrink guard's baseline, so
they are not deleted — but at 30 M parts they dominate the table. `ow store compact --before-gen N`
folds `done` rows older than the last successful full reconcile into a `work_done_summary`
`(unit_uri, operator, op_version, cache_key, gen, cost_micros)` row, preserving both uses at ~90 B/row.

---

## 2. Concrete shape

### 2.1 New and amended DDL

```sql
-- ═══ additions to the `work` table (mine-runtime §7.3.1 otherwise UNCHANGED) ═══
ALTER TABLE work ADD COLUMN decision_id TEXT NOT NULL REFERENCES route_decision(decision_id); -- D4
ALTER TABLE work ADD COLUMN service     TEXT;      -- NULL unless this unit needs a Service
ALTER TABLE work ADD COLUMN batch_hint  TEXT;      -- '<driver_id>|<config_digest>' — B1 grouping
ALTER TABLE work ADD COLUMN staged_gen  INTEGER;   -- §1.6; NULL for part-granularity work

-- The Conductor's second hot read: claimable rows bound to ONE service (the refill loop).
CREATE INDEX work_claimable_svc ON work(service, status, retry_after, priority DESC, id)
    WHERE status IN ('pending','failed_transient') AND service IS NOT NULL;
-- B1 batch formation.
CREATE INDEX work_batch ON work(batch_hint, status, id) WHERE status = 'claimed';

-- failure_class domain = D3's FailureClass (13 values) ∪ the runtime's five, closed and
-- append-only in codes.toml (D1 gate G13):
--   UNEXPLAINED_LOSS · OOM · WORKER_DIED · SUPERSEDED · QUARANTINED
-- DEFERRED_BUDGET is an Outcome, NOT a failure_class. Budget exhaustion is never breakage.

-- ═══ the dependency record — the mechanism that makes incremental CORRECT ═══
CREATE TABLE dep (
  dependent_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  dep_kind     TEXT    NOT NULL CHECK (dep_kind IN
                 ('unit','part','name','policy','service_model')),
  dep_key      TEXT    NOT NULL,
  dep_digest   TEXT    NOT NULL,
  PRIMARY KEY (dependent_id, dep_kind, dep_key)
) WITHOUT ROWID;
CREATE INDEX dep_reverse ON dep(dep_kind, dep_key);
-- MAX_DEPS_PER_UNIT = 256. Past it the operator MUST declare dep_kind='name',
-- dep_key='slice:<selector>'. Enforced in Store.complete(), not by review.

-- ═══ durable budget reservations — closes D4's in-memory ledger hole ═══
CREATE TABLE budget_reservation (
  reservation_id TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  work_id     INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  decision_id TEXT NOT NULL REFERENCES route_decision(decision_id),
  dim    TEXT NOT NULL CHECK (dim IN
           ('micros','tokens_in','tokens_out','calls','gpu_ms','wall_ms','cpu_ms','bytes_egress')),
  amount INTEGER NOT NULL,
  scope  TEXT NOT NULL CHECK (scope IN ('run','unit','operator','provider')),
  claimed_gen INTEGER NOT NULL,
  expires_ms  INTEGER NOT NULL,
  state  TEXT NOT NULL CHECK (state IN ('held','committed','released'))
) STRICT;
CREATE INDEX res_open   ON budget_reservation(dim, scope) WHERE state = 'held';
CREATE INDEX res_expiry ON budget_reservation(expires_ms)  WHERE state = 'held';

-- ═══ the run row (the manifest's durable half; the JSON is a projection of it) ═══
CREATE TABLE run (
  run_id TEXT PRIMARY KEY,
  generation INTEGER NOT NULL,                 -- monotonic INTEGER, never a clock
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  config_digest TEXT NOT NULL, policy_digest TEXT NOT NULL, pricebook_digest TEXT NOT NULL,
  omniweave_version TEXT NOT NULL, lock_digest TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('cli','hook','upstream','watch')),
  needs_full_scan INTEGER NOT NULL DEFAULT 0,  -- the latch; cleared only by a full reconcile
  events_dropped  INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('running','ok','partial','failed','abandoned'))
) STRICT;

-- ═══ service lifecycle, for `ow services status` and cross-run attach diagnosis ═══
CREATE TABLE service_observation (
  run_id TEXT NOT NULL, name TEXT NOT NULL, config_digest TEXT NOT NULL,
  model_id TEXT NOT NULL, model_rev TEXT,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('attached','spawned','failed','quarantined')),
  requests INTEGER NOT NULL DEFAULT 0, gpu_ms_total INTEGER NOT NULL DEFAULT 0,
  health_failures INTEGER NOT NULL DEFAULT 0, peak_inflight INTEGER NOT NULL DEFAULT 0,
  spawn_ms INTEGER, log_tail TEXT,             -- the server's OWN log tail on a failure
  PRIMARY KEY (run_id, name, config_digest)
) STRICT;
```

### 2.2 The core scheduling types

```python
# ══ omniweave_core/operator.py — D2's Producer IS this type; D2's field names verbatim ══
@dataclass(frozen=True, slots=True)
class OperatorIdentity:                 # == omniweave_core.model.Producer
    operator: str                       # registry key, "parse.pdf.pdfium"
    op_version: str                     # str(schema_version); work.op_version = int(this)
    code_fingerprint: str               # sha256(operator module source)[:12] — NEVER a pkg lookup
    model_id: str | None = None
    model_rev: str | None = None        # exact sha; "main" is a lint error (D2)
    runtime: str | None = None
    runtime_version: str | None = None
    prompt_fp: str | None = None        # CRLF→LF, trailing ws stripped, THEN hashed
    options_digest: bytes = b""         # == config_digest, as bytes

# ══ omniweave_core/sched.py ══
@dataclass(frozen=True, slots=True)
class Lease:
    work_id: int
    unit: UnitRef                       # (uri, content_digest, part)
    identity: OperatorIdentity
    decision_id: str
    candidate: "Candidate"              # D3: card + effective_config + config_digest + isolation
    cache_key: str
    claimed_gen: int
    lease_expires_ms: int
    reservations: tuple[str, ...]       # reservation_ids held for this unit
    batch_hint: str
    service: str | None

@dataclass(frozen=True, slots=True)
class Dep:
    kind: Literal["unit", "part", "name", "policy", "service_model"]
    key: str
    digest: str

@dataclass(frozen=True, slots=True)
class Completion:
    lease: Lease
    result: StepResult                  # mine-runtime §7.1.2, UNCHANGED
    deps: tuple[Dep, ...]
    spend: "Spend"                      # D4's seven-vector
    blocks_written: int
    staged_gen: int | None

class Admission:
    """Three independent semaphores; ALL must admit. A denial is never a failure."""
    __slots__ = ("_class_sem", "_worker_sem", "_service_sem", "_hwm", "_lwm")
    def try_admit(self, lease: Lease) -> "Admitted | Backpressure": ...
    def release(self, lease: Lease) -> None: ...
    def producer_should_pause(self, claimable: int) -> bool: ...   # hysteresis 50k / 25k

class Conductor:
    """The ONLY thread in this process that touches sqlite3. ~600 lines."""
    def tick(self) -> "TickReport":
        self._heartbeat()                       # watchdog liveness, monotonic_ns
        self._reap()                            # expired leases AND reservations, ONE txn
        self._expand_plan_if_under_lwm()
        self._refill_services()                 # pull-based, per-service in-flight target
        for lease in self._claim(self._batch_size()):
            self._dispatch(lease)               # bounded queue -> a Runner thread
        for completion in self._drain_completions():
            self._commit(completion)            # ONE transaction. See I20.
        return report
```

```python
# ══ omniweave_core/cache.py ══
class Tier(StrEnum):
    BLOB = "blob"; STORE = "store"; CALL = "call"; RENDER = "render"; SIGNAL = "signal"

class Verdict(StrEnum):
    HIT = "hit"; MISS = "miss"; MISS_CORRUPT = "miss_corrupt"; MISS_PARTIAL = "miss_partial"
    MISS_EMPTY = "miss_empty"; MISS_UNIT_MISMATCH = "miss_unit_mismatch"; HIT_LEGACY = "hit_legacy"

def cache_key(unit: UnitRef, ident: OperatorIdentity, ctx: RunContext, *,
              cost_class: CostClass, consumes_blocks: bool, deps_digest: str) -> str:
    return sha256_canonical({
        "k": 1,                                                   # KEY RECIPE version
        "unit": {"digest": unit.content_digest,
                 "salt":   unit_salt(unit, ctx.roots),            # walked path rel. source_root
                 "part":   unit.part or ""},
        "op":   {"operator": ident.operator,
                 "schema_version": int(ident.op_version),
                 "code_fingerprint": ident.code_fingerprint,
                 # D3: the [deps] pin digest is a key input ONLY for a free driver.
                 "deps": deps_digest if cost_class is CostClass.FREE else None},
        "cfg":  {"op": ident.options_digest.hex(),
                 "run": ctx.config_digest,
                 # D2: a digest_recipe bump is a RE-DIGEST pass, never a re-parse. So the recipe
                 # is a key input only for operators that CONSUME block-level digests.
                 "digest_recipe": DIGEST_RECIPE if consumes_blocks else None},
    })
# sha256_canonical: sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False.
# NEVER "".join(values) — graphrag's gen_sha512_hash collides ["a","bc"] with ["ab","c"].
# An un-canonicalisable config value is a STARTUP ERROR. There is no str() fallback, ever.

def namespace(ident: OperatorIdentity, cfg_digest: str, cost_class: CostClass) -> str:
    match cost_class:
        case CostClass.FREE:
            return f"op/{ident.operator}/v{ident.op_version}-c{ident.code_fingerprint}/"
        case CostClass.LOCAL_COMPUTE:
            return (f"op/{ident.operator}/v{ident.op_version}-c{ident.code_fingerprint}/"
                    f"cfg/{cfg_digest}/")
        case CostClass.BILLED_API:
            return f"cfg/{cfg_digest}/"                            # NEVER swept
```

```python
# ══ omniweave_core/modelserver.py — seam S3. surya's shape, verbatim in structure. ══
@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str; backend: str; model_id: str
    external_url: str | None; autostart: bool; keep_alive: bool
    startup_timeout_s: int; request_timeout_s: int
    max_inflight: int; batch_wait_ms: int; max_batch: int
    config_digest: str

class ServiceHandle(Protocol):
    def capacity(self) -> int: ...          # server-reported concurrency ceiling
    @property
    def inflight(self) -> int: ...
    def base_url(self) -> str: ...
    def health(self) -> "Health": ...
    def stop(self) -> None: ...

def attach_or_spawn(spec: ServiceSpec) -> ServiceHandle:
    """0. external_url pinned -> probe /health; GET /v1/models; REFUSE on model-id mismatch.
       1. UNLOCKED sentinel fast path: read, probe, verify model id, attach.
          This path MUST NOT mutate the sentinel. An unlocked waiter deleting a sentinel during
          another process's mid-spawn model load spawns a SECOND 7B engine on the same GPU.
       2. not autostart -> SpawnError naming `ow services start <name>`.
       3. FileLock(120 s) -> re-check inside the lock -> detached spawn -> write sentinel
          -> atexit cleanup registered ONLY in the spawning process.
       Shutdown: SIGTERM, poll os.kill(pid, 0) 20x at 0.5 s, then SIGKILL with a WARNING.
       EVERY SpawnError carries the tail of the server's own log."""
```

```python
# ══ omniweave_core/events.py — stdlib only. OTel lives in omniweave-serve. ══
@dataclass(frozen=True, slots=True)
class Event:
    ts_wall_ns: int; ts_mono_ns: int
    run_id: str; trace_id: str; span_id: str; parent_span_id: str | None
    name: str                               # "ow.unit", "ow.driver.invoke", … CLOSED vocabulary
    kind: Literal["start", "end", "point"]
    attrs: Mapping[str, Scalar]

class TraceSink(Protocol):
    def emit(self, e: Event) -> None: ...   # MUST NOT block. Drop-oldest at 64k, counted.
    def flush(self, timeout_ms: int) -> int: ...

def traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"    # W3C. Rides HELLO, job.json, and the HTTP header.
```

### 2.3 Protocol additions (backward-compatible with D3's frame set; no new frame kinds)

```jsonc
// D3 kind 1 HELLO, host -> driver: ONE added key.
{"port":"parse/1","card_schema":1,"card_sha256":"…","driver_id":"parse.pdf.pdfium",
 "effective_config":{},"roots":{"source_ro":"…","tmp":"…"},"blob_base":"…",
 "isolation_granted":{"net":false,"rss_bytes":536870912},
 "traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",   // NEW
 "deadline_ms":120000}

// D3 kind 6 RESULT, driver -> host: the RUNNER adds these; a driver may not set them.
// outcome ∈ {ok, ok_partial} only (D3). confidence, origin_operator, origin_driver,
// driver_schema_v, restriction_bits, was_cache_hit and decision_id are RUNNER-SET, so a
// driver cannot forge a cache hit, a budget deferral, its provenance, or a licence bit.
```

### 2.4 Config — `[runtime]`, `[services.*]`, `[cache]`, `[trace]`

D1's `[budget] max_inflight` and D3's `[drivers] max_workers` are kept **verbatim under their existing
keys**. `[runtime]` adds only what neither can express.

```toml
[runtime]
queue_high_water      = 50000    # claimable rows; the planner pauses here
queue_low_water       = 25000    # …and resumes here. Hysteresis, never a single threshold.
plan_expand_batch     = 512      # rows per planner transaction
inproc_bulk_threshold = 64       # > this many units => isolation TIGHTENED to subproc (§1.1)
lease_ms              = 120000
lease_extend_ms       = 60000    # ONE warned extension for a LIVE holder. Never a steal.
watchdog_ms           = 60000    # no synchronous stage may exceed watchdog_ms / 2   (I15)
yield_interval        = 1000     # at the TOP of the loop body, so `continue` still yields
batch_wait_ms         = 5        # B1 coalescing window
reap_interval_ms      = 5000
interactive_wait_ms   = 2000     # named wait budgets, passed per call, never a constant
batch_wait_lock_ms    = 60000
max_deps_per_unit     = 256

[services."vlm.olmocr"]
backend           = "vllm"
model_id          = "allenai/olmOCR-7B-…"   # verified via GET /v1/models ON ATTACH
autostart         = true
keep_alive        = true         # a 7B cold load is 30-120 s; a second run must attach
max_inflight      = 96           # surya: 48->96 = +28%, 96->240 = +5%; MAX_AUTO_PARALLEL = 96
batch_wait_ms     = 5            # server-side coalescing across ALL clients
max_batch         = 8
startup_timeout_s = 300
request_timeout_s = 600

[cache]
blob_bytes_max   = 107374182400  # 100 GB. At 90% the blob store REFUSES; it does not evict.
render_bytes_max = 21474836480   # 20 GB, LRU on page_render.last_used_ns
signal_bytes_max = 2147483648    # 2 GB, swept per signal_version
call_bytes_max   = 0             # 0 = unbounded. The BILLED tier is NEVER swept, only reported.
legacy_namespace_allow = false

[trace]
events        = "ndjson"                      # ndjson | none
queue         = 65536                         # drop-oldest past this; counted in the manifest
sample        = { non_ok = 1.0, ok = 0.01 }   # deterministic: blake2b, never RNG
otlp_endpoint = ""                            # honoured by omniweave-serve ONLY
```

### 2.5 Package layout (inside D1's fixed tree — no new distributions)

```
packages/omniweave-core/src/omniweave_core/
  operator.py     OperatorIdentity(==Producer) · StepResult · Outcome · RunContext · Roots
  work.py         WorkRow · FailureClass · claim/complete/reap SQL · the retry ladder
  sched.py        Conductor · RunnerPool · Admission · Lease · Completion · backpressure
  cache.py        cache_key · namespace · Tier · Verdict · miss policy · liveness prune
  deps.py         Dep · record_deps · invalidate(changed) · definition-set digests
  ledger.py       BudgetLedger over budget_reservation · reserve/commit/release · headroom SQL
  events.py       Event · TraceSink · NdjsonSink · traceparent · the CLOSED span vocabulary
  modelserver.py  ServiceSpec · ServiceHandle · attach_or_spawn · ServiceRegistry   (seam S3)
  msgpack.py      NEW (conflict C1): the D3 frame subset, ~250 lines, parity-tested + fuzzed
  jsonschema_flat.py  NEW (conflict C1): the flat-scalar card [config] subset, ~120 lines
  host/
    subproc.py    seam 4: framed msgpack over 0600 UDS / owner-only named pipe; supervisor
    inproc.py     DriverGuard; first-party only; forced to subproc above inproc_bulk_threshold
  store/sqlite.py THE ONLY sqlite3.connect · pragmas · heal-on-open · WAL valve · bulk window
  locks.py        process_locks shape: O_CREAT|O_EXCL + flock + (pid, create_time) + inspect()
packages/omniweave/src/omniweave/plan/
  discover.py     streaming acquire; never materialises a list
  expand.py       the plan.expand operator; part rows per document, gated by the high-water mark
  resume.py       re-derive the plan, subtract what is done; keep stale_since
  manifest.py     the run-manifest projection + the two cost self-checks
packages/omniweave-serve/src/omniweave_serve/
  otel.py         Event -> OTLP span mapping. The ONLY place opentelemetry may be imported.
tools/gate_no_asyncio.py     G17
tools/gate_one_txn.py        G18 (semgrep: no conn.commit() outside store/sqlite.py)
fixtures/incremental/        300-doc corpus + 40 scripted mutations for the equivalence job
```

### 2.6 CLI

```
ow ingest <path…> [--dry-run] [--profile fast|balanced|thorough] [--max-rung PAGE]
ow queue status                  # SELECT status, count(*) GROUP BY status — no counter row
ow queue reset --failed-transient [--older-than 7d]
ow run show <run_id> | ow run manifest <run_id> | ow run abandon <run_id>
ow deps of <uri>                 # what this unit read
ow deps rdeps name fig:3.1       # who would be invalidated — the reverse index, exposed
ow cache stats                   # per tier: entries, bytes, hits, misses, legacy, corrupt,
                                 # and the growth bound as a sentence: live units x configs seen
ow cache prune --tier render --to 10G
ow cache verify --tier call --sample 1000
ow replay <work_id> [--verify]
ow services status | ow services stop <name> | ow services start <name>
ow store heal | ow store compact --before-gen N | ow store gc --abandoned-gens
ow trace tail | ow trace tree <run_id>
ow test crash-matrix             # SIGKILL at every statement boundary in Store.complete
```

---

## 3. Invariants I19–I31, and how each is enforced

D3 rules that D6 keeps **I1–I18 unchanged**. These are additional.

| # | Invariant | Enforced by |
|---|---|---|
| **I19** | Exactly one thread per process holds a `sqlite3.Connection`. | `store/sqlite.py` records `threading.get_ident()` at connect and asserts on every call; `check_same_thread` left at its default `True`; a lint rule bans `import sqlite3` outside `omniweave_core/store/`; a test spawns 16 runner threads and asserts every store call from them raises |
| **I20** | A unit's derived rows, work transition, `dep` rows, reservation commit and `route_spend` row commit in ONE transaction. | `Store.complete()` is the only mutation entry point; semgrep gate G18 bans `conn.commit()` elsewhere; `ow test crash-matrix` SIGKILLs at every statement boundary and asserts `owcheck` passes and the pending set is exactly the unfinished work |
| **I21** | A document-granularity producer's pages are invisible until its work row is `done`. | Writes go to `staged_gen = doc.gen + 1`; readers filter on the committed `doc.gen`; the bump is in the completing transaction; a test kills mid-document and asserts `Doc` still resolves the previous generation and the staged one is swept at startup |
| **I22** | No unit is ever claimed twice, on either SQLite path. | `UPDATE … RETURNING` and the `BEGIN IMMEDIATE` + `UPDATE` + `SELECT` fallback are both exercised in CI by a 16-process hammer claiming 100k rows; the test asserts each id appears exactly once |
| **I23** | A superseded result writes nothing. | Commit predicate `WHERE id=:id AND claimed_gen=:gen AND status='claimed'`; zero rows ⇒ rollback; a test bumps `ctx.generation` mid-flight and asserts zero rows written and `CANCELLED` recorded |
| **I24** | Budget headroom is never leaked by a crash. | Reservations are durable rows reaped with leases in one transaction; `headroom()` is computed in SQL and never cached in an attribute; a SIGKILL test asserts headroom returns after `lease_ms` |
| **I25** | Every micro spent is attributable to exactly one `(unit, part, decision, attempt)`. | Manifest-write self-check `Σ route_spend.micros == cost.billed_micros`, exactly; every `ok`/`ok_partial` work row has ≥1 spend row and every spend row joins to exactly one work row; a `Sequence` apportionment must sum to the session total ±1 micro |
| **I26** | Batching is invisible to the work table, the spend ledger, the trace and the failure taxonomy. | One `RESULT` per unit (D3); `batch_index`/`batch_size` are span *attributes*, never rows; a test invokes with `batch = 32` and asserts 32 work transitions, 32 spend rows, 32 `ow.unit` spans, and after a poison unit exactly one `FAILED_PERMANENT` |
| **I27** | A cache hit consumes zero budget and zero provider tokens, and still reports metrics. | `with_cache` outside `with_budget`; metrics replayed with `was_cache_hit = True`; a test asserts the ledger is byte-unchanged across a hit while `would_have_been_micros` is non-zero |
| **I28** | A derivation records every input it read outside its own unit. | The `dep` table; cross-unit reads go only through `DeriveIO.read_unit()` / `read_name()`, which append to the dep log (D4's `Evidence.read()` discipline one level up); `Store.complete()` refuses more than `MAX_DEPS_PER_UNIT` without a slice declaration; **the real enforcer is the incremental-vs-full equivalence CI job** |
| **I29** | Trace context reaches every seam and the span tree has no orphans. | `traceparent` in `HELLO`, in `job.json`, and as an HTTP header to a Service; a CI test reconstructs the tree from a fixture run and asserts zero orphan spans and no parentless span except `ow.run` |
| **I30** | No unattended path exceeds its declared memory envelope without a named refusal. | `RLIMIT_AS` (Linux) / `RLIMIT_DATA` (macOS — `RLIMIT_AS` is unreliable under Apple's libmalloc) / Job Object (Windows) per subproc worker from `[isolation] memory_mb`; `peak_rss_bytes` in `StepMetrics`; a breach is an `OW-P-nnn` naming which knob would need raising, never an OOM-killer visit |
| **I31** | Every governor has a futility latch, and every degradation is visible within one heartbeat. | 2 consecutive give-ups ⇒ 60 s disable ⇒ degrade to the un-governed behaviour; each governor logs an `armed` line and a heartbeat; `degradations[]` in the manifest and `Freshness.degradations` in every response; a fault-injection test forces the WAL valve, backpressure and the service breaker and asserts all three appear |

Two CI gates, additive to D1's sixteen:

- **G17** — `import omniweave_core` under `-X importtime` loads no `asyncio` and no `selectors`.
- **G18** — semgrep: no `conn.commit()`, no `conn.execute("BEGIN`, and no `sqlite3` import outside
  `omniweave_core/store/`; and no bare `except` around `content_digest`, `config_digest`,
  `code_fingerprint`, `cache_key` or a baseline read (I12).

---

## 4. The 100k-document ingest, with arithmetic

Mixed corpus: 60k office documents, 40k PDFs averaging 20 pages. Two GPU-less runner hosts plus one
box with a single 80 GB GPU. `[drivers] max_workers = {free: 4, local_compute: 4, billed_api: 8}`.

| stage | quantity | rate | wall |
|---|---|---|---|
| Discovery + document rows | 100k rows, 512/txn | ~30 MB written | minutes |
| Plan expansion | 40k PDFs → 800k part rows; office stays document-granular | one sniff per document | bounded by HWM 50k |
| Office parse (`subproc`, forced by `inproc_bulk_threshold`) | 60k docs | anydoc README: **4.4 ms** median across 14 formats, 100 documents | ≈ 264 s of driver time ÷ 4 workers ≈ **1.1 min**; worker spawn amortised over `worker_idle_ttl_s = 300` |
| PDF text-layer parse | 800k parts | D3's card: p50 **210 ms** for `parse.pdf.native` | 168,000 s ÷ 4 ≈ **11.7 h** — the dominant CPU cost, and the reason T2 exists |
| Routing signals | 800k parts, FREE tier only on clean pages | ~2 ms/part (D4) | ≈ 27 min, cached in `route_signal` |
| VLM escalation | 800k × 18.8% (D4's rate) ≈ **150k page calls** | olmocr p50 **2.4 s**, 96 in flight | 150k × 2.4 ÷ 96 ≈ **1.04 h of GPU** |
| Blocks written | 800k parts × 90 blocks/page (D2's 60–120 envelope) + office | | ≈ **80 M blocks**; D2: 10 M ≈ 3.3 GB ⇒ **≈ 26 GB `.owstore`** |
| Work table | 900k live rows ≈ 500 MB; ~90 B/row after compaction | | |
| Decision ledger | D4: ~1 GB per million parts | | **≈ 0.9 GB**, ~0.3 GB after the 30-day evidence sweep |
| Runtime overhead | one claim UPDATE + one commit + one key + one event per unit | **budgeted ≤ 0.3 ms/unit**, CI-gated | 900k × 0.3 ms ≈ **4.5 min** total |

Read the last row carefully, because it is the design's own bill: 0.3 ms of runtime overhead is **7% of
an anydoc office document (4.4 ms)** and **0.012% of an olmocr page (2.4 s)**. The tax is highest
exactly where the work is cheapest. That is the honest shape of a durable, per-unit, transactional
scheduler, and it is why `plan.expand` keeps office documents at document granularity rather than
splitting them into pages: splitting a 4.4 ms document into 12 page rows would make the runtime cost
more than the parse.

**Memory.** Conductor steady state ≤ 250 MB (64 MB page cache, bounded queues, no document ever in its
address space). Each runner thread holds one unit's control payload; anything over D3's
`INLINE_MAX = 262144` travels as a blob reference. Subproc workers are capped at `[isolation]
memory_mb`. The ingest therefore has a **declared** RSS envelope
(`250 MB + Σ workers × memory_mb`, default ≈ 8.5 GB) rather than an emergent one.

**The finding that matters for D5.** 26 GB is a comfortable single-file SQLite; the 300-page legal
variant (100k × 300 = 30 M parts, ~2.7 B blocks) is **not**, and neither is its 7.5 GB work table. This
design's honest ceiling on one host is on the order of **10^7 parts**; past that the store backend must
be Postgres and the claim becomes `SELECT … FOR UPDATE SKIP LOCKED`. Nothing else in the runtime
changes, which is the entire point of making the store the distribution boundary.

---

## 5. What it costs

**Engineering, for two people:**

| component | wk |
|---|---|
| `work` table, claim/lease/reap, failure taxonomy, retry ladder, both SQLite paths | 2.0 |
| Conductor, RunnerPool, Admission, backpressure, the thread model | 2.5 |
| `cache.py`: key, five tiers, miss policy, namespaces, liveness prune, `ow cache stats` | 2.0 |
| `deps.py` + the incremental-vs-full equivalence harness and its 300-document fixture corpus | 2.5 |
| `ledger.py`: durable reservations, headroom SQL, the two manifest self-checks | 1.5 |
| `modelserver.py`: attach-or-spawn, registry, capacity refill, the service breaker | 2.0 |
| `events.py` + NDJSON sink + `omniweave_serve/otel.py` + the orphan-span test | 1.5 |
| Resume, generation staging, `ow test crash-matrix`, `ow replay --verify` | 2.0 |
| WAL valve, heal-on-open, bulk-load window, futility latches, `process_locks` | 1.5 |
| `msgpack.py` + `jsonschema_flat.py` + parity tests + decoder fuzz (conflict C1) | 1.0 |
| Windows parity: Job Objects, named-pipe DACLs, no `fork`, no `SIGALRM`, `os._exit` timer | 2.0 |
| **Total** | **≈ 20.5 engineer-weeks** |

First user-visible milestone at **week 4**: `ow ingest` over a mixed corpus with `ow queue status`,
crash-resume and a run manifest — before the cache, before services, before the dep table.

**Runtime overhead:** ≤ 0.3 ms/unit, CI-gated against the fixture corpus with a 25% drift tolerance
(the same shape as D1's G10 cold-start gate).

**Memory:** `250 MB + Σ workers × [isolation] memory_mb`, declared rather than emergent.

**Dependency weight:** **zero** new third-party runtime dependencies, at the price of ~370 lines of
core code and two parity suites (conflict C1).

**Operational burden, stated plainly:** an operator acquires four durable artefacts to keep honest —
`pricebook.toml` (D4's), the cache disk budgets, the `[services.*]` block, and the `runs/` retention.
Plus one standing obligation nobody will want: the **incremental-vs-full equivalence job** must stay
green and must stay fast enough that nobody disables it. It is a correctness test wearing the costume
of an integration test, and the day it is marked `xfail` the incremental path becomes quietly wrong
with no symptom for months.

---

## 6. Rationale

**Why the Conductor owns the connection.** Every durability property in this document reduces to "one
transaction per unit", and every corruption story in the mine reduces to two writers who each thought
they were alone. Making a *thread* the writer, rather than a lock, is stronger than a lock because it
is checkable statically: I19 is a lint rule plus an assertion, and no future contributor can quietly
open a second connection in a worker and survive review. It also upgrades D1's *"the only module
permitted to call `sqlite3.connect`"* from a module rule into a module **and** thread rule at zero
cost, which removes the entire `SQLite objects created in a thread can only be used in that same
thread` failure class before anyone meets it.

**Why the dep table is the centrepiece and the cache is not.** Every proposal in this space reaches for
a better cache key, and a cache key is provably insufficient: it is a function of *this* derivation's
inputs, while incremental correctness is a question about *other* derivations' inputs. codegraph paid
4.3% of its distinct edges to learn this, wrong in both directions, silently, until a full rebuild. The
fix is to record the read set at derivation time and index it in reverse — which is exactly the
discipline D4 already applies at the routing layer with `Evidence.read()` and `read_set_digest`. I am
not inventing a mechanism; I am noticing that the mechanism D4 built for routing decisions is the
correct mechanism for derivation dependencies, and applying it one level up under the same rules. The
`name` kind — section numbers, figure labels, defined terms, citation keys, table ids — is codegraph's
`definitionDelta` translated into document vocabulary, and it is what makes cross-document citation
resolution incremental rather than quadratic.

**Why batching is pushed to the edges.** There are exactly two places where batching produces real
throughput — the driver worker's `INVOKE` frame and the model server's coalescing window — and both are
already owned by D3 and by surya's proven design. A third, runtime-level batcher would be the one that
owns units, and the moment a batcher owns units it owns accounting, retry granularity, failure
isolation and the shrink guard along with them. Making the refill loop *pull* from the claimable index
means cross-document batching happens as a side effect of `ORDER BY priority DESC, id` and required no
component at all. The best batcher is the one you did not write.

**Why a per-Service ceiling had to exist.** D1's `max_inflight` and D3's `max_workers` are both real and
both insufficient: 96 concurrent sequences on one vLLM engine served by 4 worker processes is
inexpressible in either. surya measured the knee precisely — 48→96 buys +28%, 96→240 buys +5% — and past
the knee you are buying `queued_ms`, not throughput. A design that cannot express the number the
evidence gives you is a design that will be worked around with an environment variable.

**Why generation staging.** The D2/D3 interaction that produces a torn document-granularity parse is
not hypothetical and has no fix inside either ruling. Staging into `gen + 1` costs one integer column
that D2 already defined for a different reason (re-parse identity) and one startup sweep. Reusing an
existing concept to close a cross-ruling seam is strictly better than adding a journal table or a
`partial` flag, both of which would be a second checkpoint model — exactly what mine-runtime §7.4
forbids and what DataFlow's eight failure modes are made of.

**Why events in core and OTel in serve.** D1's zero-dependency gate is not an inconvenience to route
around; it is the reason `import omniweave_core` can sit on the per-turn hook path at all. And the
separation is better engineering regardless: a stable event schema written to NDJSON is replayable,
greppable, diffable, and survives an exporter outage, while an OTel SDK in the hot path is a background
thread, a gRPC channel and a protobuf runtime on a code path whose budget is 80 ms.

---

## 7. Tradeoffs

1. **No asyncio buys statically-checkable single-writer semantics and costs the ability to hold
   thousands of concurrent in-flight HTTP calls in one process.** With `Σ max_workers` at 16 and
   per-Service in-flight at 96 the ceiling is comfortable; a future BILLED_API workload wanting 2,000
   concurrent hosted calls needs a small async client *inside a worker process*, never in core.
2. **Two-level planning bounds memory and the work table, and costs an exact `--dry-run`.** The estimate
   carries a sample size and an interval instead of a number that looks precise and is not.
3. **The `dep` table costs a write per cross-unit read and buys the only real proof of incremental
   correctness.** Budget ≤ 8 rows/unit at p95; an operator that genuinely reads the world declares a
   coarse slice dependency and over-invalidates on purpose.
4. **One transaction per unit costs one commit per unit (~50–200 µs at `synchronous=NORMAL`) and buys
   crash atomicity with no reconciliation pass anywhere in the system.**
5. **Writing our own MessagePack and flat-schema validator costs ~370 lines and two parity suites, and
   keeps D1's G1 bright line intact.** If the judge relaxes G1 instead, we save the lines and put a C
   extension on the hook path.
6. **Durable reservations cost a row per billable unit and buy a headroom number that survives
   SIGKILL.** A FREE-only run leaves the table empty, so the cost is paid only by runs with money at
   stake.
7. **Forcing `subproc` above 64 units costs the CLI's fast path nothing and costs a bulk run one worker
   spawn per cost class, amortised over 300 s of idle TTL** — while removing a GIL-serialisation cliff
   that would otherwise cap office throughput at roughly one core.
8. **Events are dropped, never blocking.** A saturated tracer loses telemetry and reports how much. The
   alternative — backpressuring the Conductor on a log write — is the failure codegraph shipped.
9. **`done` rows are retained.** Resume and the shrink guard both need them; the compaction verb keeps
   the table sane at 30 M parts at the price of one more verb an operator must know exists.
10. **Thirteen new invariants and two new gates are a real tax on every PR** — roughly 90 s of extra CI,
    plus a crash-matrix job measured in minutes. Each one names a failure a repo in `_collections/`
    actually shipped.

---

## 8. Failure modes — including the inputs that break this

1. **A corpus past ~10^7 parts on one host.** The `.owstore` crosses tens of GB, the work table crosses
   several GB, and single-file SQLite write contention becomes the bottleneck. 100k × 300-page legal
   discovery is exactly this input. The answer is Postgres with `FOR UPDATE SKIP LOCKED` and no operator
   change — but that path is unwritten at v1, and the first customer to hit it will hit it in production.
2. **A wedged Conductor stalls everything.** One thread owning the store is a correctness win and a
   liveness single point of failure: a pathological `CREATE INDEX`, a network-filesystem stall on the
   store file, or a SQLite `busy` storm blocks every runner. Mitigations are the watchdog (the
   `WATCHDOG_MS/2` rule, a `faulthandler` stack dump, then `os._exit(70)`) and every claimed row
   returning to `pending` on lease expiry, so a restart loses at most one lease interval. The failure is
   loud and bounded — and real.
3. **A driver that wedges holding its socket read burns a runner thread until `wall_ms_hard`.** With
   `max_workers[free] = 4`, four such drivers stall the free lane entirely. `progress_ms` catches a
   driver that stops reporting; a driver that reports progress forever and produces nothing does not hit
   `progress_ms` and burns until the hard deadline.
4. **The dep table is only as complete as the operators that write it.** An operator that reads another
   document through some path other than `DeriveIO` records nothing, and incremental silently diverges.
   The equivalence job is the only real defence, and it only covers the mutations someone thought to
   script. This is the most likely place this design is quietly wrong in year two.
5. **`MAX_DEPS_PER_UNIT` degrades to a slice dependency, which over-invalidates.** A cross-document dedup
   operator that legitimately reads 5,000 units declares `slice:*` and is then re-run whenever anything
   changes — correct, and potentially the most expensive operator in the system.
6. **Generation staging leaks disk on repeated crashes.** N SIGKILLs mid-document leave N abandoned
   generations of pages until the startup sweep runs. On a corpus of large documents in a crash loop the
   store can double before anything notices, and a process that never restarts cleanly never sweeps.
7. **The blob store refuses instead of evicting at 90%.** Deliberate — evicting a blob that a
   `quote='verbatim'` block depends on breaks D2's verifiability invariant — but it makes a full disk a
   hard stop for ingest rather than a degradation, and the message had better name the knob.
8. **Replay of a non-deterministic driver proves nothing.** A vLLM engine with continuous batching
   produces batch-composition-dependent output, so `--verify` on a VLM yields a diff report and a number,
   not a verdict. Every replay-based debugging story for the expensive half of the pipeline is therefore
   statistical.
9. **Clock skew is handled for leases and not for humans.** Durations are monotonic and expiries use the
   store's clock, but the manifest's wall timestamps come from whichever host wrote them; under T3 a
   run's timeline can read out of order.
10. **The one input that breaks the whole thing: a single document whose part count is enormous.** A 4M-cell
    XLSX is one document-granularity unit whose `DocSink.end_page()` is one very large transaction (D2
    names this risk itself). The runtime cannot subdivide it, the WAL grows to hold it, and `RLIMIT_AS`
    on the worker turns it into `OW-P-nnn ResourceLimit` rather than an OOM-killer visit — a refusal, not
    a fix. D2's fork trigger and a sub-page commit boundary are the only real answers, and both are out
    of scope here.

---

## 9. Why I reject the alternatives

- **An `asyncio` runtime in core.** It buys concurrency on a path SQLite serialises anyway, puts an event
  loop on a hook import path with an 80 ms budget (D1 G9/G10), and every async artefact in the mine is on
  the do-not-copy list: graphrag's `asyncio.new_event_loop()` per LLM call (which also raises inside a
  thread that already has a loop) and its rate limiter's `time.sleep` under a held lock called from
  async, burning a core per blocked worker. The concurrency this system needs is ≤16 blocking socket
  readers.
- **A `ProcessPoolExecutor` instead of D3's long-lived workers.** A pool re-imports the driver per task in
  the worst case, cannot amortise a model load, gives no per-driver quarantine, and has no protocol — so a
  crashed worker is a `BrokenProcessPool` that kills the pool rather than one row. D3's supervisor is
  strictly better and is already ruled.
- **A step-numbered or JSON-bag checkpoint (DataFlow, graphrag).** DataFlow's `cache_step_{N}.json` has
  eight documented failure modes, its artifacts live outside the checkpoint model and are not
  content-addressed, and its row index is not stable under batching; graphrag's `state: dict[Any, Any]`
  makes `update_clean_state` load-bearing (omitting it crashes at the *end* of a successful run) and makes
  reordering the workflow list a `KeyError` hours in. The pending set is a checkpoint that cannot disagree
  with the work.
- **A separate parse-result cache beside the store.** Three of the five tiers people ask for *are* the
  store, and a second copy of parse output is D2's "model plus a sync layer" failure at the runtime
  level — the same drift that produced graphrag's `deleted_inputs`, computed and consumed nowhere.
- **A better cache key as the incremental mechanism.** Provably insufficient: the key is a function of this
  derivation's inputs; incremental correctness is a question about other derivations' inputs. codegraph
  priced the gap at 4.3% of distinct edges, wrong in both directions, silently.
- **A runtime-level batcher that owns units.** It would own accounting, retry granularity, failure isolation
  and the shrink guard with them. D3 already ruled the batch invisible to the work table; extending that to
  the spend ledger and the trace costs nothing and closes the whole class.
- **A long-lived local scheduler daemon with a loopback control port.** D1 bans it and names why: LEANN's
  `api.py:133` `zmq.REQ` to `tcp://localhost:{port}` with no auth and no CURVE is compute theft from any
  local process, and open-slide needs a 76-line CSRF guard as a *minimum* for a local server that writes
  files. A run-scoped child over a 0600 UDS with a 300 s idle TTL is not a daemon.
- **A single global `max_inflight`.** It cannot simultaneously express 4 worker processes, 96 in-flight GPU
  sequences and 2 concurrent billed API calls, and the number the evidence gives you (surya's 96) would be
  unexpressible. Three ceilings is one per real resource, not one per taste.
- **An in-memory `BudgetLedger` (D4 as written).** A crash with outstanding reservations leaks headroom
  silently, which is the specific failure that makes a budget untrustworthy — and an untrustworthy budget
  gets raised until it stops firing. Thirty lines of DDL and one reaper clause fix it.
- **OpenTelemetry inside `omniweave-core`.** It breaks D1's G1 and G9, adds a background thread and a gRPC
  channel to the hook path, and couples core's release to an SDK's. A stable event schema plus an exporter
  in `omniweave-serve` is strictly more replayable and strictly cheaper.
- **Wall-clock generations, wall-clock lease expiry, and PID-only lease ownership.** codegraph's
  `Date.now()` stamps make a backward NTP step permanently stale or silently evict; jcodemunch #450
  observed two-week-old lock rows resolving to a Chrome renderer and an AMD service. Integers for
  generations, the store's clock for expiry, `(host, pid, process_create_time)` for ownership.
- **Stealing a lease from a live holder on timeout.** codegraph's `STALE_TIMEOUT_MS = 2 min` unlinks locks
  regardless of liveness, so a legitimate 3-minute bulk index loses its lock mid-write. One warned
  extension for a live holder; never a steal.
- **One `--force` flag.** Overrides are named per check — `--allow-unexplained-loss`, `--allow-rebill`,
  `--accept-partial`, `--ignore-cache`, `--allow-abandoned-gen`. *"An override flag whose scope is 'skip
  whatever check just complained' is not an override, it is an off switch."*

---

## 10. Build order — each phase ships something a user runs

1. **P1 (≈4 wk).** `canonical_uri` + `content_digest` + the racily-clean stat index; the `work` table, both
   claim paths, leases, the reaper, the failure taxonomy and retry ladder; the Conductor's tick loop with
   one FREE operator; the run row and manifest. **Ships: `ow ingest` over a mixed corpus, `ow queue
   status`, and Ctrl-C-then-resume that loses nothing.** I19, I20, I22, I23; I6, I7.
2. **P2 (≈4 wk).** `sched.py` in full — Admission's three semaphores, backpressure with hysteresis,
   two-level plan expansion, the subproc host and `msgpack.py`, B1 batch formation, per-driver quarantine.
   **Ships: a 100k-document ingest that does not OOM and does not exceed its declared RSS envelope.** I26,
   I30.
3. **P3 (≈4 wk).** `cache.py`: the five tiers, the three-group key with all three ruling-forced amendments,
   the six-clause miss policy, namespaces and liveness pruning, `ow cache stats`. Then `ledger.py`, the
   middleware stack with `with_budget`, `--dry-run` on ingest *and* update, and `_chaos`. **Ships: a second
   run that is a 90% cache hit and loads zero models.** I24, I25, I27; I8, I12, I13.
4. **P4 (≈4.5 wk).** `deps.py`, the reverse index, `ow deps of` / `ow deps rdeps`, the 300-document fixture
   corpus and the incremental-vs-full equivalence job; generation staging and `ow test crash-matrix`;
   `ow replay --verify`. **Ships: `ow update` you can believe.** I5, I21, I28.
   ★ Deliberately before the watcher — this is the invariant a watcher breaks silently.
5. **P5 (≈3 wk).** `modelserver.py`: attach-or-spawn, the registry, capacity-aware refill, the service
   breaker, `ow services status`. **Ships: many light workers sharing one GPU, and a clean digital document
   that never starts one.** I31.
6. **P6 (≈3 wk).** `events.py`, the NDJSON sink, `omniweave_serve/otel.py`, `ow trace tree`; the WAL valve,
   heal-on-open and the bulk-load window; `ow store compact` / `heal` / `gc`. **Ships: a run you can explain
   to someone whose bill doubled on Tuesday.** I29, I15, I18.
7. **P7 (≈2 wk).** Windows parity as a funded phase, not a discovery: Job Objects instead of `RLIMIT_AS`,
   owner-only named-pipe DACLs instead of a 0600 socket, no `fork`, no `SIGALRM` (a `threading.Timer` plus
   **`os._exit`**, because a Timer thread raising `SystemExit` does not stop the main thread), and
   `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` — never `DETACHED_PROCESS`.
8. **T2/T3.** T2 (N runner processes, one host) is reachable from P2 with no operator change. T3 is Postgres
   with `FOR UPDATE SKIP LOCKED` and blob URIs, built only when a real workload demands it — i.e. when a
   corpus crosses ~10^7 parts.

---

## 11. Open questions

- **Is 0.3 ms/unit of runtime overhead achievable at `synchronous=NORMAL`, and what is the real
  distribution?** Everything in §4 scales off it, and nothing in `_collections/` measures a per-unit
  transactional scheduler. Settled by a benchmark: 1 M synthetic units through the Conductor with a no-op
  operator on {NVMe, spinning disk, SMB mount}, reporting p50/p95/p99 of claim, commit and total. If p95
  exceeds 1 ms the office path must be batched at the store level (B3 widened to N units per transaction),
  which weakens I20 to "one transaction per *batch* of same-operator units" and costs per-unit crash
  atomicity — a trade I would rather make with a number in hand.
- **What is the true p95 of `dep` rows per unit on a real cross-referencing corpus?** The ≤8 budget is an
  estimate. Court filings with dense internal cross-references may blow it, at which point either
  `MAX_DEPS_PER_UNIT` rises (write amplification) or slice dependencies become the norm
  (over-invalidation). Settled by instrumenting `DeriveIO` over a 500-document legal fixture.
- **Does the `name` dep kind need a per-document or a per-corpus namespace?** A section number `4.2` is
  corpus-ambiguous; a defined term is not. Corpus-scoping over-invalidates; document-scoping cannot express
  cross-document citation resolution, which is the whole point. Settled by D7's entity model: if a defined
  term already has a corpus-level surrogate key with an alias set, `name` deps key on that and the ambiguity
  disappears.
- **Should the equivalence job diff the store or diff a canonical export?** Diffing tables directly requires
  normalising `block_id` allocation order, which is exactly the kind of normalisation that can hide a real
  bug. D2 already ships `import(export(store)) == store` and an archive that contains no `block_id`, so
  diffing two `.owdoc` archives may be strictly better. Settled by running both on the fixture corpus and
  counting false positives.
- **Is `keep_alive = true` safe as an interactive default?** A resident 7B engine holds 20–40 GB of VRAM
  after the run exits, which is correct for a developer iterating and hostile on a shared box. Settled by a
  policy decision plus an idle TTL on the server itself, which surya's spawn machinery does not currently
  provide and which we would have to add.
- **Does `route_signal` (D4, FREE) actually need a disk budget, or does `signal_version` sweeping bound
  it?** If a signal's version never changes the namespace never sweeps and the table grows with the corpus.
  Settled by measuring `route_signal` growth over the 100k-document ingest; if it exceeds the 2 GB default
  the sweep needs an LRU component, which makes a FREE cache behave like a LOCAL_COMPUTE one and is worth
  knowing before it ships.
