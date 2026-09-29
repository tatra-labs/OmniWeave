"""The agent loop: one agent, two arms, a fixed budget, every turn through a Cassette (ADR-14)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import agent as a
import anyio
import pytest
import serve_harness as h
from agent_cassette import AgentCassette
from host_tools import HostTools
from models import ModelRequest, ToolSpec, ToolUse, Turn
from omniweave_core.cassette import CassetteMode

SETTINGS = a.LoopSettings(model="m", temperature=0.0, max_tokens=256, tool_budget=3)
INSTRUCTIONS = "Call mcp__omniweave__ow_query first."


class Scripted:
    """A model that plays a list of turns, and remembers every request it was shown."""

    def __init__(self, *turns: Turn) -> None:
        self.turns = list(turns)
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> Turn:
        self.requests.append(request)
        return self.turns.pop(0) if self.turns else Turn("out of script")


class FakeServer:
    instructions: str | None = INSTRUCTIONS

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("ow_query", "ask the corpus", {"type": "object"}),)

    async def call(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        self.calls.append((name, dict(arguments)))
        return "Notice is thirty days [d1#3].", False


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    (tmp_path / "msa.txt").write_text("Notice is thirty days.\n", encoding="utf-8")
    return tmp_path


def _use(name: str, **arguments: object) -> ToolUse:
    return ToolUse(f"u-{name}-{len(arguments)}", name, arguments)


def _run(turn: a.TurnFn, docs: Path, arm: h.Arm, server: FakeServer | None = None) -> a.AgentRun:
    async def go() -> a.AgentRun:
        return await a.run_task(
            "cite-notice",
            "What is the notice period?",
            arm,
            host=HostTools(docs),
            turn=turn,
            settings=SETTINGS,
            server=server,
        )

    return anyio.run(go)


def test_the_control_arm_greps_reads_and_answers_on_a_turn_with_no_tool_call(docs: Path) -> None:
    model = Scripted(
        Turn("", (_use("Grep", pattern="Notice"),)),
        Turn("", (_use("Read", file_path="msa.txt"),)),
        Turn("Thirty days (msa.txt)."),
    )
    run = _run(model, docs, h.Arm.CONTROL)
    assert [call.tool for call in run.transcript.calls] == ["Grep", "Read"]
    assert run.transcript.answer == "Thirty days (msa.txt)."
    assert (run.budget_exhausted, run.model_turns, run.tool_calls) == (False, 3, 2)
    assert not any(tool.name.startswith(a.MCP_PREFIX) for tool in model.requests[0].tools)
    task = h.Task(
        id="cite-notice",
        task_class=h.TaskClass.RETRIEVAL,
        corpus=h.Corpus.LEGAL_MATTER,
        source_kind=h.SourceKind.BORN_DIGITAL,
        prompt="What is the notice period?",
        expect=h.Expect(contains=("thirty days",)),
    )
    graded = h.outcome(task, run.transcript, h.indexed_sources("msa.txt\n", docs.as_posix()))
    assert (graded.correct, graded.reread, graded.mis_pick) == (True, True, None)


def test_the_budget_counts_calls_then_forces_one_answer_with_tools_offered_not_allowed(
    docs: Path,
) -> None:
    reading = Turn("", (_use("Read", file_path="msa.txt"),))
    model = Scripted(reading, reading, reading, reading, Turn("Thirty days."))
    run = _run(model, docs, h.Arm.CONTROL)
    assert run.tool_calls == SETTINGS.tool_budget
    assert run.budget_exhausted is True
    assert run.model_turns == SETTINGS.tool_budget + 1
    final = model.requests[-1]
    assert final.allow_tools is False
    assert final.tools, "a conversation holding tool calls must still define its tools"
    assert run.transcript.answer == ""  # the fourth scripted turn, which tried a tool anyway


def test_a_turn_asking_for_more_calls_than_are_left_gets_refusals_for_the_rest(
    docs: Path,
) -> None:
    many = Turn("", tuple(_use("Read", file_path="msa.txt", n=i) for i in range(5)))
    model = Scripted(many, Turn("Thirty days."))
    run = _run(model, docs, h.Arm.CONTROL)
    assert run.tool_calls == SETTINGS.tool_budget
    refused = [
        message
        for message in model.requests[1].messages
        if getattr(message, "text", "") == "tool budget exhausted; answer now"
    ]
    assert len(refused) == 2


def test_the_omniweave_arm_sees_the_server_prefixed_and_its_instructions(docs: Path) -> None:
    server = FakeServer()
    model = Scripted(
        Turn("", (_use(a.MCP_PREFIX + "ow_query", query="notice period"),)),
        Turn("Thirty days [d1#3]."),
    )
    run = _run(model, docs, h.Arm.OMNIWEAVE, server)
    names = [tool.name for tool in model.requests[0].tools]
    assert names == ["mcp__omniweave__ow_query", "Read", "Grep", "Bash"]
    assert model.requests[0].system.endswith(INSTRUCTIONS)
    assert server.calls == [("ow_query", {"query": "notice period"})]
    assert run.transcript.calls == (h.ToolCall("ow_query", {"query": "notice period"}),)


def test_both_arms_share_one_system_prompt_and_one_set_of_host_tools(docs: Path) -> None:
    control = Scripted(Turn("x"))
    served = Scripted(Turn("x"))
    _run(control, docs, h.Arm.CONTROL)
    _run(served, docs, h.Arm.OMNIWEAVE, FakeServer())
    assert served.requests[0].system.startswith(control.requests[0].system)
    assert served.requests[0].tools[1:] == control.requests[0].tools


def test_an_arm_and_its_server_must_agree(docs: Path) -> None:
    with pytest.raises(ValueError, match="needs a server"):
        _run(Scripted(Turn("x")), docs, h.Arm.OMNIWEAVE)
    with pytest.raises(ValueError, match="must not have"):
        _run(Scripted(Turn("x")), docs, h.Arm.CONTROL, FakeServer())


def test_a_recorded_run_replays_to_the_same_transcript_with_no_model(
    docs: Path, tmp_path: Path
) -> None:
    script = (
        Turn("", (_use("Grep", pattern="Notice"),)),
        Turn("", (_use("Read", file_path="msa.txt"),)),
        Turn("Thirty days."),
    )
    store = tmp_path / "cassettes"
    recording = AgentCassette(CassetteMode.ALLOW, store)
    live = Scripted(*script)
    first = _run(
        lambda r: recording.turn(r, model_key="scripted/1", live=live), docs, h.Arm.CONTROL
    )

    replaying = AgentCassette(CassetteMode.REQUIRED, store)
    second = _run(
        lambda r: replaying.turn(r, model_key="scripted/1", live=None), docs, h.Arm.CONTROL
    )
    assert second.transcript == first.transcript
    assert (len(recording.recorded), replaying.live_calls, len(replaying.hits)) == (3, 0, 3)
