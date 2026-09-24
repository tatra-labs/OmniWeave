"""`ow hook <event>` in-process: words, bytes, the TTY order, settle-after-flush, what is unwired.

**The sharpest test is `test_a_non_ascii_briefing_leaves_as_utf8_bytes_whatever_the_code_page`.**
D431 measured that a piped child on Windows gets cp1252 and that `print()` of a briefing with one
non-cp1252 character exits 1. This suite drives `main()` with byte streams so the claim is exact:
the bytes written are the UTF-8 encoding of `emission()`'s string, and nothing in between consults a
code page. The same claim as a real process is `tests/conform/test_hooks_process.py`.

`test_g26s_word_and_the_transcripts_word_reach_the_same_handler` is D432: the gated command and the
printed command must not be two different code paths, one of which is the cheapest silent exit.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks import main as hook_main
from omniweave.hooks.envelope import EVENTS, Advice, Outcome, session_key
from omniweave.hooks.main import (
    ALIASES,
    HOOK_WORD,
    WORDS,
    event_of,
    handler_for,
    kebab,
    main,
    read_payload,
    unwired,
    write_stdout,
)
from omniweave.hooks.posttool import queue_key, read_lease
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR, append, journal_paths, read

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conftest import PlanDocs

SESSION: Mapping[str, Any] = {"session_id": "abc-123"}
KEY: str = session_key(SESSION)
EDIT: Mapping[str, Any] = {"tool_input": {"file_path": "docs/policy.md"}}


class _Clock:
    def __init__(self, now: int) -> None:
        self._now = now

    def monotonic_ns(self) -> int:
        return self._now

    def wall_ns(self) -> int:
        return self._now


class _Refusing(io.BytesIO):
    """A stdout whose host has gone away: every write raises."""

    def write(self, _data: Any) -> int:
        raise BrokenPipeError


class _Blocking(io.BytesIO):
    """A stdin that must never be read. Reading it is the TTY bug."""

    def read(self, _size: int | None = -1) -> bytes:
        raise AssertionError("stdin was read on a TTY")


def _project(tmp_path: Path) -> Path:
    """A directory `sessions_dir()` resolves: an `omniweave.toml` under a `.git` root."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    return tmp_path


def _sessions(project: Path) -> Path:
    return project / CONTROL_DIR / SESSIONS_DIR


def _invoke(
    word: str,
    payload: bytes,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    tty: bool = False,
    stdout: io.BytesIO | None = None,
) -> tuple[Outcome, bytes]:
    out = io.BytesIO() if stdout is None else stdout
    outcome = main(
        [word],
        stdin=io.BytesIO(payload),
        stdout=out,
        env={} if env is None else env,
        clock=_Clock(time.time_ns()),
        cwd=cwd,
        tty=tty,
        pid=4242,
    )
    return outcome, (b"" if isinstance(out, _Refusing) else out.getvalue())


# ---------------------------------------------------------------------------------------------
# The words. D432.
# ---------------------------------------------------------------------------------------------


def test_the_words_are_derived_from_the_six_events_and_cover_all_of_them() -> None:
    assert set(WORDS.values()) == set(EVENTS)
    assert WORDS == {
        "session-start": "SessionStart",
        "pre-compact": "PreCompact",
        "user-prompt-submit": "UserPromptSubmit",
        "pre-tool-use": "PreToolUse",
        "post-tool-use": "PostToolUse",
        "session-end": "SessionEnd",
    }


@pytest.mark.parametrize(
    ("name", "word"),
    [("UserPromptSubmit", "user-prompt-submit"), ("A", "a"), ("ABTest", "abtest")],
)
def test_kebab(name: str, word: str) -> None:
    assert kebab(name) == word


def test_the_five_words_18_prints_are_exactly_what_this_derives(plan: PlanDocs) -> None:
    plan.require()
    printed = {
        line.split()[0]: line.split()[3]
        for line in plan.text("18-api-sketch.md").split("\n")
        if " hook " in line and "resolved" in line and line.split()[0] in EVENTS
    }

    assert len(printed) == 5
    for event, word in printed.items():
        assert WORDS[word] == event


def test_g26_gates_a_word_no_transcript_prints(plan: PlanDocs) -> None:
    """D432: `ow hook prompt` is gated; `ow hook user-prompt-submit` is what 18 prints."""
    plan.require()
    designed = [name for name in plan.documents() if "/" not in name]
    gated = plan.grep(r"ow hook prompt\b", documents=designed)
    printed = plan.grep(r"ow hook user-prompt-submit", documents=designed)

    assert len(gated) == 13
    assert len({hit.document for hit in gated}) == 7
    assert [hit.document for hit in printed] == ["18-api-sketch.md"]


def test_the_alias_set_is_closed_at_the_one_spelling_the_plan_uses() -> None:
    assert dict(ALIASES) == {"prompt": "UserPromptSubmit"}
    assert not set(ALIASES) & set(WORDS)


def test_g26s_word_and_the_transcripts_word_reach_the_same_handler(tmp_path: Path) -> None:
    project = _project(tmp_path)
    payload = json.dumps({"prompt": "what is the notice period?"}).encode()

    gated, _ = _invoke("prompt", payload, cwd=project)
    printed, _ = _invoke("user-prompt-submit", payload, cwd=project)

    assert gated.counters == printed.counters
    assert gated.counters[0].startswith("ow-hook-ups-")
    assert "noop-event" not in gated.counters[0]


@pytest.mark.parametrize("word", ["", "bogus", "UserPromptSubmit", "Prompt", "session_start"])
def test_an_unknown_word_is_a_counted_silent_exit(tmp_path: Path, word: str) -> None:
    outcome, out = _invoke(word, b"{}", cwd=_project(tmp_path))

    assert event_of(word) == ""
    assert out == b""
    assert outcome.counters == ("ow-hook-unknown-noop-event",)
    assert outcome.exit_code() == 0


# ---------------------------------------------------------------------------------------------
# Bytes in. D431.
# ---------------------------------------------------------------------------------------------


def test_a_utf8_payload_round_trips_exactly() -> None:
    text = "Kündigungsfrist → 契約.pdf"

    assert (
        read_payload(io.BytesIO(json.dumps({"prompt": text}, ensure_ascii=False).encode()))[
            "prompt"
        ]
        == text
    )


def test_a_bom_and_a_trailing_crlf_are_what_powershell_sends_and_are_accepted() -> None:
    """Measured: PowerShell with a UTF-8 `$OutputEncoding` prepends a BOM and appends CRLF."""
    raw = b'\xef\xbb\xbf{"prompt":"x\xe2\x86\x92y"}\r\n'

    assert read_payload(io.BytesIO(raw)) == {"prompt": "x→y"}


def test_utf16_is_detected_by_json_itself() -> None:
    raw = json.dumps({"prompt": "→"}).encode("utf-16")

    assert read_payload(io.BytesIO(raw)) == {"prompt": "→"}


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[1, 2]", b'"a string"', b"\xff\xfe\xfd", b'{"a": 1', b"null"],
)
def test_anything_but_a_json_object_is_an_empty_payload(raw: bytes) -> None:
    assert read_payload(io.BytesIO(raw)) == {}


def test_nesting_deep_enough_to_recurse_is_an_empty_payload_and_not_an_escape() -> None:
    """Measured: `json.loads` raises `RecursionError`, which is not a `ValueError`."""
    assert read_payload(io.BytesIO(b"[" * 100_000)) == {}
    assert read_payload(io.BytesIO(b'{"a":' * 100_000)) == {}


def test_no_stdin_at_all_is_an_empty_payload() -> None:
    assert read_payload(None) == {}


def test_a_stdin_that_raises_is_an_empty_payload() -> None:
    class _Broken(io.BytesIO):
        def read(self, _size: int | None = -1) -> bytes:
            raise OSError

    assert read_payload(_Broken()) == {}


# ---------------------------------------------------------------------------------------------
# Bytes out. D431, and 10:2004's settle-after-flush.
# ---------------------------------------------------------------------------------------------


def test_write_stdout_is_utf8_and_reports_success() -> None:
    out = io.BytesIO()

    assert write_stdout(out, "→ 契約")
    assert out.getvalue() == "→ 契約".encode()


def test_nothing_to_say_writes_nothing_and_is_not_a_success() -> None:
    out = io.BytesIO()

    assert not write_stdout(out, "")
    assert out.getvalue() == b""


def test_a_closed_pipe_is_a_failed_write_and_never_raises() -> None:
    assert not write_stdout(_Refusing(), "text")
    assert not write_stdout(None, "text")


def test_a_lone_surrogate_is_a_failed_write_rather_than_a_crash() -> None:
    """An undecodable file name surfaces as a lone surrogate; strict UTF-8 refuses it."""
    out = io.BytesIO()

    assert not write_stdout(out, "bad \udcff name")


def test_a_non_ascii_briefing_leaves_as_utf8_bytes_whatever_the_code_page(tmp_path: Path) -> None:
    """D431. The bytes on stdout are `emission()`'s string in UTF-8 -- never a code page."""
    project = _project(tmp_path)
    root = _sessions(project)
    append(
        root,
        KEY,
        {"kind": "corpus", "corpus": "契約", "version": 3, "stale": 0},
        at_ns=time.time_ns() - 1,
    )

    outcome, out = _invoke(
        "session-start", json.dumps({**SESSION, "source": "resume"}).encode(), cwd=project
    )

    assert outcome.stdout
    assert out == outcome.stdout.encode("utf-8")
    body = json.loads(out.decode("utf-8"))["hookSpecificOutput"]
    assert body["hookEventName"] == "SessionStart"
    assert "契約@3" in body["additionalContext"]


def test_settle_runs_only_after_the_bytes_are_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _handler(*_args: Any, **_kwargs: Any) -> Any:
        return lambda _payload: Advice(text="hi", counter="t", after_emit=lambda: calls.append("s"))

    monkeypatch.setattr(hook_main, "handler_for", _handler)

    outcome, out = _invoke("user-prompt-submit", b"{}", cwd=Path.cwd())
    assert out == outcome.stdout.encode()
    assert calls == ["s"]

    calls.clear()
    _invoke("user-prompt-submit", b"{}", cwd=Path.cwd(), stdout=_Refusing())
    assert calls == []


# ---------------------------------------------------------------------------------------------
# The TTY order and the kill switch.
# ---------------------------------------------------------------------------------------------


def test_a_tty_is_never_read_and_the_silence_is_counted(tmp_path: Path) -> None:
    """10:1996's TTY switch must fire BEFORE the read; `run()` receives the payload too late."""
    out = io.BytesIO()
    outcome = main(
        ["session-end"],
        stdin=_Blocking(),
        stdout=out,
        env={},
        clock=_Clock(time.time_ns()),
        cwd=_project(tmp_path),
        tty=True,
        pid=1,
    )

    assert outcome.counters == ("ow-hook-end-noop-tty",)
    assert out.getvalue() == b""


def test_the_kill_switch_writes_nothing_under_sessions(tmp_path: Path) -> None:
    project = _project(tmp_path)

    outcome, _ = _invoke(
        "session-end", json.dumps(SESSION).encode(), cwd=project, env={"OMNIWEAVE_HOOK": "0"}
    )

    assert outcome.counters == ("ow-hook-end-noop-killed",)
    assert not (project / CONTROL_DIR).exists()


# ---------------------------------------------------------------------------------------------
# Wiring: every event reaches its handler, with the seams this build has.
# ---------------------------------------------------------------------------------------------


def test_every_event_has_a_handler_and_none_fails(tmp_path: Path) -> None:
    project = _project(tmp_path)
    payload = json.dumps({**SESSION, "source": "compact", "prompt": "x", **EDIT}).encode()

    for word in WORDS:
        outcome, _ = _invoke(word, payload, cwd=project)
        assert outcome.failed == "", word
        assert not outcome.counters[0].endswith("noop-failure"), word
        assert not outcome.counters[0].endswith("noop-event"), word


def test_post_tool_use_queues_the_edit_and_counts_the_unwired_drain(tmp_path: Path) -> None:
    """D433: `spawn=None` -- the counter says the drain did not happen, and the queue keeps it."""
    project = _project(tmp_path)
    root = _sessions(project)

    outcome, _ = _invoke("post-tool-use", json.dumps({**SESSION, **EDIT}).encode(), cwd=project)

    assert outcome.counters == ("ow-hook-posttool-noop-spawn-failed",)
    assert read_lease(root) is None
    queued = read(root, queue_key(KEY), now_ns=time.time_ns()).records
    assert [record["path"] for record in queued] == ["docs/policy.md"]


def test_session_end_journals_the_end_and_leaves_no_lease(tmp_path: Path) -> None:
    project = _project(tmp_path)
    root = _sessions(project)

    _invoke("post-tool-use", json.dumps({**SESSION, **EDIT}).encode(), cwd=project)
    outcome, _ = _invoke(
        "session-end", json.dumps({**SESSION, "reason": "exit"}).encode(), cwd=project
    )

    assert outcome.counters == ("ow-hook-end-noop-spawn-failed",)
    assert read_lease(root) is None
    assert journal_paths(root, KEY)[0].is_file()


def test_no_omniweave_toml_anywhere_is_d403s_silent_deployment(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    for word in WORDS:
        outcome, out = _invoke(word, json.dumps({**SESSION, **EDIT}).encode(), cwd=tmp_path)
        assert out == b"", word
        assert outcome.failed == "", word
    assert not (tmp_path / CONTROL_DIR).exists()


def test_the_sessions_walk_runs_inside_the_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A walk that raised outside `run()` would be a failure path that is not a silent exit 0."""

    def _explodes(_cwd: Path) -> Path:
        raise PermissionError

    monkeypatch.setattr(hook_main, "sessions_dir", _explodes)

    outcome, out = _invoke("session-end", json.dumps(SESSION).encode(), cwd=tmp_path)

    assert out == b""
    assert outcome.counters == ("ow-hook-end-noop-failure",)
    assert outcome.failed == "PermissionError"


def test_a_cwd_that_does_not_exist_is_a_quiet_counter(tmp_path: Path) -> None:
    bound = handler_for(
        "SessionEnd", cwd=tmp_path / "missing", env={}, clock=_Clock(0), pid=1, argv0=""
    )

    assert bound(SESSION).counter == "noop-no-key"


def test_the_drain_stays_unwired_until_something_dispatches_ingest() -> None:
    """D433. When `ingest` joins `DISPATCHED`, this fails -- and the spawn should land with it.

    `install` and `uninstall` joined in W7.5h; neither is the drain."""
    import omniweave.__main__ as launcher  # noqa: PLC0415

    assert frozenset({HOOK_WORD, "install", "uninstall"}) == launcher.DISPATCHED
    assert "ingest" not in launcher.DISPATCHED


# ---------------------------------------------------------------------------------------------
# `python -m omniweave`, in-process.
# ---------------------------------------------------------------------------------------------


def test_every_other_root_is_refused_with_internal_errors_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import omniweave.__main__ as launcher  # noqa: PLC0415
    from omniweave_core.errors import InternalError  # noqa: PLC0415

    assert launcher.main(["query", "x"]) == InternalError.EXIT == 70
    assert launcher.main([]) == InternalError.EXIT
    assert launcher.main(["契約"]) == InternalError.EXIT
    assert "not dispatched" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_never_touches_text_mode_stdio() -> None:
    """D431 as a source property: no `print`, no `sys.stdin.read`, no `sys.stdout.write`."""
    import ast  # noqa: PLC0415

    tree = ast.parse(Path(str(hook_main.__file__)).read_text(encoding="utf-8"))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}

    assert "print" not in calls
    assert not {"sys.stdin.read", "sys.stdout.write", "sys.stdin.readline"} & calls


def test_the_module_imports_no_subprocess_and_core_only_for_the_clock() -> None:
    import ast  # noqa: PLC0415

    tree = ast.parse(Path(str(hook_main.__file__)).read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) if node.module}

    assert "subprocess" not in names
    assert {name for name in names if name.startswith("omniweave_core")} == {"omniweave_core.clock"}


def test_the_unwired_list_names_what_this_entry_point_runs_against() -> None:
    stated = unwired()

    assert len(stated) == 5
    for entry in ("D431", "D432", "D433", "D397"):
        assert any(entry in item for item in stated), entry
