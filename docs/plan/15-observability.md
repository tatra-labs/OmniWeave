# Observability and Operations

**In one paragraph.** omniweave has exactly three observability artefacts and no fourth: a
**closed, append-only NDJSON `Event` stream** written by `omniweave_core.events`, the **run
manifest** at `{output_root}/runs/{run_id}.json`, and the **store's own ledger tables**
(`work`, `route_spend`, `cache_index`, `driver_observation`, `service_observation`,
`retrieval_event`, `diag`). There is no metrics SDK, no in-process exporter, no daemon and no
second durable record of what happened: **a metric is a query, not a counter**, derived either
from the event stream by `ow top` or from SQL by `ow cost`, `ow queue status` and
`ow trace stat`. OTLP is produced offline, by `ow trace export` in `omniweave_serve.otlp`, as
OTLP/HTTP JSON over `urllib.request` with no OpenTelemetry SDK anywhere in the tree — so a
broken exporter cannot break a run and no distribution grows a 40 MB dependency to have one.
Every number an operator sees reconciles back to a row: `Σ route_spend.micros ==
manifest.cost.billed_micros` exactly (I30), and every micro names one
`(unit, part, decision, attempt)`.

This document owns the event and span model, the metric registry, the cost ledger's read paths,
the two explain commands, logging and redaction, `ow doctor`, the deployment topologies as
operational configurations, five runbooks, and the telemetry policy. It does **not** own the
scheduler or the manifest writer ([the execution runtime](08-runtime.md)), the routing ledger's
schema ([acquisition, parsing and routing](05-ingest-and-routing.md)), the `Verdict` and
`retrieval_event` schemas ([storage, indexing and retrieval](07-store-and-retrieval.md)), the
process topology ([system architecture](02-architecture.md) §5), the `ActionSpec` generation of
the CLI and MCP surfaces ([interfaces](10-interfaces.md)), latency budgets and the Pacer's
methodology ([performance](12-performance.md)), or the eval harness and gate ownership
([quality, testing and evaluation](13-quality.md)).

## 1. The substrate: three artefacts, and the rule that keeps them from multiplying

| artefact | written by | grain | lifetime | read by |
|---|---|---|---|---|
| the `Event` stream | `NdjsonSink`, `ConsoleSink` | one record per span boundary or point | `[observe] retain_days = 14`, sharded at `shard_bytes = 67108864` | `ow trace export/tree/stat/prune`, `ow top` |
| the run manifest | `omniweave/run/manifest.py` | one JSON document per `run_id`, written **incrementally** | until deleted; `run.manifest_path` points at it | `ow queue status`, `ow why <run_id>`, CI Counters, a human |
| the ledger tables | `Store.complete()`, `GraphSink`, the two flushers | one row per work transition / decision attempt / cache entry / query | 400 d decisions, 90 d queries, cache per `[cache] gc` | `ow cost`, `ow why`, `ow route scoreboard`, SQL |

Three rules make this a substrate rather than a pile.

1. **The event stream is diagnostic; the ledger is authoritative.** Events are dropped under
   pressure — a bounded 64k drop-oldest queue, because `TraceSink.emit` must not block — so
   nothing that must reconcile may be computed from them. Money, completion and coverage are
   read from SQL. The drop count is itself reported, as `run.events_dropped` and as
   `Degradation(kind="events_dropped")` on the result — the charter's §6.12 requires it in those
   words, and §6.3 prints the record.
2. **The manifest is not a log** (terminology lock). It carries counts, `failures_by_class`,
   cache statistics, `cost.would_have_been_micros_if_uncached`, per-Stage timings and
   `degradations[]`, and it is written incrementally so a crash at hour six leaves a partial
   manifest that still names what completed. graphify reported exactly the facts in the `cache`
   block through `warnings.warn(RuntimeWarning)` — filterable, unstructured, and invisible under
   JSON logging (`mine-runtime.md` §3.2 leave #3). Here they are manifest fields. graphrag's
   `PipelineRunStats.workflows: dict[str, WorkflowMetrics]`
   (`packages/graphrag/graphrag/index/typing/stats.py`) is the shape adopted for `stage_ms`, and
   its `tracemalloc_overhead_bytes` field is the discipline adopted in §3.3: an observability
   artefact reports its own cost so a reader can subtract it.
3. **No new sink type, ever.** A fifteenth `omniweave-otel` distribution plus an
   `omniweave.sinks` entry-point group was rejected in the charter as a third extension point
   created for one implementation. `TraceSink` is a Protocol with two methods and two shipped
   implementations; a third is a charter amendment.

### 1.1 What this substrate does under stress

The four questions asked of every mechanism in this document, asked once of the substrate
itself, because the answers set the shape of everything below.

| | the event stream | the manifest | the ledger |
|---|---|---|---|
| **at scale** | bounded by `retain_days` × `shard_bytes`; sampling (§2.4) makes the reference ingest one shard rather than nineteen | one JSON document, rewritten incrementally; `degradations[]` and `failures_by_class` are the only unbounded members, and both are dicts keyed by a closed vocabulary | 400 d / 90 d retention plus `work_compact_above`; §5.5 |
| **on hostile input** | `Event.fields` is `Mapping[str, Scalar]` with a per-`kind` key allowlist, so document text has nowhere to ride; §8.3 | written by the host from its own counters; a driver contributes no field | a driver writes no row at all (INV-7) |
| **on partial failure** | an unwritable path is `Degradation(kind="events_dropped")` and the run continues; a partial final line is skipped on read, never repaired | written at every Stage boundary and at every `degrade()`, so a killed run has one | `Store.complete()` is one transaction per unit (I20) |
| **under concurrency** | one writer thread per process; `seq` is per `(run_id, writer_id)` (§3.2); a shard is immutable after roll | one writer process holds the `store.write` lock, so one manifest has one author | one writer per `.owstore`; readers use `connect_readonly` |

## 2. The span model

### 2.1 The hierarchy is closed and five deep

```text
run                      one per `ow` invocation, SDK embed, or MCP session-scoped operation
 |- plan                 one per Stage entered (2.2). NEVER sampled out.
     |- unit             one per (unit_uri, unit_part) x operator. THE SAMPLING BOUNDARY.
         |- attempt      one per claim of that work row; work.attempts_total is its ordinal
             |- call     one per DriverHost.invoke, io.service() request, or Toolchain child
```

There is **no sixth level and no level between `plan` and `unit`**: the unit *is*
`(unit_uri, unit_part)`. `batch_index` and `batch_size` are attributes on `call`, never rows — a
Batch is visible for diagnosis and invisible for accounting (I24). Adding a level is a charter
amendment, not a refactor.

### 2.2 Stage — the pipeline phase, as a span attribute

`Event.phase` is already taken (`start | end | point`) and `derive_pass.phase` is already taken
(a card-declared ordering integer *within* a `cost_rank`). The pipeline phase is a third thing
and gets a third name: **Stage**, carried as the span attribute `ow.stage` on `plan` and
inherited by every descendant.

Its vocabulary is closed and is *exactly* the key set of the run manifest's `stage_ms` map, so a
timing in the manifest and a subtree in the trace are the same partition of the run.
**`stage_ms` is not `timings_ms`**: `doc.timings_ms` is a `doc`-table column holding one
document's driver-reported parse timings ([the document model](03-document-model.md)'s
`DocRecord.timings_ms`), and a run-level Stage map under that name would have been one name over
two objects at two grains. The manifest key is `stage_ms`, the document column stays
`timings_ms`, and the two are never joined.

| Stage | opens on | closes on | operators inside | in `stage_ms` |
|---|---|---|---|---|
| `discover` | the roster scan starting | the last `unit` row written | `acquire/1` connectors | yes |
| `plan` | the first `op.identify` claim | expansion drained to `queue_low_water` | `op.identify` | yes |
| `parse` | the first `parse/1` claim | no claimable `parse/1` work | `parse/1` drivers, every Rung | yes |
| `derive` | the first `derive/1` or graph `op.*` claim | the coverage ledger complete for the run | `derive/1`, `op.lexicon`, `op.resolve`, `op.cluster` | yes |
| `index` | the first `embed/1` claim or an FTS repopulate | `vec_manifest` and `stat` written | `embed/1`, the segment and vector build | yes |
| `converge` | `op.converge` claimed | the `anchor_delta` applied, dependents enqueued | `op.converge` | yes |
| `maintain` | a sweep, GC, `VACUUM` or compaction starting | it finishing | none (host-side) | yes |
| `query` | `retrieve()` entered | the `Answer` rendered | none — a read creates no work row | no: a read writes no manifest |
| `compile` | `ow out compile` entered | the receipt written | `compile/1` drivers, Toolchain children | no: a compile writes a receipt |

A Stage may be entered more than once in a run (a `converge` pass re-enqueues `derive` work);
`stage_ms[s]` is the **sum** of the elapsed times of every `plan` span carrying that Stage, and
the manifest carries `stage_entries[s]` beside it so a reader can tell one 600 s Stage from six
100 s ones. `[observe] timings` is the switch: `"always"` (the shipped default) records
`stage_ms` unconditionally; `"never"` omits the map, which is the only supported way to get a
manifest with no wall-clock content in it at all — a reproducibility need, not a performance one,
since a monotonic read per Stage boundary is nine reads per run.

`query` and `compile` are why the hierarchy did not need widening. A query has no work row and
no retry ladder, so it emits `run > plan(query) > call` — one `call` per Channel, one per
hydration, one per query-embed. A compile has real units (`artifact_unit`), so it emits the full
`run > plan(compile) > unit > attempt > call`.

### 2.3 Attributes, per level

Every span carries the `Event` envelope (`ts_wall_ns`, `ts_mono_ns`, `run_id`, `seq`,
`trace_id`, `span_id`, `parent_span_id`, `kind`, `phase`, `level`, `unit`, `part`, `operator`,
`driver`). These are the **additional** attributes, and the set is closed per level.

| level | attributes |
|---|---|
| `run` | `trigger` (`cli\|hook\|upstream\|watch\|mcp\|sdk`), `argv_digest`, `config_digest`, `semantic_digest`, `policy_digest`, `pricebook_digest`, `lock_digest`, `catalog_digest`, `generation`, `omniweave_version`, `contract`, `schema`, `corpus_id`, `needs_full_scan` |
| `plan` | `ow.stage`, `scope_id`, `discovered`, `skipped`, `rows`, `claimable`, `high_water` |
| `unit` | `operator`, `op_version`, `cost_class`, `cache_key`, `decision_id`, `staged_gen`, `queued_ms`, `ran_ms`, `rows_written`, `outcome`, `was_cache_hit`, `peak_rss_bytes`, `sampled` |
| `attempt` | `attempt` (1-based), `claimed_gen`, `lease_ms`, `failure_class`, `retry_after`, `rung`, `lane` |
| `call` | `driver`, `driver_version`, `driver_schema_v`, `isolation`, `invoke_id`, `batch_index`, `batch_size`, `dispatch_key`, `service`, `provider`, `wall_ms`, `cpu_ms`, `gpu_ms`, `tokens_in`, `tokens_out`, `calls`, `bytes_egress`, `micros` |

**What cannot be an attribute, by construction.** `Event.fields` is `Mapping[str, Scalar]` and
the permitted key set per `kind` is declared in `tools/events.toml`, so document text has no
free-form field to ride in. `unit` holds a `unit_uri`, which is a path — the one envelope field
that can leak a filename, and §8.3 says what redaction does to it. A `cite`, a `block_id`, an
`entity_id`, a query string and a `quote` never appear in an `Event`, at any level.

### 2.4 Sampling is tail sampling at the `unit` boundary, and it has to be

`[observe] sample = { non_ok = 1.0, ok = 0.015625 }` — one in 64 (the charter's `[observe]`
default). The key is `blake2b(work_id ‖ salt)`, never RNG, so two processes select the same set
and a replay selects the same set.

Deciding at `unit.begin` is wrong twice: the outcome is not yet known, so `non_ok = 1.0` is
unimplementable; and dropping a `unit` while keeping its `call` children produces exactly the
orphans I33's CI test forbids. Therefore:

- a `unit` span and its whole subtree are **buffered in the sink** until the span closes, bounded
  by `MAX_SPAN_BUFFER_EVENTS = 64` per open unit;
- on close the subtree is emitted whole if `outcome != ok`, or if
  `int.from_bytes(blake2b(work_id ‖ salt).digest()[:8], "big") < ok_rate * 2**64`; otherwise it
  is dropped whole and counted into `run.events_dropped`;
- a buffer overflow **flushes the unit unsampled** rather than truncating it — fail visible;
- `run` and `plan` spans are never sampled out and are never buffered, so the tree always has a
  spine and a fully sampled-out run still produces a manifest and a `plan` subtree per Stage.

**Where 64 comes from, and what it costs.** The charter's reference-ingest projection budgets
`~8 events` per unit (a `unit` pair, an `attempt` pair, a `call` pair, plus `work.claim` and
`work.complete`) — an estimate in that projection, not a measurement, and the first thing
`ow trace stat` measures. 64 is eight times that estimate, which covers a `REGEN` ladder of
three attempts each with a coalesced `call`, and it is a ceiling rather than a target. Peak
buffer memory is

```text
  Σ max_inflight  ×  MAX_SPAN_BUFFER_EVENTS  ×  mean serialised event bytes
```

which at the charter's default `[budget] max_inflight = { free = 32, local_compute = 4,
billed_api = 2 }` = 38 units and the reference ingest's ~180 B per event is
38 × 64 × 180 = 437,760 B = **427.5 KiB**; at §10.2's single-server `max_inflight` of 76 it is
855 KiB. The buffer is per open unit and per process, so a second `ow` process doubles it. That
is the entire cost of making sampling coherent, and it is why the bound is a formula in
`omniweave_core.limits` and not a comment.

### 2.5 Trace context across the four seams

`traceparent(trace_id, span_id) -> "00-{trace_id}-{span_id}-01"`. The sampled flag is always
`01`, because tail sampling means anything reaching a wire was already selected; a `00` would
instruct a downstream server to discard what we have decided to keep.

| seam | carrier | read by |
|---|---|---|
| S1 `inproc` | the `DriverGuard` sets it on the call frame | nothing external; the span parents in-process |
| S2 Toolchain | `traceparent` in `job.json`, plus `OMNIWEAVE_TRACEPARENT` in the constructed env allowlist | `target-runtime.ts`, which echoes it into the receipt |
| S3 model server | a `traceparent` HTTP header on every request to the sanctioned loopback listener | the server if it understands it; harmlessly ignored if not |
| S4 `subproc` | the `HELLO` frame, then every `INVOKE` frame | the driver, which may echo it from `io.log()` |

CI rebuilds the tree from a full run's NDJSON and asserts **zero orphans and zero cycles**
(I33). An orphan is a defect, not a warning: it means a seam dropped context, and a trace with a
hole is worse than no trace, because the hole is where the failure was.

**The one place a `traceparent` is not enough.** A monotonic clock is per-process, so a
`ts_mono_ns` from an S4 worker, an S2 Toolchain child or an S3 server is not comparable with the
host's. Therefore **every `Event` in the stream carries the host's two clocks, read by the sink
at `emit()`** — a driver-supplied or receipt-supplied timestamp is a value in `fields`
(`toolchain.run.ran_ms`, `service_observation.cold_start_ms`), never an envelope field, and
`ow trace tree` computes every duration from host monotonic deltas only. A `call` span's
`wall_ms` is measured host-side around the seam crossing, which is also the only measurement
that includes the seam's own cost. *(Build note, D950: `ow trace tree <run_id> [--unit U] [--depth N] [--slow MS]` runs, through an `[omniweave.trace] tree` entry point. Every span nests under its `parent_span_id` and every point record under the span it names. Each node is listed in pre-order with its depth and its duration from monotonic deltas, and a span with no `end` is listed `open`. `--unit` keeps that unit's nodes with their ancestors and descendants, `--slow` the spans at least that slow with their ancestors, and `--depth` cuts below a level. With `export` and `stat`, `ow trace` has three verbs.)*

### 2.6 The OpenTelemetry mapping, and why it needs no SDK

`ow trace export` is a **reconstructor**, not an emitter: it reads NDJSON shards, pairs
`phase="start"` with `phase="end"` on `(trace_id, span_id)`, and builds OTLP. Nothing on the hot
path knows OTLP exists.

It also imports no `opentelemetry`. It writes **OTLP/HTTP JSON** — the
`ExportTraceServiceRequest` message in its JSON encoding, `POST {endpoint}/v1/traces`,
`Content-Type: application/json`, through `urllib.request` — because the alternative fails a
dependency check the charter already ships: `omniweave-serve`'s declared dependencies are
`core, ports, mcp` under a 40 MB ceiling (§3.2), and the OpenTelemetry SDK plus a gRPC channel
does not fit inside either. The terminology lock's permission for `opentelemetry` in
`omniweave_serve.otlp` is therefore **reserved and unused at release 1**, which is the honest
state: a future SDK path has a legal home and needs no lock amendment, and release 1 ships
neither the dependency nor the import.

The precedent for consuming and producing OTLP without an SDK is jcodemunch's `otel.py`, an
OTLP-JSON *parser* importing no `opentelemetry`; across all 22 mined repositories there are
**zero OpenTelemetry emitters**, which is why this is the exception in the design rather than
the default.

```text
ow trace export [--run <run_id>|--since <dur>] [--otlp <endpoint>|--file <path>]
                [--follow] [--dry-run] [--print-payload] [--max-batch N]
ow trace tree   <run_id> [--unit <uri>] [--depth N] [--slow <ms>]
ow trace stat   [--run <run_id>]     # per-kind counts, per-Stage wall, dropped, shard bytes
ow trace prune  [--older-than <dur>] [--dry-run]
```

Four verbs, so `ow trace` clears the CLI grammar's three-verb floor for creating a group
([interfaces](10-interfaces.md) owns the grammar and its generation).

| omniweave | OTLP | note |
|---|---|---|
| a span-shaped `Event` pair | `Span` | `startTimeUnixNano`/`endTimeUnixNano` from `ts_wall_ns`; the duration is recomputed from `ts_mono_ns` and, if the two disagree by more than 1 ms, the monotonic duration wins and `ow.clock_stepped=true` is set — a wall clock steps and a stepped clock produces negative durations a dashboard renders as zero |
| span name | `run`, `plan/<stage>`, `unit/<operator>`, `attempt/<operator>`, `call/<driver>` | low cardinality by construction: never a path, never a cite, never a query |
| span kind | `SPAN_KIND_INTERNAL`, except a `call` with a non-empty `provider` or `service`, which is `SPAN_KIND_CLIENT` | an S4 driver invocation is not a network call; a Service request is |
| `outcome = ok` | `Status = STATUS_CODE_UNSET` | OTel's `OK` is an explicit assertion; we do not assert |
| `outcome = ok_partial` | `STATUS_CODE_UNSET` + `ow.partial_reason` | OTel has no partial state, and `ERROR` would paint every escalated document red |
| `failed_*`, `cancelled` | `STATUS_CODE_ERROR`, description = `failure_class` | never the driver's stderr |
| a point `Event` | `LogRecord` with `traceId`/`spanId` set | `severityNumber` from §8.1 |
| `Degradation` | a span event named `degradation` on the innermost open span | one per record, carrying `kind` and `message` |
| `Diag` | a `LogRecord` at `WARN`, `code` = the **symbol** | the numeric is a rendering concern (§6.4) |
| metrics | `Histogram` and `Sum` data points **derived at export time** from SQL (§4) | no in-process metric reader, no periodic reader thread, no gRPC channel |

Resource attributes: `service.name = "omniweave"`, `service.version = RELEASE`,
`omniweave.contract`, `omniweave.schema`, `omniweave.config_digest`, and `omniweave.corpus_id`
only when one corpus is in scope. **Never** `host.name`, `host.id`, `os.user`,
`process.command_line`, or any absolute path (§12). `[observe] otlp_endpoint` is honoured by
`ow trace export` only; a run never reads it. *(Build note, D947: `ow trace export --run R --file P` and `--dry-run [--print-payload]` run. The verb is the CLI-only Action `trace.export`, and it reaches `omniweave_serve.entry.export` through an `[omniweave.trace] export` entry point, because `omniweave` may not import this distribution (D369). The file holds one `ExportTraceServiceRequest` per line, the body `--otlp` would POST and the layout the OpenTelemetry Collector's file exporter writes. Spans only, as the send path sends. Point records, unterminated starts and orphaned ends are counted and named, not written. G29 greps the file. Not yet: `--since`, `--otlp`, `--follow`, and `ow trace tree`, `stat` and `prune`.)* *(Build note, D948: `--otlp E` sends now, and so does a bare `ow trace export --run R` when `[observe] otlp_endpoint` is set. Each request is POSTed to `E/v1/traces` through `UrllibTransport` on the 1/2/4 s ladder, and the cursor is committed after each, so a re-run resumes. `--dry-run` beside `--otlp` rehearses and sends nothing. A send that stops is `ResourceLimit`, exit 1, carrying `Halted.message()`'s committed offset and that class's own symbol, the shape D363 pointed at; no code is minted. The endpoint is never printed, since a URL may carry a credential. `trace.export` is `open_world`.)* *(Build note, D952: `--since <n>m|h|d` runs, 15:233's other selection, exclusive with `--run`. It reads every run in the events directory, each kept to records at or after the window's wall-clock start, the clock read once. A file or a rehearsal holds every run's requests in run order, and `--otlp` sends each run under its own cursor key. Not yet: `--follow`.)*

**Export mechanics, because "then it POSTs" is not a design.** Spans are batched at
`--max-batch 512` spans per request, capped at 4 MiB of serialised JSON per request (whichever
binds first). A non-2xx response or a socket error is retried three times with 1 s / 2 s / 4 s
backoff, after which the export **stops and exits non-zero naming the last shard offset it
committed**, so a re-run resumes rather than duplicating: the offset is written to
`.omniweave/events/.export_cursor.json` keyed by `(endpoint_digest, run_id)`. Export is
idempotent at the span level because a span id is stable across re-reads, so a duplicate arrival
is a duplicate the collector deduplicates, never a double-count in omniweave.

`--follow` tails the live shard. The mechanism is stated because tailing a rotating file is a
classic defect: the follower holds the **open handle**, not the path, and the writer emits a
final `kind = "shard.roll"` point record carrying the new shard's name as the last line of the
shard it closes. The follower reads to EOF, sees the roll record, closes, and opens the named
successor. It never stats the path in a loop and never re-reads a `.gz`.

## 3. Events

### 3.1 The vocabulary is closed, append-only and generated

`tools/events.toml` holds one `[[event]]` row per `kind`, with the `fields` that ride in
`Event.fields` and the `level` §8.1 assigns. `schema/event-v1.json` is **generated** from it and
byte-diff gated by G20. A row is never removed and a `kind` is never reused: an event kind is a
name a dashboard, a runbook and a test all hard-code, so retiring one silently breaks three
consumers.

The charter's inventory covers `run.*`, `plan.*`, `work.*`, `unit.*`, `driver.*`, `service.*`,
`cache.*`, `budget.*`, `store.*`, `dep.*`, `gc.sweep`, `degrade` and `manifest.write` — the
ingest runtime. It carries no read-path, no compile-path and no driver-log rows, so this document
**appends** them. Appending is the sanctioned change to an append-only file.

```toml
# tools/events.toml — APPENDED BY THIS DOCUMENT. Ordering is append order; nothing is renumbered.
[[event]]
kind = "query.plan"
level = "info"
fields = ["surface", "mode", "plan_digest", "narrowing_kind", "narrowing_n", "prefilter_exact"]
[[event]]
kind = "query.channel"
level = "info"
fields = ["channel", "status", "reason", "ranked_n", "ran_ms", "truncated_at_limit"]
[[event]]
kind = "query.complete"
level = "info"
fields = ["verdict_state", "gates_n", "confidence", "returned_n", "latency_ms", "micros"]
[[event]]
kind = "query.refuse"
level = "warn"
fields = ["code", "detail"]
[[event]]
kind = "compile.begin"
level = "notice"
fields = ["target", "slug", "artifact_gen", "units"]
[[event]]
kind = "compile.unit"
level = "info"
fields = ["unit_index", "unit_outcome", "reason", "nsig"]
[[event]]
kind = "compile.gate"
level = "notice"
fields = ["gate_status", "findings_error", "findings_warning", "determinism"]
[[event]]
kind = "toolchain.run"
level = "notice"
fields = ["name", "version", "queued_ms", "ran_ms", "exit_code"]
[[event]]
kind = "driver.log"
level = "info"
fields = ["driver_level", "message", "redacted"]
[[event]]
kind = "doctor.check"
level = "info"
fields = ["check_id", "status", "detail"]
[[event]]
kind = "shard.roll"
level = "notice"
fields = ["closed", "successor", "bytes", "records"]
```

Adding an event costs one row plus a regenerated schema; a reviewer rejects a `logger.info` that
should have been one of these.

**One change is not an append and is declared as such.** `level` becomes a required key on
*every* row, including the charter's forty-eight, so `tools/events.toml` and
`schema/event-v1.json` are both regenerated once in the same change that lands this document.
G20's byte diff is against the committed file, so the regeneration is a normal reviewed diff and
not a gate bypass. The alternative — a per-call-site level — is what §8.1 rejects.

### 3.2 The record, the two clocks, and `seq`

```python
@dataclass(frozen=True, slots=True)
class Event:
    ts_wall_ns: int; ts_mono_ns: int; run_id: str; writer_id: str; seq: int
    trace_id: str; span_id: str; parent_span_id: str | None      # W3C shaped: 16B / 8B, hex
    kind: str                          # from tools/events.toml — CLOSED, APPEND-ONLY, CI-diffed
    phase: Literal["start", "end", "point"]
    level: Literal["debug", "info", "notice", "warn", "error"]   # from tools/events.toml
    unit: str | None; part: str; operator: str | None; driver: str | None
    fields: Mapping[str, Scalar]

class TraceSink(Protocol):
    def emit(self, e: Event) -> None: ...          # MUST NOT BLOCK
    def flush(self, timeout_ms: int) -> int: ...   # returns the number still queued
```

`ts_wall_ns` is for humans and correlation with an external system; **every duration is computed
from `ts_mono_ns`**, and both are read host-side by the sink (§2.5).

`seq` is a monotone integer per `(run_id, writer_id)`, and both halves matter:

- `writer_id` is `sha256(host ‖ pid ‖ process_create_time)[:12]`, the same triple
  `work.claimed_by` uses. One run can have several writers — a detached `ow add` child, a hook
  invocation inside a `watch` run — and a bare per-`run_id` counter would have each of them
  restarting at 1, making every gap indistinguishable from a collision. With `writer_id` present,
  a reader sorts by `(writer_id, seq)` inside a run and merges the streams on `ts_mono_ns` only
  within one writer.
- `seq` is assigned under the sink's own lock at the *head* of `emit()`, **before** the
  drop-oldest queue can discard anything. That ordering is what makes a drop detectable as a gap
  in `seq` rather than invisible; the reverse ordering would have made `run.events_dropped` the
  only evidence a record ever existed.

The `Clock` protocol is injected, never ambient, which is what makes an event stream replayable
in a test.

### 3.3 The NDJSON file, sharding, volume and retention

```text
.omniweave/events/{run_id}.ndjson              [observe] ndjson_path, the live shard
.omniweave/events/{run_id}.0001.ndjson.gz      rolled at [observe] shard_bytes = 67108864
.omniweave/events/.export_cursor.json          §2.6's resume offsets. Derived, deletable.
```

- One record per line, UTF-8, `json.dumps(..., sort_keys=True, separators=(",", ":"))`, no
  trailing whitespace. A partial final line is skipped on read, never repaired. *(Build note, D941: `ow add` and `ow ingest` write this shard. Before this cell nothing in either constructed an `NdjsonSink` or a `RunRecorder`, so a run wrote no event. `omniweave.run.trace.RunTrace` writes the run span's spine: `run.start`, one `unit.failed` per work row the run failed, carrying the stored and already redacted message (D934), and `run.end` with the units, failures, spend and records dropped. The path resolves against the project root, and `$OMNIWEAVE_HOME` expands from the run's declared environment. A run with no project, or with `ndjson` left out of `[observe] sinks`, writes none. No `unit`, `plan` or `call` span is opened yet. G29 greps the shard.)*
- The live shard rolls at 64 MiB **of uncompressed bytes**, is renamed `NNNN`, and is deflated in
  the writer thread. The roll writes a `shard.roll` record as the closing line (§2.6).
- Retention is `[observe] retain_days = 14`, swept by `ow trace prune` and by the `maintain`
  Stage; a run whose manifest is still referenced by an open `eval_run` is exempt. A read-only
  deployment (§10.5) never enters `maintain`, so its cron runs `ow trace prune` — stated because
  a retention policy nothing executes is not a retention policy. *(Build note, D951: `ow trace prune [--older-than D] [--dry-run]` runs, through an `[omniweave.trace] prune` entry point. It removes every live or rolled shard last written at least `[observe] retain_days`, or `--older-than`, before the wall clock it reads once, and leaves the export cursor and any other file. A shard the platform will not unlink is named and left for the next sweep, exit 0. No run is exempt yet: no `eval_run` row names an ingest run's manifest. The `maintain` Stage does not run it yet, and no `gc.sweep` event is written.)*
- The writer holds an append-mode handle and `fsync`s **only on roll and at exit**. An unwritable
  path is a `Degradation(kind="events_dropped")` and the run continues: telemetry never fails a
  run, exactly as telemetry never fails a query.
- `ow trace tree`, `ow trace stat` and `ow trace export` read shards in place, streaming; there
  is no index file, because a second index is a second thing that can be wrong. Cost, derived
  rather than asserted: a 64 MiB shard is ~370k records at ~180 B, and at a conservative
  400 MB/s sequential read plus `json.loads` at ~1 μs/record that is 170 ms of I/O and 370 ms of
  parse — **~0.5 s per shard, dominated by parsing, single-threaded** (an estimate from those two
  rates, and the number `ow trace stat` reports so it stops being one). `--slow` and `--unit`
  filter on the envelope before parsing `fields`, which is what keeps `ow trace tree` on one
  unit under a second on a full shard.

**The stream's actual size, because the charter's figure and the shipped sampling rate disagree
and the difference is 18×.** The charter's reference ingest budgets
`events ~846k × 8 × ~180 B, deflated, 64 MiB shards → ~140 MB`. Working it through:

```text
  unsampled   846,400 units × ~8 events            = 6.77M records
              × ~180 B                             = 1.22 GB uncompressed
              / 64 MiB per shard                   = 19 shards
              deflated at ~8.7x (JSON, sorted keys) = ~140 MB on disk   <- the charter's figure
  shipped     ok = 0.015625, and ~95% of units settle ok
              6.77M × (0.05 × 1.0 + 0.95 × 0.015625) = 439k records
              × ~180 B                             = 79 MB uncompressed
                                                   = 2 shards, ~9 MB deflated
```

So the charter's ~140 MB is the **ceiling at `ok = 1.0`** — which is exactly the CI setting
(§10.4), where it matters — and the shipped default produces ~9 MB. Both numbers are correct for
their configuration and neither is a measurement; the deflate ratio is the one assumption, and
`ow trace stat` reports the observed ratio per shard so it is replaced by a measurement on the
first reference run. The consequence for `retain_days = 14` on a laptop is ~9 MB per full ingest
and rather less per interactive run, which is why the default is 14 days and not 1. *(Build note, D949: `ow trace stat [--run R]` runs, through an `[omniweave.trace] stat` entry point as `export` does. It prints each shard's records, bytes on disk, uncompressed bytes and their ratio (1.00 for a live shard, which is never deflated), the records per kind, each span name's count and summed wall, a `plan/<stage>` name being 15:236's per-Stage wall, and the dropped records the runs' `run.end` carry. Without `--run` it reads every run in the events directory, a run being named by its live or its rolled shards. Not yet: the reader's own wall time per shard (15:2165), which needs a clock the serve side does not read.)*

**The overhead it costs the run.** `~8 events` at a serialise-plus-enqueue cost the charter
budgets inside `<= 0.5 ms/unit` of total runtime overhead (F8's open question, with its own
fallback). The manifest records what observability actually cost — `observe.events_emitted`,
`observe.events_dropped`, `observe.serialise_ns_total`, `observe.shard_bytes` — adopting
graphrag's habit of reporting the profiler's own overhead so a reader can subtract it. A number
that cannot be subtracted contaminates every measurement beside it.

### 3.4 `ConsoleSink` writes to stderr, and that is a correctness property

`ConsoleSink` renders the same records for a human at
`[observe] sinks = ["console", "ndjson"]`, one line per record, **on stderr**. Not stdout:
stdout is the machine channel — `ow query --render json`, `ow cost --render json`,
`ow doctor --render json` — and a progress line interleaved into a JSON document is a parse
error in the caller, discovered by whoever automated the command rather than by us. The same
rule the charter applies to the Toolchain wire ("stdout is CONTROL ONLY") applies to ours.

It is suppressed to `warn` and above when **stderr is not a TTY**, so a hook, a cron and a piped
invocation do not spray progress into a transcript or a CI log. codegraph's prompt hook makes the
same call from the same premise (`if (process.stdin.isTTY) return;` in its hook entry) — the
lesson taken is that an interactive-only side effect must test the stream it writes to, not a
config flag someone forgot to set.

## 4. Metrics

### 4.1 There is no metrics pipeline, and that is the design

A metric in omniweave is one of exactly two things: a **fold over the event stream** inside the
running process (`ow top`), or a **SQL expression over a ledger table** (`ow cost`,
`ow queue status`, `ow trace stat`, and OTLP export). There is no counter registry, no atomic
increment in the hot path, no periodic reader thread and no `/metrics` listener. Two reasons, both
load-bearing: an in-process counter is a second record of a fact the ledger already holds and can
disagree with it, and a metrics SDK in `omniweave_core` breaks G1 and G9 for a path with an 80 ms
import budget.

The registry is `tools/metrics.toml`, one row per metric, generated into
`schema/metric-v1.json` and byte-diff gated by G6 (`ow schema emit --check`). The generator is
also the validator: `ow schema emit --check` fails when a row has no `source`, when a label is
outside the closed-cardinality set below, or when a declared `source` names an event `kind` that
is not in `tools/events.toml` or a column that is not in the applied migration set. That last
check is the one that matters, because it is what stops a metric row from outliving the column it
reads. A metric with no declared source fails CI, which is the same rule that makes an
unclassified config key fail G18.

```toml
# tools/metrics.toml — one row per metric. GENERATED INTO schema/metric-v1.json (G6).
[[metric]]
name = "ow_work_claimable"
type = "gauge"
unit = "rows"
labels = ["cost_class"]
source_kind = "sql"
source = "SELECT cost_class, count(*) FROM work WHERE status IN ('pending','failed_transient') GROUP BY cost_class"
[[metric]]
name = "ow_unit_ran_ms"
type = "histogram"
unit = "ms"
labels = ["operator"]
buckets = "ms_pow2"
source_kind = "sql_hist"
source = "work.ran_ms"
[[metric]]
name = "ow_driver_crash_total"
type = "counter"
unit = ""
labels = ["driver", "failure_class"]
source_kind = "event"
source = "driver.crash"
```

**Cardinality is a contract, not a hope.** A label may only be drawn from a closed enum, a
`DriverId`, an operator name, a Stage, a corpus name from `[corpora]`, or a `codes.toml` code.
`unit_uri`, `cite`, `block_id`, `decision_id`, `cache_key`, `query` and `provider`-supplied
strings are **banned as labels**; a row declaring one fails schema emit. The worst two series
counts, both bounded by files in the repository rather than by data: `driver × failure_class` is
a roster of ~20 drivers × the 13 `FailureClass` members = 260 series, and `code × severity` is
the `codes.toml` register's row count at release × 3 severities — which is why `ow_diag_total`
is the one metric whose series count `ow schema emit --check` prints, so a register that grows
past a few hundred rows is a visible cost rather than a surprise on a dashboard.

The discipline is codegraph's, and it is worth naming because it is the cheap half of
observability: its prompt-hook gate records **counter names only**
(`prompt-hook-gate-high-keyword`, `-high-token`, `-noop-shape`, `-noop-no-index`), never prompt
content — *"the data that turns 'is the gate any good' from vibes into a measured recall rate"*.
A closed name set with no payload is what makes a metric safe to export at all.

### 4.2 The registry

Naming: `ow_<subsystem>_<name>[_<unit>]`, counters end `_total`, histograms carry the unit,
gauges carry neither. `micros` is millionths of the pricebook currency, never a float.

| metric | type | unit | labels | source |
|---|---|---|---|---|
| `ow_run_total` | counter | — | `trigger`, `status` | `run` table |
| `ow_run_duration_ms` | histogram | ms | `trigger` | `run.ended_ns - started_ns` |
| `ow_stage_duration_ms` | histogram | ms | `stage` | `manifest.stage_ms` |
| `ow_stage_entries` | gauge | entries | `stage` | `manifest.stage_entries` |
| `ow_work_rows` | gauge | rows | `cost_class`, `status` | `SELECT status, count(*) FROM work GROUP BY` |
| `ow_work_claimable` | gauge | rows | `cost_class` | the `work_claimable` partial index |
| `ow_work_attempts_total` | counter | — | `operator`, `failure_class` | `work.attempts_total` deltas |
| `ow_unit_settled_total` | counter | — | `operator`, `outcome` | `unit.complete` |
| `ow_unit_queued_ms` | histogram | ms | `cost_class` | `work.queued_ms` |
| `ow_unit_ran_ms` | histogram | ms | `operator` | `work.ran_ms` |
| `ow_unit_peak_rss_bytes` | gauge | B | `operator` | `max(work.peak_rss_bytes)` |
| `ow_lease_reap_total` | counter | — | `operator` | `work.lease_reap` |
| `ow_driver_invoke_total` | counter | — | `driver`, `outcome` | `driver.result` |
| `ow_driver_batch_size` | histogram | units | `driver` | the `call` span's `batch_size` |
| `ow_driver_crash_total` | counter | — | `driver`, `failure_class` | `driver.crash` |
| `ow_driver_quarantine_total` | counter | — | `driver` | `driver.quarantine` |
| `ow_driver_cost_micros_total` | counter | micros | `driver` | `driver_observation.cost_micros_total` |
| `ow_service_inflight` | gauge | requests | `service` | `Admission.service_sem` |
| `ow_service_peak_inflight` | gauge | requests | `service` | `service_observation.peak_inflight` |
| `ow_service_queue_ms` | histogram | ms | `service` | `service_observation.queue_p50_ms/p95_ms` |
| `ow_service_cold_start_ms` | histogram | ms | `service` | `service_observation.cold_start_ms` |
| `ow_service_gpu_ms_total` | counter | ms | `service` | `service_observation.gpu_ms` |
| `ow_cache_lookup_total` | counter | — | `layer`, `verdict` | `cache.hit`, `cache.miss` (`CacheVerdict`) |
| `ow_cache_bytes` | gauge | B | `layer` | `SUM(cache_index.bytes)` |
| `ow_cache_rows` | gauge | rows | `layer`, `cost_class` | `cache_index` |
| `ow_cache_saved_micros_total` | counter | micros | `layer` | `cache.hit.would_have_been_micros` |
| `ow_budget_held` | gauge | dim-units | `dim`, `scope` | `SUM(amount) WHERE state='held'` |
| `ow_budget_deny_total` | counter | — | `dim`, `scope` | `budget.deny` |
| `ow_spend_micros_total` | counter | micros | `provider`, `cost_class` | `spend_attribution.micros` — `cost_class` is `route_decision`'s, so this one reads §5.2's view, not `route_spend` alone |
| `ow_spend_tokens_total` | counter | tokens | `direction`, `provider` | `route_spend.tokens_in/out` |
| `ow_spend_gpu_ms_total` | counter | ms | `driver` | `route_spend.gpu_ms` |
| `ow_egress_bytes_total` | counter | B | `provider`, `grant_id` | `route_spend.bytes_egress` |
| `ow_store_txn_ms` | histogram | ms | — | `store.txn` |
| `ow_store_wal_bytes` | gauge | B | — | `store.wal_valve.wal_bytes` |
| `ow_store_wal_growth_bytes` | gauge | B | — | `wal_bytes − size_at_last_full_backfill` (§4.4) |
| `ow_store_contend_ms` | histogram | ms | `holder_kind` | `store.contend.waited_ms` |
| `ow_loop_lag_ms` | gauge | ms | — | `lag_monitor` at 100 ms |
| `ow_events_dropped_total` | counter | — | — | `run.events_dropped` |
| `ow_degradation_total` | counter | — | `kind` | `degrade` |
| `ow_diag_total` | counter | — | `code`, `severity` | `diag` |
| `ow_query_total` | counter | — | `surface`, `verdict_state` | `retrieval_event` |
| `ow_query_latency_ms` | histogram | ms | `surface` | `retrieval_event.latency_ms` |
| `ow_query_channel_ms` | histogram | ms | `channel` | `json_each(retrieval_event.channel_ms)` |
| `ow_query_channel_status_total` | counter | — | `channel`, `status` | `json_each(retrieval_event.channels)` |
| `ow_query_confidence` | histogram | ratio | `surface` | `retrieval_event.confidence` |
| `ow_query_gate_total` | counter | — | `gate` | `json_each(retrieval_event.gates)` |
| `ow_compile_total` | counter | — | `target`, `gate_status` | `artifact` |
| `ow_compile_unit_total` | counter | — | `target`, `unit_outcome` | `artifact_unit` |
| `ow_toolchain_ms` | histogram | ms | `name` | `toolchain.run.ran_ms` |

Forty-seven rows. Four of them read a JSON column with `json_each`, which is stated in the source
column because a reader who assumes a scalar writes the wrong query; `retrieval_event.channels`,
`.channel_ms`, `.gates` and `.degraded_because` are JSON TEXT by
[storage, indexing and retrieval](07-store-and-retrieval.md)'s schema and this document does not
change that.

### 4.3 A histogram out of SQLite, without a percentile function

Fourteen rows above declare `type = "histogram"`, and SQLite has no percentile aggregate and no
guaranteed `log2()` — math functions are a compile-time option, so a bucketing expression that
calls one is a metric that works on the maintainer's build and fails on a distro's. The
mechanism is therefore boring on purpose:

- one bucket ladder, `ms_pow2`, with **explicit** base-2 boundaries
  `[1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]` —
  seventeen finite boundaries plus `+Inf`, covering 1 ms to 65 s, which brackets both a 38 ms
  lexical Channel and a 41 s VLM page;
- a second ladder, `bytes_pow2`, from 1 KiB to 64 GiB, for the two byte-valued histograms;
- the bucketing query is a `CASE` ladder generated from the ladder into
  `omniweave_core/store/sql/hist.sql` by the same emitter that writes `schema/metric-v1.json`, so
  the boundaries exist in exactly one place and a reviewer diffs a generated file rather than
  seventeen hand-written `WHEN` clauses;
- the export shape is an OTLP `Histogram` with `explicitBounds` equal to the ladder, `bucketCounts`
  from the query, and `sum`/`count` from the same scan. Not an `ExponentialHistogram`: the
  boundaries are fixed and shared across every metric, which is what makes two runs' histograms
  addable.

`ow top`'s in-process folds use the same ladder, so a live view and an exported histogram agree
by construction rather than by coincidence.

### 4.4 The five that belong on an on-call dashboard

Everything above is available; these five are what a pager should watch, and the reason each is
here is that it fails *before* the symptom a user reports.

1. **`ow_work_claimable{cost_class}` and `rate(ow_unit_settled_total)` on one axis.** Claimable
   flat and settled at zero is a stalled pipeline; claimable at `queue_high_water = 50000` with
   settled healthy is back-pressure working as designed. These two together distinguish "stuck"
   from "busy", which no single number can.
2. **`rate(ow_work_attempts_total{failure_class!=""})` by class.** The failure *mix* is the
   diagnosis: `rate_limited` is a provider problem, `needs_ocr` is a routing problem,
   `driver_crashed` is ours, `resource_limit` is a config problem naming its own knob.
3. **`ow_spend_micros_total` against `ow_budget_held{scope="unit"}` and
   `rate(ow_budget_deny_total)`.** Money, plus the headroom that will stop it. A rising deny rate
   with flat spend means the corpus is now being deferred rather than processed, which looks
   identical to progress from every other angle.
4. **`ow_query_total{verdict_state="degraded"} / ow_query_total`.** The honesty rate. This is the
   number that says the product is answering with caveats; if it climbs above a few percent the
   index or a Channel is broken, and the users have not noticed yet because the answers still
   arrive.
5. **`ow_store_wal_growth_bytes` and `ow_loop_lag_ms`.** The two numbers that precede an outage.

Metric 5 is the one that needed correcting, and the correction generalises. Raw WAL size is a
**monotone-non-decreasing observable that is not the quantity anyone cares about**: after a full
backfill the writer's next commit restarts the WAL from the top and the frames recycle inside the
same file, so the file's size says nothing about the un-backfilled backlog, and a size-triggered
alert (or valve) degenerates into firing forever once the file passes its threshold — measured in
the mined collection as a crawler slowing to ~9 minutes per 160 files with the writer permanently
parked. The transform is a **baseline refreshed on a confirmed-complete event**:
`store.wal_valve` carries `size_at_last_full_backfill`, refreshed whenever a checkpoint reports
everything backfilled, and `ow_store_wal_growth_bytes` is the growth past it.
`ow_store_wal_bytes` stays in the registry as context for a human reading a runbook; the alert
is on the growth series. omniweave has this same shape in two more places and the same transform
applies: `ow_cache_bytes` against live `cache_index` rows, and `ow_work_rows` against the
claimable subset. codegraph's recorded failure mode was 22 GB of WAL and exit 137, and
`loop_lag_max_ms = 250` breached means a commit is holding the loop, which is F29's 4M-cell
document.

**The anti-metrics.** There is no `documents_processed_total` as a headline — it is
`ow_unit_settled_total{outcome="ok"}` filtered, and a vanity counter that double-counts a
re-parse is worse than none. There is no cache *hit rate* as a gauge: the useful number is
`ow_cache_saved_micros_total`, because a 99% hit rate on the `signal` layer and a 4% hit rate on
the `call` layer differ by three orders of magnitude in value. And there is no
`ow_store_wal_bytes` **alert**, for the reason just given.

## 5. The cost ledger

### 5.1 Three writers, one authority

Cost is **physical, then priced** (INV-15): a driver reports a `Spend`
(`wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls, bytes_egress` + `provider`), and the
operator-owned `PriceBook` at `.omniweave/pricebook.toml` converts it. `DriverMetrics` has no
currency field, ever, and `Spend.micros(book)` is the one place money appears.

| writer | table | grain | role |
|---|---|---|---|
| the runner, on every attempt | `route_spend` | `(decision_id, attempt)` | **the authority.** Physical dimensions + `micros` + `was_cache_hit` + `would_have_been_micros` |
| the cache, on every write | `cache_index.spend_json`, `.micros` | one cache entry | the counterfactual: the `Spend` that produced the row, replayed on every hit |
| the runner, at run end | `driver_observation.cost_micros_total` | `(run_id, driver, driver_version, outcome, failure_class)` | the per-driver rollup, and the operability record |
| the runner, per work row | `work.cost_micros` | one work row | a denormalised convenience; **never summed for a bill** |
| the flusher | `retrieval_event.micros`, `.spend` | one query | read-path cost, in the events sidecar, never in `route_spend` |

An `op.*` operator has no `decision_id` — the `work` table's three pairing CHECKs make that
structural — therefore no `route_spend` row. Its cost is `work.cost_micros` and
`driver_observation` under the synthetic driver name `op.<name>`, and that asymmetry is why
`work.cost_micros` is not the bill: summing it would double-count every routed row.

### 5.2 Attribution: one view, three group-bys

I30 requires every micro to name exactly one `(unit, part, decision, attempt)`. The join that
makes that queryable is a view, so nobody writes it twice:

```sql
CREATE VIEW spend_attribution AS
SELECT u.unit_uri, u.unit_part, u.lane,
       d.decision_id, d.rung, d.driver, d.cost_class, d.slice_key, d.pinned,
       d.grant_id, d.admission,
       s.attempt, s.provider, s.outcome, s.was_cache_hit,
       s.wall_ms, s.cpu_ms, s.gpu_ms, s.tokens_in, s.tokens_out, s.calls, s.bytes_egress,
       s.micros, s.would_have_been_micros,
       d.generation, d.decided_at
FROM route_unit_decision u
JOIN route_decision d ON d.decision_id = u.decision_id
LEFT JOIN route_spend s ON s.decision_id = d.decision_id;
```

No new index is needed, and none is added: `route_unit_decision` is `WITHOUT ROWID` with
`PRIMARY KEY (unit_uri, unit_part, lane, decision_id)`, so a per-document lookup is a prefix
range scan of the primary key, and `route_decision_slice` already serves the per-driver and
per-slice group-bys. `route_unit_decision` also **survives `work` row deletion**, which is what
makes per-document cost answerable after a compaction.

Three properties of that view are deliberate and a "simplification" would break all three.

- The `LEFT JOIN` is correct: a `deferred` decision has no spend row, and a per-document report
  that silently dropped deferred decisions would show a document as free when it was in fact
  refused. `d.admission` is selected so a reader can tell `micros IS NULL` (deferred) from
  `micros = 0` (a free driver ran).
- Escalation makes the view **one row per attempt per rung**, not one row per document. A
  188-page PDF that escalated 31 pages has 188 `DECODE` rows plus 31 `PAGE` rows plus 3 `REGEN`
  rows in this view. Every consumer therefore aggregates; nothing counts rows as documents.
- **`d.cost_class` is selected, and it is the only place the money and the class meet.**
  `route_spend` carries no class column and `route_decision.cost_class` is frozen at decision
  time ([routing](05-ingest-and-routing.md) §7.1's `route_decision` DDL), so this join makes
  `ow_spend_micros_total{cost_class}` (§4.2) a real series and the `class` column of
  `ow cost --by driver` (§5.4) a real column. Reading the class from the live driver catalog
  instead would re-label history the first time a card's `[cost.model]` changed.

**`route_scoreboard.micros` is not the bill either, and no cost surface reads it.** That view
([routing](05-ingest-and-routing.md) §8.2) ends in `WHERE d.pinned = 0`, because a decision an
operator pinned may not justify demoting the rule it bypassed — and the filter is on the whole
row, so every micro spent under a `[[pin]]` leaves the view's `micros` column with it. That is
intended: `micros` there is per-slice context for a `state`, not an amount owed. The pinned
spend is not lost — it is in `route_spend`, and it is in `spend_attribution`, which selects
`d.pinned` and filters on nothing. Summing a bill from the scoreboard under-counts by exactly
the pinned decisions, which is why §5.4's `--verify` reconciles against `route_spend` and this
section's three group-bys are all over `spend_attribution`.

The three group-bys, which are the only ones any surface needs:

- **Per document:** `GROUP BY unit_uri` over `spend_attribution`, plus the `doc` row's
  `doc_key` and `gen` to name the generation the money bought.
- **Per corpus:** the same view without a `WHERE`, plus `service_observation` for GPU time the
  driver could not see (§5.3), plus `retrieval_event` for read cost. One corpus is one store, so
  a corpus total is one query; a multi-corpus total is N queries the surface sums and says so.
- **Per driver, over time:** `GROUP BY driver, date(decided_at/1000,'unixepoch')` — the query
  behind `ow cost --by driver --since 7d`, and the lagging indicator for a forgotten
  `schema_version` bump (a driver's spend falling to zero after a release, §6.6).

### 5.3 GPU-seconds, and the one place attribution is genuinely approximate

Three sources of `gpu_ms`, and they must not be added:

1. **A local-compute driver on its own device** reports `DriverMetrics.gpu_ms` measured around
   its own kernel launches. This is exact and lands in `route_spend.gpu_ms`.
2. **A `billed_api` provider** reports no GPU time at all; its cost is `tokens_in`/`tokens_out`
   and `calls` priced through `PriceBook.provider`. `gpu_ms` stays 0, and pricing GPU time here
   would double-charge.
3. **A Service-backed driver** (S3) cannot observe the server's GPU time from the client side.
   The driver reports `gpu_ms = 0` and `wall_ms` for its request; the **runner** attributes GPU
   time from `service_observation.gpu_ms`, apportioned across that Service's
   `service_observation.requests` for that run in proportion to each request's `wall_ms`.

The apportionment, exactly, so it is implementable and its error is nameable:

```text
  for one (run_id, service, config_digest) row:
      total   = service_observation.gpu_ms
      w_i     = the wall_ms of request i, from its `call` span
      gpu_i   = total * w_i / Σ w_j        , integer division
      residue = total − Σ gpu_i            , assigned to the largest w_i
```

The residue clause is why the corpus total reconciles exactly rather than to within N micros:
integer division loses up to `len(requests) − 1` ms and dropping it would put a growing,
unexplained gap between `Σ route_spend.gpu_ms` and `service_observation.gpu_ms`.

Item 3 is approximate, and the size of the error is stated rather than hidden: under server-side
Coalescing a batch of heterogeneous requests shares one forward pass, so a short request batched
with long ones is over-charged and the reverse is under-charged. The apportionment sums to the
Service's measured total exactly, so a **corpus** bill is right and a **per-document** GPU figure
inside a coalesced batch is an estimate. `ow cost --by document` prints `gpu_ms~` with a tilde
for any document whose GPU time came through this path, and the run manifest carries
`cost.gpu_ms_apportioned` separately from `cost.gpu_ms_measured`. This is the honest form of a
number that cannot be measured client-side; F7's unmeasured 1.5×–4× Coalescing speedup is the
same uncertainty seen from the throughput side.

### 5.4 `ow cost`

```text
ow cost [--corpus N] [--by driver|document|provider|lane|rung|slice|day]
        [--since <dur>|--run <run_id>] [--currency] [--verify] [--render text|json]
```

```text
$ ow cost --corpus handbook --by driver --since 7d
driver                class          units    calls  tokens_in  tokens_out      gpu_ms     micros    hits         saved
parse.page.olmocr     local_compute  1,214    1,214          0   4,981,220   2,913,600    671,876  74,982    41,498,038
derive.entity.llm     billed_api       318      318  1,884,220     212,004           0  6,830,000   1,272    27,320,016
derive.segment.spine  free          88,406        0          0           0           0          0  12,004             0
parse.pdf.pdfium      free          18,402        0          0           0           0          0       0             0
parse.office.anydoc   free          70,004        0          0           0           0          0       0             0
op.resolve            local_compute      1        0          0           0           0          0       0             0
                                                                            TOTAL   7,501,876            68,818,054
cache saved 68,818,054µ (9.2x the bill).  worked: olmocr 74,982 hits x the 2,400 ms mean gpu_ms
  of a miss x pricebook gpu_ms 0.2306 µ/ms = 41,498,038µ.
deferred 0 rows (no dimension exhausted in this window).  gpu_ms 2,913,600 all APPORTIONED (~).
pricebook 4b1f9c2a effective_from 2026-07-01 currency EUR
reconcile: Σ route_spend.micros = 7,501,876 == manifest.cost.billed_micros  OK
```

Four things in that output are checkable rather than decorative: `TOTAL` is the sum of the
`micros` column; `saved` is the sum of the `saved` column and the ratio is `saved / TOTAL`; the
worked line shows the one arithmetic step that turns cache hits into money, so a reader can
repeat it for the other row; and the `~` note says every GPU figure here came through §5.3's
apportionment, because olmocr runs behind a Service. *(Build note, D838: `ow cost --by driver` ships, reading from `omniweave.run.cost`, with `--run R` and `--render json`. A routed row's numbers are `route_spend` joined to `route_decision` directly, because the `spend_attribution` view repeats a decision once per unit it serves. `units` counts the distinct units in `route_unit_decision`. The class is the decision's frozen `cost_class`, a decision with no driver is `(no driver)`, and each `op.*` operator is its own row, as `op.resolve` is above. TOTAL, saved and the reconcile line are printed. A mismatch is printed and not exited on, because that is `--verify`'s job. The other six `--by` slicings, `--since`, `--currency` and `--verify` are not served yet: `work` records no outcome for I30's audit, and parse rows carry no spend.)* *(Build note, D855: under `--run`, a run's `op.*` rows are those whose `last_attempt_at` falls in its span, `started_ns` to `ended_ns`, open while it runs. D838 kept those whose `claimed_gen` was the run's, but completing a work row clears that column, so a real run's table never showed `op.identify`. One store has one writer, so two runs' spans cannot overlap.)*

`--verify` runs I30's two self-checks and exits non-zero on a mismatch: `Σ route_spend.micros ==
manifest.cost.billed_micros` **exactly**, and every `ok`/`ok_partial` work row with a
`decision_id` has at least one spend row. A Sequence's apportionment must sum to the session
±1 micro (integer division). A mismatch is `OW-R-*` and names the run. *(Build note, D853: `ow cost --verify` ships. It checks the run `--run` names, or the latest one, and prints a `verify` line per check after the bill. The first check is the reconcile, exact, and a manifest that does not read fails it. The second counts `done` work rows whose decision is the run's generation and that have no spend row; completing a row clears its `claimed_gen`, so the generation is the decision's. A failure is `OW-R-031` `OW_ROUTE_SPEND_UNRECONCILED`, exit 70. The apportionment check is not made, because no session total is recorded apart from its parts. On a real `ow add` of the Tier-A fixtures the second check fails: 26 finished parse rows have no spend row, because the parse operator's `StepMetrics` carries no `Spend` and D733 writes a row only when one was measured.)*

`--currency` multiplies by `PriceBook.currency` and prints the `pricebook_digest`, because a bill
without the price list it was computed against is not auditable. The pricebook is versioned and
digested per run (`run.pricebook_digest`), so re-pricing history is `ow route replay --pricebook`
and costs nothing — `evaluate()` is pure and the evidence payloads are stored.

**What `ow cost` does on a compacted or truncated ledger.** `--since` beyond the 400-day decision
retention prints the window it actually covered and a line naming the earliest `decided_at` it
found; a bill that silently starts where the sweep stopped is a bill with a hole. A compaction
that reset a ledger emits `Degradation(kind="ledger_reset_by_compaction")`, and `ow cost` renders
it above the table rather than in a footnote. *(Build note, D839: `--since <n>m|h|d` keeps decisions whose `decided_at` is at or after the cutoff, and `op.*` rows whose `last_attempt_at` is. It is refused alongside `--run`. When the cutoff reaches past the ledger's earliest decision, a line names that decision's date, which is this paragraph's "window it actually covered". The `ledger_reset_by_compaction` degradation is not read yet. `--by` now serves provider, lane, rung, slice and day besides driver, each keeping the frozen class. `op.*` rows are the synthetic `op` row under every slicing but `driver` and `day`. A provider of `''` is `local`. `document` stays refused, because one decision serves several documents and a per-document row would need section 5.3's apportionment. The reconcile line sums `route_spend` whatever the slicing.)*

### 5.5 Retention

Retention of the routing ledger is
[acquisition, parsing and routing](05-ingest-and-routing.md)'s: 400-day decision rows, 30-day
evidence blobs, `audit_selected`/`pinned`/`degraded`/`REGRESSED` rows never aged out, and
~1 GB per million parts falling to ~360 MB after the sweep. This document depends on exactly one
consequence of it: **`route_unit_decision` outlives `work`**, which is what makes a per-document
cost answerable after `work_compact_above = 5000000` has archived the queue into `work_done`
(which preserves `cost_micros`). The event stream's own retention is §3.3's.

## 6. Explaining a result

### 6.1 `ow query --explain`

`--explain` adds an `ow:explain` section after `ow:trailer`. It shows three things a user cannot
otherwise get: which signals fired, which producer made each block, and at what calibrated
confidence.

```text
$ ow query --corpus handbook "parental leave notice period" --explain
ow/1 ok corpus=handbook@41 fresh blocks=9/61 docs=3/17 chars=18412/22000 calls=1/3 spend=0µ scorer=1
... (ow:evidence, ow:provenance, ow:notseen as specified in the Answer document) ...

**ow:explain**
plan          plan_digest=7c3f19a2  rule="mixed-text" (project:.omniweave/policy.d/10-retrieval.toml:23)
narrow        Filters(layers={BODY}, min_trust=INFERRED)  kind=set  n=38,104  prefilter_exact=1
snapshot      gen=41  held 41 ms of snapshot_ms=2000  one BEGIN DEFERRED for all channels

channel      status              ranked  ran_ms/budget  weight  contribution to best hit
identity     empty                    0       1 /  15    2.0    0.00000   (counts in ceiling)
exact        empty                    0       0 /  25    1.2    0.00000   (counts in ceiling)
lexical      ok                     214      38 /  50    1.0    0.01639   rank 1
structural   empty                    0      12 /  40    0.4    0.00000   re-seeded from lexical
semantic     off(vectors_disabled)    0       0 /  80    0.8    ---       operator choice, disclosed
             ceiling = (2.0+1.2+1.0+0.4)/61 = 0.07541      best = 0.01639
             confidence = 0.01639 / 0.07541 = 0.217  ->  low_confidence (< 0.35)

block                producer                                    method      trust      quote      score
handbook:d7#412      parse.pdf.pdfium@2.1.0 op=parse.pdf/3       text_layer  extracted  verbatim   0.98
                     code_fp=9c1e4a  options=4b1f  decision=dec_8a91f3  rung=DECODE  micros=0
                     byte_exact: re-read part cas://a1/b2/9f8e… -> equal
handbook:d7#418      parse.pdf.pdfium@2.1.0 op=parse.pdf/3       text_layer  inferred    reflowed   0.71
                     score_kind=layout_softmax  calibrated: p_hat=0.74 [0.69,0.79] n=1,204
                     slice=producer_family:acrobat/lang:de  eval_set=golden-2026-07
handbook:d9#88       derive.entity.table@0.4.0 op=derive.entity/2 heuristic  inferred    normalized 0.55
                     grounded via mention 4127 -> block 88 span (12,31)  taint=0x0

verdict       state=low_confidence  gates=[]  freshness=fresh  coverage=17/17
              fusion=rrf  scorer=1  space=none
```

Four things in that transcript are load-bearing and non-obvious.

- **An `empty` channel's weight is in the ceiling.** It discloses "we looked there and found
  nothing", which is the confidence penalty an honest ceiling carries; `off` contributes nothing
  and is labelled an operator choice. `unavailable` would force `degraded`. Nobody may
  "simplify" `ceiling()` to match `fuse()` — ST6's property test has two halves for that reason,
  and half (a) is false on the shipped default because `vectors = "off"` makes `semantic` empty.
- **The producer line is the six provenance axes, spelled out**: reproduction (`producer_id`'s
  tuple, printed as `op=`, `code_fp=`, `options=`), method, ownership (`op=` is
  `origin_operator`), trust, score with its named `score_kind`, and cost
  (`decision=`/`micros=`). One line per axis-group, never a single "confidence" number.
- **The renderer consumes `Calibrated.status`, never the float** (INV-19, Q-G14). `--explain` is
  the one surface that prints the raw value *alongside* its `p_hat`, Wilson interval, `n`,
  `slice_key` and `eval_set_id`, so a reader can see that 0.71 on a layout softmax means an
  empirical 0.74 on this slice — and where calibration is missing the line reads
  `calibrated: unavailable (no eval set for slice …)` rather than implying the float is a
  probability. It is the one exception, and it exists because a surface that prints a number and
  its calibration together is not the failure mode Q-G14 guards against; a surface that prints
  the number alone is.
- **`byte_exact` is proved, not claimed**: the line names the CAS ref it re-read, on whichever of
  INV-10's three branches the producing driver's `os_kind` selects.

`--render json` emits the same content against `schema/answer-v1.json`, with `explain` as a
sibling of `verdict`; every field above is a real key, so a UI does not scrape text.

**Cost of `--explain`, because a diagnostic that changes the answer is not a diagnostic.**
`--explain` adds no channel, no store read on the query path and no work row; the calibration
lookup is one indexed read per distinct `(score_kind, slice_key)` in the returned set, bounded by
the packing tier's `max_docs`, and it happens **after** the snapshot closes. `plan_digest` and the
channel table come from the `Verdict` the query already built. So `--explain` is renderer-side and
`retrieval_event.latency_ms` is unaffected — which is also why `--explain` may be passed on a
production surface without a footnote.

### 6.2 `ow why <ref>` — one verb, four subjects

```text
ow why <cite>          a Block: the six provenance axes, the decision, the rebind history
ow why <path>[#pN]     a document or part: the ingest report of §7
ow why <run_id>        a run: the manifest, rendered, with the degradation list expanded
ow why absent "<q>"    an absence: the fifteen gates in precedence order, with the fix commands
```

`ow why absent` is the one an agent needs most, because a zero result is the answer most likely
to be believed:

```text
$ ow why absent --corpus handbook "is liability capped at twelve months of fees"
verdict          degraded   (NOT citable as absence)
gates fired      [parse_gap_in_scope]        checked in precedence order 1..15
  1 timed_out                     pass   snapshot 38 ms / 2000, no channel over its budget
  2 channel_unavailable           pass   semantic=off is an operator choice, not unavailable
  3 store_changed_mid_query       pass   gen 41 at plan and at pack
  4 coverage_incomplete           pass   discovered=17 indexed=17 complete=1
  5 pending_work_in_scope         pass   0 rows pending|claimed for units in scope
  6 source_edited_unindexed       pass   max(mtime_ns)+2s <= indexed_at_ns
  7 freshness_unknown             pass   17/17 stat-checked
  8 inputs_unreadable             pass
  9 parse_gap_in_scope            FAIL   OW_NEEDS_OCR on 2024-appendix.pdf p.12-15
                                         diag_codes=[OW_NEEDS_OCR]  where=[(9,12,15)]
                                         fix: ow add 2024-appendix.pdf --allow-cost 40000
 10 restricted_withheld           pass   0 rows removed by deny_restriction_bits
 11 filter_starved                pass   no ANN ran, so nothing to over-fetch or post-filter
 12 truncated_by_packing          pass   matches_before_packing = 0
 13 space_mismatch                pass   vectors = "off", so there is no space to mismatch
 14 shard_unreachable             pass   not federated
 15 similarity_only               pass   semantic did not run, so vacuous
what this means  4 pages that could contain the answer were never read. This is NOT an
                 absence claim and must not be reported as one.
```

The precedence order is printed *with the checks that passed*, because `gates=[]` tells a reader
nothing about what was verified. Gate 15 (`similarity_only`) is checked last on purpose: every
gate above it names something the caller can fix, and a cosine zero is a statement about the
model, not about the corpus. The gate list, its precedence and the one citability rule are
[storage, indexing and retrieval](07-store-and-retrieval.md)'s; this section owns only the
rendering, and the rendering's one obligation is that **it prints all fifteen rows, passes
included** — a report that shows only the failure teaches a reader that the other fourteen gates
do not exist.

**There is no "not evaluated" row, and there never can be.** All fifteen gates run on every
query — [storage, indexing and retrieval](07-store-and-retrieval.md) §6.7 states it and §6.8's
table is the closed list — so a fired gate does not end the ladder. Gate 9 firing above is why
the verdict is `degraded`; it is not why gates 10-15 would be skipped, because they are not.
Three facts hold this shut: `Verdict.gates` and `Verdict.degraded_because` are both plural and
§6.6's worked plan reports three fired gates numbered 4, 5 and 9; [quality](13-quality.md)'s
`degradation_detection == 1.000` asserts that the *expected* gate appears in `Verdict.gates`,
which a short-circuit breaks the instant two gates fire, and P-11 requires the reported list to
be in precedence order for **any subset** of the fifteen forced to fire — a property with no
content unless a subset can be larger than one; and gates 4-9 all read one `Coverage` object from
one scan, so stopping early would save nothing to trade the disclosure for. A renderer that
printed `10..15 … not evaluated` would be describing an evaluator this framework does not have.

### 6.3 `Degradation` — the one downgrade record, and its twenty-seven kinds

`Degradation` is the framework's **only** typed downgrade record. It is *carried*, never raised:
[system architecture](02-architecture.md) §7.1's six-vocabulary table places it beside `OwError`,
`Diag`, `Finding`, `Rejection` and the `quarantine` row, and that separation is not repeated here.
Charter §5 X21 fixes the shape — one enum for the whole framework, extended by literal, never
re-invented per layer — and **this section is the type's sole home** (charter §9 errata `E15`).
Every other document constructs a `Degradation`; this one prints it and owns the member count.

```python
# omniweave_core/observe/degradation.py — a T-SCHEMA published read contract.
# schema/degradation-v1.json is generated from this module and byte-diffed by G6.
# Rung is omniweave_core.route.rung.Rung (05 §5.2); a read-path Degradation has none.

DegradationKind = Literal[
    # routing and admission
    "budget", "signal_unavailable", "driver_unavailable", "acceptor_exhausted",
    "rung_ceiling", "policy_pruned", "auto_demote", "no_driver",
    # drivers, isolation, packaging and the toolchain
    "discovery_slow", "quarantine", "deprecation", "isolation_shortfall",
    "toolchain_missing", "pin",
    # store, cache and the read path
    "store_busy", "stat_stale", "pushdown_unavailable", "vector_scan_over_budget",
    "hub_capped", "segment_lift_capped", "cache_disabled_no_space",
    "ledger_reset_by_compaction",
    # generation, governance and telemetry
    "grant_missing", "compile_normalized", "scope_clamped", "calibration_stale",
    "events_dropped",
]   # TWENTY-SEVEN, closed. The register below is the normative list; adding a member is one
    # edit to that table, to this literal and to §4.2's series-count note, in the same change.

@dataclass(frozen=True, slots=True)
class Degradation:
    kind: DegradationKind
    message: str                       # one sentence, for a human. It MUST name the knob or the
                                       # command that would undo this, in prose; `knob` and
                                       # `fix_command` carry the same fact machine-readably.
    # --- what was downgraded -------------------------------------------------------------
    unit_uri: str | None = None        # §8.3's redacted `u:<hash>` form; {run_id}.paths.json
                                       # resolves it. None when the subject is the run, the
                                       # query or the store rather than one unit.
    parts_affected: tuple[int, ...] = ()   # 1-based part ordinals. Consumed by 07 §5.6's
                                       # segment_lift_capped and by §7's ingest report.
    wanted_driver: str | None = None   # the DriverId this concerns — the one asked for
                                       # (driver_unavailable, no_driver) or the one that fell
                                       # over (quarantine, discovery_slow, deprecation).
    # --- the arithmetic, when the cause is a bound that was reached ----------------------
    unit_dim: str | None = None        # the exhausted dimension: "micros", "wall_ms",
                                       # "max_cost_class", "vram_bytes", "chars". None means
                                       # this degradation is not a bound, and spent == limit == 0.
    spent: int = 0
    limit: int = 0
    rung_reached: Rung | None = None   # the escalation ladder's position when it stopped.
                                       # None on every read-path member: the ladder is the
                                       # router's, and 07's Channels never occupy one.
    # --- the recovery --------------------------------------------------------------------
    knob: str | None = None            # ONE fully-qualified config or policy key, e.g.
                                       # "[budget.per_unit].micros_per_part". None means no
                                       # knob raises this limit — R3's "raise nothing — fix
                                       # the driver" is a real and common answer.
    fix_command: str | None = None     # the exact command line that clears it, e.g.
                                       # "ow add invoice.pdf --allow-cost 12000".
```

Six rules hold over the record, and each has a consumer that breaks without it.

1. **`knob` is the CI-checked half; `message` is the human half.** The charter's rule — a
   `Degradation.message` must name a knob that exists and would raise the limit — is enforced by a
   test that resolves the *quoted key* out of the message template against the config and policy
   schemas. With `knob` printed, that test resolves the field, and the message scan becomes a
   redundant second reading rather than the only one. `knob = None` is a positive assertion, not an
   omission: it says a configuration change cannot help, and the test then requires either
   `fix_command` or a `message` naming the non-configuration remedy.
2. **`unit_dim is None` implies `spent == limit == 0`,** asserted in `__post_init__`. Seventeen of
   the twenty-seven members carry no arithmetic, and a zero pair rendered as "0 of 0 spent" is the
   defect this rule exists to prevent.
3. **A resource that runs out is `kind="budget"` with a new `unit_dim`, never a new member.**
   [routing](05-ingest-and-routing.md) §6.4 already settles this for `max_cost_class`, and it is why
   VRAM pressure evicting a GPU group ([runtime](08-runtime.md) §3.8) is
   `Degradation(kind="budget", unit_dim="vram_bytes", wanted_driver=<the evicted service's driver>)`
   rather than a twenty-eighth member.
4. **The carrier identifies the subject, so the record carries no `run_id`, `query_hash` or
   `artifact_gen`.** A `Degradation` lives in `route_decision.degradations`, `artifact.degradations`,
   the query-ledger row, or the run manifest, and each of those rows already names its own subject.
   Duplicating the key onto the record would give one fact two homes and two ways to disagree.
5. **`parts_affected` is the field name and the serialised key, everywhere, and there is no short
   form.** The JSON in `schema/answer-v1.json`, `schema/degradation-v1.json` and every
   `degradations` column is `parts_affected`, because a UI reads the JSON and the terminology lock
   allows the concept one name. Exactly one `ow:trailer` transcript still prints the key as
   `parts:` to save width — the charter's own, in §D9's "The Answer document", where the body is
   immutable and charter §9 errata `E20` carries the correction. It is wrong against this rule,
   not licensed by it: a transcript that abbreviates a serialised key is where a client author
   learns the wrong shape. [interfaces](10-interfaces.md) §3.6 and
   [api sketch](18-api-sketch.md) §2.5 print `parts_affected` in full. This document prints no
   such abbreviation, and nothing here defines a wire alias for the field.
6. **Every `Degradation` is visible on every surface it reaches** — the result, the run manifest and
   the serve envelope (I18, and charter §6.5's carrier table). There is no suppressed variant and
   therefore no visibility flag on the record; the only per-kind variation is whether an instance on
   the read path also forces `Verdict.state = "degraded"`, which the register's last column decides.

#### The register — twenty-seven members, one row each

`emitted by` is the document that constructs the member, and is the document to ask when a row's
meaning is unclear. **forces degraded** says whether an instance reaching a query forces
`Verdict.state = "degraded"`; `n/a` marks a member that cannot occur on the read path at all.

| # | member | emitted by | what it records | knob or fix | forces degraded |
|---:|---|---|---|---|---|
| 1 | `budget` | [routing](05-ingest-and-routing.md) §6.4, §10.3 | a declared budget dimension was exhausted and the work settled short | `[budget.per_unit].micros_per_part`; `--allow-cost` | n/a |
| 2 | `signal_unavailable` | [routing](05-ingest-and-routing.md) §2.1, §4.3 | a rule's key never resolved, so `on_unknown='defer'` fell through to `skip` | the key's provider driver | n/a |
| 3 | `driver_unavailable` | [drivers](04-driver-system.md) §4.5, [routing](05-ingest-and-routing.md) §10.3 | the chosen driver is absent, not enabled, or refused by `[licence] allow_tiers` | `[drivers] enabled`; `[licence] allow_tiers` | n/a |
| 4 | `acceptor_exhausted` | charter §D4 — no plan document constructs it yet | every acceptor on a lane rejected the output and the ladder had no rung left | the failing acceptor's `@thresholds` key | n/a |
| 5 | `rung_ceiling` | [routing](05-ingest-and-routing.md) §5.2, §7.1 | `--max-rung` or `RouteHints.max_rung` stopped an escalation that would have succeeded | `--max-rung` | n/a |
| 6 | `policy_pruned` | [routing](05-ingest-and-routing.md) §4.3 | a subsumed rule was dropped from the demand plan and its keys were never computed | the subsuming rule's id | n/a |
| 7 | `auto_demote` | charter §D4; [routing](05-ingest-and-routing.md) §8.3's automatic write is its first site, over §8.2's scoreboard states | a slice was `REGRESSED` twice consecutively and its rule was demoted with no operator in the loop | `[audit] auto_demote` in the shipped policy ([routing](05-ingest-and-routing.md) §4.4) | n/a |
| 8 | `no_driver` | [architecture](02-architecture.md) §7.4 | a zero-candidate resolution — a routing outcome, not an exception | `[drivers] enabled`; `ow drivers explain` | n/a |
| 9 | `discovery_slow` | [drivers](04-driver-system.md) §4.4 | discovery crossed the 250 ms hard ceiling; the slowest step is named | `ow drivers explain --discovery` | n/a |
| 10 | `quarantine` | [drivers](04-driver-system.md) §6.2, [runtime](08-runtime.md) §3.8 | three crashes or health failures in 60 s took a driver out **for the run**; affected plans re-route | `[drivers] crash_quarantine.crashes`, or none — fix the driver | n/a |
| 11 | `deprecation` | [drivers](04-driver-system.md) §5.4, [model](03-document-model.md) §15.4, [repo](11-repo-layout.md) §4.4 | something inside its `since <= RELEASE < removed_in` window was used; the replacement is named | the replacement's id | no |
| 12 | `isolation_shortfall` | [drivers](04-driver-system.md) §6.2 | an isolation control was requested and the OS did not provide it; the control and the OS are named (DR10) | none — the platform is the limit | no |
| 13 | `toolchain_missing` | charter §D8; [generation](09-generation.md) §9 is its first site | a compile tier needs a toolchain that is not installed, so the tier stays `unavailable` | `ow doctor --deep`, then the install command | n/a |
| 14 | `pin` | [repo](11-repo-layout.md) §2.6, §7.2 | a component resolved `unpinned` — an editable or path install absent from the release manifest | `pip install omniweave==<release>` | no |
| 15 | `store_busy` | [architecture](02-architecture.md) §5.4 | a write verb met the scoped lock; the envelope returns `accepted = false` naming the holder's host | `[store] lock_wait_ms` | no |
| 16 | `stat_stale` | [store](07-store-and-retrieval.md) §3.8, §14 | `stat.computed_ns` is past `STAT_MAX_AGE_NS`, so the over-fetch factor took its maximum clamp of 64 | `ow index stats` | **yes** |
| 17 | `pushdown_unavailable` | [store](07-store-and-retrieval.md) §6.3 | a `VectorBackend` declared no pushdown, so narrowing could not precede ranking and recall is at risk | `[retrieval] backend` | **yes** |
| 18 | `vector_scan_over_budget` | [store](07-store-and-retrieval.md) §3.9 | 197k–250k segments: the brute-force scan still serves, but expects `UNAVAILABLE(timeout)` on a cold page cache | `[retrieval] backend` | **yes** |
| 19 | `hub_capped` | [store](07-store-and-retrieval.md) §5.2 | a block above `Expand.hub_cap = 4096` contributed a weight-sampled subset of its neighbours | `Expand.hub_cap` | **yes** |
| 20 | `segment_lift_capped` | [store](07-store-and-retrieval.md) §5.6 | a segment above `SEM_BLOCKS_PER_SEGMENT = 64` lifted only its first 64 members in `segment_block.ord` order | `SEM_BLOCKS_PER_SEGMENT` | **yes** |
| 21 | `cache_disabled_no_space` | [runtime](08-runtime.md) §4.7 | the cache write refusal latched at `cache.min_free_bytes`, so `with_cache` is a pass-through for the rest of the run | `[cache] min_free_bytes` | no |
| 22 | `ledger_reset_by_compaction` | [runtime](08-runtime.md) §1.8, [interfaces](10-interfaces.md) §8.3 | `work_compact_above` cleared a ledger, so the next Answer re-sends evidence it had already sent | `work_compact_above` | no |
| 23 | `grant_missing` | [generation](09-generation.md) §5.3 | a compile had to fetch an asset with no site Grant; the compile REFUSES and the Grant and its `dpa_ref` are named (OUT10) | the Grant id | n/a |
| 24 | `compile_normalized` | [generation](09-generation.md) §4.5 | a `normalize`-disposition rewrite was accepted; one record per `normalizations` entry | `--accept-normalization` | no |
| 25 | `scope_clamped` | [interfaces](10-interfaces.md) §3.2 | a page-range upper bound above `doc.pages` was clamped rather than refused | the corrected range | **yes** |
| 26 | `calibration_stale` | [quality](13-quality.md) §9.5 | a calibration curve is past `max_age_days = 30`, so `Calibrated.status = 'stale'` (Q-G13) | `ow eval calibrate` | **yes** |
| 27 | `events_dropped` | this document, §1.1 and §3.3 | the bounded 64k drop-oldest queue discarded records, or `ndjson_path` was unwritable | `[observe] ndjson_path`; `[observe] sample` | no |

Rows 1–4, 6, 7, 10–14, 19, 20, 22, 23 and 26 are the charter's sixteen. Rows 5, 8, 9, 15–18, 21,
24, 25 and 27 are the eleven the charter's closed literal did not admit and that written plan documents already
construct — registered as `15#1` in [risks](17-risks.md) and as `E15` in the charter's §9 errata,
whose closing condition is this table. Three members — `acceptor_exhausted`, `auto_demote` and
`toolchain_missing` — are charter grants that no document constructs yet; their rows name the first
site each will land in, so a reader can tell a reserved member from a live one.

**Seven of the twenty-seven force `degraded`** — rows 16–20, 25 and 26, and they are
`FORCES_DEGRADED`. That is this type's entire interface to the honest-absence contract, and it is
small on purpose. A downgrade that happened during *ingest* (rows 1–14 and 23, marked `n/a`) is
disclosed on the document and in the manifest and does not by itself make a later query dishonest —
the fifteen absence gates read the `Diag` rows it produced, not these records. Five more (rows 15,
21, 22, 24 and 27) can occur while a query is running and still do not force `degraded`, because
each of them changes what the *system* did and not what the *ranking* means: a lock wait, a
pass-through cache, a re-sent evidence block, an accepted rewrite, a dropped span. The seven that
do force it each say the same thing — the ranking the caller is looking at is not the ranking the
corpus supports.

#### What the manifest stores, and why it stays bounded

§1.1 claims the manifest's `degradations[]` is bounded because it is "a dict keyed by a closed
vocabulary". That holds only with a roll-up, because a 188-part document can produce 188 `budget`
records. So:

```python
MAX_ROLLUP_PARTS = 64        # matches MAX_SPAN_BUFFER_EVENTS (§2.4); §7's report prints a count

@dataclass(frozen=True, slots=True)
class DegradationRollup:     # the VALUE of one manifest.degradations[<kind>] entry
    kind: DegradationKind
    n: int                   # how many records merged into this entry
    first_ns: int            # host Clock at merge time — injected, never ambient (§3.2).
    last_ns: int             # A driver contributes no field to the manifest (§1.1).
    units: tuple[str, ...]           # distinct redacted unit_uris, capped at MAX_ROLLUP_PARTS
    parts_affected: tuple[int, ...]  # union of the merged records', capped the same way
    truncated: bool          # either cap was hit, so a reader never reads the cap as the total
    exemplar: Degradation    # the first record, verbatim — it carries message, knob and fix
```

`manifest.degradations` is therefore at most twenty-seven entries of bounded width, which is what
makes it safe to rewrite the manifest incrementally at every Stage boundary and at every
`degrade()`. The serve envelope's `degradations` is the un-rolled list for that one answer, because
one answer cannot produce twenty-seven of anything.

#### The three carriers, the event, and the metric

| carrier | shape | written by | read by |
|---|---|---|---|
| the result | `degradations: tuple[Degradation, ...]` on `Verdict` and on the ingest result | the host | `ow query`, the serve envelope, `--render json` |
| the run manifest | `degradations: dict[DegradationKind, DegradationRollup]` | `omniweave/run/manifest.py` | `ow why <run_id>`, §7's ingest report, CI Counters |
| the ledger | a `degradations` JSON TEXT column on `route_decision`, on `artifact`, and on the query-ledger row | `Store.complete()`, the OUT compiler, the query-ledger flusher | `ow cost`, `ow why`, SQL |

The `degrade` event carries **two** fields, `degradation_kind` and `message`, and that is
deliberate: the event stream is diagnostic and droppable (§1, rule 1), so the full record must be
reconstructable from the ledger and never only from a span. `ow_degradation_total{kind}` (§4.2) is
therefore exactly **twenty-seven series** — a closed enum, inside §4.1's cardinality contract, and
the second metric after `ow_diag_total` whose series count is a fact about a file in the repository
rather than about the data.

#### The contract this section needs from `Verdict`

**`Verdict` carries `degradations: tuple[Degradation, ...]`, and `build_verdict()` sets
`state = "degraded"` when any member of it is in `FORCES_DEGRADED` — the seven rows above —
independently of the fifteen absence gates and of `degraded_because`.** The gates, `DegradeCause`,
`build_verdict()` as the only constructor and the printed `Verdict` dataclass belong to
[storage, indexing and retrieval](07-store-and-retrieval.md) §6 and none of them is restated here;
`FORCES_DEGRADED` is defined beside `DegradationKind` in `omniweave_core.observe.degradation`, so
the read path imports one name and this document keeps the count.

## 7. Explaining an ingest

`ow why <path>` answers the two questions an operator actually asks — why did this take so long,
and why did it cost that — from the ledger, with no re-run.

```text
$ ow why ./contracts/msa-2024.pdf --corpus contracts
document      msa-2024.pdf   doc_key=3f1a…  doc_ord=41  gen=3  status=ok  188 parts
              declared=parse.pdf.pdfium@2.1.0  achieved: origin_span=exact spatial=exact
                                               math={} tables=basic notes=false
elapsed       11m 42s        first enqueue 00:29:14 -> last settle 00:40:56
Σ over rows   Σ queued 41m 08s   Σ ran 18m 53s   over 193 work rows   <- SUMS, NOT WALL (§6.7)
              queued/(queued+ran) = 69%: [budget] max_inflight.local_compute = 2 was the
              binding constraint, not the driver

Stage         elapsed   units   cached   ok   partial   failed   deferred
discover         0.3s       1        0     1        0        0          0
plan             0.9s       1        0     1        0        0          0
parse         10m 51s     188       22   181        7        0          0
derive            38s       3        0     3        0        0          0
index              9s       1        0     1        0        0          0
              Σ elapsed 11m 39s; the 3 s against wall is inter-Stage handoff, not lost time.

Rung ladder (parse, lane=text)                 parts   Σ ran     micros   driver
GATE                                             188     0.4s         0   -
DECODE   deterministic text layer                188      22s         0   parse.pdf.pdfium
PAGE     escalated: garble.score>=0.50            31  15m 41s    15,727   parse.page.olmocr
REGEN    attempt 2, repeat_ngram_max tripped       3   1m 22s     1,540   parse.page.olmocr
DEGRADE  olmocr quarantined after 3 crashes/60s     7      39s         0   parse.pdf.pdfium
                                                       Σ 18m 04s  17,267  TOTAL
              THE COLUMN IS Σ ran, NOT wall: rungs run concurrently across parts, so this sum
              exceeds the parse Stage's 10m 51s elapsed. Comparing them is the point.

Why it escalated (top causes, from route_decision.cause)
  garble.score=0.71>=0.50                       19 parts   rule=escalate-garble  :41
  decode.cid_ratio=0.83>=0.60                    9 parts   rule=escalate-cid     :52
  geometry.overlap_line_frac=0.34>=0.25          3 parts   rule=escalate-overlap :60

Where the money went
  billed 17,267µ  |  saved by cache 0µ (cold corpus)  |  re-parse into a second store: 0µ
                     (call-layer entries are retained: [cache] gc billed_after_days = 0 = NEVER)
  gpu_ms 74,880~ apportioned by wall_ms across 34 requests to service `vlm` (§5.3, an estimate
                 per document, exact per corpus).  0.2306 µ/ms x 74,880 = 17,267µ  <- checkable
  headroom after this document: 17,267 / 568,000  = 3.0% of the unit's cap
                 = [budget.per_unit] clamp(micros_base 4,000 + micros_per_part 3,000 x 188,
                                           0, micros_max 16,000,000)   (05 §10.1 prints the same)

Degradations (2)
  quarantine       parse.page.olmocr, 3 crashes in 60s; 7 parts fell to DEGRADE at reduced quality
                   raise nothing — fix the driver, or set [drivers] crash_quarantine.crashes
  driver_unavailable  derive.claim.llm not in [drivers] enabled; the `claim` lane produced 0 items

Diags (9)
  OW_TABLE_SYNOPSIS_ONLY   p.61     table has 41,204 cells > TABLE_SYNOPSIS_CELLS=20,000
  OW_NEEDS_OCR             p.12-15  handled: escalated to PAGE and succeeded
  ...  (7 more, `ow doc verify msa-2024.pdf` for the full list)

Slowest 3 attempts   [from the trace; 34 of 188 units sampled at ok=0.015625 — see the note]
  p.61  attempt 1  ran 41.2s  call parse.page.olmocr batch=1/1  gpu_ms=38,900  4M-cell table
  p.12  attempt 2  ran 22.8s  call parse.page.olmocr batch=4/8  REGEN at temperature 0.2
  p.88  attempt 1  ran 19.1s  call parse.page.olmocr batch=8/8  queued 14.0s behind the semaphore
```

Three design points make this report possible rather than aspirational.

First, **`queued_ms` is always separate from `ran_ms`**, everywhere (§6.7), because a contended
lock and slow work are indistinguishable from the outside — and here 69% queued immediately names
`max_inflight` as the constraint instead of blaming the driver. The report is explicit about which
columns are sums over rows and which are elapsed wall, because under concurrency those differ by
more than a rounding error and a report that conflated them would have made a healthy pipeline
look pathological.

Second, **`route_decision.cause` is a generated string** (`cause_from`), so "why it escalated" is
a `GROUP BY cause` and not a log-grep, and every row names the policy file and line
(`route_decision.rule_origin`) that produced it.

Third, **the last block degrades honestly under sampling.** Everything above it is a ledger
query and is exact regardless of `[observe] sample`; "slowest attempts" is the one block that
reads the trace, and at `ok = 0.015625` most units emitted no span at all. The report therefore
prints how many units it actually had spans for, and if that number is zero it prints
`no sampled attempts for this document; re-run with OMNIWEAVE_OBSERVE_SAMPLE_OK=1.0, or read
work.ran_ms with: ow store sql "SELECT unit_part, ran_ms, queued_ms FROM work WHERE unit_uri = …
ORDER BY ran_ms DESC LIMIT 3"` — the same three rows without the `call` detail. A report that
silently showed the slowest of the 1.5% it happened to sample would be worse than one that says
what it has.

`ow top` is the live form of the same data: the claimable set by cost class, in-flight units by
driver, the current `ow_loop_lag_ms` and `ow_store_wal_growth_bytes`, spend against headroom, and
the ten longest-running attempts with their `queued_ms`/`ran_ms` split. It opens the store
`mode=ro` and folds the local event stream at **1 Hz**, opens no listener and starts no daemon.
The 1 Hz figure is a budget, not a measurement: the counts come from
`SELECT cost_class, status, count(*) FROM work GROUP BY 1, 2`, which is a scan of the
`work_claimable` partial index, and at the reference ingest's 846k rows that scan's cost is F8's
open question. The pre-committed fallback is in Open questions.

## 8. Logging

### 8.1 There is one stream, and the level is declared by the kind

omniweave has no logger hierarchy, no `logging.getLogger(__name__)` tree and no per-module level
configuration. Everything a human or a machine reads is an `Event`. The level is **declared in
`tools/events.toml` per `kind`**, not chosen at the call site — so "which events are warnings" is
a static list a reviewer can read, and a refactor cannot silently demote an error.

| level | OTel `severityNumber` | meaning | examples |
|---|---|---|---|
| `debug` | 5 | off unless `[observe] level = "debug"`; may be high-volume | `dep.record`, `store.txn`, `cache.write` |
| `info` | 9 | the normal narrative; sampled per §2.4 | `unit.begin`, `work.claim`, `driver.invoke`, `cache.hit` |
| `notice` | 11 | a state change an operator would want in a diary | `service.spawn`, `store.bulk_lock`, `plan.pause`, `gc.sweep`, `shard.roll` |
| `warn` | 13 | a degradation, a recoverable failure, a refusal | `degrade`, `work.defer`, `unit.failed`, `cache.corrupt`, `store.wal_valve` |
| `error` | 17 | the run's outcome is compromised | `driver.crash`, `driver.quarantine`, `service.refuse`, `run.degraded` |

`[observe] level` sets the floor for both sinks (default `info`) and is applied **at `emit()`**,
before serialisation, so a `debug` floor costs one comparison rather than a discarded JSON
document. It is an **operational** config key — it cannot change the content of any produced row
— and so is every other `[observe]` key.

`DriverIO.log(level, message)` is the only channel a driver has into the stream. It produces a
`driver.log` event, at most `[observe] driver_log_max_chars = 512` per message and at most 64
messages per invocation, past which the rest are counted and dropped and the count rides in the
event's `redacted` field. A driver cannot emit at `error`: the runner owns the run's outcome, and
a driver that believes something is fatal raises `DriverError` with a `FailureClass`. A driver
that exceeds the per-invocation cap is not throttled further — the cap is per invocation, so a
chatty driver pays 64 records per unit and not 64 per run, which is what keeps the cap from
hiding the second half of a long parse.

### 8.2 There is no Python `logging` in the framework, with one exception

`omniweave_core` and `omniweave` do not import `logging`. The exception is a
`logging.Handler` **adapter** installed by `omniweave/run/supervisor.py`, in the `omniweave`
distribution, which captures records from third-party libraries a driver pulls in (a tokenizer,
an HTTP client) and converts them into `driver.log` events attributed to the driver whose
`subproc` worker emitted them — because a library that writes through `logging` in a worker would
otherwise land in the stderr ring tail with no attribution, or nowhere at all.

Four mechanics, because an adapter with unstated timing is a leak:

1. It is installed at **step 2 of the startup sequence** ([system architecture](02-architecture.md)
   §5.3), immediately after config resolution and before anything imports a driver. Records
   emitted by a library at *its own* import time therefore reach it, which is when a tokenizer
   emits its loudest ones.
2. It attaches to the root logger with `logging.raiseExceptions = False` and
   `logging.lastResort = None`, so a library's record cannot print to stderr behind the sink's
   back and a formatting error inside a third-party record cannot raise into our frame.
3. It drops records below `warn`. A library's `INFO` narrative is not our narrative, and the
   alternative is a `debug` floor that makes the reference ingest's stream several times larger
   for content no runbook reads.
4. It applies §8.3's redactor to `record.getMessage()` and **never** to `record.exc_info`, which
   it does not render at all — see the next section.

### 8.3 Redaction — the real hazard, and the five channels that carry it

The framework's whole job is handling documents that must not leak. **Document content in a log
file is the single most likely way omniweave violates its own posture**, because a log is copied
to a ticket, a chat and a vendor's support portal by people whose threat model is "it's just a
log".

The structural defence comes first: `Event.fields` is `Mapping[str, Scalar]` with a per-`kind`
key allowlist, so **there is nowhere in an event to put a paragraph**. That closes the largest
channel by construction. Five channels remain, and each has a rule.

| channel | what it can carry | rule |
|---|---|---|
| `unit` in the envelope, and `unit_uri` in every ledger table | a filename, a folder structure, a client name | `[observe] redact = "paths"` (the default for `trigger ∈ {mcp, hook}`) replaces the path with `u:` + `blake2b(unit_uri ‖ run_salt)[:12]`; the mapping is written to `{output_root}/runs/{run_id}.paths.json`, mode 0600, and is **not** in the event stream. `redact = "none"` is the CLI default, because an operator running `ow ingest` on their own laptop needs to read the filenames. *(Build note, D943: `redact()` mode `"paths"` is built. Rule 1 turns a path under the run's `[roots]` (absolute, backslashed or `file://`, normalised as a `unit_uri`) into `redact.path_token`. Rule 2 turns a whitespace-free run of 24 or more characters into `<redacted:{n}chars>` unless it is a `DriverId` or config key, a code, a cite, a digest (rule 3's) or a token or marker it wrote. A run under `[observe] redact = "paths"` writes its event shard's `unit` as that token and its messages through `redact()`, and writes `{output_root}/runs/{run_id}.paths.json`, created at mode 0600, from a per-run salt written nowhere. Not yet: the manifest's degradation roll-up, whose `units` no shipped `degrade()` fills yet, and `trigger in {mcp, hook}`'s default, which no config layer derives from the trigger.)* |
| a driver's `stderr` ring tail | anything the driver printed, including page text | bounded to 8 samples + a 4-line tail (~4 KiB), **never parsed for a code**, stored in `work.failure_message` and `service_observation.log_tail`, and passed through `redact()` before either. Never in an event. |
| `Diag.message` and its `detail` bag; `DriverError.message`; `Degradation.message` | a snippet, a term, a value from the document | `redact()` runs at the construction boundary. A `Diag` names *where* (`addr`, page, `os_*`) and *what class* (a code), never the text. A message that needs the text is a `quarantine` row instead. |
| **an exception traceback** | **every local variable in every frame** | **no traceback is ever rendered into an `Event`, a ledger column, a console line or an OTLP payload.** See below — this is the channel that gets frameworks. *(Build note, D934: both Driver hosts rendered a driver's unexpected exception as `f"{type(exc).__name__}: {exc}"`, and an exception's args are its frame's data: `int(page_text)` puts the page in the `ValueError`. `omniweave_core.redact.described()` replaces it: the type name and the innermost frame's file name, line and function. The subprocess worker and the in-process guard also pass every `DriverError.message` through `redact()` before it can be a `work.failure_message`. `redact()` lives in `omniweave_core.redact` and not `events.py`, because the worker imports nothing of the sinks. Its six shapes are declared there and `tools/redact.toml` is rendered from them. Only mode `none`, rules 3 and 4, is built, and `paths` is refused by name. `authorization_header` also takes a `Bearer`/`Basic`/`Digest`/`Token` scheme word, which the printed pattern left in front of the token. Not built: the G8 ban on formatting a traceback, and G29's canary, which needs a fault a real `ow add` can be forced into: a worker starts isolated from `PYTHONPATH`, so none can be planted from a test.)* |
| the `quarantine` table | a rejected derive draft, **verbatim, on purpose** | the one deliberate exception, because "never delete what we cannot restore" needs the payload. It lives in the `.owstore`, never in a log, never in an event, never in an export, and `ow graph residue` is the only reader. |

**The traceback channel, which the four-channel version of this section missed.** A
rich-traceback renderer — `loguru` with `diagnose=True`, `rich`, `better_exceptions`, or a crash
reporter's local-variable capture — writes the *locals of every frame* into the log. The mined
collection contains the precise defence, written as a comment because the author had to reason it
out:

```python
# local-deep-research: library/download_management/status_tracker.py:~60
        except DatabaseInitializationError:
            # ``logger.warning`` (no traceback) rather than ``logger.exception``:
            # ``password`` is a live local in this frame, so rendering a traceback
            # under ``diagnose=True`` would dump the plaintext SQLCipher master
            # password (unrecoverable). The redacted failure detail is already
            # logged at the raise site in ``open_user_database``.
            logger.warning(f"[STATUS_TRACKER] Database init failed for user: {username}")
            raise RuntimeError(f"Database initialisation failed for user {username}") from None
```

omniweave's frames hold worse: a `parse/1` driver's frame holds page text, a `DocSink.add_block`
frame holds a block's text, a connector's frame holds an access token, and an `io.service()`
frame holds an `Authorization` value. So the rule is structural, not editorial:

- **`omniweave_core` and `omniweave` never format a traceback.** No `traceback.format_exc()`, no
  `logging.exception`, no `exc_info=True`, no `%r` of an exception whose `args` may hold a
  payload. A semgrep rule in G8's set bans all four in library code, alongside the bare-`except`
  and `time.time()` bans already there.
- **What is recorded instead** is the exception's **type name**, its `codes.toml` symbol, and the
  `FailureClass` — `unit.failed{failure_class, code}` — plus the frame's *source location* from
  `tb.tb_frame.f_code.co_filename` and `tb_lineno`, which are our own file paths and carry no
  data. That is enough to find the bug and carries no locals.
- **`raise … from None` at every boundary that re-raises across a seam**, so a suppressed cause's
  frames cannot be re-rendered by a caller that is less careful than we are. This is the second
  half of the mined pattern and the half that is usually dropped.
- **A `subproc` worker's uncaught traceback** goes to its stderr, which is the ring tail — a
  bounded, redacted, never-parsed channel — and not to the event stream. A crash without a frame
  yields `driver_crashed` synthesised from the exit status plus the last 4 KiB of that ring.
- **`--render json` never carries a traceback either**, so an agent surface cannot ask for one.
  Exit 70 prints the `OW-*` code and the report command (§6.4's rule), and the report command
  collects the three files of §9.2, not a stack.

```python
# omniweave_core/events.py
def redact(s: str, *, mode: Literal["none", "paths"], salt: bytes,
           field: str | None = None) -> tuple[str, int]:
    """Returns (redacted, n_removed). PURE, no clock, no IO, no env. Applied at the
    construction boundary of every message that crosses into an Event, a ledger column
    or a console line. `field` names the column being written, so a declared digest
    column is exempt from the hex-run rule and nothing else is."""
```

`redact()` removes, in this order:

1. any absolute path or `file://` URI under a configured `[roots]` entry, replaced by its `u:`
   digest — mode `"paths"` only;
2. any run of ≥ 24 characters that is not a known identifier shape (a `DriverId`, a
   `codes.toml` code, a declared digest, a `cite`, a config key), replaced by
   `<redacted:{n}chars>` — mode `"paths"` only;
3. anything matching a credential shape in `tools/redact.toml`, **always, at every mode**;
4. `<ow:untrusted>` markers and chat-template sentinels matched by form, **always**, so a
   defanged block cannot un-defang itself through a log line, and so a served block's marker
   count in `OW_UNTRUSTED_DEFANGED` is not itself a re-injection vector.

Rules 3 and 4 are unconditional: `redact = "none"` relaxes the path and long-run rules, which are
about a document's *identity*, and never the credential and marker rules, which are about a
secret and an attack. `n_removed` is carried on the event (`redacted`), so a message that lost
content says so instead of reading as complete.

```toml
# tools/redact.toml — APPEND-ONLY, like codes.toml. The one register redact() reads.
# Patterns are TOML LITERAL strings: a backslash is a backslash and needs no escaping.
[[shape]]
id = "authorization_header"
unconditional = true
pattern = '(?i)\bauthorization\s*[:=]\s*\S+'
replace = "Authorization: <redacted>"
[[shape]]
id = "prefixed_token"
unconditional = true
pattern = '\b(sk|rk|ghp|gho|ghu|ghs|glpat|xoxb|xoxp|AKIA)[-_][A-Za-z0-9_-]{16,}'
replace = "<redacted:token>"
[[shape]]
id = "jwt"
unconditional = true
pattern = '\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'
replace = "<redacted:jwt>"
[[shape]]
id = "hex_run"
unconditional = true
pattern = '\b[0-9a-fA-F]{32,}\b'
replace = "<redacted:hex>"
exempt_fields = ["cache_key", "content_sha256", "config_digest", "semantic_digest", "policy_digest", "pricebook_digest", "lock_digest", "evidence_digest", "read_set_digest", "hints_digest", "card_sha256", "code_fp", "options_digest", "plan_digest", "argv_digest", "catalog_digest", "trace_id", "span_id", "parent_span_id", "member_sha256"]
[[shape]]
id = "untrusted_marker"
unconditional = true
pattern = '</?ow:untrusted[^>]*>'
replace = "<redacted:marker>"
[[shape]]
id = "chat_sentinel"
unconditional = true
pattern = '<\|(im_start|im_end|endoftext|eot_id|start_header_id|end_header_id)\|>'
replace = "<redacted:sentinel>"
```

`exempt_fields` is why `redact()` takes a `field` argument: a `cache_key` is a 64-hex string and
the hex-run rule would eat every one of them, turning the cache diagnostics into
`<redacted:hex>`. The exemption is a closed list of column names, checked by the same generator
that validates `tools/metrics.toml`, so a new digest column that forgets the list fails CI as an
unredactable-looking value rather than shipping as a redacted one.

**How an operator verifies it.** `tests/test_no_content_in_artefacts.py` ingests a fixture
corpus whose every page contains the canary `OWCANARY-7f3a91`, runs a full ingest with a forced
driver crash, a forced budget denial, a forced quarantine and a forced exception inside a driver
frame that holds page text in a local, then greps **every** produced artefact — the NDJSON
shards, the manifest, `{run_id}.paths.json`, `work.failure_message`, `diag`,
`driver_observation`, `service_observation.log_tail`, the console capture, and an
`ow trace export --file` payload — and asserts the canary appears in exactly one place, the
`quarantine` payload, and nowhere else. A second assertion covers the traceback channel
specifically: the forced exception's frame binds `page_text = "…OWCANARY-7f3a91…"` and the test
asserts no artefact contains it *and* that `unit.failed` carries the type name and the code. That
test **is gate `G29`** — the redaction canary — allocated by
[ADR-2](adr/0002-invariant-and-gate-registers.md) decision 4 and registered in
[repo layout](11-repo-layout.md) §6.4: job `gates`, budget 60 s, blocking on every PR. Deleting the
test now fails `G27` clause d2, which resolves the `G<n>` this section names against
`tools/gates.toml`. *(Build note, D936: the test is `packages/omniweave/tests/conform/test_no_content_in_artefacts.py`. It spawns `ow`, so Q-G25 makes it T3, which resolves this section's `tests/` root. It forces two of the four faults, through hostile drivers in `omniweave_conform.canary` that a project card names and a project rule routes to (D935). `BugParser`'s `int(page_text)` carries the page in its exception, and `CrashParser` writes the page to stderr and exits with no frame. No artefact holds the canary: neither console, nothing under `.omniweave/` but the retained source, both home trees, and no text cell of the store. The bug is recorded as `ValueError at canary.py:N in parse` (D934). The crash is recorded by its exit status, and a unit its worker never reached now says so, where its message was empty. Nothing in this build can force the budget denial (`--allow-cost` is unserved, and a billed card defers before a driver holds a page) or the quarantine (no model-free derive writes one). The event shards, `paths.json` and `ow trace export --file` are not produced, and a test fails the day one is.)*

### 8.4 Rotation, permissions and cleanup

`.omniweave/events/` is created mode 0700 and every shard 0600, and `{run_id}.paths.json` is
0600 under `{output_root}/runs/`. `rm -rf .omniweave` remains a supported, documented, lossless
operation — the events directory is derived and deletable, like the `events.owstore` query
sidecar. A shard is never mutated after roll, so a concurrent reader cannot see a torn record and
`ow trace prune` can unlink a rolled shard while `ow trace export --follow` holds the live one.

On Windows an unlink of a shard a reader still holds open fails; `ow trace prune` therefore
records the failure as a `gc.sweep` event with the count it could not remove and retries on the
next sweep, rather than raising. Retention that fails loudly on a platform quirk is retention
someone disables.

## 9. Health, readiness and `ow doctor`

### 9.1 Liveness and readiness

omniweave runs no daemon, so liveness is process liveness and there is nothing to probe. Two
long-lived surfaces need readiness, and both key it on the same startup sequence
([system architecture](02-architecture.md) §5.3) rather than on a second notion of "ready":

- **`ow serve --mcp` (stdio):** readiness is the MCP `initialize` response, returned only after
  startup steps 1–7 complete, so a host that got a successful `initialize` has a server that can
  answer. SV1 is asserted at step 5, before the transport opens.
- **`ow serve --http`:** `GET /healthz` returns `200 {"status":"ok","schema":N,"contract":N}`
  after the same steps, `503` before them, and `503 {"status":"degraded","degradations":[…]}`
  when the one-way `degrade()` latch is set. It requires no API key and **returns no corpus
  names, no paths and no version string beyond the two integers** — a readiness listener that
  enumerates corpora is a reconnaissance surface. A non-loopback bind without `--api-key` is
  refused with `OW_HTTP_BIND_UNAUTHENTICATED` (`OW-A-040`) before the listener opens.

There is no third health endpoint and no metrics listener. `/healthz` is not a third sanctioned
TCP endpoint: it is a path on the second one.

### 9.2 `ow doctor`

`ow doctor` is the only command that rebuilds the catalog and re-probes unconditionally;
everything else reads the frozen one. It has one flag that changes what it checks
(`--runtime`, adding the resource and probe checks), one that changes state
(`--refresh-probes`, deleting `$OMNIWEAVE_HOME/probe/`), and `--render json`. **Posture is not a
flag**: `ow drivers check --posture`'s report is reproduced by `ow doctor` as check D-20 on every
run, and a posture failure fails the doctor run at exit 6 — because
[drivers, operators and the extension system](04-driver-system.md) settled that the posture is
not something anyone has to remember to look at.

Exit codes: `0` ok, warnings included — a doctor never fails on a *warning*; `1` a
config-class failure; `6` a posture refusal; `7` the store is busy and a write verb was
requested; `9` not configured. Every failing row prints the exact command that clears it (§6.4). *(Build note, D953: D-01, D-05, D-11 and D-15 run, in `omniweave.doctor.local`, beside D-02 and D-08. D-01 asks the store's own `refuse_old_sqlite()`, since INV-17 keeps `sqlite3` inside the store. D-05 reports `declared_corpus()`'s `OW-A-002`, a store path that is a directory or sits under a file, and a missing source root. A store not written yet is fine. D-11's fix names the shortfall and the volume, because `ow cache prune` is rostered and not built. D-15 checks the shard directory, or its nearest existing ancestor, for write access and on POSIX for mode 0700. Every path is resolved as a run resolves it.)* *(Build note, D956: D-06, D-13 and D-17 run, in `omniweave.doctor.project`. D-06 compiles the routing policy as a run does and fails a driver it or `[graph.passes] enable` names that is not enabled. A rule declaring `expect_unavailable` makes the absence a warning instead, so the builtin `fields.extract` warns for `parse.fields.lift` and a fresh install passes, as 05:1622-1625 says. `[[pin]]` is no configuration key yet. D-13 parses each corpus's pricebook through `PriceBook.loads` and warns on a future `effective_from`; an absent one is reported. D-17 is `ow skills verify`'s own check, with `ow skills update` as its fix. A configured checkout now passes the nine rows doctor runs.)* *(Build note, D957: D-16 runs `ow hooks check`'s own probe, `install.verbs.hooks_check`, each probe in a scratch project removed after. A run in which every installed hook resolved and ran passes. No hook recorded passes too, though `ow hooks check` exits 1 for it: a doctor asks whether what is installed works. Anything else is `OW-A-030` with `ow hooks check` as its fix. Doctor runs ten rows.)*

| id | check | severity | code / fix |
|---|---|---|---|
| D-01 | `sqlite3.sqlite_version_info >= MIN_SQLITE = (3,42,0)` | fail | `pip install omniweave-core[sqlite]` |
| D-02 | no `.owstore` is tracked in git; the shipped `.gitignore` covers it | fail | `OW-S-060`; `git rm --cached` |
| D-03 | `omniweave.index.lock` has no conflict markers | fail | `OW-S-061`; `ow store verify --lock` |
| D-04 | `index_state.bulk_window` is closed | fail | `OW-S-031`; `ow store repair` |
| D-05 | every `[corpora]` path resolves; `[serve] default_corpus` names an entry | fail | `OW-A-002` |
| D-06 | every driver named in `policy.d`, `[graph.passes] enable`, or a `[[pin]]` is in `[drivers] enabled` | fail | INV-5; add it to `enabled` |
| D-07 | every `[targets] enabled` entry has an installed target distribution | fail | `ow targets install` |
| D-08 | every enabled driver's card validates; `attested = true` unless `allow_unattested` | fail | `ow drivers verify` *(Build note, D954: D-08 also asks the two trust gates `resolve()` applies after attestation, for the cards it routes, the `parse` cards. Under `require_lock`, a tier outside `LOCK_SATISFIED` fails as `NOT_IN_LOCKFILE`. An id in `[drivers] inproc` outside `INPROC_TRUST` fails as `TRUST_INSUFFICIENT`. Each prints its `[drivers]` fix. A source checkout carries no release manifest, so every first-party card computes as `unpinned`, and `ow add` there routed nothing while D-08 passed. Following the two fixes, a fresh project parsed txt, pdf, docx and pptx. The attestation finding no longer says `resolve()` refuses a derive pass it never routes.)* |
| D-09 | `probe()` for every enabled driver returns a status meeting its declared capability floor | warn | `ow drivers explain <id>` |
| D-10 | `Σ_class (max_workers × card.limits.memory_mb) <= 0.8 × physical RAM` | fail (`--runtime`) | lower `[drivers] max_workers` *(Build note, D958: runs under `--runtime` only, in `omniweave.doctor.local.check_ram`, with the Supervisor's own `derive_admission`, `ram_required` and `check_ram`, so the doctor sums the CPU-clamped workers a run would start (08:729's laptop: 3 free, not 4). `memory_mb` is `[isolation] memory_mb` (08:707), each cost class's heaviest enabled card; a card with no `[cost.model]` is `free`. A plain `ow doctor` prints that D-10 runs only with `--runtime`. RAM the platform will not report is a warning, `check_ram`'s `unknown`. `_ram_bytes` now reads Windows through `GlobalMemoryStatusEx` (it returned 0 there) and takes a cgroup v2 `memory.max` or v1 `memory.limit_in_bytes` below physical RAM, without which 08:731's 4 GB container read the host's RAM and passed.)* |
| D-11 | free space on `cache_root` ≥ `[cache] min_free_bytes = 5 GiB`; on `output` ≥ 1 GiB | warn | `ow cache prune` |
| D-12 | `route_threshold` holds all three rows (`audit.min_audit_n`, `.regress_at`, `.release_at`) | fail | reinstall the policy; a missing row makes `route_scoreboard.state` fall through to `OK` |
| D-13 | `.omniweave/pricebook.toml` parses, `effective_from <= today`, currency set | warn | absent pricebook ⇒ `billed_api` cannot be admitted |
| D-14 | the `events.owstore` query sidecar is writable, or its fallback is | warn | prints "the query ledger is OFF"; telemetry never fails a query |
| D-15 | `[observe] ndjson_path`'s directory is writable, mode 0700 | warn | the stream degrades to `console` only |
| D-16 | installed hooks resolve **and execute** against a probe payload | warn | `OW-A-030`; `ow hooks check` |
| D-17 | installed skill bundles match their recorded hashes | warn | `OW-A-031`; `ow skills update` |
| D-18 | Toolchain digests present for every enabled target; `node_range` satisfied | warn | `ow targets install` |
| D-19 | `omniweave-vision`'s resolved installed size, printed | info | the one distribution exempt from G2 *(Build note, D965, a user ruling of 2026-10-23: `omniweave.doctor.local.check_vision_size`, under `--runtime` only. It reads `omniweave-vision`'s own `RECORD` and follows its requirements to the installed closure, by name, each path once (G2's union), skipping an extra's; 11 section 2.3's ban is on walking every distribution. An unconditional requirement that is not installed is named; a marked one is not, since markers go unevaluated without `packaging`. An editable install says its `RECORD` lists links. Measured here: 609.0 MB across 37 distributions with `torch`. It reads no configuration, so it runs when that fails to load.)* |
| D-20 | posture: `ow drivers check --posture`'s verdict — no egress without a `Grant` with a `dpa_ref`; licence tiers vs `allow_tiers`; `isolation_floor` achievable on this OS | fail (exit 6) | names the grant or the tier |
| D-21 | no migration with `backfill_done < backfill_total`; if any, print `unbackfilled_means` **verbatim** | warn | `ow store migrate --resume` |
| D-22 | store clock vs host monotonic skew < 5 s (leases use `unixepoch('subsec')`, the **store's** clock) | warn | a large skew reaps live leases |
| D-23 | no abandoned `staged_gen` rows outside the current run | warn | `--allow-abandoned-gen` *(Build note, D969: `omniweave.doctor.store.check_abandoned`. The build stages as pages above `doc.gen`, not `staged_gen`, so it reads `store.doc.ABANDONED_SQL` from each corpus store opened read-only. Abandoned pages warn, with `ow add <uri>` as the fix, since a re-parse sweeps them. A quarantined generation (its `OW_REBIND_UNEXPLAINED` diag) is reported as kept for `ow doc diff`, and a store under a live `store.write` lock as a parse that may be in flight; neither warns.)* |
| D-24 | a live `store.write` lock: prints holder host, pid, `process_create_time`, age | info | exit 7 if a write verb was requested *(Build note, D959: in `omniweave.doctor.store`, once per declared corpus, over the lock file beside its store (`locks.store_write_lock`'s path, D560), asked through `locks.inspect()`, which takes nothing and breaks nothing. Every finding is `ok`, as an info row is never a warning; it prints no lock, a lock held by host, pid, `process_create_time` (and what read it) and age, or a stale lock whose process is gone, which the next writer breaks. A payload that does not parse, which `_read_holder` reads as pid 0, is named as unreadable. The age is read against `SystemClock`, once per run. `ow doctor` is no write verb, so exit 7 is not this row's.)* |
| D-25 | the canary grep of §8.3 over the **newest** event shard, plus `{run_id}.paths.json` mode | fail | delete the shards; file a bug *(Build note, D961: `omniweave.doctor.local.check_canary`, on every `ow doctor`. The newest shard is the newest `.ndjson` or rolled `.ndjson.gz` in the events directory `shard_of` names, by mtime, a rolled one read through `gzip`; `OWCANARY-7f3a91` in it fails with this row's fix. The canary moved to `omniweave_core.redact.CANARY`, which `omniweave_conform.canary` re-exports, because `omniweave` may not import conform. That run's `{output}/runs/{run_id}.paths.json`, when present, must be mode 0600 on POSIX (15:1330), with `chmod 600` as the fix. No shard is ok, and a shard that does not decompress warns.)* |
| D-26 | `[observe] otlp_endpoint`, if set, is printed with its config source and the count of runs that had it set | info | an endpoint cannot be configured invisibly (§12) *(Build note, D963, a user ruling of 2026-10-23: `omniweave.doctor.local.check_otlp` prints set or unset, the key's config source, and how many recorded runs had it set, and never the URL, which `ow trace export` never prints either (D948). Each run manifest gains `otlp_endpoint_set`, its twenty-second member, from the run's configuration; the count reads `{output}/runs/*.json` and leaves out a manifest written before the member existed, so it claims no history that was not recorded. An info row: every finding is `ok`.)* |
| D-27 | the `omniweave-golden` corpus's state, printed and never failing the run | info | `ow eval fetch omniweave-golden@<version>` |

**`D-27` prints one of two values and the second retires the first.** Until the published artefact
is repackaged it prints `golden: unavailable (no zstd decoder)` — the interim
[ADR-10](adr/0010-data-artefacts-and-weight-ceiling.md) pre-commits, because a `.tar.zst` corpus is
unreadable from a stdlib-only install and reporting that in the doctor beats failing at first use.
Once the artefact ships as a plain ZIP ([repo layout](11-repo-layout.md) §3.2) it prints
`golden: not installed — ow eval fetch omniweave-golden@<version>`, and the first branch is dead
code deleted with the last `.tar.zst` artefact. `D-27` is `info` in both: the corpus is read only by
`omniweave-conform`'s eval harness, so its absence is never a runtime fault.

**What `ow doctor` costs, because a doctor nobody runs is a doctor that does not exist.** The
budget is **≤ 10 s warm** and the two checks that can breach it are named: D-09 re-probes every
enabled driver at `[drivers] probe_timeout_ms = 2000` each, which is 22 s worst case on the
shipped eleven-driver `enabled` list if every probe times out, so probes run **concurrently**
bounded by `max_workers.free` and the aggregate is capped at 8 s with any unfinished probe
reported as `unknown` rather than waited for (`unknown` is the state, never a skipped row); and
D-25 scans one 64 MiB shard, which §3.3 derives at ~0.5 s. `ow doctor --deep` scans every
retained shard and re-probes serially with no aggregate cap, and is the form a support request
asks for.

`ow store doctor` and `ow graph doctor` are narrower, subsystem-specific, and enumerate their own
checks in [storage, indexing and retrieval](07-store-and-retrieval.md) and
[structure extraction](06-structure-extraction.md). `ow doctor` does **not** re-run them; it
names them when a subsystem check fails, because a doctor that takes four minutes is a doctor
nobody runs.

Every check emits a `doctor.check` event, so a support bundle is `ow doctor --render json` plus
the last shard plus the manifest — three files, no screenshots, no traceback (§8.3).

## 10. Deployment topologies

Five, and no sixth is supported at v1. The process topology is
[system architecture](02-architecture.md) §5; this section is the operational configuration,
the resources, and the caveat that bites.

### 10.1 Laptop — the shipped defaults, which is the whole configuration

The laptop topology is the one that must work with **no configuration file at all**, so this
block is not a configuration to write: it is the relevant slice of the shipped defaults, quoted
from `omniweave.toml.example`, printed here so a reader can see what zero configuration means.

```toml
[drivers]
max_workers = { free = 4, local_compute = 4, billed_api = 8 }
isolation_floor = "subproc"
inproc = ["parse.office.anydoc"]
[drivers.cost]
allow_classes = ["free", "local_compute"]
auto_refresh_classes = ["free"]
[budget]
max_inflight = { free = 32, local_compute = 4, billed_api = 2 }
[retrieval]
vectors = "off"
[observe]
sinks = ["console", "ndjson"]
level = "info"
redact = "none"
retain_days = 14
timings = "always"
```

Resources: 8 GB RAM, 4 cores, no GPU. `ow query` warm ≤ 250 ms; `ow hook prompt` ≤ 250 ms p95
warm, 1 s cold (G26). Corpus ceiling ~10^5 parts before an ingest stops being interactive.
Events at `retain_days = 14`: ~9 MB per full reference-scale ingest (§3.3), far less per
interactive run.

**Caveat, and it will surprise people.** With `allow_classes` excluding `billed_api` and
`omniweave-vision` not installed, a scanned PDF produces `OW_NEEDS_OCR` diags and every query
over those pages reports `parse_gap_in_scope` — degraded, never a confident zero. That is the
correct behaviour, and `ow corpora --detail coverage` prints it before the first query rather
than after the first wrong answer. The second caveat is `vectors = "off"`: four channels, and
`semantic: off` in every verdict, which is the charter's deliberately-not-deferred default.

### 10.2 Single server (a team's shared ingest host, CPU only)

```toml
[drivers]
max_workers = { free = 8, local_compute = 8, billed_api = 16 }
isolation_floor = "subproc"
[budget]
max_inflight = { free = 64, local_compute = 8, billed_api = 4 }
[runtime]
queue_high_water = 200000
queue_low_water = 100000
batch_wait_lock_ms = 300000
[store]
wal_valve_mb = 0
bulk_windows = true
[observe]
level = "notice"
sample = { non_ok = 1.0, ok = 0.001 }
retain_days = 30
```

`wal_valve_mb = 0` means `clamp(db_bytes/4, 256 MB, 2 GB)`; `sample.ok = 0.001` is 1 in 1,000,
chosen so a 10× larger corpus produces the same shard count as §10.1 rather than ten times as
many, and the span-buffer bound moves to 76 × 64 × 180 B = 855 KiB (§2.4).

Resources: 32–64 GB RAM, 16 cores, NVMe. `Σ max_workers × memory_mb` must clear D-10's 0.8×RAM
refusal. Corpus ceiling ~10^7 parts (the honest ceiling); beyond it the answer is a Postgres T3
behind the same 33-method port surface, not a bigger box.

**Caveat.** One `.owstore` has one writer, and a second `ow ingest` gets exit 7 naming the
holder's host, pid and lock age. Schedule ingests; do not run two. At `retain_days = 30` and this
volume the events directory is the one thing on the host that grows without an operator noticing,
so the cron that runs `ow trace prune` is part of the topology, not an afterthought.

### 10.3 GPU server (the VLM escalation path)

```toml
[drivers]
enabled = ["parse.office.anydoc", "parse.pdf.pdfium", "parse.page.olmocr", "derive.segment.spine"]
max_workers = { free = 8, local_compute = 4, billed_api = 8 }
[drivers.cost]
allow_classes = ["free", "local_compute", "billed_api"]
[services.vlm]
model_id = "allenai/olmOCR-7B"
model_revision = "9f8e7d6c5b4a3928"
endpoint = "http://127.0.0.1:8000"
autostart = false
capacity = 0
batch_wait_ms = 5
max_batch = 8
keep_alive_s = 0
```

`endpoint` set plus `autostart = false` means **attach, never spawn**: the engine is pre-warmed
outside the run. `capacity = 0` derives from `min(server-reported, MAX_AUTO_PARALLEL = 96,
ledger headroom)`; a flat 96 on a 24 GB card is an OOM, not a throughput gain (surya's
`MAX_AUTO_PARALLEL = 96` is the cap past a B200's knee, with `_max_num_seqs = 8` as its actual
default, and the charter records the flat-96 claim as checked and wrong).

Resources: one 24–80 GB accelerator, 64 GB host RAM, 16 cores. A resident 7B engine holds
20–40 GB of VRAM (F37); the CPU render semaphore is `cpu_count - 2` and a 192-DPI A4 page is
10.7 MB decoded, so rendering must **follow** routing — 5,000 rendered pages is ~53 GB.

**Caveats, two.** `keep_alive_s = 0` costs a cold start per run, recorded as
`service_observation.cold_start_ms`, and is still right on a shared box because otherwise the
next interactive command finds no VRAM (F37's pre-committed fallback drops it to 0 for
`trigger ∈ {cli, hook}` anyway). And every GPU-hour plan on this host carries F7's uncertainty:
the Coalescing speedup is an unmeasured 1.5×–4× band, so watch `ow_service_queue_ms` and
`ow_service_peak_inflight` and treat capacity plans as wrong by up to 2.7× until
`ow bench service` runs. Per-document `gpu_ms` on this topology is always apportioned and always
prints with a tilde (§5.3).

### 10.4 CI

```toml
[drivers]
enabled = ["parse.office.anydoc", "parse.pdf.pdfium", "derive.segment.spine"]
isolation_floor = "subproc"
[drivers.cost]
allow_classes = ["free"]
[observe]
sinks = ["ndjson"]
level = "warn"
sample = { non_ok = 1.0, ok = 1.0 }
retain_days = 1
[retrieval]
event_log = false
```

Resources: 2 cores, 7 GB, no GPU, no network. `--cassette required`; a cassette miss is
`OW-Q-004` and **never** a live call. The `parity` job runs offline, GPU-free and Node-free in a
container.

**Caveat, and it is the arithmetic of §3.3.** `ok = 1.0` samples nothing out, because a flake
needs the whole trace — and that is exactly the configuration in which the reference ingest emits
1.22 GB across 19 shards. `retain_days = 1` bounds it, and CI uploads **only the shards for a
failing run**, selected by `run_id`, never the directory. A job that archives
`.omniweave/events/` wholesale is a job whose artefact store fills up in a week.

`sinks = ["ndjson"]` and not `console`: §3.4 puts the console sink on stderr, so it would not
corrupt a JSON artefact, but it would still bury a CI log under one line per event at 439k
events. The Pacer runs immediately before and after every timed measurement and every budget is
a ratio to it; a > 15% disagreement between the two readings yields `unstable`, not a failure,
because a shared runner's CPU is not a measurement instrument
([performance](12-performance.md) owns the methodology).

### 10.5 A shared team service (`ow serve`, read-mostly)

```toml
[serve]
profile = "default"
enabled = "read_only"
[observe]
redact = "paths"
level = "notice"
ndjson_path = "$OMNIWEAVE_HOME/events/{run_id}.ndjson"
retain_days = 7
[retrieval]
event_log = true
event_log_query = false
snapshot_ms = 2000
```

Run it as N stateless `ow serve --http --api-key …` processes behind whatever the site already
has, on a host that mounts the `.owstore` **read-only**; a separate single-writer host runs
ingest. Readers use the `connect_readonly` ladder (`mode=ro` when a `-wal` sidecar exists,
`mode=ro&immutable=1` when it does not) — a plain read-write open creates the WAL sidecars and
moves the very mtime the freshness check reads (I10), so a read-only mount is a correctness
mechanism and not a hardening measure.

Three things this topology forces on the observability substrate, all of them stated here
because a read-only mount breaks the defaults:

1. **`ndjson_path` moves off the corpus.** `.omniweave/events/` is inside the read-only mount, so
   the default path is unwritable and D-15 would warn on every process. It points at
   `$OMNIWEAVE_HOME/events/`, which is per-host and writable. Each of the N processes has its own
   `run_id`, so the shards do not collide; `writer_id` (§3.2) disambiguates the rare case of one
   `run_id` spanning a parent and a detached child.
2. **The query ledger falls back the same way.** When `cache_root` is read-only,
   `retrieval_event` goes to `$OMNIWEAVE_HOME/events/<corpus_id>.owstore`; if that fails too the
   ledger is **off**, `ow doctor` D-14 says so, and F52's input does not exist. Telemetry never
   fails a query.
3. **Nothing here ever enters the `maintain` Stage**, so nothing sweeps the events directory. The
   topology's cron runs `ow trace prune --older-than 7d` on each serve host. `retain_days = 7`
   rather than 14 because N processes × many short runs produces many small shards, and a serve
   host's diagnostic window is a day, not a fortnight.

**Caveats, three.** (1) Tenancy is **store-per-tenant** (F27); row-level tenancy is not designed
and no plan document may assume it. (2) A shared service has no session identity from some
hosts, and the cite-qualification rule then keys on `[corpora]` having more than one entry — so a
multi-corpus deployment pays ~10 characters per cite always, which is correct. (3) Two hosts
cannot share one `.owstore` for writing; the scoped lock's `host` component makes that a refusal
rather than corruption. There is no distributed mode at v1.

## 11. Failure runbooks

Five, chosen because each is evidenced by a measured failure in the mined collection or by a
mechanism whose breach is silent. Each names the detection query, the immediate action, the root
cause, the fix, and the guard that should have caught it earlier.

### R1 — The store is busy, or the WAL is growing without bound

**Symptom.** `ow query` slow or exit 7 `store busy`; `.owstore-wal` in the gigabytes; in the
worst case the process is killed (codegraph's recorded outcome was 22 GB of WAL and exit 137).

**Detect.** `ow doctor` D-04/D-24, then:

```text
$ ow store stats --wal
wal_bytes            3,412,918,272
baseline             1,073,741,824   size_at_last_full_backfill, refreshed 00:12:41
growth               2,339,176,448   <- THE ALERTING NUMBER (ow_store_wal_growth_bytes)
valve_mb             2048            clamped from db_bytes/4
armed                1               since 00:41:12
oldest reader        pid 41102 host box01 age 1,842s  snapshot_gen 41
```

Read `growth`, not `wal_bytes`. §4.4 is the argument: raw size recycles inside the same file after
a backfill, so a size threshold latches on and never clears — the mined measurement is a crawler
degraded to ~9 minutes per 160 files with the writer permanently parked by its own valve.

**Immediate.** Find the long reader: a held read transaction **pins the WAL**, and that is the
futility-latch condition. Kill it, or wait for `snapshot_ms` to abort it with `OW-S-010` and
`verdict=degraded`. Do not `VACUUM` while the writer runs.

**Root cause.** One of three: a query exceeding `[retrieval] snapshot_ms = 2000` (the reader's
deadline is a **WAL-valve safety parameter**, not a UX parameter); a single-page transaction so
large it cannot checkpoint (F29's 4M-cell document, visible as `ow_loop_lag_ms` over 250); or
`bulk_windows` left open by a killed process.

**Fix.** `ow store repair` closes a bulk window and repopulates dropped indexes; the store
**refuses to serve** with an open marker rather than serving a partially-indexed corpus. The WAL
itself is truncated by heal-on-open above `[store] wal_heal_mb = 64` — so closing every reader
and reopening is the checkpoint, and there is no separate verb for it — with `ow store vacuum`
reclaiming the file after the writer exits. For F29, `MAX_BLOCKS_PER_DOC` and a
`RESOURCE_LIMIT` refusal naming the knob is the shipped answer; a sub-page commit boundary is
not granted speculatively.

**Guard.** `ow_store_wal_growth_bytes` and `ow_loop_lag_ms` on the dashboard (§4.4);
`store.wal_valve` events carry `armed` and `size_at_last_full_backfill`; G22's nightly asserts
supervisor RSS ≤ 600 MB at ≥ 2,000 transitions/s.

### R2 — Spend exhausted mid-corpus: everything looks fine and nothing finishes

**Symptom.** `ow_work_claimable` steady, `ow_unit_settled_total` near zero, no failures. Work
rows are `deferred`, which is an `Outcome`, not a failure — so nothing is red.

**Detect.**

```text
$ ow queue status --corpus contracts
pending 41,208   claimed 2   deferred 88,104   failed_transient 0   failed_permanent 12
deferred by dim (first exhausted wins):
  micros        88,104  scope=unit   clamp(4,000 + 3,000 x part_count, 0, 16,000,000) exhausted
  calls              0  gpu_ms 0     bytes_egress 0
$ ow cost --corpus contracts --by day --since 3d
```

**Immediate.** Decide, do not raise blindly. `ow route simulate` replays `evaluate()` over stored
evidence with a different `PriceBook` or policy and reports the counterfactual bill at zero cost
— `evaluate()` is pure, so the entire history re-prices for free.

**Root cause.** A per-dimension budget's **first exhausted dimension wins**, and the deferral
re-entered the decision as the evidence key `budget.exhausted` (INV-14). Almost always the
estimate is wrong rather than the limit: the p95 of `tokens_out` for a page VLM is F6's open
question and the published anchors are **3.4× apart**.

**Fix.** Raise the named key the `Degradation.message` quotes — and the message names the key
that actually bound, which is almost always `micros_per_part` and not `micros_max`, because under
the shipped `micros_base = 4,000`, `micros_per_part = 3,000`, `micros_max = 16,000,000` the clamp
does not bind until `(16,000,000 - 4,000) / 3,000` = **5,332 parts** — above the largest document
the framework prices, so `micros_max` is a runaway guard and the per-part term is what denies a
routine unit. Both live in
`.omniweave/policy.d/`, the one home for a currency cap. Or set `on_exhausted = ["defer"]`
deliberately and drain later. `--allow-cost <micros>` authorises one invocation. There is no
blanket override in this framework and none will be added (§6.4).

**Guard.** §4.4's metric 3 (spend against held headroom **and** the deny rate);
`ow route lint --estimates`, which refuses a policy whose estimates are inconsistent with
observed `route_spend`.

### R3 — A driver quarantines and a whole format silently degrades

**Symptom.** A format's documents complete with `ok_partial`, or fall to a `DEGRADE` rung, at
lower quality. Three crashes in 60 s quarantine the **driver for the run** — not the unit — after
which `resolve()` returns `RejectCode.QUARANTINED` and the router re-plans.

**Detect.**

```text
$ ow drivers explain parse.page.olmocr --run r_2026_09_03_0141
quarantined at 00:41:52 after 3 crashes in 60s (window from [drivers] crash_quarantine)
crash 1  unit=u:9f8e21… p.61   exit=-9 (SIGKILL)  stderr_tail=4096B  peak_rss=6.1GB > memory_mb=4096
crash 2  unit=u:1a4c07… p.12   exit=-9            peak_rss=5.8GB
crash 3  unit=u:1a4c07… p.12   exit=-9            batch retried at batch=1 to localise the poison unit
consequence: 7 parts routed to DEGRADE (parse.pdf.pdfium), Degradation(kind="quarantine")
```

The `unit=u:…` form is §8.3's path redaction; `{run_id}.paths.json` resolves it for whoever holds
the host, and a support bundle that omits that file is a bundle with no filenames in it, on
purpose.

**Immediate.** Nothing, if the degradation is acceptable — it is recorded on the result, in the
manifest and in the serve envelope (I18). Re-run the affected units after the fix; the `call`
cache means a successful page is not re-billed.

**Root cause.** Read `peak_rss_bytes` first. Here the driver exceeded its own card's
`memory_mb`, so AIMD halved the batch — and recovers after 20 consecutive clean batches, because
halve-and-never-recover lets one foreign process permanently cap a driver's throughput.

**Fix.** Lower the card's declared batch, raise `memory_mb` if the host allows, or refuse the
document with `RESOURCE_LIMIT` naming the knob. A crash *without* a frame yields
`driver_crashed` synthesised from the exit status plus the last 4 KiB of the stderr ring — and
never a rendered traceback, because that worker's frames held page text (§8.3).

**Guard.** `ow_driver_crash_total` and `ow_driver_quarantine_total` by driver;
`ow_unit_peak_rss_bytes` against the card's `memory_mb`; D-10's 0.8×RAM refusal.

### R4 — A silent re-bill, or its mirror image: silently stale billed output

**Symptom (re-bill).** `ow_spend_micros_total` jumps on a corpus that has not changed.
**Symptom (stale).** A driver's spend falls to zero after a release, and the output is unchanged
because a stale cache is being served. The second is worse, and §6.6 names it the most expensive
single mistake available in the design: forgetting to bump a driver's `schema_version` serves
stale billed output forever with no symptom.

**Detect.**

```text
$ ow cache stat --corpus contracts
growth bound: live units x configurations seen        # THESE WORDS, verbatim
layer   rows       bytes    hits    miss  corrupt  partial  legacy   saved_micros  cost_class
call    116,412  41.2 GB   8,904   1,204        2       11       0     94,102,000  billed_api
signal  1,884,220  1.9 GB 84,102  12,004        0        0       0              0  free
$ ow cost --by driver --since 14d      # a driver whose micros fell to 0 across a release
$ ow show-config --digest              # config_digest and semantic_digest, with sources
```

The five miss shapes in that table are the cache's own read policy, counted rather than inferred:
`corrupt`, `partial`, empty, a `(unit, part)` mismatch, and an older namespace served as
`HIT_LEGACY`.

**Immediate (re-bill).** Diff `semantic_digest` across the two runs (`run` table). Only the
semantic projection enters a cache key; if an *operational* key moved the key, that is a G18 bug
— and `drivers.enabled` is the canonical example of a key that must stay operational, because
classifying it semantic would re-bill an entire corpus every time an operator enabled an
unrelated driver.

**Immediate (stale).** `ow replay --verify` over the fixture corpus; the conformance kit's check
that diffs output across two tagged driver versions.

**Root cause.** An unclassified config key (treated at runtime as `semantic` — fail expensive,
never wrong), a `digest_recipe` or `recipe` bump (which **namespaces** and never deletes), or a
missing `schema_version` bump. `driver_schema_v` is the only driver version in a cache key.

**Fix.** Bump `schema_version` and let the namespace change; never hand-delete a `billed_api`
cache row. An automatic sweep **never** deletes one (`cache_ns` is a partial index on
`cost_class='free'`); deletion requires `ow cache prune --allow-rebill`, which prints the count
and the `would_have_been_micros` it is about to discard.

**Guard.** G18 (config axes, unclassified fails CI), I26 (mutate every operational key, assert a
byte-identical `cache_key`), I27 (no automatic billed deletion), and
`ow_cache_saved_micros_total` falling off a cliff — which is the only one of the four that fires
without someone looking, which is why it is on the dashboard's periphery even though it is not
one of the five.

### R5 — Every query says `degraded` and nobody knows why

**Symptom.** `ow_query_total{verdict_state="degraded"}` at or near 100%. Answers still arrive,
which is why this can run for weeks.

**Detect.**

```text
$ ow store sql "SELECT gates, count(*) FROM retrieval_event
                WHERE verdict_state <> 'ok' AND ts_ns > :since GROUP BY gates ORDER BY 2 DESC"
["channel_unavailable"]      4,102
["parse_gap_in_scope"]         311
["coverage_incomplete"]         44
```

That is the one query an operator actually runs, and `retrieval_event_bad` is a **partial** index
on `verdict_state <> 'ok'` — about 2% of the full index on a healthy store — specifically so it
is cheap.

**Immediate.** `ow query "<a known query>" --explain` and read the channel table. The two
outcomes that look alike and are not: a channel over **its own** `budget_ms` returns
`UNAVAILABLE(timeout)` and forces `degraded`; a channel pre-empted by the **query** deadline
reports a partial ranking with `truncated_at_limit = True` and status `OK`, and the remaining
channels report `OFF(query_deadline)`. Only the first is a fault, and absence gate 1 reads only
the first.

**Root cause.** Four candidates, each of which the explain output names, and the mechanics of all
four belong to [storage, indexing and retrieval](07-store-and-retrieval.md):
`lexical: UNAVAILABLE(fts_stale)` after a killed bulk window, fixed by `ow store repair`; a
vector sidecar whose `vec_manifest.model_key` disagrees with the config, which is gate 13
`space_mismatch` and means the sidecar is **ignored, not read**; `stat` stale past
`STAT_MAX_AGE_NS`, which takes the maximum over-fetch clamp of 64 and records
`Degradation(kind="stat_stale")`; and a channel budget set above `query_ms`, which
`ow route lint` refuses because the five shipped budgets sum to 210 ms against
`[retrieval.budget] query_ms = 250` and a set that sums above it guarantees a G10 breach and
turns the honesty machinery into permanent noise.

**Fix.** Whichever of the four the explain output names, each of which prints its own command.

**Guard.** §4.4's metric 4; G10's `ow query` warm ≤ 250 ms budget; `ow route lint` in CI.

## 12. Telemetry policy

**omniweave sends nothing, to nobody, ever, unless an operator configures an endpoint they own.**
There is no default endpoint, no `anon_id`, no first-run prompt and no phone-home compiled into
any distribution.

The precedent this policy is written against is concrete. jcodemunch ships **default-on**
telemetry from `storage/token_tracker.py:75` to
`https://j.gravelle.us/APIs/savings/post.php`, sending `{"delta": N, "total": M, "anon_id":
"<uuid>"}`, plus a phone-home licence gate from `org/license.py:42` to
`https://j.gravelle.us/jCodeMunch/validate.php` — nine outbound hosts across the package. The
*engineering* is admirable and worth copying: a minimal payload documented field-by-field in the
module docstring, an opt-out env var, an endpoint override, a lazily-started daemon thread so a
plain `import` has no side effect, and `GREATEST(stored, total)` so a dropped POST self-heals.
The **default** is still disqualifying for an enterprise product: default-on egress to a third
party is a procurement blocker, and a stable `anon_id` plus a monotone counter fingerprints an
installation over time. omniweave copies the transparency and inverts the default. codegraph
reaches the same conclusion from the other side — its own "must not copy" list names
telemetry-by-default as the thing that would kill a local-first claim.

| what | collected where | leaves the machine? |
|---|---|---|
| event stream, run manifest, ledger tables | `.omniweave/` and the store, local files | **no** |
| the query ledger (`retrieval_event`) | `events.owstore`, per-user, derived, deletable | **no** |
| the raw query text | only when `[retrieval] event_log_query = true`; `query_hash` otherwise | **no** |
| the `{run_id}.paths.json` redaction map | `{output_root}/runs/`, mode 0600 | **no** |
| a document's bytes, text, or any `cite` | never in any observability artefact except the `quarantine` payload | **no** |
| a driver's model calls | to the provider the operator configured, priced through `PriceBook`, requiring a `Grant` with a `dpa_ref` | **yes, and only this** |
| OTLP spans | `ow trace export --otlp <endpoint>`, an operator-supplied endpoint, run offline | **only when invoked** |

**Never collected, at any level, in any mode:** document content; a filename outside `redact`'s
digest when `redact = "paths"`; a hostname, username, machine id or MAC; an absolute path in an
OTLP resource attribute; a query string in a metric label; an exception traceback or any frame's
locals; a licence key; an installation id; a usage counter aggregated to a vendor.

**How an operator verifies it — five mechanisms, none of them a promise.**

1. **G15 proves no egress is compiled in**: a hostname-literal grep of every distribution against
   an allowlist, plus a conformance run with sockets blocked. The precedent it exists for is
   marker's `--use_llm` shipping page images to Gemini by default.
2. `bytes_egress` defaults to **0**. The first hosted escalation is a deliberate act requiring a
   site-layer `Grant` with a `dpa_ref` printed in the run manifest of every document that
   egressed. `ow cost --by provider` and `ow_egress_bytes_total{grant_id}` show every byte.
3. `ow trace export --dry-run --print-payload` prints the exact OTLP JSON that *would* be sent,
   to stdout, and sends nothing. Diff it before pointing it anywhere. Because §2.6's exporter is
   `urllib.request` and not an SDK, the payload it prints is the payload byte for byte — there is
   no batching processor, resource detector or instrumentation library between the print and the
   socket that could add a field the print did not show.
4. `[observe] otlp_endpoint` is a config key, so it is in `config_digest`, printed with its
   source by `ow show-config`, visible in the `run` row of every run that had it set, and
   reported by `ow doctor` D-26 with the count of such runs. An endpoint cannot be configured
   invisibly, and it cannot be configured *historically* without a record.
5. The `parity` CI job runs the full suite in a container with **no network**, so a dependency
   that grew a phone-home fails the build rather than a review. §8.3's canary test runs in the
   same job — `parity` runs the whole suite — which is what covers the other direction: not "did
   we send it" but "did we ever write it down". Its *gate* registration is separate and is
   `G29` in the `gates` job at a 60 s budget ([repo layout](11-repo-layout.md) §6.4), so deleting
   the test fails a named gate and not only a suite count.

## Extends the charter

Marked because these are decisions this document made where the charter is silent, all inside
D6's shape.

1. **Stage** (`ow.stage`) as the pipeline-phase span attribute, with a closed nine-member
   vocabulary. The charter closes the span hierarchy at five levels and never names the pipeline
   phase on a span; `Event.phase` and `derive_pass.phase` were both already taken.
2. **`manifest.stage_ms` and `manifest.stage_entries`** as the manifest's per-Stage timing map.
   The charter and [system architecture](02-architecture.md) both say the manifest carries
   "per-phase timings" without naming the field, and `timings_ms` was unavailable: it is
   `doc.timings_ms`, a per-document driver-reported column. Two objects, two names.
3. **The read and compile paths use three of the five span levels** (`run > plan > call` for a
   query, the full five for a compile) rather than adding a level.
4. **Tail sampling at the `unit` boundary**, with `MAX_SPAN_BUFFER_EVENTS = 64` and a peak-memory
   bound stated as a formula, because `sample.non_ok = 1.0` is unimplementable at span open and
   head sampling produces the orphans I33 forbids.
5. **Eleven appended `[[event]]` rows** for the read path, the compile path, driver logs, doctor
   checks and the shard-roll marker; plus **`level` as a required key on every row**, which
   regenerates `tools/events.toml` and `schema/event-v1.json` once under G20.
6. **`Event.writer_id`**, and `seq` scoped to `(run_id, writer_id)` and assigned before the
   drop-oldest queue, so a gap means a drop rather than a second writer.
7. **`tools/metrics.toml`** as the generated, byte-diff-gated metric registry with a declared
   `source` per row, a closed label-cardinality rule, and a source-resolution check against
   `tools/events.toml` and the applied migration set; `schema/metric-v1.json` is emitted from it
   under G6. Plus the two explicit bucket ladders (`ms_pow2`, `bytes_pow2`) and their generated
   `CASE` ladder, because SQLite has no percentile aggregate and no guaranteed `log2()`.
8. **`ow_store_wal_growth_bytes`** against `size_at_last_full_backfill`, and the alerting rule
   that the growth series and not the raw size is what a pager watches.
9. **The `spend_attribution` view**, with `admission` selected so a deferred decision is
   distinguishable from a free one, `cost_class` selected so `ow_spend_micros_total{cost_class}`
   and `ow cost --by driver`'s `class` column have a source, and no new index.
10. **Service GPU-time apportionment** by `wall_ms` with a named residue rule, with
    `cost.gpu_ms_apportioned` separated from `cost.gpu_ms_measured` and a tilde in the
    per-document render. The charter requires `gpu_ms` in `Spend` and gives no client-side way to
    measure it.
11. **`Event.level` closed to five values, declared per `kind`** and applied at `emit()`. The
    charter types it `level: str`.
12. **`ConsoleSink` writes to stderr** and self-suppresses when stderr is not a TTY, so a console
    sink can never corrupt a `--render json` document.
13. **`redact()`, its `field` argument and `tools/redact.toml`**, plus the traceback ban and its
    semgrep rules in G8's set. The charter's §6.11 names document content as untrusted input and
    never addresses the log direction.
14. **The `[observe]` keys `level`, `redact`, `retain_days`, `driver_log_max_chars`** — all
    classified **operational** in `tools/config_axes.toml` and all added to
    `omniweave.toml.example`, because G18 asserts the two key lists cover that file *exactly* and
    a key declared only in code would fail it from the other direction.
15. **OTLP as OTLP/HTTP JSON over `urllib.request`**, with no `opentelemetry` import anywhere at
    release 1, a resumable export cursor, and a `shard.roll` marker record so `--follow` tails a
    rotating file correctly. `omniweave-serve`'s declared dependencies are `core, ports, mcp`
    under a 40 MB ceiling and an SDK fits in neither.
16. **`GET /healthz`** on `ow serve --http` only, returning two integers and no names.
17. **`ow trace prune`** as the fourth `ow trace` verb, and `ow doctor --deep`; plus `ow doctor`'s
    ≤ 10 s warm budget with its two named breaching checks.
18. **`ow doctor` D-26**, and the eleven `Degradation.kind` members the charter's closed literal did
    not admit — now printed, with the other sixteen, in §6.3's register.
19. **`Degradation`'s printed field set** (§6.3): the charter gives eight fields; this document adds
    `unit_uri`, `knob` and `fix_command`, relaxes `rung_reached` to `Rung | None` because no
    read-path member occupies a rung, and gives every field but `kind` and `message` a default so
    the plan's existing partial constructions type-check. Charter §9 errata `E22` grants exactly
    this — the three added fields, the `rung_reached` relaxation and the defaults — and says so;
    `E15` grants the `kind` literal and its member count, and deliberately covers nothing else.
20. **`DegradationRollup` and `MAX_ROLLUP_PARTS = 64`** as the manifest's `degradations` value,
    which is what makes §1.1's "a dict keyed by a closed vocabulary" a bound rather than a hope.
21. **`FORCES_DEGRADED`** — the seven of the twenty-seven members that force
    `Verdict.state = "degraded"` when they occur inside a query. The charter forces `degraded` from
    `ChannelStatus.unavailable` and from the fifteen gates and never says what a read-path
    `Degradation` does; [storage, indexing and retrieval](07-store-and-retrieval.md) §6 consumes
    the name and this document defines it.

## Open questions

- **`Degradation.kind` is printed at twenty-seven members in §6.3, against the charter's closed
  sixteen — and the remaining question is the three the register reserves without a construction
  site.** The literal, the surrounding fields and the per-member register now live in §6.3, which
  is this type's sole home (charter §9 errata `E15`); the eleven members the charter's literal did
  not admit are registered as `15#1` in [risks](17-risks.md) and closed by that table, and
  `ow_degradation_total{kind}` is now exactly twenty-seven series rather than eleven label values
  the type does not admit. What is *not* closed: `acceptor_exhausted`, `auto_demote` and
  `toolchain_missing` are charter grants that no plan document constructs, so their field shapes —
  which `unit_dim`, whether `wanted_driver` is set — are asserted by §6.3's register and unverified
  by a caller. **Closes when** the acceptor ladder ([routing](05-ingest-and-routing.md) §6.4), the
  scoreboard's auto-demotion and the `bake` tier ([generation](09-generation.md) §9) each construct
  one, at which point either the register's row stands or the constructing document reports the
  mismatch. **Pre-committed fallback:** a member still unconstructed at the P5 exit review is
  struck from the literal, and the register, the `Literal`, §4.2's series count and the charter's
  `E15` row are amended in that one change — a member with no writer is a fiction the type check
  cannot catch.

- **The redaction canary test has no gate number — ANSWERED** by
  [ADR-2](adr/0002-invariant-and-gate-registers.md), which retires the charter's "CI gates are
  `G1-G27` and nothing else" (erratum `E33`) and allocates the test **`G29`**: job `gates`,
  budget 60 s, its row in `tools/gates.toml` and its rendering in
  [repo layout](11-repo-layout.md) §6.4. §8.3 is the assertion's sole home. The G8 absorption this
  entry proposed was rejected there for a stated reason: `G8` is a static scan, the canary is a
  full ingest under four forced faults followed by a grep over produced artefacts, and one failure
  message cannot mean both "a semgrep rule fired" and "content leaked into an artefact". **This
  entry is a pointer and carries no fact of its own.**

- **Is `ok = 0.015625` the right sample rate, and is it the right *shape*?** One in 64 sits
  between §3.3's two arithmetics: it turns the reference ingest's 19 shards into 2. It is
  untested against an interactive workload, where 1-in-64 means most single-document ingests emit
  no unit spans at all and §7's "slowest attempts" block falls back to the ledger every time.
  **Closes when** `ow trace stat` reports records, bytes and the observed deflate ratio per Stage
  across the reference ingest and a week of interactive use. **Pre-committed fallback:** rate by
  `trigger` — `1.0` for `cli`/`hook`/`sdk`, `0.015625` for `watch`/`upstream` — because an
  interactive run's whole trace is smaller than one shard, and the fallback is a two-line change
  to a default rather than a mechanism.

- **Per-document GPU attribution under Coalescing is an estimate and the error is unbounded.**
  §5.3's `wall_ms`-proportional apportionment sums correctly at corpus grain and can be
  arbitrarily wrong for one document batched with dissimilar work. **Closes when** F7's
  `ow bench service` measures the Coalescing speedup and the batch-composition spread, at which
  point either the server exposes per-request accounting (attribute it exactly and drop the
  tilde) or the tilde becomes a stated confidence interval.

- **`ow top` reads `work` at 1 Hz `mode=ro`; is that free?** A read-only open on a contended
  store is cheap, but `SELECT cost_class, status, count(*) FROM work GROUP BY 1, 2` over 846k
  rows is a full scan of a partial index, and F8 has not measured the scheduler's per-unit cost
  either. **Closes when** `ow bench scheduler` reports the scan cost at 1M rows.
  **Pre-committed fallback:** back `ow top` off to 0.2 Hz and read the manifest's incremental
  counts instead, accepting staleness in a display that is already a display.

- **`ow trace tree`'s ~0.5 s per shard is derived, not measured.** §3.3 gets it from a 400 MB/s
  sequential read and a ~1 μs/record `json.loads`, both of which are assumptions rather than
  readings, and the parse term dominates by 2.2×. **Closes when** `ow trace stat` prints its own
  wall time per shard on the reference ingest. **Pre-committed fallback:** if the parse term is
  materially worse, `ow trace tree` gains a `--fields off` mode that reads only the envelope
  keys with a bounded manual scan and never calls `json.loads` on `fields` — which is what
  `--slow` and `--unit` already filter on, so the fast path exists before the measurement does.

- **Does an operator want a metrics listener badly enough to break the no-daemon rule?** The
  design's answer is no: `ow trace export --follow` plus a 60-second cron over
  `ow cost --render json` covers scraping without a listener. **Closes when** a real deployment
  reports that its monitoring cannot pull, only scrape. **Pre-committed fallback:** a
  `--prometheus` *file* writer (textfile-collector shape) in `omniweave-serve`, never a listener,
  because a listener is a third sanctioned TCP endpoint and that is a charter amendment.

- **`ow doctor`'s ≤ 10 s warm budget has no home in the gate table.** G10 measures cold start for
  `ow --version`, `ow --help` and `ow query`, and G26 measures `ow hook prompt`; nothing measures
  the command every support interaction begins with, and §9.2's 8 s probe cap is a design choice
  with no assertion behind it. **Closes when** [performance](12-performance.md) either adds
  `ow doctor` to the cold-start budget table or states that it is deliberately unbudgeted; this
  document's number stands as a target until then.

## New terms

Additions proposed for `terminology.md` §2, in the same change as this document.

| Term | Kind | Definition |
|---|---|---|
| Stage | concept | The pipeline phase a span belongs to, carried as the span attribute `ow.stage` on `plan` and inherited by descendants. A closed nine-member vocabulary — `discover`, `plan`, `parse`, `derive`, `index`, `converge`, `maintain`, `query`, `compile` — whose first seven members are the key set of `manifest.stage_ms`. **Not `phase`**, which is `Event.phase`'s `start\|end\|point`, and **not** `derive_pass.phase`, which is a card-declared ordering integer within a `cost_rank`. |
| `stage_ms` | column | The run manifest's `Stage -> summed elapsed ms` map, with `stage_entries` beside it giving the number of `plan` spans that contributed. **Not `timings_ms`**, which is `doc.timings_ms`: one document's driver-reported parse timings. Two objects at two grains, two names. |
| `writer_id` | column | `sha256(host ‖ pid ‖ process_create_time)[:12]`, the same triple `work.claimed_by` carries. Present on every `Event`, and the second half of `seq`'s scope: one `run_id` may have several writers, and a per-`run_id` counter alone would make every restart look like a gap. |
| `spend_attribution` | view | The one join from `route_unit_decision` through `route_decision` to `route_spend` that makes I30's per-`(unit, part, decision, attempt)` attribution queryable. Per-document, per-corpus and per-driver cost are `GROUP BY`s of it. The `LEFT JOIN` is deliberate — a `deferred` decision has no spend row and must still appear — and `admission` is selected so `micros IS NULL` (deferred) is distinguishable from `micros = 0` (a free driver ran). `d.cost_class` is selected because `route_spend` has no class column, and it is what gives `ow_spend_micros_total{cost_class}` and `ow cost --by driver`'s `class` column a source. Unlike `route_scoreboard` it does **not** filter `pinned`, which is why the bill is summed here and never there. One row per attempt per rung, so every consumer aggregates. |
| `redact()` | fn | The pure function in `omniweave_core.events` applied at the construction boundary of every message crossing into an `Event`, a ledger column or a console line. Returns `(redacted, n_removed)`; takes the target column as `field` so a declared digest column is exempt from the hex-run rule. Removes paths under a `[roots]` entry and long non-identifier runs under `redact = "paths"`, and credential shapes and untrusted markers unconditionally. No traceback is ever passed to it, because no traceback is ever rendered. |
| `tools/metrics.toml` | file | The generated, byte-diff-gated metric registry: one row per metric with `name`, `type`, `unit`, `labels`, an optional `buckets` ladder, and a declared `source` (an event `kind`, a SQL expression, or a column for a histogram). `schema/metric-v1.json` is emitted from it under G6. A metric with no source, a label outside the closed-cardinality set, or a source naming a `kind` or column that does not exist fails CI. |
| `tools/redact.toml` | file | The credential- and marker-shape register `redact()` reads: `Authorization` values, prefixed tokens, JWTs, long hex runs with a closed `exempt_fields` list, `<ow:untrusted>` markers and chat-template sentinels. Patterns are TOML literal strings. Append-only, like `codes.toml`. |
| `ms_pow2` | const | The one shared histogram bucket ladder for millisecond-valued metrics: seventeen explicit base-2 boundaries from 1 to 65536 plus `+Inf`, generated into a `CASE` ladder in `omniweave_core/store/sql/hist.sql` and into OTLP `explicitBounds`. `bytes_pow2` is its byte-valued twin, 1 KiB to 64 GiB. Fixed and shared, so two runs' histograms are addable. |
| `MAX_SPAN_BUFFER_EVENTS` | const | `= 64`. The per-open-`unit` tail-sampling buffer ceiling in a `TraceSink`. An overflow flushes the unit **unsampled** rather than truncating its subtree, so a sampling decision never produces an orphan span. Peak buffer memory is `Σ max_inflight × MAX_SPAN_BUFFER_EVENTS × mean event bytes` per process. |
| `size_at_last_full_backfill` | column | The WAL baseline on `store.wal_valve`, refreshed whenever a checkpoint reports everything backfilled. `ow_store_wal_growth_bytes` is measured against it, because raw WAL size recycles inside one file after a backfill and a size-triggered alert latches on and never clears. |
| `DegradationKind` | type | The closed twenty-seven-member `Literal` behind `Degradation.kind`, printed with one register row per member in §6.3, which is its sole home (charter §9 errata `E15`). `ow_degradation_total{kind}` is exactly twenty-seven series because this literal is closed. |
| `DegradationRollup` | type | The value of one `manifest.degradations[<kind>]` entry: `n`, `first_ns`/`last_ns` from the host `Clock`, the distinct units and the union of `parts_affected` capped at `MAX_ROLLUP_PARTS`, a `truncated` flag, and the first record verbatim as `exemplar`. It is what makes the manifest's degradation list bounded at twenty-seven entries. |
| `MAX_ROLLUP_PARTS` | const | `= 64`, matching `MAX_SPAN_BUFFER_EVENTS`. The cap on `DegradationRollup.units` and `.parts_affected`; hitting it sets `truncated = true` so a reader never mistakes the cap for the total. |
| `FORCES_DEGRADED` | const | The seven `DegradationKind` members that force `Verdict.state = "degraded"` when they occur inside a query, defined beside `DegradationKind` and consumed by `build_verdict()` ([07](07-store-and-retrieval.md) §6). The other twenty are ingest-time or system-facing and are disclosed without touching a verdict. |
| `Degradation.knob` | field | The one fully-qualified config or policy key that would undo a degradation, machine-readable — e.g. `"[budget.per_unit].micros_per_part"`. The charter's CI test resolved a key *quoted inside* `message`; it now resolves this field. `None` is a positive assertion that no configuration change helps, and then `fix_command` or a non-configuration remedy in `message` is required. |
| `Degradation.fix_command` | field | The exact command line that clears one degradation, e.g. `"ow add invoice.pdf --allow-cost 12000"`. Distinct from `knob`: [routing](05-ingest-and-routing.md) §10.3 prints both, and `ow index stats` is a command with no key behind it. |
