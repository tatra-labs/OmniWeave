# Build Order and Milestones

**In one paragraph.** The order is forced, not chosen: five dependency edges — the pivot before its
producers, provenance before the first stored row, the recording before the mechanism that reads it,
the `call` cache before the first billed driver, and the Action registry before the second surface —
fix the sequence of one walking skeleton (**M0**) plus ten phases; everything else is a headcount
question. M0 is three weeks of deliberately dishonest end-to-end code that touches L0, L1, L2, L4, L6
and SERVE, falsifies six structural claims while they are still cheap to falsify, and marks every fake
with `# OW-SKELETON:` so a semgrep rule can prove the last one is gone. **v0.1** (the IN spine, four
listed Actions, no graph, no OUT, no vectors) lands at program week **42** and **224 engineer-weeks**;
**v1.0 == release 1** (the whole loop, every `G` row in `tools/gates.toml` and all 27 `Q-G` gates
green) lands at week **64** and **363.8 engineer-weeks**, peak seven engineers. Each phase has a
**freeze point** — a named set of types, grammars, vocabularies and digests that may not move
afterwards without a charter amendment, a `CONTRACT` bump or a `digest_recipe` bump — and exit
criteria that are commands with exit codes. [00-vision.md](00-vision.md) §9 owns the acceptance
definitions this document sequences toward and [13-quality.md](13-quality.md) owns the gates it
invokes; this document owns the order, the estimates, the staffing arithmetic, the build-versus-wrap
verdicts and the decision dates.

## 1. The sequencing principle

### 1.1 Five forcing edges

A forcing edge is a dependency where the reverse order does not cost rework — it costs a data
migration, a re-bill, or a lie that shipped. There are five. Every other ordering in §3 is
resourcing.

| edge | A must precede B | why the reverse order is damage, not rework |
|---|---|---|
| **FE1** | `omniweave_core.model` and the four store protocols precede **every** driver | A `parse/1` driver's `capability` conformance suite proves `origin_span = "exact"` by re-reading the retained part on whichever of INV-10's three branches (`bytes`, `nodepath`, `glyphs`) its `os_kind` selects. A driver written against a provisional `Block` has a kit-written `[quality]` block measured against a contract that no longer exists, and `ow conform` cannot re-attest it without re-running every fixture. |
| **FE2** | The six provenance axes, `Producer`, `restriction_bits` and `Taint` precede the **first row ever written** | INV-7 and INV-16 are stamped by the host *after* the driver returns, on every `block`, `segment`, `entity`, `mention`, `edge`, `claim`, `asset` and `artifact` row. Adding an axis afterwards is a backfill with no source of truth: nothing recorded which driver produced a row before the column existed, so `origin_driver` is NULL on exactly the corpus that was supposed to demonstrate the mechanism. |
| **FE3** | The **recording** precedes the mechanism that reads it | Every honesty mechanism in this framework is a comparison against something already recorded. Absence gate `parse_gap_in_scope` joins `diag` (`CREATE INDEX diag_code` exists for that join and nothing else). `agree.decode_vs_page` compares two readings already paid for. `cost.would_have_been_micros_if_uncached` reads `cache_index`'s stored `Spend`. `anchor_delta` diffs two `anchor` generations. Build the mechanism first and it has nothing to read, so it ships as a stub that always reports clean — which is INV-12's failure mode with a green test suite on top. |
| **FE4** | `cache.py`'s `call` layer precedes the **first `billed_api` or `local_compute` model driver** | The `call` layer caches a driver's raw response, not the derived rows. Without it, every iteration on a page prompt, every fixture re-run and every second `.owstore` re-pays for the whole VLM page set. This is not an optimisation; it is the precondition for iterating on a model-backed pass at all, and it is why `parse.page.olmocr` is in P5 and not in P3. |
| **FE5** | `surface/registry.py` precedes the **second** agent-facing surface | INV-20 makes the CLI parser, the SDK stubs, the MCP tool schemas, the `instructions` string, `llms.txt`, `AGENTS.md` and the router skill's action table all *generated* from one `ActionSpec` set and byte-diff gated (G25). Ship a hand-written CLI first and the registry's arrival is a reconciliation between two surfaces that already disagree — which is LEANN's defect (`llms.txt` declaring two tools against a four-tool server, G6's cited catch) arrived at from the inside. |

A sixth constraint is stated in the charter as a bare imperative and is honoured literally:
**`op.converge` must ship before the watcher**, because a watcher is precisely the thing that breaks
incremental correctness without a symptom. The consequence in this plan is that the watcher is not in
v1 at all (§18) and `op.converge` lands inside P4 as W4.6.

### 1.2 Three orderings the collection actually used, and why each is rejected

- **Parser-first** (docling, marker, markitdown): build format coverage, then a model to hold it.
  Rejected by FE1. docling's `DoclingDocument` is the asset and it arrived after twenty backends, so
  six of its defaults — `sys.maxsize` limits, a `self.valid = False` that never surfaces, a
  decompressing sniffer, `revision="main"`, torch in the base dependency set, URL fetch inside the
  converter — are now inversions [01-principles.md](01-principles.md) writes down rather than choices
  anyone could still make.
- **Retrieval-first** (LEANN): build the index, then decide what a document is. Rejected by FE2 —
  provenance is not a field you add to a vector after the fact, which is why `leann-core` needs AGPL
  PyMuPDF *and* torch to answer the question "where did this come from".
- **LLM-extraction-first** (graphrag, DataFlow): get entities out of text, then worry about identity
  and cost. Rejected by FE4 and by its measured consequence: graphrag's config axes produce a
  permanent, silent 100% cache miss — the defect G18 exists to catch — which is survivable only when
  nobody is paying per call.

### 1.3 How the phases were cut

The phase boundaries are not calendar quarters. Each boundary is placed where a **freeze point**
falls, because a freeze is the only thing in this program that is genuinely expensive to reverse:

| a boundary is placed where | example |
|---|---|
| a wire or ABI version locks | P1 ends at `CONTRACT = 1` and `card_schema = 1` |
| a digest definition locks | P2 ends at `digest_recipe = 1` and `SCHEMA = 1` |
| a vocabulary closes | P3 ends at `FailureClass`'s thirteen members; P5 at `Rung`'s ordering; P8 at `AnchorKind`'s fourteen |
| a public name becomes durable | P7 ends at the four `cite` sigils and the four listed tool names |
| a promise becomes measurable | P10 ends at `eval/gates.toml`, and every number in it carries `(n, ci95, method, MeasuredOn, witness)` |

**Freeze week and exit week are different weeks and this document reports both.** A phase's freeze
week is when its named interfaces lock and downstream phases may build against them; its exit week is
when every exit command in that phase's section exits 0. The gap is integration and hardening, it is
where most schedule risk actually lives, and hiding it inside one number is how a plan becomes a
fiction. Phases overlap across that gap by construction: P6 starts on P2's freeze, not P2's exit.

## 2. Milestone 0 — the walking skeleton

**Program weeks 1-3. Two engineers. 6 engineer-weeks. One branch, merged, never a long-lived fork.**

### 2.1 What it does

The narrowest path that touches every layer, over exactly one fixture:
`fixtures/skeleton/termination.docx` — three paragraphs and one two-row table.

```text
ow add fixtures/skeleton/
  L0   acquire.fs             -> 1 `unit` row, 1 blob in CAS, canonical_uri() applied
  L1   parse.office.anydoc    -> the real driver over the real firecrawl-anydoc wheel, inproc,
                                 one call for the whole document
  L2   DocSink (host-side)    -> 6 `block` rows + 2 `cell` rows in a real .owstore; cites minted
                                 from doc.next_cite_n; one transaction per page
  L4   retrieve()             -> identity + lexical channels over block_fts, fuse(), ceiling()
       Answer.render()        -> the fixed section order; every block carries cite/page/quote/trust
  SERVE ow query | ow open    -> CLI only, both verbs GENERATED from surface/registry.py
  L6   ow out compile         -> compile.text.owtext sketch -> 1 artifact + 2 artifact_cite rows
       ow out back            -> read_back re-enters the store as doc 2 with Method.ROUNDTRIP
```

The last two lines are the point of the milestone. A compiled artefact re-entering the corpus as an
ordinary parsed document on day 21 is the one claim in the charter that nothing else in the plan
proves cheaply, and the one whose failure would invalidate D8's "retention, not reconstruction"
synthesis before a line of `omniweave_core.out` is written.

### 2.2 What it fakes, exactly

Every fake carries a `# OW-SKELETON: <phase that deletes it>` comment. The semgrep rule
`skeleton-marker-survived` in `tools/semgrep/omniweave.yaml` fails the build on any marker present
after the P4 exit. **Skeleton code is deleted, never grown**: each row below is a deletion, not a
refactor, and a PR that extends a marked function instead of replacing it is rejected on that basis
alone.

| faked | what M0 actually does | deleted in |
|---|---|---|
| L3 entirely | no `segment` rows, no graph rows. The `structural` and `semantic` channels return `ChannelStatus.OFF` with `reason = "not_built"`, which the Answer discloses in its verdict line | P8 |
| The Supervisor | `ow add` runs a synchronous `for` loop over the roster in-process. No `work` table, no claim, no reap, no `Admission`, no `dispatch_key` | P4 |
| The router | `evaluate()` returns a hardcoded `Candidate` naming `parse.office.anydoc` at `Rung.DECODE`. No `Evidence`, no `SignalSpec` registry, no escalation, no `route_decision` row | P5 |
| Budget | `admit()` returns `admitted` unconditionally. No `budget_reservation`, no `PriceBook`, no micros anywhere in the process | P4 |
| The cache | absent; every run re-parses. Tolerable **only** because `parse.office.anydoc` is `cost_class = "free"`, which is exactly the condition FE4 states | P4 |
| The Verdict | `build_verdict()` implements 2 of the 15 absence gates. **Any other zero returns `VerdictState.DEGRADED` with `reason = "gates_unimplemented"`, never `ABSENT`.** The skeleton is structurally incapable of the one lie that matters | P6 |
| Confidence | every `Calibrated.status` is `uncalibrated`, so nothing renders a digit | never — this is v1.0 behaviour too (V10-5) |
| MCP | not built. The CLI is generated from a four-row `ACTIONS` tuple; the MCP generator raises `NotImplementedError` | P7 |
| Isolation | `inproc` only. No `subproc` host, no `omniweave-driver/1` framing, no `DriverGuard` | P3 |
| `.owdoc` | writer only. No reader, no `frames.json`, and `import(export(store)) == store` is not tested | P2 |
| `compile.text.owtext` | a ~200-line sketch. No ConstructTable, no RulePack, `GateStatus` hardcoded to `not-provided`. `omniweave_core.out` does not exist | P9 |
| The store | 5 tables of the 91 (`doc`, `block`, `cell`, `block_fts`, `unit`) plus the `block_cite` unique index. No triggers, no `enum_val`, no migration file — M0 creates its schema inline and P2 deletes that code | P2 |

### 2.3 Why this de-risks the rest

Six structural claims. Each is a one-line assertion in week 3 and a cross-cutting refactor in month
nine.

1. **A driver never holds a `DocSink`.** If M0's parse driver can be written against `DriverIO`
   alone — blobs in, `BlockDraft`s out over a frame protocol — INV-6 is structural rather than
   aspirational. If it cannot, the driver system is re-decided before P1 spends 22 engineer-weeks
   building against it.
2. **`cite` minting survives a re-parse.** Re-parse the same DOCX with a one-word edit and assert
   `d1#3` still names the same paragraph, through `rebind()` rule 2. This is the only property in the
   framework that is unrecoverable if it ships wrong, because a shipped cite is a durable public
   name that lives in somebody else's document.
3. **The Answer is text-first and fits.** Render the six-block answer and count `tiktoken cl100k_base`
   tokens. If the fixed section order plus per-block provenance already crowds SV2's 700-token
   per-tool schema budget, the section set is wrong, not the budget.
4. **The loop closes.** `read_back` is an ordinary `parse/1` driver, not a special case with a private
   path into `DocSink`.
5. **`omniweave-core` stays third-party-free with a real store inside it.** G1, G9, G17 and G23 run
   from week 1 against a core containing `sqlite3`, `json`, `zipfile` and nothing else.
6. **The Action registry generates rather than mirrors.** The CLI is generated in M0 or FE5 is not
   load-bearing and G25 will never hold.

Claims 1, 2 and 4 are the ones that would force a charter amendment. Claims 3, 5 and 6 would force a
scope change inside a decision the charter already made. That asymmetry is why M0 exists at all: the
first three are unrecoverable later and cost three weeks now.

### 2.4 Exit criteria

```bash
uv sync && uv run pytest tests/skeleton/ -q
uv run tools/gate_core_pure.py                       # G1
uv run tools/gate_importtime.py                      # G9 + G23
uv run tools/gate_lazy_core.py                       # G17
uv run semgrep --config tools/semgrep/omniweave.yaml --error
ow add fixtures/skeleton && ow query "termination" --render json | jq -e '.hits[0].cite == "d1#3"'
ow open d1#3 --render json | jq -e '.page == 1 and (.quad | length) == 8'
ow out compile --target owtext --brief fixtures/skeleton/brief.md
ow out back --last && ow query "termination" --render json \
  | jq -e '[.hits[].method] | index("roundtrip")'
python fixtures/skeleton/edit_one_word.py && ow add fixtures/skeleton \
  && ow query "termination" --render json | jq -e '.hits[0].cite == "d1#3"'
```

### 2.5 Non-goals

No performance work of any kind: no budget, no Pacer, no Counter, no `eval/perf.toml` row. No error
codes beyond the six M0 needs. No second format. No CI matrix — one cell, `ubuntu × 3.11`. No
documentation. **The skeleton is not shippable and is not shipped:** not tagged, not published,
`ow --version` reports `0.0.0.dev0`, and there is no `[project.urls]` entry pointing anywhere public.

## 3. The phase map, and the calendar arithmetic behind it

| id | phase | freeze wk | exit wk | ew | goal in one line | tier |
|---|---|---|---|---|---|---|
| **M0** | Walking skeleton | — | 3 | 6 | falsify the six structural claims end to end | — |
| **P1** | Substrate and the CI floor | 10 | 10 | 22 | ports, canonicalisation, config, discovery, 14 wheels, the gate harness | — |
| **P2** | L2 and the store | 16 | 18 | 38 | the pivot: 91 tables, the four protocols, `rebind()`, `.owdoc` | v0.1 |
| **P3** | Drivers, the host, parse | 22 | 26 | 32 | `resolve()`, both DriverHosts, office + PDF, the twelve conformance suites | v0.1 |
| **P4** | The execution runtime | 33 | 40 | 42 | Supervisor, `work`, five cache layers, budget, `dep`, `op.converge` | v0.1 |
| **P6** | Retrieval, Answer, Verdict | 33 | 40 | 34 | five channels, `fuse()`/`ceiling()`, the fifteen absence gates, the Answer | v0.1 |
| **P5** | The router | 38 | 42 | 24 | `Evidence`, pure `evaluate()`, the policy grammar, escalation, `parse.page.olmocr` | v0.1 |
| **P7** | The agent-facing surface | 42 | 42 | 26 | `ActionSpec`, seven generated surfaces, MCP, hooks, install | **v0.1 ships** |
| **P8** | L3 — the knowledge graph | 52 | 58 | 46 | Segments, anchors, entities, `op.resolve`, `op.cluster`, claims, reports | v1.0 |
| **P9** | OUT — the compilers | 56 | 62 | 60 | `omniweave_core.out`, pptx, docx, deck, `read_back`, the receipt | v1.0 |
| **P10** | Quality, calibration, release | 62 | 64 | 33.8 | `.oweval`, the pyramid, the 54 gates, the scoreboard, 14 wheels on a tag, `omniweave-langchain` | **v1.0 ships** |

**Every phase builds what another document specifies.** This one owns the order, never the design; a
work item's row is a pointer, and where the two disagree the owning document wins:

| phase | the document that specifies what it builds |
|---|---|
| P1 | [02-architecture.md](02-architecture.md), [04-driver-system.md](04-driver-system.md), [11-repo-layout.md](11-repo-layout.md) |
| P2 | [03-document-model.md](03-document-model.md), [07-store-and-retrieval.md](07-store-and-retrieval.md) |
| P3 | [04-driver-system.md](04-driver-system.md), [05-ingest-and-routing.md](05-ingest-and-routing.md), [14-security.md](14-security.md) |
| P4 | [08-runtime.md](08-runtime.md), [15-observability.md](15-observability.md), [12-performance.md](12-performance.md) |
| P5 | [05-ingest-and-routing.md](05-ingest-and-routing.md) |
| P6 | [07-store-and-retrieval.md](07-store-and-retrieval.md) |
| P7 | [10-interfaces.md](10-interfaces.md), [18-api-sketch.md](18-api-sketch.md) |
| P8 | [06-structure-extraction.md](06-structure-extraction.md) |
| P9 | [09-generation.md](09-generation.md) |
| P10 | [13-quality.md](13-quality.md), [17-risks.md](17-risks.md) |

`ew` is the sum of the per-work-item estimates in §4-§13; §15.1 states the estimation basis in a form
a reviewer can reject. Phase numbering follows the layer each phase builds, not the calendar: **P6
starts before P5** because retrieval depends only on P2's frozen store protocols while the router
depends on P4's durable ledger, and renumbering them to match the Gantt would have made every
cross-reference in this plan wrong.

### 3.1 The staffing matrix, which is the schedule

The calendar is derived from a headcount ramp, not asserted. The table below allocates every one of
the 363.8 engineer-weeks to a `(block, phase)` cell. It sums **both ways**: each row's cells equal that
block's capacity, and each column's cells equal that phase's `ew`. A reviewer who disagrees with the
schedule should attack a cell, not a milestone date.

```text
block  weeks   eng  cap | M0  P1  P2  P3  P4  P6  P5  P7  P8  P9  P10 |  used
  A     1-3      3    9 |  6   3   -   -   -   -   -   -   -   -    - |     9
  B     4-10     4   28 |  -  19   9   -   -   -   -   -   -   -    - |    28
  C    11-18     5   40 |  -   -  29  11   -   -   -   -   -   -    - |    40
  D    19-26     6   48 |  -   -   -  21  16  11   -   -   -   -    - |    48
  E    27-33     6   42 |  -   -   -   -  21  14   7   -   -   -    - |    42
  F    34-42     7   63 |  -   -   -   -   5   9  17  26   6   -    - |    63
  G    43-52     7   70 |  -   -   -   -   -   -   -   -  34  36    - |    70
  H    53-58     6   36 |  -   -   -   -   -   -   -   -   6  20   10 |    36
  I    59-64     5   30 |  -   -   -   -   -   -   -   -   -   4 23.8 |  27.8
                   ---- | --  --  --  --  --  --  --  --  --  -- ---- | -----
       total        366 |  6  22  38  32  42  34  24  26  46  60 33.8 | 363.8
```

**2.2** engineer-weeks of the 366 are unallocated, all of them in block I. **That is the program's
entire schedule buffer: 0.6%.** Block I opened with six: W10.10 bought three of them, and
[ADR-11](adr/0011-eval-register-reconciliation.md)'s four extra gate scripts bought 0.8 more
(§15.1 rule 3), which is why P10's block-I cell reads 23.8 rather than 23. Stating it is the point; a
plan whose buffer is invisible has none.

**§3's phase table is the authoritative program total, and it is 363.8 ew.** Recounted three ways
and agreeing on all three: §3's `ew` column sums to 363.8; this matrix's rows sum to each block's
capacity and its columns to each phase's `ew`, for a `used` total of 363.8 against 366 of capacity;
and P10's own work items — W10.1-W10.11 at 6, 3, 2, 3, 4, 5, 2, 3, 2, 3 and 0.8 — sum to the 33.8
its row carries. **363** appears in [`adr/README.md`](adr/README.md) §7 — "none of it inside
[16-roadmap.md]'s 363 engineer-weeks" — and is the **pre-ADR-11 figure**: correct when written, and
superseded by that same ADR's 0.8 ew debit. Where the two disagree this table wins, and the twelve
ADRs' own 37.5 engineer-days remain outside it either way.

Three things this matrix makes checkable that a Gantt alone does not:

- **The ramp is real.** Three engineers in week 1, four by week 4, five by week 11, six by week 19,
  seven by week 34, back to five for the release run-in. Nobody is assumed productive on day one of a
  program whose binding charter is 631 KB.
- **Peak concurrency is seven, in weeks 34-52** — P7 finishing while P8 and P9 ramp. Below six the
  schedule stretches roughly linearly *except on the critical path*, where P2 and P9 cannot absorb an
  extra body usefully: P2 because 91 tables share one strictly-ordered migration sequence, P9 because
  W9.1 is serial ahead of every Target.
- **P4's tail is visible.** P4 holds 42 ew but only 5 fall after its freeze at week 33. The gap
  between freeze (33) and exit (40) is integration against P5 and P6 — where the estimate is most
  likely wrong, and where §15.1's rescaling rule applies first.

### 3.2 The Gantt

```text
week       5   10   15   20   25   30   35   40   45   50   55   60
       ....|....|....|....|....|....|....|....|....|....|....|....|....
M0     ###
P1     ##########
P2        ###############
P3               ################
P4                       ######################
P6                       ######################
P5                               ################
P7                                      #########  <- v0.1 @ 42
P8                                         ######################
P9                                               ####################
P10                                                        ############ <- v1.0 @ 64
```

One column is one program week, column 1 is week 1, and the `#` runs are start-to-exit inclusive and
generated from §3.1's matrix rather than drawn by hand. The picture already states the schedule's single most
valuable fact: **P8 and P9, the two largest phases, run concurrently and neither is a prerequisite of
the other.** §14 defends it; R-Q7 states the one case in which it is false.

### 3.3 Three program-wide sequences that cross every phase

**Migrations are numbered by layer, not by date.** `schema/migrations/` applies in numeric order onto
an empty file (G27(b)), and L4's indexes and foreign keys reference L3 tables, so the numbers are
allocated in advance and a phase fills its reserved file rather than appending a new one at the end:

| file | layer | written in |
|---|---|---|
| `0001_init.sql` | L2 — the document model | P2 |
| `0002_graph.sql` | L3 — segments, anchors, entities, edges, claims | P2 creates them **empty**; P8 fills them |
| `0003_index.sql` | L4 — the occurrence tables, `embed_space`, the retrieval indexes | P2 |
| `0004_runtime.sql` | the runtime ledger — `unit`, `work`, cache, budget, `route_*` | P2 creates them **empty**; P4 fills them |
| `0005_out.sql` | OUT — the artefact tables | P9 |

The per-file object assignment is [07](07-store-and-retrieval.md) §3's; this table adds only the
phase column. Reserving a number is not shipping an empty file: G27(b) asserts the numeric prefixes
present in the tree are exactly `1..N` with no gap and no duplicate
([11](11-repo-layout.md) §5.2), so P2's exit ships four files and `0005_out.sql` does not exist until
W9.7 writes it.

P2 creating L3's **and the runtime's** tables empty is deliberate, and the reason is the tag boundary
rather than convenience: renumbering a migration is legal only until it appears in a published
release ([11](11-repo-layout.md) §5.2), v0.1 tags at week 42, and P8 and P9 run to week 62 — so
`0002` and `0004` must already carry their final numbers and their final DDL when v0.1 ships. W2.2
therefore writes the DDL for `0001`-`0004` in one strictly-ordered pass; W4.1 and P8's passes fill
what P2 left empty, and `0005_out.sql` (W9.7) is the one file P2 does not write, appended after the
v0.1 tag under the append-only rule. G27(b) exercises the whole sequence against `MIN_SQLITE` on
every run whether or not the tables have rows.

**`codes.toml` is append-only (G13) and its ranges are reserved up front**, so phases developing in
parallel cannot collide on a number and no code is ever renumbered:

| range | area | reserved by |
|---|---|---|
| `OW-A-nnn` | answer and serve | P6, P7 |
| `OW-D-nnn` | driver resolution — one row per `RejectCode` member | P1, P3 |
| `OW-G-nnn` | graph | P8 |
| `OW-M-nnn` | model and L2 | P2 |
| `OW-Q-nnn` | quality, cassette, eval | P3, P10 |
| `OW-R-nnn` | runtime, budget, cache | P4, P5 |
| `OW-S-nnn` | store | P2 |
| `OW-T-nnn` | OUT targets and constructs | P9 |

**CI jobs turn on in a fixed order**, and a job is never added in warn-only mode — the charter's ban
on a warning that cannot fail applies to CI configuration as much as to eval status:

| CI job | first green in | why not earlier |
|---|---|---|
| `gates` | M0 (G1, G9, G17, G23 only; grows every phase) | the other 23 have nothing to assert against |
| `build` (14 sdists + 14 wheels, one runner, all `py3-none-any`) | P1 | it is W1.7's deliverable |
| `test` (9 cells) | P2 | cross-cell determinism is meaningless before `canonical()` and the DDL exist |
| `golden` (Reductions, Counters, Cassette replay) | P3 | the Cassette codec is W3.7 and the reducers need real documents |
| `conform` (the twelve suites) | P3 | it is W3.6's deliverable |
| `parity` (offline, GPU-free, Node-free container) | P3 | before the first optional heavy dependency lands there is nothing for it to catch |
| `nightly` on the pinned runner `ow-bench-1` | P2 | `store.bytes_per_block` and `rss.gen5000p_peak_bytes` are its first two budgets, and F1 closes off them |
| `toolchains` (node 20, path-filtered) | P9 | the first Toolchain is `omniweave-target-deck` |
| `publish` (OIDC trusted publishing; `release.yml` must not be renamed) | P10 | first tag |

## 4. P1 — Substrate and the CI floor

**Goal.** Everything a driver author or a gate can see, and nothing that touches a document. At P1's
exit a third-party driver distribution can be built, discovered, refused, enabled and explained
without omniweave owning a single document row.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W1.1 | `omniweave-ports` complete: `DriverIO`, `DriverError`, `DriverResult`, `DriverMetrics`, `FailureClass` (13 members), `Isolation`, `LicenceTier`, and the `AcquireV1` / `ParseV1` / `DeriveV1` / `EmbedV1` Protocols | S-core | 3 | ~900 lines of frozen `slots=True` dataclasses and Protocols, spec-complete in the charter, plus ~60 property tests at 8/day |
| W1.2 | `canonical.py` (`canonical()`, `sha256_canonical`, `ow128`), `identity.py`, `ident.py` (`normalize_key`, `normalize_k`) | S-core | 2 | `canonical()` is ~120 lines carrying three distinct encodings for absent / null / `""`; `ident.py` is **`normalize_key` from `vendor/graphify-ids/` and `normalize_k` written here** — `normalize_k` is omniweave's own grounding normaliser with **no graphify original** ([06](06-structure-extraction.md) §1.9 defines its six operations and its back-map; [11](11-repo-layout.md) §1.3 marks the split in the tree) — plus a 20k-string five-script corpus (Turkish dotted I, Greek ypogegrammeni, CJK, Cyrillic, full-width Latin) run against both |
| W1.3 | `errors.py` (the `OwError` tree, `.code()`, `.is_fatal()`, `.fix`), `codes.toml` seeded with its eight reserved ranges, `limits.py` with `MIN_SQLITE = (3, 42, 0)`, the `Diag` type | S-core | 1.5 | one register file plus ~40 codes at the P1 boundary; every row carries a meaning **and the exact command that clears it**, which is the half that takes the time |
| W1.4 | `config.py`: flat scalar coercion, source tracking, the five-level precedence chain, one `OMNIWEAVE_*` twin per key, `ow show-config --digest`, `tools/config_axes.toml` generation with glob arity, gate G18 | S-core | 3 | ~250 lines of coercion plus the generator and the exact-coverage assertion — the assertion that was missing while sixteen shipped config keys matched no pattern at all |
| W1.5 | `discovery.py` (metadata-only), `drivers/card.py`, the `driver_card_cache`, and the tombstone grammar branch taken **before** card validation | S-core | 3 | the card grammar is ~30 tables and keys; the cache's validity key is the measured 1.01 ms `scandir`+`stat` over 328 distributions, against the 2,124 ms `RECORD` scan that is forbidden |
| W1.6 | `probe.py` (capability probes, per-run cache, 24 h persistence keyed on all four of `(driver_id, driver_version, card_sha256, env_digest)`), `toolchain.py`'s manifest reader | S-core | 1.5 | three probe shapes, each a real operation and not an import: a tesseract missing its language pack, a CUDA torch that fails on first kernel launch, an Ollama client with no model pulled |
| W1.7 | The workspace: 14 `pyproject.toml`, `uv.lock`, hatchling, the 1:1 extra alias map, and gates G2, G3, G4, G5, G7, G13, G14 | S-rel + S-sec | 3 | 14 distributions at ~0.1 ew each plus seven gate scripts at 1 engineer-day; G4 reads entry points rather than a hand-maintained list, which is most of its cost |
| W1.8 | `tools/schemagen.py`: `emit \| --check \| --bless`, `schema/*.json`, `schema/expected/`, gate G6 | S-quality | 2 | 13 generated schema files from Python declarations; CRLF normalisation is the only subtlety and it is the one that bites on Windows |
| W1.9 | The semgrep bank and the gate harness: G1, G8, G9, G10, G17, G23, G24 | S-core | 3 | 7 gates at 1 engineer-day plus ~20 semgrep rules; G10's per-OS cold-start baseline recording is half the item |

**Total 22 ew.**

#### Frozen at the end of P1 (week 10)

`CONTRACT = 1`. Every type in `omniweave_ports` — `DriverIO` is declared **not extensible**, so adding
a field amends the charter. `codes.toml`'s numbering, append-only under G13. `canonical()` and both
normalisers, a change to either being a `digest_recipe` bump budgeted at most annually. The config
precedence chain and the `OMNIWEAVE_` prefix. `card_schema = 1`. The fourteen distribution names and
the `tools/layers.toml` rows.

#### The demo

Build the conformance-template driver into a wheel in a clean venv. `ow drivers list` shows it from
`dist-info` alone. `ow doctor` **fails**, naming it as discovered-but-unenabled. Adding it to
`[drivers] enabled` makes it eligible, and `ow drivers explain <id>` prints the resolve trace with
each gate's outcome. Throughout, a `sys.modules` assertion proves no driver module was imported. Then
install the rogue driver whose module body writes a file and raises `SystemExit`, and assert `ow
doctor` exits 0 and the file is absent — G11's fixture, built here and gated in P3.

#### Exit criteria

```bash
uv run tools/check_versions.py                       # G5, CI job 1
uv run tools/gate_weights.py                         # G2: 14 rows + the 250 MB [recommended] aggregate
uv run tools/gate_licences.py                        # G3: resolved graph + import graph + artifacts
uv run tools/gate_layers.py                          # G4: reads entry points, not a hand list
uv run tools/gate_coldstart.py --record-baseline     # G10 baselines for 3 OSes
uv run ow schema emit --check                        # G6
uv run pytest packages/omniweave-ports packages/omniweave-core/tests/unit -q
uv run python -c "import omniweave_core, sys; assert not [m for m in sys.modules if m.startswith('omniweave_core.model')]"
```

#### Non-goals

No store beyond M0's six-table sketch. No `omniweave_core.model`. No parse of any real document
outside M0's fixture. `ow query` is still M0's, not P1's. No MCP, no hooks, no install. No CI matrix
beyond three OSes at 3.11 — the nine-cell `test` job arrives with P2's determinism work.

## 5. P2 — L2 and the store

**Goal.** The pivot exists, is honest, and is provable from bytes. Nothing above L2 is built; several
things above L2 have their tables created and left empty (§3.3).

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W2.1 | `omniweave_core.model`: `Block`, `BlockDraft` (the one mutable type), `Kind`, `Layer`, `Trust`, `Quote` as an ordered `IntEnum` with the weakest tier lowest, `Method`, `OriginSpan`, `TextSpan`, `Quad`, the three coordinate systems with no implicit conversion, `Capabilities` (15 fields), `SERIALIZER_CAPS`, `Degradation`, and the `Doc` / `Grid` lazy handles | S-core | 5 | ~1,400 lines plus ~120 property tests; D2 is spec-complete, so this is transcription plus tests at 8 tests/day. The two tests that are not transcription are `segment.quote_min == min(member quotes)` over a deliberately mixed segment and `Quote.SYNTHETIC < Quote.VERBATIM` |
| W2.2 | The DDL: **91** `CREATE TABLE`, **82** indexes, **7** views, `enum_val` generation with two-way CI parity, the `MAX_TRUST_BY_METHOD` and INV-13 `BEFORE INSERT` triggers generated at migration time, `schema/migrations/0001-0004` (0002 and 0004 created empty per §3.3), and the schema lint (FK-target classification, no second text column, no positional Block reference) | S-core | 9 | 0.5 engineer-day per table including its `CREATE TABLE`, its migration line, its lint row, its `enum_val` rows and one round-trip test ⇒ 45.5 engineer-days. Counts verified by `grep -oh 'CREATE TABLE [a-z_]*' charter.md \| sort -u \| wc -l` |
| W2.3 | `store/sqlite.py`: the only `sqlite3.connect` in the framework, the pragma set, heal-on-open, the store thread and its bounded queue, `Store` (4 methods) + `Reader` (6) + `DocSink` (11) + `GraphSink` (12) = **33**, one transaction per unit, the opaque `Snapshot`, the read-only connection | S-core | 6 | 33 protocol methods at ~0.5 engineer-day each plus the thread-ownership assertions. The T3 distribution boundary is these 33 methods, not "four" |
| W2.4 | `rebind()`: the three-rule matcher, cite carry on rules 1 and 2, `block_history` with `superseded_by`, quarantine below `threshold`, `--allow-unexplained-rebind` as a named override | S-core | 3 | one matcher with two consumers — re-parse identity and P10's golden differ. codegraph priced skipping the equivalent pass at 4.3% of distinct edges wrong, in both directions, silently |
| W2.5 | `archive/`: the `.owdoc` plain-ZIP codec (`ZIP_DEFLATED` `.ndjson` members, no zstd on the read path), `frames.json`, `Frame` at a target of 8,192 blocks, writer **and** reader, and `import(export(store)) == store` | S-core | 4 | the codec is stdlib; the frame index and the seek path are the work. `unzip -l` and `jq` must both work with no external tool installed, which is a test, not a claim |
| W2.6 | `blobs.py` CAS: `put(BinaryIO) -> sha256`, the path layout, refcounting, mark-and-sweep, the headroom file; `part` retention at `retain_parts = "when_citable"` | S-core | 2.5 | retention is load-bearing in five places (INV-10, X8's three re-read branches, Q-G6, SV13, the storage projection), so the tests outweigh the code |
| W2.7 | `owcheck`, `ow doc verify`, `ow store verify \| lock \| diff \| explain \| residue \| export --portable`, `omniweave.index.lock` and its sort-merge git merge driver registered **for that path only** | S-core | 3.5 | ~200 B per document of lock line; the merge driver's one non-obvious property is that **a deleted line stays deleted**, which graphify's `nx.compose` union driver throws away (`graphify/cli.py:2572`, with caps at `:2547-2548` two to three orders below a real corpus) |
| W2.8 | `serialize() -> (str, SpanMap)` over the five core formats, `block_sec` derivation with `sec_path`, `block_fts` as an FTS5 **external-content** table | S-core | 3 | five formats, one `SpanMap` each. There is deliberately no text-only serializer: if you have the text you have the map |
| W2.9 | `ow test crash-matrix`: SIGKILL at **every** statement boundary in `Store.complete()`; G21's three-random-point CI job | S-quality | 2 | ~40 statement boundaries at a scripted kill-and-verify cycle each; DataFlow's eight checkpoint failure modes are the fixture list |

**Total 38 ew.**

#### Frozen at the end of P2 (week 16)

`SCHEMA = 1` and the system-of-record read contract. `digest_recipe = 1`. `container_version` and the
`.owdoc` member layout. `Block`'s field set. The four store protocols — `Store` is never widened, and
neither is any of the other three. The `addr` grammar. The `cite` grammar and `doc.next_cite_n`
minting. `Frame` as a block-count-bounded run.

**This freeze carries a forward-compatibility obligation nothing else in the plan does.** v0.1 ships a
store at `SCHEMA = 1`, and v1.0 ships the same `SCHEMA`. Every L3 and runtime table that P8 and P4
fill is created empty in P2, and P9's artefact tables arrive as one appended file (`0005_out.sql`),
so the v0.1 → v1.0 upgrade is additive DDL plus passes and never a re-parse. If P8 or P9 needs a
column that P2 did not create, that is a `SCHEMA` minor and the upgrade note says so — but a column
that forces a re-parse of an existing corpus is a defect, not a migration, because it re-mints cites.

#### The demo

Ingest `fixtures/gen/gen_5000p_pdf.py`'s output through a stub `parse/1` driver. `ow store verify`
re-derives every `content_digest` and every `content_sha256` from stored bytes and compares. `unzip -p
out.owdoc blocks/000063.ndjson | jq .` works with no external decompressor installed. SIGKILL the
writer mid-commit, reopen, and `ow resume` converges to the uninterrupted result byte for byte in the
`.owdoc` export. Then re-parse the corpus with a one-paragraph edit in each document and watch
`rebind()` carry every cite except the edited paragraphs', which take a fresh `n` from
`doc.next_cite_n` and leave a `block_history` row naming their successor.

#### Exit criteria

```bash
uv run tools/gate_migrations.py --min-sqlite 3.42    # G27(b): numeric order onto an empty file
uv run tools/gate_schema_lint.py                     # INV-1, the FK-target classification
uv run pytest tests/store tests/model tests/archive -q
uv run ow test crash-matrix --statement-boundaries all
uv run tools/gate_crash.py                           # G21
uv run tools/gate_incremental.py --smoke             # G19's harness exists; its fixture lands in P4
uv run ow eval perf --check store.bytes_per_block    # <= 660 B +/- 10% on gen_5000p_pdf
uv run ow eval perf --check rss.gen5000p_peak_bytes  # <= 1,610,612,736 bytes +/- 10%
```

#### Non-goals

No lexical scoring beyond the FTS5 table existing — no `W_HEAD`, no `SPINE_DECAY`, no sanitiser. No
`segment` rows and no L3 rows: the tables exist and are empty. No `Verdict`, no `Answer`. No vector
column. No second store backend. **F1 is open through P2 and closes at its exit** (DP8): every
storage, frame, segment and RSS number in this plan scales off blocks-per-page, and P2 is where the
count is finally taken rather than estimated.

## 6. P3 — Drivers, the host, and parse

**Goal.** A real corpus of office documents and born-digital PDFs in the store, produced by drivers a
third party could have written, and proved honest by a kit that runs on their machine with no corpus
of ours.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W3.1 | `drivers/resolve.py`: the INV-5 gate order, `Requirement` and the capability floors (`>=` on ordered fields, `⊇` on `math`, booleans on `text_span` and `marks`), `RejectCode` mapped one-to-one onto `OW-D-nnn`, `resolution_report`, `ow drivers check \| explain \| verify \| list` | S-core | 4 | eight gates in a fixed order plus ~20 `RejectCode` members, each with a `codes.toml` row and a fix command. A capability floor is a filter and never a ranking key, which is one assertion and a class of bugs |
| W3.2 | `host/wire.py` (framing only, ~80 lines, fuzzed at `header_len <= 1 MiB`, `body_len <= INLINE_MAX`, JSON depth 32), `host/inproc.py`'s `DriverGuard`, `host/subproc.py` (S4: one long-lived worker per `(driver_id, config_digest)`, `worker_idle_ttl_s = 300`, a 0600 unix socket or an owner-only named pipe) | S-runtime | 5 | 80 lines of framing plus an atheris target; the worker lifecycle, the `HELLO`/`INVOKE`/`CANCEL` loop and the process-group reap are the bulk. Never a daemon, never a loopback TCP listener |
| W3.3 | `licence.py`: `compute_tier`, the shipped tombstones as the known-bad weights-licence seed set, `LICENCE_ACK_STALE` against the licence text's hash, and `Grant` with a required `dpa_ref` printed in every covered run manifest | S-sec | 2 | ~15 tombstone cards plus the mutated-licence test. The separate denylist and `weights_licence_md5` are struck, so this is one mechanism rather than two that can disagree |
| W3.4 | `omniweave-office`: `parse.office.anydoc` over `firecrawl-anydoc == 0.2.4`, `py.detach` for the decode, one call per document, the **honest** card (`origin_span = "none"`, `os = {"k": "none"}`), and `vendor/anydoc/` at a recorded SHA with LICENSE + NOTICE + `.sha256` + `FORK-TRIGGER.md` | S-parse | 4 | the decoder is someone else's wheel; the work is mapping anydoc's nine `Block` variants (`_collections/anydoc/src/model/block.rs` — `Heading`, `Paragraph`, `List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`, `Math`, none carrying a source address; only `Asset` carries `origin_part`), the exactly-once grid, and the twelve limit constants |
| W3.5 | `omniweave-pdf`: `parse.pdf.pdfium` — born-digital text runs, glyph geometry, INV-10's `glyphs` branch with a recorded `os_extractor`, `Quad.from_driver` as the sole constructor, the char-stream reading order | S-parse | 6 | pdfium's text API plus the glyph-run re-extraction proof. marker's own annotation records a pdftext char-stream order at 75% against a learned head's 56% (`marker/marker/builders/line.py:77-85`), which is the floor we may not ship below |
| W3.6 | `omniweave-conform`: the **twelve** suites (`card`, `purity`, `contract`, `capability`, `idempotence`, `determinism`, `limits`, `sandbox`, `cost`, `licence`, `fuzz`, and the non-mandatory `quality`), the ~120-test testkit, `ow conform`, the conformance-template driver, and the `Attestation` written by `ow conform` | S-quality | 7 | 12 suites at 3 engineer-days plus 120 property tests at 8/day. `capability` alone must prove `origin_span` on all three INV-10 branches, which is why the mandatory tier is eleven suites and still has to run in five minutes on a laptop |
| W3.7 | The Cassette codec, recorded at `DriverIO.service()` and `omniweave_core.modelserver` — the only two outbound model channels a driver has — plus `--cassette off\|allow\|required` and `OW-Q-004` on a miss | S-quality | 2 | two interception points, so coverage is complete by construction. That is why this is 2 ew and not 8: an interception layer that had to find call sites would be the larger number |
| W3.8 | `acquire.fs`, the `unit` roster writer, `canonical_uri()`, the stat index, `--scope` | S-runtime | 2 | ~22 MB of roster per 100k documents; the realpath / normcase / `\\?\`-stripping normalisation is the whole correctness surface and the reason `canonical_uri()` is one function |

**Total 32 ew.**

#### Frozen at the end of P3 (week 22)

The five Port protocols at major 1. `DriverIO`'s field set. The `omniweave-driver/1` framing. The
`driver.toml` grammar, including which unknown keys are hard errors (any top-level table) and which
are ignored with a recorded degradation (a key inside `[capability.<port>]`, because every such key is
an ordered or set-valued floor and an unrecognised one can only make a driver look less capable).
The twelve suite names and the `[quality.suites]` sub-table. `Isolation`'s members. `FailureClass`'s
thirteen members.

#### The demo

`ow conform packages/omniweave-pdf` writes the card's `[quality]` block with its four kit-written keys
(`n`, `ci95`, `witness`, `measured_on`) and a complete ten-field `MeasuredOn`; author-supplied values
in that block are rejected. Then take the same driver, change its card to declare `origin_span =
"exact"`, and watch the `capability` suite fail on the first fixture by re-reading the retained part.
That failure is the entire argument for the design: a third party's honesty is machine-checkable, on
their machine.

#### Exit criteria

```bash
uv run tools/gate_discovery_no_import.py             # G11, with the rogue driver installed
uv run tools/gate_vendor.py                          # G12: sha + parity test + arch assert + NOTICE
uv run tools/gate_egress.py                          # G15: hostname grep + a socket-blocked run
uv run tools/gate_contract.py --releases 2           # G16 (vacuous at P3; wired for later)
uv run ow conform packages/omniweave-office --suites mandatory
uv run ow conform packages/omniweave-pdf    --suites mandatory
uv run ow eval golden --check span_exact_rate        # Q-G6, hard, at 1.000
uv run pytest tests/host tests/drivers fuzz/ -q
```

#### Non-goals

No OCR, no VLM, no `omniweave-vision`. The `REPAIR` and `PAGE` rungs do not exist; a scanned PDF is
`FailureClass.needs_ocr` with a `Diag` and a coverage gap, disclosed by the corpus card. No escalation
of any kind — one rung, selected by format. `layout.class_hist` is absent (F4), and every decision
that would have read it records `cause = "layout_unavailable"`, so the cost of that veto is a number
rather than a rumour. `verbatim` is unreachable on the office path and `corpus_card.verbatim_fraction`
says so before any query runs.

## 7. P4 — The execution runtime

**Goal.** Durable, resumable, budgeted, cached, incrementally correct execution — with `op.converge`
shipped, which is the precondition for ever building a watcher.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W4.1 | `work.py`: the two-table plan (`unit` roster → `work`), `WorkRow`, the claim / complete / reap SQL, the failure ladder, `classify()`, and the nullable-together routing columns with their three CHECKs | S-runtime | 5 | one state machine of ~14 transitions, each with a crash test. The `op.*` NULL-triple is the subtlety a fabricated `route_decision` row would have hidden |
| W4.2 | `run/supervisor.py`: one asyncio loop (claim → admit → dispatch → complete → reap), `Admission`'s four semaphore families, `producer_should_pause()` water-mark hysteresis, the CPU render semaphore held separately from the Service semaphore, and `TaskGroup` for structured shutdown only | S-runtime | 6 | olmocr's `pipeline.py:87-88` split — two `asyncio.BoundedSemaphore`s with CPU render via `asyncio.to_thread` at `:112` — is adopted verbatim. At 10.7 MB per rendered 192-DPI page a shared semaphore renders faster than it evicts |
| W4.3 | `run/discover.py`'s streaming roster and connector cursors; `run/expand.py` and `op.identify` materialising part rows under the water mark | S-runtime | 2.5 | a document's part count is not knowable without opening it, so this is an operator with a work row, not a scan |
| W4.4 | `cache.py`: five layers under one `cache_index`, the single `cache_key()` in `omniweave_core.cache`, `semantic_digest`, the six-clause read policy, `put(entries, allowed_units=…)`, one GC, `ow cache stat \| prune` | S-runtime | 5 | six read clauses with a fixture each, plus the growth bound `ow cache stat` must print **in these words**: live units × configurations seen |
| W4.5 | `budget.py`: `budget_reservation` as durable rows, headroom computed in SQL, `admit()` returning `admitted \| deferred \| degraded`, `DEFERRED_BUDGET` as an `Outcome`, `PriceBook`, `Spend.micros(book)` | S-runtime | 4 | per-dimension budgets with first-exhausted-wins. The measured anti-pattern is the test: 8,000 tokens × 8 retries = 64,000 output tokens for one page, fired in parallel |
| W4.6 | `deps.py` and `run/converge.py`: the `dep` reverse index over six closed kinds, the three population paths (runner-known, driver-declared `witness_set`, cohort merkle), `anchor_delta`, the per-unit attribution guard | S-runtime | 6 | *observing* a driver's reads cannot be built — INV-6 gives it no store handle — so this is three declaration paths plus one reverse-index query, not an instrumentation layer. It is also the item the watcher's absence in v1 buys us the right to get wrong once |
| W4.7 | `run/dispatch.py`: `dispatch_key` Batch formation, AIMD adaptation that never halves-and-never-recovers, crash quarantine, and `Sequence` sessions with per-token apportionment | S-runtime | 4 | a Batch is invisible to the work table, the spend ledger, the trace and the failure taxonomy, and visible only as `call`-span attributes — which is exactly what keeps this item small |
| W4.8 | `events.py`, `tools/events.toml` (closed, append-only, byte-diff gated), `schema/event-v1.json` generated from it, the five-deep closed span hierarchy `run > plan > unit > attempt > call`, `manifest.py` and the two cost self-checks | S-runtime | 3 | ~45 event kinds sharing one envelope; the generator is what makes G20 possible at all |
| W4.9 | `modelserver.py` (S3 attach-or-spawn with model-id verification and a 32-byte token in a 0600 sentinel), `locks.py` (`O_CREAT\|O_EXCL` + flock + host/pid/create_time), `clock.py` (injected, never ambient) | S-runtime | 3 | three seams at ~250 lines each, each with a stale-lock test and a wrong-model test |
| W4.10 | The `fixtures/incremental/` 300-document / 40-mutation corpus and G19 (diffing `.owdoc` **exports**), G21, G22's nightly 100k-roster run, and `ow bench scheduler \| inproc \| service \| rss` | S-quality | 3.5 | 40 scripted mutations at ~0.4 engineer-day each including the expected-delta assertion; see R-Q4, which is the reason this number carries a stated confidence |

**Total 42 ew.**

#### Frozen at the end of P4 (week 33)

`Producer`, which **is** `OperatorIdentity`, with `op_version` an integer at every site — the
`producer` column, the `Producer` field, `work` and `work_done` — so `producer_identity` and
`work_identity` cannot disagree about the same operator through a text round-trip. The `cache_key()`
input recipes and `CacheLayer`'s five members. `Spend`'s dimensions. `DepKind`'s six members.
`tools/events.toml`, append-only, with a `kind` never reused. The `work` state machine. The five-deep
span hierarchy. The `dispatch_key` formula.

#### The demo

The sentence D6 exists for, made executable. Ingest a 500-document corpus containing 2,000 pages that
escalate to a billed page driver; record the spend; delete the `.owstore`; ingest the identical corpus
into a fresh store; and show `ow cost --by driver` reporting **0 micros** with `rebilled_units == 0`
while wall time falls to CPU-seconds. Then `kill -9` the supervisor three times at random points
during a 100k-roster run and show `ow resume` converging to store equality with an uninterrupted run.

#### Exit criteria

```bash
uv run tools/gate_config_axes.py                     # G18: exact key coverage, one pattern per key
uv run tools/gate_incremental.py                     # G19: 300 docs, 40 mutations, .owdoc exports
uv run tools/gate_events.py                          # G20
uv run tools/gate_crash.py                           # G21
uv run tools/gate_scale.py --roster 100000           # G22: RSS <= 600 MB, >= 2000 transitions/s
uv run ow bench scheduler --units 1000000 --report p50,p95,p99
uv run ow eval counters --check rebilled_units       # exact: +/-1 fails
uv run semgrep --config tools/semgrep/omniweave.yaml --error   # skeleton-marker-survived finds 0
```

#### Non-goals

**No watcher.** `ow watch` does not exist, and `op.converge` shipped here precisely so that a watcher
can later be added without breaking incremental correctness silently. No connector beyond
`acquire.fs`. No `wasm` DriverHost (F25: one reason is a special case, two is a mechanism). No
multi-tenancy — F27 makes v1 store-per-tenant, and no plan document may assume row-level tenancy. No
sub-page commit boundary (F29): the shipped answer is `MAX_BLOCKS_PER_DOC` plus a `RESOURCE_LIMIT`
refusal naming the knob, and the 4M-cell page — under both that cap and `MAX_GRID_SLOTS` — is
**admitted** at §18's printed cost rather than refused.

## 8. P5 — The router

**Goal.** Evidence-driven, per-part, monotone escalation whose decisions are pure, recorded and
replayable, and whose budget never changes which rung is chosen.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W5.1 | `route/evidence.py`: `Evidence` as a flat namespaced scalar record, `read()` as the only accessor and it appends to a read log, the `SignalSpec` registry, and the model-free signal set — `decode.cid_ratio`, `decode.replacement_ratio`, `geometry.overlap_line_frac`, `decode.has_text_span` | S-parse | 4 | four free signals at ~0.5 ew each plus the registry. There is no `__getitem__` and no public mapping, which is what lets a third party add a key core has never heard of |
| W5.2 | `route/eval.py`: the pure `evaluate()`, the policy grammar (first-match `[[rule]]` blocks, closed comparison clauses, `@thresholds` substitution, a required `on_unknown`), the loader, the interval-box subsumption linter, the isotonic threshold fitter | S-parse | 6 | ~700 lines. The semgrep bans on clock, RNG, env and IO inside `eval.py` are what make it testable at 200 derandomized hypothesis examples, and the linter's incompleteness over open string domains is F30's subject |
| W5.3 | `route/admit.py` and the `budget.exhausted` write-back — the only channel by which budget reaches a routing decision (INV-14) | S-parse | 2 | one impure function over W4.5's ledger, plus the property test that `evaluate()` never sees it |
| W5.4 | `route/rung.py`, the open `Lane` registry (five parse lanes at v1), the generated `BEFORE INSERT` trigger enforcing `child.rung > parent.rung`, with CI parity against the compiler's backward-`escalate_to` rejection, and the three exact counters | S-parse | 2.5 | SQLite prohibits a subquery in a `CHECK`, so the constraint must be a trigger — and two enforcers need one truth, which is the parity test |
| W5.5 | `route_decision`, `route_signal`, `route_spend`, `route_scoreboard`, and `ow route lint \| explain \| propose \| promote` | S-parse | 4 | `ow route lint` resolves every key in `[slice] by`, in every `when` clause and in `[thresholds]` against the `SignalSpec` registry, and refuses a channel-budget sum `>= query_ms` |
| W5.6 | `omniweave-vision`: `parse.page.olmocr` at the `PAGE` rung, 192-DPI raster, `binarize = false` always, weights pinned by exact revision | S-parse | 4 | the weights and the page-query prompt are taken; the client, the pre-filter and the harness are ours (§16). Ollama-OCR's 72-DPI-then-Otsu destroys the antialiasing a VLM was trained on, which is why `binarize` is not a knob |
| W5.7 | `agree.decode_vs_page` as the free quality channel, `TruthKind = "agreement"` plumbing, and the rule that it may **never** populate an accuracy column | S-quality | 1.5 | normalised edit distance over two readings already paid for. The cost is zero and it lands exactly on the population where the cheap driver is suspect |

**Total 24 ew.**

#### Frozen at the end of P5 (week 38)

The policy grammar — `surface = "route"` and `surface = "retrieval"` share it verbatim, with D4's
loader, subsumption linter and isotonic fitter reused unchanged. `Rung`'s ordering and the escalation
invariant `child.rung > parent.rung`, under which `DEGRADE` is a **forward** move even though it runs
a cheaper driver. The `SignalSpec` registry's key namespace. `route_decision`'s columns. `CostClass`'s
three members and their ordering as the single deterministic-first key.

#### The demo

A 40-document folder: born-digital PDFs, one scanned fax, one PDF with a broken CID map, one encrypted
file. `ow route explain d12/p3` prints the evidence read log, the rule that matched, the chosen
`Rung`, the estimate, the admission outcome and the actual spend. On a clean born-digital page the
three counters read `page_renders == 0`, `service_attaches == 0`, `signal_computations == 0` — and
they are **exact** counters, so ±1 fails. That is INV-13 as a number rather than a promise.

#### Exit criteria

```bash
uv run ow route lint --strict --estimates
uv run pytest tests/route -q --hypothesis-profile=ci    # derandomize=True @ 200
uv run tools/gate_pure_eval.py                          # semgrep: no clock/RNG/env/IO in eval.py
uv run ow eval counters --check page_renders,service_attaches,signal_computations
uv run ow eval run --suite parse --corpus fixtures/route/mixed-40 --cassette required
uv run tools/gate_trigger_parity.py                     # SQL trigger vs compiler rejection
```

#### Non-goals

No learned router. There are no labels on day one, and the label you would need — which driver *would
have been* right — does not exist. No `REPAIR` rung beyond the two model-free signals, because F4 has
no licence-clean pinnable layout model to build one on. No hosted escalation: `bytes_egress` defaults
to 0, so the first hosted call requires a site-layer `Grant` carrying a `dpa_ref`.

## 9. P6 — Retrieval, the Answer and the Verdict

**Goal.** Five honest channels, a fusion whose confidence is a real ratio to a real ceiling, and a
zero that is called `absent` only after all fifteen gates pass. P6 starts at week 19 on P2's frozen
store protocols, so it runs concurrently with P4 and ahead of P5.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W6.1 | `retrieve/plan.py`: pure, memoised on `(mode, channel set, filter-field set, policy_digest, caps_digest)`, cheapest-first inside **one** `Snapshot`, and the two-deadline split — a channel over its own `budget_ms` is `UNAVAILABLE(timeout)` and forces `degraded`; a channel pre-empted by the query deadline reports `OK` with `truncated_at_limit` while the rest report `OFF(query_deadline)` | S-retrieve | 3 | the split **is** the verdict. Without it a plan that merely used its budgets makes every query `degraded`, which turns the honesty machinery into permanent noise |
| W6.2 | The five channels: `identity` (the five-tier ladder including the 40 tier), `exact`, `lexical` (`lex(b) = W_BODY × bm25n(block_fts, b) + W_HEAD × max over spine(b) of bm25n(head_fts) × SPINE_DECAY**depth`, the sanitiser as a semantic transform, the eight-field DSL, `MAX_QUERY_TERMS = 64`, 5× over-fetch before re-rank), `structural` (`Expand`: hard cap 4 hops, per-hop beam, visited cap, explicit relation allowlist, a `hub_cap` that truncates and says so), `semantic` (`vector.brute` plus the 250k refusal, off by default) | S-retrieve | 10 | five channels at 1-3 ew each. Lexical is the largest because the sanitiser lifts reference-shaped tokens — `§4.2(b)`, `Fig. 3a`, `GL-4471`, `d7#412` — out to `Query.refs` before the residue reaches FTS5, and an unknown `foo:bar` prefix must pass through as plain text so `TODO:` still returns results |
| W6.3 | `fuse()` (weighted RRF at one key, `block_id`, with **1-based** ranks), `ceiling()`, the shared `_weight()`, `FusedHit` carrying per-channel contributions and ranks, and the two-half property test | S-retrieve | 2.5 | ~200 lines. Half (a) alone is false on the shipped default — `vectors = "off"` makes `semantic` EMPTY and an empty `exact` channel is routine — which is why the test is stated in two halves and nobody may simplify `ceiling()` to match `fuse()` |
| W6.4 | `PREFILTER_MAX = 200_000` narrowing into `tmp_narrow`, the over-fetch factor `clamp(1/selectivity, 1, 64)` above it, the `filter_starved` gate, and `Filters` with `deny_restriction_bits` set by policy and never by the caller | S-retrieve | 3 | an exact candidate set or a proof it is too big. No histogram, no independence assumption, no cost-based optimiser |
| W6.5 | `build_verdict()`: the **fifteen** absence gates in precedence order, one fixture per gate, exactly one `return VerdictState.ABSENT` site, `citable_as_absence()`, and `DegradeCause` carrying the `diag` codes and the exact clearing command | S-retrieve | 5 | 15 gates at 0.3 ew each including a fixture. The semgrep assertion that there is exactly one `ABSENT` site is what stops a sixteenth hazard from becoming a second citability rule |
| W6.6 | `answer/`: `worth`, `allocate` (the monotone tier table), `render` (the fixed `**ow:<name>**` section order, never an ATX heading), `dedup` (the emission ledger keyed `(corpus_id, doc_key, gen, cite, content_digest)`, disabled when the host supplies no session id), `untrusted` (`<ow:untrusted>`), and the truncator that cuts whole sections and whole blocks with post-truncation counts substituted through a sentinel | S-retrieve | 6 | ≤ 24,000 chars, one content block, no `outputSchema`. The monotonicity property test — a larger tier may never receive a smaller chars-per-doc — plus one fixture per section |
| W6.7 | `Calibrated`, `CalStatus`, and the render rule: `status != "calibrated"` prints an ordinal name plus `(uncalibrated)` and never a numeral, percentage, bar, colour or grade, while remaining usable as an internal filter and sort key | S-quality | 1.5 | one wrapper type plus a renderer test fed each status. The renderer consumes the **status**, never the float |
| W6.8 | `corpus_card` generation (non-LLM), coverage gaps joined against `diag_code`, the achieved capability **floor**, the trust and quote histograms, `verbatim_fraction`, embedding metadata | S-retrieve | 3 | one row per `card_gen`. The coverage-gap join is absence gate `parse_gap_in_scope`'s only input, which is FE3 made concrete |

**Total 34 ew.**

#### Frozen at the end of P6 (week 33)

`Query`, `Filters`, `ChannelResult`, `ChannelStatus`, `FusedHit`, `Verdict` and its states, the Answer
section names and their order, the fifteen gates and their precedence, `SCORER_VERSION = 1`, and the
identity ladder's tiers — including the 40 tier, which is the first thing a well-meaning
simplification deletes: collapsing 40 into 50 lets a punctuation-different match tie a literal one and
fall through to BM25, measured as a fixture outranking the symbol it tests by 0.355 of ~58. **No field in any of these types defaults to `...`**: a default is a real value or the field
is required, and there is no third option.

#### The demo

The compliance query that has no answer. On a corpus where the fact is genuinely absent, `ow query`
returns `absent` with all fifteen gates listed as passed and their evidence printed. Then corrupt
`block_fts` with a fault-injection fixture and re-run the identical query: the answer is `degraded`
with the channel named `unavailable` and a reason — never `absent`. That pair, not either half of it,
is the product.

#### Exit criteria

```bash
uv run pytest tests/retrieve tests/answer -q --hypothesis-profile=ci
uv run ow eval run --suite retrieve --corpus fixtures/store/golden-queries.jsonl
uv run ow eval run --suite absence --deterministic-half
uv run ow eval gates --check false_confident_zero,degradation_detection,citability_violations
uv run ow eval perf --check query.warm_p50_ms        # <= 180 ms, under G10's 250 ms ceiling
uv run tools/gate_one_absent_site.py                 # semgrep: exactly one ABSENT return
uv run tools/gate_no_ellipsis_default.py             # no `= ...` in a shipped shape
```

#### Non-goals

`vectors = "off"` is the shipped default and stays so through v1: no ANN Backend (F10, DP3), so most
first runs get four channels and a `Verdict` that says `semantic: off`. No reranker model. No
cross-corpus fusion inside one `Query` — one `retrieve()` reads one `Reader`, a `Reader` is one store
and a store is one corpus, so a surface asked to span corpora issues N calls and rank-merges them,
disclosing `fusion_kind = "rank_merge"`. No `community_report` channel, because there is no L3 yet,
and the structural channel traverses `block_link` only.

## 10. P7 — The agent-facing surface, and v0.1

**Goal.** One registry, seven generated surfaces, four listed tools, and an install that reverses
byte-identically. At P7's exit, v0.1 ships.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W7.1 | `surface/registry.py`: `ActionSpec` (name, `mcp_name`, `listed_in`, the read-only / idempotent / open-world bits, cost class, a ≤160-char summary, a ≤90-char `decision` clause, a validated example, input and output types, the advanced-arg set, the CLI verb tuple), the full Action set, `HUMAN_ONLY`, the `listed ⊆ enabled` startup invariant, and `compact_schemas` with `_DECLARED_ARG_KEYS` snapshotted **before** the strip | S-retrieve | 4 | ~45 Actions at ~0.08 ew each. `mcp_name = None` is structural, so `uninstall`, `corpus.rm`, `route.promote`, `skills.remove` and `targets.remove` are unreachable from any agent surface by construction rather than by policy |
| W7.2 | `gen/`: `ow surface emit` producing the argparse tree, the SDK sync and async twins, the MCP tool schemas, the `instructions` string, `llms.txt`, `AGENTS.md` and the router skill's action table — seven artefacts, all byte-diff gated (G25) — plus the no-two-groups-differ-only-by-a-trailing-`s` check | S-retrieve | 5 | seven generators at ~0.6 ew each. The CLI generator is the largest because a verb is an imperative, a group is created only at three or more verbs, and there are no aliases |
| W7.3 | `omniweave-serve`: MCP over stdio and HTTP, `ow_query`, `ow_open`, `ow_corpora`, `ow_add`, the frozen 1,900-token `tools/list` baseline with a 5% drift gate, and `structuredContent` on the two row-shaped tools only | S-retrieve | 5 | jcodemunch's receipt settles the magnitude — 22,741 tokens per turn for 91 tools against 939 for three — so the four-tool listing rule is the design and the token budget is the test. `omniweave-serve` may never import `omniweave` and never runs the Supervisor |
| W7.4 | `hooks/`: `ow hook <event>`, the `UserPromptSubmit` front-load tiered by **verified** confidence (high / medium / silent), the 8,000-char cap, counter **names** only and never prompt text, and the `PreCompact` marker that invalidates the emission ledger | S-retrieve | 3 | G26 is p95 ≤ 250 ms warm and 1 s cold, and a silent exit-0 deadline breach turns the adoption lever off with no symptom — so half of this item is the instrumentation that makes the breach visible |
| W7.5 | `install/`: `ow install \| uninstall \| --check`, one `AgentTarget` per host (`detect`, `install`, `uninstall`, `print_config` which must not touch the filesystem, `describe_paths`), the install receipt recording every written path with its post-write sha256, and the byte-identity reversal gate | S-rel | 4 | three hosts at v1 at ~0.8 ew each plus the receipt and the reversal test. A new host is one file and one registry row, which is the claim this item has to make true |
| W7.6 | Skills: `omniweave/SKILL.md` and `references/actions.md`, both generated; `ow skills install \| remove`; the NOTICE discipline | S-retrieve | 2 | generated from the registry, so the work is packaging and the install path, not prose |
| W7.7 | `bench/serve/`: the 30-task scripted-agent harness, `source_reread_rate` **paired with** task accuracy, F19's mis-pick counters, and `first_answer_seconds` | S-quality | 3 | 30 tasks at ~0.08 ew each plus the harness. This is the instrument for [00-vision.md](00-vision.md) §10's stop condition, so it must exist **before** v0.1 ships, not after — and it must report the pair, because a run in which `source_reread_rate` falls and task accuracy falls with it is a failing run |

**Total 26 ew.**

#### Frozen at the end of P7 (week 42)

The four listed tool names. The Answer section names and order — again, and now publicly.
`ActionSpec`'s fields. The install receipt format. **The four `cite` sigils**: `d<doc_ord>#<n>` for a
Block and `e`, `c`, `k` for an Entity, a Community and a Claim. F14 must close before this freeze
(DP1), because a sigil in a shipped answer is forever.

#### The demo

`first_answer_seconds`, scripted end to end: a clean 4-core machine with no GPU, offline after
install, over a folder of 100 born-digital office documents — `ow install` → `ow add ~/docs` → `ow
query "<question>"` returns an Answer with at least one `cite` that `ow open` resolves, paged unless its page kind is `stream` (ADR-13 D13.1), in under 600 s. Then
`ow uninstall` and a byte-identity diff of every path the receipt names.

#### Exit criteria

```bash
uv run ow surface emit --check                       # G25: six file artefacts byte-identical
uv run tools/gate_hook_latency.py                    # G26: p95 <= 250 ms warm / 1 s cold
uv run pytest packages/omniweave/tests/unit/test_gate_install.py   # G-install: byte-identity reversal (ADR-13 D13.4)
uv run pytest bench/serve -q --tasks all
uv run pytest packages/omniweave/tests/unit/test_gen_budget.py     # SV2
uv run pytest packages/omniweave/tests/unit/test_surface_registry.py packages/omniweave/tests/unit/test_surface_startup.py -k sv1   # SV1
uv run tools/acceptance_v01.py                       # V01-1 .. V01-17 from 00-vision.md 9.1
```

**v0.1 ships at week 42, at 224 cumulative engineer-weeks.** Its acceptance set is
[00-vision.md](00-vision.md) §9.1's seventeen criteria, verbatim; this document adds nothing to it and
subtracts nothing from it.

#### Non-goals

**The OUT direction is never on MCP** — skills plus CLI only, at v1 and after. No generic `ow_do`
dispatcher: an untyped `action: string` collapses the host's only authority control, which is granted
per tool name. No watcher. No hosted egress. No calibrated digit anywhere.

## 11. P8 — L3, the knowledge graph

**Goal.** Deterministic-first structure — Segments, anchors, cross-references, entities, communities
and claims — with every free pass preempting every paid one and a coverage ledger that proves it
rather than asserting it.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W8.1 | `derive.segment.spine` plus `segment` / `segment_block`: heading-scoped, table-atomic, zero-overlap, block-aligned, at `SEGMENT_TARGET_TOKENS = 1200` under `MAX_SEGMENT_TOKENS = 2048` and `MAX_SEGMENT_BLOCKS = 512`; `segment_recipe = 1` | S-graph | 4 | one segmenter in the framework, and a Block belongs to exactly one Segment so overlap is unrepresentable. `graphrag-chunking` is rejected as a dependency: 388 lines, `sentence_chunker.py:9` imports nltk with nltk absent from `pyproject.toml:32-35`, and `bootstrap_nltk.py` fires eight `nltk.download()` calls from `SentenceChunker.__init__` — failing G15 and `needs_network = false` at once |
| W8.2 | `anchor`, `ref_site`, `ref_unresolved`, the fourteen-member `AnchorKind`, and the free anchor passes — `derive.anchor.defterm` first | S-graph | 6 | 14 anchor kinds, each with a detector and a fixture. `defterm` is first because it mints `abbrev` and `expansion` aliases, and "IBM" against "International Business Machines" scores far below Jaro-Winkler 92, so the fuzzy funnel **provably** cannot catch that class |
| W8.3 | `block_link`, the cross-reference resolvers, `bound_by`, and unbind-on-`anchor_delta`-removal | S-graph | 4 | the block→block table is a different table from `edge` with different consumers. Only a row carrying `bound_by` may be unbound, which is "never delete what we cannot restore" made mechanical |
| W8.4 | `GraphSink` (12 host-side methods): `Draft` and per-invocation `tmp` id resolution over `owgraph-items/1`, the `MAX_TRUST_BY_METHOD` clamp writing `OW_GRAPH_TRUST_CLAMPED` with the driver's **original claim**, `Taint` ORing upward and never across edges, `restriction_bits` stamping | S-graph | 5 | 12 methods at ~0.4 ew. The sink has no `drop()` — quarantine is the only disposal path — which is what makes a dangling `tmp` a hard gate rather than graphrag's `filter_orphan_relationships` delete |
| W8.5 | `derive_pass` as a **data** registry, `(cost_rank, phase)` coverage ordering, `derive_cover` bitmaps (≤ 64 B at 512 blocks), `cover_empty` with a mandatory reason, `derive_run` per `(Segment, pass)` | S-graph | 5 | 15 shipped passes, each a registry row plus a coverage assertion. `cost_rank` primary with `phase` ordering only *within* a rank is the whole of "deterministic before LLM", and it is what keeps a third party's free extractor able to preempt every paid one with no core change |
| W8.6 | `entity`, `entity_alias`, `entity_band` (persisted MinHash), `entity_merge` (append-only, `polarity ∈ {+1,-1}`), `op.lexicon`, `op.resolve` — the funnel: exact key → type gate → entropy ≥ 2.5 bits/char → MinHash/LSH → Jaro-Winkler ≥ 92.0 → community boost +5.0 → the nine negative guards re-applied → union-find with a deterministic survivor → a cohesion re-check — and the path-compressed `canonical_id` | S-graph | 8 | graphify's measured constants (`dedup.py:244-248`) plus **three guards that are ours**: `scoped_label_crossdoc` (two `scope='document'` entities in different documents never merge — the single most common false merge in a document corpus), `cooccurrence_in_segment`, `cross_trust_class`. 128-perm signatures over 1.5M entities is ~1.3 GB of RAM, which is why the bands are a table and never an in-memory index |
| W8.7 | `op.cluster`: pure-Python Louvain over an `array('i')` CSR from one SQL scan, per connected component, a direction-normalised duplicate-dropped sorted edge list under a fixed seed, `MAX_COMMUNITY_SIZE = 512`, and a refusal above `MAX_CLUSTER_EDGES` naming `omniweave-driver-leiden` | S-graph | 4 | graphrag's determinism triple (`cluster_graph.py:57-97`) adopted whole. `use_lcc` is rejected permanently: `defaults.py:72`'s `use_lcc=True` silently discards everything outside the largest component, and a folder of unrelated PDFs is this framework's premise |
| W8.8 | `claim`, `community`, `community_member`, `community_report`, `community_report_fresh`, the grounding gate (`OW_GRAPH_UNGROUNDED`), and `omniweave-llm`'s four billed `derive/1` drivers reaching a model through `io.service()` | S-graph | 6 | the fourteenth distribution is ports-only and 2 MB because putting those four drivers in `omniweave-vision` would force a tensor library on anyone who wants LLM extraction. `MAX_COMMUNITY_SIZE = 512` instead of graphrag's 10 is the largest single line item in the config file: 10 over 3M entities is ~300k leaves, hence ≥ 400k report calls |
| W8.9 | The structural channel's L3 half, `locate()` over edge → `edge_evidence` → mention → block → `quad` / page / `os_*`, `quarantine`, `graph_history`, and `ow graph doctor \| plan \| types \| split \| residue` | S-graph | 4 | no synthesized box, ever (INV-9): `precision ∈ {line, block}` and the query says which. Sub-block precision is a query, never a stored column |

**Total 46 ew.**

#### Frozen at the end of P8 (week 52)

`GraphSink`'s twelve methods. `owgraph-items/1`. `segment_recipe = 1`. `etype_vocab`'s seeding rules
and its `source ∈ {builtin, proposed, user}`. `alias_kind` and `akind` as **disjoint** vocabularies in
separate `enum_val` domains. The nine negative guards and the funnel's order. `MAX_COMMUNITY_SIZE` and
`MAX_SEGMENT_BLOCKS`.

#### The demo

A 137-document data room, run twice. First with `[graph.passes] enable` restricted to the free
passes: `coverage_frac` printed per document class, the bill **0 micros**, and an entity-mediated
query still answering with `locate()` returning a page and a polygon for every mention. Then with the
billed passes enabled: the same query, the delta in coverage, and the delta in micros, side by side.
That comparison is F13's instrument and the only evidence the economics argument will ever have.

#### Exit criteria

```bash
uv run pytest tests/graph -q --hypothesis-profile=ci
uv run tools/gate_graph_schema.py                    # no quad/bbox/poly column in any L3 table
uv run tools/gate_incremental_graph.py               # the graph-specific 60-document / 20-step run
uv run tools/gate_incremental.py                     # G19 still green with L3 rows present
uv run ow graph doctor --check dangling_tmp,trust_clamped,ungrounded
uv run pytest tests/graph/test_resolve_order.py -q   # shuffled candidate order, identical closure
uv run ow eval run --suite extract --cassette required
```

D707 maps each line to what runs it at the end of the graph verbs (the tree has no `tests/` root, D19's shape):

1. `tests/graph` is `packages/omniweave/tests/unit/test_graph_*.py` with the core store's graph tests. `--hypothesis-profile=ci` ran Hypothesis's own `ci` profile at 100 examples until `packages/conftest.py` re-registered it at 633's 200 (D707); every Hypothesis test passes under it.
2. `tools/gate_graph_schema.py` is GR1, a clause of `tools/gate_schema_lint.py` since D612, which passes.
3. `tools/gate_incremental_graph.py` is GR8 and passes; 4. `tools/gate_incremental.py` is G19 and passes.
5. `ow graph doctor --check dangling_tmp,trust_clamped,ungrounded` exits 0, vacuously until W8.8: all three are billed signals, and no billed pass has run.
6. `tests/graph/test_resolve_order.py` is GR6's shuffle test in `test_graph_resolve.py`.
7. `ow eval run --suite extract` is W10.6's, a P10 instrument (D25's ruling).

#### Non-goals

No Leiden in tree: `omniweave-driver-leiden` is out of tree and conditional on F40, because naming an
escape that does not exist is worse than naming none. No `derive.code.treesitter` — out of tree, in
`omniweave-driver-code`, since a pass in the shipped ladder whose distribution does not exist is a
promise nothing keeps. The `[75, 92)` LLM merge band ships with `derive.merge.llm` **disabled by
default** pending F39, whose pre-committed answer is to delete it. No entity summarisation beyond the
derived `description`; graphrag's description-as-a-list re-summarised on every merge is rejected.

## 12. P9 — OUT, the compilers

**Goal.** Three Targets at `GateStatus == passed`, a retained IL that makes editing a `passthrough`
operation, and a receipt that closes the loop back into L2.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W9.1 | `omniweave_core.out` — the framework every Target gets free and no Target may reimplement: `CompileV1`, `finding.py` (orthogonal `Severity` and `Provenance`, `FindingSet.fold()` on `(code, rule, unit, canonical)`), `constructs.py`, `rules.py`, `carrier/xml.py` + `carrier/html.py` (**two** parse functions one line apart — error-recovering for READ, strict for anything that WRITES; DOCTYPE banned), `report.py` with `il_digest()` and `nsig()`, `gate.py` (ten statuses), `plan.py` (seven `UnitOutcome`s), `brief.py`, `ledger.py`, `marker.py` (the `OWC1` grammar), `manual.py`, `receipt.py`, `roundtrip.py` (r1..r7 as executable predicates), `opc.py` (the only ZIP-for-write in the framework), `job.py` | S-out | 14 | 17 modules at ~0.8 ew each. ppt-master conflates severity and provenance in one 9,368-line class (`svg_quality/checker.py`, verified by `wc -l`), so the orthogonality plus `fold()` is the highest-leverage piece here and gets a fixture per severity × provenance cell |
| W9.2 | `omniweave-target-pptx`: `constructs.toml` (~180 rows), `rules/` at one rule per file with one test per file, `measure.py` (uharfbuzz shaping, imported by **both** `rules/` and `lower/` — that shared import is the whole point), `lower/{drawingml, charts, boolean, media, pack}` | S-out | 16 | ppt-master's `svg_to_pptx` subtree is **53,666** Python lines (`find ppt-master -path '*svg_to_pptx*' -name '*.py' \| xargs wc -l`). We reimplement it as ~180 declared constructs plus a rule per file, which makes the surface enumerable rather than open |
| W9.3 | `parse.pptx.native` (`read_back`): python-pptx → `owdoc-fragment/1`, `Method.ROUNDTRIP`, and the `artifact_el` map from IL element address to produced Block | S-out | 5 | ppt-master's `pptx_to_svg` subtree is **20,917** lines because it reconstructs SVG. We need a fragment, not a render, and that difference is the entire saving |
| W9.4 | `omniweave-target-docx`: `owflow/1`, an html carrier, python-docx + lxml, a flow-carrier construct table | S-out | 6 | a flow carrier has no geometry and no shaping, so its **compile half** is roughly a third of W9.2's 16 ew. The ratio is taken against W9.2 alone and therefore excludes `read_back`, which is W9.3's separate 5 ew for pptx and W9.4b's for docx — a Target's full price is compile + `read_back` + card, and any ratio to another Target must be taken against the same three. Deliberately **not** in `[recommended]`, so its dependency weight never lands on the default install |
| W9.5 | `omniweave-target-deck`: the `deck` Toolchain, `toolchains/_shared/target-runtime.ts` (the framework-owned hello / ready / validate / compile loop), `omniweave-target/1` as NDJSON-on-stdio with a **job directory** as the data plane, and `ow targets install` by digest into `$OMNIWEAVE_HOME/` | S-out | 7 | open-slide is a pnpm + Turbo monorepo of 68,009 non-vendored TypeScript lines (`find open-slide -name '*.ts*' \| grep -v node_modules \| xargs wc -l`). We take the AST-located `@slide-comment` feedback loop and the `pnpm-lock.yaml` discipline, not the app |
| W9.6 | `omniweave-target-video`: the card at `[compile] implemented = false`, and `ow out targets` printing the reason | S-out | 0.5 | one card and one message. This is why `[compile]` unknown keys are a hard error: an older core reading a newer card must not drop `implemented = false` and treat the target as implemented |
| W9.7 | `artifact`, `artifact_unit`, `artifact_asset`, `artifact_cite`, `artifact_el`, the retained IL bundle frozen into CAS, `read_back_doc_ord` as a foreign key, and INV-16's compile-side refusal naming the offending cites and asset ids | S-out | 4 | five tables at 0.5 engineer-day plus the retention path. `artifact_cite`'s `verbatim` bit is **proved**, never claimed, which is where the cost sits |
| W9.8 | The OUT conformance suite, `compile.text.owtext` as the reference target, `fixtures/out/{golden, foreign, expected}`, and the 40-unit golden fixture compiled on all nine cells | S-quality | 4 | r1..r7 with a fixture each, plus the nine-cell `part_digest` member-by-member diff that closes F16 |
| W9.9 | `ow out scaffold \| stamp \| check \| normalize \| compile \| verify \| back \| constructs \| targets`, and `ow make deck` | S-out | 3.5 | nine verbs plus one composite. `ow out constructs pptx --format md` is CI-gated at `agent_doc_tokens_max = 6000`, which is the constraint that shapes the output format |

**Total 60 ew.**

#### The `read_back` exposure — W9.4b and W9.5b

W9.3 funds exactly **one** `read_back` driver, `parse.pptx.native`.
[Generation](09-generation.md) §12's target table names `parse.docx.native` and `parse.deck.native`
as the other two Targets' readers, and §11's **R2** (ADDRESS SURVIVAL) and **R3** (SECOND-ROUND FIXED
POINT) are both stated over `read_back(compile(I))` — R2 whenever `fidelity != none`, R3 for every
value but `none`. Neither law is testable for `docx` or `deck` without a reader, and both Targets are
required to reach `GateStatus == passed` by this phase's goal. **The 60 ew above does not carry
them.** They are named and priced here so that the gap is a funding decision at week 40 rather than a
discovery at the week-56 freeze.

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W9.4b | `parse.docx.native` (`read_back`): python-docx → `owdoc-fragment/1`, `Method.ROUNDTRIP`, the `artifact_el` map, and `w:comment` → `Kind.COMMENT` on `Layer.ANNOTATION` ([09](09-generation.md) §12.3) | S-out | 3 | W9.3 is 5 ew against `owsvg/1`'s ~180 constructs. `owflow/1` declares ~70 and carries no geometry, no z-order and no shaping, so the per-construct term is ~40% of pptx's (70/180) while the per-Target constant — the fragment writer, `Method.ROUNDTRIP`, `artifact_el` — is identical. W9.3's 5 splits ~1.8 constant + ~3.2 per-construct, so 1.8 + 0.4 × 3.2 ≈ 3 |
| W9.5b | `parse.deck.native` (`read_back`): the `deck` Toolchain's html carrier → `owdoc-fragment/1`, `data-ow-cite` recovery, and `Method.ROUNDTRIP` | S-out | 3 | ~90 `owdeck/1` constructs, and the carrier is html the Toolchain itself emitted, so W9.1's error-recovering READ parse in `carrier/html.py` is the whole parse layer and none of it is target-specific. The cost is the runtime-rule half: `getBoundingClientRect` capacity results are not recoverable from the artefact, so the reader must **not** claim them, and R2's exactly-one-Block assertion is what proves it did not |

**Exposure: 6 ew**, inside the evaluation's ~5-8 ew band. It is **not** inside P9's 60, not inside the
program's 366, and §3.1's matrix is unchanged — R-Q8 is where the 6 ew has to come from. The decision
deadline is **week 40**, one freeze earlier than the work: `owflow/1` and `owdeck/1` freeze at the end
of P9 (week 56), and a reader written after its carrier freezes cannot ask that carrier to keep a key
it did not keep.

#### What an additional Target costs

**25.5 of P9's 60 ew is one-time shared framework** — W9.1 (14), W9.7 (4), W9.8 (4) and W9.9 (3.5) —
and no second Target pays any of it again. The other 34.5 funded engineer-weeks plus the 6 ew of
`read_back` exposure above are target-specific, and they divide per Target: **pptx 21** (W9.2 16 +
W9.3 5), **docx 9** (W9.4 6 + W9.4b 3), **deck 10** (W9.5 7 + W9.5b 3), **video 0.5** (W9.6's card
alone, `[compile] implemented = false`). 25.5 + 21 + 9 + 10 + 0.5 = 66, and 66 − 6 = the 60 above.

So **each additional Target is 6-10 ew, not 20**, and the marginal figure is the one a reader should
carry out of this section: once `omniweave_core.out` exists, OUT is extensible at roughly one
engineer-month per Target. docx is the measurement rather than the projection — it came in at 6 ew of
compile, a third of pptx, exactly as its estimation basis predicted, and that is the evidence the
framework/Target split of [09](09-generation.md) is real rather than asserted. The estimation rule
that keeps the next number right: **price a Target as compile + `read_back` + card**, and take any
ratio to another Target against the same three. W9.4's original basis was a ratio against W9.2 alone,
and that omission is exactly how W9.4b and W9.5b came to be missing from this table.

#### Frozen at the end of P9 (week 56)

`owsvg/1`, `owflow/1`, `owdeck/1`, `owmotion/1`. The `constructs.toml` grammar with
`unknown_construct = "forbidden"`, which is not configurable. `GateStatus`'s ten values, exactly one
of which (`passed`) permits a release. `ArtefactDeterminism`'s four classes with `part` as the
promised floor and `byte` recorded-never-promised. The `OWC1` marker grammar. `omniweave-target/1`.
The receipt schema. `el` addresses — minted once by `ow out stamp`, never renumbered, refused on a
duplicate.

#### The demo

`ow make deck` from a corpus brief produces a PPTX in which every quoted line resolves through
`artifact_cite` to a page and a polygon in the source contract. Edit one slide's IL by hand,
recompile, and every untouched unit reports `passthrough` with a byte-identical `part_digest`. Then
`ow out back` re-enters the deck as a corpus document, and "which decks quote page 14 of this
contract" becomes one indexed query.

#### Exit criteria

```bash
uv run ow conform packages/omniweave-target-pptx --suites all
uv run ow conform packages/omniweave-target-docx --suites all
uv run ow conform packages/omniweave-target-deck --suites all
uv run ow out verify fixtures/out/golden/pptx --determinism part --cells 9
uv run pytest packages/omniweave-core/tests/out -q          # r1..r7
uv run pytest tests/out/test_restricted_refusal.py -q       # INV-16 parse -> derive -> compile
uv run ow out targets --render json | jq -e '.[] | select(.target=="video") | .implemented == false'
uv run ow eval run --suite roundtrip --cassette required
```

#### Non-goals

`bake` is `unavailable` on **every** Target (F18), with both exits named in the error; if the tier has
zero live rows at release, DP5's pre-committed action demotes `bake` to `forbidden` with a documented
degradation rather than keeping a `Disposition` member nothing implements. `project(Doc) -> IL` for a
foreign artefact is the honest `rebuilt` path only, and below F17's ~70% shape round-trip the card
declares `project = false` for foreign input and `ow out back` is corpus-only. No video. **No `il_node`
table** — the stamped `data-ow-el` attribute in the file *is* the durable anchor, and a node table
would be a second representation of what the text already carries.

## 13. P10 — Quality, calibration and release

**Goal.** Turn the measurements that have been accumulating since P2 into a publishing gate, and ship
fourteen wheels on a tag.

#### Work items

| id | item | skill | ew | estimation basis |
|---|---|---|---|---|
| W10.1 | `.oweval` as a separate SQLite file: `eval_corpus`, `eval_run`, `eval_assertion`, `eval_verdict`, `eval_metric`, `eval_counter`, `eval_perf`, `eval_calibration`, `eval_flake`; the RNG-free harness; closed-form statistics (macro mean at `min_slice_n = 30`, `se = sqrt((1/S²)·Σ sd_s²/n_s)`, Wilson everywhere, the sign-flip permutation test's exact asymptotic with exact enumeration below N = 20) | S-quality | 6 | nine tables plus the statistics module. olmOCR-Bench calls `np.random.choice` and `shuffle` unseeded at `olmocr/bench/utils.py:33,55,120,172` with no `seed` anywhere under `olmocr/bench/`, so its published intervals do not reproduce — that is the defect this item exists not to repeat |
| W10.2 | Reductions (`shape` frozen; `pages` and `outline` tracked; `outline` suppressed above 500 pages), the PR-comment differ led by the `shape` delta, and the bless flow: `OMNIWEAVE_BLESS` + a `BLESS.log` row in the same commit with a ≥ 20-char reason + a second reviewer past 20% of files + `test_bless_flag_is_off()` | S-quality | 3 | three reducers plus the differ. "6 fewer tables, 174 more cells" is the sentence a reviewer needs; 9,000 diff lines are not. docling's `tests/test_data_gen_flag.py` is adopted whole |
| W10.3 | The Deep golden: an exploded `.owdoc.d/` for at most 24 documents of at most 40 pages, with `rebind()` as the **only** semantic differ | S-quality | 2 | one matcher, two consumers — the differ is P2's `rebind()`, so this item is corpus curation plus the harness and nothing else |
| W10.4 | Counters (`eval/counters.toml`, each `exact` or `ratchet`), the Pacer (`blake2b` over 64 MiB, a 2M-iteration integer loop, 200k SQLite insert+select, run **before and after** every timed measurement, `unstable` above 15% disagreement), `eval_perf`, and the release-anchored anti-ratchet (against N−1 at tolerance **and** N−2 at 2×) | S-quality | 3 | ~30 counters plus one workload. Counters catch what a clock cannot: a silent re-render, a re-billed free operator, a 100% cache miss |
| W10.5 | Calibration: `eval_calibration` buckets, Wilson intervals, ECE and Brier over 10 equal-mass bins, `Calibrated` population, and the four calibration gates | S-quality | 4 | four gates plus the fitter. n ≥ 150 per bucket per slice for ordinal separation and n ≥ 1000 for probability sharpness set the corpus size, and F22 says whether that size is reachable at all |
| W10.6 | The seven eval suites (`parse`, `extract`, `retrieve`, `absence`, `roundtrip`, `portability`, `perf`) and `ow eval run \| record \| bless \| golden \| calibrate \| correlate \| release-check` | S-quality | 5 | seven suites at ~0.5 ew plus eight verbs. `skip` is not a state, so every suite must be able to report `unknown` and `release-check` must refuse on it |
| W10.7 | `eval_scoreboard` as the publishing view (`UNKNOWN` / `WITHHELD` / `UNRANKED` / `RANKED`), byte-diff gated, every row carrying `witness`, `not_measured[]` and `confounders[]`; the harness self-test over deliberately wrong outputs | S-quality | 2 | one view plus three wrong-output fixtures — a dropped page, a transposed table, a fabricated quote — each with an exact expected score |
| W10.8 | `omniweave-golden` as a data artefact (~600 documents, `omniweave-golden-<version>.zip` with `ZIP_DEFLATED` members + `manifest.toml` + `.sha256`, digest-installed, re-verified on every use, a mismatch never triggering a fetch); Tier A's ≤ 64 MB budget with ≥ 40% real public-domain scans; the two independent booleans `document_redistributable` and `assertions_redistributable` | S-quality + S-sec | 3 | 600 documents of provenance review at ~4 minutes each is the bulk. A Tier-B assertion file quoting more than `min(2000 chars, 10%)` of one source document is refused |
| W10.9 | Release engineering: `release.yml` with OIDC trusted publishing (the file **must not** be renamed), 14 sdists and 14 wheels on one runner all `py3-none-any`, generated `LICENSES/` and `THIRD_PARTY.md`, G16's template-driver archive, and the two-release deprecation machinery | S-rel | 2 | one workflow plus the generators. The build matrix is deliberately one runner because every wheel is pure |
| W10.10 | `omniweave-langchain`: `OmniweaveLoader(BaseLoader)`, `OmniweaveBlobParser(BaseBlobParser)`, `OmniweaveRetriever(BaseRetriever)`, then `create_omniweave_tool(...) -> StructuredTool(response_format="content_and_artifact")` and `OmniweaveMiddleware(AgentMiddleware)` harvesting artifacts off `ToolMessage`s into a custom `AgentState` channel | S-retrieve | 3 | 1 ew for the three ABCs, 2 for the artifact path and middleware (`_index/in-04-agentic.md` §7 item 2). `ToolMessage.artifact: Any` is the only lossless crossing available in any framework's own types, and langchain 1.4.0's dependency on `langgraph>=1.2.11,<1.3.0` puts provenance into a durable forkable execution state at the same time. It depends on the `Corpus.doc` ruling: `@stable` ([10](10-interfaces.md) §9.4), so the adapter's `CellPos`/`OriginSpan`/`marks`/`SpanMap` path is not on a MINOR-breakable symbol |
| W10.11 | The four `Q-G` gate scripts [ADR-11](adr/0011-eval-register-reconciliation.md) added when it closed the series at twenty-seven — a silently deleted test suite (`Q-G24`), a misplaced marker (`Q-G25`), corpus leakage (`Q-G26`) and metric rot (`Q-G27`), defined by [quality](13-quality.md) §13.1 | S-quality | 0.8 | §15.1 rule 3 at 1 engineer-day per gate script. `Q-G26` and `Q-G27` land here with the corpus and the scoreboard; `Q-G24` and `Q-G25` are written in P1 with the gate harness and are funded from this row because blocks A and B carry no unallocated capacity (§3.1) |

**Total 33.8 ew.**

**W10.8 carries an ordering constraint that is not a preference.** The data artefacts' container is
[ADR-10](adr/0010-data-artefacts-and-weight-ceiling.md)'s plain ZIP
([repo layout](11-repo-layout.md) §3.2), and the re-packaging **costs nothing if it lands before
W10.8 first publishes `omniweave-golden`** — the packager is written once and the whole price is
roughly 15% on a one-time ~240 MB download. After W10.8 it is a re-publish: both artefacts are
repacked *and* their digests change, and a digest change is by the charter's own rule a permanent
failure that never triggers a fetch, so every installed copy must be told to re-fetch by hand. The
same constraint binds `omniweave-index` at the `V20-6` line (§18). No other work item in this phase
has a deadline that runs backwards from a publication rather than forwards from a dependency.

#### Frozen at the end of P10 (week 62)

`harness_version`. `eval/gates.toml`'s thresholds and guards. `eval/counters.toml`'s exact/ratchet
classification. `eval/perf.toml`'s budgets. The scoreboard's columns. And every gate row's owner and
`review_by` date — the rot check fails the build on a row past its date, which is the mechanism that
stops §17's decision points from decaying into a table nobody reads.

#### The demo

`ow eval release-check` on the release commit exits 0 with **zero** `unknown` results. Immediately
after, feed the harness three deliberately wrong outputs and watch it produce the exact expected
scores. The eval code is itself tested, which is the one piece of infrastructure that is otherwise
always tested less rigorously than the runtime it judges. *(Build note, D835: `tools/acceptance_v10.py` rolls up V10-1 .. V10-17 with `acceptance_v01.py`'s machinery, loaded rather than copied. On landing it reads 0 PASS, 12 PARTIAL, 0 FAIL and 5 UNMEASURED: V10-3 and V10-14 have no instrument, and V10-4, V10-7 and V10-8 are slow. Each row's gap names the clause nothing asserts. The rows wait most often on a `v*` tag, the corpora, `ow eval release-check`, the 14-wheel build and the nine-cell matrix.)* *(Build note, D873: the demo's first half runs. `ow eval run` measures parse, absence, retrieve and roundtrip into an `.oweval` (D868-D871), and `ow eval release-check` over it exits 0 with three hard gates met. `--strict` refuses on extract, portability and perf. Each writes an `unknown` run naming what is missing (D872): an extraction harness and labelled corpus, a plan definition, and the pinned runner. V10-1 runs that pair as a slow instrument, and V10-4's gap no longer says `citability_violations` has no gate row. The roll-up still reads 0 PASS: every row waits on a tag, the corpora, the matrix or the runner.)*

#### Exit criteria

```bash
uv run ow eval release-check --strict                # zero unknown outside perf and false_confident_zero (D987, D1017); skip is not a state
uv run tools/gate_bless.py                           # bless flow + test_bless_flag_is_off()
uv run tools/gate_frozen_stability.py --pdfium-minors 2 --cells 9
uv run tools/gate_measured_on.py                     # every published number's ten-field MeasuredOn
uv run tools/gate_gate_rot.py                        # every gate row's review_by
uv run tools/gate_flake.py --window 30d              # >2% quarantines to informational
uv run tools/gate_parity.py --offline --no-gpu --no-node     # <= 600 s hard ceiling
uv run tools/acceptance_v10.py                       # V10-1 .. V10-17 from 00-vision.md 9.2
```

**v1.0 == release 1 ships at week 64, at 363.8 cumulative engineer-weeks.**

#### Non-goals

**No rendered digit.** No confidence signal is calibrated at v1.0, so every badge stays dark and the
internal-filter clause keeps `Trust` and `Quote` usable as sort keys — that is V20-5, not V10. No
public ranking for any corpus whose `publishable = 0`. No competitor `Runner` in a wheel: heavy
runners live in `evals/runners/`, in tree and unpackaged, so docling's torch never reaches a weight
gate.

## 14. The critical path and what runs in parallel

### 14.1 The dependency graph

```text
                 M0 (claims 1,2,4 gate the shapes below)
                  |
                  v
   P1 substrate ------> P2 store/L2 ------> P3 drivers+parse ------> P4 runtime
        |                  |    |                   |                  |   |
        |                  |    +--------> P6 retrieval <--------------+   |
        |                  |                        |                      |
        |                  +--------> P9 OUT <------+                      v
        |                                  ^                            P5 router
        |                                  |                               |
        +--------> (gate harness) ---------|-------> P7 surface <----------+
                                           |             |
                                  P8 graph -+            v
                                           |          v0.1 @ 42
                                           v
                                      P10 release ---> v1.0 @ 64

   ===>  critical path: M0 -> P1 -> P2 -> P3 -> P4 -> P9 -> P10
   ---   P8 is NOT a prerequisite of P9.
```

**The critical path is M0 → P1 → P2 → P3 → P4 → P9 → P10.** Laid end to end with no overlap those
seven phases are 3 + 10 + 15 + 16 + 22 + 20 + 12 = 98 weeks; the overlaps §14.2 permits compress them
to 64. Every week of that 34-week compression is bought by a freeze point landing earlier than its
phase's exit, which is why §1.3 separates the two.

Note what is *not* on it. **P8, the graph, is not a prerequisite of P9, OUT.** A Brief is consumed
from an Answer; an `artifact_cite` points at a Block; the OUT gate reads `constructs.toml` and
`rules()`. None of those touch L3. That is the single most valuable schedule fact in this document,
because it means the two largest phases (46 + 60 = 106 of 363.8 ew) run concurrently and the graph can
slip a month without moving the release. R-Q7 states the one case in which the claim is false and
names the experiment that settles it in P9 week 2.

### 14.2 Edges, with the forcing reason and the earliest start they permit

| edge | forcing reason | earliest start of the target |
|---|---|---|
| M0 → P1 | claims 1, 2 and 4 decide whether `omniweave_ports`' shape is right before 22 ew is spent against it | week 1; P1 runs alongside, and only W1.1 waits on claim 1 |
| P1 → P2 | `canonical()` and `ow128` are digest **inputs**; a table cannot be written before its digest function is frozen | P1 week 4, after W1.2 |
| P2 → P3 | FE1: a driver's `capability` suite asserts against `Block`'s field set | P2 week 4, after W2.1 and before the full DDL |
| P2 → P6 | retrieval reads `Reader`, `block_fts` and `block_sec`, and nothing else | P2 week 9, after W2.3 and W2.8 |
| P3 → P4 | the runtime dispatches to `DriverHost.invoke()`, which P3 owns | P3 week 5, after W3.2 |
| P4 → P5 | `admit()` needs the durable ledger; `route_spend` needs `Spend` | P4 week 9, after W4.5 |
| P4 → P5 (again) | FE4: `parse.page.olmocr` is the first model-backed driver and must not run before the `call` layer | P4 week 8, after W4.4 |
| P5 + P6 → P7 | FE5 is already satisfied by M0, so P7 needs only the Actions' *implementations* | P6 week 12 |
| P6 → P8 | the graph's structural half extends P6's `Expand`, and the semantic channel reads `segment` | P6 exit |
| P2 + P6 → P9 | `artifact_cite` needs Blocks with cites; a Brief needs an Answer | week 43 — **resourcing-limited, not logic-limited** |
| P4 → P9 | a `compile` work row is dispatched, budgeted and cached like any other | P4 exit |
| everything → P10 | a gate needs the thing it gates | instruments continuous from P2; gating from week 53 |

### 14.3 What can be pulled forward, and what cannot

**Can, if headcount allows.** W10.1 (`.oweval` and the statistics module) depends on nothing above L2
and could start at week 8; doing so buys earlier measurements for F1, F2 and F13. **W9.1
(`omniweave_core.out`) depends only on P2's model and could start at week 26 — this is the single
highest-leverage schedule change available**, because W9.1 is serial ahead of every Target (R-Q1).
W8.1 and W8.2 (Segments and anchors) depend only on P2 and could start at week 20.

**Cannot, and it is worth saying why.** W5.6 (`parse.page.olmocr`) cannot precede W4.4 (the cache):
that is FE4, and violating it means every iteration on the page prompt re-bills the fixture corpus.
W8.8 (the billed graph passes) cannot precede W8.5 (the coverage ledger), because without
`derive_cover` there is no evidence that the free passes preempted anything and the entire
deterministic-first argument collapses into a claim. W7.3 (MCP) cannot precede W7.1 (the registry):
that is FE5, and the inversion is LEANN's defect built deliberately.

## 15. Team shape and effort

### 15.1 The estimation basis, stated so a reviewer can reject a number

1. **Rate.** 1,250 reviewed, typed, tested and gated Python lines per engineer-week (250/day) for work
   whose contract is already written. The charter is spec-complete for most of P1-P6, so this is a
   transcription-plus-tests rate, not a design rate. **Calibration anchor:** the charter prices the
   rejected Rust store kernel at 4-6 engineer-weeks for the substrate alone — roughly 6,000 lines of
   unsafe-adjacent systems code — which is consistent with 1,250/week for ordinary code and materially
   slower for novel code.
2. **Schema.** 0.5 engineer-day per SQL table, covering its `CREATE TABLE`, its migration line, its
   schema-lint row, its `enum_val` rows and one round-trip test. 91 tables ⇒ 45.5 engineer-days ⇒ 9 ew
   (W2.2).
3. **Gate.** 1 engineer-day per `G` or `Q-G` gate script. 27 + 27 = 54 gates ⇒ **10.8 ew**,
   distributed into the phase that first needs each — never batched into P10, which is why P10 is
   30 ew and not 40. **The four extra days are a debit, not a credit, and the plan's own index had
   the sign backwards.** [ADR-11](adr/0011-eval-register-reconciliation.md) closed the `Q-G` series
   at twenty-seven rather than twenty-three; at 1 engineer-day per gate script, four more gates are
   four more engineer-days of work, not four recovered, so 50 ed ⇒ 10 ew becomes 54 ed ⇒ 10.8 ew.
   `Q-G24` and `Q-G25` land in P1 with the gate harness and `Q-G26` and `Q-G27` in P10 with the
   corpus and the scoreboard, per this rule's own distribution clause; all four are funded from
   P10's row as work item **W10.11** (§13) and come out of block I's slack (§3.1), which is the only
   unallocated capacity in the matrix. **The `G` half of this arithmetic is a literal the roadmap no longer owns.**
   [ADR-2](adr/0002-invariant-and-gate-registers.md) made the G-series append-by-ADR and appended
   `G28` and `G29`; its cardinality lives in `tools/gates.toml` and its sole home is
   [repo layout](11-repo-layout.md) §6.4. ADR-2 priced no roadmap consequence for the two, and at
   this rule's own rate they are **2 further engineer-days** that neither ADR budgeted. The next
   change to this line re-prices from the register's row count, not from `27 +`.
4. **Conformance suite.** 3 engineer-days per suite. 12 suites ⇒ 7.2 ew (W3.6).
5. **Property test.** 8 hypothesis property tests per engineer-day at `derandomize=True @ 200`.
6. **Integration tax.** +30% on any work item that crosses a distribution boundary, applied inside the
   numbers above rather than added at the end. The four most heavily taxed items are W3.2, W4.2, W9.1
   and W9.5.
7. **Exclusions.** The F-item measurement runs are **not** inside the 363.8 ew: they are ~14 additional
   bench-weeks on the pinned runner `ow-bench-1`, which is machine time plus roughly 0.3 ew of analysis
   each. Documentation beyond generated artefacts is excluded. Recruiting, onboarding and holiday are
   excluded, which is why §3.1's ramp is a ramp and not a step.
8. **Confidence.** These are p50 estimates for one senior engineer fluent in the charter. They are not
   commitments. **The intended use is relative: if P1's actuals land at 1.4×, rescale every later phase
   by 1.4 rather than re-arguing each item** (R-Q3). P1 is the best early estimator available because
   it is the most spec-complete work in the program.

### 15.2 Skills, and where each is load-bearing

| skill | what it means concretely | phases where it is on the critical path |
|---|---|---|
| **S-core** | SQLite internals (WAL, FTS5 external content, trigger generation, `WITHOUT ROWID`), canonical serialisation and digest discipline, zero-dependency Python | P1, P2 |
| **S-parse** | PDF internals (pdfium text API, CID maps, glyph runs), OOXML and ODF, Unicode normalisation across five scripts, layout heuristics | P3, P5 |
| **S-runtime** | asyncio at scale, process supervision and reaping, durable queues and lease semantics, cost accounting | P3 (the hosts), P4 |
| **S-retrieve** | BM25 and FTS5 scoring, rank fusion, query parsing, and the agent-surface token economics | P6, P7 |
| **S-graph** | entity resolution (LSH, Jaro-Winkler, union-find), community detection, prompt engineering with grounding gates | P8 |
| **S-out** | OOXML writing (DrawingML, OPC), SVG, text shaping (uharfbuzz), and enough TypeScript for one Toolchain | P9 |
| **S-quality** | applied statistics (Wilson, ECE, Brier, permutation tests), test infrastructure, CI, determinism | P2 (the crash matrix), P10 |
| **S-sec** | licence review (SPDX, OpenRAIL clause reading), SSRF and egress control, semgrep authoring | P1 (G3), P3, P10 (corpora) |
| **S-rel** | packaging, `uv` workspaces, OIDC trusted publishing, install receipts | P1, P7, P10 |

Two hiring consequences follow. **S-out is needed from week 43 and not before**, which is late enough
to hire against a working product rather than a plan — and it is the largest single skill draw (60 ew
in one phase). **S-quality is needed from week 11 and never leaves**, because the instruments are
built inside the phases they measure (FE3); hiring S-quality at P10 would mean building P10's gates
against measurements nobody recorded.

## 16. Build versus wrap, per component

The verdict vocabulary is closed. **Depend** = a resolver dependency in a `pyproject.toml`. **Wrap** =
depend, behind a driver card, so a swap is a config line. **Vendor** = copy source at a recorded SHA
under `vendor/<name>/` with LICENSE + NOTICE + `.sha256` + a parity test (G12) + a written
`FORK-TRIGGER.md`. **Reimplement** = write it, using the mined repo as a design reference, recording
that no code was copied. **Reject** = read only, with a written reason.

**The exit rule, stated once.** Every wrapped component sits behind a `driver.toml`, so replacing it
is a `[drivers] enabled` edit plus a card. Every vendored component has a `FORK-TRIGGER.md` naming a
**testable** condition. Every rejection names its alternative in the `codes.toml` fix command for the
error its absence produces. **There is no component in this framework whose disappearance has no
written response.**

| component | verdict | source | reason | exit if upstream dies |
|---|---|---|---|---|
| Office / ODF / RTF / EPUB / CSV decode | **depend + vendor** | `firecrawl-anydoc == 0.2.4` (MIT, published `abi3` wheel) | the only compiled dependency in the framework, and we do not build it. Best limit discipline in the collection (twelve constants in `src/package/limits.rs`), twelve fuzz targets, no network by design. Risk accepted with eyes open: three months old, 130 commits, 91% single author | `vendor/anydoc/FORK-TRIGGER.md`, two named clauses: (1) emit a `w:p` / `a:t` child-index path per Block — the day that lands, `origin_span` becomes `"exact"` and `verbatim` opens on the office path; (2) F2's marshal breach. A fork is a Rust crate we then own forever, priced deliberately as an option rather than paid up front |
| PDF text and geometry | **depend** | `pypdfium2` | pure wheels for all nine cells, no system library, and a text API exposing glyph runs — which INV-10's `glyphs` branch requires | a second `parse/1` card over `pdfminer.six` at a lower declared `origin_span`; the capability ladder already expresses the downgrade without a code change |
| OCR / VLM weights | **depend on the weights, reimplement the harness** | olmocr (Apache-2.0 **code and weights**) | the only permissive high-accuracy OCR in the collection. But 88% single author, five months quiet, a retry amplifier and a 1600-concurrency default, so the pipeline is not adoptable. We take the weights, the page-query prompt, `PdfFilter` and the `finished_on_attempt_N` metric shape; we own the client, the pre-filter and the harness | weights are a file pinned by exact revision; a replacement is one distribution and one card. The ~4-point olmOCR-bench gap to surya is **the price of OpenRAIL clause 2(c)** and may not be re-litigated as an engineering shortfall |
| Layout detection | **reject, for now** | docling's six RT-DETR variants | no candidate has both an OpenRAIL-free licence and a pinnable revision; docling's own `revision` defaults to `"main"` | ship without it. Every affected decision records `cause = "layout_unavailable"`, so the veto's cost is a scoreboard number rather than a rumour (F4) |
| marker / surya weights | **reject** | marker, surya | OpenRAIL-M clause 2(c) plus clause 8 make the weights unusable at $0 | read the architecture; use olmocr's weights with docling's assembly ideas |
| The document model | **reimplement** | docling's `DoclingDocument` | the design is the asset; the package is not, because torch is a base dependency and that fails G1 on its own | none needed — nothing is depended on |
| Segmentation | **reimplement** | `graphrag-chunking` | 388 lines; `sentence_chunker.py:9` imports nltk with nltk absent from `pyproject.toml:32-35`; `bootstrap_nltk.py` fires eight `nltk.download()` calls from `SentenceChunker.__init__`, failing G15 and `needs_network = false` | `derive.segment.spine` is ours |
| Graph extraction design | **reject as a dependency, take the shapes** | graphrag (MIT, **declared maintenance mode**) | verified at `_collections/graphrag/README.md:3`: "largely in maintenance mode, and won't be accepting new PRs or implementing new features. We'll perform bug fixes and dependency updates … particularly to address CVEs as they arise." **Maintenance mode is a real input, and here it is a non-issue precisely because we take zero code and zero dependency.** We take the extraction schema, the determinism triple (`cluster_graph.py:57-97`) and the cache/storage abstraction shape, and invert three defaults: `use_lcc=True` (`defaults.py:72`), `MAX_COMMUNITY_SIZE = 10`, and description-as-a-list re-summarised on every merge | **there is no upstream to die.** The only thing lost is a design reference, already transcribed into [06-structure-extraction.md](06-structure-extraction.md). A declared policy also beats undeclared silence: markitdown, docling and olmocr are all quiet with no stated posture, which is strictly worse to depend on |
| Entity id normalisation | **vendor** | `graphify/ids.py` (Apache-2.0) at `vendor/graphify-ids/` | reimplementing a caseless-stable, charset-closed normaliser is how you ship a Turkish-dotted-I bug. `normalize_key` and `normalize_k` live in `omniweave_core.ident` because `GraphSink.mention`, `FieldGrounding`, the anchor writers and `op.resolve` all call them host-side | ~200 lines under a permissive licence, plus the 20k-string five-script conformance corpus that proves a replacement. Vendoring makes the exit cheap; depending would not have |
| Egress guard | **vendor** | `graphify/security.py` (460 lines: SSRF, path confinement, sanitisers) and `llm_wrap.py`, at `vendor/graphify-security/` | the mining's own conclusion: reimplementing an SSRF guard from scratch is how you get a bypass. Real risk: graphify has relicensed once already | a copy taken under the prior licence is unaffected by a later relicence, and the four-part vendor rule is what makes that provable rather than asserted |
| Clustering | **reimplement, with an out-of-tree escape** | graphrag's Louvain determinism; graspologic-native for the escape | pure Python over an `array('i')` CSR from one SQL scan. graphify's `cluster.py:22-40` measured **7-19 s** of graspologic package import for a layout algorithm it never calls, which is exactly why the escape is a driver and not a dependency | above `MAX_CLUSTER_EDGES`, refuse and name `omniweave-driver-leiden`. Conditional on F40: if its licence does not clear G3's three scans, the refusal has **no** named escape and F15's fallback becomes `num_perm = 64` plus a smaller `MAX_COMMUNITY_SIZE` |
| ANN vector index | **reimplement the algorithm, never the package** | LEANN | `leann-core` requires AGPL PyMuPDF **and** torch, ships archived `PyPDF2`, four PDF libraries, and an unauthenticated loopback ZMQ REQ/REP on a dynamic port — compute theft from any local process. The pruned-graph plus selective-recomputation design is the asset | v1 ships `vector.brute` plus the 250k refusal and `vectors = "off"`. The seam is the `omniweave.backends` entry point plus `backend.toml`, with four verified contract obligations. F10 gates any candidate through G3 **before the vector phase starts** |
| PPTX writing | **depend on the writers, reimplement the compiler** | `python-pptx`, `XlsxWriter`, `skia-pathops`, `uharfbuzz`, Pillow; ppt-master as prior art | ppt-master is 96% single author across 78 scripts, with `svg_to_pptx` at 53,666 lines and a single 9,368-line checker class, and it carries three things we excise outright (a watermark remover, `curl_cffi` impersonation, `edge-tts` on by default) plus AGPL PyMuPDF and an **undeclared** LGPL `cairosvg` import — which is precisely what G3's import-graph scan exists to catch | `opc.py` is ours and is the only ZIP-for-write in the framework, so a `python-pptx` exit is a writer swap behind one module rather than a target rewrite |
| DOCX writing | **depend** | `python-docx`, `lxml` | a flow carrier needs no geometry and no shaping. Deliberately **not** in `[recommended]`, so its dependency weight never lands on the default install | the same `opc.py` seam |
| Deck rendering | **adapt as a Toolchain** | open-slide | not a dependency: it is an app (68,009 non-vendored TS lines). We take the AST-located `@slide-comment` feedback loop and the `pnpm-lock.yaml` discipline; we reject its `SECURITY.md` (an unedited template) and its `skills-lock.json` (pins no ref, hashes only `SKILL.md`, records no licence) | the Toolchain is a digest-pinned bundle with the digest **in the path**, installed by `ow targets install`, never by `pip`. Replacing it changes one manifest row. F18 decides whether its rasterizer clears `tools/licences.toml` at all |
| Video | **defer** | hyperframes | H.264 + AAC carries pool royalties and pulls a GPL ffmpeg build; the mining was never written, so a construct table designed from an index page would be exactly the speculative generality D8 refuses | `omniweave-target-video` ships at `[compile] implemented = false`, honoured because `[compile]` unknown keys are a hard error. Royalty-free codecs are the default when it lands |
| MCP protocol | **depend** | `mcp`, in `omniweave-serve` only | one distribution, one dependency, and `omniweave-serve` may never import `omniweave` | the four-tool surface is generated from our registry; a protocol change touches one adapter |
| MCP tool-surface design | **reject the code, take the measurements** | jcodemunch-mcp | Dual-Use licence: no redistribution tier at any price, registry publication forbidden, default-on telemetry, a phone-home in the library. We keep a written no-code-copied record | the measured findings are ours to cite: 22,741 tokens/turn for 91 tools against 939 for three, and the retreat shipped as the new-install default |
| Review and governance process | **adopt** | awesome-skills | a `SECURITY.md` threat model with hard rejects, `REVIEWING.md`'s four-stage process, "never run scripts from the PR", the `?token=` rule, cost as a review criterion, `lint_references.py` | process, not code |
| Security CI | **adopt** | local-deep-research | CVE-annotated pins, `.semgrep/rules/`, five security workflows plus `zizmor`, the disclosure SLA table (30/45/60/90 d by severity, 48 h ack) | process, not code. Its 90-direct-dependency single package is the anti-pattern our fourteen distributions exist to avoid |
| Operator / registry pattern | **reimplement the shape** | DataFlow | its code carries `os.system` f-string injection, in-process `exec` of model output, `pickle.load`, `trust_remote_code=True` by default and four `0.0.0.0` binds. Its 20 extras include four mutually incompatible vLLM pins under a `requires-python` that is false by three minor versions | nothing depended on |
| Vendored-artefact discipline | **adopt the design** | codegraph | sha + parity test + arch assertion + pin comments, which is G12 verbatim. Rejected: 66 MB in the package, 24 of 27 grammars unattributed, verbatim untrusted source handed to the agent with no delimiter | process, not code. Its SQLite result — 6.4M relationships with sub-millisecond reads — is the evidence for shipping no graph engine at v1 |

## 17. Decision points

Each row names a trigger week, an owner, and the action taken **automatically** if the date passes
with no measurement. The gate-rot check enforces the dates: every gate row carries an owner and a
`review_by`, and a row past its date fails the build. That mechanism, not this table's existence, is
what stops the table rotting. Charter §7's F1-F41 are the questions; these are their deadlines.

| # | trigger | question | owner | action if the trigger passes unmeasured |
|---|---|---|---|---|
| **DP1** | **before the P7 freeze, week 36** | F14 — do current models emit `e412`, `c412` and `k412` as reliably as `d7#412`? | Retrieval lead | measure in P6 over 1,000 generations. **Change the sigil before anything ships, never after** — a sigil in a shipped answer is forever. Unmeasured at week 36, v0.1 ships with no non-Block sigil in a rendered Answer and L3 evidence renders through member Block cites only |
| **DP2** | **before the golden suite freezes, week 53** | F31 — does whole-point quantisation absorb driver geometry jitter, so `layout_digest` is a usable frozen-golden key? The `shape` byte-diff gate rests on it | Quality lead | widen the quantum — one `digest_recipe` bump, budgeted once — and demote geometry goldens to the tolerance comparison (`STRICT_BBOX_TOL_RATIO = 0.0025`) on every run rather than a byte diff. §6.6 prices the exit at "invalidates every content-addressed cache in the fleet", so this is written down **before** the freeze, not after |
| **DP3** | **before the vector phase, G3 scan at week 24** | F10 — which ANN library clears G3's three scans and ships pure wheels for nine cells? | Core lead + S-sec | `vector.brute` plus the 250k refusal; `vectors = "off"` remains the shipped default through v1 and the ANN Backend becomes a v2 item behind the existing entry point |
| **DP4** | **P9 week 8 = calendar week 50** | F16 — does `part` determinism hold for `python-pptx` across nine cells? `byte` is knowingly resolution-scoped; `part` is **promised** | OUT lead | the declared floor moves from `part` to a normalised-part class — **a card-visible downgrade**, never a silent one. See R-Q5 on the charter's ambiguous phrasing of this deadline |
| **DP5** | **before P9 starts, week 40** | F18 — does the `deck` Toolchain's rasterizer clear `tools/licences.toml`, and at what install weight? | S-sec | `bake` stays `unavailable` on every Target. If the tier has **zero live rows** at release, demote `bake` from a `Disposition` member nothing implements to `forbidden`, with a documented degradation |
| **DP6** | **before P8's billed passes, week 46** | F13 — what is `coverage_frac` on real corpora? The entire cost argument for deterministic-first is a projection until this runs | Graph lead | if the median outside structured corpora is below 0.2, `llm_coverage_floor` becomes per-corpus and the economics section is **rewritten rather than defended** |
| **DP7** | **before P8 freezes `op.resolve`, week 48** | F39 — does the `[75, 92)` LLM merge band earn its cost? F38 — what is the LSH block-miss rate at 0.7 / 128 perms on **document entity labels**? graphify's constants were measured on code identifiers, not "Indemnified Party" against "Indemnitee" | Graph lead | F39: **delete the band** — remove `derive.merge.llm` from the ladder and `llm_band` from the `entity_merge` stage vocabulary. It is a billed pass sitting on a free funnel and the easiest thing in the framework to remove. F38: drop `LSH_THRESHOLD` to 0.6 and accept the candidate-pair cost |
| **DP8** | **P2 exit, week 18** | F1 — the blocks-per-page envelope. Every storage, frame, segment and RSS number scales off it | Core lead | retune the 8,192-block frame target and the peak-RSS budget: the page equivalence in [`07`](07-store-and-retrieval.md) §12.5 falls from ~110,000 to ~33,000 pages, and every storage, frame and RSS projection moves with `bytes/block`. The 10M-50M **block** ceiling is unchanged: it is denominated in blocks and set by [`07`](07-store-and-retrieval.md) §12.4 item 4 — and V20-2 is refit rather than defended |
| **DP9** | **P3 exit, week 26** | F2 — does the anydoc eager marshal dominate? F32 — should `part` bytes be retained by default, and what does retention cost? | Parse lead | F2: `vendor/anydoc/FORK-TRIGGER.md` fires and the fork's first change is a single-buffer return. F32: under ~20% achieved-exact, retention becomes opt-in per corpus (`retain_parts = "never"`), which makes `verbatim` unreachable — disclosed by `corpus_card.verbatim_fraction`, not hidden |
| **DP10** | **P4 exit, week 40** | F8 — is ≤ 0.5 ms/unit scheduler overhead achievable at `synchronous=NORMAL`, and what is the p99? F6 — the real p95 of `tokens_out` for a page VLM (the two published anchors are **3.4× apart**). F7 — the real server-coalescing speedup (every GPU-hour figure is a 1.5-4× band). F26 — should the cache key include a lockfile digest? | Runtime lead | F8: group commit widens from zero-derived-row transitions to same-operator batches, weakening I20 for the case it protects — a trade made **with a number in hand**. F6: the estimator stays opt-in and the default uses `promote_frac`. F7: raise `max_batch` and reconsider the per-part `wall_ms_hard`; capacity planning stays wrong by up to 2.7× until this runs. F26: per-driver `[deps] pins` digests suffice |
| **DP11** | **P6 exit, week 40** | F11 — is `W_HEAD = 6.0` with `SPINE_DECAY = 0.6` right, or does heading propagation promote tables of contents above the sections they name? F19 — do `ow_query` and `ow_open` mis-pick, at what rate? F20 — are the budget tiers right for documents? | Retrieval lead | F11: if the nDCG curve is flat, drop `head_fts` and the lexical channel becomes one term. F19: above ~5%, `ow_open` folds into `ow_query` as a `ref` parameter and the listed set drops to three. F20: refit the config object against its fixtures rather than redesign |
| **DP12** | **the v1.0 tag, week 64** | F27 — multi-tenancy. F28 — is T3 in v1 scope? | The program | F27: **v1 is store-per-tenant**, recorded as a decision; row-level tenancy is not designed and must not be assumed. F28: T3 is v2, and the 16-bit `block_id` minting prefix already ships at shard 0 so this cannot become a migration |
| **DP13** | **two releases after v1.0** | F33 — should `omniweave` depend on `omniweave-office` at all, given it puts a compiled `abi3` wheel on the default install path? | Core lead | count platform-support issues attributable to `firecrawl-anydoc`. If material, move office behind `omniweave[office]` with a one-line remedy in the "no driver for .docx" error. **The dependency row is the only thing that changes** |
| **DP14** | **before the deck target ships, week 56** | F41 — is `[compile]`'s hard-error-on-unknown-key the right asymmetry for a Toolchain target, whose `ready` frame is produced by a different language reading the same card? | OUT lead | add one unknown `[compile]` key to the deck card and observe whether `target-runtime.ts` refuses, ignores or crashes. If a hard error there is unshippable, unknown `[compile]` keys become a hard error **on the Python side only** and the TS runtime records `CARD_KEY_UNKNOWN` into the receipt — declared, not inferred |
| **DP15** | **every release** | is any gate row past its `review_by`? | Quality lead | the build fails. There is no `--warn-only` |

Four deferred items get **no** decision point, because their answer changes nothing structural and
their fallback is already the shipped default: **F5** (`garble.score` thresholds — ships reporting
`calibration: bootstrap`), **F22** (calibration n — the badge stays dark), **F24** (the synth-OCR gap
— demoted to a smoke signal), **F30** (subsumption completeness — the linter reports only the complete
cases and says so). **F34, F35, F36 and F37** are v2 measurements and appear in §18.

## 18. Out of scope for v1, and the seam that already exists

Each row states the seam, so the item is an addition rather than a rewrite. **The rule: if a v2 item
needs a column, that column ships at v1.** There is exactly one deliberate exception and it is stated.

| v2 item | the seam that already ships at v1 | what a plan document may **not** assume |
|---|---|---|
| ANN vector index (V20-1) | the `omniweave.backends` entry point + a `backend.toml` read by the same import-free loader as a DriverCard + `VectorBackend`'s four verified contract obligations + `embed_space`'s nine-field identity, pinned at build **and** search time | that `vectors` defaults to anything but `"off"`, or that the semantic channel contributes at v1 |
| The full WAL valve at T2 (V20-1) | the valve's release condition (a full backfill), the Bulk window marker written **before** the first DDL, and the refusal-to-serve on an open marker at store open | that the valve helps mid-transaction. It cannot, which is F29's residue |
| Postgres T3 (V20-3) | the four protocols — `Store` 4, `Reader` 6, `DocSink` 11, `GraphSink` 12 = **33 methods** — are the distribution boundary, and `block_id`'s layout is `(minting_shard_ord << 48) \| sequence` with shard 0 shipping from day one | that any Operator changes. The acceptance test is `tests/store/` running unmodified against both backends with G19 green on both |
| Shard federation T4 (V20-4) | `GlobalRef = (corpus_id, block_id)` as the only cross-store reference type, plus `fusion_kind = "rank_merge"`, `shards_contributed` and `shard_unreachable`, all shipping at v1 with one shard | that absence gate `coverage_incomplete` has a global count. At federation it becomes per-shard and the verdict reports `coverage: unknown` with the shard named (F35) *(Build note, D904: cross-corpus fan-out, `CorpusSet` and `ow query --corpus a,b`, is deferred past v1.0 by a user ruling of 2026-10-19 and rides this seam; until it lands both refuse by name.)* |
| The `video` Target (V20-7) | `omniweave-target-video` ships at `[compile] implemented = false`, honoured because `[compile]` unknown keys are a hard error; `owmotion/1` is reserved; `ArtefactDeterminism` already carries `frame` | that hyperframes' mining exists. It was never written, and a construct table designed from an index page is the speculative generality D8 refuses |
| `bake` as a live disposition | `Disposition` already has the member; `[compile] bake = "available \| unavailable \| toolchain:<name>"` is the switch | that any Target implements it at v1. DP5 may demote it to `forbidden` |
| The watcher | `op.converge` ships in P4 **for exactly this reason**; `trigger.kind = "watch"` is a registered value; `auto_refresh_classes = ["free"]` and the watcher-may-not-bill policy rule already exist | that a watcher may auto-run `billed_api` work. It may never |
| Connectors beyond `acquire.fs` | `acquire/1` at Port major 1, the `unit` roster, connector cursors in `run/discover.py`, and `canonical_uri()` | that a connector holds a store handle. It receives `DriverIO` and nothing else |
| Source variety (RSS, Wikipedia, `.msg`, email) | an `acquire` + `parse` driver distribution, out of tree | that markitdown's `convert_uri` is ever called: it supports the `file:` scheme with only a netloc check and has **no timeout**. The narrow doors (`convert_local` / `convert_stream`) are the only adoptable shape |
| Tree-sitter code extraction | `omniweave-driver-code`, out of tree, an ordinary `derive/1` driver, with `derive_pass` as a **data** registry so no core change is needed | that `derive.code.treesitter` is in the shipped ladder |
| Leiden clustering | `omniweave-driver-leiden`, out of tree, named in `MAX_CLUSTER_EDGES`' refusal | that it exists. Conditional on F40 clearing G3 (DP7) |
| A rendered digit (V20-5) | `Calibrated` and `CalStatus` already carry the signal, the raw value, the bucket's empirical accuracy, its Wilson interval, `n`, `eval_set_id` and `slice_key`; `eval_calibration` already stores the buckets | that anything is calibrated at v1. Nothing is, so nothing renders a numeral, percentage, bar, colour or grade |
| The `wasm` DriverHost | `Isolation` already has the member; `DriverHost` is the executor seam; `subproc` is the shipped escalation | that F25 is answered. One reason (a pathological XLSX needing an RSS-capped worker) is a special case; two is a mechanism |
| Row-level multi-tenancy (F27) | **none, deliberately.** v1 is store-per-tenant and there is **no reserved `tenant_id` column** — reserving one would imply a design that does not exist | anything at all. The `segment.content_digest` embedding dedup is a covert channel in a shared store: two tenants observe each other's embeddings as a timing difference. Row-level tenancy forfeits the dedup, and that trade is not made here |
| Sub-page commit boundary (F29) | `MAX_BLOCKS_PER_DOC` plus a `RESOURCE_LIMIT` refusal naming the knob; generation staging already fixed the 5,000-*page* case | that a 4M-cell sheet commits incrementally. It is one transaction, and v1 **admits** it rather than refusing it — neither `MAX_BLOCKS_PER_PAGE` (4.9% headroom) nor `MAX_GRID_SLOTS` (4,000,000 is not greater than 4,000,000) fires ([03](03-document-model.md) §14 and §14.1). The admitted cost is printed, not hidden: a ~2.8 GB WAL and a ~23 s commit against `loop_lag_max_ms = 250`, a **92×** breach and `17` R-T13's own detection trigger. **F29 is a spike, not a shipped refusal.** It runs on the built 4M-cell fixture — the ~2.8 GB and ~23 s are printed estimates, not measurements — and it runs **before** §3.3's P2 migration sequence, because a pessimistic answer is a fourth span level and a change to the `work` table's unit, and 91 tables share one strictly-ordered numbering that may not be renumbered after v0.1 tags — and a fix must move **both** constants, since a page admitted by one and unbounded by the other is the shape of the failure |
| Framework adapters beyond langchain — `omniweave-haystack` (2 ew), `omniweave-llamaindex` (3), `omniweave-adk` (2) | the MCP server reaches seven of the eight frameworks with **zero** omniweave-side code (`_index/in-04-agentic.md` §2), `serialize(scope, fmt) -> (str, SpanMap)` is the primitive all three need ([03](03-document-model.md) §16.1), and [11](11-repo-layout.md) §1.2's attachment-distribution block already fixes their layer rows and their separate versioning | that MCP is a *fidelity* path. It is an *access* path: `MCPTool.invoke` returns a JSON **string**, which escapes [10](10-interfaces.md) §3.5's section layout, so haystack's adapter is the one that buys legibility rather than reach. `_index/in-04-agentic.md` §7 owns the order and the reasons four more are declined outright |
| `omniweave-docling` — the two-way `DoclingDocument` adapter and its published fidelity matrix | `charter.md`:905's commitment, `serialize()`'s `SpanMap`, and `ow store export --portable`'s plain ZIP that `unzip -l` and `jq` both read with no external tool ([07](07-store-and-retrieval.md):2560-2566) | that the fidelity matrix has an owner. It has none, no phase and no engineer-week until this row is funded — ~1 engineer-day of prose plus the adapter itself. `omniweave-docling` appears in **zero** of the 21 plan documents today and this row is the whole of the plan's commitment |
| Third-party driver index at scale (V20-6) | `omniweave-index` as a data artefact (`omniweave-index-<version>.zip` with `ZIP_DEFLATED` members + `manifest.toml` + `.sha256`), digest-installed into `$OMNIWEAVE_HOME/`, re-verified on every use, a mismatch a **permanent** failure that never triggers a fetch | that five third-party drivers exist. V10-12 requires exactly **one**, and that one is the criterion deciding whether the Port design is real |

**Not deferred — rejected permanently**, so no v2 list may reclaim them: `ord_path` (OUT edits always
write a new `artifact_gen`, so nothing patches a sealed generation and the motivating workload does
not exist); `use_lcc` (not a knob); a generic `ow_do` MCP dispatcher; a long-lived local IPC daemon or
loopback listener for parse, embed, index or schedule; a language-neutral IDL; a fifth seam; a second
error register; a second chunking; a second matcher; a second absence-gate list.

## Open questions

Numbered `R-Q` so other documents can reference them. Charter §7's F1-F41 are not restated; they are
scheduled in §17.

- **R-Q1 — Is P9 parallelisable at its allocated staffing, given W9.1 is serial ahead of every
  Target?** `omniweave_core.out` (14 ew) must be interface-complete before `omniweave-target-pptx`
  (16 ew) can build against it, and the same holds for docx and deck. P9's 60 ew fits its 20-week
  window only if W9.1 finishes by week 48 with two engineers while a third writes `constructs.toml`
  and the rule *tests* against a provisional signature. *Closes:* the W9.1 interface freeze. If
  `CompileV1`, `Finding`, `RuleSpec` and `CarrierDoc` are not frozen by week 48, P9 serialises and
  v1.0 slips roughly six weeks. *Mitigation available now:* pull W9.1 forward to week 26 — it depends
  only on P2's model — which is the single highest-leverage schedule change in this plan.
- **R-Q2 — Does v0.1 ship publicly at week 42, or only internally?** Four deferred items need
  production traffic that no fixture provides: F6 explicitly needs "one week of production traffic
  through `route_spend`", F19 and F21 need real MCP hosts, and F37 needs a real interactive session's
  VRAM residency. Shipping v0.1 publicly buys all four by week 48; not shipping leaves DP10 and DP11
  answered from fixtures. *Closes:* a decision at the P7 exit review, owned by the program. The charter
  names only "release 1", so the tiering — and therefore this question — is genuinely open.
- **R-Q3 — Is 1,250 lines per engineer-week the right rate?** It is calibrated against exactly one
  charter datapoint (the rejected Rust substrate at 4-6 engineer-weeks) and one structural argument
  (the charter is spec-complete, so most of P1-P6 is transcription plus tests). *Closes:* P1's
  actuals, which are the most spec-complete 22 ew in the program and therefore the best early
  estimator. **The intended response is to rescale every later phase by the P1 ratio, not to re-argue
  each item.** At 1.4× the program is 504 ew and v1.0 lands near week 88 under the same ramp.
- **R-Q4 — Who builds G19's fixture, and what does a mutation cost to author?** The gate owns two
  numbers — a 300-document fixture under 40 scripted mutations — and nothing in the charter says who
  constructs it or what a mutation costs with its expected delta. It is assigned here to W4.10 at 3.5
  ew including the bench harness. *Closes:* the first ten mutations. If they average more than 0.4
  engineer-day each, incremental equivalence cannot be gated at the P4 exit and G19 moves to P8, where
  the smaller 60-document / 20-step graph run has to carry the invariant alone for four months.
- **R-Q5 — Charter gap: F16's deadline is ambiguous.** "before the OUT phase's week 8" is the
  charter's only calendar anchor and reads either as week 8 of the OUT phase or as program week 8.
  Read here as **week 8 of P9, calendar week 50** (DP4), because program week 8 predates
  `omniweave_core.out` by thirty-five weeks and cannot have been meant. Flagged so a reviewer can
  overrule the reading rather than discover it.
- **R-Q6 — Charter gap: nothing prices N open stores in one process.** §1's non-goals say "not
  multi-tenant at v1" and F27 says "v1 is store-per-tenant", while `omniweave.toml [corpora]` plus the
  `corpus` argument on every Action make one MCP server process address N corpora in N `.owstore`
  files. Store-per-tenant is followed as written. But nothing states the file-descriptor multiplier,
  the per-store page-cache cost, or a ceiling on N — and P7 is where it bites, because `ow_corpora`
  enumerates exactly that registry. *Closes:* a measurement at the P7 exit of RSS and fd count against
  N ∈ {1, 8, 32, 128} open Readers, plus a documented `max_open_corpora` if one is needed. Recorded
  rather than decided, because deciding it would amend the charter.
- **R-Q7 — Is P8 really off the critical path, or does a Brief need L3?** §14 asserts that OUT does not
  depend on the graph, on the grounds that a Brief is consumed from an Answer and `artifact_cite`
  points at a Block. That holds for the pptx and docx flows. It is untested for a Brief whose
  `## sections` were authored from community reports — the deck use case. *Closes:* authoring the
  40-unit golden fixture's Brief in P9 week 2 with no L3 row present. If it cannot be done, P8 becomes
  a P9 prerequisite, the two largest phases serialise, and v1.0 slips roughly twelve weeks — which
  makes this the highest-value cheap experiment in the program.
- **R-Q8 — Where do W9.4b and W9.5b's 6 ew come from?** §12's `read_back` exposure is required work,
  not deferred work: R2 and R3 are stated over `read_back(compile(I))` and `docx` and `deck` cannot
  reach `GateStatus == passed` without a reader each. The 366-ew capacity holds 363.8 after W10.10
  and after ADR-11's four gate scripts, so the buffer covers **2.2** of the 6, not 3. The three candidate sources, in the order they cost the program least:
  block G or H absorbs it at seven and six engineers (the same weeks P9 runs, so no serialisation);
  `omniweave-target-deck` demotes to `[compile] implemented = false` like `video`, which returns
  W9.5's 7 plus W9.5b's 3 and forfeits §12's "the only proof a Toolchain target is not second-class";
  or a seventh engineer joins block I. *Closes:* the week-40 decision named in §12, which is DP5's
  week and therefore already a scheduled review. A fourth option is refused here: shipping `docx` or
  `deck` with R2 and R3 marked `not-provided` is `GateStatus != passed`, and §12's goal does not admit
  it. *(Build note, D910: closed by a user ruling of 2026-10-21, which took the second source: `omniweave-target-deck` ships at release 1 as a `compile.deck.native` card at `[compile] implemented = false` with its reason, and a driver that refuses with it, as video's does (D760). The card keeps §12's deck column -- html / owdeck/1, unit `page`, `data-ow-cite`, runtime rules, the `deck` Toolchain, `render` determinism, `structure` fidelity -- and names no reader and no table, since `parse.deck.native` and the ~90 rows are W9.5's and W9.5b's, unbuilt. `ow out targets` prints the reason. V10-9 is therefore judged on `pptx` and `docx`, and the Toolchain is post-v1.0 work.)*

## New terms

Candidates for `terminology.md` §2. None renames an existing concept; all seven are program-management
vocabulary the lock does not carry, which is why the roadmap needed to coin them.

| Term | Kind | Definition |
|---|---|---|
| **Phase** | concept | One numbered stage of the build (`M0`, `P1`-`P10`) with a goal, an engineer-week cost, a set of work items, a **freeze week**, an **exit week**, a demo, executable exit criteria and explicit non-goals. A phase ends when its exit commands exit 0, never when its calendar window closes. |
| **Milestone** | concept | A named point the program is measured against: `M0`, `v0.1`, `v1.0`. A Milestone's acceptance set lives in [00-vision.md](00-vision.md) §9; a Phase's exit criteria live in this document. Two names for two things. |
| **Forcing edge** | concept | A dependency between phases where the reverse order costs a data migration, a re-bill, or a lie that shipped — not rework. There are exactly five, `FE1`-`FE5`; every other ordering in the schedule is a headcount question. |
| **Freeze point** | concept | The named set of types, Port majors, grammars, digests and enum vocabularies that a Phase's **freeze week** makes immovable. Changing one afterwards requires a charter amendment, a `CONTRACT` bump or a `digest_recipe` bump, and the roadmap says which. Distinct from the exit week: downstream phases build against the freeze, not the exit. |
| **Skeleton marker** | concept | The `# OW-SKELETON: <phase>` comment on every deliberate fake in M0, naming the phase that **deletes** it. The semgrep rule `skeleton-marker-survived` fails the build on any marker present after the P4 exit. Skeleton code is deleted, never grown. |
| **Wrap verdict** | concept | The recorded build-versus-wrap decision for one external component, drawn from the closed set `depend \| wrap \| vendor \| reimplement \| reject`, carrying its reason and its exit strategy. Every wrap sits behind a card; every vendor has a `FORK-TRIGGER.md`; every rejection names its alternative in a `codes.toml` fix command. |
| **Decision point** | concept | A row of §17: a dated obligation to close a deferred item, with a named owner and a **pre-committed** action that executes automatically if the date passes unmeasured. Enforced by the gate-rot check, which fails the build on a gate row past its `review_by`. |
