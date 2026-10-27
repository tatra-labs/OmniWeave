# D8-out — The OUT compiler contract and closing the loop (SHIPPING PRAGMATIST)

## Headline

**There is no omniweave IL. There are per-target ILs — each a closed subset of an existing text
format that already has a proven compiler in `_collections/` — and the framework owns one thing
instead: the *IL discipline*, expressed as a machine-readable `constructs.toml` per target that is
simultaneously the validator's rule source, the compatible-input normalizer registry, the
documentation, and the test plan.** A Target is a Driver on D3's `compile/1` port plus a
`parse_back` Driver on `parse/1`, both reading and writing D1's job directory. The framework
supplies findings, the nine-value gate bound to a byte fingerprint, the asset ledger, the
element-addressed feedback protocol, `manual_required`, the fidelity-tier assertion and the
conformance kit; each target supplies its construct table, its rules, its compiler and its
`parse_back`. First three targets: **`pptx` (pure Python, the flagship, the only target in the
collection with a real `parse_back`), `docx` (pure Python, cheapest possible second target, proves
the framework generalizes with zero new runtime), `deck` (first Toolchain, HTML IL that is the
direct precursor of video)** — and **video is fourth, not third**, because `mine-out.md`'s PART 3
on hyperframes *was never written* (digest-out.md says so in its first paragraph) and designing
target #3 on the one OUT repo nobody mined is exactly the speculative generality this panel should
refuse.

---

## 1. Consistency with the upstream rulings, and where the seams are

I re-litigate nothing. Two places need an explicit reading, and one place needs a one-clause
amendment request. All three are stated up front so the judge can rule on them.

**1.1 `omniweave.targets` (D1) vs `compile/1` Drivers (D3) — a seam, not a conflict.**
D1 fixes an entry-point group `omniweave.targets` keyed by artefact kind (`pptx`, `docx`, `deck`,
`video`), an `omniweave.toml [targets] enabled` list, and per-target option tables. D3, ruled later,
makes `compile/1` a Port and rules that D8 "gets `compile/1`, `capability.compile.*`, `parse_back`
as a named `parse/1` driver id on the card". Both hold, at different layers:

* `omniweave.targets` is the **artefact-kind alias layer**. Its entry-point value is a dotted
  package path (D3's mandatory form — a path-shaped value fails `setuptools._entry_points.validate`
  at build time) containing `target.toml`. `target.toml` declares the artefact kind, the IL id, the
  reproducibility class, the realization table, the round-trip loss declaration, and the two driver
  ids behind it.
* `omniweave.drivers` carries the actual code: `compile.pptx.native` and `parse.pptx.native`, each
  its own sub-package with its own `driver.toml` (D3: one driver per card file).
* **`[targets] enabled` is not a bypass of D3.** Both gates apply: the artefact kind must be enabled
  *and* the compile driver must survive `resolve()` — tier, ack, lockfile, attestation, probe.

Why two files rather than folding the construct table into `driver.toml`: D3 measured
`entry_points(group=…)` at **15.3 ms** for 328 distributions with a **1.01 ms** `scandir`+`stat`
validity key, and the catalog parses every card on a cold scan. A construct table is 200–400 rows.
Putting it in `driver.toml` inflates every discovery scan for data only the validator reads.
`target.toml` and `constructs.toml` are read on demand, by name, from the same package.

**1.2 `provenance` and `severity` are orthogonal — and D1's own wire frame already says so.**
ppt-master conflates them: its four provenance categories are `blocking / introduced / inherited /
source-import`, where `blocking = len(errors)` and `introduced = len(warnings)`
(`ppt-master/skills/ppt-master/scripts/svg_quality/checker.py:9192-9230`). D1's
`omniweave-target/1` example frame emits `{"code":"OW-T-311","severity":"error",
"provenance":"introduced", …}` — a severity *and* a provenance on one finding, which is only
coherent if the two axes are independent. I take D1's reading and fix ppt-master's:
`severity ∈ {error, warning, info}` decides **whether it blocks**;
`provenance ∈ {introduced, inherited, imported, framework}` decides **who owns it, which fix command
prints, and whose count it inflates**. An inherited *error* still blocks (the template is genuinely
invalid) but the message names the template and the fix command targets the template. An inherited
warning never blocks and never enters the generated-quality count — which is the whole point
ppt-master was making.

**1.3 Amendment requested (minimal, additive, D2).** `rebind()` should gain **rule 0**: *equal
`x.omniweave.el` under the same `doc_ord` carries the `block_id`*, evaluated before D2's existing
rules 1–3, and only for documents whose `achieved.round_trip != "none"`. Without it, re-importing a
deck whose slides were **reordered** trips D2's quarantine on every page, because D2's `addr` is
`p{page}/{ord}` and rule 2 keys on `addr` + `kind`. With it, a reorder carries every `block_id`
exactly. The clause cannot fire on any document that does not carry the key, so it is inert for
every parse driver shipping today. This is a one-line addition, not a re-litigation: D2's own open
question #2 ("Will an editing surface ever mutate a stored generation in place… settled by D9's
[sic] ruling on whether `parse_back()` and OUT-direction edits write a new `gen`") explicitly defers
this to me, and **my ruling is: `parse_back` always writes a new `gen`, never patches one.**

**1.4 Two additive additions to D1's layout**, both of which D1's own gates price without change:

* `omniweave_core/out/` — `finding.py`, `gate.py`, `fingerprint.py`, `ledger.py`, `constructs.py`,
  `report.py`, `feedback.py`. Stdlib only (`dataclasses`, `enum`, `hashlib`, `json`, `tomllib`,
  `base64`, `re`); no XML parsing in core (that lives in each target, which owns its IL syntax), so
  gate **G1** (core resolves to exactly one distribution) and **G9** (`import omniweave_core` loads
  zero third-party modules) both hold unchanged.
* A twelfth distribution, `omniweave-target-docx` (`core`, `python-docx`, `lxml`; ceiling 20 MB).
  D1's "eleven" is a count of the day-one set, not a cap; adding a row touches
  `tools/weights.toml`, `[tool.uv.workspace]` and G5's version-agreement list, all of which are
  per-row mechanisms. `omniweave[recommended]` is unchanged (it does not include docx).

Everything else here uses D1/D2/D3/D4 names verbatim: `job_dir`, `omniweave-target/1`,
`ToolchainSpec`/`ToolchainResult`, `Outcome`, `OW-T-nnn`, `codes.toml`, `DocSink`, `Block`,
`BlockId`, `addr`, `cite`, `content_digest`, `layout_digest`, `OriginNodePath`, `OriginBytes`,
`Quad.from_driver`, `Capabilities`, `Producer`, `Diag`, `restriction_bits`, `origin_driver`,
`DriverIO`, `DriverResult`, `Requirement`, `Resolution`, `Spend`, `degradations[]`.

---

## 2. What an IL is here

**An IL is a closed subset of an existing text format, plus a construct table that names every
allowed construct, its state, its canonical spelling, its target mapping and its finding code.**
Not a schema. Not a grammar we invent. Not a projection of L2.

Three reasons, each checkable:

1. **All three OUT repos converged on seven mechanisms and on zero shared IL.** `mine-out.md` §0's
   convergence table: the closed authoring surface is *"project-canonical SVG subset"* (ppt-master),
   *"fixed 1920×1080 canvas + `Page` component contract"* (open-slide), *"HTML + closed `data-*`
   timing attribute set"* (hyperframes). Three teams solved the same *meta* problem three ways and
   the *object-level* problem three genuinely different ways, because a slide deck of native
   DrawingML objects, a flowing document and a seekable timeline are not the same kind of thing. An
   abstraction over all three that is loose enough to hold video is loose enough to constrain
   nothing — which is exactly the failure the brief names.
2. **A universal IL would force the wrong thing into L2.** D2 forbids any model class from declaring
   an `html`, `markdown` or `md` field, and its rationale generalizes: L2 is a *parse* model
   (reading order, provenance, spans, trust). A slide carries z-order, transforms, gradient stops,
   `mix-blend-mode` and shape-boolean operands. Pushing those into `Block.payload` corrupts the
   pivot for the benefit of one direction.
3. **We already own the mapping evidence for exactly one of them.** ppt-master's `svg_to_pptx`
   package (`drawingml/`, `native_objects/`, `pptx_package/`, `use_expander.py`,
   `tspan_flattener.py`, `shape_boolean.py`) is the only working closed-subset→native-object
   compiler in `_collections/`, and its dependency set is exactly D1's declared
   `omniweave-target-pptx` deps: `python-pptx>=0.6.21`, `XlsxWriter>=3.0.0`, `skia-pathops>=0.9.2`,
   `uharfbuzz>=0.50.0`, `Pillow>=9.0.0` (`ppt-master/skills/ppt-master/requirements.txt`). D1 read
   that file. Writing a new IL and a new compiler discards it.

### 2.1 The construct table is the test plan

This is the single generalization that earns its keep, and it is D3's "the card is the test plan"
applied one level down. `constructs.toml` is read by four consumers and written once:

| consumer | what it reads |
|---|---|
| validator | `state`, `select`, `rule`, `code`, `severity`, `normalize` |
| compiler | `maps_to`, `normalize` |
| docs generator | `canonical`, `reason`, `fix` (renders the IL reference; nothing is hand-written) |
| `omniweave-conform` OUT suites | every row, **in both directions** |

The meta-gate (`ow out lint --table`, CI gate **G-OUT-2**) asserts:

* every code any rule can emit is declared on some row, and every declared code is emitted by at
  least one fixture (both directions — D3-12's rule);
* every `state = "canonical"` row has a non-empty `maps_to`;
* every `state = "compatible"` row names a registered normalizer, and that normalizer passes
  `n(n(x)) == n(x)` and `sha256(compile(x)) == sha256(compile(n(x)))` as property tests;
* every `state = "invalid"` row has a fixture the validator refuses;
* every `state = "bake"` row has a fixture that blocks *and* a fixture that passes after baking;
* the compiler's dispatch table, enumerated at import, is exactly the set of `canonical` +
  `compatible` rows — a mapping in code with no row fails the build, and a row with no mapping fails
  the build.

That last bullet is what makes "the checker and the compiler share one parser" mechanical rather
than cultural. ppt-master achieves it socially, by having `svg_contracts.py` import ~40 symbols from
`svg_to_pptx.*` behind `try/except ImportError` with a warning fallback; verified at
`ppt-master/skills/ppt-master/scripts/text_measure.py:36-37`, which imports
`estimate_single_line_text_frame_width` from `svg_to_pptx.drawingml.elements` so the checker's
overflow estimator *is* the compiler's. In omniweave the validator and the compiler are modules of
one distribution, so there is no `ImportError` branch and no degradation path: **one implementation
of "what does `fill=` mean", enforced by the layer graph (D1 gate G4) rather than by a comment.**

---

## 3. Concrete shape

### 3.1 Directory and distribution layout

```
packages/
├── omniweave-core/src/omniweave_core/
│   └── out/                       STDLIB ONLY — the framework half of the OUT contract
│       ├── finding.py             Finding · Severity · Provenance · fold()
│       ├── constructs.py          ConstructTable · load() · ConstructState · Normalizer registry
│       ├── rules.py               RuleSpec · RuleRunner (ordering, scope, bail-on-parse-failure)
│       ├── gate.py                GateStatus (9) · gate_status() · ReportStatus (3)
│       ├── fingerprint.py         source_fingerprint()  — ONE implementation (see §3.5)
│       ├── ledger.py              AssetLedger · LedgerRow · resolve()
│       ├── feedback.py            Marker grammar · b64url · plan/apply/verify
│       ├── manual.py              ManualRequired · Realization
│       ├── receipt.py             Receipt schema types
│       └── job.py                 JobDir layout · job.json writer/reader
│
├── omniweave-target-pptx/src/omniweave_target_pptx/       IL owsvg/1     pure Python
│   ├── target.toml                artefact/IL/repro/realization/roundtrip-loss
│   ├── il/                        parse.py model.py addr.py  ← imported by BOTH rules/ and compile/
│   ├── constructs.toml            ~180 rows
│   ├── rules/                     one rule per file, one test per file  (NOT a 9368-line class)
│   ├── measure.py                 uharfbuzz shaping; SHARED with rules/overflow.py
│   ├── compile/                   driver.toml  →  compile.pptx.native
│   │   ├── driver.py  dispatch.py  drawingml/  charts.py  boolean.py
│   │   └── opc.py                 THE deterministic OPC writer (§3.6)
│   └── parse_back/                driver.toml  →  parse.pptx.native
│       └── driver.py  intake.py  fidelity.py
│
├── omniweave-target-docx/src/omniweave_target_docx/       IL owmark/1    pure Python
│   ├── target.toml  constructs.toml (~70 rows)  il/  rules/  compile/  parse_back/
│
├── omniweave-target-deck/src/omniweave_target_deck/       IL owdeck/1    Toolchain manifest
│   ├── target.toml  constructs.toml (~90 rows, SHARES owmark/1's element closure)
│   ├── il/                        the shared XHTML-subset parser (imported from docx target? NO —
│   │                              vendored as omniweave_core.out has no XML; see §7 note)
│   └── toolchain.toml             ToolchainSpec(name="deck", sha256=…, entry=("dist/deck.mjs",))
│
└── omniweave-conform/src/omniweave_conform/suites/out/
    ├── table.py  findings.py  gate.py  determinism.py  ledger.py
    ├── fidelity.py  roundtrip.py  feedback.py  manual.py  restrictions.py
    └── corpus/                    golden IL + golden artefacts, per target
```

### 3.2 `target.toml`

```toml
# packages/omniweave-target-pptx/src/omniweave_target_pptx/target.toml
target_schema = 1

[target]
artefact       = "pptx"                    # the omniweave.targets entry-point name
il             = "owsvg/1"
il_syntax      = "xml"                     # xml | html | text  — picks the marker grammar
media_type     = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
unit           = "slide"                   # the addressable output unit; "section" for docx
compiler       = "compile.pptx.native"     # a driver id resolved through D3's resolve()
parse_back     = "parse.pptx.native"       # a parse/1 driver id; omit ⇒ round_trip = none
toolchain      = ""                        # "" ⇒ in-Python; else a ToolchainSpec name

[capability.compile]
measure            = "estimator"           # none | estimator | browser  → gates overflow findings
bake               = "none"                # none | raster  → PPTX HAS NO RASTERIZER (§4.3)
assets             = "embed"               # embed | reference
provenance_embed   = "custom_part"         # custom_part | inline | sidecar_only
feedback_from_artefact = "comments"        # none | notes | comments
page_plan          = true                  # can reorder/duplicate units on export

[reproducibility]
class = "byte_exact"                       # byte_exact | normalized_exact | frame_exact | none
basis = ["python-pptx", "XlsxWriter", "skia-pathops", "uharfbuzz", "Pillow", "cpython"]

[roundtrip]
tiers   = ["passthrough", "cloned_passthrough", "patched", "rebuilt"]
capabilities = "parse_back/driver.toml"    # the D2 Capabilities block lives on the driver card

# EVERY loss must be declared here. The conform suite asserts observed_loss ⊆ declared_loss
# AND that every declared row has a fixture in which the loss actually occurs. (§6.3)
[[roundtrip.lossy]]
construct = "animation.entrance"
loss      = "timing_curve"
reason    = "owsvg expresses trigger+preset; PowerPoint's per-point Bezier is not authored"
fixture   = "corpus/pptx/anim-bezier.pptx"

[[roundtrip.lossy]]
construct = "text.autofit"
loss      = "normalizer"
reason    = "normAutofit fontScale is recomputed from measure.py, not carried"
fixture   = "corpus/pptx/autofit.pptx"

# ppt-master's content-family → realization → boundary table, as data.
[[realization]]
family     = "editable_text"
default    = "native_text"
boundary   = "exact visible wording, line grouping, alignment, emphasis"
on_failure = "manual_required"

[[realization]]
family     = "data_graphic"
default    = "native_chart"
alt        = ["native_table", "source_graphic"]
boundary   = "every value, label, relationship and geometry preserved"
on_failure = "manual_required"
```

### 3.3 `constructs.toml` — the IL, as data

```toml
# packages/omniweave-target-pptx/src/omniweave_target_pptx/constructs.toml
constructs_schema = 1
il = "owsvg/1"
unknown_construct = "invalid"          # FAIL CLOSED. There is no permissive mode.
ignore = ["svg:desc", "svg:title", "svg:metadata", "ow:*"]

# ── canonical ───────────────────────────────────────────────────────────────
[[construct]]
id        = "paint.fill"
select    = "@fill"                    # closed selector grammar: element / @attr / element/@attr
state     = "canonical"
canonical = "uppercase #RRGGBB | none | url(#id)"
maps_to   = "a:solidFill/a:srgbClr@val"
rule      = "paint"
code      = "OW-T-410"                 # the code emitted when the value does NOT parse

[[construct]]
id        = "text.font-size"
select    = "@font-size"
state     = "canonical"
canonical = "finite unitless px, e.g. font-size=\"24\""
maps_to   = "a:rPr@sz"
rule      = "typography"
code      = "OW-T-412"

# ── compatible: one documented alias, one deterministic normalization, warn, NEVER generate ──
[[construct]]
id        = "paint.fill.lowercase-hex"
of        = "paint.fill"
state     = "compatible"
normalize = "upper_hex"                # registered in omniweave_target_pptx.normalizers
code      = "OW-T-210"
severity  = "warning"
canonical = "#RRGGBB with uppercase hex digits"

[[construct]]
id        = "paint.fill.transparent-keyword"
of        = "paint.fill"
state     = "compatible"
normalize = "transparent_to_none"
code      = "OW-T-211"
severity  = "warning"
canonical = "fill=\"none\""

# ── bake: expressible only as a raster; a DETERMINISTIC degradation, not a refusal ──
[[construct]]
id       = "style.mix-blend-mode"
select   = "@style/mix-blend-mode"
state    = "bake"
bake     = { to = "raster", needs = "capability.compile.bake" }
code     = "OW-T-311"
severity = "error"
fix      = "ow out assets bake <el>   # or remove the property"

# ── invalid: no mapping, ambiguous, or a structural-contract break ──
[[construct]]
id       = "element.script"
select   = "svg:script"
state    = "invalid"
code     = "OW-T-401"
severity = "error"
reason   = "no DrawingML mapping; executable content in an authored artefact"

[[construct]]
id       = "attr.id-with-style"        # CONDITIONAL prohibition — the hazard is the PAIR
select   = "@id"
state    = "invalid"
when     = "document has svg:style"    # closed predicate vocabulary, 6 forms
code     = "OW-T-402"
severity = "error"
reason   = "id is required inside <defs>; it is only hazardous when CSS selectors exist"
```

The three tiers plus the `bake` middle are lifted verbatim from
`ppt-master/skills/ppt-master/scripts/svg_quality/svg_contracts.py:180-188`:
`_SUPPORTED_INLINE_STYLE_PROPERTIES` (29 members), `_BAKE_REQUIRED_VISUAL_PROPERTIES`
(`backdrop-filter`, `isolation`, `mix-blend-mode`), `_SHARED_FAIL_CLOSED_STYLE_PROPERTIES`
(`mask`). The conditional `id`-with-`<style>` prohibition is verbatim from the same module's
comment. **`bake` is the tier most designs miss** — a construct the target cannot express but which
has a deterministic degradation — and it is a *state*, so it is a table row, so it is testable.

### 3.4 Findings and rules

```python
# omniweave_core/out/finding.py — stdlib only
class Severity(StrEnum):    ERROR="error"; WARNING="warning"; INFO="info"
class Provenance(StrEnum):
    INTRODUCED="introduced"   # the generator authored this node
    INHERITED="inherited"     # byte-identical in the prototype/template it derives from
    IMPORTED="imported"       # arrived through a tolerant parse_back import
    FRAMEWORK="framework"     # omniweave itself (a skipped check, a probe shortfall)

@dataclass(frozen=True, slots=True)
class Finding:
    code: str                       # OW-T-nnn; MUST be in codes.toml (D1, append-only)
    severity: Severity
    provenance: Provenance
    at: str                         # "il/p03.svg:41:9"   — D1's omniweave-target/1 field
    msg: str
    el: str | None = None           # data-ow-el address of the owning element
    construct: str | None = None    # constructs.toml row id
    canonical: str | None = None    # the exact replacement text, for a compatible finding
    fix: str | None = None          # the exact command that clears it
    count: int = 1                  # folded occurrences
    examples: tuple[str, ...] = ()  # AT MOST 3 `at` strings   (ppt-master's remember_example)

def fold(fs: Iterable[Finding]) -> tuple[Finding, ...]:
    """Group by (code, construct, canonical); sum count; keep <= 3 examples.
    A page with 200 lowercase hex colours yields ONE recommendation, not 200."""
```

```python
# omniweave_core/out/rules.py
ILNode = TypeVar("ILNode")                # opaque to core; the target owns its node type

@dataclass(frozen=True, slots=True)
class RuleSpec(Generic[ILNode]):
    id: str
    order: int                            # the ORDER ENCODES DEPENDENCIES (ppt-master §1.2.3)
    scope: Literal["document", "unit", "node"]
    codes: frozenset[str]                 # every code this rule MAY emit — G-OUT-2 checks it
    needs: frozenset[str] = frozenset()   # e.g. {"measure"}; unmet ⇒ a FRAMEWORK info finding,
    fn: Callable[["ILContext", ILNode], Iterable[Finding]] = ...   # never a silent pass

class RuleRunner:
    """order 0 is ALWAYS the syntax parse and it SHORT-CIRCUITS. Everything after it assumes a
    parsed tree; running text-level rules over unparseable input emits nonsense
    (ppt-master checker.py:1253 comment 0, verbatim)."""
    def run(self, ctx: ILContext, stage: Stage) -> ValidateReport: ...
```

One rule per file, one test per file, signature `(ctx, node) -> Iterable[Finding]`, no shared
mutable state. This is the explicit rejection of ppt-master's packaging: **9,368 lines in one
`SVGQualityChecker` class** (`svg_quality/checker.py`) with 1,121 lines of stateless contract
functions beside it in `svg_contracts.py`. We take the second shape for everything.

### 3.5 The gate — nine values, one of which proceeds

```python
# omniweave_core/out/gate.py
class GateStatus(StrEnum):
    NOT_PROVIDED       = "not-provided"        # you never ran the gate
    UNREADABLE         = "unreadable"          # the report exists and will not parse
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    NON_FINAL          = "non-final"           # an early/unit report cannot release
    UNVERIFIED         = "unverified"          # no fingerprint, or a malformed count
    FAILED             = "failed"              # blocking findings
    STALE              = "stale"               # the IL bytes changed since validation
    RESTRICTED         = "restricted"          # D3-17: cited blocks carry disallowed restriction_bits
    PASSED             = "passed"

class ReportStatus(StrEnum):
    PASSED="passed"; PASSED_WITH_WARNINGS="passed-with-warnings"; FAILED="failed"

def gate_status(report: Mapping[str, Any], live_fingerprint: Mapping[str, Any],
                policy: "Policy") -> tuple[GateStatus, int]: ...
```

`NOT_PROVIDED ≠ FAILED` — "you never ran the gate" and "you ran it and it found errors" are
different user errors and get different messages. `RESTRICTED` is my ninth value and it is where
D3-17 lands: the compile host refuses an artefact whose IL cites blocks with disallowed
`restriction_bits`, and the message names the offending `cite` tokens.

Every failure message names the status **and prints the exact command that clears it**:

```
Error: `ow out compile --target pptx` requires a passing final report for the current il/;
       found `stale` (2 of 12 IL files changed after validation).
Run:   ow out validate ./il --target pptx --stage final --json
```

**Fingerprint — one implementation, not two.** ppt-master deliberately has the checker
(`checker.py:9335-9368`) and the exporter (`pptx_package/cli.py:1223-1240`) each compute
`_svg_source_fingerprint` independently, so divergence surfaces as `stale`. I overrule that and keep
D1's "no second implementation of anything": the drift ppt-master's design actually catches is
*temporal* (the files changed between validate and compile), not implementational, and a second
implementation only adds a way for the two to disagree about a file neither read wrong. So:

```python
# omniweave_core/out/fingerprint.py — the ONLY implementation
def source_fingerprint(paths: Sequence[Path]) -> dict:
    """Bind a report to the exact IL bytes. Sorted by BASENAME (a moved project must not change
    the digest). `name \\0 sha \\n` framing (no delimiter collision). An unreadable file
    contributes the literal 'unreadable' PLUS an error row — it never silently drops out."""
```

The compiler calls the same function over the files it is about to compile and compares
`(algorithm, digest, file_count)`. Everything else is ppt-master's, copied exactly.

### 3.6 Determinism and byte-reproducible output

`reproducibility.class` is declared per target and each value has a matching CI gate.

| class | meaning | gate **G-OUT-3** |
|---|---|---|
| `byte_exact` | two compiles of the same `job_digest` produce one `sha256` | compile each golden fixture twice on {ubuntu, macos, windows} × {3.11, 3.12, 3.13} (D1's existing matrix), assert one digest across all 18 runs |
| `normalized_exact` | identical after a declared, tested canonicalizer | same, comparing `canonicalize(bytes)`; the canonicalizer is target code with its own tests |
| `frame_exact` | decoded frames identical at sampled times | decode at `t ∈ {0, 0.5·d, d−ε}` + 8 deterministic samples, assert per-frame sha256 of the RGB planes |
| `none` | refused at registration | — |

`pptx` and `docx` are **`byte_exact`**. `deck` is `byte_exact` with `sourcemap: false`. `video`
(target 4) is **`frame_exact`** and nothing better is honest: libvpx/x264 output depends on thread
count and CPU feature detection, so a byte claim would be a lie the receipt cannot support.

What `byte_exact` costs, concretely, for OOXML:

```python
# omniweave_target_pptx/compile/opc.py
DETERMINISTIC_ZIP = dict(date_time=(1980, 1, 1, 0, 0, 0), compress_type=ZIP_DEFLATED, compresslevel=6)

# 1. members written in one canonical order: [Content_Types].xml, _rels/.rels, then
#    every part sorted by partname; never dict/insertion order.
# 2. docProps/core.xml: dcterms:created == dcterms:modified == clock_ns from job.json
#    (0 ⇒ 1980-01-01T00:00:00Z), cp:revision = 1, cp:lastModifiedBy = "".
# 3. NO w:rsid* (DOCX), NO p14:creationId, NO random shape GUIDs. Shape ids come from a
#    deterministic per-slide counter seeded at 2.
# 4. Geometry is EMU INTEGERS ONLY. A float never reaches the XML — which is also why D2's
#    Quad is i32 in 1/1000 pt: a float bbox makes any digest libm- and platform-dependent.
# 5. XML: lxml with a fixed nsmap ordering, no pretty-printing, UTF-8, standalone="yes".
# 6. Shaping (uharfbuzz) and boolean ops (skia-pathops) are deterministic per version, so the
#    versions are exact-pinned in the distribution AND recorded in receipt.reproducibility.basis.
```

`job.json` carries `determinism: {seed: 0, clock_ns: 0}` — D1's `hello` frame already defines those
fields, and the in-Python compiler reads them from `job.json` rather than from the wire, so the two
paths are configured identically.

### 3.7 The job directory (D1's layout, filled in)

```
<cache_root>/jobs/<run_id>/<unit_digest>/
├── job.json                      schema/job-v1.json  (D1) — extended below
├── il/
│   ├── deck.toml                 the roster: unit order, canvas format, masters
│   ├── p01.svg  p02.svg  …       one file per output unit
│   └── brief.md                  the FROZEN brief (§3.10)
├── assets/
│   ├── ledger.jsonl              one row per frozen asset, append-only
│   └── cas/ab/cd/<sha256>        the frozen bytes; hardlinked from the store CAS when possible
└── out/
    ├── validate-final.json       THE ONLY file the gate reads
    ├── validate-early.json       distinct filenames per stage, so no diagnostic run can
    ├── validate-unit.json        ever produce the release gate's report
    ├── trace.json                per-unit conversion trace (normalizations applied)
    ├── receipt.json              schema/receipt-v1.json (D1)
    └── <artefact>                deck.pptx
```

```jsonc
// job.json  — D8 owns everything inside it (D1 consequence)
{"schema":1, "kind":"compile", "target":"pptx", "il":"owsvg/1",
 "run_id":"01JBQ…", "unit_digest":"…", "artefact":"out/deck.pptx",
 "determinism":{"seed":0,"clock_ns":0},
 "limits":{"wall_ms":600000,"rss_bytes":4294967296,"out_bytes":2147483648,
           "max_units":500,"max_il_node_bytes":1048576},
 "gate":{"report":"out/validate-final.json","required":true},
 "assets":{"ledger":"assets/ledger.jsonl","root":"assets/cas"},
 "page_plan":"il/page_plan.json",
 "provenance":{"corpus_id":"…","embed":"custom_part"},
 "policy":{"allow_restriction_bits":0,"licence_tiers":["open"]},
 "options":{"format":"ppt169"}}
```

### 3.8 The asset ledger

The ledger is **not a new asset store.** D2 already defines an `asset` table with `sha256`,
`store_ref = cas://ab/cd/<sha256>`, `licence`, `licence_url`, `spdx`, `source_url`,
`retrieved_at_ns`, and a `block_asset` link with a `role`. The OUT ledger is a per-job *projection*
of those rows plus rows for assets that were generated or fetched during authoring.

```jsonc
// assets/ledger.jsonl — one JSON object per line, append-only
{"ref":"a7","sha256":"9f2c…","media_type":"image/png","bytes":184320,"w":1600,"h":900,
 "origin":{"kind":"store","asset_id":4412,"doc_ord":7,"origin_part":"ppt/media/image3.png"},
 "licence":{"spdx":"CC-BY-4.0","url":"https://…","attribution_required":true},
 "restriction_bits":0,
 "producer":null,
 "usage":[{"el":"p03/e17","role":"image","w_emu":5486400,"h_emu":3086100},
          {"el":"p11/e04","role":"image","w_emu":2743200,"h_emu":2057400}],
 "usage_count":2,
 "display_ratio_variants":[1.7778,1.3333]}
```

`display_ratio_variants` is ppt-master's `_manifest_entry` field
(`source_to_md/ppt_to_md.py:839-1014`) and it is kept because two ratios for one image means the
deck is *stretching* it — something the compiler must know before re-placing it. `origin.kind ∈
{store, generated, fetched, local}`; a `generated` row carries D2's full `Producer` tuple so a
re-render is reproducible, and `"main"` as a `model_rev` is a card error (D2/D3).

Invariants, and this is where I go further than any of the three repos:

* **O9 — no compile may reference an asset that is not a ledger row.** `AssetLedger.resolve(ref) ->
  Path` is the only resolver; a raw filesystem path or a URL in the IL is `OW-T-501` *invalid*, and
  a semgrep rule bans `open(`/`Path(` on any IL-derived string inside `compile/`. ppt-master only
  *warns* about external image references in its portability audit
  (`pptx_package/cli.py:1388-1535`, `resources.images.external_references`). Making it structurally
  impossible is strictly better and costs one indirection.
* Every row carries `licence.spdx`. A row whose SPDX is on D1's `tools/licences.toml` denylist, or
  whose `restriction_bits` policy disallows, makes the gate `restricted`.
* **`data:` URIs in the IL are `OW-T-502` invalid.** The IL is text; blobs live in `assets/`. This is
  what keeps the IL diffable, keeps `omniweave-target/1`'s stdout under 1 MiB, and keeps
  `source_fingerprint` meaningful.

### 3.9 Element-addressed feedback

Generalized from open-slide's `@slide-comment` (`packages/core/src/editing/comments.ts:5-8`), whose
four mechanics I adopt intact: **marker presence is the state**, base64url payload, position-derived
line number, reverse-order application, skip-is-legal.

```
owsvg  (xml)   <!-- @ow-comment id="c-1a2b3c4d" ts="2026-09-01T12:04:00Z"
                    el="p03/e17" anchor="sha256:7c3f…" text="<base64url(JSON)>" -->
owmark (html)  <!-- @ow-comment … -->
owdeck (html)  <!-- @ow-comment … -->

MARKER_RE = r'@ow-comment\s+id="(c-[a-f0-9]{8})"\s+ts="([^"]+)"\s+el="([^"]+)"\s+'
            r'anchor="sha256:[0-9a-f]{64}"\s+text="([A-Za-z0-9_-]+={0,2})"'
```

base64url, not escaping, for the same reason open-slide gives: arbitrary user feedback contains
`"`, `-->`, `{`, newlines, and encoding makes the marker's grammar a fixed regular language
regardless of content. A corrupt payload is **skipped, not fatal**.

**Two-factor address** — open-slide's `prevText` lesson, generalized: *location proposes, content
disposes, uniqueness arbitrates.*

| resolution | outcome |
|---|---|
| `el` resolves and `anchor` matches | `applied` |
| `el` resolves, `anchor` differs | `applied` + `stale_anchor` in the report — never silently |
| `el` gone, exactly one element hashes to `anchor` | `applied` + `relocated` |
| `el` gone, zero or ≥2 anchor matches | `skipped: orphan` — **the marker stays in place** |

Apply is transactional over a closed op set, exactly open-slide's `applySplices`
(`editing/edit-ops.ts`): collect every splice → apply back-to-front → **reparse → all-or-nothing**;
a rewrite that will not parse is rejected whole with `OW-T-604 edit would produce invalid IL`.
Unmodelled source is carried through verbatim, never dropped and never guessed.

`data-ow-el` is assigned by an **explicit** command, never by the validator:

```
ow out il stamp ./il --target pptx      # assigns missing data-ow-el; REFUSES on duplicates
```

Refusing rather than renumbering on a duplicate (`OW-T-405`) is deliberate: an agent copy-pasting a
slide produces duplicates, and renumbering would silently invalidate every existing comment. The
validator never writes to `il/` — enforced by a semgrep rule over the `rules/` package, because
"the checker never rewrites source SVG" is ppt-master's rule and it only survives if it is a lint.

**Feedback also arrives from the artefact.** Someone comments in PowerPoint; `ow out import` reads
the comments part, maps each to an `el` through the provenance sidecar (§3.11), and writes markers
into the IL. Declared per target as `capability.compile.feedback_from_artefact ∈ {none, notes,
comments}` — `pptx` = `comments`, `docx` = `comments` (`w:comment` is trivial), `deck` = `none`
(the browser inspector writes to the IL directly). Nothing here is claimed that is not declared.

### 3.10 `manual_required` — a first-class outcome, in the IL

```xml
<ow:manual-required el="p03/e17" family="data_graphic" blocks="delivery"
                    reason="chart values not legible at source resolution; identity unverifiable"
                    evidence="analysis/inventory.json#r14"/>
```

* `blocks="delivery"` → gate `failed`, code `OW-T-900`, message naming the element and the human
  action. `blocks="unit"` → the unit compiles with a placeholder shape carrying the reason as alt
  text, and the receipt lists it.
* The *policy* (which content families may be reconstructed, and the non-negotiable boundary for
  each) is target data in `target.toml`'s `[[realization]]` rows — ppt-master's content-family →
  realization → boundary table (`workflows/profiles/image-to-pptx.md:53-68`) as a machine-readable
  table instead of prose. The *mechanism* — representable, blocking, counted — is framework.
* ppt-master's separation rule is carried verbatim into the docs and into a conform assertion:
  **source clarity never decides whether a required editable object becomes a separate layer, only
  how that layer is prepared.**
* The **observation artefact is separate from the decision artefact.** An extraction inventory
  records only what is visibly present — bboxes, observed family, verbatim text, confidence,
  sufficiency, occlusion — and *no* layer choices, prompts, output filenames or IL bindings. Every
  extraction artefact omniweave emits carries ppt-master's `usage_contract` block stating, in the
  artefact, what authority it has under each profile.

### 3.11 Citations — how a `cite` survives into the artefact and back

D2 gives exactly one identifier that may enter a prompt or model output: `cite = d7#412`. That is
the token that travels.

**Out.** The IL carries `data-ow-cite="d7#412 d7#413"` on any element whose content came from the
store. The compiler writes two things:

1. an **embedded provenance part** inside the artefact — for OOXML,
   `customXml/omniweave-provenance.json` with its `[Content_Types].xml` override and package
   relationship; for `owdeck`, `<script type="application/json" id="ow-provenance">`; for video,
   nothing (declared `provenance_embed = "sidecar_only"`);
2. the same JSON at `out/<artefact>.owcite.json`, always, so a target that cannot embed still has it.

```jsonc
{"schema":"omniweave.provenance/1","corpus_id":"…","artefact_sha256":"…",
 "docs":[{"doc_ord":7,"doc_key":"a1b2c3d4e5f60718","uri":"file:///…/10-K.pdf",
          "source_sha256":"…","gen":3}],
 "elements":[{"el":"p03/e17","unit":3,"native_id":42,
              "anchor":"sha256:7c3f…","cites":["d7#412","d7#413"],
              "quote":"normalized","trust":2}]}
```

`docs[]` carries `doc_key` (D2's global content identity) and `uri` beside the corpus-local
`doc_ord`, so an artefact that leaves its corpus can be re-resolved against another `.owstore` —
or, failing that, reports each cite as unresolvable by name rather than silently dropping it.

**Back.** `parse_back` reads the embedded part when present, falls back to the sidecar, and for each
element sets `block.x["x.omniweave.cites"]`. Two honest limitations, stated rather than papered over:

* PowerPoint's Document Inspector can strip custom XML parts. When the part is gone, `parse_back`
  falls back to the two-factor address (`native_id`, then `anchor`) against the sidecar; when the
  sidecar is also gone, `receipt.citations.unresolved` counts every element and the gate on the
  *next* export reports `imported` provenance findings. Degradation is visible, never silent.
* **A generated deck's blocks are `quote = "normalized"`, not `verbatim`.** D2 requires
  `quote='verbatim'` to have `os_kind = 'bytes'` *and* a retained part; a shape addressed by
  `OriginNodePath` has no byte range. `parse.pptx.native` does emit `OriginBytes` for a text run
  whose `a:t` content is provably a contiguous unescaped byte range in the retained
  `ppt/slides/slideN.xml`, so a majority of runs *are* verbatim-quotable — but the claim is per
  block, driven by the model, and serve may only make it where D2 allows.

Citation edges are **not** written into `rel`: D2 restricts `rel` to the intra-document DAG and
assigns cross-document edges to D7. `x.omniweave.cites` is the carrier; D7 may promote it to a real
edge later. Using `x` for two keys (`x.omniweave.el`, `x.omniweave.cites`) is a deliberate, priced
use of D2's extension bag, with the alternative — a D2 amendment adding an `el TEXT` column to
`block` — named in §1.3 and left to the judge.

### 3.12 The receipt

```jsonc
// out/receipt.json — validated against schema/receipt-v1.json (D1). EXIT 0 IFF this was written.
{"schema":"omniweave.out-receipt/1","status":"passed-with-warnings","target":"pptx","il":"owsvg/1",
 "artefact":{"path":"out/deck.pptx","bytes":1284119,"sha256":"…"},
 "gate":{"status":"passed","report":"out/validate-final.json","stage":"final",
         "source_match":"passed","introduced_warnings":3,"inherited_warnings":40},
 "source_fingerprint":{"algorithm":"sha256","digest":"…","file_count":12,"files":[…]},
 "checks":{"container_integrity":"passed","unit_count":"passed",
           "internal_relationships":"enforced-at-build","project_il_contract":"enforced-at-build",
           "compatibility_normalization":"warning","quality_gate":"passed",
           "font_portability":"warning","external_assets":"passed","template_tokens":"passed"},
 "fidelity":{"units":12,"passthrough":7,"cloned_passthrough":1,"patched":2,"rebuilt":2,
             "classified":12,"sum_asserted":true},
 "portability":{"fonts":{"stacks":[…],"generic_only_stacks":["sans-serif"],
                         "unsafe_exported_faces":[]},
                "external_references":[],"unresolved_tokens":[]},
 "assets":{"ledger_digest":"…","rows":9,"bytes":2148311,"restricted":0,"attribution_required":2},
 "citations":{"docs":3,"elements":47,"embedded":"custom_part","unresolved":0},
 "manual_required":[],
 "degradations":[{"kind":"capability_absent","detail":"bake unavailable: target pptx has no rasterizer"}],
 "reproducibility":{"class":"byte_exact",
                    "basis":{"python-pptx":"1.0.2","XlsxWriter":"3.2.0","skia-pathops":"0.9.2",
                             "uharfbuzz":"0.50.4","Pillow":"11.0.0","cpython":"3.11.9"}},
 "spend":{"wall_ms":8412,"cpu_ms":8102,"gpu_ms":0,"tokens_in":0,"tokens_out":0,"calls":0,
          "bytes_egress":0},
 "trace":"out/trace.json"}
```

Two ideas kept from ppt-master's postflight receipt (`pptx_package/cli.py:1388-1535`):
**`"enforced-at-build"` is a first-class check value** — some invariants are guaranteed by
construction and re-verifying them postflight would be theatre, and saying so is better than
omitting the row or faking a re-check; and **the portability audit is a second axis, not part of
validity** — a generic-only font stack, an unsafe exported face, an external reference and an
unresolved `{{TOKEN}}` do not make the file invalid, they make it break on someone else's machine.

Console output is one line, full JSON on disk:

```
[POSTFLIGHT] pptx status=passed-with-warnings gate=passed units=12 rebuilt=2 warnings=3 sha256=4b1e…
```

### 3.13 CLI

```
ow out targets                                       installed targets: artefact, IL, repro class,
                                                     capabilities, toolchain state
ow out project  <doc|cite-scope> --target pptx -o il/     STORE  → IL   (authoring projection)
ow out il stamp ./il --target pptx                        assign data-ow-el; refuse on duplicate
ow out assets freeze ./il --target pptx                   resolve every ref → ledger rows
ow out validate ./il --target pptx --stage early|unit|final [--json]
ow out compile  ./il --target pptx -o deck.pptx [--page-plan page_plan.json]
ow out import   deck.pptx --target pptx                   ARTEFACT → STORE (new gen; parse_back)
ow out diff     ./il --against deck.pptx --target pptx    fidelity tiers, dry run, spends nothing
ow out comments list|apply|resolve ./il
ow out explain  OW-T-311
```

`ow out project` is the load-bearing verb: it is what makes *editing a generated deck the same code
path as creating one*, because both start from `il/`.

### 3.14 The two-gate validation cadence

Copied from ppt-master because its rationale is economic and correct: each validator call is a tool
round-trip in the agent's context.

* **early** — the first **5** units as a *method sample*. Classifies the whole issue set into
  method-level (recurs on every unit, change the approach), unit-local (a one-off), and
  not-yet-exercised (a capability the sample never used). One consolidated fix loop. Rosters of
  **≤ 6 units skip it**.
* **no validator calls between early and final.**
* **final** — the complete declared roster, before any post-processing (icon embedding, asset
  inlining), because post-processing rewrites the IL and would mask source-level violations.
* Report filenames are distinct per stage, so no diagnostic run can produce the file the release
  gate reads.

---

## 4. The first three targets

### 4.1 T1 — `pptx`, IL `owsvg/1`, pure Python (weeks 1–12)

**IL:** one SVG file per slide under `il/`, plus `il/deck.toml` (roster, canvas format, masters,
structured-vs-flat). Namespace `xmlns:ow="urn:omniweave:il:1"` for `ow:manual-required` and the
`data-ow-el` / `data-ow-cite` attributes. Closed surface: ppt-master's 29 supported inline
properties, 3 bake-required, 1 fail-closed, and the forbidden-element closure (`<style>`, `class=`,
`id=` **when** `<style>` is present, `<?xml-stylesheet`, `<link rel=stylesheet>`, `@import`,
`<foreignObject>`, `<textPath>`, `@font-face`, all SMIL `<animate*>`/`<set>`, `<script>`, `on\w+=`,
`<iframe>`) — every one of them a `constructs.toml` row.

**Why SVG:** it is the only closed subset in `_collections/` with a *proven* mapping to editable
native DrawingML objects; `viewBox` gives the fixed canvas, which deletes an entire class of layout
failure; LLMs write it well; it is text, diffable and previewable.

**Compiler:** `python-pptx` + `XlsxWriter` (native charts with their embedded workbook) +
`skia-pathops` (shape boolean) + `uharfbuzz` (shaping, glyph outlines, and the *shared* width
estimator) + `Pillow`, on the deterministic OPC writer of §3.6. Exactly D1's declared dependency
set for `omniweave-target-pptx`, and exactly ppt-master's.

**Overflow is measured, not prompted.** `measure.py` is imported by both `compile/` and
`rules/overflow.py`, so a text box that will not fit is a **finding** (`OW-T-330`), not a paragraph
in a skill file telling the model to do arithmetic. This is the single most transferable correction
to open-slide in the whole mining set.

**`parse_back` = `parse.pptx.native`**, a `parse/1` Driver writing through `DocSink`. Declared D2
`Capabilities`:

```yaml
spatial:       block_bbox        # EMU → Quad.from_driver(origin="topleft", unit="emu")
origin_span:   exact             # OriginBytes into a retained slide part where provable,
text_span:     true              #   OriginNodePath otherwise
reading_order: source
sections:      outline_from_source
tables:        cells_with_spans
math:          []                # OMML→LaTeX is target 1.1, not v1. Declare none, deliver none.
assets:        bytes
asset_origin:  true              # the OPC partname is anydoc's origin_part
notes:         linked            # speaker notes land in Layer.NOTE, never deleted
marks:         true
confidence:    none
furniture:     separated
round_trip:    passthrough
spanmap:       true
```

**Fidelity tiers**, ppt-master's four, with the sum asserted and an unclassifiable unit a hard
error (`pptx_package/cli.py:2951-2990`): `passthrough` (the original slide part copied
byte-for-byte) / `cloned_passthrough` (same bytes at a different output index, via `page_plan.json`)
/ `patched` (non-visual edits, part edited in place) / `rebuilt` (visuals changed, recompiled).
Change detection is **canonicalize-then-hash**, not byte comparison — six normalizations before
hashing, and the clause everyone forgets: *a subtree referencing a changed `<defs>` entry is changed
even though its own bytes are identical* (`authoring_roundtrip.py:979-1069`). The comparison
baseline is **regenerated**, not read off disk, so a change in the projection code itself does not
read as a user edit.

**Opaque-relationship refusal.** A rebuild that would drop a video, audio or opaque OLE
relationship **refuses**, naming the exact part paths and the two ways out; unmapped relationships
are treated as at-risk whenever visuals changed at all. Fail closed on the unknown
(`pptx_package/cli.py:2890-2948`).

**What we do not lift from ppt-master:** `attribution_guard.py` (attribution as a *runtime
precondition of conversion*, "do not inspect, repair, or bypass" — ship attribution as licence text
and a `NOTICE`); the flat 79-script directory and the 9,368-line checker class; hand-rolled
`sys.argv` scanning; `PyMuPDF`, `edge-tts`, `curl_cffi` and **`cairosvg`** — the last is an
undeclared LGPL-3.0 import at
`ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_package/media.py:15`, absent from
`skills/ppt-master/requirements.txt`, and it is on D1's `tools/licences.toml` denylist as the named
regression fixture for gate G3.

### 4.2 T2 — `docx`, IL `owmark/1`, pure Python (weeks 13–17)

The cheapest possible second target, chosen precisely because it proves the framework generalizes
**with zero new runtime, zero new process seam and zero new licence surface** — the honest test of
whether the abstraction is real or is one implementation wearing an interface.

**IL:** a closed XHTML5 subset, *not* Markdown. Markdown cannot express named styles, numbering
restarts, footnote linkage, table spans or fields, and D2's own evidence is that eleven parsers in
the collection hand downstream a string and that is why nothing citable can be built on their
output. `owmark/1`'s closure: `section[@data-ow-el] h1-h6 p ul ol li table thead tbody tr th
td[@colspan|@rowspan] blockquote pre code figure figcaption img a strong em code sub sup hr`, plus
`ow:field ow:toc ow:footnote ow:pagebreak ow:manual-required`. Styling is by **named class from a
closed vocabulary** declared in `il/doc.toml` and mapped to DOCX styles — there is no CSS, so there
is no cascade to validate.

~70 construct rows. No canvas, no z-order, no bake tier, no shape boolean, no gradient stops.
Compiler: `python-docx` (MIT) + `lxml`. `parse.docx.native` walks `word/document.xml` with
`OriginNodePath` — the same child-index-path machinery built for `pptx`, reused verbatim, which is
where most of the 4-week estimate comes from.

**And it sets up target 3 for free:** `owdeck/1` reuses `owmark/1`'s element closure.

### 4.3 T3 — `deck`, IL `owdeck/1`, first Toolchain (weeks 18–24)

**One deliberate change from open-slide: the IL is HTML, not TSX.** TSX drags babel into the
validator, a React runtime into the compiler, and a JS AST parser into `parse_back`; open-slide's
`packages/core/package.json` lists 31 runtime dependencies including React, Vite, Tailwind, shadcn,
dnd-kit, cmdk and emoji-picker-react, essentially all of which are the *editor*, not the deck.
HTML is parseable on both sides of the seam, and — the sequencing argument — **the deck IL is the
video IL minus the timeline**: hyperframes proved a closed HTML + `data-*` surface works for the
strictly harder problem (`packages/parsers/src/compositionContract.ts`: `data-start`,
`data-duration`, `data-track-index` canonical, `data-end` derived, `data-layer` legacy, with the
rule *"Readers accept legacy documents; writers always emit the canonical representation"* stated in
the file header). So target 3 is the on-ramp to target 4 rather than a detour.

`owdeck/1` = `owmark/1`'s element closure + `<section class="slide">` on a fixed 1920×1080 canvas +
a closed `--ow-*` CSS custom-property token set + **no `<script>`**. Compiler: a digest-pinned Node
Toolchain (`omniweave targets install deck`) that inlines ledger assets and emits static HTML plus
PDF, driven over `omniweave-target/1`. It is the first and only place the wire protocol runs, and it
is where the `ready` frame's `capabilities:{parse_back, assets}` and `external:[…]` block finally
have a second implementation to prove them against.

What we take from open-slide besides the canvas: the loc-tag injection pattern (`data-ow-el` in our
own transform, because React's `_debugSource` goes stale on fibers across HMR —
`vite/loc-tags-plugin.ts` says so in a comment); the comment protocol; `http/request-guard.ts`
verbatim for any preview server. What we supply that open-slide does not have at all: **a semantic
validator.** open-slide ships only `tsc --noEmit` and biome — *is this valid TypeScript*, never *is
this a valid slide* — and its scaffolded consumer projects ship neither. Every one of 1080px fit,
notes/page alignment, undeclared `var(--ow-…)` tokens, unresolved asset imports and misnested
components is mechanically checkable, and here it is a construct table.

`parse_back` for `deck` is `round_trip: structure`: the static HTML is re-parsed to blocks with
`OriginNodePath` into the emitted HTML. It is genuinely weaker than `pptx`'s `passthrough` and it is
declared as such.

### 4.4 Why video is fourth

1. **`mine-out.md`'s PART 3 on hyperframes was never written.** digest-out.md's first paragraph says
   so and warns to *"treat hyperframes as indexed but not mined."* Every hyperframes fact available
   to this panel is from the convergence table and the index. Making the third target the one repo
   nobody read is the exact failure mode this panel exists to avoid.
2. **The runtime cost is a step change**, and it is checkable: `hyperframes/packages/engine` is
   *"Seekable web page to video rendering engine (Puppeteer + FFmpeg)"*. That is a headless Chromium
   download plus a system FFmpeg, on top of the Node toolchain target 3 already introduced.
3. **Reproducibility drops a class.** `frame_exact` needs a decode-and-hash harness that no other
   target uses.
4. **Codec licensing is live.** D1 already rules `ffmpeg = "system"`, never bundled, `codec = "vp9"`
   with h264 an operator opt-in, `ffmpeg-static`/`ffprobe-static` denied because libx264 makes a
   bundle GPL-2.0-or-later, and *refuse rather than substitute a codec*. That is a policy surface,
   not a feature.
5. Target 3 as specified makes target 4 mostly additive: same IL family, same validator, same
   ledger, one new construct group (the timing attributes) and one new toolchain.

---

## 5. The `parse_back` fidelity contract, as testable properties

For every target `T` with `roundtrip.capabilities.round_trip != "none"`:

```
Let  compile_T : IL → Artefact
     back_T    : Artefact → Doc          (a parse/1 Driver writing through DocSink)
     project_T : Doc → IL                (`ow out project`)

P1  ELEMENT SURJECTIVITY
    ∀ e ∈ elements(I) with data-ow-el:
        ∃! b ∈ back_T(compile_T(I))  with  b.x["x.omniweave.el"] == e.el
        ∧ b.kind == constructs[e.construct].maps_to_kind
        ∧ nfc(b.text) == nfc(visible_text(e))
        ∧ b.x["x.omniweave.cites"] == e.data_ow_cite
    Enforced: conform suite `roundtrip`, per golden fixture. A missing, duplicated or
    kind-mismatched element is a FAILURE, not a warning.

P2  SECOND-ROUND FIXED POINT              ← the contract that actually matters
    D1 = back_T(compile_T(I))
    D2 = back_T(compile_T(project_T(D1)))
    ⇒  digest_tree(D1) == digest_tree(D2)
    where digest_tree = the multiset of D2-ruling `content_digest` values over
    Layer.BODY blocks in (page, ord) order.
    The FIRST round is NOT required to be a fixed point — an author writes
    non-canonical-but-compatible input and the compiler normalizes it, which legitimately
    changes the tree once. The second must be. This is the honest, achievable statement of
    "round trip is lossless" and it is the one an implementation can be held to.

P3  EDIT LOCALITY / PASSTHROUGH
    (a) back_T then compile_T with ZERO edits ⇒ 100% of output units classify as
        `passthrough` or `cloned_passthrough`, and each copied part's sha256 is asserted
        equal to the source part's.
    (b) with edits confined to element set E ⇒ every unit whose source-refs and definition
        dependencies are disjoint from E classifies as passthrough or patched, NEVER rebuilt.
    Enforced: `omniweave-conform` suite `fidelity`, plus the runtime hard error when
    passthrough + cloned + patched + rebuilt != len(units).

P4  NOTHING SILENTLY DROPPED
    ∀ relationship / media part / opaque payload p present in A and not representable in IL_T:
        p is (a) carried as an opaque passthrough asset with a ledger row, OR
             (b) a BLOCKING refusal naming p's exact part path and the two ways out.
    There is no third branch. Enforced: a fixture deck carrying an embedded mp4 and an OLE
    object; the test asserts a refusal message containing both part paths.

P5  DECLARED LOSS IS EXACT
    observed_loss(T) ⊆ declared_loss(T)      -- nothing is lost that is not declared
    ∧ ∀ row ∈ declared_loss(T): row.fixture exhibits row.loss
                                             -- nothing is declared that does not happen
    Both directions, D3-12's rule. observed_loss is computed by diffing the authoring Doc
    against back_T(compile_T(project_T(Doc))) construct-class by construct-class.
```

**What must survive, stated once:** element identity (`data-ow-el`), block kind, visible text under
NFC, table cell topology including spans, reading order, asset identity by sha256, citation tokens,
speaker notes / footnotes as a distinct `Layer`, and — for `passthrough` and `patched` units — the
original container bytes.

**What is allowed to be lost, stated once:** anything with a `[[roundtrip.lossy]]` row. For `pptx`
v1 that is: animation timing curves (trigger + preset survive), `normAutofit` font scaling
(recomputed), theme-relative colour references resolved to literal `srgbClr`, OMML math (v1: refused
as `manual_required`, not silently dropped), and slide-transition sound. Five rows, each with a
fixture. **A sixth kind of loss is a bug, and P5 makes it a build failure.**

---

## 6. Invariants and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| O1 | The IL is text on disk; blobs never travel in it. | `data:` URI ⇒ `OW-T-502` invalid; a node over `max_il_node_bytes` ⇒ `OW-T-503`; fuzz fixture |
| O2 | Every construct the compiler can emit is a `constructs.toml` row, and every row has a mapping. | G-OUT-2: the compiler's dispatch table is enumerated at import and diffed against the table, both directions |
| O3 | Every finding code is in `codes.toml` (D1, append-only) and is emitted by ≥1 fixture. | G-OUT-2; `RuleSpec.codes` is checked against what the rule actually emits under the fixture corpus |
| O4 | An unrecognised construct is invalid. | `unknown_construct = "invalid"` is not configurable; dispatch default raises `OW-T-499`; the `ignore` list is closed and in the table |
| O5 | The validator never rewrites the IL. | semgrep: no write to a path under `il/` from `rules/`; `stamp` and `normalize` are separate commands with their own exit codes |
| O6 | A `compatible` normalization is idempotent and compile-equivalent. | Property test per normalizer: `n(n(x))==n(x)` ∧ `sha256(compile(x))==sha256(compile(n(x)))` |
| O7 | Compilation requires a `passed` final gate whose fingerprint matches the IL bytes *now*. | `compile()` recomputes `source_fingerprint`; mismatch ⇒ `stale`, exit 2, message names the changed files |
| O8 | File creation is not proof. | Postflight re-opens the artefact as a container, asserts integrity and `units == len(il_units)`, **deletes the artefact** and raises on failure; test with a truncated writer |
| O9 | Every referenced asset is a ledger row. | `AssetLedger.resolve` is the only resolver; semgrep bans `open(`/`Path(` on IL-derived strings in `compile/`; a raw path ⇒ `OW-T-501` |
| O10 | No artefact carrying disallowed `restriction_bits` is emitted. | Gate status `restricted`, naming the offending `cite` tokens; D3-17's synthetic-restricted-driver test extended parse → derive → **compile** |
| O11 | Every output unit is in exactly one fidelity tier and the sum is asserted. | Hard error, artefact not written; fixture with a deliberately unclassifiable unit |
| O12 | A rebuild that would drop an unrepresentable relationship refuses, naming the paths. | Fail-closed on unmapped dependencies; embedded-mp4 + OLE fixture |
| O13 | The second round trip is a fixed point (P2). | conform `roundtrip` over the golden corpus per target |
| O14 | Nothing is lost that is not declared, and nothing declared fails to occur (P5). | conform `roundtrip`, both directions |
| O15 | Two compiles of one job digest are identical per the declared reproducibility class. | G-OUT-3 across {ubuntu, macos, windows} × {3.11, 3.12, 3.13} |
| O16 | A feedback marker is never silently discarded. | Post-apply verification re-reads the IL and asserts the only remaining markers are the ones reported `skipped`; every marker gets `applied \| relocated \| skipped:<reason>` in the report |
| O17 | `parse_back` writes a new `gen`; a stored generation is never patched in place. | `DocSink.begin_doc` with `gen = max(gen)+1`; a test asserts the prior generation still resolves and reports `superseded_by` |
| O18 | Severity and provenance are orthogonal; an inherited error still blocks, attributed to the template. | `gate_status` computes `blocking = count(severity==ERROR)` over all provenances; the report's `categories` block is a cross-tab; test with a template carrying 40 inherited warnings and 1 inherited error |
| O19 | A skipped check is visible in the report. | An unmet `RuleSpec.needs` emits a `FRAMEWORK` info finding naming the capability; there is no silent-pass branch |

---

## 7. Cost, honestly

| item | engineer-weeks | notes |
|---|---|---|
| `omniweave_core.out` + conform OUT suites | 4 | stdlib only; ~2,000 LoC + tests |
| `pptx` target | 11 | ~180 construct rows, ~45 rules, compiler, deterministic OPC writer, `parse_back`, fidelity tiers, golden corpus |
| `docx` target | 4 | ~70 rows; reuses the `OriginNodePath` machinery |
| `deck` target | 6 | Node toolchain build + pnpm lockfile + digest pin + `ow targets install` + a validator open-slide never had |
| Windows parity | 1.5 | named pipes, path normalization, `node.exe` invoked directly (D1's recorded scar) |
| **total to three targets** | **26.5** | ≈ **3.5 calendar months for two people** |

**Each phase ships something a user runs:**

* **week 4** — `ow out validate ./il --target pptx` + `ow out compile` from a hand-written IL,
  producing a real `.pptx` with the forbidden-element closure enforced and a receipt. No store, no
  gate binding, no `parse_back`. A user makes a deck.
* **week 8** — the full gate, fingerprint binding, asset ledger, `ow out project` from the store, and
  citations embedded. A user makes a deck **from their corpus**, with sources.
* **week 12** — `ow out import` (`parse_back`), fidelity tiers, feedback markers. **The loop closes.**
* **week 17** — `docx`. A user makes a report.
* **week 24** — `deck`. A user makes a web deck, and the Toolchain seam has two implementations.

**Runtime overhead.** Validation is a single parse plus a linear rule pass: ~40 ms per slide for
~45 rules on a 300-node SVG, dominated by `xml` parsing; a 60-slide deck validates in ~2.5 s.
Shaping-based overflow measurement adds ~1 ms per text run (~40 runs/slide → ~2.5 s for 60 slides).
Compilation is python-pptx-bound at ~120 ms/slide. `parse_back` is ~80 ms/slide.

**Dependency weight.** `omniweave-target-pptx` stays inside D1's 60 MB ceiling on the declared set.
`omniweave-target-docx` adds `python-docx` + `lxml` ≈ 20 MB and is **not** in
`omniweave[recommended]`, so the 250 MB aggregate gate is untouched. `omniweave-target-deck` is a
1 MB manifest; the Toolchain lives in `$OMNIWEAVE_HOME` and is never a `pip` dependency.

**Operational burden.** One golden corpus per target, versioned and blessed (`--bless`); a
construct-table review whenever a mapping changes; a per-target fidelity matrix published in the
docs and regenerated from `[[roundtrip.lossy]]`; the deck Toolchain's pnpm lockfile as a second
supply chain that can move without a Python-side signal, held only by the full-digest pin.

**One implementation note that costs something:** `owmark/1` and `owdeck/1` share an element
closure but live in separate distributions, and D1's `tools/layers.toml` forbids
`omniweave_target_deck → omniweave_target_docx`. The shared XHTML-subset parser is therefore
~350 lines duplicated in both, with a CI test asserting the two `constructs.toml` element closures
are identical on their shared rows. Duplicating 350 lines is cheaper than a twelfth distribution
whose only job is to hold them, and the test makes the duplication safe. I state this rather than
hide it.

---

## 8. Failure modes, including the input that breaks it

1. **A chart title edit in a round-tripped deck.** A native chart lives in `chart1.xml` plus an
   embedded workbook; `owsvg` expresses "there is a native chart here", not its internals. Editing
   the title is a *visual* change the IL cannot express, so the unit cannot be `patched` and a
   `rebuilt` would regenerate the chart from IL that does not contain the data. Outcome:
   `manual_required` with `blocks="unit"`. Honest, and frustrating. The fix — a fifth "native part
   patch" fidelity tier that edits `c:tx` in place — is deliberately **not** in v1, because a tier
   that edits a part the authoring model cannot read is a tier whose correctness nothing can check.
2. **A 4 M-cell spreadsheet becoming a table.** D2 caps at `MAX_GRID_SLOTS = 4_000_000`; the
   compiler refuses at `OW-T-303 ResourceLimit{limit}` naming the knob. A user who wanted that
   table gets a refusal, not a 900 MB pptx.
3. **`bake` on the PPTX target is unreachable.** `mix-blend-mode` needs a rasterizer; the only one
   ppt-master has is `cairosvg` (LGPL-3.0, undeclared, on D1's denylist), and D1 requires the PPTX
   target to be pure Python with zero Node. So `capability.compile.bake = "none"`, `OW-T-311` is a
   blocking error, and its `fix` is `ow out assets bake <el>` — which, on the pptx target, is
   itself a refusal telling the author to attach a pre-rendered raster to the ledger or remove the
   property. **Refuse rather than substitute** (D1's codec rule, applied to a rasterizer). It is a
   real product gap and the receipt's `degradations[]` says so on every compile.
4. **The construct table and the compiler drift in the one direction the meta-gate cannot see:** a
   row exists, a mapping exists, and the mapping is *wrong*. Only the golden corpus catches that,
   and only for constructs the corpus exercises. The table is a bound on what can be attempted, not
   a promise of correctness.
5. **`data-ow-el` duplicates from an agent copy-pasting a slide.** `stamp` refuses rather than
   renumbering, which is correct and which will annoy someone weekly until the authoring skill
   learns to stamp before duplicating.
6. **Custom XML stripped by PowerPoint's Document Inspector.** Citations degrade to the sidecar,
   then to unresolved. Visible in `receipt.citations.unresolved`; nothing prevents it.
7. **The second-round fixed point fails on floating-point-shaped input.** A gradient stop at
   `offset="0.3333333333"` normalizes to a 1/1000-pt-quantized EMU on compile and back to
   `0.333` on parse; round two is stable, round one is not — which is exactly why P2 and not P1
   is the contract. If a target ever fails P2, the cause is almost always an unquantized value
   surviving the compiler, and the debugging path is the `trace.json` normalization ledger.
8. **A deck with 500 slides.** `job.json` caps `max_units`; above it the compile refuses and names
   the cap. Below it, validation and shaping are linear and a 500-slide deck takes ~5 minutes,
   which will feel broken. Progress frames are rate-limited to 4/s (D1) and the in-Python path
   emits the same progress through `DriverIO.progress`.
9. **A malicious IL.** The forbidden closure kills `<script>` and `on*=`, and the deck preview
   server is `omniweave-serve`'s surface with open-slide's request guard. But an IL is authored by
   an LLM from parsed documents, and awesome-skills' security class #8 — *scraped content passed
   onward as instructions rather than as data* — is live here: a document containing
   `<!-- @ow-comment … -->` in its body text becomes a feedback marker when projected into the IL.
   Mitigation: `ow out project` escapes any body text matching `MARKER_RE` (ppt-master's
   `_escape_readback_control_lines` applied to a different marker grammar), and a conform fixture
   carries the attack string.
10. **Two package managers.** A pnpm bump silently changes the deck toolchain's output; only the
    full sha256 pin stands between that and an unreproducible deck. D1 already names this risk; the
    deck target inherits it whole.

---

## 9. Why I reject the alternatives

**A single universal IL (one AST, one schema, all targets).** It is the option the brief warns about
by name, and the evidence is that three teams who each solved this well chose three different
surfaces because the targets differ in kind: native objects on a fixed canvas, flowing text with
styles and numbering, and a seekable timeline. Any surface loose enough to hold all three constrains
nothing, and a validator over it can only check syntax — which is precisely open-slide's actual
state (`tsc --noEmit` and biome, nothing semantic). The convergence in `mine-out.md` §0 is at the
*mechanism* layer, not the *language* layer, and that is where the framework belongs.

**Generating the IL from a schema, or an IDL / codegen for the construct table.** D1 already ruled
out a language-neutral IDL for a boundary carrying a ~30-field job envelope, and the same argument
holds one level down: `constructs.toml` is read by `tomllib` in core and by the toolchain's own TOML
reader, and a code generator would be a fourth build system with one consumer.

**Making L2 the IL (`project_T` is the identity).** Tempting, and it corrupts the pivot. L2 is a
parse model — reading order, provenance, spans, trust, `quote` tiers. A slide carries z-order,
transform matrices, gradient stops, blend modes and boolean operands, none of which belong in
`Block.payload`; D2 forbids an `html`/`markdown` field on any model class for the same instinct. The
bridge is `parse_back` and `ow out project`, which is precisely the pair of functions the fidelity
contract in §5 is written against.

**LibreOffice headless as the compiler.** The obvious shortcut. Rejected on five grounds, four of
them checkable: it is an LGPL/GPL external binary (D1 permits it only as a spawned process, never
bundled); D4's evidence names `subprocess.run` on `libreoffice` **with no `timeout=`** as a recorded
anti-pattern; its output is not byte-reproducible; it emits no element addressing, so there is no
`data-ow-el`, no feedback protocol and no fidelity tiers; and it therefore destroys `parse_back`,
which is the entire point of this decision.

**Two independent validator implementations, ppt-master's fingerprint-recompute design.** Rejected
per D1's "no second implementation of anything." The divergence ppt-master's `stale` status actually
catches is temporal, not implementational, and a second implementation only adds a way for two
readers to disagree about bytes neither read wrong.

**Per-unit validator calls.** ppt-master rejected this explicitly on context economics — each call
is a tool round-trip — and its two-gate cadence (first 5 units as a method sample, then nothing
until the final gate) is a measured design, not a preference. Adopted whole.

**A `markdown` or `text` target.** D2 already owns `serialize(scope, fmt) -> (str, SpanMap)` with a
`spanmap:false` refusal path. A "markdown target" would be a second implementation of D2's
serializer with a worse citation story.

**`video` as the third target.** `mine-out.md`'s hyperframes section was never written; the digest
says so and says to treat hyperframes as *indexed but not mined*. Building the third target on the
one OUT repo nobody read, at a step change in runtime (Puppeteer + Chromium + FFmpeg), a step down
in reproducibility (`frame_exact`), and a live codec-licensing surface, is the exact shape of
speculative generality this proposal exists to refuse. Target 3 as specified makes target 4 mostly
additive.

**TSX as the deck IL.** open-slide's genuine assets are the fixed canvas, the comment protocol, the
loc-tag injection and the request guard — none of which require TSX. TSX requires babel in the
validator, React in the compiler and a JS AST parser in `parse_back`, and it forecloses the
sequencing argument that makes the deck IL the video IL minus the timeline.

**Findings as strings.** ppt-master's per-file result is `{'errors': list[str], 'warnings':
list[str]}` (`svg_quality/checker.py:1243-1251`). Strings cannot be folded, cannot carry a canonical
replacement, cannot be counted by code, cannot be bound to an element address, and cannot be
diffed across releases. A structured `Finding` with a code from `codes.toml` costs nothing and is
the difference between a report and a wall of text.

**A `--force` or `--no-gate` escape hatch.** ppt-master's diagnostic override exists, is named, and
is recorded in the receipt — that shape is fine, and it is what `--source` other than `output` does
there. What is not fine is an override whose scope is "skip whatever complained." So: the only
bypass is `ow out compile --diagnostic`, which refuses to write to `output_root`, stamps
`status: "diagnostic"` in the receipt, and cannot produce a file the release path will accept.
