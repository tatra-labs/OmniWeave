# D8-out — The OUT compiler contract and closing the loop (ecosystem / operator proposal)

## Headline

**There is no `GeneratorTarget` abstraction over "generation". There is a Target, and a Target is
exactly four artefacts a contributor can write in an afternoon: a `constructs.toml` table, a rule
pack of one-function-per-file predicates, a `lower()`, and a `read_back()`. Everything else —
findings, provenance classes, the source fingerprint, the ten-value gate, the asset ledger, the
feedback marker grammar, the receipt, the round-trip laws, the CLI, the docs — is framework code
that every target gets for free and no target may reimplement.** The IL is not a schema and not a
new grammar: it is *a closed, declared subset of an existing text format*, where the subset is
**data** (a construct table) and the enforcement is **code** (rules that call the compiler's own
parsers). And `parse_back` is not a special code path: it is an ordinary `parse/1` Driver with an
ordinary `driver.toml`, so a generated deck re-enters the corpus through the pipe that already
exists, inherits D3's discovery, conformance, licence and restriction machinery unchanged, and the
loop closes with **zero new plumbing**.

---

## 0. Consistency with settled law, and the one amendment I ask for

I use D1's names verbatim: `omniweave_core`, `omniweave-target-pptx` / `-deck` / `-video`,
`omniweave-conform`, the **job directory** (`job.json` / `il/` / `assets/` / `out/`), the
`omniweave-target/1` NDJSON-on-stdio protocol with its `hello` / `ready` / `validate` / `compile` /
`result` frames and its exit codes, `OW-T-nnn` error codes in the append-only `codes.toml`,
`$OMNIWEAVE_HOME`, `omniweave.toml [targets] enabled`, and the rule that a target **refuses rather
than substitutes** a codec.

I use D2's names verbatim: `Block`, `block_id`, `addr`, `cite`, `content_digest`, `layout_digest`,
`Quad`, `OriginNodePath`, `TextSpan`, `SpanMap`, `Quote`, `Trust`, `Method.ROUNDTRIP`, `Producer`,
`Diag`, `DocSink`, `rel(derived_from)`, the `asset` / `part` / `page` / `block` tables, and the
`Capabilities` vocabulary.

I use D3's names verbatim: the `compile/1` and `parse/1` Ports, `DriverCard` / `driver.toml` /
`card_schema` / `card_sha256`, `DriverIO`, `DriverResult`, `ArtifactRef`, `FailureClass`,
`restriction_bits`, `Restriction`, `compute_tier`, `attestation`, `RejectCode`, `resolve()`, and the
rule that discovery never imports.

I use D4's names verbatim: `Spend`, `PriceBook`, `Degradation`, `degradations[]`, `Grant`,
`dpa_ref`, `bytes_egress = 0`, `decision_id`, and the rule that a budget-exhausted result is
success-shaped with a banner, never `isError`.

**Three readings that a judge will check, resolved rather than fudged:**

1. **D1's `omniweave.targets` entry-point group vs D3's `compile/1` Port.** Both stand. A *Target*
   is the operator-facing artefact name (`pptx`) that appears in `omniweave.toml [targets] enabled`
   and in the `omniweave.targets` entry-point group. It resolves to exactly one `compile/1` driver
   id (`compile.pptx.native`) and at most one `parse/1` driver id (`parse.pptx.owpptx`), both named
   inside `[capability.compile]` on the compile driver's ordinary `driver.toml`. D3 already ruled
   this shape: *"D8 gets `compile/1`, `capability.compile.*`, `parse_back` as a named `parse/1`
   driver id **on the card**"*. So the `omniweave.targets` group is a **routing alias** and every
   execution goes through D3's driver host, its licence gate and its restriction refusal. **I ask
   for no new top-level table on the card**, because D3 makes an unknown top-level table a hard
   error; everything D8 needs lives under `[capability.compile]`, where D3 makes unknown keys a
   recorded degradation rather than an error.

2. **D3's "a driver never receives a writable `output_root`" vs a compiler that emits a 40 MB
   PPTX.** No conflict. The compile driver writes into `io.tmpdir`, returns `ArtifactRef`s, and the
   **host** promotes them to `output_root`. On the Toolchain path, `job_dir/out/` *is* that tmpdir
   and D1 already says the toolchain writes there. The receipt is written by the child; the artifact
   is moved by the parent; `EXIT 0 IFF a receipt was written` (D1) is the only success signal.

3. **D1 says `omniweave-core` has zero third-party dependencies; D2 says `omniweave-core` depends on
   pydantic and zstandard.** Not my decision and I do not reopen it. I note only that
   `omniweave_core.out` needs **neither**: it is `tomllib`, `hashlib`, `base64`, `json`, `zipfile`
   and `dataclasses`. Every carrier *parser* (XML, JSX, HTML) lives in the target distribution, never
   in core — which is also why `defusedxml` sits in `omniweave-target-pptx` and gate G1 stays intact.

### The one amendment I ask for — D2 §5, quotability of a round-tripped OOXML block

D2 §5 states the invariant, and the DDL restates it:

> `-- INVARIANT: quote = 'verbatim' requires os_kind = 'bytes' AND part.store_ref IS NOT NULL.`

D2 §5 also rules, correctly and on ppt-master's verified evidence, that the stable address for an
OOXML part is **`OriginNodePath`**, not a byte range: *"ppt-master's verified
`SourceRefRecord.source_path`, which survives edits to other subtrees where a byte range into
`word/document.xml` does not"*.

Taken together, **no block recovered by `parse_back` from a PPTX or DOCX can ever be `verbatim`**,
even though omniweave wrote those bytes itself, retains the part, and can prove the text matches.
The best available tier is `normalized`, so D2's own consequence — *"Serve (D10) may claim
byte-exactness for a minority of blocks"* — silently excludes the one document class where we have
perfect knowledge. That is a real defect for the closed loop: an agent editing last quarter's
generated deck is told the text it is quoting is not byte-exact when it demonstrably is.

**Minimum amendment (D2 §5 and the `part` DDL comment), stated so it can be refused cheaply:**

> `quote = 'verbatim'` requires (`os_kind = 'bytes'` OR (`os_kind = 'nodepath'` AND the addressed
> node's text content, decoded under `os_codec`, equals `block.text` under NFC)) AND
> `part.store_ref IS NOT NULL`.

Cost: one extra clause in `owcheck`, one extra property test in the driver testkit
(`normalize_nfc(node_text(part_bytes, os_path)) == block.text`), zero schema change. **My design
works without it** — every `parse_back` block simply lands at `quote = normalized`, the loop still
closes, and serve declines the byte-exactness claim. I flag it because refusing it silently would
degrade a product claim nobody would trace back to this line.

---

## 1. What an IL is here

The blueprint's sketch says `il_spec — closed subset of a general format + registered mapping per
construct`. That is right and it is not yet a design, because it does not say *what kind of object
the spec is*. Three candidates, and the evidence rules out two.

**Not a schema.** A JSON Schema over the carrier cannot express the three things the verified
sources actually need. It cannot express *"`mix-blend-mode` is legal input with a deterministic
degradation into a raster"* (ppt-master `_BAKE_REQUIRED_VISUAL_PROPERTIES`,
`svg_contracts.py:180-188`). It cannot express the **conditional prohibition** — `id=` is an error
*only when `<style>` is also present*, because the hazard is the pair and `id` inside `<defs>` is
required (verified in ppt-master's source comment). And it cannot express *"the third occurrence of
an undeclared type size is an error"* (`checker.py` check 9, `_undeclared_size_occurrences:
Counter[str]`), which is a cross-element budget, not a shape.

**Not a new grammar.** Nobody is going to write, maintain and document a parser for a bespoke
authoring language, and no third party will learn one. All three mined repos independently chose an
**existing text format** as the carrier — SVG (ppt-master), TSX (open-slide), HTML with `data-*`
timing attributes (hyperframes `packages/parsers/src/compositionContract.ts:11-32`, verified). Zero
of three invented syntax. That is not a coincidence; it is the adoption constraint. An LLM authors
SVG and TSX far better than it authors a tree of JSON objects, `git diff` is legible, an editor
highlights it, and every existing tool works.

**So: an IL is a triple** — a **carrier**, a **construct table**, and a **rule pack**.

```
IL(target) = ( carrier , constructs.toml , rules/ )
             ^^^^^^^^^   ^^^^^^^^^^^^^^^   ^^^^^^
             an existing  the CONTRACT      the ENFORCEMENT
             text format  (data, diffable,  (code, one rule
             + its parser  generates docs)   per file, testable)
```

The construct table is the load-bearing invention. Every allowed construct is one row declaring a
**disposition** — and the disposition set is five, not ppt-master's three, because ppt-master's
"compatible" channel and its `manual_required` outcome are the two missing tiers:

| disposition | meaning | validator | compiler |
|---|---|---|---|
| `native` | the one canonical spelling; a registered mapping exists | silent | `maps_to` symbol |
| `normalize` | a documented alias with **one** deterministic normalization | **warning** with the canonical replacement text, a count and ≤3 examples | normalizes, records in the conversion trace |
| `bake` | the target cannot express it, but a deterministic degradation exists | **warning** naming the bake command | rasterizes to a ledger asset |
| `manual` | recognized, unverifiable, refuses to guess | **error** `manual-required` | unit outcome `manual_required` |
| `forbidden` | no mapping, ambiguous, or produces an invalid package | **error** | never reached |

ppt-master's severity doctrine is adopted verbatim as the promotion/demotion protocol between rows,
and it goes in the target's `CONTRIBUTING.md` because it decides who fixes what:

> *"Severity is determined by whether the input maps deterministically and legally, not merely by
> whether it uses the recommended spelling."*
> *Warning volume is a prompt bug (fix the agent-facing doc). Warning danger is a contract bug (move
> the row to `forbidden` and change the checker in the same commit).*

**One implementation of "what does this construct mean."** ppt-master's validator imports ~40 symbols
from the compiler (`svg_quality/svg_contracts.py`), so there is exactly one answer to "what does
`fill=` mean", and a missing import degrades to *a warning visible in the report*, never a silent
pass. I take that and make it a **two-way CI gate**, which ppt-master does not have: every
`maps_to` symbol in `constructs.toml` must resolve in the lowering module (`OW-T-001
CONSTRUCT_UNMAPPED`), **and** every public lowering symbol must be named by exactly one row
(`OW-T-002 CONSTRUCT_UNDECLARED`). A compiler cannot grow support for a construct the contract does
not admit, and the contract cannot promise a construct the compiler does not implement.

**The construct table is the documentation.** `ow out constructs pptx --format md` renders the
agent-facing IL reference from the same rows the checker and compiler read, with a per-target token
budget declared on the card (`agent_doc_tokens_max`) and gated in CI. This is ppt-master's
`prompt_audit.py` insight (64 per-file budgets, 95 load sets, 27 finding codes — the real shape of a
skill-surface context budget) at ~2% of its cost, and it retires the 137 KB hand-written
`technical-design.md` that the digest correctly flags as violating its own doctrine.

---

## 2. The validator gate

### 2.1 A rule is a function, and the framework runs it

Verified from hyperframes `packages/lint/src/types.ts:52-56`:

```ts
// A rule is a function: receives parsed context, returns zero or more findings.
export type LintRule<TContext> = (ctx: TContext) => HyperframeLintFinding[] | Promise<...>;
```

18 files under `packages/lint/src/rules/` (9 rules + 9 test files, 1:1). That is the shape, and it
is the direct answer to ppt-master's 9,368-line single validator class, which the digest names as a
trap. The framework supplies the runner, the context, the finding record, the timing attribution and
the report; a target supplies functions.

hyperframes also supplies the operability detail worth copying exactly (`types.ts:20-27`): timings
are attributed **per rule-source module plus the single slowest rule as `<group>#<index>`, so a
pathological rule is locatable**. A validator with no per-rule timing becomes a validator nobody runs.

### 2.2 Ten framework rules every target gets for free

This is the adoption argument as a number. A new target starts with ten working, tested rules and
writes roughly fifteen of its own.

| rule | code | what it enforces | why it is framework-level |
|---|---|---|---|
| `cite.resolves` | `OW-T-101` | every `data-ow-cite` resolves in the store at the pinned `gen` | `cite` is D2's, not the target's |
| `cite.quoted` | `OW-T-102` | an element claiming `data-ow-quote="verbatim"` matches its cited block's `text` under NFC | the only mechanical check on fabrication |
| `cite.coverage` | `OW-T-103` | when the brief sets `citations = "required"`, every text run over `min_chars` carries a cite | D4's `grounded_field_frac`, applied to generation |
| `asset.resolved` | `OW-T-111` | every `asset-slot:<sha256>` has an `asset` row and a `store_ref` | the ledger is framework-owned |
| `asset.no-external` | `OW-T-112` | no `http(s)://`, `file:`, `data:` URI survives into the IL | ppt-master's portability audit, promoted to a rule |
| `asset.permitted` | `OW-T-113` | no asset's `restriction_bits` is barred by policy | D3-17 |
| `brief.forbidden` | `OW-T-121` | no `## forbidden` row of the brief is violated | the brief grammar is framework-owned |
| `brief.anchor-drift` | `OW-T-122` | an undeclared value within `±drift` of an anchor may appear twice; **the third occurrence is an error** | ppt-master check 9, and it is target-independent |
| `plan.bijection` | `OW-T-131` | exactly one IL file per plan unit and one plan unit per IL file | kills open-slide's index-aligned-arrays trap outright |
| `marker.clean` | `OW-T-141` | no unresolved feedback marker survives into a release compile | the marker grammar is framework-owned |

### 2.3 Findings carry a provenance class

ppt-master's `_provenance_categories` (`checker.py:9192-9230`) is, per the digest, its most
under-appreciated idea and neither other repo has it. Adopted verbatim, four classes:
`blocking` (errors) / `introduced` (warnings the generator caused) / `inherited` (byte-identical in
the template the unit derives from) / `source-import` (arrived through a tolerant import or through
`parse_back`). One function feeds both the console and the JSON so they can never disagree. Without
it, a corporate template carrying 40 pre-existing warnings makes every generated deck look broken
and the team stops reading the report — which is the same failure as no report at all.

### 2.4 Static rules in Python, runtime rules over NDJSON

The genuine split, and the reason the two Toolchain targets are not second-class:

- **Static rules** run in Python against a `CarrierDoc`. Always available, licence-free, no Node, no
  browser. `ow out lint` runs only these; budget **≤ 40 ms per unit** on a 200-element page,
  CI-gated.
- **Runtime rules** need the carrier's own runtime — real text metrics, real layout. They are
  delegated to the toolchain over D1's existing `{"t":"validate","id":1,"il":"il/main.tsx"}` frame,
  which returns `{"t":"result","status":"blocked","findings":[…]}` in exactly the `Finding` shape
  below. The framework ships the 40-line TS receiver in `toolchains/_shared/` so a toolchain author
  writes rules, not protocol.

This is the mechanical answer to the digest's sharpest OUT criticism: *"The fixed-canvas overflow
problem must be measured, not prompted."* open-slide's 1080 px vertical budget (usable 840 px at
120 px padding, ≤5 bullets, hero 140–200 / body 32–44) is excellent guidance and a bad architecture
because the LLM redoes the arithmetic by hand per page with no verification. ppt-master shares
`text_measure.py` between compiler and checker so overflow is a *finding*; hyperframes measures off
canvas via `window.__hyperframes.pretext` and emits `text_box_overflow` / `canvas_overflow` /
`clipped_text`. omniweave: `RuleCtx.measure(node) -> Box | None`, target-supplied, and **`None` is
a recorded skip in the report, never a pass** — ppt-master's try/except-ImportError-to-warning
discipline generalized.

### 2.5 The gate is a ten-value enum bound to bytes

ppt-master's release gate is eight statuses plus a ninth report-level `passed-with-warnings`
(`pptx_package/cli.py:1243-1315`), of which exactly one lets a release proceed. I keep all of them
and add exactly two, each for a condition the mined repos never faced:

- `restricted` — the artifact would embed a block or asset whose `restriction_bits` policy bars
  (D3-17: *"the `compile` host refuses, naming the item ids"*).
- `manual-required` — one or more units reached the `manual` disposition. Distinct from `failed`
  because the fix is a human, not a re-author.

`not-provided` stays distinct from `failed` for exactly ppt-master's reason: "you never ran the
gate" and "you ran it and it found errors" are different user errors and need different messages.
Every non-`passed` status prints the exact command that clears it (D1's error-message rule).

Bound to bytes, not to a filename. ppt-master's `source_fingerprint`
(`checker.py:9335-9368`) — basename-sorted, `name\0sha\n` framing, an unreadable file contributing
the literal `unreadable` plus an error entry rather than dropping out — is adopted verbatim as
`il_digest`, **and so is the discipline that the compiler recomputes it with an independent
implementation** over the files it is about to compile, so drift surfaces as `stale`. In omniweave
the two implementations are `omniweave_core.out.report.source_fingerprint` (checker side) and the
target host's own recomputation before lowering; a divergence is `OW-T-004 FINGERPRINT_DIVERGED`
and is a bug in one of them, which is the point.

### 2.6 Two gates, and no auto-fix

Cadence adopted from ppt-master with its economics stated: an **early gate** at unit 5 treating the
first five units as a *method sample* and classifying the whole issue set into method-level /
unit-local / not-yet-exercised, fixed in one consolidated loop; rosters of **≤6 units skip it**;
**zero checker calls between the early gate and the final gate**, because each call is a context
round-trip. The classification that ppt-master leaves to a prompt is mechanical here:
`ow out check --early` groups findings by `(rule, code)` and labels a group `method-level` when it
fires on ≥3 of the 5 sampled units, `unit-local` otherwise, and lists every construct row with
`disposition = native` that the sample never exercised as `not-yet-exercised`.

**No auto-fix, ever.** ppt-master, verbatim: *"It intentionally has no auto-fix: a mechanical patch
can silently overwrite valid design intent and ship a worse page."* `ow out lint --fix` does not
exist and will be refused in review.

---

## 3. Determinism and byte reproducibility

`compile()` is a pure function of five digests, all recorded in the receipt and all in the
`artifact` table's unique index:

```
artifact_bytes = f( il_digest , constructs_digest , ledger_digest ,
                    card_sha256 (compile driver) , toolchain_digest | NULL )
```

**`repro` is declared per target and is a three-value ladder, because pretending video is
byte-stable is a lie the first ffmpeg point release exposes:**

| value | claim | how the conform kit proves it |
|---|---|---|
| `bytes` | two compiles of identical inputs produce identical bytes | compile twice in two temp dirs, different cwd, different `TMPDIR`, `SOURCE_DATE_EPOCH=0`; `assert sha256(a) == sha256(b)` |
| `normalized` | two compiles agree under a declared normalizer | `assert repro_digest(a) == repro_digest(b)`; the normalizer is a named function on the card and its own output is fixture-tested |
| `none` | no claim | the kit asserts the card does **not** also claim `parse_back` T2 (below), because idempotence is undecidable without a comparison |

For `pptx`, `bytes` is achievable and the mechanics are not optional — every one of these is a
non-determinism a naive python-pptx writer ships:

```
ZIP entry order        sorted by part name, fixed
ZIP timestamps         (1980,1,1,0,0,0) for every entry            # the ZIP epoch
ZIP compresslevel      pinned integer, recorded in the receipt
docProps/core.xml      dcterms:created == dcterms:modified == job.json.determinism.clock_ns (0)
                       cp:revision = "1"; cp:lastModifiedBy = ""   # never getpass.getuser()
generated ids          seeded PRNG, seed = sha256(il_digest)[:8]   # never uuid4(), never id()
dict iteration         every emitted attribute map sorted before serialization
float formatting       EMU integers only; no repr(float) reaches the XML
```

D1's `{"determinism":{"seed":0,"clock_ns":0}}` block in the `hello` frame already carries the same
contract to a Toolchain, and D1 already concedes the residual: *"Allowing `node` on PATH means two
renders of the same job can differ; the receipt records the resolved version and a mismatch is a
`degradations[]` entry rather than a refusal."* I accept that verbatim and add the operator control:
`[targets.<name>] repro_strict = true` promotes that degradation to a refusal for a fleet that needs
it, and the failure message names the resolved and expected Node versions.

**The gate:** `ow out compile --repro-check` runs the double compile locally; CI runs it over the
whole fixture corpus on every PR touching a target. It doubles compile time on fixtures only. It is
the single highest-value gate in this design because it catches the entire class of "works on my
machine, differs in the artifact" without anyone reasoning about it.

---

## 4. The asset ledger

**There is no new asset model.** D2 already defines `asset(asset_id, doc_ord, media_type,
origin_part, sha256, byte_len, width, height, store_ref, licence, licence_url, spdx, source_url,
retrieved_at_ns)` with `store_ref = cas://ab/cd/<sha256>` and `NO INLINE BYTES, EVER`. The OUT
ledger is that table plus one join table, `artifact_asset`.

That matters, and hyperframes shows why. Its `.media/manifest.jsonl` is the best asset ledger in the
collection and its record shape, verified at `skills/media-use/scripts/resolve.mjs:509-534`, is:

```js
{ id, type, path, source, description, duration, width, height, transparent, entity,
  provenance: { provider, prompt, ...heygenAuthMethodFor(provider), ...metadata.provenance } }
```

**There is no licence field, no SPDX, no attribution requirement and no restriction code anywhere in
it.** A frozen asset with a prompt and a provider but no licence is reproducible and undeliverable.
D2's `asset` table already carries `licence`, `licence_url` and `spdx`; D3 already carries
`restriction_bits` and `Restriction.ATTRIBUTION_PER_OUTPUT`. Reusing them closes hyperframes' gap
for free, and it is why I refuse a second ledger file.

**What omniweave takes from hyperframes and keeps:**

- **Freeze to a local file, always.** `freezeUrl` / `freezeLocalFile`
  (`skills/media-use/scripts/lib/freeze.mjs`) with `MAX_FREEZE_BYTES = 256 * 1024 * 1024`, a
  `content-length` pre-check *and* a streaming abort so a lying chunked body cannot buffer to
  memory, and an empty-response error. Becomes `omniweave_core.limits.MAX_ASSET_BYTES = 268435456`
  under D1's clamp rule (`effective = min(tenant_cap, MAX_*)`), and a breach is
  `OW_RESOURCE_LIMIT{limit="MAX_ASSET_BYTES"}` naming the knob.
- **The SSRF guard,** but not hyperframes'. Its own comment is honest that a DNS name resolving to a
  private IP still passes. omniweave has one guarded egress path already — D2: *"A driver NEVER
  opens a socket: egress is `ctx.fetch` (one guarded path) or nothing."* — and D4 sets
  `bytes_egress = 0` by default. So: **a compile that needs to fetch refuses**, with
  `Degradation(kind="grant_missing")` whose message names the site-layer `Grant` and its `dpa_ref`.
  That is the correct default for a framework whose users are enterprises, and it is D4's ruling,
  not mine.
- **Content-addressed cross-project reuse** (`~/.media/`, SHA-256): becomes
  `$OMNIWEAVE_HOME/cas/` shared across projects, with the per-project `.owstore` holding the rows.
- **Occurrence tracking.** ppt-master's `image_manifest.json` records one entry per unique media
  *part* with an `occurrences[]` array and, cleverly, `display_ratio_variants` — the same image
  placed at two aspect ratios means the deck is stretching it, which the next placement needs to
  know. `artifact_asset.units` is the JSON array of unit ids; `display_ratio_variants` becomes a
  computed rule (`OW-T-114 ASSET_RATIO_INCONSISTENT`, warning).

**The wire form is a token, not a path.** An IL references an asset only as
`asset-slot:<sha256-hex>`. ppt-master invented this token as an internal normalization step before
hashing (`authoring_roundtrip.py:979-1041` rewrites `data-icon` to `asset-slot:<baseline_key>`); I
promote it to the wire format. The consequences are large and cheap: the IL is location-independent
so it compiles identically on another machine, the round-trip hash needs no path normalization at
all, and `ow out lint` can validate asset references with no filesystem access.

**Bake assets are ledger assets.** A `bake` disposition rasterizes and writes an `asset` row with
`role = 'bake'` and `source_url = NULL`, so the raster is content-addressed, cached across compiles
and visible in the receipt. Which brings the honest problem:

> **The bake tier has no licence-clean rasterizer on day one.** Verified: ppt-master's bake path is
> `cairosvg` (LGPL-3.0), imported at `svg_to_pptx/pptx_package/media.py:15` and declared in **no**
> requirements file — it is the exact regression fixture D1's gate G3 and D3's `licence` suite
> exist to catch. Its documented fallback (`media.py:19-21`) is `svglib`, also LGPL-3.0. D1's
> `tools/licences.toml` denies `LGPL-3.0*` and names `cairosvg` explicitly.
>
> **Day-one ruling: `bake` is fail-closed for the `pptx` target.** A bake-required construct is
> `OW-T-311 BAKE_UNAVAILABLE` with two named exits printed in the message: remove the property, or
> supply the raster yourself (`ow out assets add <file> --slot <name>`, which writes the ledger row
> and hands you the token). When the `deck` toolchain is installed, `ow out compile --bake` routes
> rasterization through it, because a Node-side rasterizer whose SPDX passes `tools/licences.toml`
> is a solved packaging problem and a Python-side one is not. Naming a specific crate here would be
> an unverified claim; the licence gate is the decider and the open question below says so.

---

## 5. Element-addressed feedback

Two-factor addressing, taken from open-slide's `findElementForEdit` and stated as the doctrine the
mining notes give it: **location proposes, content disposes, uniqueness arbitrates.** A positional
anchor is cheap and goes stale; a content anchor is robust and needs uniqueness; an element with
multiple text candidates and no `prevText` is a **refusal, not a guess**.

**Presence is the state.** open-slide's `@slide-comment` marker lives in the source, its payload is
base64url so the marker grammar stays a fixed regular language regardless of what the user typed,
its line number is *derived from position, not stored*, a corrupt payload is skipped rather than
fatal, application is in reverse line order, and **skip is a legal outcome with a defined
representation** (leave the marker, report it). Present after a claimed application is a failure
signal. No side table can disagree with the artifact because there is no side table.

The framework owns the grammar and the verbs; a target owns one function:

```
marker  ::= <carrier-comment-open> "OWC1:" base64url(json) <carrier-comment-close>
json    ::= {"id": "<ulid>", "ts": <int ms>, "kind": "note"|"edit", "text": "<utf8>",
             "at": {"addr": "<ow-src>", "prev": "<prevText|null>"}}
```

Carrier comment syntax comes from the target's `CarrierDoc.comment_syntax`; placement comes from the
target's `place_marker(node) -> Insertion` (open-slide's JSX-container rule, generalized). Everything
else — scan, decode, order, apply, verify-cleared, report-skipped — is
`omniweave_core.out.marker`, one module, shared.

**Transactionality is not negotiable.** open-slide's `edit-ops.ts` is the safest renderer→source
edit path in the collection (1,223 lines against 1,146 lines of test, ≈1:1) and the mechanism is:
a **closed five-op set**, collect all splices → apply back-to-front → **reparse → all-or-nothing**
(`422 edit would produce invalid source`), with unmodelled source **carried through verbatim** (a
non-object `style` expression is preserved as a spread with new properties appended, not dropped and
not guessed). And the policy encoded in two parse functions one line apart: an error-recovering
parse for read-only transforms, a strict parse that rejects any recovered error for anything that
writes. All of it is adopted; the op set is per-carrier and declared on the card.

**No local HTTP server at v1.** open-slide's write endpoint needs `request-guard.ts` — verified at
exactly **76 lines** — as a *minimum* (`Sec-Fetch-Site`, origin normalize-and-compare honouring
`x-forwarded-proto`'s first comma token, explicit rejection of the literal `null` origin, JSON
content-type required), and D1 bans loopback listeners for the pipeline outright. So v1's feedback
channel is the file: a human or an agent writes markers into `il/`, `ow out comments apply` resolves
them. A preview server is a later, separate distribution that must ship that guard verbatim on day
one of its existence.

---

## 6. `manual_required`, and unit-outcome classification

ppt-master's round-trip export classifies **100% of output units into four fidelity tiers and
asserts the sum**, treating an unclassifiable page as a hard error and printing the counts
(`pptx_package/cli.py:2951-2990`). That is a reviewer-checkable invariant and it generalizes. I
extend it to seven outcomes so it covers create *and* edit *and* refusal in one enum:

```
native  baked  passthrough  cloned_passthrough  patched  rebuilt  manual_required
```

Every unit lands in exactly one; `sum(counts) == len(plan.units)` or `OW-T-005
UNIT_UNCLASSIFIED` is fatal; the counts are printed on one console line and stored in
`artifact_unit`. `reason` is **required** for `manual_required` and `baked`.

`manual_required` is reached through a declared content-family table, not a vibe. ppt-master's
(`workflows/profiles/image-to-pptx.md:53-68`) is the model, and its two governing rules are adopted
verbatim because they are the ones that keep it from collapsing into "the model gives up":

> *"Hard rule — separate layer need from realization: source clarity never decides whether a
> required editable, movable, or overlapping object becomes a separate layer, only **how** that
> layer is prepared."*
> *"Graphic identity is authoritative; source pixel bytes are not."*

And the observation/decision split, which is the reason it works: `plan.json` records **only what
is present** — unit id, bbox, observed family, verbatim text, confidence, sufficiency, occlusion,
overlap — and explicitly no realization choices, no prompts, no output filenames, no IL bindings.
Decisions live in the IL. That keeps the observation reusable and stops the model rationalizing an
observation to fit a decision it already made.

**The escape hatch is named, never `--force`** (D4's rule). `ow out compile --accept-manual`
produces a **draft**: each `manual_required` unit gets a placeholder carrying
`data-ow-manual="<reason>"`, the gate status stays `manual-required`, the receipt records
`delivery: "draft"`, and `parse_back` of a draft writes `Diag(OW_MANUAL_REQUIRED)` rows so the
placeholder is machine-detectable forever after. A draft can never be mistaken for a release,
because the release path reads the gate status and there is exactly one status that passes.

---

## 7. The brief — a frozen contract, not a conversation

open-slide has the best question design in the collection — four questions each chosen because it
collapses a downstream decision tree, options generated per topic rather than drawn from a preset
list, one call, a "(Recommended)" default so silence is a valid answer — **and it persists none of
it**. ppt-master and hyperframes both persist and neither asks as well. Take the question design
from open-slide and the persistence from the other two.

The persisted artifact is ppt-master's `spec_lock.md` grammar verbatim: a schema-version HTML
comment as line 1, then **only** `## section` headings and `- key: value` lines, except
`## forbidden` whose items are literal rules. Human-diffable, machine-parseable, validator-enforced.
Three tiers of prohibition with different owners, and the enforcement that makes the tiers real:
**the validator rejects an untagged non-baseline row**, so nobody can smuggle a designer opinion
into the hard-constraint list, and a `(user)` row is the user's sentence verbatim, never a paraphrase
and never widened.

Two more rules carried across because they are cheap and they work:

- **The role that consumes the lock cannot write it.** In omniweave that is mechanical: `ow out
  brief` writes it, `ow out lint|check|compile` open it read-only, and a compile whose brief digest
  differs from the one in the last report is `stale`.
- **A scheduled re-read every five units with explicitly no side effects** — no checker run, no
  output, no repair loop — purely to fight long-context drift. This lives in the agent-facing
  workflow doc, and per ppt-master's own doctrine it is *labelled unenforceable* rather than
  pretended to be a gate.

---

## 8. `parse_back` — the fidelity contract as three testable laws

`parse_back` is a `parse/1` Driver. It has a `driver.toml`, a `DriverCard`, a `capability.parse`
block in D3's vocabulary, a probe, a licence block, and it runs under `omniweave-conform`'s eleven
suites like any other parser. It writes through `DocSink` like any other parser (D2's stated
obligation). It stamps `method = Method.ROUNDTRIP` on every block — the enum member D2 already
defines. **The loop closes through the pipe that already exists.** No new operator, no new port, no
new table, no new cache tier, no new conformance surface.

What "fidelity" means is stated as three properties the conform kit executes. This is the part the
blueprint left as a wish and it is where a target lives or dies.

### Law T1 — address survival (mandatory, every target)

> For every Block `b` referenced by a `data-ow-cite` in the IL, let `a = compile(il)` and
> `d = parse_back(a)`. Then `d` contains a Block `b'` with `rel(derived_from, b', b)` and
> `b'.content_digest == b.content_digest`.

Losing an address is a hard failure. Losing geometry is not. `content_digest` is the right
comparator precisely because D2 excludes geometry, spans, marks and producer from it — a target that
rounds a coordinate does not fail T1, and a target that drops a word does.

### Law T2 — one-shot idempotence (mandatory unless `repro = none`)

> `compile(to_il(parse_back(compile(il)))) ≡_repro compile(il)`

The loop converges after one iteration. This is the property that catches a reader silently dropping
a construct: the second artifact differs. It is also the property that makes "editing a generated
deck is the same code path as creating one" a *test result* rather than an architecture diagram.
Under `repro = bytes` the comparison is `sha256`; under `normalized` it is `repro_digest`.

### Law T3 — declared loss, enforced in both directions

> `[capability.compile.round_trip] loses = ["<construct id>", …]`
>
> For every construct **not** in `loses`, a fixture exercising it satisfies T1 and T2.
> For every construct **in** `loses`, the round trip emits `Diag(OW_ROUNDTRIP_LOST, {construct})`.

Undeclared loss is a test failure. **Over-declared loss is also a test failure** — declaring you lose
something you actually keep is D3's exact capability rule (*"declaring `spatial = "none"` is not a
failure; declaring `line_bbox` and returning none is"*) applied in the mirror direction, and it is
what stops a lazy target from declaring `loses = ["*"]` to get a green report.

### What must survive, what may be lost

| must survive T1/T2 | may be lost, and must be declared |
|---|---|
| `cite` and `addr` of every addressable block | geometry below the target's grid quantum (PPTX: 1 EMU; deck: 1 px) |
| `text` under NFC | `mark` kinds outside the target's declared set |
| reading order (`ord`) | `score` / `score_kind` |
| `kind` under the card's declared `kind_map` | `layer = hidden` where the target has no hidden layer |
| table cell topology (`r`, `c`, `row_span`, `col_span`) | `raw_kind` |
| asset identity (`asset.sha256`) | every construct row listed in `loses` |
| `rel(caption_of)`, `rel(continues)` | |
| `restriction_bits` | |

**What must never be invented.** `parse_back` writes `quote = Quote.RECONSTRUCTED` for anything it
did not read as text from the artifact, `Trust.INFERRED` wherever the `kind_map` is many-to-one, and
`Trust.EXTRACTED` only where the artifact's own structure states the answer. Absent the D2 §5
amendment above, the ceiling on an OOXML round trip is `Quote.NORMALIZED`.

**The honest weakness, stated before a reviewer finds it:** we test our own reader against our own
writer. A jointly-wrong pair passes T1, T2 and T3 forever. The only defence is a fixture corpus of
artifacts **we did not author** — `fixtures/out/foreign/` holds real decks and documents from
outside the project, and T1/T3 (not T2, which needs an IL) run against them. That corpus is a
standing maintenance obligation with a named owner, exactly like D3's index and lockfile.

### How citations physically survive

| target | into the artifact | out of the artifact | claim on the card |
|---|---|---|---|
| `pptx` | `<p:extLst><p:ext uri="{6F2A…-OMNIWEAVE}"><ow:cite v="d7#412"/></p:ext></p:extLst>` on the shape | `python-pptx` `shape._element` read, containment rule documented per ppt-master's API-stability disclosure | `citations = "embedded"` |
| `deck` | `data-ow-cite` attribute on the JSX host element | AST read, same acorn parse the toolchain already runs | `citations = "embedded"` |
| `video` | **nowhere in the MP4** — a `.owcite.jsonl` sidecar plus a WebVTT chapters track | sidecar only | `citations = "sidecar"` |

`citations = "sidecar"` is a first-class, machine-readable admission that mailing the artifact alone
loses the provenance, and D9's serve layer must render it. Pretending otherwise is the kind of
quiet lie this whole design exists to prevent.

---

## 9. Concrete shape

```
packages/omniweave-core/src/omniweave_core/out/          # STDLIB ONLY. No carrier parser lives here.
├── finding.py     Severity · Provenance · Disposition · Finding · FindingSet · fold()
├── constructs.py  ConstructTable · load_constructs() [tomllib] · constructs_digest()
├── rules.py       Rule · RulePack · run_pack() · RuleTimings (per-group + slowest rule)
├── carrier.py     CarrierDoc / CarrierNode / Insertion Protocols       (NO implementation)
├── report.py      OutReport · source_fingerprint() · schema "omniweave.out-report.v1"
├── gate.py        GateStatus (10) · gate_status(report, fingerprint) -> (GateStatus, int)
├── plan.py        Plan · Unit · UnitOutcome (7) · classify_and_assert()
├── brief.py       Brief · parse_spec_lock() · validate() (rejects untagged non-baseline forbidden)
├── ledger.py      AssetLedger over D2's `asset` · freeze() · slot_token() · MAX_ASSET_BYTES
├── marker.py      OWC1 grammar · scan() · apply_reverse() · assert_clean()
├── receipt.py     Receipt · CheckValue ("passed"|"warning"|"enforced-at-build"|"skipped"|…)
├── roundtrip.py   law_t1() · law_t2() · law_t3()   — executable predicates, imported by the kit
└── target.py      TargetCard (from driver.toml [capability.compile]) · TargetHost · CompileV1

packages/omniweave/src/omniweave/out/cli.py              # ow out …
packages/omniweave-conform/src/omniweave_conform/suites/target/   # the 12th suite

packages/omniweave-target-pptx/src/omniweave_target_pptx/
├── driver.toml            compile.pptx.native   [capability.compile]
├── constructs.toml        the IL contract — 1 row per construct
├── carrier_xml.py         CarrierDoc impl over defusedxml            (~500 LoC)
├── rules/                 one rule per file, one test per rule
│   ├── r_viewbox.py  r_forbidden_elements.py  r_style_surface.py  r_mask.py
│   ├── r_fonts.py  r_text_capacity.py  r_paint_canonical.py  r_image_fit.py  …
├── lower/                 the compiler: shapes, text, paths, tables, charts, media
├── measure.py             text metrics — SHARED with r_text_capacity.py                (the whole point)
└── back/
    ├── driver.toml        parse.pptx.owpptx   [capability.parse]
    └── reader.py          python-pptx -> DocSink

toolchains/_shared/target-runtime.ts     hello/ready/validate/compile NDJSON loop (framework-owned)
toolchains/deck/  toolchains/video/      rules/ + lower/ , written against it

fixtures/out/
├── golden/<target>/       one fixture per construct row — the kit maps rows to fixtures
├── foreign/               artifacts WE DID NOT AUTHOR — T1/T3 only
└── expected/              snapshot baselines; `--bless` to update            (D1's shape)
```

### `constructs.toml` — the IL contract as data

```toml
# omniweave_target_pptx/constructs.toml
schema  = "omniweave.out-constructs.v1"
carrier = "xml/svg"
version = 3                        # ENTERS constructs_digest AND the cache key

[[construct]]
id          = "attr.font-size"
selector    = "@font-size"
disposition = "native"
canonical   = "font-size=\"24\""            # finite unitless px semantics
maps_to     = "lower.text_properties:font_size"
code        = "OW-T-201"
since       = "0.1.0"

[[construct]]
id          = "attr.font-size.pt"
selector    = "@font-size[unit=pt]"
disposition = "normalize"
normalizes_to = "attr.font-size"
rule        = "px = round(pt * 4 / 3, 3)"   # deterministic, single-valued, unit-tested
code        = "OW-T-202"

[[construct]]
id          = "style.mix-blend-mode"
selector    = "@style|mix-blend-mode"
disposition = "bake"
bake        = { renderer = "raster", dpi = 192, role = "bake" }
code        = "OW-T-311"

[[construct]]
id          = "elem.style"
selector    = "svg|style"
disposition = "forbidden"
code        = "OW-T-301"
msg         = "use inline attributes instead"

[[construct]]
id             = "attr.id"
selector       = "@id"
disposition    = "native"                   # id inside <defs> is REQUIRED
forbidden_when = "svg|style"                # ...but an error when <style> is also present
code           = "OW-T-302"
msg            = "CSS selectors are forbidden; id is only harmful paired with <style>"

[[construct]]
id          = "elem.foreignObject"
selector    = "svg|foreignObject"
disposition = "forbidden"
code        = "OW-T-303"
msg         = "use <tspan> for manual line breaks"

[[construct]]
id          = "region.unverifiable-brand-mark"
selector    = "@data-ow-family=logo[confidence<0.8]"
disposition = "manual"
code        = "OW-T-401"
msg         = "brand identity is not verifiable from the source at this resolution"
```

`forbidden_when` is one field and it buys the verified conditional prohibition exactly. `bake` and
`manual` are rows, not special cases in code. A row with `disposition = "native"` and no `maps_to`
fails `OW-T-001` at load; a lowering symbol with no row fails `OW-T-002`.

### The target card — one new block on an ordinary `driver.toml`

```toml
# omniweave_target_pptx/driver.toml
card_schema = 1

[driver]
id             = "compile.pptx.native"
port           = "compile/1"
version        = "0.1.0"
schema_version = 1
title          = "PPTX (native DrawingML)"
summary        = "Canonical SVG subset -> editable native PowerPoint shapes. No Node."
entrypoint     = "omniweave_target_pptx.driver:PptxCompiler"
granularity    = "document"
deterministic  = true

[capability]
formats  = ["application/vnd.openxmlformats-officedocument.presentationml.presentation"]
consumes = ["il_unit", "asset"]              # closed, core-owned artifact kinds (D5 owns the vocab)
produces = ["artifact", "receipt"]

[capability.compile]
target            = "pptx"                    # the omniweave.targets alias; omniweave.toml enables THIS
carrier           = "xml/svg"
constructs        = "constructs.toml"         # package data; its sha256 enters card_sha256
constructs_digest = "sha256:71c4…"
il_version        = 3
repro             = "bytes"                   # bytes | normalized | none
citations         = "embedded"                # embedded | sidecar | none
assets            = ["image", "bake", "font", "audio", "video"]
bake              = "unavailable"             # available | unavailable | toolchain:<name>
toolchain         = ""                        # "" => pure Python
runtime_rules     = false                     # no `validate` frame; all rules are static
measure           = "uharfbuzz"               # the metrics engine SHARED by checker and compiler
agent_doc_tokens_max = 6000                   # ow out constructs pptx --format md, CI-gated
unit_outcomes     = ["native","baked","passthrough","cloned_passthrough","patched","rebuilt",
                     "manual_required"]

[capability.compile.round_trip]
parse_back = "parse.pptx.owpptx"              # D3: "parse_back as a named parse/1 driver id on the card"
laws       = ["t1", "t2", "t3"]
fidelity   = "passthrough"                    # D2 Capabilities.round_trip ladder
loses      = ["style.mix-blend-mode",         # baked: the raster survives, the property does not
              "attr.vector-effect",
              "elem.marker.custom-path"]
kind_map   = "kind_map.toml"                  # Kind <-> PPTX shape family; the T1 comparator's contract

[hardware]
gpu = "none"; needs_network = false; needs_binaries = []; imports_torch = false
install_bytes = 58_000_000                    # under D1's 60 MB ceiling for this distribution

[isolation]
requires = "subproc"; memory_mb = 2048; progress_ms = 15_000; wall_ms_hard = 300_000
batch_max_units = 1                           # one artifact per invocation

[licence.code]
spdx = "Apache-2.0"; licence_sha256 = "sha256:…"; redistribution = "allowed"
output_share_alike = false; competitor_bar = false; attribution_per_output = false
```

```toml
# omniweave_target_pptx/back/driver.toml   — parse_back is an ORDINARY parse driver
card_schema = 1
[driver]
id = "parse.pptx.owpptx"; port = "parse/1"; version = "0.1.0"; schema_version = 1
entrypoint = "omniweave_target_pptx.back.reader:PptxReader"
granularity = "document"; deterministic = true; detects = true
[capability]
formats = ["application/vnd.openxmlformats-officedocument.presentationml.presentation"]
consumes = ["raw_bytes"]; produces = ["doc_fragment"]
[capability.parse]
spatial = "block_bbox"      # PPTX geometry is exact EMU; every shape has one
charspan = true
reading_order = "source"    # a slide's shape tree IS the order
sections = "typed_levels"
tables = "cells_with_spans"
math = []
assets = "bytes"
notes = "linked"            # speaker notes are a real linked part
confidence = "none"
furniture = "separated"     # placeholders vs body is declared in the layout
round_trip = "passthrough"
```

### Types

```python
# omniweave_core/out/finding.py
class Severity(StrEnum):    ERROR="error"; WARNING="warning"; INFO="info"
class Provenance(StrEnum):  BLOCKING="blocking"; INTRODUCED="introduced"
                            INHERITED="inherited"; SOURCE_IMPORT="source_import"
class Disposition(StrEnum): NATIVE="native"; NORMALIZE="normalize"; BAKE="bake"
                            MANUAL="manual"; FORBIDDEN="forbidden"

@dataclass(frozen=True, slots=True)
class Finding:
    code: str                        # OW-T-nnn — MUST exist in codes.toml  (gate G13: append-only)
    severity: Severity
    provenance: Provenance
    rule: str                        # "pptx.style.blend@1"
    unit: str                        # plan unit id, "p03"
    msg: str
    fix: str                         # the exact command or edit. NEVER EMPTY — asserted in __post_init__
    at: str | None = None            # "il/p03.svg:41:9"
    node: str | None = None          # the data-ow-src address inside the carrier
    construct: str | None = None
    canonical: str | None = None     # REQUIRED iff Disposition.NORMALIZE — the replacement TEXT
    count: int = 1                   # occurrences FOLDED; 200 lowercase hex colours => ONE finding
    examples: tuple[str, ...] = ()   # <= 3, asserted   (ppt-master `remember_example`)

# omniweave_core/out/rules.py
class RuleCtx(Protocol):
    doc: "CarrierDoc"
    unit: "Unit"
    plan: "Plan"
    constructs: "ConstructTable"
    brief: "Brief"
    cites: "CiteResolver"            # by_cite() ONLY. No writes, no full store handle.
    limits: Mapping[str, int]
    def measure(self, node: "CarrierNode") -> "Box | None": ...   # None => RECORDED SKIP, never a pass

Rule = Callable[[RuleCtx], Iterable[Finding]]

@dataclass(frozen=True, slots=True)
class RuleTimings:                   # hyperframes packages/lint/src/types.ts:20-27, verbatim intent
    total_ms: int
    group_ms: Mapping[str, int]
    slowest_rule: str                # "<group>#<index-in-group>" — a pathological rule is LOCATABLE
    slowest_rule_ms: int

# omniweave_core/out/carrier.py — a PROTOCOL. No parser in core. Targets implement it.
class CarrierNode(Protocol):
    kind: str
    def attr(self, name: str) -> str | None: ...
    def text(self) -> str: ...
    def children(self) -> Iterator["CarrierNode"]: ...
    def src(self) -> tuple[int, int]: ...        # (line, col) — the target INJECTS these
    def ow_addr(self) -> str | None: ...         # data-ow-src / data-slide-loc equivalent

class CarrierDoc(Protocol):
    comment_open: str; comment_close: str        # "<!--" / "-->"  |  "/*" / "*/"
    def root(self) -> CarrierNode: ...
    def select(self, selector: str) -> Iterator[CarrierNode]: ...   # constructs.toml's selector dialect
    def place_marker(self, n: CarrierNode) -> "Insertion": ...      # the ONLY per-carrier feedback hook
    def source(self) -> str: ...
    def splice(self, edits: Sequence["Splice"]) -> "str | ParseError": ...
    # applySplices: sort DESC by `from`, apply, REPARSE, all-or-nothing.  open-slide edit-ops.ts.

# omniweave_core/out/gate.py
class GateStatus(StrEnum):
    NOT_PROVIDED="not-provided"; UNREADABLE="unreadable"; UNSUPPORTED_SCHEMA="unsupported-schema"
    NON_FINAL="non-final"; UNVERIFIED="unverified"; FAILED="failed"; STALE="stale"
    RESTRICTED="restricted"; MANUAL_REQUIRED="manual-required"; PASSED="passed"
# EXACTLY ONE value lets a release proceed. `passed-with-warnings` is a REPORT status, not a gate one.

def gate_status(report: "OutReport", recomputed: "SourceFingerprint") -> tuple[GateStatus, int]:
    """Ordered predicate cascade. Returns (status, introduced_warning_count).
       report absent            -> NOT_PROVIDED   (distinct from FAILED. Different user error.)
       unparseable              -> UNREADABLE
       schema mismatch          -> UNSUPPORTED_SCHEMA
       stage != 'final'         -> NON_FINAL
       blocking count not int   -> UNVERIFIED
       blocking > 0             -> FAILED
       restricted items present -> RESTRICTED        (D3-17)
       manual_required units    -> MANUAL_REQUIRED
       fingerprint mismatch     -> STALE
       fingerprint unavailable  -> UNVERIFIED
       else                     -> PASSED"""

# omniweave_core/out/plan.py
class UnitOutcome(StrEnum):
    NATIVE="native"; BAKED="baked"; PASSTHROUGH="passthrough"
    CLONED_PASSTHROUGH="cloned_passthrough"; PATCHED="patched"; REBUILT="rebuilt"
    MANUAL_REQUIRED="manual_required"

def classify_and_assert(plan: "Plan", outcomes: Mapping[str, UnitOutcome]) -> Mapping[UnitOutcome, int]:
    """Every unit lands in exactly one bucket and the sum is asserted. An unclassifiable unit is
       OW-T-005 UNIT_UNCLASSIFIED, FATAL — never a warning.  (ppt-master cli.py:2951-2990)"""

# omniweave_core/out/target.py
class CompileV1(Protocol):
    PORT: ClassVar[str] = "compile/1"
    @classmethod
    def probe(cls, env: "ProbeEnv") -> "ProbeVerdict": ...
    def __init__(self, **config: Scalar) -> None: ...     # STATIC CONFIG ONLY (D3)
    def carrier(self, path: str, text: str) -> CarrierDoc: ...
    def rules(self) -> Mapping[str, Sequence[Rule]]: ...  # group -> rules; the pack
    def lower(self, plan: "Plan", il: "ILSet", ledger: "AssetLedger",
              io: "DriverIO") -> "DriverResult": ...      # writes into io.tmpdir. NEVER output_root.
    def postflight(self, artifact_path: str, plan: "Plan") -> "Receipt": ...
    # There is NO validate() on this Protocol. The FRAMEWORK validates, using rules() and
    # constructs.toml. A target that could run its own gate could skip it.
```

### The report and the receipt

```jsonc
// report.json — schema "omniweave.out-report.v1"
{
  "schema": "omniweave.out-report.v1",
  "target": "pptx", "il_version": 3, "stage": "final",
  "constructs_digest": "sha256:71c4…", "brief_digest": "sha256:0aa1…",
  "source_fingerprint": {                       // ppt-master checker.py:9335-9368, verbatim framing
    "algorithm": "sha256", "digest": "…", "file_count": 12,
    "files": [{"file": "p01.svg", "sha256": "…"}, {"file": "p07.svg", "sha256": null,
               "error": "source bytes were not available during validation"}]
  },
  "summary":  {"total": 12, "passed": 9, "warnings": 3, "errors": 0},   // FILES, one bucket each
  "issue_types": {"font": 2, "capacity": 1},                            // FINDINGS. Two denominators.
  "categories": {                                // who owns this finding
    "blocking":      {"count": 0, "findings": []},
    "introduced":    {"count": 3, "findings": [ /* Finding */ ]},
    "inherited":     {"count": 1, "findings": []},
    "source_import": {"count": 4, "summary": {"warning_count": 4, "by_code": {"OW-T-202": 4}}}
  },
  "skipped_checks": [{"rule": "pptx.text.capacity", "reason": "measure() unavailable: uharfbuzz absent",
                      "fix": "pip install omniweave-target-pptx"}],   // VISIBLE. Never a silent pass.
  "units": [{"unit": "p03", "outcome": "manual_required", "reason": "brand mark confidence 0.61"}],
  "cites": {"declared": 41, "resolved": 41, "verified_verbatim": 38, "unresolved": []},
  "assets": {"slots": 9, "frozen": 9, "external_refs": [], "restricted": []},
  "timings": {"total_ms": 412, "group_ms": {"style": 88, "text": 201},
              "slowest_rule": "text#3", "slowest_rule_ms": 140},
  "degradations": []                             // D4's channel, rendered by D9
}
```

```jsonc
// receipt.json — schema "omniweave.out-receipt.v1"    (written by the COMPILER, in out/)
{
  "schema": "omniweave.out-receipt.v1",
  "status": "passed | passed-with-warnings | failed",
  "delivery": "release | draft",                 // draft iff --accept-manual
  "output": {"path": "out/q3.pptx", "bytes": 1284211, "sha256": "…"},
  "repro": {"mode": "bytes", "digest": "…", "seed": "sha256(il_digest)[:8]",
            "toolchain": null, "node": null},
  "inputs": {"il_digest": "…", "constructs_digest": "…", "ledger_digest": "…",
             "card_sha256": "…", "brief_digest": "…"},
  "units": {"native": 9, "baked": 0, "passthrough": 2, "cloned_passthrough": 0,
            "patched": 0, "rebuilt": 0, "manual_required": 1, "total": 12},   // SUM ASSERTED
  "package": {"zip_integrity": "passed", "slides": 12, "media_parts": 9},
  "checks": {
    "zip_integrity":        "passed",
    "unit_count":           "passed",
    "internal_relationships": "enforced-at-build",     // FIRST-CLASS value. Not omitted, not faked.
    "construct_closure":    "enforced-at-build",
    "quality_gate":         "passed",                  // the ten-value enum
    "asset_ledger":         "passed",
    "citation_embedding":   "passed",
    "text_capacity":        "skipped",
    "repro_double_compile": "not-run"                  // local; CI runs it
  },
  "resources": {                                        // PORTABILITY, not validity — a second axis
    "unresolved_tokens": [], "external_images": [],
    "fonts": {"stacks": ["Inter, sans-serif"], "generic_only_stacks": [], "unsafe_exported_faces": []}
  },
  "restrictions": {"bits": 0, "items": []},
  "licence_notices": [],                                // D3 -> D9's response envelope
  "report_sha256": "…"
}
```

Console, one line, full JSON on disk:

```
[OUT] pptx status=passed-with-warnings gate=passed units=12 (native 9 · passthrough 2 · manual 1)
      repro=bytes cites=41/41 assets=9 warn=3  ->  out/q3.pptx
```

### DDL — four tables, over D2's store, no second representation

```sql
CREATE TABLE artifact (
  artifact_id       INTEGER PRIMARY KEY,
  target            TEXT    NOT NULL,                 -- 'pptx'
  compile_driver    TEXT    NOT NULL,                 -- 'compile.pptx.native'
  media_type        TEXT    NOT NULL,
  path              TEXT    NOT NULL,
  sha256            BLOB    NOT NULL,
  byte_len          INTEGER NOT NULL,
  il_digest         BLOB    NOT NULL,
  constructs_digest BLOB    NOT NULL,
  ledger_digest     BLOB    NOT NULL,
  brief_digest      BLOB,
  card_sha256       BLOB    NOT NULL,
  toolchain_digest  BLOB,                             -- NULL for a pure-Python target
  repro             TEXT    NOT NULL CHECK (repro IN ('bytes','normalized','none')),
  repro_digest      BLOB,                             -- NULL iff repro='none'
  gate_status       TEXT    NOT NULL,
  delivery          TEXT    NOT NULL CHECK (delivery IN ('release','draft')),
  report_sha256     BLOB    NOT NULL,
  receipt_sha256    BLOB    NOT NULL,
  restriction_bits  INTEGER NOT NULL DEFAULT 0,
  producer_id       INTEGER NOT NULL REFERENCES producer(producer_id),
  decision_id       TEXT,                             -- D4's route_decision join
  built_at_ns       INTEGER NOT NULL,
  parsed_back_doc_ord INTEGER REFERENCES doc(doc_ord),-- set when parse_back has run. THE LOOP.
  CHECK ((repro = 'none') = (repro_digest IS NULL))
);
-- Identical inputs => identical artifact. A recompile is a lookup, not a build.
CREATE UNIQUE INDEX artifact_repro ON artifact(
  target, il_digest, constructs_digest, ledger_digest, card_sha256, IFNULL(toolchain_digest, x''));

CREATE TABLE artifact_unit (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit        TEXT    NOT NULL,
  ord         INTEGER NOT NULL,
  outcome     TEXT    NOT NULL CHECK (outcome IN
              ('native','baked','passthrough','cloned_passthrough','patched','rebuilt',
               'manual_required')),
  il_path     TEXT    NOT NULL,
  il_sha256   BLOB    NOT NULL,
  reason      TEXT,                                   -- REQUIRED for manual_required and baked
  CHECK (outcome NOT IN ('manual_required','baked') OR reason IS NOT NULL),
  PRIMARY KEY (artifact_id, unit)
) WITHOUT ROWID;

CREATE TABLE artifact_asset (                          -- the ledger JOIN. `asset` is D2's, unchanged.
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  asset_id    INTEGER NOT NULL REFERENCES asset(asset_id),
  slot        TEXT    NOT NULL,                        -- 'asset-slot:<sha256>' as it appears in the IL
  role        TEXT    NOT NULL,                        -- image|bake|font|audio|video|lut
  units       TEXT    NOT NULL,                        -- JSON array (ppt-master `occurrences[]`)
  PRIMARY KEY (artifact_id, asset_id, slot, role)
) WITHOUT ROWID;

CREATE TABLE artifact_cite (                           -- provenance across the round trip
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit        TEXT    NOT NULL,
  cite        TEXT    NOT NULL,                        -- 'd7#412' — D2's only prompt-safe id
  block_id    INTEGER REFERENCES block(block_id),      -- NULL => unresolved at build time
  quote_tier  INTEGER NOT NULL,                        -- D2 Quote as INTEGER
  verified    INTEGER NOT NULL,                        -- text matched the cited block under NFC
  PRIMARY KEY (artifact_id, unit, cite)
) WITHOUT ROWID;
-- "which generated decks quote page 14 of this contract?" — one index, one query:
CREATE INDEX artifact_cite_block ON artifact_cite(block_id);
```

`parse_back` adds nothing here: it writes an ordinary `doc` row through `DocSink`, sets
`artifact.parsed_back_doc_ord`, and emits `rel(derived_from, new_block, cited_block)` per D2's
closed relation set. **The loop is a foreign key.**

### CLI

```
ow out scaffold <name> --carrier xml|jsx|html    # a GREEN target in one command (see §11)
ow out targets                                   # installed · enabled · toolchain state · repro · fidelity
ow out explain <target>                          # D3's `drivers explain` shape, for targets
ow out constructs <target> [--format md|json]    # the agent-facing IL reference, GENERATED
ow out brief [--interactive]                     # writes spec_lock; the compile path opens it read-only
ow out lint  <target> <il-dir>                   # static rules only. No store, no assets. < 1 s.
ow out check <target> [--early] [--json]         # full: assets, cites, runtime rules -> report.json
ow out compile <target> -o <path> [--accept-manual] [--bake] [--repro-check]
ow out snapshot <target> [--bless]               # visual regression vs fixtures/out/expected/
ow out comments list|apply <il-dir>              # the feedback loop; apply is reverse-order, transactional
ow out back <artifact> [--into <store>]          # parse_back — resolves to the parse/1 driver
ow out assets add <file> --slot <name> [--spdx X --source-url U]
ow out verify <artifact>                         # recompute repro_digest; PASSED | DRIFTED
```

### Invariants and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| O1 | Every construct the compiler supports has a row; every row's `maps_to` resolves. | Two-way CI gate: `OW-T-001` / `OW-T-002`. Import the lowering module, diff its public symbol set against `constructs.toml`. |
| O2 | There is exactly one implementation of "what does this construct mean". | The rule pack receives `RuleCtx` and calls the lowering's own parsers; `CompileV1` has **no** `validate()`; a semgrep rule bans a second parser module under `rules/`. |
| O3 | A check that could not run is visible in the report. | `report.skipped_checks[]` is required non-null; `measure() -> None` writes a row; the conform kit removes `uharfbuzz` and asserts the row appears and the gate does **not** say `passed`. |
| O4 | The gate binds to bytes, not filenames. | `source_fingerprint` in the report; the target host recomputes it with an independent implementation before lowering; divergence is `STALE` / `OW-T-004`. |
| O5 | Exactly one gate status permits a release. | `gate_status()` returns a `GateStatus`; the compile path compares `is GateStatus.PASSED`; a test asserts all nine other values are refused with a distinct message and a fix command. |
| O6 | Every finding carries a provenance class and a non-empty `fix`. | `Finding.__post_init__` raises on empty `fix`; one function feeds both console and JSON so they cannot disagree. |
| O7 | A finding is folded, not repeated. | `FindingSet.add()` folds on `(code, rule, unit, canonical)`, increments `count`, keeps ≤3 `examples`; a test emits 200 occurrences and asserts one finding. |
| O8 | Every plan unit is classified into exactly one outcome and the sum is asserted. | `classify_and_assert()`; `OW-T-005` is fatal; `artifact_unit` PK plus the CHECK on `reason`. |
| O9 | No external URL, path, or byte blob appears in the IL. | Framework rule `OW-T-112`; `asset-slot:` is the only asset syntax; the conform kit greps the golden corpus. |
| O10 | Every asset is frozen, content-addressed and licence-bearing before compile. | `AssetLedger.freeze()` is the only writer; `asset.store_ref NOT NULL`; `OW-T-113` reads `restriction_bits`. |
| O11 | An artifact never contains a restricted item without policy. | D3-17: the compile host refuses, naming ids; gate status `RESTRICTED`; a synthetic restricted driver fixture asserts refusal survives parse → derive → compile. |
| O12 | Compilation is a pure function of five digests. | `artifact_repro` UNIQUE index; `--repro-check`; CI double-compile over the fixture corpus with different cwd and `TMPDIR`. |
| O13 | A `repro` claim is proved, not asserted. | Conform suite `repro` executes exactly the declared mode; `repro = "none"` forbids claiming law T2. |
| O14 | An unresolved feedback marker never reaches a release artifact. | Framework rule `OW-T-141`; `marker.assert_clean()` runs inside `compile`, after the gate, before lowering. |
| O15 | A feedback edit is transactional. | `CarrierDoc.splice()` sorts descending, applies, **reparses**, all-or-nothing; a fuzz test applies 10k random op batches and asserts the file is always parseable or unchanged. |
| O16 | An ambiguous edit address is refused, never guessed. | Two-factor resolution; multiple text candidates without `prevText` returns `OW-T-151`, and a test asserts refusal rather than a first-match write. |
| O17 | `parse_back` never invents provenance. | `Method.ROUNDTRIP` stamped by the reader; `Quote.RECONSTRUCTED` unless the text was read from the artifact; the D2 driver testkit's ~120 property tests run against it unchanged. |
| O18 | Round-trip loss is declared in both directions. | Conform suite `roundtrip`: T1 and T2 for every construct not in `loses`; `OW_ROUNDTRIP_LOST` asserted present for every construct in `loses`; over-declaration fails. |
| O19 | A target cannot skip its own gate. | The framework owns `ow out compile`; `lower()` receives an already-gated `Plan` and has no access to the report; the conform suite calls `lower()` with a failing report and asserts the host never reaches it. |
| O20 | Auto-fix does not exist. | No `--fix` flag; a semgrep rule bans a write to `il/` from anything under `rules/`. |
| O21 | The agent-facing IL doc is generated and budgeted. | `ow out constructs --format md --check` byte-diffs the committed render (D1's gate G6 shape); `agent_doc_tokens_max` is a CI assertion. |
| O22 | `omniweave_core.out` imports no third party and no carrier parser. | D1's gate G1 and G9 unchanged; a test asserts `omniweave_core.out` under `-X importtime` loads zero third-party modules. |

---

## 10. The first three targets

I ship **`pptx`, `deck`, `video`** — exactly D1's three target distributions, deliberately, because
between them they exercise every axis of the contract. A judge should read this table as the proof
that the abstraction constrains something.

| | **pptx** | **deck** | **video** |
|---|---|---|---|
| distribution | `omniweave-target-pptx` (60 MB) | `omniweave-target-deck` (1 MB + toolchain) | `omniweave-target-video` (1 MB + toolchain) |
| execution | **pure Python** — no Node | Toolchain, `omniweave-target/1` | Toolchain + external `ffmpeg` |
| carrier | canonical SVG subset (`xml/svg`) | canonical TSX subset (`jsx/tsx`) | HTML + closed `data-*` timing set (`html/hf`) |
| deps | python-pptx, XlsxWriter, skia-pathops, uharfbuzz, Pillow, defusedxml | node ≥20 | node ≥20, system ffmpeg (`ffmpeg = "system"`, never bundled) |
| constructs (v1) | ~140 rows | ~60 rows | ~45 rows |
| runtime rules | none | yes (`getBoundingClientRect` capacity) | yes (`pretext` off-canvas measurement, sampled times) |
| `repro` | **`bytes`** | **`bytes`** (static HTML/PDF output) | **`normalized`** |
| repro normalizer | — | — | `sha256(canonical([frame_sha256(t) for t in 0..dur step 1/repro_sample_hz], pcm_sha256, stream_layout))` |
| `citations` | `embedded` (`p:extLst`, our GUID) | `embedded` (`data-ow-cite`) | **`sidecar`** (`.owcite.jsonl` + WebVTT chapters) |
| `parse_back` | `parse.pptx.owpptx` | `parse.deck.owtsx` | `parse.video.owbrief` |
| `round_trip.fidelity` | **`passthrough`** | `structure` | `text` |
| laws proved | T1, T2, T3 | T1, T2, T3 | T1, T3 (T2 refused: `repro=normalized` + lossy encode) |
| bake | `unavailable` day one (see §4) | `available` (toolchain rasterizer) | `available` |
| codec policy | n/a | n/a | **VP9/WebM default; libx264 is an operator opt-in; refuse rather than substitute** |

**Why `pptx` first.** D1 already ruled it the flagship and the evidence agrees: it is the only
target in the collection with a working `parse_back` (`pptx_intake.py` + `ppt_to_md.py`), it is the
only one that reaches `passthrough` fidelity (ppt-master's four-tier classification with an asserted
sum), and it requires **zero Node**, which is what makes `pip install omniweave[pptx]` a 60 MB
one-liner. Its dependency set is verified from ppt-master's own `skills/ppt-master/requirements.txt`
(`python-pptx>=0.6.21`, `XlsxWriter>=3.0.0`, `skia-pathops>=0.9.2`, `uharfbuzz>=0.50.0`,
`Pillow>=9.0.0`) and matches D1's declared ceiling exactly. **Three files from ppt-master must never
be vendored**: `gemini_watermark_remover.py` (a provenance-marker stripper — the risk digest calls
its mere presence a fatal diligence fact), `curl_cffi` (TLS-fingerprint impersonation), and
`edge-tts`. And the PDF path via `PyMuPDF` (AGPL-3.0) is out; that is D1's `parse.pdf.pdfium`.

**Why `deck` second.** It is the cheapest proof that a Toolchain target is not second-class: the
same brief, the same plan, the same ledger, the same markers, the same report, the same gate, with
`lower()` on the other side of an NDJSON pipe. open-slide has **no semantic validator at all** —
only `tsc --noEmit` and biome, i.e. *is this valid TypeScript*, never *is this a valid slide* — and
nothing checks 1080 px fit, `notes`/page alignment, `var(--osd-X)` token declaration, or whether a
`<Step>` sits inside a `<Steps>`. Every one is mechanically checkable and becomes a construct row
plus a rule. `deck` is also where the bake rasterizer lives, so installing it upgrades `pptx`'s bake
tier from `unavailable` to `toolchain:deck` — a genuine, visible, one-command capability gain that
`ow out explain pptx` prints.

**Why `video` third.** It is the only target that forces the contract to admit what it cannot claim:
`repro = normalized` because a resolved ffmpeg differs, `citations = sidecar` because MP4 has
nowhere to put them, T2 refused because a lossy encode is not idempotent, and `ffmpeg = "system"`
because bundling `ffmpeg-static` puts a GPL-2.0-or-later `libx264` binary inside a deploy artefact
carrying no ffmpeg NOTICE. hyperframes' determinism contract is the reason it works at all, and it
is verified in-tree (`packages/parsers/src/compositionContract.ts:1-32`): source HTML is authored
with `data-start` + `data-duration` + `data-track-index`, `data-end` is compiler-derived,
`data-layer` is legacy input only, and the doctrine sentence is in the file header —
*"Readers accept legacy documents; writers always emit the canonical representation."* That is my
`normalize` disposition, in someone else's production code, with the canonical/derived/legacy split
already frozen into three exported arrays.

**`docx` is target four, not target three,** and it costs a twelfth distribution
(`omniweave-target-docx`, pure Python, carrier `html/flow`, `repro = bytes`, fidelity `patched`).
D1 enumerated eleven day-one distributions and separately promised *"PPTX and DOCX never require
Node"*; adding the twelfth is a release event under D1's `RELEASE` axis, not a contradiction, and I
price it at ~6 engineer-weeks. I decline to ship it in the first three because a flow-layout carrier
shares almost no rules with a canvas carrier, and proving the contract generalizes across
*execution models* (Python / Toolchain / Toolchain+binary) teaches more than proving it generalizes
across two Office formats.

---

## 11. The afternoon test

This is my prior's acceptance criterion, so it gets a concrete definition.

```
$ ow out scaffold slidev --carrier html
  wrote omniweave-target-slidev/
    pyproject.toml          2 entry points: omniweave.targets, omniweave.drivers
    driver.toml             compile.slidev.native · repro="none" · round_trip.fidelity="none"
    constructs.toml         3 rows (heading, paragraph, image) · schema v1
    carrier_html.py         CarrierDoc over html.parser                              48 lines
    rules/r_heading.py      1 rule + 1 test
    lower/__init__.py       lower() -> writes a .md file
    conftest.py             from omniweave_conform.target import *
$ cd omniweave-target-slidev && uv run pytest
  ==== 11 suites, 96 passed, 0 failed in 41s ====
```

**Green, honest and useless on minute one.** It supports three constructs, claims no
reproducibility, claims no round trip, and every one of those claims is *tested*. Then every row you
add to `constructs.toml` becomes a fixture the kit demands and a rule the kit runs; every capability
you raise on the card becomes an assertion in both directions. The kit tells you when you are done.
D3's bar applies verbatim — *"the honesty of the descriptor, not the excellence of the driver"* —
and the mandatory tier must run in under five minutes on a laptop, a CI timing assertion, because a
skipped gate is not a gate.

`omniweave-conform`'s twelfth suite, `target`, is eleven checks: `card`, `constructs` (two-way
closure), `carrier` (round-trips `source() → splice([]) → source()` byte-identically), `rules`
(every rule has a test and a `codes.toml` entry), `gate` (all ten statuses reachable and each has a
distinct message with a fix command), `ledger`, `marker`, `repro`, `roundtrip` (T1/T2/T3),
`portability` (the receipt's resources block), and `docs` (`--check` on the generated IL reference).

**Operability, priced:**

- `ow doctor` gains one section per enabled target: carrier, construct count, toolchain resolved
  path and digest, `repro` mode, bake availability, and for a missing toolchain the exact
  `omniweave targets install deck` line. D1 already rules that a missing toolchain **prunes the plan
  with a report**, never an `ImportError`.
- Every `OW-T-nnn` ends with the command that clears it and `ow explain OW-T-311` prints the long
  form. `codes.toml` is append-only under D1's gate G13.
- Upgrade path: `il_version` and `constructs_digest` are on the card and in the cache key, so a
  construct-table change invalidates compiles and nothing else. A `loses` row added between releases
  is a **minor** bump with a `degradations[]` entry naming the construct on the first affected
  compile; a row moving `normalize → forbidden` is a **major** bump because it breaks input that
  used to work. That rule goes in `CONTRIBUTING.md` and `ow out constructs --diff <tag>` computes
  the required bump mechanically.

---

## Rationale

The blueprint's `GeneratorTarget` has nine members and every one of them is a verb. Nine verbs is
not an interface, it is a job description, and if a third party has to implement nine verbs to add a
target, nobody adds a target. So the first thing I did was ask, member by member, *who should
actually own this?* — and the honest answer for six of the nine is **the framework**. `canonical()`
and `compatible()` are not functions, they are two columns of one table. `validate()` is a runner
the framework owns plus predicates the target owns. `assets()` is entirely framework: freezing,
content-addressing, licence facts and restriction codes are policy, and policy that varies per
target is policy nobody can audit. `feedback()` is entirely framework except one placement hook.
`manual_required` is not a member at all, it is a value in an enum. What is genuinely per-target is
four things: a table, some predicates, a lowering, and a reader.

That collapse is the whole proposal, and the evidence supports it from an unexpected direction. The
three repos converged on **seven** mechanisms, not one, and a design implementing fewer than seven
is behind the state of the art. But look at *which* seven: the closed surface, the trichotomy, the
tolerant-reader/canonical-writer rule, the blocking validator, the frozen brief, the
element-addressed feedback artifact, the asset ledger. **Six of the seven are format-independent.**
Only the first — what the closed surface actually contains — is about PPTX or MP4 at all. Three
teams independently built six identical mechanisms and one different one, which is precisely the
signature of an abstraction that wants to exist.

On the IL question specifically, I ruled against a schema on evidence rather than taste. The three
things a real construct table must express — a bake tier with a deterministic degradation, a
conditional prohibition, and a cross-element occurrence budget — are all verified in ppt-master's
source and none of them is a shape constraint. And I ruled against a bespoke grammar on adoption:
zero of three repos invented syntax, and the one thing that would make a third-party target
impossible is requiring its author to write a parser before writing a rule.

The single highest-leverage decision here is making `parse_back` an ordinary `parse/1` Driver. D3
already offered it (*"parse_back as a named parse/1 driver id on the card"*) and it would be easy to
treat that as bookkeeping. It is not. It means a generated deck enters the corpus through the same
router, the same cache, the same conformance kit, the same capability declaration, the same licence
gate and the same `restriction_bits` stamp as a scanned PDF — and that a generated artifact is
*retrievable* next quarter with no new code anywhere. The blueprint calls step 9 the least
implemented step in the collection. It is least implemented because everyone builds it as a special
edit mode. Built as a driver, it is the cheapest step, not the most expensive.

I also want to defend the two places where I made the contract *harsher* than the sources. First,
the two-way construct gate: ppt-master's checker imports the compiler's parsers, which prevents the
checker from being wrong, but nothing prevents the compiler from quietly supporting a construct the
contract never admitted — and a construct that works but is undeclared is exactly how a closed
authoring surface stops being closed. Second, two-directional round-trip declaration: without it,
`loses = ["*"]` is a green report, and a capability declaration that can be trivially satisfied by
pessimism is worth nothing. D3 already established the pattern for parse capabilities; I am applying
it to loss.

Finally, the operator numbers. `artifact_repro` as a unique index means a recompile of identical
inputs is a SQL lookup — the double-compile gate that proves reproducibility also *buys* caching,
for free, from the same property. `artifact_cite_block` means "which decks quote page 14 of this
contract" is one indexed query, which is the compliance question an enterprise actually asks and
which no repo in the collection can answer at all.

---

## Tradeoffs

- **The construct table is a real authoring burden.** ~140 rows for `pptx`, each with a code, a
  disposition, a fixture and a doc line. That is the cost of the contract being data. The
  alternative — the contract living in 9,368 lines of validator — is what the collection actually
  shipped, and it is unreadable, undocumentable and unforkable.
- **`repro = bytes` for PPTX makes python-pptx a frozen dependency.** Any upgrade that changes
  attribute ordering fails the double-compile gate and blocks the upgrade until someone re-blesses
  the fixtures. I would rather block an upgrade than lose reproducibility silently, but this will
  cost a day, repeatedly.
- **Bake is fail-closed on day one.** A construct with a known, deterministic degradation refuses
  instead of degrading, because both available Python rasterizers are LGPL-3.0. Users will hit this
  and it will read as the framework being precious about licences. It is, and D1's denylist is why.
- **Ten gate statuses is more surface than a boolean, and every one needs a message and a test.**
  Users will read `unverified` and `stale` as the same thing until they hit them. The payoff is that
  `not-provided` never gets debugged as `failed`.
- **No preview server at v1** costs the single best feedback UX in the collection (click an element,
  comment attaches to the AST node). The file-based marker path is strictly worse ergonomically and
  strictly safer, and it is the same protocol, so the server is additive later.
- **`video` cannot claim T2** and therefore cannot claim "editing a generated video is the same code
  path as creating one". That is honest and it is a smaller product than the blueprint implies.
- **Three carriers means three `CarrierDoc` implementations,** two of them in TypeScript. Two
  languages of carrier code is real maintenance, and D1's two-lockfile warning applies.
- **The `foreign/` fixture corpus is a standing obligation with a named owner.** Without it the
  round-trip laws test a closed loop against itself. Unstaffed, it rots and the laws become theatre.

---

## Failure modes

1. **The construct table is right and the lowering is wrong.** O1 proves a row maps to *a symbol*,
   not that the symbol is correct. A row claiming `native` whose lowering emits a subtly wrong
   DrawingML passes every gate. Only the golden corpus catches it, and only for constructs someone
   wrote a fixture for. **The input that breaks it:** a gradient with a stop at exactly 0.5 that
   lowers with the stops reversed — valid package, valid gate, wrong picture, forever.
2. **`repro = bytes` is a lie on a platform we did not test.** Dictionary ordering is stable in
   CPython but `zipfile`'s external attributes carry the umask on POSIX and not on Windows. The gate
   compiles twice on *one* machine; cross-platform byte identity is asserted only by the
   {ubuntu, macos, windows} test matrix, and the first artifact that differs between a developer's
   Mac and CI will be blamed on the target rather than on `zipfile`.
3. **The agent oscillates against the gate.** The IL is 95% right, three findings block, the agent
   re-authors and introduces two new ones. The early-gate method-sample classification bounds this
   in principle; in practice a 60-unit deck with a systematically wrong assumption burns the context
   window before the classification helps. Mitigation is the finding-folding budget and
   `--explain-findings`; there is no mechanical fix, and a hard call cap (`OW-T-006 GATE_OSCILLATION`
   after N cycles with no net finding reduction) is the honest stop.
4. **A 400-unit artifact makes the report unreadable.** Findings fold by `(code, rule, unit)`, so
   *unit* is in the key and 400 units with one systematic warning is 400 findings, not one. Folding
   across units would lose the address. There is no good answer; `--group-by rule` is a flag, and
   the JSON is machine-readable, which is the actual defence.
5. **`prevText` ambiguity on a template deck.** Fourteen slides all contain the string "Learn more".
   Location is stale after a re-author, content is ambiguous, so the edit is refused and the human
   is told to pick a different element. Correct, and infuriating.
6. **Citation laundering.** An agent writes `data-ow-cite="d7#412"` on text it composed. `OW-T-102`
   only checks the claim when the element also declares `quote="verbatim"`; a paraphrase carrying a
   cite passes. That is a genuine hole in the provenance story and no mechanical check closes it —
   the citation proves *where the agent said it looked*, never that the text follows.
7. **The `video` sidecar gets separated from the artifact.** A user mails `q3.webm` and loses every
   citation. `citations = "sidecar"` is machine-readable and D9 must surface it, but the loss is
   physical and unpreventable.
8. **Two targets fight over one artefact name.** A third party publishes `omniweave.targets pptx =
   …`. D3's `Registry.register` raises `DuplicateDriver` and `[drivers.resolve]` disambiguates, so
   the failure is loud — and one bad PyPI upload still bricks an install until the user uninstalls
   it. There is no namespace reservation for entry points.
9. **`parse_back` and `lower` are jointly wrong.** T2 passes because the reader inverts exactly the
   writer's mistake. The `foreign/` corpus is the only defence and it cannot exercise constructs
   foreign artifacts do not contain.
10. **The one input that breaks the whole design:** a 900-slide PPTX where every slide carries a
    `mix-blend-mode` overlay and an embedded OLE object. Bake is `unavailable` so every slide is
    `OW-T-311`; the OLE relationships mean every rebuilt page must refuse rather than drop
    (ppt-master's opaque-relationship rule, which I adopt); the gate is `failed` with 900 folded
    findings, and the correct behaviour — refuse, name the two exits — is indistinguishable from the
    framework being unable to do anything at all. The fix is `--bake` with the deck toolchain, and
    the error message must say so on the first line or the user leaves.

---

## Why I reject the alternatives

**A universal IL — one schema, one format, all targets.** ppt-master's own sentence is the refutation:
*"Compatible reads are a controlled migration boundary, not permission to widen the authoring
language."* An IL that expresses a 1920×1080 canvas, a flow-layout Word document and a timeline of
seekable animations expresses nothing, and its validator can only check well-formedness — which is
exactly open-slide's failure (`tsc --noEmit` answers *is this valid TypeScript*, never *is this a
valid slide*). The shared thing is the *pipeline*, not the language. Three repos proved that by
building three different languages and six identical mechanisms.

**JSON or a typed AST as the IL wire form.** Loses `git diff`, loses editor support, loses the
agent's fluency (an LLM writes SVG far better than it writes a tree of SVG-shaped objects), and adds
a serializer that must be kept equal to the carrier's own. Zero of three repos chose it. It also
breaks the feedback protocol: presence-is-state markers need a comment syntax, and JSON has none.

**JSON Schema as the construct contract.** Cannot express bake, cannot express the verified
conditional prohibition (`id=` only with `<style>`), cannot express the verified occurrence budget
("the third occurrence is an error"). A schema that must be supplemented by code for three of the
five dispositions is not the contract; the code is.

**A separate, independent validator implementation.** Produces the "checker passed, compiler failed"
bug class, which is the bug class the gate exists to prevent. ppt-master's answer — the checker
imports the compiler's parsers, and an unavailable import degrades to a *visible warning* — is right
and I strengthen it into a two-way gate rather than weakening it.

**A boolean gate.** `not-provided` and `failed` are different user errors with different fixes;
`stale` and `unverified` are different again; `restricted` is a legal refusal, not a validation
failure; `manual-required` needs a human, not a re-author. Collapsing six distinct remedies into
"validation failed" is how a gate becomes something people bypass.

**Byte comparison for round-trip change detection.** Verified insufficient: ppt-master needs six
normalizations before hashing (clone-local id prefixes stripped, asset refs rewritten to stable
tokens, asset edits folded in as an explicit marker, single-child group filters lowered,
attribute-free one-child `<g>` wrappers collapsed, the source-ref attribute ignored) — and the clause
everyone forgets, *a subtree referencing a changed `<defs>` entry is changed even though its own
bytes are identical*. Canonicalize, then hash, and track shared-definition dependencies.

**A feedback side table.** open-slide's presence-is-state marker cannot desync from the artifact
because there is no second place for the state to live; a side table can always disagree, and
"present after a claimed application" stops being a failure signal. The base64url payload is not
decoration: it keeps the marker grammar a fixed regular language no matter what the user typed.

**`parse_back` as a special edit mode.** It is the reason step 9 is the least-implemented step in the
collection. As a `parse/1` Driver it inherits discovery, the card, the probe, eleven conformance
suites, the licence gate, the restriction stamp, the cache and the router for free, and a generated
artifact becomes ordinary corpus.

**An asset ledger of its own (a `.media/manifest.jsonl` beside the store).** D2's `asset` table
already carries `sha256`, `store_ref`, `licence`, `licence_url`, `spdx`, `source_url` and
`retrieved_at_ns`; hyperframes' excellent ledger carries none of the licence fields and is
undeliverable for that reason. A second ledger is a sync layer, and D2 ruled on sync layers.

**Auto-fix.** ppt-master, verbatim: *"a mechanical patch can silently overwrite valid design intent
and ship a worse page."*

**A local preview/editor HTTP server at v1.** It needs open-slide's 76-line `request-guard.ts` as a
*minimum* on day one of its existence, and D1 bans loopback listeners in the pipeline outright. It is
additive later, over the same marker protocol, in its own distribution.

**Per-unit validation.** Explicitly rejected by ppt-master on economics — every checker call is a
context round-trip — and replaced by the two-gate cadence with a five-unit method sample and ≤6-unit
skip. I make its classification mechanical instead of prompted, which is the only part that was ever
a vibe.

**Shipping `docx` as target three.** It shares almost no rules with a canvas carrier and proves the
contract generalizes across two Office formats rather than across three execution models. `deck` and
`video` prove that a Toolchain target and a Toolchain-plus-external-binary target are first-class,
which is the property a third-party target author actually needs to believe.
