"""`bench/serve/run.py` end to end: record with a local model, then replay with none (ADR-14 D14.7).

The accessibility claim, run as a user would run it. The "local model" is a stand-in HTTP
server in this process that speaks the OpenAI Chat Completions wire, the one Ollama, vLLM,
llama.cpp and LM Studio serve.
1. The first child records, with `--record --provider openai --base-url <it>` and no key, over
   `personal_archive` at `--scale quick`: both arms, a real `ow add` and a real `ow serve --mcp`.
2. The stand-in is stopped.
3. The second child replays with `--cassette required`. It must make no live call at all and
   reach the same outcomes.

The stand-in's answers are not a model's, so the accuracy it produces means nothing. What is
asserted is the path: configuration, corpus cache, both arms, Cassette record and replay, report.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

SCRIPT = Path(__file__).resolve().parents[4] / "bench" / "serve" / "run.py"
TIMEOUT_S = 600


def _keyword(prompt: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9.-]+", prompt)
    capital = [word for word in words[1:] if word[0].isupper()]
    return max(capital or words, key=len)


class _StandIn(BaseHTTPRequestHandler):
    """One tool call -- `ow_query` where offered, else `Grep` -- then an answer from its result."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- the base's name
        del format, args

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        messages = body["messages"]
        tools = {tool["function"]["name"]: tool["function"] for tool in body.get("tools", [])}
        results = [m for m in messages if m["role"] == "tool"]
        prompt = next(m["content"] for m in messages if m["role"] == "user")
        if body.get("tool_choice") != "none" and not results:
            if "mcp__omniweave__ow_query" in tools:
                name = "mcp__omniweave__ow_query"
                argument = tools[name]["parameters"]["required"][0]
                call = {argument: prompt}
            else:
                name, call = "Grep", {"pattern": _keyword(prompt), "output_mode": "content"}
            message = {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": name, "arguments": json.dumps(call)}}
                ],
            }  # fmt: skip
        else:
            text = results[-1]["content"] if results else ""
            found = text.strip() and "No matches" not in text
            message = {"content": f"From the documents: {text[:800]}" if found else "NOT FOUND"}
        raw = json.dumps({"choices": [{"message": message}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _run(tmp_path: Path, *argv: str) -> dict[str, object]:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    report = tmp_path / f"report-{len(list(tmp_path.glob('report-*')))}.json"
    done = run_captured(
        (
            sys.executable, str(SCRIPT), "--tasks", "personal_archive", "--scale", "quick",
            "--provider", "openai", "--model", "stand-in-1", "--workers", "3",
            "--cache", str(tmp_path / "cache"), "--cassettes", str(tmp_path / "cassettes"),
            "--json", str(report), *argv,
        ),
        stdin=b"",
        cwd=str(tmp_path),
        env=keep,
        timeout_s=TIMEOUT_S,
    )  # fmt: skip
    printed = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert done.returncode == 0, printed[-4000:]
    return json.loads(report.read_text(encoding="utf-8"))


def test_a_local_model_records_the_run_and_a_replay_needs_no_model_at_all(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        recorded = _run(tmp_path, "--record", "--base-url", base_url)
    finally:
        server.shutdown()
        server.server_close()
    replayed = _run(tmp_path, "--cassette", "required")

    ledger = recorded["cassette_ledger"]
    assert isinstance(ledger, dict)
    assert ledger["recorded"] == ledger["live_calls"] > 0
    assert replayed["cassette_ledger"] == {
        "hits": ledger["recorded"],
        "recorded": 0,
        "live_calls": 0,
    }
    assert replayed["outcomes"] == recorded["outcomes"]
    outcomes = recorded["outcomes"]
    assert isinstance(outcomes, list)
    assert {(o["arm"], o["task"]) for o in outcomes} == {
        (arm, task)
        for arm in ("omniweave", "control")
        for task in (
            "home-cite-rent-increase", "home-cite-flood", "home-ret-dental", "home-ret-harrow",
            "home-abs-passport", "home-abs-pet", "home-dmg-refund", "home-dmg-ldl",
        )
    }  # fmt: skip
    #  D640 and D641: `mask_format` and `chaos` are built, so both damaged tasks of this corpus run
    #  over their own damaged corpora, and nothing of it is held back.
    assert recorded["unmeasured"] == []
    assert recorded["scale"] == "quick"
