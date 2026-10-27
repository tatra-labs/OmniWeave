# ADR-2 — The registers: twenty-five invariants, `G27(d)` stays with `gate_docs.py`, the two register checks become job assertions, and the G-series stops being closed at 27

**Status:** Accepted · **Priority:** 7 of 12 · **Price:** 3 ed
**Discharges:** `01#1`, `01#2`, `00#V-Q8`, `11#OQ-10`, `15#2` (defect); `01#3` (adjacent)
**Charter errata claimed:** `E30`, `E31`, `E32`, `E33`, `E34` (block `E30`-`E35`, one unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks P1, which builds the gate harness against a `tools/invariants.toml` printed with two of twenty-five rows and an unowned `G27(d)`. Closes [_plan/README.md](../README.md) unresolved contradictions 2 (the job-assertion count) and 4 (the invariant count). **Must land before ADR-11:** both amend `V10-1` at [00-vision.md](../00-vision.md):724, and two ADRs editing one sentence land in order or in one PR. Both also claim an erratum at charter `:8221`.

## Context

Five rows, quoted from [17-risks.md](../17-risks.md) §§7.3-7.4:

- `01#1` (:571) — "INV-21..INV-25 need a charter amendment | defect | `release` | a five-part ADR
  quoting section 2's old count; until then say "principle", not "invariant" | v0.1"
- `01#2` (:572) — "two enforcer columns are incomplete (INV-1's `G6`; INV-19's `DocSink` raise) |
  defect | `release` | the same ADR corrects both columns | v0.1"
- `00#V-Q8` (:568) — "gate `G6` has two definitions | defect | `release` | an ADR renumbering one;
  cite the **property**, not the number, until then | v1.0"
- `11#OQ-10` (:675) — "the G-series is closed at 27 by a core document and the `build` job's
  reproducibility assertion is a real gate by every criterion | defect | `release` | an amendment to
  V10-1 replacing the literal 27 with "every row in `tools/gates.toml`", after which new gates are
  ordinary appends. Fallback: the `[[job_assertion]]` family stays and every future gate lands
  there — which is what this document's own check does | v1.0; ADR-2; also `RK-Q1`"
- `15#2` (:712) — "the redaction canary test has no gate number, so a future contributor can delete
  the only mechanical proof of this document's one self-authored posture claim | defect | `release` |
  a charter amendment allocating a number, or G8 absorbing it as a named assertion beside its semgrep
  set … The `[[job_assertion]]` family is the third option and needs no amendment | v1.0; ADR-2"
- `01#3` (:573, adjacent) — "the enforcement ladder is not yet mechanical | gap | `release` |
  `tools/gate_invariants.py` over `tools/invariants.toml` as the `gates.invariant_register` job
  assertion — **not** `G27(d)`, which [11](../11-repo-layout.md) already spends on `gate_docs.py`;
  rule 2's independence check is **undecidable in general**, so ship the two decidable cases"

**The count is stated four ways.** [01](../01-principles.md) defines twenty-five;
[charter.md](../_notes/charter.md) `:66` opens §2 with "Twenty properties."; `:8221` (X32) writes
"`INV-1..20` (this charter) are unchanged"; [11](../11-repo-layout.md) §1.8's tree calls
`ARCHITECTURE.md` the carrier of "the twenty invariants"; and [17](../17-risks.md) `R-A1` counts
"twenty invariants plus five pending principles". At most one can be what `G27(d)` checks.

**`G27(d)` is claimed twice.** [11](../11-repo-layout.md) §8.6 *spends* it: `tools/gate_docs.py`,
five clauses `d0`-`d4`, a symbol floor of **520** in `tools/gates.toml`, a 25 s budget, and a
released failure-message format. [01](../01-principles.md) §Open questions item 3 *requests* it for
`tools/gate_invariants.py`, "a natural extension of `G27` … rather than a twenty-eighth gate, because
§5 X32 states that CI gates are `G1-G27` and nothing else". A clause can be spent once.

**Two enforcer columns are wrong in the charter and already corrected in `01`.** Charter `:72`
credits `G6` with `import(export(store)) == store` over the fixture corpus; `G6` is
`ow schema emit --check` (charter `:782`, [11](../11-repo-layout.md) §6.4), and the round-trip check
exists (charter §D2, `:1604`) with no number at all. Charter `:90` names only `Q-G8` and `Q-G14` for
INV-19 while [01](../01-principles.md) §INV-19 carries four enforcers including an `A`-class raise at
`DocSink.add_block`.

**Why this is a decision and not a repair.** "Twenty-five" cannot be written into the charter — §1-8
are immutable — and cannot be asserted anywhere until something decides whether the five are
invariants at all. The `G27(d)` collision is between two final documents, neither wrong. And the
`15#2` and `11#OQ-10` rows both need to know whether the G-series can grow, which is a constitutional
question about how this framework registers its own promises, not a filing question.

**The ladder's own claim was checked before ruling.** [01](../01-principles.md)'s rule 1 —
"at least two independent enforcers and at least one of `{A, S, L, G, X}`" — holds for all
twenty-five rows as written: every `**Enforced by.**` line carries three or more enforcers and none
is `R`-alone. The claim is true; what is missing is a machine that keeps it true.

## Decision

### 1. There are twenty-five invariants, and INV-21..INV-25 are invariants

`INV-21`..`INV-25` are adopted as invariants. [01](../01-principles.md) §1b's amendment note, its
"carry the force of a principle" clause and its "a reviewer citing one must say so" instruction are
discharged; `tools/invariants.toml`'s five rows move from `force = "principle"`, `adr = "pending"` to
`force = "invariant"`, `adr = "ADR-2"`.

The test is the ladder's own rule 1, and all five pass it independently of this ADR: INV-21 is
`G`+`L`+`G` (`G27(c)`, a schema lint over the DDL, `G18`), INV-22 `A`+`L`+`X`, INV-23 `A`+`L`+`G`,
INV-24 `G`+`X`+`L`, INV-25 `A`+`S`+`X`+`L`. A statement with two independent non-`R` enforcers is an
invariant by [01](../01-principles.md)'s own definition; calling it a principle is a filing error, not
a lower standard. The plan already relies on it: charter §8 rejection criterion 19 ("a second home for
one config key") **is** INV-21, and ADR-9 exists to discharge exactly that criterion.

### 2. `G27(d)` belongs to `gate_docs.py`; the two register checks are job assertions

`G27(d)` is [11](../11-repo-layout.md) §8.6's `tools/gate_docs.py`, clauses `d0`-`d4`, unchanged.
`tools/gate_invariants.py` becomes the `[[job_assertion]]` **`gates.invariant_register`**, job
`gates`, budget **2 s** — the same shape and the same budget [17](../17-risks.md) §1.1 gave its own
register check, `gates.risk_register`, for the same reason, stated there and adopted here: `G27(d)`
is "the correct home for *identifier resolution* and the wrong home for *semantic assertions over a
register's rows*". `d2` resolves whether `INV-21` exists; `gates.invariant_register` asserts whether
its row is well-formed. Different questions, different failure messages, different owners.

**The release-1 `[[job_assertion]]` count is nine**, not seven: the seven of
[11](../11-repo-layout.md) §6.4 plus `gates.invariant_register` and `gates.risk_register`. This is
`RK-Q1`, and it closes [_plan/README.md](../README.md) contradiction 2.

`gates.invariant_register` asserts, over `tools/invariants.toml`:

1. every `### INV-<n>` heading in `01-principles.md` has exactly one `[[inv]]` row and every
   `INV-<n>` row has exactly one heading — bidirectional, the shape the terminology lock already uses;
2. `independent >= min_enforcers` and `classes != ["R"]` for every row (ladder rule 1);
3. `independent == len(enforcers) + len(sites)` (see decision 3);
4. the two **decidable** cases of ladder rule 2, and only those: two enforcers naming the same
   semgrep config file count as one, and a `S`-class trigger plus the mapping it was generated from
   count as one unless a parity gate is named. The general case is undecidable and stays `R`. This
   is `01#3`'s own pre-committed scope, quoted in its register row;
5. **every spelled-out invariant count in any document equals the number of `[[inv]]` rows whose id
   matches `^INV-\d+$` and whose `force` is `invariant`** — modelled exactly on `G27(d)` clause d2's
   distribution-count check, which already fails a PR that adds a fifteenth distribution and forgets
   the prose. This is the mechanism that makes one count true and keeps it true.

### 3. The two enforcer columns, and the field that lets them be written down

Charter `:72`'s INV-1 row and `:90`'s INV-19 row are superseded; [01](../01-principles.md) §INV-1 and
§INV-19 are the sole homes. INV-1's third enforcer is **`G28`** (decision 4), not `G6`. INV-19 has
four enforcers, not two: the `A`-class raise at `DocSink.add_block` plus the frozen ten-field
`MeasuredOn`, `Q-G8`, `Q-G10`, `Q-G14`, and the renderer test.

Writing INV-19's row down exposes a schema gap: an `A`-class or `X`-class enforcer has no id for
`enforcers` to hold, and `G27(d)` d2 resolves only ids. **`[[inv]]` therefore gains a second list,
`sites`**, for enforcers that have no register id, each entry either a dotted `omniweave*` symbol —
which `G27(d)` clause **d1** already resolves by importing it — or a repo-relative path. `independent`
counts both lists. Two rows, as they will be committed:

```toml
[[inv]]
id = "INV-1"
title = "One representation of a Block"
force = "invariant"
owner_doc = "03-document-model.md"
enforcers = ["GR15", "G28"]
sites = ["tools/semgrep/no-second-text-column.yml"]   # the html/md/markdown field ban
classes = ["L", "G"]
independent = 3

[[inv]]
id = "INV-19"
title = "Every number carries its evidence"
force = "invariant"
owner_doc = "13-quality.md"
enforcers = ["Q-G8", "Q-G10", "Q-G14"]
sites = ["omniweave_core.store.doc.DocSink.add_block", "omniweave_conform.render.MeasuredOn"]
classes = ["A", "G", "X"]
independent = 5
```

### 4. The G-series stops being closed at 27; `G28` and `G29` are the first appends

**`V10-1` ([00-vision.md](../00-vision.md):724) drops the literal `27`.** It reads "All **27** `G`
gates and all **23** `Q-G` gates green on the tagged commit"; its `G` half becomes "every `G` row in
`tools/gates.toml` green". This is `11#OQ-10`'s recommended closer rather than its fallback: a
register whose cardinality is quoted in a vision document cannot grow, and a reader of `V10-1` needs
"all gates green", never a number. **The `Q-G` half is ADR-11's** and is untouched here.

Charter X32's "CI gates are `G1-G27` and nothing else" and the T0 pyramid's "`G1-G27`" are superseded
with it. Adding a `G<n>` still requires an ADR — not because a count is quoted, but because a `G<n>`
is a **numbered promise a document may cite**, which is [11](../11-repo-layout.md) §8.7's own
distinction between a gate and a job assertion. Nothing else in §8.7's row changes.

Two numbers are allocated by this ADR, which is the ADR §8.7 requires:

| gate | assertion | job | budget | implements |
|---|---|---|---|---|
| **`G28`** | `import(export(store)) == store` over the fixture corpus | `gates` | 45 s | INV-1's `G`-class enforcer; charter §D2's unnumbered "CI gate" at `:1604`; `V01-7` |
| **`G29`** | the redaction canary: `tests/test_no_content_in_artefacts.py` ingests a canary corpus under a forced crash, a forced budget denial, a forced quarantine and a forced exception holding page text, and asserts `OWCANARY-7f3a91` appears in the `quarantine` payload and nowhere else | `gates` | 60 s | [15](../15-observability.md) §8.3 |

`G28`'s 45 s and `G29`'s 60 s are estimates, and the plan's idiom applies: **pre-committed fallback**
— if either pushes the `gates` job past its 3-minute ceiling (`V01-14`), it moves to the `test` job
beside `G26` at the first measured run, which is a one-line change to its `tools/gates.toml` row.

`G6` is **not** renumbered. It is `ow schema emit --check` at charter `:782`, in
[11](../11-repo-layout.md) §6.4, in INV-20's enforcer list and in `ST17`'s "byte-diff gated like G6";
the defect `00#V-Q8` records is that charter `:72` credited `G6` with a second, different assertion.
Numbering the second assertion `G28` resolves it without touching four correct citations.

### 5. The charter amendment, in the five parts [README](README.md) §4 requires

Five loci, five errata, claimed from ADR-2's block `E30`-`E35` and written here for a later stage to
insert into charter §9.2. `E35` is unused and is never reallocated.

| # | locus | search phrase | what the charter says | what supersedes it, and its live home | re-issues |
|---|---|---|---|---|---|
| `E30` | `:66` | `Twenty properties.` | §2's count of framework invariants | **ADR-2.** Twenty-five. `INV-21`-`INV-25` are invariants; sole home [01](../01-principles.md) §1, §1b, and `tools/invariants.toml` | none |
| `E31` | `:72` | `over the fixture corpus (G6)` | INV-1's enforcer column, crediting `G6` | **ADR-2.** The archive round-trip check is **`G28`**; `G6` is `ow schema emit --check` and is unchanged. Sole home [01](../01-principles.md) §INV-1 | none |
| `E32` | `:90` | `Q-G8, Q-G14; \`MeasuredOn\` is frozen` | INV-19's enforcer column, naming two gates | **ADR-2.** Four enforcers: the `A`-class raise at `DocSink.add_block`, `Q-G8`, `Q-G10`, `Q-G14`, and the renderer-status test. Sole home [01](../01-principles.md) §INV-19 | none |
| `E33` | `:8221` (X32) | `(this charter) are unchanged. CI gates are` | `INV-1..20` unchanged; "CI gates are `G1-G27` and nothing else" | **ADR-2.** `INV-1..25`; the G-series is append-by-ADR and its cardinality lives in `tools/gates.toml`. **The same line's `Q-G1..23` is ADR-11's**, in its own §9.2 row at this locus | **D1** (the gate harness) |
| `E34` | `:7082` | `T0 gates      G1-G27` | the T0 row of the test pyramid | **ADR-2.** "every `G` row in `tools/gates.toml` + the static `Q-G` series". Sole home [11](../11-repo-layout.md) §6.4 | D1 |

## Alternatives rejected

**Leave INV-21..INV-25 as principles.** At its best this is free, it is what
[01](../01-principles.md) §1b already says, and it keeps the charter's count true without an
amendment. Rejected because the register cannot hold the fiction: `tools/invariants.toml` is read by
`G27(d)` d2 and by `gates.invariant_register`, and a row with `force = "principle"` and five real
enforcers is a row that passes every check while a reviewer is told not to cite it. Worse, the plan
already cites them as invariants in effect — charter §8 rejection criterion 19 is INV-21, and ADR-9
is written to discharge it. Leaving them as principles makes a shipped rejection criterion
unciteable.

**Give `gate_invariants.py` a fifth clause, `G27(e)`.** Genuinely close, and it is what
[01](../01-principles.md) proposes. It needs no new number, it keeps document checking in one script,
and `G27` is already the gate that machine-checks documents. Rejected on the argument
[17](../17-risks.md) §1.1 made when it faced the identical choice for its own register and declined:
`G27` resolves identifiers across documents, and a register's semantics are not a document check.
Concretely, `G27(d)`'s clause `d0` — "the walk found something" — guards `d1`-`d4` and would guard a
semantic assertion it has nothing to do with, and `G27`'s single 25 s budget and single failure prefix
would then cover two unrelated failure modes. Two job assertions, two budgets, two messages.

**Resolve `G27(d)` in `01`'s favour and move `gate_docs.py` elsewhere.** The strongest form: `01` is
the constitution and the invariant register is more load-bearing than a symbol walk. Rejected on
precedence and on cost. [11](../11-repo-layout.md) §8.6 *spends* the clause with an implementation, a
floor of 520 committed to `tools/gates.toml`, a failure-message format quoted in three places and a
released budget; [01](../01-principles.md) *proposes* it in an Open question. Moving `gate_docs.py`
would renumber a clause four documents cite.

**Keep `V10-1`'s literal `27` and file everything as job assertions.** This is `11#OQ-10`'s own
pre-committed fallback and it costs nothing today. Rejected because it makes the numbered table the
smaller half of the register — [11](../11-repo-layout.md) §8.6 says so already at seven job
assertions against twenty-seven gates — and because it leaves `15#2` unfixable within the nine-row
count [17](../17-risks.md) `R-A1` and §1.1 both assert. A framework whose gate register can only grow
sideways has two gate registers.

**Absorb the redaction canary into `G8`.** [15](../15-observability.md) §Open questions calls this
"the natural home, since the traceback ban of §8.3 is already four semgrep rules in `G8`". Rejected
because `G8` is a static scan and the canary is a full ingest under four forced faults followed by a
grep over produced artefacts. Hanging it off `G8` puts a behavioural test inside a lint gate's budget
and makes one failure message cover "a semgrep rule fired" and "content leaked into an artefact",
which are not the same incident. A posture claim that is the only mechanical proof of a
self-authored promise earns its own number.

**Renumber `G6`.** `00#V-Q8` offers this ("an ADR renumbering one"). Rejected: `G6` as
`ow schema emit --check` is correct in the gate table, in INV-20's enforcer column, in `ST17` and in
[11](../11-repo-layout.md)'s `.gitattributes` comment; the incorrect citation is the charter's INV-1
row. Renumbering the correct one to fix the incorrect one inverts the repair.

## Consequences

| document | edit | price |
|---|---|---|
| [00-vision.md](../00-vision.md):724 | `V10-1`'s `G` half becomes "every `G` row in `tools/gates.toml` green"; `V01-7`'s "charter cites G6; see V-Q8" becomes `G28`; `V-Q8` moves to answered. **Sequenced with ADR-11**, which owns the same sentence's `Q-G` half | 0.5 ed |
| [01-principles.md](../01-principles.md) §1b, §1e, §INV-1, §INV-19, §Open questions | §1b's amendment note becomes a "landed" note citing ADR-2; §1e's two illustrative rows become the INV-1 and INV-19 rows above and the `sites` field is documented; INV-1's enforcer names `G28`; Open questions 1, 2 and 3 move to answered | 1 ed |
| [11-repo-layout.md](../11-repo-layout.md) §1.8, §6.4, §8.6, §8.7, `OQ-10` | "the twenty invariants" becomes twenty-five; §6.4's table gains `G28` and `G29` and the job-assertion table gains two rows with "Seven" becoming "Nine"; §8.7's "add a gate" row drops "(the count 27 is asserted by 00-vision V10-1)" and keeps the ADR requirement on the numbered-promise argument; `OQ-10` moves to answered | 1 ed |
| [15-observability.md](../15-observability.md) §8.3, §Open questions | "That this test has no `G` number is recorded in Open questions" becomes `G29`; the row moves to answered | 0.25 ed |
| [17-risks.md](../17-risks.md) `R-A1`, `R-A2` | "twenty invariants plus five pending principles" becomes "twenty-five invariants" in both rows; `R-A1`'s "twenty-seven `G` gates" becomes twenty-nine | 0.25 ed |
| [_notes/terminology.md](../_notes/terminology.md) | `invariant`-kind rows for `INV-21`..`INV-25`, and a row for `sites` — **claimed through ADR-1's bulk pass**, not written here | 0 (ADR-1) |
| charter §9.2 | five rows, `E30`-`E34` | 0.25 ed |

**Registers that change shape.** `tools/invariants.toml` gains a `sites` list per `[[inv]]` row and
its five `force = "principle"` rows become `invariant`. `tools/gates.toml` gains two `G` rows and two
`[[job_assertion]]` rows. Both are append-only against the previous tag
([11](../11-repo-layout.md) §5.2), so all four are legal appends.

**What becomes harder, priced.** Two new gates cost roughly 105 s of `gates`-job time against a
180 s ceiling (`V01-14`), which is why the fallback in decision 4 is pre-committed rather than
discovered. And `gates.invariant_register`'s clause 5 makes every spelled-out invariant count in
nineteen documents a gated fact: a PR that adds `INV-26` and forgets a paragraph now fails, which is
the intent and is also two more places to edit per invariant.

**What a future reader must not do.** Do not cite `G6` for the archive round-trip — it is `G28`. Do
not add a clause `G27(e)`; the register checks are `[[job_assertion]]` rows by decision. Do not read
charter `:66`, `:7082` or `:8221` as current. Do not add a `G<n>` without an ADR: the reason changed,
the requirement did not.

## Open

**Ladder rule 2's general case stays undecidable and stays `R`.** `gates.invariant_register` ships
the two decidable cases named in decision 2 and asserts nothing about the rest, exactly as
`01#3`'s register row pre-commits. The evidence that would widen it is a measured count of how often
a real PR disables two enforcers of one invariant in one edit; until someone has that number, a third
heuristic is a guess with a failure message.

**`G28` and `G29` are claimed, not allocated.** [11](../11-repo-layout.md) §6.4 runs to `G27` and no
document holds a `G`-number block the way [17](../17-risks.md) §7.7 holds the `F`-series. Six ADRs are
being written in parallel; if another allocates `G28`, this one renumbers. That there is no block rule
for the `G` series is a finding recorded here, not fixed here — `17` §7.7's mechanism is the obvious
remedy and applying it to a second series is ADR-scope creep.
