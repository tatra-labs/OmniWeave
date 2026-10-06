"""D657: a claimed batch whose call a memory verdict or a crash cut short goes again, smaller.

`ParseOperator._answers` is driven here against a worker that is a function: a unit that does not
fit beside others is killed with everything after it, and answers once it is alone. The worker is
fake so that what is asserted is the operator's decision -- which calls, at which sizes, under
which invoke ids, and which answer each row ends with -- and not anydoc's memory on this machine.
`tools/ow_bench.py inproc` is the real thing, over office-200.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave.run.dispatch import AimdRegistry
from omniweave.run.operators import parse as parse_module
from omniweave.run.operators.parse import ParseOperator, ParseTally
from omniweave.run.pipeline import Reply
from omniweave_core.errors import RouteError
from omniweave_core.host.subproc import BatchEvent, HostVerdict, InvokeReport, WorkerKey
from omniweave_core.operator import Outcome
from omniweave_ports.types import DriverResult, Isolation

DRIVER = "parse.office.anydoc"
DIGEST = "0" * 64
KEY = WorkerKey(DRIVER, DIGEST)
OOM = HostVerdict.over_memory(observed_bytes=2 * 2**30, cap_mb=1024)
OK = DriverResult(outcome="ok", produced=())


class _Worker:
    """Units in `large` do not fit beside any other unit; units in `huge` do not fit at all.

    Set on the class as `_call`, and an instance is not a descriptor: no operator is passed."""

    def __init__(self, *, large: frozenset[int] = frozenset(), huge: frozenset[int] = frozenset()):
        self.large = large
        self.huge = huge
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def __call__(
        self,
        _batch: object,
        invoke_id: str,
        slots: Sequence[int],
        _staged: object,
        *,
        granted: object,
        operator: str,
    ) -> Reply:
        del granted, operator
        self.calls.append((invoke_id, tuple(slots)))
        results: list[DriverResult | None] = []
        failures: list[HostVerdict | None] = []
        killed = False
        for slot in slots:
            killed = killed or slot in self.huge or (slot in self.large and len(slots) > 1)
            results.append(None if killed else OK)
            failures.append(OOM if killed else None)
        report = InvokeReport(
            results=tuple(results),
            failures=tuple(failures),
            event=BatchEvent.RESOURCE_LIMIT if killed else BatchEvent.CLEAN,
        )
        outcomes = tuple(
            Outcome.OK if one is None else Outcome.FAILED_PERMANENT for one in failures
        )
        return Reply(outcomes=outcomes, report=report)


def _operator(monkeypatch: pytest.MonkeyPatch, worker: _Worker, *, ceiling: int = 8) -> Any:
    monkeypatch.setattr(ParseOperator, "_call", worker)
    monkeypatch.setattr(ParseOperator, "_ceiling", lambda _self, _granted: ceiling)
    operator = object.__new__(ParseOperator)
    operator._aimd = AimdRegistry()
    operator._aimd_lock = threading.Lock()
    operator._tally = ParseTally()
    return operator


def _granted(isolation: Isolation = Isolation.SUBPROC) -> Any:
    card = SimpleNamespace(identity=SimpleNamespace(id=DRIVER))
    return parse_module._Granted(card, {}, DIGEST, isolation)  # type: ignore[arg-type]


def _answer(operator: Any, ready: Sequence[int], isolation: Isolation = Isolation.SUBPROC) -> Any:
    batch = SimpleNamespace(invoke_id="iv_a")
    return operator._answers(
        batch, list(ready), [None] * 8, granted=_granted(isolation), operator="parse.office"
    )


def _verdict(answers: Any, index: int) -> HostVerdict | None:
    reply, slot = answers[index]
    return reply.report.failures[slot]


def test_a_small_document_beside_a_large_one_is_answered_about_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The batch of eight is killed at the large unit; the three it took down go again as one call
    of three -- half of eight is four -- which the large unit kills again, and then alone. Every
    unit ends with its own answer: all eight parse, the large one included."""
    worker = _Worker(large=frozenset({5}))
    operator = _operator(monkeypatch, worker)
    answers = _answer(operator, range(8))
    assert worker.calls == [
        ("iv_a", (0, 1, 2, 3, 4, 5, 6, 7)),
        ("iv_a.1", (5, 6, 7)),
        ("iv_a.2", (5,)),
        ("iv_a.3", (6,)),
        ("iv_a.4", (7,)),
    ]
    assert sorted(answers) == list(range(8))
    assert all(_verdict(answers, index) is None for index in range(8))
    assert operator._tally.regrouped == 3 + 3


def test_the_report_says_how_many_units_went_again() -> None:
    tally = ParseTally()
    tally.parsed[DRIVER] = 8
    assert not any("sent again" in line for line in tally.lines())
    tally.regrouped = 6
    assert (
        "  parse     6 unit(s) sent again in a smaller batch after a memory limit or a crash in "
        "theirs"
    ) in tally.lines()


def test_a_unit_that_does_not_fit_alone_keeps_the_memory_verdict_and_nothing_else_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _Worker(huge=frozenset({2}))
    operator = _operator(monkeypatch, worker)
    answers = _answer(operator, range(4))
    assert worker.calls == [
        ("iv_a", (0, 1, 2, 3)),
        ("iv_a.1", (2, 3)),
        ("iv_a.2", (2,)),
        ("iv_a.3", (3,)),
    ]
    assert _verdict(answers, 2) is OOM
    assert [_verdict(answers, index) for index in (0, 1, 3)] == [None, None, None]


def test_aimd_cuts_the_next_claimed_batch_to_the_size_it_learned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two memory verdicts halve the key's size from 8 to 2, so the next batch of eight is four
    calls of two from the start -- 08-runtime.md:760's AIMD, which nothing called before D657."""
    worker = _Worker(large=frozenset({5}))
    operator = _operator(monkeypatch, worker)
    _answer(operator, range(8))
    assert operator._aimd.size(KEY, ceiling=8) == 2
    worker.calls.clear()
    worker.large = frozenset()
    _answer(operator, range(8))
    assert [slots for _id, slots in worker.calls] == [(0, 1), (2, 3), (4, 5), (6, 7)]


def test_in_process_a_batch_is_one_call_whatever_it_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1 has no worker memory to halve and a crash is the run's (04:1826): one call, as before."""
    worker = _Worker(large=frozenset({1}))
    operator = _operator(monkeypatch, worker)
    answers = _answer(operator, range(3), Isolation.INPROC)
    assert worker.calls == [("iv_a", (0, 1, 2))]
    assert _verdict(answers, 2) is OOM
    assert operator._aimd.known() == ()


def test_a_regroup_that_does_not_shrink_is_refused_rather_than_looped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop ends because every regroup is smaller than its call. A `regroup` that broke that
    -- measured, by mutating it to keep the call's width -- turned one batch into a worker called
    forever; the operator now refuses it on the first round."""
    worker = _Worker(large=frozenset({1}))
    operator = _operator(monkeypatch, worker)
    monkeypatch.setattr(parse_module, "regroup", lambda group, _failures: (group,))
    with pytest.raises(RouteError, match="regrouped no smaller"):
        _answer(operator, range(4))
    assert len(worker.calls) == 1
