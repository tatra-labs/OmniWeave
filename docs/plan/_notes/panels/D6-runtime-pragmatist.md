# D6-runtime — Execution runtime: scheduling, concurrency, caching, incremental refresh, observability
### Proposal from the shipping-pragmatist seat

---

## Headline

**Ship `mine-runtime.md` §7 essentially as written — it is already a finished design that three
upstream rulings have now made binding — and spend the entire D6 budget on the six things §7 left
undone and the four it got wrong: one asyncio loop plus D3's existing subproc worker pool (no third
concurrency mechanism), a five-layer content-addressed cache whose only new rule is "if it is a row
in the `.owstore` it is never also a blob in the cache", a two-level batching model where the
*service* coalesces across documents and the *host* only amortises IPC, `origin_operator` narrowed
to `<kind>.<family>` so ownership actually protects billable rows, `ctx.config_digest` removed from
the artifact cache key, and observability as one always-on NDJSON event stream with an offline
OTLP exporter instead of an OpenTelemetry dependency in a zero-dependency core.**

Every phase ships a command a user runs. Phase 1 lands in week 3 and it is
`ow ingest ./corpus && ow queue status && ow resume` surviving a `SIGKILL`.

---

## 0. What is already decided, and the name reconciliations I am doing rather than re-litigating

D3 makes §7 binding on me in one sentence: *"D6 (runtime) keeps `StepResult`, `Outcome`, `UnitRef`,
`RunContext`, `canonical_uri`, the `work` table and invariants I1–I18 unchanged."* I take that
literally. I1–I18 below are quoted, not restated, and I add I19–I28.

Three upstream rulings use three names for the same thing or two things for one name. None of these
is worth a conflict flag; the charter needs the mapping written down once. **I adopt the right-hand
column throughout.**

| Appears as | In | Adopted name | Why |
|---|---|---|---|
| `omniweave/core/drivers/` | D3 layout | `omniweave_core.drivers` | D1 fixes the import package: `packages/omniweave-core/src/omniweave_core/`. D1 is the packaging ruling. |
| `ctx.driver(kind)` → `ctx.service(name)` (D3) vs `ctx.resource(kind) -> Resource` (D4) | D3 Consequences / D4 Consequences | **`ctx.service(name) -> ServiceHandle`** | D3 defines the noun ("a Service … such as a vLLM engine, named and never routed"), ships `omniweave/services/`, and puts `service(name)` on `DriverIO`. D4's rename has the same motive (free the word *Driver*) and a different word. Two accessors would be a second implementation. **Flagged as CONFLICT-2 below** because D4 states its version as a binding consequence. |
| `producer.op_version TEXT` (D2) vs `work.op_version INTEGER` (§7.3.1) vs `driver_version` semver + `schema_version` int (D3) | D2 / §7 / D3 | `work.op_version INTEGER` = D3 `schema_version`; `producer.op_version TEXT` = D3 `driver_version`; `block.driver_schema_v` (D3) carries the int onto items | The int is the cache-key axis; the semver is the human axis. Both already exist in the schemas; only the shared word is unfortunate. |
| `unit_part = NULL` for document-granularity (D2 Consequences) | D2 | `unit_part = ''` | §7.3.1's DDL is `unit_part TEXT NOT NULL DEFAULT ''` precisely because *"NULLs are distinct in a UNIQUE index"*. D2's prose means the same thing. |
| `_origin` / `origin_operator` (§7.6.1) and `origin_driver` (D3) | §7 / D3 | Both, at different grains — see §5.3 | Today they would hold the same string, which makes one of them dead weight and breaks I4. |

---

## 1. The job model

### 1.1 There are exactly six Operators, forever, and nobody outside core writes one

D3 settled this: *"An Operator becomes thin — resolve a Driver, invoke it through a `DriverHost`,
translate `DriverResult` → `StepResult`. Third parties write Drivers; nobody outside core writes an
Operator."* D1 reserves the `omniweave.operators` entry-point group and does not create it.

I take the further step the two rulings imply but neither states: **there is one generic Operator
per Port, parameterised by the resolved Candidate.** Not "an operator base class with N subclasses"
— one class, five instantiations plus a sixth housekeeping operator that wraps no Port.

```
op.acquire   ← Port acquire/1     locator → UnitRefs + blobs
op.parse     ← Port parse/1       bytes + PartSelector → owstore rows via DocSink
op.derive    ← Port derive/1      owstore rows → chunks / entities / edges / fields
op.embed     ← Port embed/1       texts → vectors
op.compile   ← Port compile/1     IL + assets → artifact bytes + report
op.converge  ← no Port            the dependency-delta pass (I5), GC, rebind, index maintenance
```

This is the single largest simplification available to D6 and it falls out of D3 for free. The
consequence is that `OperatorABC.run()` has exactly one implementation body, so I1/I2/I4/I8/I13 are
enforced in *one* place rather than being properties every operator author must remember. D1's
terminology already anticipates it: *"Operator := a unit of scheduled work with a cache key and a row
in the `work` table; the framework ships operators, a distribution ships drivers."*

`OperatorIdentity` is D2's `Producer`, verbatim, because D2 ruled *"Producer := L5's
`OperatorIdentity`. One type, two layers."* I do not get to add a field.

### 1.2 The unit is `(unit_uri, unit_part)` and D4 already fixed the grain

D4: *"`mine-runtime.md` §7.12 open question 1 is settled: the router's decision grain and the `work`
row's identity are the same thing, always. A 4,000-page PDF is 4,000 parts."* D2 agrees from the
other side: *"the `work` table's unit is `(unit_uri, unit_part=page)` for parse and
`(unit_uri, unit_part='')` for document-level structure, which is what `DocSink.end_page()`'s
one-transaction-per-page commit makes true."*

So §7.12 open question 1 is closed and I do not reopen it. What is *not* closed and is mine: **a
document-granularity driver produces one work row for a document whose parse then emits many pages.**
anydoc's card says `granularity = "document"` (D3). pdfium's is `part`. So the same corpus mixes
grains, and D3 lists exactly this under its own risks (*"Mixed granularity on a large document is
unresolved"*). My answer is in §1.4.

### 1.3 The planner is a bounded generator, and it is the only writer of `work` rows

D4: *"`work.decision_id NOT NULL` means the planner is the only producer of work rows."* Combined
with §7.4.2's *"resume re-derives the plan from current inputs and config and subtracts what is
done"*, the planner is:

```
plan(scope) -> Iterator[PlannedRow]      # a GENERATOR. Never a list. Never materialised.
  for unit in discover(scope):                  # streams; connector cursor or walk
      ev  = evidence.collect(unit, part=None)   # FREE signals only at this stage
      dec = route.evaluate(policy, ev, narrowing)      # D4, pure, ~50 µs
      adm = route.admit(dec, ledger)                   # D4, impure, reserves
      if adm is Degraded:                              # budget.exhausted written back
          dec = route.evaluate(policy, ev.with_exhausted(), narrowing)   # ONE re-eval, bounded at 2
      yield PlannedRow(unit, part='', operator=port_of(dec), driver=dec.driver,
                       decision_id=dec.decision_id, cache_key=cache_key(...))
```

`plan()` never holds more than one unit. The scheduler drains it into `INSERT OR IGNORE` batches of
1,024 and **stops pulling when `queue_depth() > max_queue_depth`**, resuming at 50% — §7.3.5's
*"backpressure pauses the producer at a safe boundary; it never drops work."*

The chicken-and-egg (a decision needs evidence, evidence needs a part list, a part list needs a
parse) is resolved by D4's own ladder: `GATE` and `DECODE` decisions are made from the `unit.*`
signal group, which is available from the connector listing and a `stat` — `unit.format`,
`unit.bytes`, `unit.part_count`, `unit.encrypted`, `unit.needs_ocr_parts`. Per-part decisions are
made *after* `op.acquire` and the format probe have run, which is why acquire is itself a routed
operator at `GATE`. **No signal computation is ever a `work` row.** Signals are computed inside the
plan phase and memoised in D4's `route_signal` table, which is why D4 could specify a demand plan at
all.

### 1.4 Mixed granularity: the escalation artefact is a new work row at a finer grain

D3's unresolved case is real and cheap to solve inside the work table. A 4,000-page PDF routed
`decode.pdftext` at document granularity, of which page 3,999 escalates:

```
work(uri, '',     op.parse, driver=parse.pdf.pdfium,  status=done)      # the 4,000-page decode
work(uri, 'p3999',op.parse, driver=ocr.page.olmocr,   status=pending)   # ONE escalated part
```

Both rows are legal because `work_identity` is `(unit_uri, unit_part, operator, op_version)`. The
finer row's output supersedes the coarser one's for that part, resolved at commit by
`(doc_ord, gen, page)` in the `page` table — D2's `page.method` column records *"the branch that ran
on THIS page"* precisely for this. The shrink guard (§5.4) treats a coarse-grain unit and its escalated
parts as one attribution set, keyed on `unit_uri`, so a page moving from the coarse owner to the fine
owner is an accounted loss. **The cost model works because D4 apportions:** `route_spend` rows key on
`decision_id`, and `route_unit_decision` maps both rows back to one `unit_uri`.

---

## 2. Concurrency: one loop, two threads, N driver processes, nothing else

### 2.1 The decision

| Mechanism | Used for | Count | Why not something else |
|---|---|---|---|
| **one `asyncio` event loop** in the scheduler process | claim/complete, socket IO to driver workers, HTTP to Services, orchestration | 1 | Everything the parent does is IO. D1 forces 3.11, which gives `TaskGroup`/`ExceptionGroup`. olmocr's production pipeline is the precedent: `pipeline.py:87-88` runs two `asyncio.BoundedSemaphore`s and pushes CPU work through `asyncio.to_thread`. |
| **the store-writer thread** | every `sqlite3` write, one bounded `queue.Queue` of closures | 1 | `sqlite3` connections are not shareable across threads, and a 250 ms commit on the loop violates I15. One writer also makes D2's *"one writer per `.owstore`"* structurally true inside a process. |
| **the blob/CAS thread** | streaming writes to `cache_root/blobs/`, fsync, rename | 1 | Same reason; a 40 MB asset write must not block the loop. |
| **`inproc` driver invocations** | D3-eligible first-party drivers only, via `asyncio.to_thread` | `max_inproc = 2` | See §2.2. |
| **`subproc` driver workers** | every third-party driver, every GPU driver, every driver with egress | `max_workers[cost_class]` per `(driver_id, config_digest)` | D3 owns this; I add nothing. |
| ~~`multiprocessing` / Ray / Celery / Dask / a task broker~~ | — | 0 | D3 already ships a worker protocol with a supervisor, a circuit breaker, per-OS limits and a wire format. A second process abstraction is an abstraction with one implementation. T3 is *"the same claim protocol against a shared store"* (§7.10.1) — `SELECT … FOR UPDATE SKIP LOCKED` and nothing else changes. DataFlow's RayOrch is the counter-example: `AcceleratedOperatorABC` subclasses plus a `MemoryStorage` shim, *"so an operator is either local or distributed and porting is a rewrite"* (§1.7). |

### 2.2 `max_inproc = 2`, and it is an honest number, not a conservative one

D1 states the constraint in its own risk register: *"`anydoc/python/src/document.rs` states 'converted
eagerly into Python objects', and `py.detach` covers the Rust decode but **not** the marshal, so the
GIL is held for a duration proportional to document size, so thread-pool scaling is worse than the
GIL-release story suggests and must be measured rather than assumed."*

So the default is 2, not `cpu_count()`, and `ow doctor` prints:

```
inproc concurrency: 2 (GIL-bound: the anydoc marshal holds the GIL for the whole document).
  Raise [runtime].max_inproc only after `ow bench inproc --corpus fixtures/office-200`
  shows wall time falling. Recorded baseline: <none>.
```

`ow bench inproc` is the benchmark D1's open question #1 asks for, shipped as a command rather than
promised as a task. If it shows the marshal under ~30% of wall time the default moves; if it shows
over, D1's fork trigger fires and D6 was right to be conservative.

### 2.3 `TaskGroup` is used for shutdown and for nothing else

The 3.11 gotcha that will otherwise cost a day: `TaskGroup` cancels every sibling on the first
unhandled exception. That is exactly wrong for a scheduler, where one driver crash must cost one
unit. So:

- The scheduler runs a fixed set of long-lived `worker_loop()` tasks, one per slot, each wrapped in
  a `try/except BaseException` that converts *everything* into a `StepResult` and never propagates.
  D3 requires this anyway: *"A crashing driver never aborts the run."*
- `TaskGroup` wraps only the top-level `{planner, workers, reaper, lag_monitor, heartbeat}` set, so
  `Ctrl-C` gives a structured drain: stop claiming, let in-flight units finish or hit their lease,
  flush the event stream, write the manifest, `SHUTDOWN` every worker with `grace_ms`.

### 2.4 The admission gate

```python
@dataclass(frozen=True, slots=True)
class Admission:                                  # §7.3.5, verbatim, plus two rows
    max_inflight: Mapping[CostClass, int]         # FREE 32 · LOCAL_COMPUTE 4 · BILLED_API 2  (D1)
    max_inflight_per_provider: Mapping[str, int]
    max_queue_depth: int = 50_000                 # producer pauses above; resumes at 50%
    max_inproc: int = 2                           # §2.2
    max_workers: Mapping[CostClass, int] = ...    # D3 [drivers] max_workers: process ceiling
```

**D1's `[budget] max_inflight` and D3's `[drivers] max_workers` are different things and both are
kept.** `max_inflight` bounds *units in flight* (an admission decision); `max_workers` bounds
*processes* (a resource decision). Effective slots per class = `min(max_inflight[c],
max_workers[c] × batch_size)`. `ow show-config` prints all three numbers and the resulting slot
count, because two knobs that multiply is exactly the shape nobody can debug from a log line.

### 2.5 Two named wait budgets, never a constant

`INTERACTIVE_WAIT = 2 s`, `BATCH_WAIT = 60 s`, passed per call. §7.3.4's evidence: *"jcodemunch
repeats `wait_seconds=60.0` at four call sites and its own server comments call a 60 s wait the
outcome to avoid."*

---

## 3. Batching: two levels, and only the lower one touches the GPU

This is where the task's *"one inference manager many heads (surya)"* and *"batching across documents
to keep a GPU fed"* actually live, and the two are not the same mechanism.

### 3.1 Level A — the host INVOKE batch: amortises IPC, invisible to the work table

D3 owns the frame: *"One `INVOKE` carries up to `batch_max_units`; one `RESULT` per unit, so **the
batch is invisible to the `work` table**."* D6 owns how a batch is *formed*, and that requires one
schema change:

```sql
ALTER TABLE work ADD COLUMN driver TEXT NOT NULL;         -- denormalised from route_decision
CREATE INDEX work_claimable ON work(driver, status, retry_after, priority DESC, id)
    WHERE status IN ('pending','failed_transient');
```

The claim must return a *homogeneous* batch — one driver, one config — or the batch cannot be a
single `INVOKE`. Joining `route_decision` inside the claim predicate on a 600k-row table is the hot
path and I will not pay it; `driver` is denormalised and a CHECK-equivalent test asserts
`work.driver == route_decision.driver` on the fixture corpus.

`claim(driver, batch)` batch sizes: **256 FREE, 32 LOCAL_COMPUTE, 8 BILLED_API**, then clamped by
`min(card.isolation.batch_max_units, adaptive_batch[driver, config])`.

**AIMD on the adaptive batch, because §7.3.2 already mandates the decrease:**

```
on OOM or WORKER_DIED:      batch := max(1, batch // 2)        # §7.3.2: "halves the batch size"
on DRIVER_CRASHED:          batch := 1 for the retry           # D3: "retries once at batch = 1"
after 20 consecutive clean batches: batch := min(batch + 1, card.isolation.batch_max_units)
```

Additive increase, not multiplicative: a driver that OOMs at 32 and recovers at 16 should not jump
back to 32 on the next clean batch. The adaptive value is per `(driver_id, config_digest)`, held in
memory for the run and reported in the manifest.

**I23: a batch is never a failure unit.** A crashed `INVOKE` re-invokes at `batch = 1` across the same
units *before* any unit is marked failed; only the unit that crashes alone gets
`FAILED_PERMANENT{DRIVER_CRASHED}`. Enforced by a fault-injection test that poisons unit 7 of 32 and
asserts 31 `ok` rows and 1 `failed_permanent`.

### 3.2 Level B — the Service coalesces across documents, and that is what fills the GPU

This is surya's, verbatim in shape, and it is the only mechanism in the collection that keeps a GPU
fed from many independent clients. `surya/common/batch_service/server.py:79-99`:

> *"Block for one job, then coalesce more arriving within the wait window, up to the batch ceiling.
> This is the continuous-batching step: units from independent client requests merge into one
> forward."*

Defaults verified in `surya/settings.py`: `*_SERVER_BATCH_WAIT_MS = 5`, `*_SERVER_MAX_BATCH = None`
with `default_max_batch = 8` in `batch_service/config.py:37`.

The composition is the point:

```
N subproc driver workers  →  each holds ≤ batch_max_units parts from ONE document
        ↓ HTTP (attach-or-spawn, model-id verified)
1 Service per (service_name, model_id, config_digest)
        ↓ _Batcher._drain(): block for 1, coalesce ≤ batch_wait_ms, ceiling max_batch
1 forward pass containing parts from up to `max_batch` DIFFERENT DOCUMENTS
```

**The runtime never batches across documents itself.** It cannot: D3 forbids a driver from seeing
another unit's data, and cross-document batching in the scheduler would put document boundaries into
the host's hot loop for no benefit. Coalescing at the server is strictly better because it merges
across *worker processes* too, which host-side batching cannot do.

`omniweave_core.services` (D1's `modelserver.py`, D3's `omniweave/services/`) is surya's
attach-or-spawn wholesale, including the two details that make it work and that everyone reimplements
wrong:

- **Model-identity verification on attach.** `GET /v1/models`, compare to `expected_model_name`,
  refuse with a message naming both. Kills the "attached to yesterday's model" class outright.
- **The unlocked fast path must not mutate the sentinel.** surya's own comment
  (`inference/backends/spawn.py`): *"when many clients cold-start at once, one holds the lock
  mid-spawn with its server still loading (so it reads unhealthy here). If an unlocked waiter deleted
  the sentinel on that 'unhealthy' read, it would then acquire the lock, find no sentinel, and spawn a
  second server."* Two GPU servers on one card is a 2× VRAM bill and an OOM.
- Lazy spawn: **a clean digital corpus never starts a GPU server.** D4's R4 already gates this from
  the evidence side (*"a test asserts a clean born-digital PDF computes zero `LOCAL_COMPUTE` signals
  and spawns no inference server"*); the Service's laziness is the enforcement.
- One Service, many **heads**: `ServiceHandle.generate(head, items)` where `head ∈ {layout,
  recognition, table_rec, page}`. surya's `LayoutPredictor(manager)` / `RecognitionPredictor(manager)`
  / `TableRecPredictor(manager)` sharing one `SuryaInferenceManager` is exactly this, and
  `surya/settings.py:173-178` states the reason: *"there's no benefit to more than one layout model
  on a host, and N in-process copies thrash the CPU/GPU."*

### 3.3 Separate the CPU-render semaphore from the GPU-inference semaphore

olmocr `pipeline.py:87-88`, and it is `mine-parse.md` B8's rule 15. Page rendering (pdfium →
192-DPI raster, 10.7 MB per A4 page per D2) is CPU and runs under
`render_slots = BoundedSemaphore(cpu_count - 2)`; inference runs under the per-provider
`max_inflight_per_provider`. Sharing one semaphore starves whichever side is slower — and at D2's
numbers, rendering all 5,000 pages of one document is **53 GB**, so render *must* be demand-driven
and immediately evictable, which is why D2 made `page_render` a derived cache with `last_used_ns`.

---

## 4. The cache: five layers, one key function, one new rule

### 4.1 The key

§7.5's three groups, unchanged in shape, with three amendments — one settled upstream, two mine.

```python
def cache_key(unit: UnitRef, ident: OperatorIdentity, card: DriverCard, ctx: RunContext) -> str:
    payload = {
      "unit": {"digest": unit.content_digest,           # §7.5.1 normalised load-bearing bytes
               "salt":   unit_salt(unit, ctx.roots),    # walked path rel. to source_root, normcased
               "part":   unit.part or ""},
      "op":   {"name":            ident.operator,       # D2 Producer field names, verbatim
               "schema_version":  card.schema_version,  # D3: "it ALONE enters the cache key"
               "code_fingerprint": ident.code_fingerprint,
               "model_id":  ident.model_id  or "",
               "model_rev": ident.model_rev or "",      # exact sha; "main" is a lint error (D2)
               "prompt_fp": ident.prompt_fp or "",
               # D3 settled §7.12 open question 4: the dep-pin digest enters the key for FREE only.
               "deps": deps_digest(card) if card.cost.klass is CostClass.FREE else ""},
      "cfg":  {"op":  ident.options_digest.hex(),       # per-driver effective config
               "run": ctx.run_scope_digest},            # ★ AMENDED — see 4.2
    }
    return sha256_canonical(payload)
```

`sha256_canonical` is D1's `omniweave_core.canonical.sha256_canonical`: sorted keys, `allow_nan=False`,
`separators=(",",":")`, and **an un-canonicalisable value is a startup error, never a `str()`
fallback** — graphrag's `make_yaml_serializable` fallback produces *"objects with address-bearing
reprs … a new key every run: permanent silent cache miss"* (§2.12 #6). D1 already made this a
startup error for driver config; I extend it to every key input.

`sha256_canonical` is never `"".join(values)`: graphrag's `gen_sha512_hash` concatenates without a
separator so `["a","bc"]` and `["ab","c"]` collide (§2.11).

### 4.2 Amendment: `ctx.config_digest` is replaced by `ctx.run_scope_digest` in the artifact key

§7.5 puts `ctx.config_digest` — *"the digest of the **effective** run config"* — into every artifact
cache key. **That is a defect and it is the single most expensive line in §7.** Under it, changing
`[targets.video] codec` from `vp9` to `av1`, or adding a driver to `[drivers] enabled`, invalidates
every parse, every extraction and every embedding in the corpus, including the `BILLED_API` tier
that §7.5.2 goes to great lengths never to sweep. The whole two-tier invalidation design is defeated
by one field in the key.

```python
run_scope_digest = sha256_canonical({
    "limits":     effective_limits_dict,      # clamped ceilings actually change output
    "source_root": ctx.roots.source,          # the salt anchor
    "normalizers": NORMALISER_REGISTRY_VERSION,   # §7.5.1: changes what bytes are hashed
    "digest_recipe": store.meta["digest_recipe"], # D2: a recipe bump is a re-digest pass
})
```

Four keys, each of which provably changes some artifact. The **full** `config_digest` keeps its other
two jobs from §7.5.3 untouched: it appears in the run manifest, and a change to it **sets the
full-scan latch** (§7.9). So a config edit still forces a full reconcile; it just does not re-bill the
corpus. This is a change to a mining note, not to a ruling, and it is the reason I flag nothing here.

### 4.3 The five layers, and the rule that keeps them from doubling storage

| # | Layer | Location | Key | Tier | Swept? |
|---|---|---|---|---|---|
| **C0** | raw bytes + large binaries | `cache_root/blobs/ab/cd/<sha256>` | `sha256(bytes)` — nothing else | — | refcount GC only (`ow gc`) |
| **C1** | routing evidence / signals | `route_signal` table (D4) | `(content_digest, unit_part, signal_key, signal_version)` | FREE | old `signal_version` namespaces swept per signal |
| **C2** | **driver raw responses** | `cache_root/resp/<key[:2]>/<key>.zst` + `cache_entry` row | `cache_key()` | by `card.cost.class` | FREE swept; LOCAL_COMPUTE by liveness; **BILLED_API never** |
| **C3** | embeddings | `cache_root/emb/<embedder_key>/<content_digest>.f32` | `(block content_digest, embed driver identity, options_digest)` | LOCAL_COMPUTE or BILLED_API | liveness only |
| **C4** | page renders | `page_render` table + C0 blob (D2) | `(doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)` | FREE | LRU on `last_used_ns`, hard cap `[runtime] render_cache_bytes` |

**I20 — the rule that makes this affordable: if it is a row in the `.owstore`, it is never also a
blob in the cache.** D2 ruled *"one store, never a model plus a sync layer"*; a parse-result cache
beside the store would be that sync layer with a second name. So there is no C-layer for parsed
blocks. The memoisation of a parse is: the `work` row is `done`, its recorded `cache_key` matches the
planned one, and `doc(doc_key, gen)` exists.

**And here is why that is still cheap for the billable tier.** C2 caches the *driver's raw response* —
the VLM's YAML-front-matter page text, the LLM's extraction JSON, the toolchain's receipt — not the
derived rows. Re-parsing the same PDF into a *different* corpus therefore replays 116,000 cached VLM
responses at zero marginal cost and re-derives the rows from them in CPU seconds. This is the property
that makes "ingest the same corpus into a second project" affordable, and it is unrepresentable if
you cache the derived rows instead of the response.

### 4.4 Two invalidation tiers, chosen by who pays for a miss (§7.5.2, unchanged)

| `cost.class` | Namespaced by | Old namespaces | On a `schema_version` bump |
|---|---|---|---|
| `free` | `op/{name}/v{schema_version}-c{code_fingerprint}-d{deps}/` | **swept on first use** | full invalidation, silently |
| `local_compute` | same, plus `cfg/{options_digest}/` | swept **by liveness only** | nothing; expires by liveness |
| `billed_api` | `cfg/{options_digest}/` — **not** by code version | **never swept**; liveness-pruned | nothing at all |

graphify says the second half out loud (§3.2): two hosts with different prompts sharing one output dir
must not *"each run delete the other's entries and re-bill extraction on every alternation."* Growth
bound, printed in `ow cache status` in these words: **`live units × configurations seen`**.

**I26: an automatic sweep never deletes a `billed_api` entry.** Deleting one requires
`ow cache prune --allow-rebill`, which prints the count and the `would_have_been_micros` it is about
to throw away. §7.6.3's rule applies: *"an override flag whose scope is 'skip whatever check just
complained' is not an override, it is an off switch."*

### 4.5 Miss policy is the cache's business, not the caller's (§7.5.4)

Six clauses, verbatim, with clause 2's improvement kept: **a corrupt entry is counted, reported, and
overwritten on the next success**, which self-heals without a flag. graphify counts them and leaves
them on disk, so *"a corrupt entry stays on disk and fails again every run."*

Clause 4 — *"entry fails the operator's `is_valid_nonempty`"* — is now enforceable in one place,
because D3 put `is_valid_nonempty(ref) -> bool` on the `ParseV1` protocol and stated the rule: *"the
host converts an `ok` failing `is_valid_nonempty` into `FAILED_PERMANENT(EMPTY_RESULT)` **before
anything is cached**."*

### 4.6 Cache poisoning (I13)

graphify's write allowlist, verified at `graphify/cache.py:1385` — the parameter is
`allowed_source_files: Iterable[str | Path] | None`, and `cache.py:1410` states the rule: *"only those
files may be used as …"*. It is the only cache-poisoning control in twenty-two repositories.

```python
cache.put(entries, allowed_units=frozenset(claimed_units))     # runner-supplied, never driver-supplied
```

D3 makes this structural rather than policed: a Driver receives `DriverIO`, which has *no* cache
handle, *no* store handle and *no* writable root. So the poisoning surface is one call site in the
runner. **The allowlist is still enforced**, because the runner is also the thing that could get it
wrong on a batch: the allowed set is the units of *this* `INVOKE`, not of this run.

### 4.7 `policy_digest` and `pricebook_digest` are decision-key inputs and never artifact-key inputs

**I19.** D4 puts them in `route_decision`'s identity. If they leaked into `cache_key()`, tuning
`garble_escalate` from 0.50 to 0.48 would re-bill the corpus, which is the exact failure D4 legislates
against from the other side: *"A policy change invalidates decisions but must never invalidate
artifacts."* Enforced by a unit test that asserts the `cache_key` payload's key set equals a frozen
literal.

---

## 5. Incremental invalidation, ownership, and convergence

### 5.1 What invalidates what — the whole table, because this is where systems rot

| Change | Invalidates | Mechanism |
|---|---|---|
| source bytes change | that unit's every layer | new `content_digest` → new `cache_key` → work-row `cache_key` mismatch → reset to pending; D2 `rebind` carries `block_id`s into the new `gen` |
| source metadata-only touch | **nothing** | `normalise_for_hash` strips `/ModDate`, `w:rsid*`, frontmatter, EXIF before hashing (§7.5.1) |
| mtime touch, identical bytes | nothing, and it is not even read | `_stat_sig_fresh`: `size == st_size ∧ mtime_ns == st_mtime_ns ∧ st_mtime_ns + 2e9 <= indexed_at_ns`, with `indexed_at_ns` captured **before** the read |
| driver `version` bump (semver only) | nothing | not in the key |
| driver `schema_version` bump | that driver's artifacts, all tiers | in the key. D3's own risk: *"forgetting to bump it silently serves stale cached output … the most expensive single mistake available in the design."* |
| driver `[deps] pins` change (pdfium, tree-sitter, tokenizer) | **FREE tier only** | D3 settled §7.12 open question 4 |
| driver config change | that driver's artifacts | `options_digest` |
| run config change | full-scan latch; **no artifacts** | §4.2 |
| policy / threshold / pricebook change | decisions only | D4: `reused_above_policy`; a lower existing rung with a `BILLED_API` upgrade enqueues `needs_upgrade` as `DEFERRED_BUDGET` |
| `digest_recipe` bump (D2) | every content-addressed cache in the fleet | in `run_scope_digest`. D2 prices it: *"a re-digest pass rather than a re-parse. Budget it as at most annual."* |
| a document is deleted | its rows, all owners, by cascade | `ON DELETE CASCADE` + `foreign_keys = ON` — replaces graphify's 290 hand-rolled eviction lines |
| a *cross-document* answer's input changed | the dependents | §5.2 |

### 5.2 The dependency delta — the only new mechanism I am adding, and I5 requires it

codegraph measured **4.3% of distinct edges wrong, in both directions, silently, forever until a full
rebuild**, from skipping this one pass (§4.5.3). digest-graph names the document analogue: *"section
numbers, figure labels, defined terms, citation keys, table ids."* D2's `rel` kinds `anchor_ref` and
`note_ref` and D5's forthcoming citation resolution all mint these.

Two tables, and they are small:

```sql
-- A resolvable name a unit DEFINES. codegraph's `file\0name` pairs, as rows.
CREATE TABLE defines (
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,            -- section | figure | table | term | citekey | anchor
  name TEXT NOT NULL,            -- normalised by ONE function, shared with the resolver
  gen  INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, kind, name)
) WITHOUT ROWID;

-- A resolution a unit's derivation DEPENDED on. Written by op.derive / op.converge.
CREATE TABLE dep (
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  operator TEXT NOT NULL,        -- the dependent's owner
  kind TEXT NOT NULL, name TEXT NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, operator, kind, name)
) WITHOUT ROWID;
CREATE INDEX dep_name ON dep(kind, name);
```

`op.converge` computes, exactly as codegraph does, the **symmetric difference of `(kind, name)` pairs
across the store phase** — sampled before the unit's rows are replaced, diffed after — and re-queues
every `dep` row matching a changed name. **A body-only edit leaves the delta empty, which is the
common case and free.**

And the gate, because a dependency record with no equivalence test is a comment:

**CI gate `incremental-vs-full` (I5).** Over `fixtures/corpus-incremental/` (40 documents with
deliberate cross-references): run a full ingest into store A; run a staged incremental — 12 edits, 3
deletions, 5 additions — into store B; assert **every table byte-equal** after normalising `block_id`
allocation order and run-scoped columns. This job is expensive (~4 min) and runs on every PR touching
`omniweave/run/` or `omniweave_core/cache.py`. It is a correctness test, not a perf test, and it is
never marked flaky.

### 5.3 Stage ownership, narrowed: `origin_operator` is `<kind>.<family>`

§7.6.1's I4 is the whole defence against *"a free structure re-extraction silently deleting every
LLM-derived row for that unit."* But if `origin_operator` were the Port (`op.derive`), a free chunker
re-run would own — and therefore delete — the billed entity rows. And if it were the full driver id
(`derive.chunk.recursive`), swapping the chunker implementation would leave the old chunks orphaned
forever.

**So `origin_operator` is the first two segments of D1's registry-key grammar and `origin_driver` is
all three.** D1 fixes the grammar as `<kind>.<family>.<impl>`, so this is mechanical, not a judgement
call:

```
origin_operator = "derive.chunk"                 # the JOB — the eviction key (I4)
origin_driver   = "derive.chunk.recursive"       # the IMPLEMENTATION — the provenance and cost key
```

`derive.chunk` re-running replaces `derive.chunk` rows and cannot touch `derive.entities` rows. That
is I4, made true. And it resolves the redundancy between §7.6.1's `origin_operator` and D3's
`origin_driver`, which would otherwise hold the same string on every block.

**Parse is the exception and D2 already handles it:** a re-parse mints a new `gen`, and `rebind`
carries `block_id`s forward or quarantines below threshold. Ownership governs eviction *within* a
generation only.

The runner stamps five columns on every produced item, and no driver may set any of them (D3-8):

```
origin_operator   <kind>.<family>              §7.6.1 — ownership
origin_driver     <kind>.<family>.<impl>       D3 — provenance
driver_schema_v   card.schema_version          D3
restriction_bits  from card licence facts      D3 — "may I ship this deck" is an indexed query
decision_id       from route_decision          D4
```

### 5.4 The per-unit attribution guard (§7.6.3)

Per-unit, not global; row-set comparison, not a count; `O(delta)`, not `O(existing × new)`; quarantines
one unit instead of aborting the run. And the starred clause, which is what makes it sound:

> **A loss is NEVER accounted by a unit whose derivation FAILED this run.** *"Files in `failed_sources`
> never account for lost nodes: extraction did not complete, so their disappearance is the silent
> shrink this guard protects."*

Unaccounted loss ⇒ refuse that unit's transaction, `failed_permanent(UNEXPLAINED_LOSS)`, one manifest
row. Named override: `--allow-unexplained-loss`. Never `--force`.

Fail-closed on the baseline: *"could not read the baseline"* and *"there is no baseline"* are different
outcomes, and I12's lint rule (no bare `except` around `content_digest`, `config_digest`,
`code_fingerprint`, or a baseline load) is a semgrep rule in D1's `tools/semgrep/omniweave.yaml`, not a
convention.

---

## 6. Checkpoint, resume, and the 100k-document walkthrough

### 6.1 There is no checkpoint file (§7.4)

```
INVARIANT: a completed operator pass removes every row it claimed from the claimable set.
THEREFORE: after any crash, SIGKILL or Ctrl-C, the 'claimed' rows with expired leases plus the
           'pending' rows are EXACTLY the unfinished work.
THEREFORE: recovery is running the normal command, and the healthy-store check is one indexed COUNT.
```

Resume **re-derives the plan from current inputs and current config and subtracts what is done**. It
never replays a recorded plan — because between the crash and the resume the source, the config, the
operator version and the *scope* may all have changed, and codegraph #1590 shows what replaying a
plan costs: *"the watcher re-parsed a file the user had just excluded … an oscillation, not a one-time
error."*

`stale_since` is **kept** across a reset and set on the first transition only: it measures how long
the answer has been untrustworthy, not how long the attempt has run.

### 6.2 One transaction per unit, and what is inside it

```
BEGIN IMMEDIATE
  ... the unit's owstore rows (blocks / marks / rels / grids / diags), via DocSink
  ... route_spend row(s) for this decision's attempts                  ← I25
  ... budget commit(reservation, actual)
  UPDATE work SET status=:s, ... WHERE id=:id AND claimed_gen=:gen AND status='claimed'
COMMIT
```

`rowcount == 0` ⇒ the row was reclaimed at a newer generation ⇒ **the whole transaction rolls back**
and the result is discarded. §7.8.1: *"the claim IS the lease and the generation check is a predicate
on it"* — no extra lock. Generations are monotonic integers, never a clock, because *"a backward NTP
step makes a serviced entry permanently stale or silently evicts an unserviced one."*

**I25: every billable Spend commits in the same transaction as the work-row transition that produced
it.** Otherwise a crash between them produces either unbilled work or a charge for a unit that will
be redone. Nothing in the collection gets this right because nothing in the collection has a cost
ledger at all.

### 6.3 The reference ingest: 100,000 documents

Composition: 70k office (anydoc, `granularity = document`), 25k born-digital PDF, 5k scanned PDF,
mean 12 pages.

| Quantity | Count | Basis |
|---|---:|---|
| `op.acquire` work rows | 100,000 | one per document |
| `op.parse` work rows | 70,000 + 300,000 + 60,000 = **430,000** | office at document grain; PDF at part grain |
| escalated parts | ~116,000 | 60k scanned + 18.8% of 300k digital (D4's stated escalation rate) |
| `op.derive` + `op.embed` rows | 200,000 | document grain |
| **total `work` rows** | **~730,000** | ~200 B/row + 3 indexes ≈ **~220 MB** |
| `route_decision` + evidence + spend | ~730,000 decisions | D4's own figure: ~1 GB/million parts, → **~730 MB**, ~260 MB after the 30-day evidence sweep |
| VLM calls | ~116,000 pages | |
| GPU time, single-stream | 116k × 2.4 s = **77 GPU-hours** | D3's `p50_ms_per_unit` card example for `parse.ocr.olmocr` |
| GPU time, coalesced at `max_batch = 8` | **≈ 19 GPU-hours** ⇒ ~1 day on one A100, ~3 h on eight | assumes 4× throughput from continuous batching — **derived, not measured; the first thing `ow bench service` must check** |
| billable tier at olmocr's published self-hosted rate | ~$23 | `<$200/1M pages`. D4 records a **3.4×** spread against a naive `gpu_ms` estimate; the ledger exists precisely because of that spread |
| peak RSS, scheduler process | **target ≤ 900 MB**, CI-gated | see §6.4 |
| event stream | 730k units × ~8 events × ~180 B ≈ 1.0 GB raw → **~100 MB** zstd-3, sharded at 64 MiB | |

The free tier is not the problem: 70k office documents at anydoc's measured 4.4 ms median (its own
README benchmark, 100 documents, versus 134.8 ms markitdown and 513.6 ms docling) is ~5 CPU-minutes
of actual decode. The scheduler is the risk, so it gets a gate: **`ow bench scheduler` drives 100,000
no-op work rows through `claim → complete` in ≤ 60 s single-process (≈1,700 transitions/s), on
ubuntu/3.11, ±25% against a recorded baseline.** If the scheduler cannot sustain that, the free tier
is scheduler-bound and every other number is fiction.

### 6.4 Not OOM — the five mechanisms, each with an enforcer

1. **The planner is a generator and discovery streams.** Semgrep bans `list(discover(...))` and
   `sorted(discover(...))` in `omniweave/plan/`.
2. **`DocSink.end_page()` commits one transaction** (D2), so a 5,000-page document never exists in
   memory. D2 sized it: 300k–600k blocks, ~200 MB of store, and the `Frame` (block-count-bounded,
   target 8,192) is the streaming unit.
3. **Page renders follow routing and are evicted.** A 192-DPI A4 page is 10.7 MB decoded (D2); all
   5,000 pages of one document is ~53 GB. `render_cache_bytes` defaults to 2 GB with LRU on
   `page_render.last_used_ns`, and the render semaphore bounds how many exist at once.
4. **The parent never holds a unit's content.** **I21:** the scheduler process holds `UnitRef`s and
   `ArtifactRef`s (digests) only; anything over D3's `INLINE_MAX = 262144` travels as a blob
   reference. Enforced by a semgrep rule banning `.read()` on a source path outside
   `omniweave_core.blobs`, plus the peak-RSS gate.
5. **Driver workers are RSS-capped and an OOM costs one unit.** D3's `isolation.memory_mb`, applied
   as `RLIMIT_AS` (linux) / `RLIMIT_DATA` (darwin, *"`RLIMIT_AS` is unreliable under Apple's
   libmalloc"*) / a Job Object (Windows). `OOM` is a transient class that **halves the batch**. In
   process, D1's pathological 4M-cell XLSX takes the run down; out of process it is one row and a
   `RESOURCE_LIMIT` diag naming which knob would need raising.

**CI gate `peak-rss`:** `ow ingest fixtures/corpus-rss/` (includes D2's `gen-5000p.pdf` and
`merged-4m-cell.xlsx`) with `/usr/bin/time -v`, asserting scheduler peak RSS ≤ 900 MB and no worker
exceeding its declared `memory_mb`.

### 6.5 The watchdog rule, restated for an event loop (I15)

§7.8.3's most expensive lesson is codegraph's: four `CREATE INDEX` at ~20 s each = 79 s against a 60 s
liveness watchdog meant *"a daemon-triggered re-index was SIGKILLed right after doing the work — the
most expensive failure available is one that discards completed work."*

In an asyncio scheduler, "no synchronous stage exceeds `WATCHDOG_MS / 2`" becomes **"the event loop is
never blocked longer than `LOOP_LAG_MAX`"**, and it needs a measurement, not a rule:

```python
async def lag_monitor(sink: StatsSink, period_s: float = 0.1) -> None:
    t = monotonic_ns()
    while True:
        await asyncio.sleep(period_s)
        now = monotonic_ns(); lag_ms = (now - t) // 1_000_000 - int(period_s * 1000); t = now
        sink.observe("loop_lag_ms", lag_ms)
        if lag_ms > LOOP_LAG_MAX_MS:                    # 250 ms
            degrade("scheduler", f"event loop blocked {lag_ms} ms")   # one-way latch → I18
```

**I24**, enforced by the monitor at runtime and by a CI assertion that p99 loop lag on the fixture
corpus stays under 250 ms. Cooperative yields every `YIELD_INTERVAL = 1000` items, **at the top of
the loop body so `continue` fast-paths still hit it**.

Bulk phases get codegraph's index window (`2.8 s → 1.1 s` for a 224k-edge insert by dropping and
recreating five indexes, recreation ~0.3 s) and the WAL valve, verified at
`codegraph/src/db/wal-valve.ts:64-75`: `min(2048, max(256, dbSize/4/MiB))` MB, hard cap 2×, file cap
4× ⇒ TRUNCATE at a parked barrier, 20 passes, then the **futility latch** — 2 consecutive give-ups ⇒
disable for 60 s ⇒ degrade to un-valved behaviour (**I9**), because the un-latched valve produced
*22 GB of WAL and an exit-137 OOM at an envelope the un-valved build survived*.

---

## 7. Multi-writer, which D2 handed me

D2: *"One writer per `.owstore`. Multi-writer is D6's problem, not the model's."* It is a smaller
problem than it looks, because D3 already removed the hard case: **a Driver never receives the store**
(D3-7). So driver worker processes are not writers at all.

| Situation | Answer |
|---|---|
| N driver workers | never touch the store. The scheduler writes on their behalf. |
| N tasks inside one scheduler | one store-writer thread with a bounded queue (§2.1). |
| 2 scheduler processes (a `ow ingest` and a PostToolUse hook) | both may claim; the claim `UPDATE` is atomic and each writes only its own claimed units in short transactions. WAL + `busy_timeout = 5000` is exactly designed for this. |
| bulk phases (migration, index drop/recreate, WAL TRUNCATE, `ow gc`) | a **coarse `store.bulk` scoped lock**, jcodemunch's shape: `O_CREAT\|O_EXCL` + JSON metadata + `flock` on POSIX + `(host, pid, process_create_time)` liveness + `inspect()` without acquiring + `held()` exposing `waited_seconds` and naming the holder past 1 s. |
| read-only consumers (hooks, CLI, MCP server) | `connect_readonly`: `mode=ro` when a WAL sidecar exists, `mode=ro&immutable=1` when it does not — because opening WAL SQLite `mode=ro` *creates* the sidecars and moves the mtime a freshness check reads, and `immutable=1` against a live WAL raises *"no such table"*, which a caller mapping to "no embeddings" turns into **a false absence about a corpus that was just embedded**. |

Leases, not locks: `lease_ms = max(60_000, 5 × card.isolation.wall_ms_hard)`; heartbeat at `lease/3`;
the reaper returns expired-lease rows to `pending` **only after `_is_live_holder`**, and a live holder
past its lease gets **one extension with a WARNING naming it, never a steal** — codegraph's
`STALE_TIMEOUT_MS = 2 min` unlinks locks regardless of liveness, so a legitimate 3-minute bulk index
loses its lock mid-write. `claimed_by` is `(host, pid, process_create_time)`: jcodemunch #450 observed
*"two-week-old lock rows resolving to a Chrome renderer and an AMD service."*

**Enqueue before attempting the lock** (§7.3.4): a trigger writes its work rows *first*, then tries the
lock; if held it returns immediately having lost nothing, because the holder's next claim is a
superset. This makes graphify's `.pending_changes` file, three-phase drain and
`_PENDING_DRAIN_MAX_PASSES = 20` all unnecessary.

---

## 8. Determinism and replay

### 8.1 The worker environment is constructed, never inherited

D1 already requires this for Toolchains (*"env is a constructed allowlist, never `os.environ`"*). I
apply the identical rule to every `subproc` driver worker, and add the determinism block:

```
PYTHONHASHSEED=0   SOURCE_DATE_EPOCH=0   TZ=UTC   LC_ALL=C.UTF-8   PYTHONDONTWRITEBYTECODE=1
OMNIWEAVE_WORKER=1                       cwd = the per-invocation tmpdir, never inherited
+ exactly the vars named in card.hardware.needs_binaries' resolution and the Service URLs
```

graphify pins `PYTHONHASHSEED` in its hook and *still* needs `_report_for_compare` to strip a
timestamp before comparison (I17), which is why the rule is "no wall clock in committed output" and
not "we set a seed".

### 8.2 `ow replay`

```
ow replay --run <run_id>            re-executes every deterministic decision from recorded inputs
ow replay --work <work_id>          one unit
ow replay --decision <decision_id>  delegates to D4's `route replay`
```

Exit codes match D4's: `0 IDENTICAL`, `3 DIVERGED`, `4 REPLAY_DRIFT` (an input the recorded key
claims is unchanged is now absent or different). **I27: a `deterministic = true` driver replays
byte-identical over recorded inputs**, and the fixture-corpus replay is a CI gate. A
`deterministic = false` driver records the divergence as a `route_verdict` row with
`source = 'self'` — which never enters D4's Scoreboard, by the view definition.

### 8.3 Fault injection ships

`_chaos: {failure_rate, exception_class, latency_ms, oom_at_unit}` on the driver config, off by
default, **present in production builds**. graphrag's `with_errors_for_testing` is how this stack gets
tested at all; the whole retry/lease/quarantine/futility layer is untestable without it. `oom_at_unit`
is mine and it is what tests I23 and the AIMD ladder.

---

## 9. Observability: one event stream, no OpenTelemetry dependency

### 9.1 The evidence, and the decision

Zero of the twenty-two repositories emit OpenTelemetry. The only occurrence in `_collections/` is
`jcodemunch-mcp/examples/otel-collector/jcm-exporter.yaml` and
`jcodemunch-mcp/src/jcodemunch_mcp/runtime/otel.py`, which *ingest* OTLP as a data source — and
jcodemunch is licence-barred entirely. So there is no precedent to copy and no dependency to justify.
D1's gate **G1** makes it decisive: `omniweave-core` resolves to exactly one distribution, and
`opentelemetry-sdk` pulls a real tree onto the per-turn hook import path that G9 also gates.

**So: one always-on structured NDJSON event stream in core, and an offline OTLP exporter in
`omniweave-serve`, which already carries `mcp`.** The mapping lives in one file that can be wrong
without breaking a run.

```
{output_root}/runs/{run_id}/
├── manifest.json            §7.4.4, written incrementally so a crash leaves a partial
├── events-000.ndjson.zst    64 MiB shards, zstd-3
└── events-001.ndjson.zst
```

```jsonc
// The event envelope. Field names are FROZEN in an append-only registry CI diffs
// (D2's wire-key discipline, applied to telemetry).
{"t":1725190000123,          // wall ms — for humans and correlation only
 "m":41230,                  // monotonic ms since run start — the ONE field durations derive from
 "run":"01JBQ…","gen":41,
 "e":"unit.complete",        // CLOSED event vocabulary — 34 names, unit-tested
 "sev":"info",
 "span":"01JBQ…-0f3a","parent":"01JBQ…-0002",   // correlation WITHOUT an OTel SDK
 "work":184203,"decision":"dec_77a2…","driver":"ocr.page.olmocr","invoke":"inv_9c1",
 "uri":"file:///c/corpus/10k.pdf","part":"p41",
 "f":{"outcome":"ok","ran_ms":2411,"queued_ms":83,"tokens_out":964,
      "micros":193,"cache_hit":false,"batch":8,"peak_rss":412000000}}
```

Closed event vocabulary (34 names), grouped:

```
run.start run.end run.degraded
plan.begin plan.unit plan.end plan.paused plan.resumed
work.enqueue work.claim work.lease_extend work.lease_reap work.complete work.defer work.cancel
unit.begin unit.complete unit.failed unit.progress
driver.spawn driver.ready driver.invoke driver.result driver.crash driver.quarantine driver.shutdown
service.attach service.spawn service.batch service.error
cache.hit cache.miss cache.corrupt cache.write cache.sweep
budget.reserve budget.deny budget.commit
store.txn store.wal_valve store.bulk_lock
```

Adding a name is a PR that touches `tools/events.toml`; the CI diff is append-only, and every name
has a test that emits it. This is the same discipline D2 applied to wire keys and D1 applied to error
codes, and it exists because DataFlow's 171 hand-written `get_desc(lang)` strings with nothing
checking them against `inspect.signature` is what an unpoliced descriptor surface becomes.

### 9.2 Volume control, deterministically

```toml
[runtime.events]
level = "sampled"     # full | sampled | off
# sampled: EVERY non-ok event, plus 1-in-64 ok events selected by
#          blake2b(work_id ‖ events.salt) % 64 == 0  — never RNG (D4's R2)
```

Deterministic sampling, so two runs of the same corpus sample the same units and a diff of two event
streams is meaningful.

### 9.3 The OTLP bridge, offline

```
ow trace export <run_id> --otlp https://collector:4318 [--service-name omniweave]
```

`run.start`/`run.end` → a root span; each `span`/`parent` pair → a child span; `f.*` → attributes;
`sev` → severity. It lives in `omniweave-serve`, it is 200 lines, it reads a finished (or partial)
event file, and **if it is broken, a run still completes**. That is the entire argument. An operator
who wants live OTLP runs `ow trace export --follow`.

### 9.4 The run manifest is the reporting artefact and it is not a log (§7.4.4)

Taken whole, including the three blocks people leave out:

- `cache.{corrupt_entries, legacy_vintage_hits, rebilled_units}` — graphify reports exactly these
  through `warnings.warn(RuntimeWarning)`, which is filterable, unstructured and **invisible under
  JSON logging**.
- `cost.would_have_been_micros_if_uncached` — replayed from cached metrics with `was_cache_hit=true`.
  *"Without this number nobody can justify the cache's existence, and nobody can estimate a cold run."*
- `timings_ms` per phase with counts, **always on, never behind an env var**: codegraph *"burned three
  25-minute cycles before 'is the valve even alive?' could be answered."*
- `degradations[]` (**I18**) — a degraded subsystem is visible in the product surface, one-way latch,
  and D4 requires the message to name the knob that would raise the limit.

Plus D6's additions: `batch.{adaptive_final, oom_halvings}`, `loop_lag_ms.{p50,p99,max}`,
`services[]` with `{name, model_id, attached|spawned, coalesced_batches, mean_batch}`, and
`workers[]` with `{driver, spawns, crashes, quarantined, peak_rss}`.

### 9.5 Freshness (§7.7), which is the observability the *agent* sees

Derived from `work`-table state so every process agrees: `stale = EXISTS(claimable)`,
`refreshing = EXISTS(claimed with a live lease)`. Per-corpus `Freshness` plus a per-unit pending list
**filtered to the units this answer cites**. `indexing: bool` from `last_seen_gen <= claimed_gen`, not
from timestamps. The tie-break is written down with its cost: prefer *"shown stale, actually fresh"*
(one extra read) over *"shown fresh, actually stale"* (misleads the agent). Error detail on the 2nd
consecutive failure, or immediately if the class is FATAL. `strict_timeout_ms = 500`, tuned *"against
the agent's patience, not the indexer's convenience"*, returning `{fresh, waited_ms, reason}` — never
a bare boolean. **"Never indexed" is trivially fresh**, or every first-run query burns the timeout.

---

## 10. Cost accounting

D4 owns `Spend`, `PriceBook`, `CostCard`, `route_spend` and the rule that **no driver prices anything**.
D6 owns the ledger, the reservation lifecycle, and the rollups.

```python
@dataclass
class BudgetLedger:                     # persisted per run in `budget_reservation`; §7.8.2
    limits: dict[BudgetKind, int]       # WALL_MS · MICROS · TOKENS_IN · TOKENS_OUT · CALLS
                                        # · GPU_MS · BYTES_EGRESS · UNITS, per scope
    def reserve(self, scope: BudgetScope, spend: Spend, book: PriceBook) -> Reservation | Denied
    def commit(self, r: Reservation, actual: Spend) -> None
    def release(self, r: Reservation) -> None
    def headroom(self, scope: BudgetScope, kind: BudgetKind) -> int
```

Four scopes, and the first exhausted **dimension** wins (D4), the first exhausted **scope** wins (D6):

```
run  ⊃  corpus  ⊃  unit  ⊃  part
effective per-unit micros = min( omniweave.toml [budget].per_document_micros ,     # D1
                                 route.toml [budget.per_unit].micros_base
                                   + per_part × part_count , micros_max )          # D4
```

Reservations use `CostCard.tokens_out_p95_multiple`, not the mean, and D4's reconciliation gate
(`omniweave driver check` fails an understatement >25%; `route lint --estimates` fails the build at
>2× off the 7-day median) is what keeps them honest.

The middleware stack is graphrag's ordering, which §7.8.3 calls its best contribution, with
`with_budget` in the one correct slot:

```
with_logging → with_request_count → with_cache → with_budget → with_retries
             → with_rate_limiting → with_metrics → with_fault_injection → driver
```

Cache **outside** budget and retry, so a hit costs no budget and no tokens and its metrics are
replayed with `was_cache_hit=true`. Retry **outside** rate limiting, so retries re-queue for the
limiter. **Do not copy graphrag's rate limiter** (busy-wait + `time.sleep` under a held lock, called
from async) and **do not copy its sync cache facade** (`asyncio.new_event_loop()` per LLM call).

Rollups are views, not tables, so they cannot drift:

```sql
CREATE VIEW cost_per_document AS
SELECT rud.unit_uri,
       SUM(rs.micros)                                        AS micros,
       SUM(rs.gpu_ms)                                        AS gpu_ms,
       SUM(rs.tokens_in), SUM(rs.tokens_out), SUM(rs.calls),
       SUM(rs.bytes_egress)                                  AS bytes_egress,
       SUM(CASE WHEN rs.was_cache_hit THEN rs.would_have_been_micros ELSE 0 END) AS saved_micros
FROM route_unit_decision rud
JOIN route_spend rs ON rs.decision_id = rud.decision_id
GROUP BY rud.unit_uri;

CREATE VIEW cost_per_corpus AS SELECT SUM(micros), SUM(saved_micros), COUNT(*) FROM cost_per_document;
```

D4's `route_unit_decision` exists precisely so this *"survives `work` row deletion, so cost stays
attributable per corpus after the queue drains."* `ow cost --by document --top 20` and
`ow cost --by driver --since 7d` are the two commands an operator actually runs, and the second one is
what catches a `schema_version` that was not bumped.

**A watcher may never auto-run billable work.** `dispatch()`: FREE now, LOCAL_COMPUTE within headroom,
`BILLED_API` **enqueued as `deferred_budget` with a pending-cost record**, never run. D4 encodes it as
a `GATE` rule (`gate.watcher-may-not-bill`) and D3 as
`[drivers.cost] auto_refresh_classes = ["free"]`; D6 enforces it in `dispatch()` so all three agree.
Deletions are always free to service, or graphify #2580 recurs: *"a doc-only deletion batch would sit
behind the needs_update flag until the next code event."*

---

## 11. Concrete shape

### 11.1 Directory layout (inside D1's tree, adding nothing outside it)

```
packages/omniweave-core/src/omniweave_core/
├── operator.py        OperatorABC · OperatorIdentity(==D2 Producer) · StepResult · Outcome
│                      RunContext · Roots · StepMetrics · Confidence · FailureClass
├── work.py            WorkRow · claim/complete/reap SQL · the failure taxonomy + classifier
├── cache.py           cache_key · sha256_canonical · three-group payload · two-tier namespaces
│                      six-clause miss policy · put(entries, allowed_units=…)
├── blobs.py           CAS: put(BinaryIO)->sha256 · path(sha256) · refcount · mark-and-sweep
├── budget.py          BudgetLedger · Reservation · BudgetScope
├── events.py          Event · the closed vocabulary · NDJSON sink · shard rotation · sampling
├── services.py        attach-or-spawn (surya shape) · sentinel+filelock · model-id verify · heads
├── drivers/host/      D3: inproc.py (DriverGuard) · subproc.py (supervisor + pool) · wire.py
├── wire.py            ★ pure-stdlib MessagePack, 7 types — see CONFLICT-1
├── clock.py           Clock protocol: monotonic_ns() + wall_ns(); injected, never ambient
├── locks.py           scoped cross-process lock (O_CREAT|O_EXCL + flock + (host,pid,ctime))
└── store/sqlite.py    THE ONLY sqlite3.connect · pragmas · connect_readonly · WAL valve · heal

packages/omniweave/src/omniweave/
├── run/
│   ├── scheduler.py   the loop · admission · claim batching · AIMD · reaper · lag_monitor
│   ├── planner.py     plan() generator · resume subtraction · full-scan latch
│   ├── operators.py   the SIX generic operators (§1.1)
│   ├── converge.py    defines/dep delta · rebind driver · GC
│   ├── guard.py       per-unit attribution guard (§5.4)
│   ├── manifest.py    incremental run manifest writer
│   └── watch.py       three triggers, watcher last, cost-tier dispatch
└── cli/               ingest · resume · queue · cache · cost · replay · gc · bench · doctor
```

### 11.2 The runtime DDL delta (on top of §7.3.1, D3's and D4's)

```sql
-- one row per run; makes replay and cross-run cost attribution possible
CREATE TABLE run (
  run_id           TEXT PRIMARY KEY,
  generation       INTEGER NOT NULL,
  started_wall_ms  INTEGER NOT NULL, ended_wall_ms INTEGER,
  status           TEXT NOT NULL CHECK (status IN ('running','ok','partial','failed','cancelled')),
  config_digest    TEXT NOT NULL,     -- FULL effective config: manifest + full-scan latch
  run_scope_digest TEXT NOT NULL,     -- ★ the NARROW digest that enters cache keys (§4.2)
  policy_digest    TEXT NOT NULL,     -- D4
  pricebook_digest TEXT NOT NULL,     -- D4
  omniweave_version TEXT NOT NULL, contract INTEGER NOT NULL, schema INTEGER NOT NULL,
  trigger          TEXT NOT NULL CHECK (trigger IN ('cli','hook','upstream','watch','mcp'))
) STRICT;

ALTER TABLE work ADD COLUMN driver TEXT NOT NULL;    -- denormalised: the claim must be homogeneous
DROP INDEX work_claimable;
CREATE INDEX work_claimable ON work(driver, status, retry_after, priority DESC, id)
    WHERE status IN ('pending','failed_transient');

-- the artifact cache index. Blobs live in cache_root/{resp,emb}/; this is the liveness record.
CREATE TABLE cache_entry (
  cache_key   TEXT PRIMARY KEY,
  layer       TEXT NOT NULL CHECK (layer IN ('resp','emb')),
  namespace   TEXT NOT NULL,          -- op/{name}/v{sv}-c{cf}-d{deps}/  |  cfg/{options_digest}/
  cost_class  TEXT NOT NULL CHECK (cost_class IN ('free','local_compute','billed_api')),
  blob_sha256 BLOB NOT NULL,
  byte_len    INTEGER NOT NULL,
  unit_uri    TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',   -- miss clause 5
  micros      INTEGER NOT NULL DEFAULT 0,   -- what this entry SAVED; replayed on a hit
  partial     INTEGER NOT NULL DEFAULT 0,   -- miss clause 3
  created_ms  INTEGER NOT NULL, last_used_ms INTEGER NOT NULL, hits INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX cache_live  ON cache_entry(unit_uri, unit_part);
CREATE INDEX cache_sweep ON cache_entry(cost_class, namespace) WHERE cost_class = 'free';

-- the dependency record that makes incremental converge (I5, §5.2)
CREATE TABLE defines (unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL, name TEXT NOT NULL, gen INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, kind, name)) WITHOUT ROWID;
CREATE TABLE dep (unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  operator TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, operator, kind, name)) WITHOUT ROWID;
CREATE INDEX dep_name ON dep(kind, name);

-- reservations, so a crash mid-flight releases rather than leaking headroom
CREATE TABLE budget_reservation (
  reservation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
  scope TEXT NOT NULL, scope_key TEXT NOT NULL, decision_id TEXT NOT NULL,
  spend_json TEXT NOT NULL, micros INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('held','committed','released')),
  created_ms INTEGER NOT NULL
) STRICT;
CREATE INDEX budget_held ON budget_reservation(run_id) WHERE state = 'held';

-- the pending-cost record a watcher writes instead of billing (§10)
CREATE TABLE pending_cost (
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', driver TEXT NOT NULL,
  est_micros INTEGER NOT NULL, reason TEXT NOT NULL, first_seen_ms INTEGER NOT NULL,
  PRIMARY KEY (unit_uri, unit_part, driver)
) WITHOUT ROWID;
```

### 11.3 The scheduler loop

```python
async def run(scope: Scope, ctx: RunContext) -> RunManifest:
    async with asyncio.TaskGroup() as tg:            # structured SHUTDOWN only (§2.3)
        tg.create_task(lag_monitor(ctx.stats))
        tg.create_task(lease_reaper(ctx))
        tg.create_task(producer(scope, ctx))         # plan() → INSERT OR IGNORE in 1024s
        for cls, n in ctx.admission.max_inflight.items():
            for _ in range(n):
                tg.create_task(worker_loop(cls, ctx))

async def worker_loop(cls: CostClass, ctx: RunContext) -> None:
    while not ctx.cancel.stopped:
        driver = await next_hot_driver(cls)                       # round-robin over runnable drivers
        rows = await ctx.store.claim(driver=driver, batch=batch_for(driver, cls),
                                     gen=ctx.generation, worker=WORKER_ID, lease_ms=lease_for(driver))
        if not rows:
            await idle_backoff(cls); continue
        handle = await host.acquire(driver, rows[0].config_digest)   # pooled subproc / inproc guard
        try:
            async for res in handle.invoke(rows):                    # ONE RESULT per unit (D3)
                await complete(res, ctx)                             # one txn: rows + spend + work
        except WorkerCrashed as e:
            if len(rows) > 1:
                await handle.reinvoke_singly(rows, ctx)              # I23: localise the poison unit
            else:
                await fail_permanent(rows[0], DRIVER_CRASHED, e.stderr_tail, ctx)
            adapt_batch_down(driver, rows[0].config_digest)
            if host.crash_rate(driver) >= 3 / 60:                    # D3's circuit breaker
                host.quarantine(driver); degrade("driver", f"{driver} quarantined")
```

`next_hot_driver` is deliberately round-robin rather than priority-ordered across drivers: a
per-driver claim with a global `ORDER BY priority` would let one hot driver starve the pool, and the
priority ordering that matters is *within* a driver's claimable set, which the index already provides.

### 11.4 Config

```toml
[runtime]
max_inproc          = 2          # GIL-bound; see `ow bench inproc`
max_queue_depth     = 50_000     # producer pauses above, resumes at 50%
yield_interval      = 1000
loop_lag_max_ms     = 250
lease_floor_ms      = 60_000     # effective = max(floor, 5 × card.isolation.wall_ms_hard)
interactive_wait_ms = 2_000
batch_wait_ms       = 60_000
render_cache_bytes  = 2_147_483_648
work_compact_above  = 5_000_000  # rows; then `ow work compact` is offered in the manifest

[runtime.claim]
batch = { free = 256, local_compute = 32, billed_api = 8 }   # clamped by card.batch_max_units

[runtime.events]
level = "sampled"                # full | sampled | off
salt  = "2026-09-a"
shard_bytes = 67_108_864

[runtime.wal]
valve = true                     # clamp(dbSize/4, 256 MB, 2 GB); hard 2×; file cap 4× ⇒ TRUNCATE
futility = { give_ups = 2, cooldown_s = 60 }

[services."ocr.page"]            # one Service, many heads
model_id       = "allenai/olmOCR-7B-0225-preview"
url            = ""              # "" ⇒ attach-or-spawn
autostart      = true
batch_wait_ms  = 5               # surya's verified default
max_batch      = 8               # surya's default_max_batch
startup_timeout_s = 300
keep_alive     = false
```

### 11.5 CLI

```
ow ingest <scope> [--dry-run] [--profile fast|balanced|thorough]
ow resume                       # the recovery command IS the normal command
ow queue status [--by driver|class|failure]      # GROUP BY over an indexed column; no counter row
ow queue retry --class TIMEOUT [--reset-permanent]
ow work compact                 # delete `done` rows whose cache entry is live; see the risk below
ow cache status | prune [--allow-rebill] | verify
ow cost --by document|driver|corpus [--since 7d] [--top 20]
ow replay --run|--work|--decision <id>
ow gc [--dry-run]               # blob mark-and-sweep over part/asset/cache_entry refs
ow bench scheduler | inproc | service
ow trace export <run_id> --otlp <endpoint> [--follow]
ow doctor                       # probes, effective slots, inproc note, service model ids, WAL health
```

---

## 12. Invariants

I1–I18 are §7.11's, **unchanged and binding by D3's ruling**. I list only what D6 adds, with the
enforcement column that is the only column that matters.

| # | Invariant | Enforced by |
|---|---|---|
| **I19** | `policy_digest` and `pricebook_digest` never enter an artifact cache key. | A unit test asserts the `cache_key` payload key-set equals a frozen literal; semgrep bans those names in `cache.py`. |
| **I20** | A row in the `.owstore` is never also a blob in the artifact cache. | `cache_entry.layer` is a 2-value CHECK (`resp`, `emb`); a test writes a parse result and asserts zero `cache_entry` rows. |
| **I21** | The scheduler process never holds more than `INLINE_MAX` bytes of any unit's content. | semgrep bans `.read()`/`read_bytes()` on a source path outside `omniweave_core.blobs`; the `peak-rss` CI gate at 900 MB over the RSS fixture corpus. |
| **I22** | Every `work` row carries a `decision_id` and a `driver`, and the planner is its only writer. | `NOT NULL` + FK (D4); a semgrep rule allowing `INSERT INTO work` only in `planner.py`; a test asserts `work.driver == route_decision.driver` over the fixture corpus. |
| **I23** | A batch is never a failure unit. | Fault injection poisons unit 7 of 32; the test asserts 31 `ok` + 1 `failed_permanent`, and that `re-invoke at batch=1` appears in the event stream. |
| **I24** | The event loop is never blocked longer than `loop_lag_max_ms`. | `lag_monitor` at runtime with a one-way `degrade()`; a CI assertion on p99 loop lag over the fixture corpus. |
| **I25** | Every billable `Spend` commits in the same transaction as the work-row transition that produced it. | The `complete()` code path is one function; a crash-injection test kills the process between the driver result and the commit and asserts zero `route_spend` rows and a claimable work row. |
| **I26** | An automatic sweep never deletes a `billed_api` cache entry. | `cache_sweep` is a partial index `WHERE cost_class='free'`; the sweep query is unit-tested against a fixture containing all three classes. |
| **I27** | A `deterministic = true` driver replays byte-identical over recorded inputs. | `ow replay --run` over the fixture corpus as a CI gate; exit 3 fails the build. |
| **I28** | Batch size adapts down on `OOM`/`WORKER_DIED` and never exceeds `card.isolation.batch_max_units`. | AIMD is one function with a property test; `_chaos.oom_at_unit` drives it. |

---

## 13. Build order — every phase ships a command a user runs

| Phase | Weeks | Ships | Invariants | The command |
|---|---:|---|---|---|
| **P1 Identity + queue** | 3 | `canonical_uri`, `content_digest` + normaliser registry, the stat index with the racily-clean check, the `work` table, claim/lease, the failure taxonomy and its pure classifier, the `run` table, the NDJSON event sink, `ow queue status` | I6, I7, I14, I24 | `ow ingest ./corpus --driver parse.doc.anydoc`, `kill -9`, `ow resume` — and it finishes. |
| **P2 Operators + cache** | 3 | the six generic Operators, `StepResult`/`OperatorIdentity`, the three-group key, two-tier namespaces, the six-clause miss policy, `allowed_units`, the blob CAS, `--dry-run`, the run manifest | I1, I2, I12, I13, I16, I19, I20, I26 | `ow ingest` twice; the second run is 100% `skipped_cached` and `ow cost` prints `saved_micros`. |
| **P3 Concurrency + services** | 3 | the asyncio scheduler, admission, homogeneous claim batching, AIMD, the subproc pool wired to D3's host, `omniweave_core.services` attach-or-spawn with model-id verification and head routing, separate render/inference semaphores, the WAL valve + futility latch, the lag monitor | I9, I15, I21, I23, I24, I28 | `ow ingest` on a 5k mixed corpus keeps one GPU fed from four workers; `ow doctor` shows one Service, not four. |
| **P4 Ownership + budget** | 2 | `origin_operator`/`origin_driver` stamping, the per-unit attribution guard, the `BudgetLedger`, the middleware stack, `route_spend` writing, the cost views, fault injection | I4, I8, I17, I18, I25 | `ow cost --by document --top 20`; a free re-derive after an LLM extraction leaves the billed rows intact, proved by a test. |
| **P5 Convergence + triggers** | 3 | `defines`/`dep`, the delta pass, `ow replay`, the incremental-vs-full CI gate, freshness, then the three triggers **in order** — tool-call hook, upstream delta, watcher last | I3, I5, I10, I11, I27 | `ow ingest`, edit one document, `ow ingest` again — and the CI gate proves it equals a full rebuild. |

**~14 engineer-weeks for one senior engineer, plus ~3 weeks of explicitly budgeted Windows parity**
(Job Objects instead of `RLIMIT_AS`, named pipes with an owner-only DACL, no `fork`,
`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` and *not* `DETACHED_PROCESS`, `CREATE_BREAKAWAY_FROM_JOB`
attempted first with a fallback), plus a standing ~0.1 FTE owning the event vocabulary and the
benchmark baselines. No new third-party runtime dependency: `sqlite3`, `asyncio`, `hashlib`,
`tomllib`, `blake2b` and `zlib`/`zstandard` (already core's, per D2) are the whole surface.

**P5 before the watcher is deliberate** and it is §7.12's own build order: *"do this before the
watcher, because it is the invariant a watcher will break silently."*

---

## 14. Upstream conflicts

### CONFLICT-1 — D1 gate G1 vs D3's stated core dependency surface (MessagePack)

**D1** (`packages/omniweave-core/pyproject.toml`): `dependencies = []  # ENFORCED BY GATE G1.
Amending this amends D1.` and G1: *"`omniweave-core` resolves to exactly ONE distribution."*

**D3** (Consequences): *"Core's new dependency surface is `tomllib` (stdlib), a JSON Schema validator
and a MessagePack codec — three small pure-Python-capable libraries."* And D3's wire protocol is
`Frame ::= u32 length_le | u8 kind | MessagePack payload`, with `omniweave/core/drivers/host/` in core.

These cannot both hold. It lands on D6 because the driver wire protocol is the runtime's hot path and
I cannot ship a scheduler without deciding what encodes a frame.

**Minimum amendment: neither ruling changes. Add `omniweave_core/wire.py` — a pure-stdlib MessagePack
encoder/decoder restricted to the eight types the protocol uses** (nil, bool, int, float, str, bin,
array, map). The msgpack spec for those eight is small; this is ~260 lines and a property test against
the real `msgpack` package pinned in `[dependency-groups] dev` only. G1 holds byte-for-byte, D3's wire
format holds byte-for-byte, and the dev-only dependency makes the parity test real rather than
self-referential.

If the panel prefers a dependency, the *other* minimum amendment is to move
`omniweave_core/drivers/host/subproc.py` into the `omniweave` distribution, which already permits
third-party deps — but that puts the driver host outside the layer every driver-loading path depends
on, and D1's `tools/layers.toml` would need `omniweave_serve` and `omniweave_conform` to depend on
`omniweave`, which inverts the DAG. **I recommend the 260 lines.**

*(The JSON Schema validator D3 also names is not D6's problem: card validation happens once at
discovery, in `omniweave`, not on the hot path.)*

### CONFLICT-2 — D3 `ctx.service(name)` vs D4 `ctx.resource(kind) -> Resource`

**D3** (Consequences): *"`ctx.driver(kind)` becomes `ctx.service(name)`."*
**D4** (Consequences, first bullet): *"`mine-runtime.md` §7.1.3's `ctx.driver(kind)` is renamed
`ctx.resource(kind) -> Resource`. … One rename, done now, before D5–D10 write against it."*

Same motive (free the word *Driver* for the parse-engine noun), two different names, both stated as
binding. Silently picking one is exactly the failure the panel instructions warn about.

**Minimum amendment: D4's bullet reads `ctx.service(name) -> ServiceHandle`.** D3 defines the *concept*
(a Service is a host-managed shared resource, named and never routed), ships the package
(`omniweave/services/`), and puts `service(name)` on `DriverIO` — so `ctx.service` is the only spelling
that makes the runtime accessor and the driver accessor one name for one thing. D4's `Resource` type
has no other referent in D4 and loses nothing.

### CONFLICT-3 — `DriverMetrics.cost_micros` (D3) vs "no driver may price" (D4)

**D3**: `metrics: "DriverMetrics" = ...  # ran_ms, input/output_tokens, cost_micros, bytes_read,
peak_rss_bytes`.
**D4**: *"Cost is a seven-unit physical `Spend` vector … that **no driver may price**"* and *"Drivers
report Spend and never money. A contributor on a rented A100 cannot know your GPU-hour cost, and if
they guess, every estimate in your fleet is wrong in a way you cannot audit."*

Small, and exactly the kind of thing that survives into the charter and then into thirty documents.

**Minimum amendment: `DriverMetrics` becomes `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls,
bytes_egress, bytes_read, peak_rss_bytes}` — the seven `Spend` dimensions plus two diagnostics — and
`cost_micros` is deleted from it.** `StepResult.metrics.cost_micros` survives unchanged because the
*runner* computes it via the `PriceBook`, which is what D4 wants and what D3-8 already establishes
(*"`confidence`, `origin_driver`, `restriction_bits`, `was_cache_hit` are set by the runner"*).

### Non-conflict, noted for the charter

D4's Consequences call D6 *"document model"* and D6/D7 *"document model, structure extraction"*. D2 is
the document model and D3 correctly names D6 the runtime. D4's substantive requirement — `decision_id`
on every block as the join key from an artifact back to its decision — is honoured here: it is one of
the five columns the runner stamps (§5.3). No amendment needed, just a note so the charter does not
propagate the mislabel.

---

## 15. What this costs

- **Engineering:** ~14 engineer-weeks (one senior) + ~3 weeks Windows parity + ~0.1 FTE standing.
- **Runtime overhead per unit:** one `evaluate()` (~50 µs, D4) + one claim row + one canonical-JSON
  digest (~30 µs) + ~8 events (~1.4 KB before compression) + one transaction. Measured target: the
  scheduler adds **< 1 ms/unit**, gated by `ow bench scheduler` at ≥1,700 transitions/s.
- **Memory:** scheduler ≤ 900 MB at 100k documents, CI-gated. Each subproc worker costs its own Python
  import (200–800 ms cold, D3) and its declared `memory_mb`.
- **Disk, per 100k-document corpus:** ~220 MB `work` + ~730 MB routing ledger (~260 MB swept) +
  ~100 MB compressed events + the C2/C3 caches, which are the real number and are bounded by
  `live units × configurations seen`.
- **Dependency weight:** zero new third-party runtime packages. `wire.py` is 260 lines we own.
- **Operational burden:** two things a human owns — the event vocabulary registry (append-only, CI-diffed)
  and the four benchmark baselines (`scheduler`, `inproc`, `service`, `peak-rss`), which drift with
  hardware and must be re-blessed deliberately. Plus D4's pricebook, which D4 already staffed.
- **CI time:** +6 minutes on the runtime path (`incremental-vs-full` ~4 min, `peak-rss` ~90 s,
  `bench scheduler` ~60 s). The equivalence gate is the expensive one and it is the one that cannot
  be cut, because I5 is the invariant whose violation is invisible for months.

---

## 16. Failure modes

1. **One 4-million-cell XLSX still takes down a transaction.** D2 commits per page and admits *"a
   4M-cell sheet is one very large transaction."* My mitigations are the WAL valve, the RSS cap on the
   worker, and a `RESOURCE_LIMIT` refusal at `MAX_GRID_SLOTS` — but a sheet at 3.9M cells is legal,
   fits under the cap, and produces a multi-gigabyte WAL and a multi-minute commit that will trip I24
   and degrade the scheduler. **The input that breaks this design is a legal-discovery XLSX just under
   the limit.** The real fix is a sub-page commit boundary, which is D2's to grant.
2. **`schema_version` not bumped.** D3 names it *"the most expensive single mistake available in the
   design"* and it lands on my cache: stale billed output served forever with no symptom. My only
   additional defence is `ow cost --by driver --since 7d` showing a driver's spend fall to zero after
   a release — a lagging indicator that requires someone to look.
3. **Denormalised `work.driver` drifts from `route_decision.driver`.** I added it for the claim's hot
   path and it is a second copy of a fact. A test checks it on the fixture corpus; a hand-written
   migration or a `route promote` that rewrites decisions could still desynchronise them in the field,
   and the symptom would be a heterogeneous `INVOKE`, which the driver would reject as a config
   mismatch — loud, but confusing.
4. **`ow work compact` is a foot-gun and I am shipping it anyway.** Above ~5M rows the work table
   dominates a small store. Compacting deletes `done` rows whose cache entry is live, which means the
   next resume re-plans them and pays one cache probe each (~40 µs → ~60 s at 1.5M units). If someone
   compacts *and* prunes the cache, the corpus silently re-derives. The guard is that
   `ow cache prune --allow-rebill` refuses while a compaction is recorded in `run`; that is a check,
   not a proof.
5. **The 4× continuous-batching speedup is unmeasured.** Every GPU-hour figure in §6.3 rests on it.
   surya ships the mechanism and states the rationale but publishes no throughput number, and D3's
   `p50_ms_per_unit = 2.4 s` is a card *example*. If the real gain is 1.5×, a 100k ingest is 51
   GPU-hours, not 19, and the capacity planning in every downstream document is wrong by 2.7×.
6. **Round-robin over drivers starves a rare driver behind a hot one.** `next_hot_driver` is fair
   across drivers, not across units, so 300k pdfium parts and 40 pptx compiles share the pool equally
   at the driver level — which means the pptx work finishes early and the loop then spins on an empty
   driver. `idle_backoff` bounds the spin; it does not make the policy right, and a real workload with
   twelve drivers will need weighting.
7. **Deterministic event sampling hides the tail it was designed to hide.** At `level = "sampled"`,
   1-in-64 `ok` events means a latency regression affecting 1% of units is invisible in the event
   stream. The manifest's percentiles are computed over *all* units, not the sample, which covers the
   aggregate — but a per-unit investigation of an unsampled unit has no events at all.
8. **The `dep`/`defines` delta is only as complete as the operators that write it.** If `op.derive`
   forgets to record a dependency, incremental diverges from full and the CI gate catches it *only if
   the fixture corpus exercises that reference kind*. Forty documents is not a proof; it is a
   tripwire.
9. **`connect_readonly` cannot save a reader from a store mid-migration.** A hook process opening the
   store while `ow ingest` holds `store.bulk` for a migration gets a schema it does not understand.
   The `min_reader` check (D2) refuses loudly, which is correct and still means every hook fails for
   the duration of a migration.
10. **Two scheduler processes both honouring `max_inflight` spend 2× the intended concurrency.**
    Admission is per-process, held in memory. A CLI ingest and a hook-triggered refresh each admit
    `BILLED_API = 2` and the provider sees 4. The fix is a durable semaphore in the store, which costs
    a write per admission; I have not paid for it, and the mitigation is that D4's `budget.per_unit`
    and the provider's own rate limit bound the damage in money if not in concurrency.

---

## 17. Why I reject the alternatives

**A real task queue — Celery, RQ, Dramatiq, arq, or a Redis/AMQP broker.** It adds a second durable
store that must agree with the `work` table about what is done, and the whole point of §7.4 is that
*"there is no checkpoint file; the `work` table's `pending` set IS the checkpoint."* Two sources of
truth for completion is the DataFlow failure (`cache_step_{N}.json`, eight documented failure modes,
*"artifacts live outside the checkpoint model entirely"*) with a network hop added. It also forfeits
the property that makes freshness work: *"omniweave computes `stale = EXISTS(claimable)` … so hooks,
CLI and server agree"*, which is impossible when the queue is in another process's memory. And it
breaks D1's install story — `pip install omniweave` must read a DOCX with no broker.

**Ray, Dask, or any distributed-execution framework.** DataFlow priced this: RayOrch requires
`AcceleratedOperatorABC` subclasses plus a `MemoryStorage` shim, *"so an operator is either local or
distributed and porting is a rewrite"* (§1.7), and it moves payloads with `df.to_dict("records")`,
*"full materialisation per hop, fatal for binary payloads."* §7.10.1 already shows the cheap path:
T1→T2→T3 requires **no operator change** because the claim protocol is the seam and Postgres's
`SELECT … FOR UPDATE SKIP LOCKED` is the only difference. Buying a framework to get a property the
schema already gives us is the definition of speculative generality.

**Threads or processes as the primary parent-side concurrency.** A thread pool in the parent hits the
GIL exactly where D1 says it will (the anydoc marshal), and a process pool in the parent duplicates
D3's worker pool, which already has a supervisor, a circuit breaker, per-OS resource limits, a wire
protocol and a conformance suite. Two process abstractions is one too many, and the second one would
be the one without the fuzz suite.

**A long-lived local daemon for the scheduler.** D1 bans it in terms: *"A long-lived local IPC daemon
for parsing, embedding or indexing is banned; if a later decision needs one it is a unix socket or
named pipe at 0600, never a loopback port."* The evidence is LEANN's unauthenticated ZMQ REQ/REP on a
dynamic loopback port — compute theft from any local process — and open-slide's mandatory 76-line CSRF
guard. The `work` table gives coordination without a resident process, and D3's worker pool with
`worker_idle_ttl_s = 300` gives warm processes without a daemon.

**Client-side batching across documents.** It sounds like the obvious way to keep a GPU fed and it is
strictly worse than the server-side coalescer: it cannot merge across worker *processes*, it forces
document boundaries into the scheduler's hot loop, and it violates D3's *"one `RESULT` per unit, so
the batch is invisible to the `work` table."* surya already solved it in the right place, in ~60 lines
(`batch_service/server.py:79-99`), and the win is bigger because it merges across clients.

**Caching the parsed rows instead of the driver's raw response.** It doubles storage against D2's
canonical store, reintroduces the model-plus-sync-layer failure the whole document model was designed
to avoid, and buys nothing: re-deriving rows from a cached VLM response is CPU-microseconds against
the seconds the response cost. The response is the expensive artefact; cache the expensive artefact.

**Keeping `ctx.config_digest` in the artifact cache key (§7.5 as written).** It defeats the two-tier
invalidation design in one field: any run-config edit — a new enabled driver, a codec change on the
video target — re-bills the `BILLED_API` tier that §7.5.2 explicitly *"never sweeps."* The narrowed
`run_scope_digest` keeps every property the full digest was there for (a config change still sets the
full-scan latch, still appears in the manifest, still shows in `ow show-config --digest`) and drops the
one that costs money.

**An OpenTelemetry SDK dependency in core.** Zero of twenty-two repositories emit OTel; the only
occurrence is jcodemunch's *ingest* endpoint, in the one repo that is licence-barred outright. D1's G1
forbids the dependency and G9 (`import omniweave_core` loads zero third-party modules) and G10 (cold
start ≤ 80 ms) would both fail. An NDJSON stream with `span`/`parent` ids gives every correlation
property that matters, costs nothing at import time, is greppable with `jq`, and converts to OTLP
offline in 200 lines that can be broken without breaking a run. If someone later wants live OTLP badly
enough, `ow trace export --follow` is a sidecar, not a dependency.

**A `route_decision`-joined claim instead of denormalising `work.driver`.** It is the pure choice and
it puts a join on the hottest query in the system, executed once per claim at ~1,700 claims/s over a
600k-row table. I took the redundant column and paid for it with a test. That is the trade I make on
purpose.

**Waiting for a "proper" incremental design before shipping ingest.** The alternative build orders all
put convergence last, after the watcher, because the watcher demos better. §7.12 says the opposite in
one line — *"do this before the watcher, because it is the invariant a watcher will break silently"* —
and codegraph's 4.3% is what that costs when you get it backwards. So P5 does convergence first and
the watcher third, and P1 through P4 each ship a command anyway.
