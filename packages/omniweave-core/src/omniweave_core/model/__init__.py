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

`Doc` is deliberately still absent from the surface, which keeps `document-v1.json` PENDING. It is
a lazy handle that reads THROUGH the store (03 sections 13.5 and 2584: "`Doc` is a **lazy handle**,
not a loaded object"), so it follows `omniweave_core.store` rather than the value types, and the
store is P2 stage B. Binding a placeholder to satisfy the inventory would make G6 assert a schema
for a type whose read path does not exist.

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

Still owed by P2. `Doc` and `Grid`, the two lazy handles (03 sections 13.5 and 10.1) -- `Doc`
reads through the store and `Grid` is built only by `build_grid`, so both follow the store
rather than the value types. `DocSink`'s eleven methods (03 section 2.10). Section 2.8's
records: `Producer`, `DocRecord`, `PageRecord`, `AssetDraft`, `AssetRef`, `Rel`, `Frame`.
`payload.py`'s three named readers (03:991). `MAX_QUOTE_BY_OS_KIND` (03 section 8.3). And
`taint.py`, if the owner keeps 02-architecture.md:248's separate home for names `enums.py`
already declares -- as a pure re-export, never a second declaration.
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
    "GENERATION_BLOCKED",
    "MAX_TRUST_BY_METHOD",
    "SERIALIZER_CAPS",
    "Addr",
    "AliasKind",
    "AnchorKind",
    "Block",
    "BlockDraft",
    "BlockId",
    "Capabilities",
    "CellPos",
    "Cite",
    "ClaimStatus",
    "Kind",
    "Lane",
    "Layer",
    "Mark",
    "Method",
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
    "SpanMap",
    "TableKind",
    "Taint",
    "TextSpan",
    "TimePrecision",
    "Trust",
    "enum_val_rows",
]
