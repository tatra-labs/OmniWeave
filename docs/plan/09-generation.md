# Generation: the OUT Compiler Contract

**In one paragraph.** OUT is not an abstraction over "generation". A **Target** is an artefact kind
(`pptx`, `deck`, `docx`, `video`) implemented by exactly two Drivers on existing Ports — one
`compile/1` and one `parse/1` — plus four target-owned artefacts: a `constructs.toml`
**ConstructTable**, a **RulePack** of one-function-per-file predicates, a `lower()`, and a
`read_back`. Everything else — the `Finding` model with orthogonal severity and provenance, the rule
runner, the ten-value `GateStatus` bound to `il_digest`, the asset ledger, the `OWC1` marker grammar,
the `Brief`, `manual_required`, the seven `UnitOutcome`s, the receipt, the round-trip laws `r1..r7`,
the OPC writer and the conformance suite — is framework code in `omniweave_core.out` that every
target gets for free and no target may reimplement. An **IL** is a carrier plus a ConstructTable plus
a RulePack: a closed, declared subset of an existing text format, described as data and enforced as
code, retained content-addressed in CAS so that editing an omniweave-built artefact is a
`passthrough` operation rather than a reconstruction. This document is the implementable expansion
of charter §D8 and invariants OUT1-OUT24.

Dependencies stated once and not restated: the document model, `Kind`/`Layer`/`Quote`/`Trust`, the
`asset` table and the `x` extension bag come from [the document model](03-document-model.md); Ports,
`DriverCard`, `DriverIO`, `probe()` and conformance from [the driver system](04-driver-system.md);
`cite` resolution and `Hit` selection from [storage and retrieval](07-store-and-retrieval.md); the
work queue, cache, `Producer` identity, Toolchain execution and `Degradation` from
[the execution runtime](08-runtime.md); the `ow out` flag grammar, the exit-code table, the OUT
skills and `ow make` from [interfaces](10-interfaces.md); the determinism and golden gates in CI, the
golden corpus and the eval scoreboard from [quality](13-quality.md); egress grants, `dpa_ref`,
`restriction_bits` policy and toolchain licence scans from [security](14-security.md); the routing
rule that would prefer a target's own `read_back` from
[ingest and routing](05-ingest-and-routing.md).

What this document decides that no other document may re-decide: the `compile/1` protocol, the IL
contract and its governance, the validator and its gate, the compiler and its receipt, the asset
ledger's compile-time behaviour, the `OWC1` grammar, `manual_required`, the citation chain from the
artefact back to a polygon, the round-trip laws, and the three release-1 targets.

## 1. The seam: what the framework supplies, what a target supplies

There is deliberately **no `GeneratorTarget` protocol**. The charter rejects it by name, and the
`docx` target exists in the release-1 set specifically to falsify it: one interface over a slide
canvas, a flow document and a video timeline is one implementation wearing an interface. What
generalizes is not "a generator" — it is the *contract shape*: IL → validate → compile →
round-trip, with the validator and the gate owned by the framework.

| # | Artefact | Owner | Why it sits there |
|---|---|---|---|
| 1 | `CompileV1` (seven methods) | framework, `omniweave_core.out.compile` | its signature mixes ports types (`DriverIO`, `DriverResult`) with OUT types (`Plan`, `ILBundle`, `AssetLedger`, `RuleSpec`, `CarrierDoc`); a Protocol lives in one distribution (§5 X4) |
| 2 | `constructs.toml` — the ConstructTable | **target** | the contract *as data*, one row per allowed construct, read by validator, compiler, doc generator and kit |
| 3 | `rules/` — the RulePack | **target** | one function per file, one test per file, `(RuleCtx) -> Iterable[Finding]` |
| 4 | `lower/` | **target** | IL → target primitives, into `io.tmpdir` |
| 5 | `read_back` (a `parse/1` driver) | **target** | an ordinary parse Driver with an ordinary card |
| 6 | `project()` | **target**, optional, carded | `Doc -> ILBundle`, the reconstruction path |
| 7 | `measure.py` | **target** | one `TextMeasure` implementation (§4.4), imported by **both** `rules/` and `lower/` |
| 8 | `kind_map.toml` | **target** | `Kind` ↔ target primitive; R2's comparator |
| 9 | `normalizers.py` | **target** | the pure `str -> str` functions a `normalize` row's `normalizer` key names |
| 10 | `Finding`, `Severity`, `Provenance`, `FindingSet.fold()` | framework | so console and JSON cannot disagree |
| 11 | the rule runner `run_pack()`, `RuleCtx`, `RuleSpec`, `DocIndex` | framework | a target that could run its own gate could skip it |
| 12 | `GateStatus`, `gate_status()` | framework | exactly one of ten values permits a release |
| 13 | `il_digest()`, `il_digest_rt()`, `nsig()`, `part_digest()` | framework | one implementation; the Toolchain's is a second *language*, spec'd and parity-fixtured |
| 14 | `AssetLedger` over L2's `asset` | framework | `asset` stays the single source of truth |
| 15 | the `OWC1` marker grammar | framework | `scan()`, `apply_reverse()`, `assert_clean()` |
| 16 | `Brief`, `parse_brief()` | framework | the role that consumes a Brief cannot write it |
| 17 | `ManualReason`, `ManualEvidence` | framework | a closed vocabulary |
| 18 | `Plan`, `OutUnit`, `UnitOutcome`, `classify_and_assert()` | framework | total classification; unclassifiable is fatal |
| 19 | `Receipt`, `CheckValue` | framework | the delivery evidence |
| 20 | `roundtrip.py` `r1..r7` | framework | executable predicates, imported by `omniweave-conform` |
| 21 | `opc.write_opc()` | framework | the only `zipfile`-for-write in the framework (OUT15) |
| 22 | `job.py` — the JobDir layout, `il.toml` | framework | for a Toolchain target this directory **is** the S2 data plane |
| 23 | `carrier/xml.py`, `carrier/html.py` | framework | stdlib parsers; DOCTYPE banned |

Eight files a target author writes, fifteen framework modules they inherit. The charter's four
target-owned artefacts — the ConstructTable, the RulePack, `lower()` and `read_back` — are the
load-bearing ones; the other four (`project()`, `measure.py`, `kind_map.toml`, `normalizers.py`) are
the supporting data those four cannot be written without. The ratio is the point: a third-party
target author writes a table, some predicates, a lowering and a reader, and inherits a gate they
cannot weaken.

Two entry-point groups, both of which apply and neither of which bypasses the other (§5 X5):

```
omniweave.drivers  "compile.pptx.native" = "omniweave_target_pptx"        # a dotted PACKAGE path
                   "parse.pptx.native"   = "omniweave_target_pptx.back"
omniweave.targets  "pptx"                = "omniweave_target_pptx"        # an ARTEFACT ALIAS
omniweave.toml  [targets] enabled = ["pptx"]   -> an artefact-kind POLICY allowlist
                [drivers] enabled = [...]      -> DriverIds (INV-5, the activation gate)
```

`omniweave.targets` maps an artefact kind to the package holding its compile driver's card, which is
what lets `ow out targets` list an artefact kind without resolving a driver. `ow doctor` **fails** on
a target enabled in `[targets]` whose compile driver is absent from `[drivers] enabled`, naming both
the target and the DriverId that must be added — the same failure shape §D1 defines for a
`[graph.passes]` pass whose driver is unenabled.

## 2. `CompileV1` in full

Seven methods. `probe` and `__init__` are the `DriverBase` shape from
[the driver system](04-driver-system.md); the other five are OUT's.

```python
# omniweave_core/out/compile.py
class CompileV1(Protocol):
    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...
    def __init__(self, **config: Scalar) -> None: ...
    def carrier(self, path: str, text: str) -> CarrierDoc: ...
    def rules(self) -> Mapping[str, Sequence[RuleSpec]]: ...
    def measure(self) -> TextMeasure | None: ...
    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger,
              io: DriverIO) -> DriverResult: ...
    def postflight(self, artifact: str, plan: Plan) -> Receipt: ...
    def project(self, doc: Doc, io: DriverIO) -> ILBundle: ...
# THERE IS NO validate().
```

| method | may do | may **not** do | framework guarantee to the target | target guarantee to the framework |
|---|---|---|---|---|
| `probe` | import the target's own heavy deps; run a **capability probe** — the smallest real operation that proves a capability works (shape one glyph run with `uharfbuzz`, not `import uharfbuzz`) | download, spawn, write, read config | runs in a worker, never the host; cached per `(driver_id, version, env_digest)` under `$OMNIWEAVE_HOME` | `ProbeStatus.OK` implies `lower()` will not fail for a missing toolchain or a missing measure engine |
| `__init__` | validate and hold static config | load a model, open a file, touch the network | config is already validated against the card's `[config]` schema | constructing is free — a 100 %-cache-hit run constructs nothing |
| `carrier` | return a `CarrierDoc` over one IL file | mutate the file; resolve `asset-slot:` refs; recurse past `MAX_IL_DEPTH` | `text` is exactly the bytes on disk, already checked against `MAX_IL_FILE_BYTES`; `path` is job-relative | the parse is **strict** for anything that writes and error-recovering only for read (§8.3) |
| `rules` | return `group -> tuple[RuleSpec, ...]` | run anything; read the filesystem; import `lower/` | `run_pack()` orders by `RuleSpec.order`, short-circuits at order 0, folds findings, records skips and truncations | the union of every `RuleSpec.codes` equals the set of symbols the pack can emit — the meta-gate checks **both** directions |
| `measure` | return the target's one `TextMeasure`, or `None` (§4.4 prints it and `Box`) | differ from the estimator `lower/` uses; return a fresh object per call | a `None` return makes every rule with `"measure"` in `needs` a **recorded skip** and the gate `unverified` | `measure()` and `lower/` share one implementation (OUT2) |
| `lower` | write into `io.tmpdir`; call `io.service("toolchain:<name>")`; call `write_opc()` | write `output_root` or `cache_root` (DR7, INV-6); read a clock, cwd, env or RNG (OUT14); open a ZIP for writing outside `opc` (OUT15); see the report (OUT23) | `plan` is **already gated** — `lower()` is unreachable behind a non-`passed` gate | every unit in `plan.units` gets exactly one `UnitOutcome`, and the sum equals `plan.unit_count` |
| `postflight` | reopen the produced artefact and re-verify structure | rerun the validator; treat file creation as proof | the artefact path exists and is complete | a `Receipt` whose `CheckValue`s are honest, `enforced-at-build` included |
| `project` | reconstruct an `ILBundle` from a `Doc` | claim `passthrough` fidelity | called only when `[compile.round_trip] project = true` | the bundle declares its loss; every produced unit's outcome is `rebuilt`, and every `Finding` the bundle later raises is `Provenance.IMPORTED` |

**The one Port protocol outside `omniweave_ports`.** `CompileV1` lives in `omniweave_core.out`
because it references `Plan`, `ILBundle`, `AssetLedger`, `RuleSpec` and `CarrierDoc`. The
consequence is that a `compile` distribution's `layers.toml` row is
`["omniweave_core", "omniweave_ports"]`, while an `acquire`/`parse`/`derive`/`embed` driver's is
`["omniweave_ports"]` alone. G4 derives each row from the distribution's declared entry points, so
no author picks (§5 X4, and [the driver system](04-driver-system.md) §1.6).

**No `validate()`, restated as a mechanism.** The framework calls `carrier()` to parse, `rules()` to
enumerate, `run_pack()` to execute and `gate_status()` to decide. The target never holds the
`OutReport`. `omniweave-conform`'s `target` suite calls `lower()` behind a deliberately failing
report and asserts the host never reaches it (OUT23).

**The compile-time call order**, which is the runner's middleware order and is semgrep-enforced to
have one call site:

```
resolve(target)                        # [targets] enabled AND [drivers] enabled
  -> activate()                        # asserts PORT and SCHEMA_VERSION against the card
  -> probe()                           # cached; a FAIL prunes the target FROM THE PLAN, with a report
  -> ILBundle.load(job_dir/il)         # il.toml + files; il_digest and il_digest_rt computed HERE, once
  -> AssetLedger.freeze()              # every asset content-addressed and licence-bearing (OUT10)
  -> restriction aggregate #1          # at plan time (OUT11)
  -> for each IL file: carrier(path, text)          # ONE UNIT RESIDENT AT A TIME (section 14.2)
  -> run_pack(rules(), bundle, mk_ctx)  # order 0 = the carrier parse, and it SHORT-CIRCUITS
  -> FindingSet.fold()                 # (code, rule, unit, canonical) -> count + <=3 examples
  -> gate_status(report, il_digest)     -> (GateStatus, introduced_warning_count)
  -> IF status != PASSED: STOP. lower() is not called.                          (OUT5, OUT23)
  -> marker.assert_clean()             # AFTER the gate, BEFORE lower()         (OUT16)
  -> restriction aggregate #2          # at compile time, the same SQL          (OUT11, DR17)
  -> lookup_before_build(six digests)  # a hit reuses bytes + part_digest       (OUT12)
  -> lower(plan, il, ledger, io)       # -> DriverResult, into io.tmpdir
  -> write_opc() | toolchain receipt   # container assembly
  -> postflight(artifact, plan)        # -> Receipt
  -> classify_and_assert(plan)         # sum(UnitOutcome) == unit_count, else FATAL (OUT8)
  -> seal: artifact + artifact_unit + artifact_asset + artifact_cite, sealed_at_ns
```

`marker.assert_clean()` sits between the gate and `lower()` on purpose. An unresolved feedback marker
is not a validity question — the IL is perfectly valid with a comment in it — and it is not a
lowering question, because by then the artefact exists. It is a **delivery** question, and delivery
is the last gate before bytes.

**Where the order can fail, and what survives.** Every step from `lower()` onwards writes into
`io.tmpdir`, which the host deletes on any exit path; nothing before `seal` touches `output_root`.
A crash, a timeout or a `DriverError` anywhere in the tail leaves: the JobDir with its
`validation/*.json` intact (written before the gate), no `artifact` row, and no bytes under
`output_root`. There is no partial artefact and no half-sealed generation — §5.4's sealed-row trigger
makes that structural rather than a convention. Section 14 gives the per-mechanism failure table. D749 builds `omniweave_core.out.compile`: `CompileV1`, structural and with no `validate()`, and `check()`, the call order's first half from `ILBundle.load()` to `gate_status()`, writing `validation/<stage>.json` over section 4.3's roster for each stage. Given the Plan's roster, `final` holds the bundle to it (`OW-T-507`). A need is met when the compile has what it names, so `cites` and `assets`, with no resolver or ledger yet, are recorded skips. A corrupt marker joins `skipped_checks`, and `RuleCtx.measure()` delegates to the one estimator. `omniweave_core.out.ledger` holds `AssetLedger`'s interface and `slot()`; the store-backed ledger and the call order's second half land with W9.7. D755 builds that second half as `omniweave.run.out_compile.compile_artifact()`, in the runner as this section calls it. It cannot live in `omniweave_core.out`, because the seal's rows are `store.artifact`'s and `store.artifact` imports `out`. Like `check()`, a closed gate is returned with its exit, never raised. A release needs `passed` and a draft needs `manual-required`; a draft of a gate that passed is a usage error. A Plan whose `il_digest`, `constructs_digest` or `ledger_digest` is not the one computed now is `stale`. Then, in order: `assert_clean()`; preflight's framework half (the rosters, every `asset-slot:` frozen, every cite resolving, each raised); aggregate #2 over the ledger's assets and the resolved blocks (`restricted`, exit 6); the lookup (a hit lowers nothing and re-places the bytes from CAS); `lower()`; `postflight()`, whose receipt must name this Plan, these bytes and the classifier's outcomes; `classify_and_assert()`; `retain.freeze()`; and the seal. The artefact is a CAS object, placed at `<slug>@<gen>/<slug><suffix>` only after the seal. This section never prints the attributes for a citation's `kind` and span, so `data-ow-cite-kind` and `data-ow-cite-span` are read where a target declares them, the default is `derived` with no span, and `verbatim` is set only where `out.cites.verbatim()` proves it. D772: `lower()` through `postflight()` is a `Lowering` in `omniweave.run.out_compile`, and where it runs is the caller's. `in_process()` is the conformance kit's seam and the tests'. `CompileWorker` runs it in an S4 worker launched for the one compile and stopped after it, because every compile card asks for `subproc`. Its one `INVOKE` is `pipeline.compile_host()`, so the call order keeps its one call site. A compile has no `Batch`, its cache is the lookup-before-build, and a `free` target reserves no budget, so no layer sits above that call. The worker's `RESULT` is read back as an in-process answer is: one `artifact` and one `receipt` ref out of the run's CAS, the receipt built again. A refusal is raised under its own symbol, and any other failure is `OW_TARGET_COMPILE_FAILED` (`OW-T-526`), with nothing sealed and nothing under `output_root`. The worker's output ceiling is `MAX_CONTAINER_TOTAL_BYTES`, since no limit names an artefact's size and an artefact is the container a parse reads back.

## 3. IL discipline

### 3.1 What qualifies as an IL

```
IL(target) = (carrier, ConstructTable, RulePack)
```

A carrier is an **existing text format with an existing parser** — `svg` for `pptx`, `html` for
`deck` and `docx`. Zero of the three mined OUT repos invented syntax, and that is the adoption
constraint: an LLM authors SVG far better than a tree of JSON objects. Four consequences are
normative, not stylistic.

1. **Text on disk, never a node table in the store.** An `il_node` table would be a second
   representation of what the text already carries (INV-1). The central argument for one — that
   file-based anchors go stale — does not survive the source: ppt-master stamps
   `SOURCE_REF_ATTRIBUTE = "data-pptx-source-ref"`
   (`ppt-master/skills/ppt-master/scripts/svg_authoring_view.py:89`) into the authoring SVG and keys
   `source_refs` on it, while `source_path: tuple[int, ...]` (`authoring_roundtrip.py:87-88`) is a
   *resolution* path, not the identity. A stamped attribute in the file survives file edits precisely
   because it is in the file. The rejected alternative cost nine tables, a parallel identity system,
   and a `parse_il(emit_il(n)) == n` property in the wrong direction — with a node table as the
   pivot, `emit_il` rewrites the agent's authored file on every validate, contradicting "the checker
   never rewrites source".
2. **Retained, content-addressed.** The bundle is frozen into CAS at compile time and pointed at by
   `artifact.il_store_ref` (the bundle) and `artifact_unit.il_sha256` (per unit). Editing an
   omniweave-built artefact fetches the retained IL. This is retention, not reconstruction, and it is
   the central synthesis of §D8: ppt-master's round trip keeps backing SVGs and regenerates its
   comparison baseline from them rather than reconstructing authoring source from a PPTX. D752 builds `omniweave_core.out.retain`. `freeze()` puts every IL file `il_digest` covers into CAS, `il.toml` included and dot-files excluded, and then one manifest object. The manifest's bytes are `il_digest`'s own preimage, one `name 0x00 hex 0x0A` line per file, so its CAS digest is `il_digest`, `il_store_ref` is `cas://` plus that digest, and the stored bundle verifies itself. Each file is hashed as it streams into CAS and compared with the row the gate passed. A difference is `OW-T-512 OW_TARGET_IL_MOVED` (appended), so a compile never seals bytes no gate saw. `Retained.units` holds each unit's `artifact_unit.il_sha256`. `fetch()` writes a retained bundle into a new directory only. It bounds and hashes the manifest, parses each line strictly, and streams each file out of CAS hashing as it goes. Any difference removes what it wrote and raises `StoreError`. D775: the Brief is retained beside the IL, as its digest's preimage. `Brief.record()` is the object `digest()` hashes, and `out.retain.freeze_brief()` puts its canonical bytes into CAS, so `artifact.brief_digest` names the Brief the compile read and no column is added, as `il_store_ref` is `il_digest`'s. `fetch_brief()` hashes the object against the digest and reads it back closed (`Brief.from_record()`). The record keeps every value and loses the file's order, which nothing reads. `compile_artifact()` retains the Brief before the seal. An edit (`ow out back`) and a verify from the artefact need it, because `brief_digest` is a purity input and the JobDir held the Brief's only copy.
3. **`asset-slot:<sha256>` is the only asset syntax inside an IL** (OUT9). No `http(s)://`, no
   `file:`, no `data:` URI and no filesystem path survives into IL text. The IL therefore hashes
   identically on another machine and needs no path normalisation before hashing. Semgrep bans
   `open()`/`Path()` on an IL-derived string inside `lower/`; the rule code is `OW-T-112`.
4. **The carrier parser is stdlib.** `carrier/xml.py` uses `xml.etree`, `carrier/html.py` uses
   `html.parser`, and DOCTYPE is banned in both — an external DTD is a network fetch and an
   entity-expansion bomb. Semgrep bans a second carrier parser under any target's `rules/` (OUT2).
   `xml.etree`'s expat is additionally constructed with entity definition handling disabled, so a
   billion-laughs payload fails at the first internal entity declaration rather than at expansion.
   **Extends the charter, which bans DOCTYPE and is silent on the rest:** both carriers additionally
   refuse every processing instruction other than the XML declaration itself, and `carrier/html.py`
   refuses every HTML bogus comment. The reason is the selector grammar below — a ConstructTable row
   can address an element or an attribute and nothing else, so a construct no selector reaches has to
   be refused by the parse rather than by a row. `<?xml-stylesheet` is exactly that: a stylesheet
   link wearing a syntax the grammar cannot name.

**`visible_text` is framework code, one implementation per carrier — extends the charter.** R2 and
`OW-T-102` both compare against "the visible text of an element" and neither is implementable until
that phrase is a function. `CarrierDoc` therefore gains one method beyond the charter's five:

```python
class CarrierDoc(Protocol):
    comment_open: str; comment_close: str
    def root(self) -> CarrierNode: ...
    def select(self, selector: str) -> Iterator[CarrierNode]: ...
    def place_marker(self, n: CarrierNode) -> Insertion: ...
    def source(self) -> str: ...
    def splice(self, edits: Sequence[Splice]) -> str | ParseError: ...
    def visible_text(self, n: CarrierNode) -> str: ...   # ADDED HERE. See below.
```

`visible_text` is defined per carrier and lives in `carrier/`, not in a target:

| carrier | definition |
|---|---|
| `svg` (`owsvg/1`) | the concatenation of character data under `<text>` and its `<tspan>` descendants in document order, with `xml:space="preserve"` honoured and otherwise leading/trailing whitespace stripped and internal runs collapsed to one space; each `<tspan>` carrying an explicit `x`/`dy` line break contributes `"\n"` before its content; `<title>`, `<desc>` and `<metadata>` contribute nothing |
| `html` (`owdeck/1`, `owflow/1`) | the concatenation of character data under the element with the same whitespace rule, `"\n"` inserted at every block-level boundary in the declared construct set, `<br>` contributing `"\n"`, and elements whose construct row carries `visible = false` (a footnote body rendered elsewhere, a `<template>`) contributing nothing |

Both are followed by `unicodedata.normalize("NFC", s)` at every comparison site, written `nfc(s)`.
`read_back` calls the same function to fill `Block.text`, which is why R2's `nfc(b.text) ==
nfc(visible_text(e))` is a real equality and not an aspiration. A target that wants a different
notion of visible text is asking for a different carrier.

**The four types those signatures reference, printed.** `rules/` is the target's principal
deliverable and it is written against `CarrierNode` and nothing else, so leaving the node type a
forward reference leaves the deliverable unwritable. All four live in
`omniweave_core/out/carrier/__init__.py` beside `CarrierDoc` — the charter's inventory line for that
directory names them and stops there — are carrier-agnostic, and are implemented exactly once per
carrier by `carrier/xml.py` and `carrier/html.py`.

```python
# omniweave_core/out/carrier/__init__.py
class CarrierNode(Protocol):
    at: str                    # "il/u03.svg:41:9" — job-relative path, 1-based line, 1-based
                               #   column. EXACTLY the form Finding.at carries: a rule passes it
                               #   through and never reformats it.
    el: str | None             # the data-ow-el address, "u03/e17". None until `ow out stamp` has
                               #   minted one, which is why every rule reading it tolerates None.
    tag: str                   # the element name IN SELECTOR SPELLING: "svg|text", "html|p". One
                               #   spelling for the node, the selector and the ConstructTable row.
    nsig: str                  # 8 hex — nsig() over THIS node's canonical subtree (section 8.2),
                               #   computed lazily and memoized per node.
    def attr(self, name: str) -> str | None: ...   # None => absent; "" => present and empty
    def children(self) -> Iterator[CarrierNode]: ...
    def text_content(self) -> str: ...   # RAW concatenated character data of the subtree: no
                                         #   whitespace rule, no NFC. NOT visible_text().

@dataclass(frozen=True, slots=True)
class Splice:
    start: int                 # a BYTE offset into source().encode("utf-8"), inclusive
    end: int                   # exclusive. start == end inserts; text == "" deletes
    text: str                  # the replacement
    # __post_init__ raises on end < start or start < 0.

@dataclass(frozen=True, slots=True)
class Insertion:
    at_byte: int               # where the marker line landed, in the SAME byte space as Splice
    line: int                  # the 1-based line the marker now occupies
    el: str                    # the address the marker was written AGAINST
    container_el: str | None   # the ancestor that actually carries it, set iff hoisted
    hoisted: bool              # True => the anchor was self-closing (section 8.2), so the note may
                               #   refer to a CHILD of container_el and the applier must say so

@dataclass(frozen=True, slots=True)
class ParseError:
    at: str                    # the same "path:line:col" form as CarrierNode.at and Finding.at
    msg: str                   # the stdlib parser's own message, passed through, never reworded
```

Four decisions inside those shapes, each one already depended on elsewhere in this document:

1. **Offsets are byte offsets, in one space.** `Splice.start`/`end` and `Insertion.at_byte` index
   `source().encode("utf-8")`, never `source()`. §8.3's descending-offset ordering, its
   pre-application overlap rejection and `il_digest`'s per-file `sha256(bytes)` are all byte facts; a
   character-offset batch would need one conversion per edit and would put the two orderings out of
   agreement on any non-ASCII unit. The applier encodes once per batch.
2. **`CarrierNode.nsig` is the subtree half only.** §8.2's shared-definition conjunct — *a subtree
   referencing a changed definition id is changed even when its own bytes are not* — is computed once
   per unit by the resolver, not per node by the carrier, because the naive per-node form is
   `O(elements × definitions)`. A node never claims to know whether it changed: it reports its own
   digest and the resolver ANDs.
3. **`ParseError` is returned, never raised.** `splice()` and `apply_reverse()` return
   `str | ParseError`, so a reparse failure is a value the caller must branch on while the original
   file is still untouched (§8.3 pt 3). It is therefore neither a `Diag`, which is recorded, nor an
   `OwError`, which is raised (§5.1) — it is the third thing, and it is what lets `ow out stamp` and
   `ow out normalize` exit 70 *having written nothing* (§4.3) instead of unwinding an exception
   through a half-written file.
4. **`text_content()` and `visible_text()` are two functions on purpose.** The node's is raw and
   carrier-independent and is what `lower/` joins when it emits text; the doc's is the per-carrier
   definition in the table above and is the only one R2 and `OW-T-102` compare against. Collapsing
   them would push a whitespace rule into every carrier's node implementation and would make R2's
   `nfc(b.text) == nfc(visible_text(e))` an equality between two things that were never one function.

**The carrier selector grammar — one grammar, one parser, three callers.** `CarrierDoc.select()`, a
`constructs.toml` row's `selector` and a row's `forbidden_when` all parse through
`omniweave_core.out.carrier.parse_selector()`. It is deliberately **not CSS**: a ConstructTable row
must be decidable against one node plus that node's own attributes, with no cascade, no ancestor
context and no document order — which is exactly what lets `run_pack()` drop each parsed tree at the
end of its unit (§14.2), and what lets the contract be data rather than code.

```abnf
selector     = element / attribute / subproperty
element      = ns "|" local [ "[" attr-name "]" ]   ; "svg|script"   "html|div[data-ow-manual]"
attribute    = "@" attr-name                        ; "@fill"  "@id"  "@data-ow-cite"
subproperty  = "@style|" css-prop                   ; "@style|mix-blend-mode"
ns           = "svg" / "html"      ; the carrier's OWN prefix, from constructs.toml's `carrier`
local        = 1*( ALPHA / DIGIT / "-" )            ; "foreignObject" is legal; case is significant
attr-name    = ( ALPHA / "_" ) *( ALPHA / DIGIT / "-" / "_" / ":" )
css-prop     = ALPHA *( ALPHA / DIGIT / "-" )
```

| form | matches | yields |
|---|---|---|
| `svg\|script` | every element whose `tag` equals the selector | the element |
| `html\|div[data-ow-manual]` | every element of that tag **that also carries the named attribute** | the element |
| `@fill` | every element carrying that attribute, whatever its value | **the element**, never the attribute |
| `@style\|text-shadow` | every element whose `style` attribute **declares** that CSS property | the element |

Eight rules close it:

1. **The two attribute forms yield elements.** `select("@id")` returns nodes and a rule reads the
   value with `n.attr("id")`, which is why the reference target's `rule_id_with_style` is written the
   way it is ([the API sketch](18-api-sketch.md) §6.2). There is no attribute node type and no
   `Finding` addresses one: an attribute-level finding addresses its element through `el`/`at` and
   names the attribute in `msg`.
2. **`ns` is the carrier's own prefix and nothing else.** `svg` for `carrier = "svg"`, `html` for
   `carrier = "html"`, applied to the carrier's default namespace — so an unprefixed `<link>` in an
   `owsvg/1` file is `svg|link`. An element in any *other* namespace matches no selector at all and
   is therefore caught by `unknown_construct = "forbidden"` (§3.5). Fail-closed is the right answer
   for a foreign-namespace element in an authored IL.
3. **`<sub>` is defined for `style` and for no other attribute.** `@style|<prop>` is *declaration
   presence*: the framework's inline-style splitter parses the `style` attribute into declarations
   over the carrier's closed property set (§12.1) and the selector matches when `<prop>` is among
   them. It is never a value match. `style` is the only attribute whose value is itself a declaration
   list, so `@<name>|<sub>` for any other `<name>` is a load error rather than a permissive no-op.
4. **The forms do not otherwise compose.** A selector is exactly one of the three productions, and
   the element form's single optional `[attr-name]` qualifier is the only composition the grammar
   admits. There is no descendant or sibling combinator, no `:pseudo`, no `.class`, no `#id`, no
   attribute-value predicate and no wildcard. Each of those needs either a cascade or a value
   grammar, and both belong in a `rules/` predicate — which has a test file — not in a table cell
   nothing executes.
5. **`selector` matches per node; `forbidden_when` matches per unit.** A row's `selector` is
   evaluated against the node under test. Its `forbidden_when` is evaluated against the whole unit —
   *does anything in this unit match* — which is what makes `attr.id`'s `forbidden_when = "svg|style"`
   mean "an `id` anywhere in a unit that also contains a `<style>` block". The framework evaluates the
   condition from the table and the rule only reports it; a rule that re-derived the condition would
   be a second implementation of the table.
6. **An unparseable selector is a usage error, never an empty match.** `ConstructTable.load()` raises
   `OW_TARGET_SELECTOR_INVALID` (`OW-T-007`) naming the row id, the key (`selector` or
   `forbidden_when`) and the offending offset within the string; `select()` raises the same for a
   rule's literal. Returning an empty iterator is what turns a `forbidden_when` typo into a silently
   disabled prohibition — the failure §3.4 assertion 3 calls the worst in the file.
7. **A node that is neither an element nor an attribute is not selectable, and is refused by the
   parse instead.** That is the whole of item 4 above: processing instructions and HTML bogus comments
   are rejected at `order = 0`, and a CSS at-rule (`@import`, `@font-face`) cannot occur once every
   construct that could host one is forbidden. No ConstructTable row is written for any of them.
8. **A `normalize` row declares no `selector`** and inherits its `normalizes_to` target's — §3.4. D738 builds the carriers in `omniweave_core.out.carrier`: the printed types, `parse_selector()`, the inline-style splitter and the one transactional splice, with `svg_carrier()` over expat and `html_carrier()` over `html.parser`. `select()` returns a tuple, because the reference target's `if not ctx.doc.select("html|style")` never returns against an iterator. A file that will not parse raises `CarrierParseError` carrying the `ParseError`. A ceiling is a `ResourceLimit` naming its knob. The recovering READ records each error it stepped over in `problems`, and `splice()` will not write such a document. A DOCTYPE, an entity declaration, a processing instruction, an HTML bogus comment or CDATA section, and each ceiling are refused in both modes. The strict HTML parse refuses a non-void `<x/>`, which a browser would not close. The HTML block and invisible sets are arguments until `constructs.py` exists. `nsig` and `place_marker()` arrive with the marker.

### 3.2 The bundle on disk, and `il.toml`

The lock defines an IL bundle as *"the set of IL text files plus `il.toml` for one artefact
generation"*. `il.toml` is the bundle's own roster and is framework-owned:

```toml
# job_dir/il/il.toml — written by `ow out scaffold`, read by ILBundle.load()
schema = "omniweave.out-il/1"
il = "owsvg/1"
constructs_digest = "sha256:71c4…"     # the table this bundle was authored against

[[unit]]
id = "u01"                              # matches ^u\d{2,}$ and is NEVER renumbered
ord = 1                                 # 1-based, contiguous, unique
file = "u01.svg"                        # a basename under il/, never a path
anchor = "cover"                        # the Brief's `## rhythm` anchor, or ""
```

Three rosters exist and all three must agree, which is what makes preflight check 3 a real check
rather than a tautology:

| roster | written by | authority |
|---|---|---|
| `job.json`'s `plan.units` | `ow out scaffold` from the Brief's unit count | the **Plan** — what was commissioned |
| `il/il.toml`'s `[[unit]]` rows | `ow out scaffold`, then edited by the authoring agent as units are added | the **bundle** — what was authored |
| the `*.svg` / `*.html` basenames present under `il/` | the authoring agent's file writes | the **filesystem** — what exists |

`ILBundle.load()` computes the three-way difference and raises `OW_TARGET_ROSTER_MISMATCH` naming
every id in exactly one of the three, in each of the three directions. A file on disk with no
`il.toml` row is as fatal as a row with no file: an orphan file is either a forgotten unit or a
leftover from a previous generation, and guessing which is how a deck ships eleven slides when the
Brief said twelve.

`il_digest` covers **every file under `il/` including `il.toml`**, sorted by basename. That is why
adding a unit to the roster invalidates a standing report even before the unit's own file exists.

### 3.3 The trichotomy, and the enforcement mechanism for each state

ppt-master's three input states (`ppt-master/docs/technical-design.md:17-25`), with omniweave's
enforcement bound to a `Disposition` row:

| state | the definition | omniweave `Disposition` | enforcement mechanism | severity |
|---|---|---|---|---|
| **canonical authoring input** | the single recommended expression prompts, templates and examples generate | `native` | the row's `canonical` field is the one spelling; `maps_to` resolves into `lower/`, checked **both ways** by OUT1 | no finding |
| **compatible input** | an explicitly documented historical or manual spelling with **one** safe deterministic normalization | `normalize` | `normalizes_to` names the canonical row; `normalizer` names a pure function in `normalizers.py`; `canonical` is **required** on the `Finding`; `ow out normalize` is a separate command with its own exit code | `warning`, **never** `error`, and never generated |
| **compatible but unexpressible** | (omniweave's fourth state) a construct with no native mapping and a defined deterministic degradation | `bake` | `bake = { renderer, dpi, role }`; the unit outcome becomes `baked` and `artifact_unit.reason` is **mandatory**; the row's `round_trip` is `lossy` | `warning` when bake is available; `error` when `[compile] bake = "unavailable"` |
| **invalid or unsupported** | no mapping, ambiguous meaning, a broken structural contract, or a risk of an invalid container | `forbidden`, or `native` with `forbidden_when` | the rule emits the row's `code`; the gate returns `failed`; there is **no `--fix`** and no auto-rewrite (OUT20) | `error` |

Three sentences from the same source are doctrine here, quoted because they are load-bearing:

- *"Severity is determined by whether the input maps deterministically and legally, not merely by
  whether it uses the recommended spelling."*
- *"It intentionally has no auto-fix: a mechanical patch can silently overwrite valid design intent
  and ship a worse page."*
- *"Prompts, templates, and examples … are not a correctness or safety boundary."*

The last one is why the validator, not the prompt, is the gate, and why `agent_doc_tokens_max`
exists. `ow out constructs pptx --format md` renders the ConstructTable as agent documentation under
a CI-gated ceiling (`agent_doc_tokens_max = 6000` for `pptx`). The document is *generated from the
table*, so a construct not in the table cannot be documented and a construct in the table cannot be
undocumented. D762 builds the verb, `ow out constructs <target> [--format text|md] [--group G | --construct ID]`, a CLI-only Action, since 10's roster names no tool for it. `omniweave_core.out.agentdoc` finds the table beside the card and reads the normalizer names from `normalizers.py` with `ast`, so documenting a target imports none of its code. A table whose digest is not the card's is `OW_CARD_INVALID`. A group is the id's first dotted segment. Each row is one line: the id, the selector and the disposition, one clause chosen by the disposition, and the code as its register numeric. owtext's ten rows come to 396 `cl100k_base` tokens against its 1200. The gate is a test, because `tiktoken` is dev-only, and it counts every implemented card's document whole and per group. Found: no card key carried the ceiling, so `agent_doc_tokens_max` is now required of an implemented card. Registered: `OW-T-515 OW_TARGET_UNKNOWN`, `OW-T-516 OW_CONSTRUCT_UNKNOWN` and `OW-T-517 OW_TARGET_AMBIGUOUS`.

**What that ceiling actually buys, with the arithmetic.** 6000 tokens over ~180 `pptx` rows is
**≈ 33 tokens per construct** — an id, one canonical spelling and one clause, and deliberately not
room for prose. A table that grows past its budget has three legal exits and no fourth: delete rows,
shorten `canonical` strings, or split the render with `ow out constructs pptx --group text`, which
emits one group under its own budget. There is no `--no-budget`.

**Three things a real table must express that JSON Schema cannot.** All three are verified in
ppt-master's source, and all three are why the ConstructTable is TOML data rather than a schema:

1. A **bake tier with a deterministic degradation** — `style.mix-blend-mode` has no DrawingML
   mapping but a defined raster fallback at a declared DPI.
2. A **conditional prohibition** — `id=` is an error *only when* `<style>` is also present. `id`
   alone is legal and is required inside `<defs>`; the hazard is the pair
   (`svg_quality/svg_contracts.py:196-278`). The row carries `forbidden_when = "svg|style"`.
3. A **cross-element occurrence budget** — "the third undeclared value is an error". ppt-master's
   check 9 keeps `_undeclared_size_occurrences: Counter[str]` and lets a sparse type size pass twice;
   the third occurrence fails. That is a stateful count across elements, expressible as a rule
   reading `RuleCtx.limits` and not as a shape constraint.

**Correction carried from the charter.** ppt-master's closed inline-style surface is **32**
properties (`_SUPPORTED_INLINE_STYLE_PROPERTIES`, `svg_quality/svg_contracts.py:180-188`, counted),
not 29. The number matters because it was about to seed a registry row count.

### 3.4 `constructs.toml` — the contract as data

```toml
schema = "omniweave.out-constructs/1"
carrier = "svg"
il = "owsvg/1"
version = 3
unknown_construct = "forbidden"                # FAIL CLOSED. NOT CONFIGURABLE.
ignore = ["svg|desc", "svg|title", "svg|metadata"]   # selectors, §3.1's grammar

[[construct]]
id = "attr.fill"
selector = "@fill"
disposition = "native"
round_trip = "exact"
canonical = "uppercase #RRGGBB | none | url(#id)"
maps_to = "lower.paint:solid_fill"
code = "OW_TARGET_FILL_INVALID"                # OW-T-410 is the HUMAN form
since = "0.1.0"
```

Every row carries `id`, `disposition`, `round_trip` and a `code` **symbol** — §5 C9 fixes the symbol
as the stored and wire form, and the numeric `OW-T-nnn` is resolved from `codes.toml` at render time.
Every row **except a `normalize` row** additionally carries a `selector` in §3.1's grammar; a
`normalize` row inherits the selector of the `native` row its `normalizes_to` names, because it is an
alias *of* that construct and a second selector could disagree with the row it normalizes into.
Additional per-disposition requirements, asserted by `ConstructTable.load()`:

| `disposition` | additionally required | additionally forbidden |
|---|---|---|
| `native` | `canonical`, `maps_to` | `normalizer`, `normalizes_to`, `bake` |
| `normalize` | `normalizes_to`, `normalizer`, `canonical`, `severity = "warning"` | `selector`, `maps_to`, `bake`, `forbidden_when` |
| `bake` | `bake = { renderer, dpi, role }`, `round_trip = "lossy"` | `canonical`, `maps_to`, `normalizer` |
| `forbidden` | `msg`, `round_trip in {lossy, dropped}` | `canonical`, `maps_to`, `normalizer`, `bake` |

Four more load-time assertions, each closing a way the table could lie:

1. `normalizes_to` resolves to a row whose `disposition == "native"`. A normalize row pointing at
   another normalize row is a chain, and a chain has no fixed point the table can prove.
2. `normalizer` resolves to a callable in the target's `normalizers.py`, and a property test asserts
   `f(f(x)) == f(x)` over the golden corpus's values for that construct. A non-idempotent normalizer
   makes `ow out normalize` non-terminating.
3. `selector` and `forbidden_when` both parse through **§3.1's carrier selector grammar** — one
   grammar, one parser (`parse_selector()`), and the same one `CarrierDoc.select()` uses. An
   unparseable value raises `OW_TARGET_SELECTOR_INVALID` (`OW-T-007`) naming the row and the key, and
   never degrades to an empty match: a typo that silently disables a prohibition is the worst failure
   mode in the file.
4. `since` is a valid version and never decreases across `version` bumps of the table. G13's
   append-only discipline for `codes.toml` has no equivalent here, so this is the substitute.

Three constructs are **mandatory in every ConstructTable** — a target that cannot express them
cannot be a target: `ow:cite`, `ow:manual`, `ow:unit`, plus the `data-ow-el` attribute.
`ConstructTable.digest()` is `sha256_canonical` over the loaded table, and `constructs_digest` on
the card is kit-checked against it. D739 builds `omniweave_core.out.constructs`: `ConstructTable.load(path, normalizers)` asserts the per-disposition table, the four load-time assertions bar `since`'s monotonicity, which needs the previous table, and the three mandatory attributes. An unknown key is refused at the top and in a row, because a misspelt `forbidden_when` would load as an unconditional native row. `severity` is a normalize row's key alone, and `msg` is required on a forbidden row. The mandatory constructs are recognised by the `data-ow-*` attribute their selector names. `ow:unit` is spelt per carrier, so order 10 checks it. `ignore` holds selectors, so the charter's `svg:desc` and the API sketch's `html:head` fail to load. `digest()` is `sha256:` over `sha256_canonical` of the loaded TOML. `conditional(doc)` evaluates `forbidden_when` per unit, for the rule to report.

### 3.5 The governance rule that stops an IL re-widening

An IL carved out of a general format decays back toward that format one accepted alias at a time.
Five mechanisms, all mechanical:

1. **`unknown_construct = "forbidden"`, and it is not configurable.** There is no tolerant mode, no
   per-project override, no `--allow-unknown`. A construct not in the table is an error. D781: `omniweave_core.out.conformance.table_pack()` checks this from the table. An element must match an element row. An attribute must be named by an attribute row, or by the qualifier of an element row that matched. A style property needs a `@style|<prop>` row. Whatever no row declares is `OW_TARGET_CONSTRUCT_NOT_IN_TABLE` (`OW-T-412`), and an `ignore` selector removes what it matches, an element with its subtree.
2. **A `normalize` row may never be generated.** Its `Finding` is a `warning` carrying a required
   `canonical`, and a framework rule (`ow.il.no-generated-alias@1`, `scope = "document"`,
   `order = 90`) asserts that no `normalize` construct appears in a bundle whose `Brief` declares it
   machine-authored. A compatible read is a **migration boundary**, not permission to widen the
   authoring language.
3. **The promotion/demotion protocol, with different owners.** *Warning volume is a prompt bug;
   warning danger is a contract bug.* A `normalize` warning recurring across newly generated units
   is fixed in the generated documentation or the skill, never by adding a `native` row. A
   `normalize` row shown to produce an invalid container or an ambiguous meaning has its
   `disposition` changed to `forbidden` and its `severity` to `error` **in the same change as its
   rule**, with `constructs.toml.version` bumped. A `disposition` change moves
   `constructs_digest`, which is one of the six purity inputs, which invalidates every artefact keyed
   on it — so the promotion is felt, not filed.
4. **The two-way gate (OUT1).** CI imports `lower/`, diffs its public symbol set against the table's
   `maps_to` set, and fails in **both** directions: `OW-T-001 CONSTRUCT_UNMAPPED` (a row whose
   `maps_to` does not resolve) and `OW-T-002 CONSTRUCT_UNDECLARED` (a lowering symbol with no row).
   You cannot widen the compiler without widening the table, and you cannot widen the table without
   widening the compiler.
5. **The row-count budget is visible.** `agent_doc_tokens_max` is CI-gated per target. A table that
   grows past its own agent-documentation budget fails the build, which converts "the IL is getting
   big" from a feeling into a red pipeline. Release-1 sizes, from the charter: `pptx` ~180 rows,
   `deck` ~90, `docx` ~70, the reference target `compile.text.owtext` ~10.

**Extends the charter.** Items 2 and 3's `version`-bump requirement, and the per-disposition
required-key table plus the four load-time assertions in §3.4, are new decisions in the charter's
spirit; the charter fixes `unknown_construct`, the two-way gate and `agent_doc_tokens_max`.

### 3.6 Editing an artefact authored against an older table

This is the case the mined collection never faced, because none of the three ships a versioned
contract. An artefact sealed with `constructs_digest = X` is opened for editing on a host where the
installed table digests to `Y`. Guessing is not available: the old table is not on disk, and CAS
retains IL text, not the contract it was written against.

The rule is **the installed table always governs, and the difference is attributed, never
suppressed**:

1. `ow out back <slug>` restores the retained bundle and compares `artifact.constructs_digest`
   against `ConstructTable.load().digest()`. Equality is the common case and nothing further happens.
2. On a difference the restored `il.toml` keeps its recorded `constructs_digest`, and every `Finding`
   raised against a construct that did **not** exist, or had a different `disposition`, in the
   recorded digest's table is stamped `Provenance.INHERITED` — not `INTRODUCED`. The generator did
   not author the breakage; a contract change did.
3. An **inherited error still blocks** (§4.1). A row demoted to `forbidden` because it produced an
   invalid container produces invalid containers regardless of when it was authored. The fix command
   names `ow out normalize` where the row is now `normalize`, and the construct's `msg` otherwise.
4. The recompile is a **new `artifact_gen`** with the new `constructs_digest`, never a patch of the
   sealed row (OUT24).
5. `ow out back` prints the contract delta before it prints anything else: rows added, rows removed,
   rows whose `disposition` moved, each with its `since`. A silent contract change discovered as a
   pile of findings is how a team concludes the checker is broken. D777 builds `ow out back <slug> [--gen N]`: the newest generation unless `--gen` names one, restored by D776's `restore()` into a new run's JobDir for the generation one past the store's newest. Its first line is the contract: `unchanged`, or `CHANGED` naming both digests and saying the rows that moved cannot be listed, since no recorded table version exists. The loop closes through the verbs. An unedited restore checks and compiles to OUT12's lookup of the sealed generation, because its six purity inputs are the sealed ones. An edited one seals the next generation. **Found:** owtext's `postflight()` reported every unit `native`, which is right on the create path only. An edited unit carries its source, the framework classifies it `passthrough`, `cloned_passthrough`, `patched` or `rebuilt`, and a receipt that disagrees is `OW-T-005`, so owtext now reports `classify_and_assert()`'s answer.

The framework cannot compute the delta without the old table, and it does not pretend to: the delta
is computed from the `since` field of the *installed* table's rows against the artefact's recorded
`version`, which is why `since` is mandatory and monotone (§3.4 assertion 4). It is a conservative
delta — it over-reports rows added since the recorded version and cannot see rows deleted — and the
console says so in one line rather than implying completeness. D776 builds the restore half of `ow out back`: `out.retain.restore()` writes the edit's JobDir, staged and renamed in as a scaffold is. `il/` is the retained bundle, its `il.toml` keeping the recorded `constructs_digest` (rule 2). `brief.md` is the retained Brief (D775) rendered by `out.brief.render_brief()`, and `assets/index.json` is the artefact's frozen assets, read by `SqliteArtifactStore.ledger()`. `job.json`'s Plan names the next generation with the gate `not-provided`, and its units are the sealed roster (`edit_roster()`), each with `source_part`, `source_nsig` and `source_ord` from its `artifact_unit` row. Those rows carry no part name but `il_path`, so `source_part` is the sealed `il_path`. **Found:** the delta above is computed against the artefact's recorded table `version`, and nothing records that version: the row, the retained `il.toml` and the receipt carry the table's digest alone.

### 3.7 `ILBundle`, `OutUnit` and `Plan`, printed

These three are the OUT framework's most-referenced types and the last of it without a field list —
`18#2` and `09#Q7` both record that, and `CompileV1.lower()`, `CompileV1.postflight()`, `RuleCtx`,
`run_pack()`, `marker.assert_clean()` and `classify_and_assert()` are every one of them written
against a name with no shape behind it. They are printed here, at the end of §3, rather than in §5
with the compiler, because §4.4's `RuleCtx` annotates two of the three and a type may not be
referenced before it is defined.

No new module: `ILBundle` and `ILFile` land in `omniweave_core/out/job.py` beside the JobDir layout
and `il.toml` (§1 row 22); `OutUnit` and `Plan` land in `omniweave_core/out/plan.py` beside
`UnitOutcome` and `classify_and_assert()` (§1 row 18).

```python
# omniweave_core/out/plan.py
@dataclass(frozen=True, slots=True)
class OutUnit:
    id: str                    # "u01" — matches ^u\d{2,}$, minted by `ow out scaffold`, and NEVER
                               #   renumbered: it is the first half of every `el` (§8.2) and of
                               #   every `artifact_cite.unit`, so a renumber invalidates citations.
    ord: int                   # 1-based, contiguous and unique within one roster. IL order, never
                               #   the filesystem's — `lower()` emits in `plan.units` order (§2).
    il_path: str               # JOB-RELATIVE: "il/u01.svg". `il.toml`'s `file` is the BASENAME and
                               #   this is "il/" + file. Two consumers need exactly this spelling:
                               #   `Finding.at` prefixes it ("il/u03.svg:41:9"), and every `fix`
                               #   command interpolates it (`ow out normalize il/u03.svg`).
    anchor: str = ""           # the Brief's `## rhythm` anchor for this unit ("cover"), or "" when
                               #   the Brief declared none. Read by the order-90 Brief rule.
    nsig: str | None = None    # 8 hex over the UNIT ROOT's canonical subtree (§8.2). None until
                               #   ILBundle.load() computes it; §5.5's classifier reads it.
    source_part: str | None = None    # "ppt/slides/slide3.xml" — the container part this unit is
                                      #   being edited FROM. None on the create path, which is what
                                      #   §5.5's second branch tests.
    source_nsig: str | None = None    # that part's nsig at seal time, from `artifact_unit`
    source_ord: int | None = None     # that part's ord at seal time; `ord != source_ord` with equal
                                      #   nsig is exactly `cloned_passthrough`
    manual_reason: ManualReason | None = None   # set from the unit's `ow:manual` construct after
                                                #   the check pass; §5.5's FIRST branch, and the
                                                #   source of `OutReport.manual_units[].reason`
    # __post_init__ raises on: an `id` not matching ^u\d{2,}$; `ord < 1`; an `il_path` not starting
    # "il/"; and any of `source_nsig`/`source_ord` set while `source_part is None` — a half-filled
    # source triple would make the classifier silently return `native` for an edited unit.
```

**Who fills each field, and when.** A reader deleting one needs to know which writer breaks.

| field | written by | when |
|---|---|---|
| `id`, `ord`, `il_path`, `anchor` | `ow out scaffold` into `job.json`'s `plan`; the authoring agent into `il.toml` as units are added | plan time, then throughout authoring |
| `nsig` | `ILBundle.load()`, over the same single parse that computes `il_digest` and `il_digest_rt` | once per compile |
| `source_part`, `source_nsig`, `source_ord` | `ow out back`, from the `artifact_unit` rows of the artefact being edited | only on an edit; all three `None` on the create path |
| `manual_reason` | the framework, from the unit's `ow:manual` region, after the check pass | before `classify_and_assert()` reads it |

`OutUnit` carries **no** `UnitOutcome`. The outcome is a compile-time result and lives in
`Receipt.units` and `artifact_unit.outcome`; a frozen `OutUnit` that appeared to carry one would
give `classify_and_assert()` two places to write and the receipt two places to read.

```python
# omniweave_core/out/job.py
@dataclass(frozen=True, slots=True)
class ILFile:
    name: str                  # a BASENAME under il/ — "u01.svg", "il.toml" — never a path
    sha256: str                # 64 lower-case hex, or the literal "unreadable" (§4.2's report JSON
                               #   emits exactly this string, and §14.4's rule is that an unreadable
                               #   file contributes it to `il_digest` rather than dropping out)
    byte_len: int              # 0 iff sha256 == "unreadable"
    error: str | None = None   # non-None IFF sha256 == "unreadable"; the OS or decode error verbatim
    # __post_init__ raises on the two IFFs being violated in either direction.

@dataclass(frozen=True, slots=True)
class ILBundle:
    schema: Literal["omniweave.out-il/1"]   # `il.toml`'s own `schema` key, checked on load
    il: str                    # "owsvg/1" — the IL id, NOT the target name. `pptx` has one IL;
                               #   `deck` and `docx` share a carrier and do not share an IL.
    root: str                  # absolute path of `<job_dir>/il/`. THE ONLY PATH IN THIS TYPE, and
                               #   the reason `text()` needs no second argument.
    constructs_digest: str     # the table this bundle was AUTHORED against — §3.6 compares it to
                               #   the installed table's and attributes the difference
    units: tuple[OutUnit, ...] # `il.toml`'s [[unit]] rows in `ord` order. This is the BUNDLE's
                               #   roster and is deliberately not `Plan.units`: preflight check 3
                               #   compares the two, and one object could not disagree with itself.
    files: tuple[ILFile, ...]  # EVERY file under il/ INCLUDING il.toml, sorted by `name`
    il_digest: str             # "sha256:…" over `files` in that order (§3.2)
    il_digest_rt: str          # §11.3's second digest, over the same parse
    els: Mapping[str, frozenset[str]]   # unit id -> the `data-ow-el` addresses stamped in it. The
                                        #   stamped index; `DocIndex.els` is rebuilt from the same
                                        #   walk and this is what `assert_clean()` and `ow out back`
                                        #   read without re-parsing.

    @classmethod
    def load(cls, il_dir: str) -> "ILBundle": ...
    def text(self, il_path: str) -> str: ...    # takes OutUnit.il_path ("il/u01.svg"); UTF-8 strict
    def data(self, il_path: str) -> bytes: ...  # the same bytes `il_digest` hashed
```

Four decisions inside that shape.

1. **The bundle holds digests and paths, never the bytes.** §14.2 fixes `il_digest` as a streaming
   hash over a fixed-size buffer precisely so a 2000 × 4 MiB = 8 GiB bundle digests in constant
   memory, and the whole-roster budget of ~150 MB has exactly one parsed unit resident. A `bytes`
   field would make `ILBundle.load()` alone 8 GiB. `text()` and `data()` re-read from `root`
   on demand, bounded per call by `MAX_IL_FILE_BYTES` (4 MiB), which is what both the reference
   target's `lower()` and `run_pack()`'s pass A already assume by calling
   `il.text(unit.il_path)` once per unit rather than indexing a mapping.
2. **`load()` parses each unit exactly once**, in `ord` order, and drops each tree: per file it
   records the `ILFile` row, and per unit it fills `OutUnit.nsig`, contributes to `els`, and feeds
   both digests. §11.3's *"both digests are computed once, in `ILBundle.load()`, over the same
   parse"* is that sentence, and it is why neither digest is recomputed per rule.
3. **`units` is the bundle's roster and not the Plan's.** §3.2's three-roster table only makes sense
   if the Plan's roster, `il.toml`'s and the filesystem's are three separately-sourced values;
   `ILBundle.load()` raises `OW_TARGET_ROSTER_MISMATCH` (`OW-T-507`) on the bundle-versus-filesystem
   difference it can see alone, and preflight check 3 raises the same code on the Plan-versus-bundle
   difference it cannot.
4. **A roster row and a rich `OutUnit` are one type, not two.** `il.toml` declares four of the nine
   fields and the rest default to `None`; a separate `UnitRow` would put the same `id`/`ord`/`file`
   grammar in two places and force a conversion at the one point — preflight check 3 — where the two
   rosters must be compared field for field. D744 builds `ILBundle` in `omniweave_core.out.job`. `load(il_dir, carrier=, constructs=)` takes the carrier and the table, since neither is reachable from a path. `il.toml` is asserted (`OW_TARGET_IL_TOML_INVALID`, `OW-T-011`, appended), and the bundle-against-filesystem difference names each id both ways (`OW-T-507`). `il_digest_rt` elides the selectors of the non-`exact` rows, but not a normalize row's, which shares its exact native row's selector and would hide R5's mutation. A unit the carrier refuses loads with no `nsig` and contributes 64 zeros to `il_digest_rt`, leaving the refusal to order 0. `text()` and `data()` re-read `take(N+1)`-then-check, and undecodable bytes are a `CarrierParseError`.

```python
# omniweave_core/out/plan.py
@dataclass(frozen=True, slots=True)
class Plan:
    schema: Literal["omniweave.out-plan/1"]   # the `plan` object inside `job.json`. Versioned in
                               #   its own right because for a Toolchain target the JobDir IS the
                               #   S2 data plane (§12.2) and the child parses this object across a
                               #   wire-version boundary; an unrecognised value is a refusal, never
                               #   an ignore, by the same reasoning as `[compile]`'s hard-error-on-
                               #   unknown-key (§12.4).
    target: str                # "pptx" — the ARTEFACT KIND, `omniweave.targets`' key. `Receipt.target`
    slug: str                  # "q3-board" — `artifact.slug`, and part of the `artifact_pure` index
    artifact_gen: int          # the PROPOSED generation, the one already in the JobDir path
                               #   `<artifact_slug>@<gen>/`. The SEALED value is allocated by the
                               #   INSERT (§5.4 rule 1); a difference is `OW-T-510`, not a rewrite.
    delivery: Literal["release", "draft"]     # `--accept-manual` produces "draft". Third column of
                               #   the `artifact_pure` unique index, and `Receipt.delivery`.
    units: tuple[OutUnit, ...] # THE COMMISSIONED ROSTER, in `ord` order. `lower()` emits in this
                               #   order and `classify_and_assert()` iterates it.
    unit_count: int            # stored, not derived: §5.3's precondition 2 compares the OUTPUT's
                               #   unit count against it and `OW-T-502` prints both numbers.
                               #   __post_init__ asserts `unit_count == len(units)`.
    brief: Brief               # the frozen Brief. `RuleCtx.brief` IS `ctx.plan.brief` — one object,
                               #   surfaced twice for the rule author's convenience, never copied.
    corpus: str                # the corpus id every cite resolves in; `ow open <cite> --corpus`
                               #   ([the API sketch](18-api-sketch.md) §6.2) interpolates exactly it
    cites: Mapping[Cite, int]  # cite token -> the `doc_gen` PINNED at plan time. The resolved cite
                               #   set: `CiteResolver` resolves at these gens, `artifact_cite.doc_gen`
                               #   is written from them, and §10's "a later re-parse cannot re-point
                               #   a shipped citation" is this mapping being immutable.
    gate_status: GateStatus    # THE STATUS, NEVER THE REPORT (OUT23). `postflight()` fills
                               #   `Receipt.gate_status` from here and has no other source.
    il_digest: str             # ─┐
    constructs_digest: str     #  │ the six purity inputs of §5.4, carried so that `lower()` and
    ledger_digest: str         #  │ `postflight()` can be re-entered against a JobDir without a
    brief_digest: str          #  │ store handle. `card_sha256` is the compile driver's card.
    card_sha256: str           # ─┘
    toolchain_digest: str | None = None   # None for a pure-Python target; the `artifact_pure` index
                                          #   spells this `IFNULL(toolchain_digest, x'')`
```

Five things that shape settles, each of which was otherwise a hole.

1. **`Plan` carries the gate status and not the `OutReport`.** §2's method table says `lower()` may
   not see the report and `omniweave-conform` asserts the host never reaches `lower()` behind a
   failing one — but `postflight()` returns a `Receipt` with a `gate_status` field and had no way to
   obtain it. One `GateStatus` on the `Plan` closes that without handing a target the findings.
2. **`Plan` carries no path.** No `job_dir`, no `output_root`, no `tmpdir`. `lower()` reaches IL text
   through `il` and writes through `io` — the two arguments DR7 and INV-6 are stated against — so a
   target that wanted to write beside the JobDir would have to invent the path rather than be handed
   it.
3. **`ledger_digest`, not the ledger.** The `Plan` carries the digest; the `AssetLedger` object
   itself is `lower()`'s third argument. The digest is on the `Plan` because it is a purity input;
   the object is an argument because it is a handle. They are not a duplicate home for one fact.
4. **`nsig` is non-`None` on every unit of a `Plan` that reaches `lower()`.** After preflight check 3
   has proved the Plan's roster and the bundle's agree on `(id, ord)`, the framework rebuilds
   `plan.units` with each unit's `nsig` copied from the bundle's. A `Plan` reaching
   `classify_and_assert()` with any `nsig is None` raises `OW-T-005` and the artefact is not written,
   rather than falling through to `native` — which is the branch a missing `nsig` would otherwise
   silently take.
5. **`artifact_gen` is proposed, not allocated.** §5.3 gives `Receipt.artifact_gen` and §5.4 says the
   generation is allocated by the INSERT; both are right and neither said which number the receipt
   holds. It holds the proposed one, which is the number already in the JobDir path the receipt is
   written into, and §5.4 rule 2's `OW_TARGET_GEN_CONTENDED` names the winner rather than the
   framework rewriting a sealed receipt.

## 4. The validator contract

### 4.1 What blocks, what warns, and who decides ownership

`Severity` decides **blocking**. `Provenance` decides **ownership**. They are orthogonal, and the
charter is explicit that ppt-master conflates them (`blocking = errors`, `introduced = warnings`,
`checker.py:9192-9230`).

```python
class Severity(StrEnum):    ERROR="error"; WARNING="warning"; INFO="info"
class Provenance(StrEnum):  INTRODUCED="introduced"   # the generator authored it
                            INHERITED="inherited"     # byte-identical in the template it derives from
                            IMPORTED="imported"       # arrived through project() of a tolerant read
                            FRAMEWORK="framework"     # omniweave itself: a skipped check, a shortfall
```

| | `introduced` | `inherited` | `imported` | `framework` |
|---|---|---|---|---|
| `error` | blocks; fix the IL | **blocks**, attributed to the template; the fix command names the template | blocks; the artefact is not deliverable from a tolerant read | blocks; a framework bug, prints the report command |
| `warning` | recorded; counts toward `introduced_warning_count` | recorded; **excluded** from the introduced count | recorded; excluded | recorded; excluded |
| `info` | recorded | recorded | recorded | a **recorded skip** → the gate becomes `unverified` |

**An inherited error still blocks.** That is the one behavioural difference from ppt-master and it is
deliberate: a template with a broken structural contract produces a file the host application will
offer to repair, whoever authored the breakage. What provenance buys is that a template with 40
pre-existing *warnings* does not make every generated deck look broken, so the team keeps reading the
report. ppt-master routes inherited findings out of the warning channel entirely
(`_append_inherited_info`, *"Record prototype-owned diagnostics outside the warning channel"*); here
they stay in one channel with an orthogonal owner field, which is strictly more expressive and one
list instead of two.

**A rule may only emit `INTRODUCED`; the framework stamps the other three.** This is the mechanism
the draft contract needs and the mined collection lacks: without it, "inherited" is a claim a rule
author makes and nothing can check. `run_pack()` raises `OW_TARGET_RULE_FORGED_PROVENANCE`
(`OW-T-004`) on any rule returning a `Finding` whose `provenance != INTRODUCED`, then re-stamps with
`dataclasses.replace()` under exactly three conditions:

| stamped | condition, computed by the framework |
|---|---|
| `INHERITED` | the finding's `el` resolves to an element whose `nsig` is a member of the template's stamped nsig set, **or** its `construct` moved disposition since the bundle's recorded table version (§3.6) |
| `IMPORTED` | the bundle's `il.toml` carries `origin = "project"` — the whole bundle came out of `project()` |
| `FRAMEWORK` | the framework minted the finding itself: an unmet `needs`, a truncation, a shortfall. A target cannot mint one |

The template's nsig set comes from the `Brief`'s `## template` section:

```text
## template
- ref: asset-slot:9f3a1c04…            # the template artefact, frozen in the ledger like any asset
- units: u01, u02                       # which authored units derive from it; omitted means all
```

`ow out scaffold --from-template <path>` freezes the template through `AssetLedger.freeze()`, runs
the target's `read_back` over it once, stamps `el` addresses, computes one `nsig` per element and
stores the set in `il/template.nsig` (one hex value per line, sorted). `nsig` is already the
canonicalized-subtree digest with six normalizations and shared-definition dependency tracking
(§8.2), which is exactly the equality "byte-identical in the template it derives from" needs and is
strictly better than byte equality, because a template element that survived a legitimate id-prefix
rewrite is still the template's.

No template, no `template.nsig` file, no `INHERITED` findings. That is correct and is the release-1
state for a from-scratch deck.

`Provenance` is orthogonal again to **`baselined`**, which the eval report *computes* from
`eval/baselines/` and which a generator may never declare — see [quality](13-quality.md). The release
headline is therefore `severity == error` plus `severity == warning AND provenance == INTRODUCED AND
NOT baselined` (§5 X16): three axes, three jobs — severity blocks, provenance attributes, `baselined`
suppresses noise.

### 4.2 The diagnostic returned to an authoring agent

This is the critical DX surface. One function feeds the console and the JSON, so they cannot
disagree (OUT6).

```python
@dataclass(frozen=True, slots=True)
class Finding:
    code: str                       # THE SYMBOL, e.g. 'OW_TARGET_BLEND_REQUIRES_BAKE'
    severity: Severity              # decides whether it BLOCKS
    provenance: Provenance          # decides who OWNS it and which fix command prints
    rule: str                       # "pptx.style.blend@1"  — id@version
    unit: str                       # "u03"
    msg: str
    fix: str                        # THE EXACT COMMAND. NEVER EMPTY — __post_init__ raises.
    at: str | None = None           # "il/u03.svg:41:9"
    el: str | None = None           # a data-ow-el address, "u03/e17"
    construct: str | None = None    # the ConstructTable row id
    canonical: str | None = None    # REQUIRED iff the construct's disposition is NORMALIZE
    count: int = 1                  # FOLDED occurrences
    examples: tuple[str, ...] = ()  # <= 3, ASSERTED
```

**Folding** (OUT7). `FindingSet.fold()` groups on `(code, rule, unit, canonical)`, sums `count` and
keeps at most three `examples`. Two hundred lowercase hex colours on one slide are **one** finding
with `count = 200`, not 200 lines an agent must scroll past. The key includes `unit` so a per-unit
fix stays per-unit, and includes `canonical` so two different replacement values do not merge into
one ambiguous recommendation. §14.3 gives the second fold that bounds a 2000-unit roster.

**The console render**, which is what an agent actually reads — one block per folded finding, sorted
by `(severity, unit, code)`:

```
ow out check --target pptx --stage final
gate: failed   (3 blocking · 2 introduced warnings · 1 skipped check · il_digest sha256:9a02…)

E OW-T-401  u03/e17  il/u03.svg:41:9   x1
  <script> has no DrawingML mapping; executable content in an authored artefact
  construct: elem.script   provenance: introduced
  fix: remove <script> from il/u03.svg   (see `ow out constructs pptx --construct elem.script`)

E OW-T-402  u07/e04  il/u07.svg:12:3   x1
  id= is only hazardous paired with <style>; id is REQUIRED inside <defs>
  construct: attr.id   provenance: inherited  (template: asset-slot:9f3a1c04, unit u07)
  fix: remove <style> from il/u07.svg, or drop id= outside <defs>

E OW-T-102  u05/e31  il/u05.svg:88:5   x1
  cite d7#412 is kind="quote" but nfc(visible_text) != nfc(block.text[411:503])
  construct: ow:cite   provenance: introduced
  fix: ow open d7#412 --raw   and copy the exact span, or set kind="paraphrase"

W OW-T-210  u02      il/u02.svg:19:14  x200
  fill is not uppercase hex
  canonical: #RRGGBB with uppercase hex digits   provenance: introduced
  examples: fill="#3a7bd5" | fill="#ffffff" | fill="#0d1b2a"
  fix: ow out normalize --target pptx --construct attr.fill.lowercase-hex

I OW-T-003  -        -                 x1
  rule pptx.text.overflow@2 needs "measure"; uharfbuzz is not importable
  provenance: framework
  fix: uv pip install 'omniweave-target-pptx[measure]'   (the gate stays `unverified` until it runs)

3 blocking. Release refused: gate = failed.
Clear with: ow out check --target pptx --stage final --json      (exit 8)
```

Five properties of that shape, each with a mechanism behind it:

1. **Every finding carries an element address, a `file:line:col`, or both.** `el` is the durable
   anchor and survives a reflow; `at` is the convenience and does not. A finding with neither is a
   `scope = "document"` rule and prints `-`.
2. **`fix` is a command, never advice.** `__post_init__` raises on an empty `fix`. A rule author who
   cannot write the command has not finished the rule. A conformance check additionally resolves the
   first token of every `fix` against the Action registry and the `uv pip install` grammar, so a
   `fix` naming a verb that does not exist fails the kit rather than the user.
3. **`x<count>` is the fold count** and `examples` shows at most three. An agent fixing 200 hex
   colours needs the pattern, not the list.
4. **`provenance: inherited` names the template.** The message answers "is this mine?" without the
   agent guessing, and the ppt-master evidence is that without it nobody reads the report.
5. **The trailer prints the exact command that clears the status and the exit code** — required of
   every non-`passed` `GateStatus` (OUT5).

**The JSON report** — schema `omniweave.out-report/1`, written to `validation/<stage>.json`.
Per-stage filenames are distinct so a diagnostic run cannot overwrite the release gate's report; this
copies ppt-master's four-way `report_name` map (`svg_quality/cli.py:87-107`) exactly, and the reason
matters enormously: the release gate reads exactly one filename and no diagnostic run can accidentally
produce it.

```jsonc
{
  "schema": "omniweave.out-report/1",
  "stage": "final",                       // early | first-unit | unit | final
  "target": "pptx",
  "constructs_digest": "sha256:71c4…",
  "il_digest": "sha256:9a02…",            // BINDS THE REPORT TO BYTES (OUT4)
  "il_files": [ {"name": "il.toml", "sha256": "…"},
                {"name": "u01.svg", "sha256": "…"},
                {"name": "u02.svg", "sha256": "unreadable", "error": "…"} ],
  "summary":  {"units": 12, "clean": 9, "warned": 2, "blocked": 1},   // UNITS, one bucket each
  "counts":   {"error": 3, "warning": 2, "info": 1},                  // FINDINGS
  "by_provenance": {"introduced": 4, "inherited": 1, "imported": 0, "framework": 1},
  "introduced_warning_count": 2,
  "findings": [ /* folded Finding records, exactly the dataclass fields */ ],
  "skipped_checks": [                     // REQUIRED, non-null (OUT3)
    {"rule": "pptx.text.overflow@2", "needs": "measure", "reason": "uharfbuzz not importable"}
  ],
  "truncations": [],                      // REQUIRED, non-null. See section 14.3
  "restricted_items": [],                 // cites and asset ids barred by restriction_bits (OUT11)
  "manual_units": [],                     // units carrying an ow:manual region, with the reason
  "markers": [ {"el": "u03/e17", "id": "k-1a2b3c4d", "state": "pending"} ],
  "portability": {                        // NOT validity. See section 5.3.
    "generic_only_font_stacks": [], "unresolved_brief_tokens": [],
    "external_asset_refs": [], "unsafe_exported_faces": []
  },
  "rule_timings_ms": {"pptx.style.blend@1": 4, "pptx.text.overflow@2": 0},
  "gate": {"status": "failed", "introduced_warning_count": 2, "exit": 8,
           "fix": "ow out check --target pptx --stage final --json"}
}
```

`summary` counts **units**, each landing in exactly one bucket; `counts` counts **findings**. Two
different denominators, both reported — ppt-master reports both (`checker.py:1407-1421`) and the
distinction is what stops "3 errors" being read as "3 broken slides".

`restricted_items`, `manual_units` and `truncations` are the three fields `gate_status()` reads and
the three the draft contract would otherwise have referenced without defining. All three are required
and non-null: an absent list and an empty list must not be the same value to a gate that fails
closed.

**`skipped_checks` is required and non-null (OUT3).** A check that could not run is visible and the
gate becomes `unverified`, never `passed`. `omniweave-conform` removes `uharfbuzz` from the
environment and asserts both halves: the entry appears, and the gate is not `passed`. This
generalizes ppt-master's best failure mode — `check_paint_compatibility` degrades to a warning when
the compiler's parsers cannot be imported, rather than silently passing or crashing.

### 4.3 Four stages, three verbs, three questions

hyperframes separates `lint` / `check` / `snapshot` because static validity, semantic validity and
visual regression are three different questions. omniweave maps them onto its own locked verb tree
rather than adding verbs — the CLI grammar admits no aliases and G25 forbids a group below three
verbs:

| question | invocation | reads | writes | fails on |
|---|---|---|---|---|
| **static validity** — is this the declared IL subset? | `ow out check --stage early` | the IL text plus `constructs.toml` | `validation/early.json` | any `error`; exit 8 |
| **semantic validity** — is this a valid *unit of this target*? | `ow out check --stage final` | the above plus the `Brief`, the `Plan`, the `CiteResolver` and `measure()` | `validation/final.json` | any `error`, a missing unit, an unresolved cite, an overflowing text box; exit 8 |
| **visual regression** — does it still look the same? | `ow out verify --class render` | the artefact plus its retained IL bundle | the receipt's `determinism` block | a sampled paint-tree or measured-layout difference against the golden at the declared `render` class; exit 8 |

`ow out check` is one command with a `--stage` because it is one rule runner over one report schema;
the stages differ in which `RuleSpec`s are eligible and in the structural completeness required.
`ow out verify` is a different command because it consumes an artefact rather than an IL bundle and
because `render`-class comparison is pinned to a toolchain digest. D766 lands `ow out check --stage S [--unit U] [--job DIR] [--target T]`, a CLI-only Action over D749's `check()`. The JobDir is `--job`, else `cwd`. Its `job.json` gives the target, the corpus, the Brief and the roster. The compiler is the target's own class, built through `host.activate.construct()`. `early`, `first-unit` and `unit` read the IL and the table; `final` adds the Brief, the Plan's roster and a `CiteResolver` over the corpus store, opened read-only. `final` exits as `gate_status()` decides. A non-final stage exits 8 on an error and 0 otherwise, as this section's table says, while its report's gate stays `non-final`. Found: this document's fix commands print `--json`, which the CLI does not parse. The global flag is `--render json` (18:889), so `gate.py` and the truncation finding now print that.

**Four stages, one per report path**, following ppt-master's `report_name` map:

| `--stage` | roster requirement | eligible rules | report path | `gate_status` |
|---|---|---|---|---|
| `early` | every unit authored so far, ≥ 1 | every rule whose `RuleSpec` does not declare `final_only` | `validation/early.json` | `non-final` |
| `first-unit` | exactly `u01` | the same | `validation/first-unit.json` | `non-final` |
| `unit` | exactly the `--unit` argument | the same | `validation/unit.json` | `non-final` |
| `final` | the **complete** declared roster, all three lists agreeing (§3.2) | every rule | `validation/final.json` | any of the ten |

`first-unit` and `unit` are diagnostic stages: `first-unit` is the cheapest possible calibration
before an agent commits to a method, and `unit` is what an agent runs after fixing one unit without
paying for the whole roster. Neither can produce a releasable report, because `gate_status()` returns
`non-final` for any `stage != "final"` before it looks at anything else.

**Two gates, and why there are two** — following ppt-master's measured design:

- `--stage early` runs after the **first five units** and treats them as a *method sample*. It
  classifies the whole issue set into **method-level** (the approach is wrong and will recur on every
  unit), **unit-local** (a one-off) and **not-yet-exercised** (a construct the sample never used, so
  its correctness is unknown), then fixes every blocking error and selected warnings in **one
  consolidated loop**. Only method-level issues justify changing how the remaining units are
  authored. Rosters of six or fewer units skip it.
- Between the early gate and the final gate there are **no checker calls**. Running the validator per
  unit is the obvious design and it is rejected for a stated economic reason: each call is a tool
  round-trip in the agent's context window, and the early gate has already calibrated the method.
  `--stage unit` exists for the *repair* loop, not the authoring loop, and the skill says so.
- `--stage final` requires the **complete declared unit roster** from the `Plan`. It is the only
  stage whose report the release gate reads.
- The gate runs **before** any post-processing that rewrites IL (icon embedding, asset inlining),
  because post-processing masks source-level violations.

**`ow out stamp` and `ow out normalize`, specified** — the two commands that exist because the
validator may not write (OUT20):

| command | reads | writes | idempotent | exit |
|---|---|---|---|---|
| `ow out stamp` | every IL file under `il/` | `data-ow-el` on every citable and text-bearing element **that has none**; never renumbers an existing one (OUT21) | yes | 0; 70 if a reparse fails, having written nothing |
| `ow out normalize` | `validation/<stage>.json` plus the IL | the `normalizer` of each `normalize`-disposition finding, applied through `CarrierDoc.splice()` | yes, asserted per normalizer (§3.4 assertion 2) | 0; 70 on a normalizer or reparse failure, having written nothing |

Both recompute `il_digest` before doing anything and refuse on a mismatch with the report they were
given — a normalize run against a stale report edits offsets that moved. Both write through the same
transactional splice as the marker applier: sort descending by offset, apply, reparse, all-or-nothing,
then `os.replace()` the temp file over the original so a crash mid-write leaves the original intact.
Both **move `il_digest` by construction**, so the standing report becomes `stale` and the command's
last line is the re-check invocation. `ow out normalize` on a clean bundle writes nothing and says so. D768 builds `omniweave_core.out.normalize.normalize()` and `ow out normalize [--stage S] [--unit U] [--construct ID] [--job DIR]`. A finding is folded, so the report cannot list every occurrence: it chooses which `normalize` rows run, and the current IL says where. That is also why no offset in the report is read. With `--stage`, the report must exist and its `il_digest` must be the bundle's (`OW-T-523`). Without it, every normalize row runs. An attribute's quoted value is rewritten and escaped for its quote. An element row, a style sub-property row (not built), an unquoted attribute, a normalizer that does not settle, and a unit that does not reparse are `OW-T-524`, with nothing written. The normalizers are the target's own `normalizers.py`, loaded by `host.activate.normalizers()`. 09's positional IL path is the `--unit` option, since a positional cannot be optional in the generated grammar. Found: the API sketch's owtext fixes name `--drop` and `--scope-styles`. Those rewrite forbidden constructs, which OUT20 rules out, and no CLI parses them. owtext's fixes now name `ow out constructs owtext --construct <id>` and `ow out normalize --unit <id> --construct attr.class.upper`.

`ow out stamp` takes an exclusive `il/.stamp.lock` (O_CREAT|O_EXCL, holding pid and start time, stale
after 300 s) because the per-unit `e` counter is `max(existing ordinal) + 1` and two concurrent
stampers would both mint `e17`. D767 builds `omniweave_core.out.stamp.stamp()` and `ow out stamp [--job DIR]`. It stamps an element with no address that bears visible text or carries `data-ow-cite`, except a tag the table ignores. An address is `<unit>/e<N>`, counting up from the unit's largest ordinal in document order. It goes before the start tag's `>` or `/>`, through `CarrierDoc.splice()`. Every unit is reparsed before any file is written, so one unit that does not reparse is `OW-T-522` and nothing is written. Each file is replaced through a dot-file sibling, which `ILBundle` never counts. The lock holds the pid and the injected clock's start time: a lock younger than 300 s is `OW-T-521`, and an older or unreadable one is replaced and reported.

### 4.4 `RuleSpec`, `RuleCtx`, `DocIndex` and the rule runner

```python
@dataclass(frozen=True, slots=True)
class RuleSpec:
    id: str                            # "pptx.style.blend@1" — id@version
    order: int                         # the phase. ORDER 0 IS THE CARRIER PARSE and SHORT-CIRCUITS.
    scope: Literal["document", "unit", "node"]
    codes: frozenset[str]              # every SYMBOL this rule MAY emit; the meta-gate checks BOTH ways
    fn: Rule                           # REQUIRED. `fn: Rule = ...` binds Ellipsis — neither required
                                       #   nor defaulted, and every consumer then type-checks against
                                       #   EllipsisType. There is no `= ...` in a shipped shape.
    needs: frozenset[str] = frozenset()  # {"measure","cites","assets"}; an unmet member yields a
                                         #   FRAMEWORK info finding and the gate becomes `unverified`
    final_only: bool = False             # skipped at every stage except `final`

class RuleCtx(Protocol):
    doc: CarrierDoc | None             # None iff scope == "document"
    unit: OutUnit | None               # None iff scope == "document"
    plan: Plan; constructs: ConstructTable; brief: Brief
    index: DocIndex                    # ALWAYS populated. The only thing a document rule sees.
    cites: CiteResolver                # by_cite()/by_cites() ONLY. No writes, no store handle.
    limits: Mapping[str, int]          # occurrence budgets, e.g. undeclared_size_max = 2
    def measure(self, n: CarrierNode) -> Box | None: ...   # None => A RECORDED SKIP, never a pass

Rule = Callable[[RuleCtx], Iterable[Finding]]

@dataclass(frozen=True, slots=True)
class DocIndex:
    """Everything a document-scope rule may know, built incrementally during the unit pass.
    Bounded by the roster, NEVER by the node count: one entry per unit, plus per-unit counters."""
    units: tuple[str, ...]                              # in roster order
    els: Mapping[str, frozenset[str]]                   # unit -> the el addresses stamped in it
    nsigs: Mapping[str, str]                            # el -> nsig
    construct_counts: Mapping[str, Counter[str]]        # unit -> construct id -> occurrences
    cites: Mapping[str, frozenset[str]]                 # unit -> cite tokens
    slots: Mapping[str, frozenset[str]]                 # unit -> asset-slot digests
    markers: tuple["Marker", ...]
    value_occurrences: Mapping[str, Counter[str]]       # e.g. "type_size" -> value -> count
```

**`Box` and `TextMeasure`, printed.** They are the two shapes a `pptx` or `docx` target author
implements against, and the reference target's `measure = "none"` exercises only their *absence*
([the API sketch](18-api-sketch.md) §6.2), so a forward reference here leaves the whole `order`
60-79 band unwritable. Both live in `omniweave_core/out/rules.py` beside `RuleCtx`, the only
framework object that references either — two names added to an existing module in the charter's
inventory, no new module.

```python
# omniweave_core/out/rules.py
@dataclass(frozen=True, slots=True)
class Box:
    advance: float      # advance width of the laid-out content
    height: float       # total laid-out height: ascent + descent + (lines - 1) * leading
    ascent: float       # above the FIRST baseline
    descent: float      # below the LAST baseline, POSITIVE downward
    lines: int          # laid-out line count; 1 for a single positioned line
    overflow: bool      # the content exceeded the geometry declared ON THE MEASURED NODE

class TextMeasure(Protocol):
    def box(self, n: CarrierNode) -> Box | None: ...   # the ONE method RuleCtx.measure delegates to
```

Six fields, one per question the 60-79 band asks (text capacity, overflow, off-canvas — the band
table below). `advance` and `height` answer capacity; `ascent` and `descent` answer off-canvas,
because a first line's ascent is what crosses the top edge of a canvas and a last line's descent the
bottom; `lines` answers "did this wrap inside a box declared for one line"; `overflow` is the
estimator's own verdict against the geometry it read off the node it was handed, which is why the
method needs no second argument. There is no `fits()` predicate: a predicate would move the capacity
decision out of the rule — which owns the `Finding`, its `fix` and its model statement — and into the
estimator, where nothing can review it.

**One declared unit: IL user units.** A `Box` is expressed in the coordinate system the measured
unit's own geometry constructs are written in, and `Box` performs no conversion:

| carrier | the IL user unit a `Box` reports in |
|---|---|
| `svg` (`owsvg/1`) | the unit `<svg>` root's `viewBox` coordinate system (§12.1) — the same numbers an `x`, `y` or `width` attribute carries |
| `html` (`owdeck/1`, `owflow/1`) | CSS px, exactly as the Toolchain child's `getBoundingClientRect` reports them (§12.2) — the unit the declared page box is itself declared in |

That is what puts a `uharfbuzz` estimator and a browser-child estimator into one space: a capacity
rule compares a `Box` against geometry it read off the same node with `n.attr(...)` and needs no
conversion table to do it. EMU appears exactly once, in `lower/`'s serializer, where geometry becomes
integers and no `repr(float)` reaches the XML (§6, and [architecture](02-architecture.md)'s compile
walkthrough, step 8); device pixels appear nowhere. A rule never renders a raw `Box` float into a
`msg` or an `examples` entry — it rounds to whole IL user units first — because a report is compared
byte for byte by the golden gates and `repr(float)` is not portable across the nine platform cells.

**Two different `None`s, both recorded skips, neither a pass.** `CompileV1.measure() -> None` means
the target has no estimator at all: every `RuleSpec` declaring `needs={"measure"}` yields one
`Provenance.FRAMEWORK` `info` finding and the gate is `unverified`. `TextMeasure.box(n) -> None`
means *this node* is unmeasurable — no resolvable face, or no declared geometry to measure against —
and `RuleCtx.measure(n)` passes it straight through, so the rule emits nothing for that node and the
framework records one skip naming the rule and the `el`. Where a capacity decision was actually
required, that is `ManualReason.MEASUREMENT_FAILED` (§9), never "assume it fits".

**OUT2 becomes checkable rather than claimed.** The framework's `mk_ctx` closes over whatever
`CompileV1.measure()` returned, once per compile, and `RuleCtx.measure(n)` is exactly
`m.box(n) if m is not None else None` — one wrapper, no second code path, and a wrapper that could
not have been written while the method had no name. `lower/` holds a `Plan` and an `ILBundle` and
never receives a `CarrierNode`, so it reaches the same call the way the reference target's `lower()`
already does: it parses the unit itself through the target's own
`carrier(unit.il_path, il.text(unit.il_path))` — the same parse function, over the same retained
bytes the validator read — and calls `self.measure().box(n)` on the resulting node. Two mechanical checks
then make "exactly one implementation, both callers" hold rather than being asserted: semgrep permits
exactly one module under a target to import a shaping or layout engine, and that module is
`measure.py` (§3.1 pt 4's one-parser rule, extended to the estimator); and the kit asserts `measure()`
returns the **identical object** on repeated calls within one driver instance, so a target that
builds a fresh estimator per call — the first step toward two — fails the kit.

`run_pack()` executes in two passes and **never holds more than one parsed unit**:

```python
def run_pack(pack: Mapping[str, Sequence[RuleSpec]], bundle: ILBundle,
             mk_ctx: Callable[[OutUnit, CarrierDoc, DocIndex], RuleCtx]) -> FindingSet: ...
#  pass A: for each unit in roster order —
#            carrier(path, text) at order 0; on failure record the finding and SKIP the unit's
#            remaining rules (the short circuit), then continue to the next unit;
#            run every rule of scope unit|node with order 1..89 sorted by (order, id);
#            fold the unit's findings, merge the unit's contribution into DocIndex, DROP the tree.
#  pass B: run every rule of scope "document" (order 90..99) against one RuleCtx whose
#            doc and unit are None and whose index is the completed DocIndex.
```

**Order 0 is the carrier parse and it short-circuits**: a malformed IL file fails before construct
compatibility matters, and every later rule assumes a parsed tree. ppt-master's sequence has the same
shape and the same stated reason — *"Parse XML once — every other check assumes the file is valid
XML. Bail early on failure so the regex-based checks below don't produce misleading errors"*
(`svg_quality/checker.py:1253-1400`). The short circuit is **per unit, not per run**: one unreadable
unit must not hide the other eleven, and `il_digest` already records the unreadable file explicitly.

Shipped phase bands, so a third-party rule author knows where to sit:

| `order` | band | scope | example |
|---|---|---|---|
| 0 | carrier parse | unit | well-formedness; short-circuits the file |
| 10-19 | structural contract | unit | the unit root, `ow:unit`, the canvas/viewBox, `data-ow-el` presence and uniqueness |
| 20-39 | construct conformance | node | one rule per ConstructTable disposition class |
| 40-59 | grammar and value | node | path data, transforms, colour, length and opacity grammars |
| 60-79 | measurement | node | text capacity, overflow, off-canvas — every rule here declares `needs={"measure"}` |
| 80-89 | cross-reference | unit | `ow:cite` resolution and verbatim proof (`needs={"cites"}`); `asset-slot:` resolution (`needs={"assets"}`) |
| 90-99 | document-scope | document | Brief conformance, the no-generated-alias rule, roster completeness, marker inventory, cross-unit occurrence budgets |

The band table is also the reason `DocIndex` carries `value_occurrences`: ppt-master's
"third undeclared type size is an error" is a **cross-element** budget, and once the runner drops
each tree it can only be evaluated at order 90 against a counter, not at order 40 against a tree.
That is a better place for it anyway — a per-unit rule cannot see the third occurrence when the
first two were on other slides.

`run_pack()` records per-rule wall time into `rule_timings_ms` and enforces
`MAX_FINDINGS_PER_RULE` (§14.1).

**`measure()` returning `None` is a recorded skip, never a pass.** The rule emits nothing, the
framework emits one `Provenance.FRAMEWORK` `info` finding naming the rule and the unmet need, and the
gate becomes `unverified`. A rule must also **state the scope of what it models in its own output** —
ppt-master's round-trip capacity scan prints *"single-line width per positioned line; vertical
wrapping is not modeled"*, which prevents a reader concluding "text fits" from "no findings". A
measurement rule whose `msg` does not state its model is a review rejection, and the kit greps for
the model statement in every rule declaring `needs={"measure"}`.

**The validator and the compiler share one estimator.** `measure.py` is imported by both `rules/` and
`lower/`. There is exactly one implementation of "how wide is this text at this size in this font",
and the checker asks it. A second independent implementation drifts and produces the "checker passed,
compiler failed" class of bug the gate exists to prevent (OUT2).

**The validator never rewrites the IL** (OUT20). Semgrep bans a write under `il/` from `rules/`.
`ow out stamp` and `ow out normalize` are separate commands with their own exit codes (§4.3).
**There is no `--fix`.** D742 builds `omniweave_core.out.rules`: `RuleSpec`, refused outside its scope's band, so order 0 stays the framework's. It also builds `RuleCtx`, `DocIndex`, `Box`, `TextMeasure` and `run_pack()`. That takes the target's carrier as an argument, because pass A calls it and 09's signature does not hand it over. A parse refusal, or a recovering read with problems, is one `OW_TARGET_IL_MALFORMED` (`OW-T-400`) a problem, and the unit's rules are skipped. A forged provenance raises `OW-T-004` and stops the run. A rule that raises is one framework `OW_TARGET_RULE_RAISED` (`OW-T-010`) error and the run goes on. `MAX_FINDINGS_PER_RULE` is per rule across the run, recorded as a `rule` truncation. An unmet need is one skip a rule, with the target's per-need fix. `DocIndex` fills `els`, `cites`, `slots` and `construct_counts`; `nsigs`, `markers` and `value_occurrences` stay empty until their cells.

### 4.5 `GateStatus` — ten values, one release, one order

```python
class GateStatus(StrEnum):
    NOT_PROVIDED="not-provided"; UNREADABLE="unreadable"
    UNSUPPORTED_SCHEMA="unsupported-schema"; NON_FINAL="non-final"
    UNVERIFIED="unverified"; FAILED="failed"; STALE="stale"
    RESTRICTED="restricted"; MANUAL_REQUIRED="manual-required"; PASSED="passed"

def gate_status(report: "OutReport | None", il_digest: bytes) -> tuple[GateStatus, int]:
    if report is None:                             return NOT_PROVIDED, 0
    if report.unreadable:                          return UNREADABLE, 0
    if report.schema != "omniweave.out-report/1":  return UNSUPPORTED_SCHEMA, 0
    n = report.introduced_warning_count
    if report.stage != "final":                    return NON_FINAL, n
    if report.il_digest != il_digest:              return STALE, n        # BYTES BEFORE CONTENT
    if report.counts["error"] > 0:                 return FAILED, n
    if report.skipped_checks or report.truncations: return UNVERIFIED, n
    if report.restricted_items:                    return RESTRICTED, n
    if report.manual_units:                        return MANUAL_REQUIRED, n
    return PASSED, n
```

`OutReport.load(path)` returns `None` when the file is absent and an `OutReport` with
`unreadable = True` and every other field zeroed when the file exists and does not parse — so
"no gate" and "a broken gate" reach `gate_status()` as different values rather than as one exception.
`OutReport.il_digest` is **`bytes`**, decoded from the report's `"sha256:…"` hex at load time, so the
comparison against the freshly computed digest is a bytes comparison and not a str-vs-bytes
comparison that is unequal for every input.

**The order is part of the contract, and each step is justified by the step below it being
unreadable without it:**

| rank | status | why it outranks everything below |
|---|---|---|
| 1 | `not-provided` | there is nothing to read |
| 2 | `unreadable` | there are bytes but no fields |
| 3 | `unsupported-schema` | there are fields but their meaning is another version's |
| 4 | `non-final` | the fields are valid but describe a partial roster; a partial roster's error count says nothing about the whole |
| 5 | `stale` | the report describes **different bytes**. Its `at` addresses point at lines that moved and its `fix` commands are unrunnable, so reporting its error count would send an agent to edit the wrong place. ppt-master checks blocking first; omniweave does not, and this is a deliberate divergence |
| 6 | `failed` | a known error against the current bytes is actionable now, and outranks a check that did not run |
| 7 | `unverified` | a check could not run, or a rule's output was truncated; the absence of a finding proves nothing |
| 8 | `restricted` | every check ran and passed, and policy refuses the bytes |
| 9 | `manual-required` | nothing is wrong; a human has work to do |
| 10 | `passed` | the only value that permits a release |

| status | means | the command that clears it |
|---|---|---|
| `not-provided` | you never ran the gate | `ow out check --target T --stage final --json` |
| `unreadable` | the report exists and does not parse | delete `validation/final.json`, re-run check |
| `unsupported-schema` | a report from another schema version | re-run check with the current `ow` |
| `non-final` | an `early`, `first-unit` or `unit` report offered as a release gate | `ow out check --stage final` |
| `stale` | the report's `il_digest` ≠ the bundle's | re-run check against the current IL |
| `failed` | errors found | fix them; each finding names its own `fix` |
| `unverified` | a check could not run, or a rule truncated | install the named extra, or fix the truncating rule, then re-check |
| `restricted` | a restricted cite or asset is in the artefact | `ow out assets --explain`, or a policy grant |
| `manual-required` | a unit needs a human | `ow out compile --accept-manual` (a **draft**) |
| `passed` | the only value that permits a release | — |

`not-provided` is **not** `failed`: "you never ran the gate" and "you ran it and it found errors" are
different user errors needing different messages. `passed-with-warnings` is a **report** status and
never a gate status. There is no `--force` and no `--no-gate`; a test asserts the other nine are
refused with a distinct message **and** a fix command (OUT5).

The gate **binds to bytes** (OUT4):

```
il_digest = sha256 over, for each file under il/ SORTED BY BASENAME (il.toml included):
              name ‖ 0x00 ‖ hex(sha256(bytes)) ‖ 0x0A
```

Sorted by **basename**, not path, so moving the job directory does not change the digest. An
unreadable file contributes the literal string `unreadable` **and** an error row — it never silently
drops out, which would make an unreadable file invisible to the comparison. The framing is
ppt-master's, verbatim (`checker.py:9335-9368`). One Python implementation; the Toolchain's
TypeScript recomputation is spec'd in `schema/il-digest-v1.md` with a cross-language parity fixture,
and it is the one form of duplication D1 sanctions. D737 builds sections 4.1, 4.2, 4.5 and 14.3's fold in `omniweave_core.out`: `finding` (`Severity`, `Provenance`, `Finding`, `FindingSet.fold()`), `gate` (`GateStatus`, `gate_status()` as printed, each refusal's meaning and command, section 15's exits), `job.ILFile` and `report` (`il_digest()`, `OutReport` with `build`, `load` and `write`, and `render()`, which reads only the JSON). The fold key is section 4.2's four fields split by severity and provenance, because a merge across either would move a blocking count or an owner. A re-folded finding carries `units_affected` and `unit_examples`, section 14.3's two fields that 4.2's list had no place for. The framework mints a skipped check's and a truncation's findings itself, so 4.1's `info`/`framework` cell holds by construction. `il/` is read flat, and a dot-file (`.stamp.lock`) is not IL.

## 5. The compiler contract

### 5.1 Preflight

`lower()` receives an already-gated `Plan`, so `lower()`'s preflight is not a second validation pass;
it is the set of assertions the compiler needs and the validator cannot make because they are about
the *lowering*, not the source. Five checks, in order, each raising `DriverError` with an `OW-T-*`
code:

| # | preflight check | code | why it cannot live in the validator |
|---|---|---|---|
| 1 | every `maps_to` symbol referenced by the units in this `Plan` resolves in the loaded `lower/` | `OW_TARGET_CONSTRUCT_UNMAPPED` | resolution depends on the installed target version, not the IL |
| 2 | every `asset-slot:<sha256>` in the bundle has a frozen `AssetLedger` row with a non-NULL `store_ref` | `OW_TARGET_ASSET_UNFROZEN` | freezing is a store-side act the validator has no handle for |
| 3 | the three rosters agree: `plan.units`, `il.toml`'s rows, the files on disk | `OW_TARGET_ROSTER_MISMATCH` | the Plan's roster is not the bundle's, and the validator only sees the bundle (§3.2) |
| 4 | `[compile] max_units` is not exceeded | `OW_TARGET_TOO_MANY_UNITS` | a card limit, checked against the plan |
| 5 | `bake` is reachable for every unit whose classification is `baked` | `OW_TARGET_BAKE_UNAVAILABLE` | `bake = "unavailable"` is a card fact plus a probe fact |

Preflight failures are **`DriverError`**, not `Finding`s: they are raised, not recorded, because the
compile cannot proceed and there is no report to append to. `Diag` is recorded; `OwError` is raised;
two names for two things (§6.5).

### 5.2 The mapping table, and the one estimator

`maps_to` is the whole mapping table: a `native` row names exactly one lowering symbol, one lowering
symbol is named by at least one row, and OUT1 checks both directions in CI by importing `lower/` and
diffing its public symbol set. There is no dispatch dictionary maintained by hand and no `getattr`
on a construct id.

The `pptx` target's `lower/` decomposition, given as the reference shape:

```
lower/
├── drawingml/   shape, paint, path, transform, text-body, effect  — one module per DrawingML family
├── charts.py    XlsxWriter-backed chart parts
├── boolean.py   skia-pathops path booleans, for constructs DrawingML has no operator for
├── media.py     media parts and their relationships; bake output lands here as a picture part
└── pack.py      the part graph, then write_opc()
measure.py       uharfbuzz shaping — IMPORTED BY BOTH rules/ AND lower/   (THE WHOLE POINT)
normalizers.py   the pure str -> str functions a `normalize` row names
```

**Why ~180 rows is not ~180 rules.** A rule is one predicate over a *family*, not one predicate per
row: the colour-grammar rule covers every row whose value grammar is a colour, and the disposition
rules cover a whole disposition class at once. The `pptx` pack is therefore ~60 rule files over ~180
rows — one file, one function, one test, per the RulePack lock definition — and the ratio is the
measure of whether the table is factored. A table needing one bespoke rule per row is a table whose
`selector` grammar is too weak.

### 5.3 Package validation, and the rule that file creation is not proof

The compiler **independently re-verifies** the package it produced. This is not theatre: ppt-master's
postflight raises `PptxPostflightValidationError` on a ZIP-integrity failure or a slide-count
mismatch (`svg_to_pptx/pptx_package/cli.py:1388-1535`), and the layer table states the compiler's
job as *"defensively validate compiler mappings and the package … It does not rerun the complete
`svg_quality_checker.py` or treat file creation as proof that the upstream quality gate passed."*

`postflight(artifact, plan) -> Receipt`. Hard preconditions that raise rather than record:

| precondition | code |
|---|---|
| container integrity — every member decompresses | `OW_TARGET_PACKAGE_CORRUPT` (names the member) |
| output unit count equals `plan.unit_count` | `OW_TARGET_UNIT_COUNT_MISMATCH` (prints both numbers) |
| every relationship target resolves to a member that exists | `OW_TARGET_DANGLING_REL` (names the rel and the target) |
| every declared content type covers a present part | `OW_TARGET_CONTENT_TYPE_GAP` |

The `Receipt`:

```python
@dataclass(frozen=True, slots=True)
class CheckValue:
    name: str                  # ^[a-z][a-z0-9_]{2,39}$ — "zip_integrity", "slide_count",
                               #   "measure_available". Target-chosen, and UNIQUE within one
                               #   `Receipt.checks`: `Receipt.__post_init__` raises on a duplicate,
                               #   because `verify` and the golden gates read a check BY NAME.
    value: Literal["passed", "warning", "failed", "enforced-at-build",
                   "not-applicable", "skipped"]
    detail: str | None = None  # free text, and the only place a number belongs
    fixture: str | None = None # REQUIRED IFF value == "enforced-at-build": the kit test that proves
                               #   the claim by mutating the builder and asserting it raises. Without
                               #   it the claim is unfalsifiable, which is the exact failure the
                               #   `enforced-at-build` value exists to avoid. __post_init__ raises
                               #   on the IFF in either direction.

@dataclass(frozen=True, slots=True)
class Receipt:
    schema: Literal["omniweave.out-receipt/1"]
    target: str; slug: str; artifact_gen: int
    output: Mapping[str, int | str]           # {"path": …, "bytes": …, "sha256": <hex>}
    part_digest: str                          # HEX. artifact.part_digest is the BLOB of these bytes
    determinism: tuple[ArtefactDeterminism, ...]   # the SET, as compiled
    gate_status: GateStatus
    delivery: Literal["release", "draft"]
    checks: tuple[CheckValue, ...]
    units: Mapping[str, UnitOutcome]          # unit -> outcome
    counts: Mapping[UnitOutcome, int]         # the sum is asserted == plan.unit_count
    portability: Mapping[str, tuple[str, ...]]
    normalizations: tuple[Mapping[str, str], ...]   # every rewrite the compiler performed
    degradations: tuple[Degradation, ...]
    skipped_checks: tuple[Mapping[str, str], ...]   # carried forward from the report
    truncations: tuple[Mapping[str, str], ...]      # carried forward from the report
```

**A `CheckValue` is not what a rule returns.** OUT has exactly two "a check said something" types and
they belong to two different stages: a `RulePack` predicate is `(RuleCtx) -> Iterable[Finding]` and
runs **before** the gate, against IL text; a `CheckValue` is a row of `Receipt.checks` and is written
by `postflight()` **after** `lower()`, against the produced artefact. Nothing that produces a
`Finding` may produce a `CheckValue` and nothing that produces a `CheckValue` may gate — §2's method
table forbids `postflight` from rerunning the validator, and
[the API sketch](18-api-sketch.md) §6.2's `postflight` docstring says it does not decide the gate.
The confusion is worth naming because it is the one that would otherwise be made: a receipt row that
could block would be a sixteenth gate, reachable only after the artefact exists.

**How the six values compose with `Severity` and `GateStatus`.** `Severity` decides blocking and
`Provenance` decides ownership (§4.1); a `CheckValue` decides neither, and this table is the whole of
the relationship, so that a reader never has to infer one from the other:

| `CheckValue.value` | the `Severity` a *rule* would have used for the same fact | effect on `GateStatus` | effect on `delivery` |
|---|---|---|---|
| `passed` | — | none | none |
| `warning` | `WARNING` | none — the gate was decided before `lower()` ran | none; it feeds the console receipt's `passed-with-warnings` |
| `failed` | `ERROR` | none. It is a **postflight** failure, and the four that must block are §5.3's hard preconditions, which **raise** `DriverError` and never reach a receipt | the compile has already raised; a `failed` row can only be written by `ow out verify` re-reading a sealed artefact |
| `enforced-at-build` | — | none | none. Requires `fixture` |
| `not-applicable` | — | none | none. The honest value for a check a card key disables (`measure = "none"`) |
| `skipped` | `INFO`, `Provenance.FRAMEWORK` | none **here** — the gate's own `unverified` comes from `OutReport.skipped_checks`, which is a different list carried forward into `Receipt.skipped_checks` | none |

The two rows with an empty severity column are the point: `enforced-at-build` and `not-applicable`
have no `Finding` equivalent at all, because a rule can only report something it observed and neither
of those is an observation. That is why the receipt needs its own vocabulary rather than reusing
`Severity`, and why the vocabulary is six values and not three.

Three properties of `CheckValue` worth stating explicitly:

- **`enforced-at-build` is a first-class value.** Some invariants are guaranteed by construction —
  `pack.py` cannot emit a dangling relationship because it builds the rel graph from the part graph —
  and re-verifying them postflight would be theatre. Saying so in the receipt is better than either
  omitting the row or faking a re-check. The kit checks the claim once, in CI, by mutating the part
  graph and asserting `pack.py` raises: an `enforced-at-build` row with no such fixture fails the kit.
- **`portability` is a separate axis from validity.** A generic-only font stack, an unsafe exported
  face, an external asset reference, an unresolved `Brief` token: none of these makes the file
  invalid, and all of them make it break on someone else's machine. They are recorded, they are not
  errors, and they get their own block rather than diluting `findings`.
- **`normalizations` is a ledger of what the compiler rewrote.** If the compiler is allowed to
  rewrite input at all, every rewrite must be (a) behind a named flag, (b) a structured record,
  (c) counted in the receipt. ppt-master's `normalize_single_child_group_filters` returns
  `{action, target_tag, filter}` per rewrite, gated behind `--dangerous-nonconforming-export`, and
  flips `export_policy.project_svg_contract` to `"strict-after-dangerous-normalization"`. omniweave's
  equivalent is `ow out compile --accept-normalization` — **extends the charter**: a new member of
  the named-override set, conforming to §6.4's `--accept-` convention for a named hazard, added
  because the charter's list has no override for a compile-time rewrite — whose effect is exactly one
  thing: each rewrite lands in `Receipt.normalizations` and one
  `Degradation(kind="compile_normalized")` lands on the artefact row. Without the flag, a
  `normalize`-disposition construct reaching `lower()` is `OW_TARGET_NORMALIZE_AT_COMPILE` — the
  validator warned, and `ow out normalize` was the fix.

The one-line console receipt, printed always, with the full JSON on disk:

```
[POSTFLIGHT] slug=q3-board gen=4 status=passed-with-warnings gate=passed units=12
             native=9 passthrough=2 baked=1 determinism=part,byte bytes=1843112
```

`status` here is the three-way **report** status, derived exactly as ppt-master derives it from seven
independent signals: `failed` if the gate failed; `passed` only if the gate passed **and**
`introduced_warning_count == 0` **and** every `portability` list is empty **and** `normalizations` is
empty; `passed-with-warnings` otherwise. It is never a gate status and never gates anything. D747 builds `omniweave_core.out.opc`: `write_opc(members)` in the canonical member order (`[Content_Types].xml`, `_rels/.rels`, then sorted), rather than a caller's, with every `ZipInfo` field pinned as `archive/owdoc.py` pins them and the package built in memory. It also builds `part_digest()` over parts, and `check_package()` and `check_unit_count()`, the four hard preconditions above, raised over the bytes produced. OPC's extension follows the segment's last dot, so `.rels` is extension `rels`, which `posixpath.splitext` reads as a hidden file. The `Receipt` comes next.

### 5.4 Purity: compile is a function of six digests

```
compile = f(il_digest, constructs_digest, ledger_digest, brief_digest, card_sha256, toolchain_digest)
```

Enforced as a **lookup-before-build** in `omniweave_core.out`, keyed on those six, reusing the prior
row's bytes and `part_digest` (OUT12). The unique index additionally carries `slug` and `delivery`,
because three cases the charter demands elsewhere are all "the same six digests, a second row":
`--accept-manual` producing a draft; a recompile after the gate clears; one IL compiled under two
slugs.

```sql
CREATE UNIQUE INDEX artifact_pure ON artifact(
  target, slug, delivery, il_digest, constructs_digest, ledger_digest, card_sha256,
  IFNULL(toolchain_digest, x''));
```

`gate_status` may advance **on a new `artifact_gen`** and never in place. A `BEFORE UPDATE/DELETE`
trigger refuses to modify a row with `sealed_at_ns` set (OUT24), which is what makes "OUT edits
always write a new `artifact_gen`" structural rather than a convention — and which settles
`ord_path` permanently: it stays rejected. `policy_digest` and `pricebook_digest` are
**decision**-key inputs and never artefact-key inputs. D750 ships `0005_out.sql`: `artifact`, `artifact_unit`, `artifact_asset`, `artifact_cite` and `artifact_el` as charter.md:6071-6155 prints them, `artifact_pure`, `artifact_cite_block`, and two triggers, `artifact_sealed_no_update` and `artifact_sealed_no_delete`, that refuse a sealed row with `OW-T-511 OW_TARGET_ARTIFACT_SEALED` (appended). `sealed_at_ns` is NOT NULL, so every row is sealed the moment it exists. The file is additive DDL and no SCHEMA minor (16-roadmap.md section 4's freeze). `artifact_cite_block`'s register owner, `09-generation`, now resolves to migration 5, so the index is checked rather than pending. Once a row exists, a doc or block an artefact cites cannot be deleted under the FKs as printed: `artifact_cite.block_id`, `artifact_el.block_id` and `artifact.read_back_doc_ord` carry no ON DELETE action.

**Two compiles racing on one slug.** The lookup-before-build is an optimisation and the unique index
is the authority; the two are not the same check, and treating them as one is how a duplicate row
appears under load. Three rules:

1. `artifact_gen` is **allocated by the INSERT**, not read beforehand:
   `INSERT INTO artifact(slug, artifact_gen, …) VALUES (:slug, (SELECT IFNULL(MAX(artifact_gen),0)+1
   FROM artifact WHERE slug=:slug), …)` inside one transaction. Two racers that read `MAX+1` and then
   insert both pick the same number; a racer computing it inside the INSERT does not, because SQLite
   serialises writers.
2. A `UNIQUE (slug, artifact_gen)` conflict is retried **once**, then fails with
   `OW_TARGET_GEN_CONTENDED` naming the winning generation. It is not retried in a loop: a second
   conflict means something other than a race.
3. An `artifact_pure` conflict is **not an error**. The loser re-reads the winner's row and returns
   it as a cache hit, exactly as `lookup_before_build` would have. Two identical compiles produce one
   row and both callers get it — which is only sound because `part_digest` equality is a proved CI
   invariant (OUT13), not an assumption. D751 builds `omniweave_core.store.artifact`, `SqliteArtifactStore` on the store thread, with these rules as its seal. The seal is one transaction: the artifact row, then `artifact_unit`, `artifact_asset` and `artifact_cite`. Rule 1's INSERT computes `MAX + 1` and writes only the generation the compile was planned under, because `Plan.artifact_gen`, the JobDir and the receipt name the generation before the seal. A compile that lost the race is `OW_TARGET_GEN_CONTENDED` naming the winner, so rule 2's one retry is the compile's re-plan, not the INSERT's. An identical compile is returned the winner's row as a hit, whether `artifact_pure` or the generation guard is what refused it. The seal also refuses a compile's cite with no block (`OW-T-101`), a `verbatim` row over a block that is not `VERBATIM` or that has no span (`OW-T-102`), and an asset join whose slot is not its asset's sha256 (`OW-T-506`). It ORs every source's `restriction_bits` into the row's. Two amendments to the DDL above, both in `0005_out.sql`. First, `artifact_pure` carries `IFNULL(brief_digest, x'')`: compile is a function of six digests and the printed index holds five, so two briefs over one IL would share a row. Second, the sealed-row trigger names every column but `read_back_doc_ord` in an `UPDATE OF` list, and `artifact_read_back_once` lets that column go from NULL to a document once. 02-architecture.md routes re-ingest on `read_back_doc_ord IS NULL`, which only works if `read_back` can set it after the seal. `close_loop()` is that write, together with the `artifact_el` rows.

The JobDir is `<cache_root>/jobs/<run_id>/<artifact_slug>@<gen>/` and is `run_id`-scoped, so two
concurrent runs never share a directory and no filesystem locking is needed below the store. D764 builds `omniweave_core.out.job.scaffold()` and `job_path()`. `job_path()` takes `<cache_root>` as given (the `roots.cache` key, for the verb to resolve), and the slug, which becomes a directory name and the plan never gives a grammar, is lower-case letters, digits and hyphens, 1 to 64 long (`OW-T-519`). The JobDir is staged beside its name and renamed in, so it exists whole or not at all, and a scaffold never writes over one (`OW-T-520`). The commissioned roster is the Brief's `## rhythm` rows, in numeric order with their anchors: section 3.2's "the Brief's unit count" has no other source. `il/il.toml` starts with no `[[unit]]` row, because a row with no file is `OW-T-507` and the early stage checks the units authored so far. The scaffolded Plan carries `not-provided`, no cites, and the digests of what the scaffold wrote. `SqliteArtifactStore.latest(slug)` is the generation the next scaffold proposes one past. D765 lands the verb, `ow out scaffold <target> --brief PATH --slug S [--corpus N]`, a CLI-only Action and the one Action that is not idempotent, because each call mints a run. Before it writes a byte, it resolves the corpus and its store, the one card and its table, the Brief (parsed against the table's baseline), the generation (one past the store's newest seal) and the slug's grammar. `<cache_root>` is `[roots] cache`, resolved against its declaring file as D527 resolves a corpus path. The run id, the trace context and `clock_ns` are minted at that edge. Found: 18 section 6.4 prints `ow out scaffold --target mytarget --carrier html --unit page` creating a target package. That is a second meaning for one verb, and the drivers group's rostered `ow drivers scaffold` is its home. `ow out scaffold` is the JobDir verb that 02 section 5 row 2 and 13.3 print.

### 5.5 Unit classification — the seven outcomes, defined

The charter fixes the enum and asserts totality; it does not say what the members mean, and R7 is
unimplementable until they are defined. They are, from ppt-master's measured classifier
(`svg_to_pptx/pptx_package/cli.py:2951-2990`, the counts printed at `:1265-1277`):

| `UnitOutcome` | definition | `reason` |
|---|---|---|
| `native` | the unit was lowered from IL to target primitives — the create path | — |
| `baked` | at least one construct in the unit took its `bake` degradation | **NOT NULL** |
| `passthrough` | the original container part was copied byte-for-byte into the output at the **same** output index; the copied part's sha256 is asserted equal to the source's | — |
| `cloned_passthrough` | copied byte-for-byte at a **different** output index — a roster reorder or a duplicated unit | — |
| `patched` | non-visual edits only; the source part is edited in place | — |
| `rebuilt` | the unit's visuals changed; the unit is recompiled from IL | — |
| `manual_required` | a human must do it; the unit ships as a placeholder in a `draft` and blocks a `release` | **NOT NULL** |

`artifact_unit` carries `CHECK (outcome NOT IN ('manual_required','baked') OR reason IS NOT NULL)`,
so the two outcomes that need an explanation cannot be written without one.

**The classifier, in order.** `classify_and_assert(plan)` runs after `postflight` and is total:

```
for each unit u in plan.units:
    if u has an ow:manual region                             -> manual_required  (reason = ManualReason)
    elif u.source_part is None                               -> native | baked   (baked iff a bake row fired)
    elif u.nsig == u.source_nsig and u.ord == u.source_ord    -> passthrough
    elif u.nsig == u.source_nsig                             -> cloned_passthrough
    elif not visual_changed(u)                               -> patched
    else                                                     -> rebuilt
assert sum(counts.values()) == plan.unit_count   else OW-T-005, FATAL, THE ARTEFACT IS NOT WRITTEN
```

`visual_changed(u)` is **not** a heuristic: it is `nsig(u) != nsig(u.source)` restricted to the
elements whose construct rows carry `visual = true`, which is a ConstructTable fact and therefore
declared, versioned and diffable. That is the whole reason `nsig`'s six normalizations and its
shared-definition dependency tracking exist — a unit whose own bytes did not move but which
references a changed `<defs>` entry *has* changed visually, and `nsig` already knows.

Unclassifiable is FATAL and the artefact is not written. That is stronger than reporting it, and the
reason is delivery: a unit nobody can name the outcome of is a unit nobody can say survived. D741 builds `omniweave_core.out.plan`: `OutUnit` and `Plan` as section 3.7 prints them. Each refuses a malformed shape at construction, `Plan` adding a contiguous unique roster and `unit_count == len(units)`. It also builds `UnitOutcome`, `ManualReason`, and `Classified`, which holds `artifact_unit`'s reason CHECK, and `classify_and_assert(plan, baked=, visual_changed=)`. That last is this pseudocode in its order, as a pure function: the bake rows that fired and the `visual = true` predicate are arguments, because the ConstructTable carries no `visual` yet. Any unit with no `nsig` is `OW-T-005` on every path, not only an edited one. The sum is asserted over the outcomes, so a unit reported twice fails too.

## 6. Determinism

`ArtefactDeterminism` is a **declared set**, compared `⊇`, never a boolean.

```python
class ArtefactDeterminism(StrEnum):
    PART="part"; BYTE="byte"; FRAME="frame"; RENDER="render"
```

| class | equality means | portability | promised? |
|---|---|---|---|
| `part` | the member-name set and each member's **payload bytes** are identical | portable across any environment satisfying the pinned major deps | **yes. The floor. Every enabled target has it.** |
| `byte` | container bytes are identical | asserted under one pinned `(python, zlib, compresslevel, dep-set)` | **no.** Recorded in the receipt. A zlib bump falsifies it |
| `frame` | 12 deterministically sampled decoded frames plus the full PCM are identical | pinned `(ffmpeg, codec, threads)` | `video` only |
| `render` | a sampled DOM paint tree and measured layout are identical at sampled times | pinned to a toolchain digest | `deck` only |

**What may vary** and is therefore excluded from `part`: container compression bytes;
central-directory ordering artefacts of the zip writer; the order of attributes as emitted by a
non-canonicalizing serializer (which is why every attribute map is sorted before serialization);
anything the OPC writer normalizes below.

**What may not vary, enforced in `omniweave_core/out/opc.py`** — the only module permitted to open a
ZIP for writing (OUT15), verified against CPython 3.11.9:

```python
CANONICAL_DATE = (1980, 1, 1, 0, 0, 0)
def write_opc(members, order, *, compresslevel=6) -> bytes: ...
def part_digest(members) -> bytes: ...   # sha256 over  name \0 sha256(payload) \n , sorted by name

# ZipInfo.from_file -> mtime = time.localtime(st.st_mtime); date_time = mtime[0:6]  NON-DETERMINISTIC
# ZipFile.writestr  -> ZipInfo(date_time=time.localtime(time.time())[:6])           LOCAL TIME
# ZipInfo(name)     -> date_time == (1980,1,1,0,0,0)                                THE SAFE CTOR
```

Also mandatory, and each one a real observed nondeterminism source:

| rule | what it kills |
|---|---|
| members in canonical order: `[Content_Types].xml`, `_rels/.rels`, then sorted by partname | directory-walk order |
| `dcterms:created == dcterms:modified == job.determinism.clock_ns` | the wall clock |
| `cp:revision="1"`, `cp:lastModifiedBy=""` | host identity |
| no `w:rsid*`, no `p14:creationId` | library-generated randomness |
| shape ids from a per-unit counter seeded at 2 | id allocation order |
| EMU integers only — no `repr(float)` reaches the XML | platform float formatting |
| every attribute map sorted before serialization | dict iteration order under a different hash seed |

**How it is tested.** `OUT13` plus `OUT14`:

- Three runs × `PYTHONHASHSEED ∈ {0, 1, random}`, each in each of two temp directories with a
  different cwd and `TMPDIR` and `SOURCE_DATE_EPOCH=0` — **3 × 2 = six** compiles. `part_digest` must
  be equal across all six; `byte` equality is asserted only within one pinned resolution.
- The cross-platform matrix — nine cells, `{ubuntu, macos, windows} × {3.11, 3.12, 3.13}` — asserts
  **`part` only**. `byte` is a single-cell assertion, recorded in the receipt and never surfaced as a
  promise.
- G8 is extended to `packages/omniweave-target-*` and additionally bans `random`, `secrets`,
  `uuid4` and `datetime.now`. The determinism harness monkeypatches all of them to raise, so a
  compiler that reaches for a clock fails loudly rather than producing a second digest.
- `omniweave-conform`'s `determinism` suite compiles the 40-unit golden bundle twice in one process
  and once in a fresh process, and diffs `part_digest` **member by member** — a whole-digest
  comparison tells you it broke, a member diff tells you which part. *(Build note, D878: `omniweave_conform.out_determinism` compiles each register `[[target]]`'s golden five ways: twice in process, and once in a fresh process per `PYTHONHASHSEED` in `0`, `1` and `random`. Each child runs under `SOURCE_DATE_EPOCH=0` with its own cwd and `TMPDIR`. It diffs each OPC part by sha256 against the first compile. `part` is always judged; `byte` only where the card declares it. `tools/check_out_determinism.py` runs it, and V10-10 too. On this machine docx's 17 members and pptx's 40 agree five ways on both classes, in about 6 s. The goldens carry two units, not forty, and the nine cells are CI's, which is off.)*

A card that declares `byte` and fails the pinned assertion fails the kit. A card that declares
`part` and fails it is a **card-visible downgrade** to a normalized-part class, never a silent one —
see Q1 in Open questions. D748 builds `omniweave_core.out.receipt`: `ArtefactDeterminism`, `CheckValue` (its grammar, and a `fixture` iff `enforced-at-build`), `Receipt` and the report status. A `Receipt` is refused unless it is consistent: unique check names, counts that are the units' tally, `part` in the determinism set, a hex `part_digest`, and an `output` with path, bytes and sha256. A `release` receipt carries `passed` and a `draft` one `manual-required`, unchanged. `degradations` are mappings, because `Degradation` lives above `omniweave_core`. `report_status()` takes the gate's signals, not a receipt, which never carries `failed`.

## 7. The asset ledger

hyperframes' `/media-use` is "the media OS": resolve any media need into **a frozen local file plus a
ledger record**, and reuse assets across projects through a manifest. omniweave adopts the pattern
and refuses the second store: the ledger is a **join** onto L2's `asset` table, which stays the
single source of truth.

```sql
CREATE TABLE artifact_asset (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id),
  slot TEXT NOT NULL,                   -- 'asset-slot:<sha256>' EXACTLY as it appears in the IL
  role TEXT NOT NULL,                   -- image|bake|font|video|audio|ole|thumbnail
  units TEXT NOT NULL,                  -- a JSON array of unit ids
  ratio_variants TEXT NOT NULL DEFAULT '[]',  -- two ratios => THE DECK IS STRETCHING IT
  PRIMARY KEY (artifact_id, asset_id, slot, role)
) WITHOUT ROWID;
```

`ratio_variants` is ppt-master's `display_ratio_variants` (`ppt_to_md.py:839-1014`), and it earns its
column: the same image placed at two different aspect ratios means the deck is stretching it, which
downstream code — a re-place, a re-crop, a `project()` — needs to know before it acts.

### 7.1 Freezing

```python
class AssetLedger:
    def slot(self, sha256: str) -> str: ...        # -> 'asset-slot:<sha256>'; the ONLY IL syntax
    def freeze(self, src: "AssetSource", *, role: str, unit: str) -> "LedgerRow": ...
    def digest(self) -> bytes: ...                 # ledger_digest, one of the six purity inputs
MAX_ASSET_BYTES = 268_435_456                      # §6.10's, not this document's
```

`freeze()` is the **only writer**, and it is the whole of OUT10:

1. Stream the source into CAS, hashing as it goes. A 200 MB video never materialises in memory.
2. Enforce `MAX_ASSET_BYTES` with **both** a content-length pre-check where the source offers one
   **and** a streaming abort — so the limit is not discovered after the memory is spent. The abort
   deletes the partial CAS write before raising, so a refused asset leaves no orphan object for
   `ow store gc` to reap.
3. Write or match an `asset` row: `media_type`, `sha256`, `byte_len`, `width`/`height`,
   `store_ref = "cas://ab/cd/<sha256>"`, and the licence facts `licence`, `licence_url`, `spdx`,
   `source_url`, `retrieved_at_ns`, plus `restriction_bits`. **`asset.store_ref` is NOT NULL**, so
   an unfrozen asset is unrepresentable.
4. Write the `artifact_asset` join row with the slot, the role and the unit.

**A compile that must fetch REFUSES.** Not "fetches and records" — refuses, with
`Degradation(kind="grant_missing")` naming the site Grant and its `dpa_ref`. Freezing happens at
authoring time, through the acquisition path, under an egress grant; it never happens inside a
compile, because a compile is a pure function of six digests and a network fetch is not.

**The digest the producer claims is not the digest stored.** `freeze()` hashes the stream itself; a
disagreement with a claimed digest is `OW_ASSET_DIGEST_MISMATCH` and the asset is rejected. A
content-addressed store with an unverified writer is a substitution oracle. D753 builds `omniweave_core.store.ledger.SqliteAssetLedger`, which follows these four steps in this order. A declared length past the ceiling is refused before the source is opened. `BlobStore.put()` hashes the stream and aborts at the ceiling. A claim the stream disproves is `OW-M-035 OW_ASSET_DIGEST_MISMATCH`: the symbol `store/doc.py` already raised, now registered. The `asset` row is then written, or matched and never patched. The source names its corpus document (`AssetSource.doc_ord`) and may carry an `AssetLicence`, and a document the store does not hold is refused. `ledger_digest` covers `(slot, role, unit)` and never `asset_id`, a surrogate local to one store. The frozen rows persist in the JobDir's `assets/index.json` until the seal, because `artifact_asset` needs an `artifact_id` that only the seal mints. `assert_frozen()` is preflight check 2 and names every slot that fails. `joins()` gives the seal its `artifact_asset` rows. `open(slot)` is the reader half the glossary promises: it reads frozen bytes out of CAS and never fetches.

**Every ledger asset belongs to a corpus document, and at release 1 that is exhaustive.**
`asset.doc_ord` is `NOT NULL REFERENCES doc(doc_ord)` ([the document model](03-document-model.md)),
so an `asset` row cannot exist without a document that owns it. Three consequences, stated because
the constraint is easy to discover late:

- Every asset an IL references entered the corpus through the acquisition path and carries the
  `doc_ord` of the document it came from. A logo the user supplies is ingested as its own `doc`
  before it can be slotted; `ow out scaffold --asset <path>` does exactly that and prints the
  resulting cite.
- A template frozen by `ow out scaffold --from-template` is likewise a `doc` — which is also what
  gives its `read_back` a place to live and its `nsig` set something to be computed from.
- A **compile-produced** asset has no owning document at the moment it is produced, and there is
  exactly one class of those: `bake` output. Because `bake` is `unavailable` on all three release-1
  targets, no such asset exists at release 1 and the constraint holds trivially. It does **not** hold
  the day a rasterizer clears G3, and the answer is the **job document** below, decided now because
  the anchor is *before `bake` ships, not with it*.

**A bake asset hangs off a synthetic job document.** One `doc` row per compile job, written by
`omniweave_core.out.job`'s job runner (§1 row 22) before `bake` produces its first byte, using
columns that already exist. `asset.doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE
CASCADE` is unchanged, the `asset_identity` unique index is unchanged, and **no `doc.origin`
column is added** — a `doc` DDL change would land inside the one strictly-ordered migration
sequence ninety-one tables share, in exchange for a fact `format` already carries.

| column | value |
|---|---|
| `uri` | `ow-job://<corpus>/<artifact_slug>/<job_digest>` |
| `media_type` | `application/vnd.omniweave.job+json` |
| `format` | `owjob` |
| `format_evidence` | `{"synthetic":"compile-job","run_id":…,"artifact_slug":…,"unit_count":…}` |
| `doc_key` | `sha256(canonical job record)[:16]`, so an identical re-run is the same document rather than a second one |
| `source_sha256` | `sha256` of the same canonical bytes |
| `normalizer` | `"canonical/1"` — the bytes were canonical when produced, so normalising them is the identity. **Not** `NULL`, which means the normaliser threw and records `OW-C-041` |
| `status` | `'ok'` |
| `page_count` | `NULL` |
| `next_cite_n` | 1, and it stays 1 |

**`format = 'owjob'` is the origin discriminator.** `WHERE format = 'owjob'` is the exhaustive
selector for synthetic documents and costs nothing, because `format` is already `NOT NULL`. The
token belongs to the format-token register [ingest and routing](05-ingest-and-routing.md) §2.2 owns,
and it is **minted, never detected**: no row of §2.2's detection table produces it, because a job
document is written by the job runner and never walked by a connector. D771: a compile worker is invoked over this document as its one unit. `out.job.job_unit()` is that `UnitRef`, with the `uri` and `media_type` the table prints, digested over the canonical job record, `canonical(job.as_json())`. It is not `Job.to_bytes()`, which keeps the Brief's section order, because a frame's header is encoded with sorted keys and a job that crossed one writes other file bytes for the same record. The S4 worker now serves `compile/1`: `out.compile.lower_job()` runs the card's `carrier()`, `lower()` and `postflight()` there, and refuses as `OW_TARGET_JOB_CHANGED` (`OW-T-525`) a JobDir whose `il_digest`, `constructs_digest` or `ledger_digest` is not the Plan's. The artefact and the receipt return through the CAS, and the gate, the lookup, the restriction aggregate and the seal stay with the host, which holds the store (INV-6). A `HELLO` may name the card's file (`card_source`, `card_origin`), because a catalog built with no environment holds no `OMNIWEAVE_DRIVER_PATH` card. A refusal crosses as `corrupt_input` with its symbol and fix leading the message.

**A job document carries zero `block` rows.** A Channel ranks Blocks, so a job document is invisible
to every Channel by construction and can never be cited: `next_cite_n` is never drawn from, and
`rebind()` is a no-op over it. It is not the artefact's `read_back` document —
`artifact.read_back_doc_ord` (§11) points at that one and never at this one. What the job document
carries is the bake's provenance — which unit, which construct, which DPI — in `format_evidence`
and `x`.

**Deleting a job document deletes its bake assets, and that is refused rather than swept.**
`asset.doc_ord` is `ON DELETE CASCADE` from `doc(doc_ord)`, so removing the job row would silently
take its `asset` rows with it and leave every artefact that slotted those bytes with a dangling
`artifact_asset` join. `ow store gc` never reaps a `doc` row — it reaps a CAS object only when no
`asset` row in any corpus references its digest (§7.2) — so the cascade cannot fire by sweep. The
one path that could is `ow store rm --doc <ord>`, and it **refuses** on a `format = 'owjob'`
document while any `artifact_asset` row references one of its assets, naming the artefact slugs that
would lose their bytes. Deleting those artefacts first is the only way through, and it is deliberate:
a job document is provenance, and provenance outlives the job.

### 7.2 Reuse across projects

Reuse is a **consequence of content addressing**, not a feature with its own manifest. Because the IL
references `asset-slot:<sha256>` and `asset` is keyed `(doc_ord, sha256, IFNULL(origin_part,''))`,
the same logo in 400 documents is 400 `asset` rows — so licence facts and `restriction_bits` stay
per-document — and **one** CAS object. A CAS object is deleted only when no `asset` row in any
corpus references its digest, which is what `ow store gc` implements. `ow out assets <slug>` prints
the ledger for one artefact; `ow out assets --slot <sha256>` prints every artefact and every corpus
document that references one byte-identical asset, which is the reuse query. D778 builds `ow out assets --slug S [--gen N] [--explain] | --slot SHA`. A positional cannot be optional in the generated grammar, and the `--slot` form takes no slug, so the slug is an option. `--slug` lists that generation's frozen assets (`SqliteArtifactStore.assets()`): slot, role, units, bytes and owning document. With `--explain` it adds each asset's licence and the names of its restriction bits, which is where section 15 sends a `restricted` gate. `--slot` (`slot_use()`) lists every artefact generation that slots those bytes and every document that owns an `asset` row of them, each document with its own `asset_id`, because the ledger deduplicates bytes and not permission. A store holds one corpus, so the reuse query reads one `--corpus` at a time.

The consequence worth stating: **the ledger deduplicates bytes and does not deduplicate permission.**
The same JPEG can be freely licensed in one document and barred in another, and a compile that
touches the barred one is refused even though the bytes are already local. That is correct, and it is
why `restriction_bits` lives on `asset` and not on the CAS object.

### 7.3 Licensing metadata on an asset

Six columns on `asset`, plus 32 reserved `restriction_bits`. Two consequences at compile time:

1. **The restriction aggregate runs twice** — once at plan time and once at compile time, as one SQL
   aggregate each, and it is the same statement both times (OUT11, DR17, INV-16). A restricted item
   yields gate status `restricted`, naming the offending cites and asset ids. Two evaluations because
   the store can change between them and the second is the one that governs bytes.
2. **A font is an asset with `role = "font"`**, and its own licence facts propagate. A
   no-redistribution font blocks a compile exactly as a restricted image does. This is the whole
   reason `[capability.compile] assets` includes `font` as a declared member: a target that cannot
   embed fonts cannot be asked to, and a target that can must carry their restrictions.

```sql
-- the restriction aggregate: ONE statement, evaluated at plan time and again at compile time
SELECT 'asset' AS what, a.asset_id AS id, a.restriction_bits AS bits
  FROM artifact_asset aa JOIN asset a USING (asset_id)
 WHERE aa.artifact_id = :aid AND (a.restriction_bits & :barred_mask) != 0
UNION ALL
SELECT 'cite', ac.block_id, b.restriction_bits
  FROM artifact_cite ac JOIN block b ON b.block_id = ac.block_id
 WHERE ac.artifact_id = :aid AND (b.restriction_bits & :barred_mask) != 0;
```

`:barred_mask` comes from the effective policy and is [security](14-security.md)'s to define; this
document fixes only that the statement is one statement, evaluated twice, and that the second
evaluation governs bytes. D751 runs this statement with its two halves, its `UNION ALL` and its predicate, but reads the asset ids and block ids from two JSON arrays (`json_each`) instead of `:aid`. Neither evaluation has an `artifact_id` yet, because plan time and compile time both precede the seal, which is the only writer of `artifact`. A sealed artefact is re-checked by passing its own rows. D779: the effective policy is `[licence] deny_restrictions`, a list of `Restriction` names (default empty, which bars nothing). 14 prints no key, so it sits beside `jurisdiction` and `fields_of_use` as a deployment fact. It is `operational`, since it changes which compile is refused and no produced byte. `drivers.licence.restriction_mask()` ORs each name's bit, and `ow out compile` passes the result as `CompileHost.barred_mask`, so a compile citing a block or slotting an asset that carries a barred bit is `restricted` (exit 6), naming each one, before `lower()`. Retrieval's `Filters.deny_restriction_bits` (07, DR17) is still refused when a caller sets it, and the policy does not yet substitute for it (D261's missing carrier is now this key).

`ledger_digest` is `sha256_canonical` over the frozen ledger rows in `(slot, role)` order. Because it
is one of the six purity inputs, replacing an image — same slot, new bytes, new sha256 — is a new
`artifact_gen` and never a patch of a sealed one.

## 8. Element-addressed feedback: the `OWC1` marker

open-slide's `@slide-comment` is the pattern: element-addressed feedback that **lives in the artifact
source rather than a side channel**, so the tracker and the artefact cannot disagree.
`packages/core/src/editing/comments.ts:5-8` gives the grammar; `apply-comments/SKILL.md` gives the
procedure; `edit-ops.ts` gives the transaction. omniweave generalizes all three to any carrier.

### 8.1 The grammar

```text
<comment_open> OWC1:v1 el=u03/e17 nsig=9f3a1c04 id=k-1a2b3c4d
               ts=2026-09-03T11:04:00Z p=<base64url(JSON)> <comment_close>
```

`OWC1:` is the locked marker token (terminology lock, *Marker*). `CarrierDoc` supplies
`comment_open` / `comment_close`; for both release-1 carriers they are `<!--` and `-->`. Fields are
unquoted and space-separated, so the whole marker is a fixed regular language:

```python
MARKER_RE = re.compile(
    r'OWC1:v1'
    r'\s+el=(?P<el>u\d{2,}/e\d{1,6})'
    r'\s+nsig=(?P<nsig>[0-9a-f]{8})'
    r'\s+id=(?P<id>k-[0-9a-f]{8})'
    r'\s+ts=(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)'
    r'\s+p=(?P<p>[A-Za-z0-9_ -]{0,11000})'
)
```

**Why base64url and not raw text.** The payload is arbitrary human feedback: it contains `"`, `-->`,
newlines, `<` and `>`, every one of which breaks the host syntax. Encoding makes the marker's grammar
a fixed regular language regardless of content. Escaping is the right answer for a *line-structured*
format (ppt-master's `_escape_readback_control_lines` for its Markdown channel); base64url is the
right answer for an *inline* marker.

**Why `p` is not plain base64url, and why this matters more here than in open-slide.**
The base64url alphabet is `[A-Za-z0-9_-]`, which contains `-`. XML 1.0 §2.5 forbids the string `--`
anywhere inside a comment — it is a hard well-formedness error, not a warning — and `xml.etree` is
exactly the parser `carrier/xml.py` uses. open-slide never met this because its marker lives in a JSX
comment where `--` is harmless; omniweave's `owsvg/1` marker lives in an XML comment where it is
fatal. HTML is not safe either: `-->` and `--!>` both close a comment. So:

- **The writer** emits base64url with padding stripped, then inserts one U+0020 between every pair of
  adjacent `-`. No two `-` remain adjacent, `-->` cannot occur (`>` is not in the alphabet), and
  `--!>` cannot occur (`!` is not either).
- **The reader** strips every U+0020 from `p`, re-adds `=` padding to a multiple of four, then
  decodes. The transform is exactly invertible, and a property test round-trips 10 000 random
  payloads asserting both `decode(encode(x)) == x` and `"--" not in encode(x)`.
- The regex bound is derived: `MAX_MARKER_PAYLOAD_BYTES = 4096` encodes to
  `ceil(4096/3) × 4 = 5464` base64 characters; worst case every character is `-`, so at most 5463
  spaces are inserted, giving 10 927 — rounded to 11 000.

Decoded payload:

```jsonc
{"note": "this number should be the FY26 figure, not FY25",
 "hint": "text node under <text data-ow-el=\"u03/e17\">",   // what the placer knew, optional
 "prev": "41.2",                                            // the content re-anchor, optional
 "sev":  "must",                                            // must | should | ask
 "by":   "human"}                                           // human | agent
```

`scan()` is line-based, tolerant and **never throws**: a corrupt payload is skipped and reported, not
fatal (open-slide's `parseMarkers` does exactly this, with a bare `catch {}`). A skipped marker
appears in `OutReport.markers` with `state: "corrupt"` and a `Provenance.FRAMEWORK` info finding —
which makes the gate `unverified`, because a marker nobody can read may be a `must`.

**The marker carries no location.** Its location *is* its location; the reported line is derived
from position in the file at scan time. There is nothing to go stale.

### 8.2 How it is located in source, and the two-factor anchor

`el` proposes. `nsig` disposes. Uniqueness arbitrates (OUT18).

- **`el`** — the stamped IL element address, `u03/e17`, carried as `data-ow-el`. Minted once by
  `ow out stamp`, **never renumbered**, refused on a duplicate (`OW-T-405`, `OUT21`). Renumbering
  would silently invalidate every existing marker and every existing citation.
- **`nsig`** — the content half: the first 8 hex of the canonicalized-subtree digest, after **six**
  declared normalizations (ppt-master `authoring_roundtrip.py:979-1069`):

```text
nsig(el) = hex(sha256(canonical_subtree(el)))[:8]
  1 clone-local id prefixes stripped        4 single-child group filters lowered
  2 asset refs -> asset-slot:<sha256>       5 attribute-free one-child <g> collapsed
  3 an edited asset folded in as :edited:   6 the data-ow-el attribute itself ignored
AND: a subtree referencing a CHANGED DEFINITION ID IS CHANGED even though its own bytes are
identical. SHARED-DEFINITION DEPENDENCY TRACKING IS MANDATORY.
```

That last clause is the one people forget, and it is why `nsig` is not a byte hash. ppt-master's
`authoring_source_ref_is_unchanged` ANDs the subtree hash with
`not (changed_definition_ids & _referenced_definition_ids(current_element))`, and computes
`changed_definition_ids` once per unit — once, not per element, because the naive form is
`O(elements × definitions)` and the computed form is `O(elements + definitions)`.

**8 hex is 32 bits, and that is deliberate.** `nsig` is a *change detector*, not an identity: a
collision means a stale marker is applied to a changed element, which the applier then reparses and
the human reviews. Over a 2000-unit roster with ~200 elements each, 4×10⁵ elements against 2³²
values gives a birthday collision probability near 1.8 % per full-roster comparison — acceptable for
a detector whose failure mode is a reviewable edit, and unacceptable for an identity, which is why
`el` and not `nsig` is the identity. D743 builds `nsig()` and `canonical_subtree()` in `omniweave_core.out.report`, over a canonical copy and never the parsed tree, plus a memoized `CarrierNode.nsig`. Normalization 2 is the identity, because OUT9 leaves `asset-slot:` the only asset syntax. The clone prefix and the edited slots are arguments, being facts of the ledger rather than the tree. Normalizations 4 and 5 apply below the measured element, never to it. The framing is ppt-master's `semantic_subtree_sha256`. The shared definitions are the id'd direct children of the root's direct `<defs>`, and `changed_definitions()` is computed once a unit. `unchanged()` ANDs the subtree's `nsig` with no changed definition its `referenced_ids()` reach (`url(#id)` anywhere, `href="#id"`). `DocIndex.nsigs` is filled per stamped element.

Resolution, and the refusals:

| condition | outcome | code |
|---|---|---|
| exactly one element with `data-ow-el == el`, and its `nsig` matches | resolved; apply | — |
| exactly one element with that `el`, `nsig` differs | **refuse**; the element changed since the marker was placed | `OW-T-153 OW_TARGET_MARKER_STALE` |
| no element with that `el` | orphan; delete the marker, report it | `OW-T-152 OW_TARGET_MARKER_ORPHAN` |
| more than one element with that `el` | impossible by OUT21; a stamping bug | `OW-T-405` |
| the marker targets text content and `prev` is absent with multiple candidate text nodes | **refuse**, never guess | `OW-T-151 OW_TARGET_MARKER_AMBIGUOUS` |

**Placement**, when something needs to *insert* a marker rather than read one:
`CarrierDoc.place_marker(n) -> Insertion` is the only per-carrier feedback hook, and it exists
because insertion is the one part that is carrier-specific. open-slide's rule generalizes: *always
splice the marker as the first child of a container*, because a comment-like token outside a
container context can be parsed as something else entirely and break the surrounding expression. The
marker always sits on its own line, which is what makes removal a **whole-line splice** with no
partial-line surgery and no whitespace repair. For a self-closing element the insertion hoists to the
nearest non-self-closing ancestor, and the `Insertion` records that it hoisted so the applier knows
the note may refer to a child. `MAX_MARKERS_PER_UNIT = 256`; the 257th placement is refused with
`OW_TARGET_MARKER_BUDGET`, because a unit with 256 open notes needs a conversation, not a 257th note. D746 builds placement: `Insertion`, `CarrierDoc.place_marker()` and `marker.place(doc, el, payload, ts)`. When the container's start tag ends its line, the marker opens the next line at that line's indent, and a whole-line removal restores the file byte for byte. When it does not, a newline goes first and stays. `nsig` now frames text whitespace-collapsed (amending D743), so a marker's own line moves no `nsig`. Placement refuses an orphan, a duplicate, the 257th note, and a text target with two runs that `prev` cannot pick (`OW-T-151`). The timestamp is the caller's.

### 8.3 The apply-and-clear command, and why presence is the state

**Marker presence is the state** (OUT19). Present ⇒ pending. Absent ⇒ resolved. Present after a
claimed application ⇒ a **failure signal**. There is no side table, no status field and therefore no
possibility of the tracker and the artefact disagreeing.

The mechanical half is framework code in `omniweave_core/out/marker.py`; the judgment half is the
`omniweave-apply-comments` skill (see [interfaces](10-interfaces.md)), because "make this bigger" is
an authoring decision and the framework does not make authoring decisions.

```python
def scan(doc: CarrierDoc) -> tuple[Marker, ...]: ...
def apply_reverse(doc: CarrierDoc, edits: Sequence[MarkerEdit]) -> str | ParseError: ...
def assert_clean(bundle: ILBundle) -> None: ...        # raises OW-T-141 if any marker remains
```

The apply loop, and the four properties that make it a protocol rather than a prompt:

```text
ow out check --target pptx --markers            # enumerate: el, nsig, note, sev, state
  -> the agent reads the authoring reference FIRST, then edits                  (2)
  -> for each resolved marker, in DESCENDING byte offset order:                 (1)
       splice the edit AND delete the marker's whole line, in ONE Splice batch
  -> collect all splices -> apply back-to-front -> REPARSE -> all-or-nothing    (3)
  -> a marker the agent could not resolve STAYS IN PLACE and is reported skipped (4)
ow out check --target pptx --markers --require-clean   # exit 8 while any marker remains
ow out compile ...                                     # assert_clean() runs here; OW-T-141
```

1. **Reverse order, because edits shift offsets.** Processing top-down invalidates every later
   offset as the file grows or shrinks.
2. **The feedback applier does not re-litigate the design system.** open-slide's rule, adopted: the
   applier consults the authoring reference before editing, so "make this bigger" lands inside the
   declared type scale rather than as a free-floating pixel value.
3. **The edit is transactional** (OUT17). `CarrierDoc.splice()` sorts descending by offset, applies,
   **reparses**, and is all-or-nothing — the direct lift of open-slide's `edit-ops.ts`. A 10 000-op
   random-batch fuzz asserts the file is always either parseable or unchanged. And two parse
   functions one line apart: error-recovering for READ (a work-in-progress file mid-keystroke should
   still scan), strict for anything that WRITES (never modify a file you could not fully parse).
   Overlapping splices in one batch are rejected before any is applied, not resolved by precedence:
   two edits to one byte range are two opinions and the applier does not arbitrate.
4. **Skip is a legal outcome with a defined representation** — leave the marker, report it. That is
   `manual_required` by another name, at element granularity.

**Concurrency.** `apply_reverse` reads the file, computes the whole batch, writes a temp file and
`os.replace()`s it. Two appliers on one file therefore last-writer-wins at whole-file granularity
rather than interleaving, which is the only outcome that keeps the file parseable. The loser's edits
are not silently lost: because presence is the state, its markers are still in the winner's file on
the next scan, and `ow out check --markers` shows them pending. That is the whole payoff of having
no side table.

`assert_clean()` runs inside compile, **after** the gate and **before** `lower()` (OUT16). An
unresolved feedback marker never reaches a release artefact. D745 builds `omniweave_core.out.marker`, with the payload as canonical JSON in this section's base64url. `scan()` and `scan_text()` read lines and never throw: a payload that does not decode is `corrupt`, and a match outside the delimiters is no marker. The id is minted from the marker's content, `blake2b`, with no randomness. `resolve()` follows 8.2's table, and `apply_reverse()` puts each resolved marker's edits and the deletion of its whole line into one carrier `splice()`, refusing an unresolved or unscanned marker before anything applies. `assert_clean(bundle)` scans every unit's text unparsed, corrupt markers included. `over_budget()` holds `MAX_MARKERS_PER_UNIT`, and `DocIndex.markers` is the scan's. Placement and `Insertion` come with the next cell.

## 9. `manual_required`

`manual_required` is simultaneously three things and deliberately not a fourth:

| it is | where |
|---|---|
| a mandatory IL construct in **every** ConstructTable | `ow:manual` |
| a `UnitOutcome` | `artifact_unit.outcome`, with `reason` **NOT NULL** |
| a `GateStatus` | `manual-required` |
| **not** a `Disposition` | a disposition says what the *compiler* does with a construct; `manual` says what a *human* must do about a region |

```python
class ManualReason(StrEnum):
    UNVERIFIABLE_WORDING="unverifiable_wording"; UNVERIFIABLE_IDENTITY="unverifiable_identity"
    UNVERIFIABLE_DATA="unverifiable_data";       INSUFFICIENT_SOURCE="insufficient_source"
    UNREPRESENTABLE="unrepresentable";           LICENCE_BARRED="licence_barred"
    MEASUREMENT_FAILED="measurement_failed"
```

**When a target must raise it.** ppt-master's realization table
(`workflows/profiles/image-to-pptx.md:53-68`), as the closed rule set:

| situation | reason | never instead |
|---|---|---|
| text whose exact visible wording cannot be read at final display size | `unverifiable_wording` | invent plausible wording |
| a logo, badge or ornament whose identity cannot be preserved by exact vector, deterministic redraw or sufficient source pixels | `unverifiable_identity` | a merely similar graphic |
| a chart or table where a value, label, relationship or geometry cannot be verified | `unverifiable_data` | a generatively recreated data graphic |
| a region contaminated, occluded, incomplete or too low-resolution to crop or reconstruct | `insufficient_source` | upscale and hope |
| a construct with no `native` row and no reachable `bake` | `unrepresentable` | silently drop it |
| an asset whose `restriction_bits` bar this use | `licence_barred` | embed and record |
| a `measure()` that returned `None` where a capacity decision was required | `measurement_failed` | assume it fits |

Two rules make the vocabulary work rather than becoming a shrug:

- **Assess sufficiency per region at final display size, without a page-wide score.** A page-level
  confidence number hides exactly the one region that is unreadable.
- **Separate layer need from realization.** Source clarity never decides *whether* a required
  editable, movable or overlapping object becomes its own element — only *how* that element is
  prepared. Conflating them makes a blurry photo into a flattened slide.

**Observation is separate from decision.** `ManualEvidence` records **only what is visibly present**:
the source frame, its sha256 and pixel dimensions, and per region a stable id, a bbox, the observed
family (`text` / `graphic` / `image` / `unknown`), verbatim text where readable, a confidence, the
observed sufficiency, boundary completeness, occlusion and identity/data verifiability, and
overlap/z-order observations. It records **no** realization choices, no prompts, no output filenames
and no IL bindings. It is named `ManualEvidence` and not `Evidence` because `Evidence` is the routing
record in `omniweave/route/evidence.py` (§5 X38). Keeping the observation artefact free of decisions
makes it re-reviewable and stops the model rationalizing an observation to fit a decision it already
made.

**How it surfaces to the human.** Four surfaces, one fact:

1. **The gate.** `manual-required` is a `GateStatus`, so a release stops. The message names each
   unit, its `ManualReason` and the region.
2. **The draft.** `ow out compile --accept-manual` produces a draft: placeholders carrying their
   `ManualReason`, `delivery: "draft"` in the receipt and on the `artifact` row, `gate_status`
   **unchanged** (still `manual-required`), and a `Diag(OW_MANUAL_REQUIRED)` on every later
   `read_back`. **There is no gate bypass** — the draft is a second row with a different `delivery`,
   not a pass. A `draft` row is additionally refused by `ow out verify --class render` against a
   release golden, because comparing a placeholder to a finished unit produces a diff nobody wants.
3. **The IL.** The `ow:manual` construct is in the source, so the region is visible where the work
   happens.
4. **The receipt.** `Receipt.units` maps the unit to `manual_required` and `Receipt.counts` carries
   the total; `artifact_unit.reason` is NOT NULL by CHECK constraint for both `manual_required` and
   `baked`. D756 builds `omniweave_core.out.manual`. A region is an element carrying `data-ow-manual`, whose value is the reason. `ILBundle.load()` reads every region in its one parse, and the first with a known reason becomes `OutUnit.manual_reason`. `check()` reports each region of the stage's roster as a `manual_units` row (unit, `el`, reason), which is what makes the gate `manual-required`. A value outside `ManualReason` is `OW-T-513 OW_TARGET_MANUAL_REASON_UNKNOWN` (appended), a framework error, so the gate fails rather than asking a human to act on an undefined word. The runner rebuilds `plan.units` from the bundle once preflight check 3 holds (section 3.7 note 4), copying each `nsig` and `manual_reason`. A draft of a manual unit therefore seals `manual_required` with its reason, and a release of one is a closed gate. `ManualEvidence` reads exactly its observation keys (the frame, then per region an id, a bbox inside the frame, the family, the text, the confidence, the sufficiency, boundary, occlusion, the two verifiabilities, overlaps and z) and refuses any other key, so a decision cannot ride along.

## 10. Citation flow

A claim in a generated artefact carries a pointer back through the store to a polygon on a source
page. The chain, end to end:

```text
polygon on a source page
  ^  block.quad + block.page  (NO SYNTHESIZED BOX, EVER — INV-9)
  |
block row  (block_id, addr, cite, span (ts_a,ts_b), origin (os_*), quote, trust)
  ^  block_cite: UNIQUE(doc_ord, cite), no `gen` — one cite names at most one row for the life
  |  of the corpus; rebind() CARRIES the cite, so a re-parse cannot re-point a shipped citation
cite token  'd7#412'   (the ONLY identifier that may appear in a prompt or in model output)
  |
IL element  <text data-ow-el="u05/e31" data-ow-cite="d7#412"> … </text>
  |
artifact_cite  (artifact_id, unit, el, cite, block_id, doc_gen PINNED, kind, span_a, span_b, verbatim)
  |
the artefact  three channels: visible · embedded · ledger
```

**Three channels, and which one is authoritative.**

| channel | where it lives | suppressible | who reads it |
|---|---|---|---|
| **visible** | a rendered marker in the artefact | yes — and suppression is a **receipt row** | a human reading the deck |
| **embedded** | a provenance part inside the container (`customXml/omniweave-provenance.json` for OOXML; `data-ow-cite` attributes for `deck`) | no | `read_back`, and only this one |
| **ledger** | `artifact_cite` in the store | no | queries; **authoritative** |

A `.owcite.json` sidecar is written **always**, at `out/<slug>.owcite.json`, so a target whose
`[compile] citations = "sidecar"` cannot embed still has a resolvable channel. `read_back` recovers
citations from the **embedded channel only** and **never infers a citation from visible text** —
that inference is rejected by name in the charter, because visible text that happens to look like a
cite token is not a provenance claim.

**What the artefact embeds to make this resolvable later.** The provenance part carries, per cited
element: the `el`, the `cite`, the pinned `doc_gen`, the citation `kind`
(`quote | paraphrase | derived | data`), the `(span_a, span_b)` where one exists, and the corpus id.
`doc_gen` is pinned at build time, so a later re-parse of the source document cannot re-point a
shipped citation — and where a cite has been retired, resolution follows
`block_history.superseded_by`, or refuses with `OW-M-030 / OW_CITE_RETIRED` naming the generation and
the reason. Never a silent miss, never a nearby block. D783 writes the docx embedded part as canonical JSON (`omniweave.out-provenance/1`): the corpus, slug and generation once, then one row for each cited element and cite, in document order, with `el`, the canonical cite, its pinned `doc_gen`, and `kind` and `span` where the IL states them. A span is read beside a single cite only, as the seal's rows read it. The part is related from the package root under the relationship type `urn:omniweave:relationship:provenance`, and is written even when nothing is cited. The receipt's `citations_channel` row counts its rows. Found: nothing filled `Plan.cites`. A scaffold has no IL to cite from, and the compile resolved cites only for the seal's rows. The compile now pins them before lowering, as each resolved block's canonical cite and the generation it resolved at, so the part and the `artifact_cite` rows name the same generations. A cite that is unaddressed, unpinned or of an unknown kind is refused before a byte is written.

**`artifact_cite.block_id` is NULL on exactly one kind of row.** The column is nullable and the DDL
comments it *"NULL ⇒ unresolved at build time"*, which is only reachable one way: a row written by
`read_back` over an artefact whose cites name blocks this corpus does not have — a deck built against
another corpus, or one edited outside omniweave. A row written by a **compile** is never NULL,
because `--stage final` blocks on an unresolvable cite (`OW-T-101 OW_TARGET_CITE_UNRESOLVED`) before
`lower()` is reached. A CI assertion over the golden corpus states it as an invariant, because a
nullable column with no stated rule becomes a dumping ground within two releases.

**Verbatimness is proved, never claimed.** `artifact_cite.verbatim` is set by rule `OW-T-102`, which
asserts `nfc(visible_text(el)) == nfc(block.text[span_a:span_b])` **and**
`block.quote == Quote.VERBATIM`. The author never asserts it, and an author who writes `kind="quote"`
over text that does not match gets a blocking finding with `ow open d7#412 --raw` as the fix. Note
what this means at release 1 for OOXML sources: every Block from the office parse path is
`quote = normalized`, so a `pptx` artefact quoting a `.pptx` source cannot reach `verbatim = 1` until
the anydoc fork emits a node path — the second conjunct fails, correctly, rather than the rule being
weakened to fit.

**Cite resolution is batched.** A 2000-unit roster with 20 cites per unit is 40 000 resolutions;
`CiteResolver` therefore exposes `by_cites(tuple[Cite, ...]) -> Mapping[Cite, Block | None]` as well
as `by_cite`, and the `order = 80` cross-reference rule calls the batch form once per unit. The
resolver holds no store handle beyond the read: no writes, no retrieval, no `Filters`. D754 builds `omniweave_core.out.cites` (`CiteResolver`, `CitedBlock`, `NO_CITES`, `verbatim()`) and `omniweave_core.store.cites.SqliteCiteResolver`. A resolver returns a `CitedBlock`, not a `Block`: the id, the document, its head generation (the `doc_gen` a row pins), the text, the quote tier and the restriction bits, and nothing a rule could reach the store through. One `by_cites()` call is one transaction, at 500 cites a statement through `block_cite`. A compile cites what is live, so a retired cite does not resolve, and `ow open` names its successor. The resolver serves one corpus: its qualified tokens resolve, other corpora's do not, and the result is keyed as asked. `check(cites=...)` meets the `cites` need, and `RuleCtx.cites` is that resolver. Without one it is `NO_CITES`, which refuses, so a rule that reads cites without declaring the need fails as `OW_TARGET_RULE_RAISED` instead of passing on nothing. `verbatim()` is this section's predicate whole: a `VERBATIM` block and the `nfc` of a span inside its text. The rule and the seal both use it.

**The query the mined collection cannot answer.** `CREATE INDEX artifact_cite_block ON
artifact_cite(block_id)` makes "which decks quote page 14 of this contract?" one indexed query:

```sql
SELECT a.slug, a.artifact_gen, ac.unit, ac.el, ac.kind, ac.verbatim
FROM artifact_cite ac
JOIN artifact a USING (artifact_id)
JOIN block b ON b.block_id = ac.block_id
WHERE b.doc_ord = :doc AND b.page = 14 AND a.delivery = 'release'
ORDER BY a.slug, ac.unit, ac.el;
```

**The honest limit, stated because it is real.** PowerPoint may discard an unknown OPC part on save.
The loss is *detectable* — `ow out verify` reports the missing provenance part — it is reported, and
the ledger is unaffected, because the ledger is in the store and not in the file. What is lost is the
ability of a *third party* to resolve citations from the file alone after such a save. The `deck`
target does not have this problem (`data-ow-cite` is an ordinary attribute), and `docx` has it
exactly as `pptx` does.

## 11. `read_back`: the round-trip contract

`read_back` is the locked name for what `_index/framework-blueprint.md` called `parse_back()`. It is
**an ordinary `parse/1` Driver** — an ordinary card, an ordinary probe, an ordinary licence block, an
ordinary conformance run, and the ~120-test driver testkit runs against it **unchanged**. That is the
whole trick: a generated artefact re-enters the corpus through the pipe that already exists, and
`artifact.read_back_doc_ord` is a foreign key into `doc`. D786 builds the first: `parse.docx.native`, docx's read_back, a card in `omniweave_target_docx.read` with its own entry point. It reads only what `lower/` writes. A `w:sectPr` ends a unit, and each unit is a `section` block. A style names a block's kind. `w:numPr` gives lists, nested by level. Consecutive `Quote` paragraphs are one blockquote. A caption before a table is the table's, and after a picture it makes a figure. A table is its cells, with spans from `w:gridSpan` and `w:vMerge`. A note body is a `Layer.NOTE` block, and its reference a zero-width `note_ref` mark. Every block is `roundtrip`/`inferred`/`normalized`. A bookmark's ends sit in the first and last paragraphs its element made, so it cannot say whether `u01/e1` is a section or the heading it opens with. The provenance part therefore now maps each address to its construct, and the address goes to the nearest block of that construct's `kind_map` kind, with its cites (`x.ow.el`, `x.ow.cites`, D785). A `.docx` with no provenance part is refused as not this target's, and `sniff()` answers no stream (Q4). `resolve()` for the docx media type now lists it beside `parse.office.anydoc`, and `decode.office-native` still names anydoc, so ingest is unchanged. R2 holds over a rich unit's read-back. Found: the html carrier gave a `visible = false` element no text of its own, so a footnote body's R2 comparand was empty. Invisible now means contributing nothing to the elements around it.

### 11.1 The seven laws, as testable properties

```text
compile : ILBundle -> Artefact       read_back : Artefact -> owdoc-fragment/1 -> Doc
project : Doc -> ILBundle            =_det : equality at the declared determinism classes
```

| law | statement | mandatory when | the test |
|---|---|---|---|
| **R1** RETAINED-IL IDENTITY | for every artefact `A` omniweave built with retained bundle `I`: `compile(I) =_det A` | **every** target | `ow out verify <artefact>`; this is what makes editing an omniweave-built artefact `passthrough` rather than reconstruction |
| **R2** ADDRESS SURVIVAL | for every element `e` in `I` carrying `data-ow-el`: `read_back(compile(I))` contains **exactly one** Block `b` with `b.x["x.ow.el"] == e.el`, `b.kind == kind_map[e.construct]`, `nfc(b.text) == nfc(visible_text(e))`, `b.x["x.ow.cite"] == e.cites` | `fidelity != none` | missing / duplicated / kind-mismatched / text-mismatched are each a distinct failure |
| **R3** SECOND-ROUND FIXED POINT | `D1 = read_back(compile(I))`; `D2 = read_back(compile(project(D1)))` ⇒ the multiset of `content_digest` over `Layer.BODY` blocks in `(page, ord)` order is EQUAL | `fidelity ∈ {structure, passthrough, patched}` — every value but `none`. R3 is a predicate over `content_digest` and carries no geometry, so a `patched` carrier that re-lays-out a flow still owes a second-round fixed point over its BODY blocks; `fidelity = "none"` is the one exemption, because a lossy encode is not idempotent and §12.4 says so | **the first round is not required to be a fixed point** — an author writes compatible-but-non-canonical input and the compiler legitimately normalizes it once. The second must be. That is the honest, achievable statement of "lossless round trip" |
| **R4** EDIT LOCALITY | (a) `read_back` then compile with **zero** edits ⇒ 100 % of units are `passthrough` or `cloned_passthrough`, each copied part's sha256 **asserted equal** to the source part's. (b) edits confined to element set `E` ⇒ every unit whose source-refs **and definition dependencies** are disjoint from `E` is `passthrough` or `patched`, **never `rebuilt`** | `fidelity == passthrough` | the definition-dependency clause is the non-obvious half: a unit referencing a changed `<defs>` entry is changed even though its own bytes are not |
| **R5** DECLARED LOSS, BOTH DIRECTIONS | `observed_loss ⊆ declared_loss` **and** every row with `round_trip ∈ {lossy, dropped}` has a fixture where the loss **occurs** and emits `Diag(OW_ROUNDTRIP_LOST, {construct})` **and** every `round_trip == exact` row is exercised by the golden corpus **and** a semantic mutation of its payload **moves `il_digest_rt`** | every target | without the third clause, `loses = ["*"]` is a green report |
| **R6** NOTHING SILENTLY DROPPED | every relationship, media part or opaque payload in `A` not representable in the IL is either (a) an opaque passthrough asset **with a ledger row**, or (b) a **blocking refusal naming the exact part paths and both exits**. There is no third branch | every target | unmapped relationships are AT-RISK whenever visuals changed at all — fail closed on the unknown |
| **R7** TOTAL CLASSIFICATION | every output unit lands in exactly one `UnitOutcome` and the sum equals `unit_count`. Unclassifiable is FATAL, the artefact is **not written**, and the counts are printed | every target | `classify_and_assert()` (§5.5); `OW-T-005` |

R6's refusal message is ppt-master's, and it is the model for every refusal in this layer
(`svg_to_pptx/pptx_package/cli.py:2890-2948`) — it names the exact paths **and both ways out**:

```text
Error: round-trip export would drop source video, audio, or opaque payload relationships:
  unit u03 (source slide 5): ppt/media/media1.mp4, ppt/embeddings/oleObject1.bin
Keep each listed source unit unedited, or remove the opaque relationship from the source
artefact before importing.
```

R4(b)'s dependency resolution is precise rather than conservative: a unit is blocked only when the
*specific* dependency paths are affected by the edit, and unmapped dependencies — relationships
nothing in the IL claims — are treated as at-risk whenever the unit's visuals changed at all. D774: `ow out verify [--job DIR]` checks R1 and R7 (`omniweave.run.out_verify`). R1 fetches the sealed row's retained IL into a scratch JobDir, recompiles it in an S4 worker, and compares at each class the row declares: `byte` is the sha256, `part` the receipt's `part_digest`, and `frame` and `render` are reported `unchecked`, which is not a pass. R7 counts the `artifact_unit` rows against the roster. **Found:** the retained bundle is the IL alone, and R1 also recompiles over the Brief (a purity input), the clock every OPC timestamp is written as, and the frozen assets. None of these is retained beside the row, so the verb reads them from the JobDir that compiled the artefact, each held to the row's digest (`OW_TARGET_VERIFY_INPUTS`, `OW-T-527`), rather than from the artefact path 18 prints. Retaining the job record (the canonical `Job` the worker is sent, whose digest is the synthetic job document's) would let a verify start from the artefact alone.

### 11.2 What MUST survive, what MAY be lost

| MUST survive R2/R3 | mechanism |
|---|---|
| `data-ow-el` | `x.ow.el` on the Block; `artifact_el` rows |
| a Block `kind` under `kind_map` | the target's `kind_map.toml`, R2's comparator |
| visible text under NFC | `nfc(b.text) == nfc(visible_text(e))`, one `visible_text` per carrier (§3.1) |
| reading order | `(page, ord)` on the Block, from the container's own order |
| table cell topology `(r, c, row_span, col_span)` | the `cell` table; a cell **is** a Block |
| asset identity by sha256 | `asset.sha256`, the `artifact_asset` join |
| cite tokens | `x.ow.cite`, `artifact_cite` |
| notes and footnotes as a distinct `Layer` | `Layer.NOTE` |
| `restriction_bits` | runner-stamped, propagating (INV-16) |
| for `passthrough`/`patched` units, **the original container bytes** | part-level copy, sha256 asserted |

| MAY be lost — and MUST be declared as a construct row with `round_trip ∈ {lossy, dropped}` |
|---|
| geometry below the target's grid quantum |
| marks outside the declared set |
| `score` / `score_kind` |
| `raw_kind` |
| `layer = hidden` where the target has no equivalent |
| animation timing curves (trigger and preset survive) |
| autofit font scaling (recomputed) |
| theme-relative colours resolved to literal |
| transition sound |

**A sixth kind of loss is a bug**, and R5 makes it a build failure: `observed_loss ⊆ declared_loss` is
checked over the golden corpus, so a loss with no row fails CI rather than shipping. D785 gives a read-back's two keys a way into the store. The fragment decoder now carries a block record's `x`, which it had dropped for every driver, and refuses only one that is not an object. `DocSink` keeps the key rules: the `ow` segment is still the framework's, and its two read-back keys, `x.ow.el` (a `data-ow-el` address) and `x.ow.cites` (a list of cite tokens), are admitted on a block whose method is `roundtrip` and refused anywhere else (OUT22). Found: section 11.1 prints R2's cite key as `x.ow.cite`, which the archive already uses to carry a block's own durable cite through `add_block` and strips on export. Cites stored there would read as the block's identity and vanish from every archive, so the read-back key is `x.ow.cites`.

### 11.3 `il_digest_rt`, and why a second digest exists

```text
il_digest_rt = il_digest over canonical_subtree with every payload key of a construct whose
               round_trip != EXACT elided.  THE EXCLUSION SET IS DERIVED FROM THE TABLE.
```

`il_digest` answers "are these the same bytes" and gates the report. `il_digest_rt` answers "are
these the same *round-trippable content*" and is what R5's third clause mutates against. The
exclusion set is **derived** from `constructs.toml`, never hand-tuned — which is what stops a target
from quietly widening the exclusion set until every mutation is invisible. Both digests are computed
once, in `ILBundle.load()`, over the same parse.

### 11.4 The conformance test

`omniweave_core/out/roundtrip.py` exposes `r1 … r7` as **executable predicates**, imported by
`omniweave-conform`'s `target` suite. The suite is parameterized over
`fixtures/out/golden/<target>/` and `fixtures/out/foreign/`, and a target's card declares which laws
apply (`[compile.round_trip] laws = ["r1", …]`). A law the card does not declare is **reported as
not applicable in the conformance output**, not silently absent — so `laws = ["r1"]` is visible as a
weak claim rather than an unremarked one. The kit additionally refuses a card declaring a law the
`fidelity` tier does not permit: `laws` containing `r4` with `fidelity != "passthrough"` is a card
error, because R4 is only meaningful where container parts are copyable. D757 builds `omniweave_core.out.roundtrip`. Each law is a predicate over facts already observed and never runs a pipeline. R1 takes the declared classes and two digest maps. R2 takes IL elements, read-back blocks and `kind_map`. R3 takes two rounds' blocks. R4 is `r4a` for zero edits (copied, sha256 equal) and `r4b` for edits confined to `E`, with source-refs and definition dependencies as one set. R5 takes its four clauses' sets, R6 the unrepresented parts and the ledgered paths, and R7 a roster and its outcomes. Each returns a `LawResult` whose `Failure`s carry a kind from the law's closed set, so R2's missing, duplicated, kind, text and cites failures stay distinct. R1 fails a declared class that is unmeasured, rather than passing it. R3 compares BODY digests in `(page, ord)` order, as a sequence. R6 builds section 11.1's refusal: the paths and both ways out. `applicable(laws, fidelity)` reports undeclared laws as not applicable, and refuses `r4` without `passthrough` and `r2`/`r3` at `none`.

`read_back` provenance is not negotiable (OUT22): `Method.ROUNDTRIP` **always**;
`Quote.RECONSTRUCTED` unless the text was read from the artefact; `Trust.INFERRED` wherever
`kind_map` is many-to-one. A `read_back` that stamps `Trust.EXTRACTED` on a many-to-one mapping fails
the testkit, and `kind_map.toml`'s many-to-one entries are the kit's input for that check rather than
a reviewer's judgement. D759 builds the `target` suite as `omniweave_conform.suites.target.suite.run_target()`, with the first golden fixture at `fixtures/out/golden/owtext/` (IL and a `cites.json` its cites resolve against). It is not one of the twelve card suites, so it reports a `TargetReport` of per-law outcomes, and its verdict excludes undeclared laws. The golden fixture must pass its own gate first, or every declared law is `unknown` and nothing is lowered. Exercising the mandatory `ow:manual` row makes the gate `manual-required`, so the golden compile is a draft. R1 compiles twice and compares the card's declared classes. R7 is the classifier plus the receipt's agreement with it. For R5, clauses 3 and 4 are computed: a byte inserted into each exact row's payload must move `il_digest_rt`. Clauses 1 and 2 need `read_back`, so R5 is `unknown` while 3 and 4 hold. Found: `attr.ow-el` is a mandatory `exact` row, but `canonical_subtree()` drops `data-ow-el` by normalization, so no target's el mutation can move `il_digest_rt`. R5's fourth clause, read literally, therefore fails for every target. The suite exempts that row by name: the address's survival is R2's to prove. D784 adds the second golden fixture, `fixtures/out/golden/docx/`. It has two units that use every `exact` row of owflow/1, outside any non-exact parent whose payload `il_digest_rt` elides. It also has a manual region, a cite with its kind and span, two notes and a frozen picture. Against it, docx's R1 and R7 pass and R5's clauses 3 and 4 hold, while R2, R3 and R6 are `unknown` until `parse.docx.native`. The suite gained three things to run it. A fixture's `assets/` files are the frozen ledger its compile reads. The scratch JobDir has a `job.json` with a fixed clock, which docx reads `dcterms` from. The golden Plan pins its cites as the compile does. The exemption is by selector, and its reason names the table's own row: owtext's `attr.ow-el`, docx's `ow.el`. D787 runs R2 when the caller hands the suite the target's reader, because the read_back is a separate `parse/1` card. The golden is compiled once and read back, and R2 is judged over every addressed element of its IL, each under its construct and the card's `kind_map.toml`. Over docx's golden with `parse.docx.native`, R2 passes. A reader that loses one address fails it, naming the address. Without a reader, R2 is `unknown` and says so. R3 is `unknown` naming `project = false`, which docx's card declares beside `r3`. Found: R3 can never be checked for docx while the card claims it, because R3 needs a projection the card says it lacks. Found: the manual placeholder wrote its reason into its own text, which can never equal the region's visible text. The reason is now a Word comment, `ow:manual <reason>`, dated with the job's clock, since python-docx stamps the wall clock. The read_back returns it as a `comment` block on `Layer.ANNOTATION`, and `ow.manual` maps to `paragraph`. *(Build note, D911: V10-9 asks each target to reach `GateStatus == passed` on this suite, and a golden carries an `ow:manual` region by design, since R5 needs every exact row exercised and `ow:manual` is mandatory in every table, so the golden's own gate is `manual-required`. `TargetReport.release` is the gate of the golden with each unit its check lists in `manual_units` withheld whole and the roster renumbered, and when it passes the remainder is compiled once as a `release` Plan whose receipt must say `release` and `passed`. docx's remainder passes. pptx's does not, because its `u01` links to `#u02`, and that exposed a gap: `pptx.reference@1` checked a slide link's spelling and not that the slide exists, so the gate passed IL whose `lower()` then refused. The rule now checks `#u<NN>` against the roster. pptx's release is the 40-unit golden, whose gate and release both pass with R1, R2 and R7 holding.)*

## 12. The three v1 targets, and the v2 seam

| | **pptx** | **deck** | **docx** |
|---|---|---|---|
| distribution | `omniweave-target-pptx` | `omniweave-target-deck` | `omniweave-target-docx` |
| execution | **pure Python, no Node** | Toolchain (node ≥ 20), S2 | pure Python |
| carrier / IL | `svg` / `owsvg/1` | `html` / `owdeck/1` | `html` / `owflow/1` |
| `unit` | `slide` | `page` | `section` |
| deps | python-pptx, XlsxWriter, skia-pathops, uharfbuzz, Pillow (≤ 60 MB) | a 1 MB manifest plus a `$OMNIWEAVE_HOME` bundle | python-docx, lxml (~20 MB); **not** in `[recommended]` |
| constructs v1 | ~180 rows | ~90 rows | ~70 rows |
| runtime rules | none | **yes** (`getBoundingClientRect` capacity, off-canvas measure) | none |
| `determinism` | `["part","byte"]` | `["render","part"]` | `["part","byte"]` |
| `citations` | `embedded` (customXml) | `embedded` (`data-ow-cite`) | `embedded` (customXml) |
| `read_back` | `parse.pptx.native` | `parse.deck.native` | `parse.docx.native` |
| `fidelity` | **passthrough** | `structure` | `patched` |
| `laws` | R1-R7 | R1, R2, R3, R5, R6, R7 | R1, R2, R3, R5, R6, R7 |
| `bake` | `unavailable` → `toolchain:deck` once installed | — | `unavailable` |
| why it is in the set | the **only** working round trip in the collection; zero Node | the **only** proof a Toolchain target is not second-class; open-slide has **no** semantic validator | the honest test that the abstraction is not one implementation wearing an interface — a **flow** carrier: no canvas, no z-order, no bake |

### 12.1 `pptx` — carrier `svg`, IL `owsvg/1`

**The IL.** A closed SVG subset. The `viewBox` is the canvas and one `<svg>` root is one slide. The
authoring surface is a **closed inline-style property set** (ppt-master's is 32 properties;
omniweave's is the ConstructTable's `native` rows, and it is the set `@style|<prop>` selectors are
resolved against) and inline attributes only. `<style>` (`svg|style`), `class` (`@class`) and
`<link rel="stylesheet">` (`svg|link`) are each a `forbidden` row: a CSS cascade has no DrawingML
equivalent and would have to be resolved by the compiler, at the cost of being the only construct
whose meaning depends on document order. The remaining CSS spellings need no row at all —
`<?xml-stylesheet` is a processing instruction and is refused one layer earlier by the carrier parse
(§3.1 item 4), and `@import` and `@font-face` are at-rules that cannot occur once all three of their
hosts are gone, which is also the answer to "what declares a text face": a system font stack in the
inline property set, and nothing else. D789 builds the IL's contract in `omniweave_target_pptx`: the card (`compile.pptx.native`, `implemented = false`), a 190-row table, `kind_map.toml`, four normalizers, and `rules/`, one rule a file. The table has the four mandatory constructs, the canvas, ten shapes, text, geometry, paint and opacity, stroke, gradients, a preset pattern, one shadow or glow, markers and clips. The closed inline-style set is 30 `@style|<prop>` rows: ppt-master's 32, less `filter` and `shape-rendering`, each lowered as its attribute is. 34 rows are forbidden, four are bake rows, and 27 are normalize rows: hex case, a `px` suffix and an opacity written as a percentage. The structural band is three rules. The slide is one `<svg>` root, never nested. The `viewBox` is `0 0 W H` in integers within PowerPoint's 96 to 5376 user units, with no root `transform`, `width` or `height` that rescales it, and at the final stage W:H is the Brief's `canvas format`. `data-ow-el` is unique. `table_pack()` gains the bake rule, an error while the card's `bake` is `unavailable` and a warning otherwise (section 3.3's table), and `RuleCtx` gains `brief`, which section 4.4 prints and the Protocol had lacked. Found: a bake construct passed the gate and was refused only at preflight 5, because no rule reported bake rows at check time. D790 builds the grammar band, ten rules at orders 40-49, one a file. They cover paint, opacity, geometry lengths, point lists, path data, transforms, keyword properties, strokes, fonts and gradients. Each is grounded in ppt-master's exporter, and each names the value, where it is written, and the spelling that would hold. A rule reads an attribute as the table's normalize rows leave it, through `RuleCtx.constructs`, which section 4.4 prints and the Protocol lacked. So `fill="#abc"` is the normalize row's warning alone, and `fill="#abcd"` is this band's error. A `style` declaration is read as written, with `px` allowed on a style length as CSS writes one. A value is refused where DrawingML has nowhere to put it: `points` off a polygon or polyline, `d` off a path, `text-anchor` on a `<tspan>`, `baseline-shift` off one, and a transform inside a `<clipPath>`, `<marker>` or `<pattern>`. Text takes a translation or one rotation. owsvg/1 refuses where ppt-master clamps an opacity or lets a gradient end overshoot its box, because a clamp writes a value the author did not. D791 builds the references and effects, orders 50-52. Every local reference resolves to what it needs. An id is defined once in the slide. A `fill` names a gradient or a pattern and a `stroke` a gradient. `filter`, `marker-start`, `marker-end` and `clip-path` name a `<filter>`, `<marker>` and `<clipPath>`. A `<use>` names a local shape, group, text, image or symbol, an `<image>` its picture as `asset-slot:<sha256>`, and an `<a>` a slide (`#u<NN>`) or an `https:` page. A filter holds one drop shadow or one blur, and a marker and a clip one shape each. A line end stands on a line or a path, a clip on an image, and an image takes a filter or a clip, not both. A definition stands in `<defs>` with an id, and a pattern names one of DrawingML's 54 presets, with no fallback. The cite facts and the cite batch move to the framework, `omniweave_core.out.conformance.cite_pack()`, built from the table and named for the target. docx uses it under its own rule ids, and pptx gains both. `CITE_KINDS` moves to `out.cites`, since `out` imports nothing from `store`. D792 builds `measure.py`, the one `TextMeasure`: uharfbuzz shaping over the faces the card's `[config] font_dirs` names, absolute directories read once in path order, and no system font directory. Measuring against whatever fonts a host holds would differ across the nine cells a target's output is compared on. A face is found by family name (IDs 16 then 1), then italic, then the nearest weight, with path order breaking ties. A generic family names no face. Text properties inherit as SVG's do. A `<text>` is its positioned lines, each run shaped in its own face. The `Box` is the widest line, the first line's ascent, the last line's descent and the node's own leading. A node with no face is `None`. With no `font_dirs`, or no uharfbuzz, `measure()` is `None` and every measurement rule is a recorded skip. One compiler has one estimator. Tests build their faces from raw tables (`tests/fontkit.py`), since no font is committed and fontTools is not a dependency. `ow out check`, `stamp` and `normalize` now build a target with its `[drivers."<id>".config]`; each had used only the card's defaults. Found: `compile`, `verify` and the read-back still cannot honour a driver's config. The effective config is not one of a compile's six purity inputs, so a compile under another config would find, and place, bytes an earlier config built. pptx's lowering, which shapes text too, needs that closed or its fonts frozen as `role = "font"` assets (section 7.3). D793 builds the measurement band. `pptx.text.canvas@1` (order 60, `needs={"measure"}`) places each text's widest measured line by its inherited `text-anchor` and its summed translations, and runs it from the first baseline less the ascent to the last baseline plus the descent. A text past the `viewBox` is `OW_TARGET_TEXT_OFF_CANVAS` (`OW-T-429`), and every message states the model: single-line width per positioned line, vertical wrapping not modeled. A rotated or scaled text is outside the model. `pptx.text.lines@1` (53) makes the widest line bound them all. A positioned `<tspan>` is a paragraph of its own text box, a direct child of its `<text>` at the text's `x`, because DrawingML's paragraphs share their box's position. The framework now records section 4.4's per-node skip. A rule that needs `measure` gets a context whose `measure(n)` records one skip naming the rule and the element when the estimator answers `None`, so text nobody could measure leaves the gate `unverified`, never `passed`. D794 builds the document band's type-size budget. The framework fills `DocIndex.value_occurrences["type_size"]`, counting every `font-size` a unit states, attribute or style, by its value in user units, summed across the roster. Type size is CSS's `font-size` in both carriers, so the framework counts it once rather than each target. `pptx.type.budget@1` (order 90, a document rule at the final stage) reads the Brief's numeric `## typography` values as anchors. A size within 2 of an anchor is declared. Any other size's second occurrence across the deck is a warning and its third an error (`OW_TARGET_TYPE_SIZE_UNDECLARED`, `OW-T-430`), at `limits["undeclared_size_max"]`, 2. A Brief that names no size sets no budget, as ppt-master's check runs only when its spec declares sizes.

**Validator rules, the ones with teeth** (~180 constructs, ~60 rule files):

| band | rules |
|---|---|
| structural | one `<svg>` root per unit; the `viewBox` matches the `Brief`'s `## canvas - format` (a Brief fact, **not** a card key — `[compile]` is hard-error-on-unknown-key and has no `format`); `data-ow-el` present on every citable and every text-bearing element and unique per unit |
| forbidden | `<script>` and event attributes (`OW-T-401`); `<foreignObject>` (use `<tspan>` for manual line breaks); `<textPath>` (path text has no PPT equivalent); `<iframe>`; `<style>`, `class` and `<link rel="stylesheet">`; `id=` **when** `<style>` is present (`OW-T-402`) |
| grammar | path data and point lists complete; the transform grammar and its native mappings; opacity and native alpha; gradient definitions, stops and coordinates; `<pattern>` declares a PPTX preset |
| measurement | text capacity per positioned line under `measure.py`'s uharfbuzz shaping — and the rule's `msg` states its model: single-line width per positioned line, vertical wrapping is not modeled |
| reference | every `use` reference resolves locally; every `asset-slot:` resolves in the ledger; every icon placeholder resolves **before** post-processing |
| document | the third occurrence of an undeclared type size is an error, the second a warning, the first silent (`RuleCtx.limits["undeclared_size_max"] = 2`, counted across units in `DocIndex.value_occurrences`) |

**The compiler.** `lower/drawingml/` per DrawingML family; `charts.py` via XlsxWriter; `boolean.py`
via skia-pathops for the path operations DrawingML has no operator for; `media.py` for media parts;
`pack.py` builds the part graph and calls `write_opc()`. Preflight per §5.1; package validation per
§5.3 with `zip_integrity`, `slide_count`, `internal_relationships: enforced-at-build`. D795 builds the compiler's first families. Preflight check 1 and the normalize refusal move to `omniweave_core.out.lowering`, which docx now uses too. A `maps_to` resolves to a callable its family module exports, and only the constructs a unit uses are asked, so a table may declare rows its lowering has not built. A unit using one is refused (`OW_TARGET_CONSTRUCT_UNMAPPED`). `lower/` holds one module a `maps_to` family (`lower.shapes:rect`), as docx's does, rather than a `drawingml/` folder. It draws: the slide; groups as `p:grpSp` whose child frame is their own frame; `rect`, `roundRect`, `ellipse` and `line` presets; solid fill and line paint, with `opacity` multiplied down the chain and each opacity clamped to 0 to 1; a stroke's width, dash, cap and join; and `translate`, `scale`, `rotate` and `matrix`, decomposed into a box, a turn and a flip. Every unit's `viewBox` must be one slide size (`OW_TARGET_CANVAS_MISMATCH`). The package drops the template's thumbnail, its 4:3 `sldSz` type and its app properties, and takes `dcterms` from the job's clock. `_pack` checks the package it builds, so `internal_relationships` is `enforced-at-build`, with the fixture that breaks the part graph. `postflight()` re-reads `zip_integrity`, `slide_count`, `content_types` and the slide size. The card stays `implemented = false` until text, paths, gradients, patterns, effects, pictures and links are lowered. D796 lowers freeforms. A `<path>`, `<polygon>` or `<polyline>` is one `a:custGeom`. Its points, control points included, take the node's matrix and are written in EMU from the corner of the points' box, and an axis with no extent gets a path one EMU across. `d` is read by the gate's own grammar (`rules.path_data.segments`) and drawn as SVG 1.1 section 8.3 draws it: relative commands are relative, `M`'s later pairs are lines, `S` and `T` reflect a cubic's or a quadratic's control point, and a command after `Z` starts with a move. An arc becomes cubics by SVG's implementation notes F.6.5 and F.6.6, at most a quarter turn a piece, since `a:arcTo` has no axis rotation. A zero radius is a line, and an arc to its own start draws nothing. `points` is read by `rules.points.pairs`, the gate's grammar. D797 lowers text. A `<text>` is one text box (`txBox`, `wrap="none"`, no insets, no autofit), and each positioned line is a paragraph. The lines are `textlines`', the model `measure.py` shapes, moved out of it free of uharfbuzz so the compiler and the checker read the same lines. The compile reads no font, so the box is a model. `text-anchor` is `algn`, with the frame's left edge, centre or right edge at `x`. The frame's width is 0.6 em a character of the widest line. Each paragraph's spacing is exact: the first's is 1.2 em of its largest run, and each later one's is its distance from the baseline before. The box's top is the first baseline less 0.8 of the first line's spacing. A run is an `a:r` with its owner's inherited properties: `sz` and `spc` at px x 75, `b` from a weight of 600, `i`, `u` and `strike`, `baseline` 30% for `super` and -25% for `sub`, and the shapes' fill and line paint. Its face is the stack's first family that is not a CSS generic, and its `lang` is the Brief's primary language. `pptx.text.lines@1` now also refuses what one text box cannot draw: a non-zero `dx`, a `y` on a run that starts no line, and a line whose baseline is not below the one before. D798 lowers paint servers. A `url(#id)` fill or line resolves through the slide's ids to a gradient or a pattern, and an id that names nothing, or no paint, is refused as `pptx.reference@1` refuses it. A linear gradient is `a:lin scaled="1"`, its angle read in the unit box. DrawingML runs it across the whole box, so each stop moves to where SVG's run from `(x1, y1)` to `(x2, y2)` puts it on the box's projection. A radial is a circle path from its focus (`a:fillToRect`), and its stops scale by `2r`, so the default `r = 0.5` maps one to one. A stop's alpha is its `stop-opacity` times the shape's. A pattern is `a:pattFill` of its `data-ow-preset` and its two colours. `rotWithShape` turns a preset's gradient with it, and a freeform's angle is turned by its matrix. D799 lowers effects. A filter is the shape's `a:effectLst`: a shape's in `p:spPr`, a group's in `p:grpSpPr`, and a text's in each run's `a:rPr`. Its blur radius is two deviations, and each length grows with the matrix. `<feDropShadow>` is an `a:outerShdw` at `hypot(dx, dy)` and `atan2(dy, dx)`, turning with its shape as SVG's local filter space does. `<feGaussianBlur>` is an `a:glow`, coloured by its `flood-color`, else by the shape's own solid fill. A marker is the line's `a:headEnd` or `a:tailEnd`. Its type is the shape it holds: an oval, a diamond, an open arrow or a triangle. Its size is bucketed in stroke widths into DrawingML's `sm`, `med` and `lg`. `refX` and `refY` have no DrawingML equivalent. The paint resolver becomes `_style.named()`, which resolves paints, filters and markers alike. D800 lowers pictures. Preflight check 2 reads each `<image>`'s `asset-slot:` from the ledger (`OW_TARGET_ASSET_UNFROZEN`) and refuses a picture PowerPoint cannot hold (`OW_TARGET_ASSET_FORMAT`). An image is a `p:pic` whose part python-pptx adds and dedupes. Three boxes place it: the viewport; the shown image, fitted by `preserveAspectRatio` (`meet`, `slice` or `none`, aligned at min, mid or max); and what is seen, which is the clip's box, else the viewport and the shown image's overlap. The picture sits at what is seen, and `a:srcRect` crops the shown image to it, so `slice` crops what spills past the viewport and a clip crops to its shape's box. A clip's shape is the picture's geometry: an ellipse, a rect or roundRect, or a freeform. A picture's `opacity` is `a:alphaModFix`, and its filter is its effect list. D801 lowers `<use>` and links. A `<use>` is a group named by its own address, holding a clone of what it names. A `<symbol>`'s clone is its content. The clone inherits from the `<use>`, as SVG clones it as the use's child. The use's `x` and `y`, and the symbol's `viewBox` fitted into the use's box, are the matrix's. A clone's shapes take no address, since the address is its original's and may not repeat, and a `<use>` that reaches itself is refused. An `<a>` puts an `a:hlinkClick` on every shape it holds. A page is an external hyperlink, and `#u<NN>` is a relationship to that unit's slide with PowerPoint's `ppaction://hlinksldjump`, so every slide is made before any is lowered. A unit the deck lacks is refused, and the inner link of two wins. `tools/egress.toml` gains the `ppaction://` row. D802 lowers the last of the table's families, and the card says `implemented = true`. The embedded citation channel moves to the framework, `omniweave_core.out.provenance`, which docx now uses too. Its parts are: the rows for each cited element and cite, with their pinned `doc_gen`; the kind and span grammars; `els`, each address's construct; the canonical body; and the receipt's `citations_channel` row, read from the part. A deck writes `customXml/omniweave-provenance.json` from it, related from the package root, whether or not anything is cited. A manual region is a group of its own content, named by its address and described `ow:manual <reason>`, with a dashed outline over its box, so a draft's placeholder is found in the slide and in the selection pane. The probe is `OK`, and `ow out compile` lowers a deck. D803 readies the deck for its reader. The text model's whitespace becomes the carrier's `collapse`: a newline is whitespace like a space or a tab, and `xml:space="preserve"` keeps every character. D792 had dropped a newline, as SVG 1.1 does, so two source lines lowered as one word while `visible_text`, which R2 compares, read a space. An `<a>` is a group named by its address, since `kind_map.toml` makes it a container and an address needs a shape. A click sits on its shapes and never on a group, as PowerPoint holds one; D801's clicks on groups were a defect python-pptx refuses to read. The provenance part gains `at`, where each address landed: its unit, its shape's id, and for a `<tspan>` its paragraph and run range, since a run has no name to carry an address. Read back, each located range is its element's `visible_text`. D804 builds the read_back: `parse.pptx.native`, a card in `omniweave_target_pptx.back` with its own entry point, the package this section's registry names. It reads only what `lower/` writes. Each slide, in the presentation's order, is a `slide` page and a `section`; a group is a `container`, a text box a `paragraph`, a picture a `picture` and any other shape a `diagram`, unless an address's construct names its kind. A `<use>` group's clone is not read, since the IL holds its text once. `at` names a slide by its number rather than its unit, since a reader sees slides, and records a preserved text, since the reader collapses a run's text as the carrier does unless it is preserved. A manual region's outline is a `comment` on the annotation layer, a page root after its slide's section, because M-INV-5 lets only a page root name its own layer. Each page's record comes before its blocks, as the store's sink takes them. A `.pptx` with no provenance part is refused as `CORRUPT_INPUT`. R2 holds over the IL, and the store takes the read-back as an ingest would. D805 gives the pptx target its golden fixture, `fixtures/out/golden/pptx/`: two slides that use every `exact` row of owsvg/1, a manual region, a cite with its kind and span, and a frozen picture. Its text names `Probe Sans`, the face the tests write, so the measurement band runs and the gate is `manual-required` rather than `unverified`. Through the target suite with `parse.pptx.native`, R1, R2 and R7 pass, and R5's third and fourth clauses hold. Eleven attribute rows that only a filter primitive or a marker holds (`stdDeviation`, the `flood-*` pair and its two `style` forms, `orient`, `markerWidth`, `markerHeight`, `markerUnits`, `refX` and `refY`) said `exact`, but `il_digest_rt` elides their host whole, so no mutation of them could move it. They are now `normalized`, as their hosts are. An exact construct's first use must stand outside every non-exact element, so the golden keeps its filters, its marker and its symbol on the second slide. R4 is `unknown`, saying the suite compiles from IL alone; pptx is the first card to claim it. D806 makes the faces settable. D792's card declared `font_dirs` a list, and the config layer refused it: a driver's configuration is flat scalars, as every Port's `__init__(**config: Scalar)` is. So no face could be named, every measurement rule was a recorded skip, and no deck passed `ow out check`. `font_dir` now names one absolute directory, read with its subdirectories. With it set, a deck is checked, compiled in a worker, and read back by `ow out back`, which closes the loop through `parse.pptx.native` and maps every address. Found: the skip's fix names `ow out targets`, which reports no target's unmet needs. D807 makes that fix lead somewhere. When a card declares a `measure` other than `none` and a `[config]`, `ow out check` hands the framework a fix that sets those keys under `drivers."<id>".config`, which for pptx is `font_dir`. A need the card names no setting for keeps the framework's fix. D808 builds R4 in the target suite. A card claiming `fidelity = "passthrough"` names the part each unit lowers to, `[compile.round_trip] unit_part`, required exactly then; pptx's is `ppt/slides/slide{ord}.xml`. R4(a) compiles the golden, then compiles it again as the next generation with each unit edited from itself, and every unit's part must be its source's, byte for byte. R4(b) recompiles with the golden's `edit/` in place, and every unit the edit does not touch must be `passthrough` or `patched`, its part its source's. The outcomes are the receipt's, and an `edit/` that changes nothing is an `unedited` failure. A `manual_required` unit is exempt from both halves, since section 5.5's classifier places it first whatever the edits. owsvg/1's golden passes: its lowering is deterministic, so an untouched slide is byte-identical across generations, which is the copy section 5.5 defines, observed rather than performed. Found: an edit's `source_part` is the unit's IL path rather than the container part section 3.7 names, and the compile does not yet assert R4(a) when it seals. D809 makes the seal assert it. An edit's Plan names the generation it restores, `parent_gen`, which `ow out back` writes and the seal records as `parent_artifact_gen`. Section 3.7's Plan names no such field, and a unit's `source_part` named a part without saying whose. `source_part` is now the container part the card's `unit_part` names, `ppt/slides/slide3.xml`. Before the seal, each `passthrough` or `cloned_passthrough` unit's part is read beside the part its `source_ord` lowered to in the parent, fetched from CAS, and the two must be the same byte for byte. Otherwise the compile is refused as `OW_TARGET_COPY_MOVED` (`OW-T-530`) and nothing is sealed. A deck that is checked, compiled, restored, edited in one slide and recompiled seals its next generation with the untouched slide `passthrough`, byte for byte its parent's. D810 builds seam S2's Python half for the `deck` target, `omniweave_core.toolchain.run()`. It resolves node on 11-repo-layout's ladder, or raises `CapabilityMissing` (exit 64) naming the install. It hashes the installed archive, kept in `$OMNIWEAVE_HOME/toolchains/<name>@<version>-<sha256>/`, against the register's full sha256 on every invocation, and runs the entry it just verified. The child is spawned with the JobDir as its `cwd` and an allowlisted environment, and on Windows it is born suspended in a job object. The exchange is `hello`, `ready` (naming the spec's toolchain and version), the request, `progress`* and one `result` of `ok` or `blocked`, then `bye`. stdout carries only JSON-object frames, under 1 MiB in all, while stderr goes to a ring that is never parsed. One deadline from the injected clock bounds it all, and any break reaps the tree. A `compile` exits 0 iff it wrote its receipt, and a child exiting 64, even before its `ready`, has no runtime of its own. Found: section 12.2's measurement needs a browser-grade layout engine inside a bundle that "carries no binary", which no release-1 Toolchain can yet resolve. D811 closes INV-16 at ingest. The parse operator had handed its sink no restriction bits, so every ingested block carried 0 and the compile's restriction aggregate (OUT11) had nothing to bar. It now stamps each block and asset with the granted card's bits, the OR over its code and weights tables, which the segmenter and the graph sink already carry into what they derive. A card with a restricted licence is tested parse to derive to compile: its blocks and segments carry its bit, and the aggregate bars each cited block under a policy that denies that bit. D812 runs the conformance kit over both read_backs, which no cell had done, each over its golden compiled. Both readers now check `io.cancelled()` at their loop tops and report progress after them: pptx at each slide, docx after the body. Neither card declares `format_tokens` any more, because core's table maps both media types and a pair is a claim `sniff()` must back, which a read_back reached by name never does. docx's card says `marks = true`, since a note reference is a mark. pptx's `max_input_bytes` is 64 MiB, under the host's ceiling, and its package declares the `lxml` it imports. docx's read_back passes the kit's mandatory tier. pptx's fails only the licence suite, on Pillow's `MIT-CMU` and uharfbuzz's non-SPDX licence string, which are G3's open allowlist question.

**Round-trip fidelity: `passthrough`.** R1-R7 all apply. R4(a) is the load-bearing one: `read_back`
then compile with zero edits produces 100 % `passthrough`/`cloned_passthrough` units with each
copied part's sha256 asserted equal. `read_back` is `parse.pptx.native` over python-pptx, and it
carries the API-stability disclosure ppt-master models: private attribute access
(`run._r` for internal-jump hyperlinks, `series._element` for XY and bubble data) is documented in
the module docstring with the reason the public API cannot serve, so an upgrade knows what to check.

**Open problems.** `bake` is `unavailable` at release 1 and fails closed with both exits named,
because `cairosvg` and `svglib` are both LGPL-3.0 and `cairosvg` is G3's named regression fixture
(imported by ppt-master's `media.py:15` and declared in no requirements file). `project()` for
foreign decks must invent an SVG subset from DrawingML and nothing in the mined collection does that
— Q2. `part` determinism across nine cells is unmeasured — Q1. Every OOXML Block from the office
parse path is `quote = normalized` at release 1, so a `pptx` artefact's `read_back` blocks cannot be
`verbatim` until anydoc emits a node path (the first named clause of
`vendor/anydoc/FORK-TRIGGER.md`), which is why §10's verbatim rule fails closed on the second
conjunct rather than being relaxed. *(Build note, D876: the two exits are `omniweave_core.out.manual.BAKE_EXITS`, one wording that both the table's order-24 finding and owtext's preflight-5 refusal append. Exit one rewrites the construct as a spelling the table maps natively. Exit two replaces it with an `ow:manual` region, `data-ow-manual="unrepresentable"` (section 9's row for *"a construct with no `native` row and no reachable `bake`"*), and the gate holds the unit at `manual-required` until `--accept-manual`. The region must replace the construct, not wrap it, because an error inside a region fails the gate first. On pptx, a `mix-blend-mode` slide fails naming both exits, its native rewrite passes, and its region reaches `manual-required` with no finding. V10-9 runs that test.)*

### 12.2 `deck` — carrier `html`, IL `owdeck/1`, a Toolchain target

**The IL.** A closed HTML subset over a declared design-token set, one `<section>` per page. The
carrier is `html` and the parser is `carrier/html.py`. Layout is CSS, which is precisely why this
target has **runtime rules**.

**Validator rules.** ~90 constructs, plus the release-1 answer to open-slide's decisive weakness:
open-slide's only gates are `tsc --noEmit` and biome — *is this valid TypeScript*, never *is this a
valid slide* — and in a scaffolded project not even those, since `apply-comments/SKILL.md` records
that *"scaffolded projects ship neither TypeScript nor a linter"*. Every one of the following is
mechanically checkable and is a `deck` rule:

| rule | why open-slide cannot |
|---|---|
| content fits the declared page box | needs a measurement engine; hence `runtime_rules = true` |
| every design token referenced is declared | a token registry the validator reads |
| notes are attached to their page as a record, never a parallel index-keyed array | open-slide's `export default [Cover, Body]` plus a parallel `notes` array is the failure its own docs warn about twice — *"a shifted index silently attaches the wrong script to every page after it"* |
| a staged reveal element sits inside a stage container | a containment rule |
| every asset reference resolves | `asset-slot:` plus the ledger |
| the unit roster is contiguous, ordered and unique | roster completeness at `order = 90` |

`runtime_rules = true` means the target gets a `validate` frame over `omniweave-target/1`: the
Toolchain child measures with `getBoundingClientRect` in an off-canvas pass and returns `Finding`s
over the wire, with `code` as the **symbol** (§5 C9). The child's `result` frame does carry a
per-request `status` (`ok` | `blocked`) — that is a *frame* outcome saying whether the child
completed the request — and the framework computes the ten-value `GateStatus` itself from the
returned findings. A child cannot pass its own gate, because a child cannot produce a
`GateStatus` at all: `blocked` is not one of the ten values.

**The compiler.** `lower` runs through `io.service("toolchain:deck") -> ToolchainHandle`, whose
`.run(job_dir, timeout_s)` **is** `omniweave_core.toolchain.run` executed in the host process, so
G8's one-subprocess-site rule and the non-extensible `DriverIO` both hold. The job directory is the
S2 data plane: `job.json`, `brief.md`, `il/`, `assets/`, `validation/`, `out/`. Blobs never travel on
stdio; stdout is control only and under 1 MiB; stderr is a log drained to a bounded ring tail and
never parsed; **exit 0 iff a receipt was written**. A `SIGTERM` at timeout, `SIGKILL` at +5 s and the
whole process group reaped leaves the JobDir intact and no `artifact` row — the same failure shape as
any other `lower()` abort (§2).

**Round-trip fidelity: `structure`.** R4 does not apply — there are no container parts to copy, so
`passthrough` is not expressible and claiming it would be a lie; the card therefore may not list
`r4`, and the kit refuses it if it does (§11.4). R1, R2, R3, R5, R6, R7 apply.
`determinism = ["render", "part"]`: the `render` class is a sampled paint tree and measured layout at
sampled times, pinned to the toolchain digest.

**Open problems.** Q3: whether any rasterizer clears `tools/licences.toml` at an acceptable install
weight — and if none does, `bake` stays `unavailable` on every target, at which point a disposition
tier with **zero live rows** is a reason to demote `bake` to `forbidden` with a documented
degradation rather than keep a tier nothing implements. Q5: the child owns the only measurement, so
OUT2's one-implementation guarantee holds by process boundary rather than by construction. Toolchain
install weight and the offline story are `ow targets install`'s, with the digest **in the path** and
verified on every invocation.

### 12.3 `docx` — carrier `html`, IL `owflow/1`

**Why it is in the release-1 set.** It is the falsification test. A flow document has no canvas, no
z-order, no `viewBox`, no absolute geometry and no bake tier. If the OUT framework could only express
`pptx` and `deck`, `docx` would not fit, and the `GeneratorTarget` rejection would be wrong. The
`unit` is a `section` — a run of flowed content between section breaks — not a page, because page
breaks in a flow document are computed by the renderer and are not an authoring address.

**The IL.** A closed HTML subset: block-level structure (headings, paragraphs, lists, tables,
blockquotes, code), inline marks from the declared set, footnote and endnote elements, and a section
element carrying `ow:unit`. No positioning constructs at all — the ConstructTable has **no**
`selector` matching a geometry attribute, which is what makes the ~70-row table small.

**Validator rules.** Heading level monotonicity (no `h1` → `h3` jump — a structural contract, not a
style preference); table cell topology declared consistently (`row_span`/`col_span` cover exactly);
footnote references resolve to footnote bodies within the same unit; list nesting depth within the
declared limit; every `asset-slot:` resolves; no positioning construct present (the `forbidden` rows
that make "this is a flow carrier" checkable rather than aspirational). D781 builds the table, the carrier and the rules in `omniweave_target_docx`. `constructs.toml` is owflow/1's 83 rows in ten groups: `ow`, `block`, `inline`, `lang`, `list`, `table`, `note`, `media`, `pos` and `forbid`. It has no bake row and three normalize rows. A note is an empty `<a data-ow-note>` and an `<aside data-ow-footnote>` or `<aside data-ow-endnote>` body, which the carrier treats as invisible. `omniweave_core.out.conformance.table_pack()` builds the forbidden, `forbidden_when`, closed-set and normalize rules from any table. The `pos.*` rows are the sixth rule here, as `OW_TARGET_POSITIONING_FORBIDDEN`. `rules.py` holds the other five, and adds the unit root, `data-ow-el` uniqueness, a content model and the cite batch. Heading monotonicity is checked within a unit, because `DocIndex` carries no heading levels. The list limit is WordprocessingML's nine levels. `asset-slot:` resolution is two checks: the rule holds the grammar (`OW-T-112`), and preflight 2 holds the ledger. `RuleCtx` has no ledger, and a rule needing `assets` would hold every docx gate at `unverified`. Lowering comes next, so the card says `implemented = false`. `load_table()` now refuses only a card that names no table, and `ow out compile` refuses an unimplemented target before its gate. Registered: `OW-T-212` to `214`, and `OW-T-412` to `418`. Found: 09's `CarrierNode` had no way to list a node's attributes, which the closed set needs, so it gains `attrs()`.

**The compiler.** `lower/` maps to WordprocessingML through python-docx and lxml, then `write_opc()`.
The OPC rules are identical to `pptx`'s — `dcterms` from `job.determinism.clock_ns`,
`cp:revision="1"`, **no `w:rsid*`**, sorted attributes — and the shared `opc.py` is why they cannot
drift between the two targets. D782 builds `omniweave_target_docx.lower`, one module for each construct family. A module exports exactly the functions the table's `maps_to` names in it, and a test holds both directions (OUT1). The walk dispatches each element to its row's function, so preflight check 1 is the table resolving. A module is found among the family modules the packer imports, never imported by name, because `importlib.import_module` is the host's alone (INV-4). The text follows HTML's whitespace rule across runs, so a paragraph's text is the carrier's visible text. Each `data-ow-el` is a bookmark (`ow_u01_e3`) inside the paragraphs it spans. Each unit after the first follows a continuous section break, and postflight counts `w:sectPr` against `unit_count`. A list is its own `w:num`, nine levels deep. A table is laid out by HTML's table model and merged. A picture is scaled to fit the text column in whole EMUs. The Brief's canvas `format` names the page (`A4`, `letter` and two others); any other value is letter, with a receipt warning. The package is python-docx's template less its thumbnail, its bibliography `customXml` and `stylesWithEffects`, which go with their relationships. Every `w:rsid*` attribute and `w:rsid` element is stripped, `dcterms` are `job.json`'s clock (read from the JobDir, since `lower()` is handed none), the app properties are fixed and every attribute map is sorted. Two compiles are one package byte for byte, and a child under another `PYTHONHASHSEED` gets the same part digest. Preflight also refuses a value a normalize row would rewrite (`OW-T-505`), and an asset Word cannot hold, as `OW-T-528 OW_TARGET_ASSET_FORMAT` (appended). Notes and embedded citations are D783's, so preflight refuses them as unmapped and the card stays `implemented = false`. Found: 09's `CarrierNode` could not give a node's text and children in order, so it gains `contents()`. Word 2010's styles also carry `w:rsid` as an element, which the rule's attribute spelling misses.

**Round-trip fidelity: `patched`.** R1, R2, R3, R5, R6, R7. Not `passthrough`, because a flow
document's section parts are not independently copyable the way a slide part is: an edit in section 2
can reflow section 3's page break. `patched` is the honest tier — non-visual edits are applied to the
source part in place; anything else is `rebuilt`. `visual_changed()` (§5.5) therefore does most of
the work in this target, and the ConstructTable's `visual` flag matters more here than anywhere
else — and R3 applies because R3 is a predicate over `content_digest` and carries no geometry: §11's
condition reads `fidelity ∈ {structure, passthrough, patched}`, every value but `none`.

**Open problems.** Change tracking (`w:ins` / `w:del`) has no IL representation at release 1 and
therefore no construct row, so a source `.docx` with tracked changes hits R6's blocking refusal
naming the part paths. Comments (`w:comment`) round-trip as `Kind.COMMENT` Blocks on
`Layer.ANNOTATION` but have no authoring construct, so they survive a read and cannot be authored.
Both are declared limitations with named rows, not silent gaps. D783 lowers notes and embedded citations, the last two, so the card is `implemented = true` and its probe is OK. A note body is skipped where it stands, because its row says `visible = false`. It is written when its reference is met, into `word/footnotes.xml` or `word/endnotes.xml`, with Word's two separator notes and its own note styles, and numbered in reference order. It goes through the same walk with the reference's paragraph, marks, lists and scopes set aside, so nothing the reference stands inside reaches the note. `project()` refuses by name (`OW-T-411`), as owtext's does. owflow/1 gains `ow.cite.kind` and `ow.cite.span`, for the `data-ow-cite-kind` and `data-ow-cite-span` that the compile already reads (D772). `docx.cite.facts@1` checks them at the gate as `OW-T-400`, the code the compile refuses them with.

### 12.4 `video` — the v2 target, and its seam

`omniweave-target-video` **ships at release 1 with `[compile] implemented = false`**, and that is a
deliberate, load-bearing choice rather than a placeholder.

- `[compile]` is a **hard-error-on-unknown-key** table precisely so an older core cannot silently
  drop `implemented = false` and treat the driver as implemented with unbounded units (§5 X37).
  `[capability.compile]` keeps the ignore-with-degradation asymmetry, because its keys are all
  set-valued floors where an unrecognised member can only make a driver look *less* capable.
- `ow out targets` prints the target, the flag and **the reason**: the hyperframes mining was never
  written, and a construct table designed from an index page is exactly the speculative generality
  §D8 refuses. D760 ships the card at `omniweave_target_video/driver.toml`, with entry points under `omniweave.drivers` and `omniweave.targets`, and a `VideoCompiler` whose probe is `unavailable` and whose every method refuses with `OW-T-514 OW_TARGET_NOT_IMPLEMENTED` (appended), quoting the card's reason. `omniweave_core.out.card` reads `[compile]` the way this section says: closed, so an unknown or missing key, a value outside its vocabulary, or laws the fidelity forbids is `OW_CARD_INVALID`. `[capability.compile]` drops an unknown class or role with a recorded degradation, and `part` is required. `[compile]` gains one key, `reason`, required exactly when `implemented = false`, because no printed card had a place for the reason this bullet says is printed. `targets()` gives the rows `ow out targets` prints, and `as_json()` gives the shape 16-roadmap's exit criterion reads. The verb itself waits for W9.9's `out` group, because the generated CLI tree has none yet. Found: the table below lists R2 for video, but R2 needs `fidelity != none` (section 11.1), and video's fidelity is `none`, so the card claims R1, R5, R6 and R7. D761 lands the verb as W9.9's first `out` Action: `out.targets`, MCP `ow_targets` in the `full` roster. It lists every compile card discovery finds (entry points, `OMNIWEAVE_DRIVER_PATH`, the project's `.omniweave/drivers/`) and adds whether `[targets] enabled` lists the kind, so a row names which of the two stops a kind compiling. `--render json` prints the bare array 16-roadmap's exit criterion reads. Each row carries the determinism class 10-interfaces' roster names. A card discovery refuses is counted on stderr and never listed. `--corpus` is inert and `--quiet` is refused by name, as are `--render jsonl` and `--render rows`. D770: `[compile]` gains `media_type` and `suffix`, both required of an implemented target. The `artifact` row's `media_type` is `NOT NULL`, the sealed path is `<slug>@<gen>/<slug><suffix>`, and no printed card had a key for either. The API sketch's `[capability] formats` is parse routing's input type, not a compile's output type. owtext declares `text/plain` and `.txt`. `CompileHost.of()` reads a real run's host off the card: the two keys, and the restriction bits ORed over the licence tables (INV-16). `barred_mask` is 0 until 14 gives a policy one, and the producer comes from `store.artifact.ensure_producer()`.

The seam is fully specified even though the target is not:

| aspect | the decision, at release 1 |
|---|---|
| carrier / IL | `html` / `owmotion/1` |
| `unit` | `scene` |
| `determinism` | `["frame"]` — 12 deterministically sampled decoded frames plus the full PCM, pinned `(ffmpeg, codec, threads)` |
| `citations` | `sidecar` — a video container has no place to put a provenance part that survives a re-encode |
| `laws` | R3 is **refused** because `fidelity = "none"` is §11's one exemption: a lossy encode is not idempotent, so a second-round fixed point over decoded content is not achievable. R1, R2, R5, R6, R7 apply |
| toolchain | `ffmpeg = "system"`, never bundled — libx264 makes a deploy artefact GPL-2.0-or-later |
| codec | `vp9`; h264 is an operator-owned opt-in, never a fallback |
| missing codec | **refuse rather than substitute**: libvpx/AV1 absent ⇒ refuse the target, with the install command |

The determinism contract is the whole reason `video` is hard, and hyperframes states it correctly:
to render frame-by-frame offline the renderer must jump to time *t* and get exactly the same pixels
every time, which forbids anything time-dependent, random or stateful — so **the framework owns
media playback**, because a `<video>` element playing itself is not seekable. That is the seam: an
`owmotion/1` ConstructTable's first job is to make "self-playing media" a `forbidden` row.

### 12.5 `compile.text.owtext` — the reference target

Inside `omniweave-conform`, ~10 constructs, whose job is to exercise the contract's **refusal
branches** in CI without a browser: `citations = "sidecar"`, `fidelity = "none"`,
`bake = "unavailable"`, `measure = "none"` (so `unverified` is reachable), one `normalize` row, one
conditional `forbidden_when` row, and one `bake` row that is unreachable. It is also the fixture for
every failure path in §14: an IL file over `MAX_IL_FILE_BYTES`, a rule that emits past
`MAX_FINDINGS_PER_RULE`, a marker with a corrupt payload, a roster mismatch in each of its three
directions, and a `lower()` that raises halfway. `ow out scaffold` generates its shape, which is also
how a third-party target author starts. D758 builds it at `omniweave_conform/suites/target/owtext/`, as 18-api-sketch.md section 6.2 prints it: the card, which loads through `load_card()` with `[compile]` carried whole, the ten-row `constructs.toml`, `kind_map.toml`, `normalizers.py` and `driver.py`. The sketch's `ignore = ["html:head", "html:meta"]` is refused by the selector grammar, which spells a namespace `ns|local`, and is `html|head` here. The cite rule batches once per unit at order 80, as section 10 asks, where the sketch calls `by_cite()` per token. `postflight()` takes the receipt's hex through `receipt_part_digest()`, where the sketch calls `.hex()` on a string. `lower()` refuses the unreachable `text-shadow` bake row as preflight check 5. The six construct codes the table names and `codes.toml` lacked are registered: `OW-T-103`, `211`, `312`, `403`, `404` and `406`, each in its siblings' band. A runner test compiles and seals the reference target end to end.

## 13. The generation workflow

### 13.1 Scope confirmation before work

The four scoping questions, taken from open-slide's `create-slide` skill, whose design is the best in
the collection and whose persistence is the worst. **Topic comes first**: a meaningful aesthetic
recommendation requires knowing what the artefact is about, so a thin request ("make me a deck") gets
a *separate* question gathering topic, audience and any draft outline before the four.

| # | question | why it is one of the four | shape of the options |
|---|---|---|---|
| 1 | **direction** | collapses palette, type scale, motif and asset needs at once | 3 options **generated for this topic**, never from a preset list; each is a vibe word **plus a concrete visual cue**; the three must be meaningfully different, not three flavours of one idea; the best fit is marked `(Recommended)` |
| 2 | **unit count** | bounds the whole job and the budget | brackets: 3-5 short · 6-10 standard · 11-20 deep |
| 3 | **density per unit** | **directly drives type scale and layout** | minimal (one line or one number) · light · standard · dense (multi-column) |
| 4 | **motion** | decides whether animation constructs are loaded at all | static · subtle · rich |

Four rules that make this a protocol and not a questionnaire:

1. **Asked in one call**, bounded to four.
2. **Skip a question only when it is already unambiguously answered** — by the user's own message or
   by a chosen theme — **and if you skip, restate the assumption so it can be corrected.**
3. **Follow-ups only if still unclear** (brand colours, required assets). Do not pad the conversation
   with questions already answered.
4. `(Recommended)` means silence is a valid answer.

**Router-level brief confirmation.** hyperframes' router skill is simultaneously the capability map
and the intent layer that confirms every creation brief up front, so a misunderstanding costs one
exchange rather than one render. omniweave's core skill is a router (≤ 150 lines, a state table, a
route table, ambiguities) and confirms the `Brief` before dispatching to a route; the route bodies
are installed on demand. The full skill topology is [interfaces](10-interfaces.md)'s.

### 13.2 Spec locking after confirmation: the `Brief`

open-slide's gap is exact and worth naming: the answers to the four questions are never written to a
file. They live in the conversation, so a fresh session has nothing to re-read and re-derives — or
silently contradicts — the confirmed direction. The `Brief` closes it.

```text
<!-- omniweave-schema: brief/1 -->
# Brief

## canvas
- format: 16:9
- unit: slide
## communication
- primary_language: en-GB          # canonical BCP-47; `und` and a script-less Chinese are REJECTED
- audience: the board, non-technical
- objective: approve the FY26 budget envelope
- core_message: the envelope holds if hiring slips one quarter
## direction
- vibe: confident editorial
- cue: large display serif, tight grid, one bold accent
## density
- per_unit: light
## motion
- level: subtle
## typography
- title_family: <family>
- body_family: <family>
- body: 20
- title: 44
## rhythm
- u01: { anchor: cover,   dense: false, breathing: wide }
- u02: { anchor: content, dense: false, breathing: normal }
## forbidden
- <script>, <style>, class=, external CSS, @font-face
- no shadows and no glow anywhere (user)
```

**The format is two productions and nothing else.** A schema-version comment on line 1, then only
`## section` headings and `- key: value` rows. The exception is `## forbidden`, whose items are
literal rules. Human-diffable, machine-parseable by `parse_brief()`, and `ow out check` validates it.
This is ppt-master's `spec_lock.md` grammar, adopted whole. `## template` (§4.1) is the one optional
section; every other section is required and `parse_brief()` names the missing one.

**Three tiers of prohibition, each with a different owner and a different escalation path:**

| tier | tag | source | escalation |
|---|---|---|---|
| technical baseline | untagged | derived from the ConstructTable's `forbidden` rows | change the ConstructTable |
| user prohibition | **`(user)`** | the user's own sentence, **verbatim, never a paraphrase, never widened** | ask the user |
| template rule | — | stays in the template's own installed spec; **never copied here** | change the template |

`parse_brief()` **rejects an untagged non-baseline row.** That single check is what stops a designer
opinion being smuggled into the hard-constraint list, and it is why the `(user)` tag is machine-
enforced rather than a convention: "untagged" is checkable because the baseline tier is *generated*
from the ConstructTable's `forbidden` rows, so an untagged row that is not in that generated set is a
row somebody invented. A confirmed *direction* — even one the user approved — is identity prose in
`## direction`, not a prohibition; nothing is projected from it into `## forbidden`.

**Four enforcement rules around the Brief:**

1. **The role that consumes it cannot write it.** The authoring agent reads the Brief and never edits
   it. `ow out check` treats a `brief_digest` change mid-run as `stale`.
2. **`brief_digest` is one of the six purity inputs.** Changing the Brief is a new `artifact_gen`,
   never a patch.
3. **Scheduled re-read to fight long-context drift.** After every fifth unit, when another unit
   follows, the authoring agent re-reads the Brief in full **once** — a pure re-anchor of palette,
   typography and rhythm, with **no checker run, no output, no pause and no repair loop**. A
   scheduled contract re-read with explicitly no side effects.
4. **A numeric drift budget, with the checker enforcing exactly it.** A declared typographic anchor
   may be used at the anchor or within `±2px`. A short non-structural size may stay undeclared while
   the same value appears **at most twice**; its **third occurrence needs a named role** and is an
   error. One-off exceptions are fine; a *pattern* of exceptions means the contract is wrong and must
   be amended — machine-checkable, and it does not punish the legitimate one-off. The counter is
   `DocIndex.value_occurrences`, so the third occurrence is caught across units and not only within
   one. D740 builds `omniweave_core.out.brief`: `parse_brief(text, baseline=)` over the closed set of sections, `Brief` and `baseline_rows(table)`. There are no inline comments, because a value may hold a `#`. The keys a framework rule reads are required: canvas `format` and `unit`, `primary_language`, `per_unit` and `level`. `primary_language` is canonical BCP-47, and `und` and script-less Chinese are refused. The baseline tier is generated one row per forbidden construct as `"<id>: <msg>"`, because the example's prose row cannot be generated. `digest()` is over the parsed Brief, so a CRLF checkout does not move `brief_digest`. A refusal is `OW_TARGET_BRIEF_INVALID` (`OW-T-008`), and the ConstructTable's is `OW_TARGET_CONSTRUCTS_INVALID` (`OW-T-009`), both appended to `codes.toml`.

### 13.3 Stage gates

```text
scope questions ──► Brief (frozen)
                      │
                      ▼
                 ow out scaffold <target>          -> the JobDir; job.json; il/il.toml; the roster
                      │
                      ▼
                 author u01..u05                   -> ow out stamp   (el minted once)
                      │
                      ▼
   GATE 1 ──► ow out check --stage early           -> validation/early.json
                      │   method-level | unit-local | not-yet-exercised
                      │   ONE consolidated fix loop; rosters <= 6 units skip this gate
                      ▼
                 author u06..uNN                   -> NO CHECKER CALLS IN THIS SPAN
                      │
                      ▼
   GATE 2 ──► ow out check --stage final           -> validation/final.json + GateStatus
                      │   passed? ──no──► fix; every finding carries its own command
                      ▼ yes
                 marker.assert_clean()             -> OW-T-141 if any OWC1 marker remains
                      │
                      ▼
   GATE 3 ──► restriction aggregate + AssetLedger.freeze() assertions
                      │
                      ▼
                 ow out compile                    -> lower · write_opc · postflight · Receipt
                      │
                      ▼
   GATE 4 ──► classify_and_assert()                -> sum(UnitOutcome) == unit_count, else FATAL
                      │
                      ▼
                 seal (artifact row, sealed_at_ns) -> ow out verify · ow out back
```

Four gates, four different questions, and no gate substitutes for another: gate 1 calibrates
*method*, gate 2 verifies the *whole roster*, gate 3 is *policy*, gate 4 is *completeness*. Gates 3
and 4 are not user-invocable and have no `--skip`: they are steps inside `ow out compile`, which is
what makes "there is no gate bypass" structural rather than a habit. D773: `ow out compile [--accept-manual] [--job DIR]` is built. It is `run.out_compile.compile_artifact()` over a JobDir, lowered by a `CompileWorker`, so the target's `lower()` and `postflight()` run in an S4 worker; the target's `carrier()` still runs in the CLI process, as `ow out check`'s does. The Plan is `job.json`'s with the bundle's, the table's and the ledger's digests put in (`plan_of()`), and its `gate_status` is the one `validation/final.json` gives, held to the bundle's `il_digest`. `job.json` is not rewritten. `--accept-manual` is the draft, and is a usage error against a gate that passed. The ledger, the cites, the aggregate and the seal share one `StoreThread` whose write lock is taken per unit; the CAS is the store's sibling `cas/` and the bytes land under `[roots] output`. A seal or a lookup hit exits 0, and a closed gate exits as section 15 maps it, nothing lowered. The API sketch's `ow out compile ./il/... --target pptx --slug ...` is the scaffold's to take: a JobDir's `job.json` already names the target, the slug and the corpus.

### 13.4 The audit transcript, with bounded scope

Two tools, deliberately bounded, following ppt-master's split between a manual cold log and an
automatic bounded transcript.

**The manual channel.** `omniweave_core.out.transcript.append_note(job_dir, message)` appends one
record to `<job_dir>/validation/workflow.log`. It is a **library function and not a CLI verb**: the
`ow out` verb tuple is `check|compile|stamp|normalize|verify|back|project|targets|constructs|assets|
scaffold`, the verb tree is generated from the Action registry (INV-20), and adding a verb is an
`ActionSpec` change rather than a convenience. The OUT skills call it.

```text
=== 2026-09-03T11:04:07Z NOTE id=<12 hex> ===
<message>
```

Opened with `encoding="utf-8", errors="replace", newline=""` and explicitly flushed. **An audit log
must never crash the tool it audits on an encoding error.** It records one important event and
interprets no workflow state.

**The automatic channel.** `omniweave_core/out/transcript.py`, installed by tee-ing the process's
stdout and stderr for the duration of an `ow out` verb, and designed to **not** be a console dump:

| knob | value | what it buys |
|---|---|---|
| `CRITICAL_MARKERS` | `("[ERROR]", "[FAIL]")` | the lines that must never be dropped |
| `ALWAYS_RETAIN_MARKERS` | `("[POSTFLIGHT]", "[GATE]", "[REPORT]", "[DONE]")` | the delivery envelope |
| `WARNING_SAMPLE_LIMIT` | 4 | a warning class is sampled, not enumerated |
| `OK_SAMPLE_LIMIT` | 1 | one `[OK]` proves the path ran |
| `STDERR_SAMPLE_LIMIT` | 8 | bounded stderr retention |
| `STDERR_TAIL_LIMIT` | 4 | a `deque(maxlen=4)` ring of **omitted** stderr lines, cleared whenever a stderr line is retained and flushed at close — so a crash with no marker-bearing output still leaves its last four lines |
| `CRITICAL_CONTEXT_LIMIT` | 4 | four lines of context **after** a critical marker |
| `SUMMARY_CONTEXT_LIMIT` | 12 | twelve lines after `[SUMMARY]`, until a stop marker |

Close envelope, which is the part that makes the record honest:

```text
=== 2026-09-03T11:06:22Z END run=<12 hex> elapsed_ms=71204 output_lines=1841
    retained=63 omitted=1778 ===
```

**Exact retained/omitted counts, so the reader knows the record is lossy and by how much.** The
transcript attaches only to a job directory that already owns a `validation/workflow.log` — no
surprise files, and no config key is needed to disable it: a job directory with no `workflow.log`
gets no transcript. The manual logger never auto-logs itself.

**Bounded scope, stated as a non-responsibility**, because that is the half usually missing: the
transcript records command envelopes plus bounded material outcomes. It does **not** retain the full
console stream, does **not** infer readiness, does **not** rerun another tool, and does **not** alter
the owning tool's result. The durable record of *what was built* is the `artifact` row, the
`Receipt` and `validation/final.json` — never the transcript.

## 14. Failure, scale and concurrency

Every mechanism above is specified for the happy path in its own section. This section is where each
one is asked the four questions a design document usually skips: what does it do at scale, on hostile
input, on partial failure, and under concurrency.

### 14.1 The OUT ceilings

Ceilings, not settings: `effective = min(tenant_cap, declared, HOST_MAX)`, widening past a `MAX_*` is
a fork, and a breach is `RESOURCE_LIMIT{limit}` naming the knob (§6.10). These seven are **set by
this document** and live in `omniweave_core.limits` beside §6.10's; each carries its arithmetic
because an orphan ceiling gets raised by whoever hits it first.

| constant | value | derivation |
|---|---|---|
| `MAX_IL_FILE_BYTES` | 4 194 304 (4 MiB) | `MAX_IL_NODES` × a mean 40 source bytes per element = 4 MB. The same ceiling as the next row, expressed in the unit the reader hits first |
| `MAX_IL_NODES` | 100 000 per unit | at ~1 KB of parsed node (an `Element` with an attrib dict and text, plus our `el`/`nsig` index entry), one unit's tree peaks near 100 MB — the per-unit memory the runner is built for. §14.2 makes that the whole-roster peak too |
| `MAX_IL_DEPTH` | 128 | the carrier walk, the canonicalizer and the serializer each add ~3 Python frames per level, so 128 levels ≈ 384 frames against CPython's default 1000-frame limit, leaving headroom for the caller. No legitimate slide or flow document nests 128 deep |
| `MAX_FINDINGS_PER_RULE` | 5 000 pre-fold | at ~400 B per `Finding`, 5 000 is 2 MB for one rule; the cap is per rule rather than per report so one runaway rule cannot consume the budget of the other 59 |
| `MAX_FOLDED_FINDINGS` | 20 000 | 20 000 × ~400 B = 8 MB = `MAX_REPORT_BYTES`. Beyond it the report re-folds (§14.3) |
| `MAX_REPORT_BYTES` | 8 388 608 (8 MiB) | the size at which `validation/final.json` stops being a file an agent can read and starts being a file it must page through. Enforced by the re-fold, never by truncating the JSON |
| `MAX_MARKER_PAYLOAD_BYTES` | 4 096 | one note, not a document. Encodes to ≤ 10 927 marker characters (§8.1) |
| `MAX_MARKERS_PER_UNIT` | 256 | a unit with 256 open notes needs a conversation, not a 257th note |

`MAX_ASSET_BYTES = 268_435_456` is §6.10's and is not restated as this document's.

### 14.2 Scale: a 2000-unit roster

`[compile] max_units = 2000` for `pptx`. Naively parsing that roster is
2000 × 100 MB = 200 GB resident, which is why the runner is a streaming design and not a batch one
(§4.4):

- **One parsed unit resident at a time.** Pass A parses a unit, runs its rules, folds its findings,
  merges its contribution into `DocIndex`, and drops the tree. Peak resident is one tree
  (≤ ~100 MB) plus `DocIndex` plus the folded set.
- **`DocIndex` is bounded by the roster, never by the node count.** Its per-unit entries are an `el`
  set, a construct counter, a cite set, a slot set and a marker list. At 2000 units × ~200 stamped
  elements, `els` and `nsigs` together are ~400 000 short strings ≈ 40 MB — the dominant term, and
  the reason `nsig` is 8 hex characters and not 64.
- **`il_digest` streams.** It hashes each file's bytes in a fixed-size buffer and never holds a
  bundle, so a 2000 × 4 MiB = 8 GiB bundle digests in constant memory. That is also why `il_digest`
  is computed at load and never recomputed per rule.
- **Whole-roster budget.** ~100 MB tree + ~40 MB index + ≤ 8 MB folded findings ≈ 150 MB peak,
  independent of `max_units`. That fits inside the supervisor's ≤ 600 MB RSS gate with room for the
  store handle, which is the constraint that made the streaming design non-optional.
- **`rule_timings_ms` is per rule and not per rule-per-unit**, summed across the pass. A 60-rule pack
  over 2000 units is 120 000 invocations; recording 120 000 timings would itself be a scale problem,
  and the aggregate is what identifies the slow rule anyway.

### 14.3 Hostile input, and the second fold

The IL is authored by a model and may be authored by an adversary. Every entry point fails closed:

| input | mechanism |
|---|---|
| a DOCTYPE, an external entity, a billion-laughs payload | DOCTYPE banned in both carriers; expat constructed with entity definition handling disabled, so the *declaration* fails, not the expansion |
| a 400 MB IL file | `MAX_IL_FILE_BYTES`, checked with `take(N+1)`-then-check at the read boundary, so the limit is not discovered after the memory is spent |
| a 10 000-deep nesting | `MAX_IL_DEPTH`, checked during the parse walk, not after |
| an `asset-slot:` naming a digest not in the ledger | preflight check 2 raises; before that, the `order = 80` rule blocks with `needs={"assets"}` |
| a `data:` URI, an `http://` href, an absolute path in IL text | `OW-T-112`, plus semgrep on `open()`/`Path()` over an IL-derived string in `lower/` |
| a marker whose payload is not valid base64url or not valid JSON | `scan()` skips it, records `state: "corrupt"` and a `FRAMEWORK` info finding; the gate becomes `unverified`, because an unreadable marker may be a `must` |
| a rule that emits one finding per node on a 100 000-node unit | `MAX_FINDINGS_PER_RULE` truncates at 5 000, records a `truncations` entry naming the rule and the count, and the gate becomes `unverified` — never `passed`, because the truncated tail may contain errors |
| a duplicate `data-ow-el` | `OW-T-405` at `order = 10`, before anything reads the address |
| a `constructs.toml` whose `code` names no `codes.toml` row | the meta-gate, in CI, in both directions |

**The second fold, and why the first is not enough.** `FindingSet.fold()` groups on
`(code, rule, unit, canonical)`. On a 2000-unit roster with 60 emitting codes that key can produce
120 000 folded findings ≈ 48 MB — six times `MAX_REPORT_BYTES`, and unreadable regardless. So:

```
if len(folded) > MAX_FOLDED_FINDINGS:
    refold on (code, rule, canonical)          # DROP `unit` from the key
    each refolded finding carries units_affected: int and up to 3 example unit ids
    append a `truncations` entry: {"kind": "refold", "from": 120000, "to": 60}
```

The re-fold is lossless in the dimension that matters — every code is still reported, with a true
total count — and lossy only in per-unit attribution, which is exactly the information an agent
facing 120 000 findings cannot use anyway. The `truncations` entry makes the gate `unverified`
rather than `passed`, so a re-folded report can never release. That is deliberate: a roster
generating 120 000 findings has a method problem the early gate should have caught, and shipping it
is not the right next step.

### 14.4 Partial failure

| where it fails | what survives | what is guaranteed |
|---|---|---|
| `carrier()` on one unit | every other unit's findings | the short circuit is per unit; `il_digest` already records the unreadable file with the literal `unreadable` |
| a rule raises | the run continues | the raising rule contributes one `FRAMEWORK` `error` finding naming the rule and the exception type, and the gate is `failed`. A rule that crashes is a framework-visible defect, not a silent pass |
| `run_pack()` is cancelled (`DriverIO.cancelled()`) | nothing is written | no partial report reaches `validation/`; the previous report, if any, is untouched and remains `stale` against the current bytes |
| `lower()` raises, times out, or the Toolchain child is killed | the JobDir and its reports | `io.tmpdir` is host-deleted; no bytes under `output_root`; no `artifact` row; the `DriverError`'s `failure_class` drives the runtime's retry ladder |
| `write_opc()` fails mid-write | nothing | it builds the whole archive in memory and returns `bytes`; there is no partial file to leave behind, which is a second reason it is the only ZIP-for-write site |
| `postflight()` raises | the produced bytes in `tmpdir`, which are then deleted | the artefact is **not** sealed. A package that fails its own re-verification is not delivered |
| `classify_and_assert()` fails | nothing | the artefact is not written, and the counts are printed (OUT8) |
| the process dies between `postflight` and `seal` | nothing | the seal is one transaction; there is no state between "no row" and "a sealed row" |
| `apply_reverse()` fails to reparse | the original IL file | all-or-nothing, `os.replace()` over a temp file |

The single rule behind that table: **nothing outside `io.tmpdir` and `job_dir/validation/` is written
before `seal`, and `seal` is one transaction.** Everything else follows.

### 14.5 Concurrency

| two of these at once | outcome |
|---|---|
| two `ow out compile` on one slug | §5.4: `artifact_gen` allocated inside the INSERT; a `(slug, artifact_gen)` conflict retried once then `OW_TARGET_GEN_CONTENDED`; an `artifact_pure` conflict is a cache hit, not an error |
| two `ow out stamp` on one bundle | `il/.stamp.lock`, O_EXCL, pid and start time inside, stale after 300 s. Without it both mint `e17` |
| two marker appliers on one file | last-writer-wins at whole-file granularity via `os.replace()`; the loser's markers are still present on the next scan, because presence is the state (§8.3) |
| `ow out check` while an agent writes a unit | the check reads a snapshot; a file written between the digest and the parse produces a per-file sha mismatch and the report is `stale` on its own next comparison. The check never blocks the writer |
| a compile and an `ow store gc` | `gc` deletes a CAS object only when no `asset` row references its digest, and `freeze()` writes the `asset` row before the compile proceeds. The window is closed by the write order, not by a lock |
| two `ow out normalize` runs | both refuse the second time: the first moves `il_digest`, and the second's report is `stale` |

## 15. The `OW-T-*` code register and the exit-code mapping

`codes.toml` is append-only (G13), never renumbered, never reused. Every row carries a numeric
`OW-T-nnn` (the human form), a `OW_TARGET_*` symbol (the stored and wire form), a meaning, and **the
exact command that clears it**. The band allocation, so a rule author knows where a new code goes:

| band | class |
|---|---|
| `OW-T-001..099` | contract meta |
| `OW-T-100..139` | citation and provenance |
| `OW-T-140..159` | markers |
| `OW-T-200..299` | `normalize` dispositions (warnings) |
| `OW-T-300..399` | `bake` dispositions |
| `OW-T-400..499` | `forbidden` and invalid |
| `OW-T-500..599` | compile and package |

The full register this document requires. **Thirteen numerics are fixed by the charter** and are
marked `C`; six of those also carry a charter-fixed symbol. Everything marked `+` is appended by this
document, which `codes.toml`'s append-only rule permits; the numeric assignments within each band are
provisional until the register is written, and the **symbols** are not, because the symbol is the
stored and wire form.

| | numeric | symbol | meaning |
|---|---|---|---|
| C | `OW-T-001` | `OW_TARGET_CONSTRUCT_UNMAPPED` | a `maps_to` that does not resolve in `lower/` |
| C | `OW-T-002` | `OW_TARGET_CONSTRUCT_UNDECLARED` | a lowering symbol with no ConstructTable row |
| + | `OW-T-003` | `OW_TARGET_CHECK_SKIPPED` | a rule's `needs` was unmet; the gate is `unverified` |
| + | `OW-T-004` | `OW_TARGET_RULE_FORGED_PROVENANCE` | a rule emitted a non-`INTRODUCED` provenance (§4.1) |
| C | `OW-T-005` | `OW_TARGET_UNIT_UNCLASSIFIED` | a unit landed in no `UnitOutcome`; FATAL |
| + | `OW-T-006` | `OW_TARGET_FINDINGS_TRUNCATED` | a rule passed `MAX_FINDINGS_PER_RULE`, or the report re-folded |
| + | `OW-T-007` | `OW_TARGET_SELECTOR_INVALID` | a `selector`, a `forbidden_when` or a `select()` literal that does not parse as §3.1's carrier selector grammar; raised, never an empty match |
| + | `OW-T-101` | `OW_TARGET_CITE_UNRESOLVED` | a `data-ow-cite` naming no block in this corpus, at `--stage final` |
| C | `OW-T-102` | `OW_TARGET_CITE_NOT_VERBATIM` | `kind="quote"` over text that is not the block's span |
| C | `OW-T-112` | `OW_TARGET_IL_ASSET_URI` | an `http(s)`/`file:`/`data:`/path in IL text |
| C | `OW-T-141` | `OW_TARGET_MARKER_UNRESOLVED` | `assert_clean()` found a marker at compile |
| C | `OW-T-151` | `OW_TARGET_MARKER_AMBIGUOUS` | multiple text candidates and no `prev` |
| + | `OW-T-152` | `OW_TARGET_MARKER_ORPHAN` | no element carries the marker's `el` |
| + | `OW-T-153` | `OW_TARGET_MARKER_STALE` | the element's `nsig` moved since placement |
| + | `OW-T-154` | `OW_TARGET_MARKER_BUDGET` | `MAX_MARKERS_PER_UNIT` exceeded |
| C | `OW-T-210` | `OW_TARGET_FILL_NOT_UPPER_HEX` | the reference `normalize` row |
| C | `OW-T-311` | `OW_TARGET_BLEND_REQUIRES_BAKE` | the reference `bake` row |
| C | `OW-T-401` | `OW_TARGET_SCRIPT_FORBIDDEN` | `<script>` or an event attribute |
| C | `OW-T-402` | `OW_TARGET_ID_WITH_STYLE` | the reference conditional prohibition |
| C | `OW-T-405` | `OW_TARGET_EL_DUPLICATE` | two elements with one `data-ow-el` |
| C | `OW-T-410` | `OW_TARGET_FILL_INVALID` | the reference `native` row's grammar |
| + | `OW-T-501` | `OW_TARGET_PACKAGE_CORRUPT` | a member does not decompress; names it |
| + | `OW-T-502` | `OW_TARGET_UNIT_COUNT_MISMATCH` | output units ≠ `plan.unit_count`; prints both |
| + | `OW-T-503` | `OW_TARGET_DANGLING_REL` | a relationship target that is not a member |
| + | `OW-T-504` | `OW_TARGET_CONTENT_TYPE_GAP` | a part with no declared content type |
| + | `OW-T-505` | `OW_TARGET_NORMALIZE_AT_COMPILE` | a `normalize` construct reached `lower()` without `--accept-normalization` |
| + | `OW-T-506` | `OW_TARGET_ASSET_UNFROZEN` | preflight 2 |
| + | `OW-T-507` | `OW_TARGET_ROSTER_MISMATCH` | `ILBundle.load()` for the bundle-versus-filesystem difference (§3.2, §3.7), preflight 3 for the Plan-versus-bundle one; names the ids in each of the three directions |
| + | `OW-T-508` | `OW_TARGET_TOO_MANY_UNITS` | preflight 4 |
| + | `OW-T-509` | `OW_TARGET_BAKE_UNAVAILABLE` | preflight 5 |
| + | `OW-T-510` | `OW_TARGET_GEN_CONTENDED` | §5.4 rule 2 |

Every member of a target's `RuleSpec.codes` set has a row, and the meta-gate matches in both
directions: a symbol a rule may emit with no `codes.toml` row fails CI, and a `codes.toml` row in the
`OW-T-*` class that no `RuleSpec` may emit fails CI. One further extension: `Degradation(kind=…)`
gains `compile_normalized`, extending the existing `kind` literal exactly as D6, D9 and D10 do rather
than introducing a parallel type.

**The exit-code mapping this layer needs.** §6.4's exit-code table is one table for the whole CLI and
is [interfaces](10-interfaces.md)'s to own. It has no value for "the gate refused", and mapping a
refused gate onto `1` (usage or configuration error) would make a correct tool look misconfigured.
The mapping this document requires, and the one row it asks [interfaces](10-interfaces.md) to append:

| condition | exit | status |
|---|---|---|
| `gate = passed` | 0 | existing |
| any non-`passed` `GateStatus`, including `failed` | **8** | **the appended row: "OUT gate refused"**, with the status name and its fix command on stderr |
| `gate = restricted` | 6 | existing — policy refusal outranks the generic gate code, because the fix is a grant and not an edit |
| `gate = unverified` because a declared engine is absent | 64 | existing — required capability missing, matching `omniweave-target/1`'s exit 64 |
| a normalizer or a reparse failed, nothing written | 70 | existing — internal error, prints the `OW-T-*` code and the report command |

`ow out normalize` and `ow out stamp` exit 0 on success whether or not they changed anything, and
print the count plus the re-check invocation; they never exit 8, because neither of them runs a gate.

## Open questions

**Q1. `part` determinism for `python-pptx` across nine cells (charter F16).** `byte` is knowingly
resolution-scoped, but `part` is **promised** and is the floor every enabled target declares.
*Closed by:* compiling the 40-unit golden fixture on all nine platform cells and diffing
`part_digest` member by member, before the OUT phase's week 8. *If it fails:* the floor moves from
`part` to a normalized-part class — a **card-visible** downgrade, not a silent one, which means a new
`ArtefactDeterminism` member and a `constructs`-independent card change. *(Build note, D881: the 40-unit golden is `fixtures/gen/gen_golden40.py`'s forty-slide owsvg/1 deck. It is a quarterly review in seven layouts, built only from constructs the two-unit golden exercises, with a cited quote and the frozen image. It is generated and pinned through its manifest in `fixtures/gen/EXPECTED.sha256`, not committed. It passes the pptx gate as a release with no finding, and R2 holds for all 253 addressed elements. `tools/check_out_determinism.py --golden` compiles it five ways on one cell: one `part_digest` and one sha256 across 116 package parts. The nine cells remain CI's.)*

**Q2. The honest `project(Doc) -> IL` ceiling for a foreign artefact (charter F17).**
`passthrough` is claimed for the retained-IL path (R1/R4), which is cheap. `project()` on a foreign
deck must invent an SVG subset from DrawingML, and **nothing in the mined collection does that** —
ppt-master regenerates its baseline from retained backing SVGs and never reconstructs authoring
source from a PPTX. *Closed by:* implementing `project` for ten real foreign decks and measuring what
fraction of shapes satisfy R2. *If below ~70 %:* the card declares `project = false` for foreign
input and `ow out back` is corpus-only.

**Q3. Does any rasterizer clear `tools/licences.toml` at an acceptable install weight (charter
F18)?** `bake` is `unavailable` on all three release-1 targets, so the `bake` disposition tier has
**zero live rows** at release 1. *Closed by:* resolving a candidate set, running G3 over the resolved
graph, the import graph and the unpacked artifacts, and measuring the bundle delta. *If none clears:*
demote `bake` to `forbidden` with a documented degradation rather than keep a disposition tier
nothing implements — a tier with no producer is a promise nothing keeps, exactly as the charter says
of a pass whose distribution does not exist.

**Q4. The routing policy does not yet prefer a target's own `read_back` (carried from
[architecture](02-architecture.md) Open question 4).** For a `.pptx` omniweave built, the shipped
policy resolves `parse.office.anydoc` under rule `decode.office-native` rather than
`parse.pptx.native`. At release 1 the target-specific path is exercised by `ow out back` and the
golden suite only. *Closed by:* a policy rule keyed on `unit.uri` being inside `roots.output` with a
matching `artifact` row — which is a routing-engine change, so it belongs to
[ingest and routing](05-ingest-and-routing.md). *Consequence while open:* an ordinary `ow ingest`
over the output root produces `quote = normalized` blocks with no `x.ow.el`, so `artifact_el` is
populated only through `ow out back`, and R2 is checkable only there. D788 builds that path (`omniweave.run.out_back`). When a generation's `read_back_doc_ord` is NULL and its card's `read_back` is installed, `ow out back` reads the sealed bytes from the corpus CAS in an S4 worker (`pipeline.read_back_host()`, the fourth `invoke()`), writes the fragment as an ordinary parse's document, and calls `close_loop()` with each address's block from the committed head. Every address must name a sealed unit and stand on one block, and the blocks carry the artefact's `restriction_bits`. A loop already closed is reported, not read again. A card naming no `read_back`, or one not installed, leaves the loop open and the report says why: owtext names `parse.text.owtext`, which nothing ships. A read-back that fails is `OW_TARGET_READ_BACK_FAILED` (`OW-T-529`), and nothing is restored. Found: when an ingest of the output root has already read the same bytes, the read-back is a re-parse, and the store quarantines it below the rebind threshold. The loop then stays open, naming `ow doc diff`, because the committed head is the other parse's.

**Q5. `[compile] runtime_rules = true` gives a Toolchain target a `validate` frame, and the framework
still owns the gate — but the child computes findings the framework cannot recompute.** OUT2's "one
implementation of what a construct means" holds by construction inside a Python target (`measure.py`
imported by both `rules/` and `lower/`); for `deck` the measurement lives in the child and the
Python side has no second opinion. *Closed by:* a conformance fixture set where the child's measured
capacity findings are compared against a Python-side pessimistic bound — a monotone lower bound on
capacity computed from the declared token set's font metrics, returned as an ordinary `Box` from an
ordinary `TextMeasure` and therefore already in the CSS px the child reports (§4.4), so the
comparison is an inequality on `advance` and `height` and not a unit negotiation — asserting the
child never reports *more* capacity than the bound. *If that bound is not constructible:* `deck`'s measurement rules
declare `needs={"measure"}` unmet on the Python side and the gate is `unverified` for any unit whose
capacity was not independently bounded — which is correct but weak, and should be measured before it
ships.

**Q6. `x.ow.*` reserved-key count — a charter wording defect.** §D8's DDL comment states that D8
defines "exactly two" reserved keys in L2's `x` bag — `x.ow.el` and `x.ow.cite` — while
[the document model](03-document-model.md) adds a third, `x.ow.unknown`, as an explicit charter
extension for wire-version skew. The two are consistent (the third is L2's, not D8's) but the word
"exactly" reads as a global count. **Flagged as a charter wording defect, not followed as a
prohibition:** this document treats the reserved set as `{x.ow.el, x.ow.cite, x.ow.unknown}`, with
the first two OUT's and the third L2's. The fix is one word in the charter comment: "D8 defines two
reserved keys" rather than "exactly two".

**Q7. Terminology-lock gaps, stated precisely.** The lock's CI rule 1 requires every `class` name
appearing in `charter.md` to have a §2 row. Checked mechanically against §D8, **every `class`
declaration already has a row** — the rule as written does fire clean. What does not have a row is a
different set: twelve OUT type names that appear in `charter.md` only as *annotations and forward
references* (`"Plan"`, `"ILBundle"`, `"AssetLedger"`, `"Receipt"`, `"CheckValue"`, `"FindingSet"`,
`"CiteResolver"`, `"TextMeasure"`, `"OutReport"`, `"Unit"`, `"Box"` — which occurs exactly once in the
charter, as `RuleCtx.measure`'s return annotation at `charter.md:6026`, and was defined nowhere until
§4.4 printed it — and `RuleCtx`, which appears only inside another row's prose). Rule 1 does not
reach them, and they are exactly the types a plan document must name to be implementable. **Four
more** are in the same state one layer down: `CarrierNode`, `Splice`, `Insertion` and `ParseError`
are named in the charter's `out/carrier/` module-inventory line (`charter.md:5814`) and appear
everywhere else only as annotations on `CarrierDoc`'s own method signatures; §3.1 prints them. So the
widened rule has to catch sixteen names, not eleven. Two consequences: **(a)** the lock's rule 1
should be widened from "`class` name" to "type name in a signature or annotation", which is the
mechanical form of what it was trying to say; **(b)** all sixteen definitions are supplied under New
terms below so the lock can absorb them in one change. This document follows the charter's spellings
exactly and coins nothing in their place.

**Q8. No preview server ships at release 1, so who places an `OWC1` marker?** The grammar, the
scanner, the two-factor anchor and `assert_clean()` are all specified and framework-owned, and
`CarrierDoc.place_marker` is the insertion hook — but the charter names no local server, and
open-slide's HTTP surface (`POST /__comments/add`, with `Sec-Fetch-Site` plus origin comparison plus
a JSON content-type guard) is a recommendation in the mining notes rather than a charter decision.
At release 1 markers are placed by whatever writes the IL file — a human editor, or an agent. *Closed
by:* deciding whether an `ow out preview` surface is in scope, which is
[interfaces](10-interfaces.md)'s call. *If it is:* the mutation guard is not optional — a local
server that writes source files is a CSRF target from any page the user has open.

**Q9 — closed. A compile-produced asset hangs off a synthetic job document.**
[The document model](03-document-model.md) makes every `asset` row belong to a `doc`, and at release
1 that is exhaustive because the only compile-produced asset class is `bake` output and `bake` is
`unavailable` everywhere (Q3). The day a rasterizer clears G3 the constraint needs an answer, and
**§7.1 is it**: one `doc` row per compile job, `format = 'owjob'`, written by the job runner before
`bake` produces its first byte, carrying the bake's provenance and owning its assets. `asset.doc_ord`
stays `NOT NULL`, `asset_identity` is untouched and **no column is added to `doc`** — the row shape,
the `ON DELETE CASCADE` hazard and the refusal that answers it are all in §7.1 and are not restated
here. The nullable-`doc_ord` alternative was rejected on three counts: its `CHECK` is vacuous because
every `store_ref` is already `cas://…`, `asset_identity` folds `NULL` as distinct so identical bake
output would produce unbounded duplicate rows, and a row owned by no document has no answer for the
compile-time restriction aggregate (§7.3, OUT11, DR17, INV-16). Decided **before `bake` ships**, as
the question required; if `K-5` fires and `bake` is demoted to `forbidden`, this costs one unused
row shape.

**Q10. `--stage early` fires after five units, but the sample is not necessarily representative.**
ppt-master's measured design treats the first five pages as a method sample, and omniweave adopts it.
The known hole is `not-yet-exercised`: a construct the sample never used has unknown correctness, and
nothing forces the roster's *hard* units to be among the first five. *Closed by:* measuring, over the
golden corpus, what fraction of final-gate errors were method-level and would have been caught by an
early gate on units chosen by declared `## rhythm` anchor diversity rather than by ordinal. *If the
diverse sample is materially better:* `ow out check --stage early` selects its sample by anchor
coverage rather than by position, which is a one-line change to the stage's roster requirement and
no change at all to the gate.

**Q11. `job.json` has no printed schema, and §3.7 could only version half of it.** §3.7 gives `Plan`
the schema id `omniweave.out-plan/1` because a Toolchain child parses that object across a wire
version boundary (§12.2) and an unversioned object cannot be refused on skew. But `Plan` is one key
of `job.json`, which also carries `traceparent` ([observability](15-observability.md) §2) and
`determinism.clock_ns` (§12.3), and no document prints `job.json` itself or gives it a schema id —
`job.py` is named in the module inventory (§1 row 22) and its file layout is described nowhere as
data. The result is that a `deck` child can reject an unrecognised `plan` version and cannot reject
an unrecognised *envelope*. *Closed by:* printing `job.json` in this document beside `il.toml`, with
schema `omniweave.out-job/1` and the same hard-error-on-unknown-key rule `[compile]` has, and stating
which keys the S2 child may read. It is one TOML-sized block and it belongs here rather than in
[interfaces](10-interfaces.md), because the JobDir is framework-owned. *If it is not written before
S2 ships:* the child validates `plan.schema` and treats every other key as advisory, which is the
current behaviour and is weaker than it needs to be. **Closed by D763.** `omniweave_core.out.job.Job` is `job.json`. It has four keys and no more: `schema` (`omniweave.out-job/1`), `plan` (section 3.7's `Plan`, its Brief embedded and held to `brief_digest`), `traceparent` (15 section 2.5's S2 carrier) and `determinism.clock_ns` (section 12.3). It is closed at every level, so an unknown or missing key anywhere is `OW-T-518 OW_TARGET_JOB_INVALID` (appended). A child may read all four: it refuses an unknown `schema` or `plan.schema` first, echoes `traceparent` and writes every OPC timestamp as `clock_ns`. The JobDir's other files are named by layout, not by key. `schema/job-v1.json` is generated from the type, and G6 holds it byte for byte. To reflect `Plan.cites: Mapping[Cite, int]`, schemagen now unwraps a `NewType` key to its supertype.

## New terms

Definitions for merge into `terminology.md` §2. Thirteen rows are **charter type names missing from
the lock** (Q7), given here so the lock can absorb them: `AssetLedger`, `Box`, `CheckValue`,
`CiteResolver`, `FindingSet`, `ILBundle`, `OutReport`, `OutUnit`, `OWC1`, `Plan`, `Receipt`,
`RuleCtx`, `TextMeasure`. **Four more** are the Protocol and dataclasses `CarrierDoc`'s own
signatures reference — named in the charter's `out/carrier/` inventory line and defined nowhere
until §3.1 printed them: `CarrierNode`, `Insertion`, `ParseError`, `Splice`. Six rows are **coined
by this document** and marked `(coined here)`: `DocIndex`, `ILFile`, `il.toml`, `portability`,
`normalizations`, `truncations`. `ILFile` is the only name §3.7 had to coin — `ILBundle`, `Plan` and
`OutUnit` were all already locked names with no shape, and §3.7 supplies the shape. `OutUnit` is a
rename: OUT's addressable output unit was spelled `Unit` and collided with the `unit` roster table,
which keeps the bare name because it is L2 and P2 DDL and a table rename after the freeze is a
migration. [ADR-1](adr/0001-terminology-lock-bulk-pass.md) decision 7 row 4 made the rename, the
lock carries `OutUnit` ([terminology](_notes/terminology.md):588), and the compounds `UnitOutcome`,
`UnitRef`, `UnitKey`, `artifact_unit` and `unit.part_count` are untouched — only the bare name
collided. `il_digest_rt` and `ManualEvidence` are deliberately *not* in this table: both are
already locked (§2), and this document uses them verbatim.

| Term | Kind | Definition |
|---|---|---|
| `AssetLedger` | type | The OUT framework's writer and reader over L2's `asset` table for one compile: `slot()`, `freeze()`, `digest()`. `freeze()` is the **only** writer of a compile-time asset, streams into CAS, enforces `MAX_ASSET_BYTES` with both a content-length pre-check and a streaming abort, and never fetches — a compile that must fetch refuses with `Degradation(kind="grant_missing")`. |
| `Box` | type | The one shape a `TextMeasure` returns: `advance`, `height`, `ascent`, `descent`, `lines: int` and `overflow: bool`, frozen, all six in **IL user units** — the unit `<svg>` root's `viewBox` coordinate system for `owsvg/1`, CSS px for `owdeck/1` and `owflow/1` — and never EMU, which appears only in `lower/`'s serializer, nor device pixels. It converts nothing, and a rule rounds to whole IL user units before printing one into a `msg`. |
| `CarrierNode` | proto | One element of a parsed IL file, and the type every rule iterates: `at` (`"il/u03.svg:41:9"`, exactly the form `Finding.at` carries), `el` (the `data-ow-el` address, `None` until `ow out stamp` mints one), `tag` in selector spelling (`"svg\|text"`), `nsig` (this subtree's digest only — §8.2's changed-definition conjunct is the resolver's), `attr()`, `children()`, and `text_content()` for raw subtree character data, which is **not** `CarrierDoc.visible_text()`. |
| `CheckValue` | type | One row of a `Receipt.checks` tuple, printed at §5.3: a `name` unique within one receipt, a value from `{passed, warning, failed, enforced-at-build, not-applicable, skipped}`, an optional `detail`, and a `fixture` required exactly when the value is `enforced-at-build`. `enforced-at-build` is first-class: an invariant guaranteed by construction is declared, not re-checked as theatre, and `fixture` names the kit test that proves the claim by mutating the builder. Postflight evidence, never a gate and never a rule's return — a `RulePack` predicate returns `Iterable[Finding]`, before the gate; a `CheckValue` is written after `lower()`. |
| `CiteResolver` | proto | The read-only cite handle a `RuleCtx` carries: `by_cite()` and the batch `by_cites()`, and nothing else. No writes, no store handle, no retrieval. |
| `DocIndex` | type | *(coined here)* The bounded per-roster summary the rule runner builds during its unit pass and hands to every `scope = "document"` rule: per unit, the stamped `el` set, `el -> nsig`, a construct counter, the cite set, the asset-slot set, the marker list, and cross-unit value occurrence counters. Bounded by the roster, never by the node count, which is what lets a 2000-unit roster be validated with one parsed unit resident. |
| `FindingSet` | type | The collected `Finding`s of one validation, with `fold()` grouping on `(code, rule, unit, canonical)`, summing `count` and keeping at most three examples, and a second re-fold on `(code, rule, canonical)` past `MAX_FOLDED_FINDINGS` that records itself in `OutReport.truncations`. |
| `ILBundle` | type | The loaded IL of one job, printed at §3.7: `il.toml`'s `schema`, IL id and `constructs_digest`; the bundle's own `OutUnit` roster in `ord` order; one `ILFile` row per file under `job_dir/il/` including `il.toml`; `il_digest`, `il_digest_rt` and the stamped `el` index; and `root`, the one path in the type. It holds **digests and paths, never the bytes** — `text()` and `data()` re-read from `root`, so an 8 GiB bundle loads in constant memory. Text on disk, never a node table; retained content-addressed in CAS at compile time. |
| `ILFile` | type | *(coined here)* One file under `job_dir/il/` as `ILBundle` records it: `name` (a basename, never a path), `sha256` (64 hex **or** the literal `"unreadable"`), `byte_len`, and `error`, non-`None` exactly when the file could not be read. The same four values `OutReport.il_files` serializes, so an unreadable IL file is visible in the report and contributes to `il_digest` instead of silently dropping out. |
| `il.toml` | file | *(coined here)* The IL bundle's own roster, schema `omniweave.out-il/1`: the IL id, the `constructs_digest` the bundle was authored against, and one `[[unit]]` row per unit carrying `id`, `ord`, `file` and `anchor`. One of three rosters — the Plan's, the bundle's and the filesystem's — that preflight check 3 compares in all three directions. Covered by `il_digest`. |
| `Insertion` | type | What `CarrierDoc.place_marker()` returns: the byte offset and the 1-based line the marker line now occupies, the `el` it was written against, and `hoisted` plus `container_el` when the anchor was self-closing and the marker had to sit on an ancestor — so the applier knows the note may refer to a child of that ancestor. |
| `OutReport` | type | The validation report object behind `validation/<stage>.json`, schema `omniweave.out-report/1`. Carries the stage, `il_digest` as **bytes**, the unit-bucketed `summary`, the finding-counted `counts`, `by_provenance`, the folded findings, the **required non-null** `skipped_checks`, `truncations`, `restricted_items` and `manual_units`, the marker inventory, the portability block and `rule_timings_ms`. The only input to `gate_status()` besides `il_digest`. `load()` returns `None` for an absent file and an `unreadable = True` instance for one that does not parse. |
| `OutUnit` | type | One addressable output unit of an artefact — a slide, a page, a section, a scene — printed at §3.7: `id` (`u03`, never renumbered), `ord`, the job-relative `il_path`, the Brief `anchor`, `nsig`, the `source_part`/`source_nsig`/`source_ord` triple that is all-`None` on the create path, and `manual_reason`. It carries **no** `UnitOutcome`: the outcome is a compile-time result and lives in `Receipt.units` and `artifact_unit.outcome`, with `reason` NOT NULL there for `baked` and `manual_required`. |
| `OWC1` | proto | The framework's carrier-agnostic feedback marker grammar: a fixed regular language inside a carrier comment, opening with the literal `OWC1:v1` and carrying `el`, `nsig`, `id`, `ts` and a base64url JSON payload whose `-` runs are space-separated so the marker is legal inside an XML comment. Presence is the state; there is no side table. `scan()`, `apply_reverse()`, `assert_clean()`. |
| `ParseError` | type | The value `CarrierDoc.splice()` and `marker.apply_reverse()` **return** rather than raise when the post-splice reparse fails: `at` in the `path:line:col` form and the stdlib parser's own `msg`, passed through. Neither a `Diag`, which is recorded, nor an `OwError`, which is raised — the original file is untouched and the caller exits 70 having written nothing. |
| `Plan` | type | The gated compile plan, printed at §3.7 and schema `omniweave.out-plan/1` — the `plan` object inside `job.json`, versioned in its own right because a Toolchain child parses it across a wire boundary: the target, the slug, the proposed `artifact_gen`, the `delivery` tier, the ordered `OutUnit` roster, `unit_count`, the `Brief`, the corpus id, the resolved cite set as `cite -> pinned doc_gen`, the `GateStatus`, and the six purity digests including `ledger_digest` — the frozen ledger *reference*, the object itself being `lower()`'s third argument. `lower()` receives a `Plan` and cannot see the report it was gated by, and the `Plan` carries no filesystem path at all. |
| `Receipt` | type | The postflight delivery evidence, schema `omniweave.out-receipt/1`: the output identity, `part_digest`, the compiled `ArtefactDeterminism` set, the gate status, the delivery tier, the `CheckValue` tuple, the per-unit `UnitOutcome` map with asserted counts, the portability block, the `normalizations` ledger, degradations, and the carried-forward `skipped_checks` and `truncations`. |
| `RuleCtx` | proto | What one rule may see: the parsed `CarrierDoc` and `OutUnit` (both `None` for a document-scope rule), the `Plan`, the `ConstructTable`, the `Brief`, the `DocIndex`, the `CiteResolver`, the occurrence `limits`, and `measure()` whose `None` return is a recorded skip and never a pass. |
| `Splice` | type | One all-or-nothing text edit over a byte range of `CarrierDoc.source().encode("utf-8")`: `start` inclusive, `end` exclusive, `text` the replacement; `start == end` inserts and `text == ""` deletes. A batch is applied in descending `start` order and an overlapping batch is rejected before any edit lands — two edits to one range are two opinions and the applier does not arbitrate. |
| `TextMeasure` | proto | The single text-measurement estimator a target supplies, exposing exactly one method — `box(n: CarrierNode) -> Box \| None` — and reached by **both** callers: `rules/` through the `RuleCtx.measure()` wrapper the framework builds over it, `lower/` by parsing the unit itself with the target's own `carrier()` and calling `self.measure().box(n)`. A `None` from `CompileV1.measure()` makes every rule declaring `needs={"measure"}` a recorded skip and the gate `unverified`; a `None` from `box()` makes that one node a recorded skip. Never a pass, either way. |
| **`portability`** | concept | *(coined here)* A `Receipt` and `OutReport` block recording facts that do not make an artefact invalid but make it break elsewhere: generic-only font stacks, unsafe exported faces, external asset references, unresolved Brief tokens. A separate axis from the IL contract, with its own section, so it cannot dilute the finding counts. |
| **`normalizations`** | concept | *(coined here)* The `Receipt` ledger of every rewrite the compiler performed, each a structured record, only reachable behind `ow out compile --accept-normalization`, and each accompanied by one `Degradation(kind="compile_normalized")` on the artefact row. Without the flag, a `normalize`-disposition construct reaching `lower()` is `OW_TARGET_NORMALIZE_AT_COMPILE`. |
| **`truncations`** | concept | *(coined here)* The `OutReport` and `Receipt` record of every place the validator stopped short: a rule past `MAX_FINDINGS_PER_RULE`, or a report past `MAX_FOLDED_FINDINGS` that re-folded. Required and non-null, and non-empty makes the gate `unverified` — a truncated report cannot release, because the truncated tail may hold errors. |
