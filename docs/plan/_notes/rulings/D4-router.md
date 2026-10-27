# D4-router — The routing and escalation policy engine

## Decision

Routing is **data, not code**: a first-match-wins ordered list of `Rule`s, authored in TOML across six
merge layers, evaluated by a pure function over a flat, versioned `Evidence` record for one
`(unit, part)`. The predicate grammar is closed comparisons only — no arithmetic, no expressions, no
dotted-path imports — and a clause over an unavailable signal evaluates **UNKNOWN** under Kleene
semantics, forcing every rule that reads a nullable key to declare `on_unknown`. Escalation is
monotone in a closed seven-value ordered `Rung` enum (`GATE < DECODE < REPAIR < PAGE < REGEN <
DEGRADE < ENRICH`) crossed with an open `Lane` registry (`text`, `table`, `math`, `fields`,
`caption`), which replaces the blueprint's numbered tiers because a number cannot express a cheap
high-capability driver or an expensive low-capability one. Every decision is written to an
append-only `route_decision` row that records the **read set** — the evidence keys the winning path
actually consulted, with their provider versions — so a decision replays byte-for-byte, a candidate
policy re-scores over the entire history for $0, and a new signal provider does not invalidate
decisions that never consulted it. Cost is a seven-unit physical `Spend` vector (`wall_ms`, `cpu_ms`,
`gpu_ms`, `tokens_in`, `tokens_out`, `calls`, `bytes_egress`) that **no driver may price**; an
operator-owned `PriceBook` converts it to micros, budgets are declared per-dimension and the first
exhausted dimension wins, and `bytes_egress` defaults to 0 so an escalation cannot leave the machine
without a site-layer `Grant` carrying a `dpa_ref`. **Budget never changes which rung is chosen, only
whether it runs**: `evaluate()` is pure over `(policy, evidence, narrowing)`, a separate `admit()`
gate reserves against the ledger, and exhaustion is written back as the evidence key
`budget.exhausted`, which the `DEGRADE` rules read. Quality is measured on four verdict sources —
`self` (stored, never scored), `agree` (free cross-rung edit distance on every escalated part),
`audit` (a deterministically sampled reference run), `feedback` — rolled into a `Scoreboard` whose
zero value is `UNKNOWN`; learning fits thresholds offline and emits a diff a human commits, and the
only automatic write is a TTL-bounded demotion. The shipped default policy names **no
Datalab-licensed weights**: marker's garble classifier and its layout-coverage signal are both
replaced by licence-free CPU signals (`garble.score`, a calibrated in-house logistic regression, and
`ink.coverage`, a 96-DPI ink-tile measurement), and that substitution is the single highest-leverage
piece of engineering in this ruling.

## Spec

**The unit of decision is the part** (page / slide / sheet / track), identical to the `work` table's
`unit_part` (`mine-runtime.md` §7.3.1), with block-level *flags* rather than block-level decisions.
This settles the first of `mine-runtime.md` §7.12's open questions: the router's decision grain and
the work row's identity are the same thing, always. Per-document routing is rejected on measurement —
docling computes the best per-page quality signals in the collection and consumes none of them
because `do_ocr` is a document boolean, so a 188-page 10-K with 12 scanned exhibits either pays VLM
prices for 188 pages or returns garbage for 12. Per-block routing as the *primary* unit is rejected
because one full-page request is ~7× cheaper than N block requests on llama.cpp and more accurate
(`marker/marker/builders/ocr.py:76-84`, verified verbatim), so blocks are the right unit for a flag
and the wrong unit for a decision — which is exactly marker's promotion insight
(`line.py:466-481`: `0.0` in balanced, `block_ocr_promote_fraction = 0.5` in fast, both verified).

**Evidence is acquired by a demand plan, not by a rung and not by sampling.** The compiler groups
every reachable rule's reads by `cost_class`, computes `FREE` first, re-tests, and pays for
`LOCAL_COMPUTE` only if nothing has fired. A born-digital PDF page is therefore decided from
text-layer signals alone — `decode.char_count`, `decode.cid_ratio`, `decode.replacement_ratio`,
`geometry.overlap_line_frac` (line bboxes against line bboxes; **no layout model**, verified in
marker's `check_line_overlaps`) and `garble.score` — at ~2 ms/part, and never renders a raster. The
96-DPI raster that `ink.coverage` needs is `LOCAL_COMPUTE` and is paid only on the ambiguous middle.
I reject the pragmatist's `signal_sampling {head, stride, cap}`: it produces a *wrong prior* on
precisely the mixed document that motivates per-page routing — its own worked example, a 40-page
scanned appendix at pages 2,900–2,940 of a 4,000-page report, is missed by a stride of 32 — while
demand planning is exact and costs less.

**Two of marker's four page signals cannot be shipped and the default policy must not pretend
otherwise.** `surya/surya/settings.py:137` points the OCR-error classifier at
`s3://ocr_error_detection/2025_02_18` and `:153` points the layout detector at
`hf://datalab-to/surya_layout2`; `marker/MODEL_LICENSE`, `surya/MODEL_LICENSE` and
`lift/MODEL_LICENSE` are byte-identical at md5 `e1f69b64dee2f1641a9b1ab12adf24d6`, whose clause 2(c)
is a competitor bar with no threshold and whose clause 8 is viral on Output. So the garble classifier
and `layout_coverage` are both out, and `layout.class_hist` is **absent on day one** — which makes
the `REPAIR` rung thin on the PDF path until a licence-clean layout detector lands. The router's job
is to make that hole priced and visible, not hidden: every affected decision records
`cause = "layout_unavailable"`, and adding the detector is one `[[rule]]` plus one `driver.toml`.
Replacements: `ink.coverage` (96-DPI page, 8-px tiles, a tile inked below 0.85 relative luminance,
coverage = inked tiles intersecting a text-layer line bbox over inked tiles, gate ≥ 0.25 — marker's
threshold with the detector's *opinion* replaced by actual ink) and `garble.score` (a calibrated
logistic regression over seven CPU features: CID/`U+FFFD` ratio, out-of-dominant-block character
ratio, dictionary miss rate, single-char-token ratio, character 5-gram log-probability, stream
non-monotonicity, vowelless-run ratio). `garble.score` ships with a CI gate — **ECE ≤ 0.05 and Brier
≤ 0.08 on a held-out set, and a regression fails the build** — because marker's `>= 0.05` recheck
gate is meaningless against an uncalibrated probability. Keep the score, never the label: any
`kind="classifier"` signal whose declared domain is not `[0.0, 1.0]` is refused at registration, with
`surya/surya/ocr_error/schema.py`'s own comment as the error message.

**Missing evidence is three-valued.** "A rule reading a `None` key does not match" is a silent
two-valued collapse — it turns "the garble scorer is not installed" into "the page is clean", which
is `except Exception: return {}` wearing a policy file. A clause over an unavailable key is UNKNOWN;
UNKNOWN propagates by Kleene rules (`UNKNOWN and false = false`, `UNKNOWN or true = true`); a rule
whose predicate is UNKNOWN takes its **required** `on_unknown ∈ {skip, match, defer}`. The shipped
policy uses `match` (escalate) on FREE targets and `defer` on anything billable, so an unavailable
signal can never spend money and can never silently pass a page.

**Cost.** Drivers state resource units in a declared `CostCard` with one of four models
(`constant | linear_per_part | linear_per_byte | linear_per_token`) plus an optional single-key
scaling term; core computes `estimate(evidence) -> Spend`. A driver may not supply an estimator
function — a driver-supplied estimator is a lie the router cannot audit. Reservations use the
declared `tokens_out_p95_multiple`; commits use actuals; `omniweave driver check` fails a driver
whose declared multiple understates measurement by more than 25%, and `omniweave route lint
--estimates` fails the build when a driver's estimate is more than 2× off its 7-day measured median.
That reconciliation is the honesty mechanism for the whole cost model: the pragmatist's own
arithmetic found a 3.4× discrepancy between olmocr's published `<$200/1M pages` and a naive `gpu_ms`
estimate before a line of code existed. Retries are rungs (`REGEN`), strictly serial per
`(unit, part)`, charged to the same per-part budget — the structural fix for the 64× amplifier
(`olmocr/olmocr/pipeline.py:106` `MAX_TOKENS = 8000`, `:1221` `--max_page_retries` default 8,
`:343-350` remaining retries fired in parallel on an idle queue, `:1224` `--max_concurrent_requests`
default 1600, all verified). A retry count is not a cost bound because the cost of a retry is not
fixed.

**Long horizon is a `Sequence`, not a driver.** A rule may bind a contiguous run of parts to one
driver session (`then.sequence = { max_parts = 32 }`); the CostCard's `per_session` versus `per_part`
split prices the amortisation so the planner can *see* the 3× before choosing. One `route_decision`
row per part sharing a `sequence_id`, actual cost apportioned by token share, so per-part
attribution, failure isolation and the shrink guard keep working. Unlimited-OCR is not a shipped
driver (an unsigned 12,450,224-byte sglang wheel as install step 1, `trust_remote_code=True`,
`MAX_RETRIES=5 × REQUEST_TIMEOUT=1200` = 100 GPU-minutes per document), but its long-generation
constants are adopted as `Acceptor` configuration: `no_repeat_ngram_size = 35`, window 128 for a
single part and 1024 for a sequence.

**Quality.** `agree.decode_vs_page` is the mechanism nobody in the collection has: when a part
escalates you have already paid for two independent readings, so the normalised edit distance between
them is free and is a direct measurement of the cheap driver on that slice — at an 18.8% escalation
rate that is roughly 188,000 labelled points per million pages against roughly 5,000 from a 0.5%
audit, and it lands exactly on the population where the cheap driver is suspect. It is biased to the
escalated population, which is why the audit lane exists at all. The audit is deterministically
sampled (`blake2b(unit_uri‖part‖audit.salt) % 10000 < rate * 10000`, never RNG) and **symmetric**:
agreement above 0.98 across n ≥ 30 in a slice raises `wasted_escalation`, a cost bug of the same
severity as a quality bug. Driver self-report gates escalation and is excluded from the `Scoreboard`
by the view definition.

## Concrete shape

```
omniweave/route/
├── rung.py              Rung (closed ordered IntEnum), LANES registry, CostClass
├── evidence.py          Signal, SignalSpec, SignalRegistry, Evidence, DemandPlan
├── signals/             one module per group; each provider is an entry point
│   ├── unit.py          format, bytes, part_count, encrypted, corrupt, producer_family, trust_class
│   ├── decode.py        char_count, line_count, has_charspan, cid_ratio, replacement_ratio,
│   │                    stream_monotonicity
│   ├── geometry.py      overlap_line_frac                      (line bboxes only — NO layout model)
│   ├── ink.py           tiles, coverage, block.has_ink         (96-DPI raster, LOCAL_COMPUTE)
│   ├── garble.py        score — 7 CPU features + fitted coefficients + calibration check
│   ├── corpus.py        lang, spam_score, is_form, dup_of, layout_stability
│   ├── verify.py        repeat_ngram_max, finish_reason, token_saturation, parse_ok, nonempty,
│   │                    grounded_field_frac
│   └── agree.py         decode_vs_page                         (FREE* — requires two readings)
├── policy.py            RoutePolicy: six-layer merge, compile, digest
├── rules.py             Rule, Clause, Test, Kleene evaluation, subsumption for `route lint`
├── eval.py              evaluate(policy, evidence, narrowing) -> RouteDecision      [PURE]
├── admit.py             Admission gate: BudgetLedger reserve, on_exhausted ladder, Degradation
├── spend.py             Spend, PriceBook, CostCard, estimate()
├── driver.py            DriverSpec, Driver protocol, registry, licence gate, capability probe
├── acceptor.py          Acceptor registry, AcceptorVerdict
├── ledger.py            route_decision / route_evidence / route_spend / route_verdict writers
├── audit.py             deterministic sampling + agreement metrics (olmOCR-Bench normalize_text)
├── scoreboard.py        Slice keys, views, TTL-bounded auto-demote writer
├── tune.py              offline isotonic threshold fit -> a unified diff
├── licence_denylist.toml
└── policies/            balanced.toml (default) + fast / thorough / offline overlays
```

```python
# omniweave/route/rung.py
class Rung(IntEnum):
    GATE    = 0   # pre-flight, zero compute: limits, encryption, format, corpus filters
    DECODE  = 1   # deterministic decode of a text layer or office XML. Free.
    REPAIR  = 2   # surgical per-block repair on an otherwise-good part
    PAGE    = 3   # one full-part model call
    REGEN   = 4   # regeneration of the failed subset, on a temperature ladder
    DEGRADE = 5   # a different, cheaper strategy — ALWAYS marked degraded
    ENRICH  = 6   # cross-part / cross-block model pass, scoped by block type, non-fatal

# Escalation invariant: child.rung > parent.rung, ALWAYS. DEGRADE is a forward move on the
# ladder even though it runs a cheap driver — which is the whole point of separating
# "how far down the escalation we are" (Rung) from "what it costs" (Spend).

LANES: frozenset[str] = frozenset({"text", "table", "math", "fields", "caption"})  # open registry

class CostClass(StrEnum):
    FREE = "free"; LOCAL_COMPUTE = "local_compute"; BILLED_API = "billed_api"
```

```python
# omniweave/route/evidence.py
Scalar = str | int | float | bool | None

@dataclass(frozen=True, slots=True)
class SignalSpec:
    key: str                      # "<group>.<name>", both [a-z][a-z0-9_]*
    scope: Literal["unit", "part", "block", "doc"]
    kind: Literal["fact", "measure", "classifier", "count"]
    dtype: Literal["bool", "int", "float", "str"]
    domain: tuple[float, float] | frozenset[str] | None
    cost_class: CostClass
    est: "Spend"                      # cost of computing THIS signal, per scope instance
    provider: str                     # entry-point name
    version: str                      # provider semver; enters the read set
    requires: tuple[Rung, ...] = ()   # rungs whose output this signal needs
    nullable: bool = True             # uncomputable => None. NEVER a default value.
    # REGISTRATION REFUSES kind="classifier" whose domain is not (0.0, 1.0). Error text:
    #   surya/surya/ocr_error/schema.py: "P(bad) per text (softmax of the 'bad' class). Lets
    #   callers gate expensive follow-up work on confidence instead of just the argmax label."

class Evidence:
    """Flat namespaced scalar record for ONE (unit, part). `read()` is the ONLY accessor and it
    appends to the read log. No __getitem__, no public mapping — a third party must be able to add
    `garble.acme_blur` without a core release, and the policy must be able to name a key core has
    never heard of."""
    __slots__ = ("_v", "_read", "_scope")
    def read(self, key: str) -> Scalar: ...
    def read_set(self) -> tuple[tuple[str, str, Scalar], ...]:   # (key, provider_version, value)
    def read_set_digest(self) -> str:                            # sha256_canonical, allow_nan=False
```

### The day-one signal registry — what exists WITHOUT Datalab weights

| key | scope | kind | cost | day 1 | source / note |
|---|---|---|---|---|---|
| `unit.format` `unit.bytes` `unit.part_count` `unit.encrypted` `unit.corrupt` | unit | fact | FREE | yes | content-first detection; mime→format is one-to-many |
| `unit.producer_family` | unit | fact | FREE | yes | PDF `/Producer` bucketed to ~30 families — the strongest cheap layout-pathology predictor and the natural slice axis |
| `unit.needs_ocr_parts` | unit | count | FREE | yes | `anydoc/src/error.rs` `NeedsOcr{pages, page_count}` — an error used as routing data; over-reports by design |
| `unit.trust_class` | unit | fact | FREE | yes | `internal \| untrusted_external`, from the connector. Raises `audit.rate`; the only bound on trusting that a text layer matches its pixels |
| `unit.schema_requested` | unit | fact | FREE | yes | the caller supplied a JSON Schema ⇒ `fields` lane |
| `corpus.is_form` `corpus.lang` `corpus.spam_score` `corpus.dup_of` | unit | fact/classifier | FREE | yes | `olmocr/olmocr/filter/filter.py` (12-word SEO lexicon, threshold 0.004, `get_form_text_fields()`) — **as signals, ON by default, never as exclusions** |
| `decode.char_count` `decode.line_count` `decode.has_charspan` | part | count | FREE | yes | pdfium / office XML |
| `decode.cid_ratio` | part | measure | FREE | yes | glyph runs whose font has no or partial `ToUnicode` CMap, or is CID-keyed with no mapping. **omniweave implements this over pdfium font data.** Precedent, not a source: `anydoc/src/formats/pdf.rs:26-29` receives a *document-level boolean* `has_encoding_issues` from the external `pdf-inspector` crate and only `log::warn!`s it |
| `decode.replacement_ratio` | part | measure | FREE | yes | U+FFFD, PUA code points, stray control characters |
| `decode.stream_monotonicity` | part | measure | FREE | yes | character-stream order versus geometric order |
| `geometry.overlap_line_frac` | part | measure | FREE | yes | marker's signal 4, verbatim: page bbox `.expand(5,5)`, `(intersection_matrix > 0.1).sum(axis=1) > 2`, over `len(lines)`. **Needs no layout model** |
| `garble.score` | part | classifier | FREE | yes | the fitted logistic regression. Calibration is a CI gate |
| `ink.tiles` `ink.coverage` | part | count/measure | LOCAL_COMPUTE | yes | 96-DPI raster, 8-px tiles. Replaces `layout_coverage` |
| `block.type` `block.char_count` `block.area_frac` `block.sibling_containment` `block.has_ink` | block | fact/measure | FREE / LOCAL | partial | complete on office formats; on PDF, `block.type` needs a layout detector |
| `layout.class_hist` | part | count | LOCAL_COMPUTE | **no** | **absent until a licence-clean layout detector lands.** Every affected decision records `cause="layout_unavailable"` |
| `render.short_edge_px` | part | measure | FREE | yes | lift's 692-px floor; a VLM sees pixels, not points |
| `verify.repeat_ngram_max` `verify.finish_reason` `verify.token_saturation` `verify.parse_ok` `verify.nonempty` | part | fact/measure | FREE | yes | `olmocr/olmocr/repeatdetect.py` `RepeatDetector.ngram_repeats`; `surya/surya/recognition/__init__.py:88` `_detect_repeat_loop` |
| `verify.grounded_field_frac` | unit | measure | FREE | yes | the `fields` lane cross-check (below) |
| `agree.decode_vs_page` | part | measure | FREE* | yes | `requires = (DECODE, PAGE)`; the free quality channel |
| `doc.escalated_part_frac` | doc | measure | FREE | yes | de-escalation to a `Sequence` |
| `budget.exhausted` | part/unit | fact | FREE | yes | **written by `admit()`**, read by the `DEGRADE` rules. This is how budget stays out of `evaluate()` |
| `trigger.kind` | unit | fact | FREE | yes | `cli \| hook \| upstream \| watch` — a watcher may never auto-run `BILLED_API` |
| `request.*` | unit | Narrowing | FREE | yes | typed; cannot widen |

### The policy — `omniweave/route/policies/balanced.toml` (abridged; the real file is ~300 lines)

```toml
policy_name    = "builtin:balanced"
policy_version = 1
schema         = "omniweave.route/1"

[slice]
by         = ["unit.format", "unit.producer_family", "decode.has_text_layer", "corpus.lang"]
max_slices = 512                     # route lint checks this against declared domains

[budget.per_part]                    # the runaway-page guard. First exhausted dimension wins.
micros     = 6_000                   # $0.006 — about three hosted olmocr attempts at max output
tokens_out = 24_000                  # 3 x olmocr MAX_TOKENS=8000, against its default of 8 retries
calls      = 3
gpu_ms     = 12_000

[budget.per_unit]                    # base + per_part x part_count, clamped. NO expressions.
micros_base = 4_000 ; micros_per_part = 800 ; micros_max = 250_000
wall_ms      = 600_000
bytes_egress = 0                     # 0 = no hosted escalation without a site-layer Grant
on_exhausted = ["spill_to_free", "partial", "defer"]

[audit]
rate = 0.005 ; salt = "2026-09-a" ; reference = "page.olmocr"
min_audit_n = 30 ; regress_at = 0.08 ; release_at = 0.048   # hysteresis = regress_at * 0.6
auto_demote = true ; demote_ttl_days = 30
untrusted_external_rate = 0.05       # unit.trust_class raises the sample

[calibration]
eval_set_id  = ""                    # unset => every run manifest reports calibration:bootstrap
max_age_days = 30

[render.structure] short_edge_min_px =  692 ; area_max_px = 6_291_456 ; patch_snap = 28 ; binarize = false
[render.glyph]     short_edge_min_px = 1384 ; area_max_px = 6_291_456 ; patch_snap = 28 ; binarize = false
# binarize = false, ALWAYS. Ollama-OCR's 72-DPI-then-Otsu destroys the antialiasing a VLM trained on.

[thresholds]                         # the learnable numbers. tune.py fits these per slice.
garble_escalate         = 0.50       # marker's page verdict, RECALIBRATED to OUR scorer
garble_recheck          = 0.05       # marker's per-block recheck gate
ink_coverage_min        = 0.25       # marker's layout_coverage_threshold, ink-based
overlap_max             = 0.50       # marker's overlap_line_fraction_threshold
blank_page_tiles        = 4          # marker's single-large-text-block blank-page escape hatch
promote_frac            = 0.0        # balanced: ANY flagged block promotes the part (fast: 0.5)
empty_block_area_min    = 0.01       # >= 1% of part area
empty_block_containment = 0.75       # < 75% contained in a text-bearing sibling
garble_min_chars        = 50         # short labels cannot be judged
grounded_field_min      = 0.60

# ---------------- GATE ----------------
[[rule]]
id = "gate.encrypted" ; rung = "GATE"
when = { "unit.encrypted" = true }
then = { outcome = "refuse", failure_class = "PASSWORD_PROTECTED" }

[[rule]]
id = "gate.watcher-may-not-bill" ; rung = "GATE"
comment = "graphify watch.py: FREE runs now, LOCAL_COMPUTE within headroom, BILLED_API never auto-runs."
when = { "trigger.kind" = "watch" }
then = { max_cost_class = "local_compute" }

[[rule]]
id = "gate.form-is-a-signal-not-an-exclusion" ; rung = "GATE"
comment = """olmocr's PdfFilter drops every form and every non-English document by default with a
logger.info only, behind --apply_filter (action="store_true", off). Ours runs always, its verdict is
a signal, and any rule mapping a verdict to skip records {reason, key, threshold} so it is appealable."""
when = { "corpus.is_form" = true }
then = { lane = "fields", render = "structure" }

# ---------------- DECODE ----------------
[[rule]]
id = "decode.office-native" ; rung = "DECODE"
comment = """Native formats have a canonical reading order; never re-infer it and never funnel them
through a PDF renderer. marker subclasses PdfProvider for DOCX/PPTX/XLSX/EPUB/HTML and renders to a
temp A4 PDF, destroying speaker notes, comments, tracked changes, OMML math, numbering restarts,
footnote linkage and true logical order BEFORE parsing starts. terminal = true forbids escalation."""
when = { "unit.format" = { in = ["docx","pptx","xlsx","epub","html","md","csv","txt"] } }
then = { driver = "decode.anydoc", lane = "text", terminal = true }

[[rule]]
id = "decode.pdf-text-layer" ; rung = "DECODE"
when = { "unit.format" = "pdf", "decode.char_count" = { gt = 0 } }
then = { driver = "decode.pdftext", lane = "text" }

[[rule]]
id = "decode.blank-part-escape" ; rung = "DECODE"
comment = "marker line.py:341-345 — the model sometimes reports one text block on a blank page."
when = { "ink.tiles" = { lte = "@thresholds.blank_page_tiles" } }
then = { outcome = "ok", terminal = true, reason = "blank-part" }

[[rule]]
id = "decode.part-text-unusable" ; rung = "DECODE"
comment = """marker/marker/builders/line.py:225-235 — four signals ANDed there, so ANY failing here.
Signal 2 (surya OCRErrorPredictor) and signal 3 (layout coverage, needs the layout model) are both
Datalab-licensed (MODEL_LICENSE md5 e1f69b64dee2f1641a9b1ab12adf24d6); garble.score and ink.coverage
are the licence-free replacements. THRESHOLDS ARE OURS, NOT MARKER'S — its numbers were calibrated
against its classifier's score distribution."""
on_unknown = "match"                 # REQUIRED: this rule reads nullable keys. Target is cheap.
when.any_of = [
  { "decode.line_count"          = { eq  = 0 } },
  { "garble.score"               = { gte = "@thresholds.garble_escalate" } },
  { "ink.coverage"               = { lt  = "@thresholds.ink_coverage_min" } },
  { "geometry.overlap_line_frac" = { gt  = "@thresholds.overlap_max" } },
]
then = { escalate_to = "PAGE", driver = "page.olmocr", render = "glyph", cause_from = "when" }

[[rule]]
id = "decode.skip-block-recheck-on-clean-parts" ; rung = "DECODE"
comment = "marker's 0.05 gate: confidently-clean parts skip the per-block recheck entirely."
on_unknown = "skip"
when = { "garble.score" = { lt = "@thresholds.garble_recheck" } }
then = { skip_rungs = ["REPAIR"] }

# ---------------- REPAIR ----------------
[[rule]]
id = "repair.never-escalate-furniture" ; rung = "REPAIR"
comment = """marker/marker/builders/line.py:118-133 block_ocr_skip_types, rationale verbatim in intent:
page headers/footers are dropped from output by default so OCRing them wastes a VLM call, and a single
flagged footer forces an otherwise-clean document to spawn the inference server. Tables, equations,
figures and forms have their own lanes."""
when = { "block.type" = { in = ["PageHeader","PageFooter","Picture","Figure","Diagram","Table",
                                "Form","TableOfContents","Equation","ChemicalBlock"] } }
then = { outcome = "not_eligible" }

[[rule]]
id = "repair.promote-to-part" ; rung = "REPAIR"
comment = "One full-part request is ~7x cheaper than N block requests on llama.cpp and more accurate."
when = { "block.flagged_frac" = { gt = "@thresholds.promote_frac" } }
then = { escalate_to = "PAGE", driver = "page.olmocr", render = "glyph", reason = "promotion" }

# ---------------- PAGE / de-escalation ----------------
[[rule]]
id = "page.collapse-to-sequence" ; rung = "PAGE"
comment = "If most parts escalated, per-part routing has lost: pay the per-session cost once."
when = { "doc.escalated_part_frac" = { gt = 0.80 }, "unit.part_count" = { lte = 64 } }
then = { driver = "page.olmocr", sequence = { max_parts = 64 }, reason = "de-escalation" }

# ---------------- REGEN / DEGRADE ----------------
[[rule]]
id = "regen.output-invalid" ; rung = "PAGE"
comment = "Acceptor failures. repetition_penalty stays 1.0 — real documents repeat."
when.any_of = [
  { "verify.repeat_ngram_max" = { gte = 12 } },
  { "verify.finish_reason"    = { ne  = "stop" } },
  { "verify.token_saturation" = { gte = 0.98 } },
  { "verify.parse_ok"         = false },
  { "verify.nonempty"         = false },
]
then = { escalate_to = "REGEN", cause_from = "when" }

[[rule]]
id = "degrade.budget-exhausted" ; rung = "REGEN"
comment = "budget.exhausted is written by admit(), so evaluate() never reads the ledger."
when = { "budget.exhausted" = { exists = true } }
then = { escalate_to = "DEGRADE", driver = "decode.pdftext",
         outcome = "ok_partial", reason = "budget-exhausted" }

[[rule]]
id = "degrade.marked-fallback" ; rung = "REGEN"
comment = "Unlimited-OCR/infer.py:229 writes {\"text\": \"\"} for a part that failed 5 retries. Never."
when = { "verify.attempts_exhausted" = true }
then = { escalate_to = "DEGRADE", driver = "decode.pdftext",
         outcome = "ok_partial", reason = "regen-exhausted" }
```

### The rule grammar — closed, total, comparison-only

```
rule    := { id, rung, lane?, when, then, comment?, on_unknown?, expires?, canary? }
when    := clause | {any_of:[clause,...]} | {all_of:[clause,...]} | {none_of:[clause,...]}   # 1 level
clause  := { <evidence_key>: test, ... }                       # implicit AND across keys
test    := scalar                                              # equality shorthand
         | { eq|ne|lt|lte|gt|gte : number | string | "@thresholds.<name>" }
         | { in|not_in : [scalar, ...] }
         | { exists : bool }
then    := { driver?, driver_by?, lane?, escalate_to?, skip_rungs?, sequence?, outcome?,
             failure_class?, terminal?, cause_from?, reason?, render?, max_cost_class?,
             flag_blocks? }
outcome := "ok" | "ok_partial" | "refuse" | "skip" | "not_eligible"
on_unknown := "skip" | "match" | "defer"        # REQUIRED iff the rule reads a nullable key

NO arithmetic, NO indexing, NO user functions, NO dotted import paths, NO eval.
A rule that needs a derived quantity gets a Signal, not a grammar feature. Verified sufficient:
none of the eight ladders in mine-parse.md §B2 needs arithmetic over more than one evidence key.
`@thresholds.<name>` is a compile-time substitution from [thresholds], NOT an expression — it is
what makes a threshold learnable by one-dimensional isotonic regression over the decision log.
`driver_by = "cheapest_admissible"` is the OPT-IN estimator-driven choice; the default is the
named driver, because an unreconciled estimator is a cost bug with a proof.
```

### Types

```python
# omniweave/route/spend.py
@dataclass(frozen=True, slots=True)
class Spend:
    wall_ms: int = 0; cpu_ms: int = 0; gpu_ms: int = 0
    tokens_in: int = 0; tokens_out: int = 0; calls: int = 0; bytes_egress: int = 0
    provider: str = ""                        # "" == local
    def __add__(self, other: "Spend") -> "Spend": ...
    def micros(self, book: "PriceBook") -> int: ...      # the ONLY place money appears

@dataclass(frozen=True, slots=True)
class PriceBook:                  # .omniweave/pricebook.toml — OPERATOR-owned, versioned, digested
    version: int; currency: str; effective_from: date
    local: Mapping[str, float]    # cpu_ms_micros, gpu_ms_micros, wall_ms_micros (0.0 = budgeted, unpriced)
    provider: Mapping[str, "ProviderPrice"]
    def digest(self) -> str: ...
# Drivers NEVER state dollars. A contributor on a rented A100 cannot know your GPU-hour cost, and if
# they guess, every estimate in your fleet is wrong in a way you cannot audit.

@dataclass(frozen=True, slots=True)
class CostCard:                   # declared in driver.toml; core computes the estimate
    model: Literal["constant", "linear_per_part", "linear_per_byte", "linear_per_token"]
    per_part: Spend
    per_session: Spend = Spend()  # model load / warm-up, amortised over a Sequence
    scaling: "ScalingTerm | None" = None   # ONE evidence key, one exponent, one reference value
    tokens_out_p95_multiple: float = 1.0   # reservations use p95; driver check fails if understated >25%
# A driver may NOT supply an estimator function: a driver-supplied estimator is a driver-supplied lie.
```

```python
# omniweave/route/driver.py — the entire required third-party surface
class Driver(Protocol):
    NAME: ClassVar[str]
    RUNGS: ClassVar[frozenset[Rung]]
    LANES: ClassVar[frozenset[str]]

    def probe(self) -> ProbeResult:
        """The SMALLEST REAL operation, not an import check. A tesseract without the language
        pack, a CUDA torch that fails on first kernel launch, a pdfium that cannot open an
        encrypted PDF, and an Ollama client with no model pulled all import fine."""

    def run(self, unit: UnitRef, parts: Sequence[int], ctx: RunContext) -> DriverResult:
        """`parts` is a list because of Sequence bindings. Never reads os.environ, getcwd or a
        clock; everything arrives through ctx."""

@dataclass(frozen=True, slots=True)
class DriverSpec:                          # parsed from driver.toml
    name: str; version: str
    rungs: frozenset[Rung]; lanes: frozenset[str]; formats: frozenset[str]
    cost_class: CostClass; egress: bool
    declares: Capabilities                 # mine-parse.md E11 vocabulary, VERBATIM
    forfeits: frozenset[str]               # {"blocks","spatial","charspan","citation","round_trip"}
    cost: CostCard
    code_spdx: str; weights_spdx: str; weights_repo: str
    weights_revision: str                  # absent or "main" => REFUSED TO LOAD
    weights_licence_md5: str               # checked against licence_denylist.toml, seeded with
                                           # e1f69b64dee2f1641a9b1ab12adf24d6 (marker/surya/lift)
```

```python
# omniweave/route/eval.py — PURE. No clock, no RNG, no env, no I/O, no RunContext parameter.
def evaluate(policy: RoutePolicy, ev: Evidence, nar: Narrowing) -> RouteDecision: ...

# omniweave/route/admit.py — impure; writes `budget.exhausted` back into Evidence.
def admit(d: RouteDecision, ledger: BudgetLedger) -> Admitted | Deferred | Degraded: ...

@dataclass(frozen=True, slots=True)
class Narrowing:            # the `request` layer. HAS NO budget / egress / licence FIELD.
    lane: str | None = None
    max_rung: Rung | None = None
    prefer_capability: str | None = None
    deadline_ms: int | None = None
    schema: Mapping | None = None

@dataclass(frozen=True, slots=True)
class Degradation:
    kind: Literal["budget", "signal_unavailable", "driver_unavailable", "acceptor_exhausted",
                  "auto_demote", "pin", "grant_missing", "policy_pruned", "calibration_stale"]
    unit_dim: str | None; spent: int; limit: int
    rung_reached: Rung; wanted_driver: str | None; parts_affected: tuple[int, ...]
    message: str            # MUST name the knob that would raise the limit, anydoc-style:
    # "per_unit.micros exhausted at 20000/20000 after part 63/188; raise [budget.per_unit].micros
    #  or set on_exhausted=['defer'] in .omniweave/route.toml"
```

### Override stack — six layers, higher PREPENDS (first match wins ⇒ higher wins)

| layer | location | owner | may set |
|---|---|---|---|
| `builtin` | in-package, immutable | omniweave | everything |
| `site` | `/etc/omniweave/route.d/*.toml`, `%PROGRAMDATA%\omniweave\route.d\*.toml` | platform team | everything, including `Grant`s |
| `project` | `.omniweave/route.toml` (+ `route.d/`) | the repo | rules, thresholds, budgets ≤ site |
| `profile` | named overlay, `--profile fast\|balanced\|thorough\|offline` | the repo | threshold and rule overlays |
| `request` | `route_hints` on API / MCP / CLI | the agent | a `Narrowing`, nothing else |
| `pin` | `.omniweave/pins.toml` | ops | one `(unit, part?, lane) -> driver` + `reason` + `expires` |

A pin is **honoured or refused**, never silently ignored: `PinRejected{driver, reason}` is a typed
return, not an `Optional`. Widening egress requires a site-layer `Grant` with a required
(deliberately unvalidated) `dpa_ref` that is printed in the run manifest of every document that
egressed. No `--force`; named overrides only: `--allow-egress <grant-id>`, `--allow-rebill`,
`--accept-partial`, `--ignore-evidence-cache`, `--max-rung <RUNG>`.

### DDL

```sql
-- omniweave/route/schema.sql   (SQLite; identical DDL on Postgres for T3)
PRAGMA busy_timeout = 5000;   -- FIRST: journal_mode before busy_timeout crashes a contended open
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE route_decision (
    decision_id      TEXT PRIMARY KEY,         -- 'dec_' || sha256_canonical(identity)[:24]
    content_digest   TEXT NOT NULL,            -- keyed on CONTENT: identical bytes never re-bill
    unit_part        TEXT NOT NULL DEFAULT '', -- '' folds NULL (NULLs are distinct in UNIQUE)
    lane             TEXT NOT NULL,
    rung             INTEGER NOT NULL,
    driver           TEXT NOT NULL,
    policy_digest    TEXT NOT NULL,
    pricebook_digest TEXT NOT NULL,
    narrowing_digest TEXT NOT NULL,
    read_set_digest  TEXT NOT NULL,            -- over the READ SET ONLY (key, provider_version, value)
    evidence_digest  TEXT NOT NULL REFERENCES route_evidence(evidence_digest),
    rule_id          TEXT NOT NULL,
    rule_origin      TEXT NOT NULL,            -- 'project:.omniweave/route.toml:41'
    cause            TEXT,                     -- 'garble.score=0.71>=0.50'  (from cause_from)
    slice_key        TEXT NOT NULL,
    flagged_blocks   TEXT,                     -- JSON array of block ids (REPAIR)
    sequence_id      TEXT,
    parent_decision_id TEXT REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    est_spend        TEXT NOT NULL,            -- canonical JSON of Spend
    est_micros       INTEGER NOT NULL,
    reserved_micros  INTEGER NOT NULL,         -- the p95 ceiling, not the mean
    admission        TEXT NOT NULL,            -- admitted | deferred | degraded
    audit_selected   INTEGER NOT NULL DEFAULT 0,   -- DERIVED, never random
    pinned           INTEGER NOT NULL DEFAULT 0,
    grant_id         TEXT,                     -- non-null iff bytes_egress > 0
    degraded         INTEGER NOT NULL DEFAULT 0,
    degradations     TEXT NOT NULL DEFAULT '[]',
    generation       INTEGER NOT NULL,         -- integer, never a clock
    decided_at       INTEGER NOT NULL          -- wall ms, for humans and retention only
);
CREATE UNIQUE INDEX route_decision_identity ON route_decision(
    content_digest, unit_part, lane, rung,
    policy_digest, pricebook_digest, narrowing_digest, read_set_digest);
CREATE INDEX route_decision_slice  ON route_decision(slice_key, rule_id, driver);
CREATE INDEX route_decision_audit  ON route_decision(decided_at) WHERE audit_selected = 1;
CREATE INDEX route_decision_parent ON route_decision(parent_decision_id);

-- Which URIs were served by which decision. Survives `work` row deletion, so cost stays
-- attributable per corpus after the queue drains, and a re-ingest of identical bytes is free.
CREATE TABLE route_unit_decision (
    unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', lane TEXT NOT NULL,
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    first_seen_at INTEGER NOT NULL,
    PRIMARY KEY (unit_uri, unit_part, lane, decision_id)
) WITHOUT ROWID;

-- Evidence blobs are refcounted and content-addressed so they age out independently.
CREATE TABLE route_evidence (
    evidence_digest TEXT PRIMARY KEY,
    payload BLOB NOT NULL,                     -- zstd(canonical JSON of the read set)
    first_seen_at INTEGER NOT NULL, refcount INTEGER NOT NULL DEFAULT 1
);

-- THE cache that matters. The decision itself is microseconds; the 96-DPI raster is not.
-- FREE tier => old signal_version namespaces are SWEPT. Per-signal, not per-suite: one signal's
-- version bump must not invalidate the other thirteen.
CREATE TABLE route_signal (
    content_digest TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '',
    signal_key TEXT NOT NULL, signal_version TEXT NOT NULL,
    value BLOB, unavailable_reason TEXT, compute_ms INTEGER NOT NULL, computed_at INTEGER NOT NULL,
    PRIMARY KEY (content_digest, unit_part, signal_key, signal_version)
) WITHOUT ROWID;

CREATE TABLE route_spend (
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,                  -- 1-based; REGEN increments
    provider TEXT NOT NULL DEFAULT '',
    wall_ms INTEGER NOT NULL DEFAULT 0, cpu_ms INTEGER NOT NULL DEFAULT 0,
    gpu_ms INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0,
    bytes_egress INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
    was_cache_hit INTEGER NOT NULL DEFAULT 0,
    would_have_been_micros INTEGER NOT NULL DEFAULT 0,   -- metrics replayed on a hit
    outcome TEXT NOT NULL,                     -- mine-runtime §7.1.2 Outcome
    PRIMARY KEY (decision_id, attempt)
);

CREATE TABLE route_verdict (
    verdict_id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('self','agree','audit','feedback')),
    metric TEXT NOT NULL,                      -- 'norm_edit_agreement'|'grounded_frac'|'thumb'
    agreement REAL, polarity INTEGER, ref_driver TEXT, detail TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX route_verdict_decision ON route_verdict(decision_id);

CREATE TABLE route_pin (
    unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', lane TEXT NOT NULL DEFAULT 'text',
    driver TEXT NOT NULL, reason TEXT NOT NULL, created_by TEXT NOT NULL,
    expires_at INTEGER,                        -- CLI default: now + 90d
    PRIMARY KEY (unit_uri, unit_part, lane)
);

-- No driver runs unrouted.
ALTER TABLE work ADD COLUMN decision_id TEXT NOT NULL REFERENCES route_decision(decision_id);

CREATE VIEW route_scoreboard AS
SELECT d.slice_key, d.rule_id, d.driver,
       COUNT(*)                                                  AS decisions_n,
       SUM(v.source='audit')                                     AS audited_n,
       AVG(CASE WHEN v.source='audit' THEN 1.0-v.agreement END)  AS divergence,
       AVG(CASE WHEN v.source='agree' THEN 1.0-v.agreement END)  AS escalation_divergence,
       SUM(v.source='feedback' AND v.polarity<0)                 AS complaints,
       SUM(s.micros)                                             AS micros,
       CASE WHEN SUM(v.source='audit') < :min_audit_n THEN 'UNKNOWN'
            WHEN AVG(CASE WHEN v.source='audit' THEN 1.0-v.agreement END) > :regress_at
                 THEN 'REGRESSED'
            ELSE 'OK' END                                        AS state
FROM route_decision d
LEFT JOIN route_verdict v ON v.decision_id = d.decision_id
LEFT JOIN route_spend   s ON s.decision_id = d.decision_id
WHERE (v.source IS NULL OR v.source IN ('agree','audit','feedback'))  -- NEVER 'self'
  AND d.pinned = 0
GROUP BY d.slice_key, d.rule_id, d.driver;
-- UNKNOWN is the zero value. On day one an operator sees a wall of UNKNOWN, which is the truth.
```

Retention: evidence blobs 30 days; decision rows 400 days (year-over-year comparison). Rows that are
`audit_selected`, `pinned`, `degraded`, or in a `REGRESSED` slice are never aged out. About 240 B per
decision plus ~600 B of deduplicated evidence plus ~120 B of spend gives **~1 GB per million parts**,
falling to ~360 MB after the sweep.

### The `fields` lane (lift's shortcut) — a lane with a mandatory free cross-check

`_index/framework-blueprint.md` says "tier S — lift, skip everything else." **Overturned.** lift's own
adversarial benchmark is 90.2% per field and **20.9% full-document** (`lift/README.md:75`), and the
open weights ship no verification layer. The `fields` lane therefore always also runs `DECODE` (it is
free) and emits, per extracted field,
`FieldGrounding{path, value, grounded, part, charspan}`; `verify.grounded_field_frac` below
`@thresholds.grounded_field_min` (excluding `number` and `boolean` leaves, where verbatim matching is
meaningless) escalates to a second extraction at a higher render profile or degrades to `ok_partial`
with the ungrounded fields flagged for review. Non-negotiables carried from the source:
`make_properties_nullable` before constrained decoding (`lift/lift/model/vllm.py:28-45` — without it
the grammar forces the model to invent values), explicit `minItems` on every array (surya disabled
guided table-rec entirely because an under-specified grammar lets greedy decoding legally close an
array after one element), and `repetition_penalty = 1.0`. A driver declaring
`forfeits = ["citation", ...]` makes the serve layer **refuse** a citation request against that
result rather than fabricate one. Schema-compile failure is `Degradation(kind="driver_unavailable")`,
never lift's `print(f"Schema failed validation ... skipping guardrails...")`
(`lift/lift/model/vllm.py:97-98`).

### CLI

```
omniweave route explain  <uri> [--part 41] [--profile fast]  # evidence, rules tested, cause, estimate
omniweave route replay   <decision_id>                       # IDENTICAL(0) | DIVERGED(3) | REPLAY_DRIFT(4)
omniweave route simulate --policy candidate.toml --since 30d [--slice K=V] [--gate]
omniweave route lint     [--calibration] [--estimates]       # CI gate: unreachable, cold, scope, drift
omniweave route scoreboard [--slice K=V] [--window 30d]
omniweave route propose  --since 30d                         # a unified diff + counterfactual deltas
omniweave route promote  <proposal-id>                       # requires a clean tree; a human commits
omniweave route audit    --since 7d
omniweave driver scaffold <name> --rungs PAGE --lanes text
omniweave driver check   ./drivers/<name>                    # capabilities, cost card, determinism,
                                                             # network isolation, licence, resources
omniweave parse --dry-run <uri>                              # plan + estimate, spends nothing
```

### Invariants (R1–R14)

| # | Invariant | Enforced by |
|---|---|---|
| R1 | `evaluate()` is pure: no clock, no RNG, no env, no I/O, no import of a caller-supplied name. | The signature takes no `RunContext`; semgrep bans `time.`, `random.`, `os.environ`, `importlib`, `open(` in `route/eval.py`; a property test evaluates 10k fixtures twice in shuffled order and asserts identity. |
| R2 | All sampling is `blake2b(unit_uri‖part‖salt) % 10000 < rate * 10000`. | Cross-process determinism test; semgrep ban on `random`/`secrets` under `route/`. |
| R3 | The decision records the **read set** with provider versions; `read_set_digest` covers the read set only. | `Evidence.read()` is the only accessor and appends to the read log; `Evidence` exposes no mapping and no `__getitem__`. |
| R4 | No evidence key is computed unless a reachable rule reads it, and keys compute in ascending `cost_class`. | The compiler emits a per-rung demand plan; a test asserts a clean born-digital PDF computes **zero** `LOCAL_COMPUTE` signals and spawns no inference server. |
| R5 | A classifier signal exposes a probability, not a label. | `SignalSpec` registration rejects `kind="classifier"` whose declared domain is not `(0.0, 1.0)`. |
| R6 | A probabilistic signal is calibrated. | `route lint --calibration`: ECE ≤ 0.05, Brier ≤ 0.08 on a held-out set. A regression fails the build. |
| R7 | A clause over a missing key is UNKNOWN and the rule takes its declared `on_unknown`. | `on_unknown` is a **required** field on any rule reading a nullable key; `route lint` errors otherwise. |
| R8 | Escalation is monotone: `child.rung > parent.rung`. | A SQL CHECK on the parent join; the compiler rejects a backward `escalate_to`. |
| R9 | Budget never changes which rung is chosen. | `evaluate()` has no ledger parameter; exhaustion enters as the evidence key `budget.exhausted`, written by `admit()`. |
| R10 | No billable rung is entered without a reservation; a denial is `DEFERRED_BUDGET`, not a failure. | `with_budget` inside `with_cache` and outside `with_retries`; a test asserts a denied reservation leaves the `work` row claimable and `cost_micros` unchanged. |
| R11 | Retries are serial per `(unit, part)` and share the per-part budget. | A semaphore of 1 across a `REGEN` chain; a fault-injection test asserts N sequential provider calls, not N concurrent. |
| R12 | Driver self-report never enters the `Scoreboard`. | The view filters `source IN ('agree','audit','feedback')`; `source='self'` rows are stored and excluded. |
| R13 | `auto_demote` may only move a slice toward the more expensive driver, with a TTL and hysteresis. | The demotion writer accepts only a `then.driver` of strictly greater `CostCard` rank; a test attempts a promotion and asserts refusal. |
| R14 | A driver whose `weights_revision` is absent or `"main"`, or whose `weights_licence_md5` is denied, fails to load with a named error. | Loader check plus in-tree `licence_denylist.toml`; CI asserts a synthetic `revision="main"` driver is refused. `grep -rn "revision=" marker/ surya/ lift/` returns zero hits, so those weights were never reproducible even where licensed. |

### Build order

1. **Weeks 1–3.** `Rung`/`Lane`, `Evidence` plus the registry and the day-one FREE/LOCAL signals (no
   fitted garble model yet — ship `decode.cid_ratio` and `decode.replacement_ratio` thresholds
   instead), the TOML loader, the rule compiler and `evaluate()`, the `route_decision` write, and
   `route explain`. ~1,400 LoC. **Deliverable a user runs: `omniweave parse` on a mixed corpus where
   a clean digital PDF never starts a GPU, and `route explain` prints why, with a line number.**
2. **Weeks 4–5.** `Spend`/`PriceBook`/`CostCard`, `admit()` plus budgets, `Degradation` and
   `on_exhausted`, `--dry-run`, the `driver.toml` loader and the licence denylist. ~900 LoC.
3. **Weeks 6–7.** `Acceptor`s, `REGEN`/`DEGRADE`, `route_verdict` (`self` and `agree`),
   `route simulate`, `route lint` (unreachability, cold rules, estimate drift). ~900 LoC.
4. **Weeks 8–10.** The audit lane, `Scoreboard` and slices, `auto_demote`, `route propose`; the
   `garble.score` fit (about two person-days labelling ~2,000 pages) and its calibration gate; and
   `omniweave driver check`. ~1,400 LoC.

About **4,600 LoC and ~10 engineer-weeks for one senior engineer**, plus a standing ~0.2 FTE owning
the default policy, the pricebook and the eval set. Zero new third-party runtime dependencies:
`tomllib`, `sqlite3` and `blake2b` are stdlib, and the Levenshtein behind `agree.decode_vs_page` is a
50-line DP called once per escalation. **No torch in the routing path** — an L5 layer must never make
a torch install a prerequisite for reading a DOCX.

## Rationale

Three things decided this ruling, and each of them beat a prettier alternative.

**First, the licence veto is not a footnote; it is the specification.** Marker's ladder is the only
working cost router in the collection, and two of its four page signals depend on Datalab weights
omniweave cannot use at $0 revenue. The pragmatist is the only architect who confronted that and
shipped replacements. The systems architect named the veto and then wrote `text.plausibility` as an
"honest, weaker stand-in" with the real scorer deferred; the ecosystem architect named it in §9 and
then shipped a default policy whose headline escalation rule gates on `probe.ocr_error_p_bad` (surya's
classifier) and `check.layout_coverage` (marker geometry over layout-model blocks) — two of four
clauses inoperable on day one, combined with a null-does-not-match semantics that turns the hole into
silent under-escalation. A default policy that cannot fire is worse than no default policy.
`ink.coverage` and a fitted, calibration-gated `garble.score` are therefore the load-bearing
engineering here. `geometry.overlap_line_frac` survives intact because marker's `check_line_overlaps`
reads only line bboxes and the page polygon — verified in source — so one of the four signals was
never at risk, which nobody noticed.

**Second, the policy must be linted and learned, and that decides the grammar.** The systems
architect's RPL is a hand-rolled language with a hand-rolled typer, justified by compile-time checks
(R4: no signal costs more than the rung it gates) that are only decidable against `cost_class`
ordinals — because the same proposal makes `estimate` dynamic. A closed comparison grammar buys two
things an expression language forfeits outright: interval-box subsumption, so `route lint` can prove
rule 90 is shadowed by rule 3; and one-dimensional isotonic threshold fitting, which is well-posed
only when a threshold is a bare number rather than a term inside `ratio(a,b)*3+c`. The ecosystem
architect's audit — that none of the eight ladders in `mine-parse.md` §B2 needs arithmetic over more
than one key — is checkable and correct, and the `@thresholds.<name>` indirection makes every tunable
number simultaneously readable in the rule, diffable in git and fittable by the tuner. But the
ecosystem's two-valued missing-evidence semantics is a silent-correctness bug of exactly the shape the
digest names, so the systems architect's Kleene semantics with a required `on_unknown` is taken whole.
That is the one place the systems purist was straightforwardly right and both others were wrong.

**Third, budget must not be an input to the decision.** All three proposals thread budget headroom
into the routing decision and then pay for it: the systems proposal has to store a per-decision
headroom snapshot and concede that whole-run replay is exact only under `--serial`. Factoring
`evaluate()` (pure over policy, evidence and narrowing) from `admit()` (impure, reserves, and writes
`budget.exhausted` back as evidence) removes the impurity from the replay surface entirely, and it
yields the better semantics: a low budget should never silently select a worse driver, it should say
where it stopped. This is the one structural improvement in the ruling that no proposal made.

Beyond those, the adjudications went: TOML over YAML (`no` is a string, not `False`, and a policy file
that gates money must not have implicit type coercion or anchors); `Rung × Lane` over numbered tiers
(a number cannot express anydoc-on-DOCX, cheap and high-capability, or a 7B VLM, expensive and
`spatial: none`); demand planning over signal sampling (sampling produces a wrong prior on precisely
the mixed document that motivates per-page routing — the pragmatist's own worked failure); and
`agree.decode_vs_page` adopted as the primary quality channel, because when a part escalates you have
already bought two independent readings, the edit distance between them is free, it lands exactly on
the suspect population, and it yields roughly 40× more labelled points than any audit budget buys.

**Claims I checked and found wrong.** (1) Systems: "`pdf-inspector` already computes exactly this [a
per-page 0..1 fraction of glyph runs with broken `ToUnicode`] and `anydoc/src/formats/pdf.rs:27`
throws it away … the single highest-value free signal in the collection." What that line consumes is
a **document-level boolean**, `result.has_encoding_issues`, from an external crate
(`anydoc/Cargo.toml:30`, `pdf-inspector = "1.14.2"`) that is not in `_collections/` — so "computes
exactly this" is unverifiable, and the per-page fraction is work omniweave must do, not evidence it
can reuse. (2) Systems: "Unlimited-OCR … **The repo does not do that.** There is no one-shot
whole-document path to inherit." `Unlimited-OCR/README.md:94-103` and `:119-129` document
`model.infer_multi(..., image_files=[every page], ngram_window=1024, max_length=32768)` explicitly for
"Multi page / PDF"; what is true is that the shipped `infer.py` sends one page per request
(`PAGE_SIZE = 1`). The blueprint is not wrong that the repo has a long-horizon path; it is wrong that
the path is safe. (3) Pragmatist: "Unlimited-OCR's `infer_multi` is one blob: no per-page retry" —
`grep -rn infer_multi Unlimited-OCR/` hits only the README, and `infer.py:205` has a per-page retry
loop inside `infer_one`. The conclusion survives (the README path has no per-page resume and needs
`trust_remote_code=True`); the citation does not. (4) Minor: systems and pragmatist both say olmocr's
SEO lexicon has 13 words; `olmocr/olmocr/filter/filter.py:35-47` lists 12.

## Rejected

- **Systems' RPL (a hand-rolled predicate language with arithmetic and a typer)** — the compile-time checks it exists to buy (R4, "no signal costs more than the rung it gates") are decidable only against `cost_class` ordinals, which a closed comparison grammar also has; meanwhile it forfeits subsumption linting and makes threshold learning ill-posed. 1,500 LoC of grammar for a strictly smaller checkable surface.
- **Ecosystem's two-valued missing-evidence rule ("a rule reading a `None` key does not match")** — it silently converts "the garble scorer is not installed" into "the page is clean". That is `except Exception: return {}` in a policy file, and it is exactly the pattern `mine-runtime.md` I12 forbids on a safety input.
- **Ecosystem's shipped `builtin:balanced` as authored** — its four-clause escalation rule gates on `probe.ocr_error_p_bad` (`surya/surya/settings.py:137`, `s3://ocr_error_detection/2025_02_18`) and `check.layout_coverage` (needs `hf://datalab-to/surya_layout2`, `:153`); both are under `MODEL_LICENSE` md5 `e1f69b64dee2f1641a9b1ab12adf24d6`. Two of four clauses are dead on day one and the policy never says so.
- **Pragmatist's YAML policy** — YAML 1.1 coerces `no`/`yes`/`on`/`off` to booleans and supports anchors and aliases, which make a policy diff unreadable and an audit ambiguous. TOML has neither and canonicalises reproducibly.
- **Pragmatist's `signal_sampling {head: 8, stride: 32, cap: 96}`** — it is wrong on the exact document class that motivates per-page routing (its own §6.2: a 40-page scanned appendix at pages 2,900–2,940 is hit about once by a stride of 32), and cost-class demand planning is both exact and cheaper.
- **Systems' separate `[objective]` shadow-price block alongside a `PriceBook`** — two versioned artifacts for one job (converting resource units to money), two digests to keep consistent. The `PriceBook` *is* the shadow prices.
- **Estimator-driven selection among admissible rungs as the default** — appealing, and it turns marker's hand-tuned promote fraction into a derived crossover; but the pragmatist measured olmocr's own published $0.0002/page against a naive `gpu_ms` estimate and found a **3.4×** discrepancy before any code existed. Selection on an unreconciled estimator is a cost bug with a proof. Kept as an opt-in `then.driver_by = "cheapest_admissible"`; the shipped default uses `promote_frac`, which the tuner fits from history.
- **A learned end-to-end router** — no labels on day one, and the label you need (which driver would have been right) is the expensive thing you were avoiding computing. It cannot be linted, diffed, or explained to a customer whose bill doubled on Tuesday, and it destroys replay. Learning enters as a `Signal` (`garble.score` already is one) or as a fitted threshold, never as the decider.
- **Per-document routing (docling's `do_ocr: bool`)** — docling computes the best per-page quality signals in the collection (`parse_score`, `layout_score`, `ocr_score`, `table_score`) and consumes none of them. The signal and the router are one feature: ship both or neither.
- **Per-block routing as the primary decision unit** — one full-page request is ~7× cheaper than N block requests on llama.cpp and more accurate; and one decision row per block on a 400-page document at 60 blocks per page is 24,000 accounting rows for a $0.002 document.
- **Budget as a retry count** — `olmocr/olmocr/pipeline.py:106,1221` is 8,000 tokens × 8 retries = 64,000 output tokens per page ⇒ $0.0128 at $0.20/1M, a 64× amplification fired *in parallel* on an idle queue at `--max_concurrent_requests` 1600. A count cannot bound spend when per-attempt cost varies 100× with page density.
- **The blueprint's numbered tiers `0..3` plus `S`** — overturned. A number conflates spend with capability and is the wrong join key for a scoreboard.
- **"tier S — lift, skip everything else"** — overturned on lift's own published 90.2% field / 20.9% full-document. The free text layer is the cheapest grounding signal in existence and the `fields` lane must not throw it away.
- **Unlimited-OCR as a shipped driver** — a 12,450,224-byte unsigned prebuilt sglang wheel from a dev commit as install step 1, `trust_remote_code=True`, and `MAX_RETRIES=5 × REQUEST_TIMEOUT=1200` = 100 GPU-minutes per document. The `Sequence` concept it demonstrates belongs in the policy; the repo does not belong in the dependency graph.
- **A routing microservice** — about 50 µs of atom walking and a few ms of CPU signals do not need a network hop, a second deploy artefact, or a second failure domain.

## Consequences

- **`mine-runtime.md` §7.1.3's `ctx.driver(kind)` is renamed `ctx.resource(kind) -> Resource`.** `Driver` is the parse-engine noun across `mine-parse.md` E11, `_index/framework-blueprint.md` L2 and every bill line an operator reads; the runtime resource accessor must yield the name. One rename, done now, before D5–D10 write against it.
- **`mine-runtime.md` §7.12 open question 1 is settled**: the router's decision grain and the `work` row's identity are the same thing, always. A 4,000-page PDF is 4,000 parts. A `Sequence` groups parts for *execution* and apportions cost by token share; it never changes identity, so the shrink guard and per-part attribution keep working.
- **D5 (storage, indexing, retrieval) inherits six tables and one view** and must not invent a second decision log. `work.decision_id NOT NULL` means the planner is the only producer of work rows.
- **D6/D7 (document model, structure extraction) get `decision_id` on every block** as the join key from an artifact back to the exact decision — provenance for cost, not only for content — alongside `_origin`, `_confidence` and `_partial` from the runtime contract.
- **D8/D9 (out, serve) must render `degradations[]`.** A budget-exhausted parse returns a **success-shaped** response with a banner, never `isError`: one early `isError` teaches the agent the whole toolset is broken and it stops calling. `Degradation.message` names the knob that would raise the limit, which turns an error into a pricing conversation.
- **Every driver ships a `driver.toml`** with a `CostCard`, a capability declaration in `mine-parse.md` E11's vocabulary and a pinned `weights_revision`. That is a real obligation on every parse-engine PR, and it is what makes a third-party driver reachable the afternoon it passes `omniweave driver check`.
- **The operator acquires two new files** (`route.toml`, `pricebook.toml`) and one new obligation: keeping GPU-hour and provider prices current, or every estimate drifts. `route lint` warns when the pricebook is older than 90 days, and the shipped file carries olmocr's published numbers with citations so day one is not blank.
- **The layout hole is now visible and priced.** Until a licence-clean layout detector lands, `REPAIR` is thin on the PDF path and pages marker resolves with a 650M-parameter CPU pass fall through to a 7B VLM. Every affected decision records `cause="layout_unavailable"`, so the cost of the veto is a number in the scoreboard rather than a rumour.
- **A model upgrade resets quality history.** The scoreboard is keyed by `(policy_digest, signal_versions)`; upgrading a signal provider starts a new epoch with `UNKNOWN` cells. There is no fix; it goes in the upgrade documentation.
- **`bytes_egress = 0` by default means the first hosted escalation is a deliberate act**, requiring a site-layer `Grant` with a `dpa_ref` printed in every affected run manifest. This is the direct answer to marker's `--use_llm` shipping page images to Gemini by default, and it is the field that answers the question that kills enterprise deals.
- **A policy change invalidates decisions but must never invalidate artifacts.** If an existing artifact's rung is at or above the new policy's choice, reuse it and record `reused_above_policy`; if it is lower and the new choice is `BILLED_API`, never auto-run — enqueue `needs_upgrade` as `DEFERRED_BUDGET` with a pending-cost record. Re-running a *cheaper* rung to "comply" spends money to obtain a worse answer.
- **CI grows three gates**: `route lint` (unreachable rules, cold rules, scope errors, estimate drift), `route lint --calibration` (ECE and Brier on `garble.score`), and `route simulate --gate` on any PR touching a policy layer.

## Risks

- **`garble.score` is fitted on our corpus and will be miscalibrated on someone else's.** A corpus that is 80% Thai, heavily typeset mathematics, or 1970s typewriter scans reads as either "everything escalates" (a 4× bill) or "nothing escalates" (silent garbage). Mitigations: the score is recorded per part so `route scoreboard --slice` shows the drift, and `decode.cid_ratio`, `decode.replacement_ratio` and `geometry.overlap_line_frac` are model-free and keep working. The calibration gate protects only the corpus we measured, and that is the honest statement.
- **Threshold transfer.** The shipped numbers are marker's, calibrated against marker's classifier's score distribution over a different signal set. The worked breaking input: a corpus of clean CID-keyed CJK PDFs with absent `ToUnicode` CMaps escalates every page to a 7B VLM at ~200 micros instead of ~0. Symmetric auditing detects it as `wasted_escalation`, but needs n ≥ 30 per slice, so the first thousand pages are overspent.
- **The confidently-wrong driver is invisible to escalation rate.** A VLM that transposes an invoice total passes every `Acceptor` and escalates 0%. Only the audit sample and human feedback catch it, both sampled, so a 0.5% error rate on a specific document class is statistically invisible until someone complains. No routing design fixes this; it is why per-field confidence and a review surface are mandatory downstream.
- **The adversarial document.** Every page sits just past both gates (`ink.coverage = 0.24`, `garble.score = 0.49`): the maximum-cost path on every page. `page.collapse-to-sequence` catches the ≤64-part case; beyond it the per-unit budget is the only defence, and the design's answer is to fail visibly at part 63 of 188 rather than expensively at 188.
- **Policy sprawl and first-match shadowing.** 200 rules where rule 3 silently shadows rule 90. Interval subsumption is incomplete over open string domains (`unit.producer_family`) and the linter says so — a lint that overclaims is worse than none. A 200-rule policy is still a policy nobody reads.
- **Slice cardinality.** `format × producer × text_layer × lang` fans out and every cell reads `UNKNOWN` forever. `max_slices = 512` errors at exactly the moment an operator wants more resolution. The design chooses few filled cells over many empty ones, and there is no clean answer.
- **Auto-demotion thrash.** A slice hovering at `divergence ≈ regress_at` oscillates on a 30-day cycle, doubling that slice's cost half the time. Hysteresis at `regress_at * 0.6` and `min_audit_n` bound it; a genuinely borderline slice still oscillates.
- **Pins become the configuration.** Ops pins 4,000 documents "temporarily" and 31% of the corpus leaves the scoreboard. A required `reason`, a default 90-day expiry, a `route lint` coverage warning and a `pinned_fraction` line in every manifest mitigate it; nothing prevents it, deliberately, because the alternative is an escape hatch that is missing at 2 a.m.
- **An adversarial text layer.** Cheap-rung routing trusts that the text layer matches the pixels. `unit.trust_class = untrusted_external` raises the audit rate to 0.05 and bounds the exposure to a sampled cross-check; a single targeted document with a lying text layer will very likely pass at `DECODE`.
- **The conformance harness is the part most likely to be cut and most costly to cut.** Without `omniweave driver check`, capability declarations and cost cards become prose, and the whole third-party story reduces to trust.
- **`route simulate --since 30d` silently degrades the moment someone prunes evidence to 7 days for disk.** `simulate` reports the record count and date range it actually saw and refuses below 1,000 records; a 30-day window on a corpus indexed quarterly is simply empty.
- **The pricebook rots.** Nobody owns GPU-hour prices by default; a 90-day staleness warning is a warning, and warnings get ignored. The `--estimates` lint gate is the real defence because it fails the build.

## Terminology

- Rung := One position on the escalation ladder, from the closed ordered enum `GATE < DECODE < REPAIR < PAGE < REGEN < DEGRADE < ENRICH`. It says how far down the escalation we are, never what it costs. An escalation is a decision whose parent's rung is strictly lower.
- Lane := What is being asked for at a rung, from an open registry of strings seeded with `text`, `table`, `math`, `fields`, `caption`. One resident model can serve several lanes.
- Driver := A named, versioned implementation that produces an artifact for a set of `(Rung, Lane)` pairs, declared in a `driver.toml`. The noun a user reads in `route explain` and in a bill line.
- Signal := One named, typed, scoped, cost-classed observation about a unit, part, block or document, produced by a registered provider. A classifier Signal exposes a probability, never a label.
- Evidence := The flat, namespaced, scalar-valued record of Signal values for one `(unit, part)`. Together with the RoutePolicy and the Narrowing it is the sole input to a routing decision.
- ReadSet := The evidence keys the winning evaluation path actually consulted, each with its provider version and value. Recorded on the decision; the dependency record that makes cached decisions and counterfactual replay correct.
- Rule := One `[[rule]]` in a policy layer: an id, a Rung, an optional Lane, a `when` predicate of closed comparison clauses, a `then` action, and — if it reads a nullable key — a required `on_unknown`.
- RoutePolicy := The merged, compiled, frozen, content-addressed form of the six policy layers. Its `policy_digest` enters every decision row and every cache key.
- RouteDecision := One immutable ledger row per `(content_digest, part, lane, rung, policy_digest, pricebook_digest, narrowing_digest, read_set_digest)`, written before any driver runs.
- Acceptor := A named post-hoc validator on a driver's output (repeat loop, finish reason, token saturation, parse, non-empty, blank region). Its verdict gates escalation and is stored as a `self` verdict, which never enters the Scoreboard.
- Spend := The seven-unit physical resource vector `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls, bytes_egress}`. Drivers report Spend and never money.
- PriceBook := The operator-owned, versioned, digested mapping from Spend units to micros. The only place money appears.
- CostCard := A driver's declared cost model in its `driver.toml` — one of four closed forms, with `per_part`, `per_session`, an optional single-key scaling term, and a p95 output multiple used for reservations.
- Admission := The impure gate that reserves the estimate against the BudgetLedger after `evaluate()` has chosen. Its outcomes are `admitted | deferred | degraded`, and exhaustion is written back as the evidence key `budget.exhausted`.
- Degradation := A typed record of any downgrade — budget, unavailable signal, unavailable driver, exhausted acceptors, auto-demotion, pin, missing grant, pruned policy, stale calibration — carried on the result, in the run manifest and in the serve envelope. Its `message` names the knob that would raise the limit.
- Slice := The accounting bucket for quality and cost: a pure function of Evidence, declared in the policy and capped by `max_slices`. Quality is always per Slice, never per driver.
- Scoreboard := The per-`(slice, rule, driver)` rollup of verdicts and spend, with a three-valued state whose zero value is `UNKNOWN`.
- Narrowing := The typed shape of a request-layer route hint. It may restrict lane, maximum rung, preferred capability and deadline. It has no budget, egress or licence field and therefore cannot widen anything.
- Grant := A site-layer credential authorising egress or a licence-gated driver for a scoped corpus, carrying a required `dpa_ref`, an expiry and an approver. Printed in the run manifest of every document it covers.
- Sequence := A contiguous run of parts bound to one driver session, priced by the CostCard's `per_session` versus `per_part` split. One RouteDecision per part sharing a `sequence_id`, with actual cost apportioned by token share.

## Open questions

- **Is there a licence-clean layout detector we can ship?** — `docling/docling/datamodel/layout_model_specs.py:86-121` names `docling-project/docling-layout-{old, heron, heron-101, egret-medium, egret-large, egret-xlarge}` (RT-DETR), and their weight licences are not in `_collections/`. Settled by fetching each model card and its LICENSE, checking for an OpenRAIL-style competitor clause, and confirming a pinnable revision — docling's own `revision` defaults to `"main"`, which R14 refuses. Until then `layout.class_hist` is absent and `REPAIR` is thin on PDFs.
- **What is the real p95 of `tokens_out` for `page.olmocr` on a representative corpus?** — the whole reservation model rests on it, and the only published anchors ($0.0002/page self-hosted; $0.15–0.20/1M output hosted) are 3.4× apart from a naive `gpu_ms` estimate. Settled by one week of production traffic through `route_spend` and the `--estimates` lint gate, not by another reading of the README.
- **Does `agree.decode_vs_page` correlate with human judgement well enough to drive `auto_demote` on its own?** — it measures agreement, not truth, and two drivers sharing a base model family can be wrong identically. Settled by scoring both channels against a human-labelled eval set built on olmOCR-Bench's `TestType` taxonomy plus lift's adversarial extraction categories, reporting the correlation per slice. Until that exists, only `audit` verdicts may trigger a demotion.
- **What `garble.score` threshold generalises across scripts?** — marker's numbers are its classifier's, and ours is a different model on a different feature set. Settled by fitting per-script thresholds on a labelled multi-script set and measuring whether one global threshold plus a `corpus.lang` slice overlay beats per-script thresholds; the shipped policy reports `calibration: bootstrap` until an eval set is registered.
- **Should decision identity include a lockfile digest?** — a pdfium or tokenizer bump changes signal values with no change to any provider's own source, so a stale decision replays `IDENTICAL` against evidence that would no longer be produced. Including a lockfile digest is correct and invalidates the FREE evidence cache on every unrelated dependency bump. Settled by measuring actual signal drift across one pdfium minor version on a fixture corpus: if drift is nil, per-provider `version` strings suffice.
- **Does interval-box subsumption catch enough shadowing to be worth shipping?** — it is incomplete over open string domains, which is where policy authors will actually collide (`unit.producer_family`, `unit.format`). Settled by running it against a deliberately messy 150-rule policy and counting true positives against the shadowing found by hand.
