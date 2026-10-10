"""STEP 7's salience, all four columns, and GR16's recount (D692)."""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path

import pytest
from omniweave.graph import salience
from omniweave.graph.salience import check, recount
from omniweave_core.errors import InternalError
from test_graph_cluster import APART, LEFT, PARTIES, RIGHT, _edge, _graph, _ids
from test_run_parse import _project, _rows, _run


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("salience")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return store


def _salience(connection: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    return {
        str(k): (int(f), int(d), int(c))
        for k, f, d, c in connection.execute(
            "SELECT key, frequency, degree, doc_count FROM entity"
        ).fetchall()
    }


def test_an_ingest_writes_every_entitys_mentions_and_documents(parties: Path) -> None:
    """Each party is one table row: one Segment, one document, and no edge yet."""
    connection = sqlite3.connect(parties)
    try:
        assert set(_salience(connection).values()) == {(1, 0, 1)}
        assert recount(connection).moved is False, "the ingest already wrote them"
        check(connection)
    finally:
        connection.close()


def test_degree_is_distinct_neighbour_closures_and_combined_degree_their_sum(
    parties: Path,
) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        _edge(connection, LEFT[0], LEFT[1], relation="cites")  # a second edge, one neighbour
        report = recount(connection)
        assert report.moved
        found = _salience(connection)
        assert found[LEFT[0]] == (1, 3, 1), "beta twice is one neighbour"
        assert found[LEFT[-1]] == (1, 4, 1), "delta also reaches epsilon"
        assert found[APART[0]] == (1, 1, 1)
        combined = dict(
            connection.execute(
                "SELECT s.key || '-' || t.key, g.combined_degree FROM edge g"
                " JOIN entity s ON s.entity_id = g.src_entity"
                " JOIN entity t ON t.entity_id = g.dst_entity"
                " WHERE s.key = ? AND t.key = ?",
                (LEFT[-1], RIGHT[0]),
            ).fetchall()
        )
        assert combined == {f"{LEFT[-1]}-{RIGHT[0]}": 8}
        check(connection)
        assert not recount(connection).moved, "a second pass writes nothing"
    finally:
        connection.rollback()
        connection.close()


def test_a_closure_is_counted_once_and_stamped_on_every_member(parties: Path) -> None:
    """06:270: a merge sums the closure's distinct Segments, documents and neighbours, and every
    member row carries the closure's numbers; the edge between the two is a loop and joins
    nothing."""
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        ids = _ids(connection)
        connection.execute(
            "UPDATE entity SET canonical_id = ? WHERE entity_id = ?",
            (ids[LEFT[0]], ids[LEFT[1]]),
        )
        recount(connection)
        found = _salience(connection)
        assert found[LEFT[0]] == found[LEFT[1]] == (1, 2, 1), (
            "one table Segment, gamma and delta: the loop to beta is no neighbour"
        )
        check(connection)
    finally:
        connection.rollback()
        connection.close()


def test_what_does_not_count(parties: Path) -> None:
    """Ruling 1: a retired block, a retired mention and a retired entity's edge count for
    nothing; an overloaded entity is still counted; a retired entity keeps its numbers."""
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        _edge(connection, LEFT[0], LEFT[2], relation="cites", last=True)
        recount(connection)
        connection.execute(
            "UPDATE block SET state = 1 WHERE block_id = (SELECT MAX(block_id) FROM block"
            " WHERE state = 0)"
        )
        connection.execute("UPDATE entity SET state = 2 WHERE key = ?", (RIGHT[0],))
        connection.execute("UPDATE entity SET state = 1 WHERE key = ?", (RIGHT[1],))
        recount(connection)
        found = _salience(connection)
        assert found[APART[0]] == (1, 0, 1), "its only edge's block retired"
        assert found[LEFT[-1]] == (1, 3, 1), "epsilon retired: the bridge joins nothing"
        assert found[RIGHT[1]][1] == 2, "overloaded and still counted"
        assert found[RIGHT[0]] == (1, 4, 1), "retired: its last numbers"
        [(combined,)] = connection.execute(
            "SELECT g.combined_degree FROM edge g JOIN entity s ON s.entity_id = g.src_entity"
            " WHERE s.key = ?",
            (APART[0],),
        ).fetchall()
        assert combined == 0
        [(dead,)] = connection.execute(
            "SELECT g.combined_degree FROM edge g WHERE g.relation = 'cites'"
        ).fetchall()
        assert dead == 0, "its block retired: it joins nothing, though both its ends are joined"
        check(connection)
    finally:
        connection.rollback()
        connection.close()


def test_frequency_counts_segments_and_doc_count_documents(tmp_path: Path) -> None:
    """A memo of two sections names acme in each, and the table holds its row: three Segments,
    two documents."""
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    filler = " ".join(["filler"] * 900)
    (tmp_path / "docs" / "memo.md").write_text(
        f"# One\n\nAcme Holdings signed first. {filler}\n\n"
        f"# Two\n\nAcme Holdings signed again. {filler}\n",
        encoding="utf-8",
    )
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert _rows(
        store, "SELECT frequency, degree, doc_count FROM entity WHERE key = 'acme_holdings'"
    ) == [(3, 0, 2)]


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE entity SET frequency = frequency + 1 WHERE key = 'beta_corp'",
        "UPDATE entity SET degree = 7 WHERE key = 'beta_corp'",
        "UPDATE entity SET doc_count = 0 WHERE key = 'beta_corp'",
        "UPDATE edge SET combined_degree = 99 WHERE edge_id = (SELECT MIN(edge_id) FROM edge)",
    ],
    ids=["frequency", "degree", "doc_count", "combined_degree"],
)
def test_gr16_fails_on_any_column_a_recount_disagrees_with(parties: Path, tamper: str) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        recount(connection)
        check(connection)
        connection.execute(tamper)
        with pytest.raises(InternalError, match="GR16"):
            check(connection)
    finally:
        connection.rollback()
        connection.close()


def test_ingest_recounts_after_the_graph_and_says_so(tmp_path: Path) -> None:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    first = _run(tmp_path, store, config)
    assert first.salience is not None and first.salience.entities == 10
    assert any(line.startswith("  salience") for line in first.lines())
    connection = sqlite3.connect(store)
    try:
        _graph(connection)
        connection.commit()
    finally:
        connection.close()
    second = _run(tmp_path, store, config)
    assert second.salience is not None and second.salience.edges == 14
    assert _rows(store, "SELECT degree FROM entity WHERE key = 'delta_partners'") == [(4,)]
    third = _run(tmp_path, store, config)
    assert third.salience is not None and not third.salience.moved
    assert not any(line.startswith("  salience") for line in third.lines())


def test_a_run_whose_recount_disagrees_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GR16 FAILS THE RUN: a write that disagrees with the recount is rolled back and raised."""
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    monkeypatch.setattr(salience, "_ENTITY_SQL", salience._ENTITY_SQL.replace(
        "degree = :degree", "degree = :degree + 1"))  # fmt: skip
    with pytest.raises(InternalError, match="GR16"):
        _run(tmp_path, store, config)
    assert _rows(store, "SELECT DISTINCT degree FROM entity") == [(0,)], "rolled back"
