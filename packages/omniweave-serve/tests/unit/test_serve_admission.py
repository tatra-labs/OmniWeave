"""The admission queue, driven through every state it has. 10-interfaces.md:958.

**Every test here passes integers for time.** `AdmissionQueue` takes a monotonic reading as an
argument and holds no clock, so the whole state machine -- a wait of exactly 999,999 ns, a clock
that steps backwards, a ring that turns over -- is reachable without a loop, a sleep or a fake
clock class. That is the property the loop-free shape was chosen for, and this file is the proof
that it was worth choosing.

**Two bindings cross the layers row the module may not.** `percentile` is held against
`omniweave.run.bench.percentile`, and the four defaults against `omniweave_core.config.KEYS`. G4
scans `packages/*/src/**/*.py`, so a test tree is not source and the first of those imports is
legal here and a gate failure one directory over -- `test_serve_catalog.py` establishes the
pattern and its reasoning applies unchanged.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import TYPE_CHECKING

import omniweave_serve.admission as admission_module
import pytest
from omniweave.run.bench import percentile as bench_percentile
from omniweave_core.config import KEYS, load
from omniweave_core.errors import ConfigError, InternalError, ResourceLimit
from omniweave_core.limits import MAX_SNAPSHOT_MS
from omniweave_serve.admission import (
    KEY_CEILING_MS,
    KEY_COLD_MS,
    KEY_CONCURRENT,
    KEY_QUEUED,
    OVERLOADED,
    QUANTILE,
    WINDOW,
    AdmissionQueue,
    Decision,
    Verdict,
    overloaded,
    percentile,
)

if TYPE_CHECKING:
    from omniweave_core.config import Config

MS = 1_000_000
"""One millisecond in nanoseconds, because every reading in this file is one."""


def _queue(**over: int) -> AdmissionQueue:
    """A queue with small, distinct numbers, so an off-by-one names which cap it broke."""
    numbers = {"max_concurrent": 2, "max_queued": 3, "cold_ms": 250, "ceiling_ms": 2000}
    numbers.update(over)
    return AdmissionQueue(**numbers)  # type: ignore[arg-type]


def _declared(key: str) -> int:
    """A declared default, narrowed to the int it is, so a test below reads as arithmetic."""
    default = KEYS[key].default
    assert isinstance(default, int)
    return default


def _fill(queue: AdmissionQueue, *, at_ns: int = 0) -> list[Decision]:
    """Offer until the queue refuses, and return every decision including the refusal."""
    out: list[Decision] = []
    while True:
        decision = queue.offer(at_ns=at_ns)
        out.append(decision)
        if decision.verdict is Verdict.REFUSE:
            return out


# ---------------------------------------------------------------------------------------------
# The four numbers, none of which this module owns
# ---------------------------------------------------------------------------------------------


def test_the_two_admission_keys_carry_the_defaults_10_958_prints() -> None:
    """D342's resolution. *"admits at most `[serve] max_concurrent_queries` (default **2**)
    snapshots per process, queues up to `max_queued_queries` (default **8**)"*."""
    assert KEYS[KEY_CONCURRENT].default == 2
    assert KEYS[KEY_QUEUED].default == 8
    assert KEYS[KEY_CONCURRENT].axis == "operational"
    assert KEYS[KEY_QUEUED].axis == "operational"


def test_the_estimate_and_its_ceiling_are_keys_that_already_existed() -> None:
    """Neither number is coined here. 250 is B27's committed p95 and G10's ceiling; 2,000 is the
    clamp on one read transaction's life, which is what an admitted call holds."""
    assert KEYS[KEY_COLD_MS].default == 250
    assert KEYS[KEY_CEILING_MS].default == 2000


def test_the_ceiling_cannot_advertise_a_wait_the_store_would_abort() -> None:
    """`[retrieval] snapshot_ms` clamps below `MAX_SNAPSHOT_MS`, so the advertised wait is inside
    the window a snapshot can actually live in."""
    assert _declared(KEY_CEILING_MS) <= MAX_SNAPSHOT_MS


def test_shipped_transcribes_nothing() -> None:
    """Every number in the shipped queue comes back out of the registry it came from."""
    queue = AdmissionQueue.shipped()
    concurrent, waiting = _declared(KEY_CONCURRENT), _declared(KEY_QUEUED)
    admitted = [queue.offer(at_ns=0) for _ in range(concurrent)]
    assert [d.verdict for d in admitted] == [Verdict.ADMIT] * concurrent
    queued = [queue.offer(at_ns=0) for _ in range(waiting)]
    assert [d.verdict for d in queued] == [Verdict.QUEUE] * waiting
    assert queue.offer(at_ns=0).verdict is Verdict.REFUSE
    assert queue.retry_after_ms() == _declared(KEY_COLD_MS)


def test_from_config_reads_the_same_four_keys_through_the_layers(tmp_path: Path) -> None:
    """The configured path and the shipped path agree when nothing is configured."""
    root = tmp_path / "project"
    root.mkdir()
    config: Config = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    queue = AdmissionQueue.from_config(config)
    assert [queue.offer(at_ns=0).verdict for _ in range(3)] == [
        Verdict.ADMIT,
        Verdict.ADMIT,
        Verdict.QUEUE,
    ]
    assert queue.retry_after_ms() == config.get(KEY_COLD_MS)


def test_an_operator_who_writes_the_documented_key_is_obeyed(tmp_path: Path) -> None:
    """The whole point of D342: 10:958 is readable, so a value written from it must take effect.

    Before this cell the key had no declaration, and an `omniweave.toml` carrying it was either a
    startup error or a silent ignore -- with the operator's contention limit left at 2 and nothing
    saying so.
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "omniweave.toml").write_text(
        "[serve]\nmax_concurrent_queries = 4\nmax_queued_queries = 0\n",
        encoding="utf-8",
        newline="\n",
    )
    config = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    queue = AdmissionQueue.from_config(config)
    verdicts = [d.verdict for d in _fill(queue)]
    assert verdicts == [Verdict.ADMIT] * 4 + [Verdict.REFUSE]


# ---------------------------------------------------------------------------------------------
# The three verdicts
# ---------------------------------------------------------------------------------------------


def test_the_caps_are_applied_in_order_concurrency_then_queue_then_refusal() -> None:
    decisions = _fill(_queue())
    assert [d.verdict for d in decisions] == [
        Verdict.ADMIT,
        Verdict.ADMIT,
        Verdict.QUEUE,
        Verdict.QUEUE,
        Verdict.QUEUE,
        Verdict.REFUSE,
    ]


def test_every_decision_reports_the_two_counts_that_explain_it() -> None:
    """Not only the refusal: an admission into a busy server is a different fact from an
    admission into an idle one, and `retrieval_event` needs to be able to tell them apart."""
    decisions = _fill(_queue())
    assert [(d.running, d.queued) for d in decisions] == [
        (1, 0),
        (2, 0),
        (2, 1),
        (2, 2),
        (2, 3),
        (2, 3),
    ]


def test_a_ticket_is_unique_increasing_and_zero_only_on_a_refusal() -> None:
    decisions = _fill(_queue())
    granted = [d.ticket for d in decisions if d.verdict is not Verdict.REFUSE]
    assert granted == sorted(set(granted)) == [1, 2, 3, 4, 5]
    assert decisions[-1].ticket == 0


def test_only_a_refusal_carries_a_retry_after() -> None:
    """A call that was not refused was not asked to come back, so the field is 0 rather than a
    number the caller might act on."""
    decisions = _fill(_queue())
    assert [d.retry_after_ms for d in decisions[:-1]] == [0] * 5
    assert decisions[-1].retry_after_ms > 0


def test_a_freed_slot_admits_the_next_offer_when_nobody_is_waiting() -> None:
    queue = _queue()
    first = queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    assert queue.offer(at_ns=0).verdict is Verdict.QUEUE
    queue.finish(first.ticket, at_ns=MS)
    assert queue.running == 1


# ---------------------------------------------------------------------------------------------
# Promotion, which `finish()` deliberately does not do
# ---------------------------------------------------------------------------------------------


def test_finish_frees_a_slot_and_names_nobody() -> None:
    """Two facts, two calls. An event loop needs the promoted ticket BY NAME so it can wake
    exactly one waiter; a `finish()` that promoted would hand back two and leave it guessing."""
    queue = _queue()
    held = queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    waiting = queue.offer(at_ns=0)
    assert waiting.verdict is Verdict.QUEUE

    queue.finish(held.ticket, at_ns=MS)
    assert queue.running == 1
    assert queue.queued == 1, "the waiter is still waiting until someone promotes it"

    admitted = queue.promote(at_ns=2 * MS)
    assert admitted is not None
    assert admitted.ticket == waiting.ticket
    assert queue.running == 2
    assert queue.queued == 0


def test_promotion_is_first_in_first_out() -> None:
    queue = _queue()
    running = [queue.offer(at_ns=0) for _ in range(2)]
    waiting = [queue.offer(at_ns=0) for _ in range(3)]
    for decision in running:
        queue.finish(decision.ticket, at_ns=MS)
    order = []
    for _ in range(2):
        admitted = queue.promote(at_ns=MS)
        assert admitted is not None
        order.append(admitted.ticket)
    assert order == [waiting[0].ticket, waiting[1].ticket]


def test_promote_returns_none_with_an_empty_queue() -> None:
    assert _queue().promote(at_ns=0) is None


def test_promote_returns_none_while_the_cap_is_still_full() -> None:
    """The second of the two ways there can be no taker, treated identically by the caller: it
    has nobody to wake."""
    queue = _queue()
    queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    assert queue.offer(at_ns=0).verdict is Verdict.QUEUE
    assert queue.promote(at_ns=MS) is None


# ---------------------------------------------------------------------------------------------
# The two durations, which are never one
# ---------------------------------------------------------------------------------------------


def test_an_admitted_call_waited_zero() -> None:
    queue = _queue()
    admitted = queue.offer(at_ns=0)
    held = queue.finish(admitted.ticket, at_ns=40 * MS)
    assert held.queued_ms == 0
    assert held.ran_ms == 40


def test_a_queued_call_carries_its_wait_all_the_way_to_the_ledger() -> None:
    """`queued_ms` is measured offer-to-promote, `ran_ms` promote-to-finish, and the two never
    merge. 02:1126, 08:52 and 15:1234 all state the separation; this is where it is produced."""
    queue = _queue()
    running = [queue.offer(at_ns=0) for _ in range(2)]
    waiting = queue.offer(at_ns=0)
    queue.finish(running[0].ticket, at_ns=30 * MS)

    admitted = queue.promote(at_ns=30 * MS)
    assert admitted is not None
    assert admitted.queued_ms == 30

    held = queue.finish(waiting.ticket, at_ns=100 * MS)
    assert held.queued_ms == 30, "the wait survives into the completed record"
    assert held.ran_ms == 70
    assert held.queued_ms + held.ran_ms == 100


def test_a_sub_millisecond_hold_reports_zero_and_not_one() -> None:
    """Floored, because a hold that has not lasted a millisecond has not lasted one."""
    queue = _queue()
    admitted = queue.offer(at_ns=0)
    assert queue.finish(admitted.ticket, at_ns=MS - 1).ran_ms == 0


def test_a_clock_that_steps_backwards_produces_zero_and_not_a_negative() -> None:
    """08:377's rule, at the one site in this module where a subtraction could poison a later
    estimate: a negative `ran_ms` in the ring would drag every p95 after it."""
    queue = _queue()
    admitted = queue.offer(at_ns=500 * MS)
    held = queue.finish(admitted.ticket, at_ns=0)
    assert held.ran_ms == 0
    assert queue.retry_after_ms() == 1, "floored at 1, never 0"


# ---------------------------------------------------------------------------------------------
# Abandonment, which is what `notifications/cancelled` becomes here
# ---------------------------------------------------------------------------------------------


def test_abandoning_a_waiting_ticket_frees_its_place() -> None:
    queue = _queue(max_queued=1)
    queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    waiting = queue.offer(at_ns=0)
    assert queue.offer(at_ns=0).verdict is Verdict.REFUSE

    assert queue.abandon(waiting.ticket) is True
    assert queue.queued == 0
    assert queue.offer(at_ns=0).verdict is Verdict.QUEUE


def test_abandoning_records_no_observation() -> None:
    """A wait that was abandoned measures the queue, not the work. Feeding it to the p95 would
    make cancellations read as slow queries and inflate every later `retry_after_ms`."""
    queue = _queue()
    queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    waiting = queue.offer(at_ns=0)
    queue.abandon(waiting.ticket)
    assert queue.observations == 0


def test_abandon_is_false_for_a_ticket_that_is_not_waiting() -> None:
    queue = _queue()
    running = queue.offer(at_ns=0)
    assert queue.abandon(running.ticket) is False, "a running ticket is finished, not abandoned"
    assert queue.abandon(9999) is False


def test_an_abandoned_ticket_cannot_then_be_finished() -> None:
    queue = _queue()
    queue.offer(at_ns=0)
    queue.offer(at_ns=0)
    waiting = queue.offer(at_ns=0)
    queue.abandon(waiting.ticket)
    with pytest.raises(InternalError):
        queue.finish(waiting.ticket, at_ns=MS)


@pytest.mark.parametrize("ticket", [0, 1, 9999])
def test_finishing_a_ticket_that_holds_nothing_is_our_bug_and_says_so(ticket: int) -> None:
    with pytest.raises(InternalError, match="finished twice, or never admitted"):
        _queue().finish(ticket, at_ns=0)


def test_a_ticket_cannot_be_finished_twice() -> None:
    queue = _queue()
    admitted = queue.offer(at_ns=0)
    queue.finish(admitted.ticket, at_ns=MS)
    with pytest.raises(InternalError):
        queue.finish(admitted.ticket, at_ns=2 * MS)
    assert queue.observations == 1, "the second attempt records nothing"


# ---------------------------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------------------------


def test_the_first_refusal_quotes_the_plans_own_committed_p95() -> None:
    """Before anything has completed there is no observed p95, and the number that takes its
    place is not invented: it is `[retrieval.budget] query_ms`, which B27 makes the p95 of the
    very operation the refused caller is waiting on."""
    queue = _queue(cold_ms=250)
    assert queue.observations == 0
    assert _fill(queue)[-1].retry_after_ms == 250


def test_the_estimate_is_the_nearest_rank_p95_of_what_was_observed() -> None:
    queue = _queue(max_concurrent=1, max_queued=0, ceiling_ms=100_000)
    for index in range(20):
        admitted = queue.offer(at_ns=0)
        queue.finish(admitted.ticket, at_ns=(index + 1) * MS)
    assert queue.observations == 20
    assert queue.retry_after_ms() == 19, "ceil(0.95 * 20) = 19, one-indexed, of 1..20"


def test_one_slow_call_does_not_become_the_steady_state() -> None:
    """The reason `WINDOW` is not small. Nineteen fast calls and one slow one put the p95 on a
    fast sample, because nearest rank at 0.95 of 20 is the 19th."""
    queue = _queue(max_concurrent=1, max_queued=0, ceiling_ms=100_000)
    for held_ms in [*([5] * 19), 9000]:
        admitted = queue.offer(at_ns=0)
        queue.finish(admitted.ticket, at_ns=held_ms * MS)
    assert queue.retry_after_ms() == 5


def test_the_ring_is_bounded_and_the_old_observations_leave_it() -> None:
    """A ring that never turned over would quote a latency the server no longer has."""
    queue = _queue(max_concurrent=1, max_queued=0, ceiling_ms=100_000)
    for _ in range(WINDOW + 40):
        admitted = queue.offer(at_ns=0)
        queue.finish(admitted.ticket, at_ns=900 * MS)
    assert queue.observations == WINDOW
    assert queue.retry_after_ms() == 900

    for _ in range(WINDOW):
        admitted = queue.offer(at_ns=0)
        queue.finish(admitted.ticket, at_ns=7 * MS)
    assert queue.observations == WINDOW
    assert queue.retry_after_ms() == 7, "nothing from the slow era survives a full turnover"


def test_the_estimate_is_clamped_to_the_snapshot_ceiling() -> None:
    """A hold cannot outlive `[retrieval] snapshot_ms` -- the transaction is aborted at it -- so
    a larger estimate would advertise a wait that cannot happen."""
    queue = _queue(max_concurrent=1, max_queued=0, ceiling_ms=2000)
    admitted = queue.offer(at_ns=0)
    queue.finish(admitted.ticket, at_ns=60_000 * MS)
    assert queue.retry_after_ms() == 2000


def test_the_cold_value_is_clamped_by_the_same_ceiling() -> None:
    """Both paths through `retry_after_ms()` are clamped, not just the observed one."""
    assert _queue(cold_ms=9000, ceiling_ms=2000).retry_after_ms() == 2000


def test_the_estimate_never_tells_an_agent_to_retry_immediately() -> None:
    """A `retry_after_ms` of 0 is the one instruction a server at its ceiling must not give."""
    queue = _queue(max_concurrent=1, max_queued=0)
    for _ in range(30):
        admitted = queue.offer(at_ns=0)
        queue.finish(admitted.ticket, at_ns=0)
    assert queue.retry_after_ms() == 1


# ---------------------------------------------------------------------------------------------
# `percentile`, held against the copy it was duplicated from
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "samples",
    [
        [],
        [7],
        [1, 2],
        list(range(1, 21)),
        list(range(1, 129)),
        [0] * 10,
        [3, 3, 3, 900],
    ],
)
@pytest.mark.parametrize("quantile", [0.5, 0.9, QUANTILE, 0.99, 1.0])
def test_this_percentile_is_the_repositorys_percentile(samples: list[int], quantile: float) -> None:
    """D346. The function is duplicated because 02:264 forbids the import, so the two copies are
    held equal by a test -- the same seam `catalog.py` crosses, one function smaller.

    *"Two harnesses using two of them would report two p99s for one run"* is `bench.py`'s own
    reason for fixing nearest rank, and two definitions of p95 in one repository would be exactly
    that, with `retry_after_ms` as the number that disagreed.
    """
    mine = percentile(samples, quantile)
    theirs = bench_percentile(samples, quantile)
    assert (math.isnan(mine) and math.isnan(theirs)) or mine == theirs


@pytest.mark.parametrize("quantile", [0.0, -0.1, 1.1])
def test_a_quantile_outside_its_interval_is_refused(quantile: float) -> None:
    with pytest.raises(ValueError, match=r"quantile is in \(0, 1\]"):
        percentile([1, 2, 3], quantile)


# ---------------------------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------------------------


def test_the_refusal_names_the_knob_the_wait_and_the_code() -> None:
    refused = _fill(_queue())[-1]
    error = overloaded(refused)
    assert isinstance(error, ResourceLimit)
    assert error.limit == KEY_QUEUED, "a ResourceLimit names WHICH knob would need raising"
    assert error.code() == OVERLOADED
    assert error.numeric() == "OW-A-022", "resolved from codes.toml, not transcribed"
    assert str(refused.retry_after_ms) in str(error)
    assert error.fix


def test_the_refusal_exits_one_because_it_names_a_knob() -> None:
    """`ResourceLimit` is exit 1 and not 70: *"usage or configuration error"* is what an overload
    whose fix is a configuration key actually is."""
    assert overloaded(_fill(_queue())[-1]).EXIT == 1


@pytest.mark.parametrize("verdict", [Verdict.ADMIT, Verdict.QUEUE])
def test_a_decision_that_was_not_a_refusal_has_no_ow_a_022(verdict: Verdict) -> None:
    decision = Decision(verdict=verdict, ticket=1, running=1, queued=0, retry_after_ms=0)
    with pytest.raises(InternalError, match="not a refusal"):
        overloaded(decision)


# ---------------------------------------------------------------------------------------------
# What the constructor refuses
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["max_concurrent", "cold_ms", "ceiling_ms"])
def test_a_cap_that_admits_nothing_is_refused_at_construction(key: str) -> None:
    """`max_concurrent_queries = 0` is a server that refuses every call forever, which is a
    configuration error and not a policy."""
    with pytest.raises(ConfigError, match="at least 1"):
        _queue(**{key: 0})


def test_a_negative_queue_is_refused_and_a_zero_queue_is_not() -> None:
    """Zero is a legitimate choice -- refuse rather than wait -- so it is not an error. Negative
    is not a choice."""
    with pytest.raises(ConfigError, match="must not be negative"):
        _queue(max_queued=-1)
    verdicts = [d.verdict for d in _fill(_queue(max_queued=0))]
    assert verdicts == [Verdict.ADMIT, Verdict.ADMIT, Verdict.REFUSE]


def test_the_refusal_names_the_full_key_an_operator_would_edit() -> None:
    with pytest.raises(ConfigError) as caught:
        _queue(max_concurrent=0)
    assert KEY_CONCURRENT in str(caught.value)
    assert KEY_CONCURRENT in caught.value.fix


def test_a_configured_value_of_the_wrong_kind_is_refused(tmp_path: Path) -> None:
    """The loader coerces what it can; anything that reaches here as another type is refused by
    name rather than by `TypeError` three frames later."""
    root = tmp_path / "project"
    root.mkdir()
    config = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    broken = type(config)(
        values={**config.values, KEY_CONCURRENT: "two"},
        sources=config.sources,
        config_digest=config.config_digest,
        semantic_digest=config.semantic_digest,
    )
    with pytest.raises(ConfigError, match="not an integer"):
        AdmissionQueue.from_config(broken)


# ---------------------------------------------------------------------------------------------
# The shape, asserted where the module lives
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(admission_module.__file__).read_text(encoding="utf-8"))


def test_the_policy_imports_no_loop_and_reads_no_clock() -> None:
    """The three names that would turn a testable state machine into an untestable one. `asyncio`
    is additionally banned in this distribution's source by `pyproject.toml`'s `banned-api`
    block, whose only `TID251` escape here is `otlp.py`; `time` would be the ambient clock
    02:255 row 23 bans outright.

    Over the AST rather than the text, because all three names appear in the docstring that
    explains why they are absent.
    """
    tree = _module_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"asyncio", "selectors", "time", "threading"})


def test_nothing_in_the_module_awaits() -> None:
    """A coroutine here would move the waiting inside the policy and take the state machine's
    testability with it."""
    tree = _module_tree()
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith)
    ]


def test_all_names_every_public_symbol_this_module_defines() -> None:
    """Complete, so a name added without a line in `__all__` cannot become public by accident.

    Read off the AST rather than off `vars()`, because a module's namespace also holds what it
    imported -- `math`, `KEYS`, `TYPE_CHECKING` -- and none of those are this module's to export.
    RUF022 owns the ORDER of `__all__`; this owns the SET.
    """
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    public = {name for name in defined if not name.startswith("_")}
    assert public == set(admission_module.__all__)
