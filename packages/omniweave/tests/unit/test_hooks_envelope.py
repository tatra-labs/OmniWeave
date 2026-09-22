"""The envelope: the channel, the caps, the key, the kill switches and the deadline.

**Every assertion here is about a component whose failures are invisible from outside.** A hook
exits 0 whatever happened (10:1842), so the thing under test is not the exit code -- it is the
`Outcome`, which is the only place a crash, a deadline breach and a working silent tier are three
different facts rather than one empty stdout.

No clock is read and no environment is inherited: both arrive as arguments, which is why none of
these tests sleeps and none of them is a race.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.hooks.envelope as envelope_module
import pytest
from omniweave.hooks.envelope import (
    CHANNEL,
    COUNTER_PREFIX,
    DECISION_CHANNEL,
    DECISION_REASON,
    DENY,
    EVENTS,
    EXIT_OK,
    KILL_SWITCH,
    KILL_VALUE,
    SELF_DEADLINE_MS,
    Advice,
    Outcome,
    counter,
    emission,
    run,
    session_key,
    silent_because,
    unmeasured,
)
from omniweave_core.config import KEYS, NON_KEY_ENV_VARS, default_env_name

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Path(__file__).resolve().parents[4]
MS = 1_000_000


@dataclass
class Ticking:
    """A `Clock` that reads from a script. The last reading repeats, so a caller cannot run out."""

    readings: list[int] = field(default_factory=lambda: [0, 0])
    wall: int = 1_700_000_000_000_000_000

    def monotonic_ns(self) -> int:
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]

    def wall_ns(self) -> int:
        return self.wall


def _took(ms: int) -> Ticking:
    """A clock under which the handler appears to take `ms` milliseconds."""
    return Ticking(readings=[0, ms * MS])


def _advice(text: str = "hello", *, deny: bool = False, tier: str = "high-cite") -> Advice:
    return Advice(text=text, deny=deny, counter=tier)


def _handler(advice: Advice | None = None):
    def inner(_payload: Mapping[str, Any]) -> Advice:
        return advice if advice is not None else _advice()

    return inner


# ---------------------------------------------------------------------------------------------
# The exit discipline, and what makes it observable anyway
# ---------------------------------------------------------------------------------------------


def test_the_exit_code_is_a_constant_and_takes_nothing_that_could_change_it() -> None:
    """10:1842 states a rule, not a default. A field would let a caller pass `1`."""
    assert list(inspect.signature(Outcome.exit_code).parameters) == ["self"]
    assert Outcome().exit_code() == EXIT_OK == 0
    assert "exit_code" not in set(Outcome.__dataclass_fields__)


def test_a_handler_that_raises_is_counted_and_never_propagates() -> None:
    def boom(_payload: Mapping[str, Any]) -> Advice:
        raise ValueError("the user asked about acme merger terms")

    outcome = run("UserPromptSubmit", {}, boom, clock=_took(5), env={})
    assert outcome.exit_code() == EXIT_OK
    assert outcome.failed == "ValueError"
    assert outcome.counters == ("ow-hook-ups-noop-failure",)
    assert not outcome.spoke()


def test_the_failure_carries_a_class_name_and_never_the_message() -> None:
    """10:1990's rule is that a counter records that something happened, never what the user
    typed -- and an exception message is the one channel through which a prompt could reach one."""
    typed_by_the_user = "acme merger terms"

    def boom(_payload: Mapping[str, Any]) -> Advice:
        raise RuntimeError(typed_by_the_user)

    outcome = run("UserPromptSubmit", {}, boom, clock=_took(5), env={})
    assert typed_by_the_user not in str(outcome)
    assert typed_by_the_user not in outcome.failed
    assert typed_by_the_user not in " ".join(outcome.counters)


def test_a_base_exception_is_not_swallowed() -> None:
    """`except Exception` and not `except BaseException`: a `KeyboardInterrupt` is the host taking
    the process away, and reporting an `Outcome` nobody will read would be this module deciding it
    outranks its caller."""

    def interrupted(_payload: Mapping[str, Any]) -> Advice:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run("UserPromptSubmit", {}, interrupted, clock=_took(1), env={})


@pytest.mark.parametrize(
    ("env", "tty", "expected"),
    [
        ({KILL_SWITCH: KILL_VALUE}, False, "ow-hook-ups-noop-killed"),
        ({}, True, "ow-hook-ups-noop-tty"),
    ],
)
def test_a_kill_switch_stops_the_handler_being_called_at_all(
    env: dict[str, str], tty: bool, expected: str
) -> None:
    called: list[int] = []

    def counted(_payload: Mapping[str, Any]) -> Advice:
        called.append(1)
        return _advice()

    outcome = run("UserPromptSubmit", {}, counted, clock=Ticking(), env=env, tty=tty)
    assert called == []
    assert outcome.counters == (expected,)
    assert not outcome.spoke()


def test_only_the_exact_kill_value_kills() -> None:
    """A variable that is set to something else is not a kill switch: `OMNIWEAVE_HOOK=1` and
    `OMNIWEAVE_HOOK=true` are both an operator turning it ON in the spelling they guessed."""
    assert silent_because({KILL_SWITCH: "0"}, tty=False) == "noop-killed"
    for value in ("1", "true", "", "00", "off"):
        assert silent_because({KILL_SWITCH: value}, tty=False) == ""


def test_an_unknown_event_is_counted_and_never_raised() -> None:
    outcome = run("SomeFutureEvent", {}, _handler(), clock=Ticking(), env={})
    assert outcome.counters == ("ow-hook-unknown-noop-event",)
    assert outcome.exit_code() == EXIT_OK


# ---------------------------------------------------------------------------------------------
# The deadline
# ---------------------------------------------------------------------------------------------


def test_a_handler_inside_the_budget_speaks() -> None:
    outcome = run("UserPromptSubmit", {}, _handler(), clock=_took(120), env={})
    assert outcome.spoke()
    assert outcome.elapsed_ms == 120
    assert not outcome.breached
    assert outcome.counters == ("ow-hook-ups-high-cite",)


def test_a_late_handler_emits_nothing_and_says_so_on_the_outcome() -> None:
    """The deadline cannot preempt a handler -- it can only stop a late answer being injected, and
    that is what `-noop-deadline` records."""
    outcome = run("UserPromptSubmit", {}, _handler(), clock=_took(401), env={})
    assert not outcome.spoke()
    assert outcome.breached
    assert outcome.elapsed_ms == 401
    assert outcome.counters == ("ow-hook-ups-noop-deadline",)
    assert outcome.exit_code() == EXIT_OK


def test_the_budget_boundary_is_inclusive() -> None:
    assert not run("UserPromptSubmit", {}, _handler(), clock=_took(400), env={}).breached
    assert run("UserPromptSubmit", {}, _handler(), clock=_took(401), env={}).breached


def test_the_elapsed_rounds_up_so_a_breach_cannot_be_won_by_a_rounding_rule() -> None:
    clock = Ticking(readings=[0, 400 * MS + 1])
    outcome = run("UserPromptSubmit", {}, _handler(), clock=clock, env={})
    assert outcome.elapsed_ms == 401
    assert outcome.breached


def test_the_duration_is_monotonic_and_a_wall_clock_step_cannot_reach_it() -> None:
    """`clock.py`: *"`monotonic_ns()` is the only source for a duration."* A backward NTP step
    during a hook must not turn a 5 ms handler into a breach."""

    class Stepping(Ticking):
        def wall_ns(self) -> int:
            return -1_000_000_000_000

    outcome = run("UserPromptSubmit", {}, _handler(), clock=Stepping(readings=[0, 5 * MS]), env={})
    assert outcome.elapsed_ms == 5
    assert not outcome.breached


def test_the_self_deadline_is_below_the_cold_budget_of_the_gate_that_measures_it() -> None:
    """D394, read from both registers. Every cold invocation between 400 ms and 1 s is inside G26
    and past the hook's own deadline, so the run that matters most is one a healthy gate reports
    as healthy and the hook answers with silence."""
    gates = tomllib.loads((REPO / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(g for g in gates["gate"] if g["id"] == "G26")
    assert "250 ms warm" in row["assertion"]
    assert "1 s cold" in row["assertion"]
    assert SELF_DEADLINE_MS == 400
    assert SELF_DEADLINE_MS < 1000, "the deadline is inside the cold budget it is measured against"


# ---------------------------------------------------------------------------------------------
# The output channel
# ---------------------------------------------------------------------------------------------


def test_the_only_key_that_reaches_the_model_is_additional_context() -> None:
    """10:1859, *"the single most important undocumented fact in this layer"*: stderr and a
    top-level `systemMessage` surface to the USER, so steering text in either is inert."""
    body = json.loads(emission("UserPromptSubmit", _advice("read the handbook")))
    assert set(body) == {"hookSpecificOutput"}
    assert body["hookSpecificOutput"][CHANNEL] == "read the handbook"
    assert body["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "systemMessage" not in emission("UserPromptSubmit", _advice())


@pytest.mark.parametrize("event", ["PreCompact", "PostToolUse", "SessionEnd"])
def test_an_event_with_no_channel_emits_nothing_whatever_it_is_handed(event: str) -> None:
    """10:1929: a shipped handler wrote its briefing into a `PreCompact` `systemMessage` hosts
    discard, for a whole release line. Here the refusal is structural rather than remembered."""
    assert emission(event, _advice("a restoration briefing")) == ""
    assert emission(event, _advice("x", deny=True)) == ""
    assert not EVENTS[event].speaks()
    outcome = run(event, {}, _handler(_advice("briefing")), clock=_took(5), env={})
    assert not outcome.spoke()


def test_the_text_is_capped_at_the_events_own_number() -> None:
    """The cap is on the FIELD: 10:1970 charges the `<ow:untrusted>` wrapper *"against the same
    field"*, so a caller that wrapped and then capped would ship a torn frame."""
    for event, spec in EVENTS.items():
        if not spec.speaks():
            continue
        body = json.loads(emission(event, _advice("x" * (spec.cap + 500))))
        assert len(body["hookSpecificOutput"][CHANNEL]) == spec.cap


def test_the_caps_are_the_plans_own_table_and_not_a_transcription() -> None:
    """10:1849's six rows, parsed out of the document rather than retyped, so an amended cap is a
    failing test rather than a number two files disagree about."""
    text = (REPO / "_plan" / "10-interfaces.md").read_text(encoding="utf-8")
    declared: dict[str, int] = {}
    for line in text.split("\n"):
        match = re.match(r"^\| `(\w+)` \|.*\| ([\d,]+|—) \|$", line.strip())
        if match and match.group(1) in EVENTS:
            raw = match.group(2)
            declared[match.group(1)] = 0 if raw == "—" else int(raw.replace(",", ""))
    assert declared == {name: spec.cap for name, spec in EVENTS.items()}


def test_a_deny_uses_the_decision_channel_and_still_exits_zero() -> None:
    """10:2049: the decision is emitted *"with exit code 0, so the harness reads the decision
    rather than a crash."*"""
    outcome = run(
        "PreToolUse",
        {},
        _handler(_advice("policy.pdf is indexed", deny=True)),
        clock=_took(9),
        env={},
    )
    body = json.loads(outcome.stdout)["hookSpecificOutput"]
    assert body[DECISION_CHANNEL] == DENY
    assert body[DECISION_REASON] == "policy.pdf is indexed"
    assert CHANNEL not in body
    assert outcome.exit_code() == EXIT_OK


def test_there_is_no_allow_decision_anywhere_in_the_module() -> None:
    """10:2043 makes `advisory` the default and an unknown `OMNIWEAVE_ENFORCE` fall back to it, so
    the framework either says nothing or says `deny`. An `allow` would spend the channel to permit
    what was already permitted."""
    source = Path(envelope_module.__file__).read_text(encoding="utf-8")
    assert '"allow"' not in source
    assert DENY == "deny"


def test_an_advice_with_nothing_to_say_emits_nothing() -> None:
    assert emission("UserPromptSubmit", Advice()) == ""
    assert not run("UserPromptSubmit", {}, _handler(Advice()), clock=_took(3), env={}).spoke()


def test_the_emission_is_one_line_of_real_utf8() -> None:
    line = emission("UserPromptSubmit", _advice("a \u2014 b"))
    assert "\n" not in line
    assert "\u2014" in line


# ---------------------------------------------------------------------------------------------
# The session key
# ---------------------------------------------------------------------------------------------


def test_the_key_is_the_derivation_the_plan_prints() -> None:
    raw = "/home/u/.claude/projects/x/abc.jsonl"
    expected = hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    assert session_key({"transcript_path": raw}) == expected
    assert len(expected) == 16


def test_a_session_id_outranks_a_transcript_path() -> None:
    both = session_key({"session_id": "s1", "transcript_path": "/p"})
    assert both == session_key({"session_id": "s1"})
    assert both != session_key({"transcript_path": "/p"})


def test_no_identity_is_an_empty_key_and_never_a_hash_of_nothing() -> None:
    """10:1911: an empty key means dedup is off and the hook exits 0 *"rather than writing a file
    named after nothing"* -- so it must not be the sha256 of the empty string."""
    for payload in ({}, {"session_id": ""}, {"session_id": None}):
        assert session_key(payload) == ""
    assert session_key({}) != hashlib.sha256(b"").hexdigest()[:16]


def test_an_unpaired_surrogate_in_a_path_does_not_raise() -> None:
    """`surrogatepass` is the plan's error handler and it is load-bearing on Windows, where a path
    can carry one. A raise here would be a hook failing on the deployments least able to say so."""
    assert len(session_key({"transcript_path": "C:/x/\ud800/t.jsonl"})) == 16


def test_the_key_is_a_safe_filename_on_every_platform() -> None:
    """10:1907's first clause. The key names a file the whole deployment can read."""
    key = session_key({"transcript_path": "../../etc/passwd\x00:*?"})
    assert re.fullmatch(r"[0-9a-f]{16}", key)


# ---------------------------------------------------------------------------------------------
# The counters, and the two registers they are not in
# ---------------------------------------------------------------------------------------------


def test_the_worked_counter_names_from_the_plan_are_the_ones_this_module_builds() -> None:
    """10:1990 names seven, spells the first in full and elides the prefix on the other six."""
    text = (REPO / "_plan" / "10-interfaces.md").read_text(encoding="utf-8")
    spelled = set(re.findall(r"ow-hook-[a-z-]+", text))
    assert spelled == {"ow-hook-ups-high-cite"}
    elided = {s.lstrip("-") for s in re.findall(r"`(-(?:high|medium|noop)-[a-z-]+)`", text)}
    tiers = {"high-cite"} | elided
    assert tiers == {
        "high-cite",
        "high-token",
        "high-fts",
        "medium-outline",
        "noop-shape",
        "noop-no-corpus",
        "noop-deadline",
    }
    assert counter("ups", "high-cite") == "ow-hook-ups-high-cite"
    assert all(name.startswith(f"{COUNTER_PREFIX}-ups-") for name in spelled)


def test_the_deadline_counter_is_cross_cutting_and_the_plan_files_it_under_one_event() -> None:
    """D396's other half. The 400 ms self-deadline is stated for all six handlers (10:1842) and
    `-noop-deadline` is written among UPS's seven -- so either five events breach their budget
    with no counter, or the namespace is wrong. The envelope emits it for whichever event ran."""
    for event, spec in EVENTS.items():
        outcome = run(event, {}, _handler(), clock=_took(SELF_DEADLINE_MS + 1), env={})
        assert outcome.breached
        assert outcome.counters == (f"{COUNTER_PREFIX}-{spec.slug}-noop-deadline",)


def test_five_of_the_six_events_have_no_counter_names_and_the_one_rule_collides() -> None:
    """D396. The slugs are this module's because the plan gives one worked example and no rule, and
    the obvious rule -- initials -- is not it: `PreToolUse` and `PostToolUse` share theirs."""
    initials = {name: "".join(ch for ch in name if ch.isupper()).lower() for name in EVENTS}
    assert initials["PreToolUse"] == initials["PostToolUse"] == "ptu"
    assert len(set(initials.values())) < len(EVENTS)
    assert len({spec.slug for spec in EVENTS.values()}) == len(EVENTS)


def test_the_kill_switch_is_in_neither_of_the_two_env_populations() -> None:
    """D395. `NON_KEY_ENV_VARS`'s own docstring argues the partition must be total -- *"a set of
    four would leave one `OMNIWEAVE_*` name the framework reads belonging to neither population,
    and any gate asserting that partition is total would fail on it"* -- and then takes two of the
    three hook variables."""
    twins = {default_env_name(key) for key in KEYS}
    assert KILL_SWITCH not in twins
    assert KILL_SWITCH not in NON_KEY_ENV_VARS
    assert "OMNIWEAVE_ENFORCE" in NON_KEY_ENV_VARS
    assert "OMNIWEAVE_HOOK_TTL" in NON_KEY_ENV_VARS


def test_a_counter_name_is_a_tier_and_can_carry_nothing_a_user_typed() -> None:
    outcome = run(
        "UserPromptSubmit",
        {"prompt": "what are the acme merger terms"},
        _handler(_advice("x", tier="high-fts")),
        clock=_took(10),
        env={},
    )
    assert outcome.counters == ("ow-hook-ups-high-fts",)
    assert all(re.fullmatch(r"[a-z0-9-]+", name) for name in outcome.counters)


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(envelope_module.__file__).read_text(encoding="utf-8"))


def test_the_envelope_imports_nothing_first_party_at_run_time() -> None:
    """G26 doubles the budget for a cold start, and the cheapest import is the one not written.
    The `Clock` arrives as an argument and the environment arrives as an argument."""
    runtime: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.Import):
            runtime |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            runtime.add(node.module.split(".")[0])
    assert runtime == {"__future__", "hashlib", "json", "dataclasses", "types", "typing"}
    assert not {name for name in runtime if name.startswith("omniweave")}


def test_no_part_of_this_package_pays_a_loop_import() -> None:
    """02:258's forbidden column: *"a hook must not pay a loop import (G26, INV-3)."*"""
    package = Path(envelope_module.__file__).parent
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert roots.isdisjoint({"asyncio", "selectors", "socket", "sqlite3"}), path.name


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(envelope_module.__all__)


def test_what_the_instrumentation_owes_is_reported_rather_than_absorbed() -> None:
    owed = unmeasured()
    assert len(owed) == 3
    assert any("D394" in line for line in owed)
    assert any("D396" in line for line in owed)
    assert any("append discipline" in line for line in owed)
