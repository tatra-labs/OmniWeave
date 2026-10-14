"""`ow graph split` (D698): a user's partition of one closure, and the graph settled again."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph import decide
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.store.projection import canonical_projection
from test_graph_cluster import _ids
from test_graph_decide import _cite, _heads, _ingested, _store
from test_run_parse import _run

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("split"))


def _block(connection: sqlite3.Connection, key: str) -> str:
    """The cite of a block that mentions `key`'s entity and no other."""
    [(cite,)] = connection.execute(
        "SELECT b.cite FROM block b JOIN mention m USING (block_id) WHERE m.state = 0"
        " GROUP BY b.block_id HAVING count(DISTINCT m.entity_id) = 1 AND max(m.entity_id) = ?"
        " ORDER BY b.block_id LIMIT 1",
        (_ids(connection)[key],),
    ).fetchall()
    return str(cite)


def _merged(connection: sqlite3.Connection, *keys: str) -> None:
    """User merges joining `keys[0]` to each of the others."""
    for key in keys[1:]:
        decided = decide.merge(
            connection, first=_cite(connection, keys[0]), second=_cite(connection, key), reason="m"
        )
        assert decided.followed


def _splits(connection: sqlite3.Connection) -> set[frozenset[str]]:
    rows = connection.execute(
        "SELECT l.key, w.key FROM entity_merge m JOIN entity l ON l.entity_id = m.loser_id"
        " JOIN entity w ON w.entity_id = m.winner_id"
        " WHERE m.stage = 'user' AND m.polarity = -1 AND m.retired_at_gen IS NULL"
    ).fetchall()
    return {frozenset((str(a), str(b))) for a, b in rows}


def test_partition_places_each_member_by_its_best_anchor() -> None:
    """Ruling 9: beta is nearest zeta (0.778), not acme, so side 0 wins on its best anchor."""
    keys = {1: "acme_holdings", 2: "zeta_group", 3: "gamma_inc", 4: "beta_corp", 5: "theta_labs"}
    sides, tied = decide.partition(keys, {1: 0, 2: 0, 3: 1}, head=3)
    assert (sides, tied) == ({1: 0, 2: 0, 3: 1, 4: 0, 5: 0}, ())


def test_partition_puts_a_tie_with_the_head() -> None:
    """Ruling 9: `x` is as near `xa` as `xb`, so it stays with the survivor and is reported."""
    keys = {1: "xa", 2: "xb", 3: "x", 4: "xbb"}
    assert decide.partition(keys, {1: 0, 2: 1}, head=2) == ({1: 0, 2: 1, 3: 1, 4: 1}, (3,))
    assert decide.partition(keys, {1: 0, 2: 1}, head=1) == ({1: 0, 2: 1, 3: 0, 4: 1}, (3,))


def test_partition_leaves_a_tie_out_when_the_head_is_one() -> None:
    keys = {1: "xa", 2: "xb", 3: "x", 4: "xbb"}
    assert decide.partition(keys, {1: 0, 2: 1}, head=3) == ({1: 0, 2: 1, 4: 1}, (3,))


def test_a_split_undoes_a_merge(parties: Path) -> None:
    """Rulings 8, 10, 11 and 12, on a closure of two."""
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc")
        acme, gamma = _cite(connection, "acme_holdings"), _cite(connection, "gamma_inc")
        gen = decide.current_generation(connection)
        decided = decide.split(
            connection,
            entity=gamma,
            into=[_block(connection, "gamma_inc"), _block(connection, "acme_holdings")],
            reason="two parties after all",
        )
        assert (decided.polarity, decided.written, decided.retired, decided.followed) == (
            -1,
            1,
            1,
            True,
        )
        assert decided.unassigned == ()
        heads = _heads(connection)
        assert heads["gamma_inc"] != heads["acme_holdings"]
        [row] = connection.execute(
            "SELECT m.winner_id, m.loser_id, m.reason, m.decided_at_gen, m.method, r.pass_id"
            " FROM entity_merge m JOIN derive_run r USING (run_id)"
            " WHERE m.polarity = -1"
        ).fetchall()
        assert (f"e{row[0]}", f"e{row[1]}", row[2], row[3], row[5]) == (
            acme,
            gamma,
            "two parties after all",
            gen,
            "op.resolve",
        ), "identity order, not --into's"
        retired = connection.execute(
            "SELECT retired_at_gen FROM entity_merge WHERE polarity = 1"
        ).fetchall()
        assert retired == [(gen,)]
        [closure] = decided.log.closures
        assert closure.members == (gamma,)
    finally:
        connection.rollback()
        connection.close()


def test_merge_split_merge_comes_back(parties: Path) -> None:
    """GR6's round trip (06:1904): byte-identical projections, and no row disappears."""
    connection = sqlite3.connect(_store(parties))
    try:
        before = canonical_projection(connection)
        _merged(connection, "acme_holdings", "gamma_inc")
        joined = canonical_projection(connection)
        assert joined != before
        into = [_block(connection, "acme_holdings"), _block(connection, "gamma_inc")]
        decide.split(connection, entity=_cite(connection, "acme_holdings"), into=into, reason="s")
        assert canonical_projection(connection) == before
        _merged(connection, "gamma_inc", "acme_holdings")
        assert canonical_projection(connection) == joined
        rows = connection.execute(
            "SELECT polarity, retired_at_gen IS NULL FROM entity_merge WHERE stage = 'user'"
            " ORDER BY merge_id"
        ).fetchall()
        assert rows == [(1, 0), (-1, 0), (1, 1)]
    finally:
        connection.rollback()
        connection.close()


def test_four_members_on_two_sides(parties: Path) -> None:
    """Rulings 9-11: gamma goes with acme and zeta with beta; every cross pair is kept apart."""
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc", "beta_corp", "zeta_group")
        decided = decide.split(
            connection,
            entity=_cite(connection, "zeta_group"),
            into=[_block(connection, "acme_holdings"), _block(connection, "beta_corp")],
            reason="two groups",
        )
        assert (decided.written, decided.retired, decided.followed) == (4, 2, True)
        assert _splits(connection) == {
            frozenset(pair)
            for pair in [
                ("acme_holdings", "beta_corp"),
                ("acme_holdings", "zeta_group"),
                ("gamma_inc", "beta_corp"),
                ("gamma_inc", "zeta_group"),
            ]
        }
        heads = _heads(connection)
        assert heads["gamma_inc"] == heads["acme_holdings"], "a same-side merge stands"
        assert heads["beta_corp"] != heads["acme_holdings"] != heads["zeta_group"]
    finally:
        connection.rollback()
        connection.close()


def test_a_pair_already_kept_apart_is_not_written_again(parties: Path) -> None:
    """Ruling 10: a user split appended but not yet settled is the one this split would write."""
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc")
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, guards,"
            " reason, run_id, decided_at_gen) SELECT ?, ?, -1, 'user', 0, 2, '[]', 'apart',"
            " MIN(run_id), 1 FROM derive_run",
            (ids["acme_holdings"], ids["gamma_inc"]),
        )
        decided = decide.split(
            connection,
            entity=_cite(connection, "acme_holdings"),
            into=[_block(connection, "acme_holdings"), _block(connection, "gamma_inc")],
            reason="two",
        )
        assert (decided.written, decided.retired, decided.followed) == (0, 1, True)
        assert connection.execute(
            "SELECT count(*) FROM entity_merge WHERE polarity = -1"
        ).fetchone() == (1,)
    finally:
        connection.rollback()
        connection.close()


def test_a_tie_is_reported_and_stays_with_the_survivor(parties: Path) -> None:
    """Ruling 9, through the verb's own query: gamma's key is as near acme's as beta's."""
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc", "beta_corp")
        ids = _ids(connection)
        for key, renamed in [("acme_holdings", "xa"), ("beta_corp", "xb"), ("gamma_inc", "x")]:
            connection.execute("UPDATE entity SET key = ? WHERE entity_id = ?", (renamed, ids[key]))
        [(head,)] = connection.execute(
            "SELECT DISTINCT canonical_id FROM entity WHERE entity_id = ?", (ids["gamma_inc"],)
        ).fetchall()
        decided = decide.split(
            connection,
            entity=f"e{ids['gamma_inc']}",
            into=[_block(connection, "xa"), _block(connection, "xb")],
            reason="apart",
        )
        assert decided.unassigned == (f"e{ids['gamma_inc']}",)
        written = 1 if head == ids["gamma_inc"] else 2
        assert decided.written == written
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    "case",
    [
        ("acme_holdings", ["acme_holdings", "gamma_inc"], " ", UsageError, "needs a reason"),
        ("acme_holdings", ["acme_holdings"], "x", UsageError, "two blocks or more"),
        ("acme_holdings", ["acme_holdings", "acme_holdings"], "x", UsageError, "both sides"),
        ("acme_holdings", ["acme_holdings", "delta_partners"], "x", UsageError, "no member"),
        ("delta_partners", ["delta_partners", "acme_holdings"], "x", UsageError, "is one entity"),
        ("acme_holdings", ["acme_holdings", "d999#1"], "x", NotFoundError, "d999#1"),
        ("acme_holdings", ["acme_holdings", "parties.csv"], "x", UsageError, r"names \d+ blocks"),
        ("e999999", ["acme_holdings", "gamma_inc"], "x", NotFoundError, "no entity e999999"),
    ],
    ids=["blank_reason", "one_side", "one_block_twice", "no_member", "closure_of_one",
         "missing_block", "many_blocks", "missing_entity"],
)  # fmt: skip
def test_the_refusals(
    parties: Path, case: tuple[str, list[str], str, type[Exception], str]
) -> None:
    """Ruling 8 and the closure, the reason and the entity the split needs."""
    entity, into, reason, error, match = case
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc")
        ids = _ids(connection)
        refs = [_block(connection, ref) if ref in ids else ref for ref in into]
        with pytest.raises(error, match=match):
            decide.split(
                connection, entity=f"e{ids[entity]}" if entity in ids else entity, into=refs,
                reason=reason,
            )  # fmt: skip
        assert connection.execute(
            "SELECT count(*) FROM entity_merge WHERE polarity = -1"
        ).fetchone() == (0,)
    finally:
        connection.rollback()
        connection.close()


def test_followed_says_when_the_graph_did_not_follow(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 12, read off the heads: with no settle after the rows, the sides still share one."""
    connection = sqlite3.connect(_store(parties))
    try:
        _merged(connection, "acme_holdings", "gamma_inc")
        monkeypatch.setattr(decide, "_settle", lambda _connection, _gen: None)
        decided = decide.split(
            connection,
            entity=_cite(connection, "acme_holdings"),
            into=[_block(connection, "acme_holdings"), _block(connection, "gamma_inc")],
            reason="two",
        )
        assert (decided.written, decided.followed) == (1, False)
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_commits_the_split_and_an_ingest_keeps_it(tmp_path: Path) -> None:
    project = _ingested(tmp_path)
    connection = sqlite3.connect(_store(project))
    try:
        acme, gamma = _cite(connection, "acme_holdings"), _cite(connection, "gamma_inc")
        into = f"{_block(connection, 'acme_holdings')},handbook:{_block(connection, 'gamma_inc')}"
    finally:
        connection.close()
    assert _verb(["merge", acme, gamma, "--reason", "one"], project)[0] == 0
    code, out, err = _verb(
        ["split", f"handbook:{gamma}", "--into", into, "--reason", "two", "--render", "json"],
        project,
    )
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert (document["polarity"], document["written"], document["retired"]) == (-1, 1, 1)
    assert (document["followed"], document["unassigned"]) == (True, [])
    code, _out, err = _verb(["split", acme, "--into", into, "--reason", "again"], project)
    assert code == 1 and "closure is one entity" in err, "a split made is a closure of one"
    config = load(cwd=project, env={"OMNIWEAVE_HOME": str(project / "owhome")})
    report = _run(project, _store(project), config)
    assert report.status == "ok", report.lines()
    connection = sqlite3.connect(_store(project))
    try:
        assert _heads(connection)["gamma_inc"] != _heads(connection)["acme_holdings"]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["split", "e1", "--into", "d1#1,d1#2"], 1),
        (["split", "e1", "--into", "d1#1", "--reason", "x"], 1),
        (["split", "e1", "--reason", "x"], 1),
        (["split", "e999999", "--into", "d1#1,d1#2", "--reason", "x"], 2),
        (["split", "other:e1", "--into", "d1#1,handbook:d1#2", "--reason", "x"], 6),
        (["split", "other:e1", "--into", "d1#1,d1#2", "--corpus", "handbook", "--reason", "x"], 6),
        (["split", "e1", "--into", "d1#1,d1#2", "--corpus", "other", "--reason", "x"], 2),
        (["split", "e1", "--into", "d1#1,d1#2", "--reason", "x", "--quiet"], 1),
    ],
    ids=[
        "no_reason",
        "one_side",
        "no_into",
        "missing",
        "two_corpora",
        "entity_and_flag",
        "undeclared",
        "quiet",
    ],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


@pytest.mark.parametrize(
    "argv",
    [
        ["split", "e1", "--into", "d1#1,d1#2"],
        ["split", "e1", "--into", "d1#1", "--reason", "x"],
        ["split", "e1", "--reason", "x"],
    ],
    ids=["no_reason", "one_side", "no_into"],
)
def test_a_usage_error_is_refused_before_a_store_is_opened(tmp_path: Path, argv: list[str]) -> None:
    """No project here, so a refusal that came from the store would be exit 2, not 1."""
    code, _out, err = _verb(argv, tmp_path)
    assert code == 1 and "ow graph split needs" in err, err


def test_the_action_writes_and_has_no_tool() -> None:
    spec = ACTIONS["graph.split"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        False,
        False,
        True,
    )
