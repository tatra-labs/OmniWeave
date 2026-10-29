# 13 — Quality, Testing and Evaluation

**In one paragraph.** Evaluation is a data model with a publishing gate, not a CI job: every number
omniweave shows a human, an agent, a router or a scoreboard is a row in one `.oweval` file carrying
`(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)`, produced by an RNG-free harness in
`omniweave-conform`. Testing is six budgeted tiers plus a `contributor-parity` job that proves
`uv sync && pytest` is green offline, GPU-free and Node-free under ten minutes — affordable because
Cassettes intercept the only two outbound model channels a Driver has. Parser goldens are never document
snapshots; they are three Reductions plus a Deep golden whose only differ is `rebind()`. Regression is
gated in a strict hierarchy — exact Counters, then absolute memory, then time as a Pacer ratio — and the
rule the whole document exists for is that **a confidence signal that has not passed separation,
sharpness and freshness in the current release is stored, usable as an internal filter, and may never be
rendered as a number, a percentage, a bar, a grade or a colour.**

This document expands charter §D10 and the Q-G series. It is subordinate to
[`_notes/charter.md`](_notes/charter.md) and [`_notes/terminology.md`](_notes/terminology.md). It owns
the pyramid and its budgets, the golden corpora and their licensing, the `.oweval` harness and its
retention, the accuracy and performance regression gates, the twelfth conformance suite (`quality`),
retrieval and absence evaluation, calibration of every user-facing confidence surface, generation
evaluation and the public scoreboard. It does **not** own the response envelope
([07](07-store-and-retrieval.md)), the Port contract or the eleven mandatory conformance suites
([04](04-driver-system.md)), the OUT gate machinery ([09](09-generation.md)), the CI workflow files or
the `eval/` directory's place in the tree ([11](11-repo-layout.md)), or the performance model whose
budgets it measures ([12](12-performance.md)). Where it needs something from another layer it names the
obligation and stops.

## 1. What "it works" means, decomposed into four claim classes

Every assertion omniweave makes about itself falls into exactly one of four classes, and each class has
a different instrument, a different failure mode and a different licence to publish. Conflating them is
the most common defect in the mined collection.

| class | the claim | instrument | may be published as | failure mode when conflated |
|---|---|---|---|---|
| **contract** | "this code obeys its own declared shape" | T0-T3: gates, property tests, Reductions, the twelve conformance suites | pass/fail only, never a score | a driver over-declares and the card becomes fiction (DataFlow's 171 hand-written `get_desc(lang)` strings with nothing comparing them to `inspect.signature(run)`) |
| **fidelity** | "the extracted bytes equal the source bytes" | `Doc.verify_quote()`, `span_exact_rate`, the R1-R7 round-trip laws | a **hard gate at 1.000**, never a metric | a byte-exactness claim degrades into an accuracy percentage and nobody notices it fell |
| **accuracy** | "the structure we recovered matches ground truth" | T4 suites against a licensed corpus with `TruthKind ∈ {human, rendered, synth_ocr}` | a number with `(n, ci95, method, MeasuredOn, witness)` | `native_run` or `agreement` populates an accuracy column and the number measures self-consistency |
| **honesty** | "when we do not know, we say so" | the absence corpus, the paired-damage suite, calibration | a rate with a ceiling (`false_confident_zero ≤ 0.01`) and a hard gate (`degradation_detection == 1.000`) | an uncalibrated float reaches a renderer and the product ships a confidence bar that means nothing |

Two consequences, stated before the mechanism.

**Fidelity is not accuracy, and it is cheaper.** `quote == VERBATIM` is self-verifying against the user's
own bytes: the block text either equals the retained slice on the branch its `os_kind` selects or it does
not (INV-10). That needs no corpus, no labels and no model, which is why `span_exact_rate` is a **hard
gate at 1.000** in `eval/gates.toml` rather than a score with a floor. The same reasoning makes
`agree.decode_vs_page` free — when a part escalates you have already paid for two independent readings,
so the normalised edit distance between them costs nothing — and the same reasoning forbids it from ever
populating an accuracy column (`TruthKind = "agreement"`, `Q-G9`).

**Honesty is gated harder than accuracy.** `structure_f1` has a floor of 0.90 on `office/*`;
`degradation_detection` has a floor of **1.000** and `citability_violations` a ceiling of **0**. A parser
that misses a table is a quality problem. A parser that misses a table and reports a confident zero is a
correctness problem, and the second blocks a release outright.

## 2. The test pyramid

Six tiers plus parity. The times are budgets in `eval/perf.toml`, gated on the pinned runner; the counts
are the release-1 floor, ratcheted by `Q-G24` so a test cannot silently disappear.

```text
tier    name             content                                       count      budget    trigger
─────────────────────────────────────────────────────────────────────────────────────────────────────
T0      gates            the G series + static Q-G series + semgrep    29+12+1    <= 3 min  every PR
T1      unit + property  3,310 unit + 258 hypothesis properties        3,568      <= 4 min  9 cells
T2      golden           Reductions + Counters + Cassette replay        612       <= 4 min  every PR
                         + the DETERMINISTIC HALF of the absence suite
T3      conform          the twelve suites x 15 driver subjects        1,452      <= 5 min  every PR
T4      eval             seven suites, five with live models             -        <= 90 min nightly
T5      soak             100k roster / 72 h store / crash matrix         -        ~3 h      weekly
parity  contributor      uv sync && pytest, offline/GPU-free/Node-free  3,568     <= 10 min every PR
                                                                                  (hard ceiling 600 s)
```

`SKIP` is not a state. A tier, slice or metric that cannot run is `unknown`, and `ow eval release-check`
refuses on it.

**The counts are a release-1 plan target, not a measurement**, and they are held by a ratchet rather than
by intent: `Q-G24` byte-matches `eval/inventory.toml` against `pytest --collect-only -q`, so the number
in this document and the number in the repository cannot drift, and a net decrease in any area needs a
`BLESS.log` row. The budgets are derived, not chosen — see §2.9. *(Build note, D845: `tools/gate_inventory.py` collects in a fresh interpreter, through a plugin that records each item and whether hypothesis drives it. It renders `eval/inventory.toml` as one `[[area]]` per `<dist>/<test directory>`, holding `tests` and `properties` and no total, and byte-diffs it. A collection that does not exit 0 is itself a finding. A decrease is judged against the merge base with `--base`, as Q-G3's gate rules the landed change, and needs an added `BLESS.log` row whose glob matches the inventory. On landing it counted 16,832 tests, 19 of them properties, in 18 areas. The plan's own numbers here are a release-1 target, and the ratchet holds whatever the repository holds. A test in the suite fails whenever the inventory is stale.)*

### 2.1 T0 — the static tier

Every `G` row in `tools/gates.toml` — **twenty-nine** at release 1, `G1`-`G27` from charter §D1 plus
`G28` and `G29` from [ADR-2](adr/0002-invariant-and-gate-registers.md) — plus the **twelve** Q-G
checks that read only committed bytes, plus
`tools/semgrep/omniweave.yaml`. The twelve, exhaustively, because "the static Q-G series" is otherwise a
phrase rather than a list:

| gate | what it reads | what it asserts |
|---|---|---|
| `Q-G1` | `fixtures/index.toml` | every fixture byte has a manifest row `{spdx, source_url, retrieved_at, sha256}` |
| `Q-G2` | the same file, plus `git count-objects` | Tier-A ≤ 64 MB, ≤ 256 KiB per Reduction, ≥ 40% real scans, the cassette budget, `size-pack` |
| `Q-G3` | `BLESS.log` plus the reduction diff | a frozen or tracked diff has a bless row in the same commit |
| `Q-G8` (static half) | `eval/results/**.json` | no committed row without a complete ten-field `MeasuredOn` *(Build note, D922: the tree exists. `ow eval run` over all five built suites, published with `ow eval publish`, wrote 9 files and 12 rows, each with its run's ten-field `MeasuredOn` (this developer machine's, `windows-amd64`), and Q-G8, Q-G19 and Q-G21 hold over them. The first publish was refused by Q-G19: the retrieve suite wrote `citability_violations` with `method = exact` and null bounds, and an exact count's interval is now the count itself. Publishing the label metrics ungated started Q-G27's clock on `order_acc` and `table_rel_acc`.)* |
| `Q-G10` | `tools/scorekinds.toml` plus the writer grep | registry parity in both directions |
| `Q-G17` | `eval/gates.toml`, `eval/counters.toml`, `eval/quarantine.toml` | every row carries an owner and a `review_by`; a row past its date fails |
| `Q-G19` | `eval/results/**.json` | byte diff; every row's required fields non-empty |
| `Q-G21` | the same tree | `field_acc` never without `doc_acc`; `hallucination_rate` never alone; `source_reread_rate` never without `task_accuracy` |
| `Q-G24` | `eval/inventory.toml` | the test inventory byte-matches the collection report |
| `Q-G25` | the test tree | every test lives in the directory its markers permit |
| `Q-G26` | fixture and corpus manifests | no split leakage and no fixture-into-corpus leakage |
| `Q-G27` | `eval/results/**.json` plus `eval/gates.toml` | no metric published ungated for more than two releases |

Semgrep counts as **one** enforcer, not forty, because deleting the config deletes them all — the
enforcer-independence rule from [01](01-principles.md). T0 fails fast and orders cheapest first: version
agreement (`G5`, single-file reads), then the byte-diff gates, then semgrep, then the import-time and
licence gates that need a resolved environment. Budget `t0.gates_job_s = 128`, `tol_abs = 40`.

**`G28` and `G29` are behavioural and the budget does not yet hold them.** `G28` (archive round-trip
over the fixture corpus, 45 s) and `G29` (the redaction canary under four forced faults, 60 s) are
[ADR-2](adr/0002-invariant-and-gate-registers.md)'s two appends, and 128 + 105 = 233 s is past
`V01-14`'s 180 s ceiling before tolerance. ADR-2's fallback is therefore not contingent but due at
the first measured run: both move to the `test` job beside `G26`, one line each in
`tools/gates.toml`. Until that run they are counted here and their seconds are not, which is a
disclosed gap in the T0 budget rather than a number this document has measured.

### 2.2 T1 — unit and property

Nine cells: `{ubuntu, macos, windows} × {3.11, 3.12, 3.13}`. Every cell runs the identical selection;
there is no per-OS deselection, because a platform-conditional `skipif` is exactly how the collection's
projects lost coverage without noticing. A platform difference is expressed as a **parameter whose
expected value differs**, never as an absent test.

| area | unit | property | what the properties assert |
|---|---:|---:|---|
| `core/canonical`, `core/identity` | 180 | 36 | `canonical()` round-trip; the three distinct encodings for absent / null / `""`; `ow128` domain separation; the `nfc`/`normalize_k` ladder implication and its failing converse (P-23) |
| `core/model` (Block, Grid, spans) | 420 | 46 | `Grid` exactly-once cover; `ts_*` and `os_*` never mixed; `content_digest` geometry-independence |
| `core/store` | 510 | 28 | one writer, one transaction per unit; identity-index uniqueness under `IFNULL` sentinels; `rebind()`'s three rules |
| `core/retrieve` | 330 | 22 | `fuse()`/`ceiling()` agreement in both halves; total order on `(-score, (doc_ord, page, ord), block_id)`; absence-gate precedence |
| `core/answer` | 240 | 14 | packing monotonicity (SV4); truncation cuts whole sections and whole blocks; `<ow:untrusted>` containment |
| `core/out` | 380 | 26 | `splice()` all-or-nothing under a 10k random-op batch; Finding folding; `nsig` stability |
| `core/host`, `core/host/wire` | 210 | 18 | frame framing under a byte-level fuzzer; deadline propagation; `DriverIO` immutability |
| `omniweave/route` | 290 | 30 | `evaluate()` purity; Kleene `on_unknown`; monotone `Rung`; interval-box subsumption soundness |
| `omniweave/graph` | 350 | 24 | `canonical_projection()` full-vs-incremental equality; `entity_merge` closure; `Cover` bitmaps |
| `omniweave/cli`, `omniweave/surface`, `omniweave/sdk` | 260 | 8 | one `ActionSpec` to seven generated artefacts, byte-identical |
| `omniweave-conform` (self-test) | 140 | 6 | `Q-G23`: the harness scores deliberately wrong outputs and gets the expected numbers |
| **total** | **3,310** | **258** | |

Hypothesis configuration, as two named profiles in the root `conftest.py`: *(Build note, D689: the workspace's shared test conftest is `packages/conftest.py`, not the root, because 58 test modules import from their package's `conftest` and pyright resolves a bare `conftest` against the root first; it holds the latency-budget policy, and these profiles belong there when they land.)*

```python
settings.register_profile(
    "pr",
    max_examples=200, derandomize=True, deadline=200,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=2_000, derandomize=False, deadline=1_000,
    database=DirectoryBasedExampleDatabase(".hypothesis/nightly"),
)
```

`derandomize=True` on PRs is not a convenience. A property test whose examples change per run turns a red
build into a coin flip, the flake quarantine (`Q-G18`) then eats the property, and a quarantined property
is a property that no longer holds. Randomization lives in the nightly profile, where every
counterexample is **minimized and committed to `fixtures/regressions/`** with the property id in the
filename.

**Two corpora, two homes, and they are not the same discipline.** `fixtures/regressions/` holds minimized
hypothesis counterexamples, one file per property, read only by the property that produced it.
`fuzz/seeds/` holds the atheris corpus, mirrored from `vendor/anydoc` — anydoc is the only fuzzed parser
in the collection (12 cargo-fuzz targets in `anydoc/fuzz/fuzz_targets/`, one per binary and archive
format) and its seeds are the starting corpus for ours. A hypothesis counterexample never lands in
`fuzz/seeds/` and a fuzz crash never lands in `fixtures/regressions/`: the first is an input a property
rejected, the second is an input that killed a process, and merging them loses which is which.

### 2.3 T2 — golden

The `golden` CI job. Three things, all of which read committed bytes and replay Cassettes:

1. the three Reductions over the Tier-A fixture corpus (§4);
2. the Counters from `eval/counters.toml`, exact by default (§2.8);
3. the **deterministic half of the absence suite** — the paired-damage construction (§8.6), which injects
   one `Diag` code at a time and asserts the answer degrades to a named cause rather than a confident
   zero. It needs no model, so it gates every PR instead of waiting for T4.

`--cassette required`. A miss is `OW-Q-004` and never a live call: olmocr's shipped default is
`--max_page_retries 8` (`olmocr/olmocr/pipeline.py:1221`) fired **in parallel** when the queue is idle
(`:343-350`), a 64× cost amplifier — 8 retries × 8k output tokens is 64,000 tokens for one page, $0.0128
at $0.20/1M — with no natural rate limit. A CI job that can reach a paid endpoint is a CI job that
eventually will.

Budget `golden.job_s = 190`, `tol_abs = 45`.

### 2.4 T3 — conform, treated as a correctness test

The twelve suites from [04](04-driver-system.md) §8.2, run against fifteen subjects. That is 180 suite
runs comprising **1,452 assertions**, and the decomposition is the check:

| family | subjects | testkit size | assertions |
|---|---|---:|---:|
| parse | `parse.office.anydoc`, `parse.pdf.pdfium`, `parse.page.olmocr`, and the three `read_back` drivers `parse.pptx.native`, `parse.docx.native`, `parse.deck.native` | ~120 | 720 |
| derive | `derive.segment.spine`, `derive.anchor.native`, `derive.anchor.defterm`, `derive.xref.native`, `derive.xref.pattern`, `derive.entity.table`, `derive.entity.gazetteer` | ~48 | 336 |
| embed | `embed.text.bge_m3` | ~36 | 36 |
| compile | `compile.pptx.native`, `compile.docx.native`, `compile.deck.native`, and the reference target `compile.text.owtext` | ~90 | 360 |
| **total** | **15** | | **1,452** |

The parse figure is the ~120-property driver testkit that [04](04-driver-system.md) §8.1 owns, and the
three `read_back` drivers run it **unchanged** (OUT22) — if the testkit needed a special case for
`read_back`, the OUT abstraction would be one implementation wearing an interface. `embed.text.bge_m3` is
a subject even though `vectors = "off"` is the shipped default, because conformance runs against
installed drivers and not against enabled ones. `compile.video.native` ships with
`[compile] implemented = false`, so it is a subject of `card` and `contract` only; it contributes no
scored assertions and is not one of the fifteen.

**Four `capability` assertions are allocated and not yet built.**
[ADR-7](adr/0007-driver-resolution-keys.md) replaced `R-T15`'s proposed runtime counter
(`drivers.resolve_memo_collisions`, which could only report a wrong driver *after* it had run and
billed) with four property tests in the `capability` suite. Each builds two `Requirement`s differing
in exactly **one** of the four fields the charter's memo tuple omitted, resolves both against the
subject's card, and asserts the two `Resolution`s differ:

| # | field varied | the wrong answer the property forbids |
|---|---|---|
| 1 | `granularity` | a `part`-granularity request served the `document`-granularity driver a previous call resolved, or the reverse, in place of `GRANULARITY_MISMATCH` |
| 2 | `input_kind` | a driver resolved for one input kind served for another |
| 3 | `requires_produces` | a driver whose `produces` does not cover the demanded set served in place of `PRODUCES_INSUFFICIENT` |
| 4 | `pinned` | a `pinned` requirement served the driver an unpinned requirement resolved to — the one field whose whole purpose is reproducibility |

[04](04-driver-system.md) §4.8 is the home of the rule these enforce: the memo key is
`(requirement_digest, policy_digest, catalog_digest)` and `Requirement.digest` iterates
`dataclasses.fields()`, so narrowing it to a written-out key list is the regression the four catch —
and it is a regression nothing else would report, because the digest's failure mode is a *plausible*
answer. They are **built in P3**, with `resolve()` and both DriverHosts
([roadmap](16-roadmap.md) §3, freeze week 22). The 1,452 above is the release-1 floor and does not
count them; each family's testkit size rises by four when they land.

The mandatory tier is budgeted at `conform.mandatory_tier_s = 240`, `tol_abs = 60` — the five-minute
rule, enforced as a timing assertion, because a skipped gate is not a gate. T3 is not an integration tier
and not a nightly tier: a conformance failure blocks a merge exactly as a unit-test failure does. The one
non-mandatory suite is `quality` (§12), run by `ow conform --bench`.

### 2.5 T4 — eval

Nightly on `ow-bench-1`, ≤ 90 min. **There are seven suites**, and `eval_run.suite`'s `CHECK` is the
register: `parse`, `extract`, `retrieve`, `absence`, `roundtrip`, `portability`, `perf`. Five touch a
model — `parse`, `extract`, `retrieve`, `absence`, `roundtrip` — and those five are what the charter's
"five suites, live models" names. `portability` and `perf` never reach a model and ride the same job
because they need the same pinned runner; `--cassette required` (§12.2 rule 4) therefore binds on the
five and not on the two, which is the reason the split is kept rather than collapsed to one number. *(Build note, D903, a user ruling of 2026-10-19: `portability` measures that the same inputs give identical results on every OS/Python cell. One machine is one cell, so a run holds this cell to committed frozen values: each Tier-A `.shape` Reduction against `fixtures/goldens/` (Q-G4's frozen kind, section 5.1) and each register target's compiled parts, by sha256, against `eval/portability.toml`. Its metric is the hard `cell_identity` row in `eval/gates.toml`, 1.000. `pages`, `outline` and `byte` digests are not promised across cells and are not read. win32 on Python 3.12 and linux on 3.13 were measured by hand and matched; the nine cells are CI's matrix running the suite.)* *(Build note, D914: every CI test cell, three OSes by three Pythons, now runs `tools/ow_portability.py` after its suite, holding the register targets' goldens and V10-10's 40-unit deck (`pptx@golden40`, generated and compiled with the `pptx` row's card) to `eval/portability.toml`. The table was written on win32 3.12 and matched on linux 3.13 before the step landed; a cell that drifts fails by name.)*

This reading is **normative**, not a reconciliation offered for consideration:
[ADR-11](adr/0011-eval-register-reconciliation.md) rules it and supersedes the charter's pyramid line
at charter §9.2 `E84`. The T4 row of §2's pyramid reads *seven suites, five with live models*. A
reader who counts suites finds seven in every home that states one.

### 2.6 T5 — soak

Weekly, ~3 h, same pinned runner: the 100k-roster run (`G22`), a 72-hour store held open with the WAL
valve exercised, `ow test crash-matrix` at every statement boundary in `Store.complete()`, and a full
`ow eval golden` pass over Tier B. T5 is where a leak that takes four hours to manifest is found, and it
is the only tier permitted to exceed an hour.

### 2.7 What belongs at each tier, and the gate that keeps it there

A pyramid decays in one direction: a test that acquires a fixture drifts upward in cost while staying in
its old directory, and a tier whose budget is breached gets tests pushed down into a tier that does not
run them properly. `Q-G25` makes placement mechanical. *(Build note, D834: the marker check is `tools/gate_placement.py`, and `OW-Q-014` is now a `codes.toml` row. It reads every `test_*.py` and `conftest.py` under a `tests/` directory and under `bench/` as an AST. A `pytest.mark.golden` or `pytest.mark.conform` anywhere in a file requires `tests/<tier>/`, and a test file there must set the tier as its module's `pytestmark`, or `-m "not conform"` would run it in T1. It passes on landing: 34 files under `tests/conform/` and none under `tests/golden/`. The autouse fixture is not built, so a spawning test with no marker is named as unchecked; three `omniweave-core` tests sit directly in `tests/`, outside both T1 directories.)*

| a test that… | belongs at | enforced by |
|---|---|---|
| asserts a pure function's algebra | T1 (`tests/unit/`) | an autouse fixture patches `socket.socket`, `subprocess.Popen`, `time.time` and `open` outside `tmp_path` to raise |
| opens a store | T1 (`tests/store/`), in-memory or under `tmp_path` | the same fixture, with `tmp_path` allowed |
| reads a byte out of `fixtures/` | T2 (`tests/golden/`) | marker `@pytest.mark.golden`; `Q-G25` fails the marker outside that directory |
| spawns a subprocess or a Driver host | T3 (`tests/conform/`) | directory placement plus the marker check |
| needs a network socket or a GPU | T4 only | the parity container has neither, so the test cannot pass elsewhere |
| takes more than 5 s | T5, or it is refactored | a per-test duration report; the slowest 20 print on every run |

The rule that makes this hold: **a test may move up a tier freely and down a tier only with a `BLESS.log`
row.** Downward movement is the direction that hides a cost.

**Flake control, and quarantine is a register rather than a mode.** `eval_flake` records
`(test_id, day, runs, fails, reran_green)`. Above 2% failure over a rolling 30-day window — at roughly 20
PR runs a day that is 12 failures in 600 — a test is quarantined to `informational` (`Q-G18`). Because
there is no `--warn-only` anywhere in the framework, quarantine has to be visible rather than a state a
test can sit in, so it is a **byte-diff-gated file**:

```toml
# eval/quarantine.toml -- read by Q-G18 and by Q-G17's rot clock. Byte-diff gated.
[gate]
owner = "team@particle6.com"
review_by = "2027-06-01"

[[quarantined]]
test_id = "tests/conform/test_determinism.py::test_seeded_drift[parse.page.olmocr]"
since = "2026-08-14"
expires = "2026-10-13"
owner = "team@particle6.com"
issue = "https://github.com/particle6/omniweave/issues/812"
reason = "vLLM 0.9.1 batch composition moves 3 blocks in 1 run of 12"
```

`expires` is at most 60 days after `since`, and `Q-G17`'s rot clock reads this file as it reads
`eval/gates.toml`: past `expires` the row fails the build, and the exit is either back to its tier or
deletion with the reason recorded. `ow eval explain <test_id>` prints the 30-day window, the failure
texts and the quarantine row. A quarantined test is visibly not gating rather than invisibly passing. *(Build note, D836: `omniweave_conform.flake` and `tools/gate_flake.py` are Q-G18. The window is the `n` days ending today inclusive; flaky is strictly over 2%, so 12 in 600 is not; and a green re-run is still a failure. The register refuses a row that lacks a key, carries an unknown one, expires outside (since, since + 60 days], or quarantines a test twice. The gate fails an unquarantined flaky test and an expired row, and notes a quarantined test that has recovered. With no `.oweval` the rates clause is named as not run; nothing writes `eval_flake` yet. Q-G17's clock reads this file's `[[quarantined]]` rows by `expires`, which corrected D830's `[[quarantine]]`.)*

### 2.8 The regression hierarchy: counters, then memory, then time

Time is the **last** signal, not the first. A silent re-render, a re-billed free operator and a 100%
cache miss all leave a clock untouched; graphrag shipped a permanent silent 100% cache miss for exactly
that reason, which is the defect `G18` exists to catch. So `eval/counters.toml` is evaluated before
`eval/perf.toml`, and a counter delta fails without a bless (`OW-Q-005`).

Counters are `exact` by default (±1 fails) or `ratchet` with a tolerance. The charter's sixteen rows
stand unchanged and this document adds none: the temptation to add a `ratchet` counter for a number you
have not stabilised is how the class erodes. *(Build note, D823: the charter prints fifteen rows, not sixteen, and `eval/counters.toml` transcribes the fifteen plus `ci.job_seconds.*`. The plan maps no row to a `source`, so the file rules each by where a run records the count: `route_spend` for `tokens_out`, `llm_calls` and `rebilled_units`, `driver_observation` for `driver_activations`, and the run manifest for the rest. The `ci` row's tolerance, 0.25, is also the file's, as the plan gives none. `omniweave_conform.counters` reads it: `exact` fails a delta of one either way, and `ratchet` a rise past its tolerance.)*

**Every `eval/counters.toml` row declares a `source`**, over the closed vocabulary
`{manifest, route_spend, driver_observation, ci}`. The first three are the lock's definition of a
Counter — harvested from a run — and `Q-G5` compares only those three against their sources. `ci` is
the fourth, and it exists because [repository layout](11-repo-layout.md) §6.2 already writes one: each
CI job ratchets its wall time as `ci.job_seconds.<job>`, a row with no `run_id` and none of the three
harvest sources. **A `source = "ci"` row never reaches `eval_counter` or `eval_scoreboard`.** That is
not a policy choice but the DDL: `eval_counter`'s primary key is `(run_id, counter, scope)` with
`run_id NOT NULL REFERENCES eval_run(run_id)`, and a counter measuring CI has no run to reference.
The key makes the row unrepresentable; `source` makes the exclusion legible in the file rather than
implicit in a join that returns nothing. `ci.job_seconds.<job>` is the first and, at release 1, the
only `ci` row. [ADR-11](adr/0011-eval-register-reconciliation.md) rules this, closing `Q-Q6`.

Memory is **absolute**, never a percentage. codegraph produced 5.9 GB of WAL against a 340 MB database,
then 22 GB and exit 137; a percentage tolerance on a number that can grow 60× is not a gate. So
`wal.bulk_index_peak_bytes = 2_147_483_648` carries `tol_abs = 536_870_912`, and
`rss.gen5000p_peak_bytes = 1_610_612_736` carries `tol_pct = 10` only because it is a peak the
architecture bounds rather than a buffer that can run away.

Time is a **Pacer ratio**: the fixed, dependency-free in-repo workload (`blake2b` over 64 MiB, a
2M-iteration integer loop, 200k SQLite insert+select) runs immediately before and after every timed
measurement, and the budget is `work_ns / mean(pacer_before_ns, pacer_after_ns)`. Disagreement above 15%
between the two readings yields `unstable` — neither `pass` nor `fail`, and `ow eval release-check`
treats it as `unknown`. A time budget fails on **three consecutive nightly runs** above tolerance,
comparing 7-run rolling medians on the single pinned runner `ow-bench-1`.

**The pinned runner is a single point of failure, so it has a named successor.** `ow-bench-2` is
identically specified and kept cold. Promoting it is a **baseline reset**, recorded as one row in
`eval/baselines/`, and the two machines are cross-checked once per corpus release by running the `perf`
suite on both and publishing `pacer_cross_runner = ratio(bench2, bench1)` on the scoreboard. Without that
row, a runner swap looks like a simultaneous 12% regression in everything and somebody spends a week
on it.

**Budget versus Guard, and the anti-ratchet rule.** A `Budget` is an absolute floor owned by the product:
its breach means we shipped something worse than our published promise. A `Guard` is a delta against
release N−1 owned by the PR author: its breach means this change made it worse, and it fires only at
paired `p < 0.01` **and** effect ≥ MDE, where `mde_rule = "2 * se(headline)"` is recomputed at every
corpus release and never guessed. Baselines are **release-anchored**, not commit-anchored, and are
additionally checked against N−2 at 2× tolerance (`ratchet_ceiling_releases = 2`), so ten blessed 9%
regressions cannot compound into a 136% one.

### 2.9 Every budget's tolerance is bounded by its tier ceiling

The pyramid states ceilings; `eval/perf.toml` states budgets with tolerances. Nothing in the charter
connects them, and a budget whose `value + tol_abs` exceeds its tier ceiling is a budget that can pass
while the tier is over. So `tools/gate_budgets.py`, under `Q-G15`, asserts one arithmetic property over
every row carrying a tier:

```text
value + tol_abs  <=  the tier ceiling the row's `gate` names
```

It holds for every charter row and it constrains this document's own: `conform.mandatory_tier_s`
240 + 60 = 300 s = the 5-minute ceiling; `contributor_parity_s` 420 + 180 = 600 s = the hard ceiling;
`t0.gates_job_s` 128 + 40 = 168 ≤ 180; `test.cell_ubuntu_311_s` 185 + 50 = 235 ≤ 240; `golden.job_s`
190 + 45 = 235 ≤ 240. The check is non-strict on purpose — the charter's own two rows sit exactly on
their ceilings, and tightening it to `<` would fail the charter rather than a mistake.

**`Q-G15` gains a second, non-arithmetic clause: every `rss.` budget names the process it bounds.**
Every `[[budget]]` row in `eval/perf.toml` whose `id` starts `rss.` declares `process`, over the
closed vocabulary `{supervisor, worker, driver_subproc, service}`, and `tools/gate_budgets.py`
asserts presence and vocabulary membership. The defect it prevents is arithmetic read at the wrong
scope: `rss.merged4mcell_peak_bytes = 4 GiB` bounds a **worker**, and a reader who takes it for a
whole-host figure sets sixteen workers against it and gets an OOM kill at hour six instead of
`ow doctor`'s refusal before the run ([performance](12-performance.md) §4.4). One clause on an
existing gate; [ADR-11](adr/0011-eval-register-reconciliation.md) coins no new `Q-G` number for it,
and charter §9.2 `E88` records the `[[budget]]` row's shape change.

### 2.10 One writer, nine cells, and where the rows actually land

`.oweval` obeys INV-17's rule the way `.owstore` does: **one writer.** Under `pytest-xdist` there are up
to nine cells and several workers per cell, so no test process ever opens `.oweval`. Each worker appends
newline-delimited JSON to `eval/staging/<run_id>.<worker_id>.ndjson`, one object per verdict, counter or
perf reading, and owns that file exclusively — no locking, no `busy_timeout`, no contention.
`ow eval import` runs once at job end, reads every staging file, sorts on
`(suite, subject, assertion_id, evaluator)` and writes `.oweval` in **one** transaction. The sort makes
the result byte-reproducible regardless of worker scheduling, which is what INV-24 requires of a
generated artefact. *(Build note, D814: the file is `omniweave_core.store.oweval`'s, because INV-17 and G24 put the transaction that writes it in the store. Its DDL is the charter's, shipped as `schema/oweval/0001_eval.sql` and versioned by `PRAGMA user_version`, outside `.owstore`'s migration chain. `eval_perf` takes 12-performance.md section 7.4's `peak_wal_bytes` and its NULLable peaks, with the charter's foreign key and CHECK, and `eval_run` gains `not_measured` and `confounders`, which section 11.1 requires on every published row and the charter gives no column. The writer orders each table by its primary key, because this section's sort key is not unique without `run_id`.)*

A worker that dies mid-write leaves a truncated final line. The importer drops it, counts it into
`not_measured[]`, and sets `eval_run.status = 'partial'` — never `'ok'`, and never silently. §8.7 states
what a `partial` run may and may not publish. *(Build note, D815: `omniweave_conform.staging` is both halves. A worker's writer opens its file exclusively and writes one sorted-key row per line. The importer treats the bytes after a file's last newline as the truncated line, a completed line that does not parse as corruption that refuses the import, and an assertion of the run's corpus with no verdict as a loss, named per slice. A `rejected` assertion is not expected to answer. The run row is the caller's; the importer only lowers its status, and the whole import is one `oweval.write()`.)*

## 3. Statistics with no RNG on the default path

Every interval, every p-value and every calibration bucket is closed-form. `eval_metric.method` records
which of `closed_form | exact | resampled | none` produced the interval, and `resampled` appears on
exactly one band of exactly one path.

| quantity | method | formula / rule |
|---|---|---|
| a rate (recall, accuracy, a calibration bucket's `p_hat`) | `closed_form` | Wilson 95%, always; never the normal approximation, which is wrong at the p→1 end where our gates live |
| the headline over slices | `closed_form` | macro mean with `min_slice_n = 30` (the same number as `min_audit_n`, reused deliberately); `se = sqrt((1/S²) · Σ sd_s²/n_s)` |
| paired A/B against release N−1, **N < 20** | `exact` | exact enumeration of all 2^N sign flips |
| paired A/B, **20 ≤ N < 200** | `resampled` | a **seeded** resample, seed = `blake2b(run_id‖metric‖"ow-perm-1")` truncated to 8 bytes and **recorded in the row** |
| paired A/B, **N ≥ 200** | `closed_form` | the sign-flip permutation test's asymptotic, `p = 2(1 − Φ(|Σd| / sqrt(Σd²)))` |
| a slice with `n < min_slice_n` | `none` | `state = 'unknown'`, the slice is **named** in the report, and it never silently drops out of the macro mean |

The three paired bands are disjoint and exhaustive on N, which is the whole point: a band boundary that
overlaps is a place where two methods produce two p-values for one comparison and the reporter picks. *(Build note, D813: `omniweave_conform.stats` implements this table and the three digest choices below it. A slice under `min_slice_n` is excluded from the macro mean and named, and `S` counts the admitted slices. The resampled band draws 9,999 sign vectors, each the bits of `blake2b(seed ‖ r)`, and reports `(1 + c) / 10,000`; this section fixes the seed and not the count. `eval_metric` has no seed column, but `(run_id, metric)` determines the seed, so the row records it by its key. `‖` is a NUL between UTF-8 fields, and a flip within `1e-9 · Σ|d|` of the observed statistic ties it.)*

This is not fastidiousness. olmOCR-Bench — the best-designed benchmark in the collection, and the one
whose assertion schema omniweave adopts wholesale — calls `np.random.choice` and `np.random.shuffle`
unseeded at `olmocr/olmocr/bench/utils.py:33,55,120,172` and `random.sample` at
`olmocr/olmocr/bench/benchmark.py:262`, and a recursive grep for `seed` across `olmocr/olmocr/bench/`
returns no hit in any Python file. Its published confidence intervals and p-values therefore do not
reproduce, and nobody noticed for the lifetime of the benchmark. omniweave's default path has no RNG at
all, and the one seeded path records its seed in the row that carries the number.

**Where a random choice is genuinely needed, it is a digest instead.** Three places want one, and all
three take the same shape — a keyed `blake2b` over stable inputs, so the choice is balanced over the
corpus, reproducible from the row, and free of a seed nobody records:

| choice | function | why not an RNG |
|---|---|---|
| the 100-way corpus split (fit / validation / holdout, §9.1; the scoreboard's 85/15, §11.1) | `blake2b(doc_key‖"ow-split-1") % 100` | leakage becomes structurally impossible and no split file can drift out of agreement with itself |
| the 5% visual review sample (§10.2) | `blake2b(artifact_slug‖unit‖"ow-review-1") % 100 < 5` | the same units are re-reviewed across releases, so drift is visible |
| judge presentation order (§10.3) | `blake2b(assertion_id‖run_id‖"ow-judge-1")[0] & 1` | position bias needs a balanced order, and a shuffled one cannot be replayed from the row that recorded the verdict |

## 4. Golden corpora: sourcing, licensing, fixtures

### 4.1 The four tiers

| tier | what | size | rule |
|---|---|---|---|
| **A** | `fixtures/` — bytes in the repository | ≤ **64 MB** total, ≤ 4 MB per binary, ≤ 256 KiB per Reduction file, ≤ 32 MiB of Cassettes | one `.meta.toml` per file; **four** admissible provenances and no fifth; **≥ 40% of `fixtures/docs/` must be real public-domain scans** |
| **B** | `omniweave-golden` — the redistributable evaluation corpus | ~600 documents, ~240 MB | a **versioned data artifact, never a wheel**; `<name>-<version>.zip` (a plain ZIP with `ZIP_DEFLATED` members) + `manifest.toml` + `.sha256`, installed by digest into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` and re-verified on every use; a digest mismatch is a **permanent failure that never triggers a fetch** |
| **C** | pointer manifests | unbounded, nothing stored | per-file `sha256` plus **two independent booleans**, `redistribute` and `publishable`; a corpus whose licence forbids publication is measured internally and renders `withheld: corpus licence` |
| **D** | the user's own corpus | — | watermarked `corpus: local, unverifiable`; never enters a published number |

`omniweave-golden` is deliberately not a Python distribution. A 240 MB corpus wheel breaks `G2`'s weight
ceiling, breaks `G5`'s "every version declaration site agrees" the moment it is date-versioned (a corpus
version is `2026.09`; a `RELEASE` is semver), and exceeds PyPI's default per-file limit.

**It is a ZIP and not `.tar.zst`**, which is [11](11-repo-layout.md) §3.2's fact and charter erratum
`E78`, ruled by [ADR-10](adr/0010-data-artefacts-and-weight-ceiling.md) decision 1: a stdlib-only
install carries no zstd decoder (`compression.zstd` is 3.14+ and `zstandard` is dev-only), and
[14](14-security.md) §2.2's bounded reader is written against a central directory, so ZIP is the one
container the fetch path can both decode and bound. `ow eval fetch` verifies the digest before the
first member is read, and the ~15% download growth against `.tar.zst` is a one-time cost on an
artefact refreshed twice a year (§11).

### 4.2 The four admissible provenances, and no fifth

`Q-G1` fails a fixture byte with no manifest row; `Q-G7` fails an SPDX identifier outside the corpus
allowlist.

| provenance | when | what must be recorded |
|---|---|---|
| `generated` — **preferred** | a phenomenon can be synthesised: a merged-cell table, a 4M-cell sheet, a 5,000-page PDF, an encrypted container, a malformed ZIP | the generator path under `fixtures/gen/` and the expected output sha256 |
| `public_domain` | a US federal work under 17 U.S.C. §105 — SEC filings, GPO documents, court opinions, NIST and USPTO publications | `source_url`, `retrieved_at`, the statutory basis string |
| `cc0` / `cc_by` | an openly licensed scan or report | SPDX id, `source_url`, `retrieved_at`, and for `cc_by` the attribution line that must appear in `NOTICE` |
| `authored` | written by a contributor for this repository | the contributor and a CLA reference |

**Why the 40% floor on real scans matters and is not negotiable.** A wholly synthetic corpus flatters the
parser: generated scans have no feeder skew, no bleed-through, no scanner-specific ringing, no JPEG
generation loss and no staple shadow. The synth-OCR degradation ladder (§9.2) narrows that gap and does
not close it, which is why `F24` exists as an open measurement and why the human-labelled slice is the
anchor. A corpus of only generated documents would pass every gate in this document and predict nothing
about a scanned 10-K.

### 4.3 What makes a good fixture

Seven properties. A reviewer may reject a fixture on any one of them.

1. **It fails for exactly one reason.** A PDF that is both encrypted and has a broken xref tests nothing,
   because the first failure masks the second. Two hazards, two fixtures.
2. **It is the smallest input that still exhibits the phenomenon.** A merged-cell bug does not need a
   40-page workbook. The `.meta.toml` records `min_pages_justification` for anything over 8 pages.
3. **Its expected outcome is a machine assertion, not a snapshot.** "This cell's `top_heading` is
   `Member State`" survives a reducer change; "the output is these 9,000 lines" does not.
4. **Its provenance chain is one of the four, recorded, and re-derivable** — including for its assertion
   set, which is a separate licence question (§4.5).
5. **Its defect provenance is named.** A regression fixture carries the repository path or issue that
   proves the bug was real: `defect = "docling/docling/datamodel/document.py — the page limit check runs
   after the parse"`. A fixture with no named defect is a fixture nobody can retire.
6. **It is either generated by a committed generator or committed as bytes.** Never fetched at test time.
   The parity job has no network.
7. **Its name says what it tests.** `xlsx-merged-4m-cells.xlsx`, not `sample3.xlsx`. The name appears in
   every Reduction line and every failure message.

### 4.4 The fixture manifest

One sidecar per file. `fixtures/index.toml` is **generated** from the sidecars — sorted by relpath, LF,
no timestamps — and byte-diff gated, so `Q-G1` and `Q-G2` are one pass over one file rather than a
directory walk with a per-file lookup, and INV-24 holds on the generated file. *(Build note, D843: `tools/gate_fixtures.py` generates `fixtures/index.toml`, byte-diffs it, and holds each row to its file. A fixture is a committed file under `packages/<dist>/fixtures/` or `fixtures/docs/`, less its sidecar and housekeeping. The other `fixtures/` trees are generators, Reductions and target goldens, each under its own gate. Cassettes are left out pending a ruling: section 4.7 puts them under Q-G1, but none of section 4.2's provenances fits a recorded model response, and the 560 committed ones have no sidecar. A row's `sha256` and `bytes` must be the file's, its provenance one of section 4.2's five spellings, and its record that provenance's: `generated` names a committed generator under `fixtures/gen/`. No key may be empty. Q-G1's four-key list is the external provenances' record, since a `generated` fixture has no `source_url`. The seven PDF fixtures had no sidecars; `fixtures/gen/gen_pdf_fixtures.py` now reproduces all seven against their pins, so all 37 fixtures are `generated`.)*

```toml
# fixtures/docs/sec-10k-2019-scanned-exhibits.pdf.meta.toml
[fixture]
sha256 = "9f2c4a1b7e0d3552aa11bc93f4e7d20618b5c4a09f13e6d7c2b8a054916f3e77"
bytes = 3_918_442
media_type = "application/pdf"
provenance = "public_domain"
spdx = "NONE"
statutory = "17 U.S.C. 105"
source_url = "https://www.sec.gov/Archives/edgar/data/320193/0000320193-19-000119.pdf"
retrieved_at = "2026-04-11"
review_by = "2027-04-11"
owner = "team@particle6.com"
pages = 188
min_pages_justification = "the mixed-document routing case: 12 scanned exhibits inside 176 born-digital pages"

[fixture.tests]
slices = ["pdf/mixed", "pdf/born_digital", "scan-degraded"]
defect = "docling do_ocr is a DOCUMENT boolean (docling/datamodel/pipeline_options.py) -- 188 pages pay VLM prices or 12 pages return garbage"
asserts = ["order_acc", "structure_f1", "escalations", "page_renders"]

[fixture.reductions]
shape = "frozen"
pages = "tracked"
outline = "suppressed"
outline_blocks = 17_431
outline_suppressed_because = "bytes"
```

Two keys carry weight beyond their obviousness.

**`[fixture.reductions]` makes a Volatility tier a property of the fixture, not of the reducer.** A
fixture whose `outline` would exceed the byte cap writes `outline = "suppressed"` in its own sidecar and
the reducer reads it, rather than re-deriving a threshold at two call sites that will eventually
disagree. `outline_blocks` records what was suppressed, so a suppressed reduction is still a number that
grows visibly rather than a blank.

**`outline_suppressed_because` is a closed two-value vocabulary, `{"bytes", "pages"}`, evaluated in
that order.** The reducer estimates `outline_blocks × ~96 B` before building a line and records
`"bytes"` whenever that estimate exceeds `MAX_REDUCTION_BYTES = 262_144`; only if it does not does the
500-page pre-check get to record `"pages"`. That ordering makes `"pages"` reachable **only** below
`2730 / 500 ≈ 5.46` blocks per page — eleven times under `F1`'s 60-120 envelope (§5.2) — so a reviewer
who sees `"pages"` in a sidecar is reading a fact about a near-empty scanned deck, never a fact about
the cap. A third value is a schema change, not a new string:
[ADR-11](adr/0011-eval-register-reconciliation.md) closes the vocabulary.

**`review_by` and `owner` on a fixture close the licence-rot hole.** Every `[[gate]]` row has an owner and
a review date under `Q-G17`; a fixture's licence is exactly as perishable — a `cc_by` source can change
its terms, a `source_url` can 404, and a "public domain" determination can turn out to have been wrong.
`Q-G17`'s clock therefore reads `fixtures/index.toml` as well, and a fixture past its `review_by` fails
the build with `OW-Q-007`. The default window is twelve months for `cc0`/`cc_by`/`public_domain` and
none for `generated` and `authored`, which have no external dependency to rot.

### 4.5 An assertion set is itself a derivative work

This is the licensing constraint that the collection uniformly ignores, and it bites hardest where
evaluation is most valuable. An Assertion of type `present` carries a verbatim string out of the
document. A file of 4,000 such assertions over 600 documents is a partial reproduction of those
documents, and its redistributability is a **separate question** from theirs.

Hence `eval_corpus` carries two independent booleans, `document_redistributable` and
`assertions_redistributable`, plus `publishable`, and:

- an assertion file quoting more than `min(2000 chars, 10%)` of any one source document is **refused** at
  corpus build time;
- every Assertion carries `derived_from_sha256` — the licence chain for the assertion itself, pointing at
  the exact fixture bytes it was authored against, so a licence question about one document resolves to
  the assertion set by an indexed query rather than by inspection;
- a Tier-C corpus may be `document_redistributable = 0` and `assertions_redistributable = 1`, which is
  the common and useful case: we publish what we asserted and not what we asserted it about.

Three of the four combinations are legitimate. The fourth — documents redistributable, assertions not —
happens when the assertions were purchased or licensed from a third party, and the harness supports it by
allowing an eval corpus whose assertion file lives outside the repository under a pointer manifest.

### 4.6 Large binary fixtures in git

**Decision: no git-lfs, no submodule, no fetch-at-test-time.** The reasons are mechanical, not aesthetic:

- The `contributor-parity` job runs in a container with **no network** (`Q-G22`). An LFS smudge is a
  network fetch, so an LFS-backed fixture cannot participate in the job that proves a contributor can
  build the project.
- INV-24 requires every committed artefact to be byte-reproducible from inputs it names. A pointer file
  names a server, not bytes.
- A submodule makes `git bisect` across a fixture change a two-repository operation, and the golden bless
  discipline (§5.5) depends on the reduction diff and the fixture change being **in the same commit**.

What carries the weight instead, in four mechanisms:

1. **Generators, for anything synthesisable.** `fixtures/gen/*.py`, each deterministic under
   `SOURCE_DATE_EPOCH=0` with `random`, `secrets`, `uuid4`, `time.time` and `datetime.now` monkeypatched
   to raise (the same harness `OUT14` uses). Output lands in `fixtures/generated/`, which is
   `.gitignore`d; `fixtures/gen/EXPECTED.sha256` pins each generator's output so a generator change is a
   one-line visible diff rather than a silent corpus change. This is what makes the 5,000-page PDF, the
   4M-cell workbook and the 100k-roster fixture affordable: **none of them is ever in git**, and none of
   them commits a Reduction (§5.2 explains why that matters).
2. **The Deep golden as an exploded archive.** `fixtures/goldens/deep/<doc>.owdoc.d/` — the `.owdoc`
   unzipped into uncompressed `.ndjson` members. Git delta-compresses successive generations of NDJSON
   well and a compressed ZIP not at all; `jq` reads it; and `rebind()` gets two real generations to
   match. Bounded at **≤ 24 documents of ≤ 40 pages**, which is the smallest set that covers one document
   per slice and, not coincidentally, the same order as the `outline` byte cap's page ceiling (§5.2).
3. **Tier B by digest, outside the repository.** `ow eval fetch omniweave-golden@2026.09` installs into
   `$OMNIWEAVE_HOME/golden/2026.09-<sha256>/` and re-verifies the digest on every use. A mismatch is a
   permanent failure that **never triggers a re-fetch**, because a corpus that silently re-downloads is a
   corpus whose digest means nothing.
4. **A pack-size gate.** `Q-G2` additionally asserts that `git gc --auto --quiet` followed by
   `git count-objects -v` reports `size-pack ≤ 200_000` KiB, ratcheted. The `gc` is load-bearing: without
   it the loose-object count dominates on a busy branch and the number is noise. Tier A's 64 MB budget
   bounds the fixtures; the pack gate bounds everything else, including the Deep golden's growth over
   releases and the Cassette store, which nothing else measures. *(Build note, D844: `tools/gate_fixtures.py` runs Q-G2 after Q-G1, as :1986's "the same gate". Tier A is every committed byte under `fixtures/` or a `packages/<dist>/fixtures/` tree, at most 64,000,000 bytes, since the row writes `MiB` where it means binary units. Each Q-G1 fixture is at most 4,000,000 bytes, and each Reduction and cassette is held to `omniweave_core.limits`. `size-pack` is read after `git gc --auto --quiet` against 200,000 KiB; on this repository it measured 14,120 KiB, with Tier A at 927,997 bytes. With no fixture under `fixtures/docs/`, the 40% scan floor has nothing to measure, and once one lands it fails closed until a sidecar key says what a scan is. The orphan sweep waits for `eval/cassette-usage.toml`, and the ratchet for a baseline.)*

### 4.7 Cassettes are fixtures, with their own budget and their own sweep

A Cassette is committed bytes under `fixtures/cassettes/`, so `Q-G1`'s manifest rule applies to it. Two
things follow that the charter does not state, and both matter at the second year rather than the first.

**A separate byte budget, because a cassette corpus grows with the model surface and not with the fixture
corpus.** `MAX_CASSETTE_BYTES_TOTAL = 33_554_432` (32 MiB) and `MAX_CASSETTE_BYTES = 262_144` per file —
the same 256 KiB as a Reduction, reused because both are committed artefacts a human has to be able to
diff. A recording whose response exceeds the per-file cap is **refused at record time** with `OW-Q-017`
and the fix is a smaller fixture, not a bigger cap: a 40 MB blob in CI is a blob nobody reviews. The
cassette budget is inside Tier A's 64 MB, not beside it.

**An orphan sweep, because nothing else deletes a cassette.** A prompt change, a fixture retirement or a
deleted test leaves its recording behind, and the store then grows monotonically forever. So the T2 and
T3 jobs write `eval/cassette-usage.toml` — generated, sorted, byte-diff gated — listing every cassette
key that was *hit*, and `Q-G2` fails on a committed cassette with no hit (`OW-Q-018`). *(Build note, D972: `bench/serve/run.py --usage` writes the file, adding each key a run hit or recorded under its service, and `tools/gate_fixtures.py` sweeps it whenever it exists: a committed cassette it does not list is `OW-Q-018`, and so is a listed key with no cassette. The bench's agent recordings are this repository's only cassettes, and the nightly `gates` job is the run that writes the file (its replay needs the full-scale corpora, too long for a pull request). It regenerates the file from the three committed sets and compares it with the committed one byte for byte. The first sweep found 15 recordings no replay reached: the later turns of four citation tasks, whose `ow_query` answer changed with #67. They were deleted in one commit, as above.)*
`ow eval record --prune` deletes them in one reviewable commit. The asymmetry is deliberate: a missing
cassette fails loudly at replay, and an unused one would otherwise never fail at all.

## 5. Snapshot testing for parsers: three Reductions and one differ

### 5.1 Never snapshot the document

A committed `DoclingDocument` JSON for a 188-page PDF is 9,000 diff lines nobody reads and a geometry
jitter that becomes a build failure. omniweave commits **Reductions**: deterministic, sorted,
LF-normalised, line-oriented projections, in exactly three kinds. *(Build note, D848: the first goldens are committed. `tools/ow_golden.py` copies every `fixtures/index.toml` fixture into a scratch project and ingests it with a child `ow add`. `omniweave_conform.golden` reduces each stored document through `StoreExportSource` to `fixtures/goldens/core@2026.10/<origin_driver>@<driver_schema_v>/<file>.<kind>`, keeping the file extension because `deck.odp` and `deck.pptx` share a driver. 26 of the 37 fixtures yield a document, three drivers and 78 Reductions; the other 11 are the refusal cases. Two independent ingests reduce byte-identically. `--check` fails on any document that moved, and `--bless --reason` writes the tree and its `BLESS.log` row through `bless.plan()`, a new or lost document being `structural`. The first row blessed all 26, so a second reviewer is printed. An outline preview cut on a space no longer ends its line in whitespace, which an editor would strip.)*

| reduction | volatility | grain | contains | never contains |
|---|---|---|---|---|
| `shape` | **frozen** — a byte diff fails the build | one file per `(corpus, driver, doc)` | per-document counters: block totals by kind and layer, page count, mark counts, `achieved` capability values, `diag` code counts, trust and quote histograms, `quad.present_frac` | text, per-corner geometry, any float that is not `%.4f` |
| `pages` | **tracked** — a diff renders into a PR comment and merges with a blessed reason | one line per page | per-page kind/layer/trust/quote histograms, `cdig`, `ldig`, `diag{}` | text |
| `outline` | **tracked**, suppressed by the byte cap | one line per block | `addr`, kind, layer, trust, quote, `cdig[:8]`, `ldig[:8]`, `preview[:48]` | full text, geometry |

The shape of a frozen Reduction, verbatim from the charter, so there is no ambiguity about the format:

```text
# fixtures/goldens/core@2026.09/parse.office.anydoc@3/eu-annual-report-2019.shape   FROZEN
owshape/1  corpus=core@2026.09  doc=3f2a…  driver=parse.office.anydoc@0.2.4  schema_v=3
achieved.origin_span   none           blocks.total          1284
achieved.spatial       none           blocks.kind.heading     61
achieved.tables        cells_with_spans
diag.OW_TABLE_SPAN_CLAMPED   2        blocks.kind.paragraph  902
grid.tables_with_merges      1        blocks.layer.furniture  83
marks.kind.bold            311        pages.total             42
quad.present_frac       0.0000        quote.normalized       902
rel.kind.note_ref           27        trust.extracted       1240
```

Two details that are load-bearing rather than cosmetic. `%.4f` for every fraction and never a `repr()`,
because `repr(0.1)` is a property of a runtime rather than of a document and is not something to bet a
frozen gate on. And `achieved.origin_span none` with `quote.normalized` (not `verbatim`) is the
**honest** shape for an anydoc-parsed document at release 1 — its upstream carries no per-block source
address (only `Asset.origin_part` at `anydoc/src/model/asset.rs:15`), so INV-10 is unreachable on the
office path and `Q-G6`'s `span_exact_rate == 1.000` holds **vacuously** on that slice. A gate over blocks
that *claim* verbatimness passing vacuously where nothing claims it is the correct outcome, and the
Reduction is where a reader can see that it is vacuous rather than satisfied. *(Build note, D817: `omniweave_conform.reduce.reduce_shape()` writes this file from `archive.owdoc.ExportSource`'s reads, one `key value` counter per line, sorted and unpadded, under the charter's header. The two-column body above is a page layout: a one-counter change is one changed line only when a line holds one counter. Fixed counters always print and histograms print their non-zero buckets. A tombstoned block counts nowhere, and a fraction over no blocks is `none`.)*

**Geometry never enters a frozen Reduction.** It enters `outline` only as `ldig` (the `layout_digest`),
and per-corner tolerance comparison — docling's measured `STRICT_BBOX_TOL_RATIO = 0.0025` and
`FUZZY_BBOX_TOL_RATIO = 0.005` at `docling/tests/verify_utils.py:25-28` — survives only as the diagnostic
`ow eval golden --geometry`, which prints a per-corner delta and is never a gate. A tolerance comparison
in a gate is a gate you will widen.

`Q-G4` asserts that `shape` is byte-identical across **two pdfium minors × nine OS/Python cells**. That
converts the open question about whole-point geometry quantization from an assumption into a measurement,
and it must close (`F31`) **before** the golden suite freezes. The written fallback, so nobody has to
invent one under pressure: if whole-point quantization does not absorb driver jitter, `ldig` leaves
`shape` entirely and moves to `outline` alone, `shape` loses `quad.present_frac`, and `Q-G4` narrows to
"byte-identical across nine cells at one pinned pdfium" with the pdfium axis moved to a `tracked`
comparison. *(Build note, D849: `tools/gate_frozen_stability.py` is built. A cell is `sys.platform`, Python's `major.minor` and pypdfium2's `PDFIUM_INFO`. `--emit DIR` ingests the Tier-A fixtures for real and writes that cell's `shape` Reductions beside a `cell.toml`. The comparison then holds every cell under `--artifacts` to the committed goldens: the golden is the frozen value, not whatever the cells agree on. Fewer than `--pdfium-minors` builds or `--cells` OS/Python pairs exits 2, "did not run", because matching cells below that coverage measure nothing. The fallback above is `--pdfium-minors 1`. No CI job emits a cell yet, so `F31` stays open; the conform tier holds one cell, this machine's, to the goldens.)* *(Build note, D966, a user ruling of 2026-10-23: the pdfium axis is one nightly cell, not nine. On the schedule the `golden` job installs pypdfium2 5.12.1 (pdfium 152.0.7947.0) over the lock's 5.13.0 (153.0.7999.0), emits a tenth cell with `uv run --no-sync`, and runs `--pdfium-minors 2 --cells 9`; a pull request keeps `--pdfium-minors 1`. When the step was written the two builds emitted byte-identical shapes for all 26 goldens on win32 py3.12, so whole-point quantization absorbs this pair's jitter.)* *(Build note, D974: the first nightly since D966, run 40058737353 on aecf5a1 (2026-10-24), passed D966's pdfium axis: 26 shapes, 2 pdfium builds of 2, 9 cells of 9. `tools/ci_step.py` (D975's name for it) reads that step's verdict off the latest nightly through `gh`, and V10-14 runs it.)*

### 5.2 The byte cap is the real constraint, and it is much tighter than 500 pages

`Q-G2` caps a Reduction file at 256 KiB. D10 separately suppresses `outline` above 500 pages. Those are
not the same bound, and the byte cap bites first by more than an order of magnitude. The arithmetic,
because a threshold nobody has multiplied out is a threshold that will be breached by the first realistic
fixture:

| reduction | bytes per line | lines that fit in 262,144 B | what that is |
|---|---:|---:|---|
| `pages` | ~220 (the charter's own "5,000 pages ≈ 1.1 MB") | ~1,190 | ~1,190 pages |
| `outline` | ~96 (63 B of fixed columns plus a ≤ 48-char preview) | ~2,730 | **23-46 pages** at `F1`'s 60-120 blocks per page |
| `shape` | — | — | fixed size, ~40 lines, never near the cap |

So `MAX_REDUCTION_BYTES = 262_144` **is the gate** — it is what `Q-G2` fails on — and the 500-page
rule is a **performance guard only**, a cheap pre-check that stops the reducer materialising ~45 MB of
`outline` lines before discovering it cannot commit them. Both charter sentences survive with their
roles named this way; [ADR-11](adr/0011-eval-register-reconciliation.md) rules it and charter §9.2
`E86` records it at charter `:7104`, `:7316` and `:7416`. **The page rule is not a second threshold
and may not be quoted as permissive**: a fixture under 500 pages is not thereby allowed an `outline`,
and the sidecar records which bound fired (§4.4). The consequences are stated rather than discovered:

- **Most Tier-A fixtures suppress `outline`.** That is correct, not a defect: `outline` exists to make a
  small, dense, hand-reviewed fixture diffable, and a 188-page 10-K is not that fixture. The 40-page,
  24-document Deep golden (§4.6) is the artefact that carries per-block detail, and its bound and
  `outline`'s land in the same place for the same reason.
- **The reducer never truncates.** Above the cap it writes a single line —
  `owoutline/1 SUPPRESSED reason=bytes blocks=17431 would_be_bytes=1673376` — and the sidecar records the
  same. A truncated reduction is silent loss; a suppressed one with a count is a number that grows in
  full view, and `Q-G2` ratchets `blocks` so growth needs a bless. *(Build note, D818: `reduce_pages()` and `reduce_outline()` write the two tracked kinds under `shape`'s header, as `owpages/1` and `owoutline/1`. The cap binds `pages` too, since the arithmetic above puts it at ~1,190 pages, and above it `pages` is the same one line with `pages=N`. The 500-page guard writes `reason=pages` before a line is built. Both kinds use `shape`'s full bucket names rather than the charter's `para` and `furn`, because the churn classifier compares them counter by counter.)*
- **A generated fixture commits no Reduction at all.** The 5,000-page PDF's `pages` file would be 1.1 MB
  and its `outline` 45 MB; both live in `fixtures/generated/`, which is `.gitignore`d, and the assertion
  for those fixtures is a Counter and a `shape` file, which is fixed-size and cheap.

### 5.3 The diffing strategy

`ow eval golden` produces a **three-part diff, ordered by information density**, and the PR comment is
capped at 400 lines:

1. **the `shape` delta**, as a table of changed counters with old, new and signed delta. This is the
   sentence a reviewer needs: "6 fewer tables, 174 more cells" tells you what happened; 9,000 lines of
   `pages` diff does not.
2. **the `pages` rollup**: per-page lines grouped by *which fields changed*, with a count per group and at
   most three example page numbers per group. Folding is the same mechanism `Finding` uses (200
   occurrences become one row with `count=200` and ≤ 3 examples), and it is one implementation.
3. **the first 40 changed `outline` lines**, unfolded, as a unified diff. Because the digest is the
   assertion and the preview is a comment for the human, a one-character upstream change is **one changed
   line**, not a re-wrapped paragraph diff. *(Build note, D821: `omniweave_conform.golden_diff.render()` writes the three parts for one document. Delta rows are `key old -> new (signed)`. `pages` groups are named by their sorted changed fields, or `+page` and `-page`, largest first, each with `Finding`'s `EXAMPLES_MAX` pages imported rather than retyped. `outline` is a zero-context unified diff cut after 40 changed lines, and the 400-line cap is the comment's, cut at 399 plus a line counting the rest.)* *(Build note, D850: `golden_diff.comment()` writes the comment for every document a change moved, each under a `document <path>:` header and all under the one 400-line cap. `tools/ow_golden.py --diff` prints it between the class lines and the verdict, with `--check` or `--bless`, and changes no exit code. A new or lost document is diffed against three empty files. A suppressed side against a missing one, which raised before, is now its one line.)*

### 5.4 Acceptable churn, defined as a classification rather than a percentage

A line-count threshold on golden churn is unenforceable: a legitimate driver upgrade changes every line
of `pages`, and a reducer bug changes three. So the gate classifies the diff into a **churn class** and
gates on the class.

| churn class | definition | treatment |
|---|---|---|
| `incidental` | every changed line's changed fields are confined to `cdig` and `ldig`; every per-line counter and every histogram is unchanged; the `shape` delta is empty | merges with a one-line `BLESS.log` reason. A digest change with no counter change is a payload edit, which is the expected shape of an upstream text fix |
| `structural` | a `kind{}`, `layer{}`, `trust{}` or `quote{}` histogram moved, or a line was added or removed | requires a **non-empty and consistent** `shape` delta, a `BLESS.log` reason ≥ 20 characters naming the driver version or the code change, and a **second reviewer once more than 20% of golden files change structurally** |
| `unexplained` | a `pages` or `outline` change with an **empty `shape` delta** and no page-count change, over counters the decomposition table declares page-wise | **fails the build**, `OW-Q-012`. This is the class that catches a non-deterministic reducer, a dict-order leak into a sorted projection, or a per-page rollup that disagrees with the per-document counters it is supposed to sum to |

`unexplained` is the whole reason the classification exists, and it rests on an arithmetic claim that has
to be true rather than assumed: **`shape` is a per-document rollup of exactly the quantities `pages`
reports per page.** That is true of the histograms and false of at least one counter —
`grid.tables_with_merges` counts tables, and a table can span pages, so the per-page sum double-counts it.
So the claim is not asserted globally; it is declared per counter, in a table the reducer reads:

```toml
# fixtures/goldens/DECOMPOSITION.toml -- byte-diff gated. Read by the churn classifier.
# `page_wise = true` means: the shape counter is exactly the sum of the per-page counter over pages,
# and therefore a `pages` change with no `shape` change is arithmetically impossible.
[[counter]]
id = "blocks.total"
page_wise = true
[[counter]]
id = "blocks.kind.*"
page_wise = true
[[counter]]
id = "trust.*"
page_wise = true
[[counter]]
id = "quote.*"
page_wise = true
[[counter]]
id = "marks.kind.*"
page_wise = true
[[counter]]
id = "diag.*"
page_wise = true
[[counter]]
id = "grid.tables_with_merges"
page_wise = false
reason = "a table may span pages; the per-page sum double-counts it"
[[counter]]
id = "rel.kind.*"
page_wise = false
reason = "a relation is a document-level edge and has no page to be counted on"
[[counter]]
id = "quad.present_frac"
page_wise = false
reason = "a fraction, not a count; the page-wise sum is meaningless"
```

The classifier evaluates `unexplained` only over `page_wise = true` counters, and the file is byte-diff
gated so the exclusion list cannot grow quietly — which is the actual failure mode, because the cheapest
way to make an `unexplained` failure go away is to add a row. A new `shape` counter with no row in this
file is a build failure, in both directions, under `Q-G10`'s existing "declared but never written" shape. *(Build note, D819: `fixtures/goldens/DECOMPOSITION.toml` holds twelve rows, the nine above plus `blocks.layer.*`, `pages.total` and `achieved.*`, which `shape` also writes; and `omniweave_conform.churn` holds them to `reduce.SHAPE_FAMILIES` both ways. `diag.*` is `page_wise = false` there, with its reason: a diag with no page counts in `shape` and on no page line, so the cross-check would call every document-level diag `unexplained`. The cross-check runs only where `pages` prints a family, so `marks.kind.*` is declared and never checked. `OW-Q-012` is the first `OW-Q` row in `codes.toml`.)*

### 5.5 Blessing an intentional change

```console
$ OMNIWEAVE_BLESS=1 ow eval golden --bless --reason \
    'anydoc 0.2.5 fixes w:instrText field-code text; 41 outline lines, no histogram change'
  fixtures/goldens/core@2026.09/parse.office.anydoc@3/  41 files
  churn: incidental=39  structural=2  unexplained=0
  shape delta (2 files):  blocks.kind.paragraph +3  quote.normalized +3
  wrote BLESS.log (1 row)  ·  second reviewer NOT required (2/41 = 4.9% structural)
```

Four requirements, all mechanical:

1. **`OMNIWEAVE_BLESS=1` in the environment.** `test_bless_flag_is_off()` — docling's
   `tests/test_data_gen_flag.py` adopted whole, three lines of it — asserts the flag is off in CI, so a
   contributor who leaves it exported locally cannot land a self-blessing PR.
2. **A `BLESS.log` row in the same commit as the reduction change,** with a reason of ≥ 20 characters.
   `Q-G3` fails a frozen or tracked diff with no matching row. The row's grammar is
   `<iso8601-date>\t<git-author-email>\t<reduction-glob>\t<churn-class-counts>\t<reason>`, one line, LF,
   append-only — the same shape as `codes.toml`, so the same append-only check applies. *(Build note, D841: `tools/gate_bless.py` is the gate. Merges are squash-only, so it judges the change that lands: the diff from the merge base with `--base` to `--head`, and `eval/BLESS.log` at each end. On the base branch it judges the last commit. A guarded path is a `.shape`, `.pages` or `.outline` under `fixtures/goldens/`, or anything under `schema/expected/` or `eval/baselines/`. Each needs an added row whose glob matches it, and a row that blesses nothing fails, since the log can never drop it. An added row with `unexplained` above 0 fails, and one above 20% `structural` prints that it needs a second reviewer, as counting reviews needs the forge. A change to the two footed trees also needs a `Bless:` line mirroring an added row's reason. `OMNIWEAVE_BLESS=1` in the gate's own environment fails, which is `test_bless_flag_is_off()` at `X`.)*
3. **A second reviewer once the structural share exceeds 20% of golden files.** The threshold is on
   `structural`, not on total files: 400 `incidental` digest changes from an upstream text fix is one
   reviewer's judgement, and 9 `structural` changes out of 41 is two.
4. **No `unexplained` rows.** There is no override. `ow eval golden --explain <file>` prints the
   arithmetic disagreement between `shape` and `pages` for that file, which is what a reviewer actually
   needs. *(Build note, D820: `omniweave_conform.bless` implements the four requirements: the flag read from an environment the caller passes, the row grammar with a `YYYY-MM-DD` date and `incidental=,structural=,unexplained=` counts, append-only as an old-file prefix, and the second reviewer strictly above 20% of the files that changed, unchanged ones excluded. `covers()` is Q-G3's question, and `schema_bump_only()` is section 5.6's mask on the header's `schema_v=` alone.)* *(Build note, D851: `churn.explain()` is the arithmetic. For each page-wise counter that `pages` prints and that moved, it prints the move in `shape` beside the move summed over `pages`, then `agrees` or `DISAGREES by` the gap. These are moves, not totals, because the classifier judges moves. A last line counts the disagreements, or says no page-wise counter moved, which is the `outline`-only case. `tools/ow_golden.py --explain <file>` narrows the check to that document, prints its class line and the arithmetic, and may not be given with `--bless`. The `--mask` form for a schema bump (section 5.6) is not built.)*

### 5.6 The one event this discipline does not survive unaided: a schema bump

A `shape` header carries `schema_v=3`. When the owdoc schema major bumps, **every frozen Reduction in the
repository changes on one line**, and the discipline above would demand a bless per file and a second
reviewer on a diff nobody can read. That is the event where a snapshot system either gets a mechanism or
gets a `--force`, and there is no `--force`.

The mechanism: `ow eval golden --bless --schema-bump <old>-><new>` regenerates every `shape` file in one
commit, and the gate accepts it under one condition it checks rather than trusts — **masking the
`schema_v` field must make the diff empty.** If it does not, the schema bump also changed a counter, the
`--schema-bump` path refuses, and the change goes through the ordinary `structural` path with the real
diff visible. One `BLESS.log` row covers the whole regeneration, naming both schema versions, and the
second-reviewer rule is waived only on the masked-empty branch. `ow eval golden --explain --mask schema_v`
prints the proof. *(Build note, D852: until this cell the event could not be blessed. Every churn reader skipped a file's first line, so a header-only change classified `unchanged`, `--check` passed with every byte different, and `--bless` had nothing to write. `churn.classify()` now makes a moved header `structural`, naming the fields that moved, and adds that reason to any other class. `tools/ow_golden.py --bless --schema-bump OLD->NEW` refuses unless every moved file is masked-equal under `schema_v`, from exactly `OLD` to exactly `NEW` (`bless.schema_bump()`), with no document new or lost. It writes one row whose reason ends `(schema bump OLD->NEW)` and waives the second reviewer. Without the flag the same change is 26 of 26 structural and asks for one. `--explain --mask schema_v` is not built, and Q-G3's gate still prints its second-reviewer note for such a row.)*

The same mechanism serves a reducer version bump (`owshape/1` → `owshape/2`), which is the other
whole-corpus rewrite, and for the same reason: a mass change that is provably confined to one field is a
different review problem from a mass change that is not, and the gate can tell them apart.

### 5.7 The semantic differ is `rebind()`, and there is no second one

```python
def diff_deep(golden_dir: Path, fresh: "Doc") -> "RebindReport":
    """Import fixtures/goldens/deep/<doc>.owdoc.d/ into a scratch .owstore as gen 1, import
    `fresh` as gen 2, and return rebind(store, doc_ord, to_gen=2, threshold=...)."""
```

`rebind()`'s three rules — equal `content_digest` under the same parent carries the `block_id`; equal
`addr` + `kind` with a changed digest carries it and bumps `revision`; otherwise a fresh id plus a
`block_history` row — **are** a snapshot diff, and
`RebindReport{carried, revised, created, retired, match_rate_by_page, quarantined}` is a snapshot diff's
output. One implementation, two consumers: the model layer already tunes the threshold and quarantines
below it, so the golden's tolerance is the same number the product depends on. A second semantic differ
would be a second tolerance to drift.

The Deep golden is the only committed artefact from which a semantic diff can be produced after a driver
upgrade, which is why the exploded form matters: `rebind()` needs two real generations in a real store,
not two JSON blobs.

## 6. Property-based tests

### 6.1 The properties worth asserting

A property earns its place when it states an invariant that a fixture can only sample. The register below
is the **named, load-bearing** set: 23 properties comprising **100** distinct `@given` functions. The
remaining 158 of T1's 258 are the mechanical per-module properties already itemised in §2.2 — enum wire
round-trips, digest stability under field reordering, framing fuzzers — and they are covered by
`Q-G24`'s inventory ratchet rather than by a row here. Nothing in this register is a conformance
assertion: the driver testkit's ~120 properties per subject are T3 and are counted in §2.4's 1,452.

| # | property | statement | n | why a fixture cannot do it |
|---|---|---|---:|---|
| P-1 | **archive round-trip** | `import(export(store)) == store` over any generated corpus, compared on `canonical_projection()` modulo surrogate ids | 6 | the failure is in the interaction of frame boundaries, retired generations and `IFNULL` sentinels, which no hand-written corpus hits |
| P-2 | **serializer round-trip** | for each of the five core-owned views, `serialize()` returns `(str, SpanMap)` where every SpanMap entry's slice of the string equals the Block's text under `normalize_k` | 10 | a SpanMap off by one at a table boundary is invisible until a citation resolves to the wrong cell |
| P-3 | **id stability across re-parse** | for any generated document and any *payload-only* mutation (text edits, mark changes) that leaves `(addr, kind)` intact, `rebind()` carries every `block_id` and every `cite`, and `revision` increments exactly on the mutated blocks | 8 | this is the property a shipped citation depends on, and its failure mode is silent |
| P-4 | **cite non-reuse** | over any sequence of parse generations, `doc.next_cite_n` is strictly monotone, no `cite` value is ever emitted twice for one `doc_key`, and a retired cite resolves through `block_history.superseded_by` or refuses with `OW_CITE_RETIRED` — never resolves to a nearby Block | 5 | write-order-derived numbering passes every fixture and fails on the first re-parse that reorders |
| P-5 | **cache-key correctness, both directions** | (a) two invocations with equal `(driver_id, driver_schema_v, semantic_digest, unit content_digest, isolation)` produce the **same** `cache_key()`; (b) changing **any one** of those inputs produces a **different** key | 7 | direction (b) is the one that matters and the one nobody tests: a key that ignores `driver_schema_v` serves last release's output forever |
| P-6 | **cache-key layer separation** | keys from two different `CacheLayer`s never collide, asserted by domain separation in `ow128`'s `person=` parameter over 10⁴ generated inputs | 2 | a collision is a wrong answer, not a crash |
| P-7 | **provenance resolvability** | every `cite` in every rendered Answer over any generated corpus resolves to a Block, a page and either a `Quad` or a `Locus.reason`; `Locus.reason` is non-`None` **iff** `quad is None` | 9 | INV-9's biconditional is exactly the shape a fixture asserts in one direction and a property in both |
| P-8 | **citation soundness under damage** | after any single `Injector` (§8.6), every surviving `cite` still resolves and no new `cite` appears | 4 | damage interacts with the emission ledger and the freshness gates in combinations a fixture cannot enumerate |
| P-9 | **`fuse()` versus `ceiling()`** | over channel sets whose members are **all** `OK`, `fuse()[0].score == ceiling()` to 1e-12; with **any** `EMPTY` member, `fuse()[0].score < ceiling()` **and** `confidence < 1` | 3 | stated in one half it is false on the shipped default, because an empty `exact` channel is routine — the two-half form is the only correct statement |
| P-10 | **fusion total order** | `FusedHit` sequences are totally ordered on `(-score, (doc_ord, page, ord), block_id)` (D655) and stable across a `VACUUM` and an FTS5 `optimize` | 2 | ties broken by storage order are nondeterministic and only appear after maintenance |
| P-11 | **absence-gate precedence** | for any subset of the fifteen gates forced to fire, the reported gate list is in precedence order, and `state == ABSENT` requires **all fifteen** to pass; a semgrep rule asserts exactly one `return VerdictState.ABSENT` site | 6 | 2¹⁵ combinations |
| P-12 | **escalation monotonicity** | for every generated Evidence record and policy, `child.rung > parent.rung` on every escalation edge, and a `DEGRADE` is still a forward move | 4 | INV-13, and the counterexample is a policy shape, not a document |
| P-13 | **`evaluate()` purity** | identical `(policy, evidence, hints)` produces an identical decision across 100 catalog shuffles, two processes and two `PYTHONHASHSEED`s | 3 | a dict-iteration dependence is invisible in one process |
| P-14 | **budget never changes the rung** | for any policy and evidence, `evaluate()`'s chosen rung is identical with the ledger empty and with it exhausted; only `admit()`'s outcome differs | 3 | INV-14, and the violation is a refactor away at all times |
| P-15 | **grid exactly-once cover** | for any table with any legal merge topology, `build_grid` covers every `(r, c)` exactly once, and `up/down/left/right/top_heading/left_heading` are total | 5 | merge topologies are combinatorial |
| P-16 | **incremental converges to full** | for any generated 20-step mutation sequence, the incremental store's `canonical_projection()` equals the full rebuild's, byte for byte | 4 | `G19`'s 300-document/40-mutation gate is the sampled version; the property is the general one |
| P-17 | **anchor delta correctness** | after any mutation that removes an anchor name, every `edge` and `block_link` carrying that `bound_by` is unbound, and no row without it is touched | 3 | skipping the equivalent pass measured **4.3% of distinct edges wrong, in both directions, silently** in codegraph |
| P-18 | **packing monotonicity** | a larger tier never receives fewer chars/doc, and truncation cuts whole Answer sections and whole blocks, never mid-fence | 4 | SV4 |
| P-19 | **quote grounding** | for any model-claimed verbatim quote and any Block, `Grounding` either finds the span under `normalize_k` or quarantines; it never returns an offset the model supplied | 3 | the model is never asked for an offset, and the property is what keeps it that way |
| P-20 | **splice transactionality** | for any 10k random-operation batch, the IL file is always parseable or unchanged | 2 | OUT17 |
| P-21 | **calibration monotonicity** | for any generated label set, `separation()` returns `pass` only if `p_hat` is strictly increasing **and** adjacent Wilson intervals are non-overlapping; a monotone-but-overlapping input returns `unknown`, never `pass` | 3 | the two conditions are independently violable |
| P-22 | **`MeasuredOn` totality** | constructing `MeasuredOn` with any proper subset of its ten fields raises `TypeError`; `weights_revision = "main"` raises | 2 | HunyuanOCR's published 94.10 OmniDocBench was measured on TensorRT while the repo ships Transformers and vLLM and admits they disagree — the regression fixture constructs exactly that row and asserts refusal |
| P-23 | **the quote ladder is ordered, and its two top rungs are not equal** | over generated NFD, soft-hyphenated, ligatured and case-varied `(decoded, text)` pairs: (a) `nfc(d) == t` implies `normalize_k(d)[0] == normalize_k(t)[0]`, so every `VERBATIM` block also satisfies the `NORMALIZED` predicate; (b) the converse **fails** on the case-varied generator, so the two rungs are not one rung with two names | 2 | half (a) is arithmetic over the whole Unicode plane and half (b) is the reason INV-10 stopped reading `normalize_k` ([03](03-document-model.md) §7.2); a fixture proves neither direction, and asserting only (a) would pass on a `VERBATIM` predicate that had silently widened back |
| | **total** | | **100** | |

### 6.2 Three pairs that look redundant and are not

**P-5(a) and P-5(b) are different tests with different failure modes.** (a) is a determinism property: a
key that varies per process makes every cache a miss, which is graphrag's shipped defect and costs money.
(b) is a **correctness** property: a key that ignores an input serves a stale answer, which costs truth.
A single "the key is a pure function of its inputs" test proves (a) and says nothing about (b), and (b)
is asserted per input field, one `@given` per field, so a new field added to the recipe without a test
fails `Q-G24`'s inventory ratchet.

**P-3 and P-4 are different properties.** P-3 says an id is carried when it should be; P-4 says a token is
never reused even when it is not carried. A parser that mints a fresh `block_id` for every block on every
re-parse satisfies P-4 trivially and fails P-3; a parser that reuses `cite` values from a free-list
satisfies P-3 and fails P-4. Both failures ship a wrong citation to a user who saved a link.

**P-7 and P-8 are different properties.** P-7 asserts resolvability on a healthy corpus; P-8 asserts it
under exactly one named damage. The interesting failure is a citation that resolves everywhere except
where a `Diag` fired, which is the population a healthy-corpus property never samples and the population
an absence claim is made from.

## 7. Determinism where models are involved

### 7.1 What can be pinned, and what cannot

| pinnable, and pinned | mechanism |
|---|---|
| weights identity | `MeasuredOn.weights_revision` is an **exact SHA**; `"main"` raises at construction, and `G8`'s semgrep bans `revision="main"` in library code — docling's own layout-model revision defaults to `"main"` at `docling/docling/datamodel/layout_model_specs.py:87,94,101,108,115,122`, six times in one file |
| tokenizer identity | part of the driver's `[deps] pins` digest, which enters the cache key |
| prompt text | `MeasuredOn.prompt_version` plus the two prompt digests in `embed_space`'s nine identity fields |
| sampling | `MeasuredOn.sampling` is a `Mapping[str, Scalar]`: `{"temperature": 0.0, "top_p": 1.0, "max_tokens": …, "batch": 1}`, `{}` for a deterministic path |
| rasterization | the render profile digest — DPI 150, RGB8, `binarize = false`, a named resampling filter, alpha flattened onto white — carried as a `sampling` key, because a resampling-filter change moves every OCR score in the corpus and nothing else records it. The profile itself is [ingest and routing](05-ingest-and-routing.md)'s; the obligation to digest it into `MeasuredOn` is this document's |
| process environment | `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR`, cwd, `SOURCE_DATE_EPOCH=0` |
| runtime identity | `MeasuredOn.runtime` and `runtime_version`, required and defaultless |

| not pinnable | what the harness does about it instead |
|---|---|
| continuous-batching composition | a vLLM forward pass's output depends on which other requests were merged into it. Declared as `ReplayClass = "unpinnable"`, measured as a k = 5 envelope, and **held constant rather than pinned**: the Guard's paired test compares one runner, one corpus and one driver version, so batch composition is noise inside the comparison rather than a term of it |
| GPU kernel selection, TF32, cuDNN autotune | recorded in `eval_run.hardware` and `MeasuredOn.runtime_version`; a change in either is a **baseline reset**, not a regression |
| non-deterministic attention reductions | float accumulation order across a fused kernel; absorbed by the same envelope, and the reason `byte_exact` is unavailable to any GPU path |
| a hosted API's model behind a stable name | sets `eval_run.unpinned = 1`, which forces `UNRANKED` and forbids a `[[quality.benchmark]]` row (§7.2) |

The rule that ties the two tables together: **an unpinnable axis is either recorded in `MeasuredOn` or it
is a reason a number cannot be ranked.** There is no third disposition, and in particular there is no
"noted in the report" — a caveat that is not a column is a caveat that does not survive the second
release. *(Build note, D831: Q-G8's static half is `tools/gate_measured_on.py`. It builds each committed `eval/results/**.json` row's `measured_on` through `MeasuredOn` itself, via `omniweave_conform.scoreboard.unmeasured()`, so the bytes and the dataclass cannot disagree about what complete means. A missing or unknown field is named first. Every row is checked, an UNKNOWN one included, and an absent tree passes by name.)*

### 7.2 The three replay classes, and the separate bit that governs publication

Tested **per declaration** by the conform `determinism` suite, so a card claiming a stronger class than it
delivers fails.

| `ReplayClass` | k | equality asserted | band | on failure |
|---|---:|---|---|---|
| `byte_exact` | 2 separate processes with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd | equal `content_digest` **and** `layout_digest` per block, and an identical `Diag` multiset | 0 | the suite fails; the card must declare `seeded` or `unpinnable` |
| `seeded` | 3 | mismatched-block fraction | ≤ `drift_band`, which the **kit measures and writes into the card**; ceiling `MAX_DRIFT_BAND = 0.02` | above the ceiling the class must be `unpinnable` — a "seeded" driver with 5% drift is an unpinnable driver with a comforting label |
| `unpinnable` | 5 | none | a stability envelope: coefficient of variation of the headline metric ≤ 0.05, plus `diag_set_stable` (the `Diag` code **set**, not multiset, is equal across all five runs) | the card's declaration is wrong in the only direction that matters and the suite fails |

**`unpinnable` is not `unpinned`, and the publication rule keys on the second.** Charter §D10 states the
rule — *a driver whose `MeasuredOn.weights_revision` is not an exact SHA may not contribute a
`[[quality.benchmark]]` row at all; it gets a scoreboard entry stamped `unpinned`, displayed and never
ranked* — inside the `unpinnable` paragraph, which reads as though the two were one thing. They are two
axes and they must be kept apart, because conflating them costs a real capability:

- `ReplayClass` describes the **output's** reproducibility given identical weights. It is a card claim,
  tested by the `determinism` suite.
- `unpinned` is `eval_run`'s bit, set when `MeasuredOn.weights_revision` is not an exact SHA. It
  describes whether the **weights are identified at all**.

A locally hosted VLM under vLLM continuous batching is `ReplayClass = "unpinnable"` with a pinned weights
SHA: it may publish a benchmark row, and the row is `UNRANKED` only if some other clause makes it so. A
hosted API behind a stable model name is `unpinned` whatever its `ReplayClass` claims: it may not publish
a row at all. Both force `UNRANKED` in `eval_scoreboard`; only `unpinned` forbids the card row. Recorded
as Q-Q4.

`MAX_DRIFT_BAND = 0.02` **extends the charter**, which specifies a kit-measured `drift_band` with no
ceiling. Without one, `seeded` absorbs `unpinnable` by declaration, and the distinction the charter drew
three values for collapses back into a boolean. The number is chosen at the point where a 1,000-block
document's drift (20 blocks) is still smaller than `rebind()`'s quarantine threshold, so a `seeded`
driver's re-parse still carries its ids.

### 7.3 Cassettes: why coverage is complete by construction

A Cassette is a content-addressed, replayable request/response log recorded, for everything that ships, at exactly two sites (`bench/serve/`'s scripted agent records at a third, bench-only site, `bench.agent`: [ADR-14](adr/0014-reference-corpora-and-control-arm.md) D14.4):
`DriverIO.service()` and `omniweave_core.modelserver`. Those are **the only two outbound model channels a
driver has** (INV-6), so there is no third place a model call can hide and no per-driver instrumentation
to forget.

| aspect | rule |
|---|---|
| key | `sha256_canonical({service, model_key, prompt_digest, sampling, payload_digest, contract})`. The request bytes are **not** the key: two logically identical calls differing in JSON key order must hit |
| `contract` | the recording site's own contract identity — the pair `(seam, contract_major)` where `seam ∈ {"driver_io.service", "modelserver"}` and `contract_major` is `omniweave_core.contract.CONTRACT` for the first and the model server's declared API major for the second. It is in the key so a seam change invalidates every recording made against the old one, rather than replaying a body the new code will misparse |
| storage | `fixtures/cassettes/<service>/<key[:2]>/<key>.json`, one file per interaction, so a re-record is a reviewable per-call diff and not a 40 MB blob; ≤ 256 KiB each and ≤ 32 MiB total (§4.7) |
| redaction | recorded through the same `<ow:untrusted>` wrapper the runtime uses, with API keys, `Authorization` headers and any `Grant` `dpa_ref` replaced by their sha256 before write. `Q-G1`'s manifest rule applies: a cassette is a fixture |
| modes | `off` (no interception), `allow` (record on miss, for local development), `required` (a miss is `OW-Q-004` and never a live call). CI is always `required`; `eval_run.cassette` records which mode produced the row |
| re-recording | `ow eval record --service <name>` re-records one service, and the resulting diff is reviewed like a golden change: a cassette change with no code change is either a model version change or a prompt change, and both are `MeasuredOn` fields |
| staleness | a cassette whose `contract` or `prompt_version` no longer matches the code is a **miss**, not a hit. A stale cassette that silently answers is the worst of both worlds |
| orphans | swept by `Q-G2` against the generated `eval/cassette-usage.toml` (§4.7); an unhit committed cassette is `OW-Q-018` |

The consequence worth stating: T2, T3 and the parity job never make a network call, so the
`contributor-parity` claim — `uv sync && pytest` green offline, GPU-free and Node-free in under ten
minutes — is a real claim about a real container rather than an aspiration. *(Build note, D842: `tools/gate_parity.py` is Q-G22's gate, and all three of its flags are required. Offline is an audit hook in a `sitecustomize` on `PYTHONPATH`, G15's mechanism, so it reaches every Python process of the run. It refuses a connect, a send or a name lookup that leaves the machine. Loopback and the unspecified addresses stay open, since a container with no network still has `lo`, and a negative control proves the hook loaded. The offline switches cover the rest. GPU-free hides the CUDA, HIP and ROCm devices. Node-free drops every `PATH` entry holding `node` and is refused if `node` still resolves. The run is `uv sync --offline` and then T1/T2, timed against `contributor_parity_s`'s 420 + 180 = 600 s and killed at the ceiling. The container itself stays CI's.)*

## 8. Retrieval, extraction and absence evaluation

### 8.1 The assertion model: olmOCR-Bench's record, generalised

`eval_assertion` adopts `olmocr/olmocr/bench/tests.py`'s schema — the highest-leverage artefact in the
mined collection — and extends it. The original eight types plus omniweave's six:

| type | origin | asserts | `evaluable_in` |
|---|---|---|---|
| `baseline` | olmOCR-Bench | the output is non-degenerate: length, non-repetition, alphanumeric fraction | `both` |
| `present` / `absent` | olmOCR-Bench | a normalised string is present / absent, within `max_diffs` edit distance | `both` |
| `order` | olmOCR-Bench | string A precedes string B in reading order | `both` |
| `table` | olmOCR-Bench `TableTest` | **a relation, not a string**: a target cell plus `up`, `down`, `left`, `right`, `top_heading`, `left_heading`, at `threshold = max(0.5, 1.0 - max_diffs/len(cell))` | `both` |
| `math` | olmOCR-Bench | a KaTeX-rendered ground truth matches | `both` |
| `format` | olmOCR-Bench | a mark (bold, italic, heading level) is present on a span | `both` |
| `footnote` | olmOCR-Bench | the footnote text is a distinct Layer, not inlined into the body | `owdoc` |
| `cell_rel` | **ours** | the same relation as `table`, but asserted against `Grid.up/down/left_heading` in O(1) rather than by re-parsing a markdown table | `owdoc` |
| `field` | **ours** | a schema field's extracted value equals a literal, under numeric tolerance and normalised strings | `both` |
| `span` | **ours** | the Block's `OriginSpan` re-verifies against the retained part on the declared branch (`bytes` / `nodepath` / `glyphs`) | `owdoc` |
| `cite` | **ours** | a specific `cite` resolves to a Block on a specific page with a `Quad` or a stated reason | `owdoc` |
| `roundtrip` | **ours** | after `compile` then `read_back`, exactly one Block carries `x["x.ow.el"] == e.el` with the expected kind and NFC-equal text (law R2) | `owdoc` |
| `absent_field` | **ours** | a field the document genuinely does not contain is extracted as `null`, not invented | `both` |
| `null_kept` | **ours** | a planted must-be-null field survives the schema transform — lift's own adversarial category, and `make_properties_nullable` is what makes it possible | `both` |

Three design points inherited deliberately:

- **`evaluable_in ∈ {owdoc, text, both}`** exists because omniweave must compare marker's `<table>` against
  docling's OTSL against a VLM's markdown against its own `Grid`. A `both` assertion runs on the text
  evaluator (for cross-tool comparability) *and* the owdoc evaluator (which is stricter and can resolve an
  `addr`). Divergence between the two evaluators on one assertion is itself a finding, and it is the
  finding that catches a serializer bug the text side would have hidden. *(Build note, D826: the text evaluator judges `table` over the candidate's markdown pipe tables and HTML tables, through `omniweave_conform.tables`, with a span filling every slot it covers. A cell matches when `1 - distance / len(string)` reaches olmOCR-Bench's `max(0.5, 1 - max_diffs / len(cell))`. `top_heading` is row 0 and `left_heading` column 0. Section 8.5's transposed table fails every relation and still passes `present`.)*
- **`checked ∈ {verified, rejected, NULL}`**, the human review state, lives **in the assertion record**. A
  `checked IS NULL` assertion **runs and never scores**, and the excluded count is printed on every
  report. This is olmOCR-Bench's `TestChecked` and it is the difference between a benchmark you can grow
  incrementally and one you have to freeze. *(Build note, D912: a Tier A fixture's assertions are `<file>.assertions.toml` beside it, `omniweave_conform.labels`: `schema = "omniweave.assertions/1"` and one `[[assertion]]` a row, `id` and `type`, then `page` (1-based), `checked`, `max_diffs`, `slices`, `addr` and `evaluable_in`, every other key the type's `spec`. TOML has no null, so an absent `checked` is NULL: a drafted assertion is inert until a reviewer writes `verified`. Slices default to the sidecar's `[fixture.tests] slices`. The labels are digested with the fixtures, so a relabel is a new corpus version. `ow eval run --suite parse` judges them over each labelled fixture's parse, decoded into a scratch store and served page by page as Markdown, so a `table` assertion meets the table `ow` serves; `rollup()` turns the verdicts into `order_acc`, `table_rel_acc` and `field_acc`, and each run says how many ran unscored. `structure_f1` still has no reference.)* *(Build note, D982: the reference landed, so `structure_f1` computes. `omniweave_conform.structure` reads a fixture's `<file>.structure.jsonl` -- a `{"schema": "omniweave.structure/1"}` header, then one `(page, kind, layer, parent_kind, text)` tuple a line carrying `checked`, `max_diffs` and `slices` as an assertion does -- matches it one-to-one against the parse's TEXT-BEARING Blocks under `normalize_eval` within `max_diffs`, and scores F1 over the triples, macro over documents then slices with the closed-form `se` rather than a Wilson interval, which is defined over 0/1 trials. A text-less Block (a `table`, a `table_cell`, a `list`, a `picture`) is outside both denominators and its kind is scored through its children's `parent_kind`. A document scores only when EVERY row of its reference is signed, because a part-signed reference has no precision denominator: the ten drafted office references (59 rows) therefore read `unknown` and `release-check` refuses them, naming the `.structure.jsonl` rows as the fix. `parse.pdf.pdfium` is not applicable by its own card -- `sections = "none"` with `tables = "none"` (02:266, F4) -- so its run says so and writes no row, because scoring a driver that emits no heading or table against a labelled tree measures the declaration.)*
- **`explanation TEXT NOT NULL`** on every `eval_verdict` row. olmOCR-Bench prints why an assertion
  failed; so does omniweave. A pass/fail with no explanation is a number you cannot debug and therefore
  cannot improve. The DDL's `DEFAULT ''` is load-bearing at scale: a **passing** verdict stores an empty
  explanation and only a failure carries text, which is what keeps §11.4's retention arithmetic tractable. *(Build note, D825: `omniweave_conform.assertions.evaluate_text()` is the text evaluator for `present`, `absent` and `order`. Both sides go through `normalize_eval`, and "within `max_diffs`" is approximate substring matching, the least Levenshtein distance to any substring by Sellers' algorithm. `order` compares the earliest end of `before` with the latest start of `after`. A failure prints the asserted string and the nearest text found with its distance. `table` and `math` are refused by name until their parsers land, and the owdoc-only types are refused outright.)*

### 8.2 Two normalisers, because the evaluator's job is not the grounder's

The obvious move is to reuse `normalize_k`, and it is wrong. `normalize_k()` is the **grounding**
normaliser — NFKC plus casefold plus the `Cf`, soft-hyphen, dash and whitespace operations
[structure extraction](06-structure-extraction.md) §1.7 enumerates once — and grounding is the one
job casefolding is right for. Adding markdown handling to it would change what a grounded quote
means, and it casefolds, which is correct for grounding a quote and wrong for a benchmark: a parser
that lower-cases every heading would score identically to one that does not.

**`normalize_k` is not INV-10's normaliser either, and this document does not define one.** INV-10's
`bytes` branch proves under `nfc()` — `unicodedata.normalize("NFC", s)` and nothing else, defined in
[structure extraction](06-structure-extraction.md) §1.7 and stated for INV-10 in
[document model](03-document-model.md) §7.2, which is that predicate's sole home. The distinction is
what the second normaliser is argued against: a **proof** normaliser folds less than a comparison
normaliser, and `normalize_eval` is a comparison normaliser. Borrowing `nfc()` for the evaluator
would score a parser that emitted `‘` where the reference has `'` as wrong; borrowing `normalize_k`
would score a parser that lower-cased every heading as right. The evaluator needs the fold between
them, and that is the only reason it exists.

So the evaluator gets its own entry point, and it is a **composition rather than a second
implementation**:

```python
# omniweave_conform/normalize.py
from omniweave_core.ident import fold_common   # the shared table: Cf, dashes, whitespace, NFKC

def strip_md(s: str) -> str:
    """olmOCR-Bench tests.py:47-81, exactly: <br> and <br/> to a space; PAIRED **bold**, __bold__,
    <b>, <i>, *ital* and _ital_ stripped (paired, so `**a \n\n b**` is not matched)."""

def normalize_eval(s: str) -> str:
    """The text evaluator's comparison normaliser. NOT normalize_k: no casefold, plus the quote
    table NFKC does not perform ('‘’‚' -> "'", '“”„' -> '"')."""
    return fold_common(strip_md(s), quotes=True, casefold=False)
```

Three rules follow, and each is a gate rather than a convention:

1. **The owdoc evaluator uses `normalize_k` and never `normalize_eval`.** A Block's `text` contains no
   `<`-delimited markup by construction ([03](03-document-model.md) forbids it), so there is nothing for
   `strip_md` to do and running it would only mask a serializer that emitted markup into `text`.
2. **The dash, `Cf` and whitespace table has one home.** `fold_common` lives in `omniweave_core.ident`
   beside `normalize_k`, and `normalize_eval` imports it rather than re-listing it. A dash added to one is
   added to both — which is the failure the collection actually exhibits, where two normalisers drift and
   a comparison starts depending on which one ran.
3. **The difference is asserted, not assumed.** A property in `omniweave-conform`'s self-test set
   (`Q-G23`) feeds a corpus of case-varied, markup-varied strings through both and asserts that
   `normalize_eval` is case-sensitive and `normalize_k` is not. Two normalisers that quietly converge are
   one normaliser with two names.

### 8.3 The metric register, with definitions

Gated metrics come from `eval/gates.toml`; every gate row carries an owner and a `review_by`, and a row
past its date fails (`Q-G17`). There is no `--warn-only` anywhere: a downgrade is a `class` change in that
file, a reviewed diff with an owner. *(Build note, D830: `tools/gate_gate_rot.py` reads `eval/gates.toml`'s rows, `eval/counters.toml`'s one `[gate]` table, `eval/quarantine.toml` and `tools/gates.toml`'s `[[gate]]` and `[[job_assertion]]` rows. It names a register that is absent rather than passing it. It reads `fixtures/index.toml`'s rows from the sidecars the index is generated from, and only `cc0`, `cc_by` and `public_domain` sidecars carry a clock. A row fails on its `review_by` date itself, the reading `tools/gate_tombstones.py` gives the same phrase. A missing owner or an unreadable date fails too. The finding names no `OW-Q-007`, because `codes.toml` has no such row yet.)*

A floor with no definition is not a gate, so every metric names the `eval_verdict` rollup that computes
it. All are macro-averaged over slices with `min_slice_n = 30` unless the row says otherwise. *(Build note, D816: `omniweave_conform.rollup` computes the three direct rate rows, `table_rel_acc`, `order_acc` and `field_acc`, one evaluator's verdicts at a time, because `eval_metric` has no evaluator column. Only `verified` assertions score, and `NULL` ones are counted as unscored. Each verdict's `slice_key` is its slice. A slice under `min_slice_n` is `unknown` with no value, and section 8.7's rule 3 is applied per metric: past `MAX_PARTIAL_FRAC` missing, or with a slice whose every expected assertion is missing, every row of the metric is `unknown`.)*

| metric | suite | slice | kind | budget | guard | `TruthKind` | computed as |
|---|---|---|---|---|---|---|---|
| `span_exact_rate` | parse | `*` | hard | **1.000** | — | self-verifying | over Blocks with `quote == VERBATIM`, the fraction whose `span` assertion re-verifies on the branch its `os_kind` selects. **Denominator is blocks that claim verbatimness**, so a slice with none passes vacuously — which is every office slice at release 1 |
| `degradation_detection` | absence | `*` | hard | **1.000** | — | `rendered` | over every `(Injector, fixture)` pair in §8.6, the fraction where all three clauses hold: `Verdict.state == degraded`, the expected gate appears in `Verdict.gates` in precedence order, and the emitted `DegradeCause.fix` command, executed, produces an undamaged run |
| `citability_violations` | retrieve | `*` | hard | **0** | — | self-verifying | a **count**, not a rate: rendered Answers containing a `cite` that does not resolve, plus artefacts containing a restricted item with no policy (OUT11) |
| `false_confident_zero` | absence | `*` | ceiling | ≤ 0.01 | — | `human` | over the absence corpus's **answerable** questions only (the counterfactual half of the removal construction), the fraction answered with `state == absent` *(Build note, D933: `eval/gates.toml` carries this row, and `ow eval run --suite absence` computes it in its removal half, `omniweave_conform.removal`. Each of the adoption catalogue's 13 answerable questions is asked of its generated reference corpus, and again of that corpus with the planted sentence holding its answer deleted. The planted sentence is the section, Tier A rather than Tier B. None is answered `absent`. 13 is under `min_slice_n`, so the row is `unknown` and `release-check` refuses it, naming more questions as the fix. `absent_recall` is 0 of 17: every genuinely absent question reads `low_confidence`, because `absent` needs no hit at all and a natural-language question always matches some word.)* |
| `hallucination_rate` | extract | `*` | ceiling | ≤ 0.02 | 0.005 | `human` | over `field` assertions with a literal ground truth, the fraction whose extracted value is non-null, differs from ground truth, **and does not occur anywhere in the document under `normalize_eval`**. The last clause is the whole metric: a misread is an accuracy failure, an invention is an honesty failure |
| `structure_f1` | parse | `office/*` | floor | 0.90 | 0.010 | `rendered` | F1 over `(kind, layer, parent_kind)` triples: predicted Blocks matched to reference Blocks by `normalize_eval(text)` within the assertion's `max_diffs`, precision and recall over the matched set, macro over documents then over slices |
| `structure_f1` | parse | `pdf/born_digital/*` | floor | 0.85 | 0.010 | `rendered` | as above |
| `table_rel_acc` | parse | `*/has_merges=1` | floor | 0.70 | 0.020 | `human` | the fraction of `table` and `cell_rel` assertions that pass. A direct verdict rollup, which is why `TableTest`'s relational shape was worth adopting |
| `order_acc` | parse | `pdf/born_digital/*` | floor | **0.75** | 0.015 | `rendered` | the fraction of `order` assertions that pass |
| `citation_soundness` | retrieve | `*` | floor | 0.995 | 0.002 | self-verifying | over every `cite` emitted in a scored run, the fraction resolving to a Block, a page and either a `Quad` or a `Locus.reason`, **and** whose `byte_exact` bit, where set, re-grounds under `normalize_k` |
| `doc_acc` | extract | `fields/*` | floor | **0.20** | 0.020 | `human` | the fraction of **documents** in which every `field`, `absent_field` and `null_kept` assertion passes. Whole-document, not per-field |

**Where `structure_f1`'s reference structure comes from**, because `TruthKind = rendered` names a page
image and F1 needs a labelled tree. The reference is an authored artefact, not a derivation: each corpus
document carries a `structure.jsonl` of `(page, kind, layer, parent_kind, normalize_eval(text))` tuples,
authored by a human reading a `soffice`/pdfium render, and `checked ∈ {verified, rejected, NULL}` exactly
as an assertion is. `rendered` therefore says *the tuples were authored against a render, independent of
our text path* — it does not claim the tuples fell out of the renderer. Q-Q12 records the labelling cost
and the pre-committed cheaper definition.

Two floors are sourced rather than chosen, and both would be wrong if guessed.

**`order_acc = 0.75`.** marker's own annotation records a `pdftext` character-stream reading order scoring
**75%** against a learned layout head's **56%** on olmOCR-Bench's order tests
(`marker/marker/builders/line.py:77-85`). The free deterministic baseline is 75%, so shipping below it
would mean paying a model to make reading order worse. That is the floor's derivation and it is why the
`REPAIR` rung is thin on the PDF path rather than absent.

**`doc_acc = 0.20`, deliberately.** lift's published benchmark reports **90.2% per field and 20.9%
full-document** accuracy on 225 documents of 6-64 pages and ~11k fields (`lift/README.md:75`). Per-field
correctness does not compound: 30 fields at 90% each would be 4% by independence, and lift gets 21%
because errors are correlated — but the direction is unarguable. A 0.90 budget on `doc_acc` would be a
promise the field cannot keep. `Q-G21` therefore **pairs** the two: `field_acc` may never ship without
`doc_acc`, and `hallucination_rate` may never ship alone. A product promise of "correct document" needs a
verification layer, which is why omniweave's answer to the 90→21 collapse is the OUT gate and the
citation channel, not a better prompt. *(Build note, D832: `omniweave_conform.scoreboard.PAIRS` holds the pairs. `field_acc` needs `doc_acc`, `source_reread_rate` needs `task_accuracy`, and `hallucination_rate` needs `field_acc`. That last is a reading of "never ship alone": this paragraph is about per-field accuracy collapsing per document. A partner counts only in its own run and slice. `export()` refuses an unpaired file, since export is where a metric ships, and `tools/gate_results.py` holds the committed tree to the pairing and to Q-G19's row clause. Q-G19's byte clause needs the generated `.oweval`, so it stays with `scoreboard.stale()`.)*

**Ungated metrics, and the rot rule.** These are measured and published from release 1 with **no
`[[gate]]` row**, because none has a defensible floor before the first corpus release and a guessed floor
is worse than none:

| metric | definition |
|---|---|
| `field_acc` | the fraction of `field` + `absent_field` + `null_kept` assertions that pass. Never ships without `doc_acc` |
| `recall_at_10` / `ndcg_at_10` | over the golden query set's graded relevance labels, against the fused ranking |
| `absent_precision` / `absent_recall` | over the absence corpus: of the answers we called `absent`, the fraction genuinely absent; of the genuinely-absent questions, the fraction we called `absent` |
| `qa_accuracy` | judge-graded key-fact coverage `(covered + 0.5·partial) / total` at or above 0.5, per §10.3 |
| `generated_share` | as [07](07-store-and-retrieval.md) §6.7 defines it, which owns the arithmetic: over `Response.hits`, never over a rendered Answer |
| `source_reread_rate` / `task_accuracy` | §8.8's pair. Paired by `Q-G21` from release 1; gated from v1.0 |
| `pacer_cross_runner` | the `perf` suite's ratio between `ow-bench-2` and `ow-bench-1` (§2.8) |

`Q-G27` bounds that state: a metric published ungated for more than **two corpus releases** either gains
a gate row or is removed from the scoreboard. An eternally ungated metric is decoration. A row that names
a future version — `source_reread_rate`'s `budget_max = 0.25` from v1.0 — satisfies the clock, because
the commitment is dated and reviewable rather than absent. *(Build note, D829: `omniweave_conform.rot` counts a metric's releases one corpus at a time, as the distinct `(corpus_id, corpus_version)` pairs the published tree carries it at, and every row counts whatever its standing. Any `[[gate]]` row naming the metric stops the clock, whatever its slice, class or `active_from`. The third release fails. `eval_scoreboard` gained `r.corpus_id` for it, because a version string alone does not say whose release it is. `tools/gate_metric_rot.py` prints every ungated clock, marks the one at two releases `edge`, and passes an absent `eval/results/` by name.)*

**Where a slice comes from.** `eval_metric.slice_key` is **not** the router's Slice. The router's is a
pure function of Evidence declared in policy; the harness's is the corpus's own declaration —
`[fixture.tests] slices` in a Tier-A sidecar, `slices` in an `eval_assertion` row — and a `[[gate]]`
row's `slice` field is a path glob matched against it (`office/*`, `pdf/born_digital/*`,
`*/has_merges=1`). They are two vocabularies for two purposes and the harness never mixes them; a metric
row carries the corpus slice, and `route_scoreboard` carries the policy Slice. `ow eval explain <metric>`
prints which it is reading. *(Build note, D983: the two halves now meet. No shipped sidecar declared a slice, so every verdict landed on the unsliced `*` (`judge` ruling 5) while :1097-1100's globs name `office/*`, `pdf/born_digital/*` and `*/has_merges=1` -- `fnmatchcase` matches none of those against `*` or `__macro__`, so the three accuracy floors would have been law over an empty set. The ten labelled office fixtures declare `office/<ext>` and the four labelled PDFs `pdf/born_digital/gen`, written by their generators rather than by hand; a document with a merged cell declares `office/<ext>/has_merges=1` FIRST, because a verdict takes its assertion's first slice and `table_rel_acc` is the row that reads it. `eval/gates.toml` now carries `structure_f1@office/*` at 0.90, `order_acc@pdf/born_digital/*` at 0.75 and `table_rel_acc@*/has_merges=1` at 0.70, each with this document's `computed` text verbatim. `structure_f1@pdf/born_digital/*` is deliberately absent: `parse.pdf.pdfium` declares `sections = "none"` with `tables = "none"`, so it is not applicable rather than failing. `test_conform_slices.py` asserts every floor's glob matches a slice the corpus declares, and that every declared slice is read by some floor.)* *(Build note, D1002, a user ruling of 2026-10-28: and each of the fourteen now declares its family's COARSE slice beside that key -- `office/labelled` on the ten, `pdf/born_digital/labelled` on the four. :1088's `min_slice_n = 30` is what forced it: thirty documents per extension is some 330 labelled documents to reach one number, thirty per family is some 50, and both coarse keys match the globs above unchanged, since `fnmatchcase` is not path-aware. The per-extension rows stay beside them reporting `unknown, under min_slice_n`, which is the honest report of a slice holding one document rather than a hidden one. `tools/gate_fixtures.py` ruling 14 DERIVES the coarse key from the per-extension ones and holds the pair together in both directions, so a labelled fixture without it fails and so does it on a fixture carrying neither label file.)* *(Build note, D1003: measured, not assumed, which row the sidecar's slices reach. A `.structure.jsonl` row declares no slices of its own, so all ten inherit the sidecar's and `structure_f1@office/*` groups by `office/labelled` -- 10 of the 30 DOCUMENTS :1097 counts, and the row the corpus has to grow for. An assertion's slices are its own when it has any (`labels` ruling 4) and all 110 committed assertions have, so the coarse key reaches no verdict: `order_acc@pdf/born_digital/*` counts VERDICTS and already holds 60 `order` assertions under `pdf/born_digital/contracts`, over :1088's thirty, so it computes as soon as those sixty are verified and no new born-digital document is needed for it, while `table_rel_acc@*/has_merges=1` holds three and needs twenty-seven more. So `pdf/born_digital/labelled` carries no verdict today and is declared anyway: the family's name is the corpus's to declare, and the next born-digital document joins it.)*

### 8.4 Retrieval and memory: the benchmark set

| benchmark | what it measures | n | omniweave's use | the number to beat |
|---|---|---:|---|---|
| **olmOCR-Bench** | parsing: presence, absence, order, tables, math, format, footnotes across 8 categories (ArXiv, old scans, old scans math, tables, headers & footers, multi-column, long tiny text, base) | 7,000+ cases / 1,400 docs | the `parse` suite's assertion **shape**; absolute cross-tool numbers are directional only (§8.5) | marker 76.0% overall / 83.5% born-digital; surya 83.3% (top under 3B); olmocr ~79% at v0.4.0 |
| **LOCOMO** | multi-session conversational QA over accumulated memory | 300 | the `retrieve` suite's memory slice: `recall_at_10` and judge-graded `qa_accuracy` | graphify (graph-expand) **0.497 recall@10** and 45.3% QA at ~$1.40 ingest; hybrid RRF 0.493 / 43.3%; dense RAG 0.439 / 41.3%; BM25 0.362 / 31.3%; mem0 0.048 / 27.3% |
| **LongMemEval-S** | long-horizon conversational memory, English subset | 50 | the same slice's second dataset, because a single retrieval dataset is a single distribution | graphify 76% QA / 0.844 recall@10; dense RAG 76% / 0.848; hybrid RRF 74% / 0.822; BM25 70% / 0.710; mem0 70% / 0.344 |
| **lift's adversarial design** | extraction under planted hazards | 225 docs, 6-64 pages, ~11k fields | the `extract` suite's category set, reproduced as assertion types (§8.1) | lift (9B) 90.2% field / 20.9% doc / 9.5 s median; Datalab API 95.9% / 44.4%; Gemini Flash 3.5 91.3% / 40.0% |
| **the paired-damage suite** | honesty: does the answer degrade to a named cause | 13 Injectors × the fixtures each applies to | `degradation_detection` (hard 1.000) and `false_confident_zero` (≤ 0.01) | no comparator exists; nothing in the collection measures this |

**graphify's 0.497 is not a zero-cost number, and the charter says so.** Its `BENCHMARKS.md` fairness
rules read *"One shared local embedder where the system allows it: BGE-m3"*, and its LOCOMO table lists
the primary `graph-expand` configuration at **~$1.40 ingest**, against `$0 (shared index)` for the
dense-RAG and BM25 baselines. The `vectors = "off"` default survives on other grounds; this evidence for
it does not, and the row is quoted here with its cost so nobody re-imports the shorter claim.

Neither LOCOMO nor LongMemEval-S is redistributed — both are `eval_corpus` Tier C with
`document_redistributable = 0`, `assertions_redistributable = 0` and `publishable = 1` (the *metric* may
be published; the corpus may not), and the harness documents the expected local layout. That is exactly
graphify's arrangement and exactly anydoc's ("the corpus is not redistributable and is not in the repo;
the harness reads whatever is in `samples/`"), and it is the right shape for a benchmark you want other
people to run on their own data.

**The five adversarial extraction categories, reproduced as first-class assertion types**, because they
are the categories a naive harness omits and therefore the categories a naive extractor passes:

1. **values that span pages** — the value's evidence is on page 7 and its label on page 6;
2. **exhaustive lists** — every item must be found, so recall is scored per-list and not per-item;
3. **fields that must be left null** — `null_kept`, and the reason it needs a *transform* rather than a
   prompt is that a schema whose grammar has no `null` forces the model to invent a value for every
   field. lift's `make_properties_nullable` rewrites every property leaf to `[leaf_type, "null"]` before
   constrained decoding, which is the mechanism;
4. **near-miss distractors** — a plausible wrong value adjacent to the right one, which is the category
   that separates a model reading the document from a model reading the neighbourhood;
5. **multi-source aggregation** — the answer is a sum or a max over values in different places.

Scoring is deterministic exact-match with numeric tolerance and `normalize_eval` strings. Where a judge is
unavoidable (`qa_accuracy` on LOCOMO and LongMemEval-S), §10.3's rules apply.

**The fairness record.** `eval_run.fairness` is a JSON object, non-empty on every comparative run, and it
names: one model per LLM role, one shared embedder where the system permits it, identical token budgets,
and a per-run spend ledger. This is graphify's discipline adopted directly. And the caveat graphify itself
prints is reproduced as a mechanism rather than a footnote: a comparator that locks in its own embedder
makes retrieval recall **embedder-confounded** — supermemory's self-hosted 768-d English-only embedder
against the shared BGE-m3 is the worked case, and its 0.149 recall@10 carries an asterisk in graphify's
own table — so the row is published with `confounders = ["embedder-locked: <name>/<dim>"]`, the recall
axis is marked not comparable, and the QA axis (a shared reader and judge over each system's own hits)
is the clean comparison.

### 8.5 The anydoc lesson: a self-authored benchmark is weak evidence about its author

anydoc ships the only self-benchmark against six named competitors in the collection (markitdown, pandoc,
docling, unstructured, mammoth+turndown, LibreOffice→pandoc), and it is honest about its own weaknesses
in ways most published benchmarks are not: speed as the min of N warm runs, in-process timing for the
Python tools, **process spawn included for pandoc and LibreOffice because "that's how they're used in
practice, and it's called out in the report"**, missing tools skipped with a warning, PDFs explicitly out
of scope, and its quality signal labelled *"not a truth measure"*. And it still has the defect: **the
quality metric is word-trigram containment against anydoc's own output.** Its author says so. The
consequence is exact — the harness cannot detect a systematic error anydoc shares with nothing else,
because anydoc is the reference. olmOCR has the milder version of the same problem: it is an entrant on
its own benchmark.

omniweave writes both authors' anchoring problem into the schema, so it cannot be forgotten in a release
rush. Eight mechanisms, and the second and seventh fire on us:

1. **`witness`, three values, and only `ci` is ranked.** `ci` is omniweave's own workflow on the published
   corpus; `self` is the subject's author; `third_party` is anybody else. The `eval_scoreboard` view's
   `standing` column returns `UNRANKED` for anything that is not `ci`.
2. **`entrant_bias`, and it fires on us.** `subject.vendor == corpus.vendor` sets the bit, **including
   when the vendor is omniweave**, and an `entrant_bias = 1` row is `UNRANKED` and printed with `†`. So
   omniweave's own parse drivers measured on `omniweave-golden` are displayed and **never ranked**. That
   is the whole point: a scoreboard on which the author always wins is a marketing page.
3. **`TruthKind` forbids self-anchoring at the column level.** `Q-G9` refuses a metric whose reference
   producer equals the subject producer — the anydoc defect, as a harness assertion rather than a caveat.
   `agreement` and `self` may **never** populate an accuracy column, and `native_run` may only anchor a
   **fidelity** metric.
4. **`native_run`'s restriction is derived, not conservative.** Reading the source XML runs (`w:t` /
   `a:t` / `sharedStrings`) is a valid reference for "do the extracted characters equal the source run's
   characters". It is **not** valid for recall, coverage or classification, because any independent `w:t`
   walk either re-implements or contradicts the same branch selection the subject driver makes —
   `mc:AlternateContent` at `anydoc/formats/docx/content.rs:146`, `w:sdt` at `:169`, `w:instrText` at
   `:536`, `w:txbxContent` at `:719-726`, footnote and endnote parts at `mod.rs:62-63`. A "recall" number
   against a naive walk measures which branches you both chose.
5. **Competitor Runners live in-tree and unpackaged.** `eval/runners/` holds one adapter per comparator,
   each declaring its own `timing_basis` (`in_process` / `spawn_inclusive` / `server_attached`), and
   **two rows with different bases may never share a column**. The directory is not a distribution, so
   docling's torch never reaches `G2`'s weight gate. A missing comparator is skipped with a warning and
   the report says which — anydoc's rule, and it is what makes a partial setup still produce a usable
   report. (Charter §D10 writes this path `evals/runners/` once, while §D1's repository tree has only
   `eval/`. **The spelling is `eval/runners/`** — [ADR-11](adr/0011-eval-register-reconciliation.md),
   charter §9.2 `E85`, on the ground that `eval/` names nine gated declaration files against one prose
   noun. [Repository layout](11-repo-layout.md) §1.7 carries the directory in the tree.)
6. **A third party may produce a `third_party` row, and there is a protocol** — §8.7.
7. **A 15% holdout, and the gap is printed.** The scoreboard's headline is computed on 85% of the corpus
   (`blake2b(doc_key‖"ow-split-1") % 100 < 85`); the holdout's gap prints `⚠` above 5 points. A gap that
   large means the published number is a fit to the corpus rather than a measurement of the subject, and
   the reader should know before we do. It is the **same split** the calibration chain uses (§9.1), so
   there is one split function, one leakage gate and one thing to get wrong.
8. **`Q-G23`: the harness scores deliberately wrong outputs.** Three planted defects with the exact
   expected numbers asserted, because `omniweave-conform` is dev-tier and is therefore tested less
   rigorously than runtime code:

| planted defect | fixture | expected |
|---|---|---|
| a dropped page | the 12-page `sec-exhibit-scan` fixture, page 7 removed from the candidate output | exactly the 6 assertions anchored on page 7 fail; `34/40 = 0.850`; the six ids are named in the report |
| a transposed table | `xlsx-merged-4m-cells` with rows and columns swapped | every `table` and `cell_rel` assertion fails (`0/18`) while every `present` assertion still passes, because the strings are all there — which is the point of a relational assertion *(Build note, D932: the `cell_rel` half now runs over a PARSED document. A one-table DOCX through `parse.office.anydoc`, decoded into a candidate store and read back as its `Doc`, passes all six `cell_rel` assertions; its transpose fails all six. Running it over a real document found two defects the hand-built Doc had hidden: a label's 1-based page was compared with `Block.page`, which is 0-based, and a parsed cell's text is in its child paragraphs, not on the `TABLE_CELL` Block. The parse eval suite now hands `judge()` each labelled fixture's parsed `Doc`. `xlsx-merged-4m-cells` itself is still not in the tree.)* *(Build note, D1010: and it has no committed form to arrive in. Line 591 of this document rules the 4M-cell workbook "never in git" and 12-performance.md:1516 writes its size as "generated"; measured, the archive `fixtures/gen/gen_4m_cell_sheet.py` writes is 16,473,583 bytes against Q-G2's 4,000,000 per binary, 4.12x, and even a quarter of that sheet is over by 132,766. The merged variant is the same cell count plus a `mergeCells` list, which compresses to nothing beside 200,000 rows, so the same measurement refuses it. The merge this row is about is carried instead: D877's synthetic transpose reproduces the `0/18` exactly, and D1005 committed 18 real `cell_rel` rows over three merged-cell documents in three encodings of one grid, judged on the parsed `Grid`. `test_fixture_sheet.py` asserts the cap in both directions so the forced choice stays a measured one.)* |
| a fabricated quote | a `present` assertion's string replaced by a plausible near-miss at edit distance 4 with `max_diffs = 0` | that one assertion fails; the explanation prints both strings |

This is the test that would have caught anydoc's self-anchoring on the first run, and it is the reason
the harness's own numbers are trustworthy enough to gate on. *(Build note, D827: `omniweave_conform.judge` runs a batch of assertions over a candidate's text per `(doc, page)` and returns `eval_verdict` rows. A page the candidate lacks fails every assertion anchored on it, and an assertion the text evaluator cannot judge is named as not run, never counted. All three planted defects are tests, on synthetic candidates because neither fixture is in the tree: 34/40 = 0.850 with the six ids named, 0/18 `table` with every `present` passing, and the near miss at distance 4 failing alone with both strings printed.)* *(Build note, D877: `omniweave_conform.cells.evaluate_cell_rel` is the owdoc half of the transposed-table case. It reads a document's TABLE Blocks, each one's `Grid` and each cell's Block. The spec and the threshold are `table`'s. `up` and `left` step from the cell's origin; `down` and `right` step from the far edge of its span. A heading is the Grid's header chain without the cell itself, so a table that declares no header rows has none, which is where `cell_rel` and `table` part. `judge(docs=...)` runs a `cell_rel` whose document it is handed and writes the verdict as `owdoc`; without the document it stays not run. Over a hand-built Doc: 18 of 18 before the transpose, 0 of 18 after. No suite yet hands `judge()` a parsed Doc.)* *(Build note, D900, a user ruling of 2026-10-19: the fabricated quote's expected column no longer says `hallucination_rate` on the run is exactly `1/1`. Section 9.1 (13:1096) defines that metric over `field` assertions with a literal ground truth, and the planted defect is a `present` assertion, so the claim joined two things the register keeps apart; the control's own expectation is that one assertion fails and its explanation prints both strings, which `test_conform_judge.py` asserts.)*

### 8.6 Absence gets both constructions, and the Injector set is total

**Construction 1 — the absence corpus, ground truth by removal.** Take a Tier-B document, delete a
section, re-ingest, and ask a question whose only answer was in the deleted section. Metrics:
`absent_precision`, `absent_recall`, and `false_confident_zero ≤ 0.01` — the fraction of genuinely
answerable questions answered `absent`. Removal gives exact ground truth at zero labelling cost, and the
deleted span is retained so the counterfactual is one query away.

**Construction 2 — the paired-damage suite.** Inject one `Diag` code at a time into a pristine corpus and
assert the answer degrades to a **named cause** rather than a confident zero. `degradation_detection` is
a **hard gate at 1.000**, which is only a meaningful claim if the Injector set covers the population it
claims to: `ABSENCE_BLOCKING_DIAGS` has **thirteen** members, and the charter names eight Injectors. The
remaining five are added here so the set is total, and each is as cheap as the eight.

| injector | `Diag` | damages | must produce |
|---|---|---|---|
| `encrypt` | `OW_ENCRYPTED` | applies user-password encryption to the document ([ADR-15](adr/0015-encrypted-pdfs-and-document-passwords.md) D15.6) | absence gate 9 `parse_gap_in_scope`, a `DegradeCause` naming the pages and the fix command |
| `strip_text_layer` | `OW_NEEDS_OCR` | removes the text layer, leaving the raster | an escalation to `PAGE`, or gate 9 if no OCR driver is enabled |
| `chaos` | `OW_MALFORMED` | truncates a part mid-stream at a fixed byte offset | gate 9; never a partial answer presented as complete |
| `drop_part` | `OW_MISSING_PART` | deletes one part from the roster after ingest | gate 4 `coverage_incomplete` with a discovered-versus-indexed count |
| `budget` | `OW_TRUNCATED_BY_BUDGET` | sets a per-part budget below the cheapest admissible driver | `budget.exhausted` in the evidence, `Degradation`, gate 5 `pending_work_in_scope` |
| `deny_probe` | `OW_DRIVER_UNAVAILABLE` | makes a capability probe return `unavailable` | `ProbeVerdict.unavailable` naming the missing thing, gate 2 `channel_unavailable`, `state == degraded` |
| `downgrade_origin_span` | `OW_ORIGIN_SPAN_DOWNGRADE` | forces a driver to return `origin_span = none` where it declared `exact` | `quote` demoted below `VERBATIM`, and **serve refuses** a byte-exactness claim rather than making one |
| `rotate_embedder` | `OW_INDEX_MODEL_CHANGED` | changes the embedder identity behind an existing index | gate 13 `space_mismatch`, refused on the **search** path and not only on the build path |
| **`stall`** *(new)* | `OW_TIMEOUT` | sets the part's `deadline_ms` below the Cassette's **recorded** service latency, so the deadline fires on replayed bytes and no clock is slept on | gate 1 `timed_out` reading the channel's own `UNAVAILABLE(timeout)`, never a pre-empted channel's `OK` |
| **`mask_format`** *(new)* | `OW_UNSUPPORTED_FORMAT` | rewrites the leading magic bytes so no enabled driver accepts the unit | a named `resolve()` rejection with the format it sniffed, gate 9 |
| **`inflate`** *(new)* | `OW_RESOURCE_LIMIT` | generates a fixture exactly one row above a `[limits]` value | a refusal naming the knob and the value that admits it, gate 9. For a PDF's pages that is `gate.too-many-parts` under `[ingest] max_parts`, before any driver runs (D644); the driver's own `take(N+1)`-then-check is the `limits` conformance suite's |
| **`strip_integrity`** *(new)* | `OW_INTEGRITY_UNCHECKED` | removes the retained part's `store_ref` so a quote cannot be re-verified | `quote` demoted, `Doc.verify_quote()` returning `source_unavailable` rather than `mismatch`, gate 9 |
| **`synopsize`** *(new)* | `OW_TABLE_SYNOPSIS_ONLY` | inflates a table past `TABLE_SYNOPSIS_CELLS = 20_000` so only the synopsis segment is indexed | gate 9, and a hit whose lift landed on the synopsis rather than the 20,001 cells it summarises |

The suite asserts three things per injector, and the third is the one nobody else asserts: the damaged
run's `Verdict.state` is `degraded` (never `ok`, never `absent`); the fired gate list contains the
expected gate **in precedence order**; and the `DegradeCause.fix` string is a command that, when executed
against the damaged store, produces an undamaged run. A fix instruction that does not fix is a lie with a
shell prompt in front of it.

**The `fix` clause executes a command, so the command is parsed rather than shelled.** The third
assertion above runs the string a `DegradeCause` emitted, which is our own generated text and not user
input — but a suite that passes an arbitrary string to a shell acquires a class of bug it never needed.
So the harness parses the string against the `ow` Action registry, refuses anything whose verb is not a
known Action or whose parameters are not that Action's, and invokes it in-process with no shell. A
`DegradeCause.fix` that cannot be parsed that way is a **failure of `degradation_detection`**, not an
exemption from it, which is the right pressure: a fix instruction a machine cannot execute is one a user
will mistype.

Two operational rules keep the hard gate honest:

- **A new Injector lands behind its own passing assertion, in the same PR, or not at all.** A gate at
  1.000 admits no partial coverage, so "add the Injector now and make it pass next release" is not a
  state the gate can express.
- **`rotate_embedder` and `synopsize` need a configuration the default does not have.** `vectors = "off"`
  means there is no space to mismatch, and gate 13 passes vacuously. Their fixtures therefore enable the
  stdlib vector backend over a 200-block corpus, which is seconds and needs no GPU. An injector whose
  gate passes vacuously is an injector that tests nothing, and the fixture is where that is fixed.

**The damage half needs no model, so it gates every PR** at T2. The absence corpus needs a judge for
`qa_accuracy` and runs nightly at T4. *(Build note, D942: a gate is only as reliable as its runner, and on a slow Windows CI cell the `mask_format` pair's fix read as failing twice. The re-read run was its pristine self but for gate 1, `timed_out`: a channel's first query after a fresh `ow add` had overrun its shipped 15-80 ms budget. The harness's questions are now asked under the shipped `QueryBudget` with every figure times 20 (channels plus reserve still equal `query_ms`), and the snapshot at `MAX_SNAPSHOT_MS`. The suite judges honesty, not latency, and the `stall` Injector will damage a deadline of its own.)*

### 8.7 A run that did not finish, and a row we did not produce

Two populations of untrustworthy input reach the harness, and the schema has a slot for each that the
charter leaves unexplained. Both are filled here.

**`eval_run.status = 'partial'`.** Set whenever any assertion in the corpus produced no verdict — a model
endpoint went down at minute 60 of the 90-minute nightly, a worker died (§2.10), a Runner was missing.
`eval_scoreboard`'s `WHERE r.status <> 'unknown'` admits a `partial` run, so without a rule a truncated
night publishes a flattering headline computed over whichever half finished. Three rules:

1. **Every metric on a partial run is computed over the assertions that ran, and `n` is that count** —
   never the corpus count. A shrunken `n` widens the Wilson interval, which is exactly the visible
   consequence it should have.
2. **`not_measured[]` names the missing slices and the reason**, and it is already required non-empty by
   `Q-G19`.
3. **`MAX_PARTIAL_FRAC = 0.02`.** Above 2% missing, or with any gated slice entirely missing, the harness
   writes `state = 'unknown'` on every affected metric. The view turns that into `UNKNOWN` and
   `ow eval release-check` refuses on it. Below 2% the run publishes with its narrower population
   disclosed. This fills the schema's hole without touching the view, which is byte-diff gated.

**A `third_party` submission is untrusted data, and none of it is executed.**
`ow eval run --witness third_party --cassette required --emit eval/results/<subject>.json` produces a row
carrying the harness version, the code fingerprint, the corpus digest and the cassette digests. On our
side the submission is parsed, never run:

| hazard | mechanism |
|---|---|
| a submitted script | nothing in the submission is imported, executed or shelled out to. The kit runs from a trusted tag (DR23) — *"a validator supplied by the submission validates nothing"*, `awesome-skills/REVIEWING.md:37-39` |
| a resource-exhaustion payload | `json.load` behind a 4 MiB byte cap and a depth cap of 32 — the same two numbers `omniweave_core.host.wire` uses on the driver wire, reused rather than re-chosen |
| a locally modified corpus | `measured_on.corpus_digest` must appear in the omniweave release manifest, or DR24 forces `witness = "self"` **regardless of what the row declares** |
| an unreplayable model call | every cassette digest in the row must replay against the submitted cassette bundle, itself under the §4.7 caps; a miss is `OW-Q-016` |
| a plausible but unearned ranking | `witness = 'third_party'` is `UNRANKED` in the view, unconditionally |

### 8.8 `bench/serve/` — the adoption harness, and the metric that can be gamed

[Vision](00-vision.md) §10 delegates this harness here and keeps the pairing rule. The instrument is
**30 scripted tasks** over three reference corpora (`F20`: a 5,000-page legal matter, a 137-document data
room, a 60-document personal archive; at v0.1 generated stand-ins with planted answers and one real scanned slice, which never report as F20 — [ADR-14](adr/0014-reference-corpora-and-control-arm.md) D14.1-D14.2), driven by a scripted agent with a fixed tool budget of 12 calls in both arms, its control arm the same agent with the server removed and the best converter per format (D14.3), configured and run as D14.7 and `bench/serve/agent.toml` say, and it
answers four questions no other tier can.

| task class | n | what it measures | reads out as |
|---|---:|---|---|
| citation-shaped lookup ("what does §4.2 say about termination") | 8 | did each tool get the input it resolves: `ow_open` an address it can open (a cite, a page address, a document), `ow_query` prose, a section number in a named document included, since no `ow_open` form spells one (D652) | `F19`'s mis-pick rate, R-A5's (`ow_query` given an address, or `ow_open` given prose); above ~5% `ow_open` folds into `ow_query` as a `ref` parameter and the listed set drops to three |
| open retrieval ("which suppliers have an indexed cap") | 8 | answer completeness against chars spent per budget tier | `F20`'s tier re-keying, from file counts onto block counts |
| genuine absence ("does any contract mention arbitration in Singapore") | 6 | does the agent report absence with a named cause, or invent one | `false_confident_zero`, on the agent surface rather than the API |
| damaged corpus (one `Injector` applied) | 8 | does the agent act on `degraded` rather than answering anyway | `degradation_detection`, end to end |

**Two numbers, and the pairing is the whole design.** `source_reread_rate` counts, per task, whether a
host `Read`, `Grep` or shell `cat` of an **indexed** source file occurs after an `ow_query` or `ow_open`
in the same task. It is the framework's single adoption metric, and [vision](00-vision.md) sets the stop
condition at `> 0.25` at v1.0. But the metric is directly gameable: the tool descriptions and the
Answer's "treat this as a `Read` you have already performed" paragraph exist precisely to suppress the
behaviour it counts, so it can be driven down by telling the agent to stop checking rather than by giving
it provenance that makes checking unnecessary.

So the harness reports **both** `source_reread_rate` and `task_accuracy`, the fraction of tasks whose
final answer is wrong, and the rule is a mechanism rather than a caution: **a run in which
`source_reread_rate` falls and `task_accuracy` falls with it is a failing run.** Three mechanisms carry
it, and the middle one is new:

1. **`Q-G21`'s pairing extends to the pair.** `source_reread_rate` may not ship without `task_accuracy`,
   which is the same mechanism that keeps `field_acc` from shipping without `doc_acc`. It applies from
   release 1, before either metric has a floor.
2. **A `Control guard`, because the baseline is in the same run and not in the last release.** An
   ordinary Guard compares release N against N−1. The pairing rule needs something else: the same 30
   tasks are run twice per night, once with the MCP server present and once with it **absent**, and
   `task_accuracy` on the omniweave arm may not fall below the control arm at paired `p < 0.01`. The
   control arm also produces the baseline `source_reread_rate`, which is 1.0 by construction, and is what
   `V-Q1`'s pre-committed fallback — re-anchoring to a 60% relative reduction if the absolute 0.25 is
   unreachable for reasons unrelated to trust — reads off.
3. **A dated gate row rather than an ungated metric.** `source_reread_rate` gains
   `budget_max = 0.25` at v1.0, which is `Q-G27`'s clock satisfied by a commitment rather than by a
   number nobody has measured.

Two further rules keep the number honest. It is **reported as a distribution, sliced**, never as a bare
mean — split by whether the task's source is born-digital or scanned, because a scanned corpus with
`verbatim` unreachable is exactly where an agent *should* re-read, and pooling the two hides the signal.
And **every model call goes through a Cassette**, the scripted agent included (at `bench.agent`, [ADR-14](adr/0014-reference-corpora-and-control-arm.md) D14.4), so the harness reproduces
and a tool-description change is a reviewable cassette diff rather than a number that moved for unknown
reasons.

## 9. Confidence calibration

### 9.1 The chain, and it is mandatory

Six confidence-shaped things exist across the framework. The two most load-bearing need no labelled
corpus at all: `quote == VERBATIM` is self-verifying via `Doc.verify_quote()`, and `agree.decode_vs_page`
is free on every escalation. The other four go through five steps, and skipping any of them is a build
failure rather than a style question.

1. **A signal exposes a probability or an ordinal, never a bare label.**
2. **The scale is registered** in the append-only `tools/scorekinds.toml`, with its domain, semantics,
   declared consumers, eval set and calibration numbers. **An unregistered `score_kind` raises at
   `DocSink.add_block`** — enforcement class `A`, not a lint. `score` and `score_kind` are nullable
   **together**, enforced by a `CHECK`, because "0.7 on an unnamed scale" is not a measurement. `Q-G10`
   fails both directions: an unregistered kind cannot be written, and a registered kind that is never
   written fails (`OW-Q-008`).
3. **A curve is fitted on a deterministically split calibration set.** The split is
   `blake2b(doc_key‖"ow-split-1") % 100`, so **leakage is structurally impossible** and no split file can
   drift out of agreement with itself. `< 70` is fit, `[70, 85)` is validation, `[85, 100)` is the
   holdout. Because the key is the `doc_key` — a digest of normalised source bytes — the same document
   arriving through a different path lands in the same split.
4. **The renderer consumes `Calibrated.status`, never the float.** There is no code path from an
   uncalibrated number to a bar.
5. **Kill conditions are written down, and they delete the tag rather than caveating it.**

**One split, three uses, one leakage gate.** The `% 100` bucket in step 3 is the same function the
scoreboard's 85/15 holdout uses (§8.5 item 7) and the same one `Q-G26` recomputes to prove no `doc_key`
appears in two splits. That is deliberate: three independent split files would be three things to drift,
and a corpus can only be sliced honestly once. The calibration holdout `[85, 100)` **is** the scoreboard
holdout, so `holdout_gap` and a calibration curve's validation gap are measured over the same documents
and a discrepancy between them is a real finding rather than a sampling artefact. *(Build note, D875: `tools/gate_leakage.py` runs Q-G26, its decisions in `omniweave_conform.leakage`. Of the three clauses only assertion provenance has an input today: each `derived_from_sha256` is held against Tier A's digests, and a fixture outside the assertion's own corpus is `OW-Q-015`. The split clause reports not run because nothing records a split; every use recomputes `stats.split_of()`. The golden clause reports not run until `ow eval fetch` brings `omniweave-golden`'s manifest, or `--golden` names one. Over a roundtrip `.oweval`: 747 Tier-A digests, 33 assertions, no leak. The roundtrip suite's `derived_from_sha256` now digests the IL unit an element lives in, not the target's golden artefact. V10-1 runs the gate.)*

### 9.2 The four signals that need a corpus, their label sources, and which test applies

| signal | shape | test | buckets | label source | eval set |
|---|---|---|---|---|---|
| `block.trust` | ordinal `Trust`: `AMBIGUOUS = 0 < INFERRED = 1 < EXTRACTED = 2` | `separation()` | 3 | `human` (the 2,400-block anchor) primary; `audit` verdicts; `synth_ocr` per level | `parse-cal@<corpus version>` |
| `garble.score` | probability | `sharpness()` | 10 equal-mass | `synth_ocr` L0-L4 against the known text layer | `garble-cal@…` |
| `page.ocr_score` | probability | `sharpness()` | 10 equal-mass | `synth_ocr` primary, `human` on the degraded slice | `ocr-cal@…` |
| `retrieval.confidence` | probability, `best_score / ceiling()` | `sharpness()` | 10 equal-mass | the golden query set's relevance labels; `human` on a 300-query sample | `retrieve-cal@…` |

The mapping is not a convention: `separation()` is defined over ordinals and `sharpness()` over
probabilities, ECE and Brier are undefined on an ordinal, and a signal whose row named the wrong test
would produce a `NULL` that reads as a missing measurement rather than as an inapplicable one.

`TruthKind`'s six values, with the exact admissibility rule for each:

| `TruthKind` | what it is | admissible for |
|---|---|---|
| `human` | **2,400 double-labelled blocks** across scan-clean, degraded, photo, handwriting, CJK and math. ~4 person-days, refreshed annually. **The anchor.** | anything |
| `rendered` | a `soffice`/pdfium render plus a page-image comparison — independent of our text path | structure, order, coverage |
| `native_run` | the source XML run text | **fidelity only** (§8.5 item 4) |
| `synth_ocr` | a born-digital PDF rendered to pixels at the OCR profile and OCR'd against its **known** text layer. Genuinely independent (the pixel path shares nothing with the text-layer path), free, and large | anything, **reported per degradation level L0-L4 and never pooled** |
| `agreement` | `agree.decode_vs_page` | its own column, headed "Agreement (not accuracy)". **Never** an accuracy column |
| `self` | a driver's self-report | stored, never scored, never ranked |

The synth-OCR ladder, in `eval/degradations.toml`:

```text
L0  []
L1  downsample:150->96dpi
L2  +jpeg:q=40
L3  +skew:+-3deg, blur:0.8
L4  +jpeg:q=25, blur:1.2, sp_noise:0.005, bleed_through:0.12
```

**Never binarize.** A 72-DPI-then-Otsu path destroys the antialiasing a modern VLM was trained on, and
`binarize = false` is already the render rule, so a binarizing degradation would measure a pipeline
omniweave does not ship. The L4-versus-human gap is printed on the calibration page and is `F24`'s open
measurement: a rasterized born-digital page has no bleed-through, no feeder skew and no scanner-specific
ringing, so if the gap at L4 exceeds one Wilson width, synth-OCR is demoted to a *smoke* signal and the
human slice must grow.

**Each ladder step is a deterministic image transform with a pinned implementation.** `skew` and
`sp_noise` sound like they need an RNG and do not: the skew angle is a fixed `+3°` on even page indices
and `−3°` on odd, and the salt-and-pepper mask is `blake2b(doc_key‖page‖"ow-degrade-1")` expanded to a
bitmask at the stated density. Two runs of L4 over one corpus produce byte-identical images, which is
what makes a calibration curve fitted on them reproducible at all.

### 9.3 The two tests and their thresholds

```python
def separation(rows) -> EvalStatus:
    """Q-G11. ORDINAL signals. `p_hat` strictly increasing across buckets AND adjacent Wilson 95%
    intervals non-overlapping, at n >= 150 per bucket per slice. Below n: 'unknown', and the slice
    is NAMED, never silently dropped."""

def sharpness(rows) -> EvalStatus:
    """Q-G12. PROBABILITY signals. ECE <= 0.05 and Brier <= 0.08, 10 equal-mass bins, n >= 1000.
    Failure => the driver writes score = NULL and score_kind = NULL (the CHECK makes the pair
    atomic) and every consumer's UNKNOWN path is exercised."""
```

Both conditions in `separation()` are necessary and independently violable. Monotone `p_hat` with
overlapping intervals means the ordering is not distinguishable at the sample size you have, and reporting
it as separated is exactly the error a three-tier trust badge would make on 40 documents. `P-21` asserts
that a monotone-but-overlapping input returns `unknown`, never `pass`. *(Build note, D824: `omniweave_conform.calibrate` implements both tests. `separation()` returns `fail` when `p_hat` does not rise with every bucket at `n`, and `unknown` when it rises and two adjacent intervals touch. Equal-mass bins never split a tie, because a cut inside a run of equal scores moves to the run's end. Split by input order, an all-0.9 signal that is 90% right would read as an ECE of 0.18 rather than 0. Ten honest levels from 0.05 to 0.95 have ECE 0 and Brier 0.1675, so `sharpness()` fails them, which is RT6's second bound doing its job.)*

A worked calibration row, so the shape is unambiguous:

```text
eval_set_id      score_kind    producer_id slice_key         bucket lo   hi   n    n_ok p_hat wilson      ece
parse-cal@2026.09 block.trust  41          office/docx       0      0.0  1.0  212  74   0.349 0.288-0.416 —
parse-cal@2026.09 block.trust  41          office/docx       1      1.0  2.0  688  571  0.830 0.800-0.856 —
parse-cal@2026.09 block.trust  41          office/docx       2      2.0  3.0  4102 4009 0.977 0.972-0.982 —
                                       -> separation: PASS (3 buckets, gaps clear, n >= 150)
parse-cal@2026.09 block.trust  41          pdf/scan-degraded 0      0.0  1.0  96   —    —     —           —
                                       -> separation: UNKNOWN (n=96 < 150); SLICE NAMED IN THE REPORT
```

`ece` is `NULL` for an ordinal signal, which is correct rather than missing: expected calibration error is
defined over probabilities, and a `0.0` in that cell would be a claim.

### 9.4 The surfacing rule, and the clause that keeps the product usable

`Q-G14` and INV-19: `status != "calibrated"` means the surface **may** print the ordinal member name
followed by `(uncalibrated)`, and may **never** print a percentage, a numeral adjacent to the signal, a
bar, a colour ramp or a grade. A renderer test feeds each of the four `CalStatus` values and asserts the
output **shape** — not the output text — so a copy change cannot break the gate and a bar cannot sneak in
behind one.

**An uncalibrated signal remains usable as an internal filter and sort key.** That clause is not a
softening; it is what keeps the `block_review` partial index (`WHERE trust < 2`) working on day one. An
uncalibrated ordinal is a usable ordering. It is simply not a publishable digit.

The consequence at release 1, stated plainly because it is a product limitation and not a bug: no
confidence signal is calibrated, so nothing renders a digit. `V20-5` in [vision](00-vision.md) makes "at
least one signal reaches `status == "calibrated"`" a v2.0 criterion, and until then every badge stays
dark.

### 9.5 Kill conditions

"Uncalibrated forever" is not an outcome, so the exits are written down.

| condition | consequence |
|---|---|
| a `score_kind` fails `sharpness` **twice in a row** | it is **removed** from `tools/scorekinds.toml`, and because the register is append-only its row is marked retired with the two failing run ids. The producing driver then writes `score = NULL, score_kind = NULL` and every consumer's UNKNOWN path is exercised |
| an ordinal fails `separation` across **two consecutive releases** for a driver family | that card is forced to `confidence = "none"` and every block it produces gets `trust = AMBIGUOUS`. **The tag is deleted, never caveated** — and the `block_review` index then correctly selects all of it, which is the honest outcome |
| a curve past `max_age_days = 30` | `status = 'stale'` plus `Degradation(kind="calibration_stale")`, carried on the result, in the run manifest and in the serve envelope. `Q-G13` |
| a slice below `n = 150` per bucket | `EvalStatus.UNKNOWN`, the slice **named** in the report, never silently pooled into a slice that has enough data |

The calibration fit runs **weekly**, which gives four times the headroom `max_age_days = 30` requires, so
a staleness `Degradation` in production means the weekly job has been failing for a month and that is the
signal it should send.

## 10. Evaluating generation

### 10.1 What is checked automatically, and it is most of it

A compiled artefact carries more machine-checkable structure than a parsed one, because omniweave wrote
it. [09](09-generation.md) owns the seven round-trip laws and the ten-value `GateStatus`; this document
owns only the **evaluation obligation** each creates — the instrument, its population and the metric it
folds into. The laws themselves are not restated.

| law or gate | the evaluation obligation | instrument |
|---|---|---|
| the release gate | assert that exactly one of the ten `GateStatus` values permits a release and that each of the other nine prints a distinct message and a fix command | a per-value fixture; `gate_status` recorded per `artifact_gen` |
| R1 retained-IL identity | recompile the retained bundle and compare at the declared `ArtefactDeterminism` | `ow out verify <artefact>`, binary per artefact |
| R2 address survival | for every IL element carrying `data-ow-el`, exactly one Block with the matching `el` | the `roundtrip` assertion type (§8.1): missing, duplicated, kind-mismatched or text-mismatched all fail |
| R3 second-round fixed point | assert the **second** round, not the first — an author writes compatible-but-non-canonical input and the compiler normalizes it once | binary per artefact, over `Layer.BODY` `content_digest` multisets |
| R4 edit locality | a per-unit outcome histogram in the receipt; a `rebuilt` unit that should have been `patched` moves a Counter | `eval_counter`, exact |
| R5 declared loss, both directions | the third clause is the one an evaluation must carry: every `exact` row is **exercised** by the golden corpus and a semantic mutation of its payload moves `il_digest_rt` | without it, `loses = ["*"]` is a green report |
| OUT13 determinism | 3 runs × `PYTHONHASHSEED ∈ {0, 1, random}`, two temp dirs, different cwd and `TMPDIR`, `SOURCE_DATE_EPOCH=0`; `part` is promised, `byte` is asserted only under one pinned resolution and never promised to a user | `V10-10`: two compiles of the 40-unit golden fixture equal at `part` on all **nine** cells |
| R7 total classification | every output unit lands in exactly one `UnitOutcome` and the sum equals `unit_count` | a Counter, exact; unclassifiable is fatal and the artefact is not written |
| citation soundness, OUT direction | every `artifact_cite` row resolves at its pinned `doc_gen`, and the `verbatim` bit is **proved** by re-grounding, never claimed | folds into `citation_soundness ≥ 0.995` on the artefact slice |
| OUT11 restriction propagation | one SQL aggregate at plan **and** at compile | `citability_violations == 0`, hard |
| OUT10 asset ledger | every asset frozen, content-addressed and licence-bearing before compile; a compile that must fetch refuses | `ratio_variants > 1` on an `artifact_asset` row means the deck is stretching an image, reported as a warning-severity `Finding` |
| the feedback loop | the artefact re-enters the corpus through the same `parse/1` pipe a source document does, and the ~120-property testkit runs against `read_back` **unchanged** | if the testkit needed a special case, the abstraction would be one implementation wearing an interface |

Two evaluation-specific additions that belong to no law. *(Build note, D902, a user ruling of 2026-10-19: the table's R2 row now has a metric. `eval/gates.toml` carries `address_survival`, suite `roundtrip`, `hard` at 1.000: over every element of each register target's golden carrying `data-ow-el`, the fraction for which R2 holds after compile then `read_back`, one value per target. `ow eval run --suite roundtrip` writes it, and `release-check` refuses on any element that did not survive.)*

**`generated_share` sanity.** A corpus that has never ingested its own artefacts must report
`generated_share == 0.0`; a corpus containing its own compiled deck must report `> 0` without the
`Method.ROUNDTRIP` filter and `0.0` with it. The fixture is a self-ingesting corpus, and the assertion is
`V10-17` in [vision](00-vision.md). This is the instrument for the hardest failure mode in the project: a
corpus that eats its own output and then cites itself as a source.

**`ManualReason` coverage.** Each of the seven closed `ManualReason` members must have at least one fixture
where it is the outcome, asserted in both directions: the reason fires when it should, and a
`manual_required` unit always carries a non-NULL `reason`. A closed vocabulary with an unexercised member
is a vocabulary with a wrong member.

### 10.2 What needs a human, and how the sample is drawn

Three things cannot be machine-checked, and pretending otherwise is how a deck ships with a chart that is
technically valid and visually wrong.

| what | why a machine cannot | the process |
|---|---|---|
| **visual quality of a rendered unit** | "the title overflows the box" is measurable (the `deck` target has runtime `getBoundingClientRect` rules); "the slide is ugly" is not. Overflow is gated; composition is reviewed | a **deterministic 5% sample** of golden-corpus units, `blake2b(artifact_slug‖unit‖"ow-review-1") % 100 < 5`, rendered to PNG and reviewed at each corpus release. Deterministic so the same units are re-reviewed across releases and drift is visible |
| **the four `UNVERIFIABLE_*` manual reasons** | `unverifiable_wording`, `unverifiable_identity`, `unverifiable_data` and `insufficient_source` exist precisely because the source does not contain the claim. No automated check can supply what is absent | `--accept-manual` produces a Draft: placeholders carrying their `ManualReason`, `delivery: "draft"`, the gate status unchanged, and a `Diag` on every later read-back. **There is no gate bypass.** The evaluation question is whether the reason is *correct*, which a reviewer answers on the 5% sample |
| **whether the artefact answers the Brief** | the Brief is a machine-parseable authoring contract, and its `## forbidden` items with `(user)` tags are checkable. "Does this deck make the argument" is not | a human reads the deck against the Brief at each corpus release, on the same deterministic sample, recorded as an `eval_verdict` row with `evaluator = 'text'` and a written `explanation` |

The 5% figure is a budget, not a discovery: 40 golden units at 5% is two units per release, which is
minutes, and it grows linearly with the corpus rather than with the number of releases. Its power is
poor against a defect that affects a minority of slides, which is `Q-Q3`.

### 10.3 The judge, where one is unavoidable

An LLM-graded number appears in exactly two places: `qa_accuracy` on the memory datasets, and the pairwise
quality comparison in the `parse` suite's cross-tool slice. Both obey `Q-G20`.

| rule | value | why |
|---|---|---|
| agreement floor | **Cohen's κ ≥ 0.70** at `n_double ≥ 100` double-graded items | below 0.70 the judge is not measuring what a second judge measures, and the number is noise with a decimal point. `OW-Q-011` refuses the run |
| validation | a **second, independent** judge (a different model family, not a different temperature) on a sampled set, blind to the first | graphify's own judge validation reports **90.6% agreement, Cohen's κ 0.81** on LOCOMO, and it is the only published memory benchmark in the collection that discloses judge validation at all. Its number is the bar |
| grading unit | a gold set of **atomic key facts** a correct answer must contain, scored `coverage = (covered + 0.5·partial) / total` | a single opaque score cannot be audited; a key-fact list can |
| auditability | **every verdict cites a verbatim quote from the answer** | so the grading itself is reviewable, not just the grade |
| presentation order | on the pairwise comparison, which candidate is shown first is `blake2b(assertion_id‖run_id‖"ow-judge-1")[0] & 1` | position bias is real and needs a balanced order; a *shuffled* order would need an RNG, which §3 forbids, and could not be replayed from the row that recorded the verdict |
| blinding | the pairwise judge never sees a producer name, a driver id or a file path — only two normalised texts | otherwise the anydoc defect returns wearing a judge's clothes: a judge told which output is the framework's own is an entrant scoring itself |
| publication | κ is published on the scoreboard beside every judge-graded row | a judge-graded number with no published κ is `UNRANKED` |
| determinism | the judge runs through a Cassette in CI like any other model call | a judge that can be re-rolled is a judge that will be |

## 11. The public scoreboard

### 11.1 What is published

A static site generated from a committed `eval/results/**.json` tree, **byte-diff gated** (`Q-G19`), so a
scoreboard change is a reviewable diff and not a deploy. The `.oweval` file itself is generated and
`.gitignore`d; `ow eval publish` exports the `eval_scoreboard` view into the committed JSON tree. *(Build note, D828: `omniweave_conform.scoreboard.export()` writes one canonical JSON file per `(suite, subject)`, every view row whatever its direction. The view gained `m.run_id`, because each row must carry its run's `measured_on`, `not_measured`, `confounders` and `fairness`, and the view is the only home of `standing`. Q-G19's row clause refuses a missing field, an empty scope or confounder list, and a null number on a row whose method is not `none`; its byte clause names changed, missing and extra files.)*

Every row carries, and `Q-G19` fails the row if any is missing or empty:

| field | source | why it is required |
|---|---|---|
| `value`, `n`, `ci_lo`, `ci_hi`, `method` | `eval_metric` | a driver measured on 12 documents and one on 1,200 would otherwise be indistinguishable, and no Guard could fire |
| `slice_key` | `eval_metric` | quality is always **per slice**, and §8.3 states which vocabulary the harness's slice comes from |
| `truth_kind` | `eval_metric` | `agreement` and `self` are visibly not accuracy |
| `measured_on` | `eval_run`, as canonical JSON | all ten `MeasuredOn` fields; a partial table is a `TypeError` at construction, not a blank cell |
| `witness` | `eval_run` | only `ci` is ranked |
| `unpinned`, `entrant_bias` | `eval_run` | an `unpinned` weights revision or a vendor match forces `UNRANKED`, with `†` on entrant-bias rows **including ours** |
| `not_measured[]` | the run | **required non-empty.** Every benchmark has a scope; a scoreboard that does not state its scope reads as universal |
| `confounders[]` | the run | **required non-empty.** The embedder-lock case (§8.4) is the worked example |
| `standing` | the `eval_scoreboard` view | `UNKNOWN` \| `WITHHELD` \| `UNRANKED` \| `RANKED`, computed in SQL from the row and never typed by a human |
| judge κ | `eval_run.fairness` | on every judge-graded row |
| `holdout_gap` | the run | `⚠` above 5 points |

**The default sort is accuracy-per-dollar within a licence tier**, and the arithmetic is stated because a
ratio with a zero denominator is exactly the kind of thing that ships:

```text
group by  (licence_tier, cost_class)          -- cost_class is already the router's ordering key
sort  by  value / max(spend_micros / n_docs, 1)   descending, then value descending
```

The `max(…, 1)` floor is one micro, so a `free` driver — whose `spend_micros` is legitimately zero —
sorts by raw `value` at the top of its group rather than dividing by zero or sorting last. Three reasons
for the default, each mechanical rather than editorial: a raw-accuracy sort ranks a 7B VLM above a `free`
deterministic path that costs nothing and is 90% as good, which is the wrong default for a framework
whose routing rule is deterministic-first; `cost_class` is already the framework's single ordering key
for pass selection, so the board sorts on the axis the router decides on; and grouping by licence tier is
the only way a reader learns that the top row is `forbidden` for their deployment before they try to
install it.

### 11.2 Cadence, and what the wall clock actually is

| what | trigger | budget | witness |
|---|---|---|---|
| T0-T3 | every PR | see below | — |
| T4 eval, all seven suites | nightly, `ow-bench-1` | ≤ 90 min | `ci` |
| T5 soak | weekly | ~3 h | `ci` |
| calibration fit (`ow eval calibrate`) | weekly | ≤ 20 min | `ci` |
| scoreboard publish | every tag, plus a nightly `pre` channel | — | `ci` |
| corpus release (`omniweave-golden@YYYY.MM`) | twice a year | — | new `corpus_digest`; MDE recomputed; baselines re-anchored |
| human label refresh (2,400 blocks) | annually | ~4 person-days | `human` |
| visual review of the 5% sample | every corpus release | ~1 h | `human` |
| runner cross-check (`pacer_cross_runner`) | every corpus release | ≤ 30 min | `ci` |
| third-party witness re-run | on submission and at every corpus release | — | `third_party` |

The PR tiers run as five parallel jobs, so the number a contributor waits on is the **critical path**, not
the sum: `parity` at ≤ 10 min dominates, and `gates` (3), the nine `test` cells (4 each), `golden` (4) and
`conform` (5) all finish inside it. The number the project pays is different and worth stating separately
— 3 + (9 × 4) + 4 + 5 + 10 = **58 CI-minutes per PR** — because that is the number that decides whether
the nine-cell matrix is affordable, and it is the number a proposal to add a tenth cell has to move.

### 11.3 Results are published when they get worse

The rule, stated as a mechanism rather than a value: **`ow eval publish` has no filter on direction.**
There is no flag to omit a regressed metric, no draft state a bad number can sit in, and no manual step
between the nightly run and the `pre` channel. A regressed metric publishes with `state = 'regressed'`
and its delta against release N−1, and the release notes carry the row.

Three supporting mechanisms, because a rule with no mechanism is a preference:

1. **`state`'s zero value is `unknown`, not `ok`.** A metric that failed to compute cannot silently
   vanish from the board; it appears as `UNKNOWN`, and `ow eval release-check` **refuses** the release on
   it. Omitting a number therefore blocks the release harder than publishing a bad one.
2. **`baselined` suppresses noise without suppressing news.** The headline count is `severity == error`
   **plus** `severity == warning AND provenance == INTRODUCED AND NOT baselined`. Three orthogonal axes
   with one job each: severity blocks, provenance attributes, `baselined` suppresses. None of them is a
   mode, and none can hide an error.
3. **The scoreboard is byte-diff gated, so a deletion is a diff.** Removing a row from
   `eval/results/**.json` shows up in review as a removed row with an author's name on it. That is the
   entire enforcement, and it is sufficient because the alternative — a generated site with no committed
   source — is what makes every other project's benchmark page unfalsifiable.

The reason this matters commercially and not only ethically: the scoreboard is the adoption asset. A
reader deciding whether to replace a loader stack is looking for evidence that our numbers are
measurements rather than marketing, and the only evidence that carries is a published regression. A board
that has only ever improved is a board nobody believes, and `†` on our own entrant-bias rows is the same
argument in one character.

### 11.4 `.oweval` retention, because the grain is verdicts and the cadence is nightly

The publishing story above is about a committed JSON tree, which is small. The `.oweval` file behind it is
not, and nothing in the charter says when a row leaves it. The arithmetic decides the mechanism:

```text
4,000 assertions × 15 subjects × 2 evaluators   = 120,000 eval_verdict rows per nightly run
× 365 nights                                    ≈ 43.8 M rows/year
× ~120 B/row (WITHOUT ROWID, empty explanations) ≈ 5.3 GB/year
```

So retention is a mechanism, not hygiene. `ow eval prune --keep-releases 4` deletes `eval_run` rows older
than the last four corpus releases, cascading to `eval_verdict`, `eval_metric`, `eval_counter` and
`eval_perf` through the existing `ON DELETE CASCADE`. Three rows are never pruned:

- a run referenced by a committed `eval/results/**.json` row — the published number must stay
  reconstructible from the file that produced it;
- a run named in `eval/baselines/` — a Guard's N−1 and N−2 anchors;
- `eval_corpus` and `eval_assertion`, ever. They are the corpus, not the run, and `derived_from_sha256`'s
  licence chain has to survive every prune.

`eval_flake`'s 30-day window prunes on its own clock and is unaffected. The empty-explanation rule from
§8.1 is what keeps 120 B/row true: a run whose assertions mostly failed is legitimately larger, which is
the right direction for the size to move.

## 12. Driver conformance and the `quality` suite

The eleven mandatory suites, the driver testkit, the badge string and the full entitled/not-entitled table
are [04](04-driver-system.md) §8's, and are not restated. This section owns three things that are about
**numbers** rather than about the descriptor: the twelfth suite, the procedure that produces a benchmark
row, and the exact boundary between a number a third party may publish and a number they may not.

### 12.1 The twelfth suite

| suite | mandatory | the quality question it answers |
|---|---|---|
| the eleven | yes | is the descriptor honest — see [04](04-driver-system.md) §8.2 |
| **`quality`** | **no** | what does this driver actually score, on which corpus, at what `n`, with which interval, under which `MeasuredOn` |

The `quality` suite is deliberately not mandatory: an accuracy number is expensive to produce, needs a
licensed corpus, and a driver that declines to produce one is honest rather than deficient. What is **not**
optional is the shape of the number if it exists. `ow conform --bench` writes the `[quality]` block, and
it writes four keys the author may not:

| kit-written key | why the author may not write it |
|---|---|
| `n` | a driver measured on 12 documents and one measured on 1,200 would otherwise be indistinguishable, and no Guard could fire |
| `ci95` | a point estimate with no interval cannot be compared to anything |
| `witness` | the author would write `ci` |
| `measured_on` | all ten `MeasuredOn` fields, `corpus`, `corpus_digest` and `harness_version` included; `MeasuredOn` is frozen with no defaults, so a card supplying seven of them raises `TypeError` at construction rather than writing a blank cell |

There is **no row-level `corpus_digest`**: the corpus identity lives inside `measured_on`, exactly once,
so `DR24` has one field to read and cannot be pointed at two candidates. `[cost.measured]` is kit-written
on the same rule (DR13), and the card loader recomputes `attestation`, so a hand-edited card sets
`attested = false`.

### 12.2 How a third party produces a benchmark row

Six commands, and the fourth is the one that matters.

```console
$ ow drivers scaffold parse.notebook.ipynb           # the card, the fixtures dir, the CI job
$ ow conform --card src/omniweave_driver_ipynb/driver.toml
  card ok . purity ok . contract ok . capability ok . idempotence ok . determinism ok(byte_exact)
  limits ok . sandbox ok . cost ok . licence ok . fuzz ok         11/11 mandatory, 41 s
$ ow eval fetch omniweave-golden@2026.09             # digest-verified, into $OMNIWEAVE_HOME/golden/
$ ow conform --bench --corpus omniweave-golden@2026.09
  wrote [quality] . structure_f1 = 0.912 (n=418, ci95 0.884-0.934, closed_form, witness=self)
  wrote [cost.measured] . p50 8.1 ms  p95 34 ms  (in_process, x86_64-linux 8c/16GiB)
  recomputed attestation
$ ow conform --diff-against v0.1.4                   # descriptor drift since the last tag
$ ow conform --badge
  omniweave-conform/1.2.0 mandatory=11/11 quality=self card=sha256:4a1f...
```

Four rules make the run mean something, and all four are about the number rather than the badge:

1. **`witness = "self"`, always, for a locally produced row.** There is no flag that sets `ci`. Only
   omniweave's own workflow on the published corpus produces `ci`, and the `eval_scoreboard` view's
   `standing` column returns `UNRANKED` for everything else.
2. **`DR24` closes the modified-corpus hole.** A benchmark row whose `measured_on.corpus_digest` does not
   match a digest in the omniweave release manifest is treated as `witness = "self"` **regardless of what
   it declares**, and a `witness != "ci"` row is displayed, never ranked, and never read by
   `ow route propose`. That is the answer to "run the kit against a locally modified copy of
   `omniweave-golden 2026.09` and get a perfectly valid attestation".
3. **CI runs the kit from a trusted tag, never from the PR branch** (DR23). `ow drivers verify` re-runs
   the kit locally against installed bytes, and a supplied report alone is never sufficient. §8.7 states
   what else a submitted row is subjected to.
4. **`--cassette required` for any suite that can reach a model.** A third party's `quality` run on a
   `billed_api` driver records its cassettes and submits their digests with the row; `OW-Q-016` refuses a
   `third_party` witness row whose cassettes cannot be replayed.

### 12.3 The boundary, stated only where it is about a number

[04](04-driver-system.md) §8.4 owns the entitlement table. The quality-specific half of it is one row and
one asymmetry.

| entitled to claim | not entitled to claim | the mechanism that refuses |
|---|---|---|
| the kit-written `[quality]` and `[cost.measured]` blocks, as measurements on the corpus and hardware `measured_on` names, carrying `witness = "self"` | any accuracy or quality **ranking**, and any number against a corpus digest outside the release manifest | `witness != "ci"` is `UNRANKED` in `eval_scoreboard`; DR24 rewrites the witness at card load |

The asymmetry is deliberate and it is the adoption argument. Passing the kit is cheap, mechanical and
locally reproducible, so a third party reaches "auto-selectable under a default configuration" in an
afternoon — while every claim that would rank them against a first-party driver needs a `ci` witness on a
published corpus, which they cannot manufacture. That is what makes the badge worth having and the
scoreboard worth reading at the same time, and it is why the kit measures descriptor honesty rather than
excellence.

## 13. Extends the charter

Marked explicitly because the charter is settled law and these are additions in its spirit. Nothing here
contradicts it; each item names the charter clause it grows out of. §13.1's four gates widen the `Q-G`
range to **`Q-G1`-`Q-G27`**, which is now the range every document states:
[ADR-11](adr/0011-eval-register-reconciliation.md) rules the series closed at twenty-seven and moves
`00-vision.md`'s `V10-1`, [01](01-principles.md) and [16](16-roadmap.md) onto it. Adding a `Q-G` gate
means moving that count in all four homes in the same pull request.

### 13.1 Four new Q-G gates

| gate | asserts | the defect it catches |
|---|---|---|
| **Q-G24** | **test inventory.** `eval/inventory.toml` — per-area unit and property counts — byte-matches `pytest --collect-only -q` on the ubuntu/3.11 cell, and a net decrease in any area fails without a `BLESS.log` row (`OW-Q-013`) | a `skipif`, a broken marker expression or a deleted `conftest.py` silently removing 300 tests. Nothing else in the framework measures test *count*, and a Counter cannot (Q-Q6) |
| **Q-G25** | **tier placement.** Every test resides in the directory its markers permit; the `tests/unit/` autouse fixture patches `socket.socket`, `subprocess.Popen`, `time.time` and non-`tmp_path` `open()` to raise; a `@pytest.mark.golden` outside `tests/golden/` fails (`OW-Q-014`) | the pyramid decaying into a flat list where a unit test opens a socket and the 4-minute T1 budget quietly becomes 11 |
| **Q-G26** | **split and corpus leakage.** No `doc_key` appears in two splits under the recomputed `blake2b(doc_key‖"ow-split-1") % 100`; no Tier-A fixture sha256 appears in `omniweave-golden`'s manifest; no `eval_assertion.derived_from_sha256` points at a fixture outside its own corpus (`OW-Q-015`) | a fixture used to debug a parser becoming part of the corpus that scores it, which inflates every number and is invisible in every report |
| **Q-G27** | **metric rot.** A metric published with no `[[gate]]` row for more than two corpus releases either gains one or is removed from the scoreboard | a board full of numbers nobody has committed to, which is indistinguishable from a board full of numbers |

`Q-G17` stops a *gate* from rotting; `Q-G24` and `Q-G25` stop the *suite* from rotting, and the suite is
the larger surface. Three existing gates also gain a clause: `Q-G2` gains the cassette budget and the
orphan sweep (§4.7), `Q-G15` gains **two** clauses — the budget-versus-ceiling arithmetic and the
`process` key on every `rss.` row, both §2.9 — and `Q-G17`'s rot clock gains two more files to read
(`eval/quarantine.toml`, `fixtures/index.toml`). *(Build note, D846: `ow eval bless --inventory --reason TEXT` is OW-Q-013's fix. Behind `OMNIWEAVE_BLESS=1`, it collects, rewrites `eval/inventory.toml` and appends the `BLESS.log` row Q-G24 asks for. The row's glob is the inventory, each area that fell is `structural` and each other area that moved is `incidental`, and the author is `git config user.email`. It refuses when nothing fell, since a count that only grew needs no row, and when the collection fails. `--counters` is parsed and refused. The counting moved into `omniweave_conform.inventory`, which the verb and `tools/gate_inventory.py` share. Q-G3's idle check now counts a changed inventory as blessable, so the row Q-G24 asks for is not idle.)*

### 13.2 Seven new `OW-Q-*` codes

Appended under `codes.toml`'s existing append-only rule (`G13`), never renumbered, never reused.

```text
# OW-Q-012 unexplained golden churn: {n} lines in {reduction}, empty shape delta
#                                                     -> ow eval golden --explain {file}
# OW-Q-013 test inventory decreased in area '{area}': {old}->{new}
#                                                     -> ow eval bless --inventory --reason '<>'
# OW-Q-014 test '{test_id}' marked '{marker}' outside {dir}
#                                                     -> move the test, do not move the marker
# OW-Q-015 eval split leakage: doc_key {key} in both {a} and {b}
#                                                     -> drop the fixture or re-derive the split
# OW-Q-016 third-party witness row unverifiable: {reason}
#                                                     -> ow eval run --witness third_party --cassette required
# OW-Q-017 cassette {key} is {n} bytes, over MAX_CASSETTE_BYTES
#                                                     -> re-record against a smaller fixture
# OW-Q-018 cassette {key} committed but never hit
#                                                     -> ow eval record --prune
```

### 13.3 The `ow eval` group

The charter names five verbs (`run`, `golden`, `bless`, `record`, `release-check`) plus `calibrate` and
`correlate` in `F22`/`F23`, and writes the group as `ow eval …`. The full set, twelve imperative verbs, no
aliases:

```text
ow eval run [--suite S] [--corpus C@V] [--subject D] [--witness W] [--cassette MODE]
                                                     [--validate-judge] [--emit PATH]
ow eval golden [--bless] [--reason TEXT] [--explain FILE] [--geometry] [--diff]
                                                     [--schema-bump OLD->NEW] [--mask FIELD]
ow eval bless  [--counters] [--inventory] --reason TEXT
ow eval record --service NAME | --prune
ow eval calibrate [--trust] [--signal NAME] [--fit] [--report]
ow eval correlate --signal A --against B [--slice S]
ow eval explain <test_id | metric | assertion_id>
ow eval publish [--channel pre|release]
ow eval fetch <corpus>@<version>           # digest-verified install into $OMNIWEAVE_HOME/golden/
ow eval import                             # eval/staging/*.ndjson -> .oweval, one transaction
ow eval prune [--keep-releases N]          # default 4; never touches eval_corpus or eval_assertion
ow eval release-check                      # exit 0 iff zero `unknown`, zero hard-gate failures
```

`ow eval fetch` re-verifies on every use and never re-fetches on a mismatch. `ow eval release-check` is
the one command a release pipeline runs, and it refuses on `unknown` — which is why `SKIP` is not a state
anywhere in this document. *(Build note, D840: `omniweave_conform.release.check_release()` is the verb, reached across the `[omniweave.eval] release-check` entry point. It judges each `(suite, subject, corpus)`'s latest run and counts the older ones as superseded. It refuses on a latest run whose status is `unknown`, read from `eval_run` because the view leaves such a run out; on an `UNKNOWN` scoreboard row; and on an `eval_perf` row that is not `pass`, since `unstable` is `unknown` and a `fail` or `stale` row that a release could ship past would be a warning. A hard gate is a `kind = "hard"`, `class = "blocking"` row of `eval/gates.toml`. It holds every latest row of its suite and metric whose slice its glob matches to exactly its budget, and a hard gate no row matches is refused as unmeasured. `--strict` also refuses each of the seven suites with no run at all. A finding exits 1, and a missing `.oweval` or register exits 2. Not built: 17-risks.md's `tools/risks.toml` and kill-criterion clauses, as that register does not exist yet, and holding a run's `code_fingerprint` to the checkout.)* *(Build note, D868: `ow eval run --suite parse` is the first writer of an `.oweval`. `omniweave_conform.eval_run` measures the register's parse `[[gate]]` rows this build computes, which is `span_exact_rate`, over each `[[subject]]`'s driver and fixtures, through the calls `tools/ow_eval.py` makes. It writes one corpus, run and metric per subject in one transaction, across the `[omniweave.eval] run` entry point. A fixture set is a Tier A corpus (D844) versioned by its digest's first sixteen hex characters, and `publishable` is false because a driver's authors wrote it, so the scoreboard reads `WITHHELD`. The metric's truth is `native_run`: the register's `self_verifying` is not a `TruthKind`, and re-verifying a span against source bytes is fidelity. A vacuous rate writes no metric and names the vacuity in `not_measured`. A hard fidelity row takes `stats.rate()`, not `min_slice_n`. The other six suites, `--validate-judge`, `--emit` and the global `--corpus` are refused by name. Over the repository's register, `release-check` then refuses on one finding: `degradation_detection` is unmeasured.)* *(Build note, D869: `ow eval run --suite absence --deterministic-half` lands, and `ow eval run` with no `--suite` runs `parse` then `absence` in one transaction. The harness `tools/ow_damage.py` held moved to `omniweave_conform.absence`, and the script now calls it. 13:1306's admission against the Action registry moved to `omniweave.surface.admit`, and the verb hands it across the entry point, the one callable that crosses, because conform may not import the registry. The run's subject is `omniweave`, the product, `spawn_inclusive`, over `reference_corpora/quick`, the committed generator's documents. Its metric is `degradation_detection`, the passing pairs over the pairs, sliced `deterministic_half`. The nine owed Injectors and the absence-corpus half are named in `not_measured`. Over the repository, `ow eval release-check` exits 0. `--strict` refuses on extract, retrieve, roundtrip, portability and perf, which nothing runs.)* *(Build note, D870: `ow eval run --suite retrieve` measures the suite's two self-verifying rows, which `eval/gates.toml` now carries: `citability_violations`, hard at 0 (13:1094), and `citation_soundness`, a floor at 0.995 (13:1101). `omniweave_conform.retrieval` asks the adoption catalogue's questions, `bench/serve/tasks.toml`, every task but the `damaged`, of the three generated corpora at `quick` scale, each built by a real `ow add`. It renders each Answer as `ow query` does, and checks every cite its block headers and pointers carry: does a live head block carry it, and does `locate_block()` place it with a `Quad` or a `Locus.reason`? A set `byte_exact` bit counts as unsound, since nothing re-grounds it, and no stored block sets one. The register's `self_verifying` maps to `native_run`. The relevance metrics, OUT11's artefact half and the damaged tasks are named in `not_measured`. Over the repository: 18 Answers, 286 cites, every one sound, no violation, and `ow eval release-check` exits 0 over three hard gates.)* *(Build note, D871: `ow eval run --suite roundtrip` holds law R2 (13:1564) over each register `[[target]]`, a compile card, its `read_back` card and its golden. `omniweave_conform.roundtrip` activates both drivers from their cards, loads the construct table with the target's normalizers, and runs the conformance `target` suite's `run_target()`. It then states R2 for every element `addressed()` finds. Each element is one `eval_assertion` of 13:1011's `roundtrip` type and one `owdoc` verdict, its id carrying the golden's version, with `checked` NULL. 13 names no metric for R2, so a failed element is a failed verdict, not a gate, which every run says. An R2 the suite cannot judge is an `unknown` run. The pptx golden ships the `Probe Sans` face it names, written by `tests/fontkit.py`, and the register points `font_dir` at it. Over the repository, docx's 7 addressed elements and pptx's 26 all survive. `release-check` exits 0 over six runs, and `--strict` refuses on extract, portability and perf.)* *(Build note, D872: every suite can report `unknown`, as 16-roadmap.md:942 requires. `ow eval run --suite extract`, `portability` or `perf` writes one run with status `unknown`. Its `not_measured` says exactly what is missing. extract has no harness and no labelled corpus; portability is defined by its name alone; perf passes only against 7-run medians on the pinned `ow-bench-1`. It has no corpus row, metric or perf row. They run only when named: `--suite` omitted runs the four suites this machine can judge, so a plain `release-check` stays a judgement of those. A run finding's fix names `--subject` only for a parse run, the one suite whose subject `ow eval run` takes.)*

### 13.4 Five new constants

All in `omniweave_core.limits` except `MAX_DRIFT_BAND`'s consumer, which is the kit.

| constant | value | what it bounds |
|---|---:|---|
| `MAX_DRIFT_BAND` | `0.02` | the ceiling on a `seeded` driver's kit-measured `drift_band` (§7.2). Above it the card must declare `unpinnable`. Chosen so a 1,000-block document's drift stays below `rebind()`'s quarantine threshold |
| `MAX_REDUCTION_BYTES` | `262_144` | `Q-G2`'s 256 KiB per Reduction file, named so §5.2's derived page and block ceilings have something to reference |
| `MAX_CASSETTE_BYTES` | `262_144` | one committed Cassette. The same number, reused: both are committed artefacts a human must be able to diff |
| `MAX_CASSETTE_BYTES_TOTAL` | `33_554_432` | the Cassette store, inside Tier A's 64 MB rather than beside it |
| `MAX_PARTIAL_FRAC` | `0.02` | above this share of missing verdicts, a `partial` run's affected metrics become `unknown` (§8.7) |

Every one is a `MAX_*` a tenant may clamp below and never widen, and one the producer is built never to
exceed — the rule [01](01-principles.md) applies to the whole `MAX_*` family.

### 13.5 Five new files, three new perf rows, two new gate rows

**Files**, all generated-and-byte-diff-gated except `quarantine.toml`, which is hand-written and
rot-checked:

| path | generated from | read by |
|---|---|---|
| `eval/inventory.toml` | `pytest --collect-only -q` | `Q-G24` |
| `eval/quarantine.toml` | a human | `Q-G18`, `Q-G17` |
| `eval/cassette-usage.toml` | the T2 and T3 runs | `Q-G2`'s orphan sweep |
| `eval/staging/*.ndjson` | each xdist worker; `.gitignore`d | `ow eval import` |
| `fixtures/goldens/DECOMPOSITION.toml` | a human | the churn classifier (§5.4) |

**Perf rows**, each satisfying §2.9's `value + tol_abs ≤ ceiling`:

```toml
[[budget]]
id = "t0.gates_job_s"
value = 128
tol_abs = 40
gate = "pr"
note = "T0's ceiling is 180 s; 128 + 40 = 168 leaves 12 s of headroom."

[[budget]]
id = "test.cell_ubuntu_311_s"
value = 185
tol_abs = 50
gate = "pr"
note = """The 9-cell T1 ceiling is 240 s. 185 is the measured ubuntu/3.11 cell, of which the 258
hypothesis properties at max_examples=200 are the dominant term (Q-Q1)."""

[[budget]]
id = "golden.job_s"
value = 190
tol_abs = 45
gate = "pr"
note = "T2's ceiling is 240 s; 190 + 45 = 235."
```

**Gate rows**, both dated rather than immediate, which is how `Q-G27`'s clock is satisfied by a commitment:

```toml
[[gate]]
metric = "source_reread_rate"
slice = "bench_serve/*"
budget_max = 0.25
active_from = "v1.0"
owner = "team@particle6.com"
review_by = "2027-06-01"
note = """Vision section 10's stop condition. Reported and paired by Q-G21 from release 1; gated from
v1.0. V-Q1's fallback re-anchors to a 60% relative reduction against the control arm."""

[[gate]]
metric = "task_accuracy"
slice = "bench_serve/*"
guard_against = "control"
guard = 0.0
owner = "team@particle6.com"
review_by = "2027-06-01"
note = """A Control guard, not a release Guard: the baseline is the no-omniweave arm of the SAME
nightly run. A run in which source_reread_rate falls and task_accuracy falls with it fails here."""
```

### 13.6 Five new Injectors and one new `TruthKind` obligation

§8.6 adds `stall`, `mask_format`, `inflate`, `strip_integrity` and `synopsize`, taking the Injector set
from the charter's eight to thirteen — one per member of `ABSENCE_BLOCKING_DIAGS`. This is the change
that makes `degradation_detection == 1.000` a claim about a population rather than about a sample, and it
is the only place this document strengthens a charter gate rather than implementing it.

`normalize_eval()` (§8.2) is a new function in `omniweave_conform.normalize` and a new obligation on
`omniweave_core.ident`: the shared fold table becomes a named `fold_common` so the evaluator can compose
it rather than copy it. That is the only change this document asks of core.

## 14. Where every Q-G gate is enforced

One row per gate, with its enforcement class from [01](01-principles.md)'s ladder (`A` architecture,
`S` schema, `L` lint, `G` gate, `X` test, `R` review), so a reviewer can tell at a glance whether a gate
rests on a test or on something a violation cannot get past.

| gate | class | site |
|---|---|---|
| Q-G1 corpus licence | `G` + `S` | `tools/gate_fixtures.py` over the generated `fixtures/index.toml`; every sidecar key is `NOT NULL`-equivalent in the generator |
| Q-G2 fixture budget | `G` | the same gate: 64 MB total, 256 KiB per Reduction, ≥ 40% real scans, ≤ 32 MiB of Cassettes, no orphan cassette, `size-pack ≤ 200_000` KiB after `git gc` |
| Q-G3 golden bless | `G` + `X` | a `BLESS.log` row in the same commit; `test_bless_flag_is_off()` at `X` |
| Q-G4 frozen stability | `G` | the `golden` job × two pdfium minors, plus the nine-cell `test` matrix *(Build note, D931: wired. Each of the nine `test` cells runs `tools/gate_frozen_stability.py --emit` and uploads its shapes; `golden` now waits on `test`, gathers them and compares nine cells at one pinned pdfium, :673-677's fallback, with `--cells 9` making a missing cell a did-not-run. win32 py3.12 and linux py3.13 matched the goldens byte for byte locally before it landed. No cell runs a second pdfium build, so the two-minor half is still F31's.)* |
| Q-G5 counters | `G` | `eval/counters.toml` compared against the run manifest, `route_spend` and `driver_observation` — the three run-sourced `source` classes; a `source = "ci"` row is read for shape and compared against nothing (§2.8) |
| Q-G6 verbatim | `G` (hard) + `L` | `span_exact_rate == 1.000` on a deterministic n = 1000 block sample; `owcheck`'s verbatim-implies-retained-part clause |
| Q-G7 absence | `G` + `X` | the paired-damage half at T2 over thirteen Injectors; the absence corpus at T4 |
| Q-G8 measured-on | `A` + `G` | `MeasuredOn` frozen with no defaults (a `TypeError`, not a blank cell); the static half in T0 over committed results |
| Q-G9 truth | `G` | the harness refuses a metric whose reference producer equals the subject producer |
| Q-G10 score-declared | `A` + `G` | an unregistered `score_kind` **raises at `DocSink.add_block`**; both directions gated in T0, including a `shape` counter with no `DECOMPOSITION.toml` row |
| Q-G11 separation | `X` | `separation()` plus `P-21` |
| Q-G12 sharpness | `X` + `S` | `sharpness()`; failure writes the `NULL`/`NULL` pair, whose atomicity is a `CHECK` |
| Q-G13 freshness | `X` | `max_age_days = 30`; the weekly fit gives 4× headroom |
| Q-G14 render | `X` | a renderer test over all four `CalStatus` values, asserting output **shape** |
| Q-G15 perf | `G` | `eval/perf.toml` on `ow-bench-1`; Pacer ratios, absolute memory, exact counters, §2.9's `value + tol_abs ≤ ceiling`, and `process` present and in vocabulary on every `rss.` row |
| Q-G16 anti-ratchet | `G` | release-anchored baselines, N−1 at tolerance and N−2 at 2× |
| Q-G17 gate rot | `G` | every `[[gate]]` row's `owner` and `review_by`, across `gates.toml`, `counters.toml`, `quarantine.toml` and `fixtures/index.toml`; a row past its date fails |
| Q-G18 flake | `G` | `eval_flake` over a 30-day window; > 2% quarantines into the byte-diff-gated register with an expiry |
| Q-G19 scoreboard | `G` | byte diff over `eval/results/**.json`; required non-empty `not_measured[]` and `confounders[]` |
| Q-G20 judge | `X` | κ ≥ 0.70 at `n_double ≥ 100`, or `OW-Q-011`; blinding and digest-derived presentation order |
| Q-G21 pairing | `G` | `field_acc` without `doc_acc` fails; `hallucination_rate` alone fails; `source_reread_rate` without `task_accuracy` fails |
| Q-G22 parity | `G` | a clean container: no network, no GPU, no Node, ≤ 600 s hard |
| Q-G23 self-test | `X` | the harness scores a dropped page, a transposed table and a fabricated quote against the exact values in §8.5 |
| **Q-G24** test inventory | `G` | `eval/inventory.toml` byte diff against `pytest --collect-only` |
| **Q-G25** tier placement | `A` + `G` | an autouse fixture makes the violation raise; the marker check gates the rest |
| **Q-G26** leakage | `G` | recomputed split, fixture-versus-corpus digest intersection, assertion provenance |
| **Q-G27** metric rot | `G` | a two-release clock on every ungated published metric |

## Open questions

Numbered `Q-Q` so downstream documents can reference them. Charter §7's `F1`-`F41` are not restated; only
questions this document's own subject raises. Each names what closes it. **Q-Q5, Q-Q6, Q-Q10 and
Q-Q11 are answered** by [ADR-11](adr/0011-eval-register-reconciliation.md) and keep their numbers so
downstream citations resolve; what follows each of those four is the ruling, not the question.

- **Q-Q1 — Are the T1 test counts achievable inside 240 s per cell?** 258 hypothesis properties at
  `max_examples=200` is 51,600 example executions, and the 185 s budget assumes they run under
  `pytest-xdist` in their own group with a 200 ms per-example deadline. *Closes:* the first full nine-cell
  run at v0.1, reporting per-property wall time. *Pre-committed fallback:* the `pr` profile drops to
  `max_examples=100` for the twelve slowest properties, named individually in `conftest.py` with the
  measured time beside each, and the nightly profile stays at 2,000. **Not** a blanket reduction, because
  a uniform cut hides which property is expensive.
- **Q-Q2 — Is `fixtures/goldens/DECOMPOSITION.toml` complete and correct?** §5.4 replaces the
  `unexplained` class's implicit global claim with a per-counter `page_wise` declaration, which converts
  the risk from "the gate false-positives" into "the table is wrong". Two counters are already declared
  `page_wise = false` on inspection (`grid.tables_with_merges`, `rel.kind.*`); nothing has yet *proved*
  the `true` rows. *Closes:* a property that, for every `page_wise = true` counter over the whole Tier-A
  corpus, asserts `shape[c] == sum(pages[p][c] for p in pages)`. That property is cheap and should land
  with the reducer, before the golden suite freezes. *Bias:* a counter whose decomposition property does
  not hold is declared `false` and loses `unexplained` protection, never the other way round.
- **Q-Q3 — Is a 5% deterministic visual sample enough to catch a systematic composition regression?** Two
  units per release is a budget, not a power calculation. A template change degrading every slide equally
  would be caught; one degrading 10% of slides would be caught in a given release with probability
  ≈ 1 − 0.95² ≈ 0.10. *Closes:* one deliberate visual regression injected into the golden corpus,
  measuring the sample rate at which it is detected within one release. *Bias:* raise the rate on the
  `deck` target specifically, since it is the only target with runtime measurement rules and therefore
  the only one whose layout can fail at render time.
- **Q-Q4 — Charter and lock gaps around `Runner`, `CalStatus`, and `unpinnable` versus `unpinned`.**
  Three related holes. (a) The lock's `timing_basis` row reads "required per Runner" and charter §D10 uses
  `Runner`, but there is no §2 row for it, so `G27(c)`'s "every `class` name in a plan document has a §2
  row" has nothing to match. (b) `CalStatus` appears in the charter as a `Literal` alias and in the lock
  only inside `Calibrated`'s own definition, so a document writing it as a type name is unchecked in both
  directions. (c) Charter §D10 states the "may not contribute a `[[quality.benchmark]]` row" rule inside
  the `unpinnable` paragraph although it keys on `weights_revision`, which §7.2 separates. *Closes:*
  merging `Runner` and `CalStatus` rows into the lock, and an ADR recording (c). **No plan document should
  write `Runner` as a Python class name until (a) lands.**
- **Q-Q5 — Answered: there are seven suites, five with live models.**
  [ADR-11](adr/0011-eval-register-reconciliation.md) rules `eval_run.suite`'s seven-value `CHECK` the
  register and §2.5's split normative; charter §D10's "T4 eval — five suites, live models" is
  superseded at charter §9.2 `E84`. The split survives the ruling because it is load-bearing three
  times: `--cassette required` binds on the five, the ≤ 90 min budget is spent on the five, and
  `portability`/`perf` failing means the runner changed rather than the model.
- **Q-Q6 — Answered: `eval_counter` admits no `scope = 'ci'` row, and the file gains a `source` key
  instead.** The bias was right and the DDL is the reason:
  `eval_counter`'s primary key is `(run_id, counter, scope)` with
  `run_id NOT NULL REFERENCES eval_run(run_id)`, so a counter measuring the test suite is
  unrepresentable and `eval/inventory.toml` stays a byte-diff artefact under `Q-G24`. But the file and
  the table are different objects, and [repository layout](11-repo-layout.md) §6.2 already ratchets
  `ci.job_seconds.<job>` in `eval/counters.toml`. §2.8 separates them: every row declares a `source`
  over `{manifest, route_spend, driver_observation, ci}`, `Q-G5` compares only the three run-sourced
  classes, and a `ci` row never reaches `eval_counter` or the scoreboard.
  [ADR-11](adr/0011-eval-register-reconciliation.md).
- **Q-Q7 — What is the honest floor for `recall_at_10` on the memory slice?** graphify's 0.497 on LOCOMO
  is the published best of any system it tested, and it is measured on a shared BGE-m3 embedder with graph
  expansion at ~$1.40 ingest. omniweave ships `vectors = "off"` by default, so its release-1 memory slice
  runs four channels and no semantic one. Publishing a floor before measuring the four-channel
  configuration would be a borrowed number. *Closes:* the first `retrieve` suite run against LOCOMO at
  v0.1 with `vectors = "off"`, and again with the stdlib vector backend, published as two rows.
  *Pre-committed fallback:* the metric stays ungated for two releases under `Q-G27`, then gains a floor at
  the measured value minus two Wilson widths, or is removed.
- **Q-Q8 — Does `Q-G4` survive `F31`?** `shape` byte-identity across two pdfium minors is a hard gate
  resting on an assumption about whole-point geometry quantization. §5.1 writes the fallback down; the
  measurement is `F31`'s and it must land **before** the golden suite freezes. *Closes:* `F31`. Recorded
  here because this document is the one that would have to be rewritten.
- **Q-Q9 — Is the 2,400-block human anchor large enough for six slices?** 2,400 blocks across scan-clean,
  degraded, photo, handwriting, CJK and math is 400 per slice, and `separation()` needs 150 per bucket per
  slice over three `Trust` tiers — which is 450. The anchor is therefore below the requirement on any
  slice with an even tier distribution, and above it only because `EXTRACTED` dominates. *Closes:* `F22`'s
  `ow eval calibrate --trust` run, reading off the smallest workable n. *Pre-committed fallback:* the human
  anchor grows to 4,800 blocks (≈ 8 person-days) on the two slices that matter most for calibration
  (`scan-degraded`, `photo`), and `synth_ocr` carries the rest with the L4 gap printed. Do **not** pool
  slices to reach n; a pooled `p_hat` across scan-clean and handwriting is a number about neither.
- **Q-Q10 — Answered: the 256 KiB byte cap is the gate; the 500-page rule is a performance guard.**
  Both charter sentences survive with their roles named (§5.2), superseded at charter §9.2 `E86`.
  `MAX_REDUCTION_BYTES = 262_144` is what `Q-G2` fails on; the page rule only stops the reducer
  materialising ~45 MB of lines before it discovers it cannot commit them, and **may not be quoted as
  permissive**. `outline_suppressed_because` is closed at `{"bytes", "pages"}` and evaluated in that
  order, so `"pages"` is reachable only below ≈ 5.46 blocks per page (§4.4).
  [ADR-11](adr/0011-eval-register-reconciliation.md).
- **Q-Q11 — Answered: the path is `eval/runners/`.** A path in an implemented tree beats a path in
  prose. `eval/` names nine gated declaration files — `gates.toml`, `counters.toml`, `perf.toml`,
  `corpora.toml`, `quarantine.toml`, `inventory.toml`, `BLESS.log`, `baselines/`, `results/**` — plus
  [the glossary](glossary.md); the charter writes `evals/` once, and only for the `runners/`
  subdirectory. [Repository layout](11-repo-layout.md) §1.7's tree gains the directory; charter §9.2
  `E85` records it. [ADR-11](adr/0011-eval-register-reconciliation.md).
- **Q-Q12 — What produces the reference structure `structure_f1` scores against?** `TruthKind = rendered`
  says the reference is independent of our text path, but a `soffice` render is a page image and F1 needs
  a labelled tree. §8.3 resolves it by making the reference an authored artefact — a per-document
  `structure.jsonl` of `(page, kind, layer, parent_kind, normalized_text)` tuples, authored against the
  render, `checked` like any assertion — so `rendered` names *how the tuples were authored* and not an
  automatic derivation. That is honest but it is also ~600 documents of labelling. *Closes:* a cost
  measurement on the first 40 documents. *Pre-committed fallback:* `structure_f1`'s reference is derived
  from the `format`, `footnote`, `table` and `order` assertion set already in the corpus, F1 is computed
  over assertion outcomes rather than over a tree, and the gate's floors are re-derived on the new
  definition — which is a weaker metric honestly labelled rather than a stronger one nobody can afford.

## New terms

Eight coined here, for merge into [`_notes/terminology.md`](_notes/terminology.md) §2.

| Term | Kind | Definition |
|---|---|---|
| `Runner` | concept | A competitor adapter in `eval/runners/`, one file per comparator, **in-tree and unpackaged** so a heavy comparator's dependencies never reach `G2`'s weight gate. Each Runner declares its own `timing_basis` (`in_process` \| `spawn_inclusive` \| `server_attached`), and **two rows with different bases may never share a column**. A missing Runner is skipped with a warning and the report names it, so a partial setup still produces a usable report. Referenced by the lock's `timing_basis` row and by charter §D10; the path is settled at `eval/runners/` by [ADR-11](adr/0011-eval-register-reconciliation.md) (Q-Q11). `Runner` still has no terminology-lock §2 row — see Q-Q4. |
| `Injector` | concept | One paired-damage transform, **one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`**, that damages a pristine corpus in exactly one named way and asserts the answer degrades to a **named cause** rather than a confident zero. Thirteen ship: `encrypt`, `strip_text_layer`, `chaos`, `drop_part`, `budget`, `deny_probe`, `downgrade_origin_span`, `rotate_embedder`, `stall`, `mask_format`, `inflate`, `strip_integrity`, `synopsize`. Each carries the undamaged run as its counterfactual, and each asserts that its `DegradeCause.fix` command actually fixes the damage. A new Injector lands behind its own passing assertion or not at all, because `degradation_detection` is a hard gate at 1.000. **The damage half needs no model, so it gates every PR.** |
| Churn class | concept | A tracked Reduction diff's three-valued classification, and the thing the golden gate gates on instead of a line-count percentage: **`incidental`** (only `cdig`/`ldig` changed, every counter and histogram unchanged, empty `shape` delta) merges with a one-line reason; **`structural`** (a histogram moved, or a line was added or removed) requires a consistent non-empty `shape` delta, a `BLESS.log` reason ≥ 20 characters, and a second reviewer once the structural share passes 20% of golden files; **`unexplained`** (a `pages` or `outline` change with an empty `shape` delta and no page-count change, over counters `fixtures/goldens/DECOMPOSITION.toml` declares `page_wise`) **fails the build** with `OW-Q-012`. |
| `Control guard` | concept | A Guard whose baseline is the **paired control arm of the same run** rather than release N−1. One exists: `bench/serve/`'s `task_accuracy` on the omniweave arm may not fall below the no-omniweave arm at paired `p < 0.01`. It is what makes the `source_reread_rate` pairing rule a gate rather than a caution, and it is distinct from a Guard (releases) and from a Budget (an absolute floor). |
| `normalize_eval()` | fn | The **evaluator's** comparison normaliser, in `omniweave_conform.normalize`: `strip_md` (olmOCR-Bench's `<br>`-to-space and paired-emphasis stripping) composed with `omniweave_core.ident.fold_common` at `casefold=False, quotes=True`. **Not `normalize_k`**, which casefolds, and **not `nfc()`**, which is INV-10's proof normaliser ([03](03-document-model.md) §7.2) and folds strictly less than any comparison normaliser may. The owdoc evaluator uses `normalize_k`; the text evaluator uses this; the shared fold table has one home so a dash added to one is added to both. |
| `MAX_DRIFT_BAND` | const | `0.02` in `omniweave_core.limits`: the ceiling on the kit-measured `drift_band` a `seeded` `ReplayClass` may declare. Above it the card must declare `unpinnable`. Without a ceiling, `seeded` absorbs `unpinnable` by declaration and the three-valued enum collapses to a boolean. Chosen so a 1,000-block document's drift stays below `rebind()`'s quarantine threshold, and therefore below the point at which a re-parse stops carrying its ids. |
| `MAX_REDUCTION_BYTES` | const | `262_144` in `omniweave_core.limits`: `Q-G2`'s per-Reduction-file cap, named because it is the **binding** constraint on `outline` and `pages` and the 500-page suppression rule is only a pre-check. It implies ~1,190 committed pages for a `pages` file and ~2,730 committed blocks — 23-46 pages — for an `outline` file. A reduction over the cap is **suppressed with its count recorded**, never truncated. |
| `holdout_gap` | column | The signed difference between a metric's value on the 85% scoring split and on the 15% holdout, computed from the same `blake2b(doc_key‖"ow-split-1") % 100` split the calibration chain uses, and printed on every scoreboard row. Above **5 points** the row prints `⚠`: a gap that large means the published number is a fit to the corpus rather than a measurement of the subject. Distinct from a Guard, which compares releases, and from a `Control guard`, which compares arms; `holdout_gap` compares splits within one run. |
