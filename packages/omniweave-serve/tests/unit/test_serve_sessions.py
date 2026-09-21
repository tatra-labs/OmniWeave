"""The session registry, through every state and both configurations of its timeout.

**Integers for time again.** `SessionRegistry` takes a monotonic reading as an argument and holds
no clock, so an hour of idleness is one integer and a reap that takes four sessions in
least-recently-seen order is four. Same trade as `admission.py`, and the two now share
`elapsed_ms()` rather than spelling the floor-and-clamp twice.

**The `--session-timeout 0` half is tested as thoroughly as the default.** It is the configuration
under which the plan's own `retry_after_ms` requirement has no answer (D354), and a module that
only ever ran with reaping on would make that gap invisible.
"""

from __future__ import annotations

import ast
from pathlib import Path

import omniweave_serve.sessions as sessions_module
import pytest
from omniweave_core.answer.dedup import DEDUP_OFF_MESSAGE, LEDGER_RESET_KIND, SessionLedger
from omniweave_core.config import KEYS, load
from omniweave_core.errors import ConfigError, InternalError, ResourceLimit
from omniweave_core.operator import RUN_ID_PREFIX, ULID_CHARS, ULID_ENTROPY_BYTES
from omniweave_serve.admission import OVERLOADED, elapsed_ms
from omniweave_serve.sessions import (
    DEFAULT_TIMEOUT_S,
    KEY_MAX_SESSIONS,
    SESSION_ID_PREFIX,
    TIMEOUT_DISABLED,
    Opened,
    Refused,
    SessionRegistry,
    new_session_id,
    overloaded,
    stateless_degradation,
)

SECOND = 1_000_000_000
"""One second in nanoseconds, because every reading in this file is one."""

ENTROPY = b"0123456789"
"""Exactly `ULID_ENTROPY_BYTES`. A test below asserts that anything else is refused."""


def _registry(**over: int) -> SessionRegistry:
    numbers = {"max_sessions": 3, "timeout_s": 60}
    numbers.update(over)
    return SessionRegistry(**numbers)  # type: ignore[arg-type]


def _fill(registry: SessionRegistry, *, at_ns: int = 0) -> list[Opened | Refused]:
    """Open sessions until one is refused, and return every answer including the refusal."""
    out: list[Opened | Refused] = []
    index = 0
    while True:
        index += 1
        answer = registry.open(f"sess_{index:026d}", at_ns=at_ns)
        out.append(answer)
        if isinstance(answer, Refused):
            return out


# ---------------------------------------------------------------------------------------------
# The two numbers, one of which has no home
# ---------------------------------------------------------------------------------------------


def test_the_cap_is_the_registrys_and_is_not_transcribed() -> None:
    declared = KEYS[KEY_MAX_SESSIONS].default
    assert declared == 64, "10:2399's file-descriptor argument"
    assert isinstance(declared, int)
    registry = SessionRegistry.shipped()
    assert registry.live == 0
    for index in range(declared):
        assert isinstance(registry.open(f"sess_{index:026d}", at_ns=0), Opened)
    assert registry.live == declared
    assert isinstance(registry.open("sess_" + "9" * 26, at_ns=0), Refused)


def test_the_timeout_is_a_flag_default_with_no_configuration_row() -> None:
    """D353. `max_sessions` is a key with no flag; this is a flag with no key. Two knobs on one
    object, each reachable through only one of the two channels."""
    assert DEFAULT_TIMEOUT_S == 3600
    assert "serve.session_timeout" not in KEYS
    assert not [name for name in KEYS if "session_timeout" in name]


def test_from_config_reads_the_cap_and_takes_the_timeout_as_an_argument(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "omniweave.toml").write_text(
        "[serve]\nmax_sessions = 2\n", encoding="utf-8", newline="\n"
    )
    config = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    registry = SessionRegistry.from_config(config, timeout_s=30)
    answers = _fill(registry)
    assert [isinstance(a, Opened) for a in answers] == [True, True, False]
    assert registry.reaping is True


def test_a_cap_below_one_is_refused_and_names_the_alternative() -> None:
    """A stateful server that admits no session is not a configuration, it is `--stateless`."""
    with pytest.raises(ConfigError) as caught:
        _registry(max_sessions=0)
    assert KEY_MAX_SESSIONS in str(caught.value)
    assert "--stateless" in caught.value.fix


def test_a_negative_timeout_is_refused_and_zero_is_not() -> None:
    with pytest.raises(ConfigError, match="negative means nothing"):
        _registry(timeout_s=-1)
    assert _registry(timeout_s=TIMEOUT_DISABLED).reaping is False


# ---------------------------------------------------------------------------------------------
# The id
# ---------------------------------------------------------------------------------------------


def test_a_session_id_is_a_prefixed_ulid() -> None:
    session_id = new_session_id(wall_ns=1_700_000_000 * SECOND, entropy=ENTROPY)
    assert session_id.startswith(SESSION_ID_PREFIX)
    assert len(session_id) == len(SESSION_ID_PREFIX) + ULID_CHARS


def test_the_prefix_is_not_the_run_id_prefix() -> None:
    """`r_` is a run and `sess_` is a session. One prefix per kind of id."""
    assert SESSION_ID_PREFIX != RUN_ID_PREFIX
    assert not SESSION_ID_PREFIX.startswith(RUN_ID_PREFIX)


@pytest.mark.parametrize("short", [b"", b"0", b"0123", b"0" * 9, b"0" * 11])
def test_entropy_of_the_wrong_length_is_refused_rather_than_padded(short: bytes) -> None:
    """A session id is a bearer credential for the life of a session: anyone who guesses one
    resumes another client's conversation. A caller passing four bytes must get an error, not a
    short id that looks like the others."""
    assert len(short) != ULID_ENTROPY_BYTES
    with pytest.raises(ValueError, match="exactly"):
        new_session_id(wall_ns=SECOND, entropy=short)


def test_two_ids_from_one_millisecond_differ_by_their_entropy() -> None:
    first = new_session_id(wall_ns=SECOND, entropy=b"aaaaaaaaaa")
    second = new_session_id(wall_ns=SECOND, entropy=b"bbbbbbbbbb")
    assert first != second


def test_ids_minted_in_order_sort_in_order() -> None:
    """A ULID is lexicographically sortable by mint time, which is what makes a reap's output
    readable in a log without a second timestamp."""
    early = new_session_id(wall_ns=1_000 * SECOND, entropy=ENTROPY)
    late = new_session_id(wall_ns=2_000 * SECOND, entropy=ENTROPY)
    assert early < late


# ---------------------------------------------------------------------------------------------
# Opening, resuming and refusing
# ---------------------------------------------------------------------------------------------


def test_the_cap_is_applied_and_the_refusal_reports_the_count() -> None:
    answers = _fill(_registry())
    assert [isinstance(a, Opened) for a in answers] == [True, True, True, False]
    refused = answers[-1]
    assert isinstance(refused, Refused)
    assert refused.live == 3


def test_opening_a_live_session_is_a_resume_and_not_a_second_reader() -> None:
    """A client replaying `initialize` on its own session has not asked for a second reader, and
    refusing it would consume the ceiling twice for one caller."""
    registry = _registry(max_sessions=1)
    first = registry.open("sess_a", at_ns=0)
    again = registry.open("sess_a", at_ns=30 * SECOND)
    assert isinstance(first, Opened)
    assert isinstance(again, Opened)
    assert registry.live == 1
    assert registry.reap(at_ns=61 * SECOND) == (), "the resume moved `last_seen` forward"


def test_a_resume_does_not_replace_the_ledger() -> None:
    registry = _registry()
    registry.open("sess_a", at_ns=0)
    ledger = registry.ledger("sess_a")
    registry.open("sess_a", at_ns=SECOND)
    assert registry.ledger("sess_a") is ledger


def test_an_empty_session_id_is_our_bug() -> None:
    """There is no such thing as a stateful session with no id; that is `--stateless`, which holds
    no registry at all."""
    with pytest.raises(InternalError, match="--stateless"):
        _registry().open("", at_ns=0)


def test_every_live_session_has_a_ledger_keyed_on_its_id() -> None:
    registry = _registry()
    registry.open("sess_a", at_ns=0)
    ledger = registry.ledger("sess_a")
    assert isinstance(ledger, SessionLedger)
    assert ledger.key == "sess_a"
    assert registry.ledger("sess_b") is None


def test_touch_moves_last_seen_and_reports_an_unknown_session() -> None:
    registry = _registry()
    registry.open("sess_a", at_ns=0)
    assert registry.touch("sess_a", at_ns=59 * SECOND) is True
    assert registry.reap(at_ns=100 * SECOND) == (), "59 + 60 > 100"
    assert registry.touch("sess_gone", at_ns=0) is False


# ---------------------------------------------------------------------------------------------
# Closing and reaping
# ---------------------------------------------------------------------------------------------


def test_close_frees_a_slot_and_clears_the_ledger() -> None:
    registry = _registry(max_sessions=1)
    registry.open("sess_a", at_ns=0)
    ledger = registry.ledger("sess_a")
    assert ledger is not None
    assert isinstance(registry.open("sess_b", at_ns=0), Refused)

    assert registry.close("sess_a") is True
    assert registry.live == 0
    assert ledger.stats()["calls"] == 0
    assert isinstance(registry.open("sess_b", at_ns=0), Opened)


def test_closing_an_unknown_session_is_false_and_not_an_error() -> None:
    """A `DELETE` for a session that already timed out is the normal race, not a fault."""
    assert _registry().close("sess_gone") is False


def test_a_reap_takes_everything_at_or_past_the_timeout() -> None:
    registry = _registry(max_sessions=4, timeout_s=60)
    registry.open("sess_a", at_ns=0)
    registry.open("sess_b", at_ns=10 * SECOND)
    registry.open("sess_c", at_ns=59 * SECOND)
    taken = registry.reap(at_ns=60 * SECOND)
    assert [row.session_id for row in taken] == ["sess_a"], "exactly 60 s idle is reapable"
    assert registry.live == 2


def test_a_reap_is_least_recently_seen_first_and_reports_the_idle_time() -> None:
    registry = _registry(max_sessions=4, timeout_s=10)
    registry.open("sess_late", at_ns=5 * SECOND)
    registry.open("sess_early", at_ns=0)
    taken = registry.reap(at_ns=100 * SECOND)
    assert [row.session_id for row in taken] == ["sess_early", "sess_late"]
    assert [row.idle_ms for row in taken] == [100_000, 95_000]


def test_a_reap_clears_the_ledger_it_drops() -> None:
    """10:2395: *"reaping clears that session's ledger"*. The object may outlive the registry in
    a caller's hand, so clearing it is not the same as forgetting it."""
    registry = _registry(timeout_s=1)
    registry.open("sess_a", at_ns=0)
    ledger = registry.ledger("sess_a")
    assert ledger is not None
    registry.reap(at_ns=10 * SECOND)
    assert registry.ledger("sess_a") is None
    assert ledger.stats() == {"calls": 0, "corpora": 0, "docs": 0, "blocks": 0, "chars_sent": 0}


def test_reaping_disabled_takes_nothing_however_idle() -> None:
    """`0` is a configuration and not an omission, so a decade of idleness is still not a reap."""
    registry = _registry(timeout_s=TIMEOUT_DISABLED)
    registry.open("sess_a", at_ns=0)
    assert registry.reap(at_ns=10**9 * SECOND) == ()
    assert registry.live == 1


def test_a_reap_frees_the_ceiling() -> None:
    registry = _registry(max_sessions=1, timeout_s=1)
    registry.open("sess_a", at_ns=0)
    assert isinstance(registry.open("sess_b", at_ns=2 * SECOND), Refused)
    assert len(registry.reap(at_ns=2 * SECOND)) == 1
    assert isinstance(registry.open("sess_b", at_ns=2 * SECOND), Opened)


# ---------------------------------------------------------------------------------------------
# The wait the plan requires and cannot always have
# ---------------------------------------------------------------------------------------------


def test_the_wait_is_the_time_until_the_oldest_becomes_reapable() -> None:
    registry = _registry(max_sessions=2, timeout_s=60)
    registry.open("sess_a", at_ns=0)
    registry.open("sess_b", at_ns=30 * SECOND)
    refused = registry.open("sess_c", at_ns=45 * SECOND)
    assert isinstance(refused, Refused)
    assert refused.retry_after_ms == 15_000, "60 s timeout, 45 s idle on the oldest"


def test_the_wait_is_floored_at_one_and_never_zero() -> None:
    registry = _registry(max_sessions=1, timeout_s=60)
    registry.open("sess_a", at_ns=0)
    refused = registry.open("sess_b", at_ns=60 * SECOND)
    assert isinstance(refused, Refused)
    assert refused.retry_after_ms == 1, "reapable now, but a retry hint of 0 is a hammer loop"


def test_with_reaping_disabled_the_server_says_it_cannot_say() -> None:
    """D354. `--session-timeout 0` is four lines above the sentence requiring a `retry_after_ms`,
    and under it no number the server could print would be a prediction."""
    registry = _registry(max_sessions=1, timeout_s=TIMEOUT_DISABLED)
    registry.open("sess_a", at_ns=0)
    refused = registry.open("sess_b", at_ns=SECOND)
    assert isinstance(refused, Refused)
    assert refused.retry_after_ms is None


def test_an_empty_registry_has_no_wait_to_report() -> None:
    assert _registry().retry_after_ms(at_ns=0) is None


# ---------------------------------------------------------------------------------------------
# The refusal, which is the same code as the queue's and a different knob
# ---------------------------------------------------------------------------------------------


def test_the_refusal_names_the_session_cap_and_not_the_queue_one() -> None:
    """Both raise `OW-A-022`; `.limit` is what sends an operator to the right number."""
    registry = _registry(max_sessions=1)
    registry.open("sess_a", at_ns=0)
    refused = registry.open("sess_b", at_ns=SECOND)
    assert isinstance(refused, Refused)
    error = overloaded(refused)
    assert isinstance(error, ResourceLimit)
    assert error.limit == KEY_MAX_SESSIONS
    assert error.code() == OVERLOADED
    assert error.numeric() == "OW-A-022"
    assert "retry after 59000 ms" in str(error), "60 s timeout, 1 s idle on the only session"
    assert "DELETE" in error.fix, "a client can free its own slot without an operator"


def test_the_refusal_says_so_when_it_cannot_predict() -> None:
    error = overloaded(Refused(live=64, retry_after_ms=None))
    assert "cannot say" in str(error)
    assert "reaping is disabled" in str(error)


def test_the_refusal_prints_the_wait_when_it_has_one() -> None:
    error = overloaded(Refused(live=64, retry_after_ms=1234))
    assert "1234 ms" in str(error)


# ---------------------------------------------------------------------------------------------
# `--stateless`, which holds no registry at all
# ---------------------------------------------------------------------------------------------


def test_the_stateless_degradation_is_both_literals_from_core() -> None:
    """Neither string is spelled here. 10:2386 makes the `kind` deliberately the nearest legal
    member and the `message` the real cause, and `dedup.py` is the home of both."""
    kind, message = stateless_degradation()
    assert kind == LEDGER_RESET_KIND
    assert message == DEDUP_OFF_MESSAGE
    assert "--stateless" in message
    assert "not deduplicated" in message


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(sessions_module.__file__).read_text(encoding="utf-8"))


def test_the_registry_holds_no_clock_and_no_loop() -> None:
    tree = _module_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"asyncio", "selectors", "time", "threading", "random", "secrets"})
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith)
    ]


def test_the_two_serve_modules_measure_a_duration_the_same_way() -> None:
    """`elapsed_ms` has ONE home now: it was `admission._elapsed_ms` and this module needed the
    same floor-and-clamp, so it was promoted rather than copied. Two spellings of "how long" in
    one distribution is how a `queued_ms` and an `idle_ms` come to disagree about a millisecond."""
    assert elapsed_ms(0, 1_000_000 - 1) == 0
    assert elapsed_ms(5 * SECOND, 0) == 0
    assert "elapsed_ms" not in {
        node.name for node in _module_tree().body if isinstance(node, ast.FunctionDef)
    }


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(sessions_module.__all__)
