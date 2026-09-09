"""The L2 owdoc types and taint.py. LAZY.
03-document-model.md; 02-architecture.md section 2 row 24.

**Docstring-only on purpose, and the reason is a measurement rather than a style.**
02-architecture.md:248 and 18-api-sketch.md:834-838 name `omniweave_core.model` itself as the
home of `Block`, `BlockDraft`, `Capabilities`, `Doc` and the rest, so the flat re-export
surface belongs in this file. It cannot land yet. `tools/schemagen.py`'s `INVENTORY` resolves
`fragment-v1.json` off `omniweave_core.model.BlockDraft` and `document-v1.json` off
`omniweave_core.model.Doc`, and G6 -- `test_schemagen.py::test_the_committed_tree_passes_the_gate`
-- asserts that the committed tree passes the gate. Binding either name here flips its row from
PENDING to LIVE, at which point `check()` calls `build_schema`, which raises
`UnsupportedDeclarationError` on `BlockDraft.parent`: the reflector has no handler for a
`NewType`, and none for `bytes` either, which is what `Block.content_digest` is. Measured, not
assumed. Two things must land before the surface can, and neither is one of this cluster's
files: a `NewType`/`bytes` handler in `tools/schemagen.py`, and the generated
`schema/fragment-v1.json` that the same gate then demands.

Until then every consumer names the submodule -- `omniweave_core.model.enums`,
`omniweave_core.model.spans`, `omniweave_core.model.block` -- which is also what keeps this file
free of the module-level statement that `test_core_eager_surface.py` forbids in a subpackage
home, and what keeps G17 true without argument.

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
