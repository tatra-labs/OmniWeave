"""`tools/gate_trigger_parity.py`'s own tests: every disagreement it exists to catch.

The gate's subject is two enforcers agreeing, so **a gate that cannot report a disagreement is
worse than no gate** -- it would go green on a tree where the trigger had been dropped, and RT8
(05:3348), which calls the compiler's rejection *"CI parity for the charter's
`route_decision_monotone` trigger rather than a second opinion"*, would be a comment rather than a
property. So the committed
migration set is asserted green once, and then four mutations of the trigger are each asserted red:

* the trigger DROPPED -- the compiler still rejects 28 pairs and nothing in the store does;
* `<` for `<=` -- the seven equal-rung pairs, where a child at its parent's rung is monotone to one
  enforcer and not to the other. The narrowest possible mutation, and the one a careless edit makes;
* the `WHEN` guard inverted -- a first decision, which has no parent, rejected at every rung. The
  pairs go red too, because a pair's parent row is itself a root, and every one of those findings
  names the wrong row: the root check is what says which insert actually failed;
* `>=` for `<=` -- rejects one rung too many in the other direction.

The gate lives in `tools/` and is a script rather than a distribution, so it is loaded by path with
`spec_from_file_location`, exactly as `test_gate_migrations.py` loads its own subject.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from io import StringIO
from pathlib import Path

import pytest
from omniweave.route.rung import Rung
from omniweave_core.errors import RouteError


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_trigger_parity.py"

_SPEC = importlib.util.spec_from_file_location("omniweave_gate_trigger_parity", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - the file is in this repository
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


_MUTATIONS = {
    "strict": "NEW.rung < (SELECT rung FROM route_decision WHERE decision_id "
    "= NEW.parent_decision_id)",
    "loose": "NEW.rung <= 1 + (SELECT rung FROM route_decision WHERE decision_id "
    "= NEW.parent_decision_id)",
}
"""Two comparison mutations, written as the operator a careless edit would leave behind.

`strict` accepts a child at its parent's own rung, which INV-13's `child.rung > parent.rung`
forbids and the compiler's `OW-P-005` rejects -- seven pairs. `loose` rejects a child one rung
above its parent, which both enforcers must accept -- six more."""


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    """The committed migrations applied to a scratch file. Closed by the test that opened it."""
    connection = sqlite3.connect(tmp_path / "parity.sqlite3")
    gate._apply(connection)
    return connection


def _remutate(connection: sqlite3.Connection, when: str | None) -> None:
    """Drop `route_decision_monotone` and put back a mutant, or nothing at all."""
    connection.executescript(f"DROP TRIGGER {gate.TRIGGER}")
    if when is None:
        return
    connection.executescript(
        f"CREATE TRIGGER {gate.TRIGGER} BEFORE INSERT ON route_decision"
        f"  WHEN {when}"
        f"  BEGIN SELECT RAISE(ABORT,'{gate.CODE_SQL} escalation is not monotone'); END"
    )


# --------------------------------------------------------------------------------------------
# 1. The committed tree.
# --------------------------------------------------------------------------------------------


def test_the_committed_migration_set_and_loader_agree_on_every_pair() -> None:
    """RT8 on this checkout. `0` and nothing else -- `2` would mean the gate did not run."""
    out = StringIO()
    assert gate.main([], writer=out) == gate.EXIT_CLEAN
    report = out.getvalue()
    assert "two enforcers, one truth (RT8)" in report
    assert f"{len(tuple(Rung)) ** 2} ordered rung pairs compared" in report


def test_both_enforcers_reject_exactly_the_twenty_eight_non_monotone_pairs(
    db: sqlite3.Connection,
) -> None:
    """INV-13 is `child.rung > parent.rung`, so over 7 x 7 pairs the rejections are the lower
    triangle INCLUDING the diagonal: 28 of 49. Asserted on both sides separately, because the
    parity check alone would pass if both enforcers were wrong in the same way."""
    try:
        by_trigger = {
            (parent, child)
            for parent in Rung
            for child in Rung
            if gate.trigger_verdict(db, int(parent), int(child)).rejected
        }
    finally:
        db.close()
    by_compiler = {
        (parent, child)
        for parent in Rung
        for child in Rung
        if gate.compiler_verdict(parent.name, child.name).rejected
    }
    expected = {(parent, child) for parent in Rung for child in Rung if int(child) <= int(parent)}
    assert len(expected) == 28
    assert by_trigger == expected
    assert by_compiler == expected


def test_this_sqlite_refuses_a_subquery_in_a_check(db: sqlite3.Connection) -> None:
    """05:2705's parenthetical, measured rather than quoted: *"subqueries prohibited in CHECK
    constraints (verified on SQLite 3.45.1), so the DDL that tried was unrunnable."* If this ever
    passed, the reason the trigger exists would have stopped being true."""
    try:
        verdict = gate.check_refuses_subquery(db)
    finally:
        db.close()
    assert verdict.rejected is True
    assert "subquer" in verdict.detail.lower()


def test_the_skip_rungs_half_is_reported_with_no_trigger_column() -> None:
    """RT8 names two compiler rejections and only one has a row to reject: skipping a rung writes
    nothing, so there is no `INSERT` for a trigger to see. Reporting it anyway is what keeps a
    reader from believing this gate covers all of RT8."""
    matrix = gate.skip_rungs_matrix(tuple(Rung))
    assert len(matrix) == 49
    assert sum(1 for *_, rejected in matrix if rejected) == 28
    out = StringIO()
    gate.main(["--verbose"], writer=out)
    assert "no trigger counterpart" in out.getvalue()


# --------------------------------------------------------------------------------------------
# 2. The mutations. Each must be red, and each for its own reason.
# --------------------------------------------------------------------------------------------


def test_a_dropped_trigger_is_twenty_eight_disagreements(db: sqlite3.Connection) -> None:
    """The failure the gate exists for: the compiler still rejects and nothing in the store does,
    so a writer that does not go through `load_layer()` can put a non-monotone chain in the
    database and `ow why` will explain a chain INV-13 says cannot exist."""
    try:
        _remutate(db, None)
        findings, pairs = gate.parity(db)
    finally:
        db.close()
    assert pairs == 49
    disagreements = [f for f in findings if f.clause == "escalate_to"]
    assert len(disagreements) == 28
    assert all("accepts the row" in f.detail for f in disagreements)


def test_a_strict_less_than_disagrees_on_exactly_the_seven_equal_rung_pairs(
    db: sqlite3.Connection,
) -> None:
    """The narrowest mutation there is, and the one that is easiest to argue into: a child at its
    parent's OWN rung is not an escalation, and `<` lets it in. RT8 says *"at or below"*."""
    try:
        _remutate(db, _MUTATIONS["strict"])
        findings, _ = gate.parity(db)
    finally:
        db.close()
    disagreements = [f for f in findings if f.clause == "escalate_to"]
    assert [f.where for f in disagreements] == [f"{rung.name} -> {rung.name}" for rung in Rung]


def test_a_loose_comparison_rejects_six_pairs_both_enforcers_must_accept(
    db: sqlite3.Connection,
) -> None:
    """The other direction: a child exactly one rung above its parent is the ordinary escalation,
    and rejecting it would fail every `DECODE -> PAGE` insert in section 10.1's trace."""
    try:
        _remutate(db, _MUTATIONS["loose"])
        findings, _ = gate.parity(db)
    finally:
        db.close()
    disagreements = [f for f in findings if f.clause == "escalate_to"]
    assert len(disagreements) == 6
    assert all("rejects the row" in f.detail for f in disagreements)


def test_an_inverted_when_guard_makes_every_pair_lie_and_the_root_check_says_why(
    db: sqlite3.Connection,
) -> None:
    """Property 1 earning its place -- by localising, not by catching something the pairs cannot.

    With the guard inverted the trigger fires on rows that have NO parent. A pair probe inserts a
    parent first and that parent IS a root, so every pair now fails at the parent row: the parity
    matrix reports 21 disagreements, all of them naming the child and none of them true. The seven
    root findings are the ones that say which insert actually failed.
    """
    try:
        _remutate(db, "NEW.parent_decision_id IS NULL")
        findings, _ = gate.parity(db)
    finally:
        db.close()
    clauses = [f.clause for f in findings]
    assert clauses.count("root") == len(tuple(Rung))
    assert clauses.count("escalate_to") == 49 - 28
    assert [f.where for f in findings if f.clause == "root"] == [rung.name for rung in Rung]
    assert all("no parent" in f.detail for f in findings if f.clause == "root")


# --------------------------------------------------------------------------------------------
# 3. What the gate refuses to call a verdict.
# --------------------------------------------------------------------------------------------


def test_an_integrity_error_that_is_not_the_code_is_not_a_rejection() -> None:
    """A `NOT NULL` the probe forgot, or a `CHECK` on a neighbouring column, would otherwise be
    reported as the trigger firing -- and the gate would go green on the pairs where the trigger is
    supposed to fire while measuring nothing at all."""
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        gate._integrity(sqlite3.IntegrityError("UNIQUE constraint failed"))
    assert gate._integrity(
        sqlite3.IntegrityError(f"{gate.CODE_SQL} escalation is not monotone")
    ).rejected


def test_a_route_error_that_is_not_ow_p_005_propagates() -> None:
    """Same discipline on the compiler side: a malformed probe policy is a broken fixture, not a
    verdict about the pair."""
    with pytest.raises(RouteError):
        gate.compiler_verdict("DECODE", "NOT_A_RUNG")


def test_a_missing_migration_directory_is_not_run_rather_than_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`2` and not `0`. A gate that reported a pass on a tree it could not read would be the
    quietest possible way for RT8 to stop being enforced."""
    monkeypatch.setattr(gate, "MIGRATIONS", tmp_path / "nowhere")
    out = StringIO()
    assert gate.main([], writer=out) == gate.EXIT_NOT_RUN
    assert "NOT RUN" in out.getvalue()
