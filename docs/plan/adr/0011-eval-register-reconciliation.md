# ADR-11 — Seven eval suites, the byte cap as the gate, `eval/runners/`, no numeral on an uncalibrated signal, a worker-scoped RSS budget, an ingest-only 100k reference, and a `Q-G` series that is twenty-seven

**Status:** Accepted · **Priority:** 12 of 12 · **Price:** 3 ed (the Consequences table itemises 3.3), and it **adds** 4 ed to [16](../16-roadmap.md) §15.1's gate arithmetic rather than returning it (see §7)
**Discharges:** `10#F60`, `12#D2`, `12#D3`, `13#Q-Q5`, `13#Q-Q10`, `13#Q-Q11` (defect); `13#Q-Q6` (adjacent)
**Charter errata claimed:** `E84`-`E89` (block `E84`-`E89`, all six used)
**Supersedes:** none
**Blocks / unblocks:** P10 cannot compute its own gate count. `V10-1` ([00](../00-vision.md):724) requires "all **27** `G` gates and all **23** `Q-G` gates green" while [13](../13-quality.md) defines `Q-G1`-`Q-G27`. **Must land after ADR-2** — both amend that one sentence. Unblocks `ow eval release-check`'s zero-`unknown` requirement, `Q-G14`/INV-19's renderer test, `Q-G15`'s budget arithmetic, and the `eval/runners/` tree P10 builds against.

## Context

Six defect rows and one decision row, every one a number or a path that a reader who counts will
find. They are quoted here because a row that does not say what an ADR needs it to say is a finding,
not a rounding error.

| row | [17](../17-risks.md) | the contradiction, verbatim |
|---|--:|---|
| `13#Q-Q5` | :694 | "charter tension: the pyramid says \"T4 eval — five suites\" and `eval_run.suite`'s `CHECK` admits seven" |
| `13#Q-Q10` | :699 | "charter tension: `outline` \"suppressed above 500 pages\" versus `Q-G2`'s 256 KiB cap, which binds at 23-46 pages — an order of magnitude earlier" |
| `13#Q-Q11` | :700 | "`evals/runners/` or `eval/runners/`? D10 writes the first, D1's repository tree contains only `eval/`" |
| `10#F60` | :660 | "the charter's worked Answer prints an uncalibrated confidence as a numeral (`conf = 0.98`, `0.71`, `0.71 layout`), which `Q-G14`/INV-19 forbid" |
| `12#D2` | :688 | "`rss.merged4mcell_peak_bytes = 4 GiB` and the default `max_workers` are arithmetically incompatible: 16 workers against `ow doctor`'s `0.8 x RAM` refusal caps `memory_mb` at 800 MB on a 16 GiB host, 5x below the budget" |
| `12#D3` | :689 | "the charter's 100k reference ingest is presented as a whole-system reference and is only an ingest reference … the ingest completes and every query against the resulting store reports `degraded` on the lexical Channel" |
| `13#Q-Q6` | :695 | "Counters are defined over three sources and `Q-G24` needs a fourth, so the test inventory is a byte-diff gate and is not visible in `eval_counter` or the scoreboard" |

**Every one of the six is already read correctly by a plan document, and none of the readings is
binding.** [13](../13-quality.md) §2.5 reconciles five-versus-seven, §5.2 multiplies the byte cap out,
§8.7 picks `eval/runners/`; [10](../10-interfaces.md) §3.5-3.6 renders `layout: high (uncal.)`;
[12](../12-performance.md) §4.4 attributes the 4 GiB to a worker and §3.4 splits the 100k ceilings.
In all six cases the **charter still carries the other reading**, and the charter is immutable. That
is what makes this an ADR and not a repair: the live work is a §9.2 erratum per locus, one
enforcement clause each so the defect cannot recur, and one arithmetic correction nobody has made.

**The `Q-G` count is stated three ways and the roadmap's schedule depends on the wrong one.**
[13](../13-quality.md) defines `Q-G1` through `Q-G27` and §13.1 adds `Q-G24`-`Q-G27` explicitly;
[01](../01-principles.md):32 and :75 both state the range as `Q-G1`-`Q-G23`;
[00](../00-vision.md):724 and [16](../16-roadmap.md):11 both say 23. And
[16](../16-roadmap.md):1049 — §15.1 basis rule 3 — **still computes**:

> **Gate.** 1 engineer-day per `G` or `Q-G` gate script. 27 + 23 = 50 gates ⇒ 10 ew, distributed into
> the phase that first needs each — never batched into P10, which is why P10 is 30 ew and not 40.

[16](../16-roadmap.md):191 repeats it as "the 50 gates" in P10's one-line goal. That is the thread
[final-review.md](../_notes/final-review.md) §7 item 2 says to pull.

## Decision

### 1. Seven suites, five with a model in the loop. `eval_run.suite`'s `CHECK` is the register

`parse`, `extract`, `retrieve`, `absence`, `roundtrip`, `portability`, `perf` — the seven the
charter's own DDL admits (`charter.md`:7164-7165). The charter's pyramid line "T4 eval — five suites,
live models" is superseded by [13](../13-quality.md) §2.5's reading: the same seven, **split by
whether a model is in the loop**. `portability` and `perf` reach no model and ride the T4 job because
they need the same pinned runner. The T4 pyramid row reads *seven suites, five with live models*, and
`--cassette required` continues to bind on the five and not on the two.

**Erratum `E84`** — charter `:7087`, superseded by [13](../13-quality.md) §2.5.

### 2. `MAX_REDUCTION_BYTES = 262_144` is the gate; the 500-page rule is a retained pre-check

Both charter sentences survive, with their roles named. The byte cap is what `Q-G2` fails on; the
page rule is a **performance guard only**, stopping the reducer from materialising ~45 MB of
`outline` lines before discovering it cannot commit them ([13](../13-quality.md) §5.2). It is not a
second threshold and may not be quoted as permissive.

`outline_suppressed_because` is a **closed two-value vocabulary**, `{"bytes", "pages"}`, evaluated in
that order: the reducer estimates `outline_blocks × ~96 B` before building a line and records
`"bytes"` whenever that estimate exceeds 262,144. `"pages"` is therefore reachable **only** below
`2730 / 500 ≈ 5.46` blocks per page — eleven times under `F1`'s 60-120 envelope
([13](../13-quality.md):612) — so a reviewer seeing `"pages"` in a sidecar knows it is a fact about a
near-empty scanned deck, not about the cap.

**Erratum `E86`** — charter `:7104`, `:7316` and `:7416`, superseded by [13](../13-quality.md) §5.2.

### 3. `eval/runners/`, and [11](../11-repo-layout.md)'s tree gains the directory

A path in an implemented tree beats a path in prose. [11](../11-repo-layout.md):57 and :383 both
write `eval/` and never `evals/`. But :57's contents list — "gates · counters · perf · results ·
calibration · baselines" — **does not name `runners`**, so `eval/runners/` is today a path in no tree
at all. The line gains `runners`, and §1.7's `eval/` expansion gains one row:
`runners/  competitor adapters, in-tree and unpackaged (G2)`.

**Erratum `E85`** — charter `:7075`, superseded by [11](../11-repo-layout.md) §1.7 and
[13](../13-quality.md) §8.7.

### 4. The worked Answer's `conf` column is retired outright, not reinterpreted

[10](../10-interfaces.md) §3.5-3.6 is the sole home of the provenance table. The column is `score`,
not `conf`; it renders `<kind>: <ordinal>` plus `(uncal.)` while `Calibrated.status != "calibrated"`,
and `–` where the `(score, score_kind)` pair is NULL. The two cells become:

| cite | charter `:6580`-`:6581` | ruling ([10](../10-interfaces.md):618-620) |
|---|---|---|
| `d7#412` | `0.98` | `–` — a `text_layer` extraction has no producer score at all |
| `d7#418` | `0.71`, and `0.71 layout` in the evidence header | `layout: high (uncal.)`, and `layout: high (uncalibrated)` in the header |

**This ADR rejects [10](../10-interfaces.md)'s own charitable reading** that the charter's example
"shows the *calibrated* case". No calibration state rescues `0.98`: `Hit` carries no per-hit
retrieval confidence anywhere in the framework ([07](../07-store-and-retrieval.md) §7.1;
[10](../10-interfaces.md):696-699), so that cell has no producer under any `CalStatus`. The `0.71`
cells would be legal only under a calibrated `layout` curve, and release 1 has none.

**Erratum `E87`** — charter `:6568` and `:6577`-`:6581`, superseded by [10](../10-interfaces.md)
§3.5-3.6. The renderer test over all four `CalStatus` values is already registered
([13](../13-quality.md):1900) and regenerates the example.

### 5. `rss.merged4mcell_peak_bytes` bounds a **worker**, and `[[budget]]` gains a `process` key

The 4 GiB figure is a worker peak. A driver that can reach it declares `memory_mb = 4096` on its
card; `ow doctor` then refuses sixteen workers at that size on a 16 GiB host and prints the
arithmetic, and the operator lowers `max_workers` for the hosting class to 3
(`12.8 GiB / 4 GiB = 3.2`) — a refusal with numbers before the run, not an OOM kill at hour six
([12](../12-performance.md) §4.4). The shipped anydoc card's `memory_mb = 512` is correct precisely
because sixteen of it fit.

**The recurrence guard is the schema.** Every `[[budget]]` row in `eval/perf.toml` whose `id` starts
`rss.` declares `process`, over the closed vocabulary `{supervisor, worker, driver_subproc,
service}`, and `tools/gate_budgets.py` — already the `Q-G15` script for the
`value + tol_abs <= tier ceiling` property ([13](../13-quality.md) §2.9) — asserts presence and
vocabulary. One clause on an existing gate; this ADR **coins no new `Q-G` number**.

**Erratum `E88`** — charter `:7606`-`:7610`'s `[[budget]]` row and the "the file's shape is the
charter's, verbatim" contract it fixes ([12](../12-performance.md) §2.4), superseded by
[12](../12-performance.md) §4.4 and §2.4.

### 6. The 100k reference is an **ingest** reference; the binder row splits in two

| binder | value | the 100k reference against it |
|---|---|---|
| ingest | ~10⁷ **parts** on one host | 430,000 routed parts — **4.3%** |
| query | ~10⁷ **Blocks** in one `.owstore` ([07](../07-store-and-retrieval.md) §12.5) | 80M-108M Blocks — **8-11× past it** |

The first binder to break is the lexical Channel's 50 ms budget, which reports `UNAVAILABLE(timeout)`
and **forces `degraded` on every query** — visible, not silent. `PREFILTER_MAX = 200_000` is exceeded
400× (a disclosed over-fetch mode, not a failure), and `VEC_BRUTE_MAX = 250_000` binds third and only
if vectors were turned on, which the shipped default does not. **The T1 mitigation is `[corpora]`
partitioning**: N stores of ≤ 10M Blocks, roughly twelve on this mix, reached by configuration rather
than by a rewrite ([12](../12-performance.md) §3.4).

**This is an interim position with a pre-committed fallback**, which is why the status is `accepted`.
The query binder is a 3× range — "~10M well, 10-50M with the valve" against "somewhere between 10M
and 30M" — and the measurement is `12#P-Q8` ([17](../17-risks.md):685): `ow bench query` at
10M/20M/30M/50M Blocks after an FTS5 `'merge'`, reporting the Block count at which `lexical` first
times out. **Until it runs, twelve stores is the published planning number**, and the fallback is
`12#P-Q8`'s own: `ow doctor` gains a store-size advisory naming the measured breakpoint and the
`[corpora]` partition command.

**Erratum `E89`** — charter `:4703`-`:4706` (the `★ HONEST CEILING` line), superseded by
[12](../12-performance.md) §3.4.

### 7. The `Q-G` series is closed at **twenty-seven**, and the roadmap's gate arithmetic is a debit

`Q-G1`-`Q-G27`. `V10-1`'s `23` becomes `27`; [01](../01-principles.md):32 and :75's `Q-G1`-`Q-G23`
become `Q-G1`-`Q-G27`; [16](../16-roadmap.md):11 and :191 follow. §15.1 basis rule 3 becomes:

> **Gate.** 1 engineer-day per `G` or `Q-G` gate script. 27 + 27 = 54 gates ⇒ **10.8 ew**.

**The sign is negative and the plan's own index has it backwards.** [17](../17-risks.md):795 describes
the move as one that "corrects [16](../16-roadmap.md)'s `27 + 23 = 50` gate arithmetic by four
engineer-days", and [`README.md`](README.md) §7 reads that as ADR-11 being "the only entry that
returns time". At 1 ed per gate script, four more gates are **four more engineer-days of work**, not
four recovered: 50 ed ⇒ 10 ew becomes 54 ed ⇒ 10.8 ew, against a total program buffer of 6 ew
([17](../17-risks.md) `R-A1`, 1.6%). The four land in the phase that first needs each, per rule 3's
own distribution rule: `Q-G24` and `Q-G25` in P1 with the harness; `Q-G26` and `Q-G27` in P10 with
the corpus and the scoreboard.

**Ordering.** ADR-2 edits `V10-1`'s literal `27` for the `G` series via `11#OQ-10`; this ADR edits
its literal `23`. Two ADRs editing one sentence land in that order, or in one PR.

### 8. `eval_counter` admits no `scope = 'ci'` row (`13#Q-Q6`)

Upheld, and the DDL is the reason rather than the bias: `eval_counter`'s primary key is
`(run_id, counter, scope)` with `run_id NOT NULL REFERENCES eval_run(run_id)`
(`charter.md`:7237-7240). A counter measuring the test suite has no run and is unrepresentable.
`eval/inventory.toml` stays a byte-diff artefact under `Q-G24`.

**But the file and the table are different objects, and [11](../11-repo-layout.md) has already
crossed the line.** [11](../11-repo-layout.md):1627 asserts that each CI job "writes its wall time to
the Counter `ci.job_seconds.<job>`, which ratchets in `eval/counters.toml`" — a Counter with none of
the lock's three sources and no `run_id`, exactly the shape `13#Q-Q6` says should not exist. The
ruling separates them: **`eval/counters.toml` rows gain a required `source` key** over the closed
vocabulary `{manifest, route_spend, driver_observation, ci}`; `Q-G5` reads it and compares only the
three run-sourced classes against their sources; a `source = "ci"` row never reaches `eval_counter`
or `eval_scoreboard`. `ci.job_seconds.<job>` is the first and, at release 1, the only `ci` row.

## Alternatives rejected

### Correct the pyramid to "seven suites" and delete the five/two distinction

At its best this is one word in one line and it removes a reader's need to hold two numbers.
Rejected because the split is load-bearing three times over: `--cassette required` binds only on the
five that can reach a model ([13](../13-quality.md) §12.2 rule 4), the T4 ≤ 90 min budget is spent
almost entirely on those five, and `portability` and `perf` are the two suites whose failure means
"the runner changed" rather than "the model changed". Collapsing to a single number deletes the
distinction that tells a reviewer which of those two happened.

### Raise `MAX_REDUCTION_BYTES` so the 500-page rule binds first

The honest version of this argument is that the charter's page rule was written with an intent —
*a 500-page document is too big to review by diff* — and a byte cap that fires at 23 pages defeats
it. Rejected on repository arithmetic: `outline` at ~96 B per line and 60-120 blocks per page needs
**~4.6 MB** to reach 500 pages at F1's midpoint, against `Q-G2`'s 64 MB Tier-A total and 4 MB
per-binary cap ([13](../13-quality.md):375). Two such fixtures would consume 14% of the whole fixture
budget for a file no human diffs. The 40-page, 24-document Deep golden is the artefact that carries
per-block detail, and its bound and `outline`'s land in the same place for the same reason.

### Change [11](../11-repo-layout.md)'s tree to `evals/` and keep the charter's spelling

Close on the merits — the charter is upstream, and following it looks like one character in one tree
line instead of an erratum. Rejected because it is not one character: `eval/` names nine declaration
files quoted inside gate scripts (`gates.toml`, `counters.toml`, `perf.toml`, `corpora.toml`,
`quarantine.toml`, `inventory.toml`, `BLESS.log`, `baselines/`, `results/**`) plus
[glossary.md](../glossary.md):937. The charter writes `evals/` **once**, and only for the `runners/`
subdirectory. Following the minority spelling renames nine gated files to match one prose noun.

### Accept the charter's worked Answer as a calibrated rendering ([10](../10-interfaces.md)'s own reading)

Genuinely the closest call here, and it is [10](../10-interfaces.md)'s stated position, so it is
rejected explicitly rather than by omission. Its strength: it preserves the charter's example intact,
costs no erratum, and is true of the `0.71 layout` cells the day a `layout` curve is calibrated.
Rejected because it is not true of `0.98`. There is no per-hit retrieval confidence in the framework
at any calibration status, so preserving that cell requires either inventing one or special-casing
`conf` by score kind — and a score-kind allowlist in the renderer is the mechanism `Q-G14` exists to
forbid ([10](../10-interfaces.md):2653-2655). An example legal only under a type the plan does not
have is retired law, not a special case.

### Derive `memory_mb` from a measured per-driver peak rather than a declaration

Attractive because a declared number is a guess and `12#D2` exists because two guesses collided.
Rejected on availability: the measurement is `F29`'s cell-count sweep
([12](../12-performance.md) §4.3) on `ow-bench-1`, while `ow doctor` must decide on a **fresh install
with no measurements at all**. A refusal that cannot fire until after the first pathological run is
not a refusal. The declaration is checkable — `ow drivers verify` re-runs the kit against installed
bytes — and a wrong one is a card defect with an owner.

### Keep `Q-G` at twenty-three and demote `Q-G24`-`Q-G27` to `[[job_assertion]]` rows

This is ADR-2's mechanism for the `G` series and the symmetry argument is real: no amendment to
`V10-1`, no roadmap re-pricing. Rejected because `ow eval release-check` refuses on `unknown`
**gate** results and `[[job_assertion]]` rows are not in its inventory, so four checks that catch a
silently deleted test suite, a misplaced marker, corpus leakage and metric rot would become invisible
to the release gate they exist to protect. It saves no engineer-days either — a job assertion still
has to be written.

### Admit `scope = 'ci'` to `eval_counter` with a sentinel `run_id`

At its best this puts test count on the scoreboard, where a number nobody sees is a number nobody
defends. Rejected because a sentinel FK row is a second home for "this is not a run", and every
`eval_scoreboard` query would need a predicate to exclude it — the shape charter §8 rejection
criterion 19 names. §8's `source` key gets the visibility without the sentinel.

## Consequences

| # | obligation | document | price |
|---|---|---|--:|
| 1 | T4's pyramid row reads *seven suites, five with live models*; §2.5's reconciliation becomes normative and Q-Q5 closes | [13](../13-quality.md) §2.5 | 0.2 ed |
| 2 | §5.2 names the byte cap the gate and the page rule a pre-check; `outline_suppressed_because`'s two-value vocabulary and the 5.46-blocks/page reachability note land in §4.5's sidecar spec | [13](../13-quality.md) §4.5, §5.2 | 0.4 ed |
| 3 | §1.7's tree line gains `runners`, and the `eval/` expansion gains its row | [11](../11-repo-layout.md):57, §1.7 | 0.2 ed |
| 4 | §3.6's worked Answer and §3.5 item 5 are marked the sole home of the provenance table; the Open-questions F60 entry closes | [10](../10-interfaces.md) §3.5-3.6 | 0.2 ed |
| 5 | `eval/perf.toml`'s `[[budget]]` schema gains `process`; `tools/gate_budgets.py` gains the presence-and-vocabulary assertion under `Q-G15` | [12](../12-performance.md) §2.4, [13](../13-quality.md) §2.9 | 0.5 ed |
| 6 | §3.4's two-binder split becomes the reference statement; the twelve-store planning number is published with `12#P-Q8` named as what revises it | [12](../12-performance.md) §3.4 | 0.3 ed |
| 7 | `V10-1`'s `23` → `27`, **after ADR-2's edit to the same sentence** | [00](../00-vision.md):724 | 0.1 ed |
| 8 | `Q-G1`-`Q-G23` → `Q-G1`-`Q-G27` at two loci | [01](../01-principles.md):32, :75 | 0.1 ed |
| 9 | §15.1 rule 3 becomes `27 + 27 = 54 ⇒ 10.8 ew`; :11 and :191's "50 gates" follow; §3's P10 row and the 363 ew total absorb 4 ed | [16](../16-roadmap.md):11, :191, :1049 | 0.6 ed |
| 10 | `eval/counters.toml` rows gain `source`; `Q-G5` reads it; §6.2's `ci.job_seconds.<job>` is declared `source = "ci"`; Q-Q6 closes | [13](../13-quality.md) §2.8, [11](../11-repo-layout.md) §6.2 | 0.4 ed |
| 11 | errata `E84`-`E89` are inserted into charter §9.2 — **by a later stage; no agent in this stage edits the charter** | [charter.md](../_notes/charter.md) §9.2 | 0.3 ed |

**What this costs.** Four engineer-days added to [16](../16-roadmap.md)'s gate line, against a 6 ew
program buffer. That is the finding, and it is the opposite sign from the one the index carries.

**What becomes harder.** Every future `Q-G` gate now costs an amendment to `V10-1`'s literal count as
well as a script — the defect `11#OQ-10` raises for the `G` series and ADR-2 resolves by replacing
the literal with "every row in `tools/gates.toml`". If ADR-2 lands that, the `Q-G` half should follow
with "every row in `eval/gates.toml`" in a later change; this ADR does not pre-empt it, because ADR-2
owns the mechanism and two halves out of step is worse than either.

**What a future reader must not do.** Do not quote "five suites", "suppressed above 500 pages",
`evals/runners/`, `conf = 0.98` or `27 + 23 = 50` from the charter — each is retired law with a named
erratum and a named successor. Do not add a `Q-G` gate without moving the count in all four places
listed above in the same PR.

**Names this ADR coins**, handed to ADR-1's bulk lock pass rather than written into the lock here:
the `process` budget key and its four-value vocabulary, and `source` on a Counter row with its own.

**Errata:** `E84`-`E89` claimed — all six of ADR-11's block, which is why
[`README.md`](README.md) §6 sets the block width at six.

## Open

1. **`12#P-Q8` is unrun and it moves the twelve-store number.** The query binder is a 3× range and
   the partition count scales inversely: at 30M Blocks per store the same corpus is four stores, not
   twelve. §6 carries the interim position and the fallback; what is open is the number, not the
   mechanism.
2. **`Q-G26` and `Q-G27` have no work item in [16](../16-roadmap.md) §13's P10 list.** §7 places them
   there by rule 3's own distribution rule, but P10's items were priced against 50 gates; whether the
   4 ed lands as a new item or inside an existing W10.x is [16](../16-roadmap.md)'s call.
