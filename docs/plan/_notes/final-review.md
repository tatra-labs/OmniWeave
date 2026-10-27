# Final review — is the omniweave plan finished, and is it good?

**Reviewer's summary.** It is good. It is not finished. The gap between those two facts is
specific, small in volume and large in consequence: **the plan audited itself thoroughly, found
fifty-two defects and one hundred and eighty-six open items, wrote all of them down with owners,
costs and deadlines — and then shipped the catalogue instead of the corrections.** The register is
the deliverable. The fixes are not. Everything below is an instance of that one sentence.

Read alongside: [17-risks.md](../17-risks.md) §7.6 (the twelve ADRs), the
[README](../README.md)'s own Open questions, and [glossary.md](../glossary.md)'s Q1–Q5, which
between them already contain roughly two thirds of what follows. The value this review adds is the
part the plan did not find about itself.

---

## 1. Could a competent team build omniweave from this plan?

**Partly. P1 through P4 yes, starting Monday. P5 and P6 no — the router's and the retriever's
central types do not exist in 40,958 lines.**

The substrate, the CI floor, the document model, the store, the driver system and the OUT framework
are genuinely spec-complete: real dataclasses, real DDL, real SQL, real TOML, real gate scripts, and
an arithmetic that checks (`DEFAULT_WEIGHTS` sums to 5.4 and all five worked ceilings recompute
correctly; the channel budgets sum to 210 against 250; 50e6 × 660 B = 33 GB). A team could
transcribe P1 and P2 without asking a question.

Then it stops. Named exactly:

**(a) `Verdict` and `DegradeCause` have no printed field list anywhere in the plan.** Both are
`T-SCHEMA` — a *published read contract*. `schema/verdict-v1.json` is listed in the tree
([11](../11-repo-layout.md) §1) and `$ref`'d from the MCP schema
([18](../18-api-sketch.md):1504), and it is byte-diff gated by `G6`, which means a generator must
emit it from a Python definition that no document prints. `Verdict` is the output of the entire
honesty apparatus — INV-11, INV-12, the fifteen gates, `generated_share`, `fusion_kind`,
`shards_contributed`, `coverage`, `channels`, `low_confidence < 0.35`. [18](../18-api-sketch.md), the
document that exists as the coherence check, prints `verdict: Verdict` at line 534 and never prints
`Verdict`. The glossary describes it in one sentence. Every neighbouring type gets a real dataclass:
`Hit` (07:1745), `Response` (07:1762), `Coverage` (07:2773), `Snapshot` (07:2239), `Filters`
(07:1394), `Narrowing` (07:1408), `StepResult` (08:201), `Roots`, `RunContext`, `Receipt`,
`AssetLedger`, `RuleSpec`, `CarrierDoc`, `UnitRef`, `ArtifactRef`, `Catalog`, `Spend`. The two that
carry the product's central claim do not.

**(b) The fifteen absence gates have no normative table in any plan document.** The glossary found
this itself (Q3) and it is the sharpest hole in the plan. INV-11 is the most-cited invariant in the
corpus (17 occurrences of "fifteen absence gates" across 10 documents). Its specification lives in
the charter's prose plus a **worked example** at [07](../07-store-and-retrieval.md) §6.6 — an
illustration, not a contract. There is no precedence-ordered table, no per-gate read source, no
per-gate predicate, and no gate→`Diag` mapping. Meanwhile V01-8 requires "one fixture per gate" (15)
and [13](../13-quality.md) defines its `Injector` set as "**one per `Diag` code in
`ABSENCE_BLOCKING_DIAGS`**" — thirteen — against which `degradation_detection == 1.000` is a **hard**
gate. Fifteen and thirteen are not reconciled anywhere.

**(c) `route_decision` has no DDL anywhere in the plan.** It is FK'd from `block.decision_id`
([03](../03-document-model.md):2248), it carries RT8's generated `BEFORE INSERT` monotone-escalation
trigger, it holds the read set that makes replay byte-for-byte, and it is the row written *before any
driver runs*. [05](../05-ingest-and-routing.md), which owns the router, contains exactly **one**
`CREATE TABLE` in 2,784 lines, and it is `route_signal`. [07](../07-store-and-retrieval.md) §3 lists
`0004_runtime.sql` as creating `route_*` — a glob. Same for `route_unit_decision`, `route_spend`,
`route_threshold`, `route_scoreboard`.

**(d) Ten load-bearing types are named across documents and defined in none.** `Evidence` (the flat
versioned record `evaluate()` is pure over — INV-14's whole subject), `RouteDecision`, `SignalSpec`
(the registry `ow route lint` resolves every policy key against), `Degradation`, `Plan`, `ILBundle`,
`Unit`, `CheckValue`, `Config`, `CancelToken`. Four of these — `ILBundle`, `Plan`, `Unit`,
`CheckValue` — the plan already flags as defect `18#2` under ADR-1. The other six it does not.

**(e) Fifty-one of the ninety-one tables have no DDL** (40 `CREATE TABLE` statements printed against
91 claimed). This one is honest rather than hidden: every table is *named* in the migration
inventory, the column conventions are stated framework-wide (`state=0`, `restriction_bits NOT NULL`
with no default, `enum_val`, partial indexes, no inline `CHECK` with a subquery), and
[16](../16-roadmap.md) §15.1 prices it at 0.5 ed/table = 45.5 ed. It is transcription, not design.

**(f) The twelve ADRs.** All unwritten, all on the v0.1 critical path (path **P6**), all unpriced
(`RK-Q6`), with nothing that fails when one is missing. Three change shipped behaviour: **ADR-3**
states that as printed, `ow doctor` **fails on a fresh install**, `G18` fails and `ow route lint`
fails; **ADR-4** states the flagship shipped routing policy has nine missing `on_unknown`
declarations (one silently disabling the furniture guard on the PDF path), four `GATE` rules that
cannot co-fire under first-match-wins, and **two newline-spanning inline tables — which is not valid
TOML and therefore fails `G27` against the plan's own gate**; **ADR-5** could change a shipped type.

**Verdict on buildability.** A team of seven can start P1 immediately and will be productive for
roughly six months. The wall is at P5/P6 and it is about two engineer-weeks of type-writing plus the
twelve ADRs — small work, but it is *design* work, and the plan's premise is that design is done.

---

## 2. The weakest document

**[05-ingest-and-routing.md](../05-ingest-and-routing.md).** It is the weakest because it owns the
one thing the plan calls irreplaceable, and it is the only document whose central artefacts fail
their own checks.

- Its flagship deliverable is §4.4, the complete shipped policy — ~500 lines of real TOML, and the
  best single artefact in the plan by ambition. **It does not lint against the grammar printed 200
  lines above it.** Nine missing `on_unknown` declarations on rules reading nullable keys (RT7
  makes that `OW-P-004`); four `GATE` rules that cannot co-fire; two inline tables spanning a
  newline, which the document's own header comment forbids in capitals ("`;` is not a TOML
  separator, an inline table may not span a newline, **and this file gates money**") and which
  `G27` fails on.
- It prints **none** of its own types: not `Evidence`, not `RouteDecision`, not `SignalSpec`, not
  the `route_decision` DDL. It specifies the *grammar* exhaustively and the *data* not at all. A
  reader can write `ow route lint` and cannot write the record it lints against.
- Ten of its twelve day-one escalation signals are unmeasured; the reservation model rests on F6,
  whose two published anchors are **3.4× apart**; the whole GPU cost band is 1.5×–4× pending F7.
  The document says all of this, which is honest, and it means the router ships tuned to nothing.

**Runner-up: [16-roadmap.md](../16-roadmap.md)**, whose central artefact — the schedule — is
knowably wrong in its first paragraph and in its estimation basis. It states "all 27 `G` gates and
all 23 `Q-G` gates green" (the plan corrects 23→27 in ADR-11); §15.1 basis rule 3 still computes
`27 + 23 = 50 gates ⇒ 10 ew`; exclusion 7 prices the F-backlog at `41 × 0.3 = 12.3 ew` against
[17](../17-risks.md) §7.2's itemised **20.3 ew**, an 8 ew gap against a **6 ew total program
buffer** (1.6%); and it excludes from its 360 ew both that backlog and the twelve ADRs the plan
places on the v0.1 critical path. **A schedule that omits its own critical path is not a schedule.**

**Strongest document, for contrast: [glossary.md](../glossary.md).** 824 rows, a prefix map that
prevents register collisions, and five open questions that are the only *original* defect-finding in
the whole final pass — including Q3 above and Q1, which caught a view (`ow_segment_head`) that
survives in `_notes/.snapshots/s5-round3/` and was dropped in revision. The glossary audited the
plan better than the audit did.

---

## 3. What subject is absent entirely

**1. Free-threaded CPython (PEP 703) and the 3.14+ interpreter.** Zero occurrences of
free-threading, nogil, `3.13t`, `3.14t`, or subinterpreters (PEP 734) in 40,958 lines. The CI matrix
is `{ubuntu, macos, windows} × {3.11, 3.12, 3.13}` — already a year stale, and two years stale at
v1.0 (week 64). This is not cosmetic. The entire concurrency architecture is GIL-shaped: S1's
`max_inproc = 2`, F2's whole instrument (the **GIL-held fraction**), one-thread-per-connection,
`MAX_AUTO_PARALLEL = 96`, and subprocess-per-driver as the isolation tier because in-process
parallelism is not available. Free-threading changes every one of those trades. And the load-bearing
consequence nobody wrote down: **`firecrawl-anydoc` is an `abi3` wheel, and `abi3` does not exist on
free-threaded builds** — so `omniweave-office`, the framework's only compiled dependency and the
single first-party edge out of `omniweave` (F33), structurally cannot load on a free-threaded
interpreter. `vendor/anydoc/FORK-TRIGGER.md` has two named clauses and this is neither.

**2. Accessibility, in both directions.** Not one word about alt text, reading order for assistive
technology, table header markup, PDF/UA or WCAG. Two concrete consequences:

- **IN:** the `asset` table ([03](../03-document-model.md):1980) carries `media_type`, `origin_part`,
  `sha256`, `width`, `height`, `licence`, `spdx`, `source_url` and `restriction_bits` — and **no
  description field**. `block_asset.role` is `image|thumbnail|source_crop|ole|chart_data|bake|font`
  with no `alt`. So an author's `<wp:docPr descr>`, `<a:cNvPr descr>` or PDF `/Alt` is **destroyed at
  omniweave's own parse seam** — which is the exact L-1..L-5 complaint the project was founded on,
  committed by the project. The framework then spends VLM money on a `caption` lane
  (`decode.admit-caption-lane`, reason `uncaptioned-figure`) to *invent* a caption for the figure
  whose author-written description it just discarded. That is AP-1 in miniature.
- **OUT:** the framework generates PPTX, DOCX and decks for compliance officers and legal teams in
  regulated markets. It has a `ConstructTable`, a `RulePack` of one-function-per-file predicates,
  orthogonal `Severity`/`Provenance`, and a ten-value `GateStatus` — precisely the machinery an
  accessibility rule pack would live in. There is no accessibility construct, rule, finding or
  disposition. Under EN 301 549, the European Accessibility Act and Section 508 this is a legal
  exposure for the stated users, and [14](../14-security.md)'s threat register and licence register
  carry neither.

**3. User-facing documentation.** [16](../16-roadmap.md) §15.1 exclusion 7: "Documentation beyond
generated artefacts is excluded." The entire documentation deliverable is the seven generated
agent-facing artefacts plus `llms.txt`. No tutorial, no cookbook, no migration guide from
docling/LangChain, no operator runbook beyond [15](../15-observability.md)'s five, and **no budget
for any**. The adoption argument is a 250 MB install, ~130 CLI verbs, 91 tables, a `driver.toml`
grammar and a `Brief` format; V01-15 gates `first_answer_seconds ≤ 600`; and there is no document a
human reads to get there.

**4. Ecosystem governance, for a design whose success criterion is third-party drivers.** V10-12
makes an externally-authored driver a **v1.0 release criterion**; V20-6 wants five across three
Ports; `omniweave-index` is a static card-stub index installed by digest. There is no admission
process, no published review rubric for listing, no revocation path other than a framework-shipped
tombstone in a core release, and no answer to who operates the index or who pays for it. `K-12`
names "the ecosystem investment" as a kill criterion for a thing with no operating model.

**5. Message localisation.** `codes.toml` is one register of English messages and fix commands with
no locale axis, in a framework whose `Filters.lang`, five-script normalisation and multi-script
`garble.score` calibration (F5) all assume a multilingual corpus.

---

## 4. Where the plan is still writing prose instead of deciding

This is the plan's **strongest** dimension. Almost every paragraph carries a file, a line and a
number, and the hedging vocabulary is essentially absent — a scan for `TBD`, `TODO`, "to be
determined", "we might", "should probably", "it is worth noting", "for now", "not yet specified"
returns nothing substantive across all nineteen documents. The real offenders are a narrower and
more interesting class: **decisions named as owed to another document that never took delivery.**

**Worst offender — [00-vision.md](../00-vision.md) §8, on the hazard the vision itself calls the
framework's worst:**

> "One mechanism does not exist, and this document is where the gap is recorded rather than
> discovered. `Filters` narrows on `doc_keys`, `uri_prefix`, `formats`, `kinds`, `layers`, `pages`,
> `sec_path_prefix`, `lang`, `min_trust`, `min_quote`, `deny_restriction_bits` and `gen` — and on
> nothing that names a `Method`. A caller therefore cannot say 'answer from source documents only'
> ... **Extends the charter:** [07](../07-store-and-retrieval.md) owns the resolution, the scope
> commitment here is that one must exist by v1.0"

07 did not own it. `Filters` at [07](../07-store-and-retrieval.md):1394 carries **the same twelve
fields**; the narrowing SQL at :1417 has no `method` predicate; 07's Open questions do not list it;
07's New terms do not carry `generated_share`. V10-17 is therefore a **v1.0 release criterion with
no implementing specification in any document** — while [13](../13-quality.md) §10 has already
written its test and the glossary has already defined its metric. "Document X owns the resolution"
is a decision only on the day X ships it.

**Second — [01-principles.md](../01-principles.md) §1c, the collision rule:**

> "**The rule for a collision that does not resolve.** An unresolvable collision is a charter
> defect, not a licence to choose. Record it in this document's Open questions, flagged, and follow
> **the invariant whose violation is unrecoverable**"

Read plainly: when the constitution contradicts itself, the implementer picks a half, guided by an
adjective. It is shaped as a rule and is a deferral. It becomes a rule the day
`tools/invariants.toml` carries a recoverability class per row — which the same document's Open
question 3 declines to build ("undecidable in general. Ship the two decidable cases and leave the
rest to `R`"), on a register whose own ladder rule 1 says **no invariant may rest on `R` alone**.

**Third — [17-risks.md](../17-risks.md) §9's own confession, still true:**

> "This is the one row in this table whose trigger has **no measurement in front of it** — it is a
> decision that should have been made already."

It is still not made. A generated artefact can carry an external reference or active content, reach
`GateStatus.passed`, and ship carrying omniweave's provenance markers (`R-O10`).

**Fourth — structural padding.** Nineteen "In one paragraph" openers, nineteen "What this document
owns and does not restate" sections, nineteen "New terms" tables: roughly 900 lines that decide
nothing. The glossary *is* the union of the New-terms tables and is better than any of them;
README §3.1 *is* the openers, in one table, in one place.

**Fifth — measured duplication.** The same evidence is recited across the corpus rather than cited:
"4.3% of distinct edges" in **9 documents**; "fifteen absence gates" in **10**; the Datalab licence
md5 `e1f69b64…` in **6**; "4.4 ms" 16 times in 6; "660 B" 16 times in 7. Each restatement is a
drift site, which is `A18`'s own point — and `A18` is already false in fifty-two recorded places.

---

## 5. Does the plan meet its own stated bar?

Its bar is [00-vision.md](../00-vision.md) §9 plus the charter's §8 rejection list. Scored against
that, not against a generic one.

| dimension | score | reason |
|---|--:|---|
| **Usage** | **6/10** | The four-tool front door, the mechanical L1–L4 listing rule, the measured 1,900-token baseline, typed absence states and `ow_add` returning a *pending cost* rather than a document are the best agent-surface design in the mined collection. Against that, the shipped first run gives four of five channels; `verbatim` is unreachable across the whole office path; **no confidence renders a digit at v1.0**; `bake` is `unavailable`; `video` is `implemented = false`; `doc_acc` on `fields/*` is gated at **0.20**; ADR-3 says `ow doctor` **fails on a fresh install** as printed; and there is no human documentation at all. The honest description of the v1.0 first-run experience is: a framework that correctly announces its limitations and does less than the user expected. |
| **Functionality** | **7/10** | IN, L2, L4 and the driver system are complete enough to build. The loop closing through `read_back` as an ordinary `parse/1` driver is a genuinely new idea — nothing in the twenty-two repositories has it. But the loop's own guard (the `Method` filter) does not exist, `Verdict` has no shape, the fifteen gates have no normative table, HTML and email sit in the charter's **first sentence** with no producer, and audio/video sit in the project's purpose and in no document. |
| **Structure** | **8/10** | Fourteen distributions, one pivot, four seams and a written rule against a fifth, five Ports with two deliberate non-Ports, a dependency gate that **reads entry points** rather than trusting a hand-maintained list, and one home per fact enforced bidirectionally. Two off because the lock **cannot run** (`G27(c)` blocked on ~110 missing rows), `G27(d)` is claimed by two documents, and three registers carry two live cardinalities each. |
| **Engineering quality** | **8/10** | Six enforcement classes with a ladder and an independence test; two independent enforcers per invariant; every mechanism traced to a file and a line in a real repository; `take(N+1)`-then-check; generated triggers with **bidirectional** CI parity; a crash matrix at every statement boundary in `Store.complete()`; RNG-free statistics; Cassettes at exactly two channels *because those are provably the only two*. The arithmetic holds under checking. Two off for the types named and not defined — the one place the discipline lapsed, and it lapsed on the most load-bearing output in the framework. |
| **Scalability** | **5/10** | T1 designed. T2 conditional on F9 and F10, neither run. T3 is 4 protocols / 33 methods with no implementation and an open scope question. T4 is a name plus a disclosed rank-merge bias. **Every number above 1M blocks scales off F1, which is unmeasured**, and the plan states plainly that at ~300 blocks/page T2 arrives at 5M rather than 50M — an order of magnitude on the headline capacity claim. The single-writer design has a known unbounded case (F29: a 4M-cell sheet is one transaction the WAL valve cannot help mid-transaction) whose shipped answer is a refusal. Honest, not solved. |
| **Efficiency** | **7/10** | The five-layer cache with `call` caching the *driver's raw response*; deterministic-first ordered on a coverage ledger by `(cost_rank, phase)` so a third party's free extractor preempts every paid one with no core change; an escalation ladder where a clean born-digital page computes **zero** `LOCAL_COMPUTE` signals, asserted by **exact** counters where ±1 fails; a seven-unit physical `Spend` no driver may price. This is the best design in the plan and the reason the thing might be affordable. Three off because the keystone is **F13** (`coverage_frac` on real corpora, unmeasured, pre-committed fallback: "the economics section is **rewritten rather than defended**"), the GPU figures are a 1.5×–4× band pending F7, and F6's two anchors are 3.4× apart. |

**Against the charter's §8 rejection list**, the plan is clean on 20 of 22 items and violates two of
its own: **item 19** ("a second home for one config key, or a second name for one column") — which
is `11#OQ-9`, `SCHEMA` in three homes, and it gets its own ADR precisely because it is a
rejection-criterion violation; and **item 21** ("prints a TOML or JSON block that does not parse") —
the two newline-spanning inline tables in the shipped routing policy.

---

## 6. What I would cut

Ordered by bytes recovered per unit of regret.

1. **`_notes/.snapshots/` — 218,221 lines.** Eight full generations of superseded drafts, **5.1× the
   size of the deliverable**. Keep `s6-final` if a diff is ever wanted. Delete the other seven.
2. **The assembly leftovers — 3,197 lines.** `.p1.md`–`.p8.md` are fragments of
   [17-risks](../17-risks.md); `.ow12/part1-4.md` are fragments of
   [12-performance](../12-performance.md). Build scaffolding sitting beside the product.
3. **`_notes/mine-*.md` — 27,433 lines.** They did their job. Every fact worth keeping is now cited
   in a plan document *with its file and line*, which is strictly better than the mining note. Six
   files of 2.7k–7.4k lines are a re-reading cost nobody will pay.
4. **The nineteen "In one paragraph" openers and nineteen "New terms" tables — ~900 lines.**
   Superseded by the glossary and README §3.1, both of which already are the union.
5. **`omniweave-target-video`.** A distribution shipping `[compile] implemented = false`, whose
   ConstructTable would be designed from an index page because the hyperframes mining was never
   written, whose determinism is "`frame` when it lands", and which the plan's own cut order
   (`R-A1`) names **first**. Ship the seam, not the wheel. The plan already agrees and ships it
   anyway — that is the definition of content that earns nothing.
6. **The `[75, 92)` LLM merge band.** F39's pre-committed answer is "**delete the band**"; D7's own
   proposal was to delete it; it is a billed pass sitting on top of a free nine-guard funnel and the
   plan calls it "the easiest thing in the framework to remove." It is still in the ladder and in the
   `entity_merge` stage `CHECK`. Delete it now and save the 2 ed measurement.
7. **`block_tri`, the trigram FTS5 table.** One optional table behind one config flag, at tier 35
   inside the `exact` channel, contributing membership and never a score, one `IndexCaps` bit — on a
   plan that already refuses a `prefix` index for 2.6× the bytes. Zero measured demand.
8. **The `F42`–`F169` block-allocation table** ([17](../17-risks.md) §7.7). It reserves 128 numbers
   across thirteen documents to prevent a collision that happened once, and its own concluding
   sentence is "a new document should use a local prefix, **not a block**." Keep the sentence.

---

## 7. Is the plan internally consistent now? Contradictions that survived the audit

All ten verified in-tree during this review. All still live.

1. **`block_cite` — the charter still contradicts every document written against it.** Charter §6.1's
   token table (`charter.md`:8343) writes the unique index as `block_cite(doc_ord, gen, cite)`. All
   nineteen plan documents *and* the terminology lock write `UNIQUE(doc_ord, cite)` with **no
   `gen`**. The binding upstream document disagrees with its own downstream on the one index that
   makes a shipped citation durable. Recorded as `02#2`, ADR-6. Unfixed.

2. **The `Q-G` count, in the roadmap's first paragraph.** [16](../16-roadmap.md):11 — "all 27 `G`
   gates and all 23 `Q-G` gates green". [17](../17-risks.md) `R-A1` — twenty-seven. ADR-11 states
   the count moves 23→27 and that doing so "corrects [roadmap]'s `27 + 23 = 50` gate arithmetic by
   four engineer-days" — and [16](../16-roadmap.md) §15.1 basis rule 3 **still computes**
   `27 + 23 = 50 gates ⇒ 10 ew`. The README declines to quote the number, which is honest and is not
   a fix.

3. **The invariant count, stated four ways.** [01](../01-principles.md) defines 25; charter §2 opens
   "Twenty properties"; [11](../11-repo-layout.md) §1.8 says `docs/ARCHITECTURE.md` carries "the
   twenty invariants"; [17](../17-risks.md) `R-A1` counts "twenty invariants plus five pending
   principles". At most one can be what `G27(d)` checks, and `tools/invariants.toml` — the register
   that would settle it — is printed with **two of twenty-five rows**.

4. **`Degradation.kind`: sixteen members versus twenty-seven.** The charter fixes a closed
   sixteen-member literal and states "**ONE** Degradation enum for the whole framework. D6, D9 and
   D10 extend the `kind` literal; they do not invent a parallel type."
   [15](../15-observability.md)'s **first** open question lists eleven missing members — ten of which
   *written plan documents already construct on disk*: `no_driver`, `store_busy`, `rung_ceiling`,
   `stat_stale`, `pushdown_unavailable`, `discovery_slow`, `segment_lift_capped`, `hub_capped`,
   `grant_missing`, `vector_scan_over_budget`. Every one is a downgrade a document says the framework
   emits and the type cannot hold. ADR-3. Unfixed.

5. **`generated_share` / the `Method` filter — a v1.0 release criterion with no owner in practice.**
   V10-17 ([00](../00-vision.md)) requires it. [13](../13-quality.md) §10 tests it. The glossary
   defines it. [07](../07-store-and-retrieval.md), named as owner, has it in **none** of: `Filters`,
   the narrowing SQL, its Open questions, its New terms. See §4 above.

6. **Fifteen absence gates versus thirteen Injectors.** 15 gates (charter, INV-11, V01-8 "one fixture
   per gate"); 13 Injectors, defined as "one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`", against
   which `degradation_detection == 1.000` is a **hard** gate. The mapping that reconciles them is in
   no document — and the fifteen gates have no normative table at all (glossary Q3).

7. **The ADR directory has two addresses and does not exist.** [11](../11-repo-layout.md) §1.8 and
   its `CODEOWNERS` say `docs/adr/NNNN-<slug>.md`; [01](../01-principles.md) and
   [17](../17-risks.md) `R-O9` say `_plan/adr/`. **The README asserts "`_plan/adr/` exists and is
   empty" — it does not exist at all** (243 files in `_plan/`; no `adr/`). And
   `charter_defects_open` is a ratchet in `gates.risk_register` that counts files in one of those
   two directories.

8. **The measurement backlog versus the schedule buffer.** [17](../17-risks.md) §7.2 itemises
   F1–F41 at **101.5 ed = 20.3 ew**. [16](../16-roadmap.md) exclusion 7 prices the same set at
   `41 × 0.3 = 12.3 ew`. **Both exclude it from the 360 ew entirely.** The gap is 8 ew against a 6 ew
   total program buffer, and `RK-Q7` — the one-sentence correction owed — is unwritten.

9. **The README's own arithmetic.** "Nineteen specification documents, **40,072 lines**." Actual sum
   of `00`–`18`: **40,958**. Off by 886. The README's Open question 5 already says this count "is a
   fact about a directory, not a register" with "no enforcer" — so the plan **predicted the error,
   printed it in its opening paragraph, and left it there**.

10. **INV-24 versus where the plan lives.** "Every artefact omniweave writes into a repository ... is
    byte-reproducible from inputs the artefact itself names." The **entire `_plan/` directory** — 243
    files, 28 MB, including the binding charter and the binding terminology lock — is gitignored
    (`.gitignore:3: _plan/`). The constitution of a framework whose whole thesis is provenance has no
    history, no diff and no provenance of its own.

**One genuinely blocking item, named by the plan and worth repeating here.**
[14-security.md](../14-security.md) Open question 1: `pdf-inspector` is Firecrawl's own crate, reached
from `anydoc/src/formats/pdf.rs:9`, **on the default install line**, with an **unknown SPDX** and
unaudited limit discipline — "the one dependency that could reintroduce an unbounded parser behind an
otherwise-bounded facade." Marked **"Blocking for release 1."** It is the only item in the plan
carrying that phrase, and it is a 1 ed read.

---

## 8. Prioritized remaining work

Grouped by whether it blocks writing code, blocks shipping, or blocks trusting a number.

### Tier 0 — blocks writing P5/P6 code (~2 engineer-weeks of specification)

1. **Print `Verdict` and `DegradeCause` as dataclasses** in [07](../07-store-and-retrieval.md) §6,
   with the fields the worked examples already imply plus `generated_share`, `fusion_kind`,
   `shards_contributed`, `coverage`, `channels`, `gates`, `scorer_version`, `space`. Nothing can
   generate `verdict-v1.json` until this exists, and `G6` gates it.
2. **Write the fifteen-gate normative table** in [07](../07-store-and-retrieval.md) §6: gate number,
   name, precedence rationale, read source, predicate, forced state, and its fixture. Then reconcile
   15 against [13](../13-quality.md)'s 13 Injectors — either two more Injectors or an explicit
   statement of which gates are not `Diag`-driven. (glossary Q3.)
3. **Print the `route_*` DDL** — `route_decision`, `route_unit_decision`, `route_spend`,
   `route_threshold`, `route_scoreboard` — in [05](../05-ingest-and-routing.md), plus RT8's trigger
   text. `block.decision_id` already FKs to a table that does not exist on paper.
4. **Print `Evidence`, `RouteDecision` and `SignalSpec`** in [05](../05-ingest-and-routing.md).
   `evaluate()`'s purity claim (INV-14) is unwritable without them.
5. **Print `Degradation`** in [15](../15-observability.md) with the full 27-member `kind` literal, and
   amend the charter's sixteen in the same change (ADR-3).
6. **Print `Plan`, `ILBundle`, `Unit`, `CheckValue`** in [09](../09-generation.md) (already `18#2`,
   ADR-1), and `Config` / `CancelToken` in [02](../02-architecture.md) / [08](../08-runtime.md).
7. **Add the `Method` predicate to `Filters`** and `generated_share` to `Verdict` in
   [07](../07-store-and-retrieval.md), discharging V10-17 and `00#V-Q5`.

### Tier 1 — the twelve ADRs, in the plan's own priority order

8. **ADR-1** (the terminology lock bulk pass — ~110 rows, five one-name-two-types collisions, and
   the negation-blindness fix). Unblocks `G27(c)`, which unblocks the most other work.
9. **ADR-3** (the shipped configuration, so `ow doctor` passes on a fresh install). V01-15 measures
   it; as printed it fails.
10. **ADR-4** (the shipped policy's mechanical defects — nine `on_unknown`, two unparseable TOML
    blocks, four dead `GATE` rules). Run `G27` over the plan's own TOML blocks and fix what it
    reports; the gate already exists.
11. **ADR-2** (INV-21..25's amendment, the two enforcer-column defects, the `G27(d)` double claim,
    and the gate cardinality). Settles the invariant count and the `Q-G` count together.
12. **ADR-5** (INV-10's three normalisers, the `quote` ladder's middle rung, `wirekeys.toml`, and who
    inserts a `part` row). The one whose outcome could change a shipped type — do it before P2 freezes.
13. **ADR-6, ADR-7, ADR-8, ADR-9, ADR-10, ADR-11, ADR-12** — the remaining seven. **Price them
    first** (`RK-Q6`); twelve unpriced ADRs on the v0.1 critical path is the largest unmodelled item
    in the schedule.
14. **Create `_plan/adr/`** (or `docs/adr/` — pick one; two documents disagree and the ratchet counts
    files in one of them), with a three-heading template. The README currently asserts a directory
    that does not exist.

### Tier 2 — absent subjects that need a decision, not a measurement

15. **Decide the Python floor and ceiling, in writing.** Add 3.14 to the matrix or state why not.
    Then answer the question nobody asked: **`abi3` wheels do not load on free-threaded builds**, so
    either `omniweave-office` gains a third fork-trigger clause, or free-threading is a declared
    non-target with the reason stated, or the office path is `[office]`-extra'd (which is F33's
    pre-committed fallback arriving for a second reason).
16. **Decide accessibility.** Minimum viable: an `alt`/`descr` column on `asset` (or an `alt` role on
    `block_asset`) so the parse seam stops destroying it; an accessibility section in the
    `ConstructTable` grammar; and one blocking `Finding` class for a generated artefact with an
    undescribed image. This is a `Severity`/`Provenance` pair and a construct row, not a subsystem —
    and it closes a legal exposure for the plan's own named users.
17. **Decide the documentation deliverable and budget it,** or state in
    [00](../00-vision.md) §5 that omniweave ships no human documentation as a non-goal. The current
    position — excluded from the estimate, unmentioned in the vision — is neither.
18. **Decide who operates `omniweave-index` and how a driver gets listed,** since V10-12 makes an
    external driver a v1.0 gate and `K-12` makes the ecosystem a kill criterion.
19. **Close `R-O10`.** The plan already says this "should have been made already": promote
    `portability`'s external-reference row to a blocking `Finding` for untrusted-provenance corpora,
    and add one `sandbox` fixture per carrier.

### Tier 3 — measurements standing in front of v0.1 (27 ed)

20. **F14 — the `e`/`c`/`k` sigil emission accuracy. 2 ed, ~$40.** Do it first. It is the only item in
    the plan whose contingency becomes *unavailable* after release: a sigil in a delivered answer is
    permanent.
21. **F1 — blocks per page. 3 ed.** Nine claims repoint at once, and it decides whether T2 is 50M
    blocks or 5M.
22. **F19 — the 30-task `bench/serve/` harness with its control arm. 8 ed.** The single highest-value
    instrument in the plan: it serves F19, `source_reread_rate` (the definition of failure),
    `generated_share`, `task_accuracy` and `R-E2`. [17](../17-risks.md) argues for v0.1 against
    [16](../16-roadmap.md)'s week 40; take 17's side.
23. **F8 (3 ed), F2 (2 ed), F4 (1 ed)** — the scheduler p95 premise, the anydoc marshal, the layout
    detector's licence.
24. **F31 (3 ed) and F16 (2 ed)** before their ordering conditions — the golden-suite freeze and the
    OUT phase's week 8. Running these late is not a delay, it is a worse outcome.
25. **F9 and F10 (3 ed)** before the vector phase starts.
26. **`pdf-inspector`'s licence and limits. 1 ed.** The plan's only "Blocking for release 1."

### Tier 4 — register hygiene

27. **Reconcile [16](../16-roadmap.md) exclusion 7 with [17](../17-risks.md) §7.2** — one sentence
    replacing the uniform 0.3 ew with the itemisation (`RK-Q7`) — and then say out loud what the
    itemisation implies: at a 1.6% buffer, **several deferred items will ship on their fallback
    rather than on a measurement**. [17](../17-risks.md) already says this; the roadmap does not.
28. **Fix the README's line count and its `_plan/adr/` claim**, and extend `G27(d)`'s link check to
    assert the §3.1 row set equals the `docs/plan/` file set in both directions — the mechanism the
    README's own Open question 5 specifies and nobody built.
29. **Delete the cut list in §6** — ~249,000 lines of snapshots, mining notes and assembly
    scaffolding, so that the 42,632 lines that matter are what a reader finds.
30. **Put `_plan/` under version control.** A binding charter with no history is the one artefact in
    this project that violates its own INV-24.

---

## 9. The one-paragraph verdict

This is the most disciplined design document set I have reviewed, and its discipline is why its
failure mode is so precisely locatable. Every mechanism is traced to a file and a line in a real
repository; every number carries a measurement or an admission that it is derived; every refusal is
named for its hazard; the arithmetic survives independent checking; and the plan's honesty machinery
is real enough that the plan caught most of its own defects. That last property is also the trap. A
plan that can enumerate fifty-two contradictions in itself, group them into twelve change sets, price
their owners and set their deadlines has demonstrated that it knows exactly what is wrong — and then
it stopped, because cataloguing is the same activity as writing and fixing is not. **Twelve ADRs, all
on the v0.1 critical path, all unpriced, in a directory that does not exist.** Under it sit two
specification holes that no amount of register discipline substitutes for: the framework's central
output type has no shape, and its most-cited invariant has no normative table. Fix those two and
write the twelve, and this is a plan a competent team builds. Ship it as it stands and the first
thing that happens is that P6 stops and someone designs `Verdict` in a pull request — which is
exactly the outcome forty thousand lines of specification were written to prevent.
