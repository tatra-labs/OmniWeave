"""`0005_out.sql`: the OUT tables, applied in order onto an empty store and held to their DDL.

07-store-and-retrieval.md section 3's 0005 row; charter.md:6071-6155's "OUT DDL"; 09-generation.md
section 5.4 (`artifact_pure`, the sealed-row trigger, OUT24), section 5.5 (the reason CHECK) and
section 10 (`artifact_cite`). Each behaviour the DDL promises is asserted against a real store:
a sealed row cannot be patched or deleted, a draft and a release of the same six digests coexist,
and "which decks quote this block?" is one indexed query.
"""

from __future__ import annotations

import re
import sqlite3  # noqa: TID251 -- this file drives a REAL store, as test_store_integration.py does.
from collections.abc import Iterator
from pathlib import Path

import pytest
from omniweave_core.errors import explain
from omniweave_core.store import migrate

MIGRATIONS = Path(migrate.__file__).parent / "schema" / "migrations"
OUT = MIGRATIONS / "0005_out.sql"
TABLES = ("artifact", "artifact_unit", "artifact_asset", "artifact_cite", "artifact_el")
NOW_NS = 1_700_000_000_000_000_000
HEX = bytes(32)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(tmp_path / "index.owstore", isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    applied = migrate.apply_pending(connection, now_ns=NOW_NS)
    assert [m.version for m in applied] == [1, 2, 3, 4, 5]
    connection.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES (1, 'compile.text.owtext', 1, 'f', ?)",
        (HEX,),
    )
    yield connection
    connection.close()


def _artifact(connection: sqlite3.Connection, **fields: object) -> int:
    row: dict[str, object] = {
        "slug": "q3-board",
        "artifact_gen": 1,
        "origin": "authored",
        "target": "pptx",
        "compile_driver": "compile.pptx.native",
        "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "path": "q3-board@1/q3-board.pptx",
        "sha256": HEX,
        "byte_len": 10,
        "part_digest": HEX,
        "il_digest": HEX,
        "il_store_ref": "cas://00/00/" + "0" * 64,
        "constructs_digest": HEX,
        "ledger_digest": HEX,
        "card_sha256": HEX,
        "determinism": '["part"]',
        "gate_status": "passed",
        "delivery": "release",
        "report_sha256": HEX,
        "receipt_sha256": HEX,
        "producer_id": 1,
        "sealed_at_ns": NOW_NS,
    }
    row.update(fields)
    cursor = connection.execute(
        f"INSERT INTO artifact({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",  # noqa: S608
        list(row.values()),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_the_file_is_house_style() -> None:
    raw = OUT.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    text = raw.decode("ascii")
    assert all(len(line) <= 100 for line in text.split("\n"))
    head = "\n".join(text.split("\n")[:10])
    assert head.startswith("-- 0005_out.sql")
    assert "07-store-and-retrieval.md section 3" in head
    assert "11-repo-layout.md:1188" in head
    body = "\n".join(line.split("--", 1)[0] for line in text.split("\n"))
    assert not re.search(r"IF\s+NOT\s+EXISTS|\bPRAGMA\b|\bCOMMIT\b", body, re.IGNORECASE)
    for table in TABLES:
        assert re.search(rf"-- \[(SOR|DER)\][^\n]*\n(--[^\n]*\n)*CREATE TABLE {table} \(", text), (
            table
        )


def test_the_five_tables_and_their_indexes_exist(store: sqlite3.Connection) -> None:
    objects = {
        (kind, name)
        for kind, name in store.execute(
            "SELECT type, name FROM sqlite_master WHERE name LIKE 'artifact%'"
        )
    }
    assert {("table", t) for t in TABLES} <= objects
    assert {("index", "artifact_pure"), ("index", "artifact_cite_block")} <= objects
    assert {
        ("trigger", "artifact_sealed_no_update"),
        ("trigger", "artifact_sealed_no_delete"),
    } <= objects


# ---------------------------------------------------------------------------
# OUT24: a sealed row is never patched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "word"),
    [
        ("UPDATE artifact SET gate_status = 'failed' WHERE artifact_id = ?", "patched"),
        ("DELETE FROM artifact WHERE artifact_id = ?", "deleted"),
    ],
)
def test_a_sealed_artifact_row_is_never_patched_or_deleted(
    store: sqlite3.Connection, statement: str, word: str
) -> None:
    artifact_id = _artifact(store)
    with pytest.raises(
        sqlite3.IntegrityError, match=f"OW-T-511 a sealed artifact row is never {word}"
    ):
        store.execute(statement, (artifact_id,))
    assert explain("OW-T-511").symbol == "OW_TARGET_ARTIFACT_SEALED"


def test_an_unsealed_row_cannot_exist() -> None:
    """`sealed_at_ns` is NOT NULL: there is no state between no row and a sealed row."""
    text = OUT.read_text(encoding="ascii")
    assert re.search(r"sealed_at_ns\s+INTEGER NOT NULL,", text)


def test_a_new_generation_is_a_new_row(store: sqlite3.Connection) -> None:
    _artifact(store)
    _artifact(store, artifact_gen=2, gate_status="passed", il_digest=b"\x01" * 32)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _artifact(store, artifact_gen=2, il_digest=b"\x02" * 32)


def test_artifact_pure_keys_six_digests_with_slug_and_delivery(store: sqlite3.Connection) -> None:
    """A draft and a release of one input coexist; a second release of it is the cache hit.

    D751 amended the index to hold `brief_digest`, the sixth digest 09 section 5.4 printed
    without: a new brief over one IL is a new row.
    """
    _artifact(store)
    _artifact(store, artifact_gen=2, delivery="draft", gate_status="manual-required")
    _artifact(store, artifact_gen=3, slug="q3-board-copy")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _artifact(store, artifact_gen=4)
    _artifact(store, artifact_gen=5, toolchain_digest=b"\x09" * 32)
    _artifact(store, artifact_gen=6, brief_digest=b"\x05" * 32)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _artifact(store, artifact_gen=7, brief_digest=b"\x05" * 32)


def test_the_loop_closes_once_and_nothing_else_moves(store: sqlite3.Connection) -> None:
    """D751's amendment: `read_back_doc_ord` goes from NULL to a document once."""
    artifact_id = _artifact(store)
    store.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
        " format_evidence, source_bytes, status, model_version, declared, achieved)"
        " VALUES (3, ?, ?, 'file:///out/q3-board.pptx', 'application/x', 'pptx', '{}', 1, 'ok',"
        " '1.1', '{}', '{}')",
        (b"\x03" * 16, HEX),
    )
    for statement in (
        "UPDATE artifact SET read_back_doc_ord = 3, gate_status = 'failed' WHERE artifact_id = ?",
        "UPDATE artifact SET read_back_doc_ord = NULL WHERE artifact_id = ?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="OW-T-511"):
            store.execute(statement, (artifact_id,))
    store.execute("UPDATE artifact SET read_back_doc_ord = 3 WHERE artifact_id = ?", (artifact_id,))
    for value in (3, None):
        with pytest.raises(sqlite3.IntegrityError, match=r"OW-T-511 .* read back once"):
            store.execute(
                "UPDATE artifact SET read_back_doc_ord = ? WHERE artifact_id = ?",
                (value, artifact_id),
            )


def test_the_sealed_trigger_names_every_column_but_the_loop(store: sqlite3.Connection) -> None:
    """A column `UPDATE OF` omits is a column a sealed row lets anyone patch."""
    (sql,) = store.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'artifact_sealed_no_update'"
    ).fetchone()
    listed = re.search(r"UPDATE OF\s+(.*?)\s+ON artifact", sql, re.DOTALL)
    assert listed is not None
    named = [c.strip() for c in listed.group(1).split(",")]
    columns = [row[1] for row in store.execute("PRAGMA table_info(artifact)")]
    assert sorted(named) == sorted(c for c in columns if c != "read_back_doc_ord")


@pytest.mark.parametrize(
    ("column", "value"),
    [("origin", "imported"), ("delivery", "final")],
)
def test_the_artifact_checks_hold(store: sqlite3.Connection, column: str, value: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _artifact(store, **{column: value})


# ---------------------------------------------------------------------------
# The child tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "reason", "ok"),
    [
        ("native", None, True),
        ("baked", None, False),
        ("baked", "style.mix-blend-mode at 192 dpi", True),
        ("manual_required", None, False),
        ("manual_required", "unverifiable_data", True),
        ("exported", "x", False),
    ],
)
def test_artifact_unit_holds_the_outcome_vocabulary_and_the_reason_check(
    store: sqlite3.Connection, outcome: str, reason: str | None, ok: bool
) -> None:
    artifact_id = _artifact(store)

    def insert() -> None:
        store.execute(
            "INSERT INTO artifact_unit(artifact_id, unit, ord, outcome, il_path, il_sha256, nsig,"
            " reason) VALUES (?, 'u01', 1, ?, 'il/u01.svg', ?, '0000abcd', ?)",
            (artifact_id, outcome, HEX, reason),
        )

    if ok:
        insert()
    else:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            insert()


def test_artifact_cite_kind_and_the_block_index(store: sqlite3.Connection) -> None:
    artifact_id = _artifact(store)
    store.execute(
        "INSERT INTO artifact_cite(artifact_id, unit, el, cite, block_id, doc_gen, kind)"
        " VALUES (?, 'u01', 'u01/e2', 'd7#412', NULL, 3, 'quote')",
        (artifact_id,),
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.execute(
            "INSERT INTO artifact_cite(artifact_id, unit, el, cite, doc_gen, kind)"
            " VALUES (?, 'u01', 'u01/e3', 'd7#413', 3, 'rumour')",
            (artifact_id,),
        )
    plan = " ".join(
        str(row[-1])
        for row in store.execute(
            "EXPLAIN QUERY PLAN SELECT artifact_id FROM artifact_cite WHERE block_id = ?", (1,)
        )
    )
    assert "artifact_cite_block" in plan, plan


def test_a_child_row_names_a_real_artifact(store: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.execute(
            "INSERT INTO artifact_unit(artifact_id, unit, ord, outcome, il_path, il_sha256, nsig)"
            " VALUES (99, 'u01', 1, 'native', 'il/u01.svg', ?, '0000abcd')",
            (HEX,),
        )
