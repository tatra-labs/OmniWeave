"""The fifteen closed vocabularies `enum_val` carries, and the trust ceiling per `Method`.

Specified in 03-document-model.md section 2.1 (the enums themselves, the wire-and-storage
encoding, and the append-only ordinal rule), section 4.1 (the block-type vocabulary member by
member), section 8.2 (`Trust` and `MAX_TRUST_BY_METHOD`), section 8.3 (`Quote`, the
byte-exactness ladder) and section 13.1 (the `enum_val` DDL, which is where the fifteen domain
names are enumerated). The L3 vocabularies are 06-structure-extraction.md sections 1.3, 1.4 and
1.6, with charter.md's `0002_graph.sql` block as their DDL home.

**`enum_val.ord` IS THE STORED VALUE and it is APPEND-ONLY** (03 section 2.1, restated in the
DDL comment at 03:2315). A member may be appended and may never be inserted in the middle or
reordered: stored rows hold the integer, and renumbering silently retypes every historical row.
For an ordered `IntEnum` the ordinal *is* the member's own integer, so the SQL ordinal and the
Python ordinal are one number and `MIN()` / `>=` mean what they say; for a `StrEnum` it is
declaration order and carries no ordering meaning. `enum_val_rows()` below is the single site
that applies that rule -- W2.2's migration renders these rows into SQL rather than recomputing
them, which is what makes "CI asserts parity in both directions" (charter.md:939) a comparison
of one derivation against one table rather than of two derivations against each other.

**`format` is NOT one of the fifteen** (03:2311-2312, charter.md:7948, charter.md:8746 erratum
D26, adr/0012:197). A format token is free text over a *computed* domain -- core's forty-eight
tokens union the enabled cards' `[capability.parse] format_tokens` -- and a computed domain
cannot live in a table whose `ord` is an append-only stored value: two installs with different
cards would disagree about `enum_val`. 05-ingest-and-routing.md:633 and :2074 say otherwise and
are defective; `_notes/build-defects.md` D10 rules for 03.

Stdlib only, like everything under `omniweave_core.model` (03 section 2). This module is inside
one of the nine LAZY subpackages (11-repo-layout.md section 1.3), so nothing eager may import
it: G17 asserts a bare `import omniweave_core` loads none of them.

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum, IntEnum, IntFlag, StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "ENUM_DOMAINS",
    "GENERATION_BLOCKED",
    "MAX_TRUST_BY_METHOD",
    "AliasKind",
    "AnchorKind",
    "ClaimStatus",
    "Kind",
    "Lane",
    "Layer",
    "Method",
    "OsKind",
    "PageKind",
    "Quote",
    "RelKind",
    "TableKind",
    "Taint",
    "TimePrecision",
    "Trust",
    "enum_val_rows",
]


# ---------------------------------------------------------------------------
# 1. `kind` -- the closed block-type vocabulary. 03 sections 2.1 and 4.1.
# ---------------------------------------------------------------------------


class Kind(StrEnum):
    """Thirty-four members plus `UNKNOWN`, in 03 section 4.1's table order.

    `UNKNOWN` is mandatory and asymmetric on purpose (03 section 2.1): a *driver* emitting a
    kind core does not recognise gets `UNKNOWN` plus `raw_kind` and a warning `Diag`, while a
    *reader* loading a stored non-`unknown` kind it does not recognise fails closed. Adding a
    member is a `model_version` MINOR and an APPEND (03 section 4.2); the wire value and the
    `enum_val.ord` are never reused (03:876).
    """

    DOCUMENT = "document"
    SECTION = "section"
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    # Renamed from QUOTE: the tier enum owns that word, in a framework whose central promise is
    # about quoting (03:823, charter.md section 5 X17).
    BLOCKQUOTE = "blockquote"
    CODE = "code"
    TABLE = "table"
    # A cell IS an ordinary Block; its (r, c, row_span, col_span) live in `cell` (03 section 10).
    TABLE_CELL = "table_cell"
    FIGURE = "figure"
    PICTURE = "picture"
    CAPTION = "caption"
    FORMULA = "formula"
    RULE = "rule"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    FOOTNOTE = "footnote"
    ENDNOTE = "endnote"
    SPEAKER_NOTE = "speaker_note"
    COMMENT = "comment"
    FORM = "form"
    FORM_FIELD = "form_field"
    # Separate from FORM_FIELD because docling separates CHECKBOX_SELECTED/UNSELECTED and a
    # boolean is not a label (03:840).
    CHECKBOX = "checkbox"
    KEY_VALUE = "key_value"
    TOC = "toc"
    TOC_ENTRY = "toc_entry"
    REFERENCE = "reference"
    BIBLIOGRAPHY = "bibliography"
    HANDWRITING = "handwriting"
    CHEMICAL = "chemical"
    DIAGRAM = "diagram"
    CONTAINER = "container"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 2. `layer` -- furniture is a column, not a deletion. 03 section 5.
# ---------------------------------------------------------------------------


class Layer(StrEnum):
    """A Block's role in the reading order. A COLUMN, not a second tree (03 section 5).

    Furniture and notes leave the body order and are never deleted, which is the whole reason
    this is five values on `block` rather than a filter applied at parse time.
    """

    BODY = "body"
    FURNITURE = "furniture"
    NOTE = "note"
    ANNOTATION = "annotation"
    HIDDEN = "hidden"


# ---------------------------------------------------------------------------
# 3. `trust` -- ORDERED, weakest lowest. 03 section 8.2.
# ---------------------------------------------------------------------------


class Trust(IntEnum):
    """How the value was obtained. An ordered `IntEnum` with the weakest tier lowest.

    `MIN()` over a set is the set's trust -- which is why `AMBIGUOUS` is 0 -- and it is what
    `segment.trust` holds. Absent on the wire means `AMBIGUOUS`, **and it is counted**, so a
    driver that never sets trust shows up in `ow doc verify` rather than looking clean
    (03 section 8.2). Clamped by `MAX_TRUST_BY_METHOD` after the driver returns; the clamp is a
    ceiling, never a floor.
    """

    AMBIGUOUS = 0
    INFERRED = 1
    EXTRACTED = 2


# ---------------------------------------------------------------------------
# 4. `method` -- which mechanism ran. 03 sections 2.1 and 8.4.
# ---------------------------------------------------------------------------


class Method(StrEnum):
    """One method per pass; two methods is two passes (glossary.md:779).

    Deliberately a `StrEnum` and therefore unordered: `MIN` over `Method` is undefined, and
    03:1744 keys the block-merge rule on the `MAX_TRUST_BY_METHOD` ceiling instead, ties broken
    by declaration order here.
    """

    NATIVE = "native"
    TEXT_LAYER = "text_layer"
    NATIVE_XML = "native_xml"
    OCR_PAGE = "ocr_page"
    OCR_BLOCK = "ocr_block"
    VLM_PAGE = "vlm_page"
    LLM = "llm"
    HEURISTIC = "heuristic"
    ROUNDTRIP = "roundtrip"
    USER = "user"


# ---------------------------------------------------------------------------
# 5. `quote` -- the byte-exactness ladder, ORDERED, weakest lowest. 03 section 8.3.
# ---------------------------------------------------------------------------


class Quote(IntEnum):
    """A Block's quotability tier. An ordered `IntEnum` with the weakest tier lowest.

    This ordering is load-bearing and is the reason the enum is not a `StrEnum`. Every consumer
    treats the numeric minimum as the weakest tier -- `segment.quote_min`, `Filters.min_quote`,
    and the header variants keyed on `min(quote)` over a rendered set. Under a
    declaration-ordered `StrEnum` with `VERBATIM` first, `MIN()` returned the BEST tier present,
    so one verbatim block in a segment made the whole segment pass the byte-exactness gate for
    its reflowed and synthetic members (03:128-134, charter.md:1253-1260).

    The rungs, from 03 section 8.3:
      SYNTHETIC     omniweave wrote this text -- a table synopsis, an OUT placeholder.
      RECONSTRUCTED characters rebuilt from a non-textual source. OCR and VLM output.
      REFLOWED      source characters re-joined across a line, column or page break.
      NORMALIZED    equal to the source under `normalize_k`. A CLAIM, clamped, never proved.
      VERBATIM      re-derivable from retained source bytes, provably, under `nfc()`.

    The wire value is still the lower-case member name (`"verbatim"`), as for `Trust`.
    """

    SYNTHETIC = 0
    RECONSTRUCTED = 1
    REFLOWED = 2
    NORMALIZED = 3
    VERBATIM = 4


# ---------------------------------------------------------------------------
# 6. `page_kind` -- what a `page` row denotes. 03 sections 2.1 and 12.5.
# ---------------------------------------------------------------------------


class PageKind(StrEnum):
    """`w_mpt` / `h_mpt` are NULL when the kind is `stream` (glossary.md:877)."""

    PAGE = "page"
    SLIDE = "slide"
    SHEET = "sheet"
    FRAME = "frame"
    STREAM = "stream"


# ---------------------------------------------------------------------------
# 7. `table_kind` -- `table_meta.kind`. 03 section 10.1.
# ---------------------------------------------------------------------------


class TableKind(StrEnum):
    """`data | layout`, and a layout table is unwrapped by the SERIALIZER, never dropped.

    **Extends the charter**, by exactly the argument 03:124 makes for `OsKind`: the
    `table_kind` `enum_val` domain is named at 03:2311 and charter.md:942, the two variant tags
    are fixed by `table_meta.kind`'s comment (03:1851) and by
    `Grid.kind: Literal["data","layout"]` (03:1883), but no document declares the Python enum
    the domain is generated from -- and `enum_val` is generated from a Python enum by
    construction.
    """

    DATA = "data"
    LAYOUT = "layout"


# ---------------------------------------------------------------------------
# 8. `rel_kind` -- the seven closed intra-document `rel` kinds. 03 section 2.1.
# ---------------------------------------------------------------------------


class RelKind(StrEnum):
    """Containment is NOT among them: containment is `block.parent_id` (charter.md:4832)."""

    CAPTION_OF = "caption_of"
    NOTE_REF = "note_ref"
    CONTINUES = "continues"
    ANCHOR_REF = "anchor_ref"
    HEADING_OF = "heading_of"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"


# ---------------------------------------------------------------------------
# 9. `origin_span_kind` -- the five `OriginSpan` variant tags. 03 sections 2.1 and 2.4.
# ---------------------------------------------------------------------------


class OsKind(StrEnum):
    """The discriminator over the five `OriginSpan` variants, and the source the
    `origin_span_kind` domain is generated from.

    **Extends the charter** (03:124-126): D2 names the domain and the five variant tags but
    never declares the enum. `block`'s two CHECK constraints (03:1438, :1443) resolve members
    of this domain out of `enum_val` by name, so the ordinals here are load-bearing in SQL.
    `PIXELS` caps at `Quote.RECONSTRUCTED` and `NONE` at `Quote.NORMALIZED` (03 section 8.3).
    """

    BYTES = "bytes"
    NODEPATH = "nodepath"
    GLYPHS = "glyphs"
    PIXELS = "pixels"
    NONE = "none"


# ---------------------------------------------------------------------------
# 10. `lane` -- WHAT is being asked for at a rung. charter.md:2413, glossary.md:724.
# ---------------------------------------------------------------------------


class Lane(StrEnum):
    """The five parse lanes then the six graph lanes, in charter.md:2413's order.

    **The plan contradicts itself here and this is the more normative site.** charter.md:942,
    charter.md:4834 and 03:2311 all list `lane` among `enum_val`'s CLOSED domains, and
    charter.md:4834 says `0002_graph.sql` is where the domain is added; charter.md:2415 calls
    the same eleven-member registry "An OPEN registry" and 02-architecture.md:259 puts a
    `LANES` frozenset in `omniweave.route`. The `enum_val` DDL wins because it is the site that
    fixes storage: `ord` IS THE STORED VALUE and is append-only, so a lane a third party could
    add would make two installs disagree about `enum_val` -- the same argument that keeps
    `format` out of the table. A `LANES` frozenset, if `omniweave.route` still wants one, is
    `frozenset(member.value for member in Lane)` and not a second declaration (INV-21).

    `derive_cover` is written only by Segment-grained Passes, so the ledger holds four lanes in
    practice -- `anchor`, `xref`, `entity`, `claim` -- and a `derive_cover` row on the
    `community` lane is a bug (06 section 2.2). The other seven members are still declared.
    """

    TEXT = "text"
    TABLE = "table"
    MATH = "math"
    FIELDS = "fields"
    CAPTION = "caption"
    ANCHOR = "anchor"
    XREF = "xref"
    ENTITY = "entity"
    CLAIM = "claim"
    COMMUNITY = "community"
    SUMMARY = "summary"


# ---------------------------------------------------------------------------
# 11. `akind` -- the ONE anchor/reference-kind vocabulary. charter.md:4839-4844.
# ---------------------------------------------------------------------------


class AnchorKind(StrEnum):
    """Fourteen members, THE SAME VOCABULARY on both sides of the join.

    `anchor.akind` (definitions) and `ref_site.akind` (occurrences) are joined by EQUALITY in
    two views, so they must share a column name and a vocabulary. They previously shared
    neither: `anchor` said `citation_key` where `ref_site` said `citekey`, and every `citekey`
    reference was therefore permanently unresolved with nothing reporting it (06 section 3.8).
    `citekey` wins; the union is these fourteen. A domain name holds exactly one vocabulary --
    `PRIMARY KEY (domain, ord)` cannot hold two -- so `ref_kind` is STRUCK as a second spelling
    of `akind`, and `entity_alias`'s disjoint set keeps its own `alias_kind` domain.

    `EQUATION` is the one member no shipped parse driver emits on the definition side at
    release 1 (06:1031); it has a producer on the occurrence side only. It is still declared,
    because a member with no producer must be visible in `ow graph doctor`'s per-`akind` count
    rather than absent from the vocabulary.
    """

    SECTION = "section"
    CLAUSE = "clause"
    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    CITEKEY = "citekey"
    IDENTIFIER = "identifier"
    DEFINED_TERM = "defined_term"
    FOOTNOTE = "footnote"
    EXHIBIT = "exhibit"
    SLIDE = "slide"
    SHEET = "sheet"
    GLOSSARY = "glossary"
    BOOKMARK = "bookmark"


# ---------------------------------------------------------------------------
# 12. `alias_kind` -- `entity_alias`'s own, DISJOINT vocabulary. charter.md:5017-5020.
# ---------------------------------------------------------------------------


class AliasKind(StrEnum):
    """`alias_kind`, NOT `akind`: the two sets are disjoint and one domain holds one vocabulary.

    Member order is `entity_alias.alias_kind`'s CHECK list, charter.md:5017-5018, which
    glossary.md:405 and 06:127 repeat. An alias with `(taint & UNTRUSTED_SOURCE)` and
    `doc_count = 1` is never a blocking key for cross-document resolution (charter.md:5027).
    """

    CANONICAL = "canonical"
    VARIANT = "variant"
    ABBREV = "abbrev"
    EXPANSION = "expansion"
    TRANSLIT = "translit"
    LLM = "llm"
    USER = "user"


# ---------------------------------------------------------------------------
# 13. `claim_status` -- `claim.status`. charter.md:5099.
# ---------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    """The four values of `claim.status`, in its CHECK list's order.

    The domain is `claim_status` and the column is `status`; the domain name carries the table
    because `enum_val` is one flat namespace and `status` alone would collide.

    **Extends the charter** in the same shape as `OsKind` and `TableKind`: charter.md:942 names
    the domain, charter.md:5099 fixes the four values, and no document declares the enum.
    """

    ASSERTED = "asserted"
    DENIED = "denied"
    SUSPECTED = "suspected"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# 14. `taint` -- five bits, ORed upward and NEVER across edges. charter.md:5297-5320.
# ---------------------------------------------------------------------------


class Taint(IntFlag):
    """A security fact, not a quality one, and deliberately not expressible as lower confidence.

    Bits 5..31 are RESERVED; a thirty-third bit is a migration (charter.md:5298). Taint ORs
    UPWARD -- mention to entity/edge/claim to community_report -- and NEVER ACROSS EDGES,
    because neighbourhood propagation poisons a whole subgraph from one bad PDF and makes the
    bit useless (charter.md:5306-5307). A migration may only downgrade trust and may NEVER
    clear taint (charter.md:5320).

    **The ordinal rule for an `IntFlag` is the plan's silence, and this is the choice.** 03
    section 2.1 and charter.md:948 state the rule for an ordered `IntEnum` (the member's
    integer) and for a `StrEnum` (declaration order) and say nothing about a flag. The stored
    value in `entity.taint`, `mention.taint`, `edge.taint`, `claim.taint` and
    `entity_alias.taint` is a BITMASK -- `taint & TAINT_UNTRUSTED_SOURCE` at charter.md:5027 is
    the shipped predicate -- so `enum_val.ord` here is the member's own integer, i.e. its bit.
    Declaration order would register `HIDDEN_TEXT` at 2 while the stored bit is 4, which is
    exactly the "every stored row means something else" hazard the append-only rule exists to
    prevent. The consequence is that this is the ONE domain whose ordinals are not dense.

    `NONE` is carried as a row (`ord = 0`, `name = 'none'`) because `taint = 0` is a legal and
    very common stored value and `enum_val` is the name-to-stored-value registry. Python
    excludes a zero-valued flag from `iter(Taint)`, so `__members__` is what `_declared()`
    walks.
    """

    NONE = 0
    UNTRUSTED_SOURCE = 1 << 0
    SENTINEL = 1 << 1
    HIDDEN_TEXT = 1 << 2
    OFFSCREEN = 1 << 3
    SINGLE_WITNESS_XDOC = 1 << 4


GENERATION_BLOCKED: Final[Taint] = Taint.SENTINEL | Taint.HIDDEN_TEXT | Taint.OFFSCREEN
"""The three bits that block generation at the OUT gate (charter.md:5305, 14 section 3.2).

`UNTRUSTED_SOURCE` and `SINGLE_WITNESS_XDOC` are deliberately absent: an ordinary third-party
PDF taints everything derived from it, and blocking generation on that bit would block
generation over the corpus the framework exists to read. The three that are here each mean the
document tried to say something to the model.
"""


# ---------------------------------------------------------------------------
# 15. `precision` -- `claim.t_precision`. charter.md:5100, 06:458.
# ---------------------------------------------------------------------------


class TimePrecision(StrEnum):
    """How precise `claim.t_start` / `claim.t_end` are, coarsest first.

    DERIVED BY THE SINK from the shape of the ISO-8601 string -- four characters is `year`,
    seven is `month` -- and never asked of a model, because the precision is already in the
    string and a second place to be wrong is a second thing to be wrong (06:1450, 06:2535).
    `CHECK ((t_start IS NOT NULL OR t_end IS NOT NULL) = (t_precision IS NOT NULL))`.

    **The class name departs from the domain name, and the domain is the one on disk.** The
    `enum_val` domain is `precision` (charter.md:943, charter.md:4835, 03:2311). It is spelled
    `TimePrecision` here because `Locus.precision` is a DIFFERENT and disjoint vocabulary --
    `char | line | block | page | none` (charter.md:5331, 06:2098) -- and binding one name to
    two vocabularies is the INV-21 violation this project has already paid for once. `Locus`'s
    is not this domain and could not be: it is "computed by the query, never stored as a
    column" (06:2106), and `enum_val.ord` is by definition a stored value.
    """

    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    DATETIME = "datetime"


# ---------------------------------------------------------------------------
# The clamp: a ceiling keyed on what could be READ, not on how clever the reading was.
# ---------------------------------------------------------------------------

MAX_TRUST_BY_METHOD: Final[Mapping[Method, Trust]] = MappingProxyType(
    {
        Method.NATIVE: Trust.EXTRACTED,
        Method.NATIVE_XML: Trust.EXTRACTED,
        Method.TEXT_LAYER: Trust.EXTRACTED,
        Method.HEURISTIC: Trust.EXTRACTED,
        Method.USER: Trust.EXTRACTED,
        # The ones a document can talk back on. 03:1621, charter.md:5313.
        Method.OCR_PAGE: Trust.INFERRED,
        Method.OCR_BLOCK: Trust.INFERRED,
        Method.VLM_PAGE: Trust.INFERRED,
        Method.LLM: Trust.INFERRED,
        Method.ROUNDTRIP: Trust.INFERRED,
    }
)
"""The trust ceiling per `Method`. 03 section 8.2, charter.md:5309-5314, transcribed.

Applied BY THE RUNNER after the driver returns; a driver cannot opt out (INV-7). A clamp writes
`OW_GRAPH_TRUST_CLAMPED` carrying the driver's ORIGINAL CLAIM, so over-claiming is measurable in
`ow graph doctor` rather than silently corrected. **The clamp is a ceiling, never a floor.**

`HEURISTIC` at `EXTRACTED` looks wrong and is deliberate (03:1631): the ceiling is keyed on
*what could be read*, not on *how clever the reading was*. A heuristic that splits a `w:tbl`
into rows is reading the file, and the file said so; the heuristic's own uncertainty is `score`
on a named scale, and a coin-flip heuristic must write `AMBIGUOUS` itself.

**One home, two renderings.** W2.2 generates `BEFORE INSERT` triggers on entity / mention / edge
/ claim FROM THIS MAPPING at migration time, with CI parity in both directions: two enforcers,
one truth. The mapping is total over `Method` and a test asserts it, because a `Method` member
with no ceiling is a hole in INV-7 that no generated trigger would show.
"""


# ---------------------------------------------------------------------------
# The registry: the fifteen domains, and the one site that applies the ordinal rule.
# ---------------------------------------------------------------------------

ENUM_DOMAINS: Final[Mapping[str, type[Enum]]] = MappingProxyType(
    {
        "kind": Kind,
        "layer": Layer,
        "trust": Trust,
        "method": Method,
        "quote": Quote,
        "page_kind": PageKind,
        "table_kind": TableKind,
        "rel_kind": RelKind,
        "origin_span_kind": OsKind,
        "lane": Lane,
        "akind": AnchorKind,
        "alias_kind": AliasKind,
        "claim_status": ClaimStatus,
        "taint": Taint,
        "precision": TimePrecision,
    }
)
"""The fifteen CLOSED `enum_val` domains, in 03:2311's order, each with the enum it generates
from.

`format` is not here and never will be; the reason is in this module's docstring. The three OPEN
vocabularies -- `relation`, `etype`, `claim_type` -- are not here either: they get their own
tables, because an enum generated from a Python enum cannot express "a driver may declare a new
relation" (charter.md section 5 X2, 06 section 1.6).

Iteration order is the domain list's order, so `enum_val_rows()` is stable and a migration's
generated INSERT statements are byte-reproducible (INV-24).
"""


def _declared(vocabulary: type[Enum]) -> tuple[Enum, ...]:
    """Every declared member of `vocabulary`, in declaration order, aliases excluded.

    `__members__` rather than `iter(vocabulary)` for one reason: Python excludes a zero-valued
    member of a `Flag` from iteration, and `Taint.NONE` is a legal stored value `enum_val` must
    be able to name. An alias maps a second key onto an existing member, so `member.name ==
    name` is the alias filter; none of the fifteen declares an alias today and a test asserts
    it, because an alias would put two names on one `ord` and `enum_val` has room for one.
    """
    return tuple(member for name, member in vocabulary.__members__.items() if member.name == name)


def enum_val_rows() -> tuple[tuple[str, int, str], ...]:
    """Every `enum_val` row this build writes, as `(domain, ord, name)`, in domain order.

    THE SINGLE SITE THAT APPLIES 03 SECTION 2.1'S ORDINAL RULE. The rule, in the two branches
    the plan states plus the one it is silent on:

    * an `int`-valued member (`Trust`, `Quote`, and `Taint` -- see `Taint`'s docstring for the
      silence and the choice) stores its OWN INTEGER, so the SQL ordinal and the Python ordinal
      are one number and `MIN()` / `>=` / `&` mean what they say;
    * every other member stores its DECLARATION ORDER, which carries no ordering meaning.

    `name` is the LOWER-CASE MEMBER NAME, which is also the wire value (03 section 2.1) and,
    for every `StrEnum` here, the member's own value. 03:1438 and 03:1443 resolve
    `origin_span_kind` members out of `enum_val` by exactly this spelling from inside a `block`
    CHECK constraint, so the case is not cosmetic.

    A migration RENDERS these rows and never recomputes them, and a migration that regenerates
    `enum_val` asserts every existing `(domain, ord, name)` triple is unchanged and fails
    otherwise (03:143-147). That assertion is the mechanism behind "adding a `Kind` member is a
    MINOR".
    """
    rows: list[tuple[str, int, str]] = []
    for domain, vocabulary in ENUM_DOMAINS.items():
        for index, member in enumerate(_declared(vocabulary)):
            stored = int(member) if isinstance(member, int) else index
            rows.append((domain, stored, member.name.lower()))
    return tuple(rows)
