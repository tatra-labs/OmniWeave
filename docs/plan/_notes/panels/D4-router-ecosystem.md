# D4 — The routing and escalation policy engine

**Panel:** D4. **Prior:** ecosystem / operator / TCO advocate. **Status:** proposal.

---

## Headline

**Routing is a first-match-wins decision list over a flat, versioned `Evidence` record, held in a
TOML policy file with no executable expressions; every decision is written to a content-addressed
`route_decision` row that records the policy digest and the *read set* of evidence it actually
consulted — which makes the decision replayable byte-for-byte, counterfactually re-evaluable against
a candidate policy over the entire historical log for $0, and attributable when quality regresses —
and a third party adds a driver by dropping a `driver.toml` with a `CostCard` and a capability
declaration, never by editing router code.**

The corollary that drives every mechanism below: **the router *is* the cost model, so the router's
decision must be a durable, diffable, replayable artifact — not a control-flow path.**

---

## 1. Invariants (R1–R15)

| # | Invariant | Enforced by |
|---|---|---|
| **R1** | The policy evaluator is a pure function `evaluate(Policy, Evidence) -> RouteDecision`. No clock, no RNG, no env, no I/O, no import of a caller-supplied name. | Type signature (it takes no `RunContext`, the only channel to the outside per `mine-runtime.md` §7.1.3) + a `semgrep` rule banning `time.`, `random.`, `os.environ`, `importlib`, `open(` inside `omniweave/route/eval.py` + a property test that evaluates 10k stored fixtures twice in shuffled order and asserts identity |
| **R2** | Every sampling decision (shadow audit, canary bucket) is `blake2b(unit_uri + unit_part + policy.salt) mod N` — never `random()`. | Cross-process determinism test; `semgrep` ban on `random`/`secrets` under `omniweave/route/` |
| **R3** | A `RouteDecision` records `read_set` — the evidence keys the winning path actually consulted — and `evidence_digest` is over the read set only. | `Evidence.read()` is the only accessor and appends to a per-evaluation read log; `Evidence` exposes no `__getitem__` and no public mapping |
| **R4** | No evidence key is computed unless a reachable rule reads it, and keys are computed in ascending `cost_class` order. | The policy compiler emits a per-rung demand plan; a test asserts a clean born-digital PDF fixture computes **zero** `LOCAL_COMPUTE` signals and spawns no inference server |
| **R5** | A signal that is a classifier exposes a probability, not only a label. | `SignalSpec` registration rejects `kind="classifier"` whose declared domain is not `[0.0, 1.0]` |
| **R6** | A billable rung is never entered without a successful `BudgetLedger.reserve()`; a denial yields `DEFERRED_BUDGET`, which is not a failure. | `with_budget` sits inside `with_cache` and outside `with_retries` (`mine-runtime.md` §7.8.3); test asserts a denied reservation leaves the `work` row claimable and `cost_micros` unchanged |
| **R7** | Retries within a rung are **serial** and charged to the same per-part budget. Never parallel fan-out on a metered backend. | `REGEN` runs under a semaphore of 1 per `(unit, part)`; a fault-injection test asserts N sequential provider calls, not N concurrent |
| **R8** | Budget exhaustion is a success-shaped result carrying a `Degradation`, never `isError`, never an exception at the API boundary. | Serve-layer contract test; non-empty `degradations` forces a renderer banner; a CI test enumerates every `on_exhausted` branch and asserts each emits a `Degradation` |
| **R9** | A driver's own confidence may *raise* an escalation but may never enter the `Scoreboard` as evidence that the driver is good. | The scoreboard view aggregates `route_verdict` rows only where `source IN ('agree','audit','feedback')`; `source='self'` rows are stored and excluded by the view definition |
| **R10** | A `Scoreboard` cell with `audited_n < min_audit_n` renders `UNKNOWN`, never `OK`. | Three-state enum whose zero value is `UNKNOWN`; the state is computed in the SQL view, not by callers |
| **R11** | `auto_demote` may only move a slice toward the more expensive / reference driver. Promotion is a human commit. | The demotion writer accepts only rules whose `then.driver` has a strictly greater `CostCard` rank; a test attempts a promotion and asserts refusal |
| **R12** | A policy layer above `site` may narrow within declared capability but may not grant egress, raise a budget, or select a licence-gated driver. | `Grant` objects load only from the `site` layer and below; `RouteRequest.hints` is typed `Narrowing`, which has no `budget`/`egress`/`licence_override` fields |
| **R13** | A driver whose `driver.toml` declares `weights_revision` absent or `"main"`, or whose `weights_licence_md5` is on the shipped denylist, fails to load with a named error. | Loader check + in-tree `omniweave/route/licence_denylist.toml`, seeded with md5 `e1f69b64dee2f1641a9b1ab12adf24d6` (the byte-identical marker/surya/lift `MODEL_LICENSE`); CI test asserts a synthetic `revision = "main"` driver is refused |
| **R14** | Safety and resource caps are **not** policy. They are constants (`anydoc/src/package/limits.rs` discipline). Policy may only clamp *below* them. | `Budget` load computes `min(requested, LIMITS.*)`; a test sets a policy budget above the constant and asserts the constant wins |
| **R15** | `omniweave route explain` prints the full trace — evidence read, rules tested, rule fired with `file:line`, estimate, actual spend — for any logged decision, and for a hypothetical one without spending. | Golden-output CLI test; the trace is rendered from the same `read_set` + `rule_origin` fields the decision row stores, so it cannot drift from the decision |

---

## 2. The shape of the decision

### 2.1 Rungs and Lanes — two axes, not one numbered tier

`_index/framework-blueprint.md` routes to numbered tiers (`tier 0` … `tier 3`, `tier S`). **I am
overturning that.** A number conflates *how much you are spending* with *what you are asking for*, and
it cannot express the two cases that actually occur: a cheap driver with high capability (anydoc on
DOCX — single-digit milliseconds, `cells_with_spans` tables) and an expensive driver with low
capability (a 7B VLM emitting flat markdown with `spatial: none`). Two axes:

**`Rung`** — ordered position on the escalation ladder. *How hard we are trying.* Closed enum, ten
values, lifted from the generalized ladder in `mine-parse.md` §B2:

```
GATE     pre-flight, zero compute: limits, encryption, format detection, corpus filters
DECODE   deterministic decode of a text layer or office XML.  Free.
PROBE    cheap classifier(s). KEEP THE SCORE.
CHECK    geometric cross-checks: coverage, overlap, ink, containment
REPAIR   per-block escalation — surgical repair of flagged blocks
PAGE     one full-page model call
VERIFY   output validation: repeat-loop, parse, blank-region, finish_reason, token saturation
REGEN    regeneration of the failed subset only, on a temperature ladder
DEGRADE  a different, cheaper strategy — always MARKED
ENRICH   cross-document / cross-block model pass, scoped by block type, non-fatal
```

**`Lane`** — what is being asked for at that rung. Open registry of strings: `text`, `schema`,
`table`, `math`, `translate`, `caption`. A lane is the generalization of Ollama-OCR's `format_type`
(`Ollama-OCR/src/ollama_ocr/ocr_processor.py:88-99`) and of HunyuanOCR's task-as-prompt API. Lanes let
one resident model serve several objectives without the policy pretending they are one decision.

A `RouteDecision` is `(rung, lane, driver)`. `Rung` being a closed *ordered* enum is what makes
"escalation" a well-defined word: an escalation is a decision whose `parent_decision_id` is non-null
and whose `rung` is strictly greater. That definition is enforceable in SQL and it is what the
scoreboard counts.

### 2.2 The unit of decision

**Part (page/slide/sheet/track), with a block-level *flag* refinement, plus an explicit sequence
binding.** Page-level with block refinement is marker's answer and the only working implementation in
the collection (`marker/marker/builders/line.py`). Three specifics:

1. **`unit_part` is the runtime's part identity** (`mine-runtime.md` §7.3.1: `unit_part TEXT NOT NULL
   DEFAULT ''`, folding NULL so the UNIQUE index works), so a routing decision joins the `work` table
   on `(unit_uri, unit_part, operator, op_version)` with no new identity concept. The router does not
   invent a granularity; it inherits one. **This resolves the first of `mine-runtime.md` §7.12's four
   open questions in the only way that keeps the cost model coherent: the router's decision unit and
   the work table's row identity are the same thing, always.** A 4,000-page PDF is 4,000 parts; a
   sequence binding groups them for *execution* without changing *identity*.
2. **Block-level refinement is a flag, not a decision.** `CHECK`/`REPAIR` set `block.route_flag`; the
   promotion rule then emits exactly one `RouteDecision` for the part, carrying `flagged_blocks` as a
   JSON array of block ids. Rationale is operational: one decision row per block on a 400-page
   document at 60 blocks/page is 24,000 accounting rows for a $0.002 document.
3. **A rule may bind a contiguous part range to one driver session** (`then.sequence = { max_parts =
   32 }`). This is the honest generalization of Unlimited-OCR's long-horizon path: the value there is
   not the model, it is keeping one model resident across a run of layout-consistent pages so the
   per-call overhead amortizes and cross-page context survives. The `CostCard` expresses it directly
   (`per_session_*` vs `per_part_*`), so the planner can *price* a sequence binding rather than guess.
   I reject Unlimited-OCR as a shipped driver — its documented install step 1 is a 12,450,224-byte
   unsigned prebuilt sglang wheel from a dev commit, and `Unlimited-OCR/infer.py:21-36` sets
   `MAX_RETRIES = 5` against `REQUEST_TIMEOUT = 1200`, i.e. 100 minutes of a GPU per document — but the
   *sequence* concept belongs in the policy language, not in one driver.

### 2.3 Escalation, restated as data

The escalation from `DECODE` to `PAGE` is not code. It is this, in the shipped default policy, with
marker's measured thresholds as *policy values*:

```toml
[[rule]]
id      = "check.page-text-unusable"
rung    = "CHECK"
lane    = "text"
comment = "marker/marker/builders/line.py:225-247 — four signals, ANDed there, so ANY failing here."
when.any_of = [
  { "decode.line_count"       = { eq  = 0    } },
  { "probe.ocr_error_p_bad"   = { gte = 0.50 } },
  { "check.layout_coverage"   = { lt  = 0.25 } },
  { "check.overlap_line_frac" = { gt  = 0.50 } },
]
then = { escalate_to = "PAGE", driver = "page.olmocr", trigger_from = "when" }
```

`trigger_from = "when"` tells the evaluator to record *which* clause fired into
`route_decision.trigger` (e.g. `probe.ocr_error_p_bad=0.71>=0.50`). One string per page, and it is what
makes a cost regression attributable six weeks later.

The per-block recheck gate — the mechanism that makes the whole thing affordable — is also a rule:

```toml
[[rule]]
id      = "probe.gate-garble-recheck"
rung    = "PROBE"
comment = "Confidently-clean pages skip the per-block garble recheck entirely (marker's 0.05)."
when    = { "probe.ocr_error_p_bad" = { lt = 0.05 } }
then    = { skip_rungs = ["REPAIR"] }
```

and the exclusion that stops one flagged footer from spawning a GPU server for a clean document:

```toml
[[rule]]
id      = "repair.never-escalate-furniture"
rung    = "REPAIR"
comment = """
marker/marker/builders/line.py:121-124 rationale, verbatim in intent: page headers/footers are
dropped from output by default, so OCRing them wastes a VLM call, and a single flagged footer forces
an otherwise-clean document to spawn the inference server. Equations, tables, figures, forms have
their own lanes.
"""
when = { "block.type" = { in = [
  "PageHeader","PageFooter","Picture","Figure","Diagram","Table","Form",
  "TableOfContents","Equation","ChemicalBlock" ] } }
then = { outcome = "not_eligible" }
```

Three things follow from putting these in a file rather than in `line.py`. An operator can raise
`0.05` to `0.20` on a corpus of clean typeset journals and *measure the saving with `route simulate`
before deploying*. A support engineer can answer "why did this document cost $4" by reading `route
explain`. And a threshold tuned on marker's corpus is visibly *someone's tuning* — versioned,
attributable, and safe to change — rather than a constant in our source that nobody dares touch.

### 2.4 De-escalation — the rule marker does not have

If more than `escalation_ceiling` of a document's parts escalate to `PAGE`, per-part routing has lost:
you are paying the routing overhead *and* the full-document cost. One full-document sequence run is
both cheaper — `mine-parse.md` records **~7×** for one full-page request vs N block requests on
llama.cpp (`marker/marker/builders/ocr.py:80-82`) — and more accurate, because crops lose context.

```toml
[[rule]]
id   = "page.collapse-to-sequence"
rung = "PAGE"
when = { "doc.escalated_part_frac" = { gt = 0.80 }, "doc.part_count" = { lte = 64 } }
then = { driver = "page.olmocr", sequence = { max_parts = 64 }, reason = "de-escalation" }
```

This needs one non-obvious property: `doc.escalated_part_frac` is a **document-scoped evidence key
computed from decisions already made for other parts of the same unit**. So the evidence registry has
four scopes (`unit`, `part`, `block`, `doc`), and a `doc`-scoped key is readable only at a rung that
runs after every part has a `CHECK` verdict. The compiler enforces the ordering; a policy reading a
`doc`-scoped key from a `GATE` rule fails `route lint`.

---

## 3. `Evidence` — a flat namespaced map, deliberately

```python
# omniweave/route/evidence.py
Scalar = str | int | float | bool | None

@dataclass(frozen=True, slots=True)
class Signal:
    value: Scalar
    version: str                 # provider + semver, e.g. "surya-ocr-error@0.22.1"

class Evidence:
    """A flat, namespaced, scalar-valued record about ONE (unit, part).

    Deliberately NOT a nested dataclass of named attributes. A third party adding
    `signal.acme.blur_variance` must not need a core release, and the policy file must be
    able to name a key core has never heard of. The registry supplies types and ranges;
    the container supplies lookup and a read log, nothing else.
    """
    __slots__ = ("_v", "_read", "_scope")

    def read(self, key: str) -> Scalar:
        """The ONLY accessor. Appends to the read log (invariant R3)."""

    def read_set(self) -> tuple[str, ...]: ...
    def digest(self, keys: Iterable[str]) -> str:   # sha256 of canonical JSON, allow_nan=False
        ...
```

A nested dataclass would be prettier internally and would require a core edit for every new signal.
That is exactly the boundary hostility this prior exists to reject.

### 3.1 The signal registry

```python
@dataclass(frozen=True)
class SignalSpec:
    key: str                    # "probe.ocr_error_p_bad" — namespace.name, both [a-z0-9_]+
    scope: Literal["unit", "part", "block", "doc"]
    kind: Literal["fact", "measure", "classifier", "count"]
    dtype: Literal["bool", "int", "float", "str"]
    domain: tuple[float, float] | frozenset[str] | None
    cost_class: CostClass       # FREE | LOCAL_COMPUTE | BILLED_API
    est: Spend                  # what computing THIS SIGNAL costs, per scope instance
    provider: str               # entry-point name
    version: str
    requires: tuple[str, ...] = ()   # rungs whose output this signal needs
    nullable: bool = True            # uncomputable ⇒ None, never a default
```

Non-negotiable registry rules, each with its source:

- **`kind="classifier"` must declare `domain=(0.0, 1.0)` and return the probability** (R5). This
  exists because `surya/surya/ocr_error/schema.py` is the only classifier result in the collection
  carrying `scores` beside `labels`, with a comment saying exactly why: *"P(bad) per text (softmax of
  the 'bad' class). Lets callers gate expensive follow-up work on confidence instead of just the
  argmax label."* A label-only classifier makes tiered routing impossible; marker's `>= 0.05` gate
  cannot exist without it. Any driver author shipping a label-only signal is rejected at registration
  with that sentence as the error message.
- **`nullable=True`, and `None` is not a default.** A signal that failed to compute is `None`; a rule
  reading a `None` key does not match — it is not `0`, not `false`. This is `lift`'s failure inverted
  (it prints and drops `response_format` when schema compilation fails, degrading silently).
  `route explain` prints `probe.ocr_error_p_bad = None (provider unavailable)` and the decision records
  `degradations = ["signal_unavailable:probe.ocr_error_p_bad"]`.
- **`est` is what makes lazy demand possible.** The compiler groups reachable keys by `cost_class`,
  computes `FREE` first, re-tests rules, and pays for `LOCAL_COMPUTE` only if nothing has fired. This
  is R4, and it is the single most important operational property of the design: **a clean born-digital
  PDF computes no `LOCAL_COMPUTE` signal and never starts an inference server.** marker gets this by
  hand-ordering code; we get it from a cost annotation, which means it stays true when a third party
  inserts a signal in the middle.

### 3.2 The default registry (abridged) — 34 keys, 9 of them non-free

| key | scope | kind | cost | provenance |
|---|---|---|---|---|
| `unit.format` | unit | fact | FREE | content-first detection; mime→format is one-to-many (`docling` `MimeTypeToFormat`) |
| `unit.bytes`, `unit.part_count`, `unit.encrypted`, `unit.corrupt` | unit | fact | FREE | `anydoc` `ConvertError` as routing data |
| `unit.producer_family` | unit | fact | FREE | PDF `/Producer` bucketed to ~30 families — the strongest cheap predictor of layout pathology, and the natural slice axis |
| `unit.needs_ocr_parts` | unit | count | FREE | `anydoc/src/error.rs:20` `NeedsOcr{pages, page_count}` — an error used as a routing signal; over-reports by design |
| `unit.schema_requested` | unit | fact | FREE | the caller supplied a JSON Schema |
| `gate.is_form`, `gate.lang`, `gate.spam_score`, `gate.dup_of` | unit | classifier | FREE | `olmocr/olmocr/filter/filter.py` — but as **signals**, never exclusions |
| `decode.char_count`, `decode.line_count`, `decode.has_charspan` | part | count | FREE | `pdftext` / office XML |
| `probe.ocr_error_p_bad` | part | classifier | LOCAL_COMPUTE | `surya` `OCRErrorDetectionResult.scores` |
| `check.layout_coverage`, `check.overlap_line_frac`, `check.empty_box_area_frac`, `check.sibling_containment` | part | measure | LOCAL_COMPUTE | `marker/marker/builders/line.py` |
| `check.has_ink` | block | fact | FREE | `is_blank_image` on the crop |
| `layout.class_hist` | part | count | LOCAL_COMPUTE | layout detector; drives lane selection for math/table |
| `render.short_edge_px`, `render.dpi_effective` | part | measure | FREE | `lift`'s **692 px** short-edge floor; a VLM sees pixels, not points |
| `agree.decode_vs_page` | part | measure | FREE* | **new — §7.2** |
| `verify.repeat_ngram_max` | part | measure | FREE | `olmocr/olmocr/repeatdetect.py:8` `RepeatDetector.ngram_repeats`; `surya/surya/recognition/__init__.py:88` `_detect_repeat_loop` |
| `verify.finish_reason`, `verify.token_saturation` | part | fact | FREE | `finish_reason == "stop"`; `tokens_out / max_tokens` |
| `verify.schema_violations`, `verify.grounded_field_frac` | unit | count | FREE | **new — §7.3** |
| `doc.escalated_part_frac` | doc | measure | FREE | de-escalation, §2.4 |

`FREE*` means free *when both readings already exist*; the spec carries
`requires = ("DECODE", "PAGE")` so a rule reading it can only run at `VERIFY` or later.

---

## 4. The policy language

### 4.1 Why TOML, and why no expressions

**TOML, not YAML:** no implicit type coercion (`no` is a string, not `False`), no anchors or aliases
(which make a diff unreadable and an audit ambiguous), and a canonical serialization that is easy to
digest reproducibly. Rules are `[[rule]]` arrays of tables, which diff line-by-line.

**No embedded expression language, no Python callables, no dotted-path imports.** This is not
conservatism; it is a specific bug being refused. `marker/marker/config/parser.py:73,79` exposes
`--converter_cls` and `--llm_service` as arbitrary dotted paths, settable from `--config_json`, and
`marker/marker/scripts/convert_single.py:30,36` imports and constructs whatever it finds — an RCE
channel the moment config arrives in a request body. A policy file that can execute is that bug with
extra steps, and a policy that can execute cannot be learned, subsumption-linted, or safely accepted
from a customer's repo.

The predicate grammar is therefore closed and total:

```
rule        := { id, rung, lane?, when, then, comment?, expires?, canary? }
when        := clause | { any_of: [clause, ...] } | { all_of: [clause, ...] } | { none_of: [clause, ...] }
clause      := { <evidence_key>: test, ... }      # implicit AND across keys
test        := scalar                              # equality shorthand
             | { eq | ne | lt | lte | gt | gte: number|string }
             | { in | not_in: [scalar, ...] }
             | { exists: bool }
then        := { driver?, lane?, escalate_to?, skip_rungs?, sequence?, outcome?,
                 failure_class?, terminal?, trigger_from?, reason?, render? }
```

One level of `any_of`/`all_of`/`none_of` nesting only. First match wins, evaluated in file order after
layer merge. That restriction is what buys `route lint`'s unreachability analysis (§6.3) and what
makes threshold learning a well-posed problem (§7.6).

### 4.2 The shipped default policy — `builtin:balanced`, abridged

```toml
# omniweave/route/policies/balanced.toml            (shipped, in-package, immutable)
policy_name    = "builtin:balanced"
policy_version = 1
schema         = "omniweave.route/1"

[slice]
by         = ["unit.format", "unit.producer_family", "decode.has_text_layer", "gate.lang", "layout.page_class"]
max_slices = 512

[budget.per_unit]
wall_ms      = 120_000
micros       = 20_000          # $0.020 per document
tokens_out   = 32_000
gpu_ms       = 60_000
calls        = 64
bytes_egress = 0               # 0 = no hosted escalation without a site-layer Grant
on_exhausted = ["spill_to_free", "partial", "defer"]

[budget.per_part]
micros     = 2_000             # $0.002 — 10x the olmocr self-host baseline of $0.0002/page
tokens_out = 8_000             # olmocr MAX_TOKENS=8000: ONE attempt's worth, not eight
calls      = 4

[audit]
rate        = 0.005
salt        = "2026-09-a"
reference   = "page.olmocr"
min_audit_n = 30
regress_at  = 0.08
auto_demote = true

# ---- GATE -----------------------------------------------------------------
[[rule]]
id   = "gate.encrypted"
rung = "GATE"
when = { "unit.encrypted" = true }
then = { outcome = "refuse", failure_class = "PASSWORD_PROTECTED" }

[[rule]]
id      = "gate.form-is-a-signal-not-an-exclusion"
rung    = "GATE"
comment = """
olmocr's PdfFilter discards every form and every non-English document by default with a logger.info
only. 'is a form' is a routing signal: forms go to the schema lane, they are not dropped.
"""
when = { "gate.is_form" = { gte = 0.5 } }
then = { lane = "schema", render = { short_edge_px = 1024 } }

# ---- DECODE ---------------------------------------------------------------
[[rule]]
id      = "decode.office-native"
rung    = "DECODE"
comment = """
Native formats have a canonical reading order; never re-infer it, and never funnel them through a
PDF renderer. marker subclasses PdfProvider for DOCX/PPTX/XLSX/EPUB/HTML and renders to a temp A4
PDF, destroying speaker notes, comments, tracked changes, OMML math, numbering restarts, footnote
linkage and true logical order BEFORE parsing starts. terminal = true forbids escalation.
"""
when = { "unit.format" = { in = ["docx","pptx","xlsx","epub","html","md","csv","txt"] } }
then = { driver = "decode.anydoc", lane = "text", terminal = true }

[[rule]]
id   = "decode.pdf-text-layer"
rung = "DECODE"
when = { "unit.format" = "pdf", "decode.char_count" = { gt = 0 } }
then = { driver = "decode.pdftext", lane = "text" }

# ---- PROBE / CHECK / REPAIR / PAGE ---------------------------------------
#  (rules of §2.3 and §2.4 here)

# ---- VERIFY / REGEN / DEGRADE -------------------------------------------
[[rule]]
id      = "verify.repeat-loop"
rung    = "VERIFY"
comment = "Length-scaled threshold; real documents repeat, so repetition_penalty stays 1.0."
when.any_of = [
  { "verify.repeat_ngram_max" = { gte = 12 } },
  { "verify.finish_reason"    = { ne  = "stop" } },
  { "verify.token_saturation" = { gte = 0.98 } },
]
then = { escalate_to = "REGEN", reason = "output-validation-failed", trigger_from = "when" }

[[rule]]
id      = "degrade.marked-fallback"
rung    = "DEGRADE"
comment = "A downgrade must appear in the result. Unlimited-OCR writes \"\" for a page that failed 5 retries."
when    = { "verify.attempts_exhausted" = true }
then    = { driver = "decode.pdftext", outcome = "ok_partial", reason = "regen-exhausted" }
```

### 4.3 The compiled form

`route compile` turns the merged policy into a `CompiledPolicy` — the artifact the evaluator runs and
the thing that is digested:

```python
@dataclass(frozen=True, slots=True)
class CompiledRule:
    id: str
    origin: str                     # "project:.omniweave/route.toml:41"
    rung: Rung
    lane: str | None
    reads: frozenset[str]           # evidence keys this rule tests
    predicate: tuple[Atom, ...]      # flattened, interned, no closures
    action: Action

@dataclass(frozen=True, slots=True)
class CompiledPolicy:
    digest: str                     # sha256 of canonical JSON of the whole compiled form
    layers: tuple[LayerRef, ...]     # each with its own file digest, for the manifest
    rules_by_rung: Mapping[Rung, tuple[CompiledRule, ...]]
    demand_plan: Mapping[Rung, tuple[tuple[CostClass, frozenset[str]], ...]]
    slice_fn: SliceSpec
    budgets: Mapping[BudgetScope, Budget]
    audit: AuditSpec
```

`predicate` is a tuple of interned atoms, not compiled closures, because the atoms must be *readable*
by the linter and the learner. Evaluation is a walk over ≤ a few hundred atoms.

---

## 5. The cost model

### 5.1 `Spend` — seven units, and only one of them is money

```python
class Unit(StrEnum):
    WALL_MS      = "wall_ms"
    CPU_MS       = "cpu_ms"
    GPU_MS       = "gpu_ms"
    TOKENS_IN    = "tokens_in"
    TOKENS_OUT   = "tokens_out"
    CALLS        = "calls"
    BYTES_EGRESS = "bytes_egress"

@dataclass(frozen=True, slots=True)
class Spend:
    wall_ms: int = 0
    cpu_ms: int = 0
    gpu_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    bytes_egress: int = 0
    provider: str = ""            # "" = local
    def __add__(self, other: "Spend") -> "Spend": ...
    def micros(self, book: "PriceBook") -> int: ...   # the ONLY place money appears
```

**Drivers never state dollars.** A driver author states resource units; the *operator* states prices.
This is the split that makes the ecosystem work: a contributor in another country running on a rented
A100 has no idea what your GPU-hour costs, and if they guess, every cost estimate in your fleet is
wrong in a way you cannot audit. It is also what makes the cost model portable across on-prem, cloud
and laptop without a driver change.

```toml
# .omniweave/pricebook.toml           (operator-owned, versioned, digested into every decision)
pricebook_version = 4
currency          = "USD"            # accounting currency; micros = 1e-6 currency

[local]
cpu_ms_micros = 0.0000116            # 8 vCPU at $0.334/h  =>  $0.0000000116/ms/core
gpu_ms_micros = 0.000306             # 1x L40S at $1.10/h
wall_ms_micros = 0.0                 # wall time is BUDGETED but not PRICED

[provider.openai_compatible_local]
tokens_in_micros  = 0.0
tokens_out_micros = 0.0

[provider.deepinfra]
comment           = "olmocr/README.md:339-341 hosted olmOCR-2-7B-FP8"
tokens_in_micros  = 0.10             # $0.10 / 1M in
tokens_out_micros = 0.20             # $0.20 / 1M out
calls_micros      = 0.0

[egress]
# bytes_egress is a COMPLIANCE unit, not a price. Non-zero egress requires a Grant.
requires_grant = true
```

Pricing `wall_ms` at zero while still budgeting it is deliberate: an agent's patience is a real
constraint that money does not express (`jcodemunch` §5.1 sets `strict_timeout_ms` default **500 ms**
for an agent-facing freshness wait). **The first exhausted budget dimension wins**, so a document can
be cut short by time on a machine where compute is free.

`bytes_egress` as a first-class unit is the operator-advocate move. `marker`'s `--use_llm` ships
rendered page images to Gemini by default; `ppt-master`'s `edge-tts` sends narration text to an
undocumented Microsoft endpoint; `markitdown`'s `SpeechRecognition` does the same for audio. Each
converts a compute cost into a third-party data-processing agreement. Making egress a budget unit whose
default limit is **0** means an escalation that leaves the machine cannot happen by accident — it takes
a `Grant`, and a `Grant` is a credential loaded from the site layer, not a flag.

### 5.2 `CostCard` — the driver's declared price list

```toml
# drivers/page-olmocr/driver.toml
[driver]
name    = "page.olmocr"
rungs   = ["PAGE", "REGEN"]
lanes   = ["text"]
version = "0.4.0"

[licence]
code_spdx           = "Apache-2.0"
weights_spdx        = "Apache-2.0"
weights_repo        = "allenai/olmOCR-2-7B-1025-FP8"
weights_revision    = "b3f1c2d9e4a7..."      # R13: absent or "main" fails to load
weights_licence_md5 = "9a1f..."              # checked against licence_denylist.toml

[capabilities]                                # mine-parse.md E11, verbatim vocabulary
spatial       = "page_bbox"
charspan      = false
reading_order = "model_emitted"
sections      = "markdown_only"
tables        = "flat_html"
math          = "latex"
assets        = "none"
notes         = "none"
confidence    = "page"
furniture     = "flagged"
round_trip    = "text"

[cost]
model = "linear_per_part"
per_part    = { gpu_ms = 1_900, tokens_in = 1_650, tokens_out = 1_100, calls = 1 }
per_session = { gpu_ms = 4_100 }              # model load / warmup, amortized over a sequence
scaling     = { tokens_in = { key = "render.short_edge_px", exponent = 2.0, ref = 1288 } }
variance    = { tokens_out_p95_multiple = 3.4 }   # what the estimator uses for the RESERVATION

[requires]
probe   = "vlm_chat_completions"               # capability probe name, not an import
min_vram_gb = 12                               # olmocr/README.md:221
egress  = false
```

Rules with teeth:

- **`estimate(evidence) -> Spend` is a pure function of the cost card and evidence**, computed by core
  from the declared model. A driver may not supply an estimator function — a driver-supplied estimator
  is a driver-supplied lie the router has no way to audit. The declared forms are
  `constant | linear_per_part | linear_per_byte | linear_per_token`, with an optional `scaling` term on
  one evidence key. Four forms cover every driver in the collection.
- **Reservations use `p95`, commits use actuals.** `variance.tokens_out_p95_multiple` is what stops the
  first document of a batch from consuming the corpus budget. The conformance harness measures the real
  p95 over the fixture corpus and **fails the driver if the declared multiple understates it by >25%**.
  This is the honesty mechanism for the cost model: a driver that lies about its variance cannot pass
  `driver check`.
- **`per_session` vs `per_part` is what prices a sequence binding.** For `page.olmocr` above, a
  32-part sequence costs `4_100 + 32*1_900 = 64.9 GPU-s` versus `32*(4_100+1_900) = 192 GPU-s` for 32
  cold calls — a 3.0× difference the planner can see *before* choosing. Nobody in the collection can
  express this, which is why marker's ~7× measurement lives in a comment instead of in a plan.

### 5.3 The cost table the router actually holds

Spread across engines is roughly four orders of magnitude, and these are the numbers that go in the
shipped pricebook's commentary (all from `mine-risk.md` §22.1, all provider-reported):

| tier | driver class | evidence | cost/page |
|---|---|---|---|
| DECODE | CPU text-layer / office XML | `anydoc` single-digit ms, Rust | ~$0 |
| PROBE | 60M-class DistilBERT classifier | `surya` `OCRErrorPredictor`, batch 14 on CUDA | ~$0 |
| CHECK | geometry only (numpy) | `marker` `matrix_intersection_area` | ~$0 |
| PAGE self-host | 7B VLM | `olmocr/README.md:36` **< $200 / 1M pages** | **$0.0002** |
| PAGE hosted | 7B VLM FP8 | `olmocr/README.md:339-341` $0.10 in / $0.20 out per 1M tok | ~$0.0004 |
| PAGE hosted, 8 retries | same | `pipeline.py:107,1221`: 8000 tok × 8 = 64,000 tok | **$0.0128 (64×)** |
| ENRICH | frontier VLM per block | provider list price | $0.001–0.01 |

The 64× row is the whole argument for a budget rather than a retry count, and it is why
`budget.per_part.tokens_out = 8_000` in the default policy: **one attempt's worth**. A page that needs
a second attempt is spending the *unit* budget, visibly, and the fourth attempt on the same page is
denied by arithmetic rather than by a retry counter someone can raise.

---

## 6. Caching, replay, and overrides — the operator surface

### 6.1 Two caches with opposite policies

Adopting `mine-runtime.md` §7.5.2 (from graphify §3.2) exactly, because the distinction matters more
here than anywhere:

| | **decision cache** | **driver-output cache** |
|---|---|---|
| key | `sha256(canonical({policy_digest, pricebook_digest, unit_content_digest, part, evidence_digest_over_read_set, signal_versions_over_read_set}))` | `cache_key(unit, OperatorIdentity, ctx)` per §7.5 |
| tier | FREE — swept | BILLED_API — **never swept**, pruned by liveness only |
| miss cost | one decision-list walk, µs | one VLM page, $0.0002–$0.0128 |
| invalidation | any policy or pricebook change | config digest only |

**Keying the decision cache on the read set, not on all evidence, is the load-bearing choice.** A
third party installing a new signal provider must not invalidate 4 million cached decisions that never
consulted it. This is codegraph's dependency-record lesson (`4.3% of distinct edges wrong, in both
directions, silently, forever until a full rebuild` without `resurrectStaleResolutionEdges`) applied to
routing: **re-derive everything whose answer depended on what changed, and the read set is the
dependency record.**

The `signal_versions_over_read_set` component is why a probe upgrade *does* invalidate: if
`probe.ocr_error_p_bad` was read and its provider went `0.22.1 → 0.23.0`, the decision is recomputed.
Correct, and cheap.

### 6.2 Deterministic replay, and counterfactual replay

```
$ omniweave route replay dec_7f3a91c4...
decision  dec_7f3a91c4  unit=file:///corpus/10-K.pdf part=41
policy    project@a91c4f2e  (site@771be0, builtin:balanced@0c19aa)
pricebook local@4  (2026-08-14)
replay    IDENTICAL   rule=check.page-text-unusable  rung=CHECK->PAGE  driver=page.olmocr
```

Replay re-evaluates the *stored* `Evidence` read set against the *stored* policy digest and asserts
the same `(rule_id, rung, lane, driver)`. Three outcomes, and each is a distinct exit code:
`IDENTICAL` (0), `DIVERGED` (3 — a real bug in the evaluator, and CI runs this over 10k fixtures),
`REPLAY_DRIFT` (4 — the policy or a signal version is no longer available; reported, never silently
accepted).

The version that changes operator behaviour is the counterfactual:

```
$ omniweave route simulate --policy ./candidate.toml --since 30d --slice unit.format=pdf
6,412,881 decisions replayed in 41s  (no drivers loaded, nothing spent)

                       current            candidate          delta
PAGE escalations       1,204,551 (18.8%)    712,338 (11.1%)   -40.9%
est. micros            18,240,700          11,905,412          -34.7%   (-$6.34)
est. gpu_ms            2,288,646,900        1,353,442,300      -40.9%
slices moved                                     37
  regressed slices                                 2   <-- FAIL
    pdf/scansnap/no-text/ja/dense_table   audited_n=214  divergence 0.031 -> 0.147  (regress_at 0.08)
    pdf/quartz/text/en/two_column_math    audited_n=61   divergence 0.044 -> 0.121
exit 3
```

**This is the feature that makes routing tunable at all, and no repo in the collection has it.** It is
possible only because (a) the decision log stores the evidence read set, (b) the evaluator is pure, and
(c) shadow-audit divergence is recorded per slice. The cost is a 900-byte row per part; the return is
that a threshold change is a measured change instead of an argument. `--gate` makes it a CI job: a PR
that edits `route.toml` runs `route simulate` against the last 30 days and fails on a regressed slice.
That is the whole quality-honesty story compressed into one CI check.

Determinism has one hard requirement that everyone gets wrong: **sampling must be derived, not
random** (R2). `audit_selected = blake2b(unit_uri||part||audit.salt).digest_int % 10_000 < rate*10_000`.
Otherwise replay reproduces the decision but not the audit, and the divergence series is not
reproducible either.

### 6.3 `route lint` and `route explain`

```
$ omniweave route lint
.omniweave/route.toml:112  W-UNREACHABLE  rule "repair.aggressive-tables" can never fire:
  subsumed by rule "repair.never-escalate-furniture" (:41), which matches
  block.type in {...,"Table",...} for all inputs where this rule's predicate holds.
.omniweave/route.toml:88   W-COLD         rule "page.hunyuan-cjk" fired 0 times in 30d (12,441 candidates)
.omniweave/route.toml:203  E-SCOPE        rule reads doc-scoped key "doc.escalated_part_frac" at rung GATE
.omniweave/pins.toml               W-PIN  4,118 active pins cover 31.4% of the corpus; 3,902 have no expires
policy digest a91c4f2e   slices declared: max 384 of 512   effective budget micros: 20000 (policy) / 20000 (limit)
2 warnings, 1 error
```

Unreachability is decidable here *because* predicates are comparisons on a closed key set with declared
domains: the linter converts each rule to an interval box per key and tests subsumption. It is
incomplete for `in`-sets over open string domains (`unit.producer_family`), and it says so — a lint that
overclaims is worse than none.

`route explain` is the support tool, and it is why an operator will keep this framework:

```
$ omniweave route explain corpus/10-K.pdf --part 41
unit    file:///corpus/10-K.pdf  content_digest=sha256:2b91...  format=pdf  producer_family=quartz
part    41/188   slice=pdf/quartz/text/en/two_column

evidence computed (cost-ordered)
  FREE           unit.format=pdf  unit.part_count=188  decode.char_count=3011  decode.line_count=74
  LOCAL_COMPUTE  probe.ocr_error_p_bad=0.71            (surya-ocr-error@0.22.1, 41ms)
  LOCAL_COMPUTE  check.layout_coverage=0.19            (marker-geometry@1.0.0, 6ms)
  not computed   layout.class_hist                     (no reachable rule reads it)

rules tested at rung CHECK  (first match wins)
  1 check.blank-page-escape      builtin:balanced.toml:171   NO  (total_blocks=22, not 1)
  2 check.page-text-unusable     project route.toml:41       YES
       trigger  probe.ocr_error_p_bad=0.71 >= 0.50
                check.layout_coverage=0.19 < 0.25
       action   escalate_to=PAGE driver=page.olmocr

estimate  gpu_ms=1900 tokens_in=1650 tokens_out=1100(p95 3740) calls=1 => 0 micros (local)
budget    per_part micros 0/2000  tokens_out 3740/8000 reserved   per_unit micros 610/20000
decision  dec_7f3a91c4   (not yet executed; --execute to run)
```

Every line of that trace is rendered from fields the decision row already stores, so it cannot drift
from what actually happened (R15). This is the difference between "the router decided" and "here is
why, in the operator's own file, at a line number they can edit".

### 6.4 The override stack

Six layers, lowest to highest. Higher layers **prepend** rules (first-match-wins ⇒ higher wins), and
every compiled rule keeps its `origin` as `layer:path:line`.

| layer | location | who owns it | may set |
|---|---|---|---|
| `builtin` | in-package, immutable | us | everything |
| `site` | `/etc/omniweave/route.d/*.toml`, `%PROGRAMDATA%\omniweave\route.d\*.toml` | the platform team | everything, incl. `Grant`s |
| `project` | `.omniweave/route.toml` (+ `route.d/`) | the repo | rules, budgets ≤ site, slices |
| `profile` | named block, selected `--profile fast\|balanced\|exact\|cheap` | the repo | rule overlays only |
| `request` | `route_hints` on the API/MCP/CLI call | the agent | a `Narrowing` only |
| `pin` | `.omniweave/pins.toml` | ops | one `(unit, part?) -> driver` with `reason` + `expires` |

**`request` is typed as `Narrowing` and that type has no budget, egress, or licence field** (R12). An
agent may say `lane = "table"`, `max_rung = "REPAIR"`, `prefer_capability = "cells_with_spans"`,
`deadline_ms = 4000`. It may not say "spend more" or "send this to Gemini". Widening is a `Grant`:

```toml
# /etc/omniweave/route.d/20-grants.toml     (site layer only)
[[grant]]
id           = "gemini-enrich-legal"
allows       = { egress = true, provider = "google_genai", rungs = ["ENRICH"] }
scope        = { corpus = "legal/**" }
dpa_ref      = "DPA-2026-114"          # required, free text, printed in every manifest that uses it
expires      = 2027-03-31
approved_by  = "platform@example.com"
```

The `dpa_ref` field is required and unvalidated on purpose: its job is to make the person adding
hosted escalation write down which data-processing agreement covers it, and to make that string appear
in the run manifest of every document that egressed. That is a one-line schema change that answers the
single question that kills enterprise deals.

**No `--force`.** Named overrides only, inheriting `mine-runtime.md` §7.6.3's rule verbatim — *"an
override flag whose scope is 'skip whatever check just complained' is not an override, it is an off
switch."* The router's set: `--allow-egress <grant-id>`, `--allow-rebill`, `--accept-partial`,
`--ignore-decision-cache`, `--max-rung <RUNG>`, `--budget-micros N` (site layer or below only).

---

## 7. Staying honest about quality

Five mechanisms, in increasing cost. Only the last three may write the `Scoreboard` (R9).

### 7.1 Free self-report validation — the `VERIFY` rung

Every driver returns validation signals the router can score with no second opinion:
`verify.repeat_ngram_max` (`olmocr/olmocr/repeatdetect.py:8` `RepeatDetector.ngram_repeats`;
`surya/surya/recognition/__init__.py:88` `_detect_repeat_loop`, called at `:296`),
`verify.finish_reason`, `verify.token_saturation`, blank-region hallucination checks, parse failure of
emitted HTML, `verify.schema_violations`. These gate `REGEN` and `DEGRADE`. They are recorded as
`route_verdict` rows with `source='self'` — **stored, and excluded from the scoreboard**, because a
driver grading itself is docling grading a document `EXCELLENT` on a `table_score` that is never
computed.

### 7.2 Cross-rung agreement — the best free signal, and nobody uses it

**When a part escalates from `DECODE` to `PAGE`, you have paid for two independent readings of the
same page. The normalized edit distance between them is free, and it is a direct measurement of the
cheap driver's quality on that slice.**

```
agree.decode_vs_page = 1 - lev(norm(decode.text), norm(page.text)) / max(len_a, len_b)
```

with `norm` from olmOCR-Bench's `normalize_text`. Every escalation therefore contributes one labelled
data point about `DECODE` at zero marginal cost. On a corpus where 18.8% of pages escalate, that is
188,000 free quality measurements per million pages — vastly more than any audit budget buys — and it
is *exactly* the population where `DECODE` is suspect, which is where you want the measurement.

Two honest limitations, both stated in the scoreboard's own column headers: it measures agreement, not
truth (both drivers can be wrong the same way, especially on the same base model family), and it is
biased toward the escalated population, so it cannot estimate `DECODE`'s quality on pages that never
escalated. That second bias is precisely what §7.4's shadow audit exists to cover. Neither mechanism
alone is sufficient; together the escalated population is measured for free and the non-escalated
population is measured at 0.5%.

### 7.3 The schema lane's mandatory free cross-check

`_index/framework-blueprint.md` says *"tier S — lift, skip everything else."* **I reject "skip
everything else."** `lift`'s own published benchmark is **90.2% per field but 20.9% full-document** on
its adversarial set (`lift/README.md`), and the open weights ship no verification layer — citations and
verification are hosted-only. Accuracy does not compound, so a schema shortcut that discards the free
text layer discards the only cheap grounding signal available.

The schema lane therefore **always runs `DECODE` too** (it is free) and emits, per extracted field:

```python
@dataclass(frozen=True, slots=True)
class FieldGrounding:
    path: str                # "items[3].sku"
    value: Scalar
    grounded: bool           # value found verbatim (normalized) in the decoded text layer
    part: int | None         # which part it was found on
    charspan: tuple[int,int] | None   # docling ProvenanceItem.charspan when available
```

`verify.grounded_field_frac` then becomes a routing signal: below `grounded_min` (default 0.60,
excluding fields whose JSON Schema type is `number` or `boolean`, where verbatim matching is
meaningless), the lane escalates to a second extraction at a higher render resolution, or degrades to
`ok_partial` with the ungrounded fields flagged for review. This is a free verification layer bolted
onto the one component that lacks one, and it turns `lift`'s "left blank vs hallucinated" discipline
(`make_properties_nullable` at `lift/lift/model/vllm.py:29`) into an *observable* rather than an
aspiration. Design the UX around per-field confidence and review, never a document-level pass/fail.

### 7.4 The shadow audit lane

A deterministic sample (default `rate = 0.005`) of parts routed to a cheap driver is **also** run on
the policy's `reference` driver, off the critical path, charged to a separate `audit` budget that
cannot borrow from the unit budget.

```
divergence(slice, rule, driver) = 1 - mean(agree(cheap_output, reference_output))
```

When `audited_n >= min_audit_n` (30) and `divergence > regress_at` (0.08), the router raises
`SliceRegressed` and, if `auto_demote = true`, appends a demotion rule to a machine-owned layer:

```toml
# .omniweave/route.auto.toml          MACHINE-WRITTEN. Do not edit; edits are overwritten.
[[rule]]
id      = "auto.demote.pdf-scansnap-no-text-ja-dense_table"
rung    = "CHECK"
origin_evidence = { scoreboard_epoch = "a91c4f2e/771be0", audited_n = 214, divergence = 0.147 }
created = 2026-08-29T11:04:00Z
expires = 2026-09-28T11:04:00Z         # a demotion is a hypothesis with a shelf life
when    = { "slice" = "pdf/scansnap/no-text/ja/dense_table" }
then    = { escalate_to = "PAGE", driver = "page.olmocr", reason = "auto-demote" }
```

**`auto_demote` can only demote** (R11). Asymmetry by design: an automatic demotion increases cost,
which the budget already bounds, and is reversible; an automatic *promotion* increases both cost risk
and quality risk and is not visible until a customer complains. Promotion is a human commit backed by
a `route simulate` run.

0.5% of a corpus is a real line item — 0.5% of a $10,000/month parse bill is $50/month producing no
customer-visible output — and it is off in `--profile cheap`. The honest consequence, printed by the
CLI when you select that profile: *"shadow audit disabled; the scoreboard will report UNKNOWN and
auto-demotion is inert."*

### 7.5 The `Scoreboard`

```sql
CREATE VIEW route_scoreboard AS
SELECT slice_key, rule_id, driver,
       COUNT(*)                                                   AS decisions_n,
       SUM(source='audit')                                        AS audited_n,
       AVG(CASE WHEN source='audit' THEN 1.0-agreement END)       AS divergence,
       AVG(CASE WHEN source='agree' THEN 1.0-agreement END)       AS escalation_divergence,
       SUM(source='feedback' AND polarity<0)                      AS complaints,
       SUM(cost_micros)                                           AS micros,
       CASE
         WHEN SUM(source='audit') < :min_audit_n                 THEN 'UNKNOWN'
         WHEN AVG(CASE WHEN source='audit' THEN 1.0-agreement END) > :regress_at THEN 'REGRESSED'
         ELSE 'OK'
       END                                                        AS state
FROM route_verdict v JOIN route_decision d USING (decision_id)
WHERE v.source IN ('agree','audit','feedback')     -- R9: never 'self'
  AND d.pinned = 0                                  -- pins excluded from numerators
GROUP BY slice_key, rule_id, driver;
```

`UNKNOWN` is the zero value and it is the default (R10). An operator opening the scoreboard on day one
sees a wall of `UNKNOWN`, which is the truth. Nothing in this system reports a driver as good because
nobody looked.

**Slices** are the accounting bucket, declared in policy, pure over evidence, and
cardinality-budgeted (`max_slices = 512`, checked by `route lint` against the declared domains). Coarse
on purpose: a slice function that can emit 200,000 buckets produces a scoreboard where every cell is
`UNKNOWN` forever, which is the failure mode this whole section exists to avoid.

### 7.6 Learning, bounded

Two learnable things, and nothing else:

1. **Thresholds on existing rules.** Given the decision log with evidence read sets and audit
   divergences, fitting `probe.ocr_error_p_bad`'s escalation threshold per slice is one-dimensional
   isotonic regression on `(threshold -> expected micros, expected divergence)` — solvable exactly, in
   seconds, offline, over the log. Output is a **proposed diff to `route.toml`**, printed for review,
   with the simulated deltas. Never applied automatically.
2. **Slice-level driver preference**, same shape, same review gate.

Rule *structure* is not learned. A learner that can invent predicates produces a policy no operator
can read, which forfeits the entire reason the policy is data.

---

## 8. Storage — the DDL

```sql
-- omniweave/route/schema.sql   (SQLite; identical DDL on Postgres for T3, per mine-runtime §7.10.2)
PRAGMA busy_timeout = 5000;     -- FIRST (codegraph #238: journal_mode before busy_timeout crashes)
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE route_decision (
    decision_id        TEXT    PRIMARY KEY,          -- 'dec_' || sha256(canonical(...))[:24]
    unit_uri           TEXT    NOT NULL,
    unit_part          TEXT    NOT NULL DEFAULT '',  -- '' folds NULL, per mine-runtime §7.3.1
    content_digest     TEXT    NOT NULL,
    policy_digest      TEXT    NOT NULL,
    pricebook_digest   TEXT    NOT NULL,
    evidence_digest    TEXT    NOT NULL,             -- over the READ SET only (R3)
    read_set           TEXT    NOT NULL,             -- JSON array of evidence keys consulted
    signal_versions    TEXT    NOT NULL,             -- JSON {key: version} for the read set
    rule_id            TEXT    NOT NULL,
    rule_origin        TEXT    NOT NULL,             -- 'project:.omniweave/route.toml:41'
    rung               TEXT    NOT NULL,
    lane               TEXT    NOT NULL,
    driver             TEXT    NOT NULL,
    slice_key          TEXT    NOT NULL,
    trigger            TEXT,                          -- 'probe.ocr_error_p_bad=0.71>=0.50'
    flagged_blocks     TEXT,                          -- JSON array of block ids (REPAIR)
    sequence_id        TEXT,                          -- non-null when part of a sequence binding
    parent_decision_id TEXT REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    est_micros         INTEGER NOT NULL DEFAULT 0,
    est_tokens_out     INTEGER NOT NULL DEFAULT 0,
    est_gpu_ms         INTEGER NOT NULL DEFAULT 0,
    audit_selected     INTEGER NOT NULL DEFAULT 0,   -- derived, not random (R2)
    canary_bucket      INTEGER NOT NULL DEFAULT 0,
    pinned             INTEGER NOT NULL DEFAULT 0,
    grant_id           TEXT,                          -- non-null iff bytes_egress > 0
    created_at         INTEGER NOT NULL
);
CREATE UNIQUE INDEX route_decision_identity
    ON route_decision(unit_uri, unit_part, rung, lane, policy_digest, evidence_digest);
CREATE INDEX route_decision_slice   ON route_decision(slice_key, rule_id, driver);
CREATE INDEX route_decision_audit   ON route_decision(created_at) WHERE audit_selected = 1;
CREATE INDEX route_decision_parent  ON route_decision(parent_decision_id);

-- The evidence blob is separate so it can be aged out independently of the decision.
CREATE TABLE route_evidence (
    evidence_digest TEXT PRIMARY KEY,
    payload         BLOB NOT NULL,        -- zstd(canonical JSON of the read set)
    first_seen_at   INTEGER NOT NULL,
    refcount        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE route_spend (
    decision_id   TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    attempt       INTEGER NOT NULL,       -- 1-based; REGEN rungs increment
    provider      TEXT NOT NULL DEFAULT '',
    wall_ms       INTEGER NOT NULL DEFAULT 0,
    cpu_ms        INTEGER NOT NULL DEFAULT 0,
    gpu_ms        INTEGER NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    calls         INTEGER NOT NULL DEFAULT 0,
    bytes_egress  INTEGER NOT NULL DEFAULT 0,
    micros        INTEGER NOT NULL DEFAULT 0,
    was_cache_hit INTEGER NOT NULL DEFAULT 0,
    would_have_been_micros INTEGER NOT NULL DEFAULT 0,   -- graphrag: metrics replayed on a hit
    outcome       TEXT NOT NULL,          -- Outcome enum, mine-runtime §7.1.2
    PRIMARY KEY (decision_id, attempt)
);

CREATE TABLE route_verdict (
    verdict_id  INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES route_decision(decision_id) ON DELETE CASCADE,
    source      TEXT NOT NULL CHECK (source IN ('self','agree','audit','feedback')),
    metric      TEXT NOT NULL,            -- 'norm_edit_agreement' | 'grounded_frac' | 'thumb'
    agreement   REAL,                     -- [0,1]; NULL for 'feedback'
    polarity    INTEGER,                  -- -1|0|+1 for 'feedback'
    ref_driver  TEXT,
    detail      TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX route_verdict_decision ON route_verdict(decision_id);

CREATE TABLE route_pin (
    unit_uri   TEXT NOT NULL,
    unit_part  TEXT NOT NULL DEFAULT '',
    lane       TEXT NOT NULL DEFAULT 'text',
    driver     TEXT NOT NULL,
    reason     TEXT NOT NULL,             -- required; route lint reports pins without one
    created_by TEXT NOT NULL,
    expires_at INTEGER,                    -- default now + 90d, set by the CLI
    PRIMARY KEY (unit_uri, unit_part, lane)
);
```

Retention: `route.retain_evidence_days` default 30, but rows that are `audit_selected`, `pinned`,
part of a `REGRESSED` slice, or referenced by an open `route_verdict` are never aged out. The decision
rows themselves are kept for `retain_decisions_days` default 400 (so year-over-year comparisons work);
they are 240 bytes without the evidence blob.

---

## 9. The ecosystem surface — a driver in an afternoon

This is where the design earns its prior.

```
drivers/my-ocr/
├── driver.toml            # §5.2 — capabilities, cost card, licence, requires
├── README.md              # generated skeleton; the conformance report is appended
├── NOTICE                 # required if any vendored artefact; checked by `driver check`
├── src/my_ocr/
│   ├── __init__.py
│   └── driver.py          # ONE class, ONE method
└── tests/fixtures/        # optional; the harness ships 12 of its own
```

```python
# the entire required surface
class Driver(Protocol):
    NAME: ClassVar[str]
    RUNGS: ClassVar[frozenset[Rung]]
    LANES: ClassVar[frozenset[str]]

    def probe(self) -> ProbeResult:
        """Run the SMALLEST REAL operation and return ok/unavailable + reason.

        Not an import check. A tesseract without the language pack, a CUDA torch that fails on
        first kernel launch, a pdfium that cannot open an encrypted PDF, and an Ollama client
        with no model pulled all import fine (mine-runtime §7.10.3 / LDR §6.5).
        """

    def run(self, unit: UnitRef, parts: Sequence[int], ctx: RunContext) -> DriverResult:
        """`parts` is a list because of sequence bindings. Never reads os.environ, getcwd,
        or a clock; everything arrives through ctx (mine-runtime §7.1)."""
```

```
$ omniweave driver scaffold my-ocr --rungs PAGE --lanes text
$ omniweave driver check ./drivers/my-ocr
  capability claims .................... 10/10 verified against emitted output
    charspan=false ..................... ok (no charspans emitted)
    tables=cells ....................... ok (per-cell provenance present on 4/4 table fixtures)
  cost card ............................ ok
    monotone in part_count ............. ok
    p95 tokens_out declared 3.4x, measured 3.1x .... ok  (fails above 4.25x)
  determinism .......................... ok (3 runs, identical output digests)
  network isolation .................... ok (egress=false; 0 sockets opened under the block hook)
  licence .............................. ok (Apache-2.0 code; weights pinned to b3f1c2d9; md5 not denied)
  resource discipline .................. ok (peak RSS 3.1 GB < declared 4 GB)
  fixture corpus ....................... 12/12 produced a document; 0 exceptions
  PASS  — appended report to drivers/my-ocr/README.md
```

Then the property that decides whether third parties actually show up:

**Installing a driver does not require editing the policy.** The shipped policy's last rule at each
rung is a capability dispatch:

```toml
[[rule]]
id      = "fallback.by-capability"
rung    = "PAGE"
comment = "An installed driver is usable at its declared rung immediately. Ranking it ABOVE a builtin is an explicit policy edit."
when    = { "request.prefer_capability" = { exists = true } }
then    = { driver = "$capability_match", reason = "capability-dispatch" }
```

So a new driver is reachable the moment it passes `driver check`, via
`route_hints.prefer_capability` or `--driver`, and it accrues `agree`/`audit` verdicts in the
scoreboard. Promoting it ahead of a builtin is a one-line `[[rule]]` in the project layer, backed by a
`route simulate` run over the log. **The driver author gets immediate usability; the operator keeps the
default path under explicit control.** That is the whole extensibility/safety balance in one rule.

Licence enforcement lives here because the router is the component that would otherwise silently
recruit a vetoed driver. `omniweave/route/licence_denylist.toml` ships with md5
`e1f69b64dee2f1641a9b1ab12adf24d6` (the byte-identical marker/surya/lift `MODEL_LICENSE`), and R13
refuses `weights_revision = "main"` outright — `grep -rn "revision=" marker/ surya/ lift/` returns
zero hits, so a policy naming those weights could never be reproducible even if it were licensed. The
shipped default policy therefore names `decode.anydoc`, `decode.pdftext`, `probe.ocr_error` (a
reimplemented classifier trained on permissive data, or the rung is simply absent) and `page.olmocr`
(Apache-2.0 code **and** weights). marker/surya/lift are installable drivers; their `driver.toml`
carries `licence_class = "restricted"`, and selecting one prints a one-line notice naming the clause.
We are not hiding the veto — we are making it visible at the only place a user could trip over it.

---

## 10. Budget enforcement and graceful degradation

Adopt `BudgetLedger` from `mine-runtime.md` §7.8.2 unchanged (reserve/commit/release/headroom,
hierarchical per-run / per-operator / per-provider / per-unit) and add three router-specific things:

1. **A per-part budget below the per-unit budget**, so a single runaway page cannot consume the
   document's allowance. The default `budget.per_part.tokens_out = 8_000` is one olmocr attempt.
2. **`on_exhausted` is an ordered ladder in the policy**, evaluated in order:
   - `spill_to_free` — re-route to the cheapest driver that can serve the lane at any rung ≤ current.
   - `partial` — return `ok_partial` for the remaining parts with a `Degradation`, and *keep* the parts
     already done (docling's `PARTIAL_SUCCESS` + per-page `ErrorItem`, never anydoc's all-or-nothing).
   - `defer` — leave the `work` rows claimable with `DEFERRED_BUDGET` and a pending-cost record; the
     next run with headroom completes them.
   - `refuse` — only when the policy explicitly asks for it.
3. **`Degradation` is a typed record on the result, and it is never silent** (R8):

```python
@dataclass(frozen=True, slots=True)
class Degradation:
    kind: Literal["budget", "signal_unavailable", "driver_unavailable",
                  "auto_demote", "pin", "grant_missing", "policy_pruned"]
    budget: Unit | None
    spent: int
    limit: int
    rung_reached: Rung
    wanted_driver: str | None
    parts_affected: tuple[int, ...]
    message: str            # operator-facing, names the knob that would raise the limit
```

`message` names the knob. `anydoc`'s `ResourceLimit{limit}` is the model: a limit hit should tell you
*which* knob would need raising, which turns an error into a pricing conversation. Concretely:
`"per_unit.micros exhausted at 20000/20000 after part 63/188; raise [budget.per_unit].micros or set
on_exhausted=['defer'] in .omniweave/route.toml"`.

And the serve-layer contract that must not be broken: **a budget-exhausted parse returns a
success-shaped response with a degradation banner, never `isError`.** `mine-serve.md`'s finding is
that one early `isError` teaches the agent the whole toolset is broken and it stops calling. Budget
exhaustion is the most common non-fatal condition this framework will ever produce; getting it wrong
poisons adoption on day one.

Every degradation also lands in the run manifest's `degradations[]` (`mine-runtime.md` §7.4.4) beside
`cost.would_have_been_micros_if_uncached`, so a monthly review can see how often the fleet ran
degraded — a number no repo in the collection can produce.

**Watcher safety, inherited and made explicit:** a filesystem or hook trigger may auto-run `FREE` and
(within headroom) `LOCAL_COMPUTE` rungs, and **never** `BILLED_API`. graphify does exactly this split —
`_batch_triggers_rebuild` runs the free AST rebuild, `_batch_needs_llm_flag` calls `_notify_only`
(`graphify/graphify/watch.py:2138,2170,2123`). A watcher that silently re-bills a VLM pass because
something touched a 400-page PDF's mtime ends a pilot. In the router this is one rule in the shipped
policy: `when = { "trigger.kind" = "watch" }, then = { max_cost_class = "LOCAL_COMPUTE" }`.

---

## 11. What this costs

**Engineering.** Policy parser + compiler + evaluator ≈ 1,200 LoC. Signal registry + demand planner ≈
450. Decision store + DDL + migrations ≈ 550. `route explain/replay/simulate/lint` ≈ 700. Conformance
harness + 12 fixtures ≈ 900. Scoreboard views + audit lane ≈ 500. Learner (isotonic + diff emitter) ≈
300. Total ≈ 4,600 LoC plus fixtures and docs: **one senior engineer, ~8 weeks**, of which the
conformance harness is 2 and is the part most likely to be cut and most costly to cut.

**Runtime overhead.** Evaluation is a walk over ≤ a few hundred interned atoms: measured target
**< 50 µs per part**, against a `DECODE` cost of ~2 ms and a `PAGE` cost of ~1.9 s. The decision row is
one INSERT, batched per page batch (docling's `page_batch_size = 4`), and the evidence blob is
deduplicated by digest. Budget: **≤ 2% of a 4-part batch's wall time**, enforced by a benchmark in CI
with a 5% drift gate (`jcodemunch`'s schema-budget test is the pattern).

**Storage.** Decision row ~240 B; compressed evidence read set ~600 B; spend row ~120 B. ~960 B/part
⇒ **~960 MB per million pages**, dropping to ~360 MB after the 30-day evidence sweep. Retention is a
policy knob and the sweep exempts audited, pinned and regressed rows.

**Dependency weight.** `tomllib` (stdlib 3.11+), `sqlite3` (stdlib), `blake2b` (stdlib). **Zero new
third-party dependencies in `omniweave-core`.** The Levenshtein used by `agree.decode_vs_page` is a
50-line DP over normalized text — no `rapidfuzz`, because it is called once per escalation, not per
token. This matters: `mine-risk.md`'s rule is that an L5 orchestration layer must never be a dependency
of an L1 parser, and the router sits exactly on that seam.

**Operational burden.** Two new files an operator owns (`route.toml`, `pricebook.toml`), one new CLI
noun (`route`), one new table group, one new CI job (`route simulate --gate`). The pricebook is the
genuinely new obligation — someone must keep GPU-hour and provider prices current, or every estimate
drifts. Mitigation: `route lint` warns when `pricebook.toml` is older than 90 days, and the shipped
file carries the published olmocr numbers with their citation so day one is not blank.

---

## 12. Failure modes — including the input that breaks it

1. **Policy sprawl and first-match shadowing.** 200 rules where rule 3 silently shadows rule 90.
   Mitigated by `route lint`'s interval subsumption and the cold-rule report; **not** fully mitigated —
   subsumption is incomplete over open string domains like `unit.producer_family`, and the linter says
   so. A 200-rule policy is still a policy nobody reads.
2. **Evidence drift makes history incomparable.** An operator upgrades the probe classifier; every
   stored `probe.ocr_error_p_bad` was produced by a different model. Replay reports `REPLAY_DRIFT`
   rather than lying, but the scoreboard's history is genuinely broken. There is no fix: the scoreboard
   is keyed by `(policy_digest, signal_versions_digest)` and a probe upgrade **starts a new epoch with
   `UNKNOWN` cells**. Honest cost of a model upgrade: your quality history resets. State it in the
   upgrade docs.
3. **The adversarial document.** A PDF where every page carries a text layer at `layout_coverage =
   0.24` and `probe.ocr_error_p_bad = 0.06` — just past both gates. Every page pays `PROBE` + `CHECK` +
   the per-block recheck + `PAGE`: the maximum-cost path on every page, ~$0.0128/page hosted with
   retries. The de-escalation rule (§2.4) catches the ≤64-part case; beyond that **the per-unit budget
   is the only defence**, which is exactly `mine-risk.md` §22.2's conclusion. It degrades to
   `ok_partial` at part 63 of 188 and says so. This is the input that breaks the design's *economics*,
   and the design's answer is to fail visibly and cheaply rather than to fail expensively.
4. **Slice explosion.** `format × producer × lang × page_class` fans out; every cell `UNKNOWN` forever.
   Mitigated by `max_slices = 512` checked against declared domains, but a policy author who adds
   `unit.producer_family` (30 values) × a new 20-value key blows the budget and `route lint` errors —
   which is annoying at exactly the moment they want more resolution. There is a real tension here and
   no clean answer; the design chooses "few filled cells" over "many empty ones".
5. **Shadow audit is a cost with no customer-visible output.** $50/month on a $10k bill. It is a line
   item, it is off in `--profile cheap`, and with it off the scoreboard is `UNKNOWN` and auto-demotion
   is inert. Some operators will turn it off and then be surprised the router "does not learn".
6. **Auto-demotion thrash.** A slice hovers at `divergence ≈ regress_at`; demotion rules appear and
   expire in a 30-day cycle, doubling that slice's cost half the time. Mitigated by hysteresis
   (`regress_at` to demote, `regress_at * 0.6` to let a demotion expire) and by `min_audit_n`, but a
   genuinely borderline slice will oscillate.
7. **Pins become the configuration.** Ops pins 4,118 documents "temporarily"; 31% of the corpus is
   outside the scoreboard. Mitigated by required `reason`, default 90-day `expires`, and a `route lint`
   coverage warning plus a `pinned_fraction` line in every run manifest. Not prevented — a determined
   ops team can re-pin forever, and the design deliberately lets them, because the alternative is an
   escape hatch that does not exist when they need it at 2 a.m.
8. **The laptop that has no `PAGE` driver.** The preflight capability probe prunes the policy and
   prints a report (never an `ImportError` at the bottom of a stack trace). The pruned policy has its
   own digest, so a laptop's decisions never claim to be the server's — but this means local and CI
   decisions are *not* comparable in the scoreboard, and `route simulate` on a laptop against
   server-produced decisions returns `REPLAY_DRIFT` for pruned rules. Correct, and confusing the first
   time it happens.
9. **`agree.decode_vs_page` measures agreement, not truth.** Two drivers sharing a base model family
   can be wrong identically, especially on a script neither was trained on. Its bias toward the
   escalated population is stated in the scoreboard column header, and the shadow audit exists
   specifically to cover the non-escalated population. Reading only the free column is a mistake the
   UI is designed to discourage but cannot prevent.
10. **The `Grant`/`dpa_ref` field is unvalidated free text.** Someone will type `"TODO"`. The control
    is that the string appears in every affected run manifest, so a compliance review finds it — a
    social control, not a technical one, and it is the honest limit of what the router can do.

---

## 13. Why I reject the alternatives

**Routing as code (a `route()` function with `if`s — marker's actual design).** It works, and marker's
implementation is the best in the collection. But: a threshold change is a release; a customer cannot
tune for their corpus; there is no way to answer "what would this change have done" without an online
experiment; and quality accounting has nothing to aggregate by, because the decision has no id. The
decisive argument is `route simulate`: 6.4M historical decisions re-evaluated in 41 s for $0 is
impossible against code, and it is the only mechanism that makes tuning a measurement instead of an
argument.

**Routing as an embedded expression language (CEL / Lua / Python `eval`).** More expressive, and it
forfeits everything: subsumption linting, threshold learning, and the safety of accepting a policy
from a customer's repo. `marker/marker/config/parser.py:73,79` + `convert_single.py:30,36` is the
concrete precedent — dotted-path import of `--converter_cls` and `--llm_service`, settable from
`--config_json`, i.e. RCE the moment config arrives in a request body. A closed comparison grammar
covers every rule in the collection's routers; I checked all eight ladders in `mine-parse.md` §B2 and
none needs arithmetic on more than one evidence key.

**A learned end-to-end router (a small classifier that picks the driver).** Attractive, and wrong for
this decision at this stage. It cannot be audited (`route explain` becomes "the model said so"), it
cannot be linted, it cannot be diffed in a PR, it needs labelled data the project does not yet have,
and its failure mode is a silent cost regression. Learning belongs *inside* the declarative frame:
fit thresholds, propose a diff, human commits (§7.6). When the scoreboard has real data across many
corpora, a learned *slice-level prior* becomes defensible as a proposal generator — still not as the
decision.

**Per-document routing (docling's `do_ocr` boolean).** docling computes the best per-page quality
signals anywhere — `parse_score`, `layout_score`, `ocr_score`, `table_score` at
`docling/docling/datamodel/base_models.py:417,486` — and consumes none of them, because `do_ocr` is a
document-level boolean. The signal and the router are one feature; shipping the signal without the
router is how you end up grading documents `EXCELLENT` on a `table_score` that is never computed.
Per-document routing on a 188-page 10-K means either paying for 188 VLM pages or accepting garbage on
the 12 scanned exhibits.

**Per-block routing as the primary unit.** Tempting for precision, refuted by measurement: one
full-page request is **~7×** faster than N block requests on llama.cpp
(`marker/marker/builders/ocr.py:80-82`), and tight crops lose the context that makes the model
accurate. Blocks are the right unit for a *flag* and the wrong unit for a *decision*, which is exactly
marker's `promote_fraction` insight — `0.0` in balanced mode, so any flagged block promotes the page
(`marker/marker/builders/line.py:468-481`).

**Budget as a retry count.** `olmocr/olmocr/pipeline.py:107,1221` is the counterexample and it is
decisive: `MAX_TOKENS = 8000` × `--max_page_retries` default 8 = 64,000 output tokens/page ⇒ $0.0128
at $0.20/1M, a **64× amplification** over its own $0.0002/page baseline — with the remaining retries
fired *in parallel* when the queue drains (`:343-350`) and `--max_concurrent_requests` defaulting to
**1600** (`:1224`). A retry count is not a cost bound, because the cost of a retry is not fixed. A
currency/token budget is, and `BudgetExceeded`/`DEFERRED_BUDGET` as a typed outcome makes exhaustion a
branchable fact rather than a surprise on an invoice.

**A single `--force` override.** Rejected on `mine-runtime.md` §7.6.3's grounds verbatim: an override
whose scope is "skip whatever check just complained" is an off switch. Named overrides cost more to
implement and are the difference between an operator who can safely unblock themselves and one who
disables the budget to get past a lint warning.

**Trusting driver-reported confidence for quality accounting.** Rejected because four repos
demonstrate the failure: docling grades on an uncomputed score, `lift` prints and drops
`response_format` on schema-compile failure, `Unlimited-OCR` writes `""` for a page that failed 5
retries, `surya`'s `create_model_dict(device=...)` ignores its argument. Self-report gates escalation
(cheap, useful, R9 permits it) and never populates the scoreboard.

**Numbered tiers (the blueprint's `tier 0..3` + `tier S`).** Overturned in §2.1: a number cannot
express a cheap high-capability driver or an expensive low-capability one, and it is the wrong join key
for a scoreboard. `(rung, lane, driver)` + a capability declaration is one more field and it makes
"which drivers can serve this request" a query instead of a convention.

**`lift`'s schema shortcut as a bypass ("skip everything else").** Overturned in §7.3 on its own
published numbers: **90.2% per field, 20.9% full-document**. The free text layer is the cheapest
grounding signal in existence and the schema lane must not throw it away.
