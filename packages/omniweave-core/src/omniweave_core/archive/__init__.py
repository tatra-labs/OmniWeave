"""The .owdoc plain-ZIP codec and owcheck. LAZY. 02-architecture.md section 2 row 25.

**The surface is `export(store, path)` and `import_(path, sink)`**, which 02-architecture.md:249
names as this subpackage's two entry points, plus `owcheck` -- 02:249 puts `owcheck` in
`omniweave_core.archive` beside the codec, and 03-document-model.md:69 makes it step 2 of
`end_doc()`. It reads the same block stream `OwdocReader` produces, which is why one
implementation serves a parse and `ow doc verify <archive>` both.

**`.owdoc` is not the canonical form** -- the `.owstore` is. An archive is a lossless projection
of one document's rows out of one store, single-document and single-generation (03:2503), held to
`import(export(store)) == store` in CI. That gate is **G28** and not G6: ADR-2 decision 4 gives
charter D2's unnumbered CI gate a number and says "Do not cite `G6` for the archive round-trip",
because G6 is `ow schema emit --check` and is not renumbered (00-vision.md:706, `tools/gates.toml`
G28's own comment).

Four modules, one plan section each and no name in two of them (INV-21).

* `frames.py` -- 03 section 13.3: `Frame`, the 8,192-block target, `frames.json` and the binary
  search that makes "give me pages 300-320" inflate two or three members.
* `manifest.py` -- 03 sections 13.2 and 15.1: `manifest.json`, the only mandatory member, and the
  version refusal that has no `--force`.
* `owdoc.py` -- 03 sections 3.1, 3.2 and 13.2: the twenty-nine wire keys, the byte-stable writer,
  the bounded seeking reader, `export` and `import_`.
* `owcheck.py` -- glossary.md:855 plus 03:2233 and 03:1027: the six structural clauses, as a
  report rather than an exception.

Still owed by P2. `import(export(store)) == store` in its G28 form needs the real SQLite store
(W2.3), so this wave's round trip runs against a hand-written in-memory `DocSink`; the archive
half is complete and the store half is the next wave's. `tools/wirekeys.toml` (03:648) does not
exist in the tree, so `owdoc.WIRE_KEYS` is currently the twenty-nine keys' only written home and
nothing diffs it. The exploded `.owdoc.d/` form (03:2521) writes members to disk and is
therefore `confine()`'s caller, which waits on `omniweave_core.paths`.

THE IMPORTS BELOW ARE WHY THIS FILE IS NOT EMPTY, AND THEY ARE NOT A G17 PROBLEM. `archive` is
one of the nine lazy subpackages, and G17's assertion is that `import omniweave_core` does not
reach it -- which holds because `omniweave_core/__init__.py` imports none of the nine and exposes
them through `__getattr__`. Importing `omniweave_core.archive` is what a caller does ON PURPOSE.
This home is no longer empty, so `test_core_eager_surface.py`'s `FILLED_HOMES` needs the row
`"archive": "P2 W2.5 -- the .owdoc codec, writer, reader and owcheck"`; that file is not this
wave's to edit. Reported.
"""

from __future__ import annotations

from omniweave_core.archive.frames import (
    FRAME_TARGET_BLOCKS,
    Frame,
    frames_overlapping,
    parse_frames_json,
)
from omniweave_core.archive.manifest import (
    CONTAINER_VERSION,
    DIGEST_RECIPE,
    MIN_READER,
    MODEL_VERSION,
    Manifest,
    require_readable,
)
from omniweave_core.archive.owcheck import (
    Clause,
    ClauseResult,
    ClauseState,
    Generation,
    OwcheckReport,
    Violation,
    block_facts,
    owcheck,
    owcheck_archive,
)
from omniweave_core.archive.owdoc import (
    WIRE_KEYS,
    AssetRow,
    BlockExport,
    BlockImport,
    DocHeader,
    ExportSource,
    GridRow,
    OwdocReader,
    PartRow,
    RelRow,
    ViewRow,
    export,
    import_,
    open_owdoc,
)

__all__ = [
    "CONTAINER_VERSION",
    "DIGEST_RECIPE",
    "FRAME_TARGET_BLOCKS",
    "MIN_READER",
    "MODEL_VERSION",
    "WIRE_KEYS",
    "AssetRow",
    "BlockExport",
    "BlockImport",
    "Clause",
    "ClauseResult",
    "ClauseState",
    "DocHeader",
    "ExportSource",
    "Frame",
    "Generation",
    "GridRow",
    "Manifest",
    "OwcheckReport",
    "OwdocReader",
    "PartRow",
    "RelRow",
    "ViewRow",
    "Violation",
    "block_facts",
    "export",
    "frames_overlapping",
    "import_",
    "open_owdoc",
    "owcheck",
    "owcheck_archive",
    "parse_frames_json",
    "require_readable",
]
