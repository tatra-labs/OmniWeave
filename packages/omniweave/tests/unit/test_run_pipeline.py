"""The middleware order, against the diagram that is its specification.

`08-runtime.md` section 2.4 does not describe the chain in prose, it **draws** it, and three of the
tests here read that drawing rather than a transcription of it:

* `test_the_order_is_the_diagram_read_top_to_bottom` parses the ```text fence at `08:832` and
  compares its indentation tree to `LAYER_ORDER`;
* `test_02_and_08_agree_about_the_order` parses `02-architecture.md:481`'s arrow list and compares
  the same tuple, so the two documents cannot drift apart without a failure here;
* `test_the_cache_layer_table_is_the_plans_own` parses `08:856-869`'s table and asserts both what
  is in `CACHE_LAYER_BY_OPERATOR` and what is deliberately not.

The rest are the order's consequences. Two of them are the property tests `08:850-852` names in as
many words -- I25 (a cache hit through a zero-headroom ledger) and I8 (no billable work without a
reservation) -- and the file is arranged so that those two sit together, because the whole point of
the section is that neither is true of the layers and both are true of the ordering.

## The test that is a defect report

`test_a_billed_api_driver_has_no_declared_rate_to_limit_against` walks every card shape the driver
system declares and shows that `rate_limit_rps` exists only under `[acquire]`. `with_rate_limiting`
is in the chain for every driver, and for the `billed_api` drivers it exists to protect there is no
number to read -- the only rate control is reactive, after a 429. D162.
"""

from __future__ import annotations

import ast
import pathlib
import re
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route.spend import Spend
from omniweave.run import pipeline as pipeline_module
from omniweave.run.dispatch import Batch, dispatch_key
from omniweave.run.pipeline import (
    CACHE_LAYER_BY_OPERATOR,
    DEFAULT_MAX_ATTEMPTS,
    HIT_VERDICTS,
    LAYER_ORDER,
    Admitter,
    BudgetVerdict,
    CacheDecision,
    Call,
    Chaos,
    LedgerAdmitter,
    Reply,
    RequestCount,
    RetryGuard,
    TokenBucket,
    build,
    cache_layer_for,
    chaos_fires,
    decision_of,
    prober,
    verdict_of,
    with_budget,
    with_cache,
    with_events,
    with_fault_injection,
    with_metrics,
    with_rate_limiting,
    with_request_count,
    with_retries,
)
from omniweave_core.budget import (
    Admitted,
    Deferred,
    Degraded,
    Reservation,
    admission_of,
)
from omniweave_core.cache import CacheHit, CacheLayer, CacheProbe, CacheVerdict
from omniweave_core.drivers import card as card_module
from omniweave_core.errors import ConfigError, ResourceLimit, RouteError
from omniweave_core.events import EventKind
from omniweave_core.observe.degradation import Degradation
from omniweave_core.operator import Outcome
from omniweave_core.work import WORK_COLUMNS, WorkRow
from omniweave_ports.types import ArtifactRef, FailureClass, Isolation, UnitRef

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from conftest import PlanDocs


URI = "file:///corpus/a.pdf"
DIGEST = "d" * 64
KEY = dispatch_key("parse.pdf.pdfium", DIGEST, Isolation.SUBPROC.value)


class FakeClock:
    """`Clock` with a settable monotonic reading. Nothing here needs a wall reading."""

    def __init__(self) -> None:
        self.mono = 0

    def monotonic_ns(self) -> int:
        return self.mono

    def wall_ns(self) -> int:  # pragma: no cover -- the chain measures durations only.
        return 0

    def advance_ms(self, ms: int) -> None:
        self.mono += ms * 1_000_000


def row(row_id: int = 1, *, part: str = "p1", operator: str = "parse.pdf") -> WorkRow:
    values: dict[str, object] = {}
    values.update(dict.fromkeys(WORK_COLUMNS))
    values.update(
        id=row_id,
        unit_uri=URI,
        unit_part=part,
        operator=operator,
        op_version=1,
        cache_key="k" * 64,
        decision_id=f"dec_{row_id}",
        driver="parse.pdf.pdfium",
        cost_class="billed_api",
        dispatch_key=KEY,
        status="claimed",
        attempts_total=1,
        attempts_today=1,
        cost_micros=0,
        queued_ms=0,
        ran_ms=0,
        peak_rss_bytes=0,
        priority=0,
    )
    return WorkRow.from_row(tuple(values[name] for name in WORK_COLUMNS))


def unit(part: str = "p1", *, uri: str = URI) -> UnitRef:
    return UnitRef(uri=uri, part=part, content_sha256="a" * 64, byte_len=10, media_type=None)


def call_of(n: int = 2, *, operator: str = "parse.pdf") -> Call:
    rows = tuple(row(i + 1, part=f"p{i + 1}", operator=operator) for i in range(n))
    return Call(
        batch=Batch(invoke_id="iv_1", rows=rows),
        units=tuple(unit(f"p{i + 1}") for i in range(n)),
        operator=operator,
    )


def ok_reply(call: Call, *, micros: int = 7) -> Reply:
    return Reply(
        outcomes=(Outcome.OK,) * call.size,
        produced=((ArtifactRef(kind="doc_fragment", byte_len=1, inline=b"x", blob=None),),)
        * call.size,
        spend=(Spend(calls=1),) * call.size,
        micros=(micros,) * call.size,
    )


def host_that(reply_for: Any = ok_reply, *, seen: list[Call] | None = None) -> Any:
    def host(call: Call) -> Reply:
        if seen is not None:
            seen.append(call)
        return reply_for(call)

    return host


def nothing(**_fields: object) -> None:
    """An `emit` that drops. `[observe] sinks = []` is the shipped way to turn the stream off."""
    return


# =============================================================================================
# 1. The order is the diagram
# =============================================================================================


def _section(plan: PlanDocs, heading: str) -> tuple[str, ...]:
    """One `###` section's lines, from its heading to the next one.

    Read by line rather than through `PlanDocs.fences`, because 08:831's fence is **bare** -- no
    language tag -- and a scanner keyed on the opening marker cannot tell a bare opener from
    another fence's closer. The section bound is unambiguous and needs no such guess.
    """
    lines = plan.lines("08-runtime.md")
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("### ")),
        len(lines),
    )
    return tuple(lines[start:end])


def _drawing(plan: PlanDocs) -> tuple[str, ...]:
    """The bare fence's body inside section 2.4, stripped."""
    body = _section(plan, "### 2.4 ")
    opened = body.index("```")
    closed = body.index("```", opened + 1)
    return tuple(line for line in body[opened + 1 : closed] if line.strip())


def _diagram(plan: PlanDocs) -> tuple[str, ...]:
    """The layer names of `08:832`'s drawing, outermost first, in the order they are drawn."""
    names: list[str] = []
    for line in _drawing(plan):
        found = re.search(r"^[ |\-]*(with_[a-z_]+)", line)
        if found and found.group(1) not in names:
            names.append(found.group(1))
    if not names:
        raise AssertionError("08 section 2.4's middleware diagram is gone")
    return tuple(names)


def test_the_order_is_the_diagram_read_top_to_bottom(plan: PlanDocs) -> None:
    """`LAYER_ORDER` is `08:832-845`, parsed. Not a transcription of it -- the fence itself.

    The diagram is the specification (*"the middleware order is the artifact"*), so the constant
    this module composes from has to be checkable against the drawing rather than against a second
    list somebody typed while reading it.
    """
    plan.require()
    assert _diagram(plan) == LAYER_ORDER


def test_the_diagram_bottoms_out_at_the_host(plan: PlanDocs) -> None:
    """The last line below the eight is `DriverHost.invoke(batch)` -- what `build()` wraps."""
    plan.require()
    assert _drawing(plan)[-1].strip().endswith("DriverHost.invoke(batch)")


def test_02_and_08_agree_about_the_order(plan: PlanDocs) -> None:
    """`02:481`'s arrow list, read left to right, is the same eight in the same order.

    Two documents naming one ordering is exactly the shape INV-21 is about, and the cheapest way to
    keep them from drifting is to fail here when they do.
    """
    plan.require()
    hits = plan.grep(r"with_events .{0,3} with_request_count", documents=("02-architecture.md",))
    assert len(hits) == 1, "02:481's middleware row moved"
    named = tuple(re.findall(r"`?\bwith_[a-z_]+", hits[0].text.replace("`", "")))
    assert named == LAYER_ORDER


def test_the_only_caller_rule_names_this_file(repo_root: Path) -> None:
    """G8's `omniweave-no-driverhost-invoke-outside-pipeline` excludes exactly two paths.

    `pipeline.py` because it is the permitted caller, and `omniweave_core/host/**` because that is
    where `invoke()` is defined. A third exclusion would make "the only caller" a list.
    """
    bank = (repo_root / "tools" / "semgrep" / "omniweave.yaml").read_text(encoding="utf-8")
    rule = bank.split("id: omniweave-no-driverhost-invoke-outside-pipeline", 1)[1]
    rule = rule.split("metadata:", 1)[0]
    excluded = re.findall(r'-\s+"([^"]+)"', rule.split("exclude:", 1)[1])
    assert excluded == [
        "packages/omniweave/src/omniweave/run/pipeline.py",
        "packages/omniweave-core/src/omniweave_core/host/**",
    ]


def test_no_layer_is_missing_from_build() -> None:
    """Every name in `LAYER_ORDER` is a function in this module and is applied by `build()`.

    An AST scan rather than a call, because the point is that the composition mentions all eight: a
    layer that existed and was never wrapped would pass every behavioural test in this file by
    being absent from the chain it is supposed to be in.
    """
    source = pathlib.Path(pipeline_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert set(LAYER_ORDER) <= defined
    build_fn = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build"
    )
    called = {
        node.func.id
        for node in ast.walk(build_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert set(LAYER_ORDER) <= called


# =============================================================================================
# 2. The cache-layer table
# =============================================================================================


def _layer_table(plan: PlanDocs) -> tuple[tuple[tuple[str, ...], str], ...]:
    """`08:856-869`'s table as `((operators...), layer)` per row, operators read as `x.y` tokens."""
    rows: list[tuple[tuple[str, ...], str]] = []
    started = False
    for line in plan.lines("08-runtime.md"):
        if line.startswith("| operator | `CacheLayer` probed |"):
            started = True
            continue
        if not started:
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or set(cells[0]) <= set("-: "):
            continue
        operators = tuple(
            token
            for token in re.findall(r"`([^`]+)`", cells[0])
            if re.fullmatch(r"[a-z_]+\.[a-z_*]+", token)
        )
        rows.append((operators, cells[1].strip("`")))
    return tuple(rows)


def test_the_cache_layer_table_is_the_plans_own(plan: PlanDocs) -> None:
    """Ten rows in the document; eleven operator keys here, and two rows that are not operators.

    The two are *"the raster step inside a `render`-requiring decision"* and *"`evaluate()`'s signal
    computation"* -- steps inside the router rather than `work` rows -- and they are the reason
    `CacheLayer` has five members while this table has three. Asserting that the excluded rows are
    exactly the `render` and `signal` ones is what keeps the exclusion a reading of the table rather
    than a convenience.
    """
    plan.require()
    table = _layer_table(plan)
    assert len(table) == 10, f"08 section 2.4's table has {len(table)} rows"

    without_operator = {layer for operators, layer in table if not operators}
    claimed = {layer for operators, layer in table if operators and layer != "none"}
    assert claimed == {"blob", "call", "embed"}
    assert {member.value for member in CacheLayer} - claimed == {"render", "signal"}
    assert without_operator == {"render", "signal"}

    expected: dict[str, CacheLayer | None] = {}
    for operators, layer in table:
        for name in operators:
            expected[name] = None if layer == "none" else CacheLayer(layer)
    assert expected == dict(CACHE_LAYER_BY_OPERATOR)


def test_an_operator_with_no_layer_skips_the_query_entirely() -> None:
    """`08:870`: *"An operator with no layer skips `with_cache` entirely rather than probing a layer
    it can never hit -- which is what makes a 100%-cache-hit `ow ingest` issue zero cache queries
    for `acquire.fs`."*"""
    assert cache_layer_for("acquire.fs") is None
    assert cache_layer_for("acquire.http") is CacheLayer.BLOB
    assert cache_layer_for("parse.pdf") is CacheLayer.CALL
    assert cache_layer_for("embed.text") is CacheLayer.EMBED
    for name in ("op.identify", "op.converge", "op.lexicon", "op.resolve", "op.cluster"):
        assert cache_layer_for(name) is None


def test_an_operator_outside_the_table_is_refused_rather_than_defaulted() -> None:
    """Guessing `None` would silently turn a billed driver's cache off, which no test would see."""
    with pytest.raises(ConfigError, match=r"no row in 08 section 2\.4"):
        cache_layer_for("summarise.llm")


# =============================================================================================
# 3. I25 -- a cache hit costs nothing
# =============================================================================================


class DenyingAdmitter:
    """An `Admitter` that refuses every dimension. The zero-headroom ledger, as a double."""

    def __init__(self) -> None:
        self.admits = 0
        self.commits = 0
        self.releases = 0

    def admit(self, call: Call) -> BudgetVerdict:  # noqa: ARG002
        self.admits += 1
        return BudgetVerdict(admission="deferred", deferred_dim="micros")

    def commit(self, call: Call, verdict: BudgetVerdict, spend: Any) -> None:  # noqa: ARG002
        self.commits += 1

    def release(self, call: Call, verdict: BudgetVerdict) -> None:  # noqa: ARG002
        self.releases += 1


class GrantingAdmitter(DenyingAdmitter):
    def admit(self, call: Call) -> BudgetVerdict:  # noqa: ARG002
        self.admits += 1
        return BudgetVerdict(admission="admitted", reservations=("res_1",))


def all_hits(call: Call, layer: CacheLayer) -> CacheDecision:  # noqa: ARG001
    return CacheDecision(
        verdicts=(CacheVerdict.HIT,) * call.size,
        produced=((ArtifactRef(kind="doc_fragment", byte_len=1, inline=b"c", blob=None),),)
        * call.size,
        spend=(Spend(gpu_ms=2400),) * call.size,
        micros=(553,) * call.size,
        would_have_been_micros=553 * call.size,
    )


def test_a_hit_returns_through_a_zero_headroom_ledger() -> None:
    """**I25**, and `08:850`'s first property test in as many words: *"a cache hit with a
    zero-headroom ledger still returns `SKIPPED_CACHED`."*

    Everything below `with_cache` is instrumented and everything below `with_cache` records zero
    calls: `02:481`'s *"zero budget, zero tokens, zero rate-limit slots consumed"*, asserted rather
    than asserted-about.
    """
    admitter = DenyingAdmitter()
    clock = FakeClock()
    bucket = TokenBucket(4, clock=clock)
    seen: list[Call] = []
    slept: list[float] = []
    handler = build(
        host_that(seen=seen),
        emit=nothing,
        probe=all_hits,
        cache_layer=CacheLayer.CALL,
        admitter=admitter,
        guard=RetryGuard(),
        should_retry=lambda _reply, _attempt: False,
        bucket=bucket,
        clock=clock,
        record=lambda *_: None,
        sleep=slept.append,
    )
    reply = handler(call_of(3))

    assert reply.outcomes == (Outcome.SKIPPED_CACHED,) * 3
    assert reply.stopped_at == "with_cache"
    assert admitter.admits == 0, "a hit reserved budget"
    assert seen == [], "a hit constructed a driver call"
    assert slept == [], "a hit consumed a rate-limit slot"
    assert reply.micros == (553, 553, 553), "the hit's micros are re-priced, not dropped"
    assert reply.would_have_been_micros == 1659


def test_a_hit_is_counted_as_a_request_and_not_as_a_provider_call() -> None:
    """`with_request_count` is ABOVE the cache and `with_metrics` is BELOW it, so the difference
    between the two counts is the cache's contribution -- and neither has to know it exists."""
    counter = RequestCount()
    clock = FakeClock()
    measured: list[int] = []
    handler = build(
        host_that(),
        emit=nothing,
        counter=counter,
        probe=all_hits,
        cache_layer=CacheLayer.CALL,
        clock=clock,
        record=lambda _c, _r, ms: measured.append(ms),
    )
    handler(call_of(2))
    assert counter.attempted == 1
    assert counter.succeeded == 1
    assert measured == [], "the provider was measured for a call it never saw"


# =============================================================================================
# 4. I8 -- no billable work without a reservation
# =============================================================================================


def all_misses(call: Call, layer: CacheLayer) -> CacheDecision:  # noqa: ARG001
    return CacheDecision(verdicts=(CacheVerdict.MISS,) * call.size)


def test_every_path_to_the_host_passed_admit() -> None:
    """**I8**, and `08:851`'s second property test: *"`with_budget` inside `with_cache` plus outside
    `with_retries` means no billable work happens without a reservation."*"""
    admitter = GrantingAdmitter()
    seen: list[Call] = []
    handler = build(
        host_that(seen=seen),
        emit=nothing,
        probe=all_misses,
        cache_layer=CacheLayer.CALL,
        admitter=admitter,
    )
    handler(call_of(2))
    assert admitter.admits == 1
    assert len(seen) == 1


def test_a_denial_short_circuits_to_deferred_budget_and_is_not_a_failure() -> None:
    """`08:2285`: *"A denial is never a failure."* `DEFERRED_BUDGET` carries the dimension that
    bound, and `with_request_count` counts the call as a success on the way back out."""
    admitter = DenyingAdmitter()
    counter = RequestCount()
    seen: list[Call] = []
    handler = build(host_that(seen=seen), emit=nothing, counter=counter, admitter=admitter)
    reply = handler(call_of(2))
    assert reply.outcomes == (Outcome.DEFERRED_BUDGET,) * 2
    assert reply.deferred_dim == "micros"
    assert reply.stopped_at == "with_budget"
    assert seen == []
    assert (counter.succeeded, counter.failed) == (1, 0)


def test_a_retry_re_enters_below_the_reservation_and_above_the_limiter() -> None:
    """The two halves of `with_retries`' placement, in one run.

    `with_budget` is OUTSIDE, so three attempts hold one reservation -- a `REGEN` that
    re-reserved would double-bill the page `08:925` is about. `with_rate_limiting` is INSIDE, so
    each attempt takes its own slot: `08:838`'s *"a retry gets back in line."*
    """
    admitter = GrantingAdmitter()
    clock = FakeClock()
    slept: list[float] = []
    attempts: list[int] = []

    def host(call: Call) -> Reply:
        attempts.append(call.attempt)
        return Reply.of(Outcome.FAILED_TRANSIENT, call.size)

    handler = build(
        host,
        emit=nothing,
        admitter=admitter,
        guard=RetryGuard(),
        should_retry=lambda _reply, attempt: attempt < 3,
        bucket=TokenBucket(1, clock=clock),
        sleep=slept.append,
    )
    handler(call_of(1))

    assert attempts == [1, 2, 3], "the retry loop is inside the reservation"
    assert admitter.admits == 1, "a retry re-reserved"
    assert len(slept) == 2, "a retry did not get back in line for a rate-limit slot"


def test_the_reservation_is_released_when_nothing_spent_and_committed_when_something_did() -> None:
    """`05:2537` releases the over-reservation at commit; `store/budget.py`'s
    `RELEASE_REMAINING_SQL` sweeps the rest, and D141 is what happens when neither runs."""
    spent = GrantingAdmitter()
    build(host_that(), emit=nothing, admitter=spent)(call_of(1))
    assert (spent.commits, spent.releases) == (1, 0)

    free = GrantingAdmitter()
    build(host_that(lambda call: Reply.of(Outcome.OK, call.size)), emit=nothing, admitter=free)(
        call_of(1)
    )
    assert (free.commits, free.releases) == (0, 1)


def test_a_raising_host_releases_rather_than_leaking_the_reservation() -> None:
    admitter = GrantingAdmitter()

    def host(call: Call) -> Reply:  # noqa: ARG001
        raise RuntimeError("the worker died")

    with pytest.raises(RuntimeError):
        build(host, emit=nothing, admitter=admitter)(call_of(1))
    assert admitter.releases == 1


# =============================================================================================
# 5. Narrowing and widening
# =============================================================================================


def half_hit(call: Call, layer: CacheLayer) -> CacheDecision:  # noqa: ARG001
    verdicts = tuple(
        CacheVerdict.HIT if index % 2 == 0 else CacheVerdict.MISS for index in range(call.size)
    )
    return CacheDecision(
        verdicts=verdicts,
        micros=tuple(100 if v in HIT_VERDICTS else 0 for v in verdicts),
    )


def test_a_partial_hit_dispatches_only_the_misses() -> None:
    """`08:1795`: *"`outstanding` is what gets dispatched."* The batch is re-cut with the units, so
    the `call` span below carries the real width and AIMD adapts against it."""
    seen: list[Call] = []
    handler = build(host_that(seen=seen), emit=nothing, probe=half_hit, cache_layer=CacheLayer.CALL)
    reply = handler(call_of(4))

    assert len(seen) == 1
    inner = seen[0]
    assert inner.size == 2
    assert inner.batch.size == 2, "the batch was not narrowed with the units"
    assert [u.part for u in inner.units] == ["p2", "p4"]
    assert inner.origin == (1, 3)
    assert reply.outcomes == (
        Outcome.SKIPPED_CACHED,
        Outcome.OK,
        Outcome.SKIPPED_CACHED,
        Outcome.OK,
    )


def test_widening_puts_every_answer_back_at_its_own_index() -> None:
    """The merge is by origin index and not by order of arrival: a reply whose slots drifted would
    attribute one page's spend to another, which is I30's whole subject."""
    handler = build(
        host_that(lambda call: ok_reply(call, micros=9)),
        emit=nothing,
        probe=half_hit,
        cache_layer=CacheLayer.CALL,
    )
    reply = handler(call_of(4))
    assert reply.micros == (100, 9, 100, 9)


def test_narrowing_to_nothing_is_refused_because_the_caller_short_circuits() -> None:
    with pytest.raises(RouteError, match="narrowing a call to no units"):
        call_of(2).narrowed(())


def test_narrowing_refuses_an_unordered_or_repeated_index_list() -> None:
    with pytest.raises(RouteError, match="strictly increasing"):
        call_of(3).narrowed((2, 0))
    with pytest.raises(RouteError, match="strictly increasing"):
        call_of(3).narrowed((1, 1))
    with pytest.raises(RouteError, match="outside a call of 3 units"):
        call_of(3).narrowed((0, 7))


def test_a_probe_that_answers_for_the_wrong_number_of_units_is_refused() -> None:
    def short(call: Call, layer: CacheLayer) -> CacheDecision:  # noqa: ARG001
        return CacheDecision(verdicts=(CacheVerdict.MISS,))

    handler = with_cache(host_that(), probe=short, layer=CacheLayer.CALL)
    with pytest.raises(RouteError, match="answered for 1 of 3 units"):
        handler(call_of(3))


def test_hit_legacy_short_circuits_like_a_hit() -> None:
    """`hit_legacy` served the request AND is the mixed-vintage warning -- the same split
    `CacheStats.from_verdicts()` makes in the manifest."""
    assert frozenset({CacheVerdict.HIT, CacheVerdict.HIT_LEGACY}) == HIT_VERDICTS
    decision = CacheDecision(verdicts=(CacheVerdict.HIT_LEGACY, CacheVerdict.MISS))
    assert decision.outstanding == (1,)
    assert decision.legacy == 1


# =============================================================================================
# 6. `with_retries` -- Semaphore(1) per (unit_uri, unit_part)
# =============================================================================================


def test_the_guard_serialises_one_part_against_itself() -> None:
    """`08:925`: *"Two attempts in flight on one page can double-bill it and produce two spend rows
    for one decision."*"""
    guard = RetryGuard()
    overlap = []
    inside = threading.Event()
    release = threading.Event()

    def first() -> None:
        with guard.hold([(URI, "p1")]):
            inside.set()
            release.wait(2.0)
            overlap.append("first-out")

    def second() -> None:
        inside.wait(2.0)
        with guard.hold([(URI, "p1")]):
            overlap.append("second-in")

    a, b = threading.Thread(target=first), threading.Thread(target=second)
    a.start()
    b.start()
    inside.wait(2.0)
    release.set()
    a.join(2.0)
    b.join(2.0)
    assert overlap == ["first-out", "second-in"]


def test_two_different_parts_do_not_block_each_other() -> None:
    guard = RetryGuard()
    both = threading.Barrier(2, timeout=2.0)

    def hold(part: str) -> None:
        with guard.hold([(URI, part)]):
            both.wait()

    threads = [threading.Thread(target=hold, args=(p,)) for p in ("p1", "p2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3.0)
        assert not thread.is_alive(), "two different parts serialised against each other"


def test_the_guard_holds_nothing_between_calls() -> None:
    """Reference-counted rather than a growing dict: a run over 331,455 rows would otherwise leave
    one lock object per part claimed."""
    guard = RetryGuard()
    for index in range(500):
        with guard.hold([(URI, f"p{index}")]):
            assert len(guard) == 1
    assert len(guard) == 0


def test_the_guard_takes_keys_in_sorted_order() -> None:
    """Two batches sharing two parts in opposite orders is the textbook cycle, and
    `form_batches()` preserves first-appearance order rather than sorting."""
    guard = RetryGuard()
    done = []

    def run(keys: list[tuple[str, str]]) -> None:
        with guard.hold(keys):
            time.sleep(0.01)
        done.append(keys[0][1])

    forward = threading.Thread(target=run, args=([(URI, "pa"), (URI, "pb")],))
    backward = threading.Thread(target=run, args=([(URI, "pb"), (URI, "pa")],))
    forward.start()
    backward.start()
    forward.join(3.0)
    backward.join(3.0)
    assert not forward.is_alive() and not backward.is_alive(), "the two batches deadlocked"
    assert sorted(done) == ["pa", "pb"]


def test_a_repeated_key_is_taken_once() -> None:
    """A non-reentrant `Lock` taken twice for one key is a deadlock against oneself."""
    guard = RetryGuard()
    with guard.hold([(URI, "p1"), (URI, "p1")]):
        assert len(guard) == 1


def test_the_retry_ceiling_is_the_claim_predicates_own() -> None:
    """`08:105`'s `attempts_total < 5` is how many times a row can be claimed at all, so an in-call
    loop that outlived it would be spending attempts the row does not have."""
    assert DEFAULT_MAX_ATTEMPTS == 5
    attempts: list[int] = []

    def counting(call: Call) -> Reply:
        attempts.append(call.attempt)
        return Reply.of(Outcome.FAILED_TRANSIENT, call.size)

    handler = with_retries(counting, guard=RetryGuard(), should_retry=lambda _reply, _attempt: True)
    handler(call_of(1))
    assert attempts == [1, 2, 3, 4, 5]


def test_zero_attempts_is_refused() -> None:
    with pytest.raises(ConfigError, match="attempted at least once"):
        with_retries(host_that(), guard=RetryGuard(), should_retry=lambda *_: False, max_attempts=0)


# =============================================================================================
# 7. `with_rate_limiting` -- no busy-wait, no sleep under a held lock
# =============================================================================================


def test_the_bucket_computes_the_wait_and_never_sleeps() -> None:
    """`08:841`'s two bans are two different bugs. `take()` returns a delay; the caller sleeps."""
    clock = FakeClock()
    bucket = TokenBucket(4, clock=clock)
    assert bucket.take() == 0
    assert bucket.take() == 250_000_000
    assert bucket.take() == 500_000_000


def test_a_bucket_that_has_been_idle_grants_immediately() -> None:
    clock = FakeClock()
    bucket = TokenBucket(4, clock=clock)
    bucket.take()
    clock.advance_ms(1000)
    assert bucket.take() == 0


def test_rps_zero_is_unlimited_and_the_layer_is_not_even_applied() -> None:
    """`04:615`: *"0 = unlimited"*. `build()` skips the layer, so an unlimited driver pays nothing
    for the branch."""
    clock = FakeClock()
    assert TokenBucket(0, clock=clock).take() == 0
    slept: list[float] = []
    build(host_that(), emit=nothing, bucket=TokenBucket(0, clock=clock), sleep=slept.append)(
        call_of(1)
    )
    assert slept == []


def test_a_negative_rate_is_refused() -> None:
    with pytest.raises(ConfigError, match="rate_limit_rps"):
        TokenBucket(-1, clock=FakeClock())


def test_the_limiter_takes_one_slot_per_call_not_per_unit() -> None:
    """The slot models a request, and a Batch is one `INVOKE` frame -- which is also why a batch of
    256 does not exhaust a 4-rps limiter in a quarter of a second."""
    clock = FakeClock()
    slept: list[float] = []
    handler = with_rate_limiting(
        host_that(), bucket=TokenBucket(4, clock=clock), sleep=slept.append
    )
    handler(call_of(256))
    assert slept == []


def test_a_billed_api_driver_has_no_declared_rate_to_limit_against(plan: PlanDocs) -> None:
    """**D162.** `rate_limit_rps` is declared only under `[acquire]`.

    `with_rate_limiting` is in the chain for every driver, and the drivers it exists to protect --
    the `billed_api` ones behind a hosted provider -- have no number for it to read. The only rate
    control they get is reactive: a 429 becomes `rate_limited`, and `RATE_LIMIT_COOLDOWN_MS` waits
    an hour by default.
    """
    plan.require()
    declared = plan.grep(r"^rate_limit_rps", documents=("04-driver-system.md",))
    assert len(declared) == 1, "a second rate declaration landed; D162 may be resolved"
    block = plan.lines("04-driver-system.md")[declared[0].line - 20 : declared[0].line]
    assert "[acquire]" in "\n".join(block)

    rates = [
        name
        for name in dir(card_module)
        if name.endswith("Sibling")
        and hasattr(getattr(card_module, name), "__dataclass_fields__")
        and "rate_limit_rps" in getattr(card_module, name).__dataclass_fields__
    ]
    assert rates == ["AcquireSibling"], rates


# =============================================================================================
# 8. `with_metrics` -- measures the PROVIDER, not the queue
# =============================================================================================


def test_the_queue_wait_is_not_counted_as_provider_latency() -> None:
    """`08:842`. The timer starts BELOW the limiter, so a driver that waited four seconds for a slot
    and answered in 200 ms records 200 ms.

    The fake clock advances inside the host and inside the sleep, so the two are distinguishable:
    if `with_metrics` sat one line up, the recorded number would be 4,200.
    """
    clock = FakeClock()
    measured: list[int] = []

    def host(call: Call) -> Reply:
        clock.advance_ms(200)
        return ok_reply(call)

    def slow_sleep(seconds: float) -> None:
        clock.advance_ms(int(seconds * 1000))

    handler = build(
        host,
        emit=nothing,
        bucket=TokenBucket(1, clock=clock),
        clock=clock,
        record=lambda _c, _r, ms: measured.append(ms),
        sleep=slow_sleep,
    )
    handler(call_of(1))
    handler(call_of(1))  # the second call waits a full second for its slot
    assert measured == [200, 200]


def test_provider_ms_reaches_the_reply() -> None:
    clock = FakeClock()

    def host(call: Call) -> Reply:
        clock.advance_ms(37)
        return ok_reply(call)

    reply = with_metrics(host, clock=clock, record=lambda *_: None)(call_of(1))
    assert reply.provider_ms == 37


def test_a_raising_host_is_still_measured() -> None:
    clock = FakeClock()
    measured: list[int] = []

    def host(call: Call) -> Reply:  # noqa: ARG001
        clock.advance_ms(5)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        with_metrics(host, clock=clock, record=lambda _c, _r, ms: measured.append(ms))(call_of(1))
    assert measured == [5]


# =============================================================================================
# 9. `with_fault_injection`
# =============================================================================================


def test_chaos_is_derived_and_not_sampled() -> None:
    """`random` is semgrep-banned in library code, and the ban is doing real work: a chaos run whose
    failures cannot be reproduced cannot be the counterfactual `13-quality.md`'s Injectors need."""
    source = pathlib.Path(pipeline_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert {"random", "secrets", "uuid"} & imported == set()
    assert "time.time" not in source

    first = chaos_fires(unit("p7"), rate=0.5, salt="s")
    for _ in range(20):
        assert chaos_fires(unit("p7"), rate=0.5, salt="s") is first


def test_chaos_rate_bounds_are_the_two_certainties() -> None:
    assert chaos_fires(unit("p1"), rate=0.0, salt="s") is False
    assert chaos_fires(unit("p1"), rate=1.0, salt="s") is True


def test_chaos_at_a_half_fires_for_roughly_half_the_parts() -> None:
    """Derived, not random -- but still a hash, so the distribution is the thing under test."""
    fired = sum(chaos_fires(unit(f"p{i}"), rate=0.5, salt="s") for i in range(1000))
    assert 420 <= fired <= 580, fired


def test_an_injected_failure_is_an_outcome_and_not_an_exception() -> None:
    """graphrag raises because its chain is exception-driven; ours is `Outcome`-driven all the way
    down, and `host/subproc.py` turns a dead worker into a `HostVerdict`, never into a Python
    exception crossing S4."""
    seen: list[Call] = []
    reply = with_fault_injection(
        host_that(seen=seen), chaos=Chaos(failure_rate=1.0), sleep=lambda _s: None
    )(call_of(2))
    assert reply.outcomes == (Outcome.FAILED_TRANSIENT,) * 2
    assert reply.stopped_at == "with_fault_injection"
    assert seen == []


def test_injected_latency_is_slept_before_the_call() -> None:
    slept: list[float] = []
    with_fault_injection(host_that(), chaos=Chaos(latency_ms=500), sleep=slept.append)(call_of(1))
    assert slept == [0.5]


def test_oom_at_unit_names_the_knob_that_clears_it() -> None:
    """A `ResourceLimit` is *"the ONE error required to name a knob"* (`02` section 7.2), and an
    injected fault names the same knob a real one would."""
    with pytest.raises(ResourceLimit) as failure:
        with_fault_injection(host_that(), chaos=Chaos(oom_at_unit=URI), sleep=lambda _s: None)(
            call_of(1)
        )
    assert failure.value.limit == "_chaos.oom_at_unit"


def test_chaos_is_off_by_default_and_the_layer_is_not_applied() -> None:
    """`08:843`: *"SHIPPED in production builds, OFF by default."*"""
    assert Chaos().active is False
    seen: list[Call] = []
    build(host_that(seen=seen), emit=nothing, chaos=Chaos())(call_of(1))
    assert len(seen) == 1


def test_an_injected_exception_type_is_a_failure_class() -> None:
    """A chaos run that injected an exception outside the thirteen-member vocabulary would exercise
    a path the failure ladder has no row for."""
    assert Chaos().exception_type in set(FailureClass)
    with pytest.raises(ConfigError, match="not a FailureClass"):
        Chaos(exception_type="KaboomError")  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="it is a probability"):
        Chaos(failure_rate=1.5)


# =============================================================================================
# 10. `with_events` -- ALWAYS ON
# =============================================================================================


def test_the_pair_opens_and_closes_and_joins_on_invoke_id() -> None:
    """D150 appended `call.begin` and `call.end` so the three span levels the vocabulary could not
    emit could be emitted. `invoke_id` is on both, which is what makes the pair join."""
    emitted: list[dict[str, Any]] = []
    with_events(host_that(), emit=lambda **fields: emitted.append(fields))(call_of(2))
    assert [entry["kind"] for entry in emitted] == [EventKind.CALL_BEGIN, EventKind.CALL_END]
    assert emitted[0]["fields"]["invoke_id"] == emitted[1]["fields"]["invoke_id"] == "iv_1"
    assert emitted[1]["fields"]["micros"] == 14


def test_a_raising_chain_still_closes_its_span() -> None:
    """A span that opens and never closes is I33's orphan, and `RunRecorder` buffers the subtree
    until it closes."""
    emitted: list[dict[str, Any]] = []

    def host(call: Call) -> Reply:  # noqa: ARG001
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        with_events(host, emit=lambda **fields: emitted.append(fields))(call_of(1))
    assert [entry["kind"] for entry in emitted] == [EventKind.CALL_BEGIN, EventKind.CALL_END]


def test_events_is_always_on_and_takes_no_none() -> None:
    """Turning the stream off is `[observe] sinks`' job. A layer that could be composed out would
    make *"every driver call has a span"* a configuration rather than a fact."""
    emitted: list[dict[str, Any]] = []
    build(host_that(), emit=lambda **fields: emitted.append(fields))(call_of(1))
    assert len(emitted) == 2


# =============================================================================================
# 11. `build()` -- a plain sequence of `if`s
# =============================================================================================


def test_the_bare_chain_is_events_over_the_host() -> None:
    """Every dependency `None` leaves one layer, because one layer is never optional."""
    seen: list[Call] = []
    reply = build(host_that(seen=seen), emit=nothing)(call_of(2))
    assert reply.stopped_at == ""
    assert len(seen) == 1


def test_a_prober_without_a_layer_is_refused() -> None:
    """`08:854` fixes the layer by the operator, so a prober with no layer has nothing to probe."""
    with pytest.raises(ConfigError, match="needs a prober and a layer together"):
        build(host_that(), emit=nothing, probe=all_misses)
    with pytest.raises(ConfigError, match="needs a prober and a layer together"):
        build(host_that(), emit=nothing, cache_layer=CacheLayer.CALL)


def test_request_count_counts_a_raise_as_a_failure_and_re_raises() -> None:
    counter = RequestCount()

    def host(call: Call) -> Reply:  # noqa: ARG001
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        with_request_count(host, counter=counter)(call_of(1))
    assert (counter.attempted, counter.succeeded, counter.failed) == (1, 0, 1)
    assert counter.as_manifest_fields() == {
        "attempted_request_count": 1,
        "successful_response_count": 0,
        "failed_response_count": 1,
    }


# =============================================================================================
# 12. The two records the chain carries
# =============================================================================================


def test_a_call_is_one_to_one_with_its_batch() -> None:
    """`RESULT{unit_index}` is an index INTO THE BATCH, so the pairing is load-bearing --
    `dispatch.invocation_units()` refuses the same thing from the other side."""
    with pytest.raises(RouteError, match="one-to-one and in order"):
        Call(
            batch=Batch(invoke_id="iv_1", rows=(row(1),)),
            units=(unit(), unit("p2")),
            operator="parse.pdf",
        )


def test_a_reply_answers_for_every_unit_it_carried() -> None:
    """I24 in the middleware's terms: every layer preserves the call's width or is a bug."""
    with pytest.raises(RouteError, match="empty or full width"):
        Reply(outcomes=(Outcome.OK, Outcome.OK), micros=(1,))
    with pytest.raises(RouteError, match="answers for every unit"):
        Reply(outcomes=())


def test_stopped_at_names_a_real_layer() -> None:
    with pytest.raises(RouteError, match="not one of the eight layers"):
        Reply(outcomes=(Outcome.OK,), stopped_at="with_magic")
    assert Reply(outcomes=(Outcome.OK,), stopped_at="").stopped_at == ""


def test_deferred_dim_and_deferred_budget_travel_together() -> None:
    with pytest.raises(RouteError, match="travel together"):
        Reply(outcomes=(Outcome.DEFERRED_BUDGET,))
    with pytest.raises(RouteError, match="travel together"):
        Reply(outcomes=(Outcome.OK,), deferred_dim="micros")


def test_an_admission_names_its_dimension_only_when_it_defers() -> None:
    """`route_decision.admission`'s three values, and `degraded` is not a denial: `05:2527`'s ladder
    admits a cheaper rung rather than refusing, and the work still runs."""
    assert BudgetVerdict(admission="degraded").deferred_dim is None
    with pytest.raises(RouteError, match="a deferral names the dimension"):
        BudgetVerdict(admission="admitted", deferred_dim="micros")
    with pytest.raises(RouteError, match="a deferral names the dimension"):
        BudgetVerdict(admission="deferred")
    with pytest.raises(RouteError, match="not an admission"):
        BudgetVerdict(admission="maybe")  # type: ignore[arg-type]


def test_a_degraded_admission_carries_its_record_through_to_the_reply() -> None:
    """`15:1059`: *"Every `Degradation` is visible on every surface it reaches."*"""

    class Degrading(GrantingAdmitter):
        def admit(self, call: Call) -> BudgetVerdict:  # noqa: ARG002
            self.admits += 1
            return BudgetVerdict(
                admission="degraded",
                degradations=(Degradation(kind="budget", message="a cheaper rung"),),
            )

    reply = with_budget(host_that(), admitter=Degrading())(call_of(1))
    assert [record.kind for record in reply.degradations] == ["budget"]
    assert reply.outcomes == (Outcome.OK,)


# =============================================================================================
# 9a. The probe adapter: `CacheProbe` -> `CacheDecision`
# =============================================================================================


def probe_of(*, hits: tuple[int, ...], width: int, micros: int = 5) -> CacheProbe:
    """A `CacheProbe` over `call_of(width)`'s own units, of which `hits` are answered.

    Built from the module's own `unit()` rather than from a second unit factory, so the mapping
    `decision_of` re-projects is keyed by the pairs the `Call` actually carries -- which is the
    one thing the projection can get wrong.
    """
    units = [unit(f"p{n + 1}") for n in range(width)]
    made = tuple(
        CacheHit(
            index=n,
            key=f"{n:064d}",
            unit=units[n],
            verdict=CacheVerdict.HIT,
            ref="cas://ab/cd/" + "ab" * 32,
            bytes=1,
            spend_json='{"wall_ms":3}',
            micros=micros,
        )
        for n in hits
    )
    return CacheProbe(
        hits=made,
        outstanding=tuple(units[n] for n in range(width) if n not in hits),
        verdicts={
            (u.uri, u.part): (CacheVerdict.HIT if n in hits else CacheVerdict.MISS)
            for n, u in enumerate(units)
        },
        legacy=0,
        would_have_been_micros=micros * len(hits),
        queries=1,
    )


def test_the_projection_keeps_every_tuple_parallel_to_the_calls_units() -> None:
    """`CacheDecision`'s own invariant, fed from a probe whose verdicts are a mapping."""
    decision = decision_of(probe_of(hits=(1,), width=3), call_of(3))
    assert decision.verdicts == (CacheVerdict.MISS, CacheVerdict.HIT, CacheVerdict.MISS)
    assert decision.micros == (0, 5, 0)
    assert decision.outstanding == (0, 2)
    assert decision.would_have_been_micros == 5


def test_a_caller_that_wants_only_the_short_circuit_passes_neither_payload_nor_replay() -> None:
    """08:1795's *"outstanding is what gets dispatched"* needs verdicts and micros, no more."""
    decision = decision_of(probe_of(hits=(0,), width=2), call_of(2))
    assert decision.produced == ()
    assert decision.spend == ()
    assert decision.verdicts[0] is CacheVerdict.HIT


def test_payloads_and_replayed_spend_land_at_the_hits_own_position() -> None:
    ref = ArtifactRef(kind="doc_fragment", byte_len=1, inline=b"x", blob=None)
    decision = decision_of(
        probe_of(hits=(2,), width=3),
        call_of(3),
        produced={2: (ref,)},
        replay=lambda _json: Spend(wall_ms=3),
    )
    assert decision.produced == ((), (), (ref,))
    assert decision.spend[2].wall_ms == 3
    assert decision.spend[0].wall_ms == 0


def test_the_adapter_asks_the_probe_for_the_calls_units_and_the_layer() -> None:
    seen: list[tuple[int, CacheLayer]] = []

    def fake(units: Sequence[UnitRef], keys: Sequence[str], *, layer: CacheLayer) -> CacheProbe:
        assert len(keys) == len(units)
        seen.append((len(units), layer))
        return probe_of(hits=(), width=len(units))

    run = prober(fake, keys=lambda call: [f"{n:064d}" for n in range(call.size)])
    decision = run(call_of(4), CacheLayer.CALL)
    assert seen == [(4, CacheLayer.CALL)]
    assert decision.outstanding == (0, 1, 2, 3)


def test_a_full_hit_projects_to_a_decision_with_nothing_outstanding() -> None:
    """The 100%-hit Batch of I25: every verdict is a hit, so `with_cache` never calls inward."""
    decision = decision_of(probe_of(hits=(0, 1, 2), width=3), call_of(3))
    assert decision.outstanding == ()
    assert decision.legacy == 0


# =============================================================================================
# 9b. The admission adapter: `Admitted | Deferred | Degraded` -> `BudgetVerdict`
# =============================================================================================


class _Ledger:
    """A `BudgetLedger` that answers from a script and records every call."""

    def __init__(self, denies: str | None = None) -> None:
        self.denies = denies
        self.reserved: list[tuple[str, ...]] = []
        self.committed: list[tuple[str, int]] = []
        self.released: list[str] = []

    def headroom(self, dim: str, scope: str, scope_key: str, limit: int) -> int:
        del dim, scope, scope_key
        return limit

    def reserve(self, reservations: Sequence[Reservation], limits: Mapping[str, int]) -> str | None:
        del limits
        self.reserved.append(tuple(row.dim for row in reservations))
        return self.denies

    def commit(self, reservation_id: str, amount: int, /) -> bool:
        self.committed.append((reservation_id, amount))
        return True

    def release(self, reservation_id: str, /) -> bool:
        self.released.append(reservation_id)
        return True


def _reservation(dim: str = "micros", amount: int = 10) -> Reservation:
    return Reservation(
        reservation_id=f"res_{dim}",
        run_id="r_1",
        work_id=1,
        decision_id="d_1",
        dim=dim,
        amount=amount,
        scope="part",
        scope_key=f"{URI}#p1",
        claimed_gen=1,
        expires_ms=9_999,
    )


def test_the_three_admissions_agree_with_cores_mapping() -> None:
    """Two homes for one pairing, asserted rather than trusted -- `verdict_of`'s own docstring."""
    assert verdict_of(Admitted(("res_a",))).admission == admission_of(Admitted(()))
    assert verdict_of(Deferred("micros")).admission == admission_of(Deferred("micros"))
    degraded = Degraded((Degradation(kind="budget", message="clamped"),))
    assert verdict_of(degraded).admission == admission_of(degraded)


def test_a_deferral_carries_the_dimension_and_an_admission_carries_the_ids() -> None:
    deferred = verdict_of(Deferred("calls"))
    assert (deferred.admission, deferred.deferred_dim) == ("deferred", "calls")
    admitted = verdict_of(Admitted(("res_a", "res_b")))
    assert admitted.reservations == ("res_a", "res_b")
    assert admitted.deferred_dim is None


def test_a_degraded_verdict_carries_its_degradations_and_defers_nothing() -> None:
    """`05:2519`'s steps 1-3: the work still runs, so nothing short-circuits."""
    record = Degradation(kind="budget", message="max_cost_class")
    verdict = verdict_of(Degraded((record,)))
    assert verdict.admission == "degraded"
    assert verdict.degradations == (record,)
    assert verdict.deferred_dim is None


def test_the_admitter_reserves_what_the_caller_computed() -> None:
    ledger = _Ledger()
    admitter = LedgerAdmitter(
        ledger,
        reservations_for=lambda _call: (_reservation("micros"), _reservation("calls", 1)),
        limits={"micros": 6_000, "calls": 3},
    )
    verdict = admitter.admit(call_of(2))
    assert verdict.admission == "admitted"
    assert ledger.reserved == [("micros", "calls")]
    assert verdict.reservations == ("res_micros", "res_calls")


def test_a_denial_names_the_dimension_and_holds_nothing() -> None:
    ledger = _Ledger(denies="calls")
    admitter = LedgerAdmitter(
        ledger, reservations_for=lambda _call: (_reservation("calls", 1),), limits={"calls": 3}
    )
    verdict = admitter.admit(call_of(1))
    assert (verdict.admission, verdict.deferred_dim) == ("deferred", "calls")
    assert verdict.reservations == ()


def test_a_free_call_never_reaches_the_ledger() -> None:
    """02:478's hop 8: a `free` decision reserves nothing, and reserving nothing takes no lock."""
    ledger = _Ledger()
    admitter = LedgerAdmitter(ledger, reservations_for=lambda _call: (), limits={})
    assert admitter.admit(call_of(1)).admission == "admitted"
    assert ledger.reserved == []


def test_the_commit_prices_the_attempts_actual_spend() -> None:
    """INV-15: the price arrives as a callable, because `PriceBook` is `route.spend`'s."""
    ledger = _Ledger()
    admitter = LedgerAdmitter(
        ledger,
        reservations_for=lambda _call: (_reservation("micros"),),
        limits={"micros": 6_000},
        price=lambda spend: spend.calls * 100,
    )
    call = call_of(2)
    verdict = admitter.admit(call)
    admitter.commit(call, verdict, (Spend(calls=1), Spend(calls=2)))
    assert ledger.committed == [("res_micros", 300)]


def test_without_a_pricebook_the_commit_is_zero_and_the_ceiling_is_released() -> None:
    """ "Nothing was priced" is the honest reading; committing the p95 ceiling would be a bill."""
    ledger = _Ledger()
    admitter = LedgerAdmitter(
        ledger, reservations_for=lambda _call: (_reservation("micros"),), limits={"micros": 6_000}
    )
    call = call_of(1)
    verdict = admitter.admit(call)
    admitter.commit(call, verdict, (Spend(calls=9),))
    assert ledger.committed == [("res_micros", 0)]


def test_release_returns_every_held_row_in_full() -> None:
    ledger = _Ledger()
    admitter = LedgerAdmitter(
        ledger,
        reservations_for=lambda _call: (_reservation("micros"), _reservation("calls", 1)),
        limits={"micros": 6_000, "calls": 3},
    )
    call = call_of(1)
    admitter.release(call, admitter.admit(call))
    assert ledger.released == ["res_micros", "res_calls"]


def test_the_admitter_satisfies_the_protocol_the_layer_takes() -> None:
    """Structurally, and by use: `with_budget` is what actually consumes it."""
    ledger = _Ledger()
    admitter: Admitter = LedgerAdmitter(
        ledger, reservations_for=lambda _call: (_reservation(),), limits={"micros": 6_000}
    )
    handler = with_budget(ok_reply, admitter=admitter)
    reply = handler(call_of(2))
    assert reply.outcomes == (Outcome.OK, Outcome.OK)
    assert ledger.reserved == [("micros",)]
    assert ledger.committed == [("res_micros", 0)]


def test_a_deferred_call_short_circuits_without_reaching_the_driver() -> None:
    """I8's other half: nothing below `with_budget` runs without a reservation."""
    ledger = _Ledger(denies="micros")
    admitter = LedgerAdmitter(
        ledger, reservations_for=lambda _call: (_reservation(),), limits={"micros": 6_000}
    )

    def refuses(_call: Call) -> Reply:
        raise AssertionError("a deferred call must not reach the driver")

    reply = with_budget(refuses, admitter=admitter)(call_of(2))
    assert reply.outcomes == (Outcome.DEFERRED_BUDGET, Outcome.DEFERRED_BUDGET)
    assert ledger.committed == []
