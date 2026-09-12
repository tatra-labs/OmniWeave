"""`omniweave_core.work` — the failure ladder, the three tiers, and the one home rule.

08-runtime.md section 1.6 is the subject and it is almost entirely a table: thirteen
`FailureClass` members against a verdict, a first cooldown and a side effect, plus a three-tier
classifier and an escalation ladder that overrides it after the first attempt. So most of this
file is parity — `LADDER` against the plan's printed rows, `ESCALATION_MS` against LDR's
`compute_retry_cooldown` as the plan quotes it — and the rest is the two decisions the table does
not make for itself.

**The two decisions.** `timeout` has two rows that disagree on the verdict (08:566-567), and the
selector is `Failure.source`, which `classify()`'s printed signature does not take; and tier 3
ships with an empty table on purpose, so the mechanism has to be tested through
`match_message()`'s own parameter rather than through the shipped constant. Both are argued in
`work.py`'s docstrings and both are asserted here, because an argument in a docstring that no test
can fail is a comment.

## What is NOT here, and where it is

The vocabulary's plan-parity — `WORK_COLUMNS` against the shipped DDL, `WORK_STATUSES` against the
CHECK domain, `TRANSITIONS` against `OUTCOMES` — stays in `test_store_queue.py`. Those six tests
compare a constant against a REAL migrated store, which needs the `owstore` fixture and the
migration runner, and the thing they would catch is a DDL drift. The names moved to
`omniweave_core.work` with P4 W4.1; the assertions did not follow, because a test belongs with the
machinery it needs and not with the module it names. `test_the_work_vocabulary_has_exactly_one_home`
below is the pointer a reader needs in the other direction.

Specified in 08-runtime.md section 1.6 (:533-608), 02-architecture.md section 2 row 22, and
16-roadmap.md:541 (P4 W4.1).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from omniweave_core import work
from omniweave_core.errors import DriverHostError, StoreError
from omniweave_core.work import (
    ESCALATION_MS,
    LADDER,
    MAX_WORK_ATTEMPTS,
    RATE_LIMIT_COOLDOWN_MS,
    TIMEOUT_FROM_HOST,
    UNCLASSIFIED_COOLDOWN_MS,
    Failure,
    FailureClass,
    Scope,
    Source,
    Verdict,
    classify,
    escalate,
    match_message,
    rate_limit_cooldown_ms,
    rung_for,
)

SOURCE = Path(work.__file__)
QUEUE = SOURCE.parent / "store" / "queue.py"

ONE_DAY_MS = 86_400_000
THIRTY_DAYS_MS = 2_592_000_000


class BoomError(Exception):
    """A driver's own exception: anything that is not a `DriverHostError`."""


class RetryAfterError(Exception):
    """A `DriverError`-shaped carrier for the one attribute `classify()` reads off an exception.

    A real `DriverError` would do, and a stand-in is used on purpose: `classify()` reaches for
    `retry_after_ms` with `getattr` rather than an isinstance check, so the test that proves the
    channel works should not be the one that also proves `DriverError` has the attribute.
    """

    def __init__(self, message: str, retry_after_ms: int) -> None:
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


# ---------------------------------------------------------------------------
# the ladder table
# ---------------------------------------------------------------------------


def test_the_ladder_has_a_rung_for_every_failure_class_and_no_other_key() -> None:
    """Thirteen members, thirteen keys. A fourteenth class with no rung is unclassifiable.

    `FailureClass` is frozen at the end of P3 (16-roadmap.md:498), so this is not a moving target
    — which is exactly why the ladder may be a total function over it rather than a mapping with
    a fallback.
    """
    assert set(LADDER) == {member.value for member in FailureClass}
    assert len(LADDER) == 13


@pytest.mark.parametrize(
    ("failure_class", "verdict", "cooldown_ms"),
    [
        ("encrypted", Verdict.PERMANENT, None),
        ("unsupported_format", Verdict.PERMANENT, None),
        ("corrupt_input", Verdict.PERMANENT, None),
        ("empty_result", Verdict.PERMANENT, None),
        ("auth", Verdict.PERMANENT, None),
        ("too_large", Verdict.PERMANENT, None),
        ("driver_bug", Verdict.PERMANENT, None),
        ("needs_ocr", Verdict.NOT_A_FAILURE, None),
        ("rate_limited", Verdict.TRANSIENT, None),
        ("upstream_unavailable", Verdict.TRANSIENT, 300_000),
        ("timeout", Verdict.TRANSIENT, 1_800_000),
        ("resource_limit", Verdict.TRANSIENT, 60_000),
        ("driver_crashed", Verdict.PERMANENT, None),
    ],
)
def test_each_rung_is_the_row_the_plan_prints(
    failure_class: str, verdict: Verdict, cooldown_ms: int | None
) -> None:
    """08:558-570, cell by cell. `rate_limited`'s cooldown is `None` because it is a function."""
    rung = LADDER[failure_class]
    assert rung.verdict is verdict
    assert rung.first_cooldown_ms == cooldown_ms


def test_only_the_transient_rows_carry_a_cooldown_and_rate_limited_is_the_exception() -> None:
    """A permanent row with a cooldown would be a retry nothing will ever make.

    `rate_limited` is transient and carries `None` on purpose: 08:564 makes its first cooldown
    *"the driver's `retry_after_ms` if present, else `RATE_LIMIT_COOLDOWN_MS[provider]`"*, so a
    number here would be wrong for every provider that is not the default.
    """
    for name, rung in LADDER.items():
        if rung.verdict is Verdict.TRANSIENT:
            assert (rung.first_cooldown_ms is None) == (name == "rate_limited"), name
        else:
            assert rung.first_cooldown_ms is None, name


def test_the_two_timeout_rows_disagree_and_the_source_is_what_selects() -> None:
    """08:572-576 — *"the one place two plan documents could have contradicted each other"*.

    A host-detected deadline is `FAILED_PERMANENT{TIMEOUT}` because the host killed a process that
    produced nothing and *"a driver that hangs on this input hangs on it again"*; a driver-reported
    timeout is transient because the driver watched a remote peer being slow.
    """
    assert LADDER["timeout"].verdict is Verdict.TRANSIENT
    assert TIMEOUT_FROM_HOST.verdict is Verdict.PERMANENT
    assert rung_for("timeout", Source.DRIVER) is LADDER["timeout"]
    assert rung_for("timeout", Source.HOST) is TIMEOUT_FROM_HOST
    assert rung_for("resource_limit", Source.HOST) is LADDER["resource_limit"]


def test_the_three_rows_with_a_side_effect_carry_it() -> None:
    """The plan's fifth column is what `run/dispatch.py` (W4.7) has to implement, so it is data.

    A table that dropped it would leave three behaviours — re-queue at a finer grain, halve the
    batch, retry once at `batch = 1` — to be re-derived from prose by whoever writes the loop.
    """
    assert "part-granularity" in LADDER["too_large"].side_effect
    assert "batch // 2" in LADDER["resource_limit"].side_effect
    assert "batch = 1" in LADDER["driver_crashed"].side_effect
    assert "NOT shrink" in LADDER["rate_limited"].side_effect


def test_the_scope_qualifiers_are_the_plans_own_three() -> None:
    """08:561, :569 and tier 2's 404 row each narrow "permanent" and each narrows it differently."""
    assert LADDER["too_large"].scope is Scope.OPERATOR
    assert LADDER["driver_crashed"].scope is Scope.UNIT
    assert LADDER["encrypted"].scope is Scope.ROW
    assert classify(None, BoomError("gone"), "acme", 404).scope is Scope.LOCATOR


def test_driver_crashed_is_host_sourced_in_the_table_itself() -> None:
    """A driver cannot report its own death; the host synthesises it from an exit status."""
    assert LADDER["driver_crashed"].source == "host"


def test_the_ladder_is_the_plans_table_read_out_of_the_document(plan) -> None:
    """Parity against 08:558-570, parsed rather than grepped name by name.

    A grep per class would pass on a fourteenth row the document added and this file omitted,
    which is the direction that matters: the table is the specification, and the risk is the plan
    gaining a row rather than this file inventing one.
    """
    plan.require()
    covered: set[str] = set()
    verdicts: dict[str, set[str]] = {}
    for line in plan.lines("08-runtime.md"):
        if not line.startswith("| `") or line.count("|") < 6:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        names = re.findall(r"`([a-z_]+)`", cells[0])
        # The verdict cell is never bare: three rows narrow it ("permanent **for this operator**",
        # "permanent **for this unit**") and one negates it ("**not a failure**"), which is why the
        # match is a containment rather than an equality. Collapsing those to "permanent" here
        # would be this test agreeing with a table it had first flattened.
        word = next((w for w in ("not a failure", "permanent", "transient") if w in cells[2]), None)
        if not names or word is None:
            continue
        covered.update(names)
        for name in names:
            verdicts.setdefault(name, set()).add(word)
    assert covered == set(LADDER), covered.symmetric_difference(set(LADDER))
    assert verdicts["timeout"] == {"permanent", "transient"}, "08:566-567's two rows"
    for name, rung in LADDER.items():
        if name == "timeout":
            continue
        expected = {"not a failure"} if rung.verdict is Verdict.NOT_A_FAILURE else {rung.verdict}
        assert verdicts[name] == {str(v) for v in expected}, name


# ---------------------------------------------------------------------------
# tier 1 — a structured FailureClass from the driver wins
# ---------------------------------------------------------------------------


def test_a_declared_class_wins_over_a_status_code() -> None:
    """08:543 — *"A structured `FailureClass` from the driver wins ... and it is believed."*

    The status code below would give `auth` at tier 2. The declared class is `corrupt_input`, and
    a classifier that let an HTTP code override a driver's own word would be LDR's failure mode
    with the tiers inverted.
    """
    failure = classify(FailureClass.CORRUPT_INPUT, BoomError("bad bytes"), "acme", 401)
    assert failure.failure_class == "corrupt_input"
    assert failure.tier == 1
    assert failure.verdict is Verdict.PERMANENT


def test_a_declared_class_outside_the_thirteen_is_a_raise_and_not_a_guess() -> None:
    with pytest.raises(StoreError, match="thirteen FailureClass"):
        classify("exploded", BoomError("x"), "acme", None)


def test_a_declared_rate_limit_uses_the_providers_cooldown() -> None:
    failure = classify(FailureClass.RATE_LIMITED, BoomError("slow down"), "acme", None)
    assert failure.cooldown_ms == RATE_LIMIT_COOLDOWN_MS["default"]


def test_a_retry_after_on_the_exception_overrides_the_provider_table() -> None:
    """08:588 — *"A `Retry-After` header always overrides both."*

    It reaches `classify()` as `DriverError.retry_after_ms`, which is the only channel: the
    printed signature has no parameter for it, and `exc` is the argument that carries it.
    """
    failure = classify(FailureClass.RATE_LIMITED, RetryAfterError("429", 5_000), "acme", None)
    assert failure.cooldown_ms == 5_000


def test_a_driver_timeout_is_transient_and_a_host_timeout_is_permanent() -> None:
    driver = classify(FailureClass.TIMEOUT, BoomError("peer was slow"), "acme", None)
    assert (driver.source, driver.verdict, driver.cooldown_ms) == (
        Source.DRIVER,
        Verdict.TRANSIENT,
        1_800_000,
    )
    host = classify(
        FailureClass.TIMEOUT,
        DriverHostError("progress_ms elapsed", fix="raise [isolation] progress_ms"),
        "acme",
        None,
    )
    assert (host.source, host.verdict, host.cooldown_ms) == (Source.HOST, Verdict.PERMANENT, None)


def test_driver_crashed_is_host_sourced_whichever_exception_carries_it() -> None:
    """`HostVerdict.as_error` builds a real `DriverError` for a crash, so the exception type alone
    would read it as the driver's. The table fixes the source for this one class."""
    failure = classify(FailureClass.DRIVER_CRASHED, BoomError("exit -11"), "acme", None)
    assert failure.source is Source.HOST
    assert failure.scope is Scope.UNIT


def test_needs_ocr_is_not_a_failure_and_has_no_outcome() -> None:
    """02-architecture.md section 7.1 and 08:563: it is routing data, so neither verdict fits."""
    failure = classify(FailureClass.NEEDS_OCR, BoomError("scanned"), "acme", None)
    assert failure.verdict is Verdict.NOT_A_FAILURE
    with pytest.raises(StoreError, match="routing data"):
        _ = failure.outcome


# ---------------------------------------------------------------------------
# tier 2 — the status code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "failure_class", "verdict", "scope"),
    [
        (401, "auth", Verdict.PERMANENT, Scope.ROW),
        (403, "auth", Verdict.PERMANENT, Scope.ROW),
        (404, "upstream_unavailable", Verdict.PERMANENT, Scope.LOCATOR),
        (410, "upstream_unavailable", Verdict.PERMANENT, Scope.LOCATOR),
        (429, "rate_limited", Verdict.TRANSIENT, Scope.ROW),
        (500, "upstream_unavailable", Verdict.TRANSIENT, Scope.ROW),
        (503, "upstream_unavailable", Verdict.TRANSIENT, Scope.ROW),
        (599, "upstream_unavailable", Verdict.TRANSIENT, Scope.ROW),
    ],
)
def test_the_status_code_table_is_08_545s(
    status: int, failure_class: str, verdict: Verdict, scope: Scope
) -> None:
    failure = classify(None, BoomError("no class"), "acme", status)
    assert (failure.failure_class, failure.verdict, failure.scope) == (
        failure_class,
        verdict,
        scope,
    )
    assert failure.tier == 2


def test_a_404_is_permanent_even_though_its_class_is_transient() -> None:
    """The row overrides the class, which is why tier 2's values are triples.

    A 503 means the host is down and will be back; a 404 means this URL is not a thing. Same
    `FailureClass`, opposite verdicts, and `Scope.LOCATOR` says the narrowness out loud.
    """
    assert LADDER["upstream_unavailable"].verdict is Verdict.TRANSIENT
    assert classify(None, BoomError("gone"), "acme", 404).verdict is Verdict.PERMANENT
    assert classify(None, BoomError("down"), "acme", 503).verdict is Verdict.TRANSIENT


@pytest.mark.parametrize("status", [200, 301, 418, 499, 600, 999])
def test_a_status_code_outside_the_table_falls_through_to_tier_three(status: int) -> None:
    failure = classify(None, BoomError("odd"), "acme", status)
    assert failure.tier == 3
    assert failure.failure_class is None


# ---------------------------------------------------------------------------
# tier 3 — the message table, and only then
# ---------------------------------------------------------------------------


def test_the_shipped_message_table_is_empty_on_purpose() -> None:
    """LDR's 120 lines of substring matching is the named anti-pattern (08:552-554).

    The mechanism ships and the rows do not: every failure that reaches tier 3 today becomes
    transient at one hour with `OW-D-051` naming the raw string, which is 08:570's *"fail toward
    retryable, and report the gap"* with nothing invented in between.
    """
    assert work.MESSAGE_PATTERNS == ()


def test_an_unclassified_failure_is_transient_at_one_hour_and_names_the_gap() -> None:
    failure = classify(None, BoomError("something went wrong"), "acme", None)
    assert failure.verdict is Verdict.TRANSIENT
    assert failure.cooldown_ms == UNCLASSIFIED_COOLDOWN_MS == 3_600_000
    assert failure.diag_code == "OW-D-051"
    assert failure.message == "something went wrong"
    assert failure.outcome == "failed_transient"


def test_the_message_matcher_is_ordered_first_match_and_case_insensitive() -> None:
    """The three decisions `MESSAGE_PATTERNS`' docstring states, asserted through the parameter.

    They cannot be pinned against the shipped table because it is empty, and a decision that no
    test can fail is the shape a later row would quietly violate.
    """
    patterns = (("requires login", "auth"), ("login", "corrupt_input"))
    assert match_message("Requires Login to continue", patterns) == "auth"
    assert match_message("please login", patterns) == "corrupt_input"
    assert match_message("nothing here", patterns) is None


def test_a_tier_three_match_still_records_the_diag() -> None:
    """A matched substring is a guess that happened to land, so the gap is reported either way."""
    failure = classify(None, BoomError("the disk is full"), "acme", None)
    assert failure.diag_code == "OW-D-051"


# ---------------------------------------------------------------------------
# the source axis
# ---------------------------------------------------------------------------


def test_a_driver_host_error_is_the_hosts_and_anything_else_is_the_drivers() -> None:
    """02-architecture.md:1060 makes `DriverHostError` the one type a host-attributed fault
    travels as, which is what makes the derivation exact rather than a heuristic."""
    assert (
        classify(None, DriverHostError("framing", fix="report it"), "acme", None).source
        is Source.HOST
    )
    assert classify(None, BoomError("driver"), "acme", None).source is Source.DRIVER


def test_classify_is_pure() -> None:
    """Table-driven and clock-free: the same four arguments give the same answer every time.

    That is what lets the ladder be tested without a queue, and what keeps `cooldown_ms` an offset
    rather than a timestamp — `COMPLETE_SQL` adds it to the STORE's clock because 08:600 requires
    that *"a backward NTP step on one worker must not make a row permanently unclaimable."*
    """
    exc = BoomError("same")
    assert classify(FailureClass.TIMEOUT, exc, "acme", None) == classify(
        FailureClass.TIMEOUT, exc, "acme", None
    )


def test_a_failure_maps_to_the_outcome_its_verdict_names() -> None:
    assert classify(FailureClass.ENCRYPTED, BoomError("x"), "a", None).outcome == "failed_permanent"
    assert (
        classify(FailureClass.RESOURCE_LIMIT, BoomError("x"), "a", None).outcome
        == "failed_transient"
    )


# ---------------------------------------------------------------------------
# the rate-limit cooldown
# ---------------------------------------------------------------------------


def test_the_shipped_cooldown_table_is_the_plans_single_row() -> None:
    """08:584 prints exactly `{"default": 3_600_000}`; the spread LDR needs is the override's."""
    assert dict(RATE_LIMIT_COOLDOWN_MS) == {"default": 3_600_000}


def test_the_cooldown_precedence_is_retry_after_then_provider_then_default() -> None:
    overrides = {"default": 3_600_000, "arxiv": 21_600_000}
    assert rate_limit_cooldown_ms("arxiv", 500, overrides) == 500
    assert rate_limit_cooldown_ms("arxiv", None, overrides) == 21_600_000
    assert rate_limit_cooldown_ms("unknown", None, overrides) == 3_600_000
    assert rate_limit_cooldown_ms("unknown") == 3_600_000


# ---------------------------------------------------------------------------
# the escalation ladder
# ---------------------------------------------------------------------------


def test_the_escalation_ladder_is_ldrs_compute_retry_cooldown() -> None:
    """08:591-592 quotes it verbatim: classifier -> 1 day -> 30 days -> 30 days -> PERMANENT."""
    assert ESCALATION_MS == (None, ONE_DAY_MS, THIRTY_DAYS_MS, THIRTY_DAYS_MS)


@pytest.mark.parametrize(
    ("attempts_total", "expected"),
    [
        (1, 60_000),
        (2, ONE_DAY_MS),
        (3, THIRTY_DAYS_MS),
        (4, THIRTY_DAYS_MS),
        (5, None),
        (6, None),
    ],
)
def test_the_first_attempt_uses_the_classifier_and_the_rest_use_the_ladder(
    attempts_total: int, expected: int | None
) -> None:
    """*"The classifier's cooldown governs the FIRST attempt only; after that, repeated failure is
    itself the evidence."* 60,000 ms is `resource_limit`'s, standing in for any classifier."""
    assert escalate(attempts_total, 60_000) == expected


def test_the_ladder_runs_out_exactly_where_the_claim_predicate_does() -> None:
    """`attempts_total < 5` is the claim's clause, so there is no rung after the fifth attempt.

    Four entries against a ceiling of five is not an off-by-one: a cooldown is the wait BEFORE the
    next attempt, and attempt five needs no wait after it.
    """
    assert len(ESCALATION_MS) == MAX_WORK_ATTEMPTS - 1
    assert escalate(MAX_WORK_ATTEMPTS - 1, 60_000) is not None
    assert escalate(MAX_WORK_ATTEMPTS, 60_000) is None


def test_escalate_refuses_an_attempt_count_below_one() -> None:
    """The claim increments before the attempt runs, so the first failure arrives at 1. A zero is
    a caller that read the counter from the wrong side of the claim."""
    with pytest.raises(StoreError, match="increments it before"):
        escalate(0, 60_000)


def test_a_permanent_failures_first_cooldown_is_none_and_stays_none() -> None:
    """`escalate` substitutes the classifier's number at index 0, and `None` substitutes to `None`.

    A permanent failure that acquired a one-day retry from the ladder would be a row the claim
    predicate re-offers, which is the whole thing `failed_permanent` exists to stop.
    """
    assert escalate(1, None) is None
    assert escalate(2, None) == ONE_DAY_MS


# ---------------------------------------------------------------------------
# one home
# ---------------------------------------------------------------------------


def _module_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            found.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        elif isinstance(node, ast.Assign):
            found.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return found


MOVED = (
    "WorkRow",
    "WORK_STATUSES",
    "WORK_COLUMNS",
    "OUTCOMES",
    "TRANSITIONS",
    "DECREMENTING",
    "Transition",
    "STORE_NOW_MS",
    "CLAIM_SQL",
    "COMPLETE_SQL",
    "COST_CLASS_SQL",
    "REAP_SQL",
    "REAP_RESERVATIONS_SQL",
    "COUNTS_SQL",
)


@pytest.mark.parametrize("name", MOVED)
def test_the_work_vocabulary_has_exactly_one_home(name: str) -> None:
    """A move, not a copy. `store/queue.py` defined all fifteen at P2 and now imports them.

    Its `WorkRow` docstring said what would happen: *"When `work.py` lands it takes this class
    verbatim and this one is deleted -- **not re-exported**, because 02-architecture.md:246 gives
    that module the claim/complete/reap SQL too, and a type with two homes is the failure INV-21
    names."* This asserts the second half, which is the half a refactor forgets: a re-export would
    have left every existing import working and the ownership question unanswered.

    The vocabulary's parity tests against the shipped DDL stay in `test_store_queue.py` — see this
    module's docstring for why the assertions did not follow the names.
    """
    assert name in _module_level_names(SOURCE), f"{name} is not defined in work.py"
    assert name not in _module_level_names(QUEUE), f"{name} still has a second home in queue.py"


def test_max_work_attempts_moved_to_the_module_that_owns_every_ceiling() -> None:
    """02-architecture.md:231 makes `omniweave_core.limits` the home of *"every `MAX_*` ceiling"*.

    `store/queue.py` declared it at P2 and reported the gap in its own docstring — *"this is a
    ceiling with no `limits.py` row, and INV-21 says a ceiling has exactly one home"* — with the
    required edit named. This is that edit: `work.py` imports the constant rather than declaring
    it, so the claim SQL and `limits.py` cannot disagree about how many attempts a row gets.
    """
    from omniweave_core import limits  # noqa: PLC0415 -- one test needs the module object

    assert limits.MAX_WORK_ATTEMPTS == MAX_WORK_ATTEMPTS == 5
    assert "MAX_WORK_ATTEMPTS" in limits.__all__
    assert "MAX_WORK_ATTEMPTS" not in _module_level_names(SOURCE)


def test_the_module_runs_nothing() -> None:
    """02-architecture.md:246's exclusion column: *"running the loop (L5's job)"*.

    A module that both defined the ladder and climbed it would put the runtime's scheduling policy
    inside core. The import list is the mechanism: no `sqlite3` (the statements are text and the
    store submits them), no `asyncio` and no `selectors` (G23), no `time` (a cooldown is an offset
    and the store clock is the only clock).
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("sqlite3", "asyncio", "selectors", "time", "socket", "subprocess"):
        assert banned not in imported, f"work.py imports {banned}"


def test_the_claim_statement_binds_no_cost_class() -> None:
    """The narrow `claim()` (07:57, charter.md:3394) carries none, so the SQL may not ask for one.

    Batch coherence is `dispatch_key`'s alone, and one `dispatch_key` is one `cost_class` by
    construction because the planner derives both from the same resolved `Candidate`.
    """
    assert ":cost_class" not in work.CLAIM_SQL
    assert ":cost_class" not in work.COMPLETE_SQL
    assert "dispatch_key IS h.dispatch_key" in work.CLAIM_SQL


def test_the_store_clock_fragment_is_used_and_never_retyped() -> None:
    """One fragment, five uses in the claim, so the CAST cannot be dropped from one of them.

    `STORE_NOW_MS`' docstring records the measured defect it exists for: `unixepoch('subsec')*1000`
    is a REAL, `work` is STRICT, and the un-CAST form raises `datatype mismatch` at random.
    """
    assert work.STORE_NOW_MS == "CAST(unixepoch('subsec')*1000 AS INTEGER)"
    # Four, not five. The claim reads the store clock five times and only four of them are a
    # TIMESTAMP: `date(unixepoch('subsec'),'unixepoch')` is the fifth and takes the raw float,
    # because `date()` wants seconds and CASTing it to an integer millisecond count would compare
    # today against 1970. The count is written down so that dropping a CAST is a failing test.
    assert work.CLAIM_SQL.count(work.STORE_NOW_MS) == 4
    assert work.CLAIM_SQL.count("unixepoch('subsec')") == 5
    assert work.COMPLETE_SQL.count(work.STORE_NOW_MS) == 1


def test_a_failure_is_frozen() -> None:
    """It crosses from the classifier to the commit predicate; nothing in between may edit it."""
    failure = classify(FailureClass.AUTH, BoomError("401"), "acme", None)
    assert isinstance(failure, Failure)
    with pytest.raises((AttributeError, TypeError)):
        failure.verdict = Verdict.TRANSIENT  # type: ignore[misc]
