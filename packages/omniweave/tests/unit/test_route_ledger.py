"""`omniweave.route.ledger` -- the three threshold rows, the view, and the read set on disk.

These tests open a real SQLite database and apply the committed migration set, because every claim
in this module is a claim about SQL that a mock would restate rather than check. The three that
matter most could not be made any other way:

* a `route_threshold` short one row makes `route_scoreboard.state` read `'OK'` on a slice with no
  evidence at all (05:2887), which is the silent all-clear D-12 exists to catch;
* the view's `state` moves when the policy does, which is the property that makes rows-not-binds
  worth the trouble (05:2886);
* `observations()` reads a per-decision value out of `route_evidence.payload`, so a swept payload
  costs an observation rather than silently contributing a wrong one.

The store is opened through `omniweave_core.store.sqlite.connect()` and never through an `import
sqlite3`, which INV-17 bans outside that package. That costs nothing here -- the connection object
is the same object -- and it means these tests run against 07 section 2.1's pragmas in 07 section
2.1's order rather than against a bare DBAPI connection nothing in production ever opens.
"""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING

import pytest
from omniweave.route import ledger as rlg
from omniweave.route import policy as rp
from omniweave_core.errors import RouteError
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SLICE = "pdf/workiva/true/en"
"""Section 10.3's own slice (05:3162), so the numbers in these tests have a document behind them."""

_DECISION = (
    "INSERT INTO route_decision (decision_id, content_sha256, unit_part, lane, rung, "
    "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
    "rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros, "
    "admission, pinned, generation, decided_at) "
    "VALUES (?, ?, '', 'text', 1, 'p', 'b', 'h', ?, 'parse.page.olmocr', 'local_compute', "
    "'decode.part-text-unusable', 'o', ?, ?, '{}', 854, 2732, 'admitted', ?, 1, 0)"
)
_EVIDENCE = (
    "INSERT OR IGNORE INTO route_evidence (evidence_digest, payload, swept_at, first_seen_at) "
    "VALUES (?, ?, ?, 0)"
)
_QUALITY = (
    "INSERT INTO route_quality (decision_id, source, metric, agreement, created_at) "
    "VALUES (?, ?, 'norm_edit_agreement', ?, 0)"
)
_SPEND = "INSERT INTO route_spend (decision_id, attempt, micros, outcome) VALUES (?, 1, ?, 'ok')"


@pytest.fixture
def db(tmp_path: Path, migrations: Path) -> Iterator[rlg.Connection]:
    """A store with every committed migration applied, foreign keys on.

    Every migration and not only `0004_runtime.sql`, for `gate_trigger_parity`'s reason: the
    routing tables carry `REFERENCES` into each other and into the file's own earlier statements,
    and applying one file out of a dense set is the forward reference `G27(b)` exists to catch.
    """
    conn = connect(tmp_path / "index.owstore")
    for path in sorted(migrations.glob("[0-9]*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def _decide(
    db: rlg.Connection,
    decision_id: str,
    *,
    coverage: float | None,
    agreements: tuple[tuple[str, float | None], ...],
    micros: int = 858,
    slice_key: str = SLICE,
    pinned: int = 0,
    swept: bool = False,
) -> None:
    """One decision with its evidence, its quality rows and its spend. The whole fixture shape.

    `coverage` is `ink.coverage`'s value in the decision's read set -- the one signal these tests
    fit on. `None` writes a read set that never reached the key, which is `Log.unread`'s case;
    `swept = True` writes the NULL payload the 30-day sweep leaves behind.
    """
    read_set = [("decode.line_count", "1", 84), ("garble.score", "1", 0.03)]
    if coverage is not None:
        read_set.append(("ink.coverage", "1", coverage))
    payload = rlg.payload_bytes(read_set)  # type: ignore[arg-type]
    digest = f"ev_{decision_id}"
    db.execute(_EVIDENCE, (digest, None if swept else payload, 1 if swept else None))
    db.execute(_DECISION, (decision_id, decision_id, decision_id, slice_key, digest, pinned))
    for source, agreement in agreements:
        db.execute(_QUALITY, (decision_id, source, agreement))
    db.execute(_SPEND, (decision_id, micros))


def _policy(**audit: object) -> rp.RoutePolicy:
    """The shipped policy, optionally with its `[audit]` block overridden."""
    policy = rp.compile_policy([rp.builtin_layer()], registry=None)
    if not audit:
        return policy
    merged = dict(policy.audit)
    for key, value in audit.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return rp.RoutePolicy(
        rules=policy.rules,
        thresholds=policy.thresholds,
        audit=merged,
        slice_by=policy.slice_by,
        max_slices=policy.max_slices,
        policy_digest=policy.policy_digest,
    )


# --------------------------------------------------------------------------------------------
# 1. The three rows, and the install that is all of them or none.
# --------------------------------------------------------------------------------------------


def test_the_shipped_audit_block_yields_the_three_rows_the_plan_prints() -> None:
    """05:2898, verbatim: `'audit.min_audit_n'  30`, `'audit.regress_at'  0.08`,
    `'audit.release_at'  0.048`."""
    assert rlg.threshold_rows(_policy()) == (
        ("audit.min_audit_n", 30.0),
        ("audit.regress_at", 0.08),
        ("audit.release_at", 0.048),
    )


@pytest.mark.parametrize("missing", rlg.AUDIT_FIELDS)
def test_a_missing_audit_field_refuses_before_a_single_row_is_written(
    db: rlg.Connection, missing: str
) -> None:
    """All-or-none without a rollback path: `threshold_rows()` raises before the first INSERT."""
    with pytest.raises(RouteError, match=missing):
        rlg.install_thresholds(db, _policy(**{missing: None}))
    assert rlg.thresholds(db) == {}


def test_a_release_point_at_or_above_the_regress_point_is_refused() -> None:
    """A slice REGRESSED and released at the same divergence is not hysteresis (05:2974)."""
    with pytest.raises(RouteError, match="not below regress_at"):
        rlg.threshold_rows(_policy(release_at=0.08))


def test_a_threshold_that_is_not_a_number_is_refused() -> None:
    """`route_threshold.v` is `REAL NOT NULL`, and SQLite orders text against a number by type."""
    with pytest.raises(RouteError, match="not a number"):
        rlg.threshold_rows(_policy(regress_at="0.08"))


def test_the_install_joins_an_open_transaction_rather_than_opening_a_second(
    db: rlg.Connection,
) -> None:
    """05:2884 asks for these rows and the `policy_digest` install to be ATOMIC with each other,
    so the rows must be visible to the caller's own transaction and must not be committed by it."""
    db.execute("BEGIN IMMEDIATE")
    rlg.install_thresholds(db, _policy())
    assert db.in_transaction
    assert rlg.thresholds(db)["audit.min_audit_n"] == 30.0
    db.execute("ROLLBACK")
    assert rlg.thresholds(db) == {}


def test_the_install_is_idempotent_and_moves_a_value_the_policy_moved(
    db: rlg.Connection,
) -> None:
    """*"its `state` column still moves when the policy does"* (05:2886). The upsert is that."""
    rlg.install_thresholds(db, _policy())
    rlg.install_thresholds(db, _policy(regress_at=0.2, release_at=0.12))
    assert rlg.thresholds(db) == {
        "audit.min_audit_n": 30.0,
        "audit.regress_at": 0.2,
        "audit.release_at": 0.12,
    }


def test_missing_thresholds_names_every_absent_row(db: rlg.Connection) -> None:
    """D-12's question (15:1525), answered as a list rather than a boolean."""
    assert rlg.missing_thresholds(db) == rlg.THRESHOLD_KEYS
    db.execute("INSERT INTO route_threshold (k, v) VALUES ('audit.min_audit_n', 30)")
    assert rlg.missing_thresholds(db) == ("audit.regress_at", "audit.release_at")


# --------------------------------------------------------------------------------------------
# 2. The view: the silent all-clear, and the state that moves.
# --------------------------------------------------------------------------------------------


def test_a_missing_threshold_row_makes_every_slice_read_ok(db: rlg.Connection) -> None:
    """05:2887, run rather than quoted: *"A missing threshold row makes the comparison NULL, which
    falls through to `'OK'`"*.

    This is the whole reason the install is all-or-refuse, and it is the one property in this file
    that a reader would not believe without seeing it: the slice below has ONE audited decision
    against a `min_audit_n` of thirty, which is the definition of `UNKNOWN`, and with the row
    absent the view calls it `OK`.
    """
    _decide(db, "d1", coverage=0.11, agreements=(("audit", 0.94),))
    assert rlg.scoreboard(db)[0].state == "OK"
    rlg.install_thresholds(db, _policy())
    assert rlg.scoreboard(db)[0].state == "UNKNOWN"


def test_the_state_moves_when_the_policy_does(db: rlg.Connection) -> None:
    """One decision, three states, one view text. `min_audit_n` and `regress_at` are the knobs."""
    _decide(db, "d1", coverage=0.11, agreements=(("audit", 0.5),))
    rlg.install_thresholds(db, _policy())
    assert rlg.scoreboard(db)[0].state == "UNKNOWN"
    rlg.install_thresholds(db, _policy(min_audit_n=1))
    assert rlg.scoreboard(db)[0].state == "REGRESSED"
    rlg.install_thresholds(db, _policy(min_audit_n=1, regress_at=0.9, release_at=0.54))
    assert rlg.scoreboard(db)[0].state == "OK"


def test_a_decision_whose_only_quality_row_is_self_stays_in_the_population(
    db: rlg.Connection,
) -> None:
    """The view's property 2 (05:2940), as a number: `self` is filtered inside `q`, so the decision
    keeps its place in `decisions_n` and its `micros` in the bill. RT12."""
    _decide(db, "d1", coverage=0.11, agreements=(("self", 0.9),), micros=858)
    rlg.install_thresholds(db, _policy())
    row = rlg.scoreboard(db)[0]
    assert (row.decisions_n, row.audited_n, row.micros) == (1, 0, 858)
    assert row.divergence is None


def test_a_pinned_decision_is_excluded(db: rlg.Connection) -> None:
    """*"a pinned decision may not justify a demotion"* (05:2946)."""
    _decide(db, "d1", coverage=0.11, agreements=(("audit", 0.5),), pinned=1)
    rlg.install_thresholds(db, _policy())
    assert rlg.scoreboard(db) == ()


def test_the_two_one_to_many_children_do_not_multiply_each_other(
    db: rlg.Connection,
) -> None:
    """The view's property 1 (05:2934). Four quality rows and one spend row on one decision: the
    naive two-`LEFT JOIN` form reports `micros` four times over and `audited_n` once per attempt."""
    _decide(
        db,
        "d1",
        coverage=0.11,
        agreements=(("agree", 0.9), ("audit", 0.9), ("feedback", None), ("self", 0.5)),
        micros=858,
    )
    db.execute(
        "INSERT INTO route_spend (decision_id, attempt, micros, outcome) "
        "VALUES ('d1', 2, 858, 'ok')"
    )
    rlg.install_thresholds(db, _policy(min_audit_n=1))
    row = rlg.scoreboard(db)[0]
    assert row.audited_n == 1
    assert row.micros == 858 * 2


# --------------------------------------------------------------------------------------------
# 3. The read set on disk.
# --------------------------------------------------------------------------------------------


def test_the_payload_round_trips_through_deflate_and_canonical_json() -> None:
    triples = [("ink.coverage", "1", 0.11), ("decode.line_count", "1", 84)]
    assert rlg.read_set_from(rlg.payload_bytes(triples)) == {
        "ink.coverage": 0.11,
        "decode.line_count": 84,
    }


def test_a_payload_that_is_not_the_read_set_is_refused() -> None:
    with pytest.raises(RouteError, match="not the read set"):
        rlg.read_set_from(zlib.compress(b'{"ink.coverage": 0.11}'))
    with pytest.raises(RouteError, match="not a \\[key, version, value\\] triple"):
        rlg.read_set_from(zlib.compress(b'[["ink.coverage", 0.11]]'))


def test_observations_read_the_value_the_decision_read(db: rlg.Connection) -> None:
    """One observation per decision, with the label averaged over its `agree` and `audit` rows."""
    _decide(db, "d1", coverage=0.11, agreements=(("agree", 0.94), ("audit", 0.90)), micros=858)
    log = rlg.observations(db, slice_key=SLICE, signal="ink.coverage")
    assert log.n == 1
    one = log.observations[0]
    assert one.signal == 0.11
    assert one.micros == 858
    assert one.divergence == pytest.approx((0.06 + 0.10) / 2)


def test_a_swept_payload_costs_an_observation_and_is_counted(db: rlg.Connection) -> None:
    """05:3009 ages evidence blobs out at 30 days and decision rows at 400, so a propose run over a
    year-old log fits over the last thirty days of it. The count is what stops that being silent."""
    _decide(db, "live", coverage=0.11, agreements=(("agree", 0.94),))
    _decide(db, "gone", coverage=0.11, agreements=(("agree", 0.94),), swept=True)
    log = rlg.observations(db, slice_key=SLICE, signal="ink.coverage")
    assert (log.n, log.swept, log.unread) == (1, 1, 0)
    assert "1 dropped for a swept payload" in log.render()


def test_a_read_set_that_never_reached_the_signal_is_counted_separately(
    db: rlg.Connection,
) -> None:
    """Different from swept, and the difference is actionable: the key was never computed for this
    decision, which is the demand plan's business rather than the sweep's."""
    _decide(db, "d1", coverage=None, agreements=(("agree", 0.94),))
    log = rlg.observations(db, slice_key=SLICE, signal="ink.coverage")
    assert (log.n, log.swept, log.unread) == (0, 0, 1)


def test_observations_exclude_pinned_decisions_and_other_slices(db: rlg.Connection) -> None:
    _decide(db, "mine", coverage=0.11, agreements=(("agree", 0.94),))
    _decide(db, "pinned", coverage=0.11, agreements=(("agree", 0.94),), pinned=1)
    _decide(db, "other", coverage=0.11, agreements=(("agree", 0.94),), slice_key="docx/x/true/en")
    log = rlg.observations(db, slice_key=SLICE, signal="ink.coverage")
    assert [one.decision_id for one in log.observations] == ["mine"]


def test_a_decision_with_no_agree_or_audit_row_is_not_an_observation(
    db: rlg.Connection,
) -> None:
    """05:2990's label is `1 - agree.decode_vs_page` *"on the decisions that escalated"*. A
    decision with only a `self` row has no label, and a fit over a label it invented is the one
    thing a human-in-the-loop command may never produce."""
    _decide(db, "d1", coverage=0.11, agreements=(("self", 0.94),))
    assert rlg.observations(db, slice_key=SLICE, signal="ink.coverage").n == 0
