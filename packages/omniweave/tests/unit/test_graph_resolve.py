"""`op.resolve`: the exact stage, the closure, and the log they write. **D684.**"""

from __future__ import annotations

import hashlib
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path

import pytest
from omniweave.graph import resolve as module
from omniweave.graph.resolve import (
    Node,
    Pair,
    TypeGate,
    closure,
    funnel,
    resolve,
    total_order,
)
from omniweave_core.errors import ResourceLimit
from omniweave_core.model.enums import Method, Trust
from omniweave_core.store.verify import VerifyClause, verify_store
from test_run_parse import _project, _rows, _run

GATE = TypeGate(
    resolution={"org": "fuzzy", "product": "fuzzy", "unknown": "none", "group": "fuzzy"},
    compatible={"org": frozenset({"group"}), "group": frozenset({"org"})},
)


def node(entity_id: int, key: str, *aliases: str, etype: str = "org", scope: int = 0) -> Node:
    return Node(entity_id, scope, etype, key, frozenset({key, *aliases}))


def pairs(found: list[Pair]) -> list[tuple[int, int, str]]:
    return sorted((p.a, p.b, p.stage) for p in found)


# ---------------------------------------------------------------------------------------------
# stages [1] and [2]
# ---------------------------------------------------------------------------------------------


def test_two_entities_sharing_a_name_are_one_exact_pair() -> None:
    found = funnel([node(1, "acme_holdings_ltd"), node(2, "acme", "acme_holdings_ltd")], GATE)
    assert pairs(found) == [(2, 1, "exact")], "a is first in identity order: `acme` < `acme_h...`"
    [pair] = found
    assert (pair.trust, pair.method, pair.score, pair.score_kind) == (
        Trust.EXTRACTED,
        Method.HEURISTIC,
        None,
        None,
    )


def test_a_name_in_two_scopes_is_no_pair() -> None:
    """Two documents' `the Company` (06:1829): the grouping is by scope, so they never meet."""
    assert funnel([node(1, "company", scope=7), node(2, "company", scope=9)], GATE) == []


@pytest.mark.parametrize(
    ("left", "right", "merges"),
    [
        ("org", "org", True),
        ("org", "group", True),
        ("org", "product", False),
        ("unknown", "unknown", False),
    ],
    ids=["same", "compatible_both_ways", "incompatible", "resolution_none"],
)
def test_the_type_gate(left: str, right: str, merges: bool) -> None:
    found = funnel([node(1, "atlas", etype=left), node(2, "atlas", etype=right)], GATE)
    assert bool(found) is merges


def test_compatibility_must_be_declared_both_ways() -> None:
    gate = TypeGate(
        resolution={"org": "fuzzy", "group": "fuzzy"}, compatible={"org": frozenset({"group"})}
    )
    assert not gate.admits("org", "group")


def test_a_group_of_n_is_n_minus_one_pairs_each_to_its_first_admissible_member() -> None:
    """Ruling 3: linear, connected, deterministic."""
    members = [
        node(i, f"k{i}", "atlas", etype=e)
        for i, e in enumerate(["org", "product", "org", "product", "org"], 1)
    ]
    assert pairs(funnel(members, GATE)) == [
        (1, 3, "exact"),
        (1, 5, "exact"),
        (2, 4, "exact"),
    ], "products pair with the first product, orgs with the first org"


def test_past_the_cap_is_a_refusal_not_a_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MAX_CANDIDATE_PAIRS", 1)
    with pytest.raises(ResourceLimit, match="candidate pairs"):
        funnel([node(1, "a1", "x"), node(2, "a2", "x"), node(3, "a3", "x")], GATE)


# ---------------------------------------------------------------------------------------------
# stage [9]: the closure
# ---------------------------------------------------------------------------------------------

NODES = [node(1, "delta"), node(2, "alpha"), node(3, "charlie"), node(4, "bravo"), node(5, "echo")]


def exact(a: int, b: int) -> Pair:
    return Pair(a=a, b=b, stage="exact", trust=Trust.EXTRACTED, method=Method.HEURISTIC)


def test_the_survivor_is_the_root_of_the_forest_the_total_order_builds() -> None:
    """06:1755. Pairs sorted `(min(identity), max(identity))`: (alpha, charlie) puts charlie under
    alpha, (bravo, delta) delta under bravo, (charlie, delta) bravo's root under alpha's."""
    found = closure(NODES, [exact(1, 3), exact(4, 1), exact(3, 2)])
    assert found.canonical == {1: 2, 2: 2, 3: 2, 4: 2, 5: 5}
    assert found.hops == {1: 2, 2: 0, 3: 1, 4: 1, 5: 0}
    assert [(p.a, p.b) for p in found.kept] == [(3, 2), (4, 1), (1, 3)]


def test_merge_hops_decides_before_the_alias_count() -> None:
    """06:1752's order: `merge_hops` first. `bravo` carries three names and `alpha` one, and alpha
    is the root, so alpha survives."""
    nodes = [node(1, "alpha"), node(2, "bravo", "b2", "b3")]
    assert closure(nodes, [exact(1, 2)]).canonical == {1: 1, 2: 1}


def test_a_better_scored_pair_is_unioned_first() -> None:
    """06:1735: an exact pair's NULL score is 100.0 and sorts before a fuzzy 95."""
    fuzzy = Pair(a=4, b=5, stage="lsh_jw", trust=Trust.INFERRED, method=Method.HEURISTIC,
                 score=95.0, score_kind="jaro_winkler")  # fmt: skip
    ordered = total_order([fuzzy, exact(1, 3)], {n.entity_id: n for n in NODES})
    assert [p.stage for p in ordered] == ["exact", "lsh_jw"]


def _shuffled(draw: int, item: int) -> bytes:
    """A permutation per draw: `random` is banned here, and blake2b is how this repo samples."""
    return hashlib.blake2b(f"{draw}:{item}".encode(), digest_size=8).digest()


def test_the_closure_is_a_function_of_the_pair_set_not_its_order() -> None:
    """GR6 (06:1877): 100 shuffles of the nodes and of the pairs, one answer."""
    links = [exact(1, 3), exact(4, 1), exact(3, 2), exact(5, 4)]
    want = closure(NODES, links)
    for draw in range(100):
        nodes = sorted(NODES, key=lambda n: _shuffled(draw, n.entity_id))
        shuffled = sorted(links, key=lambda p: _shuffled(draw, p.a * 100 + p.b))
        got = closure(nodes, shuffled)
        assert (got.canonical, got.hops, got.kept) == (want.canonical, want.hops, want.kept)


def test_a_user_split_blocks_the_pass_and_the_blocked_pair_is_not_kept() -> None:
    """Ruling 5: `polarity = -1` is a blocking pair, and the pass's row would contradict it."""
    found = closure(NODES, [exact(2, 3), exact(3, 1)], user_splits=[(2, 1)])
    assert found.canonical[1] != found.canonical[2]
    assert [(p.a, p.b) for p in found.blocked] == [(3, 1)]
    assert found.canonical[3] == found.canonical[2], "the pair the split does not touch stands"


def test_a_user_merge_is_applied_after_the_pass() -> None:
    user = Pair(a=5, b=2, stage="user", trust=Trust.EXTRACTED, method=Method.USER)
    found = closure(NODES, [exact(1, 3)], user_merges=[user])
    assert found.canonical[5] == found.canonical[2]
    assert found.kept == (exact(1, 3),), "a user row is the user's, never re-kept by the pass"


# ---------------------------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------------------------

PARTIES = "Party,Role\nAcme Holdings Ltd,Seller\nBeta Corp,Buyer\nGamma Inc,Agent\n"


@pytest.fixture(scope="module")
def ingested(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("resolve")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert report.resolved is not None
    assert (report.resolved.entities, report.resolved.kept) == (3, 0)
    assert not report.resolved.shown, "nothing to say: no line"
    return store


def _ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {str(k): int(e) for e, k in connection.execute("SELECT entity_id, key FROM entity")}


def _closure_ok(connection: sqlite3.Connection) -> None:
    report = verify_store(connection, now_ns=0, clauses={VerifyClause.GRAPH_CLOSURE})
    [clause] = report.clauses
    assert clause.findings == (), clause.findings


def test_a_shared_alias_merges_and_the_log_converges(ingested: Path) -> None:
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings_ltd', 'Acme Holdings Ltd', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        first = resolve(connection, gen=90)
        assert (first.kept, first.added, first.retired, first.clusters, first.merged) == (
            1,
            1,
            0,
            1,
            1,
        )
        assert first.shown and "1 cluster(s) holding 1 merged" in first.line()
        heads = sorted(str(k) for (k,) in connection.execute("SELECT key FROM ow_entity_head"))
        assert heads == ["acme_holdings_ltd", "beta_corp"], "acme sorts first: it survives"
        assert _rows_of(connection, "SELECT key, canonical_id, resolution_trust FROM entity") == [
            ("acme_holdings_ltd", ids["acme_holdings_ltd"], int(Trust.EXTRACTED)),
            ("beta_corp", ids["beta_corp"], int(Trust.AMBIGUOUS)),
            ("gamma_inc", ids["acme_holdings_ltd"], int(Trust.EXTRACTED)),
        ]
        [(stage, trust, guards, run_pass, gen)] = _rows_of(
            connection,
            "SELECT m.stage, m.trust, m.guards, r.pass_id, m.decided_at_gen FROM entity_merge m"
            " JOIN derive_run r ON r.run_id = m.run_id",
        )
        assert (stage, trust, guards, run_pass, gen) == (
            "exact", 2, '["scoped_label_crossdoc"]', "op.resolve", 90,
        )  # fmt: skip
        _closure_ok(connection)

        again = resolve(connection, gen=91)
        assert (again.added, again.retired, again.changed) == (0, 0, 0), "a fixed point"

        connection.execute("DELETE FROM entity_alias WHERE name_norm = 'acme_holdings_ltd'"
                           " AND alias_kind = 'variant'")  # fmt: skip
        undone = resolve(connection, gen=92)
        assert (undone.kept, undone.retired, undone.changed) == (0, 1, 2)
        assert _rows_of(
            connection, "SELECT retired_at_gen FROM entity_merge WHERE stage = 'exact'"
        ) == [(92,)], "retired, never deleted: the log is append-only"
        assert _rows_of(connection, "SELECT count(*) FROM ow_entity_head") == [(3,)]
        _closure_ok(connection)
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    "edit",
    [
        "UPDATE entity_alias SET taint = 1 WHERE alias_kind = 'variant'",
        "UPDATE entity SET state = 2 WHERE key = 'gamma_inc'",
        "UPDATE entity SET etype = 'unknown' WHERE key = 'gamma_inc'",
    ],
    ids=["untrusted_alias", "retired_entity", "resolution_none"],
)
def test_what_never_merges(ingested: Path, edit: str) -> None:
    """Ruling 2's untrusted key, a retired entity, and stage [2]'s `resolution = 'none'`."""
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings_ltd', 'Acme Holdings Ltd', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        connection.execute(edit)
        assert resolve(connection, gen=90).kept == 0
    finally:
        connection.rollback()
        connection.close()


def test_a_user_split_survives_the_pass_and_the_store_verifies(ingested: Path) -> None:
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings_ltd', 'Acme Holdings Ltd', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        resolve(connection, gen=90)
        connection.execute(
            "INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, guards,"
            " reason, run_id, decided_at_gen) SELECT ?, ?, -1, 'user', 0, 2, '[]', 'two parties',"
            " run_id, 91 FROM derive_run WHERE pass_id = 'op.resolve' LIMIT 1",
            (ids["gamma_inc"], ids["acme_holdings_ltd"]),
        )
        split = resolve(connection, gen=91)
        assert (split.kept, split.blocked, split.retired) == (0, 1, 1)
        assert "1 blocked by a user split" in split.line()
        assert _rows_of(connection, "SELECT count(*) FROM ow_entity_head") == [(3,)]
        _closure_ok(connection)
    finally:
        connection.rollback()
        connection.close()


def test_a_cluster_is_only_as_trusted_as_its_weakest_merge(ingested: Path) -> None:
    """06:1854: `resolution_trust` is a MIN over the cluster's merge rows. An exact merge is
    `EXTRACTED`; a user merge recorded `INFERRED` joining the same cluster lowers all three."""
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings_ltd', 'Acme Holdings Ltd', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        resolve(connection, gen=90)
        connection.execute(
            "INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, guards,"
            " reason, run_id, decided_at_gen) SELECT ?, ?, 1, 'user', 0, 1, '[]', 'same party',"
            " run_id, 91 FROM derive_run WHERE pass_id = 'op.resolve' LIMIT 1",
            (ids["beta_corp"], ids["acme_holdings_ltd"]),
        )
        resolve(connection, gen=91)
        assert _rows_of(
            connection, "SELECT DISTINCT canonical_id, resolution_trust FROM entity"
        ) == [(ids["acme_holdings_ltd"], int(Trust.INFERRED))]
        _closure_ok(connection)
    finally:
        connection.rollback()
        connection.close()


def test_an_entitys_key_is_a_name_even_with_no_alias_row_for_it(ingested: Path) -> None:
    """Ruling 1: gamma's own alias row is gone, and acme carries `gamma_inc` as a variant; the
    two still meet on gamma's key."""
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute("DELETE FROM entity_alias WHERE entity_id = ?", (ids["gamma_inc"],))
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'gamma_inc', 'Gamma Inc', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["acme_holdings_ltd"], ids["acme_holdings_ltd"]),
        )
        assert resolve(connection, gen=90).kept == 1
    finally:
        connection.rollback()
        connection.close()


def _rows_of(connection: sqlite3.Connection, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in connection.execute(sql).fetchall()]


def test_a_pass_with_nothing_to_merge_writes_nothing(tmp_path: Path) -> None:
    """Ruling 8: no run row and no registry row -- an unchanged corpus derives nothing."""
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.resolved is not None
    assert report.resolved.entities == 3
    assert _rows(store, "SELECT count(*) FROM derive_run WHERE pass_id = 'op.resolve'") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM derive_pass WHERE pass_id = 'op.resolve'") == [(0,)]


def test_a_merge_writes_one_corpus_run_and_registers_the_pass(ingested: Path) -> None:
    connection = sqlite3.connect(ingested)
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings_ltd', 'Acme Holdings Ltd', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        resolve(connection, gen=90)
        runs = (
            "SELECT at_gen, status, n_items, segment_id FROM derive_run"
            " WHERE pass_id = 'op.resolve'"
        )
        assert _rows_of(connection, runs) == [(90, "ok", 1, None)]
        registry = "SELECT port, granularity, phase FROM derive_pass WHERE pass_id = 'op.resolve'"
        assert _rows_of(connection, registry) == [("op", "corpus", 50)]
    finally:
        connection.rollback()
        connection.close()
