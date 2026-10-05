"""`Ordinals`: the `doc_ord` each first-sight document of an ingest takes, fixed in path order.

D654. `doc_ord` was the row a document's first write inserted, so it was the order parses settled
in, which as many threads as a class has workers race. `Ordinals.reserve` numbers the run's
unparsed documents in `unit_uri` order once routing has finished, and a parse takes its
document's. The end-to-end half, two drivers on their own workers, is
`tests/conform/test_add_process.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omniweave_core.store.sqlite as ow
import pytest
from omniweave.run.operators.parse import Ordinals
from omniweave_core.store import migrate

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator
    from pathlib import Path

NOW_NS = 1_757_400_000_000_000_000


def _sha(name: str) -> str:
    return name.encode().hex().ljust(64, "0")[:64]


def _key(name: str) -> bytes:
    return bytes.fromhex(_sha(name))[:16]


UNITS = (
    #  unit_uri, content, work status
    ("file:///corpus/c.pdf", "c", "pending"),
    ("file:///corpus/a.docx", "a", "pending"),
    ("file:///corpus/b.pdf", "b", "failed_transient"),
    ("file:///corpus/d.docx", "a", "pending"),  # a's bytes again: one document
    ("file:///corpus/e.xlsx", "e", "pending"),  # already stored, at doc_ord 5
    ("file:///corpus/f.pptx", "f", "done"),  # parsed by an earlier run
    ("file:///corpus/g.csv", "g", "claimed"),
)


_DECISION = (
    "INSERT OR IGNORE INTO route_decision(decision_id, content_sha256, unit_part, lane, rung, "
    "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
    "rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros, "
    "admission, generation, decided_at) VALUES(?, ?, '', 'text', 0, 'p', 'b', 'h', 'r', "
    "'parse.office.anydoc', 'free', 'r', 'o', ?, 'e', '{}', 0, 0, 'admitted', 1, 0)"
)


@pytest.fixture
def thread(tmp_path: Path) -> Iterator[ow.StoreThread]:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        with connection:
            connection.execute(
                "INSERT INTO route_evidence(evidence_digest, payload, swept_at, first_seen_at)"
                " VALUES('e', '{}', NULL, 0)"
            )
            for at, (uri, content, status) in enumerate(UNITS, start=1):
                connection.execute(
                    "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen, content_sha256)"
                    " VALUES(?, 'planned', 'internal', 1, ?)",
                    (uri, _sha(content)),
                )
                connection.execute(_DECISION, (f"dec_{content}", _sha(content), content))
                connection.execute(
                    "INSERT INTO work(id, unit_uri, operator, op_version, cache_key, decision_id,"
                    " driver, dispatch_key, cost_class, status)"
                    " VALUES(?, ?, 'parse.office', 1, ?, ?, 'parse.office.anydoc', 'd', 'free', ?)",
                    (at, uri, f"k{at}", f"dec_{content}", status),
                )
            connection.execute(
                "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen, content_sha256)"
                " VALUES('file:///corpus/0.zip', 'acquired', 'internal', 1, ?)",
                (_sha("z"),),
            )
            connection.execute(  # not a parse row: identified, not yet routed
                "INSERT INTO work(id, unit_uri, operator, op_version, cache_key, cost_class,"
                " status) VALUES(99, 'file:///corpus/0.zip', 'op.identify', 1, 'k99', 'free',"
                " 'pending')"
            )
            connection.execute(
                "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
                " format_evidence, source_bytes, status, model_version, declared, achieved)"
                " VALUES(5, ?, X'00', 'file:///corpus/e.xlsx', 'application/x', 'xlsx', '{}', 1,"
                " 'ok', '1.1', '{}', '{}')",
                (_key("e"),),
            )
    finally:
        connection.close()
    handle = ow.StoreThread(lambda: ow.connect(path)).start()
    try:
        yield handle
    finally:
        handle.close()


def test_the_unparsed_documents_are_numbered_in_path_order_past_the_highest(
    thread: ow.StoreThread,
) -> None:
    """a, b, c, g in path order from 6, whatever order their parses settle in. d is a's bytes,
    so the same document; e is in the store and keeps 5; f's row is done and is not this run's."""
    ordinals = Ordinals()
    assert ordinals.reserve(thread) == 4
    assert [ordinals.take(_key(name)) for name in "gcab"] == [9, 8, 6, 7]
    assert ordinals.take(_key("a")) == 6, "a parse retried in the same run takes the same number"


def test_a_document_the_reservation_did_not_see_takes_the_next_number_past_it(
    thread: ow.StoreThread,
) -> None:
    """A parse row written after `reserve` never takes a reserved number, which would make the
    reserved document fall back to SQLite's choice; it takes the next one, and keeps it."""
    ordinals = Ordinals()
    ordinals.reserve(thread)
    assert ordinals.take(_key("late")) == 10
    assert ordinals.take(_key("later")) == 11
    assert ordinals.take(_key("late")) == 10


def test_before_reserve_nothing_is_reserved_and_sqlite_chooses() -> None:
    """The drain that finishes an interrupted run's parses runs before routing; `take` answers
    `None` there and `DocSink` leaves the rowid to SQLite."""
    assert Ordinals().take(_key("a")) is None
