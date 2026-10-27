# ADR-6 — `block_cite` is gen-free, `vectors = "off"` is `OFF`, `rank_of` stays, and `want` closes at five

**Status:** Accepted · **Priority:** 5 of 12 · **Price:** 3 ed
**Deadline:** before the P2 schema freeze ([16](../16-roadmap.md) §3, P2 weeks 16-38) — `block_cite` is `0001_init.sql` DDL
**Discharges:** `02#2`, `02#3`, `07#D3`, `18#1`
**Charter errata claimed:** `E54`, `E55`, `E56` (block `E54`-`E59`, three unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks P2's `block` DDL, which cannot be written while two column lists are
printed as binding; unblocks `fuse()`/`ceiling()`, whose ceiling predicate today branches on a
free-form `str`; and settles what `ow surface emit --check` byte-diffs the first time it runs.
Re-issues [D2-docmodel.md](../_notes/rulings/D2-docmodel.md) and
[D5-store.md](../_notes/rulings/D5-store.md). Hands four lock rows to
[ADR-1](0001-terminology-lock-bulk-pass.md), one of which cannot land until ADR-1 fixes check 3's
negation blindness (`12#D1`).

## Context

The four register rows, quoted verbatim from [17-risks.md](../17-risks.md) §§7.3-7.4:

> `02#2` | `block_cite` is specified twice with different columns | defect | `model` |
> [07](../07-store-and-retrieval.md)'s DDL plus a one-line correction to charter section 6.1; the
> no-`gen` form is authoritative | v0.1 — [17](../17-risks.md):579

> `02#3` | `vectors = "off"` yields `OFF`, and one charter line says `EMPTY` | defect | `retrieval` |
> [07](../07-store-and-retrieval.md) stating the ceiling's status set beside `_weight()`, and
> restating ST6 half (a) over a routinely-empty `exact` Channel | v0.1 — [17](../17-risks.md):580

> `07#D3` | the semantic lift's equal ranks are unrepresentable in `ChannelResult` | defect |
> `retrieval` | already extended in [07](../07-store-and-retrieval.md)'s main text, because the
> Channel is otherwise unimplementable; needs the lock row | v0.1; ADR-6 — [17](../17-risks.md):635

> `18#1` | `--want cross_refs` does not exist and one core document uses it | defect | `retrieval` |
> the `ow surface emit` byte-diff gate, which rejects one of the two the first time it runs.
> **Recommendation: keep the five-member enum** … | v0.1; ADR-6 — [17](../17-risks.md):726

**The rows are not thin, and two of them have moved since they were written.** Each was checked
against the live text rather than taken at face value.

**`02#2` has three carriers, not two, and the root is a ruling.**
[D2-docmodel.md](../_notes/rulings/D2-docmodel.md):265 prints
`CREATE UNIQUE INDEX block_cite ON block(doc_ord, gen, cite);` on the line directly below
`block_addr`'s correctly gen-keyed index; `charter.md`:8343 carries that spelling into §6.1's
prompt-safe-token table. But `charter.md`:1081 — the `0001_init.sql` DDL in the same charter —
prints the gen-**free** form with a four-line justification, so the charter contradicts itself.
Seven documents plus the lock write gen-free: [00](../00-vision.md):360,
[01](../01-principles.md):1057 (`AP-7`'s mitigation), [03](../03-document-model.md):2274,
[06](../06-structure-extraction.md):2304, [07](../07-store-and-retrieval.md):899,
[09](../09-generation.md):1976, [14](../14-security.md):659,
[terminology.md](../_notes/terminology.md):175.

**`02#3` is half-closed, and the unclosed half is inside `07` itself.**
[07](../07-store-and-retrieval.md) §5.3 already prints the ceiling predicate beside `_weight()`
(`:1309`-`:1312`), with an `OFF(query_deadline)` carve-out the charter does not have. But
`:1353` still reads "Half (a) alone is **false on the shipped default** — `vectors = "off"` makes
`semantic` `EMPTY`" — the charter's retired reading (`charter.md`:3519, and again in the ST6 row at
`:3785`) transcribed verbatim into the document meant to supersede it.
[02](../02-architecture.md) §Open questions item 3 predicted exactly this: "fixing the comment
without re-reading the test would break the test's stated rationale on the shipped default."

**And a fifth spelling of the same fact is loose.** `ceiling()` branches on
`c.reason == "query_deadline"` — a string equality against a field typed `str = ""`. Five `OFF`
reasons are in print: `vectors`, `not_in_plan`, `query_deadline`
([07](../07-store-and-retrieval.md) §5.3), `not_built` ([16](../16-roadmap.md):113), and
`no-embeddings` (`charter.md`:6601, [10](../10-interfaces.md):640,
[18](../18-api-sketch.md):1072 and `:1420`), the last originating at
[D9-serve.md](../_notes/rulings/D9-serve.md):317 where the Channel is still called `similarity`. A
free-form string that decides an arithmetic branch is a silent confidence switch.

**`18#1`'s carrier has already moved.** [07](../07-store-and-retrieval.md) §6.6 plan (3) now reads
`ow query 'sec:/0003/0007' --want related` (`:1787`) and names the five-member enum in its body.
`cross_refs` survives in exactly two places, both in `18` and both *describing* a disagreement that
no longer exists: §7.3's spelling note (`:2838`-`:2844`) and §Open questions item 4
(`:3279`-`:3288`). The row's "one core document uses it" is stale.

**Why this is a decision and not a repair.** Three of the four are pairs of printed statements where
one must become binding and the other retired law with a named authority — `02#2` between a ruling,
a charter table and a charter DDL; `02#3` between two readings that produce different confidence
numbers on the shipped default; `18#1` between a five-member enum and a sixth. The fourth, `07#D3`,
is a ratification: `rank_of` already sits in the main text under
[07](../07-store-and-retrieval.md) §Extends the charter row 1, and what is undecided is whether it
survives review and reaches the lock.

## Decision

### 1. `block_cite` is `UNIQUE(doc_ord, cite)`, gen-free, in `0001_init.sql`

Authoritative print: [07](../07-store-and-retrieval.md):899 (the index roster) and
[03](../03-document-model.md):2274 (the DDL). Nothing about them changes; that is the point.
`charter.md`:8343's `block_cite(doc_ord, gen, cite)` is superseded by `E54`, and
[D2-docmodel.md](../_notes/rulings/D2-docmodel.md):265 is re-issued.

`cite`'s grammar is `[<corpus>:]d<doc_ord>#<n>` ([terminology.md](../_notes/terminology.md):175) and
carries no generation, so a gen-keyed index is **not resolvable from the token at all**. Retirement
is already handled by `block_history.superseded_by` with `OW-M-030 / OW_CITE_RETIRED`
([07](../07-store-and-retrieval.md) §6.6), so the with-`gen` form buys nothing and costs the one
property `AP-7` ([01](../01-principles.md):1057) exists to protect.

### 2. `[retrieval] vectors = "off"` yields `ChannelStatus.OFF`, and the ceiling predicate is as `07` prints it

```text
contributes(c)  ⇔  c.status ∈ {OK, EMPTY}  or  (c.status is OFF and c.reason == OffReason.QUERY_DEADLINE)
```

`charter.md`:3519's "`vectors = "off"` makes `semantic` EMPTY" and `charter.md`:3785's ST6 row are
superseded by `E55`. `EMPTY` and `OFF` are not interchangeable here: under the `EMPTY` reading the
shipped default's ceiling is `5.4/61` while at most `4.6/61` of score is attainable, so **no
default-configured query can ever report `confidence` above 0.852** and every calibration figure in
[13](../13-quality.md) is scaled by a constant nobody declared.

**ST6 half (a) is restated over `exact`, not over `semantic`.** The sentence at
[07](../07-store-and-retrieval.md):1353 becomes: *half (a)'s all-`OK` antecedent is rarely satisfied
on a real corpus because an empty `exact` Channel is routine; `vectors = "off"` makes `semantic`
`OFF(vectors)`, which is ceiling-exempt and therefore does not bear on half (a) at all.* Halves (b)
and (c) are unchanged.

### 3. `ChannelResult.reason` is a closed literal when `status is OFF`

```python
class OffReason(StrEnum):
    VECTORS="vectors"; NOT_IN_PLAN="not_in_plan"; NOT_BUILT="not_built"; QUERY_DEADLINE="query_deadline"
```

Exactly one member — `QUERY_DEADLINE` — is ceiling-bearing, for the reason
[07](../07-store-and-retrieval.md) §5.3 already gives: it is a runtime shortfall, and exempting it
would shrink the denominator so a worse answer reports higher confidence. `no-embeddings` becomes a
§3 rejected synonym of `vectors`; the worked trailers render `semantic:off(vectors)`. Sole home:
[07](../07-store-and-retrieval.md) §5.1, beside `ChannelStatus`. `reason` stays a free `str` for
`EMPTY` and `UNAVAILABLE` — see **Open**.

### 4. `ChannelResult.rank_of` is ratified as printed, and gets its lock row

`rank_of: Mapping[int, int] = MappingProxyType({})`, 1-based, empty for every Channel but `semantic`,
read through `_rank()` ([07](../07-store-and-retrieval.md):1301-1302). It stands exactly as
[07](../07-store-and-retrieval.md) §Extends the charter row 1 states it. The lock row text — the
wording already in [glossary.md](../glossary.md):867 — goes to
[ADR-1](0001-terminology-lock-bulk-pass.md): [terminology.md](../_notes/terminology.md) has no
`rank_of` row and its `ChannelResult` row (`:173`) does not list the field.
[D5-store.md](../_notes/rulings/D5-store.md):484-490 is re-issued — its `ChannelResult` has no
`rank_of` and uses `= ...` defaults, which the lock's own §3 row rejects. No charter erratum: the
charter's shape is *completed*, not contradicted, and §Extends the charter is the sanctioned
instrument for that.

### 5. `want` closes at five members. `cross_refs` is not one of them

`passages | table | fields | outline | related`, as [10](../10-interfaces.md) §3.2, §11's
`llms.txt`, [18](../18-api-sketch.md):263 and `:1268` already print; an unknown value is a
validation error naming the five ([10](../10-interfaces.md):395).

Because [07](../07-store-and-retrieval.md) §6.6 is already repaired, the remaining work is deletion,
not correction: [18](../18-api-sketch.md) §7.3's spelling note has no disagreement left to note, and
§Open questions item 4 closes against [07](../07-store-and-retrieval.md):1787. `cross_refs` →
`related` becomes a §3 rejected synonym so `G27(c)` catches a recurrence — **and that row may not
land before [ADR-1](0001-terminology-lock-bulk-pass.md)**, because `18` §7.3 and item 4 both *name*
the token and check 3 as written cannot tell naming a banned token from using it (`12#D1`). A
concrete instance of ADR-1's second blocker, not a hypothetical one.

### The three errata, in the five-part shape [`README.md`](README.md) §4 requires

| row | 1 locus | 2 phrase | 3 new text / sole home | 4 | 5 ruling re-issued |
|---|---|---|---|---|---|
| `E54` | §6.1, `:8343` | `block_cite(doc_ord, gen, cite)` | `block_cite(doc_ord, cite)`. Sole home [07](../07-store-and-retrieval.md) §7.1 (`:899`); DDL [03](../03-document-model.md):2274. `charter.md`:1081 already agrees | `E54` | **D2** (`:265`) |
| `E55` | §D5, `:3519` and the ST6 row at `:3785` | makes \`semantic\` EMPTY | `vectors = "off"` yields `OFF(vectors)`, ceiling-exempt; ST6 is three halves with (a) restated over `exact`. Sole home [07](../07-store-and-retrieval.md) §5.3 | `E55` | **D5** (`:502`-`:505`, for the two-half test and the missing carve-out) |
| `E56` | §6.5's worked trailer, `:6601` | `semantic:off(no-embeddings)` | `semantic:off(vectors)`; `OffReason` is closed at four members, sole home [07](../07-store-and-retrieval.md) §5.1 | `E56` | **D9** (`:317`, which also still writes `similarity`) |

## Alternatives rejected

### Keep `gen` in `block_cite` and mint a fresh cite per generation

The best form: a gen-keyed index makes `d7#412` at gen 41 and at gen 42 distinguishable rows, so
re-parse never has to retire anything, `block_history` shrinks, and `block_cite` becomes
structurally identical to `block_addr` one line above it — one index shape for two natural keys.

Rejected because the token cannot express the key: a resolver holding `d7#412` and nothing else
would have to guess a `gen` or scan. And the property it destroys is the one `AP-7` names, "a
shipped citation silently re-points at a different row". `charter.md`:1082-1084 already argues this
in the charter's own voice; §6.1's cell is a transcription of the adjacent `block_addr` row, and the
adjacency is the whole explanation.

### `vectors = "off"` yields `EMPTY`

Genuinely close on honesty grounds, and worth stating at full strength: `EMPTY` carries weight into
the ceiling, which is a *penalty* on confidence, and a framework that would rather understate its
own confidence than overstate it should prefer the penalty. `charter.md`:3521 makes precisely that
argument for `EMPTY` — "it discloses 'we looked there and found nothing'".

Rejected on arithmetic the charter itself prints fourteen lines earlier. `charter.md`:3505 gives
"four (no semantic) = 4.6/61", true only if `OFF` is ceiling-exempt. Under `EMPTY` the shipped
default's confidence caps at `4.6/5.4 = 0.852`, so `low_confidence < 0.35` and every `Q-G`
calibration threshold in [13](../13-quality.md) are measured against a scale that silently depends
on a config key. And the disclosure argument does not survive the semantics: `EMPTY` means the
Channel *looked* and found nothing. A store with no vectors did not look — which is exactly `R-A6`'s
mitigation ([17](../17-risks.md):267): "`off` is an operator choice, it is printed, and it
contributes nothing to the ceiling — so a four-Channel answer honestly reports `4.6 / 61` rather
than pretending to five".

### Add `cross_refs` as a sixth `want` member

The best case: the original heading described an intent `related` under-describes — "everything
under §3.7 that cross-references anything" — and the budget objection is empty. The compact surface
measures 850 tokens against a 1,900 ceiling with 1,050 of headroom
([10](../10-interfaces.md):304, `:308`), and `want` is `advanced` and therefore absent from the
compact schema anyway ([10](../10-interfaces.md):395), so a sixth member costs approximately zero.

Rejected because it is a second name for a composition of two knobs that already exist.
[07](../07-store-and-retrieval.md) §6.6's own Python sets no `want` at all: it is `mode="explore"`
plus `Expand(relations={refers_to, cites, part_of}, max_hops=2)`, and `related` is already defined
as "`Expand` promoted from the neighbourhood to the primary result"
([10](../10-interfaces.md) §3.2) — the same operation. A preset that is a spelling of two parameters
is what §8 rejection criterion 19 calls "a second name for one column". The cost is not tokens; it
is a second `want` branch in the packer and a second thing a caller has to choose between.

### Leave `ChannelResult.reason` an open `str`

The case: reasons are diagnostic prose for humans, closing them costs a type, a lock row and a
migration path for every future Channel author, and `ChannelResult` is a frozen shipped shape.

Rejected because one of those strings is not prose. `ceiling()` reads
`c.reason == "query_deadline"` and returns a different denominator depending on the answer, so a
misspelling changes a published confidence number with no error anywhere. Five spellings already
exist across five documents and one ruling, and the fifth — `no-embeddings` — is not even in the
lock's `snake_case` convention. Closing only the `OFF` branch is the minimal change that removes
the arithmetic hazard, and it is additive: `reason` keeps its type for the other three statuses.

### Represent equal ranks by repeating blocks in `ranked`, or by making `ranked` a tuple of tuples

The case: no new field, no charter extension, and the rank stays where a reader expects it — in the
order of the sequence.

Rejected because `ranked` is declared "totally ordered, duplicate-free" in three places including
the lock's own `ChannelResult` row (`:173`), so repetition contradicts a locked property, and a
tuple-of-tuples is a **shape change** to a field the charter prints, versus `rank_of`, which is
additive with a real default and populated by one Channel. [07](../07-store-and-retrieval.md) §5.1
names the concrete failure the alternative reintroduces: jcodemunch's `enumerate` loop spreads 64
co-ranked blocks across 64 ranks and destroys the region-level signal.

## Consequences

| obligation | locus | price |
|---|---|--:|
| `charter.md` §9.2 gains `E54`, `E55`, `E56`, each at its line-number locus per §9.1 | §9.2 table | 0.5 ed |
| [D2-docmodel.md](../_notes/rulings/D2-docmodel.md):265 re-issued gen-free; [D5-store.md](../_notes/rulings/D5-store.md):484-505 re-issued with `rank_of`, real defaults and the three-half ST6; [D9-serve.md](../_notes/rulings/D9-serve.md):317 re-issued as `semantic:off(vectors)` | `_notes/rulings/` | 0.8 ed |
| [07](../07-store-and-retrieval.md):1353's justification sentence restated over `exact` — the last live carrier of the retired `EMPTY` reading in a plan document | [07](../07-store-and-retrieval.md) §5.3 | 0.3 ed |
| `OffReason` printed in [07](../07-store-and-retrieval.md) §5.1; `ceiling()`'s predicate reads the member, not a literal | [07](../07-store-and-retrieval.md) §5.1, §5.3 | 0.4 ed |
| `off(no-embeddings)` → `off(vectors)` in three trailers, one of which is inside a JSON fence `G27(a)` parses | [10](../10-interfaces.md):640; [18](../18-api-sketch.md):1072, `:1420` | 0.2 ed |
| [18](../18-api-sketch.md) §7.3's spelling note **deleted**; §Open questions item 4 closed against [07](../07-store-and-retrieval.md):1787 | [18](../18-api-sketch.md):2838-2844, `:3279`-`:3288` | 0.3 ed |
| ST6's three halves restated once against this result, and `ST6`'s row re-read | [07](../07-store-and-retrieval.md):3121; [01](../01-principles.md):646 | 0.3 ed |
| Four lock rows drafted and handed to [ADR-1](0001-terminology-lock-bulk-pass.md): `rank_of`; `OffReason`; §3 `no-embeddings` → `vectors`; §3 `cross_refs` → `related` | [terminology.md](../_notes/terminology.md) §2, §3 | 0.2 ed |
| [`README.md`](README.md) §7's ADR-6 row moves `proposed` → `accepted`; `charter_defects_open` decrements by 4 | [`README.md`](README.md) §5, §7 | — |
| **total** | | **3.0 ed** |

**What does not change, and is the point.** [07](../07-store-and-retrieval.md):899,
[03](../03-document-model.md):2274, [07](../07-store-and-retrieval.md):1309-1312 and
[07](../07-store-and-retrieval.md) §5.1's `rank_of` are all already correct. `fuse()`, `ceiling()`,
`DEFAULT_WEIGHTS`, `RRF_K`, `SCORER_VERSION` and the three ceiling values (`0.08852`, `0.07541`,
`0.04918`) are untouched. No `Verdict` field changes shape, so `E17` and `E22`'s Tier 0 freeze at
twenty-two fields holds.

**What becomes harder.** A Channel builder can no longer invent an `OFF` reason; a new one is a lock
change plus an `OffReason` member plus a ruling on whether it is ceiling-bearing. `Verdict.channels`
is `Mapping[str, ChannelStatus]` and carries no reason ([07](../07-store-and-retrieval.md):1927), so
the ceiling-bearing distinction is visible in the rendered trailer and in `retrieval_event` but not
in the `Verdict` type — deliberately, because widening that value type after the Tier 0 freeze is a
migration, not an edit.

**What a future reader must not do.** Re-add `gen` to `block_cite`; "simplify" `ceiling()` to drop
the `OFF(query_deadline)` carve-out, which `charter.md`:3523 and
[15](../15-observability.md):877 both already forbid; read
[18](../18-api-sketch.md) §Open questions item 4 as live; or land the `cross_refs` §3 row before
[ADR-1](0001-terminology-lock-bulk-pass.md).

## Open

**Whether `UNAVAILABLE`'s `reason` should also close.** Absence gate 1 (`g01_timed_out`,
[07](../07-store-and-retrieval.md):2092) fires on "any Channel is `UNAVAILABLE` with
`reason == "timeout"`", the same free-string hazard decision 3 removes from the `OFF` branch — and
`UNAVAILABLE(vec_unreadable)` ([07](../07-store-and-retrieval.md):1291) is a second spelling in the
same document. It is deliberately not decided here: the fifteen absence gates are Tier 0's normative
table, and their 15-to-13 mapping against `ABSENCE_BLOCKING_DIAGS`' Injectors has no owner at all
([final-review.md](../_notes/final-review.md) §7 item 6), so a reason vocabulary decided here would
be re-decided there. **Closing evidence:** whoever takes the 15-to-13 mapping publishing the gate-1
trigger set. **Interim, decided:** gate 1 compares against a module constant
`TIMEOUT_REASON = "timeout"` in `omniweave_core.retrieve`, so there is one spelling even without a
type. **Pre-committed fallback:** if the mapping's owner closes the vocabulary, `TIMEOUT_REASON` is
deleted in the same commit rather than kept beside it.
