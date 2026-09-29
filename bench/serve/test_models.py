"""The two providers' wires, built and parsed with no network (ADR-14 D14.4, D14.7)."""

from __future__ import annotations

import json
from collections.abc import Mapping

import models as m
import pytest

TOOLS = (m.ToolSpec("Read", "read a file", {"type": "object", "properties": {}}),)
PNG = m.Image("image/png", "iVBORw0KGgo=")


def _request(*, allow: bool = True) -> m.ModelRequest:
    use = m.ToolUse("t1", "Read", {"file_path": "/d/a.txt"})
    second = m.ToolUse("t2", "Read", {"file_path": "/d/b.pdf"})
    return m.ModelRequest(
        system="sys",
        messages=(
            m.UserText("what is the notice period?"),
            m.AssistantTurn(m.Turn("looking", (use, second))),
            m.ToolResult("t1", "thirty days"),
            m.ToolResult("t2", "--- page 1: no text layer ---", images=(PNG,)),
        ),
        tools=TOOLS,
        model="model-x",
        temperature=0.0,
        max_tokens=512,
        sampling={"allow_tools": allow},
    )


class FakePost:
    def __init__(self, reply: Mapping[str, object]) -> None:
        self.reply = reply
        self.seen: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> bytes:
        del timeout
        self.seen.append((url, dict(headers), json.loads(body)))
        return json.dumps(self.reply).encode()


def test_anthropic_groups_tool_results_into_one_user_message_with_their_images() -> None:
    body = m.AnthropicClient(api_key="k").body(_request())
    assert body["system"] == "sys"
    assert [one["role"] for one in body["messages"]] == ["user", "assistant", "user"]
    assistant = body["messages"][1]["content"]
    assert [block["type"] for block in assistant] == ["text", "tool_use", "tool_use"]
    results = body["messages"][2]["content"]
    assert [block["tool_use_id"] for block in results] == ["t1", "t2"]
    assert results[1]["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": PNG.data_b64},
    }
    assert "tool_choice" not in body


def test_anthropic_forbids_tools_on_the_forced_final_turn_but_still_defines_them() -> None:
    body = m.AnthropicClient(api_key="k").body(_request(allow=False))
    assert body["tool_choice"] == {"type": "none"}
    assert body["tools"][0]["name"] == "Read"


def test_anthropic_parses_text_and_tool_use_blocks() -> None:
    turn = m.AnthropicClient.parse(
        {
            "content": [
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "u1", "name": "Grep", "input": {"pattern": "x"}},
            ]
        }
    )
    assert turn == m.Turn("Checking.", (m.ToolUse("u1", "Grep", {"pattern": "x"}),))


def test_anthropic_sends_the_key_and_version_to_the_configured_endpoint() -> None:
    post = FakePost({"content": [{"type": "text", "text": "done"}]})
    client = m.AnthropicClient(api_key="secret", base_url="http://proxy.local/", post=post)
    assert client.complete(_request()) == m.Turn("done")
    url, headers, _body = post.seen[0]
    assert url == "http://proxy.local/v1/messages"
    assert (headers["x-api-key"], headers["anthropic-version"]) == ("secret", "2023-06-01")


def test_openai_puts_tool_images_in_a_user_message_after_the_tool_messages() -> None:
    body = m.OpenAIClient(base_url="http://localhost:11434/v1").body(_request())
    roles = [one["role"] for one in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool", "user"]
    calls = body["messages"][2]["tool_calls"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"file_path": "/d/a.txt"}
    parts = body["messages"][5]["content"]
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{PNG.data_b64}"
    assert body["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {}}
    assert "tool_choice" not in body
    assert m.OpenAIClient().body(_request(allow=False))["tool_choice"] == "none"


def test_openai_parses_tool_calls_and_keeps_unparseable_arguments_visible() -> None:
    turn = m.OpenAIClient.parse(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "c1", "function": {"name": "Read", "arguments": '{"a": 1}'}},
                            {"id": "c2", "function": {"name": "Read", "arguments": "{oops"}},
                        ],
                    }
                }
            ]
        }
    )
    assert turn.text == ""
    assert turn.tool_uses == (
        m.ToolUse("c1", "Read", {"a": 1}),
        m.ToolUse("c2", "Read", {"_unparsed": "{oops"}),
    )
    with pytest.raises(m.ModelError, match="no choices"):
        m.OpenAIClient.parse({"choices": []})


def test_a_local_server_gets_no_authorization_header() -> None:
    post = FakePost({"choices": [{"message": {"content": "ok"}}]})
    m.OpenAIClient(base_url="http://localhost:11434/v1", post=post).complete(_request())
    url, headers, _body = post.seen[0]
    assert url == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in headers


def test_anthropic_without_its_key_names_the_variable_a_local_model_and_replay() -> None:
    with pytest.raises(m.ModelError) as caught:
        m.client_for("anthropic", key_env="ANTHROPIC_API_KEY", base_url="", timeout_s=5, env={})
    for name in ("ANTHROPIC_API_KEY", "provider = openai", "cassette = required"):
        assert name in str(caught.value)


def test_a_local_openai_compatible_server_needs_no_key_and_the_public_one_does() -> None:
    local = m.client_for(
        "openai", key_env="OPENAI_API_KEY", base_url="http://localhost:1234/v1", timeout_s=5, env={}
    )
    assert local.name == "openai"
    with pytest.raises(m.ModelError, match="base_url"):
        m.client_for("openai", key_env="OPENAI_API_KEY", base_url="", timeout_s=5, env={})


def test_the_canonical_conversation_carries_an_image_as_its_digest_not_its_bytes() -> None:
    canonical = m.canonical_request(_request())
    tool = canonical["messages"][3]
    assert tool["images"] == [PNG.sha256]
    assert PNG.data_b64 not in json.dumps(canonical)
