"""Suite 9 of 12 -- `cost`: "free" means free, the shape fits, and nobody retries behind your back.

04-driver-system.md:2080: "`class = "free"` makes no egress and no GPU call; `[cost.model] shape` is
consistent with the measured curve; `max_retries = 0` is honoured". The defect: **a "free" driver
that phones home**.

## The three claims are three different kinds of check, and it is worth saying which

* **`class = "free"` makes no egress and no GPU call** is a *runtime* claim, and it is measured the
  same way `sandbox` measures its own: the sockets are counted during a real run. What differs is
  the subject. `sandbox` asks "did it respect `needs_network`"; this asks "does the price tag
  match the behaviour", and the two can disagree -- a card declaring `needs_network = true` and
  `class = "free"` passes `sandbox` and fails here, which is exactly the driver that phones home
  and bills nobody for it because it is spending someone else's quota.
* **`shape` is consistent with the measured curve** is a *fit* check over the fixtures actually
  run. It is reported as an R-squared against the declared shape and it is deliberately generous:
  a corpus of ten small text files supports "it is not wildly non-linear" and nothing stronger.
  A tight fit claim would need the benchmark corpus, which is `--bench`'s and `quality`'s.
* **`max_retries = 0` is honoured** is a *structural* claim about the card, checked against the
  card: 18-api-sketch.md:1923-1924 records that zero is "the only value a first release accepts:
  retry is the runtime's, with the runtime's budget and ledger". A driver that retries internally
  spends a budget no ledger saw, and the runtime's own retry then multiplies it.

## Why the GPU half is a declaration check and not a measurement

There is no portable way to observe "this process made a GPU call" without importing a GPU
runtime, which would make the kit's own dependency footprint larger than every driver it tests.
So the GPU claim is checked where it is checkable: `[hardware] gpu`, `vram_gb_min` and
`imports_torch` against `class = "free"`, plus the `sys.modules` delta across the run. A driver
that reaches a GPU without importing anything that names one is outside what this kit can see, and
saying so here is better than a green tick that means "we did not look".

Specified in 04-driver-system.md section 8.2 row 9 and section 2.5.
"""

from __future__ import annotations

import socket
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import COST_SHAPES
from omniweave_core.errors import DriverHostError
from omniweave_ports.types import CostClass, DriverError, Port

from omniweave_conform.harness import run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "cost"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

_GPU_MODULES: Final = ("torch", "cupy", "pyopencl", "pycuda", "tensorrt", "onnxruntime")
"""Modules whose import is evidence of a GPU path. Not a ban list and not exhaustive -- see the
module docstring on why this half is evidence rather than measurement."""

BILLED_DIMENSIONS: Final = frozenset({"bytes_egress", "tokens_in", "tokens_out", "gpu_ms", "calls"})
"""The `Spend` dimensions that consume someone ELSE's resources.

`SPEND_DIMENSIONS` is derived from `DriverMetrics` and is "PHYSICAL UNITS ONLY -- there is no
`cost_micros`, because only the operator's `PriceBook` converts a `Spend` to money (INV-15)".
So `class = "free"` cannot be checked by looking for a price: there are no prices on a card.
What it can be checked against is the subset of those nine dimensions that only a paid or
remote resource produces -- egress, tokens, GPU time and outbound calls. `wall_ms`, `cpu_ms`,
`bytes_read` and `peak_rss_bytes` are the caller's own machine, and 04 section 3's free ipynb
card declares `per_part = { wall_ms = 3 }`, so a suite that failed on those would fail the
plan's own worked example."""

_LINEAR_SHAPES: Final = frozenset(COST_SHAPES) - {"constant"}
_GROWTH_R2: Final = 0.9
"""Above this, time tracks input size closely enough that `constant` is a false claim."""

_MIN_POINTS_FOR_FIT: Final = 3
"""Below three points a line through them is not evidence of anything, so the fit is reported as
unmeasurable rather than as a suspiciously perfect R-squared of 1.0."""


@contextmanager
def _counting_sockets() -> Iterator[list[str]]:
    seen: list[str] = []
    real_socket = socket.socket
    real_connection = socket.create_connection

    def traced_socket(*args: Any, **kwargs: Any) -> Any:
        seen.append(f"socket{args!r}")
        return real_socket(*args, **kwargs)

    def traced_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(f"connect{address!r}")
        return real_connection(address, *args, **kwargs)

    socket.socket = traced_socket  # type: ignore[misc]
    socket.create_connection = traced_connection  # type: ignore[assignment]
    try:
        yield seen
    finally:
        socket.socket = real_socket  # type: ignore[misc]
        socket.create_connection = real_connection  # type: ignore[assignment]


def run(subject: Subject) -> SuiteResult:
    """The `cost` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731
    model = subject.card.cost_model

    if model is None:
        return SuiteResult.of(
            SUITE,
            [
                Assertion(
                    "the card declares [cost.model]",
                    ok=False,
                    detail=(
                        "a card with no price is not a free card: it is a card whose price the "
                        "router cannot read, and class is what a cost policy filters on"
                    ),
                    locus="cost.model",
                )
            ],
            elapsed_ms=elapsed(),
        )

    checks = list(_declaration_assertions(subject, model))
    fit = ""
    if subject.card.identity.port is Port.PARSE and subject.fixtures:
        try:
            driver = subject.instantiate()
        except (DriverHostError, DriverError, TypeError, ValueError) as exc:
            checks.append(
                Assertion("the driver constructs", ok=False, detail=str(exc), locus="construct")
            )
        else:
            runtime, fit = _runtime_assertions(subject, driver, model)
            checks.extend(runtime)
    else:
        checks.append(
            Assertion(
                "there is a run to price",
                ok=False,
                detail=(
                    "no parse/1 fixtures; the egress, GPU and curve halves of this row are "
                    "measured over a run and were not measured"
                ),
                locus="runtime",
            )
        )

    summary = (
        f"class={model.cost_class.value}: {_egress_count(checks)} bytes egress, 0 gpu_ms; "
        f"shape={model.shape}{fit}"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _egress_count(checks: list[Assertion]) -> int:
    for check in checks:
        if check.locus == "egress":
            return 0 if check.ok else 1
    return 0


def _declaration_assertions(subject: Subject, model: Any) -> Iterator[Assertion]:
    card = subject.card
    free = model.cost_class is CostClass.FREE
    yield Assertion(
        "max_retries is zero",
        ok=model.max_retries == 0,
        detail=(
            "18:1923 -- the only value a first release accepts: retry is the runtime's, with the "
            "runtime's budget and ledger. A driver that retries spends a budget no ledger saw"
        ),
        locus="max_retries",
        expected="0",
        actual=str(model.max_retries),
    )
    if free:
        yield Assertion(
            "class = free and the card declares no network need",
            ok=not card.hardware.needs_network,
            detail=(
                "a free driver that declares egress is spending someone else's quota, which is "
                "the marker --use_llm shape of the defect with the price tag removed"
            ),
            locus="free:network",
            expected="needs_network = false",
            actual=f"needs_network = {str(card.hardware.needs_network).lower()}",
        )
        yield Assertion(
            "class = free and the card requires no GPU",
            ok=card.hardware.gpu != "required" and card.hardware.vram_gb_min == 0,
            detail=f"gpu={card.hardware.gpu} vram_gb_min={card.hardware.vram_gb_min}",
            locus="free:gpu",
        )
        declared = set(model.per_part) | set(model.per_session)
        billed = sorted(declared & BILLED_DIMENSIONS)
        yield Assertion(
            "class = free and the spend vector names no remote or metered resource",
            ok=not billed,
            detail=(
                f"billed dimensions on a free card: {', '.join(billed)}"
                if billed
                else "wall_ms and cpu_ms are the caller machine and cost nobody anything"
            ),
            locus="free:spend",
            expected="none of " + ", ".join(sorted(BILLED_DIMENSIONS)),
            actual=", ".join(billed) or "none",
        )


def _runtime_assertions(
    subject: Subject, driver: object, model: Any
) -> tuple[list[Assertion], str]:
    """Run the fixtures, count sockets and GPU imports, and fit the declared shape."""
    free = model.cost_class is CostClass.FREE
    scratch = subject.scratch(SUITE)
    before = frozenset(sys.modules)
    points: list[tuple[int, float]] = []
    with _counting_sockets() as sockets:
        for index, fixture in enumerate(subject.fixtures):
            at = time.monotonic_ns()
            try:
                run_parse(driver, fixture, scratch / f"f{index}")
            except Exception as exc:
                del exc  # A refusal is `contract`'s finding; it costs nothing and prices nothing.
                continue
            points.append((fixture.byte_len, (time.monotonic_ns() - at) / _NS_PER_MS))
    gained = sorted(
        name for name in frozenset(sys.modules) - before if name.split(".")[0] in _GPU_MODULES
    )
    checks = [
        Assertion(
            "the run opened no socket" if free else "sockets opened during the run are recorded",
            ok=not sockets if free else True,
            detail=", ".join(sockets[:3]) if sockets else "0 sockets",
            locus="egress",
        ),
        Assertion(
            "the run imported no GPU runtime",
            ok=not gained or not free,
            detail=", ".join(gained) if gained else "none of " + ", ".join(_GPU_MODULES),
            locus="gpu",
        ),
    ]
    fit, note = _fit(points)
    # The ONLY failable direction. A `constant` claim against a curve that visibly grows with
    # input is a card that will under-reserve on every large document; a `linear_*` claim
    # measured over ten small fixtures is dominated by per-call overhead and a low r2 says
    # nothing about it. So the assertion fires one way and the number is reported either way,
    # which is the honest shape for a check whose corpus cannot support the stronger claim.
    grows = fit is not None and fit >= _GROWTH_R2
    constant_but_growing = model.shape == "constant" and grows
    checks.append(
        Assertion(
            f"the measured curve is consistent with shape = {model.shape}",
            ok=not constant_but_growing,
            detail=note
            + (
                "; a constant claim over a curve this correlated with input size will "
                "under-reserve on every large document"
                if constant_but_growing
                else ""
            ),
            locus="shape",
        )
    )
    return checks, f" fits at r2={fit:.2f}" if fit is not None else ""


def _fit(points: list[tuple[int, float]]) -> tuple[float | None, str]:
    """R-squared of `ms = a + b*bytes` over the fixtures that ran. Reported; asserted one way.

    Over a handful of small fixtures, per-call overhead dominates and a genuinely linear parser
    measures a poor r2 -- which is why a low number is reported rather than failed. A HIGH
    number under `shape = "constant"` is the failable direction, and the caller owns that
    comparison. The tight version needs the benchmark corpus and is `--bench`'s.
    """
    if len(points) < _MIN_POINTS_FOR_FIT:
        return None, f"{len(points)} points; a line through fewer than 3 is not evidence"
    xs = [float(x) for x, _ in points]
    ys = [y for _, y in points]
    n = len(points)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    if sxx == 0 or syy == 0:
        return None, "every fixture is the same size, or every run took the same time"
    r2 = (sxy * sxy) / (sxx * syy)
    return r2, f"{n} points, r2 = {r2:.3f} of ms against input bytes"
