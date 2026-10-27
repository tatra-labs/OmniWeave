# omniweave — glossary and name index

## In one paragraph

Every name the framework uses, alphabetized, with the document and section that specifies it. Seven
hundred and forty-five rows, **one per row of the binding [terminology lock](_notes/terminology.md)
§2 and no more**: 407 from the lock's revision before ADR-1, 313 coined by the nineteen plan
documents and recorded in their "New terms" sections, 24 authored in the lock because no document
offered them, and **`nfc()`** — defined by [ADR-5](adr/0005-byte-exactness-chain.md) decision 1,
claimed by that ADR's consequence table "through ADR-1's bulk pass", missed by the pass, and indexed
here first because INV-10's `bytes` branch now reads `nfc(decode(...))` and the name had to be
findable. Its lock row has since landed, so the count here is 745 against the lock's 745 and the
byte-diff gate below is square. **§2 is the sole home of a definition** (ADR-1 decision 2):
this index's `Definition` and `Kind` columns are generated from it by `tools/gen_glossary.py` and
byte-diff gated, and the `Specified in` column, ["Do not confuse"](#do-not-confuse) and
["Collisions resolved"](#collisions-resolved) are this document's own facts. The
`Specified in` column is the point of this document — it converts a flat list of names into a
navigable index, so a reviewer who meets `wal_baseline_bytes` in a diff can reach the four
paragraphs that define it in one hop. Where a name is easy to confuse with a neighbour — the four
identifier kinds, the two digest families, the six trust-and-confidence enums, the nine generation
counters, the six `Verdict`-shaped types — "Do not confuse" separates them by job. Where two
documents used one spelling for two concepts, the "Collisions" section names the winner.

## How to read the `Specified in` column

The column names the document and the `##`/`###` section that **specifies** the term — not the
first place it is mentioned. It was built mechanically: for each name, every occurrence in the
nineteen documents was located, the owning document chosen as the one carrying the strongest
definitional occurrence (a heading naming the term, a `class`/`CREATE TABLE`/`def` line, a table row
whose first cell is the term, a bolded definition), and the section taken as the enclosing heading.
One hundred and sixty-six rows were then corrected by hand where the mechanical winner was a
false positive — `| Counter | Scope | Meaning |` is a table header in
[07](07-store-and-retrieval.md), not a definition of `Counter`, which belongs to
[13](13-quality.md) §2.8.

Three values in that column mean something specific:

| value | meaning |
|---|---|
| ``NN` §N.N` | a link to the document plus the section that specifies the term |
| the same with `§<heading text>` | where the document's headings are unnumbered ([01](01-principles.md) only) |
| **none** | no plan document specifies it. Three rows: `ow_segment_head`, `eval_calibration` and `edge_bound`, the last of which ADR-1 decision 3 added from the charter's L3 DDL. All three are findings against the lock's CI rule 2, not omissions from this glossary — see [Open questions](#open-questions) |

A term whose only occurrence is its own "New terms" row has no separate specifying section; those
rows were all resolved by hand to the section that carries the mechanism, so no row in the index
points at a "New terms" table.

## Naming conventions

These are the lock's §1 conventions, restated in the form a reviewer applies them, plus the
conventions the nineteen documents established that the lock does not yet carry. Nothing here is
invented: every row is a rule the lock states or a pattern every document already follows.

### Casing, by kind of name

| where | convention | example |
|---|---|---|
| distribution | `kebab-case`, always `omniweave-` prefixed | `omniweave-target-pptx` |
| import package | `snake_case`, one per distribution, no namespace packages | `omniweave_target_pptx` |
| module | `snake_case`, singular unless it registers many things | `verdict.py`, `codes.toml` |
| type, `Protocol`, enum class | `PascalCase` | `DriverCard`, `ChannelStatus` |
| enum member | `SCREAMING_SNAKE`; the wire value is the **lower-case member name**, for an `IntEnum` as much as a `StrEnum`, with no exception | `Trust.EXTRACTED` → `"extracted"`; `Rung.DECODE` → `"decode"` |
| function, method, variable | `snake_case` | `build_verdict()`, `content_digest` |
| constant, limit | `SCREAMING_SNAKE`; a ceiling is `MAX_*`, a floor is `MIN_*`, a producer's own aim is `*_TARGET_*` | `MAX_GRID_SLOTS`, `MIN_SQLITE`, `SEGMENT_TARGET_TOKENS` |
| SQL table | `snake_case`, **singular** | `block`, `segment`, `route_decision` |
| SQL view | `snake_case`, prefixed `ow_` for a head/live projection, unprefixed otherwise | `ow_block_head`, `ref_unresolved` |
| SQL index | `<table>_<purpose>` | `block_cite`, `edge_bound`, `cache_gc` |
| config key | `snake_case` under a `[section]`; a duration ends `_ms`/`_s`, a size ends `_bytes`/`_mb`, a count is a bare plural | `lease_ms`, `min_free_bytes`, `max_workers` |
| env var | `OMNIWEAVE_` + `SCREAMING_SNAKE`, one per config key | `OMNIWEAVE_MCP_LISTED` |
| CLI | `ow <group> <verb>`, both lower-case, **no aliases**; a group only at three or more verbs, and no two groups differ only by a trailing `s` (G25) | `ow store verify`, `ow drivers check` |
| CLI flag | `--kebab-case`; a named override starts `--allow-` or `--accept-` | `--allow-cost`, `--accept-partial` |
| error code | `OW-<AREA>-nnn` for a human, `OW_SCREAMING_SNAKE` for the stored and wire form | `OW-S-010` / `OW_SNAPSHOT_EXPIRED` |
| wire protocol | `<name>/<MAJOR>`, lower-case | `omniweave-target/1`, `parse/1`, `owsvg/1` |
| driver id | `<port>.<subject>.<impl>`, all lower-case `[a-z0-9_]` | `parse.office.anydoc` |
| prompt-safe token | a one-letter sigil plus digits, optionally corpus-qualified | `handbook:d7#412`, `e412` |
| registry file | `tools/<plural-noun>.toml`, one row per registered thing, append-only or generated | `tools/gates.toml`, `tools/risks.toml`, `tools/metrics.toml` |

### Suffixes and prefixes that carry meaning

- **`ow`** is the reserved vendor: `ow128`, `ow_*` views, `x.ow.*` extension keys, `<ow:untrusted>`,
  `ow:<section>` answer markers, the `ow` console script. No third party may use it.
- **`om`/`omni`** is never abbreviated. It is `omniweave` or `ow`, nothing in between.
- **`_sha256`** is always a 32-byte sha256. **`_digest`** is a digest whose width its **column type**
  gives: BLOB is a 16-byte `ow128`, TEXT is `sha256_canonical` hex. Where one name would carry both
  types it is split and the sha256 half takes `_sha256` (`content_digest`/`content_sha256`;
  `community.member_digest`/`cohort.member_sha256`). **Never `hash`.**
- **`_id`** is a durable surrogate integer, store-local, never in a prompt. **`cite`** is a
  prompt-safe token. **`addr`** is a type-free path address. **`el`** is an output-artefact element
  address. Four jobs, four suffixes, never interchanged.
- **`origin_*`** is ownership provenance (`origin_operator`, `origin_driver`), never trust.
- **bare `gen`** is the per-document **parse** generation and nothing else. Every other generation
  counter carries a qualifying prefix; the monotonic **run** counter is `generation`.
- **`ts_a`/`ts_b`** is a `TextSpan` (chars inside one block's text). **`os_*`** is an `OriginSpan`
  (an address in the original container). Never mixed.
- **`_frac`** is a `[0,1]` float; **`_rate`** is a `[0,1]` float over a population; **`_micros`** is
  money in millionths of the pricebook currency; **`_ms`/`_ns`** are durations.
- **`MAX_*`** is a ceiling a tenant may clamp below and never widen, and which the producer is built
  never to exceed. A number its own producer overshoots by design is a **`*_TARGET_*`**.
  **`MIN_*`** is a floor; exactly one gates startup (`MIN_SQLITE`).
- **`*_v`/`*_version`**: `driver_schema_v` and `op_version` are integers at every site, the
  `producer` column and the `Producer` field included; `RELEASE`, `driver_version` and
  `model_version` are strings.

### Plurals and verb forms

- SQL tables are **singular**, because a row is one of the thing. The one exception is a table whose
  row *is* a set (`entity_band`).
- A collection-valued config key is a bare plural (`enabled`, `formats`, `lanes`).
- A CLI verb is an **imperative** (`verify`, `explain`, `bless`) — never a gerund or a noun. The one
  deliberate exception is `ow bench <subject>`, whose second word is a positional subject from a
  closed set ([12](12-performance.md) §"New terms").
- A function returning a decision is named for the decision (`resolve`, `evaluate`, `admit`, `plan`),
  never `get_*` or `compute_*`.
- A function with a store side effect is named for the effect (`rebind`, `converge`, `freeze`).
- `check` is a CI-shaped byte-diff or contract assertion that exits non-zero; `verify` re-derives
  from stored bytes and compares; `doctor` reports the environment and never fails on a *warning*.
- `emit` writes a generated artefact to disk (`ow schema emit`); `render` turns internal state into
  text for a human or a model (`Answer.render`); `serialize` turns Blocks into a named view **and
  its `SpanMap`**.

### The identifier series, and who owns each prefix

Every numbered identifier a document cites belongs to exactly one series, and the owner column names
the document that assigns the numbers. Ten of these families are machine-checked: the nine invariant
prefixes `INV-<n>`, `M-INV-<n>`, `DR<n>`, `RT<n>`, `ST<n>`, `I<n>`, `GR<n>`, `OUT<n>` and `SV<n>`
resolve against `tools/invariants.toml` ([11](11-repo-layout.md) §"New terms") and `G<n>` against
`tools/gates.toml`, both under G27 clause d2 ([11](11-repo-layout.md) §8). The rest — `Q-G<n>`,
`P-<n>`, `AP-<n>`, `E<n>`, the `R`, `B`, `K-`, `FE` and `V` series — carry no register, so a reader
resolves them against the owning document, which is what this table is for. The full prefix map at
release 1:

| prefix | what it numbers | owner |
|---|---|---|
| `INV-1`…`INV-25` | framework-wide invariants | [charter](_notes/charter.md), extended by [01](01-principles.md) §1 |
| `M-INV-1`…`M-INV-5` | document-model-local invariants | [03](03-document-model.md) §19 |
| `DR1`…`DR24` | driver-system invariants | [04](04-driver-system.md) |
| `RT1`…`RT14` | router invariants | [05](05-ingest-and-routing.md) |
| `GR1`…`GR18` | graph invariants | [06](06-structure-extraction.md) |
| `ST1`…`ST22` | store invariants | [07](07-store-and-retrieval.md) §15 |
| `I1`…`I34` | runtime (scheduler) invariants | [08](08-runtime.md) |
| `OUT1`…`OUT24` | OUT-framework invariants | [09](09-generation.md) |
| `SV1`…`SV19` | serve-surface invariants | [10](10-interfaces.md) |
| `E1`…`E14` | driver-card extension items | [04](04-driver-system.md) |
| `G1`…`G27` | CI gates, **closed at 27** | [11](11-repo-layout.md) §8, register `tools/gates.toml` |
| `Q-G1`…`Q-G27` | quality gates | [13](13-quality.md) §14 |
| `P-1`…`P-13` | principles | [01](01-principles.md) §2 |
| `AP-1`…`AP-18` | anti-patterns | [01](01-principles.md) §3 |
| `P1`…`P31` | document-model conformance properties | [03](03-document-model.md) §17 |
| `P-1`…`P-22` | property-based tests | [13](13-quality.md) §6 |
| `R1`…`R7` | round-trip laws | [09](09-generation.md) §11.1 |
| `B01`…`B2n` | benchmark rows | [12](12-performance.md) §2 |
| `B1`…`B8` | trust boundaries | [14](14-security.md) §1.3 |
| `R1`…`R5` | failure runbooks | [15](15-observability.md) §11 |
| `M0`, `P1`…`P10` | build phases | [16](16-roadmap.md) §3 |
| `FE1`…`FE5` | forcing edges | [16](16-roadmap.md) §1.1 |
| `R-<CAT><n>` | risk-register rows | [17](17-risks.md) §3 |
| `K-1`…`K-13` | kill criteria | [17](17-risks.md) §5 |
| `P1`…`P6` | compound paths | [17](17-risks.md) §4 |
| `V01-n`, `V10-n`, `V20-n` | release acceptance criteria | [00](00-vision.md) §9 |

Five rows of that table collide. They are resolved in [Collisions](#collisions-resolved).

### Reserved, and forbidden

Reserved to omniweave — no third party may use them: the `ow` extension vendor (`x.ow.*`), the `ow`
console script, the `omniweave-*` distribution prefix, the `OMNIWEAVE_` env prefix, the
`omniweave.drivers` / `omniweave.targets` / `omniweave.backends` / `omniweave.operators` /
`omniweave.signals` entry-point groups, the `OW-*` and `OW_*` code namespaces, the `ow:` answer
section markers, the `<ow:untrusted>` element, `data-ow-el` / `data-ow-cite`, the four cite sigils
`d` `e` `c` `k`, and the five Port names. Forbidden anywhere in the framework: a field named `html`,
`markdown` or `md` on any model class; a second representation of a block's text, structure or
geometry; a `--force`, a `--warn-only`, a `--fix` or any gate bypass. The full forbidden list, with
its enforcement site per entry, is the lock's §4.

## Do not confuse

### The four identifier kinds

Every Block carries all four, and they answer four different questions. Substituting one for another
is the single most common naming error this section exists to prevent.

| name | type | scope | survives | who may see it |
|---|---|---|---|---|
| `block_id` | surrogate integer | store-local | a re-parse only if `rebind()` rebinds it | never a prompt, never a URL |
| `addr` | path string, `p14/3/r2c5` | `(doc_ord, gen)` | promoting a paragraph to a heading — the **kind is deliberately not in it** | CLI, URL, log, round-trip |
| `cite` | prompt-safe token, `handbook:d7#412` | corpus | forever; a retired cite carries `superseded_by` | the model, the answer, the artefact |
| `el` | IL element address, `u03/e17` | one output artefact | a recompile of the same IL bundle | the carrier file, `artifact_el`, an `OWC1` marker |

`doc_key` (the content-derived document identity) and `doc_ord` (its store-local ordinal) are a
fifth and sixth name, and they identify a *document*, not a Block. `ord` is a Block's position among
its siblings and is not an identifier at all.

### The two digest families

| family | width | function | SQL type | example |
|---|---|---|---|---|
| `ow128` | 16 bytes | `blake2b(canonical(obj), digest_size=16, person=domain)` | BLOB | `content_digest`, `layout_digest`, `segment.content_digest` |
| `sha256_canonical` | 32 bytes, stored as 64-char hex | `sha256(canonical(obj))` | TEXT | `policy_digest`, `config_digest`, `il_digest`, `cache_key` |

The rule is **one name, one type**. `content_digest` (BLOB, `ow128`, over the parsed content tree) and
`content_sha256` (TEXT, over the source bytes) are two columns because a BLOB never equals a TEXT;
`community.member_digest` and `cohort.member_sha256` are split for the same reason. `blake3_128` is
rejected — blake3 is not in the standard library. Neither family is ever spelled `hash`.

Adjacent and not a digest: `nsig` (a normalized-shape signature over an IL element),
`env_digest` (environment identity, one of the four components keying a `ProbeVerdict`; the
retired spelling `host_fingerprint` names the same thing and is never written), `writer_id`
(`sha256(host‖pid‖process_create_time)[:12]`), and `Store key id` (`sha256(derived_key)[:8]`, which
proves *which key* a store is under without carrying the key).

### The confidence and trust tiers

Six enums, all sound like "how much do we trust this", and none is a synonym for another.

| enum | question it answers | where |
|---|---|---|
| `Trust` | how the value was obtained — the epistemic ladder on a Block | [03](03-document-model.md) §8.2 |
| `Quote` | may this text be quoted byte-exactly — `VERBATIM`/`NORMALIZED`/`RECONSTRUCTED`/`SYNTHETIC` | [03](03-document-model.md) §8.3 |
| `Method` | which mechanism produced the Block — `ROUNDTRIP`, decode, OCR, and so on | [03](03-document-model.md) §8.4 |
| `TrustClass` | is the **source** internal or `untrusted_external` — the column on `unit` | [05](05-ingest-and-routing.md) §1.1 |
| `TrustTier` | is the **driver's supply chain** first-party, local or third-party | [04](04-driver-system.md) §4.2 |
| `LicenceTier` | what may this driver's output be used for | [04](04-driver-system.md) §7.1 |

`Taint` is a seventh and is a **bitmask**, not a tier: it ORs upward through L3 and says what a
document's content *may do*, not how much it is believed. `compute_tier` is a function over card
facts that returns a `LicenceTier`. `stability tier` (`T-CONTRACT`…`T-INTERNAL`) is a compatibility
promise about a file and has nothing to do with either. `Volatility tier` is a golden-fixture
sourcing class. `Rung` is spend, `Lane` is capability, and the rejected `tier 0`…`tier 3` conflated
the two.

### The generation counters

There are nine, and bare `gen` means exactly one of them.

| name | counts | scope |
|---|---|---|
| `gen` | **parse generations of one document, and nothing else** | `doc_key` |
| `generation` | runs, monotonic, never a clock | store |
| `artifact_gen` | compiles of one output artefact | artefact |
| `card_gen` | rewrites of one corpus card | corpus |
| `staged_gen` | the generation a parse is writing into but has not committed | document |
| `at_gen` / `retired_gen` | the generation an L3 row was created at / retired at | row |
| `built_gen` | the generation a derived index was built from | index |
| `last_seen_gen` | the run generation a watcher last saw a unit at | pending-set entry |

`Target generation` (`g_t = doc.gen + 1`) is the L2 face of the charter's `staged_gen`.

### The six `Verdict`-shaped types

`Verdict` alone is the retrieval honesty record. The others are named for what they judge, because
one name carrying six meanings is the collision class the lock's X14 exists to close.

| type | judges |
|---|---|
| `Verdict` | a retrieval result's honesty: state, gates, channels, freshness, coverage, confidence |
| `CacheVerdict` | one cache read (`hit`, `miss`, `miss_corrupt`, `hit_legacy`, …) |
| `ProbeVerdict` | whether a driver's environment can run it (`ok`/`degraded`/`unavailable`) |
| `QuoteVerdict` | whether a stored quote still matches the source bytes |
| `eval_verdict` | one evaluation run's pass/fail against a Guard or Budget |
| `Wrap verdict` | the build-versus-wrap decision for one external component |

`route_quality` — never `route_verdict` — is the router's scoreboard. `GateStatus` is the ten-value
OUT release gate; `EvalStatus` is the eval outcome. They are not the same enum.

### Plan, Unit, Evidence, Layer, Span, Runner

Six words the plan uses more than once, each disambiguated by its type name.

| word | the types that use it |
|---|---|
| plan | `Plan document`/`plan/1` (the run's derived JSON projection, [08](08-runtime.md)) · `Plan` (a gated OUT compile plan, [09](09-generation.md)) · `QueryPlan` (a retrieval plan, [07](07-store-and-retrieval.md)) · `DemandPlan` (a router's signal read set, [05](05-ingest-and-routing.md)) · `Operator.plan()` (a scheduling step's emitter) |
| unit | `unit` (an ingest roster row) · `OutUnit` (an addressable **output** unit: a slide, a page, a scene — spelled `Unit` until ADR-1 decision 7) · `UnitKey` = `(unit_uri, unit_part)` · `UnitRef` (a `UnitKey` plus `content_sha256`, connector and walked path) · `UnitCandidate` (metadata, no bytes) · `AcquiredUnit` (bytes fetched) · `UnitOutcome` (what a compile did to a `Unit`) · `Part` (one addressable piece **inside** a unit) |
| evidence | `Evidence` (the routing record, [05](05-ingest-and-routing.md)) · `ManualEvidence` (the OUT manual-region artefact) · `RenderedBlock` (a served answer block) · `edge_evidence`, `route_evidence` (tables) |
| layer | `Layer` (a Block's furniture column, [03](03-document-model.md) §5) · `CacheLayer` (`blob`/`call`/`embed`/`render`/`signal`) · L1–L6 (the architecture's stack, [02](02-architecture.md)) · `layers.toml` (the import DAG G4 reads) |
| span | `TextSpan` (`ts_a`/`ts_b`, chars in one block's text) · `OriginSpan` (`os_*`, an address in the original container) · `RenderSpan` (a range in a serialized view) · `SpanMap` (the mapping between them) · an OTLP trace span, [15](15-observability.md) |
| runner | `Runner` (a competitor adapter in `eval/runners/`, [13](13-quality.md)) · `Runner class pin` (the CI runner label a baseline was calibrated on, [11](11-repo-layout.md)) · the work runner (`StepResult`, `StepMetrics`, [08](08-runtime.md)) |

### Failure objects

Five, and which one a site produces is an architectural decision, not a style choice.

| object | raised or returned | scope | recorded in |
|---|---|---|---|
| `OwError` (and its ten `OW-<AREA>-*` subclasses) | **raised** | the process | an exit code, `ow explain` |
| `Diag` | **recorded**, never raised | one row of L2 | the `diag` table |
| `Finding` | **collected** | one OUT validation | `FindingSet`, `OutReport` |
| `Rejection` | **returned**, never raised | one candidate in one `resolve()` call | `resolution_report` |
| `Degradation` | **recorded** | one run, one cause | the run manifest, `Verdict` |
| `Failure` | `classify()`'s output | one attempt at one work row | `work`, `FailureClass` |

`ResourceLimit` is the one `OwError` obliged to name the knob that would need raising, which is why
it is not confined to a single area letter. `PolicyRefusal` is a refusal, not a failure — it names
the approving command.

### Verbs and near-verbs

| pair | difference |
|---|---|
| `probe()` vs Capability probe | `probe()` reads the cache and nothing else; a Capability probe proves a driver capability works |
| `nfc()` vs `normalize_k()` vs `normalize_key()` vs `normalize_eval()` vs `sanitize_label()` | canonical composition and nothing else — **INV-10's `bytes` branch is `nfc(decode(...)) == block.text`** (ADR-5 decision 1) · grounding, returning `(normalised, back)` and used by the `NORMALIZED` claim, not by the proof · an entity key · the evaluator's comparison normaliser · the display-preserving prompt/MCP filter |
| `canonical()` vs `canonical_projection()` vs `canonical_uri()` | the one JSON canonicaliser · the model's canonical view · a unit's identity URI |
| `redact()` vs `op.redact` | the pure message-boundary filter in `omniweave_core.events` · the store operator behind `ow store redact` |
| `Budget` vs `Guard` vs `Counter` | an absolute floor the product published · a delta against release N−1 · a ratcheting count |
| Stage vs `phase` | `Stage` is the nine-member pipeline vocabulary on `ow.stage`; `phase` is a durable resumption marker on `erasure` |
| `stage_ms` vs `timings_ms` | the run manifest's `Stage → ms` map · one document's driver-reported parse timings |

## Collisions resolved

One concept, one name. Every row below is a place two names met; the winner is what a document must
write, and the loser belongs in the `Rejected synonyms` column of the index so a later author
reaching for it is corrected.

### Resolved by the lock (§3), and therefore settled

The lock's §3 carries sixty rows. The index reproduces each rejected spelling against the name that
won, so they are searchable at the point of use. A mechanical check over the nineteen documents
found **no** document using a rejected spelling *as a name*; forty-one of the seventy rejected
identifiers do appear, and every appearance is one of three benign kinds: the name used in its
*other*, correct sense (`Layer` for a Block's furniture, `edge` for entity→entity, `Verdict` for the
retrieval record, `parse`/`derive` as Ports, `manifest` in "run manifest"); prose *about* the
rejection ("`Chunk` … rejected by the terminology lock", "every `blake3_128` in the source rulings is
`ow128`", "the file is `wire.py`, **not** `frames.py`"); or an ordinary English word (`Node` inside
`V01-14`, `Item` in "Item budgets", `norm` in "rather than the norm", `skip` as a verb, `defines`
in a citation of marker's source). The check therefore needs an allowlist, and the fourteen
ambiguous left-column entries are listed in [Open questions](#open-questions).

### Resolved here, because the lock does not cover them

| loser | winner | where the loser came from | why |
|---|---|---|---|
| `P-1`…`P-22` for property-based tests | `PB-1`…`PB-22` | [13](13-quality.md) §6 | `P-n` is a **principle** ([01](01-principles.md) §2). Two series, one prefix, both cited in review comments; `P-7` resolves to both "provenance resolvability" (13) and "the cheap mechanism runs first" (01), and every number through `P-13` collides the same way |
| `P1`…`P10` for build phases | `PH1`…`PH10` | [16](16-roadmap.md) §3 | collides with [03](03-document-model.md)'s conformance properties `P1`…`P31` and [17](17-risks.md)'s compound paths `P1`…`P6` |
| `P1`…`P6` for compound paths | `CP1`…`CP6` | [17](17-risks.md) §4 | same collision; `Compound path`'s own definition already spells the concept out, so the prefix is free to move |
| `R1`…`R5` for failure runbooks | `RB1`…`RB5` | [15](15-observability.md) §11 | `R1`…`R7` are the **round-trip laws** ([09](09-generation.md) §11.1), cited by [02](02-architecture.md), [08](08-runtime.md), [13](13-quality.md), [17](17-risks.md) and [18](18-api-sketch.md). "R2" must mean one thing |
| `B1`…`B8` for trust boundaries | `TB1`…`TB8` | [14](14-security.md) §1.3 | `B01`…`B2n` are **benchmark rows** ([12](12-performance.md) §2), quoted by number in [08](08-runtime.md) and [15](15-observability.md). Zero-padding is not a disambiguator |
| `MAX_TOTAL_BYTES` for the archive total | `MAX_CONTAINER_TOTAL_BYTES` | [14](14-security.md) §2.1, which adopted anydoc's own spelling (`anydoc/src/package/limits.rs`) | One ceiling, two names in two documents, which is INV-21 exactly. [05](05-ingest-and-routing.md) owns the `limits.py` container block, so its spelling wins, and the `CONTAINER` prefix is what keeps this ceiling distinct from `MAX_ASSET_TOTAL_BYTES`, which carries the identical 536 870 912. anydoc's test name `total_budget_exhaustion_reports_max_total_bytes` is quoted verbatim in [14](14-security.md) §2.2 — prose about the source, not a second constant |
| `tools/invariants.toml` defined twice | one file, owned by [11](11-repo-layout.md) | coined independently in [01](01-principles.md) and [11](11-repo-layout.md) | Same path, same content, two owners. [11](11-repo-layout.md) owns the `tools/*.toml` inventory and G27's implementation; [01](01-principles.md) is the consumer that requires it |
| `Operator` coined twice | one `Protocol`, [08](08-runtime.md) §6.1 | lock §2 and [08](08-runtime.md)'s "New terms" | Not a real collision — [08](08-runtime.md) gives the locked concept its signature. The lock row absorbs the fields. The **third** spelling, `OperatorABC`, is a real one and ADR-1 decision 7 struck it: see below |
| `canonical()` coined twice | one function, [04](04-driver-system.md) §2.8 | lock §2 and [04](04-driver-system.md)'s "New terms" | Same: [04](04-driver-system.md) fixes the exact `json.dumps` argument set the lock row describes |
| `constant` as a Kind | `const` | [04](04-driver-system.md)'s "New terms" (four rows) | The lock's Kind vocabulary spells it `const`. Normalized in the index |
| `field` as a Kind | `column` | [05](05-ingest-and-routing.md)'s `serves` row | The lock uses `column` for a card or table field |

Two Kinds the documents needed and the lock's vocabulary did not carry when this index was written.
**ADR-1 decision 3 adopted both into the lock**, so they are no longer this document's own facts;
the counts stand:

| Kind | what it labels | count in the index |
|---|---|---|
| `signal` | one registered `SignalSpec` key a routing rule may read | 13 |
| `driver-id` | one first-party driver's `<port>.<subject>.<impl>` id | 1 |

### Resolved by ADR-1, one name that was carrying two types

Five names each bound two types. ADR-1 decision 7 named the winner **and** what the loser becomes,
because picking a winner alone leaves the lock inconsistent in the direction rule 1 does not check.
All five losers are now rows in [the lock](_notes/terminology.md) §3, so a later author reaching for
one is corrected mechanically.

| loser | winner keeps the name | loser becomes | authority |
|---|---|---|---|
| `Scope` for L2's block selection | the runtime's ingest scope, charter D6 — older and more widely referenced | **`ViewScope`**, [03](03-document-model.md) §16.1 | `03#Q1` |
| `title` as a `block` column | `Kind.TITLE`, a document or slide title | **`block.label`**, and its wire key with it | `03#Q9` |
| `max_blocks` in `[retrieval.vec]` | `PackSpec.max_blocks = 60`, which really is a Block count | **`max_segments`** — it is a segment ceiling, and §1 puts the unit in the name | `07#D2` |
| `Unit` for OUT's addressable output unit | the `unit` table, the Roster — L2 and P2 DDL, so a rename would be a migration | **`OutUnit`**; the compounds `UnitOutcome`, `UnitRef`, `UnitKey`, `artifact_unit` and `unit.part_count` already disambiguate | `18#2` |
| `OperatorABC` | `Operator`, the `Protocol` in `omniweave_core/operator.py` | **struck** — a `Protocol` is not an abstract base class and the suffix is wrong on its face | `02#1` |

The rename sites outside this document and the lock are ADR-1 consequence 4 and land with the
documents that carry them: [03](03-document-model.md), [07](07-store-and-retrieval.md),
[09](09-generation.md), [18](18-api-sketch.md), `tools/wirekeys.toml` and `tools/config_axes.toml`.

## The index

745 rows: the 745 names of [the lock](_notes/terminology.md) §2, in the same order and with nothing
added — `nfc()`, the one row this index carried ahead of the lock, is now §2's own (see
[In one paragraph](#in-one-paragraph)). Sorted case-insensitively, ignoring a leading `.`, `_`, `[`,
`<`, `$` or backtick.
`Kind` uses the lock's vocabulary: `concept` · `type` · `enum` · `member` · `fn` (function or
method) · `proto` (Protocol or wire protocol) · `table` · `view` · `column` · `index` · `dist`
(distribution) · `pkg` (import package) · `module` · `file` · `dir` · `cfg` (config key) · `cli` ·
`invariant` · `const` · `code` (error/diagnostic code family) · `entry-point` · `signal` ·
`driver-id`. ADR-1 decision 3 dropped `gate` from that vocabulary — `tools/gates.toml` is the
G-series' register — and adopted `signal` and `driver-id`, which this index had already used.

| Term | Kind | Definition | Specified in | Rejected synonyms |
|---|---|---|---|---|
| Absence gate | concept | One of **fifteen** precedence-ordered checks a zero result must pass before it may be called `absent`. A new hazard adds a gate; it **never** adds a second citability rule. | [07](07-store-and-retrieval.md) §6.8 | — |
| `achieved` | column | The `Capabilities` a driver actually delivered **on this document**, stored on `doc`. May be lower than `declared`, never higher. **Serve reads this**, never a card. | [03](03-document-model.md) §2.9 | — |
| `acquire/1` | proto | The Port that turns a `Locator` into an `owroster-items/1` stream the **host** commits as `unit` roster rows plus blobs. A *connector* is an `acquire` driver. | [04](04-driver-system.md) §1.4 | — |
| `[acquire]` | file | The three non-monotone sibling tables added by E1, where an unknown key is a hard error, exactly as `[compile]` is (§5 X37). | [04](04-driver-system.md) §2.4 | — |
| `AcquiredUnit` | type | The `{"t":"fetched"}` record shape of `owroster-items/1`: both digests, the byte count, the `cas://` blob ref, the media-type hint, the etag and `fetched_at_ns`. Carries no identity — `RESULT.unit_index` says which unit it answers. | [05](05-ingest-and-routing.md) §1.1 | a `unit_uri` on the wire from a driver |
| `AcquireV1` | proto | The `acquire/1` Port's contract, in `omniweave_ports/ports.py`: `probe`, a static-config `__init__`, `enumerate(locator: Locator, io: DriverIO) -> DriverResult` emitting `owroster-items/1`, and `fetch(ref: UnitRef, io: DriverIO) -> DriverResult`. | [04](04-driver-system.md) §1.4 | an `Iterator` return across a Port seam |
| Action | concept | One capability of omniweave, declared exactly once as an `ActionSpec`, from which the CLI parser, the SDK method, the MCP tool schema, the catalog row, `llms.txt`, `AGENTS.md` and the router skill's table are all generated and byte-diff gated. | [10](10-interfaces.md) §2.1 | `ow_do`, a generic dispatcher tool |
| **action rule** / **modifier rule** | concept | The two kinds of `[[rule]]`. An action is first-match-wins per `(rung, lane, phase)`; a modifier contributes from every matching rule under a per-key monoid (§4.2). | [05](05-ingest-and-routing.md) §4.2 | — |
| `ActionSpec` | type | The frozen declaration of one Action: name, `mcp_name`, `listed_in`, read-only/idempotent/open-world bits, cost class, a ≤160-char summary, a ≤90-char `decision` clause, a validated example, input/output types, advanced-arg set, CLI verb tuple. | [10](10-interfaces.md) §2.1 | — |
| `activate()` | fn | The **only** site in the framework that imports a driver's `entrypoint`. Asserts the loaded class's `PORT` and `SCHEMA_VERSION` equal the card's before any work. | [04](04-driver-system.md) §5.3 | — |
| Activation | concept | Naming a discovered driver in `omniweave.toml [drivers] enabled`. Installation alone is *discovery* and is never consent (INV-5). | [04](04-driver-system.md) §4.8 | — |
| `addr` | column | The type-free, path-like address of a Block: `p14/3`, or `p14/3/r2c5` for a cell. Unique per `(doc_ord, gen)`. The archive's internal reference and the CLI/URL/log/round-trip address. | [03](03-document-model.md) §6.2 | — |
| `Addr` | type | `NewType("Addr", str)` over the `addr` column — `'p14/3'` or `'p14/3/r2c5'`. The Python identity of a type-free path address; `addr` is its storage. A NewType and its own column denote one concept in two Kinds and take two rows (§1). | [03](03-document-model.md) §6.2 | — |
| `Admission` | type | The runtime's four semaphore families — per cost class (units), per cost class (worker processes), the CPU render semaphore, and one per Service — plus `producer_should_pause()`, the water-mark hysteresis. | [08](08-runtime.md) §7.6 | — |
| `admit()` | fn | The impure gate that reserves a decision's estimate against the durable `BudgetLedger` **after** `evaluate()` has chosen. Outcomes `admitted \| deferred \| degraded`; exhaustion is written back as the evidence key `budget.exhausted`. | [05](05-ingest-and-routing.md) §Actions and modifiers | — |
| `AgentTarget` | proto | One install target (a host). A new host is **one file plus one registry row**: `detect`, `install`, `uninstall`, `print_config` (which must not touch the filesystem), `describe_paths`. | [10](10-interfaces.md) §7.1 | — |
| `agree.decode_vs_page` | concept | The free quality channel: when a part escalates you have already paid for two independent readings, so the normalised edit distance between them costs nothing and lands exactly on the population where the cheap driver is suspect. | [12](12-performance.md) §5.12 | — |
| `AimdState` | type | The per-`(driver_id, config_digest)` batch-adaptation state: the current batch, the card ceiling and the clean streak. | [08](08-runtime.md) §2.2 | — |
| `akind` | column | The **one** anchor/reference-kind vocabulary (`AnchorKind`), on **both** `anchor.akind` and `ref_site.akind` — two views join them by equality, so they must share a name and a vocabulary. | [06](06-structure-extraction.md) §1.3 | `ref_kind`, `ref_site.kind`, `entity_alias.akind` |
| `alias_kind` | column | `entity_alias`'s own kind vocabulary: `canonical`, `variant`, `abbrev`, `expansion`, `translit`, `llm`, `user`. **Not `akind`**, which is the anchor/reference vocabulary; the two sets are disjoint and one `enum_val` domain holds one vocabulary. | [06](06-structure-extraction.md) §1.3 | `entity_alias.akind` … i.e. `akind` |
| `anchor` | table | What a document **defines**: a globally- or document-scoped resolvable name, keyed `(doc_ord, gen, name_norm, akind)` over the fourteen-member `AnchorKind` vocabulary — a section number, a clause, a figure or table label, an equation, an exhibit, a … | [06](06-structure-extraction.md) §3.3 | `ref_name`, `defines` |
| `anchor_delta` | concept | The **per-document** symmetric difference of `(name_norm, akind)` pairs across a store phase. Added names retry the unresolved set on an index; removed names **unbind** every edge and `block_link` carrying that `bound_by`. | [06](06-structure-extraction.md) §1.4 | `ResolutionDelta` |
| `AnchorKind` | enum | The **one** fourteen-member vocabulary behind both `anchor.akind` and `ref_site.akind`: `section`, `clause`, `figure`, `table`, `equation`, `citekey`, `identifier`, `defined_term`, `footnote`, `exhibit`, `slide`, `sheet`, `glossary`, `bookmark`. | [06](06-structure-extraction.md) §1.7 | — |
| Answer | concept | The object `ow_query` and `ow open` return **and** the document they render to: a fixed-section text response with a status line, evidence blocks, provenance, back-references, pointers and a trailer. | [10](10-interfaces.md) §3.5 | — |
| Answer section | concept | One `**ow:<name>**`-marked region of an Answer. The order is fixed; truncation cuts whole sections and whole blocks, never mid-fence. Never an ATX heading. | [10](10-interfaces.md) §3.5 | — |
| **anti-pattern** (`AP-n`) | concept | A named shape this project has decided not to build, traced to a measured failure in the mined collection. Proposing one requires evidence the observed failure does not apply. Eighteen at release 1. | [01](01-principles.md) §3 | — |
| Approval window | concept | The interval during which a paused `release` environment can still be approved and produce a valid publish, bounded by the **shortest** retention on any artefact the publish job consumes — five days at release 1, set by `slsa-github-generator`'s … | [11](11-repo-layout.md) §1.1 | — |
| `artefact` | concept | Spelled **`artefact`** in prose and **`artifact`** in code and SQL (`artifact`, `artifact_unit`, `ArtifactRef`), because the identifiers were fixed first. Both mean: a file omniweave compiled out of the corpus. | [09](09-generation.md) §3.6 | — |
| `ArtefactDeterminism` | enum | The declared set over `{part, byte, frame, render}` at which two compiles of one artefact are equal. Compared `⊇`. `part` is the floor and is **promised**; `byte` is **recorded and never promised**. | [09](09-generation.md) §6 | — |
| `artifact` | table | One compiled artefact generation, keyed `(slug, artifact_gen)`: its bytes, its `part_digest`, its **retained IL bundle**, six input digests, gate status, delivery tier, degradations, and `read_back_doc_ord` — the loop as a foreign key. | [09](09-generation.md) §2 | — |
| `artifact_asset` | table | The ledger join from an artefact to L2's `asset` rows, with the IL slot, the role, the units it appears in, and `ratio_variants` (two ratios means the deck is stretching it). | [09](09-generation.md) §7 | — |
| `artifact_cite` | table | The **authoritative** citation channel: `(artifact, unit, el, cite)` with a pinned `doc_gen`, a citation kind, and a `verbatim` bit that is **proved**, never claimed. Answers "which decks quote page 14 of this contract" with one indexed query. | [09](09-generation.md) §2 | — |
| `artifact_el` | table | The host-written map from an IL element address to the Block that `read_back` produced from it. | [09](09-generation.md) §11.2 | — |
| `artifact_unit` | table | One output unit of one artefact: its `UnitOutcome`, its per-unit retained IL and `nsig`, and a `reason` that is mandatory for `baked` and `manual_required`. | [09](09-generation.md) §2 | — |
| `ArtifactKind` | enum | The closed, core-owned thirteen-member vocabulary behind `[capability] consumes` and `produces`. Adding a member bumps `card_schema`; there is no experimental namespace (E2). | [04](04-driver-system.md) §2.3 | — |
| `ArtifactRef` | type | The frozen `omniweave_ports` shape a driver returns bytes as: an artifact-kind member, `byte_len`, and **exactly one** of `inline` (set iff `byte_len <= INLINE_MAX = 262,144`) and `blob` (`cas://<sha256>`). `ArtifactRef.of()` is the single site that enforces an invocation's `max_output_bytes` ceiling, so no driver hand-rolls it and none evades it by writing many small blobs. | [04](04-driver-system.md) §1.3 | — |
| Assertion | concept | One ground-truth claim about one document in the eval corpus, carrying `checked ∈ {verified, rejected, NULL}`, `evaluable_in ∈ {owdoc, text, both}`, an optional `addr`, and `derived_from_sha256` — the licence chain for the assertion itself. | [13](13-quality.md) §4.5 | — |
| `asset` | table | A content-addressed binary belonging to a document: media type, sha256, dimensions, a `store_ref` into CAS, licence facts, and `restriction_bits`. **No inline bytes, ever.** | [09](09-generation.md) §7.3 | — |
| Asset slot | concept | `asset-slot:<sha256>` — the **only** asset syntax permitted inside an IL. Location-independent, so an IL compiles identically on another machine and needs no path normalisation before hashing. | [09](09-generation.md) §1 | — |
| `AssetDraft` | type | What `DocSink.add_asset` consumes alongside a stream: everything on `asset` except `asset_id`, `doc_ord`, `store_ref` and `restriction_bits`, which the host mints or stamps. Its `sha256` is a claim the host re-computes. | [03](03-document-model.md) §2.8 | — |
| `AssetLedger` | type | The OUT framework's writer and reader over L2's `asset` table for one compile: `slot()`, `freeze()`, `digest()`. | [09](09-generation.md) §7.1 | — |
| `AssetRef` | type | The read-side handle to one asset: identity, media type, dimensions, `store_ref` and `restriction_bits`, with no bytes. `Doc.asset(ref)` turns it into a stream. | [03](03-document-model.md) §2.8 | — |
| Attestation | concept | `sha256` over the canonical driver card minus the attestation key, written by `ow conform`. **Tamper-evidence, not a signature.** A mismatch sets `attested = false`, and an unattested driver is never auto-selected. | [11](11-repo-layout.md) §7.3 | — |
| Backend | concept | An implementation of a store or index seam, selected **by name in config**. Two kinds: a store backend (`sqlite`, `postgres`, `fabric`) and a `VectorBackend` behind the `omniweave.backends` entry point with a `backend.toml`. | [07](07-store-and-retrieval.md) §1.1 | — |
| `baselined` | column | A boolean the eval report **computes** from `eval/baselines/`: this Finding is byte-identical in the previous release's report for the same `(corpus, driver-major)`. Orthogonal to `Severity` and `Provenance`, and never declared by a generator. | [13](13-quality.md) §11.3 | — |
| `Basis` | type | The **host's** classification of how a format guess was obtained: `magic \| container_identity \| content_probe \| extension \| declared \| driver_sniff`. Six members. It is **not** a `FormatGuess` field and a driver may never assert it — `driver_sniff` is the member the host stamps on a driver's contribution. Lives in `omniweave/route/detect.py`, never in `omniweave_ports`. | [05](05-ingest-and-routing.md) §2.1 | — |
| Batch | concept | The set of claimed work rows sharing a `dispatch_key`, sent in one `INVOKE`. **Invisible to the work table, the spend ledger, the trace and the failure taxonomy**; visible only as span attributes. Adapted by AIMD. | [08](08-runtime.md) §2.2 | — |
| `BatchEvent` | enum | What `adapt_batch()` reacts to: `clean`, `resource_limit`, `worker_died`, `driver_crashed`. A projection of `FailureClass`, not a second taxonomy. | [08](08-runtime.md) §2.2 | — |
| **Billed share** | concept | The fraction of live Segments whose `covered_frac` for a lane falls **below** `llm_coverage_floor`, and which a billed Pass will therefore be handed in full. | [06](06-structure-extraction.md) §2.4 | — |
| `BlobStore` | proto | The `omniweave_ports` Protocol a driver reads and writes content-addressed bytes through: `path(digest)` (a read-only path under `roots.source_ro`), `open(digest)`, and `put(data) -> digest`, metered through `ArtifactRef.of`. Its sole implementation is `omniweave_core.blobs`; a Protocol and its one implementation are one concept and one row, not a collision. | [04](04-driver-system.md) §1.3 | — |
| Block | concept | The single node type of the document model. A row in `block`. Paragraphs, headings, figures, tables **and table cells** are all Blocks. | [03](03-document-model.md) §2.5 | `Node`, `Element`, `Item`, `Span` (as the node type) |
| `block` | table | The flat, append-only Block table: identity, containment (`parent_id` + `ord`), kind/layer/text, two digests, geometry, an `OriginSpan`, a `TextSpan`, six provenance axes, `restriction_bits`, a `decision_id`, and `state` (there is no `DELETE`). | [03](03-document-model.md) §2.5 | — |
| `block.flagged_frac` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `block_asset` | table | The many-to-many join from a Block to its assets, with a role. | [03](03-document-model.md) §11 | — |
| `block_cite` | index | `UNIQUE (doc_ord, cite)` on `block`, and **gen-free**: a cite must name at most one row for the life of the corpus, so inserting a block on re-parse cannot re-point a shipped citation. Read by every `cite` resolution on every surface. | [07](07-store-and-retrieval.md) §3.13 | `block_cite(doc_ord, gen, cite)` |
| `block_fts` | table | The lexical index: an FTS5 **external-content** table over `block.text`, so there is no second copy of the text. Unchanged by L4. | [07](07-store-and-retrieval.md) §3.3 | — |
| `block_history` | table | Retirement, instead of tombstones that outlive a generation: the retired `block_id`, its `superseded_by` (NULL means retired with no defensible successor), and a closed reason. | [03](03-document-model.md) §13.1 | — |
| `block_id` | column | An INTEGER, store-local, assigned once, never re-derived. **The only foreign-key target for a Block** — no layer references a Block by `addr`, `cite`, `(doc_ord, gen, page, ord)` or any other position. | [03](03-document-model.md) §6.1 | — |
| `block_link` | table | The **block→block** relation table: a resolved cross-reference or entity-mediated link with an observation site, a weight, an `ambiguous` bit, a `bound_by` anchor, and full provenance. Traversed by `Expand` during retrieval. | [07](07-store-and-retrieval.md) §3.6 | `edge` (for block→block) |
| `block_sec` | table | A derived section **prefix** index: for each Block, its nearest heading, its depth and a `sec_path` like `/1/4/2`, so "everything under §4.2" is a range scan. Not an ordering authority and not an identity. | [07](07-store-and-retrieval.md) §3.6 | — |
| `block_tri` | table | The optional trigram FTS5 table, created only at `[retrieval] trigram = true`. | [07](07-store-and-retrieval.md) §3.4 | — |
| `BlockDraft` | type | **The one mutable model type**, and it never reaches a reader: what an assembler builds and `DocSink.add_block` consumes. | [03](03-document-model.md) §2.6 | — |
| `BLOCKQUOTE` | member | The `Kind` member for quoted prose. Named so it cannot collide with the `Quote` tier enum. | [03](03-document-model.md) §2.1 | `Kind.QUOTE` |
| `bound_by` | column | The anchor `name_norm` that resolved an edge or a `block_link`. **Only a row carrying it may be unbound** by an `anchor_delta` removal — "never delete what we cannot restore". | [06](06-structure-extraction.md) §1.4 | — |
| `Box` | type | The one shape a `TextMeasure` returns: `advance`, `height`, `ascent`, `descent`, `lines: int` and `overflow: bool`, all six in **IL user units** — the unit `<svg>` root's `viewBox` coordinate system for `owsvg/1`, CSS px for `owdeck/1` and `owflow/1` — never EMU and never device pixels. | [09](09-generation.md) §4.4 | `Quad` is L2 page geometry in page coordinates; a `Box` is an IL-coordinate measurement and never reaches the store |
| Brief | concept | The frozen, machine-parseable authoring contract for an OUT run: a schema-version comment on line 1, then only `## section` headings and `- key: value` rows, with `## forbidden` items tagged `(user)` where they are the user's own words. | [09](09-generation.md) §13.2 | — |
| Budget | concept | (D10 sense) An **absolute floor** on a metric, owned by the product. Its breach means we shipped something worse than our published promise. Contrast **Guard**. | [12](12-performance.md) §2.3 | — |
| `budget.exhausted` | concept | The evidence key `admit()` writes back after a denial, and the only channel by which budget reaches a routing decision (INV-14). | [05](05-ingest-and-routing.md) §5.1 | — |
| `budget_id` | column | The `eval_perf` primary-key component naming one performance budget, spelled `<area>.<metric>[_<unit>]` — `query.warm_p50_ms`, `rss.gen5000p_peak_bytes`, `wal.bulk_index_peak_bytes`, `store.bytes_per_block`. | [12](12-performance.md) §2.4 | — |
| `budget_reservation` | table | A durable row holding an estimated `Spend` dimension against a scope until the work row commits, releases, or its lease expires. Headroom is computed **in SQL**. | [08](08-runtime.md) §1.5 | — |
| `BudgetLedger` | type | The durable ledger over `budget_reservation`: `reserve` / `commit` / `release` / `headroom` / `headroom_units`. One row per `(reservation, dim)`. Headroom is computed **in SQL**, never cached in an attribute. | [08](08-runtime.md) §1.3 | — |
| Bulk window | concept | A marked interval during which non-UNIQUE secondary indexes and FTS triggers are dropped for a bulk load. The marker is written **before** the first DDL, and an open marker at store open **refuses to serve**. | [07](07-store-and-retrieval.md) §10.6 | — |
| `byte` | member | The `ArtefactDeterminism` class meaning container bytes are identical. Asserted in CI under **one** pinned resolution, recorded in the receipt, **never promised to a user** — a zlib bump falsifies it. | [03](03-document-model.md) §7.4 | — |
| `byte_exact` | member | The `ReplayClass` meaning two separate processes with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd produce equal digests per block and an identical `Diag` multiset. | [07](07-store-and-retrieval.md) §8.2 | — |
| Cache layer | concept | One of `blob`, `call`, `embed`, `render`, `signal`; the enum is **`CacheLayer`**, never `Layer`. **There is no `parse` or `derive` layer:** if it is a row in the `.owstore` it is never also a blob in the cache. | [08](08-runtime.md) §4.1 | — |
| `cache_gc` | index | `cache_index(cost_class, last_hit_ns)` — the eviction scan's index. One index, one GC and one bill across all five `CacheLayer` values. | [08](08-runtime.md) §4.7 | — |
| `cache_index` | table | **One** table for all five cache layers, with the `Spend` that produced each row so a hit can replay it, the price at creation, a `partial` bit, and hit statistics. One index, one GC, one bill. | [08](08-runtime.md) §4 | — |
| `cache_key()` | fn | The **one** cache-key function, in `omniweave_core.cache`, returning `sha256_canonical(...)` — a 64-char hex TEXT. | [08](08-runtime.md) §4.2 | — |
| `CacheEntry` | type | One row `cache.put()` writes: layer, key, the blob, the `Spend`, the `partial` bit and the `(unit_uri, unit_part)` it belongs to. | [08](08-runtime.md) §4.6 | — |
| `CacheHit` | type | One decoded cache hit inside a `CacheProbe`: the artefact ref, the replayed `Spend`, the re-priced `micros` and the `CacheVerdict` (`hit` or `hit_legacy`). | [08](08-runtime.md) §5.5 | — |
| `CacheIndex` | type | The one accessor over the `cache_index` table: `get`, and `put(entries, allowed_units=…)` with a runner-supplied allowlist. Home of the six-clause read policy. There is no `parse` and no `derive` layer — a row in the `.owstore` is never also a blob in the cache (INV-1). | [08](08-runtime.md) §4.1 | — |
| `CacheLayer` | enum | `blob \| call \| embed \| render \| signal`, in `omniweave_core.cache`. **Renamed from `Layer`**, which is L2's Block layer: two enums of that name in one framework made the import ambiguous and made `WORTH_LAYER` and `cache_index.layer` read alike. | [08](08-runtime.md) §4.1 | `Layer` (for a cache layer), `parse`/`derive` as a cache layer |
| `CacheProbe` | type | What one batch cache-check returns: the decoded hits with their replayed `Spend`, the **outstanding** `UnitRef` list in order, a per-unit `CacheVerdict` map, the `hit_legacy` count and `would_have_been_micros` at the current `PriceBook`. | [08](08-runtime.md) §5.5 | — |
| `CacheVerdict` | enum | The six-clause cache read outcome: `hit \| miss \| miss_corrupt \| miss_partial \| miss_empty \| miss_unit_mismatch \| hit_legacy`. **Renamed from `Verdict`**, which is the retrieval honesty record. | [08](08-runtime.md) §4.5 | `Verdict` (for a cache read outcome) |
| `Calibrated` | type | The wrapper **every** confidence value crosses the serve boundary inside: the signal, the raw value, a `CalStatus`, this bucket's empirical accuracy and Wilson interval, `n`, `eval_set_id`, `slice_key`. | [16](16-roadmap.md) §2.2 | — |
| Call cache | concept | The `call` layer: a driver invocation's **raw response**, keyed on the cache key. The layer that makes a re-derivation of a corpus **within one store** cost CPU-seconds instead of a re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` is created by `0004_runtime.sql` inside the `.owstore`, so a fresh store opens with an empty cache and every `billed_api` response is billed again. | [08](08-runtime.md) §6.3 | — |
| `CalStatus` | type | The four-member `Literal["calibrated", "bootstrap", "uncalibrated", "stale"]` a `Calibrated` reading carries. `status != "calibrated"` permits the ordinal member name followed by `(uncalibrated)` and forbids a percentage, a numeral adjacent to the signal, a bar, a colour ramp or a grade (`Q-G14`, INV-19); a renderer test feeds all four values and asserts output **shape**. | [13](13-quality.md) §9.4 | — |
| `Cancellation` | type | The latched cause a `CancelToken` holds: a `CancelReason`, `at_mono_ns` from the injected `Clock` — **never** a wall clock, because `[runtime] shutdown_grace_ms` is measured from it and a backward NTP step must not turn a 5 s grace into an hour — and an operator-facing `detail` that is never parsed. Frozen because it is a value; the token, not this, is the latch. | [08](08-runtime.md) §1.3 | — |
| `CancelReason` | enum | `interrupt \| deadline \| shed \| client` — the four things that stop work, which differ in the `run.status` they leave, the process exit code, and whether a `run` row exists at all. First cause wins. **Supersession is not a member and must never become one:** a superseded `claimed_gen` is the other producer of `Outcome.CANCELLED`, and §8.1 exists to keep the two apart. | [08](08-runtime.md) §1.3 | a `SUPERSEDED` fifth member |
| `CancelToken` | type | One per **cancellation scope** in `omniweave_core.operator` — `run` on the ingest path, `request` on the serve path — checked at every loop top. A one-way latch: it **propagates** intent and latches one `Cancellation` naming the cause, while `claimed_gen` is the separate mechanism that makes a late result safe. Two mechanisms, not one. | [08](08-runtime.md) §1.3 | one token per run, one token per work row |
| `Candidate` | type | What `resolve()` returns per surviving driver: the `DriverCard`, the **host's** `isolation_granted` (never the card's request), the `[config]`-validated `effective_config` with defaults filled, and its `config_digest`. Purity requires that the ack set, the lockfile id set and the tombstone digest set are loaded into `Policy` at startup and never read from disk inside `resolve()`. | [04](04-driver-system.md) §4.8 | — |
| `canonical()` | fn | JSON with sorted keys, no NaN/Inf, geometry as i32 only, and **three distinct encodings for absent / null / `""`**. The input to every digest. | [04](04-driver-system.md) §2.8 | — |
| `canonical_projection()` | fn | The surrogate-id-free projection of the graph that a full build and an incremental build must agree on **byte for byte**. | [06](06-structure-extraction.md) §5.1 | — |
| `canonical_uri()` | fn | The one function that produces a `unit_uri`: realpath, normcase, `/` separators, `\\?\` stripped. | [05](05-ingest-and-routing.md) §The `acquire/1` Port | — |
| `Capabilities` | type | **One fifteen-field set**, and this dataclass, `driver.toml [capability.parse]` and `doc.declared`/`doc.achieved` are the same fields: `spatial`, `origin_span`, `text_span`, `marks`, `reading_order`, `sections`, `tables`, `math`, `assets`, `asset_origin`, `notes`, `confidence`, `furniture`, `round_trip`, `forfeits`. | [03](03-document-model.md) §2.9 | — |
| Capability floor | concept | The minimum acceptable value of one capability field in a `Requirement`. Ordered fields compare `>=`; `math` is a set and compares `⊇`; `text_span` and `marks` are booleans. **A filter, never a ranking key.** | [04](04-driver-system.md) §2.1 | — |
| Capability probe | concept | The **smallest real operation** that proves a capability works — not that a module imports. A tesseract without its language pack, a CUDA torch that fails on first kernel launch and an Ollama client with no model pulled all import fine. Cached per run, persisted 24 h per `(driver_id, driver_version, card_sha256, env_digest)` — four components, and `env_digest` is the only name for the environment half (ADR-7 D7.2; there is no `host_fingerprint`). | [12](12-performance.md) §3.2 | — |
| `card_schema` | column | The integer version of the DriverCard grammar. An unknown **top-level table** is a hard error; an unknown key inside `[capability.<port>]` is ignored with a recorded degradation — the one safe asymmetry. | [04](04-driver-system.md) §5.1 | — |
| Carrier | concept | The existing text format an IL is written in: `svg` or `html`. **Never invented; always has an existing parser.** | [09](09-generation.md) §3.1 | — |
| `CarrierDoc` | proto | A parsed IL file: `root`, `select`, `place_marker` (the only per-carrier feedback hook), `source`, `splice`. Splices sort descending by offset, apply, **reparse**, and are all-or-nothing. | [09](09-generation.md) §3.1 | — |
| `CarrierNode` | proto | One element of a parsed IL file, and the type every rule iterates: `at` (`"il/u03.svg:41:9"`), `el` (the `data-ow-el` address), `tag` in selector spelling, `nsig` (this subtree's digest only), `attr()`, `children()`, `text_content()`. | [09](09-generation.md) §3.1 | `text_content()` is raw subtree character data; `CarrierDoc.visible_text()` is the per-carrier definition R2 compares against |
| Cassette | concept | A content-addressed, replayable request/response log recorded at `DriverIO.service()` and `omniweave_core.modelserver` — **the only two outbound model channels a driver has**, so coverage is complete by construction. | [13](13-quality.md) §4.7 | — |
| `Catalog` | type | The metadata-only driver index built by `omniweave_core.discovery` from `importlib.metadata` and `tomllib` alone, holding one validated `DriverCard` per discovered `DriverId` plus a `catalog_digest` that enters `resolve()`'s memoisation key. | [02](02-architecture.md) §1.2 | — |
| `cell` | table | Origin cells only. **A cell *is* a Block**; this table adds `(r, c, row_span, col_span)` and the owning table. | [03](03-document-model.md) §10.3 | — |
| `CellDraft` | type | What `build_grid` consumes: an already-minted cell `BlockId` plus its `CellPos`. | [03](03-document-model.md) §2.6 | — |
| `CellPos` | type | A cell's grid position and spans, `(r, c, row_span, col_span)`, carried on a `BlockDraft` so a cell's `addr` step can be minted before `build_grid` runs. | [03](03-document-model.md) §2.6 | — |
| Channel | concept | One named retrieval mechanism producing a totally ordered, duplicate-free list of `block_id`s. **Exactly five:** `identity`, `exact`, `lexical`, `structural`, `semantic`. | [07](07-store-and-retrieval.md) §3.7 | — |
| `ChannelInput` | type | The **query material** bound to a `ChannelSpec` after `plan()` returns: sanitised terms, lifted `(name_norm, akind)` refs, identity candidates, the scope document, and the phase-2 query signature and full vector. | [07](07-store-and-retrieval.md) §16 | — |
| `ChannelResult` | type | One channel's output: name, `ChannelStatus`, a totally ordered duplicate-free `ranked` tuple, spans, identity grades, an explicit weight (0.0 included), a `reason` required when status is not OK, `truncated_at_limit`, timing and `Spend`. | [07](07-store-and-retrieval.md) §5.1 | — |
| `ChannelSpec` | type | One row of `QueryPlan.channels`: the Channel name, its **own** `budget_ms`, a channel-local `limit`, an over-fetch multiplier, an optional explicit weight (`0.0` included), flat scalar params, and a `bind: ChannelInput \| None`. | [07](07-store-and-retrieval.md) §16 | — |
| `ChannelStatus` | enum | `ok \| empty \| off \| unavailable`. | [07](07-store-and-retrieval.md) §5.1 | — |
| `charter_defects_open` | concept | The count of `class = "defect"` rows in [17](17-risks.md) sections 7.3 and 7.4 not yet discharged by an ADR in `_plan/adr/`. **Fifty-two** at the close of the nineteen plan documents, discharged by the twelve ADRs of section 7.6. | [17](17-risks.md) §7 | — |
| `CheckValue` | type | One row of a `Receipt.checks` tuple: a name, a value from `{passed, warning, failed, enforced-at-build, not-applicable, skipped}`, and an optional detail. | [09](09-generation.md) §5.3 | — |
| Churn class | concept | A tracked Reduction diff's three-valued classification, and the thing the golden gate gates on instead of a line-count percentage: **`incidental`** (only `cdig`/`ldig` changed, every counter and histogram unchanged, empty `shape` delta) merges with … | [13](13-quality.md) §5.4 | — |
| `cite` | column | The prompt-safe token. **The only kind of identifier that may appear in a prompt or in model output.** Grammar `[<corpus>:]d<doc_ord>#<n>` for a Block, with `e`, `c` and `k` sigils for Entity, Community and Claim. | [03](03-document-model.md) §6.3 | — |
| `Cite` | type | `NewType("Cite", str)` over the `cite` column — `'d7#412'` or `'handbook:d7#412'`. The Python identity of the prompt-safe token; `cite` is its storage. A NewType and its own column denote one concept in two Kinds and take two rows (§1). | [03](03-document-model.md) §6.3 | — |
| `CiteResolver` | proto | The read-only cite handle a `RuleCtx` carries: `by_cite()` and the batch `by_cites()`, and nothing else. No writes, no store handle, no retrieval. | [09](09-generation.md) §4.3 | — |
| `claim` | table | A subject-predicate-object assertion with a status, an optional time interval and precision, a bipartite object (an entity **or** a literal with a datatype, never both), an observation site, and the source block's `quote_tier`. | [06](06-structure-extraction.md) §9.5 | — |
| `classify()` | fn | The pure function `(FailureClass \| None, exception, provider, status_code) -> Failure`. Three tiers: the driver's structured class, then the HTTP status table, then the message table **with a recorded `Diag`**. | [08](08-runtime.md) §1.6 | — |
| `Clock` | proto | `monotonic_ns()` plus `wall_ns()`, **injected** on `RunContext`, never ambient. What makes the debounce and generation invariants testable without an operating system. | [08](08-runtime.md) §1.3 | — |
| Closure pass | concept | The `end_doc()` bottom-up rewrite of the `content_digest` of blocks whose subtree closes on a later page than their own. `O(cross-page containers)`. Why a merkle digest survives per-page transaction commit. | [03](03-document-model.md) §1.1 | — |
| Coalescing | concept | The **model server's** merging of requests from independent clients into one forward pass within `batch_wait_ms` up to `max_batch`. | [08](08-runtime.md) §3.6 | — |
| `codes.toml` | file | **The** error-code register. Append-only (G13), never renumbered, never reused. Every row carries a numeric `OW-<AREA>-nnn`, a symbolic alias, a meaning and **the exact command that clears it**. | [11](11-repo-layout.md) §1.1 | — |
| Cohort | concept | The member set of a corpus-granularity operator, identified by `member_sha256`, a merkle over `(unit_uri, unit_part, content_sha256)` in sorted order. Any member change re-derives the whole cohort — correct by construction, and expensive on purpose. | [04](04-driver-system.md) §2.5 | — |
| `cohort_member` | table | One `(cohort_id, unit_uri, unit_part)` row with the `content_sha256` observed at build time. Any change re-derives the whole cohort. | [07](07-store-and-retrieval.md) §3 | — |
| `community` | table | A cluster of entities at one level, durable across re-clusters by `member_digest` match, with a flat integer level (not `level.ordinal`, which is not stable), a NULL parent at the root (never `-1`), a size and a cohesion. | [06](06-structure-extraction.md) §1.3 | — |
| `community_member` | table | The `(community_id, entity_id)` membership join, reverse-indexed on the entity. | [06](06-structure-extraction.md) §1.1 | — |
| `community_report` | table | The demand-materialised prose report for a community, written on first descent. `report_state ∈ {absent, stale, fresh}`, a `trust` that can never be `EXTRACTED`, and a `coverage` fraction saying how much member evidence fit the context window. | [06](06-structure-extraction.md) §1.3 | — |
| `community_report_fresh` | view | The **only** report surface retrieval reads. A stale report is invisible, never silently served as current. | [06](06-structure-extraction.md) §1.1 | — |
| `compile/1` | proto | The Port that turns an IL bundle plus assets into artefact bytes and a receipt. | [04](04-driver-system.md) §1.1 | — |
| `CompileV1` | proto | The `compile/1` Driver's contract, and the one Port protocol that lives in **`omniweave_core.out`** rather than `omniweave_ports`: its signature mixes ports types with the OUT framework types a target is validated by, and a Protocol has to live in one distribution. | [18](18-api-sketch.md) §6.1 | — |
| Compound path | concept | A named conjunction of register rows whose joint consequence exceeds the sum of its parts, stated with the single earliest and cheapest decision that de-risks the whole path. | [17](17-risks.md) §4 | — |
| `ComputedDomain` | enum | A `SignalSpec.domain` that is not a literal in `signals.toml` because it depends on which drivers are enabled. One member at release 1 — `FORMAT_TOKENS`, core's 48 format tokens ∪ the `token` fields of the enabled cards' `[capability.parse] format_tokens` — resolved at policy-compile time and folded into `policy_digest`, so a rule naming a driver-contributed token lints exactly as a builtin token does and disabling the driver fails the linter rather than silently matching nothing. | [05](05-ingest-and-routing.md) §5.1 | — |
| `Config` | type | The frozen result of resolving the five configuration layers plus the declared `OMNIWEAVE_*` twins, exactly once at startup: `get`, `source_of`, and the `semantic`/`operational` projection behind `semantic_digest`. Frozen, with no mutator: an `Action` argument overrides a value for that call and never reaches this object. | [02](02-architecture.md) §8.4 | — |
| `config_digest` | concept | The digest of the **full** effective configuration. Two jobs: the run manifest, and setting the full-scan latch. **It does not enter a cache key** — `semantic_digest` does. | [02](02-architecture.md) §8.3 | — |
| `ConfigAxis` | enum | `semantic \| operational`, **required** on every `ConfigKey`. A `semantic` key changes what a cached artefact means and enters `semantic_digest`; an `operational` key changes only how the work was done. There is no third state, which is what makes G18's exact-coverage assertion over `tools/config_axes.toml` decidable. | [02](02-architecture.md) §8.4 | — |
| `ConfigError` | type | The `OW-C-*` member of the `OwError` tree: a configuration or startup failure, raised **only** during resolution and never after it. A model-id mismatch on attaching a Service is one, because retrying attaches to the same wrong server. | [02](02-architecture.md) §7.2 | — |
| `ConfigKey` | type | One key's **declaration site**, and the single home of its axis and its `OMNIWEAVE_*` twin: a dotted `name` whose segment may be `*` (`corpora.*.path`), `kind`, `default`, `axis` (**no default**, so an unclassified key is a `TypeError` at import rather than a gated warning), `env`, `choices` and `item_kind`. `tools/config_axes.toml` is generated from the registry of these and byte-diffed by G18. | [02](02-architecture.md) §8.4 | — |
| `ConfigKind` | enum | The ten coercers, one per distinct `type` in the key table: `str`, `int`, `float`, `bool`, `path`, `enum`, `list`, `table`, `matrix`, `str_or_list`. `matrix` (`serve.packing.tier`'s alone) and `str_or_list` (`serve.enabled`'s alone) are **named** rather than special-cased, so the coercion table has no `else` branch and no `str()` fallback exists to reach (I12). | [02](02-architecture.md) §8.4 | — |
| `ConfigLayer` | enum | The precedence ladder as an `IntEnum`, lowest first: `BUILTIN`, `USER_FILE`, `PYPROJECT` (only when no `omniweave.toml` was found), `PROJECT_FILE`, `EXPLICIT_FILE`, `ENV`. The declared `OMNIWEAVE_*` twins sit above the whole file chain, which is what "applied over the file layers" means. | [02](02-architecture.md) §8.4 | — |
| `ConfigSource` | type | Where **one** resolved value came from: the `ConfigLayer`, the file and the **line** for the three file layers, the twin that won for `ENV`, and `render()` — `'./omniweave.toml:141'`, `'OMNIWEAVE_MCP_LISTED'`, `'(built-in)'`. The line is recorded during the loader's single raw scan because `tomllib` reports none, and without it a precedence complaint is a bisect instead of one command's output. | [02](02-architecture.md) §8.4 | — |
| `ConfigValue` | type | The finite, **non-recursive** value grammar one config key may hold: a `Scalar`, a tuple of `Scalar` (`drivers.enabled`), a tuple of tuples — the one nested shape, `serve.packing.tier`'s five eight-column rows, a matrix and never a tree — or a `Mapping[str, Scalar]`. Non-recursive by contract: it is what keeps coercion at ~250 property-tested lines and makes "JSON-canonicalisable by contract" (I12) checkable without pydantic. | [02](02-architecture.md) §8.4 | — |
| `confine()` | fn | The **one** path-confinement function, in `omniweave_core.paths`: `resolve()` **then** `relative_to()` against an **existing** base, refusing absolute and drive-relative members, `..` segments, symlinked and junctioned parents, Windows reserved device names, alternate data streams, trailing dots and spaces, and 8.3 short names. | [14](14-security.md) §2.3 | — |
| Construct | concept | One row of a ConstructTable: an id, a selector, a `Disposition`, a `RoundTrip` class, a canonical spelling, a `maps_to` symbol and an `OW-T-nnn` code. | [04](04-driver-system.md) §1.1 | — |
| ConstructTable | concept | `constructs.toml` — the IL contract **as data**, one row per allowed construct. Read by the validator, the compiler, the doc generator and the conformance kit; hand-written by nobody else. `unknown_construct = "forbidden"` and it is not configurable. | [09](09-generation.md) §3.4 | — |
| `ContainerBudget` | type | The single decompression accumulator threaded through one container expansion tree. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit | — |
| `content_digest` | column | `ow128` over `(kind, layer, NFC text, kind payload, children's content_digests in ord order)`, a **16-byte BLOB**, on `block` and `segment` only. **Geometry is deliberately not an input**, so a driver upgrade's bbox jitter cannot orphan a document. | [03](03-document-model.md) §2.5 | — |
| `content_sha256` | column | The hex `sha256` over a unit's **normalised load-bearing source bytes**, on `unit`, `cohort_member`, `route_decision` and `route_signal`. | [05](05-ingest-and-routing.md) §The `acquire/1` Port | `content_digest` (for source bytes) |
| `CONTRACT` | concept | The small integer driver/target ABI in `omniweave_core.contract`. **The only version a third party pins.** It may change only on a `RELEASE` MINOR, and doing so is an announced, migration-guided product event. | [11](11-repo-layout.md) §4.1 | — |
| `Control guard` | concept | A Guard whose baseline is the **paired control arm of the same run** rather than release N−1. One exists: `bench/serve/`'s `task_accuracy` on the omniweave arm may not fall below the no-omniweave arm at paired `p < 0.01`. | [13](13-quality.md) §8.8 | — |
| Converge pass | concept | `op.converge`, the run-final step that computes the `anchor_delta`, applies the `dep` reverse index, runs the per-unit attribution guard, and enqueues what changed. | [08](08-runtime.md) §1.5 | `host.converge` |
| `corpus_card` | table | The generated, **non-LLM** description of a corpus, one row per `card_gen`: counts, formats, languages, an outline sample, top terms, coverage gaps with their codes and fix commands, the achieved capability **floor**, trust and quote histograms, `verbatim_fraction`, embedding metadata. | [10](10-interfaces.md) §1.4 | — |
| `corpus_id` | column | The corpus **name**, TEXT, matching `[a-z0-9][a-z0-9_-]{0,31}`. The same string a qualified cite carries. | [07](07-store-and-retrieval.md) §2 | — |
| `CorpusSet` | type | The cross-corpus fan-out handle returned by `omniweave.corpora([names])`. | [18](18-api-sketch.md) §1.1 | — |
| `cost_class` | column | `free \| local_compute \| billed_api`. Author-declared **and** kit-verified. The single ordering key for deterministic-first pass selection, and the axis on which admission, caching, namespacing and sweeping all differ. | [08](08-runtime.md) §3.4 | — |
| `CostClass` | enum | `free \| local_compute \| billed_api`. The single ordering key for deterministic-first pass selection, and the axis on which admission, caching, namespacing and sweeping all differ. | [08](08-runtime.md) §2.1 | — |
| `CostShape` | enum | `constant \| linear_per_part \| linear_per_byte \| linear_per_token` — the `[cost.model] shape` values. | [05](05-ingest-and-routing.md) §6.3 | — |
| Counter | concept | A named, **exactly reproducible** integer harvested from the run manifest, `route_spend` and `driver_observation`, gated `exact` (±1 fails) or `ratchet`. | [13](13-quality.md) §2.8 | — |
| Cover | concept | A Pass's claim that it looked at a set of a Segment's blocks for one lane **and its answer is complete**. A `derive_cover` row with a per-block bitmap. A Pass with zero items must instead write `cover_empty` **with a reason**. | [06](06-structure-extraction.md) §2.2 | — |
| `Coverage` | type | What `Reader.coverage()` returns and what absence gates 4-9 read: discovered/indexed/partial/failed/skipped counts, a `complete` bit, **`scope_rows`** (0 means coverage is *unknown*, not clean), pending work, stale and unreadable unit counts, and the already-grouped `DegradeCause` rows from gate 9's `diag` join. | [07](07-store-and-retrieval.md) §3.8 | — |
| Coverage gap | concept | A row of the corpus card derived from the `diag` table, naming documents or pages the index does not contain **and why**. The input to absence gate `parse_gap_in_scope`. | [12](12-performance.md) §3.3 | — |
| Coverage ordering | concept | The rule that a Pass's eligibility is decided by **`(cost_rank, phase)`** and the Cover already recorded by cheaper Passes. | [17](17-risks.md) §3.1 | — |
| **Decision point** | concept | A row of §17: a dated obligation to close a deferred item, with a named owner and a **pre-committed** action that executes automatically if the date passes unmeasured. | [16](16-roadmap.md) §17 | — |
| `declared` | column | The `Capabilities` a driver's card claims, copied onto `doc` at parse time. Compare `achieved`. | [03](03-document-model.md) §2.9 | — |
| Deep golden | concept | The exploded, uncompressed `.owdoc.d/` archive committed for at most 24 documents of at most 40 pages, so `rebind()` has two real generations to match. The only committed artefact from which a semantic diff can be produced after a driver upgrade. | [13](13-quality.md) §4 | — |
| `deferred_sweeper` | fn | The Supervisor task that returns `deferred` rows to `pending` when headroom reappears. | [08](08-runtime.md) §1.2 | — |
| **`DEFTERM_MAX_PER_BLOCK`** | const | `16`. The bound on definition-pattern matches taken from one block, with 512 characters of trailing context per match. | [06](06-structure-extraction.md) §3.5 | — |
| `Degradation` | type | The framework's **single** typed downgrade record, *carried* and never raised: a `DegradationKind`, a human `message` that must name the knob or the command that undoes it, what was downgraded (`unit_uri`, `parts_affected`, `wanted_driver`), the arithmetic when the cause is a bound that was reached (`unit_dim`, `spent`, `limit`, `rung_reached`), and the recovery (`knob`, `fix_command`). The twenty-seven-member register in [15](15-observability.md) §6.3 **is** the enumeration; this row does not restate a subset of it. | [15](15-observability.md) §6.3 | — |
| `DegradationKind` | enum | The closed **twenty-seven**-member vocabulary behind `Degradation.kind`, grouped as routing and admission (8), drivers, isolation, packaging and the toolchain (6), store, cache and the read path (8), and generation, governance and telemetry (5). **Seven of the twenty-seven force `degraded`**, and that is this type's whole interface to the honest-absence contract. Extended by literal, never re-invented per layer (charter §5 X21). | [15](15-observability.md) §6.3 | a per-layer downgrade enum |
| `DegradationRollup` | type | The **value** of one `manifest.degradations[<kind>]` entry, and what keeps the manifest bounded when a 188-part document produces 188 `budget` records: the kind, the count `n` merged into it, first and last injected-`Clock` timestamps, the distinct redacted `units` and the union of `parts_affected` both capped at `MAX_ROLLUP_PARTS = 64`, a `truncated` bit so a reader never reads the cap as the total, and the first record verbatim as `exemplar`. | [15](15-observability.md) §6.3 | — |
| `DegradeCause` | type | One absence gate's explanation: the gate, a detail string, the `diag` codes behind it, the `(doc, page_lo, page_hi)` ranges it covers, and **the exact command that clears it**. One per gate that failed, never a summary of several. | [07](07-store-and-retrieval.md) §6.7 | — |
| `DemandPlan` | type | Per `(rung, lane, phase)`, the reachable rules' read set grouped by `CostClass` ascending. | [05](05-ingest-and-routing.md) | — |
| `Dep` | type | One recorded cross-unit input and its closed kind `unit \| part \| name \| cohort \| policy \| service_model`. Reverse-indexed on `(kind, key)`, so invalidation is one query and never a sweep. | [08](08-runtime.md) §9.2 | — |
| `dep` | table | One row per input a derivation read **outside its own unit**, of closed kind `unit \| part \| name \| cohort \| policy \| service_model`, carrying the digest observed at derivation time. | [08](08-runtime.md) §4.8 | — |
| `DepKind` | enum | One recorded cross-unit input and its closed kind `unit \| part \| name \| cohort \| policy \| service_model`. Reverse-indexed on `(kind, key)`, so invalidation is one query and never a sweep. | [08](08-runtime.md) §Extends the charter | — |
| `[deprecation]` | file | A driver's own retirement schedule: `since`, `removed_in`, `replaced_by`, `reason`, with a **minimum two-MINOR window** matching G16 (E8). | [04](04-driver-system.md) §2.1 | — |
| `derive/1` | proto | The Port that turns document content into items: segments, anchors, cross-references, entities, mentions, edges, claims, extracted fields, reports. *Chunkers* and *extractors* are both `derive` drivers. | [04](04-driver-system.md) §1.1 | — |
| `[derive]` | file | The three non-monotone sibling tables added by E1, where an unknown key is a hard error, exactly as `[compile]` is (§5 X37). | [04](04-driver-system.md) §2.4 | — |
| `derive_admission()` | fn | The preflight function mapping `(Config, HostFacts)` to `Admission`. `os.process_cpu_count()`, not `cpu_count()`. Every semaphore is an `asyncio.BoundedSemaphore`; the RAM check is a **refusal** naming `[drivers] max_workers`, never a silent clamp. | [08](08-runtime.md) §2.1 | — |
| `derive_cover` | table | The coverage ledger: `(segment, lane, run)` with a `cover_bits` bitmap (≤ 64 B at 512 blocks), `n_covered`, and an `empty_reason` that is non-NULL exactly when the pass covered ground and emitted nothing. | [06](06-structure-extraction.md) §1.1 | — |
| `derive_pass` | table | The pass registry — **data, not a hardcoded pipeline list**. `pass_id` (a DriverId, or `op.<name>`), `port` (`derive/1` or `op`), cost class, `cost_rank`, **`phase`**, lanes, granularity, card digest, schema version, enabled bit. | [06](06-structure-extraction.md) §1.1 | — |
| `derive_run` | table | One execution of one Pass over one Segment, holding the interned reproduction tuple, the input digest, the **`cache_key` (TEXT, from the one `cache_key()` in `omniweave_core.cache`)**, the status and the `Spend`. | [06](06-structure-extraction.md) §1.1 | — |
| `DerivedRows` | type | The batch of L2/L3 rows one `Store.complete()` call commits, so the transaction boundary is a parameter rather than a convention. | [08](08-runtime.md) §9.2 | — |
| `DeriveScope` | type | The `derive/1` input: the lane, the `UnitRef` tuple, `allowed_cites` — **the containment boundary** — and the optional JSON schema and closed corpus vocabulary. An item citing outside `allowed_cites` is quarantined **by the host**, never dropped by the driver. | [04](04-driver-system.md) §1.3 | — |
| `Determinism` | cfg | The `[capability.compile]` key holding the `ArtefactDeterminism` set. | [09](09-generation.md) §6 | — |
| `Diag` | type | A **recorded** diagnostic against a document, page, block or part, with a code from `codes.toml`, a severity, a component, a message, a detail bag and a `fatal` bit. `Diag` is recorded; `OwError` is raised. Two names for two things. | [03](03-document-model.md) §9 | — |
| `diag` | table | Where `Diag` rows live. **Failure is a field, not an exception.** `CREATE INDEX diag_code` exists specifically so the absence contract can join against it. | [03](03-document-model.md) §9 | — |
| `digest_recipe` | concept | The integer version of the L2 digest definitions. | [03](03-document-model.md) §15.1 | — |
| Discovery | concept | Building the driver catalog from `importlib.metadata` and `tomllib` alone. **Discovery never executes driver code** (INV-4) and **discovery is not consent** (INV-5). | [04](04-driver-system.md) §4.4 | — |
| `discovery_slow` | member | A `Degradation.kind` literal recorded when `Catalog.build()` crosses its 250 ms hard ceiling, naming the slowest step and the installed-distribution count (E4). | [04](04-driver-system.md) §In one paragraph | — |
| Dispatch key | concept | `sha256(driver_id‖config_digest‖isolation)[:16]`, denormalised onto the work row by the planner. Two rows may share one `INVOKE` **iff** they share it. | [08](08-runtime.md) §In one paragraph | — |
| `Disposition` | enum | What the compiler does with an IL construct: `native \| normalize \| bake \| forbidden`. `manual_required` is deliberately **not** one, because a disposition says what the compiler does and `manual` says what a human must do. | [17](17-risks.md) §3.1 | — |
| `Doc` | type | A **lazy handle**, not a loaded object. Every traversal returns an iterator. There is deliberately no `Doc.pages: list[Page]` and no `Doc.blocks: list[Block]`. | [03](03-document-model.md) §4.3 | — |
| `doc` | table | **One row per `doc_key`**, whose `gen` is the head generation. Historical generations survive as `block`/`page` rows keyed `(doc_ord, gen)`. | [03](03-document-model.md) §1.1 | — |
| `doc.rung_run_length` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `doc_key` | column | `sha256` of a document's **normalized** source bytes, truncated to 16 bytes — computed after a per-format normalizer strips volatile metadata (PDF `/ModDate`, OOXML `w:rsid*`, frontmatter, EXIF). Global content identity of a document. | [03](03-document-model.md) §6 | — |
| `doc_ord` | column | The corpus-local ordinal of a document, and the number inside a Block `cite`. Assigned once per `doc_key`. | [03](03-document-model.md) §2.5 | — |
| `DocIndex` | type | *(coined here)* The bounded per-roster summary the rule runner builds during its unit pass and hands to every `scope = "document"` rule: per unit, the stamped `el` set, `el -> nsig`, a construct counter, the cite set, the asset-slot set, the marker list, and cross-unit value occurrence counters. | [09](09-generation.md) §4.4 | — |
| `DocRecord` | type | The frozen per-document record `DocSink.begin_doc`/`end_doc` carry and `Doc.rec` exposes — the `doc` row as a value type. Its `gen` is the generation it describes. | [03](03-document-model.md) §2.8 | — |
| `docs/CLEAN-ROOM.md` | file | The clean-room provenance record: one row per component whose [16](16-roadmap.md) `Wrap verdict` is `reimplement` or `reject`, naming the upstream repository, its licence, the commit read, what was taken (a shape, a constant, a published algorithm), what was not, and the author's attestation that no code was copied. | [17](17-risks.md) §3.3 | — |
| `DocSink` | proto | The **host-side** write protocol for L2. Never handed to a driver, never reachable from `DriverIO`. `end_page()` commits one transaction. | [03](03-document-model.md) §1 | — |
| Draft | concept | (L3) An item a `derive/1` driver emits over `owgraph-items/1`, addressing blocks by `cite` and other drafts by a per-invocation `tmp` id. | [06](06-structure-extraction.md) §1.7 | — |
| Driver | concept | One implementation of exactly **one** Port, shipped as one distribution, described by one DriverCard. Parsers, OCR engines, chunkers, extractors, embedders, compilers and connectors are all Drivers. | [04](04-driver-system.md) §1.1 | — |
| `driver.toml` | file | The on-disk file holding one DriverCard, inside the package the entry point names. | [04](04-driver-system.md) §2 | `omniweave-driver.toml` |
| `driver.unavailable` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `[driver] exec` | column | An argv list, relative to the card's own directory, by which a non-Python `driver_path` driver names its executable. | [04](04-driver-system.md) §6.7 | — |
| `driver_card_cache` | table | The metadata-only card cache, keyed `(prefix, dist_name, dist_version, card_path)` with mtime and size as the validity key — measured at 1.01 ms for 328 distributions, against 2124 ms for a `RECORD` scan. | [04](04-driver-system.md) §4.3 | — |
| `driver_observation` | table | The operability artefact: which drivers ran, under what isolation and licence tier, what they cost, how often they crashed, and whether they were quarantined. | [15](15-observability.md) §5.2 | — |
| `driver_schema_v` | column | A driver's `schema_version` at the moment it produced this row. **The only driver version that enters a cache key.** | [03](03-document-model.md) §2.5 | — |
| `driver_unavailable` | member | A `Degradation.kind` literal recorded when an entry point resolves and its `driver.toml` is missing or unreadable — a partially uninstalled distribution, or a wheel built without package data. Names the distribution; never stops a catalog. | [04](04-driver-system.md) §4.5 | — |
| DriverCard | concept | The TOML descriptor (`driver.toml`) core reads **without importing the driver**. The only thing `resolve()` sees. **Never called a manifest** — "run manifest" is the runtime's. | [04](04-driver-system.md) §2 | `manifest` (for a card), `Registry key` (for its id) |
| `DriverError` | type | The driver-facing exception in `omniweave_ports`: a `FailureClass`, a message, `retry_after_ms` (required iff transient), the pages a `needs_ocr` names, and the `limit` a `resource_limit` names. | [04](04-driver-system.md) §1.3 | — |
| `DriverGuard` | type | `omniweave_core/host/inproc.py`'s call boundary for an `inproc` driver: it catches `BaseException` and converts anything that is not a `DriverError` into `FailureClass.driver_bug`, so nothing propagates into the supervisor loop. Interpreter-state corruption is unrecoverable here by construction — the fifth reason `inproc` is gated to a fuzz-green first-party driver. | [02](02-architecture.md) §7.5 | — |
| `DriverHandle` | type | What `activate(candidate, host) -> DriverHandle` returns: the imported, `PORT`- and `SCHEMA_VERSION`-asserted driver bound to its host. The only object the runtime invokes work through. | [04](04-driver-system.md) §5.3 | — |
| `DriverHost` | concept | The executor for one Isolation mode: `inproc`, `subproc`, `wasm` (not built at v1). | [02](02-architecture.md) §1.2 | — |
| `DriverHostError` | type | The `OW-D-*` member: a driver-protocol failure attributable to **the framework or the wire**, not to the driver — a frame violating `wire.py`'s caps, an unknown frame `kind`, a card/code mismatch at `activate()`. | [02](02-architecture.md) §7.2 | — |
| `DriverId` | type | `<port>.<subject>.<impl>` — e.g. `parse.office.anydoc`. Fully qualified as `<id>@<dist>`. | [04](04-driver-system.md) §2.7 | `Registry key` |
| `DriverIO` | type | **The only channel a driver has to the outside**: blobs, a per-invocation tmpdir, deadlines, a max output size, `service()`, `cancelled()`, `log()`, `progress()`. | [04](04-driver-system.md) §1.3 | — |
| `DriverMetrics` | type | **Physical units only:** `wall_ms`, `cpu_ms`, `gpu_ms`, `tokens_in`, `tokens_out`, `calls`, `bytes_egress`, `bytes_read`, `peak_rss_bytes`. **No currency field, ever.** | [04](04-driver-system.md) §1.3 | — |
| `DriverResult` | type | What a driver returns: `ok \| ok_partial`, produced artefact refs, an optional partial reason, and `DriverMetrics`. **Strictly smaller** than `StepResult`: a driver cannot claim a cache hit, a budget deferral, a cancellation, an identity or a price. | [04](04-driver-system.md) §1.3 | — |
| `edge` | table | The **entity→entity** relation table: weighted, clustered, traversed, with the observation site where the relationship was *seen* (distinct from where either endpoint is defined), a `bound_by` anchor, a corroboration count that is **not** a promotion, and full provenance. | [06](06-structure-extraction.md) §1.4 | — |
| `edge_bound` | index | `edge(bound_by) WHERE bound_by IS NOT NULL` — the partial index `anchor_delta` unbinds through when a document's defined names change. | **none** — charter L3 DDL only | — |
| `edge_evidence` | table | Which mentions witnessed an edge, in which slot (`src`, `dst`, `predicate`). Drives `locate()`. | [06](06-structure-extraction.md) §1.1 | — |
| Egress audit hook | concept | The PEP 578 `sys.addaudithook` guard on `socket.connect`, armed under `[egress] mode = "none"` in the host **and in every `subproc` worker, before `activate()`**. The **secondary** net for egress paths no explicit check covers. | [14](14-security.md) §5 | — |
| `[egress] mode` | cfg | `none \| granted \| open`; `open` is env-only and a file value is a startup error. Classified `operational`. | [14](14-security.md) §5.3 | — |
| `el` | concept | The stamped IL element address, `u03/e17`, carried as `data-ow-el`. Minted once by `ow out stamp`, **never renumbered**, refused on a duplicate. The positional half of the two-factor edit anchor; `nsig` is the content half. | [09](09-generation.md) §3.4 | — |
| `embed/1` | proto | The Port that turns texts into vectors. An embedder is a Driver, not a Service — it has a model identity that enters index metadata, a `(dim, metric, normalization)` contract the store must match, a cost class and a licence. | [04](04-driver-system.md) §1.1 | — |
| `[embed]` | file | The three non-monotone sibling tables added by E1, where an unknown key is a hard error, exactly as `[compile]` is (§5 X37). | [04](04-driver-system.md) §2.4 | — |
| `embed_ms` | cfg | The **phase-2** deadline: the time allowed to embed a query, spent **before** `snapshot()` opens and therefore outside `query_ms`. | [07](07-store-and-retrieval.md) §4.4 | — |
| `embed_space` | table | The row pinning the **nine-field** embedding identity (model, exact revision, dim, metric, normalisation, pooling, the two prompt digests, driver + schema version). | [07](07-store-and-retrieval.md) §3.7 | — |
| `EmbedManifest` | type | `(dim, metric, normalization, model_id, model_revision, max_tokens)` returned by `EmbedV1.manifest()` and asserted equal to the card's `[embed]` table, on the same grounds as `HELLO_ACK`. | [04](04-driver-system.md) §1.3 | — |
| Emission ledger | concept | The per-session, per-corpus record of which blocks were already delivered, keyed `(corpus_id, doc_key, gen, cite, content_digest)`. Cleared by a compaction marker; **disabled when the host supplies no session id**. | [10](10-interfaces.md) §12.2 | — |
| Enabled | concept | Dispatchable by an MCP caller. An **authority** property, set separately from `listed`, with `listed ⊆ enabled` as a startup invariant. | [04](04-driver-system.md) §4.1 | — |
| **enforcement class** | concept | One of six labels — `A` architecture, `S` schema, `L` lint, `G` gate, `X` test, `R` review — naming *how* an invariant is enforced. Ordered; enforce at the highest available class. | [01](01-principles.md) §The enforcement classes | — |
| `engine_sizing()` | fn | The VRAM-proportional derivation of `(max_batched_tokens, max_num_seqs)` from a 24 GB baseline. omniweave **passes** these to a model server and never tunes it; a `vram_floor_mb` it cannot meet is a resolve-time refusal. | [08](08-runtime.md) §3.5 | — |
| `entity` | table | A durable node keyed `(scope, etype, key)`, where `key` is a **blocking** key and never an identity. | [06](06-structure-extraction.md) §3.6 | — |
| `entity_alias` | table | Every observed surface for an entity, keyed `(entity_id, name_norm, alias_kind)` over `canonical`, `variant`, `abbrev`, `expansion`, `translit`, `llm`, `user`, with trust, taint and a document count. | [06](06-structure-extraction.md) §1.1 | — |
| `entity_band` | table | **Persisted** MinHash bands — never an in-memory index, because 128-perm signatures for 1.5M entities is ~1.3 GB of RAM. Rebuilt whenever `graph.resolve_signature` changes, checked at the top of every resolve pass. | [06](06-structure-extraction.md) §1.1 | — |
| `entity_merge` | table | The **append-only** log of pairwise resolution decisions with `polarity ∈ {+1, -1}`, the stage, the guards that passed, and a reason that is required for a user decision. | [06](06-structure-extraction.md) §1.1 | — |
| `enum_val` | table | The closed enum domains, generated from the Python enums at migration time with CI parity in both directions. **Closed domains only** — the open vocabularies (`relation`, `etype`, `claim_type`) have their own tables. | [03](03-document-model.md) §13.1 | — |
| `env_digest` | concept | The sha256 over `(platform, machine, python minor, needs_binaries → identity of which(), identity of libcuda, OMNIWEAVE_PROBE_EPOCH)` — where an *identity* is `(realpath, st_size, st_mtime_ns)`, never a bare path and never a boolean — forming the environment component of a cached `ProbeVerdict`'s **four**-component key `(driver_id, driver_version, card_sha256, env_digest)`. The **only** name for it: there is no `host_fingerprint`. | [04](04-driver-system.md) §4.7 | `host_fingerprint` |
| `erasure` | table | The durable intent row that makes an erasure resumable across the store/filesystem boundary: `{doc_ord, reason, at_gen, phase, targets_json}` with `phase ∈ {store_done, complete}`. `ow doctor` **fails** while any row is not `complete`. | [14](14-security.md) §7.4 | — |
| Erasure cascade | concept | The fourteen locations a document's text or a derivative of it can survive a naive delete — `block`/`block_fts`, retained parts, assets, the `call`/`blob`/`render`/`embed`/`signal` cache layers, `vseg`, `quarantine`, route digests, retained IL bundles, exports, backups and the event stream — and the action on each. | [14](14-security.md) §7.4 | — |
| `Estimate` | type | A non-free operator's pre-flight prediction of `Spend` for one unit, at the **p95 ceiling**. The input to `admit()`; checked by `ow drivers check --estimates`. | [08](08-runtime.md) §7.3 | — |
| `etype_vocab` | table | Entity classes, corpus-tuned, with a scope, a resolution policy, a source (`builtin`/`proposed`/`user`) and a compatibility set. **Never a four-item config list.** | [06](06-structure-extraction.md) §1.6 | — |
| `eval_assertion` | table | One ground-truth claim about one document in an eval corpus. See **Assertion**. | [13](13-quality.md) §8.1 | — |
| `eval_calibration` | table | One calibration bucket per `(eval_set_id, score_kind, producer_id, slice_key, bucket)`: counts, `p_hat`, its Wilson interval, ECE and Brier where the signal is probabilistic, the label sources, and the harness version. | [16](16-roadmap.md) §3.3 — migration inventory only; **no specifying section** | — |
| `eval_corpus` | table | One `(corpus_id, version)` row: the corpus digest, its tier, its counts, and the **two independent booleans** `document_redistributable` / `assertions_redistributable` plus `publishable`. | [13](13-quality.md) §4.5 | — |
| `eval_counter` | table | One exactly-reproducible integer per `(run_id, counter, scope)`. See **Counter**. | [13](13-quality.md) §10.1 | — |
| `eval_flake` | table | Per-`(test_id, day)` runs, failures and rerun-green counts. Above 2% over 30 days a test is quarantined to `informational` with an issue (Q-G18). | [13](13-quality.md) §2.7 | — |
| `eval_metric` | table | One published number per `(run_id, metric, slice_key)` with `n`, its interval, its `method`, its `truth_kind` and a state whose zero value is `unknown`. `agreement` and `self` may never populate an accuracy column. | [13](13-quality.md) §3 | — |
| `eval_perf` | table | One performance budget outcome per `(run_id, budget_id)`: the Pacer readings either side, the work time, the ratio, peak RSS, peak WAL, and a status that includes `unstable`. | [12](12-performance.md) §7.4 | — |
| `eval_run` | table | One evaluation execution: suite, corpus identity, subject, `MeasuredOn`, `timing_basis`, `witness`, the `unpinned` and `entrant_bias` bits, the cassette mode, the harness version and the fairness record. | [13](13-quality.md) §2.5 | — |
| `eval_scoreboard` | view | The publishing view: `UNKNOWN` when the metric is unknown, `WITHHELD` when the corpus is not publishable, `UNRANKED` for a non-`ci` witness, unpinned weights, entrant bias or an agreement/self truth kind, and `RANKED` otherwise. | [13](13-quality.md) §7.2 | — |
| `eval_verdict` | table | The grain everything aggregates from: one `(run_id, assertion_id, evaluator)` row with pass/score, **an explanation**, its slice, and its cost. | [13](13-quality.md) §8.1 | — |
| `EvalStatus` | enum | `pass \| fail \| unstable \| stale \| unknown`. `UNKNOWN` is the zero value: never a pass, never silently dropped, and `ow eval release-check` refuses on it. **There is no `pass_with_warnings`** — a warning that cannot fail is the thing that rots. | [13](13-quality.md) §9.3 | `GateStatus` (for an eval outcome), `skip`, `pass_with_warnings` |
| `evaluate()` | fn | The **pure** routing decision over `(policy, evidence, hints)`. No clock, RNG, env, IO or `RunContext`. Never sees a ledger (INV-14). | [05](05-ingest-and-routing.md) §4.6 | — |
| `Event` | type | One NDJSON observability record: wall and monotonic timestamps, `run_id`, a sequence number, W3C-shaped trace ids, a `kind` from the closed `tools/events.toml`, a phase, a level, the unit/part/operator/driver, and a flat scalar `fields` map. | [15](15-observability.md) §3.2 | — |
| `Evidence` | type | The flat, namespaced, scalar-valued record of Signal values for one `(unit, part)`. **Not** a frozen dataclass and **not** a `Mapping`: a handle over a read log, with one accessor (`read()`, whose three-valued `None` means UNKNOWN and whose call is what puts a key in the read set), a planner probe (`computed()`) that may not enter it, `read_set()`/`read_set_digest()`, and one writer (`put()`) that `evaluate()` never calls. The absent `__getitem__` is what makes INV-14's purity claim a property of the signature. | [05](05-ingest-and-routing.md) §4.6 | — |
| `Expand` | type | The bounded structural traversal request: max hops (hard cap 4), a per-hop beam, a total visited cap, an **explicit** relation allowlist, a minimum trust, and a `hub_cap` that truncates a hot node's neighbourhood **and says so**. | [07](07-store-and-retrieval.md) §5.2 | — |
| `Failure` | type | `classify()`'s output: a `FailureClass`, a `source ∈ {driver, host}`, a verdict (`transient` or `permanent`), a first cooldown in ms and an optional `adapt_batch` event. | [08](08-runtime.md) §1.6 | — |
| `FailureClass` | enum | The closed driver failure taxonomy: `encrypted`, `needs_ocr`, `unsupported_format`, `corrupt_input`, `resource_limit`, `too_large`, `timeout`, `upstream_unavailable`, `rate_limited`, `auth`, `empty_result`, `driver_crashed`, `driver_bug`. | [08](08-runtime.md) §1.6 | — |
| `federate_ms` | cfg | The T4 fan-out deadline: fan-out, rank-merge and straggler tolerance for a federated query. | [07](07-store-and-retrieval.md) §4.4 | — |
| `FileAction` | type | One filesystem effect an install target reports, with `action ∈ {created, updated, unchanged, removed, not-found, kept}`. `json_deep_equal` before writing is what makes `unchanged` truthful rather than a guess. | [10](10-interfaces.md) §7.1 | — |
| `Filters` | type | What narrows a retrieval before any channel scores. **Filters narrow; channels score within the narrowed set.** `deny_restriction_bits` is set by policy, never by the caller. | [07](07-store-and-retrieval.md) §6.1 | — |
| `Finding` | type | A structured OUT diagnostic against one IL element: a **code symbol** from `codes.toml` (never the numeric — the symbol is the stored and wire form), a `Severity`, a `Provenance`, a **non-empty `fix`** (the constructor raises otherwise), an optional canonical replacement, a folded `count` and at most three examples. | [09](09-generation.md) §4.1 | — |
| `FindingSet` | type | The collected `Finding`s of one validation, with `fold()` grouping on `(code, rule, unit, canonical)`, summing `count` and keeping at most three examples, and a second re-fold on `(code, rule, canonical)` past `MAX_FOLDED_FINDINGS` that records itself in `OutReport.truncations`. | [09](09-generation.md) §1 | — |
| First-party release manifest | concept | `omniweave_core/drivers/first_party.toml`, generated package data listing the thirteen first-party distributions **other than `omniweave-core`** with their version and `dist_sha256`, plus the signed `first-party-<RELEASE>.json` release asset carrying the same content. | [11](11-repo-layout.md) §7.2 | — |
| `first_answer_seconds` | concept | Wall time on a clean 4-core, GPU-free machine, offline after install, from the start of `ow install` to the return of an `ow query` Answer carrying at least one `cite` with a page, over a folder of 100 born-digital office documents. | [00](00-vision.md) §9.1 | — |
| **Forcing edge** | concept | A dependency between phases where the reverse order costs a data migration, a re-bill, or a lie that shipped — not rework. There are exactly five, `FE1`-`FE5`; every other ordering in the schedule is a headcount question. | [16](16-roadmap.md) §1.1 | — |
| `forfeits` | column | The `Capabilities` set naming what a driver's output cannot support — `blocks`, `spatial`, `text_span`, `citation`, `round_trip`. A driver forfeiting `citation` makes serve **refuse** a citation request rather than fabricate one. | [04](04-driver-system.md) §2.2 | — |
| Fork trigger | concept | The written, testable condition in `vendor/<name>/FORK-TRIGGER.md` under which omniweave takes ownership of a vendored dependency. A priced option, not a cost paid before shipping. | [16](16-roadmap.md) §6 | — |
| `format_tokens` | column | The `[capability.parse]` card key: `list[FormatTokenPair]`, every member an inline table `{ media_type = "…", token = "…" }`, naming the media-type-to-token **pairs** a driver contributes to `unit.format`'s **computed** domain (core's 48 ∪ the union over enabled cards). Compared **`⊇`** over the **pair set** — the one safe asymmetry: an unrecognised member can only make a driver look less capable. It is a pair list and not a bare token list because the pair *is* the association `format_token_for(media_type)` reads; without it that function and `OW-D-024` have no input. Field rules in [04](04-driver-system.md) §2.2; the per-card **served token set** it feeds is defined in the same section. | [04](04-driver-system.md) §2.2 | — |
| `FormatGuess` | type | One detection candidate **as a driver may state it**, four fields and no more: `(media_type, format_token, confidence, consumed_bytes)`. Declared once in `omniweave_ports`. No `basis` and no `detail` — `basis` is the *host's* classification of how a guess was obtained and a driver has no standing to assert it, so the host wraps each returned guess in a `RankedGuess(guess, basis, detail)`. A third party's `confidence` is clamped to 0.95. | [04](04-driver-system.md) §1.3 | a six-field guess carrying `basis` and `detail` |
| `FormatTokenPair` | type | One `format_tokens` member: `{ media_type: str, token: str }` — the **only** place a third party's media-type-to-token association is written, and therefore the only input to `format_token_for()` ([05](05-ingest-and-routing.md) §2.2). Coined in [04](04-driver-system.md) §2.2. | [04](04-driver-system.md) §2.2 | — |
| Frame | concept | A **block-count-bounded** run of Blocks in `(page, ord)` order, target 8,192 blocks, indexed in `frames.json`. The unit of streaming and of archive seek. **Deliberately not a page range**, so a page with 400,000 blocks is harmless. | [03](03-document-model.md) §7.1 | — |
| `frame_queue_max` | const | 256. The host's bounded read queue per worker. A full queue means the host stops reading, so a frame flood becomes pipe backpressure and then `wall_ms_hard`, never host memory. | [04](04-driver-system.md) §6.5 | — |
| **Freeze point** | concept | The named set of types, Port majors, grammars, digests and enum vocabularies that a Phase's **freeze week** makes immovable. | [16](16-roadmap.md) §3 | — |
| Front door | concept | The four listed tools `ow_query`, `ow_open`, `ow_corpora`, `ow_add` and the 1,900-token budget they live inside. | [10](10-interfaces.md) §3.1 | — |
| Front-load | concept | The `UserPromptSubmit` injection, tiered by **verified** confidence (high / medium / silent), capped at 8,000 chars, instrumented with counter **names** only and never prompt text. | [10](10-interfaces.md) §8.4 | — |
| `fuse()` | fn | Weighted RRF over the channels that ran, at one key: `block_id`, with **1-based** ranks. | [07](07-store-and-retrieval.md) §5.3 | — |
| `FusedHit` | type | One fused result: `block_id`, `score`, and the **per-channel contributions and ranks** — because a fusion returning only a score is one you cannot tune. Totally ordered on `(-score, (doc_ord, page, ord), block_id)` (D655). | [07](07-store-and-retrieval.md) §5.3 | — |
| `FusionSpec` | type | The fusion parameters of one plan: `k` (default `RRF_K = 60`), the weight map, and the `low_confidence` threshold (0.35). | [07](07-store-and-retrieval.md) §16 | — |
| `gate_docs.py` | file | The implementation of G27 clause (d): the five checks of §8.6 — the parser found what it should have found, symbols import, registers contain what a document names (including the spelled-out distribution count against `packages/*`), relative links and `§` cross-references resolve, and `docs_symbols_checked` ratchets. | [11](11-repo-layout.md) §1.7 | — |
| `gates.risk_register` | const | The `[[job_assertion]]` name in `tools/gates.toml` for the risk-register check: the five rules of [17](17-risks.md) section 1, in the `gates` job, budgeted at 2 s. The eighth of nine job assertions at release 1. | [17](17-risks.md) §1 | — |
| `GateStatus` | enum | The ten-value OUT **release** gate. Exactly one value, `passed`, permits a release; `passed-with-warnings` is a report status and never a gate status; `not-provided` is not `failed`. Every non-`passed` status prints the exact command that clears it. | [09](09-generation.md) §4.5 | — |
| `gen` | column | The per-document **parse** generation, a monotonic integer. **Bare `gen` means this and only this, everywhere.** The previous generation is retained until the next successful parse, so yesterday's citation still resolves and reports `superseded_by`. | [03](03-document-model.md) §1.1 | — |
| **Gen-fencing** | concept | The `end_run` check that re-resolves every cite and compares the Segment's `content_digest` against the one handed out at `begin_run`, so a long billed extraction racing a re-parse quarantines the affected items as `OW_GRAPH_STALE_SEGMENT` rather than writing spans into text that has moved. | [06](06-structure-extraction.md) §10.3 | — |
| `generated_share` | concept | The fraction of **`Response.hits`** characters whose producing Block has `Method.ROUNDTRIP` — the share of an answer that came from omniweave's own compiled output rather than from a source document. The denominator is the set `PackSpec` bounded, **never** a rendered Answer's, whose character set moves with `Answer.render(max_chars=…)`, the packing cliff and the emission ledger's withholding; the renderer reads the number and does not recompute it. `chars(h)` is `length(block.text)` at hydration, not `len(Hit.text)`. | [07](07-store-and-retrieval.md) §6.7 | a rendered Answer's evidence characters as the denominator |
| `geometry.ruled_regions` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `GlobalRef` | type | `(corpus_id: str, block_id: int)` — the **only** reference type that may cross a store boundary. There are no cross-shard foreign keys. | [03](03-document-model.md) §6.1 | — |
| `gpu_group` | cfg | `[services.<name>] gpu_group`. Names the VRAM budget a Service draws from; `cuda:<n>` pins a device and sets `CUDA_VISIBLE_DEVICES` for the spawned child. | [08](08-runtime.md) §3.2 | — |
| Grant | concept | A **site-layer** credential authorising egress or a licence-gated driver for a scoped corpus, carrying a required (deliberately unvalidated) `dpa_ref`, an expiry and an approver. Printed in the run manifest of every document it covers. | [05](05-ingest-and-routing.md) §6.4 | — |
| `graph_history` | table | Retirement, not deletion, for every L3 kind: the retired row, its generation, an optional successor, a closed reason and the payload. | [06](06-structure-extraction.md) §1.1 | — |
| `graph_observation` | table | The per-`(run, pass, lane)` operability rollup: segments in and cached, blocks in, items out, covered and cover-empty counts, quarantines, grounded fraction, spend, and **five distinct cache-miss shapes** — corrupt, partial, empty, mismatch, vintage. | [06](06-structure-extraction.md) §4.3 | — |
| `GraphError` | type | The `OW-G-*` member: a cluster above `MAX_CLUSTER_EDGES`, an ungrounded item that must raise rather than quarantine, a trust clamp that cannot be applied. | [02](02-architecture.md) §7.2 | — |
| `GraphSink` | proto | The **only** writer of L3 tables, host-side like `DocSink`. Takes `allowed_cites`, clamps trust, grounds quotes, mints every id, stamps every provenance field, and commits one transaction per Run. | [06](06-structure-extraction.md) §1.3 | — |
| `GraphView` | type | The read-only handle over L3 returned by `Corpus.graph()`: `entity(cite)`, `neighbours(cite, relations, max_hops, min_trust)`, `evidence(edge)`, `community(cite)`, `claim(cite)`. | [18](18-api-sketch.md) §1.2 | — |
| `Grid` | type | The exactly-once table cover, built only by `build_grid`. Slots are `Origin` (a cell Block with its spans) or `Covered` (pointing at its origin). Answers `up/down/left/right/top_heading/left_heading` in O(1). | [03](03-document-model.md) §10.2 | — |
| `grid_slot` | table | The **derived** cover map, materialised only when a table has merges, capped at `MAX_GRID_SLOTS`. A merge-free 4M-cell sheet stores **zero** rows and answers `slot(r,c)` by arithmetic. | [03](03-document-model.md) §10.1 | — |
| `ground()` | fn | The **one** grounding function: `(block_text, quote) -> (ts_a, ts_b, occurrences) \| None`, in `block_text` coordinates, recovered through `normalize_k`'s back-map. It grounds the **first** occurrence and returns the count, which `.find()` alone cannot. Both endpoints map through a character **inside** the match (`back[i0]` and `back[end - 1] + 1`), and the round trip `normalize_k(block_text[ts_a:ts_b])[0] == normalize_k(quote)[0]` is asserted **inside** the function, so a boundary falling inside a length-expanding character yields `None` rather than a truncated or widened span. `GraphSink.mention` and `FieldGrounding` both call it, and neither reimplements it. | [06](06-structure-extraction.md) §1.7 | — |
| **`Grounded`** | type | `tuple[Cite, TextSpan] \| tuple[Cite, str]` — the union every Draft uses to say where an item was observed. | [06](06-structure-extraction.md) §1.7 | — |
| Grounding | concept | Locating a model-claimed verbatim `quote` inside the Block it cited, under `normalize_k`, to obtain the span. | [06](06-structure-extraction.md) §9.2 | — |
| Group commit | concept | Batching, at `store_group_commit_ms`, **only** those work-row transitions that write zero derived rows. The single stated exception to one-transaction-per-unit, safe because a crash means re-checking the cache and reaching the same outcome. | [07](07-store-and-retrieval.md) §11.1 | — |
| Guard | concept | (D10 sense) A **delta against release N−1**, owned by the PR author. Its breach means this change made it worse. Fires only at paired `p < 0.01` **and** effect ≥ MDE. Contrast **Budget**. | [13](13-quality.md) §2.8 | — |
| `head_fts` | table | A second FTS5 external-content table over `block.label` — NULL on most rows, therefore tiny. The source of the lexical scorer's heading-spine term, and how "D5 owns the BM25 weights" is discharged without touching `block_fts`. | [07](07-store-and-retrieval.md) §3.3 | — |
| Heading-spine propagation | concept | The lexical scorer's second term: a block earns a decayed share of the best BM25 score achieved by any heading on its spine. **Better than a title column**, because it lifts the paragraphs *under* a matching heading rather than only the heading. | [06](06-structure-extraction.md) §1.3 | — |
| `heading_path` | column | The JSON array of ancestor heading texts on a Segment. **A digest input**, because the prompt contains it. Computed from `block_sec`, so there is one spine computation. | [06](06-structure-extraction.md) §1.3 | `head_path` |
| `Hit` | type | One ranked retrieval result: `block_id`, `cite`, `addr`, `score`, **`text`**, `span`, per-Channel contributions and ranks, the identity grade **actually measured**, `segment_id`, `trust`, `quote`, `byte_exact` and `restriction_bits`. Fourteen fields. | [07](07-store-and-retrieval.md) §7.1 | — |
| `holdout_gap` | column | The signed difference between a metric's value on the 85% scoring split and on the 15% holdout, computed from the same `blake2b(doc_key‖"ow-split-1") % 100` split the calibration chain uses, and printed on every scoreboard row. | [13](13-quality.md) §11.1 | — |
| `host_fingerprint` | concept | **Retired alias of `env_digest`** (ADR-7 D7.2.1), kept as a row so the old spelling resolves and so nothing coins it afresh. It named the environment half of the persisted probe-verdict key under `$OMNIWEAVE_HOME/probe/`; the digest covers an environment, not a host, and the key is four components — `(driver_id, driver_version, card_sha256, env_digest)` — not two or three. A second name for one key is the collision the charter's §5 X14 forbids. Never written in new text; the lock's §3 carries the rejection row. | [04](04-driver-system.md) §4.7 | `host_fingerprint` itself, in favour of `env_digest` |
| `HostFacts` | type | The machine measured once at preflight — `cpus`, `ram_bytes`, `free_disk_bytes(roots.cache)`, `gpus` as `(name, vram_bytes)` in device order, `is_container` — and recorded in the run manifest, so a performance number is attributable to a machine. | [08](08-runtime.md) §2.1 | — |
| Human-only Action | concept | An Action whose `mcp_name` is `None`, **structurally unreachable** from any agent surface: `uninstall`, `corpus.rm`, `route.promote`, `skills.remove`, `targets.remove`. | [10](10-interfaces.md) §1.2 | — |
| IL | concept | For one Target, the triple **(Carrier, ConstructTable, RulePack)** — a closed, declared subset of an existing text format. Identified `<name>/<major>`: `owsvg/1`, `owdeck/1`, `owflow/1`, `owmotion/1`. | [09](09-generation.md) §3.1 | — |
| IL bundle | concept | The set of IL text files plus `il.toml` for one artefact generation. Content-addressed by `il_digest` and **retained in CAS**, which is what makes editing an omniweave-built artefact a passthrough rather than a reconstruction. | [09](09-generation.md) §3.2 | — |
| `il.toml` | file | *(coined here)* The IL bundle's own roster, schema `omniweave.out-il/1`: the IL id, the `constructs_digest` the bundle was authored against, and one `[[unit]]` row per unit carrying `id`, `ord`, `file` and `anchor`. | [09](09-generation.md) §3.2 | — |
| `il_digest` | concept | The source fingerprint binding a report to exact IL bytes: basename-sorted, `name\0sha\n` framed, and **an unreadable file contributes the literal `unreadable` plus an error row** rather than silently dropping out. | [09](09-generation.md) §11.3 | — |
| `il_digest_rt` | concept | `il_digest` over canonicalized subtrees with every payload key of a non-`exact` construct elided. **The exclusion set is derived from the ConstructTable, never hand-tuned.** | [09](09-generation.md) §11.3 | — |
| `ILBundle` | type | The loaded IL of one job: `il.toml` plus the ordered IL file set under `job_dir/il/`, as `ILFile` rows with their per-file sha256s and byte lengths, `il_digest`, `il_digest_rt`, and the stamped `el` index. It holds digests and paths and **never the bytes**: `text()` and `data()` re-read from `root` on demand, which is what lets a 2000 × 4 MiB bundle digest in constant memory. | [09](09-generation.md) §3.7 | — |
| `ILFile` | type | One file under `job_dir/il/`, `il.toml` included, as `ILBundle.files` carries it: the **basename** and never a path, a 64-hex `sha256` **or** the literal `"unreadable"`, a `byte_len` that is 0 iff unreadable, and an `error` that is non-`None` iff unreadable. An unreadable file contributes that string to `il_digest` rather than dropping out of it. | [09](09-generation.md) §3.7 | — |
| **independent enforcer** | concept | Two enforcers are independent when one edit cannot disable both. Two semgrep rules in one config are one enforcer; a generated trigger and the mapping it came from are two only while a parity gate compares them. | [01](01-principles.md) §The enforcement classes | — |
| `index_state` | table | The store's own scalar state: corpus id, shard ordinal, schema, scorer version, generation, FTS state, the **bulk-window marker**, the WAL baseline, the last full index, the default space. | [07](07-store-and-retrieval.md) §3.8 | — |
| `IndexCaps` | type | What `plan()` may know about a store, read once at open: schema and scorer version, which Channels can run at all, FTS availability and state, the vector space, backend, ceiling and pushdown bit, the scalar counts from `stat` with their age, the shard ordinal, and a `caps_digest` that memoises the planner. | [07](07-store-and-retrieval.md) §16 | — |
| `ingest_scope` | table | What a scan discovered versus indexed versus skipped, and why. **An absent row means "coverage unknown", never "nothing was excluded".** | [07](07-store-and-retrieval.md) §3.8 | — |
| `Injector` | concept | One paired-damage transform, **one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`**, that damages a pristine corpus in exactly one named way and asserts the answer degrades to a **named cause** rather than a confident zero. | [13](13-quality.md) §8.6 | — |
| `INLINE_MAX` | const | 262,144 bytes. A driver-protocol **body** larger than this travels as a content-addressed blob reference instead. | [03](03-document-model.md) §13 | — |
| `inproc` | member | The Isolation mode that runs a driver in the host process. Reachable **only** for a first-party or vendored driver that is free, GPU-less, network-less, fuzz-green **and** named in `[drivers] inproc`. No config key widens the first four. | [04](04-driver-system.md) §6.7 | — |
| `Insertion` | type | What `CarrierDoc.place_marker()` returns: the byte offset and 1-based line the marker line now occupies, the `el` it was written against, and `hoisted` plus `container_el` when the anchor was self-closing and the marker had to sit on an ancestor. | [09](09-generation.md) §3.1 | — |
| Install profile | concept | One of the six named `pip`/`uv` invocations in §2.3 — laptop-minimum, laptop-working, CPU server, GPU server, browser (which installs nothing) and CI — each with its distribution set, its `tools/weights.toml` ceiling sum and its cold-start budget. | [11](11-repo-layout.md) §2.3 | — |
| Install receipt | concept | `$OMNIWEAVE_HOME/install-receipt.json`, recording every path, mode, key and **post-write sha256** `ow install` produced. | [10](10-interfaces.md) §7.3 | — |
| `INV-21` … `INV-25` | invariant | The five framework-wide invariants this document adds: one name/one type/one home; a ceiling is never a target; one implementation per semantic decision; byte-reproducibility of every committed and shipped artefact; nothing is disposed of silently. | [01](01-principles.md) §1 | — |
| **Invalidation matrix** | concept | The table (§10.2) mapping each shape of change to the exact set of Segments, rows, anchors, resolution closures and reports it invalidates. The specification the incremental implementation is read against. | [06](06-structure-extraction.md) §10.2 | — |
| Isolation | enum | `inproc \| subproc \| wasm`. Declared as a *need* by the card; **decided by the host, which may only tighten**. An isolation property that was not obtained is **recorded, never claimed**. | [04](04-driver-system.md) §6 | — |
| Job assertion | concept | An unnumbered `[[job_assertion]]` row in `tools/gates.toml`: a blocking CI check that belongs to one job rather than to the G-series, because the G-series' cardinality is quoted in a core document and is therefore append-only-by-ADR. | [11](11-repo-layout.md) §3.3 | — |
| Job directory | concept | The filesystem envelope of one Toolchain invocation — `job.json`, `brief.md`, `il/`, `assets/`, `validation/`, `out/` — and the **only** channel by which bulk data crosses the Python/Toolchain boundary. Blobs never travel on stdio. | [09](09-generation.md) §2 | — |
| Kill criterion | concept | An observation — instrument, threshold, and what specifically stops — under which a component or the project is stopped rather than repaired. Thirteen at release 1 (`K-1`-`K-13`), three of them project-level. | [17](17-risks.md) §5 | — |
| `Kind` | enum | The closed Block vocabulary: 34 members plus `UNKNOWN`. Wire values are the lower-case member names; the store holds integers via `enum_val`. | [03](03-document-model.md) §8.4 | — |
| `kind_map` | file | A Target's map from `Kind` to its own primitives and back. The comparator for round-trip law R2. | [09](09-generation.md) §1 | — |
| Lane | concept | **What** is being asked for at a rung, from an open registry: `text`, `table`, `math`, `fields`, `caption` (parse lanes) and `anchor`, `xref`, `entity`, `claim`, `community`, `summary` (graph lanes). One resident model can serve several lanes. | [05](05-ingest-and-routing.md) §3.1 | `tier 0`…`tier 3`, `tier S` |
| `Layer` | enum | (L2, and **only** L2) A Block's role in the reading order: `body \| furniture \| note \| annotation \| hidden`. **A column, not a second tree**, so furniture and notes leave the body order and are never deleted. | [03](03-document-model.md) §5 | — |
| `layers.toml` | file | The import DAG. An arrow means "may import". Gate G4. | [11](11-repo-layout.md) §1.7 | — |
| Leading indicator | concept | The named instrument and threshold at which a risk is observably materialising, distinct from the damage itself. | [17](17-risks.md) §1 | — |
| **`LEXICON_MAX_DOC_SHARE`** | const | `0.5`. An alias occurring in more than this share of a corpus's documents is a template word rather than a name and is excluded from the lexicon. | [06](06-structure-extraction.md) §3.7 | — |
| **`LEXICON_MIN_LEN`** | const | `4`. The minimum `LENGTH(name_norm)` for an alias to enter the `op.lexicon` automaton. | [06](06-structure-extraction.md) §3.7 | — |
| `LicenceFacts` | type | The licence **facts** a `DriverCard` carries twice, as `licence_code` and as `licence_weights \| None`: the SPDX id, the licence sha256, and the flags `compute_tier()` reads — `requires_credential`, `competitor_bar`, `output_share_alike`, `territory_excluded`, `field_of_use_excluded`, `revenue_gate_usd`, `mau_gate`, `remote_kill_switch`, `redistribution`. Facts only: `LicenceTier` is computed by core, so an author cannot mislabel. | [04](04-driver-system.md) §7.1 | — |
| `LicencePosture` | type | The frozen result of `ow drivers check --posture` and `omniweave.licence_posture()`: per-driver tiers and acks, the aggregated `restriction_bits` of the enabled set, the not-enabled-but-present set, and a verdict. | [04](04-driver-system.md) §7.4 | — |
| `LicenceTier` | enum | `open \| restricted \| commercial \| forbidden`. **Computed** by core from the card's licence facts; never typed by an author. `ow drivers check` exits non-zero on a mismatch. | [04](04-driver-system.md) §7.1 | — |
| `Limits` | type | The resolved `MAX_*` ceilings for this run — `effective = min(tenant_cap, declared, HOST_MAX)` — carried on `RunContext` so no site reads a constant directly. | [08](08-runtime.md) §1.3 | — |
| Listed | concept | Present in the MCP `tools/list` payload for the active profile. A **context-cost** property, bounded by the schema baseline. Separate from `enabled`. | [10](10-interfaces.md) §2.1 | — |
| `locate()` | fn | The answer to "where on the page" for a mention, edge, claim or entity. Returns a `Locus` per witness. | [06](06-structure-extraction.md) §1.4 | — |
| `Locator` | type | The `acquire/1` input: a `scheme` that must be a `[capability.acquire] schemes` member, a `target`, an optional `cursor` (opaque iff `[acquire] cursor_opaque`) and `since_ns` (`None` means full enumeration). Distinct from `SourceLocator`, which is the host-side input to acquisition. | [04](04-driver-system.md) §1.3 | — |
| `Locus` | type | The resolved location: a cite, page and `addr`, a `TextSpan`, a `quad` that **may be `None`**, a `precision ∈ {char, line, block, page, none}`, the `OriginSpan`, and a `reason` that is non-`None` **iff** `quad is None`. | [06](06-structure-extraction.md) §1.1 | — |
| `lower()` | fn | The compile driver's IL-bundle-to-artefact-bytes method, writing into `io.tmpdir`. **Deliberately not named `compile`**, which is the framework's gated pipeline verb. | [09](09-generation.md) §2 | — |
| `M-INV-1` … `M-INV-5` | invariant | The document-model-local invariant prefix, subordinate to the framework `INV-*` series exactly as `DR`, `RT`, `ST`, `I`, `GR`, `OUT`, `SV` and `Q-G` are. | [03](03-document-model.md) §16.5 | — |
| `manual_required` | concept | Simultaneously a mandatory IL construct in every ConstructTable, a `UnitOutcome`, **and** a `GateStatus`. Not a `Disposition`, because a disposition says what the compiler does with a construct and `manual` says what a human must do about a region. | [09](09-generation.md) §9 | — |
| `ManualEvidence` | type | The OUT observation artefact for a `manual_required` region: **what is visibly present and explicitly no realization choices, prompts, filenames or IL bindings**. Named `ManualEvidence`, not `Evidence`, which is the routing record. | [09](09-generation.md) §1 | `Evidence` (for the OUT manual-region artefact) |
| `ManualReason` | enum | The closed vocabulary: `unverifiable_wording`, `unverifiable_identity`, `unverifiable_data`, `insufficient_source`, `unrepresentable`, `licence_barred`, `measurement_failed`. | [09](09-generation.md) §9 | — |
| Marginal weight | concept | A `tools/weights.toml` row: a distribution's own installed files plus the third-party closure it introduces, **excluding first-party siblings**, each of which is counted in its own row. | [11](11-repo-layout.md) §2 | — |
| `mark` | table | A sparse inline annotation over a character range of a Block's `text` — bold, italic, code, link, math, anchor, note_ref, dehyphenated, raw_style, lang, redaction. | [03](03-document-model.md) §2.7 | — |
| `MARK_HYDRATE_WINDOW` | const | 512. How many `block_id`s a block cursor buffers before issuing one mark query, so a scan is `O(blocks/512)` statements and not `O(blocks)`. | [03](03-document-model.md) §2.7 | — |
| Marker | concept | An `OWC1:`-prefixed base64url comment in the IL carrying one feedback item. | [09](09-generation.md) §4.4 | — |
| `math.font_hit` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `math.part_frac` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `MAX_ASSET_TOTAL_BYTES` | const | `536_870_912` — the whole document's retained asset bytes, distinct from the per-asset `MAX_ASSET_BYTES`. Derived, not copied: anydoc's 128 MiB is smaller than the charter's 256 MiB per-asset ceiling, so a single legal asset would trip the total. | [14](14-security.md) §2.1 | — |
| `MAX_BLOCK_DEPTH` | const | 64. The containment spine's depth, matching `os_path`'s ceiling and bounding `addr`. | [03](03-document-model.md) §14 | — |
| `MAX_BLOCK_TEXT_BYTES` | const | 1,048,576. One block's `text`; a longer run is split into `continues`-joined siblings, never truncated. | [03](03-document-model.md) §14 | — |
| `MAX_BLOCKS_PER_PAGE` | const | 4,194,304. One page is one transaction, so this is the commit-size ceiling and the answer to charter deferred item F29. Set so the charter's 4M-cell sheet is admissible. | [03](03-document-model.md) §14 | — |
| `MAX_CARD_BYTES` | const | 65,536. The card-size ceiling, with six sibling shape caps (nesting depth 6, 64 formats, 16 binaries, 256 pins, 64 benchmark rows, 32 config properties), each `CARD_INVALID` naming the cap (E6). | [04](04-driver-system.md) §4.5 | — |
| `MAX_CONTAINER_DEPTH` | const | 3. A zip in a zip in a zip; the fourth refuses. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit | — |
| `MAX_CONTAINER_TOTAL_BYTES` | const | 512 MiB decompressed from one container tree, and the same ceiling on one office package's cumulative part reads; the accumulator is per-scope, the constant is one. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit, [14](14-security.md) §2.1, §2.2 | `MAX_TOTAL_BYTES` |
| `MAX_CONTAINER_UNITS` | const | 10,000 child units one container may mint. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit | — |
| `MAX_DRIFT_BAND` | const | `0.02` in `omniweave_core.limits`: the ceiling on the kit-measured `drift_band` a `seeded` `ReplayClass` may declare. Above it the card must declare `unpinnable`. | [13](13-quality.md) §13.4 | — |
| `MAX_EXPANSION_TEXT_BYTES` | const | One of the five members of anydoc's twelve-constant attack taxonomy that charter §6.10 does not name and [05](05-ingest-and-routing.md) has not already adopted, added to `omniweave_core.limits`. Values and derivations in §2.1. | [14](14-security.md) §2.1 | — |
| `MAX_IDENTITY_BYTES` | const | 64 KiB. One container identity part, read in the host, with no DTD and no entity expansion. | [05](05-ingest-and-routing.md) §2.5 | — |
| `MAX_IMAGE_PIXELS` | const | `89_478_485` — decoded pixels in one image, checked from the container header **before** any decoder runs. Pillow's own default, adopted explicitly because Pillow's default only warns at the threshold and raises at twice it. | [14](14-security.md) §2.1 | — |
| **`MAX_LEXICON_ENTRIES`** | const | `200_000`. The ceiling on automaton entries, set by memory: ~3.6M goto nodes and ~600 MB of CPython dicts at an 18-character mean. A breach is `Diag(OW_RESOURCE_LIMIT)`, and selection above it is `(doc_count DESC, LENGTH(name_norm) DESC, name_norm)`. | [06](06-structure-extraction.md) §3.7 | — |
| `MAX_MARKS_PER_BLOCK` | const | 4,096. | [03](03-document-model.md) §14 | — |
| `MAX_PAYLOAD_BYTES` | const | 16,384 each, over `canonical(payload)` and `canonical(x)`. | [03](03-document-model.md) §14 | — |
| `MAX_QUOTE_BY_OS_KIND` | const | The host-applied ceiling on `Quote` by `OriginSpan` variant, symmetric with `MAX_TRUST_BY_METHOD` and applied at the same site. | [03](03-document-model.md) §2.5 | — |
| `MAX_RECORD_DEPTH` | const | One of the five members of anydoc's twelve-constant attack taxonomy that charter §6.10 does not name and [05](05-ingest-and-routing.md) has not already adopted, added to `omniweave_core.limits`. Values and derivations in §2.1. | [14](14-security.md) §2.1 | — |
| `MAX_RECORDS` | const | One of the five members of anydoc's twelve-constant attack taxonomy that charter §6.10 does not name and [05](05-ingest-and-routing.md) has not already adopted, added to `omniweave_core.limits`. Values and derivations in §2.1. | [14](14-security.md) §2.1 | — |
| `MAX_REDUCTION_BYTES` | const | `262_144` in `omniweave_core.limits`: `Q-G2`'s per-Reduction-file cap, named because it is the **binding** constraint on `outline` and `pages` and the 500-page suppression rule is only a pre-check. | [13](13-quality.md) §13.4 | — |
| `MAX_RENDER_PIXELS` | const | `40_000_000` — pixels in one page raster. Render DPI is **derived** as `min(policy_dpi, floor(sqrt(MAX_RENDER_PIXELS / page_area_in2)))`, and the clamp is recorded as `cause = "render_dpi_clamped"` rather than refusing the page. | [14](14-security.md) §2.1 | — |
| `MAX_RESIDENT_CELLS` | const | 65,536. The out-of-order-cell buffer in `build_grid`. | [03](03-document-model.md) §14 | — |
| `MAX_SPAN_BUFFER_EVENTS` | const | `= 64`. The per-open-`unit` tail-sampling buffer ceiling in a `TraceSink`. An overflow flushes the unit **unsampled** rather than truncating its subtree, so a sampling decision never produces an orphan span. | [15](15-observability.md) §2.4 | — |
| `MAX_VIEW_BYTES` | const | 67,108,864. One `serialize()` result, checked as the serializer appends. | [03](03-document-model.md) §14 | — |
| `MAX_X_BYTES` | const | 16,384 each, over `canonical(payload)` and `canonical(x)`. | [03](03-document-model.md) §14 | — |
| `MAX_XML_DEPTH` | const | One of the five members of anydoc's twelve-constant attack taxonomy that charter §6.10 does not name and [05](05-ingest-and-routing.md) has not already adopted, added to `omniweave_core.limits`. Values and derivations in §2.1. | [14](14-security.md) §2.1 | — |
| `MAX_XML_NODES` | const | One of the five members of anydoc's twelve-constant attack taxonomy that charter §6.10 does not name and [05](05-ingest-and-routing.md) has not already adopted, added to `omniweave_core.limits`. Values and derivations in §2.1. | [14](14-security.md) §2.1 | — |
| `MeasuredOn` | type | The **frozen, defaultless** reproduction tuple required on every published number: weights, an **exact** `weights_revision`, runtime, runtime_version, sampling, prompt_version, hardware, corpus, `corpus_digest`, `harness_version`. | [13](13-quality.md) §1 | — |
| `member_digest` | column | `ow128` over a community's sorted canonical member ids. **A report is stale iff its `member_digest` differs from its community's** — the only trigger for re-reporting. | [06](06-structure-extraction.md) §1.3 | — |
| `mention` | table | A `TextSpan` inside one Block that names an Entity, with its own run, trust, score and taint. **The only table in the framework referencing both a `block_id` and an `entity_id`** (GR15). Deliberately not a `mark`. | [06](06-structure-extraction.md) §1.3 | — |
| **`merge_hops`** | concept | The depth of an entity in the union-find forest built by processing its component's live `polarity = +1` `entity_merge` rows in the total order `(-COALESCE(score, 100.0), min(key), max(key))`, **before** path compression. | [06](06-structure-extraction.md) §5.1 | — |
| `Method` | enum | The branch that actually ran: `native`, `text_layer`, `native_xml`, `ocr_page`, `ocr_block`, `vlm_page`, `llm`, `heuristic`, `roundtrip`, `user`. One method per pass; two methods is two passes. | [03](03-document-model.md) §2.1 | — |
| `migration` | table | Every migration declares its **cost class** (`ddl`/`backfill`/`rebuild`), whether it is **resumable**, and **what an un-backfilled row means** — required prose that `ow doctor` prints verbatim. | [11](11-repo-layout.md) §5.1 | — |
| **Milestone** | concept | A named point the program is measured against: `M0`, `v0.1`, `v1.0`. A Milestone's acceptance set lives in [00-vision.md](00-vision.md) §9; a Phase's exit criteria live in this document. Two names for two things. | [16](16-roadmap.md) §2 | — |
| `MIN_SQLITE` | const | `(3, 42, 0)`, in `omniweave_core.limits`. STRICT tables need 3.37, `unixepoch()` needs 3.38 and `unixepoch('subsec')` needs 3.42, and shipped DDL and shipped SQL use all three. | [07](07-store-and-retrieval.md) §2.1 | — |
| Minting shard | concept | The 16-bit prefix of a `block_id`, assigned once when the Block is created and **never reused or rewritten**. Distinct from the **placement shard**, which is `jump_consistent_hash(doc_key)` and may change on a reshard. | [07](07-store-and-retrieval.md) §12.1 | — |
| `model_key` | column | `sha256_canonical` of the nine embedding-identity fields, truncated to 16 bytes. The name a vector sidecar and a query agree on. | [07](07-store-and-retrieval.md) §1.1 | — |
| `ModelError` | type | The `OW-M-*` member: an L2 violation — an unknown non-`unknown` `Kind` on read, a retired `cite` with no `superseded_by`, a torn generation. | [02](02-architecture.md) §7.2 | — |
| `Modifiers` | type | The second value of one `evaluate()` call, and the half that is **not** first-match-wins: every matching modifier rule contributes and each key combines under the monoid §4.2's table states — `max_cost_class` (a clamp that can only lower), `admit_lanes` and `deny_lanes` (union, with denial applied last), `render` (the more expensive profile wins), `skip_rungs`, `flag_blocks`, `not_eligible`, and the contributing `rule_ids` in file order. A pure function of `(policy_digest, evidence)`, so `ow route explain` recomputes it from the stored read set and it needs neither a `RouteDecision` field nor a `route_decision` column. | [05](05-ingest-and-routing.md) §4.6 | — |
| `ms_pow2` | const | The one shared histogram bucket ladder for millisecond-valued metrics: seventeen explicit base-2 boundaries from 1 to 65536 plus `+Inf`, generated into a `CASE` ladder in `omniweave_core/store/sql/hist.sql` and into OTLP `explicitBounds`. | [15](15-observability.md) §4.1 | — |
| `MTIME_GRANULARITY_NS` | const | 2 × 10⁹. The window inside which `stat_fresh` cannot prove a file unchanged. Named in the charter's `unit` DDL comment; it needs a §2 row. | [05](05-ingest-and-routing.md) §1.4 | — |
| Narrow Action | concept | A defined, typed, dispatchable Action that is **not listed** under the active profile. Reachable on the CLI, in the SDK, and by naming it in config or env. Never *refused* for being unlisted. `Narrow tool` is a rejected synonym: the noun is `Action`. | [10](10-interfaces.md) §3.8 | `Narrow tool` |
| `Narrowing` | type | The **tagged** result of applying `Filters`: `all`, `set` (a TEMP table plus its exact row count), or `empty`. "No restriction" and "restrict to nothing" are different values of different shape, so `if narrowing:` is unrepresentable. | [07](07-store-and-retrieval.md) §6.1 | — |
| `NetworkPolicy` | type | The frozen egress grant an `ingest_uri` call must pass explicitly — ports, host-suffix denials, a byte cap, a redirect cap, two timeouts, and `allow_private_destinations`. | [14](14-security.md) §4.1 | — |
| `next_cite_n` | column | The per-`doc_key` monotonic counter on `doc` from which a Block's `cite` number is minted. Never reset, never reused, and not a write-order position — which is what makes a shipped citation survive a re-parse. | [03](03-document-model.md) §2.5 | — |
| `nfc()` | fn | `unicodedata.normalize("NFC", s) -> str`, in `omniweave_core/ident.py` beside `normalize_key`, `normalize_k` and `fold_common`. No casefold, no `Cf` strip, no dash fold, no whitespace collapse and **no back-map**: canonical composition is the only length change, and INV-10's branches compare whole strings rather than locate an offset inside one. It is what INV-10's `bytes` branch compares — `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text` (ADR-5 decision 1) — so `VERBATIM` is proved under `nfc` and only `NORMALIZED` still claims under `normalize_k`. Because NFKC is total and canonically composing, `nfc(d) == t` implies `normalize_k(d)[0] == normalize_k(t)[0]`, which is P-23. | [02](02-architecture.md) §2 | `normalize_k` for INV-10's `bytes` branch |
| **`normalizations`** | concept | *(coined here)* The `Receipt` ledger of every rewrite the compiler performed, each a structured record, only reachable behind `ow out compile --accept-normalization`, and each accompanied by one `Degradation(kind="compile_normalized")` on the artefact row. | [09](09-generation.md) §template | — |
| `normalize_eval()` | fn | The **evaluator's** comparison normaliser, in `omniweave_conform.normalize`: `strip_md` (olmOCR-Bench's `<br>`-to-space and paired-emphasis stripping) composed with `omniweave_core.ident.fold_common` at `casefold=False, quotes=True`. | [13](13-quality.md) §8.2 | — |
| `normalize_k()` | fn | The **grounding** normaliser, whose signature is `normalize_k(s: str) -> tuple[str, tuple[int, ...]]`: the normalised string **and a back-map**, where `back[i]` is the index in `s` of the character that produced `out[i]`. Every one of its operations changes length, so a shift map **is** needed and `back` is it — an offset found in normalised space is only carried back into `block.text` space through `back`, and `ground()` is the only caller entitled to do the carrying. This row names the function; its operations, their order and its return type are specified once, in the linked section, and are restated nowhere. | [06](06-structure-extraction.md) §1.7 | a `str`-returning `normalize_k`; "no shift map is needed" |
| `normalize_key()` | fn | The **blocking-key** normaliser: a bounded NFKC/casefold **fixpoint** loop (casefold and NFKC do not commute and neither is a fixpoint of the other), then a `re.UNICODE` `\w`-closed filter (without `re.UNICODE`, every CJK/Cyrillic/Arabic corpus collapses to one node per document). Returns a `str`, not a pair — it grounds nothing. | [02](02-architecture.md) §2 | — |
| `nsig` | concept | The content anchor of one IL element: the first 8 hex of the canonicalized-subtree digest after **six** declared normalizations, and **a subtree referencing a changed definition id is changed** even when its own bytes are identical. | [09](09-generation.md) §1 | — |
| `omniweave` | dist / pkg / cli | The CLI distribution and package: the surface registry, the CLI, the SDK, the router, the Supervisor, the planner, install and hooks. Also the console script name (`ow` is the same script). | [11](11-repo-layout.md) §1.2 | — |
| `omniweave-conform` | dist | The conformance kit, the driver **testkit**, the eval harness, the reducers, the Cassette codec, the calibrator, the scoreboard generator, and the reference target `compile.text.owtext`. CLI `ow conform`. | [11](11-repo-layout.md) §1.2 | — |
| `omniweave-core` | dist / pkg | The foundation distribution. | [11](11-repo-layout.md) §1.3 | — |
| `omniweave-driver/1` | proto | The `subproc` DriverHost wire protocol: `u32 header_len ‖ u32 body_len ‖ JSON header ‖ raw body`, over a 0600 unix socket or an owner-only named pipe. **Never a loopback TCP port.** stdout and stderr are captured, logged at debug, and never parsed. | [04](04-driver-system.md) §6.5 | `MessagePack` on the driver wire |
| `omniweave-golden` | concept | The redistributable Tier-B evaluation corpus. **A versioned data artifact, never a Python distribution**; installed by digest into `$OMNIWEAVE_HOME/golden/<version>-<sha256>/` and re-verified on every use. | [13](13-quality.md) §4.1 | — |
| `omniweave-index` | concept | The static, CI-byte-diff-gated `index.json` of card stubs readable **before install**. An index, not a host. A data artifact, not a wheel. | [11](11-repo-layout.md) §7 | — |
| `omniweave-llm` | dist | The four `billed_api` `derive/1` LLM passes — `derive.merge.llm`, `derive.entity.llm`, `derive.claim.llm`, `derive.report.llm`. | [11](11-repo-layout.md) §1.2 | — |
| `omniweave-ports` | dist | The ~40 KB pure-typing distribution an `acquire`/`parse`/`derive`/`embed` Driver depends on **instead of** `omniweave-core`, so a driver cannot pin the framework. Imports as `omniweave_ports`. | [11](11-repo-layout.md) §1.2 | — |
| `omniweave-target/1` | proto | The NDJSON-on-stdio control protocol between omniweave and a Toolchain. stdout carries control frames only, under 1 MiB per invocation; stderr is a log, drained to a bounded ring tail, and never parsed. **Exit 0 iff a receipt was written.** | [02](02-architecture.md) §1.2 | — |
| `omniweave.acks.toml` | file | The reviewable, diffable file of per-driver licence acknowledgements, each bound to a `licence_sha256` and **void when it changes**. Never a boolean in the main config. | [04](04-driver-system.md) §7 | — |
| `omniweave.backends` | entry-point | The group declaring a `VectorBackend`, read by the same import-free loader as a DriverCard. Selected by name in config only. | [07](07-store-and-retrieval.md) §9 | — |
| `omniweave.drivers` | entry-point | The group declaring a Driver. The **entry-point *value* is a dotted package path** — never `module:attr`, never a filesystem path — and it is read as a string that is never `load()`ed. | [04](04-driver-system.md) §4.1 | — |
| `omniweave.index.lock` | file | **The one committed store artefact:** sorted plain text, one line per document, byte-stable, no timestamps, with a merge driver registered for that path only. A deleted line **stays deleted**. The index's *receipt*, not the index. | [07](07-store-and-retrieval.md) §10.1 | — |
| `omniweave.lock` | file | The project lockfile pinning every driver by version, ref, card digest, dist digest, licence tier and restriction codes. | [04](04-driver-system.md) §5 | — |
| `omniweave.operators` | entry-point | **Reserved and deliberately not created.** Operators are first-party until something appears that a Driver cannot express. | [04](04-driver-system.md) §1.1 | creating the group at all |
| `omniweave.signals` | entry-point | The signal-provider group. A provider is declared by this plus a `signals.toml`, read by the import-free card loader; it is never a `DriverCard` and never enters `resolve()`. | [05](05-ingest-and-routing.md) §4.5 | — |
| `omniweave.targets` | entry-point | The group mapping an artefact kind to the package holding its compile driver's card, so `ow out targets` can list a kind without resolving a driver. Both this gate and `[drivers] enabled` apply; neither bypasses the other. | [04](04-driver-system.md) §4.1 | — |
| `omniweave.toml` | file | The one user-facing config file. Line 1 is `schema = 1`. | [02](02-architecture.md) §8.1 | — |
| `.omniweave/policy.d/*.toml` | dir | **All** `[[rule]]` policy — routing, retrieval and pins — in one grammar with a required `surface = "route" \| "retrieval"` key. One loader, one subsumption linter, one threshold fitter, one six-layer precedence stack. | [05](05-ingest-and-routing.md) §4.1 | `route.toml`, `retrieval.toml`, `pins.toml`, `packing.toml` as separate files |
| `omniweave_core.store.crypto` | module | The **one** module permitted to call `os.urandom`, semgrep-allowlisted by path. The sole producer of the KDF salt, the recovery-blob nonce and the model-server sentinel token. | [14](14-security.md) §6.4 | — |
| `$OMNIWEAVE_HOME` | concept | The per-user state directory (default `~/.omniweave`) holding installed Toolchains, the probe verdict cache, the golden corpora and the install receipt. **Distinct** from the per-project `.omniweave/`. | [11](11-repo-layout.md) §1.1 | — |
| `op.redact` | fn | The core-side operator behind `ow store redact`: replaces a text range with `REDACTION_FILL`, resolves every intersecting `Mark`, converts the `pii` mark to `redaction`, clamps `quote` **down** to `NORMALIZED` and `origin_span` to `none`, deletes … | [14](14-security.md) §7.1 | `host.redact` |
| `op.redigest` | member | The host operator that recomputes `content_digest`/`layout_digest` bottom-up after a `digest_recipe` bump, over **every** generation present. The reason a recipe bump is not a re-parse. | [03](03-document-model.md) §15.3 | `host.redigest` |
| `op.resegment` | member | The host operator that re-runs the segmenter over stored blocks after a `segment_recipe` bump. | [03](03-document-model.md) §15.3 | `host.resegment` |
| Operator | concept | The scheduled step named on a work row: `<port>.<family>` when it invokes a driver, or `op.<name>` for a **core-only** step that invokes none — `op.identify`, `op.converge`, `op.lexicon`, `op.resolve`, `op.cluster`. | [08](08-runtime.md) §6.1 | `OperatorABC` |
| `OperatorIdentity` | type | **The same type as `Producer`.** One type, two layers, one table. | [08](08-runtime.md) §1.3 | — |
| `ord` | column | A Block's position among its siblings. **`ord` *is* the reading order** — one representation, not a scalar plus a redundant structure list held equal by a validator. | [03](03-document-model.md) §1.1 | — |
| `origin_driver` | column | The **three-segment** driver id that produced a row. The provenance and cost key. | [03](03-document-model.md) §2.5 | — |
| `origin_operator` | column | The **two-segment** `<port>.<family>` prefix. **Ownership, not trust:** the eviction key, so `derive.segment` re-running cannot touch `derive.entity` rows (I4). | [03](03-document-model.md) §2.5 | — |
| `OriginSpan` | type | The address of a Block **in its original container**. | [03](03-document-model.md) §7.2 | — |
| `OsKind` | enum | The five `OriginSpan` variant tags as a Python enum: `bytes`, `nodepath`, `glyphs`, `pixels`, `none`. The source the `origin_span_kind` `enum_val` domain is generated from. | [03](03-document-model.md) §2.1 | — |
| `Outcome` | enum | The nine-value work outcome: `ok`, `ok_partial`, `skipped_cached`, `skipped_unchanged`, `failed_transient`, `failed_permanent`, `deferred_budget`, `cancelled`, `held` (D661). | [08](08-runtime.md) §1.2 | — |
| `OutReport` | type | The validation report object behind `validation/<stage>.json`, schema `omniweave.out-report/1`. | [09](09-generation.md) §2 | — |
| `OutUnit` | type | One addressable output unit of an artefact — a slide, a page, a section, a scene — frozen at plan time and carrying its id (`u03`, never renumbered), its ordinal, its job-relative IL path, its Brief anchor, its `nsig`, the three-field source triple on an edit, and a `ManualReason` where one was declared. It carries **no** `UnitOutcome`: the outcome is a compile-time result and lives in `Receipt.units` and `artifact_unit.outcome`, so `classify_and_assert()` has one place to write. | [09](09-generation.md) §3.7 | `Unit` (for OUT's output unit) |
| `ow` | cli | The console script. `omniweave` is the same script. **No other alias.** | [10](10-interfaces.md) §6.1 | — |
| `ow bench` | cli | The performance-measurement group. | [12](12-performance.md) §7.1 | — |
| `ow128()` | fn | `blake2b(canonical(obj), digest_size=16, person=domain)`. Every 128-bit digest in the framework. The `person=` parameter is a **domain separator**, not a prefix. | [03](03-document-model.md) §2.5 | `blake3_128` |
| `<ow:untrusted>` | concept | The wrapper around every served evidence block, carrying a data-not-instruction line. | [14](14-security.md) §3.2 | — |
| `OW_ASSET_DIGEST_MISMATCH` | code | An `AssetDraft` whose declared `sha256` disagrees with the stream the host hashed. | [03](03-document-model.md) §11 | — |
| `ow_block_head` | view | `block` joined to `doc` on `gen` with `state = 0` — the head-generation projection every reader goes through, and the mechanism that makes a staged generation invisible. | [03](03-document-model.md) §13.1 | — |
| `OW_DEPTH_FLATTENED` | code | A subtree deeper than `MAX_BLOCK_DEPTH` was flattened into its ancestor. Warning. | [03](03-document-model.md) §14.1 | — |
| **`ow_entity_head`** | view | `SELECT * FROM entity WHERE state = 0 AND entity_id = canonical_id`. The row every ranking, embedding and prompt-rendering consumer reads, so a merged cluster is ranked once rather than once per fragment. | [06](06-structure-extraction.md) §1.5 | — |
| `OW_HEADING_LEVEL_SKIPPED` | code | A document whose headings skip a level; informational, and the derived depth is made consecutive by L3. | [03](03-document-model.md) §9 | — |
| `OW_INTEGRITY_UNCHECKED` | code | Already in `codes.toml` via `owcheck`; listed here because §1.1 makes `owcheck` a step of `end_doc()` rather than an archive-only pass. | [03](03-document-model.md) §1.1 | — |
| `OW_LAYER_NOT_INHERITED` | code | A non-page-root draft naming a layer different from its parent's (M-INV-5). | [03](03-document-model.md) §5 | — |
| `OW_MARK_KIND_UNKNOWN` | code | A `mark.kind` the reader does not recognise; the mark is kept and rendered as no formatting. | [03](03-document-model.md) §15.2 | — |
| `OW_MERGE_KIND_MISMATCH` | code | A merge (§8.5a) whose inputs disagree on `kind` or `layer`; refused. | [03](03-document-model.md) §8.5 | — |
| `OW_MERGE_PAYLOAD_DROPPED` | code | A merge whose inputs disagree on a shared `payload` or `x` key; the key is dropped. Informational. | [03](03-document-model.md) §8.5 | — |
| `OW_QUAD_NO_DPI` | code | `Quad.from_driver(unit="px")` without a `dpi`. | [03](03-document-model.md) §7.1 | — |
| `OW_QUOTE_CLAMPED` | code | Emitted when `MAX_QUOTE_BY_OS_KIND` lowers a driver's claim, carrying the original claim so over-claiming is measurable. | [03](03-document-model.md) §8.3 | — |
| `OW_REBIND_UNEXPLAINED` | code | A re-parse below `rebind()`'s threshold; the generation is quarantined, not committed. Cleared by `--allow-unexplained-rebind`. | [03](03-document-model.md) §6.6 | — |
| `ow_ref_resolved` | view | The resolved half of the reference layer: `ref_site` joined to `anchor` on `(name_norm, akind)`, **restricted to the head generation and honouring anchor scope** — the same two predicates `ref_unresolved` applies, because an anti-join and its join must agree. | [07](07-store-and-retrieval.md) §3.5 | — |
| `OW_SCHEMA_PAYLOAD_INVALID` | code | A `payload` failing its kind's generated schema, raised at `add_block`. | [03](03-document-model.md) §4.4 | — |
| `ow_segment_head` | view | Live Segments at their document's head generation: `segment` joined to `doc` on `gen` with `state = 0`. | **none** — charter L3 DDL only | — |
| `OW_TEXT_SPLIT` | code | A block's `text` exceeded `MAX_BLOCK_TEXT_BYTES` and was split into `continues`-joined siblings. Informational. | [03](03-document-model.md) §14 | — |
| `OWC1` | proto | The framework's carrier-agnostic feedback marker grammar: a fixed regular language inside a carrier comment, opening with the literal `OWC1:v1` and carrying `el`, `nsig`, `id`, `ts` and a base64url JSON payload whose `-` runs are space-separated so the marker is legal inside an XML comment. | [09](09-generation.md) §8 | — |
| `owcheck` | fn | The invariant validator: the parent/`ord` bijection, grid exactly-once, `rel` referential integrity, and the verbatim-implies-retained-part rule. | [03](03-document-model.md) §1.1 | — |
| `.owdoc` | file | The single-document interchange archive: **a plain ZIP** of deflated NDJSON Frames plus a pretty-printed `manifest.json`. A lossless projection of one document's rows out of an `.owstore`, held to `import(export(store)) == store` in CI. | [03](03-document-model.md) §13.2 | — |
| `owdoc` | concept | omniweave's canonical document model and its normative schema — the type layer every other layer reads and writes. | [03](03-document-model.md) §13.2 | `.ndjson.zst` members |
| `owdoc-fragment/1` | proto | What a `parse/1` driver **emits**: NDJSON addressing blocks by a per-invocation `tmp` id, with the **host** minting `block_id`, `addr` and `cite`. No `block_id` ever crosses the wire, so a fragment is portable between stores. | [03](03-document-model.md) §13.3 | — |
| `.owdoc.d/` | dir | An `.owdoc` exploded and uncompressed, so git delta-compresses it and `jq` reads it. The deep-golden form. | [13](13-quality.md) §4.6 | — |
| `OwError` | type | **Raised**, and it aborts the current unit. Carries a stable machine code, `is_fatal()` and a `fix`. `Diag` is recorded; `OwError` is raised. | [02](02-architecture.md) §7.2 | — |
| `.oweval` | file | The evaluation store — a **separate** SQLite file, because eval rows are deleted, corpus rows are not, and one eval run spans many stores. | [13](13-quality.md) §11.4 | — |
| `owgraph` | concept | omniweave's L3 knowledge model: the segment, anchor, entity, alias, mention, edge, claim, community and residue tables **inside the `.owstore`**. Never a second store, never a second block representation. | [06](06-structure-extraction.md) §1 | — |
| `owgraph-items/1` | proto | What a `derive/1` driver **returns**: drafts addressing blocks by `cite` and each other by a per-invocation `tmp` id, and, from `derive.segment.spine` alone, `segment` frames (D662). Its item frames are the Drafts' fields under the Drafts' names, each unit's opened by a `seg` frame (D666). A `tmp` referenced but never defined quarantines the whole Segment. | [06](06-structure-extraction.md) §1 | — |
| `owgraph-segment/1` | proto | What a `derive/1` driver **receives**: a Segment header plus its blocks -- or, for the segmenter, a `doc` header plus the document's blocks (D662) -- addressed by `cite` only; a cell's `table` object also carries `n_cols` (D666). **No `block_id`**, so a driver cannot forge one. | [06](06-structure-extraction.md) §3.2 | — |
| Owner role | concept | One of **ten** labels — `licence`, `model`, `drivers`, `router`, `runtime`, `retrieval`, `out`, `surface`, `quality`, `release` — naming which of the charter's decisions a risk, gate, counter or open question belongs to. | [17](17-risks.md) §1 | — |
| `owroster-items/1` | proto | What an `acquire/1` driver emits: NDJSON, one record per discovered unit, addressed by locator, with the **host** writing `unit` and `ingest_scope` rows. Symmetric with `owdoc-fragment/1` and `owgraph-items/1` — one pattern, three Ports. | [04](04-driver-system.md) §1.4 | — |
| `owrows` encoder id | concept | The short mnemonic naming one `owrows/1` schema (`hit1`, `prov1`, `nb1`, `gen1`). A decoder selects its rehydration routine by this id; a new response shape adds an id rather than changing an existing one. | [07](07-store-and-retrieval.md) §7.5 | — |
| `owrows/1` | proto | The compact tabular wire encoding for the **structured half** of a retrieval response — hits, provenance rows, neighbourhood edges — derived from jcodemunch's MUNCH **pattern and spec, not its code** (it is dual-licensed). | [07](07-store-and-retrieval.md) §7.5 | — |
| `.owstore` | file | The SQLite file holding one corpus — the L2 model, the L3 graph, the L4 index layer and the operational tables. The canonical local form and the published read interface at a `SCHEMA` major. `.gitignore`d; a tracked store fails `ow doctor`. | [07](07-store-and-retrieval.md) §1 | `index.db` |
| `owvec-batch/1` | proto | What an `embed/1` driver emits: a JSON header plus a raw little-endian f32/int8/bit body over `omniweave-driver/1`. Row order is input order; a short batch is `TOO_LARGE`, never a silent truncation. | [04](04-driver-system.md) §1.4 | — |
| Pacer | concept | The fixed, dependency-free in-repo CPU workload (`blake2b` over 64 MiB, a 2M-iteration integer loop, 200k SQLite insert+select) run immediately **before and after** a timed measurement; every time budget is a **ratio** to it. | [12](12-performance.md) §1.2 | — |
| `PackSpec` | type | What **retrieval** bounds: `k`, `max_blocks`, `max_chars`, and whether to hydrate text and spans. `hydrate_text = False` makes every `Hit.text` `None`. The Answer allocator, its tiers and its cliff are `10-interfaces.md`'s and are not here. | [07](07-store-and-retrieval.md) §16 | — |
| `page` | table | One row per `(doc_ord, gen, page)`: the **original** source index (never a batch index), the page kind, the printed label, the size in 1/1000 pt, the rotation, the origin the driver handed us, the method that ran **on this page**, four quality scores and the segmentation owner. | [03](03-document-model.md) §2.8 | — |
| `Page anchor` | concept | The topmost ancestor of a Block strictly below the `document` root; its `page` is the page component of the Block's `addr` (M-INV-2). Equal to the Block's own page except inside a page-crossing construct. | [03](03-document-model.md) §3.2 | — |
| `Page-root ordinal` | concept | A Block's index among the page-root blocks of one page, dense from 0 in `ord` order, and the first step of its `addr`. Page-local rather than document-global, so re-parsing one page renumbers no other. | [03](03-document-model.md) §3.2 | — |
| `page_render` | table | A **derived, evictable** cache of rendered page images, keyed by dpi, renderer, renderer version and colorspace. | [03](03-document-model.md) §11 | — |
| `PageKind` | enum | What a `page` row denotes: `page \| slide \| sheet \| frame \| stream`. `w_mpt`/`h_mpt` are NULL when the kind is `stream`. | [03](03-document-model.md) §2.1 | — |
| `PageRecord` | type | The frozen per-page record `DocSink.begin_page` carries — the `page` row as a value type. | [03](03-document-model.md) §2.8 | — |
| `parse.text.builtin` | driver-id | The stdlib-only `parse/1` driver for the ten text-family format tokens anydoc does not serve. It ships in `omniweave-office` and stands in the release-1 roster, [04](04-driver-system.md) §10.1. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit | — |
| `parse/1` | proto | The Port that turns bytes plus a part selector into an `owdoc-fragment/1` stream. Format detection is **not** a Port: a `parse` driver declares `detects = true` and exposes `sniff()`, and the detection chain is core code. | [04](04-driver-system.md) §1.1 | — |
| `ParseError` | type | The value `CarrierDoc.splice()` and `marker.apply_reverse()` **return** rather than raise when the post-splice reparse fails: `at` in `path:line:col` form and the parser's own `msg`. The original file is untouched. | [09](09-generation.md) §3.1 | neither a `Diag`, which is recorded on a document, nor an `OwError`, which is raised |
| `ParseV1` | proto | The `parse/1` Driver's contract, in `omniweave_ports`: `probe`, a static-config `__init__` that loads no model and opens no file, `sniff` (many-to-one, ranked, and it must not advance a stream), `parse` (emitting `owdoc-fragment/1`), `is_valid_nonempty`. | [04](04-driver-system.md) §1.4 | — |
| Part | concept | (routing) The unit of routing decision and of a `work` row: a page / slide / sheet / track for the parse lanes, and a **Segment** for the graph lanes. `unit_part` is `TEXT NOT NULL DEFAULT ''`; the empty string is what prose calls NULL. | [05](05-ingest-and-routing.md) §1.2 | — |
| `part` | table | Named byte streams of the original container, hash-pinned, with a `store_ref` that is NULL when the bytes were not retained. **`quote = 'verbatim'` requires a non-NULL `store_ref`** (INV-10). | [05](05-ingest-and-routing.md) §1.2 | — |
| `PartSelector` | type | Which parts of a document one `parse/1` call covers: `pages` (`()` means the whole document) and `parts` (container member paths, for a part-granularity driver). A fragment naming a page outside the selector is `OW_FRAGMENT_OUT_OF_SCOPE`. | [04](04-driver-system.md) §1.3 | — |
| Pass | concept | One named extraction mechanism with a cost class, a **phase**, a lane set and a granularity. A row in `derive_pass` — **data, not a hardcoded pipeline list**. Ordered by `(cost_rank, phase)`. | [06](06-structure-extraction.md) §1.7 | — |
| `PendingEntry` | type | One watcher pending-set entry: `first_seen_gen` and `last_seen_gen`. Eviction compares `last_seen_gen` against the run generation, which is what makes I3 provable. The set is in-memory by design — it is a coalescing buffer, not a queue. | [08](08-runtime.md) §5.4 | — |
| **Phase** | concept | One numbered stage of the build (`M0`, `P1`-`P10`) with a goal, an engineer-week cost, a set of work items, a **freeze week**, an **exit week**, a demo, executable exit criteria and explicit non-goals. | [16](16-roadmap.md) §3 | — |
| `phase` | column | A Pass's **secondary** ordering key on `derive_pass`, card-declared with default 50, meaningful only **within** one `cost_rank`. `(cost_rank, phase)` is the ordering. | [14](14-security.md) §8 | — |
| `pii` | member | The `mark.kind` member a PII Pass writes, carrying `{"kind": "<PiiKind>", "detector": "<driver_id>", "score_kind": "pii_span"}`. Not itself a disclosure control; an input to `op.redact` and a `corpus_card` count. | [14](14-security.md) §7.1 | — |
| `PiiKind` | enum | The closed vocabulary of a `pii` Mark's detected class, in `omniweave_core.model`: `email`, `phone`, `iban`, `card`, `national_id`, `person`, `org`, `address`, `dob`, `ip`. | [14](14-security.md) §7.1 | — |
| `Plan` | type | The gated compile plan: the target, the slug, the ordered `Unit` roster, `unit_count`, the `Brief`, the resolved cite set, the `GateStatus`, and the six purity digests — `ledger_digest`, never the `AssetLedger` object, which is `lower()`'s own argument. `lower()` receives one and cannot see the report it was gated by. | [09](09-generation.md) §3.7 | — |
| Plan document | concept | The canonical JSON projection of (catalog x policy x pass registry x scope x store state) at `plan/1`, digested as `plan_digest`. | [08](08-runtime.md) §6.3 | — |
| `plan/1` | proto | The Plan document's wire name and `schema` value. | [08](08-runtime.md) §6.3 | — |
| `plan_digest` | concept | `sha256_canonical()` over the Plan document with its own `plan_digest` key and its `estimate` block removed. Stable across two runs of the same scope over the same store, so a plan diff is meaningful. | [08](08-runtime.md) §6.3 | — |
| `PolicyRefusal` | type | The `OW-P-*` member: a licence tier, `restriction_bits`, or a missing egress `Grant`. A refusal, not a failure — it names the approving command. | [02](02-architecture.md) §7.2 | — |
| Port | concept | A typed, versioned seam identified `<name>/<major>`. **Exactly five at v1:** `acquire`, `parse`, `derive`, `embed`, `compile`. Adding one is a core release. | [04](04-driver-system.md) §1.1 | "port" for a TCP listener |
| **`portability`** | concept | *(coined here)* A `Receipt` and `OutReport` block recording facts that do not make an artefact invalid but make it break elsewhere: generic-only font stacks, unsafe exported faces, external asset references, unresolved Brief tokens. | [09](09-generation.md) §4.2 | — |
| `PREFILTER_MAX` | const | 200,000. At or below it, the narrowing set is materialised **exactly** and every channel — including the ANN one — filters exactly, with no recall loss. Above it, narrowing becomes an over-fetch factor. | [07](07-store-and-retrieval.md) | — |
| `PriceBook` | concept | The **operator-owned**, versioned, digested mapping from `Spend` units to micros. `.omniweave/pricebook.toml`. **The only place money appears** (INV-15). | [05](05-ingest-and-routing.md) §6.2 | `usd_per_unit`, `cost_micros` on a driver-facing type |
| **principle** (`P-n`) | concept | A named rule governing a judgment call no invariant decides. A reviewer may reject on one only by naming the concrete cost. Thirteen at release 1. | [01](01-principles.md) §2 | — |
| `probe()` | fn | The `CacheProbe` constructor in `omniweave_core.cache`, taking the layer from the operator's `CACHE_LAYER`. Distinct from a **Capability probe**, which proves a driver capability works; `probe()` reads the cache and nothing else. | [08](08-runtime.md) §5.5 | — |
| `probe_ttl_s` | const | 600. How long an `unavailable` `ProbeVerdict` is cached before it is re-probed, because `unavailable` is the verdict a user *fixes* and its inputs are not all in `env_digest`. `ok` and `degraded` are cached for the life of the digest (E5). | [04](04-driver-system.md) §4.7 | — |
| `ProbeEnv` | type | What `probe()` is allowed to know: `platform`, `machine`, `python`, the `which()` map for every `[hardware] needs_binaries` name, `gpu_present` (from `ctypes.util.find_library`, **never** by importing a framework), `vram_gb` (`0.0` when unknown) and `offline`. No writable path, no network handle, no config. | [04](04-driver-system.md) §1.3 | — |
| `ProbeStatus` | enum | `ok \| degraded \| unavailable` — the status half of a `ProbeVerdict`. | [04](04-driver-system.md) §5.4 | — |
| `ProbeVerdict` | type | `ok \| degraded \| unavailable` plus a `detail` that must **name the missing thing**, a machine-actionable `missing[]`, a `fix_hint`, and `capabilities_lost[]` so the router can re-filter. | [04](04-driver-system.md) §1.2 | — |
| `Producer` | type | The reproduction tuple as a row: operator, **`op_version` (an INTEGER, at every site)**, code_fingerprint, model_id, `model_rev` (an **exact** sha; `"main"` is a lint error), runtime, runtime_version, prompt_fp, options_digest. | [03](03-document-model.md) §2.8 | — |
| Profile | concept | A named listed-set for the agent surface. Two exist: `default` (the front door) and `full`. | [10](10-interfaces.md) §3.8 | — |
| `project()` | fn | A Target's `Doc -> IL bundle` method. **The reconstruction path**, used for foreign artefacts and for artefacts whose retained IL was lost. Always `rebuilt`, always with declared loss. | [09](09-generation.md) §1 | — |
| `project_schema()` | fn | The projection of a Scope through a caller's JSON Schema, returning the produced object and a `FieldGrounding` per leaf. The lift-style extraction path, expressed as a view over the model rather than a parallel output. | [03](03-document-model.md) §16.4 | — |
| Prompt-safe token | concept | See `cite`. The closed typed space `d…#…`, `e…`, `c…`, `k…`, optionally corpus-qualified. **No other identifier may enter a prompt** (INV-8). | [03](03-document-model.md) §6.3 | — |
| **`PromptPack`** | concept | The versioned set of authored prompt bodies for one distribution (`omniweave_llm/prompts/<lane>.md`), rendered against `etype_vocab` and `relation_vocab` at call time and fingerprinted as `prompt_fp`. | [06](06-structure-extraction.md) §4.7 | — |
| `Provenance` | enum | (OUT) Who **owns** a Finding: `introduced \| inherited \| imported \| framework`. **Orthogonal to `Severity`:** an inherited *error* still blocks, attributed to the template. | [09](09-generation.md) §4.1 | `FindingProvenance` |
| `publishable` | column | A corpus-manifest boolean, **independent of `redistribute`**, stating whether that corpus's numbers may reach the public scoreboard. `false` renders the cell as `withheld: corpus licence`. | [13](13-quality.md) §4.1 | — |
| `Quad` | type | Four corners in fixed-point 1/1000 pt, top-left origin, unrotated page, `i32` and **never float** — a float bbox makes `layout_digest` libm- and platform-dependent, which silently poisons every cache keyed on it. | [03](03-document-model.md) §2.3 | — |
| `QUAD_SLACK_MPT` | const | 3,000 (3 pt). The tolerance in P6's page-containment assertion, wide enough for a bleed or a skewed scan line and far short of a coordinate-frame error. | [03](03-document-model.md) §17 | — |
| `QualityError` | type | The `OW-Q-*` member: an incomplete `MeasuredOn`, an unblessed golden diff, a cassette miss under `--cassette required`. | [02](02-architecture.md) §7.2 | — |
| `quarantine` | table | Rejected derive drafts, **kept verbatim** with a closed code. A hallucinated name is very often a real entity the extractor failed to emit a row for, so it is kept, not deleted. | [06](06-structure-extraction.md) §1.1 | — |
| `Query` | type | One retrieval request: text, lifted refs, `Filters`, a mode, `k` and packing caps, an optional `space_id`, an optional `Expand`, and an optional budget. | [07](07-store-and-retrieval.md) §3.10 | — |
| `QueryBudget` | type | The deadlines of one query: `query_ms` (the snapshot-held phase), `embed_ms` (phase 2, outside it), `snapshot_ms` (clamped below `MAX_SNAPSHOT_MS`), `federate_ms` (T4), the per-Channel `channel_ms` map, and `max_micros` (0 = no billable work on the query path). | [07](07-store-and-retrieval.md) §16 | — |
| `QueryPlan` | type | `plan()`'s output: the ordered channel specs (the order **is** the run order), the filters, the fusion and packing specs, which absence gates apply, an optional short-circuit, the scorer version and two digests. | [07](07-store-and-retrieval.md) §6 | — |
| `Quote` | enum | A Block's quotability tier, an **ordered `IntEnum` with the weakest tier lowest**: `SYNTHETIC=0 < RECONSTRUCTED=1 < REFLOWED=2 < NORMALIZED=3 < VERBATIM=4`, so `MIN()` over a set is its **weakest** member — which is what makes `segment.quote_min` and `Filters.min_quote` gates rather than lies. | [03](03-document-model.md) §8.3 | — |
| `QuoteVerdict` | enum | `match \| source_ahead \| mismatch \| source_unavailable`. **`source_ahead` must not read as corruption** — the source is newer and the slice still matches. | [03](03-document-model.md) §7.4 | — |
| `rank_of` | column | `ChannelResult`'s authoritative 1-based rank per `block_id`, empty for every Channel but `semantic`. | [07](07-store-and-retrieval.md) §5.1 | — |
| `RankedGuess` | type | The host-side wrapper around a `FormatGuess`: `(guess, basis, detail)`. What ranks, what enters `doc.format_evidence`, and what the detection ladder emits. Host-side because `basis` is the host's classification and `omniweave_ports`' `layers.toml` row is `[]`. | [05](05-ingest-and-routing.md) §2.1 | — |
| `RATE_LIMIT_COOLDOWN_MS` | const | The per-provider rate-limit cooldown table in `omniweave_core.work`, keyed on `Spend.provider` with a `default` of 3,600,000 ms and overridable by `[providers.<tag>] rate_limit_cooldown_ms`. A `Retry-After` header always wins. | [08](08-runtime.md) §1.6 | — |
| `read_back` | concept | A Target's `parse/1` Driver: artefact → `owdoc-fragment/1` → Blocks, stamping `Method.ROUNDTRIP`. **An ordinary Driver** with an ordinary card, probe, licence block and conformance run, and the ~120-test testkit runs against it unchanged. | [09](09-generation.md) §11 | — |
| `Reader` | proto | The retrieval boundary: `snapshot`, `capabilities`, `narrow`, `channel`, `hydrate`, `coverage`. A Postgres T3 implements this. | [07](07-store-and-retrieval.md) §3.1 | — |
| `rebind()` | fn | The explicit re-parse identity pass, in **three rules**: equal `content_digest` under the same parent carries the `block_id`; equal `addr` + `kind` with a changed digest carries it and bumps `revision`; otherwise a fresh id and a `block_history` row. | [03](03-document-model.md) §6.5 | — |
| `RebindReport` | type | `rebind()`'s output: the generations compared, the carried/revised/created/retired counts, the per-page match rate, and whether the new generation was **quarantined** rather than committed. | [03](03-document-model.md) §6.5 | — |
| `Receipt` | type | The postflight delivery evidence, schema `omniweave.out-receipt/1`: the output identity, `part_digest`, the compiled `ArtefactDeterminism` set, the gate status, the delivery tier, the `CheckValue` tuple, the per-unit `UnitOutcome` map with asserted … | [09](09-generation.md) §5.3 | — |
| `redact()` | fn | The pure function in `omniweave_core.events` applied at the construction boundary of every message crossing into an `Event`, a ledger column or a console line. | [15](15-observability.md) §8.3 | — |
| `REDACTION_FILL` | const | `"█"` (FULL BLOCK), repeated to the redacted range's original **character** length, so every stored `TextSpan` stays valid and no offset-shift map exists anywhere in the framework. A block that becomes entirely fill is retired, not served. | [14](14-security.md) §7.2 | — |
| Reduction | concept | A deterministic, sorted, LF-normalised, line-oriented projection of one document out of an `.owstore`, in exactly three kinds: `shape` (per-document counters, no text, no per-corner geometry), `pages` (one line per page), `outline` (one line per block, suppressed above 500 pages). | [13](13-quality.md) §5 | — |
| `ref_attempt` | table | The **failed tail** only, written after a first failure: attempt count, last generation tried, and near-miss candidates. Gives the hot set an index without a status column that can lie. | [07](07-store-and-retrieval.md) §3.5 | — |
| `ref_site` | table | Every reference **occurrence** at a Block and `TextSpan`, keyed `(name_norm, akind, block_id, a)`, carrying the owning `doc_ord`, the surface as written and the scope. | [07](07-store-and-retrieval.md) §3.5 | — |
| `ref_unresolved` | view | The anti-join of `ref_site` against `anchor`, **joined to `doc` on `gen` so only the head generation resolves, and filtered so a `scope='document'` anchor resolves only its own document's references**. | [07](07-store-and-retrieval.md) §3.5 | `unresolved_ref` |
| Reference machine | concept | One of exactly three named, specified hosts on which a performance number may be measured: **`ow-bench-1`** (the pinned Pacer Runner, x86_64-linux 8c/16 GiB, no GPU — the **only** machine a `Budget` may live on, because it is the only one with a … | [12](12-performance.md) §Open questions | — |
| `RejectCode` | enum | The typed enum a `Resolution` refusal carries, and which `DR5` makes required to construct one. Its members are rows of the **one** append-only `codes.toml` register under `OW-D-nnn` with `OW_DRIVER_*` symbols — a typed enum over one register, never a second register. | [02](02-architecture.md) §7.2 | — |
| `Rejection` | type | `(DriverId, RejectCode, detail)` — a **returned value**, never a raise. **A zero-candidate `Resolution` *is* the error message.** | [04](04-driver-system.md) §4.7 | — |
| **rejection list** | concept | The table in §4.3. A row's number is a complete review rejection. | [01](01-principles.md) §4.3 | — |
| `Rel` | type | One `rel` row as a value type, returned by `Doc.rels()`. | [03](03-document-model.md) §2.8 | — |
| `rel` | table | The **closed** intra-document relation set: `caption_of`, `note_ref`, `continues`, `anchor_ref`, `heading_of`, `derived_from`, `supersedes`. Seven kinds, and only seven, because the parser produces them and the serializer consumes them. | [03](03-document-model.md) §2.8 | — |
| `relation_vocab` | table | The **open** entity-relation vocabulary, with `symmetric` and a mandatory `actor_rule` written in prose. **The extraction prompt is generated from this table**, so prompt and schema cannot drift. A relation with no `actor_rule` is a card error. | [06](06-structure-extraction.md) §1.6 | — |
| `RELEASE` | concept | The single semver carried by every first-party distribution and by the git tag. One tag, one changelog. Gate G5 checks every declaration site as CI job 1. | [11](11-repo-layout.md) §7.2 | — |
| Release provenance | concept | The Sigstore bundle, the GitHub build attestation and the SLSA build-level-3 `provenance.intoto.jsonl` that together prove a first-party artefact was built from this repository at this commit by `release.yml`. | [11](11-repo-layout.md) §7.2 | — |
| `RelKind` | enum | The seven closed intra-document `rel` kinds: `caption_of`, `note_ref`, `continues`, `anchor_ref`, `heading_of`, `derived_from`, `supersedes`. Containment is not among them. | [03](03-document-model.md) §2.1 | — |
| `RenderedBlock` | type | One evidence block as the Answer renderer sees it, and what `withhold()` takes. Named this rather than `Evidence`, which is the routing record, or `ManualEvidence`, which is the OUT artefact. | [10](10-interfaces.md) §3.5 | `Evidence` (for a served answer block) |
| `RenderSpan` | type | A character range inside a **hash-pinned named view**, carrying a `view_id` of serializer name / version / options digest. Never stored on a Block; produced and consumed at the serializer boundary, liftable only through a `SpanMap`. | [03](03-document-model.md) §2.4 | — |
| `ReplayClass` | enum | How a **driver's output** replays: `byte_exact \| seeded \| unpinnable`. Three values where a boolean could not express "continuous batching makes output batch-composition-dependent". Distinct from `ArtefactDeterminism`. | [13](13-quality.md) §7.2 | — |
| **`REPORT_CONTEXT_TOKENS`** | const | `8000`. The community-report context budget, filled in three ordered passes (members, internal edges, claims), each stopping at a whole record. `community_report.coverage` is the fraction of members that fit. | [06](06-structure-extraction.md) §6.3 | — |
| `request.deadline_ms` | signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. | [05](05-ingest-and-routing.md) §5.1 | — |
| `request.lane` | signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. | [05](05-ingest-and-routing.md) §5.1 | — |
| `request.max_rung` | signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. | [05](05-ingest-and-routing.md) §5.1 | — |
| `request.prefer_capability` | signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. | [05](05-ingest-and-routing.md) §5.1 | — |
| `request.schema_present` | signal | The charter's `request.*` glob, enumerated, because `ow route lint` cannot resolve a glob. | [05](05-ingest-and-routing.md) §5.1 | — |
| `Requirement` | type | What a caller needs from a Port: format, produced kinds, capability floors, a cost ceiling, granularity, an optional pin. | [04](04-driver-system.md) §2.3 | — |
| `requires_credential` | column | A `[licence.code]` fact: the licence requires a purchased credential. `compute_tier`'s sole route to the `commercial` tier (E10). | [04](04-driver-system.md) §In one paragraph | — |
| `Reservation` | type | One `budget_reservation` row's handle, with a `reservation_id` content-addressed over `(work_id, decision_id, attempt, dim)`, so a retried reserve is idempotent and each capped dimension is a distinct row. | [08](08-runtime.md) §Open questions | — |
| Residue | concept | `ref_unresolved` plus `quarantine`. **Unfinished business and rejected rows are queryable tables with partial indexes, never log lines.** | [06](06-structure-extraction.md) §2.4 | — |
| `Resolution` | type | `resolve()`'s output: **unordered** candidates (sorted lexically before return so no caller can depend on an emergent order), every `Rejection`, and three digests. Never contains a chosen driver. | [04](04-driver-system.md) §2.2 | — |
| `resolution_report` | table | **One row per `(run_id, resolution_digest)`** with a hit counter — not per unit, because a 4,000-page PDF must not write 4,000 report rows. | [04](04-driver-system.md) §4.7 | — |
| `resolve()` | fn | The **pure** function returning admitted candidates **and every rejection with a typed code**, memoised on `(port, format, floors, cost ceiling, policy digest, catalog digest)`. No imports, no network, no clock. | [04](04-driver-system.md) §4.7 | — |
| `RESOLVE_MEMO_MAX` | const | 512. The LRU bound on `resolve()`'s memo, held on the `Catalog` so it dies with the catalog rather than leaking across runs in a served process. | [04](04-driver-system.md) §4.8 | — |
| `ResourceLimit` | type | The cross-area `OwError` whose constructor **requires** `limit`, the name of the knob that would need raising. It is the one error obliged to name a knob, which is why it is not confined to a single area letter. | [02](02-architecture.md) §7.2 | — |
| `Response` | type | What `retrieve()` returns, and exactly three fields: a totally ordered `hits` tuple, the `Verdict`, and the `Spend`. Everything a caller might want as a fourth field is either on `Hit`, on `Verdict`, or a separately named read. | [07](07-store-and-retrieval.md) §7.1 | — |
| `Restriction` | enum | One of **32 reserved** closed-vocabulary licence restriction codes: `output_share_alike`, `competitor_bar`, `territory_excluded`, **`field_of_use_excluded`** (spelled to match the card fact exactly, like every neighbour, so the fact→bit map … | [14](14-security.md) §9 | — |
| `restriction_bits` | column | The integer bitmask over `Restriction`, **set by the runner from the producing card** and carried on every produced item — block, segment, entity, mention, edge, claim, asset, artefact. **The single name for this concept — never "encumbrance".** | [03](03-document-model.md) §2.5 | `encumbrance`, `licence_bits`, `restrictions` |
| `retrieval_event` | table | The **query ledger** in `events.owstore`: one row per retrieval, with the plan, the channels and their timings, the verdict and its gates, coverage, freshness, spend and latency. | [15](15-observability.md) §5.2 | — |
| `RetrievalPolicy` | type | D4's loaded, digested policy at `surface = "retrieval"`: first-match-wins rules, thresholds, a name and a `policy_digest`. Same grammar, same loader, same subsumption linter, same isotonic fitter as the routing surface. | [07](07-store-and-retrieval.md) §16 | — |
| `Roots` | type | `source` / `output` / `cache`, always separate; a `cache` inside `source` is a startup error. The cache salt is relative to `source`, which is why `roots.source` is `operational`. | [08](08-runtime.md) §1.3 | — |
| Roster | concept | The `unit` table — one durable row per source document, carrying the connector cursor, the acquisition state machine, the racily-clean stat triple, the content digest and the part count. | [05](05-ingest-and-routing.md) §1.3 | — |
| Route stub | concept | `skills/omniweave/references/routes/<name>.md`, ~40 lines, **generated**: one destination's inputs, outputs, triggers, non-goals, determinism class, gate, entry question and refusal condition. | [10](10-interfaces.md) §5.4 | — |
| `route_decision` | table | One immutable ledger row per `(content_digest, part, lane, rung, policy_digest, pricebook_digest, hints_digest, read_set_digest)`, **written before any driver runs**, recording the winning rule with its file and line number, the cause, the estimate, the reservation and the admission. | [05](05-ingest-and-routing.md) §7.1 | — |
| `route_evidence` | table | Refcounted, content-addressed evidence blobs, so they age out independently of decisions. | [05](05-ingest-and-routing.md) §6.6 | — |
| `route_quality` | table | Quality observations against a decision, from `self` (stored, never scored), `agree`, `audit` or `feedback`. | [05](05-ingest-and-routing.md) §7.2 | `route_verdict` |
| `route_scoreboard` | view | The per-`(slice, rule, driver)` rollup with a three-valued state whose zero value is **`UNKNOWN`**. Filters `source = 'self'` out by definition. | [05](05-ingest-and-routing.md) §7.3 | — |
| `route_signal` | table | The signal cache, **per signal** rather than per suite, so one signal's version bump does not invalidate the other thirteen. The decision itself is microseconds; the 96-DPI raster is not. | [05](05-ingest-and-routing.md) §5.4 | — |
| `route_spend` | table | Actual spend per `(decision, attempt)` in physical units plus micros, with `was_cache_hit` and `would_have_been_micros` for replayed hits. | [05](05-ingest-and-routing.md) §6.4 | — |
| `route_threshold` | table | `(k, v)` rows written by the policy loader from the compiled policy's `[audit]` block, because a **view may not contain a bind parameter**. `route_scoreboard` reads them for its `state` column. | [05](05-ingest-and-routing.md) §8.2 | — |
| `route_unit_decision` | table | The `(unit_uri, unit_part, lane, decision_id)` join that survives a `work` row's deletion, so cost provenance outlives the queue. | [15](15-observability.md) §5.2 | — |
| `RouteDecision` | type | What one `(part, lane, rung)` decided **before anything ran**: the eight identity columns of `route_decision_identity`, every one an input, so nothing about *when* it was decided appears; the winning rule's `rule_id`, `rule_origin`, `driver`, `escalate_to`, `terminal`, `outcome`, `failure_class`, `cause`, `reason`, `slice_key`, `pinned`, `flagged_blocks` and its `Degradation` **set**; and the four fields `price()` fills — `cost_class`, `est_spend`, `est_micros`, `reserved_micros`. `decision_id()` is **derived**, which is what makes the insert idempotent under concurrency. `audit_selected`, `grant_id`, `admission` and `decided_at` are the table's columns and deliberately not this type's. | [05](05-ingest-and-routing.md) §4.6 | — |
| `RouteError` | type | The `OW-R-*` member: a policy that will not load, will not lint, or names a key absent from the `SignalSpec` registry. | [02](02-architecture.md) §7.2 | — |
| `RouteHints` | type | The typed shape of a request-layer route hint. It may restrict lane, maximum rung, preferred capability and deadline. **It has no budget, egress or licence field and therefore cannot widen anything.** | [05](05-ingest-and-routing.md) §4.6 | `Narrowing` (for request hints) |
| `RoutePolicy` | concept | The merged, compiled, frozen, content-addressed form of the six policy layers. Its `policy_digest` enters every decision row. | [05](05-ingest-and-routing.md) §4.1 | — |
| Rule | concept | One `[[rule]]` in a policy layer: an id, a Rung, an optional Lane, a `when` predicate of **closed comparison clauses**, a `then` action, and — if it reads a nullable key — a **required** `on_unknown`. | [05](05-ingest-and-routing.md) §4.2 | — |
| `RuleCtx` | proto | What one rule may see: the parsed `CarrierDoc` and `Unit` (both `None` for a document-scope rule), the `Plan`, the `ConstructTable`, the `Brief`, the `DocIndex`, the `CiteResolver`, the occurrence `limits`, and `measure()` whose `None` return is a recorded skip and never a pass. | [09](09-generation.md) §4.4 | — |
| RulePack | concept | A Target's rules: **one function per file, one test per file**, signature `(RuleCtx) -> Iterable[Finding]`, ordered by an integer phase where phase 0 is the carrier parse and short-circuits. Not a 9,000-line class. | [09](09-generation.md) §4.4 | — |
| `RuleSpec` | type | One OUT rule's registration: id, integer phase (0 is the carrier parse and short-circuits), scope, the set of **code symbols** it may emit (the meta-gate checks both ways), its required `fn`, and the `needs` set whose unmet members make the gate `unverified` rather than `passed`. | [09](09-generation.md) §4.4 | — |
| Run | concept | (L3) One execution of one Pass over one Segment; a `derive_run` row. | [08](08-runtime.md) §1.2 | — |
| `run` | table | One execution: a monotonic integer generation (**never a clock**), a trigger from six values, argv, the full config digest **and** the narrow semantic digest, four more digests, versions, the full-scan latch, the dropped-event count and a status. | [08](08-runtime.md) §1.2 | — |
| Run manifest | concept | The incrementally-written reporting artefact at `{output_root}/runs/{run_id}.json`: counts, failures by class, cache statistics, `cost.would_have_been_micros_if_uncached`, per-phase timings and `degradations[]`. **Not a log.** | [08](08-runtime.md) §1.2 | — |
| `RunContext` | type | The **operator's** only channel to the outside: identity, six digests, `Limits`, `Admission`, `ServiceRegistry`, `BudgetLedger`, `CancelToken`, `Clock`, `TraceSink`, `service()`. | [08](08-runtime.md) §1.3 | — |
| `Rung` | enum | One position on the escalation ladder: `GATE < DECODE < REPAIR < PAGE < REGEN < DEGRADE < ENRICH`. It says **how far down the escalation we are, never what it costs** — which is why `DEGRADE` is a forward move even though it runs a cheap driver. | [05](05-ingest-and-routing.md) §Part 3 | `tier 0`…`tier 3`, `tier S`, an upper-case wire value |
| `rung_ceiling` | member | A new `Degradation.kind`: a part that would have escalated past `--max-rung`. Distinct from `pin`. | [05](05-ingest-and-routing.md) §7.3 | — |
| `RunManifest` | type | What `run(scope, ctx)` returns and what `omniweave.run.manifest` writes: the run's counters, to `{output_root}/runs/{run_id}.json` plus `omniweave.index.lock`, one sorted timestamp-free line per document at ~200 B. Never spelled `manifest`, which §3 rejects for a DriverCard. | [02](02-architecture.md) §4.1 | — |
| `Runner` | concept | A competitor adapter in `eval/runners/`, one file per comparator, **in-tree and unpackaged** so a heavy comparator's dependencies never reach `G2`'s weight gate. | [13](13-quality.md) §8.7 | — |
| Runner class pin | concept | The CI runner label recorded in the workflow beside the per-OS baseline it calibrated, so a runner-image change surfaces as one deliberate re-bless in `eval/BLESS.log` rather than as nine unexplained G10/G26 failures. | [11](11-repo-layout.md) §6.4 | — |
| `SAFE_XML` | const | The one permitted XML parser configuration: `resolve_entities=False`, `huge_tree=False`, `no_network=True`, `load_dtd=False`, `dtd_validation=False`, `recover=False`. | [14](14-security.md) §2.5 | — |
| **`sanitize_label()`** | fn | The five-step transform (§9.2) every stored string passes through before it re-enters a prompt or an MCP response. NFC, drop `Cf`/`Cc`, map `<` and `\|` to their fullwidth forms, collapse whitespace, truncate to 200 chars. | [06](06-structure-extraction.md) §9.2 | — |
| `SCHEMA` | concept | The integer version of the L2 model **and** the store schema, together. Its `[SOR]` tables are a public read contract at a major; `[DER]` objects are explicitly outside that promise. | [11](11-repo-layout.md) §4.1 | — |
| `schema_version` | column | A driver's output-shape/semantics integer. **The only driver version that enters a cache key**, and forgetting to bump it is the most expensive single mistake available in the design. | [04](04-driver-system.md) §5.1 | — |
| `Scope` | type | **The runtime's ingest scope** — roots, globs and a corpus — and the first argument of `run(scope, ctx)` and of `discoverer()`. It is the unit of cancellation, because it is the unit somebody actually withdraws: one `CancelToken` per Scope, never one per work row. L2's block selection, which shared this name, is **`ViewScope`** (ADR-1 decision 7; this one wins on age and on reference count). | [08](08-runtime.md) §1.3 | `Scope` for a block selection — that is `ViewScope` |
| `scorekinds.toml` | file | The **append-only** register of confidence scales, with each one's domain, semantics, declared consumers, eval set, calibration numbers and age. **An unregistered `score_kind` raises at `DocSink.add_block`.** | [06](06-structure-extraction.md) §1.2 | — |
| `SCORER_VERSION` | const | **1** at first release. "0.8 under scorer v1" is measurable; "0.8" is not. One constant, in `omniweave_core.retrieve`. | [07](07-store-and-retrieval.md) §3.3 | — |
| Segment | concept | **The** extraction, embedding, packing and cache unit: a heading-scoped, table-atomic, **zero-overlap**, block-aligned run at a **target** of `SEGMENT_TARGET_TOKENS = 1200`, under a **ceiling** of `MAX_SEGMENT_TOKENS = 2048` and an exact `MAX_SEGMENT_BLOCKS = 512`. | [06](06-structure-extraction.md) §2.6 | `Chunk` |
| `segment` | table | Where Segments live, in `0002_graph.sql`. | [06](06-structure-extraction.md) §2.6 | `chunk` |
| `segment_block` | table | `PRIMARY KEY (block_id)` — **which is what makes overlap unrepresentable** — plus the ordinal within the segment, which is the `cover_bits` bit index. | [07](07-store-and-retrieval.md) §3 | `chunk_block` |
| `segmenter` | table | The identity of a segmenting driver plus its params digest. A digest input, so two segmenters cannot collide. | [06](06-structure-extraction.md) §3.2 | `chunker` |
| `semantic_digest` | concept | The canonical digest of the run config **restricted to keys declared `semantic`**. The only run-config contribution to a cache key. An unclassified key fails CI and is treated as `semantic` — **fail expensive, never wrong**. | [02](02-architecture.md) §2 | — |
| Sequence | concept | A contiguous run of parts bound to **one driver session**, priced by the cost card's `per_session` versus `per_part` split so the planner can *see* the amortisation before choosing. | [08](08-runtime.md) §2.3 | — |
| `SERIALIZER_CAPS` | const | The core-owned map from serializer format to whether it emits a `SpanMap`. **The owner of that fact**, because `serialize()` is core's function over core's five formats and a parse driver never calls it. | [03](03-document-model.md) §2.4 | `spanmap` as a `Capabilities` field or card key |
| `serve_baseline` | table | The counterfactual half of token accounting, in `events.owstore`, one row per `serve_emission` row: how many characters the documents an Answer drew from hold in total, which baseline kind that represents (`read_whole_doc` / `read_page_window` / `unknown`), and the `chars_per_token` divisor **recorded at write time**. | [10](10-interfaces.md) §12.2 | — |
| `serve_emission` | table | The per-session emission ledger's persisted rollup, in `events.owstore`. **Local only, never egressed.** | [10](10-interfaces.md) §12.2 | — |
| `serves` | column | `SignalSpec`'s new per-provider format list. Overlapping claims for one `(key, format)` are `OW-P-022` at startup — not `OW-P-021`, which lint check 13 carries. | [05](05-ingest-and-routing.md) §The container budget and the recursion limit | — |
| Service | concept | A host-managed shared model server, **named and never routed**, one per `(name, config_digest)`, reached through `ctx.service(name)` and `DriverIO.service(name)`. | [08](08-runtime.md) §3.1 | — |
| Service capacity | concept | `min(server-reported concurrency, MAX_AUTO_PARALLEL = 96, the operator ceiling)`. | [08](08-runtime.md) §3.4 | — |
| `service_observation` | table | Per-`(run_id, name, config_digest)` Service operability: lifecycle, capacity, peak in-flight, requests, units, GPU time, health failures, cold-start and queue percentiles, **and the server's own log tail on a failure**. | [15](15-observability.md) §5.2 | — |
| `ServiceHandle` | type | What `ctx.service(name)` and `DriverIO.service(name)` return: a base URL, a 32-byte `os.urandom` token, the verified model id and revision, capacity, a `traceparent` and a deadline. | [08](08-runtime.md) §3.2 | `Resource` |
| `ServiceRegistry` | type | The per-run Service table on `RunContext`: `live()`, `handle()`, `evict()`, `observe()`. **Blocking** attach-or-spawn; the async part is the Supervisor's `service_refill` task. Never a module global and never a process singleton. | [08](08-runtime.md) §3.2 | — |
| `ServiceSpec` | type | One `[services.<name>]` block, frozen: model id and exact revision (both **semantic**), endpoint, autostart, capacity, `batch_wait_ms`, `max_batch`, `keep_alive_s`, two 600 s timeouts, `vram_floor_mb`, `server_argv` and `gpu_group`. | [08](08-runtime.md) §3.2 | — |
| `Severity` | enum | `error \| warning \| info`. Decides whether a Finding **blocks**. Orthogonal to `Provenance`. | [09](09-generation.md) §4.1 | `FindingProvenance`, `blocking` as a provenance |
| `sha256-bundle-1` | const | The named skill-bundle digest algorithm: full-path-sorted walk, each file contributing `relpath\0` then its bytes then `\0`, with CRLF→LF applied to `TEXT_EXT` members only, `.DS_Store` and `__pycache__` skipped, emitted as the full 64-hex sha256. | [10](10-interfaces.md) §5.5 | — |
| Signal | concept | One named, typed, scoped, cost-classed observation about a unit, part, block or document, produced by a registered provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `signals.lock` | file | The committed artefact `ow conform --bench` writes: the measured p50 per `SignalSpec.est`, on named hardware. | [05](05-ingest-and-routing.md) §5.1 | — |
| `signals.toml` | file | A signal provider's `SignalSpec` rows, as data, including `serves` — the format tokens this provider answers a key for (§5.2). | [05](05-ingest-and-routing.md) §4.5 | — |
| `SignalSpec` | type | A Signal's registration: key, scope, kind, dtype, **`domain` (inclusive on both ends for a float pair; a `frozenset[str]` for a `str` dtype, which is what `ow route lint` checks a rule's literals against)**, cost class, its own estimated cost as a `Spend` and never a scalar ms, the **singular** `provider` entry-point name, the provider `version` that enters the read set, `serves`, `requires` and `nullable`. `domain`, `nullable` and `requires` are what `ow route lint` checks 2, 4 and 7 read, which is why the registration is data rather than a decorator. | [05](05-ingest-and-routing.md) §5.1 | — |
| `size_at_last_full_backfill` | column | The WAL baseline on `store.wal_valve`, refreshed whenever a checkpoint reports everything backfilled. | [15](15-observability.md) §4.2 | — |
| **Skeleton marker** | concept | The `# OW-SKELETON: <phase>` comment on every deliberate fake in M0, naming the phase that **deletes** it. The semgrep rule `skeleton-marker-survived` fails the build on any marker present after the P4 exit. Skeleton code is deleted, never grown. | [16](16-roadmap.md) §2.2 | — |
| `skills-lock.json` | file | `$OMNIWEAVE_HOME/skills-lock.json` — the skill lockfile. | [10](10-interfaces.md) §5.5 | — |
| Slice | concept | The accounting bucket for quality and cost: a **pure function of Evidence**, declared in the policy and capped by `max_slices`. **Quality is always per Slice, never per driver.** | [13](13-quality.md) §8.3 | — |
| `Snapshot` | type | **One** `BEGIN DEFERRED` read transaction held for a whole retrieval call — every channel, hydration and the coverage scan. | [07](07-store-and-retrieval.md) §10.4 | — |
| `SNIFF_MEMBER_BYTES` | const | `65_536` and `8` — the most of any one archive member, and the most members, that format detection may read. Detection never decompresses a whole part; it gets its own budget, orders of magnitude below the parse budget. | [14](14-security.md) §2.4 | — |
| `SNIFF_MEMBERS` | const | `65_536` and `8` — the most of any one archive member, and the most members, that format detection may read. Detection never decompresses a whole part; it gets its own budget, orders of magnitude below the parse budget. | [14](14-security.md) §2.4 | — |
| `source_reread_rate` | concept | The fraction of `bench/serve/` harness tasks in which the scripted agent opens an **indexed** source file with a host tool (`Read`, `Grep`, a shell `cat`) *after* an `ow_query` or `ow_open` in the same task. | [00](00-vision.md) §10 | — |
| `SourceKind` | enum | `file \| dir \| url \| crawl \| connector \| stream` — the six acquisition source kinds. | [05](05-ingest-and-routing.md) §1.1 | — |
| `SourceLocator` | type | The frozen **host-side** input to acquisition: kind, ref, globs, depth, trust class, cursor floor. Built by `ow add` and `resolve_locator()`, it is the only type crossing the user-string-to-read boundary; the host projects it onto a ports-level `Locator` per invocation and a driver never sees one. | [05](05-ingest-and-routing.md) §1.1 | passing a `SourceLocator` to a driver |
| `SpanMap` | proto | The lift from a `RenderSpan` back to `(block_id, TextSpan)`, emitted **by the serializer that produced that view**. `serialize()` returns `(text, SpanMap)`. | [03](03-document-model.md) §2.4 | — |
| `Spend` | type | The seven-unit **physical** resource vector `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls, bytes_egress}` plus a provider tag. **Drivers report Spend and never money** (INV-15). | [05](05-ingest-and-routing.md) §6.1 | `usd_per_unit`, `cost_micros` on a driver-facing type |
| `spend_attribution` | view | The one join from `route_unit_decision` through `route_decision` to `route_spend` that makes I30's per-`(unit, part, decision, attempt)` attribution queryable. Per-document, per-corpus and per-driver cost are `GROUP BY`s of it. | [15](15-observability.md) §5.2 | — |
| `Splice` | type | One all-or-nothing text edit over a byte range of `CarrierDoc.source().encode("utf-8")`: `start` inclusive, `end` exclusive, `text` the replacement. A batch applies in descending `start` order and an overlapping batch is rejected before any edit lands. | [09](09-generation.md) §3.1 | — |
| **stability tier** | concept | A component's compatibility promise, one of five: `T-CONTRACT`, `T-SCHEMA`, `T-PUBLIC`, `T-GENERATED`, `T-INTERNAL`. Derived from the three version axes; it says who may depend on a component and which event moves it. | [02](02-architecture.md) §Open questions | — |
| Stage | concept | The pipeline phase a span belongs to, carried as the span attribute `ow.stage` on `plan` and inherited by descendants. | [15](15-observability.md) §2.2 | — |
| `stage_ms` | column | The run manifest's `Stage -> summed elapsed ms` map, with `stage_entries` beside it giving the number of `plan` spans that contributed. **Not `timings_ms`**, which is `doc.timings_ms`: one document's driver-reported parse timings. | [15](15-observability.md) §1 | — |
| Staged generation | concept | `doc.gen + 1`, the generation a document-granularity parse writes into. Readers resolve the committed `doc.gen`; the bump happens **inside** the completing transaction; abandoned generations are swept at startup. | [03](03-document-model.md) §1.1 | — |
| `stall_detector` | fn | The Supervisor task that ends a run at `status='partial'` when the claimable set is non-empty, nothing is claimed, nothing has committed for two `[runtime] stall_poll_ms` cycles and the sweeper returned nothing. | [08](08-runtime.md) §2.5 | — |
| **startup sequence** | concept | The nine ordered steps every `ow` process runs before any work: dispatch, config, limits, digests, surface invariants, store open, catalog freeze, write lock, loop. | [02](02-architecture.md) §5.3 | — |
| `stat` | table | Scalar counts only — `live_blocks`, `live_segments`, `docs`, per-kind counts — with `computed_ns`. **No histograms**, because the narrowing decision is an exact probe. | [07](07-store-and-retrieval.md) §3.11 | — |
| `StepMetrics` | type | The runner-owned metric bundle on a `StepResult`: `queued_ms` **always** separate from `ran_ms`, the physical `Spend`, runner-priced `micros`, `was_cache_hit`, `rows_written`, `peak_rss_bytes`. | [08](08-runtime.md) §1.3 | — |
| `StepResult` | type | What the **runner** produces for a work row, from a `DriverResult` plus everything the driver may not claim. | [08](08-runtime.md) §1.3 | — |
| `Store` | proto | The **queue** boundary: four methods — `claim`, `complete`, `reap_expired_leases`, `counts_by_status` — never widened, and `complete()` is the only mutation entry point. | [07](07-store-and-retrieval.md) §2.2 | — |
| Store key id | concept | `sha256(derived_key)[:8]`, hex. Recorded in the run manifest, by `ow store rekey` and by `ow store key-list`, so a record — including a backup file — can prove which key a store is under without carrying the key. | [14](14-security.md) §6.4 | — |
| Store thread | concept | The **one** thread in a process permitted to hold a `sqlite3.Connection`. Every write reaches it as a transaction closure on a bounded queue. | [07](07-store-and-retrieval.md) §10.1 | — |
| `StoreError` | type | The `OW-S-*` member: a snapshot expiry, a busy writer, a `MIN_SQLITE` floor breach, an open bulk-window marker, a tracked `.owstore`, a second concurrent `run()` in one process. | [02](02-architecture.md) §7.2 | — |
| `StreamHint` | type | What the host knows before any sniffer looks, four fields and no more: `(filename, extension, declared_media_type, byte_len)`. Declared once in `omniweave_ports`. A hint, never an authority, and it carries **no** `trust_class`: `TrustClass` is [routing](05-ingest-and-routing.md)'s type and `tools/layers.toml` gives `omniweave_ports = []`, so the field would pull routing across the layer boundary G4 closes. | [04](04-driver-system.md) §1.3 | a `trust_class` field |
| `subproc` | member | The default Isolation mode and **the only mode a third party gets**: one long-lived worker per `(driver_id, config_digest)`, run-scoped with a 300 s idle TTL, over `omniweave-driver/1`. | [04](04-driver-system.md) §6.2 | — |
| Supervisor | concept | The single `asyncio` event loop in `omniweave/run/supervisor.py` that claims, admits, dispatches, completes and reaps. | [08](08-runtime.md) §2.6 | — |
| `SurfaceError` | type | The `OW-A-*` member: an ambiguous `cite` across the corpora a session touched, an unlisted tool, an unauthenticated non-loopback bind. | [02](02-architecture.md) §7.2 | — |
| `T-CONTRACT` | member | A stability tier: a third party pins it and builds against it; it moves only on a `CONTRACT` bump, on a `RELEASE` MINOR, announced and migration-guided, with G16 loading the previous two releases' template drivers against HEAD. | [02](02-architecture.md) §2 | — |
| `T-GENERATED` | member | A stability tier: never hand-written, byte-identical to its generator's output, and gated by a `--check` byte diff (G6, G18, G20, G25). Editing one by hand fails the build. | [02](02-architecture.md) §2 | — |
| `T-INTERNAL` | member | A stability tier: no promise. It may change on any `RELEASE` MINOR, and only its own tests constrain it. | [02](02-architecture.md) §2 | — |
| `T-PUBLIC` | member | A stability tier: semver'd with `RELEASE`, documented, and typed in `omniweave/sdk/_generated.pyi`. A MINOR may add; a MAJOR may remove. | [02](02-architecture.md) §2 | — |
| `T-SCHEMA` | member | A stability tier: a published read contract over stored rows or digests; it moves only on a `SCHEMA` major with a two-release deprecation window. `[DER]` objects are outside the promise. | [02](02-architecture.md) §2 | — |
| `table.grid_score` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `table_meta` | table | A table Block's shape: rows, columns, an **explicit** ragged `row_len` array, header counts, `data`-vs-`layout` kind, the reconstruction strategy and its **kept** score, a `has_merges` bit that means `grid_slot` is empty, and the hash-pinned native part for passthrough export. | [03](03-document-model.md) §10.1 | — |
| `Taint` | enum | A five-bit `IntFlag` recording that an item derives from an untrusted source, a defanged chat-template sentinel, hidden text, off-page geometry, or a single-witness cross-document assertion. | [14](14-security.md) §3.2 | — |
| Target | concept | An artefact kind (`pptx`, `deck`, `docx`, `video`). Named in `[targets] enabled`, aliased in the `omniweave.targets` group, and implemented by **exactly two Drivers**: one `compile/1` and one `parse/1`. | [09](09-generation.md) §12 | — |
| `Target generation` | concept | `g_t = doc.gen + 1`, the generation a parse writes into. Rows at `g_t` are durable and invisible until `end_doc()` bumps `doc.gen`; `gen = 0` means no committed generation. The L2 face of the charter's staged generation. | [03](03-document-model.md) §1.1 | — |
| `TargetError` | type | The `OW-T-*` member: an OUT construct or gate failure that must abort rather than record a `Finding`. | [02](02-architecture.md) §7.2 | — |
| `TextBatch` | type | The `embed/1` input: a `texts` tuple and a `role ∈ {document, query}` that gates the asymmetric instruction prefix where a card declares one. | [04](04-driver-system.md) §1.3 | — |
| `TextMeasure` | proto | The single text-measurement estimator a target supplies, exposing exactly one method — `box(n: CarrierNode) -> Box \| None` — and reached by **both** `rules/` (through the `RuleCtx.measure()` wrapper) and `lower/` (through the target's own `measure()` accessor over a node it parsed itself). A `None` from `CompileV1.measure()` makes every rule declaring `needs={"measure"}` a recorded skip and the gate `unverified`; a `None` from `box()` makes that one node a recorded skip. | [09](09-generation.md) §4.4 | — |
| `TextSpan` | type | A character range inside **one Block's own `text`**. This is what a `ProvenanceItem.charspan` actually is, and it is what makes sub-block bbox attribution and L3 entity spans possible. | [03](03-document-model.md) §7.4 | — |
| **the ladder** | concept | The ordering `A > S > L > G > X > R` and its three rules (§"The enforcement classes"). Cited as "the ladder" in a review comment. | [01](01-principles.md) §The enforcement classes | — |
| **the ten questions** | concept | The ordered reviewer sequence in §4.2, covering what CI cannot answer. | [01](01-principles.md) §4.2 | — |
| Three roots | concept | `source_root`, `output_root`, `cache_root`, **always separate**. A `cache_root` inside `source_root` is a startup error. | [08](08-runtime.md) §1.3 | — |
| `timing_basis` | column | `in_process \| spawn_inclusive \| server_attached`, required per Runner. **Two rows with different bases may never share a column.** | [12](12-performance.md) §1.1 | — |
| **`TmpRef`** | type | `NewType("TmpRef", str)`: a per-invocation draft-local reference (`'e1'`) by which a Pass names its own proposed entities. Never persisted, never a `cite`, never an id. A `TmpRef` referenced but never defined quarantines the Segment. | [06](06-structure-extraction.md) §1.7 | — |
| Tombstone | concept | A **framework-shipped** card for a forbidden or removed DriverId that resolves to a quoted reason and a named replacement instead of "unknown driver". Carries a `review_by` date, and CI fails a tombstone past it. | [04](04-driver-system.md) §7 | — |
| Toolchain | concept | A digest-pinned, non-Python execution bundle (Node plus a compiled JS app) invoked as a **one-shot** child process through `omniweave_core.toolchain.run`. | [02](02-architecture.md) §1.2 | — |
| `ToolchainResult` | type | One Toolchain invocation's outcome: the same `Outcome` enum as `StepResult` (no magic values), the validated receipt, a bounded stderr ring tail, and `queued_ms` **always** separate from `ran_ms`. | [02](02-architecture.md) §1.2 | — |
| `ToolchainSpec` | type | A Toolchain's identity: name, version, the **full** sha256 (a 16-hex prefix is 64 bits and weak against intent), the entry argv, and a Node version range. | [02](02-architecture.md) §1.2 | — |
| `tools/gates.toml` | file | The G-series register: one row per numbered CI gate with its assertion, its implementing script or job step, its owner, its review date, its job, its budget in seconds and its nightly/release schedule, plus the `[[job_assertion]]` rows. | [11](11-repo-layout.md) §1.7 | — |
| `tools/invariants.toml` | file | The machine-readable invariant register (§1e): one `[[inv]]` per invariant, carrying its force, owning document, enforcer ids, classes and independent-enforcer count. Read by `G27(d)`. | [01](01-principles.md) §1 | — |
| `tools/metrics.toml` | file | The generated, byte-diff-gated metric registry: one row per metric with `name`, `type`, `unit`, `labels`, an optional `buckets` ladder, and a declared `source` (an event `kind`, a SQL expression, or a column for a histogram). | [15](15-observability.md) §4.1 | — |
| `tools/redact.toml` | file | The credential- and marker-shape register `redact()` reads: `Authorization` values, prefixed tokens, JWTs, long hex runs with a closed `exempt_fields` list, `<ow:untrusted>` markers and chat-template sentinels. Patterns are TOML literal strings. | [15](15-observability.md) §8.3 | — |
| `tools/risks.toml` | file | The machine-readable risk register: one `[[risk]]` per row carrying `id`, `category`, `title`, `likelihood`, `impact`, `owner`, `indicator`, `trigger`, `mitigation`, `contingency`, an optional `kill`, a `paths` array, a `questions` array, `reviewed_at` and `review_by`. | [17](17-risks.md) §1 | — |
| `tools/threats.toml` | file | The machine-readable threat register: one `[[threat]]` per vector, `{id, boundary, vector, adversary, mitigation_fn, limit, test_id, residual}`. | [14](14-security.md) §1.5 | — |
| `tools/toolchains.toml` | file | The Toolchain register, in two tables. | [11](11-repo-layout.md) §1.7 | — |
| `TraceSink` | proto | An event consumer. `emit` **must not block** — a bounded 64k drop-oldest queue — and the drop count is counted into `run.events_dropped` and into `degradations[]`, never a log line. | [15](15-observability.md) §3.2 | — |
| **`truncations`** | concept | *(coined here)* The `OutReport` and `Receipt` record of every place the validator stopped short: a rule past `MAX_FINDINGS_PER_RULE`, or a report past `MAX_FOLDED_FINDINGS` that re-folded. | [09](09-generation.md) §2 | — |
| `Trust` | enum | An **ordered INTEGER**: `AMBIGUOUS = 0 < INFERRED = 1 < EXTRACTED = 2`, with ambiguous lowest **so `MIN()` over a segment is the segment's trust**. Absent ⇒ ambiguous, and counted. Clamped by `MAX_TRUST_BY_METHOD` after the driver returns. | [03](03-document-model.md) §8.2 | — |
| `TrustClass` | enum | `internal \| untrusted_external` — the enum behind `unit.trust_class`. Not `TrustTier`, not `Trust`. | [05](05-ingest-and-routing.md) §1.1 | — |
| `TrustTier` | enum | `first_party \| vendored \| pinned \| local \| unpinned`. Gates whether `inproc` is representable and whether a driver activates under `require_lock`. | [04](04-driver-system.md) §4.2 | — |
| `TruthKind` | enum | The provenance of a metric's reference: `human \| rendered \| native_run \| synth_ocr \| agreement \| self`. `native_run` is admissible for **fidelity metrics only**; `agreement` and `self` may **never** populate an accuracy column. | [13](13-quality.md) §13.6 | — |
| `unit` | table | The Roster. Also carries the stat triple and `content_sha256`, so there is one freshness source and one source-bytes digest. | [05](05-ingest-and-routing.md) §1.1 | `unit_stat` |
| `unit.format_basis` | signal | Eight additions to the charter's day-one registry, all FREE, each with a named provider. | [05](05-ingest-and-routing.md) §5.1 | — |
| `unit_part` | column | The part identifier on a work row and a decision: `TEXT NOT NULL DEFAULT ''`, where the empty string folds what prose calls NULL, because **NULLs are distinct in a UNIQUE index**. | [05](05-ingest-and-routing.md) §1.2 | — |
| `unit_salt()` | fn | The `content.salt` input to `cache_key()`: for `fs`, the **walked** path relative to `roots.source`, POSIX-separated; for any other connector, `'<connector>/<locator>'`. | [08](08-runtime.md) §4.2 | — |
| `UnitCandidate` | type | The `{"t":"candidate"}` record shape of `owroster-items/1`: a per-invocation `tmp` id, the connector-local `id` the host feeds to `canonical_uri()`, `connector`, `next_cursor`, size, mtime, etag, media-type hint and labels. Metadata only — never bytes, never a `unit_uri`, never a `trust_class`. | [05](05-ingest-and-routing.md) §1.1 | — |
| `UnitKey` | type | `(unit_uri, unit_part)` — the pair that keys the pending set, the cache write allowlist and the per-part retry semaphore. Not a `UnitRef`, which additionally carries `content_sha256`, the connector and the walked path. | [08](08-runtime.md) §5.4 | — |
| `UnitOutcome` | enum | `native \| baked \| passthrough \| cloned_passthrough \| patched \| rebuilt \| manual_required`. Every output unit lands in exactly one, the sum is asserted, and **unclassifiable is fatal**. | [09](09-generation.md) §5.5 | — |
| `UnitRef` | type | The host-minted reference a driver is handed for one part: `uri`, `part`, `content_sha256`, `byte_len` and an optional `media_type`. **No `unit_id`, no `doc_ord`, no `block_id`** — the host mints every durable identity (§5 X1). | [04](04-driver-system.md) §1.3 | — |
| `UNTRUSTED_FRAME_CHARS` | const | `200` — the **worst-case** per-block character overhead of the `<ow:untrusted>` frame (§3.2's arithmetic), counted in the Answer budget so the security wrapper cannot silently overrun the context window on a corpus with long names. | [14](14-security.md) §3.2 | — |
| `vec` sidecar | concept | `index.vec.owstore`, ATTACHed as `vec`. | [07](07-store-and-retrieval.md) §3.9 | — |
| `vec_manifest` | table | The `vec` sidecar's own scalar state: corpus id (a mismatch means the sidecar is **ignored, not read**), schema, `model_key`, backend and version, storage, signature width, dimension, build time and row count. | [07](07-store-and-retrieval.md) §3.9 | — |
| `VecManifest` | type | The `vec` sidecar's identity, read at attach: `corpus_id` (a mismatch means the sidecar is **ignored, not read**), schema, `model_key`, backend and version, storage class, signature width, dimension, build time, row count, and the `pushdown` bit that decides whether `candidates` narrows before ranking. | [07](07-store-and-retrieval.md) §16 | — |
| `VectorBackend` | proto | The ANN seam: `manifest`, `upsert`, `search` (with a `candidates` set that must narrow **before** ranking), `sweep`. | [07](07-store-and-retrieval.md) §1.1 | — |
| `verbatim` | member | See `Quote`. The tier serve may call byte-exact, and only with a retained part plus a proved span (INV-10). `span_exact_rate` is a **hard gate at 1.000**, not a metric. | [03](03-document-model.md) §8.3 | — |
| `Verdict` | type | **The retrieval honesty record**, defined once in `omniweave_core.retrieve.verdict` and constructed only by `build_verdict()`: twenty-two fields — a four-state `ok \| low_confidence \| absent \| degraded`, the gates that **failed** with one `DegradeCause` each, the four-key `scanned` map, the best score and the ceiling, confidence, the scorer version, `plan_digest`, per-channel status, freshness, coverage, withheld counts, `matches_before_packing`, the space identity, the snapshot generation, the federation facts and `fusion_kind`, `did_you_mean`, and the two charter-additive fields `generated_share` and `degradations`. | [07](07-store-and-retrieval.md) §6.7 | `route_verdict`, `Verdict` reused for a cache read |
| `VerdictState` | enum | `ok \| low_confidence \| absent \| degraded`. The single most load-bearing enum in the retrieval layer: its one `ABSENT` return site **is** INV-11's and SV8's mechanism, and semgrep asserts there is exactly one. | [07](07-store-and-retrieval.md) §6.7 | — |
| `vfull` | table | Full f32 vectors, `storage = 'sig_full'` only, for an exact rerank of the top `RERANK_N`. | [07](07-store-and-retrieval.md) §3.9 | — |
| `ViewScope` | type | The block selection a projection runs over: a document, a page range, a subtree under one `BlockId`, a Segment, or an explicit `tuple[BlockId, ...]` from a retrieval result. It resolves to an ordered, duplicate-free block sequence and carries the corpus and the generation it was resolved at; `serialize()` and `project_schema()` take it. Renamed from `Scope` by ADR-1 decision 7, because charter D6's runtime `Scope` is older and more widely referenced. | [03](03-document-model.md) §16.1 | `Scope` (for a block selection) |
| Volatility tier | concept | A Reduction's CI treatment. **`frozen`** — a byte diff fails the build. **`tracked`** — a diff renders into a PR comment and merges only with a blessed reason. | [13](13-quality.md) §4.4 | — |
| `vpending` | table | The re-embed set, **materialised** so it is a scan rather than an anti-join. | [07](07-store-and-retrieval.md) §3.9 | — |
| `vseg` | table | **Contiguous segments** of signatures, never a row per vector — a row-per-vector layout costs 2.3× a segment layout in pure SQLite cursor overhead. | [07](07-store-and-retrieval.md) §3.9 | — |
| `wal_baseline_bytes` | column | The `index_state` key holding the WAL size at the last **confirmed-complete** backfill. | [07](07-store-and-retrieval.md) §3.8 | — |
| Water mark | concept | The `queue_high_water` / `queue_low_water` **hysteresis** on claimable rows at which expansion and discovery pause and resume. Backpressure pauses the producer at a safe boundary and **never drops work**. Never one threshold. | [08](08-runtime.md) §2.2 | `wave`, a checkpoint file, a step number |
| Weight ceiling | concept | The per-distribution installed-size limit in `tools/weights.toml`, measured from `RECORD` in a fresh environment, with an aggregate limit of 250 MB for `omniweave[recommended]`. | [11](11-repo-layout.md) §2.5 | — |
| `wire.py` | module | Framing only for `omniweave-driver/1` (~80 lines): two length prefixes, a JSON header, a raw body, and caps on header size, body size and JSON depth. **Named `wire.py`, not `frames.py`**, because a Frame is a run of Blocks. | [02](02-architecture.md) §1.2 | `frames.py` |
| Witness | concept | **Who produced a number** — `ci` (omniweave's own workflow on the published corpus), `self` (the subject's author), `third_party`. **Only `ci` rows are ranked.** The single name for the concept; there is no "provenance class". | [08](08-runtime.md) §5.6 | — |
| Witness set | concept | A closed artifact kind a `derive` driver may **produce**, listing the foreign `(unit_uri, unit_part, token)` tuples each produced item consulted. **The only way a driver contributes deps**, since it never touches the store. | [08](08-runtime.md) §5.6 | — |
| `work` | table | The queue. One row per `(unit_uri, unit_part, operator, op_version)` — **the unit of scheduling, claiming, accounting, retry and failure, and identical to the routing decision grain.** `op_version` is an INTEGER. | [08](08-runtime.md) §5.5 | — |
| `work_done` | table | The compaction archive, preserving **exactly** the two consumers of a `done` row: resume, and the shrink guard's baseline. ~90 B/row against `work`'s ~250 B. | [08](08-runtime.md) §1.1 | — |
| `WorkRow` | type | One claimed `work` row as returned by `Store.claim()`, carrying `claimed_gen` — which is what the commit predicate compares, and therefore what makes a superseded result write nothing. | [08](08-runtime.md) §9.2 | — |
| `WorkSpec` | type | What `Operator.plan()` emits: the tuple from which a `work` row's identity, `cache_key`, `dispatch_key` and `priority` are derived. | [08](08-runtime.md) §6.1 | — |
| Worth | concept | The **second** score in answer packing, distinct from relevance: it penalises **byte share** by layer, kind, trust and quote tier, so a page footer cannot buy 4,500 characters. | [10](10-interfaces.md) §3.5 | — |
| **Wrap verdict** | concept | The recorded build-versus-wrap decision for one external component, drawn from the closed set `depend \| wrap \| vendor \| reimplement \| reject`, carrying its reason and its exit strategy. | [16](16-roadmap.md) §16 | — |
| `writer_id` | column | `sha256(host ‖ pid ‖ process_create_time)[:12]`, the same triple `work.claimed_by` carries. | [15](15-observability.md) §1.1 | — |
| `x.ow.unknown` | cfg | The framework-reserved extension key under which a reader preserves wire keys it does not recognise, so `export(import(a)) == a` survives a version skew. The `ow` vendor segment is the framework's; no third party may write here. | [03](03-document-model.md) §15.2 | — |
| `xml_safe.py` | file | The single XML-parser factory module inside each distribution that parses XML, holding `SAFE_XML` and any named, docstring-justified relaxation. | [14](14-security.md) §2.5 | — |

## Open questions

**Q1 — `ow_segment_head` has no owning document.**
**Closed by [ADR-1](adr/0001-terminology-lock-bulk-pass.md) decision 1.** The view is declared in the
charter's L3 DDL (`CREATE VIEW ow_segment_head AS SELECT s.* FROM segment s JOIN doc d USING
(doc_ord)` …) and the lock carries a §2 row for it, but it appeared in **none** of the nineteen plan
documents — the lock's own CI rule 2, a locked name nothing uses being a concept that was renamed and
left behind. An earlier draft of [07](07-store-and-retrieval.md) carried the DDL (it survives in
`_notes/.snapshots/s5-round3/07-store-and-retrieval.md:475`) and the final revision dropped it while
keeping `ow_block_head`. Of the two closers this question offered, decision 1 takes the first: the
DDL **returns to [07](07-store-and-retrieval.md) §3** beside `segment` and `segment_block`, and
neither the §2 row nor the charter DDL is deleted. That is the correct half —
[06](06-structure-extraction.md) §2 states that Segment consumers read the head generation, which is
exactly what the view is for, and `ow_entity_head` was coined ([06](06-structure-extraction.md)) "to
parallel `ow_block_head`", so three head views exist and all three are written once the 07 edit
lands. `ow_segment_head` therefore drops out of the orphan-term set below.

**Q2 — `eval_calibration` is named only in a migration inventory.** [16](16-roadmap.md) §3.3 lists
it among `0006_eval.sql`'s tables and nothing else specifies it. [13](13-quality.md) §9 owns
confidence calibration and specifies the isotonic fitter, the two tests and the kill conditions, but
never names the table its results land in. *Closed by:* [13](13-quality.md) §9 gaining the DDL, or
the roadmap row dropping the name.

**Q3 — the fifteen absence gates have no normative table in any plan document.** The charter's
"The Verdict — fifteen absence gates, one citability rule" is the specification;
[07](07-store-and-retrieval.md) cites gates 1, 9, 10, 11, 14 and 15 individually and prints the full
fifteen-line pass list inside a **worked example** (§6.6). The index therefore points at §6.6, which
is an illustration and not a contract. *Closed by:* [07](07-store-and-retrieval.md) §6 gaining the
precedence-ordered fifteen-row table, since [13](13-quality.md)'s `Injector` set is defined as "one
per `Diag` code in `ABSENCE_BLOCKING_DIAGS`" and thirteen Injectors cannot be checked against
fifteen gates that live only in the charter.

**Q4 — the lock's Kind vocabulary declares two kinds nothing uses and lacks two it needs.**
**Closed by ADR-1 decision 3.** The lock's Kind list now adds `signal` and `driver-id`, drops `gate`
(`tools/gates.toml` is the G-series' register, so a lock row would be a second home), and keeps
`index`, which earns three rows — `block_cite`, `edge_bound` and `cache_gc`, the three names §1's
`<table>_<purpose>` convention already cited. Residual: no §2 row is a bare `pkg`, and `edge_bound`
is specified by the charter's L3 DDL and by no plan document, which is a rule-2 finding recorded in
the `Specified in` column as `**none**`.

**Q5 — the §3 mechanical check needs a fourteen-entry allowlist or it fails on correct text.**
**Superseded by ADR-1 decision 5**, which restructured §3 into `token` / `sense` /
`bannable_by_name` so that "rejected *in this sense*" is representable at all, and rewrote check 3
as the conjunction of this question's "inside a code span" clause and `12#D1`'s negation-marker
clause, with `tools/lock_allow.toml` as a ratcheted per-line residual. The observation below is what
that decision was built on, and the two real hits it names still want fixing. Fourteen left-column
entries in the old §3 were either ordinary English words or correct in another sense:
`Node`, `Element`, `Item`, `Span`, `edge`, `parse`, `derive`, `manifest`, `norm`, `skip`, `blocking`,
`defines`, `Layer`, `Verdict`. A literal implementation of rule 3 flags
[00](00-vision.md):715 (`V01-14` contains "Node"), [06](06-structure-extraction.md):1904 ("Item
budgets"), [07](07-store-and-retrieval.md):1522 ("rather than the norm") and about thirty more, all
correct. *Closed by:* the check matching only a whole-token occurrence **inside backticks** and
carrying an explicit `[allow]` table in `tools/` for the fourteen; two real hits survive that
narrowing and want fixing — `chunker` at [03](03-document-model.md):2032 (prose, should read
"segmenter") and the quoted `Chunk` at [18](18-api-sketch.md):840 (deliberate, and the reason the
allowlist is per-line rather than per-name).

**Q6 — five identifier series collide and the resolution above is not yet applied.** The
[Collisions](#collisions-resolved) table names the winners; the five documents still write the losing
prefixes. This is the same defect class the lock's §3 X32 closed for `S1`-`S20` by splitting it into
`ST`/`SV`/`GR`, and it wants the same mechanical treatment: one row per prefix in
`tools/invariants.toml` with its owning document, and a G27(d) clause asserting that a prefix
resolves to exactly one series. Until that lands, "R2" in a review comment is ambiguous between a
round-trip law and an observability runbook. *Closed by:* the rename plus the G27(d) clause.

**Q7 — nine locked concept names are capitalised in the lock and lower-case in every document.**
`Construct`, `Cohort`, `Roster`, `Witness`, `Residue`, `Assertion`, `Service capacity`,
`Volatility tier` and `Weight ceiling` each appear once or twice in their capitalised form and
between 25 and 160 times lower-case ("cohort" 25, "roster" 160, "witness" 60, "construct" 97). This
glossary treats the lower-case prose form as the same term and keeps the lock's capitalisation as
the citable form. It is recorded rather than fixed because the alternative — capitalising a common
noun mid-sentence 160 times — is worse prose for no gain. *Closed by:* a lock note saying the
capitalised form is the citable form and the lower-case form is ordinary prose, so rule 2's
"appears in at least one document" is satisfied by either.

**Q8 — `Answer section` is specified where the phrase never appears.** The concept — the fixed
`**ow:<name>**`-marked regions, their order, and the whole-section drop rule — is
[10](10-interfaces.md) §3.5, which writes "sections" throughout. The locked two-word phrase
`Answer section` appears exactly once in the nineteen documents, in [16](16-roadmap.md) §10. The
index points at [10](10-interfaces.md) §3.5, which is where the mechanism is. *Closed by:* one
sentence in [10](10-interfaces.md) §3.5 using the locked phrase, so the name check finds it where
the specification is.

**Q9 — five lock terms are specified only by a DDL comment or a single table row.** `Cohort`,
`cohort_member`, `Service capacity`, `ow_ref_resolved` and `vfull` each occur once or twice, always
inside a DDL block or a single table cell. They are specified — the charter's DDL is normative — but
no plan document explains them in prose, so the index's section reference is thinner than every
other row's. *Closed by:* deciding, per term, whether it is load-bearing enough to earn a paragraph;
`Cohort` is (it is the unit `restriction_bits` propagates over), and `vfull` probably is not (it is
one of four sidecar tables [07](07-store-and-retrieval.md) §3.9 describes as a set).

**Q10 — five lock §2 entries have no row in the index.** **Closed by ADR-1.** The five were `Basis`
and `RankedGuess` (the `Literal` and the dataclass printed at [05](05-ingest-and-routing.md) §2.1),
`format_tokens` and `FormatTokenPair` (the sixteenth `[capability.parse]` key and its member shape at
[04](04-driver-system.md) §2.2) and `ground()` (the back-map function at
[06](06-structure-extraction.md) §1.7). None was an orphan term, so none was a rule-2 violation; all
five now carry index rows at those sections. The pass that added them also merged the 313 New-terms
rows into the lock and authored 24 more, so the lock read **744** rather than the 720 this
question predicted: 720 was 407 + 313 and did not budget for the names the register itemises that no
document offers (`02#1`'s thirteen, `04#Q3`'s eleven, `13#Q-Q4`'s `CalStatus`, decision 7's
`ViewScope`, and decision 3's three `index` rows). The pass left exactly one residual — ADR-5's
`nfc()` was indexed here and had no lock row, so this index read **745** against 744, a rule-1
finding against the lock rather than against this document. That row has since been written into §2,
and both now read **745**. `InstallReport`, named in
[02](02-architecture.md)'s own list of the thirty-six, is specified by **no** document and **not** by
the charter, and was therefore not authored — see [17](17-risks.md)'s `02#1` row.

## New terms

Two, both about this document's own mechanism, offered for merge into
[`_notes/terminology.md`](_notes/terminology.md) §2.

| Term | Kind | Definition |
|---|---|---|
| **owning document** | concept | The one plan document that **specifies** a term, as against the documents that merely use it: the document carrying the term's definitional occurrence — a heading naming it, its `class`/`CREATE TABLE`/`def` line, or the table row whose first cell is the term. Exactly one per name. The value of this glossary's `Specified in` column, and the unit `G27(d)`'s register check resolves a name against. |
| **orphan term** | concept | A locked name with no owning document — specified in [the charter](_notes/charter.md) or the lock and used by nothing. A violation of the lock's CI rule 2 and always a finding, because it means a concept was renamed and one spelling was left behind. Two once ADR-1 decision 1 returns `ow_segment_head`'s DDL to [07](07-store-and-retrieval.md) §3 (Q1): `eval_calibration` (Q2) and `edge_bound` (Q4). |
