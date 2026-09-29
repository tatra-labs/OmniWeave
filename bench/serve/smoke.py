"""`uv run bench/serve/smoke.py`: the omniweave arm end to end, with no model and no key.

A check a contributor can run before recording anything (ADR-14 D14.7, *"usable"*):
1. It writes a small office folder with `first_answer.office_folder`.
2. It indexes the folder with `ow add`.
3. It starts `ow serve --mcp` and reaches it through the official MCP client, as the agent does.
4. A scripted model makes one `ow_query` call, asking the folder's needle question.

It passes when the server lists `ow_query` and `ow_open`, `initialize` carries the instructions
string, and the answer names the needle's document. It prints one JSON object, and exits 0 on a
pass and 1 otherwise. Nothing is recorded, and nothing calls a provider.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
from agent import MCP_PREFIX, LoopSettings, OwServer, run_task
from first_answer import PROJECT, _env, office_folder
from host_tools import HostTools
from models import ModelRequest, ToolResult, ToolUse, Turn
from omniweave_core.host.subproc import run_captured
from serve_harness import Arm

TIMEOUT_S = 180


class _Scripted:
    def __init__(self, *turns: Turn) -> None:
        self.turns = list(turns)
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> Turn:
        self.requests.append(request)
        return self.turns.pop(0) if self.turns else Turn("done")


def smoke(work: Path, *, docs: int = 6, python: str = sys.executable) -> dict[str, Any]:
    """Index a small folder, ask it one question through a real server, report what came back."""
    project = work / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    folder = office_folder(project / "docs", docs)
    env = _env(work)
    added = run_captured(
        (python, "-m", "omniweave", "add", "docs"),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=TIMEOUT_S,
    )
    if added.returncode != 0:
        return {
            "passed": False,
            "failed": "ow add",
            "stderr": added.stderr.decode("utf-8", "replace")[-2000:],
        }

    async def talk() -> dict[str, Any]:
        with anyio.fail_after(TIMEOUT_S):
            async with OwServer(cwd=project, env=env, python=python) as server:
                names = [spec.name for spec in server.specs()]
                query = next(spec for spec in server.specs() if spec.name == "ow_query")
                argument = query.input_schema["required"][0]
                use = ToolUse("q1", MCP_PREFIX + "ow_query", {argument: folder.question})
                model = _Scripted(Turn("", (use,)), Turn("done"))
                run = await run_task(
                    "smoke",
                    folder.question,
                    Arm.OMNIWEAVE,
                    host=HostTools(project / "docs"),
                    turn=model,
                    settings=LoopSettings("scripted", 0.0, 256, 12),
                    server=server,
                )
                result = next(m for m in model.requests[1].messages if isinstance(m, ToolResult))
                return {
                    "tools": names,
                    "instructions_chars": len(server.instructions or ""),
                    "system_ends_with_instructions": bool(server.instructions)
                    and model.requests[0].system.endswith(server.instructions or ""),
                    "first_call": run.transcript.calls[0].tool,
                    "result_is_error": result.is_error,
                    "needle": folder.needle.name,
                    "needle_named": folder.needle.name in result.text,
                    "result_head": result.text[:600],
                }

    report = anyio.run(talk)
    report["passed"] = (
        {"ow_query", "ow_open"} <= set(report["tools"])
        and report["instructions_chars"] > 0
        and report["system_ends_with_instructions"]
        and report["first_call"] == "ow_query"
        and not report["result_is_error"]
        and report["needle_named"]
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the omniweave arm end to end, no model, no key")
    parser.add_argument("--work", type=Path, help="a directory to work in (default: a temp dir)")
    parser.add_argument("--docs", type=int, default=6, help="documents in the folder (default 6)")
    args = parser.parse_args(argv)
    if args.work is not None:
        report = smoke(args.work, docs=args.docs)
    else:
        with tempfile.TemporaryDirectory(prefix="ow-smoke-") as tmp:
            report = smoke(Path(tmp), docs=args.docs)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
