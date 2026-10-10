"""`op.cluster` (D690): Louvain over a CSR, the community tree, and its reconciliation."""

from __future__ import annotations

import hashlib
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from itertools import combinations
from pathlib import Path

import pytest
from omniweave.graph import cluster as module
from omniweave.graph import louvain
from omniweave.graph.cluster import cluster, plan
from omniweave.graph.louvain import Community, communities, csr, normalise
from omniweave_core.canonical import ow128
from omniweave_core.errors import GraphError
from omniweave_core.model.enums import Trust
from omniweave_core.store.projection import canonical_projection
from test_run_parse import _project, _rows, _run


def clique(nodes: range | list[int]) -> list[tuple[int, int, float]]:
    return [(a, b, 1.0) for a, b in combinations(nodes, 2)]


def tree(edges: list[tuple[int, int, float]]) -> list[Community]:
    n = max(max(a, b) for a, b, _ in edges) + 1
    return communities(csr(n, normalise(edges)))


def shape(found: list[Community]) -> list[tuple[int, int | None, tuple[int, ...], str]]:
    return [(c.level, c.parent, c.members, c.split) for c in found]


BRIDGED = clique(range(5)) + clique(range(5, 10)) + [(4, 5, 1.0)]

PAIRED: list[tuple[int, int, float]] = []
for _group in range(4):  # two 5-cliques tied by four edges, four such pairs in a ring
    _base = _group * 10
    PAIRED += clique(range(_base, _base + 5)) + clique(range(_base + 5, _base + 10))
    PAIRED += [(_base + j, _base + 5 + j, 1.0) for j in range(4)]
    PAIRED.append((_base + 9, (_base + 10) % 40, 1.0))

SEARCHED = [  # found by search: one 6-member leaf of cohesion 0.4 that Louvain over itself divides
    (0, 6, 1.0), (0, 12, 1.0), (1, 9, 1.0), (1, 12, 1.0), (2, 7, 1.0), (2, 8, 1.0), (2, 10, 1.0),
    (3, 4, 1.0), (3, 5, 1.0), (3, 6, 1.0), (3, 9, 1.0), (3, 14, 1.0), (4, 6, 1.0), (4, 7, 1.0),
    (4, 11, 1.0), (5, 6, 1.0), (5, 7, 1.0), (5, 11, 1.0), (5, 12, 1.0), (5, 14, 1.0), (6, 14, 1.0),
    (7, 10, 1.0), (7, 11, 1.0), (7, 13, 1.0), (8, 12, 1.0), (9, 14, 1.0), (10, 12, 1.0),
    (11, 13, 1.0),
]  # fmt: skip

STAR = [(0, leaf, 1.0) for leaf in range(1, 13)]


# ---------------------------------------------------------------------------------------------
# the arithmetic
# ---------------------------------------------------------------------------------------------


def test_two_cliques_and_a_bridge_are_two_roots() -> None:
    assert shape(tree(BRIDGED)) == [
        (0, None, (0, 1, 2, 3, 4), ""),
        (0, None, (5, 6, 7, 8, 9), ""),
    ]
    assert all(c.cohesion == 1.0 for c in tree(BRIDGED))


def test_the_dendrogram_is_read_from_the_top_and_a_parent_comes_first() -> None:
    """Ruling 3: pass 1 finds the eight cliques, pass 2 pairs them; the pairs are the roots."""
    found = tree(PAIRED)
    roots = [c for c in found if c.parent is None]
    assert [c.members for c in roots] == [tuple(range(b, b + 10)) for b in (0, 10, 20, 30)]
    assert all(c.level == 0 for c in roots)
    for index, community in enumerate(found):
        if community.parent is None:
            continue
        parent = found[community.parent]
        assert community.parent < index, "parents first"
        assert community.level == parent.level + 1
        assert set(community.members) < set(parent.members), "never a copy of its parent"
    children = [c.members for c in found if c.parent == 0]
    assert children == [(0, 1, 2, 3, 4), (5, 6, 7, 8, 9)]


def test_a_set_the_next_pass_left_alone_is_written_once() -> None:
    """`PAIRED` with a fifth clique on the ring, too weakly tied to pair: pass 2 leaves it alone,
    so it is one community at both levels -- a root with no child, not a root and its copy."""
    ring = [edge for edge in PAIRED if edge != (39, 0, 1.0)]
    edges = [*ring, *clique(range(40, 45)), (39, 40, 1.0), (44, 0, 1.0)]
    levels = louvain.louvain(csr(45, normalise(edges)))
    assert [max(level) + 1 for level in levels] == [9, 5]
    found = tree(edges)
    assert shape(found)[-1] == (0, None, (40, 41, 42, 43, 44), "")
    assert len(found) == 13
    assert len({c.members for c in found}) == len(found)


def test_sixty_triangles_are_three_levels_and_no_community_copies_its_parent() -> None:
    """The resolution limit stacks a ring of triangles three passes deep; sets a pass leaves
    alone, at one level or two, collapse into one row."""
    ring: list[tuple[int, int, float]] = []
    for k in range(60):
        ring += clique(range(3 * k, 3 * k + 3))
        ring.append((3 * k + 2, (3 * k + 3) % 180, 1.0))
    levels = louvain.louvain(csr(180, normalise(ring)))
    assert [max(level) + 1 for level in levels] == [60, 26, 14]
    found = tree(ring)
    assert len(found) == 98
    for community in found:
        if community.parent is not None:
            parent = found[community.parent]
            assert community.level == parent.level + 1
            assert set(community.members) < set(parent.members)
    assert {c.level for c in found} == {0, 1, 2}


def test_a_set_left_alone_by_every_pass_is_one_root_with_no_child() -> None:
    """A 5-clique tied to the triangle ring by one edge is alone at all three levels: the chain
    collapses through two levels, not one."""
    ring: list[tuple[int, int, float]] = []
    for k in range(60):
        ring += clique(range(3 * k, 3 * k + 3))
        ring.append((3 * k + 2, (3 * k + 3) % 180, 1.0))
    edges = [*ring, *clique(range(180, 185)), (0, 180, 1.0)]
    assert len(louvain.louvain(csr(185, normalise(edges)))) == 3
    found = tree(edges)
    [lone] = [c for c in found if 180 in c.members]
    assert (lone.level, lone.parent, lone.members) == (0, None, tuple(range(180, 185)))


def test_the_seed_orders_the_sweep() -> None:
    """Ruling 1: a 10-cycle has no best cut, and the seeded sweep order picks this one."""
    cycle = [(i, (i + 1) % 10, 1.0) for i in range(10)]
    assert [c.members for c in tree(cycle) if c.parent is None] == [
        (0, 1, 9),
        (2, 3),
        (4, 5, 6),
        (7, 8),
    ]


def test_components_are_clustered_apart_in_order_of_their_smallest_node() -> None:
    edges = [(a + 3, b + 3, w) for a, b, w in BRIDGED] + [(0, 1, 1.0), (1, 2, 1.0)]
    found = tree(edges)
    assert [(c.component, c.members[0]) for c in found] == [(0, 0), (1, 3), (1, 8)]


def test_normalise_folds_the_direction_drops_a_loop_and_keeps_the_last() -> None:
    rows = [(2, 1, 1.0), (3, 3, 9.0), (1, 2, 4.0), (0, 2, 1.0)]
    assert normalise(rows) == [(0, 2, 1.0), (1, 2, 4.0)]


def _order(draw: int, row: tuple[int, int, float]) -> bytes:
    return hashlib.blake2b(f"{draw}:{row}".encode(), digest_size=8).digest()


def test_the_partition_is_a_function_of_the_graph_not_its_row_order() -> None:
    """GR18: the rows shuffled and their directions flipped 100 times give one tree."""
    expected = shape(tree(PAIRED))
    for draw in range(100):
        rows = sorted(PAIRED, key=lambda r: _order(draw, r))
        flipped = [(b, a, w) if _order(-draw, (a, b, w))[0] & 1 else (a, b, w) for a, b, w in rows]
        assert shape(tree(flipped)) == expected, draw


def test_cohesion_is_internal_edges_over_the_most_there_could_be() -> None:
    graph = csr(10, normalise(BRIDGED))
    assert louvain.cohesion(graph, [4, 5]) == 1.0
    assert louvain.cohesion(graph, [0, 9]) == 0.0
    assert louvain.cohesion(graph, [3, 4, 5, 6]) == 3 / 6
    assert louvain.cohesion(graph, [7]) == 1.0


def test_a_sparse_leaf_is_re_split_for_cohesion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 4, graphify's second pass, with its thresholds lowered to this graph's scale."""
    assert all(not c.split for c in tree(SEARCHED)), "at 50 members the default never fires"
    monkeypatch.setattr(louvain, "COHESION_SPLIT_MIN", 6)
    monkeypatch.setattr(louvain, "COHESION_SPLIT", 0.5)
    assert shape(tree(STAR)) == [(0, None, tuple(range(13)), "")], (
        "a star Louvain cannot divide is left whole: only the size cap cuts"
    )
    found = tree(SEARCHED)
    assert shape(found)[:3] == [
        (0, None, (0, 1, 2, 8, 10, 12), "cohesion"),
        (1, 0, (0, 1, 12), ""),
        (1, 0, (2, 8, 10), ""),
    ]
    assert found[0].cohesion == 0.4


def test_a_leaf_above_the_cap_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(louvain, "MAX_COMMUNITY_SIZE", 5)
    found = tree(SEARCHED)
    assert shape(found)[:3] == [
        (0, None, (0, 1, 2, 8, 10, 12), "size"),
        (1, 0, (0, 1, 12), ""),
        (1, 0, (2, 8, 10), ""),
    ]
    assert all(len(c.members) <= 5 for c in found if not c.split)


def test_a_leaf_above_the_cap_louvain_cannot_divide_is_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 5: a star has no community structure; above the cap it is cut breadth-first."""
    assert shape(tree(STAR)) == [(0, None, tuple(range(13)), "")]
    monkeypatch.setattr(louvain, "MAX_COMMUNITY_SIZE", 5)
    assert shape(tree(STAR)) == [
        (0, None, tuple(range(13)), "cut"),
        (1, 0, (0, 1, 2, 3, 4), ""),
        (1, 0, (5, 6, 7, 8), ""),
        (1, 0, (9, 10, 11, 12), ""),
    ]


# ---------------------------------------------------------------------------------------------
# `plan()`: the store's terms around the arithmetic
# ---------------------------------------------------------------------------------------------

KEYS = ["acme", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]


def _planned(ids: list[int]) -> list[tuple[bytes, int, int | None, tuple[int, ...]]]:
    """`BRIDGED` over the ten keys, whose entities carry the ids `ids` (key order)."""
    identities = {e: ("corpus", "org", k) for e, k in zip(ids, KEYS, strict=True)}
    rows = [(ids[a], ids[b], w, ("related_to",), int(Trust.INFERRED), 0) for a, b, w in BRIDGED]
    tree_, nodes, edges = plan(identities, {}, rows)
    assert (nodes, edges) == (10, 21)
    return [(p.digest, p.level, p.parent, p.members) for p in tree_]


def test_two_stores_numbering_one_graph_differently_agree_on_every_digest() -> None:
    """Rulings 9 and 10: ids order nothing and are not digested, so GR8 can compare digests."""
    first = _planned(list(range(1, 11)))
    second = _planned([97, 3, 55, 12, 8, 41, 2, 70, 19, 64])
    assert [d for d, *_ in first] == [d for d, *_ in second]
    assert first[0][0] == ow128(b"ow.community.1", [["corpus", "org", k] for k in sorted(KEYS[:5])])


def test_above_max_cluster_edges_is_a_refusal_naming_the_cap_and_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "MAX_CLUSTER_EDGES", 20)
    with pytest.raises(GraphError) as raised:
        _planned(list(range(1, 11)))
    assert raised.value.code() == "OW_GRAPH_TOO_LARGE"
    assert raised.value.numeric() == "OW-G-001"
    assert "MAX_CLUSTER_EDGES = 20" in str(raised.value)
    assert "omniweave-driver-leiden" in str(raised.value)


def test_at_max_cluster_edges_is_no_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MAX_CLUSTER_EDGES", 21)
    assert len(_planned(list(range(1, 11)))) == 2


def test_the_last_duplicate_is_the_last_in_natural_order_not_in_row_order() -> None:
    """Ruling 11: `x` is tied to the `a` clique by two rows; the natural last weighs 0.1, so `x`
    joins the `b` clique it is tied to at 1.0. The rows arrive with the 5.0 one last."""
    keys = ["a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4", "x"]
    identities = {e: ("corpus", "org", k) for e, k in enumerate(keys)}
    rows = [(a, b, 1.0, ("r",), 1, 0) for a, b, _w in clique(range(4)) + clique(range(4, 8))]
    rows += [(8, 0, 0.1, ("z",), 1, 0), (8, 0, 5.0, ("y",), 1, 0), (8, 4, 1.0, ("r",), 1, 0)]
    found, _nodes, _edges = plan(identities, {}, rows)
    assert [p.members for p in found] == [(0, 1, 2, 3), (4, 5, 6, 7, 8)]


def test_an_id_is_matched_within_its_level() -> None:
    """Ruling 12: a root whose members moved does not take a stale leaf's id."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE community(community_id INTEGER PRIMARY KEY, state INT)")
        connection.execute("CREATE TABLE community_member(community_id INT, entity_id INT)")
        old = {1: (0, {1, 2, 3, 4}), 2: (1, {1, 2}), 3: (1, {3, 4})}
        for community_id, (_level, members) in old.items():
            connection.execute("INSERT INTO community VALUES(?, 0)", (community_id,))
            connection.executemany(
                "INSERT INTO community_member VALUES(?, ?)",
                [(community_id, m) for m in members],
            )
        stored = {
            cid: module._Row(
                digest=bytes([cid]),
                level=level,
                parent=None,
                component=0,
                size=len(members),
                cohesion=1.0,
                trust=1,
                taint=0,
                state=0,
            )
            for cid, (level, members) in old.items()
        }

        def planned(members: tuple[int, ...]) -> module.Planned:
            return module.Planned(
                members=members, digest=bytes(members), level=0, parent=None, component=0,
                size=len(members), cohesion=1.0, trust=1, taint=0, split="",
            )  # fmt: skip

        ids = module._match(connection, [planned((1, 2, 3)), planned((4, 5))], stored)
        assert ids == [1, 4], "the second root is new: leaf 3 is a level below"
    finally:
        connection.close()


def test_trust_is_the_weakest_internal_edge_at_most_inferred_and_taint_ors_upward() -> None:
    identities = {e: ("corpus", "org", KEYS[e]) for e in range(4)}
    rows = [
        (0, 1, 1.0, ("a",), int(Trust.EXTRACTED), 0),
        (1, 0, 1.0, ("b",), int(Trust.AMBIGUOUS), 4),
        (2, 3, 1.0, ("a",), int(Trust.EXTRACTED), 0),
    ]
    found, _nodes, _edges = plan(identities, {3: 2}, rows)
    assert [(p.members, p.trust, p.taint) for p in found] == [
        ((0, 1), int(Trust.AMBIGUOUS), 4),
        ((3, 2), int(Trust.INFERRED), 2),
    ]


# ---------------------------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------------------------

PARTIES = (
    "Party,Role\nAcme Holdings,Seller\nBeta Corp,Buyer\nGamma Inc,Agent\nDelta Partners,Lender\n"
    "Epsilon Trust,Trustee\nZeta Group,Guarantor\nEta Systems,Vendor\nTheta Labs,Licensor\n"
    "Iota Works,Contractor\nKappa Foods,Supplier\n"
)
LEFT = ["acme_holdings", "beta_corp", "gamma_inc", "delta_partners"]
RIGHT = ["epsilon_trust", "zeta_group", "eta_systems", "theta_labs"]
APART = ["iota_works", "kappa_foods"]


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("cluster")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert report.clustered is not None
    assert (report.clustered.entities, report.clustered.communities) == (0, 0)
    assert not report.clustered.shown, "no edge, no community, no line"
    return store


def _ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {str(k): int(e) for e, k in connection.execute("SELECT entity_id, key FROM entity")}


def _edge(
    connection: sqlite3.Connection,
    left: str,
    right: str,
    *,
    relation: str = "related_to",
    trust: int = 1,
    last: bool = False,
) -> None:
    """An edge observed in the first live block, or with `last` the last."""
    ids = _ids(connection)
    connection.execute(
        "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust)"
        " SELECT ?, ?, ?, (SELECT CASE WHEN ? THEN MAX(block_id) ELSE MIN(block_id) END"
        " FROM block WHERE state = 0), run_id, ? FROM derive_run"
        " WHERE pass_id = 'derive.entity.table' LIMIT 1",
        (ids[left], ids[right], relation, last, trust),
    )


def _graph(connection: sqlite3.Connection) -> None:
    """Two 4-cliques tied by one edge, and a pair apart observed in another block."""
    for group in (LEFT, RIGHT):
        for a, b in combinations(group, 2):
            _edge(connection, a, b)
    _edge(connection, LEFT[-1], RIGHT[0])
    _edge(connection, APART[0], APART[1], last=True)


def _of(connection: sqlite3.Connection, sql: str, *args: object) -> list[tuple[object, ...]]:
    return [tuple(row) for row in connection.execute(sql, args).fetchall()]


def _members(connection: sqlite3.Connection) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for community_id, key in connection.execute(
        "SELECT m.community_id, e.key FROM community_member m JOIN entity e USING (entity_id)"
        " JOIN community c USING (community_id) WHERE c.state = 0 ORDER BY 1, 2"
    ):
        out.setdefault(int(community_id), []).append(str(key))
    return out


def test_a_graph_is_three_communities_with_members_reports_and_one_run(parties: Path) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        report = cluster(connection, gen=90)
        assert (report.entities, report.edges, report.components, report.communities) == (
            10,
            14,
            2,
            3,
        )
        assert (report.levels, report.added, report.changed, report.retired) == (1, 3, 0, 0)
        assert report.shown and "3 communities over 10 entities" in report.line()
        assert sorted(_members(connection).values()) == sorted(
            [sorted(LEFT), sorted(RIGHT), sorted(APART)]
        )
        rows = _of(
            connection,
            "SELECT cite = 'c' || community_id, level, parent, size, cohesion, trust, taint, state,"
            " cluster_run FROM community ORDER BY community_id",
        )
        assert rows == [
            (1, 0, None, 4, 1.0, int(Trust.INFERRED), 0, 0, 1),
            (1, 0, None, 4, 1.0, int(Trust.INFERRED), 0, 0, 1),
            (1, 0, None, 2, 1.0, int(Trust.INFERRED), 0, 0, 1),
        ]
        assert _of(connection, "SELECT component_ord FROM community ORDER BY 1") == [
            (0,),
            (0,),
            (1,),
        ]
        assert _of(connection, "SELECT DISTINCT report_state FROM community_report") == [
            ("absent",)
        ]
        assert _of(
            connection,
            "SELECT at_gen, status, n_items, cost_class, segment_id FROM derive_run"
            " WHERE pass_id = 'op.cluster'",
        ) == [(90, "ok", 3, "local_compute", None)]
        assert _of(
            connection,
            "SELECT port, cost_class, cost_rank, phase, lanes, granularity FROM derive_pass"
            " WHERE pass_id = 'op.cluster'",
        ) == [("op", "local_compute", 1, 10, '["community"]', "corpus")]
        digests = sorted(
            ow128(b"ow.community.1", [["corpus", "org", k] for k in sorted(group)]).hex()
            for group in (LEFT, RIGHT, APART)
        )
        assert list(canonical_projection(connection).communities) == digests
    finally:
        connection.rollback()
        connection.close()


def test_an_unchanged_graph_writes_nothing(parties: Path) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        cluster(connection, gen=90)
        before = connection.total_changes
        again = cluster(connection, gen=91)
        assert (again.added, again.changed, again.retired, again.communities) == (0, 0, 0, 3)
        assert connection.total_changes == before
        assert _of(connection, "SELECT count(*) FROM derive_run WHERE at_gen = 91") == [(0,)]
    finally:
        connection.rollback()
        connection.close()


def _live_ids(connection: sqlite3.Connection, sql: str) -> list[int]:
    return sorted(int(row[0]) for row in connection.execute(sql).fetchall())


def _fresh_reports(connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE community_report SET report_state = 'fresh', written_at_ns = 1, member_digest ="
        " (SELECT member_digest FROM community c WHERE c.community_id ="
        " community_report.community_id)"
    )


def test_a_member_that_moves_keeps_both_ids_and_stales_both_reports(parties: Path) -> None:
    """Ruling 12: matched by overlap, the digests move, and 06:2002's UPDATE fires."""
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        cluster(connection, gen=90)
        ids = {tuple(v): k for k, v in _members(connection).items()}
        _fresh_reports(connection)
        assert _of(connection, "SELECT count(*) FROM community_report_fresh") == [(3,)]
        moved = LEFT[-1]
        connection.execute(
            "DELETE FROM edge WHERE src_entity = ? OR dst_entity = ?",
            (_ids(connection)[moved], _ids(connection)[moved]),
        )
        for other in RIGHT:
            _edge(connection, moved, other)
        report = cluster(connection, gen=91)
        assert (report.added, report.changed, report.retired, report.stale) == (0, 3, 0, 2), (
            "the pair apart only renumbers its component: changed, and its report still fresh"
        )
        after = _members(connection)
        assert after[ids[tuple(sorted(LEFT))]] == sorted(LEFT[:-1])
        assert after[ids[tuple(sorted(RIGHT))]] == sorted([*RIGHT, moved])
        assert _of(connection, "SELECT count(*) FROM community_report_fresh") == [(1,)]
        assert _of(
            connection,
            "SELECT component_ord FROM community WHERE community_id = ?",
            ids[tuple(sorted(APART))],
        ) == [(2,)], "delta's edges went with it: the left three are a component of their own"
        history = _of(
            connection,
            "SELECT row_id, superseded_by, reason, json_extract(payload, '$.size')"
            " FROM graph_history WHERE kind = 'community' ORDER BY 1",
        )
        assert history == [
            (ids[tuple(sorted(LEFT))], ids[tuple(sorted(LEFT))], "pass_replaced", 4),
            (ids[tuple(sorted(RIGHT))], ids[tuple(sorted(RIGHT))], "pass_replaced", 4),
        ]
        assert _of(connection, "SELECT DISTINCT cluster_run FROM community") == [(2,)], (
            "all three were written again, by the second clustering run"
        )
    finally:
        connection.rollback()
        connection.close()


def test_a_graph_that_goes_retires_every_community_and_a_return_revives_them(
    parties: Path,
) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        cluster(connection, gen=90)
        ids = _live_ids(connection, "SELECT community_id FROM community")
        _fresh_reports(connection)
        connection.execute("DELETE FROM edge")
        gone = cluster(connection, gen=91)
        assert (gone.communities, gone.retired, gone.stale) == (0, 3, 3)
        assert _of(connection, "SELECT DISTINCT state FROM community") == [(module.RETIRED,)]
        assert _of(connection, "SELECT count(*) FROM community_report_fresh") == [(0,)]
        assert canonical_projection(connection).communities == ()
        assert _of(connection, "SELECT count(*) FROM derive_run WHERE at_gen = 91") == [(0,)]
        assert _of(
            connection, "SELECT count(*) FROM graph_history WHERE superseded_by IS NULL"
        ) == [(3,)]
        _graph(connection)
        back = cluster(connection, gen=92)
        assert (back.added, back.changed, back.communities) == (0, 3, 3)
        assert _live_ids(connection, "SELECT community_id FROM community WHERE state = 0") == ids
    finally:
        connection.rollback()
        connection.close()


def test_a_merge_folds_its_members_edges_onto_the_survivor(parties: Path) -> None:
    """Ruling 8: beta's edges become acme's, and acme-beta becomes a loop and drops; iota's one
    edge becomes acme-kappa, so kappa joins acme's side rather than leaving with iota."""
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        ids = _ids(connection)
        connection.executemany(
            "UPDATE entity SET canonical_id = ? WHERE entity_id = ?",
            [(ids["acme_holdings"], ids["beta_corp"]), (ids["acme_holdings"], ids["iota_works"])],
        )
        report = cluster(connection, gen=90)
        assert (report.entities, report.edges, report.components) == (8, 11, 1), (
            "a loop and two duplicates drop, and kappa's edge now reaches acme"
        )
        [left] = [m for m in _members(connection).values() if "acme_holdings" in m]
        assert left == sorted(["acme_holdings", "delta_partners", "gamma_inc", "kappa_foods"])
    finally:
        connection.rollback()
        connection.close()


def test_an_edge_observed_in_a_retired_block_is_not_clustered(parties: Path) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        connection.execute(
            "UPDATE block SET state = 1 WHERE block_id = (SELECT MAX(block_id) FROM block"
            " WHERE state = 0)"
        )
        report = cluster(connection, gen=90)
        assert (report.entities, report.components, report.communities) == (8, 1, 2)
        assert APART[0] not in [k for v in _members(connection).values() for k in v]
    finally:
        connection.rollback()
        connection.close()


def test_an_overloaded_or_retired_entity_takes_no_part(parties: Path) -> None:
    connection = sqlite3.connect(parties)
    try:
        _graph(connection)
        connection.execute("UPDATE entity SET state = 1 WHERE key = ?", (APART[0],))
        connection.execute("UPDATE entity SET state = 2 WHERE key = ?", (LEFT[0],))
        report = cluster(connection, gen=90)
        assert (report.entities, report.communities) == (7, 2)
    finally:
        connection.rollback()
        connection.close()


def test_ingest_clusters_after_resolve_and_says_so(tmp_path: Path) -> None:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    first = _run(tmp_path, store, config)
    assert first.clustered is not None and not first.clustered.shown
    connection = sqlite3.connect(store)
    try:
        _graph(connection)
        connection.commit()
    finally:
        connection.close()
    second = _run(tmp_path, store, config)
    assert second.clustered is not None
    assert (second.clustered.communities, second.clustered.added) == (3, 3)
    assert any(line.startswith("  cluster   3 communities") for line in second.lines())
    third = _run(tmp_path, store, config)
    assert third.clustered is not None
    assert (third.clustered.added, third.clustered.changed, third.clustered.retired) == (0, 0, 0)
    assert _rows(store, "SELECT count(*) FROM derive_run WHERE pass_id = 'op.cluster'") == [(1,)]
