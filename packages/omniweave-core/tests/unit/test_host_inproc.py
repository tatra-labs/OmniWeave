"""`DriverGuard`: the clearance it will not forge, the attribution it will not invent, the
deadline it can report but cannot enforce.

Six families, and the first two are the ones the plan makes load-bearing.

* **clearance** -- `resolve()` decides whether a driver may run in process and this guard decides
  nothing about it (04-driver-system.md:1632-1655, ledger D72). Tested in BOTH directions,
  because one direction alone is satisfied by the wrong module: a guard that refused a
  `subproc` grant and also re-ran DR9's conjuncts would pass the refusal test and be a second
  home for the policy, so there is a matching test that a card failing four of DR9's six
  conjuncts still RUNS when `resolve()` granted it `inproc`. And a look-alike object carrying
  `isolation_granted = INPROC` is refused, because clearance is the one thing here worth forging.
* **attribution** -- 02-architecture.md:1061: `BaseException` in, `FailureClass.driver_bug` out,
  nothing propagating into the loop; and a `DriverError` crosses with its five fields unchanged.
  The pair matters: converting everything would lose the driver's own diagnosis, and converting
  nothing would let a third party's `KeyError` reach the supervisor.
* **the five fields, and the constructor that cannot hold them** -- a host-detected `TIMEOUT` is
  `FAILED_PERMANENT` with no `retry_after_ms`, and `DriverError.__post_init__` refuses exactly
  that combination because it was written for the driver half of 08-runtime.md's classifier
  table. The test constructs both and asserts the asymmetry, so the reason `GuardFailure` exists
  is pinned rather than explained in a comment.
* **the three deadlines** -- named separately (04-driver-system.md:1733), reset separately
  (`progress()` resets, `log()` does not, :1735), and `0` on a card means UNSET and not
  expired. Every deadline test runs against a SUPPLIED clock, so none of them sleeps and none of
  them can flake; the one test that observes the watchdog thread uses the real clock and a
  bounded poll.
* **`DriverIO`** -- four fields, INV-6's audit question, still four through the subclass; and an
  io kept past its invocation is refused rather than silently writing into a finished call.
* **purity and platform** -- the import set is pinned as a literal. No `signal`, no `resource`,
  no `os`, no `asyncio`, no `selectors`, no `subprocess`, no wall clock. That is what makes this
  Windows cell test the same property a POSIX cell would: the S1 watchdog is a `threading.Event`
  on both, so there is no platform-specific cell here to be weaker than another. What Windows
  cannot observe is nothing that this file asserts -- the per-OS controls of
  04-driver-system.md:1748-1756 belong to the SUBPROC watchdog, and the shortfall this guard has
  is the same on every OS: it cannot preempt an uncooperative driver, only discard its result.
"""

from __future__ import annotations

import ast
import dataclasses
import threading
import time
import tomllib
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import BinaryIO, ClassVar, Final

import pytest
from omniweave_core.canonical import sha256_canonical
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.drivers.resolve import Candidate, RejectCode

# Both exception classes are bound by DIRECT IMPORT and never spelled `errors.DriverHostError`.
# `test_errors.py`'s `importlib.reload(errors)` -- it resets a memoised register read -- rebuilds
# every class object in the module, so the module attribute names the post-reload class while
# `inproc.py` still raises the pre-reload one. That mismatch fails only in a full-suite run and
# passes when this file runs alone. A direct import binds at this module's import, as
# `inproc.py`'s own import does.
from omniweave_core.errors import CapabilityMissing, DriverHostError
from omniweave_core.host import inproc
from omniweave_core.host.inproc import (
    NO_SERVICES,
    DeadlineLimit,
    Deadlines,
    DriverGuard,
    GuardFailure,
    GuardIO,
    GuardOutcome,
)
from omniweave_ports.types import (
    DriverError,
    DriverIO,
    DriverMetrics,
    DriverResult,
    FailureClass,
    Isolation,
)

ROOT: Final = Path(__file__).resolve().parents[4]
PLAN: Final = ROOT / "_plan"


MINIMAL_CARD: Final = """card_schema = 1

[driver]
id = "parse.office.anydoc"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/pdf"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""
"""The shape `test_drivers_resolve.py` uses, reduced to what a guard reads: the identity (for
`check_code`) and whatever `[hardware]` or `[isolation]` a test appends."""


def card(extra: str = "") -> DriverCard:
    loaded = load_card(
        (MINIMAL_CARD + extra).encode("utf-8"), origin="entry_point", source="driver.toml"
    )
    assert isinstance(loaded, DriverCard)
    return loaded


def candidate(
    *, granted: Isolation = Isolation.INPROC, extra: str = "", subject: DriverCard | None = None
) -> Candidate:
    """A real `resolve()` `Candidate`. Real, because `DriverGuard` refuses anything else."""
    return Candidate(
        card=subject if subject is not None else card(extra),
        isolation_granted=granted,
        effective_config=MappingProxyType({}),
        config_digest=sha256_canonical({}),
    )


class Blobs:
    """The narrowest `BlobStore` that satisfies the Protocol. The guard never touches it."""

    def path(self, digest: str) -> str:
        return f"/ro/{digest}"

    def open(self, digest: str) -> BinaryIO:  # pragma: no cover - never called by the guard
        raise AssertionError(f"the guard does not read blobs: {digest}")

    def put(self, data: bytes) -> str:  # pragma: no cover - never called by the guard
        raise AssertionError(f"the guard does not write {len(data)} bytes")


class Clock:
    """A settable monotonic clock in milliseconds.

    Settable rather than scripted: the watchdog thread reads the clock an unpredictable number of
    times, so a sequence would be consumed non-deterministically and a test built on one would
    flake. A test moves `now_ms` and every reader -- driver thread and watchdog alike -- sees the
    same value.
    """

    def __init__(self) -> None:
        self.now_ms = 0

    def __call__(self) -> int:
        return self.now_ms * 1_000_000


OK: Final = DriverResult(outcome="ok", produced=(), metrics=DriverMetrics(wall_ms=1))

NO_DEADLINES: Final = Deadlines()
"""All three unset -- a module singleton, because a call in an argument default is a call every
invocation pays and `Deadlines` is frozen and shareable -- the idiom `resolve.py`'s `_NO_ACKS`
sets."""

TMPDIR: Final = "ow-inproc-tmpdir"
"""The one writable surface a driver is given. A bare name and not a real path: the guard hands
it to the driver and never touches the filesystem, so a test that named `/tmp` would be claiming a
POSIX layout this Windows cell does not have."""


def guard(
    *,
    granted: Isolation = Isolation.INPROC,
    deadlines: Deadlines = NO_DEADLINES,
    clock: Clock | None = None,
    extra: str = "",
) -> DriverGuard:
    return DriverGuard(
        candidate(granted=granted, extra=extra),
        deadlines=deadlines,
        monotonic_ns=time.monotonic_ns if clock is None else clock,
    )


def code_without_docstrings(source: str) -> str:
    """The module's CODE, with every bare string-expression statement removed.

    A source-text assertion over this file has to survive its house style: the module carries
    thirty kilobytes of cited argument in docstrings, and this repo also documents module and
    class attributes with a bare string statement AFTER the assignment -- so "the first statement
    of a body" is not where the strings are. Every `Expr(Constant(str))` in every body is dropped
    and the tree is unparsed, which normalises attribute reads, subscripts and string literals
    into one text a substring check can trust.
    """
    tree = ast.parse(source)
    for node in list(ast.walk(tree)):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if not isinstance(block, list):
                continue
            kept = [
                stmt
                for stmt in block
                if not (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                )
            ]
            setattr(node, attr, kept or ([ast.Pass()] if attr == "body" else []))
    return ast.unparse(ast.fix_missing_locations(tree))


def test_the_docstring_stripper_strips_docstrings_and_keeps_the_code() -> None:
    """The helper above is a subject too, and a stripper that emptied the file would make every
    assertion over its output pass. Both halves are asserted."""
    code = code_without_docstrings(Path(inproc.__file__).read_text(encoding="utf-8"))
    assert "Seam S1" not in code
    assert "Which half is whose" not in code
    assert "crash containment" not in code
    assert "def invoke" in code
    assert "_start_watchdog" in code
    assert "monotonic_ns" in code


def run(subject: DriverGuard, work: object, **kwargs: object) -> GuardOutcome:
    """`invoke()` with the four host-supplied arguments a caller always has to pass."""
    return subject.invoke(
        work,  # type: ignore[arg-type]
        blobs=Blobs(),
        tmpdir=TMPDIR,
        max_output_bytes=4 * 1024 * 1024,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------------------------
# 1. Clearance: resolve() decides, the guard reads
# --------------------------------------------------------------------------------------------


def test_the_guard_refuses_a_candidate_resolve_granted_subproc() -> None:
    """S1 runs what `resolve()` granted `inproc` and nothing else.

    The refusal is at CONSTRUCTION, so there is no object on which a caller could then call
    `invoke()`: a guard that exists is a guard that may run.
    """
    with pytest.raises(DriverHostError) as caught:
        guard(granted=Isolation.SUBPROC)
    assert "'subproc' and not 'inproc'" in str(caught.value)
    assert caught.value.code() == "OW_DRIVER_HOST"


def test_the_guard_refuses_a_wasm_grant_which_is_a_mode_that_cannot_run() -> None:
    """`wasm` "is in the vocabulary and not built at v1" (04-driver-system.md:1650).

    `resolve()` refuses such a card with `ISOLATION_NOT_PERMITTED`, so a `wasm` grant reaching S1
    is a framework bug; the guard's one comparison catches it without knowing why.
    """
    with pytest.raises(DriverHostError):
        guard(granted=Isolation.WASM)


def test_a_look_alike_object_cannot_forge_inproc_clearance() -> None:
    """`type(...) is Candidate`, because clearance is the one thing worth forging here.

    A structural check would accept this namespace, and with it any caller's assertion that a
    driver was cleared. `Candidate` is built only by `resolve()`, after its gate order has run.
    """
    forged = SimpleNamespace(
        card=card(),
        isolation_granted=Isolation.INPROC,
        effective_config=MappingProxyType({}),
        config_digest="",
        driver_id="parse.office.anydoc",
    )
    with pytest.raises(DriverHostError) as caught:
        DriverGuard(forged, deadlines=NO_DEADLINES)  # type: ignore[arg-type]
    assert "resolve() Candidate" in str(caught.value)


class ForgedCandidate(Candidate):
    """A SUBCLASS of `Candidate`, which is the shape `isinstance` cannot tell from the real thing.

    `Candidate` is a frozen slotted dataclass and frozen slotted dataclasses are subclassable, so
    a caller who wants to assert clearance does not have to build a look-alike -- it can inherit
    the real type and set `isolation_granted` itself.
    """

    __slots__ = ()


def test_a_subclass_of_candidate_cannot_forge_inproc_clearance_either() -> None:
    """`type(...) is Candidate`, and the `is` is the load-bearing half.

    The look-alike test above passes against `isinstance` too -- a `SimpleNamespace` is not a
    `Candidate` under either check -- so it pinned nothing about the choice the code actually
    made. Replacing `type(candidate) is not Candidate` with `not isinstance(candidate, Candidate)`
    left all thirty-nine tests in this file green, which means the one thing the exact-type check
    buys, refusing a subclass, was asserted nowhere. `Candidate` is built only by `resolve()`'s
    `_candidate_of()` after nineteen gates, and a subclass is a way around all nineteen.
    """
    forged = ForgedCandidate(
        card=card(),
        isolation_granted=Isolation.INPROC,
        effective_config=MappingProxyType({}),
        config_digest=sha256_canonical({}),
    )
    assert isinstance(forged, Candidate)
    assert type(forged) is not Candidate
    assert forged.isolation_granted is Isolation.INPROC
    with pytest.raises(DriverHostError) as caught:
        DriverGuard(forged, deadlines=NO_DEADLINES)
    assert "resolve() Candidate" in str(caught.value)
    assert "ForgedCandidate" in str(caught.value)


def test_the_guard_does_not_re_decide_dr9_and_runs_what_resolve_granted() -> None:
    """The matching direction, and the one that stops this file from testing the wrong module.

    This card fails four of DR9's six conjuncts outright -- a GPU, a network need, no green
    `fuzz` suite, and it is named in no `[drivers] inproc` list the guard can even see -- and
    04-driver-system.md:1645 says no config key widens the first four. `resolve()` is where that
    is decided; here the grant is `inproc` and the driver therefore RUNS. A guard that
    re-evaluated the conjuncts would refuse this call and disagree with a `Resolution` whose
    digest a run manifest has already recorded.
    """
    hostile = card('\n[hardware]\ngpu = "required"\nneeds_network = true\n')
    assert hostile.hardware.gpu == "required"
    assert hostile.hardware.needs_network is True
    assert hostile.quality.suites.get("fuzz") is None
    subject = DriverGuard(candidate(subject=hostile), deadlines=NO_DEADLINES, monotonic_ns=Clock())
    assert run(subject, lambda _io: OK).result is OK


def test_the_guard_reads_no_runtime_knob_because_admission_control_is_the_dispatchers() -> None:
    """`[runtime] max_inproc` and `[runtime] inproc_bulk_threshold` are counters over a SET of
    calls (02-architecture.md:828, 04-driver-system.md:1828-1830) and 02-architecture.md:238 assigns
    batching to `run/dispatch.py` by name. A guard that read either would be counting a set it
    cannot see.

    The string half of this test used to read the file's text after the LAST triple quote in it
    -- 650 characters of `_breach`'s body out of 30,964 -- so a knob read anywhere else was
    invisible to it, and adding a module-scope `_RUNTIME["max_inproc"]` left the test green. It
    now runs over the whole module with docstrings stripped, which also catches a knob read by
    SUBSCRIPT: the `ast.Attribute` half below only ever saw `x.max_inproc`.
    """
    source = Path(inproc.__file__).read_text(encoding="utf-8")
    code = code_without_docstrings(source)
    assert "max_inproc" not in code
    assert "inproc_bulk_threshold" not in code
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"max_inproc", "inproc_bulk_threshold"}
        for node in ast.walk(ast.parse(source))
    )


# --------------------------------------------------------------------------------------------
# 2. CARD_CODE_MISMATCH: the half of activate() that survives in process
# --------------------------------------------------------------------------------------------


class Good:
    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1


class WrongPort:
    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1


class WrongSchema:
    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 2


class Neither:
    pass


def test_check_code_accepts_a_class_that_agrees_with_the_card() -> None:
    """`PORT` and `SCHEMA_VERSION` against the card's `port` and `schema_version`."""
    guard().check_code(Good)


@pytest.mark.parametrize("loaded", [WrongPort, WrongSchema, Neither])
def test_check_code_refuses_a_class_that_disagrees_with_the_card(loaded: type[object]) -> None:
    """04-driver-system.md:1543-1546, "refused BEFORE any work".

    `WrongSchema` is the expensive one: 04-driver-system.md:1478-1480 calls forgetting to bump
    `schema_version` "the most expensive single mistake available in the whole design: it serves
    stale billed output forever with no symptom", and it is the only driver version that enters a
    cache key. `Neither` is the shape a non-driver object or an `exec` driver's stand-in has.
    """
    with pytest.raises(DriverHostError) as caught:
        guard().check_code(loaded)
    assert caught.value.code() == "OW_CARD_CODE_MISMATCH"
    assert caught.value.fix == "ow drivers verify parse.office.anydoc"


def test_the_symbol_check_code_raises_is_the_row_the_register_already_carries() -> None:
    """`codes.toml` is the register and wins over any spelling this module could invent.

    The numeric is read from the register and pinned as a literal, so this test fails if the row
    moves as well as if the symbol changes -- and no row is invented here.
    """
    register = tomllib.loads((ROOT / "codes.toml").read_text(encoding="utf-8"))
    rows = {row["symbol"]: row["numeric"] for row in register["code"]}
    assert rows["OW_CARD_CODE_MISMATCH"] == "OW-D-073"
    assert RejectCode.CARD_CODE_MISMATCH.symbol == "OW_CARD_CODE_MISMATCH"


# --------------------------------------------------------------------------------------------
# 3. Attribution at the call boundary
# --------------------------------------------------------------------------------------------


def test_a_driver_error_crosses_the_boundary_with_its_five_fields_unchanged() -> None:
    """The five fields 02-architecture.md:1060 sends across S4 cross S1 in memory.

    The guard never rewrites an attribution: a driver that says `rate_limited` with a 250 ms
    cooldown is reported as saying exactly that, cooldown included, because the retry ladder
    escalates from the class's first cooldown.
    """
    raised = DriverError(
        cls=FailureClass.RATE_LIMITED,
        message="the upstream said 429",
        retry_after_ms=250,
    )

    def work(_io: DriverIO) -> DriverResult:
        raise raised

    outcome = run(guard(), work)
    assert outcome.result is None
    assert outcome.failure == GuardFailure(
        failure_class=FailureClass.RATE_LIMITED,
        message="the upstream said 429",
        retry_after_ms=250,
    )


def test_needs_ocr_keeps_its_pages_because_they_are_routing_data() -> None:
    """`NEEDS_OCR` "fills `pages` -- it is routing data, not a failure" (`DriverError`'s own
    docstring). A guard that dropped `pages` would turn an escalation into a dead end."""

    def work(_io: DriverIO) -> DriverResult:
        raise DriverError(cls=FailureClass.NEEDS_OCR, message="scanned", pages=(3, 4, 9))

    assert run(guard(), work).failure == GuardFailure(
        failure_class=FailureClass.NEEDS_OCR, message="scanned", pages=(3, 4, 9)
    )


@pytest.mark.parametrize(
    "raised",
    [RuntimeError("boom"), KeyError("k"), TypeError("nope"), ZeroDivisionError("x")],
)
def test_anything_that_is_not_a_driver_error_becomes_driver_bug(raised: Exception) -> None:
    """02-architecture.md:1061, verbatim: "converts anything that is not a `DriverError` into
    `FailureClass.driver_bug`"."""

    def work(_io: DriverIO) -> DriverResult:
        raise raised

    outcome = run(guard(), work)
    assert outcome.failure is not None
    assert outcome.failure.failure_class is FailureClass.DRIVER_BUG
    assert type(raised).__name__ in outcome.failure.message


@pytest.mark.parametrize("raised", [SystemExit(3), KeyboardInterrupt()])
def test_a_base_exception_from_the_driver_does_not_propagate_into_the_loop(
    raised: BaseException,
) -> None:
    """02-architecture.md:1061 says `BaseException`, and it means it.

    Both of these are the driver's doing in its own frame: `sys.exit` is banned in library code
    framework-wide, and cancellation "propagates **by generation, not by signal**"
    (04-driver-system.md:1739), so neither is a signal the supervisor sent. Letting either escape
    is the one thing S1's row forbids.
    """

    def work(_io: DriverIO) -> DriverResult:
        raise raised

    outcome = run(guard(), work)
    assert outcome.failure is not None
    assert outcome.failure.failure_class is FailureClass.DRIVER_BUG


def test_a_host_detected_timeout_carries_no_retry_after_and_a_driver_error_could_not() -> None:
    """WHY `GuardFailure` exists, as an assertion rather than as a paragraph.

    `omniweave_ports.types:185-186`: `TRANSIENT_FAILURE_CLASSES` "is the driver half of that
    table", and it makes `retry_after_ms` REQUIRED for `timeout` -- correct for a driver that
    observed a slow remote peer. A HOST-detected timeout is `FAILED_PERMANENT`
    (04-driver-system.md:1728) and has no cooldown to give, so a guard that reported through
    `DriverError` would have to invent one. The two constructors are exercised side by side.
    """
    with pytest.raises(ValueError, match="requires retry_after_ms"):
        DriverError(cls=FailureClass.TIMEOUT, message="host-detected")
    failure = GuardFailure(
        failure_class=FailureClass.TIMEOUT, message="host-detected", limit="progress_ms"
    )
    assert failure.retry_after_ms is None
    assert failure.limit == "progress_ms"


def test_a_guard_outcome_carries_exactly_one_of_result_and_failure() -> None:
    """Neither and both are refused in the constructor, the discipline `DriverResult`'s own
    `__post_init__` applies to `ok_partial`."""
    with pytest.raises(ValueError, match="exactly one"):
        GuardOutcome()
    with pytest.raises(ValueError, match="exactly one"):
        GuardOutcome(result=OK, failure=GuardFailure(FailureClass.DRIVER_BUG, "both"))


# --------------------------------------------------------------------------------------------
# 4. The three deadlines
# --------------------------------------------------------------------------------------------


def test_the_three_deadlines_are_named_exactly_as_the_plan_names_them() -> None:
    """04-driver-system.md:1733-1735 and the `limit` strings its section 6.3 table prints.

    The values are the strings a failure carries, so they are read out of the document rather
    than agreed with: `limit = "progress_ms"` and `limit = "wall_ms_hard"` appear verbatim
    there.
    """
    text = (PLAN / "04-driver-system.md").read_text(encoding="utf-8")
    assert 'limit = "progress_ms"' in text
    assert 'limit = "wall_ms_hard"' in text
    assert [limit.value for limit in DeadlineLimit] == [
        "progress_ms",
        "wall_ms_hard",
        "deadline_ms",
    ]


def test_a_zero_on_a_card_means_unset_and_not_expired() -> None:
    """`IsolationSpec` defaults both deadlines to `0` for an absent key.

    Read naively, a card declaring neither would breach both before the driver's first statement.
    A card declaring nothing is the COMMON case, so this is the error in this file that would
    look most like a working timeout.
    """
    plain = card()
    assert (plain.isolation.progress_ms, plain.isolation.wall_ms_hard) == (0, 0)
    assert Deadlines.of_card(plain.isolation).enabled() == ()
    clock = Clock()
    subject = DriverGuard(candidate(), deadlines=NO_DEADLINES, monotonic_ns=clock)

    def work(_io: DriverIO) -> DriverResult:
        clock.now_ms = 10_000_000
        return OK

    assert run(subject, work).result is OK


def test_of_card_takes_two_deadlines_from_the_card_and_one_from_the_invocation() -> None:
    """`deadline_ms` "on the invocation (the caller's)" is not a card field at all."""
    declared = card("\n[isolation]\nprogress_ms = 30000\nwall_ms_hard = 600000\n")
    assert Deadlines.of_card(declared.isolation, deadline_ms=1234) == Deadlines(
        progress_ms=30_000, wall_ms_hard=600_000, deadline_ms=1234
    )


def test_a_breached_progress_deadline_discards_the_drivers_result() -> None:
    """04-driver-system.md:1728: `FAILED_PERMANENT{TIMEOUT}`, `limit = "progress_ms"`.

    The driver returned a perfectly good result; it is discarded, because a result produced after
    the deadline is a result the runtime has already stopped waiting for. That is the honest half
    of a watchdog that cannot preempt: it cannot stop the CPU, and it can refuse the row.
    """
    clock = Clock()
    subject = DriverGuard(candidate(), deadlines=Deadlines(progress_ms=100), monotonic_ns=clock)

    def work(_io: DriverIO) -> DriverResult:
        clock.now_ms = 150
        return OK

    outcome = run(subject, work)
    assert outcome.result is None
    assert outcome.failure is not None
    assert outcome.failure.failure_class is FailureClass.TIMEOUT
    assert outcome.failure.limit == DeadlineLimit.PROGRESS_MS.value


def test_progress_resets_the_progress_deadline() -> None:
    """`DriverIO.progress()` is the in-process `PROGRESS` frame, and it resets the clock.

    The driver works for 90 ms, reports progress, works another 60 ms and returns at 150 ms --
    past a 100 ms `progress_ms` in absolute terms, and 60 ms inside it since the reset.
    """
    clock = Clock()
    subject = DriverGuard(candidate(), deadlines=Deadlines(progress_ms=100), monotonic_ns=clock)

    def work(io: DriverIO) -> DriverResult:
        clock.now_ms = 90
        io.progress(3, 10)
        clock.now_ms = 150
        return OK

    outcome = run(subject, work)
    assert outcome.result is OK
    assert outcome.progress_calls == 1
    assert outcome.last_progress == (3, 10)


def test_log_does_not_reset_the_progress_deadline() -> None:
    """04-driver-system.md:1735-1737: "A `LOG` frame does not, and that is a deliberate
    correction of the obvious design: a driver logging in a tight loop while making no progress
    would otherwise look alive forever, which is the failure `progress_ms` exists to catch."

    Identical to the test above except for the one call, which is the point: the same 90 ms /
    150 ms schedule times out when the driver logs and does not when it reports progress.
    """
    clock = Clock()
    sink: list[tuple[str, dict[str, object]]] = []
    subject = DriverGuard(candidate(), deadlines=Deadlines(progress_ms=100), monotonic_ns=clock)

    def work(io: DriverIO) -> DriverResult:
        clock.now_ms = 90
        io.log("still_here", page=4)
        clock.now_ms = 150
        return OK

    outcome = run(subject, work, log_sink=lambda event, fields: sink.append((event, dict(fields))))
    assert outcome.result is None
    assert outcome.failure is not None
    assert outcome.failure.limit == DeadlineLimit.PROGRESS_MS.value
    assert outcome.logs == 1
    assert sink == [("still_here", {"page": 4})]


def test_progress_cannot_extend_the_wall_clock() -> None:
    """04-driver-system.md:1794: "`progress_ms` resets, but `wall_ms_hard` does not, and it is
    the backstop. A driver cannot extend its own wall clock."

    The driver reports progress every 50 ms for 600 ms against a 500 ms `wall_ms_hard`, which is
    04-driver-system.md:1794's `PROGRESS`-flood row played out in process.
    """
    clock = Clock()
    subject = DriverGuard(
        candidate(),
        deadlines=Deadlines(progress_ms=100, wall_ms_hard=500),
        monotonic_ns=clock,
    )

    def work(io: DriverIO) -> DriverResult:
        for tick in range(1, 13):
            clock.now_ms = tick * 50
            io.progress(tick, 12)
        return OK

    outcome = run(subject, work)
    assert outcome.failure is not None
    assert outcome.failure.limit == DeadlineLimit.WALL_MS_HARD.value


def test_the_callers_deadline_is_the_third_and_is_reported_under_its_own_name() -> None:
    """`deadline_ms` is the caller's, is what `DriverIO.deadline_ms` carries, and has its own
    `limit` string -- three deadlines, "separate and separately named"."""
    clock = Clock()
    subject = DriverGuard(candidate(), deadlines=Deadlines(deadline_ms=200), monotonic_ns=clock)

    def work(io: DriverIO) -> DriverResult:
        assert io.deadline_ms == 200
        clock.now_ms = 201
        return OK

    outcome = run(subject, work)
    assert outcome.failure is not None
    assert outcome.failure.limit == DeadlineLimit.DEADLINE_MS.value


def test_when_two_deadlines_have_both_elapsed_progress_ms_is_the_one_reported() -> None:
    """OUR precedence, pinned here because the plan prints no order for a double breach.

    04-driver-system.md:1728-1729 lists the silent hang before the chatty one and gives each its
    own `limit` string, and says nothing about a wake at which both have elapsed. `progress_ms`
    wins because it is the more specific diagnosis. Nothing else in the tree pins this.
    """
    clock = Clock()
    subject = DriverGuard(
        candidate(),
        deadlines=Deadlines(progress_ms=100, wall_ms_hard=120, deadline_ms=130),
        monotonic_ns=clock,
    )

    def work(_io: DriverIO) -> DriverResult:
        clock.now_ms = 5_000
        return OK

    outcome = run(subject, work)
    assert outcome.failure is not None
    assert outcome.failure.limit == DeadlineLimit.PROGRESS_MS.value


@pytest.mark.parametrize(
    ("at_ms", "limit"),
    [
        (99, None),
        (100, DeadlineLimit.PROGRESS_MS),
        (101, DeadlineLimit.PROGRESS_MS),
    ],
)
def test_a_deadline_fires_at_exactly_its_bound_and_not_a_millisecond_before(
    at_ms: int, limit: DeadlineLimit | None
) -> None:
    """`_breach()` compares `spent >= bound * _MS`, and the `=` was pinned by nothing.

    Every other deadline test in this file overshoots -- 150 ms against 100, 201 against 200 --
    so relaxing the comparison to `spent > bound * _MS` left all thirty-nine of them green. A
    bound tested only from well above cannot distinguish `>` from `>=`, which is the same
    argument `test_host_wire.py` makes for its three caps, and here it decides whether a driver
    that finishes on the exact millisecond of its `progress_ms` keeps its result or loses it.

    OUR choice is `>=`: `progress_ms` is a budget and a budget fully spent is spent. The 99 ms
    row is the other side of the boundary, so this pins a comparison and not merely a direction.
    """
    clock = Clock()
    subject = DriverGuard(candidate(), deadlines=Deadlines(progress_ms=100), monotonic_ns=clock)

    def work(_io: DriverIO) -> DriverResult:
        clock.now_ms = at_ms
        return OK

    outcome = run(subject, work)
    if limit is None:
        assert outcome.result is OK
        assert outcome.failure is None
    else:
        assert outcome.result is None
        assert outcome.failure is not None
        assert outcome.failure.limit == limit.value


class HoldingClock:
    """A monotonic clock that HOLDS the watchdog thread inside its first reading.

    The watchdog's first act is `_next_wait_s()`, which reads the clock, so blocking that read
    parks the thread for a known interval while the driver's own thread runs on. That is what
    turns "the thread is joined" into an observable fact: without the `join()` the invocation
    returns while this thread is still parked, and `threading.enumerate()` can see it.

    Only the watchdog is held -- the guard's own `started_ns` read happens on the caller's
    thread, and holding that would just delay the test.
    """

    HOLD_S: ClassVar[float] = 0.4

    def __init__(self) -> None:
        self.entered = threading.Event()

    def __call__(self) -> int:
        watchdog = threading.current_thread().name.startswith("ow-inproc-watchdog")
        if watchdog and not self.entered.is_set():
            self.entered.set()
            time.sleep(self.HOLD_S)
        return 0


def test_the_watchdog_thread_is_gone_before_invoke_returns() -> None:
    """`_start_watchdog`'s docstring claims the `join()` in `invoke()`'s `finally` leaves "no
    thread still holding its state", and nothing asserted it.

    Deleting `watchdog.join()` left every test green, because a watchdog released by `stop.set()`
    exits in microseconds and no test looked. A leaked thread here is not cosmetic: it holds a
    reference to the `_CallState` of a finished invocation and races the `state.closed = True`
    that `_state_of()` relies on, so a driver's next call could see a half-torn-down ledger.

    The clock parks the watchdog for 400 ms, so at the moment `invoke()` returns the thread is
    either joined (the assertion below holds) or parked and visible (it does not). Two
    non-vacuity assertions come first: the thread was really started, and it really entered the
    held read -- without them a guard that never spawned a watchdog would pass.
    """
    clock = HoldingClock()
    subject = DriverGuard(candidate(), deadlines=Deadlines(wall_ms_hard=5_000), monotonic_ns=clock)
    names: list[str] = []

    def work(_io: DriverIO) -> DriverResult:
        assert clock.entered.wait(5.0) is True
        names.extend(
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("ow-inproc-watchdog")
        )
        return OK

    outcome = run(subject, work)
    assert names == ["ow-inproc-watchdog-parse.office.anydoc"]
    assert clock.entered.is_set()
    assert [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("ow-inproc-watchdog")
    ] == []
    assert outcome.result is OK


def test_a_cooperative_driver_sees_cancelled_go_true_when_the_watchdog_fires() -> None:
    """The one test that observes the watchdog THREAD, on the real clock.

    `DriverIO.cancelled()` is "checked at every loop top" (04-driver-system.md:1738) and the
    thread flipping it is the whole of what the guard can do to a running driver. The poll is
    bounded twice -- by an iteration count and by a wall budget -- so a watchdog that never fires
    fails the test instead of hanging it.
    """
    subject = DriverGuard(candidate(), deadlines=Deadlines(progress_ms=1))
    seen = {"loops": 0}

    def work(io: DriverIO) -> DriverResult:
        deadline = time.monotonic() + 5.0
        while not io.cancelled() and time.monotonic() < deadline:
            seen["loops"] += 1
        seen["cancelled"] = io.cancelled()
        return OK

    outcome = run(subject, work)
    assert seen["cancelled"] is True
    assert outcome.failure is not None
    assert outcome.failure.limit == DeadlineLimit.PROGRESS_MS.value


def test_no_watchdog_thread_is_started_when_no_deadline_is_declared() -> None:
    """A thread per invocation is a real cost on a one-shot `ow parse`, and a guard with no
    deadline to watch has nothing to wake for."""
    before = threading.active_count()

    def work(_io: DriverIO) -> DriverResult:
        assert threading.active_count() == before
        return OK

    assert run(guard(clock=Clock()), work).result is OK


def test_cancellation_is_not_a_failure_and_the_drivers_result_survives_it() -> None:
    """ "A superseded result **writes nothing**" (04-driver-system.md:1740) is the runtime's
    commit predicate, not the guard's verdict.

    So a driver that noticed `cancelled()` and returned early returns a real `DriverResult`, and
    `GuardOutcome.cancelled` is what tells the runtime the generation moved. `DriverResult`
    cannot claim `cancelled` itself (INV-7), which is why the flag rides on the outcome.
    """
    subject = guard(clock=Clock())
    held: list[DriverIO] = []

    def work(io: DriverIO) -> DriverResult:
        held.append(io)
        subject.cancel(io)
        assert io.cancelled() is True
        return OK

    outcome = run(subject, work)
    assert outcome.result is OK
    assert outcome.failure is None
    assert outcome.cancelled is True


# --------------------------------------------------------------------------------------------
# 5. The DriverIO the guard supplies
# --------------------------------------------------------------------------------------------


def test_the_supplied_io_has_the_four_fields_inv_6_audits_and_no_more() -> None:
    """INV-6's audit question is literally "count `DriverIO`'s fields". The answer stays four.

    `GuardIO` adds behaviour and no state: per-call state lives in a `WeakKeyDictionary` keyed on
    the io, the idiom `omniweave_ports.types` uses for its own output meter. `__slots__ = ()` is
    what makes the absence of a `__dict__` a structural fact rather than a convention.
    """
    assert [f.name for f in dataclasses.fields(GuardIO)] == [
        "blobs",
        "tmpdir",
        "deadline_ms",
        "max_output_bytes",
    ]
    assert [f.name for f in dataclasses.fields(DriverIO)] == [
        f.name for f in dataclasses.fields(GuardIO)
    ]
    held: list[DriverIO] = []
    run(guard(clock=Clock()), lambda io: held.append(io) or OK)
    assert not hasattr(held[0], "__dict__")
    assert isinstance(held[0], DriverIO)


def test_the_io_carries_the_invocations_ceiling_and_the_hosts_roots() -> None:
    """`max_output_bytes` is the number `ArtifactRef.of` meters the running total against
    (04-driver-system.md:1795, "on the host's number"), and `tmpdir` is the one writable
    surface."""
    held: list[DriverIO] = []
    run(guard(clock=Clock()), lambda io: held.append(io) or OK)
    assert (held[0].tmpdir, held[0].max_output_bytes) == (TMPDIR, 4 * 1024 * 1024)


def test_the_io_carries_the_exact_blob_store_the_host_handed_the_guard() -> None:
    """`blobs` is the first of INV-6's four fields and was the one nothing checked.

    The guard never touches the store -- `Blobs.open` and `Blobs.put` raise if it does -- so
    replacing `blobs=blobs` with `blobs=None` inside `invoke()` left every test green while
    handing every driver an io whose read-only blob root is `None`. Identity and not equality:
    the store is a host object, and a copy of it would be a second handle to the same bytes.
    """
    store = Blobs()
    held: list[DriverIO] = []
    outcome = guard(clock=Clock()).invoke(
        lambda io: held.append(io) or OK,  # type: ignore[arg-type, func-returns-value]
        blobs=store,
        tmpdir=TMPDIR,
        max_output_bytes=1024,
    )
    assert outcome.result is OK
    assert held[0].blobs is store
    assert held[0].blobs.path("abc") == "/ro/abc"


def test_no_services_is_a_read_only_mapping_a_driver_cannot_poison() -> None:
    """`NO_SERVICES` is a module singleton shared by every invocation that names no Service.

    `assert NO_SERVICES == {}` passes against a plain `dict` just as well, so replacing the
    `MappingProxyType({})` with `{}` changed no test's colour -- and a bare dict as a shared
    default is one `services[name] = handle` away from granting every later invocation in the
    process a Service the operator never attached. The refusal is the type's, so the type is
    what is asserted.
    """
    assert isinstance(NO_SERVICES, MappingProxyType)
    with pytest.raises(TypeError):
        NO_SERVICES["layout"] = SimpleNamespace()  # type: ignore[index]
    assert dict(NO_SERVICES) == {}


def test_service_refuses_by_naming_the_service_that_is_missing() -> None:
    """`CapabilityMissing.missing` "is machine-actionable" and exit 64.

    `omniweave_core.modelserver` -- 08-runtime.md section 3.2's attach-or-spawn ladder -- lands
    at P4 W4.9 (16-roadmap.md:549), so at P3 every S1 invocation is handed `NO_SERVICES` and a
    driver naming one gets a refusal that names it rather than an `AttributeError`.
    """
    assert NO_SERVICES == {}
    failures: list[BaseException] = []

    def work(io: DriverIO) -> DriverResult:
        try:
            io.service("layout")
        except CapabilityMissing as exc:
            failures.append(exc)
        return OK

    run(guard(clock=Clock()), work)
    assert isinstance(failures[0], CapabilityMissing)
    assert failures[0].missing == ("service:layout",)
    assert failures[0].EXIT == 64


def test_service_returns_a_handle_the_host_attached() -> None:
    handle = SimpleNamespace(name="layout", base_url="http://127.0.0.1:9", token="tok")  # noqa: S106
    held: list[object] = []

    def work(io: DriverIO) -> DriverResult:
        held.append(io.service("layout"))
        return OK

    run(guard(clock=Clock()), work, services={"layout": handle})
    assert held[0] is handle


def test_an_io_kept_past_its_invocation_is_refused() -> None:
    """A driver that stashes its `DriverIO` and calls it later is writing into a finished call.

    In a worker the process is gone, so 04-driver-system.md section 6.5 has no row for this; in
    process it is not, so the refusal is explicit. `cancelled()` is the deliberate exception and
    answers `True`: it is the one method a driver calls in its own hot loop, and telling a stale
    loop to stop beats raising into it.
    """
    held: list[DriverIO] = []
    run(guard(clock=Clock()), lambda io: held.append(io) or OK)
    stale = held[0]
    assert stale.cancelled() is True
    for call in (
        lambda: stale.log("late"),
        lambda: stale.progress(1, 2),
        lambda: stale.service("s"),
    ):
        with pytest.raises(DriverHostError, match="invocation is over"):
            call()


# --------------------------------------------------------------------------------------------
# 6. Purity, and what makes this Windows cell test the same property a POSIX one would
# --------------------------------------------------------------------------------------------


def test_the_guard_imports_no_loop_no_signal_and_no_process_control() -> None:
    """A pinned literal import set over the module's own `ast`.

    `asyncio` and `selectors` are G23; `subprocess` has exactly two permitted homes and this is
    neither; `signal`, `resource` and `os` are absent because the S1 watchdog is a thread and an
    event, which is exactly why this file's assertions are platform-independent. `time` is here
    only as the default value of a parameter.
    """
    tree = ast.parse(Path(inproc.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots == {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "omniweave_core",
        "omniweave_ports",
        "threading",
        "time",
        "types",
        "typing",
        "weakref",
    }


def test_the_clock_is_a_parameter_and_the_guard_never_reads_a_wall_clock() -> None:
    """`time.time` is banned in library code; a duration is `time.monotonic_ns`, injected.

    The assertion is over the source rather than over behaviour because a wall-clock read that
    happens once in an unusual branch is exactly the shape a behavioural test misses.
    """
    source = Path(inproc.__file__).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
    ]
    assert calls == []
    assert "time.monotonic_ns" in source
    exits = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in {"_exit", "exit"}
    ]
    assert exits == []
