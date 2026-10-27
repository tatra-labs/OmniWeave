# D4 — The routing and escalation policy engine
## Proposal: THE SHIPPING PRAGMATIST

---

## Headline

**Routing is a compiled data file, not code: a versioned `route.yaml` ladder whose gates are closed
expressions over a closed, versioned set of cheap CPU signals; every decision writes a `RouteRecord`
containing the full signal vector, so any decision replays exactly and any candidate policy can be
simulated over 30 days of history for free; cost is measured in physical units (`wall_ms`, `cpu_ms`,
`accel_ms`, `tokens_in`, `tokens_out`, `calls`) and converted to money by a separately-versioned
price sheet; and the router learns only offline — the escalation rate the ladder already produces is
the label generator, a promoted `scoreboard_snapshot` is the only way learning reaches a decision,
and a human merges the diff.**

Three weeks to the first thing a user runs: `omniweave parse` on a mixed corpus where a clean
digital PDF never starts a GPU.

---

## 0. Terms I am coining, because they propagate to D5–D10

| Name | Means | Why this word |
|---|---|---|
| **`Driver`** | A named, versioned implementation of one **capability** on one unit — `text.pdf.pdfium`, `ocr.page.olmocr`, `table.grid.cpu`, `extract.schema.vlm`. | The decision statement's own word. It is the noun a user sees in a bill line and in `route explain`. |
| **`Capability`** | What a caller asks for: `text`, `layout`, `table`, `math`, `fields`. Drivers register *under* a capability; the router chooses among the ones registered for the requested capability. | Lets eligibility be a set intersection instead of a conditional. |
| **`Signal`** | One named, cheap, pure observation about a unit, with a declared type and range, in a versioned registry (`signal_suite: 3`). | Signals are the only vocabulary a policy may name. Closed namespace = auditable policy. |
| **`Rung`** / **`Ladder`** | One tier of escalation / the ordered list of them. `Ladder` is the whole routing program. | Reads correctly in logs: "escalated from rung `1-decode` to rung `3-page-ocr`." |
| **`Gate`** | A named boolean over signals that a rung's output must pass to be accepted. | `gate_fail` is the free quality label. |
| **`RouteRecord`** | The immutable per-(unit, part) decision record. Replay input + replay output + degradations + overrides + actuals. | The single artifact that makes routing honest, auditable, replayable and simulatable. |
| **`Cost`** | A 6-field vector of **physical** units. Money is derived, never reported. | See §3. |
| **`PriceSheet`** | Versioned physical-units → micros conversion. | Lets you re-price history and compare self-host against hosted in one currency. |
| **`Scoreboard`** | Rolling per-`(driver, driver_version, corpus_id, unit_class, day)` counters. | The learning surface. |
| **`Degradation`** | `{code, rung, driver, reason}` — appended to the record, to `page_stats`, to the block, and to the serve envelope. | Nothing degrades silently. |

**One name I am overturning.** `mine-runtime.md` §7.1.3 uses `ctx.driver(kind)` for *resources*
(model clients, DB handles). That collides with the noun this decision needs, and this decision's
noun is the one users read. **Rename it `ctx.resource(kind)`.** Everything else in `mine-runtime.md`
§7 I adopt as given; this proposal is the `plan()` function that §7.3 leaves as a hole, and the
`Router` is the only producer of `work` rows.

---

## 1. What the evidence forces before any design happens

**The OCR-error-detection model is not available to us.** `_plan/_notes/DIGEST.md` risk §, from
`marker/MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`): clause 2(c) bars use by any
product that competes with Datalab, with no revenue threshold and no research carve-out, and clause
8 (`marker/MODEL_LICENSE:39`) makes the licence viral on **Output**. surya's `OCRErrorPredictor`
DistilBERT checkpoint — the classifier `marker/builders/line.py:220-247` gates its whole ladder on
— is under that licence. So is surya's layout model, so is marker's `FastLayoutPredictor` (rf-detr,
served from surya), so are lift's weights. The *code* is Apache-2.0 and free to read.

Two of marker's four page signals therefore cannot be shipped as-is:

- **signal 2, `garble_score`** — needs a model we cannot use.
- **signal 3, `layout_coverage`** — needs a layout model we cannot use.

A proposal that writes `garble_score: surya.OCRErrorPredictor` into a policy file has wasted the
run. §2.2 below replaces both with licence-free CPU signals, and that substitution is the single
highest-leverage piece of engineering in this proposal.

**Everything else in the evidence points the same direction:**

- Per-page, not per-document. docling's `do_ocr` is a document boolean and it is why a born-digital
  report with a 40-page scanned appendix either pays VLM for all 300 pages or returns garbage for 40
  (`mine-parse.md` B2). marker's measured win is that a clean digital document *never spawns the
  inference server* (`marker/builders/line.py:121-124`).
- Keep the **score**, not the label — marker gates the per-block recheck on page `P(bad) >= 0.05`,
  which is only expressible because surya returns `scores` (`mine-parse.md` B2 closing rules).
- docling **computes the best per-page quality signals in the collection and consumes none of them**
  (`digest-parse`: "The signal and the router are one feature: ship both or neither").
- Retries are the largest attacker-controlled cost amplifier: `olmocr/pipeline.py:107,1221` →
  8000 tokens × 8 retries = 64,000 tok/page = **64×**, fired **in parallel** on an idle queue
  (`:343-350`), `--max_concurrent_requests` default **1600** (`:1224`). `Unlimited-OCR/infer.py:21-36`
  → `MAX_RETRIES=5 × REQUEST_TIMEOUT=1200` = **100 GPU-minutes per document**. The control is a
  budget, not a retry count (`mine-risk.md` §22.2).
- Silent degradation is the recurring sin: `Unlimited-OCR/infer.py` returns `{"text": ""}` after 5
  failed retries; lift prints-and-drops `response_format` on schema-compile failure; olmocr's
  `PdfFilter` drops every form and non-English document with a `logger.info` only. Every one of those
  is a `Degradation` in this design.
- Escalation granularity is economics: **one full-page OCR request is ~7× cheaper than N block
  requests on llama.cpp** (`marker/builders/ocr.py:80-82`), and more accurate because crops lose
  context. So the promote fraction is the knob that expresses the economics, and `0.0` (balanced,
  any bad block promotes) is the right default.

---

## 2. The design

### 2.1 The three-file policy surface

```
policy/route.yaml         the Ladder: rungs, drivers, gates, budgets, overrides, profiles
policy/pricesheet.yaml    physical units -> micros, versioned separately
policy/snapshots/*.json   frozen Scoreboard snapshots; the only path from data to a decision
```

All three are digested into `policy_digest` (canonical JSON, `sha256_canonical` from
`mine-runtime.md` §7.5 — `sort_keys=True`, `allow_nan=False`, **never** `"".join`). `policy_digest`
enters every cache key, every `RouteRecord`, and the `work` row. A change to it sets the full-scan
latch (`mine-runtime.md` §7.9). `omniweave show-config` prints it.

Policy is **data with a closed expression language and no import mechanism.** This is not aesthetic
preference: `marker`'s `--converter_cls` / `--processors` / `--llm_service` accept arbitrary dotted
paths and are settable from `--config_json`, which is an RCE channel the moment config arrives in a
request body (`mine-parse.md` C-section). A policy file that can name a Python path is a policy file
that can be a payload.

The expression language (`omniweave/route/expr.py`, ~150 lines) is total and closed:

```
expr := or
or   := and ("or" and)* ;  and := not ("and" not)* ;  not := "not" not | cmp
cmp  := sum (("=="|"!="|"<"|"<="|">"|">=") sum)? | sum "in" list
sum  := term (("+"|"-") term)* ;  term := atom ("*" atom)*
atom := NUMBER | STRING | BOOL | root "." ident | "(" expr ")" | fn "(" args ")"
fn   := min | max | abs | clamp | ratio          # exactly five, no others, ever
root := signals | profile | page | block | budget | policy
```

No division (`ratio(a,b)` returns `0.0` when `b == 0`, so evaluation cannot raise), no indexing, no
lambdas, no user functions, no attribute access outside six roots. Compiled once at load into a
frozen tuple-AST; evaluated by a recursive `match`. **Every identifier under `signals.` must exist
in the signal registry for the declared `signal_suite`, or policy load fails closed** — that is
`omniweave route lint`, and it is a CI gate.

When a rule genuinely needs code, **it becomes a Signal, not an expression feature.** That is the
rule that keeps this file from growing a template engine.

### 2.2 The signals — and the two licence-free replacements

`omniweave/route/signals/`, one module per group, all pure, all cached by `content_digest`.

**Static, per document (`static.py`)** — free, from bytes and container:
`bytes`, `detected_format`, `format_family`, `page_count`, `encrypted`, `producer`, `has_forms`,
`is_tagged_pdf`, `dup_of` (corpus-level content-digest hit).

**Text-layer, per page (`textlayer.py`)** — ~1.2 ms/page from pdfium:
`char_count`, `has_text_layer`, `cid_ratio`, `replacement_ratio`, `token_count`,
`mean_token_len`, `char_stream_monotonicity`.

**`ink_coverage` — the licence-free replacement for marker's `layout_coverage`.** Render the page
once at 96 DPI (which is the structure tier's render anyway — `mine-parse.md` E8), divide into 8-px
tiles, mark a tile *inked* if any pixel is below 0.85 relative luminance, and compute

```
ink_tiles       = count(inked tiles)
ink_coverage    = ratio(inked tiles intersecting a text-layer line bbox, ink_tiles)
overlap_fraction= marker's, verbatim: line bboxes inside page.expand(5,5);
                  intersect_counts = (intersection_matrix > 0.1).sum(axis=1);
                  ratio(count(intersect_counts > 2), n_lines)
```

`ink_coverage >= 0.25` is marker's `layout_coverage_threshold` with the *layout model's opinion*
replaced by *actual ink*. This is arguably the better signal — it does not inherit a detector's
false negatives — and it needs no weights. Cost: ~8–14 ms render + ~2 ms scan per page. marker's
blank-page escape hatch (`line.py:343-345`, "the model sometimes says there is one text block on a
blank page") ports cleanly and gets *simpler*: `ink_tiles <= 4 → accept`.

Note the discipline boundary: binarizing a page before a **VLM** is forbidden (`Ollama-OCR`'s
72-DPI-then-Otsu is named as actively harmful, `digest-parse` Traps). Thresholding a page to compute
a **routing statistic** is not that. The tile mask never reaches a model.

**`garble_score` — the licence-free replacement for surya's `OCRErrorPredictor`.** A calibrated
logistic regression over seven CPU features, ~1 ms/page, no weights to license:

| feature | why |
|---|---|
| `f1 = ratio(cid_glyph_runs + U+FFFD, chars)` | broken/absent CMap. Highest single-feature AUC in practice. |
| `f2 = ratio(chars outside document-dominant Unicode blocks, chars)` | script scrambling |
| `f3 = 1 - dictionary_hit_rate` (20k-token frequency list per detected language, tokens ≥ 3 chars) | the classic garble tell |
| `f4 = ratio(single_char_tokens, tokens)` | a broken CMap emits space-separated glyphs |
| `f5 = char 5-gram log-prob / char` (model fitted on **our own** clean extractions — our data, no licence) | catches plausible-looking noise |
| `f6 = 1 - char_stream_monotonicity` vs geometric order | a scrambled text layer |
| `f7 = ratio(vowelless_runs, tokens)` (Latin scripts only) | ligature/encoding collapse |

`garble_score = sigmoid(w·f + b)`. Fitted on ~2,000 hand-labelled pages (~300 garbled), roughly two
person-days of labelling. **We keep the score, not the label** — that is the whole point, and
`route lint --calibration` is a CI gate asserting **ECE ≤ 0.05 and Brier ≤ 0.08** on a held-out set,
because marker's `>= 0.05` gate is meaningless against an uncalibrated probability. A calibration
regression fails the build.

**Corpus/page-class (`corpus.py`)**: `language`, `spam_score` (olmocr's 13-word lexicon shape,
threshold 0.004), `is_form` (`get_form_text_fields()`), `layout_stability` (page-to-page ink-tile
histogram distance — the precondition for the long-horizon rung), `cross_page_table_rate`
(tables touching a page edge, measured from a completed per-page run), `image_tokens` (from render
dimensions, drives the estimate).

**`unit_class(signals) -> str`** is a pure versioned function producing a coarse deterministic
bucket — `pdf/digital/clean/tabular`, `pdf/scan/garbled/prose`, `ooxml/native/dense` — and it is the
Scoreboard's key. Quality is per `(driver × unit_class)`, never per driver: a driver that wins on
born-digital invoices loses on scanned CJK.

**Sampling, because 4,000 pages × 15 ms = 60 s of routing.** The policy declares
`signal_sampling: {head: 8, stride: 32, cap: 96}`. Signals for sampled pages establish a
**document prior** that picks the *initial* rung; every page actually parsed gets its own signals
computed (for free, from the render it already needs) and **the per-page verdict always overrides
the prior**. The prior can only be wrong about which rung is tried first, never about what is
accepted.

### 2.3 The Ladder

Rungs adopt `mine-parse.md` B2's generalised ladder, with marker's numbers as the shipped defaults.

```
0 preflight     document  static gates: format, encryption, size, page cap, corpus filter, dedup
1 decode        page      text.office.native | text.pdf.pdfium              FREE
2 block-repair  block     ocr.block.olmocr (fast profile only)              LOCAL_COMPUTE/BILLED
3 page-ocr      page      ocr.page.olmocr                                   LOCAL_COMPUTE/BILLED
4 validate      page      free post-hoc gates on any rung's output          FREE
5 regenerate    page      same driver, temperature ladder, failed subset    same class
6 structural    page      text.pdf.pdfium marked is_fallback                FREE
7 long-horizon  document  ocr.doc.longctx — opt-in, earned, hard-capped     LOCAL_COMPUTE
S bypass        document  extract.schema.vlm — a bypass EDGE, not a rung    BILLED
```

**Rung 4 is the honesty engine and it is free.** Every driver's output passes the same gates
regardless of which rung produced it: repeat-loop detection (lift's two-pass — whole output *and*
`cut_from_end=50`; window scaled 128 single-page / **1024** multi-page, `Unlimited-OCR`'s actual
values, `no_repeat_ngram_size=35`), `finish_reason == "stop"`, `total_tokens <= context`,
HTML re-parse success, `is_valid_nonempty` (`mine-runtime.md` §7.1.2), blank-region hallucination
check. A gate failure is a *free label* saying the driver failed on this unit. That is where the
learning loop gets its data.

**Rung 2 eligibility is a denylist, ported with marker's reasoning intact:** never
`PageHeader, PageFooter, Picture, Figure, Diagram, Table, Form, TableOfContents, Equation,
Chemical`. marker's own comment is the rationale — "a single flagged footer forces an otherwise-clean
doc to spawn the inference server" (`marker/builders/line.py:121-124`). An empty layout box is OCR'd
only if `>= 1%` of page area, not `>= 75%` contained in a text-bearing sibling, and actually inked.

**Promotion is one number.** `promote_fraction: 0.0` in `balanced` (any bad block promotes the page
to one full-page call, because that call is ~7× cheaper than N block calls), `0.5` in `fast`.

**Rung 7, the long-horizon path, must be *earned*.** `Unlimited-OCR`'s `infer_multi` is one blob:
no per-page retry, no resume, and a repeat loop poisons everything after it
(`mine-parse.md` A11.2's own comparison table). So it is off by default and its `enabled_when` is
`signals.cross_page_table_rate > 0.15 and signals.layout_stability > 0.85 and signals.page_count <= 120`
— i.e. you turn it on for a corpus by *measuring* that per-page routing is losing cross-page tables.
Its budget is capped at `wall_ms: 300000, attempts: 1`, against the repo's own
`MAX_RETRIES=5 × REQUEST_TIMEOUT=1200 = 100 minutes`.

**Rung S, lift's schema shortcut, is a bypass edge with declared forfeits.** When the caller supplies
a JSON Schema and `capability: fields`, the router may skip rungs 1–6 entirely and send page images
to a constrained-decoding driver. Two hard rules:

1. The driver declares `forfeits: {blocks, spatial, charspan, citation, round_trip}` and the record
   marks `representation: none`. The serve layer **refuses** a citation request against such a
   result rather than fabricating one.
2. Never a document-level pass/fail. lift's own adversarial benchmark is **90.2% per field but
   20.9% full-document** (`lift/README.md`), so the bypass returns per-field confidence and a review
   surface. It is a latency feature for a known-good corpus, not a default.

The technique is reimplemented, not vendored: `make_properties_nullable` before constrained decoding
(`lift/model/vllm.py:26-45` — without it the grammar *forces* the model to invent values), explicit
`minItems` cardinality (surya disabled guided table-rec entirely because an under-specified grammar
lets greedy decoding close an array after one element), `repetition_penalty = 1.0`. Against
permissive weights, because lift's are vetoed.

### 2.4 Decision caching — cache the signals, log the decisions

The decision is a pure microsecond-scale function of `(signals, policy, profile, overrides)`. There
is nothing to cache. What costs real CPU is the **signals** (the 96-DPI render), so:

- `signal` table keyed on `(content_digest, unit_part, signal_suite)`, `WITHOUT ROWID`. Keyed on
  content, not path: survives moves and renames, portable between machines and checkouts, and has no
  staleness question at all. This sidesteps the racily-clean trap entirely for signals; the
  `(size, mtime_ns, indexed_at_ns)` predicate (`graphify/graphify/cache.py:219`) still guards the
  path→digest step upstream, as `mine-runtime.md` §7.5.1 requires.
- `signal_suite` is a hand-maintained int, `FREE`-tier, so old namespaces are **swept** on first use
  (`mine-runtime.md` §7.5.2). A signal-code change silently invalidates cheap signals; it must never
  invalidate a paid extraction, which is why the two live in different namespaces.
- `RouteRecord`s are **logged, not cached** — they are the audit and replay artifact. `route` rows
  are pruned at 30 days *except* rows with `audit_status = 'mismatch'` or a non-empty
  `degradations_json`, which are kept indefinitely.

### 2.5 Overrides — five levels, precedence stated, every one recorded

Highest wins; a constraint can veto a preference, and a vetoed preference is an **error, never a
silent downgrade.**

| # | Level | Shape | Semantics |
|---|---|---|---|
| 1 | request `pin` | `{part: "12-40", driver: "ocr.page.olmocr"}` | Forces a driver. If ineligible under level 3, returns `PinRejected{driver, reason}`. Never silently ignored. |
| 2 | request `deny` / `require` | `deny_drivers: [...]`, `deny_network: hosted`, `require: {charspan: true}` | **Constraints.** Intersected with driver declarations. Can make routing infeasible → typed `NoEligibleDriver{capability, filtered_by}`. |
| 3 | request `profile` | `offline \| fast \| balanced \| thorough` | Selects a named overlay in the same policy file. marker's `mode`, generalised. `offline` = `deny_network: [local, hosted]`. |
| 4 | corpus overlay | `policy.overlays.<corpus_id>` | Per-collection thresholds; the tuning surface an operator actually touches. |
| 5 | deployment policy | `policy/route.yaml` in git | The base. |

**Egress denial is structural, not advisory.** A driver declares `network: none | local | hosted`;
eligibility is a set intersection computed *before any bytes move*; and a semgrep rule bans any HTTP
client import inside a module declaring `network: none`. This is the direct answer to marker's
`--use_llm`, which ships rendered page images to Gemini **by default** (`mine-risk.md` §2.7) — a
compute cost silently converted into a third-party data-processing agreement.

**Overrides are named per check, never one `--force`.** `--allow-rebill`, `--allow-unexplained-loss`,
`--accept-partial`, `--ignore-signal-cache`. `mine-runtime.md` §7.6.3 states the rule I am adopting
verbatim: "an override flag whose scope is 'skip whatever check just complained' is not an override,
it is an off switch."

### 2.6 Deterministic replay

`Router.replay(record, policy, sheet) -> RouteRecord` re-derives the whole trace from
`record.signals` with zero compute. **Invariant R2: `replay(r).trace == r.trace`.** For that to hold,
the decision path may not touch:

- **the wall clock** — lint bans `time.time`, `datetime.now` inside `omniweave/route/`;
- **unseeded randomness** — the audit sample is
  `int(sha256(content_digest + part + policy_digest), 16) < 2**256 * rate`, per-unit stable and
  replayable;
- **live Scoreboard state** — and this is the load-bearing one. §2.8.

Enforcement: a CI job replays ≥500 fixture records and diffs; production `--verify-routing` replays
1% of decisions inline and a mismatch raises `degrade("route_nondeterminism")` — a one-way latch
visible in the serve envelope (`mine-runtime.md` I18).

Replay verifies **decisions, not outputs.** A driver with a temperature ladder is not deterministic
and this design does not pretend otherwise; `DETERMINISTIC: ClassVar[bool]` on the operator
(`mine-runtime.md` §7.1) is what records that.

The payoff is `omniweave route simulate --policy candidate.yaml --since 30d`, which replays every
stored record under a candidate policy and reports the exact decision delta plus the estimated cost
and escalation-rate delta. **Threshold tuning stops being a guess and becomes a diff review.**

### 2.7 Cost model — physical units, money derived

```
Cost = { wall_ms, cpu_ms, accel_ms, tokens_in, tokens_out, calls }
```

- `wall_ms` from `monotonic_ns()`, split `queued_ms` / `ran_ms` (jcodemunch: "a contended lock and
  slow work are indistinguishable from the outside").
- `accel_ms` is **device-occupancy** ms reported by the serving layer, not request latency — the two
  differ by an order of magnitude under server-side coalescing (surya's `BATCH_WAIT_MS=5` +
  `MAX_BATCH`).
- **No driver ever reports money.** `PriceSheet` converts, and it is versioned separately with
  `effective_from`, so you can re-price history and compare self-host against hosted in one currency.

Grounding the sheet in evidence: hosted olmOCR-2-7B-FP8 is **$0.07–0.10/1M in, $0.15–0.20/1M out**
(`olmocr/README.md:339-341`); self-hosted is **<$200 per 1M pages = $0.0002/page** (`README.md:36`).
Those two numbers do not reconcile with a naive `accel_ms` estimate, and that is a *feature* of this
design: at `micros_per_accel_ms = 0.306` (an A10G at $1.10/h), $0.0002/page implies **654 accel_ms
per page**, while my honest first estimate for a 7B VLM page is ~2,200 ms — a **3.4× discrepancy**
against a vendor claim. The estimate is therefore explicitly a placeholder that the Scoreboard's
measured `sum_accel_ms / n_chosen` replaces within the first week of real traffic, and
`route lint --estimates` fails when a driver's estimate is more than 2× off its own 7-day measured
median. **An estimate that nothing reconciles against is how a cost model rots.**

Two regimes, deliberately:

- **`BILLED_API` is governed by `micros` and `tokens_out`.** Real money, real amplification.
- **`LOCAL_COMPUTE` is governed by `accel_ms`.** On an owned, under-utilised GPU, marginal micros are
  a fiction and a micros budget would reject work that is genuinely free. `accel_ms` is the real
  scarce resource.

### 2.8 Quality feedback — the ladder generates its own labels

**The primary signal is `escalation_rate`, and it is free.** If driver A is chosen at rung 1 and
rung 3 subsequently had to redo 34% of its pages on corpus C, driver A is failing on corpus C. No
ground truth, no annotation, no held-out set — the ladder already computed the label as a side
effect of doing the work. This is the single most important claim in this proposal, and it is why
routing and quality measurement are the same subsystem rather than two.

The `scoreboard` table accumulates, per `(corpus_id, unit_class, driver, driver_version, day)`:
`n_chosen`, `n_gate_fail`, `n_escalated_away`, `n_repeat_loop`, `n_empty`, `n_schema_violation`,
`n_audit_sampled`, `n_audit_mismatch`, `n_human_reject` (from the review surface),
`n_agent_requery` (jcodemunch's regret shape — a re-query within a 30-day window, thresholds 5/8),
`sum_micros`, `sum_accel_ms`, `sum_wall_ms`.

**The blind spot, named: escalation rate only sees failures the *next* rung's gates detect.** A VLM
that confidently produces plausible-but-wrong text — a transposed invoice total — escalates 0% and
scores perfectly. There is exactly one affordable defence and this design ships it:

**The shadow audit.** `audit_sample: 0.02` — 2% of units a *cheap* rung accepted are also run
through the expensive rung, and the two outputs compared with format-agnostic relational assertions
(olmOCR-Bench's `TestType{baseline,present,absent,order,table,math,format,footnote}` and its
`TableTest{cell, up/down/left/right, top_heading, left_heading}` shape, `max_diffs` fuzzy budget).
Declared cost, arithmetic stated: if 90% of a corpus routes free and the expensive rung costs 600
micros/page, the audit adds `0.02 × 0.9 × 600 = 10.8 micros/page` — **$10.80 per million pages**, or
1.8% of a fully-escalated bill. That is the price of knowing your cheap tier is not lying, and it is
cheap.

**Learning reaches a decision only through a promoted snapshot.** The router **never** reads the live
Scoreboard — that would destroy replay. Instead:

```
omniweave route propose --since 30d    # emits a policy DIFF + the counterfactual from route simulate
omniweave route promote sb-2026-09-01-a  # writes scoreboard_snapshot into route.yaml; requires clean tree
```

`route propose` finds thresholds and driver preferences whose change improves the measured
escalation/mismatch/cost frontier, and reports each as a unified diff with the simulated delta
attached. **A human merges it.** The policy is a git-tracked file, so the audit trail for "why did
routing change on the 14th" is `git log policy/route.yaml`. And because the default policy ships
with `scoreboard_snapshot: null` and constant thresholds, a team that never runs `promote` loses
nothing but the improvement.

### 2.9 Budget enforcement and graceful degradation

Budgets sit in `mine-runtime.md` §7.8.2's `BudgetLedger`, hierarchical per run / document / part /
provider, with `reserve → commit | release` and `Estimate` from the driver.

Hard rules, each traceable to an observed failure:

1. **Reserve before every billable step.** A denial returns `DEFERRED_BUDGET`, which is *not* a
   failure — the `work` row stays claimable. Without a distinct outcome, budget exhaustion reads as
   breakage.
2. **Retries are strictly serial and share one reservation.** olmocr fires remaining retries **in
   parallel** when the queue drains (`pipeline.py:343-350`), removing the natural rate limit on a 64×
   amplifier. `Admission.max_inflight_per_unit = 1`.
3. **Attempt caps are budget-derived, not constants.** Default per-part `calls: 3`,
   `tokens_out: 24000` (3 × olmocr's `MAX_TOKENS=8000`), against its default of 8 retries.
4. **Degradation is a declared ladder in the policy, per rung**, and every step writes a
   `Degradation` into the RouteRecord, the block, `page_stats`, and the serve envelope:

```yaml
on_budget_exhausted:
  - try: {rung: 6-structural}      # cheaper driver, output marked is_fallback
  - try: {accept_partial: true}    # keep the pages already done; docling's PARTIAL_SUCCESS
  - then: {mark: absent, code: BUDGET_EXHAUSTED}
```

`mark: absent` is deliberate and it is where this connects to the absence contract
(`mine-graph.md` §4.6): "OCR failed on pages 12–40" and "budget exhausted at page 12" must both
surface as `degraded`, never as a confident empty. `Unlimited-OCR` writing `{"text": ""}` after five
failed retries is the exact failure this forbids.

5. **The mandatory cheap pre-filter is ON by default, and its verdict is recorded and appealable.**
   olmocr's `PdfFilter` — a ~$0 CPU pass — is gated behind `--apply_filter` (`action="store_true"`,
   off). Ours is rung 0, on, and `{skipped: reason}` lands in the record so a customer can ask why
   their form was dropped. "Is a form" is a routing signal, not an exclusion.

6. **`--dry-run` on both `parse` and `update`.** graphrag has it on `index` and not on `update`,
   which is precisely where you want the delta priced before paying. Only possible because resources
   come from `ctx.resource(kind)` and never from a constructor: **a 100% cache-hit plan loads zero
   models.**

Middleware order, adopted from graphrag with `with_budget` inserted (innermost last):

```
with_logging → with_request_count → with_cache → with_budget → with_retries
             → with_rate_limiting → with_metrics → with_fault_injection → driver
```

`with_budget` **inside** the cache (a hit must not consume budget) and **outside** retry (each retry
re-checks). Metrics are cached alongside the response and replayed with `was_cache_hit=True`, which
is the only way to compute `would_have_been_micros_if_uncached` when 90% of calls hit.

---

## 3. Concrete shape

### 3.1 `policy/route.yaml` (abridged; the real file is ~320 lines)

```yaml
policy_version: 4                  # hand-maintained int, enters policy_digest
signal_suite: 3                    # version of the signal-computation code
scoreboard_snapshot: null          # null = constant thresholds only. Promoted, never live.
default_profile: balanced

signal_sampling: {head: 8, stride: 32, cap: 96}

budgets:
  document:
    micros:     "clamp(600 * signals.page_count, 2000, 200000)"   # $0.0006/pg, $0.002–$0.20/doc
    tokens_out: "8000 * signals.page_count"
    accel_ms:   "clamp(3000 * signals.page_count, 10000, 900000)"
    calls:      "clamp(3 * signals.page_count, 8, 4000)"
    wall_ms:    600000
  part:                            # per page — the runaway-page guard
    micros: 6000                   # $0.006
    tokens_out: 24000              # 3 x olmocr MAX_TOKENS=8000, vs its default of 8 retries
    accel_ms: 12000
    calls: 3
  on_budget_exhausted:
    - try:  {rung: 6-structural}
    - try:  {accept_partial: true}
    - then: {mark: absent, code: BUDGET_EXHAUSTED}

audit: {sample: 0.02, compare_rung: 3-page-ocr, assertions: olmbench_v1}

profiles:
  offline:  {deny_network: [local, hosted], promote_fraction: 0.0}
  fast:     {promote_fraction: 0.5, enable_rungs: [2-block-repair]}
  balanced: {promote_fraction: 0.0}
  thorough: {promote_fraction: 0.0, audit: {sample: 0.10}, disable: [rung-0.corpus_filter]}

drivers:
  text.office.native:
    capability: text
    cost_class: FREE
    network: none
    granularity: document
    formats: [docx, pptx, xlsx, epub, html, md, csv]
    declares: {spatial: none, charspan: true, tables: cells_with_spans,
               reading_order: source, furniture: separated, confidence: none}

  text.pdf.pdfium:
    capability: text
    cost_class: FREE
    network: none
    granularity: part
    formats: [pdf]
    declares: {spatial: line_bbox, charspan: true, tables: none,
               reading_order: char_stream, furniture: flagged, confidence: none}

  ocr.page.olmocr:
    capability: text
    cost_class: LOCAL_COMPUTE        # BILLED_API when bound to a metered provider
    network: local
    granularity: part
    formats: [pdf, png, jpg, tiff]
    declares: {spatial: none, tables: flat_html, reading_order: model_emitted,
               furniture: flagged, confidence: none}
    render: {short_edge_min: 692, area_max: 6291456, patch_grid: 28}   # lift floor, surya cap
    estimate:
      tokens_in:  "signals.image_tokens"
      tokens_out: "clamp(6 * signals.ink_tiles, 256, 8000)"
      accel_ms:   2200
      calls:      1
    limits: {max_tokens: 8000, temperature_ladder: [0.1, 0.2, 0.4], max_attempts: 3,
             repetition_penalty: 1.0}

  extract.schema.vlm:
    capability: fields
    cost_class: BILLED_API
    network: hosted
    granularity: document
    forfeits: [blocks, spatial, charspan, citation, round_trip]
    declares: {confidence: element}
    limits: {nullable_leaves: required, min_items: required, temperature: 0.0, top_p: 0.1,
             max_attempts: 6, retry_temperature: "min(0.2 * (attempt + 1), 0.8)"}

ladder:
  - rung: 0-preflight
    unit: document
    select: [{driver: preflight.static}]
    gates:
      - {name: format_known,  when: "signals.detected_format != \"unknown\"",
         on_fail: {outcome: failed_permanent, class: UNSUPPORTED_FORMAT}}
      - {name: not_encrypted, when: "not signals.encrypted",
         on_fail: {outcome: failed_permanent, class: PASSWORD_PROTECTED}}
      - {name: size,          when: "signals.bytes <= 536870912 and signals.page_count <= 4000",
         on_fail: {outcome: failed_permanent, class: TOO_LARGE, requeue_as: parse.chunked}}
      - {name: corpus_filter, when: "not (signals.spam_score > 0.004 and profile != \"thorough\")",
         on_fail: {outcome: skipped, code: CORPUS_FILTER}}      # recorded, appealable
      - {name: dedup,         when: "signals.dup_of == \"\"",
         on_fail: {outcome: skipped, code: DUPLICATE}}

  - rung: 1-decode
    unit: part
    select:
      - {driver: text.office.native, when: "signals.format_family in [\"ooxml\",\"html\",\"text\"]"}
      - {driver: text.pdf.pdfium,    when: "signals.format_family == \"pdf\" and signals.has_text_layer"}
    escape:
      - {name: blank_page, when: "signals.ink_tiles <= 4", accept: true}   # marker line.py:343-345
    gates:
      - {name: has_text,      when: "signals.char_count >= 1"}
      - {name: ink_coverage,  when: "signals.ink_coverage >= 0.25"}        # marker 0.25
      - {name: overlap,       when: "signals.overlap_fraction <= 0.5"}     # marker 0.5 @ 0.1
      - {name: not_garbled,   when: "signals.garble_score < 0.5"}
    on_gate_fail: {escalate_to: 3-page-ocr}
    refine:
      when: "signals.garble_score >= 0.05"                                 # marker's recheck gate
      rung: 2-block-repair

  - rung: 2-block-repair
    unit: block
    enabled_when: "profile == \"fast\""
    eligible_when: >
      block.type not in ["PageHeader","PageFooter","Picture","Figure","Diagram","Table","Form",
                         "TableOfContents","Equation","Chemical"]
      and (block.char_count >= 50
           or (block.char_count == 0
               and block.area_fraction >= 0.01
               and block.contained_in_text_sibling < 0.75
               and block.inked))
    select: [{driver: ocr.block.olmocr}]
    promote: {when: "ratio(page.bad_blocks, page.blocks) > policy.promote_fraction",
              to: 3-page-ocr}

  - rung: 3-page-ocr
    unit: part
    select: [{driver: ocr.page.olmocr}]
    gates: [{ref: 4-validate}]
    on_gate_fail: {escalate_to: 5-regenerate}

  - rung: 4-validate                 # runs on EVERY rung's output. FREE. The label generator.
    unit: part
    gates:
      - {name: no_repeat_loop, when: "not signals.repeat_loop"}    # window 128 page / 1024 doc, n=35
      - {name: finished,       when: "signals.finish_reason == \"stop\""}
      - {name: within_context, when: "signals.total_tokens <= 16384"}
      - {name: parses,         when: "signals.html_parse_ok"}
      - {name: nonempty,       when: "signals.char_count >= 1"}
      - {name: no_blank_hallucination, when: "not (signals.ink_tiles <= 4 and signals.char_count > 40)"}

  - rung: 5-regenerate
    unit: part
    select: [{driver: same_as_failed}]
    limits: {attempts: 3, serial: true, share_reservation: true}
    on_exhausted: {escalate_to: 6-structural}

  - rung: 6-structural
    unit: part
    select: [{driver: text.pdf.pdfium}]
    mark: {is_fallback: true, degradation: STRUCTURAL_FALLBACK}

  - rung: 7-long-horizon
    unit: document
    enabled_when: >
      signals.cross_page_table_rate > 0.15 and signals.layout_stability > 0.85
      and signals.page_count <= 120
    select: [{driver: ocr.doc.longctx}]
    limits: {wall_ms: 300000, attempts: 1, ngram_window: 1024, no_repeat_ngram_size: 35}
```

### 3.2 Python types (`omniweave/route/`)

```python
class CostClass(StrEnum): FREE = "free"; LOCAL_COMPUTE = "local_compute"; BILLED_API = "billed_api"
class Network(StrEnum):   NONE = "none"; LOCAL = "local"; HOSTED = "hosted"
class Action(StrEnum):
    ACCEPT="accept"; ESCALATE="escalate"; REPAIR="repair"; PROMOTE="promote"
    DEGRADE="degrade"; SKIP="skip"; FAIL="fail"; DEFER="defer"

@dataclass(frozen=True)
class Cost:
    wall_ms: int = 0; cpu_ms: int = 0; accel_ms: int = 0
    tokens_in: int = 0; tokens_out: int = 0; calls: int = 0
    def micros(self, sheet: PriceSheet, driver: str) -> int: ...   # money is DERIVED, always

@dataclass(frozen=True)
class PriceSheet:
    sheet_version: int
    effective_from: date
    accel_micros_per_ms: Mapping[str, float]     # {"local.a10g": 0.306, "local.h100": 0.68}
    cpu_micros_per_ms: float                     # 0.0083  ($0.03/vCPU-h)
    provider: Mapping[str, ProviderPrice]        # micros per 1M in / 1M out / per call
    def digest(self) -> str: ...

@dataclass(frozen=True)
class DriverSpec:
    name: str; version: str; capability: str
    cost_class: CostClass; network: Network; granularity: Granularity
    formats: frozenset[str]
    declares: Capabilities                       # mine-parse.md E11, verbatim
    forfeits: frozenset[str] = frozenset()
    estimate: Mapping[str, Expr] = field(default_factory=dict)
    limits: Mapping[str, Scalar] = field(default_factory=dict)

@dataclass(frozen=True)
class GateResult:
    name: str; passed: bool; expr: str
    values: Mapping[str, Scalar]                 # only the signals this gate read

@dataclass(frozen=True)
class RungStep:
    rung: str; driver: str | None
    gates: tuple[GateResult, ...]
    action: Action; reason: str
    estimate: Cost
    reservation_id: str | None = None
    actual: Cost | None = None                   # filled by on_result()

@dataclass(frozen=True)
class Degradation:
    code: str; rung: str; driver: str | None; reason: str

@dataclass(frozen=True)
class RouteRecord:
    route_key: str
    unit: UnitRef; profile: str
    policy_digest: str; policy_version: int
    signal_suite: int; pricesheet_digest: str
    scoreboard_snapshot: str | None
    signals: Mapping[str, Scalar]                # THE replay input — complete, or replay is a lie
    trace: tuple[RungStep, ...]                  # THE replay output
    chosen: str; chosen_rung: str
    escalated_from: str | None
    degradations: tuple[Degradation, ...]
    overrides: tuple[OverrideApplied, ...]
    audit_status: Literal["none","sampled","matched","mismatch"]
    unit_class: str
    generation: int

class Router:
    """The ONLY producer of `work` rows. mine-runtime.md §7.3's plan() hole, filled."""
    def __init__(self, policy: CompiledPolicy, sheet: PriceSheet,
                 suite: SignalSuite, snapshot: Snapshot | None): ...

    def plan(self, unit: UnitRef, req: Request, ctx: RunContext
             ) -> tuple[RouteRecord, tuple[WorkRow, ...]] | PinRejected | NoEligibleDriver: ...

    def on_result(self, rec: RouteRecord, res: StepResult, ctx: RunContext
                  ) -> RouteRecord: ...          # runs rung 4, decides escalate/accept/degrade

    @staticmethod
    def replay(rec: RouteRecord, policy: CompiledPolicy, sheet: PriceSheet) -> RouteRecord:
        """Pure. No clock, no RNG, no live scoreboard, no IO. R2: replay(r).trace == r.trace."""
```

### 3.3 SQL DDL

```sql
CREATE TABLE route (
  route_key         TEXT PRIMARY KEY,           -- sha256_canonical of the identity tuple below
  unit_uri          TEXT NOT NULL,
  unit_part         TEXT NOT NULL DEFAULT '',   -- '' folds NULL; NULLs are distinct in UNIQUE
  content_digest    TEXT NOT NULL,
  unit_class        TEXT NOT NULL,
  profile           TEXT NOT NULL,
  policy_digest     TEXT NOT NULL,
  policy_version    INTEGER NOT NULL,
  signal_suite      INTEGER NOT NULL,
  pricesheet_digest TEXT NOT NULL,
  scoreboard_snapshot TEXT,
  signals_json      TEXT NOT NULL,              -- the replay input
  trace_json        TEXT NOT NULL,              -- the replay output
  overrides_json    TEXT NOT NULL DEFAULT '[]',
  degradations_json TEXT NOT NULL DEFAULT '[]',
  chosen_driver     TEXT NOT NULL,
  chosen_rung       TEXT NOT NULL,
  escalated_from    TEXT,
  audit_status      TEXT NOT NULL DEFAULT 'none',
  est_micros        INTEGER NOT NULL,
  act_micros        INTEGER, act_accel_ms INTEGER, act_tokens_out INTEGER, act_wall_ms INTEGER,
  decided_at        INTEGER NOT NULL,           -- wall ms, for humans and retention only
  generation        INTEGER NOT NULL
);
CREATE UNIQUE INDEX route_identity ON route(unit_uri, unit_part, policy_digest, signal_suite);
CREATE INDEX route_sim   ON route(policy_digest, decided_at);
CREATE INDEX route_audit ON route(audit_status) WHERE audit_status IN ('sampled','mismatch');
CREATE INDEX route_keep  ON route(decided_at)
  WHERE audit_status != 'mismatch' AND degradations_json = '[]';   -- the prunable set

-- Signals: keyed on CONTENT, so moves/renames/checkouts cost nothing and there is no staleness
-- question at all. FREE tier ⇒ old signal_suite namespaces are swept on first use.
CREATE TABLE signal (
  content_digest TEXT NOT NULL,
  unit_part      TEXT NOT NULL DEFAULT '',
  signal_suite   INTEGER NOT NULL,
  signals_json   TEXT NOT NULL,
  compute_ms     INTEGER NOT NULL,
  PRIMARY KEY (content_digest, unit_part, signal_suite)
) WITHOUT ROWID;

CREATE TABLE scoreboard (
  corpus_id  TEXT NOT NULL, unit_class TEXT NOT NULL,
  driver     TEXT NOT NULL, driver_version TEXT NOT NULL,
  window_day INTEGER NOT NULL,                  -- days since epoch; pruned at 180d
  n_chosen INTEGER NOT NULL DEFAULT 0, n_gate_fail INTEGER NOT NULL DEFAULT 0,
  n_escalated_away INTEGER NOT NULL DEFAULT 0,  -- ★ the free quality label
  n_repeat_loop INTEGER NOT NULL DEFAULT 0, n_empty INTEGER NOT NULL DEFAULT 0,
  n_schema_violation INTEGER NOT NULL DEFAULT 0,
  n_audit_sampled INTEGER NOT NULL DEFAULT 0, n_audit_mismatch INTEGER NOT NULL DEFAULT 0,
  n_human_reject INTEGER NOT NULL DEFAULT 0, n_agent_requery INTEGER NOT NULL DEFAULT 0,
  sum_micros INTEGER NOT NULL DEFAULT 0, sum_accel_ms INTEGER NOT NULL DEFAULT 0,
  sum_wall_ms INTEGER NOT NULL DEFAULT 0, sum_tokens_out INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (corpus_id, unit_class, driver, driver_version, window_day)
) WITHOUT ROWID;

-- Every work row names the decision that created it. No driver runs unrouted.
ALTER TABLE work ADD COLUMN route_key TEXT NOT NULL REFERENCES route(route_key);
```

### 3.4 CLI

```
omniweave route explain   <uri> [--part 12] [--profile fast]   # signals, gates, trace, cost, why
omniweave route lint      [policy/route.yaml]                  # CI gate; --calibration; --estimates
omniweave route simulate  --policy candidate.yaml --since 30d [--corpus C]
omniweave route scoreboard [--corpus C] [--window 30d] [--by unit_class]
omniweave route audit     --since 7d                           # replay mismatches + shadow diffs
omniweave route propose   --since 30d                          # a policy DIFF + counterfactual
omniweave route promote   sb-2026-09-01-a                      # writes the snapshot ref; clean tree
omniweave parse --dry-run <uri>                                # plan + estimate, spends nothing
```

### 3.5 Tree and size

```
omniweave/route/
  policy.py      load / overlay / compile / digest                        ~250
  expr.py        the closed expression language                           ~150
  cost.py        Cost, PriceSheet, estimate evaluation                    ~180
  router.py      plan / on_result / replay                                ~350
  budget.py      ledger binding + the degradation ladder                  ~200
  record.py      RouteRecord persistence, retention, pruning              ~200
  scoreboard.py  counters, snapshot, propose                              ~300
  audit.py       deterministic shadow sampling + olmbench assertions      ~200
  signals/
    __init__.py  registry, versioning, cache, sampling                    ~140
    static.py                                                            ~150
    textlayer.py                                                         ~180
    ink.py       96-DPI tiles, ink_coverage, overlap_fraction             ~220
    garble.py    7 features + fitted coefficients + calibration check     ~200
policy/{route.yaml, pricesheet.yaml, snapshots/*.json}
```

**~2,900 lines of Python** plus the policy files. New runtime dependencies: **zero** beyond
`pypdfium2` (already required for parsing) and a wordlist. No torch in the routing path.

---

## 4. Invariants and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| **R1** | No driver runs on a unit without a `RouteRecord` naming it. | `Router.plan` is the only producer of `work` rows; `work.route_key NOT NULL REFERENCES route`; a test asserts no driver module is importable outside the registry. |
| **R2** | `replay(r).trace == r.trace`. | CI replays ≥500 fixture records and diffs; production `--verify-routing` replays 1% inline; mismatch ⇒ one-way `degrade("route_nondeterminism")` in the serve envelope. |
| **R3** | No decision reads a clock, unseeded RNG, or live Scoreboard. | Lint bans `time.time`/`datetime.now`/`random` in `omniweave/route/`; `Snapshot` is a frozen dataclass with no DB handle, so there is nothing to read. |
| **R4** | No billable step without a reservation. | `with_budget` inside cache, outside retry; `cost_class != FREE` drivers assert `ctx.budget.has_reservation(self)` at entry. |
| **R5** | Retries are serial and share one reservation. | The retry middleware holds one `Reservation` across attempts; `Admission.max_inflight_per_unit = 1`; a test asserts N attempts draw from one budget. |
| **R6** | Every degradation is visible in the product surface. | `Degradation` written to the record, `page_stats`, the block's `_partial`, and the envelope's `degradations[]`; a test asserts each code round-trips to the envelope. |
| **R7** | A pin is honoured or refused, never silently ignored. | `plan()` returns `PinRejected` rather than a fallback; type-checked at the call site (no `| None`). |
| **R8** | Network denial is structural. | Eligibility is a `Network` set intersection before any bytes move; a semgrep rule bans HTTP-client imports in `network: none` driver modules; CI. |
| **R9** | Every signal a policy names exists, typed and ranged, in the registry. | `route lint` at load and in CI; policy load **fails closed**. |
| **R10** | Signal computation is pure and content-addressed. | `signal` PK on `(content_digest, part, suite)`; `signals/` may not import `ctx.store`; a fixture recompute-and-compare test. |
| **R11** | A probabilistic signal is calibrated. | `route lint --calibration`: ECE ≤ 0.05, Brier ≤ 0.08 on a held-out set. A regression fails the build. |
| **R12** | An empty output is never an acceptance. | `is_valid_nonempty` is a rung-4 gate, so an empty page from a paid driver escalates or degrades — it can never land as `OK`. |
| **R13** | The router never mutates policy. | `CompiledPolicy` frozen; no code path from `scoreboard.py` writes `policy/`; `promote` is a separate verb requiring a clean git tree. |
| **R14** | A cheap acceptance is auditable. | Deterministic sampling `sha256(digest+part+policy_digest) < 2**256 * rate`; `n_audit_mismatch` is a gate in `route propose`. |
| **R15** | An estimate that drifts from measurement fails the build. | `route lint --estimates`: a driver's estimate more than 2× off its 7-day measured median is an error. |

---

## 5. What it costs

**Engineering.** ~2,900 lines. Phase 1 (signals + ladder + records + `explain`) **3 weeks**; Phase 2
(budgets + `--dry-run` + degradation + `simulate`) **2 weeks**; Phase 3 (scoreboard + audit +
`propose`) **2 weeks**. Plus **2 person-days** labelling 2,000 pages for `garble.py` and a recurring
half-day per quarter to re-fit. Total ~8 engineer-weeks to a fully honest router.

**Runtime overhead, per PDF page:** static ~0 (once/doc), text-layer ~1.2 ms, 96-DPI render 8–14 ms
(shared with the structure tier — free for any page actually parsed), tile scan ~2 ms, garble ~1 ms.
**~15 ms CPU/page**, and ~4 ms of that is unavoidable-if-you-skip-the-page. Decision evaluation over
~30 signals: **~20 µs**. So for a 4,000-page PDF, naive full signal computation is 60 s of CPU —
which is why `signal_sampling` exists and why it is in the policy rather than in code.

**Storage.** `signals_json` ~600 B/page + `trace_json` ~400 B/page ⇒ **~1 GB per million pages**
routed, before pruning. With 30-day retention on clean records and permanent retention for
mismatches and degradations, steady state on a 10M-page corpus refreshed monthly is ~2–3 GB. Stated
so nobody is surprised.

**Dependency weight: zero new.** No torch, no onnx, no model weights in the routing path. That is
deliberate and it is a hard constraint from the risk digest: an L5 layer must never make a torch
install a prerequisite for reading a DOCX.

**Operational burden.** One new file a human is expected to read (`route.yaml`), one new CI job
(`route lint`, ~8 s), one weekly report (`route propose`), one governance ritual (`route promote`).
If the team skips `promote` forever, the router still works with constant thresholds — the loop is
opt-in by construction, which is the only way a 3-person team keeps it.

---

## 6. Failure modes — honestly, including the input that breaks it

1. **The confidently-wrong driver is invisible to escalation rate.** A VLM that transposes an invoice
   total passes every rung-4 gate and escalates 0%. Only the 2% shadow audit and human review catch
   it, both sampled — so a 0.5% error rate on a specific document class is statistically invisible
   until someone complains. This is the deepest limitation of the design and no amount of routing
   fixes it; it is why per-field confidence and a review surface (lift's 20.9% full-document number)
   are mandatory downstream, not optional.
2. **The breaking input: a 4,000-page born-digital report with a 40-page scanned appendix at pages
   2,900–2,940.** `signal_sampling: {head: 8, stride: 32}` samples pages 8, 40, 72, … — it will hit
   ~1 of the 40 scanned pages, so the document prior stays "digital" and the initial rung is wrong
   for those 40. The guard is that per-page signals always override the prior on pages actually
   parsed, so the output is correct; the *cost* is 40 pages of wasted rung-1 attempts and one extra
   escalation each. If a customer's corpus is shaped like this, `stride` is a corpus-overlay knob —
   but nothing detects the shape automatically, and that is a real gap.
3. **`garble_score` is fitted on our corpus and will be miscalibrated on someone else's.** A
   customer whose documents are 80% Thai, or heavily typeset mathematics, or 1970s typewriter scans,
   gets a classifier calibrated for the wrong distribution — and because rung 1's `not_garbled` gate
   is a threshold on it, miscalibration reads as either "everything escalates" (a 4× bill) or
   "nothing escalates" (silent garbage). Mitigations: the score is *also* recorded per page, so
   `route scoreboard --by unit_class` shows the drift; and `ink_coverage` + `overlap_fraction` +
   `cid_ratio` are model-free and keep working. But the honest statement is that a probabilistic
   signal is a per-corpus liability and the calibration gate only protects the corpus we measured.
4. **The policy expression language will be asked to grow.** Someone will want a regex on filename,
   then a tenant-tier lookup, then a date window. Each is one PR away from an `eval()`. The stated
   rule — *a rule that needs code becomes a Signal* — is a review discipline, not a mechanism, and
   review disciplines decay. The partial mechanism is that `expr.py` has no extension point and
   adding a `fn` requires editing a five-element frozenset with a test, which makes the wrong move
   visible in a diff.
5. **`accel_ms` → micros is a fiction on owned hardware.** At 20% fleet utilisation, marginal cost is
   near zero and a micros budget rejects free work; at 100% it under-prices the queue. The
   two-regime split (§2.7) mitigates but does not solve it, and a mixed deployment (self-host with
   burst to a hosted provider) will show a 3–5× cost discontinuity at the burst boundary that reads
   as a bug.
6. **RouteRecord retention conflicts with `route simulate --since 30d` the moment someone prunes to
   7 days for disk.** Simulation quality silently degrades with no warning. The fix is that
   `simulate` reports the record count and date range it actually saw, and refuses below 1,000
   records — but a 30-day window on a corpus indexed once a quarter is simply empty.
7. **Scoreboard `unit_class` cardinality.** `format_family × text_layer × garble_bucket ×
   table_bucket × corpus_id × driver × version × day` can explode on a multi-tenant deployment with
   thousands of corpora. At 10k corpora × 12 unit classes × 6 drivers × 180 days that is 130M rows.
   The guard is per-corpus rollup at 30 days into a `corpus_id = '*'` aggregate, which loses exactly
   the per-tenant signal a support engineer wants.
8. **Two writers, two policies, one store.** Cache namespacing handles the paid tier
   (`BILLED_API` namespaced by config digest, never swept — `mine-runtime.md` §7.5.2), but the
   `route` table's `route_identity` unique index includes `policy_digest`, so two hosts on different
   policies produce two records per unit and `simulate` over the union double-counts unless filtered
   by `policy_digest`. `simulate` filters; `scoreboard` does not, and that is a latent bug I would
   fix in Phase 3 by adding `policy_digest` to the scoreboard key.
9. **A pin plus a constraint is a UX cliff.** `pin: ocr.page.olmocr` with `deny_network: [local]`
   returns `PinRejected`, which is correct and will read to a user as "omniweave refused to do the
   obvious thing." The error message has to be excellent and it will not be, initially.

---

## 7. Why I reject the alternatives

**A learned router — a model that picks the driver.** Rejected. On day one there are no labels, and
the label you need (*which driver would have been right*) is precisely the expensive thing you were
trying to avoid computing. The ladder produces that label for free as a byproduct of escalating, so
the correct architecture is to harvest it offline — which is what `escalation_rate` +
`route simulate` do. A model in the routing path also makes every decision unexplainable to a
customer asking why their bill doubled on Tuesday, and it destroys R2. If a learned component ever
earns its place, it enters as a **Signal** (a calibrated score the policy thresholds), not as the
decider. `garble_score` is already exactly that shape.

**Routing as code — a Python `route()` with if/else. This is what marker actually ships.** Rejected,
and this is the closest call in the proposal, because marker's version *works* and is the only
working cost router in the collection (`marker/builders/line.py`). Three reasons it does not
generalise: (a) thresholds cannot be versioned, overlaid per tenant, or diffed independently of a
release, so tuning is a deploy; (b) it cannot be simulated over history, so every threshold change
is a guess with a cost consequence; (c) marker's own config surface proves the endpoint — its
`--converter_cls` / `--processors` / `--llm_service` accept dotted import paths settable from
`--config_json`, which is an RCE channel the moment config comes from a request body. Code-as-config
always arrives there. I take marker's *numbers* wholesale (0.25, 0.5, 0.1, 0.05, 50, 0.01, 0.75,
promote 0.0/0.5) and its *reasoning* verbatim, and put them in a file.

**Per-document routing — docling's `do_ocr: bool`.** Rejected on measurement. docling computes the
best per-page quality signals in the collection (`parse`/`layout`/`ocr` scores, POOR→EXCELLENT
grades) and **consumes none of them**; its escalation unit is the whole document. The consequence is
the mixed-document failure in §6.2, and the counter-evidence is marker's measured result that a clean
digital document never starts the inference server at all. `digest-parse` puts it correctly: the
signal and the router are one feature — ship both or neither.

**Drivers report dollars.** Rejected. A driver that reports money cannot be re-priced, cannot be
compared self-host against hosted, and hard-codes a commercial fact into a technical component.
Physical units plus a versioned `PriceSheet` costs one extra file and buys `route simulate --sheet
new.yaml`, historical re-pricing, and the §2.7 reconciliation check that caught a 3.4× estimate
error before any code ran.

**An online adaptive router — bandits, per-unit exploration, live threshold adjustment.** Rejected
for v1 and probably v3. It breaks R2 outright: with a non-stationary policy, "why was this page
routed here" has no answer. Cost regressions become unattributable, and a three-person team cannot
debug a policy that changed itself. The snapshot-promotion loop gets most of the value with
`git log policy/route.yaml` as the audit trail, and it can be upgraded later without changing the
`RouteRecord` schema — which is the property that matters.

**One quality number per driver.** Rejected. Quality is per `(driver × unit_class)`. The evidence is
already in the collection: marker wins accuracy-per-dollar on digital-leaning corpora while olmocr is
simpler and better on scan-heavy ones (`_index/comparisons.md`), and surya's 83.3% vs olmocr's ~79%
on olmOCR-bench is a corpus-average that says nothing about scanned CJK tables. A single number
would route the wrong way on every corpus that is not the benchmark.

**A routing/policy microservice.** Rejected. 15 ms of CPU signals and 20 µs of AST evaluation do not
need a network hop, a second deployment artefact, or a second failure domain. One process, one
SQLite store, one file.

**Adopting surya's `OCRErrorPredictor` and marker's layout model as the signals.** Rejected on
licence, not on quality — and this is the rejection that shapes the whole design. Clause 2(c) of
`marker/MODEL_LICENSE` has no revenue threshold and no research carve-out, clause 8 is viral on
Output, and `grep -rn "revision=" marker/ surya/ lift/` returns zero hits so no published number
from those repos is even reproducible. The ~4-point olmOCR-bench gap between surya (83.3%) and
olmocr (~79%) is the price of unconditional commercial rights, and the same logic applies one level
up: the price of a licence-free router is that I have to build `ink_coverage` and `garble_score`
myself. That is two files and two person-days of labelling, and it is the cheapest insurance in this
whole proposal.
