# ADR-5 — The byte-exactness chain: `nfc()` proves INV-10, the `origin_span` rung keeps three values and gains an enforcer, `wirekeys.toml` appends to twenty-nine, and only `DocSink` writes a `part` row

**Status:** Accepted · **Priority:** 3 of 12 · **Price:** 5 ed
**Discharges:** `03#Q2`, `03#Q3`, `03#Q8`, `02#6` (defect); `03#Q5` (adjacent)
**Charter errata claimed:** `E48`-`E53` (block `E48`-`E53`, all six used)
**Supersedes:** none
**Blocks / unblocks:** unblocks `Q-G6`/`V01-5` (`span_exact_rate == 1.000`, [00](../00-vision.md):706) by giving its predicate a normaliser that separates the top two rungs. Must land before the P2 schema freeze ([16](../16-roadmap.md) §3, weeks 16-38): `tools/wirekeys.toml` **is** the Block wire, and appending after the freeze costs a migration rather than an edit. Blocked by ADR-1 for one name only — `nfc()` needs a terminology-lock row, and `02#1`'s closer is one bulk pass after the documents land.

## Context

Four register rows sit on one chain — a Block's text, the bytes it came from, the function that
compares them, and the wire that carries the answer. Quoted from [17-risks.md](../17-risks.md) §7.3:

- `03#Q2` (:590) — "INV-10's `bytes` branch names the wrong normaliser and collapses two tiers |
  defect | `model` | an ADR choosing between the charter's `normalize_k` and the narrower normaliser
  the tier split needs; [13](../13-quality.md)'s `normalize_eval()` is the third normaliser in the
  family and must not be confused with either | v0.1 — it is an INV-10 precondition"
- `03#Q3` (:591) — "`tools/wirekeys.toml` was frozen at 22 keys; a Block needs 29 | defect | `model` |
  seven rows added to `wirekeys.toml` in the same change | v0.1"
- `03#Q8` (:596) — "`Capabilities.origin_span`'s middle rung has no `quote` tier | defect | `model` |
  an ADR either collapsing the rung or giving it a tier | v1.0"
- `02#6` (:583) — "does `op.identify` write `part` rows or only `unit.part_count` | defect | `model` |
  one sentence in [08](../08-runtime.md) or [03](../03-document-model.md) naming the inserter | v0.1"
- `03#Q5` (:593, adjacent) — "`MAX_QUOTE_BY_OS_KIND` puts `pixels` at `RECONSTRUCTED` | decision |
  `model` | a decision on whether a pixel-derived text run may ever claim `NORMALIZED` | v1.0"

**What is true today.** `NORMALIZED = 3` is *defined* as "equal to the source under `normalize_k`" and
`VERBATIM = 4` as re-derivable from retained bytes ([03](../03-document-model.md) §8.3). INV-10's
`bytes` branch is written `normalize_k(part_bytes[a : a+len])[0] == block.text` at six sites: charter
`:81` (INV-10 itself), `:1168` (the `part` DDL comment), `:1453` (the card commentary), `:8017` (X8's
table), [03](../03-document-model.md) §7.2 and §17 P7, and [07](../07-store-and-retrieval.md) §8.1.
`normalize_k` is NFKC **plus casefold** plus five more operations
([06](../06-structure-extraction.md) §1.7). Two consequences follow mechanically: a block whose text
is `"abc"` proves `VERBATIM` against source bytes reading `"ABC"`, and the top two rungs carry the
same predicate, differing only in whether the part was retained. `Q-G6` gates `span_exact_rate` at
1.000 over exactly that predicate. Charter errata `E1`, `E2` and `E13` already repaired three of those
loci for the *type* error — the missing `[0]` — and each says in terms "INV-10 itself is unchanged",
so the semantic defect survived the repair, on the record.

**Why this is a decision and not a repair.** The edit is one word and cannot be made by edit. Three
loci are in an immutable charter and already carry errata saying the opposite;
[13](../13-quality.md) §8.2 names `normalize_k` as INV-10's definition and uses that naming to justify
why the evaluator needed a *second* normaliser; and the family already has three members, so picking
a fourth decides what the ladder's rungs mean. The other three rows ride with it because `Q-G6`'s
denominator, the wire that carries `qt`, the card rung gating `achieved.origin_span` and the `part`
row the proof re-reads are one chain.

## Decision

### 1. INV-10's `bytes` branch reads `nfc(decode(...))`, and `nfc()` gets a definition

**Extends the charter.** At every site, the `bytes` branch becomes:

```python
nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text
```

`normalize_k` leaves INV-10 entirely and stays in grounding, where casefolding is the point. The three
branches now agree: `bytes` decodes and NFC-normalises, `nodepath` is
`nfc(node_text(part, os_path)) == block.text`, `glyphs` re-extracts "under NFC". Decode symmetry is
already an invariant ([03](../03-document-model.md) §7.2) — both sides read the same `os_codec`, error
policy included.

`nfc()` is used by [02](../02-architecture.md) §4.3, [03](../03-document-model.md) §7.2,
[07](../07-store-and-retrieval.md) §8.1 and the charter at `:1170` and `:8018`, and is **defined by
none of them**. It is defined here, once, in `omniweave_core/ident.py` beside `normalize_k`,
`normalize_key` and `fold_common`:

```python
def nfc(s: str) -> str:
    """unicodedata.normalize("NFC", s). No casefold, no Cf strip, no dash fold, no whitespace
    collapse, and NO back-map: canonical composition is the only length change, and INV-10's
    branches compare whole strings rather than locate an offset inside one. NOT normalize_k
    (grounding), NOT normalize_key (blocking keys), NOT normalize_eval (13 8.2)."""
```

**The ladder is ordered, and that becomes a property rather than an assumption.** NFKC is total and
canonically composing, so `nfc(d) == t` implies `normalize_k(d)[0] == normalize_k(t)[0]`: every
`VERBATIM` block also satisfies the `NORMALIZED` predicate. Asserted as **P-23** in
[13](../13-quality.md) §6 (`P-22` is the current maximum) over generated NFD, soft-hyphenated,
ligatured and case-varied pairs.

`NORMALIZED` keeps `normalize_k` — the right tolerance for a *claim* of sameness, which is all it is:
a declaration clamped by `MAX_QUOTE_BY_OS_KIND`, never a proof, since a block at `os_kind = none` has
no source to compare against. Only `VERBATIM` is proved, so only `VERBATIM`'s predicate narrows. The
evidence fixture is [03](../03-document-model.md) §18 Q2's own: a P7 case whose retained part reads
`ABC` and whose `block.text` is `abc`, which passes today and must fail.

### 2. `Capabilities.origin_span` keeps three values, gains no `quote` tier, and gains an enforcer

`Capabilities.origin_span: Literal["none","normalized","exact"]`
([03](../03-document-model.md) §2.9) is unchanged; no rung collapses and no sixth `Quote` tier is
added. `03#Q8`'s premise — "an ordered three-value field whose middle value changes nothing a gate
reads" — was checked and is **false in two places and true in one**:

| reader | what `normalized` changes | mechanical today |
|---|---|---|
| the `achieved.origin_span` rollup ([03](../03-document-model.md) §2.9) | "any `none` ⇒ `none`; else `exact` if every non-`pixels` block's branch re-verifies on the conformance sample, **`normalized` otherwise**" | yes — host-computed at `end_doc` |
| `byte_exact()` ([07](../07-store-and-retrieval.md) §8.2) | reads `doc.achieved.origin_span == "exact"`; a doc rolling up to `normalized` is one where a block **failed** re-verification, which is not the same fact as carrying no address | yes — `Q-G6` at 1.000 |
| `[store] retain_parts = "when_citable"` ([07](../07-store-and-retrieval.md) §8.1) | "retain a `part` iff the producing driver declared `origin_span` in `{exact, normalized}`" — retention roughly **doubles corpus storage** | no — it reads the **declared** card, and nothing proves the declaration |

The third row is the defect. `P15` (`achieved <= declared`) passes vacuously for a driver declaring
`normalized` and emitting `os_kind = 'none'` everywhere, because `achieved` then computes `none` and
`none <= normalized` holds; `P14`'s honesty assertions are written over absence (`text_span = false`,
`math = {}`, `assets = "none"`) and carry no `origin_span` clause; `P7` proves only `exact`. So the
middle rung is the one card field a driver may set for free, and it costs the operator a doubled
store. `retain_parts` must read the card rather than `achieved`, because retention happens during the
parse and `achieved` is computed at `end_doc` — the ordering forces the one card read
[07](../07-store-and-retrieval.md) §8.2 otherwise forbids.

**Extends the charter — a seventeenth driver-testkit property.** [03](../03-document-model.md) §17
gains **P17**, suite `capability`: *`origin_span = "normalized"` — for every body block on the
conformance sample, `os_kind <> 'none'` and `os_part IS NOT NULL`, and `locate(block)` returns a
`Locus` with `precision <= "block"` and `reason IS NULL`. A driver declaring `normalized` and emitting
no address fails. Re-verification is **not** asserted: a `normalized` address that re-verifies is an
under-claim, already caught by `P15`.* That is the middle rung's whole content as an assertion — an
address that locates and does not prove.

### 3. `tools/wirekeys.toml` appends the seven keys and holds twenty-nine

The seven are `c` (`cite`), `qt` (`quote`), `mt` (`method`), `ti` (`title`), `pl` (`payload`), `st`
(`state`), `dc` (`decision_id`) — exactly the set [03](../03-document-model.md) §3.1 prints, whose
table is the **sole home** of the mapping. The file moves to `model_version = "1.1"` and holds all
twenty-nine; the charter already stamps `model_version = "1.1"` on `meta` at `:969`, so the version
is not moved, only made consistent with the key count it implies.

This is an append, not a break. `tools/wirekeys.toml` is one of the six **append-only registers**
protected by squash-only merges and branch-up-to-date ([11](../11-repo-layout.md) §5.2, §8.3), so
adding rows is the legal operation and the diff is computable against the previous tag; a key is still
never reused, and retirement still runs §15.4's three phases into the file's `retired` table. `c` is
load-bearing rather than cosmetic: without it a `cite` cannot survive
`import(export(store)) == store` over the fixture corpus, so that check's fixture is what fails if the
append is dropped. Cited by property and not by number: [03](../03-document-model.md) §18 Q3 calls it
"gate G6", which is `00#V-Q8`'s defect — ADR-2 rules the round-trip check `G28` and leaves `G6` as
`ow schema emit --check`.

### 4. `DocSink.add_part` is the sole inserter of a `part` row

`op.identify` writes `unit.part_count` and the per-part `work` rows, and **never** an L2 `part` row.
Three facts force it, in ascending order of finality. (1) `part.sha256 BLOB NOT NULL` and
`part.byte_len INTEGER NOT NULL` ([03](../03-document-model.md) §13.1): `op.identify` does not read
bytes, so it can supply neither, and a NULL-tolerant variant is a DDL change to a charter table.
(2) `part.doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord)`, and `doc_ord` is assigned by
`DocSink.begin_doc` on first sight ([03](../03-document-model.md) §2.10) while `op.identify` runs at
hop 4 of the worked trace, before any parse ([02](../02-architecture.md) §4.1: `part_count = 42`,
"**No `parse.pdf` work row exists yet**") — on a first-sight document there is no `doc_ord` for the
foreign key to name. (3) L2 has one writer: `DocSink`'s eleven methods own it, `add_part` is one of
them, and its `blob` nullability **is** the retention policy in the signature (§2.10).

**The charter is not wrong; the phrase is overloaded.** D6 at `:3898` says "part rows are materialised
by `op.identify`", and its own module tree at `:3974` glosses the same step as "`op.identify`;
**part-row expansion** gated by the water mark" — one `work` row per part, keyed
`(unit_uri, unit_part, operator, op_version)`. "Part row" names two things: a row of the L2 `part`
table, and a `work` row whose `unit_part` is non-empty. `E53` retires the ambiguous sentence; the lock
gains the distinction through ADR-1's bulk pass.

### 5. `03#Q5` (adjacent): the `pixels` clamp stands, fallback pre-committed

`MAX_QUOTE_BY_OS_KIND[OsKind.PIXELS] = RECONSTRUCTED` is unchanged — an interim position with a
pre-committed fallback, which is `accepted` per [README](README.md) §6. The measurement that would
change it is [03](../03-document-model.md) §18 Q5's own closer: "a shipped driver with a legitimate
need to declare `NORMALIZED` from a pixel origin, with a stated verification procedure. Absent one,
the clamp stands." The cost is disclosed, not hidden: `Filters.min_quote = REFLOWED` excludes every
OCR block, and `corpus_card.verbatim_fraction` prints before any query runs. **Fallback:** if `F32`
([07](../07-store-and-retrieval.md) §Open questions) lands the achieved-exact fraction under ~20% and
`retain_parts` defaults to `never`, the clamp is *not* revisited — with no retained parts there is
even less to verify against, and `pixels` at `RECONSTRUCTED` becomes more correct, not less.

### 6. The charter amendment, in the five parts [README](README.md) §4 requires

Six loci, six errata, claimed from ADR-5's block `E48`-`E53` and written here for a later stage to
insert into charter §9.2. `E49`, `E50` and `E51` **supersede `E1`, `E2` and `E13`** at the same three
loci: those rows repaired the missing `[0]` and each states "INV-10 itself is unchanged", which this
ADR reverses. §9.2 orders rows by charter line number, so each new row sits beside the row it
supersedes and must say so in its `why` column.

| # | locus | search phrase | what the charter says | what supersedes it, and its live home | re-issues |
|---|---|---|---|---|---|
| `E48` | `:81` | `the byte slice equals the block text under` | INV-10's own `bytes` branch, in §2's invariant table | **ADR-5.** `nfc(decode(part_bytes[os_a : os_a+os_b], os_codec)) == block.text`. Home: [03](../03-document-model.md) §7.2 | **D2** |
| `E49` | `:1168` | `bytes    : normalize_k(part_bytes[os_a : os_a+os_b])` | the same proof, on the `part` DDL. **Supersedes E1** | ADR-5, as `E48` | D2 |
| `E50` | `:1453` | `normalize_k(part_bytes[a:a+len]) == block.text` | the same proof, in the card commentary. **Supersedes E2** | ADR-5, as `E48` | D2 |
| `E51` | `:8017` | `normalize_k(part_bytes[a : a+len]) == block.text` | X8's three-branch table. **Supersedes E13** | ADR-5, as `E48`. X8's three-branch *enumeration* is unchanged | D2 |
| `E52` | `:1597` | `{i,p,pa,o,k,rk,ly,t,ts,os,q,m,tr,sc,pd,od,oo,cd,ld,rb,rm,x}` | the twenty-two frozen wire keys | **ADR-5.** Twenty-nine at `model_version = "1.1"`; home [03](../03-document-model.md) §3.1. Frozen-ness and never-reuse unchanged | D2 |
| `E53` | `:3898` | `part rows are materialised by` | D6's execution decision | **ADR-5.** `op.identify` materialises `unit.part_count` and the per-part `work` rows; an L2 `part` row is inserted only by `DocSink.add_part`. Home [03](../03-document-model.md) §2.10 | **D6** |

## Alternatives rejected

**Keep `normalize_k` in INV-10 and narrow `NORMALIZED` instead.** At its best the cheaper edit,
preserving three charter loci, two standing errata and [13](../13-quality.md) §8.2's argument word for
word; redefining `NORMALIZED` as `fold_common(s, casefold=False, quotes=False)` separates the rungs
without touching INV-10. Rejected because it separates them in the wrong direction. `VERBATIM` is the
tier serve may call byte-exact and the only tier that is *proved*; leaving its proof casefolded means
a parser that lower-cased every heading still passes `Q-G6` at 1.000. Narrowing `NORMALIZED` narrows
the rung that is never checked — a `none`-addressed block has no source to check against — and leaves
the checked one loose. It optimises for not amending the charter, which is the wrong objective when
§9 exists for exactly this.

**Reuse `normalize_eval()` for the `bytes` branch.** Genuinely close: already `casefold=False`,
already in the plan, already property-tested against `normalize_k` for case-sensitivity (`Q-G23`), and
reusing it keeps the family at three. Rejected on two counts. It composes `strip_md`, and
`block.text` "never contains `<`-delimited markup" by construction ([03](../03-document-model.md) §17
P5), so it either does nothing or masks a driver that emitted markup into `text` — which is
[13](../13-quality.md) §8.2 rule 1's own argument inverted. And it folds the quote table, dashes, `Cf`
and whitespace: a source writing `U+2013` and a block writing `-` would prove byte-exactness. A proof
normaliser must fold **less** than a comparison normaliser, not differently. It also lives in
`omniweave_conform`, which a core invariant must not import.

**Collapse `Capabilities.origin_span` to a boolean.** [03](../03-document-model.md) §18 Q8 offers
this, and it is the honest response to a field whose middle value a driver author picks by coin flip.
Rejected on evidence: whichever way the boolean is cut it deletes a distinction something already
reads. Cut as `{no address, address}` and `byte_exact()`'s `achieved.origin_span == "exact"` has no
value to test, taking `Q-G6` with it. Cut as `{exact, not exact}` and `retain_parts = "when_citable"`
loses the difference between a driver with a non-verifying address and one with none — the operator's
storage doubles or does not, on a bit the collapse erased. The three-valued field is two independent
binary questions, "is there an address" and "does it prove", sharing one ordered field, and both are
read.

**Give the middle rung a sixth `Quote` tier.** Q8's other exit, and it would make the rung visible to
`Filters.min_quote`, the surface a caller actually reaches for. Rejected because the two ladders
measure different things: `Quote` is a **per-block** claim about text fidelity, `origin_span` a
**per-driver, per-document** statement about addressing. A sixth tier would give two blocks with
identical text and identical provenance different rungs because their drivers declared differently —
precisely what `byte_exact()` exists to forbid ("It reads `doc.achieved`, never a driver card",
[07](../07-store-and-retrieval.md) §8.2). The mechanical price is separate and large: `Quote` is an
ordered `IntEnum` with an append-only `enum_val.ord`, it is on the wire as `qt`, it is compared with
`>=` at `MAX_QUOTE_BY_OS_KIND`, `Filters.min_quote`, `clamp_quote()` and every segment's `quote_min`,
and charter D3's "every DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized`" would need re-stating
against a shifted ladder.

**Let `op.identify` insert `part` rows with a NULL `store_ref`.** [02](../02-architecture.md) §Open
questions item 6 states this fairly: it makes `unit.part_count` derivable
(`SELECT COUNT(*) FROM part`) rather than denormalised, and it matches D6's sentence as printed.
Rejected as unconstructible rather than undesirable, which is the stronger rejection: `sha256` and
`byte_len` are `NOT NULL` and `op.identify` reads no bytes, and `doc_ord` is a foreign key to a row
that does not exist yet. Making it work needs two nullable columns and a deferred foreign key on a
charter table, to denormalise a counter `unit.part_count` already holds and that the router requires
to be `NOT NULL` before it runs ([05](../05-ingest-and-routing.md):1323).

## Consequences

Each is an edit a later stage makes; none is made here.

| document | edit | price |
|---|---|---|
| [03](../03-document-model.md) §7.2, §8.3, §17 | the `bytes` predicate at three sites; §17 gains **P17** and restates `P7`'s `bytes` clause; §7.2's additive-CHECK block gains a fourth clause, `CHECK (os_kind <> <bytes ord> OR os_codec IS NOT NULL)`, because the predicate now reads `os_codec` and a NULL there makes the branch unevaluable | 1 ed |
| [03](../03-document-model.md) §2.10, §3.1, §18 | one sentence naming `DocSink.add_part` the sole inserter; §3.1's "Extends the charter" note cites `E52` instead of standing as an open divergence; Q2, Q3, Q5, Q8 move to answered | 0.5 ed |
| [07](../07-store-and-retrieval.md) §8.1 | the `bytes` row of the three-branch table | 0.25 ed |
| [13](../13-quality.md) §8.2, §6, §New terms | §8.2's opening — "INV-10's `bytes` branch is *defined* as `normalize_k(...)`" — is now false and must re-argue `normalize_eval` against `nfc`; §6 gains **P-23**; the `normalize_eval()` row drops "and is the definition of INV-10's `bytes` branch" | 0.75 ed |
| [02](../02-architecture.md) §2 row 5 | the Normalisers row says "two functions" and now names four (`normalize_key`, `normalize_k`, `nfc`, `fold_common` by reference) | 0.25 ed |
| [glossary.md](../glossary.md) :291, :741, :742 | the "Do not confuse" row becomes five-way; two rows drop the INV-10 attribution; an `nfc()` row is added | 0.25 ed |
| [_notes/terminology.md](../_notes/terminology.md) | one new row, `nfc()` — **claimed through ADR-1's bulk pass**, not written here | 0 (ADR-1) |
| [11](../11-repo-layout.md) §5.2 | none. `tools/wirekeys.toml` is already an append-only register and the append is legal under that discipline | 0 |
| charter §9.2 | six rows, `E48`-`E53`, three superseding `E1`, `E2`, `E13` | 0.5 ed |

Plus 1.5 ed for the fixture work of decision 1 and for `P17` and `P-23` themselves. **Total 5 ed.**

**Types that change shape.** Exactly one shipped type: `tools/wirekeys.toml` gains seven rows and
`model_version` reads `"1.1"`. Nothing in `Capabilities`, `Quote`, `OsKind` or `OriginSpan` changes
shape — that is the point of decisions 2 and 3, and it is what lets P2 freeze on schedule.

**Invariants.** INV-10 keeps both enforcers and both narrow: `owcheck`'s
verbatim-implies-retained-part clause is untouched, and the driver testkit's `origin_span` proof gains
a branch (`P17`) and a stricter comparison on the branch it had (`P7`). `Q-G6` does not move; its
predicate does.

**What becomes harder, priced.** Every existing `VERBATIM` fixture is re-run: one whose source and
text differ by case, by a folded dash, by a soft hyphen or by whitespace passed before and fails now.
Exposure is bounded — the office path declares `origin_span = "none"` and reaches `NORMALIZED` at best
([07](../07-store-and-retrieval.md) §8.1), so only the PDF `glyphs` path and flat-text `bytes` blocks
are in the denominator — but the re-baseline is real and sits inside the 1 ed above. Second: a driver
may no longer declare `origin_span = "normalized"` as a free hedge, so one card field in the testkit's
mandatory tier can now fail a driver that passed before.

**What a future reader must not do.** Do not re-introduce `normalize_k` into INV-10 on the strength of
charter `:81`, `:1168`, `:1453`, `:8017`, `E1`, `E2` or `E13` — all superseded by `E48`-`E53`. Do not
add a `Quote` tier for `origin_span`. Do not make `op.identify` write an L2 `part` row. Do not read
charter `:1597`'s twenty-two-key set as the wire.

## Open

**Whether any driver ever declares `origin_span = "normalized"`.** At release 1 none does: office is
`none`, PDF is `exact` through `glyphs`, and [03](../03-document-model.md) §7.5 records "**no
first-party driver occupies this row at release 1**" for the address-only shape, so `P17` runs against
the `nodepath` conformance fixture and out-of-tree drivers only. **Pre-committed fallback:** if at
v1.0 no driver has declared `normalized` and `retain_parts = "when_citable"` has never observed it,
the rung is withdrawn at the next `DriverCard` MAJOR and `when_citable` is re-expressed block-side as
"retain a `part` iff any body block has `os_kind <> 'none'`" — the same predicate one layer down,
needing no card field. Not before: `Capabilities.origin_span` is a card literal rather than an
`enum_val` ordinal, so withdrawal costs a card MAJOR and not a retired ordinal forever, the opposite
of `Kind.SECTION`'s position in [03](../03-document-model.md) §18 Q7.

**`P-23`'s number is claimed, not allocated.** [13](../13-quality.md) §6 runs to `P-22`, and
[17](../17-risks.md) §7.7's per-document block rule covers `F` numbers only. Six ADRs are being written
in parallel; if another claims `P-23`, this one renumbers. The absence of a block rule for the `P-`
series is a finding recorded here, not fixed here.
