# ADR-9 — `SCHEMA` has one code home, `omniweave_core.contract`, and one disk home, `index_state`

**Status:** Accepted · **Priority:** 6 of 12 · **Price:** 0.5 ed
**Discharges:** `11#OQ-9`
**Charter errata claimed:** `E72` (block `E72`-`E77`, five unused)
**Supersedes:** none
**Blocks / unblocks:** unblocks the P2 DDL freeze on the `meta`/`index_state` axis ([16](../16-roadmap.md) §3, P2 weeks 16-38); unblocks the `ow store verify` comparison and the `G27(b)` assertion that `11#OQ-9` names as its interim mitigation. Waits on ADR-1 for one lock row and one coined constant name.

## Context

The row this ADR discharges, quoted verbatim from [17-risks.md](../17-risks.md):674:

> `11#OQ-9` | `SCHEMA` has three homes and two of them are code: `contract` vs `limits` on the code
> side, `meta` vs `index_state` on disk. Charter section 8 item 19 makes "a second home for one
> config key" a rejection criterion, and this is that shape twice | defect | `model` | two
> sentences — one in [07](../07-store-and-retrieval.md) replacing `omniweave_core.limits` with
> `omniweave_core.contract`, one in [03](../03-document-model.md) either deleting the `meta` mention or
> declaring it a denormalised copy with `index_state` authoritative. **Until then a migration that
> writes one and not the other is a defect no gate catches**, so `ow store verify` compares them and
> `G27(b)`'s empty-file run asserts both are present after `0001_init.sql` | v0.1; ADR-9

The three homes, each opened:

| claim | locus | the words |
|---|---|---|
| code side is `contract`, disk side is `meta` | [03](../03-document-model.md) §15.1, :2607 | the version-field table's first row: "`SCHEMA` \| `omniweave_core.contract` and `meta` \| small int" |
| code side is `limits` | [07](../07-store-and-retrieval.md) §3.1, :275 | "`SCHEMA` in `omniweave_core.limits` holds the reader's" |
| disk side is `index_state` | [07](../07-store-and-retrieval.md) §3.1, :275 and §3.8, :662-663 | "`index_state.schema` holds `<major>.<minor>`" |
| both, reconciled in prose only | [11](../11-repo-layout.md) §4.1, :1016-1028 | "both cannot be right; OQ-9 records the conflict and what closes it" |

Charter §8 rejection criterion 19 ([charter.md](../_notes/charter.md):8677) rejects "a second home
for one config key, or a second name for one column". This is that shape twice, in the one document
family whose whole subject is that a fact has exactly one home.

**Four facts the register row did not have, each of which narrows the decision.**

1. **`meta`'s own DDL has never listed `schema`.** [03](../03-document-model.md) §13.1, :2215-2217,
   prints `CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);` and its key list in the comment
   below: `container_version · model_version · min_reader · digest_recipe · segment_recipe ·
   corpus_id · writer_version · graph.resolve_signature`. No `schema`. The second disk home exists in
   §15.1's prose table and nowhere in the DDL that creates the table.
2. **The `.owdoc` argument does not hold.** OQ-9 calls the denormalised copy "defensible for
   `.owdoc` export, where `index_state` does not travel". [03](../03-document-model.md) §13.2, :2393,
   prints `manifest.json`'s complete key set — `container_version, model_version, min_reader,
   digest_recipe, doc_key, source, status, producers[], parts[], assets[], views[], declared,
   achieved, confidence, timings_ms, counts, x` — and `SCHEMA` is not among them. The archive's
   compatibility is governed by the three version fields it does carry. There is nothing for a copy
   to serve.
3. **The lock already sides with `index_state`.** [terminology.md](../_notes/terminology.md):298
   defines `index_state` as "The store's own scalar state: corpus id, shard ordinal, **schema**,
   scorer version, generation, FTS state, …". No lock row gives `meta` a schema key, and the lock's
   own `SCHEMA` row at :445 names no home at all.
4. **`index_state` is not created by `0001_init.sql`.** [07](../07-store-and-retrieval.md) §3's
   migration table at :237-241 puts `meta` in `0001_init.sql` and the whole of §3 — including §3.8's
   `index_state` at :662-663 — in `0003_index.sql`. The register row's own mitigation, "`G27(b)`'s
   empty-file run asserts both are present after `0001_init.sql`", therefore names a point at which
   one of the two tables does not yet exist. As written it cannot run.

**Why this is a decision and not a repair.** Both readings are internally coherent and each is stated
by the document with the better claim to it: [03](../03-document-model.md) owns the version-field
table, [07](../07-store-and-retrieval.md) owns the comparison `Store.open()` performs against a file
it did not write. [11](../11-repo-layout.md) §4.1 picked one of each and said so, which is a third
document adjudicating two others rather than either of them changing. And the disk side is a genuine
fork: the register offers "delete the `meta` mention" **or** "declare it a denormalised copy", and
choosing between them decides whether an exported `.owdoc` ever carries a store-schema stamp.

## Decision

1. **`omniweave_core.contract` is the sole code home.** It holds four module constants:
   `CONTRACT: int`, `CONTRACTS_SUPPORTED: frozenset[int]`, `SCHEMA: int` (the major this build
   writes) and `SCHEMA_MINOR: int` (the minor this build writes). `omniweave_core.limits` holds no
   version constant, now or ever: it holds ceilings and the one `MIN_SQLITE` floor, which is what
   [02](../02-architecture.md) §2 row 7, :231, defines it as.
2. **`SCHEMA_MINOR` exists because the compatibility table reads it.**
   [07](../07-store-and-retrieval.md) §3.1's four-row table compares "file minor" against "reader
   minor" in two of its four rows, and the reader's minor has no home in any document today. Naming a
   code home and leaving half of what it must hold homeless would discharge the row and reproduce its
   defect one field over. `SCHEMA_MINOR` resets to `0` at a major bump, and the pair is formatted as
   `f"{SCHEMA}.{SCHEMA_MINOR}"` at exactly one site, in `contract`.
3. **`index_state` is the sole disk home**, key `schema`, value `<major>.<minor>` as a string, which
   is what [07](../07-store-and-retrieval.md) §3.8, :662-663, already prints. **`meta` never gains a
   `schema` key.** [03](../03-document-model.md) §15.1's cell is corrected to name
   `omniweave_core.contract` and `index_state`, and its `type` cell reads two small ints rather than
   one.
4. **`ow store verify` gains one check in its default, unflagged set: single-homedness.** It asserts
   that `meta` holds no `schema` key and that no `[SOR]` table other than `index_state` carries one.
   This is deliberately an **absence** check rather than a comparison: with one home there is nothing
   to compare, and the defect the register row fears — "a migration that writes one and not the
   other" — can only recur as a second home reappearing. The failure takes the next free numeral in
   [07](../07-store-and-retrieval.md)'s `OW-S-0xx` block; the numeral is 07's to allocate in
   `tools/codes.toml`, the check is this ADR's.
5. **`G27(b)`'s assertion moves to the end of the run.** After `0001` → `0005` apply in numeric order
   to an empty file on `MIN_SQLITE`, `index_state` holds exactly one `schema` row whose value equals
   `f"{SCHEMA}.{SCHEMA_MINOR}"` read from `omniweave_core.contract`, and `meta` holds no `schema` key.
   Not "after `0001_init.sql`", which is two migrations before `index_state` exists.
6. **Charter erratum `E72`**, claimed from ADR-9's block (`E72`-`E77`, [README](README.md) §6), in the
   five-part shape [11](../11-repo-layout.md) §8.4 requires:

   | # | part |
   |---|---|
   | 1 | locus: [charter.md](../_notes/charter.md) §2, the three version axes, :233-235 |
   | 2 | old text: "**`SCHEMA`** — the small integer versioning the L2 model **and** the store schema together." |
   | 3 | new text: that small integer is the **major** of a `<major>.<minor>` pair. The pair's code home is `omniweave_core.contract` (`SCHEMA`, `SCHEMA_MINOR`); its disk home is `index_state.schema`, written `<major>.<minor>`. One home each, and [11](../11-repo-layout.md) §4.1 is the amended text's sole home |
   | 4 | erratum row: `E72` |
   | 5 | ruling to re-issue: **none**. [D5-store.md](../_notes/rulings/D5-store.md) settled the comparison, not the constant's module |

## Alternatives rejected

### `omniweave_core.limits` for the code side

At its best this is the stronger claim, not the weaker one. `limits` is where every host-side constant
a reader consults before opening anything already lives — `MIN_SQLITE = (3, 42, 0)`, every `MAX_*`
ceiling — and a reader's own schema version is exactly that shape: a fact about this build that bounds
what it may open. And [07](../07-store-and-retrieval.md) §3.1 is the document that *specifies* the
comparison, so it has the best claim to name the constant the comparison reads.

Rejected on tier. [02](../02-architecture.md) §2 row 7, :231, defines `limits` as "every `MAX_*`
ceiling, the one `MIN_SQLITE = (3,42,0)` floor" and tiers it `T-PUBLIC`; row 2, :226, defines
`contract` as the **stamp** module, `T-CONTRACT`, holding a version int plus the set of versions this
build accepts — which is the shape `SCHEMA` needs, member for member. `SCHEMA` is a stamp carrying a
two-release deprecation window ([charter.md](../_notes/charter.md):8442), not a ceiling. Putting a
`T-CONTRACT`-behaviour constant in a `T-PUBLIC` module makes the stability tier a property of the
module rather than of the promise, which is the one thing [02](../02-architecture.md) §2's tier column
exists to prevent. Two documents already say `contract` against one that says `limits`, and the tier
argument is what would decide it if the count were even.

### `meta` as the disk home, or as a declared denormalised copy

At its best: `meta` is created by `0001_init.sql`, the very first migration, so a file that failed
part-way through the sequence would still carry its own version — and a version stamp that survives a
partial migration is worth something, because a file with tables and no version is a file
`Store.open()` cannot classify at all. `meta` is `[SOR]` ([03](../03-document-model.md) §13.1,
:2381-2384), so a reader may already depend on it. OQ-9 itself calls the copy defensible.

Rejected on three counts. The `.owdoc` justification does not survive contact with
[03](../03-document-model.md) §13.2's `manifest.json` key list, which carries no `SCHEMA` and needs
none (fact 2). The second home is not in the DDL at all (fact 1), so deleting it costs one table cell
and no migration. And a *declared* copy is worse than an undeclared one: it legalises the shape
charter §8 item 19 rejects and buys a comparison gate on every write, forever — exactly the cost the
register row was pricing when it asked `ow store verify` to compare them. The partial-migration
argument is answered where it belongs: DDL applies transactionally, and a file that never reached
`0003_index.sql` has no `migration` table either, so "no version" is already the recorded state of an
incomplete create.

### `SCHEMAS_SUPPORTED: frozenset[int]`, by symmetry with `CONTRACTS_SUPPORTED`

At its best the symmetry is real, it gives one place to read what this build can open, and it would
let a build **declare** support for two majors across the two-release deprecation window rather than
leaving it implied.

Rejected because [07](../07-store-and-retrieval.md) §3.1's table is already a total function of
(file major, file minor, reader major, reader minor): it has a row for every case, including
migrate-forward, serve-reads-refuse-writes and refuse-ahead. A supported-set would restate what the
table computes and would be the first of the two to drift. Adding a second statement of one fact
inside the ADR whose subject is second homes is not symmetry; it is the defect.

### Leave [11](../11-repo-layout.md) §4.1's reconciliation standing and change nothing

At its best: §4.1 already picks `contract` for code and `index_state` for disk, in the document that
owns the change-classification table for all three version axes, and it notes that nothing there
depends on which module wins because every mechanism reads the file's value.

Rejected because the reconciliation lives in a third document while the two contradicting sentences
are still printed unchanged in [03](../03-document-model.md) §15.1 and
[07](../07-store-and-retrieval.md) §3.1, so a reader of either still gets the wrong answer — and
`G27(d)`'s `d2` clause resolves identifiers against registers rather than prose, so nothing mechanical
disagrees with `meta` today. **This is the closest of the four**: had §4.1's paragraph been written
*into* 03 and 07 rather than *about* them, there would be no register row and no ADR.

## Consequences

| edit | locus | price |
|---|---|---|
| `limits` → `contract`; the reader's minor named | [07](../07-store-and-retrieval.md) §3.1, :275 | 0.1 ed |
| the `where` cell becomes `omniweave_core.contract` and `index_state`; `type` becomes two small ints | [03](../03-document-model.md) §15.1, :2607 | 0.1 ed |
| `contract`'s contents go from "two module constants" to four | [02](../02-architecture.md) §2 row 2, :226 | 0.05 ed |
| the constants block gains `SCHEMA_MINOR: int`; "three axes" stays true — one axis, two components | [18](../18-api-sketch.md) §1.1, :237-241 | 0.05 ed |
| `ow --version` prints `SCHEMA` as `<major>.<minor>` | [11](../11-repo-layout.md) §2, :699; §7.6 checklist item 16, :2020 | 0.05 ed |
| §4.1's "both cannot be right" paragraph becomes the settled statement; OQ-9 is struck for a pointer here | [11](../11-repo-layout.md) :1023-1028 and :2539-2553 | 0.1 ed |
| the single-homedness check, plus one `OW-S-0xx` row in `tools/codes.toml` | [07](../07-store-and-retrieval.md) §14 | 0.05 ed |
| one store-property row, `ST23` at the time of writing | [07](../07-store-and-retrieval.md) §15, after `ST22` at :3142 | 0.05 ed |
| the lock's `SCHEMA` row gains its two homes; `SCHEMA_MINOR` is coined | [terminology.md](../_notes/terminology.md):445, [glossary.md](../glossary.md):941 | carried by ADR-1 |

0.55 ed of document edits, held at the **0.5 ed** [17](../17-risks.md) §7.6 prices. The
`ow store verify` check and the `G27(b)` assertion are P2 work inside the store's own test surface,
not additional ADR cost.

- **`ST23` may collide.** ADR-6 also edits [07](../07-store-and-retrieval.md) §15; `ST22` is taken
  ([07](../07-store-and-retrieval.md):3142), so whichever of the two lands second takes `ST24`. This
  is [17](../17-risks.md) §7.7's own lesson about to recur inside the ADR set written to apply it.
- **ADR-1 must land first for two rows.** `SCHEMA_MINOR` is a coined name and the lock's `SCHEMA` row
  is an edit; both belong to the bulk pass ([README](README.md) §7.1, "ADR-1 before every ADR that
  coins a name"). Nothing else here waits on it.
- **What becomes harder.** A future `.owdoc` that wants a store-schema stamp must add the key to
  `manifest.json` and argue why the three version fields already there are insufficient. This ADR
  closes the denormalised-copy exit by name, so re-proposing it is an amendment against `E72` rather
  than an edit.
- **What a future reader must not do.** Add a version constant to `omniweave_core.limits`, add a
  `schema` key to `meta`, or add a `SCHEMAS_SUPPORTED`. Each is charter §8 item 19's shape, and each
  is now rejected on the record rather than merely unbuilt.

## Open

**`corpus_id` is the same defect one table over, and it has no register row.**
[03](../03-document-model.md) §13.1, :2216-2217, lists `corpus_id` among `meta`'s keys;
[07](../07-store-and-retrieval.md) §3.8, :662-663, lists `corpus_id` among `index_state`'s. Two homes
for one identity — and [07](../07-store-and-retrieval.md):2842 and :2979 both read the `index_state`
copy. **What closes it:** one read of who writes `meta.corpus_id`, and if the answer is "nobody", the same
one-cell deletion this ADR applies to `schema`. Not decided here: it is outside `11#OQ-9`'s stated
subject. Decision 4's check is written narrowly against `schema` and is where it generalises.
