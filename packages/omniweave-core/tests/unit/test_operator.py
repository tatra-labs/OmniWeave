"""`omniweave_core.operator` against 08-runtime.md sections 1.3 and 6.1, and against `work.py`.

Three kinds of test, and the order is the argument:

1. **Transcription.** 08:177-179 calls its own block *"the sole home"* of `Outcome`, `StepMetrics`
   and `StepResult`, so every field name and every member value is read back out of `_plan/` with
   `ast` rather than compared to a second copy of itself. A transcription test that quoted the
   plan would pass on the day someone edited both.
2. **Agreement.** `omniweave_core.work` was built one cell earlier against a *string* domain, under
   a docstring promising that *"P4's real `Outcome` satisfies every check in this module the day
   `operator.py` lands"*. Four tests here are that promise, executed.
3. **Behaviour.** `__post_init__`, the cancellation latch and the ULID are the three things in this
   module that do something, and each has the failure it was written against.

The two deliberate divergences from the printed block -- `failure_message` (D138) and `spend`'s
default (D139) -- are asserted **as divergences**: a test names the field, says the plan does not
print it, and fails if the plan ever does. That is what keeps a defect from decaying into a habit.
"""

from __future__ import annotations

import ast
import inspect
import keyword
import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Protocol

import pytest
from omniweave_core import operator as op
from omniweave_core.model.records import Producer
from omniweave_core.operator import (
    CACHE_KEY_HEX_LEN,
    CROCKFORD32,
    RUN_ID_PREFIX,
    ULID_CHARS,
    ULID_ENTROPY_BYTES,
    AdmissionView,
    Cancellation,
    CancelReason,
    CancelToken,
    Operator,
    OperatorIdentity,
    Outcome,
    Roots,
    RunContext,
    ServiceRegistryView,
    SpendVector,
    StepMetrics,
    StepResult,
    new_run_id,
    ulid,
)
from omniweave_core.store import StepResult as StoreStepResult
from omniweave_core.store import graph as store_graph
from omniweave_core.store import queue as store_queue
from omniweave_core.store.queue import StepMetricsView, StepResultView
from omniweave_core.work import OUTCOMES, TRANSITIONS
from omniweave_ports.types import UnitRef

RUNTIME = "08-runtime.md"

CACHE_KEY = "a" * CACHE_KEY_HEX_LEN
UNIT = UnitRef(uri="file:///corpus/a.pdf", part="p0", content_sha256="a0", byte_len=11)
IDENTITY = OperatorIdentity(operator="parse.pdf", op_version=1, code_fingerprint="test")

OPERATOR_SOURCE = Path(inspect.getfile(op))

RUNTIME_DDL = (
    OPERATOR_SOURCE.parent / "store" / "schema" / "migrations" / "0004_runtime.sql"
).read_text(encoding="utf-8")
"""The shipped runtime migration, which is where the `run` and `work` columns really are.

The plan cites `charter.md:4040` for the column and `_plan/_notes/charter.md` holds it, but the DDL
that matters is the one in this repository: it is what the store actually creates, `G27b` applies it
to an empty file on every run, and a defect about a column is a claim about the schema rather than
about a quotation of it."""

# The seven types this module names in an annotation and cannot import, each with the cell that
# owes it. This is `test_store_protocols.py`'s `EXPECTED_UNRESOLVED` device at a second boundary:
# the set is pinned, so a typo arrives as a new member and a type that lands arrives as a stale
# one. Unlike that file's, the suppression here is per-line, so `RUF100` is a second enforcer:
# ruff fails the build the day one of these resolves and the suppression stops being needed.
# (Spelled without the directive's own punctuation, because ruff reads a comment that carries
# it as a directive on THIS line and warns that the prose is not a rule code.)
EXPECTED_UNRESOLVED: frozenset[str] = frozenset(
    {
        "Limits",  # 08:275. `omniweave_core.limits` holds the constants, not this record.
        "BudgetLedger",  # 02 row 19 -> `omniweave_core.budget`. W4.5.
        "TraceSink",  # 02 row 21 -> `omniweave_core.events`; printed at 15-observability.md:362.
        "CacheLayer",  # 02 row 18 -> `omniweave_core.cache`. W4.4.
        "Degradation",  # 15-observability.md's, by charter erratum E15. P7.
        "WorkSpec",  # 08:2842. What `Operator.plan()` emits; no module row names it.
    }
)

# `ServiceRegistry` is the seventh name the module docstring's table lists and it is NOT here,
# because `RunContext.service()` calls it rather than naming it: it is reached through
# `ServiceRegistryView`, a declared Protocol, so there is no undefined name to suppress. The
# docstring says so and `test_the_docstring_table_names_every_owed_type` checks that it does.


def _fence_class(plan, document: str, name: str) -> ast.ClassDef:
    """The plan's own `class <name>` node, parsed out of a ```python fence in `document`.

    Every fence is parsed rather than the first one matching a regex, for the reason
    `test_store_protocols.py` gives: a fence boundary is a claim, and 08 prints more than one
    class per fence.
    """
    plan.require()
    found: ast.ClassDef | None = None
    for body in plan.fences(document, "python"):
        if f"class {name}(" not in body and f"class {name}:" not in body:
            continue
        for node in ast.parse(body).body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                assert found is None, f"_plan/{document} prints class {name} more than once"
                found = node
    assert found is not None, f"_plan/{document} prints no class {name}"
    return found


def _printed_fields(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(
        child.target.id
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    )


def _printed_members(node: ast.ClassDef) -> tuple[tuple[str, str], ...]:
    """`(NAME, value)` for every `NAME = "value"` in an enum the plan prints."""
    out: list[tuple[str, str]] = []
    for child in node.body:
        if isinstance(child, ast.Assign) and isinstance(child.value, ast.Constant):
            target = child.targets[0]
            if isinstance(target, ast.Name) and isinstance(child.value.value, str):
                out.append((target.id, child.value.value))
    return tuple(out)


def _declared_fields(cls: type) -> tuple[str, ...]:
    return tuple(f.name for f in fields(cls))


class FakeClock:
    """Two readings and a counter, which is all `Clock` is. The counter is a test of its own."""

    def __init__(self, mono: int = 0, wall: int = 1_757_400_000_000_000_000) -> None:
        self.mono = mono
        self.wall = wall
        self.reads = 0

    def monotonic_ns(self) -> int:
        self.reads += 1
        return self.mono

    def wall_ns(self) -> int:
        return self.wall


def result(outcome: Outcome = Outcome.OK, **kwargs: object) -> StepResult:
    """A `StepResult` carrying whatever its outcome demands, and nothing more."""
    required: dict[str, object] = {"cache_key": CACHE_KEY, "unit": UNIT, "identity": IDENTITY}
    required.update(kwargs)
    return StepResult(outcome=outcome, **required)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 1. Transcription -- every name read back out of the plan
# ---------------------------------------------------------------------------------------------


def test_the_eight_outcomes_are_the_plans_own_members_in_the_plans_own_order(plan) -> None:
    """08:189-198. Names, values AND order, because 08:179-183 makes the count load-bearing.

    *"Adding or removing a member is one edit to this enum **and** to section 1.2's transition
    table in the same change -- that table is the specification, and a member with no row in it is
    a rejectable PR."* This is the first half of that sentence; the `work.TRANSITIONS` tests below
    are the second.
    """
    printed = _printed_members(_fence_class(plan, RUNTIME, "Outcome"))
    assert printed == tuple((member.name, member.value) for member in Outcome)


def test_step_metrics_is_the_plans_field_list_and_the_one_divergence_is_named(plan) -> None:
    """08:200-207, verbatim -- the field names and their order are the plan's. D139 is the value.

    The divergence is in the **default**, not in the shape: `spend` is still the third field and
    still called `spend`. 08:202 gives it `Spend()`, a construction of a type
    `tools/layers.toml` forbids core from importing, and this asserts that the plan really does
    print that call, so the day the plan moves `Spend` into core this test fails and the `None`
    goes away with it.
    """
    printed = _fence_class(plan, RUNTIME, "StepMetrics")
    assert _printed_fields(printed) == _declared_fields(StepMetrics)

    spend = next(
        child
        for child in printed.body
        if isinstance(child, ast.AnnAssign)
        and isinstance(child.target, ast.Name)
        and child.target.id == "spend"
    )
    assert isinstance(spend.value, ast.Call), "08:202 prints `spend: 'Spend' = Spend()`"
    assert ast.unparse(spend.value) == "Spend()"
    assert StepMetrics().spend is None


def test_step_result_is_the_plans_field_list_plus_exactly_one_named_extension(plan) -> None:
    """08:209-220 plus `failure_message`, which is D138 and is the only addition.

    The assertion is two-sided on purpose. The plan's fields must all be here in the plan's order,
    and the difference must be exactly `{"failure_message"}` -- so neither a dropped field nor a
    second undocumented extension can pass, and the day 08 prints `failure_message` itself this
    test fails and the defect is closed by deleting a line.
    """
    printed = _printed_fields(_fence_class(plan, RUNTIME, "StepResult"))
    declared = _declared_fields(StepResult)

    assert set(printed) - set(declared) == set()
    assert set(declared) - set(printed) == {"failure_message"}
    assert tuple(name for name in declared if name != "failure_message") == printed


def test_the_failure_message_extension_is_the_column_the_plans_own_update_binds(plan) -> None:
    """D138's evidence, read out of the plan rather than asserted about it.

    08's `work` UPDATE binds `:failure_message` and the DDL declares the column; the type the
    plan prints has no field for it. Three facts, three sources, and the defect is the gap.
    """
    plan.require()
    assert plan.grep(r":failure_message", documents=[RUNTIME]), "08's UPDATE binds it"
    assert "failure_message" in RUNTIME_DDL, "the shipped 0004 migration declares the column"
    printed = _printed_fields(_fence_class(plan, RUNTIME, "StepResult"))
    assert "failure_message" not in printed
    assert "failure_message" in _declared_fields(StepResult)


@pytest.mark.parametrize("name", ["Roots", "RunContext", "Cancellation"])
def test_the_three_frozen_value_types_are_the_plans_field_lists(plan, name: str) -> None:
    """08:257-283 and :338-345. Names and order, for the three dataclasses beside `StepResult`."""
    printed = _printed_fields(_fence_class(plan, RUNTIME, name))
    assert printed == _declared_fields(getattr(op, name))


def test_run_context_carries_five_digests_and_the_glossary_says_six(plan) -> None:
    """D140. The count is not a typo on one side; the two sites hold different fives.

    `RunContext` has `catalog_digest` and no `lock_digest`; the `run` table has `lock_digest` and
    no `catalog_digest`. The union is six, which is where 08:2834's number comes from, and the
    consequence is that `catalog_digest` -- *"FROZEN at startup step 7; a mid-run install is
    invisible"* -- reaches no durable row at all.
    """
    plan.require()
    digests = tuple(name for name in _declared_fields(RunContext) if name.endswith("_digest"))
    assert len(digests) == 5
    assert "catalog_digest" in digests
    assert "lock_digest" not in digests
    assert plan.grep(r"identity, six digests", documents=[RUNTIME]), "08:2834 says six"

    run_table = RUNTIME_DDL[RUNTIME_DDL.index("CREATE TABLE run (") :]
    run_table = run_table[: run_table.index(") STRICT;")]
    stored = tuple(sorted(part for part in re.findall(r"(\w+_digest)", run_table)))
    assert stored == (
        "config_digest",
        "lock_digest",
        "policy_digest",
        "pricebook_digest",
        "semantic_digest",
    )
    assert set(stored) | set(digests) == set(stored) | {"catalog_digest"}
    assert len(set(stored) | set(digests)) == 6


def test_the_four_cancel_reasons_are_the_plans_own(plan) -> None:
    """08:332-336. Four, because four things stop work and they leave four different traces."""
    printed = _printed_members(_fence_class(plan, RUNTIME, "CancelReason"))
    assert printed == tuple((member.name, member.value) for member in CancelReason)


def test_supersession_is_not_a_cancel_reason(plan) -> None:
    """08's consequence (a), as an assertion rather than a comment.

    *"Adding a `SUPERSEDED` member would reintroduce the conflation the whole section is built to
    prevent, and would imply the doomed worker could be told."* `Outcome.CANCELLED` has two
    producers and only one of them is a token.
    """
    plan.require()
    assert "SUPERSEDED" not in {member.name for member in CancelReason}
    assert plan.grep(r"Supersession is not a `CancelReason`", documents=[RUNTIME])


def test_the_cancel_token_slots_and_methods_are_the_plans_own(plan) -> None:
    """08:355-360. Five slots and four methods, and the names are the plan's.

    `__slots__` is sorted here and 08 prints it in a different order, which is `RUF023` and not a
    decision; the SET is what the plan fixes, so the set is what this compares.
    """
    printed = _fence_class(plan, RUNTIME, "CancelToken")
    slots = next(
        child
        for child in printed.body
        if isinstance(child, ast.Assign)
        and isinstance(child.targets[0], ast.Name)
        and child.targets[0].id == "__slots__"
    )
    assert isinstance(slots.value, ast.Tuple)
    printed_slots = {
        element.value for element in slots.value.elts if isinstance(element, ast.Constant)
    }
    assert printed_slots == set(CancelToken.__slots__)

    printed_methods = tuple(
        child.name for child in printed.body if isinstance(child, ast.FunctionDef)
    )
    assert printed_methods == ("cancelled", "cause", "cancel", "remaining_ms")
    for name in printed_methods:
        assert callable(getattr(CancelToken, name))


def test_the_operator_protocol_is_the_plans_five_classvars_and_three_methods(plan) -> None:
    """08:1917-1927. The contract nobody outside core implements, transcribed whole."""
    printed = _fence_class(plan, RUNTIME, "Operator")
    assert _printed_fields(printed) == tuple(Operator.__annotations__)
    printed_methods = tuple(
        child.name for child in printed.body if isinstance(child, ast.FunctionDef)
    )
    assert printed_methods == ("plan", "run", "is_valid_nonempty")
    for name in printed_methods:
        assert callable(getattr(Operator, name))


# ---------------------------------------------------------------------------------------------
# 2. Agreement -- the promise `work.py` made one cell earlier
# ---------------------------------------------------------------------------------------------


def test_the_enum_and_the_queues_string_domain_are_the_same_eight_in_the_same_order() -> None:
    """`work.OUTCOMES` was minted as a tuple so that this module could mint the enum (08:177).

    Order and all: `OUTCOMES`'s docstring claims *"08:190-198's printed order"* and so does this
    enum, so if either drifts the tuple comparison catches it before the set comparison would.
    """
    assert tuple(member.value for member in Outcome) == OUTCOMES


def test_every_outcome_has_a_row_in_the_transition_table_and_every_row_has_an_outcome() -> None:
    """08:179-183's *"a member with no row in it is a rejectable PR"*, in both directions."""
    assert set(TRANSITIONS) == {member.value for member in Outcome}
    assert all(TRANSITIONS[member].outcome == member.value for member in Outcome)


def test_a_str_enum_member_keys_the_transition_table_written_against_strings() -> None:
    """`OUTCOMES`'s claim: *"a `StrEnum` member compares and binds equal to its value"*.

    Not obvious and worth a test rather than a comment: `Enum` defines its own `__hash__`, so a
    member that compared equal to `'ok'` but hashed differently would miss every dict keyed by the
    wire value -- silently, as a `KeyError` in the scheduler and nowhere near this module.
    """
    for member in Outcome:
        assert hash(member) == hash(member.value)
        assert TRANSITIONS[member] is TRANSITIONS[member.value]
        assert member in OUTCOMES


def test_the_store_boundary_now_names_a_type_that_resolves() -> None:
    """`Store.complete(row_id, gen, result: StepResult)` -- one object, imported, not quoted.

    `test_store_protocols.py` pinned `StepResult` as an unresolved forward reference for two
    phases. This is what closing that row looks like from the other side.
    """
    assert StoreStepResult is StepResult


@pytest.mark.parametrize(
    ("view", "real"), [(StepMetricsView, StepMetrics), (StepResultView, StepResult)]
)
def test_the_real_type_satisfies_the_stores_narrow_read_surface(view: type, real: type) -> None:
    """The P2 carriers were deleted; these Protocols are what made that a deletion.

    *"A Protocol listing only what is read is what lets P4's real `StepMetrics` satisfy this with
    no edit on either side."* Structural, so the check is the attribute set rather than an
    `isinstance`: neither View is `runtime_checkable`, deliberately, because nothing should be
    branching on it at runtime.

    Their members are **properties**, not annotations, which is what makes them read-only and
    therefore covariant -- a mutable `outcome: str` would be invariant and `StepResult.outcome`,
    an `Outcome`, would not satisfy it. So the member set is read off `vars()` rather than off
    `__annotations__`, which for these two is empty; the emptiness assertion above is what stops
    this test from passing vacuously the day someone gets that wrong.
    """
    members = {
        name
        for name, value in vars(view).items()
        if isinstance(value, property) or not name.startswith("_")
    } - set(vars(Protocol))
    assert members, "a View whose members are properties must still HAVE members"
    assert members <= set(_declared_fields(real))


def test_operator_identity_is_producer_and_not_a_subclass_of_it() -> None:
    """08:1930 -- *"`Producer` **is** `OperatorIdentity`. ONE TYPE, TWO LAYERS, ONE TABLE"*.

    `is`, not `issubclass`: two classes would be two `__eq__`s and two `producer_id` round-trips,
    which is the hazard 08:1936-1940 records against the `str()`/`int()` conversion pair it struck.
    """
    assert OperatorIdentity is Producer
    assert IDENTITY.op_version == 1
    assert isinstance(IDENTITY.op_version, int)


# ---------------------------------------------------------------------------------------------
# 3. Behaviour -- the constructor, the latch and the id
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "missing"),
    [
        (Outcome.OK_PARTIAL, "partial_reason"),
        (Outcome.FAILED_TRANSIENT, "retry_after_ms"),
        (Outcome.FAILED_PERMANENT, "failure_class"),
        (Outcome.DEFERRED_BUDGET, "deferred_dim"),
    ],
)
def test_step_result_requires_what_its_outcome_requires(outcome: Outcome, missing: str) -> None:
    """08:222-231, transcribed. The invariant is in the constructor, not in review."""
    with pytest.raises(ValueError, match=missing):
        result(outcome)


def test_a_transient_failure_needs_a_class_as_well_as_a_cooldown() -> None:
    """08:233-236: the ladder escalates FROM the class's first cooldown.

    `work.rung_for()` takes the class as its key, so a classless transient failure is not a
    missing field -- it is a `None` lookup in the retry ladder, thousands of rows later.
    """
    with pytest.raises(ValueError, match="failure_class"):
        result(Outcome.FAILED_TRANSIENT, retry_after_ms=300_000)


def test_retry_after_ms_is_meaningful_only_for_failed_transient() -> None:
    """08:229-230 verbatim: a cooldown on an `ok` is a field nothing would ever read."""
    with pytest.raises(ValueError, match="only for failed_transient"):
        result(Outcome.OK, retry_after_ms=5)


def test_the_cache_key_width_is_the_one_length_rule() -> None:
    """08:230-231. 64 hex characters, and `CACHE_KEY_HEX_LEN` is that number's only home now."""
    assert CACHE_KEY_HEX_LEN == 64
    with pytest.raises(ValueError, match="64-char hex"):
        result(Outcome.OK, cache_key="short")


def test_an_outcome_outside_the_eight_is_refused_by_the_enum_and_by_the_store() -> None:
    """The P2 carrier checked the domain in `__post_init__`; the real type does not, and need not.

    08:222-231 prints no membership check because the field is typed `Outcome`, and the domain is
    the type. What the plan does check is what a type cannot express -- a length, and four
    conditional requirements. The boundary that a string could actually reach is `complete()`, and
    `test_store_queue.py::test_complete_refuses_an_outcome_outside_the_eight` hands it a
    duck-typed object with `outcome = 'mostly_ok'` and asserts a `StoreError` naming it.
    """
    with pytest.raises(ValueError, match="mostly_ok"):
        Outcome("mostly_ok")


def test_a_run_token_may_not_carry_a_deadline() -> None:
    """08's consequence (c). Three invocation deadlines must not collapse into one cancelled run."""
    clock = FakeClock()
    with pytest.raises(ValueError, match="run token has no deadline"):
        CancelToken("run", "r_abc", clock, deadline_mono_ns=1)
    assert CancelToken("run", "r_abc", clock).deadline_mono_ns is None
    assert CancelToken("request", "req-7", clock, deadline_mono_ns=1).deadline_mono_ns == 1


def test_a_token_names_its_scope_and_refuses_a_scope_it_does_not_have() -> None:
    """One token per scope (consequence (e)), so a token with no scope id names nothing."""
    clock = FakeClock()
    with pytest.raises(ValueError, match="'run' or 'request'"):
        CancelToken("session", "s1", clock)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="names its scope"):
        CancelToken("run", "", clock)


def test_the_first_cause_wins_and_the_second_cancel_returns_false() -> None:
    """08's consequence (f): the return value IS the two-interrupt sequence.

    *"A run that is interrupted and then passes a deadline still reports `interrupt`, and the
    manifest names what the operator did rather than what happened next."*
    """
    clock = FakeClock(mono=1_000)
    token = CancelToken("run", "r_abc", clock)

    assert token.cause() is None
    assert token.cancel(CancelReason.INTERRUPT, "ctrl-c") is True
    clock.mono = 2_000
    assert token.cancel(CancelReason.SHED, "stalled") is False

    cause = token.cause()
    assert cause == Cancellation(reason=CancelReason.INTERRUPT, at_mono_ns=1_000, detail="ctrl-c")
    assert token.cancelled() is True


def test_a_request_token_latches_its_own_deadline_exactly_once() -> None:
    """The deadline is checked by `cancelled()`, so it costs one integer comparison and no timer."""
    clock = FakeClock(mono=0)
    token = CancelToken("request", "req-7", clock, deadline_mono_ns=5_000_000)

    assert token.cancelled() is False
    assert token.cause() is None

    clock.mono = 5_000_000
    assert token.cancelled() is True
    assert token.cause() is not None
    assert token.cause().reason is CancelReason.DEADLINE  # type: ignore[union-attr]

    at = token.cause().at_mono_ns  # type: ignore[union-attr]
    clock.mono = 9_000_000
    assert token.cancelled() is True
    assert token.cause().at_mono_ns == at  # type: ignore[union-attr]


def test_a_run_token_reads_no_clock_at_all_on_the_not_cancelled_path() -> None:
    """08's consequence (d), measured rather than asserted in prose.

    *"A token that took a lock, read the store, or called `time.monotonic()` through anything but
    the injected `Clock` would be the cheapest available way to trip the very monitor that is
    supposed to be watching the work."* `cancelled()` is called at every loop top on every worker,
    and `loop_lag_max_ms = 250` is sampled at 100 ms. `FakeClock.reads` is the instrument.
    """
    clock = FakeClock()
    token = CancelToken("run", "r_abc", clock)

    for _ in range(1_000):
        assert token.cancelled() is False
    assert clock.reads == 0

    request = CancelToken("request", "req-7", clock, deadline_mono_ns=1 << 62)
    for _ in range(10):
        assert request.cancelled() is False
    assert clock.reads == 10


def test_remaining_ms_is_none_on_a_run_token_and_never_negative_on_a_request_one() -> None:
    """08:399 -- `ServiceHandle.post()` takes `min(remaining, request_timeout_s)` of this."""
    clock = FakeClock(mono=0)
    assert CancelToken("run", "r_abc", clock).remaining_ms() is None

    token = CancelToken("request", "req-7", clock, deadline_mono_ns=2_500_000)
    assert token.remaining_ms() == 2
    clock.mono = 9_000_000
    assert token.remaining_ms() == 0


def test_a_ulid_is_twenty_six_crockford_characters_and_sorts_by_mint_time() -> None:
    """08:285-287. Lexicographically sortable by mint time is the property, so it is the test."""
    minted = [
        ulid(ms * 1_000_000, bytes([index % 256]) * ULID_ENTROPY_BYTES)
        for index, ms in enumerate(range(1_757_400_000_000, 1_757_400_000_200, 7))
    ]

    assert all(len(value) == ULID_CHARS for value in minted)
    assert all(set(value) <= set(CROCKFORD32) for value in minted)
    assert minted == sorted(minted)
    assert len(set(minted)) == len(minted)


def test_the_crockford_alphabet_drops_the_four_characters_that_are_read_wrong() -> None:
    """No `I`, `L`, `O` or `U`. A `run_id` is read off a terminal and typed into `ow resume`."""
    assert len(CROCKFORD32) == 32
    assert set("ILOU").isdisjoint(CROCKFORD32)
    assert "".join(sorted(CROCKFORD32)) == CROCKFORD32


def test_a_ulid_refuses_the_wrong_width_of_entropy() -> None:
    """80 bits, because 48 + 80 is 128 and anything else is not a ULID."""
    with pytest.raises(ValueError, match="10 bytes"):
        ulid(1, b"\x00")
    with pytest.raises(ValueError, match="never negative"):
        ulid(-1, bytes(ULID_ENTROPY_BYTES))


def test_a_run_id_is_the_prefix_plus_the_ulid_and_nothing_else() -> None:
    """`'r_' + ulid(...)` -- 28 characters, and not a `uuid4` and not a counter."""
    clock = FakeClock(wall=1_757_400_000_000_000_000)
    run_id = new_run_id(clock, bytes(ULID_ENTROPY_BYTES))

    assert run_id.startswith(RUN_ID_PREFIX)
    assert len(run_id) == len(RUN_ID_PREFIX) + ULID_CHARS
    assert run_id[len(RUN_ID_PREFIX) :] == ulid(clock.wall, bytes(ULID_ENTROPY_BYTES))


def test_run_context_service_delegates_and_holds_no_registry_logic() -> None:
    """08:283. A Service is named and never routed, so `service()` has nothing to decide."""
    asked: list[str] = []

    class Registry:
        def get(self, name: str) -> object:
            asked.append(name)
            return f"handle:{name}"

    clock = FakeClock()
    ctx = RunContext(
        run_id="r_abc",
        generation=1,
        trigger="cli",
        roots=Roots(source=Path("src"), output=Path("out"), cache=Path("cache")),
        config_digest="cd",
        semantic_digest="sd",
        policy_digest="pd",
        pricebook_digest="pb",
        catalog_digest="ct",
        limits=object(),
        admission=object(),
        services=Registry(),  # type: ignore[arg-type]
        budget=object(),
        cancel=CancelToken("run", "r_abc", clock),
        clock=clock,
        events=object(),
    )

    assert ctx.service("vlm") == "handle:vlm"
    assert asked == ["vlm"]


# ---------------------------------------------------------------------------------------------
# 4. The module's own boundaries
# ---------------------------------------------------------------------------------------------


def test_importing_the_runners_vocabulary_loads_no_loop() -> None:
    """G23, at the one module in core most likely to break it.

    08:186's header says *"SYNCHRONOUS, stdlib only (G23: no asyncio, no selectors)"*, and
    `RunContext.admission` is the field that would have carried a loop in: `Admission`'s four
    families are `asyncio.BoundedSemaphore` instances, which is why `AdmissionView` narrows to the
    two water marks. This asserts the source, not the process: another test may have imported
    `asyncio` first, so what matters is that this module does not name it.
    """
    tree = ast.parse(OPERATOR_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "asyncio" not in imported
    assert "selectors" not in imported
    assert "omniweave" not in imported, "core imports omniweave_ports, never omniweave (G4)"


def test_the_module_reaches_for_no_ambient_clock_and_no_ambient_randomness() -> None:
    """08:288-296's third ban, and `pyproject.toml`'s fourth banned import.

    `Cancellation.at_mono_ns` and `run_id` both need a reading, and both take it as an argument.
    A `time.monotonic_ns()` or an `os.urandom()` in this file would be the ambient source the
    injection exists to remove -- and `random` is banned outright: *"Sampling is blake2b.
    Determinism is a gate, not a habit."*
    """
    source = OPERATOR_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"time", "random", "os", "secrets", "uuid"})


def test_the_owed_types_are_exactly_the_pinned_set() -> None:
    """Every `# noqa: F821` in the module names a type, and the set is this file's constant.

    The counterpart of `store/__init__.py`'s file-level suppression, at line granularity: the
    suppression removes ruff's check on one line, and pinning the set here is what replaces it.
    `RUF100` is the other half -- the day one of these lands, the suppression becomes unused and
    ruff fails the build asking for it to be deleted.
    """
    source = OPERATOR_SOURCE.read_text(encoding="utf-8")
    suppressed = {
        name
        for line in source.splitlines()
        if "noqa: F821" in line
        for name in re.findall(r"\b([A-Z][A-Za-z]+)\b", line.split("#")[0])
        if not hasattr(op, name) and not keyword.iskeyword(name)
    }
    # `Sequence` shares the `Operator.plan()` line and resolves for the type checker only: it is
    # imported under `if TYPE_CHECKING`, so it is absent from the module at runtime without being
    # owed by anyone. It is the one name the scan cannot tell apart from a debt, so it is named.
    assert suppressed - {"Sequence"} == EXPECTED_UNRESOLVED
    assert all(not hasattr(op, name) for name in EXPECTED_UNRESOLVED)


def test_the_docstring_table_names_every_owed_type_and_the_one_that_is_not_owed() -> None:
    """A reader's index of the debt, kept true by the same set the linter is kept true by."""
    doc = op.__doc__ or ""
    for name in EXPECTED_UNRESOLVED:
        assert f"| `{name}` |" in doc, f"{name} is suppressed but not listed in the table"
    assert "`ServiceRegistry`" in doc
    assert "`ServiceRegistryView`" in ", ".join(op.__all__) or hasattr(op, "ServiceRegistryView")


@pytest.mark.parametrize("protocol", [SpendVector, AdmissionView, ServiceRegistryView])
def test_the_structural_stand_ins_are_runtime_checkable_and_narrow(protocol: type) -> None:
    """A stand-in exists so a seam can assert what it was handed, which needs the check to run.

    Narrow is the other half: `AdmissionView` names two integers out of `Admission`'s six fields
    and `ServiceRegistryView` one method out of seam S3's whole surface, because a stand-in that
    described the entire type would be the second declaration INV-21 forbids rather than a
    description of what is read.
    """
    assert getattr(protocol, "_is_runtime_protocol", False)
    assert (
        len(protocol.__annotations__)
        + len([name for name in vars(protocol) if not name.startswith("_")])
        <= 9
    )


def test_the_spend_vector_is_the_plans_seven_units_plus_a_provider_and_no_price() -> None:
    """05:2366-2374. INV-15: *"THE ONLY PLACE MONEY APPEARS"* is `Spend.micros(book)`.

    A stand-in that carried `micros()` would let a sink price something, which is the one thing
    the seven-unit vector exists to prevent.
    """
    assert tuple(SpendVector.__annotations__) == (
        "wall_ms",
        "cpu_ms",
        "gpu_ms",
        "tokens_in",
        "tokens_out",
        "calls",
        "bytes_egress",
        "provider",
    )
    assert not hasattr(SpendVector, "micros")


def test_the_store_no_longer_declares_a_spend_vector_of_its_own() -> None:
    """INV-21: the shape moved here, and `store/graph.py` re-exports rather than re-declares."""
    assert store_graph.SpendVector is SpendVector
    assert "SpendVector" in store_graph.__all__
    source = Path(inspect.getfile(store_graph)).read_text(encoding="utf-8")
    assert "class SpendVector" not in source


def test_the_carriers_are_gone_from_the_store_queue() -> None:
    """P2 said *"deleted the day `operator.py` lands"*, and this is that day."""
    assert not hasattr(store_queue, "StepResult")
    assert not hasattr(store_queue, "StepMetrics")
    assert not hasattr(store_queue, "CACHE_KEY_HEX_LEN")
    assert hasattr(store_queue, "StepResultView")
    assert hasattr(store_queue, "StepMetricsView")


def test_the_module_is_not_reached_by_a_bare_core_import() -> None:
    """Not one of the nine LAZY names, but not eager either: `import omniweave_core` loads nothing.

    G17 asserts the nine; this asserts that adding a tenth module to `omniweave_core/` did not
    quietly put it on the hook path, which has a 250 ms p95 warm budget (G26).
    """
    source = Path(inspect.getfile(sys.modules["omniweave_core"])).read_text(encoding="utf-8")
    assert "import operator" not in source
    assert "from omniweave_core.operator" not in source
