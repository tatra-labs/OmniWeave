"""`ow graph review` (D700): the rows the graph holds below `EXTRACTED`, weakest first."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import graph as verb
from omniweave.surface.graph import review_document
from omniweave.surface.registry import ACTIONS
from omniweave_core.store.review import review
from test_graph_cluster import _ids
from test_graph_decide import _ingested, _store

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("review"))


def _graded(connection: sqlite3.Connection) -> dict[str, int]:
    """Two closures (one fuzzy, one exact), a tainted, an overloaded, and graded rows."""
    ids = _ids(connection)
    set_head = "UPDATE entity SET canonical_id = ?, resolution_trust = ? WHERE entity_id IN (?, ?)"
    connection.execute(set_head, (ids["acme_holdings"], 1, ids["acme_holdings"], ids["gamma_inc"]))
    connection.execute(set_head, (ids["beta_corp"], 2, ids["beta_corp"], ids["zeta_group"]))
    connection.execute("UPDATE entity SET taint = 4 WHERE entity_id = ?", (ids["iota_works"],))
    connection.execute("UPDATE entity SET state = 1 WHERE entity_id = ?", (ids["kappa_foods"],))
    connection.execute("UPDATE mention SET trust = 2, taint = 0")
    for key, trust, taint in [
        ("acme_holdings", 1, 0),
        ("beta_corp", 0, 0),
        ("gamma_inc", 1, 2),
        ("delta_partners", 2, 8),
    ]:
        connection.execute(
            "UPDATE mention SET trust = ?, taint = ? WHERE entity_id = ?", (trust, taint, ids[key])
        )
    for src, dst, relation, trust, taint in [
        ("acme_holdings", "beta_corp", "related_to", 1, 0),
        ("beta_corp", "gamma_inc", "party_to", 1, 0),
        ("gamma_inc", "delta_partners", "related_to", 2, 1),
        ("delta_partners", "eta_systems", "related_to", 0, 0),
        ("eta_systems", "theta_labs", "related_to", 2, 0),
    ]:
        connection.execute(
            "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust,"
            " taint) SELECT ?, ?, ?, MIN(block_id), MIN(run_id), ?, ? FROM block, derive_run"
            " WHERE block.state = 0",
            (ids[src], ids[dst], relation, trust, taint),
        )
    return ids


def _cites(connection: sqlite3.Connection) -> dict[str, str]:
    return {key: f"e{entity_id}" for key, entity_id in _ids(connection).items()}


def test_closures_entities_mentions_and_edges_weakest_first(parties: Path) -> None:
    """Rulings 1-4."""
    connection = sqlite3.connect(_store(parties))
    try:
        _graded(connection)
        cite = _cites(connection)
        found = review(connection)
        assert [(c.head, c.members, c.resolution_trust) for c in found.closures] == [
            (cite["acme_holdings"], 2, 1)
        ], "the exact closure and the singletons are not reviewed"
        assert found.closures_total == 1
        assert [(e.entity, e.overloaded, e.taint) for e in found.entities] == [
            (cite["kappa_foods"], True, 0),
            (cite["iota_works"], False, 4),
        ]
        assert [(m.entity, m.trust, m.taint) for m in found.mentions] == sorted(
            [(m.entity, m.trust, m.taint) for m in found.mentions],
            key=lambda row: (row[1], -row[2]),
        )
        assert {m.entity for m in found.mentions} == {
            cite["acme_holdings"],
            cite["beta_corp"],
            cite["gamma_inc"],
            cite["delta_partners"],
        }, "a tainted mention is reviewed at any trust"
        assert (found.mentions[-1].trust, found.mentions[-1].taint) == (2, 8)
        assert found.mentions[0].entity == cite["beta_corp"], "AMBIGUOUS before INFERRED"
        first_inferred = next(m for m in found.mentions if m.trust == 1)
        assert first_inferred.taint == 2, "a tainted row before a clean one of the same trust"
        assert [(e.src, e.relation, e.trust, e.taint) for e in found.edges] == [
            (cite["delta_partners"], "related_to", 0, 0),
            (cite["beta_corp"], "party_to", 1, 0),
            (cite["acme_holdings"], "related_to", 1, 0),
            (cite["gamma_inc"], "related_to", 2, 1),
        ]
        assert found.edges_total == 4
        assert found.mentions_total == len(found.mentions)
    finally:
        connection.rollback()
        connection.close()


def test_an_edge_in_a_retired_block_and_a_retired_entity_are_not_reviewed(parties: Path) -> None:
    """Ruling 3: live rows only."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _graded(connection)
        connection.execute(
            "UPDATE block SET state = 1 WHERE block_id = (SELECT MIN(block_id) FROM block)"
        )
        connection.execute(
            "UPDATE entity SET state = 2 WHERE entity_id IN (?, ?)",
            (ids["iota_works"], ids["gamma_inc"]),
        )
        connection.execute("UPDATE mention SET state = 1 WHERE entity_id = ?", (ids["beta_corp"],))
        found = review(connection)
        assert (found.edges, found.edges_total) == ((), 0)
        assert found.closures == (), "a closure of one live member is not a merge to review"
        assert [e.overloaded for e in found.entities] == [True]
        assert _cites(connection)["beta_corp"] not in {m.entity for m in found.mentions}
    finally:
        connection.rollback()
        connection.close()


def test_each_list_is_cut_and_keeps_its_total(parties: Path) -> None:
    """Ruling 5."""
    connection = sqlite3.connect(_store(parties))
    try:
        _graded(connection)
        every = review(connection)
        cut = review(connection, limit=1)
        assert cut.edges == every.edges[:1] and cut.edges_total == every.edges_total == 4
        assert cut.entities == every.entities[:1] and cut.entities_total == 2
        assert cut.mentions == every.mentions[:1]
        assert cut.mentions_total == every.mentions_total > 1
        assert cut.limit == 1
    finally:
        connection.rollback()
        connection.close()


def test_the_json_qualifies_every_cite_when_two_corpora_exist(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        _graded(connection)
        document = review_document(review(connection), corpus="h", qualify=True)
    finally:
        connection.rollback()
        connection.close()
    cites = [row["head"] for row in document["closures"]]
    cites += [row["entity"] for row in document["entities"]]
    cites += [row[k] for row in document["mentions"] for k in ("entity", "cite")]
    cites += [row[k] for row in document["edges"] for k in ("src", "dst", "cite")]
    assert cites and all(cite.startswith("h:") for cite in cites)


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_renders_the_four_lists(tmp_path: Path) -> None:
    project = _ingested(tmp_path)
    connection = sqlite3.connect(_store(project))
    try:
        _graded(connection)
        connection.commit()
        cite = _cites(connection)
    finally:
        connection.close()
    code, out, err = _verb(["review", "--render", "json"], project)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert document["closures"][0]["head"] == cite["acme_holdings"]
    assert document["closures"][0]["resolution_trust"] == 1
    assert document["entities"][0]["overloaded"] is True
    assert (document["edges_total"], document["limit"]) == (4, 100)
    code, out, err = _verb(["review"], project)
    assert (code, err) == (0, ""), err
    lines = out.splitlines()
    assert lines[0] == (
        f"review: 1 closure(s) resolved below extracted, 2 entities tainted or overloaded, "
        f"{document['mentions_total']} mention(s), 4 edge(s)"
    )
    assert f"    {cite['kappa_foods']}  Kappa Foods (org)  overloaded" in lines


@pytest.mark.parametrize(
    ("argv", "code"),
    [(["review", "--quiet"], 1), (["review", "--corpus", "other"], 2)],
    ids=["quiet", "undeclared"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


def test_the_action_reads_and_has_no_tool() -> None:
    spec = ACTIONS["graph.review"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        True,
        False,
        True,
    )
