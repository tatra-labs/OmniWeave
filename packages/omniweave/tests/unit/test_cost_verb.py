"""`ow cost`: spend, sliced and windowed, read off a real ledger. D838, D839.

`omniweave.run.cost` reads and `omniweave.surface.cost` prints. Both are held here over one
`.owstore` built by the shipped migrations and seeded with the rows a run writes:
- `route_decision`, with a frozen `cost_class`, a generation and a `decided_at`;
- `route_spend`, one row per attempt, one of them from a named provider;
- `route_unit_decision`, one decision serving several units;
- `work` rows for two `op.*` operators.

Generation 1 decided on 2026-10-01 and generation 2 on 2026-10-10, both at 12:00 UTC. Every
expected number below is derived from the seeds by hand in a comment, so a regression in the
arithmetic cannot pass by moving its expectation with it.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.run.cost import (
    NO_DRIVER,
    RowCost,
    by_key,
    earliest_decision,
    latest_run,
    manifest_billed,
    run_window,
    since_ms,
    unspent,
)
from omniweave.surface import cost as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _ms(day: int) -> int:
    return int(dt.datetime(2026, 10, day, 12, tzinfo=dt.UTC).timestamp() * 1000)


OCT_1, OCT_10 = _ms(1), _ms(10)

_DECISION = """INSERT INTO route_decision(
    decision_id, content_sha256, unit_part, lane, rung, policy_digest, pricebook_digest,
    hints_digest, read_set_digest, driver, cost_class, rule_id, rule_origin, slice_key,
    evidence_digest, est_spend, est_micros, reserved_micros, admission, generation, decided_at)
  VALUES (?, ?, '', 'text', 1, 'p', 'b', 'h', 'r', ?, ?, 'rule', 'origin', 'slice', ?, '{}',
          0, 0, 'admitted', ?, ?)"""
_SPEND = """INSERT INTO route_spend(decision_id, attempt, provider, calls, tokens_in, tokens_out,
    gpu_ms, micros, was_cache_hit, would_have_been_micros, outcome)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')"""
_RUN = """INSERT INTO run(run_id, generation, trigger, argv, config_digest, semantic_digest,
    policy_digest, pricebook_digest, lock_digest, omniweave_version, contract, schema, started_ns,
    status, manifest_path) VALUES (?, ?, 'cli', '[]', 'c', 's', 'p', '', 'l', '0.1.0', 1, 1, 0,
    'ok', ?)"""
_WORK = """INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class,
    status, cost_micros, claimed_gen, last_attempt_at)
  VALUES (?, '', ?, 1, ?, ?, 'done', ?, ?, ?)"""


def _decide(connection: Any, decision: str, driver: str, cost_class: str, generation: int) -> None:
    connection.execute(
        "INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) VALUES (?, '{}', 0)",
        (f"ev_{decision}",),
    )
    connection.execute(
        _DECISION,
        (
            decision,
            decision.encode().hex().ljust(64, "0"),
            driver,
            cost_class,
            f"ev_{decision}",
            generation,
            OCT_1 if generation == 1 else OCT_10,
        ),
    )


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
    for decision, driver, cost_class, generation, units in decisions:
        _decide(connection, decision, driver, cost_class, generation)
        for uri in units:
            connection.execute(
                "INSERT INTO route_unit_decision(unit_uri, unit_part, lane, decision_id, "
                "first_seen_at) VALUES (?, '', 'text', ?, 0)",
                (uri, decision),
            )
    # decision, attempt, provider, calls, tokens_in, tokens_out, gpu_ms, micros, hit, would-be
    connection.executemany(
        _SPEND,
        [
            ("dA", 1, "", 1, 0, 100, 50, 600, 0, 0),
            ("dA", 2, "", 1, 0, 120, 70, 400, 1, 900),
            ("dB", 1, "vendor-a", 2, 300, 40, 0, 1500, 0, 0),
            ("dE", 1, "", 1, 0, 0, 0, 700, 0, 0),
        ],
    )
    # unit, operator, cache_key, class, micros, claimed_gen, last_attempt_at
    connection.executemany(
        _WORK,
        [
            ("file:///a", "op.cluster", "k1", "local_compute", 250, 1, OCT_1),
            ("file:///b", "op.cluster", "k2", "local_compute", 50, 2, OCT_10),
            ("file:///a", "op.identify", "k3", "free", 0, 1, OCT_1),
            ("file:///b", "op.identify", "k4", "free", 0, 1, OCT_1),
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


def _rows(project: Path, by: str, **window: Any) -> tuple[RowCost, ...]:
    connection = store_sqlite.connect_readonly(project / ".omniweave" / "index.owstore")
    try:
        return by_key(connection, by, **window)
    finally:
        connection.close()


# --- the rows ---------------------------------------------------------------------------------

WHOLE = (
    # derive.entity.llm: dB (gen 1, a) + dE (gen 2, a and b): units a, b counted once each;
    # calls 2+1; micros 1500+700.
    RowCost("derive.entity.llm", "billed_api", 2, 3, 300, 40, 0, 2200, 0, 0),
    # olmocr: one decision serving three units, two attempts, one a cache hit.
    RowCost("parse.page.olmocr", "local_compute", 3, 2, 0, 220, 120, 1000, 1, 900),
    # op.cluster: work rows on a (250) and b (50).
    RowCost("op.cluster", "local_compute", 2, 0, 0, 0, 0, 300, 0, 0),
    RowCost(NO_DRIVER, "free", 1, 0, 0, 0, 0, 0, 0, 0),
    RowCost("op.identify", "free", 2, 0, 0, 0, 0, 0, 0, 0),
    RowCost("parse.pdf.pdfium", "free", 2, 0, 0, 0, 0, 0, 0, 0),
)


def test_every_driver_and_operator_over_the_whole_ledger(project: Path) -> None:
    """Rulings 1-4 and 7: spend joined to its decision directly, so olmocr's one decision over
    three units is billed once (1,000, not 3,000); a free driver with no spend row is still a row;
    `''` is `(no driver)`; each `op.*` operator is its own row; costliest first."""
    assert _rows(project, "driver") == WHOLE


def test_a_generation_keeps_its_own_decisions_and_op_rows(project: Path) -> None:
    rows = {row.key: row for row in _rows(project, "driver", generation=1)}
    assert (rows["derive.entity.llm"].units, rows["derive.entity.llm"].micros) == (1, 1500)
    assert (rows["op.cluster"].units, rows["op.cluster"].micros) == (1, 250)
    assert rows["parse.page.olmocr"].micros == 1000


def test_since_keeps_decisions_and_op_rows_at_or_after_the_cutoff(project: Path) -> None:
    """Ruling 5: a cutoff of 2026-10-05 keeps only generation 2's decision dE and the op.cluster
    attempt on 2026-10-10; on the cutoff itself is kept."""
    late = _rows(project, "driver", cutoff_ms=_ms(5))
    assert [(r.key, r.units, r.micros) for r in late] == [
        ("derive.entity.llm", 2, 700),
        ("op.cluster", 1, 50),
    ]
    assert len(_rows(project, "driver", cutoff_ms=OCT_10)) == 2


def test_a_frozen_class_splits_one_driver_into_two_rows(project: Path) -> None:
    """Ruling 2: the class is the decision's, so a card that changed class is two rows."""
    connection = store_sqlite.connect(project / ".omniweave" / "index.owstore")
    try:
        _decide(connection, "dF", "derive.entity.llm", "local_compute", 2)
        connection.commit()
    finally:
        connection.close()
    classes = [(r.key, r.cost_class) for r in _rows(project, "driver") if "llm" in r.key]
    assert classes == [
        ("derive.entity.llm", "billed_api"),
        ("derive.entity.llm", "local_compute"),
    ]


def test_by_provider_names_the_local_one_and_folds_op_rows(project: Path) -> None:
    """Rulings 3, 4 and 6: dB's spend is vendor-a's; every other is `''`, which is `local`; the
    two op operators are one row keyed `op` per class."""
    rows = {(r.key, r.cost_class): (r.units, r.micros) for r in _rows(project, "provider")}
    assert rows == {
        ("vendor-a", "billed_api"): (1, 1500),  # dB on a
        ("local", "billed_api"): (2, 700),  # dE on a, b
        ("local", "local_compute"): (3, 1000),  # dA on a, b, c
        ("local", "free"): (3, 0),  # dC on a, b and dD on c: no spend row, provider ''
        ("op", "local_compute"): (2, 300),  # op.cluster on a, b
        ("op", "free"): (2, 0),  # op.identify on a, b
    }


@pytest.mark.parametrize(("by", "key"), [("lane", "text"), ("rung", "1"), ("slice", "slice")])
def test_a_decision_column_slices_every_routed_row(project: Path, by: str, key: str) -> None:
    """Every seeded decision has lane `text`, rung 1 and slice `slice`, so each slicing keys the
    routed rows alike, one per class; op rows are `op`."""
    rows = {(r.key, r.cost_class): r.micros for r in _rows(project, by)}
    assert rows == {
        (key, "billed_api"): 2200,
        (key, "local_compute"): 1000,
        (key, "free"): 0,
        ("op", "local_compute"): 300,
        ("op", "free"): 0,
    }


def test_by_day_merges_routed_and_op_rows_on_one_date(project: Path) -> None:
    """Ruling 4: an op row falls on its last attempt's day, and a routed row and an op row of one
    day and class are one row (olmocr 1,000 + op.cluster 250 on 2026-10-01)."""
    rows = [(r.key, r.cost_class, r.units, r.micros) for r in _rows(project, "day")]
    assert rows == [
        ("2026-10-01", "billed_api", 1, 1500),  # dB
        ("2026-10-01", "local_compute", 4, 1250),  # dA on a, b, c + op.cluster on a
        ("2026-10-10", "billed_api", 2, 700),  # dE
        ("2026-10-10", "local_compute", 1, 50),  # op.cluster on b
        ("2026-10-01", "free", 5, 0),  # dC on a, b; dD on c; op.identify on a, b
    ]


@pytest.mark.parametrize(
    ("text", "ms"), [("7d", 7 * 86_400_000), ("2h", 7_200_000), ("30m", 1_800_000)]
)
def test_since_takes_minutes_hours_and_days(text: str, ms: int) -> None:
    assert since_ms(text) == ms


@pytest.mark.parametrize("text", ["7", "0d", "7w", "-1d", "7dd", "d", ""])
def test_anything_else_is_not_a_duration(text: str) -> None:
    with pytest.raises(ValueError, match="is not a duration"):
        since_ms(text)


def test_the_earliest_decision_and_a_run_window(project: Path) -> None:
    connection = store_sqlite.connect_readonly(project / ".omniweave" / "index.owstore")
    try:
        assert earliest_decision(connection) == OCT_1
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


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> int:
    """The wall clock `--since` reads, pinned to 2026-10-12 12:00 UTC."""
    pinned = _ms(12)
    monkeypatch.setattr(verb, "_wall_ms", lambda: pinned)
    return pinned


def test_the_table_totals_and_says_what_the_cache_saved(project: Path) -> None:
    """Ruling 3: TOTAL is the sum of `micros` (2,200 + 1,000 + 300) and `saved` of `saved`."""
    code, out, err = _run(["--corpus", "handbook"], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].split() == ["driver", *verb._COLUMNS]
    assert [line.split()[0] for line in lines[1:7]] == [row.key.split()[0] for row in WHOLE]
    assert lines[7].split() == ["TOTAL", "3,500", "900"]
    assert lines[8:] == [
        "cache saved 900µ (0.3x the bill).",
        "window: every generation in the ledger",
    ]


def test_the_first_column_is_named_for_the_slicing(project: Path) -> None:
    code, out, _ = _run(["--by", "provider"], project)
    assert code == 0
    assert out.splitlines()[0].split()[0] == "provider"
    assert out.splitlines()[1].split()[:2] == ["vendor-a", "billed_api"]


@pytest.mark.usefixtures("now")
def test_since_is_a_window_back_from_now(project: Path) -> None:
    """2026-10-12 minus 7d is 2026-10-05: only dE and the second op.cluster attempt remain."""
    code, out, _ = _run(["--since", "7d"], project)
    assert code == 0
    lines = out.splitlines()
    assert [line.split()[0] for line in lines[1:3]] == ["derive.entity.llm", "op.cluster"]
    assert lines[3].split() == ["TOTAL", "750", "0"]
    assert lines[-1] == "window: since 2026-10-05 12:00 UTC (7d)"


@pytest.mark.usefixtures("now")
def test_since_past_the_ledgers_start_says_so(project: Path) -> None:
    """Ruling 2: a bill that silently starts where the ledger does is a bill with a hole."""
    code, out, _ = _run(["--since", "30d"], project)
    assert code == 0
    assert out.splitlines()[-2:] == [
        "window: since 2026-09-12 12:00 UTC (30d)",
        "the ledger's earliest decision is 2026-10-01 12:00 UTC: nothing older is held to count",
    ]


def test_a_run_reconciles_against_its_manifest(project: Path) -> None:
    code, out, _ = _run(["--run", "r1"], project)
    assert code == 0
    assert out.splitlines()[-2:] == [
        "window: run r1's generation",
        "reconcile: Σ route_spend.micros = 2,500 == manifest.cost.billed_micros 2,500  OK",
    ]


def test_the_reconcile_sums_spend_whatever_the_slicing(project: Path) -> None:
    """The bill is `route_spend`'s, so `--by provider` reconciles exactly as `--by driver` does."""
    code, out, _ = _run(["--run", "r1", "--by", "provider"], project)
    assert code == 0
    assert out.splitlines()[-1].endswith("== manifest.cost.billed_micros 2,500  OK")


def test_a_mismatch_is_printed_and_not_exited_on(project: Path) -> None:
    """Ruling 5: exiting on it is `--verify`'s (ruling 6)."""
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
    keys = ("corpus", "by", "since", "run_id", "total_micros", "saved_micros")
    assert {k: bill[k] for k in keys} == {
        "corpus": "handbook",
        "by": "driver",
        "since": None,
        "run_id": "r1",
        "total_micros": 2750,
        "saved_micros": 900,
    }
    assert (bill["billed_micros"], bill["manifest_billed_micros"]) == (2500, 2500)
    assert [row["key"] for row in bill["rows"]][:3] == [
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
        (["--by", "document"], "--by document is parsed and not served by ow cost"),
        (["--render", "jsonl"], "--render jsonl is parsed and not served by ow cost"),
        (["--quiet"], "--quiet is parsed and not served by ow cost"),
        (["--since", "7d", "--run", "r1"], "--since and --run are two windows; give one"),
        (["--since", "7w"], "'7w' is not a duration"),
    ],
)
@pytest.mark.usefixtures("now")
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


# ---------------------------------------------------------------------------
# --verify: I30's two self-checks over one run (ruling 6). D853.
# ---------------------------------------------------------------------------

_DECIDED = """INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class,
    status, decision_id, driver, dispatch_key)
  VALUES (:unit, '', 'parse.' || :key, 1, :key, 'free', :status, :decision, 'd', 'k')"""


def _decided(project: Path, *rows: tuple[str, str, str, str]) -> None:
    """Work rows naming a decision: `(unit, cache_key, status, decision_id)`."""
    connection = store_sqlite.connect(project / ".omniweave" / "index.owstore")
    try:
        connection.executemany(
            _DECIDED,
            [dict(zip(("unit", "key", "status", "decision"), row, strict=True)) for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def test_verify_passes_a_run_whose_bill_reconciles(project: Path) -> None:
    _decided(project, ("file:///a", "v1", "done", "dA"), ("file:///b", "v2", "done", "dB"))
    code, out, err = _run(["--run", "r1", "--verify"], project)
    assert (code, err) == (0, "")
    assert out.splitlines()[-3:] == [
        "verify: run r1: Σ route_spend.micros == manifest billed  OK",
        "verify: run r1: every finished decided work row has a spend row  OK",
        "verify: a Sequence's apportionment is not checked: no session total is recorded",
    ]


def test_verify_fails_a_finished_decided_row_with_no_spend(project: Path) -> None:
    """dC decided a free parse and billed nothing: I30 still wants its attempt on the bill."""
    _decided(project, ("file:///a", "v1", "done", "dA"), ("file:///b", "v2", "done", "dC"))
    code, out, err = _run(["--run", "r1", "--verify"], project)
    assert code == 70
    assert out.splitlines()[-2] == (
        "verify: run r1: every finished decided work row has a spend row  FAIL"
    )
    assert err.splitlines() == [
        "ow: OW-R-031: run r1 does not reconcile (I30): 1 finished work row(s) name a decision "
        "and have no spend row",
        "  fix: ow cost --run r1 --by driver",
    ]


def test_verify_counts_only_finished_rows_of_the_runs_generation(project: Path) -> None:
    """A failed attempt need not be billed, and dE is generation 2's, not r1's."""
    _decided(
        project,
        ("file:///a", "v1", "failed_permanent", "dC"),
        ("file:///b", "v2", "pending", "dD"),
        ("file:///c", "v3", "done", "dE"),
    )
    assert _run(["--run", "r1", "--verify"], project)[0] == 0
    assert (_unspent(project, 1), _unspent(project, 2)) == (0, 0)
    _decided(project, ("file:///c", "v4", "done", "dD"))
    assert (_unspent(project, 1), _unspent(project, 2)) == (1, 0)


def _unspent(project: Path, generation: int) -> int:
    connection = store_sqlite.connect_readonly(project / ".omniweave" / "index.owstore")
    try:
        return unspent(connection, generation)
    finally:
        connection.close()


def test_verify_fails_a_bill_its_manifest_disagrees_with(project: Path) -> None:
    (project / "runs" / "r1.json").write_bytes(b'{"cost": {"billed_micros": 2400}}')
    code, out, err = _run(["--run", "r1", "--verify"], project)
    assert code == 70
    assert out.splitlines()[-3] == "verify: run r1: Σ route_spend.micros == manifest billed  FAIL"
    assert "Σ route_spend.micros 2,500 != manifest.cost.billed_micros 2,400" in err


def test_verify_fails_a_run_with_no_manifest_to_check_against(project: Path) -> None:
    code, out, err = _run(["--run", "r2", "--verify"], project)
    assert code == 70
    assert out.splitlines()[-3] == "verify: run r2: Σ route_spend.micros == manifest billed  FAIL"
    assert "its manifest does not read, so the bill cannot be checked against it" in err


def test_verify_without_a_run_checks_the_latest(project: Path) -> None:
    code, out, _ = _run(["--verify"], project)
    assert code == 70
    assert "window: run r2's generation" in out.splitlines()
    assert out.splitlines()[-3].startswith("verify: run r2: ")


def test_verify_beside_render_json_prints_one_object(project: Path) -> None:
    """Ruling 4's one object: the report when the run reconciles, the error when it does not."""
    _decided(project, ("file:///a", "v1", "done", "dA"))
    code, out, _ = _run(["--run", "r1", "--verify", "--render", "json"], project)
    assert code == 0
    assert json.loads(out)["run_id"] == "r1"
    code, out, _ = _run(["--run", "r2", "--verify", "--render", "json"], project)
    assert code == 70
    [line] = out.splitlines()
    assert json.loads(line)["error"]["code"] == verb.UNRECONCILED


@pytest.mark.usefixtures("now")
def test_verify_is_a_runs_and_not_a_windows(project: Path) -> None:
    code, out, err = _run(["--verify", "--since", "7d"], project)
    assert (code, out) == (1, "")
    assert "--verify checks a run, and --since is not one; give --run R" in err


def test_verify_with_no_run_in_the_store_is_not_found(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    code, out, err = _run(["--verify"], tmp_path)
    assert (code, out) == (2, "")
    assert "corpus 'handbook' has no run to verify" in err


def test_the_latest_run_is_the_highest_generation(project: Path) -> None:
    connection = store_sqlite.connect_readonly(project / ".omniweave" / "index.owstore")
    try:
        assert latest_run(connection) == "r2"
    finally:
        connection.close()
