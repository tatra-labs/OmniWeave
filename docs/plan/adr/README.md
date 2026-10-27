# ADRs — the twelve amendment decisions the audit produced

This directory holds one document per **decision class** raised by the plan's own audit. It is the
backlog [17-risks.md](../17-risks.md) §7.6 names, priced and ordered here for the first time —
`RK-Q6` ([17](../17-risks.md) §Open questions, item 6) records that the pricing had never been done,
and §9's "The ADR process itself" row records that this directory had "no template, no register
file, no numbering authority and no owner".

## 1. Why the directory is `_plan/adr/` and not `docs/adr/`

[final-review.md](../_notes/final-review.md) §8 item 14 left the path open because two documents
disagree. They are:

| document | claim | locus |
|---|---|---|
| [11-repo-layout.md](../11-repo-layout.md) | ADRs ship at `docs/adr/NNNN-<slug>.md`, a **sibling** of `docs/plan/`, with `/docs/adr/` as a `CODEOWNERS` entry owned by `@omniweave/contract` | §1.8's tree; §8.4's `CODEOWNERS` block |
| [17-risks.md](../17-risks.md) | ADRs live at `_plan/adr/` | `R-O9`'s trigger; §New terms' `charter_defects_open`; §9's "The ADR process itself" row |

[01-principles.md](../01-principles.md) §Open questions item 1 and [glossary.md](../glossary.md)'s
`charter_defects_open` row both side with `17`, so the split is three documents to one.

**The tiebreak is the ratchet, not the count.** `R-O9`'s trigger fires on
"`charter_defects_open`† in `tools/risks.toml` exceeding the count of ADRs in **`_plan/adr/`** by
more than 10", and the `charter_defects_open` definition in both [17](../17-risks.md) §New terms and
[glossary.md](../glossary.md) says the same. A ratchet that counts files in a directory is wrong the
moment the directory moves, and it is the only one of the four claims with a mechanical consumer.
**Followed: [17-risks.md](../17-risks.md). `_plan/adr/` is the path.**

**Consequence recorded, not applied here.** [11-repo-layout.md](../11-repo-layout.md) §1.8 places the
nineteen design documents at `docs/plan/`, so this directory's shipped home is `docs/plan/adr/`, not
`docs/adr/`. Two lines in `11` are therefore now wrong and a later stage owns the edit: §1.8's tree
entry (`adr/NNNN-<slug>.md`, which must move inside `plan/`) and §8.4's `CODEOWNERS` line
(`/docs/adr/` becomes `/docs/plan/adr/`). The `@omniweave/contract` ownership and the two-approval
rule are unchanged and are not reopened by this choice.

## 2. Why there is no ADR for D1-D10

Stage 7 **deliberately wrote no ADR** for the ten original architecture decisions. Their context,
their spec, their rejected alternatives and their consequences already live in
[`../_notes/rulings/`](../_notes/rulings/), at 51-107 KB each — more detail than an ADR carries, in
the same shape. A reader looking for the founding architecture wants those files, not this directory:

| ruling | subject |
|---|---|
| [D1-substrate.md](../_notes/rulings/D1-substrate.md) | the substrate, the distribution split, the gate harness |
| [D2-docmodel.md](../_notes/rulings/D2-docmodel.md) | the document model, `Locus`, `origin_span`, INV-10 |
| [D3-drivers.md](../_notes/rulings/D3-drivers.md) | the driver system, ports, `resolve()` |
| [D4-router.md](../_notes/rulings/D4-router.md) | the router, `Evidence`, the policy grammar, the rungs |
| [D5-store.md](../_notes/rulings/D5-store.md) | the store, the Channels, `fuse()`/`ceiling()` |
| [D6-runtime.md](../_notes/rulings/D6-runtime.md) | the Supervisor, `work`, budget, caches |
| [D7-structure.md](../_notes/rulings/D7-structure.md) | structure extraction, Segments, the knowledge graph |
| [D8-out.md](../_notes/rulings/D8-out.md) | the OUT direction, the compilers, the receipt |
| [D9-serve.md](../_notes/rulings/D9-serve.md) | the agent-facing surface: MCP, CLI, SDK, hooks, install |
| [D10-quality.md](../_notes/rulings/D10-quality.md) | quality, calibration, the eval pyramid, release |

**These twelve are a different kind of document.** They are *amendment* decisions arising from the
audit of nineteen written plan documents against the charter — each one discharges a numbered defect
row that already exists in [17-risks.md](../17-risks.md) §§7.3-7.4. Where a ruling asked "what should
we build", an ADR here asks "which of these two printed statements is binding, and what does the
other one become". The rulings remain the house style for what a decision record looks like; these
inherit the style and narrow the scope.

## 3. What an ADR is here

An ADR **records a decision. It does not implement one.** A later stage applies each ADR to the plan
documents. An ADR that ends "and therefore [07](../07-store-and-retrieval.md) §6.2's table gains a
column" is correct and complete; the edit is not the ADR's to make.

Four rules, each with a failure mode it exists to prevent.

1. **It must decide.** Surveying options and stopping is the failure. Where the answer depends on a
   measurement nobody has run, the ADR names the measurement and its charter `F`-number, then
   **decides the interim position with its pre-committed fallback** — the plan's own idiom, used
   forty-one times in [17](../17-risks.md) §7.2. An interim position with a fallback is a decision
   and the ADR is `accepted`; a question left open is not, and the ADR stays `proposed`.
2. **The rejected alternatives are the point.** Argue each at its best before rejecting it. Where a
   rejected option is close, say so — a decision recorded as obvious when it was marginal gets
   reopened by the next reader.
3. **Consequences are obligations, not benefits.** Which documents change, which types change shape,
   which invariants gain or lose an enforcer, what becomes harder, what a future reader must not do.
   Price every consequence that is a cost.
4. **Cite everything.** Every claim about the plan carries a file and a section. The register rows an
   ADR discharges are quoted verbatim from [17-risks.md](../17-risks.md), not paraphrased.

**No ADR may edit [`../_notes/charter.md`](../_notes/charter.md).** §1-8 of the charter are immutable
by its own §9 preamble: "No line of §1-8 was edited during stage 10's repair work or stage 11's, and
none will be." An ADR that needs the charter to say something else claims an **erratum row** in §9
instead (see §6 below).

## 4. The template — a metadata block and five headings

Every file is `NNNN-<slug>.md`, opens with an `# ADR-N — <title>` line, then a **metadata block** of
bold-prefixed lines, then exactly five `##` headings in this order. Anything else is a `###` inside
one of the five. The block below is [ADR-3](0003-shipped-configuration.md)'s own opening, abridged
in its last two lines.

```markdown
# ADR-3 — The shipped configuration: thirteen enabled drivers, one flattening rule, and `ow doctor` green on a fresh install

**Status:** Accepted · **Priority:** 2 of 12 · **Price:** 4 ed
**Deadline:** before the P1 exit ([16](../16-roadmap.md) §3, week 22) — [17](../17-risks.md):346
**Discharges:** `04#Q1`, `04#Q8`, `05#2`, `05#3`, `02#5`, `15#1` (defect); `05#5`, `03#Q7`, `04#Q12` (adjacent)
**Charter errata claimed:** `E36`, `E37`, `E38`, `E39` (block `E36`-`E41`, [adr/README.md](README.md) §6)
**Supersedes:** none
**Blocks / unblocks:** unblocks `V01-15` ([00](../00-vision.md):716), which cannot be run while `ow doctor` fails as printed

## Context

## Decision

## Alternatives rejected

## Consequences

## Open
```

**Six metadata lines, in that order.** Five are on every ADR; only `Deadline` may be absent.

| line | present | what it carries |
|---|---|---|
| `Status` · `Priority` · `Price` | always — one line, three fields, ` · ` between them | the §6 vocabulary; `N of 12`, the priority §7's index sets; and engineer-days (`ed`) plus machine cost where it is not zero, the convention [17](../17-risks.md) §7.1 sets |
| `Deadline` | when the anchor is not itself a blocking relation | an **anchor**, never a date — a tier (`v0.1`, `v1.0`, `v2.0`), a roadmap phase boundary, or a named ordering condition — for the reason §7.1 gives: an anchor survives a schedule change and a date does not |
| `Discharges` | always | the register rows, defect rows first and adjacent rows marked `(adjacent)`, in the grouping §7.6 fixes |
| `Charter errata claimed` | always — all twelve claim at least one row | the rows claimed, and the §6 block they are claimed from |
| `Supersedes` | always | the ADR this one replaces, or `none` |
| `Blocks / unblocks` | always | what cannot start until this lands, what this waits on, and which of §7.1's sequencing constraints it sits under |

**A line with nothing in it is not written `—`; it is omitted, and only `Deadline` ever is.** Its
absence means the ordering anchor is stated once inside `Blocks / unblocks` rather than twice — four
of the twelve carry the line, and the other eight state the anchor there.

**Five headings, and what each is for.**

| heading | what it carries |
|---|---|
| `## Context` | **the rows this ADR discharges, quoted verbatim** from [17-risks.md](../17-risks.md) §§7.3-7.4 with their line numbers, before any prose; then what was re-verified against the pinned sources, and why the question is a decision rather than a repair |
| `## Decision` | the ruling, numbered, each part naming the document that becomes its sole home; and the charter errata rows written out in full for a later stage to insert |
| `## Alternatives rejected` | one `###` per rejected option, argued at its best before it is rejected |
| `## Consequences` | obligations, not benefits: a table of which document changes, what changes and what the edit costs, then what becomes harder and what a future reader must not do |
| `## Open` | what the decision does not settle, each with its closing evidence and its pre-committed fallback |

A row that turns out not to say what the ADR needs it to say is a finding, not a rounding error: two
earlier stages produced citations that had drifted.

**A charter-amending ADR carries five further parts inside `## Decision`**, which is what
[01-principles.md](../01-principles.md) §Open questions item 1 means by "a five-part ADR" and what
[11-repo-layout.md](../11-repo-layout.md) §8.4 means by "names the section, quotes the old text and
the new, and records which ruling's ADR must be re-issued":

| # | part |
|---|---|
| 1 | the charter locus — section number **and** line range |
| 2 | the old text, quoted verbatim |
| 3 | the new text that supersedes it, and the document that becomes its sole home |
| 4 | the erratum row number claimed from this ADR's block (§6) |
| 5 | which of D1-D10 must be re-issued, or `none` |

§8.4 adds one rule this directory inherits: **a charter-amending ADR may not land in the same PR as
the code that depends on it.**

## 5. Numbering

`ADR-1` through `ADR-12` are **allocated by [17-risks.md](../17-risks.md) §7.6 and are not
reassignable.** The number identifies the defect *class*, not the order of writing. Filenames
zero-pad to four digits (`0001`-`0012`) so the directory sorts.

`ADR-13` onward is a plain append, claimed by adding the row to the index in §7 of this file in the
same commit that adds the document. **The index table in §7 is the numbering authority** — the answer
to §9's "no numbering authority" finding. There is no separate register file: at twelve documents
[17](../17-risks.md) §9 rules that "the cheap version is correct", and a register that is a table in
the README has one home rather than two.

`charter_defects_open` in `tools/risks.toml` counts `class = "defect"` rows in
[17](../17-risks.md) §§7.3-7.4 **not yet discharged by an `accepted` ADR in this directory**. It
stood at **fifty-two** at the close of the nineteen plan documents, which is the figure
[17](../17-risks.md) §New terms and [glossary.md](../glossary.md) record. All twelve ADRs below are
`accepted`, each decrements by its row count, and 13 + 6 + 4 + 2 + 4 + 1 + 5 + 2 + 2 + 2 + 5 + 6 = 52,
so **it stands at zero**. The twelve discharge all fifty-two and nothing else does; §7's `rows`
column is the arithmetic. `R-O9`'s trigger — the counter exceeding the ADR count by more than 10 —
is therefore 0 against 12 and cannot fire on this directory.

## 6. Status vocabulary, and the erratum blocks

| status | meaning | effect on `charter_defects_open` |
|---|---|---|
| `proposed` | written and not ratified; its rows are still open | no decrement |
| `accepted` | ratified; its rows are discharged and a later stage applies it to the plan documents | decrements by the row count |
| `superseded by ADR-N` | a later ADR owns the question; the rows move to `N` with the number recorded in both files | no change — `N` carries them |
| `withdrawn` | the question dissolved rather than being answered; every row returns to [17](../17-risks.md) with a one-line note saying why | re-increments by the row count |

An ADR whose decision is an **interim position with a pre-committed fallback** is `accepted`. The
fallback is the decision. `proposed` is for an ADR that has not decided, and an ADR that stays
`proposed` after its deadline anchor passes is a schedule finding, not a status.

**All twelve are `accepted`.** Every one decides — several by pre-committed fallback — and the stage
that applies them to the plan documents is running against them, which is what `accepted` means in
the table above. §4's metadata line prints the token capitalised (`**Status:** Accepted`); it is the
same token as this table's, and there is no third spelling.

**Erratum blocks, so twelve authors do not collide.** [17-risks.md](../17-risks.md) §7.7 records what
happened the last time two documents continued one number series in parallel — two documents "took
adjacent blocks by luck rather than by rule" — and fixed it with per-document blocks. The same
mechanism applies here. `E1`-`E23` are taken by [charter.md](../_notes/charter.md) §9.2.
**ADR-`n`'s block starts at `E(18 + 6n)` and runs six rows**, and an ADR may only claim inside its
own block:

| ADR | block | ADR | block |
|---|---|---|---|
| ADR-1 | `E24`-`E29` | ADR-7 | `E60`-`E65` |
| ADR-2 | `E30`-`E35` | ADR-8 | `E66`-`E71` |
| ADR-3 | `E36`-`E41` | ADR-9 | `E72`-`E77` |
| ADR-4 | `E42`-`E47` | ADR-10 | `E78`-`E83` |
| ADR-5 | `E48`-`E53` | ADR-11 | `E84`-`E89` |
| ADR-6 | `E54`-`E59` | ADR-12 | `E90`-`E95` |

Six is the width because ADR-11 alone reaches six charter loci. Unused rows in a block are never
reallocated; §9.2 already orders its rows by charter line number rather than by row number, so gaps
cost nothing. An ADR claiming an erratum **writes the row's content in its own `## Decision`**; a
later stage inserts it into §9.2, because no agent in this stage may edit the charter.

## 7. The index

Twelve ADRs, **37.5 engineer-days** total, none of it inside the program's engineer-week total —
[16-roadmap.md](../16-roadmap.md) §3.1's staffing matrix is that total's sole home and the only place
it is quoted, because it moves whenever a phase's `ew` moves (ADR-11's four gate scripts moved it
last). The roadmap's exclusions cover documentation, recruiting and the `F`-item measurement runs and
are silent on the ADRs (`RK-Q6`). The 37.5 ed is the answer `RK-Q6` asks for and the largest
previously unmodelled item in the schedule.

Ordered by what unblocks what, not by number. `#` is priority.

| # | ADR | title | status | price | rows | unblocks |
|--:|---|---|---|--:|--:|---|
| 1 | [ADR-1](0001-terminology-lock-bulk-pass.md) | The terminology lock takes 720 rows, §3 becomes machine-readable, and `G27(c)` turns on | `accepted` | 6 ed | 13 | `G27(c)`; every later ADR that coins a name |
| 2 | [ADR-3](0003-shipped-configuration.md) | The shipped configuration: thirteen enabled drivers, one flattening rule, and `ow doctor` green on a fresh install | `accepted` | 4 ed | 6 | `V01-15`, `G18`, `ow route lint` check 1, `R-A8` |
| 3 | [ADR-5](0005-byte-exactness-chain.md) | The byte-exactness chain: `nfc()` proves INV-10, the `origin_span` rung keeps three values and gains an enforcer, `wirekeys.toml` appends to twenty-nine, and only `DocSink` writes a `part` row | `accepted` | 5 ed | 4 | `Q-G6`/`V01-5` at `span_exact_rate == 1.000`; the P2 wire |
| 4 | [ADR-12](0012-runtime-types-on-the-critical-path.md) | `Outcome` is eight members in `08` §1.3, `RunContext` stays in `omniweave_core/operator.py`, the exit-code table gains no row, and a bake asset hangs off a synthetic job document | `accepted` | 3 ed | 2 | `Store.complete()`, the exit-code table, three `18` signatures |
| 5 | [ADR-6](0006-citation-and-retrieval-surface.md) | `block_cite` is gen-free, `vectors = "off"` is `OFF`, `rank_of` stays, and `want` closes at five | `accepted` | 3 ed | 4 | `fuse()`/`ceiling()`, ST6's property test, `ow surface emit` |
| 6 | [ADR-9](0009-schema-single-home.md) | `SCHEMA` has one code home, `omniweave_core.contract`, and one disk home, `index_state` | `accepted` | 0.5 ed | 1 | `ow store verify`, `G27(b)`'s empty-file run; rejection criterion 19 |
| 7 | [ADR-2](0002-invariant-and-gate-registers.md) | The registers: twenty-five invariants, `G27(d)` stays with `gate_docs.py`, the two register checks become job assertions, and the G-series stops being closed at 27 | `accepted` | 3 ed | 5 | `G27(d)`, `gates.invariant_register`, `V10-1`, `[[job_assertion]]` 7 to 9 |
| 8 | [ADR-4](0004-shipped-routing-policy.md) | The charter's D4 policy block is retired law, and `G27(a)` gains the two clauses that would have caught it | `accepted` | 2 ed | 2 | the charter's own `tomllib.load` gate and `ow route lint` over D4; rejection criterion 21 |
| 9 | [ADR-7](0007-driver-resolution-keys.md) | Every key in the driver system digests the whole of what it identifies | `accepted` | 2 ed | 2 | `drivers.resolve_memo_collisions`, `R-T15`; the first out-of-tree caller |
| 10 | [ADR-10](0010-data-artefacts-and-weight-ceiling.md) | The data artefacts ship as ZIP, the weight ceiling reads marginal, and `omniweave-conform` implements `eval` | `accepted` | 2 ed | 2 | a stdlib-only install reaching the golden corpus; `gate_weights.py`; P2's weights mirror |
| 11 | [ADR-8](0008-input-surface-and-pass-ladder.md) | A name the charter prints with no producer becomes a producer, a definition, or a recorded absence — never silence | `accepted` | 4 ed | 5 | `V01-17`; the survivor rule; what a reader believes ships |
| 12 | [ADR-11](0011-eval-register-reconciliation.md) | Seven eval suites, the byte cap as the gate, `eval/runners/`, no numeral on an uncalibrated signal, a worker-scoped RSS budget, an ingest-only 100k reference, and a `Q-G` series that is twenty-seven | `accepted` | 3 ed | 6 | `Q-G` 23 to 27; `V10-1`'s gate arithmetic; `Q-G2`, `Q-G14`/INV-19 |
| 13 | [ADR-13](0013-v01-acceptance-reconciliation.md) | v0.1's acceptance set says what the built system can be measured against: five rulings on seven owed items | `accepted` | 3.5 ed | 0 | the P7 exit list; `V01-11`, `V01-12` and `V01-15` measurable as written |
| 14 | [ADR-14](0014-reference-corpora-and-control-arm.md) | `bench/serve/`'s corpora, tasks, control arm and agent are specified well enough to build: seven rulings on what D602 and RK-Q4 leave open | `accepted` | 10.5 ed | 0 | W7.7b; `--tasks all` in the P7 exit list; `RK-Q4` closed |
| 15 | [ADR-15](0015-encrypted-pdfs-and-document-passwords.md) | Encrypted PDFs and document passwords: a PDF that opens is read, one that does not is named, and a password has two sources and one route | `accepted` | 4.0 ed | 0 | Q-G7's `encrypt` Injector; the bench's two `encrypt` tasks *(D965 adds [ADR-16](0016-g35-install-round-trip.md): G35, the install round trip, Proposed.)* |

**ADR-13 is the first ADR the build raised rather than the audit.** It discharges no row of [17](../17-risks.md) §§7.3-7.4 — its seven items are the build ledger's *"owed to the plan"* entries — so its `rows` cell is 0, it does not move `charter_defects_open`, and it is outside the 37.5 ed above. ADR-14 is the second, on the same terms: `D602` and `RK-Q4`, neither a §§7.3-7.4 row.

**Row arithmetic: 13 + 6 + 4 + 2 + 4 + 1 + 5 + 2 + 2 + 2 + 5 + 6 = 52.** Every `class = "defect"`
row in [17](../17-risks.md) §§7.3-7.4 is owned by exactly one ADR, and no ADR claims a row that is
not a defect. Eleven further `gap` and `decision` rows ride along as **adjacent** rows, named per ADR
in §7.6's own fourth column; they do not count against `charter_defects_open` and they cannot
sensibly be settled apart from the defect they sit beside.

### 7.1 Sequencing constraints, stated once

**Read `P<n>` as a roadmap phase in this table.** The token is overloaded:
[17-risks.md](../17-risks.md) §4 numbers six **compound risk paths** `P1`-`P6`, and
[16-roadmap.md](../16-roadmap.md) §3 numbers ten **phases** `P1`-`P10`. The sentence that orders this
whole backlog — [17](../17-risks.md):346, "price and place ADR-1 and ADR-3 before P1 exits" — sits
inside the paragraph headed "**P6 — the buffer, the backlog and the ADRs**", where `P6` is a risk
path but `P1` must be a phase: risk path P1 is a measurement and has no exit, while phase P1 exits at
week 22. That reading is the one followed here, and the collision itself is unowned —
[17](../17-risks.md) §7.7 fixed the identical `R-Q` collision and did not fix this one.

| constraint | ADRs | source |
|---|---|---|
| **before the P1 exit** — [16](../16-roadmap.md) §3 places P1 (substrate, config, discovery, the gate harness) at weeks 10-22 | ADR-1, ADR-3 | [17](../17-risks.md):346 — "price and place ADR-1 and ADR-3 before P1 exits. They are the two that unblock other work" |
| **before the P2 schema freeze** — P2 is "the pivot: 91 tables, the four protocols, `rebind()`, `.owdoc`", weeks 16-38, so its freeze is *earlier in wall-clock* than the P1 exit | ADR-5, ADR-12, ADR-6, ADR-9 | ADR-5: [final-review](../_notes/final-review.md) §8 item 12 — "the one whose outcome could change a shipped type — do it before P2 freezes". ADR-12: `Store.complete()` is one of P2's four protocols. ADR-6: `block_cite`'s columns are P2 DDL. ADR-9: `meta` vs `index_state` is P2 DDL |
| **ADR-1 before every ADR that coins a name** | all eleven others | `02#1`'s closer is "one bulk lock pass **after the documents land**"; a name coined into an unfixed lock fails rule 1 twice |
| **ADR-2 before ADR-11** | ADR-2, ADR-11 | both amend `V10-1` ([00-vision.md](../00-vision.md):724, "All **27** `G` gates and all **23** `Q-G` gates green"): ADR-2 via `11#OQ-10` replaces the literal `27`, ADR-11 via `13#Q-Q5` and `10#F60` moves `23` to `27`. Two ADRs editing one sentence must land in that order, or in one PR |
| **before the first out-of-tree caller exists** | ADR-7 | `04#Q2`'s own deadline column, and `R-T15`: "the single most likely source of a silent wrong-driver bug in the plan" |
| **before `bake` ships** | ADR-12's `09#Q9` half | `09#Q9`: "**Must be made before `bake` ships, not with it**"; vacuous while `K-5` holds |
| **decides the ranking inside itself** | ADR-10 | `11#OQ-12` "changes the ranking of `11#OQ-1`'s three exits", so the two cannot be split across ADRs or across time |
| **no ordering constraint** | ADR-4, ADR-8 | ADR-4's dangerous half is already repaired in [05](../05-ingest-and-routing.md) §4.4; only the immutable charter still carries it, and the charter is not executed. ADR-8's rows are `v0.1` and `v1.0` scope statements with `V01-17` as the mechanical closer |

### 7.2 One scoping finding to carry forward

**ADR-4's question changes shape.** [final-review.md](../_notes/final-review.md) §8 item 10 scopes it
as "the shipped policy's mechanical defects — nine `on_unknown`, two unparseable TOML blocks, four
dead `GATE` rules. Run `G27` over the plan's own TOML blocks and fix what it reports". That scope is
wrong, and this was checked rather than assumed:

| block | `[[rule]]` count | `on_unknown` declarations | newline-spanning inline table | co-rung `GATE` rules |
|---|--:|--:|---|--:|
| [05-ingest-and-routing.md](../05-ingest-and-routing.md) §4.4, its one ` ```toml ` fence | 40 | 17 | none | split into action plus modifier per §4.2 |
| [charter.md](../_notes/charter.md) D4 block, fence `:2576`-`:2783` | 15 | 2 | `repair.never-escalate-furniture`'s `when` at `:2739`-`:2740` | 4 — `gate.encrypted`, `gate.watcher-may-not-bill`, `gate.agent-triggered-may-not-bill`, `gate.form-is-a-signal-not-an-exclusion`, all `rung = "GATE"` |

Every count is over the ` ```toml ` fence itself, opening line to closing line, and counts
**declarations** rather than mentions: `05` §4.4 carries four further `on_unknown` occurrences,
every one of them inside a `comment = """…"""` string, and the charter's block carries none. The
charter's span is given in lines because §1-8 is immutable and its lines cannot move; `05` §4.4's is
given as a section because the plan documents are still being edited. The same four cells are
measured independently in [ADR-4](0004-shipped-routing-policy.md) §Context, and agree.

`05` §4.4 is clean on all three counts and its `repair.never-escalate-furniture` carries
`on_unknown = "match"` with a comment saying the declaration is load-bearing. **The charter's D4
block is the unrepaired carrier**, and [05](../05-ingest-and-routing.md) §Open questions item 4
already records exactly this: "The charter's shipped policy contains three mechanical defects **this
document repairs**, and each needs the charter's own CI to catch it."

So ADR-4 is not a repair. It is an **erratum plus a gate**: the charter is immutable, its policy block
is retired law that `05` §4.4 supersedes, and the live work is (a) the §9.2 erratum row naming
`05` §4.4 as the sole home, and (b) extending `G27` to run `tomllib.load` and `ow route lint` over
the charter's and every plan document's own TOML fences — which is the mechanism that would have
caught it, and which the charter's rejection criterion 21 ("prints a TOML or JSON block in a charter
or plan document that does not parse (G27)") already demands and does not yet have.
