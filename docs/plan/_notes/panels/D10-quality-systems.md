# D10 — Quality, evaluation, testing and trust

**Panel:** D10 · **Seat:** the systems purist · 2026-09-01

> Note on numbering, so the judge is not confused: `D2-docmodel.md`'s Consequences section addresses
> a "**Serve (D10)**". This panel is **D10 = quality, evaluation, testing and trust**. Where D2
> hands "D10" the obligation to claim byte-exactness only for `quote = VERBATIM` and to *say so*,
> that obligation lands squarely in my remit as a **mechanically gated invariant** (Q7 below), and I
> discharge it. Everything else D2 addressed to a serve panel is that panel's.

---

## Headline

**Evaluation is a data model, not a CI job.** Every quality claim omniweave makes — a golden diff, a
benchmark row, a `[[quality.benchmark]]` value in a `driver.toml`, a `trust` tag rendered in an agent
response, a p95 latency in a card, a number on the public scoreboard — is a row in one
`.owstore`-shaped SQLite schema, produced by a **deterministic, RNG-free harness**, carrying
`(n, ci95, corpus_digest, measured_on, witness)`, and **a confidence signal that has no measured
reliability curve in the current release is stored and never surfaced.** The three load-bearing
mechanisms are: (1) the golden differ for parsers **is `rebind`** — D2 already specified a
carried/revised/created/retired matcher with per-page match rates, and that is exactly a snapshot
diff, so there is one implementation and no second one to drift; (2) the **paired-damage absence
suite** — inject one D2 `Diag` code at a time into a pristine corpus and assert the retrieval answer
degrades to a named cause instead of a confident zero — which is deterministic, LLM-free, runs in
under 60 s, and is therefore a *per-PR* gate for the property every RAG system silently violates; and
(3) **calibration as an admission gate** — an ordinal tag must show strictly increasing empirical
accuracy with non-overlapping Wilson intervals between adjacent buckets, or serve may print its name
and must print `(uncalibrated)` and may never print a percentage, a grade, a bar or a colour.

The structural mistake I am buying insurance against is the one every repo in `_collections/` made:
quality lives in console output and a hand-maintained markdown table, so in year three nobody can
answer *when did this regress*, *is that difference significant*, or *does our confidence tag mean
anything*. Those three questions are unanswerable retroactively. They must be schema.

---

## 1. Design

### 1.1 The thesis, and why it is a data-model decision rather than a testing decision

docling computes the best per-page quality signals in the collection and **consumes none of them** —
`do_ocr` is a document boolean (parse digest). Worse, verified in tree: `table_score` is assigned in
exactly two places (`docling/pipeline/standard_pdf_pipeline.py:867`,
`legacy_standard_pdf_pipeline.py:245`), and both compute the *document* score as
`np.nanmean([c.table_score for c in conv_res.confidence.pages.values()])` over a per-page field that
is **never assigned anywhere in the repo** (`grep -rn "table_score\s*=" docling/` returns those two
lines only). So `PageConfidenceScores.mean_score`
(`docling/datamodel/base_models.py:456-466`) is a four-component `nanmean` that is structurally a
three-component mean, and `_score_to_grade` (`:434-443`) then publishes EXCELLENT/GOOD/FAIR/POOR off
it. A grade computed from a component that is always NaN is decoration with a type signature. D2 has
already corrected the model side (`table_score` computed from `recon` scores or NULL and excluded).
My job is to make the *general* case impossible: a number that reaches a user must have a measured
relationship to ground truth, recorded, dated, and re-checkable.

That is not achievable with tests. Tests answer "does this commit behave"; they cannot answer "what
is the empirical accuracy of the `INFERRED` tag on scanned-PDF slices, measured against what, when,
and with what sample size". Those are rows. So the evaluation layer gets a schema with the same
identity discipline as everything else in the framework: content-addressed inputs
(`content_digest`, `corpus_digest`), an interned reproduction tuple (`Producer`, shared verbatim
with D2/L5), and append-only history.

Second thesis, equally structural: **the harness has no RNG on its default path.** olmOCR-Bench's
`calculate_bootstrap_ci` and `perform_permutation_test` (`olmocr/bench/utils.py:33,55,120,172`) call
`np.random.choice` and `np.random.shuffle` with **no seed anywhere**, and `benchmark.py:262` samples
with unseeded `random.sample`. So the published 95% CI and the pairwise p-values are not reproducible
run to run — the exact property a reviewer needs. §1.9 replaces both with closed forms that need no
RNG, which is cheaper *and* removes the seed question rather than answering it.

### 1.2 The invariant set

An invariant with no enforcer is a comment (D2 §11, adopted verbatim as a principle).

| # | Invariant | Enforced by |
|---|---|---|
| **Q1** | No evaluation number exists outside the `eval_*` tables. | The report generator reads only from the store; a test asserts every value in `scoreboard.json` has a matching `eval_metric` row with the same `eval_run_id`. |
| **Q2** | Every published number carries `n`, `ci95`, `measured_on`, `corpus_digest`, `witness`. | JSON-Schema `required` on `scoreboard.json` and on `[[quality.benchmark]]`; `ow bench scoreboard --check` fails on absence. |
| **Q3** | The harness is deterministic: the same score table yields a byte-identical report. | Closed-form CI and closed-form paired-permutation asymptotic (§1.9). semgrep bans `random`, `secrets`, `numpy.random`, `time.time`, `datetime.now` inside `omniweave_conform/stats/` and `omniweave_conform/report/`. A test runs the harness twice on a frozen score table and byte-compares. |
| **Q4** | Which units get audited is *derived*, never random. | `blake2b(unit_uri‖part‖audit.salt) % 10000 < rate*10000` — D4 R2, reused verbatim, not reimplemented. |
| **Q5** | A tier that cannot run reports `UNKNOWN`; the release gate refuses `UNKNOWN`. | `ow bench --require-slices=<list>`; a test deletes one corpus slice and asserts a non-zero exit naming it. Fixes anydoc's "missing tools are skipped with a warning" (`anydoc/bench/README.md`). |
| **Q6** | A golden may only be blessed by a reviewed commit, and the bless flag is off in CI. | `OMNIWEAVE_BLESS` env flag plus `test_bless_flag_is_off()` — docling's `tests/test_data_gen_flag.py` shape adopted verbatim (`assert not GEN_TEST_DATA`), which is the only reason a stray `DOCLING_GEN_TEST_DATA=1` cannot silently rewrite 412 golden files. |
| **Q7** | `quote = VERBATIM` is byte-verifiable, always, on every corpus. | `span_exact_rate` is a **gate at 1.000**, not a metric. Predicate is D2's own: `normalize_k(part_bytes[os_a:os_a+os_b]) == block.text`, i.e. `Doc.verify_quote()`. Needs no labelled corpus, so it runs on the user's documents too. This discharges D2's obligation on serve. |
| **Q8** | A confidence signal is surfaced only if calibrated in the current release. | `Q-G18/19/20`; the serve envelope carries a `Calibrated` record whose `state != "calibrated"` forbids rendering any number, percentage, bar, colour ramp or grade. A renderer test asserts the output contains no `%` and no `QualityGrade` member for an uncalibrated signal. |
| **Q9** | An ordinal confidence tag must actually separate. | Strictly increasing `p_hat` across buckets **with non-overlapping 95% Wilson intervals between adjacent buckets**. A tag that does not separate on a slice is `uncalibrated` for that slice. |
| **Q10** | Driver self-report never enters a ranking. | D4 R12 verbatim (`route_scoreboard` filters `source IN ('agree','audit','feedback')`). Extended here: a `[[quality.benchmark]]` row with `witness != "ci"` is displayed on the public scoreboard but excluded from every ranked column and from `route propose`. |
| **Q11** | A card's benchmark row binds to a corpus by digest and to a witness. | `corpus_digest` and `witness` required on `[[quality.benchmark]]` — **this is the one amendment I request of D3; see §7.** |
| **Q12** | Fixture provenance is complete. | `Q-G21`: every byte under `fixtures/` and under a corpus root has a `FIXTURES.toml` / corpus-manifest row with `sha256`, `spdx`, `source_url`, `retrieved_at`, `attribution`; SPDX must be in the fixture allowlist. |
| **Q13** | A non-redistributable fixture's bytes never enter a repo or a wheel. | `redistribute = false` is unrepresentable in Tier B by schema; a pre-commit hook and a CI job hash every new binary under `fixtures/` against the private-corpus sha256 index and refuse a match. |
| **Q14** | `deterministic = true` is proved *across processes and environments*. | D3's conform `determinism` suite, strengthened: two separate processes with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd; assert equal `content_digest` **and** `layout_digest` per block and an equal `Diag` code multiset. A determinism test that runs twice in one process proves almost nothing. |
| **Q15** | `deterministic = false` declares a measured stability envelope. | Kit-written `[[quality.stability]]` rows: k = 5 runs on a fixed 50-unit slice, coefficient of variation of the metric ≤ the recorded `cv_max`, and the `Diag` code set identical across runs. |
| **Q16** | Every generated or parametrized suite asserts its own non-vacuity. | A `conftest.py` session hook fails if any generator-backed `parametrize` produced zero cases. Directly generalized from graphify `tests/test_architecture_doc.py::test_the_table_was_actually_parsed` — *"a regex that silently matches nothing would make every parametrized test below vacuous."* |
| **Q17** | Incremental output equals full output. | T5 job: full parse of a corpus, then a fresh incremental parse with 20 scripted edits; assert byte-identical `ow doc digest` for every document. codegraph's measured **4.3% of distinct edges wrong, in both directions, silently, forever** is the failure this catches. |
| **Q18** | Absence is evaluated, not asserted. | The T3 paired-damage suite, one damage per `Diag` code that serve's absence contract reads (`diag_code` index, D2). |
| **Q19** | Time budgets are ratios to an in-repo calibrator; memory budgets are absolute. | `tools/perf-budgets.toml`; `UNSTABLE` is a third outcome, and three consecutive `UNSTABLE` on one job is itself a failure. |
| **Q20** | A baseline is release-anchored and cannot ratchet. | Drift vs release N−1 at the row's `tolerance`, **and** vs N−2 at 2×. Ten blessed 9% regressions cannot compound past 2×. |
| **Q21** | A guard that fires on noise is fixed, not disabled. | Every guard declares `min_detectable_effect`; it fires only at paired p < 0.01 **and** effect ≥ MDE. A guard that fires twice with p > 0.01 inside 30 days is listed in `flaky-guards.json`, which fails the release gate until triaged. There is no `--warn-only` for any gate, anywhere. |
| **Q22** | The scoreboard states its confounders and its non-measurements. | `confounders` and `not_measured` are `required` non-empty arrays in `scoreboard.json`. graphify's `*` embedder-confound footnote is the model; graphrag's `RAI_TRANSPARENCY.md` is the artefact type for `not_measured`. |

New CI gates, numbered from **Q-G17** so they cannot be confused with D1's G1–G16, which stand:

```
Q-G17  perf budgets: peak RSS absolute, time as calibrator ratio, WAL peak absolute
Q-G18  calibration-monotone: ordinal tags separate, non-overlapping adjacent Wilson intervals
Q-G19  calibration-sharp:    ECE <= 0.05 and Brier <= 0.08 (D4's numbers, verbatim), 10 equal-mass
                             bins, each bin n >= 30 or reported UNKNOWN
Q-G20  calibration-fresh:    measured_at within [calibration] max_age_days (D4: 30);
                             stale => Degradation(kind="calibration_stale")  (D4's enum, verbatim)
Q-G21  fixture provenance:   every fixture byte has a licence row; SPDX in the fixture allowlist
Q-G22  scoreboard --check:   byte-diff of the generated SCOREBOARD.md (D1 G6's mechanism, reused)
```

### 1.3 The pyramid — six tiers, budgeted, and none of them skippable

| tier | contents | lives in | when | budget | absent ⇒ |
|---|---|---|---|---|---|
| **T0** gates | D1 G1–G16 + Q-G17…Q-G22, semgrep, `layers.toml` | `tools/gate_*.py` | every PR | ≤ 180 s | never absent |
| **T1** unit + property | per distribution; core is stdlib-only so its unit suite is too | `packages/*/tests/` | every PR | ≤ 120 s at `-n auto` | never |
| **T2** golden / snapshot | `.owsum` compare, archive round-trip, `schema/expected` | `tests/golden/` | every PR | ≤ 90 s | never |
| **T3** absence + damage | paired-damage retrieval suite, deterministic, **zero LLM** | `omniweave-conform` | every PR | ≤ 60 s | never |
| **T4** conformance | D3's eleven suites + the `quality` suite | `omniweave-conform` | driver PR, nightly all | mandatory tier ≤ 300 s (D3's assertion, kept) | never |
| **T5** benchmark | `omniweave-golden` accuracy, retrieval, perf, incremental-vs-full | nightly + release | ≤ 90 min on one GPU box | **UNKNOWN**, never SKIPPED |
| **T6** soak / fuzz / adversarial | 12 `cargo-fuzz` targets seeded from `anydoc/fuzz/seeds/`, 5,000-page RSS run, 24 h store soak | weekly | — | **UNKNOWN** |

Two policies make the pyramid real rather than aspirational:

**Skip is not a state.** A tier or a slice that cannot run is `UNKNOWN`, and `ow release check`
refuses on `UNKNOWN`. anydoc's harness has the right *shape* — it reads whatever is in `samples/`, so
you can run it on your own corpus — and the wrong *policy*: missing tools are skipped with a warning.
D3 already ruled "a skipped gate is not a gate"; this generalizes it from timing to coverage.

**Randomized property testing is a bug finder at night and a flaky gate in a PR.** Hypothesis profiles:
`dev` (50 examples), `ci` (500, `derandomize=True`), `nightly` (5,000, `derandomize=False`). A PR's
pass/fail must be a function of the code, not of the clock. Counterexamples found at night are
minimized and committed to `tests/corpus/hypothesis/` as explicit regression cases — the fuzz-corpus
discipline applied to property tests. Precedent: graphify, jcodemunch and local-deep-research all
declare `hypothesis` and only graphify's `tests/test_id_normalization_contract.py` and jcodemunch's
`tests/test_property_based.py` actually use it; declaring the dependency is not the practice.

### 1.4 Golden corpora and fixture licensing — three tiers, and the trap

The default outcome, verified in tree, is a redistribution exposure nobody notices: **docling ships
683 files and 99 MB under `tests/data/` — arXiv PDFs, JATS eLife articles, USPTO documents, DOCX,
PPTX, XLSX, audio, TIFF — and `find tests -iname "*licen*" -o -iname "*NOTICE*"` returns nothing.**
No per-file provenance, no SPDX, no source URL, inside an MIT repository. That is what happens when
fixtures are added by whoever needed one.

**Tier A — `fixtures/` (in repo, ≤ 20 MB total, gated).** The rule that makes this affordable is
**synthesize rather than acquire**. D1's list (40-byte docx, encrypted pdf, zip bomb, 4M-cell xlsx,
fuzz corpus) and D2's (`gen-5000p.pdf`, `merged-4m-cell.xlsx`, `ragged-table.docx`,
`spanned-merged.pptx`, `html-no-pages.html`) are *all* generatable: a 5,000-page PDF and a 4M-cell
sheet cost 3 KB of committed generator script instead of 90 MB of binary, are deterministic, carry no
licence at all, and can be re-parameterized when D2's open question about the 60–120 blocks/page
envelope is answered. Only pathologies that cannot be synthesized — a real 1970s scanned filing, a
genuinely broken producer's output — need a licence row, and those go in `FIXTURES.toml`.

**Tier B — `omniweave-golden` (redistributable, versioned, out of tree).** This is **a data artifact,
not a Python distribution**, precisely so that D1's *eleven first-party distributions* stands
unamended. It ships as `omniweave-golden-<YYYY.MM>.tar.zst` plus `manifest.toml` plus `.sha256`,
installed by `ow golden install` into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` and
**digest-verified on every use**, with D1's toolchain rule applied verbatim: *a digest mismatch is a
permanent failure and never triggers a fetch.* Every document carries the hyperframes media-ledger
row (`{spdx, licence_url, source_url, retrieved_at, sha256}`) that the risk digest already prescribes
for embedded media, applied to fixtures. `version = "2026.09"` and `suite = "omniweave-golden"` are
not my choice — D3's card example already fixes both strings, and I use them verbatim.

**Tier C — `omniweave-golden-private` (non-redistributable).** Customer documents under NDA, purchased
corpora, and any public benchmark whose terms forbid redistribution. **No bytes in any repo, ever.**
What is committed is the assertion set plus each document's `sha256` and a fetch recipe. graphify's
harness states the shape exactly — *"Datasets are not redistributed; the harness documents the
expected local layout"* (`graphify/BENCHMARKS.md`). A Tier-C slice with absent documents reports
`UNKNOWN` (Q5), never `SKIPPED`.

The landmine to write down now rather than discover later: **an assertion set derived from a document
may itself be a derivative work.** An `ORDER` assertion quoting 60 characters of a copyrighted page is
a quotation; a `PRESENT` assertion set that collectively reproduces a page is a reproduction. So the
corpus manifest carries `assertions_redistributable` **separately from** `document_redistributable`,
every assertion file records `derived_from_sha256`, and Q-G21 refuses a Tier-B assertion file whose
total quoted-character count against one source document exceeds 2,000 characters or 10% of the
document's extracted text, whichever is smaller.

### 1.5 The assertion model — one table, two evaluators

The single most consequential design choice in the harness: **assertions bind to owdoc addresses, and
a projection evaluates the same assertions against a plain text/markdown string** for cross-tool
comparison. Not two assertion sets. One table, two evaluators, and every assertion declares which
evaluators can answer it.

- `evaluate_owdoc(assertions, doc: Doc) -> tuple[Verdict, ...]` resolves by `addr` (D2's type-free
  `p14/3`), reads `kind`, `layer`, `ord`, `quad`, `quote`, `trust`, and answers relational table
  assertions through `Grid.up/down/left/right/top_heading/left_heading` — which D2 explicitly notes
  are *"exactly olmOCR-Bench TableTest's relational assertions, answerable in O(1)."* Exact, no fuzzy
  matching needed for structure.
- `evaluate_text(assertions, md: str) -> tuple[Verdict, ...]` is olmOCR-Bench's evaluator, adopted
  with `normalize_text` **verbatim** (`olmocr/bench/tests.py:47-79` — the `<br>` fold, bold/italic
  strip, `\s+` collapse, NFC, and the twelve-character fancy-punctuation map including
  `µ -> μ`). Its `max_diffs` fuzzy budget, `first_n`/`last_n` windowing and
  `find_near_matches` ordering semantics come along unchanged.

Why this matters: a benchmark written natively against your own document model is unfalsifiable by
competitors, and a benchmark written against markdown strings throws away everything that makes owdoc
worth having (per-cell geometry, `quote` tiers, `layer`). Doing both from one table means the
cross-tool subset is format-agnostic **by construction**, and the report publishes how many
assertions it had to drop to be fair. Anyone can check the drop count.

The human-review state travels **inside the assertion record**, olmOCR-Bench's best small idea:
`checked ∈ {verified, rejected, unchecked}` (`olmocr/bench/tests.py:35-37`). An `unchecked` assertion
may not enter a published metric; it may only enter the candidate pool the review app drains. This is
what stops a corpus from silently accumulating wrong ground truth.

**Anchoring — the anydoc correction, made structural.** anydoc's harness is the most honest in the
collection and it names its own flaw: quality is *"word-trigram containment against anydoc's own
output — not a truth measure"* (`anydoc/bench/README.md`; mine-parse C6.4). A self-anchored metric
cannot detect a systematic error you share with nothing else. So: the anchor is human-verified
assertions plus rendered ground truth (anydoc's own `render_truth.py` idea, which they built and did
not use as the anchor). A containment-against-our-own-output signal may still exist as a
dropped-content *detector*, and it carries `not_a_truth_measure = true` **as a schema field**, not as
a sentence in a README, so no report generator can promote it into an accuracy column.

### 1.6 Snapshot / golden testing for parsers, where output is large and noisy

The hard part is that a golden for a 200-page PDF is a 40,000-line diff nobody reads, and a driver
patch that changes one bounding box by 0.3 pt rewrites the whole file. Two levels.

**Level 1 — `.owsum`, committed, always compared.** One deterministic line per page:

```
p0014  n=87  kind{para:61,heading:3,table:1,table_cell:20,caption:1,page_footer:1}
       layer{body:85,furniture:2}  trust{2:80,1:7}  quote{normalized:80,reflowed:7}
       cdig=9f2c4a1b  ldig=77a2e0d3  diag{}
```

`cdig` is the merkle `content_digest` of the page's block subtree (D2 already defines
`content_digest` as merkle over children in `ord` order, so this is free), `ldig` the equivalent over
`layout_digest`. A 5,000-page fixture is 5,000 lines ≈ 400 KB — reviewable, greppable, and a
regression names the page in the first line of the diff. Geometry lives only in `ldig`, so a
content-only change and a geometry-only change are visibly different failures, which is exactly why
D2 split the two digests.

**Level 2 — the semantic diff, and it is already written.** When `.owsum` diverges, or on `--full`,
`ow doc diff old.owdoc new.owdoc` prints carried / revised / created / retired blocks with per-page
match rates — **because the differ is `rebind`**. D2 specifies `rebind()` with three matching rules
(equal `content_digest` under the same parent carries the id; equal `addr` and `kind` with a changed
digest carries it and bumps `revision`; otherwise new id plus a `block_history` row) and a
`RebindReport{carried, revised, created, retired, match_rate_by_page, quarantined, threshold}`. That
report *is* a snapshot diff report. One implementation, two consumers, and the golden test's
tolerance is `RebindReport.threshold`, which reuses a number the model layer already tunes and
quarantines on. There is no second matcher to drift from the first.

**Tolerances, sourced.** Strict tier: `content_digest` equality, exact. Geometry tier:
`layout_digest` equality first (whole-point quantization already absorbs driver jitter by D2's
design); on failure the report falls back to a per-corner delta against docling's own verified
constants — `COORD_PREC = 2`, `STRICT_BBOX_TOL_RATIO = 0.0025`,
`FUZZY_BBOX_TOL_RATIO = 0.005` for OCR/image output (`docling/tests/verify_utils.py:26-30`). Text
tier: docling's `verify_text` fuzzy Levenshtein path with a threshold of **0.05, not its 0.4** — a
40% edit-distance budget on a golden is not a test, and docling's own default is the one number in
that file I decline to copy.

**Bless is a reviewed act.** `OMNIWEAVE_BLESS=1 pytest --bless` regenerates; `test_bless_flag_is_off()`
fails the session if the flag is set, so CI can never bless (Q6, docling's
`tests/test_data_gen_flag.py` shape). A bless commit must touch `.owsum` and `CHANGELOG` in the same
PR, and the PR template asks for the `RebindReport` summary pasted in — a diff of 4,000 created and
4,000 retired blocks is a re-segmentation, and that is a review conversation, not a rubber stamp.

### 1.7 Property tests for round-trip, and the failure corpus

D2 already fixes five schema gates including `write(read(b)) == b` and
`import(export(store)) == store`. Those are example-based. The generative layer:

A Hypothesis strategy `owdocs()` builds arbitrary **valid** Blocks / Grids / Marks *by construction*
(never by `filter`, which shrinks catastrophically), then:

1. **Archive round-trip.** `import(export(store)) == store` over generated stores, not only fixtures.
2. **`owcheck` completeness.** Everything the builders can produce passes `owcheck`; a mutation
   library that violates each named invariant one at a time (break the parent/`ord` bijection, break
   grid exactly-once, orphan a `rel`, set `quote=verbatim` with `part.store_ref IS NULL`) produces a
   *specific* failure code each time — the check is proved to be non-vacuous invariant by invariant.
3. **Geometry idempotence.** `Quad.from_driver` re-applied to the stored frame is the identity, for
   every `(origin, unit, page_h, dpi, rotation)` combination. This is the property that keeps
   "normalize once at ingest" true through five years of contributors, and D2 made it enforceable by
   giving `Quad` no other public constructor.
4. **Grid exactly-once under adversarial spans.** Arbitrary overlapping row/col spans; assert every
   `(r, c)` in range resolves to exactly one `Origin`, that clamping emits
   `OW_TABLE_SPAN_CLAMPED`, and that the table's trust drops to `INFERRED` — anydoc clamps
   deliberately (`src/model/table.rs:182-186`) and raising would fail legitimate HTML.
5. **SpanMap round-trip.** For every serializer × every `layers` subset: for every block,
   `to_text(RenderSpan(view_id, *offsets_of(b)))` returns exactly `[(b, full TextSpan)]`. This is the
   property that makes serve's citation claim mechanical rather than hopeful, and D2 requires
   `serialize` to return `(str, SpanMap)` precisely so it is testable.
6. **Digest input closure — a negative property, and the one most likely to save us.** Mutate
   `producer_id`, `x`, `marks`, `score`, `origin_operator`, `revision`, `ord`, every span field:
   assert `content_digest` is **unchanged**. Mutate `text` to an NFC-equivalent form: unchanged.
   Mutate `kind`, `layer`, `payload`, or any child's digest: **changed**. D2 enumerates the
   inclusion list; this asserts the exclusion list, which is the half that silently rots and whose
   rot means either a permanent 100% cache miss or a cache that serves stale results.

Every counterexample found in the nightly profile is minimized and committed as an explicit case, and
`tests/corpus/hypothesis/` is treated exactly as `anydoc/fuzz/seeds/` is treated: an append-only
record of things that broke once.

### 1.8 Determinism where models are involved — three classes, three tests

D3's card carries `deterministic: bool`; D3's conform kit has a `determinism` suite. Neither says
what determinism means for a VLM. Three classes:

**Class 1 — bitwise deterministic** (`deterministic = true`: anydoc, pdfium, native XML). Test Q14:
two *separate processes*, differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd; assert equal
`content_digest` and `layout_digest` per block and an identical `Diag` code multiset. Environment
variation is the whole point — dict ordering, locale-dependent number formatting and TZ-dependent
timestamps are how "deterministic" quietly stops being true, and graphify has four recorded cwd bugs
of exactly this family.

**Class 2 — distributionally stable** (`deterministic = false`, local weights, pinned revision).
Bitwise equality is not achievable and demanding it produces a permanently red suite that gets
disabled. The contract is a **stability envelope**, kit-written into the card:

```toml
[[quality.stability]]
slice = "pdf/scanned/en" ; metric = "text_f1" ; k = 5
mean = 0.883 ; cv = 0.011 ; cv_max = 0.030      # coefficient of variation over k runs
diag_set_stable = true                           # the Diag code SET is identical across all k
measured_on = { weights="olmocr-7b", model_rev="a1b2c3…", runtime="vllm",
                runtime_version="0.9.1", sampling="t=0.1,top_p=0.95", prompt_version="4" }
```

Two things ride along. `cv_max` is declared and the kit *measures* it, so an unstable driver cannot
hide behind "models are like that". And `diag_set_stable` is separate from the metric, because a
driver whose accuracy is stable but whose *failure modes* wander is a routing hazard even when the
score looks fine.

**Class 3 — unpinnable** (hosted API, `model_rev` not an exact SHA). `grep -rn "revision=" marker/
surya/ lift/` returns **zero hits**, so even the numbers those repos publish are against an
unidentifiable checkpoint; HunyuanOCR's published 94.10 OmniDocBench was measured on TensorRT while
the repo ships Transformers and vLLM, which it admits disagree. Rule: **a driver whose `measured_on`
carries no exact `model_rev` may not contribute a `[[quality.benchmark]]` row at all.** It may
contribute dated `driver_observation` rows (D3's table) and a scoreboard entry stamped
`unpinned: true`, which is displayed and never ranked. D2 already makes `model_rev = "main"` a lint
error in `producer`; this is the same rule at the evaluation boundary.

### 1.9 The benchmark harness — metrics, and statistics with no RNG

**Metric definitions.** All computed per **slice** (`slice_key` per D4's
`[slice] by = ["unit.format","unit.producer_family","decode.has_text_layer","corpus.lang"]`),
macro-averaged across slices with `min_slice_n = 30` (D4's `min_audit_n`, reused). A slice below the
floor reports `UNKNOWN`, is excluded from the macro-average, **and is named in the report** — never
silently dropped, because silent dropping is how a headline number becomes a claim about whichever
slices happened to be big.

| metric | definition | source of the shape |
|---|---|---|
| `text_recall` / `text_precision` / `text_f1` | char-level over `Layer.BODY`, both sides through olmocr `normalize_text`, aligned by **banded** Levenshtein (band = 5% of \|ref\|, capped 4,096) | docling `verify_utils.levenshtein`, olmocr `normalize_text` |
| `order_acc` | pass rate over `ORDER` assertions; owdoc path compares `(page, ord)`, text path uses `find_near_matches` | olmOCR-Bench `TextOrderTest` |
| `structure_f1` | **the metric D3's card already names.** Align candidate→reference by `content_digest` first, then normalized text at `fuzz.ratio ≥ 0.90` under a deterministic greedy matcher in `(page, ord)` order. A matched pair is *correct* iff `kind` **and** `layer` agree. `F1 = 2PR/(P+R)`. Ships with a `kind_confusion` matrix. | D3 `[[quality.benchmark]]` |
| `table_rel_acc` | pass rate over `TABLE` relational assertions via `Grid`; **reported separately for `has_merges = 0` and `= 1`** | olmOCR-Bench `TableTest` |
| `hallucination_rate` | `1 − pass rate` on `ABSENT` assertions. **Never folded into any composite** — a system that invents text raises `text_recall` | olmOCR-Bench `TestType.ABSENT` |
| `field_acc` / `doc_acc` | per-field and whole-document exact match with numeric tolerance; sliced by lift's five adversarial categories. **Always printed adjacent** | lift, 90.2% field vs **20.9% full-doc** |
| `furniture_f1` | F1 for `{FURNITURE, NOTE}` vs `BODY` | docling `ContentLayer`, marker `ignore_for_output` |
| `span_exact_rate` | **a gate at 1.000, not a metric** (Q7) | D2 testkit predicate |
| `recall@k`, `ndcg@10` | retrieval, k ∈ {1,5,10,20} | LOCOMO / LongMemEval convention |
| `citation_soundness` | fraction of returned `cite` tokens resolving to a live block whose `verify_quote()` is `match` or `source_ahead` | D2 `QuoteVerdict` |
| `absence_accuracy` | §1.12 | original |
| `wasted_escalation` | agreement > 0.98 across n ≥ 30 on an escalated slice | D4, verbatim |
| `p50/p95_ms_per_unit`, `peak_rss_bytes`, `micros_per_unit` | §1.10 | D3 `[cost]`, D4 `PriceBook` |

Note `structure_f1` uses a **greedy** matcher rather than Hungarian: O(n³) at 600,000 blocks is not
affordable, and greedy in reading order is deterministic, O(n log n), and adequate because the
alignment is anchored by exact `content_digest` matches first. The choice is stated in the report so
nobody re-derives it as a bug.

**Statistics, closed form, zero RNG.** Scores arrive as per-unit values grouped into `S` slices with
sizes `n_s`, means `m_s`, sample sds `sd_s`. olmOCR-Bench's macro structure (score = mean of
per-category scores, bootstrap resampled *within* category) is the right shape and I keep it; its
implementation is not.

```
headline      = (1/S) * Σ_s m_s
se(headline)  = sqrt( (1/S²) * Σ_s sd_s² / n_s )
ci95          = headline ± 1.96 * se                       # CLT per slice, valid since n_s >= 30
```

Paired A-vs-B on the same units, with `d_i = a_i − b_i` over the `N` units where `d_i ≠ 0`. The exact
paired permutation test flips signs; its asymptotic is closed:

```
p = 2 * (1 − Φ( |Σ d_i| / sqrt(Σ d_i²) ))                  # valid for N >= 30
```

Below either floor the harness falls back to an **exact enumeration** (N ≤ 20) or a **seeded**
resampling bootstrap with `seed = blake2b(eval_set_id ‖ candidate ‖ metric ‖ harness_version)`, and
the report stamps `method ∈ {closed_form, exact, resampled}` on every interval. The default path
therefore has no RNG at all, which is strictly stronger than seeding it: there is no seed to lose, no
`np.random` global to be perturbed by an unrelated import, and re-running the report on the same
score table is byte-identical by construction (Q3). It is also ~30× cheaper than 10,000×15,000
resamples in pure Python, which matters because D1's core is stdlib-only and I refuse to add numpy to
the gate path.

### 1.10 Regression gates — budget vs guard, and the calibrator

**Two failures with two owners.** A **budget** is an absolute floor and its breach means "we shipped
something worse than our published promise" (product owner). A **guard** is a delta against the
previous release and its breach means "this change made it worse" (PR author). Conflating them is why
quality gates get disabled: an author cannot fix an absolute floor they inherited.

A guard fires only when `paired p < 0.01` **and** `|effect| ≥ min_detectable_effect` (Q21). MDE is
declared per metric per slice and is derived, not guessed: `MDE = 2 × se(headline)` at the corpus's
current size, recomputed on every corpus release. So a slice too small to detect a 2-point regression
has an MDE of 2 points and does not pretend otherwise.

**Timing on shared runners.** Absolute wall-clock budgets on CI are either constantly red or so loose
they catch nothing; runner variance of 2–3× is normal. The fix: `fixtures/perf/calibrator.py` is a
fixed, dependency-free workload (blake2b over 64 MiB, a 2M-iteration integer loop, 200k SQLite
insert+select) run immediately before and after the measured work. Every timing is reported as
`ratio = t_work / t_calibrator`; the budget is on the ratio. If the two calibrator readings differ by
more than 15%, the runner is unstable and the result is **`UNSTABLE`** — not PASS, not FAIL — and
three consecutive `UNSTABLE` on one job fails, because a gate that is never able to measure is not a
gate.

**Memory is absolute, and it is the more important axis.** Peak RSS is not runner-dependent to first
order, and the failures the evidence actually records are memory failures: codegraph's **5.9 GB WAL
against a 340 MB DB**, and **22 GB / exit 137 (OOM)** at an envelope the unvalved build survived; D1's
own Risks name the anydoc eager Python marshal as a cliff — *"a legal-discovery XLSX near the 4M
grid-slot cap becomes millions of frozen `pyclass` instances in one un-abortable call, and
`limits.rs` caps the Rust side while nothing caps the Python heap"* — and D1's open question #1 asks
for exactly the measurement my T5 tier produces. So `peak_rss_bytes` and `wal_peak_bytes` get hard
absolute budgets per fixture, and the 5,000-page and 4M-cell fixtures are the two rows that matter.

**Anti-ratchet (Q20).** Baselines are **release-anchored**, not commit-anchored. A run is checked
against release N−1 at the row's `tolerance` and against N−2 at 2×. This is my reading of D1's G10
("cold start on 3 OSes vs a recorded per-OS baseline, 25% drift tolerance"), and the reading matters:
if the baseline moves every commit, 25% per step compounds — ten steps is 9.3×. Under a
release-anchored baseline with an N−2 ceiling, it cannot exceed 2× no matter how many blessings
happen. I am not amending G10; I am fixing its degrees of freedom, and saying so out loud because the
other reading is a slow, invisible, unrecoverable loss.

### 1.11 Driver conformance — the `quality` suite, and what attestation does and does not prove

D3 owns the eleven suites (`card`, `purity`, `contract`, `capability`, `idempotence`, `determinism`,
`limits`, `sandbox`, `cost`, `licence`, `fuzz`) and rules that the mandatory tier runs in under five
minutes on a laptop and that `[cost]` and `[quality]` are kit-written. I add one suite and one tier,
and I clarify a boundary D3 left implicit.

**`quality` (suite twelve), non-mandatory, `omniweave conform --bench`.** It runs the driver over the
slices of `omniweave-golden` its `capability.formats` covers, writes `[[quality.benchmark]]`,
`[[quality.stability]]` and `[[quality.calibration]]` rows, and refuses to write a row for a slice
with fewer than 30 units.

**The boundary, stated because a judge will otherwise assume the wrong one:** D3's bar is *"the
honesty of the descriptor, not the excellence of the driver."* Therefore **`attested` requires the
eleven honesty suites and does not require a single benchmark row.** A driver with zero
`[[quality.benchmark]]` rows is attested, admissible, and routable; it simply carries no quality
prior and the router discovers its quality the way D4 already specifies — `agree.decode_vs_page` for
free on every escalation, plus the deterministically sampled audit lane, with `UNKNOWN` as the
scoreboard's zero value. This has to be the boundary, because the slice set D4 wants
(`max_slices = 512`) at n ≥ 30 is ≥ 15,360 units, which cannot fit in five minutes on a laptop and
must not be allowed to gate admission.

**What attestation proves.** D3-13 says the loader recomputes `attestation` and an unattested driver
is never auto-selected. A recomputed self-consistent hash proves the card was not edited after the
kit wrote it. It does **not** prove the numbers were produced against the real corpus on honest
hardware: an author can run the kit against a doctored local copy and publish `structure_f1 = 0.99`
with a perfectly valid attestation. Two fields close it (`corpus_digest`, `witness`) — §7.

### 1.12 Retrieval evaluation

**The primary suite is document-native; LOCOMO and LongMemEval-S are a portability suite, and I say
so in the scoreboard.** Both are multi-session *conversational* QA, not document retrieval, and
graphify's own numbers show they are measuring quite different difficulty: recall@10 of **0.497** on
LOCOMO against **0.844** on LongMemEval-S for the same system (`graphify/BENCHMARKS.md`). Running them
is worth real money as an adoption asset for exactly the reason graphify states — *"the same academic
datasets other memory systems report on, so results are cross-referenceable"* — and worth nothing as
a measurement of whether omniweave parses a 10-K correctly. So they run, quarterly, as adapters in
our harness with our fairness rules, and they sit in their own scoreboard section labelled
**"conversational memory (portability)"**. Their targets are the published field: LOCOMO recall@10
0.497 / QA 45.3%, LongMemEval-S 76% — with graphify's ingest-cost column ($1.40 vs supermemory's
$15.67 at 11× and mem0's $3.48) carried across, because cost-per-point is the axis where a
deterministic-first design wins and the axis most benchmarks omit.

**The primary suite** is `omniweave-golden/retrieval`: queries whose gold answer is a **set of `cite`
tokens** (D2's `d7#412`), over the same corpus the parse suite uses — so a retrieval regression can be
attributed to parsing or to retrieval by holding the `.owstore` fixed. Metrics: `recall@k`, `ndcg@10`,
plus two nobody else computes.

**`citation_soundness`** — the fraction of returned citations that resolve to a live block whose
`verify_quote()` (D2) returns `match` or `source_ahead`. `source_ahead` counts as sound; D2 is explicit
that it is jcodemunch's `git_sha_uncommitted` for documents and *"MUST NOT read as corruption."* A
system that cites a block it cannot verify is worse than one that returns nothing, and this metric is
computable **live on every served response**, not only in the benchmark — which makes it a runtime
guarantee rather than an eval statistic.

**`absence_accuracy` — the paired-damage suite, and my highest-value original contribution.** The
graph digest is unambiguous that the absence contract is *"a framework invariant, not a tool
feature"* and that omniweave's list — *"OCR failed on pages 12–40, PDF password-protected, table
extractor timed out, empty text layer with no OCR fallback, embedding model changed since indexing,
block budget truncated the response"* — **is currently a silent zero in every RAG system.** Nobody
evaluates it. The construction:

```
for (query q, gold cites C) in retrieval_suite:
    for damage d in DAMAGES:                     # one damage dimension at a time
        ok       = pristine corpus
        damaged  = ok with d applied ONLY to the pages carrying C
        assert answer(q, ok).state      == "ok"        and cites(q, ok) >= C
        assert answer(q, damaged).state == "degraded"
        assert d.diag_code in answer(q, damaged).causes
        assert answer(q, damaged) is NOT a confident empty result
```

`DAMAGES`, each mapping to a code from D2's closed `Diag` registry so the assertion has a machine
target and not a prose one:

| damage | injector | expected code |
|---|---|---|
| re-encrypt the source PDF | fixture generator | `OW_ENCRYPTED` |
| strip the text layer, pages 12–40 | fixture generator | `OW_NEEDS_OCR` (which names the pages) |
| fault-inject the table stage | `_chaos {failure_rate, exception_type, latency_ms}` (mine-runtime §7.8.3 — the middleware ships it) | `OW_TIMEOUT` |
| `[budget.per_unit] micros = 1` | config | `OW_TRUNCATED_BY_BUDGET` |
| delete `word/document.xml` | fixture generator | `OW_MISSING_PART` |
| deny the capability probe | config | `OW_DRIVER_UNAVAILABLE` |
| swap in a driver declaring `origin_span: none` | config | `OW_ORIGIN_SPAN_DOWNGRADE` |
| bump `model_id` without re-embedding | config | embedding-model change ⇒ `degraded` |

This is a **causal** evaluation, not a correlational one: the counterfactual is the same query on the
undamaged corpus, so a system that always says `degraded` fails the first assertion and a system that
never does fails the second. It needs no model to check the *state*, so it is deterministic, free,
and runs on every PR (T3). That economic property is the point — the honesty guarantee is cheap
enough to gate on, while the accuracy suites are nightly.

### 1.13 Making a CONFIDENCE tag mean something

Six confidence-shaped things exist across the settled rulings, and they need six different
validations. Writing that table down is most of the work.

| signal | what it claims | ground-truth predicate | corpus needed? |
|---|---|---|---|
| `block.quote = VERBATIM` (D2) | these bytes are the source's bytes | `normalize_k(part_bytes[os_a:os_a+os_b]) == block.text` | **no — self-verifying** |
| `block.trust ∈ {AMBIGUOUS,INFERRED,EXTRACTED}` (D2) | how much to trust this block | normalized text matches the reference block at `fuzz.ratio ≥ 0.98` **and** `kind` agrees | yes |
| `block.score` + `score_kind` (D2) | a scalar on a *named* scale | whatever that scale claims; a `score_kind` with no registered predicate is refused at registration | yes |
| `page.{parse,layout,table,ocr}_score` (D2) | per-page quality | that page's `text_f1` / `table_rel_acc` falls in the grade's band | yes |
| `garble.score` (D4) | P(the cheap driver got this page wrong) | `agree.decode_vs_page` — the escalated page's cheap-vs-expensive normalized edit distance | **no — free, self-labelling** |
| `Capabilities.achieved` (D2/D3) | what the driver actually delivered | conform `capability`, asserted in **both** directions (D3-12) | no |

The first and fifth rows are the design's best property and I lead with them: **the two most
load-bearing confidence signals need no labelled corpus.** `verify_quote` runs on the user's own
documents; `agree.decode_vs_page` is free on every escalation and, at D4's cited 18.8% escalation
rate, yields roughly 188,000 labelled points per million pages against ~5,000 from a 0.5% audit —
landing precisely on the population where the cheap driver is suspect. Everything else needs the
corpus.

**The calibration record and its three gates.** Every surfaced signal has rows in `eval_calibration`
keyed `(eval_set_id, signal_key, slice_key, bucket)` with `n`, `n_correct`, `p_hat`, and Wilson
95% bounds. Then:

- **Q-G18 monotone** (ordinal tags: `trust`, `quote`, docling-shaped grades): `p_hat` strictly
  increases with bucket **and adjacent Wilson intervals do not overlap**. This is the gate that turns
  "we have a confidence tag" into "the tag separates". An ordinal tag whose EXTRACTED and INFERRED
  buckets have overlapping intervals is not a signal; it is three words.
- **Q-G19 sharp** (probabilities: `garble.score`, `score` with a probability `score_kind`):
  **ECE ≤ 0.05, Brier ≤ 0.08** — D4's numbers, reused verbatim rather than invented — over 10
  equal-mass bins, each bin `n ≥ 30` or reported UNKNOWN.
- **Q-G20 fresh**: within `[calibration] max_age_days` (D4: 30). Stale produces
  `Degradation(kind="calibration_stale")`, which is already a member of D4's `Degradation.kind` enum,
  so no new vocabulary is created.

**The surfacing rule (Q8), which is the whole point.** Every confidence value crossing the serve
boundary is wrapped:

```python
@dataclass(frozen=True, slots=True)
class Calibrated:
    signal:   str                                   # 'block.trust' | 'garble.score' | ...
    value:    float | str                           # raw score, or the ordinal MEMBER NAME
    state:    Literal["calibrated","uncalibrated","stale","unknown_slice"]
    p_correct: float | None                         # empirical accuracy of THIS bucket in THIS slice
    ci95:      tuple[float, float] | None           # Wilson
    n:         int
    eval_set_id: str
    measured_at_ns: int
```

`state != "calibrated"` ⇒ the surface may print the ordinal **name** and must print
`(uncalibrated)`, and may **never** print a percentage, a numeral, a bar, a colour ramp or a grade. A
renderer test asserts that for `state="uncalibrated"` the rendered output contains no `%`, no digit
adjacent to the signal, and no `QualityGrade` member. That is the mechanical version of docling's
stated "publish grades, keep scores internal" discipline — inverted, because docling's own grade is
the thing that turned out to be decoration. When it *is* calibrated, the surface reads:

```
EXTRACTED  (this driver, slice pdf/born_digital/en: 96.2% of EXTRACTED blocks matched
            ground truth, n=1,842, 95% CI [95.3, 97.0], eval-set 2026.09, measured 12 d ago)
```

That sentence is the difference between a trust signal and a badge.

### 1.14 The public scoreboard as an adoption asset

`SCOREBOARD.md` is **generated** from `scoreboard.json` and byte-diff gated (`Q-G22`), the same
mechanism as D1's G6 and graphify's `tools/skillgen --check/--bless`. Hand-maintaining it is how it
becomes a lie; graphify's own bug #397 is a hand-written doc block describing calls the client no
longer offers, silent because the names stayed dispatchable.

The template is `graphify/BENCHMARKS.md`, which is the best benchmark document in the collection, plus
olmOCR-Bench's statistics and D3's `measured_on` discipline. Required sections:

1. **Fairness rules.** One model for every LLM role; one shared local embedder; identical token
   budgets; `--max-spend` respected; a per-run spend ledger. Verbatim from graphify's "Fairness rules".
2. **Judge validation.** Blind second judge on a sampled set, agreement % and **Cohen's κ** (graphify
   publishes 90.6% / κ = 0.81 and notes that *"most published memory benchmarks disclose no judge
   validation at all"*). A suite whose judge κ < 0.70 is invalid and is not published. Every verdict
   cites a verbatim quote from the answer, so grades are auditable rather than one opaque score.
3. **Every row:** `value ± ci95 (n)`, `method ∈ {closed_form, exact, resampled}`, `measured_on`
   (D3's five-tuple plus hardware plus `corpus_digest`), `witness ∈ {ci, self, third_party}`.
4. **Head-to-head p-values** from the paired test, with an explicit *"not significant"* verdict
   rather than an ordering. olmOCR-Bench does pairwise permutation tests; almost nobody reports the
   negative result, which is the honest half.
5. **Confounders — mandatory, non-empty.** graphify's `*` footnote is the model: *"Retrieval-recall is
   embedder-confounded: supermemory's self-host locks in its own 768-d English-only embedder rather
   than the shared BGE-m3."* A scoreboard with no stated confounders fails review.
6. **Cost in the same table as accuracy** (graphify's $1.40 vs $15.67), sourced from `route_spend`
   (D4), because accuracy-per-dollar is the axis where a deterministic-first design wins.
7. **"What we did not measure"** — graphrag's `RAI_TRANSPARENCY.md` as an artefact type, which is the
   document that stops an unstated posture from shipping.
8. **The vetoed-competitor disclosure.** marker, surya and lift cannot be run by us at any revenue
   level (byte-identical `MODEL_LICENSE`, md5 `e1f69b64dee2f1641a9b1ab12adf24d6`, Attachment A clause
   2(c) competitor bar with no threshold; clause 8 licenses the Output). So their numbers are
   **quoted, never reproduced**, and the row states that `grep -rn "revision=" marker/ surya/ lift/`
   returns zero hits, so the benchmarked checkpoint is unidentifiable, and that marker's headline
   requires `--use_llm`, which egresses page images to Gemini by default. Publishing *that* is itself
   an adoption asset: it is the analysis a prospective adopter has to do anyway and cannot easily do.
9. **Reproduction commands** with the corpus digest and `--max-spend`.

### 1.15 Cost, and the build order

| phase | contents | weeks |
|---|---|---|
| **Q1** | T0–T2. `.owsum`, `ow doc diff` on `rebind`, `FIXTURES.toml` + Q-G21, synthetic fixture generators, `omniweave_conform.stats` (closed forms), Hypothesis strategies + the six round-trip properties. **Deliverable a user runs:** `ow doc diff a.owdoc b.owdoc`. | 3 |
| **Q2** | T3: damage injectors, the paired-damage suite, `eval_*` DDL, `ow bench` CLI. **Deliverable:** a per-PR gate proving the absence contract. | 3 |
| **Q3** | `omniweave-golden 2026.09` v1 (~600 documents, ~8,000 assertions), the review app (olmocr `review_app.py` shape with `checked` in the record), both evaluators, cross-tool adapters. | 4 |
| **Q4** | Calibration tables + Q-G18/19/20, `Calibrated` at the serve boundary, perf budgets + calibrator + Q-G17, scoreboard generator + Q-G22. | 3 |
| **Q5** | LOCOMO / LongMemEval-S adapters, quarterly portability run, incremental-vs-full (Q17), T6 soak/fuzz. | 2 |

**≈15 engineer-weeks for one senior engineer**, plus a standing **~0.4 FTE** (corpus curation,
assertion review, weekly flaky-guard triage, quarterly calibration refresh), plus **~2 person-weeks
of human labelling per 1,000 assertions** — which is the number that actually bounds corpus growth
and is why the corpus is 600 documents and not 6,000.

**Runtime and operational cost, stated honestly.** `owcheck` on read is D2's ~240 ns/block (~2.4 s at
10M). T3 adds ~60 s per PR. T0–T3 total ≈ 7.5 min per PR against D1's existing ~2 min of gates.
Nightly T5 ≈ 90 min on one GPU box. Tier-B corpus ≈ 4 GB on disk, ≈ 1.2 GB compressed. `eval_*` rows
≈ 300 B per measured unit, so a nightly over 20,000 units is ~6 MB/night, ~2 GB/year, retained 400
days to match D4's `route_decision` retention. **Zero new third-party runtime dependencies**:
`blake2b`, `statistics`, `sqlite3` and `tomllib` are stdlib, the Levenshtein is a 40-line DP, and no
numpy enters any gate path.

---

## 2. Concrete shape

```
packages/omniweave-conform/src/omniweave_conform/
├── suites/                       # D3's eleven, unchanged
│   ├── card/ purity/ contract/ capability/ idempotence/ determinism/
│   ├── limits/ sandbox/ cost/ licence/ fuzz/
│   └── quality/                  # SUITE TWELVE — non-mandatory, `omniweave conform --bench`
│       ├── metrics.py            text_f1 · structure_f1 · order_acc · table_rel_acc
│       │                         hallucination_rate · field_acc · doc_acc · furniture_f1
│       ├── evaluate_owdoc.py     resolves by `addr`; Grid.up/down/left/right/top_heading
│       ├── evaluate_text.py      olmOCR-Bench evaluator; normalize_text VERBATIM
│       ├── align.py              banded Levenshtein · deterministic greedy block matcher
│       └── stability.py          k=5 runs -> [[quality.stability]]
├── stats/                        # NO RNG ON THE DEFAULT PATH (Q3). semgrep-enforced.
│   ├── interval.py               macro mean, stratified closed-form CI, Wilson
│   ├── compare.py                paired permutation asymptotic; exact enum for N<=20
│   ├── calibrate.py              ECE (10 equal-mass bins) · Brier · reliability rows
│   └── resample.py               ONLY fallback; seed = blake2b(eval_set_id|cand|metric|version)
├── corpus/                       # D3 reserved this path. Tier A only.
│   ├── formats/ adversarial/ LICENCES.md
│   └── FIXTURES.toml
├── damage/                       # T3 injectors, one per Diag code
│   ├── encrypt.py strip_text_layer.py chaos.py budget.py drop_part.py
│   └── deny_probe.py downgrade_origin_span.py rotate_embedder.py
├── golden/                       # .owsum writer/comparer; ow doc diff delegates to rebind()
│   ├── owsum.py                  one deterministic line per page
│   └── bless.py                  OMNIWEAVE_BLESS; test_bless_flag_is_off()
├── retrieval/
│   ├── suite.py                  queries -> gold `cite` sets
│   ├── absence.py                the paired-damage harness
│   └── adapters/{locomo,longmemeval,dense_rag,bm25,hybrid_rrf}.py
├── crosstool/adapters/{docling,markitdown,pandoc,unstructured,libreoffice}.py
├── report/
│   ├── scoreboard.py             scoreboard.json -> SCOREBOARD.md ; --check / --bless
│   └── schema/scoreboard-v1.json
└── perf/
    ├── calibrator.py             blake2b 64 MiB + 2M int loop + 200k SQLite rows
    └── budgets.py                ratio for time · absolute for RSS and WAL · UNSTABLE

tools/
├── perf-budgets.toml
├── quality-gates.toml            budgets (absolute floors) and guards (deltas) per metric per slice
└── gate_{perf,calibration,fixtures,scoreboard}.py     # Q-G17, Q-G18..20, Q-G21, Q-G22

fixtures/                         # TIER A — in repo, <= 20 MB, MOSTLY GENERATED
├── FIXTURES.toml                 one row per non-generated byte
├── gen/                          committed generators (3 KB each, not 90 MB of binary)
│   ├── gen_5000p_pdf.py  gen_4m_cell_xlsx.py  gen_ragged_table_docx.py
│   ├── gen_spanned_merged_pptx.py  gen_zip_bomb.py  gen_encrypted_pdf.py
│   └── gen_40byte_docx.py
├── perf/calibrator.py
└── hypothesis/                   minimized counterexamples, append-only

$OMNIWEAVE_HOME/golden/2026.09-<sha256>/     # TIER B — a DATA ARTIFACT, NOT A 12TH DISTRIBUTION
├── manifest.toml                 corpus_digest · per-document licence rows · slice definitions
├── docs/…                        the documents
├── assertions/*.jsonl            olmOCR-Bench record shape + `checked` + `evaluable_in`
└── retrieval/queries.jsonl       query -> gold `cite` set

<private mount>/omniweave-golden-private/    # TIER C — NEVER bytes in a repo
└── (documents fetched locally; only sha256 + fetch recipe + assertions are committed)
```

```sql
-- ══ eval_*: the evaluation data model. Same file, same discipline, as .owstore. ═════
-- Pragma ORDER is load-bearing: busy_timeout FIRST (codegraph #238).
PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;

CREATE TABLE eval_corpus (
  corpus_id     TEXT NOT NULL,          -- 'omniweave-golden'
  version       TEXT NOT NULL,          -- '2026.09'   (D3's card already fixes both strings)
  corpus_digest TEXT NOT NULL,          -- sha256 over sorted (relpath, sha256) pairs, NUL-framed
  tier          TEXT NOT NULL CHECK (tier IN ('A','B','C')),
  n_docs INTEGER NOT NULL, n_assertions INTEGER NOT NULL, n_checked INTEGER NOT NULL,
  assertions_redistributable INTEGER NOT NULL,
  document_redistributable   INTEGER NOT NULL,
  PRIMARY KEY (corpus_id, version)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_run (
  eval_run_id     TEXT PRIMARY KEY,     -- 'ev_' || sha256_canonical(identity)[:24]
  corpus_id TEXT NOT NULL, corpus_version TEXT NOT NULL, corpus_digest TEXT NOT NULL,
  candidate       TEXT NOT NULL,        -- a driver id, a pipeline profile, or a competitor adapter
  producer_id     INTEGER NOT NULL REFERENCES producer(producer_id),   -- D2's type, SHARED
  policy_digest   TEXT NOT NULL,        -- D4's
  pricebook_digest TEXT NOT NULL,       -- D4's
  harness_version TEXT NOT NULL,
  witness         TEXT NOT NULL CHECK (witness IN ('ci','self','third_party')),
  hardware        TEXT NOT NULL,        -- 'x86_64-linux 8c/16GiB/A10G-24GiB'
  unpinned        INTEGER NOT NULL DEFAULT 0,   -- 1 when measured_on has no exact model_rev
  started_ns INTEGER NOT NULL, ended_ns INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','partial','unknown'))
) STRICT;

-- One row per (assertion, run). This is the grain everything else aggregates from.
CREATE TABLE eval_verdict (
  eval_run_id  TEXT NOT NULL REFERENCES eval_run(eval_run_id) ON DELETE CASCADE,
  assertion_id TEXT NOT NULL,
  evaluator    TEXT NOT NULL CHECK (evaluator IN ('owdoc','text')),
  passed       INTEGER NOT NULL,
  score        REAL,                    -- for graded assertions; NULL for pass/fail
  explanation  TEXT NOT NULL DEFAULT '',-- olmOCR-Bench prints why; so do we
  unit_uri TEXT NOT NULL, unit_part TEXT NOT NULL DEFAULT '', slice_key TEXT NOT NULL,
  PRIMARY KEY (eval_run_id, assertion_id, evaluator)
) STRICT, WITHOUT ROWID;
CREATE INDEX eval_verdict_slice ON eval_verdict(eval_run_id, slice_key);

CREATE TABLE eval_metric (
  eval_run_id TEXT NOT NULL REFERENCES eval_run(eval_run_id) ON DELETE CASCADE,
  metric TEXT NOT NULL, slice_key TEXT NOT NULL DEFAULT '__macro__',
  value REAL, n INTEGER NOT NULL,
  ci_lo REAL, ci_hi REAL,
  method TEXT NOT NULL CHECK (method IN ('closed_form','exact','resampled','unknown')),
  state  TEXT NOT NULL CHECK (state  IN ('ok','unknown')),   -- 'unknown' when n < min_slice_n
  PRIMARY KEY (eval_run_id, metric, slice_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_calibration (
  eval_set_id TEXT NOT NULL, signal_key TEXT NOT NULL, slice_key TEXT NOT NULL,
  bucket INTEGER NOT NULL, bucket_lo REAL NOT NULL, bucket_hi REAL NOT NULL,
  n INTEGER NOT NULL, n_correct INTEGER NOT NULL,
  p_hat REAL NOT NULL, wilson_lo REAL NOT NULL, wilson_hi REAL NOT NULL,
  ece REAL, brier REAL,                       -- NULL for ordinal signals
  measured_at_ns INTEGER NOT NULL, harness_version TEXT NOT NULL,
  PRIMARY KEY (eval_set_id, signal_key, slice_key, bucket)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_perf (
  eval_run_id TEXT NOT NULL REFERENCES eval_run(eval_run_id) ON DELETE CASCADE,
  budget_id TEXT NOT NULL,                    -- matches tools/perf-budgets.toml
  calib_before_ns INTEGER NOT NULL, calib_after_ns INTEGER NOT NULL,
  work_ns INTEGER NOT NULL,
  time_ratio REAL NOT NULL,                   -- work_ns / mean(calib_before, calib_after)
  peak_rss_bytes INTEGER NOT NULL, wal_peak_bytes INTEGER NOT NULL DEFAULT 0,
  verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','unstable')),
  PRIMARY KEY (eval_run_id, budget_id)
) STRICT, WITHOUT ROWID;

-- The public view. UNKNOWN is the zero value, exactly as D4's route_scoreboard.
-- Self-witnessed and unpinned runs are VISIBLE but never ranked (Q10).
CREATE VIEW eval_scoreboard AS
SELECT m.metric, m.slice_key, r.candidate, r.corpus_version, r.witness, r.unpinned,
       m.value, m.ci_lo, m.ci_hi, m.n, m.method,
       CASE WHEN m.state = 'unknown'                     THEN 'UNKNOWN'
            WHEN r.witness <> 'ci' OR r.unpinned = 1     THEN 'UNRANKED'
            ELSE 'RANKED' END AS standing
FROM eval_metric m JOIN eval_run r USING (eval_run_id)
WHERE r.status <> 'unknown';
```

```toml
# ── $OMNIWEAVE_HOME/golden/2026.09-<sha>/manifest.toml  (Tier B) ────────────────
corpus_id      = "omniweave-golden"
version        = "2026.09"
corpus_digest  = "sha256:c0de…"          # over sorted (relpath, sha256), NUL-framed
document_redistributable   = true
assertions_redistributable = true
min_slice_n    = 30                      # == D4's min_audit_n. Below it: UNKNOWN, and NAMED.

[[slice]]
key      = "pdf/born_digital/en"
by       = ["unit.format","unit.producer_family","decode.has_text_layer","corpus.lang"]
n_docs   = 84 ; n_assertions = 1_240

[[doc]]
id           = "arxiv-2305.03393v1"
path         = "docs/pdf/arxiv-2305-03393v1.pdf"
sha256       = "sha256:1a2b…"
bytes        = 3_145_728
spdx         = "CC-BY-4.0"               # MUST be in the fixture allowlist (Q-G21)
licence_url  = "https://arxiv.org/abs/2305.03393"
source_url   = "https://arxiv.org/pdf/2305.03393v1"
retrieved_at = "2026-08-14T00:00:00Z"
attribution  = "Lysak et al., Optimized Table Tokenization for Table Structure Recognition"
redistribute = true                      # `false` is UNREPRESENTABLE in Tier B
slices       = ["pdf","born_digital","table_heavy","en"]
quoted_chars_in_assertions = 1_180       # capped at min(2000, 10% of extracted text)  (Q-G21)

# Fixture SPDX allowlist, enforced by Q-G21:
#   CC0-1.0 · CC-BY-4.0 · CC-BY-SA-4.0 · Apache-2.0 · MIT · PDDL-1.0 · LicenseRef-US-Gov-Work
# Everything else is Tier C: sha256 + fetch recipe + assertions only.
```

```jsonc
// ── an assertion record. olmOCR-Bench's shape, plus four omniweave fields. ──────
{"id":"arxiv-2305.03393v1/p9/t04", "doc":"arxiv-2305.03393v1", "page":9,
 "type":"table",                       // baseline|present|absent|order|table|math|format|footnote
 "max_diffs":2,
 "checked":"verified",                 // verified|rejected|unchecked  — unchecked never scores
 "cell":"Cascade R-CNN", "up":"Model", "left_heading":"Backbone",

 // ── omniweave additions ──────────────────────────────────────────────────────
 "evaluable_in":"both",                // owdoc | text | both  — the cross-tool subset is `both`
 "addr":"p9/12/r3c1",                  // D2's type-free address; owdoc evaluator resolves this
 "derived_from_sha256":"sha256:1a2b…", // the licence chain for the assertion itself
 "not_a_truth_measure":false}          // a schema field, never a README sentence
```

```toml
# ── tools/quality-gates.toml — BUDGET (absolute floor) vs GUARD (delta). ────────
# Two failures, two owners. A budget breach is a product failure; a guard breach is a PR failure.
[defaults]
guard_p_max = 0.01                       # paired permutation; below this AND >= MDE to fire
mde_rule    = "2 * se(headline)"         # recomputed on every corpus release, never guessed
baseline    = "release"                  # NOT "previous commit" — see Q20
ratchet_ceiling_releases = 2             # also checked vs N-2 at 2x tolerance

[[gate]]  metric="span_exact_rate"  slice="*"                    budget=1.000  kind="hard"
# ^ Q7. Not a score. D2 lets serve claim byte-exactness on `verbatim`; anything under 1.0 is a lie.

[[gate]]  metric="hallucination_rate" slice="*"                  budget_max=0.02  guard=0.005
[[gate]]  metric="structure_f1"     slice="office/*"             budget=0.90   guard=0.010
[[gate]]  metric="structure_f1"     slice="pdf/born_digital/*"   budget=0.85   guard=0.010
[[gate]]  metric="table_rel_acc"    slice="*/has_merges=1"       budget=0.70   guard=0.020
[[gate]]  metric="order_acc"        slice="pdf/born_digital/*"   budget=0.75   guard=0.015
#          ^ floor sourced: pdftext char-stream order scores 75% on olmOCR-bench order tests
#            (marker/builders/line.py:80-82). We must not ship below the free baseline.
[[gate]]  metric="citation_soundness" slice="*"                  budget=0.995  guard=0.002
[[gate]]  metric="absence_accuracy"   slice="*"                  budget=1.000  kind="hard"
#          ^ deterministic and LLM-free, so 1.000 is achievable and anything less is a defect.
[[gate]]  metric="doc_acc"          slice="fields/*"             budget=0.20   guard=0.020
#          ^ 0.20, deliberately. lift's own adversarial benchmark: 90.2% per field, 20.9% full
#            document. A budget of 0.90 here would be a promise the field cannot keep.
```

```toml
# ── tools/perf-budgets.toml — memory ABSOLUTE, time as a CALIBRATOR RATIO ───────
[calibrator]
instability_pct   = 15                   # |before-after|/mean > 15% => UNSTABLE, not PASS/FAIL
unstable_streak_max = 3                  # 3 consecutive UNSTABLE on one job is a FAILURE

[[budget]]
id = "parse.pdf.pdfium/gen-5000p.pdf"
peak_rss_bytes = 1_610_612_736           # 1.5 GiB HARD — D1's anydoc-marshal cliff lives here
wal_peak_bytes = 2_147_483_648           # codegraph observed 5.9 GB WAL on a 340 MB DB
time_ratio_p50 = 41.0 ; time_ratio_p95 = 68.0 ; tolerance = 0.10

[[budget]]
id = "parse.office.anydoc/merged-4m-cell.xlsx"
peak_rss_bytes = 4_294_967_296           # the pathological case; a breach is ResourceLimit, not OOM
time_ratio_p50 = 12.0 ; tolerance = 0.15

[[budget]]                               # D1's G10 cold-start rows, re-anchored to a release
id = "import omniweave_core" ; wall_ms_abs = 80 ; tolerance = 0.25
[[budget]]
id = "ow query (warm store)"  ; wall_ms_abs = 250 ; tolerance = 0.25
```

```python
# ── omniweave_conform/stats/interval.py — CLOSED FORM. NO RNG. (Q3) ────────────
def macro_ci(slices: Sequence[SliceStats], *, z: float = 1.96
             ) -> tuple[float, float, float, str]:
    """Stratified macro-mean and its 95% interval. olmOCR-Bench's structure (mean of
    per-category means, resampled WITHIN category); its arithmetic done in closed form.

        headline = (1/S) * sum(m_s)
        se       = sqrt( (1/S^2) * sum(sd_s^2 / n_s) )

    Valid by CLT because every contributing slice has n_s >= min_slice_n (30). A slice
    below the floor is EXCLUDED and NAMED; it never silently widens or narrows the interval.
    Returns (headline, lo, hi, method) with method == 'closed_form'.
    Falls back to stats.resample.bootstrap (seeded) only for a degenerate slice."""

def wilson(k: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Used for every calibration bucket, because Wald is wrong
    at p near 0 or 1 and a calibration bucket at p=0.99 is exactly where we look."""

# ── omniweave_conform/stats/compare.py ─────────────────────────────────────────
def paired_p(deltas: Sequence[float]) -> tuple[float, str]:
    """Two-sided paired permutation test. The exact test flips the sign of each delta;
    its asymptotic, for N = count(d != 0) >= 30, is closed:

        p = 2 * (1 - Phi( |sum(d)| / sqrt(sum(d*d)) ))

    N <= 20 -> exact enumeration over 2^N sign vectors.  20 < N < 30 -> seeded resampling,
    seed = blake2b(eval_set_id | candidate | metric | harness_version).
    Returns (p, method). olmocr/bench/utils.py:120,172 shuffle with an UNSEEDED np.random,
    so its published p-values do not reproduce; this one is a pure function of its input."""

# ── omniweave_conform/golden/owsum.py ──────────────────────────────────────────
def owsum(doc: "Doc") -> Iterator[str]:
    """One deterministic line per page: block count, kind/layer/trust/quote histograms,
    the page's merkle content_digest and layout_digest, and the Diag code multiset.
    ~80 bytes/page, so a 5,000-page fixture is a 400 KB reviewable golden."""

def diff_owdoc(old: Path, new: Path, *, threshold: float = 1.0) -> "RebindReport":
    """THE GOLDEN DIFFER IS `rebind`.  D2 already specifies a three-rule matcher
    (equal content_digest under the same parent CARRIES; equal addr+kind with a changed
    digest CARRIES and bumps revision; else new id + a block_history row) returning
    RebindReport{carried, revised, created, retired, match_rate_by_page, quarantined}.
    That IS a snapshot diff. One implementation, two consumers, nothing to drift."""

# ── omniweave_conform/retrieval/absence.py ─────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Damage:
    name: str
    diag_code: str                    # from D2's CLOSED registry — a machine target, not prose
    apply: Callable[[Path, tuple[int, ...]], Path]      # returns a damaged corpus root

def run_absence_suite(queries, damages, answer) -> "AbsenceReport":
    """For each (query, gold cites) x damage:
         answer(q, pristine).state == 'ok'        and cites >= gold
         answer(q, damaged ).state == 'degraded'  and damage.diag_code in causes
         answer(q, damaged ) is NOT a confident empty result
       Deterministic. No model needed for the STATE assertion, so it is free and gates PRs.
       This is the only causal evaluation of the absence contract that exists anywhere."""
```

```
── CLI ─────────────────────────────────────────────────────────────────────────
ow golden install [--version 2026.09]     fetch + verify digest into $OMNIWEAVE_HOME/golden/
ow golden verify                          re-hash every file against manifest.toml
ow golden licence-report                  SPDX rollup + attribution block for redistribution

ow bench run --candidate <driver|profile> [--slice K=V] [--require-slices a,b,c]
ow bench compare <run-a> <run-b>          paired p, effect, MDE, per-slice deltas
ow bench calibrate --signal block.trust   writes eval_calibration; prints the reliability table
ow bench scoreboard [--check | --bless]   scoreboard.json -> SCOREBOARD.md, byte-diff gated
ow bench perf [--bless]                   calibrator ratios + absolute RSS/WAL; UNSTABLE is real

ow doc digest <doc>                       the .owsum projection
ow doc diff <a.owdoc> <b.owdoc> [--full]  the RebindReport as a review artefact
ow eval absence [--damage encrypted,…]    the T3 suite standalone

ow release check                          refuses on ANY UNKNOWN tier, slice, or calibration
```

```yaml
# ── .github/workflows/ci.yml — the tiers, added to D1's existing jobs ──────────
gates:        {runs-on: ubuntu, py: "3.11"}          # D1 G1..G16 + Q-G17..Q-G22   ~3 min
test:         {os: [ubuntu,macos,windows], py: ["3.11","3.12","3.13"]}   # T1+T2   ~4 min
absence:      {runs-on: ubuntu, py: "3.11"}          # T3 — deterministic, zero LLM  ~1 min
conform:      {runs-on: ubuntu, if: "changed(packages/omniweave-*/) "}   # T4, from a TRUSTED TAG
bench:        {schedule: nightly, runs-on: gpu-a10g} # T5 ~90 min; writes eval_* ; UNKNOWN != skip
soak:         {schedule: weekly}                     # T6 fuzz + 5000p RSS + 24h store soak
# HYPOTHESIS_PROFILE: ci (500, derandomize=True) on PRs; nightly (5000, derandomize=False) at night.
# OMNIWEAVE_BLESS is NEVER set in CI; test_bless_flag_is_off() fails the session if it is.
```

---

## 3. Rationale

**Why a schema rather than a test suite.** The three questions that decide whether omniweave is
trustworthy in year three — *when did this regress*, *is this difference real*, *does the confidence
tag mean anything* — are all historical, and none can be answered retroactively from console output.
Every repo in the collection made the same choice and paid: docling computes four page scores and
consumes none of them; marker computes a table reconstruction score, gates on it, and discards it
(D2 fixes this as `table_meta.recon_score`); graphrag's cost guidance is one qualitative paragraph.
The fix costs six tables and is the cheapest structural insurance in this design.

**Why the golden differ is `rebind`.** This is the decision I am most confident about. Snapshot
testing on a large noisy parser is exactly the problem "which blocks are the same block after a
re-parse" — and D2 already had to solve that problem for a different reason, with a specified
three-rule matcher, a per-page match rate and a quarantine threshold. Building a second differ would
put two implementations behind the same semantics, which is the failure D1 spent its whole ruling
avoiding ("there is one canonical-JSON digester, one place that opens SQLite, one subprocess seam").
Reusing `rebind` also means the golden test's tolerance and the model layer's quarantine threshold
are the same number, tuned once, and a bless commit produces a `RebindReport` a reviewer already
knows how to read.

**Why calibration is an admission gate and not a report.** A confidence tag that has never been
measured against ground truth is worse than no tag, because a downstream agent will condition on it.
docling's four-component grade is the proof: the type is right, the enum is right, the API discipline
("publish grades, keep scores internal") is right, and one of the four components is structurally
NaN, so the published grade is wrong in a way no consumer can detect. Q-G18's non-overlapping-Wilson
requirement is deliberately strict: an ordinal tag whose adjacent buckets do not separate is not
carrying information, and the correct product response is to stop rendering it rather than to
apologize for it in documentation.

**Why the absence suite is the highest-leverage new thing here.** The graph digest identifies the
absence contract as *"a framework invariant, not a tool feature"* with *"no counterpart anywhere"*,
and lists six omniweave hazards that are *"currently a silent zero in every RAG system."* Everyone
who reads that agrees. Nobody has proposed a way to *test* it. Paired damage injection is that way,
and it turns out to be the cheapest suite in the pyramid: the state assertion is deterministic and
needs no model, so it costs ~60 s per PR. A guarantee that is cheap to check is a guarantee that
survives; one that costs an hour of GPU is a guarantee that gets moved to nightly and then to
quarterly and then removed.

**Why closed-form statistics.** The purist reason is that a report which is a pure function of its
score table cannot drift, cannot be perturbed by an unrelated import touching a global RNG, and needs
no seed provenance in the manifest. The practical reason is that D1's core is stdlib-only, a stratified
bootstrap of 10,000 × 15,000 draws in CPython is ~100 s, and I refuse to add numpy to a gate path to
buy a number I can compute exactly. The evidentiary reason is that olmOCR-Bench — the best-designed
benchmark in the collection — ships unseeded `np.random.choice`/`shuffle` in
`olmocr/bench/utils.py:33,55,120,172`, so its own headline CIs and p-values do not reproduce, and
nobody noticed because nobody re-ran them.

**Why time budgets are ratios and memory budgets are absolute.** Because those are different physical
quantities with different noise structures, and treating them the same is why performance gates get
disabled. The failures in the evidence are memory failures — 5.9 GB WAL on a 340 MB DB, 22 GB and
exit 137, D1's own eager-marshal cliff — and RSS is measurable to ±2% on any runner. Wall time on a
shared runner is not, and pretending otherwise produces a gate that is red on Tuesdays.

**Why the corpus is a data artifact and not a distribution.** D1 fixes eleven distributions and says
amending the list amends D1. A wheel is also the wrong vehicle for 4 GB of documents with per-file
licence rows and a Tier-C sibling that must never be packaged. `$OMNIWEAVE_HOME/golden/<version>-<sha>/`
reuses D1's toolchain-install pattern verbatim, including the rule that a digest mismatch never
triggers a fetch.

**Why LOCOMO and LongMemEval-S are demoted to a portability suite.** They are conversational-memory
datasets. graphify's numbers on them differ by 35 recall points for one system, which tells you they
are measuring different things and neither is "does omniweave parse a 10-K". Running them is worth
doing because cross-referenceability with the memory field is a genuine adoption asset and because
graphify's cost column ($1.40 vs $15.67, zero LLM credits to build) is the argument for
deterministic-first extraction stated as a number. Treating them as the primary retrieval metric
would be optimizing the framework for the wrong workload, which is a five-year mistake.

---

## 4. Tradeoffs

- **~15 engineer-weeks plus a standing 0.4 FTE, before a single format is added.** That is real, it
  competes directly with driver work, and the corpus curation never ends. I am paying it because
  every quality claim made without it is unfalsifiable and every one of them will be made anyway.
- **PR CI goes from D1's ~2 min of gates to ~7.5 min of gates plus tests.** The absence suite and the
  golden compare are the additions. I chose to put both on the PR path rather than nightly, because a
  nightly failure is triaged by whoever is unlucky and a PR failure is triaged by the author.
- **A per-file licence row on every fixture is friction on the most casual contribution there is.**
  Adding a repro document now requires provenance. Mitigated by making most fixtures *generated*
  (a generator needs no licence), but a contributor with a real broken PDF will hit a wall.
- **Closed-form intervals assume n ≥ 30 per slice and approximate normality of the slice mean.** For a
  heavily skewed metric on a small slice this is less accurate than a resampling bootstrap. I take
  the accuracy loss in exchange for determinism, and the fallback path exists and is stamped in the
  report.
- **A greedy block matcher in `structure_f1` is not optimal.** On a document where the candidate
  drops the first block, greedy can cascade a misalignment that Hungarian would avoid. Anchoring on
  exact `content_digest` matches first bounds the damage, but the metric is slightly pessimistic for
  a badly-misaligned candidate — which is the safe direction.
- **Q-G18's non-overlapping-Wilson rule will de-surface real signals early.** With 30 samples a bucket
  at p = 0.90 has a Wilson interval roughly [0.74, 0.97]; adjacent buckets will overlap until the
  corpus grows. So on day one most tags read `(uncalibrated)`. That is the truth, and it is the same
  design choice D4 made when it said an operator's first look at the scoreboard is a wall of UNKNOWN.
- **The scoreboard's honesty makes us look worse than competitors who are not honest.** A row that
  says `76.0% ± 3.1 (n=412, witness=ci)` next to a competitor's bare `94.10` loses the skim. I accept
  this and mitigate it only by explaining the competitor's number in the same table.
- **Adding two required fields to `[[quality.benchmark]]` is a change to a schema D3 owns.** §7.
- **`min_slice_n = 30` × up to 512 slices means the corpus can never cover the full slice lattice.**
  Most slice keys will be UNKNOWN forever. The report will be mostly holes, honestly labelled.

---

## 5. Failure modes

- **The corpus becomes the model.** Six months of tuning against `omniweave-golden 2026.09` overfits
  to 600 documents, and the scoreboard rises while real-world quality does not. Mitigations: a
  held-out slice never used for tuning, rotated at each corpus release; the `agree.decode_vs_page`
  channel (D4) which is measured on *production* traffic and not on the corpus; and the audit lane.
  None of these fully fix it. This is the most likely way this design fails and I do not have a
  complete answer.
- **Assertion rot.** A `verified` assertion that was wrong at authoring time is permanently wrong, and
  it silently caps the metric. olmOCR-Bench's `checked` field plus a review app plus `--output_failed`
  (tests no candidate passes are surfaced as a batch, `olmocr/bench/benchmark.py:421-457`) is the
  mitigation, and it depends on someone actually opening the review app.
- **The input that breaks the golden design: a driver upgrade that re-segments paragraphs.** Every
  `content_digest` changes, `.owsum` diverges on every page, `rebind` reports 400,000 created and
  400,000 retired, and the bless commit is unreviewable. D2 already flags this as a `rebind`
  quarantine that "costs a human a decision"; here it costs a human a decision they cannot actually
  make. The partial answer is that `ow doc diff --full` groups retirements by `(page, kind)` and
  prints the top 20 patterns, so a reviewer sees "every paragraph on every page was re-split" rather
  than 800,000 lines. It is still a bad day.
- **`UNSTABLE` becomes the normal verdict.** If the CI fleet is genuinely noisy, the calibrator will
  say so constantly, the three-strike rule will fail the build, and the social pressure will be to
  raise `instability_pct` to 40 and thereby delete the gate. The honest outcome is a dedicated
  perf runner; the likely outcome is a raised threshold.
- **Calibration slices are too fine and every bucket is UNKNOWN.** `slice_key` from D4's four-field
  product can produce hundreds of slices; each one needs n ≥ 30 per confidence bucket, so the true
  requirement is n ≥ 90–150 per slice. With a 600-document corpus that is satisfiable for maybe eight
  slices. Confidence will be surfaced on a minority of documents for a long time.
- **The `not_a_truth_measure` flag is respected by our report generator and by nobody else.** A
  downstream consumer reading `scoreboard.json` can plot the trigram-containment column as accuracy.
  A schema field is stronger than a README sentence and weaker than not emitting the number.
- **A Tier-C slice quietly stops running.** The documents live on someone's mount; the mount goes
  away; the slice reports UNKNOWN; `ow release check` fails; someone adds it to an exclusion list
  "temporarily". The exclusion list is the vulnerability, and the only defence is that entries carry
  a required justification and a review date and a row past its date fails the gate — D1's
  `allowed-undeclared.toml` mechanism, with D1's own honest note that past ~15 rows the gate has
  failed socially while passing mechanically.
- **The paired-damage suite tests the *state machine*, not the *answer*.** It proves the system says
  `degraded` and names `OW_NEEDS_OCR`. It does not prove the prose the agent then writes is sensible.
  A system could pass `absence_accuracy` at 1.000 and still hallucinate confidently in the body text.
- **`corpus_digest` binding is defeated by a corpus the attacker also publishes.** If a third party
  ships their own `omniweave-golden`-shaped corpus with a matching id and a different digest, the
  digest check catches it — but a *witness* field is only as good as the CI that sets it, and a
  self-hosted CI can set `witness = "ci"`. The scoreboard therefore only accepts `witness = "ci"`
  rows produced by omniweave's own workflow identity, which means third-party drivers can never be
  ranked on our board without us running them. That is a governance cost, not a technical fix.
- **Six tables of evaluation data with a 400-day retention is ~2 GB/year** in the same SQLite file as
  the corpus, contending for the same WAL. If a nightly bench run and a bulk index collide, the WAL
  valve fires. The eval tables should probably live in a separate `.owstore`; I have not settled it
  and D5 owns the file-layout call.

---

## 6. Why I reject the alternatives

- **"Run olmOCR-Bench and publish the number."** Its licence-clean parts are excellent and I adopt
  them wholesale (test taxonomy, `TableTest` relations, `normalize_text`, `max_diffs`, `checked`,
  stratified macro-averaging, `--output_failed`). But as *the* yardstick it fails three ways: its
  statistics do not reproduce (unseeded RNG, §1.9); it evaluates a markdown string, so every property
  that makes owdoc worth having — per-cell geometry, `quote` tiers, `layer` separation, `OriginSpan`
  — is invisible to it; and the field's published numbers on it are mostly unverifiable, since
  `grep -rn "revision=" marker/ surya/ lift/` is empty and marker's headline needs `--use_llm`, which
  egresses page images to Gemini. A benchmark you cannot reproduce is a marketing artefact.
- **A quality gate that is a single composite score.** One number is what makes a benchmark
  gameable and a regression un-actionable. A composite would let a hallucinating driver raise
  `text_recall` and offset a `hallucination_rate` collapse. Hallucination is reported alone,
  `span_exact_rate` is a hard gate not a score, and `field_acc`/`doc_acc` are always printed adjacent
  precisely because 90.2 and 20.9 are the same system.
- **Self-reported card numbers as the router's quality input.** D4 already refuses this
  (`route_scoreboard` excludes `source='self'`, UNKNOWN is the zero value) and it is right. I extend
  the same refusal to the public board: `witness != "ci"` is displayed, never ranked. A driver author
  measuring their own driver on their own corpus on their own hardware is a prior, not evidence.
- **A hosted eval service, or "just use an LLM judge for everything."** An LLM judge is required for
  free-text QA and I use one — with graphify's discipline: one model for every role, a blind second
  judge, published Cohen's κ, a verbatim quote cited in every verdict, and a spend ledger. But a
  judge as the *primary* mechanism means the framework's quality claims depend on a model whose
  weights change under you, which is precisely the HunyuanOCR failure (94.10 measured on TensorRT
  against a repo shipping Transformers and vLLM, which it admits disagree). Deterministic assertions
  first; the judge only where nothing deterministic exists.
- **A bigger corpus instead of a better-instrumented one.** Doubling to 1,200 documents costs ~4
  person-weeks of labelling and buys a `sqrt(2)` narrowing of every interval. The same 4 weeks spent
  on the calibration tables and the absence suite buys two properties nobody else has. Marginal
  precision is the cheapest thing to buy later; missing structure is not.
- **Whole-document `.owdoc` files as the committed golden.** A 5,000-page golden is ~200 MB of store
  and an unreviewable diff, and it re-blesses on every geometry patch. `.owsum` at ~400 KB with the
  merkle digests, plus `rebind` on demand, is the same coverage at 1/500th the review cost.
- **Per-page validation calls in the generation direction, and per-block eval in the parse direction.**
  Both are rejected on the economics the evidence already establishes: ppt-master rejected per-page
  checker calls because each is a context round trip, and marker measured one full-page OCR request
  at ~7× cheaper than N block requests *and more accurate* (`marker/builders/ocr.py:76-84`). Eval
  granularity follows the same rule as routing granularity: the part is the unit, the block is a flag.
- **A separate `omniweave-eval` distribution.** It would be a twelfth distribution against D1's
  eleven, for code whose only consumers are `omniweave-conform` and CI. The suite goes inside
  `omniweave-conform`, which already exists, already depends on pytest, and is already the
  distribution a third-party driver author installs.
- **numpy/scipy in the stats path.** Rejected on D1's core-purity logic applied one level out: the
  gate path must be installable in the same clean environment the gates run in, and every number I
  need has a closed form. numpy is permitted in the *nightly* bench job's optional plotting, and
  nowhere a gate can reach.
- **Warn-only for any gate, ever.** D1 names the social failure mode itself (`mode = "fail"`, never
  `"warn"`, on the licence gate; and its own Risks note that "the social failure mode is someone
  adding `--warn-only`"). Q21 replaces the pressure valve with a real one: a guard that fires on
  noise goes on a `flaky-guards.json` list that itself blocks the release, so the fix is triage
  rather than suppression.

---

## 7. Conflict flagged: `[[quality.benchmark]]` needs two more required fields

I am not re-litigating D3; I am reporting that a table D3 owns cannot do the job D3 assigns it, and
naming the minimum amendment.

**Upstream ruling:** `_plan/_notes/rulings/D3-drivers.md`.

**Exact clauses.** From the Decision: *"`omniweave-conform` is a separate distribution whose thesis is
that **the card is the test plan** … it — not the author — writes `[cost]` and `[quality]` into the
card under a recomputable attestation."* From invariant **D3-13**: *"Publish gate rejects
author-written values; the loader recomputes `attestation`; `attested = false` ⇒ never
auto-selected."* From invariant **D3-14**: *"Every benchmark row carries its `measured_on` tuple …
HunyuanOCR's TensorRT-measured 94.10 against a repo shipping Transformers/vLLM is the cautionary
case."* And the card's shape:

```toml
[[quality.benchmark]]
suite = "omniweave-golden"; version = "2026.09"; slice = "office"
metric = "structure_f1"; value = 0.94
measured_on = { weights="n/a", runtime="anydoc", runtime_version="0.2.4",
                sampling="n/a", prompt_version="n/a" }
attestation = "sha256:9f2c…"            # over the canonical card MINUS this key
```

**The defect, in two parts.**

1. **`attestation` proves integrity, not provenance.** It is a hash over the card computed by the same
   kit run that wrote the values. An author who runs `omniweave conform --bench` against a locally
   modified copy of `omniweave-golden 2026.09` gets `structure_f1 = 0.99` and a perfectly valid
   attestation, and D3-13's loader check passes. `version = "2026.09"` is a *string*, so nothing binds
   the row to the corpus's actual bytes. The card's benchmark rows are therefore admissible evidence
   with no chain of custody — which is the same class of defect as HunyuanOCR's TensorRT number that
   D3-14 exists to prevent, one level down.
2. **`value = 0.94` has no `n` and no interval.** A point estimate with no sample size cannot be
   compared to another point estimate, cannot be regression-gated, and cannot be honestly displayed.
   A driver measured on 12 documents and one measured on 1,200 are indistinguishable in this schema.

**Minimum amendment.** Four required keys on `[[quality.benchmark]]`, all kit-written like the rest of
the block, all inside the existing `attestation`. No new tables, no new files, no change to
`compute_tier`, `resolve()`, the wire protocol, the isolation model, or any of D3's twenty-three
invariants:

```toml
[[quality.benchmark]]
suite = "omniweave-golden"; version = "2026.09"
corpus_digest = "sha256:c0de…"          # NEW — REQUIRED. Binds the row to the corpus BYTES.
slice = "office"
metric = "structure_f1"; value = 0.94
n = 412                                  # NEW — REQUIRED. Row is refused below min_slice_n = 30.
ci95 = [0.921, 0.958]                    # NEW — REQUIRED. Closed-form stratified interval.
witness = "self"                         # NEW — REQUIRED. ci | self | third_party.
measured_on = { weights="n/a", runtime="anydoc", runtime_version="0.2.4",
                sampling="n/a", prompt_version="n/a",
                hardware="x86_64-linux 8c/16GiB" }     # `hardware` mirrors [cost].measured_on
```

with one added invariant, **D3-24**: *a `[[quality.benchmark]]` row whose `corpus_digest` does not
match a corpus digest published in the omniweave release manifest is treated as `witness = "self"`
regardless of what it declares, and a `witness != "ci"` row is displayed but never ranked and never
read by `route propose`.*

**Why this is an amendment rather than a silent addition.** D3 says unknown keys inside
`[capability.<port>]` are ignored with a recorded degradation, but says nothing about unknown keys
inside `[quality]`, and the card schema's `required` set is D3's to define. Adding four required keys
to a table another ruling specified is exactly the kind of change that must be visible now rather
than discovered in the charter. Note that it costs D3 nothing it was not already paying: the kit
already computes the numbers, already knows the corpus it read, and already writes the block.

---

## 8. Terminology

- **Assertion** := one ground-truth claim about one document, in olmOCR-Bench's record shape, carrying `checked`, `evaluable_in`, and (for owdoc evaluation) an `addr`. The unit of ground truth.
- **`omniweave-golden`** := the redistributable evaluation corpus. A versioned data artifact, not a Python distribution; installed by digest into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/`.
- **`corpus_digest`** := sha256 over the sorted `(relpath, sha256)` pairs of a corpus, NUL-framed. The identity a benchmark row binds to.
- **`.owsum`** := the level-1 golden projection: one deterministic line per page carrying block counts, kind/layer/trust/quote histograms and the page's merkle `content_digest` and `layout_digest`.
- **Budget** := an absolute floor on a metric. Its breach is a product failure, owned by the product.
- **Guard** := a delta against the previous release. Its breach is a change failure, owned by the author. Fires only at paired `p < 0.01` and effect ≥ MDE.
- **MDE** := minimum detectable effect, `2 × se(headline)` at the corpus's current size, recomputed each corpus release.
- **Calibrator** := the fixed in-repo CPU workload run immediately before and after a timed measurement; every time budget is a ratio to it. Disagreement > 15% between the two readings yields `UNSTABLE`.
- **`UNSTABLE`** := a third performance verdict, distinct from pass and fail, meaning the runner could not be measured. Three consecutive on one job is a failure.
- **`UNKNOWN`** := the state of a metric, slice, tier or calibration that could not be computed. Never the same as a pass, never silently dropped, and `ow release check` refuses on it.
- **Witness** := who produced a benchmark row — `ci` (omniweave's own workflow on the published corpus), `self` (the driver author), `third_party`. Only `ci` rows are ranked.
- **Paired-damage suite** := the causal evaluation of the absence contract: one D2 `Diag` code injected at a time into a pristine corpus, with the undamaged run as the counterfactual.
- **`Calibrated`** := the wrapper every confidence value crosses the serve boundary inside, carrying `state`, the bucket's empirical accuracy, its Wilson interval, `n`, `eval_set_id` and `measured_at_ns`. `state != "calibrated"` forbids rendering any number, percentage, bar, colour or grade.
- **Portability suite** := LOCOMO and LongMemEval-S, run quarterly as competitor-comparable adapters, reported in their own scoreboard section and never used as a primary quality gate.

## 9. Open questions

- **Does whole-point quantization actually absorb driver geometry jitter, and therefore is `layout_digest` a usable golden key?** D2 leaves this open and every geometry golden depends on it. Settled by `ow bench geometry-jitter`: two pdfium versions × two layout-model revisions over the same 500-page fixture, plotting the per-corner delta distribution. If the 99th percentile exceeds half a point, geometry goldens must fall back to the tolerance comparison on every run and a `digest_recipe` bump is required.
- **What is the real blocks-per-page envelope, and does it invalidate the `.owsum` size claim?** D2's 60–120/page is an estimate. `.owsum` at ~80 B/page is insensitive to it, but the corpus's storage projection and the `min_slice_n` arithmetic are not. Answered by the same fixture run D2 already specifies.
- **Should the `eval_*` tables live in the corpus `.owstore` or a separate file?** Contention between a nightly bench write and a bulk index is a real WAL hazard. D5 owns the file-layout call; my requirement is only that the schema and the identity discipline are the ones above.
- **How many documents does a slice need before `trust` calibrates?** Each confidence bucket needs n ≥ 30 and adjacent Wilson intervals must not overlap, which for p ≈ 0.9 vs 0.96 needs roughly n ≥ 150 per bucket. Measured directly on the 2026.09 corpus; the answer sets the corpus growth plan and tells us how many slices will read `(uncalibrated)` in v1.
- **Is `agree.decode_vs_page` a good enough calibration label for `block.trust`, or only for `garble.score`?** It is free and abundant but biased to the escalated population. Settled by measuring the correlation between `agree`-derived and audit-derived `p_hat` on the slices where both exist; if they diverge by more than one Wilson width, `trust` needs corpus labels and the free channel is only good for the router.
- **Do we run the LOCOMO / LongMemEval-S adapters against `mem0` and `supermemory` ourselves, or quote graphify's numbers?** Running them costs a proxy, two self-hosted services and ~$20 of ingest per full sweep; quoting them inherits graphify's fairness rules without inheriting its verification. Decided by whether we can reproduce graphify's own row for graphify within its stated interval on the first attempt.
