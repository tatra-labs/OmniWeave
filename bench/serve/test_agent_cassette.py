"""The `bench.agent` Cassette site: record, replay, refuse (ADR-14 D14.4; 13-quality.md:982)."""

from __future__ import annotations

import json
from pathlib import Path

import agent_cassette as ca
import models as m
import pytest
from omniweave_core.cassette import MAX_CASSETTE_BYTES, CassetteMode

MODEL_KEY = "anthropic/claude-sonnet-5"


def _request(
    text: str = "notice?", *, arguments: dict[str, object] | None = None
) -> m.ModelRequest:
    use = m.ToolUse("t1", "Grep", arguments or {"pattern": "notice", "path": "/d"})
    return m.ModelRequest(
        system="sys",
        messages=(m.UserText(text), m.AssistantTurn(m.Turn("", (use,))), m.ToolResult("t1", "hit")),
        tools=(m.ToolSpec("Grep", "search", {"type": "object"}),),
        model="claude-sonnet-5",
        temperature=0.0,
        max_tokens=256,
        sampling={"allow_tools": True},
    )


def _never(request: m.ModelRequest) -> m.Turn:
    raise AssertionError(f"a live call was made for {request.model}")


def test_the_key_ignores_argument_order_and_moves_with_every_keyed_input() -> None:
    one, _ = ca.request_key(_request(arguments={"a": 1, "b": 2}), model_key=MODEL_KEY)
    two, _ = ca.request_key(_request(arguments={"b": 2, "a": 1}), model_key=MODEL_KEY)
    assert one == two
    base, _ = ca.request_key(_request(), model_key=MODEL_KEY)
    assert ca.request_key(_request("other"), model_key=MODEL_KEY)[0] != base
    assert ca.request_key(_request(), model_key="openai/qwen3:8b")[0] != base
    _, inputs = ca.request_key(_request(), model_key=MODEL_KEY)
    assert sorted(inputs) == [
        "contract",
        "model_key",
        "payload_digest",
        "prompt_digest",
        "sampling",
        "service",
    ]
    assert inputs["contract"] == ["bench.agent", ca.HARNESS_MAJOR]


def test_allow_records_once_and_required_replays_with_no_provider(tmp_path: Path) -> None:
    turn = m.Turn("Thirty days, per the MSA.")
    recorder = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    assert recorder.turn(_request(), model_key=MODEL_KEY, live=lambda _r: turn) == turn
    assert (recorder.live_calls, len(recorder.recorded)) == (1, 1)

    replayer = ca.AgentCassette(CassetteMode.REQUIRED, tmp_path)
    assert replayer.turn(_request(), model_key=MODEL_KEY, live=None) == turn
    assert (replayer.live_calls, replayer.hits) == (0, recorder.recorded)


def test_a_required_miss_is_ow_q_004_naming_the_record_path_and_never_calls_live(
    tmp_path: Path,
) -> None:
    cassette = ca.AgentCassette(CassetteMode.REQUIRED, tmp_path)
    with pytest.raises(ca.CassetteMissError) as caught:
        cassette.turn(_request(), model_key=MODEL_KEY, live=_never)
    assert "OW-Q-004" in str(caught.value)
    assert "cassette = allow" in str(caught.value)
    assert cassette.live_calls == 0


def test_off_calls_live_and_writes_nothing(tmp_path: Path) -> None:
    cassette = ca.AgentCassette(CassetteMode.OFF, tmp_path)
    cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x"))
    assert cassette.live_calls == 1
    assert not any(tmp_path.rglob("*.json"))


def test_a_record_holds_the_key_inputs_and_the_turn_and_no_header(tmp_path: Path) -> None:
    cassette = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x"))
    (path,) = tmp_path.rglob("*.json")
    assert path.parent.parent.name == "agent"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["seam"] == "bench.agent"
    assert record["prompt_version"] == ca.PROMPT_VERSION
    assert sorted(record) == [
        "contract_major",
        "inputs",
        "key",
        "prompt_version",
        "record_version",
        "seam",
        "turn",
    ]
    assert "x-api-key" not in path.read_text(encoding="utf-8").casefold()


def test_a_stale_prompt_version_is_a_miss_and_not_a_hit(tmp_path: Path) -> None:
    ca.AgentCassette(CassetteMode.ALLOW, tmp_path).turn(
        _request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x")
    )
    (path,) = tmp_path.rglob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["prompt_version"] = "agent-prompt/0"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ca.CassetteMissError):
        ca.AgentCassette(CassetteMode.REQUIRED, tmp_path).turn(
            _request(), model_key=MODEL_KEY, live=None
        )


def test_an_oversize_recording_is_refused_at_record_time_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    huge = m.Turn("x" * (MAX_CASSETTE_BYTES + 1))
    cassette = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    with pytest.raises(ca.CassetteOversizeError, match="OW-Q-017"):
        cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: huge)
    assert not any(tmp_path.rglob("*.json"))
