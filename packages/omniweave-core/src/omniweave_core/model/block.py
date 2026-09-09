"""`Block`, `BlockDraft`, `Capabilities`, and the three identities a Block carries.

Specified in 03-document-model.md section 2 -- 2.2 (the identity aliases), 2.5 (`Block` field by
field, plus `Mark`), 2.6 (`BlockDraft`, the one mutable type, and `CellPos`) and 2.9
(`Capabilities`, the fifteen fields). The column half of the field set is
03-document-model.md section 13.1's `CREATE TABLE block`, carried in charter.md:1018-1077.

**`Block`'s field set is FROZEN at P2's exit** (16-roadmap.md section 5), so it is written here
against the DDL column for column: thirty-two fields against forty columns, with the seven
`os_*` columns collapsing into `origin`, the two `ts_*` into `span`, `state` reading as
`tombstoned`, `marks` carrying a satellite table rather than a column, and exactly two columns
-- `payload` and `decision_id` -- deliberately absent because neither is meaningful without a
join (03:311). `test_model_block.py` asserts that correspondence in both directions off the
plan's own DDL fence, and asserts the charter's second transcription of the same list.

**`BlockDraft` is the ONE mutable type in the framework** (03:91, restated by
16-roadmap.md:414). Every other type in this module is `frozen=True, slots=True`, and the test
asserts that over the whole module rather than per class, so a type cannot arrive mutable by
omission.

**The value types a Block is built out of live in `omniweave_core.model.spans`** -- `Quad`, the
five `OriginSpan` variants, `TextSpan` and `SERIALIZER_CAPS` -- and are imported, never
redeclared: 03 section 2.3 is geometry and section 2.4 is the three coordinate systems, both
distinct from section 2.5's node type, and one name gets one home (INV-21). The three identity
aliases of section 2.2 are declared here because a `Block` is what carries them.

Stdlib only, like everything under `omniweave_core.model` (03 section 2): no pydantic, no
numpy, no PIL. This module is inside one of the nine LAZY subpackages (11-repo-layout.md
section 1.3), so nothing eager may reach it -- G17 asserts a bare `import omniweave_core` loads
none of the nine.

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, NewType

from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.spans import OriginNone, OriginSpan, Quad, TextSpan

# `Mapping` is a runtime import, not an `if TYPE_CHECKING:` one, and that is load-bearing:
# `Block.x` is annotated `Mapping[str, Any]`, so a name that exists only for a type checker
# makes `typing.get_type_hints(Block)` raise `NameError` -- and the field-to-column test,
# `ow schema emit`'s reflector and every other runtime walk of this module's annotations go
# through exactly that call. `collections.abc` is stdlib and already resident.

__all__ = [
    "Addr",
    "Block",
    "BlockDraft",
    "BlockId",
    "Capabilities",
    "CellPos",
    "Cite",
    "Mark",
]


# ---------------------------------------------------------------------------
# 1. Identity -- three of the four identities, and their jobs. 03 section 2.2.
# ---------------------------------------------------------------------------

BlockId = NewType("BlockId", int)
"""Store-local, durable int64 surrogate. **The only FK target for a Block** (03:270).

Never exported, never shown to a model, never a prompt token: that is `Cite`'s job. The DDL
carries `CHECK ((block_id >> 48) = 0)` with the shard ordinal interpolated as a literal by the
migration (03:2364), which is a storage constraint and not a property of this alias.
"""

Addr = NewType("Addr", str)
"""The type-free positional path: `doc`, `p14/3`, `p14/3/r2c5`. 03 sections 2.2 and 6.2.

Unique per `(doc_ord, gen)` -- `addr` is a POSITION, so it legitimately repeats across
generations, which is why `block_addr` is keyed on the generation and `block_cite` is not
(charter.md:1082-1086). Type-free on purpose: a step says where, never what.
"""

Cite = NewType("Cite", str)
"""The prompt-safe token, `[<corpus>:]d<doc_ord>#<n>`. 03 sections 2.2 and 6.3.

`n` comes from `doc.next_cite_n` and is DURABLE across generations, which is why a cite cannot
be re-minted on import and why the archive wire had to grow a `c` key (03:687).
"""

# `DocKey = NewType("DocKey", bytes)` is the fourth of 03 section 2.2's identities and is
# deliberately NOT declared here: it is a *document* identity, `Block` never carries it, and its
# only consumer is `DocRecord` (03 section 2.8), which this cluster does not own. Declaring it
# here would put one name in a home that has nothing to do with it (INV-21).


# ---------------------------------------------------------------------------
# 2. `Mark` and `Block`. 03 section 2.5.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mark:
    """Sparse inline formatting over `block.text`. 03:260, section 2.7.

    Ranges are half-open char offsets into `block.text` with `0 <= a <= b <= len(text)`, and a
    zero-width mark (`a == b`) is legal and meaningful for `anchor` and `note_ref` (03:381).
    `kind` is a string over section 2.7's release-1 vocabulary rather than an enum: the table is
    open at the edges -- `raw_style` keeps "a run style the model has no field for" -- and
    `mark.kind` is `TEXT NOT NULL` in the DDL (03:2412), not an `enum_val` domain.

    Stored with a **surrogate** `mark_id`, because two links may cover exactly the same range
    (03:354), and overlapping ranges are representable on purpose: marker's one
    `formats: List[Literal[...]]` per `Span` cannot express bold ending mid-italic, and that
    collapse is unexpressible here (03:369).

    Bare `a`/`b` ints rather than a `TextSpan` because that is what 03:260 prints and what the
    `mark` table holds: `mark(a, b)` is its own column pair with its own CHECK, and a `TextSpan`
    field would put a second name on `ts_a`/`ts_b`'s quantity.
    """

    a: int
    b: int
    kind: str
    value: Any | None = None


@dataclass(frozen=True, slots=True)
class Block:
    """The single node type. 03 section 2.5; the DDL is 03 section 13.1.

    Thirty-two fields against the `block` table's forty columns. `origin` collapses the seven
    `os_*` columns (03 section 7.2 gives the mapping), `span` collapses `ts_a`/`ts_b`,
    `tombstoned` is `state`, and `marks` is the `mark` table hydrated in 512-block windows
    rather than a column (03 section 2.7). Two columns are on the table and deliberately not
    here: `payload`, read through `Doc.payload(id)`, and `decision_id`, read through the
    runtime's `route_decision` -- neither is meaningful without a join and neither is on the hot
    path of a render (03:311).

    `method`, `trust` and `quote` have **no defaults**. Absent `trust` on the wire means
    `AMBIGUOUS` and it is COUNTED, so a driver that never sets trust shows up in
    `ow doc verify` rather than looking clean (03:1613).

    **Append-only, with exactly one named exception.** There is no `DELETE` -- retirement is
    `state = 1` plus a `block_history` row -- and no `UPDATE`, except the identity-carrying
    `UPDATE` that `rebind()` performs inside `end_doc()`'s transaction, which moves a carried
    row's `gen` forward (03:313).

    No validation in a `__post_init__`, and that is a decision rather than an omission: every
    rule a Block obeys is a rule about a Block's *relationship* to something else -- `layer`
    equals the parent's unless the block is a page root (M-INV-5), `text` never repeats a
    descendant's (M-INV-4), `layout_digest` is NULL iff `quad` is NULL, `label` is NULL on a
    text block -- and none of them is checkable from one instance. `DocSink.add_block` is where
    they are enforced (03 section 2.10) and `owcheck` over `g_t` is where they are re-proved.
    The two rules that ARE local, `score`/`score_kind` nullable together and the `os_*`
    implications, are CHECK constraints on the table and `__post_init__` validation on the
    `OriginSpan` variants respectively.
    """

    # -- identity. Written by the host; `page` by the driver. 03 sections 2.2, 6.1-6.3.
    id: BlockId  # 03:238 fixes the name; `block_id` is the column.
    addr: Addr
    cite: Cite
    doc_ord: int
    gen: int
    page: int
    # -- the containment spine. `ord` IS reading order: there is no second `position` field.
    parent: BlockId | None
    ord: int  # 03:239 fixes the name; dense from 0 among siblings.
    # -- classification. Written by the driver. Sections 4 and 5.
    kind: Kind
    raw_kind: str | None
    layer: Layer
    label: str | None
    text: str | None
    # -- digests and revision. Written by the host. Section 6.4.
    content_digest: bytes
    layout_digest: bytes | None
    revision: int
    # -- position and address in the original container. Sections 7.1, 7.2, 7.4.
    quad: Quad | None
    origin: OriginSpan
    span: TextSpan | None
    # -- provenance: six axes, never conflated. Section 8.1.
    producer_id: int
    method: Method
    trust: Trust
    quote: Quote
    score: float | None = None
    score_kind: str | None = None
    origin_operator: str = ""
    origin_driver: str = ""
    driver_schema_v: int = 0
    restriction_bits: int = 0
    # -- satellites and state.
    marks: tuple[Mark, ...] = ()
    tombstoned: bool = False
    x: Mapping[str, Any] = MappingProxyType({})


# ---------------------------------------------------------------------------
# 3. `CellPos` and `BlockDraft` -- the one mutable type. 03 section 2.6.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CellPos:
    """A table cell's grid position. 03:319. **Extends the charter**: D2 names no such type.

    It exists on `BlockDraft` because a cell's `addr` step is `r<r>c<c>` (03 section 6.2), so
    the position must be known at MINT time, inside `add_block` -- while `Grid`'s slots hold
    `BlockId`s, so `build_grid` and therefore `add_grid` necessarily run AFTER the cells are
    minted. One optional field closes the loop without adding a twelfth method to `DocSink`,
    whose eleven are fixed and printed in 03 section 2.10 (03:331).
    """

    r: int
    c: int
    row_span: int = 1
    col_span: int = 1


@dataclass(slots=True)
class BlockDraft:
    """Everything `Block` carries except what the HOST mints. **The one mutable type.**

    No `id`, no `addr`, no `cite`, no `producer_id`, no `origin_*`, no `restriction_bits`
    (03:322-325). Mutable on purpose, so an assembler can fill fields in the order the source
    yields them; it never reaches a reader, and every other model type is frozen.

    `kind`, `layer`, `method`, `trust` and `quote` have **no defaults**: a driver that has not
    thought about trust cannot silently ship `EXTRACTED`, it must write `Trust.AMBIGUOUS` and be
    counted (03:339).

    `cell is not None` implies `kind == Kind.TABLE_CELL` and a `parent` of kind `table`, both
    asserted at `DocSink.add_block` rather than here: a draft is mutable, so a constructor-time
    check could be unmade by the next assignment, and `add_block` is the point at which the pair
    is final (03:334).

    `payload` is a field here and not on `Block`: the draft carries the JSON object that becomes
    the `payload` column and a digest input, while a reader gets it through `Doc.payload(id)`
    rather than paying a `json.loads` per row of a 600k-block scan (03:985).
    """

    kind: Kind
    layer: Layer
    method: Method
    trust: Trust
    quote: Quote
    parent: BlockId | None = None
    text: str | None = None
    label: str | None = None
    raw_kind: str | None = None
    quad: Quad | None = None
    # RUF009's premise is a SHARED MUTABLE default, and `OriginNone` is a
    # frozen, slotted, fieldless dataclass, so every instance is interchangeable. The plan
    # prints exactly this default (03:330) and it is the point: "`OriginNone()` is a **value**,
    # not a null" (03:1466). `field(default_factory=OriginNone)` would allocate a new equal
    # object per draft to no end; ruff cannot see the frozen-ness across the import.
    origin: OriginSpan = OriginNone()  # noqa: RUF009
    span: TextSpan | None = None
    score: float | None = None
    score_kind: str | None = None
    payload: Any | None = None
    cell: CellPos | None = None
    marks: list[Mark] = field(default_factory=list)
    x: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 4. `Capabilities` -- fifteen fields, one field set, three homes. 03 section 2.9.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Capabilities:
    """The fifteen capability fields. 03 section 2.9; 04-driver-system.md section 2.2.

    This dataclass, `driver.toml [capability.parse]` and `doc.declared` / `doc.achieved` are
    **the same fifteen fields** -- one field set, three homes (03:530, charter section 5 C2).
    `omniweave_core.drivers.card.ParseCapability` is the card half and carries a sixteenth key,
    `format_tokens`, which is card-only and never appears on a `Doc`; the ten ordered ladders
    below are `card.PARSE_LADDERS` and `test_model_block.py` asserts the two agree member for
    member and in order.

    `declared` is the card's claim, copied onto `doc` at parse time. `achieved` is what the
    driver actually delivered on THIS document, computed by the host from the committed rows
    rather than reported by the driver (INV-7 at the capability grain, 03:536), and it may be
    lower, never higher. **Serve reads `achieved`** (charter section 5 X9): a card cannot know
    what a particular PDF permitted.

    `origin_span` and `reading_order` are ORDERED, and `reading_order`'s order is marker's own
    measurement rather than how the words sound -- `char_stream` beats `learned` 75% to 56% on
    multi-column pages (03:555). `math` is a **set**, not a ladder: latex versus mathml is a
    notation choice, not a quality rung. `forfeits` is the only field with a default, because
    "forfeits nothing" is what an absent forfeits list says.

    `spanmap` is deliberately not a sixteenth field: a `SpanMap` is emitted by core's own
    serializer over core's own five formats, which a parse driver never calls, so the field had
    no writer and nothing for the conform `capability` suite to assert. That fact lives in
    `omniweave_core.model.spans.SERIALIZER_CAPS` (03:531).
    """

    spatial: Literal["none", "page_bbox", "block_bbox", "line_bbox", "char_bbox"]
    origin_span: Literal["none", "normalized", "exact"]
    text_span: bool
    marks: bool
    reading_order: Literal["raster", "learned", "model_emitted", "char_stream", "source"]
    sections: Literal["none", "markdown_only", "outline_from_source", "typed_levels"]
    tables: Literal["none", "flat_html", "cells", "cells_with_spans"]
    math: frozenset[str]
    assets: Literal["none", "refs", "bytes"]
    asset_origin: bool
    notes: Literal["none", "inline", "linked"]
    confidence: Literal["none", "document", "page", "element"]
    furniture: Literal["destroyed", "flagged", "separated"]
    round_trip: Literal["none", "text", "structure", "passthrough"]
    forfeits: frozenset[str] = frozenset()
