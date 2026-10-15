"""A stored document as an `ExportSource`: `export()` pointed at a real `.owstore`. **D847.**

02-architecture.md:249 gives the archive a lossless projection, *"`import(export(store)) ==
store`"*, and `omniweave_core.archive.export` is typed against `ExportSource`, never a connection.
G28's round trip (`test_owdoc_roundtrip.py`) built the adapter that reads one document's committed
generation out of a store, and kept it in the test. D847 moves it here, unchanged in what it
reads, because a store-backed export is needed by more than one test:
- Reductions over a stored fixture (`omniweave_conform.reduce` reads an `ExportSource`'s five
  reads);
- an `.owdoc` written from a store;
- the `Doc` handle's export half.

## Rulings

1. **It lives in `omniweave_core.store`**, the one package `sqlite3` may be imported in (INV-17).
   The store already imports the archive's types, and the archive never imports the store, so
   the direction is the existing one.
2. **It reads `[SOR]` tables only**: `doc`, `block`, `mark`, `rel`, `table_meta`, `cell`, `part`,
   `asset`, `block_asset`, `producer`, `diag` and `enum_val`. `grid_slot` is `[DER]` and never
   read. `views()` and `toc()` are empty, since `serialize()` is not an L2 table.
3. **A missing `doc_ord` is `NotFoundError`.** The test's `AssertionError` was a test's habit. A
   store with no such document is a fact about the store, and the fix names the listing.
4. **Every decoding is the test's, byte for byte.** `quad` is 8 x i32 LE, `nodepath` is
   dot-joined, `pd` is an index into `manifest.producers[]`, and `os_b` is a length. The G28 tests
   that found each of those now import this class, so they hold it where it ships.

Specified in 02-architecture.md row 25, 03-document-model.md sections 3.1 and 13, and
16-roadmap.md W2.5.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from omniweave_core.archive import (
    AssetRow,
    BlockExport,
    DocHeader,
    GridRow,
    PartRow,
    RelRow,
)
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import NotFoundError
from omniweave_core.model import (
    Addr,
    BlockId,
    Cite,
    Kind,
    Layer,
    Method,
    Quad,
    Quote,
    RelKind,
    Trust,
)
from omniweave_core.model.block import Block, Mark
from omniweave_core.model.spans import (
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    TextSpan,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["StoreExportSource"]


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

    It reads `[SOR]` tables only (03:2474), and it is the same code whichever store it reads, so a
    difference between two projections is a difference between the stores. Until D847 this class
    lived in `test_owdoc_roundtrip.py`, whose docstring said it *"belongs in the tree and does not
    yet exist there"*. `Doc`, the lazy read handle of 03:2584-2606, will satisfy `ExportSource`
    structurally when it lands. This is the export half of that handle, and nothing else.
    """

    def __init__(self, connection: sqlite3.Connection, cas: Path, doc_ord: int = 1) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._cas = cas
        self._doc_ord = doc_ord
        row = connection.execute("SELECT * FROM doc WHERE doc_ord = ?", (doc_ord,)).fetchone()
        if row is None:
            raise NotFoundError(
                f"no document at doc_ord {doc_ord} in this store",
                fix="ow corpora   # the documents a store holds, with their ordinals",
            )
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
