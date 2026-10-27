# Stage 10 — the fix ledger

**Status:** binding for stage 10 only. Written by the S10 planner from
[evaluation-3d.md](evaluation-3d.md) after re-verifying every finding at its cited line.

**How to read this.** Nine fixers work nine disjoint file sets in parallel. Read
[§0 Decisions](#0-decisions) and [§1 Terminology additions](#1-terminology-additions) **in full**,
then your own cluster section, then nothing else. Every fact that appears in more than one document
is resolved once in §0 with its exact wording; a cluster row that says "apply D7" means paste D7's
text, not re-derive it.

**Cluster map, and the files each owns exclusively.**

| cluster | files | baseline `wc -l` |
|---|---|---:|
| C1-docmodel | `_plan/03-document-model.md`, `_plan/_notes/terminology.md` | 3068, 606 |
| C2-drivers | `_plan/04-driver-system.md` | 2514 |
| C3-routing | `_plan/05-ingest-and-routing.md` | 2784 |
| C4-structure | `_plan/06-structure-extraction.md` | 2387 |
| C5-store-runtime | `_plan/07-store-and-retrieval.md`, `_plan/08-runtime.md` | 2883, 2700 |
| C6-performance | `_plan/12-performance.md` | 1839 |
| C7-out-roadmap | `_plan/09-generation.md`, `_plan/16-roadmap.md`, `_plan/11-repo-layout.md` | 2661, 1208, 2566 |
| C8-interfaces | `_plan/10-interfaces.md`, `_plan/18-api-sketch.md` | 2662, 3264 |
| C9-evidence | `_index/in-04-agentic.md` | 301 |

`wc -l` before and after. Snapshots are at `_plan/_notes/.snapshots/s10-pre-fix/plan/<name>`. A file
that shrinks by more than its ledger rows delete is damaged — restore and start over.

**Not owned by any cluster.** `00`, `01`, `02`, `13`, `14`, `15`, `17`, `README.md`, `glossary.md`
and `charter.md` are out of scope for this stage. Where a fix leaves one of them stale, the row says
so and the fixer **reports it and does not touch it**. The list is [§11](#11-out-of-cluster-follow-ons).

---

## 0. Decisions

### D1 — `FormatGuess`, `StreamHint`, `RankedGuess`, `Basis` (blocking 1)

**Question.** `FormatGuess` and `StreamHint` are each declared twice, incompatibly, and both are in
`sniff()`'s signature. `04`:207-212 gives `StreamHint` three fields and `FormatGuess` two; `05`:536-553
gives `StreamHint` five (including `trust_class: TrustClass`) and `FormatGuess` six (including
`format` and a closed five-value `basis` Literal); `18`:1807 states "`FormatGuess` is
`(media_type, confidence)`". `05`'s version drags routing's `TrustClass` into `omniweave_ports`,
whose `tools/layers.toml` dependency row is `[]`.

**Resolution.** `omniweave_ports` carries exactly this, and it is the **only** declaration of these
two types in the plan. A driver **must** be able to name a format token — that is what makes a new
format reachable — and **must not** name a `basis`, which is the host's classification of *how* a
guess was obtained. `StreamHint` drops `trust_class` for the same reason: a driver has no business
seeing it, and it is what pulls `TrustClass` across the layer boundary.

**Canonical block (the ports declaration). Paste verbatim.**

```python
# omniweave_ports/detect.py — THE declaration. Nothing else in the plan re-declares these.
@dataclass(frozen=True, slots=True)
class StreamHint:
    """What the HOST knows before any driver looks. A hint, never an authority."""
    filename: str | None             # basename only — never a path (a path leaks roots into a card test)
    extension: str | None            # lower-cased, WITH the dot: '.docx'
    declared_media_type: str | None  # an HTTP Content-Type or a connector's claim
    byte_len: int | None             # None for a stream of unknown length
    # NO trust_class. `TrustClass` is routing's, and `omniweave_ports`' layers.toml row is [].

@dataclass(frozen=True, slots=True)
class FormatGuess:
    """One detection candidate as a DRIVER may state it. Four fields, and no more."""
    media_type: str
    format_token: str                # the framework's own token: 'pdf', 'docx', 'eml', …
    confidence: float                # [0.0, 1.0] inclusive; a third party's is CLAMPED to 0.95
    consumed_bytes: int              # how far into the stream the guess looked
    # NO basis and NO detail: `basis` is the HOST's classification of how a guess was obtained,
    # and a driver has no standing to assert it. __post_init__ raises outside [0.0, 1.0].
```

**Canonical block (the host-side wrapper). Paste verbatim.**

```python
# omniweave/route/detect.py — HOST side, never in omniweave_ports.
Basis = Literal["magic", "container_identity", "content_probe",
                "extension", "declared", "driver_sniff"]

@dataclass(frozen=True, slots=True)
class RankedGuess:
    """A FormatGuess plus what only the host can say about it. This is what ranks, what enters
    `doc.format_evidence`, and what the ladder in 05 §2.2 emits."""
    guess: FormatGuess
    basis: Basis
    detail: str                      # 'PK\x03\x04 + OPC officeDocument -> wordprocessingml.document'
```

**Canonical sentence for the `sniff()` boundary.** `sniff()` keeps its signature
`def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]`. The host wraps each
returned `FormatGuess` in a `RankedGuess` with `basis = "driver_sniff"` and a `detail` naming the
driver id.

**Consequences, each assigned.** `04` §1.3 replaces its two declarations with the canonical block
(C2-1). `05` §2.1 **deletes** its two declarations and replaces them with a reference plus the
`RankedGuess` block (C3-1). `05` §2.2 ladder step 4 stops saying "the driver's own basis" (C3-2).
`05` §5.1's `unit.format_basis` domain gains `driver_sniff` (C3-3). `18`:1807's flat sentence is
corrected (C8-1). `terminology.md` gains four rows (C1-9, listed in §1).

`Basis` has six members, not five: the ladder's step 4 is a driver contribution and it needs a basis
of its own. `driver_sniff` is that member.

### D2 — `normalize_k`'s signature and its one authoritative home (blocking 2, part 1)

**Question.** The plan carries two non-identical definitions (`02`:229 omits whitespace-collapse and
strip; `terminology.md`:326 has all six operations) and the stated return type cannot support
`GraphSink.mention`.

**Resolution.** `normalize_k` returns `(normalized: str, back: tuple[int, ...])`, where `back[i]` is
the index **in the input** of the character that produced `normalized[i]`. The map is built **during**
the transform, one operation at a time, and never by composing `str` methods after the fact. The
**one authoritative home for the six operations and the signature is
[06-structure-extraction.md](../06-structure-extraction.md) §1.7**, immediately after `MentionDraft`
— 06 owns grounding and owns `GraphSink`. `terminology.md`'s row becomes the short definition plus
the return type plus a pointer to 06 §1.7.

**Canonical block. Paste verbatim into 06 §1.7.**

```python
# omniweave_core/ident.py — THE definition. `02` §2 row 5 and `terminology.md` name it and
# point here; neither restates the operations.
def normalize_k(s: str) -> tuple[str, tuple[int, ...]]:
    """The GROUNDING normaliser. Returns the normalised string AND a back-map:
    `back[i]` is the index in `s` of the character that produced `out[i]`, so an offset found in
    `out` space is recoverable in `s` space. Six operations, in this order, each of which changes
    length — which is precisely why the back-map exists:

      1. NFKC                       (compatibility decompositions; `block.text` is NFC, so these
                                     are LIVE — U+FB01 becomes two characters)
      2. casefold                   (U+00DF becomes 'ss': one character becomes two)
      3. strip Unicode category Cf  (U+200B, U+200D and friends vanish)
      4. fold U+00AD and U+2010..2015 to '-'
      5. collapse whitespace runs to a single U+0020
      6. strip leading and trailing whitespace

    The map is built DURING the transform: each step carries its predecessor's indices forward,
    an expansion repeats the source index once per produced character, and a deletion drops it.
    `len(out) == len(back)` is asserted. `back` is empty exactly when `out` is empty.

    It is NOT `normalize_key` (the blocking-key normaliser, `02` §2 row 5) and NOT
    `sanitize_label()` (§9.2). Three functions, three jobs, and they are not interchangeable.
    """
```

**Canonical correction of the reasoning error.** Every site that says stripping `Cf` removes the
need for a shift map is **wrong and must be replaced** by:

> Stripping characters is precisely what makes an index map necessary. Fix (b) — defanging a copy —
> is what keeps the ZWJ obfuscation attack invisible to *matching*; the back-map is what keeps the
> *offset* recoverable. Two problems, two mechanisms, and conflating them is what produced the
> `ts_a`/`ts_b` defect.

Sites: `06`:1979-1988 (C4-4), `terminology.md`:326 (C1-9). `charter.md`:4812 and `02`:229 are out of
cluster — report, do not edit (§11).

**The vendoring claim is a plan error.** `grep -rn "'Cf'" _collections/graphify/graphify/*.py`
returns nothing: `normalize_k` has **no graphify original**. `11`:159's `(vendor/graphify-ids)`
annotation is corrected to cover `normalize_key` only (C7-9). **No fork, no ADR** — the adversarial
verifier settled this. `02`:229 carries the same wrong claim and is out of cluster.

### D3 — `GraphSink.mention`'s grounding algorithm (blocking 2, part 2)

**Question.** Grounding is specified as `normalize_k(block.text).find(normalize_k(quote))`, which
returns an offset in `normalize_k`'s **output** space, while `ts_a`/`ts_b` are half-open character
offsets into `block.text` such that `text[ts_a:ts_b]` is the slice (`07`:1979-1981). Every operation
in `normalize_k` changes length. `.find()` also cannot produce the occurrence **count** that
`06` §1.7 requires.

**Resolution.** One canonical algorithm, stated once in `06` §1.7 and referenced from everywhere else.

**Canonical block. Paste verbatim into 06 §1.7.**

```python
# The ONE grounding algorithm. `GraphSink.mention` and `FieldGrounding` both call it.
def ground(block_text: str, quote: str) -> tuple[int, int, int] | None:
    """-> (ts_a, ts_b, occurrences) in BLOCK.TEXT coordinates, or None when the quote is absent.

    `ts_a`/`ts_b` are half-open offsets into `block_text` such that `block_text[ts_a:ts_b]` is the
    slice (07 §9.2). The offsets come back through `normalize_k`'s back-map; they are NEVER the
    offsets `.find()` returned, which live in normalised space.
    """
    hay, back = normalize_k(block_text)
    needle, _ = normalize_k(quote)
    if not needle:
        return None                       # an empty quote is OW_GRAPH_UNGROUNDED, never a match
    # The counting loop `.find()` cannot provide. Overlapping occurrences are counted; the FIRST
    # is the one grounded, which is 06 §1.7's stated rule.
    hits: list[int] = []
    i = hay.find(needle)
    while i != -1:
        hits.append(i)
        i = hay.find(needle, i + 1)
    if not hits:
        return None
    i0 = hits[0]
    ts_a = back[i0]
    end = i0 + len(needle)
    # `back` has len(hay) entries, so the half-open end maps through back[end] when end < len(hay)
    # and through len(block_text) when the match runs to the end of the normalised string.
    ts_b = back[end] if end < len(hay) else len(block_text)
    return ts_a, ts_b, len(hits)
```

**Canonical property test (P-GROUND).** Paste verbatim into 06 §11's property table.

> **P-GROUND** — for every `(block_text, quote)` in the grounding fixture set, `ground()` returns a
> triple and `normalize_k(block_text[ts_a:ts_b])[0] == normalize_k(quote)[0]`. The fixture set
> covers, one case each and each with a **different** length delta: a ligature (U+FB01), a double
> space, a leading space, a category-`Cf` character (U+200B), a casefold-expanding letter (U+00DF),
> and a soft hyphen across a line break. Six fixtures, and the suite fails if the set has fewer.

**Canonical replacement for `06`:433-435's `MentionDraft` comment. Paste verbatim.**

```python
    # A `quote` form is GROUNDED by the sink through `ground()` (below): the offsets come back
    #   through normalize_k's back-map, in block.text coordinates. NEVER .find()'s own offsets.
    #   not found  -> quarantine OW_GRAPH_UNGROUNDED, the draft KEPT verbatim
    #   found > 1x -> the FIRST occurrence, plus Diag(OW_GRAPH_QUOTE_AMBIGUOUS) carrying the count
```

**Canonical statement of what the count is for.** `occurrences > 1` grounds the **first** occurrence
and emits `Diag(OW_GRAPH_QUOTE_AMBIGUOUS)` carrying the count. `None` quarantines
`OW_GRAPH_UNGROUNDED` with the draft **kept verbatim**.

**Sites.** `06`:433's `MentionDraft` comment, `06`:533's `OW_GRAPH_UNGROUNDED` row, `06`:1970's
layer-2 row (all C4). `07` §9.2 gains one sentence naming `ground()` as the only producer of a
`mention` row's `ts_a`/`ts_b` (C5-1). No CHECK constraint is added: the predicate needs `normalize_k`
and SQLite cannot call it.

### D4 — the `structural` channel traverses `block_link` **only**

**Question.** Six documents were said to disagree about what `structural` traverses.

**Verified, site by site.**

| site | what it says now | verdict |
|---|---|---|
| `07`:1181 | "a bounded frontier BFS over `block_link`" | **correct, this is the canonical wording** |
| `16`:690 | "the structural channel traverses `block_link` only" | correct, leave |
| `18`:2756-2757 | "Entity-level traversal is `edge`. Block-level traversal is `block_link`." | correct, leave |
| `18`:2764-2765 | "Block-level structural traversal runs through `query`, not through the graph view" | correct, leave |
| `02`:117 | "expand.py BFS over block_link / edge" | **wrong — out of cluster, report** |
| `README`:243-244 | "`structural` traverses L3's `block_link`/`edge`" | **wrong — out of cluster, report** |
| `03` | no claim about the `structural` Channel exists in `03` | **did not reproduce** — see §12 |

**Resolution.** The canonical sentence, for any document that needs to state it:

> The `structural` Channel traverses `block_link` **only**. `edge` is L3's entity→entity table and is
> reachable through `GraphView.neighbours()`, which is outside `retrieve()` and carries no budget,
> weight, ceiling contribution or `Verdict`. Two traversals, two names, and mixing them is a
> terminology-lock violation.

**The roadmap commitment stays.** `16`:765's W8.9 ("the structural channel's L3 half", P8, 4 units)
is **not** deleted: it is the scheduled work that will change `07`'s specification, and deleting it
would put `07` in conflict with the roadmap. `07` §5's `structural` paragraph gains one sentence
naming W8.9 as the item that widens it, so the two documents agree about the present *and* the plan
(C5-2). No cluster edits `02` or `README`.

### D5 — `Expand.relations` examples must name `relation_vocab` members

**Question.** `block_link.relation` is `NOT NULL REFERENCES relation_vocab(relation)` (`07`:530), and
`relation_vocab` holds thirteen builtin L3 relations (`06`:293: `refers_to`, `cites`, `defines`,
`part_of`, `member_of`, `party_to`, `supersedes`, `amends`, `located_in`, `attributed_to`,
`depends_on`, `co_occurs_with`, `related_to`). Three worked examples pass L2 `RelKind` members
instead — `anchor_ref`, `note_ref`, `continues` — which the FK rejects, so the rows they traverse
cannot exist.

**Verified.** `07`:1656, `07`:1690, `18`:2768. All three reproduce.

**Resolution.** Every `Expand.relations` example uses `relation_vocab` members. The canonical
replacement set is `frozenset({"refers_to", "cites", "part_of"})`. The `RelKind` seven stay where
they belong: on L2's `rel` table, which `structural` does not traverse.

Assigned: `07`:1656 and `07`:1690 → C5-3; `18`:2768 → C8-2. Each side changes its own example and
nothing else, because the two are independent traces.

### D6 — `Corpus.doc` is `@stable`

**Question.** Three documents answer three ways: `18`:494 marks it `@provisional`; `10` §9.4 omits it
from **both** lists; `11`:1043 makes removing an SDK attribute a `RELEASE` MAJOR with no
`@provisional` carve-out. The evaluation identifies this as the real deadline for the adapter
decision, because every recommended adapter's fidelity claim runs through it.

**Resolution.** **`Corpus.doc` is `@stable`.** Reason, stated so it is not re-argued: `Corpus.doc` is
the only escape hatch from the answer surface into the document model, and the framework's central
thesis is that structure survives the crossing. A `@provisional` escape hatch is a promise that the
thesis is not yet promised, and it makes every adapter that reads `CellPos`, `OriginSpan`, `marks` or
a `SpanMap` churn on a MINOR. The signature is `doc(self, ref: str) -> Doc` and `Doc` is a lazy
handle by contract (`11`:1043 already says so), so the stable surface is one method returning one
handle — the volatile part is `Doc`'s accessor set, which `03` owns and which is T-SCHEMA (`02`:210:
a `SCHEMA` major with a two-release deprecation window).

Assigned: `18`:494 drops the `# @provisional` marker (C8-3); `10` §9.4's `@stable` block gains
`Corpus.doc` (C8-4); `11`:1043 gains D8's carve-out (C7-8).

### D7 — `RenderedBlock`'s five unclassified fields are all `@stable`

**Question.** `18`:591-630's dataclass has 26 fields. `10` §9.4 classifies 10 as `@stable` and 4 as
`@provisional`; `18`:631-638 adds 4 more provisional (`block_id`, `kind`, `layer`, `is_context`) and
3 more stable (`span`, `superseded_by`, `retired_at_gen`). That leaves **exactly five unclassified**:
`doc_uri`, `quad`, `score`, `score_kind`, `defanged`. `18`:635 also says "eleven `@stable` fields",
which does not match its own arithmetic.

**Resolution.** All five are `@stable`, with the reason for each:

| field | why `@stable` |
|---|---|
| `doc_uri` | the document identity a caller needs to open the source; there is no other route to it from an Answer |
| `quad` | INV-9's never-synthesized polygon; it is the provenance claim the plan is built on |
| `score` | one half of a CHECK-constrained pair, and the input to every confidence figure a caller can reproduce |
| `score_kind` | the other half. "0.7 on an unnamed scale" is not a measurement, so the pair is stable or neither is |
| `defanged` | `18`:627-628 already says a droppable safety disclosure is not one. `@provisional` is droppable on a MINOR |

**Resulting arithmetic, which both documents must print identically:** **eighteen `@stable`** fields
(`cite`, `addr`, `doc_uri`, `page`, `text`, `span`, `quad`, `quote`, `trust`, `method`,
`origin_driver`, `byte_exact`, `score`, `score_kind`, `restriction_bits`, `defanged`,
`superseded_by`, `retired_at_gen`) and **eight `@provisional`** (`block_id`, `kind`, `layer`,
`identity_grade`, `channel_contributions`, `channel_ranks`, `segment_id`, `is_context`). 18 + 8 = 26,
which is every field.

Assigned: `10` §9.4 (C8-4) and `18`:631-638 (C8-5). Both in one cluster, so there is no side to invert.

### D8 — `11`:1043's SDK rule versus `10` §9.4's `@provisional` tier: **`11` changes**

**Question.** `11`:1043's SDK row makes "removing a method or an attribute" a `RELEASE` MAJOR with no
exception; `10` §9.4 says a `@provisional` symbol may change on a MINOR. The same question, answered
two ways.

**Resolution.** `10` §9.4 is the source of record for **per-symbol** stability; `11` §6 is the source
of record for **surface** versioning. A surface rule that does not name the exception its own
per-symbol tier creates is the error, so **`11`:1043 changes** and `10` §9.4 stands.

**Canonical replacement for `11`:1043's "breaking" cell. Paste verbatim.**

> removing a method or an attribute that [interfaces](../10-interfaces.md) §9.4 classifies `@stable`;
> changing a parameter's type or making one required; returning a list where an iterator was returned
> (or the reverse — `Doc` is a lazy handle by contract). **A `@provisional` symbol is the one
> carve-out:** it may be changed or removed on a `RELEASE` MINOR with a changelog entry and a
> one-MINOR deprecation shim, and an `@internal` symbol carries no promise at all — §9.4 owns which
> symbol is which, and `omniweave/sdk/_generated.pyi` is byte-diff gated so the tier is checked in
> the same PR as the change.

### D9 — `cache_index`: **retract** the cross-store reuse claim

**Question.** `cache_index` is created by `0004_runtime.sql` **inside** the store (`07`:240), and
`08`:2394 already says so ("`cache_index` is a store table, so it moves with the store"). Several
sites nevertheless advertise the `call` layer as surviving a move to a second store, and it is
load-bearing for the plan's headline cost argument.

**Verified.** `08`:1123 (the `CacheLayer` table's `call` row), `08`:1132 (§4.1's justification
paragraph), `12`:782 (§5.4's opening), `12`:1279-1284 (§6.6's "single most consequential number"),
`terminology.md`:152 ("Call cache" row). Five sites, all reproduce.

**Resolution: retract, do not fix.** A machine-scoped cache sidecar under `roots.cache` is 2-3
engineer-weeks and needs its own GC, its own price-book replay and its own `--allow-rebill` story —
it is a **new mechanism**, which this stage does not add. A retraction stated clearly beats a fix
stated vaguely, and the honest claim is still a large one.

**Canonical retraction paragraph. Paste verbatim wherever the claim is made.**

> **The `call` layer does not survive a move to a second store.** `cache_index` is created by
> `0004_runtime.sql` **inside** the `.owstore`, so a fresh store opens with an empty cache and every
> `billed_api` response is billed again. What the layer does buy, all of it inside one store: a
> re-parse at a new `producer.schema_version`; a `digest_recipe` bump re-derived as a re-digest pass
> rather than a re-parse; an `ow index rebuild --derived`; and a re-run after a metadata-only touch
> that leaves `unit.content_sha256` unchanged. On the 100k reference corpus that is 116,400 pages ×
> 853.4 micros ≈ **$99 not re-billed per re-derivation**. A machine-scoped cache sidecar under
> `roots.cache` that would make the claim true across stores is **deferred and unfunded** — 2-3
> engineer-weeks, its own GC and its own `--allow-rebill` path — and no plan document may assume it.

**Canonical one-line form**, for a table cell that cannot hold a paragraph:

> the layer that makes a re-derivation of a corpus **within one store** cost CPU-seconds instead of a
> re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` lives in the store.

Assigned: `08`:1123 and `08`:1132 → C5-4; `12`:782 and `12`:1279-1284 → C6-1;
`terminology.md`:152 → C1-9.

### D10 — `decode.text-native`'s `terminal = true` stands; the publish path changes

**Question.** `05`:1338-1341's `decode.text-native` names `driver = "parse.text.builtin"` with
`terminal = true` for ten tokens including `ipynb`. `04` §9 Step 5's transcript shows
`parse.notebook.ipynb` winning `resolve()` for exactly that format. A conformant, attested, enabled,
lockfile-pinned third-party driver for a format **inside** the 48 cannot win.

**Resolution.** `terminal = true` **stands**: it is what stops the router falling through to a paid
rung, and removing it would make every text format reachable by escalation. What is missing is the
publish path, so the fix is a documentation-and-scaffolding fix, not a routing change.

**Canonical statement, for both documents.**

> `terminal = true` ends rule evaluation at that rung; it does not make the named driver
> unreplaceable. For a format **inside** the 48, a third-party driver becomes reachable when the
> operator prepends a rule that pre-empts the builtin one — layers **prepend** and first match wins
> (`05` §4.1), so a `project`-layer rule naming the same `unit.format` set wins with no precedence
> arithmetic. `ow drivers scaffold` emits that fragment as publish **step 8**, and
> `ow drivers add --enable` prints the exact path it must be copied to; INV-5 keeps the operator in
> the loop, because enabling a driver and redirecting a route are two decisions and the second is the
> one that can move money.

**Canonical step 8. Paste verbatim into `04` §9 as `### Step 8`.**

```console
$ ow drivers scaffold --policy parse.notebook.ipynb
wrote  policy.d/50-parse-notebook-ipynb.toml   (layer: project)

# policy.d/50-parse-notebook-ipynb.toml
surface        = "route"
policy_name    = "driver:parse.notebook.ipynb"
policy_version = 1
schema         = "omniweave.policy/1"

[[rule]]
id      = "decode.notebook-ipynb"
rung    = "DECODE"
comment = "Pre-empts builtin decode.text-native for ipynb. Prepended, so first match wins."
when = { "unit.format" = { in = ["ipynb"] } }
then = { driver = "parse.notebook.ipynb", terminal = true }

$ cp policy.d/50-parse-notebook-ipynb.toml .omniweave/policy.d/
$ ow route lint && ow route explain notebooks/analysis.ipynb --rung decode
DECODE  decode.notebook-ipynb (project)  ->  parse.notebook.ipynb   terminal
        pre-empted: decode.text-native (builtin)
```

**Step 5's transcript is corrected** to show the pre-emption rather than a bare `resolve()` win
(C2-6): before the fragment is installed the dry run resolves to `parse.text.builtin` through
`decode.text-native`, and the transcript says so and names step 8.

### D11 — **no** seventh read-only `driver` policy layer

**Question.** The evaluation offers a seventh `driver` layer ranked below `builtin` as an alternative
to the eighth publish step.

**Resolution: do not add it.** Three reasons, recorded so the next reader does not re-derive them:

1. Ranked **below** `builtin`, it cannot pre-empt `decode.text-native` — which is the case that
   motivated it. Ranked **above** `builtin`, a wheel could silently redirect money, which no version
   of this framework permits.
2. `[[pin]]`'s typed `PinRejected{driver, reason}` already gives a driver author a per-unit
   demonstration path with five named reasons (`05` §4.1), so the "prove my driver would have won"
   need is already served.
3. INV-5's premise is that enabling a driver is an operator's decision. A driver-owned policy layer
   makes the *route* a driver's decision, which is a different and worse thing.

**Canonical sentence, appended to `05` §4.1's six-layer table** (C3-10):

> **Six layers, and there is deliberately no seventh.** A `driver` layer was considered and refused:
> below `builtin` it cannot pre-empt a builtin `DECODE` rule and therefore does not solve the case
> that motivates it, above `builtin` it would let an installed wheel redirect spend, and `[[pin]]`'s
> typed `PinRejected` already gives a driver author a per-unit demonstration path. A third party's
> route lands through publish step 8's `project`-layer fragment
> ([drivers](../04-driver-system.md) §9) and through an operator's copy of it.

### D12 — `empty_result`: `05` §6.5's table changes, `08` stands

**Question.** `08`:240-241 says the runner converts an `ok` result failing `is_valid_nonempty()` into
`FAILED_PERMANENT{EMPTY_RESULT}` before anything is cached. `05` §6.5's `spill_to_free` row says the
part ends `ok_partial, degraded = 1`. On a scanned page those disagree.

**Note on the citation.** The evaluation cites "`08` §9", which is the distributed-backend section.
The actual locus is `08`:240-241 (§1.6's no-empty-success rule) and `08`:428's failure table. The
substantive contradiction reproduces; only the section number was wrong.

**Resolution.** `08` is right and stands. `05` §6.5's row overstates: `spill_to_free` is an
*attempt*, and an attempt that yields zero blocks is `FAILED_PERMANENT{EMPTY_RESULT}`, after which
`on_exhausted` advances to its next member. `05` §10.3's own trace at :2620-2626 already gets this
right, which is the internal evidence that §6.5's table is the error.

**Canonical replacement for `05` §6.5's `spill_to_free` row. Paste verbatim.**

> | `spill_to_free` | re-evaluate at `DEGRADE` with `max_cost_class = "free"`. In the shipped policy that is `degrade.budget-exhausted` → `parse.pdf.pdfium`. | `ok_partial`, `degraded = 1`, `page.method` records the branch — **when the free driver produces blocks.** A free attempt returning zero blocks is `FAILED_PERMANENT{EMPTY_RESULT}` before anything is cached ([runtime](../08-runtime.md) §1.6), and `on_exhausted` advances to its next member; §10.3's part 6 is exactly that path. |

Assigned: C3-6 only. `08` is not edited.

### D13 — `micros_per_part` and `micros_max`, with the arithmetic

**Question.** `[budget.per_unit] micros_per_part = 800` (`05`:1175) sits below
`parse.page.olmocr`'s own `est_micros = 854` and far below its `reserved_micros = 2,732`
(`05`:2417-2418), so on a fully-escalating document the per-unit cap grows more slowly than the
spend. `micros_max = 250_000` caps payable escalation at 293 pages.

**Resolution — the new values.**

```toml
[budget.per_unit]                    # base + per_part x part_count, clamped. NO EXPRESSIONS.
micros_base     = 4_000
micros_per_part = 3_000
micros_max      = 16_000_000
```

**The arithmetic, which every document that prints these numbers must be able to reproduce.**

```text
cap(P)          = clamp(micros_base + micros_per_part x P, 0, micros_max)
est_micros      = 854      (parse.page.olmocr, declared p50, 05 §10)
reserved_micros = 2_732    (p95 on gpu_ms at tokens_out_p95_multiple = 3.2)

Why micros_per_part must exceed reserved_micros and not merely est_micros:
  admit() reserves reserved_micros per part BEFORE the part runs, and up to max_workers parts of
  one unit hold reservations concurrently. A cap that grows at est_micros per part covers the
  settled spend but not the outstanding reservations, so a wide unit denies parts it can afford.
  micros_per_part >= reserved_micros makes every part carry its own worst case, at any concurrency.

  3,000 >= 2,732, with 9.8% margin, and 3,000 is 3.5x est_micros.

Consequences, all payable, none degraded on a fresh budget:
  188-page 10-K  cap = 4,000 + 3,000 x   188 =      568,000   spend   188 x 853.4 =   160,439
  1,000-page     cap = 4,000 + 3,000 x 1,000 =    3,004,000   spend 1,000 x 853.4 =   853,400
  5,000-page     cap = 4,000 + 3,000 x 5,000 =   15,004,000   spend 5,000 x 853.4 = 4,267,000

Why micros_max = 16,000,000:
  it must not bind before the largest document the framework prices, which is the 5,000-page PDF
  of `rss.gen5000p_peak_bytes` (F1, 12 section 4.3): 15,004,000 rounded up to 16,000,000 gives the
  clamp a reach of P = (16,000,000 - 4,000) / 3,000 = 5,332 parts. Above that the clamp is a
  runaway guard on a pathological part count, never a routine denial, and the worst payable spend
  inside it (5,332 x 853.4 = 4,550,329) is 3.5x below the ceiling.
```

**`05` §10.3's worked trace is preserved byte-for-byte by one added setup line.** With the new
defaults a 6-part invoice never exhausts, so the trace that demonstrates "reservation denial is not
exhaustion" needs a tighter budget than the shipped default. It gets one, from the layer that is
allowed to set one.

**Canonical setup line. Paste verbatim into `05` §10.3's opening, before the existing
`clamp(4000 + 800x6, …)` sentence.**

> The corpus carries a **`site`-layer** `[budget.per_unit]` override — `micros_base = 4_000`,
> `micros_per_part = 800`, `micros_max = 12_000` — an operator's deliberately tight budget on an
> invoice corpus. Every number below is under that override, not under the shipped default of §4.4,
> and that is the point: the mechanism this trace demonstrates is reachable whenever an operator
> lowers a budget, which §4.1 permits at `site` and at `project`.

Every other number in §10.3 (`8,800`, the 2,000 pre-spent, `6,270/8,800`, `--allow-cost 12000`) then
stands exactly as printed. `05`:2144-2148's `micros_per_part` message example gains the same
one-clause attribution.

**Canonical replacement for `12` §5.1's "and the alternative ALSO degrades" block. Paste verbatim.**

```text
and the alternative is payable under the shipped default, so the 13.4x is the whole argument:
  [budget.per_unit] micros = clamp(micros_base + micros_per_part x parts, 0, micros_max)
                          = clamp(4,000 + 3,000 x 188, 0, 16,000,000)
                          = 568,000 micros
  161,304 < 568,000, so a document-level OCR boolean would have been paid in full — it is
  simply 13.4x more expensive. The pre-S10 default (micros_per_part = 800, micros_max =
  250,000) made 154,400 bind at part 181 of 188, which was a defect and not an argument:
  see 05 section 4.4 and route lint check 13.
```

The "858 micros and 853.4 micros are two different numbers" paragraph below it stays exactly as
written.

**Sites, all assigned.** `05`:1174-1176 the shipped block; `05`:2432 §10.1's
`clamp(4000 + 800x188, 0, 250000) = 154,400` recomputes to
`clamp(4000 + 3000x188, 0, 16000000) = 568,000`; `05` §10.3's setup line; `05`:2144-2148's clause →
all C3-7. `12`:705-712 → C6-2. `15`:972-973, `15`:1587-1588 and `charter.md`:2603-2605 are out of
cluster — report (§11).

### D14 — `ow route lint` check 13

**Resolution.** `ow route lint`'s twelve checks (`05`:1655-1667) gain a thirteenth. None of the
twelve compares a budget dimension against any driver's declared cost.

**Canonical row. Paste verbatim as row 13 of that table.**

> | 13 | for every enabled driver a `PAGE`- or `REGEN`-rung rule can select, `[budget.per_unit] micros_per_part >= card.reserved_micros` and `[budget.per_part] micros >= card.reserved_micros` — a per-unit cap that grows more slowly than the reservation denies parts the operator can afford, and it is the shipped default that had this defect | `OW-P-021` |

Assigned: C3-8.

### D15 — `1 − Cover` becomes the billed share

**Question.** `06` §2.4 states in bold that billed share "is **not** `1 - covered_frac`, because the
gate is per-Segment and a Segment at 0.59 is billed entire", and prints weighted covered 0.476
against weighted billed share 0.564. `12` §6.3-6.5 uses exactly `1−0.55`, `1−0.25` and `1−0.50`.

**Verified.** `12`:1180-1181 (corpus A: "45% … free Cover assumed 0.55 median"), `12`:1225-1226
(corpus B: "75% … assumed 0.25"), `12`:1256 (corpus C: "50%"). All three reproduce.

**Resolution.** Each corpus takes its billed share from `06` §2.4's table row that matches its
composition, never from `1 − covered_frac`. The mapping and the recomputation, in full:

```text
corpus A  born-digital reports  -> 06 2.4 "10-K / annual report"          covered 0.57  billed 0.48
corpus B  scanned archives      -> 06 2.4 "scanned correspondence (OCR)"  covered 0.10  billed 0.92
corpus C  mixed enterprise      -> 06 2.4's weighted reference mix        covered 0.48  billed 0.56

A  billed  0.48 x 54,000 = 25,920 segments   (was 24,300, +6.7%)
   tokens_in   25,920 x 2,000 x 0.10 = 5,184,000 micros = $5.18
   tokens_out  25,920 x   600 x 0.20 = 3,110,400 micros = $3.11
   embeddings  unchanged                 115,214 micros = $0.12
   C3 TOTAL = C2 $2.89 + 5.18 + 3.11 + 0.12                        = $11.30   (was $10.79)

B  billed  0.92 x 16,000 = 14,720 segments   (was 12,000, +22.7%)
   tokens_in   14,720 x 2,000 x 0.10 = 2,944,000 micros = $2.94
   tokens_out  14,720 x   600 x 0.20 = 1,766,400 micros = $1.77
   embeddings  unchanged                  34,138 micros = $0.03
   C3 TOTAL = C2 $7.03 + 2.94 + 1.77 + 0.03                        = $11.77   (was $10.90)

C  billed  0.56 x 35,400 = 19,824 segments   (was 17,700, +12.0%)
   tokens_in   19,824 x 2,000 x 0.10 = 3,964,800 micros = $3.96
   tokens_out  19,824 x   600 x 0.20 = 2,378,880 micros = $2.38
   embeddings  unchanged                  75,530 micros = $0.08
   C3 TOTAL = C2 $1.02 + 3.96 + 2.38 + 0.08                        =  $7.44   (was $6.74)
```

**Canonical annotation line, to replace each `(free Cover assumed …)` parenthetical.** Paste with the
corpus's own numbers substituted:

> `(billed share 0.48 from [06](../06-structure-extraction.md) §2.4's "10-K / annual report" row — the
> gate is per-Segment, so this is NOT 1 − covered_frac and a Segment at 0.59 is billed entire)`

**Canonical sentence for `12` §6.8's honesty clauses**, appended as a sixth clause:

> **Sixth: the billed share is read from a table, not computed from coverage.** Every C3 row above
> takes its billed share from [06](../06-structure-extraction.md) §2.4's per-class column.
> `1 − covered_frac` under-counts by 7-23% on the billed segment count and 5-11% on the C3 total,
> because the `llm_coverage_floor` gate is per-Segment and a Segment at 0.59 is billed entire. An
> earlier revision of this section made exactly that substitution, and §6.2 says what a cost model
> that errs cheap does.

`12` §6.6's summary table takes the three new C3 figures. `06` §2.4 is **correct and is not edited**.
Assigned: C6-3.

### D16 — F1's "5M rather than 50M": **dropped**, and replaced by the two-variable statement

**Question.** The figure is derived nowhere and is carried into nine sites. The adversarial verifier
established the deeper error: T2's ceiling is stated **in blocks** (10M-50M), and `blocks/page` does
not move a block-denominated quantity — `bytes/block` does, and it moves storage rather than the
ceiling.

**Resolution: drop it.** It is unsourced *and* wrong in kind. It is replaced by a statement of F1's
two variables and what each actually moves.

**Canonical replacement paragraph. Paste verbatim at `07`:2530-2533.**

> Every number in that sentence carries F1's envelope, and **F1 is two variables that move different
> quantities.** `blocks/page` moves the **page equivalence only**: at ~300 blocks/page the same
> ~10M-block ceiling is ~33,000 pages rather than ~110,000. `bytes/block` moves storage, peak RSS and
> `VEC_BRUTE_MAX`'s block equivalence, which is derived at 140 B/block. **Neither moves the 10M-50M
> block ceiling itself**, because that ceiling is denominated in blocks and set by the lexical
> Channel's 50 ms budget on a merged index (§12.4 item 4). `store.bytes_per_block` is the nightly
> ratchet that tells us before a user does.

**Canonical replacement for an F1 fallback cell** (a table cell that cannot hold a paragraph):

> the page equivalence in `07` §12.5 falls from ~110,000 to ~33,000 pages, and every storage, frame
> and RSS projection moves with `bytes/block`. The 10M-50M **block** ceiling is unchanged: it is
> denominated in blocks and set by `07` §12.4 item 4.

**Sites in a cluster.** `07`:2532 (the §12.5 paragraph, C5-5), `07`:2822 (the F1 open-question row's
fallback cell, C5-5), `16`:1098 (DP8's fallback cell, C7-4). **Out of cluster, reported not edited:**
`02`:1367, `17`:188, `17`:424, `README`:359, `00`:747, `charter.md`:8588.

`02`:1367 additionally lists the 600 MB supervisor RSS gate as an F1 dependent while `12` §4.2 rule 1
states that ceiling is independent of document size — the one genuinely inert entry. Reported, not
edited.

### D17 — framework adapters and `omniweave-docling`

**Question.** Zero of the eight orchestration frameworks except LangChain (2 occurrences) and
LlamaIndex (1) is named in 42,655 lines, no distribution exists among the fourteen, no roadmap item
mentions one, and `grep -rn "omniweave-docling" _plan/*.md` returns zero while `charter.md`:905
commits to it.

**Verified.** All of it. `11` §1.2 is "the fourteen distributions" with fourteen rows; `16` §§4-13 has
no adapter item; `charter.md`:905 commits to `omniweave-docling` as "a separately versioned two-way
adapter behind an extra with a published fidelity matrix".

**Resolution, three parts.**

**(a) They are attachment distributions, outside the fourteen and outside `first_party.toml`.**
`11` §1.2's fourteen are `RELEASE`-versioned wheels; an adapter tracks a third party's minors and a
docling adapter tracks two `docling-core` minors, so both are **separately versioned**, exactly as
`charter.md`:905 already says and exactly as `omniweave-ports`' Port-major versioning precedes. This
keeps `11`'s checked counts intact — "fourteen distributions", "thirteen of the fourteen",
`first_party.toml`'s 13 rows, the 26 non-core files — and still writes the commitment down.

**Canonical block. Paste verbatim into `11` §1.2, after its closing prose.**

> **The attachment distributions, separately versioned and outside the fourteen.** Five wheels exist
> to attach omniweave to somebody else's type system. None is `RELEASE`-versioned, none appears in
> `first_party.toml`, and none is in the 250 MB aggregate gate, because each tracks a third party's
> minor series rather than omniweave's — which is the same reason `omniweave-ports` is versioned by
> Port major (§6.2). Each declares `["omniweave_ports"]` in `tools/layers.toml` unless it declares
> `compile`, in which case it declares `["omniweave_core","omniweave_ports"]`; that is the shape of
> `omniweave-target-pptx` and it is why one distribution can hold both halves of a two-way adapter.
>
> | dist | import package | what it ships | deps | tier | scheduled |
> |---|---|---|---|---|---|
> | `omniweave-langchain` | `omniweave_langchain` | `OmniweaveLoader(BaseLoader)`, `OmniweaveBlobParser`, `OmniweaveRetriever`, `create_omniweave_tool(...) -> StructuredTool(response_format="content_and_artifact")`, `OmniweaveMiddleware(AgentMiddleware)` | core, ports, `langchain-core` | T-PUBLIC | [16](../16-roadmap.md) W10.10 |
> | `omniweave-haystack` | `omniweave_haystack` | `OwDocument(Document)`, `OmniweaveConverter`, `OmniweaveRetriever`, `OmniweaveOpener`, a second `@component.output_types(blocks=list[OwBlock])` socket | core, ports, `haystack-ai` | T-PUBLIC | [16](../16-roadmap.md) §18 |
> | `omniweave-llamaindex` | `omniweave_llamaindex` | `OmniweaveReader(BasePydanticReader)`, `OmniweaveSegmenter(TransformComponent)`, `OmniweaveRetriever`, the L2→`NodeRelationship` mapping | core, ports, `llama-index-core` | T-PUBLIC | [16](../16-roadmap.md) §18 |
> | `omniweave-adk` | `omniweave_adk` | `OmniweaveArtifactService(BaseArtifactService)` (7 methods), `omniweave_process_artifact`, `OmniweaveToolset(BaseToolset)` | core, ports, `google-adk` | T-PUBLIC | [16](../16-roadmap.md) §18 |
> | `omniweave-docling` | `omniweave_docling` | the two-way `DoclingDocument` adapter and the published fidelity matrix (`charter.md`:905); one `parse/1` driver in, `serialize()` out | core, ports, `docling-core` | T-PUBLIC | [16](../16-roadmap.md) §18 |
>
> Adding one is non-breaking (§6.3's packaging row). `tools/layers.toml` rows are derived from the
> entry points and never chosen, so G4 self-derives; the generated-surface registry freezes at P7
> week 42 and none of these touches it. The one irreversible step is PyPI name reservation, and it is
> taken at P1 alongside the fourteen.

**(b) `omniweave-langchain` is funded, in P10, as W10.10.** It is the only adapter that must exist
before v1.0 to test the §6.2 thesis in code: `ToolMessage.artifact` is the one lossless crossing in
any framework's own types, and it is already load-bearing in shipped first-party LangChain code. The
other three are fidelity upgrades on a path that already works, because the MCP server reaches
**seven of the eight** frameworks with zero omniweave-side code (`_index/in-04-agentic.md` §2, as
corrected by D30).

**Canonical roadmap row. Paste verbatim into `16` §13's P10 work-item table, after W10.9.**

> | W10.10 | `omniweave-langchain`: `OmniweaveLoader(BaseLoader)`, `OmniweaveBlobParser(BaseBlobParser)`, `OmniweaveRetriever(BaseRetriever)`, then `create_omniweave_tool(...) -> StructuredTool(response_format="content_and_artifact")` and `OmniweaveMiddleware(AgentMiddleware)` harvesting artifacts off `ToolMessage`s into a custom `AgentState` channel | S-retrieve | 3 | 1 ew for the three ABCs, 2 for the artifact path and middleware (`_index/in-04-agentic.md` §7 item 2). `ToolMessage.artifact: Any` is the only lossless crossing available in any framework's own types, and langchain 1.4.0's dependency on `langgraph>=1.2.11,<1.3.0` puts provenance into a durable forkable execution state at the same time. It depends on the `Corpus.doc` ruling: `@stable` ([10](../10-interfaces.md) §9.4), so the adapter's `CellPos`/`OriginSpan`/`marks`/`SpanMap` path is not on a MINOR-breakable symbol |

**The calendar arithmetic that follows, every number of it.** Block I (weeks 59-64, 5 engineers,
capacity 30) currently allocates `P9 4 · P10 20 = 24 used`, leaving the program's entire 6-ew buffer.
W10.10 takes 3 of those 6.

```text
16 section 13   P10 work items          "Total 30 ew."   ->  "Total 33 ew."
16 section 3.1  block I row, P10 cell              20    ->  23
16 section 3.1  block I row, `used`                24    ->  27
16 section 3.1  total row, P10 column              30    ->  33
16 section 3.1  total row, `used`                 360    ->  363
16 section 3.1  prose after the matrix
    "Six engineer-weeks of the 366 are unallocated, all of them in block I. That is the program's
     entire schedule buffer: 1.6%."
 -> "Three engineer-weeks of the 366 are unallocated, all of them in block I. That is the
     program's entire schedule buffer: 0.8%, and W10.10 is what the other three bought."
16 :12   "**64** and **360 engineer-weeks**"  ->  "**64** and **363 engineer-weeks**"
16 :914  "at 360 cumulative engineer-weeks"   ->  "at 363 cumulative engineer-weeks"
16 :958  "(46 + 60 = 106 of 360 ew)"          ->  "(46 + 60 = 106 of 363 ew)"
16 :1014 "are **not** inside the 360 ew"      ->  "are **not** inside the 363 ew"
```

**(c) The other four go to `16` §18, named, costed and ranked.**

**Canonical rows. Paste verbatim into `16` §18's table.**

> | Framework adapters beyond langchain — `omniweave-haystack` (2 ew), `omniweave-llamaindex` (3), `omniweave-adk` (2) | the MCP server reaches seven of the eight frameworks with **zero** omniweave-side code (`_index/in-04-agentic.md` §2), `serialize(scope, fmt) -> (str, SpanMap)` is the primitive all three need (`03` §16.1), and `11` §1.2's attachment-distribution block already fixes their layer rows and their separate versioning | that MCP is a *fidelity* path. It is an *access* path: `MCPTool.invoke` returns a JSON **string**, which escapes `10` §3.5's section layout, so haystack's adapter is the one that buys legibility rather than reach. `_index/in-04-agentic.md` §7 owns the order and the reasons four more are declined outright |
> | `omniweave-docling` — the two-way `DoclingDocument` adapter and its published fidelity matrix | `charter.md`:905's commitment, `serialize()`'s `SpanMap`, and `ow store export --portable`'s plain ZIP that `unzip -l` and `jq` both read with no external tool (`07`:2560-2566) | that the fidelity matrix has an owner. It has none, no phase and no engineer-week until this row is funded — ~1 engineer-day of prose plus the adapter itself. `omniweave-docling` appears in **zero** of the 21 plan documents today and this row is the whole of the plan's commitment |

### D18 — the 4M-cell page is **admitted**, not refused (`03`:2546 vs `03`:2566)

**Question.** `03`:2546 sets `MAX_BLOCKS_PER_PAGE = 4,194,304` "chosen so the charter's 4M-cell sheet
is admissible with 4.9% headroom", and prints the cost as a ~2.8 GB WAL and ~23 s commit against
`loop_lag_max_ms = 250` — a 92× breach. `03`:2566, twenty lines later, says the same fixture is
"refused, F29".

**Verified.** Both reproduce. `MAX_GRID_SLOTS = 4,000,000` is non-firing on the same fixture for the
same reason: 4,000,000 is not greater than 4,000,000.

**Resolution.** The page is **admitted**, at a stated cost, pending F29's spike. `03`:2566's row is
the error.

**Canonical replacement for `03`:2566's row. Paste verbatim.**

> | a 4M-cell sheet on one page | **admitted**, with 4.9% headroom under `MAX_BLOCKS_PER_PAGE` and *exactly at* `MAX_GRID_SLOTS`, which does not fire because 4,000,000 is not greater than 4,000,000. The cost is stated rather than hidden: a ~2.8 GB WAL and a ~23 s commit against `loop_lag_max_ms = 250`, a 92× breach and `17` R-T13's own detection trigger. Charter **F29** is the spike that decides whether a sub-page commit boundary is needed, and a fix must move **both** constants — the ceiling and the grid-slot cap — because a page admitted by one and unbounded by the other is the shape of the failure |

`03`:2546's row gains one clause naming :2566's row so a reader cannot read one without the other
(C1-2).

### D19 — three `owdoc-fragment` key spellings, and P24 versus `achieved`

**Question (a).** `03`:600 says "**Archive and fragment** records use short, frozen keys" and gives a
29-key table in which `t` is **text**. `04`:2073 and `18`:2016 emit fragment records with long
spelled-out keys in which `t` is the **record-type discriminator** and `text` is text. Three
spellings of one wire format.

**Resolution.** They are **two different wire formats** and `03`:600's sentence conflates them.

**Canonical replacement for `03`:600's sentence. Paste verbatim.**

> **Archive records** — the `.owdoc` container's `blocks.ndjson` — use short, frozen keys. This is
> protobuf's field-number discipline with no toolchain: a key is never reused with a different
> meaning, and CI diffs `tools/wirekeys.toml`. **`owdoc-fragment/1` is a different wire and uses
> long, spelled-out keys**, because it is authored by a third party rather than generated: its
> records are discriminated by `t ∈ {doc, part, page, block, asset, block_asset, diag}` and a
> block's text is `text`, addressed by a per-invocation `tmp` id with no `addr`, no `cite` and no
> producer index. [The driver system](../04-driver-system.md) §9 Step 3 prints the record shapes; the
> two key sets are deliberately disjoint in spelling so that a record cannot be misread as the other
> format, and `t` meaning **text** here and **type** there is the one collision that makes the rule
> worth stating.

**Question (b).** `03`:2892's property P24 ("no forged provenance") asserts the fragment "contains no
`block_id`, no `producer_id`, no `origin_operator`, no `origin_driver`, no `restriction_bits`, no
`achieved`, no currency field, and no cache-hit claim". But `04`:2073 and `18`:2016 both emit
`"achieved": _ACHIEVED` in the `doc` record, and `04`:2018-2021's `capability` suite exists precisely
to assert `achieved <= card` on every key.

**Resolution.** P24 is the error. `achieved` is not forged provenance: it is the driver's self-report
of what it delivered on *this* document, clamped by the card and re-clamped by `DocSink`, and
`byte_exact` reads it (`18`:641-645). Removing it would delete the mechanism that makes `byte_exact`
computable at all.

**Canonical replacement for `03`:2892's P24 row. Paste verbatim.**

> | P24 | no forged provenance | `sandbox` | the fragment contains no `block_id`, no `producer_id`, no `origin_operator`, no `origin_driver`, no `restriction_bits`, no currency field and no cache-hit claim. It **does** carry `achieved` on the `doc` record, and that is deliberate: `achieved` is the driver's self-report of what it delivered on *this* document, `<=` the card on every key (the `capability` suite asserts it), clamped again by `DocSink`, and the input `byte_exact` reads (`18` §5). A capability self-report is not provenance; forging provenance means naming a row, a producer or a price, and none of those is representable here |

**Question (c).** `18`:2016 emits `{"t": "doc", "format": "text/plain", …}`, but `doc.format` holds a
**format token**, not a media type (`05`:626-627).

**Resolution.** `"format": "txt"`. Assigned C8-6.

### D20 — `09`'s R3 applicability condition widens to include `patched`

**Question.** `09`:1849 states R3's condition as `fidelity ∈ {structure, passthrough}`. `09`:1944's
target table and `09`:2071 both assert R3 applies to `docx`, whose `fidelity` is `patched`.

**Verified.** Both reproduce.

**Resolution.** **R3's condition widens.** R3 is stated over the multiset of `content_digest` over
`Layer.BODY` blocks in `(page, ord)` order — a text-and-structure predicate carrying no geometry.
`patched` describes the *carrier* copy strategy (a flow layout is re-laid-out by Word), not the
recoverability of block content. Excluding `patched` excludes a target that §12.3 and the R2/R3 gate
both already require to pass it. The only exemption is `fidelity = "none"`, which is the `video`
target's, and `09`:2104 already says R3 is refused there.

**Canonical replacement for `09`:1849's condition cell. Paste verbatim.**

> `fidelity ∈ {structure, passthrough, patched}` — every value but `none`. R3 is a predicate over
> `content_digest` and carries no geometry, so a `patched` carrier that re-lays-out a flow still owes
> a second-round fixed point over its BODY blocks; `fidelity = "none"` is the one exemption, because
> a lossy encode is not idempotent and §12.4 says so.

Assigned: C7-1.

### D21 — `12` §3.1's GPU ingest wall is **19-52 h**

**Question.** `12`:338 prints "**19-77.6 h** (F7 band)" for the 100k-document GPU ingest wall while
`12`:439 prints "**19-52 h** of wall at F7's 1.5-4× band" for the same quantity. 77.6 GPU-h ÷ 1.5 =
51.7 h, so §3.1's upper bound silently sets `C_eff = 1.0`, outside F7's own declared `[1.5, 4]`.

**Resolution.** §3.4 is right. `12`:338's cell becomes:

> | ingest wall, `+ ow-gpu-1`, `parse.page.olmocr` | ~6 s | ~5 min | **19-52 h** (F7 band, `C_eff ∈ [1.5, 4]` over 77.6 GPU-h of work) | out of envelope |

Assigned: C6-4.

### D22 — `ow-bench-1` has no GPU (`12` §1 versus `11`:1525)

**Question.** `12` §1's reference-machine table gives `ow-bench-1` as "x86_64-linux, 8 cores / 16
GiB, NVMe, CPython 3.11.9, SQLite ≥ MIN_SQLITE, **no GPU**". `11`:1525's nightly row labels the same
machine "`ow-bench-1` (pinned, GPU)", and `11`:1533 then says "The nightly GPU cell is the only place
`omniweave-vision` is installed in CI".

**Resolution.** `12` §1 is the source of record for reference hardware and stands. **`11` changes:**
the existing nightly row is relabelled and a second nightly row is added for the GPU cell, so
`11`:1533's sentence has a row to refer to.

**Canonical rows. Paste verbatim, replacing `11`:1525's row.**

> | nightly | `ow-bench-1` (pinned, **no GPU** — [performance](../12-performance.md) §1) | the T4 eval suite: the twelve reducers over Tier B, calibration, the scoreboard, G22's 100k-roster scale run, the full G21 crash matrix, `rss.gen5000p_peak_bytes`, `store.bytes_per_block` as a ratchet | <= 90 min |
> | nightly | `ow-gpu-1` (pinned) | `ow bench service` and every `PAGE`-rung and GPU `embed` reference row. **This is the GPU cell**, and the only cell where `omniweave-vision` is installed | <= 45 min |

`11`:1533's sentence becomes "The nightly `ow-gpu-1` cell is the only place `omniweave-vision` is
installed in CI." Assigned: C7-7.

### D23 — `ceiling()` and `OFF(query_deadline)`

**Question.** `ceiling()` sums weights over channels whose status is `OK` **or** `EMPTY`
(`07`:1241-1243). `07` §6.4 says a Channel pre-empted by the query deadline reports
`OFF(query_deadline)`. So a runtime pre-emption **shrinks the denominator and makes the answer look
more confident** — the opposite of what the ceiling exists for. `OFF(vectors)` is an operator choice
and *should* be ceiling-exempt; `OFF(query_deadline)` is a runtime shortfall and must not be.

**Resolution.** Discriminate on the `reason` field, which `ChannelResult` already requires whenever
`status != OK`. No new status, no new mechanism.

**Canonical replacement for the formula block in `07` §5.3. Paste verbatim.**

```text
rank(c, b) is 1-BASED:  rank ∈ [1, len(c.ranked)]
score(b)   = Σ_c  _weight(c) / (k + rank(c, b))     over c.status == OK
ceiling    = Σ_c  _weight(c) / (k + 1)              over c.status in (OK, EMPTY)
                                                    OR (c.status is OFF and c.reason ==
                                                        "query_deadline")
confidence = best_score / ceiling                    low_confidence < 0.35
```

**Canonical paragraph, appended to `07` §5.3 after the "Never hardcode `1/(k+1)`" paragraph.**

> **`OFF` is two different things and only one of them is ceiling-exempt.** `OFF(vectors)` and
> `OFF(not_in_plan)` are operator choices: the Channel was never going to look, so its weight has no
> business in a denominator that measures "we looked there". `OFF(query_deadline)` is a **runtime
> shortfall** — the Channel was in the plan, the query ran out of time, and nothing looked. Exempting
> it from the ceiling shrinks the denominator and makes a *worse* answer report *higher* confidence,
> which is the exact inversion `ceiling()` exists to prevent. `ChannelResult.reason` is already
> REQUIRED whenever `status != OK`, so the discrimination costs nothing. ST6's property test gains a
> third half: **(c)** with a member at `OFF(query_deadline)`, `ceiling()` is unchanged from the
> all-ran case and `confidence` is strictly lower than it would be with that member `OK`.

`07` §6.4's block gains one clause: `OFF(query_deadline)` "— an operator-visible disclosure, not a
failure, **and it keeps its ceiling weight (§5.3)**". Assigned: C5-6.

### D24 — the hydration reservation becomes a config key, and lint check 3 reads it

**Question.** `07` §4.4 states the five per-Channel budgets "sum below the query budget **net of
hydration and the coverage scan**", and `ow route lint` check 3 (`05`:1658) refuses only a set whose
sum is `>= query_ms`. The 40 ms reservation is an implicit gap, so a `channel_ms` edit summing to 249
passes the linter and destroys it.

**Resolution.** Name the reservation. It already exists; it just has no key.

**Canonical replacement for `07` §4.4's TOML block. Paste verbatim.**

```toml
[retrieval.budget]
query_ms = 250
hydration_reserve_ms = 40        # hydration + the coverage scan. NOT a channel; NOT schedulable.
channel_ms = { identity = 15, exact = 25, lexical = 50, structural = 40, semantic = 80 }
#              15 + 25 + 50 + 40 + 80 = 210,  + 40 reserved  = 250  against  query_ms = 250
```

**Canonical sentence, replacing `07` §4.4's "`ow route lint` **refuses**" sentence.**

> `ow route lint` check 3 **refuses** a set for which
> `sum(channel_ms) + hydration_reserve_ms > query_ms`. The reservation is a key rather than an
> implicit gap because the gap is the part a reader silently spends: a `channel_ms` edit summing to
> 249 passes an arithmetic that only compares against `query_ms`, and hydration then runs past the
> gate on every query that merely used its budgets.

**Canonical replacement for `05`:1658's check-3 row.** One side only; `05` already defers to `07`.

> | 3 | `sum([retrieval.budget] channel_ms) + [retrieval.budget] hydration_reserve_ms <= query_ms` — the `retrieval` surface's check, specified in [07](../07-store-and-retrieval.md) §4.4, which owns `hydration_reserve_ms` | `OW-P-003` |

**Canonical config rows for `18`:1693 and the row above it.**

> | `retrieval.budget.hydration_reserve_ms` | int | `40` | operational | hydration plus the coverage scan. Not a Channel and not schedulable; `ow route lint` check 3 refuses `sum(channel_ms) + this > query_ms`, which is what stops a `channel_ms` edit summing to 249 from silently spending the reservation |
> | `retrieval.budget.channel_ms` | table[str,int] | `{identity=15, exact=25, lexical=50, structural=40, semantic=80}` | operational | **sums to 210, plus `hydration_reserve_ms = 40`, exactly `query_ms = 250`**. A set summing past the remainder guarantees a G10 breach and turns the honesty machinery into permanent noise; `ow route lint` check 3 refuses it |

Assigned: `07` → C5-7; `05` → C3-9; `18` → C8-7.

### D25 — 16 concurrent readers versus `max_sessions = 64`

**Question.** `12` §4.1 budgets "16 concurrent readers → **~1 GB**" and says "The cap's value is
[10](../10-interfaces.md)'s". `10`:2266 ships `[serve] max_sessions = 64` with `SESSION_LIMITS` capping
each session at 4 corpora, which is up to **256** held readers. `ow doctor` refuses on workers only
and prices no readers.

**Resolution.** `10`:2266's 64 is correct on its own terms — it is a file-descriptor argument (64 × 4
× 3 = 768 against a 1,024 soft limit) and that arithmetic holds. The **resident-memory** consequence
is `12`'s to own, and `12` §4.1's row is the one that is wrong. `12` changes; `10` gains a pointer
and nothing else.

**Canonical replacement for `12` §4.1's reader row. Paste verbatim.**

> | concurrent serve readers | **~1 GB at the budgeted 16; up to ~17.4 GB at the shipped cap** | 68 MB each (§4.1's page-cache + temp row). The **budgeted** figure is 16, which is what `ow bench query` runs and what the ~1 GB number prices. The **shipped cap** is `[serve] max_sessions = 64` × `SESSION_LIMITS`' 4 corpora per session = 256 readers ([10](../10-interfaces.md) §10), which is 256 × 68 MB ≈ 17.4 GB — a file-descriptor argument (768 of 1,024) that was never a memory argument. `ow doctor` refuses above `0.8 × RAM` on **workers** and prices no readers, so nothing catches it today. **R-Q6** ([16](../16-roadmap.md) Open questions) is the measurement, at N ∈ {1, 8, 32, 128}, and until it runs an operator raising `max_sessions` past 16 is spending unbudgeted RSS |

**Canonical sentence, appended to `10` §10 after the `max_sessions` paragraph.** A pointer, not a
restatement.

> The **memory** consequence of this cap is not priced here: 64 sessions × 4 corpora is up to 256
> held readers at 68 MB each, against [performance](../12-performance.md) §4.1's budgeted 16, and
> `ow doctor --runtime` prints the descriptor count but no RSS multiplier. `12` §4.1 owns that row
> and R-Q6 is the measurement.

Assigned: `12` → C6-5; `10` → C8-8.

### D26 — `format_tokens` as a card key, and the computed `unit.format` domain

**Question.** The 48-token `format` domain is `builtin`-provided (`05`:1704) and closed at release 1
(`05`:627), with lint checks 2 and 10 binding every rule literal to it. A conformant, attested,
enabled, lockfile-pinned `parse/1` driver's distribution therefore cannot cause its own format to be
parsed: detection yields no token, `unit.format` resolves to `'unknown'`, and
`gate.unsupported-source` (`05`:1249-1254) refuses at GATE.

**Resolution.** `[capability.parse] format_tokens` is a new card key, compared `⊇`, and
`SignalSpec.domain` for `unit.format` is computed as core's 48 ∪ the union over **enabled** cards.

**Canonical card-key row. Paste verbatim into `04`'s `[capability.parse]` table.**

> | `format_tokens` | `list[str]`, default `[]` | the format tokens this driver contributes to `unit.format`'s domain. Compared **`⊇`**, which fits `05` §2.1's safe-asymmetry rule exactly: an unrecognised set member can only make a driver look *less* capable, never more. Each token is `[a-z0-9]{1,16}`, must not collide with one of core's 48 unless the driver actually parses that format, and appears in the driver's `sniff()` output as `FormatGuess.format_token` or the `capability` suite fails |

**Canonical `SignalSpec.domain` sentence. Paste verbatim into `05` §5.1.**

> `unit.format`'s domain is **computed, not literal**: core's 48 tokens ∪ the union of
> `[capability.parse] format_tokens` over every driver in `[drivers] enabled`. The union is taken at
> policy-compile time and enters `policy_digest`, so a rule naming a driver-contributed token
> resolves under lint checks 2, 10 and 11 exactly as a builtin token does, and disabling the driver
> makes the same rule fail the linter rather than silently match nothing. `enum_val`'s `format`
> domain is seeded from the same union.

**Canonical media-type↔token mapping.** The function nobody had specified:

> `format_token_for(media_type: str) -> str | None`, in `omniweave/route/detect.py`, is a total
> lookup over core's 48-entry table ∪ the enabled cards' `format_tokens` declarations, keyed on the
> media type each `FormatGuess` carries. A media type mapping to two tokens is a card-activation
> error (`OW-D-024`) naming both drivers; a `FormatGuess` whose `format_token` is not in the union is
> dropped with `Diag(OW_DETECT_UNKNOWN_TOKEN)` naming the driver, because a token no policy can name
> is a silent non-route.

Assigned: `04` → C2-2; `05` → C3-4 and C3-5.

### D27 — `06` §3.9's two unsatisfiable Pass predicates

**Question.** `06`:1108 gives `derive.code.treesitter`'s read set as "`Kind.CODE` blocks, `doc.format`
in the grammar set". There is no source-code member in core's 48, so a `.py` file resolves to `txt`
and the predicate is unsatisfiable for every language. `06`:1109's `derive.code.manifest` reads
`pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile` and five more — all of which detect as `txt`, so
the Pass cannot distinguish them by format at all.

**Verified.** Both reproduce. The plan's own designated out-of-tree distribution is the first victim.

**Resolution, two different fixes because they are two different errors.**

1. `derive.code.treesitter`'s grammar set is `omniweave-driver-code`'s **own declared
   `format_tokens`** (D26), contributed through the `parse.code.text` driver the same distribution
   ships — a stdlib-only `parse/1` driver emitting `Kind.CODE` blocks with `origin_span = "bytes"`.
   The distribution already ships 66 MB of grammars and three licences; one more entry point is not
   a new mechanism, and without it the Pass's predicate has no producer.
2. `derive.code.manifest` keys on the **part path basename**, not on `doc.format`. A manifest is
   identified by its filename — that is what `pyproject.toml` *is* — and `part.path`'s basename is
   already available to a Pass. Keying it on format was the error.

**Canonical replacement for `06`:1108-1109's two table rows. Paste verbatim.**

> | `derive.code.treesitter` | `Kind.CODE` blocks whose `doc.format` is in **`omniweave-driver-code`'s own `[capability.parse] format_tokens`** — the distribution ships `parse.code.text`, a stdlib-only `parse/1` driver that contributes those tokens to `unit.format`'s computed domain ([05](../05-ingest-and-routing.md) §5.1) and emits `Kind.CODE` blocks with `origin_span = "bytes"`. Without a contributed token a `.py` file resolves to `txt` and this predicate is unsatisfiable, which is why the token and the grammar set are one declaration | `EntityDraft` per definition (`etype` in `function`, `class`, `method`, `module`, `type`), `EdgeDraft` for `calls`/`implements`/`imports` with `observed` at the call site, `AnchorDraft(identifier, scope='corpus')` per fully-qualified name |
> | `derive.code.manifest` | the **basename of `part.path`** in `{package.json, pyproject.toml, Cargo.toml, go.mod, pom.xml, *.csproj, Gemfile, composer.json}` — a basename match and never a format match, because a manifest is identified by its filename and all nine detect as `txt` | `EntityDraft(etype='product')` per package, `EdgeDraft(depends_on)` per requirement with the version constraint in `role`, `ClaimDraft(claim_type='attribute', predicate='version')` |

Assigned: C4-8.

### D28 — the driver is `parse.fields.lift`, not `derive.fields.lift`

**Question.** `04`:2305's licence table names `derive.fields.lift`. `05`:1509, `05`:1516, `05`:2581,
`05`:2585, `05`:2594, `18`:2685 and `18`:2698 all name `parse.fields.lift`.

**Resolution.** `parse.fields.lift`. The `fields` lane's rule sits at `rung = "PAGE"` with
`render = "glyph"` (`05`:1507-1516) — a parse rung consuming a rendered page, not a `derive` pass
reading Blocks — and `05` §3's lane table lists `fields` alongside `text` and `math`, all parse
lanes. `04`:2305 is a licence-table row, exactly the kind that goes stale.

Assigned: `04`:2305 → C2-4. Single side; `05` and `18` are not edited.

### D29 — `parse.text.builtin` joins the roster

**Question.** `04` §10.1 ships "Twenty-two drivers" and `parse.text.builtin` is not among them, yet
`decode.text-native` names it for ten format tokens and `05` Open question 2 specifies it. `17`:606
registers it as defect `05#2` with remedy "one row in `[drivers] enabled`". With the driver absent,
`driver.unavailable = true` fires and `degrade.driver-unavailable` escalates to DEGRADE for every
HTML, Markdown, XML, JSON, JSONL, notebook, TSV and SVG document.

**Resolution.** Add the row. Header count "Twenty-two" → "Twenty-three".

**Canonical row. Paste verbatim into `04` §10.1, after `parse.pdf.pdfium`.**

> | `parse.text.builtin` | `parse/1` | `omniweave-office` | stdlib only: `codecs`, `json`, `csv`, `html.parser`, `xml.etree` via `defusedxml`. Serves the ten tokens `decode.text-native` names — `html`, `xhtml`, `xml`, `md`, `txt`, `json`, `jsonl`, `ipynb`, `tsv`, `svg` — none of which anydoc's card declares | Apache-2.0 | open | first_party | subproc | free | shipped |

`05` Open question 2 closes with a pointer to that row (C3-11).

### D30 — `_index/in-04-agentic.md`'s three factual errors

**Verified in `_collections/`, not in `_index/`.**

1. **Haystack ships MCP.** `_collections/haystack/docs-website/docs/tools/mcptool.mdx` and
   `mcptoolset.mdx` document `MCPTool` and `MCPToolSet`, package name **`mcp-haystack`**, over
   Streamable HTTP, SSE and StdIO. `reference/integrations-api/mcp.md`:214 gives
   `call_tool(tool_name: str, tool_args: dict[str, Any]) -> str` and :694 gives
   `ainvoke(**kwargs: Any) -> str | dict[str, Any]`. The row's `find` receipt is wrong because it
   searched the framework repository rather than `haystack-core-integrations`.
2. **The `structuredContent` scope is stated correctly in the plan.** `10`:511: "`ow_corpora` and
   `ow_add` are small and row-shaped and **do** declare one." `in-04`:7 says "no `structuredContent`"
   without the qualifier.
3. **The arithmetic contradicts itself.** `:6` says "Four of the eight … need no omniweave-side
   code"; `:55` says "five of the eight ship an MCP client"; the §2 table lists adk, langchain,
   pydantic-ai, crewAI and llama_index as clients (5), **plus** agentcore reachable by Gateway
   configuration and langgraph reachable through langchain's `MCPAdapter`. With Haystack corrected,
   that is **six of eight shipping a client** and **seven of eight reachable with zero
   omniweave-side code**.

**Resolution.** Corrected count: **seven of eight reachable with zero omniweave-side code.**
`omniweave-haystack`'s surviving justification is **not access**: it is that `MCPTool.invoke` returns
a JSON **string**, which escapes `10` §3.5's section layout — the one client of six that **mangles**
rather than truncates. crewAI's floor truncates; haystack's stringification destroys the
`**ow:<name>**` markers a consumer greps for.

Assigned: C9-1 through C9-6.

### D31 — D9's OUT-over-MCP consequence is written down

**Question.** Ruling D9 is unambiguous in five places (`02`:595: "The OUT direction is **skills plus
CLI, never MCP**"), and the generated MCP `instructions` hands the agent a pointer instead of a
capability (`10`:848-850: "Decks, reports, video: load the `omniweave` skill; these tools do not
generate"). Skills are local files installed into an agent host and they shell out. A client reaching
omniweave over `ow serve --http` has neither. **Half the product thesis is available to zero remote
peers, and nothing in the plan writes down the consequence or its cost.**

**Resolution.** Write it down where the transport is specified, as a stated consequence and not a
hedge.

**Canonical paragraph. Paste verbatim into `10` §10, after its first paragraph.**

> **The OUT direction is unreachable over this transport, and that is a decision with a cost.**
> Ruling D9 makes OUT skills-plus-CLI and never MCP, and §3.7's generated `instructions` says so to
> the agent in seven words. A skill is a local file installed into an agent host that shells out to
> `ow`, so a peer reaching omniweave over `ow serve --http` has neither the file nor the shell: it
> can query, open, list and add, and it cannot compile. **Every remote MCP peer therefore reaches
> exactly half the product.** The consequence is stated rather than absorbed because it bounds what
> `_index/in-04-agentic.md` §2's "seven of eight with zero omniweave-side code" actually delivers —
> seven of eight for IN, zero of eight for OUT — and because the alternative was considered and
> refused: a generating MCP tool would put an unbounded, billable, filesystem-writing operation
> behind a tool call whose caller cannot see a budget, and `02` §4.3's re-ingest scenario is the
> shape of what that would cost. The seam if it is ever revisited is a `compile` Action with an
> explicit `Grant`, and no plan document may assume it exists.

Assigned: C8-9.

### D32 — the `COPYLEFT_NETWORK` conjunct on `ow serve --http`

**Question.** `14`:1621 makes `COPYLEFT_NETWORK` the bit `compute_tier` derives from
`spdx in COPYLEFT_NETWORK`, and its worked acks example turns on "internal-only deployment; section
13 not engaged, no network-served product". `ow serve --http` is precisely a network-served product,
and `10` §10 does not name the conjunct.

**Resolution.** State the conjunct at the transport.

**Canonical paragraph. Paste verbatim into `10` §10, after the two-loopback-endpoints paragraph.**

> **`ow serve --http` plus a `copyleft_network` restriction is a refusal, not a warning.** A
> `restriction_bits` value carrying `copyleft_network` is accepted for a local run under an
> acknowledged licence ([security](../14-security.md); the shipped acks example turns on
> "internal-only deployment, section 13 not engaged, no network-served product"). A **listening
> transport** engages exactly that clause, so the conjunct is checked at listener start: if any
> driver in `[drivers] enabled` computes to a tier carrying `copyleft_network`, `ow serve --http`
> refuses with `OW-A-023 / OW_SERVE_COPYLEFT_NETWORK`, names the driver, the SPDX expression and the
> `licence_sha256` the ack is bound to, and prints the two ways out — remove the driver from
> `[drivers] enabled`, or serve over `stdio`, which is not a network transport. `ow serve --stdio` is
> unaffected and `ow query` is unaffected. `ow doctor` reports the same conjunct before it is reached.

`14`'s reciprocal sentence is out of cluster — report (§11). Assigned: C8-10.

### D33 — `12` §7.1's `query` bench subject covers the block counts P-Q8 requires

**Question.** `12` §7.1's `query` row runs at "10k / 1M / 10M Blocks". `12`:1776's **P-Q8** and
`17`:679 both require 10M / 20M / 30M / 50M after an FTS5 `'merge'`, reporting the Block count at
which `lexical` first reports `UNAVAILABLE(timeout)`. **P-Q8's own instrument does not exist as
specified.**

**Resolution.** Extend the subject. Specifying the instrument is in scope; running it is not.

**Canonical replacement for `12` §7.1's `query` row. Paste verbatim.**

> | `query` | per-Channel and end-to-end p50/p95/p99 at **10k / 1M / 10M / 20M / 30M / 50M** Blocks, `vectors` off and on, each scale measured **after** an FTS5 `'merge'` so segment accumulation is not confounded with size, reporting the Block count at which `lexical` first returns `UNAVAILABLE(timeout)` | generated stores + `fixtures/store/golden-queries.jsonl` | `query.warm_p50_ms`, B26, B27; **F50**, **P-Q8** |

`12` §7.1's "Extends the charter" paragraph gains one clause naming the extension. Assigned: C6-6.

---

## 1. Terminology additions

**C1 owns `_plan/_notes/terminology.md` and adds exactly these rows, in §2's case-insensitive sort
order.** Nothing else. Every row's owning document is named, because §2's CI check 2 requires each
locked name to appear in at least one document.

| term | kind | definition to add | owning document |
|---|---|---|---|
| `Basis` | type | The **host's** classification of how a format guess was obtained: `magic \| container_identity \| content_probe \| extension \| declared \| driver_sniff`. Six members. It is **not** a `FormatGuess` field and a driver may never assert it — `driver_sniff` is the member the host stamps on a driver's contribution. Lives in `omniweave/route/detect.py`, never in `omniweave_ports`. | [05](../05-ingest-and-routing.md) §2.1 |
| `FormatGuess` | type | One detection candidate as a **driver** may state it: `(media_type, format_token, confidence, consumed_bytes)`. Four fields. A third party's `confidence` is clamped to 0.95. It carries **no `basis`** and **no `detail`** — those are the host's, on `RankedGuess`. Declared once, in `omniweave_ports`. | [04](../04-driver-system.md) §1.3 |
| `format_tokens` | column | The `[capability.parse]` card key listing the format tokens a driver contributes to `unit.format`'s **computed** domain (core's 48 ∪ the union over enabled cards). Compared **`⊇`**, the one safe asymmetry: an unrecognised member can only make a driver look less capable. | [04](../04-driver-system.md) §1.4 |
| `ground()` | fn | The **one** grounding function: `(block_text, quote) -> (ts_a, ts_b, occurrences) \| None`, in `block_text` coordinates, recovered through `normalize_k`'s back-map. It grounds the **first** occurrence and returns the count, which `.find()` alone cannot. `GraphSink.mention` and `FieldGrounding` both call it, and neither reimplements it. | [06](../06-structure-extraction.md) §1.7 |
| `RankedGuess` | type | The host-side wrapper around a `FormatGuess`: `(guess, basis, detail)`. What ranks, what enters `doc.format_evidence`, and what the detection ladder emits. Host-side because `basis` is the host's classification and `omniweave_ports`' `layers.toml` row is `[]`. | [05](../05-ingest-and-routing.md) §2.1 |
| `StreamHint` | type | What the **host** knows before any sniffer looks: `(filename, extension, declared_media_type, byte_len)`. Four fields — basename never a path, extension lower-cased **with** the dot. It carries **no `trust_class`**: a driver has no business seeing it and it is what would pull `TrustClass` across the ports boundary. A hint, never an authority. | [04](../04-driver-system.md) §1.3 |

**Two existing rows are edited, not added.**

| row | line | change |
|---|---|---|
| `normalize_k()` | 326 | Replace with: *The **grounding** normaliser, returning **`(normalized: str, back: tuple[int, ...])`** where `back[i]` is the index in the input of the character that produced `normalized[i]`. Six operations, every one of which changes length: NFKC, casefold, strip Unicode category `Cf`, fold U+00AD and U+2010..2015 to `-`, collapse whitespace runs, strip. The back-map is built **during** the transform, never by composing `str` methods afterwards — stripping characters is precisely what makes an index map necessary, and "one function, three problems" was the reasoning error that produced the `ts_a`/`ts_b` defect. Grounding always runs against the **undefanged** text; defanging a copy is what makes a ZWJ obfuscation invisible to **matching**, and the back-map is what keeps the **offset** recoverable. Two problems, two mechanisms. [06](../06-structure-extraction.md) §1.7 owns the definition.* |
| Call cache | 152 | Replace the second sentence with: *What makes a **re-derivation of a corpus within one store** cost CPU-seconds rather than a re-bill of 116,400 VLM pages. It does **not** cross stores: `cache_index` is created by `0004_runtime.sql` inside the `.owstore`, so a second store opens with an empty cache. A machine-scoped sidecar under `roots.cache` is deferred and unfunded.* |

**Two rows to leave alone.** `Grounding` (line 282) says "One `str.find` that is simultaneously the
citation, the polygon, the hallucination gate and the injection containment" — the *policy* is right
and stays; only the mechanism moves, and the `ground()` row above carries it. `RelKind` (line 409) is
correct and is what D5 restores. Do not touch either.

---

## 2. C1-docmodel — `_plan/03-document-model.md`, `_plan/_notes/terminology.md`

Baseline: `03` = 3068, `terminology.md` = 606.

| # | item | file | locus | change | must say afterwards |
|---|---|---|---|---|---|
| C1-1 | `owdoc-fragment` key spellings | `03` | §3.1, line **600** | Replace the one sentence "Archive and fragment records use **short, frozen keys**." | D19(a)'s canonical replacement paragraph, verbatim. The 29-key table below it is untouched. |
| C1-2 | 4M-cell page: admitted | `03` | §14, line **2546** (`MAX_BLOCKS_PER_PAGE` row) | Append one clause to the existing cell | …"and §14.1's hostile-input row says **admitted**, not refused, for the same fixture — F29 is the spike, not a refusal that already ships". Do not change the constant or the 4.9% / 2.8 GB / 23 s figures. |
| C1-3 | 4M-cell page: the §14.1 row | `03` | §14.1, line **2566** | Replace the row | D18's canonical replacement row, verbatim. |
| C1-4 | P24 versus `achieved` | `03` | §17, line **2892** | Replace the P24 row | D19(b)'s canonical replacement row, verbatim. |
| C1-5 | `normalize_k` back-map, reader side | `03` | §12.2, line **1369** (`bytes` branch of the `origin_span` table) | The predicate `normalize_k(part_bytes[a:a+len]) == block.text` now compares against a tuple. Change to `normalize_k(part_bytes[a:a+len])[0] == block.text` | the `[0]` is present and one clause names the reason: "`[0]` because `normalize_k` returns `(normalized, back)` ([06](../06-structure-extraction.md) §1.7); the back-map is unused on this branch and the comparison is on the string". |
| C1-6 | the same, in P5/P7 | `03` | §17, lines **2873** and **2875** | Same `[0]` correction on each `normalize_k(...)` comparison | as C1-5. `grep -n "normalize_k(" _plan/03-document-model.md` finds every site, and every one that appears inside a **comparison** takes `[0]`. Sites that only *name* the function in prose are unchanged. |
| C1-7 | §17 Q2's sibling misuse | `03` | §17, lines **2926-2937** | Leave the argument intact; append one sentence | …"The sibling defect in `GraphSink.mention` — the same function misused for an **offset** rather than a comparison — is closed by [06](../06-structure-extraction.md) §1.7's back-map and `ground()`; this document's `bytes`-branch question is unchanged by it." Do **not** re-open or re-decide Q2. |
| C1-8 | INV-10 `NORMALIZED` prose | `03` | lines **1566**, **2926-2934**, **2957** | `[0]` correction where the expression is a comparison; leave the prose meaning alone | as C1-5. |
| C1-9 | terminology lock | `_notes/terminology.md` | §2 | Add the six rows of §1 in sort order; edit the two rows of §1's second table | exactly §1. No other row moves. Re-check §2's own CI rules: every added name appears in at least one document (the owning-document column names it), and none is a §3 left-column entry. |

**Do not** add `structural`-Channel prose to `03`: the finding did not reproduce there (§12).

---

## 3. C2-drivers — `_plan/04-driver-system.md`

Baseline: 2514.

| # | item | locus | change | must say afterwards |
|---|---|---|---|---|
| C2-1 | `StreamHint` / `FormatGuess` (blocking 1) | §1.3, lines **207-213** | Replace both dataclasses | D1's canonical ports block, verbatim, including both comment lines that state what is absent and why. |
| C2-2 | `format_tokens` card key | §1.4's `[capability.parse]` table | Add one row | D26's canonical card-key row, verbatim. |
| C2-3 | ports inventory | lines **2409-2410** | Verify `FormatGuess` and `StreamHint` are still listed and that `Basis`/`RankedGuess` are **not** | unchanged. Host-side types may not appear in an `omniweave_ports` inventory. |
| C2-4 | `derive.fields.lift` → `parse.fields.lift` | line **2305** | Change the driver id in the first cell | `parse.fields.lift`. Per D28, `05` and `18` are not edited. |
| C2-5 | `parse.text.builtin` joins the roster | §10.1, line **2212** header and the table | "Twenty-two drivers" → "Twenty-three drivers"; add D29's canonical row after `parse.pdf.pdfium` | the header count and the row count agree at 23. |
| C2-6 | §9 Step 5's transcript | §9, lines **2157-2188** | The `ow parse --dry-run` block shows `parse.notebook.ipynb` winning `resolve()`. Insert, immediately above it, the fact that `decode.text-native` claims `ipynb` first, and show the pre-empted result | before step 8 the dry run reads `DECODE decode.text-native (builtin) -> parse.text.builtin terminal`, and the next line names step 8 as the fix. The `resolve()` block stays, relabelled as what step 8 makes reachable. |
| C2-7 | §9 Step 8 | §9, after Step 7 (lines **2200-2209**) | Add `### Step 8 — the routing fragment, and why the operator installs it` | D10's canonical statement paragraph followed by D10's canonical step-8 block, both verbatim. Renumber nothing: Step 7 stays Step 7. |
| C2-8 | the ipynb driver's `sniff()` and card | lines **2054-2057**, and Step 1's card | `FormatGuess(media_type=…, confidence=0.95)` is now missing two required fields | `return (FormatGuess(media_type="application/x-ipynb+json", format_token="ipynb", confidence=0.95, consumed_bytes=4096),)`, and the card's `[capability.parse]` gains `format_tokens = ["ipynb"]` with one comment line saying `ipynb` is one of core's 48, so the declaration is a **claim to the token** rather than a widening of the domain. |
| C2-9 | the no-seventh-layer cross-reference | §9's step-8 prose | One sentence | …"and there is no `driver` policy layer — [05](../05-ingest-and-routing.md) §4.1 records why". |

---

## 4. C3-routing — `_plan/05-ingest-and-routing.md`

Baseline: 2784. This is the largest slice.

| # | item | locus | change | must say afterwards |
|---|---|---|---|---|
| C3-1 | delete the duplicate declarations (blocking 1) | §2.1, lines **534-553** | **Delete** both `StreamHint` and `FormatGuess` dataclasses. Replace with a one-sentence reference plus D1's canonical `RankedGuess` block | "`StreamHint` and `FormatGuess` are declared once, in `omniweave_ports` ([04](../04-driver-system.md) §1.3): `StreamHint` is `(filename, extension, declared_media_type, byte_len)` and `FormatGuess` is `(media_type, format_token, confidence, consumed_bytes)`. Neither carries a `basis` and neither carries `trust_class` — `TrustClass` is this document's and `omniweave_ports`' `layers.toml` row is `[]`. The host wraps each guess:" then the `RankedGuess` block and the `Basis` alias. The paragraph at :554-556 about `confidence` not being a registered `Signal` **stays**. |
| C3-2 | ladder step 4 | §2.2, ~line **561** | "the driver's own basis, confidence CLAMPED 0.95" → the host's basis | `-> basis='driver_sniff',        confidence CLAMPED 0.95` |
| C3-3 | `format_basis` domain | §5.1, line **1705** | Add the sixth member | domain `{magic, container_identity, content_probe, extension, declared, driver_sniff}` |
| C3-4 | computed `format` domain | §5.1 line **1704**; §2.2's closed-at-48 sentence at line **627** | Replace the domain cell's explanation and the closed-at-48 sentence | D26's canonical `SignalSpec.domain` sentence, verbatim. Line 627's "The token set is closed at release 1" becomes "Core's token set is forty-eight at release 1 and `unit.format`'s **domain** is that set ∪ the union of `[capability.parse] format_tokens` over enabled drivers — see §5.1." The 48-token block and the "every one of them is named by a rule" sentence stay. |
| C3-5 | lint checks 2, 10, 11 over the union | §4.6's check table, lines **1655-1667** | Amend checks 2, 10 and 11 so each resolves against the **computed** domain | each row says "against the computed domain (core's 48 ∪ enabled cards' `format_tokens`, §5.1)"; check 10's equality becomes "the union of `unit.format` literals across `GATE` and `DECODE` rules equals core's **48**, and every driver-contributed token is named by at least one rule at some layer or the linter names the driver". |
| C3-6 | `empty_result` | §6.5's table, ~line **2608** | Replace the `spill_to_free` row | D12's canonical replacement row, verbatim. `08` is not edited. |
| C3-7 | budgets | §4.4 lines **1174-1176**; §10.1 line **2432**; §10.3's opening lines **2560-2561**; §6.5 item 2 lines **2144-2148**; §10.3's message block lines **2632-2634** | Set the three shipped values; recompute §10.1's clamp; add §10.3's site-override setup line; attribute the 8,800 example | D13 in full: `micros_per_part = 3_000`, `micros_max = 16_000_000`; §10.1's line reads `per_unit micros limit = clamp(4000 + 3000x188, 0, 16000000) = 568,000`; §10.3 carries D13's canonical setup line and **every other number in §10.3 is unchanged**; §6.5 item 2 and §10.3's message both gain "Under §10.3's site-layer override (`micros_per_part = 800`)," before "For a 6-part unit". |
| C3-8 | lint check 13 | §4.6's check table | Add row 13 | D14's canonical row, verbatim. Any prose saying "twelve checks" becomes "thirteen": `grep -n "twelve check" _plan/05-ingest-and-routing.md`. |
| C3-9 | lint check 3 | §4.6, line **1658** | Replace the row | D24's canonical replacement for check 3, verbatim. |
| C3-10 | no seventh policy layer | §4.1, after the six-layer table (~line **1521**) | Append one paragraph | D11's canonical sentence, verbatim. |
| C3-11 | close Open question 2 | Open questions, item 2 | Replace the "**Closing evidence:**" sentence | "**Closed:** the row ships — [04](../04-driver-system.md) §10.1 carries `parse.text.builtin` in the release-1 roster, in `omniweave-office`, stdlib-only, serving the ten tokens `decode.text-native` names. Lint check 11 prevents the recurrence." Leave the rest of the item as the record of why. |
| C3-12 | §11's RT5 row | line **2662** | The row names `FormatGuess.confidence` and is still correct. Verify no `basis` reference survives | unchanged unless it mentions `basis`. |
| C3-13 | §12's local terminology table | lines **2766-2767** | Both rows restate the deleted six-field and five-field shapes | replace with D1's shapes verbatim, and add a `RankedGuess` row and a `Basis` row. This is `05`'s own local glossary; the lock is C1's. |

---

## 5. C4-structure — `_plan/06-structure-extraction.md`

Baseline: 2387.

| # | item | locus | change | must say afterwards |
|---|---|---|---|---|
| C4-1 | `normalize_k`'s authoritative definition (blocking 2) | §1.7, immediately after the `MentionDraft` dataclass (~line **437**) | Insert D2's canonical `normalize_k` block | verbatim, under a bolded lead-in: "**`normalize_k`'s six operations and its return type are defined here, once.** `02` §2 row 5 and `terminology.md` name the function and point at this block; neither restates the operations." |
| C4-2 | `ground()` (blocking 2) | §1.7, immediately after C4-1's block | Insert D3's canonical `ground()` block | verbatim. |
| C4-3 | `MentionDraft`'s grounding comment | §1.7, lines **433-435** | Replace the four comment lines with D3's canonical `MentionDraft` comment block | that block, verbatim — four comment lines, and the first names `ground()` rather than a `.find()` expression. |
| C4-4 | the "no shift map" reasoning error | §9.2, lines **1979-1988** | Replace the clause "which is why no shift map is needed anywhere in the framework" and append D2's canonical correction | fix (b) still says grounding runs against the **undefanged** text and still defeats the ZWJ alias for **matching**; D2's canonical correction paragraph follows, stating that the back-map is what keeps the offset recoverable. Two mechanisms, named separately. |
| C4-5 | §9.2's layer-2 row | §9.2, line **1970** | Replace the mechanism cell | `` `ground(block.text, quote)` — normalised match, offsets recovered through the back-map (§1.7) `` |
| C4-6 | `OW_GRAPH_UNGROUNDED` | §1.7's diag table, line **533** | Replace the condition cell | "`ground()` returns `None`: `normalize_k(quote)[0]` is empty, or is not a substring of `normalize_k(block.text)[0]`" |
| C4-7 | P-GROUND | §11's property/gate table | Add one row | D3's canonical P-GROUND row, verbatim, with the six named fixtures. |
| C4-8 | §3.9's two predicates | §3.9, lines **1108-1109** | Replace both table rows | D27's canonical replacement rows, verbatim. |
| C4-9 | §3.9's lead paragraph | §3.9, lines **1100-1103** | Append one sentence naming the added entry point | "…It additionally ships `parse.code.text`, a stdlib-only `parse/1` driver whose `[capability.parse] format_tokens` is the grammar set: without a contributed token a `.py` file resolves to `txt` and the first Pass's predicate is unsatisfiable for every language ([05](../05-ingest-and-routing.md) §5.1)." |
| C4-10 | the two-normaliser warning | §11, lines **2258-2264** | The warning says the two differ by four operations and stands. Append the return-type difference | "…and they now differ in **return type** as well: `normalize_key` returns a `str`, `normalize_k` returns `(str, tuple[int, ...])`. A call site that compares `normalize_k(x)` to a string is a type error, which is the cheapest possible way to catch the misuse that produced the `ts_a`/`ts_b` defect — and the same semgrep rule covers it." |
| C4-11 | §8's provenance chain | §8, lines **1867-1942** | If §8's worked chain prints a `ts_a`/`ts_b` derived from `.find()`, correct it to `ground()`'s triple. `grep -n "find(" _plan/06-structure-extraction.md` | any printed offset is stated as coming from `ground()`, in `block.text` coordinates. If no such print exists, make no edit and report it. |
| C4-12 | New terms | New terms (line **2367**+) | Add `ground()` | one row matching §1's `ground()` definition. |

**06 §2.4 is correct and must not be edited.** `12` is the side that changes (D15).

---

## 6. C5-store-runtime — `_plan/07-store-and-retrieval.md`, `_plan/08-runtime.md`

Baseline: `07` = 2883, `08` = 2700.

| # | item | file | locus | change | must say afterwards |
|---|---|---|---|---|---|
| C5-1 | `ts_a`/`ts_b`'s only producer | `07` | §9.2, after the addressing table (~line **1989**) | Append one sentence | "A `mention` row's `ts_a`/`ts_b` come from **one** function, `ground(block_text, quote)` ([06](../06-structure-extraction.md) §1.7), which recovers them in `block.text` coordinates through `normalize_k`'s back-map. There is no CHECK constraint on the predicate — it needs `normalize_k` and SQLite cannot call it — so 06's P-GROUND property test is the enforcement, and a `mention` written by any other path is a bug with no database-level detector." |
| C5-2 | the `structural` Channel | `07` | §5.2, line **1181** | The sentence "a bounded frontier BFS over `block_link`" is **correct and stays**. Append one sentence after the paragraph | "`edge` — L3's entity→entity table — is **not** traversed by this Channel at v1; it is reachable only through the `@provisional` `GraphView.neighbours()`, outside `retrieve()`, with no budget, weight, ceiling contribution or `Verdict`. [16](../16-roadmap.md) W8.9 (P8, 4 units) is the scheduled work that adds the L3 half, and this section is what it will change. `README.md` and `02` §2 currently say `block_link`/`edge` and are wrong." |
| C5-3 | `Expand.relations` examples | `07` | lines **1656** and **1690** | Replace the relation sets | `relations=frozenset({"refers_to","cites","part_of"})` at :1656, and at :1690 "reached from the semantic seed over {refers_to, cites}". Per D5, `anchor_ref`/`note_ref`/`continues` are L2 `RelKind` members that `block_link`'s FK to `relation_vocab` rejects. |
| C5-4 | `cache_index` retraction | `08` | §4.1's `call` row (line **1123**) and §4.1's justification paragraph (lines **1130-1134**) | Replace the `call` row's last cell with D9's canonical one-line form; replace the justification paragraph's second sentence with D9's canonical retraction paragraph | both verbatim. The "There is no `parse` layer and no `derive` layer" paragraph and the parse-memo definition stay. |
| C5-5 | F1's two variables | `07` | §12.5 lines **2530-2533**; the F1 open-question row's fallback cell at line **2822** | Replace with D16's canonical paragraph and canonical fallback cell | verbatim. The phrase "T2 arrives at 5M blocks rather than 50M" appears **nowhere** in `07` afterwards. |
| C5-6 | `ceiling()` and `OFF(query_deadline)` | `07` | §5.3's formula block (lines **1241-1245**); after the "Never hardcode" paragraph; §6.4's block (line **1568**); §11's ST6 row (line **2685**) | Replace the formula block; append D23's canonical paragraph; add the clause to §6.4; ST6 becomes three halves | D23 in full. The "Both functions resolve weights through `_weight()`" paragraph stays. |
| C5-7 | the hydration reservation | `07` | §4.4's TOML block (lines **982-987**) and the sentence following it; `07`:2763's `QueryBudget` defaults; `07`:2876's `QueryBudget` glossary row | Replace both; add the field and name it | D24's canonical TOML block and canonical `ow route lint` sentence, verbatim; `QueryBudget` gains `hydration_reserve_ms: int = 40` and the glossary row names it. |
| C5-8 | `07`'s local terminology | `07` | §14's table (line **2871**+) | Verify no row says the `structural` Channel traverses `edge`. `Hit`'s row at :2871 is correct as written | no edit unless a row says `edge`. |

**`08` §1.6's no-empty-success rule (lines 240-241) is correct and stays.** Per D12, `05` changes.
**Do not edit `08` §9** — the evaluation's section citation was wrong and there is nothing there.

---

## 7. C6-performance — `_plan/12-performance.md`

Baseline: 1839.

| # | item | locus | change | must say afterwards |
|---|---|---|---|---|
| C6-1 | `cache_index` retraction | §5.4 (lines **779-787**), §5.8's `call` row (line **912**), §6.6's paragraph (lines **1278-1285**) | Replace §5.4's opening two paragraphs and §6.6's "single most consequential number" paragraph with D9's canonical retraction paragraph; §5.8's `call` row takes D9's canonical one-line form | all verbatim. §5.4's heading becomes "### 5.4 The `call` cache layer — $99 per re-derivation on the reference corpus". §6.6's re-ingest **column** stays and its arithmetic is unchanged; the paragraph now says the saving is realised inside one store — a `schema_version` bump, a `digest_recipe` bump, an `ow index rebuild --derived`, a metadata-only touch — and **not** on a move to a second store. |
| C6-2 | the per-unit cap collision | §5.1, lines **705-712** | Replace the "and the alternative ALSO degrades" block with D13's canonical replacement block for `12` §5.1 | that block, verbatim. The "858 micros and 853.4 micros are two different numbers" paragraph below it stays exactly as written, because both figures remain correct. |
| C6-3 | `1 − Cover` → billed share | §6.3 lines **1180-1181**, §6.4 lines **1225-1226**, §6.5 line **1256**, §6.6's table lines **1269-1272**, §6.8 | Replace each billed-residue line and its parenthetical; update the three C3 totals; update §6.6's three C3 cells; append §6.8's sixth clause | D15 in full. A 25,920 seg / $5.18 / $3.11 / **C3 $11.30**; B 14,720 seg / $2.94 / $1.77 / **C3 $11.77**; C 19,824 seg / $3.96 / $2.38 / **C3 $7.44**. Each parenthetical is D15's canonical annotation line with its own row name. C1, C2 and the re-ingest column are **unchanged**. |
| C6-4 | the GPU ingest wall | §3.1's table, line **338** | Replace the cell; add one clause to §3.1's prose | D21's canonical row verbatim, plus "§3.4 prices the same 77.6 GPU-h of work at the same band and the two now agree." §3.4's line 439 is already right and is **not** edited. |
| C6-5 | concurrent readers | §4.1's table, the "16 concurrent readers" row | Replace the row | D25's canonical replacement row, verbatim. |
| C6-6 | `ow bench query`'s scales | §7.1's table, the `query` row; §7.1's "Extends the charter" paragraph | Replace the row; append one clause | D33's canonical row verbatim, plus "…and `query`'s scale list is extended to 20M/30M/50M because **P-Q8's own instrument did not exist**: §7.1 ran 10k/1M/10M and P-Q8 asks for the breakpoint above 10M." |
| C6-7 | the `$99` arithmetic | §5.4 | The 116,400 × 853.4 ≈ $99 derivation is **unchanged**; only its framing moves | the number and its derivation survive verbatim inside D9's paragraph. |

---

## 8. C7-out-roadmap — `_plan/09-generation.md`, `_plan/16-roadmap.md`, `_plan/11-repo-layout.md`

Baseline: `09` = 2661, `16` = 1208, `11` = 2566.

| # | item | file | locus | change | must say afterwards |
|---|---|---|---|---|---|
| C7-1 | R3's `fidelity` condition | `09` | §11's law table, line **1849** | Replace the condition cell | D20's canonical replacement, verbatim. |
| C7-2 | R3 and the three targets | `09` | §12's target table line **1944**; §12.3's fidelity paragraph line **2071** | Both already assert R3 for `docx`. Append one clause to §12.3's paragraph | "…and R3 applies because R3 is a predicate over `content_digest` and carries no geometry: §11's condition reads `fidelity ∈ {structure, passthrough, patched}`, every value but `none`." |
| C7-3 | the video target's exemption | `09` | §12.4's `laws` row, line **2104** | Already says R3 is refused. Verify it names `fidelity = "none"` as the reason | "R3 is **refused** because `fidelity = "none"` is §11's one exemption: a lossy encode is not idempotent…" |
| C7-4 | F1's two variables | `16` | DP8's fallback cell, line **1098** | Replace "T2 arrives at 5M Blocks rather than 50M" | D16's canonical fallback cell verbatim, followed by "…and V20-2 is refit rather than defended". |
| C7-5 | W10.10 and the calendar | `16` | §13's P10 table (after W10.9); §3.1's matrix and prose; lines **12**, **914**, **958**, **1014** | Add the row; then apply every line of D17(b)'s calendar arithmetic | D17(b) in full. **Nine numeric edits — check each against D17(b)'s block.** The matrix must still sum both ways: block I `4 + 23 = 27` of capacity 30, and the total row's `used` = 363. |
| C7-6 | §18's two new rows | `16` | §18's table | Add both rows | D17(c)'s two canonical rows, verbatim. |
| C7-7 | the nightly GPU cell | `11` | §6.5's table line **1525**, and the sentence at line **1533** | Replace the row with D22's two canonical rows; change the sentence | D22 in full. `ow-bench-1` never carries the word "GPU" in `11` afterwards: `grep -n "ow-bench-1" _plan/11-repo-layout.md` to confirm. |
| C7-8 | the SDK carve-out | `11` | §6.3's table, line **1043**, the SDK row's "breaking" cell | Replace | D8's canonical replacement cell, verbatim. |
| C7-9 | the vendoring claim | `11` | line **159** | `normalize_key · normalize_k  (vendor/graphify-ids)` | `normalize_key (vendor/graphify-ids) · normalize_k (ours)` plus one trailing comment: `normalize_k has no graphify original`. Per D2: `grep -rn "'Cf'" _collections/graphify/graphify/*.py` returns nothing. `02`:229 carries the same wrong claim and is out of cluster. |
| C7-10 | the attachment distributions | `11` | §1.2, after its closing prose, before §1.3 | Insert D17(a)'s canonical block | verbatim. **Do not touch** §1.2's fourteen-row table, its "fourteen distributions" heading, line 51's tree annotation, line 259's "all fourteen", line 272's "five of the fourteen", line 978's "thirteen of the fourteen", line 1720's "13 rows", or line 1598's "26 non-core files". The attachment distributions are outside all of those and D17(a) says so. |
| C7-11 | §4.3's ten-site checklist | `11` | lines **480-492** | The checklist governs adding one of the fourteen. Append one line below the table | "An **attachment distribution** (§1.2's second table) is a different animal: it takes sites 1, 2, 3, 4 and 8, skips 5, 6, 7, 9 and 10 because it is not `RELEASE`-versioned, is not in `first_party.toml`, is not in an extra and is not in the `--all-packages` wheelhouse assertion, and it names its own third-party floor rather than inheriting one." |

---

## 9. C8-interfaces — `_plan/10-interfaces.md`, `_plan/18-api-sketch.md`

Baseline: `10` = 2662, `18` = 3264.

| # | item | file | locus | change | must say afterwards |
|---|---|---|---|---|---|
| C8-1 | `FormatGuess`'s flat sentence (blocking 1) | `18` | line **1807** | Replace "`FormatGuess` is `(media_type, confidence)` and `__post_init__` raises" | "`FormatGuess` is `(media_type, format_token, confidence, consumed_bytes)` — four fields, declared once in `omniweave_ports` ([04](../04-driver-system.md) §1.3) — and `__post_init__` raises outside `[0.0, 1.0]`. A driver names a **token**, which is what makes a new format reachable, and never a `basis`: `basis` is the host's classification of *how* a guess was obtained and it lives on `RankedGuess` ([05](../05-ingest-and-routing.md) §2.1)." |
| C8-2 | `Expand.relations` example | `18` | line **2768** | Replace the relation set | `relations=frozenset({"refers_to", "cites", "part_of"})`, plus one comment line: `# relation_vocab members. anchor_ref/note_ref/continues are L2 RelKind and block_link's FK rejects them.` |
| C8-3 | `Corpus.doc` | `18` | line **494** | Remove `# @provisional` | `def doc(self, ref: str) -> Doc:                                                  # @stable`, with one docstring clause: "`@stable` per [10](../10-interfaces.md) §9.4 — it is the only escape hatch from the answer surface into the document model, and every framework adapter's fidelity claim runs through it." |
| C8-4 | §9.4's stability lists | `10` | §9.4's `text` block, lines **2147-2158** | Add `Corpus.doc` to `@stable`; replace the `RenderedBlock` field lists per D7 | `@stable` names `Corpus.doc` and the fifteen `RenderedBlock` fields `cite, addr, doc_uri, text, page, quad, quote, trust, method, origin_driver, byte_exact, score, score_kind, defanged, restriction_bits`; `@provisional` names `channel_contributions, channel_ranks, identity_grade, segment_id`. Append one paragraph carrying D7's four one-line reasons for `quad`, the `score` pair, `doc_uri` and `defanged`. |
| C8-5 | `18`'s field-count paragraph | `18` | lines **631-638** | Replace | "The `@provisional` fields are exactly [interfaces](../10-interfaces.md) §9.4's four — `channel_contributions`, `channel_ranks`, `identity_grade`, `segment_id` — plus the four this document adds (`block_id`, `kind`, `layer`, `is_context`), which are provisional for the same reason: they are packer internals a programmatic caller would otherwise re-query for, and promising them at a MAJOR boundary would freeze the packer. **Eight provisional.** The **eighteen `@stable`** fields are §9.4's fifteen verbatim plus `span`, `superseded_by` and `retired_at_gen`, because [the document model](../03-document-model.md) requires a retired cite to resolve **and say so** and the charter gives that sentence no field to live in. 18 + 8 = 26, which is every field, and there is no unclassified field left." |
| C8-6 | the text driver's `doc` record | `18` | line **2016** | `"format": "text/plain"` → `"format": "txt"` | one trailing comment: `# a format TOKEN, never a media type (05 section 2.2). media_type is the next key.` |
| C8-7 | the hydration reservation | `18` | line **1693** and the row above it; the printed config line at **1206** | Add the `hydration_reserve_ms` row; replace the `channel_ms` row's note; add the printed line | D24's two canonical config rows verbatim, and `retrieval.budget.hydration_reserve_ms = 40` printed beneath `18`:1206's `channel_ms` line. |
| C8-8 | concurrent readers | `10` | §10, after the `max_sessions` paragraph (~line **2272**) | Append one sentence | D25's canonical pointer sentence, verbatim. **A pointer only** — `12` §4.1 owns the row, and restating its numbers would invert the fix. |
| C8-9 | D9's OUT consequence | `10` | §10, after its first paragraph (~line **2200**) | Insert one paragraph | D31's canonical paragraph, verbatim. |
| C8-10 | the `COPYLEFT_NETWORK` conjunct | `10` | §10, after the two-loopback-endpoints paragraph (~line **2230**) | Insert one paragraph | D32's canonical paragraph, verbatim. `10`'s error-code table gains `OW-A-023 / OW_SERVE_COPYLEFT_NETWORK`; if `10` has no such table, report it. |
| C8-11 | `18`'s ports inventory | `18` | line **834** | The T-CONTRACT row lists `StreamHint` and `FormatGuess` and is correct. Verify `Basis` and `RankedGuess` are **not** there | unchanged. They are host-side and must not appear in an `omniweave_ports` inventory. |
| C8-12 | `18` §5's `FormatGuess` construction | `18` | line **1986** (and the imports at **1926**) | Missing two required fields | `return (FormatGuess(media_type="text/plain", format_token="txt", confidence=conf, consumed_bytes=len(head)),)`. The `sniff()` signatures at :1782 and :1977 are unchanged. |

---

## 10. C9-evidence — `_index/in-04-agentic.md`

Baseline: 301. This is the one cluster whose file is an **evidence index**, not a plan document, and
its edits are factual corrections with source citations.

| # | item | locus | change | must say afterwards |
|---|---|---|---|---|
| C9-1 | the Haystack MCP row | §2's client table, the **haystack** row | Replace "**none** / `find haystack -iname "*mcp*" -name "*.py"` returns nothing. Haystack is not reachable this way and must have an adapter" | ``| **haystack** | `mcp-haystack` (`haystack-core-integrations/integrations/mcp`) → `MCPTool`, `MCPToolset` | reachable over Streamable HTTP, SSE and StdIO (`_collections/haystack/docs-website/docs/tools/mcptool.mdx`, `mcptoolset.mdx`). **But `invoke` returns a JSON `str`**: `reference/integrations-api/mcp.md`:214 gives `call_tool(tool_name, tool_args) -> str` and :694 gives `ainvoke(**kwargs) -> str \| dict[str, Any]`, and the examples at :607-641 bind `result_json = tool.invoke(...)`. So the Answer arrives **stringified**, which destroys `10` §3.5's `**ow:<name>**` markers a consumer greps for. The one client of six that **mangles** rather than truncates |`` |
| C9-2 | the answer paragraph's count | line **6** | "Four of the eight orchestration frameworks need no omniweave-side code at all" | "**Seven of the eight** orchestration frameworks need no omniweave-side code at all: six ship an MCP client (adk-python, langchain, pydantic-ai, crewAI, llama_index, and haystack via `mcp-haystack`), agentcore attaches as a Gateway target by configuration, and langgraph reaches omniweave through langchain's `MCPAdapter`. Every adapter below is therefore a **fidelity** upgrade on a path that already works, not an access path." Also change the same paragraph's "for the other four the adapter is three to six classes" to "for four of them a *fidelity* adapter is three to six classes". |
| C9-3 | the `structuredContent` scope | line **7**, and the crossing-table framing | "one text block, no `structuredContent` (`_plan/10-interfaces.md` §3.5)" | "one text block for the **Answer**, with **no `outputSchema` and no `structuredContent` on `ow_query` and `ow_open`** — `_plan/10-interfaces.md`:511 is explicit that `ow_corpora` and `ow_add` are small and row-shaped and **do** declare one, so two of the four listed tools declare `structuredContent` and the two that carry evidence do not" |
| C9-4 | §2's five-versus-six | line **55** | "Verified from source, five of the eight ship an MCP client in the vendored tree" | "Verified from source, **six** of the eight ship an MCP client — five in the framework's own tree and haystack's in `haystack-core-integrations` as `mcp-haystack`, which is why an earlier `find` over the framework repository alone returned nothing. Two more are reachable without one: agentcore by Gateway configuration, langgraph through langchain's `MCPAdapter`." |
| C9-5 | §7 item 3's justification | §7's table, the `omniweave-haystack` row | Replace "Haystack is the only one of the eight unreachable by MCP, so without this it is unreachable at all." | "Haystack **is** reachable by MCP (`mcp-haystack`), so this adapter buys **legibility**, not access: `MCPTool.invoke` returns a JSON `str`, so `10` §3.5's section layout arrives stringified and the `**ow:<name>**` markers a consumer greps for are gone. It is the one client of six that mangles rather than truncates. And connect-time DAG type validation is still the only place a native omniweave type can flow between third-party components with the edge checked statically — a genuinely better ingestion story than the loader interface, worth having as an existence proof." |
| C9-6 | where §7 landed | §7's closing paragraph | Append one sentence | "**Folded into the plan by stage 10:** `omniweave-langchain` is funded as `_plan/16-roadmap.md` **W10.10** (P10, 3 ew, from block I's schedule buffer), the other three plus `omniweave-docling` are named, costed and ranked in `16` §18, and all five appear in `_plan/11-repo-layout.md` §1.2's attachment-distribution table as separately versioned wheels outside the fourteen." |

---

## 11. Out-of-cluster follow-ons — report, do not edit

No cluster owns these files. Each fixer that notices one **reports it in its return** and makes no
edit. They are listed here so nine agents report the same list.

| file | locus | what is stale after this stage | which decision |
|---|---|---|---|
| `02-architecture.md` | 117 | "expand.py BFS over block_link / edge" — `structural` traverses `block_link` only | D4 |
| `02-architecture.md` | 229 | `normalize_k`'s definition omits whitespace-collapse and strip, gives no return type, and claims a graphify vendoring that does not exist | D2 |
| `02-architecture.md` | 1367 | "T2 arrives at 5M blocks rather than 50M", and lists the 600 MB supervisor RSS gate as an F1 dependent while `12` §4.2 rule 1 says that ceiling is corpus-independent | D16 |
| `README.md` | 243-244 | "`structural` traverses L3's `block_link`/`edge`" | D4 |
| `README.md` | 359 | "T2 arrives at 5M blocks rather than 50M" | D16 |
| `00-vision.md` | 747 | the same 5M figure | D16 |
| `17-risks.md` | 188, 424 | R-T2 and A3 both carry "T2 arrives at 5M blocks rather than 50M" | D16 |
| `17-risks.md` | both registers | neither `FormatGuess` nor `StreamHint` appears in either register, and both were blocking | D1 |
| `15-observability.md` | 972-973, 1587-1588 | `micros_per_part 800` and `micros_max 250,000` in a printed budget trace and in a knob-naming paragraph | D13 |
| `14-security.md` | 1621 | needs the reciprocal of `10` §10's conjunct: a `copyleft_network` ack does not cover a listening transport | D32 |
| `glossary.md` | 598, 979 | `FormatGuess` and `StreamHint` rows carry the deleted six-field and five-field shapes and cite `05` §2.1 as the home | D1 |
| `charter.md` | 2603-2605 | the illustrative policy block's `micros_per_part = 800` / `micros_max = 250_000` | D13 |
| `charter.md` | 4812 | "Making `normalize_k` strip Unicode `Cf` deletes the `ShiftMap` entirely… One function, three problems" — the reasoning error itself | D2 |
| `charter.md` | 8588 | F1's fallback carries the 5M figure | D16 |
| `charter.md` | 905 | commits to `omniweave-docling`; now matched by `11` §1.2 and `16` §18 rather than by nothing | D17 |

`final-review.md` lists twelve contradictions and names **neither** blocking defect and **no**
framework attachment. That is recorded here and nowhere else; `final-review.md` is not edited.

---

## 12. Did not reproduce

| finding | evidence |
|---|---|
| the `03` member of "the six-document `structural`-channel disagreement (03/07/16/18 plus `02`:117 and `README`:244)" | `grep -n "structural" _plan/03-document-model.md` returns five hits: :69 (owcheck's structural invariants), :532 ("structural rather than"), :834 ("2 structural" DocItem kinds), :1291 ("no structural meaning"), :2164 ("structural levels"). **None is a claim about the `structural` retrieval Channel.** `03` is not a party to this contradiction; the real count is five documents, of which `07`, `16` and `18` are already correct and `02` and `README` are wrong and out of cluster. No edit assigned to C1. |
| "850-vs-865 tokens" as a contradiction | 850 is the default compact `tools/list` payload (`10`:10, :308, :860; `18`:1568, :2954). 865 is the same payload **after** §3.4's `required`-promotion of `corpus`, and **both** sites that print it state it as a delta: `10`:498 and `18`:1378 read "+15 tokens on the compact payload (850 → 865)", and `10`:2451's JSON key is literally `"default_compact_corpus_required": 865`. Two conditions, two numbers, both labelled. No edit assigned. |
| the `08` §9 half of "`08` §9-vs-`05` §6.5 on `empty_result`" | `08` §9 is "What a distributed backend must supply" (:2295-2410) and says nothing about `empty_result`. The rule is at `08`:240-241 (§1.6) and `08`:428. The **substantive** contradiction reproduces against `05` §6.5's table row and is assigned (D12, C3-6); only the cited section number was wrong. Recorded so no fixer goes looking in `08` §9. |
| "`normalize_k` is vendored from graphify, so the fix needs a fork and an ADR" | `grep -rn "'Cf'" _collections/graphify/graphify/*.py` returns nothing. The adversarial verifier already overturned this; it is recorded here because `02`:229 and `11`:159 both assert the vendoring and a fixer reading them might re-derive the fork. **No fork, no ADR.** `11`:159 is corrected (C7-9); `02`:229 is out of cluster. |
| "`06` §2.4 uses `1 − covered_frac`" | `06` §2.4 states in bold that billed share is **not** `1 - covered_frac` and prints both weighted figures (0.476 and 0.564). `06` is correct; `12` §6.3-6.5 is the erring side and is where the edit goes (D15, C6-3). `06` §2.4 must not be touched. |
| "the three `owdoc-fragment` key spellings" as three *fragment* spellings | there are **two** wire formats, not three spellings of one: the `.owdoc` archive's 29 short keys (`03`:604-634, where `t` is **text**) and `owdoc-fragment/1`'s long keys (`04`:2073, `18`:2016, where `t` is the record **type**). `04` and `18` agree with each other exactly. The defect is `03`:600's sentence claiming both wires share one key set, plus `18`:2016's media type in a token field. Both assigned (D19), but the finding's framing as three drifting spellings does not hold. |

---

## 13. Deferred — cannot be closed by editing the plan

| item | why it cannot be an edit | what stage 10 does instead |
|---|---|---|
| **F29 — where a single-page commit actually fails** | needs the 4M-cell fixture *built and run*: the ~2.8 GB WAL and ~23 s commit are printed estimates. Whether a sub-page commit boundary is needed is a measurement, and a pessimistic answer is a fourth span level and a change to the work table's unit — 3-4 ew and an architecture change | D18 reconciles `03`:2546-vs-:2566 either way and states the cost. The spike is S10.5's, and it precedes P2's migration sequence because 91 tables share one strictly-ordered sequence |
| **F1 — blocks per page including cells** | needs `fixtures/gen/gen_5000p_pdf.py` plus ten real 200-page documents run on `ow-bench-1` | D16 replaces the un-derived 5M figure with the two-variable statement, so no document asserts a number the measurement has not produced |
| **P-Q8 / R-Q6 — the single-store serving ceiling, and the cost of N open Readers** | a bench sweep at 10M/20M/30M/50M plus an fd-and-RSS measurement at N ∈ {1, 8, 32, 128} | D33 extends `12` §7.1's `query` subject to the scales P-Q8 requires — the instrument did not exist. D25 states the reader-memory exposure and names R-Q6. Neither runs anything |
| **F13 — `covered_frac` on real corpora** | fixture-driven measurement | D15 makes `12` read `06` §2.4's projected billed share rather than computing a wrong one from coverage. The projections stay labelled as projections |
| **F50 / F7 / B09 / F55 / the `DEFAULT_WEIGHTS` fit** | all measurements | untouched by this stage. D23's ceiling fix is the one thing about F50 that is a specification defect rather than a missing number, and it is assigned |
| **The machine-scoped `cache_index` sidecar** | 2-3 ew of new mechanism with its own GC, price-book replay and `--allow-rebill` path. Out of scope: this stage adds no mechanism | D9 retracts the claim and records the sidecar as deferred and unfunded, with its cost, so no plan document assumes it |
| **`omniweave-haystack`, `omniweave-llamaindex`, `omniweave-adk`** | 7 ew against a schedule allocated to 363 of 366 ew | D17(c) names, costs and ranks all three in `16` §18 with `_index/in-04-agentic.md` §7 as the authority on the order. `omniweave-langchain` alone is funded (D17(b)) |
| **The generated geometry-key T-SCHEMA artefact for out-of-tree reverse adapters** | S10.4 proposed publishing the untyped-dict geometry key schema as a generated artefact. That is a **new generated surface**, and the generated-surface registry freezes at P7 week 42 | recorded here and nowhere else. `03` §16.1's `SpanMap` plus `07`:2560-2566's plain-ZIP export are the primitives an out-of-tree reverse adapter already has; a new generated artefact is out of this stage's scope |

---

## Open questions

1. **Does `micros_per_part = 3_000` need a laptop-class default?** D13 sets it from
   `parse.page.olmocr`'s `reserved_micros`, which is a GPU driver's number. On `ow-laptop-1`,
   `12` §2.6 clamps to free, so no reservation of that size is ever taken and the cap is inert — but
   a future laptop-class PAGE driver with a different `reserved_micros` would want its own row.
   **Closing evidence:** lint check 13 (D14) already fails a policy whose `micros_per_part` is below
   an enabled driver's `reserved_micros`, so the linter will name the day this matters.
2. **Is `Doc`'s accessor set individually tiered, or does `@stable` on `Corpus.doc` cover all
   twelve?** D6 makes the method `@stable` and leaves `Doc`'s accessors where `03` and `18` define
   them, on T-SCHEMA's two-release deprecation window. That is coherent, but it means a caller reads
   two different promises from one call. **Closing evidence:** whether `omniweave-langchain`'s
   artifact path touches `Doc.grid()` or `Doc.page_render()`, which W10.10 answers in its first week.
3. **Does the eighth publish step belong in `ow drivers scaffold` or in `ow drivers add`?** D10 puts
   the fragment in `scaffold` and the path hint in `add --enable`. An operator who installs a wheel
   they did not scaffold gets the hint and not the fragment. **Closing evidence:** whether a
   `driver.toml` may carry the fragment inline, which is a `card_schema` question and therefore due
   before P1 week 10.

## New terms

| term | definition | where it lands |
|---|---|---|
| `RankedGuess` | the host-side wrapper `(guess, basis, detail)` around a `FormatGuess` | `05` §2.1; locked (§1) |
| `Basis` | the host's six-member classification of how a format guess was obtained | `05` §2.1; locked (§1) |
| `ground()` | the one grounding function, returning `(ts_a, ts_b, occurrences)` in `block.text` coordinates | `06` §1.7; locked (§1) |
| `format_tokens` | the `[capability.parse]` card key that widens `unit.format`'s computed domain | `04` §1.4; locked (§1) |
| `format_token_for()` | the media-type→token lookup over the computed union | `05` §2.2; a function, not a locked concept |
| `hydration_reserve_ms` | the named `[retrieval.budget]` reservation for hydration and the coverage scan | `07` §4.4; a config key, not a locked concept |
| **attachment distribution** | a separately versioned wheel that attaches omniweave to a third party's type system; outside the fourteen and outside `first_party.toml` | `11` §1.2 |
| `parse.code.text` | the stdlib-only `parse/1` driver `omniweave-driver-code` ships to contribute its grammar-set tokens | `06` §3.9 |
| `OW-P-021` | lint check 13's code: a per-unit cap below an enabled driver's `reserved_micros` | `05` §4.6 |
| `OW-D-024` | a media type mapping to two format tokens across enabled cards | `05` §2.2 |
| `OW-A-023` / `OW_SERVE_COPYLEFT_NETWORK` | `ow serve --http` refusing a listening transport under a `copyleft_network` restriction | `10` §10 |
| `OW_DETECT_UNKNOWN_TOKEN` | a `FormatGuess` whose `format_token` is outside the computed domain, dropped with the driver named | `05` §2.2 |
