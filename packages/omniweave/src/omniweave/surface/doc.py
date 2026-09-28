"""`ow doc grid <ref>`: one table as its exactly-once grid. `ow doc diff <ref>`: two generations.

10:808 gives `ow_grid` one row: *"a table's exactly-once cover: `slot(r,c)`, headers, merges"*.
The `Grid` type and its sole constructor, `build_grid()`, have existed since P2. What did not exist
is the read: `DocReadSide.grid()` is a Protocol with no store behind it, so the CLI root `doc`
was refused as *"not dispatched by this build"*. W7.8n adds `omniweave_core.store.doc.read_grid()`,
which rebuilds a table's `Grid` from `table_meta` and `cell` through `build_grid()` and checks the
rebuilt shape against the stored one, and this module prints it.

**Two renders, one per consumer** (10 section 6.3).
- `--render json` is the grid itself: the `Grid`'s printed fields and one row per origin cell --
  its slot, its spans, whether it is a header, its cite and its text -- which is 10:808's
  `slot(r,c)`, headers and merges.
- `--render text`, the default, is 10:1529's *"a formatted table"* for a person: a head line, then
  the table as GFM from `model.grid.render_grid()`, the one table serializer (INV-1), over
  `store.doc.StoreGridReader` (W7.8s, D626). GFM has no span syntax, so a merged cell's text is
  in its origin slot and the slots it covers are blank, and trailing blank rows and columns are
  dropped (03:2035-2039). The loss is the render's only: the JSON keeps the spans and the cites.

**`ow doc diff <ref>` is 10:819's *"semantic diff between two generations of one document"*.**
13-quality.md section 5.7 fixes what that is: *"The semantic differ is `rebind()`, and there is no
second one"*, and `RebindReport` is its output. So this prints `store.doc.diff_generations()`,
which runs `rebind()`'s matcher over the store's own rows and writes nothing (W7.8t, D627).
- `ref` is anything `ow open` resolves -- a cite, a URI, a file name -- and it names the document.
- The default pair is the two newest generations that hold live rows: the head, and the
  generation a quarantine refused, which 03:1298-1302 keeps *"inspectable by `ow doc diff`"*. A
  committed head keeps no earlier generation, and that is exit 2, saying so.
- `--render json` is the ten fields of `RebindReport`, `schema` first. `--render text` is the
  counts, whether the newer generation was committed, and the pages that fell below the
  threshold.

**Refused by name**, each exit 1, for both verbs: `--quiet`, because 10:1542-1545 has each Action
declare its one scalar and neither declares one, and `--render jsonl` and `--render rows`.

Exits: 0; 1 for usage; 2 for a ref that does not resolve, a block that is neither a table nor a
cell of one, a generation with no live row, or an undeclared corpus; 6 for refs that address two
corpora (`OW-A-015`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, OwError, UsageError

from omniweave.surface.opening import corpus_for
from omniweave.surface.query import error_object, parse, store_of
from omniweave.surface.startup import corpora

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.model.grid import Grid
    from omniweave_core.model.rebind import RebindReport

__all__ = ["DOC_WORD", "diff_document", "grid_document", "main"]

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
        if parsed.ow_action == _GRID:
            return _grid(parsed, env=env, cwd=cwd, stdout=stdout)
        return _diff(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        if as_json:
            stdout.write(json.dumps(error_object(error), ensure_ascii=False) + "\n")
        else:
            stderr.write(f"ow: {error.numeric() or error.code()}: {error}\n  fix: {error.fix}\n")
        return type(error).EXIT


def _grid(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    _refuse_unserved(parsed, verb="ow doc grid", fix="ow doc grid <cite> [--render json]")
    if not str(parsed.ref).strip():
        raise UsageError("ow doc grid needs a table's cite", fix="ow doc grid d7#412")
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    ref = str(parsed.ref)
    name = corpus_for(config, [ref], parsed.corpus, verb="ow doc grid")
    store = store_of(config, name, cwd=cwd)
    as_json = parsed.render == "json"
    document, table = _read(
        store, ref, corpus=name, qualify=len(corpora(config)) > 1, gfm=not as_json
    )
    if as_json:
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        #  The serializer ends on the last row's pipe, and a line on stdout ends with a newline.
        stdout.write(_head(document) + "\n\n" + table.rstrip("\n") + "\n")
    return 0


def _refuse_unserved(parsed: argparse.Namespace, *, verb: str, fix: str) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(f"{', '.join(named)} is parsed and not served by {verb}", fix=fix)


def _diff(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    _refuse_unserved(
        parsed, verb="ow doc diff", fix="ow doc diff <document> [--from-gen N] [--to-gen M]"
    )
    ref = str(parsed.ref)
    if not ref.strip():
        raise UsageError(
            "ow doc diff needs a document: a cite, a URI or a file name",
            fix="ow doc diff policy.pdf",
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [ref], parsed.corpus, verb="ow doc diff")
    store = store_of(config, name, cwd=cwd)
    report = _compare(store, ref, from_gen=parsed.from_gen, to_gen=parsed.to_gen)
    document = diff_document(report, corpus=name)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        for line in _diff_text(document, report.match_rate()):
            stdout.write(line + "\n")
    return 0


def _compare(store: Path, ref: str, *, from_gen: int | None, to_gen: int | None) -> RebindReport:
    """Resolve `ref` to its one document, and diff two of its generations: one snapshot."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.model.enums import Layer  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.doc import diff_generations  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot() as s:
            (found,) = reader.resolve_refs(s, [ref], context=0, layers=frozenset(Layer))
            if isinstance(found, resolve.Missed):
                raise found.error
            (doc_ord,) = found.doc_ords
            return diff_generations(connection, doc_ord, from_gen=from_gen, to_gen=to_gen)
    finally:
        connection.close()


def diff_document(report: RebindReport, *, corpus: str) -> dict[str, Any]:
    """`RebindReport`'s ten fields in their order (03:1245-1250), after `schema` and `corpus`.

    `match_rate_by_page` is keyed by the page as a string, because a JSON object's keys are strings,
    and in page order. `match_rate()` is not a field: the report derives it, and so can a reader.
    """
    return {
        "schema": _SCHEMA,
        "corpus": corpus,
        "doc_ord": report.doc_ord,
        "from_gen": report.from_gen,
        "to_gen": report.to_gen,
        "carried": report.carried,
        "revised": report.revised,
        "created": report.created,
        "retired": report.retired,
        "match_rate_by_page": {
            str(page): rate for page, rate in sorted(report.match_rate_by_page.items())
        },
        "quarantined": report.quarantined,
        "threshold": report.threshold,
    }


def _diff_text(document: Mapping[str, Any], match_rate: float) -> list[str]:
    """Which generations, whether the newer one is the head, the counts, and the pages below."""
    state = "quarantined, not committed" if document["quarantined"] else "committed"
    threshold = float(document["threshold"])
    lines = [
        f"d{document['doc_ord']}  generation {document['from_gen']} -> {document['to_gen']}  "
        f"{state}",
        f"  carried {document['carried']}  revised {document['revised']}  "
        f"created {document['created']}  retired {document['retired']}",
        f"  matched {match_rate:.2f} of the older generation, threshold {threshold:.2f}",
    ]
    below = [
        (page, rate) for page, rate in document["match_rate_by_page"].items() if rate < threshold
    ]
    lines.extend(f"  page {page}  matched {rate:.2f}" for page, rate in below)
    return lines


def _read(
    store: Path, ref: str, *, corpus: str, qualify: bool, gfm: bool
) -> tuple[dict[str, Any], str]:
    """Resolve `ref` to one block, read its table's `Grid`, and hydrate each cell: one snapshot.

    With `gfm`, the table is also rendered, over the same connection and inside the same snapshot,
    so the render and the document describe one state of the store. Without it the render is `""`.
    """
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.model.block import BlockId  # noqa: PLC0415
    from omniweave_core.model.enums import Layer  # noqa: PLC0415
    from omniweave_core.model.grid import render_grid  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.doc import StoreGridReader, block_kind, read_grid  # noqa: PLC0415

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
            table = ""
            if gfm:
                table, _ = render_grid(
                    grid, StoreGridReader(connection), "gfm", table=BlockId(table_id)
                )
    finally:
        connection.close()
    return grid_document(grid, table_id, hydrated, corpus=corpus, qualify=qualify), table


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


def _head(document: Mapping[str, Any]) -> str:
    """The line above the table: its cite, its shape, and what GFM cannot show."""
    merges = "yes" if document["has_merges"] else "no"
    return (
        f"table {document['table']}  {document['n_rows']} rows x {document['n_cols']} cols  "
        f"header_rows {document['header_rows']}  header_cols {document['header_cols']}  "
        f"merges {merges}  kind {document['kind']}"
    )
