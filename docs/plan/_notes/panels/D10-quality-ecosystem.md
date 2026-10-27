# D10-quality — Quality, evaluation, testing and trust
### Ecosystem & operator proposal

---

## Headline

**Quality is a distribution, not a directory.** omniweave ships `omniweave-eval` (harness, reducers,
cassettes, calibrator, scoreboard generator) and five `omniweave-corpus-*` distributions whose every
fixture carries a licence ledger row, so an outside contributor runs *the exact gate CI runs* with
`uv sync && pytest` — offline, GPU-free, under ten minutes. Three mechanisms carry the whole design:
**goldens are reductions with declared volatility tiers**, never document blobs; **every model call in
CI is a content-addressed cassette replay**, so a laptop with no CUDA is a first-class dev
environment; and **a `score` may never be rendered as a probability until a calibration curve exists
for its `score_kind` on a named eval set** — with the labels for that curve harvested for free from
native OOXML text and from born-digital text layers rendered back to pixels, which is what makes
calibration affordable rather than aspirational. Every published number carries a complete
`MeasuredOn` tuple or the writer refuses it; truth is never our own output; and the public scoreboard
publishes what it *could not* measure beside what it did, defaults to sorting by accuracy-per-dollar
within a licence tier, and marks every row `reproduced` or `self_reported`.

---

## 0. What I inherit, and two conflicts I must flag

### 0.1 Inherited verbatim (I do not re-open any of it)

| From | What I take and use by its own names |
|---|---|
| **D1** | `sha256_canonical` (`allow_nan=False`, sorted, separator-safe); `codes.toml` append-only; gate G10's per-OS cold-start baselines with **25% drift tolerance**; the `fixtures/` seed set (40-byte docx, encrypted pdf, zip bomb, 4M-cell xlsx, fuzz corpus); `--bless` as the existing verb for golden refresh (`schema/expected/`); `tools/weights.toml`, `tools/layers.toml`; `$OMNIWEAVE_HOME`; console scripts `omniweave` and `ow` (aliases; I write `ow`) |
| **D2** | `Block`, `addr`, `cite`, `content_digest`/`layout_digest`, `trust ∈ {AMBIGUOUS,INFERRED,EXTRACTED}` as an ordered IntEnum, `quote` tiers, `Method`, `Capabilities`, `Diag` + its closed code registry, `Grid.up/down/left/right/top_heading/left_heading`, `Producer`, `owcheck` (~240 ns/block), the two existing CI gates `import(export(store)) == store` and `write(read(b)) == b`, `page.parse_score/layout_score/table_score/ocr_score`, `RebindReport` |
| **D3** | `omniweave-conform` and its **eleven suites** (`card purity contract capability idempotence determinism limits sandbox cost licence fuzz`) and the **five-minute mandatory-tier budget**; `driver.toml`; `DriverCard`; `attestation`; `MeasuredOn` as a *required* field on every benchmark row (D3-14); `Service` / `io.service(name)` as the only model seam a driver has; `restriction_bits`; `LicenceTier`; the explicit grant **"D10 (quality) owns the golden corpus"** |
| **D4** | `Rung`/`Lane`/`Slice`; `Spend`/`PriceBook`; `route_decision`/`route_verdict`/`route_spend`; `Scoreboard` with `UNKNOWN` as the zero value; the audit sampler `blake2b(unit_uri‖part‖salt) % 10000 < rate*10000`; `agree.decode_vs_page`; **ECE ≤ 0.05 and Brier ≤ 0.08** as the calibration bar; `[calibration] eval_set_id`, `max_age_days = 30`, `calibration: bootstrap`; `Degradation(kind="calibration_stale")`; R12 (driver self-report never enters the Scoreboard) |

D4's open question — *"Does `agree.decode_vs_page` correlate with human judgement well enough to drive
`auto_demote`? … Settled by scoring both channels against a human-labelled eval set built on
olmOCR-Bench's `TestType` taxonomy plus lift's adversarial extraction categories, reporting the
correlation per slice"* — is a named deliverable of this proposal (`ow eval correlate`, phase E3).
D3's open question about a licence-clean corpus producing olmOCR-Bench-comparable numbers is
answered in §3 and §9.

### 0.2 CONFLICT 1 — D3 asks the conformance kit to write benchmark rows it cannot afford to measure

D3 Spec/Conformance states two clauses that cannot both hold:

> "`[cost]` and `[quality]` are kit-written."

> "The mandatory tier must run in under five minutes on a laptop, enforced as a CI timing assertion,
> because a skipped gate is not a gate."

and its card example carries

> `[[quality.benchmark]]` / `suite = "omniweave-golden"; version = "2026.09"; slice = "office"` /
> `metric = "structure_f1"; value = 0.94`

A `structure_f1` over a corpus large enough to be worth publishing cannot be produced in five laptop
minutes; and D3-13's publish gate — *"Publish gate rejects author-written values"* — would then
reject the value written by the only tool that can produce it. Today the card either carries a
number measured on a corpus too small to mean anything, or it carries a hand-written number the gate
is supposed to refuse.

**Minimum amendment (one clause, nothing else in D3 changes).** Split the kit-written block by
writer:

- `omniweave conform` writes `[cost]` and `[quality].suites` and `[quality].kit_version` /
  `kit_run`. Five-minute budget unchanged.
- `omniweave eval` writes `[[quality.benchmark]]` rows. No time budget; it is a nightly/on-demand
  tool.
- `attestation` is `sha256` over the canonical card minus `attestation`, recomputed by whichever tool
  wrote last; the publish gate names **both** tools as permitted writers of their own blocks and
  still rejects author-written values in either.

D3-13 and D3-14 keep their full force. D3-14 ("every benchmark row carries its `measured_on` tuple")
becomes invariant **Q1** below, with the HunyuanOCR TensorRT row as its regression fixture.

### 0.3 CONFLICT 2 — D1's literal "eleven distributions" is already false and this decision makes it more false

D1 Decision: *"eleven first-party distributions sharing a single `RELEASE` version"* and
*"Day one builds eleven `py3-none-any` wheels on one runner."* D3 has already added
`omniweave-ports` and `omniweave-index`. This proposal adds `omniweave-eval` and five
`omniweave-corpus-*`. G5 ("every version declaration site agrees") and G2 ("no distribution exceeds
`tools/weights.toml`; aggregate ≤ 250 MB") are ambiguous about the new rows: a PDF fixture corpus is
~240 MB of data and would blow G2 read literally, while being nowhere near a runtime install.

**Minimum amendment.** Replace the count with the rule, and add one gate:

- **Rule:** every first-party distribution carries `RELEASE`, is `py3-none-any`, has a row in
  `tools/weights.toml` and a row in `tools/layers.toml`. The number is whatever the rows say.
- **`tools/weights.toml` gains a `tier` column: `runtime | dev | data`.** G2's 250 MB aggregate
  applies to `runtime` only. `data` rows declare a ceiling but are excluded from the aggregate.
- **New gate G17:** no distribution reachable from `omniweave[recommended]` may depend on a `dev` or
  `data` distribution. `omniweave_eval` gets a `layers.toml` row and **no runtime package may list
  it as an allowed import** — the import-graph gate G4 already enforces this shape.

Without the amendment, adding the eval tooling is either a G2 violation or an undocumented exception,
and undocumented exceptions are how the licence gate got a `--warn-only` flag in every project that
has one.

### 0.4 Inherited naming inconsistency (flagged, not mine to settle)

D1 names the driver manifest `omniweave-driver.toml` with registry keys `<kind>.<family>.<impl>` over
seven kinds; D3 names it `driver.toml` with `<port>.<subject>.<impl>` over five ports. I use **D3's**
throughout as the later and more specific ruling on drivers, and nothing in this design depends on
which way the charter resolves it. Similarly D1's `Registry`/`discovery` and D3's `Catalog`/`resolve`
overlap; I read against D3.

### 0.5 One clarification inside my grant

D3's layout puts `corpus/{formats/,adversarial/,LICENCES.md}` inside `omniweave-conform`. D3 also
rules that **D10 owns the golden corpus**. I exercise that grant: the corpus lives in
`omniweave-corpus-*` distributions, and `omniweave-conform` declares
`dependencies = ["omniweave-corpus-core"]` and re-exports it as `omniweave_conform.corpus`. Zero
change to D3's suites, its five-minute budget, or its "the card is the test plan" thesis; it stops
two distributions from owning one licence problem.

---

## 1. The test pyramid, as time budgets and pytest markers

An untimed tier is a tier that will be skipped. Every tier below has a **wall-clock budget asserted
in CI as a correctness test** — D3 already established that mechanism for conform's mandatory tier
and named "the kit rots or gets skipped" as a real risk; I apply it to all six tiers.

| tier | marker | contents | budget | gate class |
|---|---|---|---|---|
| **T0 unit** | *(none)* | pure functions: `sha256_canonical`, `Quad.from_driver`, `build_grid`, `compute_tier`, the rule compiler, `normalize_text`, config coercion, the `Diag` code registry, every reducer | **20 s** | every PR, exact |
| **T1 property** | `property` | ten hypothesis laws (§2.4) | **90 s** | every PR, exact |
| **T2 golden** | `golden` | reductions over `corpus-core`, cassette replay of the model paths, counter gate, cold-start budgets (D1 G10) | **4 min** | every PR; `frozen` exact, `tracked` needs a bless |
| **T3 conform** | `conform` | D3's eleven suites, mandatory tier, first-party drivers | **5 min** (D3) | every PR |
| **T4 eval** | `eval` | the four suites over the full corpora, live models, adapters, scoreboard rows | nightly, ~40 min on one A10G-class runner | ratchet + publish; never blocks a PR directly |
| **T5 soak** | `soak` | fuzz targets, the 5,000-page RSS fixture, the 4M-cell xlsx, the 200-document anydoc-marshal benchmark (D1's open question #1) | weekly, ~3 h | files issues; non-blocking |

```toml
# packages/*/pyproject.toml (shared via the workspace dev group)
[tool.pytest.ini_options]
addopts = "-m 'not eval and not soak and not gpu and not network' --strict-markers -p no:randomly"
markers = [
  "property: hypothesis laws (T1)",
  "golden:   reduction/golden comparisons (T2)",
  "conform:  omniweave-conform suites (T3)",
  "eval:     full-corpus evaluation, live models (T4)",
  "soak:     fuzz, RSS, long-horizon (T5)",
  "gpu:      requires a CUDA device",
  "network:  requires egress (recording cassettes, fetching external corpora)",
  "toolchain: requires an installed Node toolchain",
]
```

**The contributor claim, stated as a CI job.** `.github/workflows/ci.yml` gains a job
`contributor-parity`: a clean container, **no network** (egress blocked at the runner, reusing D1's
G15 socket-blocked harness), no GPU, no Node, `uv sync && pytest`. It asserts green **and** asserts
wall time ≤ **10 minutes**. That job is the promise; everything in §2 and §4 exists to keep it true.
If it goes red or slow, the ecosystem story is broken and we find out on the PR that broke it, not
from a GitHub issue three months later.

---

## 2. Goldens: reductions, not blobs

### 2.1 The problem, stated with D2's numbers

Parser output is large and noisy. D2's own arithmetic: 5,000 A4 pages at 60–120 blocks/page is
**300k–600k blocks**, ~200 MB of `.owstore`; a 4M-cell spreadsheet is 4M blocks. Even a
*document*-scale snapshot is a diff nobody reads. And it jitters: a pdfium patch moves every `quad`
by fractions of a point, which is precisely why D2 quantizes `layout_digest` to whole points and
excludes geometry from `content_digest`.

A golden that changes on every dependency bump is a golden people delete.

### 2.2 Three reductions, three volatility tiers

A **Reduction** is a deterministic, line-oriented, sorted projection of one document's rows out of an
`.owstore`. Three exist; each declares a **volatility tier** that decides how CI treats a diff.

| reduction | tier | contains | changes when |
|---|---|---|---|
| `shape` | **frozen** — byte-diff fails the build | counts and quantized aggregates only. No text, no per-block geometry. | the parser's *structural* behaviour changed |
| `outline` | **tracked** — diff is rendered into a PR comment; merge requires a blessed reason | one line per block: `addr kind layer trust quote sha1(nfc(text))[:8] "48-char preview"` | any block's identity, order, classification or text changed |
| `text` | **informational** — recorded, never gates | `serialize(fmt="md")` output plus its `view_id` | anything at all |

```
# eval/goldens/core@2026.09/parse.doc.anydoc@3/eu-annual-report-2019.shape
owshape/1  corpus=core@2026.09  doc_key=3f2a…  driver=parse.doc.anydoc@0.2.4  schema_v=3
achieved.origin_span      exact
achieved.spatial          none
achieved.tables           cells_with_spans
blocks.total              1284
blocks.kind.caption         14
blocks.kind.heading         61
blocks.kind.list_item      118
blocks.kind.paragraph      902
blocks.kind.table            6
blocks.kind.table_cell     174
blocks.layer.body         1201
blocks.layer.furniture      83
diag.OW_TABLE_SPAN_CLAMPED   2
grid.tables_with_merges      1
grid.slot_rows              60
marks.kind.bold            311
marks.kind.link             48
pages.total                 42
quad.present_frac         0.0000
quote.normalized           382
quote.verbatim             902
rel.kind.caption_of         14
rel.kind.note_ref           27
trust.ambiguous              0
trust.extracted           1240
trust.inferred              44
```

```
# eval/goldens/core@2026.09/parse.doc.anydoc@3/eu-annual-report-2019.outline
owoutline/1  corpus=core@2026.09  doc_key=3f2a…  driver=parse.doc.anydoc@0.2.4  schema_v=3
# blessed: 2026-08-14T09:22:31Z team@particle6.com  "anydoc 0.2.5: footnote linkage now emits
#          rel(note_ref); 44 new rel rows, 0 block changes"
p0/0        section     body  ext  norm  -         children=6
p0/0/0      heading     body  ext  verb  1a2b3c4d  "Annual Report 2019"
p0/0/1      paragraph   body  ext  norm  9f0e1d2c  "The Union's fiscal position in the reporting…"
p0/1        page_footer furn  ext  verb  cc11aa22  "EN    2    EN"
p3/2        table       body  inf  recon 4c5d6e7f  12x5 merges=1 recon=native_xml/1.00
p3/2/r0c0   table_cell  body  ext  verb  aabbccdd  "Member State"
p3/2/r0c1   table_cell  body  ext  verb  bbccddee  "2018"
```

**Design rules that make this work:**

1. **`sha1(nfc(text))[:8]` plus a 48-character preview, never the text.** A one-word fix is one
   changed line a reviewer can read. Full text lives in the `informational` `text` reduction.
2. **No geometry in `frozen`.** `quad.present_frac` is a fraction; per-corner values are never
   emitted. A T2 test asserts that two pdfium minor versions produce **byte-identical** `shape`
   reductions over the fixture corpus. This is exactly D4's open question about signal drift across a
   pdfium minor, and answering it costs nothing extra.
3. **Sorted, LF-normalized, deterministic float formatting** (four significant digits, `%.4f` for
   fractions, never a repr). CRLF normalization on read, because a Windows checkout must not read as
   a diff — hyperframes' `hashSkillBundle` already learned this and the mining notes record it.
4. **The header line is part of the golden.** `corpus@version`, `doc_key`, `driver@version`,
   `schema_version`. A golden compared against the wrong driver version fails loudly rather than
   diffing garbage.

### 2.3 Blessing, and why it has a mechanical shell

`schema/expected/` in D1 already has a `--bless`. I generalize it and add the one thing that keeps a
bless from becoming a rubber stamp: **a reason, in an append-only ledger, diffed against the previous
tag** — the same mechanic D1 uses for `codes.toml` (G13) and D3 uses for tombstone `review_by`.

```
$ ow eval bless --corpus core --driver parse.doc.anydoc \
    --reason "anydoc 0.2.5: footnote linkage now emits rel(note_ref); 44 new rel rows, 0 block changes"
  4 files updated · 1 frozen (shape) · 3 tracked (outline)
  wrote eval/goldens/BLESS.log  (append-only)
```

```
# eval/goldens/BLESS.log — append-only; CI diffs it against the previous tag (G13's mechanic)
2026-08-14T09:22:31Z  team@particle6.com  core@2026.09  parse.doc.anydoc  4  9f3c1a2  "anydoc 0.2.5: footnote linkage now emits rel(note_ref); 44 new rel rows, 0 block changes"
```

CI gate: a diff to any `frozen` or `tracked` golden **requires** a `BLESS.log` row in the same commit
whose file count matches, whose `git_sha` is the commit, and whose reason is ≥ 20 characters and does
not match `^(?i)(update|regen|fix|bless|wip|nit)\b`. A bless without a reason is the failure mode
this gate exists for, and it is fifteen lines of Python.

**The PR comment.** A `tracked` diff renders into a bot comment as: the count of changed lines by
change class (`added / removed / reclassified / retext / reorder`), the top 20 lines, and the
`shape` delta *first*, because the `shape` delta is the sentence a reviewer actually needs — "6 fewer
tables, 174 more table cells" is a legible fact and a 9,000-line outline diff is not.

### 2.4 Property tests — ten laws, each bound to an upstream invariant

Hypothesis is already in D1's dev dependency group. The key decision: **the generator produces
`.owstore` states and `DocSink` call sequences, not documents.** You cannot fuzz your way to a valid
DOCX; you can exhaustively generate valid Block trees. Byte-level fuzzing is a separate tool (§8).

| # | Law | Upstream invariant |
|---|---|---|
| P1 | `import(export(store)) == store` over generated stores | D2 §10 gate 5 |
| P2 | `write(read(b)) == b` over hand-authored future-version archives | D2 §10 gate 1 |
| P3 | `owcheck` holds after **any** legal `DocSink` call sequence (parent/`ord` bijection, grid exactly-once, `rel` integrity, verbatim⇒retained-part) | D2 §11 |
| P4 | `build_grid` never raises on any cell list; every `(r,c)` in `[0,n_rows)×[0,row_len[r])` resolves to exactly one `Origin`; charged expansion area ≤ `MAX_EXPANSION` before expanding | D2 §6 |
| P5 | `content_digest` is **invariant** under a change to `block_id`, `producer_id`, `method`, `trust`, `quote`, `score`, `raw_kind`, `origin_operator`, `marks`, `x` or any span; and **changes** under a change to `kind`, `layer`, NFC text, payload, or any child digest. Both directions, because either alone is satisfiable by a constant. | D2 digest recipe |
| P6 | For every block `b` in a serialized view, `map.to_text(RenderSpan(view_id, *map.offsets_of(b))) == [(b, TextSpan(0, len(b.text)))]` | D2 §5 |
| P7 | Two descriptions of the same physical rectangle (topleft/pt vs bottomleft/px+dpi, any rotation) produce an identical `Quad` | D2 geometry |
| P8 | `sha256_canonical(coerce(cfg)) == sha256_canonical(coerce(toml_roundtrip(coerce(cfg))))`, and no string coerces to a bool except the four TOML literals | D1's stated `"false" → True` risk |
| P9 | `resolve()` over a catalog shuffled 100× returns an identical `Resolution` | D3-4 |
| P10 | For an identity re-parse, `RebindReport.created == 0 and retired == 0 and quarantined is False` | D2 §4 |

P5's two-directional form is the one worth arguing for: a digest test that only checks invariance
passes for `def digest(b): return b""`.

---

## 3. The corpus: a licensed, versioned, installable asset

D3 names this as a real risk — *"The fixture corpus is itself a licence problem. Forty real documents
redistributed publicly need the same `{licence, licence_url, spdx, source_url, retrieved_at, sha256}`
ledger hyperframes uses for media. Get it wrong and the conformance kit is the thing that cannot
ship."* Here is the mechanism.

### 3.1 Five distributions, one manifest schema

```
packages/
  omniweave-corpus-core/         ≤  18 MB   120 docs   redistributable   IN-TREE, git-tracked
  omniweave-corpus-office/       ≤ 120 MB   480 docs   redistributable   git-lfs
  omniweave-corpus-pdf/          ≤ 240 MB   620 docs   redistributable   git-lfs
  omniweave-corpus-adversarial/  ≤   4 MB    90 docs   SYNTHETIC         in-tree
  omniweave-corpus-external/     ≤ 200 KB     0 docs   MANIFEST ONLY     in-tree
```

- **`core`** is the one every contributor gets. Hard ceiling in `tools/weights.toml`; a new fixture
  must **displace** one. That ceiling is what keeps the T2 budget at four minutes.
- **`adversarial`** is synthetic on purpose — zip bomb, 4M-cell xlsx, XML depth 257, 40-byte docx,
  encrypted PDF, a PDF whose text layer disagrees with its pixels, a DOCX with 200 overlapping
  rowspans. D1's `fixtures/` seeds it. Synthetic means no licence question and no PII question.
- **`external`** ships **only** manifest rows plus a fetcher, for corpora we may not redistribute
  (olmOCR-Bench's document set, OmniDocBench, LOCOMO, LongMemEval-S). `ow eval fetch --corpus
  external` downloads to `$OMNIWEAVE_HOME/corpora/<id>@<ver>/`, verifies every `sha256`, and
  **refuses** any asset whose manifest row lacks a licence. This is anydoc's harness shape ("the
  corpus is not redistributable and is not in the repo; the harness reads whatever is in
  `samples/`") with the manifest and the refusal added.

### 3.2 The manifest row — required fields, gated

```toml
# packages/omniweave-corpus-office/src/omniweave_corpus_office/corpus.toml
schema  = 1
id      = "omniweave-office"
version = "2026.09"
vendor  = "omniweave"                 # feeds the entrant-bias marker (Q14)
digest  = "sha256:c0de…"              # over the sorted (path, sha256) pairs; ppt-master's framing

[[doc]]
id              = "eu-annual-report-2019"
path            = "office/eu-annual-report-2019.docx"
sha256          = "sha256:3f2a…"
bytes           = 4_128_990
media_type      = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
licence         = "CC-BY-4.0"
spdx            = "CC-BY-4.0"
licence_url     = "https://creativecommons.org/licenses/by/4.0/"
attribution     = "European Union, 2019"
source_url      = "https://op.europa.eu/…"
retrieved_at    = "2026-07-14T08:12:00Z"
redistributable = true
contains_pii    = false               # REQUIRED. true ⇒ refused from any redistributable corpus.
holdout         = false               # true ⇒ lives in the -holdout sibling, hashes published only
slices          = ["office", "tables", "multilingual", "footnotes"]
truth           = ["native_xml"]      # what ground truth exists for this doc (§5.2)
notes           = "6 ragged tables, 2 merged-cell header rows, 27 footnotes, EN/FR/DE"
```

**`ow eval lint --corpus` fails on:** a file in the tree with no row; a row with no `licence`,
`spdx`, `source_url` or `retrieved_at`; an `spdx` outside the allowlist
`{CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, MIT, Apache-2.0, OGL-UK-3.0, EUPL-1.2, LicenseRef-PublicDomain}`;
`contains_pii = true` in a distribution with `redistributable = true`; `redistributable = false`
outside `omniweave-corpus-external`; a `sha256` mismatch; a `slices` entry not in the corpus's
declared slice vocabulary.

`NOTICE` and `THIRD_PARTY.md` are **generated** from these rows (D1 already generates both and gates
them with `--check`), so attribution travels with the wheel automatically. This is the one place the
collection is unanimously bad — codegraph ships 27 vendored grammars with 3 LICENSE files, open-slide
records no git ref — and it is a 40-line generator.

### 3.3 Slices, and why they are the join key

A slice is the accounting bucket. D4 already made `Slice` the unit of its Scoreboard and capped
cardinality at 512. Eval slices are the **corpus-side** counterpart and must be a subset of the same
vocabulary so a routing slice and an eval slice can be joined:

```
format:      docx pptx xlsx pdf-digital pdf-scanned html epub msg csv md
content:     tables math forms footnotes multicolumn handwriting cjk rtl multilingual
pathology:   low-dpi skewed rotated cid-broken no-text-layer huge-page ragged-table merged-header
provenance:  born-digital scan-clean scan-degraded photo
```

---

## 4. Determinism where models are involved: cassettes

### 4.1 Three layers, in order of preference

**Layer 1 — deterministic drivers get byte equality.** D3's `determinism` suite already covers this
and `driver.toml` already declares `deterministic = true`. Nothing new.

**Layer 2 — non-deterministic drivers get a cassette.** A `Cassette` is a recorded, content-addressed
request/response log intercepted at exactly two seams, both first-party and both already the *sole*
model channels in the design:

- D3's `DriverIO.service(name) -> ServiceHandle` — the only way a driver reaches an engine
  (D3-7 makes this structural: a driver has no other outbound channel).
- D1's `omniweave_core.modelserver` attach-or-spawn HTTP client (seam S3).

A driver cannot bypass either without violating D3-7, so cassette coverage is complete by
construction — this is why the interception point matters more than the mechanism.

```jsonc
// eval/cassettes/vllm.olmocr/9f/9f2c4b….ndjson.zst
{"t":"cassette","v":1,"service":"vllm.olmocr","key":"sha256:9f2c4b…",
 "measured_on":{"weights":"allenai/olmOCR-7B-0225-preview",
   "weights_revision":"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
   "runtime":"vllm","runtime_version":"0.9.1",
   "sampling":{"temperature":0.1,"top_p":1.0,"max_tokens":8000,"seed":0},
   "prompt_version":"olmocr/1","prompt_fp":"7c3f1a9b0d2e",
   "hardware":"1xA100-80GB","harness_version":"1.2.0","recorded_by":"ow eval record"},
 "recorded_at":"2026-08-14T09:22:31Z"}
{"t":"req","i":0,"digest":"sha256:11aa…","body":{ /* the exact request payload */ }}
{"t":"res","i":0,"status":200,"latency_ms":2411,"body":{ /* the exact response */ },
 "usage":{"tokens_in":1204,"tokens_out":882},"finish_reason":"stop"}
```

Key construction, reusing D1's canonicaliser and D2's `Producer` fields verbatim:

```python
key = sha256_canonical({
    "service":     handle.name,
    "endpoint":    endpoint,
    "model_id":    producer.model_id,
    "model_rev":   producer.model_rev,     # "main" is a lint error; D2 already says so
    "prompt_fp":   producer.prompt_fp,
    "sampling":    sampling,               # the full dict, canonical
    "payload":     sha256(canonical_payload_bytes),  # images by content digest, never inline
})
```

**A cassette miss in CI is a hard error, never a live call.** `ow eval run --cassette required` is
what CI passes; a miss raises `OW-E-004` and the message is
`cassette miss for vllm.olmocr key sha256:9f2c… — run: ow eval record --service vllm.olmocr --corpus core`.
This is not fussiness: a harness that silently falls through to a live call is a harness that bills
your CI account, and olmocr's own numbers put that at `$0.0128/page` under its default retry ladder
(8,000 tokens × 8 retries at $0.20/1M output) — a 64× amplifier fired in parallel.

Storage: an olmocr page response is ~4 KB of JSON; the `core` corpus at 400 pages × 3 model drivers
is ~5 MB zstd, in-tree. Cassettes for the big corpora ship as package data inside
`omniweave-corpus-pdf`, not in the git tree.

**Layer 3 — what cannot be cassetted gets a stability band, not an equality assertion.** A genuinely
new prompt has no recording. Run `k = 5` at the driver's declared sampling params and assert
`min_pairwise_agreement ≥ band_min`, where agreement is olmOCR-Bench's `normalize_text` followed by
normalized edit distance. `band_min` is declared per driver in the test, defaults to `0.98`, and a
band failure is a **flake-budget** event (§7.4), not a silent retry. This is honest about what a
sampling model can promise and it is still a gate.

### 4.2 The recording workflow, and its honest cliff

```
$ ow eval record --service vllm.olmocr --corpus core --only-missing --max-spend 5.00
  attaching vllm.olmocr … model_id verified (surya's GET /v1/models check)
  412 keys required · 398 present · 14 missing
  recording 14 … $0.31 spent of $5.00
  wrote eval/cassettes/vllm.olmocr/…  (14 files, 58 KB)
```

`--max-spend` is mandatory and defaults to `1.00`; it reuses D4's `BudgetLedger` and `PriceBook`.

**The cliff, named:** a contributor with no GPU and no API key *cannot re-record*. A PR that changes
a prompt therefore requires a maintainer to record. I would rather say that in the CONTRIBUTING doc
than pretend otherwise; the mitigation is that prompt changes are rare, the error message names
exactly what to ask for, and a `needs-cassette` label plus a maintainer-triggered workflow
(`workflow_dispatch` on the recording job, writing back to the PR branch) turns a two-day round trip
into a twenty-minute one.

---

## 5. Calibration: making CONFIDENCE mean something

This is the part of the decision most likely to be shipped as decoration, so it gets the most
mechanism.

### 5.1 What we inherit, and what is missing

D2 gives four channels: an ordinal `trust ∈ {AMBIGUOUS, INFERRED, EXTRACTED}`; a nullable
`(score, score_kind)` pair where *the scale is named or both are NULL*; per-page
`parse_score/layout_score/table_score/ocr_score`; and a `confidence` JSON blob on `doc`. D4 gives one
worked calibration: `garble.score` with **ECE ≤ 0.05, Brier ≤ 0.08** as a build gate, and
`calibration: bootstrap` in the manifest until an eval set is registered.

What is missing is the general rule, and the reason it is missing everywhere is that labels are
expensive. Two failures in the collection define the shape of the problem:

1. **docling's `table_score` is declared, never assigned, permanently `NaN`** — and
   `standard_pdf_pipeline.py`'s `nanmean` therefore publishes a three-component mean wearing four,
   with grades (POOR/FAIR/GOOD/EXCELLENT) attached. D2 already corrects this for omniweave's model;
   nothing yet *prevents its recurrence*.
2. **Every classifier in the collection that exposes a label instead of a probability** makes tiered
   routing impossible. D4 already refuses registration of a `kind="classifier"` signal whose domain
   is not `[0,1]`. But an uncalibrated probability in `[0,1]` is *also* meaningless — marker's
   `>= 0.05` recheck gate against an uncalibrated score is exactly D4's stated complaint.

### 5.2 Where the labels come from — three sources, and the cheap one is the novel one

**Source A — native-XML truth (free, large, exact).** For an office document, **the source XML is the
truth.** `w:t` run content in `word/document.xml`, `a:t` in a PPTX shape tree, and the shared-string
table in an XLSX give a mechanically-derivable expected text per paragraph/cell. So for every DOCX,
PPTX and XLSX in the corpus, every block gets a free `(predicted_text, true_text, correct: bool)`
triple. That is tens of thousands of labels on real documents at zero labelling cost, and it is
exactly the ground truth a `quote` tier and an `origin_span: exact` claim should be checked against
— D2 already specifies the per-driver check `normalize_k(part_bytes[a:a+len]) == block.text`; this
generalizes it from a driver-honesty check to a *calibration label source*.

**Source B — synthetic-but-real OCR truth (free, large, biased in a known direction).** Take a
born-digital PDF whose text layer is clean. Render it to pixels at the OCR render profile, feed the
pixels to the OCR driver, and compare its output against the *known* text layer. Every block yields a
`(ocr_score, correct)` pair. `ow eval synth-ocr --corpus pdf --n 2000` produces ~150k labelled points
in one nightly run.

The bias is real and must be stated: a rasterized born-digital page is not a scan. So the synthesizer
ships a **degradation ladder** and reports calibration **per level**:

```toml
# eval/suites/parse/degradations.toml
[[level]] id = "L0"  ops = []
[[level]] id = "L1"  ops = ["downsample:150->96dpi"]
[[level]] id = "L2"  ops = ["downsample:150->96dpi", "jpeg:q=40"]
[[level]] id = "L3"  ops = ["skew:deg=±3", "jpeg:q=40", "blur:sigma=0.8"]
[[level]] id = "L4"  ops = ["skew:deg=±3", "jpeg:q=25", "blur:sigma=1.2", "sp_noise:0.005",
                            "bleed_through:0.12"]
# NEVER binarize. Ollama-OCR's 72-DPI-then-Otsu destroys the antialiasing a modern VLM trained on;
# D4 already fixes `binarize = false, ALWAYS` in the render profile.
```

`ow eval calibrate` reports a curve per level and the report says, in the artifact itself:
*"synthetic degradation over-states accuracy on genuine scans; the human-labelled scan slice
(n=2,400) is the reference for `scan-degraded`."* Which brings us to:

**Source C — the human-labelled slice (expensive, small, authoritative).** 2,400 blocks across
`scan-clean`, `scan-degraded`, `photo`, `handwriting`, `cjk` and `math`, double-labelled at 20% with
published inter-labeller agreement. At ~800 blocks/reviewer-hour that is ~4 person-days, refreshed
annually. It exists to *anchor* A and B, not to replace them.

**Source D — `agree.decode_vs_page` (free, huge, biased to the escalated population).** D4's channel,
adopted as a supplement with its bias recorded on the curve. At D4's 18.8% escalation rate this is
~188,000 points per million pages against ~5,000 from a 0.5% audit.

### 5.3 The calibrator, and the three-state rule that stops decoration

```python
# omniweave_eval/calibrate.py
@dataclass(frozen=True, slots=True)
class Calibration:
    score_kind:      str            # e.g. "ocr.char_conf", "garble.p_bad", "table.recon"
    eval_set_id:     str            # e.g. "omniweave-parse@2026.09/scan-degraded"
    eval_set_digest: str
    method:          Literal["isotonic", "platt"]
    bins:            tuple[tuple[float, float, int], ...]   # (raw_lo, calibrated_p, n)
    ece:             float
    brier:           float
    n:               int
    ci95:            tuple[float, float]
    label_sources:   tuple[str, ...]        # ("native_xml", "synth_ocr:L2", "human")
    producers:       tuple[str, ...]        # producer_ids this curve is valid for
    fitted_at:       str
    harness_version: str

CalStatus = Literal["calibrated", "bootstrap", "uncalibrated"]

def status(score_kind: str, producer_id: str, now: int) -> CalStatus: ...
    # calibrated   : a curve exists for (score_kind, producer) and is younger than
    #                policy [calibration].max_age_days  (D4: 30)
    # bootstrap    : a SHIPPED PRIOR exists — a curve fitted on our corpus, honestly labelled as
    #                not-yours. D4 already uses this exact word in the run manifest.
    # uncalibrated : no curve at all
```

> **The rule that makes confidence non-decorative:**
> **A `score` may be rendered as a probability, a percentage, or a bar only when
> `status(score_kind, producer) == "calibrated"`. Otherwise the surface renders the ordinal `trust`
> tier and nothing else.**

This is docling's own stated API discipline — *publish the ordinal, keep the cardinal internal* — plus
the half docling never built: the cardinal becomes publishable exactly when it has earned it. The
serve envelope carries `confidence: {value, kind, status, eval_set_id, ece, n}` and the renderer
takes the **status**, not the float, so there is no code path from an uncalibrated float to a
percentage in a UI.

CI gates, all in `ow eval lint --confidence`:

- **Q9** — for every `score_kind` in the enum, either a curve exists with `ece ≤ 0.05`,
  `brier ≤ 0.08`, `n ≥ 500`, or `status` is `bootstrap`/`uncalibrated` and no surface renders it
  numerically. Enforced by a renderer test that feeds each status and asserts the output shape.
- **Q10 — the docling regression.** For every declared `score_kind`, assert (a) at least one producer
  writes a non-null value on the fixture corpus, and (b) the aggregate's declared component count
  equals the count of non-null components. **A declared-but-never-written score fails the build.**
  Forty lines, and it catches the exact defect docling shipped *and documented*.
- **Q11 — trust monotonicity.** On the labelled corpus, report
  `err(EXTRACTED) ≤ err(INFERRED) ≤ err(AMBIGUOUS)` with 95% CIs. A non-monotone ordering means the
  tier assignment is wrong, and it fails. Nobody in the collection checks this, and a three-value
  enum whose tiers do not order by measured error is worse than no enum — it is a false signal three
  layers deep. (`AMBIGUOUS` is defined by graphify's prompt line *"uncertain — flag for review, do
  not omit"*, so its error rate being highest is the whole point of the tier existing.)

```json
// eval/calibration/ocr.char_conf@omniweave-parse@2026.09.json
{
  "score_kind": "ocr.char_conf", "method": "isotonic",
  "eval_set_id": "omniweave-parse@2026.09/scan-degraded",
  "eval_set_digest": "sha256:aa11…",
  "bins": [[0.00,0.021,4102],[0.10,0.088,3517],[0.20,0.171,2988],[0.30,0.264,2610],
           [0.40,0.372,2455],[0.50,0.489,2701],[0.60,0.601,3122],[0.70,0.718,4088],
           [0.80,0.842,7215],[0.90,0.951,19883]],
  "ece": 0.0182, "brier": 0.0611, "n": 52681, "ci95": [0.0151, 0.0219],
  "label_sources": ["synth_ocr:L3", "human"],
  "producers": ["parse.ocr.olmocr@0.5.0#a1b2c3…"],
  "fitted_at": "2026-08-30T02:14:00Z", "harness_version": "1.2.0"
}
```

### 5.4 `ow eval correlate` — settling D4's open question

```
$ ow eval correlate --channels agree,audit --against human --slice-by unit.producer_family
slice                      n_agree   n_audit   n_human   r(agree,human)   r(audit,human)
pdf/Acrobat Distiller        8412       142       610          0.71             0.88
pdf/Ghostscript              5109        97       402          0.63             0.86
pdf/Microsoft Print to PDF   2288        41       188          0.79             0.91
scan/unknown                 1104        88       402          0.44 ⚠           0.85

⚠ agree.decode_vs_page correlates weakly on scan/unknown (r=0.44, n=1104): the two readings
  share a failure mode (both read the same degraded pixels). D4 R13 auto_demote must continue
  to accept `audit` verdicts only for this slice.
```

That table is the artifact D4 asked for, per slice, and it is what unblocks (or permanently blocks)
`auto_demote` on the free channel.

---

## 6. The benchmark harness

### 6.1 `MeasuredOn` — the type that makes Q1 structural

```python
# omniweave_eval/measured.py — frozen, NO DEFAULTS. A missing field is a TypeError at construction.
@dataclass(frozen=True, slots=True)
class MeasuredOn:
    weights:          str | None      # "allenai/olmOCR-7B-0225-preview" | None for a codepath
    weights_revision: str | None      # EXACT sha. "main" raises. D2/D4 already lint this.
    runtime:          str             # "vllm" | "transformers" | "tensorrt" | "anydoc" | "pdfium"
    runtime_version:  str
    sampling:         Mapping[str, Scalar]      # {} for a deterministic path
    prompt_version:   str | None
    hardware:         str             # "1xA100-80GB" | "x86_64-linux 8c/16GiB"
    corpus:           str             # "omniweave-parse@2026.09"
    corpus_digest:    str
    harness_version:  str
```

> **Q1: no number is published without a complete `MeasuredOn`.**
> Enforced three ways: the dataclass has no defaults; the scoreboard writer refuses a row missing
> one; `ow eval lint` fails. **The regression fixture is HunyuanOCR's published 94.10 OmniDocBench —
> measured on TensorRT while the repo ships Transformers and vLLM, which it admits disagree.** A
> test constructs that row without `runtime` and asserts refusal.

### 6.2 Timing, made honest by making the basis a required field

anydoc's harness gets timing right *in prose*: min-of-N warm runs; markitdown/docling/unstructured
timed **in-process**; anydoc timed from its own CLI's reported conversion time excluding spawn; and
**pandoc and LibreOffice include process spawn — "that's how they're used in practice, and it's
called out in the report."** That honesty is a paragraph, and a paragraph does not survive the
sixteenth adapter.

So: `timing_basis ∈ {in_process, spawn_inclusive, server_attached}` is a **required field per
adapter row**, and the table renderer **refuses to place two rows with different bases in one
column** — it splits them into separate blocks with the basis in the block header. D3's measured
numbers for anydoc already carry both (`measured_on` and `measured_on_spawn`); this makes it general.

```toml
# eval/suites/office/adapters.toml
[[adapter]] id="anydoc"     kind="library"  timing_basis="in_process"     import="omniweave_eval.adapters.anydoc"
[[adapter]] id="markitdown" kind="library"  timing_basis="in_process"     import="…markitdown"
[[adapter]] id="docling"    kind="library"  timing_basis="in_process"     import="…docling"
[[adapter]] id="pandoc"     kind="external" timing_basis="spawn_inclusive" bin="pandoc"
[[adapter]] id="soffice"    kind="external" timing_basis="spawn_inclusive" bin="soffice"
[[adapter]] id="olmocr"     kind="service"  timing_basis="server_attached" service="vllm.olmocr"
timing_rule = "min_of_n_warm"   # n from --iters, default 5; the ONLY permitted rule
missing_adapter = "skip_with_warning"   # anydoc's rule: a partial setup still runs
```

### 6.3 Truth is never our own output

anydoc's deterministic quality metric is *word-trigram containment against anydoc's own output*, and
the repo labels it **"not a truth measure."** That is the right label and the wrong reference. We
adopt the metric and forbid the reference:

```python
TruthKind = Literal["human", "rendered", "native_xml"]
# containment/f1/edit-distance metrics REFUSE a reference whose producing driver is the subject,
# and refuse a reference with truth_kind not in TruthKind. There is no fourth value, and in
# particular there is no "reference_tool".
```

> **Q2: truth is never our own output.** Every metric row carries `truth.kind`, and the metric
> function raises `OW-E-002` when `reference.producer == subject.producer`. anydoc's self-referential
> trigram metric is the regression fixture: a test builds exactly that configuration and asserts the
> raise.

And the second half of the self-benchmark problem — anydoc wrote both the harness and the favoured
tool; olmOCR is an entrant on its own benchmark:

> **Q14: entrant bias is marked.** `entrant_bias = (subject.vendor == corpus.vendor)`. Such rows are
> printed with `†`, excluded from the headline aggregate, and footnoted. **omniweave's own drivers on
> omniweave's own corpus carry the †.** If we will not apply the rule to ourselves it is not a rule.

### 6.4 The four suites

**`parse`** — olmOCR-Bench's taxonomy, taken whole and improved in one place.

```python
class TestType(StrEnum):
    BASELINE="baseline"; PRESENT="present"; ABSENT="absent"; ORDER="order"
    TABLE="table"; MATH="math"; FORMAT="format"; FOOTNOTE="footnote"
class Checked(StrEnum): VERIFIED="verified"; REJECTED="rejected"

@dataclass(frozen=True, slots=True)
class ParseTest:
    doc: str; page: int; id: str; type: TestType
    max_diffs: int = 0                 # fuzzy budget in edit distance
    checked: Checked | None = None     # human-review state, IN the record — olmOCR's best idea
    slices: tuple[str, ...] = ()
    note: str = ""

@dataclass(frozen=True, slots=True)
class TableTest(ParseTest):
    cell: str
    up: str = ""; down: str = ""; left: str = ""; right: str = ""
    top_heading: str = ""; left_heading: str = ""
    # threshold = max(0.5, 1.0 - max_diffs / len(cell))   -- olmOCR-Bench, verbatim
```

**The improvement:** olmOCR-Bench must re-parse the tool's *markdown* back into a table to evaluate a
relational assertion — its weakest link, and the reason it needs `ignore_markdown_tables`. D2's
`Grid` already answers `up/down/left/right/top_heading/left_heading` in **O(1)** and D2's concrete
shape says so explicitly. So for any driver that writes into an `.owstore`, `TableTest` evaluates
**against the model**, not against a re-parse. A markdown/HTML adapter is retained so external tools
are scored on the identical tests. `normalize_text` is ported verbatim, including the `µ → μ`
replacement.

**`extract`** — lift's five adversarial categories, taken whole: values spanning pages, exhaustive
lists, **fields that must be left null**, near-miss distractors, multi-source aggregation.
Deterministic exact match with numeric tolerance and normalized strings. And one hard rule:

> **The headline metric is `doc_acc`, not `field_acc`.** lift measures **90.2% per field and 20.9%
> full-document** on its own benchmark. A README, a scoreboard row, or a card that reports field
> accuracy without full-document accuracy beside it fails `ow eval lint`. Per-field accuracy does not
> compound, and the entire product promise of "correct document" lives on the second number.

The suite also emits `verify.grounded_field_frac` per document (D4's `fields`-lane cross-check), so
the eval and the router read the same number.

**`retrieve`** — LOCOMO (n=300) and LongMemEval-S (n=50), because they are the datasets other memory
systems report on and therefore the only cross-referenceable anchor we have. graphify's harness shape,
with its fairness rules **converted from prose into assertions**:

```python
# eval/suites/retrieve/fairness.py — runs BEFORE the first query; a violation aborts the run
def assert_fair(run: RetrieveRun) -> None:
    one("answer model",  {a.model_id_for("answer")  for a in run.adapters})
    one("judge model",   {a.model_id_for("judge")   for a in run.adapters})
    one("embedder",      {a.embedder_id             for a in run.adapters if a.embedder_id})
    one("token budget",  {a.max_context_tokens      for a in run.adapters})
    require(run.spend_ledger is not None and run.max_spend is not None,
            "every retrieve run writes a spend ledger and respects --max-spend")
# An adapter that cannot use the shared embedder (a self-hosted system that locks in its own) is
# admitted with `embedder_confounded = true`, its recall number is footnoted, and it may never be
# the headline. graphify flags exactly this for supermemory's 768-d English-only embedder.
```

Grading is graphify's, verbatim: `coverage = (covered + 0.5 * partial) / total` against a gold set of
atomic key facts, **every verdict citing a verbatim quote from the answer**, so a grade is auditable
rather than one opaque score.

> **Q20: a retrieve number without a validated judge is not publishable.** The scoreboard row must
> carry `judge.agreement` and `judge.kappa` over `n_double ≥ 100`, from a *second independent judge*.
> graphify publishes **90.6% agreement, Cohen's κ = 0.81** and notes that most published memory
> benchmarks disclose no judge validation at all. That is the bar; we publish ours whatever it is.

**`absence`** — ours, and the one nobody else runs. jcodemunch's absence contract has ten gates and
the correct answer to a query with no answer is `absent`, not a confident zero and not a nearest
neighbour. The corpus contains queries whose true answer is *nothing*, and a system that answers
anything **fails**.

```
metric                    definition
absence_precision         of queries answered `absent`, the fraction with genuinely no answer
false_absence_rate        of queries with an answer, the fraction answered `absent`
gate_coverage             for each of the 10 gates, ≥1 test that forces it (a coverage gate, not a score)
```

The ten omniweave-specific hazards D2 and the mining notes name — OCR failed on pages 12–40; the PDF
was password-protected (`OW_ENCRYPTED`); a table extractor timed out (`OW_TIMEOUT`); an empty text
layer with no OCR fallback (`OW_NEEDS_OCR`); the embedding model changed since indexing; the block
budget truncated the response (`OW_TRUNCATED_BY_BUDGET`); coverage incomplete; index rewritten
mid-scan; freshness unknown; absence unprovable by the mode that ran — each gets a fixture and each
must force `degraded`. **Ten tests, and they make the absence contract executable instead of
aspirational.** This is also, bluntly, the cheapest differentiator in the whole framework: every RAG
system in existence returns a confident zero here.

---

## 7. Regression gates

### 7.1 Deterministic counters — exact, and this is the gate I would fight for

Wall-clock on a shared runner is noise; it fails on Tuesdays and teaches people to hit rerun.
Counters are not.

```python
# omniweave_eval/counters.py — harvested from the D6 run manifest, D4's route_spend,
# and D3's driver_observation. Exact. A delta of ±1 fails without a bless.
COUNTERS: tuple[str, ...] = (
    # model / store writes
    "blocks_written", "pages_committed", "marks_written", "grid_slot_rows", "rel_rows",
    # store reads
    "store_transactions", "store_rows_read", "fts_queries",
    # I/O and compute
    "bytes_read", "page_renders", "signal_computations", "subprocess_spawns", "service_attaches",
    # drivers and routing
    "driver_activations", "resolutions", "escalations", "degradations",
    # money
    "llm_calls", "tokens_in", "tokens_out", "cost_micros",
    # cache
    "cache_hits", "cache_misses", "rebilled_units",
)
```

```toml
# eval/gates.toml  (excerpt)
[gate.counters]
class     = "exact"
scope     = "corpus:core"
owner     = "team@particle6.com"
review_by = "2027-06-01"
bless     = "required"
message   = """Counter delta on {corpus}. Top movers:
{top3}
If this is intended, run: ow eval bless --counters --reason '<what changed and why>'"""
```

What this catches that nothing else does:

- a driver upgrade that silently re-renders every page (`page_renders` +42);
- a router change that computes a `LOCAL_COMPUTE` signal on clean born-digital PDFs — **D4 already
  specifies exactly this test** ("a test asserts a clean born-digital PDF computes zero
  `LOCAL_COMPUTE` signals and spawns no inference server"); the counter gate generalizes it to every
  signal and every corpus;
- a cache-key change that turns 100% hits into 100% misses — graphrag's `str()`-fallback bug produced
  a **permanent silent 100% cache miss** and nothing in that repo would have caught it;
- a free operator re-run that re-bills a billable one (`rebilled_units` > 0), which D6's stage-
  ownership invariant forbids and which is invisible in wall time.

Every one of those is a production incident and none of them moves a timing number reliably.

### 7.2 Timings — per-runner baselines on a ratchet

D1's G10 already does this for cold start with a 25% drift tolerance and a per-OS recorded baseline.
I extend the same mechanism rather than inventing a second one.

```json
// eval/baselines/ubuntu-24.04-py3.12-gha-standard.json
{"recorded_at":"2026-08-30T02:41:00Z","runner":"gha-ubuntu-24.04-4c16g","harness":"1.2.0",
 "tolerance":0.25,
 "budgets":{
   "import_omniweave_core_ms":            {"p50":  61, "max":  80},
   "ow_version_ms":                       {"p50": 118, "max": 150},
   "ow_help_ms":                          {"p50": 191, "max": 250},
   "discovery_20_drivers_ms":             {"p50":  14, "max":  20},
   "ow_query_warm_ms":                    {"p50": 172, "max": 250},
   "parse_docx_in_process_p50_ms":        {"p50":   7, "max":  60},
   "parse_docx_spawn_inclusive_p50_ms":   {"p50": 244, "max": 400},
   "owcheck_ns_per_block":                {"p50": 238, "max": 300},
   "store_bytes_per_block":               {"p50": 341, "max": null, "ratchet": true},
   "peak_rss_gen5000p_bytes":             {"p50": 1_180_000_000, "max": 1_600_000_000},
   "conform_mandatory_tier_s":            {"p50": 172, "max": 300}
 }}
```

The first five rows are D1's G10 budgets verbatim. `parse_docx_in_process_p50_ms` is anchored on
anydoc's measured **4.4 ms median across fourteen formats** (against markitdown's 134.8 ms and
docling's 513.6 ms), with headroom for the Python adapter and the marshal; `owcheck_ns_per_block`
on D2's ~240 ns; `store_bytes_per_block` on D2's measured ~338 B/block and gated as a **ratchet**
(never worse than the recorded value + tolerance) rather than an absolute, because D2's own open
question is whether the 60–120 blocks/page envelope holds.

Rules: baselines are keyed `(os, python, runner_class)`; a PR may **never** write a baseline; the
nightly job on a labelled runner refreshes them and opens a PR when a p50 moves > 10%; the failure
message names the **top three counter deltas** alongside the timing, because D1's own risk register
notes that a weight gate which only reports a total is a lagging indicator nobody can action.

### 7.3 Report/artifact binding — the gate result must bind to bytes

ppt-master's `source_fingerprint` is the artifact to copy and it is thirty lines: a SHA-256 over the
exact bytes checked, **sorted by basename** (so moving the project does not change the digest),
`name\0sha\n` framing, an unreadable file contributing the literal `unreadable` plus an error entry
rather than dropping out of the digest — and, the load-bearing part, **the exporter recomputes it
with an independent implementation over the files it is about to compile, and divergence surfaces as
`stale`.**

omniweave's version: every `EvalReport` carries `corpus_fingerprint` and `golden_fingerprint`, and
`ow eval verify` recomputes both independently before a scoreboard publish. And ppt-master's
nine-value gate enum is right and a boolean is wrong:

```python
GateStatus = Literal[
  "not-provided",       # you never ran the gate            != failed
  "unreadable", "unsupported-schema", "non-final", "unverified",
  "failed", "stale",    # fingerprint diverged since the gate ran
  "passed", "passed-with-warnings",
]
# Every non-passing status prints the EXACT command that clears it. `not-provided` and `failed`
# are different user errors and must never share a message.
```

And ppt-master's provenance classes, because a corpus carrying pre-existing findings otherwise makes
every driver look broken and the team stops reading the report:

```python
FindingProvenance = Literal["blocking", "introduced", "inherited", "source-import"]
# inherited := byte-identical in the previous release's report for the same (corpus, driver-major).
# The report prints per-class counts, and the headline number counts `introduced` + `blocking` only.
```

### 7.4 Flake budget

```
$ ow eval flakes --window 30d
test                                              runs  fails  flake%  state
suites/parse/test_table_relational[cjk-merged]     412     11   2.67%  QUARANTINED  #1841
suites/parse/test_order_multicolumn                412      3   0.73%  ok
```

A test that fails then passes on a rerun records a `flake` row. Over 2% across 30 days it moves to
the `informational` tier **and opens an issue**. There is no `--rerun-failures` in CI: a flaky gate
that gets rerun is a gate that has already stopped working, and every project that adds the flag
keeps it.

### 7.5 Gate ownership and rot

```toml
# eval/gates.toml
[gate.golden_frozen]   owner="team@particle6.com" review_by="2027-06-01" class="exact"
[gate.counters]        owner="team@particle6.com" review_by="2027-06-01" class="exact"
[gate.timings]         owner="team@particle6.com" review_by="2027-03-01" class="ratchet" tolerance=0.25
[gate.calibration]     owner="team@particle6.com" review_by="2027-03-01" class="threshold" ece=0.05 brier=0.08
[gate.corpus_licence]  owner="legal@example.com"  review_by="2027-01-01" class="exact"
[gate.contributor_parity] owner="team@particle6.com" review_by="2027-06-01" class="budget" max_s=600
```

> **Q17:** every gate has an owner and a `review_by`; a row past its date **fails the gates job**.
> Same mechanic D1 uses for `allowed-undeclared.toml` and D3 for tombstones. **Q18:** a gate marked
> `--warn-only` or skipped for 14 consecutive days fails. There is no `--warn-only`; a downgrade is a
> tier change in `gates.toml`, which is a reviewed diff.

---

## 8. Fuzzing, and the one place bytes beat properties

anydoc is **the only fuzzed parser in the collection** — 12 `cargo-fuzz` targets, an in-repo seed
corpus, `publish = false` so the fuzz crate never ships, and it fuzzes the *number-format string
parser*, not just the container. The deepest bugs in spreadsheet parsers live in the little grammar
sub-parsers.

omniweave ships `fuzz/` from day one with **Atheris** (Python) targets mirroring anydoc's, plus the
sub-grammars anydoc does not have:

```
fuzz/
  targets/
    fuzz_owdoc_archive.py       # the .owdoc ZIP/NDJSON reader — tolerant load must never crash
    fuzz_reduction_parse.py     # golden reductions round-trip
    fuzz_card_toml.py           # driver.toml loader; unknown top-level table => error, never crash
    fuzz_route_policy.py        # the rule compiler; a malformed policy must be a typed error
    fuzz_config_coerce.py       # D1's ~250 lines of scalar coercion
    fuzz_cite_addr.py           # addr/cite parsers — 'p14/3/r2c5' and 'd7#412'
    fuzz_spanmap.py             # RenderSpan -> (BlockId, TextSpan) lift
    fuzz_query_sanitize.py      # FTS5 query rewriting (codegraph's '::' lesson)
  seeds/                        # seeded from anydoc/fuzz/seeds/ + corpus-adversarial
```

Rust-side format decoding is anydoc's, already fuzzed upstream; we do not re-fuzz it, we assert its
version and record the fork trigger (D1). Nightly in T5; a crash files an issue with the minimized
input added to `corpus-adversarial` — a crash becomes a fixture, permanently.

---

## 9. The public scoreboard as an adoption asset

### 9.1 Static, generated, byte-diff gated

`scoreboard.omniweave.dev` is a static site **generated from a committed `eval/results/**.json`
tree**, `--check`/`--bless` gated exactly as graphify gates its rendered skills (byte-diff, golden
`expected/`, explicit bless, baselines pinned to an immutable SHA). No hosted service, no
availability dependency, no key rota — the same reasoning D3 used to reject a hosted registry, and
the property that lets anyone fork it and re-run it.

```json
// eval/results/parse.ocr.olmocr@0.5.0/parse/omniweave-parse@2026.09.json
{
  "schema": 1,
  "suite": "parse", "slice": "tables",
  "corpus": {"id":"omniweave-parse","version":"2026.09","digest":"sha256:c0de…","n_tests":1841},
  "subject": {"driver":"parse.ocr.olmocr","version":"0.5.0","schema_version":2,
              "card_sha256":"sha256:9f2c…","attested":true,
              "licence_tier":"open","restriction_bits":0,"vendor":"allenai"},
  "measured_on": {"weights":"allenai/olmOCR-7B-0225-preview",
                  "weights_revision":"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                  "runtime":"vllm","runtime_version":"0.9.1",
                  "sampling":{"temperature":0.1,"max_tokens":8000},
                  "prompt_version":"olmocr/1","hardware":"1xA10G-24GB",
                  "corpus":"omniweave-parse@2026.09","corpus_digest":"sha256:c0de…",
                  "harness_version":"1.2.0"},
  "harness": {"timing_basis":"server_attached","timing_rule":"min_of_n_warm","iters":5,
              "cassette":false},
  "truth": {"kind":"human","labeller_agreement":0.94,"n_double_labelled":200},
  "metrics": {"overall":0.791,
              "by_type":{"baseline":0.988,"present":0.902,"absent":0.951,"order":0.883,
                         "table":0.712,"math":0.640,"format":0.774,"footnote":0.681}},
  "cost": {"usd_per_1k_pages":0.21,"pricebook_digest":"sha256:44ab…","spend_micros_total":386_000},
  "provenance": {"class":"reproduced","reproduced_at":"2026-08-30T03:12:00Z",
                 "runner":"gha-ubuntu-24.04-a10g"},
  "entrant_bias": false,
  "not_measured": ["handwriting","rtl"],
  "degradations": ["layout_unavailable"]
}
```

### 9.2 Five properties that make it an adoption asset rather than marketing

**(1) Third parties can appear, and CI re-runs them.**
`ow eval run --suite parse --submit` writes a `results/` row; a PR adding it merges when (a) D3's
conformance attestation matches, (b) `harness_version` is current, (c) `MeasuredOn` is complete. CI
then **re-runs** rows whose driver is `free` or `local_compute` on our runner and stamps
`provenance.class = "reproduced"`. A `billed_api` row is always `self_reported`, and the two classes
render visually distinct. This is what makes "add a driver in an afternoon" end in a public number
rather than a private one.

**(2) The default sort is not accuracy.** It is **accuracy-per-dollar within a licence tier**, with
the tier filter defaulting to `open`. This is a stance and it should be one: the ~4-point olmOCR-bench
gap between surya (83.3%) and olmocr (~79%) **is the price of `MODEL_LICENSE` clause 2(c)**, and a
table that sorts on the raw number silently re-argues a settled licence decision every time someone
opens it. Cost columns come from D4's `PriceBook` with its digest recorded, so the number is
reproducible rather than a vibe. `usd_per_point_over_free_baseline` is the operator's actual decision
variable and nobody publishes it.

**(3) It publishes what it could not measure.** `not_measured[]` is a required field and renders as a
coverage column. D4's `layout.class_hist` hole gets a named row on the front page: *"REPAIR rung is
thin on the PDF path — no licence-clean layout detector ships; affected decisions record
`cause=layout_unavailable`."* A scoreboard whose only content is what looks good is a brochure, and
the audience for this one is engineers who will find the gap in twenty minutes anyway.

**(4) Every cell links to its `MeasuredOn` and to the exact reproducing command.**

```
ow eval run --suite parse --slice tables --corpus omniweave-parse@2026.09 \
            --driver parse.ocr.olmocr@0.5.0 --iters 5 --max-spend 2.00
```

**(5) Held-out slices detect tuning to the public set.** 15% of each corpus lives in
`omniweave-corpus-<x>-holdout`, published as hashes only and refreshed annually. Rows report both,
and a `public − holdout` gap > 5 points prints ⚠. That is a detector, not a solution, and it is
labelled as one.

### 9.3 The correlation table, published once and maintained

D3's open question — *"Whether a licence-clean golden corpus can produce numbers comparable to
olmOCR-Bench … will read as evasion"* — gets a direct answer rather than a defence. We publish a
correlation page: for the three drivers where both a public olmOCR-Bench number and ours exist,
report both, per category, with Spearman ρ and the count. A reader who trusts olmOCR-Bench can then
convert our numbers into their frame. If the correlation is poor we publish that too, and it becomes
a finding about one of the two corpora.

---

## 10. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| Q1 | No number is published without a complete `MeasuredOn`. | Frozen dataclass, no defaults; scoreboard writer refuses; `ow eval lint`. Fixture: HunyuanOCR's TensorRT-measured 94.10 against a repo shipping Transformers/vLLM. |
| Q2 | Truth is never our own output. | `truth.kind ∈ {human, rendered, native_xml}`; metrics raise `OW-E-002` when `reference.producer == subject.producer`. Fixture: anydoc's self-referential trigram metric. |
| Q3 | Every fixture carries licence, SPDX, source URL, retrieval date and sha256. | `corpus.toml` schema `required`; `ow eval lint --corpus` fails on an unlisted file, a missing field, a non-allowlisted SPDX, `contains_pii` in a redistributable corpus; `NOTICE`/`THIRD_PARTY.md` generated and `--check` gated (D1's existing generator). |
| Q4 | A `frozen` or `tracked` golden never changes without a blessed reason. | CI diffs `eval/goldens/**` against the merge base; requires a `BLESS.log` row in the same commit, matching file count and git sha, reason ≥ 20 chars, not matching the no-op denylist. `BLESS.log` is append-only, diffed against the previous tag (D1 G13's mechanic). |
| Q5 | Geometry never enters a frozen golden. | The `shape` reducer emits only quantized aggregates; a T2 test asserts two pdfium minors produce byte-identical `shape` over the fixture corpus. |
| Q6 | CI never makes a live model call. | Socket guard installed for every non-`network` test (D1 G15's harness); `--cassette required` in CI; a miss is `OW-E-004` naming the record command. |
| Q7 | A deterministic counter cannot change silently. | Exact gate over `COUNTERS` harvested from the run manifest + `route_spend` + `driver_observation`; delta ≠ 0 fails; bless required with a reason. |
| Q8 | A timing budget is per-runner and ratcheted, never absolute. | `eval/baselines/<os>-<py>-<runner>.json`, 25% tolerance (D1 G10's rule); a PR may not write a baseline; the nightly job on a labelled runner refreshes and opens a PR. |
| Q9 | A `score` is rendered numerically only when calibrated. | `Calibration.status()` returns `calibrated \| bootstrap \| uncalibrated`; the renderer takes the status, never the float; a test feeds each status and asserts the output shape. |
| Q10 | A declared score component that nothing writes fails the build. | `ow eval lint --confidence`: ≥1 non-null value per `score_kind` on the fixture corpus, and the aggregate's declared component count equals the non-null count. Fixture: docling's permanently-`NaN` `table_score` under `nanmean`. |
| Q11 | `trust` tiers are monotone in measured error. | `err(EXTRACTED) ≤ err(INFERRED) ≤ err(AMBIGUOUS)` with 95% CIs on the labelled corpus; non-monotone fails. |
| Q12 | A stale calibration degrades loudly, never silently. | D4's `[calibration] max_age_days = 30`; the loader stamps `Degradation(kind="calibration_stale")`, which D4 already defines and D8/D9 already render. |
| Q13 | A scoreboard row is `reproduced` or `self_reported`, never unlabelled. | `provenance.class` required; CI re-runs `free`/`local_compute` rows; `billed_api` is always `self_reported`. |
| Q14 | Entrant bias is marked, including our own. | `entrant_bias = (subject.vendor == corpus.vendor)`; `†`, excluded from the headline aggregate, footnoted. |
| Q15 | The scoreboard publishes what it did not measure. | `not_measured[]` required per row; a coverage column; D4's `layout_unavailable` has a named front-page row. |
| Q16 | The default contributor test run is offline, GPU-free, and under 10 minutes. | The `contributor-parity` CI job: clean container, egress blocked, no GPU, no Node, `uv sync && pytest`, wall-time assertion. |
| Q17 | Every gate has an owner and a review date; a stale gate fails. | `eval/gates.toml`; a row past `review_by` fails the gates job. |
| Q18 | A flaky gate is quarantined and filed, never rerun-until-green. | Flake ledger; > 2% over 30 days ⇒ `informational` + an issue; no `--rerun-failures` in CI; no `--warn-only` anywhere. |
| Q19 | Fairness rules in a comparative run are asserted, not documented. | `fairness.py` runs before the first query and aborts on differing answer/judge model, embedder, or token budget; an unavoidably different embedder sets `embedder_confounded` and forfeits the headline. |
| Q20 | A retrieve number without a validated judge is not publishable. | `ow eval lint` requires `judge.agreement` and `judge.kappa` over `n_double ≥ 100`. Reference bar: graphify's 90.6% / κ 0.81. |

---

## 11. Concrete shape — layout, CLI, CI

```
packages/
├── omniweave-eval/                 src/omniweave_eval/     tier = dev.  NOTHING runtime imports it.
│   ├── measured.py                 MeasuredOn (frozen, no defaults)
│   ├── reduce.py                   shape | outline | text reducers; deterministic formatting
│   ├── golden.py                   compare · bless · BLESS.log · PR-comment renderer
│   ├── cassette.py                 record | replay at DriverIO.service + core.modelserver
│   ├── counters.py                 COUNTERS + the exact gate
│   ├── bench.py                    min-of-N warm; timing_basis enforcement; baselines + ratchet
│   ├── calibrate.py                Calibration · isotonic/platt fit · ECE/Brier · trust monotonicity
│   ├── synth.py                    native-XML truth · synth-OCR + the degradation ladder
│   ├── correlate.py                agree vs audit vs human, per slice   (D4's open question)
│   ├── fingerprint.py              corpus/golden fingerprints, ppt-master's framing
│   ├── report.py                   GateStatus (9 values) · FindingProvenance (4 classes)
│   ├── scoreboard.py               results/ -> static site;  --check / --bless
│   ├── lint.py                     --corpus --confidence --measured --estimates
│   ├── adapters/                   anydoc markitdown docling pandoc soffice olmocr bm25 dense hybrid
│   └── suites/{parse,extract,retrieve,absence,office}/
├── omniweave-corpus-core/          tier = data,   18 MB, in-tree, redistributable
├── omniweave-corpus-office/        tier = data,  120 MB, git-lfs
├── omniweave-corpus-pdf/           tier = data,  240 MB, git-lfs   (+ cassettes as package data)
├── omniweave-corpus-adversarial/   tier = data,    4 MB, synthetic
└── omniweave-corpus-external/      tier = data,  200 KB, MANIFEST ONLY + fetcher

eval/
├── gates.toml                      owner · review_by · class per gate
├── goldens/<corpus>@<v>/<driver>@<schema_v>/<doc>.{shape,outline,text}
├── goldens/BLESS.log               APPEND-ONLY; diffed against the previous tag
├── cassettes/<service>/<sha[:2]>/<sha>.ndjson.zst
├── calibration/<score_kind>@<eval_set_id>.json
├── baselines/<os>-<py>-<runner>.json
├── results/<driver>@<v>/<suite>/<corpus>@<v>.json
└── scoreboard/                     GENERATED; byte-diff gated (--check / --bless)

fuzz/targets/ fuzz/seeds/
```

```
# ow eval — the whole surface
ow eval run       --suite parse|extract|retrieve|absence|office [--slice K] [--corpus C@V]
                  [--driver D@V ...] [--iters 5] [--cassette required|allow|off]
                  [--max-spend 2.00] [--submit]
ow eval golden    [--corpus C] [--driver D]            # compare only; exit 0/3(frozen)/4(tracked)
ow eval bless     --reason "<>" [--corpus C] [--driver D] [--counters]
ow eval record    --service S [--corpus C] [--only-missing] [--max-spend 1.00]
ow eval calibrate [--score-kind K] [--eval-set E] [--trust] [--local]
ow eval correlate --channels agree,audit --against human [--slice-by KEY]
ow eval synth-ocr --corpus C --n 2000 [--levels L0..L4]
ow eval bench     [--baseline refresh] [--counters]
ow eval lint      [--corpus] [--confidence] [--measured] [--estimates]
ow eval fetch     --corpus external                     # verifies sha256; refuses unlicensed
ow eval verify    <results.json>                        # independent fingerprint recompute
ow eval scoreboard --check | --bless
ow eval flakes    [--window 30d]
ow eval doctor                                          # what can this machine run, and why not
```

```
$ ow eval doctor
python 3.12.4 · uv 0.9.2 · platform linux-x86_64
corpora     core@2026.09 ✓ (18.1 MB)   office ✗ not installed   pdf ✗   adversarial ✓   external ✓ (manifest)
cassettes   vllm.olmocr  412/412 ✓     hosted.gpt  0/0 (no tests)
gpu         none                        → suites needing a live model will REPLAY, not call
node        none                        → toolchain tests SKIPPED (deck, video)
network     blocked                     → -m network SKIPPED; `ow eval fetch` unavailable
calibration ocr.char_conf  calibrated (ece 0.018, n 52681, 6d old)
            garble.p_bad   calibrated (ece 0.031, n 18402, 6d old)
            table.recon    BOOTSTRAP   → scores render as ordinal trust only
runnable    T0 T1 T2 T3        est. 6m40s
blocked     T4 (needs --cassette off or a GPU) · T5 (needs --soak)
```

```yaml
# .github/workflows/ci.yml — the jobs this decision adds
gates:                 ubuntu · 3.11 · G1..G17 + ow eval lint --corpus --confidence --measured  (~2m)
contributor-parity:    ubuntu · 3.12 · clean container, NO network, NO gpu, NO node
                       uv sync && pytest ; assert wall ≤ 600 s                                 (~7m)
test:                  {ubuntu,macos,windows} × {3.11,3.12,3.13} · T0..T3                      (9 jobs)
golden:                ubuntu · 3.12 · reductions + counters + BLESS.log gate + PR comment
conform:               ubuntu · 3.12 · D3's kit from a TRUSTED TAG, never the PR branch
nightly-eval:          ubuntu-a10g · T4 · suites + baselines refresh + scoreboard --check
weekly-soak:           ubuntu · T5 · fuzz + RSS + 4M-cell + the anydoc-marshal benchmark
```

**Error codes (append to `codes.toml`; requests a sixth prefix `OW-E-*`, additive under G13):**

```
OW-E-001  measured_on incomplete: field '{field}' missing            → fill it or do not publish
OW-E-002  truth reference is the subject's own output                → set truth.kind and a real reference
OW-E-003  golden diff without a BLESS.log row                        → ow eval bless --reason '<>'
OW-E-004  cassette miss for {service} key {key}                      → ow eval record --service {service}
OW-E-005  counter delta {counter} {old}→{new}                        → ow eval bless --counters --reason '<>'
OW-E-006  fixture {path} has no corpus.toml row                      → add the row with a licence
OW-E-007  spdx '{spdx}' not in the corpus allowlist                  → remove the fixture or amend the allowlist
OW-E-008  score_kind '{kind}' declared but never written             → write it or remove the declaration
OW-E-009  trust tiers non-monotone: err({a})={x} > err({b})={y}      → fix the tier assignment
OW-E-010  gate '{gate}' past review_by {date}, owner {owner}         → review it or extend the date
OW-E-011  retrieve run: judge not validated (n_double={n} < 100)     → ow eval run --validate-judge
OW-E-012  fairness violation: adapters resolved {n} '{role}' models  → pin one model for every role
```

---

## Rationale

**Three arguments carry this design, and each of them beat a more conventional alternative.**

**First, the contributor's laptop is the design constraint, not an afterthought.** The single most
common way an ecosystem dies is that only the maintainers can run the tests. Every mechanism above
that looks like extra machinery — cassettes, reductions, corpus-core's hard ceiling, the marker
layout, `ow eval doctor`, the `contributor-parity` job with a wall-time assertion — exists to keep
`git clone && uv sync && pytest` green, offline, GPU-free, in under ten minutes. That is a bet: I am
spending roughly three of eleven engineer-weeks on it. The return is that "add a driver in an
afternoon" is true end-to-end — scaffold, conform green, `ow eval run --corpus core`, a public
scoreboard row — instead of true up to the point where the tests need an A100.

**Second, a golden that jitters is a golden that gets deleted, so the golden must be a projection
with a declared volatility tier.** This is the one place I think all three prior-art traditions get
it wrong. Blob snapshots are what people reach for; D2's own arithmetic (300k–600k blocks for a
5,000-page document; ~338 B/block) makes them unreviewable, and D2's exclusion of geometry from
`content_digest` is an admission that geometry is noise. Splitting into `frozen` shape / `tracked`
outline / `informational` text costs one module and buys three things a blob cannot: a diff a
reviewer reads in ten seconds, a gate that survives a pdfium patch, and — the part that matters most
— a *headline sentence* ("6 fewer tables, 174 more cells") that goes at the top of the PR comment. A
golden system's real output is a sentence, not a file.

**Third, confidence is decoration unless a specific chain holds, and the expensive link in that chain
is labels — which is where the free label sources earn their place.** The chain is: a classifier
exposes a probability (D4 already refuses labels), the probability has a named `score_kind` (D2
already refuses an unnamed scale), the `score_kind` has a fitted reliability curve on a named eval set
(new), the curve passes ECE/Brier (D4's numbers, generalized), and *no surface may render the number
without the curve* (new, and the load-bearing one). Every project that ships a confidence field skips
the last two links, and D4 already predicted the consequence: marker's `>= 0.05` recheck gate is
meaningless against an uncalibrated probability. The reason everyone skips them is labelling cost, so
the contribution I would most defend is §5.2's Sources A and B: **native OOXML text is free exact
truth for office parsing, and a born-digital PDF rendered back to pixels is free exact truth for
OCR.** Together they produce ~150k labelled points in one nightly run, on real documents, with a
stated bias and a degradation ladder that bounds it. That turns calibration from a research project
into a cron job, and it is the difference between a confidence field with three consumers and one
with zero.

Beyond those, the adjudications went as follows. **Counters over wall clock** as the primary
regression gate, because the four failures I most fear (a silent re-render, a signal computed on a
clean page, a 100% cache miss, a free operator re-billing a paid one) are all exactly-detectable and
all invisible in timing noise — D4 already writes one of them as a test and I generalize the
mechanism. **A static, forkable scoreboard over any hosted thing**, for the same reason D3 rejected a
hosted registry: it is an availability dependency and a rota. **`doc_acc` as the headline extraction
metric**, on lift's 90.2 → 20.9 collapse, because a product promise lives on the second number and
every vendor reports the first. **Cost as a first-class column with the default sort being
accuracy-per-dollar within a licence tier**, because the 4-point surya/olmocr gap *is the price of
clause 2(c)* and a table sorted on raw accuracy re-litigates a settled licence decision every time
someone opens it. And **the entrant-bias marker applied to ourselves**, because anydoc and olmOCR both
scored themselves on their own benchmarks and both were honest enough to say so — a rule that exempts
its author is a marketing rule.

---

## Tradeoffs

- **~11 engineer-weeks plus a standing ~0.3 FTE.** Phase E1 (3 wk): `MeasuredOn`, reducers, goldens +
  bless + `BLESS.log`, corpus-core + the licence lint, counters + the counter gate, the marker layout
  and the `contributor-parity` job. E2 (3 wk): cassettes at both seams, the `parse` suite against
  `Grid`, adapters, `timing_basis` enforcement, baselines + ratchet, the first scoreboard page. E3
  (3 wk): calibration (fit, ECE/Brier, Q10, Q11), `synth-ocr` + the degradation ladder, the `extract`
  and `absence` suites, `ow eval correlate`. E4 (2 wk): the `retrieve` suite (adapters, judge, judge
  validation, fairness assertions, spend ledger), the scoreboard generator + `--check`, the
  third-party submission flow, holdout slices. The standing 0.3 FTE is corpus curation, baseline
  refresh, scoreboard review and the annual human-label round — a **named role with a rota**, because
  D3 already learned that an unstaffed registry degrades to unverified cards.
- **Repo weight.** ~18 MB corpus-core in-tree, ~8 MB cassettes, ~25 MB of goldens as plain text (they
  compress in packfiles; do not pre-compress or the diff dies). The 120/240 MB corpora go to git-lfs,
  which is a real operational annoyance for contributors on restricted networks and is why
  corpus-core exists at all.
- **CI cost.** Gates +30 s, `contributor-parity` ~7 min, `golden` ~4 min, nightly ~40 min on one
  A10G-class runner, weekly soak ~3 h. The GPU runner is the one recurring bill, roughly $40–80/month
  at nightly cadence. Without it there is no live-model number and every scoreboard row is a cassette
  replay, which is honest but not a benchmark.
- **The exact counter gate will annoy people.** Every legitimate behaviour change needs a bless. The
  bet is that counter changes are rare and each is worth reading; if the bless rate exceeds ~1 per 10
  PRs the gate is mis-specified and should move to `ratchet`.
- **Cassettes make prompt changes maintainer-gated.** Named honestly in §4.2 rather than papered over.
- **Ten property laws is a real hypothesis budget** (~90 s and occasional shrinking pathologies on
  P3's `DocSink` sequences). The alternative — asserting the same laws on hand-written examples — is
  what every project does and it is why P5's "changes under a change to its inputs" direction is never
  tested anywhere.
- **Running LOCOMO and LongMemEval-S costs money and buys cross-referenceability, not product truth.**
  They are conversational-memory datasets; omniweave's centre of gravity is a 200-page 10-K. I run
  them because they are the only anchor that lets a reader compare us to mem0 and supermemory at all,
  and I say in the scoreboard that the `parse`, `extract` and `absence` suites are the ones that
  describe the product.
- **`omniweave-eval` is dev-tier and therefore untested by its own machinery** at the same rigour as
  runtime code — the reducers get property tests (P-adjacent) and the calibrator gets unit tests, but
  the scoreboard generator is gated only by its own byte-diff `--check`. That is the same trade
  graphify made for skillgen and it is acceptable; it is still a trade.

---

## Failure modes

1. **Cassette rot at a prompt change.** One prompt edit invalidates every cassette for that driver;
   CI goes red on a PR that touched no logic; a contributor without a GPU cannot fix it. Mitigated by
   `--only-missing`, an error message that names the exact command, and a maintainer-triggered
   recording workflow — not eliminated. **This is the design's sharpest contributor cliff.**
2. **The bless gate becomes a rubber stamp.** At forty blessed files nobody reads the reasons. The
   `frozen` tier is the real defence — it is small, it changes rarely, and when it changes the
   sentence at the top of the PR comment is legible. But the mechanism is thin social shell over a
   human process, and it will decay before anything else here does.
3. **Calibration is corpus-local, and we will be blamed for it.** D4 already names this for
   `garble.score`: ECE ≤ 0.05 on our documents says nothing about an 80%-Thai corpus, a
   mathematics-heavy corpus, or 1970s typewriter scans. `ow eval calibrate --local` lets an operator
   refit and register their own eval set, and the serve envelope names which set produced the number —
   that is the honest answer and it is also the enterprise feature, but the shipped default will be
   miscalibrated for somebody on day one.
4. **The synthetic OCR labels over-state clean-document accuracy and could over-state it
   systematically.** A rasterized born-digital page has no bleed-through, no skew from a physical
   feeder, no scanner-specific JPEG ringing. The degradation ladder approximates; the human-labelled
   `scan-degraded` slice anchors; the gap between L4 and human is reported on the calibration page.
   If that gap is large the synthetic source is worth less than claimed, and we will find out at E3,
   not at E1.
5. **The counter gate is defeated by a genuinely nondeterministic driver.** `tokens_out` is not
   deterministic for a sampling model even under a cassette if the cassette key misses. The mitigation
   is that under `--cassette required` the response is byte-identical and therefore so is
   `tokens_out`; the residual is a driver that consults a clock or a RNG *outside* the service seam,
   which D3-4's purity rules and D1's semgrep ban on `time.time()` are supposed to prevent and which
   would show up here as an unstable counter — arguably a feature.
6. **The scoreboard invites tuning to the public corpus.** The holdout slice detects a > 5 point gap
   and nothing prevents the behaviour. At small N the holdout gap is itself noisy, so the ⚠ will fire
   spuriously and then be ignored.
7. **`contains_pii = false` is self-declared, and the most useful fixtures are exactly the risky
   ones.** A real scanned invoice with a real address is the fixture that catches the bug and the
   fixture that ends a diligence review. The design pushes hard toward synthetic adversarial content
   and named-public-source real content, which means the corpus systematically under-represents the
   messy private documents that are most of the market.
8. **The four-minute T2 budget breaks the day corpus-core grows.** Exactly D3's stated rot for the
   five-minute conform tier. Same defence: the timing assertion is treated as a correctness test and
   corpus-core has a hard displacement ceiling. Both defences are procedural and both will be
   argued with.
9. **Judge drift on the `retrieve` suite.** The judge model will be deprecated and cross-epoch numbers
   will not be comparable. `judge_model` is in `MeasuredOn` and a judge change starts a new scoreboard
   epoch with the old rows retained and marked — the same rule D4 states for a signal-provider upgrade
   — but "the numbers reset" is a genuinely bad experience and there is no fix.
10. **Perf baselines drift with the GitHub runner fleet.** 25% tolerance absorbs most of it; the
    counter gate carries the real signal; a dedicated runner would be better and costs money we are
    not spending on day one. Expect two or three false-positive timing failures per quarter.
11. **The input that breaks this design:** a 4,000-page mixed PDF — 3,999 clean digital pages and one
    scanned exhibit — from a producer family the corpus does not contain. Its `shape` reduction is
    600k lines and unreviewable at any tier; its counters are dominated by the 3,999 free pages so a
    regression on the single escalated page is a delta of 1 against a baseline of 4,000 and reads as
    noise; and no calibration slice covers its producer family, so every score on it is `bootstrap`.
    The partial answers are per-slice counters (`escalations`, `page_renders` — the single scanned
    page moves those by 100%) and per-slice calibration status in the envelope. But the honest
    statement is that this design measures corpora well and measures *one pathological document*
    badly, and that is the document a customer will send on the first day.
12. **`omniweave-eval` and five corpus distributions are five more things to version, release and
    keep at `RELEASE`.** D1 already calls eleven distributions "real release coordination"; this makes
    it seventeen-ish. Corpora should almost certainly move to a slower cadence than `RELEASE`
    (`@2026.09` in the examples above is deliberately a date, not a semver) and that is a wrinkle in
    D1's single-version rule I have papered over with the `tier` column rather than solved.

---

## Why I reject the alternatives

- **Vendor olmOCR-Bench / OmniDocBench wholesale and report their numbers.** We cannot: their
  document sets are not redistributable, and the published numbers from the Datalab trio are not
  reproducible at all — `grep -rn "revision=" marker/ surya/ lift/` returns **zero hits**, so the
  benchmarked checkpoint is not the served one, and marker's headline additionally needs `--use_llm`,
  which egresses page images to Gemini by default. Taking the *taxonomy* and building a licence-clean
  corpus is the only lawful path, and the correlation page (§9.3) is the answer to the reasonable
  objection that it reads as evasion.
- **Whole-document snapshot goldens.** The obvious choice, and it fails on D2's own arithmetic:
  unreviewable diffs, jitter on every pdfium patch, and a review culture that learns to type
  `--update-snapshots`. Reductions with declared volatility tiers cost one module.
- **A single scalar "quality score" per driver.** D3 already ruled that capability is expressiveness
  rather than accuracy and moved ranking to D4; a scalar additionally hides the `table` vs `order`
  split that is exactly what routing needs, and D4's Scoreboard is keyed per slice. A scalar is a
  marketing artifact wearing an engineering one.
- **Live model calls in CI, with a budget cap as the safety.** A cap is a bound on the damage, not on
  the flakiness, and olmocr's own defaults are a 64× amplifier fired in parallel. Cassettes or
  nothing; a fall-through-to-live path is a harness that bills you for a network blip.
- **Wall-clock as the primary performance gate.** Noise on shared runners, fails on Tuesdays, teaches
  rerun. Counters first, timings on a per-runner ratchet — and D1 already established the ratchet.
- **A hosted eval service or a dashboards-as-a-service integration.** An availability dependency, a
  credential rota, and an artifact nobody can fork or run offline. Same reasoning D3 used against a
  hosted registry, and a static site generated from committed JSON is strictly better for adoption:
  a prospective contributor can diff it.
- **Property tests that generate documents.** You cannot hypothesis your way to a valid DOCX. Generate
  the *model*; fuzz the *bytes*. Two tools, two jobs, and anydoc already proved the byte half works —
  12 targets and the only fuzzed parser in the collection.
- **Publishing confidence as a percentage by default, with a footnote.** This is what everyone does
  and it is why nobody trusts a confidence field. docling had the right instinct (publish the ordinal,
  keep the cardinal internal) and stopped one step short; the missing step is a mechanical status that
  the renderer consumes, so there is no code path from an uncalibrated float to a progress bar.
- **A `--warn-only` or `--skip-flaky` escape on any gate.** D1's own risk register names adding
  `--warn-only` as *the* social failure mode of its import-graph scanner. A downgrade is a `tier`
  change in `gates.toml`: a reviewed diff with an owner and a date, not a flag someone adds at 2 a.m.
- **Skipping the `absence` suite as too exotic.** It is ten tests, it is the cheapest genuine
  differentiator in the framework, and the alternative is shipping the same confident zero every RAG
  system ships. jcodemunch measured the consequence: a user got confident zeros over ~1,975 unindexed
  files and moved to another tool.
- **Deferring the scoreboard until the numbers are good.** The scoreboard's value is as an adoption
  asset and a third-party on-ramp, and both of those need it to exist *before* the numbers are good —
  a wall of `UNKNOWN` with a `not_measured` column is the truth, and D4 already ruled that `UNKNOWN`
  is the correct zero value for exactly this reason.
