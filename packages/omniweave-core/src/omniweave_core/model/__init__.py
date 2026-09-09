"""The L2 owdoc types and taint.py. LAZY.
03-document-model.md; 02-architecture.md section 2 row 24.

**The flat re-export surface, which 02-architecture.md:248 and 18-api-sketch.md:834-838 put in
this module rather than in its submodules.** A consumer writes
`from omniweave_core.model import Block`, not `... .model.block import Block`.

This file was docstring-only until `tools/schemagen.py` could reflect two annotations, and the
dependency is worth recording because it is not obvious. `schemagen`'s `INVENTORY` resolves
`fragment-v1.json` off `omniweave_core.model.BlockDraft`, so BINDING THE NAME HERE flips that
row from PENDING to LIVE -- at which point G6 (`test_schemagen.py`'s
`test_the_committed_tree_passes_the_gate`) calls `build_schema`, which raised
`UnsupportedDeclarationError` on `BlockDraft.parent` (a `NewType`, which the reflector had no
handler for), on `BlockDraft.quad` (a `NamedTuple`, which `typing.get_origin` reports as
nothing) and on `Block.content_digest` (`bytes`, which has no JSON type at all). All three
handlers now exist: a `NewType` reflects as its supertype carrying its own name as the
description, a `NamedTuple` reflects as the fixed-length ARRAY the wire actually uses, and
`bytes` renders as 32 lowercase hex characters per
03-document-model.md:665's wire mapping. `schema/fragment-v1.json` is committed alongside them.

`Grid` HAS landed and is bound below; `Doc` has landed as `omniweave_core.model.doc.Doc` and is
deliberately NOT bound here, which keeps `document-v1.json` PENDING. Both halves of that need
saying, because the two types were deferred together and only one of them can be re-exported
today.

* `Grid` (03 section 10.1) reads nothing. It is a derived cover map over already-minted
  `BlockId`s, `build_grid` is its sole constructor and `render_grid(g, reader, fmt)` (03:1892) is
  handed a reader rather than holding one, so it is a value type like the rest of this surface and
  goes on it. No inventory row names it.
* `Doc` (03 section 13.5) is a lazy handle over a live reader, and `tools/schemagen.py`'s
  `document-v1.json` row resolves off `omniweave_core.model.Doc` by name. Binding it here flips
  that row from PENDING to LIVE, and a LIVE row is byte-diffed against `build_schema`'s output --
  which cannot exist. `build_schema` reflects DATACLASSES and refuses anything else, and 03:2588
  prints `class Doc:` undecorated, unlike every record in section 2.8; `_object_schema` then calls
  `typing.get_type_hints()`, and `Doc.rec`'s annotation names `DocRecord`, which 03 section 2.8
  homes in `block.py`'s cluster and which has not landed. Both gates fail, and they would fail for
  a reason deeper than a missing import: a handle whose whole job is to NOT materialise page
  renders, asset bytes, retained parts, the FTS index or a `SpanMap` (03:2617-2619) has no wire
  form for a second-language reader to read. `document-v1.json`'s own locus in that inventory row
  is 03 section 3.1, "The wire record" -- the twenty-nine short archive keys of a BLOCK -- and the
  plan names no declaring Python type for the file at any of its three enumerations
  (02-architecture.md:273, 11-repo-layout.md:347, 18-api-sketch.md section 8). So the row's
  `symbol` is a build-time inference and not a transcription, the row stays PENDING, and the fix
  is an edit to `tools/schemagen.py`'s INVENTORY plus `test_schemagen.py:539` -- which pins
  `("omniweave_core.model", "Doc")` as its example of a pending row and would break on the day the
  name is bound. Both are reported as required edits, with the exact lines, rather than made here.

THE IMPORTS BELOW ARE WHY THIS FILE IS NOT EMPTY, AND THEY ARE NOT A G17 PROBLEM. `model` is one
of the nine lazy subpackages, and G17's assertion is that `import omniweave_core` does not reach
it -- which holds because `omniweave_core/__init__.py` imports none of the nine and exposes them
through `__getattr__`. Importing `omniweave_core.model` is what a caller does ON PURPOSE; what
must never happen is paying for it unasked. `test_core_eager_surface.py`'s subpackage-home rule
covers the homes that are still EMPTY, and this one no longer is.

Landed so far, one plan section per module and no name in two of them (INV-21).

* `enums.py` -- 03 section 2.1: the fifteen closed `enum_val` vocabularies with their
  append-only ordinals, `MAX_TRUST_BY_METHOD`, `GENERATION_BLOCKED` and `Taint`.
* `spans.py` -- 03 sections 2.3 and 2.4: `Quad` and its sole driver-frame constructor, the five
  `OriginSpan` variants, `TextSpan`, `RenderSpan`, `SpanMap` and `SERIALIZER_CAPS`.
* `block.py` -- 03 sections 2.2, 2.5, 2.6 and 2.9: `BlockId`, `Addr`, `Cite`, `Mark`, `Block`,
  `CellPos`, `BlockDraft` (the one mutable type in the framework) and `Capabilities`.
* `serialize.py` -- 03 sections 16.1, 16.2 and 16.5: `serialize()` over the five core formats,
  `ArraySpanMap` (the concrete `SpanMap` 03:2855-2861 specifies), `ViewScope` -- whose sole home
  section 16.1 is (03:3048) -- and `TableFacts`. It does NOT bind `Doc`: `Doc.serialize(fmt, **kw)`
  (03:2604) is the lazy handle's forwarding method and lands with `Doc`, through the store. W2.8's
  other half -- `block_sec` with `sec_path`, and `block_fts` as an FTS5 external-content table --
  is SQL and belongs to the store wave, not here.
* `grid.py` -- 03 sections 10.1, 10.2 and 10.3's rendering paragraph: `Origin`, `Covered`, `Slot`,
  `Grid` with the exactly-once cover map, `build_grid` (the sole, streaming constructor) and
  `render_grid`, which delegates to `serialize.py` rather than carrying a second table renderer.
  `serialize.py`'s own `_cover_map` predates it and should now delegate here; reported.
* `doc.py` -- 03 section 13.5: `Doc`, the lazy read handle, and `DocReadSide`, the structural
  Protocol it reads through. Not re-exported below -- see the paragraph above.

Still owed by P2. `DocSink`'s eleven methods (03 section 2.10). Section 2.8's records:
`Producer`, `DocRecord`, `PageRecord`, `AssetDraft`, `AssetRef`, `Rel`, `Frame`. Section 2.6's
`CellDraft` (03:337-338), which `build_grid` consumes and reads structurally until it lands.
Section 9's `Diag` (03:1798-1804), which `build_grid`'s `diag` sink cannot construct until it has
a home. `payload.py`'s three named readers (03:991). `MAX_QUOTE_BY_OS_KIND` and `QuoteVerdict`
(03 section 8.3). And `taint.py`, if the owner keeps 02-architecture.md:248's separate home for
names `enums.py` already declares -- as a pure re-export, never a second declaration.
"""

from __future__ import annotations

from omniweave_core.model.block import (
    Addr,
    Block,
    BlockDraft,
    BlockId,
    Capabilities,
    CellPos,
    Cite,
    Mark,
)
from omniweave_core.model.enums import (
    ENUM_DOMAINS,
    GENERATION_BLOCKED,
    MAX_TRUST_BY_METHOD,
    AliasKind,
    AnchorKind,
    ClaimStatus,
    Kind,
    Lane,
    Layer,
    Method,
    OsKind,
    PageKind,
    Quote,
    RelKind,
    TableKind,
    Taint,
    TimePrecision,
    Trust,
    enum_val_rows,
)
from omniweave_core.model.grid import (
    RECON_STRATEGIES,
    Covered,
    Grid,
    GridReadSide,
    Origin,
    Slot,
    build_grid,
    render_grid,
)
from omniweave_core.model.serialize import (
    FORMATS,
    SERIALIZER_VERSION,
    ArraySpanMap,
    TableFacts,
    ViewScope,
    serialize,
)
from omniweave_core.model.spans import (
    SERIALIZER_CAPS,
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    OriginSpan,
    Quad,
    RenderSpan,
    SpanMap,
    TextSpan,
)

__all__ = [
    "ENUM_DOMAINS",
    "FORMATS",
    "GENERATION_BLOCKED",
    "MAX_TRUST_BY_METHOD",
    "RECON_STRATEGIES",
    "SERIALIZER_CAPS",
    "SERIALIZER_VERSION",
    "Addr",
    "AliasKind",
    "AnchorKind",
    "ArraySpanMap",
    "Block",
    "BlockDraft",
    "BlockId",
    "Capabilities",
    "CellPos",
    "Cite",
    "ClaimStatus",
    "Covered",
    "Grid",
    "GridReadSide",
    "Kind",
    "Lane",
    "Layer",
    "Mark",
    "Method",
    "Origin",
    "OriginBytes",
    "OriginGlyphs",
    "OriginNodePath",
    "OriginNone",
    "OriginPixels",
    "OriginSpan",
    "OsKind",
    "PageKind",
    "Quad",
    "Quote",
    "RelKind",
    "RenderSpan",
    "Slot",
    "SpanMap",
    "TableFacts",
    "TableKind",
    "Taint",
    "TextSpan",
    "TimePrecision",
    "Trust",
    "ViewScope",
    "build_grid",
    "enum_val_rows",
    "render_grid",
    "serialize",
]
