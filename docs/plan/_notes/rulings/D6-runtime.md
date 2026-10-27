# D6-runtime — Execution runtime: scheduling, concurrency, caching, incremental refresh, observability

## Decision

The runtime is **one `asyncio` Supervisor living in the `omniweave` distribution — never in
`omniweave-core`, which stays synchronous and asyncio-free on the per-turn hook path** — driving a
durable two-table plan (`unit` roster → `work` rows), with **exactly one thread per process holding a
`sqlite3.Connection`** and **exactly one transaction per unit that writes derived rows**. There is no
wave and no checkpoint file: the claimable set is the checkpoint, bounded by a
`queue_high_water`/`queue_low_water` hysteresis rather than by a barrier, and part rows are
materialised by `op.identify` — an ordinary operator — because a document's part count is not knowable
without opening it. Parallelism lives in exactly four places and nowhere else: the loop (IO), the
store thread (writes), D3's `subproc` DriverHost (all driver execution), and the model server
(coalescing). Batching exists at two named sites — the host **Batch** (`dispatch_key`-coherent
`INVOKE`, AIMD-adapted) and server-side **Coalescing** — and is invisible in all four ledgers. The
cache is **five content-addressed layers under one `cache_index` table**, of which the decisive one is
`call`: we cache the *driver's raw response*, never the derived rows, because the store is the parse
memo (D2's "one store, never a model plus a sync layer") and because re-ingesting a corpus into a
second store must not re-bill 116,000 VLM pages. Every config key carries a declared **`semantic` /
`operational`** axis and only the semantic projection enters a cache key — the fix for
`mine-runtime.md` §7.5's whole-`config_digest` defect. Incremental correctness rests not on the cache
key but on a **`dep` reverse index** whose cross-unit rows are supplied three ways (runner-known
inputs, a driver-declared `witness_set`, or a `cohort` merkle for corpus-granularity work that
declares nothing), enforced by an incremental-vs-full equivalence gate that diffs `.owdoc` exports. A
**staged generation** closes the torn document-granularity parse that D2 and D3 jointly create.
Observability is one stdlib NDJSON event stream in core with a closed, byte-diff-gated vocabulary;
OTLP is `ow trace export` in `omniweave-serve`, offline, and a broken exporter cannot break a run.

## Spec

**Substrate.** One `asyncio` event loop in `omniweave/run/supervisor.py`. The four arguments against
asyncio all reduce to one — D1's 80 ms `import omniweave_core` budget and gate G9 — and that argument
is answered by *location*, not by prohibition: core is sync and blocking, the loop lives in the CLI
distribution, and gate **G22** asserts `import omniweave_core -X importtime` loads neither `asyncio`
nor `selectors`. The positive evidence is olmocr, the only pipeline in `_collections/` that has
actually run millions of PDFs: `olmocr/olmocr/pipeline.py:87-88` is two `asyncio.BoundedSemaphore`s —
`pdf_render_max_workers_limit` at `cpu_count-2` and `max_concurrent_requests_limit` — with CPU render
pushed through `asyncio.to_thread` (`:112`). That split (CPU render semaphore ≠ GPU inference
semaphore) is adopted verbatim; at D2's 10.7 MB per decoded 192-DPI A4 page, sharing one semaphore
renders faster than it evicts. Blocking work — the store, framed socket reads, blob writes — runs on
named threads: **the store thread is the only holder of a `sqlite3.Connection` in the process (I19)**,
which upgrades D1's module rule into a module-and-thread rule and deletes the cross-thread-connection
failure class outright.

**Job model.** Discovery streams into a durable `unit` roster (≈220 B/row; 100k documents is 22 MB,
not a Python list) carrying the connector cursor, LDR's acquisition state machine, graphify's
racily-clean stat triple, and `part_count`. `op.identify` then fills `part_count` from the resolved
`parse/1` driver's `sniff()` plus one `INVOKE` under `PartSelector(count_only=True)`, and expansion
writes that one document's part rows in a 512-row transaction. Expansion pauses at `queue_high_water`
(50k claimable) and resumes at `queue_low_water` (25k) — backpressure pauses the producer at a safe
boundary and never drops work. I reject the ecosystem's `wave`: it is a third scheduling noun with its
own table, its own span level and a special part-window path, its benefit is already delivered by the
water mark, and its barrier is precisely where one 10,000-page filing stalls a corpus (its own failure
mode 1). I also reject sweeping `done` rows into `cache_index` as the durable derivation record — that
is two sources of truth for completion, which is the DataFlow failure with better spelling.
`ow store compact` archives `done` rows into `work_done`, preserving exactly what resume and the
shrink guard read.

**Claim and commit.** §7.3.3's protocol unchanged, with the batch axis: the claim is one statement
whose `head` CTE picks the highest-priority claimable row and whose body claims up to
`batch_max_units` rows sharing its `dispatch_key`, so a Batch is one indexed scan and priority
ordering survives. The planner denormalises exactly three facts the hot path must filter and group by
— `driver`, `dispatch_key`, `cost_class` — from the resolved `Candidate`; a join on the claim is not
affordable at ~2,000 transitions/s over a 900k-row table, and one test asserts all three against
`route_decision`. Expiry, `retry_after` and reservation timeouts are evaluated against the **store's**
clock inside the SQL, never a worker's `time.time()`; durations stay `monotonic_ns()`; generations stay
integers. Both the `UPDATE … RETURNING` path and D1's `BEGIN IMMEDIATE` fallback run in CI under a
16-process hammer. `Store.complete()` is the only mutation entry point and commits derived rows, the
work transition, `dep` rows, the reservation state change and the `route_spend` row in one transaction
(**I20**). The one relaxation is **group commit for transitions that write zero derived rows**
(`skipped_cached`, `deferred_budget`, `failed_*`): they batch at `store_group_commit_ms`, because
losing them to a crash simply re-checks the cache next run — idempotent — and they are what dominates a
warm second run.

**The torn-parse hole, closed.** D2 commits one transaction per page; D3 permits
`granularity = "document"`. A crash after page 40 of 200 therefore leaves 40 committed pages under a
`pending` work row, which on resume duplicates or trips `block_addr`'s UNIQUE index. Neither ruling can
fix it alone. A document-granularity parse writes at `staged_gen = doc.gen + 1`; readers resolve at the
committed `doc.gen`; the bump is one UPDATE inside the completing transaction; abandoned generations
are swept at startup through D2's `ON DELETE CASCADE`. One integer column that already exists (**I21**).

**Batching and services.** Batch = one `INVOKE`, AIMD per `(driver_id, config_digest)`: halve on
`OOM`/`WORKER_DIED`, `batch=1` for a crash retry to localise the poison unit, `+1` after 20 clean
batches. Halve-and-never-recover lets one foreign process permanently cap throughput. Coalescing is the
model server's, taken from surya's verified `common/batch_service/server.py:79-99` `_drain()` — block
for one job, coalesce within `batch_wait_ms` (`settings.py`: 5), ceiling `max_batch` (`config.py:37`:
8) — which merges across *worker processes*, something host-side batching cannot do. attach-or-spawn is
surya's ladder whole, plus a 32-byte token in the 0600 sentinel because `surya/surya/settings.py:97` is
`VLLM_API_KEY = "EMPTY"`. **Per-service in-flight is derived, not constant**: `min(server-reported
capacity, MAX_AUTO_PARALLEL=96, operator ceiling)`. `surya/surya/inference/backends/vllm.py` is
explicit — 96 is a *cap* (`_client_parallel()` returns `min(self._max_num_seqs, MAX_AUTO_PARALLEL)`) and
`_max_num_seqs` defaults to 8; a flat 96 on a 24 GB consumer card is an OOM, not the measured +28%.

**Cache.** One key function, three groups. `schema_version` always; `code_fingerprint` iff
`cost_class != billed_api`; `deps_digest` iff `free` (this settles `mine-runtime.md` §7.12 #4);
`digest_recipe` only for operators consuming block-level artifacts, because D2 rules a recipe bump is a
re-digest pass; `semantic_digest`, never the full `config_digest`. Every config key declares its axis at
its declaration site, gate **G17** fails on an unclassified key, and unclassified defaults to `semantic`
— fail expensive, never wrong. `roots.source` is **operational**: the salt is the walked path *relative*
to it, which is what keeps a cache portable across checkouts.

**Incremental.** The cache key answers "is this derivation stale"; it cannot answer "whose answer
depended on what changed", and codegraph priced the gap at 4.3% of distinct edges wrong in both
directions. `dep(dependent_id, kind, key, digest)` with a reverse index makes invalidation one query.
Cross-unit rows arrive three ways, and none requires a store handle inside a driver: the runner writes
`unit`/`part` deps for what it fed the driver; a `derive` driver declaring
`produces = [..., "witness_set"]` returns the foreign tuples it consulted; a corpus-granularity operator
declaring nothing gets a `cohort` merkle over its member set — correct by construction and expensive,
which is why a `billed_api` corpus driver without a witness set is refused at resolve time.

## Concrete shape

```
────────────────────────── PACKAGE LAYOUT (inside D1's tree; no new distribution) ──────────────────
packages/omniweave-core/src/omniweave_core/        SYNCHRONOUS. No asyncio. No selectors. (G22)
├── operator.py     OperatorIdentity (== D2 Producer) · StepResult · Outcome · StepMetrics
│                   RunContext · Roots · CancelToken            [§7.1, UNCHANGED by D3's ruling]
├── work.py         WorkRow · FailureClass · classify() · claim/complete/reap SQL · retry ladder
├── cache.py        cache_key · semantic_digest · CacheIndex · Layer · Verdict · six-clause read
│                   · put(entries, allowed_units=…)              [graphify cache.py:1385 allowlist]
├── blobs.py        CAS: put(BinaryIO)->sha256 · path · refcount · mark-and-sweep · headroom file
├── budget.py       BudgetLedger over budget_reservation · Reservation · headroom (computed in SQL)
├── deps.py         Dep · DepKind · record_deps · invalidate(delta) · cohort_digest
├── events.py       Event · TraceSink · NdjsonSink · ConsoleSink · traceparent · EVENTS (closed)
├── wire.py         stdlib MessagePack subset for D3's frame set   ★ UPSTREAM CONFLICT C1
├── host/           inproc.py (DriverGuard) · subproc.py (D3's DriverHost — BLOCKING, not async)
├── modelserver.py  ServiceSpec · ServiceHandle · attach_or_spawn · ServiceRegistry      [seam S3]
├── locks.py        scoped cross-process lock (O_CREAT|O_EXCL + flock + (host,pid,create_time))
├── clock.py        Clock protocol — injected, never ambient
└── store/sqlite.py THE ONLY sqlite3.connect · pragmas · heal-on-open · WAL valve · connect_readonly

packages/omniweave/src/omniweave/run/              THE SUPERVISOR. Never imported by a hook.
├── supervisor.py   the one asyncio loop: claim → admit → dispatch → complete → reap
├── discover.py     streaming roster → `unit` rows; connector cursors; the stat index; scope rules
├── expand.py       op.identify; part-row expansion gated by the water mark
├── dispatch.py     dispatch_key Batch formation · AIMD · crash quarantine · Sequence sessions
├── pipeline.py     THE middleware order. The ONLY caller of DriverHost.invoke (semgrep-enforced).
├── converge.py     dep delta · cohort · witness · the per-unit attribution guard
├── manifest.py     the incremental run manifest + the two cost self-checks
└── bench.py        ow bench scheduler | inproc | service | rss

packages/omniweave-serve/src/omniweave_serve/
└── otlp.py         `ow trace export [--follow]`. THE ONLY place `opentelemetry` may be imported.
```

```sql
-- ══════════════ THE ROSTER. One row per source document. 100k docs ≈ 22 MB. ══════════════
CREATE TABLE unit (
  unit_uri       TEXT PRIMARY KEY,          -- canonical_uri(): realpath+normcase+'/'+strip \\?\
  connector      TEXT NOT NULL DEFAULT 'fs',
  cursor         TEXT,                      -- the connector's resume token FOR THIS UNIT
  state          TEXT NOT NULL CHECK (state IN ('discovered','acquiring','acquired','identified',
                                                'planned','running','settled','failed','out_of_scope')),
  size INTEGER, mtime_ns INTEGER, indexed_at_ns INTEGER,   -- captured BEFORE the read
  content_digest TEXT,                      -- sha256 over NORMALISED load-bearing bytes (§7.5.1)
  normalizer     TEXT,                      -- NULL ⇒ raw bytes hashed; records OW-C-041
  media_type TEXT, format TEXT, bytes INTEGER,
  part_count     INTEGER,                   -- NULL until op.identify. Drives expansion.
  acq_failure_class TEXT, acq_retry_after INTEGER,
  acq_attempts_total INTEGER NOT NULL DEFAULT 0, acq_attempts_today INTEGER NOT NULL DEFAULT 0,
  acq_last_attempt_at INTEGER,              -- the PERIOD STAMP for attempts_today
  stale_since    INTEGER,                   -- FIRST transition only; KEPT across a reset
  settled_gen INTEGER, last_seen_gen INTEGER NOT NULL,
  scope_rule     TEXT CHECK (scope_rule IN ('explicit','inherited') OR scope_rule IS NULL)
) STRICT;
CREATE INDEX unit_ready ON unit(state, last_seen_gen)
  WHERE state IN ('discovered','acquired','identified','planned');
CREATE INDEX unit_stale ON unit(stale_since) WHERE stale_since IS NOT NULL;

-- ══════════════ THE QUEUE. §7.3.1 + D4's decision_id + D6's three derived columns. ══════════════
CREATE TABLE work (
  id              INTEGER PRIMARY KEY,
  unit_uri        TEXT NOT NULL REFERENCES unit(unit_uri) ON DELETE CASCADE,
  unit_part       TEXT NOT NULL DEFAULT '',  -- '' folds NULL: NULLs are distinct in a UNIQUE index
  operator        TEXT NOT NULL,             -- '<port>.<family>' | 'op.<name>' (core-only, no driver)
  op_version      INTEGER NOT NULL,          -- the OPERATOR's schema_version int
  cache_key       TEXT NOT NULL,             -- RECORDED: a config change is a mismatch, not a reuse
  decision_id     TEXT NOT NULL REFERENCES route_decision(decision_id),      -- D4
  sequence_id     TEXT,                                                      -- D4 Sequence binding
  -- ── DERIVED BY THE PLANNER FROM THE RESOLVED Candidate. Never edited elsewhere. (I22) ──
  driver          TEXT NOT NULL,             -- driver_id; the human/reporting column
  cost_class      TEXT NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  dispatch_key    TEXT NOT NULL,             -- sha256(driver‖config_digest‖isolation)[:16] ★ batch axis
  service         TEXT,                      -- NULL unless this unit needs a Service
  staged_gen      INTEGER,                   -- torn-parse fix; NULL for part-granularity work
  status          TEXT NOT NULL CHECK (status IN ('pending','claimed','done','failed_transient',
                                                  'failed_permanent','deferred')),
  failure_class   TEXT, failure_message TEXT, retry_after INTEGER,
  attempts_total  INTEGER NOT NULL DEFAULT 0, attempts_today INTEGER NOT NULL DEFAULT 0,
  last_attempt_at INTEGER, stale_since INTEGER,
  claimed_by      TEXT,                      -- '<host>:<pid>:<process_create_time>' — a PID is reusable
  claimed_gen INTEGER, lease_expires INTEGER,
  cost_micros     INTEGER NOT NULL DEFAULT 0,
  queued_ms       INTEGER NOT NULL DEFAULT 0,  -- ★ ALWAYS separate from ran_ms (jcodemunch §5.3)
  ran_ms          INTEGER NOT NULL DEFAULT 0,
  peak_rss_bytes  INTEGER NOT NULL DEFAULT 0,
  priority        INTEGER NOT NULL DEFAULT 0   -- and it is ACTUALLY ORDERED BY
) STRICT;
CREATE UNIQUE INDEX work_identity  ON work(unit_uri, unit_part, operator, op_version);
CREATE INDEX work_claimable ON work(cost_class, status, retry_after, priority DESC, dispatch_key, id)
  WHERE status IN ('pending','failed_transient');
CREATE INDEX work_leases ON work(lease_expires) WHERE status = 'claimed';
CREATE INDEX work_unit   ON work(unit_uri);
-- NO counter table: `SELECT status, count(*) FROM work GROUP BY status` is exact and cannot drift.
CREATE TRIGGER work_no_live_delete BEFORE DELETE ON work
  WHEN OLD.status IN ('pending','claimed','failed_transient')
  BEGIN SELECT RAISE(ABORT,'OW-S-014 refusing to delete a live work row'); END;

-- Compaction archive. Preserves EXACTLY the two consumers of a `done` row: resume, and the
-- shrink guard's baseline. ~90 B/row against work's ~250 B.
CREATE TABLE work_done (
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  operator TEXT NOT NULL, op_version INTEGER NOT NULL,
  cache_key TEXT NOT NULL, gen INTEGER NOT NULL,
  rows_written INTEGER NOT NULL, cost_micros INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, operator, op_version)
) WITHOUT ROWID;

-- ══════════════ THE BATCH-COHERENT CLAIM. One statement. Priority survives. ══════════════
WITH head AS (
  SELECT dispatch_key FROM work
   WHERE cost_class = :cost_class
     AND status IN ('pending','failed_transient')
     AND (retry_after IS NULL OR retry_after <= unixepoch('subsec')*1000)
     AND attempts_total < 5
   ORDER BY priority DESC, dispatch_key, id LIMIT 1)
UPDATE work SET
  status='claimed', claimed_by=:worker_identity, claimed_gen=:generation,
  lease_expires = unixepoch('subsec')*1000 + :lease_ms,   -- ★ the STORE's clock, never the worker's
  attempts_total = attempts_total + 1,
  attempts_today = CASE WHEN date(last_attempt_at/1000,'unixepoch')
                          = date(unixepoch('subsec'),'unixepoch') THEN attempts_today+1 ELSE 1 END,
  last_attempt_at = unixepoch('subsec')*1000
WHERE id IN (SELECT w.id FROM work w, head
              WHERE w.dispatch_key = head.dispatch_key AND w.cost_class = :cost_class
                AND w.status IN ('pending','failed_transient')
                AND (w.retry_after IS NULL OR w.retry_after <= unixepoch('subsec')*1000)
                AND w.attempts_total < 5
              ORDER BY w.priority DESC, w.id LIMIT :batch)
RETURNING *;
-- Commit predicate:  … WHERE id=:id AND claimed_gen=:gen AND status='claimed';
-- zero rows ⇒ superseded ⇒ the WHOLE transaction rolls back. The claim IS the lease. (I23)
-- SQLite < 3.35: BEGIN IMMEDIATE + UPDATE + SELECT. BOTH paths run in CI's 16-process hammer. (I22)

-- ══════════════ ONE CACHE INDEX, FIVE LAYERS, ONE GC, ONE BILL ══════════════
CREATE TABLE cache_index (
  cache_key    TEXT PRIMARY KEY,
  recipe       INTEGER NOT NULL,              -- a bump NAMESPACES. It NEVER deletes.
  layer        TEXT NOT NULL CHECK (layer IN ('blob','call','embed','render','signal')),
  cost_class   TEXT NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  ref          TEXT NOT NULL,                 -- 'cas://ab/cd/<sha256>'
  bytes        INTEGER NOT NULL,
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',   -- read-policy clause 5
  driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL, config_digest TEXT NOT NULL,
  origin_operator TEXT NOT NULL,              -- OWNERSHIP. Never conflated with confidence.
  spend_json   TEXT NOT NULL,                 -- the Spend that produced it — REPLAYED on every hit
  micros       INTEGER NOT NULL,              -- priced at creation; RE-priced on hit from the PriceBook
  partial      INTEGER NOT NULL DEFAULT 0,    -- read-policy clause 3
  created_ns INTEGER NOT NULL, last_hit_ns INTEGER NOT NULL, hits INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX cache_gc   ON cache_index(cost_class, last_hit_ns);
CREATE INDEX cache_unit ON cache_index(unit_uri, unit_part, layer);
CREATE INDEX cache_ns   ON cache_index(driver, driver_schema_v, recipe) WHERE cost_class='free';
-- ★ THERE IS NO `parse` OR `derive` LAYER. If it is a row in the .owstore it is NEVER also a blob
--   in the cache (D2: "one store, never a model plus a sync layer"). The parse memo IS
--   work.status='done' ∧ work.cache_key matching ∧ doc(doc_key, gen) present.
-- ★ The `call` layer caches the DRIVER'S RAW RESPONSE, not derived rows. That is what makes
--   re-ingesting a corpus into a SECOND store cost CPU-seconds instead of 116,000 VLM pages.

-- ══════════════ INCREMENTAL: the reverse index, the definition set, the cohort ══════════════
CREATE TABLE dep (
  dependent_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  kind   TEXT NOT NULL CHECK (kind IN ('unit','part','name','cohort','policy','service_model')),
  key    TEXT NOT NULL,      -- uri | 'uri#p41' | 'fig:3.1' | cohort_id | 'route:<digest>' | 'vlm.page'
  digest TEXT NOT NULL,      -- the value OBSERVED when the dependent was derived
  PRIMARY KEY (dependent_id, kind, key)
) WITHOUT ROWID;
CREATE INDEX dep_reverse ON dep(kind, key);
-- Invalidation is ONE query, never a sweep:
--   SELECT DISTINCT d.dependent_id FROM dep d JOIN changed c
--     ON c.kind=d.kind AND c.key=d.key WHERE d.digest <> c.new_digest;
-- MAX_DEPS_PER_UNIT = 256, enforced in Store.complete(). Past it the operator MUST declare a
-- cohort dep — coarser, always safe, over-invalidating on purpose.

CREATE TABLE defines (          -- what a unit DEFINES. codegraph's definitionDelta, as rows.
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,           -- section | figure | table | term | citekey | anchor
  name TEXT NOT NULL,           -- normalised by ONE function, shared with the resolver
  gen  INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, kind, name)
) WITHOUT ROWID;
CREATE INDEX defines_name ON defines(kind, name);

CREATE TABLE cohort (
  cohort_id TEXT PRIMARY KEY,   -- 'coh_' || sha256_canonical(member merkle)[:24]
  name TEXT NOT NULL, member_count INTEGER NOT NULL, member_digest TEXT NOT NULL,
  built_gen INTEGER NOT NULL, built_ns INTEGER NOT NULL
) STRICT;
CREATE TABLE cohort_member (
  cohort_id TEXT NOT NULL REFERENCES cohort(cohort_id) ON DELETE CASCADE,
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', content_digest TEXT NOT NULL,
  PRIMARY KEY (cohort_id, unit_uri, unit_part)
) WITHOUT ROWID;

-- ══════ DURABLE BUDGET. Closes D4's in-memory-ledger hole AND the cross-process over-admission
--        hole: Σ(held, dim='calls', scope='provider') IS the in-flight count. ══════
CREATE TABLE budget_reservation (
  reservation_id TEXT PRIMARY KEY,           -- 'res_' || sha256_canonical(identity)[:24]
  run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
  work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  decision_id TEXT NOT NULL REFERENCES route_decision(decision_id),
  dim TEXT NOT NULL CHECK (dim IN ('micros','tokens_in','tokens_out','calls','gpu_ms','wall_ms',
                                   'cpu_ms','bytes_egress')),
  amount INTEGER NOT NULL,                   -- the p95 ceiling (D4 tokens_out_p95_multiple)
  scope TEXT NOT NULL CHECK (scope IN ('run','corpus','unit','part','operator','provider')),
  scope_key TEXT NOT NULL DEFAULT '',
  claimed_gen INTEGER NOT NULL,
  expires_ms INTEGER NOT NULL,               -- == the work row's lease_expires
  state TEXT NOT NULL CHECK (state IN ('held','committed','released'))
) STRICT;
CREATE INDEX res_open   ON budget_reservation(dim, scope, scope_key) WHERE state='held';
CREATE INDEX res_expiry ON budget_reservation(expires_ms)            WHERE state='held';
-- headroom(dim,scope,key) = limit − Σ(held) − Σ(committed), COMPUTED IN SQL, never cached in an
-- attribute. The lease reaper releases expired reservations in the SAME transaction. (I29)

CREATE TABLE run (
  run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,   -- monotonic INTEGER, never a clock
  trigger TEXT NOT NULL CHECK (trigger IN ('cli','hook','upstream','watch')), argv TEXT NOT NULL,
  config_digest TEXT NOT NULL,      -- FULL effective config: the manifest + the full-scan latch
  semantic_digest TEXT NOT NULL,    -- ★ the NARROW projection that enters cache keys
  policy_digest TEXT NOT NULL, pricebook_digest TEXT NOT NULL, lock_digest TEXT NOT NULL,
  omniweave_version TEXT NOT NULL, contract INTEGER NOT NULL, schema INTEGER NOT NULL,
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  needs_full_scan INTEGER NOT NULL DEFAULT 0,   -- the latch; cleared only by a full reconcile
  events_dropped INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('running','ok','partial','failed','interrupted','abandoned')),
  manifest_path TEXT NOT NULL
) STRICT;

CREATE TABLE service_observation (
  run_id TEXT NOT NULL, name TEXT NOT NULL, config_digest TEXT NOT NULL,
  model_id TEXT NOT NULL, model_rev TEXT, base_url TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('attached','spawned','failed','quarantined','evicted')),
  capacity INTEGER NOT NULL, peak_inflight INTEGER NOT NULL DEFAULT 0,
  requests INTEGER NOT NULL DEFAULT 0, units INTEGER NOT NULL DEFAULT 0,
  gpu_ms INTEGER NOT NULL DEFAULT 0, health_failures INTEGER NOT NULL DEFAULT 0,
  cold_start_ms INTEGER, queue_p50_ms INTEGER, queue_p95_ms INTEGER,
  log_tail TEXT,                              -- the SERVER'S OWN log tail on a failure
  PRIMARY KEY (run_id, name, config_digest)
) STRICT;
```

```python
# ══════ IDENTITY RECONCILIATION — D2's Producer IS OperatorIdentity. D2's fields, verbatim. ══════
#   Producer.operator          = origin_operator  = '<port>.<family>'   ← THE OWNERSHIP GRAIN (I4)
#   Producer.op_version        = str(operator schema_version int)
#   Producer.code_fingerprint  = sha256(operator module source)[:12]    ← never a packaging lookup
#   Producer.runtime           = origin_driver = driver_id '<port>.<family>.<impl>'   ← D3
#   Producer.runtime_version   = the card's driver_version (semver)                   ← D3
#   Producer.model_id/.model_rev = the driver's declared model; model_rev is an exact sha ('main' lints)
#   Producer.prompt_fp         = CRLF→LF, trailing ws stripped, THEN hashed
#   Producer.options_digest    = candidate.config_digest, as bytes
#   work.operator = Producer.operator ; work.op_version = int(Producer.op_version)
# ★ origin_operator is TWO segments, origin_driver is THREE, and they are not redundant:
#   `derive.chunk` re-running replaces `derive.chunk` rows and CANNOT touch `derive.entity` rows.
#   That is I4, made true. Ownership governs eviction WITHIN a generation; a re-parse mints a new
#   `gen` and D2's `rebind` carries block_ids forward or quarantines.

# ══════════════════════════════ omniweave_core/cache.py ══════════════════════════════
class Layer(StrEnum):   BLOB="blob"; CALL="call"; EMBED="embed"; RENDER="render"; SIGNAL="signal"
class Verdict(StrEnum):
    HIT="hit"; MISS="miss"; MISS_CORRUPT="miss_corrupt"; MISS_PARTIAL="miss_partial"
    MISS_EMPTY="miss_empty"; MISS_UNIT_MISMATCH="miss_unit_mismatch"; HIT_LEGACY="hit_legacy"

def cache_key(unit: UnitRef, ident: OperatorIdentity, card: DriverCard, ctx: RunContext) -> str:
    free  = card.cost.klass is CostClass.FREE
    cheap = card.cost.klass is not CostClass.BILLED_API
    return sha256_canonical({
      "k": CACHE_RECIPE,                                   # the KEY RECIPE version
      "content":  {"digest": unit.content_digest,          # normalised load-bearing bytes (§7.5.1)
                   "salt":   unit_salt(unit, ctx.roots),   # walked path RELATIVE to source_root
                   "part":   unit.part or ""},
      "producer": {"operator": ident.operator,
                   "schema_version": card.schema_version,  # D3: "it ALONE enters the cache key"
                   "code_fingerprint": ident.code_fingerprint if cheap else None,
                   "deps_digest":      deps_digest(card)   if free  else None},
      "config":   {"driver": ident.options_digest.hex(),
                   "run":    ctx.semantic_digest,          # ★ NOT config_digest — see config_axes
                   "digest_recipe": DIGEST_RECIPE if consumes_blocks(ident) else None},
    })
# sha256_canonical: sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False.
# NEVER "".join(values) — graphrag's gen_sha512_hash collides ["a","bc"] with ["ab","c"].
# An un-canonicalisable value is a STARTUP ERROR. There is no str() fallback, ever. (I12)
# policy_digest and pricebook_digest are DECISION-key inputs (D4) and NEVER artifact-key inputs.

def namespace(ident, cfg_digest, cost_class) -> str:            # graphify's two-tier rule, ×3
    FREE          -> f"op/{ident.operator}/v{ident.op_version}-c{ident.code_fingerprint}/"   # SWEPT
    LOCAL_COMPUTE -> f"op/{ident.operator}/v{...}-c{...}/cfg/{cfg_digest}/"   # liveness only
    BILLED_API    -> f"cfg/{cfg_digest}/"                                     # NEVER SWEPT (I27)
# Growth bound, printed by `ow cache stat` IN THESE WORDS: live units × configurations seen.

# Read policy — six clauses, the cache's business and not the caller's:
#   1 no entry ⇒ MISS · 2 unparseable ⇒ MISS, counted, AND OVERWRITTEN on the next success
#   3 partial (and not allow_partial) ⇒ MISS · 4 fails is_valid_nonempty ⇒ MISS
#   5 recorded (unit, part) ≠ asked ⇒ MISS · 6 older namespace, legacy-allowed ⇒ HIT_LEGACY, reported
# Writes: cache.put(entries, allowed_units=frozenset(batch_units)) — runner-supplied, never
# driver-supplied. D3 makes this structural: DriverIO carries no cache handle at all. (I13)
```

```toml
# tools/config_axes.toml — GENERATED from omniweave_core.config declarations, committed, byte-diff
# gated (G17). An UNCLASSIFIED key FAILS CI and is treated at runtime as `semantic`
# (fail expensive, never wrong).  semantic_digest = sha256_canonical(the semantic projection).
[semantic]    # enters cache keys AND sets the full-scan latch
keys = ["drivers.*.*", "limits.*", "targets.*", "cache.recipe",
        "services.*.model_id", "services.*.model_revision"]
[operational] # NEVER enters a cache key. Changing these must not cost a dollar.
keys = ["runtime.*", "budget.*", "observe.*", "store.*", "cache.gc", "cache.max_bytes",
        "roots.source", "roots.output", "roots.cache",   # ★ the SALT is RELATIVE to roots.source;
                                                          #   the absolute root in a key would destroy
                                                          #   portability across checkouts
        "drivers.max_workers", "drivers.worker_idle_ttl_s", "drivers.crash_quarantine",
        "services.*.endpoint", "services.*.autostart", "services.*.capacity",
        "services.*.batch_wait_ms", "services.*.max_batch", "services.*.keep_alive_s"]
```

```python
# ═══════════ omniweave/run/pipeline.py — THE MIDDLEWARE ORDER IS THE ARTIFACT ═══════════
# The ONLY caller of DriverHost.invoke(). Semgrep-enforced. (graphrag §2.5, + with_budget)
with_events                       # span open/close; W3C ids; ALWAYS ON
 └ with_request_count
   └ with_cache                   # ← A HIT RETURNS HERE. No budget, no tokens, no rate-limit slot.
     │                            #   Spend replayed from cache_index.spend_json, was_cache_hit=True
     └ with_budget                # ← reserve/commit. DENIED ⇒ DEFERRED_BUDGET (an Outcome, not a failure)
       └ with_retries             #   OUTSIDE rate limiting: a retry gets back in line.
         │                        #   Semaphore(1) per (unit_uri, unit_part) — D4 R11, strictly serial.
         └ with_rate_limiting     #   NOT graphrag's: no busy-wait, no time.sleep under a held lock
           └ with_metrics         #   measures the PROVIDER, not the queue
             └ with_fault_injection   # _chaos:{failure_rate,exception_type,latency_ms,oom_at_unit}
               └ DriverHost.invoke(batch)     # SHIPPED in production builds, off by default

# ═══════════ omniweave/run/supervisor.py ═══════════
async def run(scope: Scope, ctx: RunContext) -> RunManifest:
    async with asyncio.TaskGroup() as tg:          # TaskGroup for STRUCTURED SHUTDOWN ONLY.
        tg.create_task(lag_monitor(ctx))           # A worker_loop catches BaseException and NEVER
        tg.create_task(lease_reaper(ctx))          # propagates: one driver crash costs one unit.
        tg.create_task(discoverer(scope, ctx))     # → unit rows, streamed, 512/txn
        tg.create_task(expander(ctx))              # op.identify + part rows, gated by the water mark
        for cls, n in ctx.admission.max_inflight.items():
            for _ in range(n): tg.create_task(worker_loop(cls, ctx))
        for svc in ctx.services.live(): tg.create_task(service_refill(svc, ctx))

def refill_target(svc: ServiceHandle, cfg, ledger) -> int:
    # ★ DERIVED, not constant. surya vllm.py: MAX_AUTO_PARALLEL = 96 is a CAP —
    #   `_client_parallel() = min(self._max_num_seqs, MAX_AUTO_PARALLEL)`, and `_max_num_seqs`
    #   DEFAULTS TO 8. Measured on a B200: 48→96 = +28%, 96→240 = +5%.
    return min(svc.capacity(), MAX_AUTO_PARALLEL, cfg.max_inflight, ledger.headroom_units(svc))

class Admission:
    """FREE and LOCAL_COMPUTE: in-memory semaphores. BILLED_API: the DURABLE ledger, because two
    scheduler processes each holding an in-memory semaphore of 2 show the provider 4. A held
    reservation on (dim='calls', scope='provider') IS the cross-process in-flight count."""
    class_sem:   Mapping[CostClass, Semaphore]     # D1  [budget] max_inflight  — UNITS
    worker_sem:  Mapping[CostClass, Semaphore]     # D3  [drivers] max_workers  — PROCESSES
    render_sem:  Semaphore                         # olmocr pipeline.py:87 — cpu_count-2, CPU raster
    service_sem: Mapping[str, Semaphore]           # refill_target(), per Service
    def producer_should_pause(self, claimable: int) -> bool:   # 50k / 25k, never a single threshold

def adapt_batch(driver_cfg, event) -> int:         # AIMD, per (driver_id, config_digest)
    OOM | WORKER_DIED        -> max(1, batch // 2)         # §7.3.2 "halves the batch size"
    DRIVER_CRASHED           -> 1 for the retry            # D3: localise the poison unit
    20 consecutive clean     -> min(batch + 1, card.isolation.batch_max_units)
```

```python
# ═══════════ omniweave_core/events.py — stdlib only. OTLP lives in omniweave-serve. ═══════════
@dataclass(frozen=True, slots=True)
class Event:
    ts_wall_ns: int; ts_mono_ns: int; run_id: str; seq: int
    trace_id: str; span_id: str; parent_span_id: str | None      # W3C shaped: 16B / 8B, hex
    kind: str                          # from tools/events.toml — CLOSED, APPEND-ONLY, CI-diffed
    phase: Literal["start","end","point"]; level: str
    unit: str | None; part: str; operator: str | None; driver: str | None
    fields: Mapping[str, Scalar]
class TraceSink(Protocol):
    def emit(self, e: Event) -> None: ...   # MUST NOT BLOCK. Bounded 64k queue, DROP-OLDEST,
    def flush(self, timeout_ms: int) -> int: ...  # counted into run.events_dropped AND degradations[]
def traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"    # rides D3's HELLO, D1's job.json, and the Service header
# Span hierarchy, CLOSED and five deep. There is no `wave` and no `part` level: the unit IS (uri, part).
#   run > plan > unit > attempt > call
# batch_index / batch_size are SPAN ATTRIBUTES on `call`, never rows: a Batch is visible for
# diagnosis and invisible for accounting.
```

```
tools/events.toml — CLOSED, APPEND-ONLY, byte-diff gated (G19); schema/event-v1.json generated from it
run.start run.end run.degraded
plan.discover plan.identify plan.expand plan.pause plan.resume
work.enqueue work.claim work.lease_extend work.lease_reap work.complete work.defer work.cancel
unit.begin unit.progress unit.complete unit.failed
driver.spawn driver.ready driver.invoke driver.result driver.crash driver.quarantine driver.shutdown
service.attach service.spawn service.refuse service.evict service.coalesce
cache.hit cache.miss cache.corrupt cache.write cache.sweep
budget.reserve budget.deny budget.commit
store.txn store.wal_valve store.bulk_lock store.contend
dep.record dep.invalidate  gc.sweep  degrade  manifest.write
```

```toml
# ══════════════════════════ CONFIG DELTA on omniweave.toml ══════════════════════════
[runtime]
queue_high_water      = 50000   # claimable rows; expansion PAUSES here
queue_low_water       = 25000   # …and resumes here. Hysteresis, never one threshold.
plan_batch            = 512     # rows per expansion/discovery transaction
store_group_commit_ms = 20      # group-commits ONLY transitions writing zero derived rows
lease_ms              = 120000
lease_extend_ms       = 60000   # ONE warned extension for a LIVE holder. NEVER a steal.
watchdog_ms           = 60000   # no synchronous stage may exceed watchdog_ms / 2      (I15)
loop_lag_max_ms       = 250     # measured by lag_monitor; a breach latches degrade()  (I32)
yield_interval        = 1000    # at the TOP of the loop body, so `continue` still yields
interactive_wait_ms   = 2000    # named wait budgets, passed per call, never a constant
batch_wait_lock_ms    = 60000
max_inproc            = 2       # GIL-bound: D1's anydoc eager marshal. See `ow bench inproc`.
inproc_bulk_threshold = 64      # > this many units ⇒ isolation TIGHTENED to subproc, recorded
max_deps_per_unit     = 256
work_compact_above    = 5000000

[runtime.claim]
batch = { free = 256, local_compute = 32, billed_api = 8 }   # clamped by card.batch_max_units, AIMD

[services."vlm.page"]
model_id          = "allenai/olmOCR-7B-…"   # VERIFIED via GET /v1/models ON ATTACH; mismatch ⇒ refuse
model_revision    = "a1b2c3…"               # "main" is a STARTUP ERROR (D4 R14), not a warning
endpoint          = ""                       # non-empty ⇒ attach only, never spawn
autostart = true ; keep_alive_s = 300 ; startup_timeout_s = 300 ; request_timeout_s = 600
capacity          = 0     # 0 ⇒ DERIVE from the server's reported concurrency, capped at 96
batch_wait_ms     = 5     # surya's verified default (settings.py *_SERVER_BATCH_WAIT_MS)
max_batch         = 8     # surya's batch_service/config.py default_max_batch
auth              = "token"   # 32B token in the 0600 sentinel; `none` needs allow_unauthenticated

[cache]
recipe    = 1
gc        = { free_after_days = 7, local_after_days = 90, billed_after_days = 0 }   # 0 = NEVER
max_bytes = { blob = 107374182400, render = 21474836480, signal = 2147483648,
              call = 0, embed = 0 }                                                 # 0 = unbounded
min_free_bytes = 5368709120   # below this the run PAUSES and names the GC command. Never evicts.
                              # A 256 MB headroom file is created at store init and released on the
                              # pause, so the GC is never deadlocked needing to write.

[observe]
sinks = ["console", "ndjson"]   # a Protocol in core with TWO shipped impls. No entry-point group.
ndjson_path = ".omniweave/events/{run_id}.ndjson.zst"
shard_bytes = 67108864
sample = { non_ok = 1.0, ok = 0.015625 }   # 1-in-64, blake2b(work_id‖salt), NEVER RNG   (D4 R2)
timings = "always"                          # never behind an env var
otlp_endpoint = ""                          # honoured by `ow trace export` ONLY
```

```
────────────────────────────────────── CLI ──────────────────────────────────────
ow ingest [PATHS…] [--dry-run] [--profile fast|balanced|thorough|offline] [--max-rung PAGE]
ow update [--dry-run]        ow resume            # resume is an ALIAS: recovery IS the normal command
ow queue  status [--by driver|class|failure] | retry --class TIMEOUT | reset --failed-transient
ow top    [--plain] [--interval 10]   # live, read-only, NEVER attaches to the supervisor process
ow why    <uri> [--part p41]          # ★ acquisition · decisions · WHICH CACHE-KEY GROUP DIFFERED
                                      #   · spend · retries · what it is waiting on. One screen.
ow cost   [--by document|driver|provider|slice] [--since 7d] [--format table|json|csv]
ow cache  stat | explain <uri> --op parse | gc [--dry-run] | migrate --to-recipe 2 --dry-run
          | prune --tier render --to 10G [--allow-rebill] | verify --tier call --sample 1000
ow deps   of <uri> | rdeps name fig:3.1        # the reverse index, exposed
ow replay --run|--work|--decision <id> [--offline] [--verify]   # 0 IDENTICAL 3 DIVERGED 4 DRIFT
ow services list | start <n> | stop <n> | logs <n>
ow store  heal | compact --before-gen N | gc --abandoned-gens | bulk-window
ow trace  tail | tree <run_id> | export <run_id> --otlp <url> [--follow]    # omniweave-serve
ow bench  scheduler | inproc | service | rss     # the four baselines a human must re-bless
ow test   crash-matrix                            # SIGKILL at every stmt boundary in Store.complete
ow doctor --runtime      # effective slots, derived service capacity, Σworkers×memory_mb vs RAM,
                         # WAL health, filesystem type (REFUSES T2 on a network mount)
# Named overrides only, never one --force:  --allow-unexplained-loss  --allow-rebill
#   --accept-partial  --ignore-cache  --allow-abandoned-gen  --max-rung <RUNG>
```

```
────────── INVARIANTS I19–I34 (I1–I18 are §7.11's, unchanged and binding by D3) ──────────
I19 Exactly one thread per process holds a sqlite3.Connection.  store/sqlite.py records
    threading.get_ident() at connect and asserts per call; check_same_thread stays True; lint bans
    `import sqlite3` outside omniweave_core/store/; a 16-runner-thread test asserts every call raises.
I20 A unit's derived rows + work transition + dep rows + reservation commit + route_spend row commit
    in ONE transaction.  Store.complete() is the sole mutation entry; G23 semgrep bans conn.commit()
    elsewhere; `ow test crash-matrix` SIGKILLs at every statement boundary and asserts owcheck passes
    and the pending set is exactly the unfinished work.  EXCEPTION: transitions writing ZERO derived
    rows may group-commit at store_group_commit_ms (crash ⇒ re-check the cache ⇒ same outcome).
I21 A document-granularity producer's pages are invisible until its work row is done.  staged_gen =
    doc.gen + 1; readers filter on the committed doc.gen; the bump is IN the completing transaction;
    a kill-mid-document test asserts the previous gen still resolves and the staged one is swept.
I22 No unit is claimed twice on EITHER SQLite path, and work.{driver,cost_class,dispatch_key} always
    agree with route_decision.  16-process hammer over 100k rows; a derived-column consistency test.
I23 A superseded result writes nothing.  Commit predicate on (id, claimed_gen, status); zero rows ⇒
    rollback; a test bumps ctx.generation mid-flight and asserts CANCELLED and zero rows written.
I24 A Batch is invisible to the work table, the spend ledger, the trace and the failure taxonomy.
    One RESULT per unit (D3); batch_index/batch_size are SPAN ATTRIBUTES, never rows; a batch=32 test
    asserts 32 transitions, 32 route_spend rows, 32 unit spans, and after a poison unit exactly one
    FAILED_PERMANENT{DRIVER_CRASHED} carrying the child's last 4 KiB of stderr.
I25 A cache hit consumes zero budget, zero tokens and zero rate-limit slots, and replays its Spend
    with was_cache_hit=true.  Middleware composition test; a zero-headroom-ledger test.
I26 No `operational` config key enters a cache key; code_fingerprint enters iff cost_class ≠
    billed_api; deps_digest iff free; digest_recipe iff the operator consumes block-level artifacts.
    G17 + a test mutating every operational key and asserting a byte-identical cache_key.
I27 An automatic sweep never deletes a billed_api cache entry.  cache_ns is a partial index on
    cost_class='free'; deletion needs `ow cache prune --allow-rebill`, which prints the count and the
    would_have_been_micros it is about to discard.
I28 Every derivation's cross-unit inputs are recorded, as dep rows or as a cohort digest.  A driver
    NEVER touches the store: rows come from what the runner fed it, from a declared witness_set, or
    from the cohort merkle.  THE REAL ENFORCER IS G18.
I29 Budget headroom is never leaked by a crash, and billable in-flight is bounded ACROSS processes.
    Durable reservations reaped with leases in one transaction; headroom computed in SQL; a SIGKILL
    test asserts headroom returns after lease_ms; a two-process test asserts the provider sees ≤ N.
I30 Every micro is attributable to exactly one (unit, part, decision, attempt).  Manifest self-checks:
    Σ route_spend.micros == manifest.cost.billed_micros exactly; every ok/ok_partial row has ≥1 spend
    row; every spend row joins one work row; a Sequence apportionment sums to the session ±1 micro.
I31 The supervisor holds no document bytes and stays inside a DECLARED RSS envelope.  Semgrep bans
    .read()/read_bytes() on a source path outside omniweave_core.blobs; anything over D3's
    INLINE_MAX=262144 travels as a blob reference; G21 gates peak RSS on the RSS fixture corpus.
I32 The event loop is never blocked longer than loop_lag_max_ms.  lag_monitor at 100 ms with a
    one-way degrade(); a CI assertion on p99 loop lag over the fixture corpus.
I33 Trace context reaches every seam and the span tree has no orphans.  traceparent in D3's HELLO, in
    D1's job.json, and as an HTTP header to a Service; a CI test rebuilds the tree and asserts zero
    orphans and no parentless span except run.
I34 A deterministic=true driver replays byte-identical over recorded inputs.  `ow replay --verify` over
    the fixture corpus as a CI gate.  deterministic=false yields a normalised-edit-distance DIFF
    REPORT, never an assertion: continuous batching genuinely makes output batch-composition-dependent.

────────── CI GATES, additive to D1's sixteen ──────────
G17 config axes: every resolved key is classified; unclassified fails and defaults to `semantic`
G18 incremental-vs-full equivalence: full-index a 300-doc fixture corpus, snapshot; apply 40 scripted
    mutations (in-place same-size same-mtime edit; rename; delete; add a doc defining a dangling
    label; bump a driver schema_version; bump a signal_version; change a prompt); incremental-update;
    DIFF THE .owdoc EXPORTS, not the tables — D2 guarantees import(export(store))==store and an
    archive carries no block_id, so no allocation-order normalisation can hide a real bug. ~6 min, on
    merge.  ★ THIS IS THE ONLY REASON TO BELIEVE THE dep TABLE IS COMPLETE.
G19 event schema: schema/event-v1.json generated from tools/events.toml, committed, byte-diff gated
G20 kill-9: SIGKILL at three random points; `ow resume` completes; the store equals an uninterrupted run
G21 scale: nightly 100k-synthetic-roster run asserting peak claimable ≤ queue_high_water, supervisor
    peak RSS ≤ 600 MB, and `ow bench scheduler` ≥ 2,000 transitions/s (±25% vs a recorded baseline)
G22 `import omniweave_core -X importtime` loads neither asyncio nor selectors
G23 semgrep: no conn.commit(), no `BEGIN`, no sqlite3 import outside omniweave_core/store/; no bare
    except around content_digest / semantic_digest / code_fingerprint / cache_key / a baseline read

────────── THE 100k-DOCUMENT INGEST ──────────
70k office (document grain) · 25k born-digital PDF · 5k scanned PDF · mean 12 pages
  unit roster                 100,000 rows × ~220 B                                    22 MB
  op.identify rows            100,000
  op.parse rows               70,000 office + 360,000 PDF parts                       430,000
  escalated parts             60,000 scanned + 18.8% × 300,000 (D4's rate)            116,400
  op.derive + op.embed rows   document grain                                          200,000
  TOTAL work rows             ~846,400 × ~250 B with indexes                          ~210 MB
  CLAIMABLE AT ANY INSTANT    ≤ queue_high_water                                       50,000 (~12 MB)
  time to first parsed doc    roster streams; no planning phase                        < 5 s
  office decode               anydoc README: 4.4 ms median / 14 formats / 100 docs      ~5 CPU-min
  routing signals             FREE tier only on clean pages, ~2 ms/part (D4)            ~27 min, cached
  VLM                         116,400 pages × olmocr p50 2.4 s                          77.6 GPU-h serial
    with server Coalescing    speedup is 1.5×–4× and IS NOT MEASURED ANYWHERE           19–52 GPU-h
    billable band             olmocr's <$200/1M pages vs D4's recorded 3.4× spread      $23–$80
  .owstore                    ~80M blocks at D2's 10M ≈ 3.3 GB                          ~26 GB
  routing ledger              D4: ~1 GB/million parts                                   ~850 MB → ~310 MB
  events                      ~846k × 8 × ~180 B, zstd-3, 64 MiB shards                 ~120 MB
  supervisor peak RSS         holds no document bytes; CI-gated                          ≤ 600 MB
  worker RSS                  Σ max_workers × memory_mb; `ow doctor` REFUSES > 0.8×RAM
  runtime overhead            claim share + commit + key + ~8 events                     ≤ 0.5 ms/unit
  crash at hour 6             claimed-with-expired-lease ∪ pending IS the unfinished work ≤ 1 lease
★ HONEST CEILING: ~10^7 parts on one host. 100k × 300-page legal discovery (30M parts, ~7.5 GB of
  work rows) is NOT this design on SQLite. T3 is Postgres with FOR UPDATE SKIP LOCKED and NO operator
  change — that is the entire point of making the store the distribution boundary (§7.10.2).
```

## Rationale

Three questions decided this ruling.

**Where does the event loop live?** The systems architect's case against asyncio is four arguments,
and three of them are about implementation scars (graphrag's `asyncio.new_event_loop()` per LLM call,
its busy-waiting rate limiter) or about a concurrency ceiling that is comfortable either way. The
fourth — D1's 80 ms `import omniweave_core` budget on the per-turn hook path — is decisive and is
answered by *location*, not prohibition. Put the loop in `omniweave/run/`, keep core synchronous, and
gate it. What that buys is the only production-scale precedent in the collection: olmocr's
`pipeline.py:87-88`, verified, is two `BoundedSemaphore`s with CPU render on `asyncio.to_thread`, and
the render/inference split it encodes is not optional at D2's 10.7 MB per rendered page. What it costs
is nothing the systems design was protecting, because I keep its actual load-bearing invariant — one
thread per process owns the connection — which is stronger than a lock precisely because it is a lint
rule plus an assertion rather than a discipline.

**What is the memoised artifact?** The systems design makes three of its five cache tiers "the store".
That is correct as far as D2 goes and it has a consequence nobody costed: re-ingesting the same corpus
into a second `.owstore` re-bills every VLM page, because the only record of that response was a block
row in the first store. The pragmatist's correction is the single most valuable sentence in the three
documents — **cache the driver's raw response, re-derive the rows from it in CPU-microseconds** — and
it composes with D2's "one store, never a model plus a sync layer" rather than fighting it. The
ecosystem's contribution is the accounting shape: one `cache_index` with `spend_json` per row, so
`would_have_been_micros_if_uncached`, `ow cache stat` and `ow cost` are one table and one GC instead of
five. I took the pragmatist's semantics inside the ecosystem's table.

**How does incremental become believable?** All three architects cite codegraph's 4.3%, and the systems
architect is right that a cache key is provably insufficient — it is a function of *this* derivation's
inputs while incremental correctness is a question about *others'*. But his mechanism,
`DeriveIO.read_unit()` / `read_name()` observing a driver's reads, cannot be built: D3's `DriverIO` is
declared *"Not extensible"* and carries no store handle, by design, so the host cannot see what a
cross-document derivation read. The ecosystem architect names exactly this and supplies the honest
answer — the driver *declares* (`witness_set`), or it gets a cohort digest and pays. I took the systems
architect's `dep` table and reverse index (it is the right index and the right closed kind set) and the
ecosystem architect's three population paths, plus the pragmatist's `defines` table, which is the
document-vocabulary instance of codegraph's `definitionDelta` and is what makes "a new document defines
Figure 3.2, so 40 dangling references now resolve" a bounded query. And I settled the systems
architect's own open question about the equivalence gate: diff the `.owdoc` exports, because D2 already
guarantees `import(export(store)) == store` and an archive contains no `block_id`, so the
allocation-order normalisation that could hide a bug is not needed at all.

Beyond those: **no waves.** The ecosystem's wave bounds memory with a barrier, and its own failure mode
1 is a 10,000-page filing holding that barrier; a high/low water mark on claimable rows bounds the same
quantity without one, and `op.identify` as an ordinary operator makes expansion resumable and
observable for free. **No `done`-row sweep into `cache_index`**, because two tables that must agree
about what is finished is the DataFlow failure with better spelling. **AIMD, not halve-forever**,
because one foreign process's OOM must not permanently cap a driver. **Derived service capacity**,
because 96 is a cap in surya's source and not a default. And **durable reservations for `billed_api`
admission**, which turns the pragmatist's own admitted failure mode 10 (two processes each admitting 2,
provider sees 4) into a solved problem using a table two of the three already wanted.

**Claims I checked and found wrong.** (1) Systems: *"The default `max_inflight` for a vLLM-backed
Service is 96, from surya's own measurement."* `surya/surya/inference/backends/vllm.py` reads
`MAX_AUTO_PARALLEL = 96` with `_client_parallel() = min(self._max_num_seqs, MAX_AUTO_PARALLEL)` and
`self._max_num_seqs: int = 8`; 96 is the cap past the B200's knee, not a default any smaller GPU should
see. (2) Systems: `DeriveIO.read_unit()` / `read_name()` — no such type exists in D3, and `DriverIO` is
explicitly closed. (3) Systems: *"D3's card: p50 210 ms for `parse.pdf.native`"* — that number appears
only inside an illustrative `omniweave drivers list` transcript in D3 (line 627), not as a measurement,
and the 11.7-hour PDF row of its 100k table rests on it. (4) Ecosystem: *"work rows, naive: 800k parts ×
4 PART operators = 3.2 M rows ≈ 1.3 GB"* — derive and embed are document-grain in every design here (D2
fixes `unit_part=''` for document-level structure), so the figure that motivates waves overstates by
roughly 2×. Verified true and used: surya's `VLLM_API_KEY = "EMPTY"` (`settings.py:97`),
`*_SERVER_BATCH_WAIT_MS = 5`, `default_max_batch = 8` (`batch_service/config.py:37`), the `_drain()`
coalescing comment (`server.py:79-99`), olmocr's two semaphores, anydoc's 4.4 ms median (README, 100
documents, 14 formats), graphify's `allowed_source_files` (`cache.py:1385`), codegraph's
`min(2048, max(256, dbSize/4/MiB))` WAL valve (`src/db/wal-valve.ts`), and zero OpenTelemetry emitters
across all 22 repos (jcodemunch's `otel.py` is an OTLP-JSON *parser* and imports no `opentelemetry`).

## Rejected

- **`asyncio` banned from the whole framework (systems)** — the only surviving argument is D1's 80 ms
  import budget, which is a statement about *where* the loop lives, not whether it may exist. Banning
  it also forfeits `TaskGroup` shutdown, `wait_for` deadlines and olmocr's verified two-semaphore shape,
  and replaces them with sixteen hand-managed blocking threads. Core stays asyncio-free and gated (G22);
  the loop lives one distribution up.
- **`DeriveIO.read_unit()` / `read_name()` as the dependency-recording mechanism (systems)** — it
  requires a store handle inside a driver, and D3's `DriverIO` is declared *"Not extensible"* and
  carries `blobs`, `tmpdir`, deadlines, `service`, `cancelled`, `log`, `progress` and nothing else.
  Dependencies are declared by the driver or inferred by the runner; they are never observed.
- **The `wave` table and part windows (ecosystem)** — a third scheduling noun, a fourth span level and a
  special path for oversized units, buying a bound the `queue_high_water` / `queue_low_water` hysteresis
  already provides, and adding a barrier that its own failure mode 1 identifies as the place a
  10,000-page filing stalls a corpus.
- **Sweeping `done` work rows and making `cache_index` the durable derivation record (ecosystem)** — two
  sources of truth for completion, which is precisely DataFlow's `cache_step_{N}.json` failure.
  `ow store compact` archives into `work_done`, preserving exactly what resume and the shrink guard
  read, and only above `work_compact_above`.
- **A twelfth `omniweave-otel` distribution plus an `omniweave.sinks` entry-point group (ecosystem)** —
  a third extension point created for one implementation, when D1 declined to create even
  `omniweave.operators` on the same reasoning. `ow trace export --follow` in `omniweave-serve` is live
  OTLP with one process boundary, and a broken exporter cannot break a run.
- **A four-key `run_scope_digest` allowlist (pragmatist)** — right diagnosis, wrong shape. An allowlist
  fails *open*: the next config key that genuinely changes output and is not on the list serves stale
  wrong answers forever. Classify every key with `semantic` as the unclassified default and a CI gate:
  the failure direction becomes "re-bill", which is visible, not "wrong", which is not. The same
  proposal additionally places `source_root` in the key; the salt is the walked path *relative* to
  `source_root`, so putting the absolute root in the key destroys cache portability across checkouts,
  which is the property graphify's `file_hash` exists to preserve.
- **`work.driver` alone as the batch axis, with round-robin dispatch (pragmatist)** — its own failure
  mode 6 is that round-robin over drivers discards global priority and spins on drained drivers.
  `dispatch_key` in a composite claimable index gives a batch-coherent claim as one indexed scan while
  `ORDER BY priority DESC` still holds.
- **Halve-`batch_max_units`-for-the-rest-of-the-run (ecosystem)** — one foreign process's memory spike
  permanently caps a driver's throughput. AIMD (`÷2` on OOM, `+1` after 20 clean batches) recovers.
- **A flat per-Service `max_inflight = 96` (systems)** — 96 is `MAX_AUTO_PARALLEL`, a ceiling applied to
  the server's own reported `max_num_seqs` (default 8). Capacity is derived at preflight and capped.
- **A general workflow engine (Prefect / Dagster / Temporal / Ray / Celery) or a broker** — a second
  durable store that must agree with the `work` table about what is done; a second scheduler's semantics
  between the operator and `ow why`; a service that must be running before `ow ingest` works on a
  laptop; tens of MB against D1's 250 MB `omniweave[recommended]` gate. DataFlow priced the wrapper tax:
  RayOrch needs `AcceleratedOperatorABC` subclasses and a `MemoryStorage` shim, so an operator is either
  local or distributed and porting is a rewrite.
- **A step-numbered or JSON-bag checkpoint (DataFlow, graphrag)** — eight documented failure modes,
  artifacts outside the checkpoint model and not content-addressed, a row index unstable under batching;
  and graphrag's `state: dict[Any, Any]` makes `update_clean_state` load-bearing and reordering the
  workflow list a `KeyError` hours in.
- **A runtime-level batcher that owns units, and client-side cross-document batching** — the moment a
  batcher owns units it owns accounting, retry granularity, failure isolation and the shrink guard.
  Cross-document batching falls out of `ORDER BY priority DESC, dispatch_key, id` for free, and
  server-side Coalescing additionally merges across *worker processes*, which host-side cannot.
- **A long-lived local scheduler daemon or a loopback control port** — D1 bans it and names why: LEANN's
  unauthenticated ZMQ REQ/REP on a dynamic loopback port is compute theft from any local process, and
  open-slide needs a 76-line CSRF guard as a minimum. A run-scoped child over a 0600 UDS with a 300 s
  idle TTL is not a daemon.
- **An in-memory `BudgetLedger` (D4 as written)** — a crash with outstanding reservations leaks headroom
  silently, and an untrustworthy budget gets raised until it stops firing. Thirty lines of DDL and one
  reaper clause fix it, and the same table fixes cross-process over-admission.
- **OpenTelemetry inside `omniweave-core`** — breaks D1's G1 and G9, adds a background thread and a gRPC
  channel to a path with an 80 ms budget, and has zero precedent: no repo in `_collections/` emits OTel.
- **Wall-clock lease expiry, wall-clock generations, PID-only ownership, lease stealing, and one
  `--force`** — codegraph's `Date.now()` stamps, jcodemunch #450's two-week-old locks resolving to a
  Chrome renderer, and codegraph's `STALE_TIMEOUT_MS = 2 min` unlinking a live 3-minute writer's lock.
  Store-clock expiry, integer generations, `(host, pid, process_create_time)`, one warned extension, and
  named overrides only.

## Consequences

- **D5 inherits ten tables and must not invent a second queue or a second cache index**: `unit`, `work`,
  `work_done`, `cache_index`, `dep`, `defines`, `cohort`/`cohort_member`, `budget_reservation`, `run`,
  `service_observation`. It also inherits `store_group_commit_ms` as the one place a transition may be
  batched, and the requirement that the claim work without `UPDATE … RETURNING`.
- **D7 (structure) must declare its cross-document reads.** A `derive` driver that resolves entities
  across documents either produces a `witness_set` or is treated as a cohort and re-derives wholly on
  any member change — and if it is `billed_api` and declares neither, it is refused at resolve time.
  This is a real obligation on the structure layer, and it is the price of an incremental path anyone
  can believe.
- **D8 (OUT) gets `compile/1` as an ordinary operator** with a work row, a cache key, a budget
  reservation and a `call`-layer cache entry, and inherits the rule that a Toolchain invocation is a
  `call` span with `queued_ms` separate from `ran_ms`.
- **D9 (serve) never runs the Supervisor.** `omniweave-serve` may write work rows (enqueue-before-lock)
  and read freshness derived from `work`-table state; the drain is `ow ingest`, invoked by the CLI, a
  hook, or the watcher. This keeps D1's `layers.toml` intact and keeps a read from ever blocking on a
  refresh. `degradations[]` and `Freshness` are the two runtime facts every response carries.
- **Every driver card gains three obligations the runtime reads on the hot path**:
  `isolation.batch_max_units`, `isolation.memory_mb`, and a truthful `deterministic` bit. A card that
  lies about the last one makes `ow replay --verify` a CI failure for a first-party driver and a diff
  report for a third-party one.
- **A `digest_recipe` bump (D2) no longer re-parses the corpus**, because the recipe enters a cache key
  only for operators consuming block-level artifacts. It still re-digests, which D2 budgets as at most
  annual.
- **The operator acquires four benchmark baselines to keep honest** — `ow bench scheduler`, `inproc`,
  `service`, `rss` — plus the event-vocabulary registry and D4's pricebook. Baselines drift with
  hardware and must be re-blessed deliberately; a stale baseline is a green gate that means nothing.
- **CI grows seven gates and roughly nine minutes**, of which G18 (~6 min, on merge) is the one that
  cannot be cut: it is a correctness test wearing an integration test's costume, and the day it is
  marked `xfail` the incremental path becomes quietly wrong with no symptom for months.
- **Two engineering phases are non-negotiable and usually get discovered instead of budgeted**: Windows
  parity (Job Objects instead of `RLIMIT_AS`, owner-only named-pipe DACLs, no `fork`, no `SIGALRM` — a
  `threading.Timer` plus `os._exit`, and `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, never
  `DETACHED_PROCESS`) at ~3 weeks, and the convergence pass **before** the watcher, because it is the
  invariant a watcher breaks silently.
- **Total cost: ~18 engineer-weeks for one senior engineer plus ~3 weeks of Windows parity**, in five
  phases each shipping a command a user runs — P1 roster + queue + claim + events (`ow ingest`,
  `kill -9`, `ow resume`); P2 supervisor + dispatch + AIMD + subproc host + `wire.py`; P3 `cache_index`
  + budget + middleware + `ow cost`; P4 services + `ow top` + `ow why`; P5 dep/cohort/witness + G18 +
  `ow replay`, then the three triggers with the watcher last. **Zero new third-party runtime
  dependencies.**

## Risks

- **UPSTREAM CONFLICT: D1 vs D3 on core's dependency surface, and it lands on D6's hot path.** D1
  `packages/omniweave-core/pyproject.toml`: `dependencies = []  # ENFORCED BY GATE G1. Amending this
  amends D1.` plus G9 (*"`import omniweave_core` under -X importtime loads ZERO third-party modules"*).
  D3 Consequences: *"Core's new dependency surface is `tomllib` (stdlib), a JSON Schema validator and a
  MessagePack codec — three small pure-Python-capable libraries."* D3's wire format is
  `Frame ::= u32 length_le | u8 kind | MessagePack payload` and the host lives in core, so a scheduler
  cannot be written without deciding this. **Minimum amendment: D3's sentence is replaced by "the frame
  codec is `omniweave_core.wire`, a stdlib MessagePack subset covering the D3 frame set (nil, bool, int,
  float64, str, bin, array, map), ~260 lines, parity-tested against the reference `msgpack` package
  pinned dev-only and fuzzed on the decoder (depth cap 32, element cap 1e6); full JSON Schema 2020-12
  card validation lives in `omniweave` and `omniweave-conform`, off the hot path."** Both G1 and D3's
  wire format then hold byte-for-byte. Note the file is `wire.py`, **not** `frames.py`: D2 defines
  `Frame` as a block-count-bounded run of Blocks, and two names for two things is the rule.
- **UPSTREAM CONFLICT: D3 and D4 rename `ctx.driver(kind)` to two different things.** D3 Consequences:
  *"`ctx.driver(kind)` becomes `ctx.service(name)`."* D4 Consequences: *"`mine-runtime.md` §7.1.3's
  `ctx.driver(kind)` is renamed `ctx.resource(kind) -> Resource`. … One rename, done now, before D5–D10
  write against it."* Both are stated as binding. **Minimum amendment: D4's bullet reads
  `ctx.service(name) -> ServiceHandle`.** D3 defines the concept, ships the package and already puts
  `service(name)` on `DriverIO`; D4's stated motive (free the word *Driver* for the parse-engine noun)
  is satisfied identically, and `Resource` has no other referent in D4. This ruling uses
  `ctx.service(name)` throughout.
- **UPSTREAM CONFLICT: `DriverMetrics.cost_micros` (D3) vs "no driver may price" (D4).** D3:
  `metrics: "DriverMetrics"  # ran_ms, input/output_tokens, cost_micros, bytes_read, peak_rss_bytes`.
  D4: *"Cost is a seven-unit physical `Spend` vector … that **no driver may price**"*. **Minimum
  amendment: `DriverMetrics` becomes `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls,
  bytes_egress, bytes_read, peak_rss_bytes}` and `cost_micros` is deleted from it.**
  `StepMetrics.cost_micros` survives unchanged because the *runner* computes it via the `PriceBook`.
- **UPSTREAM CONFLICT: D1's "Three seams, and no fourth" is contradicted by D3's `subproc` DriverHost.**
  D1 Spec: *"**Three seams, and no fourth.** (S1) In-process FFI … (S2) One `omniweave-target/1` child
  process … (S3) Attach-or-spawn HTTP model servers."* D3 ships a fourth: one long-lived worker per
  `(driver_id, config_digest)` over framed MessagePack on a 0600 UDS / owner-only named pipe. It is
  permitted by D1's own escape clause (*"if a later decision needs one it is a unix socket or named pipe
  at 0600, never a loopback port"*), so this is a wording conflict — and the charter will copy "three
  seams" verbatim and then contradict itself. **Minimum amendment: D1's clause reads "Four seams, and no
  fifth", enumerating S4 = the D3 `subproc` DriverHost, run-scoped with `worker_idle_ttl_s = 300`, never
  a daemon.**
- **UPSTREAM CONFLICT (not D6's to settle, but it changes every cold-start number here): D1 vs D2 on
  `omniweave-core`'s dependencies.** D1: `dependencies = []`. D2 Spec: *"`omniweave-core` depends on
  `pydantic`, `zstandard` and stdlib `sqlite3`"*, and budgets `omniweave/owdoc/` at ~15 MB against D1's
  3 MB core ceiling. Everything in this ruling is stdlib-only and designed to the tighter constraint; if
  D2 wins, G22's sibling gates and the 80 ms budget must be re-measured with `pydantic_core` on the
  import path.
- **UPSTREAM CONFLICT (minor, but every error message in the framework depends on it): two error-code
  registries.** D1 ships `codes.toml` with the grammar `OW-C-nnn / OW-S-nnn / OW-D-nnn / OW-T-nnn /
  OW-P-nnn`, append-only, gate G13. D2 ships a *separate* closed registry spelled `OW_ENCRYPTED`,
  `OW_RESOURCE_LIMIT`, `OW_TABLE_SPAN_CLAMPED`. **Minimum amendment: `codes.toml` is the single
  register; each D2 `Diag.code` is a row in it carrying both the `OW-<area>-nnn` code and its stable
  symbolic alias, and `ow explain` accepts either spelling.** This ruling emits `OW-S-014` and
  `OW-C-041` on the D1 grammar.
- **The `dep` table is only as complete as the drivers that declare witnesses.** A driver that
  under-reports produces exactly codegraph's silent staleness, and nothing detects it except G18 on a
  fixture corpus that may not exercise that driver's real dependency shape. Cohort-by-default and the
  `billed_api` refusal bound the blast radius; they do not close it. This is the most likely place this
  design is quietly wrong in year two.
- **A single document whose one page holds millions of blocks still bounds one transaction.** Generation
  staging fixes the 5,000-*page* case outright, so the residue is narrower than the panel thought: D2
  commits per page, so a 4M-cell sheet is one very large transaction, a multi-GB WAL and a multi-minute
  commit that will trip `loop_lag_max_ms`. The runtime cannot subdivide it. A sub-page commit boundary
  is D2's to grant; until then it is `MAX_GRID_SLOTS` and a `RESOURCE_LIMIT` refusal naming the knob.
- **The 1.5×–4× Coalescing speedup is unmeasured and every GPU-hour figure rests on it.** surya ships
  the mechanism and states the rationale but publishes no throughput number. At 1.5× the reference
  ingest is 52 GPU-hours, not 19, and capacity planning in every downstream document is wrong by 2.7×.
  `ow bench service` is the first thing to run.
- **`semantic`/`operational` misclassification is a human judgment in a file.** An `operational` label on
  a key that does change the answer silently reuses wrong output — worse than re-billing. G17 and the
  fail-toward-`semantic` default catch *new* keys, not a wrong judgment on an old one; `ow cache explain`
  diffing the projection between runs is the only field detection.
- **The Supervisor is a liveness single point of failure.** One loop owning dispatch and one thread
  owning the store is a correctness win and a wedge risk: a pathological `CREATE INDEX`, an NFS stall on
  the store file, or a `SQLITE_BUSY` storm blocks every worker. The watchdog (`watchdog_ms / 2`,
  `faulthandler` dump, `os._exit(70)`) and lease expiry bound it to one lease interval of lost work.
  Loud and bounded, and real.
- **A driver that reports progress forever and produces nothing burns a worker slot to `wall_ms_hard`.**
  `progress_ms` catches a silent driver; it does not catch a chatty one. With `max_workers[free] = 4`,
  four of them stall the free lane entirely.
- **`work.{driver, cost_class, dispatch_key}` are denormalised from `route_decision`.** A hand-written
  migration or a `route promote` that rewrites decisions could desynchronise them; the symptom is a
  heterogeneous `INVOKE` that the worker rejects as a config mismatch — loud, but confusing. A
  fixture-corpus test checks agreement; nothing checks the field.
- **`schema_version` not bumped is still the most expensive single mistake available**, and it lands on
  this cache: stale billed output served forever with no symptom. The only additional defence here is
  `ow cost --by driver --since 7d` showing a driver's spend fall to zero after a release — a lagging
  indicator that requires someone to look.
- **Events are dropped, never blocking, and the drop count is a `degradations[]` entry rather than a log
  line.** A saturated tracer loses telemetry; at `sample.ok = 1/64` a latency regression affecting 1% of
  units is invisible in the stream, though the manifest's percentiles are computed over all units. A
  per-unit investigation of an unsampled unit has no events at all.
- **`generation` collisions serialise run starts under heavy T2 fan-out.** Fine at ten concurrent runs,
  wrong at ten thousand — and ten thousand concurrent runs against one SQLite file is already outside
  this design's stated envelope.

## Terminology

- Supervisor := the single `asyncio` event loop in `omniweave/run/supervisor.py` that claims, admits, dispatches, completes and reaps. It executes no driver code and holds no document bytes. Exactly one per `ow` process, and it never lives in `omniweave-core`.
- Store thread := the one thread in a process permitted to hold a `sqlite3.Connection`. Every write reaches it as a transaction closure on a bounded queue.
- Roster := the `unit` table — one durable row per source document, carrying the connector cursor, the acquisition state machine, the racily-clean stat triple, `content_digest` and `part_count`.
- Work row := one `(unit_uri, unit_part, operator, op_version)` in the `work` table. The unit of scheduling, claiming, accounting, retry and failure. Identical to D4's decision grain.
- Operator := the scheduled step named on a work row: `<port>.<family>` when it invokes a driver, or `op.<name>` for a core-only step that invokes none and costs nothing (`op.identify`, `op.converge`). One generic Operator class per D3 Port; nobody outside core writes one.
- origin_operator := the first two dotted segments of the driver id, `<port>.<family>`. The eviction key: an operator's re-run replaces only rows it owns (I4). Distinct from origin_driver, which is all three segments and is the provenance and cost key.
- Plan expansion := writing one document's part rows, performed by `op.identify` after it learns `part_count` from the resolved parse driver's `sniff()` plus one `PartSelector(count_only=True)` invocation. Never eager, never guessed.
- Water mark := the `queue_high_water` / `queue_low_water` hysteresis on claimable rows at which expansion and discovery pause and resume. Backpressure pauses the producer at a safe boundary and never drops work.
- Dispatch key := `sha256(driver_id‖config_digest‖isolation)[:16]`, denormalised onto the work row by the planner. Two rows may share one `INVOKE` iff they share it.
- Batch := the set of claimed rows sharing a dispatch key sent in one D3 `INVOKE`. Invisible to the work table, the spend ledger, the trace and the failure taxonomy; visible only as span attributes.
- Coalescing := the model server's merging of requests from independent clients into one forward pass within `batch_wait_ms` up to `max_batch`. It happens in the server, never in omniweave, and it merges across worker processes.
- Service := a host-managed shared model server, named and never routed, one per `(name, config_digest)`, reached through `ctx.service(name)` and `DriverIO.service(name)`. Attach-or-spawn with model-id verification on attach and a 32-byte token in a 0600 sentinel.
- Service capacity := `min(server-reported concurrency, MAX_AUTO_PARALLEL = 96, the operator ceiling)`. Derived at preflight, never a constant.
- Staged generation := `doc.gen + 1`, the generation a document-granularity parse writes into. Readers resolve the committed `doc.gen`; the bump happens inside the completing transaction; abandoned generations are swept at startup.
- Group commit := batching, at `store_group_commit_ms`, only those work-row transitions that write zero derived rows. The single stated exception to one-transaction-per-unit.
- Cache layer := one of `blob`, `call`, `embed`, `render`, `signal`, all indexed by `cache_index`. There is no `parse` or `derive` layer: if it is a row in the `.owstore` it is never also a blob in the cache.
- Call cache := the `call` layer — a driver invocation's raw response, keyed on the cache key. It is what makes re-ingesting a corpus into a second store cost CPU-seconds rather than a re-bill.
- semantic_digest := the canonical digest of the run config restricted to keys declared `semantic`. The only run-config contribution to a cache key. `config_digest` remains the full digest and keeps its two other jobs: the manifest, and setting the full-scan latch.
- Dep := a row recording one input a derivation read outside its own unit, of closed kind `unit | part | name | cohort | policy | service_model`, carrying the digest observed at derivation time. Reverse-indexed, so invalidation is one query.
- Witness set := a closed artifact kind a `derive` driver may produce, listing the foreign `(unit_uri, unit_part, token)` tuples each produced item consulted. The only way a driver contributes deps, since it never touches the store.
- Cohort := the member set of a corpus-granularity operator, identified by a merkle over `(unit_uri, unit_part, content_digest)` in sorted order. Any member change changes the identity and re-derives the whole cohort — correct by construction, and expensive on purpose.
- Converge pass := `op.converge`, the run-final step that computes the `defines` symmetric difference, applies the dep reverse index, runs the per-unit attribution guard, and enqueues what changed.
- Budget reservation := a durable row holding an estimated `Spend` dimension against a scope until the work row commits, releases, or its lease expires. Headroom is computed in SQL. A held `(dim='calls', scope='provider')` reservation is also the cross-process in-flight count.
- Event := one record on the always-on NDJSON stream, with a `kind` from the closed append-only `tools/events.toml` registry and W3C-shaped trace ids. The span hierarchy is `run > plan > unit > attempt > call`.
- Run manifest := the incrementally-written reporting artifact at `{output_root}/runs/{run_id}.json`, carrying counts, failures by class, cache statistics, `cost.would_have_been_micros_if_uncached`, per-phase timings, and `degradations[]`. Not a log.

## Open questions

- **Is ≤ 0.5 ms/unit of runtime overhead achievable at `synchronous=NORMAL`, and what is the p99?** — every wall-clock figure here scales off it and nothing in `_collections/` measures a per-unit transactional scheduler. Settled by `ow bench scheduler`: 1 M synthetic units through the loop with a no-op operator on {NVMe, spinning disk, SMB mount}, reporting p50/p95/p99 of claim, commit and total. If p95 exceeds 1 ms, group commit must widen from zero-derived-row transitions to same-operator batches, which weakens I20 for the case it protects — a trade I want to make with a number in hand, not before.
- **What is the real Coalescing speedup for a 7B VLM at `max_batch = 8` and a 5 ms window?** — the whole GPU-hour model is a 1.5×–4× band. Settled by `ow bench service`: 2,000 pages through one vLLM engine at `max_batch ∈ {1, 4, 8, 16}` and `batch_wait_ms ∈ {0, 5, 25}`, reporting throughput and `queue_p95_ms`. If the gain is under 2×, `max_batch` should rise and the per-part `wall_ms_hard` be reconsidered.
- **What is the p95 of `dep` rows per unit on a densely cross-referencing corpus?** — `MAX_DEPS_PER_UNIT = 256` and a p95 budget of ~8 are estimates. Settled by instrumenting a 500-document legal fixture with dense internal cross-references; if it blows the budget, either the cap rises (write amplification) or cohort dependencies become the norm (over-invalidation), and both are worth knowing before D7 writes against it.
- **Does the `name` dep kind need a per-document or a per-corpus namespace?** — a section number `4.2` is corpus-ambiguous; a defined term is not. Corpus-scoping over-invalidates; document-scoping cannot express cross-document citation resolution, which is the point. Settled by D7's entity model: if a defined term already has a corpus-level surrogate key with an alias set, `name` deps key on that and the ambiguity disappears.
- **Does the anydoc eager marshal make `max_inproc = 2` right, generous, or already too high?** — D1 records the GIL-hold risk and calls for a measurement; `ow bench inproc` over `fixtures/office-200` is that measurement, reporting wall time, peak RSS and GIL-held fraction at `max_inproc ∈ {1, 2, 4, 8}` against the pure-Rust path. If the marshal exceeds ~30% of wall time, `inproc` is worth only the single-document CLI path and `inproc_bulk_threshold` should drop toward 1.
- **Should the cache key include a lockfile digest for the `free` tier?** — a pdfium or tokenizer bump changes output with no change to any operator's source, and D3 settled only the driver's own `[deps] pins`. Including the lockfile is correct and invalidates the whole free tier on every unrelated dependency bump. Settled by measuring actual output drift across one pdfium minor over a 500-document fixture: if drift is nil, per-driver pin digests suffice.
- **Does `route_signal` (D4, free tier) need a disk budget, or does `signal_version` sweeping bound it?** — if a signal's version never changes, its namespace never sweeps and the table grows with the corpus. Settled by measuring `route_signal` growth over the reference 100k ingest; if it exceeds the 2 GB default, the sweep needs an LRU component, which makes a free cache behave like a `local_compute` one and is worth knowing before it ships.
- **Is `keep_alive_s = 300` safe as an interactive default?** — a resident 7B engine holds 20–40 GB of VRAM after the run exits: correct for a developer iterating, hostile on a shared box. Settled by a policy decision plus an idle TTL on the *server*, which surya's spawn machinery does not currently provide and which we would have to add.
