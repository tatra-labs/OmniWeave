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
from agent_cassette import USAGE_HEADER
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
    graded, failures, _owed = anyio.run(
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

    graded, failures, _owed = anyio.run(
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


def test_prepare_only_needs_no_recording_and_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D650: `--prepare-only` builds the corpora and calls no model, so neither the replay's
    recordings nor a provider's key may stop it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    built: list[str] = []
    monkeypatch.setattr(
        run, "prepare", lambda corpus, scale, **_kw: built.append(f"{corpus}/{scale}") or None
    )
    code, out = _main(
        "--prepare-only", "--tasks", "home-ret-dental", "--cassettes", str(tmp_path / "none")
    )
    assert code == 0, out
    assert built == ["personal_archive/full"]


def test_a_declared_owed_recording_is_held_and_does_not_fail_the_run(tmp_path: Path) -> None:
    """D1029. `home-cite-flood` is one of the four `OWED_RECORDINGS` rows.

    What this replaces: four red FAILED lines every night for a gap CHANGELOG.md's known
    limitations already declare. A declared gap spelled as a break teaches a reader to read the
    nightly's colour as noise, which is the one thing a nightly cannot afford.
    """
    assert "home-cite-flood" in run.owed_for("anthropic/claude-sonnet-5")
    runnable, _ = run.partition(run.select(CATALOG, "home-cite-flood"))
    prepared = {"personal_archive": _prepared(tmp_path, "personal_archive")}

    def always_missing(_request: ModelRequest) -> Turn:
        raise run.CassetteMissError("OW-Q-004 cassette miss for agent key x")

    lines: list[str] = []
    graded, failures, owed = anyio.run(
        lambda: run.run_all(
            runnable,
            [h.Arm.CONTROL],
            prepared,
            turn=always_missing,
            settings=SETTINGS,
            workers=1,
            model_key="anthropic/claude-sonnet-5",
            log=lines.append,
        )
    )

    assert failures == [], "a declared gap is not a failure"
    assert graded == []
    assert [u.task_id for u in owed] == ["home-cite-flood"]
    assert "recordings were orphaned" in owed[0].reason
    assert any(line.lstrip().startswith("OWED") for line in lines), lines
    config = ac.resolve(env={"OW_BENCH_ARMS": "control"})
    report_lines, passed, result = run.summarize(config, graded, failures, tuple(owed), {})
    assert passed is True, report_lines
    assert any(line.startswith("UNMEASURED  home-cite-flood") for line in report_lines)
    assert [u["task"] for u in result["unmeasured"]] == ["home-cite-flood"]


def test_a_declared_task_that_fails_for_any_other_reason_is_still_a_failure(
    tmp_path: Path,
) -> None:
    """What is declared is the ABSENCE OF ITS RECORDINGS and nothing else. A declared task that
    times out, or whose server dies, is a break like any other -- and a row in a register is
    exactly the kind of thing that quietly grows into a blanket exemption if it is not held to
    the one error it was written for."""
    runnable, _ = run.partition(run.select(CATALOG, "home-cite-flood"))
    prepared = {"personal_archive": _prepared(tmp_path, "personal_archive")}

    def broken(_request: ModelRequest) -> Turn:
        msg = "the provider hung up"
        raise OSError(msg)

    _graded, failures, owed = anyio.run(
        lambda: run.run_all(
            runnable,
            [h.Arm.CONTROL],
            prepared,
            turn=broken,
            settings=SETTINGS,
            workers=1,
            model_key="anthropic/claude-sonnet-5",
        )
    )

    assert owed == [], "an OSError is not a missing recording"
    assert [f.task_id for f in failures] == ["home-cite-flood"]
    assert "hung up" in failures[0].message


def test_the_owed_declaration_is_checked_the_other_way_too() -> None:
    """A declared gap that is filled is a stale declaration, not a pass.

    Both guards in `stale_declarations` are the evidence and not caution, so both are driven:
    under `allow` the task would be graded whether or not a recording existed, and with nothing
    replayed the store was never read. Only a `required` run that replayed can tell the two apart.
    """
    ids = {"home-cite-flood", "data-ret-series-b"}
    required = {
        "model_key": "anthropic/claude-sonnet-5",
        "mode": run.CassetteMode.REQUIRED,
        "replayed": 7,
    }
    (one,) = run.stale_declarations(ids, (), **required)
    assert one.task_id == "home-cite-flood", "an undeclared task is not asked about"
    assert "drop the model key from its row" in one.message
    assert "anthropic/claude-sonnet-5" in one.message, "the message names the model set"
    #  The case the real replay found. The control arm grades the task from recordings of its own
    #  while the omniweave arm misses, so the id is graded AND held, and a gap that is held is
    #  not a gap that is filled. Without the subtraction all four tasks read UNMEASURED and
    #  FAILED at once.
    assert run.stale_declarations(ids, {"home-cite-flood"}, **required) == []
    allow = {
        "model_key": "anthropic/claude-sonnet-5",
        "mode": run.CassetteMode.ALLOW,
        "replayed": 7,
    }
    cold = {
        "model_key": "anthropic/claude-sonnet-5",
        "mode": run.CassetteMode.REQUIRED,
        "replayed": 0,
    }
    assert run.stale_declarations(ids, (), **allow) == []
    assert run.stale_declarations(ids, (), **cold) == []


def test_the_declaration_is_per_model_set_because_the_gap_is() -> None:
    """D1029, and the finding that keyed this register by model set rather than by task.

    D972 deleted fifteen orphaned recordings. Fifteen does not cover all twelve (task, model set)
    pairs: under `openai/qwen3:4b`, `legal-cite-liability-cap` REPLAYS on every arm. The first
    version of this register declared the four tasks outright, and the real sweep's third replay
    reported that pair as a stale declaration -- which is the other direction doing exactly its
    job, on a case no amount of reading the code would have produced.

    Declared per task, that one working pair would have been excused for ever, and the day its
    recordings broke the nightly would have stayed green.
    """
    qwen, sonnet = "openai/qwen3:4b", "anthropic/claude-sonnet-5"
    assert "legal-cite-liability-cap" not in run.owed_for(qwen), "it replays under qwen3:4b"
    assert "legal-cite-liability-cap" in run.owed_for(sonnet)
    assert run.owed_for(qwen) == {
        "legal-cite-termination",
        "data-cite-nda-term",
        "home-cite-flood",
    }
    assert len(run.owed_for(sonnet)) == 4
    assert len(run.owed_for("openai/gpt-5-mini")) == 4
    #  Eleven of twelve pairs, counted the other way round, so a row silently losing a model key
    #  moves this number.
    assert sum(len(models) for models in run.OWED_RECORDINGS.values()) == 11
    assert run.owed_for("openai/some-model-nobody-replays") == frozenset(), (
        "a model set with no declaration declares nothing"
    )


def test_every_owed_row_names_a_task_the_catalogue_actually_has() -> None:
    """The register, checked against the catalogue. A row naming no task excuses nothing and
    reads as though it does, which is the failure mode of every exemption list."""
    known = {task.id for task in CATALOG.tasks}
    unknown = sorted(set(run.OWED_RECORDINGS) - known)
    assert not unknown, f"OWED_RECORDINGS names {unknown}, which bench/serve/tasks.toml does not"
    classes = {task.id: task.task_class.value for task in CATALOG.tasks}
    assert {classes[one] for one in run.OWED_RECORDINGS} == {"citation"}, (
        "CHANGELOG.md declares four CITATION tasks; a row of another class is a different gap"
    )
    assert len(run.OWED_RECORDINGS) == 4, "CHANGELOG.md's known limitations say four"


def test_usage_adds_the_keys_a_run_hit_or_recorded_to_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D972: `--usage` is the half of Q-G2's orphan sweep a replay writes (13-quality.md:622)."""
    hit, recorded, earlier = "a" * 64, "b" * 64, "c" * 64
    cassette = run.AgentCassette(run.CassetteMode.REQUIRED, tmp_path)
    cassette.hits.append(hit)
    cassette.recorded.append(recorded)
    started = run.Started(ac.resolve(flags={}), CATALOG, (), (), cassette, None, {})
    monkeypatch.setattr(run, "_start", lambda _args, _emit: started)

    async def nothing(*_args: object, **_kwargs: object) -> tuple[list[Any], list[Any], list[Any]]:
        return [], [], []

    monkeypatch.setattr(run, "run_all", nothing)
    usage = tmp_path / "eval" / "cassette-usage.toml"
    usage.parent.mkdir()
    usage.write_text(f'[agent]\nhit = ["{earlier}"]\n', encoding="utf-8")
    code, out = _main("--usage", str(usage))
    assert code == 0, out
    assert out[-1] == f"bench/serve: 3 key(s) used, in {usage.as_posix()}"
    rows = "".join(f'    "{key}",\n' for key in (hit, recorded, earlier))
    assert usage.read_bytes() == f"{USAGE_HEADER}\n[agent]\nhit = [\n{rows}]\n".encode()
