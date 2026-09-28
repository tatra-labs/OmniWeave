"""`ow doc grid <ref>`: one table as its exactly-once grid. `ow doc diff`: refused by name.

10:808 gives `ow_grid` one row: *"a table's exactly-once cover: `slot(r,c)`, headers, merges"*.
The `Grid` type and its sole constructor, `build_grid()`, have existed since P2. What did not exist
is the read: `DocReadSide.grid()` is a Protocol with no store behind it, so the CLI root `doc`
was refused as *"not dispatched by this build"*. W7.8n adds `omniweave_core.store.doc.read_grid()`,
which rebuilds a table's `Grid` from `table_meta` and `cell` through `build_grid()` and checks the
rebuilt shape against the stored one, and this module prints it.

**What is printed is the grid, not a render of it.** `--render json` is the `Grid`'s printed fields
and one row per origin cell -- its slot, its spans, its cite and its text -- which is 10:808's
`slot(r,c)`, headers and merges. `--render text` is the same, one line per cell. A GFM table would
come from `model.grid.render_grid()`, the one table serializer (INV-1), and that needs each cell as
a model `Block`. D621 said no store read built one; `store.portable.read_block()` does since W7.8r,
and wiring it to `render_grid()` is owed (D625). A hand-drawn table here would be the second
serializer INV-1 forbids.

**`ow doc diff` is refused by name**, exit 70, 10:2185's *"anything else"*. It compares two
generations through `model.rebind`'s `RebindReadSide`, and no store implements that Protocol
either (D621).

**Also refused by name**, each exit 1: `--quiet`, because 10:1542-1545 has each Action declare its
one scalar and `doc.grid` declares none, and `--render jsonl` and `--render rows`.

Exits: 0; 1 for usage; 2 for a ref that does not resolve, a block that is neither a table nor a
cell of one, or an undeclared corpus; 6 for refs that address two corpora (`OW-A-015`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import InternalError, NotFoundError, OwError, UsageError

from omniweave.surface.opening import corpus_for
from omniweave.surface.query import error_object, parse, store_of
from omniweave.surface.startup import corpora

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.model.grid import Grid

__all__ = ["DOC_WORD", "grid_document", "main"]

DOC_WORD: Final[str] = "doc"

_SCHEMA: Final[int] = 1
_GRID: Final[str] = "doc.grid"


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`ow doc <verb> ...` from argv (starting at the root word)."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    as_json = parsed.render == "json"
    try:
        if parsed.ow_action != _GRID:
            raise InternalError(
                "ow doc diff compares two generations through model.rebind's RebindReadSide, and "
                "no store implements it in this build (D621)",
                fix="ow doc grid <cite>   # the one ow doc verb this build serves",
            )
        return _grid(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        if as_json:
            stdout.write(json.dumps(error_object(error), ensure_ascii=False) + "\n")
        else:
            stderr.write(f"ow: {error.numeric() or error.code()}: {error}\n  fix: {error.fix}\n")
        return type(error).EXIT


def _grid(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    _refuse_unserved(parsed)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    ref = str(parsed.ref)
    name = corpus_for(config, [ref], parsed.corpus, verb="ow doc grid")
    store = store_of(config, name, cwd=cwd)
    document = _read(store, ref, corpus=name, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        for line in _text(document):
            stdout.write(line + "\n")
    return 0


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow doc grid",
            fix="ow doc grid <cite> [--render json]",
        )
    if not str(parsed.ref).strip():
        raise UsageError("ow doc grid needs a table's cite", fix="ow doc grid d7#412")


def _read(store: Path, ref: str, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """Resolve `ref` to one block, read its table's `Grid`, and hydrate each cell: one snapshot."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.model.enums import Layer  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.doc import block_kind, read_grid  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot() as s:
            (found,) = reader.resolve_refs(s, [ref], context=0, layers=frozenset(Layer))
            if isinstance(found, resolve.Missed):
                raise found.error
            block_id = _one_block(found.block_ids, ref)
            read = read_grid(connection, block_id)
            if read is None:
                kind = block_kind(connection, block_id) or "missing"
                raise NotFoundError(
                    f"{ref} names a {kind} block, which is neither a table nor a cell of one",
                    symbol="OW_ADDR_NOT_FOUND",
                    fix="ow doc grid <cite of a table>   # ow open shows each block's kind",
                )
            table_id, grid = read
            hydrated = {
                row.block_id: row
                for row in reader.hydrate(s, [table_id, *(o.block for o in grid.cells())])
            }
    finally:
        connection.close()
    return grid_document(grid, table_id, hydrated, corpus=corpus, qualify=qualify)


def _one_block(block_ids: Sequence[int], ref: str) -> int:
    if len(block_ids) != 1:
        raise UsageError(
            f"{ref} names {len(block_ids)} blocks, and ow doc grid reads one table",
            fix="ow doc grid <cite of a table>",
        )
    return int(block_ids[0])


def grid_document(
    grid: Grid,
    table_id: int,
    hydrated: Mapping[int, Any],
    *,
    corpus: str,
    qualify: bool,
) -> dict[str, Any]:
    """The grid as JSON: `Grid`'s printed fields, then one row per origin cell, row-major.

    No schema file publishes `ow_grid`'s output (D621), so the shape is this build's, and `schema`
    comes first (10:1530). A cell's `header` is 03's rule: inside `header_rows` or `header_cols`.
    """

    def cite(block_id: int) -> str:
        row = hydrated.get(block_id)
        plain = "" if row is None else str(row.cite)
        return f"{corpus}:{plain}" if qualify and plain else plain

    cells = [
        {
            "cite": cite(origin.block),
            "r": origin.r,
            "c": origin.c,
            "row_span": origin.row_span,
            "col_span": origin.col_span,
            "header": origin.r < grid.header_rows or origin.c < grid.header_cols,
            "text": getattr(hydrated.get(origin.block), "text", None),
        }
        for origin in grid.cells()
    ]
    return {
        "schema": _SCHEMA,
        "corpus": corpus,
        "table": cite(table_id),
        "n_rows": grid.n_rows,
        "n_cols": grid.n_cols,
        "row_len": list(grid.row_len),
        "header_rows": grid.header_rows,
        "header_cols": grid.header_cols,
        "kind": grid.kind.value,
        "recon": None
        if grid.recon is None
        else {"strategy": grid.recon[0], "score": grid.recon[1]},
        "has_merges": grid.has_merges,
        "native": None
        if grid.native is None
        else {"part": grid.native[0], "sha256": grid.native[1].hex()},
        "cells": cells,
    }


def _text(document: Mapping[str, Any]) -> list[str]:
    """A head line, then one line per origin cell: its slot, a span when it has one, cite, text."""
    merges = "yes" if document["has_merges"] else "no"
    lines = [
        f"table {document['table']}  {document['n_rows']} rows x {document['n_cols']} cols  "
        f"header_rows {document['header_rows']}  header_cols {document['header_cols']}  "
        f"merges {merges}  kind {document['kind']}"
    ]
    for cell in document["cells"]:
        span = (
            f" {cell['row_span']}x{cell['col_span']}"
            if cell["row_span"] > 1 or cell["col_span"] > 1
            else ""
        )
        head = " header" if cell["header"] else ""
        #  One line per cell. Not `str.replace`: this package's no-write test bans the name.
        text = " ".join((cell["text"] or "").splitlines())
        lines.append(f"  [{cell['r']},{cell['c']}]{span}{head}  {cell['cite']}  {text}")
    return lines
