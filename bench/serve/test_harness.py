"""`bench/serve/serve_harness.py`: the instrument's arithmetic, over transcripts built here.

Every transcript below is synthetic, and that is the point of this file rather than a shortcut: the
rules that turn transcripts into a verdict -- what a re-read is, how an answer is graded, when a run
fails -- must be pinned before any real transcript exists, or the first real run would be graded by
rules chosen after seeing it.

`uv run pytest bench/serve -q` runs these. `--tasks all` (16-roadmap.md:745) additionally asks for a
task run, which FAILS today with its reason: the catalogue is empty (D602) and no scripted agent is
wired. The P7 exit command is meant to fail until W7.7 is done, and it says why.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import serve_harness as h
from omniweave_core.store.indexlock import LockHeader, LockRow, write_lock

HERE = Path(__file__).resolve().parent
ROOT = "c:/corpus"
MSA = f"{ROOT}/contracts/msa.pdf"
NDA = f"{ROOT}/contracts/nda.docx"
INDEXED = frozenset({MSA, NDA})


def _task(
    task_id: str,
    task_class: h.TaskClass = h.TaskClass.RETRIEVAL,
    *,
    source: h.SourceKind = h.SourceKind.BORN_DIGITAL,
    contains: tuple[str, ...] = ("thirty days",),
) -> h.Task:
    return h.Task(
        id=task_id,
        task_class=task_class,
        corpus=h.Corpus.LEGAL_MATTER,
        source_kind=source,
        prompt="What notice does the MSA require?",
        expect=h.Expect(contains=contains),
        injector="stall" if task_class is h.TaskClass.DAMAGED else None,
    )


def _run(task: h.Task, arm: h.Arm, calls: list[h.ToolCall], answer: str) -> h.TaskOutcome:
    return h.outcome(task, h.Transcript(task.id, arm, tuple(calls), answer), INDEXED)


QUERY = h.ToolCall("ow_query", {"query": "notice period"})
OPEN = h.ToolCall("ow_open", {"ref": "d1#4"})
READ_MSA = h.ToolCall("Read", {"file_path": MSA})


# ---------------------------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------------------------


def test_the_shipped_catalogue_parses_and_owes_all_thirty() -> None:
    catalog = h.load_catalog((HERE / "tasks.toml").read_text(encoding="utf-8"))
    assert h.TASKS_TOTAL == 30
    assert catalog.missing() == h.REQUIRED_COUNTS


@pytest.mark.xfail(strict=True, reason="D602: F20's three reference corpora and their 30 tasks")
def test_the_catalogue_holds_the_thirty_tasks_section_8_8_specifies() -> None:
    assert h.load_catalog((HERE / "tasks.toml").read_text(encoding="utf-8")).complete


def test_a_task_run_needs_the_catalogue_and_the_agent(request: pytest.FixtureRequest) -> None:
    """`--tasks` other than `none` is a task run, and a task run cannot happen yet. It fails, and
    names both halves of why, rather than passing over zero tasks."""
    selected = str(request.config.getoption("--tasks"))
    if selected == "none":
        pytest.skip("no --tasks selected")
    catalog = h.load_catalog((HERE / "tasks.toml").read_text(encoding="utf-8"))
    held = len(catalog.tasks)
    pytest.fail(
        f"--tasks {selected}: the catalogue holds {held} of {h.TASKS_TOTAL} tasks (D602) and no "
        f"scripted agent is wired to run one (W7.7b)"
    )


def test_a_catalogue_task_round_trips_and_its_rules_are_refused_by_name() -> None:
    text = """
[catalog]
version = 1
[[task]]
id = "cite-termination"
class = "citation"
corpus = "legal_matter"
source = "scanned"
prompt = "What does section 4.2 say about termination?"
expect = { contains = ["thirty days"], forbids = ["no such section"] }
"""
    (task,) = h.load_catalog(text).tasks
    assert (task.task_class, task.source_kind, task.injector) == (
        h.TaskClass.CITATION,
        h.SourceKind.SCANNED,
        None,
    )
    with pytest.raises(h.CatalogError, match="unknown keys"):
        h.load_catalog(text + 'colour = "red"\n')
    with pytest.raises(h.CatalogError, match="appears twice"):
        h.load_catalog(text + text.split("[catalog]\nversion = 1\n", 1)[1])
    with pytest.raises(h.CatalogError, match="injector is required"):
        h.load_catalog(text.replace('"citation"', '"damaged"'))
    with pytest.raises(h.CatalogError, match="injector is required"):
        h.load_catalog(text + 'injector = "stall"\n')


def test_a_class_over_its_size_is_refused_because_the_sizes_are_the_design() -> None:
    nine = tuple(_task(f"t{i}", h.TaskClass.CITATION) for i in range(9))
    with pytest.raises(h.CatalogError, match="9 citation tasks"):
        h.Catalog(tasks=nine)
    assert h.TaskClass.CITATION not in h.Catalog(tasks=nine[:8]).missing()


def test_an_answer_is_graded_by_substrings_casefolded_and_an_empty_key_is_refused() -> None:
    expect = h.Expect(contains=("Thirty Days",), forbids=("I could not find",))
    assert expect.grades("Notice is thirty days in writing.")
    assert not expect.grades("Notice is sixty days.")
    assert not expect.grades("Thirty days -- though I could not find the clause.")
    with pytest.raises(h.CatalogError, match="nothing can fail"):
        h.Expect()


# ---------------------------------------------------------------------------------------------
# what a re-read is (D601)
# ---------------------------------------------------------------------------------------------


def test_the_indexed_set_is_the_receipt_ow_ingest_writes() -> None:
    """The harness is stdlib-only and reads the receipt as text; this writes one with the
    framework's own `write_lock`, so the two cannot drift apart unnoticed."""
    rows = [
        LockRow(bytes(16), 1, "ok", 3, 0, bytes(16), "contracts/msa.pdf"),
        LockRow(bytes([1] * 16), 1, "ok", 5, 0, bytes(16), "contracts/nda.docx"),
    ]
    text = write_lock(LockHeader(scorer=1, segmenter="none", space="none"), rows)
    assert h.indexed_sources(text, "C:\\corpus") == INDEXED


@pytest.mark.parametrize(
    ("call", "reads"),
    [
        (h.ToolCall("Read", {"file_path": MSA}), True),
        (h.ToolCall("Read", {"file_path": "C:\\corpus\\contracts\\msa.pdf"}), True),
        (h.ToolCall("Read", {"file_path": f"{ROOT}/notes.txt"}), False),
        (h.ToolCall("Grep", {"pattern": "notice", "path": f"{ROOT}/contracts"}), True),
        (h.ToolCall("Grep", {"pattern": "notice", "path": f"{ROOT}/other"}), False),
        (h.ToolCall("Bash", {"command": f"cat {MSA}"}), True),
        (h.ToolCall("Bash", {"command": f"head -n 40 '{NDA}'"}), True),
        (h.ToolCall("Bash", {"command": f"ls {ROOT}/contracts"}), False),
        (h.ToolCall("ow_open", {"ref": MSA}), False),
    ],
)
def test_a_read_is_a_host_tool_over_an_indexed_file(call: h.ToolCall, reads: bool) -> None:
    """13:1373's `Read`, `Grep` and shell read, and nothing else: `ls` lists, `ow_open` is ours,
    and a file the receipt does not list is not a source omniweave could have answered from."""
    assert h.reads_source(call, INDEXED) is reads


def test_a_read_counts_only_after_the_first_omniweave_call() -> None:
    task = _task("q1")
    before = _run(task, h.Arm.OMNIWEAVE, [READ_MSA, QUERY], "thirty days")
    after = _run(task, h.Arm.OMNIWEAVE, [QUERY, READ_MSA], "thirty days")
    assert (before.reread, after.reread) == (False, True)


def test_the_control_arm_rereads_by_construction_under_the_same_rule() -> None:
    """D601: a task with no omniweave call rereads iff it reads a source at all -- so the control
    arm is 1.0 exactly when its agent must read to answer, 13:1392's "by construction"."""
    tasks = [_task(f"c{i}") for i in range(3)]
    outcomes = [_run(t, h.Arm.CONTROL, [READ_MSA], "thirty days") for t in tasks]
    assert h.report(h.Arm.CONTROL, outcomes).total.source_reread_rate == h.Rate(3, 3)


def test_a_mis_pick_is_the_wrong_first_tool_for_the_task_class() -> None:
    """F19: `ow_open` is the right first pick for a citation-shaped lookup, `ow_query` for the
    rest. A task that never called either has no pick to be wrong about."""
    citation = _task("c", h.TaskClass.CITATION)
    assert _run(citation, h.Arm.OMNIWEAVE, [QUERY], "thirty days").mis_pick is True
    assert _run(citation, h.Arm.OMNIWEAVE, [OPEN], "thirty days").mis_pick is False
    assert _run(_task("r"), h.Arm.OMNIWEAVE, [OPEN, QUERY], "thirty days").mis_pick is True
    assert _run(_task("n"), h.Arm.OMNIWEAVE, [READ_MSA], "thirty days").mis_pick is None


# ---------------------------------------------------------------------------------------------
# the numbers
# ---------------------------------------------------------------------------------------------


def test_wilson_is_the_score_interval_and_not_the_normal_approximation() -> None:
    """13:401. At 10 of 10 the normal interval collapses to [1, 1]; Wilson's does not."""
    lo, hi = h.wilson(10, 10)
    assert hi == pytest.approx(1.0) and 0.72 < lo < 0.73
    lo, hi = h.wilson(0, 10)
    assert lo == 0.0 and 0.27 < hi < 0.28
    assert h.wilson(0, 0) == (0.0, 1.0)


def test_every_line_that_shows_the_reread_rate_shows_accuracy_beside_it() -> None:
    """Q-G21 as a type: `Paired` is the only carrier of either number, and it renders both."""
    outcomes = [
        _run(_task("a"), h.Arm.OMNIWEAVE, [QUERY], "thirty days"),
        _run(_task("b", source=h.SourceKind.SCANNED), h.Arm.OMNIWEAVE, [QUERY, READ_MSA], "no"),
    ]
    lines = [line for line in h.report(h.Arm.OMNIWEAVE, outcomes).lines() if "reread" in line]
    assert lines and all("task_accuracy" in line for line in lines)


def test_the_report_is_sliced_so_a_scanned_reread_is_never_pooled_away() -> None:
    """13:1399-1401: a scanned source is where an agent SHOULD re-read. Pooled, one scanned
    re-read in two tasks reads 0.5; sliced, it is 1 of 1 scanned and 0 of 1 born-digital."""
    outcomes = [
        _run(_task("a"), h.Arm.OMNIWEAVE, [QUERY], "thirty days"),
        _run(
            _task("b", source=h.SourceKind.SCANNED),
            h.Arm.OMNIWEAVE,
            [QUERY, READ_MSA],
            "thirty days",
        ),
    ]
    arm = h.report(h.Arm.OMNIWEAVE, outcomes)
    assert arm.total.source_reread_rate == h.Rate(1, 2)
    assert arm.by_source[h.SourceKind.SCANNED].source_reread_rate == h.Rate(1, 1)
    assert arm.by_source[h.SourceKind.BORN_DIGITAL].source_reread_rate == h.Rate(0, 1)
    with pytest.raises(h.CatalogError, match="not from the control arm"):
        h.report(h.Arm.CONTROL, outcomes)


def test_mcnemar_is_exact_and_one_sided() -> None:
    """Only discordant pairs count. Five tasks omniweave lost and control won, none the other way,
    is p = 1/32 -- not significant at 0.01; seven is 1/128, which is."""
    assert h.mcnemar_worse([False] * 5, [True] * 5) == pytest.approx(1 / 32)
    assert h.mcnemar_worse([False] * 7, [True] * 7) == pytest.approx(1 / 128)
    assert h.mcnemar_worse([True, False], [True, False]) == 1.0
    assert h.mcnemar_worse([True] * 7, [False] * 7) == 1.0, "better is never worse"


def _arms(omni_correct: list[bool], control_correct: list[bool]) -> tuple[list, list]:
    tasks = [_task(f"t{i}") for i in range(len(omni_correct))]
    omni = [
        _run(t, h.Arm.OMNIWEAVE, [QUERY], "thirty days" if ok else "sixty days")
        for t, ok in zip(tasks, omni_correct, strict=True)
    ]
    control = [
        _run(t, h.Arm.CONTROL, [READ_MSA], "thirty days" if ok else "sixty days")
        for t, ok in zip(tasks, control_correct, strict=True)
    ]
    return omni, control


def test_the_control_guard_fails_an_arm_significantly_less_accurate_than_control() -> None:
    omni, control = _arms([False] * 7 + [True] * 3, [True] * 10)
    guard = h.ControlGuard.judge(omni, control)
    assert not guard.ok
    assert "below control" in guard.lines()[-1]
    omni, control = _arms([False] * 2 + [True] * 8, [True] * 10)
    assert h.ControlGuard.judge(omni, control).ok


def test_a_reread_rate_bought_with_wrong_answers_fails_the_run() -> None:
    """13:1382, verbatim in effect: `source_reread_rate` falls and `task_accuracy` falls with it --
    the agent was talked out of checking and was wrong more for it. Failing, though the paired
    test against control passes."""
    tasks = [_task(f"t{i}") for i in range(4)]
    before = h.report(
        h.Arm.OMNIWEAVE,
        [_run(t, h.Arm.OMNIWEAVE, [QUERY, READ_MSA], "thirty days") for t in tasks],
    )
    omni = [
        _run(t, h.Arm.OMNIWEAVE, [QUERY], "thirty days" if i else "sixty days")
        for i, t in enumerate(tasks)
    ]
    control = [_run(t, h.Arm.CONTROL, [READ_MSA], "thirty days") for t in tasks]
    gamed = h.ControlGuard.judge(omni, control, previous=before)
    assert gamed.p_worse >= h.ALPHA, "the paired test alone would pass this run"
    assert gamed.gamed and not gamed.ok
    honest = [_run(t, h.Arm.OMNIWEAVE, [QUERY], "thirty days") for t in tasks]
    assert h.ControlGuard.judge(honest, control, previous=before).ok, (
        "fewer re-reads, same accuracy"
    )


def test_the_arms_must_hold_the_same_tasks() -> None:
    omni, control = _arms([True, True], [True, True])
    with pytest.raises(h.CatalogError, match="different tasks"):
        h.ControlGuard.judge(omni, control[:1])
