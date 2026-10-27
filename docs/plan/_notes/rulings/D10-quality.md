# D10-quality — Quality, evaluation, testing and trust

## Decision

Evaluation is a **data model with a publishing gate**, not a CI job: every number omniweave shows a
human, an agent, a router or a scoreboard is a row in one `.oweval` SQLite file carrying
`(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)`, produced by an **RNG-free
harness** that lives inside `omniweave-conform` — **D1's eleven distributions stand unamended and
D10 adds none**. The test pyramid is six budgeted tiers plus a `contributor-parity` job that proves
`uv sync && pytest` is green offline, GPU-free and under ten minutes, made possible by **Cassettes**:
content-addressed replays intercepted at D3's `DriverIO.service()` and D1's `omniweave_core.modelserver`,
the only two outbound model channels a driver has (D3-7), so coverage is complete by construction.
Parser goldens are **Reductions** — `shape` (frozen, per-document counters, no text, no geometry),
`pages` (tracked, per-page rollup), `outline` (tracked, per-block digest + preview) — and the only
semantic differ is **`rebind()`**, D2's existing three-rule matcher, run against a committed exploded
`.owdoc.d/` deep golden, so there is one matcher and nothing to drift. Regression is gated in a strict
hierarchy: exact **Counters** first (they catch a silent re-render, a re-billed free operator, a 100%
cache miss — none of which move a clock), then absolute memory, then time as a **Pacer** ratio on one
pinned runner against a 7-run rolling median. And the rule the whole decision exists for: **a
confidence signal that has not passed separation, sharpness and freshness in the current release is
stored, usable as an internal filter, and may never be rendered as a number, a percentage, a bar, a
grade or a colour** — with a written kill condition that deletes the tag rather than caveating it, and
with `span_exact_rate` a hard gate at 1.000 rather than a metric, because `quote = VERBATIM` is
self-verifying on the user's own documents and needs no corpus at all.

## Spec

**Scope.** D10 owns the pyramid and its budgets, the golden corpora and their licensing, the
`.oweval` schema and the harness, accuracy and performance regression gates, a twelfth conformance
suite (`quality`), retrieval and absence evaluation, calibration of every user-facing confidence
surface, and the public scoreboard. It does not own the response envelope (D9), the store layout
(D5), the router (D4), or D3's kit contract. Where it needs something from another layer it names
the obligation and stops.

**No new distributions.** Harness, metrics, reducers, Cassette codec, calibrator and scoreboard
generator go into `omniweave-conform` (D1's eleventh, `core + pytest`, 3 MB). Heavy competitor
`Runner`s live in `evals/runners/`, in-tree and unpackaged, so docling's torch never reaches a
weight gate. `omniweave-golden` is a **data artifact, not a wheel** — `.tar.zst` + `manifest.toml` +
`.sha256`, installed by `ow eval fetch` into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` and
digest-verified on every use, with D1's toolchain rule verbatim: *a digest mismatch is a permanent
failure and never triggers a fetch*. A 240 MB corpus wheel breaks G2, breaks G5 the moment it is
date-versioned, and exceeds PyPI's default per-file limit.

**The pyramid.** T0 gates (D1 G1–G16 + the static Q-G series, ≤ 3 min, every PR) · T1 unit +
property (≤ 4 min/cell) · T2 golden (Reductions + Counters + Cassette replay + the deterministic half
of the absence suite, ≤ 4 min) · T3 conform (D3's eleven suites, ≤ 5 min — D3's number, treated as a
correctness test) · T4 eval (five suites, live models, nightly, ≤ 90 min) · T5 soak (weekly). Two
workflow files, not sixty. **`SKIP` is not a state**: a tier, slice or metric that cannot run is
`UNKNOWN`, and `ow eval release-check` refuses on it. Hypothesis runs `derandomize=True` at 200
examples on PRs and 2,000 randomized nightly; every nightly counterexample is minimized and committed
to `fixtures/regressions/`, treated exactly as anydoc treats `fuzz/seeds/`.

**Goldens.** Never snapshot the document. `shape` is **frozen** — a byte diff fails, and a T2 test
asserts two pdfium minors and all nine OS×Python cells produce identical `shape` bytes, converting
D2's open question about whole-point quantization from an assumption into a measurement. `pages` and
`outline` are **tracked**: a diff renders into a PR comment led by the `shape` delta, because "6
fewer tables, 174 more cells" is the sentence a reviewer needs and 9,000 diff lines are not.
`outline` is suppressed above 500 pages. Geometry never enters a frozen golden; it enters `outline`
only as `layout_digest`, and the per-corner tolerance comparison (docling's measured
`STRICT_BBOX_TOL_RATIO = 0.0025` / `FUZZY_BBOX_TOL_RATIO = 0.005`, `verify_utils.py:26-30`) survives
only as the diagnostic `ow eval golden --geometry`. Blessing requires `OMNIWEAVE_BLESS`, a
`BLESS.log` row in the same commit with a reason ≥ 20 characters, and a second reviewer past 20% of
files; `test_bless_flag_is_off()` is docling's `tests/test_data_gen_flag.py` adopted whole.

**Corpora, four tiers.** Tier A `fixtures/` — in repo, ≤ 64 MB, one `.meta.toml` per file, four
admissible provenances (`generated` preferred; `public_domain` US federal works under 17 U.S.C. §105;
`cc0`/`cc_by`; `authored`) and no fifth, with **≥ 40% of `fixtures/docs/` real public-domain scans**
because a wholly synthetic corpus flatters the parser. Tier B `omniweave-golden` — redistributable,
digest-installed, ~600 documents. Tier C — pointer manifests with per-file sha256 and two independent
booleans, `redistribute` and **`publishable`**; a corpus whose licence forbids publication is measured
internally and renders `withheld: corpus licence`. Tier D — the user's own corpus, watermarked
`corpus: local, unverifiable`. **An assertion set can itself be a derivative work**:
`assertions_redistributable` is separate from `document_redistributable`, and a Tier-B assertion file
quoting more than `min(2000 chars, 10%)` of one source document is refused.

**Determinism with models.** Three declared classes, tested per declaration. **D0
byte-deterministic**: two *separate processes* with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`,
`TMPDIR`, cwd; equal `content_digest` and `layout_digest` per block and an identical `Diag` multiset.
**D1 seeded**: k = 3 runs, mismatched-block fraction ≤ a `drift_band` the kit *measures and writes*
into the card. **D2 unpinnable**: no equality test, a k = 5 stability envelope with a measured
coefficient of variation and `diag_set_stable`, and **a driver whose `MeasuredOn.weights_revision` is
not an exact SHA may not contribute a `[[quality.benchmark]]` row at all** — it gets a scoreboard
entry stamped `unpinned`, displayed and never ranked. In CI every model call is a Cassette replay and
a miss is `OW-Q-004`, never a live call: olmocr's defaults are a 64× amplifier fired in parallel.

**Statistics, closed form, zero RNG.** Macro mean over slices with `min_slice_n = 30` (D4's
`min_audit_n`, reused); `se = sqrt((1/S²)·Σ sd_s²/n_s)`; Wilson for every rate and every calibration
bucket. Paired A/B is the sign-flip permutation test's exact asymptotic,
`p = 2(1 − Φ(|Σd| / sqrt(Σd²)))`, with exact enumeration below N = 20 and a seeded resample only in
between, and `method ∈ {closed_form, exact, resampled}` stamped on every interval. This is not
fastidiousness: olmOCR-Bench — the best-designed benchmark in the collection — calls
`np.random.choice`/`shuffle` unseeded at `olmocr/bench/utils.py:33,55,120,172` and `random.sample` at
`benchmark.py:262`, with no `seed` anywhere in `olmocr/bench/`, so its published CIs and p-values do
not reproduce and nobody noticed.

**Regression, three mechanisms in a strict order.** (1) **Counters** — exact, per PR, ±1 fails without
a bless. They catch the four production incidents that are invisible in timing noise. (2) **Memory** —
absolute budgets on `peak_rss_bytes` and `wal_peak_bytes`; the recorded failures are memory failures
(codegraph's 5.9 GB WAL against a 340 MB DB; exit 137 at 22 GB; D1's own anydoc eager-marshal cliff).
(3) **Time** — a **Pacer** ratio on one pinned runner, 7-run rolling median, three consecutive
breaches. A **Budget** is an absolute floor owned by the product; a **Guard** is a delta against
release N−1 owned by the PR author, firing only at paired `p < 0.01` **and** effect ≥ MDE. Baselines
are **release-anchored** and additionally checked against N−2 at 2×, so ten blessed 9% regressions
cannot compound. There is no `--warn-only` anywhere; a downgrade is a `class` change in `gates.toml`,
a reviewed diff with an owner and a `review_by`.

**Confidence.** Six confidence-shaped things exist across the settled rulings; the two most
load-bearing need no labelled corpus at all, because `quote = VERBATIM` is self-verifying via
`Doc.verify_quote()` and `agree.decode_vs_page` is free on every escalation. The chain for the rest:
a signal exposes a probability (D4 R5), the scale is named in an append-only `tools/scorekinds.toml`
and **an unregistered `score_kind` raises at `DocSink.add_block`**, a curve is fitted on a
deterministically split calibration set (`blake2b(doc_key‖"ow-split-1") % 100`, so leakage is
structurally impossible), and the renderer consumes `Calibrated.status`, never the float. Kill
conditions are written: a `score_kind` failing sharpness is written `NULL`; an ordinal failing
separation across two consecutive releases forces `confidence = "none"` on the card and
`trust = AMBIGUOUS` on every block, which makes D2's `block_review` index correctly select all of it.

**Absence** gets both constructions, because they measure different things and both are cheap: an
absence corpus whose ground truth is built by *removal* (`absent_precision`, `absent_recall`,
`false_confident_zero ≤ 0.01`), and a **paired-damage** suite that injects one D2 `Diag` code at a
time into a pristine corpus and asserts the answer degrades to a *named cause* rather than a confident
zero. The damage half needs no model, so it gates every PR.

**The scoreboard** is a static site generated from a committed `eval/results/**.json` tree,
byte-diff gated, defaulting to **accuracy-per-dollar within a licence tier**, with `not_measured[]`
and `confounders[]` required non-empty, `witness` on every row, `†` on entrant-bias rows **including
our own**, published judge κ, and a 15% holdout whose gap prints ⚠ above 5 points.

## Concrete shape

```
packages/omniweave-conform/src/omniweave_conform/     # NO NEW DISTRIBUTION. D1's eleventh.
├── suites/                       # D3's eleven, unchanged, PLUS one
│   ├── card/ purity/ contract/ capability/ idempotence/ determinism/
│   ├── limits/ sandbox/ cost/ licence/ fuzz/
│   └── quality/                  # SUITE TWELVE — NON-MANDATORY. `omniweave conform --bench`.
│       ├── metrics.py            text_f1 structure_f1 order_acc table_rel_acc
│       │                         hallucination_rate field_acc doc_acc furniture_f1
│       ├── eval_owdoc.py         resolves by `addr`; Grid.up/down/left/right/top_heading
│       ├── eval_text.py          olmOCR-Bench evaluator; normalize_text VERBATIM
│       ├── align.py              banded Levenshtein · deterministic greedy block matcher
│       └── stability.py          k=5 -> [[quality.stability]]
├── stats/                        # NO RNG ON THE DEFAULT PATH. semgrep-enforced.
│   ├── interval.py               macro_ci (closed form) · wilson
│   ├── compare.py                paired_p (sign-flip asymptotic; exact below N=20)
│   ├── calibrate.py              isotonic/platt fit · ECE (10 equal-mass bins) · Brier
│   └── resample.py               FALLBACK ONLY; seed = blake2b(eval_set_id|cand|metric|version)
├── reduce.py                     shape | pages | outline · deterministic float formatting
├── golden.py                     compare · bless · BLESS.log · PR-comment renderer
│                                 diff_deep() DELEGATES TO rebind(). There is no second matcher.
├── cassette.py                   record | replay at DriverIO.service + core.modelserver
├── counters.py                   COUNTERS tuple + the exact/ratchet gate
├── damage/                       one injector per Diag code
│   ├── encrypt.py strip_text_layer.py chaos.py budget.py drop_part.py
│   └── deny_probe.py downgrade_origin_span.py rotate_embedder.py
├── suites_eval/{parse,extract,retrieve,absence,roundtrip}/
├── portability/{locomo,longmemeval}.py    # QUARTERLY. Own scoreboard section. Never a gate.
├── runners.py                    Runner protocol; measured_on() is REQUIRED
├── perf/pacer.py                 blake2b 64 MiB + 2M int loop + 200k SQLite rows
├── store.py                      .oweval writer/reader (the ONLY sqlite3 use outside core.store)
├── report.py                     GateStatus · FindingProvenance · export to eval/results/
├── scoreboard.py                 eval/results/**.json -> site;  --check / --bless
└── lint.py                       --corpus --confidence --measured --estimates

evals/runners/                    IN-TREE, UNPACKAGED: docling markitdown pandoc soffice unstructured
fixtures/                         TIER A — <= 64 MB, >= 40% real public_domain scans (Q-G2)
├── NOTICE.md                     GENERATED from *.meta.toml; --check gated
├── docs/<name>.<ext> + <name>.<ext>.meta.toml
├── gen/                          committed generators: 3 KB of script, not 90 MB of binary
│   gen_5000p_pdf.py gen_4m_cell_xlsx.py gen_ragged_table_docx.py gen_zip_bomb.py
│   gen_encrypted_pdf.py gen_40byte_docx.py gen_spanned_merged_pptx.py
├── goldens/<corpus>@<v>/<driver>@<schema_v>/<doc>.{shape,pages,outline}
├── goldens/deep/<doc>.owdoc.d/   EXPLODED, ZSTD OFF: manifest.json + blocks/*.ndjson.
│                                 <= 24 docs, <= 40 pages each. This is what rebind() matches.
├── goldens/BLESS.log             APPEND-ONLY; CI diffs it against the previous tag (D1 G13)
├── cassettes/<service>/<sha[:2]>/<sha>.ndjson.zst
├── regressions/                  minimized hypothesis + fuzz counterexamples, forever
└── perf/pacer_baseline.json

corpora/*.toml                    TIER C pointer manifests + per-file .sha256
$OMNIWEAVE_HOME/golden/<version>-<sha256>/            TIER B, digest-verified on every use
eval/results/<runner>@<v>/<suite>/<corpus>@<v>.json   COMMITTED, byte-diff gated
eval/gates.toml  eval/counters.toml  eval/perf.toml  tools/scorekinds.toml
eval/calibration/<score_kind>@<eval_set_id>.json
eval/baselines/<os>-<py>-<runner>.json
fuzz/targets/                     atheris: owdoc_archive reduction card_toml route_policy
                                  config_coerce cite_addr spanmap query_sanitize
fuzz/seeds/                       mirrored from vendor/anydoc/fuzz/seeds at the pinned SHA
```

```sql
-- ══ .oweval — a SEPARATE SQLite file from .owstore. Eval rows are deleted; corpus rows are not,
--    and one eval run spans many stores. Pragma ORDER is load-bearing (codegraph #238).
PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;

CREATE TABLE eval_corpus (
  corpus_id TEXT NOT NULL, version TEXT NOT NULL,      -- ('omniweave-golden','2026.09') — D3's strings
  corpus_digest TEXT NOT NULL,                          -- sha256 over sorted (relpath,sha256), NUL-framed
  tier TEXT NOT NULL CHECK (tier IN ('A','B','C','D')),
  n_docs INTEGER NOT NULL, n_assertions INTEGER NOT NULL, n_checked INTEGER NOT NULL,
  document_redistributable   INTEGER NOT NULL,
  assertions_redistributable INTEGER NOT NULL,
  publishable INTEGER NOT NULL,        -- may its numbers reach the PUBLIC scoreboard?
  PRIMARY KEY (corpus_id, version)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_run (
  run_id TEXT PRIMARY KEY,                              -- 'ev_' || sha256_canonical(identity)[:24]
  suite TEXT NOT NULL CHECK (suite IN ('parse','extract','retrieve','absence','roundtrip',
                                       'portability','perf')),
  corpus_id TEXT NOT NULL, corpus_version TEXT NOT NULL, corpus_digest TEXT NOT NULL,
  subject TEXT NOT NULL,                                -- a driver id, a pipeline profile, or a Runner
  subject_version TEXT NOT NULL,
  producer_id INTEGER,                                  -- D2's Producer, when the subject is ours
  measured_on TEXT NOT NULL,                            -- MeasuredOn as canonical JSON. NOT NULL.
  timing_basis TEXT NOT NULL CHECK (timing_basis IN ('in_process','spawn_inclusive',
                                                     'server_attached')),
  witness TEXT NOT NULL CHECK (witness IN ('ci','self','third_party')),
  unpinned INTEGER NOT NULL DEFAULT 0,                  -- 1 when weights_revision is not an exact sha
  entrant_bias INTEGER NOT NULL DEFAULT 0,              -- subject.vendor == corpus.vendor. Ours too.
  cassette TEXT NOT NULL CHECK (cassette IN ('off','allow','required')),
  policy_digest TEXT, pricebook_digest TEXT, harness_version TEXT NOT NULL,
  code_fingerprint TEXT NOT NULL, hardware TEXT NOT NULL,
  fairness TEXT NOT NULL DEFAULT '{}',                  -- one model per role, one embedder, budgets
  spend_micros INTEGER NOT NULL DEFAULT 0,
  degradations TEXT NOT NULL DEFAULT '[]',
  started_ns INTEGER NOT NULL, ended_ns INTEGER,
  status TEXT NOT NULL CHECK (status IN ('ok','partial','unknown'))
) STRICT;

CREATE TABLE eval_assertion (            -- olmOCR-Bench's record, generalised
  assertion_id TEXT PRIMARY KEY,
  corpus_id TEXT NOT NULL, corpus_version TEXT NOT NULL,
  doc TEXT NOT NULL, page INTEGER,
  type TEXT NOT NULL,                    -- baseline present absent order table math format footnote
                                         -- + ours: cell_rel field span cite roundtrip absence
  spec TEXT NOT NULL,                    -- JSON: TableTest's up/down/left/right/top_heading/…
  addr TEXT,                             -- D2's type-free address; the owdoc evaluator resolves this
  evaluable_in TEXT NOT NULL CHECK (evaluable_in IN ('owdoc','text','both')),
  max_diffs INTEGER NOT NULL DEFAULT 0,
  checked TEXT CHECK (checked IN ('verified','rejected')),   -- NULL runs but NEVER scores
  derived_from_sha256 TEXT NOT NULL,     -- the licence chain for the assertion itself
  slices TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE TABLE eval_verdict (              -- the grain everything aggregates from
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  assertion_id TEXT NOT NULL REFERENCES eval_assertion(assertion_id),
  evaluator TEXT NOT NULL CHECK (evaluator IN ('owdoc','text')),
  passed INTEGER NOT NULL, score REAL,
  explanation TEXT NOT NULL DEFAULT '',  -- olmOCR-Bench prints WHY. So do we.
  slice_key TEXT NOT NULL, wall_ms INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, assertion_id, evaluator)
) STRICT, WITHOUT ROWID;
CREATE INDEX eval_verdict_slice ON eval_verdict(run_id, slice_key);

CREATE TABLE eval_metric (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  metric TEXT NOT NULL, slice_key TEXT NOT NULL DEFAULT '__macro__',
  value REAL, n INTEGER NOT NULL, ci_lo REAL, ci_hi REAL,
  method TEXT NOT NULL CHECK (method IN ('closed_form','exact','resampled','none')),
  truth_kind TEXT NOT NULL CHECK (truth_kind IN ('human','rendered','native_run','synth_ocr',
                                                 'agreement','self')),
  state TEXT NOT NULL CHECK (state IN ('ok','regressed','unknown')),   -- UNKNOWN is the zero value
  PRIMARY KEY (run_id, metric, slice_key)
) STRICT, WITHOUT ROWID;
-- truth_kind='agreement' and 'self' may NEVER populate an accuracy column (Q-G9).
-- truth_kind='native_run' may ONLY anchor a FIDELITY metric, never recall/coverage/classification.

CREATE TABLE eval_calibration (
  eval_set_id TEXT NOT NULL, score_kind TEXT NOT NULL, producer_id INTEGER NOT NULL,
  slice_key TEXT NOT NULL, bucket INTEGER NOT NULL,
  bucket_lo REAL NOT NULL, bucket_hi REAL NOT NULL,
  n INTEGER NOT NULL, n_correct INTEGER NOT NULL,
  p_hat REAL NOT NULL, wilson_lo REAL NOT NULL, wilson_hi REAL NOT NULL,
  ece REAL, brier REAL,                                  -- NULL for ordinal signals
  label_sources TEXT NOT NULL,                           -- '["synth_ocr:L3","human"]'
  measured_at_ns INTEGER NOT NULL, harness_version TEXT NOT NULL,
  PRIMARY KEY (eval_set_id, score_kind, producer_id, slice_key, bucket)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_counter (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  counter TEXT NOT NULL, scope TEXT NOT NULL, value INTEGER NOT NULL,
  PRIMARY KEY (run_id, counter, scope)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_perf (
  run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
  budget_id TEXT NOT NULL,
  pacer_before_ns INTEGER NOT NULL, pacer_after_ns INTEGER NOT NULL, work_ns INTEGER NOT NULL,
  time_ratio REAL NOT NULL,                              -- work_ns / mean(pacer_before, pacer_after)
  peak_rss_bytes INTEGER NOT NULL, wal_peak_bytes INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('pass','fail','unstable','stale','unknown')),
  PRIMARY KEY (run_id, budget_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE eval_flake (
  test_id TEXT NOT NULL, day TEXT NOT NULL,
  runs INTEGER NOT NULL, fails INTEGER NOT NULL, reran_green INTEGER NOT NULL,
  PRIMARY KEY (test_id, day)
) STRICT, WITHOUT ROWID;

-- The publishing view. UNKNOWN is the zero value, exactly as D4's route_scoreboard.
CREATE VIEW eval_scoreboard AS
SELECT m.metric, m.slice_key, r.suite, r.subject, r.subject_version, r.corpus_version,
       r.witness, r.unpinned, r.entrant_bias, m.value, m.ci_lo, m.ci_hi, m.n, m.method,
       m.truth_kind, c.publishable,
       CASE WHEN m.state = 'unknown'                              THEN 'UNKNOWN'
            WHEN c.publishable = 0                                THEN 'WITHHELD'
            WHEN r.witness <> 'ci' OR r.unpinned = 1
              OR r.entrant_bias = 1
              OR m.truth_kind IN ('agreement','self')             THEN 'UNRANKED'
            ELSE 'RANKED' END AS standing
FROM eval_metric m
JOIN eval_run r USING (run_id)
JOIN eval_corpus c ON c.corpus_id = r.corpus_id AND c.version = r.corpus_version
WHERE r.status <> 'unknown';
```

```python
# ══ omniweave_conform/measured.py — frozen, NO DEFAULTS. A missing field is a TypeError. ══
@dataclass(frozen=True, slots=True)
class MeasuredOn:
    weights:          str | None       # None for a pure-code path
    weights_revision: str | None       # EXACT sha. "main" raises (D2/D4 already lint it).
    runtime:          str              # "vllm"|"transformers"|"tensorrt"|"anydoc"|"pdfium"
    runtime_version:  str
    sampling:         Mapping[str, Scalar]        # {} for a deterministic path
    prompt_version:   str | None
    hardware:         str              # "1xA10G-24GB" | "x86_64-linux 8c/16GiB"
    corpus:           str              # "omniweave-golden@2026.09"
    corpus_digest:    str
    harness_version:  str
# Q-G8's regression fixture is HunyuanOCR's published 94.10 OmniDocBench — measured on TensorRT
# while the repo ships Transformers and vLLM, which it admits disagree. A test constructs that
# row without `runtime` and asserts refusal.

GateStatus = Literal["pass", "fail", "unstable", "stale", "unknown"]
# There is no "pass_with_warnings". A warning that cannot fail is the thing that rots.
FindingProvenance = Literal["blocking", "introduced", "inherited"]
# inherited := byte-identical in the previous release's report for the same (corpus, driver-major).
# The headline count is `introduced` + `blocking` only, so a corpus of pre-existing findings does
# not make every driver look broken and make the team stop reading the report.  (ppt-master)

# ══ omniweave_conform/reduce.py ═══════════════════════════════════════════════
Volatility = Literal["frozen", "tracked"]
def reduce_shape(doc: "Doc")   -> str: ...   # FROZEN. per-document counters only.
def reduce_pages(doc: "Doc")   -> str: ...   # TRACKED. one line per page.
def reduce_outline(doc: "Doc") -> str: ...   # TRACKED. one line per block; suppressed > 500 pages.
```

```
# fixtures/goldens/core@2026.09/parse.doc.anydoc@3/eu-annual-report-2019.shape   FROZEN
owshape/1  corpus=core@2026.09  doc=3f2a…  driver=parse.doc.anydoc@0.2.4  schema_v=3
achieved.origin_span   exact          blocks.total          1284
achieved.spatial       none           blocks.kind.heading     61
achieved.tables        cells_with_spans
diag.OW_TABLE_SPAN_CLAMPED   2        blocks.kind.paragraph  902
grid.tables_with_merges      1        blocks.layer.furniture  83
marks.kind.bold            311        pages.total             42
quad.present_frac       0.0000        quote.verbatim         902
rel.kind.note_ref           27        trust.extracted       1240
# NO text. NO per-corner geometry. Sorted, LF, %.4f for fractions, never a repr.
# Q-G4: two pdfium minors x 9 OS/py cells produce BYTE-IDENTICAL bytes for this file.

# …/eu-annual-report-2019.pages    TRACKED — one line per page. 5,000 pages ~= 1.1 MB.
p0014 n=87 kind{para:61,head:3,table:1,cell:20,cap:1,pgfoot:1} layer{body:85,furn:2}
      trust{2:80,1:7} quote{norm:80,reflow:7} cdig=9f2c4a1b ldig=77a2e0d3 diag{}

# …/eu-annual-report-2019.outline TRACKED — one line per block, <= 500 pages.
# addr      kind        layer trust quote  cdig[:8]  ldig[:8]  preview[:48]
p0/0        title       body  ext   verb   3f9a1c02  1a2b3c4d  Master Services Agreement
p3/2        table       body  inf   recon  01bb9e30  4c5d6e7f  12x5 merges=1 recon=native_xml/1.00
p3/2/r0c0   table_cell  body  ext   verb   7c1120af  aa03f7de  Member State
# The DIGEST is the assertion; the preview is a comment for the human. A one-character upstream
# change is one changed line, not a re-wrapped paragraph diff.
```

```python
# ══ omniweave_conform/golden.py — THE DIFFER IS rebind(). There is no second matcher. ══
def diff_deep(golden_dir: Path, fresh: "Doc") -> "RebindReport":
    """Import fixtures/goldens/deep/<doc>.owdoc.d/ into a scratch .owstore as gen 1, import
    `fresh` as gen 2, and return rebind(store, doc_ord, to_gen=2, threshold=...).

    D2 already specifies the three-rule matcher (equal content_digest under the same parent
    CARRIES the block_id; equal addr+kind with a changed digest CARRIES and bumps revision;
    otherwise a fresh id plus a block_history row) and RebindReport{carried, revised, created,
    retired, match_rate_by_page, quarantined, threshold}. That report IS a snapshot diff.
    One implementation, two consumers, and the golden's tolerance is the same number the model
    layer already tunes and quarantines on.

    The deep golden is the EXPLODED archive (`.owdoc.d/`, zstd off) so git delta-compresses it,
    `jq` reads it, and rebind has two real generations to match. <= 24 docs, <= 40 pages each."""
```

```toml
# ══ eval/counters.toml — EXACT by default. The gate that catches what a clock cannot. ══
[gate]  owner = "team@particle6.com"  review_by = "2027-06-01"
message = """Counter delta on {corpus}. Top movers:\n{top3}\n
If intended: ow eval bless --counters --reason '<what changed and why>'"""

[[counter]] id="blocks_written"        class="exact"
[[counter]] id="pages_committed"       class="exact"
[[counter]] id="page_renders"          class="exact"   # a driver upgrade silently re-rendering
[[counter]] id="signal_computations"   class="exact"   # D4 R4 generalised to every signal
[[counter]] id="subprocess_spawns"     class="exact"
[[counter]] id="service_attaches"      class="exact"   # a clean digital PDF must start no GPU
[[counter]] id="driver_activations"    class="exact"
[[counter]] id="escalations"           class="exact"
[[counter]] id="degradations"          class="exact"
[[counter]] id="llm_calls"             class="exact"
[[counter]] id="cache_hits"            class="exact"   # graphrag's permanent silent 100% miss
[[counter]] id="cache_misses"          class="exact"
[[counter]] id="rebilled_units"        class="exact"   # a free re-run re-billing a paid operator
[[counter]] id="tokens_out"            class="ratchet" tolerance=0.02
[[counter]] id="store_rows_read"       class="ratchet" tolerance=0.05
```

```toml
# ══ eval/gates.toml — every gate has an owner and a review date. No --warn-only, anywhere. ══
[defaults]
guard_p_max = 0.01                 # paired sign-flip; must ALSO clear the MDE
mde_rule    = "2 * se(headline)"   # recomputed each corpus release, never guessed
baseline    = "release"            # NOT "previous commit"
ratchet_ceiling_releases = 2       # also checked vs N-2 at 2x tolerance
min_slice_n = 30                   # == D4's min_audit_n

[[gate]] metric="span_exact_rate"     slice="*"                  budget=1.000  kind="hard"
# ^ Q-G6. NOT a score. D2 lets serve claim byte-exactness on `verbatim`; under 1.0 it is a lie.
[[gate]] metric="degradation_detection" slice="*"                budget=1.000  kind="hard"
[[gate]] metric="citability_violations" slice="*"                budget=0      kind="hard"
[[gate]] metric="false_confident_zero"  slice="*"                budget_max=0.01
[[gate]] metric="hallucination_rate"  slice="*"                  budget_max=0.02  guard=0.005
[[gate]] metric="structure_f1"        slice="office/*"           budget=0.90   guard=0.010
[[gate]] metric="structure_f1"        slice="pdf/born_digital/*" budget=0.85   guard=0.010
[[gate]] metric="table_rel_acc"       slice="*/has_merges=1"     budget=0.70   guard=0.020
[[gate]] metric="order_acc"           slice="pdf/born_digital/*" budget=0.75   guard=0.015
# ^ floor sourced: a pdftext char-stream reading order scores 75% where a learned head scores 56%
#   (marker/marker/builders/line.py:80-82). We must not ship below the free baseline.
[[gate]] metric="citation_soundness"  slice="*"                  budget=0.995  guard=0.002
[[gate]] metric="doc_acc"             slice="fields/*"           budget=0.20   guard=0.020
# ^ 0.20, deliberately. lift/README.md:75 — 90.2% per field, 20.9% full document. A 0.90 budget
#   here would be a promise the field cannot keep, and it is why Q-G21 pairs the two metrics.
```

```toml
# ══ eval/perf.toml — counters exact · memory absolute · time as a Pacer ratio ══
[pacer]
work = "blake2b(64MiB) + 2M int loop + 200k sqlite insert+select"
instability_pct = 15               # |before-after|/mean > 15% => UNSTABLE (not pass, not fail)
rule = "fail on 3 consecutive nightly runs above tolerance, comparing 7-run rolling medians"
runner = "ow-bench-1"              # ONE pinned machine. A runner change is a baseline reset.

# ---- PR-gating (deterministic enough) ----
[[budget]] id="import.omniweave_core_ms"   value=62   tol_pct=25  gate="pr"   # D1 G10
[[budget]] id="cold.ow_version_ms"         value=118  tol_pct=25  gate="pr"
[[budget]] id="conform.mandatory_tier_s"   value=240  tol_abs=60  gate="pr"   # D3's 5-min rule
[[budget]] id="contributor_parity_s"       value=420  tol_abs=180 gate="pr"   # hard ceiling 600

# ---- nightly, pinned runner ----
[[budget]] id="parse.office.p50_ms"        value=5    tol_pct=20  gate="nightly"
# ^ anydoc README: 4.4 ms median across 14 formats. timing_basis = in_process.
[[budget]] id="rss.gen5000p_peak_bytes"    value=1_610_612_736  tol_pct=10  gate="nightly"
note = """THE FORK-TRIGGER GATE. D1 open question #1: anydoc marshals eagerly into Python objects
and py.detach does not cover the marshal. A breach fires vendor/anydoc/FORK-TRIGGER.md."""
[[budget]] id="rss.merged4mcell_peak_bytes" value=4_294_967_296 tol_pct=10 gate="nightly"
[[budget]] id="wal.bulk_index_peak_bytes"  value=2_147_483_648  tol_abs=536_870_912 gate="nightly"
# ^ codegraph: 5.9 GB WAL against a 340 MB DB, then 22 GB and exit 137. Absolute, not a percent.
[[budget]] id="store.bytes_per_block"      value=660  tol_pct=10  gate="nightly" ratchet=true
[[budget]] id="query.warm_p50_ms"          value=180  tol_pct=20  gate="nightly"   # D1: <= 250
```

```toml
# ══ tools/scorekinds.toml — APPEND-ONLY. An unregistered score_kind RAISES at write time. ══
[garble_p_bad]
domain = [0.0, 1.0]
semantics = "P(this page's extracted text layer is garbled)"
consumers = ["route:garble_escalate", "review:block_review", "serve:low_confidence"]
eval_set_id = "omniweave-golden@2026.09/calib"
bins = 10 ; ece = 0.031 ; brier = 0.061 ; n = 4820      # gates: ECE <= 0.05, Brier <= 0.08 (D4 R6)
measured_at = "2026-08-19T00:00:00Z" ; max_age_days = 30      # D4 [calibration]
label_sources = ["synth_ocr:L3", "human"]
diagram = "eval/calibration/garble_p_bad.svg"           # committed, with its CSV beside it

[table_recon]
domain = [0.0, 1.0]
semantics = "marker's judge score (purity+no_compound+fill+hdr+2*one_span)/6"
consumers = ["route:table_accept", "review", "render:trust_downgrade"]
ece = 0.044 ; brier = 0.072
```

```python
# ══ omniweave_conform/calibrate.py — the chain that makes CONFIDENCE non-decorative ══
CalStatus = Literal["calibrated", "bootstrap", "uncalibrated", "stale"]

@dataclass(frozen=True, slots=True)
class Calibrated:
    """The wrapper EVERY confidence value crosses the serve boundary inside. D9 renders the
    STATUS, never the float, so there is no code path from an uncalibrated number to a bar."""
    signal:      str                       # 'block.trust' | 'garble.p_bad' | 'page.ocr_score'
    value:       float | str               # the raw score, or the ordinal MEMBER NAME
    status:      CalStatus
    p_correct:   float | None              # empirical accuracy of THIS bucket in THIS slice
    ci95:        tuple[float, float] | None   # Wilson
    n:           int
    eval_set_id: str
    slice_key:   str
    measured_at_ns: int

# THE SURFACING RULE (Q-G14). status != "calibrated" =>
#   the surface MAY print the ordinal NAME followed by "(uncalibrated)";
#   it may NEVER print a percentage, a numeral adjacent to the signal, a bar, a colour ramp
#   or a grade. A renderer test feeds each status and asserts the output shape.
# AN UNCALIBRATED SIGNAL REMAINS USABLE AS AN INTERNAL FILTER AND SORT KEY. This is the clause
# that keeps D2's block_review partial index (WHERE trust < 2) working on day one.

def separation(rows: Sequence[CalRow]) -> GateStatus: ...
    """Q-G11. Ordinal signals. p_hat strictly increasing across buckets AND adjacent Wilson 95%
    intervals non-overlapping, at n >= 150 per bucket per slice. Below n: 'unknown', and the
    slice is NAMED, never silently dropped."""

def sharpness(rows: Sequence[CalRow]) -> GateStatus: ...
    """Q-G12. Probability signals. ECE <= 0.05 and Brier <= 0.08 (D4 R6, verbatim), 10
    equal-mass bins, n >= 1000. Failure => the driver writes score = NULL, score_kind = NULL
    (D2's CHECK makes the pair atomic) and every consumer's UNKNOWN path is exercised."""

# KILL CONDITIONS — written down, because "uncalibrated forever" is not an outcome.
#  * a score_kind failing sharpness twice in a row is REMOVED from tools/scorekinds.toml;
#  * an ordinal failing separation across TWO consecutive releases for a driver family forces
#    `confidence = "none"` on that card and `trust = AMBIGUOUS` on every block it produces.
#    The tag is DELETED, never caveated. D2's block_review index then correctly selects all of it.
#  * a curve past [calibration] max_age_days = 30 yields status='stale' and
#    Degradation(kind="calibration_stale") — D4's enum member, verbatim, no new vocabulary.

# LABEL SOURCES, with their validity stated in the type, not in a README.
TruthKind = Literal["human", "rendered", "native_run", "synth_ocr", "agreement", "self"]
#  human      — 2,400 double-labelled blocks across scan-clean/degraded/photo/handwriting/cjk/math.
#               The anchor. ~4 person-days, refreshed annually.
#  rendered   — soffice/pdfium render + page-image comparison. Independent of our text path.
#  native_run — the source XML run text (w:t / a:t / sharedStrings). VALID ONLY FOR FIDELITY:
#               "do the extracted characters equal the source run's characters". It is NOT valid
#               for recall, coverage or classification, because any independent w:t walk either
#               re-implements or contradicts the same branch selection the subject driver does
#               (anydoc/src/formats/docx/content.rs:146 mc:AlternateContent, :169 w:sdt,
#               :536 w:instrText, :719-726 w:txbxContent; mod.rs:62-63 footnotes/endnotes parts).
#               A metric declaring truth_kind='native_run' outside the fidelity set fails Q-G9.
#  synth_ocr  — a born-digital PDF rendered to pixels at the OCR profile and OCR'd against its
#               KNOWN text layer. Genuinely independent (the pixel path shares nothing with the
#               text-layer path), free, and large. Reported PER DEGRADATION LEVEL L0..L4, never
#               pooled, and the calibration page prints the L4-vs-human gap.
#  agreement  — D4's agree.decode_vs_page. Its own column, headed "Agreement (not accuracy)".
#  self       — driver self-report. Stored, never scored, never ranked. (D4 R12, one level down.)

# eval/degradations.toml — the synth-OCR ladder. NEVER binarize: Ollama-OCR's 72-DPI-then-Otsu
# destroys the antialiasing a modern VLM trained on, and D4 already fixes binarize = false.
#   L0 []  ·  L1 downsample:150->96dpi  ·  L2 +jpeg:q=40  ·  L3 +skew:+-3deg,blur:0.8
#   L4 +jpeg:q=25, blur:1.2, sp_noise:0.005, bleed_through:0.12

# THE DETERMINISTIC SPLIT — leakage is structurally impossible because the split is a pure
# function of the document, not of the run. (D4 R2's shape, reused rather than reinvented.)
def split_of(doc_key: bytes) -> Literal["train", "calib", "test"]:
    h = int.from_bytes(blake2b(doc_key + b"ow-split-1", digest_size=2).digest(), "big") % 100
    return "train" if h < 70 else ("calib" if h < 85 else "test")
```

```python
# ══ omniweave_conform/damage/ — the paired-damage suite. Deterministic. LLM-free. ══
@dataclass(frozen=True, slots=True)
class Damage:
    name: str
    diag_code: str                        # from D2's CLOSED registry — a machine target, not prose
    apply: Callable[[Path, tuple[int, ...]], Path]     # returns a damaged corpus root

DAMAGES = (
  Damage("encrypt",         "OW_ENCRYPTED",              ...),   # re-encrypt the source PDF
  Damage("strip_text",      "OW_NEEDS_OCR",              ...),   # pages 12-40; the code names them
  Damage("stage_timeout",   "OW_TIMEOUT",                ...),   # graphrag's _chaos middleware
  Damage("budget_1micro",   "OW_TRUNCATED_BY_BUDGET",    ...),   # [budget.per_unit] micros = 1
  Damage("drop_part",       "OW_MISSING_PART",           ...),   # delete word/document.xml
  Damage("deny_probe",      "OW_DRIVER_UNAVAILABLE",     ...),   # capability probe refuses
  Damage("downgrade_span",  "OW_ORIGIN_SPAN_DOWNGRADE",  ...),   # a driver declaring origin_span:none
  Damage("rotate_embedder", "OW_INDEX_MODEL_CHANGED",    ...),   # ** NEW CODE — see Risks **
)

def run_damage_suite(corpus, damages, *, answer=None) -> "DamageReport":
    """PHASE 2 (T2, per PR, no serve layer needed, ~60 s):
         for each damage: apply, parse, and assert the expected Diag row lands with the right
         page set and the document status is 'partial'. Metric: degradation_detection == 1.000.
       PHASE 4 (T4, once D9's answer state machine exists):
         for each (query, gold cites) x damage, with the pristine run as the COUNTERFACTUAL:
           answer(q, pristine).state == 'ok'        and cites >= gold
           answer(q, damaged ).state == 'degraded'  and damage.diag_code in causes
           answer(q, damaged ) is NOT a confident empty result
       Causal, not correlational: a system that always says 'degraded' fails the first assertion
       and one that never does fails the second. No model is needed for the STATE assertion, which
       is why the honesty guarantee is cheap enough to gate on rather than expensive enough to
       be moved to nightly, then quarterly, then removed."""
```

```python
# ══ omniweave_conform/runners.py — the competitor seam ══
class Runner(Protocol):
    NAME: ClassVar[str]; VERSION: ClassVar[str]
    TIMING_BASIS: ClassVar[Literal["in_process","spawn_inclusive","server_attached"]]
    def measured_on(self) -> MeasuredOn: ...   # REQUIRED. No tuple, no scoreboard row.
    def run(self, doc: Path, *, out: Path, budget_micros: int) -> "RunnerResult": ...
# Shipped: omniweave · markitdown · docling · pandoc · soffice · unstructured · bm25 · dense · hybrid
# A MISSING runner is skipped with a warning and a recorded degradation (anydoc's rule), never
# silently dropped: a partial setup still produces a usable report.
# The table renderer REFUSES to place two rows with different timing_basis in one column; it
# splits them into separate blocks with the basis in the block header. anydoc got this right in
# prose ("pandoc and LibreOffice include process spawn — that's how they're used in practice, and
# it's called out in the report"); a paragraph does not survive the sixteenth adapter.

# normalize_text is adopted VERBATIM from olmocr/olmocr/bench/tests.py:47-81 — the <br> fold, the
# PAIRED bold/italic regexes, \s+ collapse, NFC, and the twelve-character punctuation map
# including 'µ' -> 'μ'. Comparing markdown vs HTML vs OTSL is impossible without exactly this.
```

```
══ METRICS ═══════════════════════════════════════════════════════════════════════════════
suite      primary (deterministic)                                          never
parse      olmOCR-Bench typed assertions per TestType; text_f1 (char-level, olmocr           an LLM judge
           normalize_text, banded Levenshtein band=5%|ref| cap 4096); structure_f1           as primary
           (greedy matcher in (page,ord) anchored on content_digest equality first,
           then fuzz>=0.90; a pair is correct iff kind AND layer agree; ships a
           kind_confusion matrix — greedy not Hungarian, because O(n^3) at 600k
           blocks is unaffordable and the choice is printed in the report);
           order_acc; table_rel_acc via Grid.up/down/left/right/top_heading/
           left_heading in O(1), REPORTED SEPARATELY FOR has_merges 0 and 1;
           hallucination_rate = 1 - pass rate on ABSENT, NEVER composited;
           furniture_f1; span_exact_rate (a GATE at 1.000, not a metric)
extract    lift's five adversarial categories; exact match with numeric tolerance;           field_acc
           field_acc AND doc_acc, ALWAYS BOTH (Q-G21); verify.grounded_field_frac            alone
retrieve   recall@{1,5,10,20}, ndcg@10, mrr — per channel THEN fused, reported as            a raw
           score/ceiling where ceiling = sum(w)/(k+1) and depends on which channels           un-normalised
           ran; citation_soundness = fraction of returned cites resolving to a live           WRR score
           block whose verify_quote() is 'match' or 'source_ahead' (D2: source_ahead
           is NOT corruption) — computable LIVE on every served response, so it is a
           runtime guarantee and not only an eval statistic
absence    absent_precision · absent_recall · false_confident_zero · degradation_detection   —
roundtrip  import(export(store)) == store; write(read(b)) == b; ppt-master's four            byte compare
           fidelity tiers with an asserted sum; layout_digest equality                       of artefacts
perf       p50/p95_ms_per_unit · peak_rss_bytes · wal_peak_bytes · micros_per_unit ·         wall clock as
           usd_per_1k_units · usd_per_point_over_free_baseline                               a PR gate
portability  LOCOMO(300) + LongMemEval-S(50), QUARTERLY, its own scoreboard section,         a primary
  (not a     graphify's fairness rules asserted not documented, judge kappa >= 0.70          quality gate
   suite)    at n_double >= 100. Field: LOCOMO recall@10 0.497 / QA 45.3% at ~$1.40
             ingest vs supermemory 49.7% at $15.67; LongMemEval-S 76%.
```

```
══ PROPERTY LAWS (T1, hypothesis; the generator produces .owstore states and DocSink call
   sequences, NOT documents — you cannot fuzz your way to a valid DOCX) ════════════════════
P1  import(export(store)) == store over GENERATED stores, not only fixtures        D2 gate 5
P2  write(read(b)) == b over hand-authored FUTURE-version archives                 D2 gate 1
P3  owcheck holds after ANY legal DocSink sequence; a mutation library violating   D2 §11
    each named invariant one at a time yields a SPECIFIC code each time
P4  build_grid never raises; every (r,c) in range resolves to exactly one Origin;  D2 §6
    clamping emits OW_TABLE_SPAN_CLAMPED and forces the table's trust to INFERRED
P5  content_digest is INVARIANT under producer_id, method, trust, quote, score,    D2 digest
    raw_kind, origin_operator, marks, x, revision, ord and every span; and CHANGES   recipe
    under kind, layer, NFC text, payload or any child digest. BOTH DIRECTIONS —
    an invariance-only test passes for `def digest(b): return b""`.
P6  to_text(RenderSpan(v, *offsets_of(b))) == [(b, TextSpan(0, len(b.text)))]      D2 §5
P7  Quad.from_driver: two descriptions of one rectangle (topleft/pt vs             D2 geometry
    bottomleft/px+dpi, any rotation) produce an IDENTICAL Quad; re-applying it
    to the stored frame is the identity
P8  sha256_canonical(coerce(cfg)) survives a TOML round trip; no string coerces    D1 "false"
    to a bool except the four TOML literals; ["a","bc"] != ["ab","c"]                -> True
P9  resolve() over a catalog shuffled 100x returns an identical Resolution         D3-4
P10 rebind: carried + revised + created == |blocks(new gen)|; every retired block  codegraph's
    has a block_history row; an identity re-parse gives created == retired == 0      4.3%
P11 every one of the twelve limits raises OW_RESOURCE_LIMIT{limit} naming the      D1/D3-20
    right knob, and NEVER OOMs, at cap-1 / cap / cap+1
P12 overlapping marks survive serialize -> parse                                   marker's
                                                                                     collapse
```

```
══ THE Q-GATE SERIES (Q-G*, never G17 — D1 owns G1..G16 and both other proposals collided) ══
Q-G1   corpus-licence   every fixture byte has a manifest row {spdx, source_url, retrieved_at,
                        sha256, provenance}; spdx in the allowlist {CC0-1.0, CC-BY-4.0,
                        CC-BY-SA-4.0, MIT, Apache-2.0, OGL-UK-3.0, EUPL-1.2, PD-USGov};
                        contains_pii=true is unrepresentable in a redistributable tier;
                        NOTICE.md generated and --check gated. docling ships 683 files and
                        99 MB under tests/data/ with ZERO licence artefacts. Verified.
Q-G2   fixture-budget   Tier A <= 64 MB; no reduction file > 256 KiB; >= 40% of fixtures/docs/
                        is provenance=public_domain REAL (a synthetic corpus flatters the parser)
Q-G3   golden-bless     a frozen or tracked diff requires a BLESS.log row in the same commit
                        (matching count, git sha, reason >= 20 chars, not in the no-op denylist);
                        > 20% of files needs a second reviewer; test_bless_flag_is_off()
Q-G4   frozen-stability `shape` is byte-identical across two pdfium minors and 9 OS/py cells
Q-G5   counters         exact/ratchet per eval/counters.toml; a delta fails without a bless
Q-G6   verbatim         span_exact_rate == 1.000 on a deterministic sample of n=1000 blocks
                        claiming quote='verbatim'. ZERO tolerance. Needs NO labelled corpus:
                        the predicate is D2's own, so it runs on the user's documents too.
Q-G7   absence          false_confident_zero <= 0.01 · degradation_detection == 1.000 ·
                        citability_violations == 0
Q-G8   measured-on      no eval_metric row without a complete MeasuredOn; unpinned => UNRANKED
Q-G9   truth            a metric whose reference producer == subject producer is refused
                        (OW-Q-002); truth_kind='native_run' only on fidelity metrics;
                        'agreement'/'self' never populate an accuracy column
Q-G10  score-declared   an unregistered score_kind cannot be written; a DECLARED score_kind that
                        nothing ever writes fails the build. Fixture: docling's table_score,
                        assigned only as a document nanmean over a per-page field never assigned
                        anywhere (base_models.py:419; standard_pdf_pipeline.py:867;
                        legacy_standard_pdf_pipeline.py:245) — a published grade computed from a
                        permanently-NaN component. Verified in tree.
Q-G11  separation       ordinal tags: strictly increasing p_hat with non-overlapping adjacent
                        Wilson 95% intervals at n >= 150/bucket/slice, or the slice is
                        `uncalibrated`; two consecutive releases fires the kill condition
Q-G12  sharpness        ECE <= 0.05, Brier <= 0.08, 10 equal-mass bins, n >= 1000, or NULL
Q-G13  freshness        within [calibration] max_age_days = 30; stale =>
                        Degradation(kind="calibration_stale")   (D4's enum member, verbatim)
Q-G14  render           status != 'calibrated' => no digit, no %, no bar, no colour, no grade
Q-G15  perf             counters exact; RSS and WAL absolute; time as a Pacer ratio on the
                        pinned runner, 7-run rolling median, 3 consecutive breaches; UNSTABLE
                        is a third verdict and 3 consecutive UNSTABLE is itself a failure
Q-G16  anti-ratchet     baselines are RELEASE-anchored: vs N-1 at tolerance AND vs N-2 at 2x
Q-G17  gate-rot         every gate row carries owner + review_by; a row past its date fails.
                        There is no --warn-only. A downgrade is a class change in gates.toml.
Q-G18  flake            > 2% failure over 30 days => quarantine to `informational` + an issue.
                        No --rerun-failures in CI: a gate that is rerun has already stopped working.
Q-G19  scoreboard       SCOREBOARD byte-diff gated; every row carries witness, not_measured[]
                        (required, non-empty) and confounders[] (required, non-empty);
                        publishable=false renders `withheld: corpus licence`
Q-G20  judge            an LLM-graded number needs Cohen's kappa >= 0.70 at n_double >= 100 from
                        a SECOND INDEPENDENT judge, published beside it, every verdict citing a
                        verbatim quote. graphify publishes 90.6% / kappa 0.81 (BENCHMARKS.md:16)
                        and notes most memory benchmarks disclose no judge validation at all.
Q-G21  pairing          field_acc never ships without doc_acc; hallucination_rate is never
                        folded into a composite (a system that invents text raises text_recall)
Q-G22  parity           contributor-parity: clean container, NO network, NO gpu, NO node,
                        `uv sync && pytest` green, wall <= 600 s, asserted as a correctness test
Q-G23  self-test        the harness scores a set of DELIBERATELY WRONG outputs (a dropped page,
                        a transposed table, a hallucinated field, an empty result) and asserts
                        the exact expected scores; every generator-backed parametrize asserts
                        it produced >= 1 case (graphify tests/test_architecture_doc.py:44-50 —
                        "a regex that silently matches nothing would make every parametrized
                        test below vacuous"); every damage injector asserts it actually fired
```

```
══ CLI ═════════════════════════════════════════════════════════════════════════════════════
ow eval fetch    <corpus>                    verify per-file sha256; refuse licence="unknown"
ow eval run      --suite parse|extract|retrieve|absence|roundtrip [--corpus C@V] [--slice K=V]
                 [--subject D@V] [--runner R] [--iters 5] [--cassette required|allow|off]
                 [--max-spend 2.00] [--require-slices a,b,c]
ow eval golden   [--corpus C] [--driver D] [--geometry]   exit 0 | 3 frozen | 4 tracked
ow eval bless    --reason "<>" [--corpus C] [--driver D] [--counters] [--perf]
ow eval record   --service S [--only-missing] [--max-spend 1.00]
ow eval calibrate --score-kind K | --trust [--eval-set E] [--local] [--check]
ow eval correlate --channels agree,audit --against human [--slice-by KEY]   # D4's open question
ow eval synth-ocr --corpus C --n 2000 [--levels L0..L4]
ow eval absence  [--damage encrypted,needs_ocr,...]
ow eval verbatim --n 1000                    # Q-G6, zero tolerance
ow eval bench    [--baseline refresh]        # Pacer ratios + absolute RSS/WAL; UNSTABLE is real
ow eval compare  <run-a> <run-b>             # paired p, effect, MDE, per-slice deltas
ow eval lint     [--corpus] [--confidence] [--measured] [--estimates]
ow eval export                               # .oweval -> eval/results/**.json  (committed)
ow eval scoreboard [--check | --bless]
ow eval flakes   [--window 30d]
ow eval doctor                               # what can THIS machine run, and why not
ow eval release-check                        # refuses on ANY unknown tier, slice or calibration
ow doc digest <doc>   ow doc diff <a> <b>    # the Reduction + the RebindReport as review artefacts
```

```yaml
# .github/workflows/ci.yml — added to D1's five jobs. TWO workflow files total, not sixty
# (local-deep-research ships 66 in .github/workflows/; every one was justified).
gates:              {runs-on: ubuntu, py: "3.11"}      # D1 G1..G16 + the static Q-G series  ~3m
test:               {os: [ubuntu,macos,windows], py: ["3.11","3.12","3.13"]}   # T1  ~4m/cell
golden:             {runs-on: ubuntu, needs: gates}    # T2: Reductions + Counters + damage  ~4m
conform:            {runs-on: ubuntu}                  # T3, from a TRUSTED TAG (D3-23)      ~5m
contributor-parity: {runs-on: ubuntu, container: clean, network: blocked}      # Q-G22       ~7m
# .github/workflows/nightly.yml — ONE file, a matrix inside it.
nightly:  jobs: [eval, perf, calibration, conform-full, fuzz]      # T4, gpu-a10g            ~90m
weekly:   jobs: [soak]                                             # T5                      ~3h
# OMNIWEAVE_BLESS is NEVER set in CI. HYPOTHESIS_PROFILE=ci (200, derandomize) on PRs,
# nightly (2000, randomized) at night. --cassette required on every PR job.
```

```toml
# ══ THE D3 AMENDMENT I REQUEST — four required keys on [[quality.benchmark]] ══
# All kit-written like the rest of the block, all inside the existing `attestation`. No new
# tables, no change to compute_tier, resolve(), the wire protocol, or any of D3's 23 invariants.
[[quality.benchmark]]
suite = "omniweave-golden"; version = "2026.09"        # D3's strings, verbatim
corpus_digest = "sha256:c0de…"     # NEW, REQUIRED — binds the row to the corpus BYTES
slice  = "office"
metric = "structure_f1"; value = 0.94
n      = 412                        # NEW, REQUIRED — refused below min_slice_n = 30
ci95   = [0.921, 0.958]             # NEW, REQUIRED — closed-form stratified interval
witness = "self"                    # NEW, REQUIRED — ci | self | third_party
measured_on = { weights="n/a", weights_revision="n/a", runtime="anydoc",
                runtime_version="0.2.4", sampling="n/a", prompt_version="n/a",
                hardware="x86_64-linux 8c/16GiB" }     # `hardware` mirrors [cost].measured_on
# plus D3-24: a row whose corpus_digest does not match a digest in the omniweave release
# manifest is treated as witness="self" regardless of what it declares; a witness != "ci" row
# is DISPLAYED and never RANKED and never read by `route propose`.

# ══ Q-G* ERROR CODES — append to codes.toml under a new OW-Q-* prefix (additive under G13) ══
# OW-Q-001 measured_on incomplete: field '{field}' missing   -> fill it or do not publish
# OW-Q-002 truth reference is the subject's own output       -> set truth.kind and a real reference
# OW-Q-003 golden diff without a BLESS.log row               -> ow eval bless --reason '<>'
# OW-Q-004 cassette miss for {service} key {key}             -> ow eval record --service {service}
# OW-Q-005 counter delta {counter} {old}->{new}              -> ow eval bless --counters --reason
# OW-Q-006 fixture {path} has no .meta.toml row              -> add the row with a licence
# OW-Q-007 spdx '{spdx}' not in the corpus allowlist         -> remove it or amend the allowlist
# OW-Q-008 score_kind '{kind}' declared but never written    -> write it or remove the declaration
# OW-Q-009 trust tiers do not separate: {a}={x} vs {b}={y}   -> fix the tier assignment
# OW-Q-010 gate '{gate}' past review_by {date}, owner {owner}-> review it or extend the date
# OW-Q-011 judge not validated (n_double={n} < 100)          -> ow eval run --validate-judge
# OW-Q-012 fairness violation: {n} '{role}' models resolved  -> pin one model for every role
# OW-Q-013 tier/slice/calibration UNKNOWN at release-check   -> run it or record why
```

```
══ BUILD ORDER — every phase ships something a real user runs ═══════════════════════════════
Q1 (wk 1-3)   fixtures/ + generators + .meta.toml + Q-G1/2 · the reducers + BLESS.log + Q-G3/4 ·
              .oweval schema + normalize_text + eval_assertion · stats/ (closed forms) ·
              the 12 property laws.   USER-VISIBLE: `ow eval run --suite parse --corpus fixtures/`
              prints a per-category pass table. A driver author can measure their driver in week 3.
Q2 (wk 4-6)   Counters + Q-G5 · Cassettes at both seams + Q-G22 contributor-parity · Pacer +
              eval/perf.toml + the pinned runner · damage injectors + the PHASE-2 Diag assertions
              (no serve layer needed) · deep goldens + diff_deep on rebind().
              USER-VISIBLE: a PR that silently re-renders every page goes red, with the counter named.
Q3 (wk 7-10)  omniweave-golden 2026.09 (~600 docs, ~8,000 assertions) + the review app (olmocr's
              review_app shape with `checked` IN the record) · both evaluators · Runners ·
              corpora/*.toml + publishable · extract suite (field AND doc) · Q-G6 verbatim ·
              scorekinds.toml + synth-ocr + calibrate + Q-G10..14.
              USER-VISIBLE: the first public scoreboard — mostly UNKNOWN, and honest about it.
Q4 (wk 11-14) retrieve suite + citation_soundness · the PHASE-4 paired-damage assertions once D9
              lands · judge + Q-G20 · ow eval correlate (settles D4's open question) · holdout
              slices · portability (LOCOMO/LongMemEval) quarterly · T5 soak + fuzz.
              USER-VISIBLE: `ow eval absence` proves the framework's cheapest differentiator.

COST, STATED PLAINLY
  ~14 engineer-weeks for one senior engineer to the first public scoreboard, plus a standing
  ~0.3 FTE (corpus curation, assertion review, weekly flake triage, quarterly calibration and
  judge refresh — a NAMED ROLE WITH A ROTA, because D3 already learned an unstaffed registry
  degrades to unverified cards), plus ~2 person-weeks of human labelling per 1,000 assertions,
  which is the number that actually bounds corpus growth and is why the corpus is 600 documents
  and not 6,000.  CI: PR wall clock ~10 min with the jobs in parallel; nightly ~90 min.
  MONEY: one pinned perf runner (~$40/mo or a spare workstation — the single non-negotiable
  operational cost) plus a nightly A10G-class box; billed suites capped IN THE HARNESS at
  --max-spend, budget $150/mo. REPO: <= 64 MB fixtures, ~8 MB cassettes, ~25 MB of plain-text
  goldens. No git-LFS, no vendored corpora. .oweval ~200 B/verdict, swept to ~1 GB steady state.
  ZERO new runtime dependencies: blake2b, statistics, sqlite3, tomllib are stdlib; the
  Levenshtein is a 40-line DP; pytest and hypothesis are already in D1's dev group; numpy is
  permitted in the nightly job's optional plotting and NOWHERE a gate can reach.
```

## Rationale

**Why a schema and not a test suite.** The three questions that decide whether omniweave is
trustworthy in year three — *when did this regress*, *is that difference real*, *does the confidence
tag mean anything* — are historical, and none can be answered retroactively from console output.
Every repo in the collection paid this: docling computes four page scores and consumes none of them,
and one of the four is structurally `NaN` while a published EXCELLENT/GOOD/FAIR/POOR grade is derived
from it. Six tables in a separate `.oweval` file is the cheapest structural insurance in this design.
`.oweval` rather than the systems proposal's tables inside the corpus `.owstore`, because eval rows
are deleted while corpus rows are not, one eval run spans many stores, and the systems proposal
flagged the WAL contention as its own unresolved question.

**Why the golden differ is `rebind`, and why the deep golden is an exploded archive.** Snapshot
testing a large noisy parser *is* the question "which blocks are the same block after a re-parse," and
D2 already had to answer it with a specified three-rule matcher, a per-page match rate and a
quarantine threshold. Building a second differ puts two implementations behind one semantics, which is
the failure D1 spent its whole ruling avoiding. But `rebind()` needs two generations in a store, and
the systems proposal's `.owsum`-only golden cannot supply the old one after an upgrade — so a bounded
deep set of committed `.owdoc.d/` directories is load-bearing, not a luxury. Exploding the archive
(zstd off) buys git delta-compression, `jq`, and exactly the inspectability D2 paid a measured 4%
size penalty to get.

**Why volatility tiers, and why three reductions rather than one.** The ecosystem architect is right
that a golden which jitters is a golden people delete, and the `frozen`/`tracked` split is the
mechanism. But one reduction cannot serve both a 3-page fixture and a 5,000-page one: `shape` alone
cannot localise, and `outline` at 400,000 lines cannot be read. The per-page tier is the systems
proposal's `.owsum` and it earns its place between them. I cut the ecosystem's fourth,
`informational` text reduction: it never gates, it is the largest and noisiest file, and its stated
purpose is served by re-running the serializer.

**Why counters lead the regression hierarchy.** This is the ecosystem architect's strongest
contribution and it beat both alternatives outright. The four failures I most fear — a driver upgrade
silently re-rendering every page, a router computing a `LOCAL_COMPUTE` signal on a clean born-digital
PDF, a cache-key change turning 100% hits into 100% misses (graphrag shipped exactly this,
permanently and silently), a free operator re-billing a paid one — are all exactly countable and all
invisible in timing noise. D4 already writes one of them as a test; generalizing the mechanism costs
one module. Timing then only has to carry what counters cannot, which is why a Pacer ratio on one
pinned runner with a rolling median is sufficient rather than heroic.

**Why closed-form statistics.** olmOCR-Bench is the best-designed benchmark in the collection and its
published CIs and p-values do not reproduce: `np.random.choice`/`shuffle` at
`olmocr/bench/utils.py:33,55,120,172` and `random.sample` at `benchmark.py:262`, with no `seed`
anywhere in `olmocr/bench/`. The sign-flip permutation test has an exact closed asymptotic
(`p = 2(1 − Φ(|Σd|/sqrt(Σd²)))`), the stratified macro interval has one too, and using them removes
the seed question rather than answering it — while keeping numpy out of a gate path D1's core-purity
logic says must be installable in a clean environment.

**Why calibration is an admission gate with a written kill condition.** A confidence tag that has
never been measured is worse than no tag, because an agent will condition on it. But the systems
proposal's rule alone produces "uncalibrated forever," which is a slow social failure. The
pragmatist's kill condition is the missing half: after two consecutive releases without separation the
tag is *deleted* — the card goes `confidence = "none"`, the runner writes `trust = AMBIGUOUS`, and
D2's `block_review` partial index then correctly selects everything from that driver, which is the
truth. And I added the clause neither proposal stated: **an uncalibrated ordinal remains usable as an
internal filter and sort key.** Without it, day one — when almost everything is uncalibrated — deletes
the review surface along with the badge.

**Why the paired-damage suite is the highest-leverage new mechanism.** The graph digest names the
absence contract *"a framework invariant, not a tool feature"* with *"no counterpart anywhere,"* lists
six omniweave hazards that are *"currently a silent zero in every RAG system,"* and records the
consequence — a user got confident zeros over ~1,975 unindexed files and left. Everyone agrees it
matters; nobody proposed a way to *test* it. Injecting one `Diag` code at a time with the pristine run
as the counterfactual is a causal test, it needs no model for the state assertion, and it therefore
costs ~60 s per PR. A guarantee cheap enough to gate on survives; one that costs an hour of GPU gets
moved to nightly, then quarterly, then removed. I split it so the half that needs no serve layer
(the `Diag` assertions) ships in week 6 rather than waiting on D9 — a sequencing error in the systems
proposal's own build order.

**Why the corpus is a data artifact and no distribution is added.** D1 fixes eleven distributions and
says amending the list amends D1. A 240 MB corpus wheel breaks G2, breaks G5 the moment it carries a
date version instead of `RELEASE`, and exceeds PyPI's default per-file limit — and the ecosystem
proposal's own failure mode 12 concedes it "papered over" the cadence problem. Installing by digest
into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` reuses D1's toolchain pattern verbatim, including
the rule that a digest mismatch is permanent and never triggers a fetch. Keeping the harness inside
`omniweave-conform` costs nothing: it already exists, already depends on pytest, and is already the
distribution a third-party driver author installs.

**Where I corrected a proposal's headline claim.** The ecosystem architect's most-defended
contribution is that native OOXML text is "free exact truth" for office parsing, generating tens of
thousands of labels at zero cost. It is not — not for the thing it is used for. A reference produced
by walking `w:t` is algorithmically dependent on the same branch selection the subject driver
performs: anydoc handles `mc:AlternateContent` (`src/formats/docx/content.rs:146`, and `:719-726`
skips `mc:Fallback` "so AlternateContent shapes aren't collected twice"), `w:sdt` (`:169`),
`w:instrText` (`:536`), `w:txbxContent` (`:726`) and separate footnotes/endnotes parts
(`mod.rs:62-63`). An independent walker either re-implements that logic — in which case it is
self-anchored, the anydoc trigram flaw one level down, and the ecosystem's own `reference.producer ==
subject.producer` guard does not fire — or it does not, in which case it *disagrees with the correct
answer* and scores true positives as parser errors. So `native_run` truth is admitted for **fidelity
only** (do the extracted characters equal the source run's characters — which is D2's `verify_quote`
generalised) and is refused for recall, coverage and classification by Q-G9. Source B, synthetic OCR
against a known text layer, survives intact: the pixel path genuinely shares nothing with the
text-layer path, and it is adopted with the degradation ladder and the L4-vs-human gap published.

**And one proposal flagged a conflict that is not one.** The ecosystem architect argues D3 cannot both
have kit-written `[quality]` and a five-minute mandatory tier. D3 says *the mandatory tier* runs in
five minutes and lists eleven honesty suites; it never places `[[quality.benchmark]]` inside that
tier, and D3-13's publish gate rejects *author*-written values, which a second tool is not. The
natural reading — eleven suites in the mandatory tier, benchmark rows from a longer non-mandatory run
— is consistent, and it is what I ship as suite twelve. A spurious conflict is not free: it consumes a
charter triage slot that a real one needs.

## Rejected

- **A new `omniweave-eval` distribution plus five `omniweave-corpus-*` wheels (ecosystem)** — a 240 MB
  wheel breaks D1's G2 aggregate reading, a date-versioned corpus breaks G5's single-`RELEASE` rule,
  and PyPI's default 100 MB per-file limit blocks it outright. The proposal's own failure mode 12
  concedes the cadence problem is "papered over." A digest-installed data artifact in
  `$OMNIWEAVE_HOME` reuses a pattern D1 already ruled and costs nothing.
- **Eval tables inside the corpus `.owstore` (systems)** — the proposal itself flags the WAL
  contention between a nightly bench write and a bulk index as an unresolved question. Eval rows are
  deleted, corpus rows are not, and one eval run spans many stores. `.oweval` is a separate file.
- **A separate `.geom` geometry golden with its own tolerance comparison (pragmatist)** — D2 quantized
  `layout_digest` to whole points *precisely so* geometry does not need a tolerance ladder. Keeping
  one re-introduces the machinery D2 designed away and hides whether the quantization actually works.
  Geometry lives in `layout_digest` inside `outline`, its absence from `shape` is gated (Q-G4), and
  the per-corner comparison survives only as a diagnostic flag.
- **The `text` / `informational` reduction tier (ecosystem)** — a golden that never gates and is the
  largest, noisiest file is a golden nobody reads and everybody re-blesses. Cut.
- **Whole-document `.owdoc` blobs as the general committed golden (the obvious choice)** — D2's own
  arithmetic makes a 5,000-page golden ~200 MB and unreviewable, and it re-blesses on every geometry
  patch. Bounded to 24 documents at 40 pages where the semantic diff is affordable and worth having.
- **`.owsum` alone as the golden, with `ow doc diff` on demand (systems)** — you cannot re-parse at the
  old driver version after you have upgraded, so "on demand" has no old side. This is a real hole in
  the systems design and the deep set closes it.
- **A single composite quality score** — one number is what makes a benchmark gameable and a regression
  un-actionable, and it would let a hallucinating driver raise `text_recall` and offset a
  `hallucination_rate` collapse. Hallucination is reported alone, `span_exact_rate` is a hard gate,
  and `field_acc`/`doc_acc` are always printed adjacent because 90.2 and 20.9 are the same system.
- **Native-XML text as general ground truth (ecosystem)** — refuted above with file:line evidence;
  admitted for fidelity only.
- **LLM-judge-only evaluation, and its symmetric error, deterministic-only evaluation** — a judge as
  the primary mechanism makes every quality claim depend on weights that change under you, which is
  the HunyuanOCR failure. Deterministic-only cannot measure "did the summary say the right thing,"
  which is half of what an agent framework does. Deterministic anchors first; a judge only where none
  exists, and then only with published κ ≥ 0.70 at n_double ≥ 100.
- **Quoting upstream README numbers** — `grep -rn "revision=" marker/ surya/ lift/` returns zero, so
  the benchmarked checkpoint is unidentifiable; marker's headline needs `--use_llm`, which egresses
  page images to Gemini by default; HunyuanOCR's 94.10 was TensorRT against a repo shipping
  Transformers and vLLM, which it admits disagree. We run every comparison ourselves or we print the
  quote *and* the reason it cannot be reproduced.
- **Wall-clock as a PR gate, and its opposite, no timing gate at all** — shared runners vary 2-3×, and
  a gate that fails on Tuesdays teaches rerun. Counters carry the PR signal; timing runs nightly on one
  pinned machine with a Pacer validity check and a rolling median.
- **`--warn-only`, `--rerun-failures`, a global `--force`, or coverage percentage as a gate** — D1 names
  `--warn-only` as *the* social failure mode of its own scanner; a rerun-until-green flag is a gate that
  has already stopped working; coverage measures which lines ran, not which invariants hold. Overrides
  are named per check (`--allow-golden-drift`, `--allow-uncalibrated-score`, `--accept-stale-baseline`).
- **Defining `serve_event` DDL and mining it here (pragmatist)** — D9 owns the response envelope and D5
  owns store layout, and a table holding raw query text is a privacy surface neither this decision nor
  this author should design. D10 places two named obligations on D9's telemetry instead (below) and
  computes metrics over whatever D9 defines.
- **A hosted eval service, dashboard app or results database** — a second product with uptime, auth and
  a key rota, and an artefact nobody can fork or diff. Same reasoning D3 used against a hosted registry.
- **A twelfth CI gate series numbered `G17` (both pragmatist and ecosystem, colliding)** — D1 owns
  G1..G16 and both proposals independently claimed G17 for different gates. The `Q-G*` prefix makes a
  collision unrepresentable.

## Consequences

- **D3 must accept four required keys on `[[quality.benchmark]]` and one new invariant D3-24.** Kit-
  written like the rest of the block, inside the existing attestation, no change to `compute_tier`,
  `resolve()`, the wire protocol or any of D3's twenty-three invariants. Without them a benchmark row
  cannot be regression-gated, compared, or honestly displayed.
- **D3 gains a twelfth conform suite, `quality`, explicitly NON-mandatory.** `attested` requires the
  eleven honesty suites and **zero** benchmark rows: D3's bar is the honesty of the descriptor, and a
  driver with no quality prior is still admissible and routable, discovering its quality through D4's
  `agree` channel and audit lane with `UNKNOWN` as the zero value.
- **D9 inherits three obligations.** (1) Every confidence value crosses the serve boundary inside
  `Calibrated`, and the renderer consumes `status`, never the float. (2) Its telemetry rows carry
  `producer_version INTEGER NOT NULL` (so a labelling fix can be bounded by version instead of by 130
  lines of trust heuristics) and, beside any truncated id list, a true-count companion (`returned_n`)
  — without it a stored 50 means "50" or "500" and no analysis can exclude the truncated rows.
  (3) The four-state answer contract is measurable: `absent` must be reachable, distinguishable from
  `degraded`, and each of the injected `Diag` codes must surface as a named cause.
- **D2's `Diag` registry gains one appended code, `OW_INDEX_MODEL_CHANGED`** — the "embedding model
  changed since indexing" hazard the graph digest names has no code, and the registry is append-only,
  so this is additive.
- **D5 must expose `wal_peak_bytes` and a bulk-index counter set**, because the recorded failures are
  memory failures and Q-G15's most important budgets are absolute WAL and RSS.
- **D4's open question about `agree.decode_vs_page` gets a named deliverable**, `ow eval correlate`,
  and until it reports, `auto_demote` continues to accept `audit` verdicts only.
- **D1's eleven distributions and sixteen gates stand unamended.** The Q-G series is additive; the
  `OW-Q-*` code prefix is an append to `codes.toml` under G13's existing rule.
- **A per-file licence row is friction on the most casual contribution there is.** Adding a repro
  document now requires provenance. Mitigated by making most fixtures generated (a generator needs no
  licence), and by naming US federal works as the sanctioned source of real hard documents — but a
  contributor with a genuinely broken customer PDF hits a wall, and that is deliberate.
- **Cassettes make a prompt change maintainer-gated.** A contributor with no GPU and no API key cannot
  re-record. The error message names the exact command, a `needs-cassette` label plus a
  `workflow_dispatch` recording job that writes back to the PR branch turns a two-day round trip into
  twenty minutes, and CONTRIBUTING says so plainly rather than pretending otherwise.
- **On day one the scoreboard is mostly `UNKNOWN` and most confidence tags read `(uncalibrated)`.**
  That is the truth, it is the same choice D4 made, and it fills in visibly — which is itself the
  adoption story. It also means we look worse than competitors who are not honest, and the only
  mitigation is explaining the competitor's number in the same table.

## Risks

- **UPSTREAM CONFLICT: `_plan/_notes/rulings/D3-drivers.md` — `[[quality.benchmark]]` cannot carry a
  gateable number.** The card's shape is `metric = "structure_f1"; value = 0.94` plus `measured_on`,
  and D3-13 rules *"Publish gate rejects author-written values; the loader recomputes `attestation`;
  `attested = false` ⇒ never auto-selected."* Two defects follow. (1) `attestation` is a hash over the
  card computed by the same kit run that wrote the values, so an author running
  `omniweave conform --bench` against a locally modified copy of `omniweave-golden 2026.09` gets
  `structure_f1 = 0.99` with a perfectly valid attestation and D3-13's loader check passes;
  `version = "2026.09"` is a *string* and binds nothing to the corpus bytes. This is the same class of
  defect as the HunyuanOCR case D3-14 exists to prevent, one level down. (2) `value = 0.94` has no `n`
  and no interval, so a driver measured on 12 documents and one measured on 1,200 are
  indistinguishable, and no guard can fire. **Minimum amendment:** four required kit-written keys —
  `corpus_digest`, `n`, `ci95`, `witness` — inside the existing attestation, plus invariant D3-24 as
  written in Concrete shape. Nothing else in D3 changes and the kit already computes all four.
- **UPSTREAM CONFLICT: `_plan/_notes/rulings/D3-drivers.md` — `[capability.parse]` cannot express the
  claim the conformance suite must test.** D3's vocabulary is exactly *"`spatial · charspan ·
  reading_order · sections · tables · math · assets · notes · confidence · furniture · round_trip`"*,
  and D3-12 rules *"A card claim is a test, in both directions. Conform `capability` derives
  assertions from the card; `false`/`none`/`[]` is asserted absent."* D2 rules a strictly larger
  `Capabilities` set and makes three of the extras load-bearing — `origin_span` (*"gates serve's
  byte-exactness claim"*), `spanmap` (*"a serializer that cannot emit one declares `spanmap: false`,
  and its output MAY NEVER BE CITED"*) and `marks` — and states the enforcement: *"`origin_span='exact'`
  is proved by `normalize_k(part_bytes[a:a+len]) == block.text`. That test is the only mechanism here
  that makes a third party's honesty machine-checkable."* Under D3's own rule that an unknown key
  inside `[capability.<port>]` is ignored with a `CARD_CAPABILITY_UNKNOWN` degradation, a driver
  writing `origin_span = "exact"` has written a comment. **Minimum amendment:** three additive keys
  (`origin_span` ordered `none < normalized < exact`; `spanmap: bool`; `marks: bool`) plus renaming
  D3's `charspan` to D2's `text_span` so the card and the `Capabilities` dataclass are one field.
  D3's own asymmetry rule makes this free — an unrecognised capability can only make a driver look
  less capable. **Mitigation if the charter declines it:** the *output-side* gate still works, because
  Q-G6 tests `Doc.verify_quote()` against the store rather than against the card. What is lost is the
  driver-honesty half — a driver could claim byte-exactness and be caught only by a corpus run instead
  of by its own conformance report.
- **The corpus becomes the model.** Six months of tuning against `omniweave-golden 2026.09` overfits to
  600 documents while the scoreboard rises and real-world quality does not. The 15% holdout with a
  >5-point ⚠, the production-side `agree.decode_vs_page` channel, and the audit lane all help; none
  fixes it. This is the most likely way the design fails and I do not have a complete answer.
- **The input that breaks this design: a 4,000-page mixed PDF with 3,999 clean pages and one scanned
  exhibit from a producer family the corpus does not contain.** Its `outline` is suppressed and its
  `shape` is dominated by the 3,999 free pages, so a regression on the one escalated page is a delta
  of 1 against a baseline of 4,000 and reads as noise; no calibration slice covers its producer family,
  so every score on it is `bootstrap`. Partial answers: per-slice counters (`escalations` and
  `page_renders` move by 100% on that page) and per-slice calibration status in the envelope. The
  honest statement is that this design measures *corpora* well and measures *one pathological
  document* badly, and that is the document a customer sends on day one.
- **A high-value document class that is 0.5% of the corpus and 90% of the business value.** A rate
  schedule, a covenant table, an invoice total: deterministic sampling puts ~1 case in the audit, every
  aggregate stays green, and per-field confidence looks fine because the VLM is confidently wrong. D4
  names this hole exactly. The only honest remedy is that the audit sampler must be stratifiable by a
  user-declared document class with a minimum n per stratum, and the documentation must say omniweave
  measures aggregates and the customer must name their high-value classes.
- **Assertion rot.** A `verified` assertion that was wrong at authoring time is permanently wrong and
  silently caps the metric. `checked` in the record, a review app, and olmocr's `--output_failed` batch
  are the mitigation, and they depend on someone opening the review app.
- **The exact counter gate will annoy people, and the bless will become a reflex.** If the bless rate
  exceeds ~1 per 10 PRs the gate is mis-specified and the counter moves to `ratchet`. At forty blessed
  files nobody reads the reasons; the `frozen` tier is the real defence because it is small and changes
  rarely, and this mechanism will decay before anything else here does.
- **Calibration is corpus-local and we will be blamed for it.** ECE ≤ 0.05 on our documents says
  nothing about an 80%-Thai corpus, heavy typeset mathematics, or 1970s typewriter scans.
  `ow eval calibrate --local` lets an operator refit and register their own eval set and the envelope
  names which set produced the number; the shipped default will be miscalibrated for somebody on day one.
- **Q-G11's separation rule will de-surface real signals early.** With three trust buckets and n ≥ 150
  per bucket per slice, the `AMBIGUOUS` bucket will be under-populated in most slices for a long time.
  The internal-filter clause keeps the review surface alive; the badge stays dark.
- **The deep golden re-blesses catastrophically on a re-segmentation.** A driver upgrade that re-splits
  paragraphs produces a `RebindReport` with hundreds of thousands of created and retired blocks, and
  the bless is unreviewable. `ow doc diff --full` groups retirements by `(page, kind)` and prints the
  top 20 patterns so a reviewer sees "every paragraph on every page was re-split" — it is still a bad day.
- **`UNSTABLE` becomes the normal verdict** if the pinned runner is shared or moved to a hosted VM, and
  the social pressure is to raise `instability_pct` and thereby delete the gate.
- **`.oweval` and `eval/results/**.json` are two stores of one truth.** `ow eval export` is the only
  writer of the second and Q-G19 byte-diff gates it, but a divergence is possible and would be silent
  until someone re-ran the export.
- **A self-hosted CI can set `witness = "ci"`.** The scoreboard therefore only accepts `ci` rows
  produced by omniweave's own workflow identity, which means third-party drivers can never be ranked
  on our board without us running them. That is a governance cost, not a technical fix.
- **`omniweave-conform` is dev-tier and is therefore tested less rigorously than runtime code.** Q-G23
  (score deliberately-wrong outputs, assert exact expected scores) is the defence; the scoreboard
  generator is gated only by its own byte-diff `--check`.

## Terminology

- Reduction := a deterministic, sorted, LF-normalised line-oriented projection of one document out of an `.owstore`, in exactly three kinds — `shape` (per-document counters, no text, no per-corner geometry), `pages` (one line per page), `outline` (one line per block, suppressed above 500 pages).
- Volatility tier := a Reduction's CI treatment. `frozen` — a byte diff fails the build. `tracked` — a diff renders into a PR comment and merges only with a blessed reason.
- Deep golden := the exploded, uncompressed `.owdoc.d/` archive committed for at most 24 documents of at most 40 pages each, so that `rebind()` has two real generations to match. The only committed artefact from which a semantic diff can be produced after a driver upgrade.
- Assertion := one ground-truth claim about one document, in olmOCR-Bench's record shape, carrying `checked ∈ {verified, rejected, NULL}`, `evaluable_in ∈ {owdoc, text, both}`, an optional D2 `addr`, and `derived_from_sha256`. A `checked IS NULL` assertion runs and never scores, and the excluded count is printed.
- `omniweave-golden` := the redistributable Tier-B evaluation corpus. A versioned data artifact, never a Python distribution; installed by digest into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` and re-verified on every use.
- `corpus_digest` := sha256 over the sorted `(relpath, sha256)` pairs of a corpus, NUL-framed. The identity a benchmark row, an eval run and a calibration curve bind to.
- `publishable` := a corpus-manifest boolean, independent of `redistribute`, stating whether that corpus's numbers may reach the public scoreboard. `false` renders the cell as `withheld: corpus licence`.
- Witness := who produced a number — `ci` (omniweave's own workflow on the published corpus), `self` (the subject's author), `third_party`. Only `ci` rows are ranked. This is the single name for the concept; there is no "provenance class".
- `MeasuredOn` := the frozen, defaultless reproduction tuple required on every published number: weights, exact `weights_revision`, runtime, runtime_version, sampling, prompt_version, hardware, corpus, `corpus_digest`, harness_version.
- `timing_basis` := `in_process | spawn_inclusive | server_attached`, required per Runner. Two rows with different bases may never share a column.
- Counter := a named, exactly-reproducible integer harvested from the run manifest, `route_spend` and `driver_observation`, gated `exact` (±1 fails) or `ratchet` (never worse than baseline + tolerance) per `eval/counters.toml`.
- Pacer := the fixed, dependency-free in-repo CPU workload (blake2b over 64 MiB, a 2M-iteration integer loop, 200k SQLite insert+select) run immediately before and after a timed measurement; every time budget is a ratio to it. Disagreement above 15% between the two readings yields `unstable`. Never confused with Calibration, which is about confidence.
- Budget := an absolute floor on a metric. Its breach means we shipped something worse than our published promise, and it is owned by the product.
- Guard := a delta against release N−1. Its breach means this change made it worse, and it is owned by the PR author. Fires only at paired `p < 0.01` **and** effect ≥ MDE, where MDE (minimum detectable effect) is `2 × se(headline)` at the corpus's current size, recomputed at every corpus release and never guessed.
- `GateStatus` := `pass | fail | unstable | stale | unknown`. `UNKNOWN` is the zero value: never a pass, never silently dropped, and `ow eval release-check` refuses on it. There is no `pass_with_warnings`.
- `Calibrated` := the wrapper every confidence value crosses the serve boundary inside, carrying `status ∈ {calibrated, bootstrap, uncalibrated, stale}`, the bucket's empirical accuracy, its Wilson interval, `n`, `eval_set_id` and `slice_key`. A non-`calibrated` status forbids rendering any number, percentage, bar, colour or grade, and permits internal filtering and sorting.
- `TruthKind` := the provenance of a metric's reference — `human | rendered | native_run | synth_ocr | agreement | self`. `native_run` is admissible for fidelity metrics only; `agreement` and `self` may never populate an accuracy column.
- Damage := one injector paired to exactly one D2 `Diag` code, applied to a pristine corpus with the undamaged run as the counterfactual. The paired-damage suite is the causal evaluation of the absence contract.
- Cassette := a content-addressed, replayable request/response log recorded at `DriverIO.service()` and `omniweave_core.modelserver`, the only two outbound model channels a driver has. `--cassette required` in CI; a miss is `OW-Q-004` and never a live call.
- Portability suite := LOCOMO and LongMemEval-S, run quarterly as cross-referenceable adapters in their own scoreboard section. Never a gate, never a primary quality metric.

## Open questions

- **How many documents does a slice need before `trust` separates?** Q-G11 sets n ≥ 150 per bucket per slice from a Wilson calculation at p ≈ 0.90 vs 0.96, but the real requirement depends on the empirical spread between adjacent tiers, and the `AMBIGUOUS` bucket is rare by construction. Settled by running `ow eval calibrate --trust` on the 2026.09 corpus and reading off the smallest n at which the two gaps clear: that number sets the corpus growth plan and tells us how many slices will read `(uncalibrated)` in v1.
- **Does whole-point quantization actually absorb driver geometry jitter, and is `layout_digest` therefore a usable golden key?** D2 leaves this open and Q-G4 depends on it. Settled by the `shape`-stability run across two pdfium minors and two layout-model revisions over the same 500-page fixture, plotting the per-corner delta distribution. If the 99th percentile exceeds half a point, geometry goldens fall back to the tolerance comparison on every run and a `digest_recipe` bump is required.
- **Is `agree.decode_vs_page` a good enough calibration label for `block.trust`, or only for `garble.p_bad`?** It is free and abundant and biased to the escalated population. Settled by `ow eval correlate` measuring, per slice, the divergence between `agree`-derived and audit-derived `p_hat` where both exist; if they differ by more than one Wilson width, `trust` needs corpus labels and the free channel is good only for the router. This is D4's own open question and it is a named phase-4 deliverable here.
- **How large is the synth-OCR L4-vs-human gap, and is the synthetic label source worth its build cost?** A rasterized born-digital page has no bleed-through, no feeder skew and no scanner-specific ringing, so the degradation ladder only approximates. Settled at Q3 by fitting a curve per level and against the 2,400-block human `scan-degraded` slice and publishing the gap; if it exceeds one Wilson width at L4, synth-OCR is demoted to a *smoke* signal and the human slice must grow.
- **What is the real blocks-per-page envelope, and does it invalidate the `pages` reduction's size claim?** D2's 60–120/page is an estimate. `pages` at ~220 B/page is insensitive, but the `outline` 500-page suppression threshold, the corpus storage projection and the `min_slice_n` arithmetic are not. Answered by the same `gen-5000p.pdf` run D2 already specifies.
- **Do we run the portability suite against `mem0` and `supermemory` ourselves, or quote graphify's numbers?** Running them costs a proxy, two self-hosted services and ~$20 of ingest per full sweep; quoting inherits graphify's fairness rules without inheriting its verification. Decided by whether we can reproduce graphify's own row for graphify within its stated interval on the first attempt.
- **Can a hand-maintained `schema_version` be mechanically defended, and does that check belong in the `quality` suite or D3's `card` suite?** D3 raises the question and the kit can diff a driver's output across two tagged versions. Settled by running that diff against two real tagged versions of anydoc and olmocr and measuring the false-positive rate on legitimately nondeterministic drivers; if it is low the check goes in the `quality` suite as a `schema_version_honest` assertion.
