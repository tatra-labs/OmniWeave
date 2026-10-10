"""`ow graph merge` (D697): a user's decision appended to the log, and the graph settled again."""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph import decide
from omniweave.graph.resolve import resolve, run_row
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, UsageError
from test_graph_cluster import PARTIES, _ids
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence


def _ingested(tmp_path: Path) -> Path:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "parties.csv").write_text(PARTIES, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("decide"))


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _cite(connection: sqlite3.Connection, key: str) -> str:
    return f"e{_ids(connection)[key]}"


def _heads(connection: sqlite3.Connection) -> dict[str, int]:
    return {str(k): int(c) for k, c in connection.execute("SELECT key, canonical_id FROM entity")}


def test_a_merge_is_one_user_row_and_the_graph_settled_after_it(parties: Path) -> None:
    """Rulings 1, 3 and 7: at the current generation, on op.resolve's run, with its reason."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        acme, gamma = _cite(connection, "acme_holdings"), _cite(connection, "gamma_inc")
        [(stored,)] = connection.execute(
            "SELECT v FROM index_state WHERE k = 'generation'"
        ).fetchall()
        gen = int(stored)
        assert gen > 0 and decide.current_generation(connection) == gen
        run_id = run_row(connection, gen)
        connection.execute(
            "UPDATE derive_run SET status = 'ok', n_items = 5 WHERE run_id = ?", (run_id,)
        )
        connection.execute(
            "INSERT INTO edge(src_entity, dst_entity, relation, observed_block, run_id, trust)"
            " SELECT ?, ?, 'related_to', MIN(block_id), ?, 1 FROM block WHERE state = 0",
            (ids["gamma_inc"], ids["beta_corp"], run_id),
        )
        decided = decide.merge(connection, first=gamma, second=acme, reason="one party")
        assert (decided.polarity, decided.written, decided.retired, decided.joined) == (
            1,
            1,
            0,
            True,
        )
        heads = _heads(connection)
        assert heads["gamma_inc"] == heads["acme_holdings"]
        [closure] = decided.log.closures
        assert set(closure.members) == {acme, gamma}
        [decision] = closure.decisions
        assert (decision.stage, decision.method, decision.reason, decision.decided_at_gen) == (
            "user",
            "user",
            "one party",
            gen,
        )
        assert (decision.winner, decision.loser) == (acme, gamma), "identity order, not argv's"
        [(owner,)] = connection.execute(
            "SELECT r.pass_id FROM entity_merge m JOIN derive_run r USING (run_id)"
            " WHERE m.stage = 'user'"
        ).fetchall()
        assert owner == "op.resolve"
        salient = connection.execute(
            "SELECT DISTINCT frequency, degree, doc_count FROM entity WHERE key IN"
            " ('acme_holdings', 'gamma_inc')"
        ).fetchall()
        assert salient == [(1, 1, 1)], "settled: gamma's edge to beta is now the closure's"
        assert connection.execute(
            "SELECT status, n_items FROM derive_run WHERE run_id = ?", (run_id,)
        ).fetchone() == ("ok", 5), "the run row the decision points at is not re-stamped"
    finally:
        connection.rollback()
        connection.close()


def test_the_same_decision_twice_writes_nothing(parties: Path) -> None:
    """Ruling 5."""
    connection = sqlite3.connect(_store(parties))
    try:
        acme, gamma = _cite(connection, "acme_holdings"), _cite(connection, "gamma_inc")
        once = decide.merge(connection, first=acme, second=gamma, reason="one party")
        [decision] = once.log.closures[0].decisions
        assert (decision.winner, decision.loser) == (acme, gamma), "either argv order: identity"
        again = decide.merge(connection, first=gamma, second=acme, reason="still one")
        assert (again.written, again.joined) == (0, True)
        count = connection.execute(
            "SELECT count(*) FROM entity_merge WHERE stage = 'user'"
        ).fetchone()
        assert count == (1,)
    finally:
        connection.rollback()
        connection.close()


def _split(connection: sqlite3.Connection, left: str, right: str) -> None:
    ids = _ids(connection)
    connection.execute(
        "INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, guards,"
        " reason, run_id, decided_at_gen) SELECT ?, ?, -1, 'user', 0, 2, '[]', 'apart',"
        " MIN(run_id), 1 FROM derive_run",
        (ids[left], ids[right]),
    )


def test_a_merge_retires_the_split_between_the_same_two(parties: Path) -> None:
    """Ruling 4: the newer decision wins."""
    connection = sqlite3.connect(_store(parties))
    try:
        _split(connection, "gamma_inc", "acme_holdings")
        gen = decide.current_generation(connection)
        decided = decide.merge(
            connection,
            first=_cite(connection, "acme_holdings"),
            second=_cite(connection, "gamma_inc"),
            reason="one after all",
        )
        assert (decided.retired, decided.joined) == (1, True)
        retired = connection.execute(
            "SELECT retired_at_gen FROM entity_merge WHERE polarity = -1"
        ).fetchone()
        assert retired == (gen,)
    finally:
        connection.rollback()
        connection.close()


def test_a_merge_a_split_elsewhere_blocks_is_written_and_reported(parties: Path) -> None:
    """Ruling 6: gamma is in acme's closure and kept apart from beta; acme-beta cannot join."""
    connection = sqlite3.connect(_store(parties))
    try:
        ids = _ids(connection)
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
            " SELECT ?, 'acme_holdings', 'Acme Holdings', 'variant', run_id, 2"
            " FROM entity_alias WHERE entity_id = ?",
            (ids["gamma_inc"], ids["gamma_inc"]),
        )
        resolve(connection, gen=decide.current_generation(connection))
        _split(connection, "beta_corp", "gamma_inc")
        decided = decide.merge(
            connection,
            first=_cite(connection, "acme_holdings"),
            second=_cite(connection, "beta_corp"),
            reason="same group",
        )
        assert (decided.written, decided.joined) == (1, False)
        heads = _heads(connection)
        assert heads["beta_corp"] != heads["acme_holdings"]
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    "case",
    [
        ("acme_holdings", "acme_holdings", "x", None, UsageError),
        ("acme_holdings", "gamma_inc", " ", None, UsageError),
        ("acme_holdings", "gamma_inc", "x", "UPDATE entity SET state = 1 WHERE key = 'gamma_inc'",
         UsageError),
        ("acme_holdings", "gamma_inc", "x", "UPDATE entity SET state = 2 WHERE key = 'gamma_inc'",
         UsageError),
        ("acme_holdings", "k1", "x", None, UsageError),
        ("acme_holdings", "e999999", "x", None, NotFoundError),
    ],
    ids=["one_entity", "blank_reason", "overloaded", "retired", "claim_cite", "missing"],
)  # fmt: skip
def test_the_refusals(
    parties: Path, case: tuple[str, str, str, str | None, type[Exception]]
) -> None:
    """Rulings 2 and 7, and a decision that names one entity twice."""
    first, second, reason, edit, error = case
    connection = sqlite3.connect(_store(parties))
    try:
        if edit is not None:
            connection.execute(edit)
        ids = _ids(connection)
        cite = {key: f"e{entity_id}" for key, entity_id in ids.items()}
        with pytest.raises(error):
            decide.merge(
                connection, first=cite.get(first, first), second=cite.get(second, second),
                reason=reason,
            )  # fmt: skip
        assert connection.execute("SELECT count(*) FROM entity_merge").fetchone() == (0,)
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_commits_the_decision_and_an_ingest_keeps_it(tmp_path: Path) -> None:
    project = _ingested(tmp_path)
    connection = sqlite3.connect(_store(project))
    try:
        acme, gamma = _cite(connection, "acme_holdings"), _cite(connection, "gamma_inc")
    finally:
        connection.close()
    code, out, err = _verb(
        ["merge", gamma, f"handbook:{acme}", "--reason", "one party", "--render", "json"], project
    )
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    assert (document["written"], document["joined"], document["polarity"]) == (1, True, 1)
    assert document["closures"][0]["decisions"][0]["reason"] == "one party"
    code, out, _err = _verb(["merge", acme, gamma, "--reason", "again"], project)
    assert code == 0 and out.startswith("merge already stood: nothing written; the graph follows")
    config = load(cwd=project, env={"OMNIWEAVE_HOME": str(project / "owhome")})
    report = _run(project, _store(project), config)
    assert report.status == "ok", report.lines()
    connection = sqlite3.connect(_store(project))
    try:
        assert _heads(connection)["gamma_inc"] == _heads(connection)["acme_holdings"]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["merge", "e1", "e2"], 1),
        (["merge", "e1", "e2", "--reason", " "], 1),
        (["merge", "e1", "e999999", "--reason", "x"], 2),
        (["merge", "other:e1", "handbook:e2", "--reason", "x"], 6),
        (["merge", "e1", "e2", "--reason", "x", "--quiet"], 1),
    ],
    ids=["no_reason", "blank_reason", "missing", "two_corpora", "quiet"],
)
def test_the_verbs_exits(parties: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, parties)
    assert got == code, err


def test_the_action_writes_and_has_no_tool() -> None:
    spec = ACTIONS["graph.merge"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        False,
        False,
        True,
    )
