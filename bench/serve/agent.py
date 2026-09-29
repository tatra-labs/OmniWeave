"""The scripted agent: one loop, two arms, a fixed tool budget (ADR-14 D14.3, D14.4).

**One agent, two arms, one difference.** Both arms use the same model, sampling, system prompt,
host tools (`host_tools.HostTools`) and budget. The omniweave arm also has `omniweave-serve` over
stdio, reached through the official MCP client exactly as a host reaches it:
- its `tools/list`, with names prefixed `mcp__omniweave__` as a host prefixes them (10:898);
- its `instructions` string, appended to the system prompt as a host does with what `initialize`
  returns.
The control arm has neither. Nothing else differs, so a difference in `task_accuracy` is the
server's.

**The stopping rule** (D14.3 part 4). A task ends on a turn with no tool call, and that turn's
text is the answer. The budget counts tool CALLS, not turns. Once it is spent, one last turn is
asked for with the tools offered but not allowed (`allow_tools = False`, a provider's
`tool_choice: none`), and the run is flagged `budget_exhausted`. The tools stay OFFERED because a
conversation that holds tool calls must still define them on both wires. So a task costs at most
`budget + 1` model calls.

**Every model call goes through `AgentCassette`** (13:1402). The loop is given a `TurnFn` and
never a client, so it cannot make an unrecorded call.

The transcript records bare tool names (`ow_query`, `Read`) and the absolute paths a host call
touched, which is what `serve_harness.outcome()` grades.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import anyio
import anyio.to_thread
from host_tools import HostTools
from models import AssistantTurn, ModelRequest, ToolResult, ToolSpec, ToolUse, Turn, UserText
from serve_harness import Arm, ToolCall, Transcript

__all__ = [
    "MCP_PREFIX",
    "SYSTEM_PROMPT",
    "AgentRun",
    "LoopSettings",
    "OwServer",
    "ToolServer",
    "TurnFn",
    "run_task",
    "system_prompt",
]

MCP_PREFIX: Final[str] = "mcp__omniweave__"

SYSTEM_PROMPT: Final[str] = (
    "You are answering a question about the documents in the folder {root}. Use the tools you "
    "have to find the answer. Answer concisely, and name the document the answer comes from, and "
    "its page where it has one. If the documents do not contain the answer, say so plainly and "
    "do not guess. Your final message, the one with no tool call, is your answer."
)
"""The one system prompt, identical in both arms. Its version is `agent_cassette.PROMPT_VERSION`,
and changing a word of it is a re-record."""

TurnFn = Callable[[ModelRequest], Turn]
"""One model call, already routed through the Cassette."""


class ToolServer(Protocol):
    """What the omniweave arm needs from an MCP server: its instructions, tools and calls."""

    instructions: str | None

    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def call(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]: ...


@dataclass(frozen=True, slots=True)
class LoopSettings:
    model: str
    temperature: float
    max_tokens: int
    tool_budget: int


@dataclass(frozen=True, slots=True)
class AgentRun:
    """One task on one arm: the graded transcript, and how the run ended."""

    transcript: Transcript
    budget_exhausted: bool
    model_turns: int
    tool_calls: int


def system_prompt(root: Path, instructions: str | None) -> str:
    base = SYSTEM_PROMPT.format(root=root.as_posix())
    return f"{base}\n\n{instructions}" if instructions else base


async def run_task(
    task_id: str,
    prompt: str,
    arm: Arm,
    *,
    host: HostTools,
    turn: TurnFn,
    settings: LoopSettings,
    server: ToolServer | None = None,
) -> AgentRun:
    """Run one task to its answer, or to its budget. `server` is required on the omniweave arm."""
    if (arm is Arm.OMNIWEAVE) != (server is not None):
        msg = f"the {arm.value} arm {'needs' if arm is Arm.OMNIWEAVE else 'must not have'} a server"
        raise ValueError(msg)
    served = tuple(
        ToolSpec(MCP_PREFIX + spec.name, spec.description, spec.input_schema)
        for spec in (server.specs() if server is not None else ())
    )
    tools = served + host.specs()
    system = system_prompt(host.root, server.instructions if server is not None else None)
    messages: list[UserText | AssistantTurn | ToolResult] = [UserText(prompt)]
    calls: list[ToolCall] = []
    used = turns = 0

    while True:
        allow = used < settings.tool_budget
        request = ModelRequest(
            system=system,
            messages=tuple(messages),
            tools=tools,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            sampling={"allow_tools": allow},
        )
        answer = await anyio.to_thread.run_sync(turn, request)
        turns += 1
        messages.append(AssistantTurn(answer))
        if not answer.tool_uses or not allow:
            transcript = Transcript(task_id, arm, tuple(calls), answer.text)
            return AgentRun(transcript, not allow, turns, used)
        for use in answer.tool_uses:
            if used >= settings.tool_budget:
                messages.append(
                    ToolResult(use.id, "tool budget exhausted; answer now", is_error=True)
                )
                continue
            used += 1
            result, call = await _dispatch(use, host=host, server=server)
            messages.append(result)
            calls.append(call)


async def _dispatch(
    use: ToolUse, *, host: HostTools, server: ToolServer | None
) -> tuple[ToolResult, ToolCall]:
    if use.name.startswith(MCP_PREFIX) and server is not None:
        bare = use.name.removeprefix(MCP_PREFIX)
        text, is_error = await server.call(bare, use.arguments)
        recorded = {
            key: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
            for key, value in use.arguments.items()
        }
        return ToolResult(use.id, text, is_error=is_error), ToolCall(bare, recorded)
    invocation = host.call(use)
    return invocation.result, invocation.call


class OwServer:
    """`python -m omniweave serve --mcp` as a child, through the official MCP client."""

    def __init__(
        self,
        *,
        cwd: Path,
        env: Mapping[str, str],
        python: str = sys.executable,
    ) -> None:
        self._cwd = cwd
        self._env = dict(env)
        self._python = python
        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._specs: tuple[ToolSpec, ...] = ()
        self.instructions: str | None = None

    async def __aenter__(self) -> OwServer:
        from mcp import ClientSession  # noqa: PLC0415 -- only the omniweave arm needs a client
        from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: PLC0415

        params = StdioServerParameters(
            command=self._python,
            args=["-m", "omniweave", "serve", "--mcp"],
            env=self._env,
            cwd=self._cwd,
        )
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            initialized = await session.initialize()
            listed = await session.list_tools()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._session = stack, session
        self.instructions = initialized.instructions
        self._specs = tuple(
            ToolSpec(tool.name, tool.description or "", dict(tool.inputSchema))
            for tool in listed.tools
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    def specs(self) -> tuple[ToolSpec, ...]:
        return self._specs

    async def call(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        from mcp.types import TextContent  # noqa: PLC0415

        result = await self._session.call_tool(name, dict(arguments))
        text = "\n".join(part.text for part in result.content if isinstance(part, TextContent))
        return text, bool(result.isError)
