"""`ow store export --portable` -- the store as one `.owdoc` per document, and nothing else.

07-store-and-retrieval.md:3092-3096 is the whole of this module's law, and it draws the line
between two verbs that both produce a file:

    `ow store backup` is a `VACUUM INTO` (atomic, no torn WAL). `ow store export --portable`
    writes **one `.owdoc` per document** as a *transport* artefact -- a plain ZIP that
    `unzip -l` and `jq` both read with no external tool. An archive contains **no `block_id`**:
    every internal reference in it is an `addr`, and import assigns fresh ids. That is what
    makes an archive portable between stores and what makes the G19 export-diff sound.
    `import(export(store)) == store` over the fixture corpus is gate **G6**, per INV-1.

`maintenance.backup()` is the first sentence and already exists. This module is the second, and
it is a different artefact for a different reason: 00-vision.md:429 makes it the sanctioned exit
under NG-4 (*"Not a vector database, graph database or search engine"*) -- *"export with
`ow store export --portable` and index it yourself"*. The consumer is explicitly **not**
omniweave, so the format is constrained by who has to read it and not by what is convenient to
write: a ZIP whose members are JSON and NDJSON, no block ids, no store-local integers, nothing
that needs this library to interpret.

WHAT THIS MODULE IS, AND WHAT IT IS NOT
----------------------------------------
`omniweave_core.archive.owdoc.export(source, path)` already writes the format, byte-stably, from
an `ExportSource` -- nine read methods that are deliberately neither `Store` nor `Reader`
(`owdoc.py`, `ExportSource`'s docstring). What did not exist is an `ExportSource` over a
`.owstore`, and `_StoreDocument` is exactly that and nothing more. There is no second codec here:
every byte of the archive is written by `archive/owdoc.py`, so a format change lands in one file.

`ExportSource`'s docstring names the type that will eventually satisfy it -- `Doc`, the lazy read
handle of 03-document-model.md:2584-2606 -- and says "when `Doc` lands it satisfies this protocol
structurally and `export(doc, path)` is the call". `Doc` has no store-backed implementation yet
(`model/doc.py` defines `DocReadSide` as a Protocol and nothing in the tree implements it over
SQLite), so `_StoreDocument` is the interim. It is deliberately private: when the store-backed
`Doc` lands, `export_portable` calls it and this class is deleted, which is a smaller change than
un-publishing a name.

THE THREE PROPERTIES THE PLAN CLAIMS, AND WHERE EACH IS MADE TRUE
------------------------------------------------------------------
1. **"a plain ZIP that `unzip -l` and `jq` both read with no external tool."** `archive/owdoc.py`
   writes `zipfile.ZIP_DEFLATED` with every clock- and platform-dependent field pinned, and every
   member is UTF-8 JSON or NDJSON. `test_store_inspect.py` proves the claim the only way it can be
   proved -- by reading an exported artefact back with `zipfile` and `json` and nothing else, no
   `omniweave_core` import on the reading side at all.
2. **"An archive contains no `block_id`."** Three places in this module could leak one and each is
   closed by construction, not by a filter at the end:
   * a block's own id never reaches the record -- `block_record` emits `i` (the `addr`) and `pa`
     (the parent's `addr`), and `BlockExport` carries no id column;
   * `rel.src_id`/`dst_id` are translated to addresses through `_addr_of`, which raises on a miss
     rather than emitting the integer;
   * `diag.block_id` is translated the same way -- and it is the one that needed thought, because
     `0001_init.sql:461` says that column is deliberately NOT a foreign key ("a diagnostic often
     concerns a block the parse then refused to write"). An unresolvable diag id is therefore a
     real state, and the record carries `addr: null` plus `unresolved_block: true` rather than the
     integer. Dropping the diagnostic would lose a fact; keeping the id would break portability.
   `producer_id` is the fourth store-local integer and it is handled by the format itself:
   `BlockExport.producer` is an INDEX into `manifest.producers[]` (03:666), which `_producers`
   builds.
3. **"import assigns fresh ids"** is `archive.import_`'s and is not restated here.

WHAT AN ARTEFACT IS CALLED, AND WHY IT IS NOT NAMED BY `doc_ord`
-----------------------------------------------------------------
`<doc_key hex>.owdoc`, lower-case, in the caller's directory. `doc_key` is
`sha256(NORMALIZED source bytes)[:16]` (`0001_init.sql:150`) and is the same value in every store
that ever ingested those bytes; `doc_ord` is *"corpus-local; the number inside a `cite`"* (:149)
and would name the same document differently in two corpora, which is precisely the property
07:3078 says an archive must not carry. The file name is therefore a fact about the document and
not about this store, and two exports of one corpus from two machines produce the same set of
names.

WHAT IS EXPORTED, AND THE FOUR THINGS THAT ARE NOT
----------------------------------------------------
The head generation of every `doc` row, one archive each. Blocks, marks, rels, grids, parts,
assets and diags come out of the store; four members are empty and each for a stated reason:

* **`views/`** -- there is no `view` table in the shipped schema. A serialized view is
  `omniweave_core.model.serialize`'s output and is not a stored row, so there is nothing to read.
* **`toc.json`** -- likewise: 03:2491's table of contents is derived from the heading spine at
  render time and no migration stores one.
* **`grid_slot`** -- deliberately, and the reason is the archive's: `GridRow`'s docstring says
  03:2467 classifies it `[DER]` and "exporting a derived cover map would put a second, staler
  truth in the archive".
* **part and asset BYTES** -- unless a `BlobStore` is handed in. `part.store_ref` and
  `asset.store_ref` are `cas://` references and the CAS is a directory beside the store, not
  inside it (`blobs.py`); `PartRow.present = False` is 03:2488's "OPTIONAL (present:false)" and
  carries the path, `sha256` and `byte_len` regardless, which is what lets INV-10's `glyphs`
  branch name the part it could not read.

DEFECTS
--------
**DEFECT 1 -- `(page, ord)` is not a total order over a document's blocks, and 03:2624 treats it
as one.** `ExportSource.blocks()` is specified to yield in `(page, ord)` order and `Frame` records
`(lo_page, lo_ord)`/`(hi_page, hi_ord)` bounds from it. But `ord` is *"position among siblings"*
(`0001_init.sql:242`) and the uniqueness the schema enforces is `block_sib`, UNIQUE
`(doc_ord, gen, IFNULL(parent_id,-1), ord)` -- so a page root and its first child both have
`ord = 0` on the same page, and two blocks tie. A tie under `ORDER BY` is resolved by storage
order, which `VACUUM` and an FTS `optimize` both change (07:218-219, and P-10 at
13-quality.md:874 is the property test that exists because of it). An export whose member bytes
move after a `VACUUM` is not byte-stable, so `_BLOCKS_SQL` breaks the tie on `addr`, which
`block_addr` makes UNIQUE per `(doc_ord, gen)`. Reported: the plan owes `(page, ord, addr)` or an
equivalent third key wherever it says `(page, ord)`.

**DEFECT 2 -- `MODEL_VERSION` is the archive's constant and `doc.model_version` is a column, and
nothing reconciles them.** `manifest.model_version` defaults to `archive.manifest.MODEL_VERSION`;
the `doc` row carries its own `model_version` TEXT ("1.1"). This module puts the stored value in
`source["model_version"]` and leaves the manifest key to the archive's constant, because the
manifest key means "the model version these RECORDS are written in" (which is this build's) while
the column means "the model version the document was parsed under". Two facts, two homes; the
plan names neither relationship. Reported.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple

from omniweave_core.archive.manifest import Manifest
from omniweave_core.archive.owdoc import (
    AssetRow,
    BlockExport,
    DocHeader,
    GridRow,
    PartRow,
    RelRow,
    ViewRow,
    export,
)
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import StoreError
from omniweave_core.model.block import Addr, Block, BlockId, Cite, Mark
from omniweave_core.model.enums import Kind, Layer, Method, OsKind, Quote, RelKind, Trust
from omniweave_core.model.spans import (
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    OriginSpan,
    Quad,
    TextSpan,
)

__all__ = [
    "ARCHIVE_SUFFIX",
    "PortableArtefact",
    "PortableExport",
    "export_portable",
]

ARCHIVE_SUFFIX: Final = ".owdoc"
"""The transport artefact's extension. 07:3092 and 03-document-model.md section 13.1."""

_FIX_EXPORT: Final = "ow store export --portable"
"""The verb every refusal in this module names."""

_QUAD_STRUCT: Final = struct.Struct("<8i")
"""`block.quad` is *"8 x i32 LE, or NULL"* (`0001_init.sql:258`, 03:2338)."""


# ---------------------------------------------------------------------------------------------
# 1. The result.
# ---------------------------------------------------------------------------------------------


class PortableArtefact(NamedTuple):
    """One document's archive: where it went, what identifies it, and what it holds.

    `doc_ord` is here and is deliberately NOT inside the file: a caller that just exported a
    corpus needs to map artefacts back to the store it exported them from, and that mapping is
    the caller's to keep. Putting it in the manifest would make the archive corpus-local, which
    is the one thing 07:3078 says it must not be.
    """

    doc_ord: int
    doc_key: str
    gen: int
    path: Path
    manifest: Manifest


class PortableExport(NamedTuple):
    """Every artefact `export_portable` wrote, in `doc_key` order.

    `skipped` names the documents that produced no archive and why -- a `doc` row with no
    `document` block at its head generation is the only case, and it is reported rather than
    raised so one unfinished document cannot cost a caller a whole corpus export.
    """

    artefacts: tuple[PortableArtefact, ...]
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def documents(self) -> int:
        """How many archives were written."""
        return len(self.artefacts)

    @property
    def blocks(self) -> int:
        """Every block in every archive, from the manifests rather than from a second count."""
        return sum(int(a.manifest.counts.get("blocks", 0)) for a in self.artefacts)


# ---------------------------------------------------------------------------------------------
# 2. The verb.
# ---------------------------------------------------------------------------------------------

_DOCS_SQL: Final = """
SELECT doc_ord, doc_key, gen, status, source_sha256, normalizer, uri, media_type, format,
       format_evidence, source_bytes, page_count, model_version, declared, achieved,
       confidence, timings_ms, x
  FROM doc
 ORDER BY doc_key
"""
"""Every document at its head generation, in `doc_key` byte order.

`doc.gen` is *"THE HEAD GENERATION. One doc row per doc_key"* (`0001_init.sql:158`), so there is
no `WHERE gen = ...` to write: the row IS the head. Ordering by `doc_key` rather than `doc_ord`
makes the sequence of artefacts a function of the documents and not of the order this corpus
happened to ingest them, which is the same choice `omniweave.index.lock` makes and for the same
reason (01-principles.md:688).
"""


def export_portable(
    connection: sqlite3.Connection,
    directory: str | Path,
    *,
    blobs: BlobStore | None = None,
) -> PortableExport:
    """Write one `.owdoc` per document into `directory`. 07:3092.

    Becomes `ow store export --portable` at P7. Read-only against the store: it opens no
    connection, takes no clock and writes nothing back -- every write goes to the caller's
    directory through `archive.export`, which stages each archive beside its target and
    `Path.replace`s it into place, so a crash leaves no truncated ZIP.

    `blobs` is the CAS the `cas://` references in `part.store_ref` and `asset.store_ref` point
    into. Without it the artefacts carry every part's and asset's path, `sha256` and `byte_len`
    with `present = false`, which is 03:2488's own spelling for "the bytes did not travel" and is
    what `[store] retain_parts = "none"` produces anyway. With it the bytes are embedded and the
    archive is self-contained.

    **The directory must exist.** Creating it would make a read-only verb create a tree, and the
    caller who chose the path is the one who knows whether a typo should produce a new directory
    or an error.
    """
    target = Path(directory)
    if not target.is_dir():
        raise StoreError(
            f"{target} is not an existing directory: `export --portable` writes one archive per "
            f"document into a directory the caller has already chosen",
            fix=_FIX_EXPORT,
        )
    artefacts: list[PortableArtefact] = []
    skipped: list[tuple[str, str]] = []
    for row in connection.execute(_DOCS_SQL).fetchall():
        doc_ord = int(row[0])
        doc_key = bytes(row[1]).hex()
        gen = int(row[2])
        document = _StoreDocument(connection, row=row, blobs=blobs)
        if document.root_addr is None:
            skipped.append(
                (doc_key, f"no `document` block at gen {gen}: nothing to export (03:1096)")
            )
            continue
        path = target / f"{doc_key}{ARCHIVE_SUFFIX}"
        manifest = export(document, path)
        artefacts.append(PortableArtefact(doc_ord, doc_key, gen, path, manifest))
    return PortableExport(artefacts=tuple(artefacts), skipped=tuple(skipped))


# ---------------------------------------------------------------------------------------------
# 3. The `ExportSource` over one document of one store.
# ---------------------------------------------------------------------------------------------

_BLOCKS_SQL: Final = """
SELECT block_id, addr, cite, page, parent_id, ord, kind, raw_kind, layer, label, text,
       content_digest, layout_digest, revision, quad, os_kind, os_part, os_a, os_b, os_path,
       os_extractor, os_codec, ts_a, ts_b, producer_id, method, trust, quote, score, score_kind,
       origin_operator, origin_driver, driver_schema_v, restriction_bits, decision_id, payload,
       state, x
  FROM block
 WHERE doc_ord = ? AND gen = ?
 ORDER BY page, ord, addr
"""
"""Every block of one generation, in frame order. **`addr` is the tiebreak; see DEFECT 1.**"""

_MARKS_SQL: Final = """
SELECT m.block_id, m.a, m.b, m.kind, m.value
  FROM mark m JOIN block b ON b.block_id = m.block_id
 WHERE b.doc_ord = ? AND b.gen = ?
 ORDER BY m.block_id, m.a, m.b, m.mark_id
"""
"""Every mark of one generation, ordered so a block's marks are stable under a `VACUUM`.

`mark_id` is a SURROGATE and two marks may cover exactly the same range (`0001_init.sql:352`),
so `(a, b)` alone is not a total order and the surrogate is the third key. It never reaches the
archive -- `mark_records` emits `[a, b, kind, value]` -- it only fixes the sequence.
"""

_RELS_SQL: Final = """
SELECT src_id, dst_id, kind, producer_id, trust, score, score_kind, origin_operator, x
  FROM rel
 WHERE doc_ord = ? AND gen = ?
 ORDER BY src_id, dst_id, kind, producer_id
"""
"""The closed intra-document DAG. The `ORDER BY` is `rel`'s own UNIQUE identity, so it is total."""

_GRIDS_SQL: Final = """
SELECT t.block_id, t.n_rows, t.n_cols, t.row_len, t.header_rows, t.header_cols, t.kind,
       t.recon_strategy, t.recon_score, t.has_merges, t.native_part, t.native_sha256
  FROM table_meta t JOIN block b ON b.block_id = t.block_id
 WHERE b.doc_ord = ? AND b.gen = ?
 ORDER BY t.block_id
"""

_CELLS_SQL: Final = """
SELECT c.table_id, c.r, c.c, c.row_span, c.col_span
  FROM cell c JOIN block b ON b.block_id = c.table_id
 WHERE b.doc_ord = ? AND b.gen = ?
 ORDER BY c.table_id, c.r, c.c
"""

_PARTS_SQL: Final = """
SELECT path, sha256, byte_len, store_ref FROM part WHERE doc_ord = ? ORDER BY path
"""

_ASSETS_SQL: Final = """
SELECT asset_id, media_type, origin_part, sha256, byte_len, width, height, licence, spdx,
       source_url, restriction_bits, store_ref
  FROM asset
 WHERE doc_ord = ?
 ORDER BY sha256, IFNULL(origin_part, '')
"""
"""Assets in `asset_identity`'s own key order (`0001_init.sql:435`), which is total."""

_ROLES_SQL: Final = """
SELECT ba.asset_id, b.addr, ba.role
  FROM block_asset ba JOIN block b ON b.block_id = ba.block_id
 WHERE b.doc_ord = ? AND b.gen = ?
 ORDER BY ba.asset_id, b.addr, ba.role
"""

_DIAGS_SQL: Final = """
SELECT page, block_id, part, code, severity, component, message, detail, fatal
  FROM diag
 WHERE doc_ord = ? AND gen = ?
 ORDER BY code, IFNULL(page, -1), IFNULL(block_id, -1), message
"""

_PRODUCERS_SQL: Final = """
SELECT producer_id, operator, op_version, code_fingerprint, model_id, model_rev, runtime,
       runtime_version, prompt_fp, options_digest
  FROM producer
 ORDER BY producer_id
"""

_ENUM_SQL: Final = "SELECT domain, name, ord FROM enum_val"

_ROOT_ADDR: Final = "doc"
"""The parentless block's address. Minted in exactly one place, `store/doc.py:1501`."""


class _StoreDocument:
    """One document of one store, shaped as `archive.owdoc.ExportSource`. Nine read methods.

    Constructed per document and used once. It holds the block-id-to-address map for the
    generation it is exporting, which is the one thing every other method needs and the one
    thing the archive may not contain: `rel`, `block_asset` and `diag` all address blocks by
    `block_id` in the store, and every one of them leaves here as an `addr`.

    **Resident state is bounded by the document, not by the corpus**, which is the bound
    03:2574-2582 states ("a 5,000-page document never exists in memory"). Two maps are built
    eagerly -- the address map and the marks -- because both are keyed by `block_id` while the
    block stream is ordered by `(page, ord, addr)`, so neither can be walked in step with it.
    `MAX_BLOCKS_PER_DOC` and `MAX_MARKS_PER_BLOCK` are what bound them, and when the store-backed
    `Doc` lands with its 512-block mark window (03 section 2.7) the marks map goes with it.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        row: Sequence[Any],
        blobs: BlobStore | None,
    ) -> None:
        self._c = connection
        self._blobs = blobs
        self._doc_ord = int(row[0])
        self._doc_key = bytes(row[1]).hex()
        self._gen = int(row[2])
        self._row = row
        self._enums = _enum_map(connection)
        self._addr: dict[int, str] = {
            int(block_id): str(addr)
            for block_id, addr in connection.execute(
                "SELECT block_id, addr FROM block WHERE doc_ord = ? AND gen = ?",
                (self._doc_ord, self._gen),
            )
        }
        self._marks = _marks_by_block(connection, self._doc_ord, self._gen)
        self._producers, self._producer_index = _producers(connection)

    # -- identity ------------------------------------------------------------

    @property
    def root_addr(self) -> str | None:
        """`'doc'` when this generation has its `document` block, else `None`.

        A `doc` row whose head generation has no root block is a document `end_doc` never
        finished. `export_portable` skips it with a reason rather than writing an archive whose
        `manifest.counts` claims a document nobody can render.
        """
        return _ROOT_ADDR if _ROOT_ADDR in self._addr.values() else None

    # -- the nine ------------------------------------------------------------

    def header(self) -> DocHeader:
        """`manifest.json`'s projection of the `doc` row. 03:2482-2484's key set.

        `source` carries the columns that describe the bytes this document came from, and
        `source_sha256` is spelled hex because 03:665 fixes hex as the wire spelling of every
        digest. `format_evidence` is re-parsed from its stored JSON rather than passed through as
        a string: the manifest is JSON, and a JSON string containing JSON is what a consumer with
        `jq` and nothing else cannot walk.
        """
        row = self._row
        return DocHeader(
            doc_key=self._doc_key,
            gen=self._gen,
            status=str(row[3]),
            source={
                "uri": str(row[6]),
                "media_type": str(row[7]),
                "format": str(row[8]),
                "sha256": bytes(row[4]).hex(),
                "normalizer": None if row[5] is None else str(row[5]),
                "bytes": int(row[10]),
                "page_count": None if row[11] is None else int(row[11]),
                "model_version": str(row[12]),
                "format_evidence": _json_object(row[9]),
            },
            declared=_json_object(row[13]),
            achieved=_json_object(row[14]),
            producers=self._producers,
            confidence=_json_object(row[15]),
            timings_ms=_json_object(row[16]),
            x=_json_object(row[17]),
        )

    def blocks(self) -> Iterator[BlockExport]:
        """Every block of the head generation, in `(page, ord, addr)` order. See DEFECT 1."""
        for row in self._c.execute(_BLOCKS_SQL, (self._doc_ord, self._gen)):
            yield self._block(row)

    def rels(self) -> Iterator[RelRow]:
        """`rel`, with `block_id` endpoints translated to addresses (03:2508)."""
        for src, dst, kind, producer, trust, score, score_kind, operator, x in self._c.execute(
            _RELS_SQL, (self._doc_ord, self._gen)
        ):
            yield RelRow(
                src=Addr(self._addr_of(int(src), "rel.src_id")),
                dst=Addr(self._addr_of(int(dst), "rel.dst_id")),
                kind=RelKind(self._member("rel_kind", int(kind))),
                producer=self._producer_index[int(producer)],
                trust=Trust(int(trust)),
                origin_operator=str(operator),
                score=None if score is None else float(score),
                score_kind=None if score_kind is None else str(score_kind),
                x=_json_object(x),
            )

    def grids(self) -> Iterator[GridRow]:
        """`table_meta` plus its origin `cell` geometry. `grid_slot` is `[DER]` and excluded."""
        cells: dict[int, list[tuple[int, int, int, int]]] = {}
        for table_id, r, c, row_span, col_span in self._c.execute(
            _CELLS_SQL, (self._doc_ord, self._gen)
        ):
            cells.setdefault(int(table_id), []).append(
                (int(r), int(c), int(row_span), int(col_span))
            )
        for row in self._c.execute(_GRIDS_SQL, (self._doc_ord, self._gen)):
            block_id = int(row[0])
            yield GridRow(
                table=Addr(self._addr_of(block_id, "table_meta.block_id")),
                n_rows=int(row[1]),
                n_cols=int(row[2]),
                row_len=tuple(int(n) for n in json.loads(str(row[3]))),
                kind=self._member("table_kind", int(row[6])),
                cells=tuple(cells.get(block_id, ())),
                header_rows=int(row[4]),
                header_cols=int(row[5]),
                recon_strategy=None if row[7] is None else str(row[7]),
                recon_score=None if row[8] is None else float(row[8]),
                has_merges=bool(row[9]),
                native_part=None if row[10] is None else str(row[10]),
                native_sha256=None if row[11] is None else bytes(row[11]).hex(),
            )

    def parts(self) -> Iterator[tuple[PartRow, bytes]]:
        """`part`, with its bytes when a `BlobStore` was handed in and `present = False` if not."""
        for path, sha256, byte_len, store_ref in self._c.execute(_PARTS_SQL, (self._doc_ord,)):
            digest = bytes(sha256)
            blob = self._blob(store_ref, digest)
            yield (
                PartRow(
                    path=str(path),
                    sha256=digest.hex(),
                    byte_len=int(byte_len),
                    present=blob is not None,
                ),
                blob or b"",
            )

    def assets(self) -> Iterator[tuple[AssetRow, bytes]]:
        """`asset`, with its `block_asset` roles addressed by `addr` rather than by `block_id`."""
        roles: dict[int, list[tuple[Addr, str]]] = {}
        for asset_id, addr, role in self._c.execute(_ROLES_SQL, (self._doc_ord, self._gen)):
            roles.setdefault(int(asset_id), []).append((Addr(str(addr)), str(role)))
        for row in self._c.execute(_ASSETS_SQL, (self._doc_ord,)):
            asset_id = int(row[0])
            digest = bytes(row[3])
            blob = self._blob(row[11], digest)
            yield (
                AssetRow(
                    sha256=digest.hex(),
                    media_type=str(row[1]),
                    byte_len=int(row[4]),
                    present=blob is not None,
                    origin_part=None if row[2] is None else str(row[2]),
                    width=None if row[5] is None else int(row[5]),
                    height=None if row[6] is None else int(row[6]),
                    licence=None if row[7] is None else str(row[7]),
                    spdx=None if row[8] is None else str(row[8]),
                    source_url=None if row[9] is None else str(row[9]),
                    restriction_bits=int(row[10]),
                    roles=tuple(roles.get(asset_id, ())),
                ),
                blob or b"",
            )

    def views(self) -> Iterable[ViewRow]:
        """Empty: no shipped migration stores a serialized view. See the module docstring."""
        return ()

    def diags(self) -> Iterator[Mapping[str, Any]]:
        """`diag`, with `block_id` resolved to an `addr` -- or reported unresolvable, never leaked.

        `0001_init.sql:461-463`: *"`block_id` is deliberately NOT a foreign key: a diagnostic
        often concerns a block the parse then refused to write."* So an id that names no row is a
        legal state and not corruption, and the record says so with `unresolved_block` rather
        than carrying a number that means nothing outside this store.
        """
        for (
            page,
            block_id,
            part,
            code,
            severity,
            component,
            message,
            detail,
            fatal,
        ) in self._c.execute(_DIAGS_SQL, (self._doc_ord, self._gen)):
            addr = None if block_id is None else self._addr.get(int(block_id))
            yield {
                "code": str(code),
                "severity": str(severity),
                "component": str(component),
                "message": str(message),
                "page": None if page is None else int(page),
                "addr": addr,
                "unresolved_block": block_id is not None and addr is None,
                "part": None if part is None else str(part),
                "detail": _json_object(detail),
                "fatal": bool(fatal),
            }

    def toc(self) -> Sequence[Mapping[str, Any]]:
        """Empty: the table of contents is derived at render time and is not a stored row."""
        return ()

    # -- decoding ------------------------------------------------------------

    def _block(self, row: Sequence[Any]) -> BlockExport:
        """One `block` row as a `Block` plus the two columns `Block` deliberately does not hold.

        The four `enum_val` codes go back through `_member`, which is the same resolution
        `SqliteReader._member` performs and for the same reason: reading the ordinal off this
        build's Python enum would let a store seeded by an older build answer with this build's
        numbering, which is exactly the drift `enum_val` exists to make impossible.
        """
        block_id = int(row[0])
        quad = None if row[14] is None else Quad(*_QUAD_STRUCT.unpack(bytes(row[14])))
        block = Block(
            id=BlockId(block_id),
            addr=Addr(str(row[1])),
            cite=Cite(str(row[2])),
            doc_ord=self._doc_ord,
            gen=self._gen,
            page=int(row[3]),
            parent=None if row[4] is None else BlockId(int(row[4])),
            ord=int(row[5]),
            kind=Kind(self._member("kind", int(row[6]))),
            raw_kind=None if row[7] is None else str(row[7]),
            layer=Layer(self._member("layer", int(row[8]))),
            label=None if row[9] is None else str(row[9]),
            text=None if row[10] is None else str(row[10]),
            content_digest=bytes(row[11]),
            layout_digest=None if row[12] is None else bytes(row[12]),
            revision=int(row[13]),
            quad=quad,
            origin=self._origin(row),
            span=None if row[22] is None else TextSpan(int(row[22]), int(row[23])),
            producer_id=int(row[24]),
            method=Method(self._member("method", int(row[25]))),
            trust=Trust(int(row[26])),
            quote=Quote(int(row[27])),
            score=None if row[28] is None else float(row[28]),
            score_kind=None if row[29] is None else str(row[29]),
            origin_operator=str(row[30]),
            origin_driver=str(row[31]),
            driver_schema_v=int(row[32]),
            restriction_bits=int(row[33]),
            marks=self._marks.get(block_id, ()),
            tombstoned=bool(row[36]),
            x=_json_object(row[37]),
        )
        return BlockExport(
            block=block,
            producer=self._producer_index[int(row[24])],
            payload=None if row[35] is None else _json_object(row[35]),
            decision_id=None if row[34] is None else str(row[34]),
        )

    def _origin(self, row: Sequence[Any]) -> OriginSpan:
        """The seven `os_*` columns back into one `OriginSpan`. `doc.py:398`'s mapping, reversed.

        `os_b` is a LENGTH and never an end offset (03:1471-1473), which is why it becomes
        `length=` on both variants that carry it and never `b=`.
        """
        kind = OsKind(self._member("origin_span_kind", int(row[15])))
        part = None if row[16] is None else str(row[16])
        if kind is OsKind.BYTES:
            return OriginBytes(
                part=str(part), start=int(row[17]), length=int(row[18]), codec=str(row[21])
            )
        if kind is OsKind.NODEPATH:
            return OriginNodePath(
                part=str(part), path=tuple(int(step) for step in str(row[19]).split("."))
            )
        if kind is OsKind.GLYPHS:
            return OriginGlyphs(
                part=str(part), start=int(row[17]), length=int(row[18]), extractor=str(row[20])
            )
        if kind is OsKind.PIXELS:
            return OriginPixels()
        return OriginNone()

    def _member(self, domain: str, code: int) -> str:
        """The `enum_val` member name for one stored code, refusing a code the store cannot name.

        The same refusal as `SqliteReader._member`: a stored code with no `enum_val` row means
        the seed and the rows disagree, and a guessed member would be written into an archive
        that then travels to another store.
        """
        member = self._enums.get((domain, code))
        if member is None:
            raise StoreError(
                f"this store holds {domain} code {code}, which its own enum_val does not name: "
                f"exporting a guessed member would put it in a portable archive",
                fix="ow store verify",
            )
        return member

    def _addr_of(self, block_id: int, column: str) -> str:
        """One `block_id` as its `addr`, raising rather than letting the integer into the archive.

        07:3094: *"An archive contains no `block_id`: every internal reference in it is an
        `addr`."* `rel` and `table_meta` both have `ON DELETE CASCADE` foreign keys into `block`,
        so a miss here is a store that failed `PRAGMA foreign_key_check` -- a raise naming
        `ow store repair` is the honest answer and an integer in the archive is not.
        """
        addr = self._addr.get(block_id)
        if addr is None:
            raise StoreError(
                f"{column} = {block_id} names no block at (doc_ord={self._doc_ord}, "
                f"gen={self._gen}), and an archive may carry no block_id "
                f"(07-store-and-retrieval.md:3094)",
                fix="ow store repair",
            )
        return addr

    def _blob(self, store_ref: object, digest: bytes) -> bytes | None:
        """The retained bytes for one `cas://` reference, or `None` when they did not travel."""
        if store_ref is None or self._blobs is None:
            return None
        if not self._blobs.has(digest):
            return None
        with self._blobs.open(digest) as handle:
            return handle.read()


# ---------------------------------------------------------------------------------------------
# 4. Small readers.
# ---------------------------------------------------------------------------------------------


def _json_object(value: object) -> dict[str, Any]:
    """One JSON TEXT column as a dict. An empty or NULL column is `{}`, never `None`.

    Every JSON column this module reads is declared `TEXT NOT NULL DEFAULT '{}'`, so `None` can
    only come from a hand-edited store; treating it as `{}` rather than raising keeps one broken
    column from costing a whole export, and the value it produces is the column's own default.
    """
    if value is None or value == "":
        return {}
    decoded = json.loads(str(value))
    return dict(decoded) if isinstance(decoded, dict) else {}


def _enum_map(connection: sqlite3.Connection) -> dict[tuple[str, int], str]:
    """`{(domain, ord): name}` for every closed domain, read once per document."""
    return {
        (str(domain), int(ord_)): str(name) for domain, name, ord_ in connection.execute(_ENUM_SQL)
    }


def _marks_by_block(
    connection: sqlite3.Connection, doc_ord: int, gen: int
) -> dict[int, tuple[Mark, ...]]:
    """Every mark of one generation, grouped by `block_id`. See `_StoreDocument`'s docstring."""
    grouped: dict[int, list[Mark]] = {}
    for block_id, a, b, kind, value in connection.execute(_MARKS_SQL, (doc_ord, gen)):
        grouped.setdefault(int(block_id), []).append(
            Mark(a=int(a), b=int(b), kind=str(kind), value=None if value is None else str(value))
        )
    return {block_id: tuple(marks) for block_id, marks in grouped.items()}


def _producers(
    connection: sqlite3.Connection,
) -> tuple[tuple[dict[str, Any], ...], dict[int, int]]:
    """`manifest.producers[]` and the `producer_id` -> index map wire key `pd` needs (03:666).

    Every producer row in the store is carried, not only the ones this document's blocks cite.
    The list is short -- one row per reproduction tuple, and `producer_identity` deduplicates it
    -- and a per-document subset would make the same producer land at a different index in two
    archives, which turns a diff of two documents' records into noise.
    """
    rows: list[dict[str, Any]] = []
    index: dict[int, int] = {}
    for producer_id, *rest in connection.execute(_PRODUCERS_SQL):
        index[int(producer_id)] = len(rows)
        operator, op_version, fingerprint, model_id, model_rev = rest[0:5]
        runtime, runtime_version, prompt_fp, options_digest = rest[5:9]
        rows.append(
            {
                "operator": str(operator),
                "op_version": int(op_version),
                "code_fingerprint": str(fingerprint),
                "model_id": None if model_id is None else str(model_id),
                "model_rev": None if model_rev is None else str(model_rev),
                "runtime": None if runtime is None else str(runtime),
                "runtime_version": None if runtime_version is None else str(runtime_version),
                "prompt_fp": None if prompt_fp is None else str(prompt_fp),
                "options_digest": bytes(options_digest).hex(),
            }
        )
    return tuple(rows), index
