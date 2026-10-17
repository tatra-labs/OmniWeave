"""`StoreDocReader`: `model.doc.DocReadSide` over one `.owstore` connection. D864.

`model/doc.py` has carried `Doc`, the L2 lazy handle (03 section 13.5), since W2, over a structural
`DocReadSide` that nothing in the store implemented: every `Doc` in the tree read a test's fake.
This is the store's side, so `Doc(StoreDocReader(connection), doc_ord, gen)` reads a real
document, and `Corpus.doc()` (18-api-sketch.md section 1.2) has something to return.

Every Block comes through `portable.BlockDecoder`, the store's one decode (SV19), which
`read_block()` and the export also use. Nothing here decodes a column of its own.

## Rulings

1. **Every read is of live rows at the handle's generation.** `state = 0` and `gen = ?` on every
   statement, so a retired row is a miss, as `Doc.block()`'s docstring says it is ("a torn read or
   a retired row"). A cite is durable across generations (03:1141), so `block_at_cite` still
   filters on the generation: a `Doc` is pinned to one.
2. **`doc_record` answers for the head generation only.** The `doc` table holds one row per
   document and its `gen` is the head (`0001_init.sql`), so no stored record describes a staged
   or quarantined generation. Asking for one is `NotFoundError`, not the head's record under the
   wrong generation.
3. **`blocks()` is a cursor in windows of `MARK_WINDOW` = 512 rows** (03:2607-2609): *"the reader
   holds one `Block` plus one 512-block mark window at a time"*. Each window's marks are one
   statement. The order is the export's, `page, ord, addr`, over the `block_read` index. When the
   connection is not already in a transaction, the cursor opens `BEGIN DEFERRED` and ends it when
   it is exhausted or closed, so every window reads one snapshot. A caller already inside one,
   such as `SqliteReader.snapshot()`, keeps its own.
4. **`under=` is the subtree rooted at that block, the block included.** 03:2814 calls the scope
   *"a subtree under one `BlockId`"*, and a subtree has its root. The descent is a recursive CTE
   over `block_parent` (03:2610), not a scan. The other filters apply to the root too.
5. **Filters bind the store's own `enum_val` codes** through `BlockDecoder.ordinal()`, never this
   build's enum positions. `trust` and `quote` are stored as values (`0001_init.sql`), so
   `trust_below` binds `int(trust)`.
6. **Five reads are refused by name**, each a `UsageError` saying why, because this build has no
   store for them: `frames()` (Frames are a `.owdoc` archive's, located through `frames.json`),
   `page_render()` (no renderer is reachable from a read), `asset()` (the bytes are in the CAS,
   which a connection does not reach), `verify_quote()` (`QuoteVerdict` has no module, 03:1706),
   and `resolve_scope()`, so `Doc.serialize()`, until its satellites are read.

A missing block in `payload()` and `grid()` is `NotFoundError`. `Doc.payload()` documents an empty
mapping for a NULL column, not for an absent block, and `Doc.grid()` has no `None` to return.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, NoReturn

from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.block import BlockId
from omniweave_core.model.enums import RelKind, Trust
from omniweave_core.model.records import Rel
from omniweave_core.store.doc import read_doc_record, read_grid
from omniweave_core.store.portable import BlockDecoder

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping

    from omniweave_core.model.block import Addr, Block, Cite
    from omniweave_core.model.enums import Kind, Layer
    from omniweave_core.model.grid import Grid
    from omniweave_core.model.records import AssetRef, DocRecord

__all__ = ["MARK_WINDOW", "StoreDocReader"]

MARK_WINDOW: Final = 512
"""Rows per `blocks()` window, and so marks per statement (03:2608, section 2.7's window)."""

_FIX_SHOW: Final = "ow doc show d<doc_ord>  # list the document's blocks"

_LIVE: Final = "doc_ord = ? AND gen = ? AND state = 0"


class StoreDocReader:
    """`DocReadSide` over one connection (rulings 1-6). Holds the connection, never opens one."""

    __slots__ = ("_connection", "_decoder")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._decoder: BlockDecoder | None = None

    # -- the record ------------------------------------------------------------------------------

    def doc_record(self, doc_ord: int, gen: int) -> DocRecord:
        """The `doc` row, for the head generation only (ruling 2)."""
        row = self._connection.execute(
            "SELECT gen FROM doc WHERE doc_ord = ?", (doc_ord,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no document d{doc_ord} in this store", fix="ow corpora --detail")
        if int(row[0]) != gen:
            raise NotFoundError(
                f"document d{doc_ord}'s record is its head generation's, {int(row[0])}: the doc "
                f"table holds one row per document, so generation {gen} has no record",
                fix=f"read d{doc_ord} at generation {int(row[0])}",
            )
        return read_doc_record(self._connection, doc_ord)

    # -- one block -------------------------------------------------------------------------------

    def block(self, doc_ord: int, gen: int, block: BlockId) -> Block | None:
        return self._one("block_id = ?", (int(block),), doc_ord, gen)

    def block_at_addr(self, doc_ord: int, gen: int, addr: Addr) -> Block | None:
        return self._one("addr = ?", (str(addr),), doc_ord, gen)

    def block_at_cite(self, doc_ord: int, gen: int, cite: Cite) -> Block | None:
        return self._one("cite = ?", (str(cite),), doc_ord, gen)

    # -- the cursor ------------------------------------------------------------------------------

    def blocks(
        self,
        doc_ord: int,
        gen: int,
        *,
        pages: range | None,
        kinds: frozenset[Kind] | None,
        layers: frozenset[Layer],
        under: BlockId | None,
        trust_below: Trust | None,
    ) -> Iterator[Block]:
        """The document's live blocks in windows of `MARK_WINDOW` (rulings 3-5)."""
        decoder = self._decode()
        prefix, where, params = "", [_LIVE], [doc_ord, gen]
        if under is not None:
            prefix = (
                "WITH RECURSIVE sub(id) AS (SELECT ? UNION ALL SELECT b.block_id FROM block b "
                "JOIN sub ON b.parent_id = sub.id WHERE b.state = 0) "
            )
            params.insert(0, int(under))
            where.append("block_id IN (SELECT id FROM sub)")
        if pages is not None:
            where.append("page >= ? AND page < ?")
            params += [pages.start, pages.stop]
        if kinds is not None:
            where.append(_holes("kind", len(kinds)))
            params += sorted(decoder.ordinal("kind", kind.value) for kind in kinds)
        where.append(_holes("layer", len(layers)))
        params += sorted(decoder.ordinal("layer", layer.value) for layer in layers)
        if trust_below is not None:
            where.append("trust < ?")
            params.append(int(trust_below))
        sql = (
            f"{prefix}SELECT {BlockDecoder.COLUMNS} FROM block "  # noqa: S608 -- constants and holes
            f"WHERE {' AND '.join(where)} ORDER BY page, ord, addr"
        )
        return self._windows(decoder, sql, tuple(params))

    # -- what a block carries --------------------------------------------------------------------

    def payload(self, doc_ord: int, gen: int, block: BlockId) -> Mapping[str, Any]:
        """One block's `payload`; an empty mapping when the column is NULL (03:988)."""
        row = self._connection.execute(
            f"SELECT payload FROM block WHERE block_id = ? AND {_LIVE}",  # noqa: S608 -- constants
            (int(block), doc_ord, gen),
        ).fetchone()
        if row is None:
            raise NotFoundError(_missing(block, doc_ord, gen), fix=_FIX_SHOW)
        return MappingProxyType({} if row[0] is None else json.loads(str(row[0])))

    def rels(
        self,
        doc_ord: int,
        gen: int,
        block: BlockId,
        kind: RelKind | None,
        *,
        inbound: bool,
    ) -> Iterator[Rel]:
        """One block's `rel` rows, outbound unless `inbound`; every kind when `kind` is `None`."""
        decoder = self._decode()
        end, other = ("dst_id", "src_id") if inbound else ("src_id", "dst_id")
        where, params = [f"doc_ord = ? AND gen = ? AND {end} = ?"], [doc_ord, gen, int(block)]
        if kind is not None:
            where.append("kind = ?")
            params.append(decoder.ordinal("rel_kind", kind.value))
        rows = self._connection.execute(
            "SELECT src_id, dst_id, kind, producer_id, trust, score, score_kind, origin_operator "  # noqa: S608 -- constants
            f"FROM rel WHERE {' AND '.join(where)} ORDER BY kind, {other}, producer_id",
            tuple(params),
        ).fetchall()
        return iter(
            [
                Rel(
                    src=BlockId(int(row[0])),
                    dst=BlockId(int(row[1])),
                    kind=RelKind(decoder.member("rel_kind", int(row[2]))),
                    producer_id=int(row[3]),
                    trust=Trust(int(row[4])),
                    score=None if row[5] is None else float(row[5]),
                    score_kind=None if row[6] is None else str(row[6]),
                    origin_operator=str(row[7]),
                )
                for row in rows
            ]
        )

    def grid(self, doc_ord: int, gen: int, table: BlockId) -> Grid:
        """The `Grid` of a table, or of the table a cell sits in, as `read_grid()` rebuilds it."""
        if self.block(doc_ord, gen, table) is None:
            raise NotFoundError(_missing(table, doc_ord, gen), fix=_FIX_SHOW)
        found = read_grid(self._connection, int(table))
        if found is None:
            raise NotFoundError(
                f"block {int(table)} is neither a table nor a cell of one",
                fix="ow doc grid <cite>  # name a table or one of its cells",
            )
        return found[1]

    # -- refused by name (ruling 6) --------------------------------------------------------------

    def frames(self, doc_ord: int, gen: int) -> NoReturn:  # noqa: ARG002 -- the Protocol's
        _refuse("frames()", "Frames are a .owdoc archive's, located through its frames.json")

    def page_render(self, doc_ord: int, page: int, dpi: int) -> NoReturn:  # noqa: ARG002
        _refuse("page_render()", "no page renderer is reachable from a read")

    def asset(self, ref: AssetRef) -> NoReturn:  # noqa: ARG002
        _refuse(
            "asset()", "an asset's bytes are in the CAS, which a store connection does not reach"
        )

    def verify_quote(self, doc_ord: int, gen: int, block: BlockId) -> NoReturn:  # noqa: ARG002
        _refuse("verify_quote()", "QuoteVerdict (03:1706) has no module in this build")

    def resolve_scope(
        self,
        doc_ord: int,  # noqa: ARG002 -- the Protocol's names
        gen: int,  # noqa: ARG002
        *,
        pages: range | None,  # noqa: ARG002
        under: BlockId | None,  # noqa: ARG002
    ) -> NoReturn:
        _refuse("serialize()", "the view scope's satellites are not read from a store yet")

    # -- the machinery ---------------------------------------------------------------------------

    def _decode(self) -> BlockDecoder:
        """The decoder, reading the store's `enum_val` on first use and keeping it."""
        if self._decoder is None:
            self._decoder = BlockDecoder(self._connection)
        return self._decoder

    def _one(self, key: str, value: tuple[object, ...], doc_ord: int, gen: int) -> Block | None:
        decoder = self._decode()
        row = self._connection.execute(
            f"SELECT {BlockDecoder.COLUMNS} FROM block WHERE {key} AND {_LIVE}",  # noqa: S608 -- constants
            (*value, doc_ord, gen),
        ).fetchone()
        if row is None:
            return None
        block_id = int(row[0])
        return decoder.decode(row, decoder.marks((block_id,)).get(block_id, ()))

    def _windows(
        self, decoder: BlockDecoder, sql: str, params: tuple[object, ...]
    ) -> Iterator[Block]:
        """Yield each window's blocks, one marks statement per window, under one snapshot."""
        connection = self._connection
        owned = not connection.in_transaction
        if owned:
            connection.execute("BEGIN DEFERRED")
        try:
            cursor = connection.execute(sql, params)
            while window := cursor.fetchmany(MARK_WINDOW):
                marks = decoder.marks([int(row[0]) for row in window])
                for row in window:
                    yield decoder.decode(row, marks.get(int(row[0]), ()))
        finally:
            if owned and connection.in_transaction:
                connection.execute("COMMIT")


def _holes(column: str, count: int) -> str:
    """`column IN (?, ...)`; an empty set is `0`, which matches nothing, as an empty filter must."""
    return f"{column} IN ({', '.join('?' * count)})" if count else "0"


def _missing(block: BlockId, doc_ord: int, gen: int) -> str:
    return f"no live block {int(block)} in document d{doc_ord} at generation {gen}"


def _refuse(read: str, why: str) -> NoReturn:
    raise UsageError(
        f"Doc.{read} is not built for a stored document: {why}",
        fix="read the document's blocks: Doc.blocks(), Doc.block(), Doc.grid()",
    )
