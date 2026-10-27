# 12 — Performance, Scalability and Efficiency

## In one paragraph

Every performance number in omniweave is a **row in `eval/perf.toml`** with a value, a tolerance, a
gate class and a named Runner, measured as a **Pacer ratio** for time, an **absolute** for RSS and
WAL, and an **exact integer** for counters — because a clock moves for a hundred reasons and a
counter moves for one. This document states the budgets operation by operation on three named
**reference machines**, the cold-start table G10 gates against, the scaling envelope at 10 / 1k /
100k / 10M documents with the component that binds at each step, the resident-set policy and the
streaming rules that make a 5,000-page document and a 4-million-cell sheet both survivable, the
efficiency techniques each with its measured or derived saving, a dollar cost model for three
corpora under three configurations plus the incremental unit cost, the `ow bench` harness, and the
regression mechanism that stops all of it rotting. It does not restate the query latency
decomposition ([07](07-store-and-retrieval.md) §4.4), the store's byte-per-Block sizing
([07](07-store-and-retrieval.md) §4.1-4.3), the `owrows/1` grammar
([07](07-store-and-retrieval.md) §7.5), the WAL valve and Bulk window mechanics
([07](07-store-and-retrieval.md) §10.5-10.6), the routing cost table
([05](05-ingest-and-routing.md) §6.6) or the accuracy gates ([13](13-quality.md) owns the Q-G
series); it links them and owns the numbers nobody else does.

## 1. Reference hardware, and what a number without it means

**A performance number without a reproduction tuple is not a number.** `MeasuredOn` is frozen with
ten required fields and no defaults; a row missing one is a `TypeError`, not a blank cell, and Q-G8
refuses to publish it. Three **reference machines** are named here; every budget row in §2 says
which one it holds on, and `timing_basis` says what the clock covered.

| id | what it is | spec | role |
|---|---|---|---|
| **`ow-bench-1`** | the pinned Pacer Runner. `[pacer] runner = "ow-bench-1"` | x86_64-linux, 8 cores / 16 GiB, NVMe, CPython 3.11.9, SQLite ≥ `MIN_SQLITE = (3,42,0)`, **no GPU** | every `free` and CPU-side `local_compute` budget; nightly ≤ 90 min; weekly T5 soak ~3 h. **The only machine that carries a Pacer baseline, and therefore the only machine a `Budget` may live on** |
| **`ow-gpu-1`** | the GPU reference | single RTX 5090 (32 GB), `vllm/vllm-openai:v0.20.1`, same host CPU | every `PAGE`-rung and GPU `embed` reference row. Chosen **because surya publishes its own throughput table on exactly this configuration**, so our hardware is comparable to a third-party measurement rather than to nothing |
| **`ow-laptop-1`** | the floor, and the one that decides adoption | Apple Silicon, `llama-server` Metal backend, `--parallel 8`, 18 GB unified | the same `PAGE`-rung rows on the machine a first user actually has. surya publishes this row too |

`ow-bench-1` is deliberately the machine named in the driver card's own `hardware` string
(`"x86_64-linux 8c/16GiB"`), so a first-party `[cost.measured]` block and an `eval/perf.toml` row
are measured on the same silicon and can be compared without a conversion factor.

**`ow-gpu-1`'s 32 GB is at the bottom of the resident-engine envelope, deliberately.** §4.1 budgets
a resident 7B VLM engine at 20-40 GB of VRAM, so a 7B model at bf16 with a generous KV cache does
**not** fit on this card: `ow bench service` runs it with a reduced `--max-model-len` and
`gpu_memory_utilization`, and the run records both in `MeasuredOn.runtime_version`. That is the
point of the choice — the reference GPU is a card a user plausibly owns, not the one that makes the
numbers look best, and it is the reason `MAX_AUTO_PARALLEL = 96` is a cap past a B200's knee rather
than a default (charter §D6 claim 1).

### 1.1 `timing_basis`, with the inclusion boundary written down

**`timing_basis` is a required column on every card `[cost.measured]` block and every `eval_run`
row, and two rows with different bases may never share a column.** The charter locks the three
values and that rule; it does not say what each covers, and an unstated boundary is a silent
comparison error worth 20× on B02 against B03. The boundaries:

| `timing_basis` | includes | excludes | used for |
|---|---|---|---|
| `in_process` | the call, in the already-warm host process | interpreter start, driver import, model load | per-part and per-Block driver budgets |
| `spawn_inclusive` | fork/exec of the `subproc` DriverHost, HELLO, the call, teardown | interpreter start of the CLI itself | the honest per-unit cost at `max_workers = 1`, and every CLI-verb budget |
| `server_attached` | the request against an already-attached Service | the ~31 s model load, which the Service pays once per run | every `PAGE`-rung row |

**This rule is violated by the most-cited benchmark in the collection, and the violation is why B02
carries a caveat.** anydoc's self-benchmark times anydoc, markitdown, docling and unstructured
**in-process** and pandoc and LibreOffice **including process spawn**, "that's how they're used in
practice" (`_index/comparisons.md`). So anydoc's 4.4 ms and LibreOffice's 1,129.5 ms are not in the
same column and their 257× ratio is not a measurement of anything. The comparison that *is*
basis-clean is anydoc **4.4 ms** against docling **513.6 ms**, both `in_process`: **117×**. PDF is
explicitly excluded from that harness, and anydoc wrote both the harness and the winner, so the row
publishes with `witness = self` and the entrant-bias bit set, which makes it `UNRANKED` under §7.4.
`parse.office.p50_ms = 5` is therefore a budget omniweave **re-measures on `ow-bench-1`**, not a
number it inherits.

### 1.2 The Pacer, and the three things it does not cover

Every time budget on `ow-bench-1` is a ratio to the Pacer: `blake2b` over 64 MiB, a 2M-iteration
integer loop, and 200k SQLite insert+select, run immediately **before and after** the timed
measurement. `time_ratio = work_ns / mean(pacer_before_ns, pacer_after_ns)`. Disagreement above
`instability_pct = 15` between the two readings yields `EvalStatus.UNSTABLE` — **neither a pass nor
a fail** — and the correct response is to fix the Runner, never to bless the row. An eval status is
`pass`, `fail`, `unstable`, `stale` or `unknown`, and there is no sixth value that lets a warning
survive without failing. *(Build note, D822: `omniweave.run.bench.pacer()` is the workload. It hashes 1 MiB of zeros 64 times, runs a 64-bit linear congruential loop, and makes `store.pacer.sqlite_round()`'s 200k inserts, in one transaction, plus their select, over a scratch file. Each third is timed by an injected clock and returns a result proving it ran. `paced()` builds the `eval_perf` row: `unstable` past 15%, otherwise `unknown`, because the pass or fail is the nightly's comparison with its rolling median. `ow bench pacer --runs N` runs it N times, and measured ~0.65 s a run on this Windows machine.)*

Three limits are stated here because the draft mechanism hides them:

1. **The Pacer is CPU and disk only.** It contains no GPU work and no network. A `server_attached`
   row therefore has no Pacer ratio, which is the subject of §8.5.
2. **The Pacer runs on `ow-bench-1` alone.** `[pacer] runner` names one machine. A row measured on
   `ow-gpu-1` or `ow-laptop-1` cannot be ratio'd and cannot be a `Budget`.
3. **Two concurrent bench runs invalidate both.** `ow bench` takes an exclusive `flock` on
   `$OMNIWEAVE_HOME/bench.lock` and a second run **refuses with exit 7** — the same store-busy exit
   code — naming host, pid and age. It does not queue, because a queued run measures a page cache
   the first run warmed.

**A Runner change is a baseline reset, and the reset has a procedure.** The new host runs **seven**
nightly cycles before any `nightly` row is gated again — seven because the comparison is against a
7-run rolling median and a shorter window compares a number to itself. During those seven nights
every `nightly` row's `class` in `eval/gates.toml` is `informational` with an owner and a
`review_by` at day 14, so Q-G17 fails the build if someone forgets to re-arm them. The reset is a
reviewed diff, exactly like any other class change (§8.3 step 5).

## 2. The performance budget

Three tables. §2.2 is **the whole envelope**, operation by operation, including rows nothing gates.
§2.3 is the **cold-start table** G10 checks against a per-OS baseline. §2.4 is the subset that is a
committed `eval/perf.toml` row with a tolerance and a gate class — the numbers CI actually fails on.

### 2.1 Notation

- **M** = measured by us or by a first-party card's kit-written `[cost.measured]` block, source
  named. **X** = extrapolated, derivation named. **R** = a **third-party published reference**: a
  real number, on real hardware, produced by software omniweave does not ship.
- **An X row may not become a gate until it has been measured once on `ow-bench-1`. An R row may
  never become a gate at all** — it publishes with `witness = third_party`, which §7.4 resolves to
  `UNRANKED`, and it exists to bound what a rung *could* cost, not to promise what ours does.
- Times are p50 / p95 of the operation, `timing_basis` as stated, min-of-5 warm.
- A `PAGE`-rung row carries **both** the throughput-amortised per-page figure and the per-request
  wall latency, because at the concurrency that maximises throughput they differ by two orders of
  magnitude, and quoting only one is how a capacity plan goes wrong by 100×.

**The two page-driver anchors are different models and may not be mixed.** The shipped `PAGE` driver
is `parse.page.olmocr` — a **7B** VLM whose card declares `gpu_ms = 2,400` p50. Every surya row
below is a **650M**-parameter model whose weights omniweave **may not ship at all**:
`parse.page.surya` is a framework-owned **Tombstone** at `tier = "forbidden"`, because clause 2(c)
of its weights licence bars use by any party offering a competing product with no revenue threshold
(charter §D3). Its published throughput is admissible as evidence about *hardware and shape* and
inadmissible as a budget for omniweave's own `PAGE` rung. **The per-page work differs by 12.8×
(2,400 ms against 187 ms), so a wall-time row and a dollar row in this document name their driver
explicitly, every time.**

### 2.2 The envelope

| # | Operation | Runner | basis | p50 | p95 | class | Ground |
|---|---|---|---|---:|---:|:--:|---|
| B01 | format decode: content-first detection of one unit (magic + container probe) | `ow-bench-1` | `in_process` | 0.3 ms | 2.1 ms | **X** | one 8 KiB read plus, for OOXML, a ZIP central-directory read; the p95 is the container branch ([05](05-ingest-and-routing.md) §2.2-2.5) |
| B02 | office document decode, whole document (`parse.office.anydoc`) | `ow-bench-1` | `in_process` | **4.4 ms** | 41 ms | **M** | `anydoc/README.md` benchmark table row 178: 4.4 ms median over 100 documents across 14 formats, PDF excluded, against docling's 513.6 ms on the same basis (117×). p95 is the card's kit-written `p95_ms_per_unit = 41`. `witness = self`, entrant-bias set — see §1.1 |
| B03 | office document decode, spawn-inclusive | `ow-bench-1` | `spawn_inclusive` | 95 ms | 180 ms | **X** | B02 plus a `subproc` fork/exec and HELLO. This 21× ratio is why `inproc = ["parse.office.anydoc"]` exists as a reviewable act and why `inproc_bulk_threshold = 64` exists at all |
| B04 | born-digital PDF page parse (`parse.pdf.pdfium`, text layer) | `ow-bench-1` | `in_process` | 8 ms | 35 ms | **X** | the working figure in [05](05-ingest-and-routing.md) §10.1's 188-page trace. The charter **struck** "p50 210 ms for a native PDF driver" as an illustrative transcript line mistaken for a measurement; P-Q1 is the measurement |
| B05 | routing evidence, FREE group, one clean born-digital part | `ow-bench-1` | `in_process` | **2 ms** | 6 ms | **M/X** | 2 ms is the charter's reference-ingest figure for five FREE signals ([05](05-ingest-and-routing.md) §6.6); the p95 is extrapolated from the two O(chars) signals inside `garble.score` (character 5-gram log-probability and dictionary miss rate) |
| B06 | `evaluate()` over the shipped ~40-rule policy | `ow-bench-1` | `in_process` | 50 µs | 140 µs | **X** | pure atom walking, memoised on the compiled `RoutePolicy` ([05](05-ingest-and-routing.md) §6.6) |
| B07 | routing evidence, LOCAL_COMPUTE group: one 96-DPI grayscale render plus `ink.tiles` | `ow-bench-1` | `in_process` | 15 ms | 40 ms | **X** | [05](05-ingest-and-routing.md) §10.1 uses 15 ms on the scanned branch and 16 ms on the `ink.coverage` branch. **15 ms of CPU to avoid a 2,400 ms GPU call is a 160× trade**, and it is why INV-13 is structural rather than advisory |
| B08 | `PAGE` rung, `parse.page.olmocr`, the card's declared per-page GPU work | `ow-gpu-1` | `server_attached` | **2,400 ms** | 7,680 ms | **M/X** | olmocr p50 2.4 s, the charter's reference-ingest figure. The p95 is the **reservation** basis: [05](05-ingest-and-routing.md) §10.1 reserves 2,732 micros against an estimate of 854, i.e. 3.2×, and `reserved gpu_ms 7,680 = 2,400 × 3.2`. §2.5 reconciles 3.2 against the 2.25 a published tail actually shows |
| B09 | `PAGE` rung, `parse.page.olmocr`, per-request wall at any concurrency | `ow-gpu-1` | `server_attached` | **unknown** | **unknown** | — | **Nothing in the collection publishes olmocr's per-request latency at concurrency.** This is F7, and it is the single largest hole in the capacity model: the shipped default driver's wall time is a 1.5×-4× band around a serial figure. `ow bench service` is the instrument |
| B10 | `PAGE` rung throughput-amortised, surya-650M reference | `ow-gpu-1` | `server_attached` | **187 ms** | — | **R** | `surya/README.md` throughput table: 5.35 pages/s at concurrency 128, 96-DPI input, 2,410 avg output tokens/page ⇒ 1/5.35 = 186.9 ms of GPU per page. A 650M model, forbidden weights (§2.1) |
| B11 | `PAGE` rung per-request wall at that concurrency, surya-650M reference | `ow-gpu-1` | `server_attached` | **18,915 ms** | **42,538 ms** | **R** | the same table. **This is the number a per-document deadline must respect, and B10 is not**; `[isolation] wall_ms_hard = 120_000` sits above this p95 with 2.8× of headroom, which is the case the constant was sized for |
| B12 | `PAGE` rung throughput-amortised, surya-650M reference | `ow-laptop-1` | `server_attached` | **9,259 ms** | — | **R** | `surya/README.md` Apple Silicon row: 0.108 pages/s at `--parallel 8`, ~30 W. **50× the GPU figure**, and the number that makes `--max-rung decode` a first-class mode rather than a curiosity |
| B13 | `PAGE` rung per-request wall, surya-650M reference | `ow-laptop-1` | `server_attached` | **59,313 ms** | **129,173 ms** | **R** | the same row. **The p95 exceeds `wall_ms_hard = 120_000` and the p50 is 4× `progress_ms = 15_000`.** §2.6 is the consequence, and it is a defect rather than a preference |
| B14 | free deterministic extraction, one Segment, one pass | `ow-bench-1` | `in_process` | 0.6 ms | 2.4 ms | **X** | a regex or Aho-Corasick scan over ~4,800 chars of Segment text (`SEGMENT_TARGET_TOKENS = 1200` × ~4 chars/token) |
| B15 | free deterministic extraction, one Segment, the whole shipped free ladder | `ow-bench-1` | `in_process` | **4.2 ms** | 17 ms | **X** | seven shipped free passes × B14. At the ~30-Blocks-per-Segment planning ratio that is **140 µs/Block**, which is the "extraction per Block" figure |
| B16 | billed LLM extraction, one Segment (2,000 tokens in / 600 out) | `ow-gpu-1` | `server_attached` | 1,200 ms | 3,840 ms | **X** | `SEGMENT_TARGET_TOKENS = 1200` plus prompt and schema in, `MAX_ITEMS_PER_SEGMENT`-bounded out; decode-bound, so the p95 tracks B08's 3.2× reservation multiple. **P-Q5 is the measurement, and every C3 figure in §6 rests on it** |
| B17 | billed field extraction, whole document, `fields` lane | GPU, 8 concurrent | `server_attached` | **9,500 ms** | — | **R** | `lift/README.md`: 9.5 s median per document over a 225-document, 6-64-page, ~11,000-scored-field benchmark, vLLM on a single GPU. `fields` is document-grain, so this is the right grain. **It buys 90.2% field accuracy and 20.9% whole-document accuracy**, which is why `doc_acc` on `fields/*` is gated at 0.20 and never shipped without `field_acc` (Q-G21) |
| B18 | embed one Segment, batch 1 | `ow-bench-1` | `in_process` | 180 ms | 320 ms | **X** | a 768-dim encoder over 1,200 tokens on CPU. **Off the default path**: `[retrieval] vectors = "off"` |
| B19 | embed one Segment, batch 32 | `ow-bench-1` | `in_process` | 22 ms | 40 ms | **X** | the same forward pass amortised; batching is the entire saving on CPU (8.2×) |
| B20 | embed one Segment, batch 64 | `ow-gpu-1` | `server_attached` | 6 ms | 14 ms | **X** | 3.7× B19 on a card, which is why `embed` is the one lane where a GPU pays for itself on a corpus this small |
| B21 | embed **the query text** at read time | `ow-bench-1` | `spawn_inclusive` | 40 ms | **120 ms** | **X** | [07](07-store-and-retrieval.md) §4.4 phase 2. `embed_ms = 120` is a deadline **outside** `query_ms` and **outside** the snapshot, because a held read transaction pins the WAL. A breach is `semantic: UNAVAILABLE(embed_timeout)` and forces `degraded` |
| B22 | index commit: one `work` transition (claim share + `Store.complete()` + key + ~8 events) | `ow-bench-1` | `in_process` | **0.45 ms** | 1.0 ms | **X** | the charter's `≤ 0.5 ms/unit` runtime overhead, cross-checked against G22's `≥ 2,000 transitions/s` = 0.5 ms/transition. F8 is the measurement and names p95 > 1 ms as the trigger for widening group commit |
| B23 | index commit: `end_page()`, one page of 120 Blocks | `ow-bench-1` | `in_process` | 6 ms | 25 ms | **X** | 120 rows × ~660 B across `block`, nine indexes, `block_fts` and `block_sec`, in one transaction at `synchronous = NORMAL` ([07](07-store-and-retrieval.md) §4.1 owns the byte decomposition) |
| B24 | index commit: a `BILLED_API` unit at `synchronous = FULL` | `ow-bench-1` | `in_process` | 8 ms | 30 ms | **X** | ST14 sets `FULL` **before** `BEGIN` for a billed operator. One fsync against a VLM call is free; re-billing a page because a laptop lid closed is not |
| B25 | bulk index rate, inside a Bulk window | `ow-bench-1` | `in_process` | **204k rows/s** | — | **M** | codegraph: 224k edges in **1.1 s** with non-UNIQUE secondary indexes dropped, against **2.8 s** with them present, and ~0.3 s to recreate — **2.0× net** ([07](07-store-and-retrieval.md) §10.6) |
| B26 | cold query: `ow query` on a warm page cache but a cold process | `ow-bench-1` | `spawn_inclusive` | 700 ms | 1,400 ms | **X** | `cold.ow_version_ms = 118` plus the lazy import of `{store, retrieve, answer}`, `connect_readonly`, and first-touch B-tree reads. G17 is what keeps the 118 ms honest. **Not gated** — §2.3 explains why |
| B27 | warm query, four Channels, `vectors = "off"` | `ow-bench-1` | `in_process` | **180 ms** | 250 ms | **M/X** | `query.warm_p50_ms = 180` ± 20% is the committed budget; 250 ms is G10's ceiling and `[retrieval.budget] query_ms`. The per-scale decomposition (≈12 / 35 / 110 ms at 10k / 1M / 10M Blocks) is [07](07-store-and-retrieval.md) §4.4's, and is labelled an estimate there (F50) |
| B28 | warm query, five Channels, stdlib `vector.brute` at 250k Segments | `ow-bench-1` | `in_process` | 281 ms | — | **M/X** | 180 ms plus the **measured** 101 ms signature scan. **This exceeds the 250 ms ceiling**, which is precisely why `VEC_BRUTE_MAX = 250_000` is a refusal (`OW-S-022`) and not a slow path |
| B29 | `ow hook prompt`, warm | `ow-bench-1` | `spawn_inclusive` | 150 ms | **250 ms** | **X** | G26's gate. **The tightest latency path in the framework**: a silent exit-0 deadline breach turns the adoption lever off with no symptom at all |
| B30 | `ow hook prompt`, cold | `ow-bench-1` | `spawn_inclusive` | 600 ms | **1,000 ms** | **X** | G26's cold half |
| B31 | driver discovery, 20 installed distributions | `ow-bench-1` | `in_process` | 15.3 ms | **20 ms** | **M** | `entry_points(group=…)` measured at 15.3 ms over **328** installed distributions, warm — so 20 dists is comfortably inside V01-3's 20 ms ceiling. **Imports nothing** (G11) |
| B32 | driver card cache validity check, 328 distributions | `ow-bench-1` | `in_process` | **1.01 ms** | — | **M** | `scandir`+`stat` of every `*.dist-info`, against **2,124 ms** for a `Distribution.files` (`RECORD`) scan — a **2,100×** gap, which is why `RECORD` is *forbidden* as a discovery mechanism rather than merely discouraged. Implies **~3.1 µs per `stat`**, which B42 reuses |
| B33 | archive Frame decode, 8,192 Blocks into frozen `Block` instances | `ow-bench-1` | `in_process` | **45 ms** | — | **X** | `archive.frame_decode_ms ≤ 45`, i.e. 182,044 Blocks/s ([03](03-document-model.md) §13.4 owns the shape it is measured over and says this budget is ours) |
| B34 | whole `.owdoc` decode, 1M Blocks (123 Frames) | `ow-bench-1` | `in_process` | **5.5 s** | — | **X** | 123 × B33. At 10M Blocks it is 55 s, which is why `ow store import` runs through `work` and not inside a request |
| B35 | point read of one Block by `block_id` | `ow-bench-1` | `in_process` | **20 µs** | 25 µs | **M** | a SQLite index seek. The comparison that decided the at-rest format is Parquet's **42.8 ms** for the same point read — a factor of ~2,000. The 25 µs at 10M Blocks is one more B-tree level at `page_size = 8192` and is an estimate |
| B36 | `owrows/1` encode of one `Response` (20 hits, 3 tables) | `ow-bench-1` | `in_process` | 0.4 ms | 1.2 ms | **X** | prefix-frequency legend build plus one pass per table over ≤ 20 rows × ≤ 14 columns. `encoding = "auto"` encodes, measures and **discards** below a 15% saving, so the worst case is B36 wasted, not a larger payload ([07](07-store-and-retrieval.md) §7.5) |
| B37 | artefact compile, one `pptx` unit (a slide) from retained IL | `ow-bench-1` | `in_process` | 45 ms | 140 ms | **X** | carrier parse plus `lower()` plus one OPC part write. Nothing in the mined collection times a deck compile; P-Q2 is the measurement |
| B38 | artefact compile, whole `pptx` artefact, 20 units | `ow-bench-1` | `in_process` | 1.2 s | 3.4 s | **X** | 20 × B37 plus one canonical-order OPC zip write plus the receipt |
| B39 | artefact compile, `deck` target, Toolchain spawn | `ow-bench-1` | `spawn_inclusive` | 900 ms | 2,200 ms | **X** | resolve node → verify the **full** sha256 → probe (cached per run) → spawn → drain → reap. Paid **once per compile**, not per unit, and `ToolchainResult` reports `queued_ms` separately from `ran_ms` always |
| B40 | `read_back` of a compiled artefact | `ow-bench-1` | `in_process` | 320 ms | 900 ms | **X** | it is an ordinary `parse/1` Driver emitting `owdoc-fragment/1`, so it lands in the parse budgets and inherits B23's commit cost |
| B41 | `op.resolve` MinHash band construction, per entity | `ow-bench-1` | `in_process` | 0.2 ms | — | **X** | the charter's own estimate at `num_perm = 128`. **F15 is the measurement**, and its pre-committed fallback is `num_perm = 64` plus `omniweave-driver-leiden` as the documented default install |
| B42 | `op.cluster` Louvain, one sweep at `MAX_CLUSTER_EDGES` | `ow-bench-1` | `in_process` | **~12 s** | — | **X** | ~1.5 µs/edge/sweep — one CPython loop iteration doing three `array('i')` index reads and one dict update — × 8,000,000 edges. A five-sweep run is ~60 s, which is why the refusal (`OW_GRAPH_TOO_LARGE`) sits at 8M edges and not at 80M |
| B43 | incremental re-index: one changed document in a 100k-document corpus | `ow-bench-1` | `spawn_inclusive` | **~550 ms** | ~3 s | **X** | §6.7 shows the arithmetic. **The workload a deployed system actually runs**, and the one the draft budget omitted |

### 2.3 The cold-start table, and the two rows with a gate but no budget

G10 checks cold start "on 3 OSes vs a recorded per-OS baseline, 25% drift". V01-3 fixes the
ceilings. The `eval/perf.toml` budget for each is set so that **budget × (1 + tolerance) lands just
inside the ceiling** — a breach fires before the gate does, which is the whole point of having both:

| what | V01-3 ceiling | `eval/perf.toml` row | budget + tol | headroom | basis |
|---|---:|---|---:|---:|---|
| `import omniweave_core` | **80 ms** | `import.omniweave_core_ms = 62` ±25% | 77.5 ms | 2.5 ms | `in_process`, `-X importtime` |
| `ow --version` | **150 ms** | `cold.ow_version_ms = 118` ±25% | 147.5 ms | 2.5 ms | `spawn_inclusive` |
| `ow --help` | **250 ms** | **none** | — | — | `spawn_inclusive` |
| driver discovery, 20 dists | **20 ms** | **none** | — | — | `in_process` (B31) |
| `ow query`, warm store | **250 ms** | `query.warm_p50_ms = 180` ±20% | 216 ms | 34 ms | `in_process` (B27) |

**Extends the charter (new decision).** Two of those five rows have a G10 ceiling and no budget, so
a drift of up to 25% inside G10's own baseline tolerance is invisible until it crosses the ceiling —
at which point the regression is already shipped and the bisect window is a release wide. Two rows
are added:

- `cold.ow_help_ms = 190`, ±25% (⇒ 237.5 ms, inside the 250 ms ceiling), `gate = "pr"`.
- `discovery.20dists_ms = 16`, ±20% (⇒ 19.2 ms, inside the 20 ms ceiling), `gate = "pr"`. 16 rather
  than B31's 15.3 because 15.3 was measured over 328 distributions and the ceiling is stated for 20;
  the budget is set at the measured figure and the first run on `ow bench cold` replaces it.

**B26's cold `ow query` at ~700 ms is deliberately not in this table and deliberately not gated.**
It is `spawn_inclusive` over a path whose dominant term is filesystem state nobody controls in CI
(page cache, `.pyc` freshness, store size). The gated surrogate is the pair `cold.ow_version_ms` +
`query.warm_p50_ms`, which decompose it into two things that *are* deterministic. A single 700 ms
number would be a gate that fails for reasons unrelated to any change — the flake Q-G18 exists to
quarantine, installed on purpose.

### 2.4 The gated subset — `eval/perf.toml`

These are the rows CI fails on. The file's shape is the charter's plus exactly one key — `process`,
added by [ADR-11](adr/0011-eval-register-reconciliation.md) D5 and recorded as charter §9.2 `E88`.
The table below the schema is the same data plus the escalation each breach triggers, which is the
part a plan document owes a reader.

**The `[[budget]]` row schema — this section is its sole home.** An unknown key is a hard error at
load; `tol_pct` and `tol_abs` are mutually exclusive and exactly one is required.

| key | type | required | meaning |
|---|---|---|---|
| `id` | `str`, `[a-z0-9_.]{1,64}`, unique across the file | yes | the `budget_id`; the suffix carries the unit |
| `value` | `int` or `float` | yes | the budgeted figure, in the unit `id`'s suffix names (`_ms`, `_s`, `_bytes`, else dimensionless) |
| `tol_pct` | `int`, 0-100 | exactly one of the two | tolerance as a percentage of `value` |
| `tol_abs` | `int` or `float`, same unit as `value` | exactly one of the two | tolerance as an absolute, where a percentage of a growing number is not a bound |
| `gate` | `str` ∈ `{pr, nightly}` | yes | the CI job that fails on breach |
| `process` | `str` ∈ `{supervisor, worker, driver_subproc, service}` | **iff `id` starts `rss.`**; rejected on any other row | the process whose resident set the figure bounds |
| `note` | `str` | no | provenance, free text |

`process` exists because a memory budget read at the wrong scope is an OOM kill at hour six instead
of a refusal before the run. All three `rss.` rows declare `process = "worker"`: the supervisor is
capped at 600 MB by I31 and forbidden from holding document bytes, and both a 5,000-page parse and a
4M-cell merge read document bytes (§4.1, §4.4). `tools/gate_budgets.py` asserts presence and
vocabulary membership under `Q-G15` alongside its `value + tol_abs <= tier ceiling` clause
([13](13-quality.md) §2.9); no new `Q-G` number is coined.

| `budget_id` | value | tol | gate | on breach |
|---|---:|---|---|---|
| `import.omniweave_core_ms` | 62 | ±25% | `pr` | G10 fails the PR. The usual cause is a new top-level import in core; G9 (zero third-party modules) and G23 (no `asyncio`, no `selectors`) catch the two worst kinds first |
| `cold.ow_version_ms` | 118 | ±25% | `pr` | G10. The second-order cause is a lazy submodule that stopped being lazy, which G17 names directly |
| `cold.ow_help_ms` | 190 | ±25% | `pr` | new (§2.3). `ow --help` renders the generated argparse tree, so a breach is usually G25's surface generator growing, not core |
| `discovery.20dists_ms` | 16 | ±20% | `pr` | new (§2.3). A breach means discovery started doing more than `entry_points` + `tomllib.load`; check G11 first |
| `conform.mandatory_tier_s` | 240 | ±60 s | `pr` | the 5-minute rule over the **eleven mandatory suites** of the twelve (V01-14). A conformance suite that grows past it is **split**, never skipped |
| `contributor_parity_s` | 420 | ±180 s | `pr` | hard ceiling **600 s**. Q-G22 additionally requires the clean container to be offline, GPU-free and Node-free, so this row also fails when a test acquires a hidden dependency |
| `parse.office.p50_ms` | 5 | ±20% | `nightly` | anydoc's 4.4 ms median at `timing_basis = in_process`, re-measured by us (§1.1). A breach is either a driver regression or F2's marshal |
| `query.warm_p50_ms` | 180 | ±20% | `nightly` | under G10's 250 ms ceiling, with the five Channel budgets summing to 210 ms. `ow route lint` refuses a `channel_ms` sum ≥ `query_ms` at config load, so this budget cannot be breached by configuration alone |
| `store.bytes_per_block` | 660 | ±10%, **ratchet** | `nightly` | a ratchet: it may fall and never rise. Set at ~2× the measured 338 B/Block and below the pessimistic synthetic corpus's 912 B/Block, so it is neither a rubber stamp nor a number the first real 10-K breaks |
| `rss.gen5000p_peak_bytes` | 1,610,612,736 (1.5 GiB) | +10%, one-sided | `nightly` | the S4 worker of the driver the catalog resolves for `gen_5000p_pdf` — `parse.pdf.pdfium` on the shipped roster, since anydoc refuses a PDF; a card whose `memory_mb` sits under the row makes it unreachable for that driver. **Not** the anydoc fork trigger: that is `rss.office200_peak_bytes` in `eval/perf.toml` — 1.5 GiB, +10% one-sided, `nightly` — the peak of `parse.office.anydoc`'s worker over `fixtures/office-200` (F2), which **fires `vendor/anydoc/FORK-TRIGGER.md`** because anydoc marshals eagerly into Python objects and `py.detach` does not cover the marshal. Every `rss.` row is a one-sided ceiling, `value × (1 + tol_pct/100)`; the ± is a width, never a lower bound ([ADR-13](adr/0013-v01-acceptance-reconciliation.md) D13.2) |
| `rss.merged4mcell_peak_bytes` | 4,294,967,296 (4 GiB) | ±10% | `nightly` | the pathological-XLSX envelope, bounding a **worker** process (§4.4 works out why it can only be a worker's, and what the operator does about it) |
| `wal.bulk_index_peak_bytes` | 2,147,483,648 (2 GiB) | **±512 MiB, absolute** | `nightly` | **absolute, not a percentage**, because a percentage of a growing number is not a bound: codegraph measured **5.9 GB of WAL against a 340 MB DB**, then 22 GB and exit 137 |

Four counters gate alongside them, from `eval/counters.toml`, and they catch what no clock can:

| counter | class | tolerance | the defect it catches |
|---|---|---|---|
| `cache_misses` | `exact` | ±0 | graphrag's permanent silent 100% cache miss — a run that is correct, slow and expensive with no error anywhere in it |
| `rebilled_units` | `exact` | ±0 | a free re-run that re-billed a paid operator. I4's ownership rule broken here costs money, not correctness, so nothing else notices |
| `tokens_out` | `ratchet` | 2% | a prompt or retry change that quietly widened output |
| `store_rows_read` | `ratchet` | 5% | a lost index or a plan flip. ST17 pairs with it: `ow store explain --golden` is byte-diff gated like G6 |

**Why counters, and not the clock, are the primary regression signal.** *Time as the primary signal
is rejected*: a silent re-render, a re-billed free operator and a 100% cache miss are the three
regressions that cost the most and move no clock at all — the first two because the extra work is
proportional to a corpus nobody re-times, the third because the machine simply does what it always
did. The clock is the confirming signal, not the detecting one.

### 2.5 Reconciling the two tail multiples

Two numbers describe a `PAGE` call's tail and they disagree by 1.42×. Both are printed because the
disagreement has a direction and the direction is correct:

```text
the reservation multiple, 05 §10.1's trace
  estimate per part                        854 micros
  reserved per part                      2,732 micros
  ratio                                      3.20      -> reserved gpu_ms = 2,400 x 3.2 = 7,680

the observed tail, surya's published table (R, a different model)
  RTX 5090, concurrency 128     p95/p50 = 42,538 / 18,915 = 2.249
  Apple Silicon, --parallel 8   p95/p50 = 129,173 / 59,313 = 2.178
                                                     -------
                               a decode-bound VLM's tail is ~2.2x its median
```

**A reservation is held, not spent, so over-reserving costs headroom and under-reserving costs a
`Degradation` mid-document.** `tokens_out_p95_multiple` is author-declared and
`ow drivers check` **fails an understatement**, so the shipped `parse.page.*` cards declare **3.2**
and not 2.25: 1.42× of deliberate conservatism on a number whose only failure mode in the
conservative direction is a smaller in-flight window. The anydoc card's `1.0` is correct for a
`constant`-shape free driver whose output size does not vary with input, and is not a default any
`PAGE` driver may inherit.

### 2.6 The laptop deadline collision — a defect, not a preference

B13 is the sharpest row in §2.2 and it falls outside every budget in §2.4, so it is stated on its
own:

```text
ow-laptop-1, surya-650M, --parallel 8    (the SMALLEST page model with a published number)
  p50 per-request wall                   59,313 ms
  p95 per-request wall                  129,173 ms
against the shipped isolation defaults
  [isolation] progress_ms                15,000 ms   <- the no-PROGRESS deadline
  [isolation] wall_ms_hard              120,000 ms   <- SIGTERM then SIGKILL
                                        ----------
  p50 is 4.0x progress_ms.  p95 is 1.08x wall_ms_hard.
and the driver omniweave actually ships is 7B, i.e. 12.8x the per-page work of this one.
```

Two consequences, and both are requirements rather than observations:

1. **A `parse/1` driver serving the `PAGE` rung MUST emit `PROGRESS` frames at ≤ `progress_ms / 3`
   intervals** for the whole duration of an outstanding model call. Frame 8 (`PROGRESS`,
   `{invoke_id, unit_index, done, total}`) resets `progress_ms`; a driver that blocks on one HTTP
   request without emitting it is SIGTERM'd at 15 s on Apple Silicon and never reaches
   `wall_ms_hard` at all. This is a conformance obligation on the `capability` suite, not advice.
2. **`wall_ms_hard = 120_000` is breached by ~5% of pages on `ow-laptop-1` even with the smallest
   available page model.** A killed page retries, and a retry of a `local_compute` GPU call re-pays
   the whole page's `gpu_ms`. At corpus B's 8,000 pages that is ~400 pages of duplicated work per
   run, and the retry has the same 5% chance of dying again. **`--max-rung decode` therefore becomes
   the default when no accelerator probe passes** — implemented as a `GATE` modifier clamping
   `max_cost_class` to `free`, by exactly the mechanism `gate.watcher-may-not-bill` already uses, so
   the outcome is a `Degradation` naming the knob and a `Coverage gap` with the command that clears
   it, never a silent refusal and never a 21-hour run that ends in retries. P-Q4 is the decision
   record; this is its pre-committed answer.

## 3. Scaling envelopes

Four steps. The corpus mix is the charter's reference mix scaled — **70% office (document grain),
25% born-digital PDF, 5% scanned PDF, mean 12 pages** — applied as expectations rather than integers
so the 10-document column stays on the same mix as the others.

**Two rates, printed rather than hidden.** [07](07-store-and-retrieval.md) §4.3's planning rate is
**90 Blocks/page** (the midpoint of F1's 60-120 envelope); the charter's own 100k reference ingest
resolves to **~67 Blocks/page** (80M Blocks over 1.2M pages), i.e. its corpus was 26% lighter than
the midpoint. Every row below that depends on the Block count carries both, because a projection
with one number hides its own error bar and F1 is the framework's largest open envelope.

**Pages and routed parts are different counts and the difference is 2.8×.** Office is
document-grain: one `route_decision` for the whole document, no matter how many pages it lays out
to. Blocks scale with pages; the routing ledger, the `work` table and the escalation count scale
with routed parts. The draft that conflates them overstates the ledger by 2.8× and understates the
Block count by the same factor.

### 3.1 The four steps

| | **10 documents** | **1,000 documents** | **100,000 documents** | **10,000,000 documents** |
|---|---|---|---|---|
| pages (layout grain) | 120 | 12,000 | 1.2M | 120M |
| routed parts (`route_decision` units) | 43 | 4,300 | **430,000** | 43M |
| Blocks, at 07's 90/page planning rate | 10.8k | 1.08M | **108M** | 10.8G |
| Blocks, at the charter's measured 67/page | 8k | 804k | **~80M** (charter) | ~8G |
| Segments, at ~30 Blocks each (planning rate) | 360 | 36,000 | **3.6M** | 360M |
| `work` rows, at the reference ingest's 8.46 per document | ~85 | ~8,460 | **846,400** | ~85M |
| `.owstore` @ 338 B/Block on the charter's Block count | 2.7 MB | 272 MB | **~26 GB** (charter) | ~2.7 TB |
| `.owstore` @ 660 B/Block on the planning Block count | 7.1 MB | 713 MB | **71 GB** | ~7.1 TB |
| ⇒ **provision** (×1.25 free pages + 64 MB WAL) | 9 MB | 891 MB | **89 GB** | ~8.9 TB |
| CAS at `retain_parts = "when_citable"` (≈ ×1 the store) | ~7 MB | ~713 MB | **~71 GB** | ~7.1 TB |
| routing ledger, ~960 B/decision before the 30-day sweep | ~41 KB | ~4 MB | **~850 MB** (charter; see below) | ~85 GB |
| events, ~180 B/event × 8 per `work` row, deflated ~8.7× | ~14 KB | ~1.4 MB | **~140 MB** | ~14 GB |
| escalated parts (scanned + 18.8% of born-digital) | 12 | 1,164 | **116,400** | ~11.6M |
| ingest wall, `ow-bench-1`, `--max-rung decode` | **~4 s** | ~2.2 min | ~3.6 h | out of envelope |
| ingest wall, `+ ow-gpu-1`, `parse.page.olmocr` | ~6 s | ~5 min | **19-52 h** (F7 band, `C_eff ∈ [1.5, 4]` over 77.6 GPU-h of work) | out of envelope |
| ingest wall, `ow-laptop-1`, `parse.page.olmocr` | ~2 min | ~3.1 h+ | not attempted (§2.6) | out of envelope |
| supervisor peak RSS | ≤ 600 MB | ≤ 600 MB | **≤ 600 MB** (G22) | ≤ 600 MB per shard |
| warm query p50, four Channels | ~12 ms | ~35 ms | **`degraded`** — §3.4 | ~150 ms (T4, ~10 shards + `federate_ms = 40`) |
| **the component that binds on ingest**, `parse.page.olmocr` enabled (C2/C3) | **cold start and the driver probe** | **the VLM** | **the VLM** | **the store: SQLite is out of envelope** |
| **the component that binds on ingest**, `--max-rung decode` (C1) | cold start and the driver probe | **the writer**: 12,000 serialised `end_page` transactions at 6 ms (§6.3) | **the writer**: 1.2M `end_page` transactions ⇒ **~2.0 CPU-h**, serialised (§3.4) | **the store: SQLite is out of envelope** |
| **the component that binds on query** | nothing | nothing | **the lexical Channel's 50 ms budget** | **the store** |

**The GPU ingest wall is one number, and §3.4 derives it.** §3.4 prices the same 77.6 GPU-h of work at
the same band and the two now agree. An earlier revision of this table printed **19-77.6 h**, whose
upper bound silently set `C_eff = 1.0` — outside F7's own declared `[1.5, 4]` — when the band's own
arithmetic is 77.6 GPU-h ÷ 1.5 = **51.7 h**, rounded to 52.

**The ledger row does not reconcile, and the discrepancy is named.** [05](05-ingest-and-routing.md)
§6.6 prices a `route_decision` with its deduplicated `route_evidence` and `route_spend` at ~960 B,
falling to ~360 B after the 30-day evidence sweep. The charter's ~850 MB at 100k documents therefore
implies **~885,000 decisions**. My own decomposition gives 430,000 parse decisions + 116,400
escalations + one document-grain decision per enabled free graph lane (seven lanes × 100,000 =
700,000) = **~1.25M decisions ⇒ ~1.2 GB**, which is 1.4× the charter's figure. The charter's number
is reproduced above because it is the binding one; **P-Q7 resolves which decomposition is right**,
and the answer changes a provisioning number by 350 MB per 100k documents.

### 3.2 Ten documents — the bottleneck is the process, not the corpus

At 10 documents the corpus is noise and the fixed costs are everything. Seven office documents
decode in 31 ms and three PDFs in 288 ms; the wall time is `ow --version`'s 118 ms plus discovery's
15.3 ms plus, on a first run, one **Capability probe** per enabled driver at
`probe_timeout_ms = 2000`.

**Mitigation, and it is the only one that matters at this size:** the probe verdict is cached per
run **and persisted 24 h per `(driver_id, driver_version, card_sha256, env_digest)`** in
`$OMNIWEAVE_HOME` — four components, and `env_digest` is the only name for the environment half
([ADR-7](adr/0007-driver-resolution-keys.md) D7.2; there is no `host_fingerprint`). Without
that persistence, thirteen drivers × a 2 s worst-case probe is a 26 s first query on a corpus that
parses in 319 ms. With it, the second invocation pays 0 ms of probe. The acceptance criterion for this
whole regime is `first_answer_seconds ≤ 600 s` over 100 born-digital office documents on a 4-core
machine with no GPU, offline after install ([00](00-vision.md) V01-15) — and that budget is
dominated by `ow install` and the wheel download, not by parsing, which is why V-Q2 splits it into
`install_seconds` and `first_answer_seconds`.

The second-order binder is the **serve packing tier**: below 5,000 indexed Blocks the tier is
`[5000, 12000, 4, 3500, 1, false, false, false]` — 4 documents, 3,500 chars each, one call,
`meta_text` **off**. Meta-text is gated off on small corpora because prose is overhead when one call
is the whole story. Note the tier keys on **Blocks, not documents**: ten spreadsheet-heavy documents
can be 40k Blocks and land two tiers up, which is why the tier boundaries are re-keyed onto Block
counts (F20).

### 3.3 One thousand documents — the VLM arrives, and the writer is the CPU floor

```text
escalated = 50 scanned docs x 12 parts             =   600
          + 18.8% x (250 born-digital x 12)        =   564
                                                     -----
                                                     1,164

GPU wall, ow-gpu-1, olmocr-7B  = 1,164 x 2.4 s / C_eff, C_eff in [1.5, 4]  = 12-19 min   (F7)
GPU wall, ow-gpu-1, surya-650M = 1,164 / 5.35 pages/s                      = 218 s       (R)
GPU wall, ow-laptop-1, surya   = 1,164 / 0.108 pages/s                     = 3.0 h       (R)

CPU, single-threaded
  office decode        700 x 4.4 ms                                        =     3.1 s
  pdfium decode      3,600 x 8 ms                                          =    28.8 s
  FREE signals       4,300 routed parts x 2 ms                             =     8.6 s
  LOCAL renders      ~1,400 deferring parts x 16 ms                        =    22.4 s
  free derive       36,000 segments x 4.2 ms                               =   151.2 s
                                                                             ----------
                                            parallelisable, at max_workers=4    53.5 s

  end_page commits  12,000 pages x 6 ms                                    =    72.0 s
  work transitions   8,460 x 0.45 ms                                       =     3.8 s
                                                                             ----------
                            SERIALISED on the single store.write lock          75.8 s

  ingest wall, --max-rung decode  = 75.8 + 53.5                            =   129 s = 2.2 min
```

**Two bottlenecks, and the second one is the interesting one.** The GPU is the headline: 12-19 min
of olmocr against 2.2 min of all CPU work combined, and on `ow-laptop-1` it is 3.0 h against the
same 2.2 min. But **59% of the CPU wall is the single writer**, not the parsers — `end_page` commits
and `work` transitions serialise on one cross-process `store.write` lock, so adding workers past 4
buys nothing on this mix. That is [07](07-store-and-retrieval.md) §12.4 item 6 arriving three orders
of magnitude earlier than the shard-count discussion, and it is why B22 and B23 are gated rows. *(Build note, D837: the claim B22 prices was O(claimable). `work_claimable` leads on `cost_class`, which the shipped narrow `claim` never constrains, so each claim scanned and sorted the claimable set twice: 14 ms at the 50,000-row `queue_high_water` (D190). `0004_runtime.sql` adds `work_claim_head (priority DESC, dispatch_key, id)` and `work_claim_key (dispatch_key, priority DESC, id)`, both partial on the claimable statuses, and the claim seeks them: 0.28 ms at the same depth. G22 went from 81 to 504 transitions/s and from 1,626 s to 217 s. It is still under 2,000, because a NULL `dispatch_key` is claimed one row per statement (D191), which is a ruling this document owes.)*

**Mitigations, in the order they are applied.** (1) Per-page routing has already cut 3,000
born-digital parts to 564; a document-level OCR boolean would send all 3,600. (2) `Coalescing` in
the model server merges across worker processes within `batch_wait_ms = 5` up to `max_batch = 8`,
claimed at 1.5-4× and **measured nowhere** — F7, with `ow bench service` as the instrument.
(3) `--max-rung decode` refuses escalation entirely and reports the 600 scanned pages as a
**Coverage gap** with the exact command that clears it, which is the correct answer on a laptop.
(4) On the writer, group commit: F8's pre-committed widening from zero-derived-row transitions to
same-operator batches, which is the knob that moves the 75.8 s. *(Build note, D919: a user ruling of 2026-10-22 kept F8's narrow form, the 08:2600 window over zero-derived-row transitions of one operator, and did not widen to same-operator batches with derived rows. On `op.identify` it took G22 from 870 to a median of 2,651 transitions/s at 100,000 units over seven runs, two of them under 2,000, measured on a developer machine and not `ow-bench-1`.)*

The second-order binder at this size is **`op.resolve`**: 1,000 documents at ~40 entities each is
40k entities, and `entity_band` construction at B41's 0.2 ms/entity is 8 s. That is fine. It is also
the number that becomes 300 s at 1.5M entities, which is F15.

### 3.4 One hundred thousand documents — where two ceilings disagree

The charter measured this ingest and this document reproduces it so a reader does not hold two files
open. `70k office (document grain) · 25k born-digital PDF · 5k scanned PDF · mean 12 pages`:

| item | figure |
|---|---|
| `unit` roster | 100,000 rows × ~220 B = **22 MB** |
| `work` rows | 100,000 `op.identify` + 430,000 parse (70k office parts + 360k PDF parts) + 116,400 escalation + 200,000 derive/embed = **846,400** × ~250 B with indexes = **~210 MB** |
| claimable at any instant | ≤ `queue_high_water` = **50,000** |
| time to first parsed document | the roster streams; **there is no planning phase** — **< 5 s** |
| office decode | 70,000 × 4.4 ms = **~5 CPU-min** |
| routing signals, FREE tier on clean pages | 430,000 × ~2 ms = **~14 CPU-min** (the charter's ~27 min assumes ~2× the signal set on the escalating population) |
| free `derive` over 3.6M Segments | 3,600,000 × 4.2 ms = **~4.2 CPU-h**, parallel across `max_workers` at §6.3's per-Segment rate |
| `end_page` commits | 1,200,000 pages × 6 ms = **~2.0 CPU-h**, **serialised on the single writer** — the CPU floor under `--max-rung decode`, and the component §3.1's C1 binder row names |
| VLM, `parse.page.olmocr` | 116,400 pages × 2.4 s = **77.6 GPU-h** of work; **19-52 h** of wall at F7's 1.5-4× band |
| billable band | **$23-$80** (olmocr's `<$200/1M pages` against a recorded 3.4× spread); §6.1 derives **$99** from the pricebook and reconciles the three |
| `.owstore` | ~80M Blocks at 338 B ⇒ **~26 GB**; 108M at 660 B ⇒ **71 GB**; provision **89 GB** |
| routing ledger | **~850 MB** falling to ~360 MB after the 30-day evidence sweep — see §3.1's unreconciled 1.4× |
| events | ~846k × 8 × ~180 B, deflated ⇒ **~140 MB** |
| supervisor peak RSS | **≤ 600 MB**, CI-gated by G22 |
| runtime overhead | **≤ 0.5 ms/unit** |
| crash at hour 6 | claimed-with-expired-lease ∪ pending **is** the unfinished work; no checkpoint file exists to be wrong |

**The two ceilings disagree here, and this is the hard part of the whole document.** The charter's
honest ceiling is **~10⁷ parts on one host**; [07](07-store-and-retrieval.md) §12.5's honest ceiling
is **~10⁷ Blocks in one `.owstore`**. Both are true and they are not the same ceiling:

```text
100,000 documents, one host, one store
  routed parts        430,000        against the charter's ~10^7 PART ceiling   ->  4.3% of it
  Blocks           80M - 108M        against 07's ~10^7 BLOCK serving ceiling  ->  8-11x PAST it
```

**So the 100k reference ingest is an INGEST reference and not a SERVING reference, and the plan has
never said so.** The ingest completes comfortably: the queue, the roster, the supervisor's RSS and
the per-unit overhead are all inside their envelopes at 4.3% of the part ceiling. The resulting
store is 8-11× past the size [07](07-store-and-retrieval.md) §12.5 says a single `.owstore` serves
well, and what binds is **not** the vector cap:

1. **The lexical Channel's 50 ms budget** breaks "somewhere between 10M and 30M Blocks depending on
   term selectivity" ([07](07-store-and-retrieval.md) §12.4 item 4). At 80M Blocks it reports
   `UNAVAILABLE(timeout)`, which **forces `degraded` on every query**. This is the first binder and
   it is visible, not silent.
2. **`PREFILTER_MAX = 200_000` Blocks** is exceeded 400×, so the exact narrowing `TEMP` table is not
   materialised and the planner switches to an over-fetch factor `clamp(1/selectivity, 1, 64)`.
   *That is not a failure; it is a different, disclosed mode*, and `filter_starved` fires if
   post-filtering leaves fewer than *k*.
3. **`VEC_BRUTE_MAX = 250_000` Segments** is exceeded 10.8-14.4×, so the stdlib `vector.brute`
   backend refuses (`OW-S-022`). This binds **only if someone turned vectors on**; the shipped
   default is `vectors = "off"`, so it is third in line and not first.

**The mitigation is corpus partitioning, and it is a first-class mechanism rather than a workaround.**
`omniweave.toml [corpora]` is the registry, one `retrieve()` reads one store, and a surface asked to
span corpora issues N calls and rank-merges them with `fusion_kind = "rank_merge"` disclosed. A
100k-document deployment is **N stores of ≤ 10M Blocks each** — roughly 12 stores on this mix — which
is T4's federation shape reached by configuration at T1 rather than by a rewrite. The alternative
mitigations, each naming its knob: Bulk windows (B25, 2.0×) for the index build; the WAL valve at
`clamp(db_bytes/4, 256 MB, 2 GB)`, which on 26 GB resolves to the 2 GB cap;
`journal_size_limit = 67108864` for a 64 MB steady-state WAL; `work_compact_above = 5_000_000` for
the queue table; the FTS5 `'merge'` maintenance step, whose absence is the one degradation in
[07](07-store-and-retrieval.md) §12.4 caused by *not running maintenance* rather than by size; and
`Σ max_workers × memory_mb` checked against RAM with `ow doctor` **refusing** above 0.8× (§4.4).

### 3.5 Ten million documents — out of envelope, and the exit is named

Ten million documents at 12 pages is **1.2×10⁸ parts** — twelve times the charter's part ceiling —
**43M routed parts**, ~10.8G Blocks and ~8.9 TB of provisioned store. This is stated plainly rather
than projected: *100k × 300-page legal discovery (30M parts, ~7.5 GB of `work` rows) is already not
this design on SQLite.*

The exit is the point of making the store the distribution boundary, and
[07](07-store-and-retrieval.md) §12.2-12.3 and [00](00-vision.md) §2.4 own the tier definitions.
This document owns only the three numbers a capacity plan needs from them:

- **T3 (Postgres, same four protocols, zero Operator change).** The port is `Store` (4 methods),
  `Reader` (6), `DocSink` (11) and `GraphSink` (12) — **33 methods, not four** — and `claim()`
  becomes `FOR UPDATE SKIP LOCKED`. The migration cost is bounded by that count; the acceptance test
  is that `tests/store/` runs unmodified against both backends.
- **T4 (a fabric of shards).** Up to 65,536 shards × 2.81×10¹⁴ Blocks each, placed by
  `jump_consistent_hash(int.from_bytes(doc_key[:8],'big'), n_shards)`. A document never spans a
  shard and there are no cross-shard foreign keys, so the shard count is a provisioning free
  variable rather than a schema change. `block_id`'s 16-bit minting prefix ships at shard 0 from day
  one, at zero bytes, precisely so this cannot become a migration (F28).
- **Query latency at T4 is `query_ms` per shard plus `federate_ms = 40`.** The fabric never waits
  past `federate_ms`, so **p99 is bounded by a constant and not by the slowest shard** — the
  opposite of the usual fan-out failure. 10 shards × 10M Blocks is ~150 ms
  ([07](07-store-and-retrieval.md) §4.4); 120 shards for this corpus is the same ~150 ms, because
  the fan-out is parallel and the merge of 120 × k=20 items is microseconds.

**What breaks first on the ingest side if you stay on SQLite.** [07](07-store-and-retrieval.md)
§12.4 owns the retrieval-side list; these four are the write-side ones it does not:

1. **The single writer.** One `store.write` scoped lock across processes. §3.3 measured it as 59% of
   the CPU wall at 1,000 documents on the reference mix; it does not improve with scale.
2. **The `work` table's B-tree** at 85M rows and eight indexes. `work_compact_above = 5_000_000`
   moves completed rows to `work_done`, which is the mechanism, and its own compaction is a
   resumable migration through `work` because a `CREATE INDEX` at that size is a multi-minute
   synchronous scan.
3. **WAL write amplification**, because it scales with the *existing* database size and not the
   change size — codegraph's "small syncs on big indexes hurt most", measured as a 7-file
   incremental sync taking **2 minutes at 0-2% CPU**. This is the one that makes a *correct* system
   feel broken, and it is why B43 exists as a budget row.
4. **`PRAGMA incremental_vacuum`.** The 0.25 free-page ratio trigger on an 8.9 TB file is itself a
   multi-hour operation, and `VACUUM INTO` needs free space equal to the final file.

### 3.6 Performance under hostile input

Scale is not the only axis a budget dies on. Four adversarial shapes, each with the mechanism that
bounds it, because a limit that only exists in prose is not a limit:

| shape | what it attacks | bound | what the user sees |
|---|---|---|---|
| **fixed-cost amplification**: 100k one-byte files | the per-unit overhead, not the parsers. 846,400 `work` rows for ~0 bytes of content; B22's 0.45 ms × 846k = 6.3 min of pure scheduler | nothing caps it, and nothing should — the work is real. `ow bench scheduler` measures exactly this shape (1M synthetic units, no-op operator) so the overhead is a known constant rather than a surprise | a run whose `ow cost` is $0 and whose wall time is 6 minutes, with `runtime_overhead_ms` in the manifest naming the cause |
| **one page, millions of Blocks**: a 4M-cell sheet | the transaction, not the memory. Rules 3-5 of §4.2 hold the RSS; the commit is still one transaction and the WAL valve cannot help mid-transaction | `MAX_GRID_SLOTS = 4_000_000`, `MAX_BLOCKS_PER_DOC`, and `TABLE_SYNOPSIS_CELLS = 20_000` collapsing the *embedding* while every cell stays citable | `RESOURCE_LIMIT` naming the knob, plus `Diag(OW_TABLE_SYNOPSIS_ONLY)`. F29 is the open residue |
| **container recursion / a zip bomb** | the decode budget and the disk | `MAX_ENTRY_BYTES = 134_217_728`, `MAX_ENTRY_COUNT = 100_000`, the container recursion limit ([05](05-ingest-and-routing.md) §2.5), `MAX_ASSET_BYTES = 268_435_456`, and `effective = min(tenant_cap, declared, HOST_MAX)` | a refusal naming which knob would need raising. **Widening past a `MAX_*` is a fork, not a flag** |
| **a query designed to blow the plan**: 64 rare terms, no filters | the lexical Channel and the narrowing probe | `MAX_QUERY_TERMS = 64`, the per-Channel `budget_ms`, and `PREFILTER_MAX`'s `LIMIT cap+1` probe, which **proves** the set is too big rather than discovering it after the memory is spent | `UNAVAILABLE(timeout)` on the Channel that ran out, `degraded` on the `Verdict`, and the partial ranking it had |

**The concurrency case that has no bound yet, stated as such.** 16 concurrent read connections is
~1 GB of page cache (§4.1). Nothing in this document or the charter says what the 17th does.
[10](10-interfaces.md) owns the concurrency cap's value; the **behaviour** at the cap is this
document's requirement and it is a **refusal**: a request arriving above the cap gets
`OW-S-0xx`-class store-busy with host, pid and age, exactly as a second writer does, and never a
queue — because a queued query has already blown `query_ms` before it starts and would report
`degraded` for a reason the operator cannot act on.

## 4. Memory

### 4.1 The resident-set policy

| process or phase | ceiling | how it is enforced |
|---|---:|---|
| the supervisor ([08](08-runtime.md) owns its structure) | **600 MB** | I31 plus G22's nightly 100k-roster run. Semgrep bans `.read()` / `read_bytes()` on a source path outside `omniweave_core.blobs`; anything over `INLINE_MAX = 262_144` travels as a blob reference |
| one `subproc` worker | `card.isolation.memory_mb`, default **512 MB** | `RLIMIT_AS` on Linux, `RLIMIT_DATA` on macOS, a Job Object on Windows; a breach is `RESOURCE_LIMIT{memory_mb}` naming the knob |
| all workers together | **0.8 × RAM** | `Σ max_workers × memory_mb`; **`ow doctor` refuses** above it rather than letting the OOM killer decide (§4.4) |
| parse of a 5,000-page PDF | **1.5 GiB** | `rss.gen5000p_peak_bytes`, nightly, a one-sided ceiling at +10% over the parsing driver's worker; not the anydoc fork trigger, which is `rss.office200_peak_bytes` (ADR-13 D13.2) |
| merge of a 4M-cell sheet | **4 GiB**, in a **worker** | `rss.merged4mcell_peak_bytes`, nightly ±10%. §4.4 attributes it and prices the consequence *(Build note, D929: the fixture exists, `fixtures/gen/gen_4m_cell_sheet.py`, and its first measurement is against this budget. Through a real `ow add` with the office driver in a worker, peak worker RSS was 214 MB at 50k cells, 390 MB at 100k and 757 MB at 200k: ~3.7 KB a cell, so the card's `memory_mb = 1024` refuses from ~280k cells, and 4M cells would want ~14.7 GB, 3.6x this row. At 4M cells nothing gets that far: anydoc refuses the part on its own `max_xml_nodes = 2,000,000` in 12 s. F2's fork trigger and F29's sweep are where this goes; developer machine, not `ow-bench-1`.)* |
| one serve read connection | **64 MB** page cache + **≤ 4 MB** temp | `cache_size = -64000`, `temp_store = MEMORY`. The temp figure is the narrowing table at `PREFILTER_MAX`: 200,001 rows × ~12 B ≈ 2.4 MB of leaf pages, rounded up |
| concurrent serve readers | **~1 GB at the budgeted 16; up to ~17.4 GB at the shipped cap** | 68 MB each (§4.1's page-cache + temp row). The **budgeted** figure is 16, which is what `ow bench query` runs and what the ~1 GB number prices. The **shipped cap** is `[serve] max_sessions = 64` × `SESSION_LIMITS`' 4 corpora per session = 256 readers ([10](10-interfaces.md) §10), which is 256 × 68 MB ≈ 17.4 GB — a file-descriptor argument (768 of 1,024) that was never a memory argument. `ow doctor` refuses above `0.8 × RAM` on **workers** and prices no readers, so nothing catches it today. **R-Q6** ([16](16-roadmap.md) Open questions) is the measurement, at N ∈ {1, 8, 32, 128}, and until it runs an operator raising `max_sessions` past 16 is spending unbudgeted RSS |
| the `mmap`'d `vec` sidecar | **27.2 MB, mapped once, shared** | `mmap_size = 268435456`; not per-query, which is the whole point of a segment layout |
| a resident 7B VLM engine | **20-40 GB VRAM** | `[services.*] keep_alive_s = 300`. **F37 is open**: if that residency blocks the next interactive command, `keep_alive_s` drops to 0 for `trigger.kind in {cli, hook}` and stays 300 for `watch`. Note this does not fit `ow-gpu-1`'s 32 GB at the top of the range (§1) |
| the event queue | **64k entries, drop-oldest** | the drop count is a `Degradation`, not a log line |
| the `retrieval_event` queue | **4,096 entries, drop-oldest** | flushed on a 2 s timer and at exit, **never** inside the read snapshot and never on the response path |
| the `array('i')` CSR for Louvain | **~64 MB at 8M edges** | two `array('i')` buffers of `E` and `V+1` int32 entries from one SQL scan. The one place omniweave allocates a flat typed buffer, deliberately (§4.5) |

### 4.2 Streaming and lazy-loading rules

Seven rules. Each has an enforcement mechanism, because a memory rule held only by discipline is not
held.

1. **The supervisor holds no document bytes.** I31, plus the semgrep ban above. This is the rule that
   makes the 600 MB ceiling independent of document size and therefore independent of corpus.
2. **`Doc` is a lazy handle, not a loaded object.** There is deliberately no `Doc.pages: list[Page]`
   and no `Doc.blocks: list[Block]`; every traversal returns an iterator. `Doc`, `Grid` and
   `Evidence` are deliberately **not** dataclasses, because freezing a handle would say something
   false about what it holds.
3. **The write path is resident for one page.** The driver emits `owdoc-fragment/1` NDJSON, the host
   reads it **line by line**, buffers one page's `BlockDraft`s, and `end_page()` commits one
   transaction. Peak resident state is one page of drafts plus the tmp-id map for the current page:
   at 120 Blocks/page and ~1.1 KB per materialised draft that is **~132 KB**
   ([03](03-document-model.md) §13.5 shows the 1.1 KB arithmetic). A 5,000-page document never
   exists in memory.
4. **The read path is resident for one Frame.** A Frame is **block-count-bounded** at a target of
   8,192 Blocks — *deliberately not a page range*, so a page with 400,000 Blocks is harmless — and
   its decode budget is B33's 45 ms. That bound is `blocks/page`-independent by construction but
   **not** F1-independent: B33 prices 8,192 Blocks *decoded into frozen `Block` instances*, so the
   45 ms moves with **`bytes/block`**, the second of F1's two variables, and `store.bytes_per_block`
   is the nightly ratchet that catches it. Rule 1's 600 MB ceiling is independent of **both**,
   because the supervisor holds no document bytes at all.
5. **Every read boundary is `take(N+1)`-then-check.** A limit is never discovered *after* the memory
   is spent. This is what turns `MAX_GRID_SLOTS = 4_000_000`, `MAX_MENTIONS_PER_DOC = 250_000`,
   `MAX_ITEMS_PER_SEGMENT = 2048` and `PREFILTER_MAX = 200_000` from documentation into enforcement.
6. **`entity_band` is persisted, never an in-memory index.** 128-permutation signatures for 1.5M
   entities is **~1.3 GB of RAM** (1.5M × 128 × 8 B for the min-hash row alone), and it is rebuilt
   whenever `graph.resolve_signature` changes and checked at the top of every resolve pass.
7. **The vector sidecar is contiguous segments, never a row per vector.** `vseg` holds
   `n × 16 B` digests and `n × 96 B` signatures at `VSEG_SIZE = 4096`. A row-per-vector layout costs
   **2.3×** a segment layout in pure SQLite cursor overhead (1,072 ms vs 466 ms per million), and
   storing float vectors as BLOBs in the main `.owstore` churns the writer's B-tree, WAL, backup and
   `VACUUM` at ~3.2 KB per Segment.

### 4.3 The largest single document, and how it is handled

Two named worst cases, and they fail in different directions.

**A 5,000-page PDF.** 300k-600k Blocks at the 60-120 Blocks/page envelope, ~200 MB of `.owstore`,
~45 MB as a `.owdoc`. It is handled by rules 3 and 4 above: one page resident on write, one Frame on
read, and `staged_gen` so a crash after page 3,000 leaves 3,000 committed **invisible** pages and a
claimable `work` row rather than a torn document. The peak-RSS budget is 1.5 GiB, and the reason it
is that high rather than the ~132 KB rule 3 implies is anydoc's eager marshal into Python objects,
which `py.detach` does not cover — F2, with `ow bench inproc` as the instrument and a fork trigger
as the fallback. **The wall-time check:** 5,000 pages × B04's 8 ms is ~40 s of decode against
`[budget.per_unit] wall_ms = 600_000`, so the decode budget is 6.7% of the per-unit wall — and P-Q1's
pre-committed fallback is that a p95 above ~120 ms makes that 6.7% into 100% and forces a re-derive.

**A merge-free 4M-cell spreadsheet.** This is the document that broke every proposal, and the priced
answer is: **4,000,000 FTS rows, 4,000,000 citable Blocks, 1 embedding.** A table above
`TABLE_SYNOPSIS_CELLS = 20_000` collapses to **one synopsis Segment** carrying header rows,
dimensions, eight sampled rows and per-column type/range, plus `Diag(OW_TABLE_SYNOPSIS_ONLY)`. Every
cell stays individually citable; only the *embedding* collapses. The peak-RSS budget is 4 GiB in a
worker.

**The residue, stated because it is real.** One page holding millions of Blocks is still **one
transaction**: a 4M-cell sheet is a multi-GB WAL and a multi-minute commit that will trip
`loop_lag_max_ms = 250`, and **the WAL valve cannot help mid-transaction** because its release
condition is a full backfill. Generation staging fixed the 5,000-*page* case; this one is narrower
and open (F29). The pre-committed answer is `MAX_BLOCKS_PER_DOC` and a `RESOURCE_LIMIT` refusal
naming the knob — a sub-page commit boundary complicates the `work` table's unit and adds a fourth
span level, and is not granted speculatively.

**F29's spike, specified.** The ~2.8 GB WAL and ~23 s commit that
[03](03-document-model.md) §14.1 prints for this fixture are **estimates**, and every constant that
would bound the case is set from them rather than from a measurement. The spike builds the
merge-free 4M-cell fixture (§7.2) and runs `ow bench rss` with commit instrumentation over a
**cell-count sweep at 0.5M / 1M / 2M / 4M / 8M cells on one page**, reporting per point: peak WAL
bytes against `wal.bulk_index_peak_bytes = 2 GiB ± 512 MiB`, the `end_page` commit wall against
`loop_lag_max_ms = 250`, and peak worker RSS against `rss.merged4mcell_peak_bytes`. The answer it
must produce is **the cell count at which the first of those three breaches**, which is the real
ceiling and is what a refusal constant should be set from. It runs **before** P2's migration
sequence, because 91 tables share one strictly-ordered sequence and a fourth span level is a
migration. **A pessimistic answer moves two constants, not one:** `MAX_BLOCKS_PER_PAGE` admits
this fixture with 4.9% headroom and `MAX_GRID_SLOTS = 4_000_000` does not fire at exactly
4,000,000 cells, so a page admitted by one and unbounded by the other is the shape of the
failure. [03](03-document-model.md) §14.1 owns both constants and that arithmetic; this document
owns the instrument, and it did not exist.

### 4.4 The `max_workers` / `memory_mb` tension, resolved

This is the one arithmetic collision in the memory model and it is worth spelling out because two
shipped defaults produce it.

```text
ow-bench-1 RAM                                            16 GiB
[drivers] max_workers = { free = 4, local_compute = 4, billed_api = 8 }
                                                          16 worker processes
ow doctor refuses above                                   0.8 x 16 GiB = 12.8 GiB
=> the largest memory_mb that passes at 16 workers        12.8 GiB / 16 = 800 MB
but rss.merged4mcell_peak_bytes                           4 GiB
```

**The resolution: the 4 GiB figure is a *worker* peak, not a supervisor peak, and a driver that can
reach it declares `memory_mb = 4096` on its card.** `ow doctor` then refuses 16 workers at that size
on a 16 GiB machine and prints the arithmetic, and the operator lowers `max_workers` for the class
that hosts the driver — to 3 for that class, since `12.8 GiB / 4 GiB = 3.2`. That is the intended
behaviour: **a refusal with the numbers, before the run, rather than an OOM kill at hour six.** It
also explains why `memory_mb` defaults to **512** on the shipped anydoc card rather than to something
generous — the default has to be a number sixteen of which fit.

**Extends the charter (new decision).** The charter states `rss.merged4mcell_peak_bytes` without
saying which process it bounds. It is the **worker** process, because I31 already caps the supervisor
at 600 MB and forbids it from holding document bytes, and the grid merge reads document bytes.

### 4.5 Arenas and pooling — the decision is "no", and here is what is pooled instead

**There is no arena allocator and no object pool for model types, and that is a decision, not an
omission.** `Block`, `Segment` and every other model type is a frozen `slots=True` dataclass: 56 +
8×N bytes with no `__dict__`, which is already within ~15% of what a pooled layout could achieve. A
pool of *frozen* objects cannot be reset in place — you would have to unfreeze the model to pool it,
which forfeits INV-1's single-representation property and every digest that depends on it. CPython's
own free lists already cover the allocation pattern (many short-lived same-size objects), and
`omniweave-core` is stdlib-only, so there is no numpy arena to borrow.

What omniweave pools instead, and each because it amortises something expensive:

| pooled thing | size | what it amortises |
|---|---|---|
| the SQLite page cache | 64 MB per connection | B-tree page reads; SQLite's own pool, not ours |
| the **worker process** | `worker_idle_ttl_s = 300` | the model load, the driver import, and the `subproc` fork/exec of B03 — the single largest fixed cost in the pipeline, at 21× the in-process call it wraps |
| the `mmap`'d `vec` sidecar | 27.2 MB, shared | one map, N queries |
| the bounded event queue | 64k entries | allocation churn on the hot path; drop-oldest, and the drop count is a `Degradation` |
| the `stderr_tail` ring | 8 samples + a 4-line tail | unbounded child stderr, which is how a subprocess wrapper acquires an OOM |
| the `array('i')` CSR for Louvain | two flat int32 buffers, ~64 MB at 8M edges, from one SQL scan | **the one place omniweave allocates a flat typed buffer rather than objects**, deliberately, because a Python object per edge at 8M edges is ~450 MB and not affordable |
| the compiled `RoutePolicy` | memoised | B06's 50 µs assumes the policy is already compiled |
| the `plan()` result | memoised on `(mode, channel set, filter-field set, policy_digest, caps_digest)` | planning is pure, so memoising it is free and correct |
| the Capability probe verdict | per run, plus 24 h per `(driver_id, driver_version, card_sha256, env_digest)` | §3.2: thirteen drivers × `probe_timeout_ms = 2000` is a 26 s first query without it |

The one buffer discipline that is load-bearing rather than an optimisation: `serialize()` returns
`(str, SpanMap)` — **the text and its map in one pass**. A two-pass implementation would build the
text, throw away the offsets, and re-derive them, which is both slower and the exact place a
byte-exactness claim goes wrong.

## 5. Efficiency techniques, each with its saving

Fifteen techniques. Where the saving is measured, the source is named; where it is derived, the
arithmetic is shown; where a technique was **rejected**, its number is still printed, because a
rejected optimisation with a number is a decision and a rejected optimisation without one is a
prejudice.

### 5.1 Per-page routing — derived 13.4× on the reference document

The unit of routing decision is the **part**, not the document. On the 188-page born-digital 10-K
with 12 scanned exhibits (the document docling structurally cannot route, because `do_ocr` is a
document boolean), from [05](05-ingest-and-routing.md) §10.1's full trace:

```text
escalated parts                     13 of 188                = 6.9%
GPU calls                           14 = 13 parts + part 47's REGEN
GPU wall                            14 x 2.41 s              = 33.7 s
spend                               14 x 858 micros          = 12,012 micros = $0.0120
under a document-level OCR boolean  188 x 858 micros         = 161,304 micros = $0.161
                                                               ---------------------
saving                                                         13.4x

and the alternative is payable under the shipped default, so the 13.4x is the whole argument:
  [budget.per_unit] micros = clamp(micros_base + micros_per_part x parts, 0, micros_max)
                          = clamp(4,000 + 3,000 x 188, 0, 16,000,000)
                          = 568,000 micros
  161,304 < 568,000, so a document-level OCR boolean would have been paid in full — it is
  simply 13.4x more expensive. The pre-S10 default (micros_per_part = 800, micros_max =
  250,000) made 154,400 bind at part 181 of 188, which was a defect and not an argument:
  see 05 section 4.4 and route lint check 13.
```

**13.4× is a single-document derivation, and the corpus band is 5.3× to 1.0×.** The multiple is
algebraically `1/escalated_fraction`, so it is a restatement of *this document's* 6.9% escalation
and it moves with the mix. §6's three corpora price the same substitution over a population and
print the band a budget decision actually faces:

| corpus | escalating fraction | document-level OCR boolean | per-part routing (C2) | multiple |
|---|---:|---:|---:|---:|
| the 188-page 10-K, one document | 6.9% | $0.161 | $0.0120 | **13.4×** |
| A — born-digital reports | 18.8% (P-Q3's planning rate) | $15.36 | $2.89 | **5.3×** (§6.3) |
| C — mixed enterprise | 32.3% of PDF parts | $3.07 | $1.02 | **3.0×** (§6.5) |
| B — scanned archives | **100%** | $7.03 | $7.03 | **1.0×** (§6.4) |

**On a pure-scan corpus per-page routing saves nothing, and that is the floor a reader must see.**
Every part escalates, so the part-grain decision and the document-grain boolean select the same
work and bill the same dollars — which is why §6.4 has no "the alternative" line to print. The
technique's value is *entirely* in the mixed document and the mixed corpus; the 6.9% figure is the
best case in the plan and not a representative one, and the 18.8% rate the corpus band rests on is
itself unmeasured (§6.8 clause 2, P-Q3).

**858 micros and 853.4 micros are two different numbers and both are correct.** 858 is
[05](05-ingest-and-routing.md) §10.1's **observed** figure at the observed `gpu_ms = 2,410`
(2,410 × 0.3556 = 857.0, rounded to 858 in the trace). 853.4 is the **planning** figure at the
card's declared p50 of 2,400 ms (2,400 × 0.3556). §6 uses 853.4 throughout, because a cost model
prices the declared p50 and not one trace's observation; §5.1 uses 858 because it reproduces that
trace line by line.

**INV-13 makes it structural, not advisory:** computing a `LOCAL_COMPUTE` signal, rendering a
raster, or starting a model server for a clean born-digital page is a reviewer-rejectable defect.
The mechanism is the **demand plan** — the compiler groups every reachable rule's reads by
`cost_class`, computes FREE first, re-tests, and pays for `LOCAL_COMPUTE` only if nothing has fired
— and on the 10-K, 164 of 188 parts never rendered a pixel because
`decode.blank-part-escape`'s deferral sits *later* in file order than the rule that matched.

**Sampling was rejected with its failure named:** a `{head, stride, cap}` sample produces a *wrong
prior* on precisely the mixed document that motivates per-page routing. A 40-page scanned appendix at
pages 2,900-2,940 of a 4,000-page report is missed by a stride of 32. Demand planning is exact and
costs less.

### 5.2 One LOCAL_COMPUTE render instead of one GPU call — derived 160×

When the FREE group is inconclusive, the escalation to `LOCAL_COMPUTE` is one 96-DPI grayscale
render at **15 ms of CPU** to decide whether to spend **2,400 ms of GPU**. On the 12 scanned exhibits
the render *confirmed* the escalation; on part 177 (a full-page photograph with an 84-character
caption) it triggered one, which is the known false positive and is exactly the evidence
`ow route propose` reads to raise `ink_coverage_min` for the slice `pdf/workiva/true/en`.

**`binarize = false`, always.** Ollama-OCR's 72-DPI-then-Otsu path destroys the antialiasing a
modern VLM was trained on — a "cheaper" preprocessing step that costs accuracy, which is the wrong
direction on both axes.

**The raster's own size, because it sets the `render` cache cap.** The glyph profile is
`short_edge_min_px = 1384`, `area_max_px = 6_291_456`. On A4 (aspect 1.414) that is
1,384 × 1,957 = **2.71 Mpx**, well under the area cap, and at 3 B/px RGB it is **8.1 MB** per page.
`[cache.max_bytes] render = 20 GiB` therefore holds **~2,500 glyph rasters** — roughly one
2,500-page scanned corpus — which is why `render` is the one cache layer a scanned-archive operator
raises first, and why re-render (15-40 ms of CPU) is the cheapest cache miss in the framework.

### 5.3 Deterministic-first extraction — and the honest state of its evidence

**Coverage ordering is `(cost_rank, phase)`, with `cost_rank` primary.** Every free pass precedes
every `local_compute` pass and every `local_compute` pass precedes every billed one, *whatever* the
phases say — which is what keeps a third party's free extractor able to preempt a paid one with no
core change. A billed pass then runs only over the residue that cheaper passes did not **Cover**,
gated by `llm_coverage_floor = 0.60`.

**The evidence, corrected.** The framing "graphify ties dense RAG at zero LLM build cost" **does not
survive its own source**, and the charter records the correction: `graphify/BENCHMARKS.md`'s LOCOMO
table lists the primary `graph-expand` configuration at **~$1.40 ingest cost**, against
`$0 (shared index)` for the dense-RAG and BM25 baselines. What survives is the accuracy claim —
**0.497 recall@10 on LOCOMO, 76% on LongMemEval-S, tying dense RAG** — and the structural argument
that deterministic extraction is *competitive on the metric that matters*, not merely cheaper. The
`vectors = "off"` default survives; that particular piece of evidence for it does not.

**So the saving here is a projection, and it is labelled one.** F13 is the measurement — the free
passes over ten real documents per class, plotting the `coverage_frac` distribution — and its
pre-committed fallback is unusually honest: *if the median outside structured corpora is below 0.2,
`llm_coverage_floor` becomes per-corpus and the economics section is **rewritten rather than
defended**.* §6 prices both branches, and §6.8 clause 1 prints the assumption.

The one free pass with a provable, non-projected yield: **`derive.anchor.defterm`** mints
abbrev/expansion aliases, and "IBM" versus "International Business Machines" scores far below the
Jaro-Winkler 92 threshold, so **the fuzzy funnel provably cannot catch that class**. On legal and
financial corpora that is the highest-yield free pass in the ladder.

### 5.4 The `call` cache layer — $99 per re-derivation on the reference corpus

Three of five cache tiers are "the store", which is correct for L2 and has a consequence nobody
costed before the charter: the only record of a VLM response was a `block` row, so **re-deriving
rows from that response meant paying for it again**. The correction is to cache the **driver's raw
response** and re-derive the rows from it in CPU microseconds. What that correction does and does
not buy has one statement, and this is it:

**The `call` layer does not survive a move to a second store.** `cache_index` is created by
`0004_runtime.sql` **inside** the `.owstore`, so a fresh store opens with an empty cache and every
`billed_api` response is billed again. What the layer does buy, all of it inside one store: a
re-parse at a new `producer.schema_version`; a `digest_recipe` bump re-derived as a re-digest pass
rather than a re-parse; an `ow index rebuild --derived`; and a re-run after a metadata-only touch
that leaves `unit.content_sha256` unchanged. On the 100k reference corpus that is 116,400 pages ×
853.4 micros ≈ **$99 not re-billed per re-derivation**. A machine-scoped cache sidecar under
`roots.cache` that would make the claim true across stores is **deferred and unfunded** — 2-3
engineer-weeks, its own GC and its own `--allow-rebill` path — and no plan document may assume it.

Two structural guards on it:

- **There is no `parse` and no `derive` cache layer.** If it is a row in the `.owstore` it is never
  also a blob in the cache (INV-1). The parse memo *is* `work.status = 'done'` ∧ a matching
  `work.cache_key` ∧ `doc(doc_key, gen)` present.
- **I27: an automatic sweep never deletes a `billed_api` entry.** `cache_ns` is a *partial* index on
  `cost_class = 'free'`; deleting a paid entry needs `ow cache prune --allow-rebill`, which prints
  the count and the `would_have_been_micros` it is about to discard. `[cache.gc] billed_after_days
  = 0` means **never**.

### 5.5 Binary quantisation — derived 96.7% storage, arrived at differently from LEANN

LEANN's headline is **97% storage reduction** — 201 GB → **6 GB** at 60M passages, ~100 B/node for
the pruned CSR graph against ~3.35 KB per stored float32 vector — achieved by *selective
recomputation*: the index stores a pruned graph and re-embeds every node on the search path at query
time. [07](07-store-and-retrieval.md) §9.4 owns the five-objection rejection of that mechanism as a
shipped mode; the decisive number is that at 1M Blocks the whole `sig_only` sidecar is 3.7 MB, so
recomputation trades 3.7 MB for a resident model server.

**omniweave takes the storage saving and rejects the mechanism.** The saving arrives instead from
**binary quantisation at `sig_bits = dim`**:

```text
storage = 'sig_only'
  16 B segment content_digest + 96 B signature (768 sign bits) + 0.125 B live bit
  + ~0.01 B amortised vseg row header                             = ~112 B / Segment
a stored float32 vector in a conventional vector DB               = ~3,350 B
                                                                    ------------------
reduction                                                           96.7%
```

That is arithmetically the same saving as LEANN's 97%, with **no query-time model load**. The
measured cost is the scan: **200,000 96-byte signatures in 81 ms** (CPython 3.11, XOR +
`int.bit_count()` + a 512-entry heap), extrapolating to ~406 ms/1M — within 15% of a cited 466
ms/1M, so `VEC_BRUTE_MAX = 250_000` (~101 ms, B28) is a **measured** ceiling and not a guess. Above
it the stdlib backend **refuses** (`OW-S-022`): *an honest refusal beats a five-second query nobody
warned you about.* `RERANK_N = 1000` exact f32 rerank recovers precision; F9 gates recall@10 ≥ 0.95
against exhaustive f32 on a fixed 50k fixture, and below that the backend ships `sig_full` only
(~3.2 KB/Segment) with a smaller ceiling.

### 5.6 Byte-offset retrieval — 20 µs against 42.8 ms, at 2× storage

A point read of one Block by `block_id` is a SQLite index seek at **20 µs** (B35). The comparison
that decided the at-rest format is **Parquet's 42.8 ms** for the same point read — a factor of
~2,000, which is why Parquet is `ow store export parquet` and not the storage engine.

The provenance half is `OriginSpan` plus the retained `part` in CAS. INV-10 makes
`part.store_ref IS NOT NULL` a **precondition** of `quote = 'verbatim'`, proved per driver by
re-reading the retained part on whichever of three branches the driver's `os_kind` selects
([03](03-document-model.md) §7.3 owns the three branches and their normalisation).

**The cost is printed:** `[store] retain_parts = "when_citable"` **roughly doubles corpus storage** —
§3.1's CAS row, ~71 GB at 100k documents on the planning rate — and CAS lives on the filesystem
rather than in the `.owstore` so `ow store stats` reports the two separately for exactly that
reason. F32 is the measurement, and its pre-committed fallback is that under ~20% achieved-exact,
retention becomes opt-in per corpus and `corpus_card.verbatim_fraction` prints the consequence
**before any query runs**.

**LEANN's offset map is the anti-pattern to name.** A pickled `dict[str, int]` at 10M entries is
roughly 1-1.5 GB of interpreter objects, loaded per shard at searcher construction. omniweave's
equivalent is `part` plus `block.os_a` / `os_b` in the same store with a covering index, which is
why B35 is 20 µs of disk rather than 1.5 GB of RAM.

### 5.7 Compact wire encoding — adopted as `owrows/1`, and scoped by a printed number

**omniweave ships a MUNCH-derived tabular encoding named `owrows/1`.**
[07](07-store-and-retrieval.md) §7.5 owns the envelope grammar, the six rules, the encoder registry
(`hit1`, `prov1`, `nb1`, `gen1`) and the `encoding = "auto" | "rows" | "json"` surface. This
document owns the numbers and the scope decision.

jcodemunch's MUNCH is measured against tiktoken `cl100k_base` over six tools
(`jcodemunch-mcp/TOKEN_SAVINGS.md`): **median 45.5%, mean 46.4%, min 39.4%, max 55.4%** of response
tokens. `owrows/1` inherits the mechanism, the 15% savings gate and the fail-open negotiation, and
**not the code** — jcodemunch is dual-licensed and the pattern is taken from the spec.

**Where it is refused, with the arithmetic that refuses it.** It never touches the MCP Answer:

```text
tier 3 packing budget                                    22,000 chars
structure: 8 docs x doc_overhead 180                    =  1,440
         + ~40 blocks x block_overhead 95               =  3,800
                                                           ------
                                             structure =  5,240 chars = 23.8% of the response
MUNCH's median saving applied to the structure only     =  2,385 chars
                                                           ------
saving on the whole Answer                              = 10.8%
```

**10.8% is not worth encoding a text document as a table.** The Answer is fixed as one content
block, a fixed section order, `ow:<name>` markers, no `outputSchema`, and ≤ 24,000 characters; its
payload is verbatim document text inside fences, which a tabular encoding cannot compress at all —
MUNCH's own lesson, since codegraph's responses are 90%+ code fences. `owrows/1` is therefore exposed
on the SDK and CLI structured paths only, where the consumer is a program and `hits` is 14 columns ×
20 rows of dense, prefix-heavy scalars.

**The savings figure is jcodemunch's, not ours, until measured.** `ow bench encoding` runs the
golden query set through all four encoders and publishes a per-encoder ratio with `n` and a
confidence interval against a committed floor in `eval/gates.toml` (F51). B36 is the encode cost, and
because `auto` measures before it emits, a below-threshold payload costs B36 and ships as JSON.

The savings that *are* taken at the Answer surface are structural rather than syntactic: the packing
tiers themselves, `TABLE_PROMOTE` (a `TABLE_CELL` hit never packs alone — without it one query
against a 4M-cell workbook returns forty thousand 12-character passages), and the **Emission
ledger**, which never re-delivers a Block already sent in this session, keyed
`(corpus_id, doc_key, gen, cite, content_digest)`.

The number that *does* transfer from jcodemunch is the **retrieval** one, not the encoding one:
**27.4× token reduction against a grep-top-3 baseline** over 15 task-runs across 3 repositories
(664,975 → 24,249 tokens), per-query range 7.3×-79.8×, median 25.5×. That is the saving `ow_query`
exists to deliver, and the repo is explicit that no single multiple describes every query — and that
its denominator is deliberately conservative, so the published multiples *understate*.

### 5.8 Caching, layer by layer

**One `cache_index` table for all five layers**, each row carrying the `Spend` that produced it so a
hit can **replay** the spend rather than reporting zero. One index, one GC, one bill.
[08](08-runtime.md) owns the six-clause read policy and the middleware order; the numbers below are
this document's.

| layer | what it holds | saving | bound |
|---|---|---|---|
| `blob` | content-addressed source and intermediate bytes | dedup by sha256 across the whole corpus | `[cache.max_bytes] blob = 100 GiB` |
| `call` | **a driver's raw response** | §5.4: the layer that makes a re-derivation of a corpus **within one store** cost CPU-seconds instead of a re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` lives in the store | `0` = unbounded, and `[cache.gc] billed_after_days = 0` = never swept |
| `embed` | a vector keyed on `segment.content_digest` | **identical text is embedded once corpus-wide** — a boilerplate clause repeated in 400 contracts is one forward pass | `0` = unbounded |
| `render` | a page raster at a declared profile | §5.2: 8.1 MB per glyph raster, ~15-40 ms of CPU per re-render | `20 GiB` ⇒ ~2,500 glyph rasters |
| `signal` | a `route_signal` row | re-deciding a part costs 0 ms of signal recomputation | `2 GiB`, and **F37 asks whether `signal_version` sweeping actually bounds it** |

Above all five: `min_free_bytes = 5368709120` (5 GiB). The GC refuses to let the cache grow the disk
below that, which is the bound that matters when four layers are individually capped and one is not.

**A hit consumes zero budget, zero tokens and zero rate-limit slots** (I25), enforced by the
middleware order: `with_cache` sits **outside** `with_budget`, so a hit returns before a reservation
is ever taken. Of the read policy's six clauses, **five are miss shapes a naive `if key in cache`
reports as a hit** — an unparseable entry (counted *and overwritten* on the next success), a partial
one, one failing `is_valid_nonempty`, a `(unit, part)` mismatch, and an older namespace under
legacy-allow — which is why the policy is the cache's business and not the caller's.

**Only the `semantic` projection of config enters a cache key.** `config_digest` is the full digest
and keeps its two other jobs (the run manifest and the full-scan latch). Classifying
`drivers.enabled` as semantic would **re-bill an entire corpus every time an operator enabled an
unrelated driver** — which is the failure this axis exists to prevent, pointed the other way. An
unclassified key **fails CI** (G18) and is treated at runtime as `semantic`: fail expensive, never
wrong.

**Free artefacts carry a producer-version namespace so an upgrade invalidates them. Paid artefacts
do not carry `driver_version`, so a bug-fix release never re-bills a corpus.** `prompt_fp` is hashed
after CRLF→LF and trailing-whitespace normalisation, *or every Windows checkout re-bills*.

### 5.9 Batching — two named sites, and the number that is missing

**Host Batch** ([08](08-runtime.md) owns the mechanism; the numbers are here). The set of claimed
rows sharing a `dispatch_key = sha256(driver ‖ config_digest ‖ isolation)[:16]`, sent in one
`INVOKE`, bounded by `card.isolation.batch_max_units = 32`. **Invisible to the work table, the spend
ledger, the trace and the failure taxonomy** (I24) — one `RESULT` per unit, 32 transitions for a
`batch = 32`, and batch identity is a *span attribute*. Adapted by AIMD:
`OOM | WORKER_DIED → max(1, batch // 2)`; `DRIVER_CRASHED → 1` for the retry, to localise the poison
unit; 20 consecutive clean → `min(batch + 1, batch_max_units)`. **Halve-and-never-recover was
rejected**: it lets one foreign process permanently cap a driver's throughput.

**Server Coalescing.** The model server's own merging, taken from surya's verified `_drain()`: block
for one job, coalesce within `batch_wait_ms = 5`, ceiling `max_batch = 8`. It merges across **worker
processes**, which host-side batching structurally cannot do.

**The gap, stated:** the Coalescing speedup ships as a **1.5×-4× band and is measured nowhere**
(F7). Every olmocr wall-time figure in §3 and §6 inherits that band, so capacity planning is
uncertain by up to **2.7×** until `ow bench service` runs 2,000 pages at `max_batch ∈ {1,4,8,16}` ×
`batch_wait_ms ∈ {0,5,25}` and reports throughput and `queue_p95_ms`. Note that B10's 5.35 pages/s
is not the missing number: it is a **different model's** already-coalesced figure at concurrency 128,
so it bounds the hardware and says nothing about olmocr's curve.

**What *is* measured is the shape of the curve, and it is why concurrency is derived rather than
constant.** On a B200, layout throughput 48→96 concurrency is **+28%** and 96→240 is **+5%**.
`MAX_AUTO_PARALLEL = 96` is therefore the cap *past the knee*, not a default, and
`refill_target(svc, cfg, ledger) = min(svc.capacity(), MAX_AUTO_PARALLEL, cfg.max_inflight,
ledger.headroom_units(svc))`. **A flat 96 on a 24 GB consumer card is an OOM, not the measured
+28%.**

**CPU-side batching is the largest single-lane saving in the framework and it is off the default
path.** B18 → B19 is 180 ms → 22 ms per Segment, **8.2×**, purely from batch 1 → 32; B19 → B20 is a
further 3.7× on a card. It is off the default path because `vectors = "off"`, which is exactly why
turning vectors on is a decision with a measured price rather than a checkbox.

### 5.10 Bulk windows and the WAL valve — measured 2.0× and 25×

[07](07-store-and-retrieval.md) §10.5-10.6 own both mechanisms, all eight valve properties, its
constants and the four subtleties. This document owns the two savings and the escalation:

| mechanism | saving | source |
|---|---|---|
| Bulk window (drop non-UNIQUE secondary indexes and FTS triggers) | **2.0× net** — 2.8 s → 1.1 s on a 224k-edge `INSERT OR IGNORE` stream, ~0.3 s to recreate | codegraph; B25 is the row |
| WAL valve (defer checkpoints during a bulk index) | **25×** — 19+ min → 45 s on HDD-class storage at 150 random IOPS, because default autocheckpointing is **~95% of all disk I/O** during a bulk index | codegraph |

**The escalation on both is in this document because it is a budget question.** `wal.bulk_index_peak_bytes`
is **absolute at 2 GiB ± 512 MiB**, not a percentage, because the failure it guards is 5.9 GB of WAL
against a 340 MB DB, then 22 GB and exit 137, then 25.6 GB leaked across SIGKILLed sessions. A
percentage tolerance would have passed every one of those.

**And index recreation gets its own rule with its own measurement**, because it is where a correct
optimisation turns into a SIGKILL: each `CREATE INDEX` is a synchronous full-table scan (~20 s apiece
at kernel-repository scale, **79 s total**), and running them back-to-back is a single event-loop
stall longer than a 60 s watchdog window — *codegraph was SIGKILLed immediately after doing 79 s of
correct work*. So **a migration whose estimated row-touch exceeds `watchdog_ms / 2` must set
`resumable = 1` and run through `work`**, with a yield between statements. `MAX_SNAPSHOT_MS = 5000`
on the read side is the same problem from the other end: a held read transaction pins the WAL, so the
reader's deadline is a WAL-valve safety parameter, not a UX parameter, and 30 s was rejected as
*precisely* the condition the futility latch exists for.

### 5.11 Discovery without importing — measured 2,100×

Building the driver catalog from `importlib.metadata` and `tomllib` alone. **Discovery never executes
driver code** (INV-4), and the performance case is as strong as the security one:

| mechanism | cost, 328 installed distributions | verdict |
|---|---:|---|
| `entry_points(group=…)` | **15.3 ms** | the discovery mechanism |
| `scandir`+`stat` of every `*.dist-info` | **1.01 ms** | the `driver_card_cache` validity key |
| `Distribution.files` (a `RECORD` scan) | **2,124 ms** | **forbidden** as a discovery mechanism |

The card cache is keyed `(prefix, dist_name, dist_version, card_path)` with mtime and size as the
validity key, so the steady-state cost of knowing every card is 1.01 ms rather than 15.3 ms of
`entry_points` plus N `tomllib.load`s — a **15×** steady-state saving on top of the 2,100× the
forbidden mechanism would have cost. The 1.01 ms figure also yields the framework's per-`stat`
constant, **~3.1 µs**, which B43 spends 100,000 of.

### 5.12 The free quality channel — `agree.decode_vs_page` at zero inference cost

When a part escalates, **you have already paid for two independent readings of it**. The normalised
edit distance between them therefore costs zero additional inference, and it lands exactly on the
population where the cheap driver is suspect. `requires = (DECODE, PAGE)`, `cost_class = FREE`.

The discipline that keeps it honest: `TruthKind = "agreement"`, its own scoreboard column headed
**"Agreement (not accuracy)"**, and it may **never** populate an accuracy column. Two drivers sharing
a base model family can be wrong identically, which is F23 — and until F23 reports, **only `audit`
verdicts may trigger a demotion**. Note the signal is unavailable on exactly the population that
motivates escalation most: on the 12 scanned exhibits `DECODE` produced nothing, so
`agree.decode_vs_page` is `NOT COMPUTED` there and only the false-positive population (part 177,
0.94 agreement) yields a reading. That asymmetry is the signal's whole value and also its limit.

### 5.13 Where re-work is avoided rather than made faster

Four mechanisms whose saving is "the work does not happen", which is the only kind of optimisation
that cannot regress. Each is owned elsewhere; the saving is here:

| mechanism | the saving | owner |
|---|---|---|
| `rebind()` **carries the `cite`** on rules 1 and 2 | a re-parse that re-minted cites would re-point every citation already shipped in someone's document — an unbounded external cost, not a CPU one | [03](03-document-model.md) §6.5 |
| `anchor_delta`, not a full re-resolve | the per-document symmetric difference of `(name_norm, akind)` pairs is **empty on a body-only edit**, which is the common case. Skipping the equivalent pass measured **4.3% of distinct edges wrong, in both directions, silently** (codegraph CG-33, G19's fixture) | [06](06-structure-extraction.md) |
| the `dep` reverse index | `CREATE INDEX dep_reverse ON dep(kind, key)` makes invalidation **one query, never a sweep**. `MAX_DEPS_PER_UNIT = 256`; past it the operator **must** declare a cohort dep — coarser, always safe, over-invalidating on purpose | [07](07-store-and-retrieval.md) §11.4 |
| the `stat_fresh` predicate | `size == st_size AND mtime_ns == st_mtime_ns AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns`, with `indexed_at_ns` captured **before** the content read. At B32's ~3.1 µs/`stat` a 100k-document freshness check is **310 ms**; LEANN's full-bytes re-hash of the corpus is the counter-example and at 10M files is unusable | [05](05-ingest-and-routing.md) §1.4 |

**F34 is the open one and it is the load-bearing one:** the whole incremental cost argument is that
`anchor_delta` stays empty on real edits. Its pre-committed fallback is a dedicated re-bind budget
plus a keyset cursor over `ref_unresolved`, so a large delta degrades to a bounded, resumable pass
rather than a stall.

### 5.14 The compact archive, and the encoding that was measured and refused

The `.owdoc` archive is a **plain ZIP** of NDJSON: `unzip -l` and `jq` both work with no external
tool, ZIP members are `ZIP_DEFLATED`, and there is no `.zst` suffix and no zstd on the read path.
Measured at **~75 B/Block deflated**.

A `SCHEMA`-versioned msgpack encoding beside JSON was measured at **~72 B/Block** — a **4% win for
which you surrender `jq`, `unzip -p` and browser-console inspection**, and add a C extension to a
distribution whose entire premise is zero third-party dependencies. Refused, with the number. The
same reasoning struck MessagePack from the driver wire: `omniweave-driver/1` is
`u32 header_len ‖ u32 body_len ‖ JSON header ‖ raw body`, which carries binary without base64 and
lets `wire.py` be ~80 fuzzed lines instead of a ~260-line hand-rolled decoder on a security boundary.

### 5.15 Refusal as an efficiency technique

Five of the mechanisms above end in a refusal rather than a slow path, and that is a deliberate
pattern with a stated rationale: **an honest refusal beats a five-second query nobody warned you
about**, and it beats a multi-hour run that ends in an OOM kill even more decisively. The set, so a
reviewer can see it is a pattern and not five accidents:

| refusal | threshold | what the slow path would have cost |
|---|---|---|
| `OW-S-022`, stdlib vector backend | `VEC_BRUTE_MAX = 250_000` Segments | B28's 281 ms against a 250 ms ceiling, growing linearly and silently |
| `OW_GRAPH_TOO_LARGE` | `MAX_CLUSTER_EDGES = 8_000_000` | B42's ~60 s per five-sweep run, ×10 at 80M edges, in a pure-Python loop |
| `ow doctor` on `Σ max_workers × memory_mb` | `> 0.8 × RAM` | an OOM kill at hour six of a 19-hour ingest (§4.4) |
| store-busy, exit 7 | a second writer, or a reader above the concurrency cap | a silent retry loop, or a query that has blown `query_ms` before it starts (§3.6) |
| `RESOURCE_LIMIT{knob}` | any `MAX_*` | the limit discovered after the memory is spent, which rule 5 of §4.2 exists to prevent |

Every one of them prints the knob that would raise it, and **widening past a `MAX_*` is a fork, not
a flag**.

## 6. The cost model, in dollars

### 6.1 The pricebook and the two rates to check hardest

Every figure below resolves through `.omniweave/pricebook.toml`, which is **operator-owned,
versioned and digested**. `pricebook_digest` enters `route_decision`'s identity, so a price change
makes a *new* decision row rather than silently rewriting history, and `ow route replay --pricebook
<old>` re-prices the entire log against the previous book for **$0**.

```toml
version = 3
currency = "USD"
effective_from = 2026-09-01

[local]
cpu_ms_micros = 0.00928
gpu_ms_micros = 0.3556
wall_ms_micros = 0.0
bytes_egress_micros = 0.0

[provider.parasail]
tokens_in_micros = 0.10
tokens_out_micros = 0.20
calls_micros = 0.0
bytes_egress_micros = 0.00009
```

```text
where the four rates come from, because a wrong one is invisible
  cpu_ms_micros  = 0.0334 $/vCPU-h / 3.6e6 ms-per-h = 9.28e-9 $/ms = 0.00928 micros/ms
  gpu_ms_micros  = 1.28   $/h for one A10G / 3.6e6  = 3.556e-7 $/ms = 0.3556  micros/ms
  wall_ms_micros = 0.0    -> UNPRICED, which is NOT the same as free
  tokens_*       = $0.10 / $0.20 per 1M tokens      = 0.10 / 0.20 micros per token
```

**The two local rates are the ones an error hides in.** At `gpu_ms_micros = 0.3556` and B08's 2.4 s
p50, one `PAGE` call is `2,400 × 0.3556 = 853.4` micros ≈ **$0.00085/page**, and the 100k reference
ingest's 116,400 escalated pages is **$99**. Three anchors now describe the same quantity and they
do not agree:

```text
  this pricebook, olmocr p50               116,400 x 853.4 micros           = $99
  the charter's billable band              olmocr <$200/1M pages, 3.4x spread = $23-$80
  olmocr's own published figure            $0.0002/page x 116,400             = $23
                                                                               --------
  the spread is 4.3x, and the charter names it: the naive gpu_ms estimate and
  olmocr's published price are 3.4x apart (F6).
```

**That is why `driver_by = "cheapest_admissible"` is opt-in and the shipped default names a driver.**
Selection on an unreconciled estimator is a cost bug with a proof. §6.3-6.5 use the pricebook figure
(853.4) because it is the one the framework will actually charge against a budget; §6.8 clause 4
prints the band.

**INV-15: no driver prices anything.** A driver reports a seven-dimension physical `Spend`
(`wall_ms`, `cpu_ms`, `gpu_ms`, `tokens_in`, `tokens_out`, `calls`, `bytes_egress`) plus a
`provider` string; the operator's `PriceBook` converts it, in `Spend.micros(book)`, which is the only
place money appears. There is no currency field on any driver-facing type or card, ever.

### 6.2 The three corpora and the three configurations

| corpus | composition | pages | routed parts | Blocks @90 | Segments |
|---|---|---:|---:|---:|---:|
| **A — born-digital reports** | 1,000 PDFs, mean 18 pages, 0% scanned | 18,000 | 18,000 | 1.62M | 54,000 |
| **B — scanned archives** | 1,000 image-only PDFs, mean 8 pages | 8,000 | 8,000 | 480k (~60/page: OCR emits lines, not cells) | 16,000 |
| **C — mixed enterprise** | 700 office (document grain) + 250 PDF × 12 + 50 scanned × 12 | 12,000 | 4,300 | 1.06M | 35,400 |

**One Block rate throughout, and it is 90/page** — the midpoint of F1's 60-120 envelope and
[07](07-store-and-retrieval.md) §4.3's planning number. §3.1 additionally prints the charter's
measured ~67/page so the reference ingest can be checked against the charter; every dollar figure
below uses 90, because more Blocks means more Segments means a **larger** C3 bill, and a cost model
that errs cheap is the one that gets someone fired. Corpus B is the exception at ~60/page, because a
VLM emits lines and a spreadsheet emits cells.

| config | what it turns on |
|---|---|
| **C1 `decode-only`** | `--max-rung decode`, free graph passes only, `vectors = "off"`. No GPU, no billed API |
| **C2 `local escalation`** | the shipped default plus `parse.page.olmocr` on a local GPU (`cost_class = local_compute`, priced through `[local] gpu_ms_micros`), free graph passes, `vectors = "off"` |
| **C3 `full`** | C2 plus a billed `derive` pass over the residue at `llm_coverage_floor = 0.60`, plus local GPU embeddings for all Segments |

### 6.3 Corpus A — born-digital reports, per 1,000 documents

```text
C1  decode-only
    pdfium decode      18,000 parts x  8 ms                    = 144,000 cpu-ms
    FREE signals       18,000 parts x  2 ms                    =  36,000 cpu-ms
    free derive        54,000 segments x 4.2 ms                = 226,800 cpu-ms
    end_page commits   18,000 pages x 6 ms                     = 108,000 cpu-ms
    runtime overhead   ~20,000 transitions x 0.45 ms           =   9,000 cpu-ms
                                                                 -------------
                       523,800 cpu-ms x 0.00928 micros/ms      =   4,861 micros
                                                        C1 TOTAL = $0.0049
    wall: 117,000 ms serialised on the writer + 406,800/4       = ~219 s

C2  local escalation                                (adds to C1)
    escalated          18.8% x 18,000                          = 3,384 parts
    ink renders        ~1.2x the escalating set x 16 ms         =  64,973 cpu-ms  =    603 micros
    GPU                3,384 x 2,400 gpu-ms = 8,121,600 gpu-ms
                       x 0.3556 micros/ms                      = 2,888,041 micros
                                                        C2 TOTAL = $2.89   ($0.00085 per escalated page)
    wall, ow-gpu-1, olmocr   8,121,600 gpu-ms / C_eff, C_eff in [1.5,4]  = 34-90 min   (F7)
    wall, ow-laptop-1        not attempted: section 2.6         = clamped to free

C3  full                                            (adds to C2)
    billed residue     48% of 54,000 segments                  = 25,920 segments
                       (billed share 0.48 from 06 section 2.4's "10-K / annual report" row --
                        the gate is per-Segment, so this is NOT 1 - covered_frac and a Segment
                        at 0.59 is billed entire; covered_frac on that row is 0.57. F13)
    tokens_in          25,920 x 2,000 x 0.10 micros            = 5,184,000 micros = $5.18
    tokens_out         25,920 x   600 x 0.20 micros            = 3,110,400 micros = $3.11
    embeddings         54,000 x 6 gpu-ms x 0.3556              =   115,214 micros = $0.12
                                                        C3 TOTAL = C2 2.89 + 5.18 + 3.11 + 0.12
                                                                 = $11.30

    the alternative:  a DOCUMENT-level OCR boolean over corpus A
                      18,000 x 853.4 micros = 15,361,200 micros = $15.36 against C2's $2.89
                                                        = 5.3x, for a strictly worse result
```

### 6.4 Corpus B — scanned archives, per 1,000 documents

```text
C1  decode-only
    format probe + FREE signals + the ink render that
    decode.blank-part-escape defers to
                       8,000 parts x 18.5 ms                   = 148,000 cpu-ms
    end_page commits   8,000 pages x 6 ms                      =  48,000 cpu-ms
                                                                 -------------
                       196,000 cpu-ms x 0.00928                =   1,819 micros
                                                        C1 TOTAL = $0.0018
    ** AND ZERO USABLE DOCUMENTS. ** decode.no-text-layer cannot escalate under --max-rung decode,
    so every part settles empty_result, corpus_card reports a Coverage gap over 8,000 pages, and
    absence gate parse_gap_in_scope makes every query say so with the command that clears it.
    This row is in the table precisely because a cost model that omits it is dishonest.

C2  local escalation
    GPU                8,000 x 2,400 gpu-ms = 19,200,000 gpu-ms
                       x 0.3556 micros/ms                      = 6,827,520 micros = $6.83
    REGEN              3% invalid-output rate                  = 240 calls
                       240 x 853.4                             =   204,816 micros = $0.20
                       (05's trace observed 1 of 12 = 8%, n = 12; 3% is the planning figure)
    render CPU         8,000 x 16 ms x 0.00928                 =     1,188 micros = $0.001
                                                        C2 TOTAL = $7.03
    wall, ow-gpu-1, olmocr  19,776,000 gpu-ms / C_eff          = 1.4-3.7 h   (F7)
    wall, ow-laptop-1       not attempted: section 2.6. At B12's 9.26 s/page it is 21 h, and at
                            B13's p95 roughly 5% of pages exceed wall_ms_hard and retry.

C3  full
    billed residue     92% of 16,000 segments                  = 14,720 segments
                       (billed share 0.92 from 06 section 2.4's "scanned correspondence (OCR)"
                        row -- the gate is per-Segment, so this is NOT 1 - covered_frac and a
                        Segment at 0.59 is billed entire; covered_frac on that row is 0.10,
                        the WORST case in the table. F13)
    tokens_in          14,720 x 2,000 x 0.10                   = 2,944,000 micros = $2.94
    tokens_out         14,720 x   600 x 0.20                   = 1,766,400 micros = $1.77
    embeddings         16,000 x 6 x 0.3556                     =    34,138 micros = $0.03
                                                        C3 TOTAL = C2 7.03 + 2.94 + 1.77 + 0.03
                                                                 = $11.77
```

### 6.5 Corpus C — mixed enterprise, per 1,000 documents

```text
C1  decode-only
    office             700 x 4.4 ms                            =   3,080 cpu-ms
    pdfium             3,000 x 8 ms                             =  24,000 cpu-ms
    scanned probe      600 x 18.5 ms                            =  11,100 cpu-ms
    FREE signals       4,300 routed parts x 2 ms                =   8,600 cpu-ms
    free derive        35,400 segments x 4.2 ms                 = 148,680 cpu-ms
    end_page commits   12,000 pages x 6 ms                      =  72,000 cpu-ms
                                                                 -------------
                       267,460 cpu-ms x 0.00928                 =   2,482 micros
                                                        C1 TOTAL = $0.0025
    Office and born-digital PDF are FULLY USABLE here; the 600 scanned pages are a Coverage gap.
    This is the configuration a laptop should run, and on this mix it is 0.037% of C3's cost.

C2  local escalation
    escalated          600 scanned + 18.8% x 3,000 = 564        = 1,164 parts
    GPU                1,164 x 2,400 = 2,793,600 gpu-ms
                       x 0.3556                                 = 993,404 micros = $0.993
    REGEN              3% x 1,164 = 35 calls x 853.4            =  29,869 micros = $0.030
                                                        C2 TOTAL = $1.02
    wall, ow-gpu-1, olmocr  2,873,400 gpu-ms / C_eff            = 12-19 min   (F7)
    wall, ow-laptop-1       clamped to free by section 2.6

C3  full
    billed residue     56% of 35,400 segments                   = 19,824 segments
                       (billed share 0.56 from 06 section 2.4's weighted reference mix -- the
                        gate is per-Segment, so this is NOT 1 - covered_frac and a Segment at
                        0.59 is billed entire; covered_frac on that mix is 0.48. F13)
    tokens_in          19,824 x 2,000 x 0.10                    = 3,964,800 micros = $3.96
    tokens_out         19,824 x   600 x 0.20                    = 2,378,880 micros = $2.38
    embeddings         35,400 x 6 x 0.3556                       =    75,530 micros = $0.076
                                                        C3 TOTAL = C2 1.02 + 3.96 + 2.38 + 0.08
                                                                 = $7.44

    the alternative:  a DOCUMENT-level OCR boolean
                      3,600 PDF parts x 853.4 = 3,072,240 micros = $3.07 against C2's $1.02
                                                        = 3.0x
```

### 6.6 The summary table, and the row that matters most

| per 1,000 documents | **C1 decode-only** | **C2 local escalation** | **C3 full** | **C2 re-ingest, `call` cache warm** |
|---|---:|---:|---:|---:|
| A — born-digital reports | **$0.0049** | **$2.89** | **$11.30** | **$0.0050** |
| B — scanned archives | $0.0018 (**and nothing usable**) | **$7.03** | **$11.77** | **$0.0022** |
| C — mixed enterprise | **$0.0025** | **$1.02** | **$7.44** | **$0.0026** |

The re-ingest column is `C1 + (escalated parts × 5 ms of CPU to re-derive rows from the cached
response)`: corpus A is `4,861 + 3,384 × 5 × 0.00928 = 5,018` micros; corpus B is
`1,819 + 8,000 × 5 × 0.00928 = 2,190`; corpus C is `2,482 + 1,164 × 5 × 0.00928 = 2,536`.

**That right-hand column is the single most consequential number in this document, and it prices a
re-derivation inside one store — not a move to a second one.** With the `call` layer warm, the four
re-derivations §5.4 enumerates — a re-parse at a new `producer.schema_version`, a `digest_recipe`
bump taken as a re-digest pass, an `ow index rebuild --derived`, and a re-run after a metadata-only
touch — pay only that CPU: **$0.0050 against $2.89 on corpus A, a 576× reduction**, and
**$7.03 → $0.0022, a 3,196× reduction, on corpus B**, which is the corpus where the whole bill is
the VLM. **None of those figures applies to a second `.owstore`**: `cache_index` is created by
`0004_runtime.sql` inside the store, a fresh store opens with an empty cache, and §5.4 states the
retraction and records the machine-scoped sidecar that would change it as deferred and unfunded.
That is what "cache the driver's raw response, never the derived rows" buys, and it is why
`[cache.gc] billed_after_days = 0` means never and why I27 requires `--allow-rebill` to delete a
paid entry.

### 6.7 The incremental unit cost — the workload a deployed system actually runs

Every figure above prices a first ingest. A deployed corpus is re-ingested one document at a time,
forever, and **that unit cost is what determines whether the system is usable a year in**. B43 is the
budget row; here is its arithmetic, for one changed 12-page born-digital document in a
100k-document corpus:

```text
freshness scan       100,000 stat calls x ~3.1 us (from B32's 1.01 ms / 328 dists)  =  310 ms
change detection     one document's content_sha256, 2 MB at ~500 MB/s              =    4 ms
pdfium decode        12 parts x 8 ms                                               =   96 ms
FREE signals         12 parts x 2 ms                                               =   24 ms
rebind()             1,080 blocks: digest compare + carry, one query per parent     =   35 ms
end_page commits     12 pages x 6 ms                                               =   72 ms
work transitions     ~14 x 0.45 ms                                                 =    6 ms
free derive          36 segments x 4.2 ms                                          =  151 ms  <- only
                                                                                      the changed doc's
invalidation         ONE query on dep_reverse(kind, key)                            =   <1 ms
anchor_delta         EMPTY on a body-only edit                                      =    0 ms  (F34)
                                                                                      --------
                                                                       B43 p50        ~700 ms
     of which 44% is the freshness scan, which does not depend on the edit at all

cost, at 0.00928 micros/cpu-ms                                                       = ~6 micros
                                                                                       = $0.000006
```

**Three things that table makes visible and no other table in this document does.**

1. **The freshness scan is 44% of the incremental cost and it is O(corpus), not O(change).** At 1M
   documents it is 3.1 s and dominates completely. The mitigation is the connector cursor and the
   stat index ([05](05-ingest-and-routing.md) §1.4): a source that supports a change cursor never
   walks the roster. A plain filesystem source does, and that is the case B43 budgets.
2. **The p95 is 4× the p50 and the cause is not parsing.** ~3 s is an FTS5 segment merge, a WAL
   checkpoint, or a `store.write` lock held by a watcher batch. This is codegraph's measured
   pathology — a **7-file incremental sync taking 2 minutes at 0-2% CPU** on HDD-class storage
   because each commit paid its own autocheckpoint — and `journal_size_limit = 67108864`, the WAL
   valve and the batch-takes-the-lock-once rule are the three mechanisms that keep it at 3 s.
   **An incremental pipeline whose per-change cost scales with total corpus size is not
   incremental**, and store-level write amplification is the easiest way to acquire that property
   without noticing.
3. **The money is zero and that is the point.** A body-only edit to a born-digital document costs
   six millionths of a dollar because nothing escalates and nothing is re-billed: `rebind()` carries
   the `cite`, the `call` cache holds any page response, and paid artefacts carry no
   `driver_version`. A re-ingest that *does* cost money means something in the semantic config
   projection changed, and `ow cost --by driver` says which.

### 6.8 Six honesty clauses on the whole table

1. **The billed shares in C3 (0.48 / 0.92 / 0.56) are projections, not measurements.** They are
   [06](06-structure-extraction.md) §2.4's per-class figures, and §2.4 labels them projections.
   F13 is the measurement, and its pre-committed fallback is that the economics section is
   *rewritten rather than defended* if the median coverage outside structured corpora falls below
   0.2 — which on a per-Segment gate pushes the billed share above 0.9 on every class.
2. **The 18.8% born-digital escalation rate is the charter's planning figure and is not sourced to a
   measurement.** P-Q3 is the measurement. Corpus A's C2 total scales linearly in it: at 5% it is
   $0.77, at 40% it is $6.15.
3. **B16's Segment shape (2,000 in / 600 out) is extrapolated and every C3 figure rests on it.**
   P-Q5 is the measurement; the only measured extraction anchor in the collection is lift's 9.5 s,
   which is document-grain on a different task.
4. **The GPU dollar figures inherit F6's 3.4× estimator spread**, not F7's Coalescing band. `gpu_ms`
   is per-page *work* and Coalescing improves *throughput*, so cost and wall time are separate
   columns here on purpose. The wall columns inherit F7 and are printed as bands.
5. **No wall-time figure for `ow-laptop-1` appears in C2 or C3.** §2.6 clamps that machine to `free`
   when no accelerator probe passes, so the honest entry is "not attempted" and not a 21-hour number
   the framework would refuse to produce.
6. **The billed share is read from a table, not computed from coverage.** Every C3 row above takes
   its billed share from [06](06-structure-extraction.md) §2.4's per-class column.
   `1 − covered_frac` under-counts by 7-23% on the billed segment count and 5-11% on the C3 total,
   because the `llm_coverage_floor` gate is per-Segment and a Segment at 0.59 is billed entire. An
   earlier revision of this section made exactly that substitution, and §6.2 says what a cost model
   that errs cheap does.

## 7. The benchmark harness

### 7.1 `ow bench <subject>` — what it measures

`bench` is the verb and the second word is a **positional subject from a closed set**, which is how
the charter already spells it (`ow bench scheduler | inproc | service | rss`) and which avoids
inventing CLI verbs that are nouns. The registry is one function per subject in
`packages/omniweave/src/omniweave/run/bench.py`, so adding a subject is one function plus one row in
the closed set. The full set, with what each writes:

| `ow bench …` | measures | fixture | writes |
|---|---|---|---|
| `pacer` | the Pacer workload alone, N times | none | the Runner's baseline; a Runner change is a baseline reset with §1.2's seven-night procedure |
| `cold` | `import omniweave_core`, `ow --version`, `ow --help`, discovery over 20 dists | a synthetic dist-info tree | `import.omniweave_core_ms`, `cold.ow_version_ms`, `cold.ow_help_ms`, `discovery.20dists_ms`, B31 |
| `scheduler` | p50/p95/**p99** of claim, commit and total over **1M synthetic units** with a no-op operator, on {NVMe, spinning disk, SMB} | generated | B22; **F8**, whose fallback is widening group commit from zero-derived-row transitions to same-operator batches. Also the fixed-cost-amplification shape of §3.6 |
| `inproc` | wall, peak RSS and GIL-held fraction at `max_inproc ∈ {1,2,4,8}` against the pure-Rust path | `fixtures/office-200` | B02/B03; **F2**, whose fallback is the anydoc fork trigger |
| `parse` | per-part decode at each Rung, by format and `producer_family` | `fixtures/gen/gen_5000p_pdf.py` + ten real 200-page documents | B04, B23, `store.bytes_per_block`, **F1**, **P-Q1** |
| `route` | `evaluate()` throughput, FREE and LOCAL signal cost per part, the ledger growth rate, and the `route_decision` count per document | the same | B05, B06, B07, **P-Q3**, **P-Q7** |
| `service` | throughput and `queue_p95_ms` for 2,000 pages at `max_batch ∈ {1,4,8,16}` × `batch_wait_ms ∈ {0,5,25}`, **and the per-request p50/p95 wall at each point** | 2,000 rendered pages | B08, B09; **F7**, the missing Coalescing number, and the number that closes B09 |
| `embed` | per-Segment cost at batch ∈ {1,8,32,64}, the query-time embed path, and the `vseg` signature scan at 50k/100k/200k/250k | `fixtures/store/` | B18-B21, B28, `VEC_BRUTE_MAX` |
| `query` | per-Channel and end-to-end p50/p95/p99 at **10k / 1M / 10M / 20M / 30M / 50M** Blocks, `vectors` off and on, each scale measured **after** an FTS5 `'merge'` so segment accumulation is not confounded with size, reporting the Block count at which `lexical` first returns `UNAVAILABLE(timeout)` | generated stores + `fixtures/store/golden-queries.jsonl` | `query.warm_p50_ms`, B26, B27; **F50**, **P-Q8** |
| `encoding` | the `owrows/1` saving per encoder id, with `n` and a ci95, against the `eval/gates.toml` floor | the golden query set | B36; **F51** ([07](07-store-and-retrieval.md) §7.5 names this subject) |
| `incremental` | the B43 shape: one changed document at roster sizes {1k, 10k, 100k}, by edit shape (body-only, heading, whole-document), **and F55's soak: 10,000 successive single-document ingests into a 1M-block store with no maintenance window** — `SELECT count(*)` over `block_fts_data`'s segment rows, `lexical` p50 and p95, and total index bytes sampled every 500 ingests, the whole soak run twice, with and without the window | a generated roster + the 40 scripted mutations of G19's fixture | B43; **F34**, **F55**, and §6.7's freshness-scan term |
| `compile` | per-unit and whole-artefact compile, plus Toolchain spawn, per target ([09](09-generation.md) owns the contract) | the 40-unit golden OUT fixture | B37-B40; **P-Q2** |
| `rss` | peak RSS on the 5,000-page PDF and the 4M-cell sheet, and supervisor RSS on a 100k roster | the two pathological fixtures | `rss.gen5000p_peak_bytes`, `rss.merged4mcell_peak_bytes`, G22 |

**Extends the charter (new decision).** The charter's `bench.py` inventory lists four subjects
(`scheduler | inproc | service | rss`); [07](07-store-and-retrieval.md) references `ow bench query`
and `ow bench encoding`, and [05](05-ingest-and-routing.md) references `ow bench route`. The thirteen
above are the complete set. The additions beyond those seven are `pacer`, `cold`, `parse`, `embed`,
`compile` and `incremental` — each because a committed `eval/perf.toml` row or a deferred F- or P-Q
item names a measurement with no instrument otherwise, and `query`'s scale list is extended to
20M/30M/50M because **P-Q8's own instrument did not exist**: §7.1 ran 10k/1M/10M and P-Q8 asks
for the breakpoint above 10M. `incremental` absorbs **F55**, FTS5 segment accumulation, which was
the one [07](07-store-and-retrieval.md) §12.4 binder with no `ow bench` subject at all — and it
belongs there rather than on `query` because accumulation is produced by the successive-re-ingest
workload §6.7 prices, not by store size.

**F55 has exactly one instrument and this document states it: 10,000 single-document ingests into a
1M-block store, sampled every 500, reporting `lexical` p50 and p95, run twice — with and without the
maintenance window.** The `incremental` row above is authoritative for it: where another document
restates the instrument, this row's figures govern, and a divergence is a defect in that document.
10,000 rather than 1,000 because F55's question is months of writes: at `automerge = 4` and
`MERGE_STEPS = 16`, a thousand single-document writes is roughly one month of a deployed roster,
and the degradation [07](07-store-and-retrieval.md) §12.4 item 3 predicts has not accumulated yet
— so a thousand-ingest soak can only return a null result on the exact question F55 asks. Both p50
and p95 are reported because §12.4 item 3 predicts the p50 climb while F55's fallback trips on
either. Every 500 gives twenty samples over the run, and 1M blocks is the store size at which
§6.7's p95 already attributes its 3 s tail to a segment merge.

### 7.2 The corpora it runs on

[13](13-quality.md) owns the fixture licence regime (Q-G1, Q-G2) and the `bench/serve/` agent
harness. This table names only what each fixture measures *for this document*:

| fixture | size | what it is for |
|---|---|---|
| `fixtures/docs/` (Tier A) | ≤ 64 MB total, no reduction file > 256 KiB, ≥ 40% real public-domain scans | the correctness corpus; every parse budget's realism check |
| `fixtures/gen/gen_5000p_pdf.py` | generated, not committed | F1's Blocks-per-page envelope, `store.bytes_per_block`, and `rss.gen5000p_peak_bytes` |
| `fixtures/office-200` | 200 office documents, generated by `fixtures/gen/gen_office200.py` and pinned in `EXPECTED.sha256` (D656) | F2's marshal question; B02/B03 |
| the 4M-cell merge-free sheet | generated | `rss.merged4mcell_peak_bytes`, `TABLE_SYNOPSIS_CELLS`, F29 |
| a 100k-unit synthetic roster | generated | G22's scale gate; §6.7's freshness-scan term |
| `fixtures/store/golden-queries.jsonl` | a fixed query set | `query.warm_p50_ms`, `ow bench encoding`, nDCG@10 for F11 |
| the fixed 50k vector fixture | committed | F9's recall@10 of `sig → top-1000 → f32 rerank` |
| G19's 300-document / 40-mutation fixture | committed | `ow bench incremental`, B43, F34 |
| `bench/serve/` | a 30-task scripted-agent harness | `source_reread_rate`, `first_answer_seconds` (V01-15), F19, F20. **[13](13-quality.md) owns the harness; this document consumes its timings** |

**Deep goldens** are the exploded `.owdoc.d/` archives committed for at most **24 documents of at
most 40 pages**, so `rebind()` has two real generations to match. **Reductions** — `shape`, `pages`,
`outline` — are the committed line-oriented projections; a `pages` reduction is one line per page
(5,000 pages ≈ 1.1 MB) and an `outline` is one line per Block, suppressed above 500 pages.

### 7.3 How it is run

```text
CI jobs that carry a performance obligation
  gates        ubuntu x 3.11        G1..G27 + the static Q-G series, fails fast, <= 3 min
  conform      ubuntu x 3.11        the ELEVEN MANDATORY suites of the twelve, <= 5 min
                                    (conform.mandatory_tier_s = 240 +/- 60)
  parity       clean container      uv sync && pytest: offline, GPU-free, Node-free
                                    (contributor_parity_s = 420 +/- 180, hard ceiling 600)
  nightly      ow-bench-1 (pinned)  T4 eval, <= 90 min       <- every `nightly` perf budget
  weekly       ow-bench-1 (pinned)  T5 soak, ~3 h            <- leak detection, lease reaping
```

Five rules that make a run comparable to the run before it:

1. **Time is a ratio to the Pacer, taken before *and* after.** `eval_perf` stores
   `pacer_before_ns`, `pacer_after_ns`, `work_ns` and `time_ratio`, so a reader can see the Runner's
   own drift rather than inferring it.
2. **Counters are exact and RSS/WAL are absolute.** Q-G15. A percentage tolerance on WAL would have
   passed codegraph's 5.9 GB-against-340 MB.
3. **One bench run at a time, enforced by a lock, and a second run refuses.** §1.2. A queued run
   measures a page cache the first run warmed, which is a silent 2-5× on every disk-touching row.
4. **`--cassette required` in CI.** A cassette miss is `OW-Q-004` and **never** a live call: olmocr's
   defaults are a 64× output amplifier fired in parallel (8,000 tokens × 8 retries at
   `--max_concurrent_requests 1600`), so a single accidental live path in a benchmark is a real bill.
5. **No RNG on the statistics path.** Sampling is `blake2b(work_id ‖ salt)`, the eval split is
   `blake2b(doc_key ‖ "ow-split-1") % 100` so **leakage is structurally impossible**, and Hypothesis
   runs `derandomize=True` at 200 examples on PRs and 2,000 randomized nightly, with every nightly
   counterexample minimized and committed to `fixtures/regressions/`. olmOCR-Bench's unseeded
   `np.random` is the cautionary case: its published confidence intervals do not reproduce.

**What a nightly run does when the machine reboots mid-suite.** The run is `unknown`, not partial:
`SKIP` is not a state, `ow eval release-check` refuses on `unknown`, and an `unknown` run **does not
count toward §8.2's three consecutive breaches** — the same rule as `unstable`, for the same reason.
A gap in the 7-run rolling median window shortens the window rather than reusing a stale reading; a
window below 4 readings makes every `nightly` row `unknown` until it refills.

### 7.4 How results are published

`eval_perf` rows → a committed `eval/results/**.json` tree → the static scoreboard, byte-diff gated
like every generated artefact.

```sql
CREATE TABLE eval_perf (
  run_id TEXT NOT NULL,
  budget_id TEXT NOT NULL,
  pacer_before_ns INTEGER NOT NULL,
  pacer_after_ns INTEGER NOT NULL,
  work_ns INTEGER NOT NULL,
  time_ratio REAL NOT NULL,
  peak_rss_bytes INTEGER,
  peak_wal_bytes INTEGER,
  status TEXT NOT NULL,
  PRIMARY KEY (run_id, budget_id)
) STRICT, WITHOUT ROWID;
```

`time_ratio` is `work_ns / mean(pacer_before_ns, pacer_after_ns)`; `status` takes the five
`EvalStatus` values, `unstable` included. `budget_id` joins a CI failure message, an issue title, a
`BLESS.log` row and §2.4 of this document, which is why it is a stable identifier and not a test
name.

The scoreboard defaults to **accuracy-per-dollar within a licence tier** — which is why §6 exists at
all — and every row carries `witness`, a non-empty `not_measured[]` and a non-empty `confounders[]`.
`eval_scoreboard` resolves to `UNKNOWN` when the metric is unknown, `WITHHELD` when the corpus is
not publishable, `UNRANKED` for a non-`ci` witness or unpinned weights or entrant bias or an
agreement/self truth kind, and `RANKED` otherwise. **`†` marks entrant-bias rows including our
own** — which, per §1.1, includes B02's anydoc anchor and, per §2.1, every **R** row in §2.2.

**Publishing a number without `(n, ci95, method, MeasuredOn, witness)` is a rejectable defect**
(INV-19, reviewer rule 15). A driver measured on 12 documents and one measured on 1,200 would
otherwise be indistinguishable, and no guard could fire.

## 8. Performance regression gates

### 8.1 Budget versus Guard — two mechanisms, two owners

| | **Budget** | **Guard** |
|---|---|---|
| what it is | an **absolute floor** on a metric | a **delta against release N−1** |
| owner | the product | the PR author |
| breach means | we shipped something worse than our published promise | *this change* made it worse |
| fires when | the value crosses the tolerance | paired `p < 0.01` **and** effect ≥ MDE |
| lives in | `eval/perf.toml` | `eval/gates.toml` with a `guard` column |

**Baselines are release-anchored, and additionally checked against N−2 at 2×** (Q-G16), so **ten
blessed 9% regressions cannot compound** into a 2.4× loss nobody ever approved. That anti-ratchet
clause is the difference between a gate and a ceremony.

### 8.2 The mechanism

```text
nightly on ow-bench-1
  |
  +- take the bench lock; refuse (exit 7) if held        <- section 1.2 rule 3
  +- run the Pacer                       -> pacer_before_ns
  +- run the measurement                 -> work_ns, peak_rss_bytes, peak_wal_bytes
  +- run the Pacer                       -> pacer_after_ns
  |
  +- |before - after| / mean > 15%       -> status = unstable   (NOT pass, NOT fail)
  +- an aborted or rebooted run          -> status = unknown    (NOT pass, NOT fail)
  +- time_ratio vs the 7-run rolling median, against tol_pct / tol_abs
  +- counters vs eval/counters.toml, exact or ratchet
  |
  +- 3 CONSECUTIVE nightly runs above tolerance -> THE JOB FAILS and files an issue
     (unstable and unknown runs break the streak's counting but do not reset the window)
```

**Three consecutive runs, not one.** A single nightly breach on a shared Runner is noise; three in a
row on a pinned Runner against a 7-run rolling median is a signal. `unstable` and `unknown` runs do
not count toward the three — an unstable reading is a Runner problem, and treating it as a regression
trains everyone to bless. *(Build note, D916: by a user ruling of 2026-10-21 the first nightly bench runs on a GitHub-hosted runner, not `ow-bench-1`: the `gates` job, on the `schedule:` trigger only, runs `ow bench query` over `gen_5000p_pdf`'s 5,000 pages and keeps the run as `.oweval` rows, a `perf` run whose `hardware` names the runner and an `eval_perf` row for `query.warm_p50_ms`, its `work_ns` the warm p50 with the Pacer read before and after the timed passes. The row is `unstable` or `unknown`, never `pass` or `fail`, since no seven-run median on a pinned Runner exists, and `release-check` refuses it. The artefact is kept thirty days, so a median can be read off them once something computes one.)*

**`pr`-gated rows fire on the first breach**, because they are cheap, deterministic and measured
in-process: `import.omniweave_core_ms`, `cold.ow_version_ms`, `cold.ow_help_ms`,
`discovery.20dists_ms`, `conform.mandatory_tier_s`, `contributor_parity_s`.

### 8.3 What happens when a gate fires — the runbook

1. **Read `status` before reading the number.** `unstable` ⇒ fix the Runner. `unknown` ⇒ re-run. Do
   not bless, do not raise the value, do not open a performance investigation.
2. **Bisect on counters, not on the clock.** Check `cache_misses`, `rebilled_units`,
   `store_rows_read`, `tokens_out` first. If a counter moved, **that** is the regression and the
   clock is a symptom — and the counter names the mechanism, which the clock never does. If no
   counter moved and the clock did, the change is genuinely in the work itself.
3. **Check the paired escalations before anything else.** `rss.gen5000p_peak_bytes` firing is a
   **fork trigger** (`vendor/anydoc/FORK-TRIGGER.md`), not a budget conversation.
   `store.bytes_per_block` is a **ratchet** and cannot be raised at all. `wal.bulk_index_peak_bytes`
   is **absolute** and a percentage argument against it is out of order.
4. **If the change is intended:** `ow eval bless --counters --reason '<...>'` writes a `BLESS.log`
   row **in the same commit** (Q-G3; a golden or counter diff without one is `OW-Q-003` /
   `OW-Q-005`). Q-G16 then checks the new baseline against N−2 at 2×.
5. **If it is not intended and not fixable in this release:** the row's `value` is **not** raised.
   The gate's `class` in `eval/gates.toml` changes to `informational`, as a **reviewed diff with an
   owner and a `review_by` date**, and Q-G17 fails the build the day that date passes
   (`OW-Q-010`, which prints the owner). There is no flag that downgrades a gate without that diff,
   and a gate that cannot fail is a rejectable defect on its own.
6. **A flaky perf test is quarantined, not tolerated.** Above **2% failure over 30 days** Q-G18
   moves it to `informational` and files an issue; `eval_flake` holds per-`(test_id, day)` runs,
   failures and rerun-green counts, so "it's flaky" is a number rather than a claim.

### 8.4 The gates that are performance gates by another name

Five rows do performance work and would be missed by a reader looking only at `eval/perf.toml`:

| gate | asserts | the performance defect it catches |
|---|---|---|
| **G9** | `import omniweave_core` under `-X importtime` loads **zero** third-party modules | the 80 ms ceiling dies to one convenience import, and nothing else notices |
| **G17** | `import omniweave_core` imports none of `{model, store, archive, retrieve, answer, out, host, toolchain, modelserver}` | the per-turn hook path. A submodule that stops being lazy costs B29's 250 ms p95 directly |
| **G22** | a nightly **100k-roster** run: peak claimable ≤ `queue_high_water`, supervisor RSS ≤ **600 MB**, ≥ **2,000** transitions/s | the scheduler's per-unit overhead and the supervisor's memory independence, at a scale a unit test cannot reach |
| **G18** | the union of the two config-axis lists covers every key in `omniweave.toml.example` **exactly**, one pattern per key | graphrag's permanent silent 100% cache miss. An unclassified key is treated as `semantic` at runtime, so the failure mode is a re-bill, not a wrong answer |
| **ST17** | `tools/indexes.toml` names each index and its statement; `ow store explain --golden` is byte-diff gated | a plan flip, which presents as an outage and moves no budget until it is already bad |

### 8.5 The rows that cannot be gated, and what happens to them instead

Every `PAGE`-rung row in §2.2 — B08 through B13 — is measured on `ow-gpu-1` or `ow-laptop-1`, neither
of which carries a Pacer baseline (§1.2 limit 2). **They therefore cannot be Budgets and are not
gated.** Saying so explicitly matters, because a reader who sees thirteen rows in §2.4 and 43 rows in
§2.2 will otherwise assume the gap is oversight rather than mechanism. The regime for an ungated row:

| mechanism | applies to | what it gives |
|---|---|---|
| published with `(n, ci95, method, MeasuredOn, witness)` | every **M** and **R** row | INV-19's floor: a reader can tell a 12-document measurement from a 1,200-document one |
| a **Guard** against the same machine's previous release | the **M** rows on `ow-gpu-1` | a delta signal without an absolute floor. Fires at paired `p < 0.01` and effect ≥ MDE, which a 4-run GPU sample rarely reaches — so it is a weak signal, honestly labelled |
| `UNRANKED` on the scoreboard | every **R** row | surya's numbers can inform a capacity plan and can never win a comparison |
| an **F-item with a pre-committed fallback** | B09, the row with no number at all | F7. The plan states what changes if the measurement disappoints, before it runs |

**The consequence, stated so nobody discovers it during an incident: a `PAGE`-rung throughput
regression is not caught by CI.** It is caught by `ow cost --by driver` on a real run, by
`route_spend`'s `tokens_out` ratchet counter (which *is* gated, and which moves when a prompt or
retry change widens output), and by the `rebilled_units` exact counter. Those three are the GPU
lane's regression detection, and they are counters rather than clocks for exactly the reason §2.4
gives.

## 9. What omniweave is not fast at, and why the trade is right

Ten of them. Each is a real cost, stated in numbers, with the thing that was bought instead.

1. **First byte on a cold process — ~700 ms p50 (B26).** There is no daemon: *a long-lived local
   daemon or loopback socket for parse, embed, index or schedule is banned outright.* LEANN's
   unauthenticated ZMQ REQ/REP on a dynamic loopback port is compute theft from any local process,
   and open-slide needs a 76-line CSRF guard as a **minimum**. **The trade:** we pay ~700 ms once per
   invocation and get zero listeners, zero background processes, and a `--offline` mode that means
   what it says. The mitigation is that the paths where latency actually matters — `ow hook prompt`
   at G26's 250 ms warm — are held to a much tighter budget by keeping core lazy (G17) rather than by
   keeping a process alive.

2. **Sub-second document-to-queryable.** Not a target, and no budget in this document implies one.
   `ow_add` returns a **pending cost**, not a document: free and local work runs immediately, and
   anything that would spend money comes back as the exact command that approves it.
   **The trade:** `gate.agent-triggered-may-not-bill` clamps an MCP or SDK `ow_add` to
   `local_compute`, because *an `ow_add` arriving over MCP is not the cost consent a human gave by
   typing*. A real-time path would have to skip that gate.

3. **Aggregate analytics over extracted fields.** A point read is 20 µs (B35); a full scan of 80M
   Blocks is not what a B-tree is for. Aggregating a million invoices needs a columnar scan, a join
   planner and a cost model. **The trade:** `ow store export` plus DuckDB or a warehouse — *keep the
   `cite` column, because it is what lets you walk from a suspicious aggregate back to a polygon.*
   Building it in would mean a second storage engine (NG-13).

4. **High-QPS multi-tenant serving.** One writer, a cross-process `store.write` lock that §3.3
   measures as 59% of the CPU ingest wall, and `MAX_SNAPSHOT_MS = 5000` bounding every reader — the
   reader's deadline being a **WAL-valve safety parameter, not a UX parameter**. 16 concurrent read
   connections is ~1 GB of page cache, and the 17th is refused (§3.6). **The trade:** store-per-tenant
   at v1 (F27), which forfeits the `segment.content_digest` embedding dedup across tenants — and the
   reason is written down: that dedup **is a covert channel** in a shared store, because two tenants
   observe each other's embeddings as a timing difference.

5. **Semantic-only queries out of the box.** `vectors = "off"` is the shipped default, and the stdlib
   backend **refuses** above `VEC_BRUTE_MAX = 250_000` Segments (B28 shows why: 281 ms against a 250
   ms ceiling). **The trade:** *an honest refusal beats a five-second query nobody warned you
   about*, and the alternative on the default install path is numpy in core, which breaks G1. Four
   Channels and a `Verdict` that says `semantic: off` is a **visible** product limitation, and
   deliberately not a stop condition. The measured price of the alternative is §5.9's 8.2× batching
   saving that nobody on the default path collects.

6. **A single enormous document.** A 4M-cell sheet is one page, one transaction, a multi-GB WAL and a
   multi-minute commit that trips `loop_lag_max_ms = 250`, and the WAL valve **cannot help
   mid-transaction** because its release condition is a full backfill (F29). **The trade:**
   `MAX_BLOCKS_PER_DOC` plus a `RESOURCE_LIMIT` refusal naming the knob, rather than a sub-page
   commit boundary — which would complicate the `work` table's unit and add a fourth span level for
   a workload nobody has yet presented.

7. **A second pass over an unchanged corpus whose cache root was discarded.** The store is the parse
   memo, but the `call` layer is what makes a **re-derivation inside one store** cheap — a re-parse
   at a new `producer.schema_version`, a `digest_recipe` bump, an `ow index rebuild --derived`, a
   metadata-only touch. It does **not** cross stores (§5.4): `cache_index` is created by
   `0004_runtime.sql` inside the `.owstore`, so a fresh store bills every `billed_api` response
   again. Delete `.omniweave/cache` and a re-ingest costs $2.89 instead of $0.0050 on corpus A —
   **576×**. **The trade:** the cache is a
   deletable, GC'd, size-capped artefact rather than part of the store, so `.owstore` stays portable
   and `ow store export --portable` stays meaningful. `ow cache stat` prints the growth bound in
   these words: **live units × configurations seen**.

8. **Louvain and MinHash at graph scale, in pure Python.** B41's ~0.2 ms/entity and B42's ~12 s per
   8M-edge sweep are **estimates** (F15). `MAX_COMMUNITY_SIZE = 512` rather than graphrag's 10,
   because 10 on 3M entities is ~300k leaves ⇒ ≥ 400k report calls, **the biggest bill in the config
   file**. Above `MAX_CLUSTER_EDGES = 8_000_000` omniweave **refuses** and names
   `omniweave-driver-leiden` — whose licence is itself unverified (F40), and if it does not clear G3
   the cap becomes a plain refusal with no named escape, because *naming an escape that does not
   exist is worse than naming none*. **The trade:** zero graph engines, zero `graspologic` imports
   (graphify measured **7-19 s** of package import for a layout algorithm it never calls), and a
   clustering step that is a pure function over one SQL scan.

9. **Byte-exact artefact reproducibility.** `ArtefactDeterminism.byte` is **asserted in CI under one
   pinned resolution, recorded in the receipt, and never promised to a user** — a zlib bump
   falsifies it. `part` is the floor and is promised. **The trade:** we do not pin zlib, and we do
   not ship a determinism claim that a dependency bump turns into a bug report. The OPC writer
   still does everything that *is* portable: `ZipInfo(name)` for the safe 1980-01-01 constructor,
   members in canonical order, `dcterms:created == dcterms:modified == job.determinism.clock_ns`,
   EMU integers only, every attribute map sorted.

10. **Anything on slow storage.** codegraph's 19 minutes → 45 seconds is the *same work* on 150-IOPS
    storage, and a 7-file incremental sync on a large index took **2 minutes at 0-2% CPU** because
    write amplification scales with the *existing* database size and not the change size — which is
    why B43's p95 is 4× its p50. **The trade:** the WAL valve, Bulk windows and `journal_size_limit`
    are all present and all tuned for this case, `ow bench scheduler` runs on
    `{NVMe, spinning disk, SMB}` deliberately, and `ow doctor` reports the storage class — but the
    framework does not pretend a network share is a local NVMe. **An incremental pipeline whose
    per-change cost scales with total corpus size is not incremental**, and store-level write
    amplification is the easiest place to acquire that property without noticing.

## Extends the charter

Seven new decisions, each in the charter's spirit, each marked so a reviewer can attack it:

1. **Three named reference machines** (`ow-bench-1`, `ow-gpu-1`, `ow-laptop-1`) with specs. The
   charter names `ow-bench-1` as the pinned Pacer Runner and gives no spec; the card's own
   `hardware = "x86_64-linux 8c/16GiB"` supplies it. The two accelerator machines are chosen to
   **match surya's two published throughput rows exactly**, so the hardware behind every `PAGE`-rung
   reference row is comparable to a third-party measurement.
2. **An `R` evidence class, distinct from `M`.** A third-party published number on software omniweave
   does not ship is real evidence and can never be a gate. Six rows in §2.2 are `R`, all of them from
   a driver that is a framework-owned **Tombstone** at `tier = "forbidden"`. Without the distinction,
   B10's 187 ms reads as omniweave's `PAGE` budget when the shipped driver's figure is 2,400 ms.
3. **Two new `eval/perf.toml` rows**, `cold.ow_help_ms = 190` ±25% and `discovery.20dists_ms = 16`
   ±20%, both `gate = "pr"` (§2.3). Both close a G10 ceiling that had no budget beneath it, so a 25%
   drift was invisible until it shipped.
4. **`rss.merged4mcell_peak_bytes` bounds a *worker* process, not the supervisor** (§4.4). I31
   already caps the supervisor at 600 MB and forbids it from holding document bytes, so the 4 GiB
   figure can only be a worker's, and the consequence — `memory_mb = 4096` on that driver's card and
   an `ow doctor` refusal at 16 workers on 16 GiB — is the intended behaviour.
5. **A `PROGRESS`-emission obligation on every `PAGE`-rung `parse/1` driver**, at
   ≤ `progress_ms / 3` intervals, and **`--max-rung decode` as the default when no accelerator probe
   passes** (§2.6). Both follow from B13: the smallest available page model's published p50 on Apple
   Silicon is 4× `progress_ms` and its p95 exceeds `wall_ms_hard`.
6. **Nine additional `ow bench` subjects** beyond the charter's four: `pacer`, `cold`, `parse`,
   `route`, `embed`, `query`, `encoding`, `incremental`, `compile`. Each exists because a committed
   `eval/perf.toml` row or a deferred F- or P-Q item names a measurement with no instrument.
   `query`, `route` and `encoding` are already referenced by [07](07-store-and-retrieval.md) and
   [05](05-ingest-and-routing.md).
7. **A Runner-reset procedure and a bench lock** (§1.2): seven nightly cycles at
   `class = informational` with an owner and a day-14 `review_by` before a `nightly` row is re-armed,
   and an exclusive `flock` that makes a concurrent bench run refuse with exit 7 rather than queue.
   The charter says a Runner change is a baseline reset without saying how the reset ends, and a
   seven-run rolling median compared against a two-run history is a gate comparing a number to
   itself.

Also stated as rules rather than new decisions, because the charter already implies them:
**`ow bench`'s second word is a positional subject, not a verb** (the charter spells it that way and
the terminology lock forbids noun-shaped verbs), and **the three `timing_basis` inclusion
boundaries** (§1.1), which the charter locks by name without saying what each covers.

## Open questions

Numbered `P-Q` so downstream documents can reference them. Charter §7's F1-F41 and
[07](07-store-and-retrieval.md)'s F50-F54 are **not** restated; where one is the binding uncertainty
for a number here, the number cites it inline. These are the questions this document's own subject
raises.

- **P-Q1 — What is the real p50/p95 of a born-digital PDF page parse?** B04's 8 ms / 35 ms is the
  working figure in [05](05-ingest-and-routing.md) §10.1's trace, and the charter explicitly
  **struck** the only published-looking anchor ("p50 210 ms for a native PDF driver") as a transcript
  line mistaken for a measurement — noting that an 11.7-hour PDF row had been resting on it. Nothing
  in the collection times pdfium text extraction per page. *Closes:* `ow bench parse` over
  `fixtures/gen/gen_5000p_pdf.py` plus the ten real 200-page documents, sliced by
  `unit.producer_family`. *Pre-committed fallback:* if the p95 exceeds ~120 ms, the born-digital
  path stops being "free" in the routing sense and `[budget.per_unit] wall_ms = 600_000` needs
  re-deriving — §4.3 shows the current margin is 6.7% of the per-unit wall and a 15× regression
  consumes all of it.

- **P-Q2 — What does an artefact compile actually cost?** B37-B40 are entirely extrapolated; **no
  repo in the mined collection times a deck or document compile**, and the OUT mining never produced
  a throughput number for any of the three targets. *Closes:* `ow bench compile` over the 40-unit
  golden fixture per target, reporting per-unit and whole-artefact p50/p95 and separating
  `queued_ms` from `ran_ms`. *Pre-committed fallback:* if a whole-artefact compile exceeds ~10 s at
  20 units, `ow make` grows a progress channel and the OUT path gets its own `[budget]` row, because
  a silent 10 s wait in an interactive verb is a usability defect that no perf gate would catch.

- **P-Q3 — Is 18.8% the real escalation rate on born-digital PDF parts?** It appears once in the
  charter's reference ingest with no source, and **corpus A's C2 cost is linear in it** ($0.77 at
  5%, $2.89 at 18.8%, $6.15 at 40%). *Closes:* count `route_decision` rows at `rung >= PAGE` over
  the reference corpora, sliced by `unit.producer_family` — which is already stored, so this is a
  query and not an experiment. *Pre-committed fallback:* the cost model prints a three-point
  sensitivity band instead of a single figure, as §6.8 clause 2 already does.

- **P-Q4 — Should `--max-rung decode` be the default with no accelerator, and is that a config
  default or a policy `GATE`?** §2.6 pre-commits the *answer* — clamp `max_cost_class` to `free` when
  no accelerator probe passes — because B13's numbers make the alternative a retry loop rather than a
  slow run. What is open is the **mechanism**: a `GATE` modifier in the shipped policy (uniform with
  `gate.watcher-may-not-bill`, replayable, linted, and visible in `ow route explain`) or an
  `omniweave.toml` default (simpler, but invisible in the decision log and therefore un-replayable).
  *Closes:* a decision, informed by `ow bench service` on Metal and by whether `first_answer_seconds`
  (V01-15) holds on a scanned corpus at all. *Pre-committed fallback:* the `GATE` modifier, because
  a cost decision that does not appear in `route_decision` cannot be replayed and cannot be audited.

- **P-Q5 — What is the real Segment-level cost of a billed `derive` pass?** B16's 1,200 ms and §6's
  2,000-in/600-out token shape are both extrapolated from `SEGMENT_TARGET_TOKENS` and the prompt
  budget; lift's 9.5 s median (B17) is the only measured extraction anchor and it is *document*-grain
  on a different task, buying 90.2% field accuracy for 20.9% whole-document accuracy. **Every C3
  figure in §6 rests on this.** *Closes:* one week of `route_spend` rows for the billed graph lanes,
  which is the same instrument F6 names for `tokens_out` p95. *Pre-committed fallback:* C3's dollar
  figures are published as a band rather than a point, and `ow cost --by driver` becomes the
  recommended pre-flight for a full ingest.

- **P-Q6 — Is `instability_pct = 15` the right threshold on a real Runner over a year?** A threshold
  too tight makes every nightly `unstable` and the gate stops meaning anything; too loose and a
  genuine 12% regression hides inside Runner noise. Nothing in the collection publishes a
  before-and-after Pacer distribution. *Closes:* 90 nightly runs on `ow-bench-1`, plotting
  `|before − after| / mean`. *Pre-committed fallback:* the Pacer's own workload grows (a longer
  `blake2b` and a larger SQLite batch) until the distribution tightens, rather than the threshold
  widening — because widening the threshold is the move that makes the gate ceremonial.

- **P-Q7 — How many `route_decision` rows does one document produce?** §3.1 cannot reconcile the
  routing ledger: the charter's ~850 MB at 100k documents implies ~885,000 decisions, and my
  decomposition (430,000 parse + 116,400 escalation + one document-grain decision per enabled free
  graph lane) gives ~1.25M ⇒ ~1.2 GB, a **1.4× provisioning difference** and a 350 MB error per
  100k documents. The ambiguity is whether a free graph lane's document-grain routing writes a
  `route_decision` at all, or whether `derive_run` alone records it. *Closes:* `ow bench route`
  counting `route_decision` rows per document on the reference corpora with the full free ladder
  enabled. *Pre-committed fallback:* the ledger row in §3.1 becomes a band, and `ow store stats`
  reports `route_decision` count alongside bytes so an operator can measure their own corpus rather
  than trusting either figure.

- **P-Q8 — What is the single-store serving ceiling, in Blocks, on the reference machine?**
  [07](07-store-and-retrieval.md) §12.5 says "~10M Blocks well, 10-50M with the valve and an ANN
  backend, above that T3 or T4", and §12.4 says the lexical Channel's 50 ms budget breaks
  "somewhere between 10M and 30M" — a 3× range that decides whether a 100k-document deployment is
  one store, twelve stores or a shard fabric (§3.4). *Closes:* `ow bench query` at 10M / 20M / 30M /
  50M Blocks on `ow-bench-1`, after an FTS5 `'merge'`, reporting per-Channel p50/p95 and the Block
  count at which `lexical` first reports `UNAVAILABLE(timeout)`. *Pre-committed fallback:*
  `ow doctor` gains a store-size advisory that names the measured breakpoint and the
  `omniweave.toml [corpora]` partition command, so the operator is told before the first `degraded`
  query rather than after.

- **P-Q9 — Does the anydoc anchor survive a first-party re-measurement?** `parse.office.p50_ms = 5`
  rests on a vendor self-benchmark that excludes PDF, mixes `timing_basis` across its own columns
  (§1.1), and was authored by the winner. The basis-clean comparison is 117× over docling, not the
  257× the LibreOffice row suggests. *Closes:* `ow bench inproc` over `fixtures/office-200` on
  `ow-bench-1`, at `witness = ci`, over the **twelve media types** the card claims (ADR-8 D8.2;
  token list in [05](05-ingest-and-routing.md) §4.4). anydoc's own "fourteen formats" is the
  **benchmark denominator** of `anydoc/README.md:178` and is never a served-format count.
  *Pre-committed fallback:* the budget moves to whatever we measure and the anydoc figure becomes a
  `†` row on the scoreboard, because a budget nobody re-measured is a marketing number with a
  `budget_id`.

### Three problems found in the binding documents, followed anyway

Recorded here per the instruction to follow the charter and flag the defect rather than deviate.

- **⚠ `terminology.md`'s CI check 3 as written fails the charter, the lock file itself, and every
  document that states a prohibition.** Check 3 is *"no document contains a left-column entry from §3
  (Rejected synonyms)"*, and two of §3's left-column entries are the names of things the framework
  bans — an eval status and a gate-bypass flag. But the charter states both prohibitions by name,
  `01-principles.md` states them three times, and **§2 of the lock file itself states one of them
  inside the `EvalStatus` row**. A mechanical string check cannot distinguish a use from a ban, and
  the only way a reader learns a name is forbidden is to see it written. *This document is written to
  pass the check as it stands* — §1.2 and §8.3 state both prohibitions in the lock's own approved
  vocabulary (`pass`/`fail`, "a named override per hazard") without spelling either banned token —
  but that is a workaround, not a fix, and it makes the prohibition slightly less legible than it
  should be. *The fix, offered:* check 3 must ignore an occurrence inside a code span **and** on a
  line carrying a negation marker (`no`, `never`, `not`, `rejected`, `forbidden`, `struck`), or §3
  must gain a `bannable_by_name` column marking the rows a document may legitimately name. Until
  then G27(c) fails on `charter.md`, on `terminology.md` and on `01-principles.md`, and the correct
  response is to fix the check rather than delete the prohibitions.
- **⚠ `rss.merged4mcell_peak_bytes = 4 GiB` and the default `max_workers` are arithmetically
  incompatible on the reference machine.** §4.4 works it out: 16 default worker processes against
  `ow doctor`'s `0.8 × RAM` refusal caps `memory_mb` at 800 MB on a 16 GiB host, 5× below the
  budget. Nothing in the charter reconciles them. Resolved here by reading the 4 GiB as a **worker**
  peak and requiring the driver to declare `memory_mb = 4096`, so the refusal fires before the run
  rather than the OOM killer firing during it — but the charter should say which process the row
  bounds.
- **⚠ The charter's 100k reference ingest is presented as a whole-system reference and is only an
  ingest reference.** §3.4 shows why: it uses 4.3% of the charter's ~10⁷-*part* ceiling and 8-11× of
  [07](07-store-and-retrieval.md) §12.5's ~10⁷-*Block* serving ceiling, so the ingest completes
  comfortably and every query against the resulting single store reports `degraded` on the lexical
  Channel's 50 ms budget. Both documents are individually correct; read together they imply a
  deployment that works and does not serve. This document resolves it by naming corpus partitioning
  through `omniweave.toml [corpora]` as the T1 mitigation and by splitting §3.1's binder row into an
  ingest binder and a query binder — but the charter's reference-ingest block should say which of the
  two ceilings it is demonstrating, and P-Q8 measures the one that binds.

## New terms

Three, all narrow, all offered for merge into the lock:

| Term | Kind | Definition |
|---|---|---|
| Reference machine | concept | One of exactly three named, specified hosts on which a performance number may be measured: **`ow-bench-1`** (the pinned Pacer Runner, x86_64-linux 8c/16 GiB, no GPU — the **only** machine a `Budget` may live on, because it is the only one with a Pacer baseline), **`ow-gpu-1`** (single RTX 5090 32 GB under vLLM) and **`ow-laptop-1`** (Apple Silicon under llama.cpp Metal, `--parallel 8`, 18 GB unified). Every `eval/perf.toml` row and every `[cost.measured]` block names one. A machine change is a **baseline reset**, not a re-measurement, and the reset takes seven nightly cycles at `class = informational`. The two accelerator machines are chosen to match a third party's published throughput table so the hardware behind an `R` row is comparable to something. |
| `budget_id` | column | The `eval_perf` primary-key component naming one performance budget, spelled `<area>.<metric>[_<unit>]` — `query.warm_p50_ms`, `rss.gen5000p_peak_bytes`, `wal.bulk_index_peak_bytes`, `store.bytes_per_block`. It is the identifier a breach message, an issue title and a `BLESS.log` row all carry, so it is the join key between CI output and §2.4 of [performance](12-performance.md). Distinct from `Budget` (the D10 concept) and from `[budget]` (the config section holding admission only). Already named inside the lock's `eval_perf` row; this gives it a row of its own. |
| `ow bench` | cli | The performance-measurement group. The second word is a **positional subject from a closed set** — `pacer · cold · scheduler · inproc · parse · route · service · embed · query · encoding · incremental · compile · rss` — one function per subject in `omniweave/run/bench.py`. Not a verb, so it does not collide with the noun-shaped-verb prohibition, and not `ow benchmark`, because no two CLI groups may differ only by a suffix. |
