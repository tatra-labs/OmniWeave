# D8-out — The OUT compiler contract and closing the loop

## Decision

There is no `GeneratorTarget` abstraction over "generation" and no universal omniweave IL. A
**Target** is an artefact kind (`pptx`) implemented by exactly two Drivers on D3's existing ports —
a `compile/1` Driver and a `parse/1` Driver — plus **four target-owned artefacts**: a
`constructs.toml` **ConstructTable**, a **RulePack** of one-function-per-file predicates, a
`lower()`, and a `read_back()`. Everything else is framework code in `omniweave_core.out` that
every target gets for free and no target may reimplement: the Finding model with orthogonal
severity/provenance, the rule runner, the ten-value **GateStatus** bound to `il_digest`, the asset
ledger over D2's `asset` table, the `OWC1` feedback marker grammar, the brief, `manual_required`,
the seven-outcome unit classification, the receipt, the round-trip laws and the conformance suite.
**An IL is a carrier + a ConstructTable + a RulePack** — a closed, declared subset of an existing
text format where the subset is data and the enforcement is code; it is **text on disk**, never a
node table in the store, and it is **retained content-addressed in CAS**, which is what makes
editing an omniweave-built artefact a `passthrough` operation rather than a reconstruction.
`read_back` is an ordinary `parse/1` Driver writing through `DocSink`, so a generated artefact
re-enters the corpus through the pipe that already exists; `project(Doc) -> IL` is a method on the
compile driver and is the only reconstruction path. Determinism is a **declared set** over four
classes — `part` (member-payload equality, portable, the floor) / `byte` (container bytes, asserted
under a pinned resolution, recorded, never promised) / `frame` / `render` — because container-byte
reproducibility is not a portable property and every proposal that promised it was wrong. First
three targets: **`pptx` (pure Python, `passthrough`), `deck` (Toolchain, `render`), `docx` (pure
Python, flow carrier)**; `video` is fourth and ships from release 1 as a declared-unimplemented
card, because `mine-out.md` PART 3 on hyperframes was never written and I will not design a
construct table from an index page.

## Spec

**1. What an IL is.** `IL(target) = (carrier, ConstructTable, RulePack)`. The carrier is an existing
text format with an existing parser — `svg` for `pptx`, `html` for `deck` and `docx`. Zero of the
three mined repos invented syntax; that is the adoption constraint, and an LLM authors SVG far
better than a tree of JSON objects. The ConstructTable is the contract, as TOML data with one row
per allowed construct. The RulePack is the enforcement, as functions. This is the answer to "a
schema, a grammar, or a subset": a subset of an existing format, whose *description* is a table and
whose *enforcement* is code, because the three things a real table must express are not shape
constraints — a bake tier with a deterministic degradation, a conditional prohibition (`id=` is an
error only when `<style>` is also present), and a cross-element occurrence budget ("the third
undeclared value is an error"). All three are verified in ppt-master's source; none is expressible
in JSON Schema.

**Correction to the record.** All three proposals and `digest-out.md` state ppt-master's closed
inline-style surface is **29** properties. It is **32**
(`_SUPPORTED_INLINE_STYLE_PROPERTIES`, `svg_quality/svg_contracts.py:180-188`, counted). The three
bake-required and one fail-closed are correct. The number matters because it was about to seed a
registry row count.

**2. Why not a node table in the store (against the systems proposal).** Its central claim — that
IL-as-files makes feedback anchors go stale — does not survive the source. ppt-master's own
round-trip stamps `SOURCE_REF_ATTRIBUTE = "data-pptx-source-ref"`
(`extract_svg_assets.py:81`) into the authoring SVG and keys `source_refs: dict[str,
SourceRefRecord]` on it; `source_path: tuple[int,...]` (`authoring_roundtrip.py:87-88`) is a
*resolution* path, not the identity. A stamped attribute in the file **is** the durable anchor, and
it survives file edits precisely because it is in the file. An `il_node` table is therefore a second
representation of a thing the text already carries — the exact pattern D2 forbade for L4 — costing
nine tables, a parallel identity system (`node_id`/`addr`/`nsig`/`origin_ref`), and a
`parse_il(emit_il(n)) == n` property in the wrong direction: making the node table the pivot means
the agent's authored file is rewritten by `emit_il` on every validate, which contradicts the rule
the same proposal adopts elsewhere ("the checker never rewrites source SVG").

**3. Retention, not reconstruction — the central synthesis.** ppt-master's round-trip keeps
`flat_source_path` / `layered_source_path` backing SVGs and regenerates the comparison baseline from
them; it does not reconstruct authoring source from a PPTX. omniweave does the same, explicitly:
the IL bundle is frozen into CAS at compile time and pointed at by `artifact_unit.il_sha256`.
Editing an omniweave-built artefact fetches the retained IL — no lossy pivot, no reconstruction,
`passthrough` for untouched units. `project(Doc) -> IL` exists for foreign artefacts and for
artefacts whose IL was lost, is honestly a `rebuilt` path, and declares its loss. Two paths, both
named, each with a fidelity ceiling on the card.

**4. Validation: framework infrastructure, target rules.** `CompileV1` has **no `validate()`** — a
target that could run its own gate could skip it. The framework runs the RulePack against a
`CarrierDoc`; registry-derived checks (construct exists, disposition, attribute schema, deterministic
normalization applied and recorded) are free for every target. One rule per file, one test per file,
signature `(ctx) -> Iterable[Finding]`, ordered by an integer phase where phase 0 is the carrier
parse and short-circuits. Per-group timings plus the single slowest rule as `<group>#<index>`, so a
pathological rule is locatable (hyperframes `packages/lint/src/types.ts:20-27`). Ten framework rules
ship: cite resolution, cite verbatim proof, cite coverage, asset resolved, no external reference,
asset permitted, brief forbidden, anchor drift, unit/IL bijection, marker clean. A rule whose
`needs` are unmet emits a `framework`-provenance `info` finding and the gate becomes `unverified`,
never `passed`. **No auto-fix, ever** — `--fix` does not exist and a semgrep rule bans any write
under `il/` from `rules/`.

**5. Severity and provenance are orthogonal.** ppt-master conflates them (`blocking = errors`,
`introduced = warnings`, `checker.py:9192-9230`); D1's own wire frame already carries both on one
finding. `severity ∈ {error, warning, info}` decides whether it blocks; `provenance ∈ {introduced,
inherited, imported, framework}` decides who owns it and which fix command prints. An inherited
*error* still blocks, attributed to the template. Findings fold on `(code, rule, unit, canonical)`
with a count and ≤3 examples, so 200 lowercase hex colours are one recommendation.

**6. The gate.** Ten values, exactly one passes:
`not-provided | unreadable | unsupported-schema | non-final | unverified | failed | stale |
restricted | manual-required | passed`, plus a report-level `passed-with-warnings`.
`not-provided ≠ failed`. Every non-`passed` status prints the exact command that clears it. It binds
to bytes: `il_digest` uses ppt-master's verified framing (`checker.py:9335-9368` — basename-sorted,
`name\0sha\n`, an unreadable file contributing the literal `unreadable` plus an error row). **One
implementation**, recomputed by the same function at compile; the drift ppt-master's two
implementations guard is temporal, not implementational, and the store cannot go stale under us.
The only second implementation is the Toolchain's, because it is a second *language*; it is
specified in `schema/il-digest-v1.md` with a cross-language parity fixture, which is the one form
D1 already sanctions. Two gates: early over the first 5 units as a method sample with mechanical
classification (fires on ≥3 of 5 ⇒ method-level), ≤6 units skip it, **zero validator calls between
early and final**, distinct report filenames per stage.

**7. Determinism.** `Determinism` is a declared set over `{part, byte, frame, render}`, compared
`⊇`. `part` is the floor for any enabled target. The split is not pedantry: a zlib bump changes
compressed bytes for identical input, so container-byte equality is not portable and must not be
promised. Verified against CPython 3.11.9: `ZipInfo.from_file` does
`mtime = time.localtime(st.st_mtime)`; `ZipFile.writestr` constructs
`ZipInfo(date_time=time.localtime(time.time())[:6])` — **local time**; `ZipInfo(name)` alone
defaults to `(1980,1,1,0,0,0)`. `omniweave_core.out.opc.write_opc` is the only module permitted to
open a ZIP for writing, and the reproducibility gate runs three times under
`PYTHONHASHSEED ∈ {0,1,random}` from two temp dirs with different cwd and `TMPDIR`.

**8. Citations.** `data-ow-cite="d7#412"` — D2's only prompt-safe token — on any element whose
content came from the store. Three channels: **visible** (a rendered marker, suppressible, and
suppression is a receipt row), **embedded** (a provenance part inside the container), **ledger**
(`artifact_cite`, authoritative). A `.owcite.json` sidecar is written **always**, so a target that
cannot embed still has one. `read_back` recovers from the embedded channel only and never infers a
citation from visible text. `OW-T-102` proves verbatimness — `nfc(text) == block.text[a:b]` and
`block.quote == verbatim` — the author never asserts it. Honest limit: PowerPoint may discard an
unknown OPC part; the loss is detectable, reported by `ow out verify`, and the ledger is unaffected.

**9. `manual_required`** is a mandatory IL construct in every ConstructTable, a unit outcome, and a
gate status — not a disposition, because a disposition says what the compiler does with a construct
and `manual` says what a human must do about a region. Closed reason vocabulary. Observation is
separate from decision: the evidence artefact records only what is visibly present and explicitly no
realization choices, prompts, filenames or IL bindings. `--accept-manual` produces a **draft**:
placeholders carrying the reason, gate status unchanged, `delivery: "draft"` in the receipt, and
`read_back` of a draft emits `Diag(OW_MANUAL_REQUIRED)` forever after. There is no gate bypass.

**10. Round trip.** Seven laws, R1–R7 in the concrete shape, executable by `omniweave-conform`. The
one that matters is **R3, the second-round fixed point**: the first round is *not* required to be a
fixed point, because an author writes compatible-but-non-canonical input which the compiler
legitimately normalizes once; the second must be. That is the honest, achievable statement of
"lossless round trip" and the one an implementation can be held to. Loss is declared per construct
row (`round_trip ∈ {exact, normalized, lossy, dropped}`) and checked **in both directions**:
undeclared loss fails, and so does over-declaration, plus a semantic mutation of any `exact`
construct must move `il_digest_rt` or the declaration is a lie.

## Concrete shape

```
════════ A. LAYOUT ════════════════════════════════════════════════════════════════════════
packages/omniweave-core/src/omniweave_core/out/     STDLIB ONLY (G1/G9 intact). LAZY submodule:
├── finding.py    Severity · Provenance · Finding · FindingSet.fold()      `import omniweave_core`
├── constructs.py ConstructTable · Disposition · RoundTrip · load() · digest()  must NOT import it.
├── rules.py      Rule · RuleCtx · RuleSpec · RulePack · run_pack() · RuleTimings
├── carrier/      xml.py (xml.etree) · html.py (html.parser)  — STDLIB parsers, DOCTYPE banned
│                 CarrierDoc / CarrierNode / Splice / Insertion Protocols
├── report.py     OutReport · il_digest() · nsig() · schema "omniweave.out-report/1"
├── gate.py       GateStatus (10) · gate_status() -> (GateStatus, int)
├── plan.py       Plan · Unit · UnitOutcome (7) · classify_and_assert()
├── brief.py      Brief · parse_brief() · validate()  (rejects untagged non-baseline forbidden)
├── ledger.py     AssetLedger over D2 `asset` · freeze() · slot() · MAX_ASSET_BYTES
├── marker.py     OWC1 grammar · scan() · apply_reverse() · assert_clean()
├── manual.py     ManualReason (closed) · Evidence
├── receipt.py    Receipt · CheckValue
├── roundtrip.py  r1..r7 — executable predicates, imported by omniweave-conform
├── opc.py        write_opc() · part_digest()  ── THE ONLY ZIP-FOR-WRITE IN THE FRAMEWORK
└── job.py        JobDir layout · job.json writer/reader

packages/omniweave-target-pptx/src/omniweave_target_pptx/    IL owsvg/1 · carrier svg · pure Python
├── driver.toml         compile.pptx.native   [capability.compile]
├── constructs.toml     ~180 rows
├── rules/              one rule per file, one test per file  (NOT a 9368-line class)
├── measure.py          uharfbuzz shaping — IMPORTED BY BOTH rules/ AND lower/   (the whole point)
├── lower/              drawingml/ · charts.py · boolean.py · media.py · pack.py
└── back/  driver.toml  parse.pptx.native   +  reader.py (python-pptx -> DocSink)
packages/omniweave-target-deck/   IL owdeck/1  · carrier html · toolchain "deck"
packages/omniweave-target-docx/   IL owflow/1  · carrier html · pure Python      (12th distribution)
packages/omniweave-target-video/  IL owmotion/1 · card ships with implemented=false at release 1
packages/omniweave-conform/.../suites/target/  the 12th suite + compile.text.owtext REFERENCE TARGET
toolchains/_shared/target-runtime.ts           framework-owned hello/ready/validate/compile loop
fixtures/out/{golden/<target>/, foreign/, expected/}

ENTRY POINTS  (reconciling D1 and D3; both stand)
  omniweave.drivers  "compile.pptx.native" = "omniweave_target_pptx"        # D3: DOTTED PACKAGE
                     "parse.pptx.native"   = "omniweave_target_pptx.back"
  omniweave.targets  "pptx"                = "omniweave_target_pptx"        # D1: ARTEFACT ALIAS
  omniweave.toml  [targets] enabled = ["pptx"]   -> an artefact-kind POLICY ALLOWLIST
                  [drivers] enabled = [...]      -> DriverIds.   BOTH gates apply.
```

```toml
════════ B. driver.toml — the ONE card. No new top-level table (D3 makes that a hard error). ═══
card_schema = 1
[driver]
id="compile.pptx.native"; port="compile/1"; version="0.1.0"; schema_version=1
entrypoint="omniweave_target_pptx.driver:PptxCompiler"; granularity="document"; deterministic=true
[capability]
formats=["application/vnd.openxmlformats-officedocument.presentationml.presentation"]
consumes=["il_bundle","asset"]; produces=["artifact","receipt"]

[capability.compile]
target            = "pptx"          # the omniweave.targets alias
unit              = "slide"         # slide | section | page | scene — the addressable output unit
carrier           = "svg"           # svg | html   (a core CarrierDoc, or target-supplied)
il                = "owsvg/1"
constructs        = "constructs.toml"          # package data; its sha256 is inside card_sha256
constructs_digest = "sha256:71c4…"             # kit-checked against load()
determinism       = ["part","byte"]            # SET, compared ⊇.  `part` is MANDATORY.
citations         = "embedded"                 # embedded | sidecar | none
provenance_part   = "customXml/omniweave-provenance.json"
assets            = ["image","bake","font","video","audio","ole"]
bake              = "unavailable"              # available | unavailable | toolchain:<name>
measure           = "uharfbuzz"                # none | <engine> — gates the overflow rules
runtime_rules     = false                      # true => the target gets a `validate` frame
toolchain         = ""                         # "" => pure Python
implemented       = true
max_units         = 2000
agent_doc_tokens_max = 6000                    # `ow out constructs pptx --format md`, CI-gated

[capability.compile.round_trip]
read_back = "parse.pptx.native"                # D3: "parse_back as a named parse/1 driver id"
project   = true                               # Doc -> IL is implemented
fidelity  = "passthrough"                      # none < text < structure < passthrough  (D2 ladder)
laws      = ["r1","r2","r3","r4","r5","r6","r7"]
kind_map  = "kind_map.toml"                    # D2 Kind <-> target primitive; R2's comparator
```

```toml
════════ C. constructs.toml — the IL contract as data. FOUR dispositions. ═══════════════════
schema="omniweave.out-constructs/1"; carrier="svg"; il="owsvg/1"; version=3
unknown_construct="forbidden"                  # FAIL CLOSED. Not configurable.
ignore=["svg:desc","svg:title","svg:metadata"]

[[construct]]                                  # native: the ONE canonical spelling
id="attr.fill"; selector="@fill"; disposition="native"; round_trip="exact"
canonical="uppercase #RRGGBB | none | url(#id)"; maps_to="lower.paint:solid_fill"
code="OW-T-410"; since="0.1.0"

[[construct]]                                  # normalize: ONE documented alias, ONE deterministic
id="attr.fill.lowercase-hex"; normalizes_to="attr.fill"; disposition="normalize"
normalizer="upper_hex"; round_trip="normalized"; code="OW-T-210"; severity="warning"
canonical="#RRGGBB with uppercase hex digits"  # WARNING, NEVER ERROR, NEVER GENERATED

[[construct]]                                  # bake: unexpressible, deterministic degradation
id="style.mix-blend-mode"; selector="@style|mix-blend-mode"; disposition="bake"
bake={renderer="raster", dpi=192, role="bake"}; round_trip="lossy"; code="OW-T-311"

[[construct]]                                  # forbidden, CONDITIONALLY — the hazard is the PAIR
id="attr.id"; selector="@id"; disposition="native"; forbidden_when="svg|style"
round_trip="exact"; maps_to="lower.ids:passthrough"; code="OW-T-402"
msg="id is REQUIRED inside <defs>; it is only hazardous paired with <style>"

[[construct]]
id="elem.script"; selector="svg|script"; disposition="forbidden"; round_trip="dropped"
code="OW-T-401"; msg="no DrawingML mapping; executable content in an authored artefact"

# MANDATORY IN EVERY ConstructTable — a target that cannot express these cannot be a target:
#   ow:cite   ow:manual   ow:unit   (and the data-ow-el attribute)
```

```python
════════ D. omniweave_core.out — the framework half ════════════════════════════════════════
class Severity(StrEnum):    ERROR="error"; WARNING="warning"; INFO="info"
class Provenance(StrEnum):  INTRODUCED="introduced"  # the generator authored it
                            INHERITED="inherited"    # byte-identical in the template it derives from
                            IMPORTED="imported"      # arrived through project() of a tolerant read_back
                            FRAMEWORK="framework"    # omniweave itself: a skipped check, a shortfall
class Disposition(StrEnum): NATIVE="native"; NORMALIZE="normalize"; BAKE="bake"; FORBIDDEN="forbidden"
class RoundTrip(StrEnum):   EXACT="exact"; NORMALIZED="normalized"; LOSSY="lossy"; DROPPED="dropped"
class Determinism(StrEnum): PART="part"; BYTE="byte"; FRAME="frame"; RENDER="render"
class UnitOutcome(StrEnum): NATIVE="native"; BAKED="baked"; PASSTHROUGH="passthrough"
                            CLONED_PASSTHROUGH="cloned_passthrough"; PATCHED="patched"
                            REBUILT="rebuilt"; MANUAL_REQUIRED="manual_required"
class GateStatus(StrEnum):  NOT_PROVIDED="not-provided"; UNREADABLE="unreadable"
                            UNSUPPORTED_SCHEMA="unsupported-schema"; NON_FINAL="non-final"
                            UNVERIFIED="unverified"; FAILED="failed"; STALE="stale"
                            RESTRICTED="restricted"; MANUAL_REQUIRED="manual-required"; PASSED="passed"
class ManualReason(StrEnum):                    # CLOSED. ppt-master's realization table, as data.
    UNVERIFIABLE_WORDING="unverifiable_wording"; UNVERIFIABLE_IDENTITY="unverifiable_identity"
    UNVERIFIABLE_DATA="unverifiable_data";       INSUFFICIENT_SOURCE="insufficient_source"
    UNREPRESENTABLE="unrepresentable";           LICENCE_BARRED="licence_barred"
    MEASUREMENT_FAILED="measurement_failed"

@dataclass(frozen=True, slots=True)
class Finding:
    code: str                 # OW-T-nnn, in codes.toml (D1 G13 append-only)
    severity: Severity        # decides whether it BLOCKS
    provenance: Provenance    # decides who OWNS it and which fix command prints
    rule: str                 # "pptx.style.blend@1"
    unit: str                 # "u03"
    msg: str
    fix: str                  # the exact command. NEVER EMPTY — __post_init__ raises.
    at: str | None = None     # "il/u03.svg:41:9"
    el: str | None = None     # data-ow-el address
    construct: str | None = None
    canonical: str | None = None    # REQUIRED iff the construct's disposition is NORMALIZE
    count: int = 1                  # FOLDED occurrences: 200 hex colours => ONE finding
    examples: tuple[str, ...] = ()  # <= 3, asserted  (ppt-master `remember_example`)

class RuleCtx(Protocol):
    doc: "CarrierDoc"; unit: "Unit"; plan: "Plan"; constructs: "ConstructTable"; brief: "Brief"
    cites: "CiteResolver"          # by_cite() ONLY. No writes, no store handle.
    limits: Mapping[str, int]
    def measure(self, n: "CarrierNode") -> "Box | None": ...  # None => RECORDED SKIP, never a pass
Rule = Callable[[RuleCtx], Iterable[Finding]]

@dataclass(frozen=True, slots=True)
class RuleSpec:
    id: str; order: int                # phase. order 0 IS the carrier parse and SHORT-CIRCUITS.
    scope: Literal["document","unit","node"]
    codes: frozenset[str]              # every code this rule MAY emit — the meta-gate checks both ways
    needs: frozenset[str] = frozenset()# {"measure","cites","assets"} — unmet => FRAMEWORK info finding
    fn: Rule = ...

@dataclass(frozen=True, slots=True)
class RuleTimings:                     # hyperframes packages/lint/src/types.ts:20-27
    total_ms: int; group_ms: Mapping[str, int]; slowest_rule: str; slowest_rule_ms: int

class CarrierNode(Protocol):
    kind: str
    def attr(self, name: str) -> str | None: ...
    def text(self) -> str: ...
    def children(self) -> Iterator["CarrierNode"]: ...
    def src(self) -> tuple[int, int]: ...
    def el(self) -> str | None: ...            # data-ow-el

class CarrierDoc(Protocol):
    comment_open: str; comment_close: str
    def root(self) -> CarrierNode: ...
    def select(self, selector: str) -> Iterator[CarrierNode]: ...
    def place_marker(self, n: CarrierNode) -> "Insertion": ...  # THE only per-carrier feedback hook
    def source(self) -> str: ...
    def splice(self, edits: Sequence["Splice"]) -> "str | ParseError": ...
    # applySplices: sort DESC by offset, apply, REPARSE, ALL-OR-NOTHING (open-slide edit-ops.ts).
    # Two parse functions one line apart: error-recovering for READ, strict for anything that WRITES.
```

```python
════════ E. omniweave.ports.compile_v1 — the whole third-party surface ═════════════════════
class CompileV1(Protocol):
    PORT: ClassVar[str] = "compile/1"
    @classmethod
    def probe(cls, env: "ProbeEnv") -> "ProbeVerdict": ...
    def __init__(self, **config: Scalar) -> None: ...   # STATIC CONFIG ONLY (D3). Loads nothing.
    def carrier(self, path: str, text: str) -> CarrierDoc: ...
    def rules(self) -> Mapping[str, Sequence[RuleSpec]]: ...     # group -> the RulePack
    def measure(self) -> "TextMeasure | None": ...               # SHARED with rules/. One estimator.
    def lower(self, plan: "Plan", il: "ILBundle", ledger: "AssetLedger",
              io: DriverIO) -> DriverResult: ...  # writes into io.tmpdir. NEVER output_root (D3-7).
    def postflight(self, artifact: str, plan: "Plan") -> "Receipt": ...
    def project(self, doc: "Doc", io: DriverIO) -> "ILBundle": ...   # Doc -> IL. Optional; carded.
# There is NO validate(). The FRAMEWORK validates from rules() + constructs.toml.
# A Toolchain target runs `lower` through io.service("toolchain:<name>") -> ToolchainHandle,
# whose .run(job_dir, timeout_s) IS omniweave_core.toolchain.run EXECUTED IN THE HOST PROCESS.
# D1 gate G8 (one subprocess site) and D3's non-extensible DriverIO both hold. Namespace reserved.
```

```sql
════════ F. DDL — five tables over D2's .owstore. No second representation of anything. ════
CREATE TABLE artifact (
  artifact_id   INTEGER PRIMARY KEY,
  slug          TEXT NOT NULL, gen INTEGER NOT NULL,     -- OUT edits ALWAYS write a new gen
  parent_gen    INTEGER, origin TEXT NOT NULL
                CHECK(origin IN ('authored','feedback','read_back','rebase')),
  target        TEXT NOT NULL, compile_driver TEXT NOT NULL, media_type TEXT NOT NULL,
  path          TEXT NOT NULL, sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL,
  part_digest   BLOB NOT NULL,                            -- the `part` determinism digest
  il_digest     BLOB NOT NULL, il_store_ref TEXT NOT NULL,-- cas:// THE RETAINED IL BUNDLE
  constructs_digest BLOB NOT NULL, ledger_digest BLOB NOT NULL, brief_digest BLOB,
  card_sha256   BLOB NOT NULL, toolchain_digest BLOB,
  determinism   TEXT NOT NULL,                            -- JSON set, as compiled
  gate_status   TEXT NOT NULL,
  delivery      TEXT NOT NULL CHECK(delivery IN ('release','draft')),
  report_sha256 BLOB NOT NULL, receipt_sha256 BLOB NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,            -- D3, set by the RUNNER
  producer_id   INTEGER NOT NULL REFERENCES producer(producer_id),   -- D2's shared type
  degradations  TEXT NOT NULL DEFAULT '[]',               -- D4's channel, verbatim
  read_back_doc_ord INTEGER REFERENCES doc(doc_ord),      -- THE LOOP IS A FOREIGN KEY
  sealed_at_ns  INTEGER NOT NULL,
  UNIQUE (slug, gen)
);
-- Identical inputs => identical artefact. A recompile is a LOOKUP, not a build.
CREATE UNIQUE INDEX artifact_pure ON artifact(
  target, il_digest, constructs_digest, ledger_digest, card_sha256, IFNULL(toolchain_digest, x''));

CREATE TABLE artifact_unit (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit TEXT NOT NULL, ord INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('native','baked','passthrough','cloned_passthrough',
                                          'patched','rebuilt','manual_required')),
  il_path TEXT NOT NULL, il_sha256 BLOB NOT NULL,        -- per-unit retained IL
  nsig TEXT NOT NULL,                                    -- canonicalized-subtree content anchor
  reason TEXT,
  CHECK (outcome NOT IN ('manual_required','baked') OR reason IS NOT NULL),
  PRIMARY KEY (artifact_id, unit)
) WITHOUT ROWID;

CREATE TABLE artifact_asset (           -- the LEDGER JOIN. D2's `asset` is unchanged and is the SSOT.
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id),
  slot TEXT NOT NULL,                   -- 'asset-slot:<sha256>' exactly as it appears in the IL
  role TEXT NOT NULL,                   -- image|bake|font|video|audio|ole|thumbnail
  units TEXT NOT NULL,                  -- JSON array  (ppt-master `occurrences[]`)
  ratio_variants TEXT NOT NULL DEFAULT '[]',  -- two ratios => the deck is STRETCHING it
  PRIMARY KEY (artifact_id, asset_id, slot, role)
) WITHOUT ROWID;

CREATE TABLE artifact_cite (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit TEXT NOT NULL, el TEXT NOT NULL,
  cite TEXT NOT NULL,                                    -- D2's 'd7#412'
  block_id INTEGER REFERENCES block(block_id),           -- NULL => unresolved at build time
  doc_gen INTEGER NOT NULL,                              -- PINNED: a re-parse cannot re-point a ship
  kind TEXT NOT NULL CHECK(kind IN ('quote','paraphrase','derived','data')),
  span_a INTEGER, span_b INTEGER,
  verbatim INTEGER NOT NULL DEFAULT 0,                   -- PROVED by OW-T-102, never claimed
  PRIMARY KEY (artifact_id, unit, el, cite)
) WITHOUT ROWID;
CREATE INDEX artifact_cite_block ON artifact_cite(block_id);
-- "which decks quote page 14 of this contract?" — one indexed query. No repo in the collection can.

CREATE TABLE artifact_el (              -- written by the HOST from read_back's x.ow.el values
  artifact_id INTEGER NOT NULL, unit TEXT NOT NULL, el TEXT NOT NULL,
  block_id INTEGER NOT NULL REFERENCES block(block_id),
  PRIMARY KEY (artifact_id, el)
) WITHOUT ROWID;

-- D8 defines EXACTLY TWO reserved keys in D2's `x` bag, and `ow` is the ONLY reserved vendor:
--   x.ow.el    the IL element address a read_back Block came from   -> indexed into artifact_el
--   x.ow.cite  the JSON array of cite tokens on that element        -> indexed into artifact_cite
```

```
════════ G. DIGESTS AND DETERMINISM ═══════════════════════════════════════════════════════
il_digest  = sha256 over, for each IL file SORTED BY BASENAME: name ‖ 0x00 ‖ hex(sha256(bytes)) ‖ 0x0A
             An unreadable file contributes the literal `unreadable` AND an error row — it never
             silently drops out.        (ppt-master checker.py:9335-9368, verbatim framing)
nsig(el)   = hex(sha256(canonical_subtree(el)))[:8]   -- the CONTENT ANCHOR.
             SIX normalizations before hashing (authoring_roundtrip.py:979-1069):
               1 clone-local id prefixes stripped        4 single-child group filters lowered
               2 asset refs -> asset-slot:<sha256>       5 attribute-free one-child <g> collapsed
               3 an edited asset folded in as :edited:   6 the data-ow-el attribute itself ignored
             AND: a subtree referencing a CHANGED definition id is CHANGED even though its own
             bytes are identical. Shared-definition dependency tracking is MANDATORY.
il_digest_rt = il_digest over canonical_subtree with every payload key of a construct whose
             round_trip != EXACT elided. The exclusion set is DERIVED FROM THE TABLE, never tuned.

DETERMINISM CLASSES — declared as a SET, compared ⊇
  part   member-name set and each member's PAYLOAD BYTES identical. PORTABLE across any environment
         satisfying the pinned major deps.  ── THE FLOOR. Every enabled target declares it.
  byte   container bytes identical. Asserted in CI under ONE pinned (python, zlib, compresslevel,
         dep-set); RECORDED in the receipt; NEVER PROMISED TO A USER (a zlib bump falsifies it).
  frame  12 deterministically sampled decoded frames + full PCM identical, pinned (ffmpeg,codec,threads)
  render sampled DOM paint tree and measured layout identical at sampled times, pinned toolchain digest

# omniweave_core/out/opc.py — THE ONLY module permitted to open a ZIP for writing (semgrep, O15)
CANONICAL_DATE = (1980, 1, 1, 0, 0, 0)
def write_opc(members, order, *, compresslevel=6) -> bytes: ...
def part_digest(members) -> bytes: ...  # sha256 over  name \0 sha256(payload) \n , sorted by name
# VERIFIED against CPython 3.11.9:
#   ZipInfo.from_file -> mtime = time.localtime(st.st_mtime); date_time = mtime[0:6]  NON-DETERMINISTIC
#   ZipFile.writestr  -> ZipInfo(date_time=time.localtime(time.time())[:6])           LOCAL TIME
#   ZipInfo(name)     -> date_time == (1980,1,1,0,0,0)                                the safe ctor
# Also mandatory: members in canonical order ([Content_Types].xml, _rels/.rels, then sorted by
# partname); dcterms:created == dcterms:modified == job.determinism.clock_ns; cp:revision="1";
# cp:lastModifiedBy=""; NO w:rsid*, NO p14:creationId; shape ids from a per-unit counter seeded at 2;
# EMU INTEGERS ONLY — no repr(float) reaches the XML; every attribute map sorted before serialization.
# GATE: 3 runs x PYTHONHASHSEED in {0,1,random}, two temp dirs, different cwd and TMPDIR,
#       SOURCE_DATE_EPOCH=0. The cross-platform matrix asserts `part` ONLY.
```

```jsonc
════════ H. JOB DIRECTORY (D1's envelope; D8 owns the contents) ════════════════════════════
<cache_root>/jobs/<run_id>/<artifact_slug>@<gen>/
├── job.json      schema/job-v1.json        ├── assets/index.json + cas/ab/cd/<sha256>
├── brief.md      the frozen brief          ├── validation/{early,final}.json
├── il/  il.toml u001.svg …  CANONICAL TEXT └── out/ <artefact> · receipt.json · <slug>.owcite.json
└── cites.json    the flattened sidecar          (+ il/ and project.json on a `project` run)

{"schema":"omniweave.compile-job/1",
 "artifact":{"slug":"q3-review","target":"pptx","gen":4,"unit":"slide"},
 "il":{"path":"il/","carrier":"svg","il":"owsvg/1","digest":"sha256:9c2f…","units":40},
 "constructs_digest":"sha256:71c4…","ledger":"assets/index.json","cites":"cites.json",
 "gate":{"status":"passed","report":"validation/final.json","introduced_warnings":3},
 "policy":{"restriction_bits_allowed":0,"visible_citations":true,"bake":["u07/e3"]},
 "determinism":{"seed":0,"clock_ns":0,"tz":"UTC","source_date_epoch":0,"classes":["part","byte"]},
 "limits":{"wall_ms":600000,"rss_bytes":4294967296,"out_bytes":2147483648,"max_units":2000},
 "out":"out/"}

// omniweave-target/1 — D1's protocol, extended by exactly TWO fields and ONE frame:
{"t":"ready", …, "constructs_digest":"sha256:71c4…","determinism":["render","part"]}
{"t":"project","id":3,"doc":"in/doc.owdoc","out":"out/il/"}   // Doc -> IL, toolchain targets only
// `constructs_digest` on `ready` is the ONLY defence against a pnpm bump changing the toolchain's
// construct set with no Python-side signal — D1's own named two-lockfile risk.

// cites.json — how a store fact reaches a renderer that has NO store access
[{"el":"u03/e17","cite":"d7#412","doc_gen":2,"kind":"quote","verbatim":true,
  "text":"Revenue grew 14% year over year.",
  "source":{"uri":"file:///corpus/fy24-10k.pdf","page":13,
            "quad":[102000,318000,470000,318000,470000,335000,102000,335000]}}]

// assets/index.json — a PROJECTION of D2's `asset` rows. The store is authoritative; this is not.
[{"slot":"asset-slot:3f9c…","sha256":"3f9c…","media_type":"image/png","w":1600,"h":900,
  "file":"assets/cas/3f/9c/3f9c….png","spdx":"CC-BY-4.0","licence_url":"…","source_url":"…",
  "attribution":"Photo by A. Author","restriction_bits":256,"producer":"gen.image.sdxl@a1b2c3"}]
```

```jsonc
════════ I. REPORT AND RECEIPT ═════════════════════════════════════════════════════════════
// validation/final.json — "omniweave.out-report/1"
{"schema":"omniweave.out-report/1","target":"pptx","il":"owsvg/1","stage":"final",
 "constructs_digest":"sha256:71c4…","brief_digest":"sha256:0aa1…",
 "il_digest":{"algorithm":"sha256","digest":"…","file_count":40,
              "files":[{"file":"u001.svg","sha256":"…"},
                       {"file":"u007.svg","sha256":null,"error":"source bytes unavailable"}]},
 "summary":{"units":40,"passed":37,"warnings":3,"errors":0},       // UNITS, one bucket each
 "issue_types":{"font":2,"capacity":1},                            // FINDINGS. Two denominators.
 "categories":{                                    // severity x provenance CROSS-TAB
   "introduced":{"error":0,"warning":3,"info":0,"findings":[/*Finding*/]},
   "inherited": {"error":0,"warning":40,"info":0,"findings":[]},   // template debt, OUT of the score
   "imported":  {"error":0,"warning":4,"info":0,"summary":{"by_code":{"OW-T-210":4}}},
   "framework": {"error":0,"warning":0,"info":1,"findings":[]}},
 "blocking":0,                                    // = count(severity==error) OVER ALL PROVENANCES
 "skipped_checks":[{"rule":"pptx.text.capacity","reason":"measure() unavailable: uharfbuzz absent",
                    "fix":"pip install omniweave-target-pptx"}],   // VISIBLE. Never a silent pass.
 "units":[{"unit":"u03","outcome":"manual_required","reason":"unverifiable_identity: brand mark 0.61"}],
 "cites":{"declared":41,"resolved":41,"verified_verbatim":38,"unresolved":[],"restricted":[]},
 "assets":{"slots":9,"frozen":9,"external_refs":[],"restricted":[]},
 "timings":{"total_ms":412,"group_ms":{"style":88,"text":201},
            "slowest_rule":"text#3","slowest_rule_ms":140},
 "degradations":[]}

// out/receipt.json — "omniweave.out-receipt/1".  EXIT 0 IFF THIS WAS WRITTEN (D1).
{"schema":"omniweave.out-receipt/1","status":"passed-with-warnings","delivery":"release",
 "target":"pptx","driver":"compile.pptx.native@omniweave-target-pptx","driver_schema_v":1,
 "output":{"path":"out/q3.pptx","bytes":1284211,"sha256":"…","part_digest":"…"},
 "inputs":{"il_digest":"…","constructs_digest":"…","ledger_digest":"…","card_sha256":"…",
           "brief_digest":"…","toolchain_digest":null},
 "gate":{"status":"passed","stage":"final","il_digest_match":"passed","introduced_warnings":3},
 "units":{"native":37,"baked":0,"passthrough":2,"cloned_passthrough":0,"patched":0,
          "rebuilt":0,"manual_required":1,"total":40,"sum_asserted":true},
 "determinism":{"classes":["part","byte"],"byte_asserted_in":{"python":"3.11.9","zlib":"1.3.1",
   "compresslevel":6,"deps":{"python-pptx":"1.0.2","uharfbuzz":"0.50.4"},"pythonhashseed_runs":3}},
 "checks":{"container_integrity":"passed","unit_count":"passed",
           "internal_relationships":"enforced-at-build",  // FIRST-CLASS VALUE. Not omitted, not faked.
           "construct_closure":"enforced-at-build","quality_gate":"passed","asset_ledger":"passed",
           "citation_embedding":"passed","text_capacity":"warning","repro_double_compile":"not-run"},
 "resources":{                                   // PORTABILITY — a SECOND AXIS, not validity
   "fonts":{"stacks":["Inter, sans-serif"],"generic_only_stacks":[],"unsafe_exported_faces":[],
            "embedded":[{"face":"Inter-Regular","source_sha256":"…","subset_sha256":"…","glyphs":412}],
            "resolution":"embedded"},
   "external_images":[],"unresolved_tokens":[]},
 "citations":{"els":41,"visible":41,"embedded":41,"ledger":41,"unresolved":[]},
 "restrictions":{"bits":0,"items":[]},"licence_notices":[],"bake":[],"manual_required":[],
 "degradations":[{"kind":"driver_unavailable","message":"bake unavailable: no licence-clean
   rasterizer. Install the deck toolchain (`omniweave targets install deck`) or supply the raster
   (`ow out assets add <file> --slot <name>`)."}],
 "report_sha256":"…"}

[OUT] pptx status=passed-with-warnings gate=passed units=40 (native 37 · passthrough 2 · manual 1)
      det=part,byte cites=41/41 assets=9 warn=3  ->  out/q3.pptx
```

```
════════ J. THE ROUND-TRIP LAWS — executable in omniweave_core.out.roundtrip ═══════════════
compile : ILBundle -> Artefact         read_back : Artefact -> Doc  (a parse/1 Driver, DocSink)
project : Doc -> ILBundle              ≡_det : equality at the target's declared determinism classes

R1  RETAINED-IL IDENTITY            (mandatory, EVERY target)
    For every artefact A omniweave built with retained bundle I:  compile(I) ≡_det A.
    `ow out verify <artefact>` is the user-facing check. This is what makes editing an
    omniweave-built artefact PASSTHROUGH rather than reconstruction.
R2  ADDRESS SURVIVAL                (mandatory when fidelity != none)
    For every element e in I carrying data-ow-el: read_back(compile(I)) contains EXACTLY ONE Block b
    with b.x["x.ow.el"] == e.el, b.kind == kind_map[e.construct], nfc(b.text) == nfc(visible_text(e)),
    b.x["x.ow.cite"] == e.cites.  Missing / duplicated / kind-mismatched / text-mismatched = FAILURE.
R3  SECOND-ROUND FIXED POINT        (mandatory when fidelity in {structure, passthrough})
    D1 = read_back(compile(I));  D2 = read_back(compile(project(D1)))
    => the multiset of content_digest over Layer.BODY blocks in (page, ord) order is EQUAL.
    The FIRST round is NOT required to be a fixed point: an author writes compatible-but-non-canonical
    input and the compiler legitimately normalizes it ONCE. The second must be.
R4  EDIT LOCALITY                   (mandatory when fidelity == passthrough)
    (a) read_back then compile with ZERO edits => 100% of units are passthrough|cloned_passthrough,
        each copied part's sha256 asserted equal to the source part's.
    (b) edits confined to element set E => every unit whose source-refs AND definition dependencies
        are disjoint from E is passthrough|patched, NEVER rebuilt.
R5  DECLARED LOSS, BOTH DIRECTIONS
    observed_loss ⊆ declared_loss  (nothing lost that is not declared)
  ∧ every row with round_trip in {lossy,dropped} has a fixture where the loss OCCURS and emits
    Diag(OW_ROUNDTRIP_LOST,{construct})                    (nothing declared that does not happen)
  ∧ every row with round_trip == exact is EXERCISED by the golden corpus AND a SEMANTIC MUTATION of
    its payload MOVES il_digest_rt.   <- without this, `loses = ["*"]` is a green report.
R6  NOTHING SILENTLY DROPPED
    Every relationship / media part / opaque payload in A not representable in the IL is either
    (a) an opaque passthrough asset with a ledger row, or (b) a BLOCKING refusal naming the exact
    part paths and BOTH exits. There is no third branch. Unmapped relationships are AT-RISK whenever
    visuals changed at all — fail closed on the unknown.  (ppt-master cli.py:2890-2948)
R7  TOTAL CLASSIFICATION
    Every output unit lands in exactly ONE UnitOutcome and sum == unit_count. Unclassifiable = FATAL,
    artefact not written, counts printed.                   (ppt-master cli.py:2951-2990)

MUST SURVIVE R2/R3: data-ow-el · block kind under kind_map · visible text under NFC · reading order ·
  table cell topology (r,c,row_span,col_span) · asset identity by sha256 · cite tokens · notes and
  footnotes as a distinct Layer · restriction_bits · and, for passthrough/patched units, the
  ORIGINAL CONTAINER BYTES.
MAY BE LOST, and MUST be declared as a construct row with round_trip in {lossy,dropped}:
  geometry below the target's grid quantum · marks outside the declared set · score/score_kind ·
  raw_kind · layer=hidden where the target has none · animation timing curves (trigger+preset survive) ·
  autofit font scaling (recomputed) · theme-relative colours resolved to literal · transition sound.
A SIXTH KIND OF LOSS IS A BUG, and R5 makes it a build failure.
```

```
════════ K. THE FIRST THREE TARGETS (+ what ships beside them) ═════════════════════════════
                pptx                    deck                     docx
distribution    omniweave-target-pptx   omniweave-target-deck    omniweave-target-docx  (12th)
execution       PURE PYTHON, no Node    Toolchain (node >=20)    PURE PYTHON
carrier / IL    svg / owsvg/1           html / owdeck/1          html / owflow/1
unit            slide                   page                     section
deps            python-pptx XlsxWriter  1 MB manifest +          python-docx lxml   ~20 MB
                skia-pathops uharfbuzz  $OMNIWEAVE_HOME bundle   NOT in [recommended]
                Pillow          <=60 MB
constructs v1   ~180 rows               ~90 rows                 ~70 rows
runtime rules   none                    YES (getBoundingClientRect capacity, off-canvas measure)
determinism     ["part","byte"]         ["render","part"]        ["part","byte"]
citations       embedded (customXml)    embedded (data-ow-cite)  embedded (customXml)
read_back       parse.pptx.native       parse.deck.native        parse.docx.native
fidelity        PASSTHROUGH             structure                patched
laws            R1-R7                   R1,R2,R3,R5,R6,R7        R1,R2,R3,R5,R6,R7
bake            unavailable -> toolchain:deck once deck installed  unavailable
feedback        IL markers + PowerPoint comments import          IL markers + w:comment import
why             the ONLY working        the ONLY proof a         the honest test that the
                parse_back in the       Toolchain target is      abstraction is not ONE
                collection; zero Node   not second-class;        IMPLEMENTATION WEARING AN
                                        open-slide has NO        INTERFACE — a FLOW carrier, no
                                        semantic validator       canvas, no z-order, no bake

ALSO SHIPPING AT RELEASE 1
  omniweave-target-video   card present, `implemented = false`, `ow out targets` prints the reason.
                           mine-out.md PART 3 (hyperframes) WAS NEVER WRITTEN; a construct table
                           designed from an index page is exactly the speculative generality this
                           ruling refuses. Target 4: carrier html/owmotion/1, determinism ["frame"],
                           citations "sidecar", R3 REFUSED (a lossy encode is not idempotent),
                           ffmpeg="system", codec vp9, REFUSE RATHER THAN SUBSTITUTE (D1).
  compile.text.owtext      the REFERENCE TARGET, shipped inside omniweave-conform. ~10 constructs,
                           determinism ["byte"], citations "sidecar", fidelity "none", bake
                           "unavailable". Its job is to EXERCISE THE REFUSAL BRANCHES of the contract
                           in CI without Chromium. `ow out scaffold` generates its shape.
```

```
════════ L. INVARIANTS AND HOW EACH IS ENFORCED ════════════════════════════════════════════
O1  Every construct the compiler can emit has a row; every native row's maps_to resolves.
      Two-way CI gate: import lower/, diff its public symbol set against constructs.toml.
      OW-T-001 CONSTRUCT_UNMAPPED · OW-T-002 CONSTRUCT_UNDECLARED. BOTH directions.
O2  Exactly ONE implementation of "what does this construct mean".
      rules/ and lower/ are modules of ONE distribution; CompileV1 has NO validate(); measure.py is
      imported by both; semgrep bans a second carrier parser under rules/.
O3  A check that could not run is VISIBLE and the gate is `unverified`, never `passed`.
      report.skipped_checks[] required non-null; conform removes uharfbuzz and asserts both.
O4  The gate binds to BYTES. il_digest recomputed by the SAME function at compile; mismatch => STALE.
      The toolchain's TS recomputation is spec'd in schema/il-digest-v1.md + a parity fixture.
O5  EXACTLY ONE GateStatus permits a release. A test asserts the other nine are refused with a
      distinct message AND a fix command. There is no --force and no --no-gate.
O6  Every Finding carries a provenance class and a NON-EMPTY fix. __post_init__ raises otherwise.
      ONE function feeds console and JSON, so they cannot disagree.
O7  Findings FOLD. 200 occurrences => one finding, count=200, <=3 examples. Asserted.
O8  Every unit in exactly one outcome; sum asserted; unclassifiable is FATAL (OW-T-005).
O9  No http(s)://, file:, data: URI or filesystem path survives into the IL. `asset-slot:<sha256>`
      is the ONLY asset syntax (ppt-master's internal token, promoted to the wire form).
      OW-T-112; semgrep bans open()/Path() on an IL-derived string inside lower/.
O10 Every asset frozen, content-addressed, licence-bearing before compile. AssetLedger.freeze() is
      the only writer; asset.store_ref NOT NULL; MAX_ASSET_BYTES = 268435456 with BOTH a
      content-length pre-check and a streaming abort (hyperframes freeze.mjs). A compile that must
      fetch REFUSES with Degradation(kind="grant_missing") naming the site Grant and its dpa_ref.
O11 No artefact contains a restricted item without policy. Gate RESTRICTED, naming the offending
      cites and asset ids. D3-17; one SQL aggregate at plan AND at compile.
O12 compile is a pure function of six digests (il, constructs, ledger, brief, card, toolchain).
      artifact_pure UNIQUE index; a recompile of identical inputs is a LOOKUP.
O13 A determinism claim is PROVED. `part` is the floor; `byte` is asserted only under a pinned
      resolution and is NEVER promised to a user. 3 x PYTHONHASHSEED, two temp dirs.
O14 No compiler reads a clock, cwd, env or RNG. D1 gate G8 extended to packages/omniweave-target-*,
      plus random/secrets/uuid4/datetime.now; the determinism harness monkeypatches them to raise.
O15 Only omniweave_core.out.opc opens a ZIP for writing. semgrep on zipfile.ZipFile(...,'w'/'a'/'x')
      and shutil.make_archive.
O16 An unresolved feedback marker never reaches a release artefact. OW-T-141; marker.assert_clean()
      runs inside compile, AFTER the gate, BEFORE lower().
O17 A feedback edit is TRANSACTIONAL: collect -> apply back-to-front -> REPARSE -> all-or-nothing.
      A 10k random-op-batch fuzz asserts the file is always parseable or unchanged.
O18 An ambiguous edit address is REFUSED, never guessed. Two-factor: el proposes, nsig disposes,
      uniqueness arbitrates; multiple text candidates with no prev => OW-T-151 refusal.
O19 Marker PRESENCE IS THE STATE. Base64url payload, position-derived line, corrupt payload skipped
      not fatal, reverse-order application, SKIP IS LEGAL (leave the marker, report it). Present
      after a claimed application is a failure signal. There is NO side table.
O20 The validator NEVER rewrites the IL. semgrep bans a write under il/ from rules/. `ow out stamp`
      and `ow out normalize` are separate commands with their own exit codes. THERE IS NO --fix.
O21 data-ow-el is minted once by `ow out stamp` and REFUSES on a duplicate (OW-T-405). Renumbering
      would silently invalidate every existing marker and citation.
O22 read_back NEVER invents provenance. Method.ROUNDTRIP always; Quote.RECONSTRUCTED unless the text
      was read from the artefact; Trust.INFERRED wherever kind_map is many-to-one. D2's ~120-test
      driver testkit runs against it UNCHANGED.
O23 A target cannot skip its own gate. lower() receives an already-gated Plan and has no access to
      the report; a conform test calls lower() behind a failing report and asserts the host never
      reaches it.
O24 OUT edits ALWAYS write a new gen; a sealed generation is never patched. artifact.sealed_at_ns
      NOT NULL + a BEFORE UPDATE/DELETE trigger. (Settles D2 open question #2. ord_path stays rejected.)
O25 A bake whose subtree contains a verbatim citation REFUSES (OW-T-215) — rasterizing destroys the
      text the citation claims to quote.
O26 The agent-facing IL reference is GENERATED from constructs.toml and byte-diff gated
      (`ow out constructs <t> --format md --check`, D1 gate G6 shape) under agent_doc_tokens_max.
O27 omniweave_core.out imports NO third party and NO carrier parser at package import; carriers are
      stdlib (xml.etree / html.parser) and lazily imported. IL input containing <!DOCTYPE, <!ENTITY
      or a processing instruction is refused BEFORE parsing (OW-T-401) — that ban is what makes a
      stdlib XML parser safe on a closed authoring surface.
O28 The foreign corpus is a standing obligation with a named owner. fixtures/out/foreign/ holds
      artefacts WE DID NOT AUTHOR; R2 and R5 run against them (not R3, which needs an IL). Without
      it the round-trip laws test our reader against our writer and a jointly-wrong pair passes forever.

════════ M. CLI AND CODE RANGES ════════════════════════════════════════════════════════════
ow out targets                       installed · enabled · carrier · constructs · determinism ·
                                     fidelity · toolchain state · bake availability
ow out explain <target> | ow explain OW-T-311
ow out constructs <target> [--format md|json] [--check] [--diff <tag>]
ow out scaffold <name> --carrier svg|html         a GREEN, HONEST, USELESS target in one command
ow out brief [--interactive]         writes it; every other verb opens it READ-ONLY
ow out project <scope> --target pptx -o il/       STORE -> IL  (authoring projection)
ow out stamp ./il --target pptx                   mint data-ow-el; REFUSE on duplicates
ow out assets freeze ./il | add <file> --slot <n> --spdx X --source-url U
ow out check ./il --target pptx [--early] [--json]   -> validation/{early,final}.json
ow out compile ./il --target pptx -o q3.pptx [--accept-manual] [--bake <el>] [--repro-check]
ow out verify <artefact>             recompute part_digest from the RETAINED IL: PASSED | DRIFTED
ow out back <artefact> [--into <store>]           ARTEFACT -> STORE (new gen; read_back)
ow out diff ./il --against <artefact>             fidelity tiers, dry run, spends nothing
ow out comments list|apply ./il      reverse-order, transactional, skip-is-legal
ow out cite trace <artefact> <el>    el -> cite -> block_id -> OriginSpan -> quad on page 13
ow out snapshot <target> [--bless]

OW-T-0nn framework/contract  OW-T-1nn cites & assets  OW-T-2nn normalize  OW-T-3nn bake/capability
OW-T-4nn forbidden/carrier   OW-T-5nn round-trip & refusals   OW-T-6nn feedback
OW-T-7nn brief & drift       OW-T-9nn manual_required & limits
Every message ends with the exact command that clears it. codes.toml is append-only (D1 G13).
```

## Rationale

The three proposals agreed on far more than they disagreed on — a construct table as the contract,
one rule per file, ppt-master's four tiers with `bake` as the tier everyone else misses, the
provenance classes, the byte-bound gate, the two-gate cadence, the folded finding, the
asset-slot token, presence-is-state feedback, the transactional splice, no auto-fix, the four
fidelity tiers with an asserted sum, and `read_back` as a `parse/1` Driver. Two questions were
genuinely contested and one nobody answered.

**Where does the IL live?** The systems architect put it in the `.owstore` as `il_node` and made the
text a projection; the other two left it as files. I rule for files, and the deciding evidence is
that the systems proposal's justification does not survive `grep`: ppt-master's round-trip already
solved the stale-anchor problem with a **stamped attribute** (`SOURCE_REF_ATTRIBUTE =
"data-pptx-source-ref"`, `extract_svg_assets.py:81`), keying `source_refs` on that id and using
`source_path: tuple[int,...]` only to resolve it. An id in the file is a durable anchor that
survives file edits *because* it is in the file. Strip that premise and `il_node` is nine tables and
a parallel identity system reproducing what the text already carries — the second-representation
pattern D2 forbade for L4 — plus a `parse_il(emit_il(n)) == n` property pointing the wrong way:
making the table the pivot means the agent's authored file is rewritten on every validate, which
contradicts the "the checker never rewrites source SVG" rule the same proposal adopts elsewhere.

**But nobody answered how an edit loop actually closes without reconstruction**, and that is the
synthesis. ppt-master does not reconstruct authoring SVG from a PPTX; it keeps
`flat_source_path` / `layered_source_path` backing SVGs and regenerates the comparison baseline from
them. So: **the IL bundle is retained, content-addressed, in CAS** (`artifact.il_store_ref`,
`artifact_unit.il_sha256`). Editing an omniweave-built artefact fetches the retained IL and is
`passthrough`; `project(Doc) -> IL` exists for foreign artefacts and is honestly `rebuilt` with
declared loss. Two paths, both named, each with a carded ceiling. That dissolves the dispute rather
than splitting it.

**Determinism is where the systems architect was simply right and the other two were simply wrong.**
The `part` / `byte` split is verified in the interpreter (`ZipInfo.from_file` uses `time.localtime`;
`writestr` stamps local wall-clock; the bare `ZipInfo(name)` constructor is the deterministic one)
and it is correct in principle: a zlib bump changes compressed bytes for identical input, so
container-byte reproducibility is not portable. The pragmatist's gate asserts one digest across 18
platform x version runs, and the ecosystem declares `repro = "bytes"` while its own failure mode 2
admits `zipfile`'s external attributes carry the POSIX umask. Both gates go red on day one and
someone weakens them. `part` is the promise; `byte` is asserted under a pinned resolution and
recorded, never promised.

Three further picks. **Severity and provenance are orthogonal** (pragmatist), because ppt-master's
`blocking = errors` / `introduced = warnings` (`checker.py:9192-9230`) conflates them and D1's own
wire frame already carries both. **One `il_digest` implementation** (systems, pragmatist) — the
drift ppt-master's second implementation catches is temporal, and the ecosystem's two Python
implementations of one function are a way for two readers to disagree about bytes neither read
wrong. **R3, the second-round fixed point** (pragmatist), is the best round-trip statement in the
panel: the first round legitimately normalizes compatible input once, the second must be stable —
and I bolt on the systems architect's mutation test (R5), without which `loses = ["*"]` is a green
report.

Two corrections to the record. All three proposals and the digest say ppt-master's closed inline
surface is 29 properties; it is 32, counted from the frozenset. And the pragmatist's requested D2
`rebind()` "rule 0" amendment is unnecessary: D2's existing rule 1 (equal `content_digest` under the
same parent carries `block_id`) already carries a pure slide reorder, because a reorder changes no
slide's own merkle digest and no slide's parent. Adding a load-bearing `x` key to a D2 hot path for
a case D2 already handles was the wrong trade.

Finally, the third target. `deck` and `video` prove the contract across execution models, which is
real; `docx` proves it across carrier *shape* — flow, no canvas, no z-order, no bake — which is the
direct test of whether this abstraction is one implementation wearing an interface, and it is the
test the brief actually asks for. Against that, `mine-out.md` PART 3 on hyperframes was never
written, and designing a construct table for `video` from an index page would be the exact
speculative generality this ruling refuses. So the third target is `docx`, `video` ships as a
declared-unimplemented card, and the refusal branches of the contract (`citations = sidecar`,
`fidelity = none`, `bake = unavailable`) are exercised in CI by a shipped reference target rather
than left unexecuted until video lands.

## Rejected

- **`il_node` as a durable node table in the `.owstore`, with the text as a projection (systems)** —
  its motivating claim, that IL-as-files makes anchors stale, is refuted by ppt-master's own
  `data-pptx-source-ref` stamped-attribute anchor; it is a second representation of what the text
  carries (the pattern D2 forbade for L4), it costs nine tables and a parallel identity system, and
  making the table the pivot means `emit_il` rewrites the author's file on every validate.
- **A universal IL across all targets** — hyperframes' `data-start` / `data-duration` /
  `data-track-index` (`packages/parsers/src/compositionContract.ts:11-32`, verified) and DrawingML's
  `a:prstGeom` share nothing above "tree with attributes". Three teams converged on **seven
  mechanisms and three different languages**; the shared thing is the pipeline. A surface loose
  enough to hold a fixed canvas, a flow document and a seekable timeline can only be checked for
  well-formedness, which is exactly open-slide's actual state (`tsc --noEmit` and biome).
- **The L2 block model as the IL** — `trust`, `quote`, `method`, `producer_id` and `origin_operator`
  are extraction axes and category errors on authored content; D2's 34-member `kind` has no room for
  a connector, a gradient stop, a track index or an animation trigger; and pushing them into
  `payload` / `x` recreates D2's own named shadow-schema risk at ten times the volume.
- **JSON Schema as the construct contract, or an IDL / codegen for the table** — cannot express the
  bake tier, cannot express the verified conditional prohibition (`id=` only with `<style>`), cannot
  express the occurrence budget. D1 already rejected an IDL for a larger boundary.
- **`parse_back` split into two port operations, `parse_back`(->IL) and `ingest_back`(->L2)
  (systems)** — the split is real but it is `read_back` composed with `project`, and making it two
  operations duplicates the reader for no property. The blueprint says `parse_back()` -> L2 and D3
  says "parse_back as a named `parse/1` driver id on the card"; both are satisfied by one reader.
- **A separate `target.toml` beside `driver.toml` (pragmatist)** — three files per target for a
  discovery cost D3 already measured and solved (`entry_points(group=…)` 15.3 ms behind a 1.01 ms
  `scandir`+`stat` validity key). Everything fits under `[capability.compile]`, where D3 makes
  unknown keys a recorded degradation rather than the hard error an unknown top-level table is.
- **A `manual` disposition with confidence predicates in the selector grammar (ecosystem)** — a
  disposition says what the compiler does with a construct; `manual_required` says what a human must
  do about a region, which is authored content. Making it a disposition inflates the selector
  dialect to carry `[confidence<0.8]` for one row in one target.
- **`Rule.AFTER` with a topological scheduler (systems)** — an abstraction with one implementation
  and no evidence of a real dependency beyond "the parse runs first". An integer `order` with a
  documented phase table is what ppt-master actually uses and it is checkable.
- **A second `il_digest` implementation in Python (ecosystem)** — ppt-master's two-implementation
  design guards *staleness*, not implementation drift, and the store removes staleness structurally.
  Two Python implementations only add a way to disagree. The Toolchain's is a second *language*,
  spec'd and parity-fixtured, which is the one form D1 sanctions.
- **`repro = "bytes"` / `byte_exact` promised portably (pragmatist, ecosystem)** — falsified by a
  zlib point release or a base-image bump, and by the POSIX umask in `zipfile`'s external
  attributes, which the ecosystem proposal itself names in its own failure mode 2. `part` is the
  property that is both true and useful.
- **`x.omniweave.el` plus a D2 `rebind()` rule-0 amendment (pragmatist)** — the amendment is
  unnecessary (D2 rule 1 already carries a reorder) and the key namespace is wrong; `ow` is the
  reserved first-party vendor and the two keys are indexed into real tables so `x` never becomes the
  query surface.
- **hyperframes' `.media/manifest.jsonl` as the ledger** — the best ledger in the collection, and
  its record is `{id,type,path,source,description,duration,width,height,transparent,entity,
  provenance:{provider,prompt,…}}` (`skills/media-use/scripts/resolve.mjs:509-534`) with **no
  licence, no SPDX, no attribution, no restriction code**. A frozen asset with a prompt and no
  licence is reproducible and undeliverable. D2's `asset` already has all of it; a JSONL SSOT beside
  a SQL table is a sync layer, and D2 ruled on sync layers. (The job directory's
  `assets/index.json` is a projection for a process with no store access, and says so.)
- **TSX as the deck carrier** — open-slide's real assets are the fixed canvas, the comment protocol,
  the loc-tag injection and the request guard, none of which need TSX; TSX drags babel into the
  validator and a JS AST parser into `read_back`, and it forecloses `owdeck/1` being `owmotion/1`
  minus the timeline.
- **`video` as target three (systems, ecosystem)** — `mine-out.md` PART 3 was never written and
  `digest-out.md` says to treat hyperframes as *indexed but not mined*. A construct table designed
  from an index page, at a step change in runtime (Puppeteer + Chromium + system ffmpeg), a step
  down in determinism, and a live codec-licensing surface, is the failure mode this ruling exists to
  refuse. The refusal branches it would exercise are exercised by the shipped reference target.
- **LibreOffice headless as the compiler** — LGPL/GPL external binary, no byte reproducibility, no
  element addressing, therefore no `data-ow-el`, no feedback protocol, no fidelity tiers, and no
  `read_back` — which is the entire point of this decision.
- **A local preview / editor HTTP server at v1** — needs open-slide's `request-guard.ts` (verified
  76 lines) as a *minimum* and D1 bans loopback listeners in the pipeline. It is additive later,
  over the same marker protocol, in its own distribution, shipping that guard on day one of its
  existence.
- **`attribution_guard.py`'s shape** — hashing `LICENSE` and requiring a `SPONSORS*.md` as a runtime
  precondition of conversion. Attribution ships as licence text and a `NOTICE`, never as a gate that
  breaks an unrelated task.
- **Auto-fix, and any `--force` / `--no-gate`** — ppt-master verbatim: *"a mechanical patch can
  silently overwrite valid design intent and ship a worse page."* The only named relaxation is
  `--accept-manual`, which produces a `delivery: "draft"` the release path cannot accept.

## Consequences

- **D3 gets a fifth port with real contents.** `compile/1`'s `capability.compile` block, its
  `[capability.compile.round_trip]` sub-block, and a twelfth `omniweave-conform` suite (`target`)
  whose mandatory tier must fit inside D3's five-minute CI timing assertion.
- **D3's Service namespace `toolchain:<name>` is reserved by D8.** `io.service("toolchain:deck")`
  returns a `ToolchainHandle` whose `.run(job_dir, timeout_s)` is `omniweave_core.toolchain.run`
  executed **in the host process**. This is how a `compile/1` Driver invokes a Toolchain without a
  second subprocess site; D1 gate G8 and D3's non-extensible `DriverIO` both hold unchanged.
- **D2's open question #2 is settled: OUT edits and `read_back` always write a new `gen`.** A sealed
  generation is never patched, `ord` rebalancing is never a hot path, and `ord_path` stays rejected.
- **D1's open question on msgpack is settled: no.** No target needs the L2 block model in a
  non-Python process. A Toolchain receives IL text, an asset index projection and a flattened
  `cites.json`.
- **D2 gains exactly two reserved `x` keys**, `x.ow.el` and `x.ow.cite`, with `ow` as the only
  reserved first-party vendor prefix, both indexed into real tables (`artifact_el`, `artifact_cite`)
  so `x` is a transport and never a query surface.
- **`omniweave_core.out` adds a stdlib carrier layer** (`xml.etree`, `html.parser`) that `deck` and
  `docx` share, at the price of a hard pre-parse ban on `<!DOCTYPE`, `<!ENTITY` and processing
  instructions. This removes the 350 lines of duplication the pragmatist priced and keeps gates G1
  and G9 intact, provided `omniweave_core.out` stays a lazy submodule off the per-turn import path.
- **D1's distribution table grows to twelve** (`omniweave-target-docx`, `core + python-docx + lxml`,
  ~20 MB ceiling, **not** in `omniweave[recommended]`, so the 250 MB aggregate gate is untouched).
  Adding a row touches `tools/weights.toml`, `[tool.uv.workspace]` and G5's version list — all
  per-row mechanisms — and it is a `RELEASE` event, not a contradiction.
- **D5 inherits five OUT tables in the same `.owstore`** and one useful index: `artifact_cite_block`
  answers "which generated artefacts quote page 14 of this contract", which is the compliance
  question an enterprise actually asks and which no repo in the collection can answer.
- **D9 (serve) must render `degradations[]`, `licence_notices[]` and `citations: "sidecar"`** — the
  last is a first-class, machine-readable admission that mailing the artefact alone loses the
  provenance, and hiding it would be the kind of quiet lie this contract exists to prevent.
- **D10 owns the golden and foreign corpora.** `fixtures/out/foreign/` is a standing obligation with
  a named owner; unstaffed, the round-trip laws test our reader against our writer forever.
- **`bake` is fail-closed for `pptx` at release 1** and becomes `toolchain:deck` once the deck
  toolchain is installed. Users will hit `OW-T-311` and read it as the framework being precious
  about licences. It is: ppt-master's rasterizer is `cairosvg` (LGPL-3.0, imported at
  `svg_to_pptx/pptx_package/media.py:15`, absent from `requirements.txt`) falling back to `svglib`
  (also LGPL-3.0), and `cairosvg` is D1's named regression fixture for gate G3.
- **Three construct tables need an owner.** ~180 + ~90 + ~70 rows, each with a code, a disposition,
  a fixture and a generated doc line. Budget ~0.2 FTE per active target for registry review under
  the severity doctrine.
- **Cost, honestly: ~32.5 engineer-weeks** — `omniweave_core.out` + conform 8, `pptx` 11, `deck` 7,
  `docx` 5, Windows parity 1.5. Roughly four calendar months for two people. Week 4: `ow out check`
  and `ow out compile` from a hand-written IL produce a real PPTX with a receipt. Week 8: the gate,
  the ledger, `ow out project` from the store, citations embedded — a deck from your corpus, with
  sources. **Week 13: `ow out back` and the fidelity tiers — the loop closes.** Week 18 `docx`,
  week 25 `deck`.

## Risks

- **UPSTREAM CONFLICT: D1 and D3 contradict each other on the driver surface, and D8 must pick.**
  D1 fixes the manifest as `omniweave-driver.toml` — *"`omniweave-driver.toml` — shipped as package
  data. Read WITHOUT importing the driver. Located via
  `importlib.metadata.distribution(dist).locate_file(...)`"* — with an entry-point value of the form
  `"parse.office.anydoc" = "omniweave_office.driver:AnydocOfficeDriver"`. D3 fixes it as
  `driver.toml` with a **dotted package** value: *"A value containing `:` or `/` is rejected with
  `CARD_ENTRYPOINT_NOT_A_PACKAGE`"*, justified by a build-time check
  (`setuptools._entry_points.validate`). These cannot both hold. **Minimum amendment: strike D1's
  `omniweave-driver.toml` filename and its `module:attr` entry-point example; D3's `driver.toml` and
  dotted-package form govern.** D8 is written against D3. The same ruling pair also diverges on core
  import paths (`omniweave_core.*` in D1, `omniweave.core.*` / `omniweave.ports.*` in D3); D8 uses
  `omniweave_core.out` and `omniweave.ports.compile_v1`, and the charter must pick one repo-wide.
- **D1's `omniweave.targets` entry-point group and D3's five-Port `omniweave.drivers` group are
  reconciled here, not amended, and the charter should confirm it.** `omniweave.targets` maps an
  artefact kind to the package holding its compile driver's card; `[targets] enabled` is an
  artefact-kind policy allowlist; `[drivers] enabled` names DriverIds; **both gates apply and
  neither bypasses the other.** If the charter prefers the systems architect's reading, the
  amendment is to strike the `omniweave.targets` row from D1's ENTRY-POINT GROUPS block and address
  targets solely as `compile.<artefact>.<impl>`. D8 works either way; it must not be left ambiguous.
- **D2 §5 caps an OOXML round trip below `verbatim` unless a driver uses `OriginBytes`.** Two
  proposals called this a hard defect and requested the same amendment. It is softer than they
  claim: nothing in D2 forbids `OriginBytes` into a **retained, hash-pinned** OOXML part, and
  `parse.pptx.native` emits it wherever an `a:t` run is a contiguous unescaped byte range in the
  retained `ppt/slides/slideN.xml`, so `verbatim` is reachable for the majority of runs today. The
  desirable-but-optional amendment is: `quote='verbatim'` requires (`os_kind='bytes'` OR
  (`os_kind='nodepath'` AND `nfc(node_text(part, os_path)) == block.text`)) AND
  `part.store_ref IS NOT NULL`. Cost: one `owcheck` clause and one testkit property. Declining it
  costs nothing structural.
- **The construct table is right and the lowering is wrong.** `OW-T-001` proves a row maps to *a
  symbol*, never that the symbol is correct. A `native` row whose lowering emits subtly wrong
  DrawingML — a gradient with reversed stops — passes every gate forever. Only the golden corpus
  catches it, and only for constructs someone wrote a fixture for. The table is a bound on what may
  be attempted, not a promise of correctness.
- **`read_back` and `lower` are jointly wrong.** R3 passes because the reader inverts exactly the
  writer's mistake. `fixtures/out/foreign/` is the only defence and it cannot exercise constructs
  foreign artefacts do not contain.
- **The ordinary case breaks the shipped provenance claim.** A user opens the PPTX in PowerPoint,
  edits one word and saves: PowerPoint rewrites every part, `data-ow-el` survives only if it
  round-tripped into `p:extLst`, and the Document Inspector can strip the custom provenance part
  outright. Citations degrade to `ledger_only`; the *shipped file* no longer carries them.
  Detectable and reported by `ow out verify`, not preventable.
- **Citation laundering.** `OW-T-102` proves verbatimness only where the element also declares
  `kind="quote"`. An agent writing `data-ow-cite` on text it composed passes. The cite proves where
  the agent said it looked, never that the text follows. No mechanical check closes this.
- **The agent oscillates against the gate.** 60 units, three blocking findings, the re-author
  introduces two new ones. The early-gate method sample bounds it in principle; in practice a
  systematically wrong assumption burns the context window first. `OW-T-006 GATE_OSCILLATION` after
  N cycles with no net finding reduction is the honest stop, and it is a stop, not a fix.
- **A 400-unit artefact makes the report unreadable.** Findings fold on `(code, rule, unit,
  canonical)`, so *unit* is in the key and 400 units with one systematic warning is 400 findings.
  Folding across units loses the address. `--group-by rule` is a flag; the JSON is the real defence.
- **`byte` determinism will produce a red CI nobody understands, at least once.** A python-pptx or
  lxml patch release that changes attribute emission order breaks the double-compile gate for no
  user-visible reason and blocks the upgrade until fixtures are re-blessed. `part` being the
  *promised* class bounds the blast radius; it does not remove the day of debugging.
- **Two package managers.** A pnpm bump changes the deck toolchain's construct set with no
  Python-side signal. `constructs_digest` on the `ready` frame is the only thing standing between
  that and a silently different deck, and it is one more thing a toolchain release must not forget.
- **`prevText` ambiguity on a template deck.** Fourteen units all containing "Learn more": location
  stale, content ambiguous, edit refused, human told to pick another element. Correct, and
  infuriating.
- **The input that breaks the whole design:** a 900-slide PPTX where every slide carries a
  `mix-blend-mode` overlay and an embedded OLE object. Bake is unavailable so every slide is
  `OW-T-311`; the OLE relationships mean every rebuilt unit must refuse rather than drop; the gate
  is `failed` with 900 folded findings, and the correct behaviour is indistinguishable from the
  framework being unable to do anything. The first line of the error must name both exits or the
  user leaves.
- **Registry sprawl.** 180 constructs today; in three years 400, of which forty are `normalize`
  aliases nobody generates and nobody dares delete. `ow out constructs --diff <tag>` dates them and
  computes the required semver bump; the promotion / demotion protocol says how to retire one;
  neither stops it.

## Terminology

- Target := an artefact kind (`pptx`, `deck`, `docx`, `video`). Named in `omniweave.toml [targets] enabled`, aliased in the `omniweave.targets` entry-point group, and implemented by exactly two Drivers: one `compile/1` and one `parse/1`.
- Carrier := the existing text format an IL is written in (`svg`, `html`). Never invented; always has an existing parser.
- IL := for one Target, the triple (Carrier, ConstructTable, RulePack). A closed, declared subset of the Carrier. Identified as `<name>/<major>`, e.g. `owsvg/1`.
- IL bundle := the set of IL text files plus `il.toml` for one artefact generation. Content-addressed by `il_digest`, retained in CAS, pointed at by `artifact.il_store_ref`.
- ConstructTable := `constructs.toml`, one row per allowed construct. The contract as data. Read by the validator, the compiler, the doc generator and the conformance kit; hand-written by nobody else.
- Construct := one ConstructTable row: an id, a selector, a Disposition, a RoundTrip class, a canonical spelling, a `maps_to` symbol and an `OW-T-nnn` code.
- Disposition := `native | normalize | bake | forbidden`. What the compiler does with a construct. `manual_required` is deliberately not one.
- RoundTrip class := `exact | normalized | lossy | dropped`, declared per construct. Drives `il_digest_rt`'s exclusion set and law R5's both-directions check.
- RulePack := the target's rules, one function per file with one test per file, signature `(RuleCtx) -> Iterable[Finding]`, ordered by an integer phase where phase 0 is the carrier parse and short-circuits.
- Finding := a structured diagnostic carrying a code, a Severity, a Provenance, a non-empty `fix`, an optional canonical replacement, a folded `count` and at most three examples.
- Provenance := `introduced | inherited | imported | framework`. Who owns a Finding. Orthogonal to Severity: an inherited error still blocks, attributed to the template.
- GateStatus := the ten-value release gate. Exactly one value, `passed`, permits a release. `passed-with-warnings` is a report status, never a gate status.
- il_digest := the source fingerprint binding a report to exact IL bytes — basename-sorted, `name\0sha\n` framed, an unreadable file contributing the literal `unreadable` plus an error row. One implementation; the Toolchain's is a second language, spec'd and parity-fixtured.
- il_digest_rt := `il_digest` computed over canonicalized subtrees with every payload key of a non-`exact` construct elided. The exclusion set is derived from the ConstructTable, never hand-tuned.
- nsig := the content anchor of one IL element: the first 8 hex of the canonicalized-subtree digest, after six declared normalizations, treating a subtree that references a changed definition as changed.
- el := the stamped IL element address, `u03/e17`, carried as `data-ow-el`. Minted once by `ow out stamp`, never renumbered, refused on duplicate. The positional half of the two-factor anchor.
- Asset slot := `asset-slot:<sha256>`, the only asset syntax permitted in an IL. Location-independent, so an IL compiles identically on another machine and needs no path normalization before hashing.
- Marker := an `OWC1:`-prefixed base64url comment in the IL carrying one feedback item. Presence is the state; there is no side table. Skip is a legal outcome represented by leaving the marker.
- Brief := the frozen, machine-parseable authoring contract: a schema-version comment on line 1, then only `## section` headings and `- key: value` rows, with `## forbidden` items tagged `(user)` where they are the user's own words. The role that consumes it cannot write it.
- UnitOutcome := `native | baked | passthrough | cloned_passthrough | patched | rebuilt | manual_required`. Every output unit is in exactly one; the sum is asserted; unclassifiable is fatal.
- Determinism class := one of `part | byte | frame | render`, declared as a set. `part` is member-payload equality and is portable and promised; `byte` is container-byte equality, asserted under one pinned resolution, recorded, and never promised.
- read_back := the Target's `parse/1` Driver: artefact -> `DocSink` -> L2 Blocks, stamping `Method.ROUNDTRIP`. An ordinary Driver with an ordinary card, probe, licence block and conformance run.
- project := the Target's `Doc -> IL bundle` method. The reconstruction path, used for foreign artefacts and for artefacts whose retained IL was lost. Always `rebuilt`, always with declared loss.
- lower := the compile Driver's `IL bundle -> artefact bytes` method, writing into `io.tmpdir`. Deliberately not named `compile`, which is the framework's gated pipeline verb.
- Draft := the artefact produced by `--accept-manual`: placeholders carrying their `ManualReason`, `delivery: "draft"` in the receipt, gate status unchanged, and `Diag(OW_MANUAL_REQUIRED)` on every later read_back. It can never be mistaken for a release because the release path reads the gate status.
- Reference target := `compile.text.owtext`, shipped inside `omniweave-conform`. ~10 constructs whose job is to exercise the contract's refusal branches — `citations = sidecar`, `fidelity = none`, `bake = unavailable` — in CI without a browser.

## Open questions

- Does the `deck` toolchain's rasterizer clear `tools/licences.toml`, and at what install weight? — naming a package here would be an unverified claim. Settle it by resolving a candidate set (resvg-js, sharp, a headless-Chromium screenshot path already present for `render` determinism), running D1's gate G3 over the resolved graph, the import graph and the unpacked artifacts, and measuring the bundle delta. If none clears, `bake` stays `unavailable` on every target and the `bake` disposition has zero live rows — which would be a reason to demote it to `forbidden` with a documented degradation rather than keep a tier nothing implements.
- Does `part` determinism actually hold for `python-pptx` across the {ubuntu, macos, windows} x {3.11, 3.12, 3.13} matrix? — the `byte` claim is knowingly resolution-scoped, but `part` is *promised* and rests on lxml serializing in insertion order with nothing iterating an unordered collection. Settle it by compiling the 40-unit golden fixture on all nine cells and diffing `part_digest` member by member before week 8; a failure moves the floor from `part` to a normalized-part class, and that is a card-visible downgrade.
- What is the real cost of `project(Doc) -> IL` for `pptx`, and is `structure` the honest ceiling rather than `passthrough`? — `passthrough` is claimed for the *retained-IL* path (R1/R4), which is cheap. `project` on a foreign deck must invent an SVG subset from DrawingML, and nothing in `_collections/` does that: ppt-master reads a PPTX to Markdown plus an intake bundle, not to authoring SVG. Settle it by implementing `project` for ten real foreign decks and measuring what fraction of shapes round-trip R2; below ~70% the card should declare `project = false` for foreign input and `ow out back` should be corpus-only.
- Is the ten-value gate the right size, or do `unverified` and `stale` collapse in practice? — users will read them as the same thing until they hit them. Settle it by instrumenting the first two releases' issue tracker for gate-status confusion reports; two distinct statuses producing one class of question is evidence to merge, and merging is cheaper than splitting later.
- Does the early gate's mechanical classification (fires on >=3 of 5 sampled units => method-level) actually reduce agent iterations? — ppt-master leaves the classification to a prompt; making it mechanical is my change and it is unmeasured. Settle it by running twenty authoring tasks with and without the classification and counting validator invocations to a passing gate; if the reduction is under ~20% the early gate is context cost for nothing and should be a flag rather than a default.
- Should `video`'s IL be `owmotion/1` as `owdeck/1` plus a timing attribute group, or a separate carrier? — the pragmatist's sequencing argument says the deck IL is the video IL minus the timeline, and hyperframes' verified `compositionContract.ts` supports it. Settle it when PART 3 of `mine-out.md` is written: mine `hyperframes/packages/parsers` and `packages/lint` properly, then diff its element closure against `owdeck/1`'s. If the shared closure is under ~60%, `owmotion/1` is a separate carrier and the deck-before-video ordering buys less than claimed.
- Do `deck` and `docx` really share one `html` CarrierDoc, or does `docx` need a real HTML5 parser? — the stdlib `html.parser` is adequate for a closed, machine-stamped subset and inadequate for hand-written HTML with implied end tags. Settle it by running the `owflow/1` fixture corpus, including deliberately sloppy hand edits, through `html.parser` and counting parse divergences from a reference HTML5 parser; more than a handful and `docx` ships its own carrier and the duplication returns.
