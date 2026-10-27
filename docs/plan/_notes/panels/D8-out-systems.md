# D8-out — The OUT compiler contract and closing the loop (systems prior)

## Headline

**The IL is not a file format and not a shared schema: it is a durable, content-addressed
node table in the `.owstore` (`il_node`), whose vocabulary is a per-target closed
`ConstructRegistry` with four tiers, and whose textual surface (canonical SVG / TSX / HTML)
is a byte-deterministic *projection* held to `parse_il(emit_il(nodes)) == nodes` in CI.**
Core owns the algebra — identity, canonical order, digests, the finding model, the gate,
the asset ledger, the feedback anchor, the receipt; each target owns exactly one closed
vocabulary and one compiler. `parse_back` is split in two, because the blueprint conflates
two obligations with different fidelity contracts: **`parse_back` (artifact → IL, enables
editing) and `ingest_back` (artifact → L2 blocks, enables corpus)**. Every escape hatch —
`bake`, `manual_required`, a missing `parse_back`, a weaker determinism class — is a
*declared* capability that the conformance kit checks in both directions and the receipt
records, which is what stops the generalization from collapsing into a set of hooks.

---

## 0. Position in the settled law, and three flagged conflicts

I write against D1, D2, D3, D4 as settled. Everything below uses their names verbatim:
`compile/1`, `DriverCard`/`driver.toml`, `DriverIO`, `DriverResult`, `resolve()`,
`restriction_bits`, `Service`, the job directory, `omniweave-target/1`, `.owstore`,
`block_id`/`addr`/`cite`, `content_digest`/`layout_digest`, `Quad` (1/1000 pt, topleft),
`DocSink`, `Diag`, `rebind`, `part`, `asset`, `producer`, `Degradation`, `OW-T-nnn`.

Three conflicts I must name rather than paper over, plus two upstream open questions I settle.

### C1 — `omniweave.targets` (D1) vs `compile/1` in `omniweave.drivers` (D3). D3 wins.

D1 fixes: *"ENTRY-POINT GROUPS … `omniweave.targets` `<artefact>` e.g. `pptx`, `docx`,
`deck`, `video`"* and *"Target := an OUT compiler addressed by artefact kind … registered in
the `omniweave.targets` entry-point group."* D3 fixes: *"There are five Ports at v1 —
`acquire`, `parse`, `derive`, `embed`, `compile`"*, one entry-point group
`omniweave.drivers`, ids matching
`^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$`, and consequence
*"D8 (OUT) gets `compile/1`, `capability.compile.*`."*

These cannot both hold. **Minimum amendment: strike the `omniweave.targets` row from D1's
ENTRY-POINT GROUPS block.** The argument is D1's own: a second discovery path means a second
card loader, a second licence gate, a second probe cache and a second `resolve()` — *"there
is one canonical-JSON digester, one place that opens SQLite, one subprocess seam"*. A target
is a Driver on the `compile/1` port; its DriverId is `compile.<artefact>.<impl>`
(`compile.pptx.drawingml`). D1's distribution names (`omniweave-target-pptx/-deck/-video`)
and its `[targets]` config table survive unchanged: **`[targets] enabled` is an artefact-kind
policy allowlist, `[drivers] enabled` names DriverIds.** They are different lists and both
are needed.

### C2 — a `compile` driver cannot invoke a Toolchain. Reconciled, not amended.

D1: *"`omniweave_core/toolchain.py` — THE ONLY module permitted to import `subprocess`
(Gate G8)."* D3: `DriverIO` has `blobs`, `tmpdir`, `deadline_ms`, `max_output_bytes`,
`service()`, `cancelled()`, `log()`, `progress()` and is *"Not extensible."* So
`compile.deck.openslide` has no way to run the deck Toolchain.

Both rulings' words already permit the fix: D3's **Service** is *"a host-managed shared
resource a Driver requests by name through `io.service(name)` — attach-or-spawn lifecycle,
no unit, no card, never routed."* I reserve the Service namespace **`toolchain:<name>`**.
`io.service("toolchain:deck") -> ToolchainHandle`, whose `.run(job_dir, timeout_s) ->
ToolchainResult` is `omniweave_core.toolchain.run` executed **in the host process**, not the
driver's. No new seam, no second subprocess site, G8 intact. Flagged so the charter records
the reservation.

### C3 — D2's `verbatim` rule makes every OOXML block unquotable. This is a defect.

D2 §5, verbatim: *"`verbatim` requires an `OriginBytes` span **and** a retained copy of that
part, since an offset without retained bytes is unverifiable."* And the DDL:
`-- INVARIANT: quote = 'verbatim' requires os_kind = 'bytes' AND part.store_ref IS NOT NULL.`

But D2's own §5 rules that the correct OOXML address is `nodepath`, *"ppt-master's verified
`SourceRefRecord.source_path`, which survives edits to other subtrees where a byte range into
`word/document.xml` does not"*. The consequence is that **no DOCX, PPTX or XLSX block can ever
be `quote='verbatim'`**, so serve can never claim byte-exactness for the formats
`pip install omniweave` reads by default — and, downstream of me, no citation from an office
document can ever be proved verbatim inside a generated deck.

The stated *reason* for the rule is verifiability, and `nodepath` + a retained part is exactly
as verifiable: resolve the child-index path in the retained part and compare. D2's own
`verify_quote` is defined as *"the stored span equals the current source slice"*, which the
resolve satisfies.

**Minimum amendment:** `quote='verbatim'` requires `os_kind ∈ {bytes, nodepath}` **and**
`part.store_ref IS NOT NULL`; for the `nodepath` case verification is
`normalize_k(resolve(part, os_path).text) == block.text`, and the driver testkit proves it the
same way it proves the `bytes` case. Nothing else in D2 changes. Without this amendment, my
invariant I10 (`CITE_VERBATIM_UNPROVEN`) can never be satisfied by an office source and the
product claim "this slide quotes the 10-K byte for byte" is unbuildable.

### S1 — settling D2's open question: OUT edits write a new `gen`.

D2 asks: *"Will an editing surface ever mutate a stored generation in place, resurrecting the
case for a gap-allocated order key? — settled by D9's ruling on whether `parse_back()` and
OUT-direction edits write a new `gen` … or patch the current one."*

**Ruling: every OUT-direction edit writes a new `gen`.** An `artifact_gen` row is *sealed*
once compiled (`sealed_at_ns NOT NULL`), and a sealed generation's `il_node` rows are
insert-only. Feedback application, `parse_back` recovery and rebase all produce gen N+1 with
`parent_gen = N` and a closed `origin` reason. `ord` rebalancing is therefore never a hot
path and `ord_path` stays rejected.

### S2 — settling D1's open question: no msgpack encoding of L2 is needed.

D1 asks: *"Is a `SCHEMA`-versioned msgpack encoding of L2 worth adding beside JSON? … Settled
by D8 naming a target that genuinely needs L2 in-process."*

**Ruling: no target needs the L2 block model in a non-Python process.** A Toolchain receives
IL text, an asset index and a *flattened citation sidecar* (`cites.json`, §6) carrying the
handful of L2 facts a renderer can use — cite token, quote text, page, quad. Nothing needs
`Block`, `Grid`, `Mark` or `SpanMap` across the boundary. Do not add msgpack.

---

## 1. What an IL is, exactly

Three layers, three owners. This is the answer to "a schema, a grammar, or a subset of an
existing format?" — all three, and they are owned by different parties so that the shared part
is small enough to be sound and the target-specific part is closed enough to constrain.

| Layer | Owner | Artifact | Enforced by |
|---|---|---|---|
| **Algebra** — node identity, containment, canonical order, digests, findings, gate, ledger, anchors, receipt | `omniweave_core.il` (stdlib only) | SQL DDL + ~1,400 LoC | types, SQL constraints, CI |
| **Vocabulary** — the closed construct set, four tiers, per-construct attribute schema, per-construct round-trip class, the mapping to a target primitive | the target | `ConstructRegistry`, materialized into `il_construct` at migration | FK from `il_node`; `omniweave-conform` |
| **Surface syntax** — canonical SVG / TSX / HTML | the target | `emit_il` / `parse_il` | `parse_il(emit_il(n)) == n` CI gate |

The **pivot is the node table, not the text.** The text is what an agent writes and what a
human diffs; the table is what the validator, the compiler, the feedback system and
`parse_back` operate on. This inverts ppt-master, where the checker and the exporter both
re-parse the same SVG text (and paper over the resulting drift with `try/except ImportError`
warnings in `svg_contracts.py`), and it removes the whole "checker passed, compiler failed"
class of bug by construction: there is exactly one parse.

**Why not one universal IL across targets.** hyperframes' timing attributes
(`data-start`/`data-duration`/`data-track-index`,
`packages/parsers/src/compositionContract.ts:9-32`) and DrawingML shape geometry have no
common supertype above "tree of nodes with attributes". A supertype at that altitude
constrains nothing — the exact failure mode the brief warns about. The *algebra* is shared;
the *vocabulary* is deliberately not.

**Why not the L2 block model as the IL.** D2's `block` carries `trust`, `quote`, `method`,
`producer_id`, `origin_operator` — four extraction axes that are category errors on authored
content — and its `kind` is a 34-member *document-semantics* vocabulary with no room for a
connector, a shadow, a track index or an animation trigger. Forcing those into `payload`
recreates D2's own named risk (*"`x` becomes a shadow schema … something load-bearing will
live in `x.acme.something` with no validator behind it"*) at ten times the volume.

**Why not IL-as-files-only (the ppt-master shape).** Feedback anchors go stale on every edit —
open-slide had to invent `prevText` precisely because `data-slide-loc` line:col does — and
ppt-master's `source_path: tuple[int,...]` child-index path is invalidated by any sibling
insertion. Citations become comments, `restriction_bits` enforcement becomes a text grep, and
cross-generation diffing means keeping N trees on disk. One integer column buys all of it back.

### The four tiers

Verbatim from ppt-master `docs/technical-design.md:17-25` plus the bake tier from
`svg_quality/svg_contracts.py:180-188`:

- **canonical** — the one recommended spelling. Compiles with no diagnostic.
- **compatible** — a documented alias with **one** safe deterministic normalization. Warning,
  never error, and *never generated*. `canonical_of` names the target construct.
- **bake** — the target cannot express it, but a deterministic degradation exists
  (rasterize the subtree). Opt-in per node, recorded, counted in the receipt.
- **invalid** — no mapping, ambiguous, or produces a broken package. Error, blocks.

The severity doctrine is carried verbatim and is a review rule on every registry PR:
*"Severity is determined by whether the input maps deterministically and legally, not merely
by whether it uses the recommended spelling."* With the promotion/demotion protocol:
**warning volume is a prompt bug; warning danger is a contract bug.**

The bake tier is the piece most designs miss and it is the one that needs a safety rule I add:
**a bake whose subtree contains a `verbatim` citation refuses** (`OW-T-215`), because
rasterizing destroys the text the citation claims to quote.

---

## 2. Concrete shape

### 2.1 DDL — additions to the `.owstore` (D2's file, D2's pragmas)

```sql
-- ═══════════ OUT. Same .owstore as D2. No second store, no sidecar SSOT. ═══════════
-- Generated from each target's Python ConstructRegistry at migration time, exactly as
-- D2 generates `enum_val`; CI asserts parity in both directions.
CREATE TABLE target_reg (
  target           TEXT    NOT NULL,      -- 'pptx' | 'deck' | 'video'
  registry_version INTEGER NOT NULL,      -- bumped when the construct set changes
  driver_id        TEXT    NOT NULL,      -- 'compile.pptx.drawingml'
  il_syntax        TEXT    NOT NULL,      -- 'svg/1' | 'tsx/1' | 'html/1'
  determinism      TEXT    NOT NULL,      -- JSON set: ["part","byte"] | ["frame"] | ["render","part"]
  feedback         TEXT    NOT NULL CHECK(feedback IN ('in_artifact','sidecar','none')),
  parse_back       INTEGER NOT NULL,      -- artifact -> IL
  ingest_driver    TEXT,                  -- artifact -> L2 blocks; a parse/1 DriverId. NOT NULL
                                          -- unless parse_back = 1 and the same reader serves both.
  registry_digest  BLOB    NOT NULL,      -- sha256 over the canonical registry; enters cache keys
  PRIMARY KEY (target, registry_version)
) WITHOUT ROWID;

CREATE TABLE il_construct (
  target           TEXT NOT NULL, registry_version INTEGER NOT NULL,
  construct        TEXT NOT NULL,         -- 'rect' | 'text' | 'Page' | 'clip' | 'cite'
  tier             INTEGER NOT NULL,      -- 0 canonical · 1 compatible · 2 bake · 3 invalid
  canonical_of     TEXT,                  -- REQUIRED iff tier = 1
  round_trip       INTEGER NOT NULL,      -- 0 exact · 1 normalized · 2 lossy · 3 dropped
  attr_schema      TEXT NOT NULL,         -- JSON Schema 2020-12 over payload
  defaults         TEXT NOT NULL DEFAULT '{}',
  maps_to          TEXT NOT NULL,         -- 'a:sp/a:prstGeom' | '<Page>' | 'div.clip'
  since_version    INTEGER NOT NULL,
  PRIMARY KEY (target, registry_version, construct),
  FOREIGN KEY (target, registry_version) REFERENCES target_reg(target, registry_version),
  CHECK ((tier = 1) = (canonical_of IS NOT NULL)),
  CHECK (NOT (tier = 3 AND round_trip <> 3))
) WITHOUT ROWID;

CREATE TABLE artifact (
  artifact_id INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,       -- 'q3-review'; the CLI handle
  target      TEXT NOT NULL, registry_version INTEGER NOT NULL,
  head_gen    INTEGER NOT NULL DEFAULT 1,
  brief_sha256 BLOB,                      -- the frozen brief; NULL only before `ow author`
  status      TEXT NOT NULL CHECK(status IN
                ('draft','validated','manual_required','compiled','failed')),
  FOREIGN KEY (target, registry_version) REFERENCES target_reg(target, registry_version)
);

CREATE TABLE artifact_gen (
  artifact_id    INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  gen            INTEGER NOT NULL,
  parent_gen     INTEGER,
  origin         TEXT NOT NULL CHECK(origin IN
                   ('authored','feedback','parse_back','rebase','bake')),
  il_fingerprint BLOB,                    -- see §3.3. NULL until the gen is complete.
  node_count     INTEGER, unit_count INTEGER,
  sealed_at_ns   INTEGER,                 -- NOT NULL => il_node for this gen is INSERT-ONLY
  PRIMARY KEY (artifact_id, gen)
) WITHOUT ROWID;

CREATE TABLE il_node (
  node_id     INTEGER PRIMARY KEY,        -- DURABLE surrogate. The only FK target. Never shipped.
  artifact_id INTEGER NOT NULL,
  gen         INTEGER NOT NULL,
  unit        INTEGER NOT NULL,           -- slide | page | track-time-window. D2's `page` analogue.
  addr        TEXT    NOT NULL,           -- 'u3/7' | 'u3/7/2'  — TYPE-FREE, like D2's addr
  parent_id   INTEGER REFERENCES il_node(node_id) ON DELETE CASCADE,
  ord         INTEGER NOT NULL,           -- position among siblings IS the paint/reading order
  construct   TEXT    NOT NULL,
  tier        INTEGER NOT NULL,           -- denormalized from il_construct; index-friendly
  payload     TEXT    NOT NULL DEFAULT '{}',   -- canonical JSON, validated against attr_schema
  text        TEXT,                       -- plain text of a text construct; NULL otherwise
  quad        BLOB,                       -- D2's Quad: 8 x i32 LE, 1/1000 pt, topleft. Or NULL.
  content_digest BLOB NOT NULL,           -- D2's recipe shape, IL variant (§3.2)
  layout_digest  BLOB,                    -- NULL when quad IS NULL
  nsig        TEXT    NOT NULL,           -- content_digest[:4] hex — the STAMPED content anchor
  origin_ref  INTEGER REFERENCES il_node(node_id),  -- the gen N-1 node this carries from
  recovery    INTEGER,                    -- NULL on authored; §5's Recovery on parse_back
  bake        INTEGER NOT NULL DEFAULT 0, -- 1 => this subtree is rasterized at compile
  manual      TEXT,                       -- a ManualRequired reason_class, or NULL
  state       INTEGER NOT NULL DEFAULT 0, -- 0 live · 1 tombstone.  There is no DELETE.
  x           TEXT NOT NULL DEFAULT '{}', -- keys MUST be 'x.<vendor>.<key>'
  FOREIGN KEY (artifact_id, gen) REFERENCES artifact_gen(artifact_id, gen) ON DELETE CASCADE,
  CHECK (parent_id IS NULL OR parent_id <> node_id),
  CHECK (tier <> 3)                       -- an INVALID construct is never storable. I2.
);
CREATE UNIQUE INDEX il_node_addr ON il_node(artifact_id, gen, addr);
CREATE UNIQUE INDEX il_node_sib  ON il_node(artifact_id, gen, IFNULL(parent_id,-1), ord);
CREATE INDEX il_node_paint  ON il_node(artifact_id, gen, unit, ord) WHERE state = 0;
CREATE INDEX il_node_nsig   ON il_node(artifact_id, gen, nsig);      -- the content anchor lookup
CREATE INDEX il_node_carry  ON il_node(origin_ref);
CREATE INDEX il_node_manual ON il_node(artifact_id, gen) WHERE manual IS NOT NULL;

-- Citations: the ONLY channel by which a store fact reaches an artifact.
CREATE TABLE il_cite (
  node_id   INTEGER NOT NULL REFERENCES il_node(node_id) ON DELETE CASCADE,
  block_id  INTEGER NOT NULL REFERENCES block(block_id),   -- D2's durable surrogate
  cite      TEXT    NOT NULL,             -- D2's 'd7#412', as written by the agent
  doc_gen   INTEGER NOT NULL,             -- the source doc generation this resolved against
  kind      TEXT    NOT NULL CHECK(kind IN ('quote','paraphrase','derived','data')),
  span_a    INTEGER, span_b INTEGER,      -- D2's TextSpan inside block.text; NULL = whole block
  verbatim  INTEGER NOT NULL DEFAULT 0,   -- proved by I10, never claimed by the author
  PRIMARY KEY (node_id, block_id, IFNULL(span_a,-1)),
  CHECK ((span_a IS NULL) = (span_b IS NULL))
) WITHOUT ROWID;
CREATE INDEX il_cite_block ON il_cite(block_id);   -- "which decks cite this paragraph?"

-- The asset ledger is D2's `asset` table plus ONE join. There is no manifest.jsonl,
-- because a sidecar SSOT can disagree with the store and hyperframes' does not carry
-- licence facts at all (`skills/media-use/scripts/lib/manifest.mjs` has only
-- `provenance.prompt`).
CREATE TABLE artifact_asset (
  artifact_id INTEGER NOT NULL, gen INTEGER NOT NULL,
  node_id     INTEGER NOT NULL REFERENCES il_node(node_id) ON DELETE CASCADE,
  asset_id    INTEGER NOT NULL REFERENCES asset(asset_id),
  role        TEXT NOT NULL,              -- image|video|audio|font|lut|baked|thumbnail
  fit         TEXT NOT NULL DEFAULT 'contain',
  PRIMARY KEY (node_id, asset_id, role)
) WITHOUT ROWID;

-- Findings. Closed code registry, append-only, CI-diffed (D1 codes.toml, OW-T-nnn).
CREATE TABLE il_finding (
  finding_id INTEGER PRIMARY KEY,
  artifact_id INTEGER NOT NULL, gen INTEGER NOT NULL, stage TEXT NOT NULL, -- 'early'|'final'
  code       TEXT NOT NULL,
  severity   TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
  provenance TEXT NOT NULL CHECK(provenance IN
                ('blocking','introduced','inherited','source_import')),
  node_id    INTEGER, addr TEXT, construct TEXT,
  message    TEXT NOT NULL,
  fix        TEXT NOT NULL,               -- the exact command that clears it. NEVER empty.
  canonical  TEXT,                        -- the replacement text, on a compatible-tier finding
  occurrences INTEGER NOT NULL DEFAULT 1, -- COUNT, not one row per element
  examples   TEXT NOT NULL DEFAULT '[]'   -- at most 3 addrs (ppt-master `remember_example`)
);
CREATE INDEX il_finding_gate ON il_finding(artifact_id, gen, stage, provenance);

-- Observation, kept strictly apart from decision (ppt-master reconstruction_inventory.json).
CREATE TABLE il_evidence (
  artifact_id INTEGER NOT NULL, gen INTEGER NOT NULL, unit INTEGER NOT NULL,
  region_id   TEXT NOT NULL, quad BLOB, family TEXT, observed_text TEXT,
  confidence  REAL, sufficiency TEXT, occlusion TEXT, resolved INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (artifact_id, gen, unit, region_id)
) WITHOUT ROWID;   -- NO layer choices, NO prompts, NO output filenames, NO IL bindings.

-- Element-addressed feedback. Two-factor anchor; the ARTIFACT is authoritative for state
-- when the target's feedback channel is `in_artifact`.
CREATE TABLE feedback (
  ann_id      TEXT PRIMARY KEY,           -- 'fb_' || base32(random)  — appears in the artifact
  artifact_id INTEGER NOT NULL, opened_gen INTEGER NOT NULL,
  addr        TEXT NOT NULL,              -- positional anchor
  nsig        TEXT NOT NULL,              -- content anchor
  quote       TEXT,                       -- third factor for text nodes; open-slide's prevText
  body        TEXT NOT NULL, author TEXT NOT NULL, created_ns INTEGER NOT NULL,
  state       TEXT NOT NULL CHECK(state IN ('pending','applied','skipped','stale')),
  applied_gen INTEGER, skip_reason TEXT
);

CREATE TABLE compile_run (
  run_id      TEXT PRIMARY KEY,
  artifact_id INTEGER NOT NULL, gen INTEGER NOT NULL,
  driver_id   TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  gate_status TEXT NOT NULL,              -- the nine-value enum
  out_sha256  BLOB, out_bytes INTEGER, part_digest BLOB,   -- D-PART digest (§4)
  receipt     TEXT NOT NULL,              -- canonical JSON; schema/receipt-v1.json
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  degradations TEXT NOT NULL DEFAULT '[]',-- D4's channel, verbatim
  decided_at_ns INTEGER NOT NULL
);
```

### 2.2 The port — `omniweave.ports.compile_v1` (D3 owns the file; D8 owns its contents)

```python
# omniweave/ports/compile_v1.py — pure typing, ~40 KB dist. A target imports THIS, never core.
class Tier(IntEnum):      CANONICAL=0; COMPATIBLE=1; BAKE=2; INVALID=3
class RoundTrip(IntEnum): EXACT=0; NORMALIZED=1; LOSSY=2; DROPPED=3
class Recovery(IntEnum):  EXACT=0; NORMALIZED=1; RECONSTRUCTED=2; DROPPED=3; FOREIGN=4
class Determinism(StrEnum): PART="part"; BYTE="byte"; FRAME="frame"; RENDER="render"

@dataclass(frozen=True, slots=True)
class Construct:
    name: str
    tier: Tier
    round_trip: RoundTrip
    attr_schema: Mapping[str, Any]        # JSON Schema 2020-12
    defaults: Mapping[str, Scalar] = MappingProxyType({})
    canonical_of: str | None = None       # REQUIRED iff tier is COMPATIBLE
    maps_to: str = ""                     # the target primitive. Non-empty unless tier=INVALID.
    normalize: str | None = None          # name of a registered pure normalizer, tier=COMPATIBLE
    # There is no `check` callable here. A construct is DATA. Rules are separate, below.

@dataclass(frozen=True, slots=True)
class ConstructRegistry:
    target: str; version: int; il_syntax: str
    constructs: Mapping[str, Construct]
    mandatory: ClassVar[frozenset[str]] = frozenset({"root", "unit", "cite"})
    # `cite` is MANDATORY IN EVERY REGISTRY. A target that cannot express a citation
    # cannot be a target. This is the single hardest constraint in the contract.
    def digest(self) -> bytes: ...        # sha256_canonical; enters every cache key

@dataclass(frozen=True, slots=True)
class Finding:
    code: str; severity: Literal["error","warning","info"]
    provenance: Literal["blocking","introduced","inherited","source_import"]
    message: str; fix: str                # `fix` is REQUIRED and is a runnable command
    addr: str | None = None; construct: str | None = None
    canonical: str | None = None          # the replacement text on a compatible finding
    occurrences: int = 1
    examples: tuple[str, ...] = ()        # <= 3. Asserted by the Finding constructor.

class Rule(Protocol):
    CODE: ClassVar[str]                   # one code per rule; one rule per module; one test
    NEEDS: ClassVar[frozenset[str]]       # {'parsed','assets_frozen','measured','cited'}
    AFTER: ClassVar[frozenset[str]] = frozenset()
    SCOPE: ClassVar[Literal["node","unit","artifact"]]
    def check(self, subject: Any, ctx: "CheckCtx") -> Iterable[Finding]: ...   # PURE

class TextMeasure(Protocol):
    def measure(self, runs: Sequence["Run"], box: "Box") -> "Overflow": ...
    # The estimator the CHECKER uses is the estimator the COMPILER uses. One implementation.
    # (ppt-master's text_measure.py shares its estimator with the checker; open-slide has the
    #  model redo the arithmetic by hand per page with no verification.)

class CompileV1(Protocol):
    PORT: ClassVar[str] = "compile/1"
    @classmethod
    def probe(cls, env: "ProbeEnv") -> "ProbeVerdict": ...
    def __init__(self, **config: Scalar) -> None: ...   # STATIC CONFIG ONLY. Loads nothing.
    def registry(self) -> ConstructRegistry: ...        # PURE. No I/O, no clock.
    def rules(self) -> tuple[Rule, ...]: ...            # beyond the registry-derived checks
    def measure(self) -> TextMeasure | None: ...
    def emit_il(self, nodes: "NodeStream", out: Path) -> None: ...   # byte-deterministic
    def parse_il(self, src: Path, sink: "ILSink") -> None: ...       # text -> nodes
    def compile(self, plan: "CompilePlan", io: DriverIO) -> DriverResult: ...
    def parse_back(self, art: "ArtifactRef", sink: "ILSink",
                   io: DriverIO) -> "RecoveryReport": ...            # optional; card declares
```

### 2.3 The card block (`driver.toml`, `[capability.compile]`)

```toml
[driver]
id = "compile.pptx.drawingml" ; port = "compile/1" ; version = "0.1.0"
schema_version = 1 ; granularity = "document" ; deterministic = true

[capability]
formats  = ["pptx"]            # for compile/1, `formats` is the ARTEFACT KIND produced
consumes = ["il_tree","asset"] ; produces = ["artifact","receipt"]

[capability.compile]
artefact          = "pptx"
il_syntax         = "svg/1"                 # svg/1 | tsx/1 | html/1
registry_version  = 3
registry_digest   = "sha256:5c1a…"          # must equal registry().digest(); kit-checked
determinism       = ["part", "byte"]        # a SET, compared with ⊇ (D3's `math` precedent)
parse_back        = true
ingest_driver     = "parse.pptx.ooxml"      # the parse/1 DriverId for corpus ingest
feedback          = "in_artifact"
citation_channels = ["visible", "embedded", "ledger"]
bake              = true
fidelity_tiers    = ["passthrough","cloned_passthrough","patched","rebuilt"]
max_units         = 2000
max_nodes         = 2_000_000
external          = []                      # video: ["ffmpeg"]
```

Every one of these is asserted **in both directions** by the `omniweave-conform` suites in
§7 — `parse_back = false` is honest, not exempt: it forces `ingest_driver` to be non-null and
the kit checks that the named driver exists and passes `parse/1` conformance.

### 2.4 The job directory (D1's envelope; D8 owns the contents)

```
<cache_root>/jobs/<run_id>/<artifact_slug>@<gen>/
├── job.json            schema/job-v1.json
├── brief.md            the frozen brief, verbatim
├── il/                 the CANONICAL TEXT PROJECTION. Byte-deterministic. `il/u000.svg` …
├── cites.json          the flattened citation sidecar
├── assets/
│   ├── index.json      the ledger projection: licence, spdx, restriction_bits, attribution
│   └── cas/ab/cd/<sha256>.png
├── validation/final.json
└── out/                artifact + receipt.json + (parse_back) il/ + recovery.json
```

```jsonc
// job.json
{"schema":"omniweave.compile-job/1",
 "artifact":{"slug":"q3-review","target":"pptx","registry_version":3,"gen":4},
 "il":{"path":"il/","syntax":"svg/1","fingerprint":"sha256:9c2f…","units":40,"nodes":16233},
 "assets":{"index":"assets/index.json"},"cites":"cites.json","brief":"brief.md",
 "gate":{"status":"passed","report":"validation/final.json","introduced_warnings":3},
 "policy":{"restriction_bits_allowed":0,"visible_citations":true,"embed_provenance":true,
           "bake":["u07/3"]},
 "determinism":{"seed":0,"clock_ns":0,"tz":"UTC","source_date_epoch":0,"class":"part"},
 "limits":{"wall_ms":600000,"rss_bytes":4294967296,"out_bytes":2147483648,
           "max_nodes":2000000,"max_units":2000},
 "out":"out/"}
```

```jsonc
// cites.json — how a store fact reaches a renderer with NO store access
[{"node":"u3/7","cite":"d7#412","doc_gen":2,"kind":"quote","verbatim":true,
  "text":"Revenue grew 14% year over year.",
  "source":{"uri":"file:///corpus/fy24-10k.pdf","page":13,
            "quad":[102000,318000,470000,318000,470000,335000,102000,335000]}}]
```

```jsonc
// assets/index.json — a PROJECTION of D2's `asset` rows. The store is authoritative.
[{"id":"a7","sha256":"3f9c…","media_type":"image/png","w":1600,"h":900,
  "file":"assets/cas/3f/9c/3f9c….png","spdx":"CC-BY-4.0",
  "licence_url":"https://…","source_url":"https://…","retrieved_at_ns":1756700000000000000,
  "attribution":"Photo by A. Author","restriction_bits":256,
  "producer":"gen.image.sdxl@a1b2c3"}]
```

### 2.5 Protocol frames (D1's `omniweave-target/1`, extended by exactly one frame)

```jsonc
{"t":"ready","target":"deck","version":"0.1.0","proto":"omniweave-target/1",
 "capabilities":{"parse_back":true,"assets":true},
 "registry_digest":"sha256:5c1a…",                 // ADDED: the toolchain proves it agrees
 "external":[{"name":"node","version":"22.11.0"}]}
{"t":"validate","id":1,"il":"il/"}
{"t":"result","id":1,"status":"blocked","findings":[
  {"code":"OW-T-311","severity":"error","provenance":"introduced","at":"u07/3",
   "msg":"mix-blend-mode requires bake","fix":"omniweave compile q3-review --bake u07/3"}]}
{"t":"compile","id":2,"il":"il/","out":"out/deck.zip"}
{"t":"parse_back","id":3,"artifact":"in/deck.zip","out":"out/il/"}   // ADDED
{"t":"result","id":3,"status":"ok","receipt":"out/recovery.json"}
```

`registry_digest` on the `ready` frame is the one thing I add to D1's handshake, and it exists
because a pnpm bump that changes the toolchain's construct set with no Python-side signal is
the failure D1's own risk list names.

---

## 3. Validation: framework infrastructure, target rules

### 3.1 What core supplies

1. **Registry-derived checks, free for every target.** For each node core checks: construct
   exists at the artifact's `registry_version`; tier ≠ invalid; payload validates against
   `attr_schema`; every compatible-tier value normalizes deterministically (and the
   normalization is applied and recorded); every declared default is not explicitly restated.
   Looking at ppt-master's ordered check sequence (`svg_quality/checker.py:1253-1400`), items
   **2, 2a–2i** — forbidden elements, the 29-property inline-style closure, geometry/stroke,
   line-presentation, image fit/crop, path and point-list grammar, transform grammar, opacity,
   the authoring-property surface, filters, gradients — are *all* of this shape. They are a
   vocabulary and an attribute grammar, and a target that writes them as data gets them
   enforced without writing a checker.
2. **The rule scheduler.** Rules declare `NEEDS` and `AFTER`; core topologically sorts, runs
   phase 0 (well-formedness / registry) first and **short-circuits** on failure — ppt-master's
   check-0 rule, *"malformed SVG fails before DrawingML compatibility matters"* — then runs the
   remaining rules. **One rule per module, signature `(subject, ctx) -> Iterable[Finding]`,
   one test per rule.** This is the explicit rejection of ppt-master's 9,368-line checker
   class, which its own do-not-copy list names.
3. **Diagnostic economy.** `Finding.occurrences` + ≤3 `examples`, enforced in the constructor.
   A unit with 200 lowercase hex colours yields one finding (`remember_example`).
4. **Provenance classes** — `blocking | introduced | inherited | source_import`
   (`checker.py:9192-9230`). Inherited findings are routed out of the warning channel
   entirely. Without this, a template carrying 40 pre-existing warnings makes every generated
   deck look broken and the team stops reading the report.
5. **A degraded check is visible, never silent.** If a rule's `NEEDS` cannot be satisfied
   (no font file, no measurement engine, no headless browser) the rule emits
   `Finding(severity="info", code="OW-T-190", message="check skipped: …")` and the gate status
   becomes `unverified`, never `passed`. ppt-master's `try/except ImportError` → warning
   pattern, promoted to a gate consequence.
6. **The two-gate cadence.** Early gate over the first 5 units as a *method sample*; artifacts
   of ≤6 units skip it; **zero validator invocations between the early and final gate**.
   Per-stage report filenames are distinct (`validation/early.json` vs `validation/final.json`)
   so a diagnostic run can never produce the file the release gate reads.

### 3.2 The IL digest recipe (`il_digest_recipe = 1`)

```
canonical(x) = JSON, sorted keys, no NaN/Inf, geometry as i32 only, three distinct
               encodings for absent / null / "".

content_digest = sha256_128(canonical([
    construct,
    nfc(text) or None,
    canonical(payload minus every key equal to the construct's declared default),
    [child.content_digest for child in children in `ord` order],   # merkle
]))
layout_digest  = sha256_128(canonical([content_digest, unit, quad quantised to WHOLE POINTS]))
nsig           = hex(content_digest)[:8]

NOT digest inputs: node_id, addr, ord, origin_ref, recovery, bake, manual, state, x.
DEFAULTS ARE ELIDED. This is load-bearing: it makes "restating a default" and "omitting it"
the same node, which is what makes loss category (1) in §5 testable.
```

`content_digest` is D2's recipe shape with a different tuple; the hash primitive is whatever
`omniweave_core.identity` uses. (D1 says sha256, D2 says blake3-128; that conflict is not
mine and D8 is indifferent as long as there is exactly one implementation.)

### 3.3 The fingerprint and the nine-value gate

```
il_fingerprint = sha256( for each node in ORDER BY addr :  addr ‖ 0x00 ‖ hex(content_digest) ‖ 0x0A )
```
Framing and sort discipline copied from ppt-master `checker.py:9335-9368` (`name\0sha\n`,
sorted by basename, an unreadable member contributes the literal `unreadable` rather than
dropping out). A node whose payload failed to canonicalize contributes the literal
`uncanonical` **and** an error finding, so it can never become invisible to the comparison.

```
GateStatus = not-provided | unreadable | unsupported-schema | non-final
           | unverified   | stale      | failed             | manual-required | passed
ReportStatus = passed | passed-with-warnings | manual-required | failed
```

Nine values, one of which lets a compile proceed. `not-provided` ≠ `failed` because "you never
ran the gate" and "you ran it and it found errors" are different user errors with different
fix commands, and **every non-`passed` status prints the exact command that clears it**.
I add one value to ppt-master's set: **`manual-required`**, distinct from `failed`, because
"your IL is wrong, fix it" and "a human must decide something the system refuses to invent"
have different owners and different commands.

**On the two-implementation question.** ppt-master computes the fingerprint twice —
`checker.py:_quality_source_fingerprint` and the exporter's independent
`cli.py:1223-1240 _svg_source_fingerprint` — and a divergence surfaces as `stale`. D1 forbids
second implementations. Both are right about different risks: ppt-master's second
implementation guards *staleness* (files changed between check and compile), not
implementation drift. In omniweave staleness is prevented structurally — the IL is store rows
and a sealed `gen` is insert-only — so **the in-process path recomputes with the same
function and no second implementation exists.** For a Toolchain the IL genuinely leaves the
store as text, so the toolchain recomputes the fingerprint over `il/` bytes; that is a second
implementation *because it is a second language*, it is specified in
`schema/il-fingerprint-v1.md`, and CI runs a cross-language parity fixture. This is exactly
the class D1 already accepts: *"plain `sha256` over bytes, on which every language already
agrees."*

---

## 4. Determinism, stated as four classes and a set of CI gates

This is where a lot of OUT designs wave. The evidence is concrete, so the spec is too.

**ppt-master's PPTX writer is not reproducible, and the mechanism is checkable.**
`svg_to_pptx/pptx_package/builder.py:8145-8149`:

```python
with zipfile.ZipFile(temp_output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for file_path in extract_dir.rglob('*'):
        if file_path.is_file():
            zf.write(file_path, file_path.relative_to(extract_dir))
```

Two independent nondeterminism sources: `rglob` yields **filesystem order**, and
`ZipFile.write` → `ZipInfo.from_file`, verified in CPython 3.11.9, does
`mtime = time.localtime(st.st_mtime); date_time = mtime[0:6]`. Separately,
`ZipFile.writestr(str_name, data)` constructs `ZipInfo(filename, date_time=time.localtime(time.time())[:6])`
— **local time**, so the same build in two timezones produces different bytes. And
`ZipInfo(filename)` alone defaults to `(1980,1,1,0,0,0)`, which is the deterministic
constructor. All three verified by `inspect.getsource` against the interpreter.

### The four classes

| Class | Property | Scope of the promise | Mandatory for |
|---|---|---|---|
| **D-PART** | the member name set and each member's **payload bytes** are identical | any environment satisfying the pinned major dep versions | `pptx`, `docx`, `deck` (source tree) |
| **D-BYTE** | the container bytes are identical too | one pinned `(python, zlib, compresslevel, dep-set)` | asserted in CI, **recorded in the receipt, never promised to a user** |
| **D-FRAME** | 12 deterministically sampled decoded frames + the full PCM stream are identical | one pinned `(ffmpeg, codec, threads)` | `video` |
| **D-RENDER** | the sampled DOM paint tree and measured layout are identical at sampled times | one pinned toolchain digest | `deck` |

Splitting D-PART from D-BYTE is the correction most designs miss: a zlib version bump changes
compressed bytes for identical input, so **container-byte reproducibility is not a portable
property and must not be claimed as one.** Part-payload equality is portable, is what a
reviewer actually wants ("did the content change?"), and is what a diff tool can show.

### The mechanism

```python
# omniweave_core/opc.py — THE ONLY module permitted to open a ZIP for writing (semgrep, I22)
CANONICAL_DATE = (1980, 1, 1, 0, 0, 0)

def write_opc(members: Sequence[tuple[str, bytes]], order: Sequence[str], *,
              compresslevel: int = 6) -> bytes:
    """Members in `order` first, then the remainder sorted lexicographically by name.
    ZipInfo constructed EXPLICITLY: fixed date, external_attr 0o644<<16, create_system 0,
    ZIP_DEFLATED at a pinned level, zip64 only when a size actually requires it."""

def part_digest(members: Sequence[tuple[str, bytes]]) -> bytes:
    """sha256 over  name \0 sha256(payload) \n  for members sorted by name. The D-PART digest."""
```

Rules, all enforced:

- **No clock, env, cwd or RNG in a compiler.** D1's semgrep gate G8 already bans `time.time()`,
  `os.getcwd`, `Path(".")`; I extend the rule set to `packages/omniweave-target-*`, add
  `random`/`secrets`/`uuid4`/`datetime.now`, and the conformance harness additionally
  monkeypatches `time.time` and `random.random` to raise during the determinism suite.
- **Timestamps come from `job.determinism.clock_ns`.** D1's `hello` frame already carries
  `"determinism":{"seed":0,"clock_ns":0}`. PPTX `docProps/core.xml` `dcterms:created`/`modified`
  and `app.xml` are written from it; `cp:revision` is fixed at `1`.
- **`PYTHONHASHSEED` is part of the gate.** The reproducibility test runs the same compile three
  times under `PYTHONHASHSEED ∈ {0, 1, random}` and asserts an identical D-PART digest. This is
  the gate that catches a set or dict iteration leaking into emission order, which is the most
  common way a "deterministic" builder is not.
- **Byte-preserve part payloads; canonicalize only the container.** We do not C14N OOXML parts —
  PowerPoint's tolerance for attribute reordering is not something to bet a release on. The
  builder's own XML emission is deterministic (lxml serializes in insertion order) *provided*
  nothing iterates an unordered collection, which is what the `PYTHONHASHSEED` gate proves.
- **Fonts.** An embedded subset must be produced by a pinned subsetter over a sorted glyph-id
  list; the receipt records `{face, source_sha256, subset_sha256, glyph_count}` per embedded
  face. ppt-master's `unsafe_exported_faces` becomes a receipt row rather than a print.
- **Video.** The reproducibility run pins `-threads 1` and `SOURCE_DATE_EPOCH`; the receipt
  records the ffmpeg version, encoder, and thread count. D1 binds `codec = "vp9"`,
  `ffmpeg = "system"`, and *"refuse rather than substitute a codec"* — honoured verbatim: a
  missing `libvpx-vp9` is `PROBE_UNAVAILABLE` and the target is pruned from the plan with a
  report, never silently re-encoded as h264.
- **`omniweave repro <artifact>`** rebuilds from the sealed `gen` and prints a member-level
  diff of the D-PART digest. It is a user-facing command because a reproducibility claim
  nobody can check is a comment.

---

## 5. `parse_back`, `ingest_back`, and the fidelity contract as a testable property

### 5.1 The split

The blueprint's single `parse_back()` conflates two obligations with different consumers,
different inputs and different failure modes. Splitting them is the highest-value correction
in this proposal.

| | `parse_back` | `ingest_back` |
|---|---|---|
| Signature | artifact → `il_node` rows + `RecoveryReport` | artifact → `DocSink` (D2 blocks) |
| Port | `compile/1`, operation `parse_back` | `parse/1`, a separate DriverId |
| Input domain | our artifacts first; foreign artifacts tolerated | **any** artifact of that kind |
| Enables | "editing a deck is the same code path as creating one" | "generated artifacts become corpus" |
| Declares | `capability.compile.parse_back` | D2 `Capabilities` (a full driver card) |
| pptx | yes | `parse.pptx.ooxml` |
| deck | yes | `parse.html.deck` |
| video | **no** | `parse.video.frames` |

They **share one reader**. `omniweave_target_pptx._opc` is opened once and projected two ways.
That is the "one implementation" discipline, and it is why the split costs almost nothing.

### 5.2 `Recovery` — the classification

```python
class Recovery(IntEnum):
    EXACT         = 0   # round-tripped bit-identically under the construct's canonicalization
    NORMALIZED    = 1   # recovered through a declared deterministic compatible-tier normalization
    RECONSTRUCTED = 2   # inferred from target primitives; same rendering, different spelling
    DROPPED       = 3   # the construct declares round_trip: dropped and it is absent
    FOREIGN       = 4   # present in the artifact, not produced by our IL (a human edited it)
```

`FOREIGN` is the point. A foreign node gets `origin_ref = NULL`, a construct from the
*tolerant* reader, and — when the reader cannot model it at all — becomes an **opaque
passthrough node holding the original part hash-pinned**, exactly D2's
`table_meta.native_part/native_sha256` pattern. Nothing is ever silently dropped.

Export-side classification is ppt-master's four tiers, taken whole
(`svg_to_pptx/pptx_package/cli.py:2951-2990`): `passthrough | cloned_passthrough | patched |
rebuilt`, **every output unit in exactly one bucket, the sum asserted, an unclassifiable unit
a hard error**.

### 5.3 The fidelity contract, stated as a property

> **P1 (round-trip identity).** For every artifact `A` in target `T`'s golden corpus, with IL
> `I` and `A = compile(I)`:
> `il_digest_rt(parse_back(A)) == il_digest_rt(I)`, where `il_digest_rt` is the
> `il_fingerprint` computed over the **round-trip recipe** — identical to §3.2 except that for
> every node it elides every payload key belonging to a construct whose `round_trip ≠ EXACT`.
> **The exclusion set is derived from the registry, not hand-tuned.** This is ppt-master's
> canonicalize-then-hash generalized, with the normalizations declared instead of coded.
>
> **P2 (total classification).** `parse_back` assigns exactly one `Recovery` to every recovered
> node and `sum(counts) == node_count`; `compile` assigns exactly one fidelity tier to every
> output unit and `sum == unit_count`. An unclassifiable node or unit is a hard error, and
> the counts are printed and stored in the receipt.
>
> **P3 (no false EXACT).** Every node whose construct declares `round_trip: EXACT` recovers
> with `Recovery.EXACT`, and `foreign_count == 0` on a corpus artifact.
>
> **P4 (the registry cannot lie).** For every construct `C` with `round_trip: EXACT`:
> (a) the golden corpus contains at least one artifact exercising `C`, and
> (b) a **semantic mutation** of `C`'s payload in that artifact changes `il_digest_rt`.
> A construct declared `EXACT` but never exercised, or whose mutation does not move the digest,
> **fails `omniweave-conform`**.

P4 is the systems contribution. P1–P3 are properties of an implementation; P4 is a property of
the *declaration*, and it is the same trick D3 uses for capability honesty (*"`charspan = false`
asserts charspans are absent"*). Without it, a target passes the round-trip suite by declaring
everything `lossy`.

### 5.4 What is allowed to be lost — three closed categories

1. **Presentation defaults.** Any attribute equal to its construct's declared default.
   Testable: `compile(I with the default stated explicitly)` must have the same D-PART digest
   as `compile(I with it omitted)`. The digest recipe elides defaults, so this is enforced by
   construction and the test only guards a registry mistake.
2. **Declared-lossy constructs.** `round_trip ∈ {LOSSY, DROPPED}` in the registry. The list is
   short, versioned, printed by `omniweave targets fidelity <target>`, and **shrinking it is a
   registry_version bump; growing it is a breaking change requiring a migration note.**
3. **Foreign content the reader declares it cannot model.** Retained as an opaque passthrough
   node with `native_part` + `native_sha256`, never dropped.

Everything else is a bug, not a tolerance.

### 5.5 The refusal that makes this safe

Generalized from ppt-master `cli.py:2890-2948`: **a rebuild that would drop an opaque
dependency refuses**, naming the exact paths and both ways out.

```
OW-T-501  round-trip export would drop source video, audio, or opaque payload relationships:
            unit 3 (source slide 5): ppt/media/media1.mp4, ppt/embeddings/oleObject1.bin
          Keep unit 3 as passthrough (`omniweave compile q3-review --pin-unit 3`), or remove
          the opaque relationship from the source before importing.
```

And the dependency analysis is precise, not blanket: a unit is blocked only when the *specific*
dependency paths are affected by the edit, with **unmapped relationships treated as at-risk
whenever visuals changed at all** — fail closed on the unknown.

---

## 6. Citations: how a store fact survives into the artifact and back

Seven steps, all mechanical.

1. Retrieval hands the agent `cite` tokens (`d7#412`) — D2's only prompt-safe identifier.
2. The agent writes the mandatory `cite` construct: `<ow:cite ref="d7#412"/>` (svg/1),
   `<Cite ref="d7#412"/>` (tsx/1), `data-ow-cite="d7#412"` (html/1). **Every registry must
   have it.**
3. `parse_il` resolves `cite → block_id` **against a pinned `doc_gen`** and writes `il_cite`.
   Pinning the generation is what stops a later re-parse of the source from silently
   re-pointing a shipped citation.
4. Validation:
   - `OW-T-201 CITE_UNRESOLVED` — no such block.
   - `OW-T-202 CITE_SUPERSEDED` — the block retired; `block_history.superseded_by` names the
     successor and the fix line offers `omniweave cite rebase`.
   - `OW-T-210 CITE_VERBATIM_UNPROVEN` — `kind='quote'` but
     `normalize_k(node.text) != block.text[span_a:span_b]`, or `block.quote != 'verbatim'`.
     Sets `il_cite.verbatim = 0`. **The author never asserts verbatim; the validator proves it.**
   - `OW-T-203 CITE_RESTRICTED` — `restriction_bits ∧ ¬policy ≠ 0` (D3-17). Raised at
     **`il_cite` insert time**, so the failure lands while the agent is authoring, not an hour
     later at compile.
5. Compile emits three channels, and the receipt records which landed per node:
   - **visible** — a rendered marker in the target's own vocabulary (a superscript run, a
     footer line, a notes entry). Suppressible by `[targets.pptx] visible_citations = false`;
     suppression is a receipt row, never silent.
   - **embedded** — machine-readable, inside the container: an OPC part
     `/omniweave/provenance.json` related from the presentation part
     (`http://omniweave.dev/relationships/provenance`) for PPTX/DOCX; a
     `<script type="application/ow-provenance+json">` block plus per-element
     `data-ow-cite` for deck; container metadata (`Tags`/`udta`) plus a `.owprov.json`
     sidecar for video.
   - **ledger** — the `il_cite`/`il_node`/`compile_run` rows. **Authoritative.**
6. `parse_back` recovers from the embedded channel only. It never infers a citation from
   visible text — a guessed provenance is worse than none. It reports per node
   `citations: recovered | ledger_only | lost`.
7. **The transitive claim.** `il_cite.block_id → block.origin` (`OriginGlyphs` / `OriginPixels`
   / `OriginNodePath`) `→ quad on page 13 of the source PDF`. `omniweave cite trace q3-review
   u3/7` prints the whole chain and can emit a crop of the source region. This is the
   blueprint's headline promise and it works only because D2 kept the polygons and the
   `origin_span` union.

**Honest limit, stated up front:** channel 2 is best-effort. PowerPoint may discard an unknown
OPC part on save. The loss is *detectable* (the ledger knows the part should be there), it is
reported by `omniweave cite verify`, and the ledger channel is unaffected — but a deck that has
been through PowerPoint may ship without embedded provenance. See failure mode F3.

---

## 7. Feedback, `manual_required`, the brief, and the asset ledger

### 7.1 Element-addressed feedback — a two-factor anchor

open-slide's verified rule (`editing/edit-ops.ts`, `findElementForEdit` /
`findUniqueElementByText`) generalized off JSX and onto nodes:

> **Location proposes, content disposes, uniqueness arbitrates.**

`Anchor = (addr, nsig, quote?)`. Resolution order:
1. `addr` resolves **and** `nsig` matches → bind, `MATCH`.
2. `addr` resolves, `nsig` differs → bind, `EDITED` (the node changed under the comment).
3. `addr` misses, `nsig` unique in the gen → bind, `MOVED`.
4. `nsig` ambiguous and `addr` missing → **refuse**, `OW-T-602 AMBIGUOUS_ANCHOR`. Never guess.

For text nodes, `quote` is the third factor and is **required** when the node has multiple text
children — open-slide's `'element has multiple text candidates; missing prevText'`, with the
same documented `.trim()` for renderer-vs-source whitespace.

**Marker presence is the state.** For `feedback = "in_artifact"` targets the marker lives in
the artifact (PowerPoint modern comments in `ppt/comments/`; an `@ow-note` comment with a
**base64url** payload for tsx/1 and html/1 — base64url so the marker's grammar stays a fixed
regular language whatever the human typed, exactly open-slide's reasoning; line numbers derived
from position, never stored, so nothing can go stale). If the store says `applied` and the
marker is still present → `OW-T-604 FEEDBACK_DESYNC`, **and the store is corrected from the
artifact**, because the artifact is what the human is looking at. A target with
`feedback = "sidecar"` (video) loses this guarantee and must use a monotone `applied_gen`
instead; the card says so and the receipt says so.

**Application is transactional over a closed op set** — six ops, generalizing open-slide's five
off text splices and onto nodes:

```python
EditOp = SetAttr | SetText | InsertNode | DeleteNode | ReplaceAsset | Reorder
```

Collect every op → apply in **reverse `addr` order** → re-run the **whole** validator → commit
gen N+1 or roll back entirely. Any op that cannot be modelled is a **refusal, not a rewrite**
(open-slide's `'style attribute has unsupported form'`). **Skip is a legal outcome** with a
defined representation: leave the marker, write `state='skipped'` with a `skip_reason`, report
it. An artifact-mutating apply never produces a partially-applied gen.

### 7.2 `manual_required`

A first-class outcome, not an exception, with a **closed** reason vocabulary generalized from
ppt-master's content-family → realization → non-negotiable-boundary table:

```
unverifiable_wording | unverifiable_identity | unverifiable_data | insufficient_source
| unrepresentable_construct | licence_barred | measurement_failed
```

Rules carried verbatim:
- *"Graphic identity is authoritative; source pixel bytes are not."*
- *"Source clarity never decides whether a required editable object becomes a separate layer,
  only how that layer is prepared."* Generalized: **evidence sufficiency decides realization,
  never structure.**
- **Unresolved evidence blocks delivery.** `il_evidence.resolved = 0` on any region ⇒ gate
  status `manual-required`.
- **Observation and decision are separate artifacts.** `il_evidence` records only what is
  visibly present — bbox, family, verbatim text, confidence, sufficiency, occlusion — and
  explicitly no layer choices, prompts, filenames or IL bindings. This is what stops a model
  from rationalizing an observation to fit a decision it already made.

### 7.3 The frozen brief

`<artifact>.brief.md`: a schema-version HTML comment on line 1 and a two-production grammar
(`## section`, `- key: value`), human-diffable and machine-parseable, digested into
`artifact.brief_sha256`. Three prohibition tiers with different owners: technical baseline
(untagged), **user prohibitions verbatim and `(user)`-tagged**, template rules (never copied
in). **The validator rejects an untagged non-baseline prohibition row**, so nobody smuggles a
designer opinion into the hard-constraint list. The brief is written once by `omniweave author`
and is immutable for the artifact's life; changing it is `omniweave brief amend`, which records
a diff and bumps `brief_gen`. **The role that consumes the lock cannot write it.**

The anti-drift rule is a validator rule, not prose: `OW-T-407 UNDECLARED_VALUE_PATTERN` fires
on the **third distinct occurrence** of a value outside the brief's declared token set, with a
±2px anchor drift budget. One-off exceptions are legal; a *pattern* of exceptions means the
contract is wrong.

Where a rule genuinely cannot be enforced (ppt-master's *"never a merely similar substitute"*),
the skill manifest **labels it unenforceable** — hyperframes' treatment — rather than pretending.
The doctrine is carried verbatim: *"prompts, templates, and examples are not a correctness or
safety boundary."*

### 7.4 The asset ledger

It is D2's `asset` table plus `artifact_asset`. **There is no `.media/manifest.jsonl`.**
hyperframes' ledger (`skills/media-use/scripts/lib/manifest.mjs`) is the best in the
collection and it still carries only `provenance.prompt` — a `grep` for licence fields in that
module returns nothing. D2's `asset` row already has `licence, licence_url, spdx, source_url,
retrieved_at_ns, sha256, store_ref`; adding a JSONL SSOT beside it creates two things that can
disagree.

Enforced at compile:
- Every referenced asset is **frozen**: `store_ref NOT NULL` and the CAS bytes re-hashed
  (`OW-T-301 ASSET_NOT_FROZEN`, `OW-T-302 ASSET_DIGEST_MISMATCH`).
- Every asset has a non-null `spdx` (`OW-T-304`).
- A generated asset carries a `producer_id` row, so "this logo came from model X at revision Y"
  is in the receipt.
- `OR(restriction_bits)` over every reachable node and asset is admitted by policy, or the
  compile **refuses naming the offending ids** (D3-17). The check is one SQL aggregate, run at
  plan time and again at compile.
- `Restriction.ATTRIBUTION_PER_OUTPUT` (bit 8) ⇒ the receipt must contain the attribution
  block **and** the target must emit it into the artifact; a target that cannot express
  attribution refuses the asset rather than shipping an unattributed artifact.

---

## 8. The receipt

```jsonc
{"schema":"omniweave.compile-receipt/1","status":"passed-with-warnings",
 "target":"pptx","driver":"compile.pptx.drawingml@omniweave-target-pptx","driver_schema_v":1,
 "artifact":{"slug":"q3-review","gen":4,"path":"…/q3-review.pptx","bytes":4211934,
             "sha256":"…","part_digest":"…"},
 "il":{"fingerprint":"sha256:9c2f…","registry_version":3,"registry_digest":"sha256:5c1a…",
       "nodes":16233,"units":40},
 "gate":{"status":"passed","stage":"final","source_match":"passed","introduced_warnings":3},
 "determinism":{"class":"part","byte_asserted":true,
                "env":{"python":"3.11.9","zlib":"1.3.1","compresslevel":6,
                       "deps":{"python-pptx":"1.0.2","uharfbuzz":"0.39.1"},
                       "toolchain":null,"pythonhashseed_runs":3}},
 "fidelity":{"passthrough":0,"cloned_passthrough":0,"patched":0,"rebuilt":40,
             "sum":40,"unit_count":40,"asserted":true},
 "checks":{"zip_integrity":"passed","unit_count":"passed",
           "internal_relationships":"enforced-at-build","registry_closure":"enforced-at-build",
           "quality_gate":"passed","citation_channels":"passed","text_overflow":"warning",
           "font_portability":"warning","external_images":"passed","asset_ledger":"passed"},
 "citations":{"nodes":52,"visible":52,"embedded":52,"ledger":52,"unresolved":[],"restricted":[]},
 "restrictions":{"bits":0,"offending":[]},
 "assets":[{"id":"a7","sha256":"3f9c…","spdx":"CC-BY-4.0","attribution_required":false}],
 "portability":{"fonts":{"stacks":["Inter, sans-serif"],"generic_only":[],
                         "embedded":[{"face":"Inter-Regular","source_sha256":"…",
                                      "subset_sha256":"…","glyphs":412}],
                         "resolution":"embedded"},
                "images":{"local":14,"external":0,"external_refs":[]},
                "unresolved_tokens":[]},
 "bake":[{"addr":"u07/3","construct":"mix-blend-mode","raster":"a9","reason":"bake-required"}],
 "manual_required":[],
 "degradations":[],                 // D4's channel, verbatim
 "trace_ref":"cas://…/q3-review@4.trace.json"}
```

Two things carried whole from ppt-master:
- **`"enforced-at-build"` is a first-class check value.** Some invariants are guaranteed by
  construction; re-verifying them postflight is theatre, and saying so is better than either
  omitting the row or faking the check.
- **The portability audit is a separate axis from validity.** Generic-only font stacks, unsafe
  exported faces, external image references and unresolved tokens do not make a file invalid;
  they make it break on someone else's machine.

And the compiler **independently re-verifies postflight** and raises rather than reporting
success: open the produced package, assert ZIP integrity and
`package['slides'] == unit_count`. **File creation is not proof the gate passed.**

Console output is one line; the JSON goes on disk:
```
[POSTFLIGHT] q3-review@4 status=passed-with-warnings gate=passed units=40 rebuilt=40 warn_cats=2
```

---

## 9. The first three targets

### 9.1 `pptx` — `compile.pptx.drawingml`, dist `omniweave-target-pptx`, **pure Python**

- **IL syntax `svg/1`**: canonical SVG subset, ppt-master's proven surface. Registry ≈ 120
  constructs. Tiers seeded directly from `svg_quality/svg_contracts.py:180-188` — 29 supported
  inline style properties (canonical), the documented alias set (compatible),
  `mix-blend-mode` / `isolation` / `backdrop-filter` (bake), `mask` + `<style>` + `class=` +
  `<textPath>` + `@font-face` + SMIL + `<script>` + `on*=` + `<iframe>` + `<foreignObject>`
  (invalid). The **conditional** prohibition — `id=` invalid *iff* `<style>` is present, because
  the hazard is the pair and `id` inside `<defs>` is required — stays a `Rule`, since a
  registry cannot express a pairwise condition. That is precisely why rules exist beside it.
- **determinism `["part","byte"]`.** Build the package with python-pptx into memory, then
  serialize through `omniweave_core.opc.write_opc`. Never `Presentation.save()`, whose
  `writestr` path stamps local wall-clock time into every member.
- **text measure**: uharfbuzz + the resolved font file — already in D1's dependency list for
  this distribution (`python-pptx, XlsxWriter, skia-pathops, uharfbuzz, Pillow`). Overflow is a
  **finding**, never a prompt instruction.
- **`parse_back` yes.** `EXACT` for the constructs with native DrawingML inverses;
  `RECONSTRUCTED` for path geometry compiled to custom geometry; nothing `DROPPED` — anything
  unmappable becomes an opaque passthrough node.
- **`ingest_driver = "parse.pptx.ooxml"`**, a `parse/1` driver sharing `_opc`. Declares D2
  `Capabilities`: `spatial: block_bbox`, `origin_span: normalized` (`nodepath`; `exact` once C3
  is amended), `reading_order: source`, `tables: cells_with_spans`, `notes: linked` (speaker
  notes are blocks with `layer: note` — the thing marker throws away, `mine-parse.md:1465`),
  `round_trip: structure`.
- **feedback `in_artifact`** via PowerPoint modern comments.
- **Why first:** D1 makes it the flagship precisely because it needs zero Node
  (`pip install omniweave[pptx]` is a 60 MB one-liner), and it is the only target in the
  collection with a working round-trip precedent to check ourselves against.

### 9.2 `deck` — `compile.deck.openslide`, dist `omniweave-target-deck`, Node Toolchain

- **IL syntax `tsx/1`**: a closed component set (`<Deck> <Page> <Steps> <Step> <Media> <Cite>`)
  with a closed prop grammar and **no arbitrary expressions in props**. Registry ≈ 45
  constructs.
- **This is where we overtake the source repo.** open-slide has *no semantic validator at all* —
  only `tsc --noEmit` and biome, i.e. "is this valid TypeScript", never "is this a valid
  slide". Everything it leaves unchecked becomes a rule: 1080px vertical fit (**measured**
  in headless via `window.__ow.measure`, hyperframes' off-canvas `pretext` pattern, never
  arithmetic the model redoes by hand), `<Step>` outside `<Steps>`, an undeclared
  `var(--osd-X)` token, an unresolvable asset import, `meta.createdAt` parseability. The
  notes/page misalignment bug — *"silently attaches the wrong script to every page after it"* —
  is dissolved structurally: **a page is one node, notes are a child construct**, so there are
  no index-aligned parallel arrays to misalign.
- **determinism `["render","part"]`.** D-PART on the emitted source tree (our serializer);
  D-RENDER on the browser output. We do not claim byte determinism for a bundler we do not own.
- **`parse_back` yes** — the artifact carries the authored source, parsed by the toolchain's own
  parser with open-slide's verified two-function policy: an error-recovering parse for read-only
  transforms, a strict parse (rejects any recovered error) for anything that writes.
- **feedback `in_artifact`** — open-slide's `@slide-comment` marker taken essentially verbatim
  as `@ow-note`, base64url payload, position-derived line, reverse-order application, skip by
  leaving the marker.
- Any HTTP surface it exposes ships open-slide's `packages/core/src/http/request-guard.ts`
  (76 lines, verified) as a **minimum**, and D1 already forbids the loopback-server shape for
  everything else.

### 9.3 `video` — `compile.video.hyperframes`, dist `omniweave-target-video`, Node Toolchain

- **IL syntax `html/1`**: canonical HTML plus a closed timing attribute set. Taken verbatim
  from `packages/parsers/src/compositionContract.ts:9-32`, including the tier split that maps
  1:1 onto mine: authored/canonical = `data-start`, `data-duration`, `data-track-index`;
  derived = `data-end`; legacy/compatible = `data-end`, `data-layer`. And the doctrine, which
  is the same as ppt-master's stated in one line: *"Readers accept legacy documents; writers
  always emit the canonical representation."*
- **The determinism contract is a validator, not a hope.** Rules forbidding `Date.now`,
  `Math.random`, `performance.now`, un-owned `<video>`/`<audio>` playback, rAF-driven state and
  render-time network fetch — plus runtime traps in the render harness
  (`globalThis.Math.random = () => { throw }`). The framework owns media playback because a
  `<video>` element playing itself is not seekable.
- **determinism `["frame"]`.** 12 frames sampled as `blake2b(artifact_id‖idx‖salt) % n`
  (D4's R2 rule — never RNG), decoded to raw and compared, plus full-PCM comparison.
- **`parse_back` FALSE, and that is the honest call.** You cannot recover an IL from an MP4.
  The edit loop still closes — the IL is in the store, so editing a video is editing its IL —
  and the corpus loop closes through `ingest_driver = "parse.video.frames"` (keyframes + ASR +
  the `.owprov.json` sidecar → blocks). Declaring `parse_back = false` and naming an
  `ingest_driver` is exactly what the contract is for.
- **feedback `sidecar`** (`<artifact>.owfb.json`), which loses presence-is-state; the card says
  so and a monotone `applied_gen` replaces it.
- D1's bindings honoured verbatim: `ffmpeg = "system"` (never bundled — libx264 makes a bundle
  GPL-2.0-or-later), `codec = "vp9"`, refuse rather than substitute.

`docx` is target four, on the same registry machinery with `il_syntax = "html/1"` and
`determinism = ["part","byte"]`. It is deliberately not in the first three: it adds no new
mechanism, and the three chosen exercise all four determinism classes, both feedback channels,
and both sides of the `parse_back` / `ingest_back` split.

---

## 10. Invariants and their enforcement

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Every `il_node.construct` exists in the target's registry at the artifact's `registry_version`. | SQL FK `il_node(target,registry_version,construct) → il_construct` (via `artifact`) |
| I2 | No stored node has tier `invalid`. | `CHECK (tier <> 3)` on `il_node`; `parse_il` converts an invalid construct into a Finding, never a row |
| I3 | `compile()` is never entered while the final report has `blocking > 0` or a `manual_required` row. | The compiler recomputes the gate **from the store**, not from the report file; `GateStatus != 'passed'` is a refusal naming the status and the fix command |
| I4 | The report binds to the exact IL: `il_fingerprint` recomputed at compile equals the report's. | Same function in-process; the toolchain recomputes over `il/` bytes per `schema/il-fingerprint-v1.md`; mismatch ⇒ gate `stale` |
| I5 | A compiled artifact is reproducible in every class the card declares. | `omniweave-conform` suite `determinism`, 3 runs × `PYTHONHASHSEED ∈ {0,1,random}`; `omniweave repro` for users |
| I6 | No compiler reads a clock, env, cwd, or RNG. | semgrep (D1 gate G8, extended to `packages/omniweave-target-*`); the determinism harness monkeypatches `time.time`/`random.random` to raise |
| I7 | Only `omniweave_core.opc` opens a ZIP for writing. | semgrep ban on `zipfile.ZipFile(..., 'w'/'a'/'x')` and `shutil.make_archive` outside it |
| I8 | Every asset referenced by the IL is frozen and re-hashed at compile. | `store_ref NOT NULL` + a CAS re-hash; `OW-T-301`/`OW-T-302` |
| I9 | `OR(restriction_bits)` over reachable nodes and assets is admitted by policy, or compile refuses naming the ids. | one SQL aggregate at plan **and** compile; conform test parses with a synthetic restricted driver and asserts the refusal survives parse → derive → compile (D3-17) |
| I10 | `il_cite.verbatim` is proved, never claimed. | validator rule `OW-T-210`: `normalize_k(node.text) == block.text[a:b]` **and** `block.quote='verbatim'` (requires conflict C3's amendment for office sources) |
| I11 | Every output unit falls in exactly one fidelity tier; the sum is asserted and printed. | hard error in the compiler; receipt field `fidelity.asserted` |
| I12 | Every recovered node falls in exactly one `Recovery`; the sum equals the node count. | hard error in `parse_back`; `recovery.json` |
| I13 | A construct declaring `round_trip: EXACT` is exercised by the corpus and its mutation moves `il_digest_rt`. | conform suite `roundtrip`, property P4 |
| I14 | A rebuild that would drop an opaque dependency refuses, naming the paths and both ways out. | `OW-T-501`; fixture: a deck with an embedded `.mp4` and an OLE object |
| I15 | For `feedback: in_artifact`, marker presence in the artifact is the state; a store disagreement corrects the store. | `OW-T-604`; a test applies a comment, reverts the artifact, and asserts the store row returns to `pending` |
| I16 | Feedback application is all-or-nothing: collect → reverse-`addr` apply → full revalidate → commit gen N+1 or roll back. | one transaction; a fault-injection test kills mid-apply and asserts gen N is untouched |
| I17 | `manual_required` blocks delivery and is a gate value distinct from `failed`. | gate enum; `il_evidence.resolved = 0` ⇒ `manual-required` |
| I18 | Bake is opt-in per node, returns a structured record, lands in the trace, and is counted in the receipt. | `--bake <addr>` only; no config key enables it globally; `receipt.bake[]` |
| I19 | A bake whose subtree contains a `verbatim` citation refuses. | `OW-T-215`; test fixture |
| I20 | An OUT edit writes a new `gen`; a sealed gen's `il_node` rows are insert-only. | `artifact_gen.sealed_at_ns NOT NULL` + a `BEFORE UPDATE`/`BEFORE DELETE` trigger raising on a sealed gen |
| I21 | The text projection round-trips: `parse_il(emit_il(nodes)) == nodes`. | CI property over the golden corpus, per target |
| I22 | Every registry is closed: `mandatory ⊆ constructs` and `cite ∈ constructs`. | `ConstructRegistry.__post_init__`; conform suite `card` |
| I23 | A skipped check is visible in the report and the gate is `unverified`, never `passed`. | `OW-T-190`; conform test removes the font file and asserts the gate does not read `passed` |

---

## 11. Build order and cost

| Phase | Weeks | Ships |
|---|---:|---|
| **P1** core algebra | 6 | `omniweave_core.il`: DDL + migrations, `ILSink`, `ConstructRegistry`, registry-derived checks, rule scheduler, `Finding` + provenance classes, `il_fingerprint`, the nine-value gate, `omniweave_core.opc`. `omniweave.ports.compile_v1`. **Runs:** `omniweave il validate` against a hand-written registry. I1–I4, I7, I22, I23. |
| **P2** pptx | 8 | The ~120-construct registry, `emit_il`/`parse_il` for `svg/1`, the DrawingML compiler, deterministic OPC write, uharfbuzz measurement, the receipt. **Runs:** `omniweave compile` produces a byte-reproducible deck. I5, I6, I11, I18. |
| **P3** ledger + citations | 4 | `artifact_asset`, the freeze/verify path, restriction admission, `il_cite` + the three channels, `omniweave cite trace`. I8–I10, I19. |
| **P4** the loop | 6 | `parse_back` for pptx, `Recovery`, `parse.pptx.ooxml`, the four fidelity tiers and the opaque-dependency refusal, `omniweave repro`. **Runs:** edit a generated deck through the same code path. I12–I14, I20, I21. |
| **P5** feedback + brief + manual | 4 | The two-factor anchor, the six-op transaction, marker channels, `brief.md` grammar and the drift rule, `il_evidence` and `manual_required`. I15–I17. |
| **P6** deck | 8 | The tsx/1 registry, the toolchain, headless measurement, `@ow-note`, `parse_back`. |
| **P7** video | 8 | The html/1 registry with the determinism validator, the frame-sampling suite, `parse.video.frames`. |
| **P8** conform | 3 | Suites `registry`, `determinism`, `roundtrip`, `ledger`, `feedback`, `citations` — all under the five-minute mandatory-tier budget D3 enforces as a timing assertion. |

**≈47 engineer-weeks** for two people to P7, plus the standing cost of owning three registries.
That is the honest number and it is large. P1+P2+P3 (18 weeks) is the point at which
`omniweave compile` produces a citation-carrying, byte-reproducible, licence-audited PPTX,
which is a shippable product; P4 (6 more) is where the loop closes.

**Runtime and memory.** Validation is 30–60 rules over the node stream; measured against D2's
`owcheck` figure of ~240 ns/block, budget **5–20 µs/node** (rules do real work — schema
validation, text shaping) ⇒ a 40-unit deck at ~400 nodes/unit = 16k nodes ⇒ **0.1–0.3 s**.
Memory is bounded by the same discipline as D2: `ILSink` commits one transaction per unit, no
traversal returns a list, and `MAX_IL_NODES_PER_UNIT` / `MAX_IL_NODES` are `omniweave_core.limits`
constants a tenant may only clamp **down**.

**Dependency weight.** Zero new distributions — the algebra is stdlib inside `omniweave-core`,
the port typing rides in `omniweave-ports`, and the three target distributions are D1's. Core's
storage grows by nine tables in the existing `.owstore`.

**Operational burden.** Three construct registries need an owner. A registry is a versioned
contract; every PR that touches one is reviewed against the severity doctrine, and `registry_digest`
must be regenerated (a byte-diff gate, D1's G6 shape). Budget **~0.2 FTE per active target**.

---

## 12. Failure modes, honestly

- **F1 — a construct declared `EXACT` whose real inverse is lossy in a way the corpus never
  exercises.** P4's mutation test catches a *structural* miss but only if the mutation is
  semantic; a subtle DrawingML rounding difference passes. This is the residual risk of the
  whole round-trip claim and it is not eliminated.
- **F2 — a dependency changes emission order in a patch release** (lxml, python-pptx) and
  byte-reproducibility breaks a release for no user-visible reason. Mitigated by exact pins and
  by D-PART being the *promised* class, with D-BYTE only asserted inside a pinned resolution;
  it will still produce a red CI nobody understands at least once.
- **F3 — the common case breaks the provenance claim.** A user opens the PPTX in PowerPoint,
  edits one word and saves. PowerPoint rewrites every part: `addr` anchors are destroyed
  (`nsig` content anchors survive), and it may discard `/omniweave/provenance.json`. Result:
  citations degrade to `ledger_only` and the *shipped file* no longer carries provenance. This
  is the input that breaks "provenance survives a full round trip", it is the ordinary case,
  and the design's only answer is that the loss is detectable and reported, not prevented.
- **F4 — measurement disagreement.** uharfbuzz shapes with the *installed* font; PowerPoint
  renders with the *embedded or substituted* one. Overflow findings are therefore
  advisory-accurate, not exact, and the receipt records `font_resolution:
  embedded|matched|substituted` per face so a reader knows which.
- **F5 — bake destroys addressability.** Rasterizing a subtree makes its text unselectable and
  its descendants unaddressable for feedback. I19 refuses a bake over a `verbatim` citation,
  but a bake over a *paraphrase* citation silently moves the anchor to the raster node. That is
  a real fidelity loss recorded in `receipt.bake[]` and nowhere else.
- **F6 — the adversarial IL.** A generated chart emitting one node per data point: 2M nodes on
  one unit. `MAX_IL_NODES_PER_UNIT` refuses with `OW-T-101 ResourceLimit{limit}` naming the
  knob, which is correct and still means the user's chart does not compile. The remedy is a
  `chart` construct with a data payload, which is the right answer and is target work.
- **F7 — registry sprawl.** 120 constructs today; in three years, 400, of which forty are
  `compatible` aliases nobody generates and nobody dares delete. `omniweave targets fidelity`
  surfaces the count and `since_version` dates them; the promotion/demotion protocol says how to
  retire one; neither stops it.
- **F8 — a target declares a weak determinism class to pass the suite.** `determinism = []` is
  syntactically legal. Mitigated socially (the card is public and `omniweave drivers explain`
  prints it) and by making D-PART a **floor for any target in `[targets] enabled` by default**;
  a weaker declaration requires an explicit config opt-in. Not eliminated.
- **F9 — two writers.** D2 gives one writer per `.owstore`. A long compile that held a write
  transaction would block parsing. Mitigated structurally: `compile` writes only at unit
  boundaries and only to the OUT tables; artifact bytes go to CAS, never to a BLOB column.
- **F10 — PowerPoint comment dialects.** Modern comments (`ppt/comments/modernComment*.xml`)
  are invisible to older PowerPoint, which uses `cmAuthorLst`. A deck reviewed in an old client
  loses the feedback channel silently from the reviewer's side. The receipt records which
  dialect was written; there is no way to write both safely.
- **F11 — `registry_digest` drift across the language boundary.** A pnpm bump changes the
  toolchain's construct set with no Python-side signal. The `ready` frame's `registry_digest`
  catches it, which is why I added it; it is also one more thing that must not be forgotten in
  a toolchain release.

---

## 13. Rejected alternatives

- **`GeneratorTarget` as an ABC with nine methods, one per blueprint bullet** (the literal
  blueprint sketch). It is a shape, not a contract: nothing prevents `validate()` from returning
  `[]`, `assets()` from returning the input unchanged, or `parse_back()` from raising
  `NotImplementedError`. Every one of those is a *silent* degradation. The fix is not more
  methods; it is that each obligation becomes a **declaration the kit checks in both
  directions** — which is D3's proven mechanism applied to OUT, and it is why my contract has a
  registry and a card block rather than nine abstract methods.
- **One universal IL across all targets.** hyperframes' `data-start`/`data-duration`/
  `data-track-index` and DrawingML's `a:prstGeom` share nothing above "tree with attributes",
  and an abstraction at that altitude constrains nothing. The mined evidence is that the three
  repos converged on **seven mechanisms**, not on one language — so the mechanisms are what to
  factor out.
- **The L2 block model as the IL.** `trust`, `quote`, `method`, `producer_id` and
  `origin_operator` are extraction axes and category errors on authored content; D2's 34-member
  `kind` is a document-semantics vocabulary with no room for a connector, a track index or an
  animation trigger; and pushing visual constructs into `payload` recreates D2's own named
  `x`-bag shadow-schema risk at ten times the volume.
- **IL as files only, no store table** (ppt-master's shape). Feedback anchors go stale on every
  edit — open-slide invented `prevText` for exactly this reason and ppt-master's
  `source_path: tuple[int,...]` is invalidated by any sibling insertion; citations become
  comments; `restriction_bits` enforcement becomes a grep; cross-generation diffing needs N
  trees on disk. One integer column buys all four back.
- **Markdown as the IL** (or as the primary channel). D2 already rules that eleven of the
  collection's parsers hand downstream a string and that is why nothing needing
  citation-to-pixel or round-trip can be built on their output. The same argument runs in the
  OUT direction with the same force: a Markdown IL cannot carry a quad, a track index, a
  fidelity tier or a node identity.
- **A second independent validator implementation** (ppt-master's two-fingerprint pattern,
  generalized). ppt-master needs it because its checker and exporter are separate processes
  reading files; the risk it guards is staleness, which the store removes. Where a second
  implementation is unavoidable (a Toolchain in TypeScript) it is specified in
  `schema/il-fingerprint-v1.md` and CI runs a cross-language parity fixture — the one form D1
  already sanctions.
- **A JSON-Schema-first or protobuf IL definition with a code generator.** D1 rejected an IDL
  for the substrate and the reasons hold here: a fourth build system with one consumer, and
  proto3's all-optional model cannot express "every node has a construct and a tier". The
  registry is Python, `schema/*.json` is generated from it and byte-diff gated (G6).
- **`parse_back` as a single function.** Conflates "any artifact of this kind becomes corpus"
  (must work on foreign input, produces blocks, needs a full `parse/1` card) with "our artifact
  becomes editable IL" (needs only our output, produces IL nodes, tolerates foreign). One
  function means one fidelity contract for two problems, and the weaker one wins.
- **A router for compile targets.** The artefact kind is *requested*, not inferred, so
  `Requirement(port="compile/1", format="pptx")` normally admits exactly one candidate. Building
  D4-style ranking over compiles would be a mechanism with no decision to make.
- **Byte-reproducibility promised to users.** A zlib version bump changes compressed bytes for
  identical input. Promising D-BYTE portably is a claim that will be falsified by a base-image
  update; D-PART is the property that is both true and useful.
- **hyperframes' `.media/manifest.jsonl` as the asset ledger.** It is the best ledger in the
  collection and it still carries only `provenance.prompt` — no `spdx`, no licence URL, no
  source URL (checked: a licence grep over
  `skills/media-use/scripts/lib/manifest.mjs` returns nothing). D2's `asset` table already has
  all of it, and a JSONL SSOT beside a SQL table is two things that can disagree.
- **`attribution_guard.py`'s shape** — hashing `LICENSE`, asserting frontmatter and requiring a
  `SPONSORS*.md` as a runtime precondition of conversion. Attribution ships as licence text and
  a `NOTICE`, never as a pipeline gate that breaks an unrelated task with a useless message.
- **Per-unit validation between the two gates.** ppt-master rejected it on economic grounds and
  the reason survives translation: for us the validator is cheap, but the *agent's* re-read of
  the report is not, and that is the actual budget. Two gates, a five-unit method sample, ≤6
  units skips the early gate, zero validator calls in between.
