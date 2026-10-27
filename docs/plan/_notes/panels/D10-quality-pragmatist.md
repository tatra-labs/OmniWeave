# D10 — Quality, evaluation, testing and trust

**Panel:** D10 · **Seat:** the shipping pragmatist · 2026-09-01

---

## Headline

**One harness, one ledger, one command. `omniweave-conform` is the single quality artifact — it holds
the driver conformance suites, the golden-corpus loader, the benchmark runners and the metric code —
and everything it produces lands in one `.oweval` SQLite file that `ow eval report` turns into the
public scoreboard. Nothing here is a new subsystem: every gate hangs off a mechanism an upstream
ruling already built (D1's sixteen CI gates, D2's `owcheck` / `Capabilities` / `content_digest`, D3's
eleven conform suites and kit-written `[quality]` block, D4's `route_verdict` and its ECE ≤ 0.05 /
Brier ≤ 0.08 calibration gate). The one genuinely new rule is about confidence: `trust` and `score`
ship with a measured reliability table or they are written NULL and shown to nobody — a confidence
field that cannot pass its own gate is deleted, never softened.**

The three sentences everything below serves:

> 1. **Every number omniweave publishes is reproducible by a stranger with one command**, and carries
>    the `measured_on` tuple that makes it meaningful.
> 2. **omniweave is never its own reference.** No published accuracy number may be scored against
>    omniweave output. anydoc's trigram metric and olmOCR's own-benchmark entry are the two cautionary
>    cases, and they are cited on the scoreboard page itself.
> 3. **A confidence surface with no measured hit rate is a lie the agent cannot detect**, and the
>    remedy is deletion, not a disclaimer.

---

## 0. Scope, and what is already settled

This decision owns: the test pyramid, golden corpora and their licensing, the benchmark harness, the
accuracy and performance regression gates, the conformance kit's *contents* (D3 owns its contract),
retrieval and absence evaluation, calibration of user-facing confidence, and the public scoreboard.

It does **not** own: what the router does with a verdict (D4), the response envelope (D9), the store
schema (D5), the runtime's work table (D6). Where I need one of those I name it and stop.

Four upstream mechanisms I build directly on, verbatim:

| Upstream | What it already gives me |
|---|---|
| **D1** | Sixteen CI gates G1–G16, the `gates`/`test`/`build` job split, cold-start budgets (G10, 25 % drift), `fixtures/`, the `tools/*.toml` convention, the append-only `codes.toml`, eleven distributions with weight ceilings |
| **D2** | `owcheck` at ~240 ns/block, `content_digest` with geometry excluded, `layout_digest` with geometry quantised to whole points, `Capabilities` as a declaration a testkit proves, `import(export(store)) == store` as a CI gate, the closed `Diag` registry, `Grid.up/down/left/right/top_heading/left_heading` in O(1), `quote ∈ {verbatim…synthetic}`, `fixtures/owdoc/v1/*.owdoc` |
| **D3** | `omniweave-conform` as a separate distribution; eleven suites; **"the card is the test plan"** (D3-12: a `false`/`none`/`[]` declaration is asserted *absent*); `[cost]` and `[quality]` are kit-written and attested (D3-13); every benchmark row carries `measured_on` (D3-14); the five-minute mandatory tier; the kit is run from a trusted tag, never the PR branch (D3-23) |
| **D4** | `route_verdict{self,agree,audit,feedback}`, `route_scoreboard` with `UNKNOWN` as the zero value, deterministic sampling `blake2b(unit_uri‖part‖salt) % 10000 < rate*10000`, **ECE ≤ 0.05 and Brier ≤ 0.08 as a build-failing gate** (R6), self-report excluded from the scoreboard (R12) |

I harmonise one naming collision rather than inventing a third name: **D2's
`omniweave-driver-testkit` (~120 property tests) and D3/D1's `omniweave-conform` are one distribution,
named `omniweave-conform`.** D2's property tests become its `contract` and `capability` suites. Two of
three rulings say `omniweave-conform`, D1 lists it as one of the eleven, and a driver author must not
install two kits to get one green report.

I also note without re-litigating: D1 names the driver manifest `omniweave-driver.toml` with an entry
point value of `module:attr`; D3 names it `driver.toml` with a dotted-package value and *rejects* a
value containing `:`. I assume D3's form throughout (it is the later, more specific ruling, and its
`CARD_ENTRYPOINT_NOT_A_PACKAGE` reject code is load-bearing). The charter must settle it; my design is
indifferent to which wins, and only a string in two file paths changes.

---

## 1. UPSTREAM CONFLICT — D3's `[capability.parse]` cannot express the claim D2 requires serve to prove

**This is the one place an upstream ruling makes my job impossible, and the fix is three lines.**

D3 rules that conformance derives from the card in both directions (D3-12) — that is the entire
premise of "the card is the test plan", and it is the mechanism I depend on to make a third party's
honesty machine-checkable. D3's `[capability.parse]` vocabulary is exactly:

```
spatial · charspan · reading_order · sections · tables · math · assets · notes ·
confidence · furniture · round_trip
```

D2 rules a strictly larger `Capabilities` set and makes three of the extra fields load-bearing:

> `origin_span: Literal["exact","normalized","none"]   # gates serve's byte-exactness claim`
> `spanmap: bool` … *"a serializer that cannot emit one declares `spanmap: false`, and its output MAY
> NEVER BE CITED."*
> `marks: bool`

and D2 §11 states the enforcement explicitly:

> *"`origin_span='exact'` is proved by `normalize_k(part_bytes[a:a+len]) == block.text`. That test is
> the only mechanism here that makes a third party's honesty machine-checkable."*

**The defect:** D3's card has no `origin_span`, no `spanmap`, no `marks` key. Under D3's own rule that
unknown keys inside `[capability.<port>]` are *ignored* with a recorded `CARD_CAPABILITY_UNKNOWN`
degradation, a driver that writes `origin_span = "exact"` has written a comment. The conformance suite
therefore cannot derive the byte-exactness assertion, `resolve()` cannot filter on it, and D2's stated
consequence — *"Serve (D10) may claim byte-exactness for a minority of blocks, and must say so"* —
becomes an unenforceable review item. The single strongest trust claim in the framework
("byte-identical, safe to Edit from") would ship with no test behind it.

**Minimum amendment** (additive, and D3's own asymmetry rule makes it free — an unrecognised
capability can only make a driver look *less* capable):

```toml
[capability.parse]
origin_span = "exact"     # ORDERED: none < normalized < exact  — gates the verbatimness claim
spanmap     = true        # bool — a serializer that cannot emit a SpanMap may not be cited
marks       = true        # bool — inline formatting survives as sparse Marks
```

plus one rename for consistency with D2's type names: D3's `charspan` is D2's `text_span`. Either name
is fine; **one** name is required, because the conform suite reads the card and the testkit reads the
`Capabilities` dataclass and they must be the same field. I use `text_span` below and accept
`charspan` as an alias if the charter prefers it.

Nothing else in D3 changes. `compute_tier`, the reject codes, the wire protocol, the eleven suites and
the attestation model are untouched.

---

## 2. The test pyramid — five layers, each with an owner, a budget and a place it runs

Not a metaphor: a table with wall-clock budgets, because a gate that makes CI take 40 minutes is a
gate somebody disables in month four. `local-deep-research` ships **60 GitHub Actions workflow files**
(`_collections/local-deep-research/.github/workflows/`, counted) — that is the failure mode, and D1
already ruled the answer (five jobs, sixteen gates). I add exactly two jobs.

| L | Layer | Runs | What it proves | Budget | Owner |
|---|---|---|---|---|---|
| **L0** | Static gates | every PR | D1's G1–G16 + the eight semgrep classes | **≤ 2 min** | D1 |
| **L1** | Unit + property | every PR, 9-cell matrix | the invariants of §5 | **≤ 4 min/cell** | package owner |
| **L2** | Golden projections | every PR | a parser's output did not change unnoticed | **≤ 3 min** | driver owner |
| **L3** | Conformance, fast tier | every PR, first-party drivers | the card is honest | **≤ 5 min** (D3's rule) | D3 |
| **L3n** | Conformance full + fuzz | nightly | limits, sandbox, licence, fuzz | ≤ 40 min | D3 |
| **L4** | Eval + bench | nightly on one pinned machine; full on tags | accuracy and cost against ground truth | ≤ 90 min | this decision |
| **L5** | Production telemetry | continuous | what actually happened to real users | ~0 | D4 / D9 |

**Two new CI jobs, and no more:**

```yaml
# .github/workflows/ci.yml — added to D1's five jobs
  golden:    { runs-on: ubuntu-latest,            needs: gates }   # L2, <= 3 min
  perfcheap: { runs-on: [self-hosted, ow-bench],  needs: gates }   # cold start + import time only

# .github/workflows/nightly.yml — ONE file, matrix inside it. Not thirty files.
  jobs: [conform-full, fuzz, eval-free, bench, calibration]
```

Everything else — competitor comparisons, olmOCR-Bench, LOCOMO, the stability suite — is a *step* in
`nightly.yml`, not a workflow file. One file, one place to look when it goes red.

**PR wall clock, against these budgets: ~8 minutes with the jobs in parallel.** That is the number the
design is optimised for, and it is why the full benchmark is not a PR gate.

---

## 3. Golden corpora — three tiers, and the licence is a field, not an assumption

Test documents are redistributed content. hyperframes is the only repo in the collection that
understood this: it ships `packages/producer/tests/hdr-regression/NOTICE.md` and
`packages/producer/tests/vfr-screen-recording/NOTICE.md` — attribution for *test media*, which the
risk notes call "a real copyright exposure in a public repo." We do it for every fixture, and we make
it a gate.

### Tier 0 — `fixtures/` — in-repo, redistributable, ≤ 64 MB total (hard gate G17)

Every file has a sidecar `<name>.meta.toml`. A file without one, or with `spdx = "unknown"`, **fails
the build**. Four admissible provenances and no fifth:

1. **`generated`** — produced by a committed script with a fixed seed. Preferred. This is how we get
   the adversarial cases D1 and D2 named (`gen-5000p.pdf`, `merged-4m-cell.xlsx`, the zip bomb, the
   40-byte docx) with no licence question and no 60 MB blob in git. Generators write into
   `$OMNIWEAVE_HOME/fixtures-cache/`, keyed by `sha256(generator source ‖ seed)`.
2. **`public_domain`** — US federal government works (17 U.S.C. §105): GAO reports, NIST SPs, Federal
   Register pages, US Courts opinions. The best real scanned-document source with no licence risk, and
   it covers the hard cases (multi-column, tables, footnotes, old scans).
3. **`cc0` / `cc_by`** — attribution reproduced in `fixtures/NOTICE.md`, generated by
   `tools/gen_fixture_notice.py --check`.
4. **`authored`** — we wrote it; records the author and the commit.

**Never**: a document off the web with no stated licence, a customer document, anything with a
personal name in it, or a file whose provenance is "it was in someone's Downloads folder."

```
fixtures/                                          <= 64 MB, gate G17
├── NOTICE.md                     GENERATED from *.meta.toml; --check gated
├── docs/            ~110 files   one per (format x hazard) cell
├── owdoc/v1/*.owdoc  ~12 files   one per released model_version (D2's compat gate)
├── fuzz/
│   ├── seeds/                    mirrored from vendor/anydoc/fuzz/seeds at the pinned SHA
│   └── regressions/              every crash ever found, committed forever
└── golden/<driver>/<major>/      the L2 projections, §4
```

```toml
# fixtures/docs/gao-25-106321-scan.pdf.meta.toml
spdx         = "PD-USGov"          # "unknown" FAILS the build (gate G17)
provenance   = "public_domain"
source_url   = "https://www.gao.gov/assets/gao-25-106321.pdf"
retrieved_at = "2026-08-03T00:00:00Z"
sha256       = "8f14e45fceea167a5a36dedd4bea2543..."
bytes        = 2_318_442
why          = "3-column scan, rotated pages 4-6, footnotes, 2 ragged tables — the old-scans slice"
hazards      = ["multi_column", "rotation", "footnote", "ragged_table"]
```

### Tier 1 — `corpora/*.toml` — pointer manifests, fetched, never vendored

```toml
# corpora/olmocr-bench.toml
name         = "olmocr-bench"
version      = "2025.10"
kind         = "parse"
license      = "ODC-BY-1.0"        # READ AND RECORDED. "unknown" fails `ow eval fetch`.
redistribute = false               # we never mirror it
publishable  = true                # may its numbers appear on the PUBLIC scoreboard?
source       = "hf://allenai/olmOCR-bench"
layout       = "bench_data/pdfs/**.pdf + bench_data/*.jsonl"
files_sha256 = "corpora/olmocr-bench.sha256"   # per-file digests, committed
cases        = 7000                            # 7,000+ cases / 1,400 docs
harness_license = "Apache-2.0"     # olmocr/bench/ code — safe to adapt, attributed in NOTICE
notes = """olmOCR is an entrant on its own benchmark. Category SHAPE is the contribution;
absolute numbers are directional. We report only our own runs."""
```

`publishable` is the field most teams miss, and it is why it exists. **A non-commercially-licensed
academic eval set may be used for internal measurement and its numbers may not go on the public
scoreboard.** LOCOMO and LongMemEval-S are exactly this risk class — their terms must be read, put in
the manifest, and `ow eval report --html` **refuses to render a row whose corpus has
`publishable = false`**, printing `withheld: corpus licence` in its place. That refusal is a feature:
visible, honest, one boolean.

Manifests shipped on day one: `olmocr-bench`, `locomo`, `longmemeval-s`, `omnidocbench`,
`ow-office-v1` (ours, Tier 0), `ow-extract-v1` (ours, lift-shaped, Tier 0), `ow-absence-v1` (ours,
Tier 0), `ow-retrieval-v1` (ours, Tier 0).

### Tier 2 — the user's own corpus

`ow eval --corpus ./my-contracts --suite office` runs the identical harness. This is anydoc's insight,
named in the notes: *"the corpus is not redistributable and is not in the repo; the harness reads
whatever is in `samples/`. That is the right shape for a benchmark you want people to run on **their**
corpus."* It is also the honest answer to "will this work on my documents", and a better adoption
asset than any number we publish.

---

## 4. Snapshot/golden testing for parsers, where the output is large and noisy

**Never snapshot the document.** Snapshot a *projection* chosen so the diff is readable and the noise
is quantised away. D2 already did the hard part: `content_digest` excludes geometry, and
`layout_digest` quantises geometry to whole points.

Three projections, three files, deliberately separate so a layout change does not produce a
4,000-line diff on the text golden:

```
fixtures/golden/parse.doc.anydoc/0/contract-ragged.docx.tree     # structure + text
fixtures/golden/parse.doc.anydoc/0/contract-ragged.docx.geom     # geometry, whole points
fixtures/golden/parse.doc.anydoc/0/contract-ragged.docx.diag     # Diag codes, sorted
```

```
# .tree — one line per Block, ~70 bytes, TSV, sorted by (page, ord). A human can read the diff.
# addr    kind       layer  trust  quote      cdig     text[:72]
p0/0      title      body   2      verbatim   3f9a1c02 Master Services Agreement
p0/1      paragraph  body   2      normalized 88de4471 This Agreement is entered into as of the…
p0/2      table      body   1      synthetic  01bb9e30 -
p0/2/r0c0 table_cell body   1      verbatim   7c1120af Region
p0/2/r0c1 table_cell body   1      verbatim   aa03f7de FY24
```

Rules, each of which exists because of a specific failure:

- **`content_digest[:8]`, not the text body.** A one-character upstream change shows as one changed
  digest on one line, not a re-wrapped paragraph diff. The truncated text is a *comment* for the
  human; the digest is the assertion.
- **Geometry lives in `.geom` at whole-point quantisation**, compared with docling's measured
  tolerances — `STRICT_BBOX_TOL_RATIO = 0.0025`, `FUZZY_BBOX_TOL_RATIO = 0.005` of the page extent
  (`docling/tests/verify_utils.py:27-30`) — strict for deterministic drivers, fuzzy for OCR/VLM.
- **A golden file over 256 KiB fails the gate.** If the projection is that big, the projection is
  wrong. (ppt-master's 9,368-line single-class validator is the shape to avoid at every scale.)
- **Goldens are keyed by driver *major* version**, so a driver upgrade *creates* `…/1/` rather than
  mutating `…/0/`. The diff between them is the upgrade review artefact, and it pairs with D2's
  `RebindReport`.
- **The regeneration flag has a test asserting it is off.** Copied verbatim from docling, the only
  repo in the collection that thought of it:

```python
# tests/test_data_gen_flag.py  <- docling/tests/test_data_gen_flag.py, adopted whole
GEN = TypeAdapter(bool).validate_python(os.getenv("OMNIWEAVE_BLESS_GOLDEN", 0))
def test_bless_flag_is_off():
    assert not GEN, "OMNIWEAVE_BLESS_GOLDEN was left on; goldens would self-approve"
```

- **`ow golden bless` requires a reason and writes it.** The commit trailer `Golden-Bless: <reason>`
  is required by a CI check, and a bless touching **> 20 %** of goldens requires a second reviewer (a
  CODEOWNERS rule on `fixtures/golden/`). A reflexive `--bless` is how a golden suite becomes a record
  of what the code does instead of what it should do.

---

## 5. Property tests — round-trip, and the invariants worth generating against

`hypothesis` is already in D1's dev group. Fifty examples per property in PR CI, two hundred nightly,
`--derandomize` off nightly (we *want* new inputs), and every failing example is auto-committed to
`fixtures/fuzz/regressions/` so it becomes a permanent unit test.

| Property | Generator | The bug it exists to catch |
|---|---|---|
| `import(export(store)) == store` | random `Doc`s, not just fixtures | D2's gate, widened: store/archive drift |
| `load(dump(archive))` is tolerant | archives with a missing / corrupt member | docling's `ConversionAssets.load` contract |
| `Quad.from_driver` round-trips within 1 mpt | random (origin, unit, page_h, rotation, dpi) | docling's three live coordinate conventions |
| every `(r,c)` in a `Grid` resolves to exactly one `Origin`; `up(down(r,c)) == (r,c)`; clamping never orphans a slot | random cell sets with overlapping spans | anydoc's exactly-once grid, and its clamp |
| `SpanMap.to_text(RenderSpan(v,a,b))` covers exactly `text[a:b]`; `offsets_of` round-trips | random docs × every serializer | a citation that points at the wrong characters |
| `sha256_canonical`: key order irrelevant, any value change matters, **`["a","bc"] != ["ab","c"]`** | random configs | graphrag's separator-free `gen_sha512_hash` collision |
| `content_digest` invariant under a metadata-only touch | one mutator per format: PDF `/ModDate`+`/ID`, OOXML `cp:revision`/`w:rsid*`/`TotalTime`, MD frontmatter, EXIF | re-billing a VLM pass because someone opened the file |
| `rebind`: `carried + revised + created == |blocks(new gen)|`; every retired block has a `block_history` row | random edits and re-segmentations | codegraph's measured **4.3 % of edges wrong, silently, forever** |
| overlapping `mark`s survive serialize→parse | random overlapping ranges | marker's bold+italic collapse |
| every one of the twelve limits raises `OW_RESOURCE_LIMIT{limit}` naming the right knob, and **never OOMs**, at cap−1 / cap / cap+1 | sized inputs per cap | the `take(N+1)`-then-check rule; markitdown's uncapped `ZipConverter` |
| `addr` / `cite` unique under adversarial `ord` sequences | pathological sibling orders | the `IFNULL(parent_id,-1)` sentinel |

Fuzzing, pragmatically: **we do not own Rust, so we do not write cargo-fuzz targets.** Two cheap things
instead. (a) The nightly runs `cargo fuzz run` against **anydoc's own twelve targets at our pinned
vendored SHA** — `vendor/anydoc/fuzz/fuzz_targets/{csv,doc,docx,epub,numfmt,odf,pdf,ppt,rtf,xls,xlsb,xlsx}.rs`,
verified present — 15 minutes each. Free coverage of the largest attack surface we ship, and the only
defence in the collection that found bugs before shipping. (b) `atheris`/`hypothesis` fuzz the Python
surfaces anydoc does not cover: the format-detection chain, the `.owdoc` archive reader, the config
coercion layer (D1 flags `"false" → True` as a live risk), and the `omniweave-target/1` frame parser.

---

## 6. Determinism, where models are involved

Three declared tiers. The card declares one; the conform `determinism` suite tests **that one**.
Declaring the weakest tier is not a failure; declaring D-0 and failing it is (D3's honesty bar).

| Tier | Declaration | Test | Gate |
|---|---|---|---|
| **D-0 byte-deterministic** | `deterministic = true`, no model | 3 runs, same host: byte equality of the `.tree` projection; plus **cross-platform** equality across D1's 9-cell matrix compared on `content_digest`, not bytes (geometry is i32-quantised precisely so this is possible) | any mismatch fails |
| **D-1 seeded-reproducible** | local model, `temperature = 0`, fixed `seed`, `weights_revision` an exact SHA | 3 runs: `n_mismatched_blocks / n_blocks ≤ drift_band`, where `drift_band` is **measured and written into the card by the kit**, never chosen by the author | drift above the recorded band fails |
| **D-2 statistically stable** | hosted API, no seed available | no equality test. N = 5 repeats over a 30-document slice; report the metric's mean and 95 % CI; **gate on the CI width against `variance_budget`, not on the mean** | a CI wider than the budget ⇒ **the benchmark row is refused**, not published |

The D-2 rule is the one that matters commercially: *you may not publish a number you cannot
reproduce.* HunyuanOCR's 94.10 OmniDocBench — measured on TensorRT while the repo ships Transformers
and vLLM, which it admits disagree — is the case this rule refuses to repeat, and D3-14's mandatory
`measured_on` tuple is where the refusal is enforced.

Two supporting mechanisms, both shipped rather than stubbed:

- **Fault injection is a product feature, not a test helper.** graphrag's
  `_chaos: {failure_rate, exception_type, latency_ms}` rides the middleware pipeline. Without it the
  retry ladder, budget deferral, the futility latch, the crash quarantine (D3: 3 crashes / 60 s) and
  every `degradations[]` path are untested code. D3's `fuzz` suite already ships a deliberate segfault
  fixture (D3-11); `_chaos` extends that to the network and the clock.
- **A frozen clock and a frozen RNG in every test process.** `time.time()` is already semgrep-banned
  in library code (D1's G8); the harness additionally injects a fixed `clock_ns` and asserts no
  `random`/`secrets` import under the routing and eval packages (D4's R2).

---

## 7. CONFIDENCE — three surfaces, three validations, three kill conditions

This is the section the whole decision exists for. The collection's own verdict, from the graph notes:
*"never ship a confidence field with fewer than three consumers — ranking, review surface and
rendering — or it rots into decoration."* I add a fourth requirement that makes the first three
meaningful: **a measured reliability table, refreshed on a clock, with a written kill condition.**

omniweave shows a user or an agent exactly three confidence surfaces. There is no fourth, and in
particular **there is no 0–100 "confidence score" anywhere in the product.**

### 7a. `trust ∈ {ambiguous, inferred, extracted}` — validated as an *ordinal*, and nothing more

`trust` is D2's ordered integer (0/1/2; `MIN()` over a chunk is the chunk's trust). The claim it makes
is **not** a probability. The claim is:

> Blocks marked `extracted` are more often right than blocks marked `inferred`, which are more often
> right than blocks marked `ambiguous`, for this driver family, on this corpus.

That claim is cheap to measure and easy to falsify, which is exactly why it is the one we make.

```
ow eval trust --driver parse.pdf.pdfium --corpus ow-office-v1 --check

trust      n     acc     Wilson 95% CI      verdict
extracted  4118  0.981   [0.976, 0.985]
inferred    902  0.874   [0.851, 0.894]     separated  (0.976 > 0.894)   OK
ambiguous   211  0.612   [0.545, 0.675]     separated  (0.851 > 0.675)   OK
MONOTONIC: pass   (n >= 200 per cell, non-overlapping Wilson 95% CIs)
```

- **Gate:** `lower(extracted) > upper(inferred)` and `lower(inferred) > upper(ambiguous)`, n ≥ 200 per
  cell. Nightly; a regression **fails the build**; a first-time failure on a new driver blocks its
  `[quality]` attestation rather than the framework build.
- **Kill condition, written down:** if a driver family cannot show separation across two consecutive
  releases, that driver's card becomes `confidence = "none"`, the runner writes `trust = AMBIGUOUS`
  for every block it produces, and the review surface stops filtering on it. The tag is **removed**,
  not caveated. D2's `block_review` partial index (`WHERE trust < 2`) then correctly selects
  everything from that driver, which is the truth.
- **Migrations may only downgrade** (D2's rule; graphify's `default="EXTRACTED"` is the bug it fixes)
  — enforced by a test that applies every migration to a fixture store and asserts `trust` is
  non-increasing per `block_id`.

### 7b. `score` + `score_kind` — a registered scale, calibrated or NULL

D2 already ruled `score` and `score_kind` nullable *together*, "since a layout softmax and a token
probability are not comparable." I make the scale a registered object and reuse D4's thresholds
verbatim, so the framework has **one** calibration bar, not two.

```toml
# tools/scorekinds.toml — append-only. An unregistered score_kind is REFUSED AT WRITE TIME.
[garble_p_bad]
domain          = [0.0, 1.0]
semantics       = "P(this text is garbled) for a page's extracted text layer"
consumers       = ["route:garble_escalate", "review:block_review", "serve:low_confidence"]
calibration_set = "ow-calib-v1"
bins            = 10                # equal-mass
ece             = 0.031             # gate: <= 0.05      (D4 R6)
brier           = 0.061             # gate: <= 0.08      (D4 R6)
n               = 4820
measured_at     = "2026-08-19T00:00:00Z"
max_age_days    = 90
diagram         = "scoreboard/calib/garble_p_bad.svg"    # committed, with its CSV beside it

[table_recon]
domain          = [0.0, 1.0]
semantics       = "marker's judge score (purity+no_compound+fill+hdr+2*one_span)/6"
consumers       = ["route:table_accept", "review", "render:trust downgrade"]
calibration_set = "ow-tables-v1"
ece             = 0.044
brier           = 0.072
```

- **Refuse at write time.** `DocSink.add_block` raises if `score_kind` is not in the registry. The
  cheapest possible enforcement, and it stops the field becoming a free-text bag.
- **The dataset split is deterministic, never RNG** (D4's R2 shape):
  `int.from_bytes(blake2b(doc_key + b"ow-split-1").digest()[:2]) % 100` → `< 70` train, `< 85`
  calibration, else test. Committed, reproducible, and **leakage is structurally impossible** because
  the split is a pure function of the document, not of the run.
- **Staleness is a degradation, not an error.** Past `max_age_days` the run manifest carries
  `calibration: stale` and D4's `calibration_stale` degradation fires; the score is still written.
  Refusing to parse because a calibration expired would be worse than the imprecision.
- **Kill condition:** a `score_kind` failing ECE or Brier is **dropped**, not softened — the driver
  writes `score = NULL, score_kind = NULL` (D2's `CHECK ((score IS NULL) = (score_kind IS NULL))`
  makes the pair atomic) and every consumer's UNKNOWN path is exercised. There is no "we shipped it
  but rounded it to three buckets."
- **Keep the score, never the label** (marker/surya's rule): D4 already refuses to register a
  `kind="classifier"` signal whose domain is not `(0,1)`. Same registry, same rule, one place.

### 7c. The user-facing answer state — validated by an *absence corpus*

D9 owns the response envelope; the four-state shape the notes converge on is
`ok | low_confidence | absent | degraded`, where `absent` is reached only after failing ten gates in
precedence order, and one gate governs citability. **I own its measurement**, and the measurement is
the thing nobody in the collection has.

`corpora/ow-absence-v1.toml`, Tier 0, ours, ~400 cases:

- **200 known-absent** questions whose answer is provably not in the corpus — built by *removing* the
  source document from a corpus where we know the answer was, so absence is ground truth *by
  construction*, not by judgement.
- **200 known-present** questions with a gold `cite` (`d7#412`) so a correct answer is checkable.
- **Six hazard slices**, one per silent-zero shape the graph notes name for documents, injected
  deliberately: OCR failed on pages 12–40 · PDF password-protected · table extractor timed out ·
  empty text layer with no OCR fallback · embedding model changed since indexing · block budget
  truncated the response.

```
ow eval absence --corpus ow-absence-v1

                                 n     rate    gate     verdict
false_confident_zero            200    0.005   <= 0.01  PASS   # said absent; the answer was there
unwarranted_absent              200    0.030   <= 0.05  PASS   # said absent; should have said degraded
missed_degradation                6    0.000   == 0     PASS   # a hazard fired and nothing was reported
absent_precision                       0.970
absent_recall                          0.935
citability_violations                  0       == 0     PASS   # cited a block from a non-citable state
```

`false_confident_zero ≤ 1 %` is the number, and the motivating scar is quoted on the scoreboard page:
*"a user got confident zeros over ~1,975 unindexed files and left."* `missed_degradation` and
`citability_violations` are **zero-tolerance** — they are correctness claims, not quality scores.

### 7d. The verbatimness audit — the one metric with no error budget

Serve's most valuable sentence is *"byte-for-byte identical to what the Read tool returns … treat each
block as a Read you have already performed."* D2 makes it conditional on `quote = 'verbatim'`, which
requires `os_kind = 'bytes'` **and** `part.store_ref IS NOT NULL`. The audit turns that from an
invariant into a measurement:

```python
# omniweave_conform/suites/verbatim.py — release gate, plus a nightly sample
def audit_verbatim(store, *, n=1000, salt: str) -> VerbatimReport:
    """Deterministically sample n blocks claiming quote='verbatim' (blake2b(cite||salt) % N),
    re-read part.store_ref, and assert

        decode(part_bytes[os_a : os_a + os_b], os_codec) == block.text

    with DECODE SYMMETRY: the same codec and the same error policy on both sides — never
    text=True on one side and bytes on the other (jcodemunch #400).
    FAILURES ALLOWED: 0.  This is a correctness claim, not a quality score."""
```

Any failure is `OW_ORIGIN_SPAN_DOWNGRADE` on that block, a release blocker, and — because the card is
the test plan — a `capability` suite failure for the driver that declared `origin_span = "exact"`.
That is the §1 amendment doing its work.

### 7e. What is never allowed to become a confidence number

- **`agree.decode_vs_page` is an agreement measure and may never be published as accuracy.** D4 says
  it plainly, and its own open question says it: *"it measures agreement, not truth, and two drivers
  sharing a base model family can be wrong identically."* On the scoreboard it appears in a separate
  column headed **Agreement (not accuracy)**. Only `audit` verdicts — scored against human-verified
  ground truth — populate the accuracy column. D4's R12 (self-report excluded) is the same rule one
  level down.
- **Driver self-report never enters any published number.** Stored, used to gate escalation, excluded
  by the view definition.
- **Never our own output as reference.** anydoc's word-trigram containment against its own output is
  labelled by its own authors *"not a truth measure"*, and we adopt it under exactly that label as a
  **dropped-content detector**, in a column headed *Coverage proxy* — anchored on rendered ground
  truth (`soffice` render + page-image comparison) for anything we call accuracy.

---

## 8. The harness — `.oweval`, one file, one command

The harness core lives in **`omniweave-conform`** (D1's eleventh distribution, deps `core` + `pytest`,
3 MB ceiling) because it shares the corpus loader, the `measured_on` tuple, `normalize_text` and the
metric code with the conformance suites, and because a driver author needs both. The packaged corpus
slice is capped at **2 MB** (≈30 small synthetic files) so the ceiling holds; everything larger is
Tier 0 in the repo or Tier 1 fetched. **Competitor runners are repo-only** (`evals/runners/`), never
packaged — `docling` as a comparison runner drags torch, and D1's weight gates must not be negotiated
for a benchmark.

```sql
-- .oweval — a SEPARATE SQLite file from .owstore. Eval rows get deleted, corpus rows do not, and
-- one eval run spans many stores. Same pragma order (busy_timeout FIRST — codegraph #238).
CREATE TABLE eval_run (
  run_id         TEXT PRIMARY KEY,        -- ULID
  started_ns     INTEGER NOT NULL, ended_ns INTEGER,
  suite          TEXT NOT NULL,           -- parse|office|tables|extract|retrieval|absence|memory|roundtrip
  corpus         TEXT NOT NULL, corpus_version TEXT NOT NULL, corpus_sha256 TEXT NOT NULL,
  runner         TEXT NOT NULL,           -- 'omniweave' | 'docling' | 'markitdown' | 'pandoc' | ...
  runner_version TEXT NOT NULL,
  ow_release     TEXT, code_fingerprint TEXT,
  measured_on    TEXT NOT NULL,           -- JSON, REQUIRED, schema below. No row without it.
  fairness       TEXT NOT NULL,           -- JSON: model, embedder, token budget, max_spend
  spend_micros   INTEGER NOT NULL DEFAULT 0,
  publishable    INTEGER NOT NULL,        -- copied from the corpus manifest
  degradations   TEXT NOT NULL DEFAULT '[]',
  UNIQUE (suite, corpus, corpus_version, runner, runner_version, code_fingerprint, started_ns)
) STRICT;
-- measured_on, REQUIRED on every run (D3-14 generalised):
--   {weights, weights_revision, runtime, runtime_version, sampling, prompt_version,
--    hardware, os, python, timing_mode}
--   timing_mode IN (in_process, spawn_inclusive)   -- anydoc's honesty rule, declared PER ROW

CREATE TABLE eval_case (                  -- olmOCR-Bench's BasePDFTest, generalised
  case_id   TEXT PRIMARY KEY,
  corpus    TEXT NOT NULL, corpus_version TEXT NOT NULL,
  doc       TEXT NOT NULL, part INTEGER,
  type      TEXT NOT NULL,                -- baseline present absent order table math format footnote
                                          -- + ours: cell_rel field span absence roundtrip cite
  spec      TEXT NOT NULL,                -- JSON: the assertion (TableTest's up/down/left/right/…)
  max_diffs INTEGER NOT NULL DEFAULT 0,   -- fuzzy edit-distance budget
  checked   TEXT CHECK (checked IN ('verified','rejected')),  -- HUMAN REVIEW STATE, IN THE RECORD
  url       TEXT
) STRICT;
-- A case with checked IS NULL RUNS but is EXCLUDED FROM EVERY PUBLISHED NUMBER, and the count of
-- excluded cases is printed. Adopted verbatim from olmocr/bench/tests.py.

CREATE TABLE eval_result (
  run_id  TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  case_id TEXT NOT NULL REFERENCES eval_case(case_id),
  passed  INTEGER NOT NULL, explanation TEXT NOT NULL,  -- (passed, explanation) — never a bare bool
  score   REAL, wall_ms INTEGER NOT NULL, micros INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, case_id)
) STRICT;

CREATE TABLE eval_metric (                -- the rolled-up numbers the scoreboard reads
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  slice  TEXT NOT NULL,                   -- 'all' | 'type=table' | 'lang=ja' | 'category=old_scans'
  metric TEXT NOT NULL,                   -- pass_rate|field_acc|fulldoc_acc|recall@10|ndcg@10|…
  value  REAL, n INTEGER NOT NULL,
  ci_lo  REAL, ci_hi REAL,                -- Wilson for rates, bootstrap otherwise. ALWAYS present.
  state  TEXT NOT NULL CHECK (state IN ('OK','REGRESSED','UNKNOWN')),  -- UNKNOWN is the zero value
  PRIMARY KEY (run_id, slice, metric)
) STRICT;
```

```python
# The competitor-runner seam. olmocr/bench/runners/run_*.py is the shape; this is the contract.
class Runner(Protocol):
    NAME: ClassVar[str]; VERSION: ClassVar[str]
    def measured_on(self) -> Mapping[str, str]: ...   # REQUIRED. A runner that cannot fill this
                                                      # tuple cannot appear on the scoreboard.
    def run(self, doc: Path, *, out: Path, budget_micros: int) -> RunnerResult: ...

# Shipped runners (all already written against these tools in anydoc/bench and olmocr/bench):
#   omniweave · markitdown · docling · pandoc · libreoffice-headless · unstructured
# A MISSING runner is SKIPPED WITH A WARNING and a recorded degradation, never silently dropped,
# so a partial setup still produces a usable report (anydoc bench/convert.py's rule).
```

```
# normalize_text — adopted VERBATIM from olmocr/bench/tests.py:47-81, because comparing markdown
# against HTML against OTSL output is impossible without exactly this canonicalisation:
#   <br>, <br/>                       -> " "
#   **bold** __bold__ <b> <i>         -> stripped  (PAIRED regexes, so "**a \n\n b**" is NOT matched)
#   *ital* _ital_                     -> stripped
#   \s+                               -> " "
#   unicodedata.normalize("NFC", ...)
#   ' ' , -> '      " " „ -> "      ＿ -> _      – — ‑ ‒ − -> -      µ -> μ
```

### Metric definitions, per suite

| Suite | Truth metric (deterministic) | Secondary | Never |
|---|---|---|---|
| `parse` | olmOCR-Bench typed assertions, per category, pass rate + macro | wall_ms, micros | an LLM judge as the primary |
| `office` | structure counts (heading/table/list/link/footnote) against **rendered** ground truth | trigram containment as a *coverage proxy*, explicitly labelled not truth | anchoring on our own output (anydoc's flaw) |
| `tables` | relational assertions through `Grid.up/down/left/right/top_heading/left_heading`, O(1) per D2 | `recon_score` distribution | comparing serialised HTML strings |
| `extract` | lift's five adversarial categories; exact match with numeric tolerance; **field accuracy AND full-document accuracy, both, always** | grounded-field fraction | quoting field accuracy alone |
| `retrieval` | recall@{1,5,10}, nDCG@10, MRR, per channel then fused; ceiling-normalised | `channel_contributions` | a raw un-normalised WRR score |
| `absence` | §7c | — | — |
| `memory` | LOCOMO / LongMemEval-S QA accuracy + recall@10, judge-graded with published κ | ingest cost | a judge with no validation |
| `roundtrip` | `import(export(store)) == store`; ppt-master's four fidelity tiers with an asserted sum | `layout_digest` equality | byte comparison of the artefact |

**The lift number is a policy, not a datum.** 90.2 % per field collapsing to **20.9 % full-document**
(`lift/README.md`) is why `ow eval report` **refuses to emit a `field_acc` row without the matching
`fulldoc_acc` row**, and why a release note quoting one without the other fails a lint. Per-field
accuracy does not compound; a product promise of "correct document" needs a verification layer, and
the open weights do not have one.

### CLI

```
ow eval fetch    <corpus>                       # verify per-file sha256; refuse license = "unknown"
ow eval run      --suite office --corpus ow-office-v1 [--runner docling] [--max-spend 5.00]
ow eval report   [--html scoreboard/] [--md] [--since 30d]   # refuses publishable=false rows
ow eval trust    --driver X --check                          # §7a monotonicity gate
ow eval calib    --score-kind garble_p_bad --check           # ECE/Brier + reliability diagram
ow eval absence  --corpus ow-absence-v1                      # §7c
ow eval verbatim --n 1000                                    # §7d, zero tolerance
ow eval regret   --since 7d                                  # §10, clusters from the serve ledger
ow bench         [--compare] [--baseline tools/perf.toml]    # §9
ow golden bless  <path...> --reason "..."                    # §4
```

---

## 9. Performance regression gates, with budgets and an anti-flake rule

The honest problem: **GitHub-hosted runners are too noisy to gate throughput on.** Pretending
otherwise produces a gate that fails randomly, gets marked `continue-on-error`, and is then
decoration. So: **two cheap deterministic metrics gate on every PR; everything else runs nightly on
one pinned self-hosted machine and gates on a rolling median.**

```toml
# tools/perf.toml — every row has a baseline, a tolerance, an owner and a review date.
schema = 1
method = "min-of-5 warm"              # anydoc's rule
runner = "ow-bench-1"                 # ONE pinned machine. A runner change is a baseline reset.
rule   = "fail on 3 consecutive nightly runs above tolerance, comparing 7-run rolling medians"

# ---- PR-gating (deterministic enough) ----
[[metric]]
id = "import.omniweave_core_ms"       baseline = 62    tol_pct = 25   gate = "pr"   # D1 G10
owner = "core"   review_by = "2027-03-01"
[[metric]]
id = "cold.ow_version_ms"             baseline = 118   tol_pct = 25   gate = "pr"
[[metric]]
id = "conform.fast_tier_s"            baseline = 240   tol_abs = 60   gate = "pr"
note = "D3's five-minute rule, enforced as a timing assertion. A skipped gate is not a gate."

# ---- nightly ----
[[metric]]
id = "parse.office.p50_ms"            baseline = 5     tol_pct = 20   gate = "nightly"
note = "anydoc README: 4.4 ms median across 14 formats. timing_mode = in_process."
[[metric]]
id = "parse.office.p95_ms"            baseline = 41    tol_pct = 25   gate = "nightly"
[[metric]]
id = "parse.pdf.digital_pages_per_s"  baseline = 22.0  tol_pct = 15   gate = "nightly"
[[metric]]
id = "rss.gen5000p_peak_mb"           baseline = 1450  tol_pct = 10   gate = "nightly"
note = """THE FORK-TRIGGER GATE. D1 open question #1: anydoc marshals eagerly into Python objects and
py.detach does not cover the marshal. If gil_held_fraction > 0.30 or this budget breaks on a 200-doc
mixed corpus, vendor/anydoc/FORK-TRIGGER.md fires."""
[[metric]]
id = "store.bytes_per_block"          baseline = 660   tol_pct = 10   gate = "nightly"
note = "D2 projects 300k-600k blocks at ~200 MB with FTS5. This is that projection, measured."
[[metric]]
id = "store.wal_peak_mb_bulk"         baseline = 2048  tol_abs = 512  gate = "nightly"
note = "codegraph: 5.9 GB WAL against a 340 MB DB; 22 GB then exit 137. Absolute cap, not a percent."
[[metric]]
id = "query.warm_p50_ms"              baseline = 180   tol_pct = 20   gate = "nightly"   # D1: <= 250
[[metric]]
id = "index.blocks_per_s"             baseline = 4200  tol_pct = 20   gate = "nightly"
```

Three rules that make this survivable:

1. **3-consecutive-run failure, 7-run rolling median.** One slow night is weather; three is a
   regression. The nightly comments on the offending commit range at the first breach and opens an
   issue at the third.
2. **Blessing a perf baseline is an explicit commit with a reason**, same discipline as goldens, and a
   row whose `review_by` has passed fails the gate — a stale baseline is not a baseline.
3. **`timing_mode` is declared per row.** anydoc times markitdown/docling in-process and
   pandoc/LibreOffice spawn-inclusive *"because that's how they're used in practice, and it's called
   out in the report."* We copy the honesty and the disclosure.

Cost is a performance metric. Every nightly writes `spend_micros`, and the scoreboard carries a
**$/1,000 documents** column beside every accuracy column. Publishing accuracy without cost is how a
design silently chooses the 64× retry amplifier (olmocr: `MAX_TOKENS = 8000` × 8 retries, fired *in
parallel* on an idle queue).

---

## 10. Retrieval evaluation, and the ledger that makes it continuous

### Offline: `ow eval run --suite retrieval --corpus ow-retrieval-v1`

- **Per channel, then fused.** recall@{1,5,10}, nDCG@10 and MRR for lexical (FTS5/BM25), structural
  and vector *separately*, then fused. A fusion function reporting only a score is one you cannot
  tune, so every result carries `channel_contributions` and `channel_ranks`.
- **Report `score / ceiling`, never the raw WRR score.** The achievable ceiling is `Σw/(k+1)` and it
  *depends on which channels actually ran*; a perfect two-channel result scores 0.049 and reads as
  "low confidence" against a BM25-shaped curve. The eval asserts the reported confidence is
  ceiling-normalised, and a hardcoded `1/(k+1)` anywhere is a lint error.
- **Ties break on `(-score, id)`**, asserted by a property test that shuffles the input rows 100× and
  requires an identical ranking.
- **Post-filter recall loss is measured explicitly**: run each metadata-filtered query with and
  without over-fetch and report the delta. Silent recall loss shaped exactly like absence is the
  failure this catches.
- **Absence:** §7c, same suite.
- **Memory / QA:** LOCOMO (n = 300) and LongMemEval-S (n = 50), under **graphify's fairness rules
  adopted verbatim** — one model for every LLM role, one shared local embedder, identical token
  budgets, a per-run spend ledger honouring `--max-spend`, and graphs built with no LLM so an unset
  API key produces zero credits. Reported against graphify's published field (LOCOMO recall@10 0.497 /
  QA 45.3 % at ~$1.40 ingest against supermemory's 49.7 % at $15.67; LongMemEval-S 76 %, tying dense
  RAG at **zero** LLM build cost) — and **subject to `publishable`**: if the dataset licence forbids
  it, the number is internal and the scoreboard prints `withheld: corpus licence`.
- **Judge validation is mandatory for any LLM-graded number.** graphify blind-validated its judge
  against a second independent judge at 90.6 % agreement, Cohen's κ 0.81, and publishes it. Our bar:
  **κ ≥ 0.70 on a ≥ 100-case sample, published beside the number, or the number does not ship.** Every
  verdict cites a verbatim quote from the answer, so a grade is auditable rather than one opaque
  score. Grading is key-fact coverage, `(covered + 0.5·partial) / total`. The judge model is
  exact-pinned with a revision; changing it starts a new **epoch**, and prior numbers are either re-run
  or labelled with their epoch — never silently mixed.

### Online: `serve_event` — the ledger, clean-room, with the one column that saves a module

jcodemunch's `ranking_events` is the right idea and its code is unusable at any price (dual-use
licence: no redistribution tier, registry publication forbidden — the notes say reimplement from the
design). Reimplemented, with the two defects its own authors documented fixed at design time:

```sql
CREATE TABLE serve_event (
  ts_ns            INTEGER NOT NULL,
  producer_version INTEGER NOT NULL,  -- ** THE COLUMN THAT MAKES ledger_trust.py UNNECESSARY. **
                                      -- jcodemunch wrote 130 lines of trust heuristics because its
                                      -- ledger had no version column to bound a labelling fix by.
                                      -- One integer per row. Five minutes. Never regret it.
  corpus       TEXT NOT NULL, tool TEXT NOT NULL,
  query_hash   TEXT NOT NULL, query TEXT NOT NULL,  -- hash joins repeats; text is for the human
  returned_ids TEXT NOT NULL,         -- JSON, FIRST 50 ONLY
  returned_n   INTEGER NOT NULL,      -- ** the true count beside the truncated list. **
                                      -- Without it a stored 50 means "50" or "500", and no analysis
                                      -- can exclude the truncated rows or say how many it dropped.
  top1_score REAL, top2_score REAL,   -- top1-top2 is the DISAMBIGUATION GAP: a distinct failure mode
  answer_state  TEXT NOT NULL,        -- ok|low_confidence|absent|degraded  (D9's)
  channels_ran  TEXT NOT NULL,        -- JSON: which channels actually ran, so the ceiling is known
  index_stale   INTEGER NOT NULL,     -- recorded AT QUERY TIME; retrospective analysis is impossible
  redelivered_spans INTEGER NOT NULL DEFAULT 0,
  redelivered_tokens_est INTEGER NOT NULL DEFAULT 0
) STRICT;
```

`ow eval regret --since 7d` mines it, read-only, into clusters: the same `query_hash` asked N times, a
low top1, a thin top1−top2 gap, a high stale rate. Clusters are **suggestions, never applied** — they
produce a diff a human commits, exactly as D4's `route propose` does. Retention 30 days by default,
`query` text hashed-only under `[telemetry] store_query_text = false`, and **nothing leaves the
machine, ever** — no beacon, no default-on telemetry, asserted by D1's G15 egress gate. (jcodemunch
posts token savings to a vendor URL unless disabled; a local-first claim dies on the first default-on
beacon.)

---

## 11. The public scoreboard, as an adoption asset

`ow eval report --html scoreboard/` → a static site generated from `.oweval`, published on tag to
GitHub Pages. No app, no database, no service. It is a build artefact.

What is on it, and why each thing is there:

1. **Head-to-head tables** — omniweave against markitdown, docling, pandoc, LibreOffice and
   unstructured on office; against the olmOCR-Bench category set on PDF; against BM25 / dense / hybrid
   RRF on retrieval. **Every competitor number is one we ran ourselves, on our harness, at a named
   version and commit.** We never quote a README.
2. **Every row links to four things**: the corpus manifest and version, the `measured_on` tuple, the
   exact command, and `results.jsonl.zst` — the raw per-case export. A number you cannot drill into is
   marketing.
3. **`UNKNOWN` is the zero value.** A cell with `n < min_n` shows `UNKNOWN`, not a number. On day one
   the page is mostly UNKNOWN, which is the truth, and it fills in visibly — which is itself the
   adoption story.
4. **A cost column beside every accuracy column**, and an ingest-cost row. graphify's strongest
   presentational choice: 45.3 % QA at ~$1.40 against supermemory's 49.7 % at $15.67 makes an argument
   the accuracy column alone cannot.
5. **Judge validation published** — κ, agreement, sample size — for every LLM-graded row.
6. **"Agreement (not accuracy)"** as a separately headed column, so `agree.decode_vs_page` can never
   be read as ground truth.
7. **A row we publish against ourselves: "What licence compliance costs."** The ~4-point olmOCR-Bench
   gap between surya (83.3 %) and olmocr (~79 %) is *the price of `MODEL_LICENSE` clause 2(c)*, stated
   as such, with the clause quoted. Publishing your own weakness with its reason is worth more than
   four points, and it pre-empts the comparison a competitor would otherwise make for us.
8. **A known-limitations block** carrying: `origin_span: exact` is a minority of blocks, and which
   drivers achieve it; `layout.class_hist` is absent until a licence-clean layout detector lands
   (D4), so `REPAIR` is thin on the PDF path; the calibration set is ours and `garble.score` will be
   miscalibrated on a corpus unlike it.
9. **`withheld: corpus licence`** wherever a Tier-1 dataset's terms forbid publication.
10. **`ow eval run --corpus ./mine`** as the page's call to action, with the exact command. The most
    persuasive number is the one the reader produces on their own documents.

---

## 12. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| Q1 | Every fixture has a licence record. | Gate G17 (`tools/gate_fixtures.py`): a file in `fixtures/` with no `.meta.toml`, or `spdx = "unknown"`, fails the build; `fixtures/NOTICE.md` is generated and `--check` gated |
| Q2 | `fixtures/` never exceeds 64 MB; no golden exceeds 256 KiB. | Same gate. Large fixtures are generated at test time into `$OMNIWEAVE_HOME/fixtures-cache/` |
| Q3 | Every benchmark number carries `measured_on`, including `timing_mode`. | `eval_run.measured_on` is NOT NULL and schema-validated; `Runner.measured_on()` is a protocol method; D3-14 on cards |
| Q4 | No published number is scored against omniweave output. | `ow eval report` refuses a metric whose `reference_runner == 'omniweave'`; the coverage-proxy column is separately headed |
| Q5 | A case with `checked IS NULL` is excluded from published numbers, and the count is printed. | Report query filter + a printed `excluded_unreviewed` line |
| Q6 | An unregistered `score_kind` cannot be written. | `DocSink.add_block` raises against `tools/scorekinds.toml`; a unit test asserts the raise |
| Q7 | A probabilistic score is calibrated: ECE ≤ 0.05, Brier ≤ 0.08, 10 equal-mass bins, n ≥ 1,000. | `ow eval calib --check` nightly (D4's R6 thresholds — one pair for the whole framework); a regression fails the build |
| Q8 | Calibration and eval sets never overlap. | The split is `blake2b(doc_key ‖ "ow-split-1") % 100`; a test asserts an empty intersection over the whole corpus |
| Q9 | `trust` is ordinally separated or it is deleted. | `ow eval trust --check`: non-overlapping Wilson 95 % CIs at n ≥ 200/cell; two consecutive failures ⇒ the card becomes `confidence = "none"` |
| Q10 | Migrations may only downgrade `trust`. | A test applies every migration to a fixture store and asserts `trust` is non-increasing per `block_id` |
| Q11 | `quote = 'verbatim'` is byte-true, with zero tolerance. | `ow eval verbatim --n 1000` on every release plus a nightly sample; failure ⇒ `OW_ORIGIN_SPAN_DOWNGRADE` and a `capability` suite failure for the declaring driver |
| Q12 | A confident zero is measured, not assumed. | `ow eval absence`: `false_confident_zero ≤ 0.01`, `missed_degradation == 0`, `citability_violations == 0` |
| Q13 | The golden bless flag is off in CI. | `test_bless_flag_is_off`; a `Golden-Bless:` trailer required; > 20 % of goldens ⇒ a second reviewer via CODEOWNERS |
| Q14 | A perf baseline is fresh and blessed deliberately. | `tools/perf.toml` rows carry `owner` and `review_by`; a past-date row fails `ow bench`; blessing is a commit |
| Q15 | A perf gate fails on 3 consecutive nightly breaches of a 7-run rolling median, never on one run. | `ow bench --gate` reads the last 7 nightly rows from `.oweval` |
| Q16 | A driver's `[quality]` rows are reproducible. | The attestation covers `(card − attestation) ‖ corpus_version`; `ow eval --driver X --suite omniweave-golden --version <v>` reproduces them; the kit runs from a trusted tag (D3-23) |
| Q17 | An LLM-graded number ships with judge validation. | `ow eval report` refuses a judge-sourced metric with no `kappa ≥ 0.70` at n ≥ 100 in the same run |
| Q18 | A dataset whose licence forbids publication cannot reach the scoreboard. | `corpora/*.toml publishable`; the renderer prints `withheld: corpus licence` |
| Q19 | Every derived and telemetry row carries `producer_version`. | `NOT NULL` on `serve_event`; a schema test asserts the column on every table under `evals/` |
| Q20 | A truncated column has a true-count companion. | `serve_event.returned_n`; a schema lint rejects any `*_ids TEXT` column with no sibling `*_n INTEGER` |
| Q21 | The fast conformance tier stays under five minutes. | `conform.fast_tier_s` in `tools/perf.toml`, gated on PRs — D3's own rule, given teeth |
| Q22 | Nothing in the eval path egresses without a declared host. | D1's G15 plus `[telemetry] enabled = false` as the shipped default, with a socket-blocked conformance run |
| Q23 | `field_acc` never ships without `fulldoc_acc`. | `ow eval report` refuses the pair-incomplete row; a release-note lint scans for the same |

---

## 13. Build order — four phases, each shipping something a real user runs

| Phase | Weeks | Built | The user-visible thing |
|---|---|---|---|
| **P1** | 1–3 | Tier-0 `fixtures/` + generators + `.meta.toml` + gate G17 · the pytest/hypothesis layout and the §5 property list · the `.tree`/`.geom`/`.diag` golden projections + `ow golden bless` + the bless-flag test · `.oweval` schema + `eval_case` + `normalize_text` | **`ow eval run --suite office --corpus fixtures/` prints a per-category pass table.** A driver author can measure their driver in week 3. |
| **P2** | 4–6 | `ow bench` + `tools/perf.toml` + the pinned nightly runner · the three PR-gating perf metrics · competitor runners (markitdown, docling, pandoc, LibreOffice, unstructured) · `nightly.yml`, one file | **`ow bench --compare` prints the head-to-head office table** — the first number we can defend in public. |
| **P3** | 7–10 | `corpora/*.toml` + `ow eval fetch` · olmOCR-Bench + the lift-shaped extraction suite (field **and** full-document accuracy, always both) · `ow-absence-v1` + `ow eval absence` · `tools/scorekinds.toml` + `ow eval calib` + reliability diagrams · `ow eval trust` · `ow eval verbatim` · `ow eval report --html` | **The first public scoreboard** — mostly UNKNOWN, and honest about it. |
| **P4** | 11–14 | `serve_event` + `ow eval regret` · the `agree` channel wired into D4's `route_verdict` · LOCOMO + LongMemEval-S under the fairness rules with judge validation · release notes generated from `.oweval` | **`ow eval regret --since 7d`** — the system tells you which of your queries it is failing. |

**≈14 engineer-weeks for one engineer, plus a standing ~0.2 FTE** owning the corpora, the judge and
the calibration sets. No phase's first deliverable is more than three weeks out. Zero new runtime
dependencies in shipped code: `sqlite3`, `blake2b`, `tomllib` and `statistics` are stdlib;
`hypothesis` and `pytest` are already in D1's dev group; the Levenshtein behind fuzzy matching is a
40-line DP.

---

## 14. What this costs, stated plainly

- **CI wall clock:** +5 min on every PR (golden + perf-cheap + conform-fast) on top of D1's ~6, so
  ~11 minutes. Nightly: ~90 minutes on one machine.
- **One pinned self-hosted runner.** A small dedicated box (~$40/month, or a spare workstation).
  Without it the throughput numbers are noise and the gate is theatre. This is the single
  non-negotiable operational cost in the design.
- **Money per nightly:** ~$0 for the free/local path (olmocr self-hosted is <$200/1M pages, so ~$0.28
  for olmOCR-Bench's 1,400 documents). The billed path runs on a deterministic 10 % slice
  (`blake2b(case_id ‖ salt) % 10 == 0`) nightly and in full only on release tags; the memory suites
  are ~$2–20 per run under `--max-spend`. Budget **$150/month** and cap it *in the harness*, not in a
  policy document.
- **Repo size:** ≤ 64 MB of fixtures. No git-LFS, no vendored corpora.
- **`.oweval` growth:** ~200 B per `eval_result`. 7,000 cases × 6 runners nightly ≈ 8 MB/night;
  retention 30 days for nightly and 400 days for release runs, swept ⇒ ≈ 1 GB steady state.
- **Human time:** ~2 person-days to label the initial calibration set (D4 already budgets this for
  `garble.score`); ~3 person-days to build `ow-absence-v1` and `ow-extract-v1`; ~1 day per quarter to
  re-verify judge κ and refresh calibration.
- **A standing tax on driver authors:** a green conformance report before a driver is auto-selectable.
  That is D3's cost, not mine — but I am the one making it bite.

---

## 15. Failure modes — including the input that breaks this

1. **A synthetic Tier-0 corpus overfits and the framework looks better than it is.** Generated
   fixtures are clean by construction, and D2's own open question — does 60–120 blocks/page hold on
   real dense corpora? — is the same doubt. Mitigation: at least **40 % of Tier-0 `docs/` must be
   `public_domain` real scans**, enforced by a count in gate G17. A mitigation, not a fix.
2. **`ow eval run --corpus ./mine` becomes the only number anyone quotes, and it is unverifiable.**
   The Tier-2 escape hatch is our best adoption asset and our worst evidence hygiene. Mitigation:
   reports from a Tier-2 corpus are watermarked `corpus: local, unverifiable` in every output format.
3. **The judge changes and every historical number shifts under us.** Mitigation: an exact-pinned
   judge with a revision; a change starts a new epoch; the scoreboard shows the epoch and the renderer
   refuses a cross-epoch comparison. This will still confuse somebody.
4. **`--bless` becomes a reflex** and the golden suite records what the code does, not what it should.
   The reason trailer and the 20 % second-reviewer rule slow it. Nothing stops a determined team.
5. **The perf gate flakes and gets disabled.** The 3-consecutive-run rule and the single pinned runner
   are the whole defence. If the runner is shared, or moves to a hosted VM, the gate dies within a
   quarter.
6. **The calibration set is unlike the customer's corpus, so the confidence is confidently wrong.** A
   corpus that is 80 % Thai, heavily typeset mathematics, or 1970s typewriter scans reads as
   "everything escalates" or "nothing escalates". D4 says this about `garble.score` and it is equally
   true of every `score_kind`. The known-limitations block states it, per-slice reporting exposes the
   drift, and the model-free signals (`decode.cid_ratio`, `decode.replacement_ratio`) keep working.
   There is no fix, only disclosure.
7. **The absence corpus is gameable.** A system that answers `absent` more often scores better on
   `false_confident_zero` and worse on `unwarranted_absent`; both are reported and the second is
   gated, but a determined tuner can sit between them. Mitigation: the 200 known-present cases and
   `absent_precision`/`absent_recall` are reported together, always, in one block.
8. **The input that actually breaks this design:** *a single high-value document class that is 0.5 %
   of the corpus and 90 % of the business value* — a rate schedule, a covenant table, an invoice
   total. Deterministic sampling at 0.5 % puts ~1 case of it in the audit; every aggregate metric stays
   green; per-field confidence looks fine because the VLM is confidently wrong. D4 names this exact
   hole: *"a VLM that transposes an invoice total passes every Acceptor and escalates 0 %."* Nothing
   here catches it. The honest answer, and the only one: **the audit sampler must be stratifiable by a
   user-declared document class** (`[audit.strata]` in `omniweave.toml`, with a minimum n per stratum),
   and the documentation must say that omniweave measures aggregates and the customer must name their
   high-value classes. Written as a limitation, not hidden.
9. **The eval harness itself has a metric bug and we rank ourselves first.** The `quality` suite in
   `omniweave-conform` scores a set of *deliberately wrong* outputs — a dropped page, a transposed
   table, a hallucinated field, an empty result — and asserts the exact expected scores. A benchmark
   harness with no tests is how a self-flattering metric ships.
10. **Nobody reads the scoreboard.** It is a static page generated on tag. If nobody looks, the cost
    was P3's four weeks and the internal gates still work. The cheapest failure in the list, which is
    why the scoreboard is P3 and not P1.

---

## 16. Rejected alternatives

- **A separate evaluation service, dashboard app or hosted results database.** A second product with
  its own uptime, auth and CSRF surface (open-slide needed a 76-line request guard for a *local*
  writer). A SQLite file and a static site do everything a small team needs and cost nothing to run.
- **A twelfth distribution for the eval harness.** D1 fixed eleven distributions with one shared
  `RELEASE` and version agreement as CI job 1 (G5). A twelfth for a benchmark nobody `pip install`s
  buys a release-coordination tax and zero users. The harness core goes in `omniweave-conform`; heavy
  competitor runners stay in `evals/`, unpackaged, so docling's torch never touches a weight gate.
- **Coverage percentage as a gate, and mutation testing.** Coverage measures which lines ran, not
  which invariants hold; a 90 % target produces tests written to move a number. The property list in
  §5 and the invariant table in §12 are the coverage target. Mutation testing over a codebase with a
  5,000-page fixture is a nightly that never finishes.
- **A full benchmark as a PR gate.** olmOCR-Bench is 7,000+ cases over 1,400 documents. As a PR gate
  that is a 40-minute job that gets `continue-on-error`'d within a quarter. Nightly, plus a
  deterministic fast slice on PRs touching a parser, is the version that survives.
- **Sixty workflow files.** `local-deep-research/.github/workflows/` has 60. Every one was justified;
  collectively they are unmaintainable and nobody knows which is authoritative. One `ci.yml` (seven
  jobs) and one `nightly.yml` (five jobs).
- **Quoting upstream README numbers.** marker's 76.0 %, surya's 83.3 %, HunyuanOCR's 94.10 —
  `grep -rn "revision=" marker/ surya/ lift/` returns **zero hits**, so the benchmarked checkpoint is
  not the served one; and HunyuanOCR's number came from TensorRT while the repo ships Transformers and
  vLLM, which it admits disagree. We run every comparison ourselves or we print nothing.
- **LLM-judge-only evaluation.** Cheap, fast, unfalsifiable. Every suite anchors on a deterministic
  assertion (olmOCR-Bench's typed tests, lift's exact-match-with-tolerance, relational cell queries)
  and uses a judge only where no deterministic anchor exists — and then only with published κ.
- **Deterministic-only evaluation.** The symmetric error. It cannot measure "did the summary say the
  right thing", which is half of what an agent framework does.
- **A user-facing 0–100 confidence score.** Three surfaces, no fourth. A single blended number is
  uncalibratable by construction (it mixes a layout softmax, a token probability and an index
  freshness state) and, once shipped, can never be removed because a customer has built a threshold
  on it.
- **`agree.decode_vs_page` as the accuracy metric.** It is ~40× cheaper per labelled point than an
  audit and lands exactly on the suspect population — and it measures agreement, not truth. It gets
  its own column. D4's open question is right to hold `auto_demote` to `audit` verdicts until the
  correlation is measured.
- **Vendoring benchmark corpora into git.** A 2 GB clone is a repo nobody contributes to, and
  redistributing an ODC-BY or CC-BY-NC dataset is a licence decision made by accident. Pointer
  manifests with per-file digests, plus `ow eval fetch`.
- **A `--force` or a global `--skip-gates`.** Overrides are named per check
  (`--allow-golden-drift`, `--allow-uncalibrated-score`, `--accept-stale-baseline`), because *"an
  override flag whose scope is 'skip whatever check just complained' is not an override, it is an off
  switch."*
- **`warnings.warn` for quality signals.** Filterable, unstructured, invisible under JSON logging —
  graphify's receipt. Every quality finding is a `degradations[]` entry in the run manifest and a row
  in `.oweval`.
