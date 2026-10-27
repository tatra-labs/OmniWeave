# 01 — Principles and Invariants

**In one paragraph.** This is the constitution: twenty-five numbered, falsifiable properties every
part of omniweave upholds, each with the failure it prevents, the mechanism that enforces it, and the
shape a violation takes in a diff. INV-1 through INV-20 are the charter's, restated with their
enforcement decomposed into a named class so a reviewer checks the enforcer rather than trusting the
claim; INV-21 through INV-25 are this document's additions, adopted as invariants by
[ADR-2](adr/0002-invariant-and-gate-registers.md). Below them sit the rule for a collision between two invariants, the four axes along which the
invariants are hardest to hold, thirteen principles that govern judgment calls no invariant can
decide, and eighteen anti-patterns traced to measured failures in the twenty-two mined repositories.
The document ends with the checklist a reviewer runs against a pull request.

## How this document is used

Three registers, three different forces.

| register | force | who may waive it |
|---|---|---|
| **Invariant** (`INV-n`) | A pull request violating one is wrong without further argument. | Nobody. An amendment is an ADR, shaped as below. |
| **Principle** (`P-n`) | Governs a judgment call. A reviewer may ask "which principle decided this?" and expect an answer; a reviewer may not reject on a principle without naming the concrete cost. | The author, with a written reason in the PR. |
| **Anti-pattern** (`AP-n`) | A named shape we have already decided not to build. Proposing one requires evidence that the observed failure does not apply here. | The author, with the evidence. |

**Cite a row by the spelling in that table** — `INV-7`, `P-4`, `AP-12`, hyphenated, in a heading as
well as in prose. The hyphen is load-bearing rather than cosmetic: the unhyphenated `P<n>` series
numbers [the document model](03-document-model.md) §17's thirty-one conformance properties, so `P4`
and `P-4` are rows in two different registers and neither spelling is available to a third. Which
register owns which prefix is settled in one place, the [glossary](glossary.md)'s prefix map, and a
register that wants a taken prefix takes another (INV-21).

Layer-local invariants — `DR1`-`DR24` (drivers), `RT1`-`RT14` (router), `ST1`-`ST20` (store),
`I1`-`I34` (runtime), `GR1`-`GR18` (graph), `OUT1`-`OUT24` (out), `SV1`-`SV19` (serve),
`Q-G1`-`Q-G27` (quality) — are **subordinate** to these twenty-five. They live with their decisions
in the charter and in the plan document that owns each layer. Where a layer invariant is the enforcer
of a framework invariant, this document names it; it does not restate it.

**Amending an invariant.** An ADR that changes `INV-1`..`INV-20` amends `_notes/charter.md` §2 and
must carry all five of:

1. the section amended, named (`_notes/charter.md` §2, or this document's §1b);
2. the old text and the new text, quoted, not paraphrased;
3. every enforcer that gains, loses or changes class, named by id (`G<n>`, `Q-G<n>`, `DR<n>`, …);
4. which ruling's ADR must be re-issued, per the charter's own amendment rule;
5. the migration for any stored data whose shape the change now permits.

An amendment that removes an enforcer without naming its replacement is refused at review. The ladder
rules below are properties of the whole register, not of one row, and an amendment that breaks one
breaks the register.

**Where each invariant is discharged.** This document states the properties; the documents below
specify the mechanisms that hold them. Each fact has exactly one home.

| invariants | owning document |
|---|---|
| INV-1, INV-9, INV-10, INV-21 (the model half) | [the document model](03-document-model.md) |
| INV-2, INV-3, INV-23, INV-24 (the packaging half) | [system architecture](02-architecture.md), [repository layout](11-repo-layout.md) |
| INV-4, INV-5, INV-6, INV-7, INV-15 | [drivers, operators and the extension system](04-driver-system.md) |
| INV-13, INV-14 | [acquisition, parsing and the routing engine](05-ingest-and-routing.md) |
| INV-16, INV-25 (the L3 half) | [structure extraction and the knowledge graph](06-structure-extraction.md) |
| INV-1 (the schema half), INV-11, INV-17, INV-22 | [storage, indexing and retrieval](07-store-and-retrieval.md) |
| INV-12, INV-18 | [the execution runtime](08-runtime.md) |
| INV-16 (the OUT half), INV-24 (the artefact half) | [generation: the OUT compiler contract](09-generation.md) |
| INV-8, INV-20 | [interfaces: MCP, skills, CLI, SDK and hooks](10-interfaces.md) |
| INV-19, and every `G`-class enforcer named below | [quality, testing and evaluation](13-quality.md) |

## The enforcement classes, and the ladder

Every invariant below names its enforcers by class. The classes are ordered by how early and how
cheaply they reject a violation.

| class | means | example |
|---|---|---|
| **A** — architecture | The violation is **unrepresentable**. There is no field to write, no handle to hold, no constructor to call. | `DriverIO` is frozen with no store handle; `DocSink` is host-side |
| **S** — schema | The database rejects the row: `NOT NULL`, `CHECK`, `UNIQUE INDEX`, a generated `BEFORE INSERT` trigger. | `restriction_bits NOT NULL` on every carrier |
| **L** — lint | A static scan rejects the source: semgrep, a grep gate, a schema lint, `ow route lint`. | `sqlite3.connect` outside `omniweave_core/store/` |
| **G** — gate | A CI job rejects the commit on a byte diff or a number: every `G` row in `tools/gates.toml`, `Q-G1`-`Q-G27`. | `G9`: `import omniweave_core` loads zero third-party modules |
| **X** — test | An executable assertion rejects the behaviour: property test, fixture, fault injection, crash matrix, conformance suite. | the crash matrix SIGKILLs at every statement boundary in `Store.complete()` |
| **R** — review | A human rejects it against this document. | "this rung is not monotone" |

**Three rules about the ladder. All three are checkable properties of the register.**

1. **No invariant rests on `R` alone.** An invariant held only by discipline is not held. Every entry
   in §1 carries **at least two independent enforcers and at least one of `{A, S, L, G, X}`**. A
   proposed invariant that can only be reviewed is a **principle** and belongs in §2. The rule counts
   enforcers, not classes: INV-2 and INV-3 are held at class `G` alone, by three gates each, and that
   is sufficient because the three read three different artefacts.
2. **Two enforcers are independent when one edit cannot disable both.** Two semgrep rules in one
   config file are **one** enforcer, because deleting the config deletes both — which is why
   rejection-list item 8 tells a reviewer to read the semgrep-config diff first. A schema trigger and
   the Python mapping it was generated from are two enforcers only because CI asserts parity between
   them in both directions; without that parity they are one.
3. **Enforce at the highest class available.** If a violation can be made unrepresentable (`A`), a
   schema constraint is a weaker choice and a test is much weaker. The charter applies this in both
   directions. `MAX_TRUST_BY_METHOD` is enforced at `A` (the runner writes `trust`; a driver cannot)
   **and** at `S` (a generated `BEFORE INSERT` trigger on `entity`/`mention`/`edge`/`claim`, with CI
   parity against the mapping in both directions) — two enforcers, one truth, because a runner bug
   and a migration bug are different bugs. Conversely `RT8`'s monotone escalation is a trigger and
   **not** a `CHECK`, because SQLite forbids a subquery in a `CHECK` body: the higher class was
   unavailable, and the charter says so rather than shipping a constraint that fails at
   `CREATE TABLE`.

## 1. The invariants

### INV-1 — One representation of a Block

**Statement.** No layer stores a second copy of a Block's text, structure or geometry, and no table
references a Block by anything other than `block_id` — never by `addr`, `cite`,
`(doc_ord, gen, page, ord)` or any other position.

**Why.** Two copies of text diverge, and the divergence is invisible until a citation points at the
stale one. marker's digital table path sets `block.html` and `structure = []`, which destroys
per-cell polygons, cell spans and citation-to-cell in one assignment; anydoc's `CellSlot::Origin(Cell)`
/ `CellSlot::Covered{origin_row, origin_col}` grid with `GridBuilder` as the sole constructor is the
counter-design, and it is the one adopted — cells are ordinary Blocks and HTML is rendered *from*
them, never stored as primary. The positional half is the same failure one level up: graphrag's chunk
id omits `document_id`, so identical text in two documents collapses into one `TextUnit`, and its
edges key on `clean_str(title.upper())`, so an entity whose spelling drifts between chunks becomes
two nodes. `block_fts` is an FTS5 **external-content** table for exactly this reason: it indexes
`block.text` rather than copying it.

**Enforced by.** `L` — a schema lint classifies every FK target and rejects both a second text column
and a positional reference to a Block (`GR15` restricts the both-layers case to `mention`); `L` —
semgrep bans an `html`, `markdown` or `md` field on any model class; `G` — **`G28`**, the archive
round-trip check, `import(export(store)) == store` over the fixture corpus, `gates` job, 45 s
(charter §D2 states the check and leaves it unnumbered; [ADR-2](adr/0002-invariant-and-gate-registers.md)
numbers it). The charter's §2 row credits `G6` with this assertion and is superseded: `G6` is
`ow schema emit --check` and nothing else. Do not cite `G6` for the round-trip.

**A violation looks like.** A new column named `*_html`, `*_text`, `*_md` or `*_bbox` on a table that
already reaches a Block; a `FOREIGN KEY (doc_ord, page, ord)`; a cache row holding rendered text "so
the renderer does not have to hydrate"; an FTS table declared with content of its own.

### INV-2 — Core imports zero third-party modules

**Statement.** `omniweave-core` resolves to exactly two first-party distributions —
`omniweave-core` + `omniweave-ports` — and zero third-party ones. `omniweave-ports` is stdlib-only
and depends on nothing.

**Why.** `import omniweave_core` is on the per-turn path of every hook and every CLI call, and a
compiled extension there is a fixed tax on every agent turn. Zero is a gate that cannot erode; "few"
is not. The negative evidence is unambiguous: `torch` and `torchvision` are **base** requirements of
docling, so its DOCX reader costs ≈2.5-3.5 GB installed with CUDA wheels; `leann-core` requires torch
**and** AGPL PyMuPDF **and** four PDF libraries including archived `PyPDF2`. Core being the host, and
being written in the driver-facing vocabulary (`DriverIO`, `DriverError`, `DriverResult`,
`FailureClass`, `Isolation`, `LicenceTier`), is why the single first-party edge points at
`omniweave-ports` rather than duplicating those six types — a duplicate would give `Isolation` two
definitions and demote `DR8` and INV-6 from structural to reviewable.

**Enforced by.** `G` — `G1` (clean-environment resolve asserts exactly that pair, and that
`omniweave_ports` has no dependencies); `G` — `G9` (`-X importtime` shows zero third-party modules);
`G` — `G4` (the module graph obeys `tools/layers.toml` **and** §3.2's dependency rule read off each
distribution's entry points, so a new distribution cannot pick its own row). Three gates, three
artefacts: a resolved dependency set, an import trace, an entry-point-derived module graph.

**A violation looks like.** A line added to `packages/omniweave-core/pyproject.toml`; a
`from pydantic import` inside `omniweave_core/model/`; a `numpy` import inside a retrieval channel; an
`omniweave_core` row appearing in a non-`compile` driver distribution's `layers.toml` entry.

### INV-3 — `import omniweave_core` is cheap and shallow

**Statement.** ≤ 80 ms. It imports none of `model`, `store`, `archive`, `retrieve`, `answer`, `out`,
`host`, `toolchain`, `modelserver`, and it imports neither `asyncio` nor `selectors`.

**Why.** `ow hook prompt` has a p95 budget of 250 ms warm and 1 s cold (`G26`), and every failure path
on that hook is a silent exit 0. A deadline breach therefore turns the adoption lever off with no
symptom, which is the worst failure shape available on the agent path: the feature stops working and
nothing reports it.

**Enforced by.** `G` — `G10` (per-OS cold-start baseline, 25% drift); `G` — `G17` (the lazy-submodule
assertion, listing the nine names); `G` — `G23` (neither `asyncio` nor `selectors`).

**A violation looks like.** A convenience re-export at the top of `omniweave_core/__init__.py`; a
module-level `from .store import Store` added to make a type annotation resolve at runtime instead of
under `TYPE_CHECKING`.

### INV-4 — Discovery never executes driver code

**Statement.** The catalog is built from `importlib.metadata` and `tomllib` alone. An entry-point
value is a string that is never `load()`ed.

**Why.** docling's `base_factory.py:95-105` imports a plugin **before** the `allow_external_plugins`
gate, so the consent check runs after the code has already run. Installation must not be able to
execute anything, because `pip install` is not a decision about what may run. Cost is the second
reason: `entry_points(group=…)` measures 15.3 ms over 328 installed distributions, while a
`Distribution.files` (`RECORD`) scan measures 2,124 ms and is forbidden as a discovery mechanism.

**Enforced by.** `L` — `EntryPoint.load()` is banned under `omniweave_core/drivers/`; `G` — `G11`
installs a rogue driver whose module body writes a file and raises `SystemExit`, and asserts
`ow doctor` succeeds and the file is absent; `X` — a core test discovers 30 cards and asserts
`sys.modules` gains no `omniweave_driver_*` key (`DR1`).

**A violation looks like.** `ep.load()` "just to read `SCHEMA_VERSION`"; an `importlib.import_module`
in `discovery.py`; a card field read by importing the module that declares it rather than by
`tomllib.load`ing `driver.toml`.

### INV-5 — Installation is not consent

**Statement.** A driver executes only when it is named in `omniweave.toml [drivers] enabled`, its
**computed** licence tier is allowed and (if restricted) acknowledged against the licence text's hash,
its `card_schema` and Port major are supported, and its probe is not `unavailable`.

**Why.** The mined collection's recurring shape is a safety mechanism whose default disables it
(AP-4). Here the direction is inverted: nothing runs until it is named. The licence half is not
hypothetical — marker, surya and lift ship a byte-identical modified AI Pubs OpenRAIL-M
`MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`) whose Attachment A clause 2(c) bars use by
anything that competes with the licensor, with no revenue, funding, personal-use or research
carve-out. The Apache-2.0 top-level `LICENSE` mentions weights nowhere, which is the trap. Hence
`DR15` (`licence.tier` is computed, never declared) and `DR16` (a restricted driver never activates
without an ack bound to the licence text hash).

**Enforced by.** `A` — the gate order inside `resolve()`, with a `Rejection` carrying a typed
`RejectCode` required to construct a `Resolution` (`DR5`); `X` — a mutated-licence test asserts
`LICENCE_ACK_STALE` with the hash diff printed (`DR16`); `X` — a framework-shipped tombstone for every
vetoed id, with a non-empty reason and a future `review_by` (`DR22`).

**A violation looks like.** A driver that runs because it is installed; a `[drivers]` key that widens
`inproc` eligibility past `DR9`'s four structural conditions; a `licence.tier` read from the card
instead of computed; `ow doctor` passing with a driver named in `[graph.passes] enable` but absent
from `[drivers] enabled`.

### INV-6 — A driver receives `DriverIO` and nothing else

**Statement.** No store handle, no cache handle, no budget ledger, no `RunContext`, no writable
`output_root` or `cache_root`, no socket.

**Why.** Every capability handed to a driver becomes a capability an attacker gets on a successful
compromise, and a surface the framework must then defend. It is also the only way INV-7, `I13` and
`I28` can be structural rather than reviewable: a driver that cannot reach the cache cannot poison it,
and a driver that cannot read the store cannot have undeclared dependencies. `ctx.service(name)` is
the one widening, and it returns a `ServiceHandle`, not a socket.

**Enforced by.** `A` — `DriverIO` is a frozen dataclass with no such field and is declared not
extensible; `A` — `HELLO` carries only `{source_ro, tmp, blob_base}`; `X` — the `sandbox` conformance
suite asserts a write outside `tmp` fails (`DR7`).

**A violation looks like.** An extra field on `DriverIO`; a `cache` keyword on `invoke()`; a `Store`
passed into a `derive/1` driver "for the corpus-wide view" — the case answered instead by making
`op.lexicon`, `op.resolve` and `op.cluster` host-side operators in the `omniweave` distribution.

### INV-7 — A driver cannot forge provenance, a cache hit, a price, a trust level or a citation

**Statement.** `producer_id`, `origin_driver`, `origin_operator`, `restriction_bits`, `confidence`,
`was_cache_hit`, every micro, and the `MAX_TRUST_BY_METHOD` clamp are written by the runner **after**
the driver returns.

**Why.** graphify's `confidence` field defaults to `EXTRACTED` — the strongest tier — so a producer
that says nothing is trusted most, exactly backwards. A draft proposes; the runner decides. The clamp
is measurable rather than silent: it writes `OW_GRAPH_TRUST_CLAMPED` carrying the driver's **original
claim**, so over-claiming shows up in `ow graph doctor` instead of being corrected invisibly.

**Enforced by.** `A` — `DriverResult.outcome ∈ {ok, ok_partial}` only, so a driver cannot report a
cache hit or a failure class; `A` — `DriverMetrics` has no currency field; `A` — `GraphSink` and
`DocSink` are host-side and a driver never holds one; `S` — a generated `BEFORE INSERT` trigger
mirrors the trust clamp (`GR4`), with CI parity against the mapping in both directions.

**A violation looks like.** `DriverMetrics.cost_micros` (deleted by the charter's §5 C6); a `trust=`
keyword on a sink method; a `was_cache_hit` field on a driver-facing type; a `[cost] usd_per_unit` key
on a card.

### INV-8 — Only a prompt-safe token may enter a prompt or model output

**Statement.** The space is closed: `[<corpus>:]d<doc>#<n>` (Block), `[<corpus>:]e<n>` (Entity),
`[<corpus>:]c<n>` (Community), `[<corpus>:]k<n>` (Claim). No `block_id`, `entity_id`, `addr`, path or
UUID, ever.

**Why.** graphrag's own `Identified.short_id` docstring states the principle — "Human readable ID used
to refer to this community in prompts" — and splitting `id` (a UUID, for joins) from `short_id` (a
small integer, the only id a model may cite) is the asymmetry that makes citation resolvable at all.
The corpus qualifier exists because one server serves N corpora, and two corpora both containing
`d7#412` make an unqualified cite **silently resolvable to the wrong document**, which is worse than
unresolvable. codegraph is the counter-example in the other direction: it returns verbatim
line-numbered source to the agent with no delimiter at all.

**Enforced by.** `A` — the prompt builder accepts only the four `Cite` NewTypes; `L` — a prompt-lint
regex over every rendered prompt in CI, and `GR11` additionally greps rendered prompts for `p\d+/\d+`
and bare integers; `X` — a renderer test asserts a single qualification form per response at each of
the three trigger states.

**A violation looks like.** An f-string interpolating `block.block_id` into an extraction prompt; a
model-returned `id`-shaped field flowing anywhere but into `normalize_key`; an MCP response carrying
`addr`; a two-corpus deployment emitting a bare cite — the emission trigger fails **expensive**, so
without a session identity a surface qualifies whenever `[corpora]` holds more than one entry, and an
ambiguous unqualified token returns `OW_CITE_AMBIGUOUS_CORPUS` (`OW-A-014`) with the candidates rather
than resolving. The **inbound** direction of this invariant is a separate hazard and is treated in
§1d: a document whose own text contains a cite-shaped string is an injection vector the prompt-lint
regex does not catch and was never meant to.

### INV-9 — A citation resolves to a Block, a page, and a polygon or a stated reason

**Statement.** No synthesized geometry anywhere in the framework. `Locus.reason` is non-`None` iff
`quad is None`.

**Why.** A box that is nearly right is worse than no box, because a reviewer clicking it lands on the
wrong paragraph and stops trusting every box. anydoc's `Block` enum has eight variants
(`Heading{level, anchor, content}`, `Paragraph`, `List`, `Table`, `BlockQuote`, `CodeBlock`, `Rule`,
`Math`) with **no source address of any kind** — verified against the pinned wheel's
`_collections/anydoc/src/model/block.rs`, where only `Asset` carries `origin_part` — so the office
path returns `quad = None` plus a reason, and that is the honest answer rather than a rectangle
inferred from a paragraph index.

**Enforced by.** `A` — `Quad.from_driver` is the sole constructor; `L` — `GR1` greps the graph DDL and
the generated `schema.json` for `quad|bbox|poly|x0` and fails on a hit, because no L3 table stores
geometry; `X` — a test asserts `locate()` returns `quad=None` plus a reason on an anydoc-parsed
document, and that `precision` says which of `line` or `block` was measured.

**A violation looks like.** `Quad(x0=block.page.x0, ...)`; a "best effort" bbox derived from a line
index; an L3 column named `bbox`; a `locate()` that returns a parent's polygon for a child it could
not resolve.

### INV-10 — Byte-exactness is claimed only where it is proved

**Statement.** `quote == VERBATIM` requires a retained content-addressed copy of the part **and** an
`OriginSpan` that re-verifies against those bytes by exactly one of three branches: `bytes` (the byte
slice equals the block text under `normalize_k`), `nodepath` (the node's text equals the block text),
`glyphs` (re-extraction of that glyph run by the recorded `os_extractor` reproduces the block text).
`pixels` and `none` can never reach `verbatim`. The serve layer claims it per Block, from
`doc.achieved`, never from a card.

**Why.** Byte-exactness is the one claim a user cannot check without the framework's help, so it is
the one claim that must be machine-proved. Stating only the `bytes` form made the property
**inapplicable** to the container formats it matters most for — and, unnoticed, to every PDF text
layer, since a PDF paragraph has no byte range in the content stream. That is why there are three
branches and why the driver testkit proves the claim on whichever branch a driver's `os_kind` selects.
Consequence, stated plainly: at release 1 every DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized`,
`verbatim` is unreachable on the office path, and `corpus_card.verbatim_fraction` discloses it before
any query runs.

**Enforced by.** `X` — `owcheck`'s verbatim-implies-retained-part clause; `G` — `Q-G6` gates
`span_exact_rate` at **1.000** on a deterministic sample of n = 1000 blocks, as a hard gate and not a
metric; `X` — the driver testkit re-reads the retained part on all three branches; `A` — `Quote` is an
ordered `IntEnum` with the weakest tier lowest (`SYNTHETIC = 0`, `VERBATIM = 4`), so `min()` over a
Segment returns the weakest and not the best member — the bug that let one verbatim Block pass a whole
Segment's reflowed and synthetic members through the byte-exactness gate.

**A violation looks like.** `quote = VERBATIM` on a `pixels` driver; a `Capabilities.origin_span =
"exact"` declaration the testkit's first fixture falsifies; a serve renderer reading a `DriverCard`
instead of `doc.achieved`; a defanged block still labelled `verbatim` (`SV12` re-labels it
`normalized`, marks it `ow:defanged`, and counts it in the trailer).

### INV-11 — A zero result is `absent` only after all fifteen absence gates pass

**Statement.** One `build_verdict()` constructor, one `citable_as_absence()` predicate, exactly one
`return ABSENT` site. A new hazard adds a gate; it never adds a second citability rule.

**Why.** This is the invariant with no counterpart anywhere in the collection, and the failure it
prevents is measured: a corpus that dropped files at index time sat at the same SHA as the checkout,
so it reported `fresh` while whole files were missing, and a user received confident zeros over
roughly 1,975 unindexed files and moved to another tool. omniweave's hazards are the document
analogues — OCR failed on pages 12-40, the PDF is password-protected, the table extractor timed out,
an empty text layer with no OCR fallback, the embedding model changed since indexing, the block budget
truncated the response — and each is currently a silent zero in every RAG system. An embedding zero is
a statement about the model, not about the corpus, and it must not be citable as one. Fifteen is the
**union** of two independently derived twelve-gate lists (charter §5 X28), not a pick between them.

**Enforced by.** `A` — `build_verdict` is the sole constructor; `L` — semgrep asserts exactly one
`return VerdictState.ABSENT` site, over `omniweave_core/retrieve/verdict.py` (`SV8`); `X` — one fixture
per gate plus a test asserting that adding a hazard requires no second citability rule (`ST9`); `G` —
`Q-G7` (`false_confident_zero ≤ 0.01`, `degradation_detection == 1.000`).

**A violation looks like.** A second `return ABSENT`; an `if not hits: return absent` shortcut in a
channel; a sixteenth gate added as an `or` inside `citable_as_absence()` instead of as a gate; a
`degraded` verdict downgraded to `absent` because the caller "wanted a clean answer".

### INV-12 — Unknown is never collapsed into unchanged, absent or clean

**Statement.** Three-valued signals are Kleene. A rule reading a nullable evidence key declares
`on_unknown`. No soft fallback ever applies to an identity or safety input. There is no bare `except`
around a digest, a cache key, a baseline read, a probe or a retrieval channel.

**Why.** Four measured instances, each silent and each permanent. graphrag's `str()` fallback for an
un-serialisable cache-key value yields address-bearing reprs and therefore a **permanent silent 100%
cache miss**. `_EXTRACTOR_VERSION = "unknown"` shares one AST cache namespace across every extractor
version, for exactly the developers changing the extractor. `except Exception: return {}` around a
baseline load turns every downstream safety check into a no-op at the moment it was needed. And
opening a WAL SQLite database with `immutable=1` against a live WAL raises "no such table"; a caller
mapping that to "no embeddings" states a **false absence** about a corpus it just embedded.

**Enforced by.** `A` — three-valued returns are sum types, not `Optional[bool]` (`I11`); `L` — `G8`
and `G24` ban a bare `except` around a digest, a cache key, a code fingerprint, a probe, a baseline
read or a retrieval channel; `L` — `ow route lint` errors on a rule reading a nullable key without
`on_unknown` (`RT7`); `X` — a fault-injection test corrupts `block_fts` and asserts `degraded`, never
`absent` (`ST8`).

**A violation looks like.** `except Exception: pass` anywhere near an identity function;
`config.get(k, "unknown")` inside a cache namespace; `if narrowing:` where `Narrowing` is tagged and
"no restriction" and "restrict to nothing" are different values (`ST5`); `freshness = "fresh"` derived
from a missing field.

### INV-13 — Escalation is per part and monotone, and a clean page costs nothing

**Statement.** `child.rung > parent.rung`, always. A clean born-digital PDF page computes zero
`LOCAL_COMPUTE` signals, renders no raster and starts no model server.

**Why.** The cost model only holds if the cheap path is genuinely free. marker calls deferring the
high-resolution render until after the routing decision the cheapest optimization in the repo, and it
generalizes to any stage graph where a later decision determines an earlier cost. `DEGRADE` is a
**forward** move on the `Rung` axis even though it runs a cheaper driver — which is exactly why "how
far down the escalation we are" (`Rung`) is separated from "what it cost" (`Spend`).

**Enforced by.** `S` — a generated `BEFORE INSERT` trigger on the parent join
(`route_decision_monotone`, raising `OW-R-030`), because SQLite prohibits a subquery in a `CHECK`,
with CI parity against the policy compiler's rejection of a backward `escalate_to`; `L` — the compiler
emits a per-rung demand plan, so no evidence key is computed unless a reachable rule reads it (`RT4`);
`X` — the `service_attaches`, `page_renders` and `signal_computations` counters are **exact**: ±1
fails.

**A violation looks like.** A `REPAIR` rung whose `escalate_to` points back at `DECODE`; a
`garble.score` computed on every page "so the histogram is complete"; a model server spawned at
preflight rather than lazily; a raster rendered before the decision that needs it.

### INV-14 — Budget never changes which rung is chosen, only whether it runs

**Statement.** `evaluate()` is pure over `(policy, evidence, hints)`. `admit()` reserves. Exhaustion
re-enters as the evidence key `budget.exhausted`.

**Why.** A policy whose output depends on a ledger is unreplayable, so `ow why` cannot answer why a
document was routed the way it was, and the router cannot be tuned at all. Keeping exhaustion as
**evidence** rather than as a parameter lets the decision stay a pure function while still being able
to say "we chose the VLM rung and deferred it", which is a different fact from "we chose the cheap
rung".

**Enforced by.** `A` — `evaluate()`'s signature has no ledger and no `RunContext`; `L` — semgrep bans
`time.`, `random.`, `os.environ`, `importlib` and `open(` in `route/eval.py` and `retrieve/plan.py`;
`X` — a property test evaluates 10k fixtures twice in shuffled order and asserts identity (`RT1`);
`X` — a test asserts a denied reservation leaves the `work` row claimable with `cost_micros` unchanged
(`RT10`).

**A violation looks like.** A `ledger` parameter on `evaluate()`; a `datetime.now()` in a policy
clause; a `Rung` selected by reading remaining headroom; a `DEFERRED_BUDGET` recorded as a failure
rather than an `Outcome`.

### INV-15 — No driver prices anything

**Statement.** A driver reports a physical `Spend` vector. Only the operator-owned `PriceBook` converts
`Spend` to micros.

**Why.** A driver author does not know the operator's contract price, their committed-use discount,
their currency, or whether the GPU is rented or owned. A currency number on a card is a claim that ages
the moment it is published, and it silently becomes the number a router optimises against.
`DriverMetrics` is therefore `{wall_ms, cpu_ms, gpu_ms, tokens_in, tokens_out, calls, bytes_egress,
bytes_read, peak_rss_bytes}` and nothing else, and `[cost] usd_per_unit` was deleted from the card for
being the same claim under another name.

**Enforced by.** `A` — `DriverMetrics` and every `[cost]` table contain no currency field; `A` —
`Spend.micros(book)` is the only place money appears; `L` — a lint bans a `*_micros` or `*_usd*` field
on any driver-facing type or card table.

**A violation looks like.** `cost_micros` on a driver-facing type; a `[cost] usd_per_page` key; a
scoreboard column reading a card's own price; `ow route propose` reading anything but measured `Spend`
through the operator's book.

### INV-16 — Restrictions travel to every derived item and block the OUT direction

**Statement.** `restriction_bits` is stamped by the runner from the producing card onto every Block,
Segment, Entity, mention, edge, claim, asset and artefact.

**Why.** A licence restriction that stops at the parse boundary is not a restriction. The failure is a
compliance failure rather than a correctness one, which means it is discovered by counsel and not by a
test — unless there is a test. `FIELD_OF_USE_EXCLUDED` is a bit, and the artefact compiler is where it
has to bite, because that is the point at which restricted content leaves the system.

**Enforced by.** `S` — `NOT NULL` columns with **no column default**, plus partial indexes, on every
carrier; `A` — the `compile` host refuses, naming the offending cites and asset ids (gate
`RESTRICTED`, one SQL aggregate at plan **and** at compile — `OUT11`, `DR17`); `X` — a synthetic
restricted driver's refusal is tested parse → derive → compile.

**A violation looks like.** A derived table without a `restriction_bits` column; an `INSERT` that omits
it and relies on a default; a `compile` path that checks at plan time only; an override that skips the
aggregate.

### INV-17 — One writer per store, one thread per connection, one transaction per unit

**Statement.** `sqlite3.connect` appears in exactly one module. The store thread is the only holder of
a `Connection`. A unit's derived rows, its work transition, its `dep` rows, its reservation commit and
its spend row commit together.

**Why.** Multi-writer SQLite fails by corruption and by lock storms, and both are expensive to diagnose
after the fact. The transactional grouping is what makes the pending set a checkpoint: a crash cannot
produce a phantom completion, so recovery is re-running the normal command. codegraph's WAL story is
the cautionary measurement — 22 GB of WAL then an OOM-kill (exit 137) at an envelope the un-valved
build survived, and 25.6 GB of WAL leaked across SIGKILLed sessions.

**Enforced by.** `L` — `G24` bans `conn.commit()`, `BEGIN` and `import sqlite3` outside
`omniweave_core/store/`; `A` — `Store.complete()` is the sole mutation entry point; `X` — a
monkeypatch test; `X` — a 16-runner-thread test asserts every cross-thread call raises (`I19`); `X` —
`ow test crash-matrix` SIGKILLs at every statement boundary in `Store.complete()`.

**A violation looks like.** A read-only helper opening its own connection "because it is only a
`SELECT`"; a `BEGIN` in a retrieval channel; a spend row committed separately from the work transition;
a group commit widened past `I20`'s zero-derived-row exception.

### INV-18 — An incremental run converges to a full rebuild

**Statement.** An incremental run produces the same corpus as a full rebuild from the same inputs.

**Why.** The most expensive silent failure in the collection, with a number on it: codegraph measured
**4.3% of distinct edges wrong, in both directions, silently, forever until a full rebuild** from
skipping a convergence pass. graphrag's incremental path fails four independent ways — delta detection
is `~input["title"].isin(previous["title"])`, so an in-place edit reports "No new update documents
found" and stops; `deleted_inputs` is computed and consumed nowhere; merged entity `degree` is
`"first"`; and communities are never recomputed, so after an update an entity in both halves lives in
two unrelated hierarchies with two separate reports and global search map-reduces over both.
Incremental correctness is not "re-derive the changed thing"; it is "re-derive everything whose answer
depended on what changed", and the second set is not derivable from the first without an explicit
dependency record.

**Enforced by.** `G` — `G19` owns the fixture size and the mutation count (a 300-document fixture in
40 scripted mutations) and diffs the `.owdoc` **exports**, not the tables; `G` — `GR8` is the smaller
graph-specific gate (60 documents, 20 shuffled steps including 3 edits, 2 deletions and 1
driver-version re-parse), asserting equality on `canonical_projection()` modulo surrogate ids, and it
is **blocking, not nightly**; `S` — `dep` rows and the cohort merkle make the cross-unit input set a
stored fact rather than an inference (`I28`).

**A violation looks like.** A new cross-document derivation with no `dep` row and no cohort digest; an
`anchor_delta` pass skipped because "a body edit cannot change a reference"; a merge that concatenates
ids with an offset instead of re-clustering.

### INV-19 — Every number carries its evidence, and an uncalibrated confidence renders no digit

**Statement.** A published metric requires `(n, ci95, method, slice_key, corpus_digest, MeasuredOn,
witness)`. A confidence whose `Calibrated.status != "calibrated"` may print an ordinal name plus
`(uncalibrated)` and may never print a numeral, percentage, bar, colour or grade — while remaining
usable as an internal filter and sort key.

**Why.** HunyuanOCR's published 94.10 OmniDocBench was measured on TensorRT while the repo ships
Transformers and vLLM, which it admits disagree — so a model configuration is
`(weights, runtime, runtime version, sampling params, prompt version)` and no README number may enter a
router's cost/quality table. The internal-filter clause is what keeps the `block_review` partial index
(`WHERE trust < 2`) working on day one: an uncalibrated signal is still a usable ordering, it is simply
not a publishable digit.

**Enforced by.** `A` — an unregistered `score_kind` **raises at `DocSink.add_block`** (charter §6.3
chain step 2), and `MeasuredOn` is frozen with **no defaults and ten fields**, so a card supplying
seven of them raises `TypeError` at construction rather than writing a blank cell; `G` — `Q-G8` (no
`eval_metric` row without a complete `MeasuredOn`; `unpinned` ⇒ UNRANKED), `Q-G10` (an unregistered
`score_kind` cannot be written, and a declared-but-never-written one fails) and `Q-G14` (the render
rule); `X` — a renderer test feeds each `Calibrated.status` and asserts the output shape. The charter's
§2 row names only `Q-G8` and `Q-G14` and is superseded by
[ADR-2](adr/0002-invariant-and-gate-registers.md): **four enforcers stand**, and this section is
their sole home.

**A violation looks like.** A scoreboard row with `value = 0.94` and no `n`; a confidence bar rendered
from a float whose curve is `stale`; a card benchmark row whose `measured_on.corpus_digest` does not
match a digest in the omniweave release manifest and is nonetheless ranked — `DR24` demotes it to
`witness = "self"`, displayed and never ranked, and never read by `ow route propose`.

### INV-20 — Nothing agent-facing is written by hand

**Statement.** Every MCP tool schema, the `instructions` string, `llms.txt`, `AGENTS.md`, the CLI verb
tree, the SDK stubs and the router skill's action table are generated from the Action registry and
byte-diff gated.

**Why.** LEANN's hand-written `llms.txt` declares 2 tools against a 4-tool server. The drift is
invisible to every test that does not compare the two, and it is read by a model that has no way to
know it is wrong. The same argument settles the TypeScript SDK: `ow surface typescript <dir>` generates
`omniweave.d.ts` plus a ~120-line zero-dependency client from the same gated `schema/*.json`, so the
types cannot drift, whereas a hand port can.

**Enforced by.** `G` — `G25` (`ow surface emit --check`: every agent-facing artefact is generated and
byte-identical, and no two CLI groups differ only by a trailing `s`); `G` — `G6`
(`ow schema emit --check`, CRLF-normalised); `X` — a hand-edited agent-facing artefact fails the build.

**A violation looks like.** A tool description edited in `mcp-tools-v1.json`; a CLI verb added to the
argparse tree by hand; a sentence added to `docs/AGENTS.md`; a shortened tool description committed to
fit a token budget — the correct move is to remove `want` and `route_hints` from the compact schema,
never to shorten a description.

## 1b. Extends the charter — INV-21 to INV-25

> **Amendment note — landed.** [ADR-2](adr/0002-invariant-and-gate-registers.md) adopts the five
> below as **invariants**. The charter's §2 opens with "Twenty properties."; that count is superseded
> (charter §9.2 `E30`) and **there are twenty-five**. Each of the five generalises a property the
> charter already enforces in at least two layers without ever stating it framework-wide, and each
> passes the ladder's rule 1 independently: INV-21 is `G`+`L`+`G`, INV-22 `A`+`L`+`X`, INV-23
> `A`+`L`+`G`, INV-24 `G`+`X`+`L`, INV-25 `A`+`S`+`X`+`L`. **Cite them as invariants**; the earlier
> instruction to say "principle" is withdrawn. `tools/invariants.toml`'s five rows carry
> `force = "invariant"` and `adr = "ADR-2"` (§1e). Nothing below contradicts the charter.

### INV-21 — One name, one type, one home

**Statement.** Every concept has exactly one name; every name has exactly one type; every configuration
key, every error code and every constant has exactly one home. A name that would carry two types is
split, and the split is recorded in `terminology.md`.

**Why.** The charter's own terminology lock failed all three of its checks before its last revision: it
shipped `Verdict` and `Layer` in a module inventory a plan document would have copied verbatim, while
§3 lists both as rejected. `Layer` named both L2's Block layer
(`body|furniture|note|annotation|hidden`) and a cache layer, inside one distribution, which makes
`from omniweave_core... import Layer` ambiguous and makes `WORTH_LAYER` and `cache_index.layer` read
alike while meaning different things. `Evidence` was carrying three types: the routing record, the OUT
manual-region artefact, and a served answer block. `content_digest` carried both a 16-byte `ow128` BLOB
and a hex sha256 TEXT under one name, and **a BLOB never equals a TEXT**, so a join across the two
silently returned nothing. `--ignore-cache` named a five-layer `cache_index` and was therefore an
unnamed authorisation to re-bill.

**Enforced by.** `G` — `G27(c)` checks the lock in **both** directions: every `CREATE TABLE`,
`CREATE VIEW` and `class` name in the charter or a plan document has a row in `terminology.md` §2,
every §2 term appears in at least one document, and no document contains a §3 rejected synonym; `L` — a
schema lint rejects one column name bound to two SQL types across the DDL; `G` — `G18` asserts the
union of the two config-axis key lists covers every key in `omniweave.toml.example` **exactly**, with
exactly one matching pattern per key, which is what catches a key with two homes; `G` — `G13`
(`codes.toml` append-only) makes the code register single by construction.

**A violation looks like.** A second `class Layer`; a `member_digest` column of TEXT type beside a
`member_digest` of BLOB type; a `[route]` knob duplicated in `omniweave.toml` and
`.omniweave/policy.d/*.toml`; a new `RejectCode` member with no `OW-D-nnn` row; a numbered register
opened under a prefix the [glossary](glossary.md)'s prefix map already assigns to another one; a flag
whose name describes a subsystem rather than a hazard.

### INV-22 — A ceiling is never a target and never a setting

**Statement.** A `MAX_*` constant is a number its own producer is built never to exceed, enforced at the
read boundary with `take(N+1)`-then-check, clampable **down** by a tenant and never widenable:
`effective = min(tenant_cap, declared, HOST_MAX)`. Widening past a `MAX_*` is a fork, not a flag. A
number a producer overshoots by design is a `*_TARGET_*`.

**Why.** Both halves failed in the mined collection, and one failed inside the charter's own drafts. The
config half: docling's `DocumentLimits.max_file_size` and `max_num_pages` both default to `sys.maxsize`
(`docling/docling/datamodel/settings.py:23-24`), which is a limit that does not exist; anydoc's own
comment is the correct posture — a knob that turns off the zip-bomb cap will be turned off — and
markitdown's default-registered `ZipConverter` has no entry cap, no size cap, no total cap, no
recursion-depth counter on nested zips and no path sanitization. The naming half:
`MAX_SEGMENT_TOKENS = 1200` was a **target** wearing a ceiling's name, because the segmenter emits
*after* crossing it, so the total lands above it by design; the resolution is
`SEGMENT_TARGET_TOKENS = 1200` plus `MAX_SEGMENT_TOKENS = 2048`, and only the second is enforceable by
`take(N+1)`-then-check. A `MAX_` name on a routinely-overshot number is a false invariant, and a false
invariant is worse than none, because tests get written against it and then relaxed.

**Enforced by.** `A` — limits live in `omniweave_core.limits` as host constants, and a card declaration
above `HOST_MAX` is `CARD_INVALID` (`DR20`); `L` — a lint over `limits.py` requires every `MAX_*` to
have an enforcement site that reads `N+1` and every `*_TARGET_*` to have none; `X` — one property test
per `MAX_*` drives its own producer past the number and asserts a `RESOURCE_LIMIT{limit}` naming the
knob that would need raising. Rejection-list item 24 is the supplementary `R`-class check and does not
count toward ladder rule 1.

**A violation looks like.** A `MAX_*` whose only use is a comparison after the collection is already in
memory; a `MAX_*` read from config; `MAX_SEGMENT_BLOCKS` widened rather than forked, when
`derive_cover.cover_bits` is sized off it; a new ceiling with no `RESOURCE_LIMIT` message naming its
knob.

### INV-23 — Exactly one implementation of any semantic decision

**Statement.** "What does this mean" has one implementation, and every consumer calls it. Where two
artefacts must agree and cannot be one artefact, one is **generated** from the other and the diff is
byte-gated.

**Why.** ppt-master's validator imports the compiler's parsers to decide validity — `svg_contracts.py`
pulls ~40 symbols from `svg_to_pptx.drawingml.utils`, `…paths` and `…elements` — so there is exactly
one implementation of what `fill=` means, and the alternative produces the "checker passed, compiler
failed" bug class. The charter applies the rule in five places without generalising it: `OUT2`
(`rules/` and `lower/` are modules of one distribution, `CompileV1` has no `validate()`, `measure.py`
is imported by both); `rebind()` is one matcher with two consumers, the re-parse identity pass and the
golden differ; `ST6` (`fuse()` and `ceiling()` resolve weights through one `_weight()`, because a
ceiling that drifts from the scorer silently rescales every confidence number in the product); `SV19`
(one renderer, three surfaces — `omniweave_core.answer.render`); and `GR17` (the extraction prompt is
rendered from `relation_vocab.actor_rule`, so prompt and schema cannot drift). The negative evidence
for the "obvious duplicate" temptation is the charter's `X30`: `normalize_key` and `normalize_k` differ
by four characters, do different jobs, both survive, and a semgrep rule flags a call to either from a
module that should use the other. One implementation per **decision**, not one function per
name-shape.

**Enforced by.** `A` — a target has no `validate()`, and a validator with no independent parser cannot
disagree with the compiler; `L` — semgrep bans a second carrier parser under `rules/`, a second
`BEGIN`-scoped statement group, and a second `ABSENT` return; `G` — the two-way symbol-set gate
(`OUT1`: import `lower/`, diff its public symbol set against `constructs.toml`, both directions) and
every byte-diff gate in `G6`, `G20` and `G25`; `X` — trigger-versus-mapping CI parity, in both
directions.

**A violation looks like.** A second normaliser "for the fast path"; a linter that re-implements a rule
the runtime enforces; a hand-maintained JSON Schema beside the Python definitions it describes; a
scoreboard SQL view that recomputes a threshold instead of reading `route_threshold` rows.

### INV-24 — Every committed or shipped artefact is byte-reproducible from declared inputs

**Statement.** Every artefact omniweave writes into a repository (generated schemas, `tools/*.toml`,
`omniweave.index.lock`, golden reductions) and every artefact it ships to a user at a declared
determinism floor (an OUT `part`, an `.owdoc`) is byte-reproducible from inputs the artefact itself
names.

**Why.** This is `I17` — "every artifact omniweave commits to a repo is byte-reproducible" — widened to
the shipped side, because one mechanism carries both halves and only one half was stated. A generated
artefact that is not byte-reproducible cannot be byte-gated, and a byte gate is the only enforcement
class that catches drift in a file nobody reads. The hazards are verified against CPython 3.11.9
rather than assumed: `ZipInfo.from_file` takes `mtime = time.localtime(st.st_mtime)`, which is
non-deterministic; `ZipFile.writestr` stamps local time; only `ZipInfo(name)` yields the safe
`(1980, 1, 1, 0, 0, 0)`. The OPC writer's rules that follow from this — canonical member order, a
fixed `dcterms:created`/`dcterms:modified`, no `w:rsid*`, EMU integers so no `repr(float)` reaches the
XML — are specified once in [generation](09-generation.md) and are not restated here.
`omniweave.index.lock` is sorted by `doc_key`, byte-stable, with **no timestamps**, and its merge
driver is registered for that path only: sort-merge by `doc_key`, identical lines union, a conflicting
line for one `doc_key` is a real conflict a human resolves, and **a deleted line stays deleted** —
which is exactly the property graphify's `nx.compose` union driver throws away
(`graphify/cli.py:2572`, under caps `_MERGE_MAX_BYTES = 50 MB` and `_MERGE_MAX_NODES = 100_000` at
`:2547-2548`, two to three orders of magnitude below a real corpus).

**Enforced by.** `G` — every byte-diff gate (`G6`, `G18`, `G20`, `G25`) plus `Q-G4` (`shape` is
byte-identical across two pdfium minors and 9 OS/py cells); `X` — the determinism harness: 3 runs ×
`PYTHONHASHSEED ∈ {0, 1, random}`, two temp dirs, different `cwd` and `TMPDIR`, `SOURCE_DATE_EPOCH=0`,
with the cross-platform matrix asserting `part` **only** (`OUT13`); `L` — `G8` and `OUT14` ban
`time.time()`, `os.getcwd()`, `Path(".")`, `random`, `secrets`, `uuid4` and `datetime.now` in library
code and in every `omniweave-target-*`; `A` — `omniweave_core.out.opc` is the only module permitted to
open a ZIP for writing (`OUT15`).

**A violation looks like.** A generated file with a timestamp header; a sorted-collection assumption
that relies on dict insertion order across processes; a `byte` determinism claim made without a pinned
resolution — `part` is the floor and `byte` is never promised; a float formatted with `repr()` into a
committed artefact.

### INV-25 — Nothing is disposed of silently; every rejection is retained as addressable data

**Statement.** No item is disposed of by a mechanism nobody asked for and nothing records. A rejected,
superseded, unresolved or quarantined item is retained, addressable, and explains itself. There is no
`drop()` on any sink, no silent skip, and no terminal state without a scheduled way out. A named,
bounded, operator-invoked reclamation that records what it removed is **not** a violation.

**Why.** The residue is data, and every repo that discarded it lost a capability. codegraph's
unresolved-reference table with a status lifecycle is the collection's most under-copied idea: rows are
inserted `pending` by extraction, and a resolution pass either deletes the row or marks it `failed` —
kept, with a `name_tail` retry key and a partial index `WHERE status='failed'` — so "the corpus grew
and now this citation resolves" is a bounded query rather than a re-index. omniweave mints these
constantly: a citation to a document not yet ingested, a cross-reference to a figure in another PDF, a
caption naming a section number. The same shape recurs as jcodemunch's
`*_unmapped(..., reason, count, last_seen)`
tables per producer. The framework's five instances, each owned elsewhere: `GraphSink` has **no**
`drop()` and quarantine is the only disposal path (`GR10`); a retired cite resolves through
`block_history.superseded_by`, or refuses with `OW_CITE_RETIRED` (`OW-M-030`) naming the generation
and the reason — never a silent miss and never a nearby Block; a removed driver resolves to a
framework-shipped tombstone with a reason and a future `review_by`, not to "unknown" (`DR22`); a
rejected candidate carries a typed code in `resolution_report` (`DR5`); and `SKIP` is not a state,
`unknown` is, on which `ow eval release-check` refuses. Every terminal state has an exit:
`clear_old_permanent(30d)`, a corrupt cache entry overwritten on the next success, and `PERMANENT`
carrying no `retry_after` so the ladder terminates (`I7`). The statement's last sentence is what
separates this invariant from "nothing is ever deleted",
which is false and would be unshippable: `clear_old_permanent(30d)`, the `cache_index` sweep on the
`cost_class='free'` partial index (`I27`) and `ow cache prune --allow-rebill` all delete, all are named,
all are bounded, and all leave a record.

**Enforced by.** `A` — no sink exposes a delete; `S` — retention tables with `NOT NULL` reasons
(`quarantine.code`, `block_history.reason`, `GraphSink.cover` requiring `empty_reason` when the cite
set produced nothing); `X` — `owcheck --graph` asserts zero orphans, and a dangling-tmp draft produces
a quarantine row; `L` — a lint asserts every `DELETE FROM` under `store/` is filtered on
`origin_operator` (`ST11`), which is the mechanism that makes an operator's reclamation scoped rather
than global.

**A violation looks like.** A `GraphSink.drop()`; a `DELETE` that removes a superseded Block row instead
of setting `state=1` and writing `block_history`; a driver veto with no tombstone; a `skip` state on a
gate; a permanent failure class with no sweep; an automatic sweep of `billed_api` cache rows — `I27`
forbids it, and the deletion requires `ow cache prune --allow-rebill`, which prints the count.

## 1c. When two invariants collide

Two invariants can appear to pull in opposite directions on one diff. Three of the four cases below
resolve by reading both statements carefully; the fifth paragraph is the rule for when they do not.

**INV-25 × §6.10's ceilings × an erasure obligation.** Retention is unbounded and a ceiling refuses.
The reconciliation is INV-25's last sentence: the invariant binds the framework's *automatic*
behaviour, not an operator's explicit command. The separating test is two questions — could the
disposal happen without anyone asking for it, and does anything record that it happened? Yes-then-no is
the violation. Erasure of *source* content is neither designed nor forbidden here and is Open
question 5.

**INV-10 × F32's retention fallback.** If `retain_parts` becomes opt-in, `verbatim` has no producer.
Both hold, because INV-10 is conditional by construction: it does not say `verbatim` is reachable, it
says it is unclaimable without proof. Under `retain_parts = "never"` the tier is empty and
`corpus_card.verbatim_fraction` prints that before any query runs (P-3). A PR that reacts to the
fallback by weakening the *precondition* — proving verbatimness from a card, or from a driver's
declaration — violates INV-10; it is not a consequence of F32.

**INV-13 × INV-11.** Absence gate 4 (`coverage_incomplete`) needs a discovered-versus-indexed count,
and INV-13 forbids a clean page paying for evidence it does not need. They do not collide, because
absence evidence is *read* from `diag` and `ingest_scope` — rows written by work that already
happened — and never computed at query time. A PR that computes a signal at query time to satisfy an
absence gate breaks INV-13's exact counters and is rejected there.

**INV-2/INV-3 × INV-20.** Generating every agent-facing artefact needs a generator; core must not
import one. The generator is not in core: `ow surface emit` lives in `omniweave` and
`omniweave-conform`, and core carries the Action registry as data only. A PR that puts a generator in
core to satisfy INV-20 breaks INV-3's lazy list, and the fix is to move the generator, not to relax
the list.

**The rule for a collision that does not resolve.** An unresolvable collision is a charter defect, not
a licence to choose. Record it in this document's Open questions, flagged, and follow **the invariant
whose violation is unrecoverable**: a byte-exactness, provenance, restriction or citation claim is
unrecoverable once shipped, because it is already inside someone else's document; cost, latency and
install weight are recoverable in the next release. Do not average the two, and do not ship both
halves weakened.

## 1d. Where the invariants are hardest to hold

For each mechanism, the axis that bends it, the named defence, and what is left over. A "left over"
cell is a risk this plan carries knowingly, not an oversight.

| axis | what bends | the named defence | what is left over |
|---|---|---|---|
| **Scale** | INV-17: a 4M-cell sheet is one page, one transaction, a multi-GB WAL and a commit that trips `loop_lag_max_ms`; the WAL valve cannot help mid-transaction because its release condition is a full backfill | `MAX_GRID_SLOTS = 4_000_000` at the read boundary; the table-synopsis rule bounding `segment_block`; `ST16`'s futility latch degrades to un-valved with an armed log line rather than fighting | a sub-page commit boundary (F29); `MAX_BLOCKS_PER_DOC` plus a `RESOURCE_LIMIT` naming the knob is the shipped answer |
| **Scale** | INV-11: gate 4 needs a **global** discovered-vs-indexed count that no shard can compute | `shard_unreachable`, `federated` and `shards_contributed` ship regardless | F35's fallback: `coverage_incomplete` becomes per-shard and the verdict reports `coverage: unknown` naming the shard |
| **Scale** | INV-25: residue grows without bound — `route_signal`, `quarantine`, `ref_attempt`, `block_history` | `clear_old_permanent(30d)`; the `cache_index` sweep on the `cost_class='free'` partial index (`I27`); every ceiling at `take(N+1)` | `route_signal` disk growth against the sweep rate (F37). If sweeping does not bound it, the 2 GB cap becomes a hard refusal naming `ow cache prune` |
| **Hostile input** | INV-8, **inbound**: a document whose own text contains `d7#412` reaches an extraction prompt as block text, and the model may return it as its own citation — attributing a claim to a document it never read. The prompt-lint regex checks that no *forbidden* identifier appears and therefore passes this cleanly | `begin_run(allowed_cites=…)` rejects any emitted cite outside the handed set with `OW_GRAPH_OUT_OF_SCOPE_BLOCK` (`GR9`); `GR5`'s grounding gate requires the emitted row's span to be findable in the block it cited; `GR12` routes untrusted text through `wrap_untrusted()` only | an injected cite that falls **inside** `allowed_cites` re-attributes within the handed set, and nothing today detects that. Open question 4 |
| **Hostile input** | INV-22: a zip bomb, nested archives, a page carrying 400,000 blocks | `take(N+1)`-then-check at the read boundary, so a limit is never discovered after the memory is spent; `MAX_ENTRY_BYTES`, `MAX_ENTRY_COUNT`; `Frame` is bounded by **block count** and deliberately not a page range | — |
| **Hostile input** | INV-6: a compromised publisher's driver holding read access to `source_ro` | `subproc` plus one writable tmpdir; net namespaces where the OS provides them | on macOS and Windows `needs_network = false` degrades to a process-level guard a determined malicious driver in that process can bypass. `DR10` **records** the shortfall rather than claiming isolation; the residual is written down (§6.11) |
| **Partial failure** | INV-16: a crash between deriving a row and stamping its `restriction_bits` | INV-17's one-transaction-per-unit makes the two atomic; `restriction_bits NOT NULL` **with no column default** makes a partial write impossible to commit | — |
| **Partial failure** | INV-7: a runner bug writes an unclamped `trust` | the generated `BEFORE INSERT` trigger is the second, independent enforcer, and CI parity in both directions keeps trigger and mapping equal (`GR4`) | — |
| **Partial failure** | INV-18: a converge pass that dies half-way | `dep` rows and the cohort merkle are stored facts; resume re-derives the plan from current inputs and subtracts what is done, never replaying a recorded plan (AP-5), so a half-converged run is re-planned | — |
| **Concurrency** | INV-14: two scheduler processes each admit 2 and show the provider 4 | durable `budget_reservation` rows; headroom computed **in SQL**, never cached in an attribute; a held `(dim='calls', scope='provider')` reservation **is** the cross-process in-flight count (`I29`) | — |
| **Concurrency** | INV-7: a superseded result writes rows after cancellation | cancellation propagates **by generation, not by signal**: the commit predicate `WHERE id=:id AND claimed_gen=:gen AND status='claimed'` makes a superseded write a zero-row update (`I23`) | — |
| **Concurrency** | INV-1: `block_fts` and `block.text` diverging under a concurrent rebuild | one writer per store (INV-17); `block_fts` is an FTS5 **external-content** table, so there is no second copy to diverge | — |

## 1e. The register as data

The invariant register is this document's own artefact. [Quality, testing and
evaluation](13-quality.md) owns gate *definitions*; this file owns the list of invariants, their
force, their enforcers and their owning document. Below is the machine-readable form. Two rows are
shown — the two [ADR-2](adr/0002-invariant-and-gate-registers.md) corrected; the committed file
carries all twenty-five, every one of them `force = "invariant"`.

```toml
# tools/invariants.toml — hand-written here. Identifiers resolved by G27(d); row semantics asserted
# by the `gates.invariant_register` job assertion.
schema = 1
ladder = ["A", "S", "L", "G", "X", "R"]
min_enforcers = 2

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

**`sites` is the second enforcer list, and it exists because `A`- and `X`-class enforcers have no
id.** `enforcers` holds register ids — `G<n>`, `Q-G<n>`, `DR<n>`, `RT<n>`, `ST<n>`, `I<n>`, `GR<n>`,
`OUT<n>`, `SV<n>` — which resolve to a row in `eval/gates.toml` or in the owning plan document.
`sites` holds enforcers that have no such id: each entry is either a dotted `omniweave*` symbol,
which `G27(d)` clause `d1` already resolves by importing it, or a repo-relative path. Writing
INV-19's row is what exposed the gap — the raise at `DocSink.add_block` and the frozen `MeasuredOn`
are two of its five enforcers and neither has a number. **`independent` counts both lists**, which is
why INV-19's is 5 against three `enforcers` entries.

**The register is checked by two different machines, on purpose.** `G27(d)` resolves identifiers
across documents ([repository layout](11-repo-layout.md) §8.6, clauses `d0`-`d4`). The semantics of a
register's rows are not a document check, so they are the `[[job_assertion]]`
**`gates.invariant_register`** — job `gates`, budget 2 s — the same shape and budget
[risks](17-risks.md) §1.1 gave `gates.risk_register` for the same reason. It asserts, over
`tools/invariants.toml`:

1. **bidirectional coverage** — every `### INV-<n>` heading in this document has exactly one `[[inv]]`
   row, and every `INV-<n>` row has exactly one heading;
2. **ladder rule 1** — `independent >= min_enforcers` and `classes != ["R"]` for every row;
3. **the arithmetic** — `independent == len(enforcers) + len(sites)`;
4. **the two decidable cases of ladder rule 2, and only those** — two enforcers naming the same
   semgrep config file count as one, and an `S`-class trigger plus the mapping it was generated from
   count as one unless a parity gate is named. The general case is undecidable and stays `R`;
5. **the count** — every spelled-out invariant count in any document equals the number of `[[inv]]`
   rows whose id matches `^INV-\d+$` and whose `force` is `invariant`. This is the mechanism that
   makes "twenty-five" one number rather than four, and a pull request that adds `INV-26` and forgets
   a paragraph fails here.

Do not propose a clause `G27(e)` for any of those five assertions: that alternative is recorded and
rejected in [ADR-2](adr/0002-invariant-and-gate-registers.md), on the argument that `G27(d)`'s `d0`
guard, its single 25 s budget and its single failure prefix would then cover two unrelated failure
modes.

## 2. The principles

These decide the cases an invariant cannot. Each is stated, then applied, then over-applied — because
every principle here has a failure mode consisting of believing it too hard.

### P-1 — Evidence before mechanism

A mechanism ships when the failure it prevents has been observed in the collection or measured here.
"Someone might" is not a reason; a file, a line and a number is.

*Applied.* The `anchor` / `ref_site` / `ref_unresolved` machinery — three objects, a status lifecycle
and a partial index — is affordable only because codegraph measured 4.3% of distinct edges wrong in
both directions from skipping the equivalent pass. Without that number, "an unresolved-reference table"
is speculative infrastructure.

*Over-applied.* Refusing `omniweave-target-docx` because no mined repo measured the cost of a second
OUT target. The second implementation **is** the test that the abstraction is not one implementation
wearing an interface (the charter's `X33`), and that argument is structural, not empirical. Evidence
governs mechanisms that cost money at runtime; it does not govern whether an abstraction is honest.

### P-2 — Two reasons or it is a special case

A general mechanism needs two independent motivating cases. One case gets a specific answer.

*Applied.* Per-driver process isolation is deliberately not generalised: the pathological-XLSX failure
argues for an RSS-capped worker, and until a **second and different** reason appears (a CUDA OOM, a
native crash), the answer is `subproc` plus `memory_mb` plus a refusal. `F25` states the closing
condition in one line: one reason is a special case; two is a mechanism.

*Over-applied.* Waiting for a second reason before propagating `restriction_bits` through derived rows.
A legal obligation is not a mechanism-generalisation question, and INV-16 exists because the *cost* of
the failure is unbounded, not because it was observed twice.

### P-3 — Disclose the limitation; never hide it behind a default

Where a capability is genuinely unavailable, the shipped default makes the absence visible in the
product surface, in words the operator can act on.

*Applied.* `vectors = "off"` is the shipped default, so most first runs get four retrieval channels and
a verdict that says `semantic: off`. That is a visible product limitation and the correct one; the
alternative is a five-second query or numpy in core. Likewise `corpus_card.verbatim_fraction` prints
that the office path can never reach `verbatim` **before** any query runs, because the anydoc upstream
carries no per-block source address.

*Over-applied.* Disclosing instead of fixing. Printing "we may have missed pages" is not a substitute
for adding the absence gate that turns the miss into `degraded`. Disclosure is the honest answer when
the capability does not exist; it is an evasion when the capability exists and someone did not wire it.

### P-4 — Fail expensive, never wrong

When a classification is missing, take the branch that costs money or refuses. Never the branch that
produces a row.

*Applied.* Every config key declares a `semantic` / `operational` axis at its declaration site, and **an
unclassified key fails CI and is treated at runtime as `semantic`**. The failure direction is therefore
"re-bill" (visible in `ow cost`) rather than "serve stale" (invisible). The rejected alternative was a
four-key `run_scope_digest` allowlist — right diagnosis, wrong shape, because an allowlist fails *open*.

*Over-applied.* Classifying `drivers.enabled` as `semantic`. Which driver runs is already in the cache
key through `producer.operator`, `schema_version`, `code_fingerprint` and `options_digest`, so an
allowlist that merely selects among drivers is `operational` — and classifying it `semantic` re-bills an
entire corpus every time an operator enables an unrelated driver, which is the failure this axis exists
to prevent, pointed the other way. Fail-expensive is a **default for the unclassified**, not a licence
to classify everything expensively.

### P-5 — Prefer the measurement you can take today, labelled for what it is

A cheap signal with an honest label beats an expensive signal that does not exist yet.

*Applied.* `agree.decode_vs_page` is free on every escalation — two independent extraction paths over
the same page — and it appears in the scoreboard in **its own column, headed "Agreement (not
accuracy)"**. `synth_ocr` (a born-digital PDF rendered to pixels at the OCR profile and OCR'd against
its known text layer) is genuinely independent, free and large, and is reported **per degradation level
L0..L4, never pooled**, with the calibration page printing the L4-versus-human gap.

*Over-applied.* Treating agreement as truth. Two drivers sharing a base model family can be wrong
identically, which is why `F23` pre-commits that until `ow eval correlate` reports, **only `audit`
verdicts may trigger a demotion**. The measurement you can take today is a signal; promoting it to a
label is what this principle does not license.

### P-6 — Put the constraint in the type; normalise once, at the boundary

A unit, an origin or a coordinate frame belongs in the type. The conversion happens at exactly one
place, at ingest.

*Applied.* The three coordinate systems are distinct types with **no implicit conversion, ever**, and
geometry has one stored frame and one constructor. docling supplies both halves of the lesson: its
`BoundingBox` carries `CoordOrigin` (BOTTOMLEFT for PDF/PPTX, TOPLEFT for images) *in the type*, which
is right, and then reconciles three live conventions per call site with
`.to_top_left_origin(page_height)`, which is a bug farm. Take the type; normalise once. `ts_a`/`ts_b`
(a `TextSpan`, chars inside one Block's text) and `os_*` (an `OriginSpan`, the address in the original
container) are separate for the same reason and are never mixed.

*Over-applied.* A `NewType` per unit everywhere. `Spend` is a vector of nine physical dimensions and
arithmetic over it must stay arithmetic; wrapping each component kills `Spend.micros(book)` for no gain.
The test is whether a wrong assignment is *plausible*: a `Quad` in the wrong frame is plausible;
`cpu_ms` added to `gpu_ms` is a bug that already reads as one.

### P-7 — The cheap mechanism runs first, and the expensive one may not re-cover its ground

Ordering is by cost class, and the expensive tier is *selected* by what the cheap tier failed to cover.

*Applied.* The shipped pass ladder orders on `(cost_rank, phase)` — `phase` is **within** a rank, so
every free pass precedes every `local_compute` pass and every `local_compute` pass precedes every billed
one, whatever the phases say, which is what keeps a third party's free extractor able to preempt a paid
one. The input selector for a billed pass **is** the `covered_frac` query, and the per-item gate is a
`cover_bits` bit test (`GR2`); `test_deterministic_first.py` asserts the join count is 0 on the fixture
corpus. The premise is measured: graphify ties dense RAG accuracy at **0.497 recall@10 on LOCOMO and 76%
on LongMemEval-S, at zero LLM build cost**.

*Over-applied.* Trusting the coverage claim. A pass that finds nothing and claims coverage is silent
recall loss shaped exactly like absence, which is why `GR3` requires `cover_empty` with an
`empty_reason` and `ow graph doctor` warns above a 0.98 empty rate. Deterministic-first is a cost rule,
not a permission to believe a free pass.

### P-8 — Prefer a schema constraint to a code path, and a generated code path to a hand-written one

*Applied.* Idempotence is a schema constraint, not a convention: `INSERT OR IGNORE` with no `UNIQUE`
index to conflict on is a plain `INSERT` (codegraph #1034 produced byte-identical duplicate rows that
inflated counts and flowed into callers), and SQL `NULL`s are each distinct, so a nullable natural key
needs an `IFNULL` sentinel — and because SQLite prohibits an expression in a table-level constraint,
that identity is **always a standalone `CREATE UNIQUE INDEX`**, never an inline `UNIQUE` (`ST10`). The
installing migration `GROUP BY`s the identical expression, sentinels included.

*Over-applied.* Reaching for a constraint the engine cannot compile. `RT8`'s monotone escalation
**cannot** be a `CHECK` — SQLite forbids a subquery in a `CHECK` body — so it is a generated
`BEFORE INSERT` trigger with CI parity against the policy compiler. Rejection-list items 20a and 20b
reject the two directions of this mistake: a `MAX_*` its own producer exceeds, and an inline constraint
SQLite cannot compile.

### P-9 — When two things must agree, generate one from the other

*Applied.* `schema/*.json` is generated from the Python definitions, committed and byte-diff gated, so
there is no IDL and no cross-language document model — L2 never crosses a language boundary. The
extraction prompt is rendered from `relation_vocab.actor_rule`, so prompt and schema cannot drift.
`tools/config_axes.toml` is generated from the `omniweave_core.config` declarations. The TypeScript
client is generated by `ow surface typescript` from the same gated schemas.

*Over-applied.* Generating a thing that then needs hand editing, which produces two sources of truth
plus a merge conflict. The rule has a precondition: the generator's input must be the *actual*
authority. Where it is not — a Toolchain's `ready` frame is produced by a different language reading the
same card — the honest answer is `F41`'s pre-committed fallback: a hard error on the Python side only,
with the TS runtime recording `CARD_KEY_UNKNOWN` into the receipt, **declared, not inferred**.

### P-10 — An override is named for its hazard, never for what complained

*Applied.* `--allow-cost`, `--allow-egress <grant-id>`, `--accept-partial`,
`--allow-unexplained-rebind`, `--allow-rebill`, `--ignore-evidence-cache`, `--allow-abandoned-gen`,
`--max-rung`, `--allow-tainted`, `--accept-manual`. There is no `--force` and no `--warn-only` anywhere
in the framework, because an override whose scope is "skip whatever complained" is an off switch, not
an override.

*Over-applied.* A flag per check. Forty flags nobody can audit is a worse surface than one. The unit is
the **hazard class**, which is why `--ignore-cache` was struck: it named a five-layer `cache_index`
rather than a hazard, and the hazard it actually authorised — re-billing — already had `--allow-rebill`.
The test for a new flag: name the hazard in three words. If you cannot, it is not a flag.

### P-11 — Cost and provenance are outputs, not footnotes

*Applied.* Every micro is attributable to exactly one `(unit, part, decision, attempt)`, and the manifest
self-checks it: `Σ route_spend.micros == manifest.cost.billed_micros`, **exactly** (`I30`). Metrics are
cached alongside the response and replayed with `was_cache_hit=True`, which is the only way to do cost
accounting when 90% of calls are hits — and the only source of
`cost.would_have_been_micros_if_uncached`. Provenance is six axes never conflated: reproduction, method,
ownership, trust, score, cost.

*Over-applied.* Pricing where the price is not known (INV-15), or conflating two axes because they
correlate. `origin_operator` (ownership: who may replace this row) and `trust` (how much the shape of
this row can be relied on) are different axes; graphify's own code conflates them, and eviction filtered
by `file_type` instead of `origin_operator` wrongly drops `INFERRED` and `AMBIGUOUS` items.

### P-12 — Refuse with a name; do not guess

When the right answer is not derivable, return a typed refusal carrying the command that clears it —
never the nearest plausible row.

*Applied.* An ambiguous unqualified cite across two touched corpora returns `OW_CITE_AMBIGUOUS_CORPUS`
(`OW-A-014`) listing the qualified candidates, rather than resolving. An ambiguous OUT edit address with
multiple text candidates and no `prev` is `OW-T-151`, refused rather than guessed (`OUT18`). A retired
cite whose `superseded_by IS NULL` is `OW_CITE_RETIRED` naming the generation it was retired at — never
a silent miss and never a nearby Block. Every one of these ends with the command that clears it (§6.4).

*Over-applied.* Refusing where a `Degradation` plus a partial answer is the honest response. A
`driver_unavailable` covering pages 12-40 is not a reason to refuse the query; it is a reason to return
`degraded` with the pages named. The test: can the caller act on the partial result without being
misled about what it covers? If yes, degrade; if no, refuse. Refusing a whole answer because one channel
is `unavailable` converts an honest partial into an unusable product.

### P-13 — Reserve the name, not the mechanism

Where a future shape is foreseeable, reserve the identifier at zero cost and build nothing.

*Applied.* `omniweave.operators` is a reserved entry-point group name that is deliberately **not
created**. `block_id` is laid out `(minting_shard_ord << 48) | sequence` and ships at shard 0 from day
one, with a CREATE-time literal `CHECK ((block_id >> 48) = 0)` in the `block` DDL (`ST20`), so a
Postgres T3 is a decision rather than a migration (F28). `omniweave-target-video` ships a card declaring
`implemented = false`. The `ow` vendor prefix is reserved across `x.ow.*`, the console script,
`<ow:untrusted>`, `data-ow-el`, the `ow:` answer markers and the four cite sigils. Each costs one line
now and removes a rename later.

*Over-applied.* Reserving a mechanism's *shape*. A reserved name constrains nothing; a reserved
interface is AP-2 — an abstraction with one implementation, where the implementation it encodes is the
one nobody has written. `omniweave.operators` stays uncreated precisely because creating it would fix a
contract around zero implementations, which is the failure the reservation exists to avoid.

## 3. The anti-patterns

Each row is a shape we have decided not to build, the place it was observed, and the mechanism that
forbids it here. A proposal matching a row needs evidence that the observed failure does not apply.

| # | Anti-pattern | Observed | What it cost | Forbidden here by |
|---|---|---|---|---|
| **AP-1** | **A serialized string as the interchange format** ("markdown as the document model") | Only 4 of 11 parsing repos expose anything beyond a markdown string; markitdown, omniparse, olmocr, HunyuanOCR, Unlimited-OCR and Ollama-OCR hand downstream a `str` | No citation-to-pixel, no round-trip and no layout-aware segmentation can be built on the output at all — and it happens silently: a caller who reads only the README never learns their pipeline forfeited it | No `html`/`markdown`/`md` field on any model class (`terminology.md` §4, a build-failing test); `serialize()` returns `(str, SpanMap)`, and a format whose `SERIALIZER_CAPS` entry is `False` may never be cited from; INV-1 |
| **AP-2** | **An abstraction with one implementation** | The rejected twelfth `omniweave-otel` distribution plus an `omniweave.sinks` entry-point group — "a third extension point created for one implementation"; `omniweave.operators` stays reserved and uncreated | An extension point with one implementation encodes that implementation's accidents as the contract, and the second implementation is then a rewrite | `omniweave-target-docx` ships at release 1 as the honest test that the OUT abstraction is not one implementation wearing an interface (`X33`); `omniweave.operators` is reserved and not created; `derive.code.treesitter`, whose distribution does not exist in tree, was **removed from the shipped ladder** rather than promised |
| **AP-3** | **Prompts as a correctness boundary** | ppt-master's own layer table states it — "prompts, templates, and examples … are not a correctness or safety boundary" — and its 137 KB design doc violates it in places; open-slide's vertical budget is arithmetic the model redoes by hand per page with no verification | A rule that lives only in a skill file is not enforced, and the failure is invisible in review because the prose reads like a spec | The framework validates from `rules()` plus `constructs.toml`; a target has no `validate()` and cannot reach its own report (`OUT2`, `OUT23`); overflow is a **finding** from an estimator shared with the checker, not a prompt instruction; every LLM-emitted row is span-grounded in the Block it cited (`GR5`) |
| **AP-4** | **The safety mechanism whose default disables it** | docling `max_file_size = sys.maxsize` and `max_num_pages = sys.maxsize` (`docling/docling/datamodel/settings.py:23-24`); docling's model `revision` defaults to `"main"` while its own field docstring says the field exists for reproducibility; olmocr builds `PdfFilter` with spam and form checks on but `--apply_filter` is `action="store_true"`; marker's `--use_llm` ships page images to Gemini by default; DataFlow's `--host` defaults to `0.0.0.0` in four places | The mechanism exists, the audit finds it, and it has never once run | Limits are host constants, not configuration, clampable down only (INV-22, `DR20`); `bytes_egress = 0` by default, so the first hosted escalation is a deliberate act requiring a site `Grant` with a `dpa_ref` printed in every affected run manifest, with `G15` asserting no compiled-in egress; `RT14` refuses a driver whose `weights_revision` is absent or `"main"`, with a named error |
| **AP-5** | **A second source of truth for "what is done"** | DataFlow's step-numbered `cache_step_{N}.json` has eight documented failure modes and its artifacts live outside the checkpoint model entirely; graphrag's `state: dict[Any, Any]` makes reordering the workflow list a `KeyError` hours in | Recovery becomes a second protocol that must agree with the first, and it does not | There is no checkpoint file: the `work` table's claimable set **is** the checkpoint; resume re-derives the plan from current inputs and subtracts what is done, and never replays a recorded plan; the proposal to sweep `done` rows and make `cache_index` the durable derivation record was rejected for exactly this reason |
| **AP-6** | **A soft fallback on an identity or safety input** | graphrag's `str()` fallback for an un-serialisable cache-key value ⇒ **permanent silent 100% cache miss**; `_EXTRACTOR_VERSION = "unknown"` sharing one AST namespace across every extractor version; `except Exception: return {}` around a baseline load | The system runs, produces output, and is wrong for months | INV-12; `G8` and `G24` ban a bare `except` around a digest, a cache key, a code fingerprint, a probe or a baseline read; config is JSON-canonicalisable **by contract** and an un-canonicalisable value is a startup error, with no `str()` fallback ever |
| **AP-7** | **A position used as an identity** | graphrag keys edges on `clean_str(title.upper())`, so a spelling drift makes two nodes, and its chunk id omits `document_id`, so identical text in two documents collapses into one `TextUnit`; `gen_sha512_hash` concatenates without a separator, so `["a","bc"]` and `["ab","c"]` collide | A shipped citation silently re-points at a different row | `cite`'s `n` is drawn from `doc.next_cite_n`, a per-`doc_key` monotonic counter never reset and never reused; `block_cite` is `UNIQUE(doc_ord, cite)` with **no `gen`**, so one cite names at most one row for the life of the corpus and inserting a Block on re-parse cannot re-point a shipped citation; `sha256_canonical` with `allow_nan=False`; INV-1's positional-FK ban |
| **AP-8** | **Computing a signal and consuming none of it** | docling computes the best per-page quality signals in the collection (parse/layout/ocr scores, grades POOR→EXCELLENT) and `do_ocr` is a **document-level boolean**; marker computes a table reconstruction confidence, uses it for the gate, then discards it | You pay for the signal, ship the routing bug anyway, and cannot even diagnose it afterwards | `RT4`: no evidence key is computed unless a reachable rule reads it, and keys compute in ascending `cost_class`; `Q-G10`: a declared `score_kind` that is never written **fails**. The signal and the router are one feature — ship both or neither |
| **AP-9** | **A label where a probability is needed** | marker gates the expensive per-block garble recheck on the page's `P(bad) ≥ 0.05`, which is only possible because surya's `OCRErrorDetectionResult` returns `scores` as well as argmax labels | Tiered routing becomes impossible, so the choice collapses to all-or-nothing and the expensive tier runs on everything | `RT5`: `SignalSpec` registration rejects `kind="classifier"` whose declared domain is not `[0.0, 1.0]`, closed on both ends because a softmax legitimately returns 0.0 and 1.0; `RT6` requires the probability to be calibrated (ECE ≤ 0.05, Brier ≤ 0.08 on a held-out set) |
| **AP-10** | **A warning that cannot fail** | ppt-master's report-level `passed-with-warnings`; graphify reports cache vintage, corruption and re-bill through `warnings.warn(RuntimeWarning)` — filterable, unstructured, invisible under JSON logging | The report rots. A template carrying 40 pre-existing warnings makes every generated artefact look broken, and the team stops reading it | No `--warn-only` anywhere; `pass_with_warnings` is not an eval status; `passed-with-warnings` is a **report** status and never a gate status; the headline count is `severity == error` **plus** `severity == warning AND provenance == INTRODUCED AND NOT baselined`, where `baselined` is computed by the harness from `eval/baselines/` and never declared by a generator |
| **AP-11** | **A general workflow engine, broker or service mesh under the pipeline** | DataFlow's RayOrch charges a wrapper tax — `AcceleratedOperatorABC` subclasses plus a `MemoryStorage` shim — so an operator is either local or distributed and porting is a rewrite; artifacts are paths, not payloads, and the row index is not stable under batching | A second durable store that must agree with the `work` table about what is done; a second scheduler's semantics between the operator and `ow why`; a service that must be running before `ow ingest` works on a laptop; tens of MB against a 250 MB aggregate gate | Four seams and no fifth (`S1`-`S4`); a long-lived local IPC daemon for parsing, embedding, indexing or scheduling is banned outright; one operator type, with distribution a property of the runner and the store backend — a Postgres T3 is `SELECT … FOR UPDATE SKIP LOCKED` and nothing else changes |
| **AP-12** | **A loopback TCP port for internal IPC** | LEANN's embedding server is a ZMQ REQ/REP socket on a dynamic loopback TCP port with no auth and no CURVE — any local process on a shared host or CI runner can submit text for embedding or probe msgpack paths | Compute theft and a DoS surface on any shared host, with no audit trail | `S2` and `S4` use stdio, 0600 unix sockets or owner-only named pipes; **two** loopback TCP endpoints are sanctioned and named — an attached or spawned model server (`S3`, a 32-byte token in a 0600 sentinel, model-id verification on attach) and `ow serve --http`, which refuses a non-loopback bind without `--api-key` (`OW_HTTP_BIND_UNAUTHENTICATED`, `OW-A-040`) — and a third requires a charter amendment |
| **AP-13** | **An untyped dispatcher on the agent surface** | The rejected `ow_do`; LEANN's hand-written `llms.txt` declaring 2 tools against a 4-tool server | An untyped `action: string` collapses the host's only authority control over a corpus of untrusted third-party documents; a hand-written manifest drifts silently and is read by a model that cannot know | Four listed tools plus narrow Actions; `SV1` (`listed ⊆ enabled`, `HUMAN_ONLY ∩ enabled = {}`) as a startup check; INV-20 and `G25` |
| **AP-14** | **Letting the model decide what to discard** | HunyuanOCR's parsing prompt instructs the model to ignore headers and footers, so furniture never exists in the output | Unrecoverable loss with no record that anything was dropped. A compliance query about a footer disclosure cannot be answered at all | `Layer` keeps `furniture` in the model — it is one of the five `Layer` values — and out of the body tree; suppression belongs in the **serializer**, which is a per-query choice; `raw_kind` retains the producer's own label through canonicalisation |
| **AP-15** | **Manifest-only licence scanning** | `cairosvg` (LGPL-3.0) is imported by `ppt-master/skills/ppt-master/scripts/svg_to_pptx/pptx_package/media.py` and `visual_review.py` and appears in **no** requirements file; AGPL PyMuPDF is a **mandatory** dependency of `leann-core` and `markitdown-ocr`, both of which advertise MIT, and `markitdown-ocr` self-registers via a `markitdown.plugin` entry point, so it is invisible once installed | An AGPL §13 network clause reaching a network-served product, discovered by counsel rather than by CI | `G3` resolves the **resolved dependency graph**, the **import graph** and the **unpacked artifacts** — three scans, with `cairosvg` as the regression fixture; `DR18` fails the build, never warns |
| **AP-16** | **Summing nested spans** | Summing `byte_length` over nested symbols inflated real source mass by **33.4% overall and up to 2.28× on one file**, non-uniformly — it tracks how class-heavy a file is | Every coverage, saving and concentration number built on it is wrong by a document-dependent factor, so cross-corpus comparison is meaningless | Blocks nest page ⊃ section ⊃ paragraph ⊃ table ⊃ cell, so any coverage number merges intervals first and carries a third **unmeasurable** bucket that is neither 0 nor a guess; `byte_offset == 0` cannot distinguish "unset" from "starts at byte 0", so absence is `NULL`, never a sentinel |
| **AP-17** | **An index sized for the author's corpus** | graphify's `nx.compose` union merge caps at `_MERGE_MAX_BYTES = 50 MB` and `_MERGE_MAX_NODES = 100_000` (`graphify/cli.py:2547-2548`), two to three orders of magnitude below a real corpus; 128-perm MinHash signatures for 1.5M entities is ~1.3 GB resident | The mechanism works in development and then OOMs, or refuses, on the first real corpus — after the whole cost of building up to the limit has already been paid | `entity_band` is a **persisted** table, never an in-memory index, rebuilt whenever `graph.resolve_signature` changes and checked at the top of every resolve pass; every ceiling is enforced at the read boundary with `take(N+1)`-then-check so a limit is never discovered after the memory is spent; `MAX_CLUSTER_EDGES = 8_000_000` names its escape rather than failing bare |
| **AP-18** | **A self-reported measurement that ranks** | HunyuanOCR's 94.10 OmniDocBench measured on TensorRT against a repo shipping Transformers and vLLM, which it admits disagree; a card `[[quality.benchmark]]` whose `attestation` is a hash over the card computed by the same kit run that wrote the values, so an author running the kit against a locally modified `omniweave-golden` gets `structure_f1 = 0.99` with a perfectly valid attestation (§5 C1) | A router optimises against a number nobody independently measured, and the driver that over-claims most wins the selection | `DR24`: a row whose `measured_on.corpus_digest` is not a digest in the omniweave release manifest is `witness = "self"` regardless of what it declares, and a `witness != "ci"` row is displayed, never ranked, and never read by `ow route propose`; `RT12` filters `source='self'` out of the scoreboard view; `Q-G9` refuses a metric whose reference producer is the subject producer |

Three of these deserve amplification, because they are the ones a well-intentioned pull request reaches
for.

- **AP-1 is not about markdown.** It is about any lossy serialization occupying the position of the
  model. A `SpanMap` beside the string is what makes `serialize()` legitimate: if you have the text you
  have the map, and there is deliberately **no text-only serializer**.
- **AP-3 is the most likely form of this project's own failure.** Anything stated only in a skill file,
  a prompt or a plan document is unenforced by definition. The correct handling of a genuinely
  unenforceable rule is to **label it unenforceable**, which is what hyperframes does and what
  ppt-master's own design doc fails to do in places.
- **AP-11 has a legitimate-looking version.** "Just use Celery for the ingest queue" is a proposal to
  add a second durable record of what is done. The question that settles it is `I6`: after a SIGKILL,
  which store is authoritative? If the answer is not "the `work` table, alone", the proposal is AP-5.

## 4. Using this document in review

### 4.1 What CI already answered — do not re-derive it

A reviewer who re-checks a machine-checked property wastes the review. These gates run on every PR (T0,
≤ 3 minutes) and their failure is not a review comment.

| the reviewer need not check | because |
|---|---|
| core's dependency set, the import DAG, the per-distribution dependency rule | `G1`, `G4`, `G9` |
| cold start, lazy submodules, no `asyncio` in core | `G10`, `G17`, `G23` |
| distribution weights and the 250 MB `[recommended]` aggregate | `G2` |
| licences across the resolved graph, the import graph and the unpacked artifacts | `G3` |
| every version declaration site against the tag | `G5` |
| every generated schema and every agent-facing artefact, byte for byte | `G6`, `G20`, `G25` |
| the banned-call list (`os.getcwd`, `Path(".")`, bare `subprocess`, `time.time()`, `sys.exit`, bare `except` around an identity fn, `revision="main"`) | `G8` |
| discovery never importing a rogue driver | `G11` |
| `codes.toml` append-only against the previous tag | `G13` |
| no compiled-in egress | `G15` |
| the previous two releases' template drivers against HEAD | `G16` |
| config-axis coverage, exactly one matching pattern per key | `G18` |
| incremental-vs-full equivalence over 300 documents in 40 mutations | `G19` |
| kill-9 recovery and the nightly 100k-roster scale run | `G21`, `G22` |
| no `sqlite3` outside the store module | `G24` |
| the hook path's p95 | `G26` |
| every fenced block in this document parsing, every migration applying in numeric order to an empty file, and the terminology lock in both directions | `G27` |

### 4.2 The ten questions a reviewer asks, in order

CI cannot answer these. They are ordered so a `no` at step *n* makes every step after *n* moot.

```text
1  WHO WRITES IT?      Does this change let a driver, a model or a caller write a field the
                       runner owns?  (INV-6, INV-7, INV-15)  -> reject
2  WHAT IS THE CLAIM?  Does it assert byte-exactness, a geometry, a trust tier, a confidence
                       digit or an absence?  If so, name the proof.
                       (INV-9, INV-10, INV-11, INV-19)  -> no proof, no claim
3  WHERE IS UNKNOWN?   For every three-valued input: what happens on unknown, and is the
                       branch declared?  (INV-12, RT7)  -> undeclared is a reject
4  WHAT IS THE NAME?   Is the name in terminology.md section 2?  Is it in section 3?  Does it
                       already name something else with a different type?  (INV-21, G27c)
5  WHERE IS THE HOME?  Does this fact now live in two places -- two columns, two config keys,
                       two registers, two implementations of one decision?
                       (INV-1, INV-23, rejection-list item 19)
6  WHAT ENFORCES IT?   Name the class: A, S, L, G or X.  Then count INDEPENDENT enforcers --
                       two rules in one semgrep config are one.  If the honest answer is R
                       alone, the property is a principle and the PR claims an invariant it
                       does not have.  (ladder rules 1 and 2)
7  COULD IT BE HIGHER? Is there an A- or S-class enforcement available that this PR
                       implemented at X?  (ladder rule 3)
8  WHAT DOES IT COST?  Does a clean born-digital page pay anything new?  Does a cache hit pay
                       anything?  (INV-13, I25)
9  WHAT IS THE EXIT?   Every refusal names the command that clears it; every terminal state
                       has a sweep; every rejected item is retained.  (charter 6.4, I7, INV-25)
10 WHAT IS THE OPEN?   If a number here is under an F-item, does the PR pre-commit the
                       fallback, or silently assume the optimistic branch?  (charter 7)
```

### 4.3 The rejection list

A pull request is wrong, without further argument, if it does any of the following. Items 1-22 are the
charter's §8 in substance, each with the one-line test a reviewer runs; items 23-27 are this document's
extensions and carry §1b's amendment caveat.

| # | Rejected because it | The one-line test |
|---|---|---|
| 1 | adds a runtime dependency to `omniweave-core`, or makes `import omniweave_core` import a lazy submodule | `git diff packages/omniweave-core/pyproject.toml`; grep the nine lazy names in `__init__.py` |
| 2 | hands a driver anything beyond `DriverIO`, or adds a field to `DriverIO` | count `DriverIO`'s fields |
| 3 | lets a driver write `producer_id`, `trust`, `restriction_bits`, `origin_driver`, a cache hit or a price | grep the sink signatures and `DriverResult` for those names |
| 4 | puts a `block_id`, an `entity_id`, an `addr`, a path or a UUID into a prompt | grep the prompt builder's parameter types for anything but the four `Cite` NewTypes |
| 5 | synthesizes a `Quad`, or returns `quad = None` without a `reason` | grep for `Quad(` outside `Quad.from_driver` |
| 6 | labels a Block byte-exact without a retained part **and** an `OriginSpan` re-verified on `bytes`, `nodepath` or `glyphs` | find the re-read; if there is no re-read there is no claim |
| 7 | adds a second path to `VerdictState.ABSENT`, or a second citability rule | count `return VerdictState.ABSENT` |
| 8 | writes a bare `except` around a digest, a cache key, a baseline read, a probe or a retrieval channel | `G8` and `G24` catch it; if the PR touched the semgrep config, read that diff first |
| 9 | computes a `LOCAL_COMPUTE` signal, renders a raster, or starts a model server for a clean born-digital page | the three exact counters; ±1 fails |
| 10 | passes a ledger, a clock, an RNG or a `RunContext` into `evaluate()` or `plan()` | read the two signatures |
| 11 | puts a currency field on a driver-facing type or a card | grep for `micros`, `usd`, `cost_` on those types |
| 12 | drops `restriction_bits` on a derived row, or lets `compile` emit a restricted item without policy | every new derived table's DDL; the compile aggregate at plan **and** at compile |
| 13 | calls `sqlite3.connect`, `conn.commit()` or `BEGIN` outside `omniweave_core/store/` | `G24` |
| 14 | stores a second copy of a Block's text, structure or geometry | the schema lint's FK classification, and the new columns' names |
| 15 | publishes a number without `(n, ci95, method, MeasuredOn, witness)`, or renders a digit for an uncalibrated confidence | construct the row; `MeasuredOn` raises `TypeError` if it is short |
| 16 | hand-writes an agent-facing artefact | `G25` |
| 17 | introduces a name `terminology.md` §3 lists as a rejected synonym | `G27(c)` |
| 18 | adds `--force`, `--warn-only`, `--fix`, or an override whose scope is "skip whatever complained" | name the hazard in three words; if you cannot, reject |
| 19 | adds a fifth seam, a sixth version axis, a second error register, a second chunking, a second matcher, a second absence-gate list, a second renderer, a second home for one config key, or a second name for one column | ask which of the two is authoritative; if the answer is "both", reject |
| 20a | ships a `MAX_*` its own producer is designed to exceed | find the enforcement site; if it does not read `N+1`, the name is wrong and the number is a `*_TARGET_*` |
| 20b | ships an inline `UNIQUE`/`PRIMARY KEY`/`CHECK` SQLite cannot compile (an expression in a table constraint, a subquery or a bind parameter in a `CHECK`, a parameter in a view) | apply the migration to an empty file (`G27(b)`) |
| 21 | prints a TOML, JSON or SQL block in a charter or plan document that does not parse | `G27(a)` |
| 22 | ships a warning that cannot fail | find the status that lets a release proceed with it |
| 23 | binds one name to two types, or one config key to two homes | INV-21; `G27(c)` and `G18` |
| 24 | names a ceiling something its producer overshoots, or reads a `MAX_*` from config | INV-22 |
| 25 | adds a second implementation of one semantic decision, including a validator with its own parser | INV-23 |
| 26 | commits or ships a generated artefact that is not byte-reproducible from its declared inputs | INV-24; run it twice under the determinism harness |
| 27 | disposes of a rejected, superseded or unresolved item automatically and without a record | INV-25; ask who asked for the disposal, and where it is written down |

### 4.4 How to write the rejection

Cite the number and the enforcer, and stop. "This violates INV-7: `trust` is written by the runner after
the driver returns, and the generated `BEFORE INSERT` trigger would reject these rows anyway" is a
complete review comment. An invariant does not need to be re-argued in a PR thread; if the author
believes the invariant is wrong, the venue is the five-part ADR against the charter's §2, not the diff.

For a principle, the comment must carry the concrete cost. "P-4 says fail expensive, and classifying
`drivers.enabled` as semantic re-bills the whole corpus whenever an operator enables an unrelated
driver" is a review comment; "this violates P-4" is not.

### 4.5 What a reviewer may NOT reject for

This section exists so the checklist cannot become an obstruction.

- **A decision the charter already made**, including one the reviewer disagrees with. `vectors = "off"`
  by default, `use_lcc` permanently off, `ord_path` permanently rejected, store-per-tenant at v1, no
  published npm package at v1: these are settled, and the venue is an ADR.
- **A locked name.** If it is in `terminology.md` §2, it is the name. If the reviewer believes it is the
  wrong name, they amend §2 in the same change and expect to be asked whether it is really a new
  concept.
- **A number under an open F-item.** `F1`-`F41` name numbers nobody has measured yet, each with a
  pre-committed fallback. A PR that ships the charter's default and cites the F-item is correct; a PR
  that ships a *different* number without a measurement is not.
- **Style, in place of substance.** A reviewer who cannot name an invariant, a principle with its cost,
  or an anti-pattern has an opinion, not a rejection.
- **The absence of a test for a property already enforced at a higher class.** If the violation is
  unrepresentable (`A`) or rejected by the schema (`S`), demanding a unit test as well is asking for a
  test of the type checker. Ladder rule 2 is the one exception that survives this: a second enforcer is
  required when a single edit can disable the first.

## Open questions

Questions 1, 2 and 3 are **answered**. They keep their numbers so existing citations resolve; what
follows each is the ruling, not a restatement of the question.

1. **The INV-21..INV-25 amendment — answered by
   [ADR-2](adr/0002-invariant-and-gate-registers.md).** The five are invariants and there are
   **twenty-five**. Charter §2's "Twenty properties." is superseded at charter §9.2 `E30`;
   `tools/invariants.toml`'s five rows carry `force = "invariant"` and `adr = "ADR-2"`, and
   `terminology.md` §2 gains their `invariant`-kind rows in the lock's bulk pass. A reviewer cites them
   as invariants without qualification. What keeps the count honest is
   `gates.invariant_register` clause 5 (§1e), not this paragraph.

2. **The two charter enforcer-column defects — answered by
   [ADR-2](adr/0002-invariant-and-gate-registers.md).** (a) INV-1's charter §2 row credited **`G6`**
   with `import(export(store)) == store`. The round-trip check is **`G28`** (§INV-1), a new `G` row in
   `tools/gates.toml`; `G6` remains `ow schema emit --check` and is not renumbered, because four
   correct citations name it. (b) INV-19's charter §2 row named only `Q-G8` and `Q-G14`; **four
   enforcers stand**, including the `A`-class raise at `DocSink.add_block` and the frozen `MeasuredOn`
   (§INV-19). Charter §9.2 `E31` and `E32` record both, and §INV-1 and §INV-19 are the sole homes.

3. **The ladder is now mechanical — answered by
   [ADR-2](adr/0002-invariant-and-gate-registers.md).** `tools/gate_invariants.py` reads
   `tools/invariants.toml` as the `[[job_assertion]]` **`gates.invariant_register`** (job `gates`,
   2 s), **not** as a clause `G27(e)`: `G27(d)` is spent on `tools/gate_docs.py`
   ([repository layout](11-repo-layout.md) §8.6), and a register's semantics are not a document check.
   §1e states the five clauses. Rule 2's independence check ships the two decidable cases — two rules
   in one semgrep config, and a trigger-plus-mapping pair with or without a parity gate — and the
   general case stays undecidable and stays `R`. The evidence that would widen it is a measured count
   of how often one edit disables two enforcers of one invariant.

4. **The inbound half of INV-8 has no enforcer for the in-scope case.** `GR9` rejects an emitted cite
   outside `allowed_cites`; nothing detects an injected cite-shaped string that happens to name a Block
   *inside* the handed set, which re-attributes a claim within that set. **Closes when:** someone
   measures whether `GR5`'s span-grounding gate already catches it — an injected re-attribution still
   has to quote text that exists in the block it names — by extending the 40-payload `derive_injection`
   conformance suite with cite-shaped payloads. If grounding catches it, say so and cite `GR5`; if not,
   the answer is a defanging rule for cite-shaped runs inside `<ow:untrusted>` blocks, applied **on a
   copy**, exactly as chat-template sentinels are handled today, with the block re-labelled `normalized`
   and counted in the trailer (`SV12`).

5. **Erasure of source content is undesigned.** INV-25 governs automatic disposal and explicitly does
   not forbid an operator's named, bounded, recorded reclamation — but no such command exists for
   *source* content, and a licence revocation or an erasure request needs one. It cannot be a plain
   `DELETE`: `block_history`, `artifact_cite` and every shipped citation reference those rows.
   **Closes when:** [security, privacy and licensing](14-security.md) decides between tombstoning with
   content redaction (the row and its cite survive; the text and the retained part do not) and corpus
   re-derivation from a filtered roster, and names the command. Until then the honest answer to an
   erasure request is "rebuild the corpus without that unit", and this document says so rather than
   implying a capability that does not exist.

6. **Whether P-5's labelling discipline needs an enforcer.** "Agreement (not accuracy)" is currently a
   column heading in a generated scoreboard, which makes it `G`-class for that one surface and `R`-class
   everywhere else. **Closes when:** `tools/scorekinds.toml` gains a required `interpretation` field per
   `score_kind` — one of `accuracy`, `agreement`, `self_report`, `derived` — that every renderer must
   print adjacent to the number, at which point P-5 becomes a candidate invariant. Until it is measured
   against a real surface it stays a principle.

7. **The anti-pattern register has no gate, by design, and that may be wrong.** `AP-1` through `AP-18`
   are review-time objects. Four are mechanically detectable and already gated: `AP-1` by the
   `html`/`markdown`/`md` field ban, `AP-6` by `G8`/`G24`, `AP-15` by `G3`, `AP-18` by `DR24` plus
   `Q-G9`. **Closes when:** someone determines whether `AP-8` — a computed-but-unconsumed signal — is
   detectable as a static property. `Q-G10` catches the declared-but-never-written direction; the
   written-but-never-read direction needs a reachability analysis over the compiled policy's demand
   plan, which `RT4` already builds. If it is detectable, `AP-8` becomes an invariant; if not, the
   register stays review-time and this document says so.

## New terms

Coined here. Each needs a row in `terminology.md` §2; the rows land in the lock's bulk pass under
[ADR-1](adr/0001-terminology-lock-bulk-pass.md), which is also where `sites` (§1e) is locked.

| Term | Kind | Definition |
|---|---|---|
| **enforcement class** | concept | One of six labels — `A` architecture, `S` schema, `L` lint, `G` gate, `X` test, `R` review — naming *how* an invariant is enforced. Ordered; enforce at the highest available class. |
| **the ladder** | concept | The ordering `A > S > L > G > X > R` and its three rules (§"The enforcement classes"). Cited as "the ladder" in a review comment. |
| **independent enforcer** | concept | Two enforcers are independent when one edit cannot disable both. Two semgrep rules in one config are one enforcer; a generated trigger and the mapping it came from are two only while a parity gate compares them. Every invariant carries ≥ 2, and never `R` alone. |
| `INV-21` … `INV-25` | invariant | The five framework-wide invariants this document adds: one name/one type/one home; a ceiling is never a target; one implementation per semantic decision; byte-reproducibility of every committed and shipped artefact; nothing is disposed of silently. |
| **principle** (`P-n`) | concept | A named rule governing a judgment call no invariant decides. A reviewer may reject on one only by naming the concrete cost. Thirteen at release 1. |
| **anti-pattern** (`AP-n`) | concept | A named shape this project has decided not to build, traced to a measured failure in the mined collection. Proposing one requires evidence the observed failure does not apply. Eighteen at release 1. |
| **rejection list** | concept | The table in §4.3. A row's number is a complete review rejection. |
| **the ten questions** | concept | The ordered reviewer sequence in §4.2, covering what CI cannot answer. |
| `tools/invariants.toml` | file | The machine-readable invariant register (§1e): one `[[inv]]` per invariant, carrying its force, owning document, enforcer ids (`enforcers`), un-numbered enforcer `sites`, classes and independent-enforcer count. Identifiers resolved by `G27(d)`; row semantics asserted by the `gates.invariant_register` job assertion. |
