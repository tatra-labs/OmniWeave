"""`ow graph merges` (D696): the resolution decision log, one closure at a time."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph.resolve import resolve
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.errors import NotFoundError
from omniweave_core.store.merges import merge_log
from test_graph_cluster import PARTIES, _ids
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("merges")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _alias(connection: sqlite3.Connection, key: str, name: str) -> None:
    """`key` carries `name` as a variant, so the exact stage merges the two."""
    ids = _ids(connection)
    connection.execute(
        "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
        " SELECT ?, ?, ?, 'variant', run_id, 2 FROM entity_alias WHERE entity_id = ?",
        (ids[key], name, name, ids[key]),
    )


def test_nothing_merged_is_an_empty_log(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        log = merge_log(connection)
        assert (log.entity, log.closures) == (None, ())
    finally:
        connection.close()


def test_a_merge_is_one_closure_and_its_live_decision(parties: Path) -> None:
    """Ruling 2: the whole log is every closure of two or more, and only its live decisions."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        _alias(connection, "gamma_inc", "acme_holdings")
        resolve(connection, gen=90)
        [closure] = merge_log(connection).closures
        acme, gamma = f"e{ids['acme_holdings']}", f"e{ids['gamma_inc']}"
        assert (closure.head, closure.members) == (acme, (acme, gamma))
        [decision] = closure.decisions
        assert (decision.loser, decision.winner, decision.polarity, decision.stage) == (
            gamma,
            acme,
            1,
            "exact",
        )
        assert (decision.method, decision.decided_at_gen, decision.retired_at_gen) == (
            "heuristic",
            90,
            None,
        )
        assert decision.guards == ("scoped_label_crossdoc",)
    finally:
        connection.rollback()
        connection.close()


def test_an_entity_names_its_closure_and_its_history(parties: Path) -> None:
    """Ruling 1: a retired decision is in the entity's log and out of the whole log."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        _alias(connection, "gamma_inc", "acme_holdings")
        resolve(connection, gen=90)
        gamma = f"e{ids['gamma_inc']}"
        merged = merge_log(connection, gamma)
        assert merged.entity == gamma
        assert merged.closures[0].head == f"e{ids['acme_holdings']}", "a merged-away cite"
        connection.execute("DELETE FROM entity_alias WHERE alias_kind = 'variant'")
        resolve(connection, gen=91)
        assert merge_log(connection).closures == ()
        [closure] = merge_log(connection, gamma).closures
        assert (closure.head, closure.members) == (gamma, (gamma,))
        [decision] = closure.decisions
        assert decision.retired_at_gen == 91
        by_number = merge_log(connection, str(ids["gamma_inc"]))
        assert (by_number.entity, by_number.closures) == (gamma, (closure,)), "the cite, named"
    finally:
        connection.rollback()
        connection.close()


def test_the_whole_log_shows_a_closures_live_decisions_only(parties: Path) -> None:
    """Ruling 2: gamma left acme's closure and beta joined it; the whole log shows beta's merge,
    and acme's own log shows both."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        _alias(connection, "gamma_inc", "acme_holdings")
        resolve(connection, gen=90)
        connection.execute("DELETE FROM entity_alias WHERE alias_kind = 'variant'")
        _alias(connection, "beta_corp", "acme_holdings")
        resolve(connection, gen=91)
        [closure] = merge_log(connection).closures
        assert [d.loser for d in closure.decisions] == [f"e{ids['beta_corp']}"]
        [full] = merge_log(connection, f"e{ids['acme_holdings']}").closures
        assert [(d.loser, d.retired_at_gen) for d in full.decisions] == [
            (f"e{ids['gamma_inc']}", 91),
            (f"e{ids['beta_corp']}", None),
        ]
    finally:
        connection.rollback()
        connection.close()


def test_a_user_split_is_in_the_closure_of_either_end(parties: Path) -> None:
    """Ruling 3, with its reason."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, guards,"
            " reason, run_id, decided_at_gen) SELECT ?, ?, -1, 'user', 0, 2, '[]',"
            " 'two parties', MIN(run_id), 92 FROM derive_run",
            (ids["beta_corp"], ids["acme_holdings"]),
        )
        for key in ("beta_corp", "acme_holdings"):
            [closure] = merge_log(connection, f"e{ids[key]}").closures
            [decision] = closure.decisions
            assert (decision.polarity, decision.stage, decision.reason) == (
                -1,
                "user",
                "two parties",
            )
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("entity", "error"),
    [("k1", ValueError), ("e999999", NotFoundError)],
    ids=["claim_cite", "missing"],
)
def test_the_refusals(parties: Path, entity: str, error: type[Exception]) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        with pytest.raises(error):
            merge_log(connection, entity)
    finally:
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_renders_the_log(parties: Path) -> None:
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        _alias(connection, "gamma_inc", "acme_holdings")
        resolve(connection, gen=90)
        connection.commit()
        code, out, err = _verb(["merges", "--render", "json"], parties)
        assert (code, err) == (0, ""), err
        document: dict[str, Any] = json.loads(out)
        [closure] = document["closures"]
        assert closure["head"] == f"e{ids['acme_holdings']}"
        assert closure["decisions"][0]["stage"] == "exact"
        code, out, _err = _verb(["merges", "--entity", f"handbook:e{ids['gamma_inc']}"], parties)
        assert code == 0
        head, line = out.rstrip("\n").split("\n")
        assert head.startswith(f"e{ids['acme_holdings']}  2 member(s)")
        assert "merge " in line and "exact" in line and "live" in line
    finally:
        connection.execute("DELETE FROM entity_alias WHERE alias_kind = 'variant'")
        resolve(connection, gen=91)
        connection.commit()
        connection.close()


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["merges", "--entity", "k1"], 1),
        (["merges", "--entity", "e999999"], 2),
        (["merges", "--quiet"], 1),
        (["merges", "--entity", "other:e1", "--corpus", "handbook"], 6),
    ],
    ids=["claim_cite", "missing", "quiet", "two_corpora"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


def test_an_empty_log_says_so(parties: Path) -> None:
    code, out, _err = _verb(["merges"], parties)
    assert (code, out) == (0, "no closure of two or more: nothing is merged\n")


def test_the_action_has_no_tool_and_is_read_only() -> None:
    spec = ACTIONS["graph.merges"]
    assert (spec.mcp_name, spec.cli, spec.read_only) == (None, ("graph", "merges"), True)
