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
Agreement here is therefore an assertion about the replay order, not a tautology --
`test_a_changed_cite_in_the_source_turns_the_comparison_red` proves the comparison sees a cite.

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

Specified in 00-vision.md:708 (V01-7), 02-architecture.md:249, 03-document-model.md:1083, :2485-
2497 (the container) and :2519 (the comparison), 16-roadmap.md:418 (W2.5) and :550 (G19's export
diff), and `tools/gates.toml`'s G28 row.

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
import io
import json
import sqlite3  # noqa: TID251 -- see the module docstring: this file drives two REAL stores.
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from omniweave_core.archive import (
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
"""The asset payload, and it deliberately contains no `0x0A`.

`BlobStore._create_tmp` opens the staging file with `os.open(..., O_WRONLY | O_CREAT | O_EXCL)`
and no `os.O_BINARY`, which on Windows is TEXT mode: every `\\n` in a blob is written as `\\r\\n`,
so the CAS stores bytes that do not hash to their own name and `add_asset` then refuses the
re-import with `OW_ASSET_DIGEST_MISMATCH`. That is a defect in `blobs.py`, not in the codec, and
it is reported as a required edit rather than worked around silently -- this constant is the
workaround, named here so that removing it is a one-line change once the flag lands."""

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


def _sink(thread: Any, cas: Path, producer_id: int) -> DocSink:
    return DocSink(
        thread,
        producer_id=producer_id,
        origin_operator=OPERATOR,
        origin_driver=ORIGIN_DRIVER,
        driver_schema_v=DRIVER_SCHEMA_V,
        blobs=BlobStore(cas),
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
            part=r["os_part"], path=tuple(json.loads(r["os_path"]))
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


def _import_archive(root: Path, archive: Path, name: str = "imported.owstore") -> tuple[Path, Path]:
    """Replay an archive into a SECOND, FRESH store through a second real `DocSink`."""
    path, cas, producer_id = _fresh(root, name)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        import_(
            archive,
            _ImportSink(_sink(thread, cas, producer_id)),
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
so an equality over these keys would compare two constructor calls and could not fail.
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
    assert len(records["blocks/000000.ndjson"]) == 6, records["blocks/000000.ndjson"]
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
    """
    before, after = _records(trip.exported), _records(trip.reexported)
    assert sorted(before) == sorted(after), "the two archives do not even hold the same members"
    for member in sorted(before):
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
