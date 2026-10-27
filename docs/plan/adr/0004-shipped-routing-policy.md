# ADR-4 — The charter's D4 policy block is retired law, and `G27(a)` gains the two clauses that would have caught it

**Status:** Accepted · **Priority:** 8 of 12 · **Price:** 2 ed
**Deadline:** no ordering constraint; clause `a2` lands with P1's gate harness, clause `a3` at the P5 exit
**Discharges:** `05#1`, `05#4`
**Charter errata claimed:** `E42` (block `E42`-`E47`, five unused)
**Supersedes:** none
**Blocks / unblocks:** blocks nothing downstream — and that is the finding. Unblocks charter §8
rejection criterion 21 ("prints a TOML or JSON block in a charter or plan document that does not
parse (G27)"), today a promise with no enforcer, and closes
[05](../05-ingest-and-routing.md) §Open questions items 1 and 4.

## Context

The two register rows, quoted verbatim from [17-risks.md](../17-risks.md) §7.3:

> `05#1` | `Rung` casing in a policy file contradicts the lock | defect | `router` | a one-line
> amendment stating that `policy.d/*.toml` is author-facing config, not a wire | v0.1; ADR-4
> — [17](../17-risks.md):611

> `05#4` | three mechanical defects in the shipped policy | defect | `router` | the charter running
> its own `tomllib.load` gate and `ow route lint` over its own D4 block. One is dangerous rather
> than cosmetic: `repair.never-escalate-furniture` reads `block.type`, which has no PDF provider, so
> **without `on_unknown = "match"` the furniture guard is silently off on the PDF path** and one
> flagged footer spawns the inference server for a clean document | v0.1; ADR-4
> — [17](../17-risks.md):614

**The scope this ADR inherited is wrong, and it was measured rather than assumed.**
[final-review.md](../_notes/final-review.md) §8 item 10 scopes ADR-4 as repairing "the shipped
policy" — nine `on_unknown`, two unparseable TOML blocks, four dead `GATE` rules. Every ` ```toml `
fence in `charter.md` and in `00`-`18` was extracted and run through `tomllib.loads`, and every
`[[rule]]` array walked against [05](../05-ingest-and-routing.md) §5.1's fifty-four-row signal
registry under `ow route lint` check 4's own predicate (§4.5, `OW-P-004`: a nullable read with no
`on_unknown`, `exists`-only exempt).

| measured | charter D4 fence `:2576`-`:2783` | [05](../05-ingest-and-routing.md) §4.4 fence `:1203`-`:1678` |
|---|--:|--:|
| `[[rule]]` blocks | 15 | 40 |
| rules declaring `on_unknown` | 2 | 17 |
| `tomllib.loads` | **parses** | parses |
| check 4 (`OW-P-004`) failures | **7** | **0** |
| check 1 (`OW-P-001`) failures against §5.1 | 0 | 0 |
| co-rung `GATE` rules | 4 | 12, split into action plus modifier per §4.2 |

Three corrections follow, and each changes what this ADR is.

1. **Nothing in the plan fails to parse.** Seventy-three fences scanned, seventy-three parse — the
   charter's D4 block included. TOML 1.0.0 permits a newline between an inline table's braces where
   it falls inside a value, and `:2739`'s falls inside an array literal. `G27(a)` as written passes
   the exact block the plan calls defective, and criterion 21 as worded names a failure the corpus
   does not have.
2. **One newline-spanning inline table, not two, and it is a `when`, not a `then`.**
   [05](../05-ingest-and-routing.md) §Open questions item 4(b) says "Two `then = {…}` inline tables
   span a newline, which the charter's own rule forbids and `tomllib` rejects". One `when` spans a
   newline, `tomllib` accepts it, and the rule it breaks is the charter's own **style** rule —
   stated four times as a comment (`charter.md`:465, `:1857`; [04](../04-driver-system.md):840,
   `:885`) and enforced nowhere.
3. **Seven rules fail check 4, not nine.** `repair.never-escalate-furniture` is one of them, so the
   dangerous half of `05#4` is real and is in the charter.
   [05](../05-ingest-and-routing.md) §4.4's own copy carries `on_unknown = "match"` with a comment
   saying the declaration is load-bearing (`:1584`, `:1591`).

**Why this is a decision and not a repair.** The defective block is `charter.md` §D4, immutable by
the charter's own §9 preamble: "No line of §1-8 was edited during stage 10's repair work or stage
11's, and none will be." The live policy is already correct on all three counts, which
[05](../05-ingest-and-routing.md) §Open questions item 4 states in those words — "three mechanical
defects **this document repairs**". Nothing is left to repair. What is left is a choice about
**status** (which of two printed policies binds) and one about **enforcement** (what stops the
charter's block being transcribed a second time, given that `tomllib` will not).

The second is not hypothetical. The same pathology sits one type away:
[D2-docmodel.md](../_notes/rulings/D2-docmodel.md):265 prints
`CREATE UNIQUE INDEX block_cite ON block(doc_ord, gen, cite);` directly beneath `block_addr`'s
correctly gen-keyed index; `charter.md`:8343 carries that spelling forward while `charter.md`:1081
carries the right one. That is the defect [ADR-6](0006-citation-and-retrieval-surface.md)
discharges, and it entered the way this one did.

## Decision

### 1. The charter's D4 policy block is retired in favour of `05` §4.4 — erratum `E42`

The five parts [`README.md`](README.md) §4 requires of a charter-amending ADR:

| # | part |
|---|---|
| 1 | **Locus:** `charter.md` §D4, the ` ```toml ` fence at `:2576`-`:2783`, whole |
| 2 | **Search phrase:** `id      = "repair.never-escalate-furniture"` |
| 3 | **Old text:** the fifteen-rule shipped policy as printed there, `policy_name` through `degrade.marked-fallback`. **Superseded by** [05](../05-ingest-and-routing.md) §4.4, its sole home |
| 4 | **Erratum row:** `E42` |
| 5 | **Ruling re-issued:** none. [D4-router.md](../_notes/rulings/D4-router.md) states the grammar and the rungs correctly; the defects entered in transcription, not in the ruling |

The row retires the block **in whole, not clause by clause**, on four counts: 7 check-4 failures
against 0; 15 rules against 40; four co-rung `GATE` rules that a single first-match-wins list cannot
deliver, which §4.2's action/modifier split resolves; and one inline table spanning a newline at
`:2739`. A reviewer reading that block for the shipped policy is reading retired law. `E42` does not
touch §8 criterion 21, which stands and which decision 2 makes enforceable for the first time.

### 2. `G27(a)` gains clauses `a2` and `a3`, in `tools/gate_docs.py`

`G27` already carries clauses `(a)`-`(d)` and the G-series cardinality is
[ADR-2](0002-invariant-and-gate-registers.md)'s question (`11#OQ-10`, `01#1`). **No new `G` number
is allocated here.** Both clauses attach to `(a)`, whose subject is already "every fenced block
parses under the parser its fence names".

**Clause `a2` — one key per line.** For every ` ```toml ` fence in `charter.md` or a plan document,
after `tomllib.loads` succeeds: outside comments and strings, the running count of `{` minus `}`
must be zero at the end of every physical line. A line ending at brace depth ≥ 1 fails, naming file,
line and fence. This is the charter's own four-times-stated style rule given an enforcer. **Run over
the corpus exactly as specified it scans 73 fences and reports exactly one line, `charter.md`:2739**
— no false positives across the nineteen plan documents, 43,611 lines as this stage opened, plus
8,762 of charter. ~40 lines in
`tools/gate_docs.py`, landing with P1's gate harness ([16](../16-roadmap.md) §3, weeks 10-22).

**Clause `a3` — a policy fence is linted, not merely parsed.** Every ` ```toml ` fence that parses
to a table containing a `[[rule]]` array is additionally run through `ow route lint` checks 1, 2, 4,
5, 7, 9, 10 and 12 ([05](../05-ingest-and-routing.md) §4.5) against the shipped registry and the
shipped `[drivers] enabled`. Checks 3, 6, 11 and 13 are excluded: they read `retrieval.toml`, driver
cards or a budget block a documentation fence need not carry.

`a3` cannot land before P5, where the router ships ([16](../16-roadmap.md) §3 maps
[05](../05-ingest-and-routing.md) to P5), so the interim is decided rather than deferred:

> **Interim:** from P1, `tools/gate_docs.py` runs a standalone check 4 over `[[rule]]` fences,
> reading nullability from [05](../05-ingest-and-routing.md) §5.1's `null` column parsed out of the
> markdown table — ~30 lines, no import of `omniweave.route`.
> **Pre-committed fallback:** at the P5 exit the standalone check is **deleted** and `a3` replaces
> it wholesale. It is not maintained in parallel; two implementations of one check is the second
> enforcer §8 criterion 19 names.

### 3. `Rung` casing: `policy.d/*.toml` is author-facing config — and the amendment is to the lock, not the charter

`SCREAMING_SNAKE` is the authored spelling. `rung = "GATE"`, `escalate_to = "PAGE"`,
`skip_rungs = ["REPAIR"]` and `--max-rung <RUNG>` are correct as
[05](../05-ingest-and-routing.md) §4.4 writes them. The policy compiler accepts **exactly one**
spelling and rejects a lower-case `Rung` at load, on the path that already rejects a backward
`escalate_to` value (§4.2); [05](../05-ingest-and-routing.md) allocates the `OW-P-` numeral from the
register it owns, which currently reaches `OW-P-022`.

**`05#1` and [05](../05-ingest-and-routing.md) §Open questions item 1 both name the wrong
document.** Both call for "a one-line **charter** amendment". The charter states no casing rule: the
convention is [terminology.md](../_notes/terminology.md) §1's `enum member` row (`:40`) and its §3
rejection row (`:577`), and `charter.md`:6473 defers to it explicitly ("because the lock's rule
is…"). The instrument is a **lock amendment**, and the lock is
[ADR-1](0001-terminology-lock-bulk-pass.md)'s. ADR-4 decides the substance and hands ADR-1 the text:

- §1's `enum member` row loses "there is **no exception**" and gains a scope: the lower-case wire
  value governs JSON, generated schemas, DB columns and every byte-diff-gated generated artefact. It
  does not govern an **author-facing config artefact** — `.omniweave/policy.d/*.toml`,
  `omniweave.toml`, `pricebook.toml`, `retrieval.toml` — where the enum member name is what the
  author reads against §4.2's ladder.
- §3's row `an upper-case Rung on the wire` → `the lower-case member name` is **unchanged**. Its
  qualifier "on the wire" is already the right scope; §1's absolute is what contradicts it, and §3
  is right.

No wire is violated today: `route_decision.rung` is stored as an INTEGER and every generated
artefact emits the lower-case member name.

## Alternatives rejected

### Repair the charter's D4 block in place

The strongest case: `charter.md` is the first document a new contributor reads, and a reader who
reaches `:2650` before reaching §9 reads a defective policy with nothing on the page to say so. A
twenty-four-row errata table is a worse index than a correct block.

Rejected on the charter's own §9 preamble and `E-Q1`'s fallback: "Folding a correction into §1-8
destroys the record of what was decided and why, which is the only thing §1-8 is for." The four
co-rung `GATE` rules are the proof — they are *why*
[05](../05-ingest-and-routing.md) §4.2 has an action/modifier split at all, and a silently corrected
block would leave that split looking like unmotivated complexity. §9.1's locus rule keeps the
erratum reachable from `:2650` by phrase search.

### Do nothing: the charter's block is not executed, so a defective policy in it costs nothing

Genuinely close, and it deserves the strong form. `policy_digest` is taken over the shipped
`policy.d` bytes; no CI job loads a markdown fence; the block cannot mis-route a document because
nothing runs it. [`README.md`](README.md) §7.1 already classes ADR-4 as unordered on this reasoning.

Rejected for two reasons visible only in how the plan was written. The charter's blocks **are** the
source the plan documents were transcribed from, and the transcription is demonstrably lossy —
`block_cite` above. And §8 criterion 21 already promises this gate while §8 criterion 22 rejects "a
warning that cannot fail": a stated rejection criterion with no enforcer *is* that warning. Doing
nothing fails criterion 22 in order to avoid enforcing criterion 21.

### Allocate `G28` rather than extending `G27(a)`

The case: a distinct number makes a CI failure legible without reading clause letters, and `G27`
already carries four unrelated checks under one number.

Rejected because [17](../17-risks.md) §7.7 records what happens when two documents allocate in one
series in parallel — "adjacent blocks by luck rather than by rule" — and the G-series count is live:
whether it is closed at 27 or open to `tools/gates.toml` is
[ADR-2](0002-invariant-and-gate-registers.md)'s `11#OQ-10`. An ADR at priority 8 allocating into a
series an ADR at priority 7 is renumbering is the collision, not the fix. Clause letters collide
with nobody.

### Make the gate `ow route lint` only, and drop clause `a2`

The case: one enforcer for one property, no second TOML tokenizer, and check 4 is already specified
with a code.

Rejected twice over. `ow route lint` ships at P5 and `G27` runs from P1, so a lint-only gate cannot
run during the twenty weeks in which the documents are edited. And `ow route lint` operates on a
**loaded** policy — a `dict` — so it can never observe a lexical property of the source text. The
one-key-per-line rule is unreachable from any semantic checker by construction, which is exactly why
`tomllib` did not catch it and why criterion 21's own wording misses it.

### Take the register row literally and repair nine `on_unknown` declarations in `05` §4.4

The case: it is what [final-review.md](../_notes/final-review.md) §8 item 10 instructs, and an ADR
overriding its own brief owes a reason.

Rejected by measurement: `05` §4.4 has zero check-4 failures and no rule there to repair. Adding
declarations would put `on_unknown` on rules whose `when` is `exists`-only, which check 4's
exemption exists to permit and which [05](../05-ingest-and-routing.md):990 explains — `{exists:
bool}` is total, so a declaration there is dead configuration.

## Consequences

| obligation | locus | price |
|---|---|--:|
| `charter.md` §9.2 gains row `E42`, inserted at its line-number locus per §9.1 | §9.2 table, locus `:2576` | 0.2 ed |
| `tools/gate_docs.py` gains clause `a2` (~40 ln) and the interim standalone check 4 (~30 ln) | [11](../11-repo-layout.md) §1.8, `:47` | 1.0 ed |
| `tools/gate_docs.py` gains clause `a3`; the interim check is deleted in the same commit | at the P5 exit | 0.3 ed |
| [11](../11-repo-layout.md)'s `G27` gate-table row (`:1529`) and the `:47` tree comment name clauses `a2` and `a3` | [11](../11-repo-layout.md) §1.8, §11 | 0.2 ed |
| [05](../05-ingest-and-routing.md) §Open questions items 1 and 4 close, item 4 recording all three corrections (seven not nine; `when` not `then`; one not two; `tomllib` accepts it) | [05](../05-ingest-and-routing.md):3278-3311 | 0.3 ed |
| [`README.md`](README.md) §7's ADR-4 row moves `proposed` → `accepted`; `charter_defects_open` decrements by 2 | [`README.md`](README.md) §5, §7 | — |
| **total** | | **2.0 ed** |

**Handed to [ADR-1](0001-terminology-lock-bulk-pass.md), not priced here:**
[terminology.md](../_notes/terminology.md) §1's `enum member` row (`:40`). ADR-1 owns every lock
edit; a row coined outside its bulk pass fails the lock's own CI rule 1 in both directions (`02#1`).

**What becomes harder.** Every TOML fence written into a plan document must keep each inline table
on one physical line, including one whose value is a ten-member array — the
`repair.never-escalate-furniture` shape. The remedy is the plan's own house style: a sub-table,
which `charter.md`:577 and `:1857` both name ("a sub-table, NOT a multi-line inline table").
[05](../05-ingest-and-routing.md) §4.4 writes forty rules without needing it once.

**What a future reader must not do.** Read the charter's D4 block as the shipped policy; allocate a
new `G` number for a documentation check; re-open `Rung` casing as a wire question, because
`route_decision.rung` is an INTEGER and no generated artefact emits `"GATE"`; or keep the standalone
check 4 alive after clause `a3` lands.

## Open

**Whether `tools/gate_docs.py` may import `omniweave.route` at all.** Clause `a3` calls
`ow route lint`'s checks from the gate harness. INV-4 and the registry's own comment
([05](../05-ingest-and-routing.md):1975 — "read by the import-free `tomllib` loader, never by
importing a provider") constrain the *policy loader*, not the *harness*, and no document says
whether the harness is under the same rule. **Closing evidence:** [11](../11-repo-layout.md) §1.8
stating whether `tools/` may depend on `packages/`. **Pre-committed fallback:** if it may not, `a3`
shells out to the installed `ow route lint` and asserts on its exit code — one subprocess per policy
fence, and the check stays in one implementation, which is the property `a3` exists to guarantee.
