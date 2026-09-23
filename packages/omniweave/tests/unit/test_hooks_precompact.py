"""`PreCompact`: the marker, the briefing, and a renderer checked against the plan's own example.

**The load-bearing test here is `test_the_renderer_reproduces_the_plans_example_byte_for_byte`.**
The plan declares no journal record schema (D405), so the only way to know that `KINDS` is the right
shape is to feed it records and see whether 10:1953's eight rendered lines come back out. They do,
exactly -- heading, corpora, cite block, note, gaps and artefacts, character for character. That
turns an invented schema into a derived one, and it turns an edit to the example into a failing test
instead of a second opinion.

Everything else is deterministic: `wall_ns` is an integer argument, `tmp_path` is the only
filesystem, and no test spawns anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks.envelope import EVENTS, Advice, emission, run
from omniweave.hooks.precompact import (
    ARTEFACT,
    BRIEFING,
    BRIEFING_MAX_CHARS,
    CITE,
    COMPACTED,
    CORPUS,
    GAP,
    KIND,
    KINDS,
    SOURCE_LABELS,
    TRIGGER,
    briefing,
    handler,
    render_briefing,
    run_precompact,
    unfrozen,
)
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, append

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conftest import PlanDocs

NOW: int = 1_800_000_000_000_000_000
SESSION: Mapping[str, Any] = {"session_id": "abc-123"}

EXAMPLE_RECORDS: tuple[Mapping[str, Any], ...] = (
    {KIND: CORPUS, "corpus": "handbook", "version": 41, "stale": 0},
    {KIND: CORPUS, "corpus": "contracts", "version": 12, "stale": 2},
    {KIND: CITE, "corpus": "handbook", "ref": "d7#412"},
    {KIND: CITE, "corpus": "handbook", "ref": "d7#418"},
    {KIND: CITE, "corpus": "handbook", "ref": "d31#88"},
    {KIND: CITE, "corpus": "contracts", "ref": "d3#77"},
    {
        KIND: GAP,
        "uri": "2024-appendix.pdf",
        "pages": 4,
        "span": "p.12-15",
        "reason": "OCR deferred",
    },
    {KIND: ARTEFACT, "name": "deck/2025-q1-benefits", "gate": "manual_required", "units": 2},
)


def _store(tmp_path: Path) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    return root


def _marker(root: Path, key: str, name: str) -> Mapping[str, Any]:
    return json.loads((root / f"{key}.{name}").read_text(encoding="utf-8"))


def _key() -> str:
    from omniweave.hooks.envelope import session_key  # noqa: PLC0415

    return session_key(SESSION)


# ---------------------------------------------------------------------------------------------
# The renderer against the plan.
# ---------------------------------------------------------------------------------------------


def test_the_renderer_reproduces_the_plans_example_byte_for_byte(plan: PlanDocs) -> None:
    """D405's answer. The example is the plan's only statement of the journal's record shape.

    Eight lines at 10:1953, rendered from eight records built out of `KINDS`. If this passes, the
    schema is derived rather than invented; if the example is amended, this fails and says so.
    """
    example = _plan_example(plan)

    assert briefing(render_briefing(EXAMPLE_RECORDS), "compact") == example


def _plan_example(plan: PlanDocs) -> str:
    plan.require()
    lines = plan.text("10-interfaces.md").split("\n")
    start = next(
        index for index, line in enumerate(lines) if line.startswith("## omniweave session state")
    )
    #  The example lives in a ```text fence, so the fence is its end and not a blank line: the
    #  heading is followed by one, and it is part of the example.
    end = start
    while end + 1 < len(lines) and not lines[end + 1].startswith("```"):
        end += 1
    return "\n".join(lines[start : end + 1]).rstrip()


def test_the_three_source_labels_are_the_plans_own_three(plan: PlanDocs) -> None:
    plan.require()
    text = plan.text("10-interfaces.md")

    assert set(SOURCE_LABELS) == {"compact", "resume", "fork"}
    for label in SOURCE_LABELS.values():
        assert label in text


def test_a_source_with_no_briefing_emits_nothing_rather_than_an_unlabelled_one() -> None:
    """10:1974: an unrelated session's journal would present stale files as this session's focus."""
    body = render_briefing(EXAMPLE_RECORDS)

    assert briefing(body, "startup") == ""
    assert briefing(body, "clear") == ""
    assert briefing("", "compact") == ""


def test_the_briefing_cap_is_the_cap_of_the_event_that_will_emit_it() -> None:
    """A briefing frozen above the cap is truncated at emission, and truncation takes the tail."""
    assert EVENTS["SessionStart"].cap == BRIEFING_MAX_CHARS


# ---------------------------------------------------------------------------------------------
# The four sections.
# ---------------------------------------------------------------------------------------------


def test_the_latest_record_wins_for_a_corpus_touched_twice() -> None:
    body = render_briefing(
        (
            {KIND: CORPUS, "corpus": "handbook", "version": 40, "stale": 3},
            {KIND: CORPUS, "corpus": "handbook", "version": 41, "stale": 0},
        )
    )

    assert body == "Corpora touched: handbook@41 (fresh)"


def test_one_stale_document_is_singular() -> None:
    body = render_briefing(({KIND: CORPUS, "corpus": "x", "version": 1, "stale": 1},))

    assert "1 document stale" in body
    assert "documents" not in body


def test_cites_are_grouped_by_corpus_deduplicated_and_kept_in_first_seen_order() -> None:
    body = render_briefing(
        (
            {KIND: CITE, "corpus": "handbook", "ref": "d31#88"},
            {KIND: CITE, "corpus": "contracts", "ref": "d3#77"},
            {KIND: CITE, "corpus": "handbook", "ref": "d7#412"},
            {KIND: CITE, "corpus": "handbook", "ref": "d31#88"},
        )
    )

    assert "handbook:d31#88 d7#412 · contracts:d3#77" in body


def test_the_cite_block_carries_the_instruction_not_to_read_the_file() -> None:
    """10:1968: the briefing carries cites, never content, and says what to do with them."""
    body = render_briefing(({KIND: CITE, "corpus": "h", "ref": "d1#1"},))

    assert "do NOT Read the file" in body
    assert "ow_open" in body


def test_a_record_of_an_unknown_kind_is_dropped_rather_than_raised() -> None:
    """D405: the schema is undeclared, so an unheard-of kind is the expected state, not an error."""
    body = render_briefing(
        (
            {KIND: "something_the_server_added_later", "whatever": 1},
            {KIND: CITE, "corpus": "h", "ref": "d1#1"},
        )
    )

    assert "h:d1#1" in body


def test_a_record_with_a_newline_cannot_forge_a_briefing_section() -> None:
    body = render_briefing(
        ({KIND: CORPUS, "corpus": "h\nCites delivered before compaction", "version": 1},)
    )

    assert body.count("\n") == 0


def test_an_empty_journal_renders_an_empty_body() -> None:
    assert render_briefing(()) == ""


def test_a_section_with_no_usable_record_is_absent_rather_than_a_bare_heading() -> None:
    body = render_briefing(
        (
            {KIND: CORPUS, "version": 1},
            {KIND: GAP, "pages": 3},
            {KIND: ARTEFACT, "gate": "x"},
            {KIND: CITE, "corpus": "h", "ref": "d1#1"},
        )
    )

    assert "Corpora touched" not in body
    assert "Open gaps" not in body
    assert "Artefacts in flight" not in body


# ---------------------------------------------------------------------------------------------
# The budget. D408.
# ---------------------------------------------------------------------------------------------


def test_when_the_body_will_not_fit_the_artefacts_go_first_and_the_cites_go_last() -> None:
    """10:1968 puts the value in the cites; the plan states no priority, so this is D408."""
    records: list[Mapping[str, Any]] = [
        {KIND: CORPUS, "corpus": "c" * 60, "version": 1},
        {KIND: CITE, "corpus": "h", "ref": "d1#1"},
        {KIND: GAP, "uri": "g" * 60, "pages": 1},
        {KIND: ARTEFACT, "name": "a" * 60, "gate": "manual"},
    ]
    full = render_briefing(records)

    tightened = render_briefing(records, limit=len(full) - 10)
    assert "Artefacts in flight" not in tightened
    assert "h:d1#1" in tightened

    tighter = render_briefing(records, limit=200)
    assert "Open gaps" not in tighter
    assert "h:d1#1" in tighter

    tightest = render_briefing(records, limit=180)
    assert "Corpora touched" not in tightest
    assert "h:d1#1" in tightest


def test_a_cite_block_that_alone_exceeds_the_limit_is_sliced_and_not_dropped() -> None:
    """The last resort is a slice: an empty briefing tells the agent less than a truncated one."""
    records = [{KIND: CITE, "corpus": "h", "ref": f"d{index}#1"} for index in range(400)]

    body = render_briefing(records, limit=300)

    assert len(body) == 300
    assert body.startswith("Cites delivered")


def test_the_default_limit_is_the_briefing_cap() -> None:
    records = [{KIND: CITE, "corpus": "h", "ref": f"d{index}#1"} for index in range(2_000)]

    assert len(render_briefing(records)) == BRIEFING_MAX_CHARS


# ---------------------------------------------------------------------------------------------
# The handler: two writes, no output.
# ---------------------------------------------------------------------------------------------


def test_the_marker_carries_the_trigger_and_the_moment(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_precompact({**SESSION, TRIGGER: "auto"}, root=root, wall_ns=NOW)

    assert _marker(root, _key(), COMPACTED) == {"at_ns": NOW, "reason": "auto"}
    assert advice.counter


def test_a_payload_with_no_trigger_records_unknown_rather_than_nothing(tmp_path: Path) -> None:
    """10:1942 spells the default: `payload.get("trigger", "unknown")`."""
    root = _store(tmp_path)

    run_precompact(SESSION, root=root, wall_ns=NOW)

    assert _marker(root, _key(), COMPACTED)["reason"] == "unknown"


def test_the_briefing_is_frozen_from_the_journal(tmp_path: Path) -> None:
    root = _store(tmp_path)
    key = _key()
    for index, record in enumerate(EXAMPLE_RECORDS):
        append(root, key, record, at_ns=NOW - 1, seq=index)

    advice = run_precompact(SESSION, root=root, wall_ns=NOW)

    assert advice.counter == "frozen"
    assert "handbook:d7#412" in _marker(root, key, BRIEFING)["body"]


def test_the_marker_is_written_before_the_briefing_and_survives_an_empty_journal(
    tmp_path: Path,
) -> None:
    """The marker is the ledger's correctness condition; the briefing is a convenience."""
    root = _store(tmp_path)

    advice = run_precompact(SESSION, root=root, wall_ns=NOW)

    assert (root / f"{_key()}.{COMPACTED}").is_file()
    assert not (root / f"{_key()}.{BRIEFING}").exists()
    assert advice.counter == "marked-no-briefing"


def test_records_outside_the_window_do_not_reach_the_briefing(tmp_path: Path) -> None:
    """10:1884's 240 minutes, applied by the read this handler makes."""
    root = _store(tmp_path)
    key = _key()
    append(root, key, dict(EXAMPLE_RECORDS[2]), at_ns=NOW - 5 * 3600 * 10**9, seq=0)

    run_precompact(SESSION, root=root, wall_ns=NOW)

    assert not (root / f"{key}.{BRIEFING}").exists()


def test_a_payload_with_no_session_id_writes_nothing(tmp_path: Path) -> None:
    root = _store(tmp_path)

    advice = run_precompact({}, root=root, wall_ns=NOW)

    assert advice.counter == "noop-no-key"
    assert list(root.iterdir()) == []


def test_a_deployment_with_no_sessions_directory_writes_nothing() -> None:
    """D403: no `omniweave.toml`, no `<sessions>`, and the handler is silent rather than broken."""
    assert run_precompact(SESSION, root=None, wall_ns=NOW).counter == "noop-no-key"


def test_an_unwritable_root_is_a_counter_and_never_an_exception(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    assert run_precompact(SESSION, root=blocker / "s", wall_ns=NOW).counter == "noop-no-write"


def test_the_handler_binds_a_root_and_reads_the_clock_when_it_is_called(tmp_path: Path) -> None:
    root = _store(tmp_path)
    readings = iter((NOW, NOW + 5))
    bound = handler(root, lambda: next(readings))

    bound(SESSION)

    assert _marker(root, _key(), COMPACTED)["at_ns"] == NOW


# ---------------------------------------------------------------------------------------------
# Silence. 10:1927.
# ---------------------------------------------------------------------------------------------


def test_precompact_cannot_speak_whatever_the_handler_returns() -> None:
    """10:1926's shipped defect: a briefing emitted here goes into a field hosts discard."""
    assert emission("PreCompact", Advice(text="## omniweave session state")) == ""
    assert EVENTS["PreCompact"].cap == 0


def test_the_handler_under_the_envelope_emits_nothing_and_exits_zero(tmp_path: Path) -> None:
    root = _store(tmp_path)
    key = _key()
    for index, record in enumerate(EXAMPLE_RECORDS):
        append(root, key, record, at_ns=NOW - 1, seq=index)

    outcome = run(
        "PreCompact",
        SESSION,
        handler(root, lambda: NOW),
        clock=_FrozenClock(),
        env={},
    )

    assert outcome.stdout == ""
    assert outcome.exit_code() == 0
    assert outcome.counters == ("ow-hook-precompact-frozen",)
    assert (root / f"{key}.{BRIEFING}").is_file()


class _FrozenClock:
    def monotonic_ns(self) -> int:
        return NOW

    def wall_ns(self) -> int:
        return NOW


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_four_record_kinds_are_the_four_lines_of_the_example() -> None:
    assert set(KINDS) == {CORPUS, CITE, GAP, ARTEFACT}
    assert KINDS[CITE] == ("corpus", "ref")


def test_the_unfrozen_list_names_the_five_readings_this_module_renders_against() -> None:
    stated = unfrozen()

    assert len(stated) == 5
    assert any("D405" in item for item in stated)
    assert any("D407" in item for item in stated)


def test_the_module_reaches_for_no_distribution_but_its_own() -> None:
    """A hook may not pay a loop import, and this one pays no first-party import outside `hooks`."""
    import ast  # noqa: PLC0415

    import omniweave.hooks.precompact as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    modules = [
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
    ]

    assert [name for name in modules if name.startswith("omniweave")] == [
        "omniweave.hooks.envelope",
        "omniweave.hooks.session",
    ]


@pytest.mark.parametrize("source", ["compact", "resume", "fork"])
def test_every_labelled_source_produces_a_heading(source: str) -> None:
    assert briefing("body", source).startswith("## omniweave session state (")
