# D4 — The routing and escalation policy engine

**Panel proposal — the systems-purist position.**
Author prior: correctness under scale; a design still right in five years; willing to pay upfront
engineering cost to avoid a structural mistake.

---

## Headline

**Routing is a compiled, content-addressed policy artifact evaluated against a stored signal vector,
and every decision is written to an append-only `route_ledger` before the work runs — so the router
is replayable, re-scorable offline, budget-bounded by currency rather than by retry count, and able
to notice on its own that a driver has started failing on a corpus. The policy is data; the engine is
~2.5 kLoC of code that can type-check the policy; the ledger's stored signal vectors are the one
artifact that cannot be added later.**

---

## 0. What this decision actually is

The cost spread between the cheapest and most expensive way to read one page is roughly **five orders
of magnitude**: a native-format decode is ~0; `olmocr` self-hosted is **$0.0002/page**
(`olmocr/README.md:36`, "< $200 per 1M pages"); the same model's worst-case retry path is
**8,000 tokens × 8 attempts = 64,000 output tokens ⇒ $0.0128/page** at $0.20/1M
(`olmocr/olmocr/pipeline.py:107` and `:1221`, prices at `olmocr/README.md:339-341`) — **64×
amplification, fired in parallel when the queue is idle** (`pipeline.py:343-350`), against
`--max_concurrent_requests` default **1600** (`:1224`). A frontier hosted VLM is another 10×
above that.

Therefore: **the routing decision *is* the cost model, and the escalation policy *is* the security
control on cost.** Everything else in this proposal follows from taking that literally.

Two facts constrain the design before any engineering:

1. **Per-document routing is not viable.** `docling` computes the best per-page quality signals in
   the collection (`ConfidenceReport`, parse/layout/ocr/table scores with POOR→EXCELLENT grades) and
   consumes **none of them** — `do_ocr` is a document-level boolean. One scanned insert in a
   300-page born-digital report either costs the whole document at VLM prices or loses that page.
2. **The one working per-page router in the collection is `marker/marker/builders/line.py`, and its
   escalation signal is a vetoed weight.** The gate that makes it work is
   `page_ocr_error_scores[page_id] = score` (`line.py:216-218`) feeding
   `block_garbled_check_min_page_score` (`line.py:115`) — and the score comes from
   `OCR_ERROR_MODEL_CHECKPOINT: str = "s3://ocr_error_detection/2025_02_18"`
   (`surya/surya/settings.py:137`), a Datalab-distributed checkpoint under the OpenRAIL-M
   `MODEL_LICENSE` that `DIGEST.md` vetoes outright (clause 2(c) competitor bar, clause 8 viral on
   Output). The *code* is Apache-2.0 and reimplementable; the *classifier* is not usable.

Consequence that a proposal must not hide: **the veto removes the middle of marker's ladder.**
Both the OCR-error classifier and the cheap `FastLayoutPredictor` (rf-detr) checkpoints are Datalab
artifacts. Until omniweave owns a garble scorer and a layout detector, its cost curve is *worse* than
marker's, because pages that marker resolves with a 650M-parameter CPU pass fall through to a 7B VLM.
The router's job is to make that gap **visible, priced, and closable by adding a driver** — not to
pretend it does not exist. §4 specifies the licence-clean signal set that recovers most of it for
free.

---

## 1. Invariants

Numbered `R1…R16` so they do not collide with `mine-runtime.md` §7.11's `I1…I18`, whose work table,
cache key, `StepResult` and `BudgetLedger` this design plugs into rather than replaces.

| # | Invariant | Enforced by |
|---|---|---|
| **R1** | A driver is invoked **only** through a `Rung` named by the active `PolicyImage`. | Type system: `DriverHandle.__init__` is private to `omniweave.route`; `ctx.driver(kind, rung: RungToken)` requires a token the `Router` mints. CI: semgrep rule banning driver-module imports outside `omniweave/route/exec/`. |
| **R2** | The `RouteDecision` row is written **in the same transaction that claims the `work` row**, before any driver runs. | SQL: `work.decision_id` is `NOT NULL REFERENCES route_decision(id)`. A claim without a decision cannot be expressed. |
| **R3** | A decision is a pure function of `(policy_digest, signals, override_set, pricebook_digest, budget_headroom_snapshot, probe_salt)`. No clock, no `random`, no environment. | `omniweave route replay <decision_id>` recomputes `chosen_rung` + `predicate_trace` and asserts byte equality. CI: a property test replays 100% of a fixture corpus's ledger; nightly job replays a 1% sample of production ledgers. |
| **R4** | No `Signal` may cost more than the cheapest `Rung` its predicates gate. | Policy **compile-time** check against the `PriceBook`. A policy that violates it does not compile. |
| **R5** | Every classifier-derived signal returns a **score** in a declared range, never a label. A predicate over a label-only signal is a compile error. | Signal registry schema requires `range: [lo, hi]`. Evidence: `surya/surya/ocr_error/schema.py` ships `scores: List[float]` with the comment *"Lets callers gate expensive follow-up work on confidence instead of just the argmax label."* Label-only ⇒ marker's 0.05 gate is impossible. |
| **R6** | Escalation is monotone in **fidelity tier**; among admissible rungs the router picks by **estimated spend for this unit**. A cheaper-tier rung after a higher one is a *fallback*, must be declared as `on_exhaust`, and its output carries `degraded = true`. | Policy compiler: `tier` is a required, strictly increasing int per ladder; `on_exhaust` is the only backward edge. Runtime: `RouteDecision.degraded`. |
| **R7** | Budget denial is an **outcome**, not an error: `Outcome.DEFERRED_BUDGET` (runtime §7.1.2) plus `RouteDecision.stopped_at_tier`. The document's status is `PARTIAL_SUCCESS`; the unserviced parts are named. | `StepResult.__post_init__`; test: a run with `billed_micros = 0` still returns a complete L2 document where every unrouted part carries `unrouted{reason, would_cost_micros}`. |
| **R8** | Furniture and specialist block classes can never trigger a *general* escalation. Exclusions live in policy data and each requires a `because:` string. | Policy schema: `exclude_block_types` entries are `{type, because}`. Evidence: marker excludes `PageHeader`/`PageFooter` from block-OCR eligibility with the rationale in-source — *"a single flagged footer forces an otherwise-clean doc to spawn the inference server"* (`marker/marker/builders/line.py:121-124`). |
| **R9** | Every degradation appears in the result. | Property test: `RouteDecision.degradations` non-empty ⇒ the parse envelope's `degradations[]` non-empty. Counter-evidence this exists to prevent: `lift` prints and drops `response_format` when schema compilation fails; `Unlimited-OCR/infer.py` writes `""` for a page that failed 5 retries. |
| **R10** | A policy cannot name a driver whose `licence_class` or `egress_class` is outside the deployment's allowlist. | Compile-time registry lookup. This is where the OpenRAIL-M / HunyuanOCR vetoes become structural rather than remembered. `egress_class: external` additionally requires a non-empty `dpa_ref`. |
| **R11** | No policy value is ever a dotted import path or a code string. Rungs, drivers, signals and acceptors are registry keys matching `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`. | Schema pattern + registry resolution at compile time. Prevents marker's `--converter_cls`/`--processors`/`--llm_service` channel, which is arbitrary-import RCE the moment config arrives in a request body. |
| **R12** | The **full signal vector** is stored on the decision row, not just the verdict. | `route_decision.signals NOT NULL`. This is the offline-tuning substrate and the only part of the design that cannot be retrofitted. |
| **R13** | The tuner never writes the active policy. It emits a `policy_candidate` with a counterfactual cost/quality diff; activation is a human act recorded with an author. | `policy_active` has `activated_by NOT NULL`; the tuner's DB role has no write grant on it. |
| **R14** | A rung's `Acceptor` set runs on every artifact **before commit**, and the accepting digest is stored on the artifact. A cached artifact is trusted because it was accepted at production time, never because it is cached. | `artifact.accepted_by = sha256(acceptor_ids ‖ policy_digest)`; the loader rejects an artifact whose `accepted_by` is unknown to the current registry and re-runs acceptors. |
| **R15** | Retries are rungs. They obey R6, are charged to the same per-unit budget, and execute **strictly serially** per unit. | The executor holds a per-`(unit, part)` semaphore of 1 across a `retry_of` chain; CI test asserts observed concurrency == 1. This is the direct fix for the 64× amplifier. |
| **R16** | No provider-reported quality number may enter the policy or the `PriceBook`. Quality is only ever *measured locally*, in the `DriverScorecard`. | The policy schema has **no** accuracy/quality field. Rationale: `grep -rn "revision=" marker/ surya/ lift/` returns zero hits, so their benchmarked checkpoint is not the served one; HunyuanOCR's 94.10 OmniDocBench was measured on TensorRT while the repo ships Transformers and vLLM, which it admits disagree. |

---

## 2. Component map and vocabulary

These names propagate to D5–D10. They are deliberately plain.

```
omniweave/route/
├── policy/
│   ├── schema.py        RoutingPolicy, Ladder, Rung, SignalDecl, PriceBook   (pydantic, frozen)
│   ├── rpl.py           Route Predicate Language: lexer, parser, typer, Kleene evaluator
│   ├── compile.py       RoutingPolicy -> PolicyImage  (+ R4/R6/R10/R11 checks)
│   └── digest.py        sha256_canonical  (shared with runtime §7.5)
├── signals/
│   ├── registry.py      SignalId -> SignalDriver, with cost_class and range
│   ├── text_layer.py    presence, coverage, overlap, encoding, replacement density
│   ├── plausibility.py  script-aware n-gram score (data table, no model weights)
│   ├── raster.py        72-dpi ink ratio, blank-region detection
│   ├── prefilter.py     form fields, language, download-spam lexicon   (olmocr's PdfFilter, reimplemented)
│   └── model.py          optional: omniweave-garble-v1  (extras only, never core)
├── exec/
│   ├── rung.py          RungToken minting, DriverHandle (private ctor)
│   ├── acceptor.py      repeat_loop, parse_valid, finish_reason, coverage_backcheck, blank_region
│   └── render.py        RenderProfile -> page raster  (short-edge floor, area cap, patch snap)
├── ledger/
│   ├── ddl.sql          route_decision, route_signal_cache, route_probe, policy, policy_active
│   ├── write.py         claim+decide in one transaction
│   └── replay.py        omniweave route replay
├── quality/
│   ├── probe.py         ShadowProbe: deterministic hash sampling, separate budget
│   ├── scorecard.py     DriverScorecard rollups, alarm bands
│   └── tuner.py         offline re-scoring of stored signal vectors -> policy_candidate
└── cli.py               route explain | replay | plan | policy {lint,diff,activate} | scorecard
```

| Name | Meaning |
|---|---|
| `RouteGoal` | `REPRESENT` \| `EXTRACT` \| `LOCATE`. Selects which `Ladder` applies. |
| `RoutingPolicy` | The authored, declarative document (TOML). Data. |
| `PolicyImage` | The compiled, frozen, content-addressed form. `policy_digest` = `sha256_canonical`. Immutable; stored in the `policy` table; never mutated. |
| `Signal` / `SignalId` | A named, typed, cost-classed observation about one `(unit, part)`. |
| `Ladder` / `Rung` | An ordered set of admissible ways to produce an artifact for one goal, ordered by `tier` (fidelity). |
| `RPL` | Route Predicate Language — a total, side-effect-free expression grammar over signals. |
| `Acceptor` | A post-hoc validator on a rung's output; failure triggers `on_reject`. |
| `PriceBook` | `(driver, model_id, revision, runtime, runtime_version) → CostVector` unit prices + estimator spec. Versioned and digested. |
| `CostVector` | `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, provider_calls, egress_bytes}` — never a scalar. |
| `objective` | The deployment's **shadow prices**, in micro-dollars per unit of each `CostVector` component. Collapses the vector to `spend_micros`. Part of the policy digest. |
| `RouteDecision` | One immutable ledger row per `(unit, part, goal, policy_digest)`. |
| `RouteOverride` | A scoped, typed, reasoned deviation. Never a `--force`. |
| `ShadowProbe` | A deterministically sampled parallel run at a higher tier, on its own budget. |
| `DriverScorecard` | Per-`(corpus, driver, revision, format, page_class)` measured agreement, reject rate, escalation rate. |
| `trust_class` | `internal` \| `untrusted_external`. A routing input, not a footnote (§8.6). |
| `RenderProfile` | Pixel-floor/area-cap raster spec, chosen per rung, applied **after** the decision. |

---

## 3. The cost model — a vector plus declared exchange rates

The brief asks which unit the cost model is in: wall time, GPU seconds, tokens, or dollars. **All
four, and the answer to "which one matters" is a deployment decision that must be part of the policy
digest, or a decision is not replayable.**

`CostVector` is measured; `objective` prices it:

```
spend_micros(rung, unit) = Σ_k  objective.weight[k] × estimate(rung, unit, signals).cost[k]
```

`objective.weight` is in **micro-dollars per unit of k**. A self-hoster with an idle 4090 sets
`gpu_ms = 0.3`; an operator renting H100 time sets `gpu_ms = 11` (≈$40/h); a latency-sensitive
interactive deployment sets `wall_ms = 2` and thereby buys the expensive-but-fast rung on purpose.
The same policy body therefore routes differently — correctly — on different hardware, and the
difference is auditable because `objective` is inside `policy_digest`.

**`estimate` is count-aware, and this matters more than it looks.** One full-page OCR request is
**~7× cheaper** than N block requests on llama.cpp (per-request overhead plus KV contention —
`marker/marker/builders/ocr.py:80-82`) *and* more accurate, because tight crops lose context. So
block-mode is cheaper than page-mode only while the flagged-block count is below roughly 1/7 of the
page's blocks. A static price per rung gets this wrong. Hence:

- `tier` is **static** and semantic (fidelity), and it is what R6, `floor`, `ceiling` and `pin`
  operate on;
- `estimate(rung, unit, signals)` is **dynamic**, and it is what selects among admissible rungs of
  equal or adjacent tier.

marker's `block_ocr_promote_fraction` (`line.py:91`, default 0.5 in fast mode, 0.0 in balanced) is
exactly this crossover expressed as a hand-tuned constant. In omniweave it is *derived* from the
estimator and the objective, and the policy only declares a bias:
`promote_bias = 1.0` reproduces marker balanced, `promote_bias = 0.15` reproduces the measured 1/7
crossover.

**Seed values for the shipped `PriceBook`** (all sourced, all local-measurement-replaceable):

| Rung class | Unit price | Source |
|---|---|---|
| native decode / PDF text layer | ~0 micros; 0.4–3 ms CPU/page | anydoc, pdfium |
| CPU layout (when a licence-clean driver exists) | ~0.2 micros/page equivalent | marker fast mode's envelope |
| 7B VLM full page, self-hosted | **200 micros/page** ($0.0002) | `olmocr/README.md:36` |
| 7B VLM full page, hosted FP8 | in $0.07–0.10/1M, out $0.15–0.20/1M | `olmocr/README.md:339-341` |
| worst-case unbounded retry ladder | **12,800 micros/page** | 8,000 tok × 8 attempts, `olmocr/olmocr/pipeline.py:107,1221` |
| frontier hosted VLM | 1,000–10,000 micros/page | published rate cards; must be entered by the operator |

The last two rows are why the default per-unit billed budget is **1,500 micros** (§7): at $0.20/1M
output tokens that is ~7,500 output tokens — one 8k attempt plus change. The 64× path is not
"discouraged" by the default configuration; it is **arithmetically unreachable**.

---

## 4. The escalation signals — and the licence-clean replacement for the classifier

marker's page verdict is four signals ANDed (`marker/marker/builders/line.py:225-235`, verified):

```python
provider_lines_good = all([
    bool(provider_lines),
    not document_page.ocr_errors_detected,          # ← the vetoed classifier
    self.check_layout_coverage(document_page, provider_lines),   # >= 0.25   (line.py:35)
    self.check_line_overlaps(document_page, provider_lines),     # <= 0.50   (line.py:45)
])
```

omniweave keeps the *shape* and rebuilds signal 2 from evidence that carries no licence:

| `SignalId` | cost_class | range | What it is | Evidence |
|---|---|---|---|---|
| `text.present` | FREE | 0..1 | fraction of page area covered by glyph runs | marker signal 1 |
| `text.layout_coverage` | FREE | 0..1 | fraction of non-figure layout blocks with ≥1 provider line, incl. the single-large-text-block blank-page escape hatch | `line.py:341`, `:343-345` |
| `text.overlap_fraction` | FREE | 0..1 | fraction of provider lines over-intersecting >0.1 with >2 neighbours | `line.py:298` |
| **`text.encoding_broken`** | **FREE** | 0..1 | fraction of glyph runs whose font has no/partial `ToUnicode` CMap, or is CID-keyed with no mapping | `pdf-inspector` already computes exactly this and `anydoc/src/formats/pdf.rs:27` *throws it away* with a `log::warn!("broken font encodings detected; extracted text may be garbled")`. **This is the single highest-value free signal in the collection and one repo logs it instead of routing on it.** |
| `text.replacement_density` | FREE | 0..1 | density of U+FFFD, PUA code points, and stray control chars | — |
| `text.plausibility` | FREE | 0..1 | script-aware character n-gram score against a shipped frequency table (data, ~2 MB, no model weights) | the honest, weaker stand-in for the DistilBERT scorer |
| `raster.ink_ratio` | FREE | 0..1 | non-white fraction of a 72-dpi thumbnail | replaces marker's `is_blank_image` crop check (`line.py:409` area gate) |
| `layout.class_frac[T]` | LOCAL | 0..1 | per-page fraction of Table/Form/Equation/Figure/Header/Footer blocks | drives R8 exclusions and the table/math sub-ladders |
| `doc.prefilter.is_form` | FREE | bool | `pdf_reader.get_form_text_fields()` | `olmocr/olmocr/filter/filter.py:29-32` — **as a signal, never an exclusion** |
| `doc.prefilter.spam_score` | FREE | 0..1 | 13-word SEO lexicon score, olmocr's threshold 0.004 | `olmocr/olmocr/filter/filter.py:20,34-58` |
| `doc.prefilter.language` | FREE | code | permissive detector | `filter.py:23` — olmocr defaults to English-only and drops the rest at `logger.info`; omniweave records and routes |
| `unit.rebill_risk` | FREE | bool | has this `content_digest` already been produced at a billed tier? | ledger lookup |
| `text.garble_p` | LOCAL | 0..1 | **optional** `omniweave-garble-v1`, a small char-level classifier trained on synthetically corrupted ToUnicode maps; ships in `omniweave-vision`, never in core | the eventual replacement for signals 4–6 as a single calibrated score |

Two points I will not soften:

- **`marker`'s numeric thresholds are not transferable.** `0.25`, `0.5`, `0.05`, `50 chars`
  (`line.py:35,45,115,110`) are calibrated against *marker's* classifier's score distribution. Copying
  them onto a different signal set is precisely the trap `DIGEST.md` names — *"never inherit ranking
  constants hand-calibrated against named fixtures as constants."* The shipped default policy
  therefore ships **deliberately conservative** thresholds, over-escalates, and the run manifest says
  `calibration: bootstrap` until an eval set is registered. The policy file carries the calibration
  procedure by reference (`calibration.eval_set_id`), and R16 keeps a vendor number from filling the
  gap.
- **`doc.prefilter.*` must be on by default and must never delete a document.** olmocr's `PdfFilter`
  is a ~$0 CPU pass and `--apply_filter` is `action="store_true"` — off. omniweave inverts it: the
  pre-filter runs always, its verdict is a *signal*, and a policy that maps a verdict to `skip` must
  record `skipped{reason, signal, threshold}` on the document so it is auditable and appealable.
  *"Is a form" is a routing signal, not an exclusion.*

**Signal fast path (bounds the cost of deciding).** If `text.present ≥ 0.9 ∧ encoding_broken = 0 ∧
replacement_density = 0 ∧ overlap_fraction ≤ 0.1`, the router short-circuits to the text-layer rung
without computing `plausibility`, `raster.ink_ratio`, or any LOCAL signal. On a born-digital corpus
that is the overwhelmingly common path, and it must cost ~1 ms/page or the router is itself the
regression. marker has the same structure: `disable_ocr` skips the classifier entirely so no
inference server is needed (`line.py` config table).

---

## 5. Concrete shape

### 5.1 The policy file

```toml
# policy/represent.toml  — authored form. Compiled to a PolicyImage; digest enters every cache key.
schema  = 1
name    = "represent.default"
version = 7
owner   = "parse-team"
notes   = "Bootstrap thresholds. calibration.eval_set_id unset => manifest reports calibration:bootstrap."

# ---- shadow prices: micro-dollars per unit of each CostVector component -------------
[objective]
wall_ms       = 0.0     # batch deployment: latency is free
cpu_ms        = 0.004   # ~$0.014/core-hour
gpu_ms        = 11.0    # ~$40/GPU-hour
tokens_in     = 0.10    # per 1k tokens  (olmocr hosted FP8 low end)
tokens_out    = 0.20    # per 1k tokens
provider_calls = 0.0
egress_bytes  = 0.0

[calibration]
eval_set_id        = ""            # unset => calibration:bootstrap in every run manifest
max_age_days       = 30
min_probe_samples  = 30

# ---- signals this policy may reference; the compiler checks cost_class against R4 ----
[[signal]]
id = "text.encoding_broken"; driver = "signals.text_layer.encoding"; version = 1
cost_class = "FREE"; range = [0.0, 1.0]; cache = "content"          # keyed by content_digest
[[signal]]
id = "text.plausibility"; driver = "signals.plausibility.ngram"; version = 3
cost_class = "FREE"; range = [0.0, 1.0]; cache = "content"
[[signal]]
id = "text.garble_p"; driver = "signals.model.garble_v1"; version = 1
cost_class = "LOCAL_COMPUTE"; range = [0.0, 1.0]; cache = "content"
optional = true; on_unavailable = "unknown"    # NOT "assume clean"

# ---- render profiles are policy data, applied AFTER the decision ---------------------
[render.structure]     # cheap tier: enough to see layout
short_edge_min_px = 692        # lift's floor; DPI is derived from it, never set directly
area_max_px       = 6291456    # 3072x2048, surya's cap
patch_snap        = 28         # ViT patch grid
binarize          = false      # never. (Ollama-OCR's Otsu path is actively harmful to a VLM.)
[render.glyph]         # expensive tier
short_edge_min_px = 1384
area_max_px       = 6291456
patch_snap        = 28
binarize          = false

# ---- the ladder ---------------------------------------------------------------------
[ladder]
goal        = "REPRESENT"
granularity = "part"          # part == page | slide | sheet | track. NEVER mixed. (see §8.8)
promote_bias = 0.15           # 1/7 crossover from the ~7x page-vs-block measurement
exclude_block_types = [
  { type = "PageHeader", because = "OCRing furniture wastes a VLM call and one flagged footer would spawn a server for a clean document (marker line.py:121-124)" },
  { type = "PageFooter", because = "same" },
  { type = "Equation",   because = "has its own math sub-ladder" },
  { type = "Table",      because = "has its own table sub-ladder" },
  { type = "Figure",     because = "asset path, not a text path" },
]

[[ladder.rung]]
id = "decode.native"; tier = 0; driver = "drivers.decode.native"
guard = "format.family in {office, html, epub, csv, md}"
accept = ["parse_valid"]
on_reject = "escalate"; on_unknown = "escalate"

[[ladder.rung]]
id = "decode.pdf_text"; tier = 1; driver = "drivers.decode.pdfium"
render = "none"
guard = """
  text.present >= 0.05
  and text.layout_coverage >= 0.25
  and text.overlap_fraction <= 0.50
  and text.encoding_broken <= 0.02
  and coalesce(text.garble_p, text.plausibility_inv) <= 0.05
"""
reading_order = "char_stream"      # 75% vs 56% vs a learned head; never re-infer here
accept = ["parse_valid", "coverage_backcheck"]
on_reject = "escalate"; on_unknown = "escalate"

[[ladder.rung]]
id = "ocr.block"; tier = 2; driver = "drivers.ocr.olmocr7b"; render = "glyph"
mode = "block"
guard = "flagged_block_frac > 0 and flagged_block_frac <= ladder.promote_bias"
max_tokens = "clamp(layout.token_estimate + 100, 64, 8192)"
sampling = { temperature = 0.1, top_p = 1.0, repetition_penalty = 1.0 }
accept = ["repeat_loop", "finish_reason_stop", "token_budget", "blank_region"]
on_reject = "escalate"; on_unknown = "defer"

[[ladder.rung]]
id = "ocr.page"; tier = 3; driver = "drivers.ocr.olmocr7b"; render = "glyph"
mode = "page"
guard = "true"                     # the general-purpose rung
max_tokens = 8000
sampling = { temperature = 0.1, top_p = 1.0, repetition_penalty = 1.0 }
accept = ["repeat_loop", "finish_reason_stop", "token_budget", "rotation_valid", "blank_region"]
on_reject = "escalate"; on_unknown = "defer"

[[ladder.rung]]
id = "ocr.page.r1"; tier = 4; retry_of = "ocr.page"
sampling = { temperature = 0.2, top_p = 0.95 }
accept = ["repeat_loop", "finish_reason_stop", "token_budget", "rotation_valid"]
on_reject = "escalate"; on_unknown = "defer"
[[ladder.rung]]
id = "ocr.page.r2"; tier = 5; retry_of = "ocr.page"
sampling = { temperature = 0.4, top_p = 0.95 }
on_reject = "exhaust"; on_unknown = "defer"

[[ladder.rung]]                    # deny-by-default; compile fails without dpa_ref (R10)
id = "ocr.hosted.frontier"; tier = 6; driver = "drivers.ocr.frontier"
enabled = false
guard = "trust_class == 'internal' and doc.pages <= 50"
on_reject = "exhaust"; on_unknown = "defer"

[ladder.on_exhaust]                # the ONLY backward edge (R6)
rung = "decode.pdf_text_raw"       # emit the raw text layer, marked degraded
degraded_reason = "all_rungs_rejected"

# ---- budgets: nested scopes, currency and time, never retry counts -------------------
[budget.run]      billed_micros = 5_000_000; gpu_ms = 7_200_000; wall_ms = 3_600_000
[budget.document] billed_micros = 250_000
[budget.part]     billed_micros = 1_500;  gpu_ms = 20_000   # makes 64x unreachable
[budget.probe]    fraction_of_run = 0.02  # reserved OFF THE TOP, before any work

[budget.on_exhausted]
REPRESENT = "use_best_available"   # a half-parsed page still has its text layer
EXTRACT   = "defer"               # a half-extracted schema is worse than none

# ---- quality bands: breaching one raises a QualityAlarm; auto_degrade is opt-in ------
[[quality.expect]]
rung = "decode.pdf_text"; acceptor_reject_rate = { max = 0.05 }
probe_disagreement = { max = 0.08 }; auto_degrade = true; auto_degrade_ttl_h = 24
[[quality.expect]]
rung = "ocr.page"; acceptor_reject_rate = { max = 0.15 }; auto_degrade = false
[[quality.expect]]
signal = "text.encoding_broken"; unavailable_rate = { max = 0.01 }; on_breach = "pause_admission"

[probe]
rate = 0.01                        # deterministic hash sampling, not RNG
oracle_rung = "ocr.page"
metrics = ["text_agreement", "structure_agreement", "order_tau"]
symmetric = true                   # alarms on WASTED escalation too, not only on under-escalation

[override_policy]
request_allowed = ["ceiling", "budget", "goal"]   # a request may never allow a denied driver
                                                  # or raise a budget above the deployment cap
reason_required_at = ["deployment", "corpus"]
```

### 5.2 RPL — the predicate language, specified

Not a general rules engine. A total, side-effect-free grammar whose entire point is that the
compiler can type-check it against the signal registry and the price book.

```ebnf
expr    ::= or
or      ::= and ( "or" and )*
and     ::= not ( "and" not )*
not     ::= "not" not | cmp
cmp     ::= term ( ("<"|"<="|">"|">="|"=="|"!="|"in") term )?
term    ::= NUMBER | STRING | BOOL | signal | call | set | "(" expr ")"
signal  ::= IDENT ( "." IDENT )*            # must exist in [[signal]] or be a builtin
call    ::= ("coalesce"|"frac"|"count"|"max"|"min"|"clamp"|"abs") "(" expr ("," expr)* ")"
set     ::= "{" STRING ("," STRING)* "}"
```

No loops, no recursion, no user functions, no `eval`. Guaranteed to terminate. Canonically
serialized so the digest is stable across formatting.

**Three-valued (Kleene) semantics, because two-valued logic here is a silent-correctness bug.** A
signal that could not be computed is `unavailable`; any comparison against it is `unknown`;
`unknown and false = false`, `unknown or true = true`, otherwise `unknown` propagates. A rung whose
guard evaluates `unknown` takes its **declared** `on_unknown` — and `on_unknown` is a *required*
field, so there is no default to get wrong. The shipped policy uses `escalate` for FREE rungs
(correctness first) and `defer` for BILLED rungs (an unavailable signal must never be able to spend
money). This is the direct application of the digest's rule that *"a soft fallback on an identity or
safety input is always a silent correctness bug"* — `on_unavailable = "assume clean"` is exactly the
`except Exception: return {}` pattern that turns a safety check into a no-op at the moment it was
needed.

### 5.3 Types

```python
# omniweave/route/policy/schema.py
class CostClass(StrEnum): FREE = "free"; LOCAL_COMPUTE = "local_compute"; BILLED_API = "billed_api"
class RouteGoal(StrEnum): REPRESENT = "represent"; EXTRACT = "extract"; LOCATE = "locate"

@dataclass(frozen=True)
class CostVector:
    wall_ms: int = 0; cpu_ms: int = 0; gpu_ms: int = 0
    tokens_in: int = 0; tokens_out: int = 0
    provider_calls: int = 0; egress_bytes: int = 0
    def spend_micros(self, objective: "Objective") -> int: ...   # exact integer arithmetic

@dataclass(frozen=True)
class SignalValue:
    id: str; version: int
    value: float | bool | str | None      # None == unavailable
    unavailable_reason: str | None = None
    cost: CostVector = CostVector()
    def __post_init__(self):
        if self.value is None and not self.unavailable_reason:
            raise ValueError("unavailable SignalValue must name its reason")

@dataclass(frozen=True)
class Rung:
    id: str; tier: int; driver: str
    guard: Predicate                       # parsed RPL AST, not a string
    render: str | None
    accept: tuple[str, ...]
    on_reject: Literal["escalate", "exhaust", "fail"]
    on_unknown: Literal["escalate", "defer", "fail"]      # REQUIRED — no default
    retry_of: str | None = None
    sampling: Mapping[str, float] = field(default_factory=dict)
    reads_signals: frozenset[str] = frozenset()           # derived from guard by the compiler

@dataclass(frozen=True)
class PolicyImage:
    digest: str                            # sha256_canonical of the whole image
    goal_ladders: Mapping[RouteGoal, Ladder]
    objective: Objective
    signals: Mapping[str, SignalDecl]
    budgets: Mapping[BudgetScope, CostVector]
    probe: ProbeSpec
    quality: tuple[QualityBand, ...]
```

```python
# omniweave/route/exec/router.py
@dataclass(frozen=True)
class RouteDecision:
    id: str                                # uuidv7
    unit: UnitRef                          # runtime §7.1: (uri, content_digest, part)
    goal: RouteGoal
    policy_digest: str
    pricebook_digest: str
    override_digest: str
    signals: tuple[SignalValue, ...]                 # R12 — the full vector
    predicate_trace: tuple[tuple[str, Ternary], ...] # (rung_id, TRUE|FALSE|UNKNOWN) in order
    admissible: tuple[str, ...]
    chosen_rung: str | None                          # None == deferred/unrouted
    estimate: CostVector
    estimate_ceiling: CostVector                     # what was RESERVED
    budget_headroom: Mapping[str, int]               # snapshot, so replay is exact (§6)
    applied_overrides: tuple[AppliedOverride, ...]   # incl. kind="inert"
    probe_selected: bool
    probe_salt: str
    stopped_at_tier: int | None
    degraded: bool
    degradations: tuple[str, ...]

class Router:
    def decide(self, unit: UnitRef, goal: RouteGoal, ctx: RunContext) -> RouteDecision: ...
    def next_rung(self, prev: RouteDecision, reject: AcceptorVerdict) -> RouteDecision: ...
```

`Router.decide` computes signals lazily in `cost_class` order, evaluating rung guards as soon as
their `reads_signals` are satisfied — so a clean page never computes a LOCAL signal.

### 5.4 Ledger DDL

```sql
-- omniweave/route/ledger/ddl.sql
CREATE TABLE policy (                       -- content-addressed, append-only, never UPDATEd
  digest        TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  version       INTEGER NOT NULL,
  image_json    BLOB NOT NULL,              -- canonical JSON, zstd
  source_toml   BLOB NOT NULL,              -- the authored form, for diffs
  created_at    TEXT NOT NULL,
  UNIQUE(name, version)
);
CREATE TABLE policy_active (
  goal          TEXT PRIMARY KEY,
  policy_digest TEXT NOT NULL REFERENCES policy(digest),
  activated_by  TEXT NOT NULL,              -- R13: the tuner has no grant here
  activated_at  TEXT NOT NULL,
  reason        TEXT NOT NULL
);

CREATE TABLE route_decision (
  id                TEXT PRIMARY KEY,               -- uuidv7
  unit_uri          TEXT NOT NULL,
  unit_part         TEXT NOT NULL DEFAULT '',       -- '' not NULL: NULL breaks UNIQUE (I-runtime)
  content_digest    TEXT NOT NULL,
  goal              TEXT NOT NULL,
  policy_digest     TEXT NOT NULL REFERENCES policy(digest),
  pricebook_digest  TEXT NOT NULL,
  override_digest   TEXT NOT NULL,
  generation        INTEGER NOT NULL,               -- runtime §7.8.1, integer not clock
  group_id          TEXT,                           -- set when a part_group rung claimed a window
  signals           BLOB NOT NULL,                  -- canonical JSON, zstd   (R12)
  predicate_trace   BLOB NOT NULL,
  admissible        TEXT NOT NULL,
  chosen_rung       TEXT,
  tier              INTEGER,
  estimate_json     BLOB NOT NULL,
  reserved_micros   INTEGER NOT NULL,
  actual_json       BLOB,                           -- filled on commit
  actual_micros     INTEGER,
  budget_headroom   BLOB NOT NULL,
  applied_overrides BLOB NOT NULL,
  probe_selected    INTEGER NOT NULL DEFAULT 0,
  probe_salt        TEXT NOT NULL,
  stopped_at_tier   INTEGER,
  degraded          INTEGER NOT NULL DEFAULT 0,
  degradations      BLOB NOT NULL DEFAULT x'',
  accepted_by       TEXT,                           -- R14
  outcome           TEXT,                           -- runtime Outcome
  decided_at        TEXT NOT NULL,
  UNIQUE(content_digest, unit_part, goal, policy_digest, pricebook_digest, override_digest)
);
CREATE INDEX route_decision_unit  ON route_decision(unit_uri, unit_part, goal);
CREATE INDEX route_decision_score ON route_decision(policy_digest, chosen_rung, decided_at);
CREATE INDEX route_decision_probe ON route_decision(probe_selected) WHERE probe_selected = 1;

CREATE TABLE route_signal_cache (           -- FREE-tier semantics: namespaced, SWEPT
  content_digest TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
  signal_id TEXT NOT NULL, signal_version INTEGER NOT NULL,
  value BLOB, unavailable_reason TEXT, cost_json BLOB NOT NULL, computed_at TEXT NOT NULL,
  PRIMARY KEY (content_digest, unit_part, signal_id, signal_version)
) WITHOUT ROWID;

CREATE TABLE route_probe (
  id TEXT PRIMARY KEY,
  base_decision_id  TEXT NOT NULL REFERENCES route_decision(id),
  oracle_decision_id TEXT NOT NULL REFERENCES route_decision(id),
  text_agreement REAL, structure_agreement REAL, order_tau REAL,
  oracle_won INTEGER NOT NULL,        -- did the oracle's artifact get served?
  extra_micros INTEGER NOT NULL,
  measured_at TEXT NOT NULL
);

-- the scorecard is a VIEW first, a materialised rollup only when it stops being fast
CREATE VIEW driver_scorecard AS
SELECT d.policy_digest, d.chosen_rung, json_extract(d.actual_json,'$.model_revision') AS revision,
       COUNT(*) AS n,
       AVG(CASE WHEN d.outcome LIKE 'failed%' THEN 1.0 ELSE 0.0 END) AS reject_rate,
       AVG(1.0 - COALESCE(p.text_agreement, 1.0))                     AS disagreement,
       SUM(d.actual_micros)                                           AS spent_micros
FROM route_decision d LEFT JOIN route_probe p ON p.base_decision_id = d.id
GROUP BY 1,2,3;
```

Ledger cost: ~400–900 bytes/part after zstd. A 4,000-page PDF ⇒ ~3 MB; 10M pages ⇒ ~7.5 GB.
`ledger.retain_signals = always | probe_only | off` bounds it — and `off` sets
`calibration: disabled` in **every** run manifest, so it can never be off silently.

### 5.5 Two schedules, and the reuse rule nobody states

Decisions are cheap to recompute; artifacts are not. So a policy change invalidates decisions but
**must not** invalidate artifacts:

| Existing artifact tier vs. new policy's choice | Action | Record |
|---|---|---|
| existing **≥** new choice | reuse the existing artifact | `reused_above_policy{had_tier, policy_tier}` |
| existing **<** new choice, cost class FREE/LOCAL | run the new rung now | normal |
| existing **<** new choice, cost class BILLED_API | **never auto-run** — enqueue `needs_upgrade` as `DEFERRED_BUDGET` with a pending-cost record | `needs_upgrade{from, to, would_cost_micros}` |

The first row is the one a naive implementation gets wrong: re-running a *cheaper* rung to "comply"
with a new policy spends money to obtain a worse answer. The third row is graphify's rule
generalised — *a watcher must never auto-run billable work* — and it is why `omniweave route plan
--policy represent.toml@8` must print a priced upgrade diff before anyone activates v8.

---

## 6. Deterministic replay

```
$ omniweave route replay 018f2a…c41
policy    represent.default@7  (digest 9a1c…)   pricebook 4f02…   overrides 0000… (none)
signals   text.present=1.00  layout_coverage=0.31  overlap_fraction=0.07
          encoding_broken=0.34  replacement_density=0.00  plausibility=0.51
          garble_p=<unavailable: driver 'signals.model.garble_v1' not installed>
trace     decode.native      FALSE  (format.family == pdf)
          decode.pdf_text    FALSE  (text.encoding_broken 0.34 > 0.02)
          ocr.block          FALSE  (flagged_block_frac 1.00 > 0.15)
          ocr.page           TRUE
chosen    ocr.page  (tier 3)   estimate 214 micros   reserved 1_500   actual 197
budget    part headroom at decision: billed_micros=1500 gpu_ms=20000
probe     not selected  (H(id‖salt) = 0.6631 >= 0.01)
verdict   REPLAY MATCHES  (chosen_rung, predicate_trace, admissible all equal)
```

The mechanics: policies are content-addressed and never mutated (`policy` table), the full signal
vector and the *budget headroom snapshot* are stored, and probe sampling is
`H(decision_id ‖ probe_salt) < rate` — a deterministic hash, never an RNG.

**Honest boundary:** per-decision replay is exact. **Whole-run replay is exact only under
`--serial --budget-from-ledger`**, because the budget headroom another worker saw depends on
interleaving. That is a real limitation and it is why the headroom snapshot is per-decision: the
decision replays exactly even when the run does not.

---

## 7. Budget enforcement and graceful degradation

Plugs into runtime §7.8.2's `BudgetLedger`. Additions:

1. **Reserve the ceiling, commit the actual.** Reserving the mean lets N documents each overspend by
   half a document. `estimate_ceiling` is the p99 of the estimator, and the estimator is calibrated
   from the ledger's `actual_json` — the router's own history is its cost model.
2. **Nested scopes:** `run > corpus > document > part > probe`. A runaway document cannot consume the
   corpus budget. The **part** budget is the one that matters: 1,500 billed micros by default, which
   makes olmocr's 12,800-micro retry path unreachable without an explicit override.
3. **Probe budget is reserved off the top**, before any work. If it cannot be reserved the manifest
   says `calibration: unfunded`. A router with no probe budget is, by construction, uncalibrated, and
   it must say so on every run.
4. **Denial is not failure.** `Outcome.DEFERRED_BUDGET`, `stopped_at_tier`, and the part is marked
   `unrouted{reason, would_cost_micros}` in the L2 model — which serve already knows how to annotate
   (its per-unit pending list). A budget-exhausted run returns a **complete document** whose gaps are
   named, never a `FAILURE`.
5. **The degradation ladder is declared, not improvised:** `budget.on_exhausted` per goal.
   `use_best_available` for REPRESENT (the raw text layer is still worth something);
   `defer` for EXTRACT (a half-filled schema reads as a complete answer and is worse than none —
   lift measures **90.2% per field but 20.9% full-document** on its own adversarial benchmark).
6. **Retries are rungs (R15)**, serial, charged to the same budget. This is the structural fix for
   the collection's universal mistake of bounding cost with a retry count: a count cannot bound spend
   when per-attempt cost varies 100× with page density, and it cannot express "stop spending on this
   corpus at all".
7. **Admission pause, not drop.** When a `quality.expect … on_breach = "pause_admission"` fires, the
   router stops *admitting* new units at that rung and the work rows stay claimable — runtime
   §7.3.5's `max_inflight` pause-the-producer semantics, never a drop.

---

## 8. The quality feedback loop — how it stays honest

Three mechanisms, and the third is the one that makes the first two trustworthy.

**8.1 Free signal, always on: acceptor reject rate and escalation cause.** Every run already produces
`escalation_rate` and an `escalation_cause` histogram per `(corpus, format, rung, model_revision)`,
because R2 wrote the decision and the acceptors wrote their verdicts. A driver degrading — a model
revision bump, a corpus shift, a provider silently swapping a checkpoint — shows up as reject rate
crossing its declared band **within one run**, at zero extra cost.

**8.2 `ShadowProbe`: a deterministically sampled second opinion.** With `probe.rate` (default 0.01,
funded by `budget.probe`, default 2% of the run), a unit routed to tier k is *also* routed to
`probe.oracle_rung`. Selection is `H(decision_id ‖ probe_salt) < rate`, so it is replayable. If the
oracle's artifact passes its acceptors it **is served** (`route_probe.oracle_won = 1`) — money already
spent is not thrown away — and the ledger records which artifact was served, so cost attribution
stays exact.

Agreement metrics needing no ground truth: `text_agreement` (olmOCR-bench's `normalize_text` plus a
`max_diffs` fuzzy budget), `structure_agreement` (block-type histogram distance, table cell-count
delta), `order_tau` (Kendall tau over reading order).

**Probing is symmetric.** `probe.symmetric = true` alarms on *wasted* escalation as loudly as on
under-escalation: if tier 3's output agrees with tier 1's at >0.98 across n≥30 samples in a corpus
cell, that is `wasted_escalation` and it is a cost bug of exactly the same severity as a quality bug.
Every escalation-only feedback loop in the collection ratchets one way; this one does not.

**8.3 Auto-degrade, bounded.** `quality.expect … auto_degrade = true` lets the router apply a
**corpus-scoped `floor` override** (raise the entry tier for that corpus) with a mandatory TTL
(`auto_degrade_ttl_h`) and a mandatory manifest entry. This is codegraph's futility-latch doctrine —
*"a governor must detect that it cannot help and get out of the way"* — applied to a driver instead
of a WAL valve. It can only ever move within pre-authorised bounds, it expires, and it is recorded.

**8.4 The tuner is offline and advisory (R13).** Because R12 stored the full signal vector, a
candidate policy can be **re-scored against history without running a single driver**:
`argmin Σ spend_micros(policy', signals_i)` subject to `disagreement(policy') ≤ target`, evaluated on
the stored vectors and the probe rows. Output is a `policy_candidate` plus a counterfactual table —
"v8 saves 41% of billed micros and raises measured disagreement from 0.061 to 0.068 on 12,400 stored
decisions" — that a human activates. This is the entire justification for the ledger's size.

**8.5 The honesty machinery.** Three structural commitments:

- **R16: no vendor number may enter the policy.** The schema has no accuracy field. Quality exists
  only in the scorecard and only as a local measurement. HunyuanOCR's 94.10 was measured on TensorRT
  while the repo ships Transformers and vLLM, which it admits disagree; marker/surya/lift pin no
  `revision=` anywhere, so their published numbers are not reproducible even in principle.
- **Calibration age is a first-class, always-printed field.** `calibration: bootstrap | ok | stale |
  unfunded | disabled` appears in every run manifest, derived from the eval-set registration,
  `max_age_days`, and probe counts per cell. A router that does not know how good it is must say so.
- **Disagreement is labelled a lower bound on error, not an error rate.** Two rungs can agree and
  both be wrong (a rotated page, a text layer that lies about the pixels). The only truth source is a
  human-labelled eval set — olmOCR-bench's test-type taxonomy (`baseline/present/absent/order/table/
  math/format/footnote` with its relational `TableTest` assertions) plus lift's adversarial extraction
  categories. Without a registered `calibration.eval_set_id` the manifest reports
  `quality: unvalidated` and the tuner refuses to emit a candidate.

**8.6 `trust_class` is a routing input.** A text layer can *disagree with the rendered pixels* — a
real attack for altered contracts and for prompt injection hidden in invisible text. No cheap signal
detects it; only a raster cross-check does. So `trust_class = untrusted_external` raises `probe.rate`
to `probe.integrity_rate` (default 0.05) and forces the probe's comparison to include
`text_agreement`, turning the quality loop into an integrity check on a budgeted sample. Cheap-tier
routing is trust-on-first-parse for text-layer fidelity, and this is the bound on that trust.

**8.7 What the router emits per part** — the telemetry that costs nothing because R2 already wrote
it. marker's `page_stats` (`marker/marker/renderers/__init__.py:102-117`: `page_id`,
`text_extraction_method`, `block_counts`, `block_metadata`) is the right shape and this is its
superset: `{part, goal, chosen_rung, tier, escalated_from, escalation_cause, signals, estimate,
actual, degradations, probe, calibration_age_days, decision_id}`. `decision_id` is the join key from
any downstream artifact back to the exact decision — provenance for cost, not just for content.

**8.8 Mixed granularity, resolved.** `mine-runtime.md` §7.12 leaves open what a "unit" is for a
4,000-page PDF, noting that mixing granularities breaks the cost model and the shrink guard. Answer:
**`unit_part` is always a canonical part (page/slide/sheet/track) and the ledger's grain never
changes.** A `part_group` rung — the long-horizon path — *claims a set of parts* and writes one
`route_decision` per part sharing a `group_id`, with the group's actual cost apportioned across its
parts by token share. Per-part attribution, failure isolation and the shrink guard all keep working.

---

## 9. Engaging the four named repos

**marker's per-page escalation — adopt the mechanics, move them into data.** Verified structure:
four ANDed page signals (`line.py:225-235`); per-block flagging gated on the page score
(`line.py:415`, `block_garbled_check_min_page_score`) with a 50-char floor (`:110`) and a 1%-page-area
floor plus a 75% sibling-containment guard for empty boxes (`:409`, `:443`); one batched classifier
call for all candidates document-wide; promotion at `0.0` balanced / `0.5` fast (`:473`). Every one of
those becomes a `Rung` guard, an `exclude_block_types` entry, or `promote_bias`. What marker cannot
do and this can: version the thresholds, digest them into the cache key, replay a decision, price a
rung, or answer "what would v8 have chosen" — because in marker they are Python constants in a class
and the only record kept is `page_stats.text_extraction_method`.

**surya's OCR-error detection — adopt the contract, reject the checkpoint.** The contract is
`scores: List[float]` beside `labels` (`surya/surya/ocr_error/schema.py`) and it is R5. The checkpoint
is `s3://ocr_error_detection/2025_02_18` (`surya/surya/settings.py:137`), Datalab-distributed under
the vetoed `MODEL_LICENSE`. Replacement in §4: `text.encoding_broken` (free, and the strongest single
signal — `pdf-inspector` computes it and `anydoc/src/formats/pdf.rs:27` merely `log::warn!`s it),
`replacement_density`, `plausibility`, with `omniweave-garble-v1` as the eventual calibrated scorer in
`omniweave-vision`. And the recalibration warning of §4: marker's 0.05 is *its* classifier's number.

**lift's schema-constrained shortcut — a `RouteGoal`, not a rung.** `lift/lift/extract.py`'s
`extract_images(images, schema, model)` takes page images and a schema and never builds a document
model at all. That is a legitimate ladder — the EXTRACT ladder may skip layout and text-layer rungs
entirely — with three non-negotiables. (a) It still emits an L2 skeleton with **per-field provenance
and per-field confidence**, because 90.2% field / 20.9% full-document means a document-level pass/fail
is a lie. (b) `make_properties_nullable` before constrained decoding and `minItems` on every array, or
the grammar forces invention (surya disabled guided table-rec entirely over the cardinality problem).
(c) If a fresh REPRESENT artifact exists, EXTRACT reuses it rather than re-rendering — `prefer_reuse`
in the ladder, and the estimator prices both paths.

**Unlimited-OCR's long-horizon path — and a correction to the blueprint.**
`_index/framework-blueprint.md:107` routes "long-horizon multi-page and layout-consistent" documents
to "tier 3 one-shot (Unlimited-OCR)". **The repo does not do that.** `Unlimited-OCR/infer.py`'s own
docstring says *"PDF pages: pass --pdf and each converted page is sent as one request,"* with
`PAGE_SIZE = 1` and `PDF_DPI = 300`. There is no one-shot whole-document path to inherit. What the
repo does contribute is the acceptor configuration for long generations
(`NO_REPEAT_NGRAM_SIZE = 35`, `NGRAM_WINDOW = 128`, `CONTEXT_LENGTH = 32768`) and the exact worst case
to design against: `REQUEST_TIMEOUT = 1200` × `MAX_RETRIES = 5` = **100 minutes of a GPU per
document**, with a silent `{"text": ""}` on give-up. So: long-horizon is expressed as a `part_group`
rung with a declared `window` and `carry` (overlapping windows with running context), never as
"whole document", so one window's failure yields `PARTIAL_SUCCESS` and not a blank page (R9 forbids
the empty-string outcome); and the 100-minute path is unreachable because `budget.part.gpu_ms` is
20,000 and a `part_group` reservation is the sum over its parts.

**Also folded in:** olmocr's rotation/`finish_reason`/token-budget checks and `RepeatDetector` become
named `Acceptor`s; its `PdfFilter` becomes signals that are on by default and never delete a document;
its temperature ladder becomes tier-4/5 rungs under R15 (serial, budgeted). docling's per-page
`ConfidenceReport` becomes signal inputs that are actually *consumed*. anydoc's
`ConvertError::NeedsOcr{pages, page_count}` (`anydoc/src/error.rs:20`, code `"needsOcr"` at `:103`) is
the right shape for an error used as routing data — omniweave's version is per-part in the ledger
rather than a document-fatal error, which fixes anydoc's one bluntness (one OCR page currently fails
the whole document).

---

## 10. What this costs

**Engineering.** Policy schema + RPL + compiler ≈ 1,500 LoC. Ledger, DDL, claim-with-decision,
replay ≈ 800. Signal registry + the 12 signals ≈ 1,200 (the PDF font/encoding scanner is the hard
part). Acceptors ≈ 600. Probe + scorecard + tuner ≈ 1,000 plus an offline job. CLI ≈ 400. Tests for
R1–R16 ≈ 1,200. **≈ 6.7 kLoC, 6–9 engineer-weeks for two people to reach the invariant set**, plus
~3 weeks for `omniweave-garble-v1` and its synthetic calibration corpus, plus a standing ~0.2 FTE to
own the default policy and the eval set. Call it **3 person-months**.

That is a lot for "routing", and the defence is one sentence: **you can swap a driver in a week; you
cannot retroactively obtain signal vectors you never stored.** Every other part of this is
retrofittable. R12 is not.

**Runtime overhead.** Fast-path signals ≈ 1–3 ms/page CPU on top of the text extraction already
performed; the 72-dpi thumbnail 5–10 ms/page when needed; policy evaluation < 50 µs/part (a parsed
AST over a dict). Ledger write ≈ 400–900 bytes/part, batched one transaction per `page_batch_size`
(docling's 4). Against a 200-micro VLM page the router's overhead is ~1–2% of spend on an escalated
page and ~100% of spend on a free page — which is the point: on the free path the *absolute* number
is single-digit milliseconds.

**Memory.** Signal vector ~1 KB/part, held only for the batch. `PolicyImage` < 100 KB resident. No
model in core.

**Dependency weight.** Zero new heavy dependencies. RPL is hand-rolled (no lark/pyparsing);
`plausibility` is a data table; the garble model lives in `omniweave-vision`. Core stays inside the
250 MB target and loads no torch — which is what keeps "a 100% cache hit loads zero models" true.

**Operational burden, honestly stated.** A new reviewable artifact class (policy versions), a
calibration corpus with an owner, a ledger retention policy, and an alarm surface someone must watch.
This is the real cost and it is not small.

---

## 11. Failure modes

1. **Threshold transfer (most likely to bite first).** My signals are not marker's, so marker's
   constants are wrong for them. **The input that breaks it: a corpus of clean CID-keyed CJK PDFs with
   absent `ToUnicode` CMaps.** `text.encoding_broken` fires on every page, the router escalates the
   entire corpus to a 7B VLM, and the bill is ~200 micros/page instead of ~0. Detection is built in —
   symmetric probing raises `wasted_escalation` when tier-3 output agrees with tier-1 at >0.98 — but
   detection needs n≥30 probe samples per cell, so the first thousand pages are overspent. Mitigation
   beyond that: a corpus-scoped `ceiling` override, and a script-aware refinement of
   `encoding_broken` that treats a consistent CID→Unicode fallback table as clean.
2. **Signal cost creep.** R4 bounds each signal individually; nothing bounds twelve of them in
   aggregate. On a 10M-page corpus a careless policy can spend more deciding than on tier 1. Bounded
   by the fast path (§4) and by `budget.signal_micros` per part, but a policy author can defeat both.
3. **Ledger growth.** ~7.5 GB at 10M pages. Needs the retention policy and, past ~100M parts, a
   rollup table and probably a columnar export. Real operational burden; the design's largest ongoing
   cost.
4. **All-guards-unknown cascade.** A crashed signal driver (a corrupt font table that throws on every
   page) makes every guard `unknown`. With `on_unknown = escalate` on a BILLED rung that is a
   full-corpus escalation. This is why `on_unknown` is a *required* field, why BILLED rungs default to
   `defer`, and why `quality.expect … unavailable_rate → pause_admission` is a hard gate rather than a
   warning. If someone writes `on_unknown = "escalate"` on tier 3, the design does not save them.
5. **Probe starvation and silent decalibration.** Under a tight run budget probes get squeezed. The
   off-the-top reservation and the `calibration: unfunded` banner cover it, but an operator who sets
   `probe.rate = 0` gets a frozen scorecard forever. The banner is the only defence and banners get
   ignored.
6. **Agreement is not truth.** The tuner optimises measured disagreement, which is a lower bound on
   error. A systematic error both rungs share (a rotated page class, a footnote convention) is
   invisible to it and the tuner will happily tune the router into it. Only the human-labelled eval
   set catches that, which is why `quality: unvalidated` blocks candidate emission.
7. **An adversarial text layer.** Cheap-tier routing trusts the text layer's fidelity to the pixels.
   `trust_class` + `integrity_rate` bound the exposure to a sampled cross-check; they do not eliminate
   it. A single targeted document with a lying text layer will very likely pass through at tier 1.
8. **NIH risk on RPL.** If RPL grows loops, user functions, or a plugin mechanism, I was wrong and
   CEL was the answer. The tripwire is explicit: any proposal to add a construct that makes RPL
   non-total is a signal to adopt an off-the-shelf evaluator and give up the R4/R6 compile-time checks.
9. **The layout-rung hole.** Until a licence-clean layout detector exists, tier 2 is thin and pages
   needing layout fall to tier 3. The router makes this visible (`escalation_cause =
   layout_driver_unavailable` in every affected decision) rather than hiding it, but visible is not
   fixed. This is the largest quality/cost consequence of the weight vetoes and it is a driver
   decision, not a routing one — the routing design's job is to make adding that driver a one-row
   policy change.

---

## 12. Why I reject the alternatives

**(a) Routing as code (marker's `LineBuilder`).** The honest baseline; it demonstrably works. Reject
because the thresholds are Python constants, so tuning is a code deploy; the decision is not
recorded beyond `page_stats.text_extraction_method`; there is no cost model at all; and you cannot
ask what a different policy would have done without re-running the corpus. marker's 14 `Annotated`
knobs settable from `--config_json` are *configuration*, not *policy* — no version, no digest, no
audit trail — and the same channel accepts dotted import paths (`--converter_cls`, `--processors`,
`--llm_service`), which is arbitrary-import RCE the moment config arrives in a request body. Config
that is not versioned and digested cannot enter a cache key, and routing that cannot enter a cache
key cannot be resumed correctly.

**(b) A learned router (a model picks the driver).** Reject on five-year correctness. It is
unauditable, not replayable without pinning the router's own weights alongside every driver's, it
puts a model load on the free path (breaking "a 100% cache hit loads zero models", which is what
makes `--dry-run` and cost estimation possible at all), and it has no way to express a licence deny,
a budget ceiling, or an operator override. A learned *signal* inside a declarative policy is exactly
right and is what I propose (`text.garble_p`). A learned *decision* is not.

**(c) Always run the best driver.** The spread is five orders of magnitude: ~$200 vs ~$12,800 per
million pages on olmocr's own published numbers. It also maximises egress and licence exposure — and
it is **worse on quality** for born-digital pages, because the PDF's own character stream beats a
learned reading-order head **75% vs 56%** on multi-column layouts, so a VLM re-reads text it did not
need to and loses order doing it.

**(d) Per-document routing (docling's `do_ocr` boolean).** docling computes the best per-page signals
in the collection and consumes none of them. One scanned insert costs a 300-page document at VLM
prices or loses that page. Rejecting this is the single least controversial claim in the proposal.

**(e) A general policy engine (Rego / CEL / Lua / JSONLogic).** Tempting, and I reject it
deliberately. R4 ("no signal costs more than the rung it gates") and R6 (cost monotonicity, with the
`tier`/`estimate` split) are decidable **only** because RPL is tiny and the ladder is an ordered
list; against a general expression language they degrade to runtime warnings. I would rather own 400
lines of grammar whose totality I can prove than inherit an evaluator whose expression space exceeds
what my compiler can check. Failure mode 8 records the condition under which this was the wrong call.

**(f) Budget as a retry count.** The collection's universal answer and the source of every cost
incident in the evidence: olmocr's 8 retries × 8k tokens (parallel), Unlimited-OCR's 5 × 1200 s. A
count cannot bound spend when per-attempt cost varies 100× with page density, and it cannot express
"stop spending on this corpus". Currency and time budgets with reserve-then-commit, and retries
modelled as rungs, are the only bound that holds under an adversarial input.

**(g) Store the verdict, not the signals.** The cheap ledger. Reject: without stored signal vectors
there is no offline re-scoring, hence no tuner, hence no tunable policy, hence the whole design
collapses back to (a) with extra machinery. 400–900 bytes per part is the price of the feedback loop,
and it is the one component that cannot be added later — you cannot recover signals you did not
store without re-parsing the corpus, which is the expensive thing the router exists to avoid.

**(h) Route on file extension / MIME alone.** `mine-parse.md` establishes that mime→format is
one-to-many and must be resolved by content probing (docling's `MimeTypeToFormat` returns a *list*;
anydoc resolves the OPC relationship graph with the root element as authority). Extension routing is
not a simpler version of this design; it is a different, wrong one.
