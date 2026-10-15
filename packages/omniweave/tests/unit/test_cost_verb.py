"""`ow cost`: spend by driver, read off a real ledger. D838.

`omniweave.run.cost` reads and `omniweave.surface.cost` prints. Both are held here over one
`.owstore` built by the shipped migrations and seeded with the rows a run writes:
- `route_decision`, with a frozen `cost_class` and a generation;
- `route_spend`, one row per attempt;
- `route_unit_decision`, one decision serving several units;
- `work` rows for two `op.*` operators.

Every expected number below is derived from those seeds by hand in the comments, so a regression
in the arithmetic cannot pass by moving its expectation with it.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.run.cost import NO_DRIVER, DriverCost, by_driver, manifest_billed, run_window
from omniweave.surface import cost as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_DECISION = """INSERT INTO route_decision(
    decision_id, content_sha256, unit_part, lane, rung, policy_digest, pricebook_digest,
    hints_digest, read_set_digest, driver, cost_class, rule_id, rule_origin, slice_key,
    evidence_digest, est_spend, est_micros, reserved_micros, admission, generation, decided_at)
  VALUES (?, ?, '', 'text', 1, 'p', 'b', 'h', 'r', ?, ?, 'rule', 'origin', 'slice', ?, '{}',
          0, 0, 'admitted', ?, 0)"""
_SPEND = """INSERT INTO route_spend(decision_id, attempt, calls, tokens_in, tokens_out, gpu_ms,
    micros, was_cache_hit, would_have_been_micros, outcome)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')"""
_RUN = """INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest,
    policy_digest, pricebook_digest, lock_digest, omniweave_version, contract, schema, started_ns,
    status, manifest_path) VALUES (?, ?, 'cli', '[]', 'c', 's', 'p', '', 'l', '0.1.0', 1, 1, 0,
    'ok', ?)"""
_WORK = """INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class,
    status, cost_micros, claimed_gen) VALUES (?, '', ?, 1, ?, ?, 'done', ?, ?)"""


def _seed(connection: Any, manifest: str) -> None:
    """The ledger every test reads. Generation 1 is run r1; generation 2 is run r2."""
    for uri in ("file:///a", "file:///b", "file:///c"):
        connection.execute(
            "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
            "VALUES(?, 'planned', 'internal', 1)",
            (uri,),
        )
    decisions = (
        # id, driver, class, generation, units
        ("dA", "parse.page.olmocr", "local_compute", 1, ("file:///a", "file:///b", "file:///c")),
        ("dB", "derive.entity.llm", "billed_api", 1, ("file:///a",)),
        ("dC", "parse.pdf.pdfium", "free", 1, ("file:///a", "file:///b")),
        ("dD", "", "free", 1, ("file:///c",)),
        ("dE", "derive.entity.llm", "billed_api", 2, ("file:///a", "file:///b")),
    )
    for at, (decision, driver, cost_class, generation, units) in enumerate(decisions):
        connection.execute(
            "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) "
            "VALUES (?, '{}', 0)",
            (f"ev_{decision}",),
        )
        connection.execute(
            _DECISION,
            (decision, f"{at:064d}", driver, cost_class, f"ev_{decision}", generation),
        )
        for uri in units:
            connection.execute(
                "INSERT INTO route_unit_decision(unit_uri, unit_part, lane, decision_id, "
                "first_seen_at) VALUES (?, '', 'text', ?, 0)",
                (uri, decision),
            )
    # decision, attempt, calls, tokens_in, tokens_out, gpu_ms, micros, hit, would_have_been
    connection.executemany(
        _SPEND,
        [
            ("dA", 1, 1, 0, 100, 50, 600, 0, 0),
            ("dA", 2, 1, 0, 120, 70, 400, 1, 900),
            ("dB", 1, 2, 300, 40, 0, 1500, 0, 0),
            ("dE", 1, 1, 0, 0, 0, 700, 0, 0),
        ],
    )
    connection.executemany(
        _WORK,
        [
            ("file:///a", "op.cluster", "k1", "local_compute", 250, 1),
            ("file:///b", "op.cluster", "k2", "local_compute", 50, 2),
            ("file:///a", "op.identify", "k3", "free", 0, 1),
            ("file:///b", "op.identify", "k4", "free", 0, 1),
        ],
    )
    connection.execute(_RUN, ("r1", 1, manifest))
    connection.execute(_RUN, ("r2", 2, ""))
    connection.commit()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    manifest = tmp_path / "runs" / "r1.json"
    manifest.parent.mkdir()
    manifest.write_bytes(json.dumps({"cost": {"billed_micros": 2500}}).encode())
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
        _seed(connection, str(manifest))
    finally:
        connection.close()
    return tmp_path


def _ledger(project: Path) -> Any:
    return store_sqlite.connect_readonly(project / ".omniweave" / "index.owstore")


# --- the rows ---------------------------------------------------------------------------------

WHOLE = (
    # derive.entity.llm: dB (gen 1, a) + dE (gen 2, a and b): units a, b counted once each;
    # calls 2+1; micros 1500+700.
    DriverCost("derive.entity.llm", "billed_api", 2, 3, 300, 40, 0, 2200, 0, 0),
    # olmocr: one decision serving three units, two attempts, one a cache hit.
    DriverCost("parse.page.olmocr", "local_compute", 3, 2, 0, 220, 120, 1000, 1, 900),
    # op.cluster: work rows on a (250) and b (50).
    DriverCost("op.cluster", "local_compute", 2, 0, 0, 0, 0, 300, 0, 0),
    DriverCost(NO_DRIVER, "free", 1, 0, 0, 0, 0, 0, 0, 0),
    DriverCost("op.identify", "free", 2, 0, 0, 0, 0, 0, 0, 0),
    DriverCost("parse.pdf.pdfium", "free", 2, 0, 0, 0, 0, 0, 0, 0),
)


def test_every_driver_and_operator_over_the_whole_ledger(project: Path) -> None:
    """Rulings 1-4 and 6: spend joined to its decision directly, so olmocr's one decision over
    three units is billed once (1,000, not 3,000); a free driver with no spend row is still a row;
    `''` is `(no driver)`; each `op.*` operator is its own row; costliest first."""
    connection = _ledger(project)
    try:
        assert by_driver(connection) == WHOLE
    finally:
        connection.close()


def test_a_generation_keeps_its_own_decisions_and_op_rows(project: Path) -> None:
    connection = _ledger(project)
    try:
        rows = {row.driver: row for row in by_driver(connection, generation=1)}
    finally:
        connection.close()
    assert (rows["derive.entity.llm"].units, rows["derive.entity.llm"].micros) == (1, 1500)
    assert (rows["op.cluster"].units, rows["op.cluster"].micros) == (1, 250)
    assert rows["parse.page.olmocr"].micros == 1000


def test_a_frozen_class_splits_one_driver_into_two_rows(project: Path) -> None:
    """Ruling 2: the class is the decision's, so a card that changed class is two rows."""
    connection = store_sqlite.connect(project / ".omniweave" / "index.owstore")
    try:
        connection.execute(
            "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) "
            "VALUES ('ev_dF', '{}', 0)"
        )
        connection.execute(
            _DECISION, ("dF", "9" * 64, "derive.entity.llm", "local_compute", "ev_dF", 2)
        )
        connection.commit()
        classes = [(r.driver, r.cost_class) for r in by_driver(connection) if "llm" in r.driver]
    finally:
        connection.close()
    assert classes == [
        ("derive.entity.llm", "billed_api"),
        ("derive.entity.llm", "local_compute"),
    ]


def test_a_run_is_its_generation_and_its_manifest(project: Path) -> None:
    connection = _ledger(project)
    try:
        r1, r2 = run_window(connection, "r1"), run_window(connection, "r2")
        assert run_window(connection, "nope") is None
    finally:
        connection.close()
    assert r1 is not None and r2 is not None
    assert (r1.generation, r2.generation, r2.manifest_path) == (1, 2, "")
    assert manifest_billed(r1.manifest_path) == 2500


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'{"cost": {}}', b'{"cost": {"billed_micros": true}}']
)
def test_an_unreadable_manifest_reads_as_none(tmp_path: Path, body: bytes) -> None:
    path = tmp_path / "m.json"
    path.write_bytes(body)
    assert manifest_billed(str(path)) is None
    assert manifest_billed("") is None
    assert manifest_billed(str(tmp_path / "absent.json")) is None


# --- the verb ---------------------------------------------------------------------------------


def _env(home: Path) -> dict[str, str]:
    return {"OMNIWEAVE_HOME": str(home / "owhome"), "HOME": str(home), "USERPROFILE": str(home)}


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["cost", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_table_totals_and_says_what_the_cache_saved(project: Path) -> None:
    """Ruling 3: TOTAL is the sum of `micros` (2,200 + 1,000 + 300) and `saved` of `saved`."""
    code, out, err = _run(["--corpus", "handbook"], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].split() == list(verb._HEADER)
    assert [line.split()[0] for line in lines[1:7]] == [row.driver.split()[0] for row in WHOLE]
    assert lines[7].split() == ["TOTAL", "3,500", "900"]
    assert lines[8:] == [
        "cache saved 900µ (0.3x the bill).",
        "window: every generation in the ledger",
    ]


def test_a_run_reconciles_against_its_manifest(project: Path) -> None:
    code, out, _ = _run(["--run", "r1"], project)
    assert code == 0
    assert out.splitlines()[-2:] == [
        "window: run r1's generation",
        "reconcile: Σ route_spend.micros = 2,500 == manifest.cost.billed_micros 2,500  OK",
    ]


def test_a_mismatch_is_printed_and_not_exited_on(project: Path) -> None:
    """Ruling 5: exiting on it is `--verify`'s, which is not served."""
    (project / "runs" / "r1.json").write_bytes(b'{"cost": {"billed_micros": 2400}}')
    code, out, _ = _run(["--run", "r1"], project)
    assert code == 0
    assert out.splitlines()[-1].endswith("!= manifest.cost.billed_micros 2,400  MISMATCH")


def test_a_run_with_no_manifest_says_so(project: Path) -> None:
    code, out, _ = _run(["--run", "r2"], project)
    assert code == 0
    assert out.splitlines()[-1] == (
        "reconcile: Σ route_spend.micros = 700; run r2 wrote no readable manifest"
    )


def test_an_unknown_run_is_not_found(project: Path) -> None:
    code, out, err = _run(["--run", "nope"], project)
    assert (code, out) == (2, "")
    assert "no run 'nope' in corpus 'handbook'" in err


def test_render_json_is_the_report(project: Path) -> None:
    code, out, _ = _run(["--run", "r1", "--render", "json"], project)
    assert code == 0
    bill = json.loads(out)
    assert {k: bill[k] for k in ("corpus", "run_id", "total_micros", "saved_micros")} == {
        "corpus": "handbook",
        "run_id": "r1",
        "total_micros": 2750,
        "saved_micros": 900,
    }
    assert (bill["billed_micros"], bill["manifest_billed_micros"]) == (2500, 2500)
    assert [row["driver"] for row in bill["rows"]][:3] == [
        "derive.entity.llm",
        "parse.page.olmocr",
        "op.cluster",
    ]


def test_an_empty_ledger_says_so(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    assert _run([], tmp_path) == (
        0,
        "handbook: no decision and no op row in this window\n"
        "window: every generation in the ledger\n",
        "",
    )


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--by", "day"], "--by day is parsed and not served by ow cost"),
        (["--render", "jsonl"], "--render jsonl is parsed and not served by ow cost"),
        (["--quiet"], "--quiet is parsed and not served by ow cost"),
    ],
)
def test_what_is_not_served_is_refused_by_name(project: Path, argv: list[str], named: str) -> None:
    code, out, err = _run(argv, project)
    assert (code, out) == (1, "")
    assert named in err


def test_the_action_is_ow_cost_in_the_full_roster() -> None:
    spec = ACTIONS["cost.report"]
    assert (spec.mcp_name, spec.cli, spec.read_only, spec.destructive) == (
        "ow_cost",
        ("cost",),
        True,
        False,
    )
    assert [str(p) for p in spec.listed_in] == ["full"]


def test_the_launcher_routes_cost(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(project)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    assert launcher.main(["cost", "--run", "nope"]) == 2
    assert "no run 'nope'" in capsys.readouterr().err
