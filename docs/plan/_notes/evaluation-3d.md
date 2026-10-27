# omniweave — final evaluation on scalability, compatibility, efficiency

Six independent lenses, each adversarially verified by a second pass. 21 plan documents (42,655
lines), `_plan/_notes/charter.md` (8,683 ln), ten rulings, and `_index/` over 39 vendored
repositories including the 17 agentic-ecosystem repos indexed 2026-09-04, after the plan was written.

## 1. Verdict

| | |
|---|---|
| **Scalability — 6/10** | The driver-publishing machinery is the best in the evidence base and genuinely import-free (INV-4, three enforcers), and T1's envelopes reproduce from their own component budgets to four significant figures. But a third-party driver's *distribution* cannot cause its own format to be parsed — the `format` token domain is core-owned and closed at 48 (`05-ingest-and-routing.md`:627) — and the T2 headline ("5M blocks rather than 50M") is derived nowhere and repeated at eight sites. |
| **Compatibility — 6/10** | The one-text-block Answer is provably the intersection of five MCP clients' capabilities, verified at crewAI's source, and the licence machinery absorbs AGPL, a hosted TOS and a mixed monorepo without an exception. But zero of the eight orchestration frameworks except LangChain and LlamaIndex is named once in 42,655 lines, and no plan document schedules, budgets or lists an adapter. |
| **Efficiency — 7/10** | The cost mechanisms are the strongest engineering in the plan and I could not break the core ones: the cache key makes a re-bill structurally impossible, the demand plan makes "a clean page computes zero paid signals" a consequence of file order, and per-page routing has no priced self-hosted peer. Against that, three headline cost figures err cheap — including a shipped default budget 6% below the shipped escalation driver's own printed price — and only half the graph reaches the query path. |

The efficiency score splits: 7/10 on the cost, routing and caching machinery; 6/10 on graph
structure and retrieval reach, where the evaluation's only blocking defect sits.
**Two of six lenses found the design substantially right** (peer interoperability 7/10, cost
machinery 7/10). Nothing else needed defending.

**Do first, before any code:** fix the two `blocking` items — the `FormatGuess`/`StreamHint` double
definition (2 engineer-days, must precede P1's week-10 `omniweave_ports` freeze) and the
`GraphSink.mention` coordinate-system defect (3-5 engineer-days, must precede any store carrying L3).
Both are cheap now and unrepairable later: the first becomes a `CONTRACT` bump, the second silently
corrupts every L3 span in every store.

## 2. The three dimensions

| Dimension | Score | Genuinely strong — the mechanism | Weakest point | Defect class |
|---|---|---|---|---|
| **Scalability** | 6/10 | `driver.toml` read via `Distribution.locate_file` + `tomllib` with no import; semgrep bans `EntryPoint.load()`, G11 installs a rogue driver that writes a file and raises `SystemExit`, and a core test asserts `sys.modules` gains no `omniweave_driver_*` key (`04-driver-system.md` §4.6). Capability declaration is *clamped*, not documented: `origin_span="none"` caps quotes at `NORMALIZED` in `DocSink.add_block` (`03-document-model.md` §8.3). Shard prefix ships at shard 0 for zero bytes (`07` §12.1). | A conformant, attested, enabled, lockfile-pinned `parse/1` driver's distribution cannot cause its own format to be parsed. Two mechanisms: the 48-token domain is `builtin`-provided (`05`:1704) with lint checks `OW-P-002`/`OW-P-014` binding every rule literal to it; and for a format *inside* the 48, `decode.text-native` already claims it with `terminal=true` (`05`:1335-1341). | **Specification gap** — the design intent is already correct in prose at `05`:638-640 ("it adds a `sniff()` contribution, a `[capability] formats` entry and a policy rule"); the card key, the computed domain and the packaging path were never written |
| **Compatibility** | 6/10 | `serialize(scope, fmt) -> tuple[str, SpanMap]` with no text-only serializer and a `False` `SERIALIZER_CAPS` entry unciteable (`03` §16.1); `.owdoc` as plain ZIP + NDJSON with a generated, byte-diff-gated `document-v1.json` explicitly written for a Rust/TS reader (`03` §3); `restriction_bits` stamped by the runner from the producing card onto every derived row, with `compile` refusing to emit a restricted item (`04` §7.2). | No plan document names or budgets any framework adapter, and `_index/in-04-agentic.md` — the only document written for this lens — has two factual errors: Haystack ships `mcp-haystack` (`_collections/haystack/docs-website/docs/tools/mcptoolset.mdx`), and two of four tools *do* declare `structuredContent` (`10-interfaces.md`:511). | **Specification gap** in the plan (nothing scheduled); **evidence-base error** in `_index/` — a fourth class the brief's taxonomy lacks, where the file to edit is the index, not the plan |
| **Efficiency** | 7/10 | `cache_key()` includes `producer.schema_version` as the only driver version, nulls `code_fingerprint` for `billed_api` and `deps_digest` for non-free, so a bug-fix release provably cannot re-bill (`08-runtime.md` §4.2, §4.8's matrix row "hit — no re-bill"); the paid tier is protected by a *partial index* on `cost_class='free'` so the sweep cannot see a billed row (`08` §4.4); `ceiling()` sums weights over `OK` **or** `EMPTY` channels so a channel that looked and found nothing keeps its denominator weight (`07` §5.3). | `[budget.per_unit] micros_per_part = 800` (`05`:1175) against `parse.page.olmocr`'s own `est_micros = 854` and `reserved_micros = 2,732` (`05`:2417-2418). `micros_max = 250_000` caps payable escalation at 293 pages, so a 1,000-page scanned archive degrades 70% of its pages on a fresh budget under the shipped default. | **Design defect** — a settled value repeated at `charter.md`:2604 and `D4-router.md`:257; the plan prints the collision at `12-performance.md`:705-712 and draws the wrong conclusion from it |

## 3. Scalability

### 3.1 The mechanism that works

Three enforcers on one invariant (INV-4, detailed in §2's table). The negative receipts are in-tree
and verified: docling calls `load_setuptools_entrypoints()` at
`_collections/docling/docling/models/factories/base_factory.py`:96 with the `allow_external_plugins`
gate in the *next* loop at :98-105 — a gate that suppresses registration by code that has already
run — and `unstructured`'s `create_file_type()` mutates `FileType._member_map_` at import time
(`_collections/unstructured/unstructured/file_utils/model.py`:555-579). omniweave is the only design
here where a licence tier, a cost class and a hardware requirement can be read and refused before a
third party's code executes once. That is also why it cannot borrow unstructured's file-type
registration: the same property that earns the strength forecloses the mechanism (§3.2).

T1's arithmetic is reproducible, which is the strongest evidence the capacity model is real. The
100k-document no-GPU ingest wall recomputes from B02/B04/B05/B07/B15/B22/B23 alone to 3.59 h against
the stated 3.6 h (`12-performance.md` §3.1), and the 1,000-document row yields the stated 59% writer
share as 58.62%. The ingest serialisation point is named in four documents, priced at 58.6% of the
no-GPU wall at both 1k and 100k documents, and given one named widening knob (F8) — most designs
with a single writer discover this at month six.

### 3.2 The strongest weakness

**Failure scenario, verified end to end.** Publish `parse.cad.dwg` exactly as `04` §9 prescribes:
card with `[capability] formats = ["image/vnd.dwg"]`, twelve suites passing, attested,
`ow drivers add --enable`, in `omniweave.lock`. Feed it a DWG. Detection yields no token,
`unit.format` resolves to `'unknown'`, and `gate.unsupported-source` (`05`:1249-1254) refuses at GATE
with `failure_class = unsupported_format` before any DECODE rule runs. The operator cannot fix it
with policy: a `project`-layer rule naming `"dwg"` fails lint check 2 because the literal is not in
the signal's domain. The same holds for DICOM, XBRL, DXF, PST, Parquet and GeoJSON.

Worse, the plan's own designated out-of-tree distribution is already a victim.
`06-structure-extraction.md`:1101-1109 declares `omniweave-driver-code` "a real distribution with a
real card" whose first Pass reads "`Kind.CODE` blocks, **`doc.format` in the grammar set**". There is
no source-code member in the 48 — no `py`, `ts`, `rs`, `java`, `toml` — so a `.py` file resolves to
`txt` through the residual probe and the predicate is unsatisfiable for every language.
`derive.code.manifest` compounds it: `pyproject.toml`, `Cargo.toml`, `go.mod` and `Gemfile` all
detect as `txt`, so the pass cannot distinguish them by format at all.

**Fix.** Make the domain a computed union: add `format_tokens = ["dwg"]` to `[capability.parse]`,
compared `⊇` (which fits `05` §2.1's safe-asymmetry rule exactly, because an unrecognised set member
can only make a driver look *less* capable), and derive `SignalSpec.domain` for `unit.format` from
core's 48 plus the union over enabled cards. 1-2 engineer-weeks, before P1 freezes `card_schema = 1`.
Add an eighth publish step so `ow drivers scaffold` emits a `policy.d/` fragment (3-5 engineer-days),
or a seventh read-only `driver` policy layer ranked below `builtin` (another 3-5 days, before P5's
week-38 policy-grammar freeze).

### 3.3 Where the lenses disagreed

Both scalability lenses scored 6/10 and their verifiers moved neither. But three of the assessors'
supporting claims were corrected, and each correction matters.

| Assessor claim | Verifier's correction |
|---|---|
| "Two independent mechanisms block a new format" | Mechanism (a) is operator-bypassable. `05` §4.1's layers *prepend* and first-match-wins, so a prepended `site` or `project` rule pre-empts `gate.unsupported-source` — and a driver can register its own boolean signal via `omniweave.signals` + `signals.toml`, so `when = {"vendor.dwg" = true}` satisfies lint check 2 and leaves check 10 untouched. The blocker is **packaging**, not the router's semantics. |
| "For `ipynb` the wrong driver silently wins" | `parse.text.builtin` is not in the driver roster (`04` §10.1 lists 22; `05` Open question 2 and `17-risks.md`:606 register it as defect `05#2`, remedy "one row in `[drivers] enabled`"). So `driver.unavailable = true` fires and `degrade.driver-unavailable` escalates to DEGRADE with `outcome = "ok_partial"`. A loud `Degradation`, not a silent win. Which driver ultimately wins is genuinely undetermined. |
| "F29's refusal only fires at 8.4M blocks, so there is no working refusal below the failure" | Wrong by a factor of two and on the wrong axis. `MAX_BLOCKS_PER_PAGE = 4,194,304` (`03`:2546) is set for exactly this purpose. The surviving finding is narrower and worse: the ceiling was **deliberately calibrated 4.9% above the known-failing fixture**, with the ~23 s commit printed at :2546 against `loop_lag_max_ms = 250` — a 92x breach — and `03`:2566 says twenty lines later that the same fixture is "refused". |

The verifier also refuted the "T2 arrives at 5M" claim's *replacement*: the assessor's corrected
figure (bytes/block falling 636 → 506, so capacity should *rise*) inherits exactly the defect it
diagnoses — the plan's only two data points are 338 B/block measured and 912 B/block on a corpus
characterised nowhere by blocks/page. The correct finding: **the 5M figure is derived nowhere and is
carried into eight sites** (`charter.md`:8588, `07`:2532, `07`:2822, `02`:1367, `16`:1098, `17`:188,
`17`:424, `README.md`:359, plus `00-vision.md`:747). State F1's two variables separately; derive 5M
from `07` §12.4 item 4's term-selectivity term or delete it. Note that `02`:1367 lists the 600 MB
supervisor RSS gate as an F1 dependent while `12` §4.2 rule 1 states that ceiling is "independent of
document size and therefore independent of corpus" — the one genuinely inert entry.

**Second lens, sharpest independent finding.** The T2 envelope's two named enablers (the WAL valve,
an ANN backend) do not address the binder the plan itself identifies. `07` §12.4 item 4: the lexical
Channel's 50 ms budget breaks "somewhere between 10M and 30M blocks depending on term selectivity",
reporting `UNAVAILABLE(timeout)` and forcing `degraded`. The valve addresses write amplification; the
ANN backend addresses the semantic channel, which is `off` by default. So the top 40% of the T2 range
is a regime in which broadly-filtered queries are degraded by the plan's own mechanism, and `07`
§4.4's latency table has no single-store row between 10M and 100M blocks in either direction.

## 4. Compatibility

### 4.1 The mechanism that works

The Answer's shape is the measured intersection of five MCP clients, not a guess.
`_collections/crewAI/lib/crewai/src/crewai/mcp/client.py`'s `_call_tool_impl` takes
`result.content[0]`, tests `hasattr(content_item, "text")`, and returns
`_MCPToolResult(str(content_item.text), is_error)` — every later block, `structured_content`,
`annotations` and `_meta` discarded. `10-interfaces.md` §3.5 emits one content block ≤ 24,000
characters with greppable `**ow:<name>**` markers and a never-dropped `ow:blocking`. A design relying
on `structuredContent` for the Answer would put the provenance table where nothing reads it.

`00-vision.md` §6.2's poverty argument survives field-by-field source checking in all eight cases:
langchain's `Document` is four fields (`libs/core/langchain_core/documents/base.py`:48,55,306,309);
haystack's is seven with no relationship field; llama_index's `NodeRelationship` is exactly
SOURCE/PREVIOUS/NEXT/PARENT/CHILD with no bbox, page, cell or confidence; MCP's `Annotations` is
`audience`/`priority`/`last_modified` only (`_collections/python-sdk/.../_types.py`:779-790). The
strategic bet is sound. The tactical work is absent.

On the peer-interoperability half the substrate is genuinely excellent: every IN-ward peer attaches
as a ports-only `parse/1` driver emitting NDJSON that carries exactly the fields the peer's own type
drops, and `_index/repos/llama-parse.md` sizes the adapter at "a few hundred lines of field mapping
needing no new abstraction". `needs_network = true` is refused at `resolve()` until a site Grant
covers the corpus, keyed on the card fact rather than the driver's self-reported `bytes_egress`.

### 4.2 The strongest weakness

Exact occurrence counts over all 21 `_plan/*.md`: **langchain 2, llamaindex 1, and langgraph /
haystack / crewai / adk / agentcore / bedrock / pydantic-ai / autogen / dspy 0.** The two
occurrences are `00-vision.md`:512 (a §6.2 heading carrying both names, under a "Why omniweave
instead" positioning frame — i.e. treated as competitors to displace, never as hosts to attach to)
and `README.md`:189 (a documentation-index row). No adapter distribution exists among the fourteen
(`11-repo-layout.md` §1.2); no work item in `16-roadmap.md` §§4-13 mentions one.
`_plan/_notes/final-review.md`:123-176 enumerates five absent subjects and framework attachment is
not among them — the plan does not know the subject exists, and its own honest self-assessment did
not catch it.

**Fails when:** P7 exits at week 42 with v0.1 shipping and the only integration path is MCP. Every
framework-native user sees omniweave as a tool call returning prose — exactly the shape §6.2 argues
is insufficient. The thesis goes untested in code for the life of v0.1.

**Fix, and it is already written.** `_index/in-04-agentic.md` §7 is a ranked costed plan: the MCP
server (0 ew, release-1 scope, reaching five frameworks plus AgentCore Gateway by configuration),
`omniweave-langchain` (3 ew), `omniweave-haystack` (2), `omniweave-llamaindex` (3),
`omniweave-adk` (2) — 10 ew across four adapters, with crewAI, pydantic-ai, agentcore and langgraph's
`BaseStore` each explicitly declined with a source-cited reason. Fold §7 into `16-roadmap.md` as
W7.8 and into the distribution table. 3 ew against 360 is 0.8%.

**The prior evaluation's urgency was wrong on all three named freezes.** Adding a distribution is
classified **non-breaking** (`11-repo-layout.md`:1043); `tools/layers.toml` rows are "derived from the
entry points, never chosen" (:485) so G4 self-derives; the generated-surface registry freezes at P7
week 42, not P1. The one genuinely irreversible item is PyPI name reservation, handled at §7.6 step 0.
**The real deadline is different:** decide whether `Corpus.doc` is `@stable` before funding the two
Tier-C adapters, because `18-api-sketch.md`:494 marks it `@provisional`, `10-interfaces.md` §9.4 omits
it from both lists, and `11-repo-layout.md`:1043 makes removing an SDK attribute a `RELEASE` MAJOR
with no `@provisional` carve-out. Three documents classify one symbol three ways.

### 4.3 Where the lenses disagreed

This is the dimension where the two lenses diverged most, and where the verifiers moved the scores in
opposite directions (agentic 6→5, peer interoperability 6→7).

- **The peer lens's single design defect was refuted by its own strongest strength.** It claimed
  `omniweave-docling` "cannot exist as one distribution" because G4 forces the row
  `["omniweave_ports"]` exactly. The rule reads "declare **only** `acquire`/`parse`/`derive`/`embed`"
  (`charter.md`:194-197), and a `compile`-declaring distribution gets
  `["omniweave_core","omniweave_ports"]` — which is the shape of `omniweave-target-pptx`, whose entry
  points declare both `compile.pptx.native` and `parse.pptx.native` (`04`:950-951). Four shipped
  distributions are the counterexample. Further, the export half needs nothing of omniweave's:
  `ow store export --portable` writes a plain ZIP that "`unzip -l` and `jq` both read with no
  external tool" (`07`:2560-2566). Corrected: a **specification gap** worth ~1 engineer-day of prose,
  not a `major` design defect worth 8 days plus a gate change and fixture.
- **What survives about docling is still real:** `grep -rn "omniweave-docling" _plan/*.md` returns
  zero. The commitment stands only at `charter.md`:905, `D2-docmodel.md`:42 and `README.md`:173, and
  the promised "published fidelity matrix" has no owner, no phase and no engineer-week.
- **The agentic lens's own strength #4 contradicts its own finding #2** on the same cited line:
  `in-04`:186 is the *langchain* row and promises `CellPos`, `OriginSpan`, `marks` and `SpanMap`,
  none of which is a `RenderedBlock` field and all of which sit behind the `@provisional`
  `Corpus.doc()`. Three of four recommended adapters straddle the tier, not two. Against that, the
  types themselves are T-SCHEMA — "a `SCHEMA` major, with a two-release deprecation window"
  (`02`:210) — so the exposure is one call site, not "every published wheel breaks".
- **Two agentic findings were filed as plan specification gaps that are errors in `_index/`.** The
  plan states the `structuredContent` scope correctly at `10-interfaces.md`:511 ("`ow_corpora` and
  `ow_add` are small and row-shaped and do declare one"), and no plan document makes any Haystack
  claim. `in-04` is additionally self-contradictory: :6 says "Four of the eight" need no code, :55
  says "five of the eight ship an MCP client". Corrected count: **seven of eight reachable with zero
  omniweave-side code**, and `omniweave-haystack`'s surviving justification is not access but the
  fact that `MCPTool.invoke` returns a JSON *string*, which escapes §3.5's section layout — the one
  client of six that mangles rather than truncates.
- **Both lenses missed the sharpest on-dimension claim, and a verifier supplied it:** the OUT
  direction is unreachable from every MCP-attached peer. D9 is unambiguous in five places —
  `02-architecture.md`:595, "The OUT direction is **skills plus CLI, never MCP**" — and the generated
  MCP `instructions` hands the agent a pointer instead of a capability (`10`:849: "these tools do not
  generate"). Skills are local files installed into an agent host and they shell out, so a client
  reaching omniweave over `ow serve --http` has neither. Half the product thesis is available to zero
  remote peers, and nothing in the plan writes down the consequence or its cost.

## 5. Efficiency

### 5.1 The mechanism that works

Four mechanisms I attacked and could not break.

1. **The cache key.** `08` §4.2's 12-row justification table makes the paid/free asymmetry
   structural: `code_fingerprint` is included only when *not* `billed_api`, `deps_digest` only when
   `free`. `policy_digest` and `pricebook_digest` are decision-key inputs and deliberately absent
   from the artefact key, so repricing re-prices history for $0 rather than re-billing it.
2. **The demand plan.** `decode.pdf-text-layer` precedes `decode.blank-part-escape` in file order, so
   on a clean born-digital page `plan.deferrals_pending` is false, the LOCAL group is never computed
   and no raster is rendered — 164 of 188 parts on the reference 10-K, enforced by exact counters
   where a deviation of one fails the gate. Compare `unstructured`'s `hi_res`, which pays layout
   inference on every page whether the page needs it or not.
3. **Per-page routing has no priced self-hosted peer.** Verified at source:
   `_collections/unstructured/unstructured/partition/pdf.py`:339-343 computes one boolean over the
   flattened element list, and `Element.routing`/`routing_score` are never assigned anywhere in the
   package. On the reference 10-K `strategy="auto"` selects `fast` and silently returns nothing for
   the 12 scanned exhibits — so omniweave's per-page routing is first a **correctness** mechanism.
   *Narrowed by the verifier:* llama_parse's `auto_mode` is declarative per-page escalation with four
   predicate types and a per-page `triggeredAutoMode` report, and MuPDF gates OCR at *region* grain.
   The defensible claim is that no peer makes a per-page decision that is **priced, replayable at $0
   and self-hosted**.
4. **`Narrowing` as a tagged three-way type.** `kind: Literal['all','set','empty']` with
   `if narrowing:` semgrep-banned, quoted against the real jcodemunch bug where a falsy
   `candidate_ids` skipped the filter and returned every symbol labelled "Confident matches
   returned". "No restriction" versus "restrict to nothing" is the failure that makes `absent`
   unreachable on both fusion paths.

**The brief's central instruction, tested.** `final-review.md` §2 ADR-4 alleges the shipped routing
policy has nine missing `on_unknown`, four dead GATE rules and two `G27` failures. All six TOML blocks
in `05-ingest-and-routing.md` parse; zero of 40 rules read a nullable key without `on_unknown`; check
10 passes exactly at 48 distinct `unit.format` literals; checks 5 and 12 pass. **The eight defects are
in `charter.md`'s 15-rule illustrative block, not in the shipped policy**, and the one
newline-spanning construct is a multi-line array inside an inline table, which TOML 1.0 permits. The
plan's most cost-critical artefact does not fail its own checks; the self-assessment does.

### 5.2 The strongest weakness

`micros_per_part = 800` sits below `est_micros = 854`, so on a fully-escalating document the per-unit
cap grows more slowly than the spend. Corrected arithmetic (the assessor conflated document length
with part index): the cap is fixed at `4,000 + 800P` by `unit.part_count`, and denial begins at
`k > (cap − 2,732)/853.4`. The asymptotic degraded share of any pure scan is **53.4/853.4 = 6.3% of
pages** — so a 100-page scan loses 4-5 pages, not 60. The severe case is `micros_max = 250_000`,
which caps payable escalation at **293 pages**: a 500-page scanned deposition degrades 41% of its
pages and a 1,000-page archive 70%, on a completely fresh budget under the shipped default policy.

The plan prints the collision itself at `12-performance.md`:705-712 —
`161,304 > 154,400, so omniweave would have spilled the last few pages to free` — in a sentence about
a *rejected counterfactual*, without noticing it is also true of a routine, correctly-routed
188-page scan. That changes the fix: raise the number **and** fix the sentence that already saw it.
None of `ow route lint`'s twelve checks compares a budget dimension against any driver's `est_micros`,
which is check 13. 1-2 engineer-days plus one 100-page fixture.

A thirteenth surviving contradiction sits on the same path: `08` §9 says an `ok` with zero blocks is
`empty_result` → "FAILED_PERMANENT before anything is cached", while `05` §6.5 says `spill_to_free`
ends the part as "`ok_partial`, `degraded = 1`". On a scanned page those two sections disagree about
what the tail settles as.

### 5.3 The one blocking defect in the whole evaluation

`GraphSink.mention` cannot produce a correct `ts_a`/`ts_b`. Grounding is
`normalize_k(block.text).find(normalize_k(quote))` (`06`:433, :1970), which returns an offset in
`normalize_k`'s **output** space. `ts_a`/`ts_b` are defined as half-open character offsets into
`block.text` such that `text[ts_a:ts_b]` is the slice (`07`:1981), are `NOT NULL`, and are digest
inputs. `normalize_k` is NFKC · casefold · strip category Cf · fold U+2010..2015 · collapse
whitespace runs · strip (`D7-structure.md`:532-537) — every operation changes length — and
`block.text` is required **NFC** (`03`:284), so compatibility decompositions are live.

For `block.text = "The ﬁnancial report names Acme Corp"` the find returns 26 while
`block.text.index("Acme Corp")` is 25, so `block.text[26:35]` is `"cme Corp"`. Same shift from a
single double space, from any leading whitespace, from a ZWJ (which the plan explicitly claims
"grounds to the real span", `06`:1988), and from ß under casefold. The span **length** is wrong too:
`ts_b − ts_a` is `len(normalize_k(quote))`. It fails silently — `grep -rn "text\[ts_a" _plan/` finds
no CHECK, invariant or property test comparing `block.text[ts_a:ts_b]` against `mention.surface`.

The charter's justification is the reasoning error: "Making `normalize_k` strip Unicode `Cf` deletes
the `ShiftMap` entirely **and** defeats the zero-width-joiner obfuscation attack. One function, three
problems" (`charter.md`:4812; the same sentence is inside the function's own docstring at
`D7-structure.md`:534-537). Stripping characters is precisely what makes an index map necessary. The
framework already uses the length-preserving predicate it needs for the OUT direction one document
over (`nfc(text) == block.text[a:b]`, `charter.md`:6216), and `03` §17 Q2 already records a *sibling*
`normalize_k` misuse in INV-10's `bytes` branch with a pre-committed ADR fix — so the plan has a live
mechanism for exactly this class of error and did not apply it to grounding, which makes this an
oversight rather than a decision.

Verifier corrections: the digest is **stable** (find is deterministic, so full and incremental builds
agree on the same wrong offsets — drop that sub-claim); `normalize_k` has **no graphify original**
(`grep -rn "'Cf'" _collections/graphify/graphify/*.py` returns nothing, so `02`:229's vendoring claim
is itself a plan error and the fix forks nothing and needs no ADR); and the plan carries **two
non-identical definitions** of `normalize_k` (`02`:229 omits whitespace-collapse and strip). The
magnitude is data-dependent, not off-by-one: whitespace collapse in a code block shifts by many
characters and crosses line boundaries, while a 1-3 character shift usually still resolves to the
same covering line child, so the visible blast radius is `Hit.span`, the highlighter and
`precision='char'`.

### 5.4 Where the lenses disagreed

- **Half the graph is not in the query path.** The `structural` channel traverses `block_link` alone
  (`07`:1181, `16`:690, `18`:2760); the L3 entity graph is reachable only through the `@provisional`
  `GraphView.neighbours()`, outside `retrieve()`, with no budget, weight, ceiling contribution or
  Verdict; `community_report` has no channel and `Query.mode` has no thematic member. Yet
  `community_report.full_content` is one of exactly three things the framework embeds, and CI fails
  an embedding with no declared consumer. **The verifier corrected the fix:** `16`:765 commits W8.9
  (P8, 4 units) to "the structural channel's L3 half", so the honest-disclosure option would put
  document 07 in direct conflict with the roadmap. The real finding is a **six-document
  contradiction** (03/07/16/18 plus `02`:117 and `README`:244) about what `structural` traverses, with
  a roadmap commitment on the side 07 does not specify. And `18`:2767-2770's own worked example passes
  `relations=frozenset({"anchor_ref","note_ref","continues"})` — three L2 `RelKind` members that
  `block_link`'s FK to `relation_vocab` rejects, so those rows cannot exist.
- **The 210-against-250 budget.** The assessor called it "~1 ms of headroom at 10M blocks"; the
  verifier refuted the premise — `07` §4.4 states the channels sum "below the query budget **net of
  hydration and the coverage scan**", so the 40 ms gap *is* the reservation and 25 + 14 = 39 fits it
  with 1 ms of deliberate margin. What survives: the reservation is an implicit gap rather than a
  config key, so `ow route lint` will pass a `channel_ms` edit summing to 249 that destroys it, and
  the arithmetic mixes worst-case budgets with estimated actuals (the 10M row totals ~110 ms p50).
  The genuinely sharp half was buried: `ceiling()` sums over `OK` and `EMPTY` only, so a runtime
  `OFF(query_deadline)` pre-emption **shrinks the denominator and can make the answer look more
  confident**. `OFF(vectors)` and `OFF(query_deadline)` are collapsed into one status when only the
  first should be ceiling-exempt.
- **The `1 − Cover` substitution.** `06` §2.4 states in bold that billed share "is **not**
  `1 - covered_frac`, because the gate is per-Segment and a Segment at 0.59 is billed entire", and
  prints weighted covered 0.476 against weighted billed share 0.564. `12` §6.3-6.5 uses exactly
  `1−0.55`, `1−0.25`, `1−0.50`. Verifier correction to the magnitude: the **billed segment count** is
  low by 7-23%; the **C3 totals** by roughly 5-8%, not 8-17%. Still the direction `12` §6.2 itself
  says "gets someone fired".
- **The showcase parsing achievement does not reach the semantic channel.** Above
  `TABLE_SYNOPSIS_CELLS = 20_000` a table becomes one synopsis segment and one embedding, so "a
  merge-free 4M-cell sheet is 4,000,000 FTS rows, 4,000,000 citable blocks and **one** embedding"
  (`06`:846-847), and a semantic hit "lifts to the synopsis segment's own blocks and never to the 4M
  cells it summarises" (`07` §5.6). `SEM_BLOCKS_PER_SEGMENT = 64` against `MAX_SEGMENT_BLOCKS = 512`
  means the cap bites for up to 448 blocks of ordinary tables. Disclosed —
  `Diag(OW_TABLE_SYNOPSIS_ONLY)` is in `ABSENCE_BLOCKING_DIAGS`, so such a query degrades — hence a
  limitation and not a defect, but the largest gap between the plan's parsing quality and its
  retrieval reach.
- **One index claim did not survive source checking.** `_index/comparisons.md`:107-109 says "none of
  the three has" a per-cell polygon. `_collections/marker/marker/schema/blocks/tablecell.py`:7-14
  makes `TableCell(Block)` carry `rowspan`, `colspan`, `row_id`, `col_id`, `is_header`, and
  `base.py`:83-88 gives every `Block` a `polygon` and a `page_id`. omniweave still wins on the
  durable citable id per cell, the `OriginSpan`, the derived lazy `grid_slot` cover map and the
  absence of an `html` field — but not as "no peer has this". A claim taken from `_index/` and not
  re-checked in `_collections/` is the one systematic weakness in the evaluation method itself.

## 6. What changed since the previous evaluation

The prior evaluation ran before the 17 agentic repos were indexed. Each of its twelve claims was
re-tested by the lens that owned it: three confirmed, eight corrected, one overturned.

| # | Prior claim | Verdict | The correct statement now |
|---|---|---|---|
| 1 | Adding a format is cheap and genuinely open | **corrected** | Cheap and open for the **driver**; closed at the **router**. The capability declaration is better than claimed (clamped by `MAX_QUOTE_BY_OS_KIND`, not merely disclosed), but a new format needs a core release to widen a `builtin`-provided SignalSpec domain. |
| 2 | OUT is a framework/target split, not a universal IL | **confirmed** | Holds exactly. D8 rejects a universal IL with a receipt; a Target is two Drivers plus eight target-owned files; P9 sums to 60 ew precisely (14+16+5+6+7+0.5+4+4+3.5). |
| 3 | Dozens of input formats is normal; each output format is a quarter of work | **overturned** | Both halves fail, in opposite directions. Each new input format needs a core release **plus** an operator-written rule no wheel can ship. Each additional output Target is **6-10 engineer-weeks** — 25.5 of P9's 60 ew is one-time shared framework, and docx came in at 6 ew, a third of pptx, exactly as its estimation basis predicted. |
| 4 | T2 may be an order of magnitude off | **corrected** | The plan does say "5M rather than 50M" at eight sites, but the figure is **derived nowhere** and F1 is a two-variable envelope (blocks/page × bytes/block). Block-denominated quantities move via bytes/block, not blocks/page. The real F1 exposure is per-document (`rss.gen5000p_peak_bytes`: a 5,000-page PDF becomes 1.5M blocks, 2.5x the assumed 600k). |
| 5 | **The plan has no integration story with any agentic framework** | **confirmed** | Re-measured with exact occurrence counts: langchain 2, llamaindex 1, everything else **0**. One correction to the prior wording — the three occurrences are not "both in §6.2"; they are the §6.2 *heading* and a `README.md` index row, and the §6.2 body names no framework at all. The author was right to act on this claim by adding the 17 repositories. The plan's own final review, which reports twelve contradictions and five absent subjects, did not catch it either. |
| 6 | The primitives an adapter needs already exist | **corrected** | `serialize() -> (str, SpanMap)` with no text-only serializer, segments as a projection, zero-overlap unrepresentable by `PRIMARY KEY (block_id)`, and the T-SCHEMA typed model re-export all confirmed and stronger than claimed. But **DoclingDocument import/export is not a primitive that exists** — `omniweave-docling` appears in zero of the 21 documents — and `quad`, `score`, `score_kind` sit on `Answer.evidence` in §9.1 while appearing in **neither** stability list in §9.4. The two lenses that both verdicted this claim split on it; the peer lens is right that the docling half is absent, the agentic lens right that everything else holds. |
| 7 | An adapter is missing and must be decided before P1 | **corrected** | The gap is confirmed; the urgency was wrong on all three named freezes. Adding a distribution is non-breaking, `layers.toml` self-derives, and the surface registry freezes at P7 week 42. The real deadline is the `Corpus.doc` stability decision, which three documents currently answer three ways. |
| 8 | A graph structure is adopted and correctly layered | **corrected** | L2-as-tree-plus-closed-`rel`, L3 above the pivot with one writer, no geometry at L3, deterministic-before-LLM enforced by the printed selector — all confirmed verbatim. The correction is the final clause: `structural` traverses `block_link` **only**. `README`:244 and `02`:117 say "`block_link`/`edge`" and are wrong. |
| 9 | The Segment is exactly one chunking serving four roles | **corrected** | "Exactly one chunking" is enforced structurally. Three of four roles hold. The fourth is wrong: **the Segment is not the packing unit** — packing is per-block (`k=20`, `max_blocks=60`, `max_chars=24_000` cut at a block boundary) and the fusion key is deliberately the Block, with `07` §5.4 giving three reasons. |
| 10 | Grounding is one `str.find`, four jobs in one | **corrected** | The policy is right and the injection analysis is the best in the plan, but "one `str.find`" is false twice: it cannot produce the occurrence **count** §1.7 mandates, and it returns an offset in the **wrong coordinate system** (§5.3). This is the evaluation's only blocking defect. |
| 11 | Five cache layers, a version-stable key, 13.4x routing, 210 against 250 | **corrected** | Layers, key stability and 210/250 confirmed. Three corrections: `cache_index` is created in `0004_runtime.sql` **inside the store** (`07`:240, `08`:2389), so all three advertised second-store cases fail; 13.4x is algebraically `1/escalated_fraction` on a document at 6.9% escalation against an unmeasured 18.8% planning rate, with corpus figures of 5.3x, 3.0x and 1.0x on pure scans; and the 40 ms of query headroom is 39 ms consumed at 10M blocks with lint check 3 blind to it. |
| 12 | The `covered_frac` economics are labelled projections with a pre-committed fallback | **confirmed** | Confirmed and extended. `06` §2.4 opens "**These are projections and are labelled as such**"; F13's fallback is one config key and no schema change. At covered_frac 0.15 instead of 0.55, corpus A's C3 goes $10.79 → ~$14.81 (+37%), not an order of magnitude, because the billed pass sends the whole Segment regardless. Aggravated by the `1 − Cover` substitution in `12` §6.3-6.5. |

## 7. The blocking list

**Two items, both cheap now.** Everything else the six lenses raised is `major` or `minor`. For a
42,655-line design plan with 41 deferred items, two blocking defects — one a wire-type duplication,
one an off-by-a-few-characters — is a strong result and should be read as one.

| # | Item | Fix | Cost | Deadline |
|---|---|---|---|---|
| 1 | **`FormatGuess` and `StreamHint` are each defined twice, incompatibly, and both are in `sniff()`'s signature** — the first method a third-party parse driver implements. `04` §1.3 gives `FormatGuess` two fields; `05` §2.1 gives it six including `format` and a closed five-value `basis` Literal; `18`:1807 states flatly "`FormatGuess` is `(media_type, confidence)`". `StreamHint` is three fields vs five, and `05`'s version drags routing's `TrustClass` into `omniweave_ports`, whose `layers.toml` row is `[]`. Neither name is in `17-risks.md`'s two registers nor in `final-review.md`'s twelve contradictions. | Ports carries `(media_type, format_token, confidence, consumed_bytes)` — a driver must be able to name a token but must not name a `basis`, which is the host's classification of *how* the guess was obtained. `StreamHint` drops `trust_class`. Delete `05` §2.1's duplicate declarations, replace with a reference plus a host-side `RankedGuess(guess, basis, detail)`. Add both names to `terminology.md`'s lock. | **2 engineer-days** | **Before P1's week-10 freeze** of "every type in `omniweave_ports`" and `CONTRACT = 1` (`16`:356-362). After that it is a `CONTRACT` bump on a `RELEASE` MINOR. |
| 2 | **`GraphSink.mention` cannot produce a correct `ts_a`/`ts_b`** (§5.3). No CHECK, invariant or property test would catch it. | Make `normalize_k` return `(normalized: str, back: tuple[int, ...])` built during the transform, and map `i -> back[i]`. Add a property test over ligature / double space / leading space / Cf / casefold-expanding fixtures. Specify the counting loop `.find()` cannot provide, and pick which of the two `normalize_k` definitions is authoritative. | **3-5 engineer-days** (the map is ~30 lines; the fixtures and the definition reconciliation are the bulk — no vendoring fork is needed, contra the assessor) | **Before `GraphSink` is written** (P8, W8.4-8.9). Deferring means every L3 span in every store is silently wrong and unrepairable without re-grounding the corpus. |

**Ranked immediately below blocking**, because deferral cost rises with a freeze: the `format`
domain as a computed union (1-2 ew, before `card_schema = 1` freezes at P1); the eighth publish step
plus a corrected §9 Step-5 transcript (3-5 ed, before P5's week-38 policy-grammar freeze); the
`Corpus.doc` three-way stability contradiction (a one-line reconciliation, before funding any
adapter); `micros_per_part`/`micros_max` plus lint check 13 (1-2 ed, no freeze, but every cost figure
inherits it); and W9.4b/W9.5b — P9 prices docx as "roughly a third of pptx", a ratio taken against
W9.2's 16 ew *compile* half, structurally excluding W9.3's 5 ew reader, so `read_back` for two of
three targets is priced by a ratio that excludes it (~5-8 ew, discovered at the week-56 freeze
otherwise, and R2/R3 cannot pass without it).

## 8. The measurement backlog

Ranked by decision value: a measurement that could change the architecture outranks one that changes
a constant.

| Rank | Measurement | Charter finding | Cost | If pessimistic |
|---|---|---|---|---|
| 1 | **Where a single-page commit actually fails.** `MAX_BLOCKS_PER_PAGE = 4,194,304` is set 4.9% *above* the known-failing 4M-cell fixture; the admitted commit is a printed ~2.8 GB WAL and ~23 s against `loop_lag_max_ms = 250` (a 92x breach, and `17` R-T13's own detection trigger) and exceeds `wal.bulk_index_peak_bytes = 2 GiB ± 512 MiB`. | **F29** (`charter.md`:8616) | 1 ew for the fixture plus calibration | A sub-page commit boundary: a fourth span level and a change to the work table's unit. **3-4 ew and an architecture change.** `MAX_GRID_SLOTS = 4_000_000` is non-firing on the same fixture for the same reason, so a fix must move two constants, and `03`:2546-vs-:2566 must be reconciled either way. |
| 2 | **Blocks per page including cells.** Estimated 60-120; measured 338 B/block with one synthetic corpus at 912. Nine claims repoint at once (`17` A3). | **F1** (`charter.md`:8588), scheduled DP8 week 18 | 3 ed (`fixtures/gen/gen_5000p_pdf.py` plus ten real 200-page documents) | The T2 fallback as written is un-derived. State the two variables separately: bytes/block moves B33's 45 ms frame budget and `VEC_BRUTE_MAX`'s block equivalence (derived "at 140 B/block"); blocks/page moves the per-document RSS and storage projections. |
| 3 | **`covered_frac` on real corpora.** Decides whether L3 is economically buildable and therefore whether the entity graph, communities and reports exist to be queried at all. | **F13** (`charter.md`:8600) | Fixture-driven; the fallback is one config key and no schema change | Below a 0.2 median, `06` §2.4 is "rewritten rather than defended" and deterministic-first becomes a correctness argument, not an economic one. K-8 goes further: L3 ships as Segments and anchors only — exactly the subset the `structural` channel depends on. |
| 4 | **recall@10 of `sig` → top-1000 → f32 rerank; and which ANN library clears G3 with pure wheels for nine cells.** | **F9**, **F10** (`charter.md`:8588) | Bench plus licence scan | K-4 (recall < 0.80) **deletes the semantic channel**, `DEFAULT_WEIGHTS` loses an entry and the ceiling arithmetic changes. F10's fallback removes one of T2's two named enablers. Below 0.95 recall the stdlib backend ships `sig_full` at ~3.2 KB/segment instead of 112 B — a 29x storage change. |
| 5 | **The single-store serving ceiling in blocks, and the cost of N open Readers.** `07` §12.5 says "~10M well, 10-50M with the valve"; §12.4 item 4 says lexical breaks at 10-30M. A 3x range that decides whether a 100k-document deployment is 4 stores or 12 — and nothing prices N open stores in one process. | **P-Q8**, **R-Q6** (`16`:1179) | 3 ed for R-Q6, on top of the bench sweep | The two must run together: P-Q8 sets N and R-Q6 prices it. **P-Q8's own instrument does not exist as specified** — `12` §7.1's `query` subject runs at 10k/1M/10M and P-Q8 requires 10M/20M/30M/50M after an FTS5 `'merge'`. Separately, `10`:2266 ships `max_sessions = 64` at four corpora each = 256 held readers against `12` §4.1's budgeted 16, and `ow doctor` refuses on workers only. |
| 6 | **The shipped PAGE driver's per-request wall at concurrency, and server-coalescing effectiveness.** B09's p50 and p95 are both printed "**unknown** — the single largest hole in the capacity model". | **F7** / B09 (`charter.md`:8588) | 3 ed; the instrument and fixture are already specified (`ow bench service`) | The 100k GPU ingest wall is a 2.7x band, and `12` contradicts itself on it: §3.1 says 19-77.6 h, §3.4 says 19-52 h for the same quantity — §3.1's upper bound silently sets C_eff = 1.0, outside F7's own declared [1.5, 4]. A coalescing regression that halves throughput moves no gated clock and no gated counter (§8.5). |
| 7 | **The per-scale query latency table.** `07` §4.4's ~12/35/110 ms at 10k/1M/10M are estimates; the only measured retrieval numbers in the plan are the 81 ms signature scan and the 250 ms gate. | **F50** (`07` Open questions) | ~1 ew (`ow bench query`) | Decides whether the 210-against-250 budget holds. F50's own fallback is to raise the lexical budget and cut one of `structural`/`semantic` at plan time — the right shape, and why the runtime `OFF(query_deadline)` ceiling bug matters more than the arithmetic. |
| 8 | **The five-channel `DEFAULT_WEIGHTS`.** `{identity 2.0, exact 1.2, lexical 1.0, semantic 0.8, structural 0.4}` — four transplanted verbatim from jcodemunch's four-channel *code-search* fusion, the fifth invented for the split documents force. | **none.** No charter finding, no risk row, no roadmap deliverable. F11 covers only `W_HEAD`/`SPINE_DECAY`. | 1 ew on top of the existing `ow route propose` isotonic fitter | `confidence = best_score / ceiling` and `low_confidence < 0.35` are computed directly from these numbers, and `scorer=1` is pinned into `omniweave.index.lock`'s header — so changing them after release invalidates every published confidence number. This should be a P6 exit gate, not a post-v1 activity. |
| 9 | **`block_link` rows per block, per document class.** Nowhere estimated. The `structural` channel holds a 40 ms budget and a 0.4 ceiling weight, and its input comes only from the two `xref` passes — projected `covered_frac` 0.10 for scanned correspondence (`xref.pattern` only) and 0.02 for photographs (none). | none | 2-3 ed; `RunReport.xrefs_bound` and `ow graph residue` already ship | On a 5,000-page scanned matter the channel returns EMPTY on essentially every query while its 0.4 weight sits in the ceiling as a permanent denominator penalty, depressing every confidence figure. The fallback — drop `structural` from the `default` plan for that corpus — needs no new mechanism; `07` §6.2 can already express it. |
| 10 | The rest, each changing a constant rather than a decision: **F55** (FTS5 segment accumulation — the only `07` §12.4 binder with no `ow bench` subject, governing the workload `12` §6.7 calls "the workload a deployed system actually runs"; `major`, not `minor`, by §7.1's own admission criterion), **F8** (scheduler overhead — the only knob on the serialisation point carrying 58.6% of the no-GPU ingest wall at both 1k and 100k documents), **F12** (grounding quarantine rate — above ~30% a fuzzy fallback makes the blocking defect strictly harder), **F16/F17/F18** (OUT: `part` determinism, the `project()` ceiling at ~70%, whether any rasterizer clears `licences.toml` — F18 failing empties a whole `Disposition` tier), **P-Q3** (the 18.8% escalation rate that *is* the routing multiple), **P-Q5/B16**, **P-Q7** (`route_decision` has no DDL anywhere in the plan, so neither the ~850 MB nor the ~1.2 GB figure can be recomputed on paper), **F26**, **F37**, **F52**, **F54**, and the ten unmeasured day-one escalation signals including `garble.score`, whose `garble_escalate = 0.50` gates the whole DECODE→PAGE cost decision against a `[calibration] eval_set_id` that ships as the empty string. | various | — | — |

## 9. Recommendation: is this plan ready to build?

**Yes, after roughly two engineer-weeks of specification work — not after a redesign.**

The plan's `buildable: true` self-assessment survives adversarial verification on all three
dimensions. Across six lenses and six verifications, exactly **two** items are blocking, both are
specification-shaped rather than architecture-shaped, and both cost under a week. Every substantive
architecture decision I attacked held: D8's refusal of a universal IL, D9's skills-not-MCP OUT
direction, the closed seven-member `RelKind` with the open escape one layer up, zero-overlap
segments, the Block as fusion key, `Narrowing` as a tagged type, the partial index on
`cost_class='free'`, and INV-4. Two of six lenses found their half of the design substantially right.

The pattern in the defects is consistent and it is the cheap pattern: **the plan decided correctly
and did not write it down.** Twelve surviving contradictions are named in `final-review.md`; the six
lenses found roughly eighteen more, and every one is a duplicate definition, a stale sentence, an
un-updated count or a missing reconciliation between two documents that agree in intent. That is
what a 42,655-line plan written by many passes looks like. It is not what a wrong architecture looks
like. The one place the plan is genuinely under-designed rather than under-documented is the
router's format domain, and that is 1-2 engineer-weeks.

**First three things, in order.**

1. **Ports freeze prep (2 ed).** Resolve `FormatGuess`/`StreamHint` to one shape, lock both names in
   `terminology.md`, and classify `quad`, `score`, `score_kind`, `doc_uri`, `defanged` and
   `Corpus.doc` in `10-interfaces.md` §9.4 — reconciling `11`:1043's `RELEASE`-MAJOR SDK rule against
   §9.4's `@provisional` tier, which currently answer the same question two ways. This is the only
   work with a hard week-10 wall.
2. **Grounding (3-5 ed).** Give `normalize_k` its back-map, pick the authoritative definition of the
   six operations, add the property test and the occurrence-counting loop. Do it before any DDL
   carries a `mention` row.
3. **The format-domain and publish-path pair (1-2 ew plus 3-5 ed).** `format_tokens` as a
   `⊇`-compared card key, the computed SignalSpec domain, lint checks 2/10/11 over the union, the
   media-type↔token mapping function nobody has specified, and an eighth publish step that emits and
   installs the routing rule. This decides whether V10-12 — an externally-authored driver as a v1.0
   release criterion — is achievable at all, and it already has a first-party victim in
   `omniweave-driver-code`.

### Recommended stage 10 — reconciliation and decision, 10 engineer-weeks

Warranted, and it must precede P1's week-10 freeze for its specification half and P2's DDL for its
model half. It is not a design stage; it produces edits, decisions and three spikes, and it should
produce no new mechanism.

| Workstream | Output | ew |
|---|---|---|
| **S10.1 Contract reconciliation** | The two blocking fixes, plus the ~18 contradictions the lenses found that `final-review.md` does not list, each closed with an edit or an ADR: `FormatGuess`/`StreamHint`×2, `03`:2546-vs-:2566, `04` §9 Step-5 vs `decode.text-native`, `09` §12's docx R3 against R3's own `fidelity` condition, `Corpus.doc`×3, `RenderedBlock`'s five unclassified fields, `12` §3.1-vs-§3.4, `12` §1-vs-`11`:1529 on the runner's GPU, `07` §4.4-vs-lint-check-3, `08` §9-vs-`05` §6.5 on `empty_result`, `derive.`-vs-`parse.fields.lift`, the three `owdoc-fragment` key spellings plus P24-vs-`achieved`, `18`:2767's `Expand.relations` example, the six-document `structural`-channel disagreement, 850-vs-865 tokens, and `omniweave-docling`'s absence from the 21 documents | 3 |
| **S10.2 Format extensibility** | `format_tokens` card key, computed domain, lint checks 2/10/11 over the union, the media-type↔token mapping function, the eighth publish step, and a decision on the seventh read-only `driver` policy layer (noting that `[[pin]]`'s typed `PinRejected` already gives a driver author a per-unit demonstration path, so any fix that omits it will re-derive it) | 2 |
| **S10.3 Cost calibration** | `micros_per_part`/`micros_max` set above `reserved_micros`, lint check 13, the `1 − Cover` → billed-share rewrite of `12` §6.3-6.5, `12` §3.4's two missing commit rows plus a per-configuration binder row in §3.1, and the `cache_index` second-store claim either fixed (a machine-scoped sidecar under `roots.cache`, 2-3 ew) or retracted (1 ed) | 1 |
| **S10.4 Ecosystem attachment** | Correct `_index/in-04-agentic.md`'s Haystack row, its `structuredContent` scope and its four-vs-five arithmetic; fold §7's ranked 10-ew adapter plan into `16-roadmap.md` as W7.8 and into the distribution table; publish the geometry-in-an-untyped-dict key schema as a generated T-SCHEMA artefact so out-of-tree reverse adapters converge instead of diverging; write down D9's OUT-over-MCP consequence; add the `COPYLEFT_NETWORK`-and-listening-transport conjunct to `ow serve --http` | 2 |
| **S10.5 Measurement spikes** | Backlog items 1, 2 and 5 run as spikes — the 4M-cell commit fixture, `gen_5000p_pdf.py` plus ten real documents, and the paired P-Q8/R-Q6 sweep (which needs `12` §7.1's `query` subject extended to 20M/30M/50M first, since it does not currently cover the block counts P-Q8 requires) | 2 |

**What stage 10 must precede.** S10.1 and S10.2 precede P1's week-10 freeze of `omniweave_ports`,
`CONTRACT = 1` and `card_schema = 1`. S10.5's F29 spike precedes P2's migration sequence, because a
sub-page commit boundary would change the work table's unit and P2's 91 tables share one
strictly-ordered sequence. S10.4 precedes P7 week 42, when the generated-surface registry freezes.
S10.3 precedes nothing structurally and is the cheapest honest win in the list.
