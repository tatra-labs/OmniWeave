"""`DocSink` -- the eleven L2 write methods, and the only writer of L2.

Implements 03-document-model.md section 2.10 (:538-620): the eleven signatures, the table of what
each one mints, stamps or enforces (:574-597), and the two charter divergences recorded there as
Q11. `01-principles.md:838` names this module's class in as many words --
`omniweave_core.store.doc.DocSink.add_block` -- which is why the concrete writer here carries the
same name as the Protocol it satisfies: one concept, one name (03:571).

**The write path is 03 section 1.1 (:54-86) and the order is load-bearing.**

```
begin_doc(rec)         insert or look up `doc` by doc_key; assign doc_ord; gen = 0 on first sight;
                       record `declared`; fix the target generation g_t = doc.gen + 1
  begin_page(pg)         insert the `page` row at (doc_ord, g_t, page); reset the page-root counter
    add_block(draft)     mint block_id, addr, cite, ord; stamp provenance; PROVISIONAL digest
    add_marks / add_grid / add_rel / add_asset / add_part / diag
  end_page(stats)      COMMIT ONE TRANSACTION. Rows are durable and invisible (g_t > doc.gen).
end_doc(status)        one final transaction: the closure pass, `owcheck` over g_t,
                       `rebind(store, doc_ord, g_t)`, `achieved` + `doc.confidence`, and iff not
                       quarantined `UPDATE doc SET gen = g_t`
```

**Nothing is visible before the `doc.gen` bump** (03:75-80). Every reader resolves through
`ow_block_head`, which joins `block.gen = d.gen`, so a crash at page 3,000 of 5,000 leaves 3,000
durable and invisible pages with the previous generation still answering every citation.
`gen = 0` is reserved and means "no committed generation" (03:82-85), which is why a first-sight
`doc` row is written at `gen = 0` and the DDL's `DEFAULT 1` stays vestigial.

**Writes reach the store as `Unit`s and this module opens no connection** (07:2714-2743, INV-17).
`store/sqlite.py`'s `StoreThread` is the one holder of a `Connection` in a process; `end_page`
submits one `Unit` and that `Unit` IS the page's transaction. `import sqlite3` below is legal
because this file is under `store/` and `pyproject.toml`'s per-file-ignore covers TID251 there; it
is imported for the `Connection` type a `Unit`'s closure receives and for nothing else.

**Buffered, then written once.** `add_block` returns a `BlockId` immediately, so the ids cannot come
from SQLite's rowid sequence: `block_id := (shard_ord << 48) | sequence` (03:1062) is minted here
from a high-water mark read at `begin_doc`, and the row itself is one entry in the open page's
statement buffer. Two facts fall out and both are wanted. A digest over a subtree that closes on
this page can be finalised BEFORE the row is written, so only genuinely page-crossing containers
carry a provisional digest into `end_doc`'s closure pass (03:1226-1234). And `end_page` is one
`Unit`, so "commits one transaction" is a property of the shape rather than a discipline.

**The clock, the ids and the randomness come from the caller.** There is no `time.time`, no
`uuid4`, no `random` here (02-architecture.md:392, `tools/gate_semgrep.py`): `AssetDraft`'s
`retrieved_at_ns` is the driver's, `producer_id` is resolved by the runner before the sink is
constructed, and the only sequences this module advances -- `block_id`, `asset_id`,
`doc.next_cite_n` -- are read from the store and written back inside a transaction.

## What is NOT here, and who owns it

* **`block_asset` has no writer among the eleven, and that is a plan defect, not a choice here.**
  03:589's cell for `add_asset` says exactly what it writes -- "hashes the stream itself
  (`OW_ASSET_DIGEST_MISMATCH` on disagreement), writes `store_ref`, dedups on
  `(doc_ord, sha256, IFNULL(origin_part,''))`, stamps `restriction_bits`. Returns `asset_id`" --
  and names no join row; no other cell of that table names one either. Yet `block_asset` is `[SOR]`
  (03:2474-2476), `owdoc-fragment/1` discriminates a `block_asset` record (03:635), and conformance
  P23 (03:3007) requires "two blocks referencing identical bytes produce one `asset` row and two
  `block_asset` rows". `add_asset` therefore writes the `asset` row and nothing else, exactly as
  printed, and the missing writer is reported rather than invented: inventing a role from the
  block's `kind`, or linking to "the most recent block", would put a fact in the store that no
  definition site put there.
* **The `payload` JSON-Schema validator.** 03:983-985 says "the same ~200-line validator checks a
  payload at `DocSink.add_block` and at archive read", and `schema.json` with one
  `$defs/payload.<kind>` per row of 03:955-974 is `ow schema emit`'s output. That file does not
  exist yet (`schema/` holds `driver-card-v1.json` and `fragment-v1.json`). What `add_block`
  enforces is therefore 03:998-1005's stated RULES -- canonicalisable, flat-ish, capped at
  `MAX_PAYLOAD_BYTES`, unknown keys preserved -- plus the two per-kind constraints 03:977 prints
  verbatim (`heading.level` integer 1..9, `checkbox.checked` boolean). Transcribing a schema for
  the other fourteen kinds out of a comment block would be an invention; reported.
* **The `score_kind` register.** 03:1715-1717 puts the scale in "an append-only
  `tools/scorekinds.toml`" and 03:295 makes an unregistered kind "raise at `DocSink.add_block`";
  01-principles.md:531 classes that raise as INV-19's `A` enforcer. **That file does not exist.**
  So the register is a constructor parameter, `score_kinds`, taken from the caller like every other
  ambient input, and its default is EMPTY -- with no register loaded every kind is unregistered and
  every scored draft raises, which is the fail-closed direction Q-G10 asks for.
* **`MAX_QUOTE_BY_OS_KIND` and `clamp_quote`** are 03 section 8.3's (:1673-1685) and belong beside
  `MAX_TRUST_BY_METHOD` in `omniweave_core/model/enums.py`, whose docstring already claims section
  8.3; `model/__init__.py:80` lists both as still owed by P2. They are transcribed here as PRIVATE
  names against that day, and `test_store_doc.py` asserts the local table against the plan's own
  printed fence and against `model.enums` the moment the public name appears.
* **`layout_digest`** has the same shape of gap: `omniweave_core.identity` homes
  `content_digest()` (03:1194-1200) and not its geometric twin (:1202-1205). Private here, parity
  asserted, required edit reported.

Tier T-SCHEMA: 02-architecture.md section 2 row 26. Stdlib only (INV-2 / G1). One of the nine LAZY
names, so nothing eager may reach it (G17).
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, get_args, get_origin, get_type_hints

from omniweave_core.archive.owcheck import BlockFacts as OwcheckFacts
from omniweave_core.archive.owcheck import Generation, owcheck
from omniweave_core.archive.owdoc import GridRow
from omniweave_core.canonical import canonical, ow128
from omniweave_core.errors import ModelError, ResourceLimit
from omniweave_core.identity import content_digest as ow_content_digest
from omniweave_core.limits import (
    MAX_BLOCK_DEPTH,
    MAX_BLOCK_TEXT_BYTES,
    MAX_BLOCKS_PER_DOC,
    MAX_BLOCKS_PER_PAGE,
    MAX_EXPANSION,
    MAX_MARKS_PER_BLOCK,
    MAX_PAYLOAD_BYTES,
    MAX_X_BYTES,
)
from omniweave_core.model.block import Addr, BlockDraft, BlockId, Capabilities, Cite, Mark
from omniweave_core.model.enums import (
    ENUM_DOMAINS,
    MAX_TRUST_BY_METHOD,
    Kind,
    Layer,
    OsKind,
    PageKind,
    Quote,
    RelKind,
    TableKind,
    Trust,
    enum_val_rows,
)
from omniweave_core.model.rebind import (
    DEFAULT_THRESHOLD,
    REBIND_UNEXPLAINED,
    BlockFacts,
    Carry,
    RebindReport,
    Retire,
    rebind,
)
from omniweave_core.model.records import (
    DOC_STATUSES,
    QUAD_ORIGINS,
    AssetDraft,
    Diag,
    DocRecord,
    PageRecord,
)
from omniweave_core.model.spans import (
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginPixels,
    OriginSpan,
    Quad,
)
from omniweave_core.store.sqlite import BATCH_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:  # pragma: no cover - annotations only.
    from typing import BinaryIO

    from omniweave_core.blobs import BlobStore
    from omniweave_core.model.grid import Grid

__all__ = [
    "ASSET_DIGEST_MISMATCH",
    "LAYER_NOT_INHERITED",
    "QUOTE_CLAMPED",
    "SCHEMA_PAYLOAD_INVALID",
    "SCORE_KIND_UNREGISTERED",
    "TRUST_CLAMPED",
    "DocSink",
]


# ---------------------------------------------------------------------------
# 0. The `codes.toml` symbols this module records or raises.
#
# `diag.code` holds the SYMBOL, never the numeric (03:1806-1808). None of these has a `codes.toml`
# row yet -- the register is seeded from the plan's definition sites and filling `meaning`/`fix` is
# W1.3's -- so they are declared as names here exactly as `model/rebind.py` declares
# `REBIND_UNEXPLAINED` and `archive/owcheck.py` declares `OW_LAYER_NOT_INHERITED`.
# ---------------------------------------------------------------------------

ASSET_DIGEST_MISMATCH: Final = "OW_ASSET_DIGEST_MISMATCH"
"""The driver's claimed `AssetDraft.sha256` disagrees with the stream. 03:589, :2137-2140.

Raised, never recorded: *"a content-addressed store with an unverified writer is a substitution
oracle"* (03:2140), so the asset is rejected rather than stored under a digest nobody checked.
"""

LAYER_NOT_INHERITED: Final = "OW_LAYER_NOT_INHERITED"
"""A non-page-root draft naming a layer other than its parent's. M-INV-5, 03:1029-1031.

Spelled identically in `archive/owcheck.py:78`, which re-asserts the same invariant over a whole
generation; one symbol, two enforcers.
"""

QUOTE_CLAMPED: Final = "OW_QUOTE_CLAMPED"
"""`MAX_QUOTE_BY_OS_KIND` (or the derive clamp) lowered a draft's claim. 03:1697."""

TRUST_CLAMPED: Final = "OW_GRAPH_TRUST_CLAMPED"
"""`MAX_TRUST_BY_METHOD` lowered a draft's claim. 03:1620, `model/enums.py:505`.

The symbol says `GRAPH` and is written by an L2 write, which looks wrong and is the plan's: the
same ceiling is mirrored into L3's generated `BEFORE INSERT` triggers ("two enforcers, one truth",
03:1626-1628) and one concept gets one symbol.
"""

SCHEMA_PAYLOAD_INVALID: Final = "OW_SCHEMA_PAYLOAD_INVALID"
"""A `payload` that fails its kind's schema. 03:979 -- *"at write, not a puzzle later"*."""

SCORE_KIND_UNREGISTERED: Final = "OW_SCORE_KIND_UNREGISTERED"
"""An unregistered `score_kind`. 03:295, :1715-1717; INV-19's `A` enforcer (01:531).

No definition site spells a symbol for this condition -- the plan names only the raise -- so the
spelling is this module's and a `codes.toml` row for it is a required edit. The numeric is not
guessed here: `codes.toml` is a transcription and inventing a row is not a fix.
"""

_MAX_QUOTE_BY_OS_KIND: Final[Mapping[OsKind, Quote]] = MappingProxyType(
    {
        OsKind.BYTES: Quote.VERBATIM,
        OsKind.NODEPATH: Quote.VERBATIM,
        OsKind.GLYPHS: Quote.VERBATIM,
        # the polygon is the address; there is no character source
        OsKind.PIXELS: Quote.RECONSTRUCTED,
        # real characters were read; the driver cannot say from where
        OsKind.NONE: Quote.NORMALIZED,
    }
)
"""03:1675-1681's fence, verbatim. **PRIVATE, and the underscore is the whole point.**

The public home is `omniweave_core.model.enums`, beside `MAX_TRUST_BY_METHOD`: that module's
docstring already claims 03 section 8.3 and `model/__init__.py:80` lists this name as owed by P2.
`add_block` cannot apply a clamp it does not have, and a second PUBLIC home would be the INV-21
violation. `test_store_doc.py` asserts this table against the plan's printed fence and against
`model.enums.MAX_QUOTE_BY_OS_KIND` as soon as that attribute exists, so the move is a two-line
edit that cannot silently disagree.

`NONE` caps at `NORMALIZED` and not `SYNTHETIC` because the charter already ruled on the case it
governs -- with `parse.office.anydoc` at `origin_span = "none"`, "at release 1 every
DOCX/ODT/RTF/EPUB/CSV Block is `quote = normalized`" (03:1687-1690). `_clamp_quote`'s second clamp
is what stops that ceiling laundering a derived block.
"""

_LAYER_BY_PAGE_ROOT_KIND: Final[Mapping[Kind, Layer]] = MappingProxyType(
    {
        Kind.PAGE_HEADER: Layer.FURNITURE,
        Kind.PAGE_FOOTER: Layer.FURNITURE,
        Kind.FOOTNOTE: Layer.NOTE,
        Kind.ENDNOTE: Layer.NOTE,
        Kind.SPEAKER_NOTE: Layer.NOTE,
        Kind.COMMENT: Layer.ANNOTATION,
    }
)
"""M-INV-5's page-root default, transcribed from 03:1027-1029.

*"where the driver states it and `DocSink` defaults it from the kind: `page_header`/`page_footer`
to `furniture`; `footnote`/`endnote`/`speaker_note` to `note`; `comment` to `annotation`;
everything else to `body`."* A DEFAULT and not a clamp: a driver that states a layer on a page root
keeps it, which is what makes `Layer.HIDDEN` reachable at all -- no kind implies it.
"""

_LAYOUT_DOMAIN: Final = b"ow.layout.1"
_MPT_PER_POINT: Final = 1_000
_SEQUENCE_BITS: Final = 48
_MAX_SHARD_ORD: Final = 32_767
_MAX_ADDR_CHARS: Final = 512
_MAX_RAW_KIND_CHARS: Final = 128
_X_KEY_SEGMENTS: Final = 3
_RESERVED_X_VENDOR: Final = "ow"
_MIN_HEADING_LEVEL: Final = 1
_MAX_HEADING_LEVEL: Final = 9
_CONFIDENCE_COMPONENTS: Final = ("parse", "layout", "table", "ocr")

_FIX_VERIFY: Final = "ow doc verify <cite>"
_FIX_REPARSE: Final = "ow add <uri> --force-reparse"


# ---------------------------------------------------------------------------
# 1. Pure helpers. Each is a transcription of one plan rule; none touches a connection.
# ---------------------------------------------------------------------------

_ORDINAL: Final[Mapping[tuple[str, str], int]] = MappingProxyType(
    {(domain, name): ordinal for domain, ordinal, name in enum_val_rows()}
)
"""The stored-value direction of 03 section 2.1's ordinal rule, read off its single site.

`model/enums.py:enum_val_rows()` is *"THE SINGLE SITE THAT APPLIES 03 SECTION 2.1'S ORDINAL
RULE"*, and `enum_val` is the stored registry those rows seed, so deriving this map from that one
call is what keeps this module from becoming a second place the rule could be wrong.
"""

_MEMBER: Final[Mapping[tuple[str, int], Enum]] = MappingProxyType(
    {
        (domain, ordinal): ENUM_DOMAINS[domain].__members__[name.upper()]
        for domain, ordinal, name in enum_val_rows()
    }
)
"""The read-back direction of the same rule: `(domain, ord) -> member`.

An `int`-valued member stores its own integer and every other member stores its declaration
order, so `Trust`/`Quote` round-trip through their values and `Kind`/`Layer`/`Method` through a
position -- and a reader that guessed either would be wrong for half the fifteen domains.
"""


def _ordinal(domain: str, member: Enum) -> int:
    """The stored `enum_val.ord` for one member of one closed domain."""
    return _ORDINAL[domain, member.name.lower()]


def _clamp_quote(claim: Quote, os_kind: OsKind, origin_operator: str) -> Quote:
    """03:1683-1686's `clamp_quote`, transcribed. A ceiling, never a floor.

    The second clamp is not decoration: a table synopsis has `os_kind = none` and
    `origin_operator = 'derive.table'`, so it lands at `SYNTHETIC` (03 section 8.5(b)) rather than
    inheriting `NORMALIZED` from the `none` row of the table above.
    """
    ceiling = _MAX_QUOTE_BY_OS_KIND[os_kind]
    if not origin_operator.startswith("parse."):
        ceiling = min(ceiling, Quote.SYNTHETIC)
    return min(claim, ceiling)


def _whole_points(value: int) -> int:
    """One millipoint coordinate quantised to whole points, half away from zero.

    03:1202-1205 makes `layout_digest`'s geometry input "quad quantised to WHOLE POINTS ... kills
    driver jitter". Integer arithmetic and not `round(v / 1000)`: a float divide reintroduces
    exactly the libm- and platform-dependence 03:181-183 excludes geometry from `content_digest`
    to avoid, and this digest is a cache key too.
    """
    if value < 0:
        return -((-value + _MPT_PER_POINT // 2) // _MPT_PER_POINT)
    return (value + _MPT_PER_POINT // 2) // _MPT_PER_POINT


def _layout_digest(content: bytes, page: int, quad: Quad | None) -> bytes | None:
    """`ow128(b'ow.layout.1', [content_digest, page, quad in whole points])`, or `None`.

    03:1202-1205's recipe. NULL iff `quad` is NULL, which the `block` DDL states as a comment and
    03:290 as a field rule. `content` is embedded as hex for the reason
    `identity.content_digest()` embeds its children as hex: `canonical()` has no `bytes` arm.

    **Private, and owed a public home.** `omniweave_core.identity` is where `content_digest()`
    lives and where this belongs; see the module docstring.
    """
    if quad is None:
        return None
    return ow128(_LAYOUT_DOMAIN, [content.hex(), page, [_whole_points(v) for v in quad]])


def _quad_blob(quad: Quad | None) -> bytes | None:
    """`block.quad`'s "8 x i32 LE, or NULL" (03:2338, charter.md:1039)."""
    return None if quad is None else struct.pack("<8i", *quad)


def _diag_bind(row: Mapping[str, Any]) -> dict[str, Any]:
    """One `owcheck` diag row, made bindable. **`archive/owcheck.py` hands us a `dict` here.**

    Two functions write the `diag` table and until this one existed they disagreed. `_diag_row`
    below (the `DocSink.diag` path) sends `detail` through `_json_column`; `owcheck.py`'s two row
    builders -- `_diag_row` at `owcheck.py:247` and the UNCHECKED arm at `:228` -- put a raw
    Python `dict` in the same key. `sqlite3` refuses to bind a `dict`, so binding those rows
    straight into `_DIAG_INSERT` raised
    `ProgrammingError: Error binding parameter 10: type 'dict' is not supported`.

    What that cost is out of proportion to the typo. `03:66-72` designs `end_doc` so that an
    owcheck violation **quarantines the generation**: the store stays consistent and the head does
    not move. A bind error instead propagates out of `end_doc` as a driver-level exception, so any
    ingest whose owcheck found one violation -- **or merely left one clause UNCHECKED, which is a
    `warning`** -- could not commit at all, and took the failure path the quarantine exists to
    avoid. It was invisible only because every fixture in the tree produced an EMPTY owcheck
    report: the code path was reachable and had never once been entered (ledger D39, and C-series
    territory -- a vacuous green rather than a wrong answer).

    Fixed on this side rather than in `owcheck.py` so the JSON encoding of a `diag.detail` keeps
    ONE home (INV-21). `archive/` would otherwise have to import `store.doc._json_column` -- an
    archive-to-store edge for a column encoding that is the store's own business -- or grow a
    second copy of `canonical()`-then-decode, which is the shape INV-21 exists to forbid.

    `block_id` is filled in here too: an owcheck finding names an `addr` inside its `detail`, not a
    `block_id`, and the column is nullable for exactly that reason.
    """
    bound = {"block_id": None, **row}
    if not isinstance(bound.get("detail"), str):
        # Every other value in the row is already a bindable scalar; `detail` is the only JSON
        # column, so this is a total conversion and not a defensive sweep.
        bound["detail"] = _json_column(bound.get("detail"))
    return bound


def _json_column(value: object) -> str:
    """A JSON column's stored text: `canonical()`'s bytes, decoded.

    Every JSON column in L2 goes through `canonical()` rather than `json.dumps`, so a value that is
    not JSON-canonicalisable is a refusal at the write (I12) instead of a column two readers
    disagree about. `None` stores as `{}`, matching the DDL default of every such column.
    """
    if value is None:
        return "{}"
    return canonical(value).decode("utf-8")  # type: ignore[arg-type]


def _capabilities_dict(caps: Capabilities) -> dict[str, Any]:
    """The fifteen fields as a plain JSON object.

    `math` and `forfeits` are `frozenset`s on the value type and sorted arrays on disk -- a set has
    no order and a byte-diffed JSON column must (03:1177-1180).
    """
    return {
        "spatial": caps.spatial,
        "origin_span": caps.origin_span,
        "text_span": caps.text_span,
        "marks": caps.marks,
        "reading_order": caps.reading_order,
        "sections": caps.sections,
        "tables": caps.tables,
        "math": sorted(caps.math),
        "assets": caps.assets,
        "asset_origin": caps.asset_origin,
        "notes": caps.notes,
        "confidence": caps.confidence,
        "furniture": caps.furniture,
        "round_trip": caps.round_trip,
        "forfeits": sorted(caps.forfeits),
    }


def _origin_columns(origin: OriginSpan) -> tuple[OsKind, dict[str, Any]]:
    """The seven `os_*` columns for one `OriginSpan`. 03:1428-1436's mapping table, row for row.

    `os_b` is a LENGTH at every site -- the column, the wire's `os.len` and `OriginBytes.length` --
    and never an end offset (03:1471-1473). `OriginNone()` is a value, not a null: `os_kind` is
    `NOT NULL` and the union is nullable only as a whole (03:1466).
    """
    columns: dict[str, Any] = {
        "os_part": None,
        "os_a": None,
        "os_b": None,
        "os_path": None,
        "os_extractor": None,
        "os_codec": None,
    }
    if isinstance(origin, OriginBytes):
        kind = OsKind.BYTES
        columns["os_part"] = origin.part
        columns["os_a"] = origin.start
        columns["os_b"] = origin.length
        columns["os_codec"] = origin.codec
    elif isinstance(origin, OriginNodePath):
        kind = OsKind.NODEPATH
        columns["os_part"] = origin.part
        columns["os_path"] = ".".join(str(step) for step in origin.path)
    elif isinstance(origin, OriginGlyphs):
        kind = OsKind.GLYPHS
        columns["os_part"] = origin.part
        columns["os_a"] = origin.start
        columns["os_b"] = origin.length
        columns["os_extractor"] = origin.extractor
    elif isinstance(origin, OriginPixels):
        kind = OsKind.PIXELS
    else:
        kind = OsKind.NONE
    columns["os_kind"] = _ordinal("origin_span_kind", kind)
    return kind, columns


def _refuse(symbol: str, message: str, *, fix: str = _FIX_VERIFY) -> ModelError:
    """A `ModelError` carrying a `codes.toml` symbol and the exact command that clears it."""
    return ModelError(message, symbol=symbol, fix=fix)


def _mean(values: Sequence[float]) -> float | None:
    """The mean of the non-NULL values, or `None` when there are none. 03:1782-1788.

    *"A component with `n_scored == 0` is `null`, not `0.0`, and is excluded from any aggregate
    grade"* -- the corrected form of docling's `nanmean` over an all-NaN list.
    """
    return sum(values) / len(values) if values else None


_LADDERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        name: get_args(hint)
        for name, hint in get_type_hints(Capabilities).items()
        if get_origin(hint) is Literal
    }
)
"""The ten ordered capability ladders, READ OFF `Capabilities`' own annotations.

`model/block.py`'s docstring already fixes that type as the home -- "the ten ordered ladders below
are `card.PARSE_LADDERS` and `test_model_block.py` asserts the two agree member for member and in
order" -- so deriving them from `get_type_hints(Capabilities)` uses the home rather than adding a
third transcription beside it and `drivers/card.py`. It also keeps `store` from importing
`drivers`, which nothing in `tools/layers.toml` forbids and nothing in the plan asks for.

`achieved` "may be lower, never higher" than `declared` (03:527), and these tuples are what
"lower" means for the ten `Literal` fields; the three booleans compare `False < True` and the two
sets compare by containment.
"""


def _clamp_ladder(field_name: str, computed: str, declared: str) -> str:
    """`min(computed, declared)` on one ordered ladder. 03:527 -- never higher than declared."""
    rungs = _LADDERS[field_name]
    return computed if rungs.index(computed) <= rungs.index(declared) else declared


# ---------------------------------------------------------------------------
# 2. The resident state. Four small records; none of them is a public type.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Minted:
    """What a minted block has to remember so a LATER block can be addressed against it.

    Five facts and a counter, because that is the whole of what `addr`, `ord` and M-INV-5 read
    from a parent: 03:1098-1106's three rules build a child's address from its parent's, 03:239
    makes `ord` "position among siblings ... dense from 0", and 03:1027 makes `layer` the parent's
    unless the block is a page root.

    **This map spans the document, not the page, and 03 section 12.3 is why.** A table crossing a
    page break is ONE `table` block at the FIRST page whose cells carry their own `page`, so a
    block minted on page 3 is a legitimate `parent` for a block minted on page 4. A per-page map
    would make the framework's own worked multi-page case unrepresentable. The cost is one small
    slotted record per block for the life of one document -- the same order as the `tmp`-id map the
    fragment decoder holds anyway (03:47-52) -- and it is bounded by `MAX_BLOCKS_PER_DOC`, which
    `add_block` charges against.
    """

    kind: Kind
    layer: Layer
    page: int
    addr: Addr
    depth: int
    next_child_ord: int = 0


@dataclass(slots=True)
class _Pending:
    """One block staged for the open page's transaction, with its digest not yet computed.

    The digest is deferred to `end_page` on purpose. `content_digest` is a merkle over children in
    `ord` order (03:1194-1200) and M-INV-1 writes a parent BEFORE its children, so a digest taken
    at `add_block` time would be provisional for every container -- including the overwhelming
    majority whose whole subtree lands on this very page. Deferring to the moment the page closes
    finalises all of those, and leaves exactly 03:1226-1230's set for the closure pass: the blocks
    "whose `max(descendant.page)` exceeds their own page".

    `children` is filled in arrival order, which IS `ord` order because `add_block` assigns `ord`
    from the parent's counter as each child arrives.
    """

    block_id: BlockId
    columns: dict[str, Any]
    kind_ord: int
    layer_ord: int
    text: str | None
    payload: Mapping[str, Any] | None
    page: int
    quad: Quad | None
    children: list[BlockId] = field(default_factory=list)


@dataclass(slots=True)
class _DocState:
    """Everything `begin_doc` resolved, and the counters the document advances.

    `g_t = gen + 1` is fixed once, at `begin_doc` (03:56-57), and never re-read: a second read
    could see a `doc.gen` some other writer moved, and the whole staging mechanism is that every
    row of this parse carries one generation number.
    """

    record: DocRecord
    doc_ord: int
    head_gen: int
    target_gen: int
    next_cite_n: int
    next_block_seq: int
    next_asset_id: int
    declared: Capabilities
    assets: dict[tuple[bytes, str], int]
    between_pages: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


@dataclass(slots=True)
class _PageState:
    """The open page: its row, its buffers and the two ordinal counters 03:1106 resets here."""

    record: PageRecord
    page_root_ord: int = 0
    blocks: list[_Pending] = field(default_factory=list)
    satellites: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. `DocSink` -- the eleven methods.
# ---------------------------------------------------------------------------


class DocSink:
    """The L2 write boundary, implemented over `StoreThread`. Eleven methods, and no twelfth.

    Satisfies `omniweave_core.store.DocSink`, the frozen Protocol, and carries the same name
    because `01-principles.md:838` spells this class
    `omniweave_core.store.doc.DocSink.add_block`. **Eleven is fixed** (03:568-572):
    "`BlockDraft.cell` exists precisely so a cell's grid position can reach `add_block` without a
    twelfth method. A
    twelfth re-prices 07 section 1.2's T3 Postgres swap ... so adding one is an ADR, not a patch."
    Every helper below is `_`-prefixed for exactly that reason, and `test_store_doc.py` counts the
    public surface.

    **HOST-SIDE. Never handed to a driver** (charter section 5 X1, 03:548-551). A `parse/1` driver
    emits `owdoc-fragment/1` addressing blocks by a per-invocation `tmp` id; the host decodes it and
    drives this. That is what makes INV-6 and INV-7 structural rather than reviewed.

    **What the constructor takes, and why each is a parameter rather than a read.**

    * `thread` -- the one `Connection` holder (INV-17, 07:2722). This class never connects.
    * `producer_id` -- the runner resolved the `producer` row before the parse ran; `Producer` IS
      L5's `OperatorIdentity` (03:396) and minting it is not one of the eleven.
    * `origin_operator` / `origin_driver` / `driver_schema_v` -- D3's three ownership columns,
      stamped on every block and every rel (03:302-304). `origin_operator` is also the second input
      to `_clamp_quote`: a `derive.*` block quotes nothing by inheritance (03:1684).
    * `restriction_bits` -- "stamped from the producing card, propagating to every derived item"
      (INV-16, 03:305).
    * `blobs` -- the CAS. `add_asset` and a retained `add_part` stream through it and this module
      writes no file itself (03:2131-2135).
    * `score_kinds` -- the `tools/scorekinds.toml` register, absent from the tree; see the module
      docstring. Empty means "no register", so every `score_kind` is unregistered and raises.
    * `shard_ord` -- 03:1058's `block_id := (shard_ord << 48) | sequence`; `0` at a single store.
    * `rebind_threshold` / `allow_unexplained` -- 03:1300's quarantine and its ONLY override.
      There is no `--force` anywhere in the framework (03:1302), and there is no `force` here.
    """

    __slots__ = (
        "_allow_unexplained",
        "_blobs",
        "_cost_class",
        "_decision_id",
        "_doc",
        "_driver_schema_v",
        "_ended",
        "_marked",
        "_minted",
        "_origin_driver",
        "_origin_operator",
        "_page",
        "_pages_written",
        "_producer_id",
        "_rebind_threshold",
        "_restriction_bits",
        "_root_id",
        "_score_kinds",
        "_shard_ord",
        "_table_cells",
        "_tabled",
        "_thread",
        "_wait_ms",
    )

    def __init__(
        self,
        thread: StoreThread,
        *,
        producer_id: int,
        origin_operator: str,
        origin_driver: str,
        driver_schema_v: int,
        blobs: BlobStore | None = None,
        score_kinds: frozenset[str] = frozenset(),
        restriction_bits: int = 0,
        decision_id: str | None = None,
        shard_ord: int = 0,
        cost_class: str = "local_compute",
        wait_ms: int = BATCH_WAIT_MS,
        rebind_threshold: float = DEFAULT_THRESHOLD,
        allow_unexplained: bool = False,
    ) -> None:
        if not 0 <= shard_ord <= _MAX_SHARD_ORD:
            msg = (
                f"shard_ord {shard_ord} is outside 0..{_MAX_SHARD_ORD}: `block_id` is a SIGNED "
                f"64-bit value, so the top bit of the shard field must be zero (03:1060-1062)"
            )
            raise ValueError(msg)
        self._thread = thread
        self._producer_id = producer_id
        self._origin_operator = origin_operator
        self._origin_driver = origin_driver
        self._driver_schema_v = driver_schema_v
        self._blobs = blobs
        self._score_kinds = score_kinds
        self._restriction_bits = restriction_bits
        self._decision_id = decision_id
        self._shard_ord = shard_ord
        self._cost_class = cost_class
        self._wait_ms = wait_ms
        self._rebind_threshold = rebind_threshold
        self._allow_unexplained = allow_unexplained
        self._doc: _DocState | None = None
        self._page: _PageState | None = None
        self._minted: dict[BlockId, _Minted] = {}
        self._marked: set[BlockId] = set()
        self._tabled: set[BlockId] = set()
        self._table_cells: dict[BlockId, list[tuple[int, int]]] = {}
        self._root_id: BlockId | None = None
        self._pages_written = 0
        self._ended = False

    # -- 1/11 ---------------------------------------------------------------------------------

    def begin_doc(self, rec: DocRecord) -> DocRecord:
        """Insert or look up `doc` by `doc_key`; assign `doc_ord`; fix `g_t`; copy `declared`.

        03:576 is the row and 03:56-57 the step. Returns the RESOLVED record -- `doc_ord` assigned,
        `gen = g_t` -- which is 03:610-614's stated divergence from the charter's `-> None`: "§1.1
        makes `begin_doc` the step that assigns `doc_ord` and fixes `g_t`, and `DocRecord` is
        frozen, so a caller's record cannot carry either value on first sight."

        **A first-sight document is written at `gen = 0`,** because "gen = 0 is reserved and means
        'no committed generation'" (03:82) -- so `g_t` is 1 and the row has no visible blocks until
        `end_doc` commits. The DDL's `DEFAULT 1` is vestigial and this statement is explicit.

        **`status`, `achieved` and `confidence` are NOT refreshed on a re-parse.** They describe
        the committed head, and overwriting them here would make a re-parse that later quarantines
        publish the new parse's verdict against the old generation's rows. `end_doc` writes all
        three, once, in the transaction that makes the generation visible.
        """
        if self._doc is not None:
            raise _refuse("OW_MODEL", "begin_doc is called once, first (03:576)", fix=_FIX_REPARSE)
        state = self._thread.run(
            Unit(
                name="doc.begin_doc",
                run=lambda connection: self._begin_doc(connection, rec),
                cost_class=self._cost_class,
                wait_ms=self._wait_ms,
            )
        )
        assert isinstance(state, _DocState)  # noqa: S101 -- the closure's own return type.
        self._doc = state
        return state.record

    # -- 2/11 ---------------------------------------------------------------------------------

    def begin_page(self, page: PageRecord) -> None:
        """Buffer the `page` row at `(doc_ord, g_t, page)` and reset the page-root counter.

        03:577. The row is buffered rather than written because `end_page` "commits ONE
        transaction" (03:594) and a page row written in its own transaction would be a second one.

        Two rules of 03 section 12.5 are enforced here rather than left to a comment:
        `w_mpt`/`h_mpt` "are NULL exactly when `page_kind == STREAM`" (03:470), and `page` is the
        ORIGINAL source index and never a batch index (03:2281) -- which this cannot check, so it
        checks the half it can, that the index is non-negative and unique within the generation.
        """
        doc = self._require_doc()
        if self._page is not None:
            raise _refuse(
                "OW_MODEL",
                f"page {self._page.record.page} is still open; end_page commits it (03:594)",
                fix=_FIX_REPARSE,
            )
        if page.page < 0:
            msg = f"page {page.page} is negative; `page` is the original 0-based index (03:2271)"
            raise _refuse("OW_MODEL", msg)
        streaming = page.page_kind is PageKind.STREAM
        sized = page.w_mpt is not None or page.h_mpt is not None
        if streaming and sized:
            msg = (
                f"page_kind='stream' carries no page box, but page {page.page} states one (03:470)"
            )
            raise _refuse("OW_MODEL", msg)
        if page.quad_origin is not None and page.quad_origin not in QUAD_ORIGINS:
            msg = f"quad_origin {page.quad_origin!r} is not topleft|bottomleft (03:2225 DDL CHECK)"
            raise _refuse("OW_MODEL", msg)
        if page.status not in DOC_STATUSES:
            msg = f"page status {page.status!r} is not one of {sorted(DOC_STATUSES)}"
            raise _refuse("OW_MODEL", msg)
        _ = doc
        self._page = _PageState(record=page)

    # -- 3/11 ---------------------------------------------------------------------------------

    def add_block(self, b: BlockDraft) -> BlockId:
        """Mint the block and stage its row. 03:578 is the cell and it is worked through in order.

        Mints `block_id` (03:1058), `addr` (03 section 6.2's three rules), `cite` from
        `doc.next_cite_n` (03:1146) and `ord` (03:239). Stamps `producer_id`, `origin_operator`,
        `origin_driver`, `driver_schema_v` and `restriction_bits` -- none of which a driver may
        write (INV-6, INV-7). Applies `MAX_TRUST_BY_METHOD` (03:1616-1622) and
        `MAX_QUOTE_BY_OS_KIND` (03:1673-1686), each a CEILING and never a floor, each recording the
        driver's ORIGINAL claim in a `Diag` so over-claiming is measurable rather than silently
        corrected. Validates the kind's `payload` (03 section 4.4), the `score_kind` register
        (03:295), `layer` inheritance (M-INV-5) and the `cell`/`table_cell` pair (03:334).

        The digest is NOT computed here; `_Pending` says why.

        Returns the `block_id`, which is what makes `BlockDraft.cell` sufficient and a twelfth
        method unnecessary: `build_grid` consumes `CellDraft(id, pos)` and the id comes from here.
        """
        doc = self._require_doc()
        page = self._require_page()
        if len(self._minted) >= MAX_BLOCKS_PER_DOC:
            msg = f"this document already holds {len(self._minted)} blocks"
            raise ResourceLimit(msg, limit="MAX_BLOCKS_PER_DOC", fix=_FIX_VERIFY)
        if len(page.blocks) >= MAX_BLOCKS_PER_PAGE:
            msg = f"page {page.record.page} already holds {len(page.blocks)} blocks"
            raise ResourceLimit(msg, limit="MAX_BLOCKS_PER_PAGE", fix=_FIX_VERIFY)

        parent = self._parent_of(b)
        layer = self._resolved_layer(b, parent)
        addr, ordinal, depth = self._address(b, parent, page)
        text = self._resolved_text(b)
        payload = self._validated_payload(b)
        self._validate_score(b)
        self._validate_x(b.x)
        if b.raw_kind is not None and len(b.raw_kind) > _MAX_RAW_KIND_CHARS:
            msg = f"raw_kind is {len(b.raw_kind)} chars; the CHECK caps it at {_MAX_RAW_KIND_CHARS}"
            raise _refuse("OW_MODEL", msg)

        block_id = self._mint_block_id(doc)
        cite = self._mint_cite(doc)
        os_kind, origin = _origin_columns(b.origin)
        trust = self._clamped_trust(b, block_id)
        quote = self._clamped_quote(b, os_kind, block_id)

        columns: dict[str, Any] = {
            "block_id": int(block_id),
            "doc_ord": doc.doc_ord,
            "gen": doc.target_gen,
            "page": page.record.page,
            "addr": str(addr),
            "cite": str(cite),
            "parent_id": None if b.parent is None else int(b.parent),
            "ord": ordinal,
            "kind": _ordinal("kind", b.kind),
            "raw_kind": b.raw_kind,
            "layer": _ordinal("layer", layer),
            "label": b.label,
            "text": text,
            "revision": 0,
            "quad": _quad_blob(b.quad),
            "ts_a": None if b.span is None else b.span.a,
            "ts_b": None if b.span is None else b.span.b,
            "producer_id": self._producer_id,
            "method": _ordinal("method", b.method),
            "trust": int(trust),
            "score": b.score,
            "score_kind": b.score_kind,
            "quote": int(quote),
            "origin_operator": self._origin_operator,
            "origin_driver": self._origin_driver,
            "driver_schema_v": self._driver_schema_v,
            "restriction_bits": self._restriction_bits,
            "decision_id": self._decision_id,
            "payload": None if payload is None else _json_column(payload),
            "state": 0,
            "x": _json_column(dict(b.x)),
        }
        columns |= origin
        pending = _Pending(
            block_id=block_id,
            columns=columns,
            kind_ord=columns["kind"],
            layer_ord=columns["layer"],
            text=text,
            payload=payload,
            page=page.record.page,
            quad=b.quad,
        )
        page.blocks.append(pending)
        self._minted[block_id] = _Minted(
            kind=b.kind, layer=layer, page=page.record.page, addr=addr, depth=depth
        )
        if parent is not None and b.parent is not None:
            parent.next_child_ord += 1
            self._same_page_parent(b.parent, pending)
        if b.parent is None:
            self._root_id = block_id
        if b.cell is not None and b.parent is not None:
            self._table_cells.setdefault(b.parent, []).append((b.cell.r, b.cell.c))
        if b.marks:
            self.add_marks(block_id, list(b.marks))
        return block_id

    # -- 4/11 ---------------------------------------------------------------------------------

    def add_marks(self, b: BlockId, marks: Sequence[Mark]) -> None:
        """Stage one block's marks. 03:579: surrogates in `(a, b, kind)` order, `0 <= a <= b <= n`.

        At most once per block, which is the cell's own "called" column: two calls would make the
        second an append the plan never describes and would break the `(a, b, kind)` ordering the
        surrogate ids are assigned in. `mark_id` is a SURROGATE because "two links may cover
        exactly the same range" (03:354), so it is left to SQLite's rowid rather than derived.

        A zero-width mark (`a == b`) is legal and meaningful for `anchor` and `note_ref` (03:381).
        """
        self._require_page()
        if b in self._marked:
            msg = f"add_marks is called at most once per block; block {int(b)} has marks (03:579)"
            raise _refuse("OW_MODEL", msg)
        self._marked.add(b)
        if not marks:
            return
        if len(marks) > MAX_MARKS_PER_BLOCK:
            msg = f"block {int(b)} carries {len(marks)} marks"
            raise ResourceLimit(msg, limit="MAX_MARKS_PER_BLOCK", fix=_FIX_VERIFY)
        text = self._text_of(b)
        limit = 0 if text is None else len(text)
        for mark in marks:
            if not 0 <= mark.a <= mark.b <= limit:
                msg = (
                    f"mark ({mark.a}, {mark.b}) on block {int(b)} is outside "
                    f"0 <= a <= b <= len(text) = {limit} (03:379-381)"
                )
                raise _refuse("OW_MODEL", msg)
        page = self._require_page()
        for mark in sorted(marks, key=lambda m: (m.a, m.b, m.kind)):
            page.satellites.append(
                (
                    "INSERT INTO mark(block_id, a, b, kind, value) "
                    "VALUES(:block_id, :a, :b, :kind, :value)",
                    {
                        "block_id": int(b),
                        "a": mark.a,
                        "b": mark.b,
                        "kind": mark.kind,
                        "value": None if mark.value is None else _json_column(mark.value),
                    },
                )
            )

    # -- 5/11 ---------------------------------------------------------------------------------

    def add_grid(self, b: BlockId, g: Grid) -> None:
        """Write `table_meta`, `cell`, and `grid_slot` only when `has_merges`. 03:580.

        Called once per table, **in the transaction of its last page** (03:580, 03:2233): the cells
        of a page-crossing table were minted across several pages and their `block_id`s are already
        committed, so this call joins the page that closes it.

        **Row-major cell arrival is asserted here** and not inside `build_grid`, which buffers an
        out-of-order stream up to `MAX_RESIDENT_CELLS` (03:1937-1939). What `add_grid` can assert
        is the thing 03:1993-1994 makes a property of the STORE -- the origins' `ord` among the
        table's children is "0-9 in that order -- row-major over origins, dense from 0" -- because
        `add_block` assigned those ordinals in arrival order. So a table whose cells reached
        `add_block` out of order has cell `ord`s that are not row-major, and that is refused.

        `MAX_EXPANSION` is charged against the materialised extent, `sum(row_len)`. 03:1946-1948
        sets it "equal to `MAX_GRID_SLOTS` ... because a table that can be built and then cannot be
        stored is the worst of both numbers", so one charge covers both.
        """
        self._require_doc()
        page = self._require_page()
        minted = self._minted.get(b)
        if minted is None:
            raise _refuse("OW_MODEL", f"add_grid names block {int(b)}, which was never minted")
        if minted.kind is not Kind.TABLE:
            msg = (
                f"add_grid names a {minted.kind.value} block; a grid belongs to a `table` (03:580)"
            )
            raise _refuse("OW_MODEL", msg)
        if b in self._tabled:
            raise _refuse("OW_MODEL", f"add_grid is called once per table; block {int(b)} is done")
        self._tabled.add(b)

        arrivals = self._table_cells.get(b, [])
        for earlier, later in pairwise(arrivals):
            if later <= earlier:
                msg = (
                    f"cells of table {int(b)} arrived at r{earlier[0]}c{earlier[1]} then "
                    f"r{later[0]}c{later[1]}: 03:1937 requires row-major origin order"
                )
                raise _refuse("OW_MODEL", msg)
        extent = sum(g.row_len)
        if extent > MAX_EXPANSION:
            msg = f"table {int(b)} declares {extent} logical positions"
            raise ResourceLimit(msg, limit="MAX_EXPANSION", fix=_FIX_VERIFY)
        arrived = set(arrivals)
        declared_cells = {(origin.r, origin.c) for origin in g.cells()}
        if arrived != declared_cells:
            msg = (
                f"table {int(b)}: {len(arrived)} cells reached add_block and the Grid holds "
                f"{len(declared_cells)} origins; the two must be the same set (03:1950)"
            )
            raise _refuse("OW_MODEL", msg)

        page.satellites.append(
            (
                "INSERT INTO table_meta(block_id, n_rows, n_cols, row_len, header_rows, "
                "header_cols, kind, recon_strategy, recon_score, has_merges, native_part, "
                "native_sha256) VALUES(:block_id, :n_rows, :n_cols, :row_len, :header_rows, "
                ":header_cols, :kind, :recon_strategy, :recon_score, :has_merges, :native_part, "
                ":native_sha256)",
                {
                    "block_id": int(b),
                    "n_rows": g.n_rows,
                    "n_cols": g.n_cols,
                    "row_len": _json_column(list(g.row_len)),
                    "header_rows": g.header_rows,
                    "header_cols": g.header_cols,
                    "kind": _ordinal("table_kind", TableKind(g.kind)),
                    "recon_strategy": None if g.recon is None else g.recon[0],
                    "recon_score": None if g.recon is None else g.recon[1],
                    "has_merges": int(g.has_merges),
                    "native_part": None if g.native is None else g.native[0],
                    "native_sha256": None if g.native is None else g.native[1],
                },
            )
        )
        for origin in g.cells():
            page.satellites.append(
                (
                    "INSERT INTO cell(block_id, table_id, r, c, row_span, col_span) "
                    "VALUES(:block_id, :table_id, :r, :c, :row_span, :col_span)",
                    {
                        "block_id": int(origin.block),
                        "table_id": int(b),
                        "r": origin.r,
                        "c": origin.c,
                        "row_span": origin.row_span,
                        "col_span": origin.col_span,
                    },
                )
            )
        for r, c, origin_id in g.grid_slots():
            page.satellites.append(
                (
                    "INSERT INTO grid_slot(table_id, r, c, origin_id) "
                    "VALUES(:table_id, :r, :c, :origin_id)",
                    {"table_id": int(b), "r": r, "c": c, "origin_id": int(origin_id)},
                )
            )

    # -- 6/11 ---------------------------------------------------------------------------------

    def add_rel(
        self,
        src: BlockId,
        dst: BlockId,
        kind: RelKind,
        *,
        trust: Trust,
        score: float | None = None,
        score_kind: str | None = None,
    ) -> None:
        """Stage one edge of the closed intra-document DAG. 03:585.

        Stamps `producer_id` and `origin_operator`, clamps `trust`, rejects anything outside the
        closed seven-member `RelKind`, and relies on `UNIQUE (src_id, dst_id, kind, producer_id)`
        for identity IN THE SCHEMA rather than a read-then-write.

        **`score_kind` is here because `Rel` carries it and the column exists** (03:615-618): "a
        signature with only `score` leaves `rel.score_kind` unwritable and a scored `rel`
        unresolvable against `tools/scorekinds.toml`". The two are nullable together, the same rule
        `Block` obeys.

        **The trust ceiling is the CURRENT PAGE's `method`.** 03:585 says "clamps `trust`" and
        names no ceiling; a `rel` has no `method` column, and `MAX_TRUST_BY_METHOD` is the only
        trust ceiling the framework has (03:1616). The page's method is "the branch that ran on
        THAT page" (03:466), which is the branch that produced this edge, so it is the ceiling that
        is in scope and it can only lower. Recorded here because the plan states the clamp without
        stating its ceiling.
        """
        doc = self._require_doc()
        page = self._require_page()
        if not isinstance(kind, RelKind):
            msg = f"rel kind {kind!r} is outside the closed seven-member RelKind (03:585)"
            raise _refuse("OW_MODEL", msg)
        for end, name in ((src, "src"), (dst, "dst")):
            if end not in self._minted:
                raise _refuse("OW_MODEL", f"rel {name} block {int(end)} was never minted")
        if (score is None) != (score_kind is None):
            msg = f"rel score/score_kind are nullable TOGETHER, got ({score!r}, {score_kind!r})"
            raise _refuse("OW_MODEL", msg)
        if score_kind is not None and score_kind not in self._score_kinds:
            raise _refuse(SCORE_KIND_UNREGISTERED, self._unregistered(score_kind))
        ceiling = MAX_TRUST_BY_METHOD[page.record.method]
        page.satellites.append(
            (
                "INSERT OR IGNORE INTO rel(doc_ord, gen, src_id, dst_id, kind, producer_id, "
                "trust, score, score_kind, origin_operator, x) "
                "VALUES(:doc_ord, :gen, :src_id, :dst_id, :kind, :producer_id, :trust, :score, "
                ":score_kind, :origin_operator, '{}')",
                {
                    "doc_ord": doc.doc_ord,
                    "gen": doc.target_gen,
                    "src_id": int(src),
                    "dst_id": int(dst),
                    "kind": _ordinal("rel_kind", kind),
                    "producer_id": self._producer_id,
                    "trust": int(min(trust, ceiling)),
                    "score": score,
                    "score_kind": score_kind,
                    "origin_operator": self._origin_operator,
                },
            )
        )

    # -- 7/11 ---------------------------------------------------------------------------------

    def add_asset(self, a: AssetDraft, blob: BinaryIO) -> int:
        """Stream the bytes into CAS, hash them, and stage the `asset` row. 03:589.

        **The digest the driver claims is not the digest we store** (03:2137-2140).
        `AssetDraft.sha256` is a claim; this hashes the stream itself through `BlobStore.put`
        and compares. A
        disagreement raises `OW_ASSET_DIGEST_MISMATCH` and the asset is rejected -- "a
        content-addressed store with an unverified writer is a substitution oracle".

        Dedup is on `(doc_ord, sha256, IFNULL(origin_part, ''))`, the `asset_identity` unique index
        (03:2088). The `IFNULL('')` sentinel is mandatory: SQL NULLs are each distinct, so a
        nullable natural key makes `INSERT OR IGNORE` degenerate into a plain INSERT. Two blocks
        referencing the same logo therefore produce ONE row, and the identity map for this
        `doc_ord` was loaded at `begin_doc` so a repeat is resolved without a read.

        **The bytes reach CAS before the row is staged, and that ordering is deliberate.** A CAS
        object with no row is swept by `ow store gc`; a row with no object is a dangling
        `store_ref`. The cheap failure is the one that happens.

        `block_asset` is not written here; the module docstring records why.
        """
        doc = self._require_doc()
        self._require_page()
        if self._blobs is None:
            msg = "add_asset streams into the CAS and this sink was built without a BlobStore"
            raise _refuse("OW_MODEL", msg, fix="ow store init")
        digest = self._blobs.put(blob)
        if digest != a.sha256:
            msg = (
                f"the driver claimed sha256 {a.sha256.hex()} and the stream hashed to "
                f"{digest.hex()}; the asset is rejected (03:2137-2140)"
            )
            raise _refuse(ASSET_DIGEST_MISMATCH, msg)
        key = (digest, a.origin_part or "")
        existing = doc.assets.get(key)
        if existing is not None:
            return existing
        asset_id = doc.next_asset_id
        doc.next_asset_id += 1
        doc.assets[key] = asset_id
        self._require_page().satellites.append(
            (
                "INSERT INTO asset(asset_id, doc_ord, media_type, origin_part, sha256, byte_len, "
                "width, height, store_ref, licence, licence_url, spdx, source_url, "
                "retrieved_at_ns, restriction_bits) VALUES(:asset_id, :doc_ord, :media_type, "
                ":origin_part, :sha256, :byte_len, :width, :height, :store_ref, :licence, "
                ":licence_url, :spdx, :source_url, :retrieved_at_ns, :restriction_bits)",
                {
                    "asset_id": asset_id,
                    "doc_ord": doc.doc_ord,
                    "media_type": a.media_type,
                    "origin_part": a.origin_part,
                    "sha256": digest,
                    "byte_len": a.byte_len,
                    "width": a.width,
                    "height": a.height,
                    "store_ref": self._blobs.ref(digest),
                    "licence": a.licence,
                    "licence_url": a.licence_url,
                    "spdx": a.spdx,
                    "source_url": a.source_url,
                    "retrieved_at_ns": a.retrieved_at_ns,
                    "restriction_bits": self._restriction_bits,
                },
            )
        )
        return asset_id

    # -- 8/11 ---------------------------------------------------------------------------------

    def add_part(self, path: str, blob: BinaryIO | None, sha256: bytes, byte_len: int) -> None:
        """The sole inserter of an L2 `part` row. 03:591, and 03:599-609 argues it three ways.

        `op.identify` writes `unit.part_count` and the per-part `work` rows and NEVER a `part` row;
        erratum E53 retires charter D6's overloaded phrase. Three facts force it, in ascending
        finality: `part.sha256`/`byte_len` are `NOT NULL` and `op.identify` reads no bytes;
        `part.doc_ord` references `doc(doc_ord)`, which `begin_doc` assigns and `op.identify` runs
        before; and L2 has one writer.

        **`blob` is nullable and that nullability IS the retention policy in the signature**
        (03:611-619). `[store] retain_parts` decides whether the bytes reach CAS; `blob = None`
        records the `path`, `sha256` and `byte_len` with `store_ref` NULL, which is exactly what
        the DDL's "NULL => bytes were not retained" means. The digest and the length are required
        either way, so INV-10's `glyphs` branch and `VERBATIM`'s re-verification can name WHICH
        part they could not read instead of failing without an explanation.

        The row is an UPSERT on `(doc_ord, path)`, its primary key. `part` is keyed on the document
        and NOT on the generation -- like `asset`, and for the same reason (03:2102): a part's
        identity is its bytes, and a re-parse of the same container names the same paths.
        """
        doc = self._require_doc()
        page = self._require_page()
        store_ref: str | None = None
        if blob is not None:
            if self._blobs is None:
                msg = "a retained part streams into the CAS and this sink has no BlobStore"
                raise _refuse("OW_MODEL", msg, fix="ow store init")
            digest = self._blobs.put(blob)
            if digest != sha256:
                msg = (
                    f"part {path!r} was declared sha256 {sha256.hex()} and hashed to "
                    f"{digest.hex()}; the same substitution-oracle rule as `add_asset` applies"
                )
                raise _refuse(ASSET_DIGEST_MISMATCH, msg)
            store_ref = self._blobs.ref(digest)
        page.satellites.append(
            (
                "INSERT INTO part(doc_ord, path, sha256, byte_len, store_ref) "
                "VALUES(:doc_ord, :path, :sha256, :byte_len, :store_ref) "
                "ON CONFLICT(doc_ord, path) DO UPDATE SET sha256 = excluded.sha256, "
                "byte_len = excluded.byte_len, store_ref = excluded.store_ref",
                {
                    "doc_ord": doc.doc_ord,
                    "path": path,
                    "sha256": sha256,
                    "byte_len": byte_len,
                    "store_ref": store_ref,
                },
            )
        )

    # -- 9/11 ---------------------------------------------------------------------------------

    def diag(self, d: Diag) -> None:
        """Record a diagnostic inside the CURRENT page's transaction. 03:593.

        "so a diagnostic about page 3,000 survives a crash at page 3,001". It is staged like every
        other row of the page, which means it is also invisible until the `doc.gen` bump and swept
        with the generation if the parse is abandoned (03:1810-1812).

        The method is spelled `diag`, not `add_diag` -- "the charter's spelling and section 1.1's,
        kept because one concept gets one name in every document" (03:571). `d.code` holds the
        SYMBOL from `codes.toml`, never the numeric (03:1806-1808), and `diag.block_id` is
        deliberately not a foreign key: "a diagnostic often concerns a block the parse then refused
        to write" (03:1813-1815).

        A diagnostic raised between two pages -- after `end_page` and before the next `begin_page`,
        or before the first page -- lands in the NEXT transaction to commit, which is the next
        `end_page` or `end_doc`. There is no third place for it to go, and dropping it would lose
        the one record of a failure that happened between pages.
        """
        self._require_doc()
        self._pending_rows().append(self._diag_row(d))

    # -- 10/11 --------------------------------------------------------------------------------

    def end_page(self, stats: Mapping[str, Any]) -> None:
        """**Commit one transaction.** 03:594. Rows are durable and invisible while `g_t > doc.gen`.

        One `Unit`, so the claim is structural: the `page` row, every `block` of the page with its
        digest now final for every subtree that closed here, every satellite, every `diag`, and the
        `doc.next_cite_n` high-water mark land together or not at all. A crash between two calls
        leaves page N durable and page N+1 absent, and both invisible.

        `stats` is merged over `PageRecord.stats`, so a caller can hand `begin_page` what it knew
        then and `end_page` what it measured.
        """
        doc = self._require_doc()
        page = self._require_page()
        self._finalise_digests(page)
        rows = self._page_statements(doc, page, stats)
        self._page = None
        self._pages_written += 1
        self._thread.run(
            Unit(
                name=f"doc.end_page[{page.record.page}]",
                run=lambda connection: _execute(connection, rows),
                cost_class=self._cost_class,
                wait_ms=self._wait_ms,
            )
        )

    # -- 11/11 --------------------------------------------------------------------------------

    def end_doc(self, status: str) -> DocRecord:
        """The closure pass, `owcheck`, `rebind`, `achieved`, and iff not quarantined the bump.

        03:596 and 03:66-72, in that order and in ONE transaction:

        1. **the closure pass** (03:1226-1234) finalises the `content_digest` of every container
           whose subtree closes on a later page than its own -- in practice the `document` root and
           the handful of page-crossing containers -- bottom-up, so a parent sees its children's
           final digests;
        2. **`owcheck`** runs the six structural clauses over `g_t` and its violations become
           `diag` rows. A FAILED clause quarantines: step 4 is gated on "iff not quarantined" and a
           generation whose parent/`ord` bijection is broken must never commit
           (`archive/owcheck.py`'s own words);
        3. **`rebind(store, doc_ord, g_t)`** reconciles identity against `g_h` (03 section 6.5) and,
           when it does not quarantine, performs the `doc.gen` bump itself -- that single statement
           IS the commit, which is why `model/rebind.py` owns it and this method does not repeat it;
        4. `achieved` and `doc.confidence` are computed from the COMMITTED rows and written with
           `status`.

        Returns the post-commit `DocRecord`: `gen` is the committed head, so a quarantined
        generation returns the OLD head and `doc.gen` has not moved. The staged rows stay durable,
        invisible and inspectable by `ow doc diff` (03:1298-1302), and the refusal is recorded as
        `OW_REBIND_UNEXPLAINED` rather than raised here, because `rebind()` returns its report and
        "the raise belongs to `end_doc()`'s caller" (`model/rebind.py`).
        """
        doc = self._require_doc()
        if self._page is not None:
            msg = f"page {self._page.record.page} is still open; end_doc is called last (03:596)"
            raise _refuse("OW_MODEL", msg, fix=_FIX_REPARSE)
        if self._ended:
            raise _refuse("OW_MODEL", "end_doc is called once, last (03:596)", fix=_FIX_REPARSE)
        if status not in DOC_STATUSES:
            msg = f"doc status {status!r} is not one of {sorted(DOC_STATUSES)} (the DDL CHECK)"
            raise _refuse("OW_MODEL", msg)
        self._ended = True
        pending = self._pending_rows()
        record = self._thread.run(
            Unit(
                name="doc.end_doc",
                run=lambda connection: self._end_doc(connection, doc, status, pending),
                cost_class=self._cost_class,
                wait_ms=self._wait_ms,
            )
        )
        assert isinstance(record, DocRecord)  # noqa: S101 -- the closure's own return type.
        return record

    # -- everything below is private, because eleven is fixed (03:568) -------------------------

    def _require_doc(self) -> _DocState:
        if self._doc is None:
            raise _refuse("OW_MODEL", "begin_doc runs first (03:56)", fix=_FIX_REPARSE)
        return self._doc

    def _require_page(self) -> _PageState:
        if self._page is None:
            msg = "no page is open; every L2 row is staged inside a page transaction (03:594)"
            raise _refuse("OW_MODEL", msg, fix=_FIX_REPARSE)
        return self._page

    def _pending_rows(self) -> list[tuple[str, dict[str, Any]]]:
        """Where a `diag` row waits: the buffer the NEXT transaction to commit will flush.

        One buffer and not two, and the single branch is deliberate. A diagnostic raised inside a
        page and one raised between two pages have the same destination -- the next `end_page`, or
        `end_doc` when there is no next page -- because 03:593 puts a `diag` "inside the CURRENT
        page's transaction" and there is no other transaction for a between-pages one to join.
        A second, page-local buffer would have been a branch no behaviour could tell apart: it was
        written, and the mutation that collapsed it survived every test, which is what a redundant
        branch always does. `_page_statements` flushes this one before the page's satellites.
        """
        return self._require_doc().between_pages

    def _unregistered(self, kind: str) -> str:
        known = ", ".join(sorted(self._score_kinds)) or "<the register is empty>"
        return (
            f"score_kind {kind!r} is not in the register (known: {known}). "
            f"'0.7 on an unnamed scale is not a measurement' (03:1713-1717); "
            f"tools/scorekinds.toml is where the scale is named"
        )

    # -- begin_doc ----------------------------------------------------------------------------

    def _begin_doc(self, connection: sqlite3.Connection, rec: DocRecord) -> _DocState:
        """The `doc` insert-or-lookup, and the three high-water marks the document then advances."""
        row = connection.execute(
            "SELECT doc_ord, gen, next_cite_n FROM doc WHERE doc_key = ?", (bytes(rec.doc_key),)
        ).fetchone()
        facts = {
            "source_sha256": bytes(rec.source_sha256),
            "normalizer": rec.normalizer,
            "uri": rec.uri,
            "media_type": rec.media_type,
            "format": rec.format,
            "format_evidence": _json_column(dict(rec.format_evidence)),
            "source_bytes": rec.source_bytes,
            "model_version": rec.model_version,
            "declared": _json_column(_capabilities_dict(rec.declared)),
            "x": _json_column(dict(rec.x)),
        }
        if row is None:
            cursor = connection.execute(
                "INSERT INTO doc(doc_key, source_sha256, normalizer, uri, media_type, format, "
                "format_evidence, source_bytes, gen, next_cite_n, status, page_count, "
                "model_version, declared, achieved, confidence, timings_ms, x) "
                "VALUES(:doc_key, :source_sha256, :normalizer, :uri, :media_type, :format, "
                ":format_evidence, :source_bytes, 0, 1, :status, :page_count, :model_version, "
                ":declared, :achieved, '{}', '{}', :x)",
                facts
                | {
                    "doc_key": bytes(rec.doc_key),
                    "status": rec.status,
                    "page_count": rec.page_count,
                    "achieved": _json_column(_capabilities_dict(rec.achieved)),
                },
            )
            doc_ord = int(cursor.lastrowid or 0)
            head_gen = 0
            next_cite_n = 1
        else:
            doc_ord, head_gen, next_cite_n = int(row[0]), int(row[1]), int(row[2])
            connection.execute(
                "UPDATE doc SET source_sha256 = :source_sha256, normalizer = :normalizer, "
                "uri = :uri, media_type = :media_type, format = :format, "
                "format_evidence = :format_evidence, source_bytes = :source_bytes, "
                "model_version = :model_version, declared = :declared, x = :x "
                "WHERE doc_ord = :doc_ord",
                facts | {"doc_ord": doc_ord},
            )
        prefix = self._shard_ord << _SEQUENCE_BITS
        top = connection.execute(
            "SELECT MAX(block_id) FROM block WHERE (block_id >> ?) = ?",
            (_SEQUENCE_BITS, self._shard_ord),
        ).fetchone()[0]
        next_seq = 1 if top is None else (int(top) - prefix) + 1
        top_asset = connection.execute("SELECT MAX(asset_id) FROM asset").fetchone()[0]
        assets = {
            (bytes(digest), part): int(asset_id)
            for asset_id, digest, part in connection.execute(
                "SELECT asset_id, sha256, IFNULL(origin_part,'') FROM asset WHERE doc_ord = ?",
                (doc_ord,),
            )
        }
        target = head_gen + 1
        return _DocState(
            record=replace(rec, doc_ord=doc_ord, gen=target),
            doc_ord=doc_ord,
            head_gen=head_gen,
            target_gen=target,
            next_cite_n=next_cite_n,
            next_block_seq=next_seq,
            next_asset_id=1 if top_asset is None else int(top_asset) + 1,
            declared=rec.declared,
            assets=assets,
        )

    # -- add_block's minting and validation ----------------------------------------------------

    def _mint_block_id(self, doc: _DocState) -> BlockId:
        """`block_id := (minting_shard_ord << 48) | sequence` (03:1058-1066).

        Sixteen bits of shard over forty-eight of sequence, and the top bit of the shard field is
        zero because SQLite's `INTEGER` is signed. At a single store `shard_ord = 0`, so ids are
        literally 1, 2, 3 -- zero bytes of overhead and human-readable in a log.
        """
        sequence = doc.next_block_seq
        if sequence >> _SEQUENCE_BITS:
            msg = f"the block sequence reached {sequence}; 2**{_SEQUENCE_BITS} is the ceiling"
            raise ResourceLimit(msg, limit="MAX_BLOCKS_PER_DOC", fix=_FIX_VERIFY)
        doc.next_block_seq += 1
        return BlockId((self._shard_ord << _SEQUENCE_BITS) | sequence)

    def _mint_cite(self, doc: _DocState) -> Cite:
        """`d<doc_ord>#<n>`, `n` from `doc.next_cite_n`. 03:1140-1160.

        The counter is per-`doc_key`, monotonic, never reset and never reused, and it is NOT a
        write-order position within a generation: a gap is correct, because it is a retirement or a
        cite minted for a staged row that `rebind()` then discarded in favour of a carried one. The
        unqualified form is what the column holds; corpus qualification is a surface decision
        (03:1165-1170).
        """
        number = doc.next_cite_n
        doc.next_cite_n += 1
        return Cite(f"d{doc.doc_ord}#{number}")

    def _parent_of(self, b: BlockDraft) -> _Minted | None:
        if b.parent is None:
            return None
        parent = self._minted.get(b.parent)
        if parent is None:
            msg = (
                f"parent {int(b.parent)} was never minted by this sink; M-INV-1 makes a forward "
                f"reference impossible (03:2214-2217)"
            )
            raise _refuse("OW_MODEL", msg)
        return parent

    def _resolved_layer(self, b: BlockDraft, parent: _Minted | None) -> Layer:
        """M-INV-5: inherited, except on a page root where the kind supplies the default.

        03:1027-1031. A page root is "a block whose parent is the `document` root". The default is
        applied only when the driver said `body` -- the mapping's own "everything else" rung -- so
        a driver that states `hidden` on a page header keeps it, which is what makes `Layer.HIDDEN`
        reachable: no kind implies it.
        """
        if parent is None:
            return b.layer
        if b.parent == self._root_id:
            if b.layer is Layer.BODY:
                return _LAYER_BY_PAGE_ROOT_KIND.get(b.kind, Layer.BODY)
            return b.layer
        if b.layer is not parent.layer:
            msg = (
                f"a {b.kind.value} block under a {parent.layer.value} parent names layer "
                f"{b.layer.value}; layer is inherited except on a page root (M-INV-5, 03:1027)"
            )
            raise _refuse(LAYER_NOT_INHERITED, msg)
        return parent.layer

    def _address(
        self, b: BlockDraft, parent: _Minted | None, page: _PageState
    ) -> tuple[Addr, int, int]:
        """03 section 6.2's three rules, and the `cell`/`table_cell` pair 03:334 asserts here.

        1. The `document` root's addr is the literal `doc`.
        2. The page component is the block's page ANCHOR, which falls out of building a child's
           address from its parent's rather than from its own `page`.
        3. The first step is a PAGE-LOCAL page-root ordinal; every later step is a child `ord`,
           except a cell, whose step is `r<r>c<c>`.

        The `ord` a page root receives is NOT its addr step: `block_sib` is
        `UNIQUE(doc_ord, gen, IFNULL(parent_id,-1), ord)` over the whole generation, so the root's
        children are numbered document-globally while their addresses are numbered per page --
        which is exactly 03:1113-1116's "re-parsing page 12 of a 5,000-page document would renumber
        pages 13 through 4,999" argument.
        """
        cell = b.cell
        if cell is not None:
            if b.kind is not Kind.TABLE_CELL:
                msg = f"BlockDraft.cell is set on a {b.kind.value} block; it implies table_cell"
                raise _refuse("OW_MODEL", msg)
            if parent is None or parent.kind is not Kind.TABLE:
                msg = "a cell's parent must be a `table` block (03:334)"
                raise _refuse("OW_MODEL", msg)
        elif b.kind is Kind.TABLE_CELL:
            msg = "a table_cell carries a CellPos: its addr step is r<r>c<c> (03:1105, 03:334)"
            raise _refuse("OW_MODEL", msg)

        if parent is None:
            if b.kind is not Kind.DOCUMENT:
                msg = f"the parentless block is the `document` root, not a {b.kind.value} (03:1096)"
                raise _refuse("OW_MODEL", msg)
            if self._root_id is not None:
                msg = "one `document` root per (doc_ord, gen); this generation already has one"
                raise _refuse("OW_MODEL", msg)
            return Addr("doc"), 0, 1

        if b.parent == self._root_id:
            step = str(page.page_root_ord)
            page.page_root_ord += 1
            addr = Addr(f"p{page.record.page}/{step}")
            depth = 2
        else:
            step = f"r{cell.r}c{cell.c}" if cell is not None else str(parent.next_child_ord)
            addr = Addr(f"{parent.addr}/{step}")
            depth = parent.depth + 1
        if depth > MAX_BLOCK_DEPTH:
            msg = f"addr {addr} is {depth} steps deep"
            raise ResourceLimit(msg, limit="MAX_BLOCK_DEPTH", fix=_FIX_VERIFY)
        if len(addr) > _MAX_ADDR_CHARS:
            msg = f"addr is {len(addr)} chars; the DDL CHECK caps it at {_MAX_ADDR_CHARS}"
            raise _refuse("OW_MODEL", msg)
        return addr, parent.next_child_ord, depth

    def _resolved_text(self, b: BlockDraft) -> str | None:
        """`block.text` is plain, fully resolved and **NFC** (03:288). The host normalises.

        NFC here and not at the driver, for the reason INV-6 gives generally and INV-10 gives
        specifically: `content_digest` hashes `nfc(text)` (03:1194-1200) and `VERBATIM`
        re-verification compares `nfc(...) == block.text` (03:1470-1476), so a column that is
        merely usually NFC makes the proof unrepeatable. `MAX_BLOCK_TEXT_BYTES` is charged against
        the NORMALISED bytes, which is what the column will hold.
        """
        if b.text is None:
            return None
        text = unicodedata.normalize("NFC", b.text)
        size = len(text.encode("utf-8"))
        if size > MAX_BLOCK_TEXT_BYTES:
            msg = f"a block carries {size} bytes of text"
            raise ResourceLimit(msg, limit="MAX_BLOCK_TEXT_BYTES", fix=_FIX_VERIFY)
        return text

    def _validated_payload(self, b: BlockDraft) -> Mapping[str, Any] | None:
        """03 section 4.4's stated rules, plus the two per-kind constraints it prints verbatim.

        *"Every payload is a flat-ish object of scalars, arrays of scalars, and at most one level of
        nested objects, JSON-canonicalisable by contract (an un-canonicalisable value is a startup
        error, I12), and `canonical(payload)` is capped at `MAX_PAYLOAD_BYTES`. Unknown payload keys
        for a known kind are PRESERVED"* (03:998-1005). The generated `$defs/payload.<kind>`
        validator is not in the tree; the module docstring records that and why the other fourteen
        kinds' schemas are not transcribed from a comment block here.
        """
        payload = b.payload
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            msg = f"payload is a JSON OBJECT discriminated by kind, not {type(payload).__name__}"
            raise _refuse(SCHEMA_PAYLOAD_INVALID, msg)
        obj = dict(payload)
        try:
            encoded = canonical(obj)
        except (TypeError, ValueError) as error:
            msg = f"payload for kind {b.kind.value} is not JSON-canonicalisable: {error}"
            raise _refuse(SCHEMA_PAYLOAD_INVALID, msg) from error
        if len(encoded) > MAX_PAYLOAD_BYTES:
            msg = f"canonical(payload) is {len(encoded)} bytes"
            raise ResourceLimit(msg, limit="MAX_PAYLOAD_BYTES", fix=_FIX_VERIFY)
        for key, value in obj.items():
            if isinstance(value, Mapping) and any(
                isinstance(inner, (Mapping, list, tuple)) for inner in value.values()
            ):
                msg = f"payload key {key!r} nests more than one level deep (03:998)"
                raise _refuse(SCHEMA_PAYLOAD_INVALID, msg)
            if isinstance(value, (list, tuple)) and any(
                isinstance(item, (Mapping, list, tuple)) for item in value
            ):
                msg = f"payload key {key!r} is an array of non-scalars (03:998)"
                raise _refuse(SCHEMA_PAYLOAD_INVALID, msg)
        self._validate_kind_payload(b.kind, obj)
        return obj

    def _validate_kind_payload(self, kind: Kind, obj: Mapping[str, Any]) -> None:
        """The two per-kind constraints 03:977 prints as the shape of the generated schemas.

        *"`heading.level` is `{"type":"integer","minimum":1,"maximum":9}`; `checkbox.checked` is
        `{"type":"boolean"}`; and so on."* Those two are printed; the "and so on" is generated, so
        the other fourteen are not invented here.
        """
        if kind is Kind.HEADING and "level" in obj:
            level = obj["level"]
            valid = isinstance(level, int) and not isinstance(level, bool)
            if not valid or not _MIN_HEADING_LEVEL <= level <= _MAX_HEADING_LEVEL:
                msg = f"heading.level is an integer {_MIN_HEADING_LEVEL}..{_MAX_HEADING_LEVEL}"
                raise _refuse(SCHEMA_PAYLOAD_INVALID, f"{msg}, got {level!r} (03:977)")
        if kind is Kind.CHECKBOX and "checked" in obj and not isinstance(obj["checked"], bool):
            msg = f"checkbox.checked is a boolean, got {obj['checked']!r} (03:977)"
            raise _refuse(SCHEMA_PAYLOAD_INVALID, msg)

    def _validate_score(self, b: BlockDraft) -> None:
        """Nullable TOGETHER, and the kind must be registered. 03:295, 03:1713-1717.

        The pair rule is also a DDL `CHECK ((score IS NULL) = (score_kind IS NULL))`, so this is
        the second enforcer rather than the only one; the REGISTER check has no second enforcer
        below `Q-G10`, which is why 01:531 classes the raise as INV-19's architectural `A`.
        """
        if (b.score is None) != (b.score_kind is None):
            msg = (
                f"score and score_kind are nullable TOGETHER, got ({b.score!r}, "
                f"{b.score_kind!r}): '0.7 on an unnamed scale is not a measurement' (03:1713)"
            )
            raise _refuse("OW_MODEL", msg)
        if b.score_kind is not None and b.score_kind not in self._score_kinds:
            raise _refuse(SCORE_KIND_UNREGISTERED, self._unregistered(b.score_kind))

    def _validate_x(self, x: Mapping[str, Any]) -> None:
        """`x.<vendor>.<key>`, vendor `ow` reserved, `canonical(x)` capped. 03:308.

        *"Keys MUST match `x\\.[a-z0-9_]+\\.[a-z0-9_]+`; the vendor segment `ow` is reserved for the
        framework. Not a digest input. `MAX_X_BYTES` caps `canonical(x)`."*
        """
        if not x:
            return
        for key in x:
            parts = key.split(".")
            shaped = (
                len(parts) == _X_KEY_SEGMENTS
                and parts[0] == "x"
                and all(_X_SEGMENT.fullmatch(part) for part in parts[1:])
            )
            if not shaped:
                msg = f"extension key {key!r} is not x.<vendor>.<key> (03:308)"
                raise _refuse("OW_MODEL", msg)
            if parts[1] == _RESERVED_X_VENDOR:
                msg = f"extension key {key!r} uses the reserved `ow` vendor segment (03:308)"
                raise _refuse("OW_MODEL", msg)
        size = len(canonical(dict(x)))
        if size > MAX_X_BYTES:
            msg = f"canonical(x) is {size} bytes"
            raise ResourceLimit(msg, limit="MAX_X_BYTES", fix=_FIX_VERIFY)

    def _clamped_trust(self, b: BlockDraft, block_id: BlockId) -> Trust:
        """`MAX_TRUST_BY_METHOD`, applied by the host. A CEILING, never a floor (03:1616-1634)."""
        ceiling = MAX_TRUST_BY_METHOD[b.method]
        if b.trust <= ceiling:
            return b.trust
        self._record_clamp(
            TRUST_CLAMPED,
            block_id,
            f"method {b.method.value} caps trust at {ceiling.name.lower()}; the driver claimed "
            f"{b.trust.name.lower()} (03:1616-1622)",
            {"claimed": b.trust.name.lower(), "stored": ceiling.name.lower()},
        )
        return ceiling

    def _clamped_quote(self, b: BlockDraft, os_kind: OsKind, block_id: BlockId) -> Quote:
        """`MAX_QUOTE_BY_OS_KIND` plus the derive clamp. 03:1673-1697. A ceiling, never a floor."""
        stored = _clamp_quote(b.quote, os_kind, self._origin_operator)
        if stored is not b.quote:
            self._record_clamp(
                QUOTE_CLAMPED,
                block_id,
                f"os_kind {os_kind.value} and operator {self._origin_operator!r} cap quote at "
                f"{stored.name.lower()}; the driver claimed {b.quote.name.lower()} (03:1697)",
                {"claimed": b.quote.name.lower(), "stored": stored.name.lower()},
            )
        return stored

    def _record_clamp(
        self, code: str, block_id: BlockId, message: str, detail: Mapping[str, Any]
    ) -> None:
        """A clamp is RECORDED with the driver's original claim, never silently corrected.

        03:1620 and 03:1697 both say so, and both say why: over-claiming has to be measurable in
        `ow graph doctor` and `ow doc verify` rather than repaired invisibly.
        """
        self._pending_rows().append(
            (
                _DIAG_INSERT,
                {
                    "doc_ord": self._require_doc().doc_ord,
                    "gen": self._require_doc().target_gen,
                    "page": None if self._page is None else self._page.record.page,
                    "block_id": int(block_id),
                    "part": None,
                    "code": code,
                    "severity": "warning",
                    "component": __name__,
                    "message": message,
                    "detail": _json_column(dict(detail)),
                    "fatal": 0,
                },
            )
        )

    def _same_page_parent(self, parent_id: BlockId, child: _Pending) -> None:
        """Record the child on its parent's pending record, when the parent is on this page.

        Only same-page parents get an entry, and that is the whole mechanism behind the closure
        pass: a container whose children are all on its own page has every child digest available
        when `end_page` runs, while a container that gains a child on a later page does not -- and
        03:1226-1230's query is exactly the set of the latter.
        """
        page = self._require_page()
        for pending in reversed(page.blocks):
            if pending.block_id == parent_id:
                pending.children.append(child.block_id)
                return

    def _text_of(self, b: BlockId) -> str | None:
        page = self._require_page()
        for pending in reversed(page.blocks):
            if pending.block_id == b:
                return pending.text
        msg = (
            f"block {int(b)} was not minted on the open page; a block's marks are staged in the "
            f"same transaction as the block (03:594)"
        )
        raise _refuse("OW_MODEL", msg)

    def _diag_row(self, d: Diag) -> tuple[str, dict[str, Any]]:
        doc = self._require_doc()
        return (
            _DIAG_INSERT,
            {
                "doc_ord": doc.doc_ord,
                "gen": doc.target_gen,
                "page": d.page
                if d.page is not None or self._page is None
                else self._page.record.page,
                "block_id": None if d.block is None else int(d.block),
                "part": d.part,
                "code": d.code,
                "severity": d.severity,
                "component": d.component,
                "message": d.message,
                "detail": _json_column(dict(d.detail)),
                "fatal": int(d.fatal),
            },
        )

    # -- end_page -----------------------------------------------------------------------------

    def _finalise_digests(self, page: _PageState) -> None:
        """One bottom-up pass over the page's forest. `_Pending` argues the timing.

        Reverse arrival order IS bottom-up: M-INV-1 writes a parent before its children, so a
        child always appears later in `blocks` than its parent. A container that gains a child on a
        LATER page is finalised here over the children it has so far -- the provisional digest
        03:1224-1228 describes -- and `end_doc`'s closure pass rewrites it.
        """
        digests: dict[BlockId, bytes] = {}
        for pending in reversed(page.blocks):
            digest = ow_content_digest(
                pending.kind_ord,
                pending.layer_ord,
                pending.text,
                pending.payload,
                [digests[child] for child in pending.children],
            )
            digests[pending.block_id] = digest
            pending.columns["content_digest"] = digest
            pending.columns["layout_digest"] = _layout_digest(digest, pending.page, pending.quad)

    def _page_statements(
        self, doc: _DocState, page: _PageState, stats: Mapping[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """The page transaction, in FK order: the `page` row, its blocks, then every satellite."""
        record = page.record
        rows: list[tuple[str, dict[str, Any]]] = [
            (
                "INSERT INTO page(doc_ord, gen, page, page_kind, label, w_mpt, h_mpt, rotation, "
                "quad_origin, method, status, ocr_error_score, parse_score, layout_score, "
                "table_score, ocr_score, producer_id, stats) VALUES(:doc_ord, :gen, :page, "
                ":page_kind, :label, :w_mpt, :h_mpt, :rotation, :quad_origin, :method, :status, "
                ":ocr_error_score, :parse_score, :layout_score, :table_score, :ocr_score, "
                ":producer_id, :stats)",
                {
                    "doc_ord": doc.doc_ord,
                    "gen": doc.target_gen,
                    "page": record.page,
                    "page_kind": _ordinal("page_kind", record.page_kind),
                    "label": record.label,
                    "w_mpt": record.w_mpt,
                    "h_mpt": record.h_mpt,
                    "rotation": record.rotation,
                    "quad_origin": record.quad_origin,
                    "method": _ordinal("method", record.method),
                    "status": record.status,
                    "ocr_error_score": record.ocr_error_score,
                    "parse_score": record.parse_score,
                    "layout_score": record.layout_score,
                    "table_score": record.table_score,
                    "ocr_score": record.ocr_score,
                    "producer_id": self._producer_id,
                    "stats": _json_column(dict(record.stats) | dict(stats)),
                },
            )
        ]
        rows.extend((_BLOCK_INSERT, pending.columns) for pending in page.blocks)
        rows.extend(doc.between_pages)
        doc.between_pages.clear()
        rows.extend(page.satellites)
        rows.append(
            (
                "UPDATE doc SET next_cite_n = :n WHERE doc_ord = :doc_ord",
                {"n": doc.next_cite_n, "doc_ord": doc.doc_ord},
            )
        )
        return rows

    # -- end_doc ------------------------------------------------------------------------------

    def _end_doc(
        self,
        connection: sqlite3.Connection,
        doc: _DocState,
        status: str,
        pending: list[tuple[str, dict[str, Any]]],
    ) -> DocRecord:
        """The four steps of 03:66-72, inside the one transaction `end_doc` submitted."""
        _execute(connection, list(pending))
        pending.clear()
        self._closure_pass(connection, doc)
        report = owcheck(_generation(connection, doc.doc_ord, doc.target_gen))
        _execute(
            connection,
            [
                (_DIAG_INSERT, _diag_bind(row))
                for row in report.diag_rows(doc_ord=doc.doc_ord, gen=doc.target_gen)
            ],
        )
        quarantined = not report.ok
        rebound: RebindReport | None = None
        if not quarantined:
            rebound = rebind(
                _Rebind(connection),
                doc.doc_ord,
                doc.target_gen,
                threshold=self._rebind_threshold,
                allow_unexplained=self._allow_unexplained,
            )
            quarantined = rebound.quarantined
        self._page_table_scores(connection, doc)
        if quarantined:
            _execute(connection, [self._quarantine_diag(doc, report.ok, rebound)])
        else:
            confidence = _confidence(connection, doc.doc_ord, doc.target_gen)
            achieved = _achieved(connection, doc, confidence)
            pages = connection.execute(
                "SELECT count(*) FROM page WHERE doc_ord = ? AND gen = ?",
                (doc.doc_ord, doc.target_gen),
            ).fetchone()[0]
            connection.execute(
                "UPDATE doc SET status = :status, achieved = :achieved, confidence = :confidence, "
                "page_count = :page_count, timings_ms = :timings WHERE doc_ord = :doc_ord",
                {
                    "status": status,
                    "achieved": _json_column(_capabilities_dict(achieved)),
                    "confidence": _json_column(confidence),
                    "page_count": int(pages) or doc.record.page_count,
                    "timings": _json_column(dict(doc.record.timings_ms)),
                    "doc_ord": doc.doc_ord,
                },
            )
        return _read_doc_record(connection, doc.doc_ord)

    def _quarantine_diag(
        self, doc: _DocState, owcheck_ok: bool, rebound: RebindReport | None
    ) -> tuple[str, dict[str, Any]]:
        """`OW_REBIND_UNEXPLAINED`, recorded rather than raised. `model/rebind.py` says why.

        *"`rebind()` RETURNS the report rather than raising ... the report is what carries
        `match_rate_by_page` to the surface that must explain the refusal, so the raise belongs to
        `end_doc()`'s caller."* The generation stays durable, invisible and inspectable by
        `ow doc diff` (03:1298-1302), and `doc.gen` has not moved.
        """
        detail: dict[str, Any] = {"owcheck_ok": owcheck_ok, "target_gen": doc.target_gen}
        if rebound is not None:
            detail |= {
                "carried": rebound.carried,
                "created": rebound.created,
                "retired": rebound.retired,
                "match_rate": rebound.match_rate(),
                "threshold": rebound.threshold,
            }
        reason = (
            "owcheck failed over the staged generation"
            if not owcheck_ok
            else "the rebind match rate is below the quarantine threshold"
        )
        return (
            _DIAG_INSERT,
            {
                "doc_ord": doc.doc_ord,
                "gen": doc.target_gen,
                "page": None,
                "block_id": None,
                "part": None,
                "code": REBIND_UNEXPLAINED,
                "severity": "error",
                "component": __name__,
                "message": f"generation {doc.target_gen} is quarantined: {reason} (03:1298-1302)",
                "detail": _json_column(detail),
                "fatal": 1,
            },
        )

    def _closure_pass(self, connection: sqlite3.Connection, doc: _DocState) -> None:
        """Finalise the digest of every container whose subtree closes on a later page. 03:1220.

        03:1230-1234 prints the query that finds them and says it is closed "transitively upward
        through `parent_id` (the root is always in the set for a multi-page document)". The pass is
        `O(cross-page containers)`, not `O(blocks)`, which is what makes it affordable inside
        `end_doc()`; the set is then walked DEEPEST FIRST so a parent reads its children's final
        digests rather than their provisional ones.
        """
        seeds = [
            int(row[0])
            for row in connection.execute(
                "SELECT DISTINCT a.block_id FROM block a JOIN block d "
                "ON d.parent_id = a.block_id AND d.gen = a.gen AND d.doc_ord = a.doc_ord "
                "WHERE a.doc_ord = ? AND a.gen = ? AND d.page > a.page",
                (doc.doc_ord, doc.target_gen),
            )
        ]
        closure: dict[int, int | None] = {}
        frontier = list(seeds)
        while frontier:
            block_id = frontier.pop()
            if block_id in closure:
                continue
            row = connection.execute(
                "SELECT parent_id FROM block WHERE block_id = ?", (block_id,)
            ).fetchone()
            parent = None if row is None or row[0] is None else int(row[0])
            closure[block_id] = parent
            if parent is not None:
                frontier.append(parent)
        for block_id in _deepest_first(closure):
            row = connection.execute(
                "SELECT kind, layer, text, payload, page, quad FROM block WHERE block_id = ?",
                (block_id,),
            ).fetchone()
            children = [
                bytes(child[0])
                for child in connection.execute(
                    "SELECT content_digest FROM block WHERE parent_id = ? AND gen = ? ORDER BY ord",
                    (block_id, doc.target_gen),
                )
            ]
            payload = None if row[3] is None else json.loads(row[3])
            digest = ow_content_digest(int(row[0]), int(row[1]), row[2], payload, children)
            quad = None if row[5] is None else Quad(*struct.unpack("<8i", row[5]))
            connection.execute(
                "UPDATE block SET content_digest = ?, layout_digest = ? WHERE block_id = ?",
                (digest, _layout_digest(digest, int(row[4]), quad), block_id),
            )

    def _page_table_scores(self, connection: sqlite3.Connection, doc: _DocState) -> None:
        """`page.table_score` is COMPUTED from that page's `table_meta.recon_score` values.

        03:474-478 and 03:1791-1794: *"or it is NULL and excluded from the mean"* -- the corrected
        form of docling's three-component mean wearing four, where the field is declared per page
        and never assigned. A page with no scored table keeps whatever the `PageRecord` carried,
        which for a driver following the rule is NULL.
        """
        connection.execute(
            "UPDATE page SET table_score = ("
            "  SELECT avg(t.recon_score) FROM table_meta t JOIN block b ON b.block_id = t.block_id"
            "   WHERE b.doc_ord = page.doc_ord AND b.gen = page.gen AND b.page = page.page"
            "     AND t.recon_score IS NOT NULL) "
            "WHERE doc_ord = ? AND gen = ? AND EXISTS ("
            "  SELECT 1 FROM table_meta t JOIN block b ON b.block_id = t.block_id"
            "   WHERE b.doc_ord = page.doc_ord AND b.gen = page.gen AND b.page = page.page"
            "     AND t.recon_score IS NOT NULL)",
            (doc.doc_ord, doc.target_gen),
        )


# ---------------------------------------------------------------------------
# 4. The statement bank, and the free functions the closures call.
# ---------------------------------------------------------------------------

_X_SEGMENT: Final = re.compile(r"[a-z0-9_]+")

_BLOCK_COLUMNS: Final = (
    "block_id",
    "doc_ord",
    "gen",
    "page",
    "addr",
    "cite",
    "parent_id",
    "ord",
    "kind",
    "raw_kind",
    "layer",
    "label",
    "text",
    "content_digest",
    "layout_digest",
    "revision",
    "quad",
    "os_kind",
    "os_part",
    "os_a",
    "os_b",
    "os_path",
    "os_extractor",
    "os_codec",
    "ts_a",
    "ts_b",
    "producer_id",
    "method",
    "trust",
    "score",
    "score_kind",
    "quote",
    "origin_operator",
    "origin_driver",
    "driver_schema_v",
    "restriction_bits",
    "decision_id",
    "payload",
    "state",
    "x",
)
"""`CREATE TABLE block`'s forty columns, in DDL order (`schema/migrations/0001_init.sql:235-289`).

A tuple and not a literal `INSERT` string, so the statement below and the carry `UPDATE` in
`_Rebind` are generated from ONE list. A column added to the DDL and forgotten in one of the two
statements is exactly the bug this shape cannot have.
"""

_BLOCK_INSERT: Final = (
    f"INSERT INTO block({', '.join(_BLOCK_COLUMNS)}) "
    f"VALUES({', '.join(':' + name for name in _BLOCK_COLUMNS)})"
)

_CARRY_COLUMNS: Final = tuple(
    name for name in _BLOCK_COLUMNS if name not in {"block_id", "doc_ord", "cite", "revision"}
)
"""What `rebind()`'s carry `UPDATE` sets. 03:1268-1274 prints the statement.

The four excluded columns are the identity that CARRIES: `block_id` is the row being updated,
`doc_ord` cannot change, `cite` is the durable name the whole pass exists to preserve, and
`revision` is `revision + :bump` rather than a literal. Everything else -- content, geometry,
spans, and all six provenance axes -- takes the staged row's value, because "identity carries;
confidence does not" (03:1296).
"""

_CARRY_UPDATE: Final = (
    # S608: every name interpolated here comes from `_BLOCK_COLUMNS`, a module constant; the
    # VALUES are bound parameters. Ruff cannot see the provenance across the join.
    f"UPDATE block SET {', '.join(f'{name} = :{name}' for name in _CARRY_COLUMNS)}, "  # noqa: S608
    f"revision = revision + :bump WHERE block_id = :old_id"
)

_DIAG_INSERT: Final = (
    "INSERT INTO diag(doc_ord, gen, page, block_id, part, code, severity, component, message, "
    "detail, fatal) VALUES(:doc_ord, :gen, :page, :block_id, :part, :code, :severity, :component, "
    ":message, :detail, :fatal)"
)


def _execute(connection: sqlite3.Connection, rows: Sequence[tuple[str, dict[str, Any]]]) -> None:
    """Run a staged transaction's statements in order, on the store thread's connection.

    Order is the contract: the `page` row before its blocks, a parent before its children
    (M-INV-1), a `table_meta` before its `cell`s. `executemany` is deliberately not used -- the
    statements differ -- and neither is a savepoint: the `Unit` IS the transaction (07:2717).
    """
    for statement, params in rows:
        connection.execute(statement, params)


def _deepest_first(closure: Mapping[int, int | None]) -> list[int]:
    """The closure set ordered children-before-parents, using only the parent links it carries.

    A container's final digest is a merkle over its children's FINAL digests (03:1194-1200), so a
    parent inside the set must be rewritten after every descendant inside it. The set is the
    transitive upward closure of 03:1230's query, so every member's parent chain is present; depth
    within the set is therefore computable without a second read.
    """
    depth: dict[int, int] = {}

    def measure(block_id: int) -> int:
        if block_id in depth:
            return depth[block_id]
        parent = closure.get(block_id)
        depth[block_id] = 0 if parent is None or parent not in closure else measure(parent) + 1
        return depth[block_id]

    return sorted(closure, key=lambda block_id: (-measure(block_id), block_id))


def _kind_at(ordinal: int) -> Kind:
    member = _MEMBER["kind", ordinal]
    assert isinstance(member, Kind)  # noqa: S101 -- the domain's own vocabulary.
    return member


def _layer_at(ordinal: int) -> Layer:
    member = _MEMBER["layer", ordinal]
    assert isinstance(member, Layer)  # noqa: S101 -- the domain's own vocabulary.
    return member


def _rel_kind_at(ordinal: int) -> RelKind:
    member = _MEMBER["rel_kind", ordinal]
    assert isinstance(member, RelKind)  # noqa: S101 -- the domain's own vocabulary.
    return member


def _generation(connection: sqlite3.Connection, doc_ord: int, gen: int) -> Generation:
    """One staged generation, in the shape `archive/owcheck.py` reads.

    That module's `BlockFacts` docstring anticipates exactly this caller -- *"this shape is also
    what lets one implementation run over a store cursor and over an archive frame ... the store
    wave's row is a third"* -- so the six clauses run over `g_t` here with the same code that runs
    over an `.owdoc`. `origin_part` is `os_part`, which the DDL already leaves NULL for `pixels`
    and `none`, the two kinds that can never reach `VERBATIM`.
    """
    blocks = [
        OwcheckFacts(
            addr=Addr(row[0]),
            page=int(row[1]),
            ord=int(row[2]),
            kind=_kind_at(int(row[3])),
            layer=_layer_at(int(row[4])),
            quote=Quote(int(row[5])),
            origin_part=row[6],
        )
        for row in connection.execute(
            "SELECT addr, page, ord, kind, layer, quote, os_part FROM block "
            "WHERE doc_ord = ? AND gen = ? AND state = 0 ORDER BY block_id",
            (doc_ord, gen),
        )
    ]
    rels = [
        (Addr(row[0]), Addr(row[1]), _rel_kind_at(int(row[2])))
        for row in connection.execute(
            "SELECT s.addr, d.addr, r.kind FROM rel r "
            "JOIN block s ON s.block_id = r.src_id JOIN block d ON d.block_id = r.dst_id "
            "WHERE r.doc_ord = ? AND r.gen = ?",
            (doc_ord, gen),
        )
    ]
    grids = [
        GridRow(
            table=Addr(row[0]),
            n_rows=int(row[1]),
            n_cols=int(row[2]),
            row_len=tuple(json.loads(row[3])),
            kind=_MEMBER["table_kind", int(row[4])].value,
            cells=tuple(
                (int(c[0]), int(c[1]), int(c[2]), int(c[3]))
                for c in connection.execute(
                    "SELECT r, c, row_span, col_span FROM cell WHERE table_id = ? ORDER BY r, c",
                    (row[5],),
                )
            ),
            header_rows=int(row[6]),
            header_cols=int(row[7]),
            has_merges=bool(row[8]),
        )
        for row in connection.execute(
            "SELECT b.addr, t.n_rows, t.n_cols, t.row_len, t.kind, t.block_id, t.header_rows, "
            "t.header_cols, t.has_merges FROM table_meta t JOIN block b ON b.block_id = t.block_id "
            "WHERE b.doc_ord = ? AND b.gen = ?",
            (doc_ord, gen),
        )
    ]
    retained = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT path FROM part WHERE doc_ord = ? AND store_ref IS NOT NULL", (doc_ord,)
        )
    )
    return Generation(blocks=blocks, rels=rels, grids=grids, retained_parts=retained)


def _confidence(connection: sqlite3.Connection, doc_ord: int, gen: int) -> dict[str, Any]:
    """`doc.confidence`, computed at `end_doc` and never a driver field. 03:1777-1790.

    Each value is the mean of the non-NULL `page.*_score` values, **with NULL pages excluded and
    the count published**. A component with `n_scored == 0` is `null`, not `0.0`, and is excluded
    from any aggregate grade -- the corrected form of docling's `nanmean` over an all-NaN list.
    """
    columns = ("parse_score", "layout_score", "table_score", "ocr_score")
    gathered: dict[str, list[float]] = {name: [] for name in _CONFIDENCE_COMPONENTS}
    for row in connection.execute(
        f"SELECT {', '.join(columns)} FROM page WHERE doc_ord = ? AND gen = ?",  # noqa: S608
        (doc_ord, gen),
    ):
        for component, value in zip(_CONFIDENCE_COMPONENTS, row, strict=True):
            if value is not None:
                gathered[component].append(float(value))
    scored = {component: len(values) for component, values in gathered.items()}
    confidence: dict[str, Any] = {
        component: _mean(values) for component, values in gathered.items()
    }
    confidence["n_scored"] = scored
    return confidence


def _achieved(
    connection: sqlite3.Connection, doc: _DocState, confidence: Mapping[str, Any]
) -> Capabilities:
    """`achieved`, derived from the COMMITTED rows and clamped by `declared`. 03 section 2.9.

    *"`achieved` is computed by the host from the committed rows, not reported by the driver. That
    is INV-7 at the capability grain"* (03:534-536), and the derivation table at 03:508-528 is
    worked through field by field below. Every field is then clamped by `declared`: achieved "may
    be lower, never higher" (03:527).

    Two fields are honestly underdetermined here and both fall to the safe side.
    `origin_span = "exact"` requires "every non-`pixels` block's branch [to] re-verify on the
    conformance sample" (03:512), which is `omniweave-conform`'s job and not a store read, so the
    strongest value this can conclude is `normalized`. `assets` distinguishes `refs` from `bytes`
    by whether the CAS actually holds the object, and `asset.store_ref` is `NOT NULL` in the DDL
    (03:2077) with no column recording a miss -- so a document with assets reports `bytes` clamped
    by `declared`, which is the value a driver that declared `refs` gets. Both are recorded rather
    than papered over, exactly as 03:526 records `reading_order` and `round_trip`.
    """
    declared = doc.declared
    where = (doc.doc_ord, doc.target_gen)

    def one(sql: str, params: tuple[Any, ...] = where) -> Any:
        return connection.execute(sql, params).fetchone()[0]

    quads = one("SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND quad IS NOT NULL")
    spatial = "none" if not quads else "block_bbox"
    if quads and declared.spatial in ("line_bbox", "char_bbox"):
        spatial = declared.spatial

    body = _ordinal("layer", Layer.BODY)
    none_kind = _ordinal("origin_span_kind", OsKind.NONE)
    pixels_kind = _ordinal("origin_span_kind", OsKind.PIXELS)
    body_rows = one(
        "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND layer=?", (*where, body)
    )
    weakest = one(
        "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND layer=? AND os_kind=?",
        (*where, body, none_kind),
    )
    non_pixel = one(
        "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND layer=? AND os_kind<>?",
        (*where, body, pixels_kind),
    )
    origin_span = "normalized" if body_rows and not weakest and non_pixel else "none"

    tables = "none"
    if one(
        "SELECT count(*) FROM table_meta t JOIN block b ON b.block_id=t.block_id "
        "WHERE b.doc_ord=? AND b.gen=?"
    ):
        spans = one(
            "SELECT count(*) FROM cell c JOIN block b ON b.block_id=c.block_id "
            "WHERE b.doc_ord=? AND b.gen=? AND (c.row_span>1 OR c.col_span>1)"
        )
        tables = "cells_with_spans" if spans else "cells"

    assets = (
        "bytes" if one("SELECT count(*) FROM asset WHERE doc_ord=?", (doc.doc_ord,)) else "none"
    )
    asset_origin = bool(
        one(
            "SELECT count(*) FROM asset WHERE doc_ord=? AND origin_part IS NOT NULL",
            (doc.doc_ord,),
        )
    )

    note_layer = _ordinal("layer", Layer.NOTE)
    notes = "none"
    note_rows = one(
        "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND layer=?", (*where, note_layer)
    )
    if note_rows:
        # 03:531 counts NOTE BODIES -- the `footnote`/`endnote` block a `note_ref` points at --
        # and not the paragraphs inside one, which inherit `layer = note` (M-INV-5) and are
        # referenced by nobody. Counting every note-layer block made a document whose every
        # note is referenced read `inline` on its first real parse (D587).
        unlinked = one(
            "SELECT count(*) FROM block b WHERE b.doc_ord=? AND b.gen=? AND b.layer=? "
            "AND b.kind IN (?, ?) "
            "AND NOT EXISTS (SELECT 1 FROM rel r WHERE r.dst_id=b.block_id AND r.kind=?)",
            (
                *where,
                note_layer,
                _ordinal("kind", Kind.FOOTNOTE),
                _ordinal("kind", Kind.ENDNOTE),
                _ordinal("rel_kind", RelKind.NOTE_REF),
            ),
        )
        notes = "inline" if unlinked else "linked"

    grain = "none"
    if any(confidence[component] is not None for component in _CONFIDENCE_COMPONENTS):
        grain = "page"
    if one("SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND score IS NOT NULL"):
        grain = "element"

    non_body = one(
        "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND layer<>?", (*where, body)
    )
    furniture = declared.furniture if non_body else "destroyed"
    if non_body and furniture == "destroyed":
        furniture = "flagged"

    section_kind = _ordinal("kind", Kind.SECTION)
    sections = (
        "typed_levels"
        if one(
            "SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND kind=?",
            (*where, section_kind),
        )
        else _clamp_ladder("sections", "outline_from_source", declared.sections)
    )

    math = _math_notations(connection, doc)
    computed = Capabilities(
        spatial=_clamp_ladder("spatial", spatial, declared.spatial),  # type: ignore[arg-type]
        origin_span=_clamp_ladder("origin_span", origin_span, declared.origin_span),  # type: ignore[arg-type]
        text_span=declared.text_span
        and bool(one("SELECT count(*) FROM block WHERE doc_ord=? AND gen=? AND ts_a IS NOT NULL")),
        marks=declared.marks
        and bool(
            one(
                "SELECT count(*) FROM mark m JOIN block b ON b.block_id=m.block_id "
                "WHERE b.doc_ord=? AND b.gen=?"
            )
        ),
        reading_order=declared.reading_order,
        sections=_clamp_ladder("sections", sections, declared.sections),  # type: ignore[arg-type]
        tables=_clamp_ladder("tables", tables, declared.tables),  # type: ignore[arg-type]
        math=math & declared.math,
        assets=_clamp_ladder("assets", assets, declared.assets),  # type: ignore[arg-type]
        asset_origin=declared.asset_origin and asset_origin,
        notes=_clamp_ladder("notes", notes, declared.notes),  # type: ignore[arg-type]
        confidence=_clamp_ladder("confidence", grain, declared.confidence),  # type: ignore[arg-type]
        furniture=_clamp_ladder("furniture", furniture, declared.furniture),  # type: ignore[arg-type]
        round_trip=declared.round_trip,
        forfeits=declared.forfeits,
    )
    return replace(computed, forfeits=declared.forfeits | _forfeited(declared, computed))


def _math_notations(connection: sqlite3.Connection, doc: _DocState) -> frozenset[str]:
    """`payload.notation` on `formula` blocks, unioned with `mark.value.notation` on math marks."""
    found: set[str] = set()
    for (payload,) in connection.execute(
        "SELECT payload FROM block WHERE doc_ord=? AND gen=? AND kind=? AND payload IS NOT NULL",
        (doc.doc_ord, doc.target_gen, _ordinal("kind", Kind.FORMULA)),
    ):
        notation = json.loads(payload).get("notation")
        if isinstance(notation, str):
            found.add(notation)
    for (value,) in connection.execute(
        "SELECT m.value FROM mark m JOIN block b ON b.block_id = m.block_id "
        "WHERE b.doc_ord=? AND b.gen=? AND m.kind='math' AND m.value IS NOT NULL",
        (doc.doc_ord, doc.target_gen),
    ):
        notation = json.loads(value).get("notation")
        if isinstance(notation, str):
            found.add(notation)
    return frozenset(found)


def _forfeited(declared: Capabilities, computed: Capabilities) -> frozenset[str]:
    """`forfeits` is "the declaration, unioned with anything the derivations above proved absent".

    03:528. The five members are `drivers/card.py`'s `PARSE_SETS["forfeits"]` vocabulary; only the
    three this document's rows can PROVE absent are added -- `blocks` and `citation` are properties
    of a parse having happened at all, which a committed generation with rows disproves.
    """
    absent: set[str] = set()
    if computed.spatial == "none":
        absent.add("spatial")
    if not computed.text_span and declared.text_span:
        absent.add("text_span")
    if computed.round_trip == "none":
        absent.add("round_trip")
    return frozenset(absent)


def _capabilities_from(obj: Mapping[str, Any]) -> Capabilities:
    """A `Capabilities` back out of a `doc.declared` / `doc.achieved` column."""
    return Capabilities(
        spatial=obj["spatial"],
        origin_span=obj["origin_span"],
        text_span=bool(obj["text_span"]),
        marks=bool(obj["marks"]),
        reading_order=obj["reading_order"],
        sections=obj["sections"],
        tables=obj["tables"],
        math=frozenset(obj["math"]),
        assets=obj["assets"],
        asset_origin=bool(obj["asset_origin"]),
        notes=obj["notes"],
        confidence=obj["confidence"],
        furniture=obj["furniture"],
        round_trip=obj["round_trip"],
        forfeits=frozenset(obj.get("forfeits", ())),
    )


def _read_doc_record(connection: sqlite3.Connection, doc_ord: int) -> DocRecord:
    """The `doc` row as a `DocRecord`. What `end_doc` returns: the record at the committed head.

    Read back rather than reconstructed, so a quarantined generation returns the OLD `gen`,
    `status`, `achieved` and `confidence` without this method having to remember which of the four
    it declined to write (03:596, 03:1298-1302).
    """
    row = connection.execute(
        "SELECT doc_ord, doc_key, gen, source_sha256, normalizer, uri, media_type, format, "
        "format_evidence, source_bytes, status, page_count, model_version, declared, achieved, "
        "confidence, timings_ms, x FROM doc WHERE doc_ord = ?",
        (doc_ord,),
    ).fetchone()
    return DocRecord(
        doc_ord=int(row[0]),
        doc_key=bytes(row[1]),
        gen=int(row[2]),
        source_sha256=bytes(row[3]),
        normalizer=row[4],
        uri=row[5],
        media_type=row[6],
        format=row[7],
        format_evidence=MappingProxyType(json.loads(row[8])),
        source_bytes=int(row[9]),
        status=row[10],
        page_count=None if row[11] is None else int(row[11]),
        model_version=row[12],
        declared=_capabilities_from(json.loads(row[13])),
        achieved=_capabilities_from(json.loads(row[14])),
        confidence=MappingProxyType(json.loads(row[15])),
        timings_ms=MappingProxyType(json.loads(row[16])),
        x=MappingProxyType(json.loads(row[17])),
    )


# ---------------------------------------------------------------------------
# 5. The `rebind()` bridge. `model/rebind.py` owns the decisions; this owns the SQL.
# ---------------------------------------------------------------------------


class _Rebind:
    """`RebindStore` over one connection. Five methods, and every one is 03 section 6.5's.

    `model/rebind.py` declares `RebindReadSide` and `RebindWriteSide` as STRUCTURAL protocols
    precisely so this class can exist without `model` importing `store` -- "the same reason
    `Snapshot.token` is typed `object`". Nothing here decides anything: the matcher is pure and
    already ran, and this applies its decisions.

    **The `DELETE`-before-`UPDATE` order is mandatory** (03:1276-1279): `block_addr` is
    `UNIQUE(doc_ord, gen, addr)`, so moving the old row to `g_t` while the staged row still holds
    that addr is a constraint violation. Two steps the plan's fence leaves as a comment -- "3.
    re-point the staged row's satellites" -- are spelled out below, because with
    `PRAGMA foreign_keys = ON` (`sqlite.py`'s `CONN_PRAGMAS`) the staged row's `DELETE` cascades
    into `mark`, `cell`, `table_meta`, `grid_slot`, `block_asset` **and its own children's
    `parent_id`**. The children are re-pointed first and the satellites are captured first, or
    carrying a table would delete its whole subtree.
    """

    __slots__ = ("_connection",)

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # -- read side ----------------------------------------------------------------------------

    def doc_generation(self, doc_ord: int) -> int:
        row = self._connection.execute(
            "SELECT gen FROM doc WHERE doc_ord = ?", (doc_ord,)
        ).fetchone()
        return 0 if row is None else int(row[0])

    def blocks_at_gen(self, doc_ord: int, gen: int) -> Sequence[BlockFacts]:
        """Every non-retired block of one generation. NOT through `ow_block_head` (03:2378).

        The staged generation is invisible to that view by design and this pass is the one caller
        that must see both.
        """
        return [
            BlockFacts(
                block_id=BlockId(int(row[0])),
                addr=Addr(row[1]),
                cite=Cite(row[2]),
                kind=_kind_at(int(row[3])),
                parent=None if row[4] is None else BlockId(int(row[4])),
                ord=int(row[5]),
                page=int(row[6]),
                content_digest=bytes(row[7]),
                revision=int(row[8]),
            )
            for row in self._connection.execute(
                "SELECT block_id, addr, cite, kind, parent_id, ord, page, content_digest, "
                "revision FROM block WHERE doc_ord = ? AND gen = ? AND state = 0 "
                "ORDER BY page, ord, block_id",
                (doc_ord, gen),
            )
        ]

    # -- write side ---------------------------------------------------------------------------

    def carry_forward(self, carry: Carry) -> None:
        """DELETE the staged row, then UPDATE the durable row forward. `Carry` says why in order."""
        new_id, old_id = int(carry.new_id), int(carry.old_id)
        staged = self._connection.execute(
            f"SELECT {', '.join(_CARRY_COLUMNS)} FROM block WHERE block_id = ?",  # noqa: S608
            (new_id,),
        ).fetchone()
        if staged is None:
            msg = f"rebind names staged block {new_id}, which is not in the store"
            raise _refuse("OW_MODEL", msg, fix=_FIX_REPARSE)
        satellites = self._capture(new_id)
        # the staged row's children must not go down with it: `parent_id` cascades.
        self._connection.execute(
            "UPDATE block SET parent_id = ? WHERE parent_id = ?", (old_id, new_id)
        )
        self._release(old_id)
        self._connection.execute("DELETE FROM block WHERE block_id = ?", (new_id,))
        params = dict(zip(_CARRY_COLUMNS, staged, strict=True))
        params["block_id"] = old_id
        self._connection.execute(_CARRY_UPDATE, params | {"bump": carry.bump, "old_id": old_id})
        self._restore(old_id, new_id, satellites)

    def retire(self, retirement: Retire) -> None:
        """`state = 1` on the head row plus one `block_history` row. Never a DELETE (03:310)."""
        self._connection.execute(
            "UPDATE block SET state = 1 WHERE block_id = ?", (int(retirement.block_id),)
        )
        self._connection.execute(
            "INSERT OR REPLACE INTO block_history(block_id, doc_ord, retired_gen, superseded_by, "
            "reason) VALUES(?, ?, ?, ?, ?)",
            (
                int(retirement.block_id),
                retirement.doc_ord,
                retirement.retired_gen,
                None if retirement.superseded_by is None else int(retirement.superseded_by),
                retirement.reason,
            ),
        )

    def commit_generation(self, doc_ord: int, gen: int) -> None:
        """`UPDATE doc SET gen = :gen` -- the single statement that makes a generation visible."""
        self._connection.execute("UPDATE doc SET gen = ? WHERE doc_ord = ?", (gen, doc_ord))

    # -- the satellite carry ------------------------------------------------------------------

    def _capture(self, block_id: int) -> dict[str, list[tuple[Any, ...]]]:
        """Every satellite row the staged block's `DELETE` is about to cascade away."""
        query = self._connection.execute
        return {
            "mark": query(
                "SELECT a, b, kind, value FROM mark WHERE block_id = ?", (block_id,)
            ).fetchall(),
            "block_asset": query(
                "SELECT asset_id, role FROM block_asset WHERE block_id = ?", (block_id,)
            ).fetchall(),
            "table_meta": query(
                "SELECT n_rows, n_cols, row_len, header_rows, header_cols, kind, recon_strategy, "
                "recon_score, has_merges, native_part, native_sha256 FROM table_meta "
                "WHERE block_id = ?",
                (block_id,),
            ).fetchall(),
            "cells_of_table": query(
                "SELECT block_id, r, c, row_span, col_span FROM cell WHERE table_id = ?",
                (block_id,),
            ).fetchall(),
            "slots_of_table": query(
                "SELECT r, c, origin_id FROM grid_slot WHERE table_id = ?", (block_id,)
            ).fetchall(),
            "own_cell": query(
                "SELECT table_id, r, c, row_span, col_span FROM cell WHERE block_id = ?",
                (block_id,),
            ).fetchall(),
            "slots_of_cell": query(
                "SELECT table_id, r, c FROM grid_slot WHERE origin_id = ?", (block_id,)
            ).fetchall(),
        }

    def _release(self, old_id: int) -> None:
        """Drop the durable row's OWN satellites: it is about to hold the staged row's content.

        A carried row takes the new generation's marks, cells and asset links wholesale, because
        none of them is a digest input and all of them describe the parse (03:1294-1300). Deleting
        `table_meta` here cascades that table's old `cell` and `grid_slot` rows, which is why the
        cells' own carries re-insert theirs.
        """
        for statement in (
            "DELETE FROM mark WHERE block_id = ?",
            "DELETE FROM block_asset WHERE block_id = ?",
            "DELETE FROM table_meta WHERE block_id = ?",
            "DELETE FROM cell WHERE block_id = ?",
        ):
            self._connection.execute(statement, (old_id,))

    def _restore(
        self, old_id: int, new_id: int, satellites: Mapping[str, Sequence[tuple[Any, ...]]]
    ) -> None:
        """Re-insert the captured satellites against the carried id, `table_meta` first."""
        execute = self._connection.execute
        for row in satellites["table_meta"]:
            execute(
                "INSERT INTO table_meta(block_id, n_rows, n_cols, row_len, header_rows, "
                "header_cols, kind, recon_strategy, recon_score, has_merges, native_part, "
                "native_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (old_id, *row),
            )
        for row in satellites["cells_of_table"]:
            execute(
                "INSERT INTO cell(block_id, table_id, r, c, row_span, col_span) "
                "VALUES(?,?,?,?,?,?)",
                (row[0], old_id, *row[1:]),
            )
        for row in satellites["own_cell"]:
            execute(
                "INSERT INTO cell(block_id, table_id, r, c, row_span, col_span) "
                "VALUES(?,?,?,?,?,?)",
                (old_id, *row),
            )
        for row in satellites["slots_of_table"]:
            origin = old_id if int(row[2]) == new_id else int(row[2])
            execute(
                "INSERT OR REPLACE INTO grid_slot(table_id, r, c, origin_id) VALUES(?,?,?,?)",
                (old_id, row[0], row[1], origin),
            )
        for row in satellites["slots_of_cell"]:
            execute(
                "INSERT OR REPLACE INTO grid_slot(table_id, r, c, origin_id) VALUES(?,?,?,?)",
                (row[0], row[1], row[2], old_id),
            )
        for row in satellites["mark"]:
            execute(
                "INSERT INTO mark(block_id, a, b, kind, value) VALUES(?,?,?,?,?)", (old_id, *row)
            )
        for row in satellites["block_asset"]:
            execute(
                "INSERT OR IGNORE INTO block_asset(block_id, asset_id, role) VALUES(?,?,?)",
                (old_id, *row),
            )
