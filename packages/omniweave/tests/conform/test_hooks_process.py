"""`python -m omniweave hook <event>` as the host runs it: a real child, piped stdio, exit 0.

`conform` rather than `unit` because it spawns processes, which 13-quality.md section 2.7 puts in
this tier. Here the process is the whole claim: D431 is about what a child's stdio encoding is when
its stdio are pipes, and no in-process test can observe that.

**The control is the point.** `test_the_obvious_hook_exits_1_on_its_own_briefing` runs the naive
version -- `print()` of the same JSON -- in the same environment and asserts it fails, so the fix
is measured against the failure it fixes rather than against an assumption. It is skipped where the
child's stdout is already UTF-8, because there the naive version works and there is nothing to show.

Every child runs with `PYTHONUTF8` and `PYTHONIOENCODING` removed from its environment: those two
belong to the user's machine, and a hook that only works when a user happened to set one is a hook
that works on the developer's machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from omniweave.hooks.envelope import session_key
from omniweave.hooks.main import WORDS
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, append

pytestmark = pytest.mark.conform

SESSION = {"session_id": "conform-1"}
CORPUS = "契約"  # two CJK characters, neither of which cp1252 can encode
TIMEOUT_S = 60


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    return tmp_path


def _hook(word: str, payload: bytes, *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 -- argv is a tuple of this interpreter and literals
        (sys.executable, "-m", "omniweave", "hook", word),
        input=payload,
        capture_output=True,
        cwd=cwd,
        env=_env(),
        timeout=TIMEOUT_S,
        check=False,
    )


def _child_stdout_encoding() -> str:
    probe = subprocess.run(
        (sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdout.encoding.encode())"),
        capture_output=True,
        env=_env(),
        timeout=TIMEOUT_S,
        check=True,
    )
    return probe.stdout.decode("ascii").lower().replace("-", "")


def _seed(project: Path) -> None:
    append(
        project / CONTROL_DIR / SESSIONS_DIR,
        session_key(SESSION),
        {"kind": "corpus", "corpus": CORPUS, "version": 3, "stale": 0},
        at_ns=time.time_ns() - 1,
    )


def test_a_non_cp1252_briefing_reaches_the_host_as_utf8_json(tmp_path: Path) -> None:
    """D431, end to end: the one hook that speaks, speaking a character the code page cannot."""
    project = _project(tmp_path)
    _seed(project)

    done = _hook("session-start", json.dumps({**SESSION, "source": "resume"}).encode(), cwd=project)

    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert done.stderr == b""
    body = json.loads(done.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert body["hookEventName"] == "SessionStart"
    assert f"{CORPUS}@3" in body["additionalContext"]


def test_the_obvious_hook_exits_1_on_its_own_briefing(tmp_path: Path) -> None:
    """The control: `print()` of the same emission, same environment, same pipes."""
    if _child_stdout_encoding() in {"utf8", "utf_8"}:
        pytest.skip("the child's stdout is already UTF-8 here; the naive hook works")
    emission = json.dumps({"additionalContext": f"{CORPUS}@3"}, ensure_ascii=False)

    naive = subprocess.run(  # noqa: S603
        (sys.executable, "-c", f"print({emission!r})"),
        capture_output=True,
        cwd=tmp_path,
        env=_env(),
        timeout=TIMEOUT_S,
        check=False,
    )

    assert naive.returncode == 1
    assert b"UnicodeEncodeError" in naive.stderr


def test_a_non_ascii_prompt_is_read_without_error_or_output(tmp_path: Path) -> None:
    """The front-load is silent without probes; what is asserted is that the bytes did not crash."""
    payload = json.dumps({**SESSION, "prompt": f"what does {CORPUS}.pdf say?"}, ensure_ascii=False)

    done = _hook("user-prompt-submit", payload.encode("utf-8"), cwd=_project(tmp_path))

    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


@pytest.mark.parametrize("word", [*WORDS, "prompt", "bogus", ""])
def test_every_word_exits_0_and_prints_nothing_or_one_json_object(
    tmp_path: Path, word: str
) -> None:
    payload = json.dumps(
        {**SESSION, "source": "compact", "prompt": "x", "tool_input": {"file_path": "a.md"}}
    ).encode()

    done = _hook(word, payload, cwd=_project(tmp_path))

    assert done.returncode == 0
    assert done.stderr == b""
    if done.stdout:
        assert isinstance(json.loads(done.stdout.decode("utf-8")), dict)


@pytest.mark.parametrize(
    "stdin",
    [b"", b"\xff\xfe\xfd garbage", b"[1,2,3]", b"[" * 100_000],
    #  Explicit ids: pytest puts the node id in `PYTEST_CURRENT_TEST`, and 100 KB of `[` exceeds
    #  the 32,767-character limit Windows sets on one environment variable.
    ids=["empty", "undecodable", "array", "recursion"],
)
def test_garbage_on_stdin_is_still_exit_0(tmp_path: Path, stdin: bytes) -> None:
    done = _hook("session-start", stdin, cwd=_project(tmp_path))

    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


def test_every_other_root_is_refused_with_exit_70(tmp_path: Path) -> None:
    done = subprocess.run(
        (sys.executable, "-m", "omniweave", "query", "x"),
        capture_output=True,
        cwd=tmp_path,
        env=_env(),
        timeout=TIMEOUT_S,
        check=False,
    )

    assert done.returncode == 70
    assert b"not dispatched" in done.stderr
