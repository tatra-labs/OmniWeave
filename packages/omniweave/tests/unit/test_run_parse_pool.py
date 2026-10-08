"""The worker pool under two first batches at once: make room and build in one step. **D676.**

`WorkerPool` is not thread-safe, and the per-key lock keeps two batches of ONE key apart, not two
keys. Once stages overlap -- a segmentation beside four free Passes -- two drivers' first workers
are wanted on two threads while the class is full. `_make_room` retires an idle worker and `acquire`
builds in its place, and if a second thread's `acquire` lands between the two, the first is
refused: `DriverHostError`, its batch crashed, its rows stranded `claimed` (the damage suite's
`pending_work_in_scope`, three runs in four, before the fix).

The pool here is a fake with exactly the property the race needs and no process behind it: a
worker takes its place in the class only when its spawn finishes, as a real one does.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave.run.operators.parse import ParseOperator
from omniweave_core.errors import DriverHostError
from omniweave_core.host import subproc

SPAWN_S = 0.05


class _Pool:
    """A class of `cap` places. A new key's worker takes its place after `SPAWN_S`, and is
    refused then if the class filled meanwhile -- the real pool's refusal, at the real moment."""

    def __init__(self, cap: int, *, idle: tuple[str, ...], busy: tuple[str, ...]) -> None:
        self.cap = cap
        self.workers: dict[str, bool] = dict.fromkeys(idle, False) | dict.fromkeys(busy, True)
        self.guard = threading.Lock()

    def _key(self, key: Any) -> str:
        return str(key.driver_id)

    def get(self, key: Any) -> object | None:
        return self.workers.get(self._key(key))

    def full(self, cost_class: str) -> bool:
        del cost_class
        return len(self.workers) >= self.cap

    def idle_order(self, cost_class: str) -> list[Any]:
        del cost_class
        return [subproc.WorkerKey(k, "c") for k, busy in self.workers.items() if not busy]

    def retire(self, key: Any) -> bool:
        return self.workers.pop(self._key(key), None) is not None

    def acquire(self, key: Any, *, cost_class: str, build: Any) -> object:
        del cost_class, build
        name = self._key(key)
        if name in self.workers:
            return name
        time.sleep(SPAWN_S)
        with self.guard:
            if len(self.workers) >= self.cap:
                raise DriverHostError(
                    f"free already has {self.cap} worker processes", fix="raise max_workers"
                )
            self.workers[name] = False
        return name


def _operator(pool: _Pool, *, locked: bool) -> Any:
    operator: Any = object.__new__(ParseOperator)
    operator._pool = pool
    operator._pool_lock = threading.Lock() if locked else _NoLock()
    operator._locks = {}
    operator._locks_guard = threading.Lock()
    return operator


class _NoLock:
    """The pre-D676 shape, for the counterfactual: a lock that excludes nothing."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> None:
        return None


def _granted(driver: str) -> Any:
    card = SimpleNamespace(identity=SimpleNamespace(id=driver), cost_model=None)
    return SimpleNamespace(card=card, config_digest="c")


def _two_first_workers(operator: Any) -> list[BaseException]:
    """Two new drivers' first workers, wanted at once, into a full class with one idle place."""
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def want(driver: str) -> None:
        barrier.wait()
        try:
            operator._worker(_granted(driver))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=want, args=(name,)) for name in ("defterm", "pattern")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return failures


def test_two_first_workers_wanted_at_once_both_get_one() -> None:
    """With the pool lock, the second waits for the first's build and then makes its own room."""
    for _ in range(5):
        pool = _Pool(2, idle=("segment",), busy=("native",))
        assert _two_first_workers(_operator(pool, locked=True)) == []
        assert set(pool.workers) == {"native", "pattern"} or set(pool.workers) == {
            "native",
            "defterm",
        }
        assert len(pool.workers) == 2, "the cap held"


@pytest.mark.parametrize("attempt", range(3))
def test_without_the_lock_the_second_takes_the_freed_place_and_the_first_is_refused(
    attempt: int,
) -> None:
    """The counterfactual, so the test above is a test of the lock and not of the fake."""
    del attempt
    pool = _Pool(2, idle=("segment",), busy=("native",))
    failures = _two_first_workers(_operator(pool, locked=False))
    assert [type(one) for one in failures] == [DriverHostError]
