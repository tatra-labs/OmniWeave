# ADR-1 — The terminology lock takes 720 rows, §3 becomes machine-readable, and `G27(c)` turns on

**Status:** Accepted · **Priority:** 1 of 12 · **Price:** 6 ed
**Deadline:** before the P1 exit ([16](../16-roadmap.md) §3, week 22) — [17](../17-risks.md):346
**Discharges:** `02#1`, `04#Q3`, `07#D1`, `07#D2`, `03#Q1`, `03#Q9`, `08#D1`, `09#Q6`, `09#Q7`, `12#D1`, `13#Q-Q4`, `14#6`, `18#2`
**Charter errata claimed:** `E24`, `E25`, `E26`, `E27` (block `E24`-`E29`, [adr/README.md](README.md) §6)
**Supersedes:** none
**Blocks / unblocks:** unblocks `G27(c)`, blocked twice over — on the missing rows (`02#1`) and independently on check 3 (`12#D1`). Unblocks every later ADR that coins a name, because `02#1`'s closer is "one bulk lock pass **after** the documents land". Retires `R-O9`'s second trigger.

## Context

The lock ([_notes/terminology.md](../_notes/terminology.md)) is binding alongside the charter and
carries **407 §2 rows with 407 distinct first cells**, 60 §3 rejected-synonym rows, and three CI
rules at `:11`, `:13` and `:15`. All three fail today.

**Rule 1 fails in bulk.** [17](../17-risks.md):578 — "`02#1` | >= 38 charter class names have no
terminology row | defect | `release` | one bulk lock pass after the documents land, then `G27(c)`
on. **`G27(c)` cannot be switched on before it**". Four more rows name specific clusters:
`04#Q3` (:601), `07#D1` (:633), `08#D1` (:648), `18#2` (:727). The clusters were re-counted against
the lock rather than trusted:

| row | claims | verified | correction |
|---|---|---|---|
| `04#Q3` (:601) | fifteen `omniweave_ports` names | [04](../04-driver-system.md) §Open questions Q3 lists **sixteen**, and `FormatGuess` ([lock](../_notes/terminology.md):270) and `StreamHint` (:471) **already have §2 rows** | **fourteen** need rows; `04`:319's "ten of those names" is a third count of a different subset |
| `07#D1` (:633) | eleven store names | eleven, none in §2, all eleven offered by `07`'s New terms | correct as written |
| `08#D1` (:648) | sixteen runtime types | sixteen, none in §2; thirteen offered by `08`'s New terms; `CacheIndex`, `Dep`, `DepKind` offered nowhere | three must be authored, not merged |
| `18#2` (:727) | six OUT class names | six, none in §2, all six offered by `09`'s New terms; overlaps `09#Q7`'s eleven | correct as written |

**The true size of the pass is 313 rows, not "around 110"** ([17](../17-risks.md) §7.6's ADR-1 cell).
[glossary.md](../glossary.md):5-7 states the arithmetic and it was reproduced mechanically: 715 index
rows = 402 of the lock's 407 plus **313 coined by the nineteen documents' New terms sections**, and
glossary Q10 (:1156) resolves the missing five to 720. The pass is a **merge**, not an authoring job:
of the names the register itemises, only sixteen are offered by no document — `DriverGuard`, `Scope`,
`OperatorABC`, `RunManifest`, `Candidate`, `CacheIndex`, `BlobStore`, `Dep`, `DepKind`, `ArtifactRef`,
`RejectCode`, `Cite`, `Addr`, `InstallReport`, `FileAction`, `CalStatus`. **Rule 2 fails once:**
`ow_segment_head` has a §2 row and appears in none of the nineteen documents (glossary Q1, :1071).

**Check 3 has no machine-readable input at all.** [12](../12-performance.md):1901-1914 records that
check 3 "fails the charter, the lock file itself, and every document that states a prohibition", and
[17](../17-risks.md):687 carries it as `12#D1`. The diagnosis is right and incomplete. §3's left
column is **prose**: of its 60 rows, **17 qualify the rejected name with a sense** ("`Verdict` (for
the cache read outcome)", "`Evidence` (for a served answer block)"), **25 pack more than one token
into one cell**, and **2 carry no backticked token at all** (`"port" for a TCP listener`; `a pydantic
model in the model layer or for driver config`). A string check over that column cannot represent
"rejected *in this sense*", which is what most of §3 says. Measured over the nineteen documents plus
the charter, the lock and the glossary, after removing the fourteen ambiguous entries glossary Q5
(:1113) names: **821 lines carry a whole-token §3 hit inside a code span, and 497 survive `12#D1`'s
proposed negation-marker exemption**. The lock's own §4 bullet at `:606` writes "a loopback TCP
**port** for any framework-internal channel" against its own `:555` row — `14#6`
([17](../17-risks.md):707) pointed at the lock rather than at the charter.

**This is a decision, not a repair,** because the pass cannot be executed without ruling on where 715
definitions live: copying 313 New-terms rows into §2 while [glossary.md](../glossary.md)'s index keeps
its own `Definition` column creates 715 double-homed facts — charter §8 rejection criterion 23
("binds one name to two types, or one config key to two homes", [01](../01-principles.md):1173) and
INV-21's own subject. And five names are bound to two types; picking a winner without saying what the
loser becomes leaves the lock inconsistent in the direction rule 1 does not check.

## Decision

**1. The lock §2 takes 720 rows and gains a fifth column.** The 313 New-terms rows merge in verbatim,
plus the five glossary Q10 names (`Basis`, `FormatTokenPair`, `RankedGuess`, `format_tokens`,
`ground()`). §2's columns become `Term | Kind | Definition | Specified in | Rejected`. Sixteen names
are authored rather than merged, each in the document that owns it. `ow_segment_head`'s DDL returns
to [07](../07-store-and-retrieval.md) §3 beside `segment` and `segment_block`, closing rule 2.

**2. `terminology.md` §2 is the sole home of a definition; `glossary.md` is generated.** The
glossary's `Definition` and `Kind` columns become output of `tools/gen_glossary.py` from §2 and are
byte-diff gated. Its `Specified in` column, its "Do not confuse" (:167) and "Collisions resolved"
(:298) sections are its own facts and stay hand-written. One fact, one home.

**3. The Kind vocabulary gains `signal` and `driver-id`, keeps `index`, drops `gate`** (glossary Q4,
:1103). `index` earns rows for `block_cite`, `edge_bound` and `cache_gc`, which §1 already names.
`gate` goes: `tools/gates.toml` is the G-series' register and `G27` clause d2 resolves a `G<n>` from
it ([11](../11-repo-layout.md):2244), so a lock row would be a second home.

**4. Rule 1 widens from "`class` name" to "declared type name", mechanically.** `09#Q7`
([17](../17-risks.md):656). A name needs a §2 row when it appears in a `python` fence as a `class`
statement, a `NewType(...)` or `TypeAlias` target, a `Literal[...]` alias name, an annotation, a
string forward reference in a signature, or a `Protocol` body; or in a SQL fence as a `CREATE
TABLE`/`VIEW`/`INDEX` name. The parser is not new work — Tier 0 AST-parsed all 150 `python` fences.

**5. §3 becomes three columns and check 3 is rewritten.** Each of the 60 rows splits into
`token` (one backticked identifier per row; the 25 multi-token cells become separate rows),
`sense` (free text — the parenthetical the row already carries), and `bannable_by_name` (a boolean:
true where the row names a thing the framework bans, so a document must be able to name it).
Check 3 flags a **whole-token occurrence inside a code span** of a §3 `token`, and exempts it when
(a) the row's `bannable_by_name` is true, or (b) the line carries a negation marker from the closed
list `{no, not, never, rejected, rejects, forbidden, banned, struck, instead of}` matched as a whole
token, or (c) `tools/lock_allow.toml` carries an explicit `file:line:token` triple. The allowlist is
a **ratchet**: `tools/gates.toml` holds its length and `G27(c)` fails on an increase.

**6. `G27(c)` turns on when four conditions hold**, and not before: §2 covers every name rule 1's
parser finds; §3 carries the three columns; `tools/lock_allow.toml` exists; and the residual on a
clean tree is zero. Until all four hold, `G27(c)` is registered in `tools/gates.toml` with
`enabled = false` and a `blocked_by = "ADR-1"` note, so its absence is visible rather than assumed.

**7. The five collisions, each with what the loser becomes.**

| # | name | winner | loser becomes | authority |
|---|---|---|---|---|
| 1 | `Scope` | the runtime's ingest scope (charter D6) — older and more widely referenced | L2's block selection becomes **`ViewScope`**, defined in [03](../03-document-model.md) §16.1 | `03#Q1`, [17](../17-risks.md):589; [03](../03-document-model.md):2933 recommends it |
| 2 | `title` | `Kind.TITLE`, a document or slide title | the column becomes **`block.label`**, and its wire key with it | `03#Q9`, [17](../17-risks.md):597; §5 X17's rule |
| 3 | `max_blocks` | `PackSpec.max_blocks = 60`, which really is a Block count ([07](../07-store-and-retrieval.md):2254) | `[retrieval.vec] max_blocks = 250000` becomes **`max_segments`** — it is a segment ceiling ([07](../07-store-and-retrieval.md):3293) and §1's rule puts the unit in the name | `07#D2`, [17](../17-risks.md):634 |
| 4 | `Unit` | the `unit` table, the Roster ([lock](../_notes/terminology.md):488) — L2 and P2 DDL | OUT's addressable output unit becomes **`OutUnit`**. Compounds are untouched: `UnitOutcome`, `UnitRef`, `UnitKey`, `artifact_unit`, `unit.part_count` already disambiguate; only the bare name collides | `18#2`, [17](../17-risks.md):727 |
| 5 | `Operator` | the Protocol in `omniweave_core/operator.py` ([08](../08-runtime.md) New terms) | **`OperatorABC` is struck** and enters §3 — a Protocol is not an abstract base class, and the suffix is wrong on its face | `02#1`, [17](../17-risks.md):578; carriers: charter `:323`, [02](../02-architecture.md):234, [18](../18-api-sketch.md):838 |

**Case pairs are not collisions, and the rule is stated once.** §2 already carries six
`PascalCase`/`snake_case` pairs — `Block`/`block`, `Diag`/`diag`, `Doc`/`doc`, `Part`/`part`,
`Run`/`run`, `Segment`/`segment` — each **one concept in two Kinds**. §1 gains the sentence: a type
and its table or column take two rows when they denote one concept, and are a collision when they
denote two. `Cite`/`cite` and `Addr`/`addr` are NewTypes over their own column (charter
`:1272-1273`) and take two rows. `Unit`/`unit` denoted two concepts, which is why it is row 4 above.

**8. `13#Q-Q4` ([17](../17-risks.md):693).** `Runner` (concept, merged from
[13](../13-quality.md):2012) and `CalStatus` (enum, authored at [13](../13-quality.md) §9) take §2
rows; the (c) half is erratum `E26`. `13`'s embargo — "no plan document should write `Runner` as a
Python class name until the lock row lands" — lifts when this ADR is applied.

**9. Four charter errata**, written here for a later stage to insert into charter §9.2:

| row | locus | what the charter says | what supersedes it |
|---|---|---|---|
| `E24` | `:6157` | "D8 defines EXACTLY TWO reserved keys in L2's `x` bag" | **three**: `{x.ow.el, x.ow.cite, x.ow.unknown}`. Sole home [03](../03-document-model.md) §15.2; the third is L2's (`03`:2636), the first two OUT's. `09#Q6`, [17](../17-risks.md):655 |
| `E25` | `:323` | `operator.py  OperatorABC · OperatorIdentity · …` | `Operator`, per decision 7 row 5. Sole home [08](../08-runtime.md) §6.1 |
| `E26` | §D10's `unpinnable` paragraph | the "may not contribute a `[[quality.benchmark]]` row" rule, stated inside it | the rule keys on `weights_revision`, not on `ReplayClass`. Sole home [13](../13-quality.md) §7.2 |
| `E27` | `:8536`, and `:220` | "No loopback TCP **port** for omniweave's own IPC" | "listener", per §3 `:555`. Optional — `bannable_by_name` covers the charter without it. Claimed because `14#6`'s closer asks for the wording reconciliation in the same change |

The lock's own §4 bullet at `:606` is corrected to "listener" in this pass. The lock is not the
charter and may be edited; that is the cheap half of `14#6`.

## Alternatives rejected

**Split the pass: land the rows now, fix check 3 later.** The strongest case is scheduling — the rows
are a mechanical merge one engineer can do in two days, while §3's restructure needs a judgement call
on 60 rows. Rejected because [17](../17-risks.md):578 and :687 are two *independent* blockers on the
same gate, so landing one leaves `G27(c)` off and the other invisible, and because a lock at 720 rows
with a check 3 that fires 497 times is worse than a lock at 407: the false-positive rate teaches
reviewers to ignore the gate.

**Implement `12#D1`'s fix as written: ignore an occurrence inside a code span.** This is the register's
own recommendation and it argues from the right observation — the prohibitions the check flags are all
written in backticks. Rejected because in this plan **every** name is written in backticks, so "ignore
inside a code span" makes check 3 vacuous: a document that introduced `chunker` as a real identifier
would pass. The register offers the alternative in the same cell (§3 "gains a `bannable_by_name`
column") and that is the half worth keeping. Decision 5 is the conjunction of `12#D1`'s negation-marker
clause and glossary Q5's "inside backticks" clause, which point in opposite directions and are each
incomplete alone — glossary Q5 clears `Item budgets` and flags the charter's `--force`; `12#D1` clears
the charter's `--force` and flags nothing at all.

**Make the glossary the source and shrink the lock to §1, §3 and §4.** Genuinely close: the glossary
is better organised, carries `Specified in`, and its "Do not confuse" sections do work no lock row
does. Rejected on authority — [_notes/terminology.md](../_notes/terminology.md):3 says "binding,
alongside `charter.md`", the glossary says no such thing, and `G27(c)` is specified against §2
([01](../01-principles.md):589). Moving binding text into a non-binding document to improve its
presentation trades a settled authority for a layout preference.

**Keep `Unit` for OUT and rename the table.** `Unit` is printed throughout [09](../09-generation.md)
§3.7 and in `18`'s signatures, and `OutUnit` reads worse. Rejected because `unit` is P2 DDL
([16](../16-roadmap.md) §3, weeks 16-38) referenced by `unit_uri`, `unit_part`, `UnitKey`,
`artifact_unit` and `unit.part_count`: a table rename after the freeze is a migration, a type rename
in `omniweave_core.out` is an edit. Cost decided the direction, not taste.

**Leave `block.title` alone.** [03](../03-document-model.md):3021 calls it "a reviewer's call" and
notes the two never co-occur, so nothing breaks. Rejected on timing, which that same line concedes:
"one migration and one wire key; it is cheap now and expensive after release 1". This ADR lands
before the P2 freeze and is the last cheap moment.

## Consequences

| # | obligation | price |
|---|---|---|
| 1 | [_notes/terminology.md](../_notes/terminology.md) §2 goes 407 → 720 rows, gains a `Specified in` column, absorbs 313 New-terms rows and authors sixteen | 2.5 ed |
| 2 | §3 goes 60 prose rows → ~85 `token`/`sense`/`bannable_by_name` rows; §1 gains the case-pair sentence; §4's `:606` bullet says "listener" | 1 ed |
| 3 | `tools/lock_check.py` implements rules 1-3 as decided; `tools/lock_allow.toml` is created with the residual and its length ratcheted in `tools/gates.toml` | 1.5 ed |
| 4 | five collision renames in the documents that carry them: `ViewScope` ([03](../03-document-model.md) §16.1); `block.label` ([03](../03-document-model.md), [07](../07-store-and-retrieval.md)'s DDL, `wirekeys.toml`); `max_segments` ([07](../07-store-and-retrieval.md), `tools/config_axes.toml`); `OutUnit` ([09](../09-generation.md) §3.7, [18](../18-api-sketch.md)); `Operator` ([02](../02-architecture.md):234, [18](../18-api-sketch.md):838) | 0.75 ed |
| 5 | four errata written into charter §9.2 by a later stage; `tools/gen_glossary.py` plus the glossary's generated columns | 0.25 ed |

**What changes shape.** `block.title` is a P2 DDL column and a wire key, so consequence 4 must land
before the P2 schema freeze or become a migration — the same deadline ADR-5 carries. `[retrieval.vec]
max_blocks` is a `tools/config_axes.toml` pattern, so **ADR-3's edit to that file must be written
against `retrieval.vec.max_segments`**; ADR-1 is priority 1 and ADR-3 priority 2, so the order is
already right, and this is the one place the two touch the same line.

**What becomes harder, and what this does not close.** Coining a name now costs a §2 row *and* a
`Specified in` reference, and `G27(c)` refuses the commit that omits either — that is the point. A
future reader must not re-propose "just add the rows" without §3's restructure, and must not add a
row to `tools/lock_allow.toml` without deleting one. `R-O9`'s first trigger (`charter_defects_open`
exceeding the ADR count by more than ten) is arithmetic over all twelve ADRs, not this one, and
`G27(d)`'s ownership is ADR-2's.

## Open

**Whether the sixteen authored names are sixteen.** The count is exact against the New-terms tables
and the lock, and approximate against [glossary.md](../glossary.md)'s index, which harvested prose
definitions this ADR did not re-parse. **Interim position:** the pass authors sixteen and populates
`Specified in` for all 720; any name the glossary already defines is a merge, so the price falls
rather than rises. **Fallback:** if the residual exceeds twenty-five, the pass splits by owning
document and each document's rows land with that document's next edit — `04#Q3`'s own closer ("lock
rows in the change that merges [04]") applied to all nineteen.

**Whether `bannable_by_name` is a boolean or a scope list.** A row marked bannable is exempt
everywhere, which loses the ability to catch a genuine misuse of `--force` or `pass_with_warnings`.
The evidence that would close it is the residual after the first clean `G27(c)` run: if more than five
bannable rows show a real misuse, the column becomes `bannable_in = ["<file>", …]`. Recorded rather
than decided because the run has not happened and a boolean is cheaper to widen than a list is to
narrow.
