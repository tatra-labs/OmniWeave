"""G28: `import(export(store)) == store`, against the REAL `DocSink` and a REAL `.owstore`.

`00-vision.md:708` (V01-7) states the criterion and `_plan/adr/0002-invariant-and-gate-registers.md`
decision 4 gives it its number: **G28**, not G6. Two live documents still print G6 for it --
`02-architecture.md:249` ("a lossless projection held to `import(export(store)) == store` (G6)")
and `03-document-model.md:2519` ("**CI gate G6:** `import(export(store)) == store` over the
fixture corpus, compared after a `block_id` remap") -- and both are the charter `:72` credit that
erratum E31 supersedes. `tools/gates.toml`'s G28 row is right and this file cites G28. Confirmed,
not overturned: 00-vision.md:848-856 answers V-Q8 in as many words, and `G6` is
`ow schema emit --check` at four other correct sites.

W2.5 (`16-roadmap.md:418`) tested this property against a hand-written in-memory `FakeSink`
because `DocSink` did not exist. It exists. This is the real form: a document goes into a real
store through `DocSink`, out through `export`, back in through `import_` into a **second, fresh**
store through a second real `DocSink`, and the two stores are compared.

THE EQUALITY, STATED, AND WHY EACH EXCLUDED FIELD IS EXCLUDED
-------------------------------------------------------------
`03-document-model.md:2519` supplies the form in its own words: the comparison is *"after a
`block_id` remap"*. So the equality is **not** row-for-row over the `block` table -- import mints
fresh `block_id`s (03:1083: the archive "never contains a `block_id`"; 03:2510 repeats it) and a
comparison over surrogates would be either trivially false or fixed up by hand. The equality
compared here is over the **wire projection**: every record the `.owdoc` carries, keyed by `addr`.
Concretely, `_records()` re-reads both stores through one exporter and compares the resulting
member maps, which is also the shape `16-roadmap.md:550` gives G19 ("diffing the `.owdoc`
**exports**") and `07-store-and-retrieval.md:3097` calls "what makes the G19 export-diff sound".

Compared, because the archive carries them and the second store must reproduce them:

* `i` (`addr`), `c` (`cite`), `pa` (parent `addr`), `p`, `o`, `k`, `rk`, `ly`, `lb`, `t`, `ts`,
  `os`, `q`, `qt`, `tr`, `mt`, `sc`, `cd`, `ld`, `rm`, `rb`, `st`, `dc`, `pl`, `x` -- the
  twenty-nine wire keys of 03 section 3.1 minus `pd`, `oo` and `od` below;
* every `rel` as `(src addr, dst addr, kind, trust, score)`; every `grid` with its origin cells
  and their spans; every `mark` as `[a, b, kind, value]`; every `part` and `asset` row plus the
  bytes of each retained member; and `manifest.json` whole, including `gen`, `status`, `source`,
  `declared` and `achieved`.

`addr` and `cite` are compared even though the importing store **re-mints** both: `add_block`
assigns them (03:60-70, the parse sequence) and the archive's `c` cannot reach it -- see
`_ImportSink`. That they agree anyway is the property `16-roadmap.md:426-431` freezes ("the
`cite` grammar and `doc.next_cite_n` minting"), and `03:2521` is where the plan says why `c`
had to become a wire key at all: a cite is durable and yesterday's citation must still resolve.

**Agreement here is an assertion about the replay ORDER and about nothing else, and this
paragraph used to claim more than that.** It read "not a tautology --
`test_a_changed_cite_in_the_source_turns_the_comparison_red` proves the comparison sees a cite".
That test proves `_records()` reads the `c` KEY; it proves nothing about whether `import_`
carries the archive's `c`, and `import_` provably does not get the chance to -- `_ImportSink`
pops `x["x.ow.cite"]` on the way past, so both stores' `cite` columns are two runs of one
minting function over two identical block orders. An importer that threw the durable cite away
outright (`cite=Cite("d1#1")` in `read_block_record`) was green over every test in this file.
The claim is cashed in section 6, at the one place the archive's cite is observable:
`test_import_hands_the_sink_the_durable_cite_the_archive_carries` reads the draft `import_`
builds, before any sink has re-minted anything.

NOT compared, each for a stated reason:

* **`block_id`, `parent_id`, `producer_id`, `asset_id`, `table_id`, `mark_id`** -- surrogates. The
  archive holds none of them (03:1083, 03:2510) and 03:2519's "after a `block_id` remap" is the
  plan saying so. The projection is addressed by `addr` throughout, which IS the remap.
* **`doc_ord`** -- corpus-local (`0001_init.sql`'s `doc` comment). It is not a wire key; it rides
  inside `cite` (`d1#4`), which IS compared.
* **`pd`, `oo`, `od`** -- the producer index and the three ownership columns. `DocSink` stamps
  `producer_id`, `origin_operator`, `origin_driver` and `driver_schema_v` from ITS OWN
  construction and a driver may not write them (INV-6, INV-7; `doc.py`'s `add_block`). Both sinks
  here are built with the same identity, so comparing these three would compare two constructor
  calls in this file rather than the round trip -- an equality whose two sides come from one
  source cannot fail, which is the trap `test_store_integration.py` records at its `cite`
  assertion. They are dropped from the projection by `_comparable()` and the loss is pinned by
  `test_the_three_ownership_columns_are_stamped_by_the_sink_and_not_read_from_the_archive`.
* **`store_ref`** -- a `cas://` path into ONE store's CAS. The archive carries `present` plus the
  digest (03:2494) and both are compared.
* **the whole `page` row** -- `page_kind`, `label`, `w_mpt`, `h_mpt`, `rotation`, `quad_origin`,
  `method`, `status`. 03:2485-2497's member tree has no `pages` member and `import_` builds a
  `PageRecord` from `{"page", "gen"}` alone, so page geometry cannot survive an export. `page` is
  `[SOR]` in the read contract at 03:2474, so this is a real gap in the container and not a
  choice made here; `test_the_page_row_is_what_the_container_cannot_carry` pins it so that closing
  it is visible.

THE CORPUS HALF, AND WHAT A CORPUS REACHES THAT A HAND-BUILT DOCUMENT CANNOT
---------------------------------------------------------------------------
G28's assertion is `import(export(store)) == store` **over the fixture corpus**, and until
section 5 landed only the left half of that sentence ran here: every document above is built by
hand, six blocks and one frame. Section 5 adds the right half. `fixtures/gen/gen_5000p_pdf.py`
synthesises a real multi-page PDF, `tools/p2_stub_parse.py` parses it out of the bytes and drives
a real `DocSink`, and then the same export -> import -> re-export path runs over the result.

`CORPUS_PAGES = 127` is not a round number; its docstring gives the one arithmetic that picks it
and the measurement that confirms it fits. What the corpus case reaches that nothing above it
does, and each of these is a way a round trip breaks:

* **a frame boundary crossed.** 8,256 blocks against `FRAME_TARGET_BLOCKS = 8_192`, so
  `blocks/000000.ndjson` and `blocks/000001.ndjson` both exist and `frames.json` carries two
  records with two independent `sha256`s. A one-frame fixture does not test the index the Frame
  exists for (03:2528-2536), and the crossing is what found the defect named below.
* **127 pages**, so `DocSink`'s per-page transaction commits 127 times and `_ImportSink`'s
  deferred `end_page` runs across a real page count instead of twice.
* **6,858 real Grid cells** across 127 tables, positioned by `_cell_positions`' geometry rather
  than by a hand-written `CellPos` list, and rebuilt on import through the `addr -> BlockId` map
  at that scale.
* **real `OriginBytes` into the source file** on all 8,001 text blocks, with `os_a` and `os_b`
  computed from where each literal actually sits in the PDF.
* **escaped literals.** 25 cells carry `(` and `)` (`ESCAPED_CELL_PAGE_STRIDE`), so their escaped
  extent is longer than their text and the stub demotes them to `Quote.NORMALIZED`.
* **coalesced text.** 1,016 paragraph blocks, each assembled from four content-stream runs, whose
  covering `OriginBytes` necessarily spans the operator bytes between the runs -- exactly the
  case `Quote.VERBATIM` may not claim.

**What the corpus half found.** The Frame index cannot name a boundary that falls inside a page.
`frames.json` brackets a frame by `(lo_page, lo_ord)`..`(hi_page, hi_ord)` (03:2483) and
`frames._check_monotonic` refuses two frames whose brackets touch, but `ord` is dense from 0
**among siblings** (03:279, :2188), so `(page, ord)` is not unique within a page and a frame
closed mid-page routinely produces `hi == lo`. It does here, at `(126, 0)`: the source export is
a well-formed archive that its own reader will not parse the frame index of. `import_` is
tolerant (03:2516), so every block still arrives -- the whole cost is one `OW_MODEL` warning,
which lands in the imported store's `diag` table and comes back out in the re-export. That is the
ONLY thing the corpus round trip does not reproduce, and
`test_the_frame_index_cannot_name_a_boundary_that_falls_inside_a_page` pins it to the byte.

**Why `_sink` and `_import_archive` take a `driver`.** Both sides of the corpus trip declare
`parse.pdf.stub`, because `od` is one of the three columns `_comparable()` drops: a mismatch
there is invisible to the projection equality and yet moves every block record's bytes, so
`test_the_two_exports_are_byte_identical` would fail while every projection assertion passed.
That is the exclusion list's price, stated as a parameter rather than discovered.

WHAT SECTION 6 IS FOR, AND WHAT IT FOUND
----------------------------------------
Sections 1 and 5 build 8,262 blocks between them and populate two of the ten OPTIONAL wire keys.
Eight of the other eight -- `rk`, `lb`, `ts`, `q`, `sc`, `ld`, `dc`, `x` -- are null on every
record of both documents, and three of the five `os` variants never occur at all, so the
projection equality compared them to themselves as `null == null` and the exclusion list above
promised more than the file delivered. Blanking all eight inside `archive/owdoc.py`'s
`block_record()` at once left every assertion in sections 1 through 5 green; so did deleting the
`"ts"` line outright. Section 6 adds a THIRD hand-built document that carries all of them and
all five variants, and pins each against a literal at BOTH ends of the trip rather than against
the other end.

It found a defect in this file: `StoreExportSource`'s `nodepath` decoder parsed `os_path` with
`json.loads`, and `os_path` is the dot-joined `'0.3.1.7'` of `spans.py:518` and
`store/doc.py:457`. Exporting any `OriginNodePath` block raised `JSONDecodeError`. It had never
been called, because no block in either document has that origin.

Specified in 00-vision.md:708 (V01-7), 02-architecture.md:249, 03-document-model.md:1083, :2485-
2497 (the container), :2519 (the comparison) and :2528-2536 (the Frame), 16-roadmap.md:418 (W2.5),
:442 (the P2 demo the corpus comes from) and :550 (G19's export diff), ADR-2 decision 4, and
`tools/gates.toml`'s G28 row.

ON `sqlite3` IN A TEST. INV-17 confines `import sqlite3` to `store/`. This file drives two real
`.owstore` files: it reads the `block`, `rel`, `mark`, `table_meta`, `cell`, `part`, `asset` and
`doc` rows out of one store to build an `ExportSource`, and it perturbs a column with UPDATE to
prove the comparison is not vacuous. Neither is expressible through the four frozen protocols --
`Reader` is the six-method RETRIEVAL boundary and carries no per-document row access
(`owdoc.py`'s `ExportSource` says exactly this) -- so the connection is taken directly, with the
`# noqa: TID251` the invariant's own carve-out for tests allows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sqlite3  # noqa: TID251 -- see the module docstring: this file drives two REAL stores.
import struct
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Final

import pytest
from omniweave_core.archive import (
    FRAME_TARGET_BLOCKS,
    AssetRow,
    BlockExport,
    DocHeader,
    GridRow,
    OwdocReader,
    PartRow,
    RelRow,
    export,
    import_,
    open_owdoc,
    owcheck_archive,
)
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import ModelError
from omniweave_core.model import (
    Addr,
    BlockId,
    Capabilities,
    Cite,
    Kind,
    Layer,
    Method,
    PageKind,
    Quad,
    Quote,
    RelKind,
    Trust,
)
from omniweave_core.model.block import Block, BlockDraft, CellPos, Mark
from omniweave_core.model.grid import build_grid
from omniweave_core.model.records import AssetDraft, Diag, DocRecord, PageRecord
from omniweave_core.model.spans import (
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    TextSpan,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink

NOW_NS = 1_757_400_000_000_000_000
"""A fixed timestamp. `time.time()` is banned in library code and injected everywhere in the
store, so a test that read the ambient clock would assert against a value production cannot
produce. The value is `test_store_integration.py`'s, so two suites agree on one epoch."""

OPERATOR = "parse.pdf"
ORIGIN_DRIVER = "parse.pdf.pdfium"
DRIVER_SCHEMA_V = 1

BODY_TEXT = "termination for convenience"
CELL_TEXTS = ("span", "a", "b")

ASSET_BYTES = b"\x89PNG\x1a\r" + b"asset-bytes-with-no-lf!" + b"\xff\x00\x01\x02"
"""The asset payload. It contains no `0x0A`, and THAT IS NO LONGER LOAD-BEARING.

It was. `BlobStore._create_tmp` used to open the staging file with
`os.open(..., O_WRONLY | O_CREAT | O_EXCL)` and no `os.O_BINARY`, which on Windows is TEXT mode:
every `\\n` in a blob was written as `\\r\\n`, so the CAS stored bytes that did not hash to their
own name and `add_asset` refused the re-import with `OW_ASSET_DIGEST_MISMATCH`. The flag has since
landed -- `blobs.py`'s `_O_BINARY` is `getattr(os, "O_BINARY", 0)` and is in the flags, with a
comment saying it is not a portability ornament -- so the constraint on this constant is spent.

The evidence is in section 5 rather than in a claim: the corpus's retained `part` is the whole
generated PDF, 748,754 bytes of newline-terminated ASCII, and
`test_the_corpus_exports_are_byte_identical_except_where_the_frame_defect_lands` puts it through
two CAS roots and back and compares it to `corpus.pdf.read_bytes()`. A newline that grew a
carriage return anywhere in that path would fail there. This payload is left as it is because
changing it would change nothing; the paragraph is corrected because it no longer describes the
tree."""

ASSET_SHA256 = hashlib.sha256(ASSET_BYTES).hexdigest()
"""The asset's content address, which is also its member name under `assets/cas/`.

Derived from this file's own `ASSET_BYTES` and never read back out of a store or a manifest, so
`FIXTURE_MEMBERS` names the member the writer must produce rather than the one it did produce.
"""

PART_SHA256 = bytes(range(32))
PART_BYTES = 4096


# ---------------------------------------------------------------------------------------------
# 1. A store, and a document written into it. The helpers are `test_store_integration.py`'s.
# ---------------------------------------------------------------------------------------------

FLOOR = Capabilities(
    spatial="none",
    origin_span="none",
    text_span=False,
    marks=False,
    reading_order="raster",
    sections="none",
    tables="none",
    math=frozenset(),
    assets="none",
    asset_origin=False,
    notes="none",
    confidence="none",
    furniture="destroyed",
    round_trip="none",
)
"""The all-absent capability floor. All fifteen fields are required (03 section 4.4)."""


def _producer(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('parse.pdf', 1, 'abc123', X'00')"
    )
    connection.commit()
    return int(cursor.lastrowid or 0)


def _fresh(root: Path, name: str) -> tuple[Path, Path, int]:
    """A migrated `.owstore` plus its own CAS root and one `producer` row."""
    path = root / name
    cas = root / f"{name}.cas"
    cas.mkdir()
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        producer_id = _producer(connection)
    finally:
        connection.close()
    return path, cas, producer_id


def _doc_record(key: int, uri: str) -> DocRecord:
    return DocRecord(
        doc_ord=0,
        doc_key=bytes([key]) * 16,
        gen=0,
        source_sha256=bytes([key]) * 32,
        normalizer="canonical/1",
        uri=uri,
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({}),
        source_bytes=4096,
        status="ok",
        page_count=2,
        model_version="1.1",
        declared=FLOOR,
        achieved=FLOOR,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page_record(page: int) -> PageRecord:
    return PageRecord(
        page=page,
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=595_280,
        h_mpt=841_890,
        rotation=0,
        quad_origin="topleft",
        method=Method.NATIVE,
        status="ok",
    )


def _sink(
    thread: Any,
    cas: Path,
    producer_id: int,
    *,
    driver: str = ORIGIN_DRIVER,
    score_kinds: frozenset[str] = frozenset(),
) -> DocSink:
    """A real `DocSink` over `thread`. Two parameters, each for exactly one reason.

    `origin_driver` reaches the wire as `od`, which `_comparable()` DROPS -- so two sinks that
    disagree about it produce two projections that compare equal and two archives that are not
    byte-identical. The corpus trip in section 5 is driven by `tools/p2_stub_parse.py` and must
    therefore stamp `parse.pdf.stub` on BOTH sides; the hand-built trips keep `ORIGIN_DRIVER`.

    `score_kinds` is `DocSink`'s stand-in for `tools/scorekinds.toml` (`store/doc.py`'s module
    docstring: the register is a constructor parameter because the file is not in the tree). It
    defaults to EMPTY, which is the fail-closed direction Q-G10 asks for and which means a
    scored draft raises -- so the rich document of section 6, and only it, names its scale.
    """
    return DocSink(
        thread,
        producer_id=producer_id,
        origin_operator=OPERATOR,
        origin_driver=driver,
        driver_schema_v=DRIVER_SCHEMA_V,
        blobs=BlobStore(cas),
        score_kinds=score_kinds,
    )


class _CellDraft:
    """03:337-338's `CellDraft`: `id: BlockId; pos: CellPos`, read structurally by `build_grid`.

    `model/block.py` has not declared the type -- `model/grid.py`'s `_cell_position` says so and
    reports it -- so `build_grid`'s callers supply the two attributes. This is one of them.
    """

    __slots__ = ("id", "pos")

    def __init__(self, ident: int, pos: CellPos) -> None:
        self.id = ident
        self.pos = pos


def _write_source_document(root: Path) -> tuple[Path, Path]:
    """Two pages, a merged table, marks, a rel, an asset and an unretained part.

    Everything the round trip must carry, and each thing is there because the archive has a
    member or a wire key for it: two pages exercise `_by_page`'s per-page transaction, the table
    exercises `grids.ndjson` and `cell`'s spans, the marks exercise the frame-aligned
    `marks/NNNNNN.ndjson`, the rel exercises `rels.ndjson`'s `addr` endpoints, the asset
    exercises `assets/cas/` and the part exercises 03:2494's `present: false`.
    """
    path, cas, producer_id = _fresh(root, "source.owstore")
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = _sink(thread, cas, producer_id)
        sink.begin_doc(_doc_record(7, "file:///corpus/contract.pdf"))

        sink.begin_page(_page_record(0))
        root_block = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        body = sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root_block,
                text=BODY_TEXT,
                origin=OriginBytes(
                    part="file", start=0, length=len(BODY_TEXT), codec="utf-8/strict"
                ),
                span=TextSpan(0, len(BODY_TEXT)),
                marks=[Mark(0, 11, "bold", None), Mark(12, 15, "italic", None)],
            )
        )
        # `blob=None` is 03:2494's `present: false`: the path, digest and length travel and the
        # bytes do not, which is what `[store] retain_parts` decides.
        sink.add_part("file", None, PART_SHA256, PART_BYTES)
        sink.end_page({})

        sink.begin_page(_page_record(1))
        table = sink.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root_block,
            )
        )
        cells: list[_CellDraft] = []
        geometry = ((0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1))
        for (row, column, row_span, col_span), text in zip(geometry, CELL_TEXTS, strict=True):
            position = CellPos(r=row, c=column, row_span=row_span, col_span=col_span)
            cell_id = sink.add_block(
                BlockDraft(
                    kind=Kind.TABLE_CELL,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.NORMALIZED,
                    parent=table,
                    text=text,
                    cell=position,
                    origin=OriginBytes(
                        part="file", start=0, length=len(text), codec="utf-8/strict"
                    ),
                )
            )
            cells.append(_CellDraft(cell_id, position))
        sink.add_grid(
            table,
            build_grid(
                cells,
                header_rows=1,
                kind="data",
                recon=("native_xml", 0.9),
                diag=lambda _d: None,
            ),
        )
        sink.add_rel(body, table, RelKind.CAPTION_OF, trust=Trust.INFERRED)
        sink.add_asset(
            AssetDraft(
                media_type="image/png",
                sha256=hashlib.sha256(ASSET_BYTES).digest(),
                byte_len=len(ASSET_BYTES),
                origin_part="media/img1.png",
            ),
            io.BytesIO(ASSET_BYTES),
        )
        sink.end_page({})
        sink.end_doc("ok")
    return path, cas


# ---------------------------------------------------------------------------------------------
# 2. The store -> archive adapter. `export()` takes an `ExportSource`, never a connection.
# ---------------------------------------------------------------------------------------------


def _unquad(blob: bytes) -> tuple[int, ...]:
    """`quad`'s column encoding: 8 x i32 LE (`0001_init.sql`'s `block.quad` comment)."""
    return struct.unpack("<8i", blob)


_ORIGIN_DECODERS = MappingProxyType(
    {
        "bytes": lambda r: OriginBytes(
            part=r["os_part"], start=r["os_a"], length=r["os_b"], codec=r["os_codec"]
        ),
        "nodepath": lambda r: OriginNodePath(
            part=r["os_part"], path=tuple(int(step) for step in r["os_path"].split("."))
        ),
        "glyphs": lambda r: OriginGlyphs(
            part=r["os_part"], extractor=r["os_extractor"], start=r["os_a"], length=r["os_b"]
        ),
        "pixels": lambda r: OriginPixels(page=r["page"], quad=Quad(*_unquad(r["quad"]))),
        "none": lambda _r: OriginNone(),
    }
)
"""The seven `os_*` columns back to one `OriginSpan`, per 03 section 7.2's mapping.

The inverse of what `DocSink.add_block` writes, and the reason `os_b` is passed as `length` and
`ts_b` as a range end: 03:671-675 makes the two different quantities and reusing one letter for
both is the bug that section says costs a week.

**`nodepath` is a DOT-JOINED STRING and was decoded here with `json.loads` until section 6
landed.** `spans.py:518` fixes the storage form as `os_path = '0.3.1.7'` and
`store/doc.py:457` writes exactly `".".join(str(step) for step in origin.path)`, so
`json.loads("1.4.3")` raises `JSONDecodeError: Extra data`. This adapter could not export any
`nodepath` block at all. Nothing caught it because neither the hand-built document of section 1
nor the 127-page corpus of section 5 emits one: every block in both carries `bytes` or `none`,
so three of the five `os` variants had never travelled a real store round trip.
`_write_rich_document` emits all five and
`test_all_five_origin_span_variants_survive_a_real_store_round_trip` is where they are cashed.
"""


class StoreExportSource:
    """One document's committed generation, read out of a real `.owstore` as an `ExportSource`.

    **This adapter belongs in the tree and does not yet exist there.** `export(store, path)`
    (02-architecture.md:249) is typed against `ExportSource`, whose own docstring names the type
    that will satisfy it structurally: `Doc`, the lazy read handle of 03:2584-2606. `Doc` is not
    in the tree, so G28 has no shipped way to point `export()` at a store and this class is the
    stand-in. It reads `[SOR]` tables only (03:2474) and it is the SAME code for both stores, so
    a difference between the two projections is a difference between the stores.
    """

    def __init__(self, connection: sqlite3.Connection, cas: Path, doc_ord: int = 1) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._cas = cas
        self._doc_ord = doc_ord
        row = connection.execute("SELECT * FROM doc WHERE doc_ord = ?", (doc_ord,)).fetchone()
        if row is None:
            message = f"no doc row at doc_ord {doc_ord}"
            raise AssertionError(message)
        self._doc = row
        self._gen = int(row["gen"])
        self._enum: dict[str, dict[int, str]] = {}
        for domain, ordinal, name in connection.execute("SELECT domain, ord, name FROM enum_val"):
            self._enum.setdefault(domain, {})[ordinal] = name

    # -- 1/9 ---------------------------------------------------------------------------------

    def header(self) -> DocHeader:
        row = self._doc
        return DocHeader(
            doc_key=bytes(row["doc_key"]).hex(),
            gen=self._gen,
            status=row["status"],
            source={
                "uri": row["uri"],
                "media_type": row["media_type"],
                "format": row["format"],
                "source_sha256": bytes(row["source_sha256"]).hex(),
                "source_bytes": row["source_bytes"],
                "normalizer": row["normalizer"],
                "format_evidence": json.loads(row["format_evidence"]),
                "page_count": row["page_count"],
                "model_version": row["model_version"],
            },
            declared=json.loads(row["declared"]),
            achieved=json.loads(row["achieved"]),
            producers=self._producers(),
            confidence=json.loads(row["confidence"]),
            timings_ms=json.loads(row["timings_ms"]),
            x=json.loads(row["x"]),
        )

    def _producers(self) -> list[dict[str, Any]]:
        """`manifest.producers[]`: the reproduction tuples this generation's blocks name."""
        return [
            {
                "operator": row["operator"],
                "op_version": row["op_version"],
                "code_fingerprint": row["code_fingerprint"],
            }
            for row in self._connection.execute(
                "SELECT DISTINCT p.producer_id, p.operator, p.op_version, p.code_fingerprint "
                "FROM producer p JOIN block b ON b.producer_id = p.producer_id "
                "WHERE b.doc_ord = ? AND b.gen = ? ORDER BY p.producer_id",
                (self._doc_ord, self._gen),
            )
        ]

    def _producer_index(self) -> dict[int, int]:
        """`pd` is an INDEX into `manifest.producers[]` and never a `producer_id` (03:666)."""
        rows = self._connection.execute(
            "SELECT DISTINCT p.producer_id FROM producer p JOIN block b "
            "ON b.producer_id = p.producer_id WHERE b.doc_ord = ? AND b.gen = ? "
            "ORDER BY p.producer_id",
            (self._doc_ord, self._gen),
        ).fetchall()
        return {int(row["producer_id"]): index for index, row in enumerate(rows)}

    def _addresses(self) -> dict[int, str]:
        return {
            int(row["block_id"]): row["addr"]
            for row in self._connection.execute(
                "SELECT block_id, addr FROM block WHERE doc_ord = ? AND gen = ?",
                (self._doc_ord, self._gen),
            )
        }

    # -- 2/9 ---------------------------------------------------------------------------------

    def blocks(self) -> Any:
        """`(page, ord)` order, which is a Frame's order by definition (03:2528)."""
        index = self._producer_index()
        marks = self._marks()
        rows = self._connection.execute(
            "SELECT * FROM block WHERE doc_ord = ? AND gen = ? ORDER BY page, ord, block_id",
            (self._doc_ord, self._gen),
        ).fetchall()
        for row in rows:
            os_kind = self._enum["origin_span_kind"][int(row["os_kind"])]
            block = Block(
                id=BlockId(int(row["block_id"])),
                addr=Addr(row["addr"]),
                cite=Cite(row["cite"]),
                doc_ord=int(row["doc_ord"]),
                gen=int(row["gen"]),
                page=int(row["page"]),
                parent=None if row["parent_id"] is None else BlockId(int(row["parent_id"])),
                ord=int(row["ord"]),
                kind=Kind(self._enum["kind"][int(row["kind"])]),
                raw_kind=row["raw_kind"],
                layer=Layer(self._enum["layer"][int(row["layer"])]),
                label=row["label"],
                text=row["text"],
                content_digest=bytes(row["content_digest"]),
                layout_digest=(
                    None if row["layout_digest"] is None else bytes(row["layout_digest"])
                ),
                revision=int(row["revision"]),
                quad=None if row["quad"] is None else Quad(*_unquad(row["quad"])),
                origin=_ORIGIN_DECODERS[os_kind](row),
                span=None if row["ts_a"] is None else TextSpan(row["ts_a"], row["ts_b"]),
                producer_id=int(row["producer_id"]),
                method=Method(self._enum["method"][int(row["method"])]),
                trust=Trust(int(row["trust"])),
                quote=Quote(int(row["quote"])),
                score=row["score"],
                score_kind=row["score_kind"],
                origin_operator=row["origin_operator"],
                origin_driver=row["origin_driver"],
                driver_schema_v=int(row["driver_schema_v"]),
                restriction_bits=int(row["restriction_bits"]),
                marks=tuple(marks.get(int(row["block_id"]), ())),
                tombstoned=bool(row["state"]),
                x=MappingProxyType(json.loads(row["x"])),
            )
            yield BlockExport(
                block=block,
                producer=index[int(row["producer_id"])],
                payload=None if row["payload"] is None else json.loads(row["payload"]),
                decision_id=row["decision_id"],
            )

    def _marks(self) -> dict[int, list[Mark]]:
        marks: dict[int, list[Mark]] = {}
        for row in self._connection.execute(
            "SELECT m.block_id, m.a, m.b, m.kind, m.value FROM mark m "
            "JOIN block b ON b.block_id = m.block_id WHERE b.doc_ord = ? AND b.gen = ? "
            "ORDER BY m.block_id, m.a, m.b, m.mark_id",
            (self._doc_ord, self._gen),
        ):
            value = None if row["value"] is None else json.loads(row["value"])
            marks.setdefault(int(row["block_id"]), []).append(
                Mark(int(row["a"]), int(row["b"]), row["kind"], value)
            )
        return marks

    # -- 3/9 ---------------------------------------------------------------------------------

    def rels(self) -> Any:
        index = self._producer_index()
        address = self._addresses()
        for row in self._connection.execute(
            "SELECT * FROM rel WHERE doc_ord = ? AND gen = ? ORDER BY src_id, dst_id, kind",
            (self._doc_ord, self._gen),
        ):
            yield RelRow(
                src=Addr(address[int(row["src_id"])]),
                dst=Addr(address[int(row["dst_id"])]),
                kind=RelKind(self._enum["rel_kind"][int(row["kind"])]),
                producer=index[int(row["producer_id"])],
                trust=Trust(int(row["trust"])),
                origin_operator=row["origin_operator"],
                score=row["score"],
                score_kind=row["score_kind"],
                x=json.loads(row["x"]),
            )

    # -- 4/9 ---------------------------------------------------------------------------------

    def grids(self) -> Any:
        """`table_meta` plus its ORIGIN `cell` rows. `grid_slot` is `[DER]` and never exported."""
        address = self._addresses()
        for row in self._connection.execute(
            "SELECT tm.* FROM table_meta tm JOIN block b ON b.block_id = tm.block_id "
            "WHERE b.doc_ord = ? AND b.gen = ? ORDER BY tm.block_id",
            (self._doc_ord, self._gen),
        ).fetchall():
            cells = tuple(
                (int(c["r"]), int(c["c"]), int(c["row_span"]), int(c["col_span"]))
                for c in self._connection.execute(
                    "SELECT r, c, row_span, col_span FROM cell WHERE table_id = ? ORDER BY r, c",
                    (row["block_id"],),
                )
            )
            yield GridRow(
                table=Addr(address[int(row["block_id"])]),
                n_rows=int(row["n_rows"]),
                n_cols=int(row["n_cols"]),
                row_len=tuple(json.loads(row["row_len"])),
                kind=self._enum["table_kind"][int(row["kind"])],
                cells=cells,
                header_rows=int(row["header_rows"]),
                header_cols=int(row["header_cols"]),
                recon_strategy=row["recon_strategy"],
                recon_score=row["recon_score"],
                has_merges=bool(row["has_merges"]),
                native_part=row["native_part"],
                native_sha256=(
                    None if row["native_sha256"] is None else bytes(row["native_sha256"]).hex()
                ),
            )

    # -- 5/9, 6/9 --------------------------------------------------------------------------

    def parts(self) -> Any:
        for row in self._connection.execute(
            "SELECT * FROM part WHERE doc_ord = ? ORDER BY path", (self._doc_ord,)
        ):
            digest = bytes(row["sha256"])
            present = row["store_ref"] is not None
            payload = self._cas_bytes(digest) if present else b""
            yield (
                PartRow(
                    path=row["path"],
                    sha256=digest.hex(),
                    byte_len=int(row["byte_len"]),
                    present=present,
                ),
                payload,
            )

    def assets(self) -> Any:
        roles = self._roles()
        for row in self._connection.execute(
            "SELECT * FROM asset WHERE doc_ord = ? ORDER BY asset_id", (self._doc_ord,)
        ):
            digest = bytes(row["sha256"])
            yield (
                AssetRow(
                    sha256=digest.hex(),
                    media_type=row["media_type"],
                    byte_len=int(row["byte_len"]),
                    present=True,
                    origin_part=row["origin_part"],
                    width=row["width"],
                    height=row["height"],
                    licence=row["licence"],
                    spdx=row["spdx"],
                    source_url=row["source_url"],
                    restriction_bits=int(row["restriction_bits"]),
                    roles=roles.get(int(row["asset_id"]), ()),
                ),
                self._cas_bytes(digest),
            )

    def _roles(self) -> dict[int, tuple[tuple[Addr, str], ...]]:
        found: dict[int, list[tuple[Addr, str]]] = {}
        for row in self._connection.execute(
            "SELECT ba.asset_id, b.addr, ba.role FROM block_asset ba "
            "JOIN block b ON b.block_id = ba.block_id WHERE b.doc_ord = ? AND b.gen = ? "
            "ORDER BY ba.asset_id, b.addr, ba.role",
            (self._doc_ord, self._gen),
        ):
            found.setdefault(int(row["asset_id"]), []).append((Addr(row["addr"]), row["role"]))
        return {key: tuple(value) for key, value in found.items()}

    def _cas_bytes(self, digest: bytes) -> bytes:
        with BlobStore(self._cas).open(digest) as handle:
            return handle.read()

    # -- 7/9, 8/9, 9/9 -----------------------------------------------------------------------

    def views(self) -> Any:
        """No views. `serialize()` is W2.8's and `view` is not an L2 table."""
        return ()

    def diags(self) -> Any:
        """`diag` rows for this generation, as the wire objects `diags.json` holds."""
        return [
            {
                "code": row["code"],
                "severity": row["severity"],
                "component": row["component"],
                "message": row["message"],
            }
            for row in self._connection.execute(
                "SELECT code, severity, component, message FROM diag "
                "WHERE doc_ord = ? AND gen = ? ORDER BY rowid",
                (self._doc_ord, self._gen),
            )
        ]

    def toc(self) -> Any:
        return ()


def _export_store(store: Path, cas: Path, target: Path) -> Path:
    connection = ow.connect_readonly(store)
    try:
        export(StoreExportSource(connection, cas), target)
    finally:
        connection.close()
    return target


# ---------------------------------------------------------------------------------------------
# 3. The archive -> store adapter, and the three things it has to work around.
# ---------------------------------------------------------------------------------------------


def _capabilities(raw: dict[str, Any]) -> Capabilities:
    """`declared`/`achieved` back off the JSON column. `math` and `forfeits` are sorted arrays."""
    return Capabilities(
        **{
            **raw,
            "math": frozenset(raw["math"]),
            "forfeits": frozenset(raw.get("forfeits", ())),
        }
    )


def _doc_record_from(header: DocHeader) -> DocRecord:
    """`DocHeader` -> `DocRecord`, the factory `import_(doc_record=...)` exists for."""
    source = header.source
    return DocRecord(
        doc_ord=0,
        doc_key=bytes.fromhex(header.doc_key),
        gen=0,
        source_sha256=bytes.fromhex(source["source_sha256"]),
        normalizer=source["normalizer"],
        uri=source["uri"],
        media_type=source["media_type"],
        format=source["format"],
        format_evidence=MappingProxyType(dict(source["format_evidence"])),
        source_bytes=source["source_bytes"],
        status=header.status,
        page_count=source["page_count"],
        model_version=source["model_version"],
        declared=_capabilities(dict(header.declared)),
        achieved=_capabilities(dict(header.achieved)),
        confidence=MappingProxyType(dict(header.confidence)),
        timings_ms=MappingProxyType(dict(header.timings_ms)),
    )


def _page_record_from(raw: dict[str, Any]) -> PageRecord:
    """`{"page", "gen"}` -> `PageRecord`, and every other field is invented here.

    That is the container's gap and not this factory's licence: 03:2485-2497 has no `pages`
    member, so `import_` has nothing but the page index to hand over. See the module docstring's
    exclusion list and `test_the_page_row_is_what_the_container_cannot_carry`.
    """
    return PageRecord(
        page=int(raw["page"]),
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=None,
        h_mpt=None,
        rotation=0,
        quad_origin=None,
        method=Method.NATIVE,
        status="ok",
    )


def _asset_draft_from(row: dict[str, Any]) -> AssetDraft:
    return AssetDraft(
        media_type=row["media_type"],
        sha256=bytes.fromhex(row["sha256"]),
        byte_len=int(row["byte_len"]),
        origin_part=row.get("origin_part"),
        width=row.get("width"),
        height=row.get("height"),
        licence=row.get("licence"),
        spdx=row.get("spdx"),
        source_url=row.get("source_url"),
    )


class _ImportSink:
    """A `DocSinkLike` over a real `DocSink`. Three workarounds, each a reported defect.

    1. **`import_` writes `x["x.ow.addr"]` and `x["x.ow.cite"]` onto every draft** (`owdoc.py`'s
       `_add_one`), because `BlockDraft` has no `cite` field and `add_block`'s signature is
       frozen. `DocSink._validate_x` refuses the reserved `ow` vendor segment outright, so the
       real sink raises `OW_MODEL` on the first block. This adapter pops both keys. The cite the
       archive carries is therefore DROPPED and the importing store re-mints its own; that the
       two agree is asserted separately and is a property of the replay order, not of the codec.
       Pinned by `test_the_real_docsink_refuses_the_reserved_x_slot_import_borrows`.
    2. **`import_` calls `add_rel`, `add_grid`, `add_part` and `add_asset` after the final
       `end_page()`**, which its own docstring says a `DocSink` "must therefore accept". The real
       `DocSink` calls `_require_page()` in all four. This adapter DEFERS each `end_page` until
       the next `begin_page` or `end_doc`, so the trailing calls land in the last page's still-
       open transaction -- which is also where 03:580 and :2231 put `add_grid` for a table that
       crosses a page break.
    3. **`_apply_grids` hands the sink a `GridRow`**, the archive's addr-keyed row type, while
       `DocSink.add_grid` takes a `Grid` whose `origins` are `BlockId`s. This adapter rebuilds the
       `Grid` through `build_grid`, the sole constructor (03:1880), off the `addr -> BlockId` map
       it accumulated at `add_block`.
    """

    def __init__(self, inner: DocSink) -> None:
        self._inner = inner
        self._ids: dict[str, int] = {}
        self._page_open = False
        self._stats: dict[str, Any] = {}

    def begin_doc(self, rec: Any) -> Any:
        return self._inner.begin_doc(rec)

    def begin_page(self, page: Any) -> None:
        self._commit_open_page()
        self._inner.begin_page(page)
        self._page_open = True

    def _commit_open_page(self) -> None:
        if self._page_open:
            self._inner.end_page(self._stats)
            self._page_open = False

    def add_block(self, b: BlockDraft) -> int:
        addr = b.x.pop("x.ow.addr", None)
        b.x.pop("x.ow.cite", None)
        block_id = self._inner.add_block(b)
        if addr is not None:
            self._ids[str(addr)] = int(block_id)
        return int(block_id)

    def add_marks(self, b: Any, marks: Any) -> None:
        self._inner.add_marks(b, marks)

    def add_grid(self, b: Any, g: GridRow) -> None:
        table = str(g.table)
        cells = [
            _CellDraft(
                self._ids[f"{table}/r{row}c{column}"],
                CellPos(r=row, c=column, row_span=row_span, col_span=col_span),
            )
            for row, column, row_span, col_span in g.cells
        ]
        self._inner.add_grid(
            b,
            build_grid(
                cells,
                header_rows=g.header_rows,
                header_cols=g.header_cols,
                kind=g.kind,
                recon=None if g.recon_strategy is None else (g.recon_strategy, g.recon_score),
                native=None,
                diag=lambda _d: None,
            ),
        )

    def add_rel(self, src: Any, dst: Any, kind: RelKind, **kwargs: Any) -> None:
        self._inner.add_rel(src, dst, kind, **kwargs)

    def add_asset(self, a: Any, blob: Any) -> int:
        return self._inner.add_asset(a, blob)

    def add_part(self, path: str, blob: Any, sha256: bytes, byte_len: int) -> None:
        self._inner.add_part(path, blob, sha256, byte_len)

    def diag(self, d: Any) -> None:
        self._inner.diag(
            Diag(
                code=d.get("code", "OW_MODEL"),
                severity=d.get("severity", "warning"),
                component=d.get("component", "archive.import"),
                message=d.get("message", d.get("detail", "")),
            )
        )

    def end_page(self, stats: Any) -> None:
        self._stats = dict(stats)

    def end_doc(self, status: str) -> Any:
        self._commit_open_page()
        return self._inner.end_doc(status)


def _import_archive(
    root: Path,
    archive: Path,
    name: str = "imported.owstore",
    *,
    driver: str = ORIGIN_DRIVER,
    score_kinds: frozenset[str] = frozenset(),
) -> tuple[Path, Path]:
    """Replay an archive into a SECOND, FRESH store through a second real `DocSink`.

    `driver` and `score_kinds` are passed straight to `_sink`, whose docstring says why each
    exists. `score_kinds` has to be given on BOTH sides of a trip whose blocks are scored: `sc`
    is a compared wire key, and an importing sink with an empty register refuses the draft
    outright rather than dropping the score.
    """
    path, cas, producer_id = _fresh(root, name)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        import_(
            archive,
            _ImportSink(_sink(thread, cas, producer_id, driver=driver, score_kinds=score_kinds)),
            doc_record=_doc_record_from,
            page_record=_page_record_from,
            asset_draft=_asset_draft_from,
        )
    return path, cas


# ---------------------------------------------------------------------------------------------
# 4. The comparison. `03-document-model.md:2519`: "compared after a `block_id` remap".
# ---------------------------------------------------------------------------------------------

_STAMPED_BY_THE_SINK = ("pd", "oo", "od")
"""The three wire keys `DocSink` writes from its own construction, not from the archive.

`producer_id`, `origin_operator`, `origin_driver` and `driver_schema_v` are host-stamped and a
driver may not write them (INV-6, INV-7). Both sinks in this file are built with one identity,
so an equality over `oo` and `od` would compare two constructor calls and could not fail.

**`pd` IS DIFFERENT AND THE SENTENCE ABOVE USED TO COVER IT WRONGLY.** `pd` is not a stamped
column read back: it is "an INDEX into `manifest.producers[]` and never a `producer_id`"
(03:666), computed by the exporter from `_producer_index()`'s `producer_id` ordering. Two sinks
sharing one identity make `oo` and `od` agree by construction; they do NOT make an index
arithmetic correct. Dropping `pd` from the projection with no other pin left
`"pd": export_row.producer + 1` green over every assertion in this file -- a block attributed to
the wrong producer, which is the provenance column INV-6 exists for. `pd` stays dropped, because
comparing it across the trip still compares two exporter runs; it is pinned instead against the
manifest it indexes, by `test_the_producer_index_is_a_position_in_the_manifests_producers_list`.
"""


def _comparable(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in _STAMPED_BY_THE_SINK}


def _records(archive: Path) -> dict[str, Any]:
    """Every member of an archive, parsed. The comparable projection of the store behind it.

    NDJSON members become lists of objects, JSON members become objects, and a blob member
    becomes its sha256 -- so a difference in an asset's bytes shows as a difference in one short
    string rather than as a wall of binary. `manifest.json` is included whole, which is what
    carries `gen`, `status`, `source`, `declared`, `achieved`, `parts[]` and `assets[]` into the
    comparison.
    """
    out: dict[str, Any] = {}
    with zipfile.ZipFile(archive) as package:
        for name in sorted(package.namelist()):
            payload = package.read(name)
            if name.endswith(".ndjson"):
                rows = [json.loads(line) for line in payload.splitlines() if line]
                out[name] = [_comparable(row) for row in rows]
            elif name.endswith(".json"):
                out[name] = json.loads(payload)
            else:
                out[name] = hashlib.sha256(payload).hexdigest()
    return out


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """One completed `import(export(store))`, and everything an assertion needs to reach."""

    source: Path
    source_cas: Path
    imported: Path
    imported_cas: Path
    exported: Path
    reexported: Path


@pytest.fixture
def trip(tmp_path: Path) -> RoundTrip:
    """source store -> `a.owdoc` -> imported store -> `b.owdoc`."""
    source, source_cas = _write_source_document(tmp_path)
    exported = _export_store(source, source_cas, tmp_path / "a.owdoc")
    imported, imported_cas = _import_archive(tmp_path, exported)
    reexported = _export_store(imported, imported_cas, tmp_path / "b.owdoc")
    return RoundTrip(source, source_cas, imported, imported_cas, exported, reexported)


def _blocks(store: Path) -> list[tuple[Any, ...]]:
    connection = ow.connect_readonly(store)
    try:
        return [
            tuple(row)
            for row in connection.execute(
                "SELECT b.addr, b.cite, b.page, b.ord, b.text, hex(b.content_digest) "
                "FROM block b JOIN doc d ON d.doc_ord = b.doc_ord "
                "WHERE b.gen = d.gen AND b.state = 0 ORDER BY b.addr"
            )
        ]
    finally:
        connection.close()


FIXTURE_BLOCKS: Final = 6
"""Blocks in `_write_source_document`'s one frame: the root, one paragraph, a table, three cells."""

FIXTURE_MEMBERS: Final = (
    f"assets/cas/{ASSET_SHA256[0:2]}/{ASSET_SHA256[2:4]}/{ASSET_SHA256}.png",
    "blocks/000000.ndjson",
    "frames.json",
    "grids.ndjson",
    "manifest.json",
    "marks/000000.ndjson",
    "rels.ndjson",
)
"""Every member `_write_source_document`'s export holds, in `sorted()` order.

No `parts/` member (the one `part` is 03:2494's `present: false`), no `diags.json`, no `toc.json`
and no `views/` -- the fixture writes none of them, and 03:2485-2497 makes every member but
`manifest.json` optional. The asset's member name is built from `ASSET_SHA256`, which is a digest
of THIS FILE's own `ASSET_BYTES` constant and not a value read back out of either store.

This tuple is what makes the equality below non-vacuous, and section 5's `CORPUS_MEMBERS` is the
same device for the corpus half. See
`test_a_document_written_through_docsink_survives_export_and_import_into_a_fresh_store`.
"""


# ---------------------------------------------------------------------------------------------
# The round trip itself
# ---------------------------------------------------------------------------------------------


def test_the_fixture_document_holds_what_the_round_trip_is_supposed_to_carry(
    trip: RoundTrip,
) -> None:
    """The count assertion 11-repo-layout.md section 6.8 demands of a gate that finds its inputs.

    Every comparison below is between two structures this file computes. If the exporter silently
    found nothing, both would be empty and every one of them would pass. These are the literals
    that make that impossible, and they are written down here rather than read out of either
    store.
    """
    records = _records(trip.exported)
    assert sorted(records) == list(FIXTURE_MEMBERS), sorted(records)
    assert len(records["blocks/000000.ndjson"]) == FIXTURE_BLOCKS, records["blocks/000000.ndjson"]
    assert len(records["marks/000000.ndjson"]) == 1, "one block carries marks"
    assert records["marks/000000.ndjson"][0]["m"] == [
        [0, 11, "bold", None],
        [12, 15, "italic", None],
    ]
    assert len(records["rels.ndjson"]) == 1
    assert len(records["grids.ndjson"]) == 1
    assert records["manifest.json"]["counts"] == {
        "blocks": 6,
        "pages": 2,
        "marks": 2,
        "rels": 1,
        "grids": 1,
        "diags": 0,
        "parts": 1,
        "assets": 1,
        "views": 0,
        "frames": 1,
    }


def test_a_document_written_through_docsink_survives_export_and_import_into_a_fresh_store(
    trip: RoundTrip,
) -> None:
    """G28. The two stores' wire projections are equal, member for member and record for record.

    This is 03:2519's equality: the comparison is addressed by `addr` throughout and never by
    `block_id`, which is what "after a `block_id` remap" means when the archive holds no
    `block_id` to remap (03:1083). See the module docstring for the field-by-field account.

    **THE MEMBER LIST AND THE RECORD COUNT ARE PINNED INSIDE THIS TEST, and that is not
    belt-and-braces.** The guard was `sorted(before) == sorted(after)` -- two lists read out of
    two archives, so both sides came from one source -- and the loop then ran over
    `sorted(before)`. Replacing the pair with two empty dicts left this test GREEN: an assertion
    over an empty collection passes and proves nothing, and the count literals that would have
    caught it live in a different test, with nothing tying them to this one. `FIXTURE_MEMBERS` is
    a literal written down in this file, so the loop cannot be empty and the equality cannot be
    vacuous. The corpus half already had this shape (`sorted(before) == list(CORPUS_MEMBERS)`);
    this is the hand-built half catching up to it.
    """
    before, after = _records(trip.exported), _records(trip.reexported)
    assert sorted(before) == list(FIXTURE_MEMBERS), sorted(before)
    assert sorted(after) == list(FIXTURE_MEMBERS), sorted(after)
    blocks = "blocks/000000.ndjson"
    assert len(before[blocks]) == FIXTURE_BLOCKS, "the source export found nothing to compare"
    assert len(after[blocks]) == FIXTURE_BLOCKS, "the re-export found nothing to compare"
    for member in FIXTURE_MEMBERS:
        assert before[member] == after[member], f"{member} differs across the round trip"


def test_the_two_exports_are_byte_identical(trip: RoundTrip) -> None:
    """The stronger form, and the one `16-roadmap.md:550` gives G19: a diff of two FILES.

    `_records()` compares parsed structures, which is what produces a readable failure. This
    compares the bytes, which is what INV-10 and 03:2505 actually promise, and it is a strictly
    stronger claim: member order, `frames.json`'s per-frame `sha256`, the manifest's printed key
    order and the pinned DOS-epoch `ZipInfo` all have to agree too.
    """
    assert trip.exported.read_bytes() == trip.reexported.read_bytes()


def test_the_imported_store_re_mints_the_cites_the_archive_carries(trip: RoundTrip) -> None:
    """`cite` is durable: yesterday's citation still resolves (03:2521, 16-roadmap.md:426-431).

    THE LITERALS ARE HERE ON PURPOSE. Asserting `source cites == imported cites` reads both sides
    out of a database, and `test_store_integration.py` records the mutation that proves such an
    assertion blind: shifting `_mint_cite`'s ordinal by one moved both sides together and stayed
    green. `d1#1` .. `d1#6` are written down where no mutation of the minting can reach them.
    """
    expected = [
        ("doc", "d1#1", 0, 0, None),
        ("p0/0", "d1#2", 0, 0, BODY_TEXT),
        ("p1/0", "d1#3", 1, 1, None),
        ("p1/0/r0c0", "d1#4", 1, 0, "span"),
        ("p1/0/r1c0", "d1#5", 1, 1, "a"),
        ("p1/0/r1c1", "d1#6", 1, 2, "b"),
    ]
    assert [row[:5] for row in _blocks(trip.source)] == expected
    assert [row[:5] for row in _blocks(trip.imported)] == expected


def test_the_imported_store_recomputes_the_same_content_digests(trip: RoundTrip) -> None:
    """`cd` is a wire key AND a host computation, so agreement is a real claim about both.

    `DocSink` recomputes every `content_digest` from the imported rows rather than trusting the
    archive's `cd`, so equality here says the digest inputs -- text, kind, the subtree -- all
    arrived. Compared per `addr`, because the `block_id`s differ by construction.
    """
    source = {row[0]: row[5] for row in _blocks(trip.source)}
    imported = {row[0]: row[5] for row in _blocks(trip.imported)}
    assert source == imported
    assert len(source) == 6


def test_owcheck_passes_on_the_imported_store(trip: RoundTrip) -> None:
    """The "lossless" half. `owcheck` over the imported store's own export (glossary.md:855).

    `ok` alone is not the assertion. `OwcheckReport.ok` is true when no clause FAILED, and a
    clause that looked at nothing has not failed -- so a report over an empty archive is `ok`.
    Every clause's `checked` count is therefore pinned to a literal derived from the fixture,
    which is the same guard `ClauseResult.checked` exists to make possible: "a clause that passed
    over zero subjects and a clause that passed over 600,000 are different facts".

    The counts, and where each comes from: six blocks in the parent/`ord` bijection; the table's
    2 x 2 extent, position by position, in `grid_exactly_once`; one `rel`; three subjects in
    `layer_inherited`, which is the six blocks minus the parentless `document` root and the two
    page roots, whose layer is set rather than inherited (M-INV-5).
    """
    with open_owdoc(trip.reexported) as reader:
        report = owcheck_archive(reader)
    assert report.ok, [violation for clause in report.clauses for violation in clause.violations]
    checked = {clause.clause.value: clause.checked for clause in report.clauses}
    assert checked["parent_ord_bijection"] == 6
    assert checked["grid_exactly_once"] == 4, "the 2 x 2 extent, position by position"
    assert checked["rel_referential"] == 1
    assert checked["layer_inherited"] == 3, "six blocks minus the root and the two page roots"
    assert sum(checked.values()) > 0, "an owcheck that looked at nothing is `ok` and worthless"


# ---------------------------------------------------------------------------------------------
# The comparison is not vacuous: three perturbations, three reds
# ---------------------------------------------------------------------------------------------
#
# Every assertion above compares two structures this file builds from two stores. If `_records()`
# were blind to a field, the comparison would be green whatever the codec did with it. So each of
# the three fields the archive most obviously has to carry -- a block's text, its `cite`, its
# `content_digest` -- is perturbed IN THE SOURCE STORE after the round trip has completed, the
# source is re-exported, and the comparison against the imported store's export is required to go
# red AT THAT FIELD. A perturbation that changed both sides would prove nothing, which is why the
# mutation lands after the import and never before it.


def _perturb(store: Path, sql: str, params: tuple[Any, ...]) -> None:
    connection = ow.connect(store)
    try:
        changed = connection.execute(sql, params).rowcount
        connection.commit()
    finally:
        connection.close()
    assert changed == 1, f"the perturbation matched {changed} rows, not 1: {sql}"


def _reexport_source(trip: RoundTrip, tmp_path: Path) -> dict[str, Any]:
    return _records(_export_store(trip.source, trip.source_cas, tmp_path / "perturbed.owdoc"))


def test_a_changed_block_text_in_the_source_turns_the_comparison_red(
    trip: RoundTrip, tmp_path: Path
) -> None:
    """`t` is a wire key (03 section 3.1). A comparison that cannot see text sees nothing."""
    _perturb(
        trip.source, "UPDATE block SET text = ? WHERE addr = ?", ("termination for cause", "p0/0")
    )
    perturbed, imported = _reexport_source(trip, tmp_path), _records(trip.reexported)
    assert perturbed != imported
    changed = [
        row["i"]
        for row, other in zip(
            perturbed["blocks/000000.ndjson"], imported["blocks/000000.ndjson"], strict=True
        )
        if row != other
    ]
    assert changed == ["p0/0"], changed


def test_a_changed_cite_in_the_source_turns_the_comparison_red(
    trip: RoundTrip, tmp_path: Path
) -> None:
    """`c` is the wire key 03:2521 names as the reason a durable cite survives an archive."""
    _perturb(trip.source, "UPDATE block SET cite = ? WHERE addr = ?", ("d1#99", "p1/0/r1c1"))
    perturbed, imported = _reexport_source(trip, tmp_path), _records(trip.reexported)
    assert perturbed != imported
    changed = [
        row["c"]
        for row, other in zip(
            perturbed["blocks/000000.ndjson"], imported["blocks/000000.ndjson"], strict=True
        )
        if row != other
    ]
    assert changed == ["d1#99"], changed


def test_a_changed_content_digest_in_the_source_turns_the_comparison_red(
    trip: RoundTrip, tmp_path: Path
) -> None:
    """`cd` is `NOT NULL` on the table and required on the wire (03:706's `required` list)."""
    _perturb(trip.source, "UPDATE block SET content_digest = ? WHERE addr = ?", (bytes(16), "p1/0"))
    perturbed, imported = _reexport_source(trip, tmp_path), _records(trip.reexported)
    assert perturbed != imported
    changed = [
        (row["i"], row["cd"])
        for row, other in zip(
            perturbed["blocks/000000.ndjson"], imported["blocks/000000.ndjson"], strict=True
        )
        if row != other
    ]
    assert changed == [("p1/0", "00" * 16)], changed


# ---------------------------------------------------------------------------------------------
# One generation, and the two losses that are the container's rather than the codec's
# ---------------------------------------------------------------------------------------------


def test_an_archive_holds_exactly_one_generation(tmp_path: Path) -> None:
    """03:2503. A staged second generation is durable, invisible, and NOT in the archive.

    `DocSink` writes at `g_t = doc.gen + 1` and does not bump `doc.gen` until `end_doc` (03
    section 2.9), so a crash mid-reparse leaves generation 2 committed page by page with
    generation 1 still the head. Exporting must carry the head only -- otherwise the deep-golden
    `rebind()` diff stops being "a diff of two files" (03:2505). Asserted three ways: the
    manifest names generation 1, the record count is the first generation's, and the second
    generation's text is nowhere in the decompressed bytes.
    """
    source, cas = _write_source_document(tmp_path)
    second = "a paragraph that belongs to the staged generation"
    connection = ow.connect_readonly(source)
    try:
        producer_id = int(connection.execute("SELECT min(producer_id) FROM producer").fetchone()[0])
    finally:
        connection.close()
    with ow.StoreThread(lambda: ow.connect(source)) as thread:
        sink = _sink(thread, cas, producer_id)
        sink.begin_doc(_doc_record(7, "file:///corpus/contract.pdf"))
        sink.begin_page(_page_record(0))
        staged_root = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=staged_root,
                text=second,
            )
        )
        sink.end_page({})
        # `end_doc` is deliberately NOT called: generation 2 is durable and unpublished.

    connection = ow.connect_readonly(source)
    try:
        staged = connection.execute("SELECT count(*) FROM block WHERE gen = 2").fetchone()[0]
    finally:
        connection.close()
    assert staged == 2, "the staged generation is not in the store, so this proves nothing"

    archive = _export_store(source, cas, tmp_path / "head.owdoc")
    records = _records(archive)
    assert records["manifest.json"]["gen"] == 1
    assert len(records["blocks/000000.ndjson"]) == 6
    with zipfile.ZipFile(archive) as package:
        blob = b"".join(package.read(name) for name in package.namelist())
    assert second.encode() not in blob, "a staged generation reached the archive"


def test_the_page_row_is_what_the_container_cannot_carry(trip: RoundTrip) -> None:
    """A DEFECT PIN, not a property. 03:2485-2497's member tree has no `pages` member.

    `page` is `[SOR]` in the read contract at 03:2474 -- `page_kind`, `label`, `w_mpt`, `h_mpt`,
    `rotation`, `quad_origin`, `method` and `status` are all part of the public model -- and none
    of them has anywhere to travel, so `import(export(store)) == store` is false over the `page`
    table by construction of the container. This pins the loss where it is visible.

    IF THIS TEST GOES RED because a `pages` member landed, delete it and add the page row to the
    projection: the gap is closed and the pin has done its job.
    """
    source = ow.connect_readonly(trip.source)
    imported = ow.connect_readonly(trip.imported)
    try:
        query = "SELECT page, w_mpt, h_mpt, quad_origin FROM page ORDER BY page"
        assert [tuple(r) for r in source.execute(query)] == [
            (0, 595_280, 841_890, "topleft"),
            (1, 595_280, 841_890, "topleft"),
        ]
        assert [tuple(r) for r in imported.execute(query)] == [
            (0, None, None, None),
            (1, None, None, None),
        ]
    finally:
        source.close()
        imported.close()


def test_the_three_ownership_columns_are_stamped_by_the_sink_and_not_read_from_the_archive(
    tmp_path: Path,
) -> None:
    """Why `pd`, `oo` and `od` are dropped from the projection, proved rather than asserted.

    A second import of the same archive into a store whose sink declares a DIFFERENT operator
    identity produces different `origin_operator` and `origin_driver` values -- so had the
    projection compared them, it would be comparing this file's two `DocSink(...)` calls and not
    the round trip. INV-6 and INV-7 are why the host stamps them; this is what that costs G28.
    """
    source, cas = _write_source_document(tmp_path)
    archive = _export_store(source, cas, tmp_path / "a.owdoc")
    path, other_cas, producer_id = _fresh(tmp_path, "other.owstore")
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.other",
            origin_driver="parse.other.driver",
            driver_schema_v=9,
            blobs=BlobStore(other_cas),
        )
        import_(
            archive,
            _ImportSink(sink),
            doc_record=_doc_record_from,
            page_record=_page_record_from,
            asset_draft=_asset_draft_from,
        )
    connection = ow.connect_readonly(path)
    try:
        stamped = connection.execute(
            "SELECT DISTINCT origin_operator, origin_driver, driver_schema_v FROM block"
        ).fetchall()
    finally:
        connection.close()
    assert [tuple(row) for row in stamped] == [("parse.other", "parse.other.driver", 9)], (
        "the archive's `oo`/`od` reached the row, so they are NOT sink-stamped and the "
        "projection should compare them"
    )


def test_the_real_docsink_refuses_the_reserved_x_slot_import_borrows(tmp_path: Path) -> None:
    """Workaround 1 of `_ImportSink`, pinned. `owdoc.import_` and `store/doc.py` disagree.

    `_add_one` writes `x["x.ow.addr"]` and `x["x.ow.cite"]` onto every draft; `_validate_x`
    refuses any key whose vendor segment is `ow`. 03:302 reserves `ow` **for the framework**, and
    `import_` is the framework -- so the refusal is the half that is wrong, and until one of the
    two moves, an unadapted `import_(path, DocSink(...))` cannot import one block.
    """
    path, cas, producer_id = _fresh(tmp_path, "refusal.owstore")
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = _sink(thread, cas, producer_id)
        sink.begin_doc(_doc_record(3, "file:///corpus/x.pdf"))
        sink.begin_page(_page_record(0))
        with pytest.raises(ModelError, match="reserved `ow` vendor segment"):
            sink.add_block(
                BlockDraft(
                    kind=Kind.DOCUMENT,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.SYNTHETIC,
                    x={"x.ow.cite": "d1#1"},
                )
            )


def test_the_archive_never_names_a_block_id_of_either_store(trip: RoundTrip) -> None:
    """03:1083, over a real store's real ids rather than over a planted constant.

    `test_archive_owdoc.py` plants a distinctive `block_id` because its source is hand-written.
    Here the ids are whatever `DocSink` minted, so the assertion is structural instead: no member
    carries the key `block_id`, `parent_id`, `src_id`, `dst_id` or `producer_id`, and every
    reference in a block record that could have been an id is an `addr`.
    """
    with zipfile.ZipFile(trip.exported) as package:
        blob = b"".join(package.read(name) for name in package.namelist())
    for forbidden in (b"block_id", b"parent_id", b"src_id", b"dst_id", b"producer_id"):
        assert forbidden not in blob, f"{forbidden!r} appears in the archive"
    records = _records(trip.exported)
    for row in records["blocks/000000.ndjson"]:
        assert row["pa"] is None or isinstance(row["pa"], str)
    for row in records["rels.ndjson"]:
        assert isinstance(row["src"], str) and isinstance(row["dst"], str)


def test_the_export_source_is_the_same_code_on_both_sides(trip: RoundTrip) -> None:
    """One exporter reads both stores, so a difference in the projections IS a difference in the
    stores -- and that is only true if the exporter actually read something from each.

    The guard against a silently-empty read on the SECOND store, which is the one an importer
    could have left empty. Without it, `_records(a) == _records(b)` could hold with both sides
    reporting an empty document, and `test_the_fixture_document_holds...` only pins the first.
    """
    records = _records(trip.reexported)
    assert len(records["blocks/000000.ndjson"]) == 6
    assert records["manifest.json"]["counts"]["assets"] == 1
    assert records["manifest.json"]["counts"]["parts"] == 1
    connection = ow.connect_readonly(trip.imported)
    try:
        assert connection.execute("SELECT count(*) FROM block").fetchone()[0] == 6
        assert connection.execute("SELECT count(*) FROM mark").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM cell").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM grid_slot").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM asset").fetchone()[0] == 1
    finally:
        connection.close()


def test_the_imported_store_is_internally_consistent(trip: RoundTrip) -> None:
    """SQLite's own verdict on the store an import produced, which no projection can give."""
    connection = ow.connect_readonly(trip.imported)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_a_reader_over_the_archive_yields_the_blocks_the_store_holds(trip: RoundTrip) -> None:
    """`OwdocReader.blocks()` is what `import_` and `owcheck_archive` both read, so the addr set
    it yields is the hinge both depend on. Asserted against the store's own `addr` set."""
    with open_owdoc(trip.exported) as reader:
        assert isinstance(reader, OwdocReader)
        addresses = sorted(str(row.addr) for row in reader.blocks())
    assert addresses == sorted(row[0] for row in _blocks(trip.imported))


# ---------------------------------------------------------------------------------------------
# 5. THE CORPUS HALF. G28 is "over the fixture corpus" and this is the half that never ran.
# ---------------------------------------------------------------------------------------------
#
# Everything above builds its document by hand. G28's assertion does not: ADR-2 decision 4
# (`_plan/adr/0002-invariant-and-gate-registers.md`:160) and V01-7 (00-vision.md:708) both write
# "over the fixture corpus", and 16-roadmap.md:442 is where a corpus P2 can actually ingest comes
# from -- "ingest `fixtures/gen/gen_5000p_pdf.py`'s output through a stub `parse/1` driver".
#
# WHICH CORPUS THIS IS, SAID PLAINLY. `fixtures/` is not one thing: 11-repo-layout.md:383-384
# lists seven members and 13-quality.md:92 makes `fixtures/index.toml` the manifest of the
# LICENSED documents Q-G1 gates. None of that exists at P2. What exists is `fixtures/gen/`, the
# deterministic generator regime of 13-quality.md:586-589, and that is the corpus round-tripped
# here: a synthesised corpus, not a licensed one. The distinction is not cosmetic -- a licensed
# PDF exercises grammars the generator's one frozen grammar does not -- so the CI step keeps its
# tripwire on `fixtures/index.toml` and this section closes the half it can close.


def _load_script(path: Path, name: str) -> ModuleType:
    """Load a `tools/`- or `fixtures/`-level script BY PATH, as a module.

    Neither script is inside a package, so there is no dotted name to import.
    `spec_from_file_location` is the mechanism `test_fixture_gen.py` and `test_gate_crash.py`
    already use, and for their reasons: not `importlib.import_module`, which INV-4 bans outside
    `host/`, and not a `sys.path` mutation, which would leak into every later test.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover -- both files are in this repo
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(Path(__file__).resolve())

gen = _load_script(REPO_ROOT / "fixtures" / "gen" / "gen_5000p_pdf.py", "ow_gen_5000p_pdf_rt")
"""Contract F1's generator (13-quality.md:586-589). A pure function of the page index."""

stub = _load_script(REPO_ROOT / "tools" / "p2_stub_parse.py", "ow_p2_stub_parse_rt")
"""Contract F2's stub `parse/1` driver (16-roadmap.md:442). Reads the PDF, drives `DocSink`."""


CORPUS_PAGES: Final = 127
"""The smallest page count that crosses a Frame boundary, and the whole reason for the number.

THE ARITHMETIC, done here rather than taken on trust. The generator emits
`BLOCKS_PER_PAGE_FIXTURE = 64` blocks of content per page (1 heading + 8 paragraphs + 1 table + 54
cells) and `tools/p2_stub_parse.py` adds one page-root `container` per page (03:1027) plus one
`document` root for the whole document, so the block count is `1 + 65 * pages`:

    126 pages -> 1 + 8_190 = 8_191  <= FRAME_TARGET_BLOCKS (8_192): ONE frame
    127 pages -> 1 + 8_255 = 8_256  >  FRAME_TARGET_BLOCKS:         TWO frames

`test_the_frame_arithmetic_that_picks_the_page_count_is_computed_and_not_quoted` asserts both
halves against the generator's own constants, so a change to `PARAGRAPHS_PER_PAGE` or
`TABLE_ROWS` fails there instead of quietly dropping the corpus back to one frame.

WHY NOT 5,000. G28 is `budget_s = 45` in the `gates` job. At 5,000 pages the store is 325,001
blocks (`tools/measure_store.py`'s measured figure) and a round trip is five passes over the
corpus -- generate, ingest, export, import, re-export -- plus a full projection comparison, not
one. 127 pages is the smallest corpus that tests what a corpus is for, and its measured cost is
reported for this wave. 13-quality.md:109-113 has already ruled on the budget independently of
any measurement here: `128 + 105 = 233 s` is past `V01-14`'s 180 s ceiling, so ADR-2's
pre-committed fallback -- G28 and G29 move to the `test` job beside G26, one line each in
`tools/gates.toml` -- is "not contingent but due at the first measured run".
"""

CORPUS_BLOCKS: Final = 8_256
"""`1 + 65 * 127`. Written down, not computed, so a change to the fixture is a visible diff."""

CORPUS_FRAME_BLOCKS: Final = (8_192, 64)
"""Blocks in `blocks/000000.ndjson` and `blocks/000001.ndjson`. The first frame is FULL."""

CORPUS_CELLS: Final = 6_858
"""`127 * 9 * 6`. Real `cell` rows with real geometry, and the reason the corpus is not prose."""

CORPUS_ESCAPED_CELLS: Final = 25
"""Cells whose literal needed unescaping: one per page on every fifth page of 127.

`ESCAPED_CELL_PAGE_STRIDE = 5`, so pages 5, 10, ... 125 -- twenty-five of them. Each is
`Quote.NORMALIZED` rather than `VERBATIM`, because the escaped extent in the file is longer than
the text (`p2_stub_parse._verbatim`, INV-10's bytes predicate at 03:1470-1476).
"""

CORPUS_QUOTES: Final = MappingProxyType(
    {Quote.SYNTHETIC: 255, Quote.NORMALIZED: 1_041, Quote.VERBATIM: 6_960}
)
"""The corpus's `Quote` mix, as literals, and each cell of it is derivable in one line.

    SYNTHETIC   255 = 1 document root + 127 page roots + 127 tables   (containers, no text)
    NORMALIZED  1_041 = 127 * 8 coalesced paragraphs + 25 escaped cells
    VERBATIM    6_960 = 127 headings + (6_858 - 25) plain cells

The mix is the point. A fixture that produced one rung would leave the `Quote` ladder untested by
the round trip, and 03 section 8.5 makes the ladder the thing that stops assembled text from
being quotable. Three rungs of five are reached; `RECONSTRUCTED` and `REFLOWED` need OCR and a
line-joiner, which the stub declines to have (`STUB_CAPABILITIES`).
"""

CORPUS_MEMBERS: Final = (
    "blocks/000000.ndjson",
    "blocks/000001.ndjson",
    "frames.json",
    "grids.ndjson",
    "manifest.json",
    "parts/file",
)
"""Every member the corpus export holds, in `sorted()` order.

No `marks/` member (`STUB_CAPABILITIES.marks` is `False`), no `rels.ndjson`, no `assets/`, no
`diags.json` and no `views` -- the stub writes none of them, and 03:2485-2497 makes every member
but `manifest.json` optional. Pinned as a tuple so that a member appearing or vanishing is a
failure here rather than a silent narrowing of the comparison below.
"""

FRAME_COLLISION: Final = (126, 0)
"""The `(page, ord)` coordinate at which frame 0's `hi` equals frame 1's `lo`. THE DEFECT.

Frame 0's last record is `p126/0/0`, page 126's heading, whose `ord` among its siblings is 0.
Frame 1's first record is `p126/0/9/r0c0`, a cell of the same page, whose `ord` among ITS siblings
is also 0. See `test_the_frame_index_cannot_name_a_boundary_that_falls_inside_a_page`.
"""

CORPUS_DIAG_KEYS: Final = ("OW_MODEL", "warning", "archive.import")
"""`(code, severity, component)` of the one diag the corpus round trip produces."""

FRAME_1_LAST_CELL: Final = "p126/0/9/r8c5"
"""A block that lives in the SECOND frame. The perturbation target, so the non-vacuity proof
reaches past the boundary rather than testing frame 0 twice."""


@dataclass(frozen=True, slots=True)
class CorpusTrip:
    """One completed `import(export(store))` over the generated corpus."""

    pdf: Path
    source: Path
    source_cas: Path
    imported: Path
    imported_cas: Path
    exported: Path
    reexported: Path


def _ingest_corpus(root: Path, pdf: Path) -> tuple[Path, Path]:
    """Ingest `pdf` into a fresh store through the stub `parse/1` driver.

    The wiring is `tools/measure_store.py`'s and is not reinvented: one `producer` row, one
    `DocSink` stamped with the driver's identity, and `ingest(sink, pdf=..., uri=..., doc_ord=0,
    doc_key=...)`. `measure_store` itself is a runner with a `main()` and a `--gate` flag, so it
    is read and not imported.

    The URI is a constant rather than the real path, for `measure_store`'s reason: `doc.uri` is a
    wire field, so a store whose `uri` depended on the tmpdir would export differently on every
    run and the comparison would be over a moving target.
    """
    path, cas, producer_id = _fresh(root, "corpus.owstore")
    uri = "file:///fixtures/generated/gen.pdf"
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = _sink(thread, cas, producer_id, driver=stub.DRIVER_ID)
        stub.ingest(
            sink,
            pdf=pdf,
            uri=uri,
            doc_ord=0,
            doc_key=hashlib.blake2b(uri.encode("utf-8"), digest_size=16).digest(),
        )
    return path, cas


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> CorpusTrip:
    """generated PDF -> store -> `a.owdoc` -> second store -> `b.owdoc`, built ONCE.

    Module-scoped because the five passes cost seconds, not milliseconds, and G28 has a 45 s
    budget to live inside. Nothing below mutates `source`: the perturbation test copies it first,
    which is the price of the shared fixture and is cheaper than five more round trips.
    """
    root = tmp_path_factory.mktemp("corpus")
    pdf = Path(gen.generate(root / "gen.pdf", pages=CORPUS_PAGES))
    source, source_cas = _ingest_corpus(root, pdf)
    exported = _export_store(source, source_cas, root / "a.owdoc")
    imported, imported_cas = _import_archive(
        root, exported, "corpus-imported.owstore", driver=stub.DRIVER_ID
    )
    reexported = _export_store(imported, imported_cas, root / "b.owdoc")
    return CorpusTrip(pdf, source, source_cas, imported, imported_cas, exported, reexported)


def _member_bytes(archive: Path) -> dict[str, bytes]:
    """Every member's UNCOMPRESSED bytes. The stronger comparison, member by member."""
    with zipfile.ZipFile(archive) as package:
        return {name: package.read(name) for name in package.namelist()}


def _copy_store(source: Path, target: Path) -> Path:
    """A byte copy of a closed `.owstore`, plus any WAL sidecars it left behind.

    `ow.connect` opens in WAL mode, so a store can carry `-wal` and `-shm` companions; copying
    the main file alone would silently drop whatever had not been checkpointed. Both are copied
    when present, which is the only form of this that is correct on both platforms.
    """
    shutil.copy2(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))
    return target


def _rows(store: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """One query against a real store, read WITHOUT the exporter in the path.

    Every projection assertion in this file runs both stores through ONE `StoreExportSource`, so
    a defect inside that adapter compares equal to itself. This is the escape hatch: SQL straight
    at the `block` table, against literals written down here or computed by the generator.
    """
    connection = ow.connect_readonly(store)
    try:
        return [tuple(row) for row in connection.execute(sql, params)]
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# The corpus is a corpus: the arithmetic, then the counts
# ---------------------------------------------------------------------------------------------


def test_the_frame_arithmetic_that_picks_the_page_count_is_computed_and_not_quoted() -> None:
    """`CORPUS_PAGES` is the SMALLEST page count that crosses a frame boundary. Both halves.

    Asserted against `FRAME_TARGET_BLOCKS` and the generator's own constants rather than against
    the number in `CORPUS_PAGES`'s docstring, so that a fixture change -- another paragraph per
    page, a wider table -- fails here and names itself, instead of leaving a corpus that says
    "127 pages" and quietly holds one frame again.
    """
    per_page = 1 + gen.BLOCKS_PER_PAGE_FIXTURE
    assert gen.BLOCKS_PER_PAGE_FIXTURE == 64, "1 heading + 8 paragraphs + 1 table + 54 cells"
    assert per_page == 65, "plus the page-root container the stub mints per page (03:1027)"
    assert FRAME_TARGET_BLOCKS == 8_192
    assert 1 + per_page * (CORPUS_PAGES - 1) <= FRAME_TARGET_BLOCKS, "126 pages fit one frame"
    assert 1 + per_page * CORPUS_PAGES == CORPUS_BLOCKS
    assert CORPUS_BLOCKS > FRAME_TARGET_BLOCKS, "so CORPUS_PAGES is the first crossing"
    assert CORPUS_FRAME_BLOCKS == (FRAME_TARGET_BLOCKS, CORPUS_BLOCKS - FRAME_TARGET_BLOCKS)
    assert CORPUS_CELLS == CORPUS_PAGES * gen.TABLE_ROWS * gen.TABLE_COLS
    escaped_pages = [
        page for page in range(1, CORPUS_PAGES + 1) if page % gen.ESCAPED_CELL_PAGE_STRIDE == 0
    ]
    assert len(escaped_pages) == CORPUS_ESCAPED_CELLS, "one escaped cell per fifth page"
    assert sum(CORPUS_QUOTES.values()) == CORPUS_BLOCKS
    assert CORPUS_QUOTES[Quote.NORMALIZED] == (
        CORPUS_PAGES * gen.PARAGRAPHS_PER_PAGE + CORPUS_ESCAPED_CELLS
    )
    assert CORPUS_QUOTES[Quote.VERBATIM] == CORPUS_PAGES + CORPUS_CELLS - CORPUS_ESCAPED_CELLS
    assert CORPUS_QUOTES[Quote.SYNTHETIC] == 1 + 2 * CORPUS_PAGES


def test_the_generated_corpus_reaches_what_the_hand_built_documents_cannot(
    corpus: CorpusTrip,
) -> None:
    """The count assertion 11-repo-layout.md section 6.8 demands, at corpus scale.

    Section 6.8's rule is that a gate which found no inputs must fail rather than pass: every
    equality below this test compares two structures this file computes, and two empty ones are
    equal. So the corpus's shape is written down here in literals -- two frames, 8,256 blocks,
    6,858 cells, 8,001 text blocks with real byte origins, three `Quote` rungs -- and each of them
    is something the six-block hand-built fixture does not have.
    """
    records = _records(corpus.exported)
    assert sorted(records) == list(CORPUS_MEMBERS)

    frames = records["frames.json"]
    assert len(frames) == 2, "a one-frame corpus does not test the frame index"
    assert [frame["blocks"] for frame in frames] == list(CORPUS_FRAME_BLOCKS)
    assert [frame["path"] for frame in frames] == list(CORPUS_MEMBERS[:2])
    assert len({frame["sha256"] for frame in frames}) == 2, "two frames, two digests"
    assert [len(records[member]) for member in CORPUS_MEMBERS[:2]] == list(CORPUS_FRAME_BLOCKS)

    assert records["manifest.json"]["counts"] == {
        "blocks": CORPUS_BLOCKS,
        "pages": CORPUS_PAGES,
        "marks": 0,
        "rels": 0,
        "grids": CORPUS_PAGES,
        "diags": 0,
        "parts": 1,
        "assets": 0,
        "views": 0,
        "frames": 2,
    }
    grids = records["grids.ndjson"]
    assert len(grids) == CORPUS_PAGES, "one real Grid per page"
    assert sum(len(grid["cells"]) for grid in grids) == CORPUS_CELLS
    assert {(grid["n_rows"], grid["n_cols"]) for grid in grids} == {
        (gen.TABLE_ROWS, gen.TABLE_COLS)
    }

    # Read past the exporter for the mix, because these are the properties a hand-built fixture
    # sets by hand and the corpus computes from the bytes of a real file.
    assert _rows(corpus.source, "SELECT quote, count(*) FROM block GROUP BY quote") == [
        (int(quote), count) for quote, count in sorted(CORPUS_QUOTES.items())
    ]
    # `enum_val` is the store's own vocabulary table (03 section 4.1), so an enum is matched by
    # NAME through a subquery rather than by an ordinal written down here -- a literal `12` would
    # be a second, silent definition site for a mapping the store owns.
    assert _rows(
        corpus.source,
        "SELECT count(*) FROM block WHERE text IS NOT NULL AND os_kind = "
        "(SELECT ord FROM enum_val WHERE domain = ? AND name = ?)",
        ("origin_span_kind", "bytes"),
    ) == [(8_001,)], "every text block carries a real OriginBytes into the source file"
    assert _rows(
        corpus.source,
        "SELECT count(*) FROM block WHERE quote = ? AND kind = "
        "(SELECT ord FROM enum_val WHERE domain = ? AND name = ?)",
        (int(Quote.NORMALIZED), "kind", "paragraph"),
    ) == [(CORPUS_PAGES * gen.PARAGRAPHS_PER_PAGE,)], "coalesced text is never VERBATIM"


# ---------------------------------------------------------------------------------------------
# G28's corpus half
# ---------------------------------------------------------------------------------------------


def _manifest_without_the_frame_defect(records: dict[str, Any]) -> dict[str, Any]:
    """`manifest.json` minus the two cells the frame-index defect moves, and NOTHING else.

    `status` and `counts.diags` are the whole of the deviation and both are pinned to literals by
    `test_the_frame_index_cannot_name_a_boundary_that_falls_inside_a_page`. Blanking them here
    rather than skipping `manifest.json` keeps the other sixteen keys -- `container_version`,
    `model_version`, `min_reader`, `digest_recipe`, `doc_key`, `gen`, `source`, `producers`,
    `parts`, `assets`, `views`, `declared`, `achieved`, `confidence`, `timings_ms`, `x` and the
    rest of `counts` -- inside the comparison.
    """
    manifest = dict(records["manifest.json"])
    manifest["status"] = "<pinned by the frame-index defect test>"
    manifest["counts"] = {key: value for key, value in manifest["counts"].items() if key != "diags"}
    return manifest


def test_the_generated_corpus_survives_export_and_import_into_a_fresh_store(
    corpus: CorpusTrip,
) -> None:
    """G28, over the fixture corpus. The half of the assertion that had never run.

    A real 127-page PDF, parsed out of its own bytes by `tools/p2_stub_parse.py`, written through
    a real `DocSink`, exported, imported into a SECOND fresh store through a second real
    `DocSink`, and re-exported. The two wire projections are equal, member for member and record
    for record, over 8,256 block records spread across two frames.

    ONE MEMBER IS NOT REPRODUCED, and the loss is not the codec's: `diags.json` exists only in
    the re-export, holding the single warning the frame index's own coordinate scheme produces.
    It is excluded here by name and pinned by name in the next test, which is the form this file
    already uses for the `page` row -- a loss that is stated and located, never smoothed.
    """
    before, after = _records(corpus.exported), _records(corpus.reexported)
    assert sorted(before) == list(CORPUS_MEMBERS)
    assert sorted(after) == sorted([*CORPUS_MEMBERS, "diags.json"])
    for member in CORPUS_MEMBERS:
        if member == "manifest.json":
            assert _manifest_without_the_frame_defect(before) == (
                _manifest_without_the_frame_defect(after)
            )
            continue
        assert before[member] == after[member], f"{member} differs across the round trip"


def test_the_corpus_exports_are_byte_identical_except_where_the_frame_defect_lands(
    corpus: CorpusTrip,
) -> None:
    """The stronger form (16-roadmap.md:550, INV-10, 03:2505): a diff of two FILES.

    Stronger than the projection equality by exactly the fields `_comparable()` drops, and by
    member order, key order and the pinned DOS-epoch `ZipInfo`. It is asserted as a SET of
    differing member names, because "the files differ" is all a byte comparison can say and
    "they differ in these two members and no others" is what a reader needs.

    Both frames' bytes are called out separately: `frames.json` restates each frame's 3.8 MB and
    29 KB of NDJSON as 64 hex characters, so frame equality is a digest claim as well as a byte
    claim, and both hold. `parts/file` is checked against the generated PDF itself, which is what
    makes the retained part (03:2494's `present: true`) a round trip of real bytes through two
    CAS roots rather than of a placeholder.
    """
    before, after = _member_bytes(corpus.exported), _member_bytes(corpus.reexported)
    differing = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    assert differing == {"diags.json", "manifest.json"}
    for member in CORPUS_MEMBERS[:2]:
        assert before[member] == after[member], f"{member} is not byte-identical"
    assert before["frames.json"] == after["frames.json"], "two frames, two agreeing digests"
    assert before["parts/file"] == after["parts/file"] == corpus.pdf.read_bytes()


def test_the_frame_index_cannot_name_a_boundary_that_falls_inside_a_page(
    corpus: CorpusTrip,
) -> None:
    """A DEFECT PIN, not a property, and the one thing the corpus half found.

    03:2528 defines a Frame as "a block-count-bounded run of Blocks in `(page, ord)` order" and
    03:2483 gives `frames.json` the four coordinates `(lo_page, lo_ord, hi_page, hi_ord)`. But
    `ord` is "dense from 0 among siblings" (03:279, restated at 03:2188), so `(page, ord)` is NOT
    unique within a page: on page 126 the heading `p126/0/0` and the cell `p126/0/9/r0c0` are both
    `(126, 0)`. `archive/frames.py`'s `_check_monotonic` refuses two frames whose brackets touch
    -- `previous.hi >= current.lo` is the test -- so an archive whose frame boundary falls inside
    a page cannot be parsed by its own reader.

    03:2531-2533 is where this bites hardest, because it is the paragraph that chose block-count
    bounding precisely to avoid a special case: "A Frame is DELIBERATELY not a page range... and
    forces a 'frames may split within a page' exception that another language's reader will get
    wrong. Block-count bounding has no such case." It has exactly that case. The coordinate
    scheme cannot express the split the bounding rule makes inevitable.

    THE COST IS BOUNDED AND IS ASSERTED HERE RATHER THAN DESCRIBED. `load()` is tolerant
    (03:2516), so `OwdocReader` falls back to a full frame scan, every one of the 8,256 blocks
    still imports, and the whole consequence is one `OW_MODEL` warning plus the `partial` status
    that warning implies. Both are pinned below, in the store and on the wire.

    IF THIS TEST GOES RED because the index changed: the fix is in `archive/frames.py`, and the
    two candidate forms are `previous.hi > current.lo` -- touching brackets are not an overlap
    when the coordinate repeats -- or a third coordinate that is unique within a page. Then
    delete this test and fold `diags.json` and `manifest.json` back into the two comparisons
    above: the gap is closed and the pin has done its job.
    """
    frames = _records(corpus.exported)["frames.json"]
    assert (frames[0]["hi_page"], frames[0]["hi_ord"]) == FRAME_COLLISION
    assert (frames[1]["lo_page"], frames[1]["lo_ord"]) == FRAME_COLLISION
    assert frames[0]["hi_page"] == frames[1]["lo_page"], "the boundary is INSIDE page 126"

    diags = _records(corpus.reexported)["diags.json"]
    assert len(diags) == 1, diags
    diag = diags[0]
    assert (diag["code"], diag["severity"], diag["component"]) == CORPUS_DIAG_KEYS
    assert "overlap or are out of order" in diag["message"], diag["message"]
    assert "(126, 0) then (126, 0)" in diag["message"], diag["message"]
    for member in CORPUS_MEMBERS[:2]:
        assert member in diag["message"], "the diag names both frames it could not order"

    assert _records(corpus.exported)["manifest.json"]["status"] == "ok"
    assert _records(corpus.reexported)["manifest.json"]["status"] == "partial"
    assert _records(corpus.exported)["manifest.json"]["counts"]["diags"] == 0
    assert _records(corpus.reexported)["manifest.json"]["counts"]["diags"] == 1
    assert _rows(corpus.source, "SELECT count(*) FROM diag") == [(0,)]
    assert _rows(corpus.imported, "SELECT code, component FROM diag") == [
        (CORPUS_DIAG_KEYS[0], CORPUS_DIAG_KEYS[2])
    ]
    assert _rows(corpus.source, "SELECT status FROM doc") == [("ok",)]
    assert _rows(corpus.imported, "SELECT status FROM doc") == [("partial",)]


def test_owcheck_passes_over_both_ends_of_the_corpus_round_trip(corpus: CorpusTrip) -> None:
    """The "lossless" half at corpus scale, with every clause's `checked` count pinned.

    `OwcheckReport.ok` is true when no clause FAILED, and a clause that looked at nothing has not
    failed -- so `ok` over an empty archive is `ok`. Every count below is therefore derived from
    the corpus's own arithmetic and written down:

    * `parent_ord_bijection` -- every block, so `CORPUS_BLOCKS`;
    * `grid_exactly_once` -- one position per cell over 127 dense 9x6 grids, `CORPUS_CELLS`;
    * `verbatim_retained_part` -- every `VERBATIM` block, which is `CORPUS_QUOTES`' top rung, and
      it is non-zero only because `add_part` retained the PDF (03:2494's `present: true`);
    * `layer_inherited` -- `CORPUS_BLOCKS` minus the parentless `document` root and the 127 page
      roots, whose `layer` is set rather than inherited (M-INV-5): 8_256 - 128 = 8_128;
    * `rel_referential` and `continues_acyclic` -- zero, because the stub emits no `rel`. Asserted
      AS zero rather than omitted, so a driver that starts emitting rels is visible here.
    """
    expected = {
        "parent_ord_bijection": CORPUS_BLOCKS,
        "grid_exactly_once": CORPUS_CELLS,
        "verbatim_retained_part": CORPUS_QUOTES[Quote.VERBATIM],
        "layer_inherited": CORPUS_BLOCKS - 1 - CORPUS_PAGES,
        "rel_referential": 0,
        "continues_acyclic": 0,
    }
    for archive in (corpus.exported, corpus.reexported):
        with open_owdoc(archive) as reader:
            report = owcheck_archive(reader)
        violations = [violation for clause in report.clauses for violation in clause.violations]
        assert report.ok, violations
        checked = {clause.clause.value: clause.checked for clause in report.clauses}
        assert checked == expected, archive.name


# ---------------------------------------------------------------------------------------------
# The corpus comparison is not vacuous, and it is not blind to its own exporter
# ---------------------------------------------------------------------------------------------


def test_a_changed_block_beyond_the_frame_boundary_turns_the_corpus_comparison_red(
    corpus: CorpusTrip, tmp_path: Path
) -> None:
    """The non-vacuity proof, aimed at the SECOND frame, which is the part that is new.

    The three perturbations above land in a one-frame archive, so they say nothing about whether
    the comparison reads `blocks/000001.ndjson` at all -- a comparison that stopped at the first
    frame would pass all three. This one perturbs `p126/0/9/r8c5`, a cell of the last page, and
    requires the difference to show up IN THE SECOND FRAME while the first stays identical.

    The mutation lands on a COPY of the source store, after the round trip has completed. Both
    halves matter: after, because a perturbation before the import would move both sides together
    and prove nothing; on a copy, because the `corpus` fixture is module-scoped and a mutation of
    it would leak into every test that runs later.
    """
    copy = _copy_store(corpus.source, tmp_path / "perturbed.owstore")
    _perturb(
        copy,
        "UPDATE block SET text = ? WHERE addr = ?",
        ("R8C5-PERTURBED", FRAME_1_LAST_CELL),
    )
    perturbed = _records(_export_store(copy, corpus.source_cas, tmp_path / "perturbed.owdoc"))
    after = _records(corpus.reexported)
    assert perturbed != after

    first, second = CORPUS_MEMBERS[0], CORPUS_MEMBERS[1]
    assert perturbed[first] == after[first], "the perturbation leaked out of the second frame"
    changed = [
        (row["i"], row["t"])
        for row, other in zip(perturbed[second], after[second], strict=True)
        if row != other
    ]
    assert changed == [(FRAME_1_LAST_CELL, "R8C5-PERTURBED")], changed


def test_the_corpus_texts_agree_with_the_generator_and_not_only_with_each_other(
    corpus: CorpusTrip,
) -> None:
    """The assertion the projection equality structurally cannot make, and why it is needed.

    `_records()` reads BOTH stores through ONE `StoreExportSource`. That is right for the
    equality 03:2519 asks for -- a difference between the two projections IS a difference between
    the two stores -- but it means a defect INSIDE that adapter is invisible: a dropped `text`
    column, a `cite` read off the wrong row, an `os_b` passed as a range end would appear
    identically on both sides and every comparison above would stay green. That is rule 5's shape
    exactly: both sides come from one source, so the test pins agreement and not value.

    So this test pins value, from three directions and none of them is a second copy of the
    exporter:

    1. **the generator.** `fixtures/gen/gen_5000p_pdf.py`'s `heading_text`, `body_text` and
       `cell_text` are closed forms in the page index, reachable by neither store, and the
       literals they must produce are ALSO written out longhand beside the call -- because a test
       that only asked the generator would agree with a generator that had changed.
    2. **direct SQL**, at the `block` table of BOTH stores, with no exporter in the path at all.
    3. **the wire records of the source export, against those same literals** -- which is the one
       direction that can see a defect INSIDE `StoreExportSource`, because a dropped `t` or a
       shifted `os` would compare equal to itself in every projection assertion above but cannot
       equal a string this file wrote down. INV-10's bytes predicate is evaluated here too, on
       the generated PDF itself (03:1470-1476): the exported `os` of a `VERBATIM` cell must slice
       that file's bytes back to the cell's own text, and the `NORMALIZED` escaped cell's must
       not.
    """
    heading = gen.heading_text(1)
    paragraph = " ".join(gen.body_text(1, 0, line) for line in range(gen.LINES_PER_PARAGRAPH))
    escaped_page = gen.ESCAPED_CELL_PAGE_STRIDE
    escaped = gen.cell_text(escaped_page, gen.ESCAPED_CELL_ROW, gen.ESCAPED_CELL_COL)

    assert heading == "Article 1. Schedule and severance"
    assert paragraph.startswith("schedule severance inspection counterpart custody effective")
    assert paragraph.endswith("escalation breach")
    assert escaped == "R4C2(0185)", "the cell whose literal had to be unescaped"
    assert gen.cell_text(1, 0, 0) == "R0C0-0031"

    # `page` in the store is the ORIGINAL 0-based index (03:277), so generator page 5 is store
    # page 4; the table is the tenth child of its page root (1 heading + 8 paragraphs before it).
    escaped_addr = f"p{escaped_page - 1}/0/9/r{gen.ESCAPED_CELL_ROW}c{gen.ESCAPED_CELL_COL}"
    expected = {
        "p0/0/0": heading,
        "p0/0/1": paragraph,
        "p0/0/9/r0c0": "R0C0-0031",
        escaped_addr: escaped,
    }
    for store in (corpus.source, corpus.imported):
        found = dict(
            _rows(
                store,
                "SELECT addr, text FROM block WHERE addr IN (?, ?, ?, ?) ORDER BY addr",
                tuple(expected),
            )
        )
        assert found == expected, store.name
        assert _rows(store, "SELECT count(*) FROM block") == [(CORPUS_BLOCKS,)]
        assert _rows(store, "SELECT count(*) FROM cell") == [(CORPUS_CELLS,)]
        assert _rows(store, "SELECT DISTINCT origin_driver FROM block") == [(stub.DRIVER_ID,)]

    # Direction 3. The archive's own records against the same literals, plus the cite minting and
    # INV-10's bytes predicate over the generated file.
    records = _records(corpus.exported)
    by_addr = {row["i"]: row for member in CORPUS_MEMBERS[:2] for row in records[member]}
    assert len(by_addr) == CORPUS_BLOCKS, "the two frames hold every block exactly once"
    assert {addr: by_addr[addr]["t"] for addr in expected} == expected
    assert by_addr["p0/0/0"]["c"] == "d1#3", "doc root, page root, then the page's first heading"
    assert by_addr["p0/0/9/r0c0"]["c"] == "d1#13"
    assert sorted(int(row["c"].removeprefix("d1#")) for row in by_addr.values()) == list(
        range(1, CORPUS_BLOCKS + 1)
    ), "`doc.next_cite_n` minted a dense 1..N across 127 pages and two frames"

    # INV-10's bytes branch, over EVERY `VERBATIM` block in the corpus and not over a sample.
    # `nfc(part_bytes[os_a : os_a + os_b].decode(codec)) == block.text` (03:1470-1476), evaluated
    # against the generated PDF -- a third file that neither store nor exporter can influence.
    # One block would not be enough: an exporter defect that clamped or shifted only the small
    # offsets, or only the long spans, would sail past any single spot check.
    data = corpus.pdf.read_bytes()
    verbatim = [row for row in by_addr.values() if row["qt"] == "verbatim"]
    assert len(verbatim) == CORPUS_QUOTES[Quote.VERBATIM]
    wrong = [
        row["i"]
        for row in verbatim
        if data[row["os"]["a"] : row["os"]["a"] + row["os"]["len"]].decode("utf-8") != row["t"]
    ]
    assert wrong == [], f"{len(wrong)} VERBATIM spans do not re-derive their own text: {wrong[:5]}"
    assert by_addr["p0/0/9/r0c0"]["t"] == "R0C0-0031", "and one of them by name, for the reader"
    marked = by_addr[escaped_addr]
    assert marked["qt"] == "normalized"
    raw = data[marked["os"]["a"] : marked["os"]["a"] + marked["os"]["len"]].decode("utf-8")
    assert raw == "R4C2\\(0185\\)", raw
    assert raw != escaped, "which is exactly why this cell may not claim VERBATIM"


def test_the_imported_corpus_store_is_internally_consistent(corpus: CorpusTrip) -> None:
    """SQLite's own verdict on a store 8,256 imported blocks built, which no projection gives."""
    connection = ow.connect_readonly(corpus.imported)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# 6. THE KEYS AND THE VARIANTS NEITHER DOCUMENT ABOVE POPULATES, and the four claims that
#    could not fail without them.
# ---------------------------------------------------------------------------------------------
#
# Sections 1 and 5 between them build 8,262 blocks, and on every one of them eight of the ten
# OPTIONAL wire keys are null and three of the five `os` variants are unreachable. The module
# docstring lists `rk`, `lb`, `ts`, `q`, `sc`, `ld`, `dc`, `pl` and `x` among the keys
# "compared, because the archive carries them and the second store must reproduce them", and
# until this section every one of them but `pl` was compared as `null == null`. That is an
# assertion over an empty collection wearing a field name: hard-coding `"ts": None`,
# `"q": None`, `"sc": None`, `"rk": None`, `"lb": None`, `"ld": None`, `"dc": None` and
# `"x": {}` in `archive/owdoc.py`'s `block_record()` -- all eight at once -- left every
# assertion in sections 1 through 5 green, and DELETING the `"ts"` line outright did too.
# `pl` is the one that was already covered, and only by accident: a payload is a
# `content_digest` input (`identity.content_digest`), so the corpus catches it through `cd`.
#
# The `os` gap was not academic. `StoreExportSource`'s `nodepath` decoder read `os_path` with
# `json.loads`, and `os_path` is a dot-joined string (`spans.py:518`, `store/doc.py:457`), so
# this file could not export a `nodepath` block at all -- it raised `JSONDecodeError`. The
# defect had sat in the adapter unexercised because no block in either document has that
# origin. See `_ORIGIN_DECODERS`.
#
# `_write_rich_document` is therefore a THIRD document, small and deliberate: six blocks, one
# frame, one page, every optional key but `dc` carrying a value this file wrote down, and all
# five `os` variants side by side. It is not folded into `_write_source_document` because that
# document's shape is pinned by literals in nine tests above; a third store is cheaper than
# renumbering them, and it keeps "what a round trip must carry" apart from "what a container
# must hold".
#
# `dc` is the one key left null, and it is null by construction rather than by omission:
# `decision_id` is one of the two `block` columns 03:311 leaves off `Block`, `BlockDraft` has no
# field for it, and `DocSink.add_block` therefore has no way to write one. That is a store-side
# gap, not a codec one, and `test_the_rich_document_populates_every_optional_wire_key_but_one`
# pins it so that closing it is visible here.


RICH_QUAD: Final = Quad(10_000, 20_000, 90_000, 20_000, 90_000, 44_000, 10_000, 44_000)
"""One 80x24-point box in millipoints, topleft origin. `q` on two of the rich blocks.

Whole thousands on purpose: `layout_digest` quantises the quad to WHOLE POINTS before hashing
(`store/doc.py`'s `_whole_points`, 03:1202-1205), so a coordinate that is already a whole point
makes `ld` a function of a number written down here rather than of a rounding rule.
"""

RICH_SCORE_KIND: Final = "layout.confidence"
"""The one scale the rich sink registers. `tools/scorekinds.toml` is not in the tree (03:1715)."""

RICH_PART_BYTES: Final = b"Article 1. Schedule\nthe body paragraph text\nhandwritten line\n" * 8
"""The retained `part`, and the file the rich document's `bytes` and `glyphs` origins point into.

Retained (03:2494's `present: true`) rather than `present: false` like section 1's, so the rich
export carries a `parts/file` member whose bytes cross two CAS roots.
"""

RICH_BLOCKS: Final = 6

RICH_MEMBERS: Final = (
    "blocks/000000.ndjson",
    "frames.json",
    "manifest.json",
    "parts/file",
)
"""Every member the rich export holds, in `sorted()` order.

No marks, rels, grids, assets or diags: the rich document is about the BLOCK RECORD, and each of
those five has its own coverage in section 1.
"""

RICH_OPTIONAL_KEYS: Final = MappingProxyType(
    {
        "rk": "H1",
        "lb": "hdr-1",
        "ts": [3, 22],
        "q": [10_000, 20_000, 90_000, 20_000, 90_000, 44_000, 10_000, 44_000],
        "sc": [0.75, RICH_SCORE_KIND],
        "ld": "b1a2d9d51572349e7cec49b72ac6dd3f",
        "pl": {"level": 2},
        "x": {"x.acme.note": "kept across the wire"},
    }
)
"""The eight optional wire keys the rich heading carries, as the LITERALS both ends must show.

Every value is written down here and none is read back from a store, a manifest or the source
export -- which is the whole point, because both sides of the projection equality come from one
exporter over two stores, and an equality like that pins agreement and not value.

`ld` is the one entry that is not an input: `layout_digest` is `ow128(b'ow.layout.1',
[content_digest, page, quad in whole points])`, computed by `DocSink` and never supplied by a
draft (03:1202-1205). Pinning its hex here rather than recomputing it is deliberate -- a test
that recomputed the recipe would agree with a broken recipe. If it goes red, either the recipe,
`RICH_QUAD`, the heading's text or its kind/layer moved, and the failure names the key.
"""

RICH_ORIGINS: Final = MappingProxyType(
    {
        "doc": {"k": "none"},
        "p0/0": {"k": "glyphs", "part": "file", "extractor": "pdfium/1", "a": 0, "len": 19},
        "p0/1": {"k": "nodepath", "part": "file", "path": [1, 4, 3]},
        "p0/2": {"k": "pixels"},
        "p0/3": {"k": "none"},
        "p0/4": {"k": "bytes", "part": "file", "a": 20, "len": 23, "codec": "utf-8/strict"},
    }
)
"""All five `os` variants as the wire objects 03:671-675 fixes, addr by addr.

`pixels` carries neither a page nor a quad (03:779-783) -- the polygon IS `q` and the page IS
`p` -- so `{"k": "pixels"}` is the whole record and the reader rebuilds `OriginPixels` from the
other two keys. `bytes` and `glyphs` carry `(a, len)` and NEVER `(a, b)`, while `ts` carries a
half-open range. Two different quantities, two encodings, and this is where a round trip has to
keep them apart.
"""


def _write_rich_document(root: Path) -> tuple[Path, Path]:
    """A third document: six blocks, one page, every optional wire key but `dc`, all five `os`.

    The blocks, and what each is there for:

    * `doc` -- the `document` root. `os_kind = none` by default, `SYNTHETIC`.
    * `p0/0` -- a heading carrying `rk`, `lb`, `ts`, `q`, `sc`, `pl`, `x` and (via `q`) `ld`,
      over an `OriginGlyphs`. Seven supplied keys and one host-computed one on one record.
    * `p0/1` -- an `OriginNodePath` paragraph. The variant this file could not export at all.
    * `p0/2` -- an `OriginPixels` handwriting block. `Trust.INFERRED` and not `EXTRACTED`
      because `method = ocr_block` caps trust at `inferred` (03:1616-1622) and the clamp would
      write an `OW_GRAPH_TRUST_CLAMPED` diag into the source store, putting a `diags.json` in
      one export and a second diag in the other. The clamp has its own coverage in
      `test_store_doc.py`; here it would only add a member to the comparison.
    * `p0/3` -- an `OriginNone` paragraph in `Layer.NOTE`, so `ly` is not `body` on every row.
    * `p0/4` -- an `OriginBytes` paragraph whose text repeats `p0/1`'s, so two records share a
      `content_digest` and differ only in `os`: a projection keyed on `cd` would collapse them.

    Every `quote` is at or below its `os_kind`'s ceiling (`_MAX_QUOTE_BY_OS_KIND`, 03:1675-1681),
    so `_clamp_quote` is a no-op here and `qt` on the wire is the value this function asked for.
    No block claims `VERBATIM`: the claim would put `owcheck`'s bytes predicate in the middle of
    a test about wire keys, and section 5 already evaluates that predicate over 6,960 blocks.
    """
    path, cas, producer_id = _fresh(root, "rich.owstore")
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = _sink(thread, cas, producer_id, score_kinds=frozenset({RICH_SCORE_KIND}))
        sink.begin_doc(_doc_record(9, "file:///corpus/rich.pdf"))
        sink.begin_page(_page_record(0))
        root_block = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.HEADING,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root_block,
                text="Article 1. Schedule",
                raw_kind="H1",
                label="hdr-1",
                quad=RICH_QUAD,
                span=TextSpan(3, 22),
                origin=OriginGlyphs(part="file", extractor="pdfium/1", start=0, length=19),
                score=0.75,
                score_kind=RICH_SCORE_KIND,
                payload={"level": 2},
                x={"x.acme.note": "kept across the wire"},
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root_block,
                text="the body paragraph text",
                origin=OriginNodePath(part="file", path=(1, 4, 3)),
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.HANDWRITING,
                layer=Layer.BODY,
                method=Method.OCR_BLOCK,
                trust=Trust.INFERRED,
                quote=Quote.RECONSTRUCTED,
                parent=root_block,
                text="handwritten line",
                quad=RICH_QUAD,
                origin=OriginPixels(page=0, quad=RICH_QUAD),
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.NOTE,
                method=Method.NATIVE,
                trust=Trust.INFERRED,
                quote=Quote.NORMALIZED,
                parent=root_block,
                text="no origin at all",
                origin=OriginNone(),
            )
        )
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root_block,
                text="the body paragraph text",
                origin=OriginBytes(part="file", start=20, length=23, codec="utf-8/strict"),
            )
        )
        sink.add_part(
            "file",
            io.BytesIO(RICH_PART_BYTES),
            hashlib.sha256(RICH_PART_BYTES).digest(),
            len(RICH_PART_BYTES),
        )
        sink.end_page({})
        sink.end_doc("ok")
    return path, cas


@pytest.fixture
def rich_trip(tmp_path: Path) -> RoundTrip:
    """rich store -> `rich-a.owdoc` -> imported store -> `rich-b.owdoc`.

    `score_kinds` is given on BOTH sides: `sc` is a compared key and an importing sink with an
    empty register refuses a scored draft outright (`DocSink._validate_score`).
    """
    source, source_cas = _write_rich_document(tmp_path)
    exported = _export_store(source, source_cas, tmp_path / "rich-a.owdoc")
    imported, imported_cas = _import_archive(
        tmp_path,
        exported,
        "rich-imported.owstore",
        score_kinds=frozenset({RICH_SCORE_KIND}),
    )
    reexported = _export_store(imported, imported_cas, tmp_path / "rich-b.owdoc")
    return RoundTrip(source, source_cas, imported, imported_cas, exported, reexported)


def _raw_records(archive: Path, member: str) -> list[dict[str, Any]]:
    """One NDJSON member's records WITHOUT `_comparable()`'s narrowing.

    `_records()` drops `pd`, `oo` and `od` on the way past, which is right for the projection
    equality and wrong for a test ABOUT one of the three: a key the comparison does not see has
    to be read here or it is not read at all.
    """
    with zipfile.ZipFile(archive) as package:
        return [json.loads(line) for line in package.read(member).splitlines() if line]


def test_the_rich_document_populates_every_optional_wire_key_but_one(rich_trip: RoundTrip) -> None:
    """The fixture-shape assertion 11-repo-layout.md section 6.8 demands, for section 6.

    Eight of the ten optional keys carry a value on ONE record, `p0/0`, so the two tests below
    have something to lose. Each value is asserted against `RICH_OPTIONAL_KEYS`, which this file
    wrote down; nothing here reads a store.

    `dc` is the tenth and it is null on every record of all three documents, because
    `decision_id` is one of the two `block` columns 03:311 leaves off `Block`, `BlockDraft` has
    no field for it, and `DocSink.add_block` has nothing to write. IF THIS TEST GOES RED at the
    `dc` line because a `decision_id` writer landed, move `dc` into `RICH_OPTIONAL_KEYS` and
    delete the line: the gap is closed and the pin has done its job.
    """
    records = _records(rich_trip.exported)
    assert sorted(records) == list(RICH_MEMBERS), sorted(records)
    rows = records["blocks/000000.ndjson"]
    assert len(rows) == RICH_BLOCKS
    heading = next(row for row in rows if row["i"] == "p0/0")
    assert {key: heading[key] for key in RICH_OPTIONAL_KEYS} == dict(RICH_OPTIONAL_KEYS)
    assert [row["dc"] for row in rows] == [None] * RICH_BLOCKS, "`dc` has no writer; see 03:311"
    assert {row["ly"] for row in rows} == {"body", "note"}, "`ly` is not one value on every row"
    assert [row["t"] for row in rows].count("the body paragraph text") == 2, (
        "two records share a content_digest and differ only in `os`"
    )


def test_every_optional_wire_key_survives_the_round_trip_into_a_fresh_store(
    rich_trip: RoundTrip,
) -> None:
    """G28 over the eight keys sections 1 and 5 leave null, and pinned at BOTH ends.

    The member-for-member equality comes first, in the shape the rest of the file uses. But that
    equality alone would not have caught this: hard-coding all eight keys to their nulls inside
    `block_record()` blanks them on BOTH sides, so the two projections still agree and the round
    trip still looks lossless. So the second half re-asserts `RICH_OPTIONAL_KEYS`' literals
    against the RE-EXPORT -- the store the importer built -- which is a claim about a value and
    not about agreement.
    """
    before, after = _records(rich_trip.exported), _records(rich_trip.reexported)
    assert sorted(before) == list(RICH_MEMBERS), sorted(before)
    assert sorted(after) == list(RICH_MEMBERS), sorted(after)
    assert len(before["blocks/000000.ndjson"]) == RICH_BLOCKS
    assert len(after["blocks/000000.ndjson"]) == RICH_BLOCKS
    for member in RICH_MEMBERS:
        assert before[member] == after[member], f"{member} differs across the round trip"

    heading = next(row for row in after["blocks/000000.ndjson"] if row["i"] == "p0/0")
    assert {key: heading[key] for key in RICH_OPTIONAL_KEYS} == dict(RICH_OPTIONAL_KEYS)
    assert before["parts/file"] == after["parts/file"], "the retained part crossed two CAS roots"
    assert _rows(rich_trip.imported, "SELECT sha256 FROM part") == [
        (hashlib.sha256(RICH_PART_BYTES).digest(),)
    ]


def test_all_five_origin_span_variants_survive_a_real_store_round_trip(
    rich_trip: RoundTrip,
) -> None:
    """`os`, variant by variant, through `DocSink`'s seven columns and back out. 03 section 7.2.

    `test_archive_owdoc.py` round-trips all five through `block_record`/`read_block_record`
    against a hand-made `Block`. That is the CODEC. This is the STORE: `os_kind`, `os_part`,
    `os_a`, `os_b`, `os_path`, `os_extractor` and `os_codec` written by `add_block` and read back
    by `StoreExportSource`, which is where the `json.loads(os_path)` defect lived and where no
    test looked. Both ends are asserted against `RICH_ORIGINS`, which is a literal.

    The `(a, len)` versus half-open-range distinction is the load-bearing one (03:671-675):
    `p0/0` has `ts = [3, 22]` (a range, end exclusive) and `os.len = 19` (a length) on the SAME
    record, and 22 - 3 == 19, so a decoder that passed one as the other would produce a record
    that still looked plausible. Asserting both against literals is what separates them.

    WHAT THIS TEST CANNOT REACH, said rather than smoothed. `OriginPixels.quad` is not an
    independent fact in a store: 03:781-783 makes the polygon `q` and the page `p`, the `block`
    table has one `quad` column serving both, and `StoreExportSource` rebuilds the variant from
    that column -- so replacing `_read_origin`'s `quad=quad` with a zero `Quad` is INVISIBLE
    through a store round trip and stays invisible however this test is written. Its home is
    `test_archive_owdoc.py`'s `test_all_five_origin_span_variants_round_trip[origin3]`, which is
    a codec-level round trip over a hand-made `Block` and does catch it. `pixels`' `q` and `p`
    are asserted below because those two ARE persisted; the origin's copy of the quad is not.
    """
    for archive in (rich_trip.exported, rich_trip.reexported):
        rows = _records(archive)["blocks/000000.ndjson"]
        assert {row["i"]: row["os"] for row in rows} == dict(RICH_ORIGINS), archive.name
        heading = next(row for row in rows if row["i"] == "p0/0")
        assert heading["ts"] == [3, 22], "a half-open RANGE"
        assert heading["os"]["len"] == 19, "a LENGTH, and 22 - 3 == 19 is why both are pinned"
        pixels = next(row for row in rows if row["i"] == "p0/2")
        assert set(pixels["os"]) == {"k"}, "pixels carries neither a page nor a quad (03:781)"
        assert pixels["q"] == list(RICH_QUAD), "its polygon IS `q`"
        assert pixels["p"] == 0, "and its page IS `p`"
    assert _rows(
        rich_trip.imported,
        "SELECT b.addr, e.name, b.os_part, b.os_a, b.os_b, b.os_path, b.os_extractor, b.os_codec "
        "FROM block b JOIN enum_val e ON e.domain = 'origin_span_kind' AND e.ord = b.os_kind "
        "ORDER BY b.addr",
    ) == [
        ("doc", "none", None, None, None, None, None, None),
        ("p0/0", "glyphs", "file", 0, 19, None, "pdfium/1", None),
        ("p0/1", "nodepath", "file", None, None, "1.4.3", None, None),
        ("p0/2", "pixels", None, None, None, None, None, None),
        ("p0/3", "none", None, None, None, None, None, None),
        ("p0/4", "bytes", "file", 20, 23, None, None, "utf-8/strict"),
    ], "the seven os_* columns of the store the IMPORTER built, read without the exporter"


def test_the_producer_index_is_a_position_in_the_manifests_producers_list(
    trip: RoundTrip, tmp_path: Path
) -> None:
    """`pd` is an INDEX into `manifest.producers[]` and never a `producer_id` (03:666).

    `_comparable()` drops `pd` from the projection, and the reason given for dropping it covered
    `oo` and `od` and not this: two sinks built with one identity make those two agree by
    construction, but they say nothing about an index arithmetic. Nothing else in this file
    pinned `pd`, so `"pd": export_row.producer + 1` inside `block_record()` was green over every
    assertion in sections 1 through 5 -- every block in the archive attributed to a producer one
    past its own, which is the provenance INV-6 exists to make trustworthy.

    A SECOND `producer` row is inserted and ONE block re-pointed at it, so the index is 0 for
    five records and 1 for one and a mutation cannot hide inside a single-producer document. The
    expected `pd` per `addr` and the two `producers[]` entries are literals; `pd` is read through
    `_raw_records`, because the comparison the rest of the file makes cannot see it.
    """
    _perturb(
        trip.source,
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES(?, ?, ?, X'01')",
        ("derive.spine", 2, "def456"),
    )
    _perturb(
        trip.source,
        "UPDATE block SET producer_id = (SELECT max(producer_id) FROM producer) WHERE addr = ?",
        ("p1/0",),
    )
    archive = _export_store(trip.source, trip.source_cas, tmp_path / "two-producers.owdoc")
    producers = _records(archive)["manifest.json"]["producers"]
    assert producers == [
        {"operator": "parse.pdf", "op_version": 1, "code_fingerprint": "abc123"},
        {"operator": "derive.spine", "op_version": 2, "code_fingerprint": "def456"},
    ]
    rows = _raw_records(archive, "blocks/000000.ndjson")
    assert {row["i"]: row["pd"] for row in rows} == {
        "doc": 0,
        "p0/0": 0,
        "p1/0": 1,
        "p1/0/r0c0": 0,
        "p1/0/r1c0": 0,
        "p1/0/r1c1": 0,
    }
    assert all(0 <= row["pd"] < len(producers) for row in rows), "`pd` indexes `producers[]`"


class _RecordingSink:
    """A `DocSinkLike` that records and validates nothing. What `import_` ACTUALLY hands a sink.

    Every assertion above about the imported side reads a store that `_ImportSink` wrote, and
    `_ImportSink`'s first workaround is to POP `x["x.ow.addr"]` and `x["x.ow.cite"]` off every
    draft before `DocSink` sees them -- because `DocSink._validate_x` refuses the reserved `ow`
    vendor segment. So no assertion in sections 1 through 5 can see either key, and the store's
    `cite` column is whatever `_mint_cite` minted on the way in. This sink is how the archive's
    own `c` becomes observable: it keeps the draft exactly as `import_` built it.

    `add_block` returns the `addr` as the block's identity, which is what makes `parent` legible
    in the recording -- `import_` puts whatever this returns into its `addr -> id` map and hands
    it back as the next draft's `parent`.
    """

    def __init__(self) -> None:
        self.drafts: list[BlockDraft] = []
        self.pages: list[int] = []
        self.rels: list[tuple[Any, Any, RelKind]] = []
        self.grids: list[tuple[Any, Any]] = []
        self.marks: list[tuple[Any, int]] = []
        self.parts: list[tuple[str, bytes, int, int | None]] = []
        self.assets: list[tuple[Any, int]] = []
        self.stats: list[Mapping[str, Any]] = []
        self.diags: list[Mapping[str, Any]] = []
        self.status: str | None = None

    def begin_doc(self, rec: Any) -> Any:
        return rec

    def begin_page(self, page: Any) -> None:
        self.pages.append(int(page["page"]))

    def add_block(self, b: BlockDraft) -> Any:
        self.drafts.append(b)
        return b.x["x.ow.addr"]

    def add_marks(self, b: Any, marks: Sequence[Mark]) -> None:
        self.marks.append((b, len(marks)))

    def add_grid(self, b: Any, g: Any) -> None:
        self.grids.append((b, g))

    def add_rel(self, src: Any, dst: Any, kind: RelKind, **_kwargs: Any) -> None:
        self.rels.append((src, dst, kind))

    def add_asset(self, a: Any, blob: Any) -> int:
        self.assets.append((a["sha256"], len(blob.read())))
        return len(self.assets)

    def add_part(self, path: str, blob: Any, sha256: bytes, byte_len: int) -> None:
        payload = None if blob is None else len(blob.read())
        self.parts.append((path, sha256, byte_len, payload))

    def diag(self, d: Any) -> None:
        self.diags.append(dict(d))

    def end_page(self, stats: Mapping[str, Any]) -> None:
        self.stats.append(dict(stats))

    def end_doc(self, status: str) -> Any:
        self.status = status
        return status

    def carried(self) -> list[tuple[str, str, Any]]:
        """`(addr, cite, parent)` per draft, in the order `import_` emitted them."""
        return [(d.x["x.ow.addr"], d.x["x.ow.cite"], d.parent) for d in self.drafts]


def test_import_hands_the_sink_the_durable_cite_the_archive_carries(trip: RoundTrip) -> None:
    """`c` is DURABLE and cannot be re-minted (03:687, 16-roadmap.md:426-431). Cashed, not stated.

    The module docstring used to close its `cite` paragraph with "agreement here is therefore an
    assertion about the replay order, not a tautology --
    `test_a_changed_cite_in_the_source_turns_the_comparison_red` proves the comparison sees a
    cite". Half of that is true: that test proves `_records()` reads the `c` KEY. It says nothing
    about whether `import_` carries the archive's `c` anywhere, and it cannot, because
    `_ImportSink` pops `x["x.ow.cite"]` before `DocSink` sees it and the imported store then
    mints its own. Replacing `cite=Cite(str(record["c"]))` with `cite=Cite("d1#1")` inside
    `read_block_record` -- an importer that discards the durable cite entirely -- left all
    twenty-six tests in this file GREEN.

    So this test reaches the one place the archive's cite is observable: the draft `import_`
    builds. The six cites are the literals
    `test_the_imported_store_re_mints_the_cites_the_archive_carries` already writes down, and
    they are asserted here as what the ARCHIVE delivered rather than as what a second minting run
    produced. `parent` is recorded beside each, because `add_block`'s return value is this sink's
    identity for a block, so the recording also shows that every non-root draft names a parent
    the sink had already been handed.
    """
    sink = _RecordingSink()
    report = import_(trip.exported, sink)
    assert sink.carried() == [
        ("doc", "d1#1", None),
        ("p0/0", "d1#2", "doc"),
        ("p1/0", "d1#3", "doc"),
        ("p1/0/r0c0", "d1#4", "p1/0"),
        ("p1/0/r1c0", "d1#5", "p1/0"),
        ("p1/0/r1c1", "d1#6", "p1/0"),
    ]
    assert report.blocks == FIXTURE_BLOCKS
    assert sink.pages == [0, 1]
    assert sink.marks == [("p0/0", 2)], "the frame-aligned marks member reached its own block"
    assert sink.rels == [("p0/0", "p1/0", RelKind.CAPTION_OF)]
    assert sink.parts == [("file", PART_SHA256, PART_BYTES, None)], "03:2494's `present: false`"
    assert sink.assets == [(ASSET_SHA256, len(ASSET_BYTES))]
    assert sink.stats == [{"blocks": 2}, {"blocks": 4}]
    assert sink.status == "ok"


class _WithoutOneBlock:
    """`StoreExportSource` minus one block, so its children's computed `pa` names nothing.

    `pa` is COMPUTED from `i` by the writer (`owdoc.parent_addr`) and never looked up, so an
    archive can carry a child whose parent record is absent without the writer noticing --
    truncation, a partial export, a hand-edited frame. `rels` and `grids` are emptied too, so
    that the ONE defect in the archive is the dangling parent: a missing table would otherwise
    also dangle a `rel` endpoint and a `grids.ndjson` origin, each of which has its own branch.
    """

    def __init__(self, inner: StoreExportSource, drop: str) -> None:
        self._inner = inner
        self._drop = drop

    def header(self) -> DocHeader:
        return self._inner.header()

    def blocks(self) -> Any:
        return (row for row in self._inner.blocks() if str(row.block.addr) != self._drop)

    def rels(self) -> Any:
        return ()

    def grids(self) -> Any:
        return ()

    def parts(self) -> Any:
        return self._inner.parts()

    def assets(self) -> Any:
        return self._inner.assets()

    def views(self) -> Any:
        return ()

    def diags(self) -> Any:
        return ()

    def toc(self) -> Any:
        return ()


def test_import_re_roots_a_block_whose_parent_the_archive_omits_and_says_nothing(
    trip: RoundTrip, tmp_path: Path
) -> None:
    """A DEFECT PIN. `_add_one` resolves a parent with `ids.get()` and does not diagnose a miss.

    `_apply_rels` has the matching branch and DOES diagnose it -- "rel <src> -> <dst> names an
    addr not in this archive" plus an `OW_MODEL` warning, which
    `test_import_replays_a_rel_only_when_both_endpoints_are_in_the_archive` covers in
    `test_archive_owdoc.py`. A BLOCK whose `pa` names an absent record gets no such treatment:
    `draft.parent` is silently `None`, so the block is re-rooted, and a real `DocSink` would then
    mint it a NEW `addr` from its new position -- the archive's `p1/0/r0c0` becoming a child of
    the `document` root. An `import(export(store))` over such an archive is not lossless, and it
    reports `status = ok` with an empty `diagnostics`.

    Nothing tested that branch either way: making `import_` SKIP such a block instead
    (`if row.parent is not None and str(row.parent) not in ids: continue`) left all twenty-six
    tests in this file and all eighty-three in `test_archive_owdoc.py` green, because no archive
    either file builds has a dangling parent. This one does: `_WithoutOneBlock` drops the table
    `p1/0` and leaves its three cells behind.

    The recording sink is used rather than a real `DocSink` deliberately. `add_block` refuses a
    parentless non-`document` block outright (`store/doc.py`, 03:1096), so a real store turns
    this into a raise; what is pinned here is what the CODEC does before the sink gets a say, and
    that it does it in silence.

    IF THIS TEST GOES RED because `import_` grew a diagnostic or a refusal: that is the fix, and
    the two candidate forms are `_apply_rels`' warning-and-skip or a `ModelError` naming the
    absent `pa`. Re-point the assertions at whichever landed and delete this paragraph.
    """
    target = tmp_path / "orphaned.owdoc"
    connection = ow.connect_readonly(trip.source)
    try:
        export(_WithoutOneBlock(StoreExportSource(connection, trip.source_cas), "p1/0"), target)
    finally:
        connection.close()
    orphaned = _raw_records(target, "blocks/000000.ndjson")
    assert len(orphaned) == FIXTURE_BLOCKS - 1
    assert [row["pa"] for row in orphaned].count("p1/0") == 3, "three records name an absent `pa`"

    sink = _RecordingSink()
    report = import_(target, sink)
    assert sink.carried() == [
        ("doc", "d1#1", None),
        ("p0/0", "d1#2", "doc"),
        ("p1/0/r0c0", "d1#4", None),
        ("p1/0/r1c0", "d1#5", None),
        ("p1/0/r1c1", "d1#6", None),
    ], "every record still arrives, and the three orphans arrive RE-ROOTED"
    assert report.blocks == FIXTURE_BLOCKS - 1, "not one of them was skipped"
    assert report.diagnostics == (), "and the re-rooting is not diagnosed anywhere"
    assert report.status == "ok", "so an archive with a dangling parent imports as `ok`"
