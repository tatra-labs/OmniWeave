"""The `omniweave` distribution's fixtures: one re-export, a reason it is a re-export, and the
three fixtures this distribution owns.

`packages/omniweave-core/tests/conftest.py` is this repository's one reader over `_plan/`. It
builds `PlanDocs` from the workspace root, skips the tests that need it when `_plan/` is absent
(the design tree is `.gitignore`d, so a clean clone has none), and carries the `fences`, `grep`
and `lines` helpers every transcription test in the tree is written against.

`repo_root` and `migrations` come across for the same reason and with the same force. `migrations`
in particular is not a path a test may compose: the migration set is `omniweave-core` package data
rather than a root directory (`_plan/_notes/build-defects.md` D12), so a second spelling here would
be a second answer to where the DDL lives.

Re-exported rather than re-declared. A second `PlanDocs` here would be a second answer to "where
is the plan and what counts as a document" -- `_notes/.snapshots/` is excluded from `documents()`
for a reason, and a copy that forgot would assert against a superseded draft and pass. INV-21 is
about facts, and "the plan is at `<root>/_plan`" is one.

The `sys.path` insertion is what makes the import work at all: pytest puts each `conftest.py`'s own
directory on the path, so `omniweave-core`'s is importable as a top-level `conftest` only from
inside that package's tests. Naming the directory here is the cost of two distributions sharing
one fixture without a test-support package neither of them ships.

`released_catalog` is this distribution's own: the shipped catalog with the office driver as a
released build carries it, the one catalog under which `resolve()` grants seam S1. Two test modules
drive S1, one through `pipeline.inproc_host` and one through a whole `ow ingest`, and a copy in
each would be two answers to what "released" means.

`seeded_store` writes a real `.owstore` holding one document and a given set of blocks, the
shape `omniweave-serve`'s `test_serve_query.py` seeds, so `ow query`'s unit and process tests
answer over the same store `ow_query`'s do (W7.8g).

`git_index` is another: a git index built byte by byte from git's `index-format.txt`. Both
`test_doctor_gitindex.py` and `test_doctor.py` write indexes, and the format should have one
spelling in the test tree, as it has one in `omniweave.doctor.gitindex` (W7.8c).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import sqlite3  # noqa: TID251 -- a type for the seeding helper's connection argument.
    from collections.abc import Callable, Mapping, Sequence

_CORE_CONFTEST = Path(__file__).resolve().parents[2] / "omniweave-core" / "tests" / "conftest.py"
_MODULE = "omniweave_core_tests_conftest"

if _MODULE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE, _CORE_CONFTEST)
    assert _spec is not None and _spec.loader is not None
    _loaded = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE] = _loaded
    _spec.loader.exec_module(_loaded)

PlanDocs = sys.modules[_MODULE].PlanDocs
migrations = sys.modules[_MODULE].migrations
plan = sys.modules[_MODULE].plan
repo_root = sys.modules[_MODULE].repo_root

__all__ = [
    "GitIndex",
    "PlanDocs",
    "git_index",
    "migrations",
    "plan",
    "released_catalog",
    "repo_root",
]

OFFICE = "parse.office.anydoc"


@pytest.fixture
def released_catalog() -> object:
    """The shipped catalog with `parse.office.anydoc` as a RELEASED build would carry it.

    Two facts move, and they are the two DR9 conjuncts a checkout cannot meet: the trust tier a
    wheel install is pinned at (`first_party`; an editable install is `unpinned`, D576), and a
    green `fuzz` suite in `[quality.suites]`, which only `ow conform` writes and no shipped card
    carries (D599). Every other conjunct is the card's own, so `resolve()` -- not a test -- is
    what grants `inproc` under it.
    """
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.drivers.catalog import Catalog  # noqa: PLC0415
    from omniweave_ports.types import TrustTier  # noqa: PLC0415

    shipped = catalog()
    card = shipped.cards[OFFICE]
    released = dataclasses.replace(
        card, quality=dataclasses.replace(card.quality, suites={"fuzz": "pass"})
    )
    return Catalog.assemble(
        validity_key=shipped.validity_key,
        cards={**shipped.cards, OFFICE: released},
        probe_status={key: str(value) for key, value in shipped.probe_status.items()},
        trust={**shipped.trust, OFFICE: TrustTier.FIRST_PARTY},
        tombstones=shipped.tombstones.values(),
    )


class GitIndex:
    """git's index format, written: the inverse of `omniweave.doctor.gitindex.parse_index`."""

    REGULAR = 0o100644
    DIRECTORY = 0o040000

    @staticmethod
    def varint(value: int) -> bytes:
        """git's `encode_varint` (`varint.c`): each continuation byte stands for one more."""
        out = [value & 0x7F]
        value >>= 7
        while value:
            value -= 1
            out.append(0x80 | (value & 0x7F))
            value >>= 7
        return bytes(reversed(out))

    @classmethod
    def entry(
        cls,
        path: bytes,
        *,
        version: int,
        previous: bytes = b"",
        hash_bytes: int = 20,
        extended: bool = False,
        mode: int = REGULAR,
    ) -> bytes:
        """One entry: stat data, object id, flags, the extended word if set, then the path."""
        stat = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0)
        flags = min(len(path), 0xFFF) | (0x4000 if extended else 0)
        head = stat + b"\x11" * hash_bytes + struct.pack(">H", flags)
        if extended:
            head += struct.pack(">H", 0x2000)  # intent-to-add, the flag `git add -N` sets
        if version == 4:
            common = 0
            while common < min(len(path), len(previous)) and path[common] == previous[common]:
                common += 1
            return head + cls.varint(len(previous) - common) + path[common:] + b"\0"
        body = head + path
        return body + b"\0" * (8 - len(body) % 8)

    @classmethod
    def build(
        cls,
        paths: Sequence[bytes],
        *,
        version: int = 2,
        hash_bytes: int = 20,
        extended: frozenset[bytes] = frozenset(),
        modes: Mapping[bytes, int] | None = None,
        extensions: bytes = b"",
    ) -> bytes:
        """A whole index: header, `paths` in order, `extensions` verbatim, a zero checksum."""
        out = b"DIRC" + struct.pack(">II", version, len(paths))
        previous = b""
        for path in paths:
            out += cls.entry(
                path,
                version=version,
                previous=previous,
                hash_bytes=hash_bytes,
                extended=path in extended,
                mode=(modes or {}).get(path, cls.REGULAR),
            )
            previous = path
        return out + extensions + b"\0" * hash_bytes


@pytest.fixture
def git_index() -> type[GitIndex]:
    """The index writer, as a fixture because a test module cannot import a sibling (TID252)."""
    return GitIndex


SEED_NOW_NS = 1_757_400_000_000_000_000
SEED_DIGEST = b"\x00" * 16
SEED_TEXTS: dict[int, str] = {
    1: "Termination",
    2: "Either party may terminate this agreement with thirty days notice.",
    3: "Fees are payable monthly in arrears.",
}


def _enum_code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _seed(conn: sqlite3.Connection, texts: Mapping[int, str]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, declared, "
        "                achieved) "
        "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', 1, 1, "
        "       'ok', '1.1', '{}', '{}')",
        (b"\x01" * 16, SEED_DIGEST),
    )
    conn.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(1, 1, 1, ?, ?, ?)",
        (_enum_code(conn, "page_kind", "page"), _enum_code(conn, "method", "native"), producer),
    )
    for block_id, text in texts.items():
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
            "                  label, text, content_digest, os_kind, producer_id, method, trust, "
            "                  quote, origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, "
            "       0, 0)",
            (
                block_id,
                f"p1/{block_id}",
                f"d1#{block_id}",
                block_id,
                _enum_code(conn, "kind", "heading" if block_id == 1 else "paragraph"),
                _enum_code(conn, "layer", "body"),
                text,
                SEED_DIGEST,
                _enum_code(conn, "origin_span_kind", "none"),
                producer,
                _enum_code(conn, "method", "native"),
            ),
        )
    conn.execute(
        "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
        "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
        (SEED_NOW_NS,),
    )
    conn.execute("COMMIT")


@pytest.fixture
def seeded_store() -> Callable[..., Path]:
    """Write a migrated `.owstore` at `path` holding one document of `texts` blocks."""
    from omniweave_core.store import migrate  # noqa: PLC0415
    from omniweave_core.store import sqlite as ow  # noqa: PLC0415

    def make(path: Path, texts: Mapping[int, str] = SEED_TEXTS) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = ow.connect(path)
        try:
            migrate.apply_pending(writer, now_ns=SEED_NOW_NS)
            _seed(writer, texts)
        finally:
            writer.close()
        return path

    return make


def _table_block(
    conn: sqlite3.Connection, block_id: int, kind: str, text: str | None, parent: int | None
) -> None:
    producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, parent_id, "
        "                  label, text, content_digest, os_kind, producer_id, method, trust, "
        "                  quote, origin_operator, origin_driver, driver_schema_v, "
        "                  restriction_bits, state) "
        "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, "
        "       0, 0)",
        (
            block_id,
            f"p1/{block_id}",
            f"d1#{block_id}",
            block_id,
            _enum_code(conn, "kind", kind),
            _enum_code(conn, "layer", "body"),
            parent,
            text,
            SEED_DIGEST,
            _enum_code(conn, "origin_span_kind", "none"),
            producer,
            _enum_code(conn, "method", "native"),
        ),
    )


@pytest.fixture
def seeded_table() -> Callable[..., Path]:
    """Add one table to a `seeded_store`, in the shape `DocSink.add_grid` writes it (W7.8n).

    `cells` maps a cell's block id to `(r, c, row_span, col_span, text)`, in row-major order. The
    shape `table_meta` records -- `n_rows`, `row_len`, `n_cols`, `has_merges` -- is derived from
    the cells the way `build_grid()` derives it, so `read_grid()`'s torn-table check passes.
    """
    import sqlite3 as db  # noqa: PLC0415, TID251 -- the fixture seeds a REAL table.

    def make(
        store: Path,
        cells: Mapping[int, tuple[int, int, int, int, str]],
        *,
        table: int = 10,
        header_rows: int = 1,
    ) -> Path:
        row_len: dict[int, int] = {}
        for r, c, row_span, col_span, _text in cells.values():
            for row in range(r, r + row_span):
                row_len[row] = max(row_len.get(row, 0), c + col_span)
        n_rows = max(row_len) + 1
        lengths = [row_len.get(row, 0) for row in range(n_rows)]
        merges = any(rs > 1 or cs > 1 for _r, _c, rs, cs, _t in cells.values())
        conn = db.connect(store)
        try:
            conn.execute("BEGIN IMMEDIATE")
            _table_block(conn, table, "table", None, None)
            for block_id, (_r, _c, _rs, _cs, text) in cells.items():
                _table_block(conn, block_id, "table_cell", text, table)
            conn.execute(
                "INSERT INTO table_meta(block_id, n_rows, n_cols, row_len, header_rows, "
                "                       header_cols, kind, has_merges) "
                "VALUES(?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    table,
                    n_rows,
                    max(lengths),
                    json.dumps(lengths),
                    header_rows,
                    _enum_code(conn, "table_kind", "data"),
                    int(merges),
                ),
            )
            for block_id, (r, c, row_span, col_span, _text) in cells.items():
                conn.execute(
                    "INSERT INTO cell(block_id, table_id, r, c, row_span, col_span) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (block_id, table, r, c, row_span, col_span),
                )
            conn.execute("COMMIT")
        finally:
            conn.close()
        return store

    return make
