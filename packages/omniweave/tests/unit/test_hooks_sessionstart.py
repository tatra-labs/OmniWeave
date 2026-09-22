"""`SessionStart`: the source gate, the cite re-verification, the fallback and the sweep.

**The assertions that matter here are about what is NOT emitted.** 10:1970 makes every cite
re-verified before emission, so the interesting cases are a cite the store has retired, a store that
cannot be reached at all, and a frozen briefing whose cites cannot be checked because it is text
(D409). In all three the briefing still goes out and says what is missing from it -- a silent
omission would be indistinguishable from a quiet session.

No store is opened. `Verify` is a callable this suite supplies, which is the same seam the module
exists to keep open (D410): importing `omniweave_core.store` costs a hook 104 ms of its 400 ms.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks.envelope import EVENTS, run, session_key
from omniweave.hooks.precompact import BRIEFING, COMPACTED, SOURCE_LABELS, strip_cites
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, append, write_marker
from omniweave.hooks.sessionstart import (
    SILENT_SOURCES,
    SOURCE,
    handler,
    retired_note,
    run_sessionstart,
    unverifiable,
    verified,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

SESSION: Mapping[str, Any] = {"session_id": "abc-123"}
KEY: str = session_key(SESSION)

RECORDS: tuple[Mapping[str, Any], ...] = (
    {"kind": "corpus", "corpus": "handbook", "version": 41, "stale": 0},
    {"kind": "cite", "corpus": "handbook", "ref": "d7#412"},
    {"kind": "cite", "corpus": "handbook", "ref": "d7#418"},
    {"kind": "cite", "corpus": "contracts", "ref": "d3#77"},
)


def _now() -> int:
    """Real wall-clock nanoseconds, because the sweep compares against filesystem mtimes.

    D412: the sweep selects by mtime and the read selects by a record's `at_ns`. A fabricated
    `wall_ns` in the future makes every file on disk look older than 24 hours, so a test that froze
    the clock here would be testing the sweep's ability to delete its own fixtures.
    """
    return time.time_ns()


def _store(tmp_path: Path, *, records: Sequence[Mapping[str, Any]] = RECORDS) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    for index, record in enumerate(records):
        append(root, KEY, record, at_ns=_now() - 1, seq=index)
    return root


def _all_live(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:
    return frozenset(pairs)


def _none_live(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:  # noqa: ARG001
    return frozenset()


def _retires(ref: str):
    def verify(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:
        return frozenset(pair for pair in pairs if pair[1] != ref)

    return verify


# ---------------------------------------------------------------------------------------------
# The source gate. 10:1954 and 10:1974.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["compact", "resume", "fork"])
def test_each_speaking_source_emits_its_own_label(tmp_path: Path, source: str) -> None:
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: source}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.text.startswith(f"## omniweave session state ({SOURCE_LABELS[source]})")


@pytest.mark.parametrize("source", ["startup", "clear"])
def test_startup_and_clear_say_nothing(tmp_path: Path, source: str) -> None:
    """10:1974: an unrelated session's journal would present stale files as this session's focus."""
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: source}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.text == ""
    assert advice.counter == "noop-source"


def test_the_two_silent_sources_are_the_plans_two() -> None:
    assert SILENT_SOURCES == ("startup", "clear")
    assert not set(SILENT_SOURCES) & set(SOURCE_LABELS)


def test_an_unknown_source_is_silent_rather_than_unlabelled(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: "something_new"}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.text == ""


def test_a_payload_with_no_session_id_emits_nothing(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_sessionstart({SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live)

    assert advice.counter == "noop-no-key"


def test_a_deployment_with_no_sessions_directory_emits_nothing() -> None:
    """D403 again: no `omniweave.toml`, no `<sessions>`, and the hook is silent not broken."""
    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=None, wall_ns=_now(), verify=_all_live
    )

    assert advice.counter == "noop-no-key"


# ---------------------------------------------------------------------------------------------
# Re-verification. 10:1970.
# ---------------------------------------------------------------------------------------------


def test_a_retired_cite_is_dropped_and_the_briefing_says_how_many(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_retires("d7#418")
    )

    assert "d7#418" not in advice.text
    assert "d7#412" in advice.text
    assert "1 cite delivered earlier has been retired" in advice.text


def test_two_retired_cites_are_reported_in_the_plural(tmp_path: Path) -> None:
    root = _store(tmp_path)

    def verify(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:
        return frozenset(pair for pair in pairs if pair[1] == "d7#412")

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=verify
    )

    assert "2 cites delivered earlier have been retired" in advice.text


def test_nothing_retired_adds_no_note(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert "retired" not in advice.text
    assert "withheld" not in advice.text


def test_no_verifier_withholds_every_cite_and_says_so_differently(tmp_path: Path) -> None:
    """`verify=None` is a deployment with no reachable store, and 10:1970 is unconditional."""
    root = _store(tmp_path)

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=None
    )

    assert "d7#412" not in advice.text
    assert "the store could not be read" in advice.text
    assert "retired" not in advice.text
    assert "Corpora touched" in advice.text


def test_a_verifier_that_raises_is_a_verifier_that_verified_nothing(tmp_path: Path) -> None:
    """10:1842: a failure here must cost the cites, never the whole briefing."""
    root = _store(tmp_path)

    def explodes(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:  # noqa: ARG001
        raise RuntimeError("the store went away")

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=explodes
    )

    assert "Corpora touched" in advice.text
    assert "d7#412" not in advice.text


def test_verified_passes_non_cite_records_through_untouched() -> None:
    kept, dropped = verified(RECORDS, _none_live)

    assert dropped == 3
    assert [record["kind"] for record in kept] == ["corpus"]


def test_verified_with_no_cites_calls_nothing_and_drops_nothing() -> None:
    def never(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:  # noqa: ARG001
        raise AssertionError("a verifier must not be called when there is nothing to verify")

    kept, dropped = verified(({"kind": "corpus", "corpus": "h"},), never)

    assert dropped == 0
    assert len(kept) == 1


def test_the_note_distinguishes_a_store_that_answered_from_one_that_was_never_reached() -> None:
    """An agent reading `retired` when the truth is `withheld` concludes a corpus changed."""
    assert "retired" in retired_note(1, had_store=True)
    assert "could not be read" in retired_note(1, had_store=False)
    assert retired_note(0, had_store=True) == ""


def test_the_note_fits_inside_the_cap_rather_than_pushing_the_body_past_it(
    tmp_path: Path,
) -> None:
    """The cap is on the field, so a note appended after a full render would be truncated away."""
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    now = _now()
    for index in range(1_500):
        append(
            root,
            KEY,
            {"kind": "cite", "corpus": "handbook", "ref": f"d{index}#1"},
            at_ns=now - 1,
            seq=index,
        )

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=now, verify=_retires("d7#1")
    )
    body = advice.text.split("\n\n", 1)[1]

    assert len(body) <= EVENTS["SessionStart"].cap
    assert "has been retired" in body


# ---------------------------------------------------------------------------------------------
# The frozen fallback. D409.
# ---------------------------------------------------------------------------------------------


def test_a_frozen_briefing_is_emitted_without_its_cites_because_text_cannot_be_verified(
    tmp_path: Path,
) -> None:
    """D409: 10:1943 freezes rendered text and 10:1970 needs records to check against a store."""
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    frozen = (
        "Corpora touched: handbook@41 (fresh)\n"
        "Cites delivered before compaction, still resolvable and still exact:\n"
        "  handbook:d7#412 d31#88\n"
        "  These are NOT in your context any more. Resolve one with ow_open, "
        "do NOT Read the file."
    )
    write_marker(root, KEY, BRIEFING, {"body": frozen})

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.counter == "briefing-unverified"
    assert "Corpora touched: handbook@41 (fresh)" in advice.text
    assert "d7#412" not in advice.text
    assert "the store could not be read" in advice.text


def test_the_journal_is_preferred_over_the_freeze_when_it_has_records(tmp_path: Path) -> None:
    root = _store(tmp_path)
    write_marker(root, KEY, BRIEFING, {"body": "Corpora touched: stale@1 (fresh)"})

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.counter == "briefing"
    assert "stale@1" not in advice.text


def test_no_journal_and_no_freeze_emits_nothing(tmp_path: Path) -> None:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live
    )

    assert advice.text == ""
    assert advice.counter == "noop-empty"


def test_a_corrupt_freeze_is_empty_rather_than_an_exception(tmp_path: Path) -> None:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    (root / f"{KEY}.{BRIEFING}").write_text("{not json", encoding="utf-8")

    assert (
        run_sessionstart(
            {**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live
        ).text
        == ""
    )


def test_strip_cites_removes_exactly_the_three_lines_of_the_block() -> None:
    body = (
        "Corpora touched: handbook@41 (fresh)\n"
        "Cites delivered before compaction, still resolvable and still exact:\n"
        "  handbook:d7#412\n"
        "  These are NOT in your context any more. Resolve one with ow_open, "
        "do NOT Read the file.\n"
        "Artefacts in flight: deck/x (gate: manual)"
    )

    assert strip_cites(body) == (
        "Corpora touched: handbook@41 (fresh)\nArtefacts in flight: deck/x (gate: manual)"
    )


def test_strip_cites_does_not_split_on_a_line_separator_inside_a_corpus_name() -> None:
    """`splitlines()` breaks on U+2028 and would shift every line after it by one."""
    #  Spelled with `chr` because RUF001 refuses an ambiguous LINE SEPARATOR in a literal,
    #  and the character is the whole point of the test.
    body = f"Corpora touched: a{chr(0x2028)}b (fresh)\nArtefacts in flight: deck/x"

    assert strip_cites(body) == body


# ---------------------------------------------------------------------------------------------
# The sweep. 10:1918, and the order D412 is about.
# ---------------------------------------------------------------------------------------------


def test_the_sweep_runs_after_the_briefing_and_never_before_it(tmp_path: Path) -> None:
    """D412: the sweep selects by mtime and the read by `at_ns`. Sweeping first eats the input."""
    root = _store(tmp_path)
    ahead = _now() + 48 * 3600 * 10**9  # every file on disk is now "older than 24 h"

    advice = run_sessionstart(
        {**SESSION, SOURCE: "compact"}, root=root, wall_ns=ahead, verify=_all_live
    )

    assert not list(root.iterdir())  # the sweep did run
    assert advice.counter == "noop-empty"  # and the read, which ran first, saw a stale journal


def test_the_sweep_runs_even_for_a_source_that_says_nothing(tmp_path: Path) -> None:
    """*"A host that crashes never fires `SessionEnd`."* `startup` is the commonest session."""
    root = _store(tmp_path)
    stale = root / "someone-else.jsonl"
    stale.write_text("{}\n", encoding="utf-8")
    import os  # noqa: PLC0415

    old = time.time() - 40 * 3600
    os.utime(stale, (old, old))

    run_sessionstart({**SESSION, SOURCE: "startup"}, root=root, wall_ns=_now(), verify=_all_live)

    assert not stale.exists()


def test_the_sweep_can_be_turned_off_for_a_caller_that_does_its_own(tmp_path: Path) -> None:
    """`ow serve` sweeps at start-up too (10:1918), so the two must not be forced to both run."""
    root = _store(tmp_path)
    stale = root / "someone-else.jsonl"
    stale.write_text("{}\n", encoding="utf-8")
    import os  # noqa: PLC0415

    old = time.time() - 40 * 3600
    os.utime(stale, (old, old))

    run_sessionstart(
        {**SESSION, SOURCE: "startup"}, root=root, wall_ns=_now(), verify=_all_live, swept=False
    )

    assert stale.exists()


# ---------------------------------------------------------------------------------------------
# Under the envelope.
# ---------------------------------------------------------------------------------------------


def test_the_handler_emits_through_the_channel_and_exits_zero(tmp_path: Path) -> None:
    root = _store(tmp_path)
    now = _now()

    outcome = run(
        "SessionStart",
        {**SESSION, SOURCE: "compact"},
        handler(root, lambda: now, verify=_all_live),
        clock=_Clock(now),
        env={},
    )
    body = json.loads(outcome.stdout)["hookSpecificOutput"]

    assert outcome.exit_code() == 0
    assert body["hookEventName"] == "SessionStart"
    assert body["additionalContext"].startswith("## omniweave session state")
    assert outcome.counters == ("ow-hook-start-briefing",)


def test_the_kill_switch_stops_the_briefing_before_the_store_is_ever_asked(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    now = _now()

    def never(pairs: Sequence[tuple[str, str]]) -> AbstractSet[tuple[str, str]]:  # noqa: ARG001
        raise AssertionError("a killed hook must not reach the store")

    outcome = run(
        "SessionStart",
        {**SESSION, SOURCE: "compact"},
        handler(root, lambda: now, verify=never),
        clock=_Clock(now),
        env={"OMNIWEAVE_HOOK": "0"},
    )

    assert outcome.stdout == ""


class _Clock:
    def __init__(self, now: int) -> None:
        self._now = now

    def monotonic_ns(self) -> int:
        return self._now

    def wall_ns(self) -> int:
        return self._now


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_imports_no_store_and_no_config() -> None:
    """D410: importing `omniweave_core.store` puts a warm process at 207 ms of a 400 ms budget."""
    import ast  # noqa: PLC0415

    import omniweave.hooks.sessionstart as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not [name for name in names if name.startswith("omniweave_core")]
    assert {name for name in names if name.startswith("omniweave")} == {
        "omniweave.hooks.envelope",
        "omniweave.hooks.precompact",
        "omniweave.hooks.session",
    }


def test_the_unverifiable_list_names_the_four_readings_this_module_emits_against() -> None:
    stated = unverifiable()

    assert len(stated) == 4
    assert any("D409" in item for item in stated)
    assert any("D410" in item for item in stated)


def test_the_compacted_marker_is_not_this_handlers_to_write(tmp_path: Path) -> None:
    """The marker is `PreCompact`'s; a `SessionStart` that wrote one would reset a live ledger."""
    root = _store(tmp_path)

    run_sessionstart({**SESSION, SOURCE: "compact"}, root=root, wall_ns=_now(), verify=_all_live)

    assert not (root / f"{KEY}.{COMPACTED}").exists()
