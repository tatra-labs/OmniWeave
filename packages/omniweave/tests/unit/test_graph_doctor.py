"""`ow graph doctor` (D702): the graph's operability, one check at a time."""

from __future__ import annotations

import io
import json
import secrets
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph import doctor as graph_doctor
from omniweave.graph import fuzzy
from omniweave.graph import resolve as op_resolve
from omniweave.graph.doctor import CHECKS, doctor
from omniweave.surface import graph as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.model.enums import AnchorKind
from test_graph_decide import _ingested as _parties
from test_graph_residue import CONTRACT, _store
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from omniweave.sdk.reports import DoctorFinding, GraphDoctorReport


def _ingested(tmp_path: Path) -> Path:
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "contract.md").write_text(CONTRACT, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    return tmp_path


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _ingested(tmp_path_factory.mktemp("doctor"))


@pytest.fixture(scope="module")
def parties(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ten entities, where the contract has one."""
    return _parties(tmp_path_factory.mktemp("doctor_parties"))


def _all(report: GraphDoctorReport) -> dict[str, DoctorFinding]:
    return {f.check: f for f in (*report.failed, *report.warned, *report.ok)}


def _one(connection: sqlite3.Connection, sql: str) -> int:
    [(value,)] = connection.execute(sql).fetchall()
    return int(value or 0)


def _billed_run(connection: sqlite3.Connection, items: int, quarantined: int = 0) -> int:
    """A copy of the first derive_run row, billed, that emitted `items` and quarantined some."""
    columns = [
        str(row[1])
        for row in connection.execute("PRAGMA table_info(derive_run)")
        if row[1] != "run_id"
    ]
    values = {
        "cost_class": "'billed_api'",
        "n_items": str(items),
        "n_quarantined": str(quarantined),
        "cache_key": f"'{secrets.token_hex(32)}'",
        "at_gen": str(1_000_000 + secrets.randbelow(1_000_000)),
    }
    picked = ", ".join(values.get(c, c) for c in columns)
    cursor = connection.execute(
        f"INSERT INTO derive_run({', '.join(columns)})"  # noqa: S608
        f" SELECT {picked} FROM derive_run ORDER BY run_id LIMIT 1"
    )
    return int(cursor.lastrowid or 0)


def _quarantine(connection: sqlite3.Connection, code: str, run_id: int, n: int) -> None:
    for _ in range(n):
        connection.execute(
            "INSERT INTO quarantine(code, run_id, row_kind, payload, at_gen) VALUES(?, ?,"
            " 'entity', '{}', 1)",
            (code, run_id),
        )


def test_the_eleven_checks_on_a_fresh_ingest(contract: Path) -> None:
    """Rulings 1, 2 and 7: every check once, in `CHECKS` order, and nothing billed to judge."""
    connection = sqlite3.connect(_store(contract))
    try:
        report = doctor(connection)
        found = _all(report)
        assert sorted(found) == sorted(CHECKS)
        ok = [f.check for f in report.ok]
        assert ok == [check for check in CHECKS if check in ok], "CHECKS order"
        assert report.failed == ()
        assert [f.check for f in report.warned] == ["unresolved"], "9 of 10 sites, above 0.35"
        assert found["unresolved"].fix == "ow graph residue"
        for check in ("ungrounded", "trust_clamped"):
            assert found[check].detail == "no billed pass has run"
        assert found["dangling_tmp"].severity == "ok"
        kinds = [part.rsplit(" ", 1)[0] for part in found["anchors"].detail.split(" · ")]
        assert kinds == [kind.value for kind in AnchorKind]
        heads = _one(
            connection,
            "SELECT count(*) FROM anchor AS n JOIN doc AS d ON d.doc_ord = n.doc_ord"
            " AND n.gen = d.gen WHERE n.akind = 'section'",
        )
        assert f"section {heads}" in found["anchors"].detail.split(" · ")
        assert found["summary"].detail.startswith("entity.summary has no producer")
        assert (
            found["stale_reports"].detail == "stale 0 · absent 0 · fresh 0 live community report(s)"
        )
    finally:
        connection.close()


def test_check_selects_and_refuses(contract: Path) -> None:
    """Ruling 1: the named checks, in `CHECKS` order; a name outside it is refused."""
    connection = sqlite3.connect(_store(contract))
    try:
        report = doctor(connection, checks=["ungrounded", "dangling_tmp", "trust_clamped"])
        assert [f.check for f in report.ok] == ["ungrounded", "trust_clamped", "dangling_tmp"]
        with pytest.raises(ValueError, match="dangling_tmp"):
            doctor(connection, checks=["dangling"])
    finally:
        connection.close()


def test_the_billed_signals(contract: Path) -> None:
    """Rulings 4 and 5: an unclamped billed pass fails; a clamped one reports its rate."""
    connection = sqlite3.connect(_store(contract))
    try:
        run_id = _billed_run(connection, 15, quarantined=5)
        found = _all(doctor(connection))
        assert (found["trust_clamped"].severity, found["trust_clamped"].fix) == (
            "error",
            "ow store verify   # the generated MAX_TRUST_BY_METHOD triggers",
        )
        _quarantine(connection, "OW_GRAPH_TRUST_CLAMPED", run_id, 20)
        _quarantine(connection, "OW_GRAPH_UNGROUNDED", run_id, 3)
        _quarantine(connection, "OW_GRAPH_DANGLING_TMP", run_id, 1)
        report = doctor(connection)
        found = _all(report)
        assert report.failed == ()
        assert found["trust_clamped"].detail.startswith("1.00 of 20 billed items clamped")
        assert found["ungrounded"].severity == "ok", "3 of 20 is 0.15, and the bar is strict"
        assert found["dangling_tmp"].detail.startswith("1 Segment(s) quarantined whole")
        _quarantine(connection, "OW_GRAPH_UNGROUNDED", run_id, 1)
        assert _all(doctor(connection))["ungrounded"].severity == "warning"
        free = _one(
            connection, "SELECT max(run_id) FROM derive_run WHERE cost_class <> 'billed_api'"
        )
        _quarantine(connection, "OW_GRAPH_UNGROUNDED", free, 50)
        assert _all(doctor(connection))["ungrounded"].detail.startswith("4 of 20"), "billed only"
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("check", "constant", "measured"),
    [
        ("unresolved", "UNRESOLVED_WARN",
         "SELECT 1.0 * (SELECT count(*) FROM ref_unresolved) / count(*) FROM ref_site"),
        ("quarantine", "QUARANTINE_WARN",
         "SELECT 1000.0 * (SELECT count(*) FROM quarantine) / sum(n_items + n_quarantined)"
         " FROM derive_run"),
        ("cover_empty", "COVER_EMPTY_WARN",
         "SELECT 1.0 * count(empty_reason) / count(*) FROM derive_cover"),
    ],
)  # fmt: skip
def test_each_bar_is_strict(
    contract: Path, monkeypatch: pytest.MonkeyPatch, check: str, constant: str, measured: str
) -> None:
    """Ruling 3: at the measured value a check passes; a hair below it, it warns."""
    connection = sqlite3.connect(_store(contract))
    try:
        _quarantine(
            connection,
            "OW_GRAPH_UNPARSED_ITEM",
            _one(connection, "SELECT max(run_id) FROM derive_run"),
            1,
        )
        connection.execute(
            "UPDATE derive_cover SET empty_reason = 'none' WHERE (segment_id, lane, run_id) IN"
            " (SELECT segment_id, lane, run_id FROM derive_cover LIMIT 1)"
        )
        [(value,)] = connection.execute(measured).fetchall()
        assert value > 0
        monkeypatch.setattr(graph_doctor, constant, float(value))
        assert _all(doctor(connection, checks=[check]))[check].severity == "ok"
        monkeypatch.setattr(graph_doctor, constant, float(value) - 1e-9)
        assert _all(doctor(connection, checks=[check]))[check].severity == "warning"
    finally:
        connection.rollback()
        connection.close()


def test_entropy_counts_live_entities_of_fuzzy_etypes(parties: Path) -> None:
    """Ruling 6: funnel stage [3] exactly -- live, of a fuzzy etype, and strictly below the bar."""
    connection = sqlite3.connect(_store(parties))
    try:
        connection.execute("UPDATE etype_vocab SET resolution = 'fuzzy'")
        [(other,)] = connection.execute(
            "SELECT etype FROM etype_vocab WHERE etype NOT IN (SELECT etype FROM entity) LIMIT 1"
        ).fetchall()
        connection.execute(
            "UPDATE etype_vocab SET resolution = 'exact_only' WHERE etype = ?", (other,)
        )
        ids = [int(r[0]) for r in connection.execute("SELECT entity_id FROM entity ORDER BY 1")]
        low, bar, exact, retired = ids[:4]
        for entity_id, key in [(low, "aaaa"), (bar, "abcdeeff"), (exact, "bbbb")]:
            connection.execute("UPDATE entity SET key = ? WHERE entity_id = ?", (key, entity_id))
        assert fuzzy.entropy("abcdeeff") == fuzzy.ENTROPY_MIN, "exactly at the bar, and kept"
        connection.execute("UPDATE entity SET etype = ? WHERE entity_id = ?", (other, exact))
        connection.execute(
            "UPDATE entity SET key = 'cccc', state = 2 WHERE entity_id = ?", (retired,)
        )
        live = [
            str(key)
            for (key,) in connection.execute(
                "SELECT key FROM entity WHERE state = 0 AND etype <> ?", (other,)
            )
        ]
        below = sum(fuzzy.entropy(key) < fuzzy.ENTROPY_MIN for key in live)
        assert below == 1, "aaaa alone: abcdeeff is at the bar, bbbb is exact, cccc is retired"
        detail = _all(doctor(connection, checks=["entropy"]))["entropy"].detail
        assert detail.startswith(f"1 of {len(live)} live entities of fuzzy etypes")
    finally:
        connection.rollback()
        connection.close()


def test_anchors_count_the_head_generation_only(contract: Path) -> None:
    """Ruling 7: an anchor of a superseded generation is history."""
    connection = sqlite3.connect(_store(contract))
    try:
        before = _all(doctor(connection, checks=["anchors"]))["anchors"].detail
        columns = [str(r[1]) for r in connection.execute("PRAGMA table_info(anchor)")]
        picked = ", ".join("gen + 1000" if c == "gen" else c for c in columns)
        connection.execute(
            f"INSERT INTO anchor({', '.join(columns)}) SELECT {picked} FROM anchor"  # noqa: S608
        )
        assert _all(doctor(connection, checks=["anchors"]))["anchors"].detail == before
    finally:
        connection.rollback()
        connection.close()


def test_candidate_pairs_bound_and_name_the_etype(
    parties: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 8: a pair counted once per band it shares (the same bucket in two bands is two
    pairs, not six); past the ceiling, 06:1803's command."""
    connection = sqlite3.connect(_store(parties))
    try:
        connection.execute("DELETE FROM entity_band")
        a, b = (r[0] for r in connection.execute("SELECT entity_id FROM entity LIMIT 2"))
        for band, bucket, etype, entity_id in [
            (0, b"\x01", "org", a),
            (0, b"\x01", "org", b),
            (1, b"\x01", "org", a),
            (1, b"\x01", "org", b),
            (2, b"\x03", "person", a),
        ]:
            connection.execute(
                "INSERT INTO entity_band(band, bucket, etype, entity_id) VALUES(?, ?, ?, ?)",
                (band, bucket, etype, entity_id),
            )
        found = _all(doctor(connection, checks=["candidate_pairs"]))["candidate_pairs"]
        assert found.severity == "ok"
        assert found.detail == (
            f"at most 2 candidate pairs from the persisted bands (the ceiling is "
            f"{op_resolve.MAX_CANDIDATE_PAIRS}); the most from org, 2"
        )
        monkeypatch.setattr(op_resolve, "MAX_CANDIDATE_PAIRS", 2)
        assert (
            _all(doctor(connection, checks=["candidate_pairs"]))["candidate_pairs"].severity == "ok"
        )
        monkeypatch.setattr(op_resolve, "MAX_CANDIDATE_PAIRS", 1)
        over = _all(doctor(connection, checks=["candidate_pairs"]))["candidate_pairs"]
        assert (over.severity, over.fix) == (
            "warning",
            "set etype_vocab.resolution = 'exact_only' for org, then: ow graph types --promote org",
        )
    finally:
        connection.rollback()
        connection.close()


def test_reports_and_summaries(contract: Path) -> None:
    """Ruling 9: live communities by report state, and a summary nothing should have written."""
    connection = sqlite3.connect(_store(contract))
    try:
        for cite, state, report in [("c1", 0, "stale"), ("c2", 0, "absent"), ("c3", 1, "stale")]:
            cursor = connection.execute(
                "INSERT INTO community(cite, level, parent, component_ord, cluster_run, size,"
                " member_digest, run_id, trust, state) SELECT ?, 0, NULL, 0, 1, 1, randomblob(16),"
                " MIN(run_id), 1, ? FROM derive_run",
                (cite, state),
            )
            connection.execute(
                "INSERT INTO community_report(community_id, report_state) VALUES(?, ?)",
                (cursor.lastrowid, report),
            )
        connection.execute(
            "UPDATE entity SET summary = 'x' WHERE entity_id = (SELECT MIN(entity_id) FROM entity)"
        )
        found = _all(doctor(connection, checks=["stale_reports", "summary"]))
        assert (
            found["stale_reports"].detail == "stale 1 · absent 1 · fresh 0 live community report(s)"
        )
        assert (found["summary"].severity, found["summary"].fix) == ("warning", "ow store verify")
    finally:
        connection.rollback()
        connection.close()


def _verb(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd / "owhome")}
    code = verb.main(["graph", *argv], env=env, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_passes_then_fails_on_an_unclamped_billed_pass(tmp_path: Path) -> None:
    project = _ingested(tmp_path)
    code, out, err = _verb(["doctor"], project)
    assert (code, err) == (0, ""), err
    lines = out.splitlines()
    assert lines[0].startswith("warn unresolved: ")
    assert lines[1] == "     fix: ow graph residue"
    assert lines[-1] == f"graph doctor: passes the {len(CHECKS)} check(s) it ran"
    connection = sqlite3.connect(_store(project))
    try:
        _billed_run(connection, 5)
        connection.commit()
    finally:
        connection.close()
    code, out, _err = _verb(["doctor", "--check", "dangling_tmp,trust_clamped,ungrounded"], project)
    assert code == 1
    assert out.splitlines()[0].startswith("FAIL trust_clamped: 0.00 of 5 billed items clamped")
    assert out.splitlines()[-1] == "graph doctor: fails the 3 check(s) it ran"
    code, out, _err = _verb(["doctor", "--quiet"], project)
    assert (code, out) == (1, "")
    code, out, _err = _verb(["doctor", "--render", "json", "--check", "summary"], project)
    document: dict[str, Any] = json.loads(out)
    assert (code, [f["check"] for f in document["ok"]], document["failed"]) == (0, ["summary"], [])


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["doctor", "--check", "nope"], 1),
        (["doctor", "--check", " , "], 1),
        (["doctor", "--render", "jsonl"], 1),
        (["doctor", "--corpus", "other"], 2),
    ],
    ids=["unknown_check", "no_check", "jsonl", "undeclared"],
)
def test_the_verbs_exits(contract: Path, argv: list[str], code: int) -> None:
    got, _out, err = _verb(argv, contract)
    assert got == code, err


def test_the_action_reads_and_has_no_tool() -> None:
    spec = ACTIONS["graph.doctor"]
    assert (spec.mcp_name, spec.read_only, spec.destructive, spec.idempotent) == (
        None,
        True,
        False,
        True,
    )
