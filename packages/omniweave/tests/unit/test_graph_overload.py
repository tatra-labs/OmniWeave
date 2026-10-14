"""Entity overload: a template artefact judged on its own incidence (D693)."""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path

import pytest
from omniweave.graph import cluster as cluster_module
from omniweave.graph import resolve as module
from omniweave.graph.resolve import overload, resolve
from omniweave_core.store import lexicon
from test_graph_cluster import LEFT, PARTIES, RIGHT, _graph, _ids
from test_run_parse import _project, _rows, _run


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("overload")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return store


@pytest.mark.parametrize(
    ("frequency", "degree", "docs", "fired"),
    [
        (5, 0, 1, "frequency"),
        (0, 5, 1, "degree"),
        (5, 5, 1, "frequency"),
        (5, 5, 0, "frequency"),
        (5, 5, 2, None),
        (4, 4, 1, None),
    ],
    ids=["frequency", "degree", "frequency_first", "no_document", "two_documents", "at_the_cap"],
)
def test_the_rule(frequency: int, degree: int, docs: int, fired: str | None) -> None:
    """Ruling 18: either incidence over the cap, in one document at most; the cap itself is not
    over it."""
    assert overload(frequency, degree, docs, cap=4) == fired


def _state(connection: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """key -> (state, canonical is itself)."""
    return {
        str(k): (int(s), int(e == c))
        for k, s, e, c in connection.execute(
            "SELECT key, state, entity_id, canonical_id FROM entity"
        ).fetchall()
    }


def _quarantined(connection: sqlite3.Connection) -> list[tuple[str, dict[str, object]]]:
    return [
        (str(json.loads(str(p))["key"]), json.loads(str(d)))
        for p, d in connection.execute(
            "SELECT payload, detail FROM quarantine WHERE code = ? ORDER BY q_id",
            (module.OVERLOAD_CODE,),
        ).fetchall()
    ]


def test_a_degree_over_the_cap_in_one_document_overloads(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delta and epsilon each have four neighbours; the others three. At a cap of 3 the two are
    template artefacts of the one table they are named in."""
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        report = resolve(connection, gen=90)
        assert (report.overloaded, report.flagged) == (2, 2)
        assert report.moved and "2 overloaded" in report.line()
        states = _state(connection)
        assert states[LEFT[-1]] == states[RIGHT[0]] == (module.OVERLOADED, 1)
        assert {k for k, (s, _) in states.items() if s == module.OVERLOADED} == {
            LEFT[-1],
            RIGHT[0],
        }
        assert _quarantined(connection) == [
            (LEFT[-1], {"cap": 3, "doc_count": 1, "incidence": "degree", "value": 4}),
            (RIGHT[0], {"cap": 3, "doc_count": 1, "incidence": "degree", "value": 4}),
        ]
        [(row_kind, run_pass)] = connection.execute(
            "SELECT DISTINCT q.row_kind, r.pass_id FROM quarantine q"
            " JOIN derive_run r USING (run_id) WHERE q.code = ?",
            (module.OVERLOAD_CODE,),
        ).fetchall()
        assert (row_kind, run_pass) == ("entity", "op.resolve")
        again = resolve(connection, gen=91)
        assert (again.overloaded, again.flagged, again.moved) == (2, 0, False), "a fixed point"
    finally:
        connection.rollback()
        connection.close()


def test_an_overloaded_entity_leaves_ranking_resolution_and_clustering(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        resolve(connection, gen=90)
        heads = {str(k) for (k,) in connection.execute("SELECT key FROM ow_entity_head")}
        assert LEFT[-1] not in heads and RIGHT[0] not in heads
        found = cluster_module.cluster(connection, gen=90)
        members = {
            str(k)
            for (k,) in connection.execute(
                "SELECT e.key FROM community_member m JOIN entity e USING (entity_id)"
            )
        }
        assert found.entities == 8
        assert LEFT[-1] not in members and RIGHT[0] not in members
    finally:
        connection.rollback()
        connection.close()


def test_overload_reverses_when_the_incidence_falls_and_is_quarantined_once(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 18: a function of the corpus as it stands. Ruling 19: one row per entity, ever."""
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        resolve(connection, gen=90)
        ids = _ids(connection)
        [(block,)] = connection.execute(
            "SELECT observed_block FROM edge WHERE src_entity = ? AND dst_entity = ?",
            (ids[LEFT[-1]], ids[RIGHT[0]]),
        ).fetchall()
        connection.execute("UPDATE block SET state = 1 WHERE block_id = ?", (block,))
        released = resolve(connection, gen=91)
        assert (released.overloaded, released.flagged) == (0, 2), (
            "every clique edge sat in one block: retiring it drops every degree"
        )
        assert set(_state(connection).values()) == {(0, 1)}
        connection.execute("UPDATE block SET state = 0 WHERE block_id = ?", (block,))
        resolve(connection, gen=92)
        assert len(_quarantined(connection)) == 2, "overloaded again, quarantined once"
    finally:
        connection.rollback()
        connection.close()


def test_a_retired_neighbour_or_a_retired_block_counts_for_nothing(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 17: delta's fourth neighbour retired is three; a mention in a retired block is no
    Segment and no document."""
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        connection.execute("UPDATE entity SET state = 2 WHERE key = ?", (RIGHT[0],))
        assert resolve(connection, gen=90).overloaded == 0
        connection.execute("UPDATE entity SET state = 0 WHERE key = ?", (RIGHT[0],))
        monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 0)
        connection.execute(
            "UPDATE block SET state = 1 WHERE block_id IN (SELECT block_id FROM mention m"
            " JOIN entity e USING (entity_id) WHERE e.key = 'kappa_foods')"
        )
        connection.execute("DELETE FROM edge")
        resolve(connection, gen=91)
        assert _state(connection)["kappa_foods"][0] == 0, "no live mention: nothing to count"
    finally:
        connection.rollback()
        connection.close()


def test_frequency_is_the_entitys_own_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 17: acme in two sections of a memo and once in the table is three Segments in two
    documents -- never overloaded. With the table's mention retired it is two Segments of one
    document, and over a cap of 1."""
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    filler = " ".join(["filler"] * 900)
    (tmp_path / "docs" / "memo.md").write_text(
        f"# One\n\nAcme Holdings signed first. {filler}\n\n"
        f"# Two\n\nAcme Holdings signed again. {filler}\n",
        encoding="utf-8",
    )
    _run(tmp_path, store, config)
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 1)
    connection = sqlite3.connect(store)
    try:
        assert _state(connection)["acme_holdings"] == (0, 1), "two documents"
        connection.execute(
            "UPDATE mention SET state = 1 WHERE entity_id = (SELECT entity_id FROM entity"
            " WHERE key = 'acme_holdings') AND block_id IN (SELECT block_id FROM block b"
            " JOIN doc d USING (doc_ord) WHERE d.uri LIKE '%parties.csv')"
        )
        report = resolve(connection, gen=90)
        assert report.overloaded == 1
        assert _quarantined(connection)[0][1]["incidence"] == "frequency"
        assert _quarantined(connection)[0][1]["value"] == 2
    finally:
        connection.rollback()
        connection.close()


def test_an_overloaded_member_leaves_its_closure_as_its_own_head(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 18: delta merged under acme by a shared alias; overloaded, it heads itself and the
    merge retires."""
    connection = sqlite3.connect(parties)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings', 'Acme Holdings', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids[LEFT[-1]], ids[LEFT[-1]]),
        )
        assert resolve(connection, gen=90).kept == 1
        assert _state(connection)[LEFT[-1]] == (0, 0), "merged under acme"
        monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
        _graph(connection)
        report = resolve(connection, gen=91)
        assert (report.kept, report.retired) == (0, 1)
        assert _state(connection)[LEFT[-1]] == (module.OVERLOADED, 1)
    finally:
        connection.rollback()
        connection.close()


def test_the_lexicon_keeps_an_overloaded_name(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`store.lexicon` ruling 1 as amended: overload is judged on the gazetteer's mentions too, so
    the name must stay findable or the judgment would undo itself."""
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    connection = sqlite3.connect(parties)
    try:
        before = lexicon.build(connection)
        _graph(connection)
        resolve(connection, gen=90)
        after = lexicon.build(connection)
        assert after.body == before.body, "overloading moved nothing the gazetteer reads"
        assert b'"delta_partners"' in after.body
    finally:
        connection.rollback()
        connection.close()


def test_an_ingest_reports_the_overloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    _run(tmp_path, store, config)
    connection = sqlite3.connect(store)
    try:
        _graph(connection)
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(module, "MAX_ENTITY_DEGREE", 3)
    report = _run(tmp_path, store, config)
    assert report.resolved is not None and report.resolved.overloaded == 2
    assert any("2 overloaded" in line for line in report.lines()), report.lines()
    assert _rows(store, "SELECT count(*) FROM entity WHERE state = 1") == [(2,)]
    assert _rows(store, "SELECT DISTINCT degree FROM entity WHERE state = 1") == [(4,)], (
        "salience still counts an overloaded entity, on its own"
    )
