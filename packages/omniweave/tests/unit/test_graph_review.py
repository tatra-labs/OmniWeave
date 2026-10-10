"""`ow graph review` (D700): the rows the graph holds below `EXTRACTED`, weakest first."""

from __future__ import annotations

import io
import json
import shlex
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph import decide
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


TRIANGLES = [
    ("acme_holdings", "beta_corp"),
    ("acme_holdings", "delta_partners"),
    ("beta_corp", "delta_partners"),
    ("epsilon_trust", "gamma_inc"),
    ("zeta_group", "gamma_inc"),
    ("epsilon_trust", "zeta_group"),
]
"""Two triangles; merging acme and gamma joins them through one head. Gamma is only ever an edge's
destination, so a reach read off one end alone would miss it."""


def _two_people_one_name(
    connection: sqlite3.Connection, extra: Sequence[tuple[str, str]] = ()
) -> None:
    """The triangles' edges, then a user merge of acme and gamma, settled with communities."""
    ids = _ids(connection)
    for src, dst in [*TRIANGLES, *extra]:
        connection.execute(
            "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust)"
            " SELECT ?, ?, 'related_to', MIN(block_id), MIN(run_id), 2 FROM block, derive_run"
            " WHERE block.state = 0",
            (ids[src], ids[dst]),
        )
    cite = _cites(connection)
    decide.merge(
        connection, first=cite["acme_holdings"], second=cite["gamma_inc"], reason="one party"
    )


def test_over_merge_finds_members_whose_neighbourhoods_fall_apart(parties: Path) -> None:
    """Rulings 6-8: acme's neighbours are one community and gamma's another."""
    connection = sqlite3.connect(_store(parties))
    try:
        _two_people_one_name(connection)
        cite = _cites(connection)
        assert review(connection).over_merges is None, "not asked for"
        found = review(connection, over_merge=True)
        assert found.over_merges is not None
        [suspect] = found.over_merges
        assert found.over_merges_total == 1
        assert suspect.apart == (cite["acme_holdings"], cite["gamma_inc"])
        assert suspect.communities == 2
        acme, gamma = suspect.members
        assert (acme.entity, gamma.entity) == suspect.apart
        assert len(acme.communities) == len(gamma.communities) == 1
        assert acme.communities != gamma.communities
        roots = {
            str(c)
            for (c,) in connection.execute(
                "SELECT cite FROM community WHERE state = 0 AND parent IS NULL"
            )
        }
        assert {*acme.communities, *gamma.communities} <= roots
        named = {
            str(b): {str(e) for (e,) in connection.execute(
                "SELECT 'e' || entity_id FROM mention WHERE block_id ="
                " (SELECT block_id FROM block WHERE cite = ?) AND state = 0", (b,)
            )}
            for b in (acme.witness, gamma.witness)
        }  # fmt: skip
        assert cite["acme_holdings"] in named[str(acme.witness)]
        assert cite["gamma_inc"] not in named[str(acme.witness)], "a witness names one member"
        assert found.closures == review(connection).closures, "a fifth list, not a mode"
    finally:
        connection.rollback()
        connection.close()


def _suspect(connection: sqlite3.Connection) -> Any:
    found = review(connection, over_merge=True).over_merges
    assert found is not None
    [suspect] = found
    return suspect


def test_what_reaches_is_live_and_outside_the_closure(parties: Path) -> None:
    """Ruling 6: a child community, a retired root, a dead block's edge and an edge inside the
    closure change nothing."""
    connection = sqlite3.connect(_store(parties))
    try:
        _two_people_one_name(connection, [("acme_holdings", "gamma_inc")])
        before = _suspect(connection)
        ids = _ids(connection)
        for key, level, state in [("beta_corp", 1, 0), ("epsilon_trust", 0, 1)]:
            connection.execute(
                "INSERT INTO community(cite, level, parent, component_ord, cluster_run, size,"
                " member_digest, run_id, trust, state)"
                " SELECT 'c9' || ?, ?, CASE WHEN ? = 1 THEN c.community_id END, c.component_ord,"
                " c.cluster_run, 1, randomblob(16), c.run_id, c.trust, ?"
                " FROM community AS c JOIN community_member AS m USING (community_id)"
                " WHERE m.entity_id = ? AND c.parent IS NULL AND c.state = 0",
                (ids[key], level, level, state, ids[key]),
            )
            connection.execute(
                "INSERT INTO community_member(community_id, entity_id)"
                " VALUES(last_insert_rowid(), ?)",
                (ids[key],),
            )
        [(quiet,)] = connection.execute(
            "SELECT max(block_id) FROM block WHERE block_id NOT IN (SELECT block_id FROM mention)"
        ).fetchall()
        connection.execute(
            "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust)"
            " SELECT ?, ?, 'related_to', ?, MIN(run_id), 2 FROM derive_run",
            (ids["gamma_inc"], ids["beta_corp"], quiet),
        )
        connection.execute("UPDATE block SET state = 1 WHERE block_id = ?", (quiet,))
        assert _suspect(connection) == before
    finally:
        connection.rollback()
        connection.close()


def test_a_member_with_no_neighbours_is_not_evidence(parties: Path) -> None:
    """Ruling 7: iota touches nothing, so acme and iota are not two things by this test."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        for src, dst in TRIANGLES:
            connection.execute(
                "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust)"
                " SELECT ?, ?, 'related_to', MIN(block_id), MIN(run_id), 2 FROM block, derive_run"
                " WHERE block.state = 0",
                (ids[src], ids[dst]),
            )
        cite = _cites(connection)
        decide.merge(connection, first=cite["acme_holdings"], second=cite["iota_works"], reason="x")
        found = review(connection, over_merge=True)
        assert (found.over_merges, found.over_merges_total) == ((), 0)
    finally:
        connection.rollback()
        connection.close()


def test_the_first_witness_by_block_and_the_cut(parties: Path) -> None:
    """Rulings 8 and 5: the lowest block naming acme alone, and a total the cut leaves whole."""
    connection = sqlite3.connect(_store(parties))
    try:
        _two_people_one_name(connection)
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO mention(entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id,"
            " trust, digest) SELECT ?, block_id, segment_id, 0, 1, 'A', run_id, trust,"
            " randomblob(16) FROM mention WHERE entity_id = ? AND state = 0",
            (ids["acme_holdings"], ids["beta_corp"]),
        )
        [(first,)] = connection.execute(
            "SELECT b.cite FROM mention AS m JOIN block AS b USING (block_id)"
            " WHERE m.entity_id = ? AND m.state = 0 AND m.block_id NOT IN"
            " (SELECT block_id FROM mention WHERE entity_id = ? AND state = 0)"
            " ORDER BY m.block_id LIMIT 1",
            (ids["acme_holdings"], ids["gamma_inc"]),
        ).fetchall()
        acme_blocks = connection.execute(
            "SELECT count(DISTINCT block_id) FROM mention WHERE entity_id = ? AND state = 0",
            (ids["acme_holdings"],),
        ).fetchone()
        assert acme_blocks[0] >= 2
        assert _suspect(connection).members[0].witness == first
        cut = review(connection, over_merge=True, limit=0)
        assert (cut.over_merges, cut.over_merges_total) == ((), 1)
    finally:
        connection.rollback()
        connection.close()


def test_a_member_reaching_both_sides_is_a_hub_not_two_things(parties: Path) -> None:
    """Ruling 7: gamma also touches beta, so its reach meets acme's."""
    connection = sqlite3.connect(_store(parties))
    try:
        _two_people_one_name(connection, [("gamma_inc", "beta_corp")])
        found = review(connection, over_merge=True)
        assert (found.over_merges, found.over_merges_total) == ((), 0)
    finally:
        connection.rollback()
        connection.close()


def test_a_witness_names_no_other_member(parties: Path) -> None:
    """Ruling 8: once every block naming gamma also names acme, gamma has no witness."""
    connection = sqlite3.connect(_store(parties))
    try:
        _two_people_one_name(connection)
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO mention(entity_id, block_id, segment_id, ts_a, ts_b, surface, run_id,"
            " trust, digest) SELECT ?, block_id, segment_id, 0, 1, 'A', run_id, trust,"
            " randomblob(16)"
            " FROM mention WHERE entity_id = ? AND state = 0",
            (ids["acme_holdings"], ids["gamma_inc"]),
        )
        suspects = review(connection, over_merge=True).over_merges
        assert suspects is not None
        [suspect] = suspects
        assert [m.witness is None for m in suspect.members] == [False, True]
        document = review_document(review(connection, over_merge=True), corpus="h", qualify=False)
        assert document["over_merges"][0]["split"] is None
    finally:
        connection.rollback()
        connection.close()


def test_the_suggested_split_runs(tmp_path: Path) -> None:
    """The text's `try:` line is a command `ow graph split` takes, and it parts the two."""
    project = _ingested(tmp_path)
    connection = sqlite3.connect(_store(project))
    try:
        _two_people_one_name(connection)
        connection.commit()
        cite = _cites(connection)
    finally:
        connection.close()
    code, out, err = _verb(["review", "--over-merge", "--render", "json"], project)
    assert (code, err) == (0, ""), err
    split = json.loads(out)["over_merges"][0]["split"]
    assert split.startswith(f"ow graph split {cite['acme_holdings']} --into d")
    code, out, err = _verb(["review", "--over-merge"], project)
    assert (code, err) == (0, ""), err
    assert f"      try: {split}" in out.splitlines()
    argv = shlex.split(split.replace('"..."', '"two parties"'))[2:]
    code, _out, err = _verb(argv, project)
    assert (code, err) == (0, ""), err
    connection = sqlite3.connect(_store(project))
    try:
        heads = dict(connection.execute("SELECT key, canonical_id FROM entity"))
        assert heads["acme_holdings"] != heads["gamma_inc"]
    finally:
        connection.close()


def test_the_action_reads_and_has_no_tool() -> None:
    spec = ACTIONS["graph.review"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        True,
        False,
        True,
    )
