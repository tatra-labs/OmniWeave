"""The scripted agent's model: provider-neutral turns, and two stdlib clients (ADR-14 D14.4, D14.7).

The agent loop speaks one small vocabulary -- a `ModelRequest` in, a `Turn` out -- and each
provider translates it to its own wire:

* **`anthropic`**: the Messages API.
* **`openai`**: the Chat Completions wire. That is also what Ollama, vLLM, llama.cpp and LM Studio
  serve, so recording with a local model needs no paid key (D14.7 part 1).

Both are stdlib `urllib`, so no SDK enters the lock and G3 does not move. The HTTP call is a
PARAMETER (`Post`), so every request body and every response parse is tested without a network.

The neutral vocabulary is also what the `bench.agent` Cassette digests (`canonical_request`):
a recording names the conversation, not one vendor's JSON for it, and an image enters the key as
its sha256 rather than as its bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

__all__ = [
    "AnthropicClient",
    "AssistantTurn",
    "Image",
    "ModelClient",
    "ModelError",
    "ModelRequest",
    "OpenAIClient",
    "Post",
    "ToolResult",
    "ToolSpec",
    "ToolUse",
    "Turn",
    "UserText",
    "canonical_request",
    "client_for",
    "turn_from_json",
    "turn_json",
    "urllib_post",
]

ANTHROPIC_URL: Final[str] = "https://api.anthropic.com"
ANTHROPIC_VERSION: Final[str] = "2023-06-01"
OPENAI_URL: Final[str] = "https://api.openai.com/v1"


class ModelError(RuntimeError):
    """A model call that could not be made or understood. The message names the fix."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool the model may call: a name, a description, a JSON Schema for its input."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolUse:
    """One tool call the model asked for."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Turn:
    """What the model returned: its text, and the tool calls it asked for, in order."""

    text: str
    tool_uses: tuple[ToolUse, ...] = ()


@dataclass(frozen=True, slots=True)
class Image:
    """A PNG handed back by a tool -- a PDF page with no text layer (ADR-14 D14.3)."""

    media_type: str
    data_b64: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data_b64.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class UserText:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    turn: Turn


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_use_id: str
    text: str
    images: tuple[Image, ...] = ()
    is_error: bool = False


Message = UserText | AssistantTurn | ToolResult


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One model call, provider-neutral."""

    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    model: str
    temperature: float | None
    max_tokens: int
    sampling: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allow_tools(self) -> bool:
        """False on the one forced final turn after the budget is spent (`tool_choice: none`)."""
        return bool(self.sampling.get("allow_tools", True))


def canonical_request(request: ModelRequest) -> dict[str, Any]:
    """The conversation as the Cassette key sees it: neutral JSON, images by digest."""

    def message(one: Message) -> dict[str, Any]:
        if isinstance(one, UserText):
            return {"role": "user", "text": one.text}
        if isinstance(one, AssistantTurn):
            return {"role": "assistant", "turn": turn_json(one.turn)}
        return {
            "role": "tool",
            "tool_use_id": one.tool_use_id,
            "text": one.text,
            "images": [image.sha256 for image in one.images],
            "is_error": one.is_error,
        }

    return {
        "system": request.system,
        "messages": [message(one) for one in request.messages],
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)}
            for t in request.tools
        ],
    }


def turn_json(turn: Turn) -> dict[str, Any]:
    return {
        "text": turn.text,
        "tool_uses": [
            {"id": use.id, "name": use.name, "arguments": dict(use.arguments)}
            for use in turn.tool_uses
        ],
    }


def turn_from_json(value: Mapping[str, Any]) -> Turn:
    return Turn(
        text=str(value.get("text", "")),
        tool_uses=tuple(
            ToolUse(id=str(use["id"]), name=str(use["name"]), arguments=dict(use["arguments"]))
            for use in value.get("tool_uses", [])
        ),
    )


# =============================================================================================
# The wire
# =============================================================================================

Post = Callable[[str, Mapping[str, str], bytes, float], bytes]
"""`(url, headers, body, timeout_s) -> response body`. Raises `ModelError`, naming the fix."""


def urllib_post(url: str, headers: Mapping[str, str], body: bytes, timeout_s: float) -> bytes:
    """The one real `Post`: stdlib, no retry, and every failure worded as its fix."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310 -- the URL is the configured endpoint
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:500].decode("utf-8", "replace")
        raise ModelError(
            f"{url} answered HTTP {exc.code}: {detail}. Check the model id and the key; "
            "or replay the committed recordings with cassette = required"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelError(
            f"cannot reach {url}: {exc}. Check base_url in bench/serve/agent.toml (a local "
            "server must be running), or replay the committed recordings with cassette = required"
        ) from exc


class ModelClient(Protocol):
    name: str

    def complete(self, request: ModelRequest) -> Turn: ...


class AnthropicClient:
    """The Messages API. Tool results go back as `tool_result` blocks, images included."""

    name = "anthropic"

    def __init__(
        self, *, api_key: str, base_url: str = "", timeout_s: float = 120, post: Post = urllib_post
    ) -> None:
        self._key = api_key
        self._url = (base_url or ANTHROPIC_URL).rstrip("/") + "/v1/messages"
        self._timeout = timeout_s
        self._post = post

    def body(self, request: ModelRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for one in request.messages:
            if isinstance(one, UserText):
                messages.append({"role": "user", "content": one.text})
            elif isinstance(one, AssistantTurn):
                blocks: list[dict[str, Any]] = []
                if one.turn.text:
                    blocks.append({"type": "text", "text": one.turn.text})
                blocks.extend(
                    {"type": "tool_use", "id": u.id, "name": u.name, "input": dict(u.arguments)}
                    for u in one.turn.tool_uses
                )
                messages.append({"role": "assistant", "content": blocks})
            else:
                content: list[dict[str, Any]] = [{"type": "text", "text": one.text or "(empty)"}]
                content.extend(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": i.media_type,
                            "data": i.data_b64,
                        },
                    }
                    for i in one.images
                )
                block = {
                    "type": "tool_result",
                    "tool_use_id": one.tool_use_id,
                    "content": content,
                    "is_error": one.is_error,
                }
                if (
                    messages
                    and messages[-1]["role"] == "user"
                    and isinstance(messages[-1]["content"], list)
                ):
                    messages[-1]["content"].append(block)
                else:
                    messages.append({"role": "user", "content": [block]})
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": messages,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)}
                for t in request.tools
            ]
            if not request.allow_tools:
                body["tool_choice"] = {"type": "none"}
        return body

    @staticmethod
    def parse(response: Mapping[str, Any]) -> Turn:
        texts: list[str] = []
        uses: list[ToolUse] = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                uses.append(
                    ToolUse(id=str(block["id"]), name=str(block["name"]), arguments=block["input"])
                )
        return Turn(text="\n".join(texts).strip(), tool_uses=tuple(uses))

    def complete(self, request: ModelRequest) -> Turn:
        headers = {
            "content-type": "application/json",
            "x-api-key": self._key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        raw = self._post(self._url, headers, json.dumps(self.body(request)).encode(), self._timeout)
        return self.parse(_json(raw, self._url))


class OpenAIClient:
    """The Chat Completions wire, which local servers speak too.

    A `tool` message carries text only on this wire, so a tool's images follow the tool messages
    as one `user` message of `image_url` parts -- the same pixels, in the one place the wire
    accepts them.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        timeout_s: float = 120,
        post: Post = urllib_post,
    ) -> None:
        self._key = api_key
        self._url = (base_url or OPENAI_URL).rstrip("/") + "/chat/completions"
        self._timeout = timeout_s
        self._post = post

    def body(self, request: ModelRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        pending: list[Image] = []

        def flush() -> None:
            if pending:
                parts: list[dict[str, Any]] = [
                    {"type": "text", "text": "Images returned by the tool calls above."}
                ]
                parts.extend(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{i.media_type};base64,{i.data_b64}"},
                    }
                    for i in pending
                )
                messages.append({"role": "user", "content": parts})
                pending.clear()

        for one in request.messages:
            if isinstance(one, ToolResult):
                messages.append(
                    {"role": "tool", "tool_call_id": one.tool_use_id, "content": one.text}
                )
                pending.extend(one.images)
                continue
            flush()
            if isinstance(one, UserText):
                messages.append({"role": "user", "content": one.text})
            else:
                message: dict[str, Any] = {"role": "assistant", "content": one.turn.text or None}
                if one.turn.tool_uses:
                    message["tool_calls"] = [
                        {
                            "id": u.id,
                            "type": "function",
                            "function": {
                                "name": u.name,
                                "arguments": json.dumps(dict(u.arguments)),
                            },
                        }
                        for u in one.turn.tool_uses
                    ]
                messages.append(message)
        flush()
        #  OpenAI's own endpoint takes `max_completion_tokens`, and its reasoning models refuse
        #  `max_tokens`; the local servers this wire also reaches (Ollama, vLLM, llama.cpp) take
        #  `max_tokens`. D650.
        limit = (
            "max_completion_tokens"
            if self._url == OPENAI_URL + "/chat/completions"
            else ("max_tokens")
        )
        body: dict[str, Any] = {
            "model": request.model,
            limit: request.max_tokens,
            "messages": messages,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": dict(t.input_schema),
                    },
                }
                for t in request.tools
            ]
            if not request.allow_tools:
                body["tool_choice"] = "none"
        return body

    @staticmethod
    def parse(response: Mapping[str, Any]) -> Turn:
        choices = response.get("choices") or []
        if not choices:
            raise ModelError(f"the response has no choices: {str(response)[:300]}")
        message = choices[0].get("message", {})
        uses: list[ToolUse] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                arguments = {"_unparsed": raw}
            uses.append(
                ToolUse(id=str(call["id"]), name=str(function["name"]), arguments=arguments)
            )
        return Turn(text=str(message.get("content") or "").strip(), tool_uses=tuple(uses))

    def complete(self, request: ModelRequest) -> Turn:
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        raw = self._post(self._url, headers, json.dumps(self.body(request)).encode(), self._timeout)
        return self.parse(_json(raw, self._url))


def _json(raw: bytes, url: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelError(f"{url} returned non-JSON: {raw[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise ModelError(f"{url} returned {type(parsed).__name__}, not an object")
    return parsed


def client_for(
    provider: str,
    *,
    key_env: str,
    base_url: str,
    timeout_s: float,
    env: Mapping[str, str] | None = None,
    post: Post = urllib_post,
) -> ModelClient:
    """The live client a configuration names. A missing key is refused here, naming the fix."""
    environ = os.environ if env is None else env
    key = environ.get(key_env, "")
    if provider == "anthropic":
        if not key:
            raise ModelError(
                f"recording with provider = anthropic needs {key_env} set. Or record with a local "
                "model (provider = openai, base_url = http://localhost:11434/v1 for Ollama), or "
                "replay the committed recordings with cassette = required, which needs no key"
            )
        return AnthropicClient(api_key=key, base_url=base_url, timeout_s=timeout_s, post=post)
    if provider == "openai":
        if not key and not base_url:
            raise ModelError(
                f"provider = openai against api.openai.com needs {key_env} set. A local server "
                "needs none: set base_url (e.g. http://localhost:11434/v1). Or replay with "
                "cassette = required"
            )
        return OpenAIClient(api_key=key, base_url=base_url, timeout_s=timeout_s, post=post)
    raise ModelError(f"unknown provider {provider!r}; expected anthropic or openai")
