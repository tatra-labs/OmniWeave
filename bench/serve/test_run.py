"""`run.py`: select, hold back, run both arms, grade, report (ADR-14 D14.7), with no subprocess."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import agent_config as ac
import anyio
import corpora
import pytest
import run
import serve_harness as h
from agent import LoopSettings, ToolServer
from corpora import Prepared, generator, key_of
from models import ModelRequest, ToolResult, ToolSpec, ToolUse, Turn
from omniweave_conform.damage import INJECTORS

HERE = Path(__file__).resolve().parent
CATALOG = h.load_catalog((HERE / "tasks.toml").read_text(encoding="utf-8"))
gen = generator()
SETTINGS = LoopSettings("scripted", 0.0, 256, 12)


def test_select_takes_all_ids_classes_and_corpora_and_refuses_an_unknown_word() -> None:
    assert len(run.select(CATALOG, "all")) == 24
    assert {t.task_class for t in run.select(CATALOG, "citation")} == {h.TaskClass.CITATION}
    mixed = run.select(CATALOG, "home-ret-dental, data_room")
    assert {t.id for t in mixed} == {"home-ret-dental"} | {
        t.id for t in CATALOG.tasks if t.corpus is h.Corpus.DATA_ROOM
    }
    with pytest.raises(ac.BenchConfigError) as caught:
        run.select(CATALOG, "citations")
    assert "citation" in str(caught.value)
    assert "--list" in str(caught.value)


def test_a_damaged_task_is_held_back_only_while_its_injector_is_not_built() -> None:
    """D640, D641 and D643: `mask_format`, `chaos` and `encrypt` are built, so all six damaged
    tasks run. The rule is unchanged: a task whose Injector is not built is held back, naming
    it and what is built."""
    runnable, held = run.partition(CATALOG.tasks)
    assert held == ()
    assert len(runnable) == len(CATALOG.tasks)
    assert {"legal-dmg-service-credit", "data-dmg-materiality"} <= {t.id for t in runnable}
    task = next(t for t in CATALOG.tasks if t.id == "data-dmg-materiality")
    runnable, held = run.partition((dataclasses.replace(task, injector="stall"),))
    (one,) = held
    assert runnable == ()
    assert one.task_id == "data-dmg-materiality"
    assert "stall Injector" in one.reason
    assert all(name in one.reason for name in INJECTORS)


def test_a_damaged_task_runs_over_its_own_corpus_with_its_answer_s_file_damaged() -> None:
    task = next(t for t in CATALOG.tasks if t.id == "home-dmg-refund")
    assert run.corpus_key(task) == "personal_archive+mask_format:tax/tax-summary-2023.docx"
    plain = next(t for t in CATALOG.tasks if t.id == "home-cite-rent-increase")
    assert run.corpus_key(plain) == "personal_archive"


# -- a whole run, in process ---------------------------------------------------------------


def _prepared(tmp_path: Path, corpus: str, damage: tuple[tuple[str, str], ...] = ()) -> Prepared:
    base = tmp_path / key_of(corpus, damage).replace(":", "_").replace("/", "_")
    project = base / "project"
    gen.write_corpus(project / "docs", corpus, "quick")
    for path, name in damage:
        target = project / "docs" / path
        target.write_bytes(INJECTORS[name].transform(target.read_bytes()))
    receipt = "".join(
        f"0  1  ok  1  0  0  docs/{doc.path}\n" for doc in gen.documents(corpus, "quick")
    )
    (project / "omniweave.index.lock").write_text(receipt, encoding="utf-8")
    return Prepared(
        corpus, "quick", "0" * 64, base, cached=True, add_seconds=None, env={}, damage=damage
    )


class Oracle:
    """A model that reads the planted document and answers from the planted sentence."""

    def __init__(self) -> None:
        self.by_prompt = {task.prompt: task for task in CATALOG.tasks}

    def __call__(self, request: ModelRequest) -> Turn:
        prompt = request.messages[0].text  # type: ignore[union-attr]
        task = self.by_prompt[prompt]
        results = [m for m in request.messages if isinstance(m, ToolResult)]
        if task.id in gen.ABSENT:
            if not results:
                return Turn("", (ToolUse("g", "Grep", {"pattern": "zzz-nothing"}),))
            return Turn("NOT FOUND: I searched every document.")
        planted = gen.PLANTED[task.id]
        if not results:
            return Turn("", (ToolUse("r", "Read", {"file_path": planted.path}),))
        if task.injector is not None:
            return Turn(f"NOT FOUND: {planted.path} cannot be read.")
        return Turn(f"{planted.text} ({planted.path})")


class FakeServer:
    instructions: str | None = "Use ow_query."

    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("ow_query", "ask", {"type": "object"}),)

    async def call(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        del name, arguments
        return "no evidence", False


@asynccontextmanager
async def fake_server(_prepared: Prepared) -> AsyncIterator[ToolServer]:
    yield FakeServer()


def test_every_task_runs_on_both_arms_is_graded_and_the_guard_holds(tmp_path: Path) -> None:
    runnable, held = run.partition(run.select(CATALOG, "personal_archive"))
    prepared = {
        run.corpus_key(task): _prepared(
            tmp_path, task.corpus.value, corpora.damage_of(task.id, task.injector)
        )
        for task in runnable
    }
    assert len(prepared) == 3
    lines: list[str] = []
    graded, failures = anyio.run(
        lambda: run.run_all(
            runnable,
            [h.Arm.OMNIWEAVE, h.Arm.CONTROL],
            prepared,
            turn=Oracle(),
            settings=SETTINGS,
            workers=3,
            server_factory=fake_server,
            log=lines.append,
        )
    )
    assert failures == []
    assert len(graded) == 2 * len(runnable) == 16
    assert all(g.outcome.correct for g in graded), [
        g.task.id for g in graded if not g.outcome.correct
    ]
    #  The oracle reads the source after no omniweave call: D601's rule makes that a re-read.
    #  A damaged file cannot be read, so reading it is no re-read of an indexed source.
    present = [g for g in graded if g.task.id in gen.PLANTED and g.task.injector is None]
    assert all(g.outcome.reread for g in present)
    config = ac.resolve(env={"OW_BENCH_SCALE": "quick"})
    report_lines, passed, result = run.summarize(config, graded, failures, held, CATALOG.missing())
    assert passed is True
    assert any(line.startswith("control guard") and " ok " in line for line in report_lines)
    assert not any(line.startswith("UNMEASURED") for line in report_lines)
    assert any(line.startswith("OWED") for line in report_lines)
    assert any(line.startswith("WATERMARK") for line in report_lines)
    assert result["control_guard"]["ok"] is True
    assert {o["task"] for o in result["outcomes"]} == {t.id for t in runnable}
    assert sum(1 for line in lines if line.startswith("  task")) == 16


def test_a_task_that_fails_is_recorded_and_fails_the_run_without_stopping_the_rest(
    tmp_path: Path,
) -> None:
    runnable, _ = run.partition(run.select(CATALOG, "home-ret-dental,home-cite-flood"))
    prepared = {"personal_archive": _prepared(tmp_path, "personal_archive")}
    oracle = Oracle()

    def flaky(request: ModelRequest) -> Turn:
        if "Brightline" in request.messages[0].text:  # type: ignore[union-attr]
            raise run.CassetteMissError("OW-Q-004 cassette miss for agent key x")
        return oracle(request)

    graded, failures = anyio.run(
        lambda: run.run_all(
            runnable, [h.Arm.CONTROL], prepared, turn=flaky, settings=SETTINGS, workers=2
        )
    )
    assert [f.task_id for f in failures] == ["home-ret-dental"]
    assert [g.task.id for g in graded] == ["home-cite-flood"]
    config = ac.resolve(env={"OW_BENCH_ARMS": "control"})
    lines, passed, _ = run.summarize(config, graded, failures, (), {})
    assert passed is False
    assert any("FAILED      control:home-ret-dental: OW-Q-004" in line for line in lines)


# -- main(): the refusals that happen before anything is built ------------------------------


def _main(*argv: str) -> tuple[int, list[str]]:
    out: list[str] = []
    return run.main(list(argv), out=out.append), out


def test_list_prints_the_selection_and_marks_nothing_held_back_once_its_injector_is_built() -> None:
    """`legal-dmg-service-credit` was UNMEASURED until `encrypt` landed (D643)."""
    code, out = _main("--list", "--tasks", "legal-dmg-service-credit,home-ret-dental")
    assert code == 0
    assert any("home-ret-dental" in line and "UNMEASURED" not in line for line in out)
    assert any("legal-dmg-service-credit" in line and "UNMEASURED" not in line for line in out)
    assert any("(flag)" in line for line in out)


def test_the_default_replay_with_no_recordings_stops_at_once_and_says_how_to_record(
    tmp_path: Path,
) -> None:
    code, out = _main("--cassettes", str(tmp_path / "none"), "--cache", str(tmp_path / "cache"))
    assert code == 2
    assert "--record --provider openai --base-url http://localhost:11434/v1" in out[-1]
    assert not (tmp_path / "cache").exists(), "nothing is generated or ingested before it stops"


def test_recording_with_anthropic_and_no_key_is_refused_naming_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out = _main("--record", "--cache", str(tmp_path / "cache"))
    assert code == 2
    assert "ANTHROPIC_API_KEY" in out[-1]
    assert "provider = openai" in out[-1]


def test_an_unusable_knob_or_task_word_is_exit_2_naming_it() -> None:
    assert _main("--tasks", "citations")[0] == 2
    code, out = _main("--tool-budget", "0", "--list")
    assert code == 2
    assert "tool_budget" in out[-1]
