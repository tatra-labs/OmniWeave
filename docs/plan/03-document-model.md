# 03 — The Document Model (`owdoc`)

**In one paragraph.** `owdoc` is a flat **Block** table with one containment spine (`parent_id` +
`ord`), a closed seven-member `rel` table, and satellites for marks, grids, parts, assets and
diagnostics; its canonical form is the `.owstore` SQLite file and its interchange form is the
`.owdoc` ZIP. Markdown, GFM, HTML, text, OTSL, segments and a caller's JSON Schema are all
**projections** computed on demand, never a stored second representation (INV-1). Every Block carries
four identities with four jobs, three non-interchangeable coordinate systems, six provenance axes and
two ordered confidence ladders. A parse writes into a **staged generation** no reader can see until
`end_doc()` commits it. This document specifies all of it normatively.

This document expands charter **D2** in full, plus the parts of §6.1 (the prompt-safe token space),
§6.2 (provenance), §6.3 (confidence), §6.6 (versioning), §6.9 (`canonical()`) and §6.10 (limits)
that land on a Block, and the L2 half of the staged-generation fix (charter §D4's torn-parse hole,
I21). Where the charter is silent on a detail the model needs, the decision is made here and marked
**Extends the charter**. Where the charter is internally inconsistent, this document follows it and
§18 records the problem.

## 1. What is normative, and what is a view

```
                    +---------------------------- L2: owdoc ----------------------------+
  parse/1 driver    |                                                                   |
  ------------->    |   block -- mark        rel        cell -- table_meta -- grid_slot |
  owdoc-fragment/1  |     |      block_asset            part      asset      page       |
  (NDJSON, tmp ids) |     |                                       diag       producer   |
        |           |     +-- block_fts   (external-content: NO second copy of text)    |
        v           |     +-- ow_block_head (the head-generation view every reader uses) |
     DocSink        +-------------------------------------------------------------------+
     (host-side)                ^ canonical form: .omniweave/index.owstore
                                |
                                +-- serialize(scope, "md"|"gfm"|"html"|"text"|"otsl") -> (str, SpanMap)
                                +-- segment / segment_block (L3)  -> Segments
                                +-- project_schema(scope, JSON Schema) -> (obj, FieldGrounding)
                                +-- export()  -> report.owdoc (ZIP of NDJSON Frames)
                                +-- page_render(page, dpi) -> an evictable derived asset
```

Three rules follow, and a reviewer may reject a PR on any of them without further argument:

1. **The store is the model.** L3 and L4 add tables and indexes to the same `.owstore` file; they
   never add a second representation of a Block. There is no model-plus-sync-layer.
2. **Everything to the right of the arrows is a function.** A projection is pure over
   `(scope, options, store snapshot)`. It may be *cached* (as a hash-pinned view in
   `manifest.views[]`, or in the `render` cache layer) but it is never a *field*. No model class in
   this framework has an `html`, `markdown` or `md` attribute, and semgrep asserts it.
3. **The host writes; the driver proposes.** A `parse/1` driver emits an `owdoc-fragment/1` NDJSON
   stream addressing blocks by a per-invocation `tmp` id. The host decodes it and drives `DocSink`,
   minting `block_id`, `addr`, `cite`, `producer_id`, `origin_*` and `restriction_bits` itself
   (INV-6, INV-7, charter §5 X1). No `block_id` ever crosses the driver wire, which is what makes a
   fragment portable between stores. See [the driver system](04-driver-system.md) for the wire and
   [ingest and routing](05-ingest-and-routing.md) for who invokes it.

### 1.1 The write path, in order, because the order is load-bearing

Six of this document's mechanisms only make sense against this sequence. `g_h` is the document's
committed head generation (`doc.gen`); `g_t = g_h + 1` is the **target generation** this parse writes.

```
begin_doc(rec)         insert or look up `doc` by doc_key; assign doc_ord; gen = 0 on first sight;
                       record `declared`; fix the target generation g_t
  begin_page(pg)         insert the `page` row at (doc_ord, g_t, page); reset the page-root counter
    add_block(draft)     mint block_id, addr, cite, ord; stamp provenance; write a PROVISIONAL digest
    add_marks / add_grid / add_rel / add_asset / add_part / diag
  end_page(stats)      COMMIT ONE TRANSACTION. Rows are durable and invisible (g_t > doc.gen).
  ... repeat per page ...
end_doc(status)        one final transaction:
                         1. the CLOSURE PASS (§6.4) finalises cross-page merkle digests
                         2. owcheck runs the structural invariants over g_t
                         3. rebind(store, doc_ord, g_t) reconciles identity against g_h (§6.5)
                         4. iff not quarantined: UPDATE doc SET gen = g_t, status = ..., achieved = ...
```

**Nothing is visible before step 4.** Every reader resolves through `ow_block_head`, which joins
`block.gen = doc.gen`; a crash at page 3,000 of 5,000 leaves 3,000 durable but invisible pages, the
previous generation still answering every citation, and a claimable `work` row. Abandoned
generations are swept at startup by `DELETE FROM page WHERE gen > (SELECT gen FROM doc d WHERE
d.doc_ord = page.doc_ord)`, which cascades through `block` and every satellite. This is charter §D4's
staged-generation fix seen from L2 (I21); `work.staged_gen` is [the runtime](08-runtime.md)'s column,
and the model's half is exactly the visibility rule, the sweep predicate and `gen = 0`.

**`gen = 0` is reserved and means "no committed generation".** A `doc` row at `gen = 0` has no
visible blocks, which is the right answer for a document whose only parse failed: `status='failed'`,
a `diag` row explaining it, and a coverage gap in the corpus card. The DDL's `DEFAULT 1` is
vestigial — `begin_doc` always states `gen` explicitly.

## 2. The type specification

`omniweave_core.model` is **stdlib only** — no pydantic, no numpy, no PIL, no pandas, no pyarrow —
asserted by `test_core_closure.py` over the resolved dependency graph rather than declared manifests
(INV-2). Every value type is `@dataclass(frozen=True, slots=True)`. There is exactly one mutable
model type, `BlockDraft`, and it never reaches a reader.

### 2.1 Enums

```python
class Kind(StrEnum):     # 34 members + UNKNOWN (mandatory for forward compatibility)
    DOCUMENT="document"; SECTION="section"; TITLE="title"; HEADING="heading"
    PARAGRAPH="paragraph"; LIST="list"; LIST_ITEM="list_item"
    BLOCKQUOTE="blockquote"          # renamed from QUOTE: the tier enum owns that word (§5 X17)
    CODE="code"; TABLE="table"; TABLE_CELL="table_cell"; FIGURE="figure"; PICTURE="picture"
    CAPTION="caption"; FORMULA="formula"; RULE="rule"; PAGE_HEADER="page_header"
    PAGE_FOOTER="page_footer"; FOOTNOTE="footnote"; ENDNOTE="endnote"
    SPEAKER_NOTE="speaker_note"; COMMENT="comment"; FORM="form"; FORM_FIELD="form_field"
    CHECKBOX="checkbox"; KEY_VALUE="key_value"; TOC="toc"; TOC_ENTRY="toc_entry"
    REFERENCE="reference"; BIBLIOGRAPHY="bibliography"; HANDWRITING="handwriting"
    CHEMICAL="chemical"; DIAGRAM="diagram"; CONTAINER="container"; UNKNOWN="unknown"

class Layer(StrEnum):    BODY="body"; FURNITURE="furniture"; NOTE="note"
                         ANNOTATION="annotation"; HIDDEN="hidden"
class Trust(IntEnum):    AMBIGUOUS=0; INFERRED=1; EXTRACTED=2
class Quote(IntEnum):    SYNTHETIC=0; RECONSTRUCTED=1; REFLOWED=2; NORMALIZED=3; VERBATIM=4
class Method(StrEnum):   NATIVE="native"; TEXT_LAYER="text_layer"; NATIVE_XML="native_xml"
                         OCR_PAGE="ocr_page"; OCR_BLOCK="ocr_block"; VLM_PAGE="vlm_page"
                         LLM="llm"; HEURISTIC="heuristic"; ROUNDTRIP="roundtrip"; USER="user"
class PageKind(StrEnum): PAGE="page"; SLIDE="slide"; SHEET="sheet"; FRAME="frame"; STREAM="stream"
class RelKind(StrEnum):  CAPTION_OF="caption_of"; NOTE_REF="note_ref"; CONTINUES="continues"
                         ANCHOR_REF="anchor_ref"; HEADING_OF="heading_of"
                         DERIVED_FROM="derived_from"; SUPERSEDES="supersedes"
class OsKind(StrEnum):   BYTES="bytes"; NODEPATH="nodepath"; GLYPHS="glyphs"
                         PIXELS="pixels"; NONE="none"
```

`OsKind` **extends the charter**: D2 names the `origin_span_kind` `enum_val` domain and the five
variant tags but never declares the enum the domain is generated from, and `enum_val` is generated
from a Python enum by construction.

`Trust` and `Quote` are **ordered `IntEnum`s with the weakest tier lowest**, so `MIN()` over a set is
its weakest member. That is the only reading under which `segment.quote_min` and `Filters.min_quote`
are gates rather than lies: under a declaration-ordered `StrEnum` with `VERBATIM` first, one verbatim
block in a segment made the whole segment pass the byte-exactness gate for its reflowed and synthetic
members. Two property tests guard it: `segment.quote_min == min(member quotes)` over a deliberately
mixed segment, and `Quote.SYNTHETIC < Quote.VERBATIM`.

**Wire and storage encoding.** Every enum value is the **lower-case member name** as a string on the
wire and in generated schema, and an **integer** in SQLite via `enum_val`, taking both wins. For an
ordered `IntEnum` the `enum_val.ord` *is* the member's integer, so the SQL ordinal and the Python
ordinal are one number; for a `StrEnum` it is declaration order and carries no ordering meaning.
marker's `BlockTypes(str, Enum)` with `auto()` serialises as `"1"`, `"2"`
(`marker/marker/schema/__init__.py:4-36`, verified in tree — 31 members, `__str__` returns `.name`,
so any JSON that writes the raw value is garbage). That is unwritable here.

**`enum_val.ord` is append-only for a `StrEnum`.** Declaration order is the stored integer, so a
member may be **appended** and may never be inserted in the middle or reordered: stored rows hold the
integer, and renumbering would silently retype every historical row. A migration regenerating
`enum_val` asserts every existing `(domain, ord, name)` triple is unchanged and fails otherwise.
That assertion is the mechanism behind §15.2's "adding a `Kind` member is a MINOR".

**Unknown-member policy, asymmetric on purpose.** A driver that emits a kind string core does not
recognise gets `Kind.UNKNOWN` with the original string preserved in `raw_kind`, plus a
`Diag(OW_SCHEMA_UNKNOWN_KIND, severity="warning")`. A *reader* that loads a stored row or archive
member carrying a non-`unknown` kind it does not recognise **fails closed** with
`OW_SCHEMA_UNKNOWN_KIND` and does not guess — §15 says how `min_reader` makes that a stated refusal
rather than a surprise.

### 2.2 Identity types

```python
BlockId = NewType("BlockId", int)   # store-local, durable, FK target. NOT in prompts or archives.
Addr    = NewType("Addr", str)      # 'doc' | 'p14/3' | 'p14/3/r2c5'. TYPE-FREE. Archive references.
Cite    = NewType("Cite", str)      # 'd7#412' | 'handbook:d7#412'.  See charter §6.1.
DocKey  = NewType("DocKey", bytes)  # sha256(normalized source bytes)[:16]
```

### 2.3 Geometry

```python
class Quad(NamedTuple):             # 1/1000 pt, TOPLEFT, unrotated page. i32, never float.
    x0:int; y0:int; x1:int; y1:int
    x2:int; y2:int; x3:int; y3:int
    def rect(self) -> tuple[int,int,int,int]: ...      # a VIEW, computed on demand
    @classmethod
    def from_driver(cls, pts: Sequence[tuple[float,float]], *,
                    origin: Literal["topleft","bottomleft"], unit: Literal["pt","px","emu"],
                    page_h: float, dpi: float | None, rotation: int) -> "Quad": ...
```

`from_driver` is the **only** public constructor. There is no way to build a `Quad` from bare
coordinates, which is how normalize-once-at-ingest survives five years of contributors. Integer
fixed point is not fussiness: a float bbox makes `layout_digest` libm- and platform-dependent, which
silently poisons every cache keyed on it.

The i32 range is not a practical constraint. An A4 page is 595.28 × 841.89 pt, so 595,280 × 841,890
in millipoints — four orders of magnitude below `2**31 - 1 = 2,147,483,647`. The largest
representable page is ~2,147,483 pt, or 29,826 inches on a side.

### 2.4 The three coordinate systems

```python
@dataclass(frozen=True, slots=True)
class OriginBytes:    part: str; start: int; length: int; codec: str   # flat text only
@dataclass(frozen=True, slots=True)
class OriginNodePath: part: str; path: tuple[int, ...]                 # OOXML/ODF
@dataclass(frozen=True, slots=True)
class OriginGlyphs:   part: str; extractor: str; start: int; length: int   # PDF text layer
@dataclass(frozen=True, slots=True)
class OriginPixels:   page: int; quad: Quad                    # OCR/VLM: the polygon IS the address
@dataclass(frozen=True, slots=True)
class OriginNone:     pass                                     # derived or synthetic
OriginSpan = OriginBytes | OriginNodePath | OriginGlyphs | OriginPixels | OriginNone

@dataclass(frozen=True, slots=True)
class TextSpan:   a: int; b: int                    # chars in THIS block's own .text
@dataclass(frozen=True, slots=True)
class RenderSpan: view_id: str; a: int; b: int      # view_id = 'md/1/7c3f' -> manifest.views[]

class SpanMap(Protocol):            # emitted BY the serializer that produced the view
    view_id: str
    def block_at(self, offset: int) -> tuple[BlockId, TextSpan] | None: ...
    def is_synthetic(self, offset: int) -> bool: ...
    def offsets_of(self, b: BlockId) -> tuple[int, int]: ...
    def to_text(self, s: RenderSpan) -> list[tuple[BlockId, TextSpan]]: ...

SERIALIZER_CAPS: Mapping[str, bool] = {"md": True, "gfm": True, "html": True,
                                       "text": True, "otsl": True}
```

**Extends the charter, twice, and both are forced by the store.**

- `OriginGlyphs` is `(part, extractor, start, length)`, not `(page, extractor, start, length)`.
  INV-10's glyphs branch re-verifies by *re-extracting that glyph run from a retained part*, so the
  variant must name the part whose `store_ref` the invariant checks; the page is `block.page`, and
  storing it twice would be two names for one fact. The charter's own DDL comment already gives the
  part spelling for this case: `os_part = 'pdf:page=12/content=0'`.
- `SpanMap` gains `is_synthetic()`, and `block_at()` returns `None` rather than raising. §16.5's
  projection law is "every offset lifts to exactly one block **or** is marked synthetic", and a
  three-method Protocol could not express the second half, so the law was unassertable.

The type system refuses to mix the three systems. There is no implicit conversion, no `int` overload
and no `from_offset` helper taking an untagged integer. §7 says why each exists and what a driver
does when it can supply only one.

### 2.5 `Block` — the single node type

```python
@dataclass(frozen=True, slots=True)
class Block:
    id: BlockId; addr: Addr; cite: Cite
    doc_ord: int; gen: int; page: int
    parent: BlockId | None; ord: int
    kind: Kind; raw_kind: str | None; layer: Layer; label: str | None
    text: str | None
    content_digest: bytes; layout_digest: bytes | None; revision: int
    quad: Quad | None
    origin: OriginSpan
    span: TextSpan | None
    producer_id: int
    method: Method                  # NO DEFAULT. State it.
    trust: Trust                    # NO DEFAULT. Absent on the wire => AMBIGUOUS, and COUNTED.
    quote: Quote                    # NO DEFAULT.
    score: float | None = None; score_kind: str | None = None
    origin_operator: str = ""       # OWNERSHIP. Set by the runner from StepResult.
    origin_driver: str = ""; driver_schema_v: int = 0
    restriction_bits: int = 0
    marks: tuple["Mark", ...] = ()
    tombstoned: bool = False
    x: Mapping[str, Any] = MappingProxyType({})       # keys MUST be 'x.<vendor>.<key>'.

@dataclass(frozen=True, slots=True)
class Mark: a: int; b: int; kind: str; value: Any | None = None
```

`x` is a `Mapping`, not a `dict`, and not `field(default_factory=dict)`: a shared mutable default on
the framework's hottest type is a bug waiting for its first author. Because `Block` is frozen,
`content_digest` may be memoised on the instance.

**Field-by-field semantics.** Types are as above; this table says what each field *means* and who is
permitted to write it.

| field | opt | written by | semantics |
|---|---|---|---|
| `id` | no | host | `block_id`. Store-local durable int64 surrogate. **The only FK target for a Block.** Never exported, never shown to a model. |
| `addr` | no | host | Type-free positional path: `doc`, or `p<page>/<step>...` with cells `.../r<r>c<c>`. Unique per `(doc_ord, gen)`. §6.2 gives the grammar. |
| `cite` | no | host | The prompt-safe token, `[<corpus>:]d<doc_ord>#<n>`, `n` from `doc.next_cite_n`. §6.3. |
| `doc_ord` | no | host | Corpus-local document ordinal; the number inside the cite. An ingest numbers its new documents in `unit_uri` order, so the same folder gets the same numbers on any number of workers (D654). |
| `gen` | no | host | The per-document **parse** generation. Bare `gen` means this and only this. |
| `page` | no | driver | The **original** source page index, 0-based. Never a batch index. 0 when `page_kind='stream'`, and 0 by convention on the `document` root, where it carries no meaning. |
| `parent` | yes | host | `NULL` exactly on the one `Kind.DOCUMENT` root per `(doc_ord, gen)`. |
| `ord` | no | host | Position among siblings. **`ord` *is* reading order** — there is no second `position` field. Dense from 0. |
| `kind` | no | driver | Closed vocabulary (§4). |
| `raw_kind` | yes | driver | The producer's own label, kept verbatim (surya's `raw_label`, `surya/README.md:159`; marker's `BlockTypes` name), surviving canonicalisation. Non-NULL whenever the driver's label is not literally the `Kind` wire value. `length(raw_kind) <= 128`, a CHECK. |
| `layer` | no | driver | Role in the reading order (§5). A column, not a second tree. Equal to the parent's unless the block is a page root (M-INV-5). |
| `label` | yes | driver | A human label for a **container**. NULL on text blocks: a chunk is addressed, not named. Renamed from `title` by ADR-1 decision 7, so that `Kind.TITLE` keeps the word. |
| `text` | yes | driver | Plain text, fully resolved, **NFC**. NULL on containers (§4.1 says which). Never contains markup. Never repeats a descendant's text (M-INV-4). |
| `content_digest` | no | host | `ow128`, merkle over content. Geometry is deliberately not an input. §6.4. |
| `layout_digest` | yes | host | `ow128` over `(content_digest, page, quad quantised to whole points)`. NULL iff `quad` is NULL. |
| `revision` | no | host | Incremented by `rebind()` rule 2 (same `addr`+`kind`, changed digest). 0 at first mint. |
| `quad` | yes | driver | Four-corner polygon, topleft, 1/1000 pt, unrotated page. NULL when the driver has no geometry. **Never synthesized** (INV-9). |
| `origin` | no | driver | Tagged union addressing the original container. `OriginNone()` is a real value, not absence. §7.2 gives the column mapping. |
| `span` | yes | driver | `TextSpan` inside **this block's own** `text`. Its meaning is §7.4. |
| `producer_id` | no | runner | FK to `producer`: the reproduction tuple. `Producer` **is** L5's `OperatorIdentity`. |
| `method` | no | runner | The branch that actually ran, from the resolved candidate. |
| `trust` | no | runner | Ordered; clamped by `MAX_TRUST_BY_METHOD` after the driver returns. §8.2. |
| `quote` | no | runner | Ordered; clamped by `MAX_QUOTE_BY_OS_KIND` and by the derive rule; `VERBATIM` additionally re-verified. §8.3. |
| `score`/`score_kind` | yes | driver | Nullable **together** (a CHECK). The scale is named in `tools/scorekinds.toml`; an unregistered `score_kind` raises at `DocSink.add_block`. |
| `origin_operator` | no | runner | Ownership, 2 segments (`parse.pdf`). Who may replace this row. |
| `origin_driver` | no | runner | Ownership, 3 segments (`parse.pdf.pdfium`). |
| `driver_schema_v` | no | runner | The driver's `schema_version` at production time. The only driver version in a cache key. |
| `restriction_bits` | no | runner | 32 reserved licence codes, stamped from the producing card, propagating to every derived item (INV-16). |
| `marks` | no | driver | Sparse inline formatting over `text`. Overlaps are representable. §2.7 also says how they are hydrated. |
| `tombstoned` | no | host | `state = 1`. There is no `DELETE`. |
| `x` | no | anyone | Extension map. Keys **must** match `x\.[a-z0-9_]+\.[a-z0-9_]+`; the vendor segment `ow` is reserved for the framework. Not a digest input. `MAX_X_BYTES` caps `canonical(x)`. |

Two columns are on the `block` table but not on `Block`: `payload` (read through `Doc.payload(id)`,
§4.4) and `decision_id` (cost provenance, read through [the runtime](08-runtime.md)'s
`route_decision`). Both are read through `Doc`, not through the value type, because neither is
meaningful without a join and neither is on the hot path of a render.

**`block` is append-only with exactly one exception, and the exception is named.** There is no
`DELETE` (retirement is `state = 1` plus a `block_history` row) and no `UPDATE` — except the
identity-carrying `UPDATE` that `rebind()` performs inside `end_doc()`'s transaction, which moves a
carried row's `gen` forward. §6.5 gives it statement by statement, because it is the only mutation of
a committed Block anywhere in the framework.

### 2.6 `BlockDraft` — the one mutable type

```python
@dataclass(frozen=True, slots=True)      # Extends the charter: D2 names no cell-position type
class CellPos: r: int; c: int; row_span: int = 1; col_span: int = 1

@dataclass(slots=True)
class BlockDraft:
    """Everything `Block` carries except what the HOST mints -- no `id`, no `addr`, no `cite`, no
    `producer_id`, no `origin_*`, no `restriction_bits`. Mutable on purpose, so an assembler can
    fill fields in the order the source yields them."""
    kind: Kind; layer: Layer; method: Method; trust: Trust; quote: Quote
    parent: BlockId | None = None; text: str | None = None; label: str | None = None
    raw_kind: str | None = None; quad: Quad | None = None
    origin: OriginSpan = OriginNone(); span: TextSpan | None = None
    score: float | None = None; score_kind: str | None = None
    payload: Any | None = None
    cell: CellPos | None = None                     # Extends the charter -- see below
    marks: list[Mark] = field(default_factory=list)
    x: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class CellDraft:                    # what build_grid consumes: a MINTED cell plus its position
    id: BlockId; pos: CellPos
```

`kind`, `layer`, `method`, `trust` and `quote` have **no defaults**. A driver that has not thought
about trust cannot silently ship `EXTRACTED`; it must write `Trust.AMBIGUOUS` and be counted.

**Extends the charter — `BlockDraft.cell`.** A table cell's `addr` step is `r<r>c<c>` (§6.2), so its
grid position must be known at *mint* time, inside `add_block`. But `Grid`'s slots hold `BlockId`s
(`Origin(block: BlockId, ...)`), so `build_grid` — and therefore `add_grid` — necessarily runs
*after* the cells are minted. One optional field on `BlockDraft` closes the loop without adding a
twelfth method to `DocSink`, whose eleven methods are fixed and printed in §2.10.
`cell is not None` implies `kind == Kind.TABLE_CELL` and a `parent` of kind `table`, both asserted
at `add_block`.

### 2.7 Marks

`Mark` is sparse inline formatting over `block.text`, stored in its own table with a **surrogate**
`mark_id` because two links may cover exactly the same range. The kind vocabulary at release 1:

| `mark.kind` | `value` (JSON) | meaning |
|---|---|---|
| `bold`, `italic`, `underline`, `strike`, `sub`, `sup`, `code` | `null` | character formatting |
| `link` | `{"target": "<uri\|addr\|anchor>", "kind": "external"\|"internal"\|"anchor"}` | a hyperlink |
| `math` | `{"notation": "latex"\|"mathml", "src": "..."}` | inline math; **LaTeX without delimiters** |
| `anchor` | `{"name": "...", "akind": "<AnchorKind>"}` | a zero-width definition site; `a == b` |
| `note_ref` | `{"target_addr": "...", "label": "3"}` | a footnote/endnote reference site |
| `dehyphenated` | `{"removed": "­"}` | a soft hyphen or `-\n` folded away; **recoverable** |
| `raw_style` | `{"vendor": "...", "props": {...}}` | a run style the model has no field for, kept |
| `lang` | `{"bcp47": "de-CH"}` | a language run |
| `redaction` | `{"reason": "..."}` | a redacted run; interacts with `restriction_bits` |

Two properties this buys that the mined parsers do not have. Overlapping ranges are representable,
so marker's formatting collapse — one `formats: List[Literal[...]]` per `Span`
(`marker/marker/schema/text/span.py:26-40`), which cannot express bold ending mid-italic — is
**unexpressible** here. And `dehyphenated` makes hyphenation recoverable, so a `REFLOWED` block
renders back to its source line breaking without a second copy of the text.

Storing math as LaTeX **without delimiters** at both block and inline level is anydoc's decision —
`Inline::Math(String)` at `anydoc/src/model/inline.rs:36` and `Block::Math(String)`, documented "a
displayed formula, as LaTeX math without delimiters", at `anydoc/src/model/block.rs:35-37` — and it
is right: delimiters are a rendering choice, and storing them forces every consumer to strip them.

**Mark ranges are half-open char offsets into `block.text`, `0 <= a <= b <= len(text)`**, and a
zero-width mark (`a == b`) is legal and meaningful for `anchor` and `note_ref`. Marks are stored in
`(a, b, kind)` order; §16.1's run-splitting algorithm produces a well-nested render from an
arbitrarily overlapping mark set by splitting runs, never by dropping a mark.

**Marks are hydrated in windows, not per row.** `Block.marks` is a tuple on the value type, but
`Doc.blocks()` iterating 600,000 rows must not issue 600,000 mark queries. The cursor buffers
`MARK_HYDRATE_WINDOW = 512` `block_id`s from the `block_read` scan and issues one
`SELECT ... FROM mark WHERE block_id IN (...) ORDER BY block_id, a, b` per window — 1,172 extra
statements for a 600k-block document instead of 600,000. The window equals
`MAX_SEGMENT_BLOCKS = 512`, so one Segment's blocks are always hydrated in at most two windows.
`Doc.block(id)` hydrates one block's marks directly.

### 2.8 Assets, parts, pages, producers, rels

```python
@dataclass(frozen=True, slots=True)
class Producer:                     # == L5's OperatorIdentity. ONE TYPE, TWO LAYERS.
    operator: str; op_version: int; code_fingerprint: str
    model_id: str | None = None; model_rev: str | None = None    # exact sha; "main" = lint error
    runtime: str | None = None; runtime_version: str | None = None
    prompt_fp: str | None = None; options_digest: bytes = b""

@dataclass(frozen=True, slots=True)          # Extends the charter: named in D2, never defined.
class DocRecord:
    doc_ord: int; doc_key: DocKey; gen: int
    source_sha256: bytes; normalizer: str | None
    uri: str; media_type: str; format: str; format_evidence: Mapping[str, Any]
    source_bytes: int; status: Literal["ok","partial","failed","skipped"]
    page_count: int | None; model_version: str
    declared: "Capabilities"; achieved: "Capabilities"
    confidence: Mapping[str, float | None]; timings_ms: Mapping[str, int]
    x: Mapping[str, Any] = MappingProxyType({})

@dataclass(frozen=True, slots=True)          # Extends the charter.
class PageRecord:
    page: int; page_kind: PageKind; label: str | None
    w_mpt: int | None; h_mpt: int | None; rotation: int
    quad_origin: Literal["topleft","bottomleft"] | None
    method: Method; status: str
    ocr_error_score: float | None = None
    parse_score: float | None = None; layout_score: float | None = None
    table_score: float | None = None; ocr_score: float | None = None
    stats: Mapping[str, Any] = MappingProxyType({})

@dataclass(frozen=True, slots=True)          # Extends the charter.
class AssetDraft:
    media_type: str; sha256: bytes; byte_len: int
    origin_part: str | None = None
    width: int | None = None; height: int | None = None
    licence: str | None = None; licence_url: str | None = None; spdx: str | None = None
    source_url: str | None = None; retrieved_at_ns: int | None = None

@dataclass(frozen=True, slots=True)          # Extends the charter.
class AssetRef:
    asset_id: int; media_type: str; sha256: bytes; byte_len: int
    width: int | None; height: int | None; store_ref: str; restriction_bits: int

@dataclass(frozen=True, slots=True)          # Extends the charter.
class Rel:
    src: BlockId; dst: BlockId; kind: RelKind; producer_id: int
    trust: Trust; score: float | None; score_kind: str | None; origin_operator: str

@dataclass(frozen=True, slots=True)          # Extends the charter.
class Frame:
    lo_page: int; lo_ord: int; hi_page: int; hi_ord: int
    path: str; blocks: int; bytes: int; sha256: bytes
```

`DocRecord.gen` is the generation this record *describes*: the target generation `g_t` while a parse
is running, the committed head afterwards. `DocSink.end_doc()` returns the post-commit value.

**`DocRecord.format` holds a format token, and exactly one token is minted rather than detected.**
The token register is [ingest and routing](05-ingest-and-routing.md) §2.2's and stays there; what
this document owes it is the one entry no detection rule can produce. That token is **`owjob`**, the
format of a **synthetic job document**: one `doc` row per compile job, written by
`omniweave_core.out`'s job runner before `bake` produces its first byte, carrying
`media_type = "application/vnd.omniweave.job+json"`,
`uri = "ow-job://<corpus>/<artifact_slug>/<job_digest>"`, `normalizer = "canonical/1"` (the bytes
were canonical when produced, so normalising them is the identity — **not** `NULL`, which means the
normaliser threw), `status = "ok"`, `page_count = NULL`, and the bake's provenance in
`format_evidence` and `x`. [Generation](09-generation.md) §7.1 is the sole home of the full column
list, of the `doc_key` recipe that makes an identical re-run the same document, and of the deletion
refusal that guards it. It exists because `asset.doc_ord` is `NOT NULL` (§11) and a compile-produced
asset has no ingested document to belong to. `WHERE format = 'owjob'` is the exhaustive selector for
synthetic documents and **no `doc.origin` column is added**
([ADR-12](adr/0012-runtime-types-on-the-critical-path.md)). A job document carries **zero `block`
rows**, so it has no `cite`, no projection and no `rebind()` work, and nothing in §6, §16 or §17
ever sees one.

`w_mpt`/`h_mpt` are NULL exactly when `page_kind == STREAM`. `page.method` is the branch that ran on
**that page**, which is what makes per-page escalation (INV-13) auditable: a 400-page PDF with three
OCR'd pages has three rows at `method='ocr_page'` and 397 at `method='text_layer'`.

`page.table_score` is **computed from that page's `table_meta.recon_score` values, or it is NULL and
excluded from the mean.** Verified in tree: docling declares `table_score: ScoreValue = np.nan` per
page (`docling/docling/datamodel/base_models.py:419`) and never assigns it anywhere, so
`docling/docling/pipeline/standard_pdf_pipeline.py:867-871`'s `nanmean` runs over an all-NaN list and
its published grade is a three-component mean wearing four. §8.6 implements the corrected form.

### 2.9 Capabilities

```python
@dataclass(frozen=True, slots=True)
class Capabilities:
    spatial:       Literal["none","page_bbox","block_bbox","line_bbox","char_bbox"]
    origin_span:   Literal["none","normalized","exact"]    # gates INV-10. ORDERED.
    text_span:     bool
    marks:         bool
    reading_order: Literal["raster","learned","model_emitted","char_stream","source"]  # ORDERED
    sections:      Literal["none","markdown_only","outline_from_source","typed_levels"]
    tables:        Literal["none","flat_html","cells","cells_with_spans"]
    math:          frozenset[str]                          # A SET: {} | {latex} | {latex,mathml}
    assets:        Literal["none","refs","bytes"]; asset_origin: bool
    notes:         Literal["none","inline","linked"]
    confidence:    Literal["none","document","page","element"]
    furniture:     Literal["destroyed","flagged","separated"]
    round_trip:    Literal["none","text","structure","passthrough"]
    forfeits:      frozenset[str] = frozenset()
```

Fifteen fields — and this dataclass, `driver.toml [capability.parse]`, `doc.declared` and
`doc.achieved` are **the same fifteen fields**. `spanmap` is not among them: a `SpanMap` is emitted by
core's own serializer over core's own five formats, which a parse driver never calls, so the field
had no writer and nothing for the conform `capability` suite to assert. That fact lives in
`SERIALIZER_CAPS`.

`reading_order` is ordered `raster < learned < model_emitted < char_stream < source`, justified by
marker's own measurement — "it beats learned reading-order models on multi-column pages
(olmocr-bench order tests: 75% vs 56%)", `marker/marker/builders/line.py:77-84`, where
`use_pdftext_reading_order` defaults to `True` — and by native formats carrying a canonical order.
`math` is a **set**, not a ladder: latex versus mathml is a notation choice, not a quality rung.

`declared` is the card's claim, copied onto `doc` at parse time. `achieved` is what the driver
actually delivered **on this document**, and it may be lower, never higher. **Serve reads
`achieved`** (charter §5 X9) — a card cannot know what a particular PDF permitted.

**`achieved` is computed by the host from the committed rows, not reported by the driver.** That is
INV-7 at the capability grain, and it is a mechanism, so here it is field by field, evaluated over
`gen = g_t` at `end_doc`:

| field | derived from |
|---|---|
| `spatial` | the finest granularity of any non-NULL `quad`: `none` if none, else `block_bbox`, raised to `line_bbox`/`char_bbox` only when the driver's declaration says so *and* quads exist (line and char grain are not distinguishable from a quad alone) |
| `origin_span` | the weakest `os_kind` over body blocks: any `none` ⇒ `none`; else `exact` if every non-`pixels` block's branch re-verifies on the conformance sample, `normalized` otherwise; `pixels`-only ⇒ `none` |
| `text_span` | `EXISTS(SELECT 1 FROM block WHERE ts_a IS NOT NULL ...)` |
| `marks` | `EXISTS(SELECT 1 FROM mark ...)` |
| `tables` | `none` if no `table` block; `cells_with_spans` if any `cell` has a span > 1; `cells` otherwise |
| `math` | the set of `payload.notation` values on `formula` blocks unioned with `mark.value.notation` on `math` marks |
| `assets` | `none`, `refs` (rows with `store_ref` pointing at bytes we did not retain), `bytes` |
| `asset_origin` | `EXISTS(SELECT 1 FROM asset WHERE origin_part IS NOT NULL ...)` |
| `notes` | `none` if no `layer = note` block; `linked` if every note body has an inbound `rel(note_ref)`; `inline` otherwise |
| `confidence` | the finest grain at which a score is non-NULL: `element` (any `block.score`), `page` (any `page.*_score`), `document`, `none` |
| `furniture` | `destroyed` if every block is `layer = body`; else the driver's declaration clamped to `flagged`/`separated` |
| `sections` | `typed_levels` if any `section` block exists; else the declaration clamped to at most `outline_from_source` |
| `reading_order`, `round_trip` | the declaration, clamped by `declared`. Neither is observable from rows, which is stated rather than papered over: they are the two fields `achieved` cannot independently check, and the conform `capability` suite is what tests them. |
| `forfeits` | the declaration, unioned with anything the derivations above proved absent |

### 2.10 `DocSink` — the eleven write methods

`DocSink` is the L2 write boundary and one of the four store Protocols;
[storage and retrieval](07-store-and-retrieval.md) §1.1 prices that boundary at **33 methods**
(`Store` 4, `Reader` 6, `DocSink` 11, `GraphSink` 12) and delegates these eleven here, because every
type they take is defined above and every rule they enforce is a rule of this document.
`GraphSink`'s twelve are [structure extraction](06-structure-extraction.md) §1.7's.

```python
class DocSink(Protocol):
    """HOST-SIDE. Never handed to a driver, never reachable from `DriverIO` (charter §5 X1). A
    `parse/1` driver emits `owdoc-fragment/1` addressing blocks by a per-invocation `tmp` id; the
    host decodes it and drives this. That is what makes INV-6 and INV-7 structural rather than
    reviewed, and what makes a fragment portable between stores."""

    def begin_doc(self, rec: "DocRecord") -> "DocRecord": ...
    def begin_page(self, page: "PageRecord") -> None: ...
    def add_block(self, b: "BlockDraft") -> BlockId: ...
    def add_marks(self, b: BlockId, marks: Sequence[Mark]) -> None: ...
    def add_grid(self, b: BlockId, g: "Grid") -> None: ...
    def add_rel(self, src: BlockId, dst: BlockId, kind: RelKind, *, trust: Trust,
                score: float | None = None, score_kind: str | None = None) -> None: ...
    def add_asset(self, a: "AssetDraft", blob: BinaryIO) -> int: ...
    def add_part(self, path: str, blob: BinaryIO | None,
                 sha256: bytes, byte_len: int) -> None: ...
    def diag(self, d: Diag) -> None: ...
    def end_page(self, stats: Mapping[str, Any]) -> None: ...
    def end_doc(self, status: str) -> "DocRecord": ...
```

**Eleven, and the count is fixed.** §2.6's `BlockDraft.cell` exists precisely so a cell's grid
position can reach `add_block` without a twelfth method. A twelfth re-prices 07 §1.2's T3 Postgres
swap and widens the only boundary a second backend has to reimplement, so adding one is an ADR, not
a patch. The method is spelled `diag`, not `add_diag` — the charter's spelling and §1.1's, kept
because one concept gets one name in every document.

| method | called | what it mints, stamps or enforces | specified in |
|---|---|---|---|
| `begin_doc` | once, first | inserts or looks up `doc` by `doc_key`; assigns `doc_ord` on first sight, the number the ingest reserved for it in `unit_uri` order before any parse settled (D654); fixes `g_t = doc.gen + 1`; copies `declared` onto `doc` | §1.1, §2.8, §2.9 |
| `begin_page` | once per page | inserts the `page` row at `(doc_ord, g_t, page)`; resets the page-root ordinal counter | §1.1, §2.8, §12.5 |
| `add_block` | once per block | `block_id`, `addr`, `cite` from `doc.next_cite_n`, `ord`, `producer_id`, `origin_operator`, `origin_driver`, `driver_schema_v`, `restriction_bits`, a provisional `content_digest` and `layout_digest`; applies `MAX_TRUST_BY_METHOD` and `MAX_QUOTE_BY_OS_KIND`; validates the kind's `payload` schema, the `score_kind` register, `layer` inheritance and the `cell`/`table_cell` pair. Returns the id | §2.5, §2.6, §4.4, §5, §6.1-§6.4, §8.2, §8.3, §8.4 |
| `add_marks` | at most once per block | `mark_id` surrogates in `(a, b, kind)` order; asserts `0 <= a <= b <= len(text)` | §2.7 |
| `add_grid` | once per table, in the transaction of its **last** page | `table_meta`, `cell`, and `grid_slot` only when `has_merges = 1`; asserts row-major cell arrival and charges `MAX_EXPANSION` | §10.1, §10.2, §12.3 |
| `add_rel` | zero or more per ordered pair | `producer_id` and `origin_operator`; clamps `trust`; rejects anything outside the closed seven-member `RelKind`; `UNIQUE (src_id, dst_id, kind, producer_id)` | §2.1, §2.8, §13.1 |
| `add_asset` | zero or more per document | hashes the stream itself (`OW_ASSET_DIGEST_MISMATCH` on disagreement), writes `store_ref`, dedups on `(doc_ord, sha256, IFNULL(origin_part,''))`, stamps `restriction_bits`. Returns `asset_id` | §11 |
| `add_part` | zero or more per document | the `part` row at `(doc_ord, path)`; `store_ref` non-NULL iff the bytes were retained | §7.2, §13.1 |
| `diag` | zero or more | a `diag` row inside the **current page's** transaction, so a diagnostic about page 3,000 survives a crash at page 3,001 | §9 |
| `end_page` | once per page | **commits one transaction.** Rows are durable and invisible while `g_t > doc.gen` | §1.1, §12.3 |
| `end_doc` | once, last | the closure pass, `owcheck` over `g_t`, `rebind(store, doc_ord, g_t)`, `achieved` and `doc.confidence` computed from the committed rows, and iff not quarantined `UPDATE doc SET gen = g_t`. Returns the post-commit `DocRecord` | §1.1, §2.8, §2.9, §6.4, §6.5, §8.6 |

**`DocSink.add_part` is the sole inserter of an L2 `part` row.** `op.identify` writes
`unit.part_count` and the per-part `work` rows and **never** a `part` row; charter D6's "part rows are
materialised by `op.identify`" is the overloaded phrase — its own module tree glosses the same step as
"part-row expansion", one `work` row per part keyed `(unit_uri, unit_part, operator, op_version)` —
and erratum `E53` retires it. Three facts force the reading, in ascending order of finality.
(1) `part.sha256 BLOB NOT NULL` and `part.byte_len INTEGER NOT NULL` (§13.1): `op.identify` does not
read bytes, so it can supply neither, and a NULL-tolerant variant is a DDL change to a charter table.
(2) `part.doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord)`, and `doc_ord` is assigned by `begin_doc`
on first sight, while `op.identify` runs at hop 4 of
[the architecture](02-architecture.md) §4.1's worked trace, before any parse — on a first-sight
document there is no `doc_ord` for the foreign key to name. (3) L2 has one writer: these eleven
methods own it, `add_part` is one of them, and the retention policy is in its signature.

**`add_part`'s `blob` is nullable, and that nullability *is* the retention policy in the signature.**
`[store] retain_parts` decides whether a part's bytes reach CAS; `blob = None` records the part's
`path`, `sha256` and `byte_len` with `store_ref` NULL, which is exactly what §13.1's DDL comment
means by "NULL => bytes were not retained". The digest and length are required either way, so the
`glyphs` branch of INV-10 and `VERBATIM`'s re-verification can name *which* part they could not read
instead of failing without an explanation (§8.3).

**Extends the charter, twice, and both are forced by rules stated above.**

- `begin_doc` returns a `DocRecord` rather than `None`. §1.1 makes `begin_doc` the step that assigns
  `doc_ord` and fixes `g_t`, and `DocRecord` is frozen, so a caller's record cannot carry either
  value on first sight. The returned record is the resolved one — `doc_ord` assigned, `gen = g_t` —
  which is the same shape as `end_doc`, whose return is the record at the committed head (§2.8).
- `add_rel` takes `score_kind` beside `score`. `Rel` carries both (§2.8) and the `rel` table has
  both columns (§13.1), so a signature with only `score` leaves `rel.score_kind` unwritable and a
  scored `rel` unresolvable against `tools/scorekinds.toml`. The two are nullable **together**,
  the same rule `Block` obeys (§8.4).

Both are recorded in §18 as Q11, because the divergence is in the charter's printed listing rather
than in this document's reading of it.

## 3. The language-neutral schema

The Python definitions are the source of truth; `schema.json` is **generated** from them by
`ow schema emit`, committed, and byte-diff gated so its diff appears in review. A second-language
reader (a Rust or TypeScript `.owdoc` reader, the JSON-Schema-validating conformance kit) reads
`schema.json` and `tools/wirekeys.toml`, never the Python.

### 3.1 The wire record

**Archive records** — the `.owdoc` container's `blocks.ndjson` — use short, frozen keys. This is
protobuf's field-number discipline with no toolchain: a key is never reused with a different
meaning, and CI diffs `tools/wirekeys.toml`. **`owdoc-fragment/1` is a different wire and uses
long, spelled-out keys**, because it is authored by a third party rather than generated: its
records are discriminated by `t ∈ {doc, part, page, block, asset, block_asset, diag}` and a
block's text is `text`, addressed by a per-invocation `tmp` id with no `addr`, no `cite` and no
producer index. [The driver system](04-driver-system.md) §9 Step 3 prints the record shapes; the
two key sets are deliberately disjoint in spelling so that a record cannot be misread as the other
format, and `t` meaning **text** here and **type** there is the one collision that makes the rule
worth stating.

| key | field | JSON type | notes |
|---|---|---|---|
| `i` | `addr` | string | the block's own identity **in the archive**; there is no `block_id` here |
| `c` | `cite` | string | unqualified form; durable across generations |
| `p` | `page` | integer | |
| `pa` | parent `addr` | string \| null | null only on the `document` root |
| `o` | `ord` | integer | |
| `k` | `kind` | string | the lower-case member name |
| `rk` | `raw_kind` | string \| null | |
| `ly` | `layer` | string | |
| `lb` | `label` | string \| null | renamed with the column (ADR-1 decision 7); `ti` was never released |
| `t` | `text` | string \| null | NFC |
| `ts` | `TextSpan` | `[int,int]` \| null | a half-open **range** `[a, b)` |
| `os` | `OriginSpan` | object | `{"k": "bytes"\|"nodepath"\|"glyphs"\|"pixels"\|"none", ...}` |
| `q` | `quad` | 8 ints \| null | i32, topleft, 1/1000 pt |
| `m` | `marks` | array of `[a,b,kind,value]` | |
| `qt` | `quote` | string | |
| `tr` | `trust` | string | |
| `mt` | `method` | string | |
| `sc` | `score` | `[number, string]` \| null | `[score, score_kind]`, both or neither |
| `pd` | producer | integer | index into `manifest.producers[]` |
| `oo` | `origin_operator` | string | |
| `od` | driver | `[string, int]` | `[origin_driver, driver_schema_v]` |
| `cd` | `content_digest` | string | 32 hex chars (a 16-byte `ow128`) |
| `ld` | `layout_digest` | string \| null | 32 hex chars |
| `rm` | `revision` | integer | |
| `rb` | `restriction_bits` | integer | |
| `st` | `state` | integer | 0 live, 1 tombstone |
| `dc` | `decision_id` | string \| null | cost provenance |
| `pl` | `payload` | object \| null | kind-discriminated (§4.4) |
| `x` | extension map | object | `x.<vendor>.<key>` only |

**Inside `os`, an offset pair is `(a, len)`, not `(a, b)`, and it is spelled differently on purpose.**
The `bytes` and `glyphs` variants carry `"a"` (a start) and `"len"` (a length), because that is what
the charter's `os_a`/`os_b` columns hold ("`(start, len)` for bytes / glyphs"). `ts` carries a
half-open range. Two different quantities never share a letter: reusing `b` for a length in one
object and an end offset in another is the exact class of bug that costs a week.

**Extends the charter, and the erratum is written.** D2 froze twenty-two keys
(`{i,p,pa,o,k,rk,ly,t,ts,os,q,m,tr,sc,pd,od,oo,cd,ld,rb,rm,x}`) at charter `:1597`; erratum `E52`
supersedes that set, names this table as the mapping's sole home, and leaves frozen-ness and
never-reuse untouched. A complete Block additionally needs `c`, `qt`, `mt`, `lb`, `pl`, `st` and `dc`;
without `c` a `cite` would not survive `import(export(store)) == store` over the fixture corpus,
because a cite is durable and cannot be re-minted on import — that round-trip check's fixture is what
fails if the append is dropped, and it is cited here by property rather than by gate number. The seven
are appended here and `tools/wirekeys.toml` at `model_version = "1.1"` holds all twenty-nine; the
charter already stamps `model_version = "1.1"` on `meta` at `:969`, so the version is not moved, only
made consistent with the key count it implies.

**This is an append, not a break.** `tools/wirekeys.toml` is one of the six append-only registers
protected by squash-only merges and branch-up-to-date ([repo layout](11-repo-layout.md) §5.2, §8.3),
so adding rows is the legal operation and the diff is computable against the previous tag. A key is
still never reused with a different meaning, and retirement still runs §15.4's three phases into the
file's `retired` table.

### 3.2 Generated JSON Schema (abridged to the shape that matters)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://omniweave.dev/schema/owdoc/1.1/block.json",
  "title": "owdoc Block wire record",
  "type": "object",
  "additionalProperties": false,
  "required": ["i","c","p","pa","o","k","ly","t","os","qt","tr","mt","pd","oo","od","cd","rm","rb","st"],
  "properties": {
    "i":  {"type": "string", "maxLength": 512,
           "pattern": "^(doc|p[0-9]+(/[0-9]+)+(/r[0-9]+c[0-9]+(/[0-9]+)*)*)$"},
    "c":  {"type": "string", "pattern": "^(?:[a-z0-9][a-z0-9_-]{0,31}:)?d[0-9]+#[0-9]+$"},
    "p":  {"type": "integer", "minimum": 0},
    "pa": {"type": ["string","null"], "maxLength": 512,
           "pattern": "^(doc|p[0-9]+(/[0-9]+)+(/r[0-9]+c[0-9]+(/[0-9]+)*)*)$"},
    "o":  {"type": "integer", "minimum": 0},
    "k":  {"enum": ["document","section","title","heading","paragraph","list","list_item",
                    "blockquote","code","table","table_cell","figure","picture","caption",
                    "formula","rule","page_header","page_footer","footnote","endnote",
                    "speaker_note","comment","form","form_field","checkbox","key_value",
                    "toc","toc_entry","reference","bibliography","handwriting","chemical",
                    "diagram","container","unknown"]},
    "rk": {"type": ["string","null"], "maxLength": 128},
    "ly": {"enum": ["body","furniture","note","annotation","hidden"]},
    "lb": {"type": ["string","null"], "maxLength": 1024},
    "t":  {"type": ["string","null"], "maxLength": 1048576},
    "ts": {"type": ["array","null"], "items": {"type":"integer","minimum":0},
           "minItems": 2, "maxItems": 2},
    "os": {"oneOf": [
      {"type":"object","additionalProperties":false,
       "required":["k","part","a","len","codec"],
       "properties":{"k":{"const":"bytes"},"part":{"type":"string","maxLength":1024},
                     "a":{"type":"integer","minimum":0},"len":{"type":"integer","minimum":0},
                     "codec":{"type":"string","pattern":"^[a-z0-9_.-]+/[a-z]+$"}}},
      {"type":"object","additionalProperties":false,
       "required":["k","part","path"],
       "properties":{"k":{"const":"nodepath"},"part":{"type":"string","maxLength":1024},
                     "path":{"type":"array","items":{"type":"integer","minimum":0},
                             "minItems":1,"maxItems":64}}},
      {"type":"object","additionalProperties":false,
       "required":["k","part","extractor","a","len"],
       "properties":{"k":{"const":"glyphs"},"part":{"type":"string","maxLength":1024},
                     "extractor":{"type":"string","pattern":"^[a-z0-9_.-]+@[0-9A-Za-z.+-]+$"},
                     "a":{"type":"integer","minimum":0},"len":{"type":"integer","minimum":0}}},
      {"type":"object","additionalProperties":false,
       "required":["k"],"properties":{"k":{"const":"pixels"}}},
      {"type":"object","additionalProperties":false,
       "required":["k"],"properties":{"k":{"const":"none"}}}
    ]},
    "q":  {"type": ["array","null"], "items": {"type":"integer"}, "minItems":8, "maxItems":8},
    "m":  {"type":"array","maxItems":4096,
           "items":{"type":"array","minItems":4,"maxItems":4,
                    "prefixItems":[{"type":"integer","minimum":0},{"type":"integer","minimum":0},
                                   {"type":"string","maxLength":32},{}]}},
    "qt": {"enum": ["synthetic","reconstructed","reflowed","normalized","verbatim"]},
    "tr": {"enum": ["ambiguous","inferred","extracted"]},
    "mt": {"enum": ["native","text_layer","native_xml","ocr_page","ocr_block","vlm_page",
                    "llm","heuristic","roundtrip","user"]},
    "sc": {"type": ["array","null"], "minItems": 2, "maxItems": 2,
           "prefixItems": [{"type":"number"},{"type":"string"}]},
    "pd": {"type": "integer", "minimum": 0},
    "oo": {"type": "string", "pattern": "^[a-z0-9_]+\\.[a-z0-9_]+$"},
    "od": {"type": "array", "minItems": 2, "maxItems": 2,
           "prefixItems": [{"type":"string","pattern":"^[a-z0-9_]+(\\.[a-z0-9_]+){2}$"},
                           {"type":"integer","minimum":1}]},
    "cd": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
    "ld": {"type": ["string","null"], "pattern": "^[0-9a-f]{32}$"},
    "rm": {"type": "integer", "minimum": 0},
    "rb": {"type": "integer", "minimum": 0},
    "st": {"enum": [0, 1]},
    "dc": {"type": ["string","null"], "maxLength": 64},
    "pl": {"type": ["object","null"]},
    "x":  {"type": "object", "propertyNames": {"pattern": "^x\\.[a-z0-9_]+\\.[a-z0-9_]+$"}}
  }
}
```

**The `pixels` variant carries neither a page nor a quad on the wire, and that is not an omission.**
The polygon *is* the address, and the polygon is already `q`; the page is already `p`. Emitting them
twice would create two facts that can disagree, and the store has nowhere to put a second quad — the
charter's `block` DDL has `os_kind`, `os_part`, `os_a`, `os_b`, `os_path`, `os_extractor` and
`os_codec`, and no `os_quad`. The reader materialises `OriginPixels(page=p, quad=q)` from the row it
is already holding, and `os_kind = 'pixels' IMPLIES quad IS NOT NULL` is a CHECK (§7.2).

**Cross-field constraints JSON Schema cannot express**, asserted by the reader, by `owcheck` and by
the conformance kit (§17):

- `ts` non-null implies `t` non-null and `0 <= ts[0] <= ts[1] <= len(t)`.
- `ld` non-null iff `q` non-null.
- `sc` is null or a two-tuple whose second element is a registered `score_kind`.
- `qt == "verbatim"` implies `os.k` in `{bytes, nodepath, glyphs}` **and** that the named `part` has a
  non-NULL `store_ref`.
- `os.k == "pixels"` implies `q` non-null; `os.k == "none"` implies `qt <= "normalized"` (§8.3).
- `pa == null` iff `k == "document"`; `i == "doc"` iff `k == "document"`.
- `i`'s page component equals `p` for every block whose parent chain reaches the root without
  changing page (M-INV-2).
- every mark satisfies `0 <= a <= b <= len(t)`.
- `ly` equals the parent record's `ly` unless this block's parent is the `document` root (M-INV-5).
- `k == "table_cell"` implies `i` ends in a `r<r>c<c>` step and the parent's `k == "table"`.

**The permitted JSON Schema subset is closed.** The framework ships a ~200-line validator for
`type`, `enum`, `required`, `additionalProperties: false`, `minimum`/`maximum`,
`minItems`/`maxItems`, `pattern`, `maxLength`, `prefixItems`, `oneOf` over a discriminated `const`,
`propertyNames.pattern` and nullable leaves — in `omniweave` and `omniweave-conform`, off the hot
path. That same validator serves the driver-card `[config]` schema, the per-kind `payload` schemas of
§4.4, and L3's prompt kit. A general JSON Schema library solves a problem omniweave does not have and
would breach INV-2.

## 4. The closed block-type vocabulary

### 4.1 The vocabulary, and what each member obliges

Thirty-four members plus `UNKNOWN`. "Text" says whether `block.text` is non-NULL; "Children" says
what may hang under it; "Payload" names the §4.4 payload schema when one is required.

| `Kind` | text | children | payload | semantics and the discriminating rule |
|---|---|---|---|---|
| `document` | NULL | page roots | — | Exactly one per `(doc_ord, gen)`, `parent IS NULL`, `addr = 'doc'`. Its `content_digest` is the document merkle root and is the `root content_digest` column of `omniweave.index.lock`. |
| `section` | NULL | any body | `section` | An **explicit** typed section from the source (EPUB nav, DITA topic, OOXML outline level). Emitted only when `Capabilities.sections == "typed_levels"`. Where absent, the hierarchy is derived into `block_sec` from `heading` blocks; §12.4. |
| `title` | yes | none | — | The document or slide title. At most one per page root. Distinct from `heading` because a title has no level. |
| `heading` | yes | none | `heading` | A numbered outline entry. `payload.level` is 1-based; `payload.anchor` is its own anchor name when the source carries one. |
| `paragraph` | yes | none | — | The default text block. |
| `list` | NULL | `list_item` | `list` | Carries `ordered`, `start`, `marker_style`, `nesting_level`. |
| `list_item` | yes | `list`, `paragraph`, `table` | — | `text` is the item's own first-level text. A child `paragraph` carries **additional** prose, never a copy of `text` (M-INV-4). |
| `blockquote` | NULL | any body | — | Quoted prose. Renamed from `QUOTE`: a block kind and a quotability tier must not share a word in a framework whose central promise is about quoting (charter §5 X17). |
| `code` | yes | none | `code` | `payload.lang`, `payload.fenced`. Whitespace is **never** normalised; `quote` may be `VERBATIM`. |
| `table` | NULL | `table_cell` | — | The grid lives in `table_meta`/`cell`/`grid_slot`, not in the payload. §10. |
| `table_cell` | yes | any body | — | **A cell is an ordinary Block.** Its `(r, c, row_span, col_span)` live in `cell`; its `addr` step is `r<r>c<c>`. |
| `figure` | NULL | `picture`, `caption`, any body | — | A composite figure region. |
| `picture` | NULL | none | `picture` | A raster or vector image. Bytes are in `asset` via `block_asset`; `payload` carries `alt` and `role`. |
| `caption` | yes | none | — | Attaches to its subject through `rel(caption_of)`, never by adjacency. |
| `formula` | yes | none | `formula` | Display math. `text` is the LaTeX **without delimiters**; `payload.mathml` when available. |
| `rule` | NULL | none | — | A horizontal rule / section break. Kept because it is load-bearing for reconstruction. |
| `page_header` | yes | none | — | `layer = furniture` by default. |
| `page_footer` | yes | none | — | `layer = furniture` by default. |
| `footnote` | yes | any body | `note` | A note **body** at the page foot. `layer = note`. Its reference site is a `note_ref` mark plus `rel(note_ref)`. |
| `endnote` | yes | any body | `note` | A note body collected at the document end. `layer = note`. |
| `speaker_note` | yes | any body | — | A PPTX notes slide. `layer = note`. Never in the body render. |
| `comment` | yes | any body | `comment` | A review comment (`w:comment`, a PDF annotation). `layer = annotation`. Carries author and timestamp. |
| `form` | NULL | `form_field`, `checkbox` | — | An AcroForm / XFA / OOXML content-control group. |
| `form_field` | yes | none | `form_field` | `payload` carries `name`, `field_type`, `value`, `readonly`, `required`. |
| `checkbox` | NULL | none | `checkbox` | `payload.checked: bool`. A separate kind because docling separates `CHECKBOX_SELECTED`/`CHECKBOX_UNSELECTED` and a boolean is not a label. |
| `key_value` | NULL | exactly 2 | `key_value` | A key/value region. Children are ordered `[key, value]`; both are ordinary text blocks. |
| `toc` | NULL | `toc_entry` | — | A table-of-contents region as printed. |
| `toc_entry` | yes | none | `toc_entry` | `payload` carries `level`, `target_anchor`, `printed_page`. |
| `reference` | yes | none | `reference` | One bibliography entry. `payload.citekey` when the source has one. |
| `bibliography` | NULL | `reference` | — | The container. |
| `handwriting` | yes | none | — | Handwritten text. Never `EXTRACTED`: a handwriting recogniser is `Method.OCR_*` or `VLM_PAGE` and is clamped to `INFERRED`. |
| `chemical` | yes | none | `chemical` | A chemical structure. `text` is SMILES/InChI when produced; `payload.notation` names which. |
| `diagram` | NULL | any body | — | A structured drawing (flowchart, org chart) whose internals were recovered as blocks. |
| `container` | NULL | any | `container` | A grouping with **no** semantics: a text box, a multi-column region, an SVG group, marker's `*Group` types. `payload.role` records why it exists. |
| `unknown` | either | any | — | Forward compatibility. `raw_kind` is mandatory and non-empty. |

**M-INV-4 (no text is stored twice).** A Block's `text` never repeats any descendant's `text`. This
matters because §16.1's traversal renders a block's own `text` **and then** its children in `ord`
order: a `list_item` whose `text` is also a child `paragraph`'s `text` renders twice, and worse, is
two citable blocks quoting one sentence. The three kinds where the hole is reachable — `list_item`,
`table_cell`, `footnote`/`endnote`/`comment` — carry the rule explicitly above, and P5 asserts the
cheap half of it (no child `paragraph` whose `normalize_k(text)[0]` equals its parent's).

### 4.2 The rule for adding a member

Adding a `Kind` member is a **`model_version` MINOR bump with a `min_reader` raise** (§15.2), an
**append** to the enum's declaration order (§2.1), and it is reviewed against four questions in this
order. All four must answer yes.

1. **Does a consumer branch on it?** Name the branch: a serializer rule, an OUT ConstructTable row,
   a retrieval filter, a segmenter atom rule, or an absence gate. A kind nothing branches on is a
   `raw_kind` string on an existing kind, and `raw_kind` is kept precisely so this is cheap.
2. **Is it a *kind*, not a *state*?** `Layer`, `Trust`, `Quote`, `restriction_bits` and `payload`
   already carry state. `HiddenParagraph` is `paragraph` + `layer=hidden`.
3. **Does at least one shipped driver populate it, with a fixture?** A speculative kind is dead
   vocabulary that every reader must nonetheless fail closed on.
4. **Is there no existing member it collapses into without loss?** "Loses" means a downstream
   consumer would have to re-infer the distinction with a heuristic.

Removing a member is a `model_version` MAJOR and follows §15.4's deprecation policy. The wire value
and the `enum_val.ord` are never reused.

### 4.3 Against marker and docling, member by member

**marker.** `marker/marker/schema/__init__.py:4-36` defines `BlockTypes(str, Enum)` with **31**
members, verified in tree: 22 concrete leaf blocks, 4 groups (`FigureGroup`, `TableGroup`,
`ListGroup`, `PictureGroup`), 3 text primitives (`Line`, `Span`, `Char`) and 2 structural (`Page`,
`Document`).

| marker | owdoc | why |
|---|---|---|
| `Text` | `paragraph` | |
| `SectionHeader` | `heading` + `payload.level` | marker keeps `heading_level` on the block; we keep it in the payload so promoting a paragraph to a heading does not change the field set. |
| `Table`, `TableCell` | `table`, `table_cell` | marker's `TableCell` carries `row_id`/`col_id`/`rowspan`/`colspan` on the block; we move them to `cell` so a cell stays an ordinary Block. |
| `ListItem` | `list_item` under a `list` | marker has `ListGroup` but **no `List` leaf** (verified: the 31 members contain no `List`); we require the container so `ordered`/`start` have a home. |
| `Figure`, `Picture`, `FigureGroup`, `PictureGroup` | `figure`, `picture` | The four collapse to two. A group whose only job is to hold a figure and its caption **is** `figure`; the `rel(caption_of)` edge carries the association explicitly rather than by containment. |
| `Caption` | `caption` | |
| `Code` | `code` | |
| `Equation`, `TextInlineMath` | `formula` (block) / a `math` **mark** (inline) | marker makes inline math a block type. Inline math is inline: it is a mark over the paragraph's text, which is what keeps the paragraph's text one string and the span arithmetic sound. |
| `PageHeader`, `PageFooter` | `page_header`, `page_footer` at `layer=furniture` | |
| `Footnote` | `footnote` at `layer=note` | |
| `Form` | `form` + `form_field` | marker has no field-level type; `Form` is one opaque block. |
| `TableOfContents` | `toc` + `toc_entry` | Same reason: marker's TOC is one block, so no consumer can resolve an entry to its target. |
| `Reference`, `Bibliography` | `reference`, `bibliography` | |
| `Handwriting` | `handwriting` | |
| `ChemicalBlock` | `chemical` | |
| `Diagram` | `diagram` | |
| `ComplexRegion` | `container` + `raw_kind="ComplexRegion"` | "Complex region" is a confession, not a type. It becomes an unsemantic container and the original label survives in `raw_kind`. |
| `ListGroup`, `TableGroup` | `container`, or the natural parent | |
| `Page` | the `page` **table** | A page is a coordinate frame with a size, a rotation, a label and four scores. Modelling it as a block would put `w_mpt` on `Block`. |
| `Document` | `document` | Kept, as the merkle root. |
| `Line`, `Span`, `Char` | **excluded** | See below. |

**`Line`, `Span` and `Char` are deliberately not block kinds.** marker needs them because its
polygons and its `text_extraction_method` live on them. omniweave gets the same three capabilities
without a sub-block node type: character-level geometry is `Capabilities.spatial = "char_bbox"`,
declared per driver and delivered as an `OriginGlyphs` range that re-extracts on demand; inline
style is a `Mark`; line breaking is recoverable from `dehyphenated` marks plus the block quad. The
cost of the alternative is decisive: a 5,000-page document at 60-120 blocks per page is 300k-600k
Blocks; at line granularity it is 5-10M and at span granularity 30M+, and every one of them would
carry a `cite`, a `content_digest` and six provenance columns.

**docling.** `DoclingDocument` partitions content into four parallel lists (`texts`, `tables`,
`pictures`, `key_value_items`) with **JSON-pointer identity** (`#/texts/1`) and two trees
(`body`, `furniture`) plus `groups` (`docling/docs/concepts/docling_document.md:23-41`). Its label
vocabulary, `DocItemLabel`, is used across the codebase with 20 members: `CAPTION CHECKBOX_SELECTED
CHECKBOX_UNSELECTED CODE DOCUMENT_INDEX FOOTNOTE FORM FORMULA KEY_VALUE_REGION LIST_ITEM MARKER
PAGE_FOOTER PAGE_HEADER PARAGRAPH PICTURE REFERENCE SECTION_HEADER TABLE TEXT TITLE`. The enum
itself lives in `docling-core`, which is not vendored here, so the count is over call sites, not the
declaration.

| docling | owdoc | why |
|---|---|---|
| four type-partitioned lists + `#/texts/1` | one `block` table + `block_id` | **A position inside an identity is exactly what `rebind()` cannot tolerate.** Inserting one text item renumbers every pointer after it, which re-points every stored reference. This is the single largest reason `owdoc` is not a `DoclingDocument` subclass. |
| `body` / `furniture` as two trees | `Layer` as a **column** | Furniture is a view, not a deletion — docling's own principle, implemented as one integer instead of two roots. It also generalises: `note`, `annotation` and `hidden` are three more roles that would each have needed a third and a fourth tree. |
| `groups` | `container`, `list`, `figure`, `section` | Typed where the type is knowable, `container` where it is not. |
| `CHECKBOX_SELECTED` / `CHECKBOX_UNSELECTED` | `checkbox` + `payload.checked` | Two labels for one type with a boolean is a modelling error that forces every consumer into a two-arm match. |
| `MARKER` | a `Mark`, or `list.marker_style` | A list bullet is not a block. |
| `DOCUMENT_INDEX` | `toc` + `toc_entry` | |
| `KEY_VALUE_REGION` | `key_value` with two children | docling makes it a leaf with unstructured content; two ordered children make the key and the value independently citable. |
| `TEXT` and `PARAGRAPH` | `paragraph` | Two labels, one concept. |
| `ProvenanceItem(page_no, charspan, bbox)` | `page` + `TextSpan` + `Quad`, plus `OriginSpan` | docling's `charspan` is **not** a page-glyph index: `docling/docling/models/stages/reading_order/readingorder_model.py:418-421` computes `(len(new_item.text)+1, ...+len(merged_elem.text))`, an intra-item range, and every other call site in that file passes `(0, len(text))` (`:95`, `:190`, `:302`, `:346`, `:363`). That is a `TextSpan`. The page-glyph space is real and comes from marker/pdftext (`marker/marker/schema/text/span.py:23-24`, `minimum_position`/`maximum_position`); it enters `owdoc` as `OriginGlyphs`. |
| `BoundingBox` with an explicit `CoordOrigin` | `Quad.from_driver(origin=...)` | Origin explicit in the type eliminates a class of off-by-a-flip bugs. We take it one step further: the origin is explicit at the **boundary** and then gone, because the stored frame is always topleft. |
| `ContentLayer` set at `add_text` time from the label (`readingorder_model.py:104-115`, `:396-398`: `PAGE_HEADER`/`PAGE_FOOTER` to FURNITURE, everything else BODY) | `layer` set by the driver, defaulted from the kind, inherited by children | The same design, one column, plus three more roles docling has no room for. |

**Not adopted from either, and why.** marker's `ignore_for_output` (a boolean meaning five different
things across processors) becomes `layer = hidden` plus `restriction_bits`. marker's
`top_k: Dict[BlockTypes, float]` becomes one `score` + `score_kind` on a named scale — a layout
softmax over 31 labels stored per block is 31 floats to answer a question one float answers, and the
runner-up label is recoverable from the layout driver's own cache when anyone actually needs it.
docling's `TableItem` structure annotations become `table_meta` columns.

### 4.4 Payload schemas

`block.payload` is a JSON object discriminated by `kind`. It exists so that kind-specific facts do
not become columns on the hottest table in the framework, and so that adding a fact to one kind is
not a schema migration. **It is a digest input** (`canonical(payload)` is hashed into
`content_digest`), so a payload change is a content change — which is correct: a list that becomes
ordered is a different list.

```jsonc
"heading":    {"level": 3, "anchor": "sec-4-2", "numbering": "4.2"}
"section":    {"level": 2, "anchor": "ch3", "label": "Chapter 3"}
"list":       {"ordered": true, "start": 1, "marker_style": "decimal", "nesting_level": 0}
"code":       {"lang": "python", "fenced": true, "line_start": 41}
"formula":    {"notation": "latex", "mathml": "<math>...</math>", "numbered": "3.14"}
"picture":    {"alt": "...", "role": "photo|chart|logo|screenshot|decorative"}
"note":       {"label": "3", "auto_numbered": true}
"comment":    {"author": "...", "created_ns": 1737000000000000000,
               "resolved": false, "reply_to": "p2/7"}
"form_field": {"name": "signature_date", "field_type": "text|date|choice|signature",
               "value": "2026-01-14", "readonly": false, "required": true,
               "choices": ["..."]}
"checkbox":   {"checked": true, "label": "I agree"}
"key_value":  {"pair_source": "layout|native|model"}
"toc_entry":  {"level": 2, "target_anchor": "sec-4-2", "printed_page": "iv"}
"reference":  {"citekey": "smith2019", "doi": "10.1000/182", "year": 1999}
"chemical":   {"notation": "smiles|inchi", "name": "..."}
"container":  {"role": "text_box|column|group|slide_placeholder|header_group|cell_group"}
```

**These are not comments; they are generated schemas.** `schema.json` carries one
`$defs/payload.<kind>` per row above, in §3.2's closed subset, and the same ~200-line validator
checks a payload at `DocSink.add_block` and at archive read. `heading.level` is
`{"type":"integer","minimum":1,"maximum":9}`; `checkbox.checked` is `{"type":"boolean"}`; and so on.
A payload that fails its kind's schema is `OW_SCHEMA_PAYLOAD_INVALID` at write, not a puzzle later.

**Reading a payload.** There is no `Block.payload`, because materialising a JSON object per block
would put a `json.loads` on every row of a 600k-block scan for a field two consumers read. Instead:

```python
class Doc:
    def payload(self, id: BlockId) -> Mapping[str, Any]: ...   # {} when the column is NULL
```

plus exactly three named readers in `omniweave_core.model.payload`, for the three keys other layers
branch on — `heading_level(doc, b) -> int | None`, `list_ordered(doc, b) -> bool | None`,
`checkbox_checked(doc, b) -> bool | None`. Everything else reads `Doc.payload()` and the generated
schema tells it the shape. Adding a fourth named reader requires naming the branch, exactly as
adding a `Kind` does.

**Rules.** Every payload is a **flat-ish object of scalars, arrays of scalars, and at most one level
of nested objects**, JSON-canonicalisable by contract (an un-canonicalisable value is a startup
error, I12), and `canonical(payload)` is capped at `MAX_PAYLOAD_BYTES`. Unknown payload keys for a
known kind are **preserved** and pass through `canonical()`: unknown payload keys are the intended
extension point for a driver that knows more than the model does, and `x.<vendor>.*` is for facts
that must **not** move the digest. A payload key promoted into the schema keeps its name. The digest
input is the **stored object**, canonicalised — never a re-serialisation of a typed reader's output,
which would make the digest depend on a reader version.

## 5. `Layer` — furniture is a column, not a deletion

```
body       the reading order proper. The default view of every projection.
furniture  running headers, footers, page numbers, watermarks. Present, ordered, excluded by default.
note       footnotes, endnotes, speaker notes. Present, addressable, citable, excluded by default.
annotation review comments, PDF annotations, tracked-change balloons.
hidden     text present in the source but not visible: white-on-white, off-canvas, zero-size,
           PPTX off-slide placeholders, `w:vanish`. Never in a default projection, always indexed,
           and it feeds L3's Taint.HIDDEN_TEXT / Taint.OFFSCREEN bits.
```

`serialize()` takes `layers: frozenset[Layer] = frozenset({Layer.BODY})`. A caller who wants
footnotes inline asks for `{BODY, NOTE}` and gets a `SpanMap` covering both. Retrieval filters on
`layer` before any channel scores.

**M-INV-5 (layer is inherited).** A block's `layer` equals its parent's, except for a **page root**
(a block whose parent is the `document` root), where the driver states it and `DocSink` defaults it
from the kind: `page_header`/`page_footer` to `furniture`; `footnote`/`endnote`/`speaker_note` to
`note`; `comment` to `annotation`; everything else to `body`. A non-page-root draft that names a
different layer from its parent's is rejected at `add_block` with `OW_LAYER_NOT_INHERITED`, and
`owcheck` re-asserts it over the whole generation.

This is not tidiness. Without inheritance, `serialize(layers={BODY})` has to decide what to do with
a `body` paragraph inside an `annotation` comment: render it (leaking a review comment into the body
text) or drop it (making the layer filter a subtree walk that costs an ancestor query per block).
With inheritance the filter is a **pure per-block predicate on an indexed column** and the ambiguity
does not exist. It also means `Layer` genuinely is one column and not a second tree, which is the
whole claim being made against docling's `body`/`furniture` split.

`Capabilities.furniture` records how a driver treated it: `destroyed` (the header text is gone — most
markdown converters), `flagged` (present but only as a heuristic guess), `separated` (a real `layer`
assignment from the source, e.g. OOXML `w:hdr`). Serve discloses `destroyed` in the corpus card,
because a corpus whose page numbers were destroyed cannot answer "what page was this on" from text.

**`hidden` is the security-relevant layer.** It is indexed and citable, and it never enters a default
projection or a prompt-facing render, because the attack it defends against is text a human reviewer
cannot see instructing a model that can. L3 ORs `Taint.HIDDEN_TEXT` upward from any mention grounded
in a `hidden` block, and `GENERATION_BLOCKED` refuses to compile it out. See
[structure extraction](06-structure-extraction.md) for the taint algebra and
[security](14-security.md) for the posture.

## 6. Identity

Four identities, four jobs, and conflating any two is the failure this section exists to prevent.

| identity | type | scope | stable across | job |
|---|---|---|---|---|
| `block_id` | int64 | one store | re-parse (via `rebind`), compaction | **the only FK target for a Block** |
| `addr` | string | `(doc_ord, gen)` | nothing — it is a position | archive references, CLI, URLs, logs, round-trip |
| `cite` | string | `doc_ord`, gen-free | re-parse, generation, the life of the corpus | the only identifier that may enter a prompt |
| `content_digest` | 16 B | global | byte-identical content | change detection, dedup, rebind, cache keys |
| `layout_digest` | 16 B | global | byte-identical content **and** whole-point geometry | round-trip / re-render detection |

### 6.1 `block_id`

```
block_id := (minting_shard_ord << 48) | sequence
```

The field layout is 16 bits of shard ordinal over 48 bits of sequence, and **the top bit of the
shard field must be zero**: SQLite's `INTEGER` is a signed 64-bit value, so `minting_shard_ord` runs
`0 .. 32767` and a store may mint `2**48 = 281,474,976,710,656` blocks — six orders of magnitude
above `MAX_BLOCKS_PER_DOC × 10^6` documents.

At a single store `shard_ord = 0`, so ids are literally 1, 2, 3 — zero bytes of overhead and
human-readable in a log. `CHECK ((block_id >> 48) = 0)` is written into the `block` DDL with the
ordinal **interpolated as a literal by the migration at CREATE time**, because SQLite prohibits a
bind parameter in a CHECK body (verified on 3.45.1); it is re-asserted at every open against
`index_state.shard_ord`. Reserving the 16 bits costs nothing now, and adding the prefix later would
rewrite every foreign key in every deployed store.

**Minting is not placement.** A document may migrate between shards; its `block_id`s keep their
prefix forever. A document never spans a shard, and there are no cross-shard foreign keys;
`GlobalRef = (corpus_id: str, block_id: int)` is the only reference type that crosses a store
boundary. See [storage and retrieval](07-store-and-retrieval.md) for placement and federation.

`block_id` never appears in a prompt (INV-8) and never appears in an `.owdoc` archive.

### 6.2 `addr` — the positional address

```
addr      := "doc" | "p" page "/" step ( "/" step )*
page       := DIGIT+                      -- the PAGE ANCHOR (M-INV-2), not necessarily block.page
step       := ord | cell_ref
ord        := DIGIT+
cell_ref   := "r" DIGIT+ "c" DIGIT+       -- the ORIGIN cell coordinates, 0-based
```

Three rules define it completely, and `DocSink` can evaluate all three inside one page's transaction,
which is why a 5,000-page document can be addressed without being resident.

1. **The `document` root's addr is the literal `doc`.** It is the one block with `parent_id IS NULL`
   and the one block whose page is meaningless, since it spans every page. Giving it a page-shaped
   address would either collide with the first page-root block or force a fake page component.
2. **`page` is the block's page anchor.** `anchor(B)` is the topmost ancestor of `B` strictly below
   the root — `B` itself when its parent is the root — and `addr`'s page component is
   `anchor(B).page`. For every block that does not belong to a page-crossing construct this equals
   `block.page` (§12.3).
3. **The first step is a page-root ordinal; every later step is a child `ord`, except a cell.** The
   page-root ordinal is the block's index among the page's page-root blocks, dense from 0 in `ord`
   order; `DocSink` keeps that counter per page and resets it at `begin_page`. A `table_cell`'s step
   is `r<r>c<c>`, and a cell's own children resume ordinary `ord` steps.

Examples. `p14/3` is the fourth page-root block of page 14. `p14/3/1` is its second child.
`p14/3/r2c5` is the cell at row 2, column 5 of the table at `p14/3`. `p14/3/r2c5/0` is the first
child block inside that cell. `doc` is the root.

Properties, each of which is load-bearing:

- **The kind is deliberately not in the address.** Promoting a paragraph to a heading does not move a
  block. marker's `BlockId.__str__` is `/page/{page_id}/{block_type.name}/{block_id}`, so a
  reclassification in a processor changes the address of the thing that was reclassified — and
  marker's processors reclassify constantly.
- **`addr` is positional and therefore generation-keyed**: `UNIQUE(doc_ord, gen, addr)`. `p14/3`
  legitimately names a different row at gen 41 and gen 42. That is what it is for.
- **The first step is page-local, not document-global.** A document-global root-child index would
  make every page's addresses depend on the block count of every earlier page, so re-parsing page 12
  of a 5,000-page document would renumber pages 13 through 4,999. Page-local numbering is the reason
  a page's addresses are a function of that page alone.
- **A cell's step is `r<r>c<c>`, not an ord**, because a cell's identity is its grid position and the
  serialization order of cells is an implementation detail of the driver. A cell nonetheless carries
  an ordinary `ord` among its siblings — `DocSink` assigns it in row-major origin order, dense from
  0 — because `ord` is dense from 0 for every block (P3) and `block_sib` is a UNIQUE index.
- **`addr` is bounded.** `MAX_BLOCK_DEPTH = 64` steps and `length(addr) <= 512`, both CHECKs. The
  depth cap matches `os_path`'s 64-element ceiling and is what stops a hostile HTML document with
  50,000 nested `div`s from producing a 50,000-deep spine and a 250 KB address (§14).

`Addr` is what every internal reference in an `.owdoc` archive uses. It is safe in a URL, a log line,
a CLI argument and a git diff. It is **not** safe in a prompt (INV-8) and it is never a foreign-key
target (INV-1, charter §5 X40).

### 6.3 `cite` — the durable, prompt-safe name

```
cite   := [ corpus ":" ] "d" doc_ord "#" n
corpus := [a-z0-9][a-z0-9_-]{0,31}     -- must name an entry in omniweave.toml [corpora]
```

`n` is drawn from **`doc.next_cite_n`**: a per-`doc_key` monotonic counter the host increments as it
mints, never reset, never reused, and **not** a write-order position within a generation. The unique
index is `block_cite(doc_ord, cite)` with **no `gen`**. Three properties follow:

1. One cite names at most one row, for the life of the corpus.
2. Inserting a block on re-parse cannot re-point a shipped citation.
3. `n` is dense-ish but has gaps, and a gap is correct — it is a retirement, or a cite minted for a
   staged row that `rebind()` then discarded in favour of a carried one (§6.5).

**The counter's burn rate, because gaps have a cost.** A re-parse mints a fresh `n` for every block
it writes and `rebind()` gives most of them back as gaps, so a document re-parsed `k` times has
consumed roughly `k × n_blocks` cite numbers. At `MAX_BLOCKS_PER_DOC` and a hundred re-parses that is
under 10^9, against an int64 counter — a non-issue, stated so nobody re-derives it as a bug.

**A retired cite still resolves.** `ow open --by-cite` follows `block_history.superseded_by` and says
so in the response. Where `superseded_by IS NULL` the answer is a stated refusal,
`OW-M-030 / OW_CITE_RETIRED`, naming the generation it was retired at and the reason — never a silent
miss and never a nearby block.

Corpus qualification is decided per surface: MCP with a session id qualifies once the session has
touched a second corpus; every surface without a session identity (MCP without a session id, the CLI,
the SDK, a hook) qualifies whenever `[corpora]` holds more than one entry; a single-entry `[corpora]`
never qualifies. One response uses one form throughout. That rule and its enforcement belong to
[interfaces](10-interfaces.md); the model's obligation is only that the column holds the unqualified
form and that both forms resolve.

### 6.4 Digests

```
ow128(domain, obj) = hashlib.blake2b(canonical(obj), digest_size=16, person=domain).digest()
    `domain` is a b'ow.<what>.<recipe>' literal -- a DOMAIN SEPARATOR, not a prefix.

canonical(x) = JSON with sorted keys, no NaN/Inf, geometry as i32 only, and THREE distinct
               encodings for absent / null / "".
               sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False.

content_digest = ow128(b'ow.content.1', [
    kind, layer,
    nfc(text) or None,                            # NFC-normalised; None != ""
    canonical(payload),
    [child.content_digest for child in children in `ord` order],     # merkle
])

layout_digest  = ow128(b'ow.layout.1', [          # NULL when quad IS NULL
    content_digest, page,
    quad quantised to WHOLE POINTS,               # kills driver jitter; canonicalise-then-hash
])
```

`blake3` is not in the standard library; `hashlib.blake2b` is, is C-accelerated, and takes `person=`,
so every "blake3_128" in the source rulings is `ow128` (charter §5 C3, X6). `"".join(values)` is
banned as a digest input — graphrag's `gen_sha512_hash`
(`graphrag/packages/graphrag/graphrag/index/utils/hashing.py`, called at
`build_noun_graph.py:79`) concatenates field values, so `["a","bc"]` and `["ab","c"]` collide.

**Not digest inputs**, and each exclusion buys something specific:

| excluded | because |
|---|---|
| every span (`os_*`, `ts_*`) | a driver changing byte accounting must not orphan unchanged content |
| `producer_id`, `method`, `origin_*`, `driver_schema_v` | two drivers producing identical content **collide on purpose** — that is how a re-parse by a better driver carries the cite |
| `x` | a third party stamping an annotation must not invalidate every cache entry |
| `marks` | a formatting-only fix must not re-bill an embedding |
| `trust`, `quote`, `score`, `raw_kind`, `restriction_bits`, `decision_id` | confidence and licensing are about the row, not the content |
| `block_id`, `addr`, `cite`, `ord`, `revision` | identity is not content |
| geometry, in `content_digest` | a driver upgrade's bbox jitter must not orphan a document |

Note the one asymmetry that looks like an inconsistency and is not: `ord` is excluded, but children
are hashed **in `ord` order**, so a reordering of siblings changes the *parent's* digest and not the
children's. That is exactly right — the children did not change; their arrangement did.

**The constraint that makes a recipe bump survivable:** every digest input is a **stored field**, so a
`digest_recipe` bump is serviced by a **re-digest pass**, never a re-parse. Budget at most annually
(§15.3).

**Digest closure and the commit boundary — Extends the charter.** `content_digest` is a merkle over
children, and `DocSink.end_page()` commits one transaction, so a block whose subtree closes on a
later page cannot have its final digest at the moment its own row is written. The rule: a block is
written with a **provisional** digest over its own content and the children committed so far, and
`end_doc()` runs one bottom-up **closure pass** over the blocks whose `max(descendant.page)` exceeds
their own page — in practice the `document` root and the handful of page-crossing containers — and
rewrites their `content_digest` and `layout_digest` in the final transaction. The pass is
`O(cross-page containers)`, not `O(blocks)`, and it finds them with one query:

```sql
SELECT DISTINCT a.block_id FROM block a JOIN block d
  ON d.parent_id = a.block_id AND d.gen = a.gen AND d.doc_ord = a.doc_ord
 WHERE a.doc_ord = ?1 AND a.gen = ?2 AND d.page > a.page;
```

closed transitively upward through `parent_id` (the root is always in the set for a multi-page
document). Three consequences a reviewer must know: a `content_digest` read from an *uncommitted*
generation is not final; `rebind()` therefore runs **after** the closure pass, inside the same
`end_doc()` transaction; and `block_cdig` lookups during ingest may miss a not-yet-closed container,
which is correct, because a container whose subtree is incomplete is not yet the same content as
anything.

### 6.5 `rebind()` — re-parse identity as an explicit pass

```python
@dataclass(frozen=True, slots=True)
class RebindReport:
    doc_ord: int; from_gen: int; to_gen: int
    carried: int; revised: int; created: int; retired: int
    match_rate_by_page: Mapping[int, float]
    quarantined: bool; threshold: float

def rebind(store, doc_ord: int, to_gen: int, *, threshold: float = 0.80) -> RebindReport: ...
```

| rule | condition | `block_id` | `cite` | `revision` | the old row |
|---|---|---|---|---|---|
| 1 | equal `content_digest` under the same parent | carried | carried | unchanged | carried forward (see below) |
| 2 | equal `addr` **and** `kind`, digest changed | carried | carried | `+= 1` | carried forward |
| 3 | neither | fresh | fresh `n` from `doc.next_cite_n` | 0 | `state = 1`, plus a `block_history` row with a reason and a `superseded_by` |

**How a `block_id` is actually carried, because `block_id` is a PRIMARY KEY.** The parse has already
written the staged generation `g_t` with *fresh* ids for every block. A carried id therefore cannot
be the new row's; it must be the **old** row's, since L3 and L4 rows from `g_h` reference it. For
each matched pair `(old_id, new_id)` the pass, inside `end_doc()`'s single transaction and in this
order:

```sql
-- 1. free the staged row's addr and cite so the UPDATE below cannot collide
DELETE FROM block WHERE block_id = :new_id;              -- cascades marks/cell/block_asset
-- 2. move the durable row forward, taking the staged row's content and parse facts
UPDATE block SET gen = :g_t, page = :new_page, addr = :new_addr, parent_id = :new_parent,
       ord = :new_ord, kind = :k, raw_kind = :rk, layer = :ly, label = :lb, text = :t,
       content_digest = :cd, layout_digest = :ld, quad = :q, os_kind = :osk, ...,
       producer_id = :pd, method = :mt, trust = :tr, quote = :qt, score = :s, score_kind = :sk,
       origin_operator = :oo, origin_driver = :od, driver_schema_v = :dv,
       restriction_bits = :rb, decision_id = :dc, payload = :pl, state = 0,
       revision = revision + :bump                       -- 0 for rule 1, 1 for rule 2
 WHERE block_id = :old_id;
-- 3. re-point the staged row's satellites (marks were deleted with it and are re-inserted)
```

The `DELETE`-before-`UPDATE` order is mandatory: `block_addr` is `UNIQUE(doc_ord, gen, addr)`, so
moving the old row to `g_t` while the staged row still holds that addr is a constraint violation.
This is the **one and only** `UPDATE` of a committed Block in the framework (§2.5), and it explains
two facts that otherwise look contradictory: a carried block does not exist at two generations at
once, and "the previous generation is retained" is a statement about *retired* rows, whose old ids
stay at their old gen with `state = 1`.

**Carrying the cite is the point of the pass.** A cite is a shipped, durable name; re-minting it on
re-parse would re-point every citation already in someone's document — the exact failure D2 rejects
one level up when it refuses an ordinal as an identity. codegraph measured **4.3% of distinct edges
wrong, in both directions, silently**, from skipping the equivalent pass.

**Matching, concretely.** Rule 1 is one indexed lookup per staged block on
`block_cdig(doc_ord, content_digest)`, filtered to the same parent's carried id; a digest matching
more than one candidate under the same parent is resolved by nearest `ord` and the loser falls
through to rule 2. Rule 2 is one lookup on `block_addr(doc_ord, gen, addr)`. Both are O(1) per
block, so the pass is O(blocks) with two index probes each and no cross join — which is what makes it
affordable inside `end_doc()`.

Below `threshold` the new generation is **quarantined, not committed**: `doc.gen` is not bumped, the
staged rows stay durable and invisible for inspection by `ow doc diff`, and the override is named per
check (`--allow-unexplained-rebind`); there is no `--force` anywhere in the framework. `rebind()` is
also the golden differ used by [quality](13-quality.md) — one matcher, two consumers.

**Rebind carries identity, never confidence.** `trust`, `quote`, `score`, `method`, `producer_id` and
the spans on a carried row are the **new** generation's values, because none of them is a digest
input and all of them describe the parse, not the content. A block whose text is unchanged but which
was read this time by OCR instead of the text layer keeps its `block_id` and `cite` and drops from
`VERBATIM` to `RECONSTRUCTED`. That is the correct answer, and it is why the two are separated.

### 6.6 Worked example

A two-page PDF, `contract.pdf`, first ingest at `doc_ord = 7`. `begin_doc` inserts `doc` at
`gen = 0`, so `g_t = 1`; `doc.next_cite_n` starts at 1.

```
block_id  addr          cite     parent  ord  page  kind          text
   1      doc           d7#1     NULL     0    0    document      NULL          <- merkle root
   2      p0/0          d7#2        1     0    0    title         "Master Services Agreement"
   3      p0/1          d7#3        1     1    0    heading       "1. Definitions"    level=1
   4      p0/2          d7#4        1     2    0    paragraph     "In this Agreement..."
   5      p0/3          d7#5        1     3    0    page_footer   "Page 1 of 2"  layer=furniture
   6      p1/0          d7#6        1     4    1    container     NULL           role="column"
   7      p1/0/0        d7#7        6     0    1    heading       "2. Fees"           level=1
   8      p1/0/1        d7#8        6     1    1    table         NULL
   9      p1/0/1/r0c0   d7#9        8     0    1    table_cell    "Segment"
  10      p1/0/1/r0c1   d7#10       8     1    1    table_cell    "FY2024"
  ...
```

`end_doc` runs the closure pass (block 1's digest closes over page 1), `owcheck`, `rebind` (a no-op:
`g_h = 0` has no rows, so `created = 10`), then `UPDATE doc SET gen = 1`.

Note what the identities do and do not say. Block 6 is `ord = 4` among the root's children — the
containment spine is one forest rooted at the `document` block — but its **first addr step is 0**,
because it is the first page-root block of page 1. Those are different numbers answering different
questions, and conflating them is what makes a document-global index renumber the whole document
when one page changes. The cite numbers are the mint order and carry no structural meaning at all.

Now the PDF is re-signed: one paragraph gains a clause, and a new paragraph is inserted after it.
The parse writes `g_t = 2` with fresh ids 41-50 and fresh cites `d7#11`-`d7#20`, then
`rebind(store, 7, 2)`:

```
gen-2 addr        kind         rule  block_id  cite   revision  why
doc               document       2        1     d7#1      1     subtree digest changed; same addr+kind
p0/0              title          1        2     d7#2      0     identical content_digest
p0/1              heading        1        3     d7#3      0     identical
p0/2              paragraph      2        4     d7#4      1     same addr+kind, text changed
p0/3              paragraph      3       47     d7#17     0     NEW: inserted. The gen-1 p0/3 was the
                                                                footer, which is now at p0/4.
p0/4              page_footer    1        5     d7#5      0     NOT matched by addr -- the addr moved.
                                                                Matched by rule 1: identical digest
                                                                under the same parent. Cite preserved.
```

The row that would have broken under an ordinal identity is `page_footer`: its `addr` moved from
`p0/3` to `p0/4`, and under a position-bearing id every citation to it would now point at the
inserted paragraph. Rule 1 matches it on `content_digest` under the same parent and carries both
`block_id` and `cite`. The staged rows for the five carried blocks are deleted, so `d7#11`-`d7#16`
and `d7#18`-`d7#20` become permanent gaps in `next_cite_n` — the gaps §6.3 describes. `RebindReport`
reads `carried = 4, revised = 2, created = 1, retired = 0`,
`match_rate_by_page = {0: 1.0, 1: 1.0}`, and `doc.gen` moves to 2. *(Build note, D905, a user ruling of 2026-10-19 (D40's option a): this example is now what `ow add` does. §2.2's `DocKey` (:162, `sha256(normalized source bytes)[:16]`) made an edit a new document, so no cite carried; the key is now `identity.location_key(unit_uri, source_root)`, the file's place in its corpus, so an edit is the same `doc_ord` at its next generation and `rebind()` carries every unchanged block. The head's normalised digest is kept as `doc.x.ow.content`. Two refinements the example did not need: an edit whose source bytes changed commits below the threshold, since the new bytes explain it, and only a re-parse of the same bytes is quarantined; a quarantined generation puts back the head's `doc` facts `begin_doc` overwrote. An older store is rekeyed by the ingest before anything parses, and `0006_doc_uri.sql` indexes `doc(uri)` for the lookups that moved from content to path. A file moved or renamed keeps its document: one whose file is gone, and a present file with the same bytes and no document, are one move (`discover.adopt_moved`), so its cites carry as they did when the key was the bytes.)*

The failing case, for contrast: a driver upgrade re-segments page 0 into line-level blocks. Every
digest differs, no `addr` survives with its kind, `match_rate_by_page[0] = 0.0`, and the generation
is **quarantined** with `OW_REBIND_UNEXPLAINED` rather than silently retiring five cites. `doc.gen`
stays at 2 and every existing citation keeps resolving.

## 7. Geometry, provenance of position, and the three coordinate systems

### 7.1 Geometry: one stored frame, one constructor

The stored frame is **always** `(topleft origin, 1/1000 pt, unrotated page)`. Normalization happens
exactly once, at the driver boundary, inside `Quad.from_driver`, which takes the driver's own frame
explicitly:

```python
Quad.from_driver(pts, origin="bottomleft", unit="pt", page_h=841.89, dpi=None, rotation=90)
```

| driver's world | `origin` | `unit` | what `from_driver` does |
|---|---|---|---|
| PDF user space (pdfium, pdftext) | `bottomleft` | `pt` | `y' = page_h - y`, scale ×1000 |
| PDF with `/Rotate 90` | `bottomleft` | `pt` | flip, then **un-rotate** by `-rotation` about the page centre, so the stored quad is in the unrotated page frame and `page.rotation` records the display rotation |
| OOXML DrawingML | `topleft` | `emu` | `× 1000 / 12700` (1 pt = 12,700 EMU) |
| a rendered raster (OCR, VLM) | `topleft` | `px` | `× 72000 / dpi`; `dpi` is **required** for `unit="px"` and its absence is `OW_QUAD_NO_DPI` |
| a normalized 0..1 layout model | `topleft` | `px` with `dpi=None` and `page_h=1.0` | rejected — normalize in the driver against the real page size first |

Rounding is `round-half-away-from-zero` on the millipoint, applied per coordinate after the affine
transform, so the operation is a pure integer function of the inputs and reproduces on every
platform. `page.quad_origin` records **what the driver handed us**, not what is stored, so an audit
can re-derive the transform. `page.w_mpt`/`h_mpt` are the unrotated page box.

Four corners, not a rect, because a rotated text box, a skewed scan and a curved-baseline OCR line
all have a real quadrilateral and an axis-aligned rect silently over-claims. `rect()` is a view for
consumers that only need a bounding box. Corner order is `(x0,y0)` top-left, then clockwise, in the
stored unrotated frame; `from_driver` re-orders whatever the driver handed it, so a driver emitting
counter-clockwise polygons does not produce quads that fail a containment test for no visible reason.

**Geometry is never synthesized** (INV-9). If a driver has no polygon, `quad` is NULL and every
consumer that needs one gets `Locus.reason` naming why — for example
`"parse.office.anydoc declares spatial=none"`. There is no fallback to the page box, no
interpolation from neighbours and no zero quad.

`Capabilities.spatial` is the declared granularity: `none < page_bbox < block_bbox < line_bbox <
char_bbox`. It is a **filter, never a ranking key** in `resolve()`.

### 7.2 `OriginSpan` — the address in the original container

There is no single answer to "where did this text come from", which is why `OriginSpan` is a tagged
union and not a `(start, end)` pair. Each variant exists because a real format needs it.

| variant | fields | when | what re-verifies it |
|---|---|---|---|
| `bytes` | `part, start, length, codec` | flat text: `.txt`, `.md`, `.csv`, `.html` source, a JSON blob | `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text` — decode under the recorded `<codec>/<errors>`, then NFC and nothing else ([structure extraction](06-structure-extraction.md) §1.7 defines `nfc()`) |
| `nodepath` | `part, path: tuple[int,...]` | OOXML, ODF, any XML container | `nfc(node_text(part, os_path)) == block.text` |
| `glyphs` | `part, extractor, start, length` | a PDF text layer | re-extracting `[a, a+len)` from `part` with the recorded `extractor` reproduces `block.text` under NFC |
| `pixels` | `page, quad` | OCR / VLM — **the polygon is the address** | nothing; `pixels` can never reach `VERBATIM` |
| `none` | — | derived, synthetic, or a driver that carries no address | nothing |

**The column mapping, because the union has to fit seven columns.** The charter's `block` DDL gives
`os_kind`, `os_part`, `os_a`, `os_b`, `os_path`, `os_extractor`, `os_codec` and nothing else; this
table is the only correct way to fill them, and the CHECKs make it enforceable rather than
conventional.

| variant | `os_kind` | `os_part` | `os_a` | `os_b` | `os_path` | `os_extractor` | `os_codec` | additional CHECK |
|---|---|---|---|---|---|---|---|---|
| `bytes` | `bytes` | part path | start | **length** | NULL | NULL | `'utf-8/strict'` | `os_codec IS NOT NULL` |
| `nodepath` | `nodepath` | part path | NULL | NULL | `'0.3.1.7'` | NULL | NULL | — |
| `glyphs` | `glyphs` | part path | start | **length** | NULL | `'pdftext@0.6'` | NULL | — |
| `pixels` | `pixels` | NULL | NULL | NULL | NULL | NULL | NULL | `quad IS NOT NULL` |
| `none` | `none` | NULL | NULL | NULL | NULL | NULL | NULL | — |

```sql
-- added to the block DDL (Extends the charter: additive CHECKs, no column changes)
CHECK (os_kind <> (SELECT ord FROM enum_val WHERE domain='origin_span_kind' AND name='pixels')
       OR quad IS NOT NULL)                            -- see the note below on SQLite
CHECK ((os_path IS NOT NULL) <= (os_part IS NOT NULL))  -- a node path needs a part
CHECK ((os_extractor IS NOT NULL) <= (os_part IS NOT NULL))
CHECK (os_b IS NULL OR os_b >= 0)                       -- os_b is a LENGTH, never an end offset
CHECK (os_kind <> (SELECT ord FROM enum_val WHERE domain='origin_span_kind' AND name='bytes')
       OR os_codec IS NOT NULL)                         -- the bytes branch decodes; NULL is unevaluable
```

SQLite prohibits a subquery inside a `CHECK`, so the `pixels` and `bytes` ordinals are
**interpolated as literals by the migration**, exactly as the shard ordinal is in
`CHECK ((block_id >> 48) = 0)`; the generator emits `CHECK (os_kind <> 3 OR quad IS NOT NULL)` and
`CHECK (os_kind <> 0 OR os_codec IS NOT NULL)`, and CI asserts each literal against
`OsKind.PIXELS`'s and `OsKind.BYTES`'s declaration index in both directions. The remaining two are
implication CHECKs written as `<=` over 0/1, which SQLite evaluates arithmetically.

The fourth clause exists because the `bytes` branch's predicate now **reads** `os_codec`: it decodes
before it compares, so a NULL codec makes the branch unevaluable rather than merely undocumented.
The mapping table above already fixes `'utf-8/strict'` as the default spelling; the CHECK is what
makes the absence impossible rather than conventional.

**`os_b` is a length, not an end offset**, at every site: the column, the wire (`os.len`), and the
value type (`OriginBytes.length`). One quantity, one spelling, three places.

**Why `nodepath` and not a byte range for OOXML.** A byte offset into `word/document.xml` is
destroyed by any attribute reordering on re-serialization. ppt-master's verified answer is a
child-index path — `SourceRefRecord.source_path: tuple[int, ...]` at
`ppt-master/skills/ppt-master/scripts/authoring_roundtrip.py:88` — which is stable under edits to
other subtrees. A byte range is right for flat text and wrong for containers.

**Why `glyphs` exists at all.** A PDF paragraph has no byte range in the content stream. Without a
glyph-run address, `parse.pdf.pdfium` could never produce a `VERBATIM` block, and with
`parse.office.anydoc` honestly declaring `origin_span = "none"` the `VERBATIM` tier would ship with
**no producer at all** (charter §5 X8). `extractor` is an exact identity like `pdftext@0.6`, because
the glyph index space is the extractor's, not the PDF's; the glyph-index space itself is real and
visible in marker as `Span.minimum_position`/`maximum_position`
(`marker/marker/schema/text/span.py:23-24`).

`OriginNone()` is a **value**, not a null. `os_kind` is `NOT NULL` on the table; the union is
nullable only as a whole, and a driver that leaves it unset gets `none` and a recorded degradation
in `achieved.origin_span`.

`os_codec` records the decode policy for the `bytes` branch as `<codec>/<errors>`
(`'utf-8/strict'`, `'cp1252/replace'`), and **decode symmetry is an invariant**: both sides of a
verification decode with the same codec and the same error policy (jcodemunch #400). A `part` decoded
`utf-8/strict` at parse time and `utf-8/replace` at verify time produces a spurious mismatch.

**Extends the charter — the `bytes` branch normalises under `nfc()`, not `normalize_k`.** The charter
writes INV-10's `bytes` branch as `normalize_k(part_bytes[a : a+len])[0] == block.text` at `:81`,
`:1168`, `:1453` and `:8017`. `normalize_k` is NFKC **plus casefold** plus five more operations
([structure extraction](06-structure-extraction.md) §1.7), so under it a block reading `"abc"` proves
`VERBATIM` against source bytes reading `"ABC"`, and `VERBATIM` and `NORMALIZED` (§8.3) carry the same
predicate, differing only in whether the part was retained. All three branches now agree on `nfc()`:
`bytes` decodes and NFC-normalises, `nodepath` is `nfc(node_text(part, os_path))`, `glyphs`
re-extracts under NFC. `normalize_k` leaves INV-10 entirely and stays in grounding, where casefolding
is the point. Charter errata `E48`-`E51` carry the amendment and supersede `E1`, `E2` and `E13`, which
repaired the missing `[0]` at three of those loci and each said "INV-10 itself is unchanged".

### 7.3 `Capabilities.origin_span` — the three declarable levels

| value | meaning | reachable `quote` ceiling |
|---|---|---|
| `none` | the driver supplies no per-block source address | `NORMALIZED` (§8.3) |
| `normalized` | an address that locates the block but does not re-verify byte-for-byte (a paragraph index, a slide/shape pair) | `NORMALIZED` |
| `exact` | an address that re-verifies on one of the three branches | `VERBATIM` |

`origin_span = "exact"` is **proved per driver by re-reading the retained part**, on whichever
branch the driver's `os_kind` selects — all three branches, not just `bytes`. Stating only the byte
form made the property inapplicable to exactly the container formats it matters most for. That test
is the only mechanism that makes a third party's honesty machine-checkable, so it must cover every
branch a driver may declare (§17, P7).

Note that `none` and `normalized` reach the same `quote` ceiling. The difference between them is not
quotability but **locatability**: a `normalized` address answers `locate()` at `precision = "block"`
from the source side even when `quad IS NULL`, and a `none` address answers nothing.

**The field keeps all three values, and the middle one is enforced rather than collapsed.** Three
readers branch on it and no two read the same fact: the `achieved.origin_span` rollup (§2.9)
distinguishes "a block failed re-verification" from "a block carried no address"; `byte_exact()`
([storage and retrieval](07-store-and-retrieval.md) §8.2) tests `achieved.origin_span == "exact"` and
is what `Q-G6` gates at 1.000; and `[store] retain_parts = "when_citable"` (§8.1 there) reads the
**declared** card and doubles or halves the store on that bit. Collapsing to a boolean deletes a
distinction one of the three already reads, whichever way it is cut; a sixth `Quote` tier would give
two blocks with identical text different rungs because their drivers declared differently, which is
what `byte_exact()` exists to forbid. What the rung lacked was not a reader but an **enforcer**, and
§17 P32 is it: declaring `normalized` now obliges an address that locates.

### 7.4 `TextSpan` versus `OriginSpan` — a span in reconstructed text is not a byte range

These are the two questions a caller confuses, and the type system refuses to let them:

- **`TextSpan(a, b)`** is a half-open character range inside **this block's own `block.text`** — the
  string omniweave reconstructed. It answers "which part of this paragraph". Its units are Python
  characters after NFC. It is what docling's `charspan` actually is
  (`readingorder_model.py:418-421`).
- **`OriginSpan`** is an address **into the original container**, in that container's own units:
  bytes of a decompressed part, a child-index path, a glyph index in an extractor's stream, or a
  polygon on a page. It answers "where in the file".

They are not convertible in general. `TextSpan -> OriginSpan` is a **query**, not an arithmetic
operation: for `bytes` it requires re-decoding the part with `os_codec` and walking the normalisation
that produced `block.text`; for `nodepath` it requires descending into the node's runs; for `glyphs`
it requires re-extraction; for `pixels` it is impossible below the block. That query is `locate()`,
and its output carries a `precision` field (`char | line | block | page | none`) that **says which** —
sub-block precision is a query, never a stored column. `Doc.verify_quote()` runs the same machinery
for a different purpose and returns only a `QuoteVerdict`; `precision` lives on `Locus`, not on the
verdict.

**What `block.span` is for.** `block.span` (the `ts_a`/`ts_b` columns) is the block's own span
inside a *parent's* text in exactly one situation: when a driver splits one source text item into
several blocks and can say which part of the original each block covers. docling's reading-order
merge does this (`(len(new_item.text)+1, ... + len(merged_elem.text))`). In every other case it is
NULL, and `NULL` here means "this block's text is the whole of its own text", not "unknown".

### 7.5 What happens when a driver can supply only one

This is the common case and it must not be a hole.

| driver supplies | `os_kind` | `ts_a/ts_b` | `quad` | `achieved` | consequence |
|---|---|---|---|---|---|
| both an origin address and a polygon (`parse.pdf.pdfium` on a born-digital page) | `glyphs` | NULL | set | `origin_span="exact"`, `spatial="block_bbox"` | full: byte-exact quoting **and** citation-to-pixel |
| **only** a polygon (OCR, VLM) | `pixels` | NULL | set | `origin_span="none"`, `spatial="block_bbox"` | citation-to-pixel yes; `quote <= RECONSTRUCTED`; `verify_quote` returns `source_unavailable` |
| **only** an origin address — the shape ppt-master demonstrates; **no first-party driver occupies this row at release 1** | `nodepath` | optional | NULL | `origin_span="exact"`, `spatial="none"` | byte-exact quoting yes; `locate()` returns `Locus(quad=None, reason="...declares spatial=none")` and **serve says so** rather than drawing a box |
| **neither** (`parse.office.anydoc` at release 1) | `none` | NULL | NULL | `origin_span="none"`, `spatial="none"` | the block is text with a `cite`, at `quote = NORMALIZED` at best; `verbatim` is unreachable on this path and `corpus_card.verbatim_fraction` discloses it **before any query runs** |

The last row is the honest state of the shipped office path, verified against the pinned wheel:
`anydoc/src/model/block.rs:5-38` defines `Block` as **eight** variants — `Heading{level, anchor,
content}`, `Paragraph`, `List`, `Table`, `BlockQuote`, `CodeBlock{lang, text}`, `Rule`, `Math` — with
**no source address of any kind**; only `Asset` carries `origin_part`
(`anydoc/src/model/asset.rs:14-15`), and `python/src/lib.rs` exposes only `format_from_*`,
`to_markdown`, `to_markdown_bytes`, `to_document`. Declaring `"exact"` would fail the testkit on the
first fixture. The first named clause of `vendor/anydoc/FORK-TRIGGER.md` is "emit a `w:p` / `a:t`
child-index path per block"; the day that lands, the card becomes `"exact"` and the tier opens with
no model change. (The charter's D3 note calls this "nine variants" while listing eight; the count is
eight in tree. §18.)

**The rule for a consumer.** Never infer one system from the other. Ask `doc.achieved`, and if the
capability is absent, say so. A driver that declares `forfeits = ["citation"]` makes serve **refuse**
a citation request against its result rather than fabricate one.

## 8. Confidence and driver attribution

Six confidence-shaped things exist across omniweave and they are not interchangeable. Three of them
live on a Block.

### 8.1 The six provenance axes on every Block

| axis | column(s) | means | who writes it |
|---|---|---|---|
| reproduction | `producer_id` -> `producer` | the tuple needed to reproduce this row | the runner |
| method | `method` | the branch that actually ran | the runner, from the resolved candidate |
| ownership | `origin_operator` (2 segments), `origin_driver` (3), `driver_schema_v` | **who may replace this row** | the runner |
| trust | `trust` | how much the *shape* of this row can be relied on | the runner, **after** the clamp |
| score | `score` + `score_kind` | the producer's own numeric confidence, on a named scale | the driver; the scale is validated at write |
| cost | `decision_id` -> `route_decision` | which routing decision produced this row and what it cost | the runner |

Plus `quote` (§8.3), `raw_kind`, `restriction_bits` and — on derived L3 rows, never on a Block —
`taint`.

Ownership is what makes incremental re-derivation safe: `derive.segment` re-running cannot touch
`derive.entity` rows, because the delete predicate is `WHERE origin_operator = 'derive.segment'`.
`origin_operator` is two segments and `origin_driver` is three precisely so the ownership grain is
coarser than the implementation — swapping `parse.pdf.pdfium` for `parse.pdf.marker` replaces the
same rows.

### 8.2 `Trust` — three levels, and the clamp

```
AMBIGUOUS = 0   the shape of this row is a guess. A layout model at low confidence; a heuristic
                that fired on a tie; a driver that did not state a level.
INFERRED  = 1   a model or a heuristic produced this and it is usually right.
EXTRACTED = 2   the source itself said so. A `w:tbl` is a table because the file says it is.
```

`MIN()` over a set is the set's trust — which is why `AMBIGUOUS` is 0 — and it is what
`segment.trust` holds. Absent on the wire means `AMBIGUOUS`, **and it is counted**, so a driver that
never sets trust shows up in `ow doc verify` rather than looking clean.

```python
MAX_TRUST_BY_METHOD: Mapping[Method, Trust] = {
    Method.NATIVE: EXTRACTED, Method.NATIVE_XML: EXTRACTED, Method.TEXT_LAYER: EXTRACTED,
    Method.HEURISTIC: EXTRACTED, Method.USER: EXTRACTED,
    Method.OCR_PAGE: INFERRED, Method.OCR_BLOCK: INFERRED, Method.VLM_PAGE: INFERRED,
    Method.LLM: INFERRED, Method.ROUNDTRIP: INFERRED,   # the ones a document can talk back on
}
```

Applied **by the runner** after the driver returns; a driver cannot opt out (INV-7). A clamp writes
`OW_GRAPH_TRUST_CLAMPED` carrying the driver's **original claim**, so over-claiming is measurable in
`ow graph doctor` rather than silently corrected. The mapping is mirrored into generated
`BEFORE INSERT` triggers at migration time with CI parity in both directions: two enforcers, one
truth. **A migration may only downgrade trust.**

`HEURISTIC` at `EXTRACTED` looks wrong and is deliberate: the ceiling is keyed on *what could be
read*, not on *how clever the reading was*. A heuristic that splits a `w:tbl` into rows is reading
the file, and the file said so. The heuristic's own uncertainty is `score` on a named scale, and its
`trust` is what the driver actually writes — which for a coin-flip heuristic must be `AMBIGUOUS`. The
clamp is a ceiling, never a floor.

### 8.3 `Quote` — the byte-exactness ladder

```
SYNTHETIC     = 0   omniweave wrote this text. A table synopsis, a heading path, an OUT placeholder.
RECONSTRUCTED = 1   characters were rebuilt from a non-textual source. OCR and VLM output.
REFLOWED      = 2   source characters, re-joined across a line, column or page break.
NORMALIZED    = 3   equal to the source under `normalize_k` (06 §1.7 enumerates its operations).
                    A CLAIM, clamped by MAX_QUOTE_BY_OS_KIND. Never proved: a block at
                    os_kind = none has no source to compare against.
VERBATIM      = 4   re-derivable from retained source bytes, provably, under `nfc()` and nothing
                    else (06 §1.7). The only tier serve may call byte-exact.
```

**`VERBATIM` requires two things, and both are re-checkable.** `part.store_ref IS NOT NULL` (the
bytes were retained, content-addressed) **and** one of exactly three re-verifiable branches passes
(§7.2). `pixels` and `none` can never reach it: there is nothing to re-read. Q-G6 gates
`span_exact_rate` at **1.000** — a hard gate, not a metric.

Say precisely what the tier promises, because "byte-exact" overstates it by one step. `block.text` is
NFC (§2.5), and a source in NFD is not NFC, so a `VERBATIM` block's characters need not be the
source's bytes. What is proved is that **`block.text` is re-derivable from the retained bytes by the
recorded, deterministic decode-and-normalise path**, checked by actually re-reading them. That is the
claim serve makes, and it is the strongest claim that is true.

**The top two rungs use different normalisers, and the ladder stays ordered.** `NORMALIZED` keeps
`normalize_k`; `VERBATIM` proves under `nfc()` (§7.2). Only `VERBATIM` is proved, so only `VERBATIM`'s
predicate narrows — a `NORMALIZED` claim is a declaration a driver makes and the host clamps, not a
re-read. Narrowing the proved rung and not the claimed one is what separates them: before this, a
parser that lower-cased every heading still passed `Q-G6` at 1.000. The order survives the split
because NFKC is total and canonically composing, so `nfc(d) == t` implies
`normalize_k(d)[0] == normalize_k(t)[0]` — every `VERBATIM` block also satisfies the `NORMALIZED`
predicate. That implication is asserted rather than assumed, as a property in
[quality](13-quality.md) §6 over generated NFD, soft-hyphenated, ligatured and case-varied pairs.

**Extends the charter — `MAX_QUOTE_BY_OS_KIND`.** The charter clamps trust by method but leaves
quote clamped only at the top by INV-10. The host applies a symmetric clamp, for the same reason and
at the same site:

```python
MAX_QUOTE_BY_OS_KIND: Mapping[OsKind, Quote] = {
    OsKind.BYTES: VERBATIM, OsKind.NODEPATH: VERBATIM, OsKind.GLYPHS: VERBATIM,
    OsKind.PIXELS: RECONSTRUCTED,   # the polygon is the address; there is no character source
    OsKind.NONE:   NORMALIZED,      # real characters were read; the driver cannot say from where
}
# and one more clamp, because os_kind alone cannot see a derivation:
def clamp_quote(claim: Quote, os_kind: OsKind, origin_operator: str) -> Quote:
    ceiling = MAX_QUOTE_BY_OS_KIND[os_kind]
    if not origin_operator.startswith("parse."):
        ceiling = min(ceiling, Quote.SYNTHETIC)   # a derived block quotes nothing by inheritance
    return min(claim, ceiling)
```

`NONE` caps at `NORMALIZED`, not `SYNTHETIC`, because the charter has already ruled on the case it
governs: with `parse.office.anydoc` at `origin_span = "none"`, "at release 1 every
DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized`" (charter D3). Those blocks did read real source
characters; what they cannot do is say which bytes. The second clamp is what stops that ceiling from
laundering a derived block: a table synopsis has `os_kind = none` and
`origin_operator = 'derive.table'`, so it lands at `SYNTHETIC` (§8.5(b)) rather than inheriting
`NORMALIZED`.

A clamp writes `OW_QUOTE_CLAMPED` with the driver's original claim. Note the consequence for OCR and
accept it: an OCR'd page's text is `RECONSTRUCTED`, so `Filters.min_quote = REFLOWED` excludes it.
That is the correct behaviour for a byte-exactness filter, and the alternative — letting OCR declare
`NORMALIZED` on the strength of a normalisation nobody can run — is the claim this ladder exists to
prevent. A tenant may clamp a ceiling lower; nothing widens it.

`Doc.verify_quote(block_id)` is the self-verifying half of confidence and needs no labelled corpus:

```python
QuoteVerdict = Literal["match", "source_ahead", "mismatch", "source_unavailable"]
```

`source_ahead` — the source is newer and the slice still matches — **must not read as corruption**.
It is jcodemunch's `git_sha_uncommitted` for documents. The verdict names what it compared against:
`{sha256, mtime_ns, part}`.

### 8.4 `score` and `score_kind`

Nullable **together**, enforced by a CHECK, because "0.7 on an unnamed scale" is not a measurement.
`score_kind` is a row in an append-only `tools/scorekinds.toml`, and an unregistered kind **raises at
`DocSink.add_block`** rather than being stored and puzzled over later. A layout softmax and a token
probability are not comparable and must not share a column without a discriminator.

`score` is never rendered as a number to a user. It crosses the serve boundary inside `Calibrated`,
which carries the raw value, a `CalStatus`, the bucket's empirical accuracy and Wilson interval,
`n`, `eval_set_id` and `slice_key`; the renderer consumes the **status**, never the float. An
uncalibrated confidence may print an ordinal name plus `(uncalibrated)` and may **never** print a
numeral, percentage, bar, colour or grade, while remaining usable as an internal filter and sort key
(INV-19). The calibration machinery belongs to [quality](13-quality.md).

### 8.5 How confidence composes

Four composition situations, four rules. All four are host-side and none is a driver's choice.

**(a) Merge — two or more blocks become one** (a paragraph rejoined across a column break, two OCR
lines merged, a `continues` pair collapsed by a `derive` pass). Every field, so there is no residue:

| field | rule |
|---|---|
| `kind` | must be identical across inputs, or the merge is refused (`OW_MERGE_KIND_MISMATCH`) |
| `layer` | must be identical across inputs (M-INV-5 makes this automatic within one subtree) |
| `page` | `MIN` over inputs; the merged block belongs to the page it starts on |
| `parent`, `ord`, `addr`, `cite`, `id` | the merged block is a **new** block with a fresh id and cite; the inputs are retired through `block_history` with `reason='reparse_resegmented'` and `superseded_by` pointing at it |
| `text` | the concatenation the merger produced, NFC-normalised once at the end |
| `trust` | `MIN` over inputs |
| `quote` | `MIN` over inputs, then further reduced to `REFLOWED` if the merge inserted or removed any character (which a join across a break always does) |
| `score` | survives **only** if every input shares one `score_kind`; then it is the `MIN`. Otherwise both columns are NULL |
| `method` | the input method with the **lowest `MAX_TRUST_BY_METHOD`**, ties broken by declaration order in `Method`. `MIN` over `Method` is undefined because `Method` is a `StrEnum`; keying on the trust ceiling is well-defined and cannot widen the merged block's trust |
| `origin` | one span covering `[min(start), max(start+len))` **iff** every input is the same variant, the same `part`, and the spans are contiguous or overlapping; identical `nodepath`s collapse to themselves; anything else is `OriginNone()` |
| `span` | NULL. A merged block's text is the whole of its own text |
| `quad` | NULL, unless the merging pass supplies one it measured. A union rectangle over two real quads is not measured geometry and INV-9 forbids it. The serializer's `continues` join (§16.1) creates no block at all, so it never faces this |
| `marks` | union, with offsets rebased; a mark that spanned a removed character is shortened, never dropped |
| `payload` | merged key-wise only when every input agrees on every shared key; a disagreement drops the key and emits `Diag(OW_MERGE_PAYLOAD_DROPPED, info)` |
| `restriction_bits` | bitwise `OR` |
| `x` | union; a key present in two inputs with different values is dropped, for the same reason as `payload` |

Minimum is the only composition that cannot overstate. There is no averaging anywhere in this table.

**(b) Derive — a new block produced from existing ones** (a table synopsis, a summary, an OUT
placeholder read back):

- `quote` is computed from the derived block's **own** `OriginSpan` under §8.3's clamp, and the
  second clamp puts it at `SYNTHETIC` because `origin_operator` is not `parse.*`. A derived block is
  never `VERBATIM` by inheritance. The exception is `read_back`, whose `origin_operator` **is**
  `parse.<target>` and which reads a real artefact part, so it can reach `NORMALIZED` honestly.
- `trust <= MIN(inputs)` and additionally clamped by `MAX_TRUST_BY_METHOD` for the deriving method.
- `restriction_bits` is the `OR` of the inputs' (INV-16), and it travels: this is why a restricted
  source blocks the OUT direction three layers away.
- `rel(kind=derived_from)` records every input, so `locate()` can walk back to a polygon.

**(c) Escalation — the same region read twice at different rungs.** The higher rung's blocks
**replace** the lower rung's; they do not merge. The lower generation's rows are retired through
`block_history` with `reason='reparse_resegmented'`. The free quality channel `agree.decode_vs_page`
— the normalised edit distance between the two independent readings — is computed and stored as a
`route_signal`, has `TruthKind = "agreement"`, and **may never populate an accuracy column**.

**(d) Rebind — §6.5.** Identity carries; confidence does not.

### 8.6 Document- and page-level confidence

`doc.confidence` is a JSON object the host computes at `end_doc`, never a driver field:

```json
{"parse": 0.94, "layout": 0.91, "table": 0.87, "ocr": null,
 "n_scored": {"parse": 42, "layout": 42, "table": 6, "ocr": 0}}
```

Each value is the mean of the non-NULL `page.*_score` values, **with NULL pages excluded and the
count published**. A component with `n_scored == 0` is `null`, not `0.0`, and is **excluded from any
aggregate grade** — this is the corrected form of docling's `nanmean` over an all-NaN `table_score`
list (`docling/docling/pipeline/standard_pdf_pipeline.py:867-871`, over a field that
`base_models.py:419` defaults to `np.nan` and nothing ever assigns), where the published grade was a
three-component mean wearing four. `page.table_score` itself is the mean of that page's
`table_meta.recon_score` values, or NULL when the page has no scored table.

`Capabilities.confidence` declares the granularity a driver offers: `none | document | page |
element`. A driver declaring `element` and returning no `score` on any block fails the conform
`capability` suite in the absent direction.

## 9. Diagnostics: failure is a field

```python
@dataclass(frozen=True, slots=True)
class Diag:
    code: str; severity: Literal["error","warning","info"]; component: str; message: str
    page: int | None = None; block: BlockId | None = None; part: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict); fatal: bool = False
```

`Diag` is **recorded**; `OwError` is **raised**. Two names for two things, and the model's half is
the recorded one. `diag.code` holds the **symbol** from `codes.toml` (`OW_TABLE_SPAN_CLAMPED`), never
the numeric — callers branch on the symbol, and the CLI prints the numeric. `CREATE INDEX diag_code`
exists specifically so the absence contract can join against it: a "no results" answer is only
`absent` after fifteen gates pass, and one of them (`parse_gap_in_scope`) reads exactly this table.

`diag` rows are written inside the page transaction that produced them, so a diagnostic about page
3,000 survives a crash at page 3,001 — and, like every other staged row, it is invisible until the
`doc.gen` bump and swept if the generation is abandoned. `diag.block_id` is deliberately **not** a
foreign key: a diagnostic often concerns a block the parse then refused to write, and a FK would
force the model to choose between losing the diagnostic and writing a block it rejected.

A limit breach is never swallowed: `fatal = true` on a `RESOURCE_LIMIT` diag and the document's
`status` becomes `partial`, with the coverage gap surfacing in `corpus_card` before any query runs.
The full code register and the "every message ends with the command that clears it" rule belong to
[observability](15-observability.md); the model's obligation is that every recoverable producer quirk
lands here rather than in an exception, which is anydoc's stated discipline
(`anydoc/src/error.rs`: an error means a complete conversion was impossible; recoverable quirks are
recovered or skipped while conversion continues).

## 10. Tables

This is the hardest single modelling problem in the document model, because one representation has
to serve four consumers with incompatible instincts:

1. **Round-trip into PPTX/DOCX/XLSX** wants the original grid with spans, the original part bytes,
   and per-cell formatting.
2. **Semantic chunking** wants a linear token stream with the header row repeated, bounded by
   `MAX_SEGMENT_TOKENS`.
3. **Cell-level query** wants `up/down/left/right/top_heading/left_heading` in O(1) — exactly
   olmOCR-Bench's table relations (`olmocr/olmocr/bench/miners/mine_tables_gemini.py:234-235`,
   `:261-263`: `left`, `up`, `top_heading`, `left_heading`).
4. **Citation** wants every cell to be an independently addressable, citable, polygon-bearing thing.

The design that serves all four: **a cell is an ordinary Block**, the grid cover map is **derived
and lazily materialized**, and no type anywhere has an `html` field.

### 10.1 The representation

```sql
CREATE TABLE table_meta (
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  n_rows INTEGER NOT NULL, n_cols INTEGER NOT NULL,   -- n_cols = max(row_len); rows may be RAGGED
  row_len TEXT NOT NULL,           -- JSON int array: raggedness is EXPLICIT, never implied
  header_rows INTEGER NOT NULL DEFAULT 0, header_cols INTEGER NOT NULL DEFAULT 0,
  kind INTEGER NOT NULL,           -- data|layout  (a layout table is unwrapped by the SERIALIZER)
  recon_strategy TEXT,             -- native_xml|span_x0|span_center|proj_1|proj_3|proj_10|
                                   -- tableformer|vlm|human
  recon_score REAL,                -- marker's judge score, KEPT (marker computes then discards it)
  has_merges INTEGER NOT NULL DEFAULT 0,   -- 0 => grid_slot is EMPTY and slot(r,c) is arithmetic
  native_part TEXT, native_sha256 BLOB     -- hash-pinned original part => passthrough export
);
CREATE TABLE cell (                -- ORIGIN cells only; a cell IS a Block
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,
  r INTEGER NOT NULL, c INTEGER NOT NULL,
  row_span INTEGER NOT NULL DEFAULT 1, col_span INTEGER NOT NULL DEFAULT 1,
  UNIQUE (table_id, r, c)
);
CREATE TABLE grid_slot (           -- DERIVED cover map. Materialized ONLY when has_merges = 1,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,  -- capped at
  r INTEGER NOT NULL, c INTEGER NOT NULL,                                       -- MAX_GRID_SLOTS
  origin_id INTEGER NOT NULL REFERENCES cell(block_id) ON DELETE CASCADE,
  PRIMARY KEY (table_id, r, c)
) WITHOUT ROWID;
```

```python
@dataclass(frozen=True, slots=True)
class Origin:  block: BlockId; r: int; c: int; row_span: int = 1; col_span: int = 1
@dataclass(frozen=True, slots=True)
class Covered: origin_r: int; origin_c: int
Slot = Origin | Covered

class Grid:                         # PRIVATE ctor. build_grid() is the only way in.
    n_rows: int; n_cols: int; row_len: tuple[int, ...]   # raggedness is EXPLICIT
    header_rows: int; header_cols: int
    kind: Literal["data","layout"]
    recon: tuple[str, float | None] | None
    has_merges: bool
    native: tuple[str, bytes] | None                      # (part, sha256) => passthrough export
    def slot(self, r: int, c: int) -> Slot | None: ...    # O(1), resolves to exactly one Origin
    def origin(self, r: int, c: int) -> Origin | None: ...
    def up(self, r, c); def down(self, r, c); def left(self, r, c); def right(self, r, c)
    def top_heading(self, c) -> tuple[Origin, ...]: ...   # a CHAIN, outermost first
    def left_heading(self, r) -> tuple[Origin, ...]: ...
    # NOTE: no .html and no .markdown. Those are renders: render_grid(g, reader, fmt).
```

**The exactly-once invariant.** Every logical grid position `(r, c)` with `r < n_rows` and
`c < row_len[r]` resolves to **exactly one** `Origin`. Content and spans live only on the origin
slot; every covered position points back at its origin. This is anydoc's
`CellSlot::Covered { origin_row, origin_col }` (`anydoc/src/model/table.rs`), and it is strictly
better than a sparse cell list with spans because every coordinate is addressable — which is
precisely what "which cell is above this one" needs.

**Extends the charter — `grid_slot` is total when it exists.** The charter's own neighbour query is
`SELECT origin_id FROM grid_slot WHERE table_id=?1 AND c=?2 AND r=?3-1`, which returns nothing for
an unmerged position unless `grid_slot` covers **every** position. So: when `has_merges = 1`,
`grid_slot` holds all `sum(row_len)` positions, an origin position mapping to itself. When
`has_merges = 0` the table has **zero rows** of `grid_slot` and `slot(r, c)` is arithmetic against
`cell`. A merge-free 4M-cell spreadsheet is 4,000,000 ordinary Blocks and zero `grid_slot` rows.

### 10.2 `build_grid` — the sole constructor, and it streams

```python
def build_grid(cells: Iterable["CellDraft"], *, header_rows: int = 0, header_cols: int = 0,
               kind: str = "data", recon: tuple[str, float | None] | None = None,
               diag: Callable[["Diag"], None]) -> Grid: ...
```

It registers covered positions, later placements skip them, and **overlapping spans are clamped** to
what the origin can actually own — anydoc's verified behaviour at
`anydoc/src/model/table.rs:179-197`, with the comment stating the reason: "Clamp the spans to
positions this origin can actually own — an overlap with an earlier span would break the exactly-once
invariant". Every clamp emits `Diag(OW_TABLE_SPAN_CLAMPED)` and forces the table's `trust` to
`INFERRED`. Clamping rather than raising is deliberate: overlapping rowspans are routine in
hand-written HTML, so raising would be fail-closed on **common** input, which is a different thing
from fail-closed on adversarial input. The span area is charged against `MAX_EXPANSION` **before**
expanding — anydoc's own pre-check, whose refusal reads "table span expansion exceeds the content
budget" (`table.rs:175`) — so a tiny document carrying `rowspan="99999"` cannot force unbounded work.

**Extends the charter — the parameter is an `Iterable`, not a `Sequence`, and this is the fix for the
hardest scale problem in the section.** The charter celebrates "a merge-free 4M-cell sheet is
4,000,000 ordinary Blocks and ZERO `grid_slot` rows" while typing `build_grid`'s input as a resident
`Sequence`. Four million `CellDraft`s is 4M × 24 B of position data plus 4M `BlockId`s — tolerable —
but the naive implementation that buffers the whole grid to detect merges is not, and the naive
implementation that buffers the cells' *drafts* is 4.4 GB. The streaming contract:

- Cells arrive in **row-major origin order** (non-decreasing `r`, and within a row increasing `c`).
  `add_grid` asserts it. A driver that cannot guarantee it gets a resident buffer bounded by
  `MAX_RESIDENT_CELLS = 65_536`, above which the table is `RESOURCE_LIMIT{MAX_RESIDENT_CELLS}`.
- The resident state is `row_len` (one integer per row), a **covered bitmap** for the rows still
  reachable by an open `row_span` — `max(row_span) × n_cols` bits, 500 KB for a 4M-cell grid with a
  4-row span — and the origin map **only for merged origins**, which is empty for the merge-free
  case. Nothing else is held.
- `has_merges` is discovered incrementally: it is 1 as soon as any cell has a span > 1. `cell` rows
  are written as they arrive; `grid_slot` rows are written only after `has_merges` is known to be 1,
  in one pass over the completed `row_len` — which is why `add_grid` is called once, at the end.
- `MAX_EXPANSION = 4_000_000` is charged incrementally against the running total, so the refusal
  happens on the cell that crosses it, not after 4M allocations. It is set **equal to
  `MAX_GRID_SLOTS = 4_000_000`** and a test asserts the equality, because a table that can be built
  and then cannot be stored is the worst of both numbers.

`CellDraft` carries an already-minted `BlockId` and its `CellPos`; the host minted the cell's
`block_id`, `addr` (`.../r<r>c<c>`, from `BlockDraft.cell`) and `cite` at `add_block` exactly as for
any other block (§2.6).

### 10.3 A merged-cell table with a header hierarchy, fully represented

```
            c0                c1              c2
    +------------------+---------------+---------------+
r0  |                  |           FY2024              |   (0,1) col_span=2
    |     Segment      +---------------+---------------+
r1  |  row_span=2      |      Q1       |      Q2       |
    +------------------+---------------+---------------+
r2  | Cloud            |     1,204     |     1,388     |
    +------------------+---------------+---------------+
r3  | Devices          |       902     |       871     |
    +------------------+---------------+---------------+
```

`table_meta` for the table block at `p1/0/1` (`block_id = 8`, `cite = d7#8`):

```
n_rows=4  n_cols=3  row_len=[3,3,3,3]  header_rows=2  header_cols=1
kind=data  recon_strategy='native_xml'  recon_score=1.0  has_merges=1
native_part='word/document.xml'  native_sha256=<32 B>
```

`cell` — **origin cells only**; the ten origins, not twelve positions:

| `block_id` | `addr` | `cite` | r | c | row_span | col_span | `text` |
|---|---|---|---|---|---|---|---|
| 9  | `p1/0/1/r0c0` | `d7#9`  | 0 | 0 | 2 | 1 | `Segment` |
| 10 | `p1/0/1/r0c1` | `d7#10` | 0 | 1 | 1 | 2 | `FY2024` |
| 11 | `p1/0/1/r1c1` | `d7#11` | 1 | 1 | 1 | 1 | `Q1` |
| 12 | `p1/0/1/r1c2` | `d7#12` | 1 | 2 | 1 | 1 | `Q2` |
| 13 | `p1/0/1/r2c0` | `d7#13` | 2 | 0 | 1 | 1 | `Cloud` |
| 14 | `p1/0/1/r2c1` | `d7#14` | 2 | 1 | 1 | 1 | `1,204` |
| 15 | `p1/0/1/r2c2` | `d7#15` | 2 | 2 | 1 | 1 | `1,388` |
| 16 | `p1/0/1/r3c0` | `d7#16` | 3 | 0 | 1 | 1 | `Devices` |
| 17 | `p1/0/1/r3c1` | `d7#17` | 3 | 1 | 1 | 1 | `902` |
| 18 | `p1/0/1/r3c2` | `d7#18` | 3 | 2 | 1 | 1 | `871` |

There is **no** `cell` row at `(1,0)` or `(0,2)`: those positions are covered, not empty. The ten
cells' `ord` values among the table's children are 0-9 in that order — row-major over origins, dense
from 0, exactly as §6.2 requires.

`grid_slot` — twelve rows, because `has_merges = 1`:

```
(r,c) -> origin_id       (r,c) -> origin_id       (r,c) -> origin_id
(0,0) -> 9               (0,1) -> 10              (0,2) -> 10    <- covered by the FY2024 colspan
(1,0) -> 9   <- covered  (1,1) -> 11              (1,2) -> 12
(2,0) -> 13              (2,1) -> 14              (2,2) -> 15
(3,0) -> 16              (3,1) -> 17              (3,2) -> 18
```

Each of the four consumers, answered from exactly this:

**Cell-level query.** `grid.up(2,1)` is one indexed read: `SELECT origin_id FROM grid_slot WHERE
table_id=8 AND c=1 AND r=1` -> block 11 (`Q1`). `grid.left(2,1)` -> block 13 (`Cloud`).

**Header hierarchy.** `top_heading(c)` returns the **chain** of distinct origins covering rows
`0 .. header_rows-1` in column `c`, outermost first — not a single cell, because `header_rows > 1`
is exactly the case that matters. `top_heading(1)` is `[Origin(10, "FY2024"), Origin(11, "Q1")]`;
`top_heading(2)` is `[Origin(10, "FY2024"), Origin(12, "Q2")]` — note that both columns share the
`FY2024` origin, which is the whole point of the cover map. `left_heading(2)` is
`[Origin(13, "Cloud")]` from `header_cols = 1`. **Extends the charter:** D2 gives the signatures and
not the return type; a chain is specified here.

So the semantic address of the value `1,204` is `Segment=Cloud, FY2024 > Q1`, derived, not stored,
and every element of it is independently citable (`d7#13`, `d7#10`, `d7#11`, `d7#14`).

**Semantic chunking.** L2's obligation is that the traversal is answerable in O(1) per position and
that a covered position is emitted **once**, at its origin: the segmenter walks `(r, c)` in row-major
order through `grid_slot`, prefixes each data row with its `left_heading` chain and each value with
its `top_heading` chain, and repeats the `header_rows` block into each segment the table spills into.
The constants (`TABLE_SEGMENT_TOKENS`, `SEM_BLOCKS_PER_SEGMENT`), the header-repetition policy and
the table-synopsis rule are [structure extraction](06-structure-extraction.md)'s.

**Round-trip.** `native_part`/`native_sha256` give byte passthrough for an untouched table. When the
table *was* touched, the compiler rebuilds it from `cell` + `grid_slot`: `row_span`/`col_span` map
directly onto `a:gridSpan`/`a:vMerge` (PPTX) and `w:gridSpan`/`w:vMerge` (DOCX), and the covered
positions are exactly the `vMerge continue` cells. Nothing needs inferring, because nothing was
flattened. See [generation](09-generation.md).

**Rendering, and where the loss is.** GFM has no span syntax, so `render_grid(g, reader, "gfm")`
renders `Covered` slots as blank cells, pops trailing all-blank rows, truncates trailing all-blank
columns, joins multi-line cell content with `<br>`, and emits a synthetic empty header row when
`header_rows == 0` because GFM requires a delimiter row. **The loss is at render time only; the
model keeps everything.** `otsl` is the lossless table serialization for a model context and
preserves spans.

**Raggedness is explicit.** `n_cols = max(row_len)` and `row_len` is a JSON int array. A ragged HTML
table is not padded with phantom cells and is not rejected; the projection pads at render time
because GFM requires it, and the model keeps the truth.

**`kind = layout`** marks a table used for positioning (DOCX text placement, HTML layout scaffolds).
The **serializer** unwraps a trivial layout table; the model never does. anydoc is the only repo in
the collection that makes this distinction, and it matters: a layout table rendered as a data table
is pure noise in a chunk.

### 10.4 What was rejected

- **`block.html` plus a `structure` list.** Forfeits per-cell polygons, spans, raggedness and the
  reconstruction score in one assignment. Eleven of the mined parsers hand downstream a string, and
  nothing needing citation-to-pixel or round-trip can be built on their output at all.
- **A separate bulk `dataset` table kind above 50k cells.** The lazily-materialized cover map removes
  the wart outright: the expensive thing about a big table was never the cells, it was the cover map,
  and an unmerged table does not need one.
- **`build_grid` raising on overlapping spans.** Fail-closed on common input is a bug.
- **Storing `recon_score` nowhere.** marker computes a table-reconstruction judge score and then
  discards it. It is kept here, and it is what `page.table_score` is derived from.
- **A `cell` FK from `grid_slot` to `block` rather than to `cell`.** `origin_id REFERENCES
  cell(block_id)` is narrower and it is deliberate: it makes "an origin that is not a cell of this
  table" unrepresentable rather than merely wrong.

## 11. Assets

```sql
CREATE TABLE asset (
  asset_id INTEGER PRIMARY KEY,
  doc_ord  INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  origin_part TEXT,               -- anydoc's origin_part, unique in the collection
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL, width INTEGER, height INTEGER,
  store_ref TEXT NOT NULL,        -- cas://ab/cd/<sha256>   NO INLINE BYTES, EVER
  licence TEXT, licence_url TEXT, spdx TEXT, source_url TEXT, retrieved_at_ns INTEGER,
  restriction_bits INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX asset_identity ON asset(doc_ord, sha256, IFNULL(origin_part,''));
CREATE TABLE block_asset (
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id) ON DELETE CASCADE,
  role TEXT NOT NULL,             -- image|thumbnail|source_crop|ole|chart_data|bake|font
  PRIMARY KEY (block_id, asset_id, role)
) WITHOUT ROWID;
```

**Storage.** Bytes live in the content-addressed store at `.omniweave/cas/ab/cd/<sha256>`, addressed
by `store_ref = "cas://ab/cd/<sha256>"`. There are **no inline bytes, ever** — not in the table, not
in a JSON column, not base64 in an archive member. A 40 MB embedded TIFF must not be loaded to
answer "how many figures are in this document".

**Addressing and dedup.** Identity is `(doc_ord, sha256, origin_part)`. The `IFNULL('')` sentinel is
mandatory: SQL NULLs are each distinct, so a nullable natural key makes `INSERT OR IGNORE`
degenerate into a plain INSERT — codegraph #1034 produced byte-identical duplicates that inflated
counts and flowed into callers. Two blocks referencing the same logo produce **one** `asset` row and
two `block_asset` rows. Two *documents* embedding the same logo produce two `asset` rows and **one**
CAS object: dedup is per-corpus at the row level (so licence facts and `restriction_bits` stay
per-document) and global at the byte level. A company handbook corpus with a logo on every page of
400 documents stores the logo once on disk.

**`asset` is keyed on `doc_ord`, not on `(doc_ord, gen)`, and that is deliberate.** An asset's
identity is its bytes, which do not change when a document is re-parsed; the *links* are
generation-scoped, through `block_asset` to blocks that carry a `gen`. A re-parse that no longer
references an image leaves the `asset` row with zero live `block_asset` rows, which is what
`ow store gc` sweeps — a CAS object is deleted only when no `asset` row in any corpus references
its digest.

**`doc_ord` is `NOT NULL`, and a compile-produced asset is no exception.** `bake` output belongs to
no ingested document, so the compile job writes a synthetic job document (`format = 'owjob'`, §2.8)
and its assets hang off that row. `doc_ord` is **not** made nullable: `asset_identity` folds every
`NULL` as distinct, so identical bake output would produce unbounded duplicate rows, and a row owned
by no document has no answer for the compile-time restriction aggregate.
[Generation](09-generation.md) §7.1 owns the job row and the `ON DELETE CASCADE` refusal that keeps
`ow store rm --doc <ord>` from taking an artefact's bytes with it.

**`origin_part` is provenance for a binary blob at basically zero cost** — anydoc's decision, where
`Asset.origin_part: String` is documented "Package part or stream the asset came from, for
provenance" (`anydoc/src/model/asset.rs:14-15`) and is not even optional. It is unique in the
collection. It is what lets an OUT compiler re-emit the exact media part it came from, and what makes
`artifact_asset`'s ledger join meaningful.

**Lazy loading.** `Doc.asset(ref) -> BinaryIO` returns a **stream**, never bytes.
`DocSink.add_asset(draft, blob: BinaryIO)` **streams** into CAS, hashing as it goes, so a driver
emitting a 200 MB video never materialises it. `MAX_ASSET_BYTES = 268_435_456` (charter §6.10) is
enforced at the read boundary with `take(N+1)`-then-check, so the limit is not discovered after the
memory is spent, and with a content-length pre-check where the source offers one (OUT10).

**The digest the driver claims is not the digest we store.** `AssetDraft.sha256` is the driver's
claim; `add_asset` hashes the stream itself and writes its own result, and a disagreement is
`OW_ASSET_DIGEST_MISMATCH` with the asset rejected. Otherwise a driver could point `store_ref` at an
existing CAS object belonging to another document — a content-addressed store with an unverified
writer is a substitution oracle.

**Fonts** are assets with `role = "font"`. An embedded font subset matters for two things: OUT
fidelity (a deck that must render with the source's typography) and text-extraction diagnosis (a
subset font with a broken `/ToUnicode` is why a PDF's text layer is garbage). The font's own licence
facts go in `licence`/`spdx` and its `restriction_bits` propagate — a no-redistribution font blocks
`compile` exactly as a restricted image does.

**Page renders are not assets of the document; they are a derived, evictable cache.**

```sql
CREATE TABLE page_render (
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, page INTEGER NOT NULL,
  dpi INTEGER NOT NULL, renderer TEXT NOT NULL, renderer_version TEXT NOT NULL,
  colorspace TEXT NOT NULL, asset_id INTEGER NOT NULL REFERENCES asset(asset_id),
  last_used_ns INTEGER NOT NULL,
  PRIMARY KEY (doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)
) WITHOUT ROWID;
```

A decoded 192-DPI A4 page is **10.7 MB**, and the arithmetic is the whole argument: A4 is
8.27 × 11.69 in, so at 192 DPI it is 1,588 × 2,245 px = 3,565,060 px, and at 3 B/px (RGB8) that is
10.70 MB. Four pages is 42.8 MB; 5,000 pages is 53.5 GB. That is why **rendering follows routing**
and is never a model field. `Doc.page_render(page, dpi)` renders on miss and returns an `AssetRef`;
the cache is swept by `last_used_ns` under the `render` cache layer. marker renders high-resolution
page images only for pages whose `text_extraction_method == "surya"` or which hold a `Table`, `Form`,
`TableOfContents`, `Equation` or `ChemicalBlock` (`marker/marker/builders/document.py:37-46` for the
set and `:67-71` for the predicate) — the single cheapest optimization in that repo, and the same
rule applies here one layer up, in the router.

**`chart_data`** is the role for a chart's underlying series (`chart1.xml`, an embedded XLSX part).
Keeping it as an asset rather than parsing it into blocks is deliberate: a chart's data is a table
the *source* already models, and re-modelling it as cells would invent a grid the file does not have.
An OUT compiler that must edit a chart reads the part back.

## 12. Reading order, sections and multi-page constructs

### 12.1 Reading order

**`ord` among siblings is reading order.** There is no separate `position`, `reading_order` or
`z_index` field, and there is no `ord_path`. A full-document render is
`SELECT ... ORDER BY page, ord` over the partial index `block_read(doc_ord, gen, page, ord) WHERE
state = 0` — a range scan, not a sort.

A gap-allocated order key was rejected: it has one consumer, one implementation and a motivating
workload (interactive insertion into a stored generation) that does not exist, because **OUT edits
always write a new generation** and nothing patches a sealed one.

`Capabilities.reading_order` records how the order was obtained, ordered
`raster < learned < model_emitted < char_stream < source`. The ordering is not a preference; it is
marker's measurement: a char-stream order beat a learned layout head 75% to 56% on olmocr-bench's
order tests (`marker/marker/builders/line.py:77-84`), and a native format's own order (`source`) is
canonical by construction. A driver that sorted boxes top-to-bottom-left-to-right declares `raster`
and is correctly ranked below one that read the PDF's content-stream order.

**`ord` is dense from 0 among siblings and is not a stable name.** Reading order is the one fact the
model stores twice-implied — once as `ord`, once as the `(page, ord)` scan order — and they are made
to agree by construction: `ord` is assigned by `DocSink` in the order the driver emits children, and
`addr`'s first step is a separate per-page counter (§6.2) precisely so that nothing derives a name
from `ord`.

### 12.2 Multi-column

Multi-column layout is resolved **at parse time into one sibling order**. The model has no column
concept, because a column is a layout fact, not a content fact, and every downstream consumer wants
the linearised order. What survives is:

- a `container` block with `payload.role = "column"` when the driver knows the region boundaries, so
  a renderer can restore the two-column layout and a chunker can avoid interleaving two columns'
  paragraphs into one segment;
- the per-block `quad`, from which column membership is re-derivable;
- `Capabilities.reading_order`, which tells a consumer how much to trust the linearisation.

A driver that cannot resolve columns emits blocks in raster order, declares
`reading_order = "raster"`, and the corpus card discloses it.

### 12.3 The containment spine, pages, and constructs that cross a page

The spine is **one forest, rooted at the single `document` block**, and it is committed page by page:
`DocSink.end_page()` **commits one transaction**. Two rules follow, and together they are what lets a
5,000-page document be ingested without ever being resident.

**M-INV-1 (parent-before-child).** `parent.page <= child.page`, and within a page a parent is written
before its children. A forward reference is impossible, so a page's transaction is self-contained and
`parent_id` is always a committed row.

**M-INV-2 (addr anchoring).** `addr`'s page component is the page of the block's **topmost ancestor
below the `document` root**. For every block that does not belong to a page-crossing construct this
equals `block.page`.

**Extends the charter.** D2 fixes neither rule explicitly; both are forced by `end_page()` committing
a transaction and by `addr` being a child-index path from a page root. Together they decide the
multi-page case:

- **A table crossing a page break is ONE `table` block** at the first page, whose cells carry their
  own `page`. Cell-level query, header hierarchy and round-trip all keep working across the break,
  which is the whole reason to model it this way; `Doc.blocks(pages=range(4,5))` filters on
  `block.page` and returns the page-4 cells without the page-3 table block. The cost is stated: the
  table's `content_digest` is provisional until the closure pass (§6.4), and `add_grid` runs in the
  transaction of the table's **last** page, referencing cell ids committed in earlier ones.
- **A paragraph broken across a page or column** is two blocks when the driver keeps them separate,
  joined by `rel(kind=continues)` from the first to the second, and one block at
  `quote <= REFLOWED` when the driver joins them. Both are legal; `achieved.reading_order` and the
  `continues` edges tell a consumer which happened. A `continues` chain is a path, never a cycle;
  `owcheck` asserts acyclicity over `rel(continues)`.
- **A list crossing a page** is one `list` container with `list_item` children on both pages.

`rel(continues)` is the only intra-document relation that expresses "these are one logical unit
split into two blocks", and the serializer joins across it (§16.1) when rendering body text.

### 12.4 Section hierarchy

L2 stores the **inputs** to the hierarchy and L3 stores the derived index. The split, in one line
each:

- **L2's contribution** is `Kind.HEADING` with `payload.level`, `Kind.TITLE`, `Kind.SECTION` for a
  source that carries typed levels, the `anchor` **mark** at a definition site, and
  `rel(anchor_ref)`/`rel(heading_of)` at an occurrence site. Nothing else. A heading's level is a
  payload key rather than a column precisely so that promoting a paragraph to a heading does not
  change the block's field set.
- **`block_sec`** — the derived prefix index (`sec_id`, `sec_depth`, `sec_path` like `/1/4/2`), one
  row per block, so "everything under §4.2" is a prefix range scan. It is a `[DER]` object, not an
  ordering authority and not an identity, and its derivation rule, the skipped-level policy and
  `segment.heading_path` all belong to [structure extraction](06-structure-extraction.md)
  (charter §5 X26: two shapes, one computation).

`Capabilities.sections` declares what the driver could see: `none`, `markdown_only` (levels inferred
from `#` counts), `outline_from_source` (a PDF outline / bookmark tree), `typed_levels` (real
structural levels). A `none` driver produces a document with one implicit section and the corpus
card says so, because "everything under §4.2" is unanswerable on it.

The **anchor** side — what a document *defines*, over the fourteen-member `AnchorKind` vocabulary —
and the **reference** side (`ref_site`, `block_link`) are L3's.

### 12.5 Page kinds

| `page_kind` | `page` means | `w_mpt`/`h_mpt` | typical `addr` |
|---|---|---|---|
| `page` | a printed page, 0-based, **the original index** | the page box | `p14/3` |
| `slide` | a slide index | the slide size | `p7/2` |
| `sheet` | a worksheet index; the sheet name is `page.label` | NULL unless the sheet has a print area | `p0/1/r99c3` |
| `frame` | a video frame or an animation state | the frame size | `p120/0` |
| `stream` | there are no pages: HTML, markdown, code, plain text, email. Always `page = 0` | NULL | `p0/12` |

`page` is **never a batch index**. A driver that processed pages 40-59 as batch 2 writes 40-59, and
the conformance kit's `limits` suite ships a fixture that would pass under batch indexing and fails.
`page.label` carries the printed label (`"iv"`, `"A-3"`) separately, because a citation that says
"page 4" when the document says "page iv" is wrong in the way a user notices.

A `stream` document still has exactly one `page` row (page 0) and one `document` root, so the
`(doc_ord, gen, page)` foreign key holds without a special case, and `p0/12` addresses the
thirteenth page-root block of a markdown file.

## 13. Serialization: at rest, on the wire, and streaming

### 13.1 At rest — `.omniweave/index.owstore`

One SQLite file per corpus. L3 and L4 **add tables and indexes to this file**; they never add a
second representation of a Block. Pragma order is load-bearing — `busy_timeout` **first**, because a
contended open crashes otherwise (codegraph #238).

```sql
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA cache_size   = -64000;      -- 64 MB
PRAGMA temp_store   = MEMORY;
PRAGMA mmap_size    = 268435456;   -- 256 MB
-- INIT (per file): journal_size_limit = 67108864.  CREATE only: page_size = 8192,
-- auto_vacuum = INCREMENTAL.

CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- container_version · model_version · min_reader · digest_recipe · segment_recipe · corpus_id
-- · writer_version · graph.resolve_signature

CREATE TABLE enum_val (domain TEXT NOT NULL, ord INTEGER NOT NULL, name TEXT NOT NULL,
                       PRIMARY KEY (domain, ord)) WITHOUT ROWID;
-- CLOSED domains only: kind, layer, trust, method, quote, page_kind, table_kind, rel_kind,
--                      origin_span_kind, lane, akind, alias_kind, claim_status, taint, precision.
-- `format` is NOT one of them: a format token is free text over a COMPUTED domain (05 section 2.2),
--                      so a minted token such as `owjob` (section 2.8) changes no row here.
-- `ord` IS THE STORED VALUE and is APPEND-ONLY (§2.1). For an ordered IntEnum it is the member's
-- integer; for a StrEnum it is declaration order and carries no ordering meaning.

CREATE TABLE block (
  block_id   INTEGER PRIMARY KEY,            -- DURABLE surrogate; the only FK target FOR A BLOCK
  doc_ord    INTEGER NOT NULL,
  gen        INTEGER NOT NULL,
  page       INTEGER NOT NULL,
  addr       TEXT    NOT NULL,               -- 'doc' | 'p14/3' | 'p14/3/r2c5'  -- TYPE-FREE
  cite       TEXT    NOT NULL,               -- 'd7#412'  -- prompts ONLY (INV-8)
  parent_id  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  ord        INTEGER NOT NULL,               -- position among siblings == READING ORDER
  kind       INTEGER NOT NULL,               -- closed vocab, FK into enum_val
  raw_kind   TEXT,                           -- the producer's own label, KEPT
  layer      INTEGER NOT NULL,               -- inherited from the parent unless a page root
  label      TEXT,                           -- a human label for a CONTAINER (§2.5); NOT Kind.TITLE
  text       TEXT,                           -- PLAIN text, fully resolved, NFC. NULL on containers.
  content_digest BLOB NOT NULL,              -- ow128, merkle. GEOMETRY IS NOT AN INPUT.
  layout_digest  BLOB,                       -- NULL when the block has no geometry
  revision   INTEGER NOT NULL DEFAULT 0,
  quad       BLOB,                           -- 8 x i32 LE, or NULL
  os_kind    INTEGER NOT NULL,               -- bytes|nodepath|glyphs|pixels|none
  os_part    TEXT, os_a INTEGER, os_b INTEGER, os_path TEXT,
  os_extractor TEXT, os_codec TEXT,          -- os_b is a LENGTH (§7.2)
  ts_a       INTEGER, ts_b INTEGER,          -- a half-open RANGE
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method     INTEGER NOT NULL,
  trust      INTEGER NOT NULL,               -- 0=ambiguous 1=inferred 2=extracted
  score      REAL, score_kind TEXT,
  quote      INTEGER NOT NULL,               -- 0=synthetic … 4=verbatim. ORDERED.
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  decision_id TEXT REFERENCES route_decision(decision_id),
  payload    TEXT,                           -- JSON, kind-discriminated, schema-validated
  state      INTEGER NOT NULL DEFAULT 0,     -- 0=live 1=tombstone. There is no DELETE.
  x          TEXT    NOT NULL DEFAULT '{}',
  FOREIGN KEY (doc_ord, gen, page) REFERENCES page(doc_ord, gen, page) ON DELETE CASCADE,
  CHECK (parent_id IS NULL OR parent_id <> block_id),
  CHECK ((os_a IS NULL) = (os_b IS NULL)),
  CHECK ((ts_a IS NULL) = (ts_b IS NULL)),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  CHECK (os_b IS NULL OR os_b >= 0),                      -- a LENGTH
  CHECK (ts_a IS NULL OR ts_a <= ts_b),                   -- a RANGE
  CHECK (length(addr) <= 512),
  CHECK (raw_kind IS NULL OR length(raw_kind) <= 128),
  CHECK ((os_path IS NOT NULL) <= (os_part IS NOT NULL)),
  CHECK ((os_extractor IS NOT NULL) <= (os_part IS NOT NULL)),
  CHECK (os_kind <> 3 OR quad IS NOT NULL),               -- 3 == OsKind.PIXELS, interpolated (§7.2)
  CHECK (os_kind <> 0 OR os_codec IS NOT NULL),           -- 0 == OsKind.BYTES; the branch decodes (§7.2)
  CHECK ((block_id >> 48) = 0)                            -- shard ordinal, interpolated
);
CREATE UNIQUE INDEX block_addr ON block(doc_ord, gen, addr);   -- addr is POSITIONAL: gen-keyed
CREATE UNIQUE INDEX block_cite ON block(doc_ord, cite);        -- cite is DURABLE: GEN-FREE
CREATE UNIQUE INDEX block_sib  ON block(doc_ord, gen, IFNULL(parent_id,-1), ord);
CREATE INDEX block_read   ON block(doc_ord, gen, page, ord) WHERE state = 0;  -- full render = scan
CREATE INDEX block_parent ON block(parent_id, ord)          WHERE state = 0;
CREATE INDEX block_kind   ON block(doc_ord, gen, kind, page, ord) WHERE state = 0;
CREATE INDEX block_cdig   ON block(doc_ord, content_digest);                  -- rebind
CREATE INDEX block_review ON block(doc_ord, gen, page) WHERE trust < 2 AND state = 0;
CREATE INDEX block_restricted ON block(restriction_bits) WHERE restriction_bits <> 0;

-- The head-generation projection every reader goes through. Staged rows (gen > doc.gen) are
-- durable and INVISIBLE (§1.1); this view is the mechanism, not a convenience.
CREATE VIEW ow_block_head AS
  SELECT b.* FROM block b JOIN doc d ON d.doc_ord = b.doc_ord
   WHERE b.gen = d.gen AND b.state = 0;

CREATE TABLE block_history (       -- retirement, instead of tombstones that outlive a generation
  block_id INTEGER PRIMARY KEY, doc_ord INTEGER NOT NULL, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER,           -- NULL = retired with no defensible successor
  reason TEXT NOT NULL             -- reparse_resegmented|driver_upgrade|source_deleted|compacted
);

CREATE TABLE rel (                 -- the CLOSED intra-document DAG. Containment is NOT here.
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  src_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  kind INTEGER NOT NULL,           -- caption_of|note_ref|continues|anchor_ref|heading_of|
                                   -- derived_from|supersedes  -- SEVEN, and only seven
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, x TEXT NOT NULL DEFAULT '{}',
  UNIQUE (src_id, dst_id, kind, producer_id)
);
CREATE INDEX rel_dst ON rel(dst_id, kind);
CREATE INDEX rel_src ON rel(src_id, kind);

CREATE TABLE mark (                -- sparse inline formatting over block.text
  mark_id INTEGER PRIMARY KEY,     -- a SURROGATE: two links may cover the same range
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  a INTEGER NOT NULL, b INTEGER NOT NULL,
  kind TEXT NOT NULL, value TEXT,
  CHECK (a >= 0 AND b >= a)
);
CREATE INDEX mark_block ON mark(block_id, a, b);

CREATE TABLE part (               -- named byte streams of the original container, hash-pinned
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  path TEXT NOT NULL,             -- 'file' | 'word/document.xml' | 'pdf:page=12/content=0'
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL,
  store_ref TEXT,                 -- cas://ab/cd/<sha256>   NULL => bytes were not retained
  PRIMARY KEY (doc_ord, path)
) WITHOUT ROWID;

-- The tokenizer, detail and columnsize options below are owned by 07-store-and-retrieval.md
-- §3.3 and carried here verbatim; they may not be changed in this document.
CREATE VIRTUAL TABLE block_fts USING fts5(
  text,
  content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2',
  detail='full',            -- REQUIRED: instance offsets are what ChannelResult.spans carries
  columnsize=1);            -- REQUIRED: bm25() needs per-row length for its normalisation

-- The three sync triggers, WITH the two guards a naive version omits: skip rows where state <> 0,
-- skip rows where text IS NULL, and make the 'delete' command row carry the OLD values EXACTLY as
-- indexed -- an external-content FTS5 table stores no text of its own, so a 'delete' whose text
-- differs from what was indexed corrupts the index silently.
CREATE TRIGGER block_fts_ai AFTER INSERT ON block
WHEN new.state = 0 AND new.text IS NOT NULL BEGIN
  INSERT INTO block_fts(rowid, text) VALUES (new.block_id, new.text);
END;
CREATE TRIGGER block_fts_ad AFTER DELETE ON block
WHEN old.state = 0 AND old.text IS NOT NULL BEGIN
  INSERT INTO block_fts(block_fts, rowid, text) VALUES ('delete', old.block_id, old.text);
END;
CREATE TRIGGER block_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, text)
    SELECT 'delete', old.block_id, old.text
     WHERE old.state = 0 AND old.text IS NOT NULL;
  INSERT INTO block_fts(rowid, text)
    SELECT new.block_id, new.text
     WHERE new.state = 0 AND new.text IS NOT NULL;
END;
```

**`block_fts`'s option set is a retrieval decision, not schema taste.** `detail='full'` and
`columnsize=1` are fixed by [storage and retrieval](07-store-and-retrieval.md) §3.3 — `detail`
supplies the instance offsets `ChannelResult.spans` carries, `columnsize` the per-row length
`bm25()` normalises by, and `prefix` is deliberately absent — and this document carries that
statement verbatim, byte for byte, because `0001_init.sql` is one file with one golden DDL and a
byte-diff gate over it must have exactly one right answer. Changing an option is a `SCHEMA` major
bump and the change is made in 07 §3.3; it is never made here.

Two consequences of those triggers worth stating. Tombstoning is an `UPDATE state 0 -> 1`, so
`block_fts_au` removes the row from the index and does not re-add it — there is no separate
tombstone trigger. And `block_fts` indexes **every** generation, including staged ones, so a lexical
search joins `ow_block_head`; the `head_fts` table over `block.label` and the BM25 weights are
[storage and retrieval](07-store-and-retrieval.md)'s.

`doc`, `page`, `producer`, `table_meta`, `cell`, `grid_slot`, `asset`, `block_asset`, `page_render`
and `diag` are in §2.8, §10.1, §11 and §9. All of it ships in `0001_init.sql`, **not** as
`ALTER TABLE`: verified on SQLite 3.45.1, `ALTER TABLE t ADD COLUMN x TEXT NOT NULL` succeeds only
against an empty table, so D3's three ownership columns and D4's `decision_id` are in the initial
DDL.

An identity containing an `IFNULL` sentinel is **always a separate `UNIQUE INDEX`**, never an inline
constraint, because SQLite prohibits an expression inside a table-level UNIQUE or PRIMARY KEY
(verified on 3.45.1). The same restriction is why two CHECKs above carry interpolated literals.

**The read contract.** At a `SCHEMA` major, these are `[SOR]` — a public read contract: `meta`,
`enum_val`, `doc`, `page`, `producer`, `block`, `block_history`, `rel`, `mark`, `table_meta`, `cell`,
`part`, `asset`, `block_asset`, `diag`. These are `[DER]` and explicitly outside it, rebuildable by
`ow store rebuild <object>`: `grid_slot`, `block_fts`, `page_render`, `ow_block_head`, plus L3's
`block_sec` and L4's indexes.

### 13.2 On the wire — the `.owdoc` archive

**A plain ZIP.** `unzip -l` and `jq` both work with no external tool.

```
report.owdoc
├── manifest.json          {container_version, model_version, min_reader, digest_recipe,
│                           doc_key, source, status, producers[], parts[], assets[], views[],
│                           declared, achieved, confidence, timings_ms, counts, x}
│                          Pretty-printed. The ONLY mandatory member.
├── frames.json            [{lo_page, lo_ord, hi_page, hi_ord, path, blocks, bytes, sha256}]
├── blocks/000000.ndjson       one FRAME: a block-count-bounded run in (page, ord) order,
├── blocks/000001.ndjson       target 8,192 blocks.
├── marks/000000.ndjson    rels.ndjson    grids.ndjson    diags.json    toc.json
├── parts/word/document.xml    original byte streams, hash-pinned; OPTIONAL (present:false)
├── assets/cas/ab/cd/<sha>.png content-addressed; OPTIONAL, separately deletable/storable
└── views/md-1-7c3f.md         + its sha256 and byte length in manifest.views
```

Members are `ZIP_DEFLATED`. There is no `.zst` suffix and no zstd on the read path:
`compression.zstd` is Python 3.14+, which would put zstd across the whole floor, for a 10-15%
archive-size win, and `unzip -p x.owdoc blocks/000063.ndjson | jq` needs no external decompressor.

**An archive holds exactly one generation**, named in `manifest.json`; `.owdoc` is a single-document,
single-generation projection. Exporting two generations of one document is two archives, which is
what makes the deep-golden `rebind()` diff described below a diff of two files rather than a
query inside one.

**Rules.**

- **The archive never contains a `block_id`.** Every internal reference — parent, `rel` endpoints,
  grid origins, mark owners, asset links — is an `addr`. Import assigns fresh `block_id`s. That is
  what makes an archive portable between stores and what makes the export-diff gate sound.
- **Wire keys are short and frozen** in `tools/wirekeys.toml`, which CI diffs (§3.1). A key is never
  reused with a different meaning: protobuf's field-number discipline with no toolchain.
- **`load()` is tolerant.** A missing or unparseable member yields `status = partial` plus a `Diag`;
  only `manifest.json` is fatal to omit. A `container_version` or `model_version` MAJOR above the
  reader's is **refused**, naming the version and the upgrade command — silent misreading is the
  failure an operator cannot detect. There is no `--force`.
- **CI gate G6:** `import(export(store)) == store` over the fixture corpus, compared after a
  `block_id` remap. That is what stops the canonical store and the interchange archive from drifting
  apart, and it is why `cite` had to become a wire key (§3.1).
- **`.owdoc.d/`** is the exploded, uncompressed form, committed for at most 24 documents of at most
  40 pages as the **deep golden** set, so `rebind()` has two real generations to diff and git can
  delta-compress them.

### 13.3 The Frame

A **Frame** is a **block-count-bounded** run of Blocks in `(page, ord)` order, target 8,192 blocks,
indexed in `frames.json`. It is the unit of streaming and of archive seek.

A Frame is **deliberately not a page range**. One page with 400,000 blocks (a spreadsheet sheet
rendered as one page) makes page-ranged frames non-uniform and forces a "frames may split within a
page" exception that another language's reader will get wrong. Block-count bounding has no such case.

`frames.json` carries `(lo_page, lo_ord, hi_page, hi_ord)` per frame, so "give me pages 300-320" is a
binary search over the frame index followed by inflating two or three members — the ZIP central
directory gives their offsets. Nothing else is read. A frame's `sha256` is over its **uncompressed**
NDJSON bytes, so a reader can verify a member it inflated without re-deflating it.

The driver protocol's unit is also called a frame; it lives in `omniweave_core.host.wire` and the
file is `wire.py`, **not** `frames.py` (charter §5 X20).

### 13.4 Size and time

The envelope: 5,000 A4 pages at 60-120 blocks per page — that wide **because cells are Blocks** — is
300k-600k blocks. The **measured** store figure is ~338 B/block; one pessimistic synthetic corpus
measured 912 B/block including FTS (both charter D2). `store.bytes_per_block = 660` is the nightly
**ratchet** budget at ±10%: it is set at roughly 2× the measured figure, which is the headroom FTS5
plus nine indexes actually consume, and below the pessimistic corpus, so it is neither a rubber stamp
nor a number the first real 10-K breaks. Archive NDJSON measures ~75 B/block deflated (against
msgpack's ~72 — a 4% win for which you surrender `jq` and add a C extension to core).

Every cell below is that arithmetic and nothing else; the two measured inputs are 338 B/block and
75 B/block, and the one budget is 45 ms per 8,192-block frame.

| blocks | store, at 338 B (measured) | store, at the 660 B budget | `.owdoc` (blocks only) | frames | full decode | point read |
|---|---|---|---|---|---|---|
| 10k | 3.4 MB | 6.6 MB | 0.75 MB | 2 | 55 ms | 20 µs |
| 1M | 338 MB | 660 MB | 75 MB | 123 | 5.5 s | 20 µs |
| 10M | 3.4 GB | 6.6 GB | 750 MB | 1,221 | 55 s | ~25 µs (est.) |

Parse-time budget, single-threaded, materialising frozen `Block` instances:
**`archive.frame_decode_ms <= 45`** per 8,192-block frame, i.e. 182,044 blocks/s, which is where the
full-decode column comes from (10,000 / 182,044 = 55 ms; 10,000,000 / 182,044 = 55 s). Frame counts
are `ceil(blocks / 8192)`. Point read is a SQLite index seek; **20 µs is measured** and the
comparison that matters is Parquet's 42.8 ms for the same point read (charter D2's rejected
alternatives) — a factor of ~2,000, which is why Parquet ships as `ow store export parquet` and is
not the at-rest format. The 25 µs at 10M blocks is an **estimate**: one more B-tree level at
`page_size = 8192`. These are budgets owned by [performance](12-performance.md); this document owns
the shapes they are measured over.

### 13.5 A 5,000-page document that must not be resident

**Write path.** The driver emits `owdoc-fragment/1` NDJSON (inline under `INLINE_MAX = 262_144`,
else a blob reference). The host reads it **line by line**, buffers one page's `BlockDraft`s, and
`end_page()` commits one transaction. Peak resident state is one page of drafts plus the tmp-id map
for the current page: at 120 blocks/page and ~1.1 KB per materialised draft that is ~132 KB. The
1.1 KB is an **estimate** with its arithmetic — a `slots=True` dataclass instance with 20 fields is
56 + 8×20 = 216 B of object, plus a ~250-character `text` at ~300 B, plus `addr`/`cite`/two digests
at ~150 B, plus an average two `Mark` instances at ~120 B each, rounded up for the tmp-id entry.
The 5,000-page document never exists in memory, and a crash at page 3,000 leaves 3,000 committed,
invisible pages and a claimable work row (§1.1).

**Read path.** `Doc` is a **lazy handle**, not a loaded object. There is deliberately no
`Doc.pages: list[Page]` and no `Doc.blocks: list[Block]`; every traversal returns an iterator:

```python
class Doc:
    rec: "DocRecord"; declared: Capabilities; achieved: Capabilities
    def block(self, id: BlockId) -> Block: ...
    def by_addr(self, a: Addr) -> Block | None: ...
    def by_cite(self, c: Cite) -> Block | None: ...
    def blocks(self, *, pages: range | None = None, kinds: Iterable[Kind] | None = None,
               layers: Iterable[Layer] = (Layer.BODY,), under: BlockId | None = None,
               trust_below: Trust | None = None) -> Iterator[Block]: ...
    def payload(self, id: BlockId) -> Mapping[str, Any]: ...
    def frames(self) -> Iterator["Frame"]: ...
    def rels(self, id: BlockId, kind: RelKind | None = None, *,
             inbound: bool = False) -> Iterator["Rel"]: ...
    def grid(self, id: BlockId) -> Grid: ...
    def page_render(self, page: int, dpi: int) -> "AssetRef": ...   # LAZY; renders on miss
    def asset(self, ref: "AssetRef") -> BinaryIO: ...               # a STREAM, never bytes
    def serialize(self, fmt: str, **kw) -> tuple[str, SpanMap]: ...
    def verify_quote(self, id: BlockId) -> "QuoteVerdict": ...
```

`blocks(pages=range(300, 321))` is a cursor over `block_read` under one `Snapshot`; the iterator
yields as SQLite pages in, and the reader holds one `Block` plus one 512-block mark window (§2.7) at
a time. Peak RSS for a full-document scan is the configured SQLite page cache (64 MB) plus that
window. `under=` uses `block_parent`, which is a recursive descent, not a scan. *(Build note, D847: `Doc` is not in the tree yet. Its export half is: `omniweave_core.store.export_source.StoreExportSource` reads one document's committed generation out of a `.owstore` as the `ExportSource` that `archive.export()` takes. It reads `[SOR]` tables only, and a missing `doc_ord` is `NotFoundError`. It was G28's test-local stand-in, moved unchanged in what it reads. Two of its reads had no test until it shipped: a block's `decision_id` as `dc`, and a tombstone as `st`. `DocSink` stamps `decision_id` from its construction, and `BlockDraft` carries none, which is why an import cannot restore it.)* *(Build note, D864: `omniweave_core.store.docread.StoreDocReader` is `DocReadSide` over one store connection, so `Doc` reads a real document; until now only tests' fakes stood behind it. Every Block comes through `portable.BlockDecoder`, the store's one decode, which `read_block()` now uses too. Every read is of live rows at the handle's generation. `blocks()` is a cursor in windows of 512 rows with one marks statement per window, in the export's `page, ord, addr` order. It opens `BEGIN DEFERRED` when no transaction is open, so every window reads one snapshot. `under=` is the subtree rooted at that block, root included, as 03:2814's "a subtree under one `BlockId`" reads. Filters bind the store's own `enum_val` codes. The record answers for the head generation only, because the `doc` table holds one row per document. `frames()`, `page_render()`, `asset()`, `verify_quote()` and `serialize()` (through `resolve_scope`) are refused by name: this build has no store for any of them.)*

**Archive path.** Reading pages 300-320 out of a 5,000-page `.owdoc` inflates two or three
`blocks/NNNNNN.ndjson` members located through `frames.json` and the ZIP central directory. At the
45 ms/frame budget that is ~135 ms, and the transient decode buffer is 3 × 8,192 × ~1.1 KB ≈ 27 MB,
against a 750 MB archive.

**What is never resident.** Page renders (10.7 MB each decoded — 53.5 GB for 5,000 pages), asset
bytes (streamed), retained parts (streamed from CAS on verification), the FTS index (queried, never
loaded), and a `SpanMap` for a document nobody serialized.

**The one thing that is resident, stated plainly.** `serialize()` returns a `str`, so serializing a
whole 5,000-page document materialises the whole view: ~600k blocks × ~250 chars is ~150 MB of
Python string plus a `SpanMap` of 600k intervals at 24 B ≈ 14 MB. `MAX_VIEW_BYTES = 67_108_864`
(64 MiB) caps it with `RESOURCE_LIMIT{MAX_VIEW_BYTES}` naming the knob, checked incrementally as the
serializer appends rather than after the memory is spent. Whole-document rendering is therefore a
page-ranged loop by construction, and the Answer path never approaches it —
`HARD_CEILING = 24_000` chars is three orders of magnitude below the cap.

## 14. Limits, hostile input, and failure at scale

Limits are **ceilings, not settings**: `effective = min(tenant_cap, declared, HOST_MAX)`. Widening
past a `MAX_*` is a fork, not a flag. A breach is `RESOURCE_LIMIT{limit}` naming **which knob would
need raising**, enforced at the read boundary with `take(N+1)`-then-check, so a limit is never
discovered after the memory is spent (charter §6.10). These are L2's, in
`omniweave_core.limits`; five are set by the charter and six are set here.

| limit | value | source | what it stops, and the arithmetic |
|---|---|---|---|
| `MAX_ASSET_BYTES` | 268,435,456 | charter §6.10 | one asset; 256 MiB, streamed with a content-length pre-check |
| `MAX_GRID_SLOTS` | 4,000,000 | charter §6.10 | one table's materialised cover map |
| `MAX_SEGMENT_BLOCKS` | 512 | charter §6.10 | L3's, and the reason `MARK_HYDRATE_WINDOW` is 512 |
| `INLINE_MAX` | 262,144 | charter §6.10 | a driver-protocol body; above it, a blob reference |
| `MIN_SQLITE` | (3, 42, 0) | charter §6.10 | the one floor |
| `MAX_EXPANSION` | 4,000,000 | **set here** | a table's charged span area, **equal to `MAX_GRID_SLOTS`** and asserted equal, so a table cannot build and then fail to store |
| `MAX_BLOCKS_PER_DOC` | 8,388,608 | **set here** | one document. `2**23`, chosen as twice the charter's celebrated 4M-cell sheet. At the 660 B budget that is 5.5 GB of store for one document, which is the largest single document omniweave admits |
| `MAX_BLOCKS_PER_PAGE` | 4,194,304 | **set here** | one page, and therefore **one transaction**. `2**22`, chosen so the charter's 4M-cell sheet is admissible with 4.9% headroom. The cost is stated rather than hidden: at 660 B/block that page is a ~2.8 GB WAL and, at 182k blocks/s, a ~23 s commit. This is charter deferred item **F29** — the sub-page commit boundary — and the charter's own resolution is exactly this refusal rather than a speculative sub-page unit, and §14.1's hostile-input row says **admitted**, not refused, for the same fixture — F29 is the spike, not a refusal that already ships |
| `MAX_BLOCK_TEXT_BYTES` | 1,048,576 | **set here** | one block's `text`. 1 MiB, four times `INLINE_MAX`, so any block arriving inline is already inside it. A longer run is **split** into sibling blocks joined by `rel(continues)` with `Diag(OW_TEXT_SPLIT, info)`, never truncated |
| `MAX_MARKS_PER_BLOCK` | 4,096 | **set here** | the mark array; the same 4,096 as `MAX_LINKS_PER_BLOCK`, and the `maxItems` in §3.2 |
| `MAX_BLOCK_DEPTH` | 64 | **set here** | the containment spine, matching `os_path`'s 64-element ceiling and bounding `addr` under its 512-char CHECK |
| `MAX_PAYLOAD_BYTES` | 16,384 | **set here** | `canonical(payload)`; a payload is kind-specific facts, not a document |
| `MAX_X_BYTES` | 16,384 | **set here** | `canonical(x)` per block; a third party's annotation, not a second document |
| `MAX_RESIDENT_CELLS` | 65,536 | **set here** | out-of-order cells in `build_grid` (§10.2) |
| `MAX_VIEW_BYTES` | 67,108,864 | **set here** | one `serialize()` result (§13.5) |

### 14.1 Hostile input, mechanism by mechanism

Every row is an attack the mined collection or the model's own shape makes reachable, and the
mechanism that stops it. "Refuse" means `RESOURCE_LIMIT` plus `status='partial'` plus a coverage gap
in the corpus card — never a silent truncation, and never an exception that loses the page.

| attack | mechanism |
|---|---|
| `rowspan="99999"` in a three-row HTML table | `MAX_EXPANSION` charged **before** expanding, incrementally (§10.2); anydoc's own pre-check, same reason |
| 50,000 nested `<div>`s | `MAX_BLOCK_DEPTH = 64`; the 65th level is flattened into its ancestor with `Diag(OW_DEPTH_FLATTENED, warning)`, because refusing the document over a stylistic nesting is worse than losing the nesting |
| one 400 MB minified JS file as a `code` block | `MAX_BLOCK_TEXT_BYTES`, split into `continues`-joined siblings |
| a 4M-cell sheet on one page | **admitted**, with 4.9% headroom under `MAX_BLOCKS_PER_PAGE` and *exactly at* `MAX_GRID_SLOTS`, which does not fire because 4,000,000 is not greater than 4,000,000. The cost is stated rather than hidden: a ~2.8 GB WAL and a ~23 s commit against `loop_lag_max_ms = 250`, a 92× breach and `17` R-T13's own detection trigger. Charter **F29** is the spike that decides whether a sub-page commit boundary is needed, and a fix must move **both** constants — the ceiling and the grid-slot cap — because a page admitted by one and unbounded by the other is the shape of the failure |
| a zip bomb in an OOXML container | `MAX_ENTRY_BYTES` / `MAX_ENTRY_COUNT` at the acquire boundary ([ingest](05-ingest-and-routing.md)); L2 sees only what survived, and `part.byte_len` records it |
| an asset whose declared sha256 points at another document's CAS object | `add_asset` hashes the stream itself; a mismatch is `OW_ASSET_DIGEST_MISMATCH` and the asset is rejected (§11) |
| white-on-white instructions to a model | `layer = hidden`, never in a default projection, always indexed, `Taint.HIDDEN_TEXT` ORed upward (§5) |
| a chat-template sentinel inside a block's text | defanged **on a copy** at the serve boundary, so `quote` stays honest; the block is emitted as `normalized`, marked and counted ([security](14-security.md)) |
| a `mark` array of 10^6 zero-width anchors | `MAX_MARKS_PER_BLOCK` |
| an `x` map carrying a megabyte per block | `MAX_X_BYTES`, and `x` is not a digest input, so it cannot be used to force cache churn either |
| a driver emitting a `parent` tmp id it never defines | P1: the whole document fails with `OW_FRAGMENT_DANGLING_TMP`. A partial spine is worse than no document |
| a driver emitting the same tmp id twice | rejected at decode; a tmp-id map with a duplicate key is a protocol error, not a last-writer-wins |
| a payload with a 10-deep nested object | the per-kind schema in §4.4, validated at `add_block` |
| a `NaN` in a score | `allow_nan=False` in `canonical()`; the write raises, and there is no `str()` fallback (I12) |

### 14.2 Concurrency and partial failure

INV-17 gives one writer per store, one thread per connection, one transaction per unit, so L2 has no
lock protocol of its own to specify. What it does have to specify is what a **second** parse of the
same document sees, and what a crash leaves behind.

| situation | outcome |
|---|---|
| two runs parse the same `doc_key` concurrently | impossible by construction: the `work` row is keyed `(unit_uri, unit_part, operator, op_version)` and a claim is exclusive ([the runtime](08-runtime.md)). Two claims of one page cannot both exist |
| a crash between `end_page()` calls | the committed pages are durable at `g_t` and invisible; the abandoned generation is swept at startup; the work row is reclaimable |
| a crash inside `end_doc()` | the whole final transaction rolls back, including the `doc.gen` bump, so the generation stays staged and the previous head keeps answering |
| a reader open across a `doc.gen` bump | a `Snapshot` is one `BEGIN DEFERRED` read transaction, so the reader sees one generation for its whole call and never mixes two |
| a `rebind()` below threshold | the generation is quarantined: durable, invisible, inspectable by `ow doc diff`, and cleared only by `--allow-unexplained-rebind` or a re-parse |
| two generations of one document alive at once | normal and bounded: the head plus at most one staged. A third would mean a sweep did not run, and `ow store verify` reports it |
| `ON DELETE CASCADE` on a sweep of a 600k-block generation | one statement, one transaction, and it is the reason `page` is the cascade root: deleting 5,000 `page` rows cascades `block`, which cascades `mark`, `cell`, `grid_slot` and `block_asset`. The `asset` rows survive, because they are keyed on `doc_ord` (§11) |

## 15. Schema evolution

### 15.1 The version fields, and which one moves

| field | where | type | governs |
|---|---|---|---|
| `SCHEMA` | `omniweave_core.contract` and `index_state` | two small ints | the L2 model **and** the store schema together. A major is a published read-contract break over the `[SOR]` set of §13.1. The code home holds the pair `SCHEMA`/`SCHEMA_MINOR`; the sole disk home is `index_state.schema`, written `<major>.<minor>`, and `meta` never gains a `schema` key (ADR-9). |
| `model_version` | `meta`, `doc.model_version`, `manifest.json` | `"MAJOR.MINOR"` | the type layer: fields, kinds, payload schemas, wire keys |
| `container_version` | `meta`, `manifest.json` | `"MAJOR.MINOR"` | the `.owdoc` envelope: member layout, compression, `frames.json` shape |
| `min_reader` | `meta`, `manifest.json` | `"MAJOR.MINOR"` | the lowest `model_version` that can read this artefact **correctly** |
| `digest_recipe` | `meta`, `manifest.json` | small int | the digest definitions |
| `writer_version` | `meta` | `RELEASE` string | forensics only; never a compatibility input |

At release 1: `SCHEMA = 1`, `SCHEMA_MINOR = 0`, `model_version = "1.1"` (the twenty-nine wire keys of §3.1),
`container_version = "1.0"`, `min_reader = "1.0"`, `digest_recipe = 1`.

### 15.2 Compatibility rules

**Backward compatibility (a new reader, an old artefact).** Always supported within a
`model_version` MAJOR. A field absent from an old record takes its documented default, and where the
default is semantically loaded the absence is **counted**, not silently defaulted: an absent `trust`
is `AMBIGUOUS` and appears in `ow doc verify`.

**Forward compatibility (an old reader, a new artefact), and it fails closed by design.**

| the new artefact has | old reader does |
|---|---|
| `model_version` MAJOR above its own | **refuses**, naming the version and the upgrade command |
| `min_reader` above its own | **refuses**, same message |
| a new *optional* field with a new wire key, `min_reader` unchanged | ignores it, and preserves it verbatim under `x.ow.unknown` so `export(import(a)) == a` still holds |
| an unknown `Kind` member | **refuses** the row with `OW_SCHEMA_UNKNOWN_KIND` — which is why adding a kind raises `min_reader` |
| an unknown top-level archive member | ignores it with a `Diag`, `status = partial` |
| an unknown `mark.kind` | keeps the mark, renders it as no formatting, `Diag(OW_MARK_KIND_UNKNOWN, info)` |
| an unknown `payload` key | keeps it; it is already in `canonical(payload)` and therefore in the digest |

**Extends the charter:** `x.ow.unknown` is the reserved slot that makes the third row true. The `ow`
vendor segment is the framework's, so no third party can collide with it, and `x` is not a digest
input, so round-tripping an unknown key through it cannot change a `content_digest` — which is
precisely the property that makes `export(import(a)) == a` hold rather than merely almost hold.

**What moves which version.**

| change | `model_version` | `min_reader` | `SCHEMA` | `digest_recipe` |
|---|---|---|---|---|
| add an optional field + wire key | MINOR | — | MINOR | — |
| add a `Kind`, `Method`, `RelKind`, `Layer` or `OsKind` member (append only) | MINOR | raised to it | MINOR | — |
| add a `mark.kind` | MINOR | — | — | — |
| add or promote a `payload` key | MINOR | — | — | **bump** (`payload` is a digest input) |
| change a digest input or the `canonical()` encoding | — | — | — | **bump** |
| remove or retype a field | MAJOR | raised | MAJOR | usually |
| reorder an enum's members | **forbidden** (§2.1) | — | — | — |
| change `.owdoc` member layout or compression | — | — | — | — (that is `container_version`) |
| add or rebuild a `[DER]` object | — | — | MINOR | — |

### 15.3 The migration mechanism

Two kinds of migration, and conflating them is the mistake this section prevents.

**Schema migrations** are numbered SQL files applied forward-only in file order:
`0001_init.sql` (L2), `0002_graph.sql` (L3), `0003_index.sql` (L4), then `0004_*` onward. Each runs
in one transaction, updates its `meta` rows, and regenerates `enum_val` from the Python enums with
CI asserting parity in both directions and the append-only assertion of §2.1. Generated
`BEFORE INSERT` triggers — the `MAX_TRUST_BY_METHOD` clamp mirror, the escalation monotonicity check
— are emitted from the same source at migration time, so there is one truth and two enforcers.
**A migration may only downgrade `trust` and may never clear `taint`.** Every migration declares its
cost class (`ddl`/`backfill`/`rebuild`), whether it is resumable, and — as required prose that
`ow doctor` prints verbatim — what an un-backfilled row means.

**Data migrations are passes, not re-parses**, and this is the property the digest design bought:

| bump | serviced by | why not a re-parse |
|---|---|---|
| `digest_recipe` | `op.redigest` — recompute `content_digest`/`layout_digest` bottom-up | every digest input is a **stored field** |
| `segment_recipe` | `op.resegment` — re-run `derive.segment.spine` over stored blocks | segmentation reads blocks, not sources |
| a new derived column | one `UPDATE ... FROM` in the migration | |
| a new `[DER]` object | `ow store rebuild <object>` | it is rebuildable by definition |

`op.redigest` walks the spine bottom-up in one pass — `ORDER BY page DESC, ord DESC` is not a valid
post-order, so it uses a recursive CTE over `block_parent` from the leaves — and it must run over
**every** generation present, not only the head, because a staged or quarantined generation whose
digests are at the old recipe would rebind against the head incorrectly. A `digest_recipe` bump
invalidates every content-addressed cache in the fleet and is budgeted at **at most annually**.

**A re-parse is never a migration.** It is a new `gen` produced by the ingest path and reconciled by
`rebind()`, and it costs money.

### 15.4 Deprecating a field

Three phases over two `RELEASE` minors, and no phase is skippable:

1. **Announce (release N).** The field is marked `deprecated` in `schema.json` with a `replaced_by`
   and a removal release. Writers still write it. Readers still read it. Every write of it emits
   `Degradation(kind="deprecation")`, which appears in the run manifest and in the serve envelope, so
   the operator learns by running rather than by reading a changelog.
2. **Stop writing (release N+1).** Writers stop. Readers still read it for old artefacts. A
   `ow store verify` counts remaining occurrences so a corpus owner can see when they hit zero.
3. **Remove (the next `model_version` MAJOR).** The column is dropped by a migration; the wire key is
   moved to `tools/wirekeys.toml`'s `retired` table and **is never reused**, exactly as an error code
   in `codes.toml` is never renumbered or reused.

An enum **member** follows the same three phases; the wire value and its `enum_val.ord` are retired
together, and a stored row carrying it reads as `unknown` + `raw_kind` after removal rather than
failing, because the member was known at write time and the retirement table records it. That is the
one deliberate exception to §2.1's fail-closed rule for unknown kinds: a *retired* value is known to
have been valid, and an *unrecognised* one is not.

## 16. Projections

**A projection is a function over the model, never a parallel representation.** This is INV-1 stated
constructively, and it is the reason `Block` has no `html` field, no `markdown` field, and no `md`
field — a build-failing semgrep rule asserts it across every model class in the framework.

### 16.1 The one serializer, and its algorithm

```python
def serialize(scope: "ViewScope", fmt: Literal["md","gfm","html","text","otsl"], *,
              layers: frozenset[Layer] = frozenset({Layer.BODY}),
              contextualize: bool = False) -> tuple[str, SpanMap]: ...
```

`ViewScope` is the block selection a projection runs over: a document, a page range, a subtree under
one `BlockId`, a Segment, or an explicit `tuple[BlockId, ...]` from a retrieval result. It resolves to
an ordered, duplicate-free block sequence and carries the corpus and the generation it was resolved
at. This section is its sole home. It is **not** charter D6's runtime `Scope` — roots, globs and a
corpus, the first argument of `run(scope, ctx)` — which keeps the bare name because it is older and
more widely referenced; ADR-1 decision 7 renamed this one and §18 Q1 records the closure. *(Build note, D866: a stored document's scope is resolved by `store.docread.StoreDocReader.resolve_scope()`, so `Doc.serialize()` works over a `.owstore`. One snapshot reads the scope's live blocks in every layer, since `layers` is `serialize()`'s argument. They come in pre-order over the generation's whole `block_parent` spine, children by `(ord, block_id)`, the serializer's own order, so a page range that cuts a table keeps its in-range cells in place. `payload`, `table_meta`, `cell` and `rel(continues)` are one statement each. `heading_paths` are `segment.heading_path`'s computation over `block_sec`, and a section block's own heading is not on its path, since step 5 prefixes the headings above a unit. `kind` is `document`, `pages` or `subtree`, and `corpus_id` is the store's `meta` row. Segment and explicit scopes have no store reader yet.)*

The traversal, which the charter leaves unspecified and which four other documents need to be able
to predict:

```
1. RESOLVE.   scope -> an ordered, duplicate-free (block_id, depth) stream, pre-order over the
              spine restricted to `state = 0` and `layer in layers`. Because layer is inherited
              (M-INV-5) this is a per-block predicate on an indexed column, not an ancestor walk.
2. UNWRAP.    a `table` whose table_meta.kind = 'layout' and fmt != 'otsl' is replaced by its
              cells in row-major origin order, rendered as ordinary body blocks. The model never
              unwraps; only this step does.
3. EMIT, per block, in this order and no other:
              a. the format's OPEN token for (kind, payload)  -- '## ' for heading level 2,
                 '```python\n' for code, '> ' per line for blockquote, '<td>' for a cell
              b. the block's OWN `text`, run-split by its marks (see below)
              c. each child, recursively, in `ord` order
              d. the format's CLOSE token
              e. the format's BLOCK SEPARATOR, unless the next block is joined (step 4)
4. JOIN.      when block B has an outbound rel(continues) to the next block in the stream, no
              separator is emitted and no OPEN/CLOSE token is repeated: the two render as one
              paragraph. The SpanMap records two adjacent intervals, so a RenderSpan across the
              seam lifts to two blocks -- which is correct, because it is two blocks.
5. CONTEXT.   contextualize=True prefixes each top-level unit of the scope with its heading_path,
              recorded in the SpanMap as SYNTHETIC.
```

**Step 3 is where M-INV-4 earns its place.** A block renders its own `text` and *then* its children,
so a `list_item` whose `text` is duplicated into a child `paragraph` renders the sentence twice.
There is no de-duplication pass and there will not be one; the model forbids the duplication instead.

**Run-splitting, for marks.** Collect every mark endpoint for the block into a sorted boundary list
`0 = b0 < b1 < ... < bn = len(text)`. Between consecutive boundaries the active mark set is constant.
Walk the boundaries once; at each one, close the format tokens for marks that ended (in reverse open
order) and open those that began (in `(a, b, kind)` order). An arbitrarily overlapping mark set
therefore produces a well-nested render by splitting runs — `**bold *both* **` becomes
`**bold **_*both*_` in `md` — and **no mark is ever dropped**. Cost is `O(m log m)` per block for
`m <= MAX_MARKS_PER_BLOCK` marks.

**The `SpanMap`, concretely.** Two parallel arrays plus a dict: `starts: list[int]` (the view offset
at which each interval begins, strictly increasing), `owners: list[BlockId | None]` (`None` marks a
synthetic interval), and `first_last: dict[BlockId, tuple[int, int]]`. `block_at(offset)` is
`bisect_right(starts, offset) - 1` plus one array read; `is_synthetic(offset)` is the same probe
against `owners`; `offsets_of` is one dict read; `to_text` clips a `RenderSpan` to the intervals it
overlaps. Size is 24 B per interval, so a 600k-block view's map is ~14 MB (§13.5).

**Every serializer returns its `SpanMap`.** There is no text-only serializer: if you have the text
you have the map. A format whose entry in `SERIALIZER_CAPS` is `False` **may never be cited from**,
and at release 1 there is no such format. `OW_SPANMAP_UNAVAILABLE` (`OW-A-012`) names the
**serializer** it read that table for — not a driver, because a parse driver never calls
`serialize()` and could not have written or tested such a claim.

The five formats and what each is for:

| `fmt` | for | block separator | table handling | lossy in |
|---|---|---|---|---|
| `md` | a model context, human reading | `\n\n` | pipe table, spans flattened | spans, layout tables unwrapped |
| `gfm` | pasting into a PR, an issue, a doc | `\n\n` | GFM strictly: synthetic delimiter row when `header_rows == 0`, `<br>` inside cells | as `md` |
| `html` | a browser preview, an OUT carrier input | none (block elements) | `rowspan`/`colspan` preserved | polygons, origin spans |
| `text` | BM25 fixtures, diffing, plain export | `\n\n` | rows joined by tab, cells by newline | all structure |
| `otsl` | a table-heavy model context | `\n` | **lossless**: spans and headers preserved | nothing about the table |

`otsl` over a scope containing non-table blocks emits those blocks as `text` lines and each `table`
as an OTSL cell-token sequence, so a mixed scope is representable rather than refused. That is the
one thing a table-only serialization has to answer and the charter does not.

### 16.2 `view_id` and hash-pinned views

A serialized view is identified by `view_id = "<fmt>/<serializer_version>/<options_digest[:4]>"` —
for example `md/1/7c3f`, where `options_digest` is `sha256_canonical` over `(layers sorted,
contextualize, scope kind and its resolved block ids' digest, gen)`. A `RenderSpan` carries it, and
lifting a `RenderSpan` through a `SpanMap` whose `view_id` differs is a **type error**, not a silent
mis-lift. When a view is materialised (into the `render` cache layer, or into an archive's `views/`
directory) its sha256 and byte length go into `manifest.views[]`, so a span into it is pinned to
bytes that can be checked.

### 16.3 Segments are a projection too

A **Segment** is a view over a contiguous run of Blocks: the `segment` row plus the exactly-once
`segment_block` membership, whose `PRIMARY KEY (block_id)` makes zero overlap **unrepresentable**
rather than merely intended. A segment stores no text.

L2's obligation is exactly two things, and everything else about segmentation belongs to
[structure extraction](06-structure-extraction.md): a Segment is addressable purely as a set of
`block_id`s, and rendering one is `serialize(ViewScope.segment(id), fmt)` — the same function, not a
second renderer. The segmenter's constants, the table-synopsis rule, `heading_path`, and
`segment.content_digest`/`trust`/`quote_min` are all L3's; the reason `MIN` works for the latter two
is L2's, and it is §2.1's ordering.

### 16.4 A caller's JSON Schema (lift-style extraction) is a projection

**Extends the charter** in shape, not in decision: D4 fixes the `fields` lane and `FieldGrounding`;
the projection signature is stated here so downstream documents have one to call.

```python
@dataclass(frozen=True, slots=True)
class FieldGrounding:
    path: str                    # RFC 6901 JSON pointer into the produced object
    value: Any
    grounded: bool
    part: str | None             # the `part` the value was located in, when grounded
    text_span: TextSpan | None
    block: BlockId | None

def project_schema(scope: "ViewScope", schema: Mapping[str, Any]
                   ) -> tuple[Any, tuple[FieldGrounding, ...]]: ...
```

The rules that make it a projection rather than a generator:

- **Every string leaf is grounded back to a `(block, TextSpan)` by
  `ground(block_text, leaf_value)`** — [structure extraction](06-structure-extraction.md) §1.7's
  single grounding algorithm, and the **only** producer of a `ts_a`/`ts_b` anywhere in this plan.
  `FieldGrounding` and `GraphSink.mention` are its two declared callers. Neither reimplements it and
  neither calls `normalize_k` or `str.find` itself: an offset `.find()` returns lives in
  `normalize_k`'s output space, `TextSpan` lives in `block.text`'s space, normalisation changes
  length, and carrying an offset between the two coordinate systems through the back-map is
  `ground()`'s whole job. **The model is never asked for an offset**; that one call is
  simultaneously the citation, the polygon, the hallucination gate and the injection
  containment.
- **`ground()`'s three outcomes map onto `FieldGrounding`'s fields, and none of them guesses.**
  `(ts_a, ts_b, 1)` sets `grounded = True`, `block` to the block the leaf was extracted from and
  `text_span = TextSpan(ts_a, ts_b)`. `(ts_a, ts_b, n)` with `n > 1` grounds the **first**
  occurrence and carries the ambiguity diag §1.7 names, with the count, so the choice is recorded
  rather than silent. `None` — an empty normalised value, a value that is not a substring, or one
  whose post-condition check fails — is `grounded = False` with `text_span = None` and
  `block = None`; a leaf that does not locate is never given a nearest match, because a wrong span
  is unrepairable without re-grounding the corpus.
- `number` and `boolean` leaves are excluded from the grounding fraction, because verbatim matching
  is meaningless for them.
- `verify.grounded_field_frac` below its threshold escalates to a second extraction at a higher
  render profile, or degrades to `ok_partial` with the ungrounded fields flagged for review. That
  overturns lift's own adversarial benchmark result — **90.2% per field against 20.9%
  full-document** (`_notes/mine-parse.md:2584`, the mined comparison table) — which is what a
  90-to-21 collapse looks like when per-field correctness does not compound, so the free `DECODE`
  pass always also runs and cross-checks.
- The permitted schema subset is the closed one of §3.2, and `make_properties_nullable` runs before
  constrained decoding (`lift/lift/model/vllm.py:29-45` — without it the grammar *forces* the model
  to invent values), with explicit `minItems` on every array.

### 16.5 The projection law (M-INV-3)

For every projection `P` and every scope `S`:

1. `P(S)` reads only committed head rows in one `Snapshot`; two calls at one `gen` are
   byte-identical.
2. `P` never writes to `block`, `rel`, `mark`, `cell` or `asset`. It may write the `render` cache
   layer, which is `[DER]`.
3. Every character of `P(S)` either lifts to exactly one `(BlockId, TextSpan)` through the `SpanMap`,
   or is marked synthetic in that map. **There is no third case**, and the conformance property is
   `for every offset i: map.block_at(i) is not None or map.is_synthetic(i)`.
4. `P` is a pure function of `(S, options, snapshot)` — no clock, no RNG, no environment.

## 17. Conformance: what a driver must pass

`omniweave-conform` ships twelve suites. The bar is **the honesty of the descriptor, not the
excellence of the driver**: declaring `spatial = "none"` is not a failure; declaring `line_bbox` and
returning none is. The mandatory tier runs in under five minutes on a laptop, enforced as a CI timing
assertion, because a skipped gate is not a gate. CI runs the kit from a **trusted tag**, never the
PR branch.

These are the model-facing properties. The suite that owns each is named; the full suite inventory is
[the driver system](04-driver-system.md)'s.

| # | property | suite | assertion |
|---|---|---|---|
| P1 | tmp-id closure | `contract` | every `tmp` referenced (parent, rel endpoint, grid cell, asset) is defined in the same fragment, and no `tmp` is defined twice. A dangling or duplicate one **fails the whole document** with `OW_FRAGMENT_DANGLING_TMP` |
| P2 | page scope | `contract` | no fragment names a page outside the `PartSelector` it was given: `OW_FRAGMENT_OUT_OF_SCOPE` |
| P3 | sibling order | `contract` | `ord` is dense from 0 and unique among siblings; `block_sib` never conflicts |
| P4 | parent before child | `contract` | `parent.page <= child.page`, and a parent's `tmp` is defined earlier in the stream than any child's (M-INV-1) |
| P5 | text/kind matrix | `capability` | `text IS NULL` for exactly the kinds §4.1 marks NULL; `text` is NFC; `text` never contains `<`-delimited markup; no child `paragraph` has `normalize_k(text)[0]` equal to its parent's (M-INV-4) |
| P6 | geometry frame | `capability` | every `quad` lies within `[-QUAD_SLACK_MPT, w_mpt+QUAD_SLACK_MPT] × [-QUAD_SLACK_MPT, h_mpt+QUAD_SLACK_MPT]` with `QUAD_SLACK_MPT = 3000` (3 pt, enough for a real bleed or a skewed scan line and far short of a frame error); no quad is all-zero; corner order is top-left-then-clockwise; `Quad.from_driver` is the only constructor reached (asserted by patching it to raise) |
| P7 | `origin_span = "exact"` | `capability` | for each block, re-read the retained part on the branch its `os_kind` selects and assert equality: `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == text` (`bytes`), `nfc(node_text(part, path)) == text` (`nodepath`), re-extraction by the recorded `os_extractor` reproduces `text` under NFC (`glyphs`). **All three branches**, because a `bytes`-only property is inapplicable to the container formats it matters most for. The `bytes` branch is `nfc()`, never `normalize_k` (§7.2): a fixture whose retained part reads `ABC` and whose `text` is `abc` **must fail** |
| P8 | span containment | `capability` | `ts_a`/`ts_b` non-NULL implies `text` non-NULL and `0 <= ts_a <= ts_b <= len(text)` |
| P9 | marks in range | `capability` | every mark satisfies `0 <= a <= b <= len(text)`; a `link` mark has a non-empty `target`; overlapping marks are accepted, not rejected; the count is at most `MAX_MARKS_PER_BLOCK` |
| P10 | grid exactly-once | `capability` | for every `(r, c)` with `c < row_len[r]`, `grid.slot(r,c)` resolves to exactly one `Origin`; no position resolves to two; no origin is unreachable |
| P11 | raggedness declared | `capability` | `n_cols == max(row_len)` and `len(row_len) == n_rows` |
| P12 | clamp is recorded | `capability` | a fixture with overlapping `rowspan` produces a `Grid`, a `Diag(OW_TABLE_SPAN_CLAMPED)` and `trust == INFERRED` — not an exception |
| P13 | cells arrive row-major | `capability` | a table's `CellDraft`s have non-decreasing `r` and, within a row, increasing `c`; a driver that cannot is held under `MAX_RESIDENT_CELLS` and says so (§10.2) |
| P14 | capability honesty, both directions | `capability` | assertions are **derived from the card**: `text_span = false` asserts spans are **absent**; `math = {}` asserts no formula block carries LaTeX; `assets = "none"` asserts zero asset drafts. Over-declaring fails; under-declaring fails |
| P15 | `achieved <= declared` | `capability` | field by field, on every fixture, on the ordered fields with `>=`, on `math` with `⊇`, on the booleans with implication, using §2.9's derivations |
| P16 | `OriginSpan` column discipline | `capability` | every block's `os_*` columns match exactly one row of §7.2's mapping; `os_kind = pixels` implies `quad IS NOT NULL`; `os_b` is never negative and is never used as an end offset *(Build note, D938: the conformance template passed this suite while emitting byte origins the host refused. `store.fragment` read only `none` and `glyphs`, and the template's codec was a bare `"utf-8"`, where 03:1466 makes it `<codec>/<errors>`. The decoder now reads `bytes` into `OriginBytes(part, start, length, codec)` and refuses a malformed one by name. The template sends `utf-8/<its errors policy>`. The kit's P16 gains a third clause: a `bytes` or `glyphs` origin must be one the model's own type accepts. The template, under its own card in a project, is now ingested by a real `ow add`, and its stored spans re-verify from the retained part.)* |
| P17 | layer inheritance | `contract` | every non-page-root block's `layer` equals its parent's (M-INV-5); a fixture whose driver states otherwise gets `OW_LAYER_NOT_INHERITED` |
| P18 | `addr` grammar and anchoring | `contract` | every `addr` matches §3.2's pattern; the root's is `doc`; the page component equals the page anchor (M-INV-2); depth `<= MAX_BLOCK_DEPTH` and length `<= 512` |
| P19 | digest stability | `determinism` | parsing the same bytes twice in one process yields identical `content_digest` for every block, **including** the cross-page containers the closure pass rewrote |
| P20 | cross-process determinism | `determinism` | two processes with differing `PYTHONHASHSEED`, `TZ`, `LC_ALL`, `TMPDIR` and cwd produce equal digests per block and an identical `Diag` multiset (`ReplayClass = byte_exact`) |
| P21 | rebind stability | `idempotence` | parse, re-parse the identical bytes, `rebind()`: `carried == n_blocks`, `created == 0`, `retired == 0`, every `cite` is preserved, and `doc.gen` advanced by exactly 1. A driver that fails this is nondeterministic in a way `content_digest` can see |
| P22 | staged invisibility | `contract` | a parse killed after page *k* leaves `doc.gen` unchanged, `ow_block_head` returning the previous generation, and every pre-existing `cite` resolving; a restart sweeps the abandoned generation |
| P23 | asset dedup, streaming and digest | `capability` | two blocks referencing identical bytes produce one `asset` row and two `block_asset` rows; `add_asset` is called with a stream and the driver never materialises the bytes (asserted by handing it a stream that raises on `.read()` without a size argument); a draft whose declared `sha256` disagrees with the stream is rejected |
| P24 | no forged provenance | `sandbox` | the fragment contains no `block_id`, no `producer_id`, no `origin_operator`, no `origin_driver`, no `restriction_bits`, no currency field and no cache-hit claim. It **does** carry `achieved` on the `doc` record, and that is deliberate: `achieved` is the driver's self-report of what it delivered on *this* document, `<=` the card on every key (the `capability` suite asserts it), clamped again by `DocSink`, and the input `byte_exact` reads (`18` §5). A capability self-report is not provenance; forging provenance means naming a row, a producer or a price, and none of those is representable here |
| P25 | limits at the boundary | `limits` | `MAX_BLOCKS_PER_DOC`, `MAX_BLOCKS_PER_PAGE`, `MAX_GRID_SLOTS`, `MAX_EXPANSION`, `MAX_ASSET_BYTES`, `MAX_BLOCK_TEXT_BYTES`, `MAX_BLOCK_DEPTH`, `MAX_MARKS_PER_BLOCK`, `MAX_PAYLOAD_BYTES`, `MAX_X_BYTES` and `MAX_VIEW_BYTES` each produce `RESOURCE_LIMIT{limit}` naming the knob, and the process RSS never exceeds the ceiling — the limit is enforced before the memory is spent, not after |
| P26 | unknown kind | `contract` | an unrecognised kind string yields `Kind.UNKNOWN` with a non-empty `raw_kind` and a warning `Diag`, never a crash and never a silent `paragraph` |
| P27 | payload validates | `contract` | every `payload` passes its kind's generated schema; an invalid one is `OW_SCHEMA_PAYLOAD_INVALID` at write, not at read |
| P28 | failure is a field | `fuzz` | a corrupt fixture yields `status='partial'` with `Diag` rows, or a typed `DriverError` from the closed `FailureClass`; a crash is allowed (one unit), a hang is not |
| P29 | page indices are original | `limits` | a fixture parsed with a page-batch size of 4 reports pages 0..N-1, not 0..3 repeated |
| P30 | round-trip | `contract` | `import(export(doc)) == doc`: every field, every mark, every rel, every grid slot, every asset link, compared after a `block_id` remap — gate G6 at driver granularity, run over the document the fragment produced rather than over the driver's own output |
| P31 | serializer totality | `contract` | for every fixture and every `fmt`, every offset of the produced view lifts to a block or is marked synthetic (§16.5 rule 3), and no mark is dropped |
| P32 | `origin_span = "normalized"` | `capability` | for every body block on the conformance sample, `os_kind <> 'none'` and `os_part IS NOT NULL`, and `locate(block)` returns a `Locus` with `precision <= "block"` and `reason IS NULL`. A driver declaring `normalized` and emitting no address **fails**. Re-verification is deliberately **not** asserted: a `normalized` address that re-verifies is an under-claim, already caught by P15 |

**P32 exists because the middle rung was the one card field a driver could set for free.** P15
(`achieved <= declared`) passes vacuously for a driver declaring `normalized` and emitting
`os_kind = 'none'` everywhere, because `achieved` then computes `none` and `none <= normalized`
holds; P14's honesty assertions are written over absence (`text_span = false`, `math = {}`,
`assets = "none"`) and carry no `origin_span` clause; P7 proves only `exact`. Meanwhile
`[store] retain_parts = "when_citable"` retains a `part` iff the **declared** card reads
`{exact, normalized}` ([storage and retrieval](07-store-and-retrieval.md) §8.1) — it must read the
card rather than `achieved`, because retention happens during the parse and `achieved` is computed at
`end_doc` — so an unproved `normalized` roughly doubles corpus storage. P32 is the middle rung's whole
content as an assertion: an address that locates and does not prove.

Three of these deserve emphasis because they are the ones a driver author will want to skip. **P7 is
the only mechanism that makes a third party's honesty machine-checkable** — it is what turns
"byte-identical, safe to edit from" into a property rather than a promise. **P21** catches the
failure class nobody notices: a driver whose block boundaries wobble between identical runs produces
a corpus where every re-ingest retires and re-mints citations, and the symptom appears months later
as broken links in someone's shipped document. **P22** is the only property that tests the staged
generation, which is the mechanism standing between a mid-document crash and a corpus that answers
citations wrongly rather than not at all.

## 18. Open questions

**Q1 — `Scope` named two things, and the charter's own terminology rule forbade it.
Answered by ADR-1.** `serialize(scope: "Scope", fmt, ...)` (charter D2) takes a block selection over
L2; `async def run(scope: "Scope", ctx: "RunContext")` (charter D6) takes the runtime's ingest scope —
roots, globs and a corpus. Neither is defined in the charter, and they are different types in
different layers. This is exactly the collision class `Verdict`/`CacheVerdict` (X14),
`Kind.QUOTE`/`Quote` (X17), `Frame`/frame (X20) and `Layer`/`CacheLayer` (X38) exist to prevent, and
it slipped through. *Answer:* the L2 one is renamed **`ViewScope`** and the runtime's `Scope` keeps
the bare name, because it is the older and more widely referenced of the two (ADR-1 decision 7,
collision 1). §16.1 is `ViewScope`'s sole home and this document writes it everywhere; the lock
carries both rows and lists `Scope` for a block selection as a rejected spelling, so G27(c) enforces
the split rather than merely reporting it. No implementer reads a parameter's layer to know which
type is meant.

**Q2 — the `bytes` branch of INV-10 used the wrong normaliser, and it collapsed two tiers.
Answered by ADR-5.** The charter defines `VERBATIM`'s `bytes` branch as
`normalize_k(part_bytes[a:a+len])[0] == block.text` while `nodepath` and `glyphs` use NFC.
`normalize_k` is NFKC **plus casefold** plus the `Cf`, soft-hyphen, dash and whitespace operations
[structure extraction](06-structure-extraction.md) §1.7 enumerates once, so under it a block whose
text is `"abc"` verified `VERBATIM` against source bytes reading `"ABC"`, whitespace differences were
invisible, and — since `NORMALIZED` is *defined* as "equal to the source under `normalize_k`" — the
top two rungs carried the same predicate, differing only in whether the part was retained.
*Answer:* the `bytes` branch reads
`nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text`, matching the
other two, and `normalize_k` leaves INV-10 for grounding, where casefolding is the point (§7.2, §8.3,
§17 P7). `nfc()` is defined once, in [structure extraction](06-structure-extraction.md) §1.7 beside
`normalize_k`. Charter errata `E48`-`E51` carry the amendment at `:81`, `:1168`, `:1453` and `:8017`,
superseding `E1`, `E2` and `E13`. The evidence fixture is this question's own: a P7 case whose retained
part reads `ABC` and whose `block.text` is `abc`, which passed before and must fail now. The sibling
defect in `GraphSink.mention` — the same function misused for an **offset** rather than a comparison —
was closed separately by §1.7's back-map and `ground()`, and is unaffected.

**Q3 — `tools/wirekeys.toml` was frozen with twenty-two keys and a Block needs twenty-nine.
Answered by ADR-5.** The charter's frozen set at `:1597` omits `cite`, `quote`, `method`, `label`
(the column the charter spelled `title`; Q9), `payload`, `state` and `decision_id`. Omitting `cite`
in particular makes `import(export(store)) == store` unsatisfiable, because a cite is durable and
cannot be re-minted on import. *Answer:* the seven are appended, the file moves to `model_version = "1.1"` and holds all
twenty-nine, and §3.1's table is the mapping's sole home; erratum `E52` supersedes the twenty-two-key
set and leaves frozen-ness and never-reuse unchanged. The append is legal because
`tools/wirekeys.toml` is one of the six append-only registers
([repo layout](11-repo-layout.md) §5.2, §8.3), so no discipline is relaxed to make room. The
enforcer is the round-trip check's fixture: if the export omits `cite`, it fails on the first
round-trip.

**Q4 — the blocks-per-page envelope is unresolved by 3-10×, and every number in §13.4 scales off
it.** The charter's own deferred item F1: 60-120 blocks/page estimated, ~338 B/block measured, one
synthetic corpus at 912 B/block. `store.bytes_per_block = 660` is a nightly ratchet budget at ±10%.
*What closes it:* `fixtures/gen/gen_5000p_pdf.py` plus ten real 200-page documents (a 10-K, a court
filing, a scientific review, a spreadsheet-heavy report), counting Blocks per page **including
cells**. If dense corpora land at ~300 blocks/page, the 8,192-block Frame target, the peak-RSS gate
and every storage projection here retune together.

**Q5 — `MAX_QUOTE_BY_OS_KIND` puts `pixels` at `RECONSTRUCTED`, not `NORMALIZED`. Answered by ADR-5:
the clamp stands, with a pre-committed fallback.** The reasoning
(§8.3) is that `NORMALIZED` means "equal to the source under `normalize_k`", which is uncheckable
without a character-level source. The cost is that `Filters.min_quote = REFLOWED` excludes every OCR
block, which is a large exclusion on scanned corpora — disclosed rather than hidden, because
`corpus_card.verbatim_fraction` prints before any query runs.
*What would reopen it:* a shipped driver with a legitimate need to declare `NORMALIZED` from a pixel
origin, with a stated verification procedure. Absent one, the clamp stands. **Pre-committed
fallback:** if charter question `F32` ([storage and retrieval](07-store-and-retrieval.md) §Open
questions) lands the achieved-exact fraction under ~20% and `retain_parts` defaults to `never`, the
clamp is *not* revisited — with no retained parts there is even less to verify against, and `pixels`
at `RECONSTRUCTED` becomes more correct, not less. Note that the mirror-image
question — whether `none` should reach `NORMALIZED`, which is equally uncheckable — is **already
answered by the charter** ("at release 1 every DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized`",
D3), so §8.3 grants it and `corpus_card.verbatim_fraction` is what discloses the asymmetry.

**Q6 — page-crossing constructs.** §12.3 keeps a page-crossing table as one `table` block with cells
carrying their own `page`, and anchors `addr` at the topmost ancestor's page. The alternative — two
tables joined by `rel(continues)` — is simpler and makes `addr.page == block.page` universal, at the
cost of losing cell-level query and round-trip across the break, and it would delete both M-INV-2 and
the closure pass.
*What closes it:* a fixture corpus with a three-page financial table and the two PPTX round-trip
paths measured against it. If the one-block form does not actually round-trip better, the model
simplifies to the two-block form.

**Q7 — `Kind.SECTION` may have no producer at release 1.** No first-party driver in the charter's
distribution table declares `Capabilities.sections = "typed_levels"`; `parse.office.anydoc` and
`parse.pdf.pdfium` are `outline_from_source` at best. A kind with no producer is dead vocabulary that
every reader must nonetheless fail closed on (§4.2 question 3), and `achieved.sections` can then
never report `typed_levels`.
*What closes it:* whether an EPUB/DITA driver ships at release 1. If not, `section` should be
withdrawn before the first `model_version` freeze rather than deprecated after it — and because
`enum_val.ord` is append-only (§2.1), withdrawing it later costs a retired ordinal forever.

**Q8 — `Capabilities.origin_span`'s middle rung had no enforcer. Answered by ADR-5: three values
stand, no `quote` tier is added, and §17 P32 is the enforcer.** The premise — "an ordered three-value
field whose middle value changes nothing a gate reads" — was checked and is false in two places and
true in one. The `achieved.origin_span` rollup (§2.9) and `byte_exact()`
([storage and retrieval](07-store-and-retrieval.md) §8.2) both read the distinction mechanically. What
read it without checking it was `[store] retain_parts = "when_citable"` (§8.1 there), which retains a
`part` on the **declared** card and so roughly doubles corpus storage on a bit nothing proved: P15
passes vacuously for a driver declaring `normalized` and emitting `os_kind = 'none'` everywhere, P14's
honesty clauses are written over absence and name no `origin_span`, and P7 proves only `exact`.
*Answer:* the field keeps `none`/`normalized`/`exact` (§7.3), no sixth `Quote` tier is added — `Quote`
is a per-block claim about text and `origin_span` a per-driver statement about addressing, and mixing
them is what `byte_exact()` exists to forbid — and the testkit gains **P32**, which obliges a driver
declaring `normalized` to emit an address that locates. *Withdrawal, pre-committed:* if at v1.0 no
driver has declared `normalized` and `when_citable` has never observed it, the rung is withdrawn at
the next `DriverCard` MAJOR and `when_citable` is re-expressed block-side as "retain a `part` iff any
body block has `os_kind <> 'none'`" — the same predicate one layer down. That is affordable because
`Capabilities.origin_span` is a card literal rather than an `enum_val` ordinal, the opposite of
`Kind.SECTION`'s position in Q7.

**Q9 — the `title` column and `Kind.TITLE` shared a word. Answered by ADR-1.** The column is a human
label on a container; `Kind.TITLE` is a document or slide title. They never appear together (a
`title` block carries no container label), so nothing broke, but the charter's own §5 X17 rule — a
block kind and another concept must not share a word — applies. *Answer:* the column is
**`block.label`** and its wire key is **`lb`**; `Kind.TITLE` keeps the word (ADR-1 decision 7,
collision 2). The cost is the one migration and one wire key this question priced, paid before the P2
schema freeze rather than after release 1, and `lb` is an append to `tools/wirekeys.toml` rather than
a reuse — `ti` was named in §3.1's twenty-nine and never shipped. §2.5's field table and §13.1's DDL
are the column's homes; §3.1's table is the wire key's.

**Q10 — two counts in the charter's record are off by one, and both are load-bearing citations.**
`anydoc/src/model/block.rs:5-38` defines **eight** `Block` variants; charter D3 calls it "nine
variants" and then lists eight. And `standard_pdf_pipeline.py`'s `table_score` `nanmean` is at
`:867-871`, over a field defaulted at `base_models.py:419`, not at the single line the charter cites.
Neither affects a decision — anydoc still carries no source address, and docling's grade is still a
three-component mean wearing four — so this document states the verified numbers and records the
divergence rather than propagating it.
*What closes it:* an editorial ADR against the charter's record. No design change.

**Q11 — the charter's printed `DocSink` listing cannot write two things the charter's own schema
requires.** D2 gives `begin_doc(rec) -> None` while its write path makes `begin_doc` the step that
assigns `doc_ord` and fixes the target generation, and `DocRecord` is frozen, so on first sight the
caller has no way to learn either number. D2 also gives `add_rel(..., score)` with no `score_kind`,
while the `rel` table has a `score_kind` column and `Rel` carries the field. §2.10 prints the
corrected signatures — a `DocRecord` return and a `score_kind` parameter — and the method count
stays **eleven**, so [storage and retrieval](07-store-and-retrieval.md) §1.1's 33-method boundary
and §1.2's T3 price are unchanged.
*What closes it:* an editorial ADR against D2's listing. No design change: both corrections are
forced by the charter's own DDL and by its own ordering of the write path, and a
`test_docsink_surface.py` counting the Protocol's methods against `07`'s stated 11 is the gate that
keeps the two documents in step.

## 19. New terms

Coined here and proposed for `_notes/terminology.md`.

| Term | Kind | Definition |
|---|---|---|
| `M-INV-1` … `M-INV-5` | invariant | The document-model-local invariant prefix, subordinate to the framework `INV-*` series exactly as `DR`, `RT`, `ST`, `I`, `GR`, `OUT`, `SV` and `Q-G` are. `M-INV-1` parent-before-child; `M-INV-2` `addr` anchoring at the page anchor; `M-INV-3` the projection law (§16.5); `M-INV-4` no block's `text` repeats a descendant's; `M-INV-5` `layer` is inherited except on a page root. |
| `OsKind` | enum | The five `OriginSpan` variant tags as a Python enum: `bytes`, `nodepath`, `glyphs`, `pixels`, `none`. The source the `origin_span_kind` `enum_val` domain is generated from. |
| `CellPos` | type | A cell's grid position and spans, `(r, c, row_span, col_span)`, carried on a `BlockDraft` so a cell's `addr` step can be minted before `build_grid` runs. |
| `CellDraft` | type | What `build_grid` consumes: an already-minted cell `BlockId` plus its `CellPos`. |
| `Page anchor` | concept | The topmost ancestor of a Block strictly below the `document` root; its `page` is the page component of the Block's `addr` (M-INV-2). Equal to the Block's own page except inside a page-crossing construct. |
| `Page-root ordinal` | concept | A Block's index among the page-root blocks of one page, dense from 0 in `ord` order, and the first step of its `addr`. Page-local rather than document-global, so re-parsing one page renumbers no other. |
| Closure pass | concept | The `end_doc()` bottom-up rewrite of the `content_digest` of blocks whose subtree closes on a later page than their own. `O(cross-page containers)`. Why a merkle digest survives per-page transaction commit. |
| `Target generation` | concept | `g_t = doc.gen + 1`, the generation a parse writes into. Rows at `g_t` are durable and invisible until `end_doc()` bumps `doc.gen`; `gen = 0` means no committed generation. The L2 face of the charter's staged generation. |
| `ow_block_head` | view | `block` joined to `doc` on `gen` with `state = 0` — the head-generation projection every reader goes through, and the mechanism that makes a staged generation invisible. |
| `DocRecord` | type | The frozen per-document record `DocSink.begin_doc`/`end_doc` carry and `Doc.rec` exposes — the `doc` row as a value type. Its `gen` is the generation it describes. |
| `PageRecord` | type | The frozen per-page record `DocSink.begin_page` carries — the `page` row as a value type. |
| `AssetDraft` | type | What `DocSink.add_asset` consumes alongside a stream: everything on `asset` except `asset_id`, `doc_ord`, `store_ref` and `restriction_bits`, which the host mints or stamps. Its `sha256` is a claim the host re-computes. |
| `AssetRef` | type | The read-side handle to one asset: identity, media type, dimensions, `store_ref` and `restriction_bits`, with no bytes. `Doc.asset(ref)` turns it into a stream. |
| `Rel` | type | One `rel` row as a value type, returned by `Doc.rels()`. |
| `MAX_QUOTE_BY_OS_KIND` | const | The host-applied ceiling on `Quote` by `OriginSpan` variant, symmetric with `MAX_TRUST_BY_METHOD` and applied at the same site. `pixels` caps at `RECONSTRUCTED`, `none` at `NORMALIZED`, the three re-readable kinds at `VERBATIM`; a block whose `origin_operator` is not `parse.*` caps at `SYNTHETIC`. A tenant may clamp lower; nothing widens it. |
| `MAX_BLOCKS_PER_PAGE` | const | 4,194,304. One page is one transaction, so this is the commit-size ceiling and the answer to charter deferred item F29. Set so the charter's 4M-cell sheet is admissible. |
| `MAX_BLOCK_TEXT_BYTES` | const | 1,048,576. One block's `text`; a longer run is split into `continues`-joined siblings, never truncated. |
| `MAX_MARKS_PER_BLOCK` | const | 4,096. |
| `MAX_BLOCK_DEPTH` | const | 64. The containment spine's depth, matching `os_path`'s ceiling and bounding `addr`. |
| `MAX_PAYLOAD_BYTES` / `MAX_X_BYTES` | const | 16,384 each, over `canonical(payload)` and `canonical(x)`. |
| `MAX_RESIDENT_CELLS` | const | 65,536. The out-of-order-cell buffer in `build_grid`. |
| `MAX_VIEW_BYTES` | const | 67,108,864. One `serialize()` result, checked as the serializer appends. |
| `MARK_HYDRATE_WINDOW` | const | 512. How many `block_id`s a block cursor buffers before issuing one mark query, so a scan is `O(blocks/512)` statements and not `O(blocks)`. |
| `QUAD_SLACK_MPT` | const | 3,000 (3 pt). The tolerance in P6's page-containment assertion, wide enough for a bleed or a skewed scan line and far short of a coordinate-frame error. |
| `x.ow.unknown` | cfg | The framework-reserved extension key under which a reader preserves wire keys it does not recognise, so `export(import(a)) == a` survives a version skew. The `ow` vendor segment is the framework's; no third party may write here. |
| `op.redigest` | member | The host operator that recomputes `content_digest`/`layout_digest` bottom-up after a `digest_recipe` bump, over **every** generation present. The reason a recipe bump is not a re-parse. |
| `op.resegment` | member | The host operator that re-runs the segmenter over stored blocks after a `segment_recipe` bump. |
| `project_schema()` | fn | The projection of a `ViewScope` through a caller's JSON Schema, returning the produced object and a `FieldGrounding` per leaf. The lift-style extraction path, expressed as a view over the model rather than a parallel output. |
| `OW_QUOTE_CLAMPED` | code | Emitted when `MAX_QUOTE_BY_OS_KIND` lowers a driver's claim, carrying the original claim so over-claiming is measurable. |
| `OW_QUAD_NO_DPI` | code | `Quad.from_driver(unit="px")` without a `dpi`. |
| `OW_LAYER_NOT_INHERITED` | code | A non-page-root draft naming a layer different from its parent's (M-INV-5). |
| `OW_SCHEMA_PAYLOAD_INVALID` | code | A `payload` failing its kind's generated schema, raised at `add_block`. |
| `OW_ASSET_DIGEST_MISMATCH` | code | An `AssetDraft` whose declared `sha256` disagrees with the stream the host hashed. |
| `OW_TEXT_SPLIT` | code | A block's `text` exceeded `MAX_BLOCK_TEXT_BYTES` and was split into `continues`-joined siblings. Informational. |
| `OW_DEPTH_FLATTENED` | code | A subtree deeper than `MAX_BLOCK_DEPTH` was flattened into its ancestor. Warning. |
| `OW_MERGE_KIND_MISMATCH` | code | A merge (§8.5a) whose inputs disagree on `kind` or `layer`; refused. |
| `OW_MERGE_PAYLOAD_DROPPED` | code | A merge whose inputs disagree on a shared `payload` or `x` key; the key is dropped. Informational. |
| `OW_HEADING_LEVEL_SKIPPED` | code | A document whose headings skip a level; informational, and the derived depth is made consecutive by L3. |
| `OW_MARK_KIND_UNKNOWN` | code | A `mark.kind` the reader does not recognise; the mark is kept and rendered as no formatting. |
| `OW_REBIND_UNEXPLAINED` | code | A re-parse below `rebind()`'s threshold; the generation is quarantined, not committed. Cleared by `--allow-unexplained-rebind`. |
| `OW_INTEGRITY_UNCHECKED` | code | Already in `codes.toml` via `owcheck`; listed here because §1.1 makes `owcheck` a step of `end_doc()` rather than an archive-only pass. |
